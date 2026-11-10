"""The test data of the surfaces (layer 1, ground.surfaces): the ground items, the parts of the street spaces, the OSM layers that name a
surface (verges, gardens, play land, buildings, car parks, construction sites, walkways) and the rows of `urban.surface` that
ground.surfaces made from them.

    python rust/tools/export_surface_fixture.py URBAN_DB OSM_DB OUT.json

Run it with the duckOSM environment. The file is not in git."""
import json
import sys

import duckdb
import shapely

from urbanstyle import ground

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
mls = lambda x: [[list(c) for c in l.coords] for l in shapely.get_parts(x) if l.geom_type == "LineString"]
land = lambda kinds: [{"ref": r, "geom": mp(g(w))} for r, w in con.execute(
    f"SELECT 'w' || osm_id, {m('geom')} FROM osm.features.land WHERE kind IN {tuple(kinds) + ('',)}").fetchall()]
layers = {
    "verge": land(ground.VERGE_LAND), "garden": land(ground.GARDEN_LAND), "play": land(ground.PLAY_LAND),
    "buildings": [{"ref": r, "geom": mp(g(w))} for r, w in con.execute(
        f"SELECT source_id, {m()} FROM work.element WHERE type = 'building' AND level_min <= 0 AND level_max >= 0").fetchall()],
    "lots": [{"ref": r, "geom": mp(g(w))} for r, w in con.execute(f"SELECT lot_id, {m()} FROM work.lot").fetchall()],
    "sites": [{"ref": r, "geom": mp(g(w))} for r, w in con.execute(
        f"SELECT 'w' || osm_id, {m('geom')} FROM osm.features.sites WHERE kind = 'construction'").fetchall()],
    "walks": [{"ref": r, "lines": mls(g(w))} for r, w in con.execute(
        f"SELECT 'w' || osm_id, {m()} FROM work.element WHERE type IN ('walkway', 'cycleway') AND level_min = 0").fetchall()],
}
groundrows = con.execute(f"SELECT ground_id, type, ref, source, method, {m()} FROM work.ground").fetchall()
parts = con.execute(f"SELECT unit_id, type, source, {m()} FROM work.part").fetchall()
json.dump({
    "input": {
        "ground": [{"id": i, "type": t, "ref": r, "source": s, "method": me, "geom": mp(g(w))} for i, t, r, s, me, w in groundrows],
        "parts": [{"unit": u, "type": t, "source": s, "geom": mp(g(w))} for u, t, s, w in parts if t in ground.STREET_SURFACE],
        "layers": layers,
    },
    "expect": [{"id": i, "ground": gd, "kind": k, "level": lv, "source": s, "method": me, "ref": r, "area": g(w).area}
               for i, gd, k, lv, s, me, r, w in con.execute(
                   f"SELECT surface_id, ground_id, kind, level, source, method, ref, {m()} FROM urban.surface").fetchall()],
}, open(out, "w"), default=str)
print(f"{len(groundrows)} ground items, {len(parts)} parts -> {out}")
