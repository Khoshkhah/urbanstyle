"""A bridge as a 3D model for the dashboard's three.js layer (docs/design/bridges-3d.md), from its profile only
(docs/design/bridge-profile.md, `bridge_profile.py`):
    deck       the outline, its top as triangles; as thick as the profile's deck thickness, with a parapet along the outline
    heights    the lanes and lines: their own axis's vertical profile; the deck: the nearest axis's, blended with the second nearest
               where the two meet (heights within MEET_M, a fork), so no step there and no bump between two roads at different heights
    lanes      each band of each section, a ribbon between its left and right edges, from where SUMO starts the lane to where it ends it at a
               junction (s_from, s_to: GMNS geom_cut), with its fields (and their sources) for the popup; through a junction on the deck,
               SUMO's path from lane to lane (the profile's connectors), so the lanes of a fork or a merge do not lie on each other;
               each path on the deck that is no band (it turns, crosses or joins) along its own line (the profile's paths)
    lines      an edge line at the outer edge of each run of lanes, a lane line between two lanes of one direction, the centre line
               between the two directions
    piers      a wall across the deck at each pier, down to the ground
Coordinates: metres east and north of the model's origin (the middle of its outline's bounds), and up.
"""
import json

STEP_M = 4.0        # the outline and the bands are sampled this often, so their heights follow the profile
BLEND_M = 40.0      # the heights of two axes are blended where the second nearest is this near
MEET_M = 1.5        # ... and only where their heights differ by less than this (they meet at a fork)
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
    xs_, ys_ = [x for x, _ in ol], [y for _, y in ol]
    x0, y0 = (min(xs_) + max(xs_)) / 2, (min(ys_) + max(ys_)) / 2       # the middle of the bridge: every part near the origin
    rel = lambda ps: [(x - x0, y - y0) for x, y in ps]
    deck = shapely.make_valid(shapely.Polygon(rel(ol)))
    deck = max(shapely.get_parts(deck), key=lambda p: p.area) if deck.geom_type != "Polygon" else deck
    DECK_M, RAIL_M = P["deck"]["thickness"]["value"], P["deck"]["parapet"]["value"]
    axes = [(shapely.LineString(rel(a["line"]["value"])), a) for a in P["axes"]]
    by_id = {a["id"]: (ln, a) for ln, a in axes}

    def z(x, y):
        """The deck's top at (x, y): the nearest axis's vertical profile, blended with the second nearest (each weighted by the other's
        distance) only where the two meet (their heights within MEET_M: a fork); two roads side by side at other heights keep their own."""
        p = shapely.Point(x, y)
        near = sorted(((ln.distance(p), _z(a["vertical"]["points"], ln.project(p))) for ln, a in axes), key=lambda dz: dz[0])[:2]
        if len(near) < 2 or near[1][0] > BLEND_M or abs(near[0][1] - near[1][1]) > MEET_M:
            return near[0][1]
        (d1, z1), (d2, z2) = near
        return (z1 * d2 + z2 * d1) / ((d1 + d2) or 1)

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
    # the deck's bottom never under the ground: near a landing the deck gets thinner and meets the street flush (the bridge is drawn over
    # the flat map, which has no depth: a slab under the ground showed as a block standing on it)
    under = lambda zz: max(zz - DECK_M, 0.0)
    bottom = [[vid(x, y, under(z(x, y))) for x, y in t.exterior.coords[:3]][::-1] for t in tris]
    sides, rails = [], []
    for ring in [dense.exterior] + list(dense.interiors):
        c = list(ring.coords)
        for (ax, ay), (bx, by) in zip(c, c[1:]):
            za, zb = z(ax, ay), z(bx, by)
            a0, b0, a1, b1 = vid(ax, ay, under(za)), vid(bx, by, under(zb)), vid(ax, ay, za), vid(bx, by, zb)
            sides += [[a0, b0, b1], [a0, b1, a1]]
            r0, r1 = vid(ax, ay, za + min(RAIL_M, za)), vid(bx, by, zb + min(RAIL_M, zb))     # a parapet ends where the deck lands
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
            out.append([round(x + nx * t, 2), round(y + ny * t, 2), round(_z(a["vertical"]["points"], s) + lift, 2)])     # its own axis
        return out

    def ribbon(line, w, lift):
        """The left and right edges of a strip w wide along a line, every STEP_M, at the deck's height plus lift."""
        line = line.segmentize(STEP_M)
        l_, r_ = [], []
        for k in range(len(line.coords)):
            x, y, nx, ny = frame(line, line.project(shapely.Point(line.coords[k])))
            for e_, sg in ((l_, 1), (r_, -1)):
                px, py = x + nx * sg * w / 2, y + ny * sg * w / 2
                e_.append([round(px, 2), round(py, 2), round(z(px, py) + lift, 2)])
        return l_, r_
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
                f_, t_ = b.get("s_from", sec["s0"]), b.get("s_to", sec["s1"])
                if t_ - f_ < 0.5:       # (inside a junction: a connector covers it)
                    continue
                lanes.append({"props": props, "l": along(ln, a, f_, t_, b["t"] + w / 2, 0.03), "r": along(ln, a, f_, t_, b["t"] - w / 2, 0.03)})
            # painted lines: across the lanes of the section, from left to right
            ls, paint = [b for b in sec["bands"] if b["type"] == "lane"], []
            f_ = min((b.get("s_from", sec["s0"]) for b in ls), default=sec["s0"])
            t_ = max((b.get("s_to", sec["s1"]) for b in ls), default=sec["s1"])
            for i, b in enumerate(ls):
                left, right = b["t"] + b["width"]["value"] / 2, b["t"] - b["width"]["value"] / 2
                if i == 0 or abs(ls[i - 1]["t"] - ls[i - 1]["width"]["value"] / 2 - left) > TOUCH_M:
                    paint.append(("edge line", left))
                if i + 1 < len(ls) and abs(ls[i + 1]["t"] + ls[i + 1]["width"]["value"] / 2 - right) <= TOUCH_M:
                    nb = ls[i + 1]
                    paint.append(("centre line" if nb["direction"] != b["direction"] else "lane line", (right + nb["t"] + nb["width"]["value"] / 2) / 2))
                else:
                    paint.append(("edge line", right))
            if t_ - f_ >= 0.5:
                lines += [{"kind": k, "ref": a["id"], "pts": along(ln, a, f_, t_, t, 0.06)} for k, t in paint]
    for f in P.get("paths", []):            # a path on the deck that is no band of an axis, along its own line
        fl = shapely.LineString(rel(f["line"]))
        if fl.length < 0.5:
            continue
        l_, r_ = ribbon(fl, f["width"]["value"], 0.04)
        lanes.append({"props": {"type": f["type"], "name": f.get("name") or P["name"], "osm": f["way"], "width_m": f["width"]["value"],
                                "width_source": f["width"]["source"], "width_method": f["width"]["method"], "source": f["source"],
                                "method": f["method"]}, "l": l_, "r": r_})
    for c in P.get("connectors", []):       # SUMO's path from lane to lane through a junction on the deck
        cl = shapely.LineString(rel(c["line"]))
        if cl.length < 0.5:
            continue
        l_, r_ = ribbon(cl, c["width"]["value"], 0.04)
        lanes.append({"props": {"type": "junction lane", "name": P["name"], "connector": c["id"], "from_lane": c["from"], "to_lane": c["to"],
                                "width_m": c["width"]["value"], "width_source": c["width"]["source"], "width_method": c["width"]["method"],
                                "source": c["source"], "method": c["method"]}, "l": l_, "r": r_})
    piers = []
    for q in P["piers"]:
        ln, a = by_id[q["axis"]]
        x, y, nx, ny = frame(ln, q["s"])
        # across its own road only (its bands at s), inside the deck
        sec = next((sc for sc in a["sections"] if sc["s0"] - 0.01 <= q["s"] <= sc["s1"] + 0.01), None)
        bs = sec["bands"] if sec else []
        lo = min((b["t"] - b["width"]["value"] / 2 for b in bs), default=-4.0) + 1.0
        hi = max((b["t"] + b["width"]["value"] / 2 for b in bs), default=4.0) - 1.0
        cut = shapely.LineString([(x + nx * lo, y + ny * lo), (x + nx * hi, y + ny * hi)]).intersection(deck.buffer(0.5))
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
