import duckdb

import urbanstyle

ROAD = "ST_GeomFromText('LINESTRING(18.0 59.3, 18.001 59.3)')"
SQUARE = "ST_GeomFromText('POLYGON((18 60, 18.001 60, 18.001 60.001, 18 60.001, 18 60))')"  # far from the road


def make_osm(path, buildings=(), edges=None, rails=(), stations=()):
    """A minimal duckOSM db: features.buildings (id, tags, wkt-expression) and mode edge tables."""
    o = duckdb.connect(str(path))
    o.execute("INSTALL spatial; LOAD spatial; CREATE SCHEMA features; CREATE SCHEMA raw")
    o.execute("CREATE TABLE raw.nodes (osm_id BIGINT, lat DOUBLE, lon DOUBLE, tags MAP(VARCHAR, VARCHAR))")
    o.execute("CREATE TABLE raw.ways (osm_id BIGINT, tags MAP(VARCHAR, VARCHAR), refs BIGINT[])")
    o.execute("""CREATE TABLE features.buildings (osm_id BIGINT, osm_type VARCHAR, kind VARCHAR, name VARCHAR,
                 tags MAP(VARCHAR, VARCHAR), geom GEOMETRY)""")
    for i, tags, geom in buildings:
        tag_sql = ", ".join(f"'{k}': '{v}'" for k, v in tags.items())
        o.execute(f"INSERT INTO features.buildings VALUES ({i}, 'way', 'yes', NULL, "
                  f"CAST(MAP {{{tag_sql}}} AS MAP(VARCHAR, VARCHAR)), {geom})")
    for tbl in ("streets", "public_transport"):
        o.execute(f"""CREATE TABLE features.{tbl} (osm_id BIGINT, osm_type VARCHAR, kind VARCHAR, name VARCHAR,
                      tags MAP(VARCHAR, VARCHAR), geom GEOMETRY)""")
    mapsql = lambda tags: "CAST(MAP {" + ", ".join(f"'{k}': '{v}'" for k, v in tags.items()) + "} AS MAP(VARCHAR, VARCHAR))"
    for i, kind, tags, geom, refs in rails:
        o.execute(f"INSERT INTO features.streets VALUES ({i}, 'way', '{kind}', NULL, {mapsql(tags)}, {geom})")
        o.execute(f"INSERT INTO raw.ways VALUES ({i}, {mapsql(tags)}, {refs})")
    for i, kind, tags, geom, name in stations:
        o.execute(f"INSERT INTO features.public_transport VALUES ({i}, 'node', '{kind}', '{name}', {mapsql(tags)}, {geom})")
    for mode in ("driving", "walking", "cycling"):
        o.execute(f"CREATE SCHEMA {mode}")
        o.execute(f"""CREATE TABLE {mode}.edges (edge_id BIGINT, osm_id BIGINT, source BIGINT, target BIGINT, highway VARCHAR,
                      name VARCHAR, layer VARCHAR, bridge VARCHAR, tunnel VARCHAR, lanes INT, geometry GEOMETRY, oneway BOOLEAN)""")
    for mode, row in (edges or {"driving": [f"(1, 100, 1, 2, 'residential', 'Main St', NULL, NULL, NULL, NULL, {ROAD})"]}).items():
        for r in row:
            o.execute(f"INSERT INTO {mode}.edges (edge_id, osm_id, source, target, highway, name, layer, bridge, tunnel, lanes, geometry) VALUES {r}")
    o.close()
    return str(path)


def test_level_rules(tmp_path):
    osm = make_osm(tmp_path / "osm.duckdb", [
        (1, {"building:levels": "3"}, SQUARE),                                     # 0..2
        (2, {"height": "10"}, SQUARE),                                             # 10 m -> 3 floors -> 0..2
        (3, {}, SQUARE),                                                           # unknown -> 0..0
        (4, {"building:levels": "2", "building:levels:underground": "1"}, SQUARE),  # -1..1
        (5, {"location": "underground"}, SQUARE),                                  # -1..-1
        (6, {"building:levels": "10", "building:levels:underground": "4"}, SQUARE),  # clamped to -2..2
        (7, {"building:levels": "3", "building:min_level": "5"}, SQUARE),          # floors 5..7: above the kept range, dropped
    ])
    con = urbanstyle.build(osm, str(tmp_path / "out.duckdb"))
    got = dict(con.execute("SELECT source_id, [level_min, level_max] FROM space.element WHERE type = 'building'").fetchall())
    assert got == {"w1": [0, 2], "w2": [0, 2], "w3": [0, 0], "w4": [-1, 1], "w5": [-1, -1], "w6": [-2, 2]}


