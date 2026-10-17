"""The street of every deck level in 3D (docs/notes/bridges-street-model.md): the spaces, parts and marks that network.py makes on level 1
and up, by the same rules as the ground, lifted to the heights of their bridge profile, with the deck under them.

    heights  each point of a space at level L takes the height of the nearest profile axis of level L that crosses the space (two axes
             meet at one height, the profile rule); an axis of another level never: a deck that crosses another keeps its own heights
    slab     under each space, at that space's heights, as thick as the profile's deck: two spaces that cross have two slabs
    sides    the slab's edge where no space of the same level touches it
    guards   along those edges too, except where a roadway part reaches the edge across its axis (a road end: open) or the deck is on the
             ground; so no guard crosses a road
    parts    each part at its height, raised by its kind (urban.style raise_m); marks as thin strips on top
    piers    from the profile

The result has the format of bridge3d.model, so the page draws it unchanged: `models(con, bridges)` -> (models, the units drawn).
"""
import json
import math

GUARD_M = (0.8, 0.3)    # a guard: this high and this wide (chosen, as bridge3d's)
STEP_M = 5.0            # the slab and the parts are cut by this grid, so they follow the heights
PAINT_M = 0.12          # a painted line's width where the mark has none (chosen)
LIFT_M = 0.03           # a part above the slab's top, so the two never fight for the same depth
PAINT_LIFT_M = 0.06     # a painted line above its part
OFF_GROUND_M = 0.3      # a deck lower than this is on the ground: no guard
END_ANGLE = 45.0        # an edge more than this across its axis, where a roadway part reaches it, is a road end: no guard
ROADWAY = ("lane", "junction area", "paved", "parking", "no parking", "bus lane", "cycle lane", "shoulder", "bridge deck")
RAISED = {"sidewalk": 0.15, "island": 0.15, "furnishing": 0.15, "frontage": 0.15, "verge": 0.15, "median": 0.15, "path": 0.15}
NEW_CHECKS = ("BR13", "BR14", "BR15")


def _grid_tris(poly, step=STEP_M):
    """poly cut by a grid of step and triangulated inside: [triangle]."""
    import shapely
    from .bridge3d import grid
    out = []
    for c in grid(poly.segmentize(step), step):
        for pc in shapely.get_parts(c):
            if pc.geom_type == "Polygon" and pc.area > 1e-4:
                out += [t for t in shapely.get_parts(shapely.constrained_delaunay_triangles(pc))
                        if t.representative_point().within(pc.buffer(0.01))]
    return out


def models(con, bridges):
    """One model per bridge profile, from the street of its deck levels: (models, the unit ids they draw)."""
    ms, drawn = [], set()
    for pf in bridges:
        m, us = model(con, json.load(open(pf)))
        ms.append(m)
        drawn |= us
    return ms, drawn


