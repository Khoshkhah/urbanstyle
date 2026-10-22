"""Step 1 of a bridge (docs/notes/bridge-steps.md): the junction nodes, the carriageway pairs, the forks and the branch points of each
bridge level, from the profile.

1. A junction node is an OSM node where three or more road ends meet on the bridge (an axis end that is not on the ground).
2. A carriageway pair: two one-way arms of one junction node that run side by side, within PAIR_M of each other over at least PAIR_MIN_M
   and PAIR_SHARE of the shorter. A pair is one road.
3. A junction node where three or more roads meet (a pair counted once) is a fork; where two meet, the road goes on.
4. The trunk of a fork is the road on the other side of the node from all the others; its branch point is the node. The branch point
   of each other arm is the first metre along it from the node where its cross-section (as wide as its one width) no longer touches
   the decks of the other roads of the fork."""
import math

PAIR_M = 14.0           # two one-way arms this near each other ...
PAIR_MIN_M = 40.0       # ... over at least this ...
PAIR_SHARE = 0.8        # ... and this share of the shorter are a carriageway pair
STEP_M = 1.0            # a branch point is found to this
SPLIT_MAX_M = 200.0     # within this of the node, at most


def _away(ln, k):
    """The unit direction from the node into an arm: its axis's first (k=0) or last (k=1) 2 m, pointing away from the end."""
    a, b = (ln.coords[0], ln.interpolate(min(2.0, ln.length)).coords[0]) if k == 0 else \
        (ln.coords[-1], ln.interpolate(max(ln.length - 2.0, 0.0)).coords[0])
    h = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
    return (b[0] - a[0]) / h, (b[1] - a[1]) / h


def forks(P, axes, a_lv, widths):
    """The points of step 1. axes: [(line, axis)] in the profile's crs; a_lv: {axis id: level}; widths: {axis id: (lo, hi)}, each axis's
    one width in its own frame (left positive). Returns {"nodes": [...], "pairs": [...], "forks": [...]}:
    nodes  [{node, xy, level, arms: [(axis id, end)]}], every junction node;
    pairs  [{node, arms: [(axis id, end), (axis id, end)], together_m}];
    forks  [{node, xy, level, roads: [[(axis id, end), ...]], trunk: [(axis id, end), ...], branch_m: {axis id: metres}}]."""
    import shapely
    from .bridge_surface import _frame
    by_id = {a["id"]: (ln, a) for ln, a in axes}
    one_way = lambda a: len({b.get("direction") for sec in a.get("sections", []) for b in (sec.get("bands") or []) if b.get("type") == "lane"}) == 1
    at = {}
    for ln, a in axes:
        for k, e in enumerate(a.get("ends", [])):
            if e.get("node") and not e.get("ground"):
                at.setdefault(e["node"], []).append((a["id"], k))
    nodes, pairs, out = [], [], []
    for node, arms in at.items():
        if len(arms) < 3:
            continue                                   # (rule 1: three or more road ends)
        ln0, _ = by_id[arms[0][0]]
        xy = ln0.coords[-1] if arms[0][1] else ln0.coords[0]
        lv = a_lv.get(arms[0][0])
        nodes.append({"node": node, "xy": xy, "level": lv, "arms": arms})
        # rule 2: carriageway pairs
        roads = [[x] for x in arms]
        ow = [x for x in arms if one_way(by_id[x[0]][1])]
        for i, A in enumerate(ow):
            for B in ow[i + 1:]:
                lnA, lnB = by_id[A[0]][0], by_id[B[0]][0]
                together = 0.0
                d = 0.0
                while d <= min(lnA.length, lnB.length):
                    pa = lnA.interpolate(lnA.length - d if A[1] else d)
                    if pa.distance(lnB) > PAIR_M:
                        break
                    together = d
                    d += STEP_M
                if together >= PAIR_MIN_M and together >= PAIR_SHARE * min(lnA.length, lnB.length):
                    pairs.append({"node": node, "arms": [A, B], "together_m": round(together, 1)})
                    ra = next(r for r in roads if A in r); rb = next(r for r in roads if B in r)
                    if ra is not rb:
                        ra += rb; roads.remove(rb)
        if len(roads) < 3:
            continue                                   # (rule 3: the road goes on)
        # rule 4: the trunk, then each arm's branch point
        aw = {x: _away(by_id[x[0]][0], x[1]) for x in arms}
        mean = lambda r: (sum(aw[x][0] for x in r) / len(r), sum(aw[x][1] for x in r) / len(r))
        trunk = min(roads, key=lambda r: sum(mean(r)[0] * mean(o)[0] + mean(r)[1] * mean(o)[1] for o in roads if o is not r))

        def strip(aid):
            ln = by_id[aid][0]
            lo, hi = widths[aid]
            return ln.buffer(hi, single_sided=True, cap_style="flat").union(ln.buffer(lo, single_sided=True, cap_style="flat")) \
                if hi > 0 > lo else ln.buffer((hi - lo) / 2, cap_style="flat")
        branch_m = {}
        for r in roads:
            for aid, k in r:
                if r is trunk:
                    branch_m[aid] = 0.0
                    continue
                ln = by_id[aid][0]
                lo, hi = widths[aid]
                others = shapely.union_all([strip(o) for o_r in roads if o_r is not r for o, _ in o_r])
                d = 0.0
                while d < min(ln.length, SPLIT_MAX_M):
                    x, y, nx, ny = _frame(ln, ln.length - d if k else d)
                    if shapely.LineString([(x + nx * lo, y + ny * lo), (x + nx * hi, y + ny * hi)]).distance(others) > 0.0:
                        break
                    d += STEP_M
                branch_m[aid] = round(d, 1)
        out.append({"node": node, "xy": xy, "level": lv, "roads": roads, "trunk": trunk, "branch_m": branch_m})
    return {"nodes": nodes, "pairs": pairs, "forks": out}


_OSM_LINES = {}


def _osm_axis(P, a):
    """An axis's line from OSM itself: its ways' node coordinates in the OSM database the profile was made from, joined end to end. The
    profile's own line is not OSM's: the LiDAR step adds landings past OSM's ends and fits the line (a8: 62 m past its end, a4: 0.6 m
    off), and SUMO's lanes lie on OSM's line (Kaveh, 2026-10-19)."""
    import duckdb
    import pyproj
    import shapely
    import shapely.ops
    src = next((x for x in (P.get("made") or {}).get("inputs", []) if str(x).endswith(".osm.duckdb")), None)
    if src not in _OSM_LINES:
        _OSM_LINES[src] = {}
    cache = _OSM_LINES[src]
    ids = [int(w[1:]) for w in a["ways"]]
    need = [w for w in ids if w not in cache]
    if need:
        o = duckdb.connect(src, read_only=True)
        tr = pyproj.Transformer.from_crs("EPSG:4326", P["crs"], always_xy=True).transform
        rows = o.execute("SELECT osm_id, refs FROM raw.ways WHERE osm_id IN (SELECT unnest(?::BIGINT[]))", [need]).fetchall()
        refs = sorted({r for _, rs in rows for r in rs})
        pts = {i: tr(x, y) for i, y, x in o.execute("SELECT osm_id, lat, lon FROM raw.nodes WHERE osm_id IN (SELECT unnest(?::BIGINT[]))", [refs]).fetchall()}
        for w, rs in rows:
            cache[w] = shapely.LineString([pts[r] for r in rs])
    merged = shapely.line_merge(shapely.MultiLineString([cache[w] for w in ids]))
    ln = merged if merged.geom_type == "LineString" else max(shapely.get_parts(merged), key=lambda g: g.length)
    old = shapely.LineString([q[:2] for q in a["line"]["value"]])        # (the same direction as the profile's axis: its ends and s)
    if shapely.Point(ln.coords[0]).distance(shapely.Point(old.coords[0])) > shapely.Point(ln.coords[-1]).distance(shapely.Point(old.coords[0])):
        ln = shapely.LineString(list(ln.coords)[::-1])
    return ln


def steps_1_3(con, P, gmns=None):
    """Steps 1 to 3 as accepted (docs/notes/bridge-steps.md): step 1's points with its own widths, then the branches and forks with each
    branch's one width from its own step-4 bands (band_widths). Returns (axes, levels, R, B, F)."""
    axes, a_lv, widths, R = step1(con, P)
    B, F = partition(P, axes, a_lv, {**widths, **band_widths(P, axes, R, gmns)}, R)
    return axes, a_lv, R, B, F


def step1(con, P):
    """Step 1 of profile P with the area's database: (axes, levels, widths, the points of forks())."""
    import shapely
    from .bridge_surface import _axis_level, _axis_width, _trim_to_osm
    _trim_to_osm(con, P)
    axes = [(_osm_axis(P, a), a) for a in P["axes"]]
    a_lv = _axis_level(con, P)
    val = lambda v: v["value"] if isinstance(v, dict) else v
    paths = [shapely.LineString([q[:2] for q in val(p["line"])]).buffer((val(p.get("width")) or 2.0) / 2)
             for p in P.get("paths", []) if len(val(p["line"])) >= 2]
    widths = {a["id"]: _axis_width(a, ln, paths, [l2 for l2, b in axes if b["id"] != a["id"]]) for ln, a in axes}
    return axes, a_lv, widths, forks(P, axes, a_lv, widths)


# ---------------------------------------------------------------- steps 2 and 3: branches and forks, centre lines and widths
CLOSE_M = 1.5           # a gap narrower than twice this inside a fork is deck
FORK_TAPER_M = 20.0     # (band_widths: a branch's width is measured from this far into it from a fork, where the shared deck ends)


