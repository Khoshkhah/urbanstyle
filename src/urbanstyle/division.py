"""The street divided between the blocks (docs/design/blocks.md, steps 2-5) and the inside of each piece (layers 1-2 of
docs/design/space-layers.md), at level 0. It replaces the level-0 spaces of `spaces.py` and their parts of `parts.py`.

    shares        every point of the street (the area less the blocks) belongs to its nearest block; the outside of the area is one
                  more block (-1), except across a street opening (where a street leaves the area)
    middle line   where two shares meet
    section       where a line square to the middle line meets block a on one side and block b on the other, each on a side running
                  along it (within FACE_DEG): cut at two positions ARM_M inside the ends of that stretch (none at the area's edge);
                  at least as long as the street is wide. Id `s<level>-<block a>~<block b>`
    intersection  the street left: the open space between the corners and ARM_M into each arm. Id `i<level>-<smallest OSM node in it>`
    subsection    a section cut across where its carriageways or lanes change, for SUB_MIN_M at least. Id `<section>/<k>`
    inside        each subsection in strips parallel to its axis (the middle line): pedestrian realm, kerb, roadway (its lanes, one
                  whole lane each, a shoulder, a median between carriageways), kerb, pedestrian realm. Each intersection: one junction
                  area, and a pedestrian corner at each block corner where the kerbs of its two arms meet (rounded by KERB_RADIUS_M)
    marks         kerbs, lane lines, centre lines, stop lines, and zebra bars where OSM maps a crossing over the roadway

Every value no source gives is urbanstyle's own, chosen (docs/design/provenance.md).
"""
import json
import math
import os
import statistics
import re

STEP_M, SAMPLE_M, RAY_M, FACE_DEG = 1.0, 0.5, 80.0, 30.0   # shares: points along outlines; facing tested every; how far; along within
MAX_POINTS = 60000       # the shares from at most this many points
OPENING_M = 40.0         # an edge of the area crossing a street, shorter than this, is a street opening: the outside is no neighbour there
ARM_M = 3.0              # an intersection reaches into each arm past the block corner (its crosswalk, stop line)
SUB_MIN_M = 12.0         # a subsection is at least this long: changes closer together are one cut
LANES_MIN_M = 5.0        # ... but where OSM's lane count changes (a turn lane before a junction), at least this long
LANE_M = 3.25            # a lane's width where nothing measures it
CORNER_ROAD_M = 2.0      # a road's line running this far through an intersection's pedestrian corner: the corner is wrong there
LANE_RANGE = (2.75, 4.0)     # a lane measured kerb to kerb, if it falls in this range; else LANE_M and a shoulder
SIDEWALK_HALF_M = 1.0    # a sidewalk is drawn along its middle: the kerb is about this far before its line
OBJECT_BACK_M = 0.5      # a tree or a pole stands at least this far behind the kerb
MIN_REALM_M = 1.5        # the pedestrian realm keeps at least this between the kerb and the block
MEDIAN_MIN_M = 1.0       # carriageways farther apart than this have a median between them
KERB_RADIUS_M = 4.0      # a corner's kerb is rounded by this
TRAVEL_M = (3.0, 3.7)    # the fit's widths (chosen): a travel lane, a parking lane, a bike lane; the gutter at each kerb
PARK_M = (2.2, 2.6)
BIKE_M = (1.5, 2.0)
GUTTER_M = 0.3
JOIN_M = 1.0             # at a joint, a lane shifted sideways by less than this still matches its continuation (join_lanes)
JOIN_EDGE_M = 2.0        # two sections whose spaces share this much edge (no intersection between them) meet at a joint
JOIN_COS = 0.85          # ... when their axes there are this near in line (cos of the angle)
FOLLOW_MAX_M = 30.0      # a section's axis runs on along its main road past the middle between the blocks by at most this
FOLLOW_MIN_M = 5.0       # ... where the middle between the blocks stops at least this short of the section's end
BASIN_BACK_M = 0.3       # a catch basin sits in the gutter: the kerb is this far behind it
OBJ_KERB_M = 0.4         # a pole, a tree, a meter stands at least this far behind the kerb
SHOULDER_EDGE_M = 0.3    # every carriageway keeps a shoulder this wide at each edge (the gutter); more where the lanes leave room
FURNISH_M = (1.0, 0.6, 2.5)  # the pedestrian realm's buffer (furniture) zone at the kerb: where nothing stands in it; at least; at most
CLEAR_M = 1.8            # the clear path, where nothing measures it
FRONTAGE_MIN_M = 0.75    # a frontage or buffer zone narrower than this is the clear path's
ROADWAY = ("lane", "shoulder", "parking", "bus zone", "cycle lane", "junction area")
PIECE_MIN_M2 = 5.0       # a strip smaller than this (in a very short subsection) joins the neighbouring strip it shares the most edge with
STOP_BACK_M = 1.0        # a stop line stands this far before the section's end at an intersection
BARRIER_W_M = 0.5        # a barrier between two carriageways through a junction (chosen)
BARRIER_SPAN_M = 60.0    # ... joining two islands at most this far apart
STREET = ("motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street", "pedestrian")
from .parts import (ARROW_M, BUS_ZONE_M, CROSS_ON_M, CROSSWALK_M, DRIVEWAY_M, GTFS_M, LINE, SAME_CROSSING_M,  # noqa: E402  (as
                    STOP_KERB_M, ZEBRA_BAR_M, ZEBRA_GAP_M)                                                  #  parts.py paints them)                                            #  paints it and the dashboard draws it)
TURN = {"left": "left", "slight_left": "left", "sharp_left": "left", "through": "straight", "right": "right", "slight_right": "right",
        "sharp_right": "right"}    # OSM's turn:lanes values, as the heads of a painted arrow
ENTRANCE_M = 15.0        # a parking entrance this close to a car park and to the street opens the kerb there
COLORS = {"subsection": "#94a3b8", "intersection": "#fbbf24"}
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

