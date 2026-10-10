"""Conformance checks for a built urbanstyle database (docs/design/street-space-spec.md, section 8).

    urbanstyle check data/monaco.duckdb [more.duckdb ...]

Prints one line per invariant: id, what is counted, the count, PASS / FAIL (or INFO for a reported number). Exit code 1 if a hard check fails.
"""

import duckdb

KINDS = ("section", "intersection", "path", "rail", "plaza")


def unit_checks(c, q, epsg):
    """U1-U7: the network-first spaces (space.unit, docs/design/network-first.md). A junction node must lie in its own intersection
    and in no road's space or line, or a click on it in the dashboard opens the road instead of the intersection."""
    m = lambda g: f"ST_Transform({g}, 'EPSG:4326', '{epsg}', always_xy := true)"
    c.execute(f"""CREATE TEMP TABLE u AS SELECT unit_id, kind, level, ST_MakeValid(ST_Buffer({m('geometry')}, -0.01)) AS g FROM space.unit""")
    c.execute(f"""CREATE TEMP TABLE jn AS SELECT DISTINCT a.intersection_id, a.level, n.p FROM space.junction a
                  JOIN (SELECT src AS node, {m('ST_StartPoint(geometry)')} AS p FROM space.element WHERE type = 'road' AND src IS NOT NULL
                        UNION SELECT dst, {m('ST_EndPoint(geometry)')} FROM space.element WHERE type = 'road' AND dst IS NOT NULL) n ON n.node = a.node_id""")
    return [
        ("U1", "spaces overlapping by more than 0.5 m2", q("""SELECT count(*) FROM u a JOIN u b ON a.level = b.level AND a.unit_id < b.unit_id
                                  AND ST_Intersects(a.g, b.g) WHERE ST_Area(ST_Intersection(a.g, b.g)) > 0.5"""), True),
        ("U2", "spaces invalid, empty or in more than one part", q("""SELECT count(*) FROM space.unit
                                  WHERE NOT ST_IsValid(geometry) OR ST_IsEmpty(geometry) OR ST_NumGeometries(geometry) > 1"""), True),
        ("U3", "junctions with no intersection space", q("""SELECT count(DISTINCT intersection_id) FROM space.junction
                                  WHERE intersection_id NOT IN (SELECT unit_id FROM space.unit)"""), True),
        ("U4", "junction nodes outside their own intersection space (> 0.5 m)", q("""SELECT count(*) FROM jn
                                  JOIN u ON u.unit_id = jn.intersection_id WHERE ST_Distance(u.g, jn.p) > 0.5"""), True),
        ("U5", "junction nodes inside a road's space", q("""SELECT count(*) FROM jn JOIN u ON u.kind = 'subsection' AND u.level = jn.level
                                  AND ST_Intersects(u.g, jn.p)"""), True),
        ("U6", "subsection lines reaching more than 1 m into an intersection", q(f"""SELECT count(*) FROM space.subsection s
                                  JOIN u ON u.kind IN ('intersection', 'roundabout') AND u.level = s.level AND ST_Intersects(u.g, {m('s.geometry')})
                                  WHERE ST_Length(ST_Intersection(u.g, {m('s.geometry')})) > 1"""), True),
        ("U7", "subsections with no space", q("SELECT count(*) FROM space.subsection WHERE subsection_id NOT IN (SELECT unit_id FROM space.unit)"), True),
    ] + part_checks(c, q, m)


def part_checks(c, q, m):
    """U8-U10: the parts of a space (space.part, docs/design/space-parts.md) cover it exactly."""
    if not q("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'space' AND table_name = 'part'"):
        return []
    c.execute(f"CREATE TEMP TABLE pt AS SELECT unit_id, part_id, ST_MakeValid(ST_Buffer({m('geometry')}, -0.01)) AS g, ST_Area({m('geometry')}) AS a FROM space.part")
    return [
        ("U8", "spaces whose parts do not add up to them (3% or 1.5 m2)", q(f"""SELECT count(*) FROM (SELECT u.unit_id, ST_Area({m('u.geometry')}) AS a,
                                  coalesce(sum(p.a), 0) AS pa FROM space.unit u LEFT JOIN pt p USING (unit_id) GROUP BY u.unit_id, u.geometry)
                                  WHERE abs(a - pa) > greatest(0.03 * a, 1.5)"""), True),
        ("U9", "parts of one space overlapping by more than 0.5 m2", q("""SELECT count(*) FROM pt a JOIN pt b ON a.unit_id = b.unit_id AND a.part_id < b.part_id
                                  AND ST_Intersects(a.g, b.g) WHERE ST_Area(ST_Intersection(a.g, b.g)) > 0.5"""), True),
        ("U10", "cuts where the roadway differs by more than 0.5 m on the two sides", roadway_mismatch(c, q, m), False),
    ] + approach_checks(q)