def _pair_mid(lnA, kA, lnB, kB):
    """The line midway between two carriageways of a pair, from their shared node outward, as long as the shorter one."""
    import shapely
    mids = []
    d = 0.0
    while d <= min(lnA.length, lnB.length):
        pa = lnA.interpolate(lnA.length - d if kA else d)
        pb = lnB.interpolate(lnB.project(pa))
        mids.append(((pa.x + pb.x) / 2, (pa.y + pb.y) / 2))
        d += STEP_M
    return shapely.LineString(mids)


def _extent_exact(line, polys, reach=40.0):
    """(lo, hi): how far the polygons reach to the left (+) and right (-) of the line, from every corner point of them (exact: a width
    measured at stations every 2 m missed the bands' edges between two stations, and they stuck out of the branch as slivers up to 1.1 m
    wide). Only the parts beside the line count (its flat strip, ``reach`` wide on each side), not past its ends."""
    import numpy as np
    import shapely
    from .bridge_surface import _frame
    strip = line.buffer(reach, cap_style="flat")
    pts = [c for g in polys for pg in shapely.get_parts(g.intersection(strip)) if pg.geom_type == "Polygon"
           for ring in [pg.exterior] + list(pg.interiors) for c in ring.coords]
    if not pts:
        return 0.0, 0.0
    ts = []
    for x, y in pts:
        s_ = line.project(shapely.Point(x, y))
        x0, y0, nx, ny = _frame(line, s_)
        ts.append((x - x0) * nx + (y - y0) * ny)
    ts = np.array(ts)
    return float(min(0.0, ts.min())), float(max(0.0, ts.max()))


def _widest_section(line, polys, reach=40.0, step=1.0):
    """(lo, hi) of the widest cross-section of the polygons across the line: at every station (every ``step`` m, and at every corner
    point of the polygons) the reach to the left (+) and right (-) at THAT station; the station with the largest width gives both edges.
    (The widest reach to the left anywhere and to the right anywhere, taken apart, gave b4 27.5 m when no cross-section was wider
    than 22.3 m, and b10 39.5 m against 28.4 m; Kaveh, 2026-10-22: one width, from all the bands.)"""
    import numpy as np
    import shapely
    from .bridge_surface import _frame
    g = shapely.union_all(polys)
    strip = line.buffer(reach, cap_style="flat")
    ss = set(np.arange(0.0, line.length + 0.01, step).tolist())
    for pg in shapely.get_parts(g.intersection(strip)):
        if pg.geom_type == "Polygon":
            for ring in [pg.exterior] + list(pg.interiors):
                for x, y in ring.coords:
                    ss.add(float(line.project(shapely.Point(x, y))))
    best = (0.0, 0.0, 0.0)
    for s_ in sorted(ss):
        x0, y0, nx, ny = _frame(line, s_)
        cut = shapely.LineString([(x0 - nx * reach, y0 - ny * reach), (x0 + nx * reach, y0 + ny * reach)]).intersection(g)
        ts = [(cx - x0) * nx + (cy - y0) * ny for part in shapely.get_parts(cut) for cx, cy in getattr(part, "coords", [])]
        if ts:
            lo, hi = min(0.0, min(ts)), max(0.0, max(ts))
            if hi - lo > best[0]:
                best = (hi - lo, lo, hi)
    return best[1], best[2]


def _extent(line, polys, step=5.0, reach=40.0):
    """(lo, hi): how far the polygons reach to the left (+) and right (-) of the line, over its length."""
    import shapely
    from .bridge_surface import _frame
    lo, hi = 0.0, 0.0
    g = shapely.union_all(polys)
    s = 0.0
    while s <= line.length:
        x, y, nx, ny = _frame(line, s)
        cut = shapely.LineString([(x - nx * reach, y - ny * reach), (x + nx * reach, y + ny * reach)]).intersection(g)
        for part in shapely.get_parts(cut):
            for cx, cy in getattr(part, "coords", []):
                t = (cx - x) * nx + (cy - y) * ny
                lo, hi = min(lo, t), max(hi, t)
        s += step
    return lo, hi


def _side(ln_a, line, lo, hi):
    """The branch's (lo, hi) in an axis's own frame: swapped where the axis runs against the branch's line."""
    import shapely
    m = ln_a.interpolate(0.5, normalized=True)
    s = line.project(m)
    p0, p1 = line.interpolate(max(0.0, s - 1.0)), line.interpolate(min(line.length, s + 1.0))
    q0, q1 = ln_a.interpolate(max(0.0, ln_a.project(m) - 1.0)), ln_a.interpolate(min(ln_a.length, ln_a.project(m) + 1.0))
    same = (p1.x - p0.x) * (q1.x - q0.x) + (p1.y - p0.y) * (q1.y - q0.y) >= 0
    return (lo, hi) if same else (-hi, -lo)


def partition(P, axes, a_lv, widths, R):
    """Steps 2 and 3 (docs/notes/bridge-steps.md) from step 1's points R: the branches and the forks of each bridge level.
    A road unit is an axis, or a carriageway pair (its line midway between the two). Units that meet at a junction node that is not a
    fork (only two roads) are chained into one branch. A branch runs from the branch point at one end to the branch point (or the
    bridge end) at the other; its centre line is its units' lines, smoothed (LINE_SMOOTH_M); its one width covers every unit's width.
    A fork is the deck between its junction node and its arms' branch points: each arm's line there as wide as its branch, the gaps
    narrower than 2 CLOSE_M closed, less the branches.
    Returns (branches, forks): branches [{id, axes, level, line, s0, s1, lo, hi, poly, ends}], forks [{id, node, level, arms, poly}]."""
    import shapely
    import shapely.ops
    from .bridge_surface import _frame
    by_id = {a["id"]: (ln, a) for ln, a in axes}
    fork_of = {f["node"]: f for f in R["forks"]}
    # the road units
    paired = {}
    for pr in R["pairs"]:
        (a1, k1), (a2, k2) = pr["arms"]
        paired[a1] = paired[a2] = pr
    units, seen = [], set()
    for ln, a in axes:
        if a["id"] in seen:
            continue
        if a["id"] in paired:
            pr = paired[a["id"]]
            (a1, k1), (a2, k2) = pr["arms"]
            mid = _pair_mid(by_id[a1][0], k1, by_id[a2][0], k2)          # (from the shared node outward)
            strips = []
            for aid in (a1, a2):
                lo_, hi_ = widths[aid][:2]
                l_ = by_id[aid][0]
                strips.append(l_.buffer(hi_, single_sided=True, cap_style="flat").union(l_.buffer(lo_, single_sided=True, cap_style="flat")))
            lo, hi = _extent(mid, strips)
            far = [e.get("node") for aid in (a1, a2) for k_, e in enumerate(by_id[aid][1]["ends"]) if (aid, k_) not in pr["arms"]]
            units.append({"axes": [a1, a2], "line": mid, "lo": lo, "hi": hi,
                          "ends": [pr["node"], far[0] if far and far[0] and far[0] == far[-1] else None]})
            seen |= {a1, a2}
        else:
            lo, hi = widths[a["id"]][:2]
            units.append({"axes": [a["id"]], "line": ln, "lo": lo, "hi": hi,
                          "ends": [e.get("node") if not e.get("ground") else None for e in a["ends"]]})
            seen.add(a["id"])
    # chain units through the junction nodes that are not forks
    def flip(u):
        return {**u, "line": shapely.LineString(list(u["line"].coords)[::-1]), "lo": -u["hi"], "hi": -u["lo"], "ends": u["ends"][::-1]}
    branches, used = [], set()
    for i, u in enumerate(units):
        if i in used:
            continue
        chain, used_ = [u], {i}
        for side in (1, 0):                                  # grow at the end, then at the start
            while True:
                end_node = chain[-1]["ends"][1] if side else chain[0]["ends"][0]
                if not end_node or end_node in fork_of:
                    break
                nxt = next(((j, v) for j, v in enumerate(units) if j not in used_ and end_node in v["ends"]), None)
                if nxt is None:
                    break
                j, v = nxt
                used_.add(j)
                if side:
                    chain.append(v if v["ends"][0] == end_node else flip(v))
                else:
                    chain.insert(0, v if v["ends"][1] == end_node else flip(v))
        used |= used_
        coords = []
        for v in chain:
            cs = list(v["line"].coords)
            coords += cs if not coords else cs[1:]
        line = shapely.LineString(coords)          # (OSM's own line: no smoothing; Kaveh 2026-10-19, "real geometry from osm as centre line")
        lo, hi = min(v["lo"] for v in chain) - 0.0, max(v["hi"] for v in chain)
        ends = [chain[0]["ends"][0], chain[-1]["ends"][1]]
        ids = [aid for v in chain for aid in v["axes"]]

        def cut_at(node):                                    # the branch point's distance from this fork node, for this branch
            f = fork_of.get(node)
            if not f:
                return 0.0
            return max([f["branch_m"].get(aid, 0.0) for aid in ids if aid in f["branch_m"]] or [0.0])
        s0, s1 = cut_at(ends[0]), cut_at(ends[1])
        # the branch on OSM's lines: each axis from its branch point to its other end; a carriageway pair's two axes each on its own
        # line with its own width (a midway line was 2.8 m from each carriageway), any other axis with the branch's one width
        osm_lines, strips, strip_of = [], [], {}
        for v in chain:
            for aid in v["axes"]:
                ln_a, a_ = by_id[aid]
                c0 = c1 = 0.0
                for k_, e in enumerate(a_["ends"]):
                    f = fork_of.get(e.get("node"))
                    if f and aid in f["branch_m"]:
                        if k_ == 0:
                            c0 = f["branch_m"][aid]
                        else:
                            c1 = f["branch_m"][aid]
                seg = shapely.ops.substring(ln_a, c0, ln_a.length - c1)
                osm_lines.append(seg)
                wd = widths[aid]
                if len(wd) == 3:                                   # one width and one offset (band_widths) about the smooth centre line
                    half = (wd[1] - wd[0]) / 2.0
                    sm = _smooth_axis(ln_a)
                    strip_of[aid] = (sm, wd[2], half)
                    strips.append(_strip_along(sm, wd[2], half, c0, sm.length - c1))
                else:
                    w_lo, w_hi = wd if len(v["axes"]) > 1 else _side(ln_a, line, lo, hi)
                    strip_of[aid] = (ln_a, [(0.0, (w_lo + w_hi) / 2.0), (ln_a.length, (w_lo + w_hi) / 2.0)], (w_hi - w_lo) / 2.0)
                    strips.append(seg.buffer(w_hi, single_sided=True, cap_style="flat").union(seg.buffer(w_lo, single_sided=True, cap_style="flat")))
        poly = shapely.union_all(strips)
        branches.append({"id": f"b{len(branches) + 1}", "axes": ids, "level": a_lv.get(ids[0]), "line": line, "s0": s0, "s1": s1,
                         "lo": lo, "hi": hi, "poly": poly, "ends": ends, "osm_lines": osm_lines, "strip_of": strip_of,
                         "end_axes": (list(chain[0]["axes"]), list(chain[-1]["axes"]))})
    # the forks: each arm's line from the node to its branch point, as wide as its branch
    forks_ = []
    for k_, f in enumerate(R["forks"]):
        parts = []
        arms = []
        # the fork starts at its trunk's full cross-section at the node (Kaveh, 2026-10-20): from there to each other arm's cross-section
        # FORK_TAPER_M along it (its branch point at most), the deck between the two is the fork's, and the arm's own strip begins only
        # there. The trunk's square end met a narrower fork with a step of 6 m and more; an arm's own strip from the node stuck out past
        # the trunk's edge as a spike (f4, a3 beside a9)
        trunk_ids = {aid for aid, _ in f["trunk"]}
        node_pt = shapely.Point(f["xy"])

        def at_end(b, e):
            """The axes of branch b at its end e, each with its station d metres from the node: [(axis id, line, mids, half, s_of(d))]."""
            out_ = []
            for aid in b["end_axes"][e]:
                ln_a, mids, half = b["strip_of"][aid]
                start_at_node = shapely.Point(ln_a.coords[0]).distance(node_pt) <= shapely.Point(ln_a.coords[-1]).distance(node_pt)
                out_.append((aid, ln_a, mids, half, (lambda d, L=ln_a.length, st=start_at_node: d if st else L - d)))
            return out_

        def xsec(b, e, d):
            return [p for aid, ln_a, mids, half, s_of in at_end(b, e) for p in _edges_at(ln_a, mids, half, s_of(d))]
        T = next(((b, e) for b in branches for e, nd in enumerate(b["ends"]) if nd == f["node"] and trunk_ids & set(b["axes"])), None)
        for b in branches:
            for e, node in enumerate(b["ends"]):
                if node != f["node"]:
                    continue
                arms.append(b["id"])
                s_cut = b["s0"] if e == 0 else b["s1"]
                L = b["line"].length
                # the fork is one straight-sided piece from the trunk's cross-section at the node to each arm's cross-section at its branch
                # point (Kaveh, 2026-10-22): a taper over FORK_TAPER_M and then the arm's own strip swelled out at the node where the
                # arms' two strips lie wider than the trunk (the south fork, a4 + a9 against a1) and bulged where they lie narrower
                if T is not None and b is not T[0]:
                    parts.append(shapely.MultiPoint(xsec(T[0], T[1], 0.0) + xsec(b, e, max(s_cut, 0.5))).convex_hull)
                elif T is None:
                    for aid, ln_a, mids, half, s_of in at_end(b, e):
                        sa, sb = sorted((s_of(0.0), s_of(max(s_cut, 0.5))))
                        parts.append(_strip_along(ln_a, mids, half, sa, sb))
        g = shapely.union_all(parts)
        g = g.buffer(CLOSE_M, join_style="round").buffer(-CLOSE_M, join_style="round").union(g)
        g = g.difference(shapely.union_all([b["poly"] for b in branches if b["level"] == f["level"]]))
        forks_.append({"id": f"f{k_ + 1}", "node": f["node"], "level": f["level"], "arms": arms, "poly": g})
    return branches, forks_