def build(con, epsg):
    import duckdb
    import numpy as np
    import shapely
    import shapely.affinity
    from shapely.ops import substring

    m = lambda col="geometry": f"ST_AsWKB(ST_Transform({col}, 'EPSG:4326', '{epsg}', always_xy := true))"
    g = lambda w: shapely.make_valid(shapely.from_wkb(bytes(w)))
    poly = lambda x: shapely.union_all([p for q in shapely.get_parts(x) for p in shapely.get_parts(q) if p.geom_type == "Polygon"]
                                       or [shapely.Polygon()])      # (a collection can hold a multipolygon)

    def rows(sql, args=None):
        try:
            return con.execute(sql, args or []).fetchall()
        except (duckdb.CatalogException, duckdb.BinderException):     # a database without that layer or column
            return []

    blocks = [(i, g(w)) for i, w in rows(f"SELECT block_id, {m()} FROM space.block WHERE level = 0 ORDER BY block_id")]
    area = rows(f"SELECT {m()} FROM space.area")
    if not blocks or not area:
        return 0
    box = g(area[0][0])
    box_edge = box.boundary        # (the area's edge: of each part, when the area has several, Monaco)
    bid = [i for i, _ in blocks]
    bgeo = [x for _, x in blocks]
    street = poly(box.difference(shapely.union_all(bgeo), grid_size=0.01))
    short = lambda k: "edge" if k == -1 else bid[k][3:] if bid[k].startswith("b0-") else bid[k]

    # ---- shares and middle lines
    openings = shapely.union_all([x for x in shapely.get_parts(shapely.line_merge(box_edge.intersection(street.buffer(0.01))))
                                  if x.length < OPENING_M] or [shapely.Point()]).buffer(0.05)
    pts, owner, seen = [], [], set()
    edge_near = box_edge.intersection(shapely.union_all(bgeo).buffer(2 * RAY_M))
    rings = [(k, b.exterior) for k, b in enumerate(bgeo)] + [(-1, x) for x in shapely.get_parts(shapely.line_merge(edge_near))
                                                            if x.geom_type == "LineString"]
    step = max(STEP_M, sum(r.length for _, r in rings) / MAX_POINTS)     # (a vast area: fewer points, coarser shares)
    for k, ring in rings:
        for i in range(max(4, int(ring.length / step))):
            q = ring.interpolate(i * ring.length / max(4, int(ring.length / step)))
            key = (round(q.x, 1), round(q.y, 1))
            if key in seen or (k == -1 and q.within(openings)):
                continue
            seen.add(key)
            pts.append(q)
            owner.append(k)
    cells = shapely.get_parts(shapely.voronoi_polygons(shapely.MultiPoint(pts), extend_to=box.buffer(200), ordered=True))
    regions = {}
    for c_, k in zip(cells, owner):
        regions.setdefault(k, []).append(c_)
    def merge(v):       # a block's cells are a coverage (they meet edge to edge): joined as one
        try:
            return shapely.coverage_union_all(v)
        except shapely.errors.GEOSException:
            return shapely.union_all([c.buffer(0.001) for c in v])
    regions = {k: merge(v).intersection(street) for k, v in regions.items()}
    rkeys = list(regions)
    rtree = shapely.STRtree([regions[k] for k in rkeys])
    mids = {}
    for a in rkeys:
        for j in rtree.query(regions[a].buffer(0.1)):
            b = rkeys[j]
            key = tuple(sorted((a, b)))
            if a == b or key in mids:
                continue
            x = regions[a].boundary.intersection(regions[b].boundary.buffer(0.05)).intersection(street.buffer(0.01))
            x = [p for p in shapely.get_parts(shapely.line_merge(x)) if p.geom_type == "LineString"]
            if x:   # pieces whose ends are within 5 cm are one line (rounding gaps where shares meet)
                x = shapely.line_merge(shapely.set_precision(shapely.union_all(x), 0.05))
                if x.length > 1:
                    mids[key] = x
    targets = [(k, b) for k, b in enumerate(bgeo)] + [(-1, box_edge)]
    ttree = shapely.STRtree([t for _, t in targets])
    cosf = math.cos(math.radians(FACE_DEG))

    def tangent(line, s):
        a, b = line.interpolate(max(s - 1, 0)), line.interpolate(min(s + 1, line.length))
        dx, dy = b.x - a.x, b.y - a.y
        h = (dx * dx + dy * dy) ** .5 or 1
        return dx / h, dy / h

    def curve(pa, ha, pb, hb, pull=0.0, to=None):
        """A quadratic curve from pa (heading ha) to pb (heading hb), its control where the two headings meet (parts.py), moved `pull` of
        the way toward the point `to`."""
        cr = ha[0] * hb[1] - ha[1] * hb[0]
        dx, dy = pb[0] - pa[0], pb[1] - pa[1]
        u, v = ((dx * hb[1] - dy * hb[0]) / cr, (ha[0] * dy - ha[1] * dx) / cr) if abs(cr) > 0.2 else (-1, -1)
        q = (pa[0] + u * ha[0], pa[1] + u * ha[1]) if u > 0 and v > 0 else ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)
        if to is not None:
            q = (q[0] + pull * (to[0] - q[0]), q[1] + pull * (to[1] - q[1]))
        return shapely.LineString([((1 - t) ** 2 * pa[0] + 2 * (1 - t) * t * q[0] + t * t * pb[0],
                                    (1 - t) ** 2 * pa[1] + 2 * (1 - t) * t * q[1] + t * t * pb[1]) for t in [i / 12 for i in range(13)]])

    def across(line, s):
        """At s along a line: the first thing met square to it on its left (1) and its right (-1): (owner or None, point, distance)."""
        p = line.interpolate(s)
        ux, uy = tangent(line, s)
        out = {}
        for sg in (1, -1):
            ray = shapely.LineString([(p.x, p.y), (p.x - sg * uy * RAY_M, p.y + sg * ux * RAY_M)])
            best = None
            for t in ttree.query(ray):
                ring = targets[t][1].exterior if targets[t][0] >= 0 else targets[t][1]
                x = ray.intersection(ring)
                for q in shapely.get_parts(x):
                    if q.is_empty:
                        continue
                    q = q if q.geom_type == "Point" else shapely.Point(q.coords[0])
                    if best is None or p.distance(q) < best[2]:
                        bt = ring.project(q)
                        e0, e1 = ring.interpolate(max(bt - 1, 0)), ring.interpolate(min(bt + 1, ring.length))
                        ex, ey = e1.x - e0.x, e1.y - e0.y
                        along = abs(ex * ux + ey * uy) / ((ex * ex + ey * ey) ** .5 or 1)
                        best = (targets[t][0] if along >= cosf else None, q, p.distance(q))
            out[sg] = best
        return out

    # ---- sections: two cuts per facing stretch
    secs = []       # dict(a, b, line, c0, c1, e0, e1, left, right): left / right = the block on the line's left / right
    cuts = []       # (line, section index, end 0 / 1)
    for (a, b), mline in mids.items():
        for line in shapely.get_parts(mline):
            if line.geom_type != "LineString":
                continue
            ss = [i * SAMPLE_M for i in range(int(line.length / SAMPLE_M) + 1)]
            ok = []
            for sv in ss:
                h = across(line, sv)
                ok.append(all(h.values()) and None not in (h[1][0], h[-1][0]) and {h[1][0], h[-1][0]} == {a, b})
            runs, start, prev = [], None, None
            for sv, v in zip(ss + [None], ok + [False]):
                if v and start is None:
                    start = sv
                if not v and start is not None:
                    runs.append((start, prev))
                    start = None
                prev = sv
            for s0, s1 in runs:
                e0 = line.interpolate(s0).distance(box_edge) < 2.0
                e1 = line.interpolate(s1).distance(box_edge) < 2.0
                c0, c1 = s0 + (0 if e0 else ARM_M), s1 - (0 if e1 else ARM_M)
                hm = across(line, (c0 + c1) / 2)
                width = hm[1][1].distance(hm[-1][1]) if all(hm.values()) else 0
                if c1 - c0 < 1 or (c1 - c0 < width and not (e0 or e1)):     # shorter than wide: part of the junction
                    continue
                left = hm[1][0]
                secs.append(dict(a=a, b=b, line=line, c0=c0, c1=c1, e0=e0, e1=e1, left=left, right=b if left == a else a))
                for cs_, edge, end in ((c0, e0, 0), (c1, e1, 1)):
                    if not edge:
                        h = across(line, cs_)
                        cuts.append((shapely.LineString([h[1][1].coords[0], h[-1][1].coords[0]]), len(secs) - 1, end))

    def extend(x, e):
        c = list(x.coords)
        out = lambda p, q: (p[0] + (p[0] - q[0]) / (math.dist(p, q) or 1) * e, p[1] + (p[1] - q[1]) / (math.dist(p, q) or 1) * e)
        return shapely.LineString([out(c[0], c[1])] + c + [out(c[-1], c[-2])])

    pieces = [x for x in shapely.get_parts(shapely.polygonize(list(shapely.get_parts(shapely.union_all(
        [street.boundary] + [extend(c, 0.05) for c, _, _ in cuts]))))) if x.representative_point().within(street) and x.area > 0.5]
    secgeo, rest = {}, []
    for x in pieces:
        hit = [i for i, s in enumerate(secs) if x.distance(s["line"].interpolate((s["c0"] + s["c1"]) / 2)) < 0.01]
        if hit:
            secgeo[hit[0]] = x
        else:
            rest.append(x)
    inter = []
    for x in rest:      # a piece meeting fewer than three sections is a street's end (at the area's edge): it joins its section
        touch = [(secgeo[i].boundary.intersection(x.boundary.buffer(0.05)).length, i) for i in secgeo if secgeo[i].distance(x) < 0.05]
        if 0 < len(touch) < 3:
            i = max(touch)[1]
            secgeo[i] = poly(shapely.union_all([secgeo[i], x], grid_size=0.01))
        else:
            inter.append(x)

    # ---- roads: carriageways (their offset, width, lanes along / against) for the subsections
    lanes = {}
    for oid, rev, ln in rows("SELECT osm_id, is_reverse, median(lanes) FROM osm.driving.edges WHERE lanes IS NOT NULL GROUP BY 1, 2"):
        lanes[(oid, bool(rev))] = int(ln)
    from .corrections import SOURCE as CORR_SRC, lanes as corrected, per_direction
    CORR = corrected()      # corrections to OSM's lane counts replace the driving network's
    for oid, (tg_c, _) in CORR.items():
        f_c, b_c = per_direction(tg_c, (oid, True) not in lanes)
        lanes[(oid, False)] = f_c
        if b_c:
            lanes[(oid, True)] = b_c
    # the streets' roads: at level 0, and on a deck at level 1 where nothing at ground level passes under it (works, not a bridge), as
    # for the blocks: such a deck is the street at ground level
    # (a corrected way's carriageway is at least as wide as its corrected lanes: its width came from OSM's count, before the correction)
    cw_min = lambda oid, wd: max(wd or 0.0, LANE_M * sum(per_direction(CORR[oid][0], (oid, True) not in lanes))) if oid in CORR else wd
    cand = [(oid, n, cl, bool(ow), cw_min(oid, wd), src, dst, g(w), lv) for oid, n, cl, ow, wd, src, dst, w, lv in rows(f"""SELECT osm_id, name, class,
               coalesce(oneway, false), width_m, src, dst, {m()}, level_min FROM space.element WHERE type IN ('road', 'walkway')
               AND level_min IN (0, 1) AND replace(class, '_link', '') IN {STREET}""")]
    ground_lines = [c[7] for c in cand if c[8] == 0] + [g(w) for (w,) in rows(f"SELECT {m()} FROM space.element WHERE type = 'rail' AND level_min = 0")]
    gl_tree = shapely.STRtree(ground_lines) if ground_lines else None
    roads, decks = [], []
    for c in cand:
        if c[8] == 0 or gl_tree is None or not any(ground_lines[k].crosses(c[7]) for k in gl_tree.query(c[7])):
            roads.append(c[:8])
            if c[8] == 1:
                decks.append(c[7])
    road_tree = shapely.STRtree([r[7] for r in roads])
    way_lines = {}       # each OSM way's line, its pieces joined
    for r in roads:
        way_lines.setdefault(r[0], []).append(r[7])
    way_lines = {k: shapely.line_merge(shapely.union_all(v)) for k, v in way_lines.items()}

    # (a walkway of a street's class is a road only buses or bikes use: a carriageway above, not a sidewalk)
    walk_rows = rows(f"""SELECT osm_id, {m()} FROM space.element WHERE type = 'walkway' AND level_min = 0 AND coalesce(subtype, '') <> 'crossing'
                           AND replace(coalesce(class, ''), '_link', '') NOT IN {STREET}""")
    walks, walk_ids = [g(w) for _, w in walk_rows], [f"w{o}" for o, _ in walk_rows]
    walk_tree = shapely.STRtree(walks) if walks else None
    crossings = [(oid, typ, g(w)) for oid, typ, w in rows(f"""SELECT osm_id, type, {m()} FROM space.element WHERE type IN ('walkway', 'cycleway')
                                                  AND level_min = 0 AND subtype = 'crossing'""")]
    unmarked = {oid for (oid,) in rows("""SELECT osm_id FROM osm.raw.ways WHERE tags['crossing'] = 'unmarked' OR tags['crossing:markings'] = 'no'""")}
    cross_pts = [(oid, cl, g(w)) for oid, cl, w in rows(f"""SELECT object_id, class, {m()} FROM space.object WHERE level = 0
                                                         AND class IN ('crossing.zebra', 'crossing.signalised')""")]
    # zebra bars only where OSM's crossing:markings says so (zebra, ladder, yes) or says nothing: a cycle crossing of dots, pictograms
    # and a green surface (n3438718321, the Granville Connector over Fir Street x West 5th Avenue) has none
    zebra_ok = lambda mk: mk is None or bool({"zebra", "ladder", "yes"} & set(str(mk).split(";")))
    unmarked |= {oid for oid, mk in rows("SELECT osm_id, tags['crossing:markings'] FROM osm.raw.ways WHERE tags['crossing:markings'] IS NOT NULL")
                 if not zebra_ok(mk)}
    node_mk = {f"n{n}": mk for n, mk in rows("SELECT osm_id, tags['crossing:markings'] FROM osm.raw.nodes WHERE tags['crossing:markings'] IS NOT NULL")}
    cross_pts = [c for c in cross_pts if zebra_ok(node_mk.get(str(c[0])))]
    # roads inside the blocks (alleys, driveways, parking aisles) and OSM's parking entrances: where the street opens to them
    services = [(oid, wd, g(w)) for oid, wd, w in rows(f"""SELECT osm_id, width_m, {m()} FROM space.element WHERE type = 'road'
                                                         AND level_min = 0 AND replace(class, '_link', '') NOT IN {STREET}""")]
    # ... and OSM's driveways and parking aisles, which space.element leaves out (duckOSM's driving network has them)
    services += [(oid, wd, g(w)) for oid, wd, w in rows(f"""SELECT e.osm_id, any_value(try_cast(w.tags['width'] AS DOUBLE)),
                     ST_AsWKB(ST_Union_Agg(ST_Transform(e.geometry, 'EPSG:4326', '{epsg}', always_xy := true))) FROM osm.driving.edges e
                     JOIN osm.raw.ways w USING (osm_id) WHERE w.tags['service'] IN ('driveway', 'parking_aisle')
                     AND coalesce(w.tags['layer'], '0') = '0' AND coalesce(w.tags['tunnel'], 'no') = 'no' GROUP BY e.osm_id""")]
    services.sort(key=lambda r: str(r[0]))      # (one order in every build: the driveways' numbers, #12, #13, came out swapped)
    lots = [g(w) for (w,) in rows(f"SELECT {m()} FROM space.lot")]
    parcel_g = [g(w) for (w,) in rows(f"SELECT {m()} FROM space.parcel")]
    parcel_u = shapely.union_all(parcel_g) if parcel_g else None
    # bus stops: OSM's, each with the timetable's stop of its number (GTFS stop_code = OSM ref), and the timetable's stops OSM lacks
    from . import gtfs as gt
    stops = [dict(id=f"n{o}" if str(o).isdigit() else str(o), pt=g(w), tags=json.loads(a or "{}"), tt=None, source="osm")
             for o, w, a in rows(f"SELECT object_id, {m()}, attrs::VARCHAR FROM space.object WHERE level = 0 AND class = 'transit.stop'")]
    (path_,) = con.execute("SELECT path FROM duckdb_databases() WHERE database_name = current_database()").fetchone()
    gtfs_file = path_[:-len(".space.duckdb")] + ".gtfs.json" if path_ and path_.endswith(".space.duckdb") else None
    tt_all = json.load(open(gtfs_file)) if gtfs_file and os.path.exists(gtfs_file) else {}
    by_ref = {st["tags"].get("ref"): st for st in stops if st["tags"].get("ref")}
    for code, tt in tt_all.items():
        (w,) = con.execute(f"SELECT ST_AsWKB(ST_Transform(ST_Point(?, ?), 'EPSG:4326', '{epsg}', always_xy := true))", [tt["lon"], tt["lat"]]).fetchone()
        pt = g(w)
        st = by_ref.get(tt.get("stop_code") or code)
        if st is not None:
            st["tt"], st["source"] = tt, "osm+gtfs"
        elif not any(o["pt"].distance(pt) <= GTFS_M for o in stops):
            stops.append(dict(id=f"gtfs:{tt['stop_id']}", pt=pt, tags={"name": tt["name"], "ref": tt.get("stop_code")}, tt=tt, source="gtfs"))
    entrances = [(oid, g(w)) for oid, w in rows(f"SELECT object_id, {m()} FROM space.object WHERE level = 0 AND class = 'access.parking_entrance'")]

    obj_rows = rows(f"SELECT object_id, source, {m()} FROM space.object WHERE level = 0")
    objs, obj_ids = [g(w) for _, _, w in obj_rows], [(str(o), s_) for o, s_, _ in obj_rows]
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
    def cid(name, pr):
        """A city feature's id, as ref: its own id where it has one, else its position."""
        k = {"public-trees": "asset_id", "parking-meters": "meter_id", "bikeways": "object_id", "sidewalk-condition-rating": "object_id"}.get(name)
        if k and pr.get(k) is not None:
            return f"{name}:{pr[k]}"
        if name == "street-lighting-poles":
            return f"{name}:{pr.get('block_number')}-{pr.get('node_number')}"
        pt = pr.get("geo_point_2d") or {}
        return f"{name}@{pt.get('lat', 0):.6f},{pt.get('lon', 0):.6f}"
    basin_rows = [(cid("sewer-catch-basins", pr), x) for pr, x in city_geoms("sewer-catch-basins")]
    behind_rows = [(cid(n, pr), x) for n in ("street-lighting-poles", "public-trees", "parking-meters") for pr, x in city_geoms(n)]  # behind the kerb
    meter_rows = [(cid("parking-meters", pr), x) for pr, x in city_geoms("parking-meters")]
    cwalk_rows = [(cid("sidewalk-condition-rating", pr), x) for pr, gm in city_geoms("sidewalk-condition-rating") for x in shapely.get_parts(gm)
                  if x.geom_type == "LineString"]
    basins, behind, meters, city_walks = ([x for _, x in r_] for r_ in (basin_rows, behind_rows, meter_rows, cwalk_rows))
    bikeways = [(pr, x) for pr, x in city_geoms("bikeways") if any(k in str(pr.get("bikeway_type") or "") for k in ("Painted", "Protected", "Separated"))]
    bike_ids = [cid("bikeways", pr) for pr, _ in bikeways]
    tree_of = lambda xs: shapely.STRtree(xs) if xs else None
    basin_t, behind_t, meter_t, cwalk_t = tree_of(basins), tree_of(behind), tree_of(meters), tree_of(city_walks)
    bike_t = tree_of([x for _, x in bikeways])
    osm_tags = {oid: dict(t or {}) for oid, t in rows("SELECT osm_id, tags FROM osm.raw.ways WHERE osm_id IN (SELECT DISTINCT osm_id FROM space.element "
                                                     "WHERE type IN ('road', 'walkway') AND level_min IN (0, 1))")}
    for oid, (tg_c, _) in CORR.items():       # (and their tags OSM's)
        if oid in osm_tags:
            osm_tags[oid].update(tg_c)
    otree = shapely.STRtree(objs) if objs else None

    def objects_in(ax, Q, sg):
        """The street objects standing in Q on one side of the axis: [(offset (left +), object id, source)]."""
        out = []
        for k in (otree.query(Q) if otree is not None else []):
            o = objs[k]
            if not Q.contains(o):
                continue
            q = ax.interpolate(ax.project(o))
            ux, uy = tangent(ax, ax.project(o))
            t = (o.x - q.x) * -uy + (o.y - q.y) * ux
            if t * sg > 0:
                out.append((t, *obj_ids[k]))
        return out

    def lanes_of(r, along):
        """(lanes going along the axis, lanes going against it) of road r, `along` whether the road's own direction is the axis's."""
        oid, n, cl, ow, wd = r[:5]
        f, bk = lanes.get((oid, False)), lanes.get((oid, True))
        tg_ = osm_tags.get(oid, {})
        if f is None and bk is None and tg_:     # not in the driving network (a road only for buses): its own OSM tags
            num = lambda k: int(tg_[k]) if str(tg_.get(k, "")).isdigit() else None
            ow = ow or tg_.get("oneway") in ("yes", "true", "1", "-1")
            f, bk = num("lanes:forward"), num("lanes:backward")
            if ow and f is None:
                f = num("lanes")
            if tg_.get("oneway") == "-1":        # one way against the way's own direction
                f, bk, ow = 0, f or 1, False
                return (f, bk) if along else (bk, f)
        tot = max(1, round((wd or LANE_M * 2) / LANE_M))
        if ow:
            f, bk = f or tot, 0
        else:
            f, bk = f or max(1, tot // 2), bk or max(1, tot - tot // 2)
        return (f, bk) if along else (bk, f)

    def profile(axis, P, s):
        """The carriageways crossed by the line square to the axis at s, left to right of nothing: [(offset, width, along, against, road)]."""
        p = axis.interpolate(s)
        ux, uy = tangent(axis, s)
        cross = shapely.LineString([(p.x - uy * RAY_M, p.y + ux * RAY_M), (p.x + uy * RAY_M, p.y - ux * RAY_M)]).intersection(P)
        out = []
        for k in road_tree.query(cross):
            r = roads[k]
            x = r[7].intersection(cross)
            if x.is_empty or x.geom_type != "Point":
                continue
            t = (x.x - p.x) * -uy + (x.y - p.y) * ux       # + left of the axis
            rt = r[7].project(x)
            rx, ry = tangent(r[7], rt)
            if abs(rx * ux + ry * uy) < cosf:              # a road crossing the section, not running along it
                continue
            fw = rx * ux + ry * uy > 0
            al, ag = lanes_of(r, fw)
            out.append((t, r[4] or (al + ag) * LANE_M, al, ag, r, fw))
        return sorted(out, key=lambda c: c[0])

    def offset_band(axis, t1, t2, P, margin=60.0):
        """The part of P between offsets t1 and t2 (left +) of the axis, run on past its ends."""
        ax = extend(axis, margin)
        side = lambda d: ax.buffer(d, single_sided=True, join_style="mitre") if abs(d) > 1e-6 else shapely.Polygon()   # 0 .. d
        if t1 >= 0:
            band = side(t2).difference(side(t1))
        elif t2 <= 0:
            band = side(t1).difference(side(t2))
        else:
            band = shapely.union_all([side(t2), side(t1)])
        return poly(shapely.make_valid(band).intersection(P, grid_size=0.01))

    def line_at(axis, t, P, width):
        """A strip along the axis at offset t, inside P, `width` wide."""
        x = extend(axis, 60.0).offset_curve(t).intersection(P)
        return poly(x.buffer(width / 2, cap_style="flat")) if not x.is_empty and x.length > 0.5 else None

    def lines(x):
        """The lines of x, merged (a painted line is stored as its middle line, drawn at its width: parts.LINE)."""
        ls = [p for p in shapely.get_parts(x) if p.geom_type == "LineString" and p.length > 0.05]
        return shapely.line_merge(shapely.union_all(ls)) if ls else None

    units, parts, marks, cut_rows, sub_rows, widths, junction = [], [], [], [], [], [], []
    section_ids = {}
    for i in sorted(secgeo, key=lambda i: (short(secs[i]["left"]), short(secs[i]["right"]))):
        s = secs[i]
        base = f"s0-{min(short(s['left']), short(s['right']))}~{max(short(s['left']), short(s['right']))}"
        # (another section between the same blocks: .2, .3, ... the next number not taken; a block's own id can end in .2 too, and
        # two sections had one id: Monaco's s0-edge~w4224972r.2, 2026-10-13)
        sid, k = base, 1
        while sid in section_ids.values():
            k += 1
            sid = f"{base}.{k}"
        section_ids[i] = sid

    def straight(line):
        c = line.coords
        chord = shapely.LineString([c[0], c[-1]])
        return chord if max(chord.distance(shapely.Point(p)) for p in c) < 1.0 else line.simplify(0.5)

    def follow_road(axis, P):
        """The axis run on past each end along the OSM line of the section's main road (the road with the most length in P), moved to start
        at that end, to the edge of P: where a block steps back, the middle between the blocks stops short of the section's end, and a
        straight run past it leaves the road where the road bends."""
        rs = [roads[k] for k in road_tree.query(P)]
        best = max(rs, key=lambda r: r[7].intersection(P).length, default=None)
        if best is None or best[7].intersection(P).length < 5:
            return axis
        cs = list(axis.coords)
        for end in (0, 1):
            E = shapely.Point(cs[-1] if end else cs[0])
            A = shapely.Point(cs[-2] if end else cs[1])
            part = min(shapely.get_parts(way_lines[best[0]]), key=lambda q: q.distance(E))
            sq = part.project(E)
            Qp = part.interpolate(sq)
            if Qp.distance(E) > RAY_M:
                continue
            ox, oy = E.x - A.x, E.y - A.y
            rx, ry = tangent(part, sq)
            fwd = rx * ox + ry * oy > 0                      # the road's own direction is the outward one
            rest = substring(part, sq, min(sq + FOLLOW_MAX_M, part.length)) if fwd else substring(part, max(sq - FOLLOW_MAX_M, 0.0), sq).reverse()
            if rest.geom_type != "LineString" or rest.length < 1:
                continue
            fx, fy = tangent(rest, 0.5)
            if (fx * ox + fy * oy) / (math.hypot(ox, oy) or 1) < 0.5:      # it must run on outward, not back along the section
                continue
            moved = shapely.affinity.translate(rest, E.x - Qp.x, E.y - Qp.y)
            piece = next((x for x in shapely.get_parts(moved.intersection(P.buffer(0.01)))
                          if x.geom_type == "LineString" and not x.is_empty and shapely.Point(x.coords[0]).distance(E) < 0.5), None)
            if piece is None or piece.length < FOLLOW_MIN_M:      # (an oblique end at an intersection: the straight run is enough)
                continue
            ext = list(piece.coords)[1:]
            cs = cs + ext if end else ext[::-1] + cs
        return shapely.LineString(cs)

    sec_axis = {}       # section index -> (its axis, its polygon)
    sub_axis = {}       # subsection id -> (axis, left block, right block, section index, its polygon)
    sub_span = {}       # subsection id -> (start, end) along its section's axis
    for i, sid in section_ids.items():
        s, P = secs[i], secgeo[i]
        line = s["line"]
        a0 = 0.0 if s["e0"] else s["c0"]
        a1 = line.length if s["e1"] else s["c1"]
        axis = substring(line, a0, a1)
        if axis.geom_type != "LineString" or axis.length < 1:
            continue
        axis = follow_road(straight(axis), P)
        sec_axis[i] = (axis, P)
        # where its carriageways change (for SUB_MIN_M at least): the subsections
        keys = []
        for k in range(int(axis.length // 2) + 1):
            sv = min(k * 2.0, axis.length)
            pr = profile(axis, P, sv)
            keys.append((sv, tuple((round(c[0] / 2), c[2], c[3]) for c in pr)))
        runs = []
        for sv, key in keys:
            if runs and runs[-1][2] == key:
                runs[-1][1] = sv
            else:
                runs.append([sv, sv, key])
        lanes_sig = lambda key: tuple((a, b) for _, a, b in key)

        def short(j):       # a run shorter than SUB_MIN_M joins a neighbour, unless OSM's lane count changes there (then LANES_MIN_M)
            L_ = runs[j][1] - runs[j][0]
            nb_ = [runs[x][2] for x in (j - 1, j + 1) if 0 <= x < len(runs)]
            return L_ < LANES_MIN_M or (L_ < SUB_MIN_M and any(lanes_sig(x) == lanes_sig(runs[j][2]) for x in nb_))
        while len(runs) > 1 and any(short(j) for j in range(len(runs))):
            j = min((j for j in range(len(runs)) if short(j)), key=lambda j: runs[j][1] - runs[j][0])
            nbs = [x for x in (j - 1, j + 1) if 0 <= x < len(runs)]     # the neighbour with the same lanes first, then the longer
            nb = max(nbs, key=lambda x: (lanes_sig(runs[x][2]) == lanes_sig(runs[j][2]), runs[x][1] - runs[x][0]))
            lo, hi = min(j, nb), max(j, nb)
            runs[lo] = [runs[lo][0], runs[hi][1], runs[nb][2]]
            del runs[hi]
        bounds = [0.0] + [(runs[j][1] + runs[j + 1][0]) / 2 for j in range(len(runs) - 1)] + [axis.length]
        pieces_ = [P]
        cutlines = []
        for sv in bounds[1:-1]:
            p = axis.interpolate(sv)
            ux, uy = tangent(axis, sv)
            cutlines.append(shapely.LineString([(p.x - uy * RAY_M, p.y + ux * RAY_M), (p.x + uy * RAY_M, p.y - ux * RAY_M)]))
        if cutlines:
            pieces_ = [x for x in shapely.get_parts(shapely.polygonize(list(shapely.get_parts(shapely.union_all(
                [P.boundary] + [c.intersection(P.buffer(0.05)) for c in cutlines]))))) if x.representative_point().within(P) and x.area > 0.5]
        for k in range(len(bounds) - 1):
            mid_pt = axis.interpolate((bounds[k] + bounds[k + 1]) / 2)
            Q = min(pieces_, key=lambda x: x.distance(mid_pt)) if pieces_ else P
            sub = f"{sid}/{k + 1}"
            sax = substring(axis, bounds[k], bounds[k + 1])      # a piece of the section's axis: neighbours meet without a turn
            sax = sax if sax.geom_type == "LineString" and sax.length >= 1 else axis
            sub_axis[sub] = (sax, s["left"], s["right"], i, Q)
            sub_span[sub] = (bounds[k], bounds[k + 1])
            units.append((sub, "subsection", sid, Q))
            sub_rows.append((sub, sid, sax, Q, s, "section end" if k == 0 else "lanes change"))

    # ---- intersections: ids from the OSM junction nodes in them
    nodes = {}
    for r in roads:
        for nid, pt in ((r[5], r[7].coords[0]), (r[6], r[7].coords[-1])):
            if nid is not None:
                nodes.setdefault(nid, shapely.Point(pt))
    for nid, pt in rows(f"""SELECT src, {m('ST_StartPoint(geometry)')} FROM space.element WHERE type = 'road' AND level_min = 0 AND src IS NOT NULL
                           UNION SELECT dst, {m('ST_EndPoint(geometry)')} FROM space.element WHERE type = 'road' AND level_min = 0 AND dst IS NOT NULL"""):
        nodes.setdefault(nid, g(pt))
    ntree = shapely.STRtree(list(nodes.values()))
    nids = list(nodes)
    inter_ids, used = [], {}
    for x in inter:
        inside = sorted(nids[k] for k in ntree.query(x) if x.contains(nodes[nids[k]]))
        iid = f"i0-{inside[0]}" if inside else f"i0-x{round(x.centroid.x)}y{round(x.centroid.y)}"
        used[iid] = used.get(iid, 0) + 1
        if used[iid] > 1:
            iid += f".{used[iid]}"
        inter_ids.append(iid)
        units.append((iid, "intersection", None, x))
        junction += [(iid, n, 0, iid) for n in inside]
    for c_, j, end in cuts:
        if j not in section_ids:
            continue
        near = [inter_ids[k] for k, x in enumerate(inter) if x.distance(c_) < 0.1]
        rd = [str(r[0]) for k in road_tree.query(c_) for r in [roads[k]] if r[7].intersects(c_)]
        cut_rows.append((near[0] if near else None, rd[0] if rd else None, c_))

    # ---- the inside of each subsection: strips parallel to its axis
    kerbs_of = {}
    pid = {}

    def add(uid, typ, geom, **kw):
        for p in shapely.get_parts(geom):
            if p.geom_type != "Polygon" or p.area < 0.05:
                continue
            pid[uid] = pid.get(uid, 0) + 1
            parts.append(dict(unit_id=uid, part_id=f"{uid}#{pid[uid]}", type=typ, geom=p, **kw))

    def mark(uid, typ, geom, src="urbanstyle", method="derived", ref=None):
        if geom is not None and not geom.is_empty:
            marks.append((uid, typ, geom, src, method, ref))

    def along(ax, line, P):
        """The offset (left +) of a line running along the axis inside P, else None."""
        w = line.intersection(P)
        if w.is_empty or w.length < 5:
            return None
        wl = max((p for p in shapely.get_parts(w) if p.geom_type == "LineString"), key=lambda p: p.length, default=None)
        if wl is None:
            return None
        c_ = wl.interpolate(0.5, normalized=True)
        sv = ax.project(c_)
        ux, uy = tangent(ax, sv)
        wx, wy = tangent(wl, wl.length / 2)
        if abs(wx * ux + wy * uy) < 0.82:
            return None
        q = ax.interpolate(sv)
        return (c_.x - q.x) * -uy + (c_.y - q.y) * ux

    def offset(ax, pt):
        sv = ax.project(pt)
        q = ax.interpolate(sv)
        ux, uy = tangent(ax, sv)
        return (pt.x - q.x) * -uy + (pt.y - q.y) * ux

    sec_kerbs = {}

    def prov_of(ev, method, fallback):
        """(source, method, ref) of a value from its evidence [(source, id)]: every source and every id."""
        if not ev:
            return fallback
        srcs = sorted({s_ for s_, _ in ev})
        ids = sorted({x for _, x in ev})
        return ("+".join(srcs), method, ", ".join(ids[:12]) + (f" (and {len(ids) - 12} more)" if len(ids) > 12 else ""))

    def section_kerbs(i, outer_l, outer_r, ways, least_l, least_r):
        """One kerb on each side of a whole section (left +, right -), top-down from the evidence along its whole length:
        OSM's and the city's sidewalk lines (the kerb SIDEWALK_HALF_M before them) and the city's catch basins (in the gutter); the city's
        poles, trees and meters stand behind it. Else the carriageways' edge (OSM's lanes x LANE_M). Returns (kerb left, kerb right,
        (source, method, ref) of each, OSM's sidewalk lines left and right [(offset, id)])."""
        if i in sec_kerbs:
            return sec_kerbs[i]
        ax, P = sec_axis[i]
        ev = {1: [], -1: []}            # (offset, source, id)
        swl, swr = [], []
        # the side of a line or a basin: of the carriageways, not of the axis (the middle between the blocks: a street off that middle has a
        # sidewalk near it); a footway between the carriageways' edges (on a median) is no kerb
        mid_ = (outer_l + outer_r) / 2
        side = lambda t: (1 if t >= outer_l - 1.0 else 0) if t > mid_ else (-1 if t <= outer_r + 1.0 else 0)
        for src, tree, lines_, ids_ in (("osm", walk_tree, walks, walk_ids), ("vancouver", cwalk_t, city_walks, [r_[0] for r_ in cwalk_rows])):
            for k in (tree.query(P) if tree is not None else []):
                t = along(ax, lines_[k], P)
                sg = side(t) if t is not None else 0
                if sg:
                    ev[sg].append((t - sg * SIDEWALK_HALF_M, src, ids_[k]))
                    if src == "osm":
                        (swl if sg > 0 else swr).append((t, ids_[k]))
        for k in (basin_t.query(P) if basin_t is not None else []):
            if P.contains(basins[k]):
                t = offset(ax, basins[k])
                sg = 1 if t > mid_ else -1
                ev[sg].append((t + sg * BASIN_BACK_M, "vancouver", basin_rows[k][0]))
        lim = {1: [], -1: []}
        for k in (behind_t.query(P) if behind_t is not None else []):
            if P.contains(behind[k]):
                t = offset(ax, behind[k])
                if (t > 0 and t > least_l) or (t < 0 and t < least_r):     # (a pole on a median stands in no kerb's way)
                    lim[1 if t > 0 else -1].append((t, behind_rows[k][0]))
        out = []
        for sg, outer in ((1, outer_l), (-1, outer_r)):
            # the evidence nearest the road holds (a second sidewalk line, a basin across a wide boulevard, lie farther out)
            least = least_l if sg > 0 else least_r
            e = sorted((x for x in ev[sg] if sg * x[0] > sg * outer - 1.0 and sg * x[0] >= sg * least), key=lambda x: abs(x[0]))   # (a footway
            # on a median, a line inside OSM's carriageway is no kerb)
            e = [x for x in e if abs(x[0]) <= abs(e[0][0]) + 2.0] if e else []
            if e:
                k_, pv = statistics.median([x[0] for x in e]), prov_of([(s_, x) for _, s_, x in e], "measured", None)
            else:   # the carriageways' edge: OSM's lanes, each LANE_M wide
                k_, pv = outer, ("urbanstyle", "derived", ", ".join(f"w{w}" for w in ways) + f" (lanes x {LANE_M} m)")
            l = sorted(lim[sg], key=lambda x: abs(x[0]))
            if len(l) >= 2:      # behind the innermost poles and trees (the second nearest: one odd point does not decide)
                cap = l[1][0] - sg * OBJ_KERB_M
                if sg * k_ > sg * cap:
                    k_ = cap
                    pv = prov_of([("vancouver", l[0][1]), ("vancouver", l[1][1])] + ([(s_, x) for _, s_, x in e] if e else []), "measured", None)
            if sg * k_ < sg * least:     # never inside OSM's carriageway: its lanes, each TRAVEL_M[0] wide at least
                k_, pv = least, ("osm", "derived", ", ".join(f"w{w}" for w in ways) + f" (lanes x {TRAVEL_M[0]} m at least)")
            out.append((k_, pv))
        sec_kerbs[i] = (out[0][0], out[1][0], out[0][1], out[1][1], swl, swr)
        return sec_kerbs[i]

    def fit(W, osm_n, al_share, oneway, park, bike, weight=1.5, fixed=False):
        """The most likely cross-section of a carriageway W wide (top-down): travel lanes, a parking lane and a bike lane at each side
        (park / bike: per side +1 / -1, True where the evidence says so, False where it says no, None where it says nothing), a gutter at
        each kerb. Evidence counts as hints; the width decides, except a mapped lane count (`fixed`): it is never changed to fit the width
        (a misfit means our kerbs are wrong: check R3). Returns (score, n, parking sides, bike sides)."""
        best = None
        for n in ((osm_n,) if fixed and osm_n else range(1, 7)):
            for pl in (0, 1):
                for pr in (0, 1):
                    for bl in (0, 1):
                        for br in (0, 1):
                            lo = 2 * GUTTER_M + n * TRAVEL_M[0] + (pl + pr) * PARK_M[0] + (bl + br) * BIKE_M[0]
                            hi = 2 * GUTTER_M + n * TRAVEL_M[1] + (pl + pr) * PARK_M[1] + (bl + br) * BIKE_M[1]
                            sc = 3.0 * max(lo - W, W - hi, 0.0)
                            if osm_n:
                                sc += weight * abs(n - osm_n)
                            if oneway is False and n < 2:
                                sc += 2.0
                            for side, has, pv in ((1, pl, park[1]), (-1, pr, park[-1])):
                                sc += 1.0 if (pv is True and not has) or (pv is False and has) else 0.3 if (pv is None and has) else 0.0
                            for side, has, bv in ((1, bl, bike[1]), (-1, br, bike[-1])):
                                sc += 1.0 if (bv is True and not has) or (bv is False and has) else 0.8 if (bv is None and has) else 0.0
                            sc += 0.2 * abs((W - 2 * GUTTER_M - (pl + pr) * 2.4 - (bl + br) * 1.75) / n - 3.3)
                            if best is None or sc < best[0]:
                                best = (sc, n, {1: pl, -1: pr}, {1: bl, -1: br})
        return best

    # ---- every edge of a subsection (kerbs, medians, lanes) has a value at each of its two ends, (start, end), and runs straight from one
    # to the other: two subsections that meet at a joint share the values there, so their roadways meet (check R1)
    V = lambda a, b=None: np.array([a, a if b is None else b], dtype=float)
    const = lambda t: abs(t[1] - t[0]) < 0.005
    mean = lambda t: float((t[0] + t[1]) / 2)

    def ribbon(axis, t, margin=60.0):
        """The line at offset t = (at the start, at the end) of the axis (left +), straight between, the same past each end."""
        ax = extend(axis, margin)
        ss = sorted(set(np.arange(0.0, ax.length, 1.0).tolist()) | {ax.length, margin, margin + axis.length})
        out = []
        for s_ in ss:
            u = min(max((s_ - margin) / axis.length, 0.0), 1.0)
            tv = t[0] + (t[1] - t[0]) * u
            p = ax.interpolate(s_)
            ux, uy = tangent(ax, s_)
            out.append((p.x - uy * tv, p.y + ux * tv))
        return out

    def band2(axis, t1, t2, P):
        """offset_band, with t1 and t2 (start, end)."""
        if const(t1) and const(t2):
            return offset_band(axis, mean(t1), mean(t2), P)
        return poly(poly(shapely.make_valid(shapely.Polygon(ribbon(axis, t1) + ribbon(axis, t2)[::-1]))).intersection(P, grid_size=0.01))

    def line2(axis, t, P, width=None):
        """The painted line at offset t (start, end) of the axis, inside P."""
        x = (extend(axis, 60.0).offset_curve(mean(t)) if const(t) else shapely.LineString(ribbon(axis, t))).intersection(P.buffer(0.01))
        return lines(x) if not x.is_empty and x.length > 0.5 else None

    stations = {}

    def block_at(i, sv):
        """The block's distance left (+) and right (-) of the section's axis at sv: the median of three lines 4 m apart, 2 m or more
        inside the section's ends. Both subsections at a joint ask for the same sv, so they get the same answer."""
        key = (i, round(sv, 2))
        if key not in stations:
            sx = sec_axis[i][0]
            lo_, hi_ = (2.0, sx.length - 2.0) if sx.length > 4 else (sx.length / 2, sx.length / 2)
            hs = [across(sx, min(max(sv + d, lo_), hi_)) for d in (-4.0, 0.0, 4.0)]
            stations[key] = (statistics.median([h[1][2] for h in hs if h[1]] or [10.0]), -statistics.median([h[-1][2] for h in hs if h[-1]] or [10.0]))
        return stations[key]

    # pass 1: what each subsection measures over its own length (its carriageways, the blocks) and its medians
    meas = {}
    for sub, (ax, L, R, i, Q) in sub_axis.items():
        n = int(ax.length // 4) + 1
        prs = [profile(ax, Q, min(k * 4.0 + 2.0, ax.length)) for k in range(n)]
        prs = [p for p in prs if p] or [[]]
        # the carriageways: their offsets and widths, the median over the subsection (they run parallel to the axis)
        nc = statistics.median_low([len(p) for p in prs])
        same = [p for p in prs if len(p) == nc]
        cw = []
        for k in range(nc):
            cs = [p[k] for p in same]
            cw.append(dict(t=statistics.median([c[0] for c in cs]), w=statistics.median([c[1] for c in cs]), al=cs[0][2], ag=cs[0][3], road=cs[0][4],
                           fw=cs[0][5]))
        cw = sorted(cw, key=lambda c: c["t"])
        # the block on each side
        hs = [across(ax, min(k * 4.0 + 2.0, ax.length)) for k in range(n)]
        tl = statistics.median([h[1][2] for h in hs if h[1]] or [10.0])
        tr = -statistics.median([h[-1][2] for h in hs if h[-1]] or [10.0])
        meds, isle = {}, set()     # carriageway k -> what lies between it and k + 1: [(a, b) at the start, (a, b) at the end]; a median
        for k in range(len(cw) - 1):    # if wider than MEDIAN_MIN_M (isle), else one line half way
            a_, b_ = cw[k]["t"] + cw[k]["w"] / 2, cw[k + 1]["t"] - cw[k + 1]["w"] / 2
            if b_ - a_ > MEDIAN_MIN_M:
                isle.add(k)
            else:
                a_ = b_ = (a_ + b_) / 2
            meds[k] = [(a_, b_), (a_, b_)]
        meas[sub] = dict(cw=cw, tl=tl, tr=tr, meds=meds, isle=isle)

    # pass 2: at each joint, what lies between two carriageways (a median, or a line) on both sides meets itself half way; a median that
    # meets a line closes on it; one on one side only closes there (a carriageway joins)
    for sub, (ax, L, R, i, Q) in sub_axis.items():
        sid, k_ = sub.rsplit("/", 1)
        nxt = f"{sid}/{int(k_) + 1}"
        if nxt not in meas:
            continue
        A, B = meas[sub]["meds"], meas[nxt]["meds"]
        pairs = sorted(((min(a[1][1], b[0][1]) - max(a[1][0], b[0][0]), ka, kb) for ka, a in A.items() for kb, b in B.items()), reverse=True)
        done_a, done_b = set(), set()
        for ov, ka, kb in pairs:
            ca, cb = sum(A[ka][1]) / 2, sum(B[kb][0]) / 2
            if ka in done_a or kb in done_b or (ov <= 0 and abs(ca - cb) > 2.0):
                continue
            if (ka in meas[sub]["isle"]) == (kb in meas[nxt]["isle"]):
                j = ((A[ka][1][0] + B[kb][0][0]) / 2, (A[ka][1][1] + B[kb][0][1]) / 2)
            else:       # a median meets a line: it closes on the line's end, half way between them
                j = ((ca + cb) / 2, (ca + cb) / 2)
            A[ka][1], B[kb][0] = j, j
            done_a.add(ka)
            done_b.add(kb)
        for ka in set(A) - done_a:
            c_ = sum(A[ka][1]) / 2
            A[ka][1] = (c_, c_)
        for kb in set(B) - done_b:
            c_ = sum(B[kb][0]) / 2
            B[kb][0] = (c_, c_)

    least_of = {}       # section -> the least kerb offsets left and right: its outermost OSM carriageways, each lane TRAVEL_M[0] wide
    for sub, (ax, L, R, i, Q) in sub_axis.items():
        for c in meas[sub]["cw"]:
            h = (c["al"] + c["ag"]) * TRAVEL_M[0] / 2
            lo_, hi_ = least_of.get(i, (-math.inf, math.inf))      # (the axis, between the blocks, can lie beside the carriageways)
            least_of[i] = (max(lo_, c["t"] + h), min(hi_, c["t"] - h))

    def frame(sub):
        """A subsection's kerbs and the edges of its carriageways, each (start, end): (kl, kr, their methods, OSM's sidewalk lines left and
        right, [[right edge, left edge] of each carriageway]); kl None where it has no carriageway."""
        ax, L, R, i, Q = sub_axis[sub]
        cw, meds = meas[sub]["cw"], meas[sub]["meds"]
        s0, s1 = sub_span[sub]
        if not cw:
            return None, None, None, None, [], [], []
        # the kerbs: the section's, measured once over its whole length (every subsection of a section shares them), kept MIN_REALM_M from
        # the block at each end
        outer_l = max(c["t"] + c["w"] / 2 for c in cw)
        outer_r = min(c["t"] - c["w"] / 2 for c in cw)
        kl_s, kr_s, kl_m, kr_m, swl, swr = section_kerbs(i, outer_l, outer_r, sorted({c["road"][0] for c in cw}), *least_of[i])
        kl, kr = V(0.0), V(0.0)
        for e, (bl, br) in enumerate([block_at(i, s0), block_at(i, s1)]):
            # MIN_REALM_M from the block, but never inside OSM's carriageway
            kl[e], kr[e] = max(min(kl_s, bl - MIN_REALM_M), min(least_of[i][0], bl)), min(max(kr_s, br + MIN_REALM_M), max(least_of[i][1], br))
            if kl[e] <= kr[e]:
                kl[e], kr[e] = (bl + br) / 2 + 0.01, (bl + br) / 2 - 0.01
        # the roadway: carriageways right to left, a median between them, a shoulder where the kerb stands wider
        edges = []
        for k, c in enumerate(cw):
            edges.append([kr.copy() if k == 0 else None, kl.copy() if k == len(cw) - 1 else None])
        for k, ((a0, b0), (a1, b1)) in sorted(meds.items()):      # a median where two carriageways stand apart, else the line between them
            m_ = 1.0 if k in meas[sub]["isle"] else 0.0
            edges[k][1], edges[k + 1][0] = np.maximum(V(a0, a1), kr + m_), np.minimum(V(b0, b1), kl - m_)
        # carriageways side by side with no median between them share their roadway by their lane counts (OSM's), not half way between
        # their OSM lines
        isle = meas[sub]["isle"]
        k = 0
        while k < len(cw):
            j = k
            while j < len(cw) - 1 and j not in isle:
                j += 1
            if j > k:           # carriageways k..j, no median between them
                n_ = [max(cw[q]["al"] + cw[q]["ag"], 1) for q in range(k, j + 1)]
                lo_, hi_ = edges[k][0], edges[j][1]
                acc = 0
                for q in range(k, j):
                    acc += n_[q - k]
                    edges[q][1] = edges[q + 1][0] = lo_ + (hi_ - lo_) * acc / sum(n_)
            k = j + 1
        # at each end, every edge between the kerbs and in order, right to left (where the kerbs squeeze the street, nothing crosses)
        seq = [e for pair in edges for e in pair]
        for x in range(len(seq)):
            seq[x] = np.minimum(np.maximum(seq[x], seq[x - 1] if x else kr), kl)
        edges = [[seq[2 * k], seq[2 * k + 1]] for k in range(len(edges))]
        return kl, kr, kl_m, kr_m, swl, swr, edges

    # one fit per OSM way in a section (its lanes, parking and bike lanes), from the median room over its subsections: the lanes go on
    # across the joints
    rooms = {}
    for sub in sub_axis:
        _, _, _, _, _, _, edges_ = frame(sub)
        for c, (lo, hi) in zip(meas[sub]["cw"], edges_):
            rooms.setdefault((sub_axis[sub][3], c["road"][0], c["fw"]), []).append(mean(hi - lo))
    fits = {}

    # where each part comes from: source, method, ref of what it is, and of where its edge is (position_*)
    PV = lambda s_, m_, r_=None: dict(source=s_, method=m_, ref=r_)
    POS = lambda pv: dict(position_source=pv[0], position_method=pv[1], position_ref=pv[2])
    both = lambda a, b: (a[0] if a[0] == b[0] else "+".join(sorted(set(a[0].split("+")) | set(b[0].split("+")))),
                         a[1] if a[1] == b[1] else "derived", "; ".join(x for x in (a[2], b[2]) if x) or None)
    bside = {}
    for b_, w_, basis, me, bl in rows("SELECT block_id, way_id, basis, method, building FROM space.block_side"):
        bside.setdefault(b_, []).append((w_, basis, me, bl))

    def edge_prov(k, ways):
        """(source, method, ref) of the block's edge on one side (space.block_side: what set it)."""
        if k is None or k < 0:
            return ("urbanstyle", "derived", "the area's edge")
        rs_ = [r_ for r_ in bside.get(bid[k], []) if r_[0] in ways] or bside.get(bid[k], [])
        basis = rs_[0][1] if rs_ else None
        src = {"parcels (joined)": "vancouver", "parcel": "vancouver", "parcels": "vancouver", "sidewalks": "osm", "building": "osm"}.get(basis, "urbanstyle")
        ref = ", ".join(sorted({r_[3] for r_ in rs_ if r_[3]})) or ("property-parcel-polygons" if src == "vancouver" else None)
        return (src, rs_[0][2] if rs_ and src != "urbanstyle" else "chosen", f"block {bid[k]} ({basis})" + (f": {ref}" if ref else ""))

    def join_lanes(la, lb, ea=1, eb=0, sgn=1, c0=0.0):
        """The joint of two subsections, A's end ea and B's end eb (la, lb: their layouts; 0 the start, 1 the end). B's offsets in A's
        frame are sgn * t + c0 (one section: 1, 0; two sections: their axes there, sgn -1 where they point apart). The items of the two sides (lanes
        by direction, cycle lanes, parking) are matched in order, most overlap first (a lane shifted sideways by less than JOIN_M still
        matches); each pair gets the mean of its edges on both sides. Between two pairs: with no other item on either side, the pairs
        meet at one point; with items on one side only, these open or close there at zero width (a taper); with items on both sides
        (a lane that becomes a cycle lane), each side fills the same room with its own. Then each median sits between its items."""
        if la[0][0] is None or lb[0][0] is None:      # a side with no roadway: nothing goes on
            return
        # the kerbs meet half way
        (klA, krA, *_r, edA), (klB, krB, *_s, edB) = la[0], lb[0]
        bl, br = (klB, krB) if sgn > 0 else (krB, klB)           # B's kerb on A's left, on A's right
        nl, nr = (klA[ea] + sgn * bl[eb] + c0) / 2, (krA[ea] + sgn * br[eb] + c0) / 2
        klA[ea] = edA[-1][1][ea] = nl
        krA[ea] = edA[0][0][ea] = nr
        bl[eb] = (nl - c0) * sgn
        br[eb] = (nr - c0) * sgn
        edB[-1][1][eb], edB[0][0][eb] = klB[eb], krB[eb]

        def pieces(lay_, e, s_):
            out = []
            for k, C in enumerate(lay_[1]):
                k_lane = 0
                for (typ, _), ed in zip(C["items"], C["ie"]):
                    if typ == "lane":
                        key = ("lane", "both" if C["shared"] else (k_lane < C["n_al"]) == (s_ > 0))
                        k_lane += 1
                    else:
                        key = (typ, None)
                    cc = c0 if lay_ is lb else 0.0
                    a_, b_ = sorted((s_ * float(ed[0][e]) + cc, s_ * float(ed[1][e]) + cc))
                    out.append(dict(key=key, ed=ed, e=e, k=k, s=s_, c=cc, a=a_, b=b_))
            return sorted(out, key=lambda r: (r["a"], r["b"]))

        def put(r, a_, b_):
            u, v = sorted(((a_ - r["c"]) * r["s"], (b_ - r["c"]) * r["s"]))     # back to its own frame
            r["ed"][0][r["e"]], r["ed"][1][r["e"]], r["a"], r["b"] = u, v, a_, b_

        def fill(U, lo_, hi_):          # the items U side by side from lo_ to hi_, each as wide as before in proportion
            ws_ = [max(r["b"] - r["a"], 0.01) for r in U]
            t_ = lo_
            for r, w_ in zip(U, ws_):
                put(r, t_, t_ + (hi_ - lo_) * w_ / sum(ws_))
                t_ = r["b"]
        P_, Q_ = pieces(la, ea, 1), pieces(lb, eb, sgn)
        score = lambda p, q: (min(p["b"], q["b"]) - max(p["a"], q["a"]) + JOIN_M) if p["key"] == q["key"] else 0.0
        n1, n2 = len(P_), len(Q_)
        D = [[0.0] * (n2 + 1) for _ in range(n1 + 1)]
        for x in range(n1 - 1, -1, -1):
            for y in range(n2 - 1, -1, -1):
                sc = score(P_[x], Q_[y])
                D[x][y] = max(D[x + 1][y], D[x][y + 1], sc + D[x + 1][y + 1] if sc > 0 else 0.0)
        pairs, x, y = [], 0, 0
        while x < n1 and y < n2:
            sc = score(P_[x], Q_[y])
            if sc > 0 and abs(D[x][y] - (sc + D[x + 1][y + 1])) < 1e-9:
                pairs.append((x, y))
                x, y = x + 1, y + 1
            elif D[x + 1][y] >= D[x][y + 1]:
                x += 1
            else:
                y += 1
        for x, y in pairs:
            p, q = P_[x], Q_[y]
            a_, b_ = (p["a"] + q["a"]) / 2, (p["b"] + q["b"]) / 2
            put(p, a_, b_)
            put(q, a_, b_)
        seq = [(-1, -1)] + pairs + [(n1, n2)]
        for (x0, y0), (x1, y1) in zip(seq, seq[1:]):
            UA, UB = P_[x0 + 1:x1], Q_[y0 + 1:y1]
            lo_ = P_[x0]["b"] if x0 >= 0 else None
            hi_ = P_[x1]["a"] if x1 < n1 else None
            if lo_ is not None and hi_ is not None:
                # no island between the two pairs (one carriageway, or two that meet at a line) on side A, on side B
                isl = lambda lay_, k0, k1: any(lay_[1][k]["isle"] for k in range(min(k0, k1), max(k0, k1)))
                one_a, one_b = not isl(la, P_[x0]["k"], P_[x1]["k"]), not isl(lb, Q_[y0]["k"], Q_[y1]["k"])
                if (one_a and UA and (UB or not one_b)) or (one_b and UB and (UA or not one_a)):
                    # a side with items in one carriageway fills the room with them; the other side's items, if any, likewise, or
                    # (across a median) open at zero width in their own middle
                    for U, one in ((UA, one_a), (UB, one_b)):
                        if U and (one or (UA and UB)):
                            fill(U, lo_, hi_)
                        else:
                            for r in U:
                                c_ = min(max((r["a"] + r["b"]) / 2, lo_), hi_)
                                put(r, c_, c_)
                    continue
                if not one_a and not one_b:     # a median between them on both sides: it stays; items in it open in their own middle
                    for r in UA + UB:
                        c_ = min(max((r["a"] + r["b"]) / 2, lo_), hi_)
                        put(r, c_, c_)
                    continue
                m_ = (lo_ + hi_) / 2            # the pairs meet (a median on one side closes there, as in pass 2)
                for r in (P_[x0], Q_[y0]):
                    put(r, r["a"], m_)
                for r in (P_[x1], Q_[y1]):
                    put(r, m_, r["b"])
                for r in UA + UB:
                    put(r, m_, m_)
            elif UA and UB:         # beyond the last pair (or the first), or no pair at all: both sides fill the same room
                lo2 = lo_ if lo_ is not None else (UA[0]["a"] + UB[0]["a"]) / 2
                hi2 = hi_ if hi_ is not None else (UA[-1]["b"] + UB[-1]["b"]) / 2
                fill(UA, lo2, hi2)
                fill(UB, lo2, hi2)
            else:                   # on one side only: they open or close at the edge of the last (or first) pair
                at_ = lo_ if lo_ is not None else hi_
                if at_ is not None:
                    for r in UA + UB:
                        put(r, at_, at_)
        for lay_, e in ((la, ea), (lb, eb)):
            edges_ = lay_[0][6]
            kl_, kr_ = lay_[0][0][e], lay_[0][1][e]
            for C in lay_[1]:                       # the items stay between the kerbs
                for ed in C["ie"]:
                    ed[0][e], ed[1][e] = min(max(ed[0][e], kr_), kl_), min(max(ed[1][e], kr_), kl_)
            for k in range(len(lay_[1]) - 1):       # the median (or the line) between two carriageways: between their items
                if lay_[1][k]["ie"] and lay_[1][k + 1]["ie"]:
                    lo_, hi_ = lay_[1][k]["ie"][-1][1][e], lay_[1][k + 1]["ie"][0][0][e]
                    edges_[k][1][e] = min(max(edges_[k][1][e], lo_), hi_)
                    edges_[k + 1][0][e] = min(max(edges_[k + 1][0][e], edges_[k][1][e]), hi_)

    # pass 3a: the layout of each subsection: its frame (kerbs, carriageways) and in each carriageway its items (parking, cycle lanes,
    # lanes, right to left), each with its edges (right, left), each (start, end)
    lay = {}
    for sub, (ax, L, R, i, Q) in sub_axis.items():
        fr = frame(sub)
        sx, sP = sec_axis[i]
        cws = []
        for c, (lo, hi) in zip(meas[sub]["cw"], fr[6]):
            rd = c["road"]
            tg = osm_tags.get(rd[0], {})
            fwd = c["fw"]
            side_of = lambda tag_side: (-1 if tag_side == "right" else 1) * (1 if fwd else -1)   # OSM's right of the way, as our side
            park, bike = {1: None, -1: None}, {1: None, -1: None}
            park_pv, bike_pv = {}, {}       # side -> (source, method, ref) of the evidence
            for k_, v in tg.items():
                if k_.startswith(("parking:lane:", "parking:")) and not k_.endswith(("restriction", "reason", "fee", "maxstay", "orientation")):
                    part_ = k_.split(":")[-1] if k_.count(":") == 1 else k_.split(":")[2] if k_.startswith("parking:lane:") else k_.split(":")[1]
                    yes = v not in ("no", "none", "separate", "no_parking", "no_stopping")
                    for sd in ((side_of("left"), side_of("right")) if part_ == "both" else (side_of(part_),) if part_ in ("left", "right") else ()):
                        park[sd] = yes
                        park_pv[sd] = ("osm", "mapped", f"w{rd[0]} {k_}={v}")
                if k_.startswith("cycleway") and k_.count(":") <= 1:
                    part_ = k_.split(":")[1] if ":" in k_ else "both"
                    yes = v in ("lane", "track", "buffered_lane", "opposite_lane")
                    for sd in ((side_of("left"), side_of("right")) if part_ == "both" else (side_of(part_),) if part_ in ("left", "right") else ()):
                        bike[sd] = yes if (yes or v in ("no", "none", "shared_lane")) else bike[sd]
                        if yes or v in ("no", "none", "shared_lane"):
                            bike_pv[sd] = ("osm", "mapped", f"w{rd[0]} {k_}={v}")
            # the city's parking meters and bike lanes near a kerb, along the whole section (one short subsection does not decide alone)
            for sd, kerb_t in ((1, hi), (-1, lo)):
                kline = line_at(sx, mean(kerb_t), sP, 6.0)
                mt = [meter_rows[k][0] for k in (meter_t.query(kline) if kline is not None and meter_t is not None else []) if kline.contains(meters[k])]
                if mt:
                    park[sd] = True
                    park_pv[sd] = prov_of([("vancouver", x) for x in mt], "mapped", None)
                bw = [bike_ids[k] for k in (bike_t.query(kline) if kline is not None and bike_t is not None else []) if bikeways[k][1].intersection(kline).length > 10]
                if bw:
                    bike[sd] = True
                    bike_pv[sd] = prov_of([("vancouver", x) for x in bw], "mapped", None)
            osm_n = c["al"] + c["ag"] if (tg.get("lanes") or tg.get("lanes:forward") or tg.get("lanes:backward")) else None
            hint_n = osm_n or (1 if (c["ag"] == 0 or c["al"] == 0) else 2)     # no lane tag: one lane each way (chosen), a weaker hint
            room = hi - lo
            key = (i, rd[0], fwd)
            if key not in fits:
                fits[key] = (fit(statistics.median(rooms.get(key) or [mean(room)]), hint_n, None, c["ag"] == 0 or c["al"] == 0, park, bike,
                                 1.5 if osm_n else 0.8, fixed=bool(osm_n)), dict(park_pv), dict(bike_pv))
            (sc, n, pk, bk), park_pv, bike_pv = fits[key]
            # what the lanes are: OSM's count where the width holds it, else the count the width holds (the fit)
            if rd[0] in CORR:
                lane_pv = (CORR_SRC, "corrected", f"w{rd[0]} lanes={osm_n}: {CORR[rd[0]][1]}")
            elif osm_n and n == osm_n:
                lane_pv = ("osm", "mapped", f"w{rd[0]} lanes={tg.get('lanes') or osm_n}")
            elif osm_n:
                lane_pv = ("urbanstyle", "derived", f"w{rd[0]} lanes={osm_n}; the width kerb to kerb holds {n}")
            else:
                lane_pv = ("urbanstyle", "chosen", f"w{rd[0]} has no lanes tag: {hint_n} chosen, the width holds {n}")
            items = [("parking", PARK_M)] * pk[-1] + [("cycle lane", BIKE_M)] * bk[-1] + [("lane", TRAVEL_M)] * n + \
                    [("cycle lane", BIKE_M)] * bk[1] + [("parking", PARK_M)] * pk[1]

            def spread(rm):
                """The widths at one end: each element within its range, filling the room; what is left goes to the gutters."""
                mn = sum(r[0] for _, r in items) + 2 * GUTTER_M
                mx = sum(r[1] for _, r in items) + 2 * GUTTER_M
                f_ = 0.0 if mx == mn else min(max((rm - mn) / (mx - mn), 0.0), 1.0)
                ws_ = [r[0] + f_ * (r[1] - r[0]) for _, r in items]
                if rm < mn:       # too narrow even at the least: everything narrower in proportion (reported by R2)
                    ws_ = [w_ * max(rm - 2 * GUTTER_M, 0.0) / sum(ws_) for w_ in ws_]
                return ws_, (rm - sum(ws_)) / 2
            (w0, g0), (w1, g1) = spread(room[0]), spread(room[1])
            ws, gut = [V(a, b) for a, b in zip(w0, w1)], V(g0, g1)
            # directions: the lanes in OSM's share (one way: all one way)
            if c["ag"] == 0 or c["al"] == 0:
                n_al = n if c["ag"] == 0 else 0
            else:
                n_al = min(max(round(n * c["al"] / (c["al"] + c["ag"])), 1), n - 1) if n > 1 else 1
            al_dir, ag_dir = ("forward", "backward") if fwd else ("backward", "forward")     # relative to the OSM way
            shared = n == 1 and c["al"] > 0 and c["ag"] > 0     # a two-way street one lane wide: one lane both ways (a yield street)
            rule = f"fit: {n} lanes" + (f" (corrected: {osm_n})" if rd[0] in CORR else f" (OSM: {osm_n})" if osm_n else " (OSM: none)") + \
                   "".join(f", parking {('left' if sd > 0 else 'right')}" for sd in (1, -1) if pk[sd]) + \
                   "".join(f", bike lane {('left' if sd > 0 else 'right')}" for sd in (1, -1) if bk[sd])
            ie, t = [], lo + gut
            for w_ in ws:
                ie.append([t, t + w_])
                t = t + w_
            cws.append(dict(c=c, rd=rd, tg=tg, fwd=fwd, osm_n=osm_n, n=n, items=items, ie=ie, n_al=n_al, al_dir=al_dir, ag_dir=ag_dir,
                            shared=shared, rule=rule, lane_pv=lane_pv, park_pv=park_pv, bike_pv=bike_pv,
                            isle=len(cws) in meas[sub]["isle"]))     # an island (not a line) between it and the next carriageway
        lay[sub] = (fr, cws)

    # pass 3b: at each joint, every item that goes on has the same edges on both sides; one with no partner starts or stops there at
    # zero width (a taper); the medians sit between the items again (check R4)
    for sub in sub_axis:
        sid, k_ = sub.rsplit("/", 1)
        if f"{sid}/{int(k_) + 1}" in lay:
            join_lanes(lay[sub], lay[f"{sid}/{int(k_) + 1}"])
    # and where two sections meet with no intersection between them (their spaces share JOIN_EDGE_M or more of edge, their axes nearly
    # in line there): the kerbs too meet half way, then the items as above
    sids = [(i, sid) for i, sid in section_ids.items() if i in sec_axis]
    stree = shapely.STRtree([sec_axis[i][1] for i, _ in sids])
    for i, sid in sids:
        Pi = sec_axis[i][1]
        for y_ in stree.query(Pi.buffer(0.1)):
            j, sjd = sids[y_]
            if j <= i:
                continue
            jl = Pi.boundary.intersection(sec_axis[j][1].buffer(0.05))
            if jl.length < JOIN_EDGE_M:
                continue
            mid_ = jl.centroid
            end = []
            for k_, sd in ((i, sid), (j, sjd)):
                subs = sorted((x for x in lay if x.rsplit("/", 1)[0] == sd), key=lambda x: int(x.rsplit("/", 1)[1]))
                ax_ = sec_axis[k_][0]
                e_ = 0 if shapely.Point(ax_.coords[0]).distance(mid_) < shapely.Point(ax_.coords[-1]).distance(mid_) else 1
                sub_ = subs[0] if e_ == 0 else subs[-1]
                sax = sub_axis[sub_][0]
                sv = 0.0 if e_ == 0 else sax.length
                end.append((sub_, e_, sax.interpolate(sv), tangent(sax, sv)))
            (A_, ea, pa, (ux, uy)), (B_, eb, pb, (vx, vy)) = end
            if abs(ux * vx + uy * vy) < JOIN_COS or lay[A_][0][0] is None or lay[B_][0][0] is None:
                continue
            sgn = 1 if ux * vx + uy * vy > 0 else -1
            c0 = (pb.x - pa.x) * -uy + (pb.y - pa.y) * ux       # B's axis, left of A's
            join_lanes(lay[A_], lay[B_], ea, eb, sgn, c0)

    # duckOSM's directed edges of each OSM way, for each lane's GMNS id (`<edge_id>_<lane_num>`, duckOSM's gmns_driving.lane.lane_id)
    edges_of = {}
    for eid, oid, w in rows(f"SELECT edge_id::VARCHAR, osm_id, {m()} FROM osm.driving.edges"):
        edges_of.setdefault(oid, []).append((eid, g(w)))

    def gmns_lane(way, ax, mid_t, sgn, num):
        """The GMNS id of a lane of OSM way `way`: the directed edge that runs the lane's way (sgn: +1 along the axis) nearest the lane's
        middle, and `num` (1 = the leftmost lane in the direction of travel); None if the way is not in duckOSM's driving network."""
        sv = ax.length / 2
        p = ax.interpolate(sv)
        ux, uy = tangent(ax, sv)
        q = shapely.Point(p.x - uy * mid_t, p.y + ux * mid_t)
        best = None
        for eid, ln in edges_of.get(way, []):
            ex, ey = tangent(ln, ln.project(q))
            if (ex * ux + ey * uy) * sgn > 0.3 and (best is None or ln.distance(q) < best[0]):
                best = (ln.distance(q), eid)
        return f"{best[1]}_{num}" if best else None

    # pass 3: the inside of each subsection
    lane_rec = []       # every travel lane: key (subsection, OSM way, direction along the way, lane from the right), its axis and middle
    arrow_req = []      # (subsection, axis, lane middle (start, end), +1 along the axis / -1, turn heads or None, OSM says, ref)
    for sub, (ax, L, R, i, Q) in sub_axis.items():
        cw, tl, tr, meds = meas[sub]["cw"], meas[sub]["tl"], meas[sub]["tr"], meas[sub]["meds"]
        fr, cws = lay[sub]
        kl, kr, kl_m, kr_m, swl, swr, edges = fr
        kerbs_of[sub] = (kl, kr, ax, L, R)
        road = cw[0]["road"] if cw else None
        ways = sorted({c["road"][0] for c in cw})
        wref = ", ".join(f"w{w}" for w in ways) or None
        common = dict(road=road[1] if road else None, road_class=road[2] if road else None,
                      road_lanes=sum(c["al"] + c["ag"] for c in cw) or None, oneway=all(c["ag"] == 0 or c["al"] == 0 for c in cw) if cw else None)
        e_l, e_r = edge_prov(L, ways), edge_prov(R, ways)
        if kl is None:
            add(sub, "sidewalk", Q, width_m=round(tl - tr, 2), width_method="derived", direction=None, lane=None, **common,
                **PV("urbanstyle", "derived", "no roadway along it"), **POS(both(e_l, e_r)))
            widths.append((sub, None, None, round(tl - tr, 2), 0.0, round(tl, 2), round(-tr, 2), 0, 0, None, "urbanstyle", None))
            continue
        # the pedestrian realm on each side, in NACTO's zones from the kerb out: buffer (furnishing), clear path (sidewalk), frontage
        for sg, kerb, edge, line_t, arm, k_pv, e_pv in ((1, kl, tl, min(swl) if swl else None, "left", kl_m, e_l),
                                                         (-1, kr, tr, max(swr) if swr else None, "right", kr_m, e_r)):
            line_t, line_id = line_t if line_t else (None, None)
            pos = POS(both(k_pv, e_pv))         # between the kerb and the block's edge
            km = mean(kerb)
            total = abs(edge - km)
            dist = lambda t: (t - km) * sg            # from the kerb, outwards

            def band(d1, d2, far=False, kerb=kerb, sg=sg):
                a_, b_ = kerb + sg * d1, kerb + sg * (d2 + (30 if far else 0))
                return band2(ax, a_, b_, Q) if sg > 0 else band2(ax, b_, a_, Q)
            if total < CLEAR_M:
                add(sub, "sidewalk", band(0, total, True), width_m=round(total, 2), width_method="derived", direction=None, lane=None, arm=arm, **common,
                    **PV("urbanstyle", "derived", "kerb to block, narrower than a clear path"), **pos)
                continue
            obs = [(dist(t), oid, s_) for t, oid, s_ in objects_in(ax, Q, sg) if 0 < dist(t) < total]
            ds = [d for d, _, _ in obs]
            f, f_m = (min(max(2 * statistics.median(ds), FURNISH_M[1]), FURNISH_M[2]), "measured") if len(ds) >= 2 else (FURNISH_M[0], "chosen")
            f_pv = prov_of([(s_ or "osm", f"object {oid}") for _, oid, s_ in obs], "measured", None) if len(ds) >= 2 else \
                ("urbanstyle", "chosen", f"no street object: {FURNISH_M[0]} m")
            if line_t is not None:      # the clear path around OSM's sidewalk line
                c0 = min(max(dist(line_t) - CLEAR_M / 2, 0.0), total - CLEAR_M)
                c_m = "measured"
            else:
                c0, c_m = min(f, total - CLEAR_M), "chosen"
            c1 = min(c0 + CLEAR_M, total)
            if total - c1 < FRONTAGE_MIN_M:
                c1 = total
            if c0 < FRONTAGE_MIN_M:         # no room for a buffer: the clear path reaches the kerb
                c0 = 0.0
            else:
                add(sub, "furnishing", band(0, c0), width_m=round(c0, 2), width_method=f_m if line_t is None else "derived", direction=None, lane=None, arm=arm,
                    **common, **PV(*(f_pv if line_t is None else ("osm", "derived", f"{line_id}: kerb to the clear path"))), **pos)
            add(sub, "sidewalk", band(c0, c1, c1 >= total), width_m=round(c1 - c0, 2), width_method=c_m, direction=None, lane=None, arm=arm, **common,
                **PV(*(("osm", "mapped", line_id) if line_t is not None else ("urbanstyle", "chosen", f"no sidewalk line: {CLEAR_M} m from the furnishing"))),
                **pos)
            if c1 < total:
                add(sub, "frontage", band(c1, total, True), width_m=round(total - c1, 2), width_method="derived", direction=None, lane=None, arm=arm, **common,
                    **PV(e_pv[0], "derived", "clear path to the block's edge"), **pos)
        mark(sub, "kerb", line2(ax, kl, Q), *kl_m)
        mark(sub, "kerb", line2(ax, kr, Q), *kr_m)
        k_both = both(kl_m, kr_m)
        for k in sorted(meas[sub]["isle"]):
            a_, b_ = edges[k][1], edges[k + 1][0]
            isl = ("osm", "derived", f"w{cw[k]['road'][0]}, w{cw[k + 1]['road'][0]}: two carriageways apart")
            add(sub, "island", band2(ax, a_, b_, Q), width_m=round(mean(b_ - a_), 2), width_method="derived", direction=None, lane=None, **common,
                **PV(*isl), **POS(isl))
            mark(sub, "kerb", line2(ax, a_, Q), *isl)
            mark(sub, "kerb", line2(ax, b_, Q), *isl)
        lin, lout, osm_total, lane_ws = 0, 0, 0, []
        sx, sP = sec_axis[i]
        for C, (lo, hi) in zip(cws, edges):
            c, rd, tg, fwd, osm_n, n, items, ie, n_al = (C[x] for x in ("c", "rd", "tg", "fwd", "osm_n", "n", "items", "ie", "n_al"))
            al_dir, ag_dir, shared, rule, lane_pv = (C[x] for x in ("al_dir", "ag_dir", "shared", "rule", "lane_pv"))
            side_pv = lambda typ, sd, pp=C["park_pv"], bp=C["bike_pv"]: (pp if typ == "parking" else bp).get(sd) or \
                ("urbanstyle", "derived", "the width holds it (the fit)")
            osm_total += osm_n or 0
            add(sub, "shoulder", band2(ax, lo, ie[0][0], Q), width_m=round(mean(ie[0][0] - lo), 2), width_method="derived", direction=None, lane=None,
                **common, **PV("urbanstyle", "derived", "the room left beside the lanes"), **POS(k_both))
            k_lane = 0
            first_t = None
            lane_at = []        # each travel lane's (right edge, left edge)
            for (typ, _), (t, t_) in zip(items, ie):
                w_ = t_ - t
                taper = min(w_) < 0.05 < max(w_)       # it opens or closes at a joint (join_lanes): its width is the full one
                w_m, rule_ = (max(w_), rule + "; a taper: zero width at a joint, where the next subsection has no such item") if taper \
                    else (mean(w_), rule)
                if typ == "lane":
                    along_ = k_lane < n_al
                    if first_t is None:
                        first_t = t
                    elif k_lane:
                        mark(sub, "centre line" if k_lane == n_al else "lane line", line2(ax, t, Q), *lane_pv)
                    # its GMNS id: lanes numbered from the left of their direction of travel (a lane both ways: each direction's id)
                    mt = float(mean(t + t_) / 2)
                    gid = ";".join(x for x in (gmns_lane(rd[0], ax, mt, 1, 1), gmns_lane(rd[0], ax, mt, -1, 1)) if x) if shared else \
                        gmns_lane(rd[0], ax, mt, 1 if along_ else -1, n_al - k_lane if along_ else k_lane - n_al + 1)
                    add(sub, "lane", band2(ax, t, t_, Q), width_m=round(w_m, 2), width_method="derived", lane_id=gid or None,
                        direction="both" if shared else al_dir if along_ else ag_dir, lane=(k_lane + 1) if along_ else (n - k_lane),
                        **common, rule=rule_, **PV(*lane_pv), **POS(k_both))
                    lane_ws.append(w_m)
                    lane_at.append((t, t_))
                    k_lane += 1
                else:
                    sd_ = 1 if first_t is not None else -1          # after the travel lanes: on the left
                    B = band2(ax, t, t_, Q)
                    if typ == "parking":    # where a bus stops at this kerb (behind its stop pole, in the travel direction): a bus zone
                        go = (1 if n_al == n else -1) if sd_ > 0 else (1 if n_al > 0 else -1)
                        zs = []          # [zone, its stops]
                        for st in stops:
                            if st["pt"].distance(B) <= STOP_KERB_M:
                                sp = ax.project(st["pt"])
                                a0, a1 = sorted((sp - go * BUS_ZONE_M, sp + go * 2.0))
                                cut_ = substring(extend(ax, 60.0), max(a0, -60) + 60, min(a1, ax.length + 60) + 60).buffer(60.0, cap_style="flat")
                                z = poly(B.intersection(cut_, grid_size=0.01))
                                if z.area >= 1.0:
                                    zs.append([z, [st]])
                        # (two stops near each other at one kerb: one bus zone that names both; their own zones overlapped, Monaco
                        # 2026-10-13, U9)
                        joined = True
                        while joined:
                            joined = False
                            for i in range(len(zs)):
                                for j in range(i + 1, len(zs)):
                                    if zs[i][0].intersection(zs[j][0]).area > 0.5:
                                        zs[i] = [poly(zs[i][0].union(zs[j][0])), zs[i][1] + zs[j][1]]
                                        del zs[j]
                                        joined = True
                                        break
                                if joined:
                                    break
                        for z, sts in zs:
                            name_ = lambda st: f"{st['id']} " + (st["tags"].get("name") or (st["tt"] or {}).get("name") or "bus stop") + \
                                (f" (stop {st['tags']['ref']})" if st["tags"].get("ref") else "")
                            when = "; ".join(w for w in (gt.describe(st["tt"]) for st in sts) if w)
                            add(sub, "bus zone", z, width_m=round(w_m, 2), width_method="derived", direction=None, lane=None, **common,
                                rule="no parking: buses stop here" + (f"; {when}" if when else ""),
                                **PV(", ".join(sorted({st["source"] for st in sts})), "mapped", "; ".join(name_(st) for st in sts)),
                                **POS(k_both))
                        B = poly(B.difference(shapely.union_all([z for z, _ in zs]), grid_size=0.01)) if zs else B
                    add(sub, typ, B, width_m=round(w_m, 2), width_method="derived", direction=None, lane=None,
                        **common, rule=rule_, **PV(*side_pv(typ, sd_)), **POS(k_both))
                    # its line on the side of the travel lanes: after them its near edge, before them its far edge
                    mark(sub, "edge line", line2(ax, t if first_t is not None else t_, Q), *side_pv(typ, sd_))
            t = ie[-1][1]
            add(sub, "shoulder", band2(ax, t, hi, Q), width_m=round(mean(hi - t), 2), width_method="derived", direction=None, lane=None, **common,
                **PV("urbanstyle", "derived", "the room left beside the lanes"), **POS(k_both))
            lin += n - n_al
            lout += n_al
            # arrows: OSM's turn:lanes on the lanes running into an intersection (each direction's lanes, its left to its right); elsewhere
            # a straight arrow (painted after the crosswalks, clear of them)
            oneway_ = c["ag"] == 0 or c["al"] == 0
            groups = {True: list(range(n_al))[::-1], False: list(range(n_al, n))}
            turns = {}
            for grp, key in ((groups[fwd], "turn:lanes:forward"), (groups[not fwd], "turn:lanes:backward")):
                val = tg.get(key) or (tg.get("turn:lanes") if oneway_ and key.endswith("forward") else None)
                vals = val.split("|") if val else []
                if grp and len(vals) == len(grp):
                    for li, v in zip(grp, vals):
                        turns[li] = {TURN[w] for w in v.split(";") if w in TURN}
            if shared:      # its one lane, each way: no arrow
                for sgn, d_ in ((1, al_dir), (-1, ag_dir)):
                    end = ax.length if sgn > 0 else 0.0
                    lane_rec.append(dict(key=(sub, rd[0], d_, 1), ax=ax, mid=sum(lane_at[0]) / 2, sgn=sgn, w=mean(lane_at[0][1] - lane_at[0][0]),
                                         at_j=any(x.distance(ax.interpolate(end)) < ARM_M + 1 for x in inter),
                                         at_s=any(x.distance(ax.interpolate(ax.length - end)) < ARM_M + 1 for x in inter)))
                lane_at = []
            for li, (a_, b_) in enumerate(lane_at):
                sgn = 1 if li < n_al else -1
                end = ax.length if sgn > 0 else 0.0
                at_j = any(x.distance(ax.interpolate(end)) < ARM_M + 1 for x in inter)
                key_ = (sub, rd[0], al_dir if sgn > 0 else ag_dir, (li + 1) if sgn > 0 else (n - li))
                lane_rec.append(dict(key=key_, ax=ax, mid=(a_ + b_) / 2, sgn=sgn, w=mean(b_ - a_), at_j=at_j,
                                     at_s=any(x.distance(ax.interpolate(ax.length - end)) < ARM_M + 1 for x in inter)))
                arrow_req.append((sub, ax, (a_ + b_) / 2, sgn, turns.get(li) if at_j else None, li in turns and at_j, f"w{rd[0]}", key_))
            # stop lines: across the lanes that run toward an end at an intersection, STOP_BACK_M before it
            for end, toward in ((ax.length, True), (0.0, False)):
                e = 1 if toward else 0
                ls = lane_at[:n_al] if toward else lane_at[n_al:]
                if not ls or ls[-1][1][e] - ls[0][0][e] < 0.5:
                    continue
                sv = end - STOP_BACK_M if toward else end + STOP_BACK_M
                p = ax.interpolate(sv)
                if not any(x.distance(ax.interpolate(end)) < ARM_M + 1 for x in inter):
                    continue
                ux, uy = tangent(ax, sv)
                t0_, t1_ = ls[0][0][e], ls[-1][1][e]
                ln = shapely.LineString([(p.x - uy * t0_, p.y + ux * t0_), (p.x - uy * t1_, p.y + ux * t1_)])
                mark(sub, "stop line", lines(ln.intersection(Q)), "osm", "derived", f"w{rd[0]} runs into a junction")
        widths.append((sub, None, None, round(tl - tr, 2), round(mean(kl - kr), 2), round(tl - mean(kl), 2), round(mean(kr) - tr, 2), lin, lout,
                       round(statistics.median(lane_ws or [0]), 2), "urbanstyle", osm_total or None))

    # ---- the inside of each intersection: a pedestrian corner where two arms' kerbs meet at a block, the junction area the rest
    def _halfplane(ax, t, sg, at_end):
        """The side of the kerb line at offset t of the axis (left if sg = 1) that holds the block, as a large polygon near one end."""
        sv = ax.length if at_end else 0.0
        p = ax.interpolate(sv)
        ux, uy = tangent(ax, sv)
        nx, ny = -uy * sg, ux * sg                     # towards the block
        bx, by = p.x - uy * t, p.y + ux * t           # on the kerb line
        L_ = 200.0
        return shapely.Polygon([(bx - ux * L_, by - uy * L_), (bx + ux * L_, by + uy * L_),
                                (bx + ux * L_ + nx * L_, by + uy * L_ + ny * L_), (bx - ux * L_ + nx * L_, by - uy * L_ + ny * L_)])

    for iid, X in zip(inter_ids, inter):
        arms = []       # (subsection, at its end, its kerb offsets)
        for sub, (kl, kr, ax, L, R) in kerbs_of.items():
            if kl is None:
                continue
            for at_end in (False, True):
                if ax.interpolate(ax.length if at_end else 0.0).distance(X) < ARM_M + 1.5 and sub_axis[sub][4].distance(X) < 0.1:
                    arms.append((sub, at_end, kl, kr, ax, L, R))
        corners = []
        for k in set([a[5] for a in arms] + [a[6] for a in arms]):
            hp = []
            for sub, at_end, kl, kr, ax, L, R in arms:
                if k == L:
                    hp.append(_halfplane(ax, kl[int(at_end)], 1, at_end))
                if k == R:
                    hp.append(_halfplane(ax, kr[int(at_end)], -1, at_end))
            if not hp:
                continue
            c = X
            for h in hp:
                c = c.intersection(h)
            if k >= 0:      # only the corner of this block: near it
                c = c.intersection(bgeo[k].buffer(RAY_M / 2))
            corners.append(poly(c))
        walkway = poly(shapely.union_all(corners)) if corners else shapely.Polygon()
        # (a corner never covers a road OSM maps: a road whose line runs through a corner for more than CORNER_ROAD_M takes its
        # carriageway back, as wide as the road, as junction area. At Monaco's Place Sainte-Dévote, a roundabout and 24 nodes, the
        # corners' half-planes ran across the roads: 4609 m2 of "sidewalk" on the roadway, i0-25193377; Kaveh, 2026-10-13. Every road
        # in the intersection took 2230 m2 of Vancouver's real corners: OSM's widths are wider than the kerbs)
        cw = [roads[k][7].buffer(max(roads[k][4] or LANE_M, LANE_M) / 2, cap_style="flat") for k in road_tree.query(X)
              if roads[k][2] != "pedestrian" and roads[k][7].intersection(walkway).length > CORNER_ROAD_M]
        if cw and not walkway.is_empty:
            walkway = poly(walkway.difference(shapely.union_all(cw), grid_size=0.01))
        roadway = poly(X.difference(walkway, grid_size=0.01))
        if not roadway.is_empty:    # the kerb's corner rounded
            roadway = poly(roadway.buffer(KERB_RADIUS_M, quad_segs=4, join_style="round").buffer(-KERB_RADIUS_M, quad_segs=4, join_style="round")
                           .intersection(X, grid_size=0.01))
            walkway = poly(X.difference(roadway, grid_size=0.01))
        nodes_ = ", ".join(f"n{n_}" for j_, n_, _, _ in junction if j_ == iid) or None
        kp = [sec_kerbs[sub_axis[a[0]][3]] for a in arms if sub_axis[a[0]][3] in sec_kerbs]
        a_pv = prov_of([(s_, x) for k_ in kp for pv in (k_[2], k_[3]) for s_ in pv[0].split("+") for x in (pv[2] or "").split(", ")[:3] if x],
                       "derived", ("urbanstyle", "derived", None))
        add(iid, "junction area", roadway, width_m=None, width_method=None, direction=None, lane=None, road=None, road_class=None,
            road_lanes=None, oneway=None, **PV("osm", "derived", f"the junction of {nodes_}" if nodes_ else None), **POS(a_pv))
        add(iid, "sidewalk", walkway, width_m=None, width_method="derived", direction=None, lane=None, road=None, road_class=None,
            road_lanes=None, oneway=None, **PV("urbanstyle", "derived", "where two arms' kerbs meet at a block"), **POS(a_pv))
        k_ = roadway.boundary.intersection(walkway.buffer(0.02)) if not roadway.is_empty and not walkway.is_empty else shapely.LineString()
        # (no kerb across an arm's roadway where it enters: a hairline of walkway left by the rounding drew one across the ends of the
        # lanes, at i0-616471133 across lane s0-w48524371r.2~w48524377r/3#9 and its cycle lane, at 40 more junctions too; Kaveh, 2026-10-12)
        arm_road = [r_["geom"] for r_ in parts if r_["type"] in ROADWAY and r_["unit_id"] in {a_[0] for a_ in arms} and r_["geom"].distance(X) < 0.5]
        mouths = [g_.boundary.intersection(X.buffer(0.3)) for g_ in arm_road]       # (each one's end edge where it enters the junction)
        if mouths and not k_.is_empty:
            k_ = k_.difference(shapely.union_all(mouths).buffer(0.4))
        if not k_.is_empty and k_.length > 0.5:
            mark(iid, "kerb", lines(k_.intersection(X.buffer(0.01))), a_pv[0], "derived", a_pv[2])
        widths.append((iid, None, None, None, None, None, None, None, None, None, "urbanstyle", None))

    # ---- barriers: two carriageways that OSM never joins (no node in common) stay apart through a junction too: where islands between
    # the same two ways lie on both sides of an intersection, a barrier joins their facing ends across it, and no move crosses it (Fir
    # Street northbound and the Granville Bridge ramp at West 8th Avenue: no way from one to the other there; Kaveh, 2026-10-11)
    import shapely.ops
    isles = [p for p in parts if p["type"] == "island" and str(p.get("ref") or "").endswith("two carriageways apart")]
    pair_ids = {int(w) for p in isles for w in re.findall(r"w(\d+)", p["ref"])}
    way_refs = {o: set(r) for o, r in rows("SELECT osm_id, refs FROM osm.raw.ways WHERE osm_id IN (SELECT unnest(?::BIGINT[]))", [sorted(pair_ids)])}
    bars = []
    for i, p in enumerate(isles):
        for q in isles[i + 1:]:
            if p["ref"] != q["ref"] or p["unit_id"] == q["unit_id"]:
                continue
            wa, wb = (int(w) for w in re.findall(r"w(\d+)", p["ref"]))
            a_, b_ = shapely.ops.nearest_points(p["geom"], q["geom"])
            link = shapely.LineString([a_, b_])
            if link.length > BARRIER_SPAN_M or not any(link.intersection(x).length > 0.5 * link.length for x in inter):
                continue
            if any(x.buffer(1.0).contains(nodes[n]) for x in inter for n in (way_refs.get(wa, set()) & way_refs.get(wb, set())) if n in nodes):
                continue            # OSM joins the two ways at a node in that junction: a real junction between them
            bars.append((link.buffer(BARRIER_W_M / 2, cap_style="flat"), f"w{wa}, w{wb}: no node in common in this junction"))
    BAR = shapely.union_all([b for b, _ in bars]) if bars else None
    if bars:
        for p in parts:             # each space the barrier crosses gives it room: its parts cut, the barrier one of them
            if p["geom"].intersects(BAR):
                p["geom"] = p["geom"].difference(BAR)
        for b, ref_ in bars:
            for uid, U in [(i_, x) for i_, x in zip(inter_ids, inter)] + [(u_[0], u_[3]) for u_ in units if u_[1] != "intersection"]:
                if U.intersects(b):
                    add(uid, "barrier", b.intersection(U), width_m=BARRIER_W_M, width_method="chosen", direction=None, lane=None,
                        **PV("urbanstyle", "derived", ref_), **POS(("urbanstyle", "derived", ref_)))

    # ---- SUMO on our lanes: duckOSM's driving network to SUMO (sumo.network) with the lanes fitted here (count and width of each
    # direction of each OSM way, where its edge runs); SUMO decides which lane goes on to which. Its connections are drawn as guide lines
    # from our in-lane's end to our out-lane's start (space.turn), and give the turn arrows (space.approach)
    from . import sumo
    sumo_net, sumo_heads, turn_rows, approach_rows = None, {}, [], []
    by_way = {}
    for lr in lane_rec:
        by_way.setdefault((lr["key"][1], lr["key"][2]), []).append(lr)
    dir_edges = rows(f"SELECT edge_id::VARCHAR, osm_id, is_reverse, {m()}, source, target FROM osm.driving.edges")
    # space.turn names the road piece (space.element's source_id, as parts.py does): a directed edge's undirected piece
    piece_of = {(o, min(a, b), max(a, b)): str(sid) for sid, o, a, b in rows("""SELECT source_id, osm_id, src, dst FROM space.element
                                                                             WHERE type = 'road' AND src IS NOT NULL AND dst IS NOT NULL""")}
    elem_id = {}
    attrs, edge_way = {}, {}
    way_line = {}
    for r in roads:
        way_line.setdefault(r[0], []).append(r[7])
    for de, oid, rev, w, a_, b_ in dir_edges:
        elem_id[de] = piece_of.get((oid, min(a_, b_), max(a_, b_)), de)
        if rev is None:     # no is_reverse: against its OSM way where it runs the other way along it
            el_ = way_line.get(oid)
            ge_ = g(w)
            if el_ and ge_.length > 0:
                c_ = ge_.interpolate(0.5, normalized=True)
                ln_ = min(el_, key=lambda x: x.distance(c_))
                ex, ey = tangent(ge_, ge_.length / 2)
                wx, wy = tangent(ln_, ln_.project(c_))
                rev = ex * wx + ey * wy < 0
        d_ = "backward" if rev else "forward"
        edge_way[de] = (oid, d_)
        cand_ = by_way.get((oid, d_))
        if not cand_:
            continue
        mid_ = g(w).interpolate(0.5, normalized=True)
        units_ = {}
        for lr in cand_:
            units_.setdefault(lr["key"][0], []).append(lr)
        near_ = min(units_.items(), key=lambda kv: sub_axis[kv[0]][4].distance(mid_))
        if sub_axis[near_[0]][4].distance(mid_) > 15.0:
            continue
        attrs[de] = {"numLanes": len(near_[1]), "width": round(min(max(statistics.median([lr["w"] for lr in near_[1]]), 2.5), 4.5), 2)}
    if attrs:
        sumo_net = sumo.network(con, attrs, epsg)
    if sumo_net is not None and os.environ.get("US_SUMO_REPORT"):     # a check of SUMO's output against what it was given
        import pickle
        pickle.dump(dict(attrs=attrs, lanes=[(e, i, n, w, k) for e, i, n, w, k, _ in sumo_net["lanes"]], conns=[c_[:5] + (c_[6],) for c_ in sumo_net["conns"]],
                         edge_way=edge_way, ends=sumo_net["ends"]), open(os.environ["US_SUMO_REPORT"], "wb"))
    if sumo_net is not None:
        way_ = {"s": "straight", "l": "left", "L": "left", "r": "right", "R": "right"}     # SUMO's dir; "t", a u-turn, is left out
        old_cond = {(f, t_): c_ for f, t_, c_ in rows("SELECT from_edge, to_edge, any_value(condition) FROM space.turn WHERE level = 0 GROUP BY 1, 2")}
        itree_ = shapely.STRtree(inter) if inter else None

        def lane_end(lr, out_):
            """(point, heading) where a lane meets its junction: an in-lane's end, an out-lane's start."""
            ax_, sgn_ = lr["ax"], lr["sgn"]
            s_ = (ax_.length if sgn_ > 0 else 0.0) if not out_ else (0.0 if sgn_ > 0 else ax_.length)
            s_ = min(max(s_ - sgn_ * STOP_BACK_M if not out_ else s_, 0.0), ax_.length)
            q = ax_.interpolate(s_)
            ux, uy = tangent(ax_, s_)
            o = lr["mid"][0] + (lr["mid"][1] - lr["mid"][0]) * s_ / ax_.length
            return (q.x - uy * o, q.y + ux * o), (ux * sgn_, uy * sgn_)

        moves, miss_, lane_edge, drawn, pairs_ = {}, {}, {}, set(), set()
        def inter_at(pt):
            """The intersection (its index) a lane's end at pt touches."""
            k_ = [k for k in (itree_.query(pt.buffer(ARM_M + 2)) if itree_ is not None else []) if inter[k].distance(pt) < ARM_M + 2]
            return min(k_, key=lambda k: inter[k].distance(pt), default=None)
        rw_of = {}

        def roadway_at(k):
            """The roadway in and around intersection k: its junction area and the roadway of the spaces that touch it."""
            if k not in rw_of:
                near = [p["geom"] for p in parts if p["type"] in ROADWAY and (p["unit_id"] == inter_ids[k] or
                        (p["unit_id"] in sub_axis and sub_axis[p["unit_id"]][4].distance(inter[k]) < 0.1))]
                rw_of[k] = shapely.union_all([x.buffer(0.05) for x in near]) if near else inter[k]
            return rw_of[k]
        # a junction of several OSM nodes (a divided road crossing another) can hold SUMO edges of its own, between the nodes SUMO did not
        # join: a move is followed through them, from the lane coming in to the lane going out
        egeom = {de: g(w) for de, _, _, w, _, _ in dir_edges}
        inside_ = {}

        def inside_k(de):
            if de not in inside_:
                ge, inside_[de] = egeom.get(de), None
                if ge is not None and ge.length > 0:
                    a_, b_ = shapely.Point(ge.coords[0]), shapely.Point(ge.coords[-1])
                    for k in (itree_.query(ge) if itree_ is not None else []):
                        if inter[k].distance(a_) < 1.0 and inter[k].distance(b_) < 1.0:     # both its ends in the junction
                            inside_[de] = k
                            break
            return inside_[de]
        succ = {}
        for f, fl, t_, tl, dr, xy, veh in sumo_net["conns"]:
            succ.setdefault((f, fl), []).append((t_, tl, dr, veh))
        composed = {}
        for f, fl, t_, tl, dr, xy, veh in sumo_net["conns"]:
            if dr not in way_:
                continue
            if inside_k(t_) is None:
                composed.setdefault((f, fl, t_, tl), (dr, veh))
                continue
            stack, seen = [(t_, tl, veh, 0)], set()
            while stack:
                e_, l_, v_, d_ = stack.pop()
                if (e_, l_) in seen or d_ > 5:
                    continue
                seen.add((e_, l_))
                for t2, tl2, dr2, veh2 in succ.get((e_, l_), []):
                    if dr2 == "t":
                        continue
                    v2 = veh2 if veh2 is not None else v_       # open to some vehicles only if any step is
                    if inside_k(t2) is None:
                        composed.setdefault((f, fl, t2, tl2), (None, v2))      # its turn: from the two lanes' directions
                    else:
                        stack.append((t2, tl2, v2, d_ + 1))
        sumo.log.info(f"SUMO moves: {len(composed)}, {sum(1 for d in composed.values() if d[0] is None)} through a junction's own edges; "
                      f"edges inside a junction: {sum(1 for v in inside_.values() if v is not None)}")
        # our lanes at each junction, with their ends: an in-lane's end (at its stop line), an out-lane's start
        at_k = {}
        for lr in lane_rec:
            for out_ in (False, True):
                if lr["at_s"] if out_ else lr["at_j"]:
                    p_, h_ = lane_end(lr, out_)
                    k = inter_at(shapely.Point(p_))
                    if k is not None:
                        at_k.setdefault((k, out_), []).append((lr, p_, h_))

        def find(edge, lane, out_):
            """Our lane for SUMO's `edge` by its geometry (not its OSM way: a way can end mid-block, at a back lane): the edge must end
            (an out-edge: start) in one of our junctions and run the lane's way there; of the lanes of that approach (one subsection,
            one way, one direction) nearest to the edge, number lane + 1 from the right, or the nearest number we have."""
            ge = egeom.get(edge)
            if ge is None or ge.length == 0:
                return None
            k = inter_at(shapely.Point(ge.coords[0] if out_ else ge.coords[-1]))
            if k is None:
                return None         # a node mid-block (a back lane, a driveway): no junction of ours
            ex, ey = tangent(ge, 0.0 if out_ else ge.length)
            c_ = [(lr, p_) for lr, p_, h_ in at_k.get((k, out_), []) if h_[0] * ex + h_[1] * ey > 0.7]
            if not c_:
                return None
            by_ = {}
            for lr, p_ in c_:
                by_.setdefault(lr["key"][:3], []).append((lr, p_))
            grp = min(by_.values(), key=lambda g_: min(shapely.Point(p_).distance(ge) for _, p_ in g_))
            return min((lr for lr, _ in grp), key=lambda lr: (abs(lr["key"][3] - (lane + 1)), lr["key"][3]))
        for (f, fl, t_, tl), (dr, veh) in composed.items():
            lin_, lout_ = find(f, fl, False), find(t_, tl, True)
            jin = inter_at(shapely.Point(lane_end(lin_, False)[0])) if lin_ is not None else None
            if lout_ is not None and inter_at(shapely.Point(lane_end(lout_, True)[0])) != jin:
                lout_ = None        # its out-lane leaves another junction: not this move's
            turn_ = way_.get(dr)
            if turn_ is None and lin_ is not None and lout_ is not None:
                (_, ha_), (_, hb_) = lane_end(lin_, False), lane_end(lout_, True)
                ang = math.degrees(math.atan2(ha_[0] * hb_[1] - ha_[1] * hb_[0], ha_[0] * hb_[0] + ha_[1] * hb_[1]))
                turn_ = None if abs(ang) > 150 else "straight" if abs(ang) < 30 else "left" if ang > 0 else "right"
            if turn_ is None:
                miss_["no turn" + (" (through)" if dr is None else "")] = miss_.get("no turn" + (" (through)" if dr is None else ""), 0) + 1
                continue
            if BAR is not None and lin_ is not None and lout_ is not None and \
                    shapely.LineString([lane_end(lin_, False)[0], lane_end(lout_, True)[0]]).intersects(BAR):
                miss_["across a barrier"] = miss_.get("across a barrier", 0) + 1
                continue
            if lin_ is not None and jin is not None:
                moves.setdefault(lin_["key"], set())
                lane_edge[lin_["key"]] = f
                if veh is None:
                    moves[lin_["key"]].add(turn_)
            if lin_ is not None and lout_ is not None and (lin_["key"], lout_["key"]) in pairs_:
                continue            # the same move, reached two ways
            if lin_ is None or lout_ is None or jin is None:
                why_ = ("no lane in" if lin_ is None else "not in a junction" if jin is None else "no lane out") + (" (through)" if dr is None else "")
                miss_[why_] = miss_.get(why_, 0) + 1
                continue
            (pa, ha), (pb, hb) = lane_end(lin_, False), lane_end(lout_, True)
            # the curve, pulled toward the junction's middle until it stays on the roadway (a tight corner's kerb)
            road_, mid_ = roadway_at(jin), inter[jin].centroid
            best = None
            for pull in (0.0, 0.25, 0.5, 0.75, 1.0):
                gl = curve(pa, ha, pb, hb, pull, (mid_.x, mid_.y))
                off_ = gl.difference(road_).length
                if best is None or off_ < best[0]:
                    best = (off_, gl)
                if off_ < 0.1:
                    break
            gl = best[1]
            uid = inter_ids[jin]
            ref_ = f"SUMO {f}_{fl} > {t_}_{tl} ({turn_}" + (", through the junction's own edges" if dr is None else "") + \
                   f"); w{edge_way[f][0]} > w{edge_way[t_][0]}"
            mark(uid, "guide line", gl, "sumo", "derived", ref_)
            turn_rows.append((uid, elem_id.get(f, f), fl + 1, elem_id.get(t_, t_), tl + 1, turn_, "sumo", veh,
                              old_cond.get((elem_id.get(f, f), elem_id.get(t_, t_))), gl))
            drawn.add(lin_["key"])
            pairs_.add((lin_["key"], lout_["key"]))
        sumo_heads = {k: v for k, v in moves.items() if v}
        sumo.log.info(f"SUMO: {len(sumo_net['conns'])} connections, {len(turn_rows)} drawn; not drawn: {miss_}; lanes into a junction "
                      f"{sum(lr['at_j'] for lr in lane_rec)}, with a move {sum(1 for lr in lane_rec if lr['at_j'] and moves.get(lr['key']))}, "
                      f"with a guide line {sum(1 for lr in lane_rec if lr['at_j'] and lr['key'] in drawn)}")
        for lr in lane_rec:
            if lr["at_j"]:
                end_ = shapely.Point(lane_end(lr, False)[0])
                k_ = [k for k in (itree_.query(end_.buffer(ARM_M + 2)) if itree_ is not None else [])]
                uid = min(k_, key=lambda k: inter[k].distance(end_), default=None)
                de_ = elem_id.get(lane_edge.get(lr["key"]), lane_edge.get(lr["key"]))
                approach_rows.append([inter_ids[uid] if uid is not None else None, de_, lr["key"][3], len(moves.get(lr["key"], ())),
                                      ",".join(sorted(moves.get(lr["key"], ()))), lr["key"]])

    # ---- crosswalks: where OSM maps a marked crossing over the roadway (a crossing way, else a crossing point with no way near it), a band
    # CROSSWALK_M wide and its zebra bars across it, ZEBRA_BAR_M wide, ZEBRA_GAP_M apart; they lie on the lanes and the junction area,
    # cutting nothing
    rw_by = {}
    for p in parts:
        if p["type"] in ROADWAY:
            rw_by.setdefault(p["unit_id"], []).append(p["geom"])
    rw_by = {u: shapely.union_all([x.buffer(0.02) for x in xs]) for u, xs in rw_by.items()}
    rw_all = shapely.union_all(list(rw_by.values())) if rw_by else shapely.Polygon()
    rw_ids = list(rw_by)
    rw_t = shapely.STRtree([rw_by[u] for u in rw_ids]) if rw_ids else None
    bands = []          # (band, walking direction, ref, source)
    for oid, typ, cl in crossings:
        for s_ in shapely.get_parts(cl.intersection(rw_all)):
            if s_.geom_type != "LineString" or s_.length < 1.0:
                continue
            c0, c1 = s_.coords[0], s_.coords[-1]
            h = math.hypot(c1[0] - c0[0], c1[1] - c0[1]) or 1
            if typ == "walkway" and oid not in unmarked:
                bands.append((s_.buffer(CROSSWALK_M / 2, cap_style="flat").intersection(rw_all), ((c1[0] - c0[0]) / h, (c1[1] - c0[1]) / h), f"w{oid}"))
    for oid, cl, pt in cross_pts:
        if rw_all.distance(pt) > 0.5 or any(pt.distance(x) < SAME_CROSSING_M for _, _, x in crossings):
            continue
        near = [roads[k][7] for k in road_tree.query(pt.buffer(CROSS_ON_M))]
        ln = min(near, key=lambda r: r.distance(pt)) if near else None
        if ln is None or ln.distance(pt) > CROSS_ON_M:
            continue
        tx, ty = tangent(ln, ln.project(pt))
        q = ln.interpolate(ln.project(pt))
        H, L_ = CROSSWALK_M / 2, 30.0
        rect = shapely.Polygon([(q.x - tx * H - ty * L_, q.y - ty * H + tx * L_), (q.x + tx * H - ty * L_, q.y + ty * H + tx * L_),
                                (q.x + tx * H + ty * L_, q.y + ty * H - tx * L_), (q.x - tx * H + ty * L_, q.y - ty * H - tx * L_)])
        bands.append((rect.intersection(rw_all), (-ty, tx), str(oid)))
    for band, (wx, wy), ref in bands:
        band = poly(band)
        if band.is_empty:
            continue
        c_ = band.centroid
        L_ = max(band.bounds[2] - band.bounds[0], band.bounds[3] - band.bounds[1]) + 2
        k = -L_
        while k <= L_:
            mx, my = c_.x + wx * k, c_.y + wy * k
            bar = shapely.LineString([(mx - wy * L_, my + wx * L_), (mx + wy * L_, my - wx * L_)]).intersection(band.buffer(-0.1))
            if not bar.is_empty:
                for j in rw_t.query(bar):
                    mark(rw_ids[j], "zebra", lines(bar.intersection(rw_by[rw_ids[j]])), src="osm", method="mapped", ref=ref)
            k += ZEBRA_BAR_M + ZEBRA_GAP_M
    xw = shapely.union_all([b for b, _, _ in bands]) if bands else shapely.Polygon()
    painted = set()     # lanes with an arrow

    # ---- arrows: a shaft ARROW_M long to its tip and a head for each way the lane may go (arrow_shape)

    for sub, ax, mid, sgn, ways, said, ref, key_ in arrow_req:
        L_ = ax.length
        src_ = ("osm", "mapped")
        if sumo_net is not None:        # SUMO's connections decide the heads (it reads OSM's turn:lanes where they are)
            heads_ = sumo_heads.get(key_)
            ways = heads_ if heads_ and any(lr["key"] == key_ and lr["at_j"] for lr in lane_rec) else None
            src_ = ("osm+sumo", "mapped") if said else ("sumo", "derived")
        turn = bool(ways)
        if turn:            # the tip 1 m before the stop line
            s_tip = L_ - STOP_BACK_M - 1.0 if sgn > 0 else STOP_BACK_M + 1.0
        elif L_ >= 20.0:    # a straight arrow in the middle of a long subsection
            s_tip, ways = L_ / 2 + sgn * ARROW_M / 2, {"straight"}
        else:
            continue
        for d in range(0, 11):      # back from the junction (or along) until clear of every crosswalk
            st = s_tip - sgn * d if turn else s_tip + (d // 2 + d % 2) * (1 if d % 2 else -1)
            if not (ARROW_M <= st <= L_ if sgn > 0 else 0 <= st <= L_ - ARROW_M):
                continue
            ux, uy = tangent(ax, st)
            def at(s, ux=ux, uy=uy):
                q = ax.interpolate(s)
                o = mid[0] + (mid[1] - mid[0]) * s / L_
                return (q.x - uy * o, q.y + ux * o)
            shape = arrow_shape(at(st), (ux * sgn, uy * sgn), ways)
            if shape.buffer(0.5).intersects(xw):
                continue
            mark(sub, "arrow", shape, src=src_[0] if turn else "osm", method=src_[1] if turn else "derived",
                 ref=ref + ("" if turn else ": a lane of this direction"))
            painted.add(key_)
            break

    # ---- driveways: where a road inside a block (an alley, a driveway, a parking aisle) crosses the pedestrian realm of a subsection, or at
    # OSM's parking entrance by a car park, the realm is a driveway there (flush with the road) and the kerb is open
    REALM = ("sidewalk", "furnishing", "frontage")
    realm = {}
    for p in parts:
        if p["type"] in REALM and p["unit_id"] in sub_axis:
            realm.setdefault(p["unit_id"], []).append(p)
    drives = {}         # subsection -> [(polygon, width, ref)]
    for oid, wd, sv in services:
        w = wd or DRIVEWAY_M
        for sub, ps in realm.items():
            ax = sub_axis[sub][0]
            for x in shapely.get_parts(sv.intersection(shapely.union_all([p["geom"] for p in ps]))):
                if x.geom_type != "LineString" or x.length < 0.5:
                    continue
                ux, uy = tangent(ax, ax.project(x.centroid))
                c0, c1 = x.coords[0], x.coords[-1]
                h = math.hypot(c1[0] - c0[0], c1[1] - c0[1]) or 1
                if abs((c1[0] - c0[0]) * ux + (c1[1] - c0[1]) * uy) / h > 0.7:     # along the street, not across it
                    continue
                # the apron is the road's mouth: the gap between the city's parcels where it enters the block, carried straight across the
                # realm to the kerb (else OSM's width about the crossing)
                sc = ax.project(x.centroid)
                q_ = ax.interpolate(sc)
                sg = 1 if (x.centroid.x - q_.x) * -uy + (x.centroid.y - q_.y) * ux > 0 else -1
                k_ = sub_axis[sub][1] if sg > 0 else sub_axis[sub][2]
                lo_, hi_ = sc - w / 2, sc + w / 2
                wpv = ("osm", "mapped") if wd else ("urbanstyle", "chosen")
                if parcel_u is not None and k_ is not None and k_ >= 0:
                    edge_ = bgeo[k_].boundary

                    def open_at(s_):        # no parcel just inside the block's edge, square across from s_
                        p_ = extend(ax, 60.0).interpolate(s_ + 60.0)
                        tx_, ty_ = tangent(extend(ax, 60.0), s_ + 60.0)
                        ray = shapely.LineString([(p_.x, p_.y), (p_.x - sg * ty_ * RAY_M, p_.y + sg * tx_ * RAY_M)])
                        hit = ray.intersection(edge_)
                        if hit.is_empty:
                            return False
                        h_ = min(shapely.get_parts(hit), key=lambda z: z.distance(p_))
                        inside = shapely.Point(h_.x - sg * ty_ * 0.75, h_.y + sg * tx_ * 0.75) if h_.geom_type == "Point" else None
                        return inside is not None and not parcel_u.contains(inside)
                    if open_at(sc):
                        a_ = b_ = sc
                        while a_ > sc - 15 and open_at(a_ - 0.25):
                            a_ -= 0.25
                        while b_ < sc + 15 and open_at(b_ + 0.25):
                            b_ += 0.25
                        if 2.0 <= b_ - a_ < 30.0:
                            lo_, hi_, wpv = a_, b_, ("vancouver", "measured")
                strip = substring(extend(ax, 60.0), lo_ + 60.0, hi_ + 60.0).buffer(60.0, cap_style="flat")
                half = strip.intersection(extend(ax, 60.0).buffer(sg * 60.0, single_sided=True))
                ds_ = drives.setdefault(sub, [])
                same_ = [d for d in ds_ if d[2] == f"w{oid}" and d[0].intersects(half)]
                if same_:       # one road crossing one side once: one apron
                    ds_.remove(same_[0])
                    half = half.union(same_[0][0])
                ds_.append((half, round(hi_ - lo_, 2), f"w{oid}", wpv))
    for oid, pt in entrances:
        if not lots or min(l.distance(pt) for l in lots) > ENTRANCE_M:
            continue
        cand_ = [(shapely.union_all([p["geom"] for p in ps]).distance(pt), sub) for sub, ps in realm.items()]
        d, sub = min(cand_, default=(1e9, None))
        if sub is None or d > ENTRANCE_M or any(dp.distance(pt) < 6.0 for dp, *_ in drives.get(sub, [])):
            continue
        ax = sub_axis[sub][0]
        sv = ax.project(pt)
        ux, uy = tangent(ax, sv)
        q, H, L_ = ax.interpolate(sv), DRIVEWAY_M / 2, 60.0
        rect = shapely.Polygon([(q.x - ux * H - uy * L_, q.y - uy * H + ux * L_), (q.x + ux * H - uy * L_, q.y + uy * H + ux * L_),
                                (q.x + ux * H + uy * L_, q.y + uy * H - ux * L_), (q.x - ux * H + uy * L_, q.y - uy * H - ux * L_)])
        side = 1 if (pt.x - q.x) * -uy + (pt.y - q.y) * ux > 0 else -1      # only the realm on the entrance's side
        half = rect.intersection(extend(ax, 60.0).buffer(side * L_, single_sided=True))
        drives.setdefault(sub, []).append((half, DRIVEWAY_M, str(oid), ("urbanstyle", "chosen")))
    reach = {}          # every subsection an apron reaches (one near a joint opens the kerb on both sides of it)
    for ds in drives.values():
        for D, w, ref, wpv in ds:
            for sub, ps in realm.items():
                if any(p["geom"].intersects(D) for p in ps):
                    reach.setdefault(sub, []).append((D, w, ref, wpv))
    for sub, ds in reach.items():
        for D, w, ref, wpv in ds:
            got = []
            for p in realm[sub]:
                x = poly(p["geom"].intersection(D, grid_size=0.01))
                if x.area < 0.5:
                    continue
                p["geom"] = poly(p["geom"].difference(D, grid_size=0.01))
                got.append(x)
            if got:
                add(sub, "driveway", poly(shapely.union_all(got)), width_m=round(w, 2), width_method=wpv[1],
                    direction=None, lane=None, road=None, road_class=None, road_lanes=None, oneway=None,
                    **PV("osm", "mapped", (ref if ref.startswith("w") else f"parking entrance {ref}")), **POS(("osm", "mapped", ref)),
                    width_source=wpv[0])
        cut = shapely.union_all([D for D, *_ in ds]).buffer(0.3)
        marks[:] = [(u, ty, (lines(x.difference(cut)) if u == sub and ty == "kerb" else x), *r_) for u, ty, x, *r_ in marks]
    marks[:] = [m_ for m_ in marks if m_[2] is not None and not m_[2].is_empty]
    parts[:] = [p for p in parts if not p["geom"].is_empty]

    # ---- no crumbs: a strip under PIECE_MIN_M2 joins its neighbour in the same space (never a lane or a shoulder, either way: they keep
    # their own shape, so the roadway's items meet the next subsection's at the joint)
    by_unit = {}
    for p in parts:
        by_unit.setdefault(p["unit_id"], []).append(p)
    for uid, ps in by_unit.items():
        for p in sorted(ps, key=lambda p: p["geom"].area):
            if p["geom"].area >= PIECE_MIN_M2 or p["type"] in ("lane", "shoulder", "junction area") or p.get("gone"):
                continue
            nb = [q for q in ps if q is not p and not q.get("gone") and q["type"] != "lane" and q["geom"].distance(p["geom"]) < 0.05]
            same = [q for q in nb if (q["type"] in ROADWAY) == (p["type"] in ROADWAY)]
            nb = same if p["type"] in ROADWAY else (same or nb)    # a crumb of roadway joins the roadway (or stays), one of the realm the realm
            if not nb:
                continue
            q = max(nb, key=lambda q: q["geom"].boundary.intersection(p["geom"].boundary.buffer(0.05)).length)
            q["geom"] = poly(shapely.union_all([q["geom"], p["geom"]], grid_size=0.01))
            p["gone"] = True
    parts = [p for p in parts if not p.get("gone")]

    # ---- write: the level-0 spaces and their insides replace those of spaces.py / parts.py
    to_ll = f"ST_Transform(ST_GeomFromWKB(?), '{epsg}', 'EPSG:4326', always_xy := true)"
    old = [u for (u,) in rows("SELECT unit_id FROM space.unit WHERE level = 0")]
    for t, cols in SCHEMA.items():      # each table with its types, whatever made it
        have = {c for (c,) in rows(f"SELECT column_name FROM information_schema.columns WHERE table_schema = 'space' AND table_name = '{t}'")}
        q_ = lambda c: f'"{c}"'
        if have:
            con.execute(f"CREATE OR REPLACE TABLE space.{t} AS SELECT " + ", ".join(
                (f"CAST({q_(c)} AS {ty}) AS {q_(c)}" if c in have else f"CAST(NULL AS {ty}) AS {q_(c)}") for c, ty in cols.items()) + f" FROM space.{t}")
        else:
            con.execute(f"CREATE TABLE space.{t} (" + ", ".join(f"{q_(c)} {ty}" for c, ty in cols.items()) + ")")
    turns = rows(f"SELECT rowid, {m('ST_Centroid(geometry)')} FROM space.turn WHERE level = 0")
    for t, col in (("part", "unit_id"), ("mark", "unit_id"), ("width", "unit_id"), ("approach", "unit_id")):
        try:
            con.execute(f"DELETE FROM space.{t} WHERE level = 0")
        except duckdb.Error:
            pass
    for t in ("cut", "junction", "subsection"):
        con.execute(f"DELETE FROM space.{t} WHERE level = 0")
    if sumo_net is not None:    # SUMO on our lanes: its connections replace the level-0 turns
        con.execute("DELETE FROM space.turn WHERE level = 0")
        if turn_rows:
            con.executemany(f"""INSERT INTO space.turn (unit_id, level, from_edge, from_lane, to_edge, to_lane, turn, source, vehicles, condition, geometry)
                                VALUES (?, 0, ?, ?, ?, ?, ?, ?, ?, ?, {to_ll})""", [r_[:-1] + (shapely.to_wkb(r_[-1]),) for r_ in turn_rows])
        if approach_rows:
            con.executemany("""INSERT INTO space.approach (unit_id, level, from_edge, lane, moves, ways, arrow, no_arrow_because) VALUES (?, 0, ?, ?, ?, ?, ?, ?)""",
                            [(u, de, ln, mv, ws, k in painted, None if k in painted else ("no move" if not mv else "another arrow in the way"))
                             for u, de, ln, mv, ws, k in approach_rows])
    elif turns:     # each turn to the new intersection holding its middle
        itree = shapely.STRtree(inter)
        moved = []
        for rid, w in turns:
            c_ = g(w)
            k = [k for k in itree.query(c_) if inter[k].distance(c_) < 1.0]
            moved.append((inter_ids[k[0]] if k else None, rid))
        con.executemany("UPDATE space.turn SET unit_id = ? WHERE rowid = ?", moved)
        con.execute("DELETE FROM space.turn WHERE level = 0 AND unit_id IS NULL")
    con.execute("DELETE FROM space.unit WHERE level = 0")
    if decks:       # a deck taken as the street at ground level: its old level-1 spaces go too
        dk = shapely.union_all(decks)
        # its spaces: those along the deck, and every piece of the deck's own container (a crumb at its end holds little of its line)
        own = {c for (c,) in rows(f"""SELECT DISTINCT container_id FROM space.element WHERE type = 'road' AND level_min = 1
                                         AND osm_id IN ({",".join(str(r[0]) for r in roads if r[7] in decks)})""")}
        gone = [u for u, w in rows(f"SELECT unit_id, {m()} FROM space.unit WHERE level = 1")
                if g(w).intersection(dk).length > 5.0 or u.split("/")[0] in own]
        for u in gone:
            for t in ("part", "mark", "width", "turn", "approach"):
                try:
                    con.execute(f"DELETE FROM space.{t} WHERE unit_id = ?", [u])
                except duckdb.Error:
                    pass
            for t, col in (("cut", "intersection_id"), ("junction", "intersection_id"), ("subsection", "subsection_id")):
                try:
                    con.execute(f"DELETE FROM space.{t} WHERE {col} = ?", [u])
                except duckdb.Error:
                    pass
            con.execute("DELETE FROM space.unit WHERE unit_id = ?", [u])
    con.executemany(f"INSERT INTO space.unit (unit_id, kind, section_id, level, color, geometry) VALUES (?, ?, ?, 0, ?, {to_ll})",
                    [(u, k, s, COLORS[k], shapely.to_wkb(x)) for u, k, s, x in units])
    if cut_rows:
        con.executemany(f"INSERT INTO space.cut (intersection_id, edge_id, level, how, length_m, geometry) VALUES (?, ?, 0, 'block corner + 3 m', ?, {to_ll})",
                        [(i, e, round(c.length, 2), shapely.to_wkb(c)) for i, e, c in cut_rows])
    if junction:
        con.executemany("INSERT INTO space.junction (intersection_id, node_id, level, cluster_id) VALUES (?, ?, ?, ?)", junction)
    srow = []
    for sub, sid, sax, Q, s, why in sub_rows:
        kl, kr = kerbs_of.get(sub, (None, None))[:2]
        cl = next((p["road_class"] for p in parts if p["unit_id"] == sub and p.get("road_class")), None)
        ow = next((p["oneway"] for p in parts if p["unit_id"] == sub and p.get("oneway") is not None), None)
        srow.append((sub, sid, cl, None if kl is None else round(float(kl.mean() - kr.mean()), 2), ow, round(sax.length, 1),
                     bid[s["left"]] if s["left"] >= 0 else "edge", bid[s["right"]] if s["right"] >= 0 else "edge", why, shapely.to_wkb(sax)))
    if srow:
        con.executemany(f"""INSERT INTO space.subsection (subsection_id, section_id, level, class, width_m, oneway, length_m, "left", "right",
                            starts_at, color, geometry) VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?, '#e6194b', {to_ll})""", srow)
    if parts:
        con.executemany(f"""INSERT INTO space.part (unit_id, part_id, level, type, arm, direction, lane, lane_id, width_m, width_source, width_method,
                            length_m, source, method, ref, position_source, position_method, position_ref, road, road_class, road_lanes, oneway, rule,
                            geometry) VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {to_ll})""",
                        [(p["unit_id"], p["part_id"], p["type"], p.get("arm"), p.get("direction"), p.get("lane"), p.get("lane_id"), p.get("width_m"),
                          p.get("width_source") or "urbanstyle", p.get("width_method"), round(p["geom"].length / 2, 1), p.get("source") or "urbanstyle",
                          p.get("method") or "derived", p.get("ref"), p.get("position_source"), p.get("position_method"), p.get("position_ref"),
                          p.get("road"), p.get("road_class"), p.get("road_lanes"), p.get("oneway"), p.get("rule"), shapely.to_wkb(p["geom"])) for p in parts])
    if marks:
        con.executemany(f"""INSERT INTO space.mark (unit_id, level, type, length_m, width_m, width_source, width_method, source, method, ref, geometry)
                            VALUES (?, 0, ?, ?, ?, 'urbanstyle', 'chosen', ?, ?, ?, {to_ll})""",
                        [(u, t, round(x.length, 1), LINE.get(t), s_, me, r, shapely.to_wkb(x)) for u, t, x, s_, me, r in marks])
    if widths:
        con.executemany("""INSERT INTO space.width (unit_id, level, edge, arm, total_m, carriageway_m, left_m, right_m, lanes_in, lanes_out, lane_m, source,
                           osm_lanes) VALUES (?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", widths)
    return dict(old_units=len(old), subsections=sum(1 for u in units if u[1] == "subsection"), intersections=len(inter),
                sections=len(section_ids), parts=len(parts), marks=len(marks))
