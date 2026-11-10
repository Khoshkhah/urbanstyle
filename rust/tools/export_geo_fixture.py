"""The test data of urbanstyle-geo: real polygons and lines of a cut, and what shapely makes of them.

    python rust/tools/export_geo_fixture.py data/cuts/sr-casino.urban.duckdb data/cuts/geo-fixture.json

Run it with the duckOSM environment (duckdb, shapely). The Rust test (rust/urbanstyle-geo/tests/shapely_cut.rs) reads the file, does
the same operations with the Rust helpers and compares the areas. The file is not in git."""
import json
import sys
import time

import duckdb
import shapely

db, out = sys.argv[1], sys.argv[2]
c = duckdb.connect(db, read_only=True)
c.execute("LOAD spatial")
T = "ST_AsWKB(ST_Transform(geometry, 'EPSG:4326', 'EPSG:32632', always_xy := true))"
g = lambda w: shapely.make_valid(shapely.force_2d(shapely.from_wkb(bytes(w))))
poly_coords = lambda p: [list(map(list, p.exterior.coords))] + [list(map(list, r.coords)) for r in p.interiors]
mp_coords = lambda x: [poly_coords(p) for p in shapely.get_parts(x) if p.geom_type == "Polygon"]

box = shapely.union_all([g(w) for (w,) in c.execute(f"SELECT {T} FROM work.area").fetchall()])
blocks = [p for (w,) in c.execute(f"SELECT {T} FROM work.block WHERE level = 0").fetchall() for p in shapely.get_parts(g(w)) if p.geom_type == "Polygon"]
lanes = shapely.union_all([g(w) for (w,) in c.execute(f"SELECT {T} FROM work.part WHERE level = 0 AND type = 'lane'").fetchall()])
lines = [shapely.get_parts(g(w))[0] for (w,) in c.execute(f"SELECT {T} FROM work.subsection WHERE geometry IS NOT NULL LIMIT 60").fetchall()]
lines = [ln for ln in lines if ln.geom_type == "LineString" and ln.length > 5]

t = time.time()
blocks_u = shapely.union_all(blocks)
street = box.difference(blocks_u)
lanes_b = lanes.buffer(8)
inter = street.intersection(lanes_b)
flat = [ln.buffer(1.5, cap_style="flat").area for ln in lines]
rnd = [ln.buffer(2.5).area for ln in lines]
wide = [shapely.union_all([q for q in shapely.get_parts(b.buffer(-4, join_style="mitre").buffer(4, join_style="mitre").intersection(b))]).area for b in blocks]
neg = [b.buffer(-3).area for b in blocks]
proj = []
for ln in lines[:20]:
    for f in (0.1, 0.5, 0.9):
        p = ln.interpolate(f * ln.length)
        q = shapely.Point(p.x + 3.0, p.y + 2.0)
        proj.append({"line": len(proj) // 3, "point": [q.x, q.y], "s": ln.project(q)})
print(f"shapely: {time.time() - t:.2f} s for the expected values")
json.dump({
    "box": mp_coords(box), "blocks": [poly_coords(b) for b in blocks], "lanes_b": mp_coords(lanes_b),
    "lines": [list(map(list, ln.coords)) for ln in lines], "projects": proj,
    "expect": {"street_area": street.area, "street_polys": len(shapely.get_parts(street)), "inter_area": inter.area,
               "union_blocks_area": blocks_u.area, "flat": flat, "round": rnd, "wide": wide, "neg": neg},
}, open(out, "w"))
print(f"{len(blocks)} blocks, {len(lines)} lines; street {street.area:,.0f} m2 -> {out}")