# ---------------------------------------------------------------- the 2D dashboard of steps 1 to 4
COLOURS = ["#1e88e5", "#43a047", "#fb8c00", "#8e24aa", "#00897b", "#e53935", "#6d4c41", "#3949ab", "#c0ca33", "#d81b60", "#00acc1", "#7cb342"]


def dashboard(con, P, out, old=None, gmns=None):
    """Steps 1 to 4 of a bridge on one 2D page (docs/notes/bridge-steps.md, step 4b): a layer for each step, each can be ticked off.
    Step 1: the junction nodes, the carriageway pairs, the branch points. Step 2: the branches and the forks. Step 3: each branch's
    centre line and one width. Step 4: the bands (lanes, paths, barriers, paint) from bridge_cover.layout. Tables of the forks and the
    branches. Drag to move, wheel to zoom, hover for the facts; ?n=<node>&w=<metres> opens the page at a junction node."""
    import html as _html
    import shapely
    import shapely.ops
    from .bridge_cover import COLOURS as COVER, layout
    from .bridge_surface import _frame
    axes, a_lv, widths, R = step1(con, P)
    B, F = partition(P, axes, a_lv, {**widths, **band_widths(P, axes, R, gmns)}, R)   # (step 1's branch points keep step 1's widths)
    S4 = step4(P, axes, B, F, gmns=gmns)
    by_id = {a["id"]: (ln, a) for ln, a in axes}
    allg = shapely.union_all([b["poly"] for b in B] + [ln.buffer(30) for ln, _ in axes])
    x0, y0, x1, y1 = allg.bounds
    X, Y = (lambda x: x - x0), (lambda y: y1 - y)
    ring = lambda r: "M" + " L".join(f"{X(x):.2f},{Y(y):.2f}" for x, y in r.coords) + " Z"
    poly_d = lambda g: " ".join(ring(pg.exterior) + "".join(ring(r) for r in pg.interiors) for pg in shapely.get_parts(g) if pg.geom_type == "Polygon")
    line_d = lambda ln: "M" + " L".join(f"{X(x):.2f},{Y(y):.2f}" for x, y in ln.coords)
    esc = _html.escape
    L = {k: [] for k in ("osm", "s4", "s2", "s3", "s1", "gm", "old", "pa", "s3b")}
    for lv, g_ in step3b(B, F, S4["bands"]).items():
        L["s3b"].append(f'<path d="{poly_d(g_)}" fill="#fff59d" fill-opacity="0.35" stroke="#f57f17" stroke-width="2" vector-effect="non-scaling-stroke">'
                        f'<title>step 3b: the smooth outline of level {lv}</title></path>')
        for x, y in jogs(g_):
            L["s3b"].append(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="2" fill="#d50000"><title>a jog left in the smooth outline</title></circle>')
    # the walking and cycling ways on the bridge (OSM, each along its own line; its width OSM's or urbanstyle's 2 m), and the crossings
    from .bridge_surface import _path_bands
    crossing_ = lambda q: q.get("footway") == "crossing" or q.get("cycleway") == "crossing" or bool(q.get("crossing"))
    pb_, pj_ = _path_bands(dict(P, paths=[q for q in P.get("paths", []) if not crossing_(q)]), axes)
    for b_ in pb_:
        c_ = "#2e8b57" if b_["kind"] == "cycle lane" else "#c8b48a"
        L["pa"].append(f'<path d="{poly_d(b_["line"].buffer(b_["width"] / 2, cap_style="flat"))}" fill="{c_}" fill-opacity="0.8" stroke="#fff" stroke-width="1" '
                       f'vector-effect="non-scaling-stroke"><title>{b_["kind"]} (OSM way {b_["way"]}), {b_["width"]:.1f} m, beside {b_["axis"]} ({b_["side"]})</title></path>')
    for jt in pj_:
        L["pa"].append(f'<circle cx="{X(jt["at"][0]):.1f}" cy="{Y(jt["at"][1]):.1f}" r="1.2" fill="#6d4c41"><title>{jt["why"]}</title></circle>')
    for q in P.get("paths", []):
        if crossing_(q):
            ql = shapely.LineString([v[:2] for v in (q["line"]["value"] if isinstance(q["line"], dict) else q["line"])])
            L["pa"].append(f'<path d="{line_d(ql)}" fill="none" stroke="#fff" stroke-width="4" stroke-dasharray="2 2" vector-effect="non-scaling-stroke">'
                           f'<title>crossing (OSM way {q.get("way")})</title></path>')
    if old:             # the old model (bridge3d.json: metres about its origin in Web Mercator scaled to true metres) in plan, for comparison
        import json as _json
        import pyproj as _pp
        OLDC = {"lane forward": "#555", "lane backward": "#777", "sidewalk": "#d9cfb8", "cycle lane": "#2e8b57", "barrier": "#c0392b",
                "barrier median": "#e67e22", "railing": "#8e24aa", "mark lane line": "#fff", "mark edge line": "#ffd700", "mark arrow": "#fff",
                "mark zebra": "#fff", "junction lane": "#666"}
        to_m = _pp.Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True).transform
        to_p = _pp.Transformer.from_crs("EPSG:3857", P["crs"], always_xy=True).transform
        for M in _json.load(open(old)):
            if M.get("name") != P["name"]:
                continue
            mx0, my0 = to_m(*M["origin"])
            kk = math.cos(math.radians(M["origin"][1]))
            loc = lambda v: to_p(v[0] / kk + mx0, v[1] / kk + my0)
            V = [loc(v) for v in M["verts"]]
            L["old"].append(f'<path d="{" ".join("M" + " L".join(f"{X(V[i][0]):.2f},{Y(V[i][1]):.2f}" for i in f) + " Z" for f in M["deck"])}" '
                            f'fill="#cfd8dc" stroke="none"/>')
            for sf in M.get("surf", []):
                if sf["key"] not in OLDC or str((sf.get("props") or {}).get("id", "")).startswith("parapet"):
                    continue
                Vs = [loc(v) for v in sf["v"]]
                d_ = " ".join("M" + " L".join(f"{X(Vs[i][0]):.2f},{Y(Vs[i][1]):.2f}" for i in f) + " Z" for f in sf["f"])
                L["old"].append(f'<path d="{d_}" fill="{OLDC[sf["key"]]}" stroke="none"><title>old model: {esc(sf["key"])}</title></path>')
    # SUMO's own geometry, from duckOSM's GMNS export: each lane (geom_cut, cut where SUMO's junction begins) and each lane-to-lane
    # connector through a junction (no U-turn), with its width; the profile's lanes that GMNS does not have are listed
    import duckdb
    import pyproj
    import shapely.ops
    gpath = gmns or next((x for x in (P.get("made") or {}).get("inputs", []) if str(x).endswith(".gmns.duckdb")), None)   # (the same GMNS as step 4)
    lids = sorted({b["lane_id"] for _, a in axes for sc in a["sections"] for b in (sc.get("bands") or []) if b.get("lane_id")})
    missing = []
    if gpath:
        g = duckdb.connect(gpath, read_only=True)
        g.execute("LOAD spatial")
        tr = pyproj.Transformer.from_crs("EPSG:4326", P["crs"], always_xy=True).transform
        got = {}
        ways = sorted({int(w[1:]) for _, a in axes for w in a["ways"]})
        rows = g.execute("SELECT n.lane_id, n.width, ST_AsText(coalesce(n.geom_cut, n.geom)) FROM gmns_driving.lane n JOIN gmns_driving.link l "
                         "USING (link_id) WHERE l.osm_id IN (SELECT unnest(?::BIGINT[])) AND n.geom IS NOT NULL", [ways]).fetchall()
        sumo_ids = [r[0] for r in rows]
        for lid, w, wkt in rows:
            ln = shapely.ops.transform(tr, shapely.from_wkt(wkt))
            got[lid] = 1
            L["gm"].append(f'<path d="{poly_d(ln.buffer((w or 3.25) / 2, cap_style="flat"))}" fill="#00838f" fill-opacity="0.35" stroke="#fff" '
                           f'stroke-width="1.5" vector-effect="non-scaling-stroke"><title>GMNS lane {lid} ({w} m)</title></path>')
        missing = []                                        # (every lane is SUMO's own now: the bridge ways' lanes in GMNS)
        lids = sumo_ids
        from .bridge_cover import _turn
        for cid, fl, tl, w, wkt in g.execute("SELECT connector_id, from_lane_id, to_lane_id, width, ST_AsText(geom) FROM gmns_driving.lane_connector "
                                             "WHERE from_lane_id IN (SELECT unnest(?::VARCHAR[])) AND to_lane_id IN (SELECT unnest(?::VARCHAR[])) "
                                             "AND geom IS NOT NULL", [lids, lids]).fetchall():
            cl = shapely.ops.transform(tr, shapely.from_wkt(wkt))
            if len(cl.coords) < 2 or _turn(cl) > 90.0:
                continue
            L["gm"].append(f'<path d="{poly_d(cl.buffer((w or 3.25) / 2, cap_style="flat"))}" fill="#f9a825" fill-opacity="0.35" stroke="#f57f17" '
                           f'stroke-width="0.8" vector-effect="non-scaling-stroke"><title>SUMO connector {fl} &gt; {tl}</title></path>')
            L["gm"].append(f'<path d="{line_d(cl)}" fill="none" stroke="#e65100" stroke-width="1.2" vector-effect="non-scaling-stroke"/>')
    for ln, a in axes:
        L["osm"].append(f'<path d="{line_d(ln)}" fill="none" stroke="#37474f" stroke-width="1" stroke-dasharray="4 3" vector-effect="non-scaling-stroke">'
                        f'<title>OSM axis {a["id"]}: {esc(", ".join(a["ways"]))}</title></path>')
    C4 = {"lane": "#5f6b70", "connector": "#f0b05a", "sidewalk": "#c8b48a", "cycle lane": "#2e8b57", "path joint": "#8d6e63", "path link": "#a1887f", "crossing": "#ffffff"}
    everything = shapely.union_all([b["poly"] for b in B] + [f["poly"] for f in F])
    for kind in ("sidewalk", "cycle lane", "path joint", "path link", "lane", "connector", "crossing"):
        for b_ in S4["bands"]:
            if b_["kind"] != kind:
                continue
            tip = esc(f"{kind} in {b_['home']}: " + " ".join(f"{k}={v}" for k, v in b_["props"].items() if k != "source") + f" ({b_['props'].get('source')})")
            op = ' fill-opacity="0.8"' if kind in ("connector", "crossing") else ""
            L["s4"].append(f'<path d="{poly_d(b_["poly"])}" fill="{C4[kind]}"{op} stroke="#fff" stroke-width="0.6" vector-effect="non-scaling-stroke"><title>{tip}</title></path>')
    for i, area in S4["outside"]:
        g_ = S4["bands"][i]["poly"].difference(everything)
        L["s4"].append(f'<path d="{poly_d(g_)}" fill="#e53935" fill-opacity="0.85"><title>outside every branch and fork: {area} m2 of this '
                       f'{S4["bands"][i]["kind"]}</title></path>')
    for k_, b in enumerate(B):
        c = COLOURS[k_ % len(COLOURS)]
        L["s2"].append(f'<path d="{poly_d(b["poly"])}" fill="{c}" fill-opacity="0.35" stroke="{c}" stroke-width="1.5" vector-effect="non-scaling-stroke">'
                       f'<title>branch {b["id"]}: {"+".join(b["axes"])}, {b["line"].length - b["s0"] - b["s1"]:.0f} m, one width {b["hi"] - b["lo"]:.1f} m</title></path>')
        m = b["line"].interpolate((b["s0"] + b["line"].length - b["s1"]) / 2)
        L["s2"].append(f'<text x="{X(m.x):.1f}" y="{Y(m.y):.1f}" font-size="7" font-weight="bold" fill="{c}" stroke="#fff" stroke-width="1.2" paint-order="stroke">{b["id"]}</text>')
        for ol in b["osm_lines"]:
            L["s3"].append(f'<path d="{line_d(ol)}" fill="none" stroke="{c}" stroke-width="2.5" vector-effect="non-scaling-stroke"><title>centre line of {b["id"]}: '
                           f'OSM\'s own line</title></path>')
        L["s3"].append(f'<path d="{poly_d(b["poly"])}" fill="none" stroke="{c}" stroke-width="1" stroke-dasharray="6 3" vector-effect="non-scaling-stroke"/>')
    for f in F:
        L["s2"].append(f'<path d="{poly_d(f["poly"])}" fill="#ff7043" fill-opacity="0.45" stroke="#bf360c" stroke-width="1.5" vector-effect="non-scaling-stroke">'
                       f'<title>fork {f["id"]} at {f["node"]}: arms {", ".join(f["arms"])}</title></path>')
    for pr in R["pairs"]:
        for aid, _ in pr["arms"]:
            L["s1"].append(f'<path d="{line_d(by_id[aid][0])}" fill="none" stroke="#8e24aa" stroke-width="3" stroke-opacity="0.7" vector-effect="non-scaling-stroke">'
                           f'<title>carriageway pair {pr["arms"][0][0]} + {pr["arms"][1][0]}: together {pr["together_m"]} m</title></path>')
    fork_nodes = {f["node"]: f for f in R["forks"]}
    for nd in R["nodes"]:
        x, y = nd["xy"]
        fk = nd["node"] in fork_nodes
        L["s1"].append(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="3" fill="none" stroke="{"#d32f2f" if fk else "#9e9e9e"}" stroke-width="2.5" vector-effect="non-scaling-stroke">'
                       f'<title>{nd["node"]}</title></circle>')
    for k_, f in enumerate(R["forks"]):
        x, y = f["xy"]
        L["s1"].append(f'<text x="{X(x) + 5:.1f}" y="{Y(y) - 5:.1f}" font-size="6" fill="#d32f2f" font-weight="bold" stroke="#fff" stroke-width="1" paint-order="stroke">'
                       f'f{k_ + 1} (trunk {"+".join(i for i, _ in f["trunk"])})</text>')
        for r in f["roads"]:
            if r is f["trunk"]:
                continue
            for aid, k in r:
                d = f["branch_m"][aid]
                ln = by_id[aid][0]
                lo, hi = widths[aid]
                bx, by_, nx, ny = _frame(ln, ln.length - d if k else d)
                bar = shapely.LineString([(bx + nx * (lo - 1), by_ + ny * (lo - 1)), (bx + nx * (hi + 1), by_ + ny * (hi + 1))])
                L["s1"].append(f'<path d="{line_d(bar)}" stroke="#000" stroke-width="3" vector-effect="non-scaling-stroke"><title>branch point of {aid}: '
                               f'{d:.0f} m from {f["node"]}</title></path>')
    names = {"osm": "OSM axes", "s1": "step 1: junction nodes, pairs, branch points", "s2": "step 2: branches and forks",
             "s3": "step 3: centre lines and widths", "s3b": "step 3b: the smooth outline (red dot: a jog left)", "s4": f"step 4: the bands: SUMO's lanes (grey) and connectors (orange), OSM's paths; red: outside every branch and fork ({len(S4['outside'])})",
             "gm": "SUMO's lanes (teal) and connectors (orange), from GMNS", "old": "the old model (bridge3d)",
             "pa": "sidewalks (beige) and cycleways (green) from OSM, crossings (white dashes)"}
    boxes = "".join(f'<label><input type="checkbox" checked data-g="{k}"> {names[k]}</label><br>' for k in ("old", "gm", "pa", "s4", "s3b", "s2", "s3", "s1", "osm"))
    frows = "".join(f"<tr><td>{f['id']}</td><td>{f['node']}</td><td>{', '.join(f['arms'])}</td></tr>" for f in F)
    brows = "".join(f"<tr><td>{b['id']}</td><td>{'+'.join(b['axes'])}</td><td>{b['line'].length - b['s0'] - b['s1']:.0f} m</td><td>{b['hi'] - b['lo']:.1f} m</td></tr>" for b in B)
    groups = "".join(f'<g id="{k}">{"".join(L[k])}</g>' for k in ("old", "s3b", "s4", "s2", "s3", "pa", "gm", "osm", "s1"))
    page_ = f"""<!doctype html><html><head><meta charset="utf-8"><title>Bridge 2D: {esc(P['name'])}</title>
<style>html,body{{margin:0;height:100%;background:#fafaf5;font-family:sans-serif}}svg{{width:100%;height:100%;cursor:grab}}
#k{{position:absolute;left:10px;top:8px;background:#fff;padding:8px 12px;border-radius:6px;box-shadow:0 1px 4px #0003;font-size:12px;max-height:95vh;max-width:430px;overflow:auto}}
#k.min .more{{display:none}} #fold{{float:right;cursor:pointer;border:1px solid #ccc;border-radius:4px;padding:0 6px;margin-left:8px;background:#f5f5f5}}
#k table{{border-collapse:collapse;margin:4px 0 8px}}#k td,#k th{{border-top:1px solid #ddd;padding:1px 6px;text-align:left}}</style></head><body>
<div id="k" class="min"><span id="fold" title="show or hide the tables">tables</span><b>{esc(P['name'])}: steps 1 to 4 in 2D</b> <small>(docs/notes/bridge-steps.md)</small><br>{boxes}<div class="more">
<small>SUMO's lanes on the bridge's OSM ways: {len(lids)} (GMNS, {esc(str(gpath))})</small><br>
<b>Forks</b><table><tr><th>fork</th><th>node</th><th>branches</th></tr>{frows}</table>
<b>Branches</b><table><tr><th>branch</th><th>axes</th><th>length</th><th>one width</th></tr>{brows}</table>
</div><small>drag: move &middot; wheel: zoom &middot; hover: the facts</small></div>
<svg id="s" viewBox="0 0 {x1 - x0:.1f} {y1 - y0:.1f}" xmlns="http://www.w3.org/2000/svg">{groups}</svg>
<script>const s=document.getElementById('s');let v=s.viewBox.baseVal,d=null;
document.getElementById('fold').onclick=()=>document.getElementById('k').classList.toggle('min');
document.querySelectorAll('#k input').forEach(i=>i.onchange=()=>document.getElementById(i.dataset.g).style.display=i.checked?'':'none');
s.onmousedown=e=>{{d={{x:e.clientX,y:e.clientY}}}};window.onmouseup=()=>{{d=null}};
window.onmousemove=e=>{{if(!d)return;const k=v.width/s.clientWidth;v.x-=(e.clientX-d.x)*k;v.y-=(e.clientY-d.y)*k;d={{x:e.clientX,y:e.clientY}}}};
s.onwheel=e=>{{e.preventDefault();const f=Math.exp(e.deltaY*0.0015),r=s.getBoundingClientRect(),px=v.x+(e.clientX-r.left)/r.width*v.width,py=v.y+(e.clientY-r.top)/r.height*v.height;
v.width*=f;v.height*=f;v.x=px-(px-v.x)*f;v.y=py-(py-v.y)*f}};
const q=new URLSearchParams(location.search);if(q.get('n')){{const c=[...document.querySelectorAll('circle')].find(c=>c.textContent===q.get('n'));
if(c){{const w=+(q.get('w')||120);v.x=+c.getAttribute('cx')-w/2;v.y=+c.getAttribute('cy')-w*0.375;v.width=w;v.height=w*0.75}}}}
if(q.get('off'))q.get('off').split(',').forEach(g=>{{const i=document.querySelector(`#k input[data-g="${{g}}"]`);if(i){{i.checked=false;i.onchange()}}}});</script></body></html>"""
    with open(out, "w") as f_:
        f_.write(page_)
    return R, B, F


