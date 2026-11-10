"""The test data of the street objects (container.OBJECTS, unit.match with only OSM as a source, product._objects): the OSM nodes whose
tags make an object, and the rows of `urban.object` that the Python build made from them. The spaces and parts that hold them come from
the model fixture (export_model_fixture.py) and the Rust model.

    python rust/tools/export_object_fixture.py URBAN_DB OSM_DB OUT.json

Run it with the duckOSM environment. The file is not in git."""
import json
import sys

import duckdb

from urbanstyle.container import OBJECT_ATTRS

urban, osm, out = sys.argv[1:4]
EPSG = "EPSG:32632"
con = duckdb.connect(urban, read_only=True)
con.execute("LOAD spatial")
con.execute(f"ATTACH '{osm}' AS osm (READ_ONLY)")
KEYS = ("highway", "railway", "crossing", "crossing:signals", "crossing_ref", "traffic_sign", "traffic_sign:forward", "public_transport", "amenity",
        "leisure", "man_made", "emergency", "advertising", "barrier", "kerb", "natural", "entrance", "level", "layer", "name") + tuple(OBJECT_ATTRS)
keys = sorted(set(KEYS))
nodes = con.execute(f"""SELECT osm_id, lon, lat, tags FROM osm.raw.nodes
                        WHERE list_has_any(map_keys(tags), ?::VARCHAR[])""", [keys]).fetchall()
pts = con.execute("""SELECT ST_X(p), ST_Y(p) FROM (SELECT ST_Transform(ST_Point(x, y), 'EPSG:4326', ?, always_xy := true) AS p
                     FROM (SELECT unnest(?::DOUBLE[]) AS x, unnest(?::DOUBLE[]) AS y))""", [EPSG, [n[1] for n in nodes], [n[2] for n in nodes]]).fetchall()
sub = lambda t: {k: v for k, v in dict(t or {}).items() if k in keys}
exp = con.execute(f"""SELECT object_id, kind, level, space_id, part_id, near_m, name, attrs::VARCHAR, width_m, width_source, width_method, height_m,
                      height_source, height_method, sources, refs, source, method FROM urban.object""").fetchall()
json.dump({
    "input": {"nodes": [{"id": o, "tags": sub(t), "xy": list(p)} for (o, lo, la, t), p in zip(nodes, pts)]},
    "expect": [{"id": i, "kind": k, "level": lv, "space": sp, "part": pt, "near_m": nm, "name": n, "attrs": at, "width": w, "ws": ws, "wm": wm, "height": h,
                "hs": hs, "hm": hm, "sources": so, "refs": rf, "source": sr, "method": me}
               for i, k, lv, sp, pt, nm, n, at, w, ws, wm, h, hs, hm, so, rf, sr, me in exp],
}, open(out, "w"), default=str)
print(f"{len(nodes)} nodes -> {len(exp)} objects -> {out}")
