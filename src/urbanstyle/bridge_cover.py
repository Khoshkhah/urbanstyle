"""The cover of a bridge (ranks 1 to 6 of docs/notes/bridges-ranks.md) and the deck it makes, from the profile by general rules only
(docs/notes/bridge-parts.md, "The cover"). No corrections file and no rule for one place:

1. A lane runs where SUMO runs it: its band from s_from to s_to (GMNS geom_cut) at its offset t, as wide as its width. It runs on to
   its section's end where the next section of its axis goes on, at a fork or a merge (2), at a ground end, and where SUMO's connector to
   the next lane is shorter than JOIN_M: there the lanes meet.
2. A junction node where every move turns JOIN_ANGLE or less is a fork or a merge. The trunk is the arm on the other side of the node
   from all the others, and it keeps its lanes. Each lane of another arm lies on the trunk lane its move names, carried straight on past
   the node, until its arm really separates from the others (its lanes clear of theirs by DIVIDER_M); then it eases to its own line over
   JOIN_BLEND_M. A lane with no move there keeps its own line. Two one-way arms that run on side by side (a carriageway pair, rank 0's
   rule) are one road: their lanes stay side by side about the line midway between them as long as the two run together.
3. At any other junction node a lane ends where SUMO ends it, and SUMO's connector carries it on: a ribbon along the connector's line.
4. No move turns more than NO_TURN_DEG: a bridge has no U-turn (bridge_surface._moves).
5. Sidewalks, cycleways and shared paths are bands along their own OSM lines, joined where OSM joins them (bridge_surface._path_bands).
   A crossing (footway=crossing, cycleway=crossing, a crossing tag) is a crosswalk over the lanes: zebra bars unless OSM says unmarked.
6. The deck of a level is all of these together, gaps narrower than 2 CLOSE_M closed, plus EDGE_M: it has no outline of its own.

Paint: a lane line between two lanes of one direction, a centre line between the two directions, an edge line along the driving side,
a guide line along each connector ribbon, an arrow on each lane every ARROW_EVERY_M. A barrier stands between the driving side and a
path band within PATH_BARRIER_M of it; the rest of the deck is paved."""
import math

JOIN_M = 2.0            # a connector shorter than this: the two lanes meet instead
JOIN_ANGLE = 30.0       # a node where every move turns this or less (degrees) is a fork or a merge
NO_TURN_DEG = 90.0      # a move that turns more than this is no move on a bridge (a U-turn)
DIVIDER_M = 0.5         # an arm separates where its lanes are this clear of the other arms' lanes
SPLIT_MAX_M = 200.0     # ... within this of the node, at most
PAIR_M = 14.0           # two one-way arms this near each other ...
PAIR_MIN_M = 40.0       # ... over at least this (and 80 % of the shorter) are one road: a carriageway pair (rank 0's rule)
JOIN_BLEND_M = 70.0     # then its lanes ease to their own line over this (40 m opened a sliver of paving where a4 leaves a9)
EDGE_M = 0.5            # the deck beyond the outer lane or path: the parapet stands on it
CLOSE_M = 1.5           # a gap narrower than twice this between two pieces of the cover is deck
SMOOTH_M = 1.0          # the deck's edge has no notch and no bump smaller than twice this
STEP_M = 1.0            # lanes are sampled this often along their axis
PATH_BARRIER_M = 2.0    # a barrier between the driving side and a path band this near it
ARROW_EVERY_M = 100.0   # an arrow on each lane this often
LIFT_M = 0.03           # the cover above the slab's top
PAINT_M = 0.06          # paint above the slab's top
RAISE_M = 0.15          # a sidewalk or cycle lane above the roadway
SEP_W, SEP_H = 0.5, 0.9  # a barrier: wide, high


def _heading(line, at_start, d=2.0):
    """The unit direction of a line at one end, over its first (or last) d metres, in its own sense."""
    if at_start:
        a, b = line.coords[0], line.interpolate(min(d, line.length)).coords[0]
    else:
        a, b = line.interpolate(max(line.length - d, 0.0)).coords[0], line.coords[-1]
    h = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
    return (b[0] - a[0]) / h, (b[1] - a[1]) / h


def _turn(line):
    """How far a connector turns, in degrees (0: straight on)."""
    (ux, uy), (vx, vy) = _heading(line, True), _heading(line, False)
    return math.degrees(math.acos(max(-1.0, min(1.0, ux * vx + uy * vy))))