# ---------------------------------------------------------------- the frozen result of steps 1 to 3
def snapshot(R, B, F):
    """Steps 1 to 3 as plain data, to freeze them (docs/notes/bridge-steps.md, "How a step is frozen"): the junction nodes, the
    carriageway pairs, the forks with their trunk and branch points, and the branches with their axes, ends, cuts, widths, lines and
    areas; the forks' areas. Coordinates and metres rounded to 1 cm."""
    r2 = lambda v: round(float(v), 2)
    return {
        "nodes": sorted(n["node"] for n in R["nodes"]),
        "pairs": sorted([[list(a) for a in p["arms"]], r2(p["together_m"])] for p in R["pairs"]),
        "forks": [{"node": f["node"], "trunk": [list(a) for a in f["trunk"]], "branch_m": {k: r2(v) for k, v in sorted(f["branch_m"].items())}}
                  for f in sorted(R["forks"], key=lambda f: f["node"])],
        "branches": [{"id": b["id"], "axes": b["axes"], "ends": b["ends"], "s0": r2(b["s0"]), "s1": r2(b["s1"]), "lo": r2(b["lo"]), "hi": r2(b["hi"]),
                      "line": [[r2(x), r2(y)] for x, y in b["line"].coords], "area_m2": r2(b["poly"].area)} for b in B],
        "fork_areas": {f["node"]: r2(f["poly"].area) for f in F},
    }


