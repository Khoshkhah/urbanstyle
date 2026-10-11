"""A bridge as a 3D model for the dashboard's three.js layer (docs/design/bridges-3d.md).

From OSM (a duckOSM database large enough to hold the whole bridge):
    deck       the bridge's outline (man_made=bridge with the name), its top as triangles
    roads      the roads on it (highway=* with bridge=*, inside the outline), their lanes (OSM `lanes`, `lanes:forward`, `lanes:backward`)
    paths      the cycleways and footways on it
    ends       where those roads meet a road that is not a bridge: there the deck is at the ground
urbanstyle's own (chosen; OSM gives no heights):
    the deck rises from the ground at the ends with GRADE, to TOP_M at most; it is DECK_M thick; piers every PIER_M where it is higher
    than PIER_MIN_M; a parapet RAIL_M high along the outline; a lane is LANE_M wide (OSM gives no width)
Coordinates: metres east and north of the model's origin (its first outline point), and up.
"""
import json

GRADE = 0.05        # the ramps rise 5 m in 100 m (chosen)
TOP_M = 27.0        # the deck at most this high above the ground at its ends (chosen; LiDAR will measure it)
DECK_M = 1.8        # deck and girders, thick (chosen)
PIER_M = 50.0       # a pier every (chosen)
PIER_MIN_M = 3.0    # no pier under a deck lower than this
RAIL_M = 1.1        # parapet height (chosen)
LANE_M = 3.3        # a lane's width, where OSM gives none (chosen)
STEP_M = 4.0        # the outline is densified to this, so its heights follow the profile


