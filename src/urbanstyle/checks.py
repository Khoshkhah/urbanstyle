"""Conformance checks for a built urbanstyle database (docs/design/street-space-spec.md, section 8).

    urbanstyle check data/monaco.duckdb [more.duckdb ...]

Prints one line per invariant: id, what is counted, the count, PASS / FAIL (or INFO for a reported number). Exit code 1 if a hard check fails.
"""

import duckdb

KINDS = ("section", "intersection", "path", "rail", "plaza")


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
    total = q("SELECT count(*) FROM space.container")
    print(f"\n== {path}  ({total} containers, all levels)")
    failed = False
    for cid, what, value, hard in rows:
        status = "PASS" if value == 0 else ("FAIL" if hard else "INFO")
        failed |= status == "FAIL"
        print(f"  {cid:3s} {status:5s} {value:6d}  {what}")
    return failed

