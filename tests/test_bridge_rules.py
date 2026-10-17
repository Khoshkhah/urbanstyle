"""The bridge model's rules on the real Granville Bridge (bridge3d.model_checks, BR1-BR11): slow (about 2 minutes) and needs the local
data/ (not in git), so it runs only on request: URBANSTYLE_BRIDGE_TESTS=1 pytest -q tests/test_bridge_rules.py."""
import json
import os

import pytest

PROFILE = "data/bridges-measured/granville-bridge.bridge.json"
DB = "data/units/broadway-granville.urban.duckdb"
# faults the checks find that are not fixed yet (2026-10-12): they are reported, but do not fail the run
KNOWN = {}

pytestmark = pytest.mark.skipif(not (os.environ.get("URBANSTYLE_BRIDGE_TESTS") and os.path.exists(PROFILE) and os.path.exists(DB)),
                                reason="slow: set URBANSTYLE_BRIDGE_TESTS=1 (needs the local data/)")


@pytest.fixture(scope="module")
def checks():
    import duckdb
    import shapely
    from urbanstyle.bridge3d import model
    P = json.load(open(PROFILE))
    c = duckdb.connect(DB, read_only=True)
    c.execute("LOAD spatial")
    ol = shapely.Polygon(P["deck"]["outline"]["value"])
    to_crs = f"ST_Transform(geometry, 'EPSG:4326', '{P['crs']}', always_xy := true)"
    ground = [g for (w,) in c.execute(f"SELECT ST_AsWKB({to_crs}) FROM work.part WHERE level = 0 AND type = 'lane'").fetchall()
              for g in [shapely.from_wkb(bytes(w))] if g.distance(ol) < 50]
    return {cid: (what, n, hard, at) for cid, what, n, hard, at in model(P, None, None, ground)["checks"]}


@pytest.mark.parametrize("cid", [f"BR{i}" for i in range(1, 12)])
def test_bridge_rule(checks, cid):
    what, n, hard, at = checks[cid]
    if cid in KNOWN and n:
        pytest.xfail(f"{cid} {what}: {n} (known: {KNOWN[cid]}) at {at[:3]}")
    assert not (hard and n), f"{cid} {what}: {n} at {at[:5]}"
