"""Steps 2-7 of docs/design/pipeline.md: the street at level 0 from the road network, data first. It writes the same level-0 rows as
division.py (work.unit, part, mark, subsection, junction) and replaces it when URBANSTYLE_DIVISION=network.

    roads        OSM's street roads at level 0 (not paths, not pedestrian streets, not the ways of a bridge that has a profile)
    lanes        each road's lanes from OSM (`lanes`, per direction from duckOSM's driving network; a two-way road one lane each way at
                 least), centred on its own OSM line, LANE_M each or OSM `width` shared; parking and bike lanes beside them only where
                 OSM tags them; the kerb is its outer edge (a result, never guessed)
    junctions    at each node where 3 or more road ends meet (a road through it counts 2) and a road ends, two roads merge or fork, or two
                 streams cross (docs/design/sections.md, rules 1-4): the arms' carriageways where they overlap, out to each arm's stop line
                 (the far edge of OSM's crosswalk within CROSS_NEAR_M, else JUNC_ARM_M past the overlap), each arm cut square across its
                 line there, with the connectors (a road between two junction nodes under CONNECTOR_M, or a `_link`); corners rounded by
                 KERB_RADIUS_M; junctions that overlap or share a connector are one (id i0-<smallest node>)
    sections     each road from junction to junction (id s0-w<way>[.n]), in subsections /k where the paint differs; one frame per
                 section (docs/design/sections.md rules 5-8): the lanes and the strips a source gives at the section's widest place, one
                 width for the whole section, no line moved sideways, no kerb taper; the lanes centred on their own way's line inside
                 it, the rest paved roadway; every tag change along the section classified first (section 3; work.change, check J4)
    pedestrian   the street (the area less the blocks) less the roadway, each piece to the nearest roadway (section or junction):
                 furnishing FURNISH_M, sidewalk CLEAR_M, the rest frontage (chosen widths)
    crosswalks   OSM's crossing ways over the roadway, and crossing nodes with no way, as parts cut from the lanes; their paint from
                 `crossing:markings` (zebra bars, crossing lines, or none)
    marks        kerbs (the roadway's edge facing the pedestrian side), lane and centre lines only between lanes OSM maps, stop lines
"""
import json
import os
import math

STREET = ("motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street")
LANE_M = 3.25           # a lane where OSM gives no width (chosen)
LANE_MIN_M = 2.75       # the least a chosen lane narrows to where the street's edges leave less room (chosen)
ROOM_STEP_M, ROOM_REACH_M = 2.5, 60.0   # the room to the street's edge is measured this often along a run, out to this far
LANE_RANGE = (2.5, 4.5)  # a lane from OSM's width shared by its lanes, kept in this range
PARK_M, BIKE_M = 2.4, 1.75  # a parking lane, a bike lane (chosen)
FURNISH_M, CLEAR_M = 1.0, 1.8   # the pedestrian side where OSM maps no sidewalk line: the furnishing zone at the kerb, the clear path (chosen)
SW_HALF_M = 1.0                 # half a sidewalk's width where OSM maps its line but no width (chosen): the strip is the sidewalk part, its near
                                # side the kerb, its far side the block's edge (Kaveh, 2026-10-16: the sidewalk line is the kerb data)
KERB_RADIUS_M = 4.0
DUAL_M = 30.0           # the two one-way carriageways of one street are one section when their lines stay within this of each other
                        # (docs/design/dual-carriageways.md, 2026-10-16)
PARK_EXTRA_M = 3.0      # an outer lane widens to the city's kerb evidence by at most this (a parking strip and the gutter; chosen)
ALLEY_W_M = 5.0         # a service road's width where OSM gives none (chosen): its driveway across the sidewalk
ALLEY_HALF_M = 2.5      # the kerb is dropped this far either side of where a service road (an alley, a driveway) joins the roadway (chosen)
SLIVER_M2 = 20.0        # a subsection whose roadway outside the junctions is smaller than this joins the junction it touches (chosen)
CUT_M = 60.0            # a roadway cut (stop line, joint) runs this far to each side across the sidewalks to the blocks
MERGE_DEG = 45.0        # a road continues into another at a node when their headings are within this angle (chosen)
XWALK_MAX_M = 40.0      # a crossing piece over the roadway longer than this runs along the road, not across it (spaces.XWALK_MAX_M)
CONNECTOR_M = 40.0      # a road between two junction nodes shorter than this (or any `_link` there) is a connector: it belongs to the
                        # intersection with both nodes (docs/design/sections.md, rule 3; chosen)
CORE_MIN_M = 1.0        # a junction's core counts only where the arms' carriageways overlap at least this wide (chosen)
JGAP_M = 2.0            # an island begins where the strip between two frames is this wide; a thinner tail with nothing on it is paved (chosen)
FILLET_MAX_M2 = 40.0    # a corner fillet of KERB_RADIUS_M is at most this big (a 30 degree corner: 2.4 R2); a bigger closing is a gap, no corner
JUNC_ARM_M, CROSS_NEAR_M, CROSS_HALF_M = 3.0, 15.0, 1.5
STOP_BACK_M = 1.0       # a stop line stands this far before the junction (chosen, as division.py)
CROSSWALK_M, ZEBRA_BAR_M, ZEBRA_GAP_M = 3.0, 0.5, 0.5     # a crosswalk where OSM gives no width; its bars (as parts.py)          # the roadway's edge sampled this often to share the pedestrian side out
COLORS = {"subsection": "#94a3b8", "intersection": "#fbbf24"}
YES_PARK = ("parallel", "diagonal", "perpendicular", "lane", "street_side", "on_street", "half_on_kerb", "on_kerb", "marked", "yes")
YES_BIKE = ("lane", "track", "buffered_lane", "opposite_lane", "opposite_track")
ARM_M = 3.0             # a junction reaches this far into each arm (bridge_lidar reads it)
GAP_M = 8.0             # a strip between two roadways narrower than this (a block is at least this wide) is roadway, unless OSM maps a kerb, an object or a path on it
TAPER_M = 15.0          # a lane that the next subsection of the road does not have narrows to nothing over this length; the lanes slide to
                        # their own position over it at a joint; the kerb taper of a 'real' change (sections.md section 3) (chosen)
POCKET_M = 80.0         # a lane `turn:lanes` names as a turn lane this near a junction is a turn pocket (sections.md section 3; chosen)
TURNS = ("left", "right", "slight_left", "slight_right", "sharp_left", "sharp_right", "reverse")     # `turn:lanes` values that name a turn
STRAIGHT_M = 2.0        # a road between two junctions whose OSM line stays this near the straight line between its ends is drawn straight
                        # (chosen: OSM's drawing error; Fir Street, Kaveh 2026-10-14)
ISLAND_TOUCH_M = 2.0    # a pedestrian piece whose boundary runs less than this along a block's edge lies between roadways: an island (chosen)
ISLAND_MIN_M2 = 4.0     # a pedestrian piece that touches no block and is smaller than this is no island: it is part of the sidewalk (chosen)
from .parts import ARROW_M  # noqa: E402
from .blocks import ALONG_COS, street_sql  # noqa: E402

