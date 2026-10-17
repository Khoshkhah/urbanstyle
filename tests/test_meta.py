"""The data about the data (meta.py): the manifest, the tree, the registry's stable ids and the check rows."""
import duckdb

import urbanstyle
from urbanstyle import meta
from test_levels import SQUARE, make_osm


def test_manifest_tree_and_stable_ids(tmp_path):
    osm = make_osm(tmp_path / "osm.duckdb", [(1, {"building:levels": "3"}, SQUARE), (2, {}, SQUARE)])
    out = str(tmp_path / "a.urban.duckdb")
    con = urbanstyle.build(osm, out)
    first = dict(con.execute("SELECT source_id, uid FROM urban.element WHERE type = 'building'").fetchall())
    keys = dict(con.execute("SELECT key, kind FROM urban.meta").fetchall())
    ranks = {r for (r,) in con.execute("SELECT DISTINCT rank FROM urban.item").fetchall()}
    orphans = con.execute("SELECT count(*) FROM urban.item WHERE rank > 0 AND parent_id IS NULL").fetchone()[0]
    con.close()
    assert len(first) == 2 and all(first.values()) and len(set(first.values())) == 2
    assert keys["version"] == "build" and keys["built"] == "build" and keys["input.osm"] == "input"
    assert keys["chosen.network.LANE_M"] == "chosen" and keys["chosen.container.FLOOR_M"] == "chosen"
    assert 0 in ranks and 1 in ranks and orphans == 0
    con = duckdb.connect(out)
    unstyled = con.execute("SELECT DISTINCT i.rank, i.kind FROM urban.item i LEFT JOIN urban.style s ON s.rank = i.rank AND s.kind = i.kind "
                           "WHERE s.kind IS NULL").fetchall()
    con.close()
    assert unstyled == []       # every kind of the tree has its style
    con = duckdb.connect(out, read_only=True)
    assert con.execute("SELECT citygml, opendrive FROM urban.code WHERE kind = 'lane'").fetchone() == (
        "TrafficSpace granularity=lane; TrafficArea", "lane type=driving")
    con.close()
    con = urbanstyle.build(osm, out)        # a rebuild of the same data: the same ids
    again = dict(con.execute("SELECT source_id, uid FROM urban.element WHERE type = 'building'").fetchall())
    seen = con.execute("SELECT count(*), count(*) FILTER (WHERE first_seen < last_seen) FROM urban.registry").fetchone()
    con.close()
    assert again == first and seen == (2, 2)


def test_check_rows(tmp_path):
    path = str(tmp_path / "c.duckdb")
    duckdb.connect(path).execute("CREATE SCHEMA urban").close()
    meta.write_checks(path, [("U1", "overlaps", 0, True), ("A1", "lanes off", 2, True, [(1.5, 2.25), (3.0, 4.0)]), ("K1", "kerbs", 3, False, [])])
    meta.write_checks(path, [("U1", "overlaps", 0, True), ("A1", "lanes off", 2, True, [(1.5, 2.25), (3.0, 4.0)]), ("K1", "kerbs", 3, False, [])])
    got = duckdb.connect(path).execute("SELECT check_id, kind, status, count, items FROM urban.check ORDER BY 1").fetchall()
    assert got == [("A1", "fault", "fail", 2, ["1.500000,2.250000", "3.000000,4.000000"]), ("K1", "info", "info", 3, []),
                   ("U1", "fault", "pass", 0, [])]
