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

SEP_BARRIER_M = (0.5, 0.8)   # a barrier between the roadway and a sidewalk or path on a deck: wide, high (as bridge3d's BARRIER_SEP_M)
LANE_ARROW_MIN_M = 20.0      # a lane this long or longer gets an arrow
ARROW_TIP_BACK_M = 1.0       # ... its tip this far before the lane's end
ARROW_W_M = 0.15             # ... painted this wide
FILL_W_M = 6.0          # a piece of deck no space covers, narrower than this, joins the nearest space (Granville's holes at forks: 3-4 m)
SAME_Z_M = 1.0          # two spaces of different levels that meet within this height of each other join there: no wall, no guard
JOINT_M = 0.5           # two spaces of one level this near each other touch: a joint, no edge, no guard
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
    # the deck no space covers, in thin strips (under FILL_W_M wide) along the spaces: the nearest space's, so the slab is whole and the
    # guards stand on the deck's edge (Granville: 2 m strips along the edges were holes with guards and walls inside the deck)
    if units:
        cover_ = shapely.union_all([v[2] for v in units.values()])
        for pc in shapely.get_parts(deck_polygon(P).difference(cover_)):
            if pc.geom_type != "Polygon" or pc.area < 0.5 or not pc.buffer(-FILL_W_M / 2).is_empty:
                continue
            u_ = min(units, key=lambda k_: units[k_][2].distance(pc))
            if units[u_][2].distance(pc) < JOINT_M:
                k_, lv_, ug_ = units[u_]
                units[u_] = (k_, lv_, shapely.make_valid(ug_.union(pc.buffer(0.05))))
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

    lv_axes = {}
    for ln, a in axes:
        lv_axes.setdefault(a_lv[a["id"]], []).append((ln, a))

    # each axis's strip (its sections as wide as their bands): a point blends only the axes whose strip holds it
    from .bridge_profile import _strip
    strip_of = {}
    for ln, a in axes:
        ps_ = []
        for sec in a["sections"]:
            bs = sec.get("bands") or []
            if bs and sec["s1"] - sec["s0"] > 0.1:
                lo = min(b["t"] - b["width"]["value"] / 2 for b in bs) - 1.0
                hi = max(b["t"] + b["width"]["value"] / 2 for b in bs) + 1.0
                ps_.append(_strip(shapely.ops.substring(ln, sec["s0"], sec["s1"]), lo, hi))
        strip_of[a["id"]] = shapely.union_all(ps_) if ps_ else ln.buffer(4.0)
        shapely.prepare(strip_of[a["id"]])

    way_g = {o_: g(w_) for o_, w_ in con.execute(f"SELECT osm_id, ST_AsWKB({to_utm}) FROM work.element WHERE type = 'road'").fetchall()}

    def way_lv_at(a, p):
        """The level of axis a's way nearest to p."""
        ws_ = [int(w[1:]) for w in a["ways"] if int(w[1:]) in way_g]
        if not ws_:
            return a_lv[a["id"]]
        return lv_of.get(min(ws_, key=lambda o_: way_g[o_].distance(p)), a_lv[a["id"]])

    def z_at(u, x, y):
        """The height at (x, y) of a space of level L: the axes of level L whose strip holds the point, blended by nearness (two
        meet at a fork); else the nearest axis of level L. (Blending any near axis tilted junctions by up to 2.9 m: an axis that only
        passes by at another height pulled the deck; Monaco i2-21927897, Kaveh 2026-10-17.)"""
        p = shapely.Point(x, y)
        lv = units[u][1]
        # (an axis counts where its way nearest to the point is on this level: a5 runs from level 2 down to level 1, and its low part
        # pulled a level-2 junction down 2.9 m)
        cand = [la for la in axes if way_lv_at(la[1], p) == lv] or own[u]
        holds = [la for la in cand if shapely.contains_xy(strip_of[la[1]["id"]], x, y)]
        if len(holds) == 1 or not holds:
            ln, a = holds[0] if holds else min(cand, key=lambda la: la[0].distance(p))
            return max(0.0, height(a["vertical"], ln.project(p)))
        ws = [(1.0 / (ln.distance(p) + 0.5) ** 2, max(0.0, height(a["vertical"], ln.project(p)))) for ln, a in holds]
        return sum(w * z for w, z in ws) / sum(w for w, _ in ws)

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
                if others.distance(mid) < JOINT_M:
                    continue            # (the next space of its level: the deck goes on; a 5 cm test put guards across the lanes at joints)
                # (or a space of another level at the same height there: a ramp of level 2 that joins a road of level 1 at a node in the
                # air; each put a side wall and a guard on the shared edge, grey plates beside the junction)
                nb = [u2 for u2, (k2, lv2, g2) in units.items() if u2 != u and lv2 != lv and g2.distance(mid) < JOINT_M]
                if nb and min(abs(z_at(u2, mid.x, mid.y) - z_at(u, mid.x, mid.y)) for u2 in nb) < SAME_Z_M:
                    continue
                za, zb = z_at(u, ax, ay), z_at(u, bx, by)
                if max(za, zb) >= OFF_GROUND_M:        # (none where the deck is on the ground: a walled box at a landing)
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
    # (the area of a space no part covers is drawn as roadway, not as the bare slab's grey: grey patches on the lanes; it is only drawn,
    # not a part: no source gives it)
    parts_by_u = {}
    for pr, pg in parts:
        parts_by_u.setdefault(pr["unit_id"], []).append(pg)
    for u, (k, lv, ug) in units.items():
        bare = ug.difference(shapely.union_all(parts_by_u.get(u, []) or [shapely.Polygon()]).buffer(0.05))
        bare = shapely.union_all([q for q in shapely.get_parts(bare) if q.geom_type == "Polygon" and q.area > 0.3] or [shapely.Polygon()])
        if not bare.is_empty:       # (in the colour of the roadway around it: "paved" is grey too, the patches stayed grey)
            mesh(u, bare, "lane", LIFT_M)
    # the painted lines, each dashed as its kind is in urban.style (a lane line 3 m on, 6 m off: they were drawn solid)
    try:
        dash_ = {k_: d_ for k_, d_ in con.execute("SELECT kind, dash FROM urban.style WHERE \"table\" = 'urban.mark' AND dash IS NOT NULL").fetchall()}
    except Exception:
        dash_ = {}

    def dashed(ln_, d_):
        on_, off_ = d_[0], d_[1]
        out_, s0_ = [], 0.0
        while s0_ < ln_.length:
            out_.append(shapely.ops.substring(ln_, s0_, min(s0_ + on_, ln_.length)))
            s0_ += on_ + off_
        return shapely.union_all(out_) if out_ else shapely.LineString()
    for u, t, wd, mg in marks:
        if u not in units or t == "kerb":
            continue
        w_ = float(wd) if wd else PAINT_M
        if mg.geom_type in ("LineString", "MultiLineString"):
            if dash_.get(t):
                mg = shapely.union_all([dashed(l_, dash_[t]) for l_ in shapely.get_parts(mg) if l_.length > 0.1])
            pg = mg.buffer(w_ / 2, cap_style="flat")
        else:
            pg = mg
        mesh(u, pg, f"mark {t}", LIFT_M + PAINT_LIFT_M)

    # an arrow on each lane LANE_ARROW_MIN_M or longer, straight, its tip ARROW_TIP_BACK_M before the lane's end in its direction (the
    # ground's arrows come from the turns at level 0; a deck had none)
    from .network import arrow_shape
    from .parts import ARROW_M
    way_ln = {o_: g(w_) for o_, w_ in con.execute(f"SELECT osm_id, ST_AsWKB({to_utm}) FROM work.element WHERE type = 'road' AND level_min >= 1").fetchall()}
    for pr, pg in parts:
        if pr["type"] != "lane" or pr["unit_id"] not in units or pr.get("direction") not in ("forward", "backward"):
            continue
        ref_ = str(pr.get("ref") or "")
        oid_ = int(ref_[1:]) if ref_[:1] == "w" and ref_[1:].isdigit() else None
        wl_ = way_ln.get(oid_) if oid_ else None
        if wl_ is None:
            near_ = sorted(way_ln.values(), key=lambda l_: l_.distance(pg))
            wl_ = near_[0] if near_ else None
        if wl_ is None or wl_.geom_type != "LineString":
            continue
        piece_ = wl_.intersection(pg.buffer(3.0))
        piece_ = max(shapely.get_parts(piece_), key=lambda l_: l_.length) if not piece_.is_empty else piece_
        if piece_.is_empty or piece_.geom_type != "LineString" or piece_.length < LANE_ARROW_MIN_M:
            continue
        c_ = list(piece_.coords)
        if pr["direction"] == "backward":
            c_ = c_[::-1]
        ln_ = shapely.LineString(c_)
        s_tip = ln_.length - ARROW_TIP_BACK_M
        q_ = ln_.interpolate(s_tip); q0_ = ln_.interpolate(max(s_tip - 1.0, 0.0))
        hx_, hy_ = q_.x - q0_.x, q_.y - q0_.y
        hn_ = math.hypot(hx_, hy_) or 1
        off_ = pg.representative_point()            # (onto the lane's own middle: the way's line can run beside it)
        dx_, dy_ = -hy_ / hn_, hx_ / hn_
        d_ = (off_.x - q_.x) * dx_ + (off_.y - q_.y) * dy_
        tip_ = (q_.x + dx_ * d_, q_.y + dy_ * d_)
        shp_ = arrow_shape(tip_, (hx_ / hn_, hy_ / hn_), {"straight"}).buffer(ARROW_W_M / 2)      # (lines: painted ARROW_W_M wide)
        shp_ = shp_.intersection(pg) if shp_ is not None and not shp_.is_empty else shp_
        if shp_ is not None and not shp_.is_empty:
            mesh(pr["unit_id"], shp_, "mark arrow", LIFT_M + PAINT_LIFT_M)

    # a barrier where the roadway meets a sidewalk or a path (as on the ground's bridges before: Kaveh, 2026-10-11), not at a crosswalk
    for u in units:
        road_ = shapely.union_all([pg for pr, pg in parts if pr["unit_id"] == u and pr["type"] == "lane"]
                                  or [shapely.Polygon()])       # (beside the lanes only: at a junction's corners and gores the barrier
                                                                # cut wedges, grey plates; a cycle lane is the bicycles', a barrier there)
        walk_ = shapely.union_all([pg for pr, pg in parts if pr["unit_id"] == u and pr["type"] in ("sidewalk", "path", "cycle lane")] or [shapely.Polygon()])
        if road_.is_empty or walk_.is_empty:
            continue
        xw_ = shapely.union_all([pg.buffer(1.5) for pr, pg in parts if pr["unit_id"] == u and pr["type"] in ("crosswalk", "cycle crossing")]
                               or [shapely.Polygon()])
        edge_ = road_.boundary.intersection(walk_.buffer(0.1)).difference(xw_)
        segs_ = [l_ for l_ in shapely.get_parts(shapely.line_merge(edge_) if not edge_.is_empty else edge_)
                 if l_.geom_type == "LineString" and l_.length > 1.5]
        if segs_:
            bar_ = shapely.union_all([l_.buffer(SEP_BARRIER_M[0] / 2, cap_style="flat") for l_ in segs_]).intersection(walk_)
            if not bar_.is_empty:
                mesh(u, bar_, "barrier", LIFT_M, {"id": f"barrier {u}", "type": "barrier", "bridge": P["name"], "height_m": SEP_BARRIER_M[1],
                                                   "source": "urbanstyle", "method": "derived", "rule": "between the roadway and a sidewalk or path on a deck"},
                     SEP_BARRIER_M[1])

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

    # ---- the structure under the deck: two columns under each pier with free space between them, and the steel truss with its own
    # piers, legs and bents where corrections/bridges.json names one (bridge_structure: the old model's agreed code)
    from .bridge_structure import structure

    def frame(ln, s_):
        p_, a_, b_ = ln.interpolate(s_), ln.interpolate(max(s_ - 1, 0)), ln.interpolate(min(s_ + 1, ln.length))
        h_ = math.hypot(b_.x - a_.x, b_.y - a_.y) or 1
        return p_.x, p_.y, -(b_.y - a_.y) / h_, (b_.x - a_.x) / h_
    piers_p, truss_p = structure(P, axes, deck_polygon(P), frame, DECK_M)
    piers = [{"a": tm(*q["a"], 0)[:2], "b": tm(*q["b"], 0)[:2], "t": q["t"], "h": q["h"]} for q in piers_p if q["h"] > 0.5]
    truss = [dict(q, a=tm(*q["a"]), b=tm(*q["b"])) for q in truss_p]

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
         "truss": truss, "surf": surf, "checks": checks, "flat": flat, "deck_ll": deck_ll,
         "sources": {"model": "deck3d: the street of the deck levels (network.py) at the profile's heights"}}
    return m, set(units)
