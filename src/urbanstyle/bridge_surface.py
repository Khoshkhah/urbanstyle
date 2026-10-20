"""The bridge's structure, rank 0 of docs/notes/bridges-ranks.md: one height surface per structure, and everything of the structure
sampled from it. No cover yet (the street on the bridge comes later and reads the same surface).

    models(con, bridges) -> (models, set())    # one model per profile, in the format bridge3d.model gives: the page draws it unchanged

The steps, per profile:
1. The nodes of all its axes (shared where axes meet) get one height each, solved together: 0 on the ground, the grade at most
   MAX_GRADE, the clearances as strong wishes, the smoothest result among those (`_solve`).
2. The axes are grouped by level into structures. A ramp beside its bridge, closer than CUT_NEAR_M with heights more than CUT_DZ_M
   apart, is its own structure (rule 4). Each structure's polygon is the union of its axes' strips (its sections as wide as their
   bands, the paths beside them, the guard).
3. The height surface of a structure, h(x, y): the heights of its axes blended by nearness (`_Surface`), continuous by construction.
4. The slab (top h, bottom h − DECK_M, never below the ground), the approach fill where h < DECK_M (ground of level 0), the sides, the
   parapet along the edge except at a landing or a joint, the piers and the truss (bridge_structure), and the checks D1 to D6.
"""
import json
import math

from .bridge_profile import CLEAR_MAX_GRADE, DECK_M, GRADE, LEVEL_M, PIER_MIN_M, TOP_M, _strip, height
from .deck3d import GUARD_M, JOINT_M, OFF_GROUND_M, STEP_M

CUT_NEAR_M = 4.0      # rule 4: two roads of one level closer than this ...
CUT_DZ_M = 1.0        # ... with heights more than this apart are two structures, a wall between (0.5 cut a loop's two carriageways apart on the curve)
EDGE_M = 0.5          # the structure's edge beyond the outer band: the parapet stands on it
SLIT_M = 0.3          # rule 4: the gap between a ramp's strip and its bridge's where a wall stands
PATH_NEAR_M = 3.0     # a path beside an axis belongs to its strip where it lies within this of the strip
OWN_REACH_M = 2.5     # a walking or cycling way within this of an axis's lanes, ...
OWN_W_M = 6.0         # an own way reaches at most this beyond the reach (a cycleway with its sidewalk)
OWN_MIN_M2 = 40.0     # ... with at least this much of it there, is the axis's own (its sidewalk, its cycleway)
STATION_M = 2.0       # the strip's width is set every this along the axis
TAPER_M = 20.0        # a change of the strip's width spreads over this length: a taper, never a step
OUTLINE_NEAR_M = 2.5  # OSM's outline widens the structure this far beyond its strips, no more (not the gores between ramps)
END_DIR_M = 10.0      # an end cap stands square to the axis's direction over its last this many metres
FORK_M = 30.0         # ... and only within this of the node where the two branches meet
GORE_M = 6.0          # a gap between two strips that meet, narrower than twice this, is deck where their heights agree
SMOOTH_M = 3.0        # an edge has no notch and no bump smaller than twice this
JUNCTION_SMOOTH_M = 3.5  # ... and at a junction none smaller than twice this
JOG_DEG = 60.0        # D8: a turn in an edge over this ...
JOG_M = 3.0           # ... beside a segment shorter than this is a jog (an end cap's corners are 90 degrees beside long segments: not counted)
BRANCH_TAPER_M = 30.0 # a narrower axis leaves a wider one along a smooth S-curve this long
LINE_SMOOTH_M = 12.0  # a branch's centre line is the mean of OSM's line within this on each side (no jog at a vertex)
PAIR_M = 14.0         # two one-way lines this near each other, side by side, are one road ...
PAIR_MIN_M = 40.0     # ... over at least this length from the node they share
PAIR_STEADY_M = 20.0  # ... their width is measured from this far from the node, where the two lines have opened to their running distance
SPLIT_M = 40.0        # a carriageway split: the two lines are measured this far from the node, where they have moved apart
BRANCH_M = 10.0       # D8: within this of a node where axes meet, a step in the edge is the branch (the width changes there), not a fault
NEAR_M = 0.5          # the blend of heights: weight 1 / (distance + NEAR_M)^2
W_CLEAR = 50.0        # the weight of a clearance (a wish: a clearance the grade cannot reach is listed, D4)
W_GRADE = 100.0       # the weight of a grade over GRADE (the deck climbs at GRADE where it can, MAX_GRADE at most)
NODE_STEP_M = 10.0    # the solve has a node at least every this along each axis
W_COUPLE = 100.0      # the weight that holds two joined decks at one height
COUPLE_FROM_GROUND_M = 10.0  # ... except within this of a ground node (a ramp descends there)
W_MEASURED = 10.0     # the weight that holds a measured height (LiDAR) where the profile has one
W_RULE = 0.02         # the weight of the agreed rule where nothing else decides: a deck rises at GRADE from its ground ends, TOP_M at most
STEEP_DEG = 45.0      # D2: a face steeper than this inside a structure
MAX_TURN_DEG = 90.0   # a bridge has no U-turn: a band link that turns more than this is not a move (Kaveh 2026-10-19)


def models(con, bridges, rank0=False, lidar=True, gmns=None):
    """rank0: the surface only, nothing on it or under it. lidar=False: the profile's measured heights are ignored; the heights come
    from the rules alone (to see what the rules give where there is no survey)."""
    import shapely
    ms, drawn = [], set()
    for pf in bridges:
        P = json.load(open(pf))
        if not lidar:
            for a in P["axes"]:
                a["vertical"]["source"], a["vertical"]["method"] = "urbanstyle", "chosen"
            P["name"] += " (no LiDAR)"
        m = model(con, P, rank0=rank0, gmns=gmns)
        ms.append(m)
        # the street spaces of level 1 and up on these structures: the page hides their flat drawing (as deck3d did)
        poly = shapely.from_geojson(json.dumps(m["deck_ll"]))
        for u, w in con.execute("SELECT unit_id, ST_AsWKB(geometry) FROM work.unit WHERE level >= 1 AND geometry IS NOT NULL").fetchall():
            if shapely.from_wkb(bytes(w)).intersects(poly):
                drawn.add(u)
    return ms, drawn


# ---------------------------------------------------------------- 1. the heights at the nodes
def _nodes(P, a_lv):
    """The nodes of the profile's axes: (nodes [{xy, ground, clear}], per axis [(s, node)], pairs [(node above, node below)] where
    two axes of different levels cross). Axes share a node where their points coincide. A point on the ground, a clearance point
    and a crossing are nodes too."""
    import shapely
    index, nodes, per_axis = {}, [], {}
    lines = {a["id"]: shapely.LineString([q[:2] for q in a["line"]["value"]]) for a in P["axes"]}
    cross = {a["id"]: [] for a in P["axes"]}      # s values of crossings with an axis of another level
    pairs_s = []                                  # (axis above, s, axis below, s)
    ids = [a["id"] for a in P["axes"]]
    for i, u in enumerate(ids):
        for w in ids[i + 1:]:
            if a_lv[u] == a_lv[w]:
                continue
            x = lines[u].intersection(lines[w])
            for pt in shapely.get_parts(x):
                if pt.geom_type != "Point":
                    continue
                su, sw = round(lines[u].project(pt), 2), round(lines[w].project(pt), 2)
                if min(su, lines[u].length - su) < 0.5 or min(sw, lines[w].length - sw) < 0.5:
                    continue        # (they meet at an end: a junction, not a crossing)
                cross[u].append(su); cross[w].append(sw)
                pairs_s.append((u, su, w, sw) if a_lv[u] > a_lv[w] else (w, sw, u, su))

    def node(x, y):
        k = (round(x, 2), round(y, 2))
        if k not in index:
            index[k] = len(nodes)
            nodes.append({"xy": (x, y), "ground": False, "clear": 0.0})
        return index[k]
    for a in P["axes"]:
        ln = shapely.LineString([q[:2] for q in a["line"]["value"]])
        ss = {0.0, ln.length}
        d = 0.0
        cs = list(ln.coords)
        for p, q in zip(cs, cs[1:]):
            d += math.dist(p, q)
            ss.add(round(d, 2))
        ss |= {round(s, 2) for s in a.get("ground_at", [])} | set(cross[a["id"]])
        ss |= {round(float(s), 2) for s in __import__("numpy").arange(NODE_STEP_M, ln.length, NODE_STEP_M)}   # (a node every NODE_STEP_M)
        clear = []
        for c in a["vertical"].get("clearances", []):
            p = shapely.Point(c["at"])
            if ln.distance(p) < 1.0 and not str(c.get("over", "")).startswith("deck"):     # (a deck below: a pair, solved together)
                s = round(ln.project(p), 2)
                ss.add(s)
                clear.append((s, c["z"]))
        seq = []
        for s in sorted(ss):
            if seq and s - seq[-1][0] < 0.05:        # (two stations within 5 cm are one node: an edge that short had no grade rule)
                continue
            p = ln.interpolate(s)
            n = node(p.x, p.y)
            seq.append((s, n))
            for s_, z_ in clear:
                if abs(s_ - s) < 0.01:
                    nodes[n]["clear"] = max(nodes[n]["clear"], z_)
        for e in a.get("ends", []):
            if e.get("ground"):
                nodes[seq[0][1] if e["s"] < 0.01 else seq[-1][1]]["ground"] = True
        for s in a.get("ground_at", []):
            n = min(seq, key=lambda t: abs(t[0] - s))[1]
            nodes[n]["ground"] = True
        per_axis[a["id"]] = seq
    nearest = lambda aid, s_: min(per_axis[aid], key=lambda t: abs(t[0] - s_))[1]
    pairs = [(nearest(u, su), nearest(w, sw)) for u, su, w, sw in pairs_s]
    return nodes, per_axis, pairs


def _couplings(P, nodes, per_axis, a_lv):
    """Pairs of a node and a point on another axis of the same level whose bands overlap there (one deck: one surface), both at least
    COUPLE_FROM_GROUND_M from every ground node: [(node, (node0, node1, t))], the point between two nodes of the other axis."""
    import shapely
    axes = [(shapely.LineString([q[:2] for q in a["line"]["value"]]), a) for a in P["axes"]]
    strips = _axis_strips(axes, [])
    halfw = {a["id"]: max(abs(v) for v in _axis_width(a, ln, [])) for ln, a in axes}
    ground = [shapely.Point(nd["xy"]) for nd in nodes if nd["ground"]]
    gmp = shapely.MultiPoint(ground) if ground else None
    out = []
    for ln, a in axes:
        for s, n in per_axis[a["id"]]:
            pt = shapely.Point(nodes[n]["xy"])
            if gmp is not None and gmp.distance(pt) < COUPLE_FROM_GROUND_M:
                continue
            for ln2, b in axes:
                # one deck until they physically separate: the other band within this axis's half width plus the gap that is still
                # filled (2 GORE_M), so the two carry one surface up to where the deck really branches
                if b["id"] == a["id"] or a_lv[a["id"]] != a_lv[b["id"]] or strips[b["id"]].distance(pt) > halfw[a["id"]] + 2 * GORE_M:
                    continue
                s2 = ln2.project(pt)
                if s2 < 1.0 or s2 > ln2.length - 1.0:
                    continue                                   # (at the other axis's end: they meet at a node, already one height)
                seq = per_axis[b["id"]]
                k = next((k for k in range(len(seq) - 1) if seq[k][0] <= s2 <= seq[k + 1][0]), None)
                if k is None:
                    continue
                (sa, na), (sb, nb) = seq[k], seq[k + 1]
                t = (s2 - sa) / ((sb - sa) or 1.0)
                if n not in (na, nb):
                    out.append((n, (na, nb, t)))
    return out


