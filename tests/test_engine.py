"""Targeted engine tests: equivalent-by-construction pairs, edge cases,
validation errors, big rationals, termination on larger inputs.
"""
import os
import sys
from fractions import Fraction

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))
from equivalence import (  # noqa: E402
    ValidationError,
    build_procedure,
    compare_procedures,
    parse_fraction,
)


def spec(states, initial, safe, commands, matrices):
    return {"states": states, "initial": initial, "safe": safe,
            "commands": commands, "matrices": matrices}


def F(s):
    return s


def test_identical_single_command():
    s = spec(["0", "1"], ["1", "0"], ["0"], ["c"],
             {"c": [["1/3", "2/3"], ["1/4", "3/4"]]})
    p = build_procedure(s, "a")
    q = build_procedure(s, "b")
    assert compare_procedures(p, q) is None


def test_lumped_equivalence():
    # B refines state t of A into t1,t2 with identical outgoing rows and
    # identical incoming column weights; aggregated process equals A.
    A = spec(["s", "t"], ["1", "0"], ["s"], ["x"],
             {"x": [["1/3", "2/3"], ["1/3", "2/3"]]})
    B = spec(["s", "t1", "t2"], ["1", "0", "0"], ["s"], ["x"],
             {"x": [
                 ["1/3", "1/3", "1/3"],
                 ["1/3", "2/3", "0"],
                 ["1/3", "0", "2/3"],
             ]})
    pa, pb = build_procedure(A, "a"), build_procedure(B, "b")
    assert compare_procedures(pa, pb) is None


def test_initial_distribution_difference_empty_word():
    A = spec(["s", "t"], ["1", "0"], ["s"], ["x"],
             {"x": [["1", "0"], ["0", "1"]]})
    B = spec(["s", "t"], ["1/2", "1/2"], ["s"], ["x"],
             {"x": [["1", "0"], ["0", "1"]]})
    w = compare_procedures(build_procedure(A, "a"), build_procedure(B, "b"))
    assert w is not None and w.word == ""
    assert w.final_a == Fraction(1) and w.final_b == Fraction(1, 2)
    assert w.difference == Fraction(1, 2)


def test_shortest_and_ascii_ordering():
    # both letters a and b differ, shorter word "a" must win
    A = spec(["s", "t"], ["1", "0"], ["s"], ["a", "b"],
             {"a": [["1/2", "1/2"], ["1/2", "1/2"]],
              "b": [["1/2", "1/2"], ["1/2", "1/2"]]})
    B = spec(["s", "t"], ["1", "0"], ["s"], ["a", "b"],
             {"a": [["0", "1"], ["0", "1"]],
              "b": [["0", "1"], ["0", "1"]]})
    w = compare_procedures(build_procedure(A, "a"), build_procedure(B, "b"))
    assert w.word == "a"


def test_witness_needs_long_word():
    # differences only emerge after two letters: b vs a ordering check
    A = spec(["0", "1", "2"], ["1", "0", "0"], ["2"], ["a", "b"],
             {"a": [["0", "1", "0"], ["0", "0", "1"], ["1", "0", "0"]],
              "b": [["1", "0", "0"], ["0", "1", "0"], ["0", "0", "1"]]})
    # B identical except under command 'a', state 1 loops instead of going to 2
    B = spec(["0", "1", "2"], ["1", "0", "0"], ["2"], ["a", "b"],
             {"a": [["0", "1", "0"], ["0", "1", "0"], ["1", "0", "0"]],
              "b": [["1", "0", "0"], ["0", "1", "0"], ["0", "0", "1"]]})
    w = compare_procedures(build_procedure(A, "a"), build_procedure(B, "b"))
    assert w.word == "aa", w.word
    # stepwise distributions present for each side
    assert len(w.steps_a) == 3 and len(w.steps_b) == 3


