"""A bridge as a 3D model for the dashboard's three.js layer (docs/design/bridges-3d.md), from its profile only
(docs/design/bridge-profile.md, `bridge_profile.py`):
    deck       the outline, its top as triangles; as thick as the profile's deck thickness, with a parapet along the outline
    heights    one surface for the deck, lanes, paths and lines: the nearest axis's vertical profile, blended with the second nearest
               where the two meet (heights within MEET_M, a fork), so no step there and no bump between two roads at different heights;
               lanes, paths and lines lie LIFT above it, in that order
    lanes      each band of each section, a ribbon between its left and right edges, from where SUMO starts the lane to where it ends it at a
               junction (s_from, s_to: GMNS geom_cut), with its fields (and their sources) for the popup; through a junction on the deck,
               SUMO's path from lane to lane (the profile's connectors), so the lanes of a fork or a merge do not lie on each other;
               each path on the deck that is no band (it turns, crosses or joins) along its own line (the profile's paths)
    lines      an edge line at the outer edge of each run of lanes, a lane line between two lanes of one direction, the centre line
               between the two directions
    piers      a wall across the deck at each pier, down to the ground
Coordinates: metres east and north of the model's origin (the middle of its outline's bounds) in the map's own projection (Web
Mercator scaled to true metres at the origin), and up.
"""
import json
import math

STEP_M = 4.0        # the outline and the bands are sampled this often, so their heights follow the profile
BLEND_M = 40.0      # the heights of two axes are blended where the second nearest is this near
MEET_M = 1.5        # ... and only where their heights differ by less than this (they meet at a fork)
FADE_M = 2.0        # an arm's weight fades to 0 over this to the edge of its lanes
OUT_FADE_M = 10.0   # ... and to nothing over this beyond its lanes and past its end (smooth: no step)
END_FADE_M = 10.0   # ... and over this to its end
LAND_PAST_M = 3.0   # ... a ground lane it lands on reaches this far past the bridge's end (it continues it)
LAND_LANE_M = 2.75  # a ground lane at least this wide is a lane: a bridge lane landing on it takes its edges
LAND_BLEND_M = 30.0 # a bridge lane moves to the street's lane it lands on over this
LIFT = {True: 0.05, False: 0.10}   # above the deck: a lane (True), a path (False); clear of each other, no flicker
LINE_LIFT_M = 0.15  # a painted line above both
SURF_LIFT_M = 0.08  # the model's lanes and junctions above the deck (on one grid with it)
PAINT_LIFT_M = 0.12 # their painted lines above them
COLUMN_M = 2.5      # a pier's column, square (chosen; 1.5 m was too narrow)
COLUMN_GAP_M = 2.0  # two columns at least this far apart, else one (chosen)
BARRIER_M = (0.8, 0.3)      # the guard: a concrete barrier this high and wide along each side of the deck (chosen)
BARRIER_SEP_M = (0.5, 0.8)  # the barrier between a path for walking and cycling and the vehicle lanes: wide, high (chosen)
RAILING_M = (1.1, 2.5)      # ... a metal railing on it, its top this high, a post every this far (chosen)
TOUCH_M = 0.5       # two lanes this close share one painted line
PATH_MIN_M = 0.5    # a piece of a path narrower than this is not drawn (a sliver left between two lanes)
GUARD_ON_LANE_M = 0.5   # no guard stands more than this inside a lane
DECK_MARGIN_M = 0.4  # the deck reaches this far past the outer lane's edge (the guard's own width)
END_EDGE_M = 3.0    # a road end's edge lies this near the axis's end, along it
PATH_BAR_MIN_M = 20.0  # ... a path at least this long (along the bridge)
EDGE_SMOOTH_R_M = 35.0  # an end whose deck edge is smoothed: this far round it
EDGE_CLOSE_M = 30.0  # (long: the deck filled as one gentle taper, "add a long buffer or footway", Kaveh, 2026-10-12)
EDGE_OPEN_M = 4.0
KEEP_BIT_M2 = 20.0  # a deck bit beside a kept path, smaller than this, is drawn with it
KEEP_HOLE_M2 = 400.0  # a hole a kept path closes in the deck, smaller than this, is deck
TRUSS_PANEL_M = 12.0  # a steel truss under a span: its panel length (chosen, from the photos)
TRUSS_CROWN_M = 1.5   # ... its bottom chord's crown this far under the deck (chosen)
TRUSS_IN_M = 1.0      # ... each side's plane this far in from the deck's edge
TRUSS_M = (0.8, 0.5)  # ... a chord's width, a vertical's or a diagonal's (chosen)
BENT_LEG_M = 1.2      # ... a steel bent's leg: its width (chosen, from the photos)
TRUSS_PIER_M = (4.0, 2.0)  # ... a concrete pier under a springing point: along the axis, out past each truss plane (photos)
TANGENT_M = 20.0    # an axis's end turned into the trunk's way at their node over this (tangent_ends)
PAIR_TANGENT_M = 20.0  # a pair's centre line leaves the trunk's node in the trunk's way, onto the middle of their lines over this
FREE_THIN_M = 1.0   # ... but a sliver of it narrower than this, beside a lane, is that lane
FREE_MIN_M2 = 0.2   # deck no part covers, this big or bigger, is the path beside it (no free space on the bridge)
LAND_FLAT_M = 3.0    # the surfaces come down flush with the ground road over this length before a landing's end
POLE_CLEAR_M = 0.4   # a lane keeps this clear of a surveyed pole (a city's lamp, OSM's): the kerb rule on the ground (blocks.md)
FREE_CHECK_M2 = 0.5  # check BR9: a piece of deck no part covers, this big or bigger
BAR_CHECK_M = 1.5    # check BR10: a lane edge on a path with no barrier, this long or longer (a path's tip is shorter)
HEIGHT_STEP_M = 0.2  # check BR11: a change in the deck's height over this between two points STEP_CHECK_M apart is a step
STEP_CHECK_M = 0.5
GORE_CLOSE_M = 4.0  # a gore filled as a path (gore_paths): the gap between the two branches closed up to twice this wide
GUARD_MIN_M = 3.0   # a guard piece shorter than this is left out
NO_GUARD_REACH_M = 15.0  # a side with no guard: this far out from its axis
PATH_PIECE_MIN_M2 = 5.0  # a drawn piece of a path smaller than this is left out
BAR_MIN_M = 6.0     # a barrier shorter than this is left out (a stub round a lane corner at a fork: barrier @297,370)
BAR_JOIN_M = 4.0    # two pieces of a barrier with ends this near are one (no crosswalk between: that gap is wider)
PATH_BAR_NEAR_M = 2.5  # a path this near the lanes has a barrier on its side towards them, at the lanes' edge (the deck between is footway too: Kaveh, 2026-10-12, "separate driving roads from footway and cycling by barrier")
JOIN_EDGE_M = 3.0   # a strip of deck joins a path only where they share this much edge
PATH_OVER_M = 0.5   # a path runs on this far past each end of its OSM line
GORE_MAX_M = 2.0    # the gore between two roads meeting at under 90 degrees is deck out to where their lanes are this far apart (chosen)
NOTCH_M = 0.5       # the deck's notches narrower than twice this are closed
HOLE_MIN_M2 = 20.0  # a hole in the deck smaller than this is filled (a slit where two pieces of the deck meet)
RECT_ROOM_M = 12.0  # a rectangle axis is a rectangle where no other axis's lanes come this near its own (past its fork)
RECT_KEEP_M = 6.0   # ... but not within this of another axis's lanes (their own paths and deck)
RECT_CUT_M = 12.0    # ... and OSM's outline is cut away this far beside it (the bits that stuck out of it)
RECT_STRAIGHT_M = 1.5  # ... its line made straight only when no point of it is further than this from straight
PIECE_TIE_M = 3.0   # ... and an OSM line that goes on past a strip, starting this near its end, starts at it
PIECE_BLEND_M = 25.0  # ... and blends back onto OSM's line over this
RECT_PIECE_M = 10.0 # ... and what is left of a path's OSM line beside a strip is kept only this long or longer
RECT_MIN_M = 50.0   # ... and a path is a strip there only where OSM maps it along at least this much of the axis
RECT_PAST_M = 8.0   # ... and past a strip's end where the road runs on, this far
RECT_TIE = False    # ... tied to them (off: with the same widths the strips meet by themselves, and the tie kinked a5)
RECT_BLEND_M = 20.0 # ... and moves to its own place over this
BESIDE_TOL_M = 5.0  # ... or one beside another: while OSM's own line stays this near that place (OSM's a4 is 2.5-4.5 m out of it)
FILLET_TURN_DEG = 60.0  # ... from a trunk it turns off by at most this at the node (a3 meets a9 at 47 degrees)
ROUND_STEP_M = 5.0  # ... on its line cut into pieces this long first
ROUND_PASSES = 3    # ... an axis with its corners rounded: this many passes of corner cutting
FOLLOW_FROM_M = 40.0  # ... or one following a path: the curve meets the moved path line this far from the node
FILLET_STRAIGHT_M = 1.0  # an axis drawn as two straight lines and a curve: its straight part keeps OSM's points this near the line
RECT_START_M = 25.0  # ... and smoothed this far round where it starts (the fork)
RECT_OPEN_M = 1.5   # ... and teeth narrower than twice this cut off there
RECT_SMOOTH_M = 3.0  # ... notches and teeth narrower than twice this closed there
FIT_MIN = 0.6       # lanes narrow to end at a mapped path beside them by at most this factor (else the path is not beside them)
LANE_MIN_M = 2.75   # ... and never under this (division's LANE_RANGE): OSM's path lines are rough, a path gives way below it
NO_TURN_DEG = 90.0  # on a bridge a move turning more than this joins the two directions: there is none
JOIN_ANGLE = 30.0   # a node where every SUMO move turns less than this (degrees) is a fork or a join, no junction
SPLIT_MAX_M = 200.0 # a branch splits off within this of the node, at most
DIVIDER_M = 0.5     # a branch leaves the main road where its lanes fit beside it with this between
TAPER_CLEAR_M = 0.5 # ... and at a fork it opens where it is this clear of the other axes' lanes
TAPER_M = 30.0      # a lane added at a landing widens from nothing over this
RAMP_BLEND_M = 70.0 # a branch beside the main road goes onto its own line over this past where its lanes fit there (5 m kinked a5's footway; "more smoother")
JOIN_BLEND_M = 40.0 # at a divided road's join, its carriageways' lanes move to the single road's over this
JUNC_SMOOTH_M = 1.0 # a junction's outline is rounded by this
JUNC_FILL_M = 10.0  # a junction on the deck reaches the ends of the lanes this near its SUMO paths
JOIN_M = 2.0        # SUMO's connector shorter than this joins a lane to its straight continuation: the two lanes meet instead
ARROW_EVERY_M = 100.0   # a direction arrow in each lane this often (one in the middle of a shorter lane), as the street's


def _h(vertical, s):
    from .bridge_profile import height
    return height(vertical, s)


def _turn(pts):
    """A move's turn in degrees (left positive), from its first two metres to its last two."""
    import shapely
    cl = shapely.LineString(pts)
    a, b = cl.coords[0], cl.interpolate(min(2.0, cl.length)).coords[0]
    c, d = cl.interpolate(max(cl.length - 2.0, 0.0)).coords[0], cl.coords[-1]
    ux, uy, vx, vy = b[0] - a[0], b[1] - a[1], d[0] - c[0], d[1] - c[1]
    return math.degrees(math.atan2(ux * vy - uy * vx, ux * vx + uy * vy))


def extend(line, d):
    """line with its first and last segments run on by d metres."""
    import shapely
    c = list(line.coords)
    (ax, ay), (bx, by) = c[0], c[1]
    (cx, cy), (dx, dy) = c[-2], c[-1]
    h1, h2 = math.hypot(bx - ax, by - ay) or 1, math.hypot(dx - cx, dy - cy) or 1
    return shapely.LineString([(ax - (bx - ax) / h1 * d, ay - (by - ay) / h1 * d)] + c[1:-1] + [(dx + (dx - cx) / h2 * d, dy + (dy - cy) / h2 * d)])


def grid(poly, step):
    """The pieces of poly in a square grid of `step` metres."""
    import numpy as np
    import shapely
    if poly.is_empty:
        return []
    x0, y0, x1, y1 = poly.bounds
    # one grid for every mesh (its lines at whole multiples of step): with each mesh's own grid, the deck and the lanes on it were cut into
    # different triangles, and on a curved or sloped deck the deck poked through (light spikes at the junctions)
    x0, y0 = math.floor(x0 / step) * step, math.floor(y0 / step) * step
    xs, ys = np.meshgrid(np.arange(x0, x1, step), np.arange(y0, y1, step))
    cells = shapely.box(xs.ravel(), ys.ravel(), xs.ravel() + step, ys.ravel() + step)
    shapely.prepare(poly)
    cells = cells[shapely.intersects(poly, cells)]
    return [c for c in shapely.intersection(cells, poly) if not c.is_empty]


