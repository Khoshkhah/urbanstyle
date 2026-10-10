"""Layer 0 of docs/design/space-layers.md: the ground. Every piece of the area at level 0 is exactly one item of `space.ground`, of one
type: water, rail, street, square, green, plot, unknown. Built in that order, each kind taking only ground no earlier kind took; within a
kind, its sources in the order listed. What is left is `unknown`: check G1 reports it, to be traced to a missing rule.

    water   OSM water areas
    rail    OSM railway land (landuse=railway); the rail lines' own beds
    street  our street spaces (space.unit)
    square  OSM pedestrian areas, squares
    green   public green: parks, playgrounds, pitches, recreation grounds, woods (before plots: a park is a parcel too)
    plot    a city's parcels; else car parks (space.lot), construction sites, OSM land use (residential, retail, ...), and a building
            no plot holds
    green   the rest of the green: grass, gardens, allotments
    unknown what is left

Level 0 only: a bridge's or a tunnel's level has no ground of its own but its structure.
"""
import json
import os

PUBLIC_GREEN = ("park", "playground", "pitch", "recreation_ground", "wood", "forest", "cemetery", "nature_reserve", "dog_park")
PLOT_LAND = ("residential", "retail", "commercial", "industrial", "brownfield", "construction", "education", "religious", "institutional",
             "garages", "railway_yard")
OTHER_GREEN = ("grass", "garden", "allotments", "meadow", "village_green", "scrub", "flowerbed", "greenfield")
SQUARE_LAND = ("pedestrian", "square", "plaza")
MIN_M2 = 0.5        # a piece of ground smaller than this is left to its neighbours (a sliver between two sources' edges)


def build(con, epsg):
    import duckdb
    import shapely
    m = lambda col="geometry": f"ST_AsWKB(ST_Transform({col}, 'EPSG:4326', '{epsg}', always_xy := true))"
    g = lambda w: shapely.make_valid(shapely.from_wkb(bytes(w)))
    poly = lambda x: shapely.union_all([p for p in shapely.get_parts(x) if p.geom_type == "Polygon"] or [shapely.Polygon()])

    def rows(sql):
        try:
            return con.execute(sql).fetchall()
        except duckdb.CatalogException:     # a database without that layer
            return []

    area = [g(w) for (w,) in rows(f"SELECT {m()} FROM osm.main.boundary")]
    area = shapely.union_all(area) if area else shapely.box(*shapely.union_all(
        [g(w) for (w,) in rows(f"SELECT {m()} FROM space.element")]).bounds)
    land = lambda kinds: [(f"w{i}" if t == "way" else f"r{i}", n, g(w)) for i, t, n, w in rows(
        f"SELECT osm_id, osm_type, name, {m('geom')} FROM osm.features.land WHERE kind IN {tuple(kinds) + ('',)}")]
    # (type, items [(ref, name, geometry)], source, method), in the order they take the ground
    order = [
        ("water", [(f"w{i}", n, g(w)) for i, n, w in rows(f"SELECT osm_id, name, {m('geom')} FROM osm.features.water_polygons")], "osm", "mapped"),
        ("rail", land(("railway",)) + [(f"w{i}", n, g(w).buffer(max(wd or 4.0, 3.0) / 2, cap_style="flat")) for i, n, w, wd in rows(
            f"SELECT osm_id, name, {m()}, width_m FROM space.element WHERE type = 'rail' AND level_min = 0")], "osm", "mapped"),
        ("street", [(u, None, g(w)) for u, w in rows(f"SELECT unit_id, {m()} FROM space.unit WHERE level = 0")], "urbanstyle", "derived"),
        ("square", land(SQUARE_LAND), "osm", "mapped"),
        ("green", land(PUBLIC_GREEN), "osm", "mapped"),
    ]
    plots = []
    (path,) = con.execute("SELECT path FROM duckdb_databases() WHERE database_name = current_database()").fetchone()
    city = path[:-len(".space.duckdb")] + ".vancouver.json" if path and path.endswith(".space.duckdb") else None
    if city and os.path.exists(city):       # a city's parcels ("much of the land base at survey accuracy")
        fc = (json.load(open(city)).get("property-parcel-polygons") or {}).get("features", [])
        con.execute("CREATE OR REPLACE TEMP TABLE parcel (id VARCHAR, name VARCHAR, g GEOMETRY)")
        if fc:
            con.executemany("INSERT INTO parcel VALUES (?, ?, ST_GeomFromGeoJSON(?))",
                            [(f"pl{(f['properties'] or {}).get('site_id') or (f['properties'] or {}).get('tax_coord') or i}",
                              " ".join(str(x) for x in ((f["properties"] or {}).get("civic_number"), (f["properties"] or {}).get("streetname")) if x),
                              json.dumps(f["geometry"])) for i, f in enumerate(fc) if f.get("geometry")])
            plots.append(([(i, n, g(w)) for i, n, w in rows(f"SELECT id, name, {m('g')} FROM parcel")], "vancouver", "surveyed"))
    plots += [([(i, n, g(w)) for i, n, w in rows(f"SELECT lot_id, name, {m()} FROM space.lot")], "osm", "mapped"),
              ([(f"w{i}", n, g(w)) for i, n, w in rows(f"SELECT osm_id, name, {m('geom')} FROM osm.features.sites WHERE kind = 'construction'")],
               "osm", "mapped"),
              (land(PLOT_LAND), "osm", "mapped"),
              ([(i, n, g(w)) for i, n, w in rows(f"""SELECT source_id, name, {m()} FROM space.element
                                                   WHERE type = 'building' AND level_min <= 0 AND level_max >= 0""")], "osm", "mapped")]
    order += [("plot", items, src, meth) for items, src, meth in plots]
    order.append(("green", land(OTHER_GREEN), "osm", "mapped"))

    taken, out = shapely.Polygon(), []
    for typ, items, src, meth in order:
        for ref, name, geom in items:
            try:
                piece = poly(poly(geom.intersection(area, grid_size=0.01)).difference(taken, grid_size=0.01))
            except shapely.errors.GEOSException:
                continue
            if piece.area < MIN_M2:
                continue
            taken = shapely.union_all([taken, piece], grid_size=0.01)
            # a building's own source: a city's outline (vb...) is the city's
            out.append((f"g0-{typ}-{ref}", typ, name, "vancouver" if ref.startswith("vb") else src, meth, ref, piece))
    rest = [p for p in shapely.get_parts(poly(area.difference(taken, grid_size=0.01))) if p.area >= MIN_M2]
    for p in sorted(rest, key=lambda p: (round(p.centroid.x), round(p.centroid.y))):     # stable for the same data
        out.append((f"g0-unknown-{round(p.centroid.x)}-{round(p.centroid.y)}", "unknown", None, "urbanstyle", "derived", None, p))
    con.execute("""CREATE OR REPLACE TABLE space.ground (ground_id VARCHAR, level INT, type VARCHAR, name VARCHAR, source VARCHAR,
                   method VARCHAR, ref VARCHAR, geometry GEOMETRY)""")
    if out:
        con.executemany(f"""INSERT INTO space.ground VALUES (?, 0, ?, ?, ?, ?, ?,
                            ST_Transform(ST_GeomFromWKB(?), '{epsg}', 'EPSG:4326', always_xy := true))""",
                        [(i, t, n, s, me, r, shapely.to_wkb(p)) for i, t, n, s, me, r, p in out])
    return len(out)