GROUND_ROAD_KEEP_M = 3.5  # ... except this far each side of a ground road's line: the road keeps its own ground where a ramp lands beside it
LOW_DECK_M = 4.5        # a deck lower than this: nothing passes under it, so on the ground it is not the street's room (chosen: a truck's height)
DECK_EDGE_M = 0.4       # a deck reaches this far past its outer lanes (the guard's own width; as bridge3d's DECK_MARGIN_M)
LANDING_JOIN_M = 4.0    # on a deck level, the walking side this near a point on the ground is roadway: the landing joint (chosen)
LANDING_Z_M = 2.5       # at a landing, the ground under the deck's lanes is roadway out to where the deck is this high (chosen, as checks.ON_GROUND_M)
SLIVER_ROAD_M2 = 2.0    # a piece of the walking side smaller than this that touches no block is roadway (chosen, as product.MIN_PART_M2)
ROAD_T = ("lane", "paved", "junction area", "parking", "cycle lane", "bridge deck")     # the parts a crosswalk is cut from


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
    offset_curve reverses or empties a line for a negative offset.)"""
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
    # J4: every place along a section where OSM's tags change, with its class (docs/design/sections.md, section 3)
    "change": dict(section_id=V, level=I, subsection_a=V, subsection_b=V, way_a=V, way_b=V, lanes_a=V, lanes_b=V, width_a=D, width_b=D,
                   **{"class": V}, note=V, geometry=G_),
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


def build(con, epsg, bridges=(), level=0):
    import duckdb
    import numpy as np
    import shapely
    import shapely.ops
    import time
    t_step = [time.time()]

    def tick(label):
        """The time of each sub-step of the division, so the slow one is known (Kaveh, 2026-10-16: "which part takes so long?")."""
        now = time.time()
        print(f"  division: {label} {now - t_step[0]:.0f} s", flush=True)
        t_step[0] = now
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

    def low_decks():
        """On the ground, the footprint of every deck lower than LOW_DECK_M (nothing passes under it, as under a building): the ground
        street's room stops at a ramp's edge, so its walking side does not spread under the ramp (a8 and a11 at Avenue de France: one
        furnishing of 1,674 m2 under the ramps, Kaveh 2026-10-17)."""
        import pyproj
        from .bridge_profile import _strip, height
        out_ = []
        for pf in bridges:
            P_ = json.load(open(pf))
            tr_ = (lambda x, y: (x, y)) if not P_.get("crs") or P_["crs"] == epsg else \
                pyproj.Transformer.from_crs(P_["crs"], epsg, always_xy=True).transform
            for a_ in P_.get("axes", []):
                ax_ = shapely.LineString([q[:2] for q in a_["line"]["value"]])
                for sec_ in a_.get("sections", []):
                    bs_ = sec_.get("bands") or []
                    if not bs_:
                        continue
                    lo_ = min(b["t"] - b["width"]["value"] / 2 for b in bs_) - DECK_EDGE_M
                    hi_ = max(b["t"] + b["width"]["value"] / 2 for b in bs_) + DECK_EDGE_M
                    run_ = None
                    ss_ = [sec_["s0"] + k_ for k_ in range(int(sec_["s1"] - sec_["s0"]) + 1)] + [sec_["s1"]]
                    for s_ in ss_ + [None]:
                        low_ = s_ is not None and height(a_["vertical"], s_) < LOW_DECK_M
                        if low_ and run_ is None:
                            run_ = s_
                        elif not low_ and run_ is not None:
                            end_ = s_ if s_ is not None else sec_["s1"]
                            if end_ - run_ > 0.5:
                                out_.append(shapely.ops.transform(tr_, _strip(shapely.ops.substring(ax_, run_, end_), lo_, hi_)))
                            run_ = None
        if not out_:
            return shapely.Polygon()
        # (not over a ground road: where a low ramp meets the ground road it lands on, they share the ground; the block cut the last
        # 13.5 m of Boulevard d'Italie's lanes at the a11 and a8 landings, Kaveh 2026-10-17)
        ground_roads_ = [g(w) for (w,) in rows(f"SELECT {m()} FROM work.element WHERE type = 'road' AND level_min = 0")]
        return shapely.union_all(out_).difference(shapely.union_all([r_.buffer(GROUND_ROAD_KEEP_M, cap_style="flat") for r_ in ground_roads_] or [shapely.Polygon()]))

    def deck_outside(lv):
        """Everything that is not deck at level lv, as the blocks are on the ground: so on a deck the street's edge is the deck's edge.
        The deck: each profile's deck (OSM's man_made=bridge outline, else its sections as wide as their lanes, with its holes), and a
        road of that level with no profile as wide as the road (OSM's width, else two lanes), flat at its ends."""
        import pyproj
        from .bridge_profile import _strip
        lv_ = dict(rows("SELECT osm_id, level_min FROM work.element WHERE type = 'road'"))
        decks = []
        for pf in bridges:
            P_ = json.load(open(pf))
            dk_ = []
            for a_ in P_.get("axes", []):        # (only this level's axes: the other level's strips are not this street's room)
                ls_ = [lv_.get(int(w[1:])) for w in a_.get("ways", []) if lv_.get(int(w[1:])) is not None]
                if not ls_ or max(set(ls_), key=ls_.count) != lv:
                    continue
                ax_ = shapely.LineString([q[:2] for q in a_["line"]["value"]])
                for sec_ in a_.get("sections", []):
                    bs_ = sec_.get("bands") or []
                    if not bs_ or sec_["s1"] - sec_["s0"] < 0.1:
                        continue
                    lo_ = min(b["t"] - b["width"]["value"] / 2 for b in bs_) - DECK_EDGE_M
                    hi_ = max(b["t"] + b["width"]["value"] / 2 for b in bs_) + DECK_EDGE_M
                    dk_.append(_strip(shapely.ops.substring(ax_, sec_["s0"], sec_["s1"]), lo_, hi_))
            lvw_ = dict(rows("SELECT osm_id, level_min FROM work.element WHERE type IN ('walkway', 'cycleway')"))
            for p_ in P_.get("paths", []):          # (and the footways and cycleways on this level of the bridge)
                if lvw_.get(int(str(p_["way"])[1:])) == lv and len(p_.get("line") or []) >= 2:
                    dk_.append(shapely.LineString([q[:2] for q in p_["line"]]).buffer(p_["width"]["value"] / 2 + DECK_EDGE_M, cap_style="flat"))
            if not dk_:
                continue
            dk = shapely.union_all(dk_).buffer(0.5).buffer(-0.5)      # (the strips joined at their nodes)
            if str(P_["deck"]["outline"].get("source") or "").startswith("osm"):       # (an OSM outline: the deck as mapped)
                o_ = P_["deck"]["outline"]
                dk = dk.union(shapely.make_valid(shapely.Polygon(o_["value"], o_.get("holes") or [])))
            if P_.get("crs") and P_["crs"] != epsg:
                dk = shapely.ops.transform(pyproj.Transformer.from_crs(P_["crs"], epsg, always_xy=True).transform, dk)
            decks.append(dk)
        roads_ = [(o, g(w), wd, ln_) for o, w, wd, ln_ in rows(f"""SELECT osm_id, {m()}, width_m, NULL
                                                                 FROM work.element WHERE type = 'road' AND level_min = {lv}""")]
        # (a deck road with no profile: as wide as the road, flat at its ends; 6 m round ends made a half-circle of walking side where
        # the road meets the ground road, Kaveh 2026-10-17)
        decks += [r_.buffer((wd_ or LANE_M * max(nl_ or 2, 1)) / 2 + DECK_EDGE_M, cap_style="flat") for o, r_, wd_, nl_ in roads_
                  if o not in profile_ways]
        roads_ = [(o, r_) for o, r_, _, _ in roads_]
        deck_ = shapely.union_all(decks or [shapely.Polygon()])
        box_ = shapely.union_all([r_ for _, r_ in roads_] + [deck_]).envelope.buffer(200.0)
        return box_.difference(deck_)

    LV = level       # (the level this run makes: 0 the ground, 1 and up the decks; docs/notes/bridges-street-model.md)
    tick(f"the road network (rank 0), level {LV}")
    # ---- 2. the road network
    profile_ways = {int(w[1:]) for pf in bridges for a in json.load(open(pf)).get("axes", []) for w in a.get("ways", [])}
    bridge_ways = set()     # (a bridge's ways are the street of their own level, made by these rules, lifted by deck3d.py)
    cand = [(oid, nm, cl, bool(ow), s_, d_, g(w), lv) for oid, nm, cl, ow, s_, d_, w, lv in rows(f"""SELECT osm_id, name, class, coalesce(oneway, false),
                 src, dst, {m()}, level_min FROM work.element e WHERE type IN ('road', 'walkway') AND level_min IN (0, 1, {LV})
                 AND {street_sql('e')}""")]
    # (a level-1 deck is the street at ground level where nothing at level 0 passes under it, as for the blocks; the ways of a bridge that
    # has a profile are the bridge model's: one 'bridge deck' part on their band, no lanes)
    ground_lines = [c[6] for c in cand if c[7] == 0] + [g(w) for (w,) in rows(f"SELECT {m()} FROM work.element WHERE type = 'rail' AND level_min = 0")]
    gl_tree = shapely.STRtree(ground_lines) if ground_lines else None
    on_ground_ = lambda c: c[0] not in profile_ways and (c[7] == 0 or c[7] == 1 and (gl_tree is None or not any(
        ground_lines[k].crosses(c[6]) for k in gl_tree.query(c[6]))))
    keep_ = [c for c in cand if on_ground_(c)] if LV == 0 else [c for c in cand if c[7] == LV and not on_ground_(c)]
    edges = [c[:7] for c in keep_]
    l1_ground = {c[0] for c in keep_ if c[7] == 1} if LV == 0 else set()      # (drawn here on the ground: no copy at level 1, below)
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
    city = _city(con) if LV == 0 else {}      # (a city's meters, bikeways and kerb evidence are on the ground)

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

    tick("the lanes of every way (rank 5's input)")
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
    def heads(p, flow=None):
        """The unit heading of each road end at p, away from p (a road through p: two ends). With `flow` (a list), also each end's
        traffic: 'in' (a one-way road that arrives at p), 'out' (one that leaves p) or None (two-way)."""
        out = []
        for k in tree.query(p.buffer(0.5)):
            ln = edges[k][6]
            if ln.distance(p) > 0.5:
                continue
            s_ = ln.project(p)
            # (over 3 m of the line, or the whole piece where it is shorter: a 2.8 m piece of Avenue Albert II had no heading, and the
            # T where Avenue des Papalins ends on it was no junction; Monaco 2026-10-23)
            for a_, b_ in ((s_, min(s_ + 3.0, ln.length)), (s_, max(s_ - 3.0, 0.0))):
                if not (b_ > s_ and s_ > ln.length - 0.5) and not (b_ < s_ and s_ < 0.5) and abs(b_ - s_) > 0.05:
                    q1, q2 = ln.interpolate(a_), ln.interpolate(b_)
                    out.append(unit_v((q2.x - q1.x, q2.y - q1.y)))
                    if flow is not None:
                        flow.append(("out" if b_ > s_ else "in") if edges[k][3] else None)     # (one-way: along the line)
        return out

    def crosses(p):
        """Whether the roads at p make a junction (docs/design/sections.md, rules 1 and 2): a road that ends at p with no road
        continuing it (a T), two ends that continue into one (a merge or a fork: a Y, a ramp joining a road, a slip lane leaving it,
        whatever the angle; until 2026-10-16 a joint inside a section), or two streams through p that cross each other (their ends
        alternate round p). Two streams that only touch (two one-way lines of one street drawn into one node) make no junction there:
        the roads continue through p as sections."""
        fl = []
        hs = heads(p, fl)
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
        for j_ in set(best.values()):
            src_ = [i for i, j in best.items() if j == j_]
            if len(src_) < 2:
                continue
            # (a two-way road that splits into its two one-way carriageways, one arriving and one leaving: each direction keeps its own
            # carriageway, nothing merges or forks; the Granville Bridge's i1-2625030369 was a junction, Kaveh 2026-10-17)
            if len(src_) == 2 and fl[j_] is None and {fl[src_[0]], fl[src_[1]]} == {"in", "out"}:
                continue
            return True             # (two ends continue into one end: a merge or a fork)
        # (a stream: an end and the end it continues into; two streams can share an end, a Y where two roads merge into one)
        pairs = {(min(i, j), max(i, j)) for i, j in best.items()}
        ang = [math.atan2(h[1], h[0]) for h in hs]
        between = lambda x, a, b: (x - a) % (2 * math.pi) < (b - a) % (2 * math.pi)
        for (i, j) in pairs:
            for (k, l) in pairs:
                if (i, j) < (k, l) and len({i, j, k, l}) == 4 and between(ang[k], ang[i], ang[j]) != between(ang[l], ang[i], ang[j]):
                    return True     # (the streams cross)
        return False
    # (a node that only a bridge's ways reach, and the ramps from it, with no level-0 road at it, is the bridge's node: its junction is
    # the bridge's (level 1), not the ground's. Monaco, Avenue de France over Boulevard d'Italie: two ground intersections for the
    # bridge's nodes lay over the real one, 2026-10-16. A landing keeps its junction: a level-0 road is there)
    l0 = [c[6] for c in cand if c[7] == 0]
    t0 = shapely.STRtree(l0) if l0 else None
    on_bridge = lambda p: any(edges[k][0] in bridge_ways for k in tree.query(p.buffer(0.5)) if edges[k][6].distance(p) <= 0.5)
    on_ground = lambda p: t0 is not None and any(l0[k].distance(p) <= 0.5 for k in t0.query(p.buffer(0.5)))
    jn = []
    for e in edges:
        for q in (e[6].coords[0], e[6].coords[-1]):
            p = shapely.Point(q)
            if all(p.distance(o) > 1.0 for o in jn) and deg(p) >= 3 and crosses(p) and (on_ground(p) or not on_bridge(p)):
                jn.append(p)

    tick("the junction nodes and streams (rank 2)")
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

    tick("the runs (rank 3)")
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
        base = f"s{LV}-w{max(lens, key=lens.get)}"
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
    # two sections that end at one node with no junction (a bend sharper than MERGE_DEG, so no chain): both frames cut on the bisector
    # of their directions there, as at a joint inside a section; two square ends left a notch outside the bend and an overlap inside
    # (W2; Kaveh 2026-10-23)
    at_end = {}
    for r in runs:
        cs_ = list(r["line"].coords)
        for where, p_, q_ in (("start", cs_[0], cs_[1]), ("end", cs_[-1], cs_[-2])):
            if any(c_[3] == where for c_ in r["cuts"]):
                continue                    # (a joint inside its section)
            at_end.setdefault((round(p_[0], 1), round(p_[1], 1)), []).append((r, where, p_, q_))
    for k_, es_ in at_end.items():
        if len(es_) != 2 or es_[0][0]["sid"] == es_[1][0]["sid"]:
            continue
        if jtree is not None and any(jn[j].distance(shapely.Point(k_)) < 0.6 for j in jtree.query(shapely.Point(k_).buffer(0.6))):
            continue
        (ra, wa, pa, qa), (rb, wb, pb, qb) = es_
        da = unit_v((pa[0] - qa[0], pa[1] - qa[1]))           # into the node along a
        db = unit_v((qb[0] - pb[0], qb[1] - pb[1]))           # out of the node along b
        n = unit_v((da[0] + db[0], da[1] + db[1])) if (da[0] + db[0], da[1] + db[1]) != (0.0, 0.0) else da
        ra["cuts"].append((pa, n, -1, wa))
        rb["cuts"].append((pb, n, 1, wb))
    tick("the sections chained (rank 2)")
    # ---- 6a''. connectors (docs/design/sections.md, rule 3): a section between two junction nodes shorter than CONNECTOR_M, or one of
    # `_link` ways only, is no section: it belongs to one intersection with both nodes (West 8th, Fir Street and the ramp foot are one).
    # Not a bridge way: the bridge model draws its deck
    at_jn = lambda p_: jtree is not None and any(jn[j].distance(p_) < 0.6 for j in jtree.query(p_.buffer(0.6)))
    # a roundabout's ring (duckOSM's junction=roundabout or circular): every piece is a connector, however long, so the whole ring
    # with all its nodes is one intersection, of kind roundabout (docs/design/stretches.md, "The intersections")
    try:
        rb_ways = {o for (o,) in con.execute("SELECT DISTINCT osm_id FROM osm.driving.edges WHERE junction IN ('roundabout', 'circular')").fetchall()}
    except duckdb.Error:
        rb_ways = set()
    by_sid0 = {}
    for r in runs:
        by_sid0.setdefault(r["sid"], []).append(r)
    for sid, rs in by_sid0.items():
        p0 = shapely.Point(rs[0]["line"].coords[-1 if rs[0]["flip"] else 0])
        p1 = shapely.Point(rs[-1]["line"].coords[0 if rs[-1]["flip"] else -1])
        L_ = sum(r_["line"].length for r_ in rs)
        if at_jn(p0) and at_jn(p1) and not any(o in bridge_ways for r_ in rs for o in r_["oids"]) \
                and (L_ < CONNECTOR_M or all((r_["cl"] or "").endswith("_link") for r_ in rs)
                     or all(o in rb_ways for r_ in rs for o in r_["oids"])):
            for r_ in rs:
                r_["connector"] = True
                # (a short piece stays a connector only where its two stop lines meet: checked at step 5, once the cores are known)
                r_["conn_by_length"] = not (all((x["cl"] or "").endswith("_link") for x in rs) or all(o in rb_ways for x in rs for o in x["oids"]))
    tick("the connectors (rank 2)")
    # ---- 6b. the change classes (docs/design/sections.md, section 3): every joint of a section, where OSM's tags change, is classified
    # before it touches the frame. The lanes here (the classes read the lane counts, `turn:lanes` and the junction nodes); the strips
    # after step 6a' (the meters' parking along the section stops for a turn pocket on the pocket's kerb side). Check J4 lists the places.
    ends_ = [(k, e, shapely.Point(r["line"].coords[0 if e == 0 else -1])) for k, r in enumerate(runs) for e in (0, 1)]
    etree2 = shapely.STRtree([p for _, _, p in ends_])
    by_sid2 = {}
    for r in runs:
        by_sid2.setdefault(r["sid"], []).append(r)

    def pocket_side(r):
        """The kerb side, in the way's frame (left +, right -), of the turn lane `turn:lanes` names on r's way; 0 for a turn lane at the
        centre (a left turn of a two-way road: the median narrows for it); None where no turn lane is named."""
        tg = tags.get(r["oid"], {})
        for key, sg_l, sg_r in (("turn:lanes", 1, -1), ("turn:lanes:forward", 1 if r["ow"] else 0, -1), ("turn:lanes:backward", 0, 1)):
            ls = [x.split(";")[0] for x in str(tg.get(key) or "").split("|")] if tg.get(key) else []
            if ls and ls[0] in TURNS and ls[0].endswith("left"):
                return sg_l
            if ls and ls[-1] in TURNS and ls[-1].endswith("right"):
                return sg_r
            if any(x in TURNS for x in ls):
                return 0
        return None

    def merging_arm(p, h_sec, n_lanes, sid):
        """An arm of another section at junction node p that continues into this one (its heading away from p within MERGE_DEG of
        opposite to the section's, h_sec) with n_lanes lanes (all, or one direction's): (its way, 'merge' or 'fork'), else None."""
        for i_ in etree2.query(p.buffer(0.6)):
            k_, e_, p_ = ends_[i_]
            q = runs[k_]
            if p_.distance(p) > 0.6 or q["sid"] == sid:
                continue
            hq = head_of(i_)
            if hq[0] * h_sec[0] + hq[1] * h_sec[1] > -math.cos(math.radians(MERGE_DEG)):
                continue
            if n_lanes not in (q["f"] + q["b"], q["f"], q["b"]):
                continue
            # (a one-way arm whose line ends at p flows into it: a merge; one that starts there leaves: a fork)
            return q["oid"], ("merge" if not q["ow"] or e_ == 1 else "fork")
        return None

    def h_away(r_, e_):     # r_'s heading away from its line's end e_ (0: the start, 1: the end)
        ln_ = r_["line"]
        a_, b_ = (ln_.interpolate(0), ln_.interpolate(min(3.0, ln_.length))) if e_ == 0 else (ln_.interpolate(ln_.length), ln_.interpolate(max(ln_.length - 3.0, 0)))
        return unit_v((b_.x - a_.x, b_.y - a_.y))
    changes = []    # J4 rows: dict(sid, i, a, b, cls, note, pt)
    for sid, rs in by_sid2.items():
        if rs[0].get("connector") or len(rs) < 2:
            continue
        L_tot = sum(r_["line"].length for r_ in rs)
        ends_sec = {0: shapely.Point(rs[0]["line"].coords[-1 if rs[0]["flip"] else 0]), 1: shapely.Point(rs[-1]["line"].coords[0 if rs[-1]["flip"] else -1])}
        h_sec = {0: h_away(rs[0], 1 if rs[0]["flip"] else 0), 1: h_away(rs[-1], 0 if rs[-1]["flip"] else 1)}
        s_along = 0.0
        for i, (a, b) in enumerate(zip(rs, rs[1:])):
            s_along += a["line"].length
            pj = shapely.Point(a["line"].coords[0 if a["flip"] else -1])
            fa = (a["f"], a["b"]) if not a["flip"] else (a["b"], a["f"])      # (forward, backward) lanes in the section's direction
            fb = (b["f"], b["b"]) if not b["flip"] else (b["b"], b["f"])
            ta, tb = sum(fa), sum(fb)
            delta = tb - ta
            wide = a if ta >= tb else b
            near = [(e_, d_) for e_, d_ in ((0, s_along), (1, L_tot - s_along)) if d_ <= POCKET_M and at_jn(ends_sec[e_])]
            both_w = a["wsrc"][0] == "osm" and b["wsrc"][0] == "osm"
            w_tag = lambda r_: tags.get(r_["oid"], {}).get("width")
            cls, note = None, ""
            if delta == 0 and fa != fb:
                cls, note = "turn pocket", f"the same total, the split differs: {fa[0]} + {fa[1]} then {fb[0]} + {fb[1]}"
            elif delta != 0:
                for e_, d_ in near:
                    hit = merging_arm(ends_sec[e_], h_sec[e_], abs(delta), sid)
                    if hit:
                        cls = hit[1]
                        note = f"{ta} then {tb} lanes: the lanes of w{hit[0]}, which {'joins' if cls == 'merge' else 'leaves'} at the junction {d_:.0f} m away"
                        break
                if cls is None and near and pocket_side(wide) is not None:
                    cls, note = "turn pocket", f"{ta} then {tb} lanes: w{wide['oid']} turn:lanes names a turn lane, {min(d_ for _, d_ in near):.0f} m from the junction"
                    wide["pocket"] = pocket_side(wide)
                if cls is None and both_w and abs(a["lw"] * ta - b["lw"] * tb) > 0.5:
                    cls, note = "real", f"{ta} then {tb} lanes, OSM width {w_tag(a)} then {w_tag(b)}"
                if cls is None:
                    cls, note = "unknown", f"{ta} then {tb} lanes: no road merges or forks, no turn lane named, no width evidence; the frame keeps {max(ta, tb)}"
            elif both_w and abs(a["lw"] - b["lw"]) > 0.1:
                cls, note = "real", f"OSM width {w_tag(a)} then {w_tag(b)}, the same lanes"
            changes.append(dict(sid=sid, i=i, a=a, b=b, cls=cls, note=note, pt=pj))
    tick("the change classes (rank 3)")
    # ---- 6a'. the kerb evidence is a section property: judged once for the whole section (the frame is one width, step 6c)
    by_sid1 = {}
    for r in runs:
        by_sid1.setdefault(r["sid"], []).append(r)
    for sid, rs in by_sid1.items():
        sec_side = lambda r_, sg: sg if not r_["flip"] else -sg       # a run's side in the section's frame
        # (the meters' parking is only where the meters stand, piece by piece: a strip that starts or stops is the class `parking` of
        # sections.md section 3, inside the frame; until 2026-10-16 it was spread along the whole section, and a strip stood at the
        # West 8th fork 40 m from its meter, s0-w473723210/3)
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
                if r_["wsrc"][0] != "urbanstyle" or r_["ex"][s_] or cl_.endswith("_link") or cl_ in ("motorway", "trunk") or r_.get("pocket") == s_:
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

    tick("the kerb evidence (rank 4)")
    # ---- 6a''. the room: the street's edge of rank 1 (the blocks and the paths' corridors) caps every kerb (Kaveh, 2026-10-16: "when
    # something partitions, there is no overlap and no gap"). The sidewalk line is data, the lane width a chosen value: where the lanes do
    # not fit between the two edges they narrow, down to LANE_MIN_M, their count as OSM maps it (width_method `narrowed`, check B8);
    # what still does not fit is cut at the edge (every space is cut from the street at the end, check B7)
    # the sidewalk strips: every walkway at level 0 that is no crossing and has no corridor of its own (a path), at OSM's width or
    # 2 SW_HALF_M, centred on its line: the walking side there, its near side the kerb (the room ends at it), its far side the block's edge
    # (blocks.py sets the edge 1 m behind the line; on a deck a footway's strip has flat ends: a round end wrapped the walking side round
    # the deck road's end where it lands, a half-disc at a1's ground point, Kaveh 2026-10-17)
    cor_ways = {w for (w,) in rows("SELECT way_id FROM work.corridor")}
    sw_items = [(g(w), g(w).buffer((wd / 2) if wd else SW_HALF_M, cap_style="round" if LV == 0 else "flat")) for o, wd, w in rows(f"""SELECT e.osm_id, e.width_m, {m('e.geometry')}
                                   FROM work.element e WHERE e.type = 'walkway' AND e.level_min = {LV} AND coalesce(e.subtype, '') <> 'crossing'
                                   AND e.class IN ('footway', 'path', 'steps', 'pedestrian')""") if o not in cor_ways]
    sw_strips = shapely.union_all([st_ for _, st_ in sw_items] or [shapely.Polygon()])
    sw_tree = shapely.STRtree([st_ for _, st_ in sw_items]) if sw_items else None
    blocks_L = [g(w) for (w,) in rows(f"SELECT {m()} FROM work.block WHERE level = 0")] + [low_decks()] if LV == 0 else [deck_outside(LV)]
    corridors_L = [g(w) for (w,) in rows(f"SELECT {m()} FROM work.corridor")] if LV == 0 else []
    hard_u = shapely.union_all(blocks_L + corridors_L or [shapely.Polygon()])
    htree = shapely.STRtree(list(shapely.get_parts(hard_u))) if not hard_u.is_empty else None
    edge_u = shapely.union_all(blocks_L + corridors_L + [sw_strips] or [shapely.Polygon()])
    etree = shapely.STRtree(list(shapely.get_parts(edge_u))) if not edge_u.is_empty else None

    def room(ln, sg):
        """The least distance from line ln to the street's edge on side sg (+ left), measured every ROOM_STEP_M; inf with no edge. A
        sidewalk strip counts only where its line runs along ln (within ALONG_COS) and beside it (LANE_M / 2 or more from ln's line): a
        footway on the road's line is no sidewalk of it, and a footway that ends at the road or crosses it is no
        sidewalk of it (its strip touched the road's line and the room was 0 for the whole road: no roadway at all, Monaco A3 499,
        Rue Bel Respiro; Kaveh, 2026-10-17, option b)"""
        best = math.inf
        if htree is None and sw_tree is None:
            return best
        n = max(2, int(ln.length // ROOM_STEP_M))
        for i in range(n):
            t = ln.length * (i + .5) / n
            a, b = ln.interpolate(max(t - 1, 0)), ln.interpolate(min(t + 1, ln.length))
            dx, dy = b.x - a.x, b.y - a.y
            h = (dx * dx + dy * dy) ** .5 or 1
            q = ln.interpolate(t)
            ray = shapely.LineString([(q.x, q.y), (q.x - sg * dy / h * ROOM_REACH_M, q.y + sg * dx / h * ROOM_REACH_M)])
            for k in (htree.query(ray) if htree is not None else []):
                hit = ray.intersection(htree.geometries[k])
                if not hit.is_empty:
                    best = min(best, q.distance(hit))
            for k in (sw_tree.query(ray) if sw_tree is not None else []):
                hit = ray.intersection(sw_items[k][1])
                if hit.is_empty:
                    continue
                wl = sw_items[k][0]
                if wl.distance(q) < LANE_M / 2:
                    continue        # (a walking way on the road's line, mapped over it or sharing its nodes, is no sidewalk of it:
                                    # a pedestrian way on Avenue Crovetto-Frères for 22 m gave its 375 m frame no room; Kaveh 2026-10-23)
                s_ = wl.project(shapely.ops.nearest_points(hit, q)[0])
                a2, b2 = wl.interpolate(max(s_ - 1, 0)), wl.interpolate(min(s_ + 1, wl.length))
                ddx, ddy = b2.x - a2.x, b2.y - a2.y
                h2 = (ddx * ddx + ddy * ddy) ** .5 or 1
                if abs(dx * ddx + dy * ddy) / (h * h2) >= ALONG_COS:
                    best = min(best, q.distance(hit))
        return best

    for r in runs:
        r["room"] = {1: room(r["line"], 1), -1: room(r["line"], -1)}
        r["room_cut"] = False
        strips_ = {s: r["wide"][s] + sum(w for _, w, _ in r["ex"][s]) for s in (1, -1)}
        avail = 2 * min(r["room"][s] - strips_[s] for s in (1, -1))
        if avail < r["W"] - 0.01:
            n_ = r["f"] + r["b"]
            W2 = max(avail, n_ * LANE_MIN_M)
            r["room_note"] = f"the street's edges leave {max(avail, 0):.2f} m for {n_} lanes: {r['lw']:.2f} m lanes narrowed to {W2 / n_:.2f} m"
            r["W"], r["lw"], r["wsrc"], r["room_cut"] = W2, W2 / n_, ("urbanstyle", "narrowed"), W2 > avail + 0.01
            r["kl"] = r["W"] / 2 + strips_[1]
            r["kr"] = -r["W"] / 2 - strips_[-1]

    def half_plane(p, n, side, far=300.0):
        t = (-n[1], n[0])
        q1 = (p[0] + t[0] * far, p[1] + t[1] * far)
        q2 = (p[0] - t[0] * far, p[1] - t[1] * far)
        return shapely.Polygon([q1, q2, (q2[0] + side * n[0] * far, q2[1] + side * n[1] * far), (q1[0] + side * n[0] * far, q1[1] + side * n[1] * far)])

    def joint_line(r):
        """r's line run on past each joint by a little more than the roadway is wide, so the bands reach the bisector there."""
        ln = r["line"]
        c = list(ln.coords)
        e = (r["fkl"] - r["fkr"]) + 2.0
        for _, n, side, where in r["cuts"]:
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
        # (the cut is local to the joint: the band runs past the joint by e (joint_line) and no more, so a disc of that reach round the
        # joint holds all there is to trim. An infinite half-plane also cut the band wherever the line came back behind it, a hairpin
        # or a long bend: Lacets Saint-Léon, Avenue des Spélugues and Avenue de La Quarantaine lost 30-100 m of lanes; Monaco 2026-10-16)
        w = r.get("fkl", r["kl"]) - r.get("fkr", r["kr"])
        for p, n, side, where in r["cuts"]:
            geom = geom.difference(half_plane(p, n, -side).intersection(shapely.Point(p).buffer(1.5 * w + 3.0)))
        return geom
    # the strips' changes (step 6b, after 6a'): a parking or cycle strip that starts or stops is class 'parking'; a joint where the lanes, the
    # width and the strips are the same is 'none' (another tag changes)
    for c_ in changes:
        a, b = c_["a"], c_["b"]
        diff = []
        for sg, nm in ((1, "left"), (-1, "right")):
            sa = {e[0] for e in a["ex"][sg if not a["flip"] else -sg]}
            sb = {e[0] for e in b["ex"][sg if not b["flip"] else -sg]}
            diff += [f"the {t} {'stops' if t in sa else 'starts'} on the {nm}" for t in sorted(sa ^ sb)]
        if diff and c_["cls"] is None:
            c_["cls"] = "parking"
        if diff:
            c_["note"] = (c_["note"] + "; " if c_["note"] else "") + ", ".join(diff)
        if c_["cls"] is None:
            c_["cls"], c_["note"] = "none", "the lanes, the width and the strips are the same (another tag changes)"
        a.setdefault("jcls", []).append(f"{c_['cls']} at the joint with w{b['oid']}")
        b.setdefault("jcls", []).append(f"{c_['cls']} at the joint with w{a['oid']}")
    tick("the room to the street's edge (rank 3)")
    # ---- 6c. one frame per section (docs/design/sections.md, rules 5-8): the lanes and the strips a source gives at the section's
    # widest place, one width for the whole section. Only a 'real' change (an OSM width on both sides) starts a new frame piece, with a
    # kerb taper over TAPER_M in the narrower piece. No line is moved sideways and no kerb tapers otherwise: where two ways' lines are not
    # aligned, the lanes jog inside the frame and the frame does not. (Until 2026-10-16 the continuity shift moved a subsection's line by
    # up to 2 m, a merging road kept its heading over its last 15 m, and a taper wedge ran from the wider kerb to the narrower: gone.)
    for r in runs:
        r["fkl"], r["fkr"], r["ftaper"], r["frame_of"] = r["kl"], r["kr"], [], r["oid"]

    def cap_room(r_):
        """The frame never passes the street's edge of rank 1 (6a''): each side capped by the run's room there."""
        r_["room_cap"] = False
        if r_["fkl"] > r_["room"][1]:
            r_["fkl"], r_["room_cap"] = r_["room"][1], True
        if r_["fkr"] < -r_["room"][-1]:
            r_["fkr"], r_["room_cap"] = -r_["room"][-1], True
    for r in runs:
        cap_room(r)
    real_at = {(c_["sid"], c_["i"]) for c_ in changes if c_["cls"] == "real"}
    for sid, rs in by_sid2.items():
        if rs[0].get("connector"):
            continue
        left = lambda r_: r_["kl"] if not r_["flip"] else -r_["kr"]       # the section's left and right kerb, as offsets from the way's line
        right = lambda r_: -r_["kr"] if not r_["flip"] else r_["kl"]
        groups_f, cur = [], [0]
        for i in range(1, len(rs)):
            if (sid, i - 1) in real_at:
                groups_f.append(cur)
                cur = []
            cur.append(i)
        groups_f.append(cur)
        for grp in groups_f:
            KL, KR = max(left(rs[i]) for i in grp), max(right(rs[i]) for i in grp)
            wo = max((rs[i] for i in grp), key=lambda q: q["kl"] - q["kr"])["oid"]
            for i in grp:
                r_ = rs[i]
                r_["fkl"], r_["fkr"] = ((KL, -KR) if not r_["flip"] else (KR, -KL))
                r_["frame_of"] = wo
                cap_room(r_)
        # the kerb taper at a real change: the narrower frame piece's edge runs from the wider kerb to its own over TAPER_M (chosen)
        for ga, gb in zip(groups_f, groups_f[1:]):
            a, b = rs[ga[-1]], rs[gb[0]]
            for fn in (left, right):
                wa = (a["fkl"] if not a["flip"] else -a["fkr"]) if fn is left else (-a["fkr"] if not a["flip"] else a["fkl"])
                wb = (b["fkl"] if not b["flip"] else -b["fkr"]) if fn is left else (-b["fkr"] if not b["flip"] else b["fkl"])
                if abs(wa - wb) < 0.05:
                    continue
                narrow = a if wa < wb else b
                sg = (1 if fn is left else -1) * (1 if not narrow["flip"] else -1)      # the section's side in the narrow piece's own frame
                narrow["ftaper"].append(((narrow is b) != narrow["flip"], sg, max(wa, wb), min(wa, wb)))
    # a joint where the room capped a frame and the two frames differ: the class `room` (a step there is a real change of the street's
    # width, as the sidewalk lines map it; R1 allows it, J4 names it)
    for c_ in changes:
        a, b = c_["a"], c_["b"]
        if (a.get("room_cap") or b.get("room_cap")) and abs((a["fkl"] - a["fkr"]) - (b["fkl"] - b["fkr"])) > 0.05:
            c_["cls"] = "room"
            c_["note"] = (f"the street's edges (the sidewalk lines, the blocks) leave the frame {a['fkl'] - a['fkr']:.2f} m then "
                          f"{b['fkl'] - b['fkr']:.2f} m: the frame ends at the edge; " + c_["note"])

    def wedge(ln, at_start, sg, kw, kn):
        """The strip on side sg (left +) of ln between the offset kn and the line from kw at ln's start (or end) to kn TAPER_M along."""
        L = min(TAPER_M, ln.length)
        lo, hi = [], []
        for s_ in [k * 1.0 for k in range(int(L) + 1)] + [L]:
            st_ = s_ if at_start else ln.length - s_
            p, a_, b_ = ln.interpolate(st_), ln.interpolate(max(st_ - 1, 0)), ln.interpolate(min(st_ + 1, ln.length))
            h = math.hypot(b_.x - a_.x, b_.y - a_.y) or 1
            nx, ny = -(b_.y - a_.y) / h, (b_.x - a_.x) / h
            d_ = kw + (kn - kw) * s_ / L
            lo.append((p.x + nx * sg * kn, p.y + ny * sg * kn))
            hi.append((p.x + nx * sg * d_, p.y + ny * sg * d_))
        return poly(shapely.make_valid(shapely.Polygon(lo + hi[::-1])))
    tick("the frames (rank 3)")
    # ---- 6c'. merges and forks (docs/design/sections.md, section 3, the classes merge and fork: "the lane blends into the neighbour at
    # the node"). At a junction node where two arms side by side (q1 through, q2 merging or forking, headings within MERGE_DEG) continue
    # into one section s whose lanes are q1's plus q2's: s keeps q1's kerb on the side away from q2, so its lanes sit half of q2's
    # width off its OSM line toward q2 (`mshift`, a section property: every piece of s with those lanes; s's frame with it, `mshift_f`),
    # and inside the intersection q2's band lies beside q1's, not on it (OSM ends q2's line on the node: a fill strip of q2's width
    # along q1 over their overlap). Without this the kerb jogged one lane on both sides at the node, each with a 4 m fillet: the bump
    # at West 8th, Kaveh 2026-10-16
    for r in runs:
        r["mshift"], r["mshift_f"] = 0.0, 0.0
    fills = {}      # junction node index -> [the strip beside the through arm]
    rtree0 = shapely.STRtree([r["line"] for r in runs]) if runs else None
    cosm = math.cos(math.radians(MERGE_DEG))
    for ni, n in enumerate(jn):
        arms = [(runs[k], e) for k in (rtree0.query(n.buffer(1.0)) if rtree0 is not None else []) for e in (0, 1)
                if shapely.Point(runs[k]["line"].coords[0 if e == 0 else -1]).distance(n) < 1.0]
        hd = {id(q): h_away(q, e) for q, e in arms}
        dot = lambda u, v: u[0] * v[0] + u[1] * v[1]
        for s_, es in arms:
            if s_.get("connector") or s_["mshift_f"]:
                continue
            for q1, e1 in arms:
                for q2, e2 in arms:
                    if s_ in (q1, q2) or q1 is q2 or q1["sid"] == q2["sid"] or (q1["f"] + q1["b"]) < (q2["f"] + q2["b"]):
                        continue
                    if dot(hd[id(q1)], hd[id(q2)]) < cosm or dot(hd[id(s_)], hd[id(q1)]) > -cosm:
                        continue        # (q1 and q2 not side by side, or s does not continue q1)
                    if s_["f"] + s_["b"] != q1["f"] + q1["b"] + q2["f"] + q2["b"]:
                        continue
                    # (q1 and q2 carry the same flow: both one-way into the node or both out of it, or both two-way. The two one-way
                    # carriageways of one street joining into its two-way way flow opposite ways: a divided road's end, no merge)
                    if not ((q1["ow"] and q2["ow"] and e1 == e2) or (not q1["ow"] and not q2["ow"])):
                        continue
                    # (side by side: q2's own band lies on q1's from the node over more than both roadways' widths; every arm's band
                    # touches the others' at the node, a side street at 45 degrees too, and that is no merge)
                    b1, b2 = band(q1["line"], q1["kr"], q1["kl"]), band(q2["line"], q2["kr"], q2["kl"])
                    ov = poly(b1.intersection(b2))
                    L1 = q1["line"].length
                    st1 = lambda pt: (q1["line"].project(pt) if e1 == 0 else L1 - q1["line"].project(pt))
                    reach_ = max([st1(shapely.Point(c_)) for q_ in shapely.get_parts(ov) for c_ in q_.exterior.coords] or [0.0])
                    if reach_ <= (q1["kl"] - q1["kr"]) + (q2["kl"] - q2["kr"]):
                        continue
                    far = shapely.Point(q2["line"].coords[-1 if e2 == 0 else 0])
                    dir_s = hd[id(s_)] if es == 0 else (-hd[id(s_)][0], -hd[id(s_)][1])        # s's line direction at the node
                    side_s = 1 if (dir_s[0] * (far.y - n.y) - dir_s[1] * (far.x - n.x)) > 0 else -1     # q2's side in s's own frame
                    w2 = (q2["f"] + q2["b"]) * s_["lw"]
                    n1 = q1["f"] + q1["b"]
                    for p_ in by_sid2.get(s_["sid"], [s_]):
                        sg_p = side_s * (1 if p_["flip"] == s_["flip"] else -1)
                        p_["mshift_f"] = sg_p * w2 / 2
                        p_["mshift"] = sg_p * max(p_["f"] + p_["b"] - n1, 0) * p_["lw"] / 2
                        p_["merge_ref"] = f"w{q2['oid']} {'joins' if dot(hd[id(q2)], hd[id(q1)]) > 0 and q2['ow'] and e2 == 1 else 'leaves'} w{q1['oid']} at n{node_id.get((round(n.x, 1), round(n.y, 1)), '?')}"
                    # the fill beside q1 on q2's side, over the stretch where q2's own band lies on q1's
                    dir_1 = hd[id(q1)] if e1 == 0 else (-hd[id(q1)][0], -hd[id(q1)][1])
                    side_1 = 1 if (dir_1[0] * (far.y - n.y) - dir_1[1] * (far.x - n.x)) > 0 else -1
                    seg_ = substring(q1["line"], 0.0, min(reach_, L1)) if e1 == 0 else substring(q1["line"], max(L1 - reach_, 0.0), L1)
                    edge_ = q1["fkl"] if side_1 > 0 else q1["fkr"]
                    fills.setdefault(ni, []).append(band(seg_, min(edge_, edge_ + side_1 * w2), max(edge_, edge_ + side_1 * w2)))
    for r in runs:
        r["xline"] = joint_line(r)
        fl_ = shift_line(r["xline"], r["mshift_f"]) if abs(r["mshift_f"]) > 1e-6 else r["xline"]
        if abs(r["mshift"]) > 1e-6:
            r["xline"] = shift_line(r["xline"], r["mshift"])
        cw = band(fl_, r["fkr"], r["fkl"])
        for at_start, sg, kw, kn in r["ftaper"]:
            cw = shapely.union_all([cw, wedge(r["line"], at_start, sg, kw, kn)])
        r["cw"] = poly(at_joints(r, cw))                                           # the frame
        r["own"] = poly(at_joints(r, band(r["xline"], r["kr"], r["kl"])))          # this piece's own lanes and strips

    tick("the merges and forks (rank 3)")
    # ---- 5. junctions
    crossings = [g(w) for (w,) in rows(f"""SELECT {m()} FROM work.element WHERE type IN ('walkway', 'cycleway') AND level_min = {LV}
                                            AND subtype = 'crossing'""")]
    rtree = shapely.STRtree([r["line"] for r in runs]) if runs else None
    jshapes = []
    reach_at = {}       # (node index, id of the run) -> how far the node's junction reaches along that run: its core + JUNC_ARM_M
    arm_cuts = []       # (point, heading) where each arm's roadway is cut at its stop line: the sidewalk is cut on the same line
    for ni, n in enumerate(jn):
        # the arms: the runs that end at the node (a run that only passes near it shares no node with it: not an arm)
        # (an end of the run's line within 1 m of the node, not the node's station on the line: a node beyond the line's end has
        # station 0 at any distance, and Boulevard Rainier III, 110 m away, was an arm of Rue Grimaldi's junction, which then
        # swallowed three junctions along it (i0-25194413, four nodes up to 98 m apart; Monaco 2026-10-16))
        arms = [runs[k] for k in (rtree.query(n.buffer(1.0)) if rtree is not None else [])
                if min(shapely.Point(runs[k]["line"].coords[0]).distance(n), shapely.Point(runs[k]["line"].coords[-1]).distance(n)) < 1.0]
        out = []
        for i, r in enumerate(arms):
            ln = r["line"]
            s0 = ln.project(n)
            away = 1 if s0 < ln.length / 2 else -1          # the arm runs from the node this way along its line
            st = lambda p: (ln.project(p) - s0) * away      # a point's station along the arm, from the node
            others = shapely.union_all([a["own"] for j, a in enumerate(arms) if j != i]) if len(arms) > 1 else shapely.Polygon()
            # the core: how far the other arms' carriageways overlap this one, from the node on without a break (an arm that comes
            # back beside another arm 100 m on overlaps it there too: that is no part of this junction, Monaco i0-25194413). The
            # arms' own lanes, not their frames: a frame wider than its lanes (the section is wider elsewhere) overlaps a parallel
            # arm along its whole length
            core, pieces = 0.0, []
            # (only where the overlap is at least CORE_MIN_M wide: two arms running side by side (a ramp beside the road it joins)
            # overlap by a sliver along their length, which is no junction; Fir Street at the Granville ramp, Kaveh 2026-10-15)
            for q in shapely.get_parts(poly(r["own"].intersection(others)).buffer(-CORE_MIN_M / 2).buffer(CORE_MIN_M / 2)):
                if q.geom_type == "Polygon" and not q.is_empty:
                    ss = [st(shapely.Point(c)) for c in q.exterior.coords]
                    pieces.append((min(ss), max(ss)))
            for lo, hi in sorted(pieces):
                if lo <= core + 0.5:
                    core = max(core, hi)
            reach = core + JUNC_ARM_M
            xdir = None         # the crosswalk that sets the stop line: its direction across the arm
            for x in crossings:
                hit = x.intersection(r["cw"])
                if hit.is_empty:
                    continue
                ss = [st(shapely.Point(c)) for q in shapely.get_parts(hit) if q.geom_type == "LineString" for c in q.coords]
                if ss and core - CROSS_HALF_M <= min(ss) <= core + CROSS_NEAR_M and max(ss) + CROSS_HALF_M >= reach:
                    reach = max(ss) + CROSS_HALF_M
                    seg = max((q for q in shapely.get_parts(hit) if q.geom_type == "LineString"), key=lambda q: q.length, default=None)
                    if seg is not None and seg.length > 0.5:
                        xdir = unit_v((seg.coords[-1][0] - seg.coords[0][0], seg.coords[-1][1] - seg.coords[0][1]))
            reach_at[(ni, id(r))] = reach      # (before the crosswalk's run-on: the core's own stop line, for the connector rule)
            reach = min(reach, ln.length)
            # (the arm's frame from the node to its stop line, cut square across the arm there: a circle round the node gave every
            # junction the wide road's radius, so a side street's lanes stopped half a road short of the kerb line, Kaveh 2026-10-15)
            a_, b_ = (s0, s0 + reach) if away > 0 else (s0 - reach, s0)
            pc = ln.interpolate(b_ if away > 0 else a_)
            qa, qb = ln.interpolate(max((b_ if away > 0 else a_) - 1, 0)), ln.interpolate(min((b_ if away > 0 else a_) + 1, ln.length))
            hd = unit_v((qb.x - qa.x, qb.y - qa.y))
            # the stop line: along the crosswalk that sets it (its own angle, 1.5 m beyond its far edge), else square to the road
            # (docs/design/stretches.md, "The geometry of a stretch"; Kaveh, 2026-10-17: "there are footways and crosswalk there!")
            cut = xdir if xdir is not None and abs(xdir[0] * hd[0] + xdir[1] * hd[1]) > 0.09 and abs(xdir[0] * hd[0] + xdir[1] * hd[1]) < 0.87 else None
            if cut is None:
                out.append(band(substring(ln, a_, b_), r["fkr"] + r["mshift_f"], r["fkl"] + r["mshift_f"]))
                arm_cuts.append(((pc.x, pc.y), hd, None))
            else:
                # the arm's roadway run on past the stop line, then cut along it on the node's side (a half-plane)
                ext_ = (s0, min(s0 + reach + 25.0, ln.length)) if away > 0 else (max(s0 - reach - 25.0, 0.0), s0)
                long_ = band(substring(ln, *ext_), r["fkr"] + r["mshift_f"], r["fkl"] + r["mshift_f"])
                nx, ny = -cut[1], cut[0]
                if (n.x - pc.x) * nx + (n.y - pc.y) * ny < 0:
                    nx, ny = -nx, -ny
                L = 200.0
                half = shapely.Polygon([(pc.x - cut[0] * L, pc.y - cut[1] * L), (pc.x + cut[0] * L, pc.y + cut[1] * L),
                                        (pc.x + cut[0] * L + nx * L, pc.y + cut[1] * L + ny * L), (pc.x - cut[0] * L + nx * L, pc.y - cut[1] * L + ny * L)])
                out.append(poly(long_.intersection(half)))
                arm_cuts.append(((pc.x, pc.y), hd, cut))
        out += fills.get(ni, [])        # (the merging arm's band beside the through arm's: step 6c')
        if out:
            jshapes.append((n, poly(shapely.union_all(out)), []))
    # the tighter connector rule (docs/design/stretches.md, "The connectors"; Kaveh, 2026-10-16): a short piece between two junction
    # nodes is a connector only where the two nodes' stop lines on it meet or cross (their cores overlap), so no section fits between
    # them; else it stays a short section between two intersections (Granville at West 6th: five nodes chained by short pieces)
    for r in runs:
        if r.get("connector") and r.get("conn_by_length"):
            ln = r["line"]
            ends = [min(range(len(jn)), key=lambda k: jn[k].distance(shapely.Point(ln.coords[e]))) for e in (0, -1)] if jn else []
            if len(ends) == 2 and all(jn[k].distance(shapely.Point(ln.coords[e])) < 1.0 for k, e in zip(ends, (0, -1))):
                ra, rb_ = reach_at.get((ends[0], id(r)), 0.0), reach_at.get((ends[1], id(r)), 0.0)
                if ra + rb_ < ln.length:
                    r["connector"] = False
    # the connectors' whole carriageways are in the intersection too (sections.md rule 4); they are no sections
    jshapes += [(None, r["cw"], r["oids"]) for r in runs if r.get("connector")]
    dropped = {}        # (W3: a road whose runs all go: why, at the last place one went; written to work.dropped)
    gone = lambda keep, why: [dropped.__setitem__(r["oid"], why) for r in runs if r not in keep]
    conn_ = [r for r in runs if not r.get("connector")]; gone(conn_, "a connector: its carriageway is in the intersection"); runs = conn_
    for r in runs:
        r["trans"] = {w: q for w, q in r.get("trans", {}).items() if q in runs}
    area = shapely.union_all([g(w) for (w,) in rows(f"SELECT {m()} FROM work.area")] or [shapely.Polygon()])
    blocks = shapely.union_all(blocks_L or [shapely.Polygon()])
    # (nor a path's corridor, a pedestrian way's own ground between the blocks, work.corridor: it ends at the street's sidewalk,
    # FURNISH_M + CLEAR_M from the roadway, so the sidewalk runs on past the path's mouth and the two touch; paths.md rule 5)
    cw_all = shapely.union_all([r["cw"] for r in runs] + [J for _, J, _ in jshapes] or [shapely.Polygon()])
    corridors = shapely.union_all([g(w) for (w,) in rows(f"SELECT {m()} FROM work.corridor")] or [shapely.Polygon()])
    street = poly(area.difference(blocks).difference(corridors)) if not area.is_empty else shapely.Polygon()
    clusters = []       # [nodes, shape, connector ways]
    for n, J, oids_ in jshapes:
        hit = [c for c in clusters if c[1].intersects(J)]
        for c in hit:
            clusters.remove(c)
        clusters.append([([n] if n is not None else []) + [x for c in hit for x in c[0]], shapely.union_all([J] + [c[1] for c in hit]),
                         list(oids_) + [o for c in hit for o in c[2]]])
    junctions = []
    for ns, U_, conn_ in clusters:
        # the corners between the arms rounded by KERB_RADIUS_M, once per intersection: what the closing adds beyond a corner's fillet (a
        # strip between two arms that run side by side, i0-430951364's loop) is no corner and stays out (J2)
        C_ = U_.buffer(KERB_RADIUS_M, join_style="round").buffer(-KERB_RADIUS_M, join_style="round")
        fillets = [q for q in shapely.get_parts(poly(C_.difference(U_))) if q.area <= FILLET_MAX_M2]
        J = poly(shapely.union_all([U_] + fillets))
        # the roadway never passes the street's edge nor a sidewalk strip: at a corner the kerb is the strip's near side where OSM maps
        # the line, the KERB_RADIUS_M fillet only where it does not (Kaveh, 2026-10-16)
        if etree is not None:       # (the edge's pieces near the junction, from the index: not the whole union)
            near_ = [etree.geometries[k] for k in etree.query(J)]
            if near_:
                J = poly(J.difference(shapely.make_valid(shapely.union_all(near_))))
        if J.is_empty:      # (all of it outside the street's edge: no junction there)
            continue
        ids = sorted(node_id.get((round(p.x, 1), round(p.y, 1))) or 0 for p in ns)
        nid = next((i for i in ids if i), None)
        jid = f"i{LV}-{nid}" if nid else f"i{LV}-x{round(J.centroid.x)}y{round(J.centroid.y)}"
        junctions.append(dict(id=jid, nodes=[i for i in ids if i], geom=poly(J.intersection(area)) if not area.is_empty else J, connectors=sorted(set(conn_))))
    J_all = shapely.union_all([j["geom"] for j in junctions] or [shapely.Polygon()])

    tick("the junction shapes (rank 2)")
    # ---- 6. sections: each run's carriageway less the junctions
    for r in runs:
        r["road_g"] = poly(r["cw"].difference(J_all))
        if not area.is_empty:
            r["road_g"] = poly(r["road_g"].intersection(area))
    keep_ = [r for r in runs if not r["road_g"].is_empty and r["road_g"].area > 0.5]
    for r in runs:
        if r not in keep_:
            dropped[r["oid"]] = ("no room: the street's edges leave its frame 0 m (6a'', the room rule)" if r["fkl"] - r["fkr"] < 0.1
                                 else "its frame lies inside the junctions or outside the area (6: road_g under 0.5 m2)")
    runs = keep_
    # (a frame's paved rest never covers another road's own lanes: two parallel one-way ways of one street, one of them wider elsewhere
    # in its section, or the narrower one is eaten and goes into the junction as a sliver; Hemlock Street at West 7th, 2026-10-16)
    own_t = shapely.STRtree([r["own"] for r in runs]) if runs else None
    for k, r in enumerate(runs):
        others = [runs[j]["own"] for j in own_t.query(r["road_g"]) if j != k and runs[j]["own"].intersects(r["road_g"])]
        if others:
            r["road_g"] = poly(r["road_g"].difference(shapely.union_all(others).difference(r["own"])))
    taken = shapely.Polygon()
    for r in sorted(runs, key=lambda r: (-(r["f"] + r["b"]), STREET.index(r["cl"].replace("_link", "")) if r["cl"].replace("_link", "") in STREET else 99)):
        r["road_g"] = poly(r["road_g"].difference(taken))
        taken = shapely.union_all([taken, r["road_g"]])
    # (a run whose roadway the junctions leave under SLIVER_M2 is a sliver between a junction and a crossing node: it joins the junction)
    small = [r for r in runs if r["road_g"].is_empty or r["road_g"].area < SLIVER_M2]
    for r in small:
        for j in junctions:
            if not r["road_g"].is_empty and j["geom"].distance(r["road_g"]) < 0.1:
                # (its own roadway outside the junctions only: the whole frame ran over the other junction's arm, U1 34.5 m2 at the
                # Granville ramp foot, i0-877917634 and i0-877917571)
                j["geom"] = poly(shapely.union_all([j["geom"], r["road_g"]]))
                break
    if small:
        J_all = shapely.union_all([j["geom"] for j in junctions] or [shapely.Polygon()])
        for r in runs:
            if r not in small:
                r["road_g"] = poly(r["road_g"].difference(J_all))
    for r in runs:
        if r in small:
            dropped[r["oid"]] = "a sliver under SLIVER_M2 after the wider roads took their part (6: joins the junction)"
    keep_ = [r for r in runs if r not in small and not r["road_g"].is_empty and r["road_g"].area > 0.5]
    gone(keep_, "nothing left after the junctions took the slivers (6)"); runs = keep_
    for r in runs:      # (a neighbour that went into the junction is no joint partner any more)
        r["trans"] = {w: q for w, q in r.get("trans", {}).items() if q in runs}
    roadway = shapely.union_all([r["road_g"] for r in runs] + [J_all])
    # W3's record: every road of this level with no run left, and why (a road the edges never gave is not in it: W3 finds those itself)
    left_ = {r["oid"] for r in runs}
    con.execute("CREATE TABLE IF NOT EXISTS work.dropped (osm_id BIGINT, level INTEGER, reason VARCHAR)")
    con.execute("DELETE FROM work.dropped WHERE level = ?", [LV])
    rows_ = [(int(o), LV, why) for o, why in dropped.items() if o not in left_]
    if rows_:
        con.executemany("INSERT INTO work.dropped VALUES (?, ?, ?)", rows_)

    tick("the sections' roadways (rank 3)")
    # ---- barriers continued from a bridge landing: a bridge whose corrections name a median barrier keeps it on the ground along the
    # landing way's chain, on the side where a roadway of the other direction runs within GAP_M, until that roadway ends or a junction
    # begins (the guardrail from the Granville ramp down to Fir Street; Kaveh 2026-10-15: OSM maps none, the bridge's correction is the source)
    from .corrections import bridge as bridge_corr
    cw_tree = shapely.STRtree([r["cw"] for r in runs]) if runs else None
    barriers = []       # (line, ref)
    for pf in (bridges if LV == 0 else ()):       # (on the ground only)
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

    tick("the barriers from bridges (rank 5)")
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
        objs = [g(w) for (w,) in rows(f"""SELECT {m()} FROM work.object WHERE level = {LV} AND source = 'osm'
                                          AND class NOT LIKE 'crossing.%' AND class NOT LIKE 'access.%'""")]
        objs += [g(w) for (w,) in rows(f"""SELECT {m()} FROM work.element WHERE type IN ('walkway', 'cycleway') AND level_min = {LV}
                                           AND coalesce(subtype, '') <> 'crossing'""")]
        o_tree = shapely.STRtree(objs) if objs else None
        objs += [bl for bl, _ in barriers]      # (a barrier along the strip: it is an island, the bridge's guardrail continued, Kaveh 2026-10-16)
        o_tree = shapely.STRtree(objs) if objs else None
        def on_barrier(q):  # a barrier runs along q (over 2 m of it)
            return any(bl.intersection(q.buffer(0.2)).length > 2.0 for bl, _ in barriers)

        def bare(q):        # nothing mapped on q: no kerb, object, path or barrier
            return o_tree is None or not any(objs[i].intersection(q.buffer(0.2)).length > 2.0 or (objs[i].geom_type == "Point" and q.buffer(0.2).contains(objs[i]))
                                             for i in o_tree.query(q.buffer(0.2)))
        for q in shapely.get_parts(thin):
            # (a strip that touches a block only at a corner (under ISLAND_TOUCH_M) lies between roadways: the gore where a slip lane
            # leaves a junction stood as a sidewalk wedge in the way of the turning lane, Kaveh 2026-10-16)
            if q.area <= 0.5 or along_edge(q) >= ISLAND_TOUCH_M:
                continue
            if bare(q):
                gaps.append(q)
                continue
            # (the strip holds something: an island. It begins where the strip is JGAP_M wide: a thinner tail of it with nothing on it is
            # paved roadway. Two frames that diverge slowly left a wedge 20 m long inside the junction, i0-245673105#9; Kaveh 2026-10-16)
            # (mitre joins: the tail is cut off square; round joins left a 1 m arc on the island's edge at the cut)
            # An island is at least JGAP_M wide: a thinner piece is paved whatever OSM maps on it (a sidewalk line or a kerb point in a 1 m
            # strip between two roadways means the roadways' edges are a little off), unless a barrier runs along it (the bridge's median
            # guardrail). The spurs on Granville north of West 6th, s0-w341691651/1#6 (1.1 m wide); Kaveh 2026-10-17: "you didn't fix it yet"
            core_ = q.buffer(-JGAP_M / 2, join_style="mitre").buffer(JGAP_M / 2, join_style="mitre")
            for sp in shapely.get_parts(poly(q.difference(core_))):
                if sp.area > 0.5 and along_edge(sp) < ISLAND_TOUCH_M and not on_barrier(sp):
                    gaps.append(sp)
    # ---- a divided road: the two one-way carriageways of one street between the same two junctions are one section, one space
    # (docs/design/dual-carriageways.md; Kaveh, 2026-10-16: the median between two sections went left and right piece by piece, a zig-zag
    # through Fir Street). Two runs pair when both are one-way, carry the same name, run side by side (every end of each within DUAL_M
    # of the other's line, the lines within DUAL_M over 80 % of their length) and no block lies between their lines. The second keeps
    # its own lanes and kerbs; it takes the first's space id, so the median between them is that one space's island
    def side_by_side(a, b):
        la, lb = a["line"], b["line"]
        if any(shapely.Point(c).distance(lb) > DUAL_M for c in (la.coords[0], la.coords[-1])) or any(shapely.Point(c).distance(la) > DUAL_M for c in (lb.coords[0], lb.coords[-1])):
            return False
        # (side by side, not end to end: each line's middle projects onto the inside of the other, 2 m or more away from it; two
        # consecutive pieces of one road passed the distance test)
        for x_, y_ in ((la, lb), (lb, la)):
            mid_ = x_.interpolate(0.5, normalized=True)
            t_ = y_.project(mid_)
            if mid_.distance(y_) < 2.0 or t_ < 0.5 or t_ > y_.length - 0.5:
                return False
        n_ = max(4, int(la.length // 5))
        near = sum(1 for i in range(n_ + 1) if la.interpolate(la.length * i / n_).distance(lb) <= DUAL_M)
        if near < 0.8 * (n_ + 1):
            return False
        between = shapely.make_valid(shapely.Polygon(list(la.coords) + list(lb.coords)[::-1]))
        return between.intersection(blocks).area < 1.0 if not blocks.is_empty else True
    dual_pairs = []
    for k1, r1 in enumerate(runs):
        if not r1["ow"] or not r1["name"] or r1.get("dual") is not None or r1.get("connector"):
            continue
        for k2 in range(k1 + 1, len(runs)):
            r2 = runs[k2]
            if r2.get("dual") is not None or not r2["ow"] or r2["name"] != r1["name"] or r2.get("connector") or r2["sid"] == r1["sid"]:
                continue
            if side_by_side(r1, r2):
                r2["dual"], r2["sid"], r2["sub"] = r1["sub"], r1["sid"], r1["sub"]
                r1["dual_w"] = round((r1["fkl"] - r1["fkr"]) + (r2["fkl"] - r2["fkr"]) + max(r1["line"].distance(r2["line"]) - (r1["fkl"] - r1["fkr"]) / 2 - (r2["fkl"] - r2["fkr"]) / 2, 0), 2)
                dual_pairs.append((r1["sub"], r2["oid"]))
                break
    if dual_pairs:
        print(f"  division: {len(dual_pairs)} divided roads, their two carriageways one section each: " + ", ".join(f"{u} + w{o}" for u, o in dual_pairs[:8]), flush=True)
    owners = [(r["sub"], r["road_g"]) for r in runs] + [(j["id"], j["geom"]) for j in junctions]
    gaps_u = shapely.union_all([q for q in gaps if q.area >= 2.0]) if gaps else shapely.Polygon()     # (shared out below, as the realm)
    # the pedestrian side is cut by the same straight lines as the roadway (each arm's stop-line cut, each joint's bisector), run
    # across the street to the blocks; each piece goes to the space whose roadway it touches most (Voronoi cells of the kerbs' points
    # gave the spaces jagged edges, Kaveh 2026-10-15)
    cutlines = []
    for pc, hd, along in arm_cuts + [(p_, n_, None) for r in runs for p_, n_, _, _ in r["cuts"]]:      # (hd: along the road; the cut is square to it, or along a crosswalk)
        t_ = along if along is not None else (-hd[1], hd[0])
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
        # the one partition (Kaveh, 2026-10-16: "why do the sections and intersections not have a clean shape?"): the whole street of
        # rank 1 cut only by the cut lines (each arm's stop line, each joint between subsections), run across the street to the blocks'
        # edges; the face between two cuts along a road is that section's, the face between a junction's arm cuts is that
        # intersection's, corners included: the roadway with the most area inside a face owns the face, and every piece of the walking
        # side goes to the owner of the face that holds it. A face with no roadway in it (a widening with no lane) keeps the old rule:
        # the roadway it touches most. (Until then every piece went to the roadway it touched most, and a corner went to the section
        # or the intersection by centimetres of shared edge: bites and hooks in every outline, Fir Street at West 8th)
        zf, zown = [], {}
        if cutlines and not street.is_empty:
            stree_ = shapely.STRtree(list(shapely.get_parts(street)))
            cl3 = [q for c_ in cutlines for k_ in stree_.query(c_) for q in shapely.get_parts(c_.intersection(stree_.geometries[k_]))
                   if q.geom_type == "LineString" and q.length > 0.01]
            zf = [f_ for f_ in shapely.get_parts(shapely.polygonize(shapely.get_parts(shapely.unary_union([street.boundary] + cl3)))) if f_.area > 0.01]
            for i_, f_ in enumerate(zf):
                best_, ba_ = None, 0.5
                for k in otree.query(f_):
                    a_ = owners[k][1].intersection(f_).area
                    if a_ > ba_:
                        best_, ba_ = k, a_
                zown[i_] = best_
        # (a face can hold several roadways where a cut is missing (a road through a T, a dead end): inside a face a piece goes to the
        # roadway of that face it touches most, and only a piece touching none of them goes to the face's owner; Pine Street's whole
        # walking side went to its bigger neighbour, s0-w1419312038/1 had its lanes alone; Kaveh, 2026-10-16)
        zin = {}
        for i_, f_ in enumerate(zf):
            zin[i_] = [k for k in otree.query(f_) if owners[k][1].intersection(f_).area > 0.5]
        ztree = shapely.STRtree(zf) if zf else None
        for q in pieces_:
            if q.area < 0.01:
                continue
            best, bl = None, 0.0
            zi = None
            if ztree is not None:
                rp = q.representative_point()
                zi = next((i_ for i_ in ztree.query(rp) if zf[i_].contains(rp)), None)
            cands = zin.get(zi) if zi is not None and zin.get(zi) else list(otree.query(q.buffer(0.1)))
            for k in cands:
                l_ = owners[k][1].boundary.intersection(q.buffer(0.05)).length
                if l_ > bl:
                    best, bl = k, l_
            if best is None and zi is not None:
                best = zown.get(zi)
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

    tick("the walking side shared out (ranks 3-4)")
    # ---- 8a. crosswalks: OSM's crossing ways over the roadway (CROSSWALK_M wide, or OSM `width`), and a crossing node on a road with no
    # crossing way at it: a band across that road's carriageway. Their paint from `crossing:markings` (see markings()); the lanes and the
    # junction area give way to them (a crosswalk is its own part).
    xways = [(o, g(w)) for o, w in rows(f"""SELECT osm_id, {m()} FROM work.element WHERE type IN ('walkway', 'cycleway') AND level_min = {LV}
                                            AND subtype = 'crossing'""")]
    xtags = {o: dict(t or {}) for o, t in rows("SELECT osm_id, tags FROM osm.raw.ways WHERE osm_id IN (SELECT unnest(?::BIGINT[]))",
                                                [[o for o, _ in xways]])} if xways else {}
    xnodes = [(o, dict(t or {}), shapely.Point(x, y)) for o, t, x, y in rows(f"""SELECT osm_id, tags, ST_X(p), ST_Y(p) FROM (SELECT osm_id, tags,
                 ST_Transform(ST_Point(lon, lat), 'EPSG:4326', '{epsg}', always_xy := true) AS p FROM osm.raw.nodes WHERE tags['highway'] = 'crossing')""")]
    xw_tree = shapely.STRtree([x for _, x in xways]) if xways else None
    rtree = shapely.STRtree([r["line"] for r in runs]) if runs else None        # (the runs as step 6 left them)
    roadway_x = shapely.union_all([roadway, gaps_u])      # (the strips between roadways are roadway too)
    xw = []     # [(polygon, markings, ref, axis line, width)]

    def crosses_road(seg):
        """The crossing piece runs across the road, not along it: a piece that crosses a road's line meets it at 30° or more; one that
        crosses no line (over a junction area, or from a median) is a crossing when it is no longer than XWALK_MAX_M. A footway tagged
        crossing that ran beside Boulevard du Larvotto for 80 m took the outer 1.5 m of its lane (A1; Monaco 2026-10-16)."""
        ks = [k for k in (rtree.query(seg) if rtree is not None else []) if runs[k]["line"].intersects(seg)]
        if not ks:
            return seg.length <= XWALK_MAX_M
        ln = runs[ks[0]]["line"]
        hit = ln.intersection(seg)
        mid = next((g for g in shapely.get_parts(hit) if g.geom_type == "Point"), hit.centroid)
        s_, t_ = ln.project(mid), seg.project(mid)
        a_, b_ = ln.interpolate(max(s_ - 1, 0)), ln.interpolate(min(s_ + 1, ln.length))
        xa, xb = seg.interpolate(max(t_ - 1, 0)), seg.interpolate(min(t_ + 1, seg.length))
        h1, h2 = math.hypot(xb.x - xa.x, xb.y - xa.y) or 1, math.hypot(b_.x - a_.x, b_.y - a_.y) or 1
        return abs((xb.x - xa.x) * (b_.x - a_.x) + (xb.y - xa.y) * (b_.y - a_.y)) / (h1 * h2) < math.cos(math.radians(30))
    for oid, x in xways:
        w = num_f(xtags.get(oid, {}).get("width")) or CROSSWALK_M
        for seg in shapely.get_parts(x.intersection(roadway_x.buffer(0.3))):
            if seg.geom_type == "LineString" and seg.length >= 1.0 and crosses_road(seg):
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

    tick("the crosswalks (rank 5)")
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

    service_in = [(g(w), num_f(dict(t or {}).get("width")) or ALLEY_W_M) for w, t in rows(f"""SELECT {m()}, tags FROM work.element e
                     LEFT JOIN osm.raw.ways w ON w.osm_id = e.osm_id WHERE e.type IN ('road', 'walkway') AND e.level_min = {LV} AND e.class = 'service'
                     AND NOT {street_sql('e')}""")]

    def ped(uid, G, R):
        """The pedestrian side R of roadway G: furnishing, sidewalk, frontage; a piece that touches no block or the area's edge lies
        between roadways only: an island (a median of a divided road, a traffic island), not a sidewalk."""
        if R.is_empty:
            return
        # a sliver of the walking side (under SLIVER_ROAD_M2) that touches no block lies in the roadway, where two roadways do not meet
        # exactly at a cut: it is paved roadway, so no kerb is drawn round it (s0-w74226330/1:kerb:1; Kaveh, 2026-10-17)
        crumbs = [q for q in shapely.get_parts(R) if q.area < SLIVER_ROAD_M2 and along_edge(q) < ISLAND_TOUCH_M and q.distance(isl_all) > 0.05]
        if crumbs:
            add(uid, "paved", shapely.union_all(crumbs), source="urbanstyle", method="derived",
                ref="a sliver between two roadways at a cut: roadway")
            R = poly(R.difference(shapely.union_all(crumbs)))
            if R.is_empty:
                return
        isl = [q for q in shapely.get_parts(R) if along_edge(q) < ISLAND_TOUCH_M and q.area >= ISLAND_MIN_M2 and not q.buffer(-0.5).is_empty]
        # (a small piece that touches no block and touches an island is that island's, also an island of the next space: the island's
        # tip cut off into the junction stood as a raised furnishing triangle in the roadway, Fir Street at Broadway; Kaveh 2026-10-16)
        isl += [q for q in shapely.get_parts(R) if along_edge(q) < ISLAND_TOUCH_M and q not in isl and q.distance(isl_all) < 0.05]
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
        pv = dict(source="urbanstyle", method="chosen", width_source="urbanstyle", width_method="chosen")
        strip_ = poly(R.intersection(sw_strips)) if not sw_strips.is_empty else shapely.Polygon()
        if not strip_.is_empty and strip_.area > 0.5:
            # OSM maps the sidewalk line: the strip is the sidewalk; what lies between it and the roadway is the furnishing zone, measured;
            # what lies beyond it (to the block's edge, 1 m behind the line: next to nothing) the frontage
            rest_ = poly(R.difference(strip_))
            f_ = shapely.union_all([q for q in shapely.get_parts(rest_) if q.distance(G) < 0.05] or [shapely.Polygon()])
            fr_ = poly(rest_.difference(f_))
            add(uid, "sidewalk", strip_, width_m=2 * SW_HALF_M, source="osm", method="mapped", width_source="urbanstyle", width_method="chosen",
                ref=f"OSM's sidewalk line, {2 * SW_HALF_M} m wide where OSM gives no width")
            add(uid, "furnishing", f_, source="osm", method="derived", width_source="osm", width_method="measured",
                ref="between the kerb and OSM's sidewalk line")
            add(uid, "frontage", fr_, ref="beyond OSM's sidewalk line to the block's edge", **pv)
            return
        f_ = poly(R.intersection(G.buffer(FURNISH_M)))
        s_ = poly(R.intersection(G.buffer(FURNISH_M + CLEAR_M)).difference(f_))
        rest = poly(R.difference(G.buffer(FURNISH_M + CLEAR_M)))
        add(uid, "furnishing", f_, width_m=FURNISH_M, ref=f"{FURNISH_M} m from the kerb", **pv)
        add(uid, "sidewalk", s_, width_m=CLEAR_M, ref=f"the clear path, {CLEAR_M} m", **pv)
        add(uid, "frontage", rest, ref="the rest to the block's edge", **pv)

    # every island of the level, whichever space holds it: a piece of the pedestrian side that touches no block (ped() reads it)
    isl_all = shapely.union_all([q for X in share.values() for q in shapely.get_parts(X)
                                 if q.area >= ISLAND_MIN_M2 and along_edge(q) < ISLAND_TOUCH_M and not q.buffer(-0.5).is_empty] or [shapely.Polygon()])
    for k, r in enumerate(runs):
        G, ln, uid = r["road_g"], r["line"], r["sub"]
        R = share.get(k, shapely.Polygon())
        U = poly(shapely.union_all([G, R] + gap_of.get(k, [])))
        units.append((uid, "subsection", r["sid"], U))
        for q in gap_of.get(k, []):
            add(uid, "paved", q, source="osm", method="derived", ref=gap_ref)
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
            if r.get("dual") is None:
                subrows.append((uid, r["sid"], r["cl"], round(r.get("dual_w") or (r["fkl"] - r["fkr"]), 2), r["ow"], round(ln.length, 1), None, None, "section end", round(r["mshift"], 3), axis_out(ln)))
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
            """The neighbour q's lane (d, n) as offsets from q's own line (q runs the other way: the directions and the sides swap), or
            q's lanes' edge on that side (no such lane: the lane opens from the lanes' edge). Both lines are OSM's: where they are not
            aligned, the lanes jog over TAPER_M inside the frame (sections.md rule 6)."""
            mirror = r["flip"] != q["flip"]
            dq = d if not mirror else ("backward" if d == "forward" else "forward")
            dz = (q["mshift"] if not mirror else -q["mshift"]) - r["mshift"]      # (each piece's line moved by its own merge shift)
            if n <= (q["f"] if dq == "forward" else q["b"]):
                t0, t1 = own(dq, n, q)
                t0, t1 = ((-t1, -t0) if mirror else (t0, t1))
                return (t0 + dz, t1 + dz)
            sq = side if not mirror else -side       # (q's lanes' edge on that side, its widened outer lane included)
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
                       position_source="osm", position_method="mapped" if not r["mshift"] else "derived",
                       position_ref=f"w{r['oid']}: the lanes' middle on its OSM line" + (f", moved {abs(r['mshift']):.2f} m: {r.get('merge_ref')}, the kerb away from it continues (sections.md, merge)" if r["mshift"] else ""))
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
                    edge = (side * (r["W"] / 2 + r["wide"][side]), side * (r["W"] / 2 + r["wide"][side]))     # (this run's lanes' edge there)
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
        # the frame beyond this piece's lanes and strips (the section is wider elsewhere, sections.md rule 6): paved roadway, no lane
        rest_ = poly(G.difference(taken_).buffer(-0.05).buffer(0.05)) if not taken_.is_empty else G
        if not rest_.is_empty and rest_.area > 0.5:
            add(uid, "paved", rest_, source="osm", method="derived", position_source="osm", position_method="derived",
                ref=f"the frame of {r['sid']} ({round(r['fkl'] - r['fkr'], 2)} m, its widest place w{r['frame_of']}) beyond w{r['oid']}'s lanes and strips: "
                    f"paved roadway, no lane" + (f" ({'; '.join(r['jcls'])})" if r.get("jcls") else ""),
                position_ref="the section's frame, one width for the whole section", **common)
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
            lo_, hi_ = lo_ + r["mshift"], hi_ + r["mshift"]
            if hi_ - lo_ < 0.5:
                continue
            p_ = ln.interpolate(s_)
            a_, b_ = ln.interpolate(max(s_ - 1, 0)), ln.interpolate(min(s_ + 1, ln.length))
            h_ = math.hypot(b_.x - a_.x, b_.y - a_.y) or 1
            nx, ny = -(b_.y - a_.y) / h_, (b_.x - a_.x) / h_
            mark(uid, "stop line", shapely.LineString([(p_.x + nx * lo_, p_.y + ny * lo_), (p_.x + nx * hi_, p_.y + ny * hi_)]).intersection(G.buffer(0.01)),
                 "urbanstyle", "derived", "where the lanes enter the junction")
        ped(uid, G, R)
        if r.get("dual") is None:
            subrows.append((uid, r["sid"], r["cl"], round(r.get("dual_w") or (r["fkl"] - r["fkr"]), 2), r["ow"], round(ln.length, 1), None, None, "section end", round(r["mshift"], 3), axis_out(ln)))
    for j in junctions:
        k = len(runs) + junctions.index(j)
        R = share.get(k, shapely.Polygon())
        units.append((j["id"], "intersection", None, poly(shapely.union_all([j["geom"], R] + gap_of.get(k, [])))))
        # (a strip between roadways inside an intersection is junction area, one surface with it: a paved tail of an island stood as a
        # dark wedge set into the junction area, i0-245673105; Kaveh 2026-10-16)
        add(j["id"], "junction area", shapely.union_all([j["geom"]] + gap_of.get(k, [])), source="osm", method="derived",
            ref=("the junction of " + ", ".join(f"n{i}" for i in j["nodes"]) if j["nodes"] else "the arms' carriageways where they meet")
            + (" with the connectors " + ", ".join(f"w{o}" for o in j["connectors"]) if j["connectors"] else ""))
        ped(j["id"], j["geom"], R)
        junction_rows += [(j["id"], i, 0, j["id"]) for i in j["nodes"]]

    # (a divided road's two carriageways: one space, their units joined)
    if dual_pairs:
        joined_, order_ = {}, []
        for u, k, s_, x in units:
            if u not in joined_:
                joined_[u] = [k, s_, x]
                order_.append(u)
            else:
                joined_[u][2] = poly(shapely.union_all([joined_[u][2], x]))
        units = [(u, joined_[u][0], joined_[u][1], joined_[u][2]) for u in order_]
    uu_ = [(u[0], u[3]) for u in units]
    ut_ = shapely.STRtree([x for _, x in uu_]) if uu_ else None
    for bl, ref_ in barriers:
        for q in shapely.get_parts(bl):
            if q.geom_type != "LineString" or q.length < 0.5:
                continue
            k_ = next((k for k in (ut_.query(q.centroid) if ut_ is not None else []) if uu_[k][1].distance(q.centroid) < 0.5), None)
            mark(uu_[k_][0] if k_ is not None else f"s{LV}-barrier", "barrier", q, "urbanstyle corrections", "continued", ref_)
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

    tick("the parts and marks (ranks 5-6)")
    # ---- write (the level-0 rows of division.py's tables, each table with division's columns and types)
    for t, cols in SCHEMA.items():
        have = {c for (c,) in rows(f"SELECT column_name FROM information_schema.columns WHERE table_schema = 'work' AND table_name = '{t}'")}
        q_ = lambda c: f'"{c}"'
        if have:
            con.execute(f"CREATE OR REPLACE TABLE work.{t} AS SELECT " + ", ".join(
                (f"CAST({q_(c)} AS {ty}) AS {q_(c)}" if c in have else f"CAST(NULL AS {ty}) AS {q_(c)}") for c, ty in cols.items()) + f" FROM work.{t}")
        else:
            con.execute(f"CREATE TABLE work.{t} (" + ", ".join(f"{q_(c)} {ty}" for c, ty in cols.items()) + ")")
    for t in ("part", "mark", "width", "turn", "approach"):
        try:
            con.execute(f"DELETE FROM work.{t} WHERE level = {LV}")
        except duckdb.Error:
            pass
    for t in ("cut", "junction", "subsection", "change"):
        try:
            con.execute(f"DELETE FROM work.{t} WHERE level = {LV}")
        except duckdb.Error:
            pass
    con.execute(f"DELETE FROM work.unit WHERE level = {LV}")
    # a level-1 way this step puts on the ground (nothing passes under it) has no space at level 1 too (spaces.py made one: West
    # Broadway's deck drawn in the air over its own street, s0-w473723218/1; Kaveh 2026-10-15)
    eids = [str(e) for (e,) in rows("SELECT DISTINCT edge_id FROM osm.driving.edges WHERE osm_id IN (SELECT unnest(?::BIGINT[]))",
                                    [sorted(l1_ground)])] if l1_ground else []
    if eids:
        for t in ("part", "mark", "width", "turn", "approach", "unit"):
            try:
                con.execute(f"DELETE FROM work.{t} WHERE level >= 1 AND regexp_extract(unit_id, '^s1-(-?[0-9]+)/', 1) IN (SELECT unnest(?::VARCHAR[]))", [eids])
            except duckdb.Error:
                pass
        try:
            con.execute("DELETE FROM work.subsection WHERE level >= 1 AND regexp_extract(subsection_id, '^s1-(-?[0-9]+)/', 1) IN (SELECT unnest(?::VARCHAR[]))", [eids])
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
    # every space is a piece of rank 1's street: cut by the blocks and the corridors, so no space reaches into a block (check B7)
    if not street.is_empty:
        # (each shape cut by the street's pieces near it, from a spatial index: thousands of cuts against the whole street polygon were slow)
        st_parts = list(shapely.get_parts(street))
        st_tree = shapely.STRtree(st_parts)
        def in_street(x):
            near_ = [st_parts[k] for k in st_tree.query(x)]
            return x.intersection(shapely.union_all(near_)) if near_ else shapely.Polygon()
        units = [(u, k, s_, poly(in_street(x))) for u, k, s_, x in units]
        units = [u for u in units if not u[3].is_empty]
        for p_ in parts:
            p_["geom"] = poly(in_street(p_["geom"]))
        marks = [m_[:2] + (in_street(m_[2]),) + m_[3:] for m_ in marks]
        marks = [m_ for m_ in marks if not m_[2].is_empty]
    # ---- the landings (docs/design/spaces.md, "At a landing"; Kaveh, 2026-10-17: the bridge model's lanes are an arm of the ground's
    # junction at the landing): the ground under a deck's lanes, from the landing back to where the deck is LANDING_Z_M high, is roadway,
    # junction area in an intersection, paved in a section, so the deck's lanes meet roadway; the walking side there gives way to it
    # (the a3 on-ramp's lanes landed on the furnishing of i0-877917375/2792935203)
    land_bands = []
    for pf in (bridges if LV == 0 else ()):       # (on the ground only: on a deck the deck's own lanes run on)
        prof = json.load(open(pf))
        if prof.get("crs") and prof["crs"] != epsg:
            continue
        for ax in prof.get("axes", []):
            pts_ = (ax.get("line") or {}).get("value") or []
            if len(pts_) < 2:
                continue
            L_ = shapely.LineString([p_[:2] for p_ in pts_])
            vp = sorted((ax.get("vertical") or {}).get("points") or [])
            secs = sorted(ax.get("sections") or [], key=lambda x: x.get("s0", 0))
            for e_ in ax.get("ends", []):
                if not e_.get("ground") or not vp or not secs:
                    continue
                at0 = e_.get("s", 0) <= 0.01
                ss_ = [p_[0] if at0 else L_.length - p_[0] for p_ in vp]       # (from this end)
                zz_ = [p_[1] for p_ in vp]
                pairs_ = sorted(zip(ss_, zz_))
                reach_ = pairs_[-1][0]
                for (s1, z1), (s2, z2) in zip(pairs_, pairs_[1:]):
                    if z1 <= LANDING_Z_M < z2:
                        reach_ = s1 + (LANDING_Z_M - z1) / (z2 - z1) * (s2 - s1)
                        break
                sec_ = secs[0] if at0 else secs[-1]
                lanes_ = [(b_.get("t", 0.0), ((b_.get("width") or {}).get("value") or LANE_M)) for b_ in sec_.get("bands", []) if b_.get("type") == "lane"]
                if not lanes_ or reach_ <= 0.5:
                    continue
                t1, t2 = min(t - w / 2 for t, w in lanes_), max(t + w / 2 for t, w in lanes_)
                piece_ = substring(L_, 0.0, min(reach_, L_.length)) if at0 else substring(L_, max(L_.length - reach_, 0.0), L_.length)
                if piece_.geom_type == "LineString" and piece_.length > 0.5:
                    land_bands.append(band(piece_, t1, t2))
            # (and where the axis touches the ground in its middle, ground_at: the band on both sides of that point, out to where the deck
            # is LANDING_Z_M high; a1 at Avenue Princesse Grace kept a half-disc of the ground road's walking side, Kaveh 2026-10-17)
            from .bridge_profile import height as _hz
            for s_g in ax.get("ground_at", []) if vp and secs else []:
                sec_ = next((sc for sc in secs if sc["s0"] - 0.01 <= s_g <= sc["s1"] + 0.01), secs[0])
                lanes_ = [(b_.get("t", 0.0), ((b_.get("width") or {}).get("value") or LANE_M)) for b_ in sec_.get("bands", []) if b_.get("type") == "lane"]
                if not lanes_:
                    continue
                t1, t2 = min(t - w / 2 for t, w in lanes_), max(t + w / 2 for t, w in lanes_)
                lo_s, hi_s = s_g, s_g
                while lo_s > 0 and _hz(ax["vertical"], lo_s - 0.5) < LANDING_Z_M:
                    lo_s -= 0.5
                while hi_s < L_.length and _hz(ax["vertical"], hi_s + 0.5) < LANDING_Z_M:
                    hi_s += 0.5
                piece_ = substring(L_, max(lo_s, 0.0), min(hi_s, L_.length))
                if piece_.geom_type == "LineString" and piece_.length > 0.5:
                    land_bands.append(band(piece_, t1, t2))
    if land_bands:
        LB_ = shapely.union_all(land_bands)
        road_types = ROAD_T + ("crosswalk", "cycle crossing", "bus lane", "shoulder", "no parking", "bus zone", "island")
        for p_ in parts:
            if p_["type"] not in road_types and p_["geom"].intersects(LB_):
                p_["geom"] = poly(p_["geom"].difference(LB_))
        for u, k, s_, x in units:
            if not x.intersects(LB_):
                continue
            mine_ = [p_["geom"] for p_ in parts if p_["unit_id"] == u and p_["type"] in road_types]
            new_ = poly(LB_.intersection(x).difference(shapely.union_all(mine_) if mine_ else shapely.Polygon()))
            if new_.area > 0.5:
                pid[u] = pid.get(u, 0) + 1
                parts.append(dict(unit_id=u, part_id=f"{u}#{pid[u]}", level=LV, type="junction area" if k == "intersection" else "paved",
                                  source="urbanstyle", method="derived", ref="the ground under a bridge deck's lanes at its landing", geom=new_))
    # ---- the landing joint on a deck level (docs/design/spaces.md, "At a landing"): within LANDING_JOIN_M of a point where this level's
    # axes touch the ground, the walking side is roadway, so two ramps that come down to one ground road meet it as at a junction (a1 and
    # its ramp at Avenue Princesse Grace: the walking side filled the tip of their V, a half-disc; Kaveh 2026-10-17)
    if LV >= 1 and bridges:
        lv_r = dict(rows("SELECT osm_id, level_min FROM work.element WHERE type = 'road'"))
        joint_pts = []
        for pf in bridges:
            prof = json.load(open(pf))
            if prof.get("crs") and prof["crs"] != epsg:
                continue
            for ax in prof.get("axes", []):
                ls_ = [lv_r.get(int(w[1:])) for w in ax.get("ways", []) if lv_r.get(int(w[1:])) is not None]
                if not ls_ or max(set(ls_), key=ls_.count) != LV:
                    continue
                L_ = shapely.LineString([p_[:2] for p_ in ax["line"]["value"]])
                for s_j in [e_["s"] for e_ in ax.get("ends", []) if e_.get("ground")] + list(ax.get("ground_at", [])):
                    joint_pts.append(L_.interpolate(s_j))
        if joint_pts:
            JZ_ = shapely.union_all([q_.buffer(LANDING_JOIN_M) for q_ in joint_pts])
            road_types_j = ROAD_T + ("crosswalk", "cycle crossing", "bus lane", "shoulder", "no parking", "bus zone")
            for p_ in parts:
                if p_["type"] not in road_types_j and p_["geom"].intersects(JZ_):
                    p_["geom"] = poly(p_["geom"].difference(JZ_))
            for u, k, s_, x in units:
                if not x.intersects(JZ_):
                    continue
                mine_ = [p_["geom"] for p_ in parts if p_["unit_id"] == u and p_["type"] in road_types_j]
                new_ = poly(JZ_.intersection(x).difference(shapely.union_all(mine_) if mine_ else shapely.Polygon()))
                if new_.area > 0.3:
                    pid[u] = pid.get(u, 0) + 1
                    parts.append(dict(unit_id=u, part_id=f"{u}#{pid[u]}", level=LV, type="junction area" if k == "intersection" else "paved",
                                      source="urbanstyle", method="derived", ref="a deck road's landing joint: roadway where it meets the ground", geom=new_))
    # ---- on a deck, the walking side is sidewalk only where OSM maps a footway or a sidewalk; the rest of the deck beside the lanes is
    # shoulder, flat at the road's level (furnishing and frontage are a ground street's, beside its blocks: on Granville they covered
    # 2,158 m2 of one deck space and on Avenue de France stood as raised blocks; Kaveh 2026-10-17)
    if LV >= 1:
        # (a cycleway on the deck, as the Granville Connector: OSM's line at its width; its walking side is the cycle lane)
        cyc_ = shapely.union_all([g(w).buffer((wd or SW_HALF_M * 2) / 2, cap_style="flat") for wd, w in rows(f"""SELECT width_m, {m()}
                                  FROM work.element WHERE type = 'cycleway' AND level_min = {LV}""")] or [shapely.Polygon()])
        for p_ in parts:
            if p_["type"] in ("furnishing", "frontage", "verge", "sidewalk"):
                a_ = p_["geom"].area or 1.0
                on_cyc_ = p_["geom"].intersection(cyc_).area if not cyc_.is_empty else 0.0
                on_path_ = p_["geom"].intersection(sw_strips).area if not sw_strips.is_empty else 0.0
                p_["type"] = "cycle lane" if on_cyc_ > 0.5 * a_ else "sidewalk" if on_path_ > 0.5 * a_ else \
                    p_["type"] if p_["type"] == "sidewalk" else "shoulder"
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
    tick("the cut by the street and the write (rank 3)")
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
    service = [g(w) for (w,) in rows(f"""SELECT {m()} FROM work.element e WHERE type IN ('road', 'walkway') AND level_min = {LV}
                                       AND class = 'service' AND NOT {street_sql('e')}""")]
    if service and not kerb_all.is_empty:
        mouths = [q_.centroid for ln_ in service for q_ in shapely.get_parts(ln_.intersection(kerb_all.buffer(0.3))) if not q_.is_empty]
        if mouths:
            kerb_all = kerb_all.difference(shapely.union_all([pt_.buffer(ALLEY_HALF_M) for pt_ in mouths]))
    # no kerb along or across the line between two spaces: a kerb is the roadway's outer edge, never a cut (Kaveh, 2026-10-17)
    if not kerb_all.is_empty:
        geoms_ = [x for _, _, _, x in units if not x.is_empty]
        utree_ = shapely.STRtree(geoms_) if geoms_ else None
        shared = []
        for i_, a_ in enumerate(geoms_):
            for j_ in (utree_.query(a_.buffer(0.05)) if utree_ is not None else []):
                if j_ > i_:
                    l_ = a_.boundary.intersection(geoms_[j_].buffer(0.05))
                    if not l_.is_empty and l_.length > 0.1:
                        shared.append(l_)
        if shared:      # (only what runs along a cut, over 0.5 m: a kerb that crosses a cut stays whole)
            along_ = [q_ for q_ in shapely.get_parts(kerb_all.intersection(shapely.union_all(shared).buffer(0.1))) if q_.length >= 0.5]
            if along_:
                kerb_all = kerb_all.difference(shapely.union_all(along_).buffer(0.01))
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
        con.executemany(f"INSERT INTO work.unit (unit_id, kind, section_id, level, color, geometry) VALUES (?, ?, ?, {LV}, ?, {to_ll})", urows)
    if junction_rows:
        con.executemany("INSERT INTO work.junction (intersection_id, node_id, level, cluster_id) VALUES (?, ?, ?, ?)", junction_rows)
    if subrows:     # (width_m: the section's frame)
        con.executemany(f"""INSERT INTO work.subsection (subsection_id, section_id, level, class, width_m, oneway, length_m, "left", "right",
                            starts_at, left_extra, color, geometry) VALUES (?, ?, {LV}, ?, ?, ?, ?, ?, ?, ?, ?, '#e6194b', {to_ll})""",
                        [(a, b, c, d, e, f, h, i, j, sh, shapely.to_wkb(x)) for a, b, c, d, e, f, h, i, j, sh, x in subrows])
    if changes:     # (J4: every tag change along a section, with its class; the lanes as forward + backward in the section's direction)
        in_sec = lambda r_: f"{r_['f']}+{r_['b']}" if not r_["flip"] else f"{r_['b']}+{r_['f']}"
        con.executemany(f"""INSERT INTO work.change (section_id, level, subsection_a, subsection_b, way_a, way_b, lanes_a, lanes_b, width_a, width_b,
                            class, note, geometry) VALUES (?, {LV}, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {to_ll})""",
                        [(c_["sid"], c_["a"]["sub"], c_["b"]["sub"], f"w{c_['a']['oid']}", f"w{c_['b']['oid']}", in_sec(c_["a"]), in_sec(c_["b"]),
                          round(c_["a"]["kl"] - c_["a"]["kr"], 2), round(c_["b"]["kl"] - c_["b"]["kr"], 2), c_["cls"], c_["note"], shapely.to_wkb(c_["pt"]))
                         for c_ in changes])
    if parts:
        con.executemany(f"""INSERT INTO work.part (unit_id, part_id, level, type, arm, direction, lane, lane_id, width_m, width_source, width_method,
                            length_m, source, method, ref, position_source, position_method, position_ref, road, road_class, road_lanes, oneway, rule,
                            holds, geometry) VALUES (?, ?, {LV}, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {to_ll})""",
                        [(p["unit_id"], p["part_id"], p["type"], p.get("arm"), p.get("direction"), p.get("lane"), p.get("lane_id"), p.get("width_m"),
                          p.get("width_source") or "urbanstyle", p.get("width_method"), round(p["geom"].length / 2, 1), p.get("source") or "urbanstyle",
                          p.get("method") or "derived", p.get("ref"), p.get("position_source"), p.get("position_method"), p.get("position_ref"),
                          p.get("road"), p.get("road_class"), p.get("road_lanes"), p.get("oneway"), p.get("rule"), p.get("holds"), shapely.to_wkb(p["geom"])) for p in parts])
    if marks:
        con.executemany(f"""INSERT INTO work.mark (unit_id, level, type, length_m, width_m, width_source, width_method, source, method, ref, geometry)
                            VALUES (?, {LV}, ?, ?, ?, 'urbanstyle', 'chosen', ?, ?, ?, {to_ll})""",
                        [(u, t, round(x.length, 1), LINE.get(t), s_, me, rf, shapely.to_wkb(x)) for u, t, x, s_, me, rf in marks])
    # a crossing is one object in one space: the loser's piece of it, cut for it before the spaces were decided (8b, each owner it
    # touched), goes where the winner's part covers it (Boulevard de Suisse: a subsection's parts outgrew its space by the crosswalk the
    # intersection holds, check U8; Monaco 2026-10-16)
    con.execute(f"""DELETE FROM work.part WHERE level = {LV} AND type IN ('crosswalk', 'cycle crossing') AND part_id IN (
        SELECT p.part_id FROM work.part p JOIN work.unit u USING (unit_id)
        WHERE p.level = {LV} AND p.type IN ('crosswalk', 'cycle crossing')
          AND ST_Area(ST_Intersection(p.geometry, u.geometry)) < 0.5 * ST_Area(p.geometry)
          AND EXISTS (SELECT 1 FROM work.part o WHERE o.level = {LV} AND o.type = p.type AND o.unit_id <> p.unit_id
                      AND ST_Area(ST_Intersection(o.geometry, p.geometry)) > 0.9 * ST_Area(p.geometry)))""")
    tick("the kerb line and the end (rank 6)")
    return dict(sections=len(runs), intersections=len(junctions), parts=len(parts), marks=len(marks))