# ---------------------------------------------------------------- step 4: the bands, from SUMO and OSM
STICK_OUT_M2 = 1.0      # a band piece outside every branch and fork larger than this is listed (a check)


def bands(P, axes, gmns=None):
    """The bands of step 4 without their homes (step4)."""
    return step4(P, axes, None, None, gmns=gmns)["bands"]


LINK_M = 12.0           # a path piece shorter than this ...
LINK_DEG = 30.0         # ... at more than this to its axis is a link between two paths (a sidewalk to the cycle path), not a band


def _is_link(line, axis):
    """A short path piece that runs across its axis: a link inside the pedestrian realm. It is not a band of the branch's width (step 3),
    so it makes no bump in the outline; the cover draws it inside the realm (step 6)."""
    import math
    if line.length >= LINK_M:
        return False
    s = axis.project(line.interpolate(0.5, normalized=True))
    p, q = axis.interpolate(max(0.0, s - 2.0)), axis.interpolate(min(axis.length, s + 2.0))
    (x0, y0), (x1, y1) = line.coords[0], line.coords[-1]
    a = math.degrees(abs(math.atan2(x1 - x0, y1 - y0) - math.atan2(q.x - p.x, q.y - p.y))) % 180.0
    return min(a, 180.0 - a) > LINK_DEG


BESIDE_M = 3.0          # a path counts in a branch's width where its edge is within this of the branch's lanes


def band_widths(P, axes, R, gmns=None, edge=0.5):
    """Step 3's one width of each axis from its own step-4 bands (Kaveh, 2026-10-20): the lanes SUMO makes on its OSM ways and the path
    bands OSM gives it, measured across its OSM line along its body (from its branch point at a fork, step 1's R, to its other end: inside
    a fork the line runs through the shared deck and the other road's sidewalk lay 15 to 18 m from it), plus ``edge`` on each side.
    {axis id: (lo, hi)}, left positive."""
    import shapely
    import shapely.ops
    bs = bands(P, axes, gmns)
    cut = {}
    for f in R["forks"]:
        for r in f["roads"]:
            for aid, k in r:
                cut[(aid, k)] = f["branch_m"].get(aid, 0.0)
    out = {}
    for ln0, a in axes:
        # (from the taper's end at a fork, FORK_TAPER_M, not from the branch point: the arm's strip inside the fork has this width too, and
        # a sidewalk beside a4 inside f1 stuck out of it by 0.7 m over 48 m; nearer the node the line runs through the shared deck)
        c0, c1 = (min(FORK_TAPER_M, cut[(a["id"], k)]) if (a["id"], k) in cut else 0.0 for k in (0, 1))
        ln = shapely.ops.substring(ln0, c0, ln0.length - c1) if ln0.length - c0 - c1 > 2.0 else ln0
        ways = set(a["ways"])
        lanes = [b_["poly"] for b_ in bs if b_["kind"] == "lane" and b_["props"]["osm"] in ways]
        if not lanes:
            continue
        # a path counts only over the stretch where it runs beside the lanes, its edge within BESIDE_M of them (Kaveh, 2026-10-20):
        # where it leaves the road (a sidewalk that turns away at a ramp) it is not this branch's width
        # ... or within BESIDE_M of a path that already counts (a sidewalk behind the cycle path, a1: 6.7 m from the lanes, 0.5 m from the
        # cycle path; Kaveh 2026-10-20). Repeated until no path is added.
        # (a path is measured against the lanes and the OTHER paths' counted pieces: against its own, it went on counting metre by metre)
        lane_g = shapely.union_all(lanes)
        paths = [b_ for b_ in bs if b_["kind"] in ("sidewalk", "cycle lane") and b_["props"].get("axis") == a["id"]]
        got = {}                                           # path index -> its counted piece
        while True:
            added = False
            for k, b_ in enumerate(paths):
                w_ = float(b_["props"].get("width_m") or 2.0)
                near = shapely.union_all([lane_g] + [g for k2, g in got.items() if k2 != k])
                beside = b_["line"].intersection(near.buffer(BESIDE_M + w_ / 2))
                if beside.is_empty or beside.length <= 0.5:
                    continue
                piece = beside.buffer(w_ / 2, cap_style="flat")
                if k in got and piece.area <= got[k].area + 0.5:
                    continue
                got[k] = piece
                added = True
            if not added:
                break
        own = list(lanes) + list(got.values())
        half, off = _one_width(ln, own)
        mids = [(0.0, off), (ln0.length, off)]                         # (one offset along the whole line)
        out[a["id"]] = (round(-half - edge, 2), round(half + edge, 2), mids)
    return out