def _solve(P, nodes, per_axis, pairs, couples=()):
    """One height per node. Hard: 0 on the ground, 0..TOP_M, the grade at most CLEAR_MAX_GRADE along every axis. Soft: the clearances
    over roads and buildings, LEVEL_M + DECK_M between two decks that cross (the lower one goes down where the upper cannot climb), the
    grade over GRADE, a measured height, a small wish to stay low; and the smoothest result: the change of grade along each axis is the
    least."""
    import numpy as np
    from scipy.optimize import minimize
    n = len(nodes)
    x0 = np.zeros(n)
    measured = np.full(n, np.nan)
    rows = []            # second differences along each axis
    edges = []           # (i, j, d)
    for a in P["axes"]:
        seq = per_axis[a["id"]]
        v = a["vertical"]
        fixed = "lidar" in str(v.get("source", "")).lower() or "measured" in str(v.get("method", "")).lower()
        for s, i in seq:
            z = max(0.0, height(v, s))
            x0[i] = z
            if fixed:
                measured[i] = z
        for (s0, i), (s1, j) in zip(seq, seq[1:]):
            if s1 - s0 > 0.01:
                edges.append((i, j, s1 - s0))
        for (s0, i), (s1, j), (s2, k) in zip(seq, seq[1:], seq[2:]):
            d0, d1 = max(s1 - s0, 0.01), max(s2 - s1, 0.01)
            r = np.zeros(n)
            r[i] += 1 / d0
            r[j] -= 1 / d0 + 1 / d1
            r[k] += 1 / d1
            rows.append(r * math.sqrt((d0 + d1) / 2))      # (weighted by the length it stands for)
    D = np.array(rows) if rows else np.zeros((0, n))
    Q = D.T @ D
    for nn, (na, nb, t) in couples:                     # one deck, one surface: the node at the other axis's height there
        r = np.zeros(n); r[nn] += 1.0; r[na] -= 1.0 - t; r[nb] -= t
        Q += W_COUPLE * np.outer(r, r)
    clear = np.array([nd["clear"] for nd in nodes])
    has_m = ~np.isnan(measured)
    # the agreed rule as the target where nothing else decides: GRADE up from the nearest ground node along the network, TOP_M at most
    import heapq
    adj = {}
    for i, j, d in edges:
        adj.setdefault(i, []).append((j, d)); adj.setdefault(j, []).append((i, d))
    dist = {i: 0.0 for i, nd in enumerate(nodes) if nd["ground"]}
    heap = [(0.0, i) for i in dist]
    while heap:
        d0, i = heapq.heappop(heap)
        if d0 > dist.get(i, np.inf):
            continue
        for j, d in adj.get(i, []):
            if d0 + d < dist.get(j, np.inf):
                dist[j] = d0 + d; heapq.heappush(heap, (d0 + d, j))
    target = np.array([min(TOP_M, GRADE * dist.get(i, 0.0)) for i in range(n)])
    ei = np.array([e[0] for e in edges]); ej = np.array([e[1] for e in edges]); ed = np.array([e[2] for e in edges])
    pu = np.array([p[0] for p in pairs], dtype=int); pl = np.array([p[1] for p in pairs], dtype=int)
    GAP = LEVEL_M + DECK_M

    def f(x):
        r = 0.5 * x @ Q @ x + W_RULE * ((x - target) ** 2).sum()
        c = np.maximum(0.0, clear - x)
        r += W_CLEAR * (c * c).sum()
        if len(pu):
            cp = np.maximum(0.0, GAP - (x[pu] - x[pl]))
            r += W_CLEAR * (cp * cp).sum()
        g = np.abs(x[ei] - x[ej]) / ed
        og = np.maximum(0.0, g - GRADE)
        r += W_GRADE * (og * og * ed).sum()
        if has_m.any():
            r += W_MEASURED * ((x[has_m] - measured[has_m]) ** 2).sum()
        return r

    def jac(x):
        j = Q @ x + 2 * W_RULE * (x - target)
        c = np.maximum(0.0, clear - x)
        j -= 2 * W_CLEAR * c
        if len(pu):
            cp = np.maximum(0.0, GAP - (x[pu] - x[pl]))
            np.add.at(j, pu, -2 * W_CLEAR * cp)
            np.add.at(j, pl, 2 * W_CLEAR * cp)
        diff = x[ei] - x[ej]
        g = np.abs(diff) / ed
        og = np.maximum(0.0, g - GRADE)
        gg = 2 * W_GRADE * og * np.sign(diff)          # d/d(x_i) of W (g - GRADE)^2 d  = 2 W og sign / d * d
        np.add.at(j, ei, gg)
        np.add.at(j, ej, -gg)
        if has_m.any():
            j[has_m] += 2 * W_MEASURED * (x[has_m] - measured[has_m])
        return j
    # the hard grade: CLEAR_MAX_GRADE d - (x_i - x_j) >= 0 and the other way
    A = np.zeros((2 * len(edges), n))
    b = np.zeros(2 * len(edges))
    for k, (i, j, d) in enumerate(edges):
        A[2 * k, i], A[2 * k, j], b[2 * k] = -1, 1, CLEAR_MAX_GRADE * d
        A[2 * k + 1, i], A[2 * k + 1, j], b[2 * k + 1] = 1, -1, CLEAR_MAX_GRADE * d
    bounds = [(0.0, 0.0) if nd["ground"] else (0.0, TOP_M) for nd in nodes]
    x0 = np.clip(x0, [lo for lo, _ in bounds], [hi for _, hi in bounds])
    cons = [{"type": "ineq", "fun": lambda x: A @ x + b, "jac": lambda x: A}] if len(edges) else []
    if not has_m.any():
        x0 = np.clip(target, [lo for lo, _ in bounds], [hi for _, hi in bounds])     # (no survey: start from the rule's own line)
    res = minimize(f, x0, jac=jac, bounds=bounds, constraints=cons, method="SLSQP", options={"maxiter": 500, "ftol": 1e-7})
    return np.clip(res.x, 0.0, TOP_M), res


def _write_back(P, nodes, per_axis, h):
    """The solved heights into each axis's vertical profile (points along s), its clearances marked met or not."""
    for a in P["axes"]:
        seq = per_axis[a["id"]]
        pts = [[round(s, 2), round(float(h[i]), 2)] for s, i in seq]
        v = a["vertical"]
        v["points"], v["curves"] = pts, None
        v["source"], v["method"] = "urbanstyle", "chosen"
        v["rule"] = (f"all nodes of the bridge solved together: 0 on the ground, {GRADE:.0%} where it can and at most {CLEAR_MAX_GRADE:.0%} "
                     f"along a road, the clearances where the grade allows, the smoothest heights among those (bridges-ranks.md)")
        for c in v.get("clearances", []):
            import shapely
            ln = shapely.LineString([q[:2] for q in a["line"]["value"]])
            p = shapely.Point(c["at"])
            if ln.distance(p) < 1.0:
                c["met"] = bool(height(v, ln.project(p)) >= c["z"] - 0.05)


# ---------------------------------------------------------------- 2. the structures
def _axis_level(con, P):
    lv_of = dict(con.execute("SELECT osm_id, level_min FROM work.element WHERE type = 'road'").fetchall())
    out = {}
    for a in P["axes"]:
        ls = [lv_of.get(int(w[1:])) for w in a["ways"] if lv_of.get(int(w[1:])) is not None]
        out[a["id"]] = max(set(ls), key=ls.count) if ls else 1
    return out


_LANES = {}          # OSM's lanes per way of the bridge being built (model() sets it): {way: {axis id: (with, against, same sense)}}


def _lane_extent(a, s_):
    """The lanes of axis a at s: (left edge, right edge) of its lanes in the axis's frame, from OSM's lanes count of the way there
    (the profile's lane width), centred on the way's line; None where the axis has no section."""
    sec = next((sc for sc in a["sections"] if sc["s0"] - 0.01 <= s_ <= sc["s1"] + 0.01 and sc.get("bands")), None)
    if not sec:
        return None
    bs = sec["bands"]
    w_ = next((b.get("way") for b in bs if b.get("way")), None)
    rec = _LANES.get(w_, {})
    if a["id"] in rec:
        n = rec[a["id"]][0] + rec[a["id"]][1]
        wid = float(bs[0]["width"]["value"])
        return (-n * wid / 2, n * wid / 2)
    return (min(b["t"] - b["width"]["value"] / 2 for b in bs), max(b["t"] + b["width"]["value"] / 2 for b in bs))


def _axis_width(a, ln, paths, others=()):
    """One width for an axis (Kaveh: the width changes only at a branch): its lanes (OSM's count) plus its own walking and cycling ways,
    plus EDGE_M on each side. A way is the axis's own when most of it (OWN_SHARE) runs beside the lanes, within OWN_REACH_M of their edge,
    and no other axis is nearer to it. Returns (lo, hi) in the axis's frame (left positive)."""
    import numpy as np
    import shapely
    L = ln.length
    ss = np.arange(0.0, L, STATION_M).tolist() + [L]
    ext = [_lane_extent(a, s_) for s_ in ss]
    lo = np.array([e[0] if e else -3.5 for e in ext]); hi = np.array([e[1] if e else 3.5 for e in ext])
    half = max(abs(lo).max(), abs(hi).max())
    near = ln.buffer(half + OWN_REACH_M)
    own = []
    for p in paths:
        part = p.intersection(near)
        if part.area < OWN_MIN_M2:
            continue
        c = part.centroid
        if any(o_.distance(c) < ln.distance(c) - 0.5 for o_ in others):
            continue                    # (nearer to another axis: that axis's way)
        own.append(p.intersection(ln.buffer(half + OWN_REACH_M + OWN_W_M)))     # (the way as far as it runs beside: one way's width out)
    reach = OWN_REACH_M + OWN_W_M
    lo, hi = lo - EDGE_M, hi + EDGE_M
    if own:
        allp = shapely.union_all(own)
        for k, s_ in enumerate(ss):
            x, y, nx, ny = _frame(ln, s_)
            cross = shapely.LineString([(x + nx * (lo[k] - reach), y + ny * (lo[k] - reach)), (x + nx * (hi[k] + reach), y + ny * (hi[k] + reach))])
            for seg in shapely.get_parts(cross.intersection(allp)):
                if seg.is_empty or seg.geom_type != "LineString":
                    continue
                ts = [((cx - x) * nx + (cy - y) * ny) for cx, cy in seg.coords]
                lo[k] = min(lo[k], min(ts) - EDGE_M); hi[k] = max(hi[k], max(ts) + EDGE_M)
    w = max(1, int(round(TAPER_M / 2 / STATION_M)))
    rmin = lambda v: np.array([v[max(0, k - w):k + w + 1].min() for k in range(len(v))])
    rmax = lambda v: np.array([v[max(0, k - w):k + w + 1].max() for k in range(len(v))])
    return float(rmin(rmax(lo)).min()), float(rmax(rmin(hi)).max())


def _frame(ln, s_):
    p_, q0, q1 = ln.interpolate(s_), ln.interpolate(max(s_ - 1, 0)), ln.interpolate(min(s_ + 1, ln.length))
    h_ = math.hypot(q1.x - q0.x, q1.y - q0.y) or 1.0
    return p_.x, p_.y, -(q1.y - q0.y) / h_, (q1.x - q0.x) / h_


