"""Acceptance entry point for the Compose ``verify`` service.

It runs entirely inside the application image and:

1. runs the exact-arithmetic engine unit tests;
2. cross-checks the decision engine against brute-force enumeration;
3. asserts the *shortest* counterexample on known cases (length and
   ASCII ordering), with exact final probabilities;
4. waits for the live HTTP API, then smoke-tests ``/health``, an
   equivalent pair, a counterexample pair and a 422 validation case;
5. exits 0 only if every check passes, non-zero otherwise (the Compose
   run returns this exact acceptance exit code).
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.equivalence import build_procedure, compare_procedures  # noqa: E402

BASE_URL = os.environ.get("APP_BASE_URL", "http://127.0.0.1:8080")

FAILURES = []


def check(name, cond, detail=""):
    print(("PASS" if cond else "FAIL"), "-", name, (":: " + detail) if detail and not cond else "")
    if not cond:
        FAILURES.append(name)


def proc(states, initial, safe, commands, matrices):
    return {"states": states, "initial": initial, "safe": safe,
            "commands": commands, "matrices": matrices}


# ---------------------------------------------------------------------------
# 1-3. direct engine checks (incl. shortest counterexamples)
# ---------------------------------------------------------------------------
def run_engine_checks():
    # shortest, ASCII-minimal witness that needs length 2
    A = proc(["0", "1", "2"], ["1", "0", "0"], ["2"], ["a", "b"],
             {"a": [["0", "1", "0"], ["0", "0", "1"], ["1", "0", "0"]],
              "b": [["1", "0", "0"], ["0", "1", "0"], ["0", "0", "1"]]})
    B = proc(["0", "1", "2"], ["1", "0", "0"], ["2"], ["a", "b"],
             {"a": [["0", "1", "0"], ["0", "1", "0"], ["1", "0", "0"]],
              "b": [["1", "0", "0"], ["0", "1", "0"], ["0", "0", "1"]]})
    w = compare_procedures(build_procedure(A, "a"), build_procedure(B, "b"))
    check("shortest witness length/order", w is not None and w.word == "aa",
          repr(w.word if w else None))
    check("witness exact final probabilities",
          w is not None and w.final_a == Fraction(1) and w.final_b == Fraction(0),
          f"{w.final_a if w else None} vs {w.final_b if w else None}")

    # genuinely equivalent (state refinement / strong lumpability)
    A2 = proc(["s", "t"], ["1", "0"], ["s"], ["x"],
              {"x": [["1/3", "2/3"], ["1/3", "2/3"]]})
    B2 = proc(["s", "t1", "t2"], ["1", "0", "0"], ["s"], ["x"],
              {"x": [["1/3", "1/3", "1/3"],
                     ["1/3", "2/3", "0"],
                     ["1/3", "0", "2/3"]]})
    check("lumped refinement is equivalent",
          compare_procedures(build_procedure(A2, "a"), build_procedure(B2, "b")) is None)

    # exactness: difference 1/10^40 must be detected exactly
    N = 10 ** 40
    A3 = proc(["s", "t"], ["1", "0"], ["s"], ["c"],
              {"c": [[f"{N - 1}/{N}", f"1/{N}"], ["0", "1"]]})
    B3 = proc(["s", "t"], ["1", "0"], ["s"], ["c"],
              {"c": [[f"{N - 2}/{N}", f"2/{N}"], ["0", "1"]]})
    w3 = compare_procedures(build_procedure(A3, "a"), build_procedure(B3, "b"))
    check("huge-denominator difference exact",
          w3 is not None and w3.difference == Fraction(1, N))


def run_unit_tests():
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    import test_engine  # noqa: E402

    fns = [v for k, v in sorted(vars(test_engine).items()) if k.startswith("test_")]
    for fn in fns:
        try:
            fn()
            check("unit " + fn.__name__, True)
        except Exception as exc:  # noqa: BLE001
            check("unit " + fn.__name__, False, repr(exc))


def run_bruteforce_crosscheck(trials=80):
    import random

    def rand_dist(rng, n):
        nums = [rng.randint(0, 4) for _ in range(n)]
        while sum(nums) == 0:
            nums = [rng.randint(0, 4) for _ in range(n)]
        s = sum(nums)
        return [Fraction(x, s) for x in nums]

    def rand_spec(rng, n, k):
        states = [f"S{i}" for i in range(n)]
        cmds = [chr(ord("a") + i) for i in range(k)]
        return {
            "states": states,
            "initial": [f"{x.numerator}/{x.denominator}" for x in rand_dist(rng, n)],
            "safe": rng.sample(states, rng.randint(1, n)),
            "commands": cmds,
            "matrices": {
                c: [[f"{x.numerator}/{x.denominator}" for x in rand_dist(rng, n)]
                    for _ in range(n)]
                for c in cmds
            },
        }

    def brute(sa, sb, depth=7):
        cmds = sa.commands

        def step(u, M, n):
            return tuple(sum(u[i] * M[i][j] for i in range(n)) for j in range(n))

        ga = [Fraction(1) if s else 0 for s in sa.safe]
        gb = [Fraction(1) if s else 0 for s in sb.safe]
        front = [("", tuple(sa.initial), tuple(sb.initial))]
        for _ in range(depth + 1):
            nxt = []
            for word, u, v in front:
                pa = sum(x * y for x, y in zip(u, ga))
                pb = sum(x * y for x, y in zip(v, gb))
                if pa != pb:
                    return word
                for c in cmds:
                    nxt.append((word + c, step(u, sa.matrices[c], sa.n),
                                step(v, sb.matrices[c], sb.n)))
            front = nxt
        return None

    rng = random.Random(20260926)
    bad = 0
    for _ in range(trials):
        n, k = rng.randint(1, 3), rng.randint(1, 3)
        sa = build_procedure(rand_spec(rng, n, k), "a")
        sb = build_procedure(rand_spec(rng, n, k), "b")
        got = compare_procedures(sa, sb)
        word = got.word if got else None
        bf = brute(sa, sb)
        if word != bf:
            bad += 1
    check(f"brute-force cross-check ({trials} random pairs)", bad == 0, f"{bad} mismatches")


# ---------------------------------------------------------------------------
# 4. live HTTP API smoke tests
# ---------------------------------------------------------------------------
def http(method, path, body=None, timeout=5):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE_URL + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def wait_for_api(deadline=60):
    t0 = time.time()
    while time.time() - t0 < deadline:
        try:
            status, body = http("GET", "/health")
            if status == 200 and body.get("status") == "ok":
                return True
        except Exception:  # noqa: BLE001
            time.sleep(1)
    return False


def run_api_smoke():
    check("live API /health reachable at " + BASE_URL, wait_for_api())

    eq_a = proc(["s", "t"], ["1", "0"], ["s"], ["x"],
                {"x": [["1/3", "2/3"], ["1/3", "2/3"]]})
    eq_b = proc(["s", "t1", "t2"], ["1", "0", "0"], ["s"], ["x"],
                {"x": [["1/3", "1/3", "1/3"],
                       ["1/3", "2/3", "0"],
                       ["1/3", "0", "2/3"]]})
    st, body = http("POST", "/api/compare", {"a": eq_a, "b": eq_b})
    check("API equivalent verdict", st == 200 and body.get("equivalent") is True, str(body)[:200])

    cx_a = proc(["safe", "risk"], ["1", "0"], ["safe"], ["a", "b"],
                {"a": [["1/2", "1/2"], ["1/2", "1/2"]],
                 "b": [["1/2", "1/2"], ["1/2", "1/2"]]})
    cx_b = proc(["safe", "risk"], ["1", "0"], ["safe"], ["a", "b"],
                {"a": [["1/2", "1/2"], ["1/2", "1/2"]],
                 "b": [["1/2", "1/2"], ["0", "1"]]})
    st, body = http("POST", "/api/compare", {"a": cx_a, "b": cx_b})
    w = body.get("witness", {})
    check("API shortest counterexample word",
          st == 200 and body.get("equivalent") is False and w.get("word") == "ab",
          str(w.get("word")))
    check("API witness exact probabilities",
          w.get("finalA") == "1/2" and w.get("finalB") == "1/4"
          and w.get("difference") == "1/4" and len(w.get("steps", [])) == 3,
          json.dumps(w)[:300])

    bad = proc(["s", "t"], ["1/0", "0"], [], ["c"],
               {"c": [["1/3", "1/3"], ["0", "1"]]})
    st, body = http("POST", "/api/compare", {"a": bad, "b": bad})
    areas = {e.get("area") for e in body.get("errors", [])}
    check("API 422 locates input errors",
          st == 422 and {"initial", "safe", "matrices"} <= areas, str(body)[:200])


def main():
    print("== acceptance verification ==")
    run_engine_checks()
    run_unit_tests()
    run_bruteforce_crosscheck()
    run_api_smoke()
    print("==============================")
    if FAILURES:
        print(f"ACCEPTANCE FAILED: {len(FAILURES)} check(s): {FAILURES}")
        return 1
    print("ACCEPTANCE PASSED: all checks green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