MID_SMOOTH_M = 20.0     # the strip's middle follows the bands' middle, averaged over this (no kink where a path begins or ends)


def _one_width(line, polys, reach=40.0, step=1.0):
    """One width and one offset for an axis, from all its bands (Kaveh, 2026-10-22): at every station along the line, the bands' reach to
    the left (+) and right (-); the offset is the middle of the overall reach, the half width holds every band from there. Returns
    (half, offset). A strip centred on the line itself was wider than any cross-section (b4 27.5 m for 22.3 m; b10 39.5 m for 28.4 m);
    a middle that followed the bands wandered where a path began or ended."""
    import numpy as np
    import shapely
    from .bridge_surface import _frame
    g = shapely.union_all(polys)
    ss = np.arange(0.0, line.length + 0.01, step)
    lo, hi = [], []
    for s_ in ss:
        x0, y0, nx, ny = _frame(line, float(s_))
        cut = shapely.LineString([(x0 - nx * reach, y0 - ny * reach), (x0 + nx * reach, y0 + ny * reach)]).intersection(g)
        ts = [(cx - x0) * nx + (cy - y0) * ny for part in shapely.get_parts(cut) for cx, cy in getattr(part, "coords", [])]
        lo.append(min(ts) if ts else np.nan)
        hi.append(max(ts) if ts else np.nan)
    lo, hi = np.array(lo), np.array(hi)
    have = ~np.isnan(lo)
    if not have.any():
        return 0.0, [(0.0, 0.0), (float(line.length), 0.0)]
    # where no band is (past the lanes' end), the nearest station with one
    idx = np.where(have)[0]
    lo = np.interp(np.arange(len(ss)), idx, lo[idx]); hi = np.interp(np.arange(len(ss)), idx, hi[idx])
    # one width and ONE offset (Kaveh, 2026-10-22: the edges are parallel offsets of the smooth centre line, no wandering where a path
    # begins or ends): the offset is the middle of the bands' overall reach, the half width what holds every band from there
    off = float((lo.min() + hi.max()) / 2.0)
    half = float(max(hi.max() - off, off - lo.min()))
    return half, round(off, 3)


CENTRE_SMOOTH_M = 20.0  # a branch's centre line: OSM's line averaged over this (step 3b; no kink at an OSM point)


def _smooth_axis(line):
    """The smooth centre line of an axis (Kaveh, 2026-10-22): OSM's line resampled every metre, each point the mean of the line within
    CENTRE_SMOOTH_M / 2 on each side; the window shrinks to nothing at the ends, so they stay where OSM puts them."""
    import numpy as np
    import shapely
    L = line.length
    if L < 4.0:
        return line
    ss = np.linspace(0.0, L, int(L) + 1)
    pts = np.array([line.interpolate(float(v)).coords[0] for v in ss])
    w = int(CENTRE_SMOOTH_M / 2)
    out = pts.copy()
    for k in range(len(pts)):
        r = min(w, k, len(pts) - 1 - k)
        if r > 0:
            out[k] = pts[k - r:k + r + 1].mean(axis=0)
    return shapely.LineString(out)


def _strip_along(line, mids, half, s0=None, s1=None, step=1.0):
    """The strip of one width 2 ``half`` about the middle line m(s) (``mids``: [(s, m)] on ``line``), from s0 to s1 (the whole line
    when not given), square ends."""
    import numpy as np
    import shapely
    from .bridge_surface import _frame
    s0 = 0.0 if s0 is None else max(0.0, s0)
    s1 = line.length if s1 is None else min(line.length, s1)
    if s1 - s0 < 0.1:
        return shapely.Polygon()
    xs = [p[0] for p in mids]; ys = [p[1] for p in mids]
    left, right = [], []
    for s_ in list(np.arange(s0, s1, step)) + [s1]:
        m = float(np.interp(s_, xs, ys))
        x0, y0, nx, ny = _frame(line, float(s_))
        left.append((x0 + nx * (m + half), y0 + ny * (m + half)))
        right.append((x0 + nx * (m - half), y0 + ny * (m - half)))
    return shapely.make_valid(shapely.Polygon(left + right[::-1])).buffer(0)


def _edges_at(line, mids, half, s_):
    """The strip's left and right edge points at station s_."""
    import numpy as np
    from .bridge_surface import _frame
    m = float(np.interp(s_, [p[0] for p in mids], [p[1] for p in mids]))
    x0, y0, nx, ny = _frame(line, float(s_))
    return [(x0 + nx * (m + half), y0 + ny * (m + half)), (x0 + nx * (m - half), y0 + ny * (m - half))]


def step4(P, axes, B, F, gmns=None):
    """Step 4 (docs/notes/bridge-steps.md): the bands of the bridge, from the sources only. Lanes: SUMO's lane lines (GMNS lane.geom_cut,
    else geom) as wide as their width, on the bridge's OSM ways. Connectors: SUMO's paths from lane to lane through a junction
    (lane_connector), none that turns back. Paths: OSM's sidewalks, cycleways and shared paths (bridge_surface._path_bands, joined where
    OSM joins them) and OSM's crossings. Each band is given to the branch or fork that holds most of it; the pieces that lie outside every
    branch and fork are listed. gmns: the GMNS database (default: the profile's input).
    Returns {"bands": [{kind, poly, line, props, home}], "outside": [(band index, area m2)]}."""
    import duckdb
    import pyproj
    import shapely
    import shapely.ops
    from .bridge_cover import _turn
    from .bridge_surface import _path_bands
    gpath = gmns or next((x for x in (P.get("made") or {}).get("inputs", []) if str(x).endswith(".gmns.duckdb")), None)
    g = duckdb.connect(gpath, read_only=True)
    g.execute("LOAD spatial")
    tr = pyproj.Transformer.from_crs("EPSG:4326", P["crs"], always_xy=True).transform
    ways = sorted({int(w[1:]) for _, a in axes for w in a["ways"]})
    bands = []
    rows = g.execute("""SELECT n.lane_id, n.link_id, l.osm_id, n.lane_num, n.allowed_uses, n.width, n.turn, ST_AsText(coalesce(n.geom_cut, n.geom))
                        FROM gmns_driving.lane n JOIN gmns_driving.link l USING (link_id)
                        WHERE l.osm_id IN (SELECT unnest(?::BIGINT[])) AND coalesce(n.geom_cut, n.geom) IS NOT NULL""", [ways]).fetchall()
    lids = [r[0] for r in rows]
    for lid, lk, osm, num, use, w, turn, wkt in rows:
        ln = shapely.ops.transform(tr, shapely.from_wkt(wkt))
        w = float(w or 3.25)
        bands.append({"kind": "lane", "line": ln, "poly": ln.buffer(w / 2, cap_style="flat"),
                      "props": {"lane_id": lid, "link_id": lk, "osm": f"w{osm}", "lane": num, "use": use, "width_m": w, "turn": turn,
                                "source": "SUMO via duckOSM GMNS (lane.geom_cut)"}})
    for cid, fl, tl, w, wkt in g.execute("""SELECT connector_id, from_lane_id, to_lane_id, width, ST_AsText(geom) FROM gmns_driving.lane_connector
                                            WHERE from_lane_id IN (SELECT unnest(?::VARCHAR[])) AND to_lane_id IN (SELECT unnest(?::VARCHAR[]))
                                            AND geom IS NOT NULL""", [lids, lids]).fetchall():
        ln = shapely.ops.transform(tr, shapely.from_wkt(wkt))
        if len(ln.coords) < 2 or ln.length < 0.05 or _turn(ln) > 90.0:
            continue
        w = float(w or 3.25)
        bands.append({"kind": "connector", "line": ln, "poly": ln.buffer(w / 2, cap_style="flat"),
                      "props": {"connector": cid, "from": fl, "to": tl, "width_m": w, "source": "SUMO via duckOSM GMNS (lane_connector)"}})
    crossing = lambda q: q.get("footway") == "crossing" or q.get("cycleway") == "crossing" or bool(q.get("crossing"))
    pb, pj = _path_bands(dict(P, paths=[q for q in P.get("paths", []) if not crossing(q)]), axes)
    for b_ in pb:
        kind = "path link" if _is_link(b_["line"], next(ln for ln, a in axes if a["id"] == b_["axis"])) else b_["kind"]
        bands.append({"kind": kind, "line": b_["line"], "poly": b_["line"].buffer(b_["width"] / 2, cap_style="flat"),
                      "props": {"osm": b_["way"], "width_m": b_["width"], "axis": b_["axis"], "side": b_["side"], "source": "OSM"}})
    for jt in pj:
        i, k = jt["bands"]
        w = min(pb[i]["width"], pb[k]["width"])
        bands.append({"kind": "path joint", "line": None, "poly": shapely.Point(jt["at"]).buffer(w / 2),
                      "props": {"why": jt["why"], "source": "OSM"}})
    val = lambda v: v["value"] if isinstance(v, dict) else v
    for q in P.get("paths", []):
        if crossing(q) and len(val(q["line"])) >= 2:
            ln = shapely.LineString([v[:2] for v in val(q["line"])])
            w = float(val(q.get("width")) or 3.0)
            bands.append({"kind": "crossing", "line": ln, "poly": ln.buffer(w / 2, cap_style="flat"),
                          "props": {"osm": q.get("way"), "marked": not (q.get("crossing") == "unmarked" or q.get("markings") == "no"), "source": "OSM"}})
    if B is None:
        return {"bands": bands, "outside": []}
    homes = [(f"branch {b['id']}", b["poly"]) for b in B] + [(f"fork {f['id']}", f["poly"]) for f in F]
    everything = shapely.union_all([h for _, h in homes])
    outside = []
    for i, b_ in enumerate(bands):
        best = max(homes, key=lambda h: h[1].intersection(b_["poly"]).area)
        b_["home"] = best[0] if best[1].intersection(b_["poly"]).area > 0 else None
        out = b_["poly"].difference(everything).area
        if out > STICK_OUT_M2 and b_["kind"] != "crossing":
            outside.append((i, round(out, 1)))
    return {"bands": bands, "outside": outside}


