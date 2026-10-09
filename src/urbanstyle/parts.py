"""The inside of every new space (space.unit): its parts, its marks and the widths of its edges (docs/design/space-parts.md).

space.part   the parts that cover a unit exactly: junction box, lane (in / out of a junction, forward / backward along a subsection),
             bus lane, cycle lane, crosswalk, cycle crossing, carriageway (roadway no lane took), sidewalk, furnishing, open
space.mark   lines on it, at real size: kerb, centre line, lane line, stop line, give-way line, zebra (one bar of a crosswalk)
space.width  per intersection arm (at its cut) and per subsection (across its middle): total, roadway and sidewalk widths, lanes, lane width

Widths are MEASURED where the data allows and say so (`source`): a road's kerbs from its mapped sidewalks (`measured`, or `measured one
side`), else from a crossing path across it (`crossing`), else estimated from its lanes (`estimated`); the roadway runs kerb to kerb, the
centre line of a two-way road in its middle, each side's lanes sharing that side's width equally. A lanes tag sets the count (`tag`); else the measured width / LANE_M sets it, at
least one lane each way on a two-way road. Cycle and bus lanes come from the cycleway tags (on the correct side of the way's direction).
The sidewalk runs from the kerb to the building face (measured); a furnishing strip only where street furniture stands, out to it.
Right-hand traffic: lanes coming into a junction lie on the left of the arm seen from the junction, a subsection's forward lanes on the
right of its road.
"""
import math

LANE_M = 3.0           # (kept for reference) a typical lane
LANE_FIT_M = 3.5       # untagged: as many whole lanes as fit at this width; what is left is shoulder (parking, a hard strip)
MIN_LANE_M, MAX_LANE_M = 2.5, 3.75   # a two-way road narrower than 2 x MIN is one lane used both ways; a side wider than its lanes x MAX has a shoulder
EST_LANE_M = 3.25      # a lane's width when nothing is measured
SIDEWALK_HALF_M = 1.0  # a sidewalk is mapped along its middle: the kerb lies this much nearer the road
KERB_SEARCH_M = 12.0   # how far from a road its sidewalks are looked for (a sidewalk farther away is not this road's)
CROSSWALK_M = 3.0
CYCLE_M = 1.5          # a cycle lane at the roadway's edge
BUS_M = 3.2            # a bus lane (shared with bikes: cycleway=share_busway)
TRACK_M = 2.0          # a mapped cycle track
OPEN_M = 6.0           # pedestrian ground farther than this from both the kerb and the buildings is open ground, not sidewalk
FURNITURE = ("vegetation.tree", "furniture.lamp", "furniture.bench", "furniture.waste", "furniture.sign", "furniture.signal",
             "furniture.bike_parking", "furniture.post_box", "furniture.bollard", "furniture.hydrant", "furniture.advertising",
             "furniture.shelter", "furniture.vending", "furniture.water", "furniture.charging", "transit.stop")
FURNISH_ALONG_M = 6.0  # a furnishing strip runs this far along the kerb either side of a piece of street furniture
CONTROL_M = 35.0       # a stop / give-way sign or a signal this close to the junction, beside an arm, puts a line across its in lanes
MIN_M2 = 0.3
KERB_RADIUS_M = 3.0    # the radius of a junction's kerb around a block corner
BAND_PAD_M = 12.0      # a road's bands are drawn this far past its unit and trimmed to it: they reach a slanted cut exactly
ZEBRA_BAR_M, ZEBRA_GAP_M = 0.5, 0.5
ARROW_M = 3.0          # a painted lane arrow's length


def _unit(x, y):
    h = math.hypot(x, y) or 1.0
    return x / h, y / h


