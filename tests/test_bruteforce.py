"""Brute-force cross check of the exact equivalence engine.

For many random pairs of small rational stochastic procedures we compare
the basis-expansion verdict against exhaustive enumeration of all words
up to a depth bound, and (for non-equivalent pairs) check that the
reported witness is truly the shortest / ASCII-smallest one.
"""
import itertools
import os
import random
import sys
from fractions import Fraction

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))
from equivalence import build_procedure, compare_procedures  # noqa: E402


def rand_dist(rng, n):
    # random rational distribution via small denominators
    nums = [rng.randint(0, 4) for _ in range(n)]
    while sum(nums) == 0:
        nums = [rng.randint(0, 4) for _ in range(n)]
    s = sum(nums)
    return [Fraction(x, s) for x in nums]


def rand_spec(rng, n, k, safe_n):
    states = [f"S{i}" for i in range(n)]
    cmds = [chr(ord("a") + i) for i in range(k)]
    spec = {
        "states": states,
        "initial": [f"{x.numerator}/{x.denominator}" for x in rand_dist(rng, n)],
        "safe": rng.sample(states, safe_n),
        "commands": cmds,
        "matrices": {
            c: [[f"{x.numerator}/{x.denominator}" for x in rand_dist(rng, n)] for _ in range(n)]
            for c in cmds
        },
    }
    return spec


def brute_force(sa, sb, depth):
    """Return the minimal counterexample word up to `depth`, else None."""
    cmds = sorted(set(sa.commands) | set(sb.commands))
    pa = sa.initial
    pb = sb.initial
    g_a = [Fraction(1) if s else 0 for s in sa.safe]
    g_b = [Fraction(1) if s else 0 for s in sb.safe]

    def safe(u, g):
        return sum(x * y for x, y in zip(u, g))

    def step(u, M, n):
        return tuple(sum(u[i] * M[i][j] for i in range(n)) for j in range(n))

    # BFS for minimal witness
    frontier = [("", tuple(pa), tuple(pb))]
    for d in range(depth + 1):
        nxt = []
        for word, u, v in frontier:
            if safe(u, g_a) != safe(v, g_b):
                return word
            for c in cmds:
                if c not in sa.matrices or c not in sb.matrices:
                    return word + c
                nxt.append((word + c, step(u, sa.matrices[c], sa.n), step(v, sb.matrices[c], sb.n)))
        frontier = nxt
    return None


def main():
    rng = random.Random(20260925)
    trials = 400
    mismatches = 0
    for t in range(trials):
        n = rng.randint(1, 3)
        k = rng.randint(1, 3)
        sa_spec = rand_spec(rng, n, k, rng.randint(1, n))
        sb_spec = rand_spec(rng, n, k, rng.randint(1, n))
        pa = build_procedure(sa_spec, "a")
        pb = build_procedure(sb_spec, "b")
        w = compare_procedures(pa, pb)
        bf = brute_force(pa, pb, depth=8)
        got = w.word if w is not None else None
        if (got is None) != (bf is None):
            # Only a real discrepancy if brute force (depth 8) disagrees:
            # engine non-None with bf None cannot happen if engine correct;
            # engine None with bf a witness also cannot.
            print("MISMATCH trial", t, "engine=", got, "brute=", bf)
            mismatches += 1
            continue
        if got is not None and got != bf:
            print("WITNESS ORDER MISMATCH trial", t, "engine=", repr(got), "brute=", repr(bf))
            mismatches += 1
    print(f"{trials} trials, {mismatches} mismatches")
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
