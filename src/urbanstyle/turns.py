"""The moves through each junction at level 0 (docs/design/pipeline.md, step 8): SUMO's lane-to-lane connections on network.py's lanes.

network.py writes the lanes (`space.part`, type lane: per OSM way, direction forward / backward, lane 1 at the middle of the road). SUMO
(sumo.network: duckOSM's to_sumo and netconvert) gets the same lane count per direction and decides which lane goes on to which. Each
of its connections becomes, on our lanes:
    space.turn      one row per move (from SUMO lane, to SUMO lane, straight / left / right), its line the guide line;
    space.mark      a 'guide line' from the lane's end at the junction to the start of the lane it goes to (none on a roundabout: the
                    ring shows the way), and a turn 'arrow' in each lane coming in, its tip TIP_BACK_M before the junction (1 m behind
                    the stop line), a head for each way open to all traffic;
    space.approach  each lane coming in: its moves, its ways, and why it has no arrow.
No move without SUMO: without netconvert nothing is written (source sumo, method derived).
"""
import math
import re

from .network import STOP_BACK_M, arrow_shape
from .parts import ARROW_M, LINE

WAY = {"s": "straight", "l": "left", "L": "left", "r": "right", "R": "right"}     # SUMO's dir; "t", a U-turn, is left out
TIP_BACK_M = STOP_BACK_M + 1.0      # an arrow's tip: 1 m behind the stop line