def build(con, epsg):
    import pandas as pd
    import shapely
    from shapely.ops import substring

    tr = lambda col="geometry": f"ST_AsWKB(ST_Transform({col}, 'EPSG:4326', '{epsg}', always_xy := true))"
    g = lambda w: shapely.make_valid(shapely.from_wkb(bytes(w)))

    def safe(op, a, b):     # a set operation that survives slightly invalid input: retry on a 1 cm grid
        try:
            return shapely.make_valid(getattr(shapely, op)(a, b))
        except shapely.errors.GEOSException:
            return shapely.make_valid(getattr(shapely, op)(shapely.make_valid(a), shapely.make_valid(b), grid_size=0.01))

    def area(geom):         # the polygons of a result only (a repair can leave lines and points beside them)
        ps = [p for p in shapely.get_parts(shapely.make_valid(geom)) if p.geom_type in ("Polygon", "MultiPolygon")] if geom is not None else []
        return shapely.union_all(ps) if ps else shapely.Polygon()

    def polys(geom):
        return [p for p in shapely.get_parts(shapely.make_valid(geom)) if p.geom_type == "Polygon" and p.area >= MIN_M2]

    def side(d, line):      # within |d| m of the line, on its left (d > 0) or right (d < 0)
        return line.buffer(d, single_sided=True, cap_style="flat") if abs(d) > 1e-6 else shapely.Polygon()

    def band(line, a, b):   # between offsets a < b from the line (left positive)
        if a >= 0:
            return safe("difference", side(b, line), side(a, line))
        if b <= 0:
            return safe("difference", side(a, line), side(b, line))
        return safe("union", side(a, line), side(b, line))

    def num(v):
        try:
            return float(str(v).split(";")[0])
        except (TypeError, ValueError):
            return None

    def direction(line, t):
        q0, q1 = line.interpolate(max(t - 1, 0)), line.interpolate(min(t + 1, line.length))
        return _unit(q1.x - q0.x, q1.y - q0.y)

    # ---- inputs
    units = [(uid, kind, sec, lv, g(w)) for uid, kind, sec, lv, w in con.execute(
        f"SELECT unit_id, kind, section_id, level, {tr()} FROM space.unit").fetchall()]
    edge_kind = {"lane": "cycle lane", "opposite_lane": "cycle lane", "share_busway": "bus lane"}
    tags, sides = {}, {}
    try:
        for osm, lanes, width, cl, cr, refs in con.execute("""SELECT osm_id, tags['lanes'], tags['width'],
                coalesce(tags['cycleway:left'], tags['cycleway:both'], tags['cycleway']), coalesce(tags['cycleway:right'], tags['cycleway:both'], tags['cycleway']),
                refs FROM osm.raw.ways WHERE tags['highway'] IS NOT NULL""").fetchall():
            tags[osm] = (num(lanes), num(width))
            if edge_kind.get(cl) or edge_kind.get(cr):
                sides[osm] = (edge_kind.get(cl), edge_kind.get(cr), list(refs or []))
    except Exception:       # no OSM database attached (a rebuild of the parts alone): counts from the widths, no cycle / bus lanes
        pass
    try:
        ring_osm = {r[0] for r in con.execute("SELECT osm_id FROM osm.raw.ways WHERE tags['junction'] IN ('roundabout', 'circular')").fetchall()}
    except Exception:
        ring_osm = set()
    roads = {}
    for eid, osm, lv, w, ow, src, dst, cid, name, wk in con.execute(f"""SELECT source_id, osm_id, level_min, coalesce(width_m, 6), coalesce(oneway, false),
            src, dst, container_id, name, {tr()} FROM space.element WHERE type = 'road' AND ST_Length(geometry) > 0""").fetchall():
        roads[eid] = dict(osm=osm, level=lv, w=w, oneway=ow, src=src, dst=dst, cid=cid, name=name or "(unnamed)", g=g(wk))
    rtree_ids = list(roads)
    rtree = shapely.STRtree([roads[e]["g"] for e in rtree_ids]) if rtree_ids else None
    paths = [(typ, sub, lv, g(w)) for typ, sub, lv, w in con.execute(
        f"SELECT type, coalesce(subtype, ''), level_min, {tr()} FROM space.element WHERE type IN ('walkway', 'cycleway')").fetchall()]
    ptree = shapely.STRtree([p[3] for p in paths]) if paths else None
    objs = [(oid, cls, lv, ctl, g(w)) for oid, cls, lv, ctl, w in con.execute(f"""SELECT object_id, class, level,
            CASE WHEN class = 'furniture.signal' THEN 'signal' WHEN json_extract_string(attrs, '$.highway') IN ('stop', 'give_way')
                 THEN json_extract_string(attrs, '$.highway') END, {tr()}
            FROM space.object WHERE class LIKE 'crossing.%' OR class IN {FURNITURE}
               OR json_extract_string(attrs, '$.highway') IN ('stop', 'give_way')""").fetchall()]
    otree = shapely.STRtree([o[4] for o in objs]) if objs else None
    blds = [(lv, g(w)) for lv, w in con.execute(f"SELECT l, {tr()} FROM space.element, generate_series(level_min, level_max) t(l) WHERE type = 'building'").fetchall()]
    btree = shapely.STRtree([b[1] for b in blds]) if blds else None
    cuts = {}
    for iid, eid, w in con.execute(f"SELECT intersection_id, edge_id, {tr()} FROM space.cut").fetchall():
        cuts.setdefault(iid, []).append((eid, g(w)))
    sub_of = {r[0]: (r[1], g(r[2])) for r in con.execute(f"SELECT subsection_id, with_sections, {tr()} FROM space.subsection").fetchall()}

    def kerbs(ln, level, r):
        """(left, right, source): where the kerbs of road `r` (its line `ln`) are. From the mapped sidewalks either side: a sidewalk is
        mapped along its middle, so the kerb is SIDEWALK_HALF_M nearer the road (`measured`; one side only: the same both ways, `measured
        one side`). Else from a crossing path across it: its length minus two half sidewalks is kerb to kerb (`crossing`). Else estimated."""
        near = [paths[k] for k in ptree.query(ln.buffer(KERB_SEARCH_M))] if ptree is not None else []
        sw = [p[3] for p in near if p[2] == level and p[1] != "crossing"]
        swu = shapely.union_all(sw) if sw else None
        L, R = [], []
        n = max(2, min(15, int(ln.length // 2) + 1))
        for i in range(n):
            t = ln.length * (i + 0.5) / n
            c = ln.interpolate(t)
            tx, ty = direction(ln, t)
            for s_, out in ((1, L), (-1, R)):
                if swu is None:
                    continue
                ray = shapely.LineString([(c.x, c.y), (c.x - s_ * ty * KERB_SEARCH_M, c.y + s_ * tx * KERB_SEARCH_M)])
                hit = safe("intersection", ray, swu)
                if not hit.is_empty:
                    d = c.distance(hit) - SIDEWALK_HALF_M
                    if d >= MIN_LANE_M / 2:
                        out.append(d)
        enough = max(2, n // 3)
        hl = sorted(L)[len(L) // 2] if len(L) >= enough else None
        hr = sorted(R)[len(R) // 2] if len(R) >= enough else None
        if hl and hr:
            return hl, hr, "measured"
        if hl or hr:                    # one side measured; the other side's half of the estimated roadway (not a mirror of a far sidewalk)
            el, er = estimate(r)
            return (hl or el), (hr or er), "measured one side"
        spans = [seg.length - 2 * SIDEWALK_HALF_M for typ, sb, lv, cl in near if lv == level and sb == "crossing" and cl.intersects(ln)
                 for seg in [cl] if seg.length - 2 * SIDEWALK_HALF_M >= MIN_LANE_M]
        if spans:
            t = sorted(spans)[len(spans) // 2]
            return t / 2, t / 2, "crossing"
        return (*estimate(r), "estimated")

    def estimate(r):
        """(left, right) half-widths of a road's roadway from its tags or width_m when nothing is measured."""
        nl, wt = tags.get(r["osm"], (None, None))
        if wt:
            return wt / 2, wt / 2
        n = int(nl) if nl and nl >= 1 else max(1 if r["oneway"] else 2, round(r["w"] / EST_LANE_M))
        return n * EST_LANE_M / 2, n * EST_LANE_M / 2

    def same_way_direction(r, ln):
        """Does `ln` run the way the OSM way runs (its left is the way's left)?"""
        refs = sides.get(r["osm"], (None, None, []))[2]
        e_fwd = True
        if r["src"] in refs and r["dst"] in refs:
            e_fwd = refs.index(r["src"]) < refs.index(r["dst"])          # the element's own geometry runs src -> dst
        g0, g1 = r["g"].coords[0], r["g"].coords[-1]
        l0, l1 = ln.coords[0], ln.coords[-1]
        along = (g1[0] - g0[0]) * (l1[0] - l0[0]) + (g1[1] - g0[1]) * (l1[1] - l0[1]) >= 0
        return along == e_fwd

    parts, marks, widths, count, claimed = [], [], [], {}, {}

    def add(uid, level, typ, geom, source, arm=None, direction=None, lane=None, width=None):
        # a part takes only ground no earlier part of this unit took: no overlaps by construction (priority = the order of the calls)
        def precise(op, a, b):     # on a 1 cm grid: exact enough, robust where floating point is not (else the plain overlay)
            try:
                return area(getattr(shapely, op)(a, b, grid_size=0.01))
            except shapely.errors.GEOSException:
                return area(safe(op, a, b))
        if uid in claimed and geom is not None and not geom.is_empty:
            geom = precise("difference", area(geom), claimed[uid])
        got = polys(geom) if geom is not None else []
        if got:
            new = shapely.union_all(got)
            claimed[uid] = precise("union", claimed[uid], new) if uid in claimed else area(new)
        for p in got:
            n = count[uid] = count.get(uid, 0) + 1
            parts.append((uid, f"{uid}#{n}", level, typ, arm, direction, lane, round(width, 2) if width else None, source, shapely.to_wkb(p)))
        return shapely.union_all(got) if got else shapely.Polygon()

    def mark(uid, level, typ, geom, arm=None):
        if geom is None or geom.is_empty:
            return
        lines = [x for x in shapely.get_parts(geom) for x in (shapely.get_parts(x) if x.geom_type.startswith("Multi") else [x])
                 if x.geom_type == "LineString"]
        for ln in (shapely.get_parts(shapely.line_merge(shapely.MultiLineString(lines))) if len(lines) > 1 else lines):
            if ln.geom_type == "LineString" and ln.length >= 0.3:
                marks.append((uid, level, typ, arm, round(ln.length, 1), shapely.to_wkb(ln)))

    def zebra(uid, level, poly, walk):
        """The white bars of a crosswalk: parallel to the road (square to the walking direction), ZEBRA_BAR_M wide, ZEBRA_GAP_M apart."""
        if poly.is_empty:
            return
        wx, wy = walk
        c = poly.centroid
        L = max(poly.bounds[2] - poly.bounds[0], poly.bounds[3] - poly.bounds[1]) + 2
        k = -L
        while k <= L:
            mx, my = c.x + wx * k, c.y + wy * k
            bar = shapely.LineString([(mx - wy * L, my + wx * L), (mx + wy * L, my - wx * L)])
            mark(uid, level, "zebra", safe("intersection", bar, poly.buffer(-0.1)))
            k += ZEBRA_BAR_M + ZEBRA_GAP_M

    def crossings(uid, level, U, C, axes):
        """Crosswalks and cycle crossings over the roadway C: mapped crossing paths, else crossing points square across the nearest of
        `axes` [line]. Draws the zebra bars. Returns the ground they took."""
        near = [paths[k] for k in ptree.query(U)] if ptree is not None else []
        mapped, taken = [], shapely.Polygon()
        for typ, sub, lv, ln in near:
            if lv != level or not (sub == "crossing" or typ == "cycleway"):
                continue
            on = safe("intersection", ln, C.buffer(1.0))
            for seg in [x for x in shapely.get_parts(on) if x.geom_type == "LineString" and x.length >= 1.0]:
                w = CROSSWALK_M if typ == "walkway" else CYCLE_M
                got = add(uid, level, "crosswalk" if typ == "walkway" else "cycle crossing", safe("intersection", seg.buffer(w / 2, cap_style="flat"), C), "measured", width=w)
                if typ == "walkway":
                    zebra(uid, level, got, _unit(seg.coords[-1][0] - seg.coords[0][0], seg.coords[-1][1] - seg.coords[0][1]))
                taken = safe("union", taken, got)
                mapped.append(seg)
        for oid, cls, lv, ctl, p in ([objs[k] for k in otree.query(U)] if otree is not None else []):
            if lv != level or not cls.startswith("crossing.") or not p.within(U) or any(p.distance(m) < 4 for m in mapped) or not axes:
                continue
            ln = min(axes, key=lambda a: a.distance(p))
            t = ln.project(p)
            tx, ty = direction(ln, t)
            c, L, H = ln.interpolate(t), 30.0, CROSSWALK_M / 2
            rect = shapely.Polygon([(c.x - tx * H - ty * L, c.y - ty * H + tx * L), (c.x + tx * H - ty * L, c.y + ty * H + tx * L),
                                    (c.x + tx * H + ty * L, c.y + ty * H - tx * L), (c.x - tx * H + ty * L, c.y - ty * H - tx * L)])
            got = add(uid, level, "crosswalk", safe("intersection", rect, C), "estimated", width=CROSSWALK_M)
            zebra(uid, level, got, (-ty, tx))
            taken = safe("union", taken, got)
        return taken

    def arrow(uid, level, ln, off, t_tip, sgn, arm=None):
        """A painted direction arrow in a lane: ARROW_M long, its tip at `t_tip` along `ln`, `off` m to the left of it, pointing along
        `ln` (sgn = 1) or back (sgn = -1)."""
        if ln.length < ARROW_M + 1:
            return
        c = ln.interpolate(t_tip)
        tx, ty = direction(ln, t_tip)
        dx, dy, nx, ny = tx * sgn, ty * sgn, -ty, tx
        tip = (c.x + nx * off, c.y + ny * off)
        tail = (tip[0] - dx * ARROW_M, tip[1] - dy * ARROW_M)
        h1 = (tip[0] - dx * 0.9 + nx * 0.45, tip[1] - dy * 0.9 + ny * 0.45)
        h2 = (tip[0] - dx * 0.9 - nx * 0.45, tip[1] - dy * 0.9 - ny * 0.45)
        for piece in (shapely.LineString([tail, tip]), shapely.LineString([h1, tip, h2])):
            marks.append((uid, level, "arrow", arm, round(piece.length, 1), shapely.to_wkb(piece)))

    def lane_set(uid, level, C, ln, r, right, left, one, arm=None, half=None, arrows="middle"):
        """The lanes of road `r` (its line `ln`) in the roadway C, each side's measured width shared equally among that side's lanes;
        a tagged cycle or bus lane takes the outer edge of its side first. Lanes come back as (direction, polygon, from, to offsets). Two-way: `right` lanes on the right of the line, `left` on its
        left; one-way: all `one`. `half`: (left, right, source) measured elsewhere (an arm's approach). Returns ([(direction, polygon)],
        lanes right, lanes left, lane width, source)."""
        hl, hr, src = half if half else kerbs(ln, level, r)
        nl, _ = tags.get(r["osm"], (None, None))
        sl, sr, _ = sides.get(r["osm"], (None, None, []))
        if sl or sr:                                     # the way's left / right, seen along `ln`
            sl, sr = (sl, sr) if same_way_direction(r, ln) else (sr, sl)
        out = []
        for kind, s in ((sl, 1), (sr, -1)):              # a cycle or bus lane at the outer edge of its side
            if kind:
                h = hl if s == 1 else hr
                w = min(BUS_M if kind == "bus lane" else CYCLE_M, max(h - 2.5, 0))
                if w <= 0:
                    continue
                a, b = (h - w, h + 30) if s == 1 else (-h - 30, -h + w)
                got = add(uid, level, kind, safe("intersection", band(ln, a, b), C), "tag", arm=arm, width=w)
                mark(uid, level, "lane line", safe("intersection", shapely.offset_curve(ln, (h - w) * s), C), arm)
                if s == 1:
                    hl -= w
                else:
                    hr -= w
        # bands across the roadway, right to left: (from, to, type, direction). A lane is MIN_LANE_M .. MAX_LANE_M wide; what a side
        # has beyond its lanes is a shoulder at the kerb (parking, a hard strip); a two-way road too narrow for a lane each way is one
        # lane used both ways (a narrow street).
        bands_ = []
        if not r["oneway"] and hl + hr < 2 * MIN_LANE_M:
            bands_.append((-hr, hl, "lane", "both"))
        elif r["oneway"]:
            n = int(nl) if nl and nl >= 1 else max(1, int((hl + hr) / LANE_FIT_M))
            wl = min((hl + hr) / n, MAX_LANE_M)
            spare = hl + hr - n * wl
            if spare > 0.3:                                # right-hand traffic: the shoulder is on the right
                bands_.append((-hr, -hr + spare, "shoulder", None))
            bands_ += [(-hr + spare + i * wl, -hr + spare + (i + 1) * wl, "lane", one) for i in range(n)]
        else:   # the centre line in the middle of the roadway (the mapped line need not be), the lanes split evenly either side
            total, c0 = hl + hr, (hl - hr) / 2
            per = max(1, int(total / 2 / LANE_FIT_M))     # untagged: whole lanes per direction; the rest is shoulder (parking)
            n = int(nl) if nl and nl >= 2 else 2 * per
            n_r, n_l = n // 2, n - n // 2
            wr, wl_ = min(total / 2 / n_r, MAX_LANE_M), min(total / 2 / n_l, MAX_LANE_M)
            if total / 2 - n_r * wr > 0.3:
                bands_.append((-hr, c0 - n_r * wr, "shoulder", None))
            bands_ += [(c0 - (n_r - i) * wr, c0 - (n_r - i - 1) * wr, "lane", right) for i in range(n_r)]
            bands_ += [(c0 + i * wl_, c0 + (i + 1) * wl_, "lane", left) for i in range(n_l)]
            if total / 2 - n_l * wl_ > 0.3:
                bands_.append((c0 + n_l * wl_, hl, "shoulder", None))
        inside = safe("intersection", ln, C.buffer(0.3))               # the line may run on past the unit: arrows only inside it
        la = max((x for x in shapely.get_parts(shapely.line_merge(inside) if inside.geom_type == "MultiLineString" else inside)
                  if x.geom_type == "LineString" and not x.is_empty), key=lambda x: x.length, default=None)
        if la is not None and ln.project(shapely.Point(la.coords[0])) > ln.project(shapely.Point(la.coords[-1])):
            la = shapely.LineString(la.coords[::-1])
        lanes_only = [x for x in bands_ if x[2] == "lane"]
        wl = sum(x[1] - x[0] for x in lanes_only) / max(len(lanes_only), 1)
        n_r = sum(x[3] in (right, "both") for x in lanes_only); n_l = sum(x[3] in (left, "both") for x in lanes_only)
        lsrc = src if not nl else "tag"
        for i, (a0, b0, typ, d) in enumerate(bands_):
            a1 = a0 - 30 if i == 0 else a0                 # the outer bands run on to the (irregular) kerb
            b1 = b0 + 30 if i == len(bands_) - 1 else b0
            got = add(uid, level, typ, safe("intersection", band(ln, a1, b1), C), lsrc, arm=arm, direction=d,
                      lane=i + 1 if typ == "lane" else None, width=b0 - a0)
            if typ == "lane":
                out.append((d, got, a0, b0))
                sgn = 1 if d == right else (-1 if d == left else 0)          # `right` lanes run along the line, `left` lanes back
                if sgn and la is not None and la.length >= ARROW_M + 2:
                    t = (la.length / 2 + sgn * ARROW_M / 2 if arrows == "middle" else
                         (1.0 if sgn < 0 else la.length - 1.0))           # ends: an arm's in lanes point at the junction, out lanes away
                    arrow(uid, level, la, (a0 + b0) / 2, t, sgn, arm)
        for (a0, b0, t0, d0), (a1, b1, t1, d1) in zip(bands_, bands_[1:]):     # the painted line between two bands
            line = shapely.offset_curve(ln, b0) if abs(b0) > 1e-6 else ln
            kind = "centre line" if (t0 == t1 == "lane" and d0 != d1) else ("lane line" if t0 == t1 == "lane" else "edge line")
            mark(uid, level, kind, safe("intersection", line, C), arm)
        return out, n_r, n_l, wl, src if not nl else "tag"

    def pedestrian(uid, level, U, C, corner_of=None):
        """The pedestrian realm U - C: a furnishing strip by the kerb only where street furniture stands (out to it), open ground far
        from both kerb and buildings, sidewalk the rest. Measured: it runs from the kerb to the building faces."""
        P = area(safe("difference", U, C))
        if P.is_empty:
            return
        near = [b for k in (btree.query(U.buffer(OPEN_M)) if btree is not None else []) for lv, b in [blds[k]] if lv == level]
        B = shapely.union_all(near) if near else shapely.Polygon()
        kerb = C.boundary if not C.is_empty else shapely.LineString()
        furn = [o for o in ([objs[k] for k in otree.query(P)] if otree is not None else []) if o[2] == level and o[1] in FURNITURE and o[4].within(P)]
        for k, piece in enumerate(polys(P), start=1):
            grp = corner_of(piece, k) if corner_of else None
            here = [o[4] for o in furn if o[4].within(piece)]
            if here and not kerb.is_empty:
                d = min(max(sorted(p.distance(kerb) for p in here)[int(0.8 * (len(here) - 1))] + 0.6, 0.8), 4.0)
                strip = safe("intersection", safe("intersection", piece, kerb.buffer(d)), shapely.union_all([p.buffer(FURNISH_ALONG_M) for p in here]))
                add(uid, level, "furnishing", strip, "measured", arm=grp, width=d)
            reach = [x.buffer(OPEN_M) for x in (B, kerb) if not x.is_empty]
            far = safe("difference", piece, shapely.union_all(reach)) if reach else shapely.Polygon()
            add(uid, level, "open", far, "measured", arm=grp)
            add(uid, level, "sidewalk", piece, "measured", arm=grp)

    def across(uid, line_or_cut, ln, C, inside):
        """Widths along a cross line: (roadway, pedestrian left, pedestrian right), left / right seen along `ln`."""
        left = right = 0.0
        for seg in shapely.get_parts(safe("difference", inside, C.buffer(0.05))):
            if seg.geom_type != "LineString" or seg.is_empty:
                continue
            m = seg.interpolate(0.5, normalized=True)
            t = ln.project(m)
            tx, ty = direction(ln, t)
            q = ln.interpolate(t)
            if tx * (m.y - q.y) - ty * (m.x - q.x) > 0:
                left += seg.length
            else:
                right += seg.length
        return round(safe("intersection", inside, C.buffer(0.05)).length, 1), round(left, 1), round(right, 1)

    def line_in(r, U, pad=0.5):
        piece = safe("intersection", r["g"], U.buffer(pad))
        return max((x for x in shapely.get_parts(shapely.line_merge(piece) if piece.geom_type == "MultiLineString" else piece)
                    if x.geom_type == "LineString" and not x.is_empty), key=lambda x: x.length, default=None)

    measured = {}   # road (edge id) -> [(left, right)] measured mid-block in its subsections, sides seen along the road's own geometry

    def along_own(r, ln):    # does `ln` run the way the road's own geometry (src -> dst) runs?
        g0, g1, l0, l1 = r["g"].coords[0], r["g"].coords[-1], ln.coords[0], ln.coords[-1]
        return (g1[0] - g0[0]) * (l1[0] - l0[0]) + (g1[1] - g0[1]) * (l1[1] - l0[1]) >= 0

    for uid, kind, sec, level, U in sorted(units, key=lambda u: u[1] == "intersection"):
        if kind in ("intersection", "roundabout"):
            rb = kind == "roundabout"
            arms = []
            for eid, cut in cuts.get(uid, []):
                r = roads.get(eid)
                ln = line_in(r, U) if r is not None else None
                if ln is None:
                    continue
                if shapely.Point(ln.coords[0]).distance(cut) < shapely.Point(ln.coords[-1]).distance(cut):
                    ln = shapely.LineString(ln.coords[::-1])          # from the junction out to the cut
                lx = line_in(r, U, pad=BAND_PAD_M)                    # the same road run on past the cut: its bands reach a slanted cut
                if lx is not None and shapely.Point(lx.coords[0]).distance(shapely.Point(ln.coords[0])) > shapely.Point(lx.coords[-1]).distance(shapely.Point(ln.coords[0])):
                    lx = shapely.LineString(lx.coords[::-1])
                # the arm's roadway as measured mid-block on the same road (its subsections), else on its approach, else estimated
                ms = measured.get(eid)
                if ms:
                    # the road's widths in the subsection that meets this cut, so arm and road line up there (else the road's median)
                    at = min(ms, key=lambda x: x[3].distance(cut))
                    if at[3].distance(cut) < 0.5:
                        lm, rm, src_ = at[0], at[1], at[2]
                    else:
                        lm, rm = sorted(x[0] for x in ms)[len(ms) // 2], sorted(x[1] for x in ms)[len(ms) // 2]
                        src_ = sorted(x[2] for x in ms)[0]
                    hl, hr = (lm, rm) if along_own(r, ln) else (rm, lm)
                else:
                    hl, hr, src_ = kerbs(ln, level, r)
                ends_here = not along_own(r, ln)     # the arm runs out from the junction: a one-way road running the other way comes in
                arms.append(dict(eid=eid, r=r, ln=ln, lx=lx or ln, cut=cut, hl=hl, hr=hr, src=src_,
                                 one="in" if ends_here else "out", name=r["name"]))
            # the roadway of a junction, built from its arms as on the street: each arm's roadway up to the junction, the kerbs of
            # neighbouring arms joined around each block corner with a rounded corner
            C = shapely.Polygon()
            if arms:
                cx = sum(a["ln"].coords[0][0] for a in arms) / len(arms); cy = sum(a["ln"].coords[0][1] for a in arms) / len(arms)
                kerb_pts, bodies = [], []
                for a in arms:
                    end = shapely.Point(a["ln"].coords[-1])
                    tx, ty = direction(a["ln"], a["ln"].length)
                    kerb_pts += [(end.x - ty * a["hl"], end.y + tx * a["hl"]), (end.x + ty * a["hr"], end.y - tx * a["hr"])]
                    bodies.append(band(a["lx"], -a["hr"], a["hl"]))
                kerb_pts.sort(key=lambda q: math.atan2(q[1] - cy, q[0] - cx))
                star = shapely.make_valid(shapely.Polygon(kerb_pts)) if len(kerb_pts) >= 3 else shapely.Polygon()
                ring = []     # a roundabout's ring: its road edges inside the space, each with its roadway band
                if rb:
                    for e in (rtree_ids[k] for k in rtree.query(U)):
                        r_ = roads[e]
                        if r_["osm"] in ring_osm and r_["level"] == level:
                            lr = line_in(r_, U, pad=BAND_PAD_M)
                            if lr is not None:
                                hl_, hr_ = estimate(r_)
                                ring.append((e, lr, hl_, hr_))
                road = shapely.union_all([star] + bodies + [band(lr, -hr_, hl_) for e, lr, hl_, hr_ in ring]).buffer(KERB_RADIUS_M).buffer(-KERB_RADIUS_M)
                # next to each cut the roadway is only what the arms' road bands cover (the same bands the roads beyond the cuts are drawn
                # with): arm and road meet without a step; the kerb outline and its rounding shape only the corners farther in
                all_bodies = shapely.union_all(bodies)
                for a in arms:
                    zone = safe("intersection", a["cut"].buffer(KERB_RADIUS_M + 1.0), U)
                    road = safe("union", safe("difference", road, zone), safe("intersection", safe("intersection", road, all_bodies), zone))
                C = area(safe("intersection", road, U))
            taken = crossings(uid, level, U, C, [a["ln"] for a in arms])
            if rb and ring:
                # the central island: the ground the ring encloses, outside its roadway (not roadway, however the outline was drawn)
                enclosed = shapely.union_all([pg for pg in shapely.get_parts(shapely.polygonize([lr for _, lr, _, _ in ring]))] or [shapely.Polygon()])
                ringway = shapely.union_all([band(lr, -hr_, hl_) for _, lr, hl_, hr_ in ring])
                island = safe("intersection", safe("difference", enclosed, ringway), U)
                if not island.is_empty:
                    taken = safe("union", taken, add(uid, level, "island", island, "measured"))
                    C = area(safe("difference", C, island))
                # the circulating lanes, in the ring's driving direction (a ring is one-way along its own geometry)
                for e, lr, hl_, hr_ in ring:
                    lanes_r, *_ = lane_set(uid, level, safe("difference", C, taken), lr, roads[e], "circulating", "circulating", "circulating",
                                           arm="ring", half=(hl_, hr_, "estimated"))
                    taken = safe("union", taken, shapely.union_all([x[1] for x in lanes_r] or [shapely.Polygon()]))
            bodies = {a["eid"]: band(a["lx"], -a["hr"], a["hl"]) for a in arms}
            arm_lanes = {}
            for a in arms:
                # an arm's lanes run straight from its cut into the junction, as far as no other arm's roadway (and no crosswalk on it)
                # lies across them: the stop position. Same widths and offsets as the road's lanes beyond the cut.
                others = [bodies[b["eid"]] for b in arms if b is not a]
                ln = a["lx"]
                block = safe("intersection", bodies[a["eid"]], safe("union", shapely.union_all(others) if others else shapely.Polygon(), taken))
                pts = shapely.get_coordinates(block) if not block.is_empty else []
                s_stop = min(max([ln.project(shapely.Point(q)) for q in pts] or [0.0]), max(a["ln"].length - 1.0, 0))
                ap = substring(ln, s_stop, ln.length) if s_stop > 0 else ln
                a["s_stop"], a["ap"] = s_stop, ap
                # seen from the junction (the line runs outwards): right-hand traffic drives out on the right and comes in on the left
                lanes, n_r, n_l, wl, src = lane_set(uid, level, safe("difference", C, taken), ap, a["r"], "out", "in", a["one"], arm=a["name"],
                                                    half=(a["hl"], a["hr"], a["src"]), arrows="ends")
                arm_lanes[a["eid"]] = (lanes, wl, src)
                taken = safe("union", taken, shapely.union_all([x[1] for x in lanes] or [shapely.Polygon()]))
            box = add(uid, level, "junction box", safe("difference", C, taken), "measured")
            # guide lines through the junction box: from every lane coming in to every lane going out on another arm, a smooth curve
            # through the junction (how lanes connect across it; a dashed line on the map)
            ends = []    # (arm, in / out, point at the stop position, heading into the junction)
            for a in arms:
                ap = a.get("ap")
                if ap is None:
                    continue
                c0 = ap.interpolate(0)
                tx, ty = direction(ap, 0)
                for d, poly, lo, hi in arm_lanes.get(a["eid"], ([], 0, ""))[0]:
                    m_ = (lo + hi) / 2
                    q = (c0.x - ty * m_, c0.y + tx * m_)
                    for kind_ in (("in", "out") if d == "both" else (d,)):
                        ends.append((a["eid"], kind_, q, (-tx, -ty)))
            if rb:
                ends = []     # a roundabout: the circulating lanes show the way round, no guide lines across it
            cx_, cy_ = (sum(q[2][0] for q in ends) / len(ends), sum(q[2][1] for q in ends) / len(ends)) if ends else (0, 0)
            for ea, ka, pa, _ in ends:
                for eb, kb, pb, _ in ends:
                    if ka != "in" or kb != "out" or ea == eb:
                        continue
                    curve = [((1 - t) ** 2 * pa[0] + 2 * (1 - t) * t * cx_ + t * t * pb[0], (1 - t) ** 2 * pa[1] + 2 * (1 - t) * t * cy_ + t * t * pb[1])
                             for t in [i / 12 for i in range(13)]]
                    mark(uid, level, "guide line", safe("intersection", shapely.LineString(curve), C))
            for a in arms:      # stop / give-way lines: across the in lanes, at the stop position, where a sign or a signal says so
                near = [objs[k] for k in otree.query(a["ln"].buffer(max(a["hl"], a["hr"]) + 6))] if otree is not None else []
                ctl = [o for o in near if o[3] and o[2] == level and o[4].distance(shapely.Point(a["ln"].coords[0])) <= CONTROL_M]
                if rb:
                    ctl = [(None, None, level, "give_way", None)]      # at a roundabout every entry gives way to the ring
                ins = [(lo, hi) for d, p, lo, hi in arm_lanes.get(a["eid"], ([], 0, ""))[0] if d in ("in", "both")]
                if ctl and ins and "ap" in a:
                    lo, hi = min(x[0] for x in ins), max(x[1] for x in ins)
                    c0 = a["ap"].interpolate(0.2)
                    tx, ty = direction(a["ap"], 0.2)
                    mark(uid, level, "give-way line" if all(o[3] == "give_way" for o in ctl) else "stop line",
                         shapely.LineString([(c0.x - ty * lo, c0.y + tx * lo), (c0.x - ty * hi, c0.y + tx * hi)]), a["name"])
            mark(uid, level, "kerb", safe("intersection", C.boundary, U.buffer(-0.05)))

            def corner_of(piece, k):    # a corner takes the names of the two arms it lies between
                near_arms = sorted(arms, key=lambda a: a["ln"].distance(piece))[:2]
                return " / ".join(a["name"] for a in near_arms) if near_arms else f"corner {k}"
            pedestrian(uid, level, U, C, corner_of)
            for a in arms:      # widths at the cut
                road_w, left, right = across(uid, a["cut"], a["ln"], C, a["cut"])
                lanes, wl, src = arm_lanes.get(a["eid"], ([], 0, a["src"]))
                widths.append((uid, level, a["eid"], a["name"], round(a["cut"].length, 1), road_w, left, right,
                               sum(x[0] in ("in", "both") for x in lanes), sum(x[0] in ("out", "both") for x in lanes), round(wl, 2), src))
        else:   # a subsection: its road (and a parallel one it carries) in lanes, crossings, the pedestrian realm
            line = sub_of.get(uid, (None, None))[1]
            own = [e for e in (rtree_ids[k] for k in rtree.query(U)) if roads[e]["level"] == level and roads[e]["g"].intersection(U).length > 1.0]
            lines, halves = {}, {}
            for e in sorted(own, key=lambda e: -roads[e]["g"].intersection(U).length):
                ln, lx = line_in(roads[e], U), line_in(roads[e], U, pad=BAND_PAD_M)
                if ln is None:
                    continue
                if line is not None and line.project(shapely.Point(ln.coords[-1])) < line.project(shapely.Point(ln.coords[0])):
                    ln = shapely.LineString(ln.coords[::-1])   # along the subsection, so forward / backward agree on its pieces
                if lx is not None and line is not None and line.project(shapely.Point(lx.coords[-1])) < line.project(shapely.Point(lx.coords[0])):
                    lx = shapely.LineString(lx.coords[::-1])
                lines[e], halves[e] = (lx or ln), kerbs(ln, level, roads[e])      # bands run on past the unit (a slanted cut); kerbs measured inside
                hl, hr, src_ = halves[e]
                measured.setdefault(e, []).append(((hl, hr, src_) if along_own(roads[e], ln) else (hr, hl, src_)) + (U,))
            # the roadway runs kerb to kerb along each of its roads
            C = area(safe("intersection", shapely.union_all([band(lines[e], -halves[e][1], halves[e][0]) for e in lines] or [shapely.Polygon()]), U))
            taken = crossings(uid, level, U, C, list(lines.values()))
            near = [paths[k] for k in ptree.query(U)] if ptree is not None else []
            track = shapely.union_all([safe("intersection", ln.buffer(TRACK_M / 2, cap_style="flat"), U) for typ, sb, lv, ln in near
                                       if typ == "cycleway" and sb != "crossing" and lv == level] or [shapely.Polygon()])
            add(uid, level, "cycle lane", track, "measured", width=TRACK_M)
            ulanes, wls, srcs = [], [], set()
            for e, ln in lines.items():
                one = "forward" if along_own(roads[e], ln) else "backward"     # a one-way road runs the way its own geometry runs
                lanes, n_r, n_l, wl, src = lane_set(uid, level, safe("difference", C, taken), ln, roads[e], "forward", "backward",
                                                    one if roads[e]["oneway"] else "forward", half=halves[e])
                ulanes += lanes; wls.append(wl); srcs.add(src)
                taken = safe("union", taken, shapely.union_all([x[1] for x in lanes] or [shapely.Polygon()]))
            add(uid, level, "carriageway", safe("difference", C, taken), "measured")
            mark(uid, level, "kerb", safe("intersection", C.boundary, U.buffer(-0.05)))
            pedestrian(uid, level, U, C)
            if line is not None and line.length > 0:     # widths across the middle
                mid = line.interpolate(0.5, normalized=True)
                tx, ty = direction(line, line.length / 2)
                cross = shapely.LineString([(mid.x + ty * 60, mid.y - tx * 60), (mid.x - ty * 60, mid.y + tx * 60)])
                inside = safe("intersection", cross, U)
                road_w, left, right = across(uid, cross, line, C, inside)
                n_f = sum(d in ("forward", "both") and not p.is_empty and p.intersects(inside) for d, p, *_ in ulanes)    # the lanes the line across meets
                n_b = sum(d in ("backward", "both") and not p.is_empty and p.intersects(inside) for d, p, *_ in ulanes)
                widths.append((uid, level, "middle", None, round(inside.length, 1), road_w, left, right, n_f, n_b,
                               round(sum(wls) / len(wls), 2) if wls else None, sorted(srcs)[0] if srcs else "estimated"))

    pdf = pd.DataFrame(parts, columns=["unit_id", "part_id", "level", "type", "arm", "direction", "lane", "width_m", "source", "wkb"])
    mdf = pd.DataFrame(marks, columns=["unit_id", "level", "type", "arm", "length_m", "wkb"])
    wdf = pd.DataFrame(widths, columns=["unit_id", "level", "edge", "arm", "total_m", "carriageway_m", "left_m", "right_m", "lanes_in", "lanes_out",
                                        "lane_m", "source"])
    to_ll = f"ST_Transform(ST_GeomFromWKB(wkb::BLOB), '{epsg}', 'EPSG:4326', always_xy := true)"
    con.execute(f"""CREATE OR REPLACE TABLE space.part AS SELECT unit_id, part_id, level::INT AS level, type, arm, direction, lane::INT AS lane,
                    width_m::DOUBLE AS width_m, source, ST_CollectionExtract(ST_MakeValid({to_ll}), 3) AS geometry FROM pdf""")
    con.execute(f"CREATE OR REPLACE TABLE space.mark AS SELECT unit_id, level::INT AS level, type, arm, length_m, {to_ll} AS geometry FROM mdf")
    con.execute("CREATE OR REPLACE TABLE space.width AS SELECT * FROM wdf")
