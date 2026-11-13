"""The tunnels in 3D (docs/notes/tunnel-walls.md): every tunnel gets walls and a roof, and the ground decides what shows.

    outline  SimReady's face of the tunnel's level (work.face, level < 0)
    portals  SimReady's face_end lines on it (work.face_end): open, no wall
    road     SimReady's road height less the ground's (work.tunnel_axis, simready.py): the map draws the ground of level 0 at 0 m
    roof     the road plus the span's clearance (OSM maxheight), else SimReady's tunnel_clearance_default_m
    walls    along the face's ring, from the road to the roof

A part under the ground (below 0 m) is drawn only when level 0 is faded or hidden (`under` in the model); a part over the ground always.
The result has the format of deck3d.model, so the page draws it with the decks: `models(con)` -> [model].
"""
import json
import math

FACE_END_M = 0.05       # a piece of the ring this near a face_end line is a portal (as deck3d)


def _utm(lon):
    return f"EPSG:{32600 + int((lon + 180) // 6) + 1}"


def models(con):
    import pyproj
    import shapely
    import shapely.ops
    from .deck3d import STEP_M, _grid_tris
    have = lambda t: con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'work' AND table_name = ?",
                                 [t]).fetchone()[0]
    if not (have("face") and have("face_end") and have("tunnel_axis")):
        return []
    lon_ = con.execute("SELECT avg(ST_X(ST_Centroid(geometry))) FROM work.face WHERE level < 0").fetchone()[0]
    if lon_ is None:
        return []
    crs = _utm(lon_)
    to_m = f"ST_Transform(geometry, 'EPSG:4326', '{crs}', always_xy := true)"
    g = lambda w: shapely.make_valid(shapely.from_wkb(bytes(w)))
    faces = [(fid, lv, g(w)) for fid, lv, w in con.execute(f"SELECT face_id, level, ST_AsWKB({to_m}) FROM work.face WHERE level < 0").fetchall()]
    ends = {}
    for lv, w in con.execute(f"SELECT level, ST_AsWKB({to_m}) FROM work.face_end WHERE level < 0").fetchall():
        ends.setdefault(lv, []).append(g(w))
    ends = {lv: shapely.union_all(v).buffer(FACE_END_M) for lv, v in ends.items()}
    axes = {}
    for lv, cl, src, w in con.execute(f"SELECT level, clearance_m, clearance_source, ST_AsWKB({to_m}) FROM work.tunnel_axis").fetchall():
        ln = shapely.from_wkb(bytes(w))
        if ln.has_z and ln.length > 0:
            axes.setdefault(lv, []).append((ln, cl, src))
    to_ll = pyproj.Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform
    merc = pyproj.Transformer.from_crs(crs, "EPSG:3857", always_xy=True).transform
    out = []
    for fid, lv, f in faces:
        mine = axes.get(lv, [])
        if not mine or f.is_empty:
            continue
        tree = shapely.STRtree([a[0] for a in mine])

        def road(x, y):
            """(the road's height less the ground's, the clearance) at a point: the nearest axis of the face's level."""
            p = shapely.Point(x, y)
            ln, cl, _ = mine[int(tree.nearest(p))]
            q = ln.interpolate(ln.project(p))
            return q.z, cl

        c0 = f.centroid
        lon0, lat0 = to_ll(c0.x, c0.y)
        mx0, my0 = merc(c0.x, c0.y)
        kk = math.cos(math.radians(lat0))
        verts, vix = [], {}

        def vid(x, y, z):
            key = (round(x, 2), round(y, 2), round(z, 2))
            if key not in vix:
                X, Y = merc(x, y)
                vix[key] = len(verts)
                verts.append([round((X - mx0) * kk, 2), round((Y - my0) * kk, 2), round(z, 2)])
            return vix[key]
        roof, walls, roof_u, walls_u = [], [], [], []
        # the roof: the face at the road's height plus the clearance, each triangle over or under the ground by its middle
        for t in _grid_tris(f):
            cs = t.exterior.coords[:3]
            zs = [sum(road(x, y)) for x, y in cs]
            (roof if sum(zs) / 3 > 0 else roof_u).append([vid(x, y, z) for (x, y), z in zip(cs, zs)])
        # the walls: along the ring, not at a portal; from the road to the roof, cut at the ground (0 m) into its two parts
        for pg in shapely.get_parts(f):
            if pg.geom_type != "Polygon":
                continue
            for ring in [pg.exterior] + list(pg.interiors):
                cs = list(ring.segmentize(STEP_M / 2).coords)
                for (ax, ay), (bx, by) in zip(cs, cs[1:]):
                    if lv in ends and ends[lv].contains(shapely.Point((ax + bx) / 2, (ay + by) / 2)):
                        continue
                    (za, ca), (zb, cb) = road(ax, ay), road(bx, by)
                    lo, hi = (za, zb), (za + ca, zb + cb)
                    for part, a0, a1 in ((walls_u, min(lo[0], 0.0), min(hi[0], 0.0)), (walls, max(lo[0], 0.0), max(hi[0], 0.0))):
                        b0, b1 = (min(lo[1], 0.0), min(hi[1], 0.0)) if part is walls_u else (max(lo[1], 0.0), max(hi[1], 0.0))
                        if a1 - a0 < 0.01 and b1 - b0 < 0.01:
                            continue
                        p0, p1, p2, p3 = vid(ax, ay, a0), vid(bx, by, b0), vid(bx, by, b1), vid(ax, ay, a1)
                        part += [[p0, p1, p2], [p0, p2, p3]]
        srcs = sorted({s for _, _, s in mine})
        out.append({"name": f"tunnel {fid}", "level": lv, "origin": [lon0, lat0], "verts": verts, "deck": roof, "sides": walls, "rails": [],
                    "under": {"deck": roof_u, "sides": walls_u}, "axes": [], "lines": [], "lanes": [], "piers": [], "truss": [],
                    "surf": [], "checks": [], "flat": [], "deck_ll": json.loads(shapely.to_geojson(shapely.ops.transform(to_ll, f))),
                    "sources": {"model": "tunnel3d: SimReady's tunnel face, its road heights less duckOSM's ground, the clearance",
                                "clearance": srcs}})
    return out


if __name__ == "__main__":       # a self-check of the zone rule
    assert _utm(7.42) == "EPSG:32632" and _utm(-123.1) == "EPSG:32610"
    print("ok")