def test_missing_command_is_witness():
    A = spec(["s"], ["1"], ["s"], ["a", "b"], {"a": [["1"]], "b": [["1"]]})
    B = spec(["s"], ["1"], ["s"], ["a"], {"a": [["1"]]})
    w = compare_procedures(build_procedure(A, "a"), build_procedure(B, "b"))
    assert w.word == "b" and (w.final_a is None or w.final_b is None)


def test_bad_fraction_and_row_sum_and_safe_errors():
    bad = spec(["s", "t"], ["1/0", "x"], ["s"], ["c"],
               {"c": [["1/2", "1/3"], ["0", "1"]]})
    try:
        build_procedure(bad, "a")
        assert False, "should raise"
    except ValidationError as e:
        areas = {(x["area"], x.get("index")) for x in e.errors}
        assert ("initial", 0) in areas  # zero denominator
        assert ("initial", 1) in areas  # unparsable
        msgs = " ".join(x["message"] for x in e.errors)
        assert "分母不能为零" in msgs

    # dangling safe state + no valid safe state
    bad2 = spec(["s"], ["1"], ["ghost"], ["c"], {"c": [["1"]]})
    try:
        build_procedure(bad2, "a")
        assert False
    except ValidationError as e:
        assert any(x["area"] == "safe" for x in e.errors)

    # row sum != 1 locates the row
    bad3 = spec(["s", "t"], ["1", "0"], ["s"], ["c"],
                {"c": [["1/2", "1/2"], ["1/3", "1/3"]]})
    try:
        build_procedure(bad3, "a")
        assert False
    except ValidationError as e:
        loc = [x for x in e.errors if x["area"] == "matrices"]
        assert loc and loc[0]["row"] == 1


def test_negative_probability():
    bad = spec(["s", "t"], ["1", "0"], ["s"], ["c"],
               {"c": [["-1/2", "3/2"], ["0", "1"]]})
    try:
        build_procedure(bad, "a")
        assert False
    except ValidationError as e:
        assert any("不能为负" in x["message"] for x in e.errors)


def test_huge_rationals_exact():
    # denominators that must not be compared by float
    big1 = "10**40"  # not legal syntax; use plain huge ints instead
    N = 10 ** 40
    eps = Fraction(1, N)
    A = spec(["s", "t"], ["1", "0"], ["s"], ["c"],
             {"c": [[f"{N - 1}/{N}", f"1/{N}"], ["0", "1"]]})
    B = spec(["s", "t"], ["1", "0"], ["s"], ["c"],
             {"c": [[f"{N - 2}/{N}", f"2/{N}"], ["0", "1"]]})
    w = compare_procedures(build_procedure(A, "a"), build_procedure(B, "b"))
    assert w.word == "c"
    assert w.difference == Fraction(1, N)


def test_large_procedure_terminates_fast():
    import time
    n, k = 20, 8

    def rand_mat():
        rows = []
        for _ in range(n):
            nums = list(range(1, n + 1))
            s = sum(nums)
            rows.append([Fraction(x, s) for x in nums])
        return [[f"{x.numerator}/{x.denominator}" for x in r] for r in rows]

    states = [f"q{i}" for i in range(n)]
    cmds = [chr(ord("a") + i) for i in range(k)]
    s = spec(states, ["1"] + ["0"] * (n - 1), states[:1], cmds,
             {c: rand_mat() for c in cmds})
    t0 = time.time()
    pa = build_procedure(s, "a")
    pb = build_procedure(s, "b")
    assert compare_procedures(pa, pb) is None
    assert time.time() - t0 < 10


def test_parse_fraction_variants():
    assert parse_fraction("2/4") == Fraction(1, 2)
    assert parse_fraction(" 3 ") == Fraction(3)
    assert parse_fraction("-1/-2") == Fraction(1, 2)
    for bad in ["1/0", "a/b", "", "1/2/3"]:
        try:
            parse_fraction(bad)
            assert False, bad
        except ValueError:
            pass


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print(f"{len(fns)} tests passed")