def _axis_strips(axes, paths):
    """Every axis's own ground: its one width, and at a branch node where a wider axis continues it (nearly the same direction), the
    wider width at the node tapering to its own over TAPER_M: the change belongs to the branch. Square ends. {axis id: polygon}"""
    import numpy as np
    import shapely
    import shapely.ops
    width = {a["id"]: _axis_width(a, ln, paths) for ln, a in axes}
    # one road, one width: axes that meet end to end with nothing else at their joint (two ends at the node) and go straight on are one
    # road; they share one width and one offset (the widest of them), so a joint without a branch never steps, shifts or narrows
    ends = {}
    for ln, a in axes:
        for e in (0.0, ln.length):
            p_ = ln.interpolate(e)
            ends.setdefault((round(p_.x, 1), round(p_.y, 1)), []).append((ln, a, e))
    parent = {a["id"]: a["id"] for _, a in axes}

    def find(i):
        while parent[i] != i:
            i = parent[i]
        return i
    for at in ends.values():
        if len(at) != 2:
            continue
        (l1, a1_, e1), (l2, a2_, e2) = at
        d1 = np.array(_frame(l1, e1)[2:]); d2 = np.array(_frame(l2, e2)[2:])
        if abs(float(d1 @ d2)) > 0.85:
            parent[find(a1_["id"])] = find(a2_["id"])
    road = {}
    for ln, a in axes:
        lo_, hi_ = width[a["id"]]
        r = road.setdefault(find(a["id"]), [lo_, hi_])
        r[0], r[1] = min(r[0], lo_), max(r[1], hi_)
    width = {a["id"]: tuple(road[find(a["id"])]) for _, a in axes}
    out = {}
    for ln, a in axes:
        lo0, hi0 = width[a["id"]]
        L = ln.length
        ss = np.arange(0.0, L, STATION_M).tolist() + [L]
        lo = np.full(len(ss), lo0); hi = np.full(len(ss), hi0)
        left, right = [], []
        for k, s_ in enumerate(ss):
            x, y, nx, ny = _frame(ln, s_)
            left.append((x + nx * hi[k], y + ny * hi[k])); right.append((x + nx * lo[k], y + ny * lo[k]))
        strip = shapely.make_valid(shapely.Polygon(left + right[::-1]))
        if strip.geom_type != "Polygon":
            strip = shapely.union_all([g for g in shapely.get_parts(strip) if g.geom_type == "Polygon"])
        out[a["id"]] = shapely.make_valid(strip.buffer(0.01).buffer(-0.01))
    # at a branch: where this axis leaves a wider one at a node, each of its edges that lies inside the wider deck runs from the wider deck's
    # corner to its own edge BRANCH_TAPER_M along, as a curve tangent at both ends (it leaves along the wider deck's edge and arrives along
    # its own: a Hermite transition, as road design draws one; it cannot bulge and has no corner). Axes of one road share one width.
    for ln, a in axes:
        lo0, hi0 = width[a["id"]]
        L = ln.length
        T = min(BRANCH_TAPER_M, L)
        for end_s, sign in ((0.0, 1), (L, -1)):
            p = ln.interpolate(end_s)
            for ln2, b in axes:
                if b["id"] == a["id"] or find(b["id"]) == find(a["id"]):
                    continue
                for e2 in (0.0, ln2.length):
                    if ln2.interpolate(e2).distance(p) > 0.5:
                        continue
                    w_lo, w_hi = width[b["id"]]
                    if w_hi - w_lo <= hi0 - lo0 + 0.05:
                        continue
                    x2, y2, nx2, ny2 = _frame(ln2, e2)
                    # the wider deck's edge direction past its end (from its inside toward the node and on)
                    q2 = ln2.interpolate(min(ln2.length, 1.0) if e2 == 0.0 else max(0.0, ln2.length - 1.0))
                    tA = np.array([x2 - q2.x, y2 - q2.y]); tA = tA / (np.linalg.norm(tA) or 1)
                    xb, yb, nxb, nyb = _frame(ln, end_s + sign * T)
                    qb = ln.interpolate(end_s + sign * max(T - 1.0, 0.0))
                    tB = np.array([xb - qb.x, yb - qb.y]); tB = tB / (np.linalg.norm(tB) or 1)
                    x1, y1, nx1, ny1 = _frame(ln, end_s)
                    corners = [np.array([x2 + nx2 * t, y2 + ny2 * t]) for t in (w_lo, w_hi)]
                    side = lambda c: (c[0] - x1) * nx1 + (c[1] - y1) * ny1
                    c_lo, c_hi = sorted(corners, key=side)
                    edges = []
                    for c_wide, t_own in ((c_lo, lo0), (c_hi, hi0)):
                        outside = (side(c_wide) - t_own) * (1 if t_own == hi0 else -1) <= 0.05
                        pts_ = []
                        for d in np.linspace(0.0, T, int(T) + 2):
                            xe, ye, nxe, nye = _frame(ln, end_s + sign * d)
                            E = np.array([xe + nxe * t_own, ye + nye * t_own])            # this axis's own edge
                            if outside:
                                pts_.append(E)                                             # (own edge outside the wider deck: as it is)
                                continue
                            F = c_wide + tA * float((E - c_wide) @ tA)                     # the wider deck's edge line, straight on
                            u = d / T
                            g = u * u * (3.0 - 2.0 * u)                                    # smoothstep: flat at both ends, no overshoot
                            pts_.append(F + (E - F) * g)
                        edges.append(pts_)
                    piece = shapely.make_valid(shapely.Polygon([tuple(q_) for q_ in edges[1]] + [tuple(q_) for q_ in edges[0][::-1]]))
                    out[a["id"]] = shapely.make_valid(out[a["id"]].union(piece))
    return out


def _branches(axes, paths, a_lv=None):
    """The bridge's branches, from the network: the axes chained at each node, the two ends that continue each other most straight
    (|cos| over 0.7) joined, so the main span is one line from end to end and each ramp one line. Each branch has one width (the widest
    of its axes, lanes plus EDGE_M and the paths beside them). Returns [(line, lo, hi, [axis ids])]."""
    import numpy as np
    import shapely
    import shapely.ops
    width = {a["id"]: _axis_width(a, ln, paths, [l2 for l2, b in axes if b["id"] != a["id"]]) for ln, a in axes}
    by_id = {a["id"]: ln for ln, a in axes}
    ends = {}
    for ln, a in axes:
        for k, e in enumerate((0.0, ln.length)):
            p_ = ln.interpolate(e)
            q_ = ln.interpolate(min(ln.length, 2.0) if k == 0 else max(0.0, ln.length - 2.0))
            d = np.array([q_.x - p_.x, q_.y - p_.y]); d = d / (np.linalg.norm(d) or 1)    # into the axis, away from the node
            ends.setdefault((round(p_.x, 0), round(p_.y, 0)), []).append((a["id"], k, d))
    link = {}                                           # (axis, end) -> (axis, end) it continues into
    for at in ends.values():
        wd = lambda i: width[i][1] - width[i][0]
        same_lv = lambda x, y: a_lv is None or a_lv.get(x) == a_lv.get(y)     # (a branch never changes level)
        cand = sorted(((float(-(d1 @ d2)), i1, i2) for i1, (a1, k1, d1) in enumerate(at) for i2, (a2, k2, d2) in enumerate(at)
                       if i1 < i2 and a1 != a2 and same_lv(a1, a2) and abs(wd(a1) - wd(a2)) <= max(3.0, 0.25 * max(wd(a1), wd(a2)))), reverse=True)
        used = set()
        for c, i1, i2 in cand:
            if c < 0.7 or i1 in used or i2 in used:
                continue
            used |= {i1, i2}
            (a1, k1, _), (a2, k2, _) = at[i1], at[i2]
            link[(a1, k1)] = (a2, k2); link[(a2, k2)] = (a1, k1)
    seen, out = set(), []
    for ln, a in axes:
        if a["id"] in seen:
            continue
        # walk back to the start of this branch, then forward
        cur, k = a["id"], 0
        guard = 0
        while (cur, k) in link and guard < 50:
            nxt, nk = link[(cur, k)]
            if nxt == a["id"]:
                break
            cur, k = nxt, 1 - nk
            guard += 1
        chain, coords, cur_end = [], [], k               # start at (cur, k): walk from end k to end 1-k
        lo_, hi_ = 0.0, 0.0
        while cur not in seen:
            seen.add(cur); chain.append(cur)
            cs = list(by_id[cur].coords)
            if cur_end == 1:
                cs = cs[::-1]
            coords += cs if not coords else cs[1:]
            w_lo, w_hi = width[cur]
            if cur_end == 1:
                w_lo, w_hi = -w_hi, -w_lo                # (walked against the axis: left and right swap)
            lo_, hi_ = min(lo_, w_lo), max(hi_, w_hi)
            nxt = link.get((cur, 1 - cur_end))
            if not nxt:
                break
            cur, cur_end = nxt[0], nxt[1]
        if len(coords) >= 2:
            out.append((shapely.LineString(coords), lo_, hi_, chain))
    if a_lv is not None:
        lv_of = lambda ids_: a_lv.get(ids_[0])
        out = [b_ for lv_ in sorted({lv_of(b_[3]) for b_ in out}) for b_ in _merge_carriageways([x for x in out if lv_of(x[3]) == lv_])]
    else:
        out = _merge_carriageways(out)
    out = [(_smooth_line(bl), lo_, hi_, ids_) for bl, lo_, hi_, ids_ in out]
    # a carriageway split is not a branch: where two lines leave the end of a wider one nearly straight on (|cos| over 0.9), one to each
    # side, they are the same road drawn as two one-way lines; each keeps its one width, but its outer edge is set so that, once the
    # lines have moved apart (SPLIT_M along), it lies on the wider road's edge line: the deck keeps its width and edges through the split
    # (an edge only moves out, never into a carriageway's own lanes)
    out = [list(b_) for b_ in out]
    for W in out:
        wl, wlo, whi, _ = W
        for w_end in (0.0, wl.length):
            xw, yw, nxw, nyw = _frame(wl, w_end)
            qw = wl.interpolate(min(wl.length, 1.0) if w_end == 0.0 else max(0.0, wl.length - 1.0))
            tA = np.array([xw - qw.x, yw - qw.y]); tA = tA / (np.linalg.norm(tA) or 1)      # the wider road's direction past its end
            kids = []
            for C in out:
                if C is W:
                    continue
                cl = C[0]
                for c_end in (0.0, cl.length):
                    if cl.interpolate(c_end).distance(shapely.Point(xw, yw)) > 1.0:
                        continue
                    sg = 1 if c_end == 0.0 else -1
                    d_ = min(SPLIT_M, cl.length)
                    pc = cl.interpolate(c_end + sg * d_)
                    dc = np.array([pc.x - xw, pc.y - yw]); dc = dc / (np.linalg.norm(dc) or 1)
                    if float(dc @ tA) > 0.9:
                        off = float((pc.x - xw) * nxw + (pc.y - yw) * nyw)              # its side offset from the wider road's line
                        kids.append((C, c_end, sg, off))
            if len(kids) < 2 or not (min(k[3] for k in kids) < 0 < max(k[3] for k in kids)):
                continue
            for C, c_end, sg, off in kids:
                # the child's left normal against the wider road's: the same where the child runs on in the wider road's direction
                xc, yc, nxc, nyc = _frame(C[0], c_end)
                same = (nxc * nxw + nyc * nyw) * sg > 0
                if off > 0:                                   # on the wider road's left side: its left edge onto the wider road's left edge
                    edge = whi - off
                    if same:
                        C[2] = max(C[2], edge)
                    else:
                        C[1] = min(C[1], -edge)
                else:                                         # on its right side: its right edge onto the wider road's right edge
                    edge = wlo - off
                    if same:
                        C[1] = min(C[1], edge)
                    else:
                        C[2] = max(C[2], -edge)
    return [tuple(b_) for b_ in out]


