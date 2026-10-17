import urbanstyle
from test_levels import make_osm

LON, LAT = (18.0, 18.002), (59.3, 59.301)      # a square of streets, about 114 x 111 m between their lines; short ends beyond


def test_a_block_is_parallel_to_its_streets_and_holds_its_buildings(tmp_path):
    """Four residential streets around one block: no parcels, no sidewalks, so each side stands 1.5 m behind its carriageway (two
    lanes of 3.25 m: 4.75 m from its line; docs/design/blocks.md); the building 5 m from the south street is behind that edge, so it
    pulls nothing."""
    xy = {1: (LON[0], LAT[0]), 2: (LON[1], LAT[0]), 3: (LON[1], LAT[1]), 4: (LON[0], LAT[1]),
          11: (LON[0] - 0.0001, LAT[0]), 12: (LON[1] + 0.0001, LAT[0]), 13: (LON[1] + 0.0001, LAT[1]), 14: (LON[0] - 0.0001, LAT[1]),
          15: (LON[0], LAT[0] - 0.0001), 16: (LON[1], LAT[0] - 0.0001), 17: (LON[1], LAT[1] + 0.0001), 18: (LON[0], LAT[1] + 0.0001)}
    pieces = [(11, 1, 100), (1, 2, 100), (2, 12, 100), (14, 4, 200), (4, 3, 200), (3, 13, 200),
              (15, 1, 300), (1, 4, 300), (4, 18, 300), (16, 2, 400), (2, 3, 400), (3, 17, 400)]
    line = lambda a, b: f"ST_GeomFromText('LINESTRING({xy[a][0]} {xy[a][1]}, {xy[b][0]} {xy[b][1]})')"
    edges = [f"({i}, {way}, {a}, {b}, 'residential', 'St {way}', NULL, NULL, NULL, NULL, {line(a, b)})" for i, (a, b, way) in enumerate(pieces, 1)]
    south = 59.3 + 5 / 111320                      # the building's face 5 m north of the south street
    bld = f"ST_GeomFromText('POLYGON((18.0008 {south}, 18.0012 {south}, 18.0012 59.3003, 18.0008 59.3003, 18.0008 {south}))')"
    osm = make_osm(tmp_path / "osm.duckdb", [(1, {"building": "yes"}, bld)], edges={"driving": edges})
    con = urbanstyle.build(osm, str(tmp_path / "out.duckdb"))
    blocks = dict(con.execute("SELECT block_id, area_m2 FROM work.block").fetchall())
    assert "b0-w100l" in blocks                              # the smallest way bounding it, and its side
    e = 2 * 3.25 / 2 + 1.5
    w = 0.002 * 111320 * 0.5105 - 2 * e                     # between the west and east streets, less 4.75 m each side
    h = 0.001 * 111320 - 2 * e                              # between the south and north streets
    assert abs(blocks["b0-w100l"] - w * h) < 0.03 * w * h
    assert con.execute("""SELECT bool_and(ST_Within(ST_Buffer(e.geometry, -0.0000001), b.geometry)) FROM work.element e, work.block b
                          WHERE e.type = 'building' AND b.block_id = 'b0-w100l'""").fetchone()[0]
    sides = dict(con.execute("SELECT way_id, basis FROM work.block_side WHERE block_id = 'b0-w100l'").fetchall())
    assert sides == {100: "carriageway", 200: "carriageway", 300: "carriageway", 400: "carriageway"}


def test_a_named_footway_cuts_the_block_and_has_a_corridor(tmp_path):
    """The same block with a named footway from the south street to the north street through its middle (docs/design/paths.md, rank
    1): two blocks, one corridor 3 m wide (PATH_W, OSM gives no width) from one carriageway's edge to the other's, and the ground
    kind path on it, less the sidewalk's width at each mouth (network FURNISH_M + CLEAR_M)."""
    from urbanstyle import blocks, network
    mid = (LON[0] + LON[1]) / 2
    xy = {1: (LON[0], LAT[0]), 2: (LON[1], LAT[0]), 3: (LON[1], LAT[1]), 4: (LON[0], LAT[1]),
          11: (LON[0] - 0.0001, LAT[0]), 12: (LON[1] + 0.0001, LAT[0]), 13: (LON[1] + 0.0001, LAT[1]), 14: (LON[0] - 0.0001, LAT[1]),
          15: (LON[0], LAT[0] - 0.0001), 16: (LON[1], LAT[0] - 0.0001), 17: (LON[1], LAT[1] + 0.0001), 18: (LON[0], LAT[1] + 0.0001),
          21: (mid, LAT[0]), 22: (mid, LAT[1])}
    pieces = [(11, 1, 100), (1, 2, 100), (2, 12, 100), (14, 4, 200), (4, 3, 200), (3, 13, 200),
              (15, 1, 300), (1, 4, 300), (4, 18, 300), (16, 2, 400), (2, 3, 400), (3, 17, 400)]
    line = lambda a, b: f"ST_GeomFromText('LINESTRING({xy[a][0]} {xy[a][1]}, {xy[b][0]} {xy[b][1]})')"
    edges = [f"({i}, {way}, {a}, {b}, 'residential', 'St {way}', NULL, NULL, NULL, NULL, {line(a, b)})" for i, (a, b, way) in enumerate(pieces, 1)]
    walk = [f"(13, 500, 21, 22, 'footway', 'Passage Test', NULL, NULL, NULL, NULL, {line(21, 22)})"]
    osm = make_osm(tmp_path / "osm.duckdb", edges={"driving": edges, "walking": walk})
    con = urbanstyle.build(osm, str(tmp_path / "out.duckdb"))
    halves = con.execute("SELECT block_id, area_m2 FROM work.block WHERE area_m2 > 1000 ORDER BY 1").fetchall()      # (the strips
    assert [b for b, _ in halves] == ["b0-w100l", "b0-w100l.2"]                                                      # beyond the ring not)
    assert abs(halves[0][1] - halves[1][1]) < 0.02 * halves[0][1]
    cors = con.execute("""SELECT corridor_id, width_m, width_source, ST_Area(ST_Transform(geometry, 'EPSG:4326', 'EPSG:32634', always_xy := true))
                          FROM work.corridor""").fetchall()
    assert len(cors) == 1 and cors[0][:3] == ("c0-w500", blocks.PATH_W["footway"], "urbanstyle")
    h = 0.001 * 111320 - 2 * 3.25                           # between the two carriageways' edges (two lanes of 3.25 m each street)
    assert abs(cors[0][3] - 3.0 * h) < 0.05 * 3.0 * h
    path = con.execute("""SELECT sum(ST_Area(ST_Transform(geometry, 'EPSG:4326', 'EPSG:32634', always_xy := true)))
                          FROM work.ground WHERE type = 'path'""").fetchone()[0]
    mouth = network.FURNISH_M + network.CLEAR_M
    assert abs(path - 3.0 * (h - 2 * mouth)) < 0.05 * path
    assert con.execute("SELECT count(*) FROM work.unit WHERE level = 0 AND ST_GeometryType(geometry) <> 'POLYGON'").fetchone()[0] == 0
