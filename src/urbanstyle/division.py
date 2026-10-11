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
import statistics

STEP_M, SAMPLE_M, RAY_M, FACE_DEG = 1.0, 0.5, 80.0, 30.0   # shares: points along outlines; facing tested every; how far; along within
MAX_POINTS = 60000       # the shares from at most this many points
OPENING_M = 40.0         # an edge of the area crossing a street, shorter than this, is a street opening: the outside is no neighbour there
ARM_M = 3.0              # an intersection reaches into each arm past the block corner (its crosswalk, stop line)
SUB_MIN_M = 12.0         # a subsection is at least this long: changes closer together are one cut
LANE_M = 3.25            # a lane's width where nothing measures it
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
BASIN_BACK_M = 0.3       # a catch basin sits in the gutter: the kerb is this far behind it
OBJ_KERB_M = 0.4         # a pole, a tree, a meter stands at least this far behind the kerb
SHOULDER_EDGE_M = 0.3    # every carriageway keeps a shoulder this wide at each edge (the gutter); more where the lanes leave room
FURNISH_M = (1.0, 0.6, 2.5)  # the pedestrian realm's buffer (furniture) zone at the kerb: where nothing stands in it; at least; at most
CLEAR_M = 1.8            # the clear path, where nothing measures it
FRONTAGE_MIN_M = 0.75    # a frontage or buffer zone narrower than this is the clear path's
ROADWAY = ("lane", "shoulder", "parking", "cycle lane", "junction area")
PIECE_MIN_M2 = 5.0       # a strip smaller than this (in a very short subsection) joins the neighbouring strip it shares the most edge with
STOP_BACK_M = 1.0        # a stop line stands this far before the section's end at an intersection
STREET = ("motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street", "pedestrian")
from .parts import (ARROW_M, CROSS_ON_M, CROSSWALK_M, DRIVEWAY_M, LINE, SAME_CROSSING_M,  # noqa: E402  (a line's width, as parts.py
                    ZEBRA_BAR_M, ZEBRA_GAP_M)                                            #  paints it and the dashboard draws it)
TURN = {"left": "left", "slight_left": "left", "sharp_left": "left", "through": "straight", "right": "right", "slight_right": "right",
        "sharp_right": "right"}    # OSM's turn:lanes values, as the heads of a painted arrow