def test_containers(tmp_path):
    line = lambda dy: f"ST_GeomFromText('LINESTRING(18.0 {59.3 + dy}, 18.001 {59.3 + dy})')"
    osm = make_osm(tmp_path / "osm.duckdb", edges={
        "driving": [f"(1, 100, 1, 2, 'residential', 'Main St', NULL, NULL, NULL, NULL, {line(0)})"],
        "walking": [f"(1, 100, 1, 2, 'residential', 'Main St', NULL, NULL, NULL, NULL, {line(0)})",
                    f"(2, 200, 3, 4, 'footway', NULL, NULL, NULL, NULL, NULL, {line(0.00005)})",  # ~5 m from the road: joins it
                    f"(3, 300, 5, 6, 'footway', NULL, NULL, NULL, NULL, NULL, {line(0.001)})"]})  # ~110 m away: own container
    con = urbanstyle.build(osm, str(tmp_path / "out.duckdb"))
    got = dict(con.execute("SELECT source_id, container_id FROM space.element WHERE type <> 'building'").fetchall())
    assert got == {"1": "s0-1", "2": "s0-1", "3": "p0-300"}
    assert con.execute("SELECT n_road, n_walkway FROM space.container WHERE container_id = 's0-1'").fetchone() == (1, 1)


def test_street_space_width(tmp_path):
    """A road with a building 10 m to its left and 6 m to its right: street space ~16 m wide, and not open."""
    dy = lambda m: m / 111_320  # metres to degrees of latitude
    box = lambda y0, y1: (f"ST_GeomFromText('POLYGON((17.9995 {59.3 + y0}, 18.0015 {59.3 + y0}, 18.0015 {59.3 + y1}, "
                          f"17.9995 {59.3 + y1}, 17.9995 {59.3 + y0}))')")
    osm = make_osm(tmp_path / "osm.duckdb", [
        (1, {"building:levels": "3"}, box(dy(10), dy(40))),
        (2, {"building:levels": "3"}, box(-dy(40), -dy(6)))],
        edges={"driving": [f"(1, 100, 1, 2, 'residential', 'Main St', NULL, NULL, NULL, 2, {ROAD})",
                           f"(2, 101, 3, 4, 'residential', 'Bridge St', NULL, 'yes', NULL, 2, {ROAD})"]})
    con = urbanstyle.build(osm, str(tmp_path / "out.duckdb"))
    w, op = con.execute("SELECT mean_width_m, open_share FROM space.container WHERE container_id = 's0-1'").fetchone()
    assert 15 <= w <= 17 and op == 0, (w, op)
    assert con.execute("SELECT mean_width_m FROM space.container WHERE container_id = 's1-2'").fetchone() == (None,)  # bridge: no rays


def test_links(tmp_path):
    """Road -> tunnel meet at node 2 (ramp 0/-1); footway -> steps on layer 1 meet at node 6 (stairs 0/1); node 5 is a subway entrance."""
    line = lambda x0, x1, y=0: f"ST_GeomFromText('LINESTRING({18 + x0} {59.3 + y}, {18 + x1} {59.3 + y})')"
    osm = make_osm(tmp_path / "osm.duckdb", edges={
        "driving": [f"(1, 100, 1, 2, 'residential', 'A', NULL, NULL, NULL, 2, {line(0, .001)})",
                    f"(2, 101, 2, 3, 'residential', 'B', NULL, NULL, 'yes', 2, {line(.001, .002)})"],
        "walking": [f"(3, 103, 5, 6, 'footway', NULL, NULL, NULL, NULL, NULL, {line(0, .001, .001)})",
                    f"(4, 102, 6, 7, 'steps', NULL, '1', NULL, NULL, NULL, {line(.001, .002, .001)})"]})
    o = duckdb.connect(osm)
    o.execute("INSERT INTO raw.nodes VALUES (5, 59.301, 18.0, CAST(MAP {'railway': 'subway_entrance'} AS MAP(VARCHAR, VARCHAR)))")
    o.close()
    con = urbanstyle.build(osm, str(tmp_path / "out.duckdb"))
    got = set(con.execute("SELECT node_id, level_a, level_b, type, assumed FROM space.link").fetchall())
    assert got == {(2, -1, 0, "ramp", False), (6, 0, 1, "stairs", False), (5, -1, 0, "entrance", True)}, got


def test_partition_has_no_overlap(tmp_path):
    """A crossroads: four roads meet at node 1. The street space is split into one intersection plus sections, with no overlap."""
    cx, cy = 18.0, 59.3
    dx, dy = 0.0009, 0.0005  # ~50 m each way
    arm = lambda i, x, y: f"({i}, {100 + i}, 1, {10 + i}, 'residential', 'Arm{i}', NULL, NULL, NULL, 2, ST_GeomFromText('LINESTRING({cx} {cy}, {cx + x} {cy + y})'))"
    osm = make_osm(tmp_path / "osm.duckdb", edges={"driving": [arm(1, dx, 0), arm(2, -dx, 0), arm(3, 0, dy), arm(4, 0, -dy)]})
    con = urbanstyle.build(osm, str(tmp_path / "out.duckdb"))
    kinds = dict(con.execute("SELECT kind, count(*) FROM space.container WHERE level = 0 GROUP BY kind").fetchall())
    assert kinds.get("intersection") == 1 and kinds.get("section", 0) >= 3, kinds
    total, union = con.execute("SELECT sum(ST_Area(geometry)), ST_Area(ST_Union_Agg(geometry)) FROM space.container WHERE level = 0").fetchone()
    assert abs(total - union) / union < 0.01, (total, union)  # areas add up: nothing is counted twice


