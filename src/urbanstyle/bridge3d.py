"""A bridge as a 3D model for the dashboard's three.js layer (docs/design/bridges-3d.md), from its profile only
(docs/design/bridge-profile.md, `bridge_profile.py`):
    deck       the outline, its top as triangles; each point at the height of the nearest axis's vertical profile; as thick as the
               profile's deck thickness, with a parapet along the outline
    lanes      each band of each section, a ribbon between its left and right edges, with its fields (and their sources) for the popup
    lines      an edge line at the outer edge of each run of lanes, a lane line between two lanes of one direction, the centre line
               between the two directions
    piers      a wall across the deck at each pier, down to the ground
Coordinates: metres east and north of the model's origin (its first outline point), and up.
"""
import json

STEP_M = 4.0        # the outline and the bands are sampled this often, so their heights follow the profile
TOUCH_M = 0.5       # two lanes this close share one painted line


def _z(points, s):
    from .bridge_profile import _z
    return _z(points, s)


def model(path):
    import pyproj
    import shapely

    P = json.load(open(path)) if isinstance(path, str) else path
    to_ll = pyproj.Transformer.from_crs(P["crs"], "EPSG:4326", always_xy=True).transform
    ol = P["deck"]["outline"]["value"]
    x0, y0 = ol[0]
    rel = lambda ps: [(x - x0, y - y0) for x, y in ps]
    deck = shapely.make_valid(shapely.Polygon(rel(ol)))
    deck = max(shapely.get_parts(deck), key=lambda p: p.area) if deck.geom_type != "Polygon" else deck
    DECK_M, RAIL_M = P["deck"]["thickness"]["value"], P["deck"]["parapet"]["value"]
    axes = [(shapely.LineString(rel(a["line"]["value"])), a) for a in P["axes"]]
    by_id = {a["id"]: (ln, a) for ln, a in axes}

    def z(x, y):
        """The deck's top at (x, y): the vertical profile of the nearest axis."""
        p = shapely.Point(x, y)
        ln, a = min(axes, key=lambda la: la[0].distance(p))
        return _z(a["vertical"]["points"], ln.project(p))

    # the deck's top: the outline densified, triangulated inside it
    dense = deck.segmentize(STEP_M)
    tris = [t for t in shapely.get_parts(shapely.constrained_delaunay_triangles(dense)) if t.representative_point().within(deck.buffer(0.01))]
    verts, index = [], {}

    def vid(x, y, zz):
        k = (round(x, 2), round(y, 2), round(zz, 2))
        if k not in index:
            index[k] = len(verts)
            verts.append(list(k))
        return index[k]
    top = [[vid(x, y, z(x, y)) for x, y in t.exterior.coords[:3]] for t in tris]
    bottom = [[vid(x, y, z(x, y) - DECK_M) for x, y in t.exterior.coords[:3]][::-1] for t in tris]
    sides, rails = [], []
    for ring in [dense.exterior] + list(dense.interiors):
        c = list(ring.coords)
        for (ax, ay), (bx, by) in zip(c, c[1:]):
            za, zb = z(ax, ay), z(bx, by)
            a0, b0, a1, b1 = vid(ax, ay, za - DECK_M), vid(bx, by, zb - DECK_M), vid(ax, ay, za), vid(bx, by, zb)
            sides += [[a0, b0, b1], [a0, b1, a1]]
            r0, r1 = vid(ax, ay, za + RAIL_M), vid(bx, by, zb + RAIL_M)
            rails += [[a1, b1, r1], [a1, r1, r0]]

    def frame(ln, s):
        """The point on the axis at s and its unit normal to the left."""
        p, a, b = ln.interpolate(s), ln.interpolate(max(s - 1, 0)), ln.interpolate(min(s + 1, ln.length))
        dx, dy = b.x - a.x, b.y - a.y
        h = (dx * dx + dy * dy) ** .5 or 1
        return p.x, p.y, -dy / h, dx / h

    def along(ln, a, s0, s1, t, lift):
        """Points at offset t along the axis from s0 to s1, at the deck's height plus lift."""
        n = max(1, int((s1 - s0) // STEP_M))
        out = []
        for i in range(n + 1):
            s = s0 + (s1 - s0) * i / n
            x, y, nx, ny = frame(ln, s)
            out.append([round(x + nx * t, 2), round(y + ny * t, 2), round(_z(a["vertical"]["points"], s) + lift, 2)])
        return out
    lanes, lines = [], []
    for ln, a in axes:
        height = f"{a['vertical']['source']}, {a['vertical']['method']}"
        for sec in a["sections"]:
            for b in sec["bands"]:
                w = b["width"]["value"]
                props = {"type": b["type"], "name": b.get("name") or P["name"], "osm": b.get("way"), "link": b.get("link"),
                         "lane_id": b.get("lane_id"), "direction": b.get("direction"), "lane": b.get("lane"), "use": b.get("use"),
                         "turn": b.get("turn"), "width_m": w, "width_source": b["width"]["source"], "width_method": b["width"]["method"],
                         "axis": a["id"], "section_m": f"{sec['s0']}-{sec['s1']}", "height": height,
                         "source": "duckOSM GMNS (lanes from SUMO)" if b["type"] == "lane" else "osm", "method": "mapped"}
                lanes.append({"props": props, "l": along(ln, a, sec["s0"], sec["s1"], b["t"] + w / 2, 0.03),
                              "r": along(ln, a, sec["s0"], sec["s1"], b["t"] - w / 2, 0.03)})
            # painted lines: across the lanes of the section, from left to right
            ls, paint = [b for b in sec["bands"] if b["type"] == "lane"], []
            for i, b in enumerate(ls):
                left, right = b["t"] + b["width"]["value"] / 2, b["t"] - b["width"]["value"] / 2
                if i == 0 or abs(ls[i - 1]["t"] - ls[i - 1]["width"]["value"] / 2 - left) > TOUCH_M:
                    paint.append(("edge line", left))
                if i + 1 < len(ls) and abs(ls[i + 1]["t"] + ls[i + 1]["width"]["value"] / 2 - right) <= TOUCH_M:
                    nb = ls[i + 1]
                    paint.append(("centre line" if nb["direction"] != b["direction"] else "lane line", (right + nb["t"] + nb["width"]["value"] / 2) / 2))
                else:
                    paint.append(("edge line", right))
            lines += [{"kind": k, "ref": a["id"], "pts": along(ln, a, sec["s0"], sec["s1"], t, 0.06)} for k, t in paint]
    piers = []
    for q in P["piers"]:
        ln, a = by_id[q["axis"]]
        x, y, nx, ny = frame(ln, q["s"])
        cut = shapely.LineString([(x - nx * 80, y - ny * 80), (x + nx * 80, y + ny * 80)]).intersection(deck.buffer(-2.0))
        h = _z(a["vertical"]["points"], q["s"]) - DECK_M
        for seg in shapely.get_parts(cut):
            if seg.geom_type == "LineString" and seg.length > 2:
                (ax, ay), (bx, by) = seg.coords[0], seg.coords[-1]
                piers.append({"a": [round(ax, 2), round(ay, 2)], "b": [round(bx, 2), round(by, 2)], "t": q["width"], "h": round(h, 2)})
    v = lambda d: f"{d['source']}, {d['method']}"
    return {"name": P["name"], "origin": list(to_ll(x0, y0)), "outline": [list(to_ll(x, y)) for x, y in ol], "verts": verts,
            "deck": top + bottom, "sides": sides, "rails": rails, "lines": lines, "lanes": lanes, "piers": piers,
            "sources": {"outline": v(P["deck"]["outline"]), "heights": "; ".join(sorted({v(a["vertical"]) for _, a in axes})),
                        "deck": v(P["deck"]["thickness"]), "parapet": v(P["deck"]["parapet"]),
                        "piers": v(P["piers"][0]) if P["piers"] else "none"}}


if __name__ == "__main__":
    import sys
    m = model(sys.argv[1])
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in m.items()}, indent=1))