ENTRANCE_M = 15.0        # a parking entrance this close to a car park and to the street opens the kerb there
COLORS = {"subsection": "#94a3b8", "intersection": "#fbbf24"}
V, D, I, G_ = "VARCHAR", "DOUBLE", "INTEGER", "GEOMETRY"
SCHEMA = {
    "unit": dict(unit_id=V, kind=V, section_id=V, level=I, color=V, geometry=G_),
    "part": dict(unit_id=V, part_id=V, level=I, type=V, arm=V, direction=V, lane=I, width_m=D, width_source=V, width_method=V, length_m=D,
                 source=V, method=V, ref=V, road=V, road_class=V, speed=V, surface=V, lit=V, road_lanes=V, oneway=V, holds=V, rule=V, geometry=G_),
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


def build(con, epsg):
    import duckdb
    import numpy as np
    import shapely
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
    bid = [i for i, _ in blocks]
    bgeo = [x for _, x in blocks]
    street = poly(box.difference(shapely.union_all(bgeo), grid_size=0.01))
    short = lambda k: "edge" if k == -1 else bid[k][3:] if bid[k].startswith("b0-") else bid[k]

    # ---- shares and middle lines
    openings = shapely.union_all([x for x in shapely.get_parts(shapely.line_merge(box.exterior.intersection(street.buffer(0.01))))
                                  if x.length < OPENING_M] or [shapely.Point()]).buffer(0.05)
    pts, owner, seen = [], [], set()
    edge_near = box.exterior.intersection(shapely.union_all(bgeo).buffer(2 * RAY_M))
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
    targets = [(k, b) for k, b in enumerate(bgeo)] + [(-1, box.exterior)]
    ttree = shapely.STRtree([t for _, t in targets])
    cosf = math.cos(math.radians(FACE_DEG))

    def tangent(line, s):
        a, b = line.interpolate(max(s - 1, 0)), line.interpolate(min(s + 1, line.length))
        dx, dy = b.x - a.x, b.y - a.y
        h = (dx * dx + dy * dy) ** .5 or 1
        return dx / h, dy / h

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
                e0 = line.interpolate(s0).distance(box.exterior) < 2.0
                e1 = line.interpolate(s1).distance(box.exterior) < 2.0
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
    # the streets' roads: at level 0, and on a deck at level 1 where nothing at ground level passes under it (works, not a bridge), as
    # for the blocks: such a deck is the street at ground level
    cand = [(oid, n, cl, bool(ow), wd, src, dst, g(w), lv) for oid, n, cl, ow, wd, src, dst, w, lv in rows(f"""SELECT osm_id, name, class,
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
    walks = [g(w) for (w,) in rows(f"""SELECT {m()} FROM space.element WHERE type = 'walkway' AND level_min = 0
                                      AND coalesce(subtype, '') <> 'crossing'""")]
    walk_tree = shapely.STRtree(walks) if walks else None
    crossings = [(oid, typ, g(w)) for oid, typ, w in rows(f"""SELECT osm_id, type, {m()} FROM space.element WHERE type IN ('walkway', 'cycleway')
                                                  AND level_min = 0 AND subtype = 'crossing'""")]
    unmarked = {oid for (oid,) in rows("""SELECT osm_id FROM osm.raw.ways WHERE tags['crossing'] = 'unmarked' OR tags['crossing:markings'] = 'no'""")}
    cross_pts = [(oid, cl, g(w)) for oid, cl, w in rows(f"""SELECT object_id, class, {m()} FROM space.object WHERE level = 0
                                                         AND class IN ('crossing.zebra', 'crossing.signalised')""")]
    # roads inside the blocks (alleys, driveways, parking aisles) and OSM's parking entrances: where the street opens to them
    services = [(oid, wd, g(w)) for oid, wd, w in rows(f"""SELECT osm_id, width_m, {m()} FROM space.element WHERE type = 'road'
                                                         AND level_min = 0 AND replace(class, '_link', '') NOT IN {STREET}""")]
    lots = [g(w) for (w,) in rows(f"SELECT {m()} FROM space.lot")]
    entrances = [(oid, g(w)) for oid, w in rows(f"SELECT object_id, {m()} FROM space.object WHERE level = 0 AND class = 'access.parking_entrance'")]

    objs = [g(w) for (w,) in rows(f"SELECT {m()} FROM space.object WHERE level = 0")]
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
    basins = [x for _, x in city_geoms("sewer-catch-basins")]
    behind = [x for n in ("street-lighting-poles", "public-trees", "parking-meters") for _, x in city_geoms(n)]     # stand behind the kerb
    meters = [x for _, x in city_geoms("parking-meters")]
    city_walks = [x for _, gm in city_geoms("sidewalk-condition-rating") for x in shapely.get_parts(gm) if x.geom_type == "LineString"]
    bikeways = [(pr, x) for pr, x in city_geoms("bikeways") if any(k in str(pr.get("bikeway_type") or "") for k in ("Painted", "Protected", "Separated"))]
    tree_of = lambda xs: shapely.STRtree(xs) if xs else None
    basin_t, behind_t, meter_t, cwalk_t = tree_of(basins), tree_of(behind), tree_of(meters), tree_of(city_walks)
    bike_t = tree_of([x for _, x in bikeways])
    osm_tags = {oid: dict(t or {}) for oid, t in rows("SELECT osm_id, tags FROM osm.raw.ways WHERE osm_id IN (SELECT DISTINCT osm_id FROM space.element WHERE type = 'road' AND level_min IN (0, 1))")}
    otree = shapely.STRtree(objs) if objs else None

    def objects_in(ax, Q, sg):
        """The offsets (left +) of the street objects standing in Q on one side of the axis."""
        out = []
        for k in (otree.query(Q) if otree is not None else []):
            o = objs[k]
            if not Q.contains(o):
                continue
            q = ax.interpolate(ax.project(o))
            ux, uy = tangent(ax, ax.project(o))
            t = (o.x - q.x) * -uy + (o.y - q.y) * ux
            if t * sg > 0:
                out.append(t)
        return out

    def lanes_of(r, along):
        """(lanes going along the axis, lanes going against it) of road r, `along` whether the road's own direction is the axis's."""
        oid, n, cl, ow, wd = r[:5]
        f, bk = lanes.get((oid, False)), lanes.get((oid, True))
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
    names = {}
    section_ids = {}
    for i in sorted(secgeo, key=lambda i: (short(secs[i]["left"]), short(secs[i]["right"]))):
        s = secs[i]
        base = f"s0-{min(short(s['left']), short(s['right']))}~{max(short(s['left']), short(s['right']))}"
        names[base] = names.get(base, 0) + 1
        section_ids[i] = base + (f".{names[base]}" if names[base] > 1 else "")

    def straight(line):
        c = line.coords
        chord = shapely.LineString([c[0], c[-1]])
        return chord if max(chord.distance(shapely.Point(p)) for p in c) < 1.0 else line.simplify(0.5)

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
        axis = straight(axis)
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
        while len(runs) > 1 and min(r[1] - r[0] for r in runs) < SUB_MIN_M:   # a short run joins the longer neighbour
            j = min(range(len(runs)), key=lambda j: runs[j][1] - runs[j][0])
            nb = j - 1 if j == len(runs) - 1 or (j > 0 and runs[j - 1][1] - runs[j - 1][0] >= runs[j + 1][1] - runs[j + 1][0]) else j + 1
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

    def section_kerbs(i, outer_l, outer_r):
        """One kerb on each side of a whole section (left +, right -), top-down from the evidence along its whole length:
        OSM's and the city's sidewalk lines (the kerb SIDEWALK_HALF_M before them) and the city's catch basins (in the gutter); the city's
        poles, trees and meters stand behind it. Else the carriageways' edge (OSM's lanes x LANE_M)."""
        if i in sec_kerbs:
            return sec_kerbs[i]
        ax, P = sec_axis[i]
        ev = {1: [], -1: []}
        swl, swr = [], []
        for src, tree, lines in (("osm", walk_tree, walks), ("vancouver", cwalk_t, city_walks)):
            for k in (tree.query(P) if tree is not None else []):
                t = along(ax, lines[k], P)
                if t is not None and abs(t) > 1.0:
                    sg = 1 if t > 0 else -1
                    ev[sg].append(t - sg * SIDEWALK_HALF_M)
                    if src == "osm":
                        (swl if sg > 0 else swr).append(t)
        for k in (basin_t.query(P) if basin_t is not None else []):
            if P.contains(basins[k]):
                t = offset(ax, basins[k])
                if abs(t) > 1.0:
                    ev[1 if t > 0 else -1].append(t + (BASIN_BACK_M if t > 0 else -BASIN_BACK_M))
        lim = {1: [], -1: []}
        for k in (behind_t.query(P) if behind_t is not None else []):
            if P.contains(behind[k]):
                t = offset(ax, behind[k])
                lim[1 if t > 0 else -1].append(t)
        out = []
        for sg, outer in ((1, outer_l), (-1, outer_r)):
            # the evidence nearest the road holds (a second sidewalk line, a basin across a wide boulevard, lie farther out)
            e = sorted((t for t in ev[sg] if sg * t > sg * outer - 1.0), key=lambda t: abs(t))   # (a footway on a median is no kerb)
            e = [t for t in e if abs(t) <= abs(e[0]) + 2.0] if e else []
            k_, me = (statistics.median(e), "measured") if e else (outer, "chosen")
            l = sorted(lim[sg], key=lambda t: abs(t))
            if len(l) >= 2:      # behind the innermost poles and trees (the second nearest: one odd point does not decide)
                cap = l[1] - sg * OBJ_KERB_M
                if sg * k_ > sg * cap:
                    k_, me = cap, ("measured" if me == "measured" else "derived")
            out.append((k_, me))
        sec_kerbs[i] = (out[0][0], out[1][0], out[0][1], out[1][1], swl, swr)
        return sec_kerbs[i]

    def fit(W, osm_n, al_share, oneway, park, bike, weight=1.5):
        """The most likely cross-section of a carriageway W wide (top-down): travel lanes, a parking lane and a bike lane at each side
        (park / bike: per side +1 / -1, True where the evidence says so, False where it says no, None where it says nothing), a gutter at
        each kerb. Evidence counts as hints; the width decides. Returns (score, n, parking sides, bike sides)."""
        best = None
        for n in range(1, 7):
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
        kl_s, kr_s, kl_m, kr_m, swl, swr = section_kerbs(i, outer_l, outer_r)
        kl, kr = V(0.0), V(0.0)
        for e, (bl, br) in enumerate([block_at(i, s0), block_at(i, s1)]):
            kl[e], kr[e] = min(kl_s, bl - MIN_REALM_M), max(kr_s, br + MIN_REALM_M)
            if kl[e] <= kr[e]:
                kl[e], kr[e] = (bl + br) / 2 + 0.01, (bl + br) / 2 - 0.01
        # the roadway: carriageways right to left, a median between them, a shoulder where the kerb stands wider
        edges = []
        for k, c in enumerate(cw):
            edges.append([kr.copy() if k == 0 else None, kl.copy() if k == len(cw) - 1 else None])
        for k, ((a0, b0), (a1, b1)) in sorted(meds.items()):      # a median where two carriageways stand apart, else the line between them
            m_ = 1.0 if k in meas[sub]["isle"] else 0.0
            edges[k][1], edges[k + 1][0] = np.maximum(V(a0, a1), kr + m_), np.minimum(V(b0, b1), kl - m_)
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

    # pass 3: the inside of each subsection
    arrow_req = []      # (subsection, axis, lane middle (start, end), +1 along the axis / -1, turn heads or None, OSM says, ref)
    for sub, (ax, L, R, i, Q) in sub_axis.items():
        cw, tl, tr, meds = meas[sub]["cw"], meas[sub]["tl"], meas[sub]["tr"], meas[sub]["meds"]
        kl, kr, kl_m, kr_m, swl, swr, edges = frame(sub)
        kerbs_of[sub] = (kl, kr, ax, L, R)
        road = cw[0]["road"] if cw else None
        common = dict(road=road[1] if road else None, road_class=road[2] if road else None,
                      road_lanes=sum(c["al"] + c["ag"] for c in cw) or None, oneway=all(c["ag"] == 0 or c["al"] == 0 for c in cw) if cw else None,
                      ref=",".join(sorted({f"w{c['road'][0]}" for c in cw})) or None)
        if kl is None:
            add(sub, "sidewalk", Q, width_m=round(tl - tr, 2), width_method="derived", direction=None, lane=None, **common)
            widths.append((sub, None, None, round(tl - tr, 2), 0.0, round(tl, 2), round(-tr, 2), 0, 0, None, "urbanstyle", None))
            continue
        # the pedestrian realm on each side, in NACTO's zones from the kerb out: buffer (furnishing), clear path (sidewalk), frontage
        for sg, kerb, edge, line_t, arm in ((1, kl, tl, min(swl) if swl else None, "left"), (-1, kr, tr, max(swr) if swr else None, "right")):
            km = mean(kerb)
            total = abs(edge - km)
            dist = lambda t: (t - km) * sg            # from the kerb, outwards

            def band(d1, d2, far=False, kerb=kerb, sg=sg):
                a_, b_ = kerb + sg * d1, kerb + sg * (d2 + (30 if far else 0))
                return band2(ax, a_, b_, Q) if sg > 0 else band2(ax, b_, a_, Q)
            if total < CLEAR_M:
                add(sub, "sidewalk", band(0, total, True), width_m=round(total, 2), width_method="derived", direction=None, lane=None, arm=arm, **common)
                continue
            ds = [dist(t) for t in objects_in(ax, Q, sg) if 0 < dist(t) < total]
            f, f_m = (min(max(2 * statistics.median(ds), FURNISH_M[1]), FURNISH_M[2]), "measured") if len(ds) >= 2 else (FURNISH_M[0], "chosen")
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
                add(sub, "furnishing", band(0, c0), width_m=round(c0, 2), width_method=f_m if line_t is None else "derived", direction=None, lane=None, arm=arm, **common)
            add(sub, "sidewalk", band(c0, c1, c1 >= total), width_m=round(c1 - c0, 2), width_method=c_m, direction=None, lane=None, arm=arm, **common)
            if c1 < total:
                add(sub, "frontage", band(c1, total, True), width_m=round(total - c1, 2), width_method="derived", direction=None, lane=None, arm=arm, **common)
        mark(sub, "kerb", line2(ax, kl, Q, LINE["kerb"]), method=kl_m)
        mark(sub, "kerb", line2(ax, kr, Q, LINE["kerb"]), method=kr_m)
        for k in sorted(meas[sub]["isle"]):
            a_, b_ = edges[k][1], edges[k + 1][0]
            add(sub, "island", band2(ax, a_, b_, Q), width_m=round(mean(b_ - a_), 2), width_method="derived", direction=None, lane=None, **common)
            mark(sub, "kerb", line2(ax, a_, Q, LINE["kerb"]))
            mark(sub, "kerb", line2(ax, b_, Q, LINE["kerb"]))
        lin, lout, osm_total, lane_ws = 0, 0, 0, []
        sx, sP = sec_axis[i]
        for c, (lo, hi) in zip(cw, edges):
            rd = c["road"]
            tg = osm_tags.get(rd[0], {})
            fwd = c["fw"]
            side_of = lambda tag_side: (-1 if tag_side == "right" else 1) * (1 if fwd else -1)   # OSM's right of the way, as our side
            park, bike = {1: None, -1: None}, {1: None, -1: None}
            for k_, v in tg.items():
                if k_.startswith(("parking:lane:", "parking:")) and not k_.endswith(("restriction", "reason", "fee", "maxstay", "orientation")):
                    part_ = k_.split(":")[-1] if k_.count(":") == 1 else k_.split(":")[2] if k_.startswith("parking:lane:") else k_.split(":")[1]
                    yes = v not in ("no", "none", "separate", "no_parking", "no_stopping")
                    for sd in ((side_of("left"), side_of("right")) if part_ == "both" else (side_of(part_),) if part_ in ("left", "right") else ()):
                        park[sd] = yes
                if k_.startswith("cycleway") and k_.count(":") <= 1:
                    part_ = k_.split(":")[1] if ":" in k_ else "both"
                    yes = v in ("lane", "track", "buffered_lane", "opposite_lane")
                    for sd in ((side_of("left"), side_of("right")) if part_ == "both" else (side_of(part_),) if part_ in ("left", "right") else ()):
                        bike[sd] = yes if (yes or v in ("no", "none", "shared_lane")) else bike[sd]
            # the city's parking meters and bike lanes near a kerb, along the whole section (one short subsection does not decide alone)
            for sd, kerb_t in ((1, hi), (-1, lo)):
                kline = line_at(sx, mean(kerb_t), sP, 6.0)
                if kline is not None and meter_t is not None and any(kline.contains(meters[k]) for k in meter_t.query(kline)):
                    park[sd] = True
                if kline is not None and bike_t is not None and any(bikeways[k][1].intersection(kline).length > 10 for k in bike_t.query(kline)):
                    bike[sd] = True
            osm_n = c["al"] + c["ag"] if (tg.get("lanes") or tg.get("lanes:forward") or tg.get("lanes:backward")) else None
            hint_n = osm_n or (1 if (c["ag"] == 0 or c["al"] == 0) else 2)     # no lane tag: one lane each way (chosen), a weaker hint
            room = hi - lo
            key = (i, rd[0], fwd)
            if key not in fits:
                fits[key] = fit(statistics.median(rooms.get(key) or [mean(room)]), hint_n, None, c["ag"] == 0 or c["al"] == 0, park, bike,
                                1.5 if osm_n else 0.8)
            sc, n, pk, bk = fits[key]
            osm_total += osm_n or 0
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
            rule = f"fit: {n} lanes" + (f" (OSM: {osm_n})" if osm_n else " (OSM: none)") + \
                   "".join(f", parking {('left' if sd > 0 else 'right')}" for sd in (1, -1) if pk[sd]) + \
                   "".join(f", bike lane {('left' if sd > 0 else 'right')}" for sd in (1, -1) if bk[sd])
            t = lo.copy()
            add(sub, "shoulder", band2(ax, t, t + gut, Q), width_m=round(mean(gut), 2), width_method="derived", direction=None, lane=None, **common)
            t = t + gut
            k_lane = 0
            first_t = None
            lane_at = []        # each travel lane's (right edge, left edge)
            for (typ, _), w_ in zip(items, ws):
                if typ == "lane":
                    along_ = k_lane < n_al
                    if first_t is None:
                        first_t = t
                    elif k_lane:
                        mark(sub, "centre line" if k_lane == n_al else "lane line", line2(ax, t, Q, LINE["centre line"]), ref=f"w{rd[0]}")
                    add(sub, "lane", band2(ax, t, t + w_, Q), width_m=round(mean(w_), 2), width_method="derived",
                        direction=al_dir if along_ else ag_dir, lane=(k_lane + 1) if along_ else (n - k_lane),
                        **{**common, "ref": f"w{rd[0]}"}, rule=rule)
                    lane_ws.append(mean(w_))
                    lane_at.append((t, t + w_))
                    k_lane += 1
                else:
                    add(sub, typ, band2(ax, t, t + w_, Q), width_m=round(mean(w_), 2), width_method="derived", direction=None, lane=None,
                        **common, rule=rule)
                    # its line on the side of the travel lanes: after them its near edge, before them its far edge
                    mark(sub, "edge line", line2(ax, t if first_t is not None else t + w_, Q))
                t = t + w_
            add(sub, "shoulder", band2(ax, t, hi, Q), width_m=round(mean(hi - t), 2), width_method="derived", direction=None, lane=None, **common)
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
            for li, (a_, b_) in enumerate(lane_at):
                sgn = 1 if li < n_al else -1
                end = ax.length if sgn > 0 else 0.0
                at_j = any(x.distance(ax.interpolate(end)) < ARM_M + 1 for x in inter)
                arrow_req.append((sub, ax, (a_ + b_) / 2, sgn, turns.get(li) if at_j else None, li in turns and at_j, f"w{rd[0]}"))
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
                mark(sub, "stop line", lines(ln.intersection(Q)), ref=f"w{rd[0]}")
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
        roadway = poly(X.difference(walkway, grid_size=0.01))
        if not roadway.is_empty:    # the kerb's corner rounded
            roadway = poly(roadway.buffer(KERB_RADIUS_M, quad_segs=4, join_style="round").buffer(-KERB_RADIUS_M, quad_segs=4, join_style="round")
                           .intersection(X, grid_size=0.01))
            walkway = poly(X.difference(roadway, grid_size=0.01))
        add(iid, "junction area", roadway, width_m=None, width_method=None, direction=None, lane=None, road=None, road_class=None,
            road_lanes=None, oneway=None, ref=None)
        add(iid, "sidewalk", walkway, width_m=None, width_method="derived", direction=None, lane=None, road=None, road_class=None,
            road_lanes=None, oneway=None, ref=None)
        k_ = roadway.boundary.intersection(walkway.buffer(0.02)) if not roadway.is_empty and not walkway.is_empty else shapely.LineString()
        if not k_.is_empty and k_.length > 0.5:
            mark(iid, "kerb", lines(k_.intersection(X.buffer(0.01))))
        widths.append((iid, None, None, None, None, None, None, None, None, None, "urbanstyle", None))

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

    # ---- arrows: a shaft ARROW_M long to its tip and a head for each way the lane may go (parts.py's shape)
    def arrow_shape(tip, h, ways):
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

    for sub, ax, mid, sgn, ways, said, ref in arrow_req:
        L_ = ax.length
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
            mark(sub, "arrow", shape, src="osm" if turn else "urbanstyle", method="mapped" if turn else "derived", ref=ref)
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
                drives.setdefault(sub, []).append((sv.buffer(w / 2, cap_style="flat"), w, f"w{oid}"))
    for oid, pt in entrances:
        if not lots or min(l.distance(pt) for l in lots) > ENTRANCE_M:
            continue
        cand_ = [(shapely.union_all([p["geom"] for p in ps]).distance(pt), sub) for sub, ps in realm.items()]
        d, sub = min(cand_, default=(1e9, None))
        if sub is None or d > ENTRANCE_M or any(dp.distance(pt) < 6.0 for dp, _, _ in drives.get(sub, [])):
            continue
        ax = sub_axis[sub][0]
        sv = ax.project(pt)
        ux, uy = tangent(ax, sv)
        q, H, L_ = ax.interpolate(sv), DRIVEWAY_M / 2, 60.0
        rect = shapely.Polygon([(q.x - ux * H - uy * L_, q.y - uy * H + ux * L_), (q.x + ux * H - uy * L_, q.y + uy * H + ux * L_),
                                (q.x + ux * H + uy * L_, q.y + uy * H - ux * L_), (q.x - ux * H + uy * L_, q.y - uy * H - ux * L_)])
        side = 1 if (pt.x - q.x) * -uy + (pt.y - q.y) * ux > 0 else -1      # only the realm on the entrance's side
        half = rect.intersection(extend(ax, 60.0).buffer(side * L_, single_sided=True))
        drives.setdefault(sub, []).append((half, DRIVEWAY_M, str(oid)))
    reach = {}          # every subsection an apron reaches (one near a joint opens the kerb on both sides of it)
    for ds in drives.values():
        for D, w, ref in ds:
            for sub, ps in realm.items():
                if any(p["geom"].intersects(D) for p in ps):
                    reach.setdefault(sub, []).append((D, w, ref))
    for sub, ds in reach.items():
        for D, w, ref in ds:
            got = []
            for p in realm[sub]:
                x = poly(p["geom"].intersection(D, grid_size=0.01))
                if x.area < 0.5:
                    continue
                p["geom"] = poly(p["geom"].difference(D, grid_size=0.01))
                got.append(x)
            if got:
                add(sub, "driveway", poly(shapely.union_all(got)), width_m=round(w, 2), width_method="mapped" if w != DRIVEWAY_M else "chosen",
                    direction=None, lane=None, road=None, road_class=None, road_lanes=None, oneway=None, ref=ref)
        cut = shapely.union_all([D for D, _, _ in ds]).buffer(0.3)
        marks[:] = [(u, ty, (lines(x.difference(cut)) if u == sub and ty == "kerb" else x), *r_) for u, ty, x, *r_ in marks]
    marks[:] = [m_ for m_ in marks if m_[2] is not None and not m_[2].is_empty]
    parts[:] = [p for p in parts if not p["geom"].is_empty]

    # ---- no crumbs: a strip under PIECE_MIN_M2 joins its neighbour in the same space (never a lane: a lane keeps its own)
    by_unit = {}
    for p in parts:
        by_unit.setdefault(p["unit_id"], []).append(p)
    for uid, ps in by_unit.items():
        for p in sorted(ps, key=lambda p: p["geom"].area):
            if p["geom"].area >= PIECE_MIN_M2 or p["type"] in ("lane", "junction area") or p.get("gone"):
                continue
            nb = [q for q in ps if q is not p and not q.get("gone") and q["geom"].distance(p["geom"]) < 0.05]
            same = [q for q in nb if (q["type"] in ROADWAY) == (p["type"] in ROADWAY)]
            nb = same or nb         # a crumb of roadway joins the roadway, a crumb of the pedestrian realm joins the realm
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
    if turns:       # each turn to the new intersection holding its middle
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
        con.executemany(f"""INSERT INTO space.part (unit_id, part_id, level, type, arm, direction, lane, width_m, width_source, width_method,
                            length_m, source, method, ref, road, road_class, road_lanes, oneway, rule, geometry)
                            VALUES (?, ?, 0, ?, ?, ?, ?, ?, 'urbanstyle', ?, ?, 'urbanstyle', 'derived', ?, ?, ?, ?, ?, ?, {to_ll})""",
                        [(p["unit_id"], p["part_id"], p["type"], p.get("arm"), p.get("direction"), p.get("lane"), p.get("width_m"),
                          p.get("width_method"), round(p["geom"].length / 2, 1), p.get("ref"), p.get("road"), p.get("road_class"),
                          p.get("road_lanes"), p.get("oneway"), p.get("rule"), shapely.to_wkb(p["geom"])) for p in parts])
    if marks:
        con.executemany(f"""INSERT INTO space.mark (unit_id, level, type, length_m, width_m, width_source, width_method, source, method, ref, geometry)
                            VALUES (?, 0, ?, ?, ?, 'urbanstyle', 'chosen', ?, ?, ?, {to_ll})""",
                        [(u, t, round(x.length, 1), LINE.get(t), s_, me, r, shapely.to_wkb(x)) for u, t, x, s_, me, r in marks])
    if widths:
        con.executemany("""INSERT INTO space.width (unit_id, level, edge, arm, total_m, carriageway_m, left_m, right_m, lanes_in, lanes_out, lane_m, source,
                           osm_lanes) VALUES (?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", widths)
    return dict(old_units=len(old), subsections=sum(1 for u in units if u[1] == "subsection"), intersections=len(inter),
                sections=len(section_ids), parts=len(parts), marks=len(marks))