def approach_checks(q):
    """U11-U13: the lanes coming into each junction (space.approach, written by parts.py) and what they may do. Reported, not failed: a
    missing move may be the law (a turn restriction, a T junction); the number says where to look."""
    if not q("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'space' AND table_name = 'approach'"):
        return []
    return [
        ("U11", "lanes entering a junction with no move at all", q("SELECT count(*) FROM space.approach WHERE moves = 0"), False),
        # at a junction of 4 or more approaches each one usually goes straight on (at a T the stem cannot): the others are worth a look
        ("U12", "approaches with no straight move for all traffic, at junctions of 4+ approaches", q("""WITH ap AS (
                                  SELECT a.unit_id, a.from_edge, bool_or(a.ways LIKE '%straight%') AS straight FROM space.approach a
                                  JOIN space.unit u USING (unit_id) WHERE u.kind = 'intersection' AND a.moves > 0 GROUP BY ALL)
                                  SELECT count(*) FROM ap WHERE NOT straight AND unit_id IN (SELECT unit_id FROM ap GROUP BY 1 HAVING count(*) >= 4)"""), False),
        ("U13", "lanes with a move for all traffic but no turn arrow (a lane piece under 4 m, another arrow in the way)", q("""SELECT count(*)
                                  FROM space.approach WHERE NOT arrow AND no_arrow_because IN ('lane piece under 4 m', 'another arrow in the way')"""), False),
    ]


def roadway_mismatch(c, q, m):
    """Along each cut line, the roadway (lanes, shoulders, bus / cycle lanes, crosswalks, junction area) on the intersection side and on the
    road side should be the same width: the arm and the road meet there."""
    road = "('lane', 'shoulder', 'bus lane', 'cycle lane', 'cycle crossing', 'island', 'crosswalk', 'junction area', 'carriageway')"
    return q(f"""WITH cut AS (SELECT intersection_id, edge_id, {m('geometry')} AS g FROM space.cut),
      rw AS (SELECT unit_id, ST_MakeValid(ST_Union_Agg(ST_MakeValid(ST_Buffer({m('geometry')}, 0.01)))) AS g FROM space.part WHERE type IN {road} GROUP BY unit_id),
      side AS (SELECT cut.intersection_id, cut.edge_id, ST_Length(ST_Intersection(cut.g, ST_Buffer(i.g, 0.3))) AS iw,
                 (SELECT max(ST_Length(ST_Intersection(cut.g, ST_Buffer(s.g, 0.3)))) FROM rw s JOIN space.unit su ON su.unit_id = s.unit_id
                  WHERE su.kind = 'subsection' AND ST_DWithin(s.g, cut.g, 0.5)) AS sw
               FROM cut JOIN rw i ON i.unit_id = cut.intersection_id)
      SELECT count(*) FROM side WHERE sw IS NOT NULL AND abs(iw - sw) > 0.5""")