def build(con, epsg):
    import duckdb
    import shapely
    from . import sumo

    m = lambda col="geometry": f"ST_AsWKB(ST_Transform({col}, 'EPSG:4326', '{epsg}', always_xy := true))"
    g = lambda w: shapely.make_valid(shapely.from_wkb(bytes(w)))
    to_ll = f"ST_Transform(ST_GeomFromWKB(?), '{epsg}', 'EPSG:4326', always_xy := true)"
    lanes = []      # (unit, oid, direction, lane, width, polygon)
    for u, d, n, ref, w, x in con.execute(f"""SELECT unit_id, direction, lane, ref, width_m, {m()} FROM space.part
                                              WHERE level = 0 AND type = 'lane' AND direction IN ('forward', 'backward')""").fetchall():
        ws = re.findall(r"w(\d+)", ref or "")      # (a lane can run along several OSM ways: one subsection with one cross-section)
        if ws and n:
            lanes.append((u, int(ws[0]), d, int(n), w, g(x), [int(o) for o in ws]))
    inter = [(u, g(x)) for u, x in con.execute(f"SELECT unit_id, {m()} FROM space.unit WHERE level = 0 AND kind = 'intersection'").fetchall()]
    if not lanes or not inter:
        return dict(turns=0, arrows=0)
    # SUMO gets our lane count and width for each direction of a way
    count, width = {}, {}
    for _, o, d, n, w, _, _ in lanes:
        count[(o, d)] = max(count.get((o, d), 0), n)
        width.setdefault((o, d), []).append(w or 3.25)
    try:        # (a network with no duckOSM driving edges or no is_reverse: no moves)
        edges = con.execute("SELECT edge_id::VARCHAR, source, target, osm_id, coalesce(is_reverse, false) FROM osm.driving.edges").fetchall()
    except duckdb.Error:
        return dict(turns=0, arrows=0)
    attrs, way_of = {}, {}
    for e, s_, t_, o, rev in edges:
        d = "backward" if rev else "forward"
        way_of[e] = (o, d, s_, t_)
        if (o, d) in count:
            ws = sorted(width[(o, d)])
            attrs[e] = {"numLanes": count[(o, d)], "width": round(ws[len(ws) // 2], 2)}
    net = sumo.network(con, attrs, epsg)
    if net is None:
        return dict(turns=0, arrows=0)
    # the road element of each SUMO edge (space.element.source_id: one of its two directed duckOSM edges) and its line
    elem, line = {}, {}
    for o, a, b, sid, w in con.execute(f"""SELECT osm_id, src, dst, source_id, {m()} FROM space.element
                                          WHERE type IN ('road', 'walkway') AND level_min IN (0, 1) AND src IS NOT NULL""").fetchall():
        # (level 1 too: a deck with nothing under it is street at level 0, as in network.py: West Broadway at Granville)
        elem[(o, min(a, b), max(a, b))] = sid
        line[(o, a, b)] = g(w)
    key = lambda e: (way_of[e][0], min(way_of[e][2:]), max(way_of[e][2:]))
    elem_of = lambda e: elem.get(key(e), e) if e in way_of else e

    def run_line(e):
        """Edge e's line in the way it runs, or None."""
        o, _, s_, t_ = way_of[e]
        x = line.get((o, s_, t_))
        if x is None and line.get((o, t_, s_)) is not None:
            x = line[(o, t_, s_)].reverse()
        return x if x is not None and x.geom_type == "LineString" else None
    try:
        ring = {o for (o,) in con.execute("SELECT osm_id FROM osm.raw.ways WHERE tags['junction'] IN ('roundabout', 'circular')").fetchall()}
    except duckdb.Error:
        ring = set()
    n_of = {}       # SUMO edge -> its driving lanes
    for e, i, n, _, kind, _ in net["lanes"]:
        if kind == "driving":
            n_of[e] = n_of.get(e, 0) + 1
    jat = {}        # junction node -> our intersection (its index in inter)
    ix = {u: k for k, (u, _) in enumerate(inter)}
    for iid, node in con.execute("SELECT intersection_id, node_id FROM space.junction WHERE level = 0").fetchall():
        if iid in ix:
            jat[node] = ix[iid]
    by_way = {}
    for k, (_, _, d, _, _, _, os_) in enumerate(lanes):
        for o in os_:
            by_way.setdefault((o, d), []).append(k)

    def unit(h):
        d = math.hypot(*h) or 1.0
        return (h[0] / d, h[1] / d)

    def ours(e, i, at_end):
        """Our lane for SUMO lane i (from the right) of edge e where e meets its junction (at_end: e comes in, else e goes out): (lane
        index, junction index, point at the junction's edge, heading in the way the lane runs), or None. The junction is ours at e's node
        (space.junction); the lane is of e's way and direction, on e's side of the junction, numbered as SUMO's (SUMO counts from the
        right, we from the middle of the road)."""
        if e not in way_of or e not in n_of:
            return None
        o, d, s_, t_ = way_of[e]
        j = jat.get(t_ if at_end else s_)
        x_e = run_line(e)
        if j is None or x_e is None:
            return None
        J = inter[j][1]
        near = [k for k in by_way.get((o, d), []) if lanes[k][5].distance(J) < 0.3]
        if not near:
            return None
        ref = x_e.interpolate(max(x_e.length - 8, 0) if at_end else min(8, x_e.length))     # (on e's side of the junction)
        u = lanes[min(near, key=lambda k: lanes[k][5].distance(ref))][0]
        want = n_of[e] - i
        k = min((k for k in near if lanes[k][0] == u), key=lambda k: abs(lanes[k][3] - want))
        x = lanes[k][5]
        edge = x.intersection(J.buffer(0.3))
        if edge.is_empty or edge.area < 0.05:
            return None
        q = edge.centroid           # (the lane's end at the junction's edge)
        back = x.intersection(q.buffer(6.0)).centroid
        if back.is_empty or back.distance(q) < 0.5:        # (a lane piece too small to show its way)
            return None
        h = unit((q.x - back.x, q.y - back.y)) if at_end else unit((back.x - q.x, back.y - q.y))
        return (k, j, (q.x, q.y), h)

    def curve(pa, ha, pb, hb):
        """A quadratic curve from pa (heading ha) to pb (heading hb), its control where the two headings meet (as parts.py)."""
        cr = ha[0] * hb[1] - ha[1] * hb[0]
        dx, dy = pb[0] - pa[0], pb[1] - pa[1]
        u, v = ((dx * hb[1] - dy * hb[0]) / cr, (ha[0] * dy - ha[1] * dx) / cr) if abs(cr) > 0.2 else (-1, -1)
        q = (pa[0] + u * ha[0], pa[1] + u * ha[1]) if u > 0 and v > 0 else ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)
        return shapely.LineString([((1 - t) ** 2 * pa[0] + 2 * (1 - t) * t * q[0] + t * t * pb[0],
                                    (1 - t) ** 2 * pa[1] + 2 * (1 - t) * t * q[1] + t * t * pb[1]) for t in [i / 12 for i in range(13)]])

    cands = []
    for f, fl, t, tl, dr, _, veh in net["conns"]:
        if dr not in WAY:
            continue
        a = ours(f, fl, True)
        b = ours(t, tl, False)
        if a is None or b is None or a[1] != b[1]:      # (both ends at one junction of ours)
            continue
        cands.append([f, fl, t, tl, dr, veh, a, b])
    # at a merge (two or more roads going straight on into one, lane for lane) the lanes keep their order across the road: the
    # leftmost lane coming in goes to the leftmost lane going out. SUMO sorted the roads by the angle of their last piece, which at
    # a shallow merge put the ramp's lanes on the wrong side (Granville Bridge ramp into Fir Street, Kaveh 2026-10-15)
    by_t = {}
    for c_ in cands:
        by_t.setdefault(c_[2], []).append(c_)
    for t, cs in by_t.items():
        if len({c_[0] for c_ in cs}) < 2 or any(c_[4] != "s" for c_ in cs) or len(cs) != n_of.get(t, -1) or len({c_[3] for c_ in cs}) != len(cs):
            continue
        hb = cs[0][7][3]                    # the heading going out; left of it is +
        lat = lambda p: -(p[0]) * hb[1] + (p[1]) * hb[0]
        ins = sorted(cs, key=lambda c_: lat(c_[6][2]))
        outs = [(c_[3], c_[7]) for c_ in sorted(cs, key=lambda c_: lat(c_[7][2]))]
        for c_, (tl_, b_) in zip(ins, outs):
            c_[3], c_[7] = tl_, b_
    turns, marks, comes = [], [], {}    # comes: (from edge, SUMO lane) -> [our lane, junction, entry point, heading, [moves]]
    for f, fl, t, tl, dr, veh, a, b in cands:
        guide = curve(a[2], a[3], b[2], b[3])
        if not inter[a[1]][1].buffer(0.5).contains(guide):       # (a sharp turn in a narrow junction: the curve bulges out of it)
            guide = shapely.LineString([a[2], b[2]])
        iid = inter[a[1]][0]
        turns.append((iid, 0, elem_of(f), fl + 1, elem_of(t), tl + 1, WAY[dr], "sumo", veh, None, shapely.to_wkb(guide)))
        if way_of[f][0] not in ring and way_of[t][0] not in ring:
            marks.append((iid, "guide line", guide, f"w{way_of[f][0]} to w{way_of[t][0]}"))
        comes.setdefault((f, fl), [*a, []])[4].append((WAY[dr], veh))
    approach, done_ = [], {}
    for (f, fl), (k, j, q, h, moves) in comes.items():
        ways = {w for w, veh in moves if veh is None}       # the arrow shows the ways open to all traffic (not a bus-only turn)
        u, x = lanes[k][0], lanes[k][5]
        tip = (q[0] - h[0] * TIP_BACK_M, q[1] - h[1] * TIP_BACK_M)
        shaft = shapely.LineString([(tip[0] - h[0] * ARROW_M, tip[1] - h[1] * ARROW_M), tip])
        why = None
        if not ways:
            why = "for some vehicles only"
        elif not x.buffer(0.3).contains(shaft):
            why = "lane piece under 4 m"
        elif k in done_:        # (two SUMO lanes on one of ours: one arrow, all their ways)
            why = "another arrow in the way"
            done_[k] |= ways
        else:
            done_[k] = set(ways)
        approach.append((inter[j][0], 0, elem_of(f), fl + 1, len(moves), ",".join(sorted(ways)), why is None, why))
    arrows = 0
    for k, ways in done_.items():
        (f, fl), (_, _, q, h, _) = next((key, v) for key, v in comes.items() if v[0] == k)
        tip = (q[0] - h[0] * TIP_BACK_M, q[1] - h[1] * TIP_BACK_M)
        for piece in shapely.get_parts(arrow_shape(tip, h, ways)):
            marks.append((lanes[k][0], "arrow", piece, f"w{lanes[k][1]}"))
        arrows += 1
    if turns:
        con.executemany(f"""INSERT INTO space.turn (unit_id, level, from_edge, from_lane, to_edge, to_lane, turn, source, vehicles, condition, geometry)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {to_ll})""", turns)
    if approach:
        con.executemany("INSERT INTO space.approach (unit_id, level, from_edge, lane, moves, ways, arrow, no_arrow_because) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        approach)
    if marks:
        con.executemany(f"""INSERT INTO space.mark (unit_id, level, type, length_m, width_m, width_source, width_method, source, method, ref, geometry)
                            VALUES (?, 0, ?, ?, ?, 'urbanstyle', 'chosen', 'sumo', 'derived', ?, {to_ll})""",
                        [(u, t, round(x.length, 1), LINE.get(t), rf, shapely.to_wkb(x)) for u, t, x, rf in marks])
    return dict(turns=len(turns), arrows=arrows)