def _transitions(branches):
    """Where a narrower branch leaves the end of a wider one, each of its edges that lies inside the wider deck blends from the wider
    deck's edge line (straight on) to its own edge over BRANCH_TAPER_M (smoothstep: flat at both ends, no overshoot, no corner)."""
    import numpy as np
    import shapely
    pieces = []
    for bl, lo0, hi0, ids in branches:
        L = bl.length
        T = min(BRANCH_TAPER_M, L)
        for end_s, sign in ((0.0, 1), (L, -1)):
            p = bl.interpolate(end_s)
            x1, y1, nx1, ny1 = _frame(bl, end_s)
            side = lambda c: (c[0] - x1) * nx1 + (c[1] - y1) * ny1
            for bl2, w_lo, w_hi, ids2 in branches:
                if bl2 is bl:
                    continue
                for e2 in (0.0, bl2.length):
                    if bl2.interpolate(e2).distance(p) > 1.0 or w_hi - w_lo <= hi0 - lo0 + 0.05:
                        continue
                    x2, y2, nx2, ny2 = _frame(bl2, e2)
                    q2 = bl2.interpolate(min(bl2.length, 1.0) if e2 == 0.0 else max(0.0, bl2.length - 1.0))
                    tA = np.array([x2 - q2.x, y2 - q2.y]); tA = tA / (np.linalg.norm(tA) or 1)
                    c_lo, c_hi = sorted([np.array([x2 + nx2 * t, y2 + ny2 * t]) for t in (w_lo, w_hi)], key=side)
                    edges = []
                    for c_wide, t_own in ((c_lo, lo0), (c_hi, hi0)):
                        outside = (side(c_wide) - t_own) * (1 if t_own == hi0 else -1) <= 0.05
                        pts_ = []
                        for d in np.linspace(0.0, T, int(T) + 2):
                            xe, ye, nxe, nye = _frame(bl, end_s + sign * d)
                            E = np.array([xe + nxe * t_own, ye + nye * t_own])
                            F = c_wide + tA * float((E - c_wide) @ tA)     # (inside or outside the wider deck: from its edge line onto
                                                                            # the branch's own edge, never a jump at the joint)
                            u = d / T; g = u * u * (3.0 - 2.0 * u)
                            pts_.append(F + (E - F) * g)
                        edges.append(pts_)
                    pieces.append(shapely.make_valid(shapely.Polygon([tuple(q_) for q_ in edges[1]] + [tuple(q_) for q_ in edges[0][::-1]])))
    return pieces


def _merge_carriageways(branches):
    """Two branches that leave the same node and run side by side (the shorter within PAIR_M of the longer over 80 % of its length, in
    the same direction) are one road drawn as two one-way lines: one branch, its centre line midway between them, its one width covering
    both. The longer one's part beyond stays its own branch. Then a road that continues another branch straight on (|cos| over 0.9)
    with about the same width joins it."""
    import numpy as np
    import shapely
    import shapely.ops
    br = [list(b_) for b_ in branches]
    changed = True
    while changed:
        changed = False
        for i in range(len(br)):
            for j in range(len(br)):
                if i == j or changed:
                    continue
                A, Bb = br[i], br[j]
                la, lb = A[0], Bb[0]
                if la.length > lb.length:
                    continue
                # a shared end node
                ea = next(((ea_, eb_) for ea_ in (0.0, la.length) for eb_ in (0.0, lb.length)
                           if la.interpolate(ea_).distance(lb.interpolate(eb_)) < 1.0), None)
                if ea is None:
                    continue
                ea_, eb_ = ea
                sa, sb = (1 if ea_ == 0.0 else -1), (1 if eb_ == 0.0 else -1)
                # how far from the shared node they run side by side (within PAIR_M, without a break)
                # one road as long as their bands touch (Kaveh: a deck branches where the decks really separate, not where the lanes fork)
                reach = max(abs(A[1]), abs(A[2])) + max(abs(Bb[1]), abs(Bb[2]))
                Lp = 0.0
                for d in np.arange(0.0, la.length + 0.01, 2.0):
                    if lb.distance(la.interpolate(ea_ + sa * d)) > reach:
                        break
                    Lp = d
                pa, pb = la.interpolate(ea_ + sa * min(20.0, la.length)), lb.interpolate(eb_ + sb * min(20.0, lb.length))
                p0 = la.interpolate(ea_)
                va = np.array([pa.x - p0.x, pa.y - p0.y]); vb = np.array([pb.x - p0.x, pb.y - p0.y])
                if Lp < PAIR_MIN_M or float(va @ vb) / ((np.linalg.norm(va) * np.linalg.norm(vb)) or 1) < 0.85:
                    continue
                if la.length - Lp < 10.0:
                    Lp = la.length
                # the centre line: midway, from the shared node over the stretch side by side
                mid = []
                for d in np.linspace(0.0, Lp, max(3, int(Lp / 2.0))):
                    q1 = la.interpolate(ea_ + sa * d)
                    q2 = lb.interpolate(lb.project(q1))
                    mid.append(((q1.x + q2.x) / 2, (q1.y + q2.y) / 2))
                ml = shapely.LineString(mid)
                qa_end = la.interpolate(ea_ + sa * Lp)
                sb_end = lb.project(qa_end)                       # where the other line is when this one leaves the pair
                sa0, sa1 = sorted((ea_, ea_ + sa * Lp)); sb0, sb1 = sorted((eb_, sb_end))
                both = shapely.union_all([_strip(shapely.ops.substring(la, sa0, sa1), A[1], A[2]),
                                          _strip(shapely.ops.substring(lb, sb0, sb1), Bb[1], Bb[2])])
                # one width: the one they have where they run together, PAIR_STEADY_M to PAIR_STEADY_M + 10 m from the node (nearer, the two
                # lines still open out from it: measured there, every pair ended at 6 m and none was merged, Hemlock a11 + a12); the merged road
                # ends where they spread wider than that by more than 1 m: there they separate, and each is its own branch (Kaveh: the width
                # changes only at a branch)
                ext = []
                for d in np.linspace(0.0, ml.length, max(3, int(ml.length / 2.0))):
                    x, y, nx, ny = _frame(ml, d)
                    cross = shapely.LineString([(x - nx * 60, y - ny * 60), (x + nx * 60, y + ny * 60)]).intersection(both)
                    ts = [((cx - x) * nx + (cy - y) * ny) for seg in shapely.get_parts(cross)
                          if not seg.is_empty and seg.geom_type == "LineString" for cx, cy in seg.coords]
                    ext.append((d, min(ts) if ts else 0.0, max(ts) if ts else 0.0))
                head = [e for e in ext if PAIR_STEADY_M <= e[0] <= PAIR_STEADY_M + 10.0] or ext[-1:]
                lo_, hi_ = float(np.median([e[1] for e in head])), float(np.median([e[2] for e in head]))
                cut = next((e[0] for e in ext if e[0] > PAIR_STEADY_M and (e[2] - e[1]) > (hi_ - lo_) + 1.0), ml.length)
                if cut < PAIR_MIN_M or cut < 0.8 * min(la.length, lb.length):
                    continue                  # (together for less than PAIR_MIN_M, or for less than 80 % of the shorter line: two ramps that
                                              # leave one node, not one road's two carriageways; they branch where they meet. a9 and a4 at the
                                              # main span's south end: 63 m of 179 m)
                if cut < ml.length - 1.0:
                    ml = shapely.ops.substring(ml, 0.0, max(cut, 1.0))
                    Lp = ml.length
                    qa_end = la.interpolate(ea_ + sa * Lp)
                    sb_end = lb.project(qa_end)
                new = [ml, lo_, hi_, A[3] + Bb[3]]
                keep = [b_ for k_, b_ in enumerate(br) if k_ not in (i, j)] + [new]
                # the parts beyond the pair, each from where it leaves it (the end of the centre line), stay their own branches
                me = shapely.Point(ml.coords[-1])
                for ln_, (lo2, hi2, ids2), s_from in ((la, (A[1], A[2], A[3]), ea_ + sa * Lp), (lb, (Bb[1], Bb[2], Bb[3]), sb_end)):
                    far = ln_.length if (ln_ is la and sa > 0) or (ln_ is lb and sb > 0) else 0.0
                    if abs(far - s_from) > 10.0:
                        part = shapely.ops.substring(ln_, min(s_from, far), max(s_from, far))
                        cs = list(part.coords)
                        if far < s_from:
                            cs = cs[::-1]; lo2, hi2 = -hi2, -lo2           # (oriented away from the pair)
                        keep.append([shapely.LineString([me.coords[0]] + cs), lo2, hi2, ids2])
                br, changed = keep, True
    # a road continues another straight on with about the same width: one branch
    changed = True
    while changed:
        changed = False
        for i in range(len(br)):
            for j in range(i + 1, len(br)):
                if changed:
                    break
                A, Bb = br[i], br[j]
                la, lb = A[0], Bb[0]
                for ea_ in (0.0, la.length):
                    for eb_ in (0.0, lb.length):
                        if changed or la.interpolate(ea_).distance(lb.interpolate(eb_)) > 3.0:
                            continue
                        xa, ya, _, _ = _frame(la, ea_); qa = la.interpolate(min(la.length, 5.0) if ea_ == 0.0 else max(0.0, la.length - 5.0))
                        xb, yb, _, _ = _frame(lb, eb_); qb = lb.interpolate(min(lb.length, 5.0) if eb_ == 0.0 else max(0.0, lb.length - 5.0))
                        va = np.array([qa.x - xa, qa.y - ya]); vb = np.array([qb.x - xb, qb.y - yb])
                        c = float(va @ vb) / ((np.linalg.norm(va) * np.linalg.norm(vb)) or 1)
                        wa, wb = A[2] - A[1], Bb[2] - Bb[1]
                        if c > -0.9 or abs(wa - wb) > max(3.0, 0.25 * max(wa, wb)):
                            continue
                        ca = list(la.coords) if ea_ > 0 else list(la.coords)[::-1]       # A ending at the joint
                        cb = list(lb.coords) if eb_ == 0.0 else list(lb.coords)[::-1]    # B starting at the joint
                        lo_a, hi_a = (A[1], A[2]) if ea_ > 0 else (-A[2], -A[1])
                        lo_b, hi_b = (Bb[1], Bb[2]) if eb_ == 0.0 else (-Bb[2], -Bb[1])
                        lo_n, hi_n = (lo_a, hi_a) if la.length >= lb.length else (lo_b, hi_b)     # (the longer road's width: one width, no widening)
                        new = [shapely.LineString(ca + cb[1:]), lo_n, hi_n, A[3] + Bb[3]]
                        br = [b_ for k_, b_ in enumerate(br) if k_ not in (i, j)] + [new]
                        changed = True
    return [tuple(b_) for b_ in br]


def _smooth_line(ln):
    """A branch's centre line as a smooth curve through OSM's points: resampled every metre, then each point the mean of the line within
    LINE_SMOOTH_M on each side; the two ends stay exactly at OSM's end nodes (the smoothing fades out over the last LINE_SMOOTH_M). A
    polyline widened by a fixed width has a jog at every vertex; a smooth line has smooth edges."""
    import numpy as np
    import shapely
    L = ln.length
    if L < 4 * LINE_SMOOTH_M:
        return ln
    ss = np.linspace(0.0, L, int(L) + 1)
    pts = np.array([ln.interpolate(float(s_)).coords[0] for s_ in ss])
    w = int(LINE_SMOOTH_M)
    out = pts.copy()
    for k in range(len(pts)):
        r = min(w, k, len(pts) - 1 - k)                 # (the window shrinks to 0 at the ends: they stay where OSM puts them)
        if r > 0:
            out[k] = pts[k - r:k + r + 1].mean(axis=0)
    return shapely.LineString(out).simplify(0.02)