def run(path):
    c = duckdb.connect(path, read_only=True)
    c.execute("LOAD spatial")
    lon = c.execute("SELECT avg(ST_X(ST_Centroid(geometry))) FROM space.container").fetchone()[0]
    epsg = f"EPSG:{32600 + int((lon + 180) // 6) + 1}"
    m = f"ST_Transform(geometry, 'EPSG:4326', '{epsg}', always_xy := true)"
    q = lambda sql: c.execute(sql).fetchone()[0]
    c.execute(f"""CREATE TEMP TABLE m AS SELECT container_id, level, kind, ST_MakeValid(ST_Buffer({m}, -0.01)) AS g, ST_Area({m}) AS a
                  FROM space.container""")
    rows = [  # id, what, value, hard (a nonzero value fails), expected-text
        ("P1", "container pairs overlapping by more than 0.5 m2", q("""SELECT count(*) FROM m a JOIN m b ON a.level = b.level AND a.container_id < b.container_id
                                  AND ST_Intersects(a.g, b.g) WHERE ST_Area(ST_Intersection(a.g, b.g)) > 0.5"""), True),
        ("P3", "invalid, empty or under 1 m2 containers", q("SELECT count(*) FROM m JOIN space.container c USING (container_id) "
                                                          "WHERE NOT ST_IsValid(c.geometry) OR ST_IsEmpty(c.geometry) OR m.a < 1"), True),
        ("P4", "containers with more than one part", q("SELECT count(*) FROM space.container WHERE ST_NumGeometries(geometry) > 1"), True),
        ("P5", "elements with no container or one that does not exist", q("""SELECT count(*) FROM space.element WHERE type <> 'building'
                                  AND (container_id IS NULL OR container_id NOT IN (SELECT container_id FROM space.container))"""), True),
        ("P6", "containers with a kind that is not allowed", q(f"SELECT count(*) FROM space.container WHERE kind NOT IN {KINDS}"), True),
        ("P7", "duplicate container ids", q("SELECT count(*) - count(DISTINCT container_id) FROM space.container"), True),
        ("S1", "sections with no road or no street_id", q("SELECT count(*) FROM space.container WHERE kind = 'section' AND (n_road = 0 OR street_id IS NULL)"), True),
        ("S2", "sections that meet more than two intersections", q("""SELECT count(*) FROM (SELECT s.container_id FROM space.container s
                                  JOIN space.arm a ON a.section_id = s.container_id GROUP BY 1 HAVING count(DISTINCT a.intersection_id) > 2)"""), True),
        ("I1", "intersections with fewer than 3 arms", q("""SELECT count(*) FROM space.container i WHERE i.kind = 'intersection'
                                  AND (SELECT count(*) FROM space.arm a WHERE a.intersection_id = i.container_id) < 3"""), True),
        ("I2", "intersections with only one street group (a loop road is the one legitimate case)", q("""SELECT count(*) FROM space.container i
                                  WHERE i.kind = 'intersection' AND (SELECT count(DISTINCT street_id) FROM space.arm a WHERE a.intersection_id = i.container_id) < 2"""), False),
        ("I3", "intersections outside 30 to 10,000 m2", q("SELECT count(*) FROM m WHERE kind = 'intersection' AND (a < 30 OR a > 10000)"), True),
    ]
    # C2: the strips of a container add up to the container (its two zones cover it), within 3% or 1.5 m2
    za = f"ST_Area(ST_Transform(geometry, 'EPSG:4326', '{epsg}', always_xy := true))"
    rows.append(("C2", "containers whose strips do not add up to their area (3% or 1.5 m2)", q(f"""SELECT count(*) FROM (
        SELECT c.container_id, {za} AS a, coalesce(s.a, 0) AS sa FROM space.container c
        LEFT JOIN (SELECT container_id, sum({za}) AS a FROM space.strip GROUP BY 1) s USING (container_id)
        WHERE c.kind IN ('section', 'intersection') AND abs({za} - coalesce(s.a, 0)) > greatest(0.03 * {za}, 1.5))"""), True))
    # I4: an arm's node should lie in (or within 3 m of) its intersection
    c.execute(f"""CREATE TEMP TABLE nodepts AS
                  SELECT src AS node, ST_StartPoint(geometry) AS p FROM space.element WHERE type = 'road' AND src IS NOT NULL
                  UNION SELECT dst, ST_EndPoint(geometry) FROM space.element WHERE type = 'road' AND dst IS NOT NULL""")
    rows.append(("I4", "arm nodes more than 3 m from their intersection", q(f"""SELECT count(*) FROM (SELECT DISTINCT a.intersection_id, a.node_id FROM space.arm a) a
                  JOIN space.container i ON i.container_id = a.intersection_id JOIN nodepts n ON n.node = a.node_id
                  WHERE ST_Distance(ST_Transform(i.geometry, 'EPSG:4326', '{epsg}', always_xy := true),
                                    ST_Transform(n.p, 'EPSG:4326', '{epsg}', always_xy := true)) > 3"""), False))
    if q("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'space' AND table_name = 'unit'"):
        rows += unit_checks(c, q, epsg)
    total = q("SELECT count(*) FROM space.container")
    print(f"\n== {path}  ({total} containers, all levels)")
    failed = False
    for cid, what, value, hard in rows:
        status = "PASS" if value == 0 else ("FAIL" if hard else "INFO")
        failed |= status == "FAIL"
        print(f"  {cid:3s} {status:5s} {value:6d}  {what}")
    return failed