def layout(P, axes, a_lv, steps1=None):
    """The cover of profile P (its axes as [(line, axis)], their levels {axis id: level}), in the profile's crs: {"items": [(polygon,
    key, lift, rise, props)], "deck": {level: polygon}, "own": {axis id: polygon}}. `own` is each axis's own lanes and paths: the
    height surface blends the axes by nearness to them. steps1: step 1's points (bridge_forks.forks); at its forks the trunk and the
    branch points are step 1's, and a branch's lanes move from the trunk's lanes at the node to their own line at the branch point,
    so that the branch begins with its bands in place (docs/notes/bridge-steps.md, step 4)."""
    import numpy as np
    import shapely
    import shapely.ops
    from .bridge_surface import _frame, _path_bands
    val = lambda v: v["value"] if isinstance(v, dict) else v
    by_id = {a["id"]: (ln, a) for ln, a in axes}

    # ---- the bands at each end of each axis, and the junction nodes
    lane_axis = {}
    for ln, a in axes:
        for sec in a.get("sections", []):
            for b in sec.get("bands") or []:
                if b.get("type") == "lane" and b.get("lane_id"):
                    lane_axis[b["lane_id"]] = a["id"]
    end_bands = lambda a, k: [b for b in (a["sections"][-1 if k else 0].get("bands") or []) if b.get("type") == "lane"] if a.get("sections") else []
    at_node = {}                                     # node -> [(axis id, end 0|1)]
    for ln, a in axes:
        for k, e in enumerate(a.get("ends", [])):
            if e.get("node") and not e.get("ground"):
                at_node.setdefault(e["node"], []).append((a["id"], k))
    cons = []                                        # (connector, its line, its turn)
    for c in P.get("connectors", []):
        if len(c.get("line") or []) >= 2:
            cl = shapely.LineString([q[:2] for q in c["line"]])
            cons.append((c, cl, _turn(cl)))
    cons = [x for x in cons if x[2] <= NO_TURN_DEG]                      # rule 4

    def end_pt(aid, k):
        ln = by_id[aid][0]
        return ln.coords[-1] if k else ln.coords[0]

    def away(aid, k):                                # from the node into the arm
        ln = by_id[aid][0]
        hx, hy = _heading(ln, k == 0)
        return (hx, hy) if k == 0 else (-hx, -hy)
    step1_forks = {f["node"]: f for f in (steps1 or {}).get("forks", [])}
    forks, meet = {}, set()          # node -> its arms and trunk; (axis id, end) whose lanes run to the section end
    for node, arms in at_node.items():
        if len(arms) < 2:
            continue
        ids = {aid for aid, _ in arms}
        xn, yn = end_pt(*arms[0])
        here = [(c, cl, t) for c, cl, t in cons if lane_axis.get(c["from"]) in ids and lane_axis.get(c["to"]) in ids
                and lane_axis.get(c["from"]) != lane_axis.get(c["to"]) and cl.distance(shapely.Point(xn, yn)) < 30.0]
        if here and all(t <= JOIN_ANGLE for _, _, t in here):            # rule 2: a fork or a merge
            aw = {x: away(*x) for x in arms}
            trunk = min(arms, key=lambda x: sum(aw[y][0] * aw[x][0] + aw[y][1] * aw[x][1] for y in arms if y != x))
            if node in step1_forks:
                trunk = step1_forks[node]["trunk"][0]
            forks[node] = (arms, trunk, here, (xn, yn))
            meet |= set(arms)
        for c, cl, t in here:
            if cl.length < JOIN_M:
                meet |= {x for x in arms if x[0] in (lane_axis.get(c["from"]), lane_axis.get(c["to"]))}

    # ---- rule 2: where each lane of a fork's arm lies near the node
    place = {}           # (lane id, axis id, end) -> (trunk point at the node, the trunk's straight direction on, the separation distance)
    for node, (arms, (tid, tk), here, (xn, yn)) in forks.items():
        lnT, T = by_id[tid]
        xT, yT, nxT, nyT = _frame(lnT, lnT.length if tk else 0.0)
        dx, dy = (-away(tid, tk)[0], -away(tid, tk)[1])              # the trunk carried straight on past the node
        t_of = {b["lane_id"]: float(b["t"]) for b in end_bands(T, tk) if b.get("lane_id")}
        own_g = {}       # each other arm's own lanes near the node, unmoved: to find where it separates
        for aid, k in arms:
            if (aid, k) == (tid, tk):
                continue
            ln, a = by_id[aid]
            L = ln.length
            span = min(L, SPLIT_MAX_M)
            parts = []
            for b in end_bands(a, k):
                seg = [(lambda s: (lambda f: (f[0] + f[2] * float(b["t"]), f[1] + f[3] * float(b["t"])))(_frame(ln, s)))(L - d if k else d)
                       for d in np.arange(0.0, span + 0.01, 2.0)]
                if len(seg) >= 2:
                    parts.append(shapely.LineString(seg).buffer(float(b["width"]["value"]) / 2, cap_style="flat"))
            own_g[(aid, k)] = shapely.union_all(parts) if parts else shapely.Polygon()
        for aid, k in own_g:
            ln, a = by_id[aid]
            L = ln.length
            others = shapely.union_all([g for x, g in own_g.items() if x != (aid, k)] or [shapely.Polygon()])
            bs = end_bands(a, k)
            ds = 0.0
            inside = node in step1_forks                   # (step 1's fork: the lanes reach their own line at its branch point)
            if inside:
                ds = float(step1_forks[node]["branch_m"].get(aid, 0.0))
            elif bs and not others.is_empty:
                lo = min(float(b["t"]) - float(b["width"]["value"]) / 2 for b in bs)
                hi = max(float(b["t"]) + float(b["width"]["value"]) / 2 for b in bs)
                while ds < min(L, SPLIT_MAX_M):
                    x, y, nx, ny = _frame(ln, L - ds if k else ds)
                    if shapely.LineString([(x + nx * lo, y + ny * lo), (x + nx * hi, y + ny * hi)]).distance(others) >= DIVIDER_M:
                        break
                    ds += 1.0
            for b in bs:
                lid = b.get("lane_id")
                ps = [t_of[o] for c, cl, t in here for m, o in ((c["from"], c["to"]), (c["to"], c["from"])) if m == lid and o in t_of]
                if ps:
                    tp = sum(ps) / len(ps)
                    place[(lid, aid, k)] = ((lambda d, q=(xT + nxT * tp, yT + nyT * tp): (q[0] + dx * d, q[1] + dy * d)), ds, inside)
        # a carriageway pair: two one-way arms that leave the fork side by side (within PAIR_M over PAIR_MIN_M and 80 % of the shorter,
        # rank 0's rule, _merge_carriageways) are one road: their lanes stay side by side about the line midway between them, on the
        # trunk lanes their moves name, as long as the two run together; then each eases to its own line (Hemlock a11 and a12 parted
        # at 20 m and left islands of paving between them)
        one_way = lambda a: len({b.get("direction") for sec in a.get("sections", []) for b in (sec.get("bands") or []) if b.get("type") == "lane"}) == 1
        others_ = [x for x in arms if x != (tid, tk) and one_way(by_id[x[0]][1])]
        for i_, A in enumerate(others_):
            for B in others_[i_ + 1:]:
                lnA, lnB = by_id[A[0]][0], by_id[B[0]][0]
                LA, LB = lnA.length, lnB.length
                at_d = lambda ln, k, d: ln.interpolate(ln.length - d if k else d)
                mids, Lp = [], 0.0
                for d in np.arange(0.0, min(LA, LB) + 0.01, 1.0):
                    pa = at_d(lnA, A[1], float(d))
                    if pa.distance(lnB) > PAIR_M:
                        break
                    pb = lnB.interpolate(lnB.project(pa))
                    mids.append(((pa.x + pb.x) / 2, (pa.y + pb.y) / 2)); Lp = float(d)
                if Lp < PAIR_MIN_M or Lp < 0.8 * min(LA, LB) or len(mids) < 3:
                    continue
                mid = shapely.LineString(mids)
                _, _, nxm, nym = _frame(mid, 0.0)
                sg = 1.0 if nxm * nxT + nym * nyT >= 0 else -1.0        # the trunk's left is the middle line's left (or its right)
                for aid, k in (A, B):
                    bs = end_bands(by_id[aid][1], k)
                    tm = {}
                    for b in bs:
                        lid = b.get("lane_id")
                        ps = [t_of[o] for c, cl, t in here for m, o in ((c["from"], c["to"]), (c["to"], c["from"])) if m == lid and o in t_of]
                        if ps:
                            tm[lid] = sg * sum(ps) / len(ps)
                    if not tm:
                        continue
                    _, _, nxo, nyo = _frame(by_id[aid][0], by_id[aid][0].length if k else 0.0)
                    so = 1.0 if nxo * nxm + nyo * nym >= 0 else -1.0    # its own left against the middle line's
                    for b in bs:            # a lane with no move there: beside its nearest lane that has one, as far as in its own band
                        lid = b.get("lane_id")
                        if lid not in tm:
                            nb = min((b2 for b2 in bs if b2.get("lane_id") in tm), key=lambda b2: abs(float(b2["t"]) - float(b["t"])))
                            tm[lid] = tm[nb["lane_id"]] + so * (float(b["t"]) - float(nb["t"]))
                        def fn(d, t_=tm[lid], mid=mid):
                            x_, y_, nx_, ny_ = _frame(mid, min(d, mid.length))
                            return x_ + nx_ * t_, y_ + ny_ * t_
                        place[(lid, aid, k)] = (fn, Lp, False)

    # ---- the lanes (rules 1 and 2): each band of each section as a centre line, then a ribbon as wide as it
    fork_arms = {x for arms_, *_ in forks.values() for x in arms_}
    lanes = []           # (polygon, props, centre line in its travel direction, axis id)
    for ln, a in axes:
        L = ln.length
        secs = a.get("sections", [])
        for si, sec in enumerate(secs):
            for b in sec.get("bands") or []:
                if b.get("type") != "lane":
                    continue
                f_, t_ = b.get("s_from", sec["s0"]), b.get("s_to", sec["s1"])
                if si > 0 or (a["id"], 0) in meet or a["ends"][0].get("ground"):
                    f_ = sec["s0"]
                if si < len(secs) - 1 or (a["id"], 1) in meet or a["ends"][1].get("ground"):
                    t_ = sec["s1"]
                if t_ - f_ < 0.5:
                    continue
                pts = []
                for s in np.linspace(f_, t_, max(2, int((t_ - f_) / STEP_M) + 1)):
                    x, y, nx, ny = _frame(ln, float(s))
                    px, py = x + nx * float(b["t"]), y + ny * float(b["t"])
                    for k, d in ((0, float(s)), (1, L - float(s))):
                        pl = place.get((b.get("lane_id"), a["id"], k))
                        if pl and d < pl[1] + (0.0 if pl[2] else JOIN_BLEND_M):
                            fn, ds, inside = pl
                            if inside:            # (step 1's fork: from the trunk's lane at the node to its own line at the branch point)
                                u = 0.5 * (1 + math.cos(math.pi * d / ds)) if ds > 0 else 0.0
                            else:
                                u = 1.0 if d <= ds else 0.5 * (1 + math.cos(math.pi * (d - ds) / JOIN_BLEND_M))
                            qx, qy = fn(d)
                            px, py = px * (1 - u) + qx * u, py * (1 - u) + qy * u
                    pts.append((px, py))
                for k, at in ((0, f_ <= 0.01), (1, t_ >= L - 0.01)):     # (a lane end at a fork runs 1 m on past the node: no wedge where
                    if at and (a["id"], k) in fork_arms and len(pts) >= 2:   # two lanes meet at an angle; the first one drawn keeps it)
                        (ax_, ay_), (bx_, by_) = (pts[0], pts[1]) if k == 0 else (pts[-1], pts[-2])
                        h_ = math.hypot(ax_ - bx_, ay_ - by_) or 1.0
                        e_ = (ax_ + (ax_ - bx_) / h_ * 1.0, ay_ + (ay_ - by_) / h_ * 1.0)
                        pts = [e_] + pts if k == 0 else pts + [e_]
                c = shapely.LineString(pts if b.get("direction") != "backward" else pts[::-1])
                w = float(b["width"]["value"])
                props = {"id": f"{b.get('lane_id')} {a['id']}.{si}", "type": "lane", "bridge": P["name"], "axis": a["id"], "lane_id": b.get("lane_id"),
                         "direction": b.get("direction"), "lane": b.get("lane"), "width_m": w, "osm": b.get("way"),
                         "source": "duckOSM GMNS (lanes from SUMO)", "method": "mapped"}
                lanes.append((c.buffer(w / 2, cap_style="flat", join_style="round"), props, c, a["id"]))
    # rule 3: SUMO's connector through any other junction node (not inside one axis, not at a fork, not where the lanes meet)
    fork_cons = {id(c) for _, _, here, _ in forks.values() for c, _, _ in here}
    junction = []
    for c, cl, t in cons:
        fa, ta = lane_axis.get(c["from"]), lane_axis.get(c["to"])
        if fa is None or ta is None or fa == ta or id(c) in fork_cons or cl.length < JOIN_M:
            continue
        w = float(val(c.get("width")) or 3.0)
        junction.append((cl.buffer(w / 2, cap_style="flat"), {"id": c["id"], "type": "junction lane", "bridge": P["name"], "from_lane": c["from"],
                                                              "to_lane": c["to"], "width_m": w, "source": c["source"], "method": c["method"]}, cl, fa))
    # lanes made disjoint: where two ribbons overlap, the first keeps it (no surface over another)
    done, out_l = shapely.Polygon(), []
    for pg, props, c, aid in lanes + junction:
        q = shapely.make_valid(pg.difference(done))
        q = shapely.union_all([g for g in shapely.get_parts(q) if g.geom_type == "Polygon" and g.area > 0.05] or [shapely.Polygon()])
        if q.area > 0.3:
            out_l.append((q, props, c, aid))
            done = done.union(pg)

    # ---- rule 5: the paths and the crossings
    crossing = lambda p: p.get("footway") == "crossing" or p.get("cycleway") == "crossing" or bool(p.get("crossing"))
    P_paths = dict(P, paths=[p for p in P.get("paths", []) if not crossing(p)])
    pb, pj = _path_bands(P_paths, axes)
    piece = lambda b_: b_["line"].buffer(b_["width"] / 2, cap_style="flat", join_style="round")
    disc = lambda jt: shapely.Point(jt["at"]).buffer(min(pb[jt["bands"][0]]["width"], pb[jt["bands"][1]]["width"]) / 2)
    path_pg = {}         # kind -> polygon
    for kind in ("sidewalk", "cycle lane"):
        path_pg[kind] = shapely.union_all([piece(b_) for b_ in pb if b_["kind"] == kind]
                                          + [disc(jt) for jt in pj if kind in (pb[jt["bands"][0]]["kind"], pb[jt["bands"][1]]["kind"])]
                                          or [shapely.Polygon()])
    crossings = [(shapely.LineString([q[:2] for q in val(p["line"])]), float(val(p.get("width")) or 3.0),
                  not (p.get("crossing") == "unmarked" or p.get("markings") == "no"), p.get("way"))
                 for p in P.get("paths", []) if crossing(p) and len(val(p["line"])) >= 2]

    # ---- rule 6: the deck of each level, and each axis's own strip
    own = {}
    for ln, a in axes:
        g = [q for q, props, c, aid in out_l if aid == a["id"]] + [piece(b_) for b_ in pb if b_["axis"] == a["id"]]
        own[a["id"]] = shapely.union_all(g).buffer(EDGE_M) if g else ln.buffer(1.0)
    deck = {}
    for lv in sorted(set(a_lv.values())):
        ids = [aid for aid, l_ in a_lv.items() if l_ == lv]
        g = [q for q, props, c, aid in out_l if aid in ids] + [piece(b_) for b_ in pb if b_["axis"] in ids] \
            + [disc(jt) for jt in pj if pb[jt["bands"][0]]["axis"] in ids]
        if g:
            u_ = shapely.union_all(g)
            d_ = u_.buffer(CLOSE_M, join_style="mitre").buffer(-CLOSE_M, join_style="mitre").union(u_).buffer(EDGE_M, join_style="mitre")
            # no notch and no bump in the edge smaller than 2 SMOOTH_M (a lane's square end beside the next one's made 22 jogs: D8)
            deck[lv] = d_.buffer(SMOOTH_M, join_style="round").buffer(-2 * SMOOTH_M, join_style="round").buffer(SMOOTH_M, join_style="round").union(u_)

    # ---- what lies on the deck, in drawing order, level by level (decks of two levels cross in plan: Avenue de France)
    items = []
    from .network import arrow_shape
    from .parts import CROSSWALK_M, ZEBRA_BAR_M, ZEBRA_GAP_M
    for lv, deck_lv in deck.items():
        ids = {aid for aid, l_ in a_lv.items() if l_ == lv}
        items += _level_items(P, lv, deck_lv, [x for x in out_l if x[3] in ids], [x for x in junction if x[3] in ids],
                              {k: shapely.union_all([piece(b_) for b_ in pb if b_["kind"] == k and b_["axis"] in ids]
                                                    + [disc(jt) for jt in pj if k in (pb[jt["bands"][0]]["kind"], pb[jt["bands"][1]]["kind"])
                                                       and pb[jt["bands"][0]]["axis"] in ids] or [shapely.Polygon()]) for k in ("sidewalk", "cycle lane")},
                              [cr for cr in crossings if deck_lv.buffer(-0.1).intersects(cr[0])], arrow_shape, (CROSSWALK_M, ZEBRA_BAR_M, ZEBRA_GAP_M))
    return {"items": [(g, k, l, r, p) for g, k, l, r, p in items if not g.is_empty and g.area > 0.01], "deck": deck, "own": own}