def _end_caps(ln):
    """The region between the two end caps of an axis: each cap a line through the end, square to the axis's direction over its last
    END_DIR_M, each kept side the one toward the axis."""
    import shapely
    L = ln.length
    region = ln.buffer(80.0)
    for s_end, s_in in ((L, max(0.0, L - END_DIR_M)), (0.0, min(L, END_DIR_M))):
        p, q = ln.interpolate(s_end), ln.interpolate(s_in)
        dx, dy = q.x - p.x, q.y - p.y                  # (toward the axis)
        n = math.hypot(dx, dy) or 1.0
        dx, dy = dx / n, dy / n
        half = shapely.Polygon([(p.x - dy * 500, p.y + dx * 500), (p.x + dy * 500, p.y - dx * 500),
                                (p.x + dy * 500 + dx * 1000, p.y - dx * 500 + dy * 1000), (p.x - dy * 500 + dx * 1000, p.y + dx * 500 + dy * 1000)])
        region = region.intersection(half)
    return region


def _outline(P):
    """OSM's man_made=bridge outline of the profile, if OSM maps one (rule 5); else None (an outline derived from the sections adds nothing)."""
    import shapely
    o = P["deck"]["outline"]
    if not str(o.get("source", "")).lower().startswith("osm"):
        return None
    return shapely.make_valid(shapely.Polygon(o["value"], o.get("holes") or []))


def _structures(P, axes, a_lv, paths):
    """The axes of each level grouped into structures: [(level, [axis ids], polygon, {axis id: its own strip})]. One structure per
    connected group of a level. Rule 4 inside a group: where two axes run closer than CUT_NEAR_M with heights more than CUT_DZ_M
    apart, the lower one loses that stretch of its strip up to a slit SLIT_M wide along the higher one, so a wall stands there and
    the two never blend; where their heights agree (at their junction) the strips stay joined."""
    import shapely
    from .bridge3d import grid
    strips = _axis_strips(axes, paths)
    by_id = {a["id"]: (ln, a) for ln, a in axes}

    def z_at(aid, p):
        ln, a = by_id[aid]
        return height(a["vertical"], ln.project(p))

    def there(aid, p):          # (the axis exists at p: a point past an end projects onto the end and would compare a height that is not there)
        ln, _ = by_id[aid]
        s_ = ln.project(p)
        return 0.5 < s_ < ln.length - 0.5
    out = []
    for _all in (True,):           # (one pass over all axes: the structures are grouped by connection, not by level)
        ids = [a["id"] for _, a in axes]
        own = {i: strips[i] for i in ids}
        slits = []
        for k, i in enumerate(ids):
            for j in ids[k + 1:]:
                reach = max(CUT_NEAR_M / 2, OUTLINE_NEAR_M + SLIT_M)      # (as far as the outline could join the two: the slit then opens into the real gap)
                near = strips[i].buffer(reach).intersection(strips[j].buffer(reach))
                if near.area < 0.5:
                    continue
                wall = []          # (rank 0's outline comes from the network only: no wall inside a level, Kaveh 2026-10-18)
                if not wall:
                    continue
                W = shapely.union_all(wall).buffer(0.01)
                hi, lo = (i, j) if z_at(i, W.centroid) >= z_at(j, W.centroid) else (j, i)
                slit = strips[hi].intersection(W.buffer(SLIT_M)).buffer(SLIT_M).difference(strips[hi])
                slits.append(slit)
                own[lo] = shapely.make_valid(own[lo].difference(strips[hi].intersection(W.buffer(SLIT_M)).buffer(SLIT_M)))
        # the groups: axes that touch (a shared node, or strips that overlap where their heights agree)
        parent = {i: i for i in ids}

        def find(i):
            while parent[i] != i:
                i = parent[i]
            return i
        ends_ = {i: [shapely.Point(by_id[i][0].coords[0]), shapely.Point(by_id[i][0].coords[-1])] for i in ids}
        for k, i in enumerate(ids):
            for j in ids[k + 1:]:
                same = a_lv[i] == a_lv[j]
                meet = any(p_.distance(q_) < 0.5 for p_ in ends_[i] for q_ in ends_[j])       # (a shared node: one deck, whatever the level)
                if meet or (same and (own[i].intersection(own[j]).area > 0.1 or by_id[i][0].distance(by_id[j][0]) < 0.05)):
                    parent[find(i)] = find(j)
        groups = {}
        for i in ids:
            groups.setdefault(find(i), []).append(i)
        branches = _branches(axes, paths, a_lv)
        for g in groups.values():
            # the structure: its branches, each its line widened by its one width (square ends)
            mine = [br for br in branches if set(br[3]) & set(g)]
            poly = shapely.make_valid(shapely.union_all([_strip(bl, blo, bhi) for bl, blo, bhi, bids in mine] + _transitions(mine)
                                                        or [own[i] for i in g]))
            # one deck across every gap narrower than 2 GORE_M between its bands (a fork, the two carriageways of a loop): the union
            # closed by GORE_M; then no notch and no bump smaller than 2 SMOOTH_M; then the walls of rule 4 cut back in
            poly = poly.buffer(SMOOTH_M, join_style="round").buffer(-2 * SMOOTH_M, join_style="round").buffer(SMOOTH_M, join_style="round")
            if slits:
                poly = poly.difference(shapely.union_all(slits))
            poly = shapely.make_valid(poly)
            out.append((min(a_lv[i] for i in g), g, poly, {i: own[i] for i in g}))
    return out


def _approaches(P, axes, own):
    """The fill at each ground point of an axis (rule 6): the axis's own strip from the ground point to where the surface reaches the
    slab's thickness. Its far edge, straight across the axis, is the abutment. [(polygon, axis id)]"""
    import shapely
    import shapely.ops
    out = []
    for ln, a in axes:
        v, L = a["vertical"], ln.length
        points = [(0.0, 1) for e in a.get("ends", []) if e.get("ground") and e["s"] < 0.01] + \
                 [(L, -1) for e in a.get("ends", []) if e.get("ground") and e["s"] > 0.01] + \
                 [(s_, d_) for s_ in a.get("ground_at", []) for d_ in (1, -1)]
        for s_g, d in points:
            s = s_g
            while 0.0 <= s + d * 0.5 <= L and height(v, s + d * 0.5) < DECK_M:
                s += d * 0.5
            if abs(s - s_g) < 1.0:
                continue
            # the band across the axis between the landing and the abutment; the structure's piece inside it is the fill (model())
            band = _strip(shapely.ops.substring(ln, min(s, s_g), max(s, s_g)), -60.0, 60.0)
            if not band.is_empty:
                out.append((shapely.make_valid(band), a["id"]))
    return out


class _Surface:
    """h(x, y) of one structure: a point takes the heights of the axes whose own strip holds it, blended by nearness; outside every
    strip (the filled edge), the nearest strip's axis."""

    def __init__(self, axes, own):
        self.lines = [ln for ln, _ in axes]
        self.axes = [a for _, a in axes]
        self.own = [own[a["id"]] for _, a in axes]

    def at(self, xs, ys):
        import numpy as np
        import shapely
        pts = shapely.points(np.asarray(xs, dtype=float), np.asarray(ys, dtype=float))
        ds = np.array([shapely.distance(o, pts) for o in self.own])          # (axes x points) to each own strip, 0 inside
        zs = []
        for ln, a in zip(self.lines, self.axes):
            s = shapely.line_locate_point(ln, pts)
            d = shapely.distance(ln, pts)
            zs.append((np.array([max(0.0, height(a["vertical"], float(s_))) for s_ in s]), d))
        # one continuous blend everywhere: each band pulls toward its own height by 1 / (distance to the band + NEAR_M)^2 (0 inside it);
        # no switch of rule at a band's edge, so no crease in the surface and no step along the deck's edge
        out = np.zeros(len(pts)); wsum = np.zeros(len(pts))
        for q, (z_, d_) in enumerate(zs):
            w = 1.0 / (ds[q] + NEAR_M) ** 2
            out += w * z_; wsum += w
        out = out / wsum
        return out

    def one(self, x, y):
        return float(self.at([x], [y])[0])


def _trim_to_osm(con, P):
    """Each axis cut back to OSM's bridge ways: a landing that the LiDAR profile added past OSM's last node (`landings`, bridge_lidar)
    gives heights only, no length (Kaveh, 2026-10-17: the start and end of a bridge come from OSM). The cut end is on the ground.
    The vertical profile's s values move with the cut."""
    import shapely
    import shapely.ops
    for a in P["axes"]:
        ln = shapely.LineString([q[:2] for q in a["line"]["value"]])
        cut_start = sum(float(l_.get("length_m") or 0) for l_ in a.get("landings", []) if l_.get("end") == "start")
        cut_end = sum(float(l_.get("length_m") or 0) for l_ in a.get("landings", []) if l_.get("end") == "end")
        if cut_start < 0.5 and cut_end < 0.5:
            continue
        s0, s1 = cut_start, ln.length - cut_end
        cut = shapely.ops.substring(ln, s0, s1)
        a["line"]["value"] = [[round(x, 2), round(y, 2)] for x, y in cut.coords]
        a["length_m"] = round(cut.length, 2)
        v = a["vertical"]
        v["points"] = [[round(s - s0, 2), z] for s, z in v["points"] if s0 - 0.01 <= s <= s1 + 0.01] or [[0.0, 0.0], [round(cut.length, 2), 0.0]]
        if v["points"][0][0] > 0.01:
            v["points"].insert(0, [0.0, v["points"][0][1]])
        if v["points"][-1][0] < cut.length - 0.01:
            v["points"].append([round(cut.length, 2), v["points"][-1][1]])
        v["curves"] = None
        a["ground_at"] = [round(g - s0, 2) for g in a.get("ground_at", []) if s0 + 0.5 < g < s1 - 0.5]
        ends = a.get("ends", [{}, {}])
        a["ends"] = [{"s": 0.0, "ground": True if cut_start >= 0.5 else ends[0].get("ground", False), "node": None if cut_start >= 0.5 else ends[0].get("node")},
                     {"s": round(cut.length, 2), "ground": True if cut_end >= 0.5 else ends[-1].get("ground", False),
                      "node": None if cut_end >= 0.5 else ends[-1].get("node")}]
        for sec in a.get("sections", []):
            sec["s0"], sec["s1"] = max(0.0, sec["s0"] - s0), min(cut.length, sec["s1"] - s0)
            for b in sec.get("bands") or []:
                for k in ("s_from", "s_to"):
                    if b.get(k) is not None:
                        b[k] = min(max(b[k] - s0, 0.0), cut.length)
        a["sections"] = [sec for sec in a.get("sections", []) if sec["s1"] - sec["s0"] > 0.1]
        a["trimmed_to_osm_m"] = [round(cut_start, 1), round(cut_end, 1)]
    return P


