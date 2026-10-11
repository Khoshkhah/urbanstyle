import urbanstyle
from test_levels import make_osm

LON, LAT = (18.0, 18.002), (59.3, 59.301)      # a square of streets, about 114 x 111 m between their lines; short ends beyond


def test_a_block_is_parallel_to_its_streets_and_holds_its_buildings(tmp_path):
    """Four residential streets around one block: no parcels, no sidewalks, so each side stands half the class's right-of-way (10 m)
    from its street, except the south side, pulled in to a building 5 m from the street."""
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
    blocks = con.execute("SELECT block_id, area_m2 FROM space.block").fetchall()
    assert [b for b, _ in blocks] == ["b0-w100l"]           # the smallest way bounding it, and its side
    w = 0.002 * 111320 * 0.5105 - 2 * 10                    # between the west and east streets, less 10 m each side
    h = 0.001 * 111320 - 10 - 5                             # between the south and north streets, less 10 m and 5 m
    assert abs(blocks[0][1] - w * h) < 0.03 * w * h
    assert con.execute("""SELECT bool_and(ST_Within(ST_Buffer(e.geometry, -0.0000001), b.geometry)) FROM space.element e, space.block b
                          WHERE e.type = 'building'""").fetchone()[0]
    sides = dict(con.execute("SELECT way_id, basis FROM space.block_side").fetchall())
    assert sides == {100: "building", 200: "class", 300: "class", 400: "class"}
