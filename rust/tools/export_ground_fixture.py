"""The test data of urbanstyle-ground: what ground.gather reads for a cut (the area, the kinds in the order they take the ground, the
blocks' land, the road and path lines) and what ground.assemble made of it.

    python rust/tools/export_ground_fixture.py URBAN_DB OSM_DB OUT.json

URBAN_DB is a cut (data/cuts/NAME.urban.duckdb), OSM_DB its input (NAME.osm.duckdb). Run it with the duckOSM environment and
PYTHONPATH=src. The file is not in git. The Python assemble is not exactly repeatable (a few alleys differ by metres between two runs),
so the tests compare areas with a tolerance."""
import json
import sys

import duckdb
import shapely

from urbanstyle import ground

urban, osm, out = sys.argv[1:4]
EPSG = "EPSG:32632"
con = duckdb.connect(urban)       # (a copy is better: gather makes no table, but the view below does)
con.execute("LOAD spatial")
con.execute(f"ATTACH '{osm}' AS osm (READ_ONLY)")
cols = {c for (c,) in con.execute("SELECT column_name FROM duckdb_columns() WHERE database_name = 'osm' AND table_name = 'boundary'").fetchall()}
con.execute(f"CREATE OR REPLACE TEMP VIEW osm_boundary AS SELECT {'geometry' if 'geometry' in cols else 'geom'} AS geometry FROM osm.main.boundary")
inp = ground.gather(con, EPSG)
res = ground.assemble(inp)

ring = lambda r: [list(c) for c in r.coords]
poly = lambda p: [ring(p.exterior)] + [ring(r) for r in p.interiors]
mp = lambda x: [poly(p) for p in shapely.get_parts(x) if p.geom_type == "Polygon" and not p.is_empty]
lines = lambda x: [[list(c) for c in l.coords] for l in shapely.get_parts(x) if l.geom_type == "LineString"]
json.dump({
    "input": {
        "area": mp(inp["area"]),
        "land": None if inp["land_"] is None else mp(inp["land_"]),
        "has_parcels": bool(inp["has_parcels"]),
        "order": [{"type": t, "source": s, "method": m, "items": [{"ref": r, "name": n, "geom": mp(g)} for r, n, g in items]}
                  for t, items, s, m in inp["order"]],
        "lines": [{"type": t, "ref": r, "name": n, "lines": lines(g), "width": wd} for t, r, n, g, wd in inp["lines"]],
    },
    "expect": [{"id": i, "type": t, "name": n, "source": s, "method": m, "ref": r, "area": g.area, "parts": len(shapely.get_parts(g))}
               for i, t, n, s, m, r, g in res],
}, open(out, "w"), default=str)
print(f"{sum(len(o[1]) for o in inp['order'])} items in {len(inp['order'])} kinds, {len(inp['lines'])} lines -> {len(res)} ground items -> {out}")
