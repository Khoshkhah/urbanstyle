"""The bridge in 2D (Kaveh, 2026-10-12: "a separate page for the 2D bridge, at one address, updated in under 5 s"):
`urbanstyle bridge2d PROFILE OUT.geojson [--db DB]` writes every part of the bridge model (bridge3d.model, flat_only: no heights, no
triangles) as a flat polygon with its id and fields; viz/bridge2d.html shows that file and reloads it by itself when it changes."""
import json
import os

COLORS = {"lane": "#5b6472", "lane forward": "#5b6472", "lane backward": "#4b5563", "junction area": "#374151", "sidewalk": "#e6d5c3",
          "cycle lane": "#2e9d5b", "barrier": "#a8a29e", "barrier median": "#d97706", "median": "#6b7280", "buffer": "#c4b5a0",
          "crosswalk": "#9ca3af"}


def write(profile, out, db=None):
    """The model of the bridge profile at `profile`, flat, to the GeoJSON file `out` (written whole, then moved in place). With a unit's
    `db`, its street's lanes near the bridge, for the landings (as the dashboard does). Returns the number of parts."""
    import shapely
    from .bridge3d import model
    P = json.load(open(profile))
    ground = None
    if db:
        import duckdb
        con = duckdb.connect(db, read_only=True)
        con.execute("LOAD spatial")
        ol = shapely.Polygon(P["deck"]["outline"]["value"])
        to_crs = f"ST_Transform(geometry, 'EPSG:4326', '{P['crs']}', always_xy := true)"
        ground = [g for (w,) in con.execute(f"SELECT ST_AsWKB({to_crs}) FROM urban.part WHERE level = 0 AND type = 'lane'").fetchall()
                  for g in [shapely.from_wkb(bytes(w))] if g.distance(ol) < 50]
    m = model(P, None, None, ground, flat_only=True)
    feats = []
    for props, key, g in m["flat"]:
        pr = {k: (v if isinstance(v, (str, int, float, bool)) or v is None else str(v)) for k, v in props.items()}
        pr["kind"] = key
        pr["color"] = COLORS.get(key) or COLORS.get(key.split(" ")[0], "#9ca3af")
        feats.append({"type": "Feature", "properties": pr, "geometry": json.loads(shapely.to_geojson(g))})
    tmp = out + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"type": "FeatureCollection", "name": P["name"], "features": feats}, f, separators=(",", ":"))
    os.replace(tmp, out)
    return len(feats)