def model(osm_db, name):
    import duckdb
    import shapely
    from shapely.ops import substring

    o = duckdb.connect(osm_db, read_only=True)
    nodes = lambda ids: {i: (x, y) for i, y, x in o.execute(f"SELECT osm_id, lat, lon FROM raw.nodes WHERE osm_id IN ({','.join(map(str, ids)) or '0'})").fetchall()}
    outl = o.execute("SELECT osm_id, refs FROM raw.ways WHERE tags['man_made'] = 'bridge' AND tags['name'] = ? ORDER BY len(refs) DESC LIMIT 1",
                     [name]).fetchone()
    if outl is None:
        raise ValueError(f"no man_made=bridge named {name!r} in {osm_db}")
    ways = o.execute("""SELECT osm_id, refs, tags FROM raw.ways WHERE tags['highway'] IS NOT NULL AND tags['bridge'] IS NOT NULL
                        AND coalesce(tags['bridge'], 'no') <> 'no'""").fetchall()
    ll = nodes({r for r in outl[1]})
    lon0, lat0 = ll[outl[1][0]]
    import pyproj
    zone = int((lon0 + 180) // 6) + 1
    tr = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{32600 + zone}", always_xy=True).transform
    x0, y0 = tr(lon0, lat0)
    xy = lambda lon, lat: (lambda p: (p[0] - x0, p[1] - y0))(tr(lon, lat))
    deck = shapely.Polygon([xy(*ll[r]) for r in outl[1]])
    deck = shapely.make_valid(deck)
    deck = max(shapely.get_parts(deck), key=lambda p: p.area) if deck.geom_type != "Polygon" else deck
    near = deck.buffer(5.0)
    # the roads and paths on the deck
    allref = {r for _, refs, _ in ways for r in refs}
    pts = nodes(allref)
    on = []
    for oid, refs, tags in ways:
        if any(r not in pts for r in refs) or len(refs) < 2:
            continue
        ln = shapely.LineString([xy(*pts[r]) for r in refs])
        if ln.intersection(near).length > 0.6 * ln.length:
            on.append((oid, refs, dict(tags), ln))
    # the ends: nodes of those roads that a road not on a bridge also uses
    mine = {r for _, refs, _, _ in on for r in refs}
    ground = {r for (r,) in o.execute(f"""SELECT DISTINCT unnest(refs) FROM raw.ways WHERE tags['highway'] IS NOT NULL
                                           AND coalesce(tags['bridge'], 'no') = 'no'""").fetchall()} & mine
    ends = shapely.MultiPoint([xy(*pts[r]) for r in ground]) if ground else shapely.MultiPoint([deck.exterior.coords[0]])

    def z(x, y):
        return min(TOP_M, GRADE * ends.distance(shapely.Point(x, y)))

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

    def runs(ln):
        """Samples every STEP_M along ln, on the deck: [[(x, y, unit normal to the left)], ...] (a new run where it leaves the deck)."""
        cs = list(ln.segmentize(STEP_M).coords)
        out, cur = [], []
        for k, (x, y) in enumerate(cs):
            (ax, ay), (bx, by) = cs[max(k - 1, 0)], cs[min(k + 1, len(cs) - 1)]
            dx, dy = bx - ax, by - ay
            h = (dx * dx + dy * dy) ** .5 or 1
            if near.contains(shapely.Point(x, y)):
                cur.append((x, y, -dy / h, dx / h))
            elif cur:
                out.append(cur)
                cur = []
        return [r for r in out + [cur] if len(r) >= 2]
    at = lambda q, off, lift: [round(q[0] + q[2] * off, 2), round(q[1] + q[3] * off, 2), round(z(q[0] + q[2] * off, q[1] + q[3] * off) + lift, 2)]
    lines = []      # {kind, ref, pts}: lane lines, carriageway edges, the centre line
    lanes = []      # {props, l, r}: each lane (and each path) a ribbon between its left and right edges, with its fields
    for oid, refs, tags, ln in on:
        hw = tags.get("highway")
        rname = tags.get("name")
        rs = runs(ln)
        if hw in ("cycleway", "footway", "path", "pedestrian"):
            w = 3.0 if hw == "cycleway" else 2.0
            for r in rs:
                lanes.append({"props": {"type": "cycleway" if hw == "cycleway" else "footway", "name": rname, "osm": f"w{oid}", "source": "osm",
                                        "method": "mapped", "width_m": w, "width_source": "urbanstyle", "width_method": "chosen"},
                              "l": [at(q, w / 2, 0.04) for q in r], "r": [at(q, -w / 2, 0.04) for q in r]})
            continue
        try:
            n = int(tags.get("lanes", "0").split(";")[0])
        except ValueError:
            n = 0
        oneway = tags.get("oneway") in ("yes", "-1")
        tagged = n > 0
        n = n or (1 if oneway else 2)
        fw = int(tags["lanes:forward"]) if tags.get("lanes:forward", "").isdigit() else (n if oneway else n - n // 2)
        bw = n - fw
        half = n * LANE_M / 2
        turns = {"forward": (tags.get("turn:lanes:forward") or (tags.get("turn:lanes") if oneway else None) or "").split("|"),
                 "backward": (tags.get("turn:lanes:backward") or "").split("|")}
        # (left +): a two-way way's backward lanes on its left, forward lanes on its right; OSM draws the way along the middle
        for k in range(n):
            off_l, off_r = half - k * LANE_M, half - (k + 1) * LANE_M
            d = "backward" if k < bw else "forward"
            num = k + 1 if d == "backward" else n - k          # from the right of its own direction
            tl = turns[d]
            nd = bw if d == "backward" else fw
            turn = tl[nd - num] if len(tl) == nd and 0 <= nd - num < len(tl) and tl[nd - num] else None
            props = {"type": "lane", "name": rname, "osm": f"w{oid}", "highway": hw, "direction": d, "lane": num,
                     "lanes": tags.get("lanes"), "turn": turn, "source": "osm" if tagged else "urbanstyle", "method": "mapped" if tagged else "chosen",
                     "width_m": LANE_M, "width_source": "urbanstyle", "width_method": "chosen", "height": "urbanstyle, chosen (bridge3d.py)"}
            for r in rs:
                lanes.append({"props": props, "l": [at(q, off_l, 0.03) for q in r], "r": [at(q, off_r, 0.03) for q in r]})
        for k in range(n + 1):
            off = half - k * LANE_M
            kind = "edge line" if k in (0, n) else ("centre line" if not oneway and k == bw else "lane line")
            for r in rs:
                lines.append({"kind": kind, "ref": f"w{oid}", "pts": [at(q, off, 0.06) for q in r]})
    # piers: a wall across the deck every PIER_M along the longest road on it, where the deck is high enough
    piers = []
    if on:
        spine = max((ln for *_, ln in on), key=lambda g: g.length)
        merged = shapely.line_merge(shapely.union_all([ln for _, _, t, ln in on if t.get("highway") not in ("cycleway", "footway", "path")]))
        for spine in sorted(shapely.get_parts(merged), key=lambda g: -g.length)[:1]:
            s = PIER_M / 2
            while s < spine.length:
                p = spine.interpolate(s)
                a, b = spine.interpolate(max(s - 1, 0)), spine.interpolate(min(s + 1, spine.length))
                dx, dy = b.x - a.x, b.y - a.y
                h = (dx * dx + dy * dy) ** .5 or 1
                cut = shapely.LineString([(p.x + dy / h * 80, p.y - dx / h * 80), (p.x - dy / h * 80, p.y + dx / h * 80)]).intersection(deck.buffer(-2.0))
                zz = z(p.x, p.y) - DECK_M
                if zz >= PIER_MIN_M:
                    for seg in shapely.get_parts(cut):
                        if seg.geom_type == "LineString" and seg.length > 2:
                            (ax, ay), (bx, by) = seg.coords[0], seg.coords[-1]
                            piers.append({"a": [round(ax, 2), round(ay, 2)], "b": [round(bx, 2), round(by, 2)], "t": 1.5, "h": round(zz, 2)})
                s += PIER_M
    return {"name": name, "origin": [lon0, lat0], "outline": [list(ll[r]) for r in outl[1]], "verts": verts, "deck": top + bottom,
            "sides": sides, "rails": rails, "lines": lines, "lanes": lanes, "piers": piers,
            "sources": {"outline": f"osm w{outl[0]} (man_made=bridge), mapped", "roads, lanes, paths": "osm, mapped: " +
                        ", ".join(f"w{oid}" for oid, *_ in on),
                        "heights": f"urbanstyle, chosen: {GRADE:.0%} up from the ends where its roads meet ground roads, at most {TOP_M} m; "
                                   f"deck {DECK_M} m, parapet {RAIL_M} m, piers every {PIER_M} m",
                        "lane width": f"urbanstyle, chosen: {LANE_M} m"}}


if __name__ == "__main__":
    import sys
    m = model(sys.argv[1], sys.argv[2])
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in m.items()}, indent=1))
