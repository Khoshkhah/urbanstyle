import datetime

import duckdb

from urbanstyle.unit import match


def test_one_lamp_from_three_sources_and_two_lamps_apart():
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial")
    con.execute("CREATE TABLE object (object_id VARCHAR, class VARCHAR, source VARCHAR, height_m DOUBLE, confidence DECIMAL(2,1), geometry GEOMETRY)")
    rows = [("pole-1", "furniture.lamp", "vancouver", 7.6, 0.9, 0, 0),      # the city's surveyed pole
            ("mly-old", "furniture.lamp", "mapillary", 7.6, 0.5, 7, 0),     # seen until 2021 ...
            ("mly-new", "furniture.lamp", "mapillary", 7.6, 0.5, 11, 0),    # ... and from 2021: the same lamp, 11 m from the pole
            ("mly-b", "furniture.lamp", "mapillary", 7.6, 0.5, 30, 0),      # another lamp, 30 m on
            ("sig", "furniture.signal", "osm", 3.3, 0.7, 1, 0)]             # a signal beside the pole: another class
    for oid, cls, src, h, c, x, y in rows:
        con.execute("INSERT INTO object VALUES (?, ?, ?, ?, ?, ST_Point(?, ?))", [oid, cls, src, h, c, x, y])
    d = datetime.datetime
    seen = {"mly-old": (d(2015, 9, 10), d(2021, 1, 22)), "mly-new": (d(2021, 1, 22), d(2024, 9, 28)), "mly-b": (d(2016, 1, 1), d(2024, 1, 1))}
    match(con, seen)
    got = {mid: set(refs.split(", ")) for mid, refs in con.execute("SELECT match_id, refs FROM match").fetchall()}
    assert sorted(map(sorted, got.values())) == [["mly-b"], ["mly-new", "mly-old", "pole-1"], ["sig"]]
    # the matched lamp stands where the city's survey puts it
    assert con.execute("SELECT ST_X(geometry), sources FROM match WHERE refs LIKE '%pole-1%'").fetchone() == (0.0, "vancouver, mapillary")