# ---------------------------------------------------------------- step 3b: smoothing
SMOOTH_M = 3.0          # the outline has no notch and no bump smaller than twice this (a jog at an OSM vertex, a step where two widths meet)
JOG_DEG, JOG_M = 60.0, 3.0   # a jog: a turn over JOG_DEG beside a segment shorter than JOG_M (as rank 0's check D8)


def jogs(poly):
    """The jogs in a polygon's outline: [(x, y)] where it turns more than JOG_DEG beside a segment shorter than JOG_M."""
    import shapely
    out = []
    for pg in shapely.get_parts(poly):
        if pg.geom_type != "Polygon":
            continue
        for ring in [pg.exterior] + list(pg.interiors):
            cs = list(ring.simplify(0.05).coords)
            cs = cs[:-1] + cs[:2]
            for (x0, y0), (x1, y1), (x2, y2) in zip(cs, cs[1:], cs[2:]):
                l1, l2 = math.hypot(x1 - x0, y1 - y0), math.hypot(x2 - x1, y2 - y1)
                if min(l1, l2) < 0.05:
                    continue
                ang = abs(math.degrees(math.atan2((x1 - x0) * (y2 - y1) - (y1 - y0) * (x2 - x1), (x1 - x0) * (x2 - x1) + (y1 - y0) * (y2 - y1))))
                if ang > JOG_DEG and (l1 < JOG_M or l2 < JOG_M):
                    out.append((x1, y1))
    return out


TAPER_M = 10.0          # step 3b: a step in the outline (a jog) becomes a straight taper over this on each side of its corner


def step3b(B, F, bands=None):
    """Step 3b (docs/notes/bridge-steps.md): the outline of each bridge level made smooth, from the frozen branches and forks: their union,
    closed and opened by SMOOTH_M with round joins, so no notch or bump smaller than 2 SMOOTH_M stays (a jog at an OSM vertex, a step where
    two branches' widths meet at a branch point), and never smaller than the union: nothing of a branch is taken, so a bridge end stays
    square. Then each jog left (a convex step where a wider branch's square end meets a narrower one: a10 against the a11 + a12 pair at
    Hemlock) becomes a straight taper: the deck between the corner and the outline TAPER_M along it on each side. ``bands`` is not used: step 3
    measures each branch's width exactly from its bands, so no sliver of a band is left outside (a path that moves away from the road,
    more than BESIDE_M from the lanes, is not deck). Returns {level: polygon}."""
    import shapely
    out = {}
    for lv in sorted({b["level"] for b in B}):
        u = shapely.union_all([b["poly"] for b in B if b["level"] == lv] + [f["poly"] for f in F if f["level"] == lv])
        closed = u.buffer(SMOOTH_M, join_style="round").buffer(-SMOOTH_M, join_style="round")
        smooth = closed.buffer(-SMOOTH_M, join_style="round").buffer(SMOOTH_M, join_style="round").union(u)
        smooth = smooth.buffer(0.5, join_style="round").buffer(-0.5, join_style="round")    # (the corners where the opened and the original meet)
        for _ in range(6):                                   # the jogs left: a straight taper at each (a few passes: a taper can leave a smaller one)
            js = jogs(smooth)
            if not js:
                break
            add = []
            for x, y in js:
                for part in shapely.get_parts(smooth):
                    ring = part.exterior if part.geom_type == "Polygon" else None
                    if ring is None or ring.distance(shapely.Point(x, y)) > 0.1:
                        continue
                    # the taper: the convex hull of the outline TAPER_M along it on each side of the corner (it fills the step's inner
                    # corner with a straight line from the wider edge to the narrower one, and adds nothing beyond the two edges)
                    L, s0 = ring.length, ring.project(shapely.Point(x, y))
                    ss = [(s0 + d) % L for d in [k * 0.5 for k in range(int(-2 * TAPER_M), int(2 * TAPER_M) + 1)]]
                    piece = shapely.MultiPoint([ring.interpolate(v) for v in ss])
                    add.append(piece.convex_hull)
            smooth = shapely.union_all([smooth] + add).buffer(0.3, join_style="mitre").buffer(-0.3, join_style="mitre")
            smooth = shapely.union_all([shapely.Polygon(p_.exterior, [r for r in p_.interiors if shapely.Polygon(r).area >= 2.0])
                                        for p_ in shapely.get_parts(smooth) if p_.geom_type == "Polygon"])   # (micro gaps where a taper meets an arc)
        ends = [shapely.Point(b["line"].coords[0] if e == 0 else b["line"].coords[-1]) for b in B if b["level"] == lv
                for e, nd in enumerate(b["ends"]) if nd is None]
        out[lv] = _fillet_corners(shapely.make_valid(smooth.simplify(0.02)), ends)
    return out


FILLET_M = 8.0          # step 3b: a corner of the outline (a fork's side meeting a branch's edge) is rounded over this on each side
FILLET_MIN_DEG = 4.0    # ... where the edge turns more than this at one point
FILLET_MAX_DEG = 35.0   # ... and at most this (a bigger turn is a bridge end or a gore: kept)


def _fillet_corners(g, ends=()):
    """The corners of the outline rounded (Kaveh, 2026-10-22: "round each corner where a fork's side meets a branch's edge, keep the
    bridge ends square"): at each point where the edge turns between FILLET_MIN_DEG and FILLET_MAX_DEG, the edge from FILLET_M before the
    point to FILLET_M after it is replaced by a curve (a quadratic Bezier through the two ends with the corner as its control point), so
    it leaves both sides along their own direction. A point within 2 FILLET_M of a bridge end is not touched (the end stays square)."""
    import numpy as np
    import shapely

    def turn(a, b, c):
        (x0, y0), (x1, y1), (x2, y2) = a, b, c
        return abs(math.degrees(math.atan2((x1 - x0) * (y2 - y1) - (y1 - y0) * (x2 - x1), (x1 - x0) * (x2 - x1) + (y1 - y0) * (y2 - y1))))

    def ring_fillet(ring):
        # (the ring starts at the point nearest a bridge end: no window then crosses the ring's start)
        cs0 = list(ring.coords)[:-1]
        if ends:
            k0 = min(range(len(cs0)), key=lambda i: min(shapely.Point(cs0[i]).distance(e) for e in ends))
            cs0 = cs0[k0:] + cs0[:k0]
        ring = shapely.LinearRing(cs0)
        L = ring.length
        at = lambda v: np.array(ring.interpolate(min(max(v, 0.0), L)).coords[0])
        coarse = list(ring.simplify(0.1).coords)[:-1]
        n = len(coarse)
        corners = []
        for i in range(n):
            if turn(coarse[i - 1], coarse[i], coarse[(i + 1) % n]) <= FILLET_MIN_DEG:
                continue
            p = shapely.Point(coarse[i])
            if any(p.distance(e) <= 2 * FILLET_M for e in ends):
                continue
            c = ring.project(p)
            if c - FILLET_M < 0 or c + FILLET_M > L:
                continue
            # the corner's turn over the window: between the chords into it and out of it; and the edge's total turn inside the window
            # (a gore tip or a bridge end turns far more than FILLET_MAX_DEG over the window: kept)
            P0, P1, P2 = at(c - FILLET_M), at(c), at(c + FILLET_M)
            net = turn(tuple(P0), tuple(P1), tuple(P2))
            ss = np.arange(c - FILLET_M, c + FILLET_M + 0.01, 1.0)
            q = [tuple(at(v)) for v in ss]
            total = sum(turn(q[j - 1], q[j], q[j + 1]) for j in range(1, len(q) - 1))
            if FILLET_MIN_DEG < net <= FILLET_MAX_DEG and total <= FILLET_MAX_DEG + 5.0:
                corners.append((c, net))
        if not corners:
            return list(ring.coords)
        spans = []                                       # the windows, the sharpest first, none overlapping another
        for c, net in sorted(corners, key=lambda x: -x[1]):
            if all(c + FILLET_M <= a or c - FILLET_M >= b for a, b, _ in spans):
                spans.append((c - FILLET_M, c + FILLET_M, c))
        spans.sort()
        # the ring's own points outside the windows (a resampling every 0.5 m put short pieces beside the square bridge ends: jogs)
        own = [(ring.project(shapely.Point(q)), q) for q in list(ring.coords)[:-1]]
        pts, s_ = [], 0.0
        for a, b, c in spans:
            pts += [q for v, q in own if s_ <= v < a]
            P0, P1, P2 = at(a), at(c), at(b)
            for u in np.linspace(0.0, 1.0, 25):
                pts.append(tuple((1 - u) ** 2 * P0 + 2 * (1 - u) * u * P1 + u ** 2 * P2))
            s_ = b
        pts += [q for v, q in own if s_ <= v]
        return pts + [pts[0]]

    parts = []
    for pg in shapely.get_parts(g):
        if pg.geom_type != "Polygon":
            continue
        parts.append(shapely.make_valid(shapely.Polygon(ring_fillet(pg.exterior), [r.coords for r in pg.interiors])))
    return shapely.union_all(parts).simplify(0.02) if parts else g