def test_a_street_is_one_container(tmp_path):
    """Two one-way carriageways of the same name joined at both ends are one street; an unnamed footpath far away is a path space."""
    line = lambda y, a, b: f"ST_GeomFromText('LINESTRING({18 + a} {59.3 + y}, {18 + b} {59.3 + y})')"
    osm = make_osm(tmp_path / "osm.duckdb", edges={
        "driving": [f"(1, 200, 1, 2, 'primary', 'Boulevard', NULL, NULL, NULL, 2, {line(0.00007, 0, .001)})",
                    f"(2, 201, 2, 1, 'primary', 'Boulevard', NULL, NULL, NULL, 2, {line(-0.00007, .001, 0)})"],
        "walking": [f"(3, 300, 8, 9, 'footway', NULL, NULL, NULL, NULL, NULL, {line(0.01, 0, .001)})",
                    f"(4, 301, 9, 10, 'footway', NULL, NULL, NULL, NULL, NULL, {line(0.01, .001, .002)})"]})
    con = urbanstyle.build(osm, str(tmp_path / "out.duckdb"))
    got = con.execute("SELECT container_id, kind, n_road, n_walkway FROM space.container WHERE level = 0 ORDER BY 1").fetchall()
    assert got == [("p0-300", "path", 0, 2), ("s0-1", "section", 2, 0)], got


def test_kerb_travelway_and_asymmetry(tmp_path):
    """Sidewalks 5 m either side of a road: its travelway is measured out to the kerb (~8 m wide). A building 10 m away on
    the north side only: the north half-width is 10 m (the narrow side), the south side is open (capped)."""
    dy = lambda m: m / 111_320
    line = lambda y: f"ST_GeomFromText('LINESTRING(18.0 {59.3 + y}, 18.001 {59.3 + y})')"
    osm = make_osm(tmp_path / "osm.duckdb", [(1, {"building:levels": "3"}, (
        f"ST_GeomFromText('POLYGON((17.9995 {59.3 + dy(10)}, 18.0015 {59.3 + dy(10)}, 18.0015 {59.3 + dy(40)}, 17.9995 {59.3 + dy(40)}, 17.9995 {59.3 + dy(10)}))')"))],
        edges={"driving": [f"(1, 100, 1, 2, 'residential', 'Main St', NULL, NULL, NULL, 2, {line(0)})"],
               "walking": [f"(2, 200, 3, 4, 'footway', NULL, NULL, NULL, NULL, NULL, {line(dy(5))})",
                           f"(3, 201, 5, 6, 'footway', NULL, NULL, NULL, NULL, NULL, {line(-dy(5))})"]})
    con = urbanstyle.build(osm, str(tmp_path / "out.duckdb"))
    row = con.execute("SELECT kerb_share, narrow_half_m, wide_half_m, one_side_open_share FROM space.container WHERE container_id = 's0-1'").fetchone()
    assert row[0] >= 0.9 and 9 <= row[1] <= 11 and row[2] > 14 and row[3] >= 0.9, row
    tw = con.execute("""SELECT ST_Area(ST_Transform(geometry, 'EPSG:4326', 'EPSG:32634', always_xy := true)) FROM space.zone
                        WHERE container_id = 's0-1' AND zone = 'travelway'""").fetchone()[0]
    assert 6.5 * 56 <= tw <= 9.5 * 58, tw  # ~8 m x 57 m, not the 6.5 m lane width


def test_rail_and_stations(tmp_path):
    """A metro tunnel tagged layer U+2212 3 is shown at -2 (clamped) as a rail space with a track zone; a station with no
    level tag takes the level of the rail beside it, one with a level tag keeps it."""
    rail = "ST_GeomFromText('LINESTRING(18.0 59.31, 18.002 59.31)')"
    pt = lambda y: f"ST_GeomFromText('POINT(18.001 {y})')"
    osm = make_osm(tmp_path / "osm.duckdb",
                   rails=[(500, "subway", {"layer": "\u22123", "tunnel": "yes"}, rail, "[11, 12]")],
                   stations=[(1, "station", {}, pt(59.3102), "Beside the tunnel"), (2, "station", {"level": "-1"}, pt(59.35), "Tagged"),
                             (3, "station", {}, pt(59.36), "Nowhere")])
    con = urbanstyle.build(osm, str(tmp_path / "out.duckdb"))
    assert con.execute("SELECT level_min, type, class FROM space.element WHERE type = 'rail'").fetchall() == [(-2, "rail", "subway")]
    assert con.execute("SELECT container_id, kind, n_rail FROM space.container WHERE level = -2 AND kind = 'rail'").fetchall() == [("r-2-500", "rail", 1)]
    assert con.execute("SELECT zone FROM space.zone WHERE container_id = 'r-2-500'").fetchall() == [("track",)]
    got = dict(con.execute("SELECT name, level FROM space.station").fetchall())
    assert got == {"Beside the tunnel": -2, "Tagged": -1, "Nowhere": 0}, got


