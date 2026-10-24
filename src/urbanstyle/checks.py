"""Conformance checks for a built urbanstyle database (docs/design/street-space-spec.md, section 8).

    urbanstyle check data/monaco.duckdb [more.duckdb ...]

Prints one line per invariant: id, what is counted, the count, PASS / FAIL (or INFO for a reported number). Exit code 1 if a hard check fails.
"""

import duckdb

KINDS = ("section", "intersection", "path", "rail", "plaza")


def unit_checks(c, q, epsg):
    """U1-U7: the network-first spaces (work.unit, docs/design/network-first.md). A junction node must lie in its own intersection
    and in no road's space or line, or a click on it in the dashboard opens the road instead of the intersection."""
    m = lambda g: f"ST_Transform({g}, 'EPSG:4326', '{epsg}', always_xy := true)"
    c.execute(f"""CREATE TEMP TABLE u AS SELECT unit_id, kind, level, ST_MakeValid(ST_Buffer({m('geometry')}, -0.01)) AS g FROM work.unit""")
    c.execute(f"""CREATE TEMP TABLE jn AS SELECT DISTINCT a.intersection_id, a.level, n.p FROM work.junction a
                  JOIN (SELECT src AS node, {m('ST_StartPoint(geometry)')} AS p FROM work.element WHERE type = 'road' AND src IS NOT NULL
                        UNION SELECT dst, {m('ST_EndPoint(geometry)')} FROM work.element WHERE type = 'road' AND dst IS NOT NULL) n ON n.node = a.node_id
                  -- (nodes inside the area only: a cut's junction whose node lies past its edge is cut there, no fault)
                  WHERE ST_Within(n.p, (SELECT ST_Union_Agg({m('geometry')}) FROM work.area))""")
    return [
        ("U1", "spaces overlapping by more than 0.05 m2 (rank 3 partitions the street; the lon/lat storage leaves hairlines under that)", q("""SELECT count(*) FROM u a JOIN u b ON a.level = b.level AND a.unit_id < b.unit_id
                                  AND ST_Intersects(a.g, b.g) WHERE ST_Area(ST_Intersection(a.g, b.g)) > 0.05"""), True),
        ("U2", "spaces invalid, empty or in more than one part", q("""SELECT count(*) FROM work.unit
                                  WHERE NOT ST_IsValid(geometry) OR ST_IsEmpty(geometry) OR ST_NumGeometries(geometry) > 1"""), True),
        # (a junction of a node outside the area is no fault: a cut's OSM extract reaches past its area, and nothing is built there)
        ("U3", "junctions inside the area with no intersection space", q("""SELECT count(DISTINCT j.intersection_id) FROM work.junction j
                                  JOIN (SELECT src AS node, ST_StartPoint(geometry) AS p FROM work.element WHERE type = 'road'
                                        UNION SELECT dst, ST_EndPoint(geometry) FROM work.element WHERE type = 'road') n ON n.node = j.node_id
                                  WHERE j.intersection_id NOT IN (SELECT unit_id FROM work.unit)
                                    AND ST_Within(n.p, (SELECT ST_Union_Agg(geometry) FROM work.area))"""), True),
        ("U4", "junction nodes outside their own intersection space (> 0.5 m)", q("""SELECT count(*) FROM jn
                                  JOIN u ON u.unit_id = jn.intersection_id WHERE ST_Distance(u.g, jn.p) > 0.5"""), True),
        ("U5", "junction nodes inside a road's space", q("""SELECT count(*) FROM jn JOIN u ON u.kind = 'subsection' AND u.level = jn.level
                                  AND ST_Intersects(u.g, jn.p)"""), True),
        ("U6", "subsection lines reaching more than 1 m into an intersection", q(f"""SELECT count(*) FROM work.subsection s
                                  JOIN u ON u.kind IN ('intersection', 'roundabout') AND u.level = s.level AND ST_Intersects(u.g, {m('s.geometry')})
                                  WHERE ST_Length(ST_Intersection(u.g, {m('s.geometry')})) > 1"""), True),
        ("U7", "subsections with no space", q("SELECT count(*) FROM work.subsection WHERE subsection_id NOT IN (SELECT unit_id FROM work.unit)"), True),
    ] + part_checks(c, q, m)


_R1 = {}


def _r1(c, q, m):
    if "v" not in _R1:
        epsg = m("x").split("'")[3]
        _R1["v"] = roadway_joints(c, epsg, bool(q("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'work' AND table_name = 'change'")))
    return _R1["v"]


def part_checks(c, q, m):
    """U8-U10: the parts of a space (work.part, docs/design/space-parts.md) cover it exactly."""
    if not q("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'work' AND table_name = 'part'"):
        return []
    c.execute(f"CREATE TEMP TABLE pt AS SELECT unit_id, part_id, ST_MakeValid(ST_Buffer({m('geometry')}, -0.01)) AS g, ST_Area({m('geometry')}) AS a FROM work.part")
    return [
        ("U8", "spaces whose parts do not add up to them (3% or 1.5 m2)", q(f"""SELECT count(*) FROM (SELECT u.unit_id, ST_Area({m('u.geometry')}) AS a,
                                  coalesce(sum(p.a), 0) AS pa FROM work.unit u LEFT JOIN pt p USING (unit_id) GROUP BY u.unit_id, u.geometry)
                                  WHERE abs(a - pa) > greatest(0.03 * a, 1.5)"""), True),
        ("U9", "parts of one space overlapping by more than 0.05 m2 (rank 5 partitions the space)", q("""SELECT count(*) FROM pt a JOIN pt b ON a.unit_id = b.unit_id AND a.part_id < b.part_id
                                  AND ST_Intersects(a.g, b.g) WHERE ST_Area(ST_Intersection(a.g, b.g)) > 0.05"""), True),
        ("U10", "cuts where the roadway differs by more than 0.5 m on the two sides", roadway_mismatch(c, q, m), False),
        ("R1", "joints between two subsections where the roadway's edges step by more than 0.1 m (the frame changes only at a 'real' change, J4)",
         _r1(c, q, m)[0], True, _r1(c, q, m)[1]),
        ("R4", "edges of lanes, cycle lanes and parking at a joint with no edge on the other side (0.3 m in, within 0.25 m)", lane_joints(c, m), False),
        ("R3", "subsections where OSM's lane count does not fit between our kerbs (a lane under 2.75 m): our kerb is probably wrong",
         q("SELECT count(DISTINCT unit_id) FROM work.part WHERE level = 0 AND type = 'lane' AND source = 'osm' AND width_m < 2.75"), False),
        ("R2", "guide lines (SUMO's moves) leaving the roadway by more than 0.5 m", q(f"""WITH rw AS (SELECT ST_Union_Agg(ST_MakeValid(
                                  ST_Buffer({m('geometry')}, 0.1))) AS g FROM work.part WHERE level = 0 AND type IN ('lane', 'shoulder', 'parking',
                                  'bus zone', 'cycle lane', 'junction area', 'paved', 'crosswalk', 'cycle crossing'))
                                  SELECT count(*) FROM work.mark, rw WHERE type = 'guide line' AND level = 0
                                  AND ST_Length(ST_Difference({m('work.mark.geometry')}, rw.g)) > 0.5"""), False),
    ] + approach_checks(q) + ground_checks(c, q, m)


def approach_checks(q):
    """U11-U13: the lanes coming into each junction (work.approach, written by parts.py) and what they may do. Reported, not failed: a
    missing move may be the law (a turn restriction, a T junction); the number says where to look."""
    if not q("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'work' AND table_name = 'approach'"):
        return []
    return [
        ("U11", "lanes entering a junction with no move at all", q("SELECT count(*) FROM work.approach WHERE moves = 0"), False),
        # at a junction of 4 or more approaches each one usually goes straight on (at a T the stem cannot): the others are worth a look
        ("U12", "approaches with no straight move for all traffic, at junctions of 4+ approaches", q("""WITH ap AS (
                                  SELECT a.unit_id, a.from_edge, bool_or(a.ways LIKE '%straight%') AS straight FROM work.approach a
                                  JOIN work.unit u USING (unit_id) WHERE u.kind = 'intersection' AND a.moves > 0 GROUP BY ALL)
                                  SELECT count(*) FROM ap WHERE NOT straight AND unit_id IN (SELECT unit_id FROM ap GROUP BY 1 HAVING count(*) >= 4)"""), False),
        ("U13", "lanes with a move for all traffic but no turn arrow (a lane piece under 4 m, another arrow in the way)", q("""SELECT count(*)
                                  FROM work.approach WHERE NOT arrow AND no_arrow_because IN ('lane piece under 4 m', 'another arrow in the way')"""), False),
    ]