# ---------------------------------------------------------------- 3. the model
def model(con, P, rank0=False, cover=True, gmns=None):
    """One bridge's 3D model. gmns (the bridge's SUMO via duckOSM GMNS): step 5 of docs/notes/bridge-steps.md, the structure (rank 0) on the
    accepted steps 1 to 4: its outline is step 3b's smooth outline of each level, and each axis's heights count where its own bands lie
    (step 4: SUMO's lanes on its ways, its OSM paths); no cover yet (step 6). Without gmns: the outline from bridge_cover.layout, as before."""
    import copy
    import numpy as np
    import pyproj
    import shapely
    import shapely.ops
    from .bridge3d import grid
    from .bridge_structure import structure
    crs = P["crs"]
    from .bridge_cover import layout
    P_raw = copy.deepcopy(P)          # (before the trim: steps_3b_4 trims its own copy)
    _trim_to_osm(con, P)             # (no corrections file: the lanes are SUMO's; an OSM fault goes to duckOSM's overrides)
    axes = [(shapely.LineString([q[:2] for q in a["line"]["value"]]), a) for a in P["axes"]]
    _LANES.clear()    # (the profile's own lanes, as the old model: Kaveh 2026-10-18)
    a_lv = _axis_level(con, P)
    nodes, per_axis, pairs = _nodes(P, a_lv)
    h, res = _solve(P, nodes, per_axis, pairs, _couplings(P, nodes, per_axis, a_lv))
    _write_back(P, nodes, per_axis, h)
    # the deck is what lies on it: the lanes, the junction lanes and the paths, plus the edge (bridge_cover, rule 6); each axis's own
    # lanes and paths set where its heights count (_Surface)
    if gmns:
        from .bridge_forks import steps_3b_4
        # (on a copy: the steps trim the profile to OSM's ends themselves, and a second trim would cut the landings again)
        s_axes, s_lv, R_, B_, F_, outline, S4 = steps_3b_4(con, copy.deepcopy(P_raw), gmns)
        own = {}
        for ln_, a_ in axes:
            ways_ = set(a_["ways"])
            g_ = [b_["poly"] for b_ in S4["bands"] if (b_["kind"] == "lane" and b_["props"].get("osm") in ways_)
                  or (b_["kind"] in ("sidewalk", "cycle lane") and b_["props"].get("axis") == a_["id"])]
            own[a_["id"]] = shapely.union_all(g_).buffer(EDGE_M) if g_ else ln_.buffer(1.0)
        structs = [(lv, [aid for aid, l_ in a_lv.items() if l_ == lv], pg, own) for lv, pg in outline.items()]
        cover = False                     # (step 6 lays the cover on this structure, later)
    else:
        cov = layout(P, axes, a_lv)
        structs = [(lv, [aid for aid, l_ in a_lv.items() if l_ == lv], pg, cov["own"]) for lv, pg in cov["deck"].items()]
    by_id = {a["id"]: (ln, a) for ln, a in axes}
    all_poly = shapely.union_all([pg for _, _, pg, _ in structs])

    # the frame: the map's metres about the bridge's middle (as bridge3d and deck3d)
    c0 = all_poly.centroid
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
    slab, sides, surf = [], [], []
    d1, d2, d3, d6, d7, d2_dbg, parapet_dbg = [], [], [], [], [], [], []
    ll = lambda x, y: list(to_ll(x, y))
    ground_pts = [shapely.Point(nd["xy"]) for nd in nodes if nd["ground"]]
    ground_mp = shapely.MultiPoint(ground_pts) if ground_pts else None
    # one piece per polygon of a structure, from landing to landing: the slab's bottom is max(h - DECK_M, 0), so near a landing the
    # structure is solid to the ground (rule 6) with no seam, no separate fill (a separate fill piece showed every seam: 2026-10-17)
    pieces = []        # (level, polygon, surface, axis ids, kind)
    for lv, ids, poly, own in structs:
        S = _Surface([by_id[i] for i in ids], own)
        for pg in shapely.get_parts(poly):
            if pg.geom_type == "Polygon" and pg.area >= 1.0:
                # no hole in a structure (Kaveh, 2026-10-17): a hole narrower than 2 GORE_M is filled; a real opening (a loop's middle) stays
                keep_ = [r for r in pg.interiors if not shapely.Polygon(r).buffer(-GORE_M).is_empty]
                pieces.append((lv, shapely.Polygon(pg.exterior, keep_), S, ids, "slab"))
    from shapely.geometry.polygon import orient
    pieces = [(lv, orient(pg), S, ids, kind) for lv, pg, S, ids, kind in pieces]      # (rings one way round: the sides face outward)
    for lv, pg, S, ids, kind in pieces:
        tris = grid(pg, STEP_M)
        tri_list = [t for t in [tt for c in tris for tt in _tris(c)]]
        if not tri_list:
            continue
        xs = np.array([x for t in tri_list for x, y in t]); ys = np.array([y for t in tri_list for x, y in t])
        hs = S.at(xs, ys).reshape(-1, 3)
        ring = pg.exterior
        edge_use = {}
        fill_v, fill_f, fill_ix = [], [], {}

        def fv(x, y, zz):
            q = (round(x, 2), round(y, 2), round(zz, 2))
            if q not in fill_ix:
                fill_ix[q] = len(fill_v)
                fill_v.append(tm(x, y, zz))
            return fill_ix[q]
        for t, hz in zip(tri_list, hs):
            top = [vid(x, y, z) for (x, y), z in zip(t, hz)]
            if rank0:                  # the surface only
                slab.append(top)
            elif kind == "approach":   # the fill from the ground up to the surface (ground of level 0), up to the abutment
                fill_f.append([fv(x, y, z) for (x, y), z in zip(t, hz)])
            else:
                slab.append(top)
                slab.append([vid(x, y, max(0.0, z - DECK_M)) for (x, y), z in zip(t, hz)][::-1])
            # D1: every edge of the top is shared, or lies on the piece's edge
            for p, q in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                k = tuple(sorted((tuple(round(v, 2) for v in p), tuple(round(v, 2) for v in q))))
                edge_use[k] = edge_use.get(k, 0) + 1
            # D2: a steep face inside the structure
            (x0_, y0_), (x1_, y1_), (x2_, y2_) = t
            run = max(math.dist(t[0], t[1]), math.dist(t[1], t[2]), math.dist(t[2], t[0]))
            if hz.max() - hz.min() > 0.3 and math.degrees(math.atan2(hz.max() - hz.min(), run)) > STEEP_DEG:     # (a wall, not a sliver)
                d2.append(ll((x0_ + x1_ + x2_) / 3, (y0_ + y1_ + y2_) / 3))
                if len(d2_dbg) < 40:
                    d2_dbg.append({"kind": kind, "run": round(run, 2), "hz": [round(float(z), 2) for z in hz], "xy": [round(x0_, 1), round(y0_, 1)],
                                   "strips": [i for i in ids if S.own[[a["id"] for a in S.axes].index(i)].distance(shapely.Point(x0_, y0_)) < 0.05]})
        for k, nuse in edge_use.items():
            if nuse == 1:
                mid = shapely.Point((k[0][0] + k[1][0]) / 2, (k[0][1] + k[1][1]) / 2)
                if pg.boundary.distance(mid) > 0.05:
                    d1.append(ll(mid.x, mid.y))
        if fill_f:
            surf.append({"key": "approach", "props": {"id": f"approach {P['name']} L{lv}", "type": "approach", "bridge": P["name"],
                                                       "level": 0, "source": "urbanstyle", "method": "derived",
                                                       "rule": "the fill between the end of the slab and the landing: ground of level 0"},
                         "v": fill_v, "f": fill_f})
        # the sides along the outer edge, and the parapet where the edge is not a landing and not a joint
        if rank0:
            continue
        others_S = [(pg2, S2) for lv2, pg2, S2, _, _ in pieces if lv2 == lv and pg2 is not pg]
        keep = []
        n_low = n_joint = 0
        for rg in [ring] + list(pg.interiors):
            cs = list(rg.segmentize(STEP_M / 2).coords)
            for (ax, ay), (bx, by) in zip(cs, cs[1:]):
                za, zb = S.one(ax, ay), S.one(bx, by)
                if max(za, zb) > 0.05:
                    a0, b0, a1, b1 = vid(ax, ay, max(0.0, za - DECK_M)), vid(bx, by, max(0.0, zb - DECK_M)), vid(ax, ay, za), vid(bx, by, zb)
                    sides += [[a0, b0, b1], [a0, b1, a1]]
                mid = shapely.Point((ax + bx) / 2, (ay + by) / 2)
                zm = (za + zb) / 2
                if zm < 0.05:                       # the landing line itself, on the ground: open (the sides keep their parapet to it)
                    n_low += 1
                    continue
                if ground_mp is not None and ground_mp.distance(mid) < 0.5 and zm > 0.1:
                    d3.append(ll(mid.x, mid.y))
                joint = any(pg2.distance(mid) < JOINT_M and abs(S2.one(mid.x, mid.y) - zm) <= CUT_DZ_M for pg2, S2 in others_S)
                if joint:
                    n_joint += 1
                    continue                        # the next structure of its level at the same height: the road goes on
                keep.append(shapely.LineString([(ax, ay), (bx, by)]))
        parapet_dbg.append((kind, round(pg.area), "ring", round(pg.exterior.length), "keep", len(keep), "low", n_low, "joint", n_joint))
        if keep:
            merged = shapely.line_merge(shapely.union_all(keep))
            for l_ in shapely.get_parts(merged):
                if l_.length < 3.0:
                    d7.append(ll(*l_.interpolate(0.5, normalized=True).coords[0]))
            band = shapely.union_all([l_.buffer(GUARD_M[1], cap_style="flat") for l_ in shapely.get_parts(merged)])
            band = band.intersection(pg)
            _mesh(band, "barrier", {"id": f"parapet {P['name']} L{lv}", "type": "barrier", "bridge": P["name"], "height_m": GUARD_M[0],
                                     "source": "urbanstyle", "method": "derived", "rule": "the parapet along the structure's edge, not at a landing or a joint"},
                  S, GUARD_M[0], tm, surf, grid)
    ends_mp = shapely.MultiPoint([shapely.Point(ln.coords[0]) for ln, _ in axes] + [shapely.Point(ln.coords[-1]) for ln, _ in axes])
    # D8: a jog in an edge: a turn of more than JOG_DEG between two edge segments shorter than JOG_M (a step, a notch, a bump)
    d8 = []
    for lv, pg, S, ids, kind in pieces:
        cs = list(pg.exterior.simplify(0.05).coords)
        for (x0, y0), (x1, y1), (x2, y2) in zip(cs, cs[1:], cs[2:]):
            l1, l2 = math.hypot(x1 - x0, y1 - y0), math.hypot(x2 - x1, y2 - y1)
            if min(l1, l2) < 0.05:
                continue
            ang = abs(math.degrees(math.atan2((x1 - x0) * (y2 - y1) - (y1 - y0) * (x2 - x1), (x1 - x0) * (x2 - x1) + (y1 - y0) * (y2 - y1))))
            if ang > JOG_DEG and (l1 < JOG_M or l2 < JOG_M) and (ends_mp is None or ends_mp.distance(shapely.Point(x1, y1)) > BRANCH_M):
                d8.append(ll(x1, y1))                 # (a step at a node where axes meet is a branch: the width changes there)
    # ---- the cover (ranks 1 to 6), made from the same profile as the structure so it fills the deck by construction
    if cover and not rank0:
        for g, key, lift, rise, props in cov["items"]:
            for lv, pg, S, ids, kind in pieces:
                if lv == props.get("level"):
                    q = shapely.make_valid(g.intersection(pg))
                    if not q.is_empty and q.area > 0.01:
                        _mesh_flat(q, key, dict(props, layer="cover"), S, lift, rise, tm, surf, grid)
        # the rest of each slab is paved: also where a hole of the deck was filled (no hole in a structure), which the cover has no piece of
        for lv, pg, S, ids, kind in pieces:
            on = shapely.union_all([g for g, key, *_r, props in cov["items"] if props.get("level") == lv and not key.startswith("mark")]
                                   or [shapely.Polygon()])
            q = shapely.make_valid(pg.difference(on))
            if not q.is_empty and q.area > 0.01:
                _mesh_flat(q, "paved", {"type": "paved", "bridge": P["name"], "layer": "cover"}, S, 0.03, 0.0, tm, surf, grid)
    # D6: two structures of one level overlapping
    for i, (lv, pg, _, _, _) in enumerate(pieces):
        for lv2, pg2, _, _, _ in pieces[i + 1:]:
            if lv == lv2:
                ov = pg.intersection(pg2)
                if ov.area > 0.5:
                    d6.append(ll(*ov.representative_point().coords[0]))
    # the piers and the truss, from the profile (its heights are the solved ones now)

    def frame(ln, s_):
        p_, a_, b_ = ln.interpolate(s_), ln.interpolate(max(s_ - 1, 0)), ln.interpolate(min(s_ + 1, ln.length))
        h_ = math.hypot(b_.x - a_.x, b_.y - a_.y) or 1
        return p_.x, p_.y, -(b_.y - a_.y) / h_, (b_.x - a_.x) / h_
    piers_p, truss_p = structure(P, axes, all_poly, frame, DECK_M) if not rank0 else ([], [])
    piers = [{"a": tm(*q["a"], 0)[:2], "b": tm(*q["b"], 0)[:2], "t": q["t"], "h": q["h"]} for q in piers_p if q["h"] >= PIER_MIN_M]   # (none under a low deck: a half-metre pier at a landing looked like a disc)
    truss = [dict(q, a=tm(*q["a"]), b=tm(*q["b"])) for q in truss_p]
    unmet = [ll(*c["at"]) + [round(c["z"] - height(a["vertical"], ln.project(shapely.Point(c["at"]))), 2)]
             for ln, a in axes for c in a["vertical"].get("clearances", [])
             if ln.distance(shapely.Point(c["at"])) < 1.0 and not str(c.get("over", "")).startswith("deck") and not c.get("met", True)]
    unmet += [ll(*nodes[i]["xy"]) + [round(float(LEVEL_M + DECK_M - (h[i] - h[j])), 2)] for i, j in pairs if h[i] - h[j] < LEVEL_M + DECK_M - 0.05]
    checks = [("D1", "edges of the height surface no neighbour shares (a hole or a tear)", len(d1), True, d1),
              ("D2", f"faces steeper than {STEEP_DEG:.0f} degrees inside a structure", len(d2), True, d2),
              ("D3", "landing points higher than 0.1 m", len(d3), True, d3),
              ("D4", "clearances the grade cannot reach, with the gap in m", len(unmet), False, [u[:2] for u in unmet]),
              ("D6", "two structures of one level overlapping", len(d6), True, d6),
              ("D7", "parapet pieces shorter than 3 m (a fragment at a step or a corner)", len(d7), True, d7),
              ("D8", f"jogs in an edge: a turn over {JOG_DEG:.0f} degrees beside a segment under {JOG_M:.0f} m (a step, a notch, a bump)", len(d8), True, d8)]
    deck_ll = json.loads(shapely.to_geojson(shapely.ops.transform(to_ll, all_poly)))
    return {"name": P["name"], "origin": [lon0, lat0], "verts": verts, "deck": slab, "sides": sides, "rails": [],
            "axes": [[list(to_ll(x, y)) for x, y in a["line"]["value"]] for a in P["axes"]], "lines": [], "lanes": [], "piers": piers,
            "truss": truss, "surf": surf, "checks": checks, "flat": [], "deck_ll": deck_ll,
            "structures": [{"level": lv, "axes": ids, "kind": kind, "area_m2": round(pg.area, 1)} for lv, pg, _, ids, kind in pieces],
            "solve": {"ok": bool(res.success), "message": str(res.message), "nodes": len(nodes)},
            "heights": {a["id"]: a["vertical"]["points"] for a in P["axes"]},
            "trimmed": {a["id"]: a["trimmed_to_osm_m"] for a in P["axes"] if a.get("trimmed_to_osm_m")},
            "d2_dbg": d2_dbg, "parapet_dbg": parapet_dbg,
            "unmet": unmet,
            "sources": {"model": "bridge_surface: the structure from one height surface (docs/notes/bridges-ranks.md)"}}