def test_entrance_tied_to_station(tmp_path):
    """A subway entrance named like a subway station 100 m away (level -2) links 0 <-> -2 and is not assumed; one with no
    station nearby stays an assumed link to -1; a subway entrance never picks a train station."""
    line = lambda x0, x1, y: f"ST_GeomFromText('LINESTRING({18 + x0} {59.3 + y}, {18 + x1} {59.3 + y})')"
    osm = make_osm(tmp_path / "osm.duckdb",
                   stations=[(1, "station", {"station": "subway", "level": "-2"}, "ST_GeomFromText('POINT(18.0015 59.3)')", "Central"),
                             (2, "station", {}, "ST_GeomFromText('POINT(18.0 59.301)')", "Rail")],
                   edges={"walking": [f"(1, 100, 5, 6, 'footway', NULL, NULL, NULL, NULL, NULL, {line(0, .001, 0)})",
                                      f"(2, 101, 7, 8, 'footway', NULL, NULL, NULL, NULL, NULL, {line(0, .001, .01)})"]})
    o = duckdb.connect(osm)
    tags = lambda name: f"CAST(MAP {{'railway': 'subway_entrance', 'name': '{name}'}} AS MAP(VARCHAR, VARCHAR))"
    o.execute(f"INSERT INTO raw.nodes VALUES (5, 59.3, 18.0, {tags('Central')}), (7, 59.31, 18.0, {tags('Elsewhere')})")
    o.close()
    con = urbanstyle.build(osm, str(tmp_path / "out.duckdb"))
    got = set(con.execute("SELECT node_id, level_a, level_b, assumed, station_id, match FROM space.link WHERE type = 'entrance'").fetchall())
    assert got == {(5, -2, 0, False, "n1", "name"), (7, -1, 0, True, None, None)}, got


def test_intersection_id_is_the_junction_node(tmp_path):
    """The crossroads' intersection takes its id from the junction's OSM node (node 1), so it survives a rebuild."""
    cx, cy, dx, dy = 18.0, 59.3, 0.0009, 0.0005
    arm = lambda i, x, y: f"({i}, {100 + i}, 1, {10 + i}, 'residential', 'Arm{i}', NULL, NULL, NULL, 2, ST_GeomFromText('LINESTRING({cx} {cy}, {cx + x} {cy + y})'))"
    osm = make_osm(tmp_path / "osm.duckdb", edges={"driving": [arm(1, dx, 0), arm(2, -dx, 0), arm(3, 0, dy), arm(4, 0, -dy)]})
    con = urbanstyle.build(osm, str(tmp_path / "out.duckdb"))
    assert con.execute("SELECT container_id FROM space.container WHERE kind = 'intersection'").fetchall() == [("i0-1",)]


def test_objects(tmp_path):
    """Classification order, level, container and zone of point objects; an object outside every container; an ignored node."""
    dy = lambda m: m / 111_320
    road = "ST_GeomFromText('LINESTRING(18.0 59.3, 18.001 59.3)')"
    osm = make_osm(tmp_path / "osm.duckdb", edges={"driving": [f"(1, 100, 1, 2, 'residential', 'Main St', NULL, NULL, NULL, 2, {road})"]})
    o = duckdb.connect(osm)
    node = lambda i, dy_m, tags: (f"({i}, {59.3 + dy(dy_m)}, 18.0005, CAST(MAP {{" + ", ".join(f"'{k}': '{v}'" for k, v in tags.items())
                                  + "} AS MAP(VARCHAR, VARCHAR)))")
    o.execute("INSERT INTO raw.nodes VALUES " + ", ".join([
        node(1, 6, {"amenity": "bench"}),                                               # beside the road: pedestrian realm
        node(2, 0, {"highway": "crossing", "crossing": "zebra"}),                       # on the road: travelway
        node(3, 0.5, {"highway": "crossing", "crossing": "traffic_signals"}),           # signalised wins over the other crossing rules
        node(4, 40, {"highway": "street_lamp"}),                                        # beyond the street space, ~20 m from it
        node(5, 6, {"natural": "tree", "layer": "\u22121"}),                           # layer -1: no container at that level here
        node(6, 6, {"amenity": "cafe"}),                                                # no taxonomy rule: ignored
        node(7, 6, {"amenity": "waste_basket", "material": "metal", "colour": "green", "fixme": "x"})]))
    o.close()
    con = urbanstyle.build(osm, str(tmp_path / "out.duckdb"))
    got = {r[0]: r[1:] for r in con.execute("SELECT object_id, class, level, container_id, zone, near_m IS NULL FROM space.object ORDER BY 1").fetchall()}
    assert got["n1"] == ("furniture.bench", 0, "s0-1", "pedestrian_realm", True), got["n1"]
    assert got["n2"][:4] == ("crossing.zebra", 0, "s0-1", "travelway"), got["n2"]
    assert got["n3"][0] == "crossing.signalised", got["n3"]
    assert got["n4"][0] == "furniture.lamp" and got["n4"][2] is None and got["n4"][4] is False, got["n4"]
    assert got["n5"][:3] == ("vegetation.tree", -1, None), got["n5"]
    assert "n6" not in got
    attrs = con.execute("SELECT attrs FROM space.object WHERE object_id = 'n7'").fetchone()[0]
    assert "material" in attrs and "colour" in attrs and "fixme" not in attrs, attrs


