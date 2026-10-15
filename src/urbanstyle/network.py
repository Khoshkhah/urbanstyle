"""Steps 2-7 of docs/design/pipeline.md: the street at level 0 from the road network, data first. It writes the same level-0 rows as
division.py (space.unit, part, mark, subsection, junction) and replaces it when URBANSTYLE_DIVISION=network.

    roads        OSM's street roads at level 0 (not paths, not pedestrian streets, not the ways of a bridge that has a profile)
    carriageway  each road's lanes from OSM (`lanes`, per direction from duckOSM's driving network; a two-way road one lane each way at
                 least), centred on its own OSM line, LANE_M each or OSM `width` shared; parking and bike lanes beside them only where
                 OSM tags them; the kerb is its outer edge (a result, never guessed)
    junctions    at each node where 3 or more road ends meet (a road through it counts 2): the arms' carriageways where they overlap, out
                 to each arm's stop line (the far edge of OSM's crosswalk within CROSS_NEAR_M, else JUNC_ARM_M past the overlap), each
                 arm cut square across its line there; corners rounded by KERB_RADIUS_M; junctions that overlap are one (id i0-<smallest node>)
    sections     each road from junction to junction (id s0-w<way>[.n], one subsection /1 each): its carriageway less the junctions
    pedestrian   the street (the area less the blocks) less the roadway, each piece to the nearest roadway (section or junction):
                 furnishing FURNISH_M, sidewalk CLEAR_M, the rest frontage (chosen widths)
    crosswalks   OSM's crossing ways over the roadway, and crossing nodes with no way, as parts cut from the lanes; their paint from
                 `crossing:markings` (zebra bars, crossing lines, or none)
    marks        kerbs (the roadway's edge facing the pedestrian side), lane and centre lines only between lanes OSM maps, stop lines
"""
import json
import math

STREET = ("motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street")
LANE_M = 3.25           # a lane where OSM gives no width (chosen)
LANE_RANGE = (2.5, 4.5)  # a lane from OSM's width shared by its lanes, kept in this range
PARK_M, BIKE_M = 2.4, 1.75  # a parking lane, a bike lane (chosen)
FURNISH_M, CLEAR_M = 1.0, 1.8   # the pedestrian side: the furnishing zone at the kerb, the clear path (chosen)
KERB_RADIUS_M = 4.0
PARK_EXTRA_M = 3.0      # an outer lane widens to the city's kerb evidence by at most this (a parking strip and the gutter; chosen)
ALLEY_W_M = 5.0         # a service road's width where OSM gives none (chosen): its driveway across the sidewalk
ALLEY_HALF_M = 2.5      # the kerb is dropped this far either side of where a service road (an alley, a driveway) joins the roadway (chosen)
SLIVER_M2 = 20.0        # a subsection whose roadway outside the junctions is smaller than this joins the junction it touches (chosen)
CUT_M = 60.0            # a roadway cut (stop line, joint) runs this far to each side across the sidewalks to the blocks
MERGE_DEG = 45.0        # a road continues into another at a node when their headings are within this angle (chosen)
CORE_MIN_M = 1.0        # a junction's core counts only where the arms' carriageways overlap at least this wide (chosen)
FILLET_MAX_M2 = 40.0    # a corner fillet of KERB_RADIUS_M is at most this big (a 30 degree corner: 2.4 R2); a bigger closing is a gap, no corner
JUNC_ARM_M, CROSS_NEAR_M, CROSS_HALF_M = 3.0, 15.0, 1.5
STOP_BACK_M = 1.0       # a stop line stands this far before the junction (chosen, as division.py)
CROSSWALK_M, ZEBRA_BAR_M, ZEBRA_GAP_M = 3.0, 0.5, 0.5     # a crosswalk where OSM gives no width; its bars (as parts.py)          # the roadway's edge sampled this often to share the pedestrian side out
COLORS = {"subsection": "#94a3b8", "intersection": "#fbbf24"}
YES_PARK = ("parallel", "diagonal", "perpendicular", "lane", "street_side", "on_street", "half_on_kerb", "on_kerb", "marked", "yes")
YES_BIKE = ("lane", "track", "buffered_lane", "opposite_lane", "opposite_track")
ARM_M = 3.0             # a junction reaches this far into each arm (bridge_lidar reads it)
GAP_M = 8.0             # a strip between two roadways narrower than this (a block is at least this wide) is roadway, unless OSM maps a kerb, an object or a path on it
TAPER_M = 15.0          # a lane that the next subsection of the road does not have narrows to nothing over this length (chosen)
STRAIGHT_M = 2.0        # a road between two junctions whose OSM line stays this near the straight line between its ends is drawn straight
                        # (chosen: OSM's drawing error; Fir Street, Kaveh 2026-10-14)
ISLAND_TOUCH_M = 2.0    # a pedestrian piece whose boundary runs less than this along a block's edge lies between roadways: an island (chosen)
ISLAND_MIN_M2 = 4.0     # a pedestrian piece that touches no block and is smaller than this is no island: it is part of the sidewalk (chosen)
from .parts import ARROW_M  # noqa: E402

ROAD_T = ("lane", "carriageway", "junction area", "parking", "cycle lane", "bridge deck")     # the parts a crosswalk is cut from


def num_f(v):
    """A tag's metres as a float (`3`, `3.5 m`), else None."""
    try:
        return float(str(v).replace("m", "").strip()) if v else None
    except ValueError:
        return None


def markings(tg):
    """A crossing's paint from its OSM tags: 'zebra', 'lines', 'dashes', 'ladder', 'dots', 'no' (unmarked) or 'unknown' (a crossing with no
    markings mapped: a crosswalk part, no paint). `crossing:markings` decides; without it, `crossing`: zebra, marked and uncontrolled
    (OSM: a marked crossing with no signals) are zebra, unmarked is none, traffic_signals alone is unknown. `yes` (marked, kind not
    mapped) is drawn as zebra, the common kind."""
    mk = str(tg.get("crossing:markings") or "").split(";")[0].strip()
    if mk in ("yes", "zebra"):
        return "zebra"
    if mk in ("lines", "dashes", "ladder", "ladder:skewed", "skewed", "dots", "surface", "pictograms"):
        return mk
    if mk == "no":
        return "no"
    cr = tg.get("crossing")
    if cr in ("zebra", "marked", "uncontrolled") or tg.get("crossing_ref") == "zebra":
        return "zebra"
    if cr in ("unmarked", "informal"):
        return "no"
    return "unknown"


def unit_v(v):
    h = math.hypot(v[0], v[1]) or 1.0
    return (v[0] / h, v[1] / h)


def shift_line(ln, d):
    """ln moved sideways by d (left +), vertex by vertex along the local normal: the same vertices, the same direction. (shapely's
    offset_curve reverses or empties a line for a negative offset, and the move was silently lost.)"""
    import shapely
    c = list(ln.coords)
    out = []
    for i, (x, y) in enumerate(c):
        a = c[max(i - 1, 0)]
        b = c[min(i + 1, len(c) - 1)]
        nx, ny = unit_v((-(b[1] - a[1]), b[0] - a[0]))
        out.append((x + nx * d, y + ny * d))
    return shapely.LineString(out)


def straight(ln):
    """ln as the straight line between its ends where it stays within STRAIGHT_M of that line, else ln (a real curve)."""
    import shapely
    ch = shapely.LineString([ln.coords[0], ln.coords[-1]])
    return ch if ch.length > 0.5 and ln.hausdorff_distance(ch) <= STRAIGHT_M else ln


# the level-0 tables this module writes, with their columns and types (other levels: spaces.py, parts.py)
V, D, I, G_ = "VARCHAR", "DOUBLE", "INTEGER", "GEOMETRY"
SCHEMA = {
    "unit": dict(unit_id=V, kind=V, section_id=V, level=I, color=V, geometry=G_),
    "part": dict(unit_id=V, part_id=V, level=I, type=V, arm=V, direction=V, lane=I, lane_id=V, width_m=D, width_source=V, width_method=V, length_m=D,
                 source=V, method=V, ref=V, position_source=V, position_method=V, position_ref=V, road=V, road_class=V, speed=V, surface=V, lit=V, road_lanes=V, oneway=V, holds=V, rule=V, geometry=G_),
    "mark": dict(unit_id=V, level=I, type=V, arm=V, length_m=D, width_m=D, width_source=V, width_method=V, source=V, method=V, ref=V, geometry=G_),
    "width": dict(unit_id=V, level="BIGINT", edge=V, arm=V, total_m=D, carriageway_m=D, left_m=D, right_m=D, lanes_in="BIGINT", lanes_out="BIGINT",
                  lane_m=D, source=V, osm_lanes="BIGINT"),
    "subsection": dict(subsection_id=V, section_id=V, level=I, **{"class": V}, width_m=D, oneway="BOOLEAN", length_m=D, left=V, right=V, left_m=D,
                       right_m=D, left_extra=D, right_extra=D, with_sections=V, starts_at=V, color=V, geometry=G_),
    "cut": dict(intersection_id=V, edge_id=V, level=I, how=V, length_m=D, geometry=G_),
    "junction": dict(intersection_id=V, node_id="BIGINT", level=I, cluster_id=V),
    "turn": dict(unit_id=V, level=I, from_edge=V, from_lane=I, to_edge=V, to_lane=I, turn=V, source=V, vehicles=V, condition=V, geometry=G_),
    "approach": dict(unit_id=V, level=I, from_edge=V, lane=I, moves=I, ways=V, arrow="BOOLEAN", no_arrow_because=V),
}


def arrow_shape(tip, h, ways):
    """A painted lane arrow (parts.py's shape): a shaft ARROW_M long to `tip` along unit h, a head for each of `ways` (straight, left,
    right)."""
    import shapely
    hx, hy = h
    tail = (tip[0] - hx * ARROW_M, tip[1] - hy * ARROW_M)
    fork = (tail[0] + hx * ARROW_M * 0.45, tail[1] + hy * ARROW_M * 0.45)
    pieces, heads = [[tail, tip if "straight" in ways else fork]], []
    if "straight" in ways:
        heads.append((tip, (hx, hy)))
    for w in ("left", "right"):
        if w in ways:
            sx, sy = (-hy, hx) if w == "left" else (hy, -hx)
            end = (fork[0] + hx * 0.7 + sx * 1.0, fork[1] + hy * 0.7 + sy * 1.0)
            pieces.append([fork, end])
            d = math.hypot(end[0] - fork[0], end[1] - fork[1])
            heads.append((end, ((end[0] - fork[0]) / d, (end[1] - fork[1]) / d)))
    for (px, py), (dx, dy) in heads:
        pieces.append([(px - dx * 0.8 - dy * 0.4, py - dy * 0.8 + dx * 0.4), (px, py), (px - dx * 0.8 + dy * 0.4, py - dy * 0.8 - dx * 0.4)])
    return shapely.MultiLineString(pieces)