def _tris(cell):
    """A grid cell (a polygon, concave where a slit or the edge cuts it) as triangles inside it (constrained Delaunay)."""
    import shapely
    out = []
    for pg in shapely.get_parts(cell):
        if pg.geom_type != "Polygon" or pg.area < 1e-6:     # (only pieces with no area: a 0.01 m2 sliver cell at the edge left a tear, D1)
            continue
        for t in shapely.get_parts(shapely.constrained_delaunay_triangles(pg)):
            if t.area > 1e-6:
                c = list(t.exterior.coords[:3])
                (x0, y0), (x1, y1), (x2, y2) = c
                if (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0) < 0:     # (counter-clockwise, seen from above: one lit side for all)
                    c = [c[0], c[2], c[1]]
                out.append(tuple(c))
    return out


def _moves(P):
    """The band-to-band links of a bridge (the profile's `connectors`: SUMO's lane connectors, via duckOSM GMNS) between two axes, each
    with its junction node and its turn: [(connector, (axis, direction, lane) from, ... to, node, turn in degrees, a move)]. A link that
    turns more than MAX_TURN_DEG is not a move: a bridge has no U-turn, and where OSM maps no turn restriction SUMO links every lane in
    to every lane out (Granville: 6 links of 113 to 141 degrees; every real move turns 30 degrees or less)."""
    import math
    band = {b["lane_id"]: (a["id"], b.get("direction"), b.get("lane")) for a in P["axes"] for sec in a.get("sections", [])
            for b in sec.get("bands", []) if b.get("lane_id")}
    ends = {}
    for a in P["axes"]:
        ln = a["line"]["value"]
        for e, q in zip(a["ends"], (ln[0], ln[-1])):
            if e.get("node"):
                ends.setdefault(e["node"], q[:2])
    hd = lambda p, q: math.degrees(math.atan2(q[1] - p[1], q[0] - p[0]))
    out = []
    for c in P.get("connectors", []):
        f, t, ln = band.get(c["from"]), band.get(c["to"]), c["line"]
        if not f or not t or f[0] == t[0] or len(ln) < 2 or not ends:
            continue
        turn = (hd(ln[-2], ln[-1]) - hd(ln[0], ln[1]) + 180) % 360 - 180
        node = min(ends, key=lambda k: math.dist(ends[k], ln[len(ln) // 2]))
        out.append((c, f, t, node, round(turn), abs(turn) <= MAX_TURN_DEG))
    return out


PATH_RUN_M = 5.0      # a path's stretch beside one axis shorter than this belongs to the axis before it (no flicker at a junction node)


def _path_bands(P, axes):
    """The walking and cycling bands of a bridge: each sidewalk, cycleway or shared path of the profile (`paths`, not a crossing) is a band
    of the axis it runs beside, cut where it passes from one axis to the next; its line is its own OSM line, its width the path's width.
    Two bands are connected where they are pieces of one OSM way, or where their OSM ways share a node; with no such source they are not
    connected and each ends there (flat). Returns (bands, joints): bands [{axis, side, s0, s1, way, kind, line, width}], joints
    [{at, bands: (i, j), why}] with i, j indexes into bands."""
    import math
    import numpy as np
    import shapely
    import shapely.ops
    val = lambda v: v["value"] if isinstance(v, dict) else v
    bands, ends = [], []
    for p in P.get("paths", []):
        if p.get("footway") == "crossing" or len(val(p["line"])) < 2:
            continue
        ln = shapely.LineString([q[:2] for q in val(p["line"])])
        kind = "cycle lane" if p.get("type") == "cycleway" or p.get("bicycle") == "designated" else "sidewalk"
        ds = np.linspace(0.0, ln.length, max(2, int(ln.length) + 1))
        near = [min(axes, key=lambda la: la[0].distance(ln.interpolate(d)))[1]["id"] for d in ds]
        runs = []                                       # [(axis id, from index, to index)], short runs given to the run before
        for k, a_id in enumerate(near):
            if runs and runs[-1][0] == a_id:
                runs[-1][2] = k
            else:
                runs.append([a_id, k, k])
        merged = []
        for r in runs:
            if merged and ds[r[2]] - ds[r[1]] < PATH_RUN_M:
                merged[-1][2] = r[2]
            elif merged and merged[-1][0] == r[0]:
                merged[-1][2] = r[2]
            else:
                merged.append(r)
        first = len(bands)
        for a_id, k0, k1 in merged:
            d0, d1 = ds[k0] if k0 == merged[0][1] else (ds[k0] + ds[k0 - 1]) / 2, ds[k1] if k1 == merged[-1][2] else (ds[k1] + ds[k1 + 1]) / 2
            piece = shapely.ops.substring(ln, d0, d1)
            ax, ax_a = next((la, a) for la, a in axes if a["id"] == a_id)
            # a path band ends where its bridge ends on the ground: OSM's path way runs on past it, onto the ground (a tail past
            # the deck at a2, a3, a5 and a8 of Granville); at a junction node the next axis's band takes it on
            gr = [bool(e.get("ground")) for e in ax_a.get("ends", [{}, {}])]
            if any(gr):
                cs = list(ax.coords)
                (x0, y0), (x1, y1), (x2, y2), (x3, y3) = cs[0], cs[1], cs[-2], cs[-1]
                h0, h1 = math.hypot(x1 - x0, y1 - y0) or 1.0, math.hypot(x3 - x2, y3 - y2) or 1.0
                run = 0.0 if gr[0] else 60.0
                run1 = 0.0 if gr[-1] else 60.0
                body = shapely.LineString([(x0 - (x1 - x0) / h0 * run, y0 - (y1 - y0) / h0 * run)] + cs[1:-1]
                                          + [(x3 + (x3 - x2) / h1 * run1, y3 + (y3 - y2) / h1 * run1)])
                kept = [g for g in shapely.get_parts(piece.intersection(body.buffer(40.0, cap_style="flat"))) if g.geom_type == "LineString"]
                if not kept:
                    continue
                piece = max(kept, key=lambda g: g.length)
            if piece.length < 0.5:
                continue
            m = piece.interpolate(0.5, normalized=True)
            x, y, nx, ny = _frame(ax, ax.project(m))
            bands.append({"axis": a_id, "side": "left" if (m.x - x) * nx + (m.y - y) * ny > 0 else "right",
                          "s0": round(min(ax.project(shapely.Point(piece.coords[0])), ax.project(shapely.Point(piece.coords[-1]))), 1),
                          "s1": round(max(ax.project(shapely.Point(piece.coords[0])), ax.project(shapely.Point(piece.coords[-1]))), 1),
                          "way": p.get("way"), "kind": kind, "line": piece, "width": float(val(p.get("width")) or 2.0)})
        ends.append((p.get("way"), first, len(bands) - 1, ln.coords[0], ln.coords[-1]))
    joints = []
    for way, i0, i1, _, _ in ends:                      # pieces of one OSM way: end to end
        for i in range(i0, i1):
            joints.append({"at": bands[i]["line"].coords[-1], "bands": (i, i + 1), "why": f"one OSM way {way}"})
    for k, (w1, a0, a1_, p0, p1) in enumerate(ends):    # two ways that share a node (an end of one on the other's line)
        for w2, b0, b1_, q0, q1 in ends[k + 1:]:
            if a1_ < a0 or b1_ < b0:
                continue
            for pt, i in ((p0, a0), (p1, a1_)):
                for j in range(b0, b1_ + 1):
                    if bands[j]["line"].distance(shapely.Point(pt)) < 0.3:
                        joints.append({"at": pt, "bands": (i, j), "why": f"OSM ways {w1} and {w2} share a node"}); break
            for pt, j in ((q0, b0), (q1, b1_)):
                for i in range(a0, a1_ + 1):
                    if bands[i]["line"].distance(shapely.Point(pt)) < 0.3 and not any(set(jt["bands"]) == {i, j} for jt in joints):
                        joints.append({"at": pt, "bands": (i, j), "why": f"OSM ways {w1} and {w2} share a node"}); break
    return bands, joints


def _mesh_flat(poly, key, props, S, lift, rise, tm, surf, grid):
    """A part of the cover on the surface: its top at h + lift + rise; a raised part (rise > 0) gets its faces down to h + lift."""
    import shapely
    v, f, ix = [], [], {}

    def vi(x, y, zz):
        q = (round(x, 2), round(y, 2), round(zz, 2))
        if q not in ix:
            ix[q] = len(v)
            v.append(tm(x, y, zz))
        return ix[q]
    for pg in shapely.get_parts(shapely.make_valid(poly)):
        if pg.geom_type != "Polygon" or pg.area < 1e-6:     # (only pieces with no area: a 0.01 m2 sliver cell at the edge left a tear, D1)
            continue
        for c in grid(pg, STEP_M):
            for t in _tris(c):
                f.append([vi(x, y, S.one(x, y) + lift + rise) for x, y in t])
        if rise > 0:
            for ring in [pg.exterior] + list(pg.interiors):
                cs = list(ring.segmentize(STEP_M / 2).coords)
                for (ax, ay), (bx, by) in zip(cs, cs[1:]):
                    za, zb = S.one(ax, ay) + lift, S.one(bx, by) + lift
                    a0, b0, a1, b1 = vi(ax, ay, za), vi(bx, by, zb), vi(ax, ay, za + rise), vi(bx, by, zb + rise)
                    f += [[a0, b0, b1], [a0, b1, a1]]
    if f:
        surf.append({"key": key, "props": props, "v": v, "f": f})


def _mesh(poly, key, props, S, rise, tm, surf, grid):
    """A raised band on the surface (the parapet): its top at h + rise, its faces down to h."""
    import shapely
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
        for c in grid(pg, STEP_M):
            for t in _tris(c):
                f.append([vi(x, y, S.one(x, y) + rise) for x, y in t])
        for ring in [pg.exterior] + list(pg.interiors):
            cs = list(ring.segmentize(STEP_M / 2).coords)
            for (ax, ay), (bx, by) in zip(cs, cs[1:]):
                za, zb = S.one(ax, ay), S.one(bx, by)
                a0, b0, a1, b1 = vi(ax, ay, za), vi(bx, by, zb), vi(ax, ay, za + rise), vi(bx, by, zb + rise)
                f += [[a0, b0, b1], [a0, b1, a1]]
    if f:
        surf.append({"key": key, "props": props, "v": v, "f": f})


def plan_html(con, P, out):
    """A 2D plan of a bridge's rank 0, to check the geometry: each branch's centre line and its band (its one width) in its own colour,
    the transitions, the final edge of each structure, with each branch's name and width. Drag to move, wheel to zoom."""
    import html as _html
    import shapely
    from .bridge3d import correct_sections
    correct_sections(P)              # (the agreed lane corrections, corrections/lanes.json, as the old model: Fir ramp 2 lanes)
    _trim_to_osm(con, P)
    axes = [(shapely.LineString([q[:2] for q in a["line"]["value"]]), a) for a in P["axes"]]
    _LANES.clear()    # (the profile's own lanes, as the old model: Kaveh 2026-10-18)
    a_lv = _axis_level(con, P)
    nodes, per_axis, pairs = _nodes(P, a_lv)
    h, _ = _solve(P, nodes, per_axis, pairs, _couplings(P, nodes, per_axis, a_lv))
    _write_back(P, nodes, per_axis, h)
    val = lambda v: v["value"] if isinstance(v, dict) else v
    paths = [shapely.LineString([q[:2] for q in val(p["line"])]).buffer((val(p.get("width")) or 2.0) / 2)
             for p in P.get("paths", []) if len(val(p["line"])) >= 2]
    branches = _branches(axes, paths, a_lv)
    structs = _structures(P, axes, a_lv, paths)
    allg = shapely.union_all([pg for _, _, pg, _ in structs] + [l_.buffer(20) for l_, *_ in branches])
    x0, y0, x1, y1 = allg.bounds
    fs = max(4.0, (x1 - x0) / 110)  # (labels readable when the whole bridge is in view)
    cols = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#46f0f0", "#f032e6", "#9a6324", "#008080", "#800000", "#808000", "#000075"]
    ox, oy = x0, y1                               # (local coordinates: an SVG is drawn in single precision, UTM numbers lose 0.5 m)
    X = lambda x: x - ox
    Y = lambda y: oy - y                          # (north up)

    def ring(r):
        return "M" + " L".join(f"{X(x):.2f},{Y(y):.2f}" for x, y in r.coords) + " Z"

    def poly_d(g):
        d = []
        for pg in shapely.get_parts(g):
            if pg.geom_type == "Polygon":
                d.append(ring(pg.exterior) + "".join(ring(r) for r in pg.interiors))
        return " ".join(d)
    svg = []
    for _, _, pg, _ in structs:
        svg.append(f'<path d="{poly_d(pg)}" fill="#ddd6cc" stroke="none"/>')
    for k, (bl, lo, hi, ids) in enumerate(branches):
        c = cols[k % len(cols)]
        band = _strip(bl, lo, hi)
        svg.append(f'<path d="{poly_d(band)}" fill="{c}" fill-opacity="0.12" stroke="{c}" stroke-width="1" class="br" vector-effect="non-scaling-stroke"/>')
    for g in _transitions(branches):
        svg.append(f'<path d="{poly_d(g)}" fill="none" stroke="#000" stroke-width="1" stroke-dasharray="4 3" class="br" vector-effect="non-scaling-stroke"/>')
    for _, _, pg, _ in structs:
        svg.append(f'<path d="{poly_d(pg)}" fill="none" stroke="#111" stroke-width="2" vector-effect="non-scaling-stroke"/>')
    for k, (bl, lo, hi, ids) in enumerate(branches):
        c = cols[k % len(cols)]
        svg.append(f'<polyline points="{" ".join(f"{X(x):.2f},{Y(y):.2f}" for x, y in bl.coords)}" fill="none" stroke="{c}" stroke-width="2" class="br" vector-effect="non-scaling-stroke"/>')
        m = bl.interpolate(0.5, normalized=True)
        svg.append(f'<text x="{X(m.x):.1f}" y="{Y(m.y):.1f}" font-size="{fs:.1f}" fill="{c}" stroke="#fff" stroke-width="{fs / 6:.2f}" paint-order="stroke" class="br">'
                   f'{_html.escape("+".join(ids))}  {hi - lo:.1f} m</text>')
    for k, (ln, a) in enumerate(axes):   # the profile's split: each axis, a tick where a section ends, a ring where an axis ends at a node
        c = cols[k % len(cols)]
        svg.append(f'<polyline points="{" ".join(f"{X(x):.2f},{Y(y):.2f}" for x, y in ln.coords)}" fill="none" stroke="{c}" stroke-width="3" class="ax" vector-effect="non-scaling-stroke"/>')
        for sec in a.get("sections", [])[1:]:
            x, y, nx, ny = _frame(ln, float(sec["s0"]))
            svg.append(f'<line x1="{X(x - nx * 4):.2f}" y1="{Y(y - ny * 4):.2f}" x2="{X(x + nx * 4):.2f}" y2="{Y(y + ny * 4):.2f}" '
                       f'stroke="#000" stroke-width="1.5" class="ax" vector-effect="non-scaling-stroke"/>')
        for e in a["ends"]:
            if not e["ground"]:
                p_ = ln.interpolate(float(e["s"]))
                svg.append(f'<circle cx="{X(p_.x):.1f}" cy="{Y(p_.y):.1f}" r="2.2" fill="#fff" stroke="#000" stroke-width="1" class="ax" data-node="{e["node"]}" vector-effect="non-scaling-stroke"/>')
        m = ln.interpolate(0.3, normalized=True)
        svg.append(f'<text x="{X(m.x):.1f}" y="{Y(m.y):.1f}" font-size="{fs:.1f}" fill="{c}" stroke="#fff" stroke-width="{fs / 6:.2f}" paint-order="stroke" font-weight="bold" class="ax">{a["id"]}</text>')
    for c, f, t, node, turn, ok in _moves(P):     # the band-to-band links between axes: a move dark, a link that turns back red
        pts_ = " ".join(f"{X(x):.2f},{Y(y):.2f}" for x, y, *_ in c["line"])
        look = 'stroke="#111" stroke-width="1.5" marker-end="url(#mv)"' if ok else 'stroke="#d00" stroke-width="2" stroke-dasharray="3 2" marker-end="url(#mvx)"'
        svg.append(f'<polyline points="{pts_}" fill="none" {look} class="mv" vector-effect="non-scaling-stroke"/>')
    for nd in nodes:
        if nd["ground"]:
            svg.append(f'<circle cx="{X(nd["xy"][0]):.1f}" cy="{Y(nd["xy"][1]):.1f}" r="1.2" fill="#000"/>')
    w, hgt = x1 - x0, y1 - y0
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>Plan: {_html.escape(P['name'])}</title>
<style>html,body{{margin:0;height:100%;background:#fafaf5;font-family:sans-serif}}svg{{width:100%;height:100%;cursor:grab}}
#k{{position:absolute;left:10px;top:8px;background:#fff;padding:6px 10px;border-radius:6px;box-shadow:0 1px 4px #0003;font-size:13px}}</style></head><body>
<div id="k"><b>{_html.escape(P['name'])}: rank 0 in plan</b><br>coloured line: a branch's centre line &middot; coloured band: its one width &middot;
dashed: a transition where a branch leaves &middot; black: the deck's edge &middot; dot: a point on the ground<br>
a1, a2, ...: an axis &middot; ring: a junction node, where an axis ends (three or more road ends meet) &middot; tick: a section ends (a GMNS link ends there)<br>\nblack arrow: a band-to-band move between two axes (SUMO) &middot; red dashed arrow: a link that turns back over 90 degrees, left out<br><small>drag: move &middot; wheel: zoom</small></div>
<svg id="s" viewBox="0 0 {w:.1f} {hgt:.1f}" xmlns="http://www.w3.org/2000/svg"><defs>
<marker id="mv" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#111"/></marker>
<marker id="mvx" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#d00"/></marker></defs>{''.join(svg)}</svg>
<script>const s=document.getElementById('s');let v=s.viewBox.baseVal,d=null;
s.onmousedown=e=>{{d={{x:e.clientX,y:e.clientY}};s.style.cursor='grabbing'}};window.onmouseup=()=>{{d=null;s.style.cursor='grab'}};
window.onmousemove=e=>{{if(!d)return;const k=v.width/s.clientWidth;v.x-=(e.clientX-d.x)*k;v.y-=(e.clientY-d.y)*k;d={{x:e.clientX,y:e.clientY}}}};
s.onwheel=e=>{{e.preventDefault();const f=Math.exp(e.deltaY*0.0015),r=s.getBoundingClientRect(),px=v.x+(e.clientX-r.left)/r.width*v.width,py=v.y+(e.clientY-r.top)/r.height*v.height;
v.width*=f;v.height*=f;v.x=px-(px-v.x)*f;v.y=py-(py-v.y)*f}};</script></body></html>"""
    with open(out, "w") as f:
        f.write(page)
    return out