def ground_checks(c, q, m):
    """G1-G2: layer 0, the ground (work.ground, docs/design/space-layers.md): every piece of the area at level 0 is one ground item."""
    if not q("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'work' AND table_name = 'ground'"):
        return []
    unknown = c.execute(f"SELECT count(*), coalesce(sum(ST_Area({m('geometry')})), 0) FROM work.ground WHERE type = 'unknown'").fetchone()
    c.execute(f"CREATE TEMP TABLE gr AS SELECT ground_id, level, ST_MakeValid({m('geometry')}) AS g FROM work.ground")
    return [
        ("G1", f"pieces of ground of no known kind ({unknown[1]:,.0f} m2)", unknown[0], False),
        ("G3", "the ground's kinds leave a gap: the area less their union, over 1 m2 in all (rank 1 partitions rank 0; hairlines of the lon/lat storage under that)", q(f"""SELECT CASE WHEN
                                  ST_Area(ST_Difference((SELECT ST_Union_Agg({m('geometry')}) FROM work.area), (SELECT ST_Union_Agg({m('geometry')}) FROM work.ground))) > 1
                                  THEN 1 ELSE 0 END"""), True),
        ("G2", "ground items overlapping by more than 0.05 m2 (the kinds partition the area; the lon/lat storage leaves hairlines under that)", q("""SELECT count(*) FROM gr a JOIN gr b ON a.level = b.level
                                  AND a.ground_id < b.ground_id AND ST_Intersects(a.g, b.g) WHERE ST_Area(ST_Intersection(a.g, b.g)) > 0.05"""), True),    ] + surface_checks(c, q, m) + block_checks(c, q, m)


def block_checks(c, q, m):
    """B1, B6: the blocks (work.block, docs/design/blocks.md). B1: a building cut by a block's edge (inside the area); B6: how well our
    blocks match a city's own, where it has them (a cross-check, never an input)."""
    if not q("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'work' AND table_name = 'block'"):
        return []
    c.execute(f"CREATE TEMP TABLE bk AS SELECT block_id, ST_MakeValid({m('geometry')}) AS g FROM work.block")
    c.execute(f"CREATE TEMP TABLE ar AS SELECT ST_MakeValid({m('geometry')}) AS g FROM work.area")
    cut = c.execute(f"""WITH b AS (SELECT ST_MakeValid(ST_Intersection(ST_MakeValid({m('e.geometry')}), ar.g)) AS g FROM work.element e, ar
                          WHERE e.type = 'building' AND e.level_min <= 0 AND e.level_max >= 0),
                        x AS (SELECT b.g, ST_Area(ST_Intersection(b.g, k.g)) AS inside FROM b JOIN bk k ON ST_Intersects(b.g, k.g))
                        SELECT count(*), coalesce(sum(ST_Area(g) - inside), 0) FROM x WHERE inside > 1 AND ST_Area(g) - inside > 1""").fetchone()
    out = [("B1", f"buildings reaching over a block's edge ({cut[1]:,.0f} m2 outside their block; drawn whole)", cut[0], False)]
    # B7: rank 3 is cut from rank 1's street, so no space reaches into a block (Kaveh, 2026-10-16: a partition has no overlap); B8: the
    # lanes that narrowed to fit between the street's edges (the sidewalk lines), their count as OSM maps it
    if q("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'work' AND table_name = 'unit'"):
        ov = c.execute(f"""WITH u AS (SELECT unit_id, ST_MakeValid({m('geometry')}) AS g FROM work.unit WHERE level = 0)
                            SELECT count(*), coalesce(sum(a), 0) FROM (SELECT ST_Area(ST_Buffer(ST_Intersection(u.g, k.g), -0.02)) AS a FROM u JOIN bk k ON ST_Intersects(u.g, k.g)) WHERE a > 0.05""").fetchone()
        # (an overlap is measured 2 cm inside its outline: the shared edge of a space and a block, stored in lon/lat and read back, leaves
        # a hairline 3 mm wide along 150 m, 0.5 m2, which is no space in a block)
        out.append(("B7", f"street spaces reaching into a block by over 0.05 m2 past a 2 cm hairline ({ov[1]:,.1f} m2 in all): every space is cut from rank 1's street", ov[0], True))
        nar = c.execute("""SELECT count(DISTINCT unit_id), count(*) FROM work.part WHERE level = 0 AND type = 'lane' AND width_method = 'narrowed'""").fetchone()
        out.append(("B8", f"spaces whose lanes narrowed to fit between the street's edges ({nar[1]} lane parts; the count as OSM maps it, down to {2.75} m)", nar[0], False))
    if q("SELECT count(*) FROM work.city_block"):
        mt = c.execute(f"""WITH cb AS (SELECT city_block_id, ST_MakeValid(ST_Intersection(ST_MakeValid({m('geometry')}), ar.g)) AS g
                                         FROM work.city_block, ar),
                              cbp AS (SELECT city_block_id, g FROM cb WHERE ST_Area(g) > 50),
                              io AS (SELECT p.city_block_id, max(ST_Area(ST_Intersection(p.g, k.g)) / ST_Area(ST_Union(p.g, k.g))) AS iou
                                     FROM cbp p JOIN bk k ON ST_Intersects(p.g, k.g) GROUP BY 1)
                              SELECT count(*) FILTER (WHERE io.iou >= 0.8), count(*), median(coalesce(io.iou, 0))
                              FROM cbp LEFT JOIN io USING (city_block_id)""").fetchone()
        out.append(("B6", f"of the city's {mt[1]} blocks, matched by one of ours (overlap >= 0.8; median overlap {mt[2] or 0:.2f})", mt[0], False))
    return out


def surface_checks(c, q, m):
    """L1-L2: layer 1, the surfaces (work.surface): they cover their ground item exactly and do not overlap."""
    if not q("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'work' AND table_name = 'surface'"):
        return []
    c.execute(f"CREATE TEMP TABLE sf AS SELECT surface_id, ground_id, ST_MakeValid(ST_Buffer({m('geometry')}, -0.01)) AS g, ST_Area({m('geometry')}) AS a FROM work.surface")
    return [
        ("L1", "ground items whose surfaces do not cover them (3% or 1.5 m2)", q(f"""SELECT count(*) FROM (SELECT gd.ground_id,
                                  ST_Area({m('gd.geometry')}) AS a, coalesce(sum(s.a), 0) AS sa FROM work.ground gd LEFT JOIN sf s USING (ground_id)
                                  GROUP BY gd.ground_id, gd.geometry) WHERE abs(a - sa) > greatest(0.03 * a, 1.5)"""), True),
        ("L2", "surfaces of one ground item overlapping by more than 0.5 m2", q("""SELECT count(*) FROM sf a JOIN sf b ON a.ground_id = b.ground_id
                                  AND a.surface_id < b.surface_id AND ST_Intersects(a.g, b.g) WHERE ST_Area(ST_Intersection(a.g, b.g)) > 0.5"""), True),
    ]