def surface(P, x0=0.0, y0=0.0, edges_of=None):
    """The deck of profile P, in metres east and north of (x0, y0): `axes` [(line, axis)], `deck` (OSM's outline and a strip along each
    measured landing), `fill` (the landings: past OSM's bridge way, the road on fill; None if no landing),
    `z(x, y)` the deck's top and `frame(line, s)`. A landing starts as wide as the outline where OSM's bridge way ends and narrows to its
    lanes on the ground, so the deck has no step there; `edges_of(axis id, end)`: the (left, right) edges of its lanes there as functions
    of s, where they move to the street's lane (model), else the bands' own."""
    import shapely

    rel = lambda ps: [(x - x0, y - y0) for x, y in ps]
    axes = [(shapely.LineString(rel(a["line"]["value"])), a) for a in P["axes"]]
    outline = shapely.make_valid(shapely.Polygon(rel(P["deck"]["outline"]["value"]), [rel(h) for h in P["deck"]["outline"].get("holes") or []]))

    def frame(ln, s):
        """The point on the axis at s and its unit normal to the left."""
        p, a, b = ln.interpolate(s), ln.interpolate(max(s - 1, 0)), ln.interpolate(min(s + 1, ln.length))
        dx, dy = b.x - a.x, b.y - a.y
        h = (dx * dx + dy * dy) ** .5 or 1
        return p.x, p.y, -dy / h, dx / h
    pieces, fill = [outline], []
    for ln, a in axes:
        for land in a.get("landings", []):
            L, d = ln.length, land["length_m"]
            end = land["end"] == "end"
            s0, s1 = (L - d, L) if end else (0.0, d)
            if d < 0.5:
                continue
            sec = a["sections"][-1] if end else a["sections"][0]
            lo = min((b["t"] - b["width"]["value"] / 2 for b in sec["bands"]), default=-4.0)
            hi = max((b["t"] + b["width"]["value"] / 2 for b in sec["bands"]), default=4.0)
            # the outline's extent across the axis where OSM's bridge way ends, else where the outline last crosses the axis before
            # it (OSM's outline can end a few metres before its bridge way: the landing then started as narrow as its lanes, a step)
            for back in range(2, 23, 2):     # (2 m inside it: its end edge can run aslant across the axis)
                sb = (s0 - back) if end else (s1 + back)
                if not 0.0 <= sb <= L:
                    break
                x, y, nx, ny = frame(ln, sb)
                cut = shapely.LineString([(x - nx * 30, y - ny * 30), (x + nx * 30, y + ny * 30)]).intersection(outline.buffer(0.05))
                ts = [(q[0] - x) * nx + (q[1] - y) * ny for g in shapely.get_parts(cut) if g.geom_type == "LineString"
                      and g.distance(shapely.Point(x, y)) < 0.5 for q in g.coords]
                if ts:
                    break
            lo0, hi0 = (min(ts), max(ts)) if ts else (lo, hi)
            n = max(2, int(d // STEP_M) + 1)
            ss = [s0 + (s1 - s0) * i / n for i in range(n + 1)]
            ss = ([max(sb - 2.0, 0.0)] + ss) if end else (ss + [min(sb + 2.0, L)])      # 2 m into the outline
            fe = edges_of(a["id"], end) if edges_of else None
            left, right = [], []
            for s in ss:
                u = min(1.0, max(0.0, (s - s0) / d if end else (s1 - s) / d))     # 0 where the bridge way ends, 1 on the ground
                x, y, nx, ny = frame(ln, s)
                eh, el = (fe[0](s), fe[1](s)) if fe else (hi, lo)
                tl, tr = hi0 + (eh - hi0) * u, lo0 + (el - lo0) * u
                left.append((x + nx * tl, y + ny * tl))
                right.append((x + nx * tr, y + ny * tr))
            pieces.append(shapely.Polygon(left + right[::-1]).buffer(0))
            k = slice(1, None) if end else slice(None, -1)          # (without the 2 m into the bridge)
            fill.append(shapely.Polygon(left[k] + right[k][::-1]).buffer(0))
    # the deck covers every lane: OSM's outline can be narrower than the lanes (a7 with its corrected 2 lanes: part of a lane hung off
    # the deck, with no guard)
    for ln, a in axes:
        for sec in a["sections"]:
            bs = [b for b in sec["bands"] if b["type"] == "lane"]
            if not bs or sec["s1"] - sec["s0"] < 0.5:
                continue
            lo = min(b["t"] - b["width"]["value"] / 2 for b in bs) - DECK_MARGIN_M
            hi = max(b["t"] + b["width"]["value"] / 2 for b in bs) + DECK_MARGIN_M
            n = max(2, int((sec["s1"] - sec["s0"]) // STEP_M) + 1)
            fr_ = [frame(ln, sec["s0"] + (sec["s1"] - sec["s0"]) * i / n) for i in range(n + 1)]
            pieces.append(shapely.Polygon([(x + nx * hi, y + ny * hi) for x, y, nx, ny in fr_] +
                                          [(x + nx * lo, y + ny * lo) for x, y, nx, ny in fr_][::-1]).buffer(0))
    # the gore between two roads that meet at a node in the air at under 90 degrees: deck, out to where their lanes are GORE_MAX_M apart,
    # so no slit ringed with a guard is left between them; at 90 degrees or more nothing is filled and each keeps its own edge
    # (Boulevard du Larvotto, a1 and a2 at J; Kaveh, 2026-10-14)
    at_node, gores = {}, []
    for ln, a in axes:
        for k, e in enumerate(a.get("ends", [])[:2]):
            if e.get("node") and not e.get("ground"):
                p0 = ln.coords[0] if k == 0 else ln.coords[-1]
                p1 = ln.interpolate(min(10.0, ln.length) if k == 0 else max(ln.length - 10.0, 0.0)).coords[0]
                sec = a["sections"][0] if k == 0 else a["sections"][-1]
                bs = [b for b in sec["bands"] if b["type"] == "lane"] or sec["bands"]
                w = (max((b["t"] + b["width"]["value"] / 2 for b in bs), default=3.0) - min((b["t"] - b["width"]["value"] / 2 for b in bs), default=-3.0))
                at_node.setdefault(e["node"], []).append((ln, p0, (p1[0] - p0[0], p1[1] - p0[1]), w))
    osm_outline = str(P["deck"]["outline"].get("source") or "").startswith("osm")     # (an OSM outline shapes its forks itself: Granville)
    for node, arms in (at_node.items() if not osm_outline else []):
        for i, (la, pa, da, wa) in enumerate(arms):
            for lb, pb, db, wb in arms[i + 1:]:
                ha, hb = math.hypot(*da) or 1, math.hypot(*db) or 1
                ang = math.degrees(math.acos(max(-1.0, min(1.0, (da[0] * db[0] + da[1] * db[1]) / (ha * hb)))))
                if ang >= 90.0 or ang < 1.0:
                    continue
                r = (GORE_MAX_M + (wa + wb) / 2) / (2 * math.sin(math.radians(ang) / 2))
                disk = shapely.Point(pa).buffer(r)
                sa = la.buffer(wa / 2 + DECK_MARGIN_M, cap_style="flat").intersection(disk)
                sb = lb.buffer(wb / 2 + DECK_MARGIN_M, cap_style="flat").intersection(disk)
                gore_ = shapely.union_all([sa, sb]).convex_hull.intersection(disk)
                pieces.append(gore_)
                gores.append(gore_)
    # notches under 1 m closed (where OSM's outline meets a landing, a short guard ran across the sidewalk: the end of a7)
    deck = shapely.make_valid(shapely.union_all(pieces).buffer(NOTCH_M, join_style="mitre").buffer(-NOTCH_M, join_style="mitre"))
    deck = max(shapely.get_parts(deck), key=lambda p: p.area) if deck.geom_type != "Polygon" else deck
    # no small hole: where OSM's outline meets a landing's strip, a slit left inside the lanes got a guard and walls around it
    deck = shapely.Polygon(deck.exterior, [r for r in deck.interiors if shapely.Polygon(r).area >= HOLE_MIN_M2])
    fill = shapely.union_all(fill).buffer(0.05) if fill else None
    if fill is not None:
        shapely.prepare(fill)

    def reach(a, s):
        """The extent across axis a at s that its lanes cover (right edge, left edge), a metre more each side."""
        sec = next((sc for sc in a["sections"] if sc["s0"] - 0.01 <= s <= sc["s1"] + 0.01), None)
        bs = sec["bands"] if sec else []
        return (min((b["t"] - b["width"]["value"] / 2 for b in bs), default=-3.0) - 1.0,
                max((b["t"] + b["width"]["value"] / 2 for b in bs), default=3.0) + 1.0)

    ground_end = {a["id"]: [bool(len(a.get("ends", [])) > k and a["ends"][k].get("ground")) for k in (0, 1)] for _, a in axes}
    # the nodes where axes meet (their ends): only there do two axes' heights blend (a fork); two axes that only lie side by side keep
    # each its own height (Boulevard du Larvotto: ramp a2 starts on the ground 7 m beside a1, 9 m up; blended, the deck between them
    # was stretched from 0 to 9 m; Kaveh, 2026-10-14)
    ends_of = {a["id"]: {(e.get("node") or f"{a['id']}.{k}"): shapely.Point(ln.coords[-k]) for k, e in enumerate(a.get("ends", [])[:2])}
               for ln, a in axes}
    sm = lambda u: (lambda c: c * c * (3 - 2 * c))(min(max(u, 0.0), 1.0))

    def z(x, y):
        """The deck's top at (x, y): the heights of the arms near it, each weighted by its nearness and by smooth fades: to nothing over
        OUT_FADE_M beyond its lanes and past its end, and over END_FADE_M to an end on the ground; then each weighted again by how near its
        height is to the mean (MEET_M: an arm passing above or below has little say). Every weight changes smoothly, so the deck has no
        step anywhere: hard switches (the nearest arm's height off the lanes, a cut-off between heights, a weight of nothing at an arm's
        end) made steps of up to 0.7 m across the deck at the forks, seen as steps in the guards (Kaveh, 2026-10-12)."""
        p = shapely.Point(x, y)
        ws, near = [], []
        def out_(la):           # how far p lies outside that axis's lanes (0 on them)
            r_ = reach(la[1], la[0].project(p))
            return max(0.0, la[0].distance(p) - max(-r_[0], r_[1]))
        ln0, a0 = min(axes, key=lambda la: (out_(la), la[0].distance(p)))     # (the axis whose deck this is: the nearest lanes)
        own, h_own = a0["id"], _h(a0["vertical"], ln0.project(p))
        fork = {n for n, q in ends_of[own].items() if q.distance(p) < BLEND_M}
        for ln, a in axes:
            if a["id"] != own and not (fork & set(ends_of[a["id"]])) and abs(_h(a["vertical"], ln.project(p)) - h_own) > 3 * MEET_M:
                continue            # (beside it at another height, not meeting it here: no say)
            d = ln.distance(p)
            sv = ln.project(p)
            hz = _h(a["vertical"], sv)
            near.append((d, hz))
            if d >= BLEND_M:
                continue
            q_, a_, b_ = ln.interpolate(sv), ln.interpolate(max(sv - 1, 0)), ln.interpolate(min(sv + 1, ln.length))
            h_ = math.hypot(b_.x - a_.x, b_.y - a_.y) or 1
            ux, uy = (b_.x - a_.x) / h_, (b_.y - a_.y) / h_
            t = ux * (y - q_.y) - uy * (x - q_.x)
            lo, hi = reach(a, sv)
            f_lane = sm((min(t - lo, hi - t) + OUT_FADE_M) / (OUT_FADE_M + FADE_M))
            along = ux * (x - q_.x) + uy * (y - q_.y)        # (past an end, how far along its way)
            past = max(0.0, -along) if sv < 0.01 else max(0.0, along) if sv > ln.length - 0.01 else 0.0
            f_end = sm(1.0 - past / OUT_FADE_M)
            ge = ground_end[a["id"]]
            if ge[0]:
                f_end *= sm(sv / END_FADE_M)
            if ge[1]:
                f_end *= sm((ln.length - sv) / END_FADE_M)
            w = f_lane * f_end / (d + 1.0)
            if w > 0:
                ws.append((w, hz))
        if not ws:
            return min(near)[1]
        m0 = sum(w * hz for w, hz in ws) / sum(w for w, _ in ws)
        use = [(w * math.exp(-((hz - m0) / MEET_M) ** 2), hz) for w, hz in ws]
        tot = sum(w for w, _ in use)
        return sum(w * hz for w, hz in use) / tot if tot > 1e-12 else m0

    return {"axes": axes, "deck": deck, "fill": fill, "z": z, "frame": frame, "gores": shapely.union_all(gores) if gores else shapely.Polygon()}


def model_checks(surf, deck, road_ends, S, axes):
    """The bridge model's own checks (`urbanstyle check --bridge`), on what the page draws, in the model's metres: [(id, what, count,
    hard, [(x, y) where]) ]. The faults Kaveh found by eye on Granville Bridge (2026-10-11), so a build finds them first."""
    import shapely
    poly = lambda sf: shapely.union_all([shapely.Polygon([sf["v"][i][:2] for i in t]).buffer(0) for t in sf["f"]
                                         if len({tuple(sf["v"][i][:2]) for i in t}) == 3])
    of = lambda pred: [(sf, poly(sf)) for sf in surf if pred(sf)]
    lanes_ = of(lambda sf: sf["key"].startswith("lane") and sf["props"] and sf["props"].get("type") == "lane")
    veh = shapely.union_all([g for sf, g in of(lambda sf: sf["key"].startswith("lane"))])
    # (only hairline gaps between lanes closed: closing 1 m gaps took a gore for lane, and its barrier's nose for a guard on a lane)
    inner = veh.buffer(0.05).buffer(-0.05 - GUARD_ON_LANE_M)
    guard = shapely.union_all([g for _, g in of(lambda sf: sf["key"] in ("barrier", "railing"))])
    bar = shapely.union_all([g for _, g in of(lambda sf: sf["key"] == "barrier")])
    paths = {}
    for sf, g in of(lambda sf: sf["key"] in ("sidewalk", "cycle lane") and sf["props"]):
        paths.setdefault(sf["props"].get("osm") or id(sf), []).append(g)
    paths = {k: shapely.union_all(v) for k, v in paths.items()}
    pk = list(paths)
    arrows = shapely.union_all([g for _, g in of(lambda sf: sf["key"] == "mark arrow")])
    ends = shapely.union_all(road_ends).buffer(1.0) if road_ends else shapely.Polygon()
    gaps = [g for g in shapely.get_parts(deck.exterior.difference(bar.buffer(0.4))) if g.length > 1.0 and g.difference(ends).length > 1.0]
    steps = []
    for ln, a in axes:              # the deck's width just before and just after each landing begins
        for land in a.get("landings", []):
            end = land["end"] == "end"
            s0 = ln.length - land["length_m"] if end else land["length_m"]
            w = []
            for ds in (-3.0, 1.0):
                x, y, nx, ny = S["frame"](ln, min(max(s0 + (ds if end else -ds), 0.0), ln.length))
                cut = shapely.LineString([(x - nx * 30, y - ny * 30), (x + nx * 30, y + ny * 30)]).intersection(deck)
                w.append(max((g.length for g in shapely.get_parts(cut) if g.distance(shapely.Point(x, y)) < 0.5), default=0.0))
            if abs(w[0] - w[1]) > 1.0:
                steps.append(S["frame"](ln, s0)[:2])
    pt = lambda g: g.representative_point().coords[0]
    on_lane = [p for p in shapely.get_parts(guard.intersection(inner)) if p.area > 0.05]
    pp = [(a, b) for i, a in enumerate(pk) for b in pk[i + 1:] if paths[a].intersection(paths[b]).area > 0.1]
    thin = [p for g in paths.values() for p in shapely.get_parts(g) if p.area >= 0.05 and p.buffer(-PATH_MIN_M / 2 + 0.01).is_empty]   # (mesh's own limit)
    ll = [g.intersection(h) for i, (sf, g) in enumerate(lanes_) for tf, h in lanes_[i + 1:]
          if sf["props"].get("axis") != tf["props"].get("axis") and g.intersection(h).area > 1.0]
    # (a lane is all its pieces, "<id> #2" ...: the deck the free-deck fill gives a lane is a piece of it with no arrow of its own)
    lane_g = {}
    for sf, g in lanes_:
        lane_g.setdefault(sf["props"]["id"].split(" #")[0], []).append(g)
    from .parts import ARROW_M

    def long_(g):           # (a lane piece too short for an arrow gets none, as the arrows' own rule says: 4 m pieces in Monaco)
        c = list(g.minimum_rotated_rectangle.exterior.coords) if not g.is_empty else []
        return len(c) > 2 and max(math.dist(c[0], c[1]), math.dist(c[1], c[2])) >= ARROW_M + 2.0
    bare = [u for u in (shapely.union_all(gs) for gs in lane_g.values() if not any(g.intersects(arrows) for g in gs)) if long_(u)]
    # the rules of 2026-10-12 (Kaveh: "the bridge can't have free space", "all boundary of the bridge must have barrier", "between driving
    # lane and other lanes must have barrier", the steps in the guards): no deck that no part covers; a barrier wherever a lane meets a path,
    # but at a crosswalk; no step in the deck's height
    cover = shapely.union_all([g.buffer(0.02) for _, g in of(lambda sf: not sf["key"].startswith("mark") and sf["key"] != "railing")])
    free = [g for g in shapely.get_parts(deck.difference(cover)) if g.area > FREE_CHECK_M2]
    xing = shapely.union_all([g.buffer(1.5) for _, g in of(lambda sf: sf["key"] in ("mark zebra", "crosswalk", "mark crosswalk"))])
    allpaths = shapely.union_all(list(paths.values())) if paths else shapely.Polygon()
    touch = veh.buffer(0.2, join_style="mitre").buffer(-0.2, join_style="mitre").boundary.intersection(allpaths.buffer(0.15))
    touch = touch.difference(bar.buffer(0.35)).difference(xing)
    nobar = [g for g in shapely.get_parts(shapely.line_merge(touch) if not touch.is_empty else touch)
             if g.geom_type == "LineString" and g.length > BAR_CHECK_M]
    hsteps = []
    for ln, a in axes:              # the deck's top every STEP_CHECK_M along each axis, at offsets across it, on the deck
        for t in (-12.0, -8.0, -4.0, 0.0, 4.0, 8.0, 12.0):
            prev = None
            for k in range(int(ln.length / STEP_CHECK_M) + 1):
                x, y, nx, ny = S["frame"](ln, k * STEP_CHECK_M)
                q = shapely.Point(x + nx * t, y + ny * t)
                if not deck.buffer(-0.3).contains(q):
                    prev = None
                    continue
                v = S["z"](q.x, q.y)
                if prev is not None and abs(v - prev) > HEIGHT_STEP_M:
                    hsteps.append((q.x, q.y))
                prev = v
    return [
        ("BR1", "guard pieces standing on a lane (more than 0.5 m inside)", len(on_lane), True, [pt(p) for p in on_lane]),
        ("BR2", "holes in the deck", len(deck.interiors), True, [pt(shapely.Polygon(r)) for r in deck.interiors]),
        ("BR3", "stretches of deck edge over 1 m with no guard, not at a road end on the ground", len(gaps), True, [pt(g) for g in gaps]),
        ("BR4", "pairs of paths drawn on top of each other (over 0.1 m2)", len(pp), True, [pt(paths[a].intersection(paths[b])) for a, b in pp]),
        ("BR5", f"path pieces narrower than {PATH_MIN_M} m", len(thin), True, [pt(p) for p in thin]),
        ("BR6", "pairs of lanes of two axes overlapping (over 1 m2)", len(ll), True, [pt(g) for g in ll]),
        ("BR7", "lanes with no arrow", len(bare), True, [pt(g) for g in bare]),
        ("BR8", "steps in the deck's width (over 1 m) where a landing begins", len(steps), True, steps),
        ("BR9", f"pieces of deck that no part covers (over {FREE_CHECK_M2} m2)", len(free), True, [pt(g) for g in free]),
        ("BR10", f"stretches over {BAR_CHECK_M} m where a lane meets a path with no barrier (not at a crosswalk)", len(nobar), True, [pt(g) for g in nobar]),
        ("BR11", f"steps in the deck's height (over {HEIGHT_STEP_M} m in {STEP_CHECK_M} m)", len(hsteps), True, hsteps),
    ]


def correct_sections(P):
    """P with the lane counts that corrections/lanes.json gives a landing's way (its own section: bridge_lidar) laid out: the extra lanes on
    the right of the travel, each widening from nothing over TAPER_M where the section with fewer lanes ends (ramp a2: 1 lane on the
    bridge, 2 on its landing), or from the fork where an axis starts on the bridge."""
    from .corrections import SOURCE, lanes as corrected, per_direction
    corr = corrected()
    for a in P["axes"]:
        secs = a["sections"]
        for si, sec in enumerate(secs):
            ls = [b for b in sec["bands"] if b["type"] == "lane"]
            ways = {b.get("way") for b in ls}
            if len(ways) != 1 or not ls or None in ways or any(b.get("method") == "corrected" for b in ls):
                continue
            w_id = int(next(iter(ways))[1:])
            if w_id not in corr:
                continue
            tags, note = corr[w_id]
            dirs = {b["direction"] for b in ls}
            for dr in dirs:
                grp = sorted([b for b in ls if b["direction"] == dr], key=lambda b: b["t"])
                f_, b_ = per_direction(tags, len(dirs) == 1)
                want = f_ if (len(dirs) == 1 or dr == "forward") else b_
                o = -1 if dr == "forward" else 1            # the travel's right, across the axis
                outer = grp[0] if o < 0 else grp[-1]
                count = lambda sc: sum(1 for x in sc["bands"] if x["type"] == "lane" and x["direction"] == dr)
                # (or the axis's first section where it leaves another road on the bridge, not the ground: a2 one lane at its fork
                # with a4, two very fast; Kaveh, 2026-10-12)
                at_start_prev = si > 0 and count(secs[si - 1]) < want
                at_start = at_start_prev or (si == 0 and not a["ends"][0].get("ground"))
                at_end = si + 1 < len(secs) and count(secs[si + 1]) < want
                for k in range(want - len(grp)):
                    w = outer["width"]["value"]
                    inner = outer["t"] + o * (w / 2 + k * w)
                    s_open = sec["s0"]
                    # (from the fork: it opens where it is clear of the other axes' lanes, open_tapers(), once the lines are drawn)
                    clear_ = si == 0 and not at_start_prev
                    nb = json.loads(json.dumps(outer))
                    nb.update(lane_id=f"{outer['lane_id']}+{k + 1}", lane=len(grp) + k + 1, t=round(inner + o * w / 2, 2),
                              source=f"{SOURCE}: {note}", method="corrected",
                              taper={"s0": s_open, "s1": min(s_open + TAPER_M, sec["s1"]), "inner": inner, "out": o, "clear": clear_} if at_start else
                              {"s0": sec["s1"], "s1": max(sec["s1"] - TAPER_M, sec["s0"]), "inner": inner, "out": o} if at_end else None)
                    sec["bands"].append(nb)
                # the lanes of a one-way road centred on its line, OSM's, as on the ground (street-rules.md, A1): the added lanes on the
                # right only put a2's two lanes 1.6 m off OSM's line and off the street's lanes at its landing (Kaveh, 2026-10-14, "a2 has
                # the wrong geometry", "does not match the lanes on the ground"). (Where an added lane opens at a fork, the fork moves
                # the lanes onto the trunk's first: lane_join)
                gr_ = [x for x in sec["bands"] if x["type"] == "lane" and x["direction"] == dr]
                if len(dirs) == 1 and len(gr_) > len(grp):
                    mid_ = (max(x["t"] + x["width"]["value"] / 2 for x in gr_) + min(x["t"] - x["width"]["value"] / 2 for x in gr_)) / 2
                    for x in gr_:
                        x["t"] = round(x["t"] - mid_, 2)
                        if x.get("taper"):
                            x["taper"]["inner"] -= mid_
            sec["bands"].sort(key=lambda b: -b["t"])
    return P


def fit_lanes(P):
    """P with its lanes narrowed where their chosen widths (GMNS: 3.25 m by road class) reach over a path that OSM maps beside them:
    on each side of the axis every lane edge moves in by one factor so the lanes end at the path's edge; the count stays. A path is
    beside a section where it runs along it (found across it at two of three stations); crossings and short links are not."""
    import shapely
    paths = [(shapely.LineString(f["line"]), f["width"]["value"], f["way"]) for f in P.get("paths", [])
             if len(f["line"]) > 1 and not (f.get("footway") == "crossing" or f.get("cycleway") == "crossing" or f.get("crossing"))]
    paths = [q for q in paths if q[0].length >= 20.0]
    for a in P["axes"]:
        if a["id"] in P.get("_rect_axes", ()):     # (a rectangle: its paths are placed beside its lanes, rectangles())
            continue
        ln = shapely.LineString(a["line"]["value"])
        for sec in a["sections"]:
            ls = [b for b in sec["bands"] if b["type"] == "lane"]
            if not ls:
                continue
            seen = {}           # (side, path index) -> [inner edge offset at each station where found]
            for k in (1, 2, 3):
                s = sec["s0"] + (sec["s1"] - sec["s0"]) * k / 4
                p, a_, b_ = ln.interpolate(s), ln.interpolate(max(s - 1, 0)), ln.interpolate(min(s + 1, ln.length))
                h = math.hypot(b_.x - a_.x, b_.y - a_.y) or 1
                nx, ny = -(b_.y - a_.y) / h, (b_.x - a_.x) / h
                cut = shapely.LineString([(p.x - nx * 25, p.y - ny * 25), (p.x + nx * 25, p.y + ny * 25)])
                for i, (g, w, _) in enumerate(paths):
                    for q in shapely.get_parts(cut.intersection(g)):
                        if q.geom_type == "Point":
                            t = (q.x - p.x) * nx + (q.y - p.y) * ny
                            seen.setdefault((1 if t > 0 else -1, i), []).append(abs(t) - w / 2)
            for side in (1, -1):
                reach = max(((b["t"] + side * b["width"]["value"] / 2) * side for b in ls), default=0.0)
                lim = [(min(v), paths[i][2]) for (sd, i), v in seen.items() if sd == side and len(v) >= 2 and min(v) < reach]
                if not lim or reach <= 0:
                    continue
                room, way = max(lim)            # the nearest path that still leaves room: its inner edge
                f = room / reach
                if f < FIT_MIN:
                    continue
                f = max(f, min(LANE_MIN_M / b["width"]["value"] for b in ls))
                for b in ls:
                    w0 = b["width"]["value"]
                    L, R = b["t"] + w0 / 2, b["t"] - w0 / 2
                    L, R = (L * f if L * side > 0 else L), (R * f if R * side > 0 else R)
                    if abs(L - R - w0) < 0.01:
                        continue
                    b["t"], b["width"] = round((L + R) / 2, 2), {
                        "value": round(L - R, 2), "source": "urbanstyle",
                        "method": f"derived: {b['width']['source']}'s {w0} m, narrowed to end at OSM's path {way} beside the lanes"}
    return P



def _continues(pa, a_ends, po, o_starts, max_deg=40.0):
    """Whether a line (points pa) that ends (a_ends) or starts at a node runs on into the line po that starts (o_starts) or ends there:
    the way out of the one and the way into the other within max_deg"""
    def way(pts, at_end):            # the direction at that end, 10 m along
        import shapely
        ln = shapely.LineString(pts)
        p, q = (ln.interpolate(max(ln.length - 10, 0)), ln.interpolate(ln.length)) if at_end else (ln.interpolate(0), ln.interpolate(min(10, ln.length)))
        return q.x - p.x, q.y - p.y
    u = way(pa, a_ends)
    u = u if a_ends else (-u[0], -u[1])         # (out of a through the node)
    v = way(po, not o_starts)
    v = v if o_starts else (-v[0], -v[1])       # (into o from the node)
    h = math.hypot(*u) * math.hypot(*v) or 1.0
    return (u[0] * v[0] + u[1] * v[1]) / h > math.cos(math.radians(max_deg))


def fillets(P):
    """P with each axis that corrections/bridges.json names under "smooth" (Kaveh, 2026-10-12: "you had to line straight for a5 and a1,
    create something smooth to connect them, two lines") drawn as one road line and one curve: where it leaves a straight road (a1)
    at a node, it starts on the lanes SUMO connects it to, in that road's direction; one cubic curve, tangent to both, takes it to its
    own line: the longest straight part of OSM's line (points within FILLET_STRAIGHT_M of a line, a5), or, under "smooth_follow"
    {axis: path way}, OSM's line of that path moved across onto the axis (a6 by its footway w871038559: "the geometry for footway in
    osm is smooth, you can use it"); then OSM's line on. Its s (sections, bands, heights, ends) moves to the nearest point of the new
    line. P["_fitted"]: {axis id: the end at the node (0: start, 1: end)}, whose lanes model() no longer moves at that node."""
    import shapely
    from shapely.ops import substring
    from .corrections import bridge as bridge_corr
    corr = bridge_corr(P["name"])
    # paths left out or cut short at their start, as corrections/bridges.json says ("drop_paths", "trim_paths": {way: metres}):
    # cycleway w1417439069 and the tip of shared path w1417439065 in the gap between a4 and a9 (Kaveh, 2026-10-12)
    P["paths"] = [f for f in P.get("paths", []) if f["way"] not in corr.get("drop_paths", [])]
    for f in P["paths"]:
        cut_ = corr.get("trim_paths", {}).get(f["way"])
        if cut_:
            l_ = shapely.LineString(f["line"])
            f["line"] = [list(c_) for c_ in substring(l_, min(cut_, l_.length - 0.5), l_.length).coords]
    names, follow, beside = corr.get("smooth", []), corr.get("smooth_follow", {}), corr.get("smooth_beside", {})
    P["_fitted"] = {}
    conn = {(c["from"], c["to"]) for c in P.get("connectors", [])}
    # (an axis beside another, a4 beside a9, after that one: it runs along its new line)
    for a in sorted(P["axes"], key=lambda a_: (a_["id"] in beside, beside.get(a_["id"]) != "straight")):
        if a["id"] not in names and a["id"] not in follow and a["id"] not in beside:
            continue
        pts0 = [list(p[:2]) for p in a["line"]["value"]]
        # the trunk: a straight road that meets it at the node (its end, a1 for a5 and a6, or its start, a1 for a4) and that it runs on from
        T, at_end, t_rev = None, 0, False
        for o in P["axes"]:
            po = [list(p_[:2]) for p_ in o["line"]["value"]]
            if o is a or o["id"] not in corr.get("rectangle", []):     # (a trunk already drawn as strips: a1 for a4, not a7 at its far end)
                continue
            for node_i, br in ((0, pts0), (1, pts0[::-1])):
                for t_r, tline in ((False, po), (True, po[::-1])):
                    if T is None and math.dist(tline[-1], br[0]) < 1.0 and _continues(tline, True, br, True, FILLET_TURN_DEG):
                        # (the first one found: a1 for a4, not a7 at a4's far end, Kaveh, 2026-10-12 "fix a7")
                        T, at_end, t_rev = o, node_i, t_r
        if T is None:
            continue
        pts = pts0[::-1] if at_end else pts0           # (from the node out)
        old = shapely.LineString(pts0)
        pT = [list(p_[:2]) for p_ in T["line"]["value"]]
        pT = pT[::-1] if t_rev else pT                  # (the trunk towards the node)
        (xa, ya), (xb, yb) = pT[-2][:2], pT[-1][:2]
        # (a trunk that rectangles() draws straight from end to end, a1: its chord's way, not OSM's last segment; a5 and a6 left a1's
        # node at an angle to its drawn lanes, a kink in their edges; Kaveh, 2026-10-12)
        ch_t = shapely.LineString([pT[0], pT[-1]])
        if T["id"] not in P["_fitted"] and max(ch_t.distance(shapely.Point(c_)) for c_ in pT) <= RECT_STRAIGHT_M:
            (xa, ya), (xb, yb) = pT[0][:2], pT[-1][:2]
        h = math.hypot(xb - xa, yb - ya)
        ux, uy = (xb - xa) / h, (yb - ya) / h               # (the trunk's way into the node, the branch's way out of it)
        nx, ny = -uy, ux
        sec = a["sections"][-1] if at_end else a["sections"][0]
        bands_a = [b for b in sec["bands"] if b["type"] == "lane"]
        bands_t = [b for b in (T["sections"][0] if t_rev else T["sections"][-1])["bands"] if b["type"] == "lane"]
        sgn = -1.0 if at_end else 1.0                       # (a band's t from the node out: the other way along a6)
        sgt = -1.0 if t_rev else 1.0                        # (the trunk's band t towards the node: the other way along a1 for a4)
        # (by the links of corrections/bridges.json where they name its lanes: a3's _2 on a9's _3, Kaveh, 2026-10-12; else SUMO's)
        user_l = {tuple(x_) for x_ in corr.get("lane_links", [])}
        lk = user_l if any(ba.get("lane_id") in {l_ for pr_ in user_l for l_ in pr_} for ba in bands_a) else conn
        on = [sgt * bt["t"] - sgn * ba["t"] for ba in bands_a for bt in bands_t
              if (bt.get("lane_id"), ba.get("lane_id")) in lk or (ba.get("lane_id"), bt.get("lane_id")) in lk]
        if not on:
            continue
        c = sum(on) / len(on)
        S0 = (pts[0][0] + nx * c, pts[0][1] + ny * c)         # (its axis at the node: its lanes on the trunk's lanes they continue)
        ln = shapely.LineString(pts)

        def follow_line():
            """OSM's line of the path it follows, where it runs along it, moved across onto it (from the node out), and the offset;
            None if there is none"""
            f = next((f_ for f_ in P.get("paths", []) if f_["way"] == follow[a["id"]]), None)
            if f is None:
                return None
            q = list(shapely.LineString(f["line"]).segmentize(1.0).coords)
            others_ = [shapely.LineString(o["line"]["value"]) for o in P["axes"] if o is not a]
            near = [i for i, c_ in enumerate(q) if ln.distance(shapely.Point(c_)) < 25 and
                    ln.distance(shapely.Point(c_)) < min(o_.distance(shapely.Point(c_)) for o_ in others_)]
            if len(near) < 20:
                return None
            seg = [q[i][:2] for i in range(near[0], near[-1] + 1)]
            if ln.project(shapely.Point(seg[0])) > ln.project(shapely.Point(seg[-1])):
                seg = seg[::-1]
            far = [p_ for p_ in seg if ln.project(shapely.Point(p_)) > FOLLOW_FROM_M]
            sides = []
            for p_ in far:
                s_ = ln.project(shapely.Point(p_))
                p0, p1 = ln.interpolate(max(s_ - 1, 0)), ln.interpolate(min(s_ + 1, ln.length))
                hh = math.hypot(p1.x - p0.x, p1.y - p0.y) or 1
                sides.append(((p_[0] - p0.x) * -(p1.y - p0.y) + (p_[1] - p0.y) * (p1.x - p0.x)) / hh)
            if not sides:
                return None
            sides.sort()
            off = sides[len(sides) // 2]
            moved = shapely.LineString(seg).offset_curve(-off, quad_segs=16, join_style="round")
            if moved.geom_type != "LineString":
                return None
            mv_ = [list(c_) for c_ in moved.coords]
            if math.dist(mv_[0], pts[0]) > math.dist(mv_[-1], pts[0]):
                mv_ = mv_[::-1]
            return shapely.LineString(mv_), off

        if a["id"] in beside:
            # one road with the axis beside it up to that one's far end, the first branch (a4 on a1's west lanes beside a9, till a10
            # branches: Kaveh, 2026-10-12, "update the bridge from a1 till the first other branch"); there one curve to its own line
            if beside[a["id"]] == "straight":       # (the trunk's line on, straight: a9 is a1 running on)
                B = {"id": T["id"] + " straight on"}
                pb = [list(pts[0]), [pts[0][0] + ux * ln.length, pts[0][1] + uy * ln.length]]
            else:
                B = next(o for o in P["axes"] if o["id"] == beside[a["id"]])
                pb = [list(p_[:2]) for p_ in B["line"]["value"]]
            pb = pb if math.dist(pb[0], pts[0]) < math.dist(pb[-1], pts[0]) else pb[::-1]       # (from the node out)
            lb = shapely.LineString(pb)
            c_off = math.dist(S0, pb[0])
            moved = [lb.offset_curve(d_) if c_off > 0.01 else lb for d_ in (c_off, -c_off)]
            moved = [m_ for m_ in moved if m_.geom_type == "LineString"]
            mv = min(moved, key=lambda m_: min(math.dist(m_.coords[0], S0), math.dist(m_.coords[-1], S0)))
            mv = [list(c_) for c_ in mv.coords]
            mv = mv if math.dist(mv[0], S0) < math.dist(mv[-1], S0) else mv[::-1]
            # beside it while OSM's own line stays there (within BESIDE_TOL_M of that place): a4 for 110 m of a9; then it leaves
            mlf = shapely.LineString(mv)
            s_lv = 0.0
            for s_ in range(0, int(mlf.length) + 1):
                if ln.distance(mlf.interpolate(s_)) <= BESIDE_TOL_M:
                    s_lv = float(s_)
                elif s_ > 20:
                    break
            # (a cap on the straight part: a9's footway w538616396 #4 made an S after a long one, Kaveh, 2026-10-12)
            s_lv = min(s_lv, corr.get("smooth_beside_max", {}).get(a["id"], s_lv))
            mv = [list(c_) for c_ in substring(mlf, 0.0, max(s_lv, 1.0)).coords]
            # a new lane from its lane to the lane of the one beside that takes its place further on (4747140365369135178_1 of a4 to
            # 4865609269725927722_2 of a9: Kaveh, 2026-10-12, "we need a new lane"): that lane carried back to where it leaves
            if "sections" in B:
                lbo = shapely.LineString([p_[:2] for p_ in B["line"]["value"]])
                s_bl = lbo.project(shapely.Point(mv[-1]))
                for si_, sc in enumerate(B["sections"]):
                    near_end = sc["s1"] if abs(sc["s1"] - s_bl) < abs(sc["s0"] - s_bl) else sc["s0"]
                    if not min(sc["s0"], sc["s1"]) - 0.5 <= near_end <= max(sc["s0"], sc["s1"]) + 0.5 or abs(near_end - s_bl) < 1.0:
                        continue
                    p0_, p1_ = lbo.interpolate(max(near_end - 0.5, 0)), lbo.interpolate(min(near_end + 0.5, lbo.length))
                    hh_ = math.hypot(p1_.x - p0_.x, p1_.y - p0_.y) or 1
                    nbx, nby = -(p1_.y - p0_.y) / hh_, (p1_.x - p0_.x) / hh_
                    pe_ = lbo.interpolate(near_end)
                    full_ = substring(shapely.LineString(mv), 0.0, shapely.LineString(mv).length)
                    for bb in [b_ for b_ in sc["bands"] if b_["type"] == "lane"]:
                        cb = shapely.Point(pe_.x + nbx * bb["t"], pe_.y + nby * bb["t"])
                        for ba in bands_a:
                            la_ = mlf.offset_curve(sgn * ba["t"])
                            if la_.geom_type != "LineString" or la_.distance(cb) > 0.5:
                                continue
                            # the stretch between: the neighbouring section of B there, split; the new lane in its part
                            # (from the trunk's node itself where corrections/bridges.json says so: a1's 641676206441300162_2 runs on
                            # into it, Kaveh, 2026-10-12)
                            if a["id"] in corr.get("new_lane_from_node", []):
                                s_bl = lbo.project(shapely.Point(pts[0]))
                            lo_, hi_ = sorted((near_end, s_bl))
                            for sj, sc2 in enumerate(B["sections"]):
                                if sc2 is not sc and sc2["s0"] - 0.5 <= lo_ and hi_ <= sc2["s1"] + 0.5:
                                    new_b = dict(bb, lane_id=f"{ba['lane_id']}>{bb['lane_id']}", lane=None, link=None,
                                                 source="urbanstyle", method=f"derived: joins {a['id']}'s {ba['lane_id']} to {B['id']}'s "
                                                 f"{bb['lane_id']} (Kaveh, 2026-10-12)", s_from=lo_, s_to=hi_)
                                    mid_ = dict(sc2, s0=lo_, s1=hi_, bands=sc2["bands"] + [new_b], links=sc2.get("links", []))
                                    parts_ = ([dict(sc2, s1=lo_)] if lo_ - sc2["s0"] > 0.5 else []) + [mid_] + \
                                             ([dict(sc2, s0=hi_)] if sc2["s1"] - hi_ > 0.5 else [])
                                    B["sections"][sj:sj + 1] = sorted(parts_, key=lambda x_: x_["s0"])
                                    break
                            break
                        else:
                            continue
                        break
            mln = shapely.LineString(mv)
            # its own line from FOLLOW_FROM_M past where it leaves, OSM's points on; or, when it also follows a path (a4: straight with a1
            # up to the branch, then OSM's footway w871038559: Kaveh, 2026-10-12, "before branching ... straight as a1"), that path's line
            tgt = ln
            if a["id"] in follow:
                fl_ = follow_line()
                if fl_ is not None:
                    tgt = fl_[0]
                    a["_follow"] = (follow[a["id"]], abs(fl_[1]))
            s_br = tgt.project(shapely.Point(mv[-1]))
            s_q0 = min(s_br + FOLLOW_FROM_M, tgt.length)
            if a["id"] in corr.get("smooth_to_end", []):
                s_q0 = tgt.length       # (one curve all the way to its far end: a9's S near the a10 node, Kaveh, 2026-10-12)
            Q_ = tgt.interpolate(s_q0)
            q1_, q2_ = tgt.interpolate(s_q0 - 1.0), Q_        # (its way there, from the metre before: at the line's end the way after is none)
            head = [list(c_) for c_ in mv]
            Hx, Hy = head[-1]
            h1 = mln.interpolate(mln.length - 1.0)
            hx_, hy_ = Hx - h1.x, Hy - h1.y
            if tgt is not ln:
                # (following a path's line: one long curve from the node, in the trunk's way, to that line past the branch; a straight
                # part beside first and a curve after it made an S: Kaveh, 2026-10-12, "fix this part")
                head = [list(S0)]
                Hx, Hy = S0
                hx_, hy_ = ux, uy
            hh_ = math.hypot(hx_, hy_) or 1
            vx, vy = q2_.x - q1_.x, q2_.y - q1_.y
            hv = math.hypot(vx, vy) or 1
            vx, vy = vx / hv, vy / hv
            k2 = math.dist((Hx, Hy), (Q_.x, Q_.y)) * 0.4
            d1, d2 = (Hx + hx_ / hh_ * k2, Hy + hy_ / hh_ * k2), (Q_.x - vx * k2, Q_.y - vy * k2)
            n2 = max(8, int(math.dist((Hx, Hy), (Q_.x, Q_.y))))
            bz2 = lambda t: [(1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3
                             for p0, p1, p2, p3 in zip((Hx, Hy), d1, d2, (Q_.x, Q_.y))]
            s_q = tgt.project(Q_)
            rest_ = [list(c_) for c_ in tgt.coords if tgt.project(shapely.Point(c_)) > s_q + 0.5]
            if tgt is not ln:       # (past the path's end, OSM's own line on)
                s_end = ln.project(shapely.Point(rest_[-1] if rest_ else [Q_.x, Q_.y]))
                rest_ += [p_ for p_ in pts if ln.project(shapely.Point(p_)) > s_end + 2.0]
            new = [list(S0)] + head[1:] + [bz2(m / n2) for m in range(1, n2)] + [[Q_.x, Q_.y]] + rest_
            if at_end:
                new = new[::-1]
            method = f"from {T['id']}'s lanes at the node beside {B['id']} while OSM's line is there ({s_lv:.0f} m), then one curve to OSM's line"
        elif a["id"] in follow:
            # OSM's line of the path beside it, where it runs along it (nearer it than any other axis), moved across onto it
            f = next((f_ for f_ in P.get("paths", []) if f_["way"] == follow[a["id"]]), None)
            if f is None:
                continue
            q = list(shapely.LineString(f["line"]).segmentize(1.0).coords)
            others_ = [shapely.LineString(o["line"]["value"]) for o in P["axes"] if o is not a]
            near = [i for i, c_ in enumerate(q) if ln.distance(shapely.Point(c_)) < 25 and
                    ln.distance(shapely.Point(c_)) < min(o_.distance(shapely.Point(c_)) for o_ in others_)]
            if len(near) < 20:
                continue
            seg = [q[i][:2] for i in range(near[0], near[-1] + 1)]
            if ln.project(shapely.Point(seg[0])) > ln.project(shapely.Point(seg[-1])):
                seg = seg[::-1]                             # (from the node out)
            fl = shapely.LineString(seg)
            # its side and its distance: where it runs steady, past FOLLOW_FROM_M from the node (at the fork it bends off)
            far = [p_ for p_ in seg if ln.project(shapely.Point(p_)) > FOLLOW_FROM_M]
            sides = []
            for p_ in far:
                s_ = ln.project(shapely.Point(p_))
                p0, p1 = ln.interpolate(max(s_ - 1, 0)), ln.interpolate(min(s_ + 1, ln.length))
                hh = math.hypot(p1.x - p0.x, p1.y - p0.y) or 1
                sides.append(((p_[0] - p0.x) * -(p1.y - p0.y) + (p_[1] - p0.y) * (p1.x - p0.x)) / hh)
            sides.sort()
            off = sides[len(sides) // 2]                    # (left of the axis +)
            # (second pass: so that its strip of that path lies on OSM's line, not OSM's own distance: model())
            off += math.copysign(P.get("_follow_shift", {}).get(a["id"], 0.0), off)
            a["_follow"] = (follow[a["id"]], abs(off))
            moved = fl.offset_curve(-off, quad_segs=16, join_style="round")
            if moved.geom_type != "LineString":
                continue
            mv = [list(c_) for c_ in moved.coords]
            if math.dist(mv[0], pts[0]) > math.dist(mv[-1], pts[0]):
                mv = mv[::-1]
            mln = shapely.LineString(mv)
            sQ = mln.project(mln.interpolate(0)) + 0.0
            # the curve meets it FOLLOW_FROM_M out; past its end, OSM's own line on
            sq = min(FOLLOW_FROM_M, mln.length / 3)
            Q = list(mln.interpolate(sq).coords[0])
            q2 = mln.interpolate(sq + 1.0)
            vx, vy = q2.x - Q[0], q2.y - Q[1]
            hv = math.hypot(vx, vy) or 1
            vx, vy = vx / hv, vy / hv
            body = [Q] + [c_ for c_ in mv if mln.project(shapely.Point(c_)) > sq + 0.5]
            s_end = ln.project(shapely.Point(mv[-1]))
            tail = [p_ for p_ in pts if ln.project(shapely.Point(p_)) > s_end + 2.0]
            method = f"from {T['id']}'s lanes at the node one curve to OSM's line of {follow[a['id']]} moved {abs(off):.1f} m across onto it"
        else:
            S = [ln.project(shapely.Point(p_)) for p_ in pts]
            best = None             # its longest straight part: OSM's points from i to j within FILLET_STRAIGHT_M of the line i-j
            for i in range(1, len(pts)):
                for j in range(i + 2, len(pts)):
                    ch = shapely.LineString([pts[i], pts[j]])
                    if max(ch.distance(shapely.Point(pts[k])) for k in range(i, j + 1)) <= FILLET_STRAIGHT_M and (best is None or S[j] - S[i] > best[2]):
                        best = (i, j, S[j] - S[i])
            if best is None:
                continue
            i, j, _ = best
            Q, R = pts[i], pts[j]
            hq = math.dist(Q, R)
            vx, vy = (R[0] - Q[0]) / hq, (R[1] - Q[1]) / hq
            body, tail = [Q, R], pts[j + 1:]
            method = f"from {T['id']}'s lanes at the node one curve to its straight part (s {S[i]:.0f}-{S[j]:.0f} m), straight there"
            # (under "straight_from_node": no curve, one straight line from the node to where its straight part is as far to the side
            # as its start on the trunk's lanes: a4, 0.9 m off a1's lanes, Kaveh, 2026-10-12, "why there is curve here instead of straight")
            lat = lambda p_: (p_[0] - pts[0][0]) * nx + (p_[1] - pts[0][1]) * ny
            if a["id"] in corr.get("straight_from_node", []) and abs(lat(R) - lat(Q)) > 1e-6 and 0.0 <= (c - lat(Q)) / (lat(R) - lat(Q)) <= 1.0:
                tj = (c - lat(Q)) / (lat(R) - lat(Q))
                J = [Q[0] + tj * (R[0] - Q[0]), Q[1] + tj * (R[1] - Q[1])]
                new = [list(S0), J, R] + tail
                if at_end:
                    new = new[::-1]
                method = f"from {T['id']}'s lanes at the node straight to its straight part ({math.dist(S0, J):.0f} m), straight there"
        if a["id"] not in beside and not method.startswith(f"from {T['id']}'s lanes at the node straight"):
            k = math.dist(S0, Q) * 0.4
            c1, c2 = (S0[0] + ux * k, S0[1] + uy * k), (Q[0] - vx * k, Q[1] - vy * k)
            n = max(8, int(math.dist(S0, Q)))
            bz = lambda t: [(1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3 for p0, p1, p2, p3 in zip(S0, c1, c2, Q)]
            new = [bz(m / n) for m in range(n)] + body + tail
            if at_end:
                new = new[::-1]
        nln = shapely.LineString(new)
        remap = lambda s_: round(nln.project(old.interpolate(s_)), 2)      # (each old place to the nearest of the new line)
        for sc in a["sections"]:
            sc["s0"], sc["s1"] = remap(sc["s0"]), remap(sc["s1"])
            for b in sc["bands"]:
                for key in ("s_from", "s_to"):
                    if b.get(key) is not None:
                        b[key] = remap(b[key])
                if b.get("taper"):          # (a lane that opens over a taper: its metres move too)
                    b["taper"] = dict(b["taper"], s0=remap(b["taper"]["s0"]), s1=remap(b["taper"]["s1"]))
        if at_end:          # (the ends of the line exactly)
            a["sections"][-1]["s1"] = round(nln.length, 2)
        else:
            a["sections"][0]["s0"] = 0.0
        v = a.get("vertical")
        if isinstance(v, dict):
            for key in ("points", "samples", "chosen_before"):
                if isinstance(v.get(key), list):
                    v[key] = [[remap(q_[0])] + list(q_[1:]) for q_ in v[key]]
            if isinstance(v.get("stations"), list):
                for st_ in v["stations"]:
                    st_["s"] = remap(st_["s"])
        for e in a.get("ends", []):
            e["s"] = remap(e["s"])
        a["line"] = {"value": [[round(x, 2), round(y, 2)] for x, y in new], "source": a["line"]["source"] + "; urbanstyle corrections (corrections/bridges.json)",
                     "method": "mapped, then " + method}
        a["length_m"] = round(nln.length, 2)
        a["_node"], a["_node_at"] = list(pts[0][:2]), at_end
        P["_fitted"][a["id"]] = at_end
    # OSM's corners rounded (before the pairs: a pair leaves its trunk in the way the trunk is drawn, a10) (Chaikin, ROUND_PASSES times; the ends stay): a3 as one smooth line near OSM's (Kaveh, 2026-10-12: "a nice
    # strips version for a3, close to the geometry from OSM")
    for a in P["axes"]:
        if a["id"] not in corr.get("round", []):
            continue
        pts_ = [list(p_[:2]) for p_ in a["line"]["value"]]
        old = shapely.LineString(pts_)
        pts_ = [list(c_) for c_ in old.segmentize(ROUND_STEP_M).coords]      # (short pieces first: each corner cut only near it)
        for _ in range(ROUND_PASSES):
            q_ = [pts_[0]]
            for p0_, p1_ in zip(pts_, pts_[1:]):
                q_ += [[0.75 * p0_[0] + 0.25 * p1_[0], 0.75 * p0_[1] + 0.25 * p1_[1]], [0.25 * p0_[0] + 0.75 * p1_[0], 0.25 * p0_[1] + 0.75 * p1_[1]]]
            pts_ = q_ + [pts_[-1]]
        nln = shapely.LineString(pts_)
        remap = lambda s_: round(nln.project(old.interpolate(s_)), 2)
        for sc in a["sections"]:
            sc["s0"], sc["s1"] = remap(sc["s0"]), remap(sc["s1"])
            for b in sc["bands"]:
                for key in ("s_from", "s_to"):
                    if b.get(key) is not None:
                        b[key] = remap(b[key])
                if b.get("taper"):          # (a lane that opens over a taper: its metres move too)
                    b["taper"] = dict(b["taper"], s0=remap(b["taper"]["s0"]), s1=remap(b["taper"]["s1"]))
        a["sections"][0]["s0"], a["sections"][-1]["s1"] = 0.0, round(nln.length, 2)
        v = a.get("vertical")
        if isinstance(v, dict):
            for key in ("points", "samples", "chosen_before"):
                if isinstance(v.get(key), list):
                    v[key] = [[remap(q2[0])] + list(q2[1:]) for q2 in v[key]]
            if isinstance(v.get("stations"), list):
                for st_ in v["stations"]:
                    st_["s"] = remap(st_["s"])
        for e in a.get("ends", []):
            e["s"] = remap(e["s"])
        a["line"] = dict(a["line"], value=[[round(x, 2), round(y, 2)] for x, y in pts_], method=a["line"]["method"] + "; corners rounded")
        a["length_m"] = round(nln.length, 2)
    # an axis that runs straight on into another at a node ("tangent_ends": [[axis, trunk]]): its last TANGENT_M turn into the trunk's way,
    # the rest keeps OSM's line; their lane ends met at an angle, a wedge between a10's and a9's (Kaveh, 2026-10-12)
    axd_t = {a["id"]: a for a in P["axes"]}
    for ida, idt in corr.get("tangent_ends", []):
        A_, T_ = axd_t.get(ida), axd_t.get(idt)
        if not (A_ and T_):
            continue
        la = [list(p_[:2]) for p_ in A_["line"]["value"]]
        lt = [list(p_[:2]) for p_ in T_["line"]["value"]]
        ea, et = min(((i, j) for i in (0, 1) for j in (0, 1)), key=lambda e: math.dist(la[-1 if e[0] else 0], lt[-1 if e[1] else 0]))
        node = lt[-1 if et else 0]
        if math.dist(la[-1 if ea else 0], node) > 1.0:
            continue
        lT = shapely.LineString(lt if not et else lt[::-1])          # (the trunk, out of the node)
        q1 = lT.interpolate(1.0)
        hq = math.dist(node, q1.coords[0]) or 1.0
        ux, uy = -(q1.x - node[0]) / hq, -(q1.y - node[1]) / hq      # (the way back along the axis, straight on from the trunk)
        old = shapely.LineString(la)
        pts_ = [list(c_) for c_ in old.segmentize(1.0).coords]
        pts_ = pts_[::-1] if ea else pts_                              # (from the node out)
        lo_ = shapely.LineString(pts_)
        new_ = []
        for c_ in pts_:
            d_ = lo_.project(shapely.Point(c_))
            w_ = (lambda u: u * u * (3 - 2 * u))(min(d_ / TANGENT_M, 1.0))
            new_.append([c_[0] * w_ + (node[0] + ux * d_) * (1 - w_), c_[1] * w_ + (node[1] + uy * d_) * (1 - w_)])
        new_ = new_[::-1] if ea else new_
        nln = shapely.LineString(new_)
        remap = lambda s_, old=old, nln=nln: round(nln.project(old.interpolate(s_)), 2)
        for sc in A_["sections"]:
            sc["s0"], sc["s1"] = remap(sc["s0"]), remap(sc["s1"])
            for b in sc["bands"]:
                for key in ("s_from", "s_to"):
                    if b.get(key) is not None:
                        b[key] = remap(b[key])
                if b.get("taper"):
                    b["taper"] = dict(b["taper"], s0=remap(b["taper"]["s0"]), s1=remap(b["taper"]["s1"]))
        A_["sections"][0]["s0"], A_["sections"][-1]["s1"] = 0.0, round(nln.length, 2)
        v = A_.get("vertical")
        if isinstance(v, dict):
            for key in ("points", "samples", "chosen_before"):
                if isinstance(v.get(key), list):
                    v[key] = [[remap(q2[0])] + list(q2[1:]) for q2 in v[key]]
            if isinstance(v.get("stations"), list):
                for st_ in v["stations"]:
                    st_["s"] = remap(st_["s"])
        for e in A_.get("ends", []):
            e["s"] = remap(e["s"])
        A_["line"] = dict(A_["line"], value=[[round(x, 2), round(y, 2)] for x, y in new_],
                          method=A_["line"]["method"] + f"; its last {TANGENT_M:.0f} m turned into {idt}'s way at their node")
        A_["length_m"] = round(nln.length, 2)
        P["_fitted"][A_["id"]] = ea
    # two roads of one divided road built on one line ("pair": [[a, b, trunk]]): their centre line, from the node with the trunk (a10)
    # the middle of their OSM lines, corners rounded; each road beside it, its lanes at the node on the trunk's lanes they continue
    # (a11 and a12: Kaveh, 2026-10-12, "strips based on one geometry")
    axd = {a["id"]: a for a in P["axes"]}
    for ida, idb, idt in corr.get("pair", []):
        A_, B_, T_ = axd.get(ida), axd.get(idb), axd.get(idt)
        if not (A_ and B_ and T_):
            continue
        pT = [list(p_[:2]) for p_ in T_["line"]["value"]]
        la = [list(p_[:2]) for p_ in A_["line"]["value"]]
        lb = [list(p_[:2]) for p_ in B_["line"]["value"]]
        node = min((pT[0], pT[-1]), key=lambda q_: min(math.dist(q_, la[0]), math.dist(q_, la[-1])))
        la = la if math.dist(la[0], node) < math.dist(la[-1], node) else la[::-1]
        lb = lb if math.dist(lb[0], node) < math.dist(lb[-1], node) else lb[::-1]
        La, Lb = shapely.LineString(la), shapely.LineString(lb)
        m_ = max(10, int(min(La.length, Lb.length) / 2))
        C = [[(La.interpolate(k / m_, normalized=True).x + Lb.interpolate(k / m_, normalized=True).x) / 2,
              (La.interpolate(k / m_, normalized=True).y + Lb.interpolate(k / m_, normalized=True).y) / 2] for k in range(m_ + 1)]
        for _ in range(ROUND_PASSES):
            q_ = [C[0]]
            for p0_, p1_ in zip(C, C[1:]):
                q_ += [[0.75 * p0_[0] + 0.25 * p1_[0], 0.75 * p0_[1] + 0.25 * p1_[1]], [0.25 * p0_[0] + 0.75 * p1_[0], 0.25 * p0_[1] + 0.75 * p1_[1]]]
            C = q_ + [C[-1]]
        # (out of the node in the trunk's way, onto the middle line over PAIR_TANGENT_M: a12's lane ends crossed a10's at an angle, a
        # wedge of overlap on one side and a gap on the other; Kaveh, 2026-10-12, "a12 has many glitches ... not fit and smooth")
        tT_ = shapely.LineString(pT if math.dist(pT[-1], node) < math.dist(pT[0], node) else pT[::-1])
        # (a strip axis within RECT_STRAIGHT_M of straight is drawn straight from end to end, rectangles(): its way is its chord's, a10)
        ch_ = shapely.LineString([tT_.coords[0], tT_.coords[-1]])
        if idt in corr.get("rectangle", []) and max(ch_.distance(shapely.Point(c_)) for c_ in tT_.coords) <= RECT_STRAIGHT_M:
            tT_ = ch_
        u0_, u1_ = tT_.interpolate(tT_.length - 1.0), tT_.interpolate(tT_.length)
        hu_ = math.dist(u0_.coords[0], u1_.coords[0]) or 1.0
        ux_, uy_ = (u1_.x - u0_.x) / hu_, (u1_.y - u0_.y) / hu_
        Cl0 = shapely.LineString(C)
        C2 = []
        for c_ in C:
            s_c = Cl0.project(shapely.Point(c_))
            w_ = (lambda u: u * u * (3 - 2 * u))(min(s_c / PAIR_TANGENT_M, 1.0))
            C2.append([c_[0] * w_ + (node[0] + ux_ * s_c) * (1 - w_), c_[1] * w_ + (node[1] + uy_ * s_c) * (1 - w_)])
        C = C2
        Cl = shapely.LineString(C)
        P.setdefault("_median_lines", []).append([list(c_) for c_ in C])     # (the guardrail between the two directions on it, model())
        c0, c1 = Cl.interpolate(0), Cl.interpolate(1.0)
        hc = math.dist(c0.coords[0], c1.coords[0]) or 1.0
        ncx, ncy = -(c1.y - c0.y) / hc, (c1.x - c0.x) / hc          # (the centre line's left, going out from the node)
        tT = tT_      # (the trunk into the node, as drawn)
        t0, t1 = tT.interpolate(tT.length - 1.0), tT.interpolate(tT.length)
        ht = math.dist(t0.coords[0], t1.coords[0]) or 1.0
        ntx, nty = -(t1.y - t0.y) / ht, (t1.x - t0.x) / ht
        t_rev = not (math.dist(pT[-1], node) < math.dist(pT[0], node))
        bands_t = [b for b in (T_["sections"][0] if t_rev else T_["sections"][-1])["bands"] if b["type"] == "lane"]
        for X_, lx in ((A_, la), (B_, lb)):
            x_out = math.dist(X_["line"]["value"][0][:2], node) < 1.0           # (its line leaves the node: a11; else it comes to it: a12)
            sec = X_["sections"][0] if x_out else X_["sections"][-1]
            nxs = 1.0 if x_out else -1.0                                         # (its left, against the centre line's)
            ds = []
            for bx in [b for b in sec["bands"] if b["type"] == "lane"]:
                for bt in bands_t:
                    if (bt.get("lane_id"), bx.get("lane_id")) in conn or (bx.get("lane_id"), bt.get("lane_id")) in conn:
                        tt = -bt["t"] if t_rev else bt["t"]
                        tx = node[0] + ntx * tt - ncx * nxs * bx["t"]
                        ty = node[1] + nty * tt - ncy * nxs * bx["t"]
                        ds.append((tx - node[0]) * ncx + (ty - node[1]) * ncy)
            if not ds:
                continue
            # (its other sections with the same lanes keep the node section's offsets: a12's two OSM ways put its lanes 0.25 m apart,
            # a jog at their joint; Kaveh, 2026-10-12, "a12 has many glitches")
            lanes_n = [b for b in sec["bands"] if b["type"] == "lane"]
            for sc2 in X_["sections"]:
                l2 = [b for b in sc2["bands"] if b["type"] == "lane"]
                if sc2 is not sec and len(l2) == len(lanes_n) and all(abs(b2["width"]["value"] - bn["width"]["value"]) < 0.01 for b2, bn in zip(l2, lanes_n)):
                    for b2, bn in zip(sorted(l2, key=lambda b_: b_["t"]), sorted(lanes_n, key=lambda b_: b_["t"])):
                        b2["t"] = bn["t"]
            d_ = sum(ds) / len(ds)
            ox = Cl.offset_curve(d_) if abs(d_) > 0.01 else Cl
            new = [list(c_) for c_ in ox.coords]
            new = new if math.dist(new[0], C[0]) <= math.dist(new[-1], C[0]) else new[::-1]
            if not x_out:
                new = new[::-1]
            old = shapely.LineString([p_[:2] for p_ in X_["line"]["value"]])
            nln = shapely.LineString(new)
            remap = lambda s_, old=old, nln=nln: round(nln.project(old.interpolate(s_)), 2)
            for sc in X_["sections"]:
                sc["s0"], sc["s1"] = remap(sc["s0"]), remap(sc["s1"])
                for b in sc["bands"]:
                    for key in ("s_from", "s_to"):
                        if b.get(key) is not None:
                            b[key] = remap(b[key])
                    if b.get("taper"):          # (a lane that opens over a taper: its metres move too)
                        b["taper"] = dict(b["taper"], s0=remap(b["taper"]["s0"]), s1=remap(b["taper"]["s1"]))
            X_["sections"][0]["s0"], X_["sections"][-1]["s1"] = 0.0, round(nln.length, 2)
            v = X_.get("vertical")
            if isinstance(v, dict):
                for key in ("points", "samples", "chosen_before"):
                    if isinstance(v.get(key), list):
                        v[key] = [[remap(q2[0])] + list(q2[1:]) for q2 in v[key]]
                if isinstance(v.get("stations"), list):
                    for st_ in v["stations"]:
                        st_["s"] = remap(st_["s"])
            for e in X_.get("ends", []):
                e["s"] = remap(e["s"])
            X_["line"] = {"value": [[round(x, 2), round(y, 2)] for x, y in new], "source": X_["line"]["source"] + "; urbanstyle corrections (corrections/bridges.json)",
                          "method": f"mapped, then beside one line with {ida if X_ is B_ else idb}: the middle of their OSM lines from {idt}'s node, {abs(d_):.2f} m off it"}
            X_["length_m"] = round(nln.length, 2)
            X_["_node"], X_["_node_at"] = list(node), 0 if x_out else 1
            P["_fitted"][X_["id"]] = 0 if x_out else 1
    # a section split at the metres corrections/bridges.json gives ("split_at"), from the start of the axis's line: a4's first lane ran
    # 138 m as OSM's one way; split where it leaves a9's lanes, 52 m (Kaveh, 2026-10-12: "it is too long, I can't use it")
    for a in P["axes"]:
        for s_cut in corr.get("split_at", {}).get(a["id"], []):
            for i_, sc in enumerate(a["sections"]):
                if sc["s0"] + 1.0 < s_cut < sc["s1"] - 1.0:
                    a["sections"][i_:i_ + 1] = [dict(sc, s1=s_cut, bands=[dict(b) for b in sc["bands"]]),
                                                dict(sc, s0=s_cut, bands=[dict(b) for b in sc["bands"]])]
                    break
    # a lane that joins two lanes ("join_lanes" [from lane, its axis, to lane, the axis it runs on]): from where the from lane's
    # piece ends, along that axis, to where the to lane starts, in its place across the road (4747140365369135178_1 a4.0 to
    # 4865609269725927722_2 a9.0: Kaveh, 2026-10-12)
    ax_ = {a["id"]: a for a in P["axes"]}
    for f_lane, f_ax, t_lane, t_ax in corr.get("join_lanes", []):
        A_, B_ = ax_.get(f_ax), ax_.get(t_ax)
        if A_ is None or B_ is None:
            continue
        la_ = shapely.LineString([p_[:2] for p_ in A_["line"]["value"]])
        lb_ = shapely.LineString([p_[:2] for p_ in B_["line"]["value"]])
        fs = [(sc, b) for sc in A_["sections"] for b in sc["bands"] if b.get("lane_id") == f_lane]
        ts = [(sc, b) for sc in B_["sections"] for b in sc["bands"] if b.get("lane_id") == t_lane]
        if not fs or not ts:
            continue
        sc_f, b_f = fs[0]           # (its first piece; its end away from its line's start)
        p0_, p1_ = la_.interpolate(sc_f["s1"] - 1.0), la_.interpolate(sc_f["s1"])
        hh_ = math.dist(p0_.coords[0], p1_.coords[0]) or 1.0
        pe = shapely.Point(p1_.x - (p1_.y - p0_.y) / hh_ * b_f["t"], p1_.y + (p1_.x - p0_.x) / hh_ * b_f["t"])
        s_from = lb_.project(pe)
        sc_t, b_t = ts[0]
        s_to = sc_t["s0"] if abs(sc_t["s0"] - s_from) < abs(sc_t["s1"] - s_from) else sc_t["s1"]
        lo_, hi_ = sorted((s_from, s_to))
        new_b = dict(b_t, lane_id=f"{f_lane}>{t_lane}", lane=None, link=None, source="urbanstyle", s_from=lo_, s_to=hi_,
                     method=f"derived: joins {f_ax}'s {f_lane} to {t_ax}'s {t_lane} (Kaveh, 2026-10-12)")
        out_ = []
        for sc in B_["sections"]:
            if sc["s1"] <= lo_ + 0.5 or sc["s0"] >= hi_ - 0.5:
                out_.append(sc)
                continue
            for a0, a1 in ((sc["s0"], max(sc["s0"], lo_)), (max(sc["s0"], lo_), min(sc["s1"], hi_)), (min(sc["s1"], hi_), sc["s1"])):
                if a1 - a0 > 0.5:
                    mid = a0 >= lo_ - 0.01 and a1 <= hi_ + 0.01
                    out_.append(dict(sc, s0=a0, s1=a1, bands=[dict(b) for b in sc["bands"]] + ([dict(new_b)] if mid else [])))
        B_["sections"] = out_
    return P


def open_tapers(P):
    """P with each lane that opens at its axis's fork (a taper with "clear", correct_sections()) opening where it is clear of the other
    axes' lanes on their drawn lines: a2's second lane past the gore with a7, not on a7's lane at the node (Kaveh, 2026-10-12, "you
    started to convert to two lanes too soon")."""
    import shapely
    lines = {a["id"]: shapely.LineString([q[:2] for q in a["line"]["value"]]) for a in P["axes"]}
    for a in P["axes"]:
        for sc in a["sections"]:
            for b in sc["bands"]:
                tp = b.get("taper")
                if b["type"] != "lane" or not tp or not tp.get("clear"):
                    continue
                ln = lines[a["id"]]
                oth = shapely.union_all([lines[o["id"]].buffer(max((abs(b2["t"]) + b2["width"]["value"] / 2 for sc2 in o["sections"]
                                                                     for b2 in sc2["bands"] if b2["type"] == "lane"), default=3.0))
                                         for o in P["axes"] if o is not a])
                t_in, t_out = tp["inner"], tp["inner"] + tp["out"] * (b["width"]["value"] + TAPER_CLEAR_M)
                for s_ in range(int(sc["s0"]), int(sc["s1"])):
                    p_, q_ = ln.interpolate(s_), ln.interpolate(min(s_ + 1.0, ln.length))
                    h_ = math.dist(p_.coords[0], q_.coords[0]) or 1.0
                    nx_, ny_ = -(q_.y - p_.y) / h_, (q_.x - p_.x) / h_
                    if not oth.intersects(shapely.LineString([(p_.x + nx_ * t_in, p_.y + ny_ * t_in), (p_.x + nx_ * t_out, p_.y + ny_ * t_out)])):
                        b["taper"] = dict(tp, s0=float(s_), s1=min(s_ + TAPER_M, sc["s1"]))
                        break
    # a lane that ends at a node, corrections/bridges.json "lane_ends": [[lane id, "node"]] narrows to nothing at the node over TAPER_M,
    # [[lane id, "clear", axis]] before it, where that axis's lanes come beside it (Kaveh, 2026-10-12, option 1 at the a9/a10/a3 node:
    # a10's third northbound lane ends before a3 comes in, a3's two lanes become one)
    from .corrections import bridge as bridge_corr
    ends_ = {e[0]: e[1:] for e in bridge_corr(P["name"]).get("lane_ends", [])}
    for a in P["axes"]:
        ln = lines[a["id"]]
        for si, sc in enumerate(a["sections"]):
            for b in sc["bands"]:
                if b["type"] != "lane" or b.get("lane_id") not in ends_:
                    continue
                how = ends_[b["lane_id"]]
                at_end = si == len(a["sections"]) - 1
                s_n = sc["s1"] if at_end else sc["s0"]
                back = -1.0 if at_end else 1.0                 # (from the node, into the axis)
                w = b["width"]["value"]
                out = -1 if b["t"] < 0 else 1                  # (it narrows to its inner edge, beside its neighbour)
                inner = b["t"] - out * w / 2
                if how[0] == "clear" and len(how) > 1 and how[1] in lines:
                    o_ = next(o for o in P["axes"] if o["id"] == how[1])
                    oth = lines[o_["id"]].buffer(max((abs(b2["t"]) + b2["width"]["value"] / 2 for sc2 in o_["sections"] for b2 in sc2["bands"]
                                                       if b2["type"] == "lane"), default=3.0))
                    s_ = s_n
                    while (s_ - sc["s0"]) * (sc["s1"] - s_) >= 0:
                        p_, q_ = ln.interpolate(s_), ln.interpolate(min(s_ + 1.0, ln.length))
                        h_ = math.dist(p_.coords[0], q_.coords[0]) or 1.0
                        nx_, ny_ = -(q_.y - p_.y) / h_, (q_.x - p_.x) / h_
                        t_out = inner + out * (w + TAPER_CLEAR_M)
                        if not oth.intersects(shapely.LineString([(p_.x + nx_ * inner, p_.y + ny_ * inner), (p_.x + nx_ * t_out, p_.y + ny_ * t_out)])):
                            break
                        s_ += back
                    s_n = s_
                b["taper"] = {"s0": s_n, "s1": s_n + back * TAPER_M, "inner": inner, "out": out, "ends": how[0],
                              "by": how[1] if how[0] == "clear" and len(how) > 1 else None}
    return P


def rectangles(P):
    """P with each axis that corrections/bridges.json names under "rectangle" drawn as a rectangle with strips (Kaveh, 2026-10-12:
    "make a8 like a rectangle with some strips"): strips of one width each along the axis's own line ("don't change geometry"; a
    line within RECT_STRAIGHT_M of straight, as a8 with its landing, is made straight from end to end); past its fork (where no other axis's lanes are
    within RECT_ROOM_M) every path along it lies at one offset, each kind of path one strip on its side, in the order OSM maps them,
    from the fork to the axis's end, after a barrier beside the lanes; the strip takes the id of the path that runs longest in it,
    the others' pieces there are left out. P["_rects"]: [(the rectangle, the zone where OSM's outline is cut away)], for model()."""
    import numpy as np
    import shapely
    from .corrections import bridge as bridge_corr
    names = bridge_corr(P["name"]).get("rectangle", [])
    names_sp = bridge_corr(P["name"]).get("strip_paths", {})
    # (a path that ends on the axis where OSM's route leaves it, "strip_osm_end": {axis: {way: crossing way}}, not at the axis's end: a4's shared path
    # w1383685288 turns off to w1417439065 100 m along a4; Kaveh, 2026-10-12, "it should go to connect shared path w1417439065")
    osm_end = bridge_corr(P["name"]).get("strip_osm_end", {})
    P["_rects"], P["_rect_axes"], P["_bars"], P["_bare"], P["_bare_zones"] = [], names, [], [], []
    P["_shift_zones"] = []      # (where the paths outside a path that ended move in: the deck freed there is that path's, model())
    ends_ = []      # (kind, axis id, point): where each axis's strips end, for the next axis's strips to start there (join)
    xings_ = [shapely.LineString(g_["line"]) for g_ in P.get("paths", []) if len(g_["line"]) > 1
              and (g_.get("footway") == "crossing" or g_.get("cycleway") == "crossing" or g_.get("crossing"))]
    for a in P["axes"]:
        if a["id"] not in names:
            continue
        pts = a["line"]["value"]
        chord = shapely.LineString([pts[0], pts[-1]])
        # (not a line fillets() fitted to its node: a11 and a12 lost the trunk's way at a10's node, 8.6 degrees off)
        if a["id"] not in P.get("_fitted", {}) and max(chord.distance(shapely.Point(c)) for c in pts) <= RECT_STRAIGHT_M:
            a["line"] = {"value": [pts[0], pts[-1]], "source": a["line"]["source"] + "; urbanstyle corrections (corrections/bridges.json)",
                         "method": "mapped, then straight from end to end (a rectangle)"}
        ln = shapely.LineString(a["line"]["value"])
        L = ln.length

        def nrm(s):
            """The point on the axis at s and its unit normal to the left."""
            p, p0, p1 = ln.interpolate(s), ln.interpolate(max(s - 1, 0)), ln.interpolate(min(s + 1, L))
            h = math.hypot(p1.x - p0.x, p1.y - p0.y) or 1
            return p.x, p.y, -(p1.y - p0.y) / h, (p1.x - p0.x) / h
        at = lambda s, t: (lambda x, y, nx, ny: (x + nx * t, y + ny * t))(*nrm(s))
        st = lambda x, y: (lambda s_: (s_, (lambda px, py, nx, ny: (x - px) * nx + (y - py) * ny)(*nrm(s_))))(ln.project(shapely.Point(x, y)))
        # (a point each metre, moved along the axis's normal, as the lanes are drawn: offset curves cut the bends otherwise, slivers)
        along = lambda s0, s1, t: [at(s0 + k * (s1 - s0) / max(1, round(s1 - s0)), t) for k in range(max(1, round(s1 - s0)) + 1)] if s1 - s0 > 0.5 else []
        # (a section that reaches the ground, a landing, does not set the strips' place: a2's second lane there put its footway 3.25 m
        # out from its one lane all along; on a side where it is wider the strips end where it starts, rectangles below)
        ground_s = [e["s"] for e in a.get("ends", []) if e.get("ground")]
        landing = [sc for sc in a["sections"] if any(min(abs(sc["s0"] - g_), abs(sc["s1"] - g_)) < 0.5 for g_ in ground_s)]
        body_ = [sc for sc in a["sections"] if not any(sc is l_ for l_ in landing)] or a["sections"]
        # (nor does a lane that opens over a taper, correct_sections(): the strips move out with it, wide_; a2's second lane)
        bands = [b for sc in body_ for b in sc["bands"] if b["type"] == "lane" and not b.get("taper")] or \
            [b for sc in body_ for b in sc["bands"] if b["type"] == "lane"]
        hi = max(b["t"] + b["width"]["value"] / 2 for b in bands)
        lo = min(b["t"] - b["width"]["value"] / 2 for b in bands)
        wide_ = []      # (side, from s, to s, by): where the lanes widen on that side past the strips' place, in the axis's own s
        for sc in a["sections"]:
            for b in sc["bands"]:
                tp_ = b.get("taper") if b["type"] == "lane" else None
                if tp_ and b["t"] + b["width"]["value"] / 2 > hi + 0.01:
                    wide_.append((1, tp_["s0"], tp_["s1"], b["width"]["value"]))
                elif tp_ and b["t"] - b["width"]["value"] / 2 < lo - 0.01:
                    wide_.append((-1, tp_["s0"], tp_["s1"], b["width"]["value"]))
                # (the outer lane ending, "lane_ends": the strips move in with its edge, from where it narrows to where it is gone; a3's
                # barrier @-127,-307 stayed out while barrier @-208,-164 followed the lane in, Kaveh, 2026-10-12)
                elif tp_ and tp_.get("ends") and abs(b["t"] + b["width"]["value"] / 2 - hi) < 0.01:
                    wide_.append((1, tp_["s1"], tp_["s0"], -b["width"]["value"]))
                elif tp_ and tp_.get("ends") and abs(b["t"] - b["width"]["value"] / 2 - lo) < 0.01:
                    wide_.append((-1, tp_["s1"], tp_["s0"], -b["width"]["value"]))
        others, runs_on, runs_ids, run_nodes, all_nodes, sibs = [], [], set(), [], [], []
        pa = a["line"]["value"]
        for o in P["axes"]:
            if o is a:
                continue
            # (not the road it runs on into at a shared node, a1 for a6: its lanes move onto that road's there, and the strips with
            # them; only a branch beside it, across a gore, stops its strips; Kaveh, 2026-10-12: "connect a6, a8 and a5 smoothly to a1")
            po = o["line"]["value"]
            ob = [b for sc in o["sections"] for b in sc["bands"] if b["type"] == "lane"]
            w = max((abs(b["t"]) + b["width"]["value"] / 2 for b in ob), default=4.0)
            band = shapely.LineString(o["line"]["value"]).buffer(w, cap_style="flat")
            # (an axis drawn as two lines and a curve, fillets(), starts beside its node: its node stands for its start)
            pa_e = [a["_node"] if a.get("_node_at") == 0 else pa[0], a["_node"] if a.get("_node_at") == 1 else pa[-1]]
            po_e = [o["_node"] if o.get("_node_at") == 0 else po[0], o["_node"] if o.get("_node_at") == 1 else po[-1]]
            all_nodes.extend(f_ for f_ in po_e if min(math.dist(f_, pa_e[0]), math.dist(f_, pa_e[1])) < 1.0)
            if any(math.dist(pa_e[ia], po_e[io]) < 1.0 and _continues(pa, ia == 1, po, io == 0) for ia in (0, 1) for io in (0, 1)):
                run_nodes.extend(f_ for f_ in po_e if min(math.dist(f_, pa_e[0]), math.dist(f_, pa_e[1])) < 1.0)
                runs_on.append(shapely.LineString(o["line"]["value"]).buffer(w))      # (round past the node: the branches' lanes start there)
                runs_ids.add(o["id"])
                continue
            others.append(band)
            # (a sibling branch from the same node, a9 beside a4: on which side of it, 30 m out, for the strips of the other side)
            for ia in (0, 1):
                for io in (0, 1):
                    if math.dist(pa_e[ia], po_e[io]) < 1.0:
                        lo_ln = shapely.LineString(po if io == 0 else po[::-1])
                        la_ln = shapely.LineString(pa if ia == 0 else pa[::-1])
                        q30, a0_, a1_ = lo_ln.interpolate(min(30.0, lo_ln.length)), la_ln.interpolate(0), la_ln.interpolate(min(1.0, la_ln.length))
                        sd = (a1_.x - a0_.x) * (q30.y - a0_.y) - (a1_.y - a0_.y) * (q30.x - a0_.x)
                        sibs.append((len(others) - 1, (1 if sd > 0 else -1) * (1 if ia == 0 else -1)))
        # (and a branch beside it only where it has left that road: at the node a8's lanes lie in a1's, and stopped a6's strips there)
        bands_o = list(others)
        others = shapely.union_all(others).difference(shapely.union_all(runs_on)) if runs_on else shapely.union_all(others)
        shapely.prepare(others)             # (tested at every metre of the axis)
        rev = others.distance(shapely.Point(ln.coords[-1])) < others.distance(shapely.Point(ln.coords[0]))
        if rev:
            # (its fork at its last point, a6: s counted from the free end; left and right swap)
            ln = ln.reverse()
            hi, lo = -lo, -hi
            sibs = [(i_, -sd_) for i_, sd_ in sibs]
        others_side = {}
        for sd_ in (1, -1):         # (a side's view: without the sibling branches on the other side)
            keep_ = [b_ for i_, b_ in enumerate(bands_o) if not any(i_ == j_ and s2 != sd_ for j_, s2 in sibs)]
            g_ = shapely.union_all(keep_) if keep_ else shapely.Polygon()
            g_ = g_.difference(shapely.union_all(runs_on)) if runs_on else g_
            shapely.prepare(g_)
            others_side[sd_] = g_

        def spec(s0, s1, ta, tb=None):
            """A strip from s0 to s1 at t (or between ta and tb), in the axis's own s and t (not reversed): model() draws it with the
            lanes' own function, so it moves with them where they move onto the main road's at a fork"""
            o0, o1 = ((L - s0, L - s1) if rev else (s0, s1))
            f_ = -1.0 if rev else 1.0
            return {"axis": a["id"], "s0": min(o0, o1), "s1": max(o0, o1), "t": f_ * ta, "tb": None if tb is None else f_ * tb}

        def end_pt(s_):
            """The axis's point at s_; at its start, its node where fillets() moved the start beside it"""
            at_first = (s_ > L - 0.5) if rev else (s_ < 0.5)          # (at the line's first point; else at its last)
            at_last = (s_ < 0.5) if rev else (s_ > L - 0.5)
            if "_node" in a and ((a.get("_node_at") == 0 and at_first) or (a.get("_node_at") == 1 and at_last)):
                return tuple(a["_node"])
            return at(s_, 0.0)

        def tie(kind, s_, side, rank):
            """At a node where the road runs on (a6 from a1; Kaveh, 2026-10-12), the end of that road's strip this one continues:
            the same kind on the side facing this side (its outer edge nearest), the same place in the order from the lanes; None"""
            if not (runs_ids and (s_ < 0.5 or s_ > L - 0.5) and any(math.dist(end_pt(s_), n_) < 1.0 for n_ in run_nodes)):
                return None         # (only at a node the road it runs on meets: not at a8's free north end)
            probe = at(s_, side * ((hi if side == 1 else -lo) + 6.0))
            edges_ = [e for e in ends_ if e["kind"] == "edge" and e["axis"] in runs_ids and e["node"]]
            if not edges_:
                return None
            e0 = min(edges_, key=lambda e: math.dist(e["pt"], probe))
            same = [e for e in ends_ if e["kind"] == kind and e["axis"] == e0["axis"] and e["side"] == e0["side"] and e["rank"] == rank and e["node"]]
            return min(same, key=lambda e: math.dist(e["pt"], e0["pt"])) if same else None

        def joined(sp, kind, s_pairs, which="t", width_=None, way_=None, side=1, rank=0):
            """sp tied at a node to the strip of the road it runs on that it continues (tie): it starts at that strip's end and moves to
            its own place over RECT_BLEND_M; its own ends recorded for the axes after it"""
            for s_, t_ in s_pairs:
                e_ = tie(kind, s_, side, rank) if RECT_TIE else None
                if e_:
                    sp["join_" + which] = list(e_["pt"])
                ends_.append({"kind": kind, "axis": a["id"], "pt": at(s_, t_), "width": width_, "way": way_, "side": side, "rank": rank,
                              "node": (s_ < 0.5 or s_ > L - 0.5) and any(math.dist(end_pt(s_), n_) < 1.0 for n_ in all_nodes)})
            return sp

        def span(t0_, t1_):
            """(from, to): the longest stretch where its cross-section from t0_ to t1_ meets no other axis's lanes (a fork at either
            end, a1, or at one, a8)"""
            oth_ = others if (t0_ < 0 < t1_) else others_side[1 if t0_ + t1_ > 0 else -1]
            free = [not shapely.LineString([at(s, t0_), at(s, t1_)]).intersects(oth_) for s in range(int(L) + 1)]
            best, run0 = (0.0, 0.0), None       # (the longest free stretch: a2's middle passes near a3, from the middle it had none)
            for s, ok in enumerate(free + [False]):
                if ok and run0 is None:
                    run0 = s
                elif not ok and run0 is not None:
                    s0_ = 0.0 if run0 == 0 else run0 + 0.0
                    s1_ = L if s - 1 >= int(L) else s - 1.0
                    if s1_ - s0_ > best[1] - best[0]:
                        best = (s0_, s1_)
                    run0 = None
            return best
        sg, se = span(lo - RECT_ROOM_M, hi + RECT_ROOM_M)
        olines = shapely.union_all([shapely.LineString(o["line"]["value"]) for o in P["axes"] if o is not a])
        own_ln = shapely.LineString(a["line"]["value"])

        def find(sg, se):
            """(side, path type) -> [(the indexes of its points in the rectangle, its points, the path, its median offset)]: the paths
            along the axis from sg to se (on its side: {1: left, -1: right}); a point nearer another axis is that axis's"""
            groups = {}
            for f in P.get("paths", []):
                if f.get("footway") == "crossing" or f.get("cycleway") == "crossing" or f.get("crossing") or len(f["line"]) < 2:
                    continue
                q = [c for c in shapely.LineString(f["line"]).segmentize(1.0).coords]
                # (all its points at once: one at a time took seconds)
                pts = shapely.points(np.array(q)[:, :2])
                S_ = shapely.line_locate_point(ln, pts)
                c0 = shapely.get_coordinates(shapely.line_interpolate_point(ln, S_))
                ca = shapely.get_coordinates(shapely.line_interpolate_point(ln, np.maximum(S_ - 1, 0)))
                cb = shapely.get_coordinates(shapely.line_interpolate_point(ln, np.minimum(S_ + 1, L)))
                d_ = cb - ca
                h_ = np.hypot(d_[:, 0], d_[:, 1])
                h_[h_ == 0] = 1.0
                T_ = ((np.array(q)[:, 0] - c0[:, 0]) * -d_[:, 1] + (np.array(q)[:, 1] - c0[:, 1]) * d_[:, 0]) / h_
                s_lo = np.where(T_ > 0, sg[1], sg[-1])
                s_hi = np.where(T_ > 0, se[1], se[-1])
                # (a path corrections/bridges.json gives this axis, "strip_paths": its own here even where another axis is nearer:
                # footway w538616397 on a10's east, nearer a3's line, Kaveh, 2026-10-12)
                forced_ = f["way"] in names_sp.get(a["id"], [])
                ok = (s_lo <= S_) & (S_ <= s_hi) & (lo - RECT_ROOM_M <= T_) & (T_ <= hi + RECT_ROOM_M) & \
                     ((shapely.distance(own_ln, pts) <= shapely.distance(olines, pts)) | forced_)
                ins = [int(i) for i in np.nonzero(ok)[0]]
                if len(ins) < 10:
                    continue
                if len(ins) < RECT_MIN_M:
                    continue        # (a short link, w1417439072's 14 m beside a1: no strip of 550 m, it keeps OSM's line)
                ts = sorted(float(T_[i]) for i in ins)
                groups.setdefault((1 if ts[len(ts) // 2] > 0 else -1, f["type"]), []).append((ins, q, f, abs(ts[len(ts) // 2])))
            return groups

        def reach_of(groups, side):
            if not any(k[0] == side for k in groups):
                return hi if side == 1 else -lo
            r = (hi if side == 1 else -lo) + BARRIER_SEP_M[0]
            return r + sum(max(mem, key=lambda m: len(m[0]))[2]["width"]["value"] for k, mem in groups.items() if k[0] == side)
        # the rectangle starts where it no longer reaches the other axes' lanes (at the fork), not RECT_ROOM_M past it: the old shape
        # stayed between the two and left steps and teeth (Kaveh, 2026-10-12: "not clean at the end of a8")
        g0 = find({1: sg, -1: sg}, {1: se, -1: se})
        e1_, e2_ = reach_of(g0, 1) + BARRIER_M[1], reach_of(g0, -1) + BARRIER_M[1]
        # each side on its own: its strips run back to where the next branch leaves on that side (Kaveh, 2026-10-12: "before reaching
        # the next branch, the rectangle")
        sg, se, land_cuts = {}, {}, {}
        for side, (t0_, t1_) in ((1, (hi, e1_)), (-1, (-e2_, lo))):
            sg[side], se[side] = span(t0_, t1_)
            # (a wider landing on this side: the strips move out by its extra width as its added lane opens, over TAPER_M; a2's
            # footway beside its second lane to its end, Kaveh, 2026-10-12 "the end part of a2 is messed")
            land_cuts[side] = []
            for w_side, w0_, w1_, by_ in wide_:
                if (-w_side if rev else w_side) == side:
                    land_cuts[side].append(((L - w0_) if rev else w0_, (L - w1_) if rev else w1_, -by_))
        groups = find(sg, se)
        edge = {1: hi, -1: -lo}
        side_cuts = {1: [], -1: []}

        def shifted(sp, which, cuts, side):
            """sp moved in towards the lanes by each cut's width past its start, over RECT_BLEND_M (model: spec_pts)"""
            if cuts:
                f_ = -1.0 if rev else 1.0
                sp["shift_" + which] = [((L - c0) if rev else c0, (L - c1) if rev else c1, f_ * -side * w_) for c0, c1, w_ in cuts]
            return sp
        for side in (1, -1):
            reach = edge[side] + BARRIER_SEP_M[0]
            rank_ = -1
            # in OSM's order from the lanes; a path that runs on from the trunk's strips (the same way) keeps its place there: a1's shared
            # path w1383685288 next to the barrier, footway w871038559 outside it, on a4 too (Kaveh, 2026-10-12: "same width")
            # (the others, in OSM's order, take the free places: a6's cycleway before its footway w871038559, which is a1's second)
            gs_ = sorted(((k, v) for k, v in groups.items() if k[0] == side), key=lambda kv: min(m[3] for m in kv[1]))
            fixed_ = {}
            for i_g, (k_g, v_g) in enumerate(gs_):
                f_ = max(v_g, key=lambda m: len(m[0]))[2]
                same = [e for e in ends_ if e["kind"] == "path" and e["axis"] in runs_ids and e["node"] and e["way"] == f"{f_['type']} {f_['way']}"]
                if same and min(e["rank"] for e in same) < len(gs_) and min(e["rank"] for e in same) not in fixed_.values():
                    fixed_[i_g] = min(e["rank"] for e in same)
            cuts_ = list(land_cuts[side])      # (from s, to s, width): past the end of a path that ends where OSM's does, the paths outside it move in by its width
            free_ = iter(r_ for r_ in range(len(gs_)) if r_ not in fixed_.values())
            place_ = {i_g: fixed_[i_g] if i_g in fixed_ else next(free_) for i_g in range(len(gs_))}
            for (_, kind), mem in [gs_[i_g] for i_g in sorted(place_, key=place_.get)]:
                ins, q, f, _ = max(mem, key=lambda m: len(m[0]))
                w = f["width"]["value"]
                rank_ += 1
                # (continuing another road's strip at the node, it takes that strip's width: a6's cycleway w1419312043 the 4 m of a1's
                # shared path w1383685288; Kaveh, 2026-10-12: "size ... not matched")
                for s_ in (sg[side], se[side]):
                    e_ = tie("path", s_, side, rank_)
                    # (the same way there first: a7's footway w871038559 continues a4's, not a4's shared path at its rank)
                    e_ = e_ and next((e for e in ends_ if e["kind"] == "path" and e["axis"] == e_["axis"] and e["node"]
                                      and e["way"] == f"{f['type']} {f['way']}"), e_)
                    if e_ and e_["width"] and abs(e_["width"]["value"] - w) > 0.01:
                        f["width"] = {"value": e_["width"]["value"], "source": "urbanstyle",
                                      "method": f"derived: the width of {e_['way']}, the strip it continues at the node"}
                        w = e_["width"]["value"]
                tc = side * (reach + w / 2)
                reach += w
                fwd = st(*q[ins[-1]])[0] >= st(*q[ins[0]])[0]
                p0_, p1_ = sg[side], se[side]
                if f["way"] in osm_end.get(a["id"], {}):
                    # (on to the crossing where OSM's route leaves the axis, the way named: w1383685288 by w1417439070 to the cycle
                    # crossing w1417439066 over a4)
                    S_ins = [st(*q[i_])[0] for i_ in ins]
                    xw_ = next((g_ for g_ in P["paths"] if g_["way"] == osm_end[a["id"]][f["way"]]), None)
                    if xw_:
                        S_ins.append(sum(st(*c_[:2])[0] for c_ in xw_["line"]) / len(xw_["line"]))
                    p1_ = max(S_ins) if max(S_ins) < se[side] - RECT_PIECE_M else p1_
                    p0_ = min(S_ins) if min(S_ins) > sg[side] + RECT_PIECE_M else p0_
                # (its line moved in as model() draws it, shifted(): the cut past the next axis's start keeps off the real path)
                sm_ = lambda u: u * u * (3 - 2 * u)
                slot = [at(s_, tc - side * sum(w_ * sm_(min(max((s_ - c0) / (c1 - c0), 0.0), 1.0)) for c0, c1, w_ in cuts_))
                        for s_ in [p0_ + k_ * (p1_ - p0_) / max(1, round(p1_ - p0_)) for k_ in range(max(1, round(p1_ - p0_)) + 1)]]
                slot = slot if fwd else slot[::-1]
                # the strip on its own, square at both ends; OSM's line before and after it its own pieces (joined to it by a jump,
                # the jump lay on a9's lanes and was cut into a slanted stub: Kaveh, 2026-10-12, "footway w538616396 #2 is not strips")
                for k_p, part_ in enumerate((q[:ins[0]], q[ins[-1] + 1:])):
                    if len(part_) < 2:
                        continue
                    # (a short end that reaches a crossing goes on from the strip's end to it: the path meets its crosswalk; footway
                    # w871038563 stopped 8 m before the crosswalk over a5, Kaveh, 2026-10-14, "must continue till it reaches the crosswalk")
                    far_ = shapely.Point(part_[0] if k_p == 0 else part_[-1])
                    to_x = any(x_.distance(far_) < 1.0 for x_ in xings_)
                    if shapely.LineString(part_).length >= RECT_PIECE_M or to_x:     # (else a stub: a 2.4 m end, footway w871038563 #2)
                        line_ = [list(c) for c in part_]
                        if to_x and shapely.LineString(part_).length < RECT_PIECE_M:
                            line_ = line_ + [list(slot[0])] if k_p == 0 else [list(slot[-1])] + line_
                        if to_x:        # (and the gore it runs in to the crossing is that path, as "gore_paths" says: model())
                            x_ = min(xings_, key=lambda x_: x_.distance(far_))
                            P.setdefault("_gore_auto", []).append((a["id"], [list(c) for c in x_.coords], f["way"]))
                        P["paths"].append({k_: v_ for k_, v_ in f.items() if k_ not in ("_slot", "rectangle", "line")} | {"line": line_, "_leftover": True})
                f["line"] = [list(c) for c in slot]
                f["_slot"] = {**joined(shifted(spec(p0_, p1_, tc), "t", cuts_, side), "path", [(p0_, tc), (p1_, tc)], width_=f["width"],
                                       way_=f"{f['type']} {f['way']}", side=side, rank=rank_), "pre": [], "post": [],
                              "first": list(slot[0])}
                f["rectangle"] = f"{a['id']}: one strip from s {p0_:.0f} m to {p1_:.0f} m (corrections/bridges.json)"
                le_ = hi if side == 1 else -lo
                if p1_ < se[side]:
                    cuts_.append((p1_, p1_ + RECT_BLEND_M, w))
                    P["_shift_zones"].append(spec(p1_, min(p1_ + RECT_BLEND_M, se[side]), side * le_, side * reach))
                if p0_ > sg[side]:
                    cuts_.append((p0_, p0_ - RECT_BLEND_M, w))
                    P["_shift_zones"].append(spec(max(p0_ - RECT_BLEND_M, sg[side]), p0_, side * le_, side * reach))
                P.setdefault("_strip_t", {})[(a["id"], f["way"])] = abs(tc)
                for ins2, q2, f2, _ in mem:          # the others of its kind on that side: only their pieces outside the rectangle
                    if f2 is f:
                        continue
                    before, after = q2[:ins2[0]], q2[ins2[-1] + 1:]
                    f2["line"] = [list(c) for c in before] if len(before) >= 2 and shapely.LineString(before).length >= RECT_PIECE_M else []
                    f2["_leftover"] = True
                    if len(after) >= 2 and shapely.LineString(after).length >= RECT_PIECE_M:
                        P["paths"].append({k_: v_ for k_, v_ in f2.items() if k_ not in ("_slot", "rectangle", "line")} | {"line": [list(c) for c in after], "_leftover": True})
            if not any(k[0] == side for k in groups):     # (a side with no path, as OSM maps a5's left: the guard beside the lanes)
                P["_bare"].append((a["id"], -side if rev else side))
                if se[side] - sg[side] > 1.0:     # (and nothing past its guard: Kaveh, 2026-10-12, "no gap between barrier @427,537 and a6")
                    le_ = hi if side == 1 else -lo
                    P["_bare_zones"].append(spec(sg[side], se[side], side * (le_ + BARRIER_M[1]), side * (le_ + RECT_CUT_M)))
            side_cuts[side] = cuts_
            if any(k[0] == side for k in groups):
                edge[side] = reach
                # its barrier a strip too, between the lanes and the first path, drawn as they are (model: P["_bars"])
                tb_ = side * ((hi if side == 1 else -lo) + BARRIER_SEP_M[0] / 2)
                P["_bars"].append(joined(shifted(spec(sg[side], se[side], tb_), "t", land_cuts[side], side), "bar", [(sg[side], tb_), (se[side], tb_)], side=side))
        P["paths"] = [f for f in P.get("paths", []) if len(f["line"]) >= 2]
        e1, e2 = edge[1] + BARRIER_M[1], edge[-1] + BARRIER_M[1]
        # (past a free end the zone reaches 1 m further: OSM's outline there is cut too)
        start = shapely.union_all([shapely.Point(at(s_, side * e_)).buffer(RECT_START_M) for side, e_ in ((1, e1), (-1, e2))
                                   for s_ in (sg[side], se[side]) if 0.5 < s_ < L - 0.5 or others.distance(shapely.Point(at(s_, 0.0))) < 1.0])
        # (and where the strips reach a fork at the axis's own end, a1: OSM's outline left notches there too)
        hspec = lambda side, t0_, t1_, past: [joined(spec(sg[side], se[side] + (past if se[side] >= L - 0.5 else 0.0), t0_, t1_), "edge",
                                                     [(sg[side], t1_ if side == 1 else t0_), (se[side], t1_ if side == 1 else t0_)],
                                                     "tb" if side == 1 else "t", side=side)] if se[side] - sg[side] > 1.0 else []
        # past a strip's end at the node where the road runs on (a1 into a9 and a4), OSM's outline is cut too for RECT_PAST_M, but not on
        # another axis's lanes or paths: it left tails beside a1's start, joined into its paths
        past_ = []
        keep_ = shapely.union_all([o_band.buffer(0.5) for o_band in runs_on] + [others.buffer(0.5)] +
                                  [shapely.LineString(f_["line"]).buffer(f_["width"]["value"] / 2 + 0.5) for f_ in P["paths"]
                                   if len(f_["line"]) > 1 and not f_.get("rectangle", "").startswith(a["id"] + ":")])
        for side, e_ in ((1, e1), (-1, e2)):
            ledge = hi if side == 1 else -lo
            for s_, out_ in ((sg[side], -1.0), (se[side], 1.0)):
                if se[side] - sg[side] <= 1.0 or 0.5 < s_ < L - 0.5 or not runs_on:
                    continue
                p0_, p1_ = at(s_ - out_, 0.0), at(s_, 0.0)
                h_ = math.dist(p0_, p1_) or 1.0
                tx_, ty_ = (p1_[0] - p0_[0]) / h_ * RECT_PAST_M, (p1_[1] - p0_[1]) / h_ * RECT_PAST_M
                A_, B_ = at(s_, side * ledge), at(s_, side * (e_ + RECT_CUT_M))
                past_.append(shapely.Polygon([A_, B_, (B_[0] + tx_, B_[1] + ty_), (A_[0] + tx_, A_[1] + ty_)]).buffer(0).difference(keep_))
        P["_rects"].append(([shifted(sp_, "tb", side_cuts[1], 1) for sp_ in hspec(1, 0.0, e1, 0.0)] +
                            [shifted(sp_, "t", side_cuts[-1], -1) for sp_ in hspec(-1, -e2, 0.0, 0.0)], hspec(1, 0.0, e1 + RECT_CUT_M, 1.0) + hspec(-1, -e2 - RECT_CUT_M, 0.0, 1.0),
                            others.buffer(RECT_KEEP_M), start, shapely.union_all(past_) if past_ else shapely.Polygon()))      # (the zone not on the other axes' own deck: their paths)
    return P


def model(path, parts=None, marks=None, ground=None, flat_only=False, poles=None):
    """The 3D model of the bridge profile at `path` (or the profile itself). `parts`, `marks`: the street's own parts and marks that lie
    on the bridge (a unit's level > 0 spaces: [(props, polygon)], [(type, line)], in the profile's crs), laid on the deck so the bridge
    is drawn as its street; elsewhere the model's lanes and paths in the street's types. `ground`: the street's lanes at level 0 near
    the bridge ([polygon], same crs): a bridge lane that lands on one moves to its place and width over the last LAND_BLEND_M. `poles`:
    the street's surveyed poles near the bridge ([(x, y)], same crs: a city's lamps, OSM's): a lane keeps POLE_CLEAR_M clear of each, as
    on the ground (blocks.md, the kerbs; Granville Bridge: lamp street-lighting-poles-133 on the edge of lane a2.1, Kaveh, 2026-10-13)."""
    import pyproj
    import shapely
    import shapely.affinity
    from shapely.ops import substring

    P = fit_lanes(rectangles(open_tapers(fillets(correct_sections(json.load(open(path)) if isinstance(path, str) else json.loads(json.dumps(path)))))))
    # on a bridge no move joins the two directions (Kaveh, 2026-10-11: "only merge and fork"): SUMO's moves that turn more than 90 degrees
    # (U-turns and left turns across the guardrail, e.g. a3 into a10 southbound) are dropped; every node is then a merge or a fork
    P["connectors"] = [c for c in P.get("connectors", []) if len(c["line"]) < 2 or abs(_turn(c["line"])) <= NO_TURN_DEG]
    to_ll = pyproj.Transformer.from_crs(P["crs"], "EPSG:4326", always_xy=True).transform
    ol = P["deck"]["outline"]["value"]
    xs_, ys_ = [x for x, _ in ol], [y for _, y in ol]
    x0, y0 = (min(xs_) + max(xs_)) / 2, (min(ys_) + max(ys_)) / 2       # the middle of the bridge: every part near the origin
    DECK_M, RAIL_M = P["deck"]["thickness"]["value"], P["deck"]["parapet"]["value"]
    S = surface(P, x0, y0)
    axes, deck, z, frame = S["axes"], S["deck"], S["z"], S["frame"]
    if flat_only:       # (the 2D page: no heights, no triangles, no checks; seconds instead of a minute)
        z = lambda x, y: 0.0
    rel = lambda ps: [(x - x0, y - y0) for x, y in ps]
    by_id = {a["id"]: (ln, a) for ln, a in axes}

    # a bridge lane that lands on a ground lane (the street's own, level 0): its edges move to that lane's over the last LAND_BLEND_M
    gl = [shapely.affinity.translate(g, -x0, -y0) for g in (ground or [])]
    pole_clear = shapely.union_all([shapely.Point(x - x0, y - y0).buffer(POLE_CLEAR_M) for x, y in (poles or [])])
    gtree = shapely.STRtree(gl) if gl else None
    land = {}       # (axis id, section index, band index) -> [(end, the ground lane's edges at s, s_full, blend length)]

    def cross(ln, g, s):
        """The ground lane g's (left, right) edge offsets across the axis at s, or None where it does not cross."""
        x, y, nx, ny = frame(ln, s)
        cut = shapely.LineString([(x - nx * 20, y - ny * 20), (x + nx * 20, y + ny * 20)]).intersection(g)
        ts = [(q[0] - x) * nx + (q[1] - y) * ny for g_ in shapely.get_parts(cut) if g_.geom_type == "LineString" for q in g_.coords]
        return (max(ts), min(ts)) if len(ts) >= 2 and max(ts) - min(ts) > 1.0 else None
    for ln, a in axes:
        for e in (0, 1):
            if gtree is None or not a["ends"][e].get("ground") or not a["sections"]:
                continue
            si = len(a["sections"]) - 1 if e else 0
            x, y, nx, ny = frame(ln, ln.length if e else 0.0)
            for bi, b in enumerate(a["sections"][si]["bands"]):
                if b["type"] != "lane":
                    continue
                pt = shapely.Point(x + nx * b["t"], y + ny * b["t"])
                near = [k for k in gtree.query(pt.buffer(2.0)) if gl[k].distance(pt) <= 2.0]
                if not near:
                    continue
                # (only a ground lane that runs on past the end, the lane it continues: not one beside the landing; a2's added lane took
                # the street's lane beside it and opened a wedge with a barrier in it, Kaveh, 2026-10-12 "the end part of a2 is messed")
                ex_, ey_ = (ny, -nx) if e else (-ny, nx)        # (out of the axis's end)
                past_ = shapely.Point(pt.x + ex_ * LAND_PAST_M, pt.y + ey_ * LAND_PAST_M)
                near = [k for k in near if gl[k].distance(past_) <= 0.5]
                if not near:
                    continue
                g = gl[min(near, key=lambda k: gl[k].distance(pt))]
                c0 = cross(ln, g, ln.length if e else 0.0)
                if c0 is None:
                    continue
                # the ground lane lies under the landing as far as it is (nearly) full width: there the bridge lane takes its edges
                full = c0[0] - c0[1]
                sf, step = (ln.length, -1.0) if e else (0.0, 1.0)
                while 0.0 <= sf + step <= ln.length:
                    c = cross(ln, g, sf + step)
                    if c is None or c[0] - c[1] < 0.8 * full:
                        break
                    sf += step
                # the move to the ground lane (LAND_BLEND_M before sf) stays inside this section: only its own bands move, and a move
                # that began in the section before started with a step at the joint (a2.0 / a2.1 1.6 m apart, and a hole in the deck
                # beside them: Kaveh, 2026-10-14, "not matched perfectly", "triangle barrier issue barrier @-387,-395")
                sc_ = a["sections"][si]
                sf = max(sf, min(sc_["s0"] + LAND_BLEND_M, sc_["s1"])) if e else min(sf, max(sc_["s1"] - LAND_BLEND_M, sc_["s0"]))
                land.setdefault((a["id"], si, bi), []).append((e, (lambda ln_, g_: lambda s_: cross(ln_, g_, s_))(ln, g), sf,
                                                               min(LAND_BLEND_M, sc_["s1"] - sc_["s0"]) or 1e-9))

    # a fork or a join, not a junction: a node where every move SUMO makes runs nearly straight on (under JOIN_ANGLE), as where the bridge's
    # divided road (a11, a12) joins the single road a10, or where the main span a1 splits into a9 and a4. OSM's ways meet at one node, so
    # the lanes of each, laid on its own line, jumped sideways there or lay on each other (Kaveh: "no junction, a straight road"). There
    # each lane of the other arms moves, over its last JOIN_BLEND_M, to the place of the lane it runs into on the arm with the most lanes
    # (carried straight on past the node); no junction is drawn, and the lanes meet
    band_at = {}            # lane id -> (axis line, axis, end section's band)
    for ln, a in axes:
        for sc in (a["sections"][0], a["sections"][-1]):
            for b in sc["bands"]:
                if b["type"] == "lane" and b.get("lane_id"):
                    band_at[b["lane_id"]] = (ln, a, b)
    at_node = {}
    for ln, a in axes:
        for e, end in enumerate(a.get("ends", [])):
            if end.get("node"):
                at_node.setdefault(end["node"], []).append((ln, a, e))

    def heading(line, first):
        (ax_, ay_), (bx_, by_) = (line.coords[0], line.interpolate(min(2.0, line.length)).coords[0]) if first else \
            (line.interpolate(max(line.length - 2.0, 0.0)).coords[0], line.coords[-1])
        h_ = math.hypot(bx_ - ax_, by_ - ay_) or 1
        return (bx_ - ax_) / h_, (by_ - ay_) / h_
    lane_join, split_lanes, join_ends = {}, set(), set()     # lane id -> its blend; lane ids at a fork or join; (axis id, end) there
    conn_ = {(c["from"], c["to"]) for c in P.get("connectors", [])}      # (SUMO's lane-to-lane moves)
    # a lane that corrections/bridges.json links ("lane_links") is placed by that link, not SUMO's (a3's _2 on a9's _3, Kaveh, 2026-10-12)
    from .corrections import bridge as bridge_corr_
    user_ = {tuple(x_) for x_ in bridge_corr_(P["name"]).get("lane_links", [])}
    user_lanes_ = {l_ for pr_ in user_ for l_ in pr_}
    for node, ents in at_node.items():
        if len(ents) < 2:
            continue
        ids = {a["id"] for _, a, _ in ents}
        xn, yn = frame(ents[0][0], ents[0][0].length if ents[0][2] else 0.0)[:2]
        cs = [c for c in P.get("connectors", []) if c["from"] in band_at and c["to"] in band_at and band_at[c["from"]][1]["id"] in ids
              and band_at[c["to"]][1]["id"] in ids and band_at[c["from"]][1]["id"] != band_at[c["to"]][1]["id"]
              and shapely.Point(c["line"][0]).distance(shapely.Point(c["line"][-1])) < 60 and len(c["line"]) > 1
              and min(math.dist(rel([c["line"][0]])[0], (xn, yn)), math.dist(rel([c["line"][-1]])[0], (xn, yn))) < 30]
        if not cs:
            continue
        ok = True
        for c in cs:
            cl = shapely.LineString(rel(c["line"]))
            (ux, uy), (vx, vy) = heading(cl, True), heading(cl, False)
            if math.degrees(math.acos(max(-1.0, min(1.0, ux * vx + uy * vy)))) > JOIN_ANGLE:
                ok = False
                break
        if not ok:
            continue
        # the trunk: the arm with the most lanes at the node; the others move to it
        lanes_at = lambda a, e: [b for b in a["sections"][-1 if e else 0]["bands"] if b["type"] == "lane"]
        # the trunk: the arm on the other side of the node from all the others (the one road that splits, or that they join into)
        def away(x):
            _, _, nx_, ny_ = frame(x[0], x[0].length if x[2] else 0.0)
            return (ny_, -nx_) if x[2] == 0 else (-ny_, nx_)
        aw = [away(x) for x in ents]
        lnT, T, eT = min(ents, key=lambda x: sum(aw[i][0] * away(x)[0] + aw[i][1] * away(x)[1] for i, y in enumerate(ents) if y is not x))
        xT, yT, nxT, nyT = frame(lnT, lnT.length if eT else 0.0)
        tx_, ty_ = (nyT, -nxT) if eT == 0 else (-nyT, nxT)       # T's tangent, pointing away from the other arms (the way it runs on)
        groups_ = {}        # the trunk's direction -> [(O, end, sign, the group's lanes, their middle in O's frame, their width)]
        for lnO, O, eO in ents:
            join_ends.add((O["id"], eO))
            split_lanes |= {b["lane_id"] for b in lanes_at(O, eO) if b.get("lane_id")}
            if O["id"] == T["id"]:
                continue
            nxO, nyO = frame(lnO, lnO.length if eO else 0.0)[2:]
            sg = 1 if nxO * nxT + nyO * nyT > 0 else -1          # the two axes point the same way at the node: O's left is T's left
            part = {}
            for c in cs:
                for mine_, other in ((c["from"], c["to"]), (c["to"], c["from"])):
                    if band_at[mine_][1]["id"] == O["id"] and band_at[other][1]["id"] == T["id"]:
                        part[mine_] = band_at[other][2]
            for dr in ("forward", "backward"):
                grp = [b for b in lanes_at(O, eO) if b["direction"] == dr and b.get("lane_id")]
                tdirs = [part[b["lane_id"]]["direction"] for b in grp if b["lane_id"] in part]
                if not tdirs:
                    continue
                cO = sum(b["t"] for b in grp) / len(grp)
                # where the group lies 20 m past the node, across the trunk: its place in the order (all the lines meet at the node)
                s20 = lnO.length - min(20.0, lnO.length) if eO else min(20.0, lnO.length)
                x2, y2, nx2, ny2 = frame(lnO, s20)
                pos = (x2 + nx2 * cO - xT) * nxT + (y2 + ny2 * cO - yT) * nyT
                groups_.setdefault(max(set(tdirs), key=tdirs.count), []).append((O, eO, sg, grp, cO, sum(b["width"]["value"] for b in grp), pos))
        # each of the trunk's directions: the branches' lane groups side by side in their own order (left to right as they leave), centred
        # on the trunk's lanes of that direction; where they have more lanes than the trunk, the road widens at the fork
        branches = [(O, eO) for _, O, eO in ents if O["id"] != T["id"]]
        # a main road among the branches (it carries both directions: a9 at the main span's south end): the other branches' lanes run
        # beside its lanes of their direction, along its line, until the deck splits; then to their own line (Kaveh, 2026-10-12: a fork is
        # where the bridge gets its new branch, not where OSM splits the ways)
        two_ = lambda a_: len({b["direction"] for sc in a_["sections"] for b in sc["bands"] if b["type"] == "lane"}) == 2
        R = next(((lnx, ax_, ex) for lnx, ax_, ex in ents if ax_["id"] != T["id"] and two_(ax_)), None)
        if R is not None:
            lnR, Rax, eR = R
            sR20 = lnR.length - min(20.0, lnR.length) if eR else min(20.0, lnR.length)
            xR2, yR2, nxR2, nyR2 = frame(lnR, sR20)
            nxR0, nyR0 = frame(lnR, lnR.length if eR else 0.0)[2:]
            stack = {}          # (R's direction, side) -> width already stacked there
            for lnO, O, eO in ents:
                if O["id"] in (T["id"], Rax["id"]):
                    continue
                nxO, nyO = frame(lnO, lnO.length if eO else 0.0)[2:]
                sgR = 1 if nxO * nxR0 + nyO * nyR0 > 0 else -1
                sO20 = lnO.length - min(20.0, lnO.length) if eO else min(20.0, lnO.length)
                xO2, yO2 = frame(lnO, sO20)[:2]
                side = 1 if (xO2 - xR2) * nxR2 + (yO2 - yR2) * nyR2 > 0 else -1
                for dr in ("forward", "backward"):
                    grp = [b for b in lanes_at(O, eO) if b["direction"] == dr and b.get("lane_id")]
                    if not grp:
                        continue
                    dR = dr if sgR == 1 else ("backward" if dr == "forward" else "forward")
                    rg = [b for b in lanes_at(Rax, eR) if b["direction"] == dR]
                    if not rg:
                        continue
                    w_ = sum(b["width"]["value"] for b in grp)
                    used = stack.get((dR, side), 0.0)
                    edge_ = max(b["t"] + b["width"]["value"] / 2 for b in rg) if side > 0 else min(b["t"] - b["width"]["value"] / 2 for b in rg)
                    centre = edge_ + side * (used + w_ / 2)
                    stack[(dR, side)] = used + w_
                    cO = sum(b["t"] for b in grp) / len(grp)
                    # where the group fits on its own line: its middle as far from the main road's line as the main road's lanes on that
                    # side, half the group and a divider (OSM's two lines are already 9 m apart 20 m past the node at a1 -> a4 + a9)
                    need = abs(edge_) + w_ / 2 + DIVIDER_M
                    ds_ = 0.0
                    while ds_ < min(lnO.length, lnR.length, SPLIT_MAX_M):
                        xo, yo, nxo, nyo = frame(lnO, lnO.length - ds_ if eO else ds_)
                        xr_, yr_ = frame(lnR, lnR.length - ds_ if eR else ds_)[:2]
                        if math.hypot(xo + nxo * cO - xr_, yo + nyo * cO - yr_) >= need:
                            break
                        ds_ += 1.0
                    dl_ = centre - sgR * cO
                    # a branch lane SUMO connects to a lane of the trunk lies on it at the node (Kaveh, 2026-10-12: "7620567699850811447_2
                    # a5.0 to 8043974233675410214_3 a1.1", "_1 to _2"): beside the main road's lanes, a5's and a6's stood one lane out
                    xR0_, yR0_ = frame(lnR, lnR.length if eR else 0.0)[:2]
                    links_ = user_ if any(b["lane_id"] in user_lanes_ for b in grp) else conn_
                    on_ = [(xT + nxT * t_["t"] - xR0_) * nxR0 + (yT + nyT * t_["t"] - yR0_) * nyR0 - sgR * b["t"]
                           for b in grp for t_ in lanes_at(T, eT) if t_.get("lane_id")
                           and ((t_["lane_id"], b["lane_id"]) in links_ or (b["lane_id"], t_["lane_id"]) in links_)]
                    if on_:
                        dl_ = sum(on_) / len(on_)
                    for b in grp:
                        lane_join[b["lane_id"]] = ("R", O["id"], eO, Rax["id"], eR, sgR, dl_, ds_)
            continue
        for dT, gs in groups_.items():
            tl = [b for b in lanes_at(T, eT) if b["direction"] == dT]
            if not tl:
                continue
            cT = sum(b["t"] for b in tl) / len(tl)
            gs = sorted(gs, key=lambda g_: -g_[6])      # left first, across the trunk
            left = cT + sum(g_[5] for g_ in gs) / 2
            for O, eO, sg, grp, cO, w_, _ in gs:
                centre = left - w_ / 2
                left -= w_
                sh_ = sg * centre - cO
                # a branch lane SUMO connects to a trunk lane lies on it at the node (Kaveh, 2026-10-12: "7620567699850811447_2 a5.0 to
                # 8043974233675410214_3 a1.1", "_1 to _2"): side by side, a5's lanes stood 1.6 m out past a1's, and its strips with them
                on_ = [sg * t_["t"] - b["t"] for b in grp for t_ in tl
                       if (t_["lane_id"], b["lane_id"]) in conn_ or (b["lane_id"], t_["lane_id"]) in conn_]
                if on_:
                    sh_ = sum(on_) / len(on_)
                for b in grp:
                    lane_join[b["lane_id"]] = ("T", O["id"], eO, (xT, yT), (tx_, ty_), (nxT, nyT), sg, sh_, 0.0)

    for lid_ in list(lane_join):        # (an axis drawn as two lines and a curve starts with its lanes in place: fillets())
        jn_ = lane_join[lid_]
        if jn_[1] in P.get("_fitted", {}) and bool(jn_[2]) == bool(P["_fitted"][jn_[1]]):
            del lane_join[lid_]

    def edges(a, ln, si, bi, b):
        """The band's left and right edge offsets, functions of s (on a ground lane at a landing, moving to it before). (At a divided
        road's join, `along` moves the points.)"""
        return edges0(a, ln, si, bi, b)

    def edges0(a, ln, si, bi, b):
        """The band's left and right edge offsets, functions of s (on a ground lane at a landing, moving to it before)."""
        w = b["width"]["value"]
        L0, R0 = b["t"] + w / 2, b["t"] - w / 2
        tp = b.get("taper")
        if tp and tp.get("by") in by_id:
            # a lane that ends where another axis's lanes come in beside it (lane_ends "clear"): its outer edge on that axis's nearest
            # lane edge wherever it comes nearer than a lane, so the two meet with no gap (a10's third lane and a3 at the a9 node:
            # Kaveh, 2026-10-12, "they shouldn't have a gap")
            lnO, aO = by_id[tp["by"]]
            scO = aO["sections"][-1] if math.dist(lnO.coords[-1], ln.interpolate(tp["s0"]).coords[0]) < math.dist(lnO.coords[0], ln.interpolate(tp["s0"]).coords[0]) else aO["sections"][0]
            bO = [b2 for b2 in scO["bands"] if b2["type"] == "lane"]
            # (that axis's lanes as an area, carried a little past its line's ends: at the node its line starts beside it, and a line along
            # its lane edge found nothing there, a8's lane kept its width on a6's: Kaveh, 2026-10-12)
            lnO_x = extend(lnO, 6.0)
            hiO = max(b2["t"] + b2["width"]["value"] / 2 for b2 in bO)
            loO = min(b2["t"] - b2["width"]["value"] / 2 for b2 in bO)
            areaO = lnO_x.buffer(hiO, single_sided=True, cap_style="flat").union(lnO_x.buffer(loO, single_sided=True, cap_style="flat")) \
                if hiO > 0 > loO else lnO_x.buffer((hiO - loO) / 2, cap_style="flat")
            inner, out = tp["inner"], tp["out"]

            def squeezed(s, inner=inner, out=out, w=w, areaO=areaO):
                x, y, nx, ny = frame(ln, s)
                full = inner + out * w
                p_in = shapely.Point(x + nx * inner, y + ny * inner)
                if areaO.contains(p_in):
                    return inner
                hit = shapely.LineString([(p_in.x, p_in.y), (x + nx * full, y + ny * full)]).intersection(areaO)
                if hit.is_empty:
                    return full
                ts = [(q[0] - x) * nx + (q[1] - y) * ny for g_ in shapely.get_parts(hit) for q in getattr(g_, "coords", [])]
                return min(ts, key=lambda t_: abs(t_ - inner)) if ts else full
            return (squeezed, inner) if out > 0 else (inner, squeezed)
        if tp:          # an added lane widening from nothing (correct_sections): its inner edge stays, its outer one moves out
            def g(s, tp=tp):
                q = min(max((s - tp["s0"]) / ((tp["s1"] - tp["s0"]) or 1e-9), 0.0), 1.0)
                return 0.5 * (1 - math.cos(math.pi * q))
            inner, out = tp["inner"], tp["out"]
            moving = lambda s, inner=inner, out=out, w=w: inner + out * w * g(s)
            return (moving, inner) if out > 0 else (inner, moving)
        tg = land.get((a["id"], si, bi), [])
        if not tg:
            return L0, R0

        def blend(base, k):
            def f(s):
                v = base
                for e, on, sf, bl in tg:
                    d = (sf - s) if e else (s - sf)         # how far before the ground lane's full width
                    c = on(s) if d <= 0 else on(sf)
                    if c is None:
                        c = on(sf)
                    u = 1.0 if d <= 0 else 0.0 if d >= bl else 0.5 * (1 + math.cos(math.pi * d / bl))
                    # to the ground lane's edges, so the lanes go on with no step and no gap between them (a3's landing: a gap
                    # between its two lanes took a barrier, barrier @-71,-454, Kaveh, 2026-10-14); to its middle, keeping its own
                    # width, where the ground lane is narrower than a lane (on ramp a2 our islands left them 1.3 m)
                    v = v * (1 - u) + (c[k] if c[0] - c[1] >= LAND_LANE_M else (c[0] + c[1]) / 2 + (base - (L0 + R0) / 2)) * u
                return v
            return f
        return blend(L0, 0), blend(R0, 1)

    def edges_of(aid, end):
        """The left edge of the leftmost lane and the right edge of the rightmost at axis aid's landing (end: its last section)."""
        ln, a = by_id[aid]
        si = len(a["sections"]) - 1 if end else 0
        bs = [(bi, b) for bi, b in enumerate(a["sections"][si]["bands"]) if b["type"] == "lane"]
        if not bs or not any((aid, si, bi) in land for bi, _ in bs):
            return None
        val = lambda t, s_: t(s_) if callable(t) else t
        es = [edges(a, ln, si, bi, b) for bi, b in bs]
        return (lambda s_: max(val(e[0], s_) for e in es)), (lambda s_: min(val(e[1], s_) for e in es))
    S = surface(P, x0, y0, edges_of)       # the landings narrow to where their lanes meet the street's
    deck = S["deck"]


    def along(ln, a, s0, s1, t, lift, lid=None):
        """Points at offset t along the axis from s0 to s1, at the deck's height plus lift. On a carriageway that joins a single road
        (lane_join: a fork or a join), its last JOIN_BLEND_M blend in place to the single road's lane line carried straight back past the node: a sideways
        move along its own line, which bends to the node, kinked the lanes."""
        # (each metre on an axis drawn as strips: its strips are, and 4 m chords cut its bends, a wedge between the lanes and the guard)
        n = max(1, int((s1 - s0) // (1.0 if a["id"] in P["_rect_axes"] else STEP_M)))
        jn = lane_join.get(lid)
        jn = jn if jn and jn[1] == a["id"] else None
        out = []
        for i in range(n + 1):
            s = s0 + (s1 - s0) * i / n
            x, y, nx, ny = frame(ln, s)
            tv = t(s) if callable(t) else t
            px, py = x + nx * tv, y + ny * tv
            if jn and jn[0] == "T":
                _, _, e_, (xn, yn), (tx_, ty_), (nxT_, nyT_), sg, sh, ds = jn
                d = (ln.length - s) if e_ else s
                if d < ds + JOIN_BLEND_M:
                    # one road with the trunk up to where the branch really splits off (ds), then smoothly to its own place
                    u = 1.0 if d <= ds else 0.5 * (1 + math.cos(math.pi * (d - ds) / JOIN_BLEND_M))
                    off = sg * (tv + sh)
                    qx, qy = xn - tx_ * d + nxT_ * off, yn - ty_ * d + nyT_ * off
                    px, py = px * (1 - u) + qx * u, py * (1 - u) + qy * u
            elif jn:            # beside the main road's lanes, along its line, only until its own lanes fit there (ds)
                _, _, e_, rid, eR_, sgR, dl, ds = jn
                d = (ln.length - s) if e_ else s
                # then on its own line at once (RAMP_BLEND_M): a longer blend reshaped the Howe Street ramp (a6) for 40 m before the merge
                if d < ds + RAMP_BLEND_M:
                    # (from the node on, one gentle curve: held on the main road's line up to ds and turned after it, a5's lanes and
                    # footway made an S at the crosswalk; Kaveh, 2026-10-12: "wasn't smooth")
                    u = 0.5 * (1 + math.cos(math.pi * d / (ds + RAMP_BLEND_M)))
                    lnR_ = by_id[rid][0]
                    sR_ = min(max((lnR_.length - d) if eR_ else d, 0.0), lnR_.length)
                    xr, yr, nxr, nyr = frame(lnR_, sR_)
                    off = sgR * tv + dl
                    px, py = px * (1 - u) + (xr + nxr * off) * u, py * (1 - u) + (yr + nyr * off) * u
            out.append([round(px, 2), round(py, 2), round(z(px, py) + lift, 2)])     # on the deck's surface
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
    axis_of = {b["lane_id"]: a["id"] for _, a in axes for sc in a["sections"] for b in sc["bands"] if b.get("lane_id")}
    # no junction where a lane runs on along its own road: between two sections of one axis (one OSM way after the next, a12), or at a
    # divided road's join; there the lanes meet
    joins_ = [c for c in P.get("connectors", []) if (c["from"] in split_lanes and c["to"] in split_lanes)
              or (axis_of.get(c["from"]) is not None and axis_of.get(c["from"]) == axis_of.get(c["to"]))]
    short_ = [(c["from"], c["to"]) for c in P.get("connectors", []) if shapely.LineString(rel(c["line"])).length < JOIN_M or c in joins_]
    out_short, in_short = {a_ for a_, _ in short_}, {b_ for _, b_ in short_}

    def span(a, si, sec, b):
        """Where band b runs along the axis: SUMO's cut, but to the joint where it runs straight on into the next lane (they meet):
        every lane between two sections of one axis, and at a divided road's join; also a lane with no connector of its own (a
        corrected count) there."""
        f_, t_ = b.get("s_from", sec["s0"]), b.get("s_to", sec["s1"])
        if si > 0 or (a["id"], 0) in join_ends:
            f_ = sec["s0"]
        if si < len(a["sections"]) - 1 or (a["id"], 1) in join_ends:
            t_ = sec["s1"]
        fw = b.get("direction") != "backward"
        if b.get("lane_id") in out_short:
            t_, f_ = (sec["s1"], f_) if fw else (t_, sec["s0"])
        if b.get("lane_id") in in_short:
            f_, t_ = (sec["s0"], t_) if fw else (f_, sec["s1"])
        return f_, t_
    for ln, a in axes:
        height = f"{a['vertical']['source']}, {a['vertical']['method']}"
        for si, sec in enumerate(a["sections"]):
            for bi, b in enumerate(sec["bands"]):
                w = b["width"]["value"]
                props = {"id": f"{b.get('lane_id')} {a['id']}.{si}", "type": b["type"], "name": b.get("name") or P["name"], "osm": b.get("way"), "edge_id": b.get("link"),
                         "lane_id": b.get("lane_id"), "direction": b.get("direction"), "lane": b.get("lane"), "use": b.get("use"),
                         "turn": b.get("turn"), "width_m": w, "width_source": b["width"]["source"], "width_method": b["width"]["method"],
                         "axis": a["id"], "section_m": f"{sec['s0']}-{sec['s1']}", "height": height,
                         "source": ("urbanstyle" if b.get("source") == "urbanstyle" else "duckOSM GMNS (lanes from SUMO)") if b["type"] == "lane" else "osm",
                         "method": b["method"] if b.get("source") == "urbanstyle" else "mapped"}      # (a lane we add: ours)
                f_, t_ = span(a, si, sec, b)
                if t_ - f_ < 0.5:       # (inside a junction: a connector covers it)
                    continue
                le, re_ = edges(a, ln, si, bi, b)
                if land.get((a["id"], si, bi)):
                    props["landing"] = "moves to the street's lane over the last %.0f m" % LAND_BLEND_M
                lanes.append({"props": props, "l": along(ln, a, f_, t_, le, LIFT[b["type"] == "lane"], b.get("lane_id")),
                              "r": along(ln, a, f_, t_, re_, LIFT[b["type"] == "lane"], b.get("lane_id"))})
            # painted lines: across the lanes of the section, from left to right
            ls = [(bi, b) for bi, b in enumerate(sec["bands"]) if b["type"] == "lane"]
            paint = []
            f_ = min((span(a, si, sec, b)[0] for _, b in ls), default=sec["s0"])
            t_ = max((span(a, si, sec, b)[1] for _, b in ls), default=sec["s1"])
            val = lambda t, s: t(s) if callable(t) else t
            for i, (bi, b) in enumerate(ls):
                left, right = b["t"] + b["width"]["value"] / 2, b["t"] - b["width"]["value"] / 2
                le, re_ = edges(a, ln, si, bi, b)
                if i == 0 or abs(ls[i - 1][1]["t"] - ls[i - 1][1]["width"]["value"] / 2 - left) > TOUCH_M:
                    paint.append(("edge line", le, b.get("lane_id")))
                if i + 1 < len(ls) and abs(ls[i + 1][1]["t"] + ls[i + 1][1]["width"]["value"] / 2 - right) <= TOUCH_M:
                    nbi, nb = ls[i + 1]
                    nle, _ = edges(a, ln, si, nbi, nb)
                    paint.append(("centre line" if nb["direction"] != b["direction"] else "lane line",
                                  (lambda s, re_=re_, nle=nle: (val(re_, s) + val(nle, s)) / 2), b.get("lane_id")))
                else:
                    paint.append(("edge line", re_, b.get("lane_id")))
            if t_ - f_ >= 0.5:
                lines += [{"kind": k, "ref": a["id"], "pts": along(ln, a, f_, t_, t, LINE_LIFT_M, lid)} for k, t, lid in paint]
    crossings = []      # (a crossing OSM maps, marked or not, its fields): a crosswalk over the lanes it crosses, not a path
    leftover_ = set()   # (the keys of the strips of rectangles(): no barrier along the lanes' edge, they have their own)
    shared = []         # (a path for walking and cycling, its width, its fields): one lane, with a barrier towards the vehicle lanes
    road_ = shapely.union_all([shapely.Polygon([p[:2] for p in l["l"]] + [p[:2] for p in l["r"]][::-1]).buffer(0) for l in lanes]) if lanes else shapely.Polygon()
    def lid_for(a_, t):
        """The outermost lane on t's side of axis a_ that moves onto the main road's at a fork (lane_join), else None"""
        best = None
        for sc in a_["sections"]:
            for b in sc["bands"]:
                lj = lane_join.get(b.get("lane_id"))
                if b["type"] == "lane" and lj and lj[1] == a_["id"] and (b["t"] > 0) == (t > 0) and (best is None or abs(b["t"]) > abs(best["t"])):
                    best = b
        return best["lane_id"] if best else None

    def spec_pts(sp, which="t"):
        """A strip of rectangles() at its offset `which` (t or tb), drawn as the lanes are (along: the same points, the same move at a
        fork); tied to another road's strip at a node (join_t, join_tb): there it starts at that strip's end and moves to its own
        offset over RECT_BLEND_M"""
        ln_, a_ = by_id[sp["axis"]]
        t, s1_ = sp[which], min(sp["s1"], ln_.length)
        lid = lid_for(a_, t)
        j = sp.get("join_" + which)
        if j:
            jx, jy = j[0] - x0, j[1] - y0
            e0_, e1_ = ln_.interpolate(sp["s0"]), ln_.interpolate(s1_)
            s_end = sp["s0"] if math.hypot(e0_.x - jx, e0_.y - jy) <= math.hypot(e1_.x - jx, e1_.y - jy) else s1_
            # (where a point lands is affine in its offset: the offset that lands on the other strip's end)
            p0_, p1_ = along(ln_, a_, s_end, s_end, 0.0, 0.0, lid)[0], along(ln_, a_, s_end, s_end, 1.0, 0.0, lid)[0]
            dx_, dy_ = p1_[0] - p0_[0], p1_[1] - p0_[1]
            tj = ((jx - p0_[0]) * dx_ + (jy - p0_[1]) * dy_) / ((dx_ * dx_ + dy_ * dy_) or 1.0)
            if abs(tj - t) * math.hypot(dx_, dy_) > 0.3:        # (only where they do not meet already: a5 met a1, the tie kinked it)
                t0_ = t
                t = lambda s, tj=tj, t0_=t0_, s_end=s_end: tj + (t0_ - tj) * (lambda u: u * u * (3 - 2 * u))(min(abs(s - s_end) / RECT_BLEND_M, 1.0))
        # (beside a lane that moves to the street's lane it lands on, edges(): the same move, so the guard and the barrier stay beside
        # it; a3's ground end, Kaveh, 2026-10-12 "fix barrier ending issue barrier @-117,-325")
        t_num = sp[which]
        for si_ in {0, len(a_["sections"]) - 1}:
            near_ = [(abs(b_["t"] - t_num), bi_, b_) for bi_, b_ in enumerate(a_["sections"][si_]["bands"])
                     if b_["type"] == "lane" and (a_["id"], si_, bi_) in land]
            for _, bi_, b_ in sorted(near_, key=lambda x_: x_[0])[:1]:
                if True:
                    Lf_, Rf_ = edges(a_, ln_, si_, bi_, b_)
                    vv_ = lambda f_, s: f_(s) if callable(f_) else f_
                    base_l = t
                    t = lambda s, base_l=base_l, Lf_=Lf_, Rf_=Rf_, b_=b_, vv_=vv_: (base_l(s) if callable(base_l) else base_l) + \
                        (vv_(Lf_, s) + vv_(Rf_, s)) / 2 - b_["t"]
        sh_ = sp.get("shift_" + which)
        if sh_:         # (moved in past the end of a path inside it, rectangles(): a4's footway past its shared path's end)
            base_ = t
            t = lambda s, base_=base_, sh_=sh_: (base_(s) if callable(base_) else base_) + sum(
                d_ * (lambda u: u * u * (3 - 2 * u))(min(max((s - c0) / (c1 - c0), 0.0), 1.0)) for c0, c1, d_ in sh_)
        return [(p[0], p[1]) for p in along(ln_, a_, sp["s0"], s1_, t, 0.0, lid)]
    for f in P.get("paths", []):            # a strip of rectangles(): its points as the lanes', in the map's metres
        sp = f.get("_slot")
        if sp:
            pts = [(x + x0, y + y0) for x, y in spec_pts(sp)]
            if pts and math.dist(pts[-1], sp["first"]) < math.dist(pts[0], sp["first"]):
                pts = pts[::-1]
            f["line"] = sp["pre"] + [list(c) for c in pts] + sp["post"]
    # an OSM line on past a strip ("tie_paths"): its end nearest the strip's drawn end moved onto it, blending back onto OSM's over
    # PIECE_BLEND_M (footway w871038559 on a7 met a4's strip 1.2 m off: Kaveh, 2026-10-12, "only change the geometry of the footway",
    # "connect them as smooth as possible")
    from .corrections import bridge as bridge_corr_t
    tie_ = bridge_corr_t(P["name"]).get("tie_paths", [])
    for f in P.get("paths", []):
        if f["way"] not in tie_ or not f.get("_leftover") or len(f["line"]) < 2:
            continue
        ends_t = [c_[:2] for g_ in P["paths"] if g_["way"] == f["way"] and g_.get("_slot") for c_ in (g_["line"][0], g_["line"][-1])]
        pl_ = shapely.LineString([c_[:2] for c_ in f["line"]]).segmentize(1.0)
        c0, c1 = pl_.coords[0], pl_.coords[-1]
        dd = [(math.dist(c0, e_), 0, e_) for e_ in ends_t] + [(math.dist(c1, e_), 1, e_) for e_ in ends_t]
        if not dd:
            continue
        dmin, which, e_ = min(dd)
        if dmin >= PIECE_TIE_M:
            continue
        cc = c0 if which == 0 else c1
        dx_, dy_ = e_[0] - cc[0], e_[1] - cc[1]
        new_ = []
        for c_ in pl_.coords:
            s_c = pl_.project(shapely.Point(c_))
            u_ = min((s_c if which == 0 else pl_.length - s_c) / PIECE_BLEND_M, 1.0)
            w_ = 1 - u_ * u_ * (3 - 2 * u_)
            new_.append([c_[0] + dx_ * w_, c_[1] + dy_ * w_])
        f["line"] = new_
    for f in P.get("paths", []):            # each path on the deck, along its own line
        fl = shapely.LineString(rel(f["line"]))
        if fl.length < 0.5:
            continue
        fl = extend(fl, PATH_OVER_M)        # a little past its ends: two paths that meet end to end at an angle left a wedge between them
        props = {"id": f"{f['type']} {f['way']}", "type": f["type"], "name": f.get("name") or P["name"], "osm": f["way"], "width_m": f["width"]["value"],
                 "width_source": f["width"]["source"], "width_method": f["width"]["method"], "source": f["source"], "method": f["method"]}
        # a crossing is what OSM maps as one (footway=crossing, cycleway=crossing, a crossing tag): a crosswalk over the lanes it crosses;
        # any other path is drawn whole (a path beside the lanes is no crossing)
        if f.get("footway") == "crossing" or f.get("cycleway") == "crossing" or f.get("crossing"):
            marked = not (f.get("crossing") == "unmarked" or f.get("markings") == "no")
            crossings.append((fl, marked, {**props, "type": "crosswalk", "marked": marked}))
        elif f["type"] == "shared path":    # a path for walking and cycling: drawn below with its barrier
            if f.get("_slot"):
                leftover_.add(("s", len(shared)))
            shared.append((fl, f["width"]["value"], props))
        else:
            l_, r_ = ribbon(fl, f["width"]["value"], LIFT[False])
            if f.get("_slot"):
                leftover_.add(("l", len(lanes)))
            lanes.append({"props": props, "l": l_, "r": r_, "len": fl.length})
    for c in P.get("connectors", []):       # SUMO's path from lane to lane through a junction on the deck
        cl = shapely.LineString(rel(c["line"]))
        if cl.length < JOIN_M or c in joins_:
            continue
        l_, r_ = ribbon(cl, c["width"]["value"], LIFT[True])
        lanes.append({"props": {"type": "junction lane", "name": P["name"], "connector": c["id"], "from_lane": c["from"], "to_lane": c["to"],
                                "width_m": c["width"]["value"], "width_source": c["width"]["source"], "width_method": c["width"]["method"],
                                "source": c["source"], "method": c["method"]}, "l": l_, "r": r_})
    # the deck covers the lanes as they are drawn (at a fork they move from their bands' places: lanes hung off the deck, the guard
    # there stood on them and went, at the a4 split)
    lane_cover = shapely.union_all([shapely.Polygon([p[:2] for p in l["l"]] + [p[:2] for p in l["r"]][::-1]).buffer(0) for l in lanes
                                    if l["props"]["type"] == "lane"]) if lanes else shapely.Polygon()
    grown_ = shapely.make_valid(deck.union(lane_cover.buffer(DECK_MARGIN_M, join_style="mitre")))
    deck = max(shapely.get_parts(grown_), key=lambda g_: g_.area) if grown_.geom_type != "Polygon" else grown_
    deck = shapely.Polygon(deck.exterior, [r for r in deck.interiors if shapely.Polygon(r).area >= HOLE_MIN_M2])
    band_ = lambda sp: shapely.Polygon(spec_pts(sp) + spec_pts(sp, "tb")[::-1]).buffer(0)
    # where a crosswalk lands, the deck stays (no cut below): it joins it to the path it leads to, w871038550 to footway w871038551
    # (Kaveh, 2026-10-12: "connect them to walking and cycling part we have in that place")
    from .parts import CROSSWALK_M as cw_m_
    # (only at an end where a path goes on: the two crosswalks over a4 led to paths since left out, and their landings stuck out into
    # the gap as a hook in the guard, barrier @-388,-409: Kaveh, 2026-10-12)
    on_ = [shapely.LineString(rel(f_["line"])) for f_ in P.get("paths", []) if len(f_["line"]) > 1
           and not (f_.get("footway") == "crossing" or f_.get("cycleway") == "crossing" or f_.get("crossing"))]
    land_ends = [shapely.Point(e_[:2]) for fl_, _, _ in crossings for e_ in (fl_.coords[0], fl_.coords[-1])
                 if any(l_.distance(shapely.Point(e_[:2])) < 2.0 for l_ in on_)]
    landings_ = shapely.union_all([extend(fl_, 1.5).buffer(cw_m_ / 2, cap_style="flat").intersection(shapely.union_all(land_ends).buffer(cw_m_ + 1.5))
                                   for fl_, _, _ in crossings]) if crossings and land_ends else shapely.Polygon()
    # (only on a side with no path, where the deck is cut away: a6's east; beside a footway it kept a bump of OSM's outline, a5's south)
    landings_ = landings_.intersection(shapely.union_all([band_(sp) for sp in P["_bare_zones"]]).buffer(0.5)) if P["_bare_zones"] else shapely.Polygon()
    for rspecs_, zspecs_, zmask_, start_, past_ in P["_rects"]:      # an axis drawn as a rectangle: OSM's outline beside it cut away (rectangles())
        rect_ = shapely.union_all([band_(sp) for sp in rspecs_]) if rspecs_ else shapely.Polygon()
        zone_ = (shapely.union_all([band_(sp) for sp in zspecs_]) if zspecs_ else shapely.Polygon()).difference(shapely.affinity.translate(zmask_, -x0, -y0))
        zone_ = zone_.union(shapely.affinity.translate(past_, -x0, -y0).difference(rect_)).difference(landings_)
        grown_ = shapely.make_valid(deck.difference(zone_).union(rect_))
        # (and the thin teeth the cut left at the zone's corners: opened by 1 m there only)
        near_ = zone_.buffer(3.0)
        # where the rectangle starts (the fork) OSM's outline left notches against it: closed by RECT_SMOOTH_M there
        st_ = shapely.affinity.translate(start_, -x0, -y0)
        sm_ = grown_.buffer(RECT_SMOOTH_M, join_style="mitre").buffer(-RECT_SMOOTH_M, join_style="mitre")     # (closed: only adds)
        grown_ = shapely.make_valid(grown_.union(sm_.intersection(st_)))
        grown_ = shapely.make_valid(grown_.difference(near_).union(grown_.buffer(-1.0, join_style="mitre").buffer(1.0, join_style="mitre").intersection(near_)))
        deck = max(shapely.get_parts(grown_), key=lambda g_: g_.area) if grown_.geom_type != "Polygon" else grown_

    # past the guard of a strip axis's side with no path (a6's east): no deck, and no path below, but the other axes' lanes and strips
    rect_by_ = {}
    for rspecs_, *_ in P["_rects"]:
        for sp in rspecs_:
            rect_by_.setdefault(sp["axis"], []).append(band_(sp))
    bare_B = shapely.union_all([band_(sp).difference(shapely.union_all([g_ for k_, v_ in rect_by_.items() if k_ != sp["axis"] for g_ in v_]))
                                for sp in P["_bare_zones"]]).difference(lane_cover.buffer(BARRIER_M[1])) if P["_bare_zones"] else shapely.Polygon()
    if not bare_B.is_empty:
        bare_B = bare_B.difference(landings_)
        cut_b = shapely.make_valid(deck.difference(bare_B))
        cut_b = max(shapely.get_parts(cut_b), key=lambda g_: g_.area) if cut_b.geom_type != "Polygon" else cut_b
        # (a hole the cut makes inside the deck, between two axes, stays deck: the triangle between a6 and a8, Kaveh, 2026-10-12: "fill it
        # by cycle and walk part")
        had_ = [shapely.Polygon(r) for r in deck.interiors]
        deck = shapely.Polygon(cut_b.exterior, [r for r in cut_b.interiors if any(h_.contains(shapely.Polygon(r).representative_point()) for h_ in had_)])
    if P["_rects"]:      # (the hair-thin slits where two axes' strips meet at a node, closed: the guard ran into one, across a footway)
        closed_ = shapely.make_valid(deck.buffer(0.2, join_style="mitre").buffer(-0.2, join_style="mitre"))
        deck = max(shapely.get_parts(closed_), key=lambda g_: g_.area) if closed_.geom_type != "Polygon" else closed_
        # (and the small holes the cuts left, as at the gore tip between a5 and a8: the guard ran round one; the deck there is footway)
        deck = shapely.Polygon(deck.exterior, [r for r in deck.interiors if shapely.Polygon(r).area >= HOLE_MIN_M2])
    # the deck's top: the outline densified, cut by a STEP_M grid and triangulated inside it, so the top follows z() inside the deck too
    # (triangles from edge to edge across a sloped deck were up to 0.2 m off: a path 0.1 m above the deck sank into it in a saw-tooth)
    dense = deck.segmentize(STEP_M)
    tris = []
    for cell in ([] if flat_only else grid(dense, STEP_M)):
        for pc in shapely.get_parts(cell):
            if pc.geom_type == "Polygon" and pc.area > 1e-4:
                tris += [t for t in shapely.get_parts(shapely.constrained_delaunay_triangles(pc)) if t.representative_point().within(pc.buffer(0.01))]
    verts, index = [], {}

    def vid(x, y, zz):
        k = (round(x, 2), round(y, 2), round(zz, 2))
        if k not in index:
            index[k] = len(verts)
            verts.append(list(k))
        return index[k]
    top = [[vid(x, y, z(x, y)) for x, y in t.exterior.coords[:3]] for t in tris]
    # the deck's height where its own triangles are (what the page draws): every surface on the deck takes it, so none sinks into the
    # deck where its height curves (at a fork the two arms' heights blend; a buffer there sank 0.26 m into it)
    ttree = shapely.STRtree(tris)

    def zd(x, y):
        for k in ttree.query(shapely.Point(x, y)):
            (x1, y1, z1), (x2, y2, z2), (x3, y3, z3) = (verts[i] for i in top[k])
            dd = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
            if abs(dd) < 1e-9:
                continue
            a_ = ((y2 - y3) * (x - x3) + (x3 - x2) * (y - y3)) / dd
            b_ = ((y3 - y1) * (x - x3) + (x1 - x3) * (y - y3)) / dd
            if min(a_, b_, 1 - a_ - b_) >= -1e-6:
                return a_ * z1 + b_ * z2 + (1 - a_ - b_) * z3
        return z(x, y)
    # the deck's bottom never under the ground: near a landing the deck gets thinner and meets the street flush (the bridge is drawn over
    # the flat map, which has no depth: a slab under the ground showed as a block standing on it)
    # on a landing (OSM maps no bridge there: the road on fill between walls) the sides reach the ground
    fill = S["fill"]
    under = lambda x, y, zz, fill=fill: 0.0 if fill is not None and shapely.contains_xy(fill, x, y) else max(zz - DECK_M, 0.0)
    bottom = [[vid(x, y, under(x, y, z(x, y))) for x, y in t.exterior.coords[:3]][::-1] for t in tris]
    sides, rails = [], []
    for ring in [dense.exterior] + list(dense.interiors):
        c = list(ring.coords)
        for (ax, ay), (bx, by) in zip(c, c[1:]):
            za, zb = z(ax, ay), z(bx, by)
            a0, b0, a1, b1 = vid(ax, ay, under(ax, ay, za)), vid(bx, by, under(bx, by, zb)), vid(ax, ay, za), vid(bx, by, zb)
            sides += [[a0, b0, b1], [a0, b1, a1]]
            r0, r1 = vid(ax, ay, za + min(RAIL_M, za)), vid(bx, by, zb + min(RAIL_M, zb))     # a parapet ends where the deck lands
            rails += [[a1, b1, r1], [a1, r1, r0]]

    from .corrections import bridge as bridge_corr_tr
    trusses_ = bridge_corr_tr(P["name"]).get("truss", [])
    piers = []
    for q in P["piers"]:
        # none where a steel truss stands: the truss and its own piers replace these rule-made ones (Kaveh, 2026-10-12)
        if any(q["axis"] == tr_.get("axis") and tr_["s0"] <= q["s"] <= tr_["s1"] for tr_ in trusses_):
            continue
        ln, a = by_id[q["axis"]]
        x, y, nx, ny = frame(ln, q["s"])
        # across its own road only (its bands at s), inside the deck
        sec = next((sc for sc in a["sections"] if sc["s0"] - 0.01 <= q["s"] <= sc["s1"] + 0.01), None)
        bs = sec["bands"] if sec else []
        lo = min((b["t"] - b["width"]["value"] / 2 for b in bs), default=-4.0) + 0.5
        hi = max((b["t"] + b["width"]["value"] / 2 for b in bs), default=4.0) - 0.5
        if hi - lo <= COLUMN_M:     # (a road narrower than a column: one column on its middle; a one-lane road had none, a2 of
            mid_ = (lo + hi) / 2    # Boulevard du Larvotto; Kaveh, 2026-10-14)
            lo, hi = mid_ - COLUMN_M / 2 - 0.01, mid_ + COLUMN_M / 2 + 0.01
        cut = shapely.LineString([(x + nx * lo, y + ny * lo), (x + nx * hi, y + ny * hi)]).intersection(deck.buffer(0.5))
        h = _h(a["vertical"], q["s"]) - DECK_M
        for seg in shapely.get_parts(cut):
            if seg.geom_type == "LineString" and seg.length > COLUMN_M:
                # two columns, one under each edge of the road, with free space between them (one under a road too narrow for two)
                ends = [0.0, seg.length] if seg.length >= 2 * COLUMN_M + COLUMN_GAP_M else [seg.length / 2]
                for d in ends:
                    d0 = min(max(d - COLUMN_M / 2, 0.0), seg.length - COLUMN_M)
                    (ax, ay), (bx, by) = seg.interpolate(d0).coords[0], seg.interpolate(d0 + COLUMN_M).coords[0]
                    piers.append({"a": [round(ax, 2), round(ay, 2)], "b": [round(bx, 2), round(by, 2)], "t": COLUMN_M, "h": round(h, 2)})
    # the steel truss under a span, corrections/bridges.json "truss": [{axis, s0, s1, panel, spring_z, crown_gap}] (Kaveh, 2026-10-12: "it
    # has some steel parts with a special pattern between its legs"; the pattern from the city's photos, 2011-07-21 Vancouver 06, the
    # heights from the profile): on each side, under the deck's edge, a top chord under the deck, a bottom chord arched from its springing
    # points to crown_gap under the deck mid-span, a vertical at each panel point and a diagonal in each panel, in a V pattern
    truss = []

    def planes_(ln, s_):
        """The axis's frame at s_ and the two truss planes' t, TRUSS_IN_M in from the deck's edges (None off the deck)."""
        x, y, nx, ny = frame(ln, s_)
        cut_ = shapely.LineString([(x - nx * 40, y - ny * 40), (x + nx * 40, y + ny * 40)]).intersection(deck)
        ts_ = [(q[0] - x) * nx + (q[1] - y) * ny for g_ in shapely.get_parts(cut_) if g_.geom_type == "LineString" for q in g_.coords]
        return (x, y, nx, ny, {1: max(ts_) - TRUSS_IN_M, -1: min(ts_) + TRUSS_IN_M}) if ts_ else None
    for tr_ in trusses_:
        if tr_.get("axis") not in by_id:
            continue
        ln, a = by_id[tr_["axis"]]
        # a concrete pier under each springing point ("piers": [s]): one block across the deck from the ground to the springing
        # height, wider than the two truss planes (Kaveh, 2026-10-12; photos 2011-07-21 Vancouver 06, the orthophoto's shores)
        for s_ in tr_.get("piers", []):
            f_ = planes_(ln, s_)
            if f_:
                x, y, nx, ny, t_ = f_
                lo_, hi_ = t_[-1] - TRUSS_PIER_M[1], t_[1] + TRUSS_PIER_M[1]
                piers.append({"a": [round(x + nx * lo_, 2), round(y + ny * lo_, 2)], "b": [round(x + nx * hi_, 2), round(y + ny * hi_, 2)],
                              "t": TRUSS_PIER_M[0], "h": tr_["spring_z"]})
        s0_, s1_ = tr_["s0"], min(tr_["s1"], ln.length)
        n_ = max(2, round((s1_ - s0_) / tr_.get("panel", TRUSS_PANEL_M)))
        mid_, half_ = (s0_ + s1_) / 2, (s1_ - s0_) / 2
        z_top = lambda s_: _h(a["vertical"], s_) - DECK_M
        if "depth" in tr_:          # (a span of one depth, the approach truss over Granville Island)
            z_bot = lambda s_, d_=tr_["depth"]: z_top(s_) - d_
        else:                       # (the arched main span: from its springing points to crown_gap under the deck)
            z_crown = z_top(mid_) - tr_.get("crown_gap", TRUSS_CROWN_M)
            z_bot = lambda s_, zc=z_crown, zs=tr_["spring_z"]: zs + (zc - zs) * (1 - ((s_ - mid_) / half_) ** 2)
        sides_t = {1: [], -1: []}           # each side's panel points: (top, bottom), 1 m in from the deck's edge
        nrm_ = []                           # ... and the axis's normal there, the side planes' normal (n: a lattice member's plane)
        for k in range(n_ + 1):
            s_ = s0_ + (s1_ - s0_) * k / n_
            f_ = planes_(ln, s_)
            if not f_:
                continue
            x, y, nx, ny, t_ = f_
            nrm_.append([round(nx, 3), round(ny, 3)])
            for sd in (1, -1):
                px, py = x + nx * t_[sd], y + ny * t_[sd]
                sides_t[sd].append(([px, py, z_top(s_)], [px, py, z_bot(s_)]))
        # an anchor leg on each side, from a springing point up to the deck ("legs": [[s at its foot, z at its foot, s at the deck]])
        for s_f, z_f, s_d in tr_.get("legs", []):
            for sd in (1, -1):
                ends_ = []
                for s_, z_ in ((s_f, z_f), (s_d, None)):
                    f_ = planes_(ln, s_)
                    if f_:
                        x, y, nx, ny, t_ = f_
                        ends_.append([x + nx * t_[sd], y + ny * t_[sd], z_ if z_ is not None else z_top(s_)])
                if len(ends_) == 2:
                    truss.append({"a": ends_[0], "b": ends_[1], "w": TRUSS_M[0]})
        # a steel bent under the truss at each s of "bents": a lattice leg under each truss plane, from the ground up to the bottom
        # chord, and an X brace between the two legs, all in the plane across the axis (Kaveh, 2026-10-12; photos p1, p0)
        for s_ in tr_.get("bents", []):
            f_ = planes_(ln, s_)
            if not f_:
                continue
            x, y, nx, ny, t_ = f_
            n_x = [round(ny, 3), round(-nx, 3)]
            (l1b, l1t), (l2b, l2t) = [([x + nx * t_[sd], y + ny * t_[sd], 0.0], [x + nx * t_[sd], y + ny * t_[sd], z_bot(s_)]) for sd in (1, -1)]
            truss += [{"a": l1b, "b": l1t, "w": BENT_LEG_M, "n": n_x}, {"a": l2b, "b": l2t, "w": BENT_LEG_M, "n": n_x},
                      {"a": l1b, "b": l2t, "w": TRUSS_M[1], "n": n_x}, {"a": l2b, "b": l1t, "w": TRUSS_M[1], "n": n_x}]
        for pts_ in sides_t.values():
            for k, (top_, bot_) in enumerate(pts_):
                truss.append({"a": top_, "b": bot_, "w": TRUSS_M[1], "n": nrm_[k]})    # the vertical
                if k + 1 < len(pts_):
                    nt_, nb_ = pts_[k + 1]
                    truss.append({"a": top_, "b": nt_, "w": TRUSS_M[0]})               # the chords
                    truss.append({"a": bot_, "b": nb_, "w": TRUSS_M[0]})
                    truss.append({"a": bot_ if k % 2 == 0 else top_, "b": nt_ if k % 2 == 0 else nb_, "w": TRUSS_M[1], "n": nrm_[k]})  # the V
        # the bracing between the two sides (Kaveh, 2026-10-12; the photo under the deck, p3): a top lateral under the deck at each
        # panel point; at every other one a bottom strut and an X across, in the plane of the verticals
        for k, ((t1_, b1_), (t2_, b2_)) in enumerate(zip(sides_t[1], sides_t[-1])):
            n_x = [nrm_[k][1], -nrm_[k][0]]     # (their plane is across the axis: its normal is the axis's direction)
            truss.append({"a": t1_, "b": t2_, "w": TRUSS_M[1], "n": n_x})
            if k % 2 == 0:
                truss += [{"a": b1_, "b": b2_, "w": TRUSS_M[1], "n": n_x}, {"a": t1_, "b": b2_, "w": TRUSS_M[1], "n": n_x},
                          {"a": b1_, "b": t2_, "w": TRUSS_M[1], "n": n_x}]
    for q in truss:
        q["a"], q["b"] = [round(v_, 2) for v_ in q["a"]], [round(v_, 2) for v_ in q["b"]]
    # the surface the page draws: every item as a mesh on the deck, in the street's types (its colours, raised sidewalks, kerbs, lines)
    from .parts import CROSSWALK_M, KERB_TOP_M, LINE, RAISED, ZEBRA_BAR_M, ZEBRA_GAP_M
    surf = []

    ids_seen = {}

    # where an axis reaches the ground (a landing on a ground road), the surfaces come down flush with the street over the last
    # LAND_FLAT_M: before, the lanes ended 0.1-0.2 m above the ground road, a step that looked like a kerb (a2.1; Kaveh, 2026-10-13)
    # (on that road's own lanes only, by the distance along it from its ground end: a line 40 m each way also flattened a1 where ramp
    # a2 starts on the ground 7 m beside it, a V down to the ground in a1, Boulevard du Larvotto; Kaveh, 2026-10-14)
    land_ = []
    for ln_l, a_l in axes:
        for e_l in a_l.get("ends", []):
            if e_l["ground"]:
                sec_l = a_l["sections"][-1] if e_l["s"] > 0 else a_l["sections"][0]
                bs_l = sec_l["bands"] or [{"t": 0.0, "width": {"value": 6.0}}]
                lo_l = min(b_["t"] - b_["width"]["value"] / 2 for b_ in bs_l) - DECK_MARGIN_M - BARRIER_M[1]
                hi_l = max(b_["t"] + b_["width"]["value"] / 2 for b_ in bs_l) + DECK_MARGIN_M + BARRIER_M[1]
                land_.append((ln_l, e_l["s"], lo_l, hi_l))

    def landf(x, y):
        f_ = 1.0
        for ln_l, s_l, lo_l, hi_l in land_:
            sv = ln_l.project(shapely.Point(x, y))
            if abs(sv - s_l) >= LAND_FLAT_M:
                continue
            xq, yq, nxq, nyq = frame(ln_l, sv)
            if lo_l <= (x - xq) * nxq + (y - yq) * nyq <= hi_l:
                f_ = min(f_, abs(sv - s_l) / LAND_FLAT_M)
        return f_

    def mesh(poly, key, lift, props=None, raise_=0.0):
        """poly (model metres) as triangles on the deck's surface, lift above it (and raise_ more, with its sides down to the lift). A lane
        keeps POLE_CLEAR_M clear of each surveyed pole (`poles`)."""
        poly = shapely.make_valid(poly)
        if key.startswith("lane") and not pole_clear.is_empty:
            poly = poly.difference(pole_clear)
        for pg in shapely.get_parts(poly):
            if pg.geom_type != "Polygon" or pg.area < 0.05:
                continue
            dense = pg.segmentize(STEP_M / 2)
            tris = [] if flat_only else [t for c in grid(dense, STEP_M) for pc in shapely.get_parts(c) if pc.geom_type == "Polygon" and pc.area > 1e-4
                    for t in shapely.get_parts(shapely.constrained_delaunay_triangles(pc)) if t.representative_point().within(pc.buffer(0.01))]
            v, f, ix = [], [], {}

            def vi(x, y, zz):
                k = (round(x, 2), round(y, 2), round(zz, 2))
                if k not in ix:
                    ix[k] = len(v)
                    v.append(list(k))
                return ix[k]
            hz = lambda x, y: (zd(x, y) + lift) * landf(x, y) + raise_
            f += [[vi(x, y, hz(x, y)) for x, y in t.exterior.coords[:3]] for t in tris]
            if raise_ > 0:                      # its sides, as a kerb's face
                for ring in [dense.exterior] + list(dense.interiors):
                    c = list(ring.coords)
                    for (ax_, ay_), (bx_, by_) in zip(c, c[1:]):
                        a0, b0 = vi(ax_, ay_, (zd(ax_, ay_) + lift) * landf(ax_, ay_)), vi(bx_, by_, (zd(bx_, by_) + lift) * landf(bx_, by_))
                        a1, b1 = vi(ax_, ay_, hz(ax_, ay_)), vi(bx_, by_, hz(bx_, by_))
                        f += [[a0, b0, b1], [a0, b1, a1]]
            if f or flat_only:
                sf_ = {"key": key, "props": props, "v": v, "f": f, "poly": pg}
                if not key.startswith("mark") and key != "railing":
                    # an id to refer to it by (Kaveh, 2026-10-12): a lane its duckOSM lane id and section, a path its type and OSM way,
                    # anything else its type and place on the bridge (metres east, north of the bridge's middle)
                    c_ = pg.representative_point()
                    base_ = (props or {}).get("id") or f"{key.split()[0]} @{round(c_.x)},{round(c_.y)}"
                    if key.startswith("barrier") and not props:
                        # (a barrier's card: the road it guards, its height, what made it; it showed only its id: Kaveh, 2026-10-14)
                        near_l = min(((shapely.Polygon([q_[:2] for q_ in l_["l"]] + [q_[:2] for q_ in l_["r"]][::-1]).distance(pg), l_["props"])
                                      for l_ in lanes if l_["props"].get("type") == "lane" and len(l_["l"]) > 1), default=None, key=lambda r_: r_[0])
                        props = {"height_m": round(raise_, 2), "source": "urbanstyle", "method": "derived",
                                 "rule": {"barrier median": "between the two directions", "barrier": "along the deck's edge, or between the lanes and a path"}
                                 .get(key, key)}
                        if near_l and near_l[0] < 3.0:
                            props.update({"road": near_l[1].get("name"), "osm": near_l[1].get("osm"), "edge_id": near_l[1].get("edge_id"),
                                          "axis": near_l[1].get("axis"), "beside_lane": near_l[1].get("lane_id")})
                    n_ = ids_seen.get(base_, 0) + 1
                    ids_seen[base_] = n_
                    sf_["props"] = {**(props or {}), "type": (props or {}).get("type") or key, "id": base_ + (f" #{n_}" if n_ > 1 else "")}
                surf.append(sf_)

    def strip(line, width, key, lift, dash=None, raise_=0.0):
        """A painted line (or a kerb) along `line`, `width` wide; dash (on, off) metres."""
        pieces = [line]
        if dash:
            pieces, d = [], 0.0
            while d < line.length:
                pieces.append(substring(line, d, min(d + dash[0], line.length)))
                d += dash[0] + dash[1]
        for pc in pieces:
            if pc.length > 0.2:
                mesh(pc.buffer(width / 2, cap_style="flat"), key, lift, None, raise_)
    covered = shapely.Polygon()
    if parts:           # the street's own parts on the bridge, laid on the deck
        rp = lambda g: shapely.affinity.translate(g, -x0, -y0)
        for props, g in parts:
            ty = props.get("type")
            mesh(rp(g), f"{ty} {props.get('direction')}".strip() if ty == "lane" and props.get("direction") else ty, 0.03, props,
                 RAISED.get(ty, 0.0))
        covered = shapely.union_all([rp(g) for _, g in parts]).buffer(1.0)
        for ty, g in (marks or []):
            g = rp(g)
            if ty == "kerb":
                strip(g, 0.25, "mark kerb", 0.03, None, KERB_TOP_M)
            elif ty in LINE and ty not in ("arrow", "zebra"):
                strip(g, LINE[ty], f"mark {ty}", 0.06, (3.0, 6.0) if ty == "lane line" else None)
    for fl_, marked, props in crossings:    # a crosswalk: its piece over the lanes, zebra bars along the road unless OSM says unmarked
        for pc in shapely.get_parts(fl_.intersection(road_.buffer(0.5))):
            if pc.geom_type != "LineString" or pc.length <= 1.0 or not marked or \
                    (not covered.is_empty and pc.intersection(covered).length > 0.5 * pc.length):
                continue
            d_ = ZEBRA_BAR_M / 2
            while d_ < pc.length:
                c_ = pc.interpolate(d_)
                a_, b_ = pc.interpolate(max(d_ - 0.25, 0)), pc.interpolate(min(d_ + 0.25, pc.length))
                h_ = math.hypot(b_.x - a_.x, b_.y - a_.y) or 1
                tx, ty = (b_.x - a_.x) / h_, (b_.y - a_.y) / h_
                bar = shapely.LineString([(c_.x - ty * CROSSWALK_M / 2, c_.y + tx * CROSSWALK_M / 2), (c_.x + ty * CROSSWALK_M / 2, c_.y - tx * CROSSWALK_M / 2)])
                mesh(bar.buffer(ZEBRA_BAR_M / 2, cap_style="flat"), "mark zebra", LINE_LIFT_M, props)
                d_ += ZEBRA_BAR_M + ZEBRA_GAP_M
    # a path never lies on a vehicle lane: its width is chosen (urbanstyle), the lanes' are SUMO's; where they overlapped the two
    # surfaces fought and the lane showed through the path in teeth
    veh_ = shapely.union_all([shapely.Polygon([p[:2] for p in l["l"]] + [p[:2] for p in l["r"]][::-1]).buffer(0) for l in lanes
                              if l["props"]["type"] in ("lane", "junction lane")]) if lanes else shapely.Polygon()
    # the paths, the longest first: a path is not drawn where a longer one lies (OSM's short links and the ends that join another path
    # were a second surface at the same height: tails and flicker), nor in pieces narrower than PATH_MIN_M (slivers between two lanes)
    rib = lambda l_, r_: shapely.Polygon([q[:2] for q in l_] + [q[:2] for q in r_][::-1]).buffer(0)
    sep_bars = []       # (the barriers between a shared path and the lanes: no other part under them)
    path_draw = {}      # each path, drawn after the fill: (key, lift, fields, raise)
    order = [(pc.length, ("s", i), rib(*ribbon(pc, w, LIFT[False]))) for i, (pc, w, _) in enumerate(shared)] + \
            [(l["len"], ("l", i), rib(l["l"], l["r"])) for i, l in enumerate(lanes) if "len" in l]
    own, taken = {}, shapely.Polygon()
    from .corrections import bridge as bridge_corr_k
    keep_w = bridge_corr_k(P["name"]).get("keep_paths", [])
    for _, k, g in sorted(order, key=lambda t: -t[0]):
        # (a path corrections/bridges.json keeps, "keep_paths": drawn whole, the deck under it, though it runs off the deck or past a
        # side with no path: shared path w1417439065 and its link w1417439069 from the crosswalks over a4 to a10, Kaveh, 2026-10-12)
        osm_k = (shared[k[1]][2] if k[0] == "s" else lanes[k[1]]["props"]).get("osm")
        kept_k = osm_k in keep_w
        on_deck = g.intersection(deck)
        # nothing of the bridge outside its deck, and no path that lies mostly off it (it leads off the bridge: w986071145 and w986071146,
        # walkways into a building's door)
        g = (g if kept_k else on_deck if on_deck.area >= 0.5 * g.area else shapely.Polygon()).difference(veh_)
        piece = g.difference(taken)
        # (square corners: rounded ones left a V-shaped gap where two paths meet end to end, the end of a7)
        own[k] = piece.buffer(-PATH_MIN_M / 2, join_style="mitre").buffer(PATH_MIN_M / 2, join_style="mitre").intersection(piece)
        if kept_k:
            grown_ = shapely.make_valid(deck.union(own[k].buffer(BARRIER_M[1] + 0.05, join_style="mitre")))
            deck = max(shapely.get_parts(grown_), key=lambda g_: g_.area) if grown_.geom_type != "Polygon" else grown_
            # (the holes it closes, between it and the lanes beside it, are deck: a guard ran round one)
            deck = shapely.Polygon(deck.exterior, [r for r in deck.interiors if shapely.Polygon(r).area >= KEEP_HOLE_M2])
        else:
            own[k] = own[k].difference(bare_B)
        taken = taken.union(g)
    # the gore between two branches from one node, "gore_paths": [[axis, axis, way]], is that way's footway, one shape with its strip
    # from the node to the strip's start, the deck under it (a7 and a2: the zebra over a7 lands on it and it runs on into footway
    # w871038545; Kaveh, 2026-10-12, "footway part from a4 to a2 is not smooth")
    # (and, with no entry, the gore a strip path runs in from its strip to the crossing OSM maps at its end: the other branch is the road
    # that crossing goes over; footway w871038563 from a8 to the crosswalk over a5, Kaveh, 2026-10-14, "must continue till it reaches
    # the crosswalk")
    gore_l = [tuple(g_) for g_ in bridge_corr_k(P["name"]).get("gore_paths", [])]
    for ga_, x_c, way_ in P.get("_gore_auto", []):
        x_l = shapely.LineString(rel([c_[:2] for c_ in x_c]))
        gb_ = min((aid_ for aid_ in by_id if aid_ != ga_), key=lambda aid_: by_id[aid_][0].distance(x_l), default=None)
        if gb_ and by_id[gb_][0].distance(x_l) < 10.0 and not any(g_[2] == way_ for g_ in gore_l):
            gore_l.append((ga_, gb_, way_))
    for ga_, gb_, way_ in gore_l:
        k_g = next((k for k in own if (shared[k[1]][2] if k[0] == "s" else lanes[k[1]]["props"]).get("osm") == way_
                    and not own[k].is_empty), None)
        if k_g is None or ga_ not in by_id or gb_ not in by_id:
            continue
        la_, lb_ = by_id[ga_][0], by_id[gb_][0]
        node_ = min(((p_, q_) for p_ in (la_.coords[0], la_.coords[-1]) for q_ in (lb_.coords[0], lb_.coords[-1])),
                    key=lambda pq: math.dist(*pq))[0]
        base_ = shapely.union_all([shapely.Polygon([p[:2] for p in l["l"]] + [p[:2] for p in l["r"]][::-1]).buffer(0) for l in lanes
                                   if l["props"]["type"] == "lane" and l["props"].get("axis") in (ga_, gb_)] + [own[k_g]])
        reach_ = shapely.Point(node_).buffer(own[k_g].distance(shapely.Point(node_)) + GORE_CLOSE_M)
        gore_ = base_.buffer(GORE_CLOSE_M).buffer(-GORE_CLOSE_M).difference(base_).intersection(reach_).difference(veh_)
        # (not over another path: the gore of cycleway w1316244489 at its crossing took 92 m2 of footway w871038551, BR4)
        gore_ = gore_.difference(taken.difference(own[k_g])).buffer(-PATH_MIN_M / 2, join_style="mitre").buffer(PATH_MIN_M / 2, join_style="mitre")
        parts_ = [g_ for g_ in shapely.get_parts(gore_) if g_.geom_type == "Polygon" and g_.distance(own[k_g]) < 0.3]
        if parts_:
            own[k_g] = shapely.union_all([own[k_g]] + parts_).buffer(0.05, join_style="mitre").buffer(-0.05, join_style="mitre").difference(veh_)
            grown_ = shapely.make_valid(deck.union(shapely.union_all(parts_).buffer(BARRIER_M[1] + 0.05, join_style="mitre")))
            deck = max(shapely.get_parts(grown_), key=lambda g_: g_.area) if grown_.geom_type != "Polygon" else grown_
            taken = taken.union(own[k_g])
    for i, (pc, w, props) in enumerate(shared):     # one lane for walking and cycling, a concrete barrier towards the vehicle lanes
        if not covered.is_empty and pc.intersection(covered).length > 0.5 * pc.length:
            continue
        path_draw[("s", i)] = ("cycle lane", LIFT[False], props, 0.0)    # (drawn below, with what joins it; its barrier: as every path's)
    # the model's own items where the street has no part: lanes, connectors and paths in the street's types, its lines as paint
    jun = []
    # a lane that corrections/bridges.json adds from one lane into another ("join_lanes", id "from>to") gives way to the lane it leaves:
    # it opens as that lane moves away (both started on one lane, 93 m2 on each other: Kaveh, 2026-10-12, "need to fix overlapping")
    by_lane_ = {}
    for l in lanes:
        if l["props"]["type"] == "lane" and l["props"].get("lane_id"):
            by_lane_.setdefault(l["props"]["lane_id"], []).append(shapely.Polygon([p[:2] for p in l["l"]] + [p[:2] for p in l["r"]][::-1]).buffer(0))
    # where lanes of two roads overlap, the road with fewer lanes (the branch that joins) gives way, so no two lanes lie on each other
    # (a2 joining a1 at a shallow angle: 104 m2 of a1's lane under a2's, the colours fought; Kaveh, 2026-10-14, BR6)
    # (but never to a joining lane that continues it, "<its lane>><next>": the join is drawn so on purpose; cut, a4's lane left a hole
    # with a barrier round it where it joins a9 on the Granville Bridge, barrier @-151,-60; Kaveh, 2026-10-14)
    osm_deck = str(P["deck"]["outline"].get("source") or "").startswith("osm")
    ax_n, all_l = {}, []
    for l in lanes:
        if l["props"]["type"] == "lane":
            ax_ = l["props"].get("axis")
            all_l.append((ax_, str(l["props"].get("lane_id") or ""), shapely.Polygon([p[:2] for p in l["l"]] + [p[:2] for p in l["r"]][::-1]).buffer(0)))
            ax_n[ax_] = ax_n.get(ax_, 0) + 1
    rank_ = lambda k_: (-ax_n.get(k_, 0), str(k_))         # (more lanes first, then by id)
    for i, l in enumerate(lanes):
        pg = shapely.Polygon([p[:2] for p in l["l"]] + [p[:2] for p in l["r"]][::-1]).buffer(0)
        if l["props"]["type"] == "lane" and not osm_deck:     # (an OSM outline: its lanes as drawn, joins and all)
            me_ = str(l["props"].get("lane_id") or "")
            kin_ = lambda o_: bool(me_) and (o_.split(">")[0] == me_.split(">")[0] or me_ in o_.split(">") or o_ in me_.split(">"))
            over_ = [g_ for k_, o_, g_ in all_l if rank_(k_) < rank_(l["props"].get("axis")) and not kin_(o_) and g_.intersects(pg)]
            if over_:
                pg = pg.difference(shapely.union_all(over_))
                pg = shapely.union_all([g_ for g_ in shapely.get_parts(pg) if g_.geom_type == "Polygon" and g_.area > 0.5]) if not pg.is_empty else pg
        src_ = (l["props"].get("lane_id") or "").split(">")[0] if ">" in (l["props"].get("lane_id") or "") else None
        if src_ and src_ in by_lane_:
            pg = pg.difference(shapely.union_all(by_lane_[src_]))
            pg = shapely.union_all([g_ for g_ in shapely.get_parts(pg) if g_.geom_type == "Polygon" and g_.area > 0.5]) if not pg.is_empty else pg
        if pg.is_empty or (not covered.is_empty and pg.intersection(covered).area > 0.5 * pg.area):
            continue
        ty = l["props"]["type"]
        if ty == "junction lane":       # (drawn below, all of a junction's as one surface)
            jun.append(pg)
            continue
        if ty not in ("lane", "junction lane"):
            pg = own.get(("l", i), pg.difference(veh_))
        key = {"lane": f"lane {l['props'].get('direction') or ''}".strip(), "junction lane": "lane", "footway": "sidewalk",
               "cycleway": "cycle lane"}.get(ty, ty)
        if ("l", i) in own:     # a path: drawn below, as one polygon with the deck strips that join it
            path_draw[("l", i)] = (key, SURF_LIFT_M, l["props"], RAISED.get(key, 0.0))
            continue
        mesh(pg, key, SURF_LIFT_M, l["props"], RAISED.get(key, 0.0))
    # a junction on the deck: SUMO's paths through it as one surface, as the street's junction area (each path a 3.25 m ribbon overlapped
    # the others in a tangle); the moves are its guide lines and the lanes' turn arrows
    lanes_only = shapely.union_all([shapely.Polygon([p[:2] for p in l["l"]] + [p[:2] for p in l["r"]][::-1]).buffer(0) for l in lanes
                                    if l["props"]["type"] == "lane"])
    paths_only = shapely.union_all(list(own.values())) if own else shapely.Polygon()
    J_ = shapely.Polygon()
    if jun:
        # ... and the deck between them and the lanes' ends (JUNC_FILL_M): a lane with no connector of its own (a corrected count) left
        # bare deck inside the junction; not over a lane or a path
        J_ = shapely.union_all(jun)
        ends_l = [shapely.LineString([l["l"][k][:2], l["r"][k][:2]]) for l in lanes if l["props"]["type"] == "lane" for k in (0, -1)]
        hulls = []
        for Jc in shapely.get_parts(J_.buffer(0.5)):        # each junction: the hull of its paths and the lane ends that reach it
            near_e = [e_ for e_ in ends_l if e_.distance(Jc) < JUNC_FILL_M]
            hulls.append(shapely.union_all([Jc] + near_e).convex_hull)
        J_ = J_.union(deck.intersection(shapely.union_all(hulls)).difference(paths_only))
    # a barrier between every walking or cycling path and the lanes beside it (Kaveh, 2026-10-11), along the path's edge that faces
    # them, BARRIER_SEP_M wide and high; not where the path meets a junction (people cross there)
    near_l = lanes_only.buffer(PATH_BAR_NEAR_M)
    # (the cracks where two lane pieces meet shut first: the edge dipped into one and the barrier broke there, a5)
    lanes_shut = lanes_only.buffer(0.2, join_style="mitre").buffer(-0.2, join_style="mitre")
    # (a crosswalk's opening is the crosswalk itself, as wide as it and in line with its edges: a round 5 m opening left 3.8 m of lane
    # edge with no barrier beside a3, between barriers @-219,-185 and @-117,-325; Kaveh, 2026-10-13)
    x_open = shapely.union_all([extend(fl_, 2.0).buffer(CROSSWALK_M / 2, cap_style="flat") for fl_, _, _ in crossings]) \
        if crossings else shapely.Polygon()
    no_bar = J_.buffer(1.0).union(x_open)
    # (none on a lane: near a fork a branch's lanes move onto the main road's, and a barrier along the branch's own line crossed them)
    on_l = lanes_only.buffer(0.1)
    rbars = [p_ for b_ in P["_bars"] for pts_ in [spec_pts(b_)] if len(pts_) > 1
             for p_ in shapely.get_parts(shapely.LineString(pts_).difference(on_l)) if p_.geom_type == "LineString" and p_.length > BAR_MIN_M]
    for b_ in rbars:           # (an axis drawn as strips: its barriers are strips too, rectangles())
        strip(b_, BARRIER_SEP_M[0], "barrier", 0.0, None, BARRIER_SEP_M[1])
        sep_bars.append(b_.buffer(BARRIER_SEP_M[0] / 2, cap_style="flat"))
    no_bar = no_bar.union(shapely.union_all([b_.buffer(BARRIER_SEP_M[0] + 0.5, cap_style="flat") for b_ in rbars])) if rbars else no_bar
    def lane_bars(pg, near=PATH_BAR_NEAR_M, need_path=False):     # (need_path: only where the deck goes on past the lanes)
        """A barrier along the lanes' edge beside the polygon pg (a path, or the deck between it and the lanes), on its side, wherever pg is
        within `near` of the lanes along them"""
        # along the lanes' edge, not the path's: OSM's path line bends at its ends, the lanes keep straight (Kaveh, 2026-10-12, barrier
        # @436,537 "not straight and parallel to the road")
        edge = lanes_shut.boundary.intersection(pg.buffer(near + 0.05)).difference(no_bar)
        # only along the path: a segment whose distance to it changes is a lane's end (across the lanes at a joint, by a crosswalk)
        keep = []
        for ln_e in shapely.get_parts(shapely.line_merge(edge) if not edge.is_empty else edge):
            if ln_e.geom_type != "LineString":
                continue
            c_e = list(ln_e.segmentize(1.0).coords)
            for p_, q_ in zip(c_e, c_e[1:]):
                d0, d1 = pg.distance(shapely.Point(p_)), pg.distance(shapely.Point(q_))
                if abs(d0 - d1) < 0.3 * math.dist(p_, q_) + 0.05 and \
                        (not need_path or deck.boundary.distance(shapely.Point((p_[0] + q_[0]) / 2, (p_[1] + q_[1]) / 2)) > 0.8):
                    keep.append(shapely.LineString([p_, q_]))
        edge = shapely.line_merge(shapely.union_all(keep)) if keep else shapely.LineString()
        # one barrier over a jog where two lane pieces meet (the jog's own segments are dropped above: a5 had two 2-3 m gaps)
        pcs = [g_ for g_ in shapely.get_parts(edge) if g_.geom_type == "LineString"]
        joined = True
        while joined:
            joined = False
            for i_, u_ in enumerate(pcs):
                for j_, v_ in enumerate(pcs):
                    if i_ == j_:
                        continue
                    if math.dist(u_.coords[-1], v_.coords[0]) < BAR_JOIN_M:
                        pcs[i_] = shapely.LineString(list(u_.coords) + list(v_.coords))
                        pcs.pop(j_)
                        joined = True
                        break
                    if math.dist(u_.coords[-1], v_.coords[-1]) < BAR_JOIN_M:
                        pcs[i_] = shapely.LineString(list(u_.coords) + list(v_.coords)[::-1])
                        pcs.pop(j_)
                        joined = True
                        break
                if joined:
                    break
        for bp in pcs:
            if bp.geom_type == "LineString" and bp.length > BAR_MIN_M:
                # beside the lanes, on the path's side (half the width off the lanes' edge)
                off = bp.offset_curve(BARRIER_SEP_M[0] / 2)
                if off.is_empty or lanes_only.contains(off.interpolate(0.5, normalized=True)):
                    off = bp.offset_curve(-BARRIER_SEP_M[0] / 2)
                if off.geom_type != "LineString" or off.is_empty:
                    continue
                strip(off, BARRIER_SEP_M[0], "barrier", 0.0, None, BARRIER_SEP_M[1])
                sep_bars.append(off.buffer(BARRIER_SEP_M[0] / 2, cap_style="flat"))

    for k_own, g in own.items():
        if k_own in leftover_:      # (a strip has its own barrier: none along the lanes' edge too, at a gore tip; barrier @315,416)
            continue
        for pg in shapely.get_parts(g):
            if pg.geom_type != "Polygon" or pg.length / 2 < PATH_BAR_MIN_M:       # (a short link or a stub: no barrier round it)
                continue
            lane_bars(pg)
    # the rest of the deck, as the street's space is: every piece between the lanes, the paths and the guards is a part of the road. A
    # piece that touches a junction is junction; between two carriageways (two axes, or the two directions of one) a median; beside
    # lanes a shoulder; else (between a path and the guard) a buffer. Kaveh, 2026-10-11: "fill all space on the bridge like in street space"
    inner_deck = deck.buffer(-BARRIER_M[1])
    rest = inner_deck.difference(lanes_only).difference(J_).difference(paths_only).difference(shapely.union_all(sep_bars) if sep_bars else shapely.Polygon())
    groups = {}
    for l in lanes:
        if l["props"]["type"] == "lane":
            key_ = (l["props"].get("axis"), l["props"].get("direction"))
            groups[key_] = groups.get(key_, shapely.Polygon()).union(shapely.Polygon([p[:2] for p in l["l"]] + [p[:2] for p in l["r"]][::-1]).buffer(0))
    fill = {"footway": [], "median": [], "buffer": []}
    cut_fill, cut_out = [], []

    def join_(k_, g_, lanes_beside=True):
        """The deck piece g_ joins the path k_ only along OSM's line of it; past its ends the deck is footway, the bridge's own fill
        (140 m of deck between a4 and a9 joined shared path w1417439065, which OSM maps along a10 only: Kaveh, 2026-10-12, "the shape
        of the bridge must be as close as possible to OSM")"""
        if k_ in leftover_ and not lanes_beside:
            # (outside a strip, beside no lanes: OSM's old outline past its edge; cut away with the deck's rim past it, so the guard
            # stands at the strip's edge: footway w538616396 #2 a strip like the others, Kaveh, 2026-10-12)
            cut_out.append(g_)
            return
        if k_ not in leftover_:
            if k_[0] == "s":
                ln_k = shared[k_[1]][0]
            else:
                l_k = lanes[k_[1]]
                ln_k = shapely.LineString([((p_[0] + q_[0]) / 2, (p_[1] + q_[1]) / 2) for p_, q_ in zip(l_k["l"], l_k["r"])])
            span_ = ln_k.buffer(40.0, cap_style="flat")
            past_ = g_.difference(span_)
            if past_.area > 1.0:
                fill["footway"].extend(q_ for q_ in shapely.get_parts(past_) if q_.geom_type == "Polygon")
                g_ = g_.intersection(span_)
                if g_.is_empty or g_.area < 0.05:
                    return
        path_extra.setdefault(k_, []).append(g_)
    path_extra = {}     # path key -> the pieces between it and another path it takes
    shift_z = shapely.union_all([band_(sp) for sp in P.get("_shift_zones", [])]) if P.get("_shift_zones") else shapely.Polygon()
    for g in shapely.get_parts(rest):
        if g.geom_type != "Polygon" or g.area < 0.05 or g.buffer(-0.05).is_empty:     # (a hairline between two lanes: no part)
            continue
        if not shift_z.is_empty and g.intersection(shift_z).area > 0.5 * g.area:
            # (freed where a path inside ended and the paths outside move in, rectangles(): the path it shares the longest edge with;
            # it was cut as old outline and left a hole, a4's footway w871038559 past shared path w1383685288)
            by_edge = [(g.boundary.intersection(P_.buffer(0.3)).length, k_) for k_, P_ in own.items() if not P_.is_empty and P_.distance(g) < 0.3]
            if by_edge:
                path_extra.setdefault(max(by_edge)[1], []).append(g)
                continue
        # (the gore where two roads meet in the air, surface(): part of their junction, not a median; median @-3,121 where a2 joins a1,
        # Boulevard du Larvotto; Kaveh, 2026-10-14)
        if not S["gores"].is_empty and g.intersection(S["gores"]).area > 0.5:
            J_ = J_.union(g.intersection(S["gores"]))
            g = max([x_ for x_ in shapely.get_parts(shapely.make_valid(g.difference(S["gores"]))) if x_.geom_type == "Polygon"] or [shapely.Polygon()],
                    key=lambda x_: x_.area)
            if g.is_empty or g.area < 0.5:
                continue
        if not J_.is_empty and g.distance(J_) < 0.3:
            J_ = J_.union(g)
            continue
        touch = [k_ for k_, G in groups.items() if G.distance(g) < 0.3]
        near_p = [k_ for k_, P_ in own.items() if not P_.is_empty and P_.distance(g) < 0.3
                  and g.boundary.intersection(P_.buffer(0.3)).length >= JOIN_EDGE_M]      # (along it, not at a corner)
        if not touch and len(near_p) >= 2:
            # between two paths only (a cycle path and a sidewalk): no strip of its own, the gap to the bigger path, so the two meet as
            # one strip (Kaveh, 2026-10-12); beside strips only, outside them, it is OSM's old outline (cut: footway w871038559 at a4)
            join_(max(near_p, key=lambda k2: own[k2].area), g, not all(k2 in leftover_ for k2 in near_p))     # (to the bigger: a smooth edge)
            continue
        # between two roads at different heights it is no deck: each keeps its own edge and guard, nothing between them (Boulevard du
        # Larvotto: ramp a2 beside a1, 0 m against 8 m, got a median and a median barrier stretched between them; Kaveh, 2026-10-14)
        # (decided every 2 m along it, not once for the whole piece: the gap between a1 and a2 runs from a2's ground start, 0 m
        # against 8 m, to the junction, where both are 2.7 m; cut whole, it left a hole ringed with barriers)
        ax_ids = sorted({aid_ for aid_, _ in touch})
        if len(ax_ids) >= 2 and not osm_deck:      # (an OSM outline decides its deck: Granville's ramps share one at two heights)
            ln_g = by_id[ax_ids[0]][0]
            zone_ = []
            for k_ in range(int(ln_g.length // 2.0) + 1):
                q_ = ln_g.interpolate(k_ * 2.0)
                if g.distance(q_) > 20.0:
                    continue
                hs_ = [_h(by_id[i_][1]["vertical"], by_id[i_][0].project(q_)) for i_ in ax_ids]
                if max(hs_) - min(hs_) > 3 * MEET_M:
                    xq, yq, nxq, nyq = frame(ln_g, k_ * 2.0)
                    zone_.append(shapely.LineString([(xq - nxq * 25, yq - nyq * 25), (xq + nxq * 25, yq + nyq * 25)]).buffer(1.05, cap_style="flat"))
            if zone_:
                cut_g = g.intersection(shapely.union_all(zone_))
                if not cut_g.is_empty:
                    cut_fill.append(cut_g)
                    g = g.difference(shapely.union_all(zone_))
                    g = max(shapely.get_parts(g), key=lambda x_: x_.area) if g.geom_type != "Polygon" and not g.is_empty else g
                    if g.is_empty or g.area < 0.05:
                        continue
                    c_ = g.representative_point()
        # a median only between two opposite directions (their travel on the map, at the piece)
        c_ = g.representative_point()
        trav = []
        for aid_, dr_ in touch:
            ln_t = by_id[aid_][0]
            s_t = ln_t.project(c_)
            p0, p1 = ln_t.interpolate(max(s_t - 1, 0)), ln_t.interpolate(min(s_t + 1, ln_t.length))
            sgn_ = 1 if dr_ != "backward" else -1
            trav.append(((p1.x - p0.x) * sgn_, (p1.y - p0.y) * sgn_))
        opposite = any(u_[0] * v_[0] + u_[1] * v_[1] < 0 for i_, u_ in enumerate(trav) for v_ in trav[i_ + 1:])
        bare_ = False       # (beside a strip axis's side with no path: OSM's old outline, cut away, whatever it touches; the gore deck
        for aid_, _ in touch:   # beside a6's outer lane, drawn as a8's footway: Kaveh, 2026-10-12, "gap between ... a6.3 and barrier")
            if aid_ in P["_rect_axes"]:
                ln_b = by_id[aid_][0]
                c_b = g.representative_point()
                xb_, yb_, nxb_, nyb_ = frame(ln_b, ln_b.project(c_b))
                if (aid_, 1 if (c_b.x - xb_) * nxb_ + (c_b.y - yb_) * nyb_ > 0 else -1) in P["_bare"]:
                    bare_ = True
        if bare_ and not near_p:        # (touching a footway it is that footway: the gore tip at a5 joins a8's w871038563)
            cut_fill.append(g)
            continue
        if touch and (near_p or not opposite):
            # the deck beside the lanes that is footway or joins a path: the barrier between them along the lanes' edge too (a2's east
            # side, joined into shared path w1417439065; Kaveh, 2026-10-12: "separate driving roads from footway and cycling by barrier")
            n_bars = len(sep_bars)
            lane_bars(g, 0.35, need_path=True)     # (not where the deck's edge, and its guard, is right there: a5's north side)
            if len(sep_bars) > n_bars:
                g = g.difference(shapely.union_all(sep_bars[n_bars:]))
                if g.is_empty or g.area < 0.05:
                    continue
                g = max(shapely.get_parts(g), key=lambda x_: x_.area) if g.geom_type != "Polygon" else g
        if near_p and (opposite or not touch):
            # beside a path it is that path, even where it touches both directions: at a fork, between a1's lanes and a5's sidewalk
            # (Kaveh, 2026-10-12: "remove median @295,372")
            join_(max(near_p, key=lambda k2: own[k2].area), g, bool(touch))
            continue
        if not opposite and touch:
            # no shoulder on the bridge: the deck beside the lanes is footway (Kaveh, 2026-10-12, shoulder @337,534); next to a path it is
            # that path, one strip
            if near_p:
                join_(max(near_p, key=lambda k2: own[k2].area), g)
            elif any(k_[0] in P["_rect_axes"] for k_ in touch):
                cut_fill.append(g)      # (beside an axis drawn as strips, with no path there: OSM's old outline, cut away; sidewalk @319,439)
            else:
                fill["footway"].append(g)
            continue
        fill["median" if opposite else "buffer"].append(g)
    if cut_out:
        keep_ = shapely.union_all([lanes_only] + [own[k2] for k2 in leftover_ if k2 in own]).buffer(BARRIER_M[1] + 0.02, join_style="mitre")
        cut_o = shapely.union_all(cut_out).buffer(BARRIER_M[1] + 0.1, join_style="mitre").difference(keep_)
        deck_ = shapely.make_valid(deck.difference(cut_o))
        deck = max(shapely.get_parts(deck_), key=lambda g_: g_.area) if deck_.geom_type != "Polygon" else deck_
    if cut_fill:        # (the guard's width beside the lanes stays; and where a crosswalk lands)
        cut_ = shapely.union_all(cut_fill)
        # (and the deck's rim beside it, out to the edge: the pieces stop at the inner deck, and the thin rim left past them made a hole
        # ringed with guards, a triangle beside a2.0; Kaveh, 2026-10-14, "triangle barrier issue barrier @-387,-395")
        rim_z = deck.difference(deck.buffer(-BARRIER_M[1] - 0.05, join_style="mitre"))
        cut_ = cut_.union(cut_.buffer(BARRIER_M[1] + 0.1, join_style="mitre").intersection(rim_z))
        cut_ = cut_.difference(lanes_only.buffer(BARRIER_M[1] + 0.05, join_style="mitre")).difference(landings_)
        deck_ = shapely.make_valid(deck.difference(cut_))
        deck = max(shapely.get_parts(deck_), key=lambda g_: g_.area) if deck_.geom_type != "Polygon" else deck_
    what = {"footway": "the deck between the lanes and the guard", "median": "the deck between two carriageways",
            "buffer": "the deck between a path and the guard"}
    # a guardrail in a median only where a source says so (corrections/bridges.json, checked by hand: Granville); else the median is deck
    # with its painted lines (Boulevard du Larvotto got a 91 m one where a2 joins a1, barrier @-11,94; Kaveh, 2026-10-14)
    for g in (fill["median"] if bridge_corr_(P["name"]).get("median") == "barrier" else []):
        G_ = next((G for G in groups.values() if G.distance(g) < 0.3), None)
        if G_ is None:
            continue
        side = shapely.line_merge(g.exterior.intersection(G_.buffer(0.3)))
        for bp in shapely.get_parts(side):
            if bp.geom_type == "LineString" and bp.length > 2.0:
                mesh(bp.buffer(BARRIER_SEP_M[0] + 0.05, cap_style="flat").intersection(g), "barrier median", SURF_LIFT_M, None, BARRIER_M[0])
    seps_ = shapely.union_all(sep_bars) if sep_bars else shapely.Polygon()      # (a path stops at its barrier)
    # the kept paths (keep_paths) drawn as one shape, with the small deck bits beside them: shared path w1417439065, its link w1417439069
    # and what lies between them in the triangle between a4 and a9 (Kaveh, 2026-10-12: "not with many strip pieces, one shape")
    kept_keys = [k_ for k_ in path_draw if path_draw[k_][2].get("osm") in keep_w]
    merged_ = None
    if kept_keys:
        main_ = max(kept_keys, key=lambda k_: own[k_].area)
        merged_ = shapely.union_all([own[k_] for k_ in kept_keys] + [g_ for k_ in kept_keys for g_ in path_extra.get(k_, [])])
        for kind in ("footway", "buffer"):
            near_f = [g_ for g_ in fill[kind] if g_.area < KEEP_BIT_M2 and g_.distance(merged_) < 0.3]
            fill[kind] = [g_ for g_ in fill[kind] if not any(g_ is h_ for h_ in near_f)]
            merged_ = shapely.union_all([merged_] + near_f)
        merged_ = merged_.buffer(0.5, join_style="mitre").buffer(-0.5, join_style="mitre").difference(lanes_only)
    for k_, (key_, lift_, pr_, raise__) in path_draw.items():     # each path once: its own polygon and the strips that join it, one shape
        if merged_ is not None and k_ in kept_keys:
            if k_ != main_:
                continue
            shape_ = merged_.difference(seps_)
            shape_ = max(shapely.get_parts(shape_), key=lambda q_: q_.area) if shape_.geom_type != "Polygon" else shape_
            mesh(shape_, key_, lift_, pr_, raise__)
            continue
        shape_ = shapely.union_all([own[k_]] + path_extra.get(k_, [])).buffer(0.01).buffer(-0.01).difference(seps_)
        # (no hairlines: slivers thinner than 0.2 m between two roads' lanes showed as a green line between a11 and a12, Kaveh, 2026-10-12)
        shape_ = shape_.buffer(-0.1, join_style="mitre").buffer(0.1, join_style="mitre").intersection(shape_)
        # (a piece under 3 m² is left out: what showed of a leftover OSM line beside a strip at a gore, footway w871038551 #2)
        shape_ = shapely.union_all([q_ for q_ in shapely.get_parts(shape_) if q_.area >= PATH_PIECE_MIN_M2]) if not shape_.is_empty else shape_
        mesh(shape_, key_, lift_, pr_, raise__)
    for kind, gs in fill.items():
        if gs:
            key_ = "sidewalk" if kind == "footway" else kind
            mesh(shapely.union_all(gs).difference(shapely.union_all(sep_bars) if sep_bars else shapely.Polygon()), key_, SURF_LIFT_M if kind != "footway" else LIFT[False], {"type": kind, "name": P["name"], "source": "urbanstyle",
                                                                  "method": f"derived: {what[kind]}"}, RAISED.get(key_, 0.0))
    if not J_.is_empty:
        # whole, just under the lanes (cut out of it, its edges left light slivers between it and them; the split between two lanes
        # showed as a long bare strip); its outline smoothed (round corners), as the street's junction area
        filled = shapely.union_all([g for gs in fill.values() for g in gs]) if any(fill.values()) else shapely.Polygon()
        J_ = J_.buffer(JUNC_SMOOTH_M).buffer(-2 * JUNC_SMOOTH_M).buffer(JUNC_SMOOTH_M).intersection(inner_deck).difference(paths_only).difference(filled)
        mesh(J_, "junction area", SURF_LIFT_M - 0.01,
             {"type": "junction area", "name": P["name"], "source": "sumo, via duckOSM GMNS lane_connector", "method": "derived"})
    from .corrections import bridge as bridge_corr
    median = bridge_corr(P["name"]).get("median") == "barrier"     # a guardrail between the two directions (corrections/bridges.json)
    # the guardrail between the two directions of a divided road built on one line (pair): on that line, as a10's on its centre line
    # (Kaveh, 2026-10-12: "the middle barrier for dividing the directions is missing there")
    if median:
        for ml_ in P.get("_median_lines", []):
            strip(shapely.LineString(rel(ml_)), BARRIER_SEP_M[0], "barrier median", 0.0, None, BARRIER_M[0])
    # (no painted line through a lane's inside: the edge line of the lane joining a4's lane _1 to a9 lay on 4747140365369135178_1;
    # Kaveh, 2026-10-12, "there is a line on lane 4747140365369135178_1")
    lane_in_ = shapely.union_all([shapely.Polygon([p[:2] for p in l["l"]] + [p[:2] for p in l["r"]][::-1]).buffer(0).buffer(-0.4)
                                  for l in lanes if l["props"]["type"] == "lane"])
    for ln_ in lines:
        g = shapely.LineString([p[:2] for p in ln_["pts"]])
        if g.length < 0.5 or (not covered.is_empty and g.intersection(covered).length > 0.5 * g.length):
            continue
        g = g.difference(lane_in_)
        g = shapely.line_merge(g) if g.geom_type == "MultiLineString" else g
        if g.is_empty or g.length < 0.5:
            continue
        for g in [g_ for g_ in shapely.get_parts(g) if g_.geom_type == "LineString" and g_.length >= 0.5]:
            if median and ln_["kind"] == "centre line":      # (its own key: the checks' guard is the deck's edge)
                strip(g, BARRIER_SEP_M[0], "barrier median", 0.0, None, BARRIER_M[0])
                continue
            strip(g, LINE.get(ln_["kind"], 0.12), f"mark {ln_['kind']}", PAINT_LIFT_M, (3.0, 6.0) if ln_["kind"] == "lane line" else None)
    # guide lines through the junctions on the deck (SUMO's moves: the profile's connectors), as the street's; an arrow in every lane,
    # one each ARROW_EVERY_M (one in the middle of a shorter lane) and, before a junction, one with a head for each way SUMO lets it go
    from .network import arrow_shape
    from .parts import ARROW_M
    cons = [(c, shapely.LineString(rel(c["line"]))) for c in P.get("connectors", []) if c not in joins_]
    for _, cl in cons:
        if cl.length >= JOIN_M:
            strip(cl, LINE["guide line"], "mark guide line", LINE_LIFT_M, (1.0, 2.0))
    for l in lanes:
        pr = l["props"]
        if pr["type"] != "lane":
            continue
        ctr = shapely.LineString([((p[0] + q[0]) / 2, (p[1] + q[1]) / 2) for p, q in zip(l["l"], l["r"])])
        if ctr.length < ARROW_M + 2.0:
            continue
        out_ = [cl for c, cl in cons if c["from"] == pr["lane_id"] and cl.length >= 0.5]
        in_ = [cl for c, cl in cons if c["to"] == pr["lane_id"] and cl.length >= 0.5]
        near = lambda q, ps: min(shapely.Point(q).distance(shapely.Point(p_)) for p_ in ps)
        if out_:            # the way the lane runs: towards the moves that leave it, away from those that reach it, else its direction
            back = near(ctr.coords[0], [cl.coords[0] for cl in out_]) < near(ctr.coords[-1], [cl.coords[0] for cl in out_])
        elif in_:
            back = near(ctr.coords[-1], [cl.coords[-1] for cl in in_]) < near(ctr.coords[0], [cl.coords[-1] for cl in in_])
        else:
            back = pr.get("direction") == "backward"
        if back:
            ctr = ctr.reverse()
        L = ctr.length

        def head(line, d):
            a_, b_ = line.interpolate(max(d - 1.0, 0.0)), line.interpolate(min(d + 1.0, line.length))
            h_ = math.hypot(b_.x - a_.x, b_.y - a_.y) or 1
            return (b_.x - a_.x) / h_, (b_.y - a_.y) / h_
        tips = []
        if out_:
            hx, hy = head(ctr, L)
            ways = set()
            for cl in out_:
                cx, cy = head(cl, cl.length)
                ang = math.degrees(math.atan2(hx * cy - hy * cx, hx * cx + hy * cy))
                ways.add("left" if ang > 30 else "right" if ang < -30 else "straight")
            tips.append((L - 2.0, ways))
        n = max(1, int(L // ARROW_EVERY_M))
        for k in range(n):
            d = L * (k + 0.5) / n + ARROW_M / 2
            if not out_ or d < L - 2.0 - 2 * ARROW_M:
                tips.append((d, {"straight"}))
        # (a lane that gives way to another, a joining lane "from>to": no arrow where it still lies on the lane it leaves)
        src_l = shapely.union_all(by_lane_.get(pr["lane_id"].split(">")[0], [])) if ">" in (pr.get("lane_id") or "") else None
        for d, ways in tips:
            if ARROW_M <= d <= L and (src_l is None or not src_l.buffer(-0.3).contains(ctr.interpolate(d))):
                tp = ctr.interpolate(d)
                for pc in shapely.get_parts(arrow_shape((tp.x, tp.y), head(ctr, d), ways)):
                    strip(pc, LINE["arrow"], "mark arrow", LINE_LIFT_M)
    # the guards on both sides of the deck: a concrete barrier and a metal railing on posts; none across a road where it leaves the bridge
    # (every edge of the bridge has its guard: the deck reaches a guard's width past every lane, a lane at the deck's edge had none;
    # Kaveh, 2026-10-12, "all boundary of the bridge must have barrier")
    grow_ = lanes_only.buffer(BARRIER_M[1] + 0.05, join_style="mitre")
    for ln_e, a_e in axes:          # (not past a road's end where it reaches the ground: a path there and a barrier across a2's end)
        for e_ in a_e.get("ends", []):
            if not e_.get("ground"):
                continue
            x_, y_, nx_, ny_ = frame(ln_e, e_["s"])
            ox_, oy_ = (ny_, -nx_) if e_["s"] > ln_e.length / 2 else (-ny_, nx_)      # (out of the end)
            grow_ = grow_.difference(shapely.Polygon([(x_ + nx_ * 40, y_ + ny_ * 40), (x_ - nx_ * 40, y_ - ny_ * 40),
                                                      (x_ - nx_ * 40 + ox_ * 20, y_ - ny_ * 40 + oy_ * 20),
                                                      (x_ + nx_ * 40 + ox_ * 20, y_ + ny_ * 40 + oy_ * 20)]))
    grown_g = shapely.make_valid(deck.union(grow_))
    deck = max(shapely.get_parts(grown_g), key=lambda g_: g_.area) if grown_g.geom_type != "Polygon" else grown_g
    ends_ = []
    # (not at every lane's end: a section's lanes end where the bridge meets its landing too, and the guard had a gap there)
    # where an axis reaches the ground, the deck's whole end edge (the lanes' ends left guard pieces between the lanes and the paths):
    # the outline's edges near the end that run across the axis rather than along it
    c_ = list(deck.exterior.coords)
    for ln, a in axes:
        for e in a.get("ends", []):
            if not e["ground"]:
                continue
            x, y, nx, ny = frame(ln, e["s"])
            for (ax_, ay_), (bx_, by_) in zip(c_, c_[1:]):
                h_ = math.hypot(bx_ - ax_, by_ - ay_) or 1
                mx_, my_ = (ax_ + bx_) / 2, (ay_ + by_) / 2
                # the end edge itself: across the axis, and at its end (within END_EDGE_M along it); a short side edge near the end
                # that ran across lost its guard too (gaps in the guard at the end of a7)
                if abs((mx_ - x) * ny - (my_ - y) * nx) < END_EDGE_M and math.hypot(mx_ - x, my_ - y) < 25 and \
                        abs((bx_ - ax_) * ny - (by_ - ay_) * nx) / h_ < 0.5:
                    ends_.append(shapely.LineString([(ax_, ay_), (bx_, by_)]).buffer(0.5))
    gaps = shapely.union_all(ends_) if ends_ else shapely.Polygon()
    # and none on a lane (where the deck's edge crosses one); the cracks between two lanes closed first (a guard stood in one)
    gaps = gaps.union(veh_.buffer(GUARD_ON_LANE_M).buffer(-2 * GUARD_ON_LANE_M))
    # the deck's edge smoothed round the ends corrections/bridges.json names ("smooth_ends": [[axis, "start" | "end"]]): closed by
    # EDGE_CLOSE_M, then opened by EDGE_OPEN_M within EDGE_SMOOTH_R_M of that end (the V in barrier @80,191 at a4's end, where its
    # footway strip met a7's OSM footway: Kaveh, 2026-10-12)
    from .corrections import bridge as bridge_corr_s
    for ax_s, end_s, *side_s in bridge_corr_s(P["name"]).get("smooth_ends", []):
        if ax_s not in by_id:
            continue
        # (its own reach and closing when given, [axis, end, side, reach, closing]: a10's end at the a9 node, a small step only)
        r_s = side_s[1] if len(side_s) > 1 else EDGE_SMOOTH_R_M
        c_s = side_s[2] if len(side_s) > 2 else EDGE_CLOSE_M
        ln_s = by_id[ax_s][0]
        zone_s = ln_s.interpolate(0.0 if end_s == "start" else ln_s.length).buffer(r_s)
        if side_s:      # (on that side of its line, carried on past its ends, only: a4's footway side)
            zone_s = zone_s.intersection(extend(ln_s, r_s).buffer(r_s if side_s[0] == "left" else -r_s, single_sided=True))
        cl_ = deck.buffer(c_s, join_style="round").buffer(-c_s, join_style="round")
        cl_ = cl_.buffer(-EDGE_OPEN_M, join_style="round").buffer(EDGE_OPEN_M, join_style="round")
        sm_ = shapely.make_valid(deck.difference(zone_s).union(cl_.intersection(zone_s)).difference(veh_.buffer(-0.01).difference(deck)))
        # (the hairline left where the two meet on the zone's edge, closed: the guards ran into it across footway w871038559 #4,
        # Kaveh, 2026-10-12 "barrier @-526,-258 and barrier @97,207 have wrong tails")
        sm_ = shapely.make_valid(sm_.buffer(0.05, join_style="mitre").buffer(-0.05, join_style="mitre"))
        deck = max(shapely.get_parts(sm_), key=lambda g_: g_.area) if sm_.geom_type != "Polygon" else sm_
    # (a hole beside a kept path, between it and the lanes beside it, is deck: a guard ran round one beside shared path w1417439065)
    kept_g = shapely.union_all([own[k_] for k_ in own if (shared[k_[1]][2] if k_[0] == "s" else lanes[k_[1]]["props"]).get("osm") in keep_w])
    if not kept_g.is_empty and deck.geom_type == "Polygon":
        deck = shapely.Polygon(deck.exterior, [r for r in deck.interiors if not (shapely.Polygon(r).area < KEEP_HOLE_M2 and shapely.LinearRing(r).distance(kept_g) < 1.0)])
    # no guard along the sides corrections/bridges.json names ("no_guard": [[axis, "left" | "right"]]): a2's east side, part of barrier
    # @-388,-409 (Kaveh, 2026-10-12)
    from .corrections import bridge as bridge_corr_g
    for ax_g, side_g in bridge_corr_g(P["name"]).get("no_guard", []):
        if ax_g in by_id:
            gaps = gaps.union(by_id[ax_g][0].buffer(NO_GUARD_REACH_M if side_g == "left" else -NO_GUARD_REACH_M, single_sided=True))
    rim = lambda d0, d1: shapely.make_valid(deck.buffer(-d0).difference(deck.buffer(-d1))).difference(gaps)
    # (no stub: a guard piece under GUARD_MIN_M long is left out, barrier @-254,-236 at the a10/a11 node, Kaveh, 2026-10-12)
    rim_ = rim(0.0, BARRIER_M[1])
    rim_ = shapely.union_all([q_ for q_ in shapely.get_parts(rim_) if q_.area >= GUARD_MIN_M * BARRIER_M[1]]) if not rim_.is_empty else rim_
    mesh(rim_, "barrier", 0.0, None, BARRIER_M[0])
    # no free space on the bridge: deck that no part covers is the path or fill it shares the longest edge with (in 2D one shape with
    # it), else footway; Kaveh, 2026-10-12, "the bridge can't have free space, all parts must be covered with something"
    cover_ = shapely.union_all([sf_["poly"] for sf_ in surf if sf_.get("poly") is not None and not sf_["key"].startswith("mark")
                                and sf_["key"] != "railing"])
    free_ = shapely.make_valid(deck.difference(cover_))
    fillable_ = [sf_ for sf_ in surf if sf_.get("poly") is not None and sf_["key"] in ("sidewalk", "cycle lane", "median", "buffer", "junction area")]
    # (its thin parts and its wide parts each on their own: a 5 cm strip along a2's lane, joined to a wide piece far away, went to a shared
    # path, and a barrier closed a2's end against it)
    free_ = free_.buffer(-0.02).buffer(0.02)
    wide_f = free_.buffer(-FREE_THIN_M / 2, join_style="mitre").buffer(FREE_THIN_M / 2, join_style="mitre").intersection(free_)
    pieces_f = list(shapely.get_parts(wide_f)) + list(shapely.get_parts(free_.difference(wide_f)))
    for g_ in pieces_f:
        if g_.geom_type != "Polygon" or g_.area < FREE_MIN_M2:
            continue
        g_ = shapely.union_all([q_ for q_ in shapely.get_parts(g_.intersection(deck)) if q_.geom_type in ("Polygon", "MultiPolygon")])
        if g_.is_empty or g_.area < FREE_MIN_M2:
            continue
        # (a sliver between lanes, under FREE_THIN_M wide, is the lane beside it: footway there put a path between two lanes)
        lanes_s = [sf_ for sf_ in surf if sf_.get("poly") is not None and sf_["key"].startswith("lane")]
        if 2 * shapely.maximum_inscribed_circle(g_).length < FREE_THIN_M and lanes_s:
            # (each part of it to the lane right beside it: one long sliver along a3 went whole to a lane 300 m away)
            near_l = sorted([sf_ for sf_ in lanes_s if sf_["poly"].distance(g_) < 0.05],
                            key=lambda sf_: -g_.boundary.intersection(sf_["poly"].buffer(0.05)).length)
            rem_ = g_
            for lb_ in near_l:
                part_ = rem_.intersection(lb_["poly"].buffer(FREE_THIN_M))
                if part_.is_empty or part_.area < 0.01:
                    continue
                rem_ = rem_.difference(part_)
                if flat_only:
                    lb_["poly"] = shapely.make_valid(lb_["poly"].union(part_.buffer(0.01)))
                else:
                    mesh(part_, lb_["key"], SURF_LIFT_M, lb_["props"])
            if near_l and not rem_.is_empty and rem_.area > 0.01:     # (what is left of it, further than that: the nearest lane's)
                lb_ = min(near_l, key=lambda sf_: sf_["poly"].distance(rem_))
                if flat_only:
                    lb_["poly"] = shapely.make_valid(lb_["poly"].union(rem_.buffer(0.01)))
                else:
                    mesh(rem_, lb_["key"], SURF_LIFT_M, lb_["props"])
            if near_l:
                continue
        by_ = [(g_.boundary.intersection(sf_["poly"].buffer(0.05)).length, i_) for i_, sf_ in enumerate(fillable_)]
        by_ = [x_ for x_ in by_ if x_[0] > 0.3]
        if by_:
            sf_a = fillable_[max(by_)[1]]
            if flat_only:
                sf_a["poly"] = shapely.make_valid(sf_a["poly"].union(g_.buffer(0.01)))
            else:
                mesh(g_, sf_a["key"], SURF_LIFT_M if sf_a["key"] != "sidewalk" else LIFT[False], sf_a["props"], RAISED.get(sf_a["key"], 0.0))
        else:
            mesh(g_, "sidewalk", LIFT[False], {"type": "footway", "name": P["name"], "source": "urbanstyle",
                                                "method": "derived: deck no other part covers"}, RAISED.get("sidewalk", 0.0))
    # a barrier wherever a driving lane meets a path (footway, cycle lane, shared path) and none stands yet, but not where a crosswalk
    # crosses: Kaveh, 2026-10-12, "between driving lane and other lanes must have barrier on bridge"
    lanes_f = shapely.union_all([sf_["poly"] for sf_ in surf if sf_.get("poly") is not None and sf_["key"].startswith("lane")])
    paths_f = shapely.union_all([sf_["poly"] for sf_ in surf if sf_.get("poly") is not None and sf_["key"] in ("sidewalk", "cycle lane")])
    bars_f = shapely.union_all([sf_["poly"] for sf_ in surf if sf_.get("poly") is not None and sf_["key"].startswith("barrier")])
    no_x = x_open
    shut_ = lanes_f.buffer(0.2, join_style="mitre").buffer(-0.2, join_style="mitre")
    miss_ = shut_.boundary.intersection(paths_f.buffer(0.15)).difference(bars_f.buffer(0.35)).difference(no_x)
    for ln_m in shapely.get_parts(shapely.line_merge(miss_) if not miss_.is_empty else miss_):
        if ln_m.geom_type != "LineString" or ln_m.length < 0.5:
            continue
        # an end next to a barrier runs on into it: cut back 0.35 m from the barriers above, it left a gap at each end (barriers @316,415
        # and @327,406; Kaveh, 2026-10-14, "not completely fit", "not connect completely")
        c_m = list(ln_m.coords)
        for i_, j_ in ((0, 1), (-1, -2)):
            if bars_f.distance(shapely.Point(c_m[i_])) < 0.5:
                (ax_, ay_), (bx_, by_) = c_m[i_], c_m[j_]
                h_ = math.hypot(ax_ - bx_, ay_ - by_) or 1
                c_m[i_] = (ax_ + (ax_ - bx_) / h_ * 0.45, ay_ + (ay_ - by_) / h_ * 0.45)
        ln_m = shapely.LineString(c_m)
        off = ln_m.offset_curve(BARRIER_SEP_M[0] / 2)
        if off.is_empty or off.geom_type != "LineString" or lanes_f.contains(off.interpolate(0.5, normalized=True)):
            off = ln_m.offset_curve(-BARRIER_SEP_M[0] / 2)
        if off.is_empty or off.geom_type != "LineString" or lanes_f.contains(off.interpolate(0.5, normalized=True)):
            off = ln_m          # (a path's tip between two lanes, a3 and a10: on the lanes' edge itself)
        if off.geom_type == "LineString" and not off.is_empty:
            strip(off, BARRIER_SEP_M[0], "barrier", 0.0, None, BARRIER_SEP_M[1])
    # the tip of a path between two lanes, narrower than a barrier, is the barrier's nose: footway w538616397's tip ran on 1.4 m past its
    # barrier between a3 and a10 (BR10)
    tips_ = paths_f.difference(paths_f.buffer(-BARRIER_SEP_M[0] / 2).buffer(BARRIER_SEP_M[0] / 2 + 0.01))
    bars_f = shapely.union_all([sf_["poly"] for sf_ in surf if sf_.get("poly") is not None and sf_["key"].startswith("barrier")])
    for t_ in shapely.get_parts(tips_):
        if t_.geom_type == "Polygon" and t_.boundary.intersection(lanes_f.buffer(0.05)).length > 0.7 * t_.length:
            # (and back to the barriers near it: with a strip's slanted end a wedge of path stayed between them)
            nose_ = paths_f.intersection(shapely.union_all([t_, bars_f.intersection(t_.buffer(2.0))]).convex_hull)
            mesh(nose_, "barrier", 0.0, None, BARRIER_SEP_M[1])
    mesh(rim(0.1, 0.2), "railing", RAILING_M[0] - 0.08, None, 0.08)
    in_ = shapely.make_valid(deck.buffer(-BARRIER_M[1] / 2))       # (its area parts only: a thin spot gave lines too, a9)
    mid = shapely.MultiPolygon([q_ for g_ in shapely.get_parts(in_) for q_ in shapely.get_parts(g_) if q_.geom_type == "Polygon"]).boundary.difference(gaps)
    for ring in shapely.get_parts(mid):
        if ring.geom_type != "LineString":
            continue
        for k in range(int(ring.length // RAILING_M[1]) + 1):
            p_ = ring.interpolate(k * RAILING_M[1])
            mesh(p_.buffer(0.05, cap_style="square"), "railing", BARRIER_M[0], None, RAILING_M[0] - BARRIER_M[0])
    rails = []        # (the guards above replace the plain parapet)
    checks = [] if flat_only else \
        [(c, w, n, h, [list(to_ll(x + x0, y + y0)) for x, y in at]) for c, w, n, h, at in model_checks(surf, deck, ends_, S, axes)]
    v = lambda d: f"{d['source']}, {d['method']}"
    # the page places the model in the map's metres (Web Mercator, scaled to true metres at the origin): UTM's north is turned from the
    # map's by the meridian convergence (0.1 degrees at Vancouver) and its scale differs, so a point 600 m from the origin was 1 m off its
    # street; every point goes through the map's projection
    import numpy as np
    merc = pyproj.Transformer.from_crs(P["crs"], "EPSG:3857", always_xy=True).transform
    mx0, my0 = merc(x0, y0)
    k = math.cos(math.radians(to_ll(x0, y0)[1]))

    def to_map(pts):
        """[[x, y, ...]] in metres east and north of the origin in UTM, to the map's metres (in place)."""
        if not pts:
            return pts
        a = np.asarray([q[:2] for q in pts], dtype=float)
        X, Y = merc(a[:, 0] + x0, a[:, 1] + y0)
        for q, xm, ym in zip(pts, (X - mx0) * k, (Y - my0) * k):
            q[0], q[1] = round(float(xm), 2), round(float(ym), 2)
        return pts
    # the slab drawn from the deck as it is now: the deck grows and is cut after the first slab (its heights, zd), and the guards stand on
    # the final deck's edge; the old slab's edge showed as steps beside them and as bare deck (Kaveh, 2026-10-12: "stepping in barriers")
    top_f, bottom_f, sides_f = top, bottom, sides
    if not flat_only:
        dense_f = deck.segmentize(STEP_M)
        tris_f = [t for cell in grid(dense_f, STEP_M) for pc in shapely.get_parts(cell) if pc.geom_type == "Polygon" and pc.area > 1e-4
                  for t in shapely.get_parts(shapely.constrained_delaunay_triangles(pc)) if t.representative_point().within(pc.buffer(0.01))]
        # (at the heights the lanes and paths stand on, zd: with z's own heights the deck rose through the lanes in grey patches)
        top_f = [[vid(x, y, zd(x, y)) for x, y in t.exterior.coords[:3]] for t in tris_f]
        bottom_f = [[vid(x, y, under(x, y, zd(x, y))) for x, y in t.exterior.coords[:3]][::-1] for t in tris_f]
        sides_f = []
        for ring in [dense_f.exterior] + list(dense_f.interiors):
            c = list(ring.coords)
            for (ax, ay), (bx, by) in zip(c, c[1:]):
                za, zb = zd(ax, ay), zd(bx, by)
                a0, b0, a1, b1 = vid(ax, ay, under(ax, ay, za)), vid(bx, by, under(bx, by, zb)), vid(ax, ay, za), vid(bx, by, zb)
                sides_f += [[a0, b0, b1], [a0, b1, a1]]
    deck_ll = json.loads(shapely.to_geojson(shapely.ops.transform(lambda x, y: to_ll(x + x0, y + y0), deck)))   # (the final outline, GeoJSON, for checks)
    flat = []           # the 2D layer (dashboard "Bridge 2D"): each surface's outline in lon / lat, with its id and fields
    for sf_ in surf:
        if sf_.get("poly") is not None and sf_["props"] and sf_["props"].get("id"):
            g_ = shapely.ops.transform(lambda x, y: to_ll(x + x0, y + y0), sf_["poly"].simplify(0.02))
            flat.append((sf_["props"], sf_["key"], g_))
        sf_.pop("poly", None)
    to_map(verts)
    for sf in surf:
        to_map(sf["v"])
    for q in piers:
        to_map([q["a"], q["b"]])
    for q in truss:
        to_map([q["a"], q["b"]])
    return {"name": P["name"], "origin": list(to_ll(x0, y0)), "outline": [list(to_ll(x, y)) for x, y in ol], "verts": verts,
            "deck": top_f + bottom_f, "axes": [[list(to_ll(x, y)) for x, y in a["line"]["value"]] for a in P["axes"]], "sides": sides_f, "rails": rails, "lines": lines, "lanes": lanes, "piers": piers, "truss": truss, "surf": surf, "checks": checks, "flat": flat, "deck_ll": deck_ll,
            "sources": {"outline": v(P["deck"]["outline"]), "heights": "; ".join(sorted({v(a["vertical"]) for _, a in axes})),
                        "deck": v(P["deck"]["thickness"]), "parapet": v(P["deck"]["parapet"]),
                        "piers": v(P["piers"][0]) if P["piers"] else "none"}}


if __name__ == "__main__":
    import sys
    m = model(sys.argv[1])
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in m.items()}, indent=1))
