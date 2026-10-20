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