def test_a_path_that_only_passes_close_is_not_part_of_the_street(tmp_path):
    """A long footway that crosses the road's 15 m buffer for only a short stretch stays a path space; a parallel one joins the street."""
    dy = lambda m: m / 111_320
    road = "ST_GeomFromText('LINESTRING(18.0 59.3, 18.001 59.3)')"
    parallel = f"ST_GeomFromText('LINESTRING(18.0 {59.3 + dy(5)}, 18.001 {59.3 + dy(5)})')"
    leaving = f"ST_GeomFromText('LINESTRING(18.0005 {59.3 + dy(5)}, 18.0005 {59.3 + dy(200)})')"
    osm = make_osm(tmp_path / "osm.duckdb", edges={
        "driving": [f"(1, 100, 1, 2, 'residential', 'Main St', NULL, NULL, NULL, 2, {road})"],
        "walking": [f"(2, 200, 3, 4, 'footway', NULL, NULL, NULL, NULL, NULL, {parallel})",
                    f"(3, 300, 5, 6, 'footway', NULL, NULL, NULL, NULL, NULL, {leaving})"]})
    con = urbanstyle.build(osm, str(tmp_path / "out.duckdb"))
    got = dict(con.execute("SELECT source_id, container_id FROM space.element WHERE type = 'walkway'").fetchall())
    assert got == {"2": "s0-1", "3": "p0-300"}, got


def test_arms_and_merged_intersections(tmp_path):
    """The crossroads has one intersection with 4 arms (one per street). A dog-leg (two T-junctions 10 m apart) is ONE intersection."""
    cx, cy, dx, dy = 18.0, 59.3, 0.0009, 0.0005
    arm = lambda i, x, y: f"({i}, {100 + i}, 1, {10 + i}, 'residential', 'Arm{i}', NULL, NULL, NULL, 2, ST_GeomFromText('LINESTRING({cx} {cy}, {cx + x} {cy + y})'))"
    osm = make_osm(tmp_path / "osm.duckdb", edges={"driving": [arm(1, dx, 0), arm(2, -dx, 0), arm(3, 0, dy), arm(4, 0, -dy)]})
    con = urbanstyle.build(osm, str(tmp_path / "out.duckdb"))
    assert con.execute("SELECT intersection_id, count(*) FROM space.arm GROUP BY 1").fetchall() == [("i0-1", 4)]
    assert con.execute("SELECT name, n_section, n_intersection FROM space.street ORDER BY name").fetchall() == [(f"Arm{i}", 1, 1) for i in (1, 2, 3, 4)]
    assert con.execute("SELECT count(DISTINCT street_id), count(DISTINCT section_id) FROM space.arm").fetchone() == (4, 4)   # one intersection, four streets
    # dog-leg: main street through nodes 1 and 2 (10 m apart), a side street north of node 1 and one south of node 2
    x1, x2, m = 18.0, 18.0 + 10 / 56_800, 18.0003
    ed = lambda i, way, a, b, name, x0, y0, x9, y9: (f"({i}, {way}, {a}, {b}, 'residential', '{name}', NULL, NULL, NULL, 2, "
                                                      f"ST_GeomFromText('LINESTRING({x0} {y0}, {x9} {y9})'))")
    osm2 = make_osm(tmp_path / "osm2.duckdb", edges={"driving": [
        ed(1, 301, 10, 1, "Main", x1 - 0.0008, 59.3, x1, 59.3), ed(2, 302, 1, 2, "Main", x1, 59.3, x2, 59.3),
        ed(3, 303, 2, 11, "Main", x2, 59.3, x2 + 0.0008, 59.3),
        ed(4, 304, 1, 20, "North", x1, 59.3, x1, 59.3 + 0.0005), ed(5, 305, 2, 21, "South", x2, 59.3, x2, 59.3 - 0.0005)]})
    con2 = urbanstyle.build(osm2, str(tmp_path / "out2.duckdb"))
    assert con2.execute("SELECT container_id FROM space.container WHERE kind = 'intersection'").fetchall() == [("i0-1",)]
    assert con2.execute("SELECT count(DISTINCT street_id) FROM space.arm").fetchone()[0] >= 3


def test_a_disconnected_region_becomes_separate_containers(tmp_path):
    """A footpath runs along a road but a row of buildings lies between them, so their street spaces are not connected: the section
    is split into two containers, each one polygon, the footpath in the second, both in the same street."""
    dy = lambda m: m / 111_320
    road = "ST_GeomFromText('LINESTRING(18.0 59.3, 18.001 59.3)')"
    path = f"ST_GeomFromText('LINESTRING(18.0 {59.3 + dy(10)}, 18.001 {59.3 + dy(10)})')"
    wall = (f"ST_GeomFromText('POLYGON((17.9995 {59.3 + dy(4)}, 18.0015 {59.3 + dy(4)}, 18.0015 {59.3 + dy(8)}, "
            f"17.9995 {59.3 + dy(8)}, 17.9995 {59.3 + dy(4)}))')")
    osm = make_osm(tmp_path / "osm.duckdb", [(1, {"building:levels": "3"}, wall)],
                   edges={"driving": [f"(1, 100, 1, 2, 'residential', 'Main St', NULL, NULL, NULL, 2, {road})"],
                          "walking": [f"(2, 200, 3, 4, 'footway', NULL, NULL, NULL, NULL, NULL, {path})"]})
    con = urbanstyle.build(osm, str(tmp_path / "out.duckdb"))
    got = con.execute("SELECT container_id, kind, street_id, ST_NumGeometries(geometry) FROM space.container WHERE level = 0 ORDER BY 1").fetchall()
    assert [(g[0], g[1]) for g in got] == [("p0-1.1", "path"), ("s0-1", "section")] and all(g[3] == 1 for g in got), got   # the part with no road is a path space
    assert dict(con.execute("SELECT source_id, container_id FROM space.element WHERE type <> 'building'").fetchall()) == {"1": "s0-1", "2": "p0-1.1"}


