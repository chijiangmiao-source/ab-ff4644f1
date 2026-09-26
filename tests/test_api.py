"""API smoke + behaviour tests through the real FastAPI ASGI stack."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def proc(states, initial, safe, commands, matrices):
    return {
        "states": states,
        "initial": initial,
        "safe": safe,
        "commands": commands,
        "matrices": matrices,
    }


def test_health_and_index():
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    page = client.get("/")
    assert page.status_code == 200 and "规程等价复核" in page.text


def test_equivalent_pair():
    A = proc(["s", "t"], ["1", "0"], ["s"], ["x"],
             {"x": [["1/3", "2/3"], ["1/3", "2/3"]]})
    B = proc(["s", "t1", "t2"], ["1", "0", "0"], ["s"], ["x"],
             {"x": [["1/3", "1/3", "1/3"],
                    ["1/3", "2/3", "0"],
                    ["1/3", "0", "2/3"]]})
    r = client.post("/api/compare", json={"a": A, "b": B})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] and data["equivalent"]


def test_counterexample_pair():
    A = proc(["safe", "risk"], ["1", "0"], ["safe"], ["a", "b"],
             {"a": [["1/2", "1/2"], ["1/2", "1/2"]],
              "b": [["1/2", "1/2"], ["1/2", "1/2"]]})
    B = proc(["safe", "risk"], ["1", "0"], ["safe"], ["a", "b"],
             {"a": [["1/2", "1/2"], ["1/2", "1/2"]],
              "b": [["1/2", "1/2"], ["0", "1"]]})
    r = client.post("/api/compare", json={"a": A, "b": B})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] and not data["equivalent"]
    w = data["witness"]
    assert w["word"] == "ab" and w["length"] == 2
    assert w["finalA"] == "1/2" and w["finalB"] == "1/4"
    assert w["difference"] == "1/4"
    # stepwise distributions on both sides, exact fractions
    assert [s["safeA"] for s in w["steps"]] == ["1", "1/2", "1/2"]
    assert [s["safeB"] for s in w["steps"]] == ["1", "1/2", "1/4"]
    assert w["statesA"] == ["safe", "risk"]


def test_validation_row_sum_located():
    bad = proc(["s", "t"], ["1", "0"], ["s"], ["c"],
               {"c": [["1/2", "1/2"], ["1/3", "1/3"]]})
    ok = proc(["s", "t"], ["1", "0"], ["s"], ["c"],
              {"c": [["1", "0"], ["0", "1"]]})
    r = client.post("/api/compare", json={"a": bad, "b": ok})
    assert r.status_code == 422
    errs = r.json()["errors"]
    mat = [e for e in errs if e["area"] == "matrices"]
    assert mat and mat[0]["side"] == "a"
    assert mat[0]["command"] == "c" and mat[0]["row"] == 1
    assert "1" in mat[0]["message"]


def test_validation_bad_fraction_and_missing_safe():
    bad = proc(["s", "t"], ["1/0", "0"], [], ["c"],
               {"c": [["x", "y"], ["0", "1"]]})
    r = client.post("/api/compare", json={"a": bad, "b": bad})
    assert r.status_code == 422
    errs = r.json()["errors"]
    areas = {e["area"] for e in errs}
    assert "initial" in areas and "matrices" in areas and "safe" in areas
    # initial error locates the offending index
    init0 = [e for e in errs if e["area"] == "initial" and e.get("index") == 0]
    assert init0 and "分母不能为零" in init0[0]["message"]


def test_missing_command_counterexample():
    A = proc(["s"], ["1"], ["s"], ["a", "b"], {"a": [["1"]], "b": [["1"]]})
    B = proc(["s"], ["1"], ["s"], ["a"], {"a": [["1"]]})
    r = client.post("/api/compare", json={"a": A, "b": B})
    data = r.json()
    assert r.status_code == 200 and not data["equivalent"]
    w = data["witness"]
    assert w["word"] == "b"
    assert (w["finalA"] is None or w["finalB"] is None) and w["note"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print(f"{len(fns)} API tests passed")
