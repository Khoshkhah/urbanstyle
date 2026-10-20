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
    from .bridge_surface import EDGE_M, _smooth_line
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
                lo_, hi_ = widths[aid]
                l_ = by_id[aid][0]
                strips.append(l_.buffer(hi_, single_sided=True, cap_style="flat").union(l_.buffer(lo_, single_sided=True, cap_style="flat")))
            lo, hi = _extent(mid, strips)
            far = [e.get("node") for aid in (a1, a2) for k_, e in enumerate(by_id[aid][1]["ends"]) if (aid, k_) not in pr["arms"]]
            units.append({"axes": [a1, a2], "line": mid, "lo": lo, "hi": hi,
                          "ends": [pr["node"], far[0] if far and far[0] and far[0] == far[-1] else None]})
            seen |= {a1, a2}
        else:
            lo, hi = widths[a["id"]]
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
        osm_lines, strips = [], []
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
                w_lo, w_hi = widths[aid] if len(v["axes"]) > 1 else _side(ln_a, line, lo, hi)
                osm_lines.append(seg)
                strips.append(seg.buffer(w_hi, single_sided=True, cap_style="flat").union(seg.buffer(w_lo, single_sided=True, cap_style="flat")))
        poly = shapely.union_all(strips)
        branches.append({"id": f"b{len(branches) + 1}", "axes": ids, "level": a_lv.get(ids[0]), "line": line, "s0": s0, "s1": s1,
                         "lo": lo, "hi": hi, "poly": poly, "ends": ends, "osm_lines": osm_lines})
    # the forks: each arm's line from the node to its branch point, as wide as its branch
    forks_ = []
    for k_, f in enumerate(R["forks"]):
        parts = []
        arms = []
        for b in branches:
            for e, (node) in enumerate(b["ends"]):
                if node != f["node"]:
                    continue
                arms.append(b["id"])
                s_cut = b["s0"] if e == 0 else b["s1"]
                L = b["line"].length
                seg = shapely.ops.substring(b["line"], 0.0, max(s_cut, 0.5)) if e == 0 else shapely.ops.substring(b["line"], L - max(s_cut, 0.5), L)
                parts.append(seg.buffer(b["hi"], single_sided=True, cap_style="flat").union(seg.buffer(b["lo"], single_sided=True, cap_style="flat")))
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
    for lv, g_ in step3b(B, F).items():
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
    C4 = {"lane": "#5f6b70", "connector": "#f0b05a", "sidewalk": "#c8b48a", "cycle lane": "#2e8b57", "path joint": "#8d6e63", "crossing": "#ffffff"}
    everything = shapely.union_all([b["poly"] for b in B] + [f["poly"] for f in F])
    for kind in ("sidewalk", "cycle lane", "path joint", "lane", "connector", "crossing"):
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
        c0, c1 = cut.get((a["id"], 0), 0.0), cut.get((a["id"], 1), 0.0)
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
        lo, hi = _extent(ln, own, step=2.0)
        out[a["id"]] = (round(lo - edge, 2), round(hi + edge, 2))
    return out


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
        bands.append({"kind": b_["kind"], "line": b_["line"], "poly": b_["line"].buffer(b_["width"] / 2, cap_style="flat"),
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


def step3b(B, F):
    """Step 3b (docs/notes/bridge-steps.md): the outline of each bridge level made smooth, from the frozen branches and forks: their union,
    closed and opened by SMOOTH_M with round joins, so no notch or bump smaller than 2 SMOOTH_M stays (a jog at an OSM vertex, a step where
    two branches' widths meet at a branch point), and never smaller than the union: nothing of a branch is taken, so a bridge end stays
    square. Returns {level: polygon}."""
    import shapely
    out = {}
    for lv in sorted({b["level"] for b in B}):
        u = shapely.union_all([b["poly"] for b in B if b["level"] == lv] + [f["poly"] for f in F if f["level"] == lv])
        closed = u.buffer(SMOOTH_M, join_style="round").buffer(-SMOOTH_M, join_style="round")
        smooth = closed.buffer(-SMOOTH_M, join_style="round").buffer(SMOOTH_M, join_style="round").union(u)
        smooth = smooth.buffer(0.5, join_style="round").buffer(-0.5, join_style="round")    # (the corners where the opened and the original meet)
        out[lv] = shapely.make_valid(smooth)
    return out
