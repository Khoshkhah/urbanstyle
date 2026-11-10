"""The test data of urbanstyle-checks (group 1: the partition checks U1-U9, U11-U13, G1-G3, L1-L2, B1, B7, B8): the geometries that the
checks read from a finished build, and the counts that `urbanstyle check` gave for it (urban.check, or a run of checks.run).

    python rust/tools/export_check_fixture.py URBAN_DB OUT.json

Run it with the duckOSM environment. The file is not in git."""
import json
import sys

import duckdb
import shapely

urban, out = sys.argv[1:3]
EPSG = "EPSG:32632"
con = duckdb.connect(urban, read_only=True)
con.execute("LOAD spatial")
m = lambda col="geometry": f"ST_AsWKB(ST_Transform({col}, 'EPSG:4326', '{EPSG}', always_xy := true))"
g = lambda w: None if w is None else shapely.make_valid(shapely.from_wkb(bytes(w)))
ring = lambda r: [list(c) for c in r.coords]
poly = lambda p: [ring(p.exterior)] + [ring(r) for r in p.interiors]
mp = lambda x: [poly(p) for p in shapely.get_parts(x) if p.geom_type == "Polygon" and not p.is_empty] if x is not None else []
raw = lambda w: [poly(p) for p in shapely.get_parts(shapely.from_wkb(bytes(w))) if p.geom_type == "Polygon" and not p.is_empty]
line = lambda w: [list(c) for c in shapely.from_wkb(bytes(w)).coords] if w is not None and shapely.from_wkb(bytes(w)).geom_type == "LineString" else None

# the geometries as stored (a polygon can be invalid or in several parts: U2 counts them), so no make_valid here
units = con.execute(f"SELECT unit_id, kind, level, {m()} FROM work.unit").fetchall()
parts = con.execute(f"SELECT unit_id, part_id, level, type, width_method, source, width_m, {m()} FROM work.part").fetchall()
ground = con.execute(f"SELECT ground_id, level, type, {m()} FROM work.ground").fetchall()
surf = con.execute(f"SELECT surface_id, ground_id, {m()} FROM work.surface").fetchall()
blocks = con.execute(f"SELECT block_id, {m()} FROM work.block").fetchall()
area = con.execute(f"SELECT {m()} FROM work.area").fetchall()
blds = con.execute(f"SELECT {m()} FROM work.element WHERE type = 'building' AND level_min <= 0 AND level_max >= 0").fetchall()
nodes = {n: shapely.from_wkb(bytes(w)) for n, w in con.execute(f"""SELECT src, {m('ST_StartPoint(geometry)')} FROM work.element WHERE type = 'road' AND src IS NOT NULL
                                  UNION SELECT dst, {m('ST_EndPoint(geometry)')} FROM work.element WHERE type = 'road' AND dst IS NOT NULL""").fetchall()}
jn = con.execute("SELECT intersection_id, level, node_id FROM work.junction").fetchall()
subs = con.execute(f"SELECT subsection_id, level, {m()} FROM work.subsection").fetchall()
app = con.execute("SELECT unit_id, from_edge, moves, ways, arrow, no_arrow_because FROM work.approach").fetchall()
from urbanstyle.blocks import street_sql
guides = con.execute(f"SELECT level, {m()} FROM work.mark WHERE type = 'guide line'").fetchall()
roads = con.execute(f"""SELECT e.osm_id, e.src, e.dst, e.level_min, e.type, ({street_sql('e')}) AS street, {m('e.geometry')}, e.class, e.width_m, e.subtype
                       FROM work.element e WHERE e.type IN ('road', 'walkway', 'cycleway')""").fetchall()
marks = con.execute(f"SELECT unit_id, type, source, {m()} FROM work.mark WHERE level = 0 AND type IN ('kerb', 'centre line', 'lane line')").fetchall()
swidth = dict(con.execute("SELECT subsection_id, width_m FROM work.subsection").fetchall())
secs = dict(con.execute("SELECT subsection_id, section_id FROM work.subsection").fetchall())
try:
    expect = {i: n for i, n in con.execute("SELECT check_id, count FROM urban.check").fetchall()}
except duckdb.CatalogException:
    expect = {}
if not expect:      # a build with no urban.check yet: run the checks
    from urbanstyle import checks
    rows = []
    checks.run(urban, rows)
    expect = {r[0]: r[2] for r in rows}
json.dump({
    "input": {
        "area": [x for (w,) in area for x in raw(w)],
        "units": [{"id": u, "kind": k, "level": lv, "geom": raw(w)} for u, k, lv, w in units],
        "parts": [{"unit": u, "id": i, "level": lv, "type": t, "width_method": wm, "source": so, "width": wd, "geom": raw(w)} for u, i, lv, t, wm, so, wd, w in parts],
        "ground": [{"id": i, "level": lv, "type": t, "geom": raw(w)} for i, lv, t, w in ground],
        "surfaces": [{"id": i, "ground": gd, "geom": raw(w)} for i, gd, w in surf],
        "blocks": [{"id": b, "geom": raw(w)} for b, w in blocks],
        "buildings": [raw(w) for (w,) in blds],
        "node_pt": {str(n): [p.x, p.y] for n, p in nodes.items()},
        "junctions": [{"intersection": i, "level": lv, "node": n} for i, lv, n in jn],
        "subsections": [{"id": i, "level": lv, "line": line(w), "width": swidth.get(i)} for i, lv, w in subs],
        "guides": [{"level": lv, "lines": [[list(c) for c in l.coords] for l in shapely.get_parts(shapely.from_wkb(bytes(w))) if l.geom_type == "LineString"]} for lv, w in guides],
        "roads": [{"osm_id": o, "src": a, "dst": b, "level": lv, "type": t, "street": bool(st), "line": [list(c) for c in shapely.from_wkb(bytes(w)).coords] if shapely.from_wkb(bytes(w)).geom_type == "LineString" else None,
                   "class": cl, "width": wd, "subtype": sb}
                  for o, a, b, lv, t, st, w, cl, wd, sb in roads],
        "marks": [{"unit": u, "type": t, "source": so, "lines": [[list(c) for c in l.coords] for l in shapely.get_parts(shapely.from_wkb(bytes(w))) if l.geom_type == "LineString"]}
                  for u, t, so, w in marks],
        "sections": secs,
        "approaches": [{"unit": u, "from_edge": fe, "moves": mv, "ways": wy, "arrow": ar, "no_arrow_because": nb} for u, fe, mv, wy, ar, nb in app],
    },
    "expect": expect,
}, open(out, "w"), default=str)
print(f"{len(units)} units, {len(parts)} parts, {len(ground)} ground, {len(surf)} surfaces; expected {sorted(expect.items())[:6]}... -> {out}")