def _level_items(P, lv, deck_lv, out_l, junction, paths_lv, crossings, arrow_shape, zebra):
    """What lies on the deck of one level: lanes, paved, sidewalks, cycle lanes, barriers, paint (layout)."""
    import numpy as np
    import shapely
    import shapely.ops
    CROSSWALK_M, ZEBRA_BAR_M, ZEBRA_GAP_M = zebra
    items = []
    drive = shapely.union_all([q for q, *_ in out_l] or [shapely.Polygon()])
    drive = drive.buffer(0.1, join_style="mitre").buffer(-0.1, join_style="mitre")   # (a hairline between two lane pieces made an edge line across)
    walk = paths_lv["sidewalk"].difference(drive).difference(paths_lv["cycle lane"])
    cyc = paths_lv["cycle lane"].difference(drive)
    sep = drive.buffer(SEP_W, join_style="mitre").difference(drive).intersection(walk.union(cyc).buffer(PATH_BARRIER_M))
    walk, cyc = walk.difference(sep), cyc.difference(sep)
    # (the rest of the deck is paved, bridge_surface.model: a gore between ramps or the edge beside a path is no sidewalk; it was made
    # the path's, and the sidewalks looked 10 m wide where the deck came from the bands, 2026-10-20)
    items.append((walk, "sidewalk", LIFT_M, RAISE_M, {"type": "sidewalk", "bridge": P["name"], "source": "osm", "method": "mapped"}))
    items.append((cyc, "cycle lane", LIFT_M, RAISE_M, {"type": "cycle lane", "bridge": P["name"], "source": "osm", "method": "mapped"}))
    items.append((sep, "barrier", LIFT_M, SEP_H, {"type": "barrier", "bridge": P["name"], "between": "the driving side and a path",
                                                 "source": "urbanstyle", "method": "derived"}))

    # ---- paint: the two directions of travel from each lane's neighbours (forward and backward are each axis's own words)
    def head_(c_, p_):
        s_ = c_.project(p_)
        u, v = c_.interpolate(max(0.0, s_ - 1.0)), c_.interpolate(min(c_.length, s_ + 1.0))
        return v.x - u.x, v.y - u.y
    band_l = [x for x in out_l if x[1]["type"] == "lane"]
    tree = shapely.STRtree([q for q, *_ in band_l]) if band_l else None
    grp = [None] * len(band_l)
    for i0 in range(len(band_l)):
        if grp[i0] is not None:
            continue
        grp[i0], stack = 0, [i0]
        while stack:
            i = stack.pop()
            qi, _, ci, _ = band_l[i]
            for j in tree.query(qi.buffer(0.5)):
                j = int(j)
                if j == i or grp[j] is not None or qi.distance(band_l[j][0]) > 0.5:
                    continue
                pi, pj_ = shapely.ops.nearest_points(qi, band_l[j][0])
                h1, h2 = head_(ci, pi), head_(band_l[j][2], pj_)
                grp[j] = grp[i] if h1[0] * h2[0] + h1[1] * h2[1] >= 0 else 1 - grp[i]
                stack.append(j)
    G = [shapely.union_all([q for (q, *_), g in zip(band_l, grp) if g == k] or [shapely.Polygon()]) for k in (0, 1)]
    G = [g_.buffer(0.1, join_style="mitre").buffer(-0.1, join_style="mitre") for g_ in G]   # (a hairline between two lanes stopped the lane line)
    # each lane drawn in the colour of its direction of travel (an axis's own forward was the other colour on the next axis: Hemlock)
    for (q, props, c, aid), g in zip(band_l, grp):
        items.append((q, "lane forward" if g == 0 else "lane backward", LIFT_M, 0.0, props))
    for q, props, c, aid in out_l:
        if props["type"] != "lane":
            items.append((q, "lane forward", LIFT_M, 0.0, props))
    paint = lambda g, w: g.buffer(w / 2, cap_style="flat") if not g.is_empty else shapely.Polygon()
    for (q, props, c, aid), g in zip(band_l, grp):
        ends_ = shapely.MultiPoint([c.coords[0], c.coords[-1]]).buffer(float(props.get("width_m") or 3.25) / 2 + 1.5)
        inner = q.boundary.intersection(G[g].buffer(-0.2)).difference(ends_)      # (along the lane only: not across its end)
        segs = []
        for l_ in shapely.get_parts(shapely.line_merge(inner) if inner.geom_type in ("LineString", "MultiLineString") else shapely.MultiLineString()):
            d0 = 0.0
            while d0 < l_.length:
                segs.append(shapely.ops.substring(l_, d0, min(d0 + 3.0, l_.length))); d0 += 9.0
        if segs:
            items.append((paint(shapely.union_all(segs), 0.12), "mark lane line", PAINT_M, 0.0, {"type": "lane line"}))
    centre = G[0].boundary.intersection(G[1].buffer(0.3))
    items.append((paint(centre, 0.15), "mark centre line", PAINT_M, 0.0, {"type": "centre line"}))
    items.append((paint(drive.buffer(-0.25).boundary, 0.12).intersection(drive).difference(paint(centre, 1.0)), "mark edge line", PAINT_M, 0.0,
                  {"type": "edge line"}))
    for q, props, cl, aid in junction:
        segs, d0 = [], 0.0
        while d0 < cl.length:
            segs.append(shapely.ops.substring(cl, d0, min(d0 + 1.0, cl.length))); d0 += 3.0
        items.append((paint(shapely.union_all(segs), 0.1), "mark guide line", PAINT_M, 0.0, {"type": "guide line", "connector": props["id"]}))
    for q, props, c, aid in band_l:
        Lc = c.length
        for s_ in ([x for x in np.arange(Lc - 15.0, 8.0, -ARROW_EVERY_M)] if Lc > 23.0 else [Lc / 2] if Lc > 8.0 else []):
            tip, back = c.interpolate(s_), c.interpolate(s_ - 1.0)
            hx, hy = tip.x - back.x, tip.y - back.y
            n = math.hypot(hx, hy) or 1.0
            a_ = arrow_shape((tip.x, tip.y), (hx / n, hy / n), {"straight"})
            if a_ is not None and not a_.is_empty:
                items.append((a_.buffer(0.075).intersection(q), "mark arrow", PAINT_M, 0.0, {"type": "arrow"}))
    for fl, w, marked, way in crossings:
        if not marked:
            continue
        for pc in shapely.get_parts(fl.intersection(drive.buffer(0.5))):
            if pc.geom_type != "LineString" or pc.length <= 1.0:
                continue
            d_ = ZEBRA_BAR_M / 2
            while d_ < pc.length:
                c_ = pc.interpolate(d_)
                a_, b_ = pc.interpolate(max(d_ - 0.25, 0)), pc.interpolate(min(d_ + 0.25, pc.length))
                h_ = math.hypot(b_.x - a_.x, b_.y - a_.y) or 1
                tx, ty = (b_.x - a_.x) / h_, (b_.y - a_.y) / h_
                half = (w or CROSSWALK_M) / 2
                bar = shapely.LineString([(c_.x - ty * half, c_.y + tx * half), (c_.x + ty * half, c_.y - tx * half)])
                items.append((bar.buffer(ZEBRA_BAR_M / 2, cap_style="flat").intersection(drive), "mark zebra", PAINT_M, 0.0,
                              {"type": "crosswalk", "osm": way, "source": "osm", "method": "mapped"}))
                d_ += ZEBRA_BAR_M + ZEBRA_GAP_M
    return [(g, k, l, r, dict(p, level=lv)) for g, k, l, r, p in items]