BEND_DEG = 35.0         # step 3b: a turn in the outline of at most this is a bend (smoothed); a larger one is a corner (kept: a bridge end, a gore)
BEND_PASSES = 4         # ... rounded by this many passes of corner cutting (Chaikin)


def _smooth_bends(g):
    """The outline's bends rounded (Kaveh, 2026-10-20: "smooth along the curves too, no kink at an OSM point"): each point where the edge
    turns BEND_DEG or less is cut, a quarter and three quarters along its two segments, BEND_PASSES times (Chaikin); a point where it turns
    more is a corner and stays (a bridge end stays square, a gore keeps its point). A kink of a few degrees at an OSM point becomes a curve
    and the edge moves by a few centimetres."""
    import shapely

    def turn(a, b, c):
        (x0, y0), (x1, y1), (x2, y2) = a, b, c
        return abs(math.degrees(math.atan2((x1 - x0) * (y2 - y1) - (y1 - y0) * (x2 - x1), (x1 - x0) * (x2 - x1) + (y1 - y0) * (y2 - y1))))

    def ring(cs):
        pts = list(cs)[:-1]
        for _ in range(BEND_PASSES):
            n, new = len(pts), []
            if n < 4:
                break
            for i in range(n):
                a, b, c = pts[i - 1], pts[i], pts[(i + 1) % n]
                if turn(a, b, c) > BEND_DEG:
                    new.append(b)                                     # a corner: kept
                    continue
                new.append((0.75 * b[0] + 0.25 * a[0], 0.75 * b[1] + 0.25 * a[1]))
                new.append((0.75 * b[0] + 0.25 * c[0], 0.75 * b[1] + 0.25 * c[1]))
            pts = new
        return pts + [pts[0]]
    parts = []
    for pg in shapely.get_parts(g.simplify(0.02)):          # (first the micro points a union leaves: a 4 cm zigzag turned 21 degrees)
        if pg.geom_type != "Polygon":
            continue
        parts.append(shapely.make_valid(shapely.Polygon(ring(pg.exterior.coords), [ring(r.coords) for r in pg.interiors])))
    return shapely.union_all(parts) if parts else g


def snapshot_3b_4(outline, S4):
    """Steps 3b and 4 as plain data, to freeze them: each level's smooth outline (area, length of its edge, its points rounded to 1 cm) and
    the bands of step 4 (kind, source id, home, area), sorted."""
    import shapely
    r2 = lambda v: round(float(v), 2)
    ol = {}
    for lv, g in outline.items():
        g = shapely.normalize(g.simplify(0.01))
        ol[str(lv)] = {"area_m2": r2(g.area), "edge_m": r2(g.length),
                       "rings": [[[r2(x), r2(y)] for x, y in ring.coords] for pg in shapely.get_parts(g) for ring in [pg.exterior] + list(pg.interiors)]}
    key = lambda b: str(b["props"].get("lane_id") or b["props"].get("connector") or b["props"].get("osm") or b["props"].get("why"))
    bands_ = sorted([{"kind": b["kind"], "id": key(b), "home": b["home"], "area_m2": r2(b["poly"].area)} for b in S4["bands"]],
                    key=lambda d: (d["kind"], d["id"], d["area_m2"]))
    return {"outline": ol, "bands": bands_}


def steps_3b_4(con, P, gmns=None):
    """Steps 3b and 4 as accepted, on the frozen steps 1 to 3: (axes, levels, R, B, F, outline {level: polygon}, step 4's result)."""
    axes, a_lv, R, B, F = steps_1_3(con, P, gmns)
    S4 = step4(P, axes, B, F, gmns=gmns)
    return axes, a_lv, R, B, F, step3b(B, F, S4["bands"]), S4


# ---------------------------------------------------------------- step 6: the cover
STRAIGHT_DEG = 30.0     # step 6: a connector that turns at most this goes straight on: it is a lane
REALM_STEP_M = 0.5      # step 6: the deck nearer to a path than to a lane is the pedestrian realm, measured to this ...
REALM_REACH_M = 30.0    # ... up to this far from the path
REALM_SMOOTH_M = 1.0    # ... its edge rounded over this


def cover_items(P, axes, a_lv, S4, outline):
    """Step 6 (docs/notes/bridge-steps.md): what lies on the structure, from step 4's bands only, in the form bridge_surface.model lays on
    the height surface: [(polygon, key, lift, rise, props)]. The lanes are SUMO's (step 4), drawn one after the other so none lies on
    another (a connector only where no lane is); the paths are OSM's; a barrier stands between the driving side and a path; the paint
    (lane lines between lanes of one direction of travel, a centre line between the two, edge lines, a guide line along each connector,
    arrows, zebra bars on the crossings) as bridge_cover._level_items draws it. The rest of the deck is paved (bridge_surface.model)."""
    import shapely
    from .bridge_cover import _level_items, _turn
    from .network import arrow_shape
    from .parts import CROSSWALK_M, ZEBRA_BAR_M, ZEBRA_GAP_M
    axis_of_way = {w: a["id"] for _, a in axes for w in a["ways"]}
    items = []
    for lv, deck_lv in outline.items():
        ids = {aid for aid, l_ in a_lv.items() if l_ == lv}
        done, out_l, junction = shapely.Polygon(), [], []
        for b in S4["bands"]:
            if b["kind"] != "lane":
                continue
            aid = axis_of_way.get(b["props"].get("osm"))
            if aid not in ids:
                continue
            q = shapely.make_valid(b["poly"].difference(done)).intersection(deck_lv)
            if q.area > 0.3:
                props = {"type": "lane", "lane_id": b["props"]["lane_id"], "width_m": b["props"]["width_m"], "axis": aid, "osm": b["props"]["osm"],
                         "bridge": P["name"], "source": b["props"]["source"]}
                out_l.append((q, props, b["line"], aid))
                done = done.union(b["poly"])
        # a connector that goes straight on (it turns STRAIGHT_DEG or less) is a lane: it joins its two lanes, with their lane lines, centre
        # line and arrows, on the axis of the lane it comes from. Only a connector that turns more is a junction lane with a guide line
        osm_of_lane = {b["props"]["lane_id"]: b["props"]["osm"] for b in S4["bands"] if b["kind"] == "lane"}
        for b in S4["bands"]:
            if b["kind"] != "connector":
                continue
            q = shapely.make_valid(b["poly"].difference(done)).intersection(deck_lv)
            if q.area > 0.3:
                osm = osm_of_lane.get(b["props"]["from"])
                if _turn(b["line"]) <= STRAIGHT_DEG and axis_of_way.get(osm) in ids:
                    props = {"type": "lane", "lane_id": b["props"]["connector"], "width_m": b["props"]["width_m"], "axis": axis_of_way[osm],
                             "osm": osm, "from_lane": b["props"]["from"], "to_lane": b["props"]["to"], "bridge": P["name"],
                             "source": b["props"]["source"]}
                    out_l.append((q, props, b["line"], axis_of_way[osm]))
                else:
                    props = {"id": b["props"]["connector"], "type": "junction lane", "from_lane": b["props"]["from"], "to_lane": b["props"]["to"],
                             "width_m": b["props"]["width_m"], "bridge": P["name"], "source": b["props"]["source"]}
                    junction.append((q, props, b["line"], None))
                done = done.union(b["poly"])
        paths_lv = {}
        for kind in ("sidewalk", "cycle lane"):
            g = [b["poly"] for b in S4["bands"] if b["kind"] == kind and a_lv.get(b["props"].get("axis")) == lv]
            g += [b["poly"] for b in S4["bands"] if b["kind"] in ("path joint", "path link")] if kind == "sidewalk" else []
            paths_lv[kind] = shapely.union_all(g or [shapely.Polygon()]).intersection(deck_lv)
        # the pedestrian realm, as on the ground: beside a path, the deck from the lanes to the parapet is the path's side; the paths of
        # step 4 lie inside it. It is the deck nearer to a path than to a lane (to REALM_STEP_M): a side with no OSM path stays paved
        drive = shapely.union_all([q for q, *_ in out_l + junction] or [shapely.Polygon()])
        any_path = paths_lv["sidewalk"].union(paths_lv["cycle lane"])
        rest = deck_lv.difference(drive)
        realm = [any_path.buffer(k * REALM_STEP_M).difference(drive.buffer(k * REALM_STEP_M)).intersection(rest)
                 for k in range(1, int(REALM_REACH_M / REALM_STEP_M) + 1)] if not any_path.is_empty else []
        # (closed, then opened by REALM_SMOOTH_M, then simplified: no gaps, and a smooth edge where a gore is split between two sides)
        realm = shapely.union_all(realm or [shapely.Polygon()]).buffer(REALM_SMOOTH_M).buffer(-2 * REALM_SMOOTH_M).buffer(REALM_SMOOTH_M)
        realm = realm.simplify(0.2).intersection(rest)
        walk = shapely.union_all([paths_lv["sidewalk"]] + [p for p in shapely.get_parts(realm) if p.geom_type == "Polygon" and p.area > 2.0])
        paths_lv["sidewalk"] = shapely.union_all([p for p in shapely.get_parts(walk) if p.geom_type == "Polygon"] or [shapely.Polygon()])
        crossings = [(b["line"], float(b["poly"].area / max(b["line"].length, 0.1)), b["props"].get("marked", True), b["props"].get("osm"))
                     for b in S4["bands"] if b["kind"] == "crossing" and deck_lv.intersects(b["line"])]
        items += _level_items(P, lv, deck_lv, out_l + junction, junction, paths_lv, crossings, arrow_shape,
                              (CROSSWALK_M, ZEBRA_BAR_M, ZEBRA_GAP_M))
    return items