def star(tmp_path, name, bearings, length_m=60):
    """A junction: roads of `length_m` leaving the centre at the given compass bearings (node 1 is the centre)."""
    import math
    cx, cy = 18.0, 59.3
    kx, ky = 111_320 * math.cos(math.radians(cy)), 111_320
    edges = [f"({i}, {100 + i}, 1, {10 + i}, 'residential', 'Arm{i}', NULL, NULL, NULL, 2, ST_GeomFromText("
             f"'LINESTRING({cx} {cy}, {cx + length_m * math.sin(math.radians(b)) / kx} {cy + length_m * math.cos(math.radians(b)) / ky})'))"
             for i, b in enumerate(bearings, 1)]
    return urbanstyle.build(make_osm(tmp_path / f"{name}.duckdb", edges={"driving": edges}), str(tmp_path / f"{name}.out.duckdb"))


def test_junction_shapes(tmp_path):
    shapes = {}
    for name, bearings in {"T": [0, 90, 180], "Y": [0, 120, 240], "cross": [0, 90, 180, 270], "multi": [0, 72, 144, 216, 288]}.items():
        con = star(tmp_path, name, bearings)
        shapes[name] = con.execute("SELECT shape, n_arms FROM space.container WHERE kind = 'intersection'").fetchall()
    assert shapes == {"T": [("T", 3)], "Y": [("Y", 3)], "cross": [("cross", 4)], "multi": [("multi", 5)]}, shapes


def test_arm_cuts_are_perpendicular(tmp_path):
    """Where each arriving road crosses the boundary of the intersection, the boundary is within 10 degrees of perpendicular."""
    import math
    import shapely
    con = star(tmp_path, "perp", [0, 90, 180, 270])
    metric = "ST_AsWKB(ST_Transform(geometry, 'EPSG:4326', 'EPSG:32634', always_xy := true))"
    poly = shapely.from_wkb(bytes(con.execute(f"SELECT {metric} FROM space.container WHERE kind = 'intersection'").fetchone()[0]))
    roads = [shapely.from_wkb(bytes(r[0])) for r in con.execute(f"SELECT {metric} FROM space.element WHERE type = 'road'").fetchall()]
    ring = list(poly.exterior.coords)
    for road in roads:
        p = road.intersection(poly.exterior)
        p = p if p.geom_type == "Point" else p.geoms[0]
        seg = min(zip(ring[:-1], ring[1:]), key=lambda s: shapely.LineString(s).distance(p))
        sx, sy = seg[1][0] - seg[0][0], seg[1][1] - seg[0][1]
        (x0, y0), (x1, y1) = road.coords[0], road.coords[-1]
        ang = abs(math.degrees(math.atan2(sx, sy) - math.atan2(x1 - x0, y1 - y0))) % 180
        assert abs(ang - 90) <= 10, ang


def test_roundabout_is_one_intersection_with_its_island(tmp_path):
    import math
    cx, cy = 18.0, 59.3
    kx, ky = 111_320 * math.cos(math.radians(cy)), 111_320
    at = lambda r, b: (cx + r * math.sin(math.radians(b)) / kx, cy + r * math.cos(math.radians(b)) / ky)
    ring = [(f"({i}, 400, {i}, {i % 6 + 1}, 'residential', 'Ring', NULL, NULL, NULL, 1, ST_GeomFromText('LINESTRING({at(25, 60 * i)[0]} {at(25, 60 * i)[1]}, "
              f"{at(25, 60 * (i % 6 + 1))[0]} {at(25, 60 * (i % 6 + 1))[1]})'))") for i in range(1, 7)]
    spokes = [(f"({10 + i}, {410 + i}, {i}, {20 + i}, 'residential', 'Spoke{i}', NULL, NULL, NULL, 2, ST_GeomFromText('LINESTRING({at(25, 60 * i)[0]} "
               f"{at(25, 60 * i)[1]}, {at(70, 60 * i)[0]} {at(70, 60 * i)[1]})'))") for i in range(1, 7)]
    osm = make_osm(tmp_path / "osm.duckdb", edges={"driving": ring + spokes})
    o = duckdb.connect(osm)
    o.execute("INSERT INTO raw.ways VALUES (400, CAST(MAP {'junction': 'roundabout'} AS MAP(VARCHAR, VARCHAR)), [1, 2, 3, 4, 5, 6, 1])")
    o.close()
    con = urbanstyle.build(osm, str(tmp_path / "out.duckdb"))
    assert con.execute("SELECT shape FROM space.container WHERE kind = 'intersection'").fetchall() == [("roundabout",)]   # 25 m apart, merged by the tag
    assert con.execute(f"SELECT ST_Contains(geometry, ST_Point({cx}, {cy})) FROM space.container WHERE kind = 'intersection'").fetchone()[0]   # the island


