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
Coordinates: metres east and north of the model's origin (the middle of its outline's bounds), and up.
"""
import json
import math

STEP_M = 4.0        # the outline and the bands are sampled this often, so their heights follow the profile
BLEND_M = 40.0      # the heights of two axes are blended where the second nearest is this near
MEET_M = 1.5        # ... and only where their heights differ by less than this (they meet at a fork)
FADE_M = 2.0        # an arm's weight fades to 0 over this to the edge of its lanes
END_FADE_M = 10.0   # ... and over this to its end
LAND_BLEND_M = 30.0 # a bridge lane moves to the street's lane it lands on over this
LIFT = {True: 0.05, False: 0.10}   # above the deck: a lane (True), a path (False); clear of each other, no flicker
LINE_LIFT_M = 0.15  # a painted line above both
COLUMN_M = 2.5      # a pier's column, square (chosen; 1.5 m was too narrow)
COLUMN_GAP_M = 2.0  # two columns at least this far apart, else one (chosen)
BARRIER_M = (0.8, 0.3)      # the guard: a concrete barrier this high and wide along each side of the deck (chosen)
BARRIER_SEP_M = (0.5, 0.8)  # the barrier between a path for walking and cycling and the vehicle lanes: wide, high (chosen)
RAILING_M = (1.1, 2.5)      # ... a metal railing on it, its top this high, a post every this far (chosen)
TOUCH_M = 0.5       # two lanes this close share one painted line


def _h(vertical, s):
    from .bridge_profile import height
    return height(vertical, s)


def model(path, parts=None, marks=None, ground=None):
    """The 3D model of the bridge profile at `path` (or the profile itself). `parts`, `marks`: the street's own parts and marks that lie
    on the bridge (a unit's level > 0 spaces: [(props, polygon)], [(type, line)], in the profile's crs), laid on the deck so the bridge
    is drawn as its street; elsewhere the model's lanes and paths in the street's types. `ground`: the street's lanes at level 0 near
    the bridge ([polygon], same crs): a bridge lane that lands on one moves to its place and width over the last LAND_BLEND_M."""
    import pyproj
    import shapely
    import shapely.affinity
    from shapely.ops import substring

    P = json.load(open(path)) if isinstance(path, str) else path
    to_ll = pyproj.Transformer.from_crs(P["crs"], "EPSG:4326", always_xy=True).transform
    ol = P["deck"]["outline"]["value"]
    xs_, ys_ = [x for x, _ in ol], [y for _, y in ol]
    x0, y0 = (min(xs_) + max(xs_)) / 2, (min(ys_) + max(ys_)) / 2       # the middle of the bridge: every part near the origin
    rel = lambda ps: [(x - x0, y - y0) for x, y in ps]
    DECK_M, RAIL_M = P["deck"]["thickness"]["value"], P["deck"]["parapet"]["value"]
    axes = [(shapely.LineString(rel(a["line"]["value"])), a) for a in P["axes"]]
    # the deck: OSM's outline, and under each measured landing (an axis run on past OSM's bridge way) a strip as wide as its bands
    pieces = [shapely.make_valid(shapely.Polygon(rel(ol)))]
    for ln, a in axes:
        for land in a.get("landings", []):
            L, d = ln.length, land["length_m"]
            s0, s1 = (L - d, L) if land["end"] == "end" else (0.0, d)
            sec = a["sections"][-1] if land["end"] == "end" else a["sections"][0]
            lo = min((b["t"] - b["width"]["value"] / 2 for b in sec["bands"]), default=-4.0)
            hi = max((b["t"] + b["width"]["value"] / 2 for b in sec["bands"]), default=4.0)
            piece = substring(ln, max(s0 - 2.0, 0.0), s1)
            if piece.length > 0.5:
                pieces.append(shapely.Polygon(list(piece.offset_curve(hi).coords) + list(piece.offset_curve(lo).coords)[::-1]).buffer(0))
    deck = shapely.make_valid(shapely.union_all(pieces).buffer(0.01).buffer(-0.01))
    deck = max(shapely.get_parts(deck), key=lambda p: p.area) if deck.geom_type != "Polygon" else deck
    by_id = {a["id"]: (ln, a) for ln, a in axes}

    def reach(a, s):
        """The extent across axis a at s that its lanes cover (right edge, left edge), a metre more each side."""
        sec = next((sc for sc in a["sections"] if sc["s0"] - 0.01 <= s <= sc["s1"] + 0.01), None)
        bs = sec["bands"] if sec else []
        return (min((b["t"] - b["width"]["value"] / 2 for b in bs), default=-3.0) - 1.0,
                max((b["t"] + b["width"]["value"] / 2 for b in bs), default=3.0) + 1.0)

    def z(x, y):
        """The deck's top at (x, y): the heights of the arms whose lanes cover the point, each weighted by how far inside its lanes the point
        is (fading over FADE_M to their edge, and over END_FADE_M to the arm's end) and by its nearness, among the arms that meet there
        (heights within MEET_M of the strongest's); where no arm's lanes reach, the nearest arm's height. No step and no kink at a fork."""
        p = shapely.Point(x, y)
        cand, near = [], []
        for ln, a in axes:
            sv = ln.project(p)
            d = ln.distance(p)
            hz = _h(a["vertical"], sv)
            near.append((d, hz))
            if d < BLEND_M:
                q_, a_, b_ = ln.interpolate(sv), ln.interpolate(max(sv - 1, 0)), ln.interpolate(min(sv + 1, ln.length))
                t = ((b_.x - a_.x) * (y - q_.y) - (b_.y - a_.y) * (x - q_.x)) / (math.hypot(b_.x - a_.x, b_.y - a_.y) or 1)
                lo, hi = reach(a, sv)
                w = min(1.0, min(t - lo, hi - t) / FADE_M) * min(1.0, sv / END_FADE_M, (ln.length - sv) / END_FADE_M)
                if w > 0:
                    cand.append((w / (d + 1.0), hz))
        if not cand:
            return min(near)[1]
        top = max(cand)[1]
        use = [(w, hz) for w, hz in cand if abs(hz - top) <= MEET_M]
        return sum(w * hz for w, hz in use) / sum(w for w, _ in use)

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
            tv = t(s) if callable(t) else t
            out.append([round(x + nx * tv, 2), round(y + ny * tv, 2), round(z(x + nx * tv, y + ny * tv) + lift, 2)])     # on the deck's surface
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
    # a bridge lane that lands on a ground lane (the street's own, level 0): its edges move to that lane's over the last LAND_BLEND_M
    gl = [shapely.affinity.translate(g, -x0, -y0) for g in (ground or [])]
    gtree = shapely.STRtree(gl) if gl else None
    land = {}       # (axis id, band index in its section, section index) -> [(end, left, right)]
    for ln, a in axes:
        for e in (0, 1):
            if gtree is None or not a["ends"][e].get("ground") or not a["sections"]:
                continue
            si = len(a["sections"]) - 1 if e else 0
            sv = ln.length if e else 0.0
            x, y, nx, ny = frame(ln, sv)
            across = shapely.LineString([(x - nx * 20, y - ny * 20), (x + nx * 20, y + ny * 20)])
            for bi, b in enumerate(a["sections"][si]["bands"]):
                if b["type"] != "lane":
                    continue
                pt = shapely.Point(x + nx * b["t"], y + ny * b["t"])
                near = [k for k in gtree.query(pt.buffer(2.0)) if gl[k].distance(pt) <= 2.0]
                if not near:
                    continue
                cut = across.intersection(gl[min(near, key=lambda k: gl[k].distance(pt))])
                ts = [(q[0] - x) * nx + (q[1] - y) * ny for g_ in shapely.get_parts(cut) if g_.geom_type == "LineString" for q in g_.coords]
                if len(ts) >= 2 and max(ts) - min(ts) > 1.0:
                    land.setdefault((a["id"], si, bi), []).append((e, max(ts), min(ts)))

    def edges(a, ln, si, bi, b):
        """The band's left and right edge offsets, functions of s (moving to a ground lane near a landing)."""
        w = b["width"]["value"]
        L0, R0 = b["t"] + w / 2, b["t"] - w / 2
        tg = land.get((a["id"], si, bi), [])
        if not tg:
            return L0, R0

        def blend(base, k):
            def f(s):
                v = base
                for e, gl_, gr_ in tg:
                    d = (ln.length - s) if e else s
                    u = 0.0 if d >= LAND_BLEND_M else 0.5 * (1 + math.cos(math.pi * d / LAND_BLEND_M))
                    v = v * (1 - u) + (gl_ if k == 0 else gr_) * u
                return v
            return f
        return blend(L0, 0), blend(R0, 1)
    lanes, lines = [], []
    for ln, a in axes:
        height = f"{a['vertical']['source']}, {a['vertical']['method']}"
        for si, sec in enumerate(a["sections"]):
            for bi, b in enumerate(sec["bands"]):
                w = b["width"]["value"]
                props = {"type": b["type"], "name": b.get("name") or P["name"], "osm": b.get("way"), "link": b.get("link"),
                         "lane_id": b.get("lane_id"), "direction": b.get("direction"), "lane": b.get("lane"), "use": b.get("use"),
                         "turn": b.get("turn"), "width_m": w, "width_source": b["width"]["source"], "width_method": b["width"]["method"],
                         "axis": a["id"], "section_m": f"{sec['s0']}-{sec['s1']}", "height": height,
                         "source": "duckOSM GMNS (lanes from SUMO)" if b["type"] == "lane" else "osm", "method": "mapped"}
                f_, t_ = b.get("s_from", sec["s0"]), b.get("s_to", sec["s1"])
                if t_ - f_ < 0.5:       # (inside a junction: a connector covers it)
                    continue
                le, re_ = edges(a, ln, si, bi, b)
                if land.get((a["id"], si, bi)):
                    props["landing"] = "moves to the street's lane over the last %.0f m" % LAND_BLEND_M
                lanes.append({"props": props, "l": along(ln, a, f_, t_, le, LIFT[b["type"] == "lane"]), "r": along(ln, a, f_, t_, re_, LIFT[b["type"] == "lane"])})
            # painted lines: across the lanes of the section, from left to right
            ls = [(bi, b) for bi, b in enumerate(sec["bands"]) if b["type"] == "lane"]
            paint = []
            f_ = min((b.get("s_from", sec["s0"]) for _, b in ls), default=sec["s0"])
            t_ = max((b.get("s_to", sec["s1"]) for _, b in ls), default=sec["s1"])
            val = lambda t, s: t(s) if callable(t) else t
            for i, (bi, b) in enumerate(ls):
                left, right = b["t"] + b["width"]["value"] / 2, b["t"] - b["width"]["value"] / 2
                le, re_ = edges(a, ln, si, bi, b)
                if i == 0 or abs(ls[i - 1][1]["t"] - ls[i - 1][1]["width"]["value"] / 2 - left) > TOUCH_M:
                    paint.append(("edge line", le))
                if i + 1 < len(ls) and abs(ls[i + 1][1]["t"] + ls[i + 1][1]["width"]["value"] / 2 - right) <= TOUCH_M:
                    nbi, nb = ls[i + 1]
                    nle, _ = edges(a, ln, si, nbi, nb)
                    paint.append(("centre line" if nb["direction"] != b["direction"] else "lane line",
                                  (lambda s, re_=re_, nle=nle: (val(re_, s) + val(nle, s)) / 2)))
                else:
                    paint.append(("edge line", re_))
            if t_ - f_ >= 0.5:
                lines += [{"kind": k, "ref": a["id"], "pts": along(ln, a, f_, t_, t, LINE_LIFT_M)} for k, t in paint]
    crossings = []      # (a crossing OSM maps, marked or not, its fields): a crosswalk over the lanes it crosses, not a path
    shared = []         # (a path for walking and cycling, its width, its fields): one lane, with a barrier towards the vehicle lanes
    road_ = shapely.union_all([shapely.Polygon([p[:2] for p in l["l"]] + [p[:2] for p in l["r"]][::-1]).buffer(0) for l in lanes]) if lanes else shapely.Polygon()
    for f in P.get("paths", []):            # each path on the deck, along its own line
        fl = shapely.LineString(rel(f["line"]))
        if fl.length < 0.5:
            continue
        props = {"type": f["type"], "name": f.get("name") or P["name"], "osm": f["way"], "width_m": f["width"]["value"],
                 "width_source": f["width"]["source"], "width_method": f["width"]["method"], "source": f["source"], "method": f["method"]}
        # a crossing is what OSM maps as one (footway=crossing, cycleway=crossing, a crossing tag): a crosswalk over the lanes it crosses;
        # any other path is drawn whole (a path beside the lanes is no crossing)
        if f.get("footway") == "crossing" or f.get("cycleway") == "crossing" or f.get("crossing"):
            marked = not (f.get("crossing") == "unmarked" or f.get("markings") == "no")
            crossings.append((fl, marked, {**props, "type": "crosswalk", "marked": marked}))
        elif f["type"] == "shared path":    # a path for walking and cycling: drawn below with its barrier
            shared.append((fl, f["width"]["value"], props))
        else:
            l_, r_ = ribbon(fl, f["width"]["value"], LIFT[False])
            lanes.append({"props": props, "l": l_, "r": r_})
    for c in P.get("connectors", []):       # SUMO's path from lane to lane through a junction on the deck
        cl = shapely.LineString(rel(c["line"]))
        if cl.length < 0.5:
            continue
        l_, r_ = ribbon(cl, c["width"]["value"], LIFT[True])
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
        lo = min((b["t"] - b["width"]["value"] / 2 for b in bs), default=-4.0) + 0.5
        hi = max((b["t"] + b["width"]["value"] / 2 for b in bs), default=4.0) - 0.5
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
    # the surface the page draws: every item as a mesh on the deck, in the street's types (its colours, raised sidewalks, kerbs, lines)
    from .parts import CROSSWALK_M, KERB_TOP_M, LINE, RAISED, ZEBRA_BAR_M, ZEBRA_GAP_M
    surf = []

    def mesh(poly, key, lift, props=None, raise_=0.0):
        """poly (model metres) as triangles on the deck's surface, lift above it (and raise_ more, with its sides down to the lift)."""
        poly = shapely.make_valid(poly)
        for pg in shapely.get_parts(poly):
            if pg.geom_type != "Polygon" or pg.area < 0.05:
                continue
            dense = pg.segmentize(STEP_M / 2)
            tris = [t for t in shapely.get_parts(shapely.constrained_delaunay_triangles(dense)) if t.representative_point().within(pg.buffer(0.01))]
            v, f, ix = [], [], {}

            def vi(x, y, zz):
                k = (round(x, 2), round(y, 2), round(zz, 2))
                if k not in ix:
                    ix[k] = len(v)
                    v.append(list(k))
                return ix[k]
            hz = lambda x, y: z(x, y) + lift + raise_
            f += [[vi(x, y, hz(x, y)) for x, y in t.exterior.coords[:3]] for t in tris]
            if raise_ > 0:                      # its sides, as a kerb's face
                for ring in [dense.exterior] + list(dense.interiors):
                    c = list(ring.coords)
                    for (ax_, ay_), (bx_, by_) in zip(c, c[1:]):
                        a0, b0 = vi(ax_, ay_, z(ax_, ay_) + lift), vi(bx_, by_, z(bx_, by_) + lift)
                        a1, b1 = vi(ax_, ay_, hz(ax_, ay_)), vi(bx_, by_, hz(bx_, by_))
                        f += [[a0, b0, b1], [a0, b1, a1]]
            if f:
                surf.append({"key": key, "props": props, "v": v, "f": f})

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
    for pc, w, props in shared:             # one lane for walking and cycling, a concrete barrier on its side towards the vehicle lanes
        if not covered.is_empty and pc.intersection(covered).length > 0.5 * pc.length:
            continue
        l_, r_ = ribbon(pc, w, LIFT[False])
        mesh(shapely.Polygon([q[:2] for q in l_] + [q[:2] for q in r_][::-1]).buffer(0), "cycle lane", LIFT[False], props)
        lt, rt = pc.offset_curve(w / 2 + BARRIER_SEP_M[0]), pc.offset_curve(-(w / 2 + BARRIER_SEP_M[0]))
        dl = road_.distance(lt) if not lt.is_empty else 1e9
        dr = road_.distance(rt) if not rt.is_empty else 1e9
        bar = pc.offset_curve((1 if dl < dr else -1) * (w / 2 + BARRIER_SEP_M[0] / 2))
        for bp in shapely.get_parts(bar.difference(road_.buffer(0.3)) if not bar.is_empty else bar):
            if bp.geom_type == "LineString" and bp.length > 1.0:
                strip(bp, BARRIER_SEP_M[0], "barrier", 0.0, None, BARRIER_SEP_M[1])
    # the model's own items where the street has no part: lanes, connectors and paths in the street's types, its lines as paint
    for l in lanes:
        pg = shapely.Polygon([p[:2] for p in l["l"]] + [p[:2] for p in l["r"]][::-1]).buffer(0)
        if pg.is_empty or (not covered.is_empty and pg.intersection(covered).area > 0.5 * pg.area):
            continue
        ty = l["props"]["type"]
        key = {"lane": f"lane {l['props'].get('direction') or ''}".strip(), "junction lane": "lane", "footway": "sidewalk",
               "cycleway": "cycle lane"}.get(ty, ty)
        mesh(pg, key, 0.03, l["props"], RAISED.get(key, 0.0))
    for ln_ in lines:
        g = shapely.LineString([p[:2] for p in ln_["pts"]])
        if g.length < 0.5 or (not covered.is_empty and g.intersection(covered).length > 0.5 * g.length):
            continue
        strip(g, LINE.get(ln_["kind"], 0.12), f"mark {ln_['kind']}", 0.06, (3.0, 6.0) if ln_["kind"] == "lane line" else None)
    # the guards on both sides of the deck: a concrete barrier and a metal railing on posts; none across a road where it leaves the bridge
    ends_ = []
    for l in lanes:
        for k in (0, -1):
            a_, b_ = l["l"][k][:2], l["r"][k][:2]
            ends_.append(shapely.LineString([a_, b_]).buffer(1.0, cap_style="flat").buffer(0.5))
    gaps = shapely.union_all(ends_) if ends_ else shapely.Polygon()
    rim = lambda d0, d1: shapely.make_valid(deck.buffer(-d0).difference(deck.buffer(-d1))).difference(gaps)
    mesh(rim(0.0, BARRIER_M[1]), "barrier", 0.0, None, BARRIER_M[0])
    mesh(rim(0.1, 0.2), "railing", RAILING_M[0] - 0.08, None, 0.08)
    mid = shapely.make_valid(deck.buffer(-BARRIER_M[1] / 2)).boundary.difference(gaps)
    for ring in shapely.get_parts(mid):
        if ring.geom_type != "LineString":
            continue
        for k in range(int(ring.length // RAILING_M[1]) + 1):
            p_ = ring.interpolate(k * RAILING_M[1])
            mesh(p_.buffer(0.05, cap_style="square"), "railing", BARRIER_M[0], None, RAILING_M[0] - BARRIER_M[0])
    rails = []        # (the guards above replace the plain parapet)
    v = lambda d: f"{d['source']}, {d['method']}"
    return {"name": P["name"], "origin": list(to_ll(x0, y0)), "outline": [list(to_ll(x, y)) for x, y in ol], "verts": verts,
            "deck": top + bottom, "sides": sides, "rails": rails, "lines": lines, "lanes": lanes, "piers": piers, "surf": surf,
            "sources": {"outline": v(P["deck"]["outline"]), "heights": "; ".join(sorted({v(a["vertical"]) for _, a in axes})),
                        "deck": v(P["deck"]["thickness"]), "parapet": v(P["deck"]["parapet"]),
                        "piers": v(P["piers"][0]) if P["piers"] else "none"}}


if __name__ == "__main__":
    import sys
    m = model(sys.argv[1])
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in m.items()}, indent=1))
