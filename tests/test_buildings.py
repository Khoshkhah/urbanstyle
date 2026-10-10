import duckdb

from urbanstyle import buildings


def test_building_use():
    # what a point inside a building stands for
    assert buildings.poi_use({"amenity": "cafe"}) == "food & drink"
    assert buildings.poi_use({"shop": "hairdresser"}) == "services"
    assert buildings.poi_use({"shop": "clothes"}) == "retail"
    assert buildings.poi_use({"amenity": "bench"}) is None
    # apartments with a café on the ground floor are mixed; an untagged building of shops is commercial; offices upstairs leave it
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial; ATTACH ':memory:' AS osm; CREATE SCHEMA osm.features; CREATE SCHEMA space")
    sq = lambda x: f"ST_GeomFromText('POLYGON(({x} 0, {x + 0.0002} 0, {x + 0.0002} 0.0002, {x} 0.0002, {x} 0))')"
    con.execute(f"""CREATE TABLE space.element AS SELECT * FROM (VALUES ('w1', 'building', {sq(0)}), ('w2', 'building', {sq(0.001)}),
                    ('w3', 'building', {sq(0.002)})) t(source_id, type, geometry)""")
    con.execute(f"""CREATE TABLE osm.features.buildings AS SELECT * FROM (VALUES ('way', 1, MAP {{'building': 'apartments'}}),
                    ('way', 2, MAP {{'building': 'yes'}}), ('way', 3, MAP {{'building': 'apartments'}})) t(osm_type, osm_id, tags)""")
    con.execute("""CREATE TABLE osm.features.pois AS SELECT tags, ST_Point(x, 0.0001) AS geom FROM (VALUES
                   (MAP {'amenity': 'cafe'}, 0.0001), (MAP {'shop': 'clothes'}, 0.0011), (MAP {'office': 'lawyer', 'level': '2'}, 0.0021)) t(tags, x)""")
    buildings.build(con, "EPSG:32631")
    got = con.execute('SELECT source_id, "use", ground_use FROM space.element ORDER BY 1').fetchall()
    assert got == [("w1", "mixed", "food & drink"), ("w2", "commercial", "retail"), ("w3", "residential", "residential")]