def test_dead_ends_and_ends_at_intersections(tmp_path):
    con = star(tmp_path, "ends", [0, 90, 180, 270])
    assert con.execute("SELECT n_dead_ends, n_intersections FROM space.container WHERE kind = 'section'").fetchall() == [(1, 1)] * 4
    con2 = urbanstyle.build(make_osm(tmp_path / "iso.duckdb", edges={"driving": [f"(1, 100, 1, 2, 'residential', 'Lone', NULL, NULL, NULL, 2, {ROAD})"]}),
                            str(tmp_path / "iso.out.duckdb"))
    assert con2.execute("SELECT n_dead_ends, n_intersections FROM space.container WHERE kind = 'section'").fetchall() == [(2, 0)]


def test_a_dual_carriageway_is_one_section(tmp_path):
    """Two one-way carriageways of 'Boulevard', 12 m apart, meet only at the junctions at both ends. They are ONE section."""
    ky = 111_320
    x0, x1 = 18.0, 18.0 + 80 / (111_320 * 0.5084)      # 80 m long at this latitude
    n, s = 59.3 + 6 / ky, 59.3 - 6 / ky                 # the two carriageways, 12 m apart
    far = lambda m: m / ky
    ed = lambda i, way, a, b, name, xa, ya, xb, yb: (f"({i}, {way}, {a}, {b}, 'residential', '{name}', NULL, NULL, NULL, 1, "
                                                       f"ST_GeomFromText('LINESTRING({xa} {ya}, {xb} {yb})'))")
    edges = [ed(1, 301, 1, 2, "Boulevard", x0, n, x1, n), ed(2, 302, 4, 3, "Boulevard", x1, s, x0, s),
             ed(3, 311, 1, 3, "Cross", x0, n, x0, s), ed(4, 312, 1, 11, "Cross", x0, n, x0, n + far(34)), ed(5, 313, 3, 13, "Cross", x0, s, x0, s - far(34)),
             ed(6, 321, 2, 4, "Other", x1, n, x1, s), ed(7, 322, 2, 12, "Other", x1, n, x1, n + far(34)), ed(8, 323, 4, 14, "Other", x1, s, x1, s - far(34))]
    osm = make_osm(tmp_path / "osm.duckdb", edges={"driving": edges})
    o = duckdb.connect(osm)
    o.execute("UPDATE driving.edges SET oneway = true WHERE osm_id IN (301, 302)")   # one east, one west
    o.close()
    con = urbanstyle.build(osm, str(tmp_path / "out.duckdb"))
    assert con.execute("SELECT n_road, n_intersections FROM space.container WHERE kind = 'section' AND name = 'Boulevard'").fetchall() == [(2, 2)]
    con.close()
    # the same two roads with different names, or two-way, are not a dual carriageway
    for tag, sql in (("names", "UPDATE driving.edges SET name = 'Other Boulevard' WHERE osm_id = 302"), ("twoway", "UPDATE driving.edges SET oneway = false")):
        o = duckdb.connect(osm)
        o.execute(sql)
        o.close()
        con = urbanstyle.build(osm, str(tmp_path / f"{tag}.duckdb"))
        assert con.execute("SELECT count(*) FROM space.container WHERE kind = 'section' AND name LIKE '%Boulevard'").fetchone()[0] == 2, tag
        con.close()


def test_a_side_street_on_one_half_cuts_both_halves(tmp_path):
    """A dual carriageway with a side street meeting only the north half: both halves are cut at that point, so there are two sections,
    each holding one piece of each half, and the side street's junction is one intersection across the median."""
    ky = 111_320
    kx = ky * 0.5084
    x0, xm, x1 = 18.0, 18.0 + 40 / kx, 18.0 + 80 / kx
    n, s = 59.3 + 6 / ky, 59.3 - 6 / ky
    far = lambda m: m / ky
    ed = lambda i, way, a, b, name, xa, ya, xb, yb: (f"({i}, {way}, {a}, {b}, 'residential', '{name}', NULL, NULL, NULL, 1, "
                                                       f"ST_GeomFromText('LINESTRING({xa} {ya}, {xb} {yb})'))")
    edges = [ed(1, 301, 1, 2, "Boulevard", x0, n, xm, n), ed(2, 302, 2, 3, "Boulevard", xm, n, x1, n),            # north half, eastbound
             ed(3, 303, 4, 5, "Boulevard", x1, s, xm, s), ed(4, 304, 5, 6, "Boulevard", xm, s, x0, s),            # south half, westbound
             ed(5, 311, 1, 6, "CrossW", x0, n, x0, s), ed(6, 312, 1, 11, "CrossW", x0, n, x0, n + far(34)), ed(7, 313, 6, 16, "CrossW", x0, s, x0, s - far(34)),
             ed(8, 321, 3, 4, "CrossE", x1, n, x1, s), ed(9, 322, 3, 13, "CrossE", x1, n, x1, n + far(34)), ed(10, 323, 4, 14, "CrossE", x1, s, x1, s - far(34)),
             ed(11, 331, 2, 20, "Side", xm, n, xm, n + far(34))]                                                  # meets the north half only
    osm = make_osm(tmp_path / "osm.duckdb", edges={"driving": edges})
    o = duckdb.connect(osm)
    o.execute("UPDATE driving.edges SET oneway = true WHERE osm_id IN (301, 302, 303, 304)")
    o.close()
    con = urbanstyle.build(osm, str(tmp_path / "out.duckdb"))
    assert sorted(con.execute("SELECT n_road, n_intersections FROM space.container WHERE kind = 'section' AND name = 'Boulevard'").fetchall()) == [(2, 2), (2, 2)]