COLOURS = {"lane forward": "#555", "lane backward": "#777", "paved": "#9e9e9e", "sidewalk": "#d9cfb8", "cycle lane": "#2e8b57",
           "barrier": "#c0392b", "mark lane line": "#fff", "mark edge line": "#ffd700", "mark centre line": "#f5c518",
           "mark guide line": "#bbb", "mark arrow": "#fff", "mark zebra": "#fff"}


def plan2d(con, P, out):
    """The cover in plan, fast (no heights, no mesh): a page with every piece of the cover in its colour, each lane's id on hover, the
    junction nodes as rings. Drag to move, wheel to zoom. To check the cover's geometry before a 3D build."""
    import html as _html
    import shapely
    from .bridge_surface import _axis_level, _trim_to_osm
    _trim_to_osm(con, P)
    axes = [(shapely.LineString([q[:2] for q in a["line"]["value"]]), a) for a in P["axes"]]
    a_lv = _axis_level(con, P)
    cov = layout(P, axes, a_lv)
    allg = shapely.union_all(list(cov["deck"].values()))
    x0, y0, x1, y1 = allg.bounds
    X, Y = (lambda x: x - x0), (lambda y: y1 - y)
    ring = lambda r: "M" + " L".join(f"{X(x):.2f},{Y(y):.2f}" for x, y in r.coords) + " Z"
    poly_d = lambda g: " ".join(ring(pg.exterior) + "".join(ring(r) for r in pg.interiors)
                                for pg in shapely.get_parts(g) if pg.geom_type == "Polygon")
    svg = [f'<path d="{poly_d(g)}" fill="#cfd8dc" stroke="#333" stroke-width="1" vector-effect="non-scaling-stroke"/>' for g in cov["deck"].values()]
    order = list(COLOURS)
    for g, key, lift, rise, props in sorted(cov["items"], key=lambda it: order.index(it[1]) if it[1] in order else 0):
        tip = _html.escape(" ".join(f"{k}={v}" for k, v in props.items() if k in ("id", "type", "axis", "lane_id", "direction", "lane", "osm", "level")))
        svg.append(f'<path d="{poly_d(g)}" fill="{COLOURS.get(key, "#999")}" fill-rule="evenodd"><title>{tip}</title></path>')
    for ln, a in axes:
        for e, q in zip(a.get("ends", []), (ln.coords[0], ln.coords[-1])):
            if e.get("node") and not e.get("ground"):
                svg.append(f'<circle cx="{X(q[0]):.1f}" cy="{Y(q[1]):.1f}" r="1.5" fill="none" stroke="#e11" stroke-width="1.5" '
                           f'vector-effect="non-scaling-stroke"><title>{e["node"]}</title></circle>')
        m = ln.interpolate(0.5, normalized=True)
        svg.append(f'<text x="{X(m.x):.1f}" y="{Y(m.y):.1f}" font-size="4" fill="#00f">{a["id"]}</text>')
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>Cover: {_html.escape(P['name'])}</title>
<style>html,body{{margin:0;height:100%;background:#fafaf5;font-family:sans-serif}}svg{{width:100%;height:100%;cursor:grab}}
#k{{position:absolute;left:10px;top:8px;background:#fff;padding:6px 10px;border-radius:6px;box-shadow:0 1px 4px #0003;font-size:13px}}</style></head><body>
<div id="k"><b>{_html.escape(P['name'])}: the cover in plan (bridge_cover.layout)</b><br>light blue: the deck &middot; dark and mid grey: the lanes of
the two directions &middot; grey: paved &middot; beige: sidewalk &middot; green: cycle lane &middot; red: barrier &middot; red ring: a junction node
<br><small>drag: move &middot; wheel: zoom &middot; hover: what it is</small></div>
<svg id="s" viewBox="0 0 {x1 - x0:.1f} {y1 - y0:.1f}" xmlns="http://www.w3.org/2000/svg">{''.join(svg)}</svg>
<script>const s=document.getElementById('s');let v=s.viewBox.baseVal,d=null;
s.onmousedown=e=>{{d={{x:e.clientX,y:e.clientY}}}};window.onmouseup=()=>{{d=null}};
window.onmousemove=e=>{{if(!d)return;const k=v.width/s.clientWidth;v.x-=(e.clientX-d.x)*k;v.y-=(e.clientY-d.y)*k;d={{x:e.clientX,y:e.clientY}}}};
s.onwheel=e=>{{e.preventDefault();const f=Math.exp(e.deltaY*0.0015),r=s.getBoundingClientRect(),px=v.x+(e.clientX-r.left)/r.width*v.width,py=v.y+(e.clientY-r.top)/r.height*v.height;
v.width*=f;v.height*=f;v.x=px-(px-v.x)*f;v.y=py-(py-v.y)*f}};
const q=new URLSearchParams(location.search);if(q.get('n')){{const c=[...document.querySelectorAll('circle')].find(c=>c.textContent===q.get('n'));
if(c){{const w=+(q.get('w')||60);v.x=+c.getAttribute('cx')-w/2;v.y=+c.getAttribute('cy')-w*0.375;v.width=w;v.height=w*0.75}}}}</script></body></html>"""
    with open(out, "w") as f:
        f.write(page)
    return out