def rule_checks(c, epsg):
    """A1-A3, J1: the agreed street rules (docs/design/street-rules.md), at level 0. Each row has the places that fail (lon, lat).
    A1: a carriageway's lanes not on their OSM line; A2: a parking or cycle lane with no real source; A3: a road line with no roadway
    under it; J1: an intersection with no junction node (3 or more road ends; a road through the node counts 2)."""
    import re
    import shapely
    import pyproj
    from .network import LANE_M, STREET, TAPER_M, CONNECTOR_M, XWALK_MAX_M, straight
    from .blocks import street_sql
    A1_M = 0.5      # a carriageway's lanes are centred on their OSM line within this (sections.md: the 2 m tolerance of the shift era is gone)
    if not c.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'work' AND table_name = 'part'").fetchone()[0]:
        return []
    m = lambda g: f"ST_AsWKB(ST_Transform({g}, 'EPSG:4326', '{epsg}', always_xy := true))"
    to_ll = pyproj.Transformer.from_crs(epsg, "EPSG:4326", always_xy=True).transform
    at = lambda g: to_ll(*g.representative_point().coords[0])
    geo = lambda w: shapely.make_valid(shapely.from_wkb(bytes(w)))
    parts = [(u, t, ref, src, geo(w)) for u, t, ref, src, w in c.execute(f"""SELECT unit_id, type, coalesce(ref, ''), coalesce(source, ''),
                 {m('geometry')} FROM work.part WHERE level = 0""").fetchall()]
    roads = [(o, cl, geo(w)) for o, cl, w in c.execute(f"""SELECT osm_id, class, {m('geometry')} FROM work.element e
                 WHERE type IN ('road', 'walkway') AND level_min = 0 AND {street_sql('e')}""").fetchall()]
    lines = {}
    for o, cl, g in roads:
        lines.setdefault(o, []).append(g)
    lines = {o: shapely.line_merge(shapely.union_all(v)) for o, v in lines.items()}
    raw_lines = dict(lines)
    # (each way as network.py draws it: cut at its junction nodes, a piece within STRAIGHT_M of straight drawn straight)
    tree = shapely.STRtree([g for _, _, g in roads])

    def deg(pt):
        d = 0
        for k in tree.query(pt.buffer(0.5)):
            ln = roads[k][2]
            if ln.distance(pt) <= 0.5:
                s_ = ln.project(pt)
                d += 1 if (s_ < 0.5 or s_ > ln.length - 0.5) else 2
        return d
    nodes = [shapely.Point(q_) for _, _, g in roads for q_ in (g.coords[0], g.coords[-1])]
    jn = shapely.MultiPoint([pt for pt in nodes if deg(pt) >= 3]) if nodes else shapely.MultiPoint()
    jpts = list(shapely.get_parts(jn))

    def drawn(ln):
        out = []
        for q_ in shapely.get_parts(ln):
            if q_.geom_type != "LineString":
                continue
            cuts = sorted({0.0, q_.length} | {q_.project(pt) for pt in jpts if q_.distance(pt) < 0.6})
            out += [straight(shapely.ops.substring(q_, a, b)) for a, b in zip(cuts, cuts[1:]) if b - a >= 0.5]
        return shapely.MultiLineString(out) if out else ln
    import shapely.ops
    lines = {o: drawn(v) for o, v in lines.items()}
    # A1: per space and OSM way, the middle of its lanes on cross lines every 5 m along the way's line; failed if the median is > 0.5 m
    groups, widened = {}, {}
    wide_rows = {(u, pid): w for u, pid, w in c.execute("""SELECT unit_id, part_id, width_m FROM work.part WHERE level = 0 AND type = 'lane'
                                                          AND holds = 'parking'""").fetchall()}
    pids = [pid for (pid,) in c.execute("SELECT part_id FROM work.part WHERE level = 0").fetchall()]
    for (u, t, ref, src, g), pid in zip(parts, pids):
        if t == "lane":
            for o in re.findall(r"w(\d+)", ref.split(" ")[0]):     # (a lane along several ways: checked against each)
                groups.setdefault((u, int(o)), []).append(g)
                if (u, pid) in wide_rows:       # (an outer lane widened to the kerb evidence, parking in it: its extra moves the middle)
                    widened.setdefault((u, int(o)), []).append((g, wide_rows[(u, pid)] - LANE_M))
    area = shapely.union_all([geo(w) for (w,) in c.execute(f"SELECT {m('geometry')} FROM work.area").fetchall()]).buffer(-2.0)
    # (a section that keeps the through arm's kerb at a merge or fork has its lanes moved off the OSM line by half the merging lanes'
    # width: the subsection's left_extra, expected there; sections.md section 3)
    mshift = {u_: (x_ or 0.0) for u_, x_ in c.execute("SELECT subsection_id, left_extra FROM work.subsection WHERE level = 0").fetchall()}
    off = []
    for (u, o), gs in groups.items():
        ln, U = lines.get(o), shapely.union_all(gs)
        if ln is None or U.is_empty or not area.contains(U):     # (a stub cut by the area's edge is not measured)
            continue
        ds = []
        for piece in shapely.get_parts(ln):
            if not piece.intersects(U.buffer(0.5)):
                continue
            for k in range(int(piece.length // 5) + 1):
                s_ = min(k * 5.0, piece.length)
                if s_ < TAPER_M or s_ > piece.length - TAPER_M:      # (the lanes slide to the next subsection's positions over TAPER_M)
                    continue
                p, a, b = piece.interpolate(s_), piece.interpolate(max(s_ - 1, 0)), piece.interpolate(min(s_ + 1, piece.length))
                h = ((b.x - a.x) ** 2 + (b.y - a.y) ** 2) ** .5 or 1
                nx, ny = -(b.y - a.y) / h, (b.x - a.x) / h
                hit = shapely.LineString([(p.x - nx * 20, p.y - ny * 20), (p.x + nx * 20, p.y + ny * 20)]).intersection(U)
                # (the lanes' run that holds the line point, or the nearest one: on a bend or a loop the cross line meets the same road
                # again 20 m on, and that run is not this place's; Avenue Hector Otto's roundabout, Monaco 2026-10-16)
                runs_ = [[(x - p.x) * nx + (y - p.y) * ny for x, y in q_.coords] for q_ in shapely.get_parts(hit) if q_.geom_type == "LineString" and len(q_.coords)]
                ts = min(runs_, key=lambda tt: 0.0 if min(tt) <= 0 <= max(tt) else min(abs(min(tt)), abs(max(tt))), default=[])
                if ts:
                    # (the widened outer lanes' extras, left minus right, move the middle by half of it: expected, not off)
                    exp_ = mshift.get(u, 0.0)
                    for g_, ex_ in widened.get((u, o), []):
                        q_ = g_.centroid
                        exp_ += ex_ / 2 if ((q_.x - p.x) * nx + (q_.y - p.y) * ny) > 0 else -ex_ / 2
                    ds.append(abs((max(ts) + min(ts)) / 2 - exp_))
        if ds and sorted(ds)[len(ds) // 2] > A1_M:
            off.append(at(U))
    # A2: a parking or cycle lane that no real source gives
    nosrc = [at(g) for u, t, ref, src, g in parts if t in ("parking", "cycle lane") and src == "urbanstyle"]
    # A3: a stretch of a road line over 2 m with no roadway under it, inside the area (not at its edge)
    road_t = ("lane", "junction area", "paved", "bridge deck", "bus lane", "bus zone", "parking", "shoulder", "cycle lane", "crosswalk",
              "cycle crossing")
    cover0 = shapely.union_all([g for u, t, ref, src, g in parts if t in road_t])
    cover = cover0.buffer(0.3)
    bare = []
    for o, cl, g in roads:
        if cl in (None, "pedestrian"):
            continue
        g = lines[o].intersection(g.buffer(3.0)) if o in lines else g
        for q_ in shapely.get_parts(g.intersection(area).difference(cover)):
            if q_.geom_type == "LineString" and q_.length > 2.0:
                bare.append(at(q_))
    # J1: an intersection with no junction node in it
    # (an intersection whose junction node lies past the area's edge is cut there: a cut's edge, no fault)
    past = {i for (i,) in c.execute(f"""SELECT DISTINCT j.intersection_id FROM work.junction j
                 JOIN (SELECT src AS node, ST_StartPoint(geometry) AS p FROM work.element WHERE type = 'road'
                       UNION SELECT dst, ST_EndPoint(geometry) FROM work.element WHERE type = 'road') n ON n.node = j.node_id
                 WHERE NOT ST_Within(n.p, (SELECT ST_Union_Agg(geometry) FROM work.area))""").fetchall()}
    nojn = [at(g) for u, g in ((u, geo(w)) for u, w in c.execute(f"""SELECT unit_id, {m('geometry')} FROM work.unit
                 WHERE level = 0 AND kind = 'intersection'""").fetchall()) if u not in past and (jn.is_empty or g.buffer(0.5).disjoint(jn))]
    # J2: a junction area outside its arms: each subsection's line as drawn, as wide as its roadway (+2.5 m: parking on one side puts the
    # line off the middle), run on 25 m past its ends, is an arm's band; a piece of a junction area over 5 m2 outside every band (a 4 m
    # corner fillet is 3.4 m2) means the junction reaches where no arm is (a disc round the node did, 2026-10-15)
    import math

    def extend(ln, d=25.0):
        pts = list(ln.coords)
        if len(pts) < 2:
            return ln
        (x0, y0), (x1, y1) = pts[0], pts[1]
        h = math.hypot(x1 - x0, y1 - y0) or 1
        a_ = (x0 - (x1 - x0) / h * d, y0 - (y1 - y0) / h * d)
        (x0, y0), (x1, y1) = pts[-2], pts[-1]
        h = math.hypot(x1 - x0, y1 - y0) or 1
        b_ = (x1 + (x1 - x0) / h * d, y1 + (y1 - y0) / h * d)
        return shapely.LineString([a_] + pts + [b_])
    subs = c.execute(f"SELECT width_m, {m('geometry')} FROM work.subsection WHERE level = 0 AND width_m IS NOT NULL").fetchall()
    # (and every road line itself, as wide as its lanes (element.width_m): an arm a junction takes whole has no subsection)
    subs += c.execute(f"""SELECT width_m, {m('geometry')} FROM work.element e WHERE type = 'road' AND level_min = 0 AND width_m IS NOT NULL
                          AND {street_sql('e')}""").fetchall()
    bands = shapely.union_all([extend(q_).buffer(wd / 2 + 2.5, cap_style="flat") for wd, w in subs for q_ in shapely.get_parts(geo(w))
                               if q_.geom_type == "LineString"] or [shapely.Polygon()])
    jover = []      # (a piece over 40 m2, a 30 degree corner's fillet of 4 m, and over a tenth of the junction: a traffic circle's ring is less)
    for u, t, ref, src, g in parts:
        if t == "junction area" and any(q_.geom_type == "Polygon" and q_.area > max(40.0, 0.1 * g.area) for q_ in shapely.get_parts(g.difference(bands))):
            jover.append(at(g.difference(bands)))
    # X1: a crossing way over the roadway with no crosswalk part on it (under 80 % of its stretch over the roadway covered)
    xw_u = shapely.union_all([g for u, t, ref, src, g in parts if t in ("crosswalk", "cycle crossing")] or [shapely.Polygon()]).buffer(0.3)
    xways = {}
    for o, w in c.execute(f"""SELECT osm_id, {m('geometry')} FROM work.element WHERE type IN ('walkway', 'cycleway') AND level_min = 0
                              AND subtype = 'crossing'""").fetchall():
        xways.setdefault(o, []).append(geo(w))
    noxw = []
    for o, gs in xways.items():     # (per way: its pieces together; a bare end under 1 m, a kerb ramp, does not count)
        x = shapely.union_all(gs).intersection(cover0.intersection(area))
        # (a way over the roadway (the 0.3 m margin in, as network.py reads it) for longer than a crosswalk can be runs along the road, not
        # across it: no crosswalk is due, as in network.py's crosses_road and spaces.XWALK_MAX_M; a footway tagged crossing beside
        # Boulevard du Larvotto for 80 m, Monaco 2026-10-16)
        if shapely.union_all(gs).intersection(cover.intersection(area)).length > XWALK_MAX_M:
            continue
        if x.length > 1.0 and x.length - x.intersection(xw_u).length > max(1.0, 0.2 * x.length):
            noxw.append(at(x.difference(xw_u) if not x.difference(xw_u).is_empty else x))
    # M1: a lane line, or a centre line with a real source, where the lane count is chosen (no source maps the lanes, so none maps a
    # line between them; the centre line between the directions is drawn as urbanstyle's own there)
    # (per road: a space can hold lanes of two roads, one with a mapped lane count and one without; the line between the mapped road's
    # lanes names its way in its ref, and it is no fault of the other road's chosen count: Monaco's four M1 places, 2026-10-24)
    import re as _re
    ways_of = lambda ref: set(_re.findall(r"w(\d+)", (ref or "").split(":")[0].split(" lanes")[0].split(" has ")[0]))
    chosen = {}
    for u, t, ref, src, g in parts:
        if t == "lane" and src == "urbanstyle":
            chosen.setdefault(u, set()).update(ways_of(ref))
    nolines = [at(geo(w)) for u, t, src, ref, w in c.execute(f"""SELECT unit_id, type, source, ref, {m('geometry')} FROM work.mark WHERE level = 0
                 AND type IN ('centre line', 'lane line')""").fetchall()
               if u in chosen and (t == "lane line" or src != "urbanstyle") and (not ways_of(ref) or ways_of(ref) & chosen[u])]
    # K1: the kerb against a city's kerb evidence: catch basins stand in the gutter at the kerb; a subsection whose kerb lies more than
    # 1.5 m from them (the median of 2 or more) has a kerb the data does not confirm: parking at the kerb that no source maps, or a wrong
    # lane width. A report, not a fault: the kerb is the lanes' edge by the agreed rule and never moves for evidence
    from .blocks import _city
    basins = [shapely.Point(pyproj.Transformer.from_crs("EPSG:4326", epsg, always_xy=True).transform(*f["geometry"]["coordinates"]))
              for f in (_city(c).get("sewer-catch-basins") or {}).get("features", []) if (f.get("geometry") or {}).get("type") == "Point"]
    kerbs = [(u, geo(w)) for u, w in c.execute(f"SELECT unit_id, {m('geometry')} FROM work.mark WHERE level = 0 AND type = 'kerb'").fetchall()]
    ktree = shapely.STRtree([g for _, g in kerbs]) if kerbs else None
    by_u = {}
    for b in basins:
        if ktree is None or cover0.distance(b) > 6.0:
            continue
        k = ktree.nearest(b)
        by_u.setdefault(kerbs[k][0], []).append((kerbs[k][1].distance(b), b))
    offkerb = [at(ds[len(ds) // 2][1]) for u, ds in by_u.items() if len(ds) >= 2 and sorted(ds)[len(ds) // 2][0] > 1.5]
    # K2: loose kerb ends: an end of a kerb line that touches no other kerb and no crosswalk within 0.3 m (a kerb ends only at a crossing)
    kerb_t = shapely.STRtree([g for _, g in kerbs]) if kerbs else None
    xw_t = shapely.union_all([g for u, t, ref, src, g in parts if t in ("crosswalk", "cycle crossing")] or [shapely.Polygon()])
    service = shapely.union_all([geo(w) for (w,) in c.execute(f"""SELECT {m('geometry')} FROM work.element e WHERE type IN ('road', 'walkway')
                                 AND level_min = 0 AND class = 'service' AND NOT {street_sql('e')}""").fetchall()] or [shapely.LineString()])
    loose = []
    for i_, (u, g) in enumerate(kerbs):
        for pt_ in (shapely.Point(g.coords[0]), shapely.Point(g.coords[-1])):
            if any(k != i_ and kerbs[k][1].distance(pt_) < 0.3 for k in kerb_t.query(pt_.buffer(0.3))) or xw_t.distance(pt_) < 0.3 \
                    or service.distance(pt_) < 3.0 or area.distance(pt_) > 0:      # (a dropped kerb at an alley's mouth; the area's edge)
                continue
            loose.append(at(pt_))
    # J3: every connector (a road piece between two of the build's junction nodes under CONNECTOR_M, or a `_link`; sections.md rule 3)
    # lies in an intersection, or on a bridge deck (the bridge model draws it)
    mt = lambda g: f"ST_Transform({g}, 'EPSG:4326', '{epsg}', always_xy := true)"
    jn_pts = [shapely.Point(x, y) for x, y in c.execute(f"""SELECT DISTINCT ST_X(n.p), ST_Y(n.p) FROM work.junction a JOIN (
                 SELECT src AS node, {mt('ST_StartPoint(geometry)')} AS p FROM work.element WHERE type = 'road' AND src IS NOT NULL
                 UNION SELECT dst, {mt('ST_EndPoint(geometry)')} FROM work.element WHERE type = 'road' AND dst IS NOT NULL) n ON n.node = a.node_id
                 WHERE a.level = 0""").fetchall()]
    jn_tree = shapely.STRtree(jn_pts) if jn_pts else None
    cover_c = shapely.union_all([geo(w) for (w,) in c.execute(f"""SELECT {m('geometry')} FROM work.unit WHERE level = 0
                                 AND kind = 'intersection'""").fetchall()] + [g for u, t, ref, src, g in parts if t == "bridge deck"]
                                or [shapely.Polygon()]).buffer(0.5)
    # (a short road between two junction nodes is a connector only where its stop lines meet, else a section: it lies in an
    # intersection or in a section; a `_link` there is always a connector: it lies in an intersection; docs/design/stretches.md)
    cover_s = shapely.union_all([geo(w) for (w,) in c.execute(f"""SELECT {m('geometry')} FROM work.unit WHERE level = 0
                                 AND kind <> 'intersection'""").fetchall()] or [shapely.Polygon()]).buffer(0.5)
    cover_cs = cover_c.union(cover_s)
    cls_of = {o: cl for o, cl, _ in roads}
    conn_out = []
    for o, ln in raw_lines.items():
        for q_ in shapely.get_parts(ln):
            if q_.geom_type != "LineString" or jn_tree is None:
                continue
            at_n = lambda pt: any(jn_pts[k].distance(pt) < 0.6 for k in jn_tree.query(pt.buffer(0.6)))
            cuts = sorted({0.0, q_.length} | {q_.project(jn_pts[k]) for k in jn_tree.query(q_.buffer(0.6)) if q_.distance(jn_pts[k]) < 0.6})
            for a_, b_ in zip(cuts, cuts[1:]):
                pc = shapely.ops.substring(q_, a_, b_)
                if pc.length < 0.5 or not (at_n(shapely.Point(pc.coords[0])) and at_n(shapely.Point(pc.coords[-1]))):
                    continue
                link_ = str(cls_of.get(o) or "").endswith("_link")
                if (pc.length < CONNECTOR_M or link_) and area.contains(pc):
                    rest_ = pc.difference(cover_c if link_ else cover_cs)
                    if rest_.length > 1.0:
                        conn_out.append(at(rest_))
    # J4: every tag change along a section, with its class (work.change, network.py step 6b): a report; the unknown ones first
    has_ch = c.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'work' AND table_name = 'change'").fetchone()[0]
    chg = c.execute(f"""SELECT class, {m('geometry')} FROM work.change WHERE level = 0 ORDER BY (class = 'unknown') DESC, class""").fetchall() if has_ch else []
    by_cls = {}
    for cl_, _ in chg:
        by_cls[cl_] = by_cls.get(cl_, 0) + 1
    return [
        ("A1", f"roads whose lanes, taken together, are off the road's OSM line (their middle more than {A1_M} m from it, median along the road)", len(off), True, off),
        ("J3", "roads between two junction nodes outside the spaces: a `_link` not inside an intersection, a road under "
               f"{CONNECTOR_M:.0f} m inside neither an intersection nor a section", len(conn_out), True, conn_out),
        ("J4", "tag changes along a section, each with its class" + (" (" + ", ".join(f"{k} {v}" for k, v in sorted(by_cls.items())) + ")" if by_cls else ""),
         len(chg), False, [at(geo(w)) for _, w in chg]),
        ("K2", "loose kerb ends (not at another kerb, a crosswalk, an alley's mouth or the area's edge)", len(loose), False, loose),
        ("A2", "parking or cycle lanes with no real source (source urbanstyle)", len(nosrc), True, nosrc),
        ("A3", "stretches of a road line over 2 m with no roadway under it", len(bare), True, bare),
        ("J1", "intersections with no junction node (3 or more road ends)", len(nojn), True, nojn),
        ("J2", "junction areas reaching over 40 m2 (and a tenth of their area) outside their arms' bands", len(jover), True, jover),
        ("X1", "crossing ways over the roadway with no crosswalk part on them", len(noxw), True, noxw),
        ("M1", "lane lines, or centre lines with a real source, where the lane count is chosen", len(nolines), True, nolines),
        ("K1", f"subsections whose kerb is over 1.5 m from the city's catch basins (median)" + ("" if basins else " (no kerb evidence here)"),
         len(offkerb), False, offkerb),
    ]


def roadway_mismatch(c, q, m):
    """Along each cut line, the roadway (lanes, shoulders, bus / cycle lanes, crosswalks, junction area) on the intersection side and on the
    road side should be the same width: the arm and the road meet there."""
    road = ("('lane', 'shoulder', 'parking', 'no parking', 'bus zone', 'bus lane', 'cycle lane', 'cycle crossing', 'island', 'crosswalk', "
            "'junction area', 'paved')")     # the kerb strip is roadway whatever it is used for
    return q(f"""WITH cut AS (SELECT intersection_id, edge_id, {m('geometry')} AS g FROM work.cut),
      rw AS (SELECT unit_id, ST_MakeValid(ST_Union_Agg(ST_MakeValid(ST_Buffer({m('geometry')}, 0.01)))) AS g FROM work.part WHERE type IN {road} GROUP BY unit_id),
      side AS (SELECT cut.intersection_id, cut.edge_id, ST_Length(ST_Intersection(cut.g, ST_Buffer(i.g, 0.3))) AS iw,
                 (SELECT max(ST_Length(ST_Intersection(cut.g, ST_Buffer(s.g, 0.3)))) FROM rw s JOIN work.unit su ON su.unit_id = s.unit_id
                  WHERE su.kind = 'subsection' AND ST_DWithin(s.g, cut.g, 0.5)) AS sw
               FROM cut JOIN rw i ON i.unit_id = cut.intersection_id)
      SELECT count(*) FROM side WHERE sw IS NOT NULL AND abs(iw - sw) > 0.5""")


def lane_joints(c, m):
    """R4: where two subsections meet (of one section, or of two with no intersection between them), each edge between two roadway items
    (lanes, cycle lanes, parking) on one side has one on the other (division.join_lanes). Read along the joint every 0.1 m, 0.3 m into
    each side; a taper (zero width at the joint) has no edge there."""
    import shapely
    from shapely import wkb
    items = ('lane', 'cycle lane', 'parking', 'bus zone')
    units = {u: wkb.loads(bytes(w)) for u, w in c.execute(f"SELECT unit_id, ST_AsWKB(ST_MakeValid({m('geometry')})) FROM work.unit "
                                                           "WHERE level = 0 AND kind = 'subsection'").fetchall()}
    parts = {}
    for u, pid, w in c.execute(f"SELECT unit_id, part_id, ST_AsWKB(ST_MakeValid({m('geometry')})) FROM work.part WHERE level = 0 AND type IN {items}").fetchall():
        parts.setdefault(u, []).append((pid, wkb.loads(bytes(w))))
    ids = list(units)
    tree = shapely.STRtree([units[u] for u in ids])
    bad = 0
    for u in ids:
        for j in tree.query(units[u].buffer(0.1)):
            v = ids[j]
            if v <= u or not (parts.get(u) or parts.get(v)):
                continue
            for seg in shapely.get_parts(shapely.line_merge(units[u].boundary.intersection(units[v].buffer(0.05)))):
                if seg.geom_type != "LineString" or seg.length < 2:
                    continue
                edges = {}
                for w in (u, v):
                    labs = []
                    for k in range(int(seg.length / 0.1)):
                        d = 0.05 + k * 0.1
                        p, a, b = seg.interpolate(d), seg.interpolate(max(d - 0.05, 0)), seg.interpolate(min(d + 0.05, seg.length))
                        nx, ny = a.y - b.y, b.x - a.x
                        h = (nx * nx + ny * ny) ** .5 or 1
                        q_ = shapely.Point(p.x + nx / h * 0.3, p.y + ny / h * 0.3)
                        if not units[w].contains(q_):
                            q_ = shapely.Point(p.x - nx / h * 0.3, p.y - ny / h * 0.3)
                        labs.append(next((pid for pid, g in parts.get(w, []) if g.contains(q_)), None))
                    edges[w] = [k for k in range(1, len(labs)) if labs[k] != labs[k - 1]]
                bad += sum(1 for k in edges[u] if not any(abs(k - x) <= 2 for x in edges[v]))
                bad += sum(1 for k in edges[v] if not any(abs(k - x) <= 2 for x in edges[u]))
    return bad


def roadway_joints(c, epsg, has_change=False):
    """Where two subsections of one section meet, the roadway (no median) reaches the joint at the same points from both sides: the frame
    is one width for the section (sections.md rule 6). A joint at a 'real' change (work.change, J4) is allowed to step. The joint is
    the two spaces' shared boundary round the end of one line nearest the other, its pieces that run across the road (over 45° to
    the line): two subsections of a section that folds back run side by side too, round an island, and that boundary is no joint
    (Avenue des Spélugues' hairpin, Monaco 2026-10-16). Level 0 only, as R2-R4: the change classes exist at level 0 alone, and a joint
    in the Tunnel Dorsale at level -2 stepped 8 m with no class to allow it. A bridge's deck is roadway: the model draws the lanes on
    it, the ground's part is 'bridge deck'. Returns (count, [(lon, lat)])."""
    import math
    import pyproj
    import shapely
    m = lambda g: f"ST_AsWKB(ST_Transform({g}, 'EPSG:4326', '{epsg}', always_xy := true))"
    geo = lambda w: shapely.make_valid(shapely.from_wkb(bytes(w)))
    to_ll = pyproj.Transformer.from_crs(epsg, "EPSG:4326", always_xy=True).transform
    road = ("lane", "shoulder", "parking", "no parking", "bus zone", "bus lane", "cycle lane", "paved", "bridge deck")
    rw = {u: geo(w) for u, w in c.execute(f"""SELECT unit_id, ST_AsWKB(ST_Union_Agg(ST_MakeValid(ST_Buffer(ST_Transform(geometry, 'EPSG:4326', '{epsg}',
                                              always_xy := true), 0.02)))) FROM work.part WHERE level = 0 AND type IN {road} GROUP BY 1""").fetchall()}
    subs = {u: (sid, geo(w), wd) for u, sid, w, wd in c.execute(f"SELECT subsection_id, section_id, {m('geometry')}, width_m FROM work.subsection WHERE level = 0").fetchall()}
    units = {u: geo(w) for u, w in c.execute(f"SELECT unit_id, {m('geometry')} FROM work.unit WHERE level = 0 AND kind = 'subsection'").fetchall()}
    real = shapely.union_all([geo(w) for (w,) in c.execute(f"SELECT {m('geometry')} FROM work.change WHERE class IN ('real', 'room')").fetchall()] or [shapely.Point()]) if has_change else shapely.Point()
    by_sec = {}
    for u, (sid, ln, wd) in subs.items():
        by_sec.setdefault(sid, []).append(u)
    bad = []
    for sid, us in by_sec.items():
        for i, a in enumerate(us):
            for b in us[i + 1:]:
                if a not in units or b not in units or not units[a].intersects(units[b]):
                    continue
                la, lb, half = subs[a][1], subs[b][1], (max(subs[a][2] or 0, subs[b][2] or 0) or 8.0) / 2 + 1.5
                ca = list(la.coords)
                p, q = (ca[0], ca[1]) if shapely.Point(ca[0]).distance(lb) <= shapely.Point(ca[-1]).distance(lb) else (ca[-1], ca[-2])
                jp = shapely.Point(p)
                if jp.distance(lb) > 1.0 or real.distance(jp) <= 1.0:
                    continue                # (no common end: side by side, no joint; a 'real' change: a step is allowed)
                d = (p[0] - q[0], p[1] - q[1]); h = math.hypot(*d) or 1.0
                shared = units[a].intersection(units[b]).intersection(jp.buffer(half))
                across = []
                for g in shapely.get_parts(shared):
                    if g.geom_type != "LineString" or g.length < 0.3:
                        continue
                    (x0, y0), (x1, y1) = g.coords[0], g.coords[-1]
                    e = (x1 - x0, y1 - y0); he = math.hypot(*e) or 1.0
                    if abs(d[0] * e[0] + d[1] * e[1]) / (h * he) < math.cos(math.radians(45)):
                        across.append(g)
                if not across:
                    continue
                jl = shapely.union_all(across)
                xa, xb = jl.intersection(rw.get(a, shapely.Polygon())), jl.intersection(rw.get(b, shapely.Polygon()))
                if xa.difference(xb.buffer(0.1)).length + xb.difference(xa.buffer(0.1)).length > 0.1:
                    bad.append(to_ll(jp.x, jp.y))
    return len(bad), bad


ROAD_PARTS = ("lane", "paved", "junction area", "ring", "bus lane", "bus zone", "cycle lane", "shoulder", "parking", "no parking",
              "crosswalk", "cycle crossing", "bridge deck")   # the roadway: the carriageway's parts (as the dashboard's G keeps them)
W1_M = 0.1      # W1: a road line this long or more between two pieces of roadway with no roadway under it
W2_M = 0.2      # W2: at a joint, the roadway's ends on the two sides differ by this or more


def across(jl, lines, ltree, reach=15.0):
    """The segments of a shared outline `jl` that run across a road: over 45 degrees to the road's line where it crosses the outline, and
    within `reach` of that crossing (as R1's joints). Where the outline runs along a kerb, roadway on one side and a sidewalk on the other
    is the kerb itself, not a step."""
    import math
    import shapely
    out = []
    for g in shapely.get_parts(jl):
        if g.geom_type != "LineString" or ltree is None:
            continue
        for j in ltree.query(g):
            ln = lines[j]
            for x in shapely.get_parts(ln.intersection(g)):
                if x.geom_type != "Point":
                    continue
                s_ = ln.project(x); a_, b_ = ln.interpolate(max(s_ - 1, 0)), ln.interpolate(min(s_ + 1, ln.length))
                d = (b_.x - a_.x, b_.y - a_.y); h = math.hypot(*d) or 1.0
                cs = list(g.coords)
                for p0, p1 in zip(cs, cs[1:]):
                    seg = shapely.LineString([p0, p1])
                    e = (p1[0] - p0[0], p1[1] - p0[1]); he = math.hypot(*e) or 1.0
                    if seg.distance(x) <= reach and abs(d[0] * e[0] + d[1] * e[1]) / (h * he) < math.cos(math.radians(45)):
                        out.append(seg)
    return shapely.line_merge(shapely.union_all(out)) if out else shapely.LineString()


def roadway_meets(c, epsg, level=0):
    """W1, W2: the roadway is one connected surface along every road of one level (`level`; the check runs it on every level). W1: a stretch of a road's line (W1_M or more) with
    roadway on both sides but none under it: the pieces do not meet. W2: where two spaces meet across a road, the roadway reaches the
    joint at different points on the two sides (W2_M or more): a step or a sideways shift. Each place has its cause: the spaces it lies
    in (one space, two subsections of one section, two sections, a section and an intersection) and what covers a W1 gap (a part of
    another kind, or nothing). Returns ([(lon, lat, cause)], [(lon, lat, cause)])."""
    import shapely
    import pyproj
    m = lambda g: f"ST_AsWKB(ST_Transform({g}, 'EPSG:4326', '{epsg}', always_xy := true))"
    geo = lambda w: shapely.make_valid(shapely.from_wkb(bytes(w)))
    to_ll = pyproj.Transformer.from_crs(epsg, "EPSG:4326", always_xy=True).transform
    parts = [(u, t, geo(w)) for u, t, w in c.execute(f"SELECT unit_id, type, {m('geometry')} FROM work.part WHERE level = {level}").fetchall()]
    rw_u = {}
    for u, t, g in parts:
        if t in ROAD_PARTS:
            rw_u.setdefault(u, []).append(g.buffer(0.02))
    rw_u = {u: shapely.union_all(v) for u, v in rw_u.items()}
    isl_u = {}          # (each space's islands: a median that begins at a joint is no step in the roadway)
    for u, t, g in parts:
        if t == "island":
            isl_u.setdefault(u, []).append(g.buffer(0.1))
    isl_u = {u: shapely.union_all(v) for u, v in isl_u.items()}
    rw = shapely.union_all(list(rw_u.values()) or [shapely.Polygon()])
    units = {u: (k, sec, geo(w)) for u, k, sec, w in c.execute(f"""SELECT u.unit_id, u.kind, s.section_id, {m('u.geometry')} FROM work.unit u
                 LEFT JOIN work.subsection s ON s.subsection_id = u.unit_id WHERE u.level = {level}""").fetchall()}
    uids = list(units); utree = shapely.STRtree([units[u][2] for u in uids])
    other = [(t, g) for _, t, g in parts if t not in ROAD_PARTS]; otree = shapely.STRtree([g for _, g in other]) if other else None
    area = shapely.union_all([geo(w) for (w,) in c.execute(f"SELECT {m('geometry')} FROM work.area").fetchall()] or [shapely.Polygon()]).buffer(-1.0)

    def pair(a, b):
        ka, sa = units[a][0], units[a][1]; kb, sb = units[b][0], units[b][1]
        if ka == "intersection" or kb == "intersection":
            return "a section and an intersection" if ka != kb else "two intersections"
        return "two subsections of one section" if sa and sa == sb else "two sections"
    w1, w2 = [], []
    from .blocks import street_sql
    # (the streets' lines only: a road that is no street, an unnamed service road, has no roadway, and its line crosses the outline
    # between two carriageways side by side without a joint there)
    lines = [geo(w) for (w,) in c.execute(f"SELECT {m('geometry')} FROM work.element e WHERE type = 'road' AND level_min = {level} AND {street_sql('e')}").fetchall()]
    ltree = shapely.STRtree(lines) if lines else None
    # (a road's dead end: the end node of a road line that no other road or walkway meets; there the roadway stops, no step)
    deg = {}
    for s_, d_ in c.execute(f"SELECT src, dst FROM work.element WHERE type IN ('road', 'walkway') AND level_min = {level}").fetchall():
        for n_ in (s_, d_):
            deg[n_] = deg.get(n_, 0) + 1
    dead = [shapely.Point(geo(w).coords[0 if k == 0 else -1]) for s_, d_, w in c.execute(f"""SELECT src, dst, {m('geometry')} FROM work.element
            WHERE type = 'road' AND level_min = {level}""").fetchall() for k, n_ in ((0, s_), (1, d_)) if deg.get(n_) == 1]
    dtree = shapely.STRtree(dead) if dead else None
    for ln in lines:
        for g in shapely.get_parts(ln.difference(rw)):
            if g.geom_type != "LineString" or g.length < W1_M or not area.contains(g):
                continue
            a_, b_ = shapely.Point(g.coords[0]), shapely.Point(g.coords[-1])
            if a_.distance(rw) > 0.05 or b_.distance(rw) > 0.05 or ln.boundary.distance(a_) < 0.05 or ln.boundary.distance(b_) < 0.05:
                continue                    # (the road's own end, or a stretch off the roadway at one side: A3's)
            mid = g.interpolate(0.5, normalized=True)
            s_ = ln.project(mid); p0, p1 = ln.interpolate(max(s_ - 1, 0)), ln.interpolate(min(s_ + 1, ln.length))
            dx, dy = p1.x - p0.x, p1.y - p0.y; h_ = (dx * dx + dy * dy) ** 0.5 or 1.0
            sides = [shapely.LineString([(mid.x, mid.y), (mid.x - k * dy / h_ * 3.0, mid.y + k * dx / h_ * 3.0)]) for k in (1, -1)]
            if sum(q.intersects(rw) for q in sides) == 1:
                continue                    # (the line runs along a kerb, roadway on one side only: A1's, not a gap in the road)
            ins = [uids[k] for k in utree.query(g.buffer(0.3)) if units[uids[k]][2].distance(mid) < 0.3]
            near = [uids[k] for k in utree.query(g) if units[uids[k]][2].intersects(g)]
            where = "outside every space" if not ins else ("in one space" if len(set(near)) <= 1 else "between " + pair(*sorted(set(near))[:2]))
            cover = sorted({other[k][0] for k in (otree.query(mid) if otree else []) if other[k][1].contains(mid)})
            w1.append(to_ll(mid.x, mid.y) + (f"gap {where}, under it: " + (", ".join(cover) or "no part"),))
    for i, a in enumerate(uids):
        for k in utree.query(units[a][2]):
            b = uids[k]
            if b <= a:
                continue
            sh = units[a][2].intersection(units[b][2])
            jl = shapely.line_merge(shapely.union_all([g for g in shapely.get_parts(sh) if g.geom_type in ("LineString", "MultiLineString")] or [shapely.LineString()]))
            # (a joint is a piece of the shared outline that a road's line crosses: where the outline runs along a kerb, roadway on one
            # side and a sidewalk on the other is the kerb itself, not a step)
            jl = across(jl, lines, ltree)
            if jl.is_empty or jl.length < 0.3:
                continue
            if dtree is not None and any(dead[k].distance(jl) < 1.0 for k in dtree.query(jl.buffer(1.0))):
                continue                    # (a road's dead end: the roadway stops there)
            xa, xb = jl.intersection(rw_u.get(a, shapely.Polygon())), jl.intersection(rw_u.get(b, shapely.Polygon()))
            if xa.is_empty and xb.is_empty:
                continue
            # (a stretch where one side has roadway and the other an island is a median's nose at the joint: the road divides round a
            # real island there, no step in its edge; counting islands as roadway everywhere turned every island beside a sidewalk into a step)
            dd_ = [q for g, other in ((xa.difference(xb.buffer(W2_M / 2)), b), (xb.difference(xa.buffer(W2_M / 2)), a)) for q in shapely.get_parts(g)
                   if not q.is_empty and not (other in isl_u and q.difference(isl_u[other]).length < 0.1)]
            d = sum(q.length for q in dd_)
            if d >= W2_M:
                p_ = max(dd_, key=lambda q: q.length).interpolate(0.5, normalized=True) if dd_ else (xa.union(xb)).representative_point()
                # (the mark at the step itself, the middle of its longest piece: the joint's middle lay up to 9 m from it)
                w2.append(to_ll(p_.x, p_.y) + (f"shift at a joint between {pair(a, b)}",))
    return w1, w2



W3_M = 0.5      # W3: at a node where roads of two levels meet, each level's roadway comes this near the node


def level_reach(c, epsg):
    """W3: at each node inside the area where streets of two or more levels meet (a tunnel's entrance, a ramp onto a deck), the roadway of
    every level reaches the node (within W3_M) from each of its streets there: else the levels do not join (Monaco, 2026-10-23: 49 of 133
    such nodes, most at tunnel entrances, a gap of 1 to 14 m). Returns [(lon, lat, what)]."""
    import shapely
    import pyproj
    m = lambda g: f"ST_AsWKB(ST_Transform({g}, 'EPSG:4326', '{epsg}', always_xy := true))"
    geo = lambda w: shapely.make_valid(shapely.from_wkb(bytes(w)))
    to_ll = pyproj.Transformer.from_crs(epsg, "EPSG:4326", always_xy=True).transform
    from .blocks import street_sql
    ends = {}
    # (streets only, as W1: a road that is no street, an unnamed service road such as a garage ramp, has no roadway by design)
    for oid, s_, d_, lv, w in c.execute(f"SELECT osm_id, src, dst, level_min, {m('geometry')} FROM work.element e WHERE type = 'road' AND {street_sql('e')}").fetchall():
        g = geo(w)
        if g.geom_type != "LineString":
            continue
        ends.setdefault(s_, []).append((lv, oid, shapely.Point(g.coords[0])))
        ends.setdefault(d_, []).append((lv, oid, shapely.Point(g.coords[-1])))
    rw = {}
    for lv, w in c.execute(f"SELECT level, {m('geometry')} FROM work.part WHERE type IN (SELECT unnest(?::VARCHAR[]))", [list(ROAD_PARTS)]).fetchall():
        rw.setdefault(lv, []).append(geo(w))
    rw = {lv: shapely.union_all(v) for lv, v in rw.items()}
    area = shapely.union_all([geo(w) for (w,) in c.execute(f"SELECT {m('geometry')} FROM work.area").fetchall()] or [shapely.Polygon()]).buffer(-5.0)
    out = []
    for n, es in ends.items():
        lvs = sorted({e[0] for e in es})
        if len(lvs) < 2 or not area.contains(es[0][2]):
            continue
        miss = sorted({(lv, oid) for lv, oid, p in es if lv not in rw or rw[lv].distance(p) > W3_M})
        if miss:
            p = es[0][2]
            out.append(to_ll(p.x, p.y) + (f"node n{n}, levels {lvs}: no roadway at the node for " + ", ".join(f"w{o} (level {l})" for l, o in miss),))
    return out

def run(path, out=None):
    """The checks of the database at `path`, printed; True when a hard check fails. `out`: a list the rows go to (urban.check)."""
    c = duckdb.connect(path, read_only=True)
    c.execute("LOAD spatial")
    lon = c.execute("SELECT avg(ST_X(ST_Centroid(geometry))) FROM work.container").fetchone()[0]
    epsg = f"EPSG:{32600 + int((lon + 180) // 6) + 1}"
    m = f"ST_Transform(geometry, 'EPSG:4326', '{epsg}', always_xy := true)"
    q = lambda sql: c.execute(sql).fetchone()[0]
    c.execute(f"""CREATE TEMP TABLE m AS SELECT container_id, level, kind, ST_MakeValid(ST_Buffer({m}, -0.01)) AS g, ST_Area({m}) AS a
                  FROM work.container""")
    rows = [  # id, what, value, hard (a nonzero value fails), expected-text
        ("P1", "container pairs overlapping by more than 0.5 m2", q("""SELECT count(*) FROM m a JOIN m b ON a.level = b.level AND a.container_id < b.container_id
                                  AND ST_Intersects(a.g, b.g) WHERE ST_Area(ST_Intersection(a.g, b.g)) > 0.5"""), True),
        ("P3", "invalid, empty or under 1 m2 containers", q("SELECT count(*) FROM m JOIN work.container c USING (container_id) "
                                                          "WHERE NOT ST_IsValid(c.geometry) OR ST_IsEmpty(c.geometry) OR m.a < 1"), True),
        ("P4", "containers with more than one part", q("SELECT count(*) FROM work.container WHERE ST_NumGeometries(geometry) > 1"), True),
        ("P5", "elements with no container or one that does not exist", q("""SELECT count(*) FROM work.element WHERE type <> 'building'
                                  AND (container_id IS NULL OR container_id NOT IN (SELECT container_id FROM work.container))"""), True),
        ("P6", "containers with a kind that is not allowed", q(f"SELECT count(*) FROM work.container WHERE kind NOT IN {KINDS}"), True),
        ("P7", "duplicate container ids", q("SELECT count(*) - count(DISTINCT container_id) FROM work.container"), True),
        ("S1", "sections with no road or no street_id", q("SELECT count(*) FROM work.container WHERE kind = 'section' AND (n_road = 0 OR street_id IS NULL)"), True),
        ("S2", "sections that meet more than two intersections", q("""SELECT count(*) FROM (SELECT s.container_id FROM work.container s
                                  JOIN work.arm a ON a.section_id = s.container_id GROUP BY 1 HAVING count(DISTINCT a.intersection_id) > 2)"""), True),
        ("I1", "intersections with fewer than 3 arms", q("""SELECT count(*) FROM work.container i WHERE i.kind = 'intersection'
                                  AND (SELECT count(*) FROM work.arm a WHERE a.intersection_id = i.container_id) < 3"""), True),
        ("I2", "intersections with only one street group (a loop road is the one legitimate case)", q("""SELECT count(*) FROM work.container i
                                  WHERE i.kind = 'intersection' AND (SELECT count(DISTINCT street_id) FROM work.arm a WHERE a.intersection_id = i.container_id) < 2"""), False),
        ("I3", "intersections of the old container step outside 30 to 10,000 m2", q("SELECT count(*) FROM m WHERE kind = 'intersection' AND (a < 30 OR a > 10000)"), True,
         [tuple(r) for r in c.execute("""SELECT ST_X(ST_PointOnSurface(x.geometry)), ST_Y(ST_PointOnSurface(x.geometry)) FROM work.container x
                                          JOIN m USING (container_id) WHERE m.kind = 'intersection' AND (m.a < 30 OR m.a > 10000)""").fetchall()]),
    ]
    # C2: the strips of a container add up to the container (its two zones cover it), within 3% or 1.5 m2
    za = f"ST_Area(ST_Transform(geometry, 'EPSG:4326', '{epsg}', always_xy := true))"
    rows.append(("C2", "containers whose strips do not add up to their area (3% or 1.5 m2)", q(f"""SELECT count(*) FROM (
        SELECT c.container_id, {za} AS a, coalesce(s.a, 0) AS sa FROM work.container c
        LEFT JOIN (SELECT container_id, sum({za}) AS a FROM work.strip GROUP BY 1) s USING (container_id)
        WHERE c.kind IN ('section', 'intersection') AND abs({za} - coalesce(s.a, 0)) > greatest(0.03 * {za}, 1.5))"""), True))
    # I4: an arm's node should lie in (or within 3 m of) its intersection
    c.execute(f"""CREATE TEMP TABLE nodepts AS
                  SELECT src AS node, ST_StartPoint(geometry) AS p FROM work.element WHERE type = 'road' AND src IS NOT NULL
                  UNION SELECT dst, ST_EndPoint(geometry) FROM work.element WHERE type = 'road' AND dst IS NOT NULL""")
    rows.append(("I4", "arm nodes more than 3 m from their intersection", q(f"""SELECT count(*) FROM (SELECT DISTINCT a.intersection_id, a.node_id FROM work.arm a) a
                  JOIN work.container i ON i.container_id = a.intersection_id JOIN nodepts n ON n.node = a.node_id
                  WHERE ST_Distance(ST_Transform(i.geometry, 'EPSG:4326', '{epsg}', always_xy := true),
                                    ST_Transform(n.p, 'EPSG:4326', '{epsg}', always_xy := true)) > 3"""), False))
    if q("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'work' AND table_name = 'unit'"):
        rows += unit_checks(c, q, epsg)
        rows += rule_checks(c, epsg)
        if q("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'work' AND table_name = 'part'"):
            w1, w2 = [], []
            for (lv,) in c.execute("SELECT DISTINCT level FROM work.part ORDER BY 1").fetchall():      # (every level: tunnels and decks too)
                a_, b_ = roadway_meets(c, epsg, lv)
                w1 += a_; w2 += b_
            w3 = level_reach(c, epsg)
            rows += [("W1", f"stretches of a road line ({W1_M} m or more) between two pieces of roadway with none under it, on any level: the pieces do not meet", len(w1), True, [p[:2] for p in w1]),
                     ("W2", f"joints where the roadway reaches the two sides at points {W2_M} m or more apart, on any level (a step or a sideways shift)", len(w2), True, [p[:2] for p in w2]),
                     ("W3", f"nodes where streets of two levels meet (a tunnel's entrance, a ramp) and one level's roadway stops more than {W3_M} m short: the levels do not join", len(w3), True, [p[:2] for p in w3])]
    total = q("SELECT count(*) FROM work.container")
    print(f"\n== {path}  ({total} containers, all levels)")
    failed = False
    for cid, what, value, hard, *at in rows:
        status = "PASS" if value == 0 else ("FAIL" if hard else "INFO")
        failed |= status == "FAIL"
        print(f"  {cid:3s} {status:5s} {value:6d}  {what}")
        for x, y in (at[0] if at else [])[:5]:      # where: a page link opens there (dashboard ?at=)
            print(f"            ?at={x:.6f},{y:.6f},20,60,0")
    c.close()
    if out is not None:
        out += rows
    return failed



ON_GROUND_M = 2.5      # BR12: a lane this near the ground (deck height) is where an object can stand in it


def objects_in_lanes(M, c, db):
    """BR12: street objects of a real source (a city's survey, OSM; not Mapillary alone, its positions are too rough) whose point stands
    inside a lane of the bridge model: the source places it, so the lane is wrong there (Granville Bridge, lamp
    street-lighting-poles-133 in lane a2.1 at its landing; Kaveh, 2026-10-13)."""
    import math
    import pyproj
    import shapely
    from .dashboard import epsg_of, matched_objects
    ep = epsg_of(c)
    to_ll = pyproj.Transformer.from_crs(ep, "EPSG:4326", always_xy=True).transform
    ox, oy = M["origin"]
    k = 111320 * math.cos(math.radians(oy))         # (the page's metres at the model's origin, as the model is placed)
    lanes = [shapely.union_all([shapely.Polygon([sf["v"][i][:2] for i in t]) for t in sf["f"] if len({tuple(sf["v"][i][:2]) for i in t}) == 3])
             for sf in M["surf"] if sf.get("props") and sf["key"].startswith("lane") and sf["props"].get("type") == "lane"]
    vz = [[v for v in sf["v"]] for sf in M["surf"] if sf.get("props") and sf["key"].startswith("lane") and sf["props"].get("type") == "lane"]
    lane_z = [(lambda V: lambda q: min(V, key=lambda v: (v[0] - q.x) ** 2 + (v[1] - q.y) ** 2)[2])(V) for V in vz]   # the deck's height there
    tree = shapely.STRtree(lanes)
    at = []
    for oid, cls, lv, grp, p, refs, sources, *_ in matched_objects(c, ep, db):
        if set(s_.strip() for s_ in str(sources).split(",")) <= {"mapillary"}:
            continue
        lon, lat = to_ll(p.x, p.y)
        q = shapely.Point((lon - ox) * k, (lat - oy) * 111320)
        for j in tree.query(q):
            if lanes[j].contains(q) and lane_z[j](q) < ON_GROUND_M:      # (a lane high on the deck passes over it)
                at.append((lon, lat))
                break
    return ("BR12", f"street objects of a city's survey or OSM standing inside a bridge lane (where it is under {ON_GROUND_M} m high)", len(at), True, at)


def bridge(profile, db=None, out=None):
    """The bridge model's checks (bridge3d.model_checks) for a bridge profile, as the page draws it: with a unit's `db`, its street's
    lanes near the bridge for the landings (as the dashboard passes them)."""
    import json
    import shapely
    from .bridge3d import model
    P = json.load(open(profile))
    ground = None
    if db:
        c = duckdb.connect(db, read_only=True)
        c.execute("LOAD spatial")
        from .bridge_profile import deck_polygon
        ol = deck_polygon(P)
        to_crs = f"ST_Transform(geometry, 'EPSG:4326', '{P['crs']}', always_xy := true)"
        ground = [g for (w,) in c.execute(f"SELECT ST_AsWKB({to_crs}) FROM work.part WHERE level = 0 AND type = 'lane'").fetchall()
                  for g in [shapely.from_wkb(bytes(w))] if g.distance(ol) < 50]
    print(f"\n== {profile}  (bridge model: {P['name']})")
    failed = False
    poles = None
    if db:
        from .dashboard import bridge_poles
        from .bridge_profile import deck_polygon
        poles = bridge_poles(c, P["crs"], deck_polygon(P), db)
    M = model(P, None, None, ground, poles=poles)
    rows = list(M["checks"])
    if db:
        rows.append(objects_in_lanes(M, c, db))
    for cid, what, value, hard, at in rows:
        status = "PASS" if value == 0 else ("FAIL" if hard else "INFO")
        failed |= status == "FAIL"
        print(f"  {cid:3s} {status:5s} {value:6d}  {what}")
        for x, y in at[:5]:         # where: a page link opens there in 3D (dashboard ?at=)
            print(f"            ?at={x:.6f},{y:.6f},20,60,0")
    if db:
        c.close()
    if out is not None:
        out += [(cid, f"{P['name']}: {what}", value, hard, at) for cid, what, value, hard, at in rows]
    return failed