def build(con, epsg, bridges=()):
    import duckdb
    import numpy as np
    import shapely
    from shapely.ops import substring

    m = lambda col="geometry": f"ST_AsWKB(ST_Transform({col}, 'EPSG:4326', '{epsg}', always_xy := true))"
    g = lambda w: shapely.make_valid(shapely.from_wkb(bytes(w)))
    poly = lambda x: shapely.union_all([p for q in shapely.get_parts(x) for p in shapely.get_parts(q) if p.geom_type == "Polygon"]
                                       or [shapely.Polygon()])
    to_ll = f"ST_Transform(ST_GeomFromWKB(?), '{epsg}', 'EPSG:4326', always_xy := true)"

    def rows(sql, args=None):
        try:
            return con.execute(sql, args or []).fetchall()
        except duckdb.CatalogException:
            return []

    # ---- 2. the road network
    bridge_ways = {int(w[1:]) for pf in bridges for a in json.load(open(pf)).get("axes", []) for w in a.get("ways", [])}
    landing_ways = {int(str(ld.get("way", "w0"))[1:]) for pf in bridges for a in json.load(open(pf)).get("axes", []) for ld in a.get("landings", [])}
    cand = [(oid, nm, cl, bool(ow), s_, d_, g(w), lv) for oid, nm, cl, ow, s_, d_, w, lv in rows(f"""SELECT osm_id, name, class, coalesce(oneway, false),
                 src, dst, {m()}, level_min FROM space.element WHERE type IN ('road', 'walkway') AND level_min IN (0, 1)
                 AND replace(class, '_link', '') IN {STREET}""")]
    # (a level-1 deck is the street at ground level where nothing at level 0 passes under it, as for the blocks; the ways of a bridge that
    # has a profile are the bridge model's: one 'bridge deck' part on their band, no lanes)
    ground_lines = [c[6] for c in cand if c[7] == 0] + [g(w) for (w,) in rows(f"SELECT {m()} FROM space.element WHERE type = 'rail' AND level_min = 0")]
    gl_tree = shapely.STRtree(ground_lines) if ground_lines else None
    keep_ = [c for c in cand if c[7] == 0 or gl_tree is None or not any(ground_lines[k].crosses(c[6]) for k in gl_tree.query(c[6]))]
    edges = [c[:7] for c in keep_]
    l1_ground = {c[0] for c in keep_ if c[7] == 1} - bridge_ways      # (drawn here on the ground: no copy at level 1, below)
    edges = [e for e in edges if e[6].geom_type == "LineString" and e[6].length > 0.2]
    oids = sorted({e[0] for e in edges})
    tags = {o: dict(t or {}) for o, t in rows("SELECT osm_id, tags FROM osm.raw.ways WHERE osm_id IN (SELECT unnest(?::BIGINT[]))", [oids])}
    try:        # (duckOSM's lanes per direction; a network without them: OSM's tags alone)
        lanes = {(o, bool(r)): int(n) for o, r, n in con.execute("""SELECT osm_id, is_reverse, median(lanes) FROM osm.driving.edges
                                                                    WHERE lanes IS NOT NULL GROUP BY 1, 2""").fetchall()}
    except duckdb.Error:
        lanes = {}
    from .corrections import lanes as corrected, per_direction
    CORR = corrected()
    for o, (tg_c, _) in CORR.items():
        f_c, b_c = per_direction(tg_c, (o, True) not in lanes)
        lanes[(o, False)] = f_c
        if b_c:
            lanes[(o, True)] = b_c
    num = lambda v: int(v) if str(v or "").isdigit() else None
    from .blocks import _city
    city = _city(con)

    def city_geoms(name):
        out = []
        for f in (city.get(name) or {}).get("features", []):
            if f.get("geometry"):
                (w,) = con.execute(f"SELECT ST_AsWKB(ST_Transform(ST_GeomFromGeoJSON(?), 'EPSG:4326', '{epsg}', always_xy := true))",
                                   [json.dumps(f["geometry"])]).fetchone()
                out.append((f.get("properties") or {}, g(w)))
        return out
    meters = [(f"parking-meters:{pr.get('meter_id')}", x) for pr, x in city_geoms("parking-meters")]
    bikeways = [(f"bikeways:{pr.get('object_id')}", x) for pr, x in city_geoms("bikeways")
                if any(k in str(pr.get("bikeway_type") or "") for k in ("Painted", "Protected", "Separated"))]
    meter_t = shapely.STRtree([x for _, x in meters]) if meters else None
    basins = [x for _, x in city_geoms("sewer-catch-basins") if x.geom_type == "Point"]     # (the city's kerb evidence: a basin stands in the gutter)
    basin_t = shapely.STRtree(basins) if basins else None
    bike_t = shapely.STRtree([x for _, x in bikeways]) if bikeways else None

    def cross_section(oid, ow):
        """(forward lanes, backward lanes, lane width, its source, extras {+1: [(type, w, source)], -1: [...]}, lane source)."""
        tg = tags.get(oid, {})
        f, b = lanes.get((oid, False)), lanes.get((oid, True))
        n = num(tg.get("lanes"))
        if f is None and b is None:
            if ow:
                f, b = n or 1, 0
            else:
                f = num(tg.get("lanes:forward")) or (n // 2 if n and n >= 2 else 1)
                b = num(tg.get("lanes:backward")) or ((n - f) if n and n > f else 1)
        if ow:
            f, b = max(f or 1, 1), 0
        else:       # (a two-way road has a lane each way at least)
            f, b = max(f or 1, 1), max(b or 1, 1)
        # (mapped only where OSM tags the count: duckOSM's driving network fills a default count for an untagged way, which is no source)
        tagged = n is not None or num(tg.get("lanes:forward")) is not None or num(tg.get("lanes:backward")) is not None
        lsrc = ("corrections", "corrected") if oid in CORR else ("osm", "mapped") if tagged else ("urbanstyle", "chosen")
        wd = None
        try:
            wd = float(str(tg.get("width", "")).replace("m", "").strip()) if tg.get("width") else None
        except ValueError:
            wd = None
        lw, wsrc = (min(max(wd / (f + b), LANE_RANGE[0]), LANE_RANGE[1]), ("osm", "mapped")) if wd else (LANE_M, ("urbanstyle", "chosen"))
        ex = {1: [], -1: []}
        side = lambda s: 1 if s == "left" else -1          # (OSM's left of the way is our + side: the line runs the way's way)
        for k, v in tg.items():
            if k.startswith("cycleway") and k.count(":") <= 1 and v in YES_BIKE:
                for s in (("left", "right") if k in ("cycleway", "cycleway:both") else (k.split(":")[1],) if ":" in k else ()):
                    if s in ("left", "right"):
                        ex[side(s)].append(("cycle lane", BIKE_M, ("osm", "mapped", f"w{oid} {k}={v}")))
        for k, v in tg.items():
            if (k.startswith("parking:") and k.count(":") == 1 or k.startswith("parking:lane:") and k.count(":") == 2) and v in YES_PARK:
                s = k.split(":")[-1]
                for s2 in (("left", "right") if s == "both" else (s,)):
                    if s2 in ("left", "right"):
                        ex[side(s2)].append(("parking", PARK_M, ("osm", "mapped", f"w{oid} {k}={v}")))
        return f, b, lw, wsrc, ex, lsrc

    # ---- the junction nodes (3+ road ends; a road through counts 2)
    tree = shapely.STRtree([e[6] for e in edges])
    node_id = {}
    for oid, nm, cl, ow, s_, d_, ln in edges:
        for nid, q in ((s_, ln.coords[0]), (d_, ln.coords[-1])):
            if nid is not None:
                node_id.setdefault((round(q[0], 1), round(q[1], 1)), nid)

    def deg(p):
        d = 0
        for k in tree.query(p.buffer(0.5)):
            ln = edges[k][6]
            if ln.distance(p) <= 0.5:
                s = ln.project(p)
                d += 1 if (s < 0.5 or s > ln.length - 0.5) else 2
        return d
    def heads(p):
        """The unit heading of each road end at p, away from p (a road through p: two ends)."""
        out = []
        for k in tree.query(p.buffer(0.5)):
            ln = edges[k][6]
            if ln.distance(p) > 0.5:
                continue
            s_ = ln.project(p)
            for a_, b_ in ((s_, s_ + 3.0), (s_, s_ - 3.0)):
                if 0 <= b_ <= ln.length and not (b_ > s_ and s_ > ln.length - 0.5) and not (b_ < s_ and s_ < 0.5):
                    q1, q2 = ln.interpolate(a_), ln.interpolate(b_)
                    out.append(unit_v((q2.x - q1.x, q2.y - q1.y)))
        return out

    def crosses(p):
        """Whether the roads at p make a junction: a road that ends at p with no road continuing it (a T), or two streams through p
        that cross each other (their ends alternate round p). Two streams that only touch (a ramp joining a road, two one-way lines of
        one street drawn into one node) make no junction there: the roads continue through p as one section (Kaveh 2026-10-15)."""
        hs = heads(p)
        if len(hs) < 3:
            return False
        best = {}
        for i, a in enumerate(hs):
            cand = [(a[0] * b[0] + a[1] * b[1], j) for j, b in enumerate(hs) if j != i]
            cand = [(d_, j) for d_, j in cand if d_ < -math.cos(math.radians(MERGE_DEG))]
            if cand:
                best[i] = min(cand)[1]
        if len(best) < len(hs):
            return True             # (an end no road continues: a road ends at p)
        # (a stream: an end and the end it continues into; two streams can share an end, a Y where two roads merge into one)
        pairs = {(min(i, j), max(i, j)) for i, j in best.items()}
        ang = [math.atan2(h[1], h[0]) for h in hs]
        between = lambda x, a, b: (x - a) % (2 * math.pi) < (b - a) % (2 * math.pi)
        for (i, j) in pairs:
            for (k, l) in pairs:
                if (i, j) < (k, l) and len({i, j, k, l}) == 4 and between(ang[k], ang[i], ang[j]) != between(ang[l], ang[i], ang[j]):
                    return True     # (the streams cross)
        return False
    jn = []
    for e in edges:
        for q in (e[6].coords[0], e[6].coords[-1]):
            p = shapely.Point(q)
            if all(p.distance(o) > 1.0 for o in jn) and deg(p) >= 3 and crosses(p):
                jn.append(p)

    # ---- 3-4. carriageways: runs of one way with one cross-section, split at the junction nodes
    groups = {}
    for oid, nm, cl, ow, s_, d_, ln in edges:
        groups.setdefault((oid, nm, cl, ow), []).append(ln)
    def band(line, t1, t2):
        """The strip between offsets t1 < t2 (left +) of line, flat at its ends."""
        side = lambda d: line.buffer(d, single_sided=True, cap_style="flat", join_style="mitre", mitre_limit=3.0) if abs(d) > 1e-6 \
            else shapely.Polygon()
        if t1 >= 0:
            x = side(t2).difference(side(t1))
        elif t2 <= 0:
            x = side(t1).difference(side(t2))
        else:
            x = shapely.union_all([side(t2), side(t1)])
        return poly(shapely.make_valid(x))
    runs = []       # dict(oid, name, class, oneway, line, f, b, lw, ex, kl, kr)
    jtree = shapely.STRtree(jn) if jn else None
    for (oid, nm, cl, ow), ls in groups.items():
        merged = shapely.line_merge(shapely.union_all(ls))
        for ln in shapely.get_parts(merged):
            if ln.geom_type != "LineString" or ln.length < 0.5:
                continue
            cuts = sorted({0.0, ln.length} | {ln.project(jn[k]) for k in (jtree.query(ln.buffer(0.6)) if jtree is not None else [])
                                                if ln.distance(jn[k]) < 0.6})
            for a, b_ in zip(cuts, cuts[1:]):
                if b_ - a < 0.5:
                    continue
                piece = substring(ln, a, b_)
                f, b, lw, wsrc, ex, lsrc = cross_section(oid, ow)
                W = (f + b) * lw
                tg_ = tags.get(oid, {})
                no_ = lambda pre, s: any(tg_.get(k) in ("no", "none", "separate", "no_parking", "no_stopping")
                                         for k in (f"{pre}:{s}", f"{pre}:both", f"{pre}:lane:{s}", f"{pre}:lane:both"))
                for sg, s in ((1, "left"), (-1, "right")):      # (the city's meters and bikeways along a side; OSM's "no" there wins)
                    t0 = sg * W / 2
                    zone = band(piece, min(t0, t0 + sg * 6.0), max(t0, t0 + sg * 6.0))
                    if not any(e[0] == "parking" for e in ex[sg]) and not no_("parking", s) and meter_t is not None:
                        ms = [meters[k][0] for k in meter_t.query(zone) if zone.contains(meters[k][1])]
                        if ms:
                            ex[sg].append(("parking", PARK_M, ("vancouver", "mapped", ", ".join(ms[:3]))))
                    if not any(e[0] == "cycle lane" for e in ex[sg]) and not no_("cycleway", s) and bike_t is not None:
                        bw = [bikeways[k][0] for k in bike_t.query(zone) if bikeways[k][1].intersection(zone).length > 10]
                        if bw:
                            ex[sg].append(("cycle lane", BIKE_M, ("vancouver", "mapped", ", ".join(bw[:3]))))
                # parking in the outer lane (Kaveh, 2026-10-16): where no source gives a lane width and the city's kerb evidence (catch
                # basins, the median of 2 or more on a side) lies beyond the chosen lanes by up to PARK_EXTRA_M, the outer lane on that
                # side widens to it, one lane that holds parking (a dashed edge line); the count stays OSM's. More than that stays a
                # K1 report, and the lanes do not move
                wide = {1: 0.0, -1: 0.0}
                if basin_t is not None and wsrc[0] == "urbanstyle":
                    ln_ = straight(piece)
                    ts_ = {1: [], -1: []}
                    for k in basin_t.query(ln_.buffer(12.0)):
                        p_ = basins[k]
                        if ln_.distance(p_) > 12.0:
                            continue
                        s_ = ln_.project(p_)
                        if s_ < 2.0 or s_ > ln_.length - 2.0:
                            continue
                        q_, a_, b_ = ln_.interpolate(s_), ln_.interpolate(max(s_ - 1, 0)), ln_.interpolate(min(s_ + 1, ln_.length))
                        h_ = math.hypot(b_.x - a_.x, b_.y - a_.y) or 1
                        t_ = (-(p_.x - q_.x) * (b_.y - a_.y) + (p_.y - q_.y) * (b_.x - a_.x)) / h_
                        ts_[1 if t_ > 0 else -1].append(abs(t_))
                else:
                    ts_ = {1: [], -1: []}
                kl = W / 2 + sum(w for _, w, _ in ex[1])
                kr = -W / 2 - sum(w for _, w, _ in ex[-1])
                runs.append(dict(oid=oid, name=nm, cl=cl, ow=ow, line=straight(piece), f=f, b=b, lw=lw, wsrc=wsrc, lsrc=lsrc, ex=ex, kl=kl, kr=kr, W=W,
                                 wide=wide, basins=ts_, no_park={sg: no_("parking", s) for sg, s in ((1, "left"), (-1, "right"))}))

    # ---- 6a. sections between junctions: a road is often several OSM ways (split at a crossing node, or where its lanes change), so
    # the runs are chained where two of them meet at a node that is no junction; a run that continues the one before it with the same
    # cross-section is one subsection with it. A section is named by its longest way (s0-w<way>[.n]), its subsections /1, /2, ...
    # along it (a section that ended in the middle of the road: Kaveh 2026-10-15)
    def xkey(r):
        return (r["f"], r["b"], round(r["lw"], 2), r["cl"], r["ow"], r["name"], r["lsrc"], r["wsrc"], r["oid"] in bridge_ways,
                tuple((sg, t, round(w, 2), pv[0]) for sg in (1, -1) for t, w, pv in r["ex"][sg]))
    epts = [shapely.Point(r["line"].coords[e and -1]) for r in runs for e in (0, 1)]       # (run k's ends at 2k and 2k + 1)
    etree = shapely.STRtree(epts) if epts else None
    def head_of(i):     # run i // 2's heading at its end i % 2, away from the end
        ln = runs[i // 2]["line"]
        a_, b_ = (ln.interpolate(0), ln.interpolate(min(3.0, ln.length))) if i % 2 == 0 else (ln.interpolate(ln.length), ln.interpolate(max(ln.length - 3.0, 0)))
        return unit_v((b_.x - a_.x, b_.y - a_.y))
    nxt = {}        # (run, end) -> the run end it continues into, away from the junctions: the one most opposite to it, if mutual
    best = {}
    for i, p in enumerate(epts):
        if (jtree is not None and any(jn[j].distance(p) < 0.6 for j in jtree.query(p.buffer(0.6)))):
            continue
        hi = head_of(i)
        near_ = [j for j in etree.query(p.buffer(0.3)) if j != i and epts[j].distance(p) < 0.3 and j // 2 != i // 2]
        dots = [(hi[0] * head_of(j)[0] + hi[1] * head_of(j)[1], j) for j in near_]
        dots = [(d_, j) for d_, j in dots if d_ < -math.cos(math.radians(MERGE_DEG))]
        if dots:
            best[i] = min(dots)[1]
    for i, j in best.items():
        if best.get(j) == i:
            nxt[(i // 2, i % 2)] = (j // 2, j % 2)
    done_r, chains = set(), []
    for k0 in sorted(range(len(runs)), key=lambda k: -runs[k]["line"].length):
        if k0 in done_r:
            continue
        done_r.add(k0)
        chain = [(k0, False)]        # [(run, runs against the chain)]
        cur = (k0, 1)
        while cur in nxt:
            k, e = nxt[cur]
            if k in done_r:
                break
            done_r.add(k)
            chain.append((k, e == 1))
            cur = (k, 1 - e)
        back, cur = [], (k0, 0)
        while cur in nxt:
            k, e = nxt[cur]
            if k in done_r:
                break
            done_r.add(k)
            back.append((k, e == 0))
            cur = (k, 1 - e)
        chains.append(back[::-1] + chain)
    seen, runs2 = {}, []
    for chain in chains:
        pieces = []
        for k, flip in chain:
            r = dict(runs[k], flip=flip, oids=[runs[k]["oid"]], lens={runs[k]["oid"]: runs[k]["line"].length})
            if pieces and not flip and not pieces[-1]["flip"] and xkey(pieces[-1]) == xkey(r):
                a = pieces[-1]
                # (each piece straightened on its own, as the checks read the ways: a whole run straightened over 170 m left the lanes
                # 2 m off the last way's line, s0-w1419312039/1)
                a["line"] = shapely.LineString(list(a["line"].coords) + list(r["line"].coords)[1:])
                a["oids"] += r["oids"]
                a["lens"][r["oid"]] = a["lens"].get(r["oid"], 0) + r["line"].length
                continue
            pieces.append(r)
        lens = {}
        for r in pieces:
            for o, l_ in r["lens"].items():
                lens[o] = lens.get(o, 0) + l_
        base = f"s0-w{max(lens, key=lens.get)}"
        seen[base] = seen.get(base, 0) + 1
        sid = base if seen[base] == 1 else f"{base}.{seen[base]}"
        for i, r in enumerate(pieces):
            r["oid"] = max(r["lens"], key=r["lens"].get)
            r["sid"], r["sub"] = sid, f"{sid}/{i + 1}"
            r["cuts"] = []
            runs2.append(r)
        # the joint between two subsections: both roadways cut on the bisector of their directions there (two flat ends meeting at a
        # bend left a hairline gap that became pedestrian realm, with a kerb across the road; Kaveh 2026-10-15)
        for a, b in zip(pieces, pieces[1:]):
            ca, cb = list(a["line"].coords), list(b["line"].coords)
            pa, qa = (ca[-1], ca[-2]) if not a["flip"] else (ca[0], ca[1])        # a's joint end and the point before it
            pb, qb = (cb[0], cb[1]) if not b["flip"] else (cb[-1], cb[-2])        # b's joint end and the point after it
            da = unit_v((pa[0] - qa[0], pa[1] - qa[1]))
            db = unit_v((qb[0] - pb[0], qb[1] - pb[1]))
            n = unit_v((da[0] + db[0], da[1] + db[1])) if (da[0] + db[0], da[1] + db[1]) != (0.0, 0.0) else da
            a["cuts"].append((pa, n, -1, "end" if not a["flip"] else "start"))
            b["cuts"].append((pb, n, 1, "start" if not b["flip"] else "end"))
            # the lane transition at the joint (lanes slide from the neighbour's positions to their own over TAPER_M) is drawn in
            # the subsection with fewer lanes, else in the later one
            ta, tb = a["f"] + a["b"], b["f"] + b["b"]
            if ta < tb:
                a.setdefault("trans", {})["end" if not a["flip"] else "start"] = b
            else:
                b.setdefault("trans", {})["start" if not b["flip"] else "end"] = a
    runs = runs2
    # ---- 6a'. width is a section property (docs/design/joints.md, rule 1): the city's meters and the kerb evidence are judged once
    # for the whole section, so the kerb does not step where two subsections meet (a parking part from the meters in one half and
    # not in the other bulged Fir Street; Kaveh 2026-10-16)
    by_sid1 = {}
    for r in runs:
        by_sid1.setdefault(r["sid"], []).append(r)
    for sid, rs in by_sid1.items():
        sec_side = lambda r_, sg: sg if not r_["flip"] else -sg       # a run's side in the section's frame
        # the meters' parking on a side anywhere in the section: on that side in every piece whose way does not say no
        for sg in (1, -1):
            park = next((e for r_ in rs for e in r_["ex"][sec_side(r_, sg)] if e[0] == "parking" and e[2][0] == "vancouver"), None)
            if park is None:
                continue
            for r_ in rs:
                s_ = sec_side(r_, sg)
                if not any(e[0] == "parking" for e in r_["ex"][s_]) and not r_["no_park"][s_]:
                    r_["ex"][s_].append(("parking", PARK_M, (park[2][0], park[2][1], park[2][2] + " (along the section)")))
        # the kerb evidence: one median per side of the section; each piece's outer lane widens to it by its own extra. Not on a
        # ramp or a through road (a `_link`, motorway, trunk: no kerbside parking), and not toward another roadway within reach (the
        # basins there stand in a median's gutter, not at a parking kerb: the Granville ramp's lanes grew to 5.8 m, 2026-10-16)
        for sg in (1, -1):
            ts_ = [t for r_ in rs for t in r_["basins"][sec_side(r_, sg)]]
            if len(ts_) < 2:
                continue
            med_ = sorted(ts_)[len(ts_) // 2]
            for r_ in rs:
                s_ = sec_side(r_, sg)
                cl_ = r_["cl"] or ""
                if r_["wsrc"][0] != "urbanstyle" or r_["ex"][s_] or cl_.endswith("_link") or cl_ in ("motorway", "trunk"):
                    continue
                extra = med_ - r_["W"] / 2
                if not (0.3 <= extra <= PARK_EXTRA_M):
                    continue
                zone_ = band(r_["line"], min(s_ * r_["W"] / 2, s_ * (med_ + LANE_M)), max(s_ * r_["W"] / 2, s_ * (med_ + LANE_M)))
                if any(edges[k][0] != r_["oid"] and edges[k][6].intersection(zone_).length > 5.0 for k in tree.query(zone_)):
                    continue        # (another road runs there: the strip is a median, not a parking kerb)
                r_["wide"][s_] = round(extra, 2)
        for r_ in rs:
            r_["kl"] = r_["W"] / 2 + r_["wide"][1] + sum(w for _, w, _ in r_["ex"][1])
            r_["kr"] = -r_["W"] / 2 - r_["wide"][-1] - sum(w for _, w, _ in r_["ex"][-1])

    def half_plane(p, n, side, far=300.0):
        t = (-n[1], n[0])
        q1 = (p[0] + t[0] * far, p[1] + t[1] * far)
        q2 = (p[0] - t[0] * far, p[1] - t[1] * far)
        return shapely.Polygon([q1, q2, (q2[0] + side * n[0] * far, q2[1] + side * n[1] * far), (q1[0] + side * n[0] * far, q1[1] + side * n[1] * far)])

    def joint_line(r):
        """r's line run on past each joint by a little more than the roadway is wide, so the bands reach the bisector there."""
        ln = r["line"]
        c = list(ln.coords)
        e = (r["kl"] - r["kr"]) + 2.0
        for p, n, side, where in r["cuts"]:
            if where == "end":
                dx, dy = c[-1][0] - c[-2][0], c[-1][1] - c[-2][1]
                h = math.hypot(dx, dy) or 1
                c = c + [(c[-1][0] + dx / h * e, c[-1][1] + dy / h * e)]
            else:
                dx, dy = c[0][0] - c[1][0], c[0][1] - c[1][1]
                h = math.hypot(dx, dy) or 1
                c = [(c[0][0] + dx / h * e, c[0][1] + dy / h * e)] + c
        return shapely.LineString(c)

    def at_joints(r, geom):
        for p, n, side, where in r["cuts"]:
            geom = geom.intersection(half_plane(p, n, side))
        return geom
    for r in runs:
        r["xline"] = joint_line(r)
        r["shift"] = 0.0
    # ---- 6c. continuity at the joints: the lanes that run on through a joint keep their position; the kerb on the side where no road
    # merges continues straight. Where OSM's line of the next way is not the centre of the lanes drawn that way (within STRAIGHT_M: the
    # line's drawing error), the whole subsection's line is moved sideways by that much (`shift`), so its lanes, kerbs and lines
    # continue the previous subsection's. A larger step is a real change and slides over TAPER_M (the lane transition, below).
    # (every lane slid to its centred position at a joint: the ramp's lanes bent 1.6 m, the kerb and the guardrail with them; a
    # turn pocket bent all five lanes; Kaveh 2026-10-15: "lanes that continue do not move")
    ends_ = [(k, e, shapely.Point(r["line"].coords[0 if e == 0 else -1])) for k, r in enumerate(runs) for e in (0, 1)]
    etree2 = shapely.STRtree([p for _, _, p in ends_])
    by_sid2 = {}
    for r in runs:
        by_sid2.setdefault(r["sid"], []).append(r)

    def align(a, b, b_end):
        """b's shift so that its lanes continue a's across the joint at b's end `b_end` ("start" / "end" in b's own orientation)."""
        mirror = a["flip"] != b["flip"]
        cb = list(b["line"].coords)
        pj = shapely.Point(cb[0] if b_end == "start" else cb[-1])
        c0, c1 = (cb[0], cb[1]) if b_end == "start" else (cb[-2], cb[-1])       # (b's running direction: left / right in b's frame)
        hb = unit_v((c1[0] - c0[0], c1[1] - c0[1]))
        sides = set()
        for i_ in etree2.query(pj.buffer(0.6)):
            k_, e_, p_ = ends_[i_]
            if runs[k_] is a or runs[k_] is b or p_.distance(pj) > 0.6:
                continue
            far = shapely.Point(runs[k_]["line"].coords[-1 if e_ == 0 else 0])
            sides.add(1 if (hb[0] * (far.y - pj.y) - hb[1] * (far.x - pj.x)) > 0 else -1)
        ka = (a["kl"] + a["shift"], a["kr"] + a["shift"])      # a's kerbs in a's frame, (left, right)
        if mirror:
            ka = (-ka[1], -ka[0])
        kb = (b["kl"], b["kr"])
        if len(sides) == 1:
            keep = -next(iter(sides))           # the kerb opposite the merging road continues
            b["merge"] = (next(iter(sides)), pj)      # (the side the road merges from, in b's frame, and where)
            # (the merging road's end is cut on the joint's bisector too: its flat end at the node left a notch against the lane it
            # runs into, and the kerb line ran a tail into the lane; kerb-162, Kaveh 2026-10-16)
            n_ = next((n__ for p__, n__, _, _ in b["cuts"] if shapely.Point(p__).distance(pj) < 0.1), None)
            if n_ is not None:
                for i_ in etree2.query(pj.buffer(0.6)):
                    k_, e_, p_ = ends_[i_]
                    if runs[k_] is a or runs[k_] is b or p_.distance(pj) > 0.6:
                        continue
                    hd = head_of(i_)        # (away from the end: into the merging road)
                    into = -(hd[0] * n_[0] + hd[1] * n_[1])      # > 0: the road runs into the joint along n
                    runs[k_]["cuts"].append(((pj.x, pj.y), n_, -1 if into > 0 else 1, "end" if e_ == 1 else "start"))
        elif abs((ka[0] - ka[1]) - (kb[0] - kb[1])) < 0.05:
            keep = 1                            # the same width: both kerbs continue
        else:
            return                              # (a width change with no merge: the lanes slide to their centred position)
        d_ = (ka[0] - kb[0]) if keep > 0 else (ka[1] - kb[1])
        if abs(d_) <= STRAIGHT_M:
            b["shift"] = d_
    # (the fixed piece of a section is the one at a bridge landing, so the bridge's lanes and the ground's meet: the shifts run away
    # from it to both ends; Kaveh 2026-10-15. Else the first piece)
    for sid, rs in by_sid2.items():
        i0 = next((i for i, r in enumerate(rs) if any(o in landing_ways for o in r["oids"])), 0)
        for i in range(i0 + 1, len(rs)):
            a, b = rs[i - 1], rs[i]
            align(a, b, "start" if not b["flip"] else "end")
        for i in range(i0 - 1, -1, -1):
            a, b = rs[i + 1], rs[i]
            align(a, b, "end" if not b["flip"] else "start")
    for r in runs:
        if abs(r["shift"]) > 1e-6:
            r["xline"] = shift_line(r["xline"], r["shift"])
    # ---- 6d. a one-sided merge (docs/design/joints.md, rule 4): a road that ends on a road running through the node (a Y) keeps its
    # heading over its last TAPER_M: the last bend of its OSM line towards the node is the drawing of the merge, not a movement of the
    # road; its far kerb runs straight to the trunk and the lane blends into the trunk's roadway (the slip lane into the Granville
    # ramp bent 3 m east and the sidewalk bulged with it; Kaveh 2026-10-16)
    rtree = shapely.STRtree([r["line"] for r in runs]) if runs else None
    for i, (k, e, pt) in enumerate(ends_):
        r = runs[k]
        if jtree is not None and any(jn[j].distance(pt) < 0.6 for j in jtree.query(pt.buffer(0.6))):
            continue
        here = [j for j in etree2.query(pt.buffer(0.3)) if ends_[j][2].distance(pt) <= 0.3]
        sids = [runs[ends_[j][0]]["sid"] for j in here]
        if sids.count(r["sid"]) > 1:
            continue                                        # (a joint of its own section: chained on)
        through = any(sids.count(sd) > 1 for sd in set(sids) if sd != r["sid"]) or any(
            k2 != k and runs[k2]["line"].distance(pt) < 0.6 and 0.5 < runs[k2]["line"].project(pt) < runs[k2]["line"].length - 0.5
            for k2 in (rtree.query(pt.buffer(0.6)) if rtree is not None else []))
        if not through:
            continue
        xl = r["xline"]
        if xl.length < TAPER_M + 2.0:
            continue
        s_end = xl.length if e == 1 else 0.0
        s_from = s_end - TAPER_M if e == 1 else TAPER_M
        a_, b_ = xl.interpolate(s_from), xl.interpolate(s_from + (-1.0 if e == 1 else 1.0))
        hd = unit_v((a_.x - b_.x, a_.y - b_.y))         # the heading at s_from, towards the end
        keep = substring(xl, 0.0, s_from) if e == 1 else substring(xl, s_from, xl.length)
        tip = (a_.x + hd[0] * TAPER_M, a_.y + hd[1] * TAPER_M)
        r["xline"] = shapely.LineString(list(keep.coords) + [tip]) if e == 1 else shapely.LineString([tip] + list(keep.coords))
    for r in runs:
        r["cw"] = poly(at_joints(r, band(r["xline"], r["kr"], r["kl"])))

    # ---- 5. junctions
    crossings = [g(w) for (w,) in rows(f"""SELECT {m()} FROM space.element WHERE type IN ('walkway', 'cycleway') AND level_min = 0
                                            AND subtype = 'crossing'""")]
    rtree = shapely.STRtree([r["line"] for r in runs]) if runs else None
    jshapes = []
    arm_cuts = []       # (point, heading) where each arm's roadway is cut at its stop line: the sidewalk is cut on the same line
    for n in jn:
        # the arms: the runs that end at the node (a run that only passes near it shares no node with it: not an arm)
        arms = [runs[k] for k in (rtree.query(n.buffer(1.0)) if rtree is not None else [])
                if min(runs[k]["line"].project(n), runs[k]["line"].length - runs[k]["line"].project(n)) < 1.0]
        out = []
        for i, r in enumerate(arms):
            ln = r["line"]
            s0 = ln.project(n)
            away = 1 if s0 < ln.length / 2 else -1          # the arm runs from the node this way along its line
            st = lambda p: (ln.project(p) - s0) * away      # a point's station along the arm, from the node
            others = shapely.union_all([a["cw"] for j, a in enumerate(arms) if j != i]) if len(arms) > 1 else shapely.Polygon()
            # the core: how far the other arms' carriageways overlap this one, from the node on without a break (an arm that comes
            # back beside another arm 100 m on overlaps it there too: that is no part of this junction, Monaco i0-25194413)
            core, pieces = 0.0, []
            # (only where the overlap is at least CORE_MIN_M wide: two arms running side by side (a ramp beside the road it joins)
            # overlap by a sliver along their length, which is no junction; Fir Street at the Granville ramp, Kaveh 2026-10-15)
            for q in shapely.get_parts(poly(r["cw"].intersection(others)).buffer(-CORE_MIN_M / 2).buffer(CORE_MIN_M / 2)):
                if q.geom_type == "Polygon" and not q.is_empty:
                    ss = [st(shapely.Point(c)) for c in q.exterior.coords]
                    pieces.append((min(ss), max(ss)))
            for lo, hi in sorted(pieces):
                if lo <= core + 0.5:
                    core = max(core, hi)
            reach = core + JUNC_ARM_M
            for x in crossings:
                hit = x.intersection(r["cw"])
                if hit.is_empty:
                    continue
                ss = [st(shapely.Point(c)) for q in shapely.get_parts(hit) if q.geom_type == "LineString" for c in q.coords]
                if ss and core - CROSS_HALF_M <= min(ss) <= core + CROSS_NEAR_M:
                    reach = max(reach, max(ss) + CROSS_HALF_M)
            reach = min(reach, ln.length)
            # (the arm's carriageway from the node to its stop line, cut square across the arm there: a circle round the node gave every
            # junction the wide road's radius, so a side street's lanes stopped half a road short of the kerb line, Kaveh 2026-10-15)
            a_, b_ = (s0, s0 + reach) if away > 0 else (s0 - reach, s0)
            out.append(band(substring(ln, a_, b_), r["kr"], r["kl"]))
            pc = ln.interpolate(b_ if away > 0 else a_)
            qa, qb = ln.interpolate(max((b_ if away > 0 else a_) - 1, 0)), ln.interpolate(min((b_ if away > 0 else a_) + 1, ln.length))
            arm_cuts.append(((pc.x, pc.y), unit_v((qb.x - qa.x, qb.y - qa.y))))
        if out:
            # the corners between the arms rounded by KERB_RADIUS_M: what the closing adds beyond a corner's fillet (a strip between two
            # arms that run side by side, i0-430951364's loop) is no corner and stays out (J2)
            U_ = shapely.union_all(out)
            C_ = U_.buffer(KERB_RADIUS_M, join_style="round").buffer(-KERB_RADIUS_M, join_style="round")
            fillets = [q for q in shapely.get_parts(poly(C_.difference(U_))) if q.area <= FILLET_MAX_M2]
            jshapes.append((n, poly(shapely.union_all([U_] + fillets))))
    area = shapely.union_all([g(w) for (w,) in rows(f"SELECT {m()} FROM space.area")] or [shapely.Polygon()])
    blocks = shapely.union_all([g(w) for (w,) in rows(f"SELECT {m()} FROM space.block WHERE level = 0")] or [shapely.Polygon()])
    street = poly(area.difference(blocks)) if not area.is_empty else shapely.Polygon()
    clusters = []       # [nodes, shape]
    for n, J in jshapes:
        hit = [c for c in clusters if c[1].intersects(J)]
        for c in hit:
            clusters.remove(c)
        clusters.append([[n] + [x for c in hit for x in c[0]], shapely.union_all([J] + [c[1] for c in hit])])
    junctions = []
    for ns, J in clusters:
        ids = sorted(node_id.get((round(p.x, 1), round(p.y, 1))) or 0 for p in ns)
        nid = next((i for i in ids if i), None)
        jid = f"i0-{nid}" if nid else f"i0-x{round(J.centroid.x)}y{round(J.centroid.y)}"
        junctions.append(dict(id=jid, nodes=[i for i in ids if i], geom=poly(J.intersection(area)) if not area.is_empty else J))
    J_all = shapely.union_all([j["geom"] for j in junctions] or [shapely.Polygon()])

    # ---- 6. sections: each run's carriageway less the junctions
    for r in runs:
        r["road_g"] = poly(r["cw"].difference(J_all))
        if not area.is_empty:
            r["road_g"] = poly(r["road_g"].intersection(area))
    runs = [r for r in runs if not r["road_g"].is_empty and r["road_g"].area > 0.5]
    taken = shapely.Polygon()
    for r in sorted(runs, key=lambda r: (-(r["f"] + r["b"]), STREET.index(r["cl"].replace("_link", "")) if r["cl"].replace("_link", "") in STREET else 99)):
        r["road_g"] = poly(r["road_g"].difference(taken))
        taken = shapely.union_all([taken, r["road_g"]])
    # (a run whose roadway the junctions leave under SLIVER_M2 is a sliver between a junction and a crossing node: it joins the junction)
    small = [r for r in runs if r["road_g"].is_empty or r["road_g"].area < SLIVER_M2]
    for r in small:
        for j in junctions:
            if not r["cw"].is_empty and j["geom"].distance(r["cw"]) < 0.1:
                j["geom"] = poly(shapely.union_all([j["geom"], r["cw"]]))
                break
    if small:
        J_all = shapely.union_all([j["geom"] for j in junctions] or [shapely.Polygon()])
        for r in runs:
            if r not in small:
                r["road_g"] = poly(r["road_g"].difference(J_all))
    runs = [r for r in runs if r not in small and not r["road_g"].is_empty and r["road_g"].area > 0.5]
    for r in runs:      # (a neighbour that went into the junction is no joint partner any more)
        r["trans"] = {w: q for w, q in r.get("trans", {}).items() if q in runs}
    # ---- 6b. tapers: where two subsections of one section meet and the roadway is wider on one side in one of them (a turn pocket,
    # a lane drop, a parking lane that ends), the roadway does not stop at a step: in the narrower subsection its edge runs from the
    # wider kerb to its own over TAPER_M (a kerb stood across the lane there, Kaveh 2026-10-15). The taper is a carriageway part
    # (roadway no lane took), derived from both subsections' OSM counts.
    for r in runs:
        r["tapers"] = []
    by_sid = {}
    for r in runs:
        by_sid.setdefault(r["sid"], []).append(r)
    all_road = shapely.STRtree([r["road_g"] for r in runs])
    for sid, rs in by_sid.items():
        for a, b in zip(rs, rs[1:]):
            for sg in (1, -1):                  # the section's left (+) and right side
                sa = sg if not a["flip"] else -sg
                sb = sg if not b["flip"] else -sg
                # (the kerb's distance from the OSM line on that side, the continuity shift included: /2's three lanes moved 1.6 m
                # looked wider than /1's two, and a taper wedge cut into the island; the Granville ramp, Kaveh 2026-10-16)
                ka = (a["kl"] + a["shift"]) if sa > 0 else -(a["kr"] + a["shift"])
                kb = (b["kl"] + b["shift"]) if sb > 0 else -(b["kr"] + b["shift"])
                if abs(ka - kb) < 0.05:
                    continue
                wide, narrow, sn, kw_, kn_ = (a, b, sb, ka, kb) if ka > kb else (b, a, sa, kb, ka)
                ln = narrow["line"]
                at_start = (narrow is b) != narrow["flip"]          # (the joint at the narrow run's start, else at its end)
                mg = wide.get("merge")          # (the wider side's extra width is a merging road's lane: no taper wedge there)
                pj_ = shapely.Point(ln.coords[0] if at_start else ln.coords[-1])
                if mg and mg[1].distance(pj_) < 1.0 and (sn if not (wide["flip"] != narrow["flip"]) else -sn) == mg[0]:
                    continue
                L = min(TAPER_M, ln.length)
                stations = [k * 1.0 for k in range(int(L) + 1)] + [L]
                pts_in, pts_out = [], []
                for s_ in stations:
                    st_ = s_ if at_start else ln.length - s_
                    p, a_, b_ = ln.interpolate(st_), ln.interpolate(max(st_ - 1, 0)), ln.interpolate(min(st_ + 1, ln.length))
                    h = math.hypot(b_.x - a_.x, b_.y - a_.y) or 1
                    nx, ny = -(b_.y - a_.y) / h, (b_.x - a_.x) / h
                    d_ = kw_ + (kn_ - kw_) * s_ / L
                    pts_in.append((p.x + nx * sn * kn_, p.y + ny * sn * kn_))
                    pts_out.append((p.x + nx * sn * d_, p.y + ny * sn * d_))
                wedge = poly(shapely.make_valid(shapely.Polygon(pts_in + pts_out[::-1])).difference(J_all))
                if not area.is_empty:       # (a joint outside the area, where the roadway is not drawn: no taper there)
                    wedge = poly(wedge.intersection(area))
                others = [runs[k]["road_g"] for k in all_road.query(wedge) if runs[k] is not narrow]
                if others:
                    wedge = poly(wedge.difference(shapely.union_all(others)))
                if wedge.area < 0.5:
                    continue
                narrow["tapers"].append(dict(geom=wedge, ref=f"the roadway narrows from w{wide['oid']}'s kerb to w{narrow['oid']}'s over {L:.0f} m (chosen)"))
                narrow["road_g"] = poly(shapely.union_all([narrow["road_g"], wedge]))
    roadway = shapely.union_all([r["road_g"] for r in runs] + [J_all])

    # ---- barriers continued from a bridge landing: a bridge whose corrections name a median barrier keeps it on the ground along the
    # landing way's chain, on the side where a roadway of the other direction runs within GAP_M, until that roadway ends or a junction
    # begins (the guardrail from the Granville ramp down to Fir Street; Kaveh 2026-10-15: OSM maps none, the bridge's correction is the source)
    from .corrections import bridge as bridge_corr
    cw_tree = shapely.STRtree([r["cw"] for r in runs]) if runs else None
    barriers = []       # (line, ref)
    for pf in bridges:
        prof = json.load(open(pf))
        if bridge_corr(prof.get("name", "")).get("median") != "barrier":
            continue
        for ax in prof.get("axes", []):
            for ld in ax.get("landings", []):
                oid_ = int(str(ld.get("way", "w0"))[1:])
                r0 = next((r for r in runs if oid_ in r["oids"]), None)
                if r0 is None:
                    continue
                for sg in (1, -1):      # the side with the other direction's roadway beside it
                    chain_ = [r0]
                    cur, end_ = r0, None
                    while True:         # (the chain on through the joints)
                        nxt_ = cur.get("trans", {})
                        q_ = next((q for key_, q in nxt_.items()), None)
                        if q_ is None or q_ in chain_:
                            break
                        chain_.append(q_)
                        cur = q_
                    pts_ = []
                    for r_ in chain_:
                        ln_ = r_["xline"]
                        # (the rail stands at the lanes' outer edge, not at the kerb: a parking lane there is outside it)
                        t_ = (r_["W"] / 2 if sg > 0 else -r_["W"] / 2) if not (r_["flip"] != r0["flip"]) else (-r_["W"] / 2 if sg > 0 else r_["W"] / 2)
                        bedge_ = ln_.offset_curve(t_)
                        if bedge_.geom_type != "LineString" or bedge_.is_empty:
                            break
                        probe = bedge_.offset_curve(sg * (GAP_M / 2) if not (r_["flip"] != r0["flip"]) else -sg * (GAP_M / 2))
                        hit = [k_ for k_ in cw_tree.query(probe.buffer(GAP_M / 2)) if runs[k_] is not r_ and runs[k_] not in chain_
                               and runs[k_]["ow"] and runs[k_]["cw"].distance(bedge_) < GAP_M]
                        if not hit:
                            break
                        seg_ = bedge_.intersection(shapely.union_all([runs[k_]["cw"] for k_ in hit]).buffer(GAP_M))
                        seg_ = max(shapely.get_parts(seg_), key=lambda q: q.length, default=None)
                        if seg_ is None or seg_.geom_type != "LineString" or seg_.length < 2:
                            break
                        seg_ = at_joints(r_, seg_)      # (each subsection's piece ends at its joint: no two rails over the joint)
                        seg_ = max((q for q in shapely.get_parts(seg_) if q.geom_type == "LineString"), key=lambda q: q.length, default=None)
                        if seg_ is None or seg_.length < 0.5:
                            continue
                        pts_.append(seg_.difference(J_all) if not J_all.is_empty else seg_)
                    if pts_:
                        barriers.append((shapely.union_all(pts_), f"{prof.get('name')}: median barrier (corrections/bridges.json), continued on the ground from axis {ax['id']}'s landing"))

    # ---- 7. the pedestrian side: the street less the roadway, each piece to the nearest roadway
    realm = poly(street.difference(roadway)) if not street.is_empty else shapely.Polygon()
    edge_ = shapely.union_all([blocks.boundary, area.boundary]) if not area.is_empty else blocks.boundary
    edge_rings = [q for q in shapely.get_parts(edge_) if q.geom_type == "LineString"]
    edge_buf = [q.buffer(0.3) for q in edge_rings]       # (once: buffering the whole area's edge for every piece took hours on Monaco)
    edge_tree = shapely.STRtree(edge_rings) if edge_rings else None

    def along_edge(q):
        """How far q's boundary runs along a block's or the area's edge (within 0.3 m)."""
        if edge_tree is None:
            return 0.0
        return sum(q.boundary.intersection(edge_buf[k]).length for k in edge_tree.query(q.buffer(0.3)))
    # (a strip narrower than GAP_M between two roadways, away from the blocks, is one paved surface with them: our chosen lane widths
    # leave it, no source makes it an island (Fir Street's two one-way ways, Kaveh 2026-10-14); it is an island only where OSM maps a
    # kerb, an object or a path along it)
    gaps = []
    if not realm.is_empty:
        thin = poly(roadway.buffer(GAP_M / 2).buffer(-GAP_M / 2).intersection(realm))     # (the roadway closed over its narrow gaps)
        objs = [g(w) for (w,) in rows(f"""SELECT {m()} FROM space.object WHERE level = 0 AND source = 'osm'
                                          AND class NOT LIKE 'crossing.%' AND class NOT LIKE 'access.%'""")]
        objs += [g(w) for (w,) in rows(f"""SELECT {m()} FROM space.element WHERE type IN ('walkway', 'cycleway') AND level_min = 0
                                           AND coalesce(subtype, '') <> 'crossing'""")]
        o_tree = shapely.STRtree(objs) if objs else None
        objs += [bl for bl, _ in barriers]      # (a barrier along the strip: it is an island, the bridge's guardrail continued, Kaveh 2026-10-16)
        o_tree = shapely.STRtree(objs) if objs else None
        for q in shapely.get_parts(thin):
            # (a strip that touches a block only at a corner (under ISLAND_TOUCH_M) lies between roadways: the gore where a slip lane
            # leaves a junction stood as a sidewalk wedge in the way of the turning lane, Kaveh 2026-10-16)
            if (q.area > 0.5 and along_edge(q) < ISLAND_TOUCH_M
                    and (o_tree is None or not any(objs[i].intersection(q.buffer(0.2)).length > 2.0 or (objs[i].geom_type == "Point" and q.buffer(0.2).contains(objs[i]))
                                                     for i in o_tree.query(q.buffer(0.2))))):
                gaps.append(q)
    owners = [(r["sub"], r["road_g"]) for r in runs] + [(j["id"], j["geom"]) for j in junctions]
    gaps_u = shapely.union_all([q for q in gaps if q.area >= 2.0]) if gaps else shapely.Polygon()     # (shared out below, as the realm)
    # the pedestrian side is cut by the same straight lines as the roadway (each arm's stop-line cut, each joint's bisector), run
    # across the street to the blocks; each piece goes to the space whose roadway it touches most (Voronoi cells of the kerbs' points
    # gave the spaces jagged edges, Kaveh 2026-10-15)
    cutlines = []
    for pc, hd in arm_cuts + [(p_, n_) for r in runs for p_, n_, _, _ in r["cuts"]]:      # (hd: along the road; the cut is square to it)
        t_ = (-hd[1], hd[0])
        cutlines.append(shapely.LineString([(pc[0] - t_[0] * CUT_M, pc[1] - t_[1] * CUT_M), (pc[0] + t_[0] * CUT_M, pc[1] + t_[1] * CUT_M)]))
    share = {}
    if owners and not realm.is_empty:
        # (the realm's boundary and the cut lines noded together and polygonized: the pieces inside the realm. A difference with the
        # buffered lines took an hour on Monaco's 1,500 cuts)
        parts_r = list(shapely.get_parts(realm))
        rtree_r = shapely.STRtree(parts_r)
        if cutlines:
            # (each cut line clipped to the realm's pieces first: whole 120 m lines crossing each other inside the blocks made a
            # quadratic number of faces, and the Monaco build never finished)
            cl2 = []
            for c_ in cutlines:
                for k_ in rtree_r.query(c_):
                    cl2 += [q for q in shapely.get_parts(c_.intersection(parts_r[k_])) if q.geom_type == "LineString" and q.length > 0.01]
            noded = shapely.unary_union([realm.boundary] + cl2)
            pieces_ = []
            for q in shapely.get_parts(shapely.polygonize(shapely.get_parts(noded))):
                rp = q.representative_point()
                if any(parts_r[k_].contains(rp) for k_ in rtree_r.query(rp)):
                    pieces_.append(q)
        else:
            pieces_ = parts_r
        otree = shapely.STRtree([G for _, G in owners])
        for q in pieces_:
            if q.area < 0.01:
                continue
            best, bl = None, 0.0
            for k in otree.query(q.buffer(0.1)):
                l_ = owners[k][1].boundary.intersection(q.buffer(0.05)).length
                if l_ > bl:
                    best, bl = k, l_
            if best is None:
                best = otree.nearest(q)
            share[best] = poly(shapely.union_all([share.get(best, shapely.Polygon()), q]))
        # (a share's piece that does not touch its own roadway goes to the space it touches most: no space in two pieces, U2)
        for _ in range(3):
            moved = []
            for k in list(share):
                keep_ = []
                for q in shapely.get_parts(share[k]):
                    if q.boundary.intersection(owners[k][1].buffer(0.05)).length > 0.5 or q.area < 0.05:     # (along an edge, not a corner)
                        keep_.append(q)
                    else:
                        moved.append(q)
                share[k] = poly(shapely.union_all(keep_ or [shapely.Polygon()]))
            for q in moved:
                best, bl = None, 0.0
                for k, (_, G) in enumerate(owners):
                    U_ = shapely.union_all([G, share.get(k, shapely.Polygon())])
                    if U_.distance(q) < 0.05:
                        l_ = U_.boundary.intersection(q.boundary.buffer(0.05)).length
                        if l_ > bl:
                            best, bl = k, l_
                if best is not None:
                    share[best] = poly(shapely.union_all([share.get(best, shapely.Polygon()), q]))

    gap_ref = f"paved roadway with no lane: a strip between two roadways narrower than {GAP_M} m with no kerb, object, path or barrier mapped on it"

    gap_of = {}     # (each roadway's share of the strips between roadways: its carriageway parts, no pedestrian side there)
    if not gaps_u.is_empty:
        for k in list(share):
            gk = [q for q in shapely.get_parts(poly(share[k].intersection(gaps_u))) if q.area > 0.5]
            if gk:
                gap_of[k] = gk
                share[k] = poly(share[k].difference(shapely.union_all(gk)))     # (exactly the pieces taken: a buffer of gaps_u lost some)

    # ---- 8a. crosswalks: OSM's crossing ways over the roadway (CROSSWALK_M wide, or OSM `width`), and a crossing node on a road with no
    # crossing way at it: a band across that road's carriageway. Their paint from `crossing:markings` (see markings()); the lanes and the
    # junction area give way to them (a crosswalk is its own part).
    xways = [(o, g(w)) for o, w in rows(f"""SELECT osm_id, {m()} FROM space.element WHERE type IN ('walkway', 'cycleway') AND level_min = 0
                                            AND subtype = 'crossing'""")]
    xtags = {o: dict(t or {}) for o, t in rows("SELECT osm_id, tags FROM osm.raw.ways WHERE osm_id IN (SELECT unnest(?::BIGINT[]))",
                                                [[o for o, _ in xways]])} if xways else {}
    xnodes = [(o, dict(t or {}), shapely.Point(x, y)) for o, t, x, y in rows(f"""SELECT osm_id, tags, ST_X(p), ST_Y(p) FROM (SELECT osm_id, tags,
                 ST_Transform(ST_Point(lon, lat), 'EPSG:4326', '{epsg}', always_xy := true) AS p FROM osm.raw.nodes WHERE tags['highway'] = 'crossing')""")]
    xw_tree = shapely.STRtree([x for _, x in xways]) if xways else None
    rtree = shapely.STRtree([r["line"] for r in runs]) if runs else None        # (the runs as step 6 left them)
    roadway_x = shapely.union_all([roadway, gaps_u])      # (the strips between roadways are roadway too)
    xw = []     # [(polygon, markings, ref, axis line, width)]
    for oid, x in xways:
        w = num_f(xtags.get(oid, {}).get("width")) or CROSSWALK_M
        for seg in shapely.get_parts(x.intersection(roadway_x.buffer(0.3))):
            if seg.geom_type == "LineString" and seg.length >= 1.0:
                xw.append((poly(band(seg, -w / 2, w / 2).intersection(roadway_x)), markings(xtags.get(oid, {})), f"w{oid}", seg, w))
    for oid, tg, p in xnodes:
        if xw_tree is not None and any(xways[k][1].distance(p) < 2.0 for k in xw_tree.query(p.buffer(2.0))):
            continue        # (a crossing way maps it)
        bands, seg0 = [], None      # (one crosswalk per node: the node can end two runs, OSM splits a way at a crossing)
        for k in (rtree.query(p.buffer(1.0)) if rtree is not None else []):
            r = runs[k]
            if r["line"].distance(p) > 1.0:
                continue
            s_ = r["line"].project(p)
            seg = substring(r["line"], max(s_ - CROSSWALK_M / 2, 0.0), min(s_ + CROSSWALK_M / 2, r["line"].length))
            if seg.length < 0.5:
                continue
            bands.append(band(seg, r["kr"], r["kl"]))
            seg0 = seg0 if seg0 is not None and seg0.length >= seg.length else seg
        if bands:
            across = poly(shapely.union_all(bands).intersection(roadway_x))
            (x0, y0), (x1, y1) = seg0.coords[0], seg0.coords[-1]
            h_ = math.hypot(x1 - x0, y1 - y0) or 1
            nx, ny = -(y1 - y0) / h_, (x1 - x0) / h_         # (the bars run across the road: the crossing's own direction)
            walk = shapely.LineString([(p.x - nx * 30, p.y - ny * 30), (p.x + nx * 30, p.y + ny * 30)]).intersection(across.buffer(0.1))
            walk = max(shapely.get_parts(walk), key=lambda q: q.length, default=seg0) if not walk.is_empty else seg0
            xw.append((across, markings(tg), f"n{oid}", walk, CROSSWALK_M))
    # two crosswalks on one spot (a marked crossing way and an unmarked kerb link beside it, a node and a way): the marked one keeps its
    # shape, the next gives way to it (no two parts of one space overlap, U9)
    rank = {"zebra": 0, "ladder": 0, "ladder:skewed": 0, "skewed": 0, "lines": 1, "dashes": 1, "dots": 1, "surface": 2, "pictograms": 2, "unknown": 3, "no": 4}
    xw.sort(key=lambda x: (rank.get(x[1], 3), -x[0].area))
    taken_x, xw2 = shapely.Polygon(), []
    for X, mk, ref, seg, w in xw:
        X = poly(X.difference(taken_x)) if not taken_x.is_empty else X
        if X.area < 0.5:
            continue
        taken_x = shapely.union_all([taken_x, X])
        xw2.append((X, mk, ref, seg, w))
    xw = xw2
    XW = taken_x

    # ---- parts and marks
    units, parts, marks, subrows, junction_rows = [], [], [], [], []
    pid = {}

    def add(uid, typ, geom, **kw):
        if typ in ROAD_T and not XW.is_empty:       # (the roadway gives way to the crosswalks)
            geom = geom.difference(XW)
        for q in shapely.get_parts(poly(geom)):     # (a part is one polygon: the 3D view triangulates each ring as one surface)
            if q.is_empty or q.area < 0.05:
                continue
            pid[uid] = pid.get(uid, 0) + 1
            parts.append(dict(unit_id=uid, part_id=f"{uid}#{pid[uid]}", type=typ, geom=q, **kw))

    def mark(uid, typ, geom, src="urbanstyle", method="derived", ref=None):
        for q in shapely.get_parts(geom):
            if q.geom_type == "LineString" and q.length > 0.5:
                marks.append((uid, typ, q, src, method, ref))

    def axis_out(ln):       # (a subsection's axis stops at the junctions' edges)
        x_ = ln.difference(J_all) if not J_all.is_empty else ln
        ps_ = [q for q in shapely.get_parts(x_) if q.geom_type == "LineString"]
        return max(ps_, key=lambda q: q.length) if ps_ else ln

    service_in = [(g(w), num_f(dict(t or {}).get("width")) or ALLEY_W_M) for w, t in rows(f"""SELECT {m()}, tags FROM space.element e
                     LEFT JOIN osm.raw.ways w ON w.osm_id = e.osm_id WHERE e.type IN ('road', 'walkway') AND e.level_min = 0 AND e.class = 'service'""")]

    def ped(uid, G, R):
        """The pedestrian side R of roadway G: furnishing, sidewalk, frontage; a piece that touches no block or the area's edge lies
        between roadways only: an island (a median of a divided road, a traffic island), not a sidewalk."""
        if R.is_empty:
            return
        isl = [q for q in shapely.get_parts(R) if along_edge(q) < ISLAND_TOUCH_M and q.area >= ISLAND_MIN_M2 and not q.buffer(-0.5).is_empty]
        # (a small piece that touches an island is that island's: a sidewalk tip stood inside an island's end; Kaveh 2026-10-16)
        if isl:
            I_ = shapely.union_all(isl)
            isl += [q for q in shapely.get_parts(R) if along_edge(q) < ISLAND_TOUCH_M and q not in isl and q.distance(I_) < 0.05]
        if isl:
            add(uid, "island", shapely.union_all(isl), source="osm", method="derived",
                ref="between roadways only: a median or a traffic island (no block reaches it)")
            R = poly(R.difference(shapely.union_all(isl)))
            if R.is_empty:
                return
        # a service road (an alley, a driveway) that reaches this roadway crosses the pedestrian side to it: a `driveway` part as wide as
        # the service road (OSM width, else ALLEY_W_M), from the kerb to the block's edge (Kaveh 2026-10-16: "alleys must cross all
        # frontage, sidewalk and furnishing till they touch the road")
        dw = shapely.Polygon()
        for ln_, w_ in service_in:
            if ln_.distance(G) < 1.0 and ln_.intersects(R.buffer(0.5)):
                piece = poly(ln_.buffer(w_ / 2, cap_style="flat").intersection(R))
                piece = shapely.union_all([q for q in shapely.get_parts(piece) if q.distance(G) < 0.5] or [shapely.Polygon()])
                dw = shapely.union_all([dw, piece])
        if not dw.is_empty and dw.area > 0.5:
            add(uid, "driveway", dw, source="osm", method="derived", ref="a service road crossing the pedestrian side to the roadway")
            R = poly(R.difference(dw))
            if R.is_empty:
                return
        f_ = poly(R.intersection(G.buffer(FURNISH_M)))
        s_ = poly(R.intersection(G.buffer(FURNISH_M + CLEAR_M)).difference(f_))
        rest = poly(R.difference(G.buffer(FURNISH_M + CLEAR_M)))
        pv = dict(source="urbanstyle", method="chosen", width_source="urbanstyle", width_method="chosen")
        add(uid, "furnishing", f_, width_m=FURNISH_M, ref=f"{FURNISH_M} m from the kerb", **pv)
        add(uid, "sidewalk", s_, width_m=CLEAR_M, ref=f"the clear path, {CLEAR_M} m", **pv)
        add(uid, "frontage", rest, ref="the rest to the block's edge", **pv)

    for k, r in enumerate(runs):
        G, ln, uid = r["road_g"], r["line"], r["sub"]
        R = share.get(k, shapely.Polygon())
        U = poly(shapely.union_all([G, R] + gap_of.get(k, [])))
        units.append((uid, "subsection", r["sid"], U))
        for q in gap_of.get(k, []):
            add(uid, "carriageway", q, source="osm", method="derived", ref=gap_ref)
        tg = tags.get(r["oid"], {})
        common = dict(road=r["name"], road_class=r["cl"], road_lanes=str(r["f"] + r["b"]), oneway=r["ow"])
        lsrc = r["lsrc"]
        ways_ = "+".join(f"w{o}" for o in r["oids"])
        lane_ref = (f"{ways_} corrected: {r['f']} + {r['b']} lanes (corrections/lanes.json; OSM lanes={tg.get('lanes', '')})" if lsrc[0] == "corrections"
                    else f"{ways_} lanes={tg.get('lanes', '')}" if lsrc[0] != "urbanstyle" else f"{ways_} has no lanes tag: one each way (chosen)")
        if r["oid"] in bridge_ways:     # (the bridge model draws its lanes)
            add(uid, "bridge deck", G, width_m=round(r["kl"] - r["kr"], 2), source="osm", method="mapped",
                ref=f"w{r['oid']} bridge=yes: drawn by the bridge model", **common)
            ped(uid, G, R)
            subrows.append((uid, r["sid"], r["cl"], round(r["kl"] - r["kr"], 2), r["ow"], round(ln.length, 1), None, None, "section end", round(r["shift"], 2), axis_out(ln)))
            continue
        xl = r["xline"]
        trans = r.get("trans", {})
        joint_s = {}        # where: the station of the joint on xl, and the transition's length
        for where, q in trans.items():
            p_ = shapely.Point(ln.coords[0] if where == "start" else ln.coords[-1])
            joint_s[where] = (xl.project(p_), min(TAPER_M, ln.length / 2))

        def own(d, n, rr=None):
            rr = rr or r
            i = (rr["f"] - n) if d == "forward" else (rr["f"] + n - 1)
            t0 = -rr["W"] / 2 + i * rr["lw"]
            t1 = t0 + rr["lw"]
            wd_ = rr.get("wide", {1: 0.0, -1: 0.0})
            if i == 0:                      # (the outer lanes widened to the kerb evidence: parking in them)
                t0 -= wd_[-1]
            if i == rr["f"] + rr["b"] - 1:
                t1 += wd_[1]
            return (t0, t1)

        def in_frame(q, d, n, side):
            """The neighbour q's lane (d, n) as offsets in r's frame (q runs the other way: the directions and the sides swap), or
            q's lanes' edge on that side (no such lane: the lane opens from the kerb). Each frame is its own moved line: q's offsets
            carry the difference of the two shifts."""
            mirror = r["flip"] != q["flip"]
            dq = d if not mirror else ("backward" if d == "forward" else "forward")
            dz = (q["shift"] if not mirror else -q["shift"]) - r["shift"]
            if n <= (q["f"] if dq == "forward" else q["b"]):
                t0, t1 = own(dq, n, q)
                t0, t1 = ((-t1, -t0) if mirror else (t0, t1))
                return (t0 + dz, t1 + dz)
            sq = side if not mirror else -side       # (q's kerb on that side, its widened outer lane included)
            e_ = side * (q["W"] / 2 + q["wide"][sq]) + dz
            return (e_, e_)

        def offs(t_own, at):
            """s -> (t0, t1) along xl: t_own away from the joints, sliding from `at[where]` over the transition's length."""
            def f(s_):
                t0, t1 = t_own
                for where, (sj, L) in joint_s.items():
                    if where not in at:
                        continue
                    u = (s_ - sj) / L if where == "start" else (sj - s_) / L
                    if u < 1.0:
                        u = max(u, 0.0)
                        a0, a1 = at[where]
                        return (a0 + (t0 - a0) * u, a1 + (t1 - a1) * u)
                return (t0, t1)
            return f

        def strip(f):
            """The polygon between the offsets f(s) along xl, a station every metre and at every bend."""
            ss = sorted({min(k * 1.0, xl.length) for k in range(int(xl.length) + 2)} | {xl.project(shapely.Point(c)) for c in xl.coords})
            lo, hi = [], []
            for s_ in ss:
                p_, a_, b_ = xl.interpolate(s_), xl.interpolate(max(s_ - 0.5, 0)), xl.interpolate(min(s_ + 0.5, xl.length))
                h = math.hypot(b_.x - a_.x, b_.y - a_.y) or 1
                nx, ny = -(b_.y - a_.y) / h, (b_.x - a_.x) / h
                t0, t1 = f(s_)
                lo.append((p_.x + nx * t0, p_.y + ny * t0))
                hi.append((p_.x + nx * t1, p_.y + ny * t1))
            return poly(shapely.make_valid(shapely.Polygon(lo + hi[::-1])))

        def curve(g):
            ss = sorted({min(k * 1.0, xl.length) for k in range(int(xl.length) + 2)} | {xl.project(shapely.Point(c)) for c in xl.coords})
            pts = []
            for s_ in ss:
                p_, a_, b_ = xl.interpolate(s_), xl.interpolate(max(s_ - 0.5, 0)), xl.interpolate(min(s_ + 0.5, xl.length))
                h = math.hypot(b_.x - a_.x, b_.y - a_.y) or 1
                pts.append((p_.x - (b_.y - a_.y) / h * g(s_), p_.y + (b_.x - a_.x) / h * g(s_)))
            return shapely.LineString(pts)
        lanes_ = []     # (f, i, direction, lane number, source, ref, kw)
        for i in range(r["f"] + r["b"]):        # right to left: forward lanes, then backward
            fwd = i < r["f"]
            d, n = ("forward", r["f"] - i) if fwd else ("backward", i - r["f"] + 1)
            t_own = own(d, n)
            side = 1 if (t_own[0] + t_own[1]) > 0 else -1
            at = {where: in_frame(q, d, n, side) for where, q in trans.items()}
            wd_ = r["wide"][1] if i == r["f"] + r["b"] - 1 else r["wide"][-1] if i == 0 else 0.0
            kw_ = dict(width_m=round(r["lw"] + wd_, 2), width_source=r["wsrc"][0], width_method=r["wsrc"][1],
                       position_source="osm", position_method="mapped", position_ref=f"w{r['oid']}: the lanes' middle on its OSM line")
            if wd_:
                kw_.update(width_source="vancouver", width_method="measured", holds="parking",
                           rule=f"the outer lane to the city's catch basins ({wd_} m beyond the chosen lane): one lane, parking in it")
            lanes_.append((offs(t_own, at), i, d, n, lsrc, lane_ref, kw_))
        # the neighbour's lanes this subsection has not: each narrows to nothing from the joint to this subsection's lanes' edge
        for where, q in trans.items():
            mirror = r["flip"] != q["flip"]
            for dq in ("forward", "backward"):
                d = dq if not mirror else ("backward" if dq == "forward" else "forward")
                for n in range((r["f"] if d == "forward" else r["b"]) + 1, (q["f"] if dq == "forward" else q["b"]) + 1):
                    t0, t1 = own(dq, n, q)
                    tq = (-t1, -t0) if mirror else (t0, t1)
                    side = 1 if (tq[0] + tq[1]) > 0 else -1
                    edge = (side * (r["W"] / 2 + r["wide"][side]), side * (r["W"] / 2 + r["wide"][side]))     # (this run's kerb there)
                    # (a lane on the side a road merges from is that road's lane running on: no taper of it here)
                    mg = q.get("merge")
                    if mg and mg[1].distance(shapely.Point(ln.coords[0] if where == "start" else ln.coords[-1])) < 1.0 \
                            and (side if not mirror else -side) == mg[0]:
                        continue
                    lanes_.append((offs(edge, {where: tq}), None, d, n, q["lsrc"], f"w{q['oid']}'s lane {n} narrows to nothing over {joint_s[where][1]:.0f} m (chosen)",
                                   dict(width_m=round(q["lw"], 2), width_source="urbanstyle", width_method="chosen", position_source="osm",
                                        position_method="derived", position_ref="a lane taper at the joint")))
        lane_geoms = []
        for f, i, d, n, src_, ref_, kw in lanes_:
            g_ = strip(f).intersection(G)
            if i is None:       # (a taper at a joint: never over another road's band, the merging road's lane lies there)
                others_ = [runs[k_]["cw"] for k_ in cw_tree.query(g_) if runs[k_] is not r and runs[k_]["cw"].intersects(g_)]
                if others_:
                    g_ = poly(g_.difference(shapely.union_all(others_)))
            lane_geoms.append(g_)
            add(uid, "lane", g_, direction=d, lane=n, source=src_[0], method=src_[1] if i is not None else "derived", ref=ref_, **kw, **common)
            # (no source maps a painted line: a line between lanes carries the lane count's source. Lane lines only between lanes OSM
            # counts; the centre line between the two directions also where the count is chosen, as urbanstyle's own, Kaveh 2026-10-15)
            if i is not None and i > 0 and tg.get("lane_markings") != "no" and (lsrc[0] != "urbanstyle" or i == r["f"]):
                mark(uid, "centre line" if i == r["f"] else "lane line", curve(lambda s_, f=f: f(s_)[0]).intersection(G.buffer(0.01)), lsrc[0],
                     "derived" if lsrc[0] != "urbanstyle" else "chosen", f"{lane_ref}: a line between the lanes")
        for sg in (1, -1):          # (a dashed line at the chosen lane's width inside a widened outer lane: the parking's edge)
            if r["wide"][sg]:
                t_ = sg * r["W"] / 2
                mark(uid, "parking line", xl.offset_curve(t_).intersection(G.buffer(0.01)) if abs(t_) > 1e-6 else shapely.LineString(),
                     "vancouver", "derived", "the chosen lane's edge inside the lane widened to the kerb evidence")
        edge_fn = {1: lambda s_: max(f(s_)[1] for f, *_ in lanes_), -1: lambda s_: min(f(s_)[0] for f, *_ in lanes_)}
        for sg in (1, -1):          # parking and bike lanes, only from OSM's tags, outside the lanes' edge
            acc = [edge_fn[sg]]
            for typ, w, pv in sorted(r["ex"][sg], key=lambda e: e[0] != "cycle lane"):
                g0 = acc[-1]
                g1 = (lambda s_, g0=g0, w=w: g0(s_) + sg * w)
                f_ = (lambda s_, g0=g0, g1=g1: (min(g0(s_), g1(s_)), max(g0(s_), g1(s_))))
                g_ = strip(f_).intersection(G)
                lane_geoms.append(g_)
                add(uid, typ, g_, width_m=w, width_source="urbanstyle", width_method="chosen", source=pv[0], method=pv[1], ref=pv[2], **common)
                acc.append(g1)
        taken_ = shapely.union_all(lane_geoms) if lane_geoms else shapely.Polygon()
        for tp in r.get("tapers", []):
            add(uid, "carriageway", tp["geom"].difference(taken_), source="osm", method="derived", ref=tp["ref"], position_source="osm",
                position_method="derived", position_ref="a taper between the two subsections' kerbs", **common)
        for at_end in (True, False):    # a stop line across the lanes that enter a junction, STOP_BACK_M before it
            q_ = shapely.Point(ln.coords[-1] if at_end else ln.coords[0])
            if J_all.is_empty or J_all.distance(q_) > 0.5:
                continue
            # (only the junction at this end: the junction at the other end moved the stop line back ~10 m, Kaveh 2026-10-15)
            jp_ = shapely.union_all([q for q in shapely.get_parts(J_all) if q.distance(q_) <= 0.5])
            pc_ = [p for p in shapely.get_parts(ln.intersection(jp_)) if p.geom_type == "LineString" and p.distance(q_) < 0.5]
            inside = sum(p.length for p in pc_)
            s_j = (ln.length - inside) if at_end else inside       # (where the line leaves the junction)
            s_ = max(min(s_j - STOP_BACK_M if at_end else s_j + STOP_BACK_M, ln.length), 0.0)
            lo_, hi_ = (-r["W"] / 2, -r["W"] / 2 + r["f"] * r["lw"]) if at_end else (-r["W"] / 2 + r["f"] * r["lw"], r["W"] / 2)
            if hi_ - lo_ < 0.5:
                continue
            p_ = ln.interpolate(s_)
            a_, b_ = ln.interpolate(max(s_ - 1, 0)), ln.interpolate(min(s_ + 1, ln.length))
            h_ = math.hypot(b_.x - a_.x, b_.y - a_.y) or 1
            nx, ny = -(b_.y - a_.y) / h_, (b_.x - a_.x) / h_
            mark(uid, "stop line", shapely.LineString([(p_.x + nx * lo_, p_.y + ny * lo_), (p_.x + nx * hi_, p_.y + ny * hi_)]).intersection(G.buffer(0.01)),
                 "urbanstyle", "derived", "where the lanes enter the junction")
        ped(uid, G, R)
        subrows.append((uid, r["sid"], r["cl"], round(r["kl"] - r["kr"], 2), r["ow"], round(ln.length, 1), None, None, "section end", round(r["shift"], 2), axis_out(ln)))
    for j in junctions:
        k = len(runs) + junctions.index(j)
        R = share.get(k, shapely.Polygon())
        units.append((j["id"], "intersection", None, poly(shapely.union_all([j["geom"], R] + gap_of.get(k, [])))))
        for q in gap_of.get(k, []):
            add(j["id"], "carriageway", q, source="osm", method="derived", ref=gap_ref)
        add(j["id"], "junction area", j["geom"], source="osm", method="derived",
            ref="the junction of " + ", ".join(f"n{i}" for i in j["nodes"]) if j["nodes"] else "the arms' carriageways where they meet")
        ped(j["id"], j["geom"], R)
        junction_rows += [(j["id"], i, 0, j["id"]) for i in j["nodes"]]

    uu_ = [(u[0], u[3]) for u in units]
    ut_ = shapely.STRtree([x for _, x in uu_]) if uu_ else None
    for bl, ref_ in barriers:
        for q in shapely.get_parts(bl):
            if q.geom_type != "LineString" or q.length < 0.5:
                continue
            k_ = next((k for k in (ut_.query(q.centroid) if ut_ is not None else []) if uu_[k][1].distance(q.centroid) < 0.5), None)
            mark(uu_[k_][0] if k_ is not None else "s0-barrier", "barrier", q, "urbanstyle corrections", "continued", ref_)
    # 8b. the crosswalk parts, each piece to the space it lies in, and their paint: zebra bars ZEBRA_BAR_M wide every ZEBRA_BAR_M +
    # ZEBRA_GAP_M along the crossing (square to the walking direction), or two lines along its edges; none where OSM says unmarked or
    # gives no markings
    for X, mk, ref, seg, w in xw:
        for k, (uid, G) in enumerate(owners):
            piece = poly(X.intersection(shapely.union_all([G] + gap_of.get(k, []))))
            if piece.is_empty or piece.area < 0.5:
                continue
            add(uid, "crosswalk", piece, width_m=w, width_source="osm" if w != CROSSWALK_M else "urbanstyle",
                width_method="mapped" if w != CROSSWALK_M else "chosen", source="osm", method="mapped",
                ref=f"{ref} crossing:markings={mk}" if mk != "unknown" else f"{ref}: a crossing, its paint not mapped")
            if mk in ("zebra", "ladder", "ladder:skewed", "skewed"):
                (x0, y0), (x1, y1) = seg.coords[0], seg.coords[-1]
                h_ = math.hypot(x1 - x0, y1 - y0) or 1
                ux, uy = (x1 - x0) / h_, (y1 - y0) / h_
                d = ZEBRA_BAR_M / 2
                while d < seg.length:
                    c_ = seg.interpolate(d)
                    bar = shapely.LineString([(c_.x - uy * w / 2, c_.y + ux * w / 2), (c_.x + uy * w / 2, c_.y - ux * w / 2)])
                    mark(uid, "zebra", bar.intersection(piece.buffer(0.01)), "osm", "mapped", f"{ref} crossing:markings={mk}")
                    d += ZEBRA_BAR_M + ZEBRA_GAP_M
            if mk in ("lines", "dashes", "ladder", "ladder:skewed", "skewed", "dots"):
                for side_ in (w / 2 - 0.1, -w / 2 + 0.1):
                    mark(uid, "crossing line", seg.offset_curve(side_).intersection(piece.buffer(0.01)), "osm", "mapped", f"{ref} crossing:markings={mk}")

    # ---- write (the level-0 rows of division.py's tables, each table with division's columns and types)
    for t, cols in SCHEMA.items():
        have = {c for (c,) in rows(f"SELECT column_name FROM information_schema.columns WHERE table_schema = 'space' AND table_name = '{t}'")}
        q_ = lambda c: f'"{c}"'
        if have:
            con.execute(f"CREATE OR REPLACE TABLE space.{t} AS SELECT " + ", ".join(
                (f"CAST({q_(c)} AS {ty}) AS {q_(c)}" if c in have else f"CAST(NULL AS {ty}) AS {q_(c)}") for c, ty in cols.items()) + f" FROM space.{t}")
        else:
            con.execute(f"CREATE TABLE space.{t} (" + ", ".join(f"{q_(c)} {ty}" for c, ty in cols.items()) + ")")
    for t in ("part", "mark", "width", "turn", "approach"):
        try:
            con.execute(f"DELETE FROM space.{t} WHERE level = 0")
        except duckdb.Error:
            pass
    for t in ("cut", "junction", "subsection"):
        try:
            con.execute(f"DELETE FROM space.{t} WHERE level = 0")
        except duckdb.Error:
            pass
    con.execute("DELETE FROM space.unit WHERE level = 0")
    # a level-1 way this step puts on the ground (nothing passes under it) has no space at level 1 too (spaces.py made one: West
    # Broadway's deck drawn in the air over its own street, s0-w473723218/1; Kaveh 2026-10-15)
    eids = [str(e) for (e,) in rows("SELECT DISTINCT edge_id FROM osm.driving.edges WHERE osm_id IN (SELECT unnest(?::BIGINT[]))",
                                    [sorted(l1_ground)])] if l1_ground else []
    if eids:
        for t in ("part", "mark", "width", "turn", "approach", "unit"):
            try:
                con.execute(f"DELETE FROM space.{t} WHERE level >= 1 AND regexp_extract(unit_id, '^s1-(-?[0-9]+)/', 1) IN (SELECT unnest(?::VARCHAR[]))", [eids])
            except duckdb.Error:
                pass
        try:
            con.execute("DELETE FROM space.subsection WHERE level >= 1 AND regexp_extract(subsection_id, '^s1-(-?[0-9]+)/', 1) IN (SELECT unnest(?::VARCHAR[]))", [eids])
        except duckdb.Error:
            pass
    from .parts import LINE
    clean = lambda x: poly(shapely.make_valid(shapely.set_precision(x, 0.01)))      # (on a 1 cm grid, valid: as division.py's)
    units = [(u, k, s_, clean(x)) for u, k, s_, x in units]
    units = [u for u in units if not u[3].is_empty and u[3].area > 0.5]
    for p_ in parts:
        p_["geom"] = clean(p_["geom"])
    parts = [p_ for p_ in parts if not p_["geom"].is_empty and p_["geom"].area > 0.05]
    # each space in one piece: its largest; every other piece (split off by the snapping, or a corner crumb) goes to the space it shares the
    # longest edge with, its parts too; a crumb under 5 m2 that touches no other space is dropped (U2)
    U_ = {u: [k, s_, x] for u, k, s_, x in units}
    ut_ = shapely.STRtree([U_[u][2] for u in U_]); ul_ = list(U_)
    by_u = {}
    for p_ in parts:
        by_u.setdefault(p_["unit_id"], []).append(p_)
    for u in ul_:
        ps_ = sorted(shapely.get_parts(U_[u][2]), key=lambda q: -q.area)
        if len(ps_) < 2:
            continue
        U_[u][2] = ps_[0]
        for q in ps_[1:]:
            best, bl = None, 0.05
            for k in ut_.query(q.buffer(0.1)):
                v = ul_[k]
                if v == u:
                    continue
                l_ = U_[v][2].boundary.intersection(q.boundary.buffer(0.05)).length
                if l_ > bl:
                    best, bl = v, l_
            if best is None and q.area < 5.0:
                for p_ in by_u.get(u, []):
                    p_["geom"] = clean(p_["geom"].difference(q))
                continue
            if best is None:
                U_[u][2] = shapely.union_all([U_[u][2], q])
                continue
            U_[best][2] = clean(shapely.union_all([U_[best][2], q]))
            for p_ in by_u.get(u, []):
                inq = clean(p_["geom"].intersection(q))
                if not inq.is_empty and inq.area > 0.05:
                    p_["geom"] = clean(p_["geom"].difference(q))
                    pid[best] = pid.get(best, 0) + 1
                    np_ = dict(p_, unit_id=best, part_id=f"{best}#{pid[best]}", geom=inq)
                    parts.append(np_)
                    by_u.setdefault(best, []).append(np_)
    # (a crumb that joined a neighbour at a hairline gap left it in two pieces: the gap closed, else a crumb under 5 m2 dropped)
    for u in ul_:
        ps_ = sorted(shapely.get_parts(U_[u][2]), key=lambda q: -q.area)
        if len(ps_) < 2:
            continue
        closed = poly(shapely.union_all(ps_).buffer(0.06).buffer(-0.06))
        if closed.geom_type == "Polygon" and closed.area > 0.999 * sum(q.area for q in ps_):
            U_[u][2] = closed
            continue
        U_[u][2] = ps_[0]
        for q in ps_[1:]:
            if q.area < 5.0:
                for p_ in by_u.get(u, []):
                    p_["geom"] = clean(p_["geom"].difference(q))
            else:
                U_[u][2] = shapely.union_all([U_[u][2], q])
    units = [(u, v[0], v[1], v[2]) for u, v in U_.items()]
    # parts of one space with the same type, source and lane that touch are one part (the pedestrian side and the strips between
    # roadways were shared out in cells: one part per cell drew "bricks", i0-414553083; Kaveh 2026-10-15)
    groups_ = {}
    for p_ in parts:
        groups_.setdefault((p_["unit_id"], p_["type"], p_.get("ref"), p_.get("direction"), p_.get("lane")), []).append(p_)
    parts = []
    for (u, *_), ps_ in groups_.items():
        if len(ps_) == 1 and ps_[0]["geom"].geom_type == "Polygon":
            parts += ps_
            continue
        one = clean(shapely.union_all([p_["geom"] for p_ in ps_]).buffer(0.02).buffer(-0.02))     # (mitre joins lost a whole strip)
        if one.is_empty or one.area < 0.9 * sum(p_["geom"].area for p_ in ps_):
            parts += ps_        # (the closing failed: keep the pieces as they are)
            continue
        for i, q in enumerate(shapely.get_parts(one)):
            if i < len(ps_):
                parts.append(dict(ps_[i], geom=q))
            else:
                pid[u] = pid.get(u, 0) + 1
                parts.append(dict(ps_[0], part_id=f"{u}#{pid[u]}", geom=q))
    parts = [p_ for p_ in parts if not p_["geom"].is_empty and p_["geom"].area > 0.05]
    # ---- the kerbs: one line for the whole level, the boundary between the roadway (lanes, paved strips, junction areas, crosswalks)
    # and the pedestrian side (sidewalks, furnishing, frontage, islands), then cut by the spaces. (A kerb per space, from its own
    # parts, broke at every joint and wherever the sidewalk beside a lane belongs to the next space: 242 loose ends; Kaveh 2026-10-16)
    # (the roadway's whole outer edge: against the pedestrian side, and against a yard or a plot where the block reaches the lanes
    # with no sidewalk between; not along the area's edge, where the roadway is only cut; and not where a service road (an alley, a
    # driveway) joins the roadway: the kerb is dropped there over the alley's width, Kaveh 2026-10-16 "kerb-134 is in front of an alley")
    rw_all = shapely.union_all([p_["geom"] for p_ in parts if p_["type"] in ROAD_T + ("crosswalk", "cycle crossing")] or [shapely.Polygon()])
    kerb_all = rw_all.buffer(0.02).buffer(-0.02).boundary if not rw_all.is_empty else shapely.LineString()     # (hairline gaps closed)
    if not area.is_empty and not kerb_all.is_empty:
        kerb_all = kerb_all.difference(area.boundary.buffer(0.5))
    service = [g(w) for (w,) in rows(f"""SELECT {m()} FROM space.element WHERE type IN ('road', 'walkway') AND level_min = 0
                                       AND class = 'service'""")]
    if service and not kerb_all.is_empty:
        mouths = [q_.centroid for ln_ in service for q_ in shapely.get_parts(ln_.intersection(kerb_all.buffer(0.3))) if not q_.is_empty]
        if mouths:
            kerb_all = kerb_all.difference(shapely.union_all([pt_.buffer(ALLEY_HALF_M) for pt_ in mouths]))
    kerb_all = shapely.line_merge(kerb_all).simplify(0.03) if not kerb_all.is_empty else kerb_all     # (no arc crumbs: 4 vertices a metre read as a sawtooth in 3D)
    marks = [m_ for m_ in marks if m_[1] != "kerb"]
    for u, k, s_, x in units:
        if x.is_empty:
            continue
        for q in shapely.get_parts(kerb_all.intersection(x.buffer(0.05))):
            if q.geom_type == "LineString" and q.length > 0.3:
                marks.append((u, "kerb", q, "urbanstyle", "derived", "the roadway's outer edge"))
    urows = [(u, k, s, COLORS[k], shapely.to_wkb(x)) for u, k, s, x in units if not x.is_empty]
    if urows:       # (a map with no street at level 0: nothing to write)
        con.executemany(f"INSERT INTO space.unit (unit_id, kind, section_id, level, color, geometry) VALUES (?, ?, ?, 0, ?, {to_ll})", urows)
    if junction_rows:
        con.executemany("INSERT INTO space.junction (intersection_id, node_id, level, cluster_id) VALUES (?, ?, ?, ?)", junction_rows)
    if subrows:
        con.executemany(f"""INSERT INTO space.subsection (subsection_id, section_id, level, class, width_m, oneway, length_m, "left", "right",
                            starts_at, left_extra, color, geometry) VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, '#e6194b', {to_ll})""",
                        [(a, b, c, d, e, f, h, i, j, sh, shapely.to_wkb(x)) for a, b, c, d, e, f, h, i, j, sh, x in subrows])
    if parts:
        con.executemany(f"""INSERT INTO space.part (unit_id, part_id, level, type, arm, direction, lane, lane_id, width_m, width_source, width_method,
                            length_m, source, method, ref, position_source, position_method, position_ref, road, road_class, road_lanes, oneway, rule,
                            holds, geometry) VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {to_ll})""",
                        [(p["unit_id"], p["part_id"], p["type"], p.get("arm"), p.get("direction"), p.get("lane"), p.get("lane_id"), p.get("width_m"),
                          p.get("width_source") or "urbanstyle", p.get("width_method"), round(p["geom"].length / 2, 1), p.get("source") or "urbanstyle",
                          p.get("method") or "derived", p.get("ref"), p.get("position_source"), p.get("position_method"), p.get("position_ref"),
                          p.get("road"), p.get("road_class"), p.get("road_lanes"), p.get("oneway"), p.get("rule"), p.get("holds"), shapely.to_wkb(p["geom"])) for p in parts])
    if marks:
        con.executemany(f"""INSERT INTO space.mark (unit_id, level, type, length_m, width_m, width_source, width_method, source, method, ref, geometry)
                            VALUES (?, 0, ?, ?, ?, 'urbanstyle', 'chosen', ?, ?, ?, {to_ll})""",
                        [(u, t, round(x.length, 1), LINE.get(t), s_, me, rf, shapely.to_wkb(x)) for u, t, x, s_, me, rf in marks])
    return dict(sections=len(runs), intersections=len(junctions), parts=len(parts), marks=len(marks))
