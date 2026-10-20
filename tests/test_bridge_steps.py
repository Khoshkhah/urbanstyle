"""Steps 1 to 3 of a bridge are frozen (docs/notes/bridge-steps.md, "How a step is frozen"): the junction nodes, carriageway pairs,
forks, branch points and branches of Granville Bridge must stay as Kaveh accepted them (tests/reference/granville-bridge-steps-1-3.json).
Needs the local data/ (not in git); about 2 s."""
import json
import os

import pytest

PROFILE = "data/bridges-measured/granville-bridge.bridge.json"
DB = "data/cuts/granville.urban.duckdb"
GMNS = "data/granville-bridge.gmns.duckdb"         # SUMO for the bridge's own edges (duckOSM, not in git)
REF = os.path.join(os.path.dirname(__file__), "reference", "granville-bridge-steps-1-3.json")

pytestmark = pytest.mark.skipif(not all(os.path.exists(f) for f in (PROFILE, DB, GMNS)), reason="needs the local data/")


@pytest.fixture(scope="module")
def now():
    import duckdb
    from urbanstyle.bridge_forks import snapshot, steps_1_3
    con = duckdb.connect(DB, read_only=True)
    con.execute("LOAD spatial")
    axes, a_lv, R, B, F = steps_1_3(con, json.load(open(PROFILE)), GMNS)
    return snapshot(R, B, F)


@pytest.fixture(scope="module")
def ref():
    return json.load(open(REF))


def test_the_points_of_step_1_are_as_accepted(now, ref):
    assert now["nodes"] == ref["nodes"]
    assert now["pairs"] == ref["pairs"]
    assert now["forks"] == ref["forks"]


def test_the_branches_of_steps_2_and_3_are_as_accepted(now, ref):
    assert [b["id"] for b in now["branches"]] == [b["id"] for b in ref["branches"]]
    for b, r in zip(now["branches"], ref["branches"]):
        assert {k: b[k] for k in ("axes", "ends", "s0", "s1", "lo", "hi")} == {k: r[k] for k in ("axes", "ends", "s0", "s1", "lo", "hi")}, b["id"]
        assert b["line"] == r["line"], b["id"]
        assert b["area_m2"] == pytest.approx(r["area_m2"], abs=0.05), b["id"]


def test_the_forks_of_step_2_are_as_accepted(now, ref):
    assert now["fork_areas"].keys() == ref["fork_areas"].keys()
    for k, v in ref["fork_areas"].items():
        assert now["fork_areas"][k] == pytest.approx(v, abs=0.05), k


REF_3B_4 = os.path.join(os.path.dirname(__file__), "reference", "granville-bridge-steps-3b-4.json")


@pytest.fixture(scope="module")
def now_3b_4():
    import duckdb
    from urbanstyle.bridge_forks import snapshot_3b_4, steps_3b_4
    con = duckdb.connect(DB, read_only=True)
    con.execute("LOAD spatial")
    *_, outline, S4 = steps_3b_4(con, json.load(open(PROFILE)), GMNS)
    return snapshot_3b_4(outline, S4)


def test_the_smooth_outline_of_step_3b_is_as_accepted(now_3b_4):
    ref = json.load(open(REF_3B_4))
    assert now_3b_4["outline"].keys() == ref["outline"].keys()
    for lv, r in ref["outline"].items():
        n = now_3b_4["outline"][lv]
        assert n["area_m2"] == pytest.approx(r["area_m2"], abs=0.5) and n["edge_m"] == pytest.approx(r["edge_m"], abs=0.5), lv
        assert n["rings"] == r["rings"], lv


def test_the_bands_of_step_4_are_as_accepted(now_3b_4):
    ref = json.load(open(REF_3B_4))
    assert [(b["kind"], b["id"], b["home"]) for b in now_3b_4["bands"]] == [(b["kind"], b["id"], b["home"]) for b in ref["bands"]]
    for b, r in zip(now_3b_4["bands"], ref["bands"]):
        assert b["area_m2"] == pytest.approx(r["area_m2"], abs=0.05), b["id"]
