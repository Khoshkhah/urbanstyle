"""The test data of urbanstyle-paths: what paths.gather reads for a cut (the path items of the ground, the corridors' widths, the walkway
and cycleway lines) and what paths.assemble made of it.

    python rust/tools/export_paths_fixture.py URBAN_DB OUT.json

URBAN_DB is a cut with a built ground (data/cuts/NAME.urban.duckdb). Run it with the duckOSM environment and PYTHONPATH=src. The file is
not in git."""
import json
import sys

import duckdb
import shapely

from urbanstyle import paths
from urbanstyle.blocks import PATH_W

urban, out = sys.argv[1:3]
EPSG = "EPSG:32632"
con = duckdb.connect(urban, read_only=True)
con.execute("LOAD spatial")
inp = paths.gather(con, EPSG, 0)
res = paths.assemble(inp)

ring = lambda r: [list(c) for c in r.coords]
poly = lambda p: [ring(p.exterior)] + [ring(r) for r in p.interiors]
mp = lambda x: [poly(p) for p in shapely.get_parts(x) if p.geom_type == "Polygon" and not p.is_empty]
json.dump({
    "input": {
        "level": inp["level"], "footway_w": PATH_W["footway"],
        "items": [{"id": i, "ref": r, "geom": mp(g)} for i, r, g in inp["items"]],
        "corridors": {c: {"name": v[0], "width": v[1], "source": v[2], "method": v[3]} for c, v in inp["corr"].items()},
        "lines": [{"way": w, "class": cl, "name": nm, "src": s, "dst": d, "line": [list(c) for c in ln.coords]} for w, cl, nm, s, d, ln in inp["elems"]
                  if ln.geom_type == "LineString"],
    },
    "expect": [{"id": a["id"], "kind": a["kind"], "ground": a["ground"], "name": a["name"], "class": a["cls"], "ways": a["ways"], "nodes": a["nodes"],
                "width": a["w"][0], "width_source": a["w"][1], "length": a["length"], "area": a["geom"].area, "links": a["links"],
                "axis": a["axis"] is not None} for a in res],
}, open(out, "w"), default=str)
print(f"{len(inp['items'])} path items, {len(inp['elems'])} lines -> {len(res)} path spaces -> {out}")
