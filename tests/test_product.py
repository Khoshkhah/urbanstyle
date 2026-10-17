"""The model in a build is the model of docs/design/tables.md: every table, every column in its order, every type."""
import os
import re

import duckdb

import urbanstyle
from urbanstyle import meta
from test_levels import SQUARE, make_osm

DOC = os.path.join(os.path.dirname(__file__), "..", "docs", "design", "tables.md")


def doc_tables():
    """{table: [(column, type)]} from every `### `urban.<table>`` section's `| Column | Type | Meaning |` table."""
    out, table, in_cols = {}, None, False
    for line in open(DOC):
        if line.startswith("#"):
            h = re.match(r"#+ .*`urban\.(\w+)`", line)
            table, in_cols = (h.group(1) if h else None), False
        elif line.startswith("| Column | Type |") and table:
            out.setdefault(table, [])
            in_cols = True
        elif in_cols and (cell := re.match(r"\| `(\w+)` \| ([A-Z\[\]]+) \|", line)):
            out[table].append((cell.group(1), cell.group(2)))
        elif in_cols and not line.startswith("|"):
            in_cols = False
    return out


def test_the_build_is_the_document(tmp_path):
    osm = make_osm(tmp_path / "osm.duckdb", [(1, {"building:levels": "3"}, SQUARE)])
    out = str(tmp_path / "a.urban.duckdb")
    urbanstyle.build(osm, out).close()
    meta.write_checks(out, [("U1", "overlaps", 0, True)])
    con = duckdb.connect(out, read_only=True)
    con.execute("LOAD spatial")
    built = {t for (t,) in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'urban'").fetchall()}
    want = doc_tables()
    assert set(want) - {"bridge_part"} == built, "tables of the document and of the build differ"
    for t, cols in want.items():
        if t == "bridge_part":
            continue
        got = [(c, ty) for c, ty, *_ in con.execute(f'DESCRIBE urban."{t}"').fetchall()]
        assert got == cols, f"urban.{t}: the build has {got}, the document {cols}"
    # the common columns stand first, in their order, in every rank table
    for t in ("area", "ground", "stretch", "plot_piece", "space", "side", "part", "mark"):
        assert [c for c, _ in want[t][1:5]] == ["kind", "rank", "parent_id", "level"], t
    for t, cols in want.items():     # a geometry is a shape or NULL, never a value with no shape
        for c, ty in cols:
            if ty == "GEOMETRY" and t not in ("item", "check"):
                assert con.execute(f'SELECT count(*) FROM urban."{t}" WHERE "{c}" IS NOT NULL AND ST_AsWKB("{c}") IS NULL').fetchone()[0] == 0, (t, c)
    for t in ("area", "ground", "stretch", "plot_piece", "space", "side", "part", "mark", "object"):
        assert con.execute(f'SELECT count(*) FROM urban."{t}" WHERE uid IS NULL').fetchone()[0] == 0, f"urban.{t}: rows with no uid"
    con.close()


def test_cut_intersection():
    import shapely
    from urbanstyle.product import cut_intersection
    sq = shapely.box(0, 0, 40, 20)
    one = cut_intersection(sq, {7: shapely.Point(10, 10)})
    assert len(one) == 1 and one[0][1].equals(sq)            # one node: the whole intersection
    two = dict(cut_intersection(sq, {7: shapely.Point(10, 10), 9: shapely.Point(30, 10)}))
    assert set(two) == {7, 9} and abs(two[7].area - 400) < 1e-6 and abs(two[9].area - 400) < 1e-6   # cut halfway, at x = 20
    ring = shapely.Point(20, 10).buffer(9).exterior               # a roundabout: a ring, an island inside it, four arm nodes
    island = shapely.Point(20, 10).buffer(5)
    rb = dict(cut_intersection(shapely.Point(20, 10).buffer(12), {k: shapely.Point(20 + 10 * dx, 10 + 10 * dy) for k, (dx, dy) in
                                                                    enumerate([(1, 0), (0, 1), (-1, 0), (0, -1)])}, [ring], [island]))
    assert set(rb) == {0, 1, 2, 3, "centre"} and abs(rb["centre"].area - island.area) < 1e-6
    assert abs(sum(g.area for g in rb.values()) - shapely.Point(20, 10).buffer(12).area) < 1e-6    # the pieces partition it
