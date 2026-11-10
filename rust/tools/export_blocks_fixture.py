"""The test data of urbanstyle-blocks: the inputs of sr_blocks.build for a cut, as the Python reference reads them, and the blocks, sides
and corridors that the reference made.

    python rust/tools/export_blocks_fixture.py URBAN_DB OSM_DB SIMREADY_DB OUT.json

URBAN_DB is a cut built with --simready from that SimReady build (data/cuts/NAME.urban.duckdb), OSM_DB its input (NAME.osm.duckdb).
Run it with the duckOSM environment and PYTHONPATH=src. The file is not in git."""
import json
import sys

import duckdb
import shapely

from urbanstyle import simready as sr
from urbanstyle.blocks import path_sql

urban, osm, simready, out = sys.argv[1:5]
EPSG = "EPSG:32632"
con = duckdb.connect(urban, read_only=True)
con.execute("LOAD spatial")
con.execute(f"ATTACH '{osm}' AS osm (READ_ONLY)")
m = lambda col="geometry": f"ST_AsWKB(ST_Transform({col}, 'EPSG:4326', '{EPSG}', always_xy := true))"
g = lambda w: shapely.make_valid(shapely.force_2d(shapely.from_wkb(bytes(w))))
ring = lambda r: [list(c) for c in r.coords]
poly = lambda p: [ring(p.exterior)] + [ring(r) for r in p.interiors]
mp = lambda x: [poly(p) for p in shapely.get_parts(x) if p.geom_type == "Polygon"]
mls = lambda x: [[list(c) for c in l.coords] for l in shapely.get_parts(x) if l.geom_type == "LineString"]

box = shapely.union_all([g(w) for (w,) in con.execute(f"SELECT {m()} FROM work.area").fetchall()])
r = sr.read(con, EPSG, simready, box)
paths = con.execute(f"""SELECT any_value(e.class), any_value(e.name), e.osm_id, {m('ST_Union_Agg(e.geometry)')}, max(try_cast(w.tags['width'] AS DOUBLE))
                        FROM work.element e LEFT JOIN osm.raw.ways w USING (osm_id)
                        WHERE {path_sql('e')} AND coalesce(w.tags['area'], 'no') <> 'yes' GROUP BY e.osm_id""").fetchall()
blocks = [(b, a, g(w)) for b, a, w in con.execute(f"SELECT block_id, area_m2, {m()} FROM work.block").fetchall()]
json.dump({
    "input": {
        "area": mp(box), "face": mp(r["face"]), "lanes": [mp(x) for x in r["lane_list"]], "junctions": [mp(x) for x in r["junction_list"]],
        "drives": [mp(x) for x in r["drive_list"]],
        "streets": [{"way": s["way"], "name": s["name"], "class": s["cl"], "line": [list(c) for c in s["line"].coords]} for s in r["streets"]],
        "paths": [{"way": o, "class": cl, "name": nm, "geom": mls(g(w)), "width": wd} for cl, nm, o, w, wd in paths],
    },
    "expect": {
        "blocks": [{"id": b, "area": a, "polygon": mp(p)} for b, a, p in blocks],
        "sides": [{"block": b, "way": w, "distance": d} for b, w, d in con.execute("SELECT block_id, way_id, distance_m FROM work.block_side").fetchall()],
        "corridors": [{"id": c, "way": w, "width": wd, "area": shapely.union_all([g(x)]).area}
                      for c, w, wd, x in con.execute(f"SELECT corridor_id, way_id, width_m, {m()} FROM work.corridor").fetchall()],
    },
}, open(out, "w"))
print(f"{len(blocks)} blocks, {len(r['streets'])} street lines, {len(paths)} path ways -> {out}")