def test_a_container_records_the_buildings_that_bound_it(tmp_path):
    """The road between a building 10 m north and one 6 m south: both are in its boundary, with about the length of the road."""
    dy = lambda m: m / 111_320
    box = lambda y0, y1: (f"ST_GeomFromText('POLYGON((17.9995 {59.3 + y0}, 18.0015 {59.3 + y0}, 18.0015 {59.3 + y1}, "
                          f"17.9995 {59.3 + y1}, 17.9995 {59.3 + y0}))')")
    osm = make_osm(tmp_path / "osm.duckdb", [(1, {"building:levels": "3"}, box(dy(10), dy(40))), (2, {"building:levels": "3"}, box(-dy(40), -dy(6)))],
                   edges={"driving": [f"(1, 100, 1, 2, 'residential', 'Main St', NULL, NULL, NULL, 2, {ROAD})"]})
    con = urbanstyle.build(osm, str(tmp_path / "out.duckdb"))
    got = con.execute("SELECT building_id, length_m FROM space.boundary WHERE container_id = 's0-1' ORDER BY 1").fetchall()
    assert [g[0] for g in got] == ["w1", "w2"] and all(30 <= g[1] <= 70 for g in got), got
    assert con.execute("SELECT n_buildings FROM space.container WHERE container_id = 's0-1'").fetchone()[0] == 2


def test_a_wide_open_space_framed_by_buildings_is_a_plaza(tmp_path):
    """Buildings 16 m either side of a 2-lane road leave a 32 m wide space: the road keeps its ribbon, the rest on each side is a plaza.
    A street with buildings 8 m either side has no plaza."""
    dy = lambda m: m / 111_320
    box = lambda y0, y1: (f"ST_GeomFromText('POLYGON((17.9995 {59.3 + y0}, 18.0015 {59.3 + y0}, 18.0015 {59.3 + y1}, "
                          f"17.9995 {59.3 + y1}, 17.9995 {59.3 + y0}))')")
    def build(gap, name):
        osm = make_osm(tmp_path / f"{name}.duckdb", [(1, {"building:levels": "3"}, box(dy(gap), dy(gap + 30))), (2, {"building:levels": "3"}, box(-dy(gap + 30), -dy(gap)))],
                       edges={"driving": [f"(1, 100, 1, 2, 'residential', 'Main St', NULL, NULL, NULL, 2, {ROAD})"]})
        return urbanstyle.build(osm, str(tmp_path / f"{name}-out.duckdb"))
    wide = build(16, "wide")
    plazas = wide.execute("SELECT container_id, ST_IsValid(geometry), ST_NumGeometries(geometry) FROM space.container WHERE kind = 'plaza'").fetchall()
    assert plazas and all(p[1] and p[2] == 1 for p in plazas), plazas
    assert wide.execute("SELECT count(*) FROM space.container WHERE container_id = 's0-1'").fetchone()[0] == 1
    assert build(8, "narrow").execute("SELECT count(*) FROM space.container WHERE kind = 'plaza'").fetchone()[0] == 0


def test_strips_fill_the_zones_completely(tmp_path):
    """The strips of a section add up to its travelway and pedestrian realm: no gap, no overlap; a 2-lane road gets two lane strips."""
    import shapely
    dy = lambda m: m / 111_320
    box = lambda y0, y1: (f"ST_GeomFromText('POLYGON((17.9995 {59.3 + y0}, 18.0015 {59.3 + y0}, 18.0015 {59.3 + y1}, "
                          f"17.9995 {59.3 + y1}, 17.9995 {59.3 + y0}))')")
    osm = make_osm(tmp_path / "osm.duckdb", [(1, {"building:levels": "3"}, box(dy(10), dy(40))), (2, {"building:levels": "3"}, box(-dy(40), -dy(10)))],
                   edges={"driving": [f"(1, 100, 1, 2, 'residential', 'Main St', NULL, NULL, NULL, 2, {ROAD})"]})
    con = urbanstyle.build(osm, str(tmp_path / "out.duckdb"))
    m = "ST_AsWKB(ST_Transform(geometry, 'EPSG:4326', 'EPSG:32634', always_xy := true))"
    zones = sum(shapely.from_wkb(bytes(r[0])).area for r in con.execute(f"SELECT {m} FROM space.zone WHERE container_id = 's0-1'").fetchall())
    strips = [(r[0], shapely.from_wkb(bytes(r[1]))) for r in con.execute(f"SELECT type, {m} FROM space.strip WHERE container_id = 's0-1'").fetchall()]
    assert abs(sum(s[1].area for s in strips) - zones) < 0.02 * zones, (zones, sum(s[1].area for s in strips))
    assert shapely.union_all([shapely.make_valid(s[1]).buffer(0.01) for s in strips]).area > 0.98 * zones
    assert sum(1 for s in strips if s[0] == "travel") >= 2, [s[0] for s in strips]
    assert {s[0] for s in strips} <= {"travel", "cycle", "frontage", "furnishing", "open", "sidewalk"}
