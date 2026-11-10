"""The test data of the building and lot rows of `element` (BUILD, CLAMP, LOTS and buildings.py): duckOSM's buildings with the tags that
the rules read, the points of interest, the lots, and the rows of `urban.element` that the Python build made from them.

    python rust/tools/export_element_fixture.py URBAN_DB OSM_DB OUT.json

Run it with the duckOSM environment. The file is not in git."""
import json
import sys

import duckdb
import shapely

from urbanstyle import buildings

urban, osm, out = sys.argv[1:4]
EPSG = "EPSG:32632"
con = duckdb.connect(urban, read_only=True)
con.execute("LOAD spatial")
con.execute(f"ATTACH '{osm}' AS osm (READ_ONLY)")
m = lambda col="geometry": f"ST_AsWKB(ST_Transform({col}, 'EPSG:4326', '{EPSG}', always_xy := true))"
g = lambda w: shapely.make_valid(shapely.from_wkb(bytes(w)))
ring = lambda r: [list(c) for c in r.coords]
poly = lambda p: [ring(p.exterior)] + [ring(r) for r in p.interiors]
mp = lambda x: [poly(p) for p in shapely.get_parts(x) if p.geom_type == "Polygon" and not p.is_empty]
BKEYS = ("building:levels", "building:levels:underground", "building:min_level", "height", "location", "building:use", "building")
PKEYS = ("amenity", "shop", "disused:shop", "vacant", "healthcare", "craft", "leisure", "office", "level", "name")
sub = lambda t, keys: {k: v for k, v in dict(t or {}).items() if k in keys}
blds = con.execute(f"SELECT osm_type, osm_id, name, kind, tags, {m('geom')} FROM osm.features.buildings").fetchall()
pois = [(sub(t, PKEYS), w) for t, w in con.execute(f"SELECT tags, {m('geom')} FROM osm.features.pois").fetchall()]
pois = [(t, w) for t, w in pois if buildings.poi_use(t) is not None]
lots = con.execute(f"SELECT lot_id, type, name, level, {m()} FROM work.lot").fetchall()
exp = con.execute(f"""SELECT element_id, kind, class, name, level_min, level_max, level_src, floors, height_m, "use", use_source, use_method,
                      ground_use, ground_source, ground_method, source, {m()} FROM urban.element WHERE kind IN ('building', 'lot')""").fetchall()
json.dump({
    "input": {
        "buildings": [{"type": t, "osm_id": o, "name": n, "kind": k, "tags": sub(tg, BKEYS), "geom": mp(g(w))} for t, o, n, k, tg, w in blds],
        "pois": [{"tags": t, "point": list(shapely.from_wkb(bytes(w)).coords[0])} for t, w in pois if shapely.from_wkb(bytes(w)).geom_type == "Point"],
        "lots": [{"id": i, "type": t, "name": n, "level": lv, "geom": mp(g(w))} for i, t, n, lv, w in lots],
    },
    "expect": [{"id": i, "kind": k, "class": c, "name": n, "level_min": a, "level_max": b, "level_src": ls, "floors": fl, "height": h, "use": u, "use_source": us,
                "use_method": um, "ground_use": gu, "ground_source": gs, "ground_method": gm, "source": s, "area": g(w).area}
               for i, k, c, n, a, b, ls, fl, h, u, us, um, gu, gs, gm, s, w in exp],
}, open(out, "w"), default=str)
print(f"{len(blds)} buildings, {len(pois)} points, {len(lots)} lots -> {len(exp)} element rows -> {out}")