def model(con, P):
    import pyproj
    import shapely
    import shapely.ops
    from .bridge_profile import deck_polygon, height
    crs = P["crs"]
    to_utm = f"ST_Transform(geometry, 'EPSG:4326', '{crs}', always_xy := true)"
    g = lambda w: shapely.make_valid(shapely.from_wkb(bytes(w)))
    deck = deck_polygon(P).buffer(1.0)
    DECK_M = P["deck"]["thickness"]["value"]
    # the axes and their level (their OSM ways' level)
    axes = [(shapely.LineString([q[:2] for q in a["line"]["value"]]), a) for a in P["axes"]]
    lv_of = dict(con.execute("SELECT osm_id, level_min FROM work.element WHERE type = 'road'").fetchall())
    a_lv = {}
    for ln, a in axes:
        ls = [lv_of.get(int(w[1:])) for w in a["ways"] if lv_of.get(int(w[1:])) is not None]
        a_lv[a["id"]] = max(set(ls), key=ls.count) if ls else 1
    # the spaces of level 1 and up on this deck, their parts and marks
    units = {u: (k, lv, g(w)) for u, k, lv, w in con.execute(
        f"SELECT unit_id, kind, level, ST_AsWKB({to_utm}) FROM work.unit WHERE level >= 1 AND geometry IS NOT NULL").fetchall()}
    units = {u: v for u, v in units.items() if v[2].intersects(deck)}
    ids = sorted(units)
    pf = ["part_id", "unit_id", "level", "type", "direction", "lane", "lane_id", "width_m", "road", "source", "method", "ref", "rule"]
    have = {r[0] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'work' AND table_name = 'part'").fetchall()}
    sel = ", ".join(c if c in have else f"NULL AS {c}" for c in pf)
    parts = [(dict(zip(pf, r[:-1])), g(r[-1])) for r in con.execute(
        f"SELECT {sel}, ST_AsWKB({to_utm}) FROM work.part WHERE unit_id IN (SELECT unnest(?::VARCHAR[])) AND geometry IS NOT NULL", [ids]).fetchall()]
    marks = [(u, t, wd, g(w)) for u, t, wd, w in con.execute(
        f"SELECT unit_id, type, width_m, ST_AsWKB({to_utm}) FROM work.mark WHERE unit_id IN (SELECT unnest(?::VARCHAR[])) "
        "AND geometry IS NOT NULL", [ids]).fetchall()]
    try:
        raise_ = dict(con.execute("SELECT kind, raise_m FROM urban.style WHERE raise_m IS NOT NULL").fetchall())
    except Exception:
        raise_ = {}

    # ---- the heights: a space's own axes are those of its level that cross it; a point takes the nearest of them
    own = {}
    for u, (k, lv, ug) in units.items():
        cand = [(ln, a) for ln, a in axes if a_lv[a["id"]] == lv and ln.intersects(ug.buffer(1.0))]
        own[u] = cand or [min(axes, key=lambda la: la[0].distance(ug))]

    def z_at(u, x, y):
        p = shapely.Point(x, y)
        ln, a = min(own[u], key=lambda la: la[0].distance(p))
        return max(0.0, height(a["vertical"], ln.project(p)))

    # ---- the frame: the map's metres around the deck's middle, as bridge3d (Web Mercator scaled to true metres at the origin)
    c0 = deck.centroid
    to_ll = pyproj.Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform
    lon0, lat0 = to_ll(c0.x, c0.y)
    merc = pyproj.Transformer.from_crs(crs, "EPSG:3857", always_xy=True).transform
    mx0, my0 = merc(c0.x, c0.y)
    kk = math.cos(math.radians(lat0))

    def tm(x, y, zz):
        X, Y = merc(x, y)
        return [round((X - mx0) * kk, 2), round((Y - my0) * kk, 2), round(zz, 2)]

    verts, vix = [], {}

    def vid(x, y, zz):
        key = (round(x, 2), round(y, 2), round(zz, 2))
        if key not in vix:
            vix[key] = len(verts)
            verts.append(tm(x, y, zz))
        return vix[key]

    # ---- the slab under each space, and its sides where no space of its level touches it
    slab, sides = [], []
    same_lv = {}
    for u, (k, lv, ug) in units.items():
        same_lv.setdefault(lv, []).append(ug)
    lv_union = {lv: shapely.union_all(gs) for lv, gs in same_lv.items()}
    outer = {}
    for u, (k, lv, ug) in units.items():
        for t in _grid_tris(ug):
            c = t.exterior.coords[:3]
            top = [vid(x, y, z_at(u, x, y)) for x, y in c]
            bot = [vid(x, y, max(0.0, z_at(u, x, y) - DECK_M)) for x, y in c]
            slab += [top, bot[::-1]]
        others = shapely.union_all([g_ for u2, (k2, lv2, g_) in units.items() if u2 != u and lv2 == lv] or [shapely.Polygon()])
        segs = []
        for ring in [ug.exterior] + list(ug.interiors) if ug.geom_type == "Polygon" else \
                [r for pg in shapely.get_parts(ug) if pg.geom_type == "Polygon" for r in [pg.exterior] + list(pg.interiors)]:
            cs = list(ring.segmentize(STEP_M / 2).coords)
            for (ax, ay), (bx, by) in zip(cs, cs[1:]):
                mid = shapely.Point((ax + bx) / 2, (ay + by) / 2)
                if others.distance(mid) < 0.05:
                    continue            # (the next space of its level: the deck goes on)
                za, zb = z_at(u, ax, ay), z_at(u, bx, by)
                a0, b0, a1, b1 = vid(ax, ay, max(0.0, za - DECK_M)), vid(bx, by, max(0.0, zb - DECK_M)), vid(ax, ay, za), vid(bx, by, zb)
                sides += [[a0, b0, b1], [a0, b1, a1]]
                segs.append(((ax, ay), (bx, by)))
        outer[u] = segs

    # ---- the parts and the marks, at their heights
    surf, flat = [], []

    def mesh(u, poly, key, lift, props=None, rise=0.0):
        v, f, ix = [], [], {}

        def vi(x, y, zz):
            q = (round(x, 2), round(y, 2), round(zz, 2))
            if q not in ix:
                ix[q] = len(v)
                v.append(tm(x, y, zz))
            return ix[q]
        for pg in shapely.get_parts(shapely.make_valid(poly)):
            if pg.geom_type != "Polygon" or pg.area < 0.02:
                continue
            for t in _grid_tris(pg):
                f.append([vi(x, y, z_at(u, x, y) + lift + rise) for x, y in t.exterior.coords[:3]])
            if rise > 0:                # (its sides down to the deck, a kerb's face)
                for ring in [pg.exterior] + list(pg.interiors):
                    cs = list(ring.segmentize(STEP_M / 2).coords)
                    for (ax, ay), (bx, by) in zip(cs, cs[1:]):
                        za, zb = z_at(u, ax, ay) + lift, z_at(u, bx, by) + lift
                        a0, b0, a1, b1 = vi(ax, ay, za), vi(bx, by, zb), vi(ax, ay, za + rise), vi(bx, by, zb + rise)
                        f += [[a0, b0, b1], [a0, b1, a1]]
        if f:
            surf.append({"key": key, "props": props, "v": v, "f": f})
            if props:
                flat.append((props, key.split(" ")[0], shapely.ops.transform(to_ll, poly)))

    road_by_u = {}
    for pr, pg in parts:
        u, kind = pr["unit_id"], pr["type"]
        if u not in units:
            continue
        props = {k_: v_ for k_, v_ in pr.items() if v_ is not None}
        props.update({"id": pr["part_id"], "bridge": P["name"], "height": "the bridge profile's, at the part's own axis"})
        key = f"{kind} {pr['direction']}" if kind == "lane" and pr.get("direction") else kind
        mesh(u, pg, key, LIFT_M, props, float(raise_.get(kind, RAISED.get(kind, 0.0)) or 0.0))
        if kind in ROADWAY:
            road_by_u.setdefault(u, []).append(pg)
    for u, t, wd, mg in marks:
        if u not in units or t == "kerb":
            continue
        w_ = float(wd) if wd else PAINT_M
        pg = mg.buffer(w_ / 2, cap_style="flat") if mg.geom_type in ("LineString", "MultiLineString") else mg
        mesh(u, pg, f"mark {t}", LIFT_M + PAINT_LIFT_M)

    # ---- the guards: along each space's outer edge, not at a road end, not on the ground
    guard_bad = []
    for u, segs in outer.items():
        road = shapely.union_all(road_by_u.get(u, []) or [shapely.Polygon()])
        keep = []
        for (ax, ay), (bx, by) in segs:
            mx, my = (ax + bx) / 2, (ay + by) / 2
            if z_at(u, mx, my) < OFF_GROUND_M:
                continue
            ln, a = min(own[u], key=lambda la: la[0].distance(shapely.Point(mx, my)))
            s_ = ln.project(shapely.Point(mx, my))
            p0, p1 = ln.interpolate(max(s_ - 1, 0)), ln.interpolate(min(s_ + 1, ln.length))
            tx, ty = p1.x - p0.x, p1.y - p0.y
            ex, ey = bx - ax, by - ay
            cosang = abs(tx * ex + ty * ey) / ((math.hypot(tx, ty) or 1) * (math.hypot(ex, ey) or 1))
            across = math.degrees(math.acos(min(1.0, cosang))) > END_ANGLE
            if across and road.distance(shapely.LineString([(ax, ay), (bx, by)])) < 0.3:
                continue                # (a road end: open)
            keep.append(shapely.LineString([(ax, ay), (bx, by)]))
        if not keep:
            continue
        lines = shapely.line_merge(shapely.union_all(keep))
        ug = units[u][2]
        band = shapely.union_all([l_.buffer(GUARD_M[1], cap_style="flat") for l_ in shapely.get_parts(lines)]).intersection(ug)
        if not band.is_empty:
            mesh(u, band, "barrier", LIFT_M, {"id": f"guard {u}", "type": "barrier", "bridge": P["name"], "height_m": GUARD_M[0],
                                              "source": "urbanstyle", "method": "derived", "rule": "along the space's outer edge, not across a road"},
                 GUARD_M[0])
            if road.intersection(band).area > 0.5:
                guard_bad.append(band.intersection(road).representative_point())

    # ---- the piers, from the profile: across their axis's lanes at s
    piers = []
    by_id = {a["id"]: (ln, a) for ln, a in axes}
    for q in P.get("piers", []):
        ln, a = by_id.get(q["axis"], (None, None))
        if ln is None:
            continue
        p = ln.interpolate(q["s"])
        p0, p1 = ln.interpolate(max(q["s"] - 1, 0)), ln.interpolate(min(q["s"] + 1, ln.length))
        h_ = math.hypot(p1.x - p0.x, p1.y - p0.y) or 1
        nx, ny = -(p1.y - p0.y) / h_, (p1.x - p0.x) / h_
        zq = height(a["vertical"], q["s"]) - DECK_M
        if zq <= 0.5:
            continue
        sec = next((sc for sc in a["sections"] if sc["s0"] - 0.01 <= q["s"] <= sc["s1"] + 0.01), None)
        bs = (sec or {}).get("bands") or []
        lo = min((b["t"] - b["width"]["value"] / 2 for b in bs), default=-3.0) + 0.5
        hi = max((b["t"] + b["width"]["value"] / 2 for b in bs), default=3.0) - 0.5
        A, B = tm(p.x + nx * lo, p.y + ny * lo, 0)[:2], tm(p.x + nx * hi, p.y + ny * hi, 0)[:2]
        piers.append({"a": A, "b": B, "t": q.get("width", 1.5) if isinstance(q.get("width"), (int, float)) else 1.5, "h": round(zq, 2)})

    # ---- the new checks (docs/notes/bridges-street-model.md, step 5)
    ll = lambda p: list(to_ll(p.x, p.y))
    on_gr = []
    for ln, a in axes:
        for s_ in [e["s"] for e in a.get("ends", []) if e.get("ground")] + list(a.get("ground_at", [])):
            if height(a["vertical"], s_) > 0.05:
                on_gr.append(ll(ln.interpolate(s_)))
    unmet = [ll(shapely.Point(c["at"])) for ln, a in axes for c in a["vertical"].get("clearances", []) if not c.get("met", True)]
    checks = [("BR13", "guards across a roadway (a road end closed)", len(guard_bad), True, [ll(p) for p in guard_bad]),
              ("BR14", "points on the ground (a road end or a road joining on the ground) not at 0 m", len(on_gr), True, on_gr),
              ("BR15", "clearances at crossings and over buildings the ramp limit does not let the deck reach", len(unmet), False, unmet)]
    deck_ll = json.loads(shapely.to_geojson(shapely.ops.transform(to_ll, deck_polygon(P))))
    m = {"name": P["name"], "origin": [lon0, lat0], "verts": verts, "deck": slab, "sides": sides, "rails": [],
         "axes": [[list(to_ll(x, y)) for x, y in a["line"]["value"]] for a in P["axes"]], "lines": [], "lanes": [], "piers": piers,
         "truss": [], "surf": surf, "checks": checks, "flat": flat, "deck_ll": deck_ll,
         "sources": {"model": "deck3d: the street of the deck levels (network.py) at the profile's heights"}}
    return m, set(units)
