"""Step 5 of a bridge (rank 0, the structure) is frozen (docs/notes/bridge-steps.md, "How a step is frozen"): Granville Bridge's heights,
structures, piers and checks must stay as Kaveh accepted them (tests/reference/granville-bridge-step-5.json). Needs the local data/ (not
in git); about 1 minute."""
import json
import os

import pytest

PROFILE = "data/bridges-measured/granville-bridge.bridge.json"
DB = "data/cuts/granville.urban.duckdb"
GMNS = "data/granville-bridge.gmns.duckdb"
REF = os.path.join(os.path.dirname(__file__), "reference", "granville-bridge-step-5.json")

pytestmark = pytest.mark.skipif(not all(os.path.exists(f) for f in (PROFILE, DB, GMNS)), reason="needs the local data/")


@pytest.fixture(scope="module")
def m():
    import duckdb
    from urbanstyle.bridge_surface import model
    con = duckdb.connect(DB, read_only=True)
    con.execute("LOAD spatial")
    return model(con, json.load(open(PROFILE)), gmns=GMNS, cover=False)


def test_rank0_is_as_accepted(m):
    ref = json.load(open(REF))
    assert [(s["level"], s["axes"], s["kind"]) for s in m["structures"]] == [(s["level"], s["axes"], s["kind"]) for s in ref["structures"]]
    for s, r in zip(m["structures"], ref["structures"]):
        assert s["area_m2"] == pytest.approx(r["area_m2"], abs=1.0)
    for k, pts in ref["heights"].items():
        now = m["heights"][k]
        assert len(now) == len(pts), k
        for (s, z), (rs, rz) in zip(now, pts):
            assert s == pytest.approx(rs, abs=0.02) and z == pytest.approx(rz, abs=0.02), k
    assert len(m["piers"]) == len(ref["piers"])
    assert {c[0]: c[2] for c in m["checks"]} == ref["checks"]
