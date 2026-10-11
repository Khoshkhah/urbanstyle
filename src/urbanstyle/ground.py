"""Layer 0 of docs/design/space-layers.md: the ground. Every piece of the area at level 0 is exactly one item of `space.ground`, of one
type: water, rail, street, path, square, structure, green, plot, unknown. Built in that order, each kind taking only ground no earlier kind took; within a
kind, its sources in the order listed. What is left is `unknown`: check G1 reports it, to be traced to a missing rule.

    water   OSM water areas
    rail    OSM railway land (landuse=railway); the rail lines' own beds
    street  our street spaces (space.unit)
    path    walkways and cycleways away from roads (a greenway, a connector, a footpath): the measured path spaces (space.container `path`)
    square  OSM pedestrian areas, squares; the measured plazas (space.container `plaza`)
    structure  the land under a bridge (OSM man_made=bridge), whose deck is a level up; and, after the plots and the green, any land
            under a street space of a higher level (a deck OSM maps as a bridge, without its outline)
    green   public green: parks, playgrounds, pitches, recreation grounds, woods (before plots: a park is a parcel too)
    plot    a city's parcels; else car parks (space.lot), construction sites, OSM land use (residential, retail, ...), and a building
            no plot holds
    green   the rest of the green: grass, gardens, allotments
    (what is left that a path or a road runs through is that path's or that street's)
    unknown what is left; a sliver (under SLIVER_M2, or thinner than SLIVER_W_M: where sources' edges almost meet) joins the neighbour it
            shares the most edge with; where a city's parcels exist, what lies outside them and touches a street is right-of-way and joins
            that street

Level 0 only: a bridge's or a tunnel's level has no ground of its own but its structure.
"""
import json
import os

PUBLIC_GREEN = ("park", "playground", "pitch", "recreation_ground", "wood", "forest", "cemetery", "nature_reserve", "dog_park")
PLOT_LAND = ("residential", "retail", "commercial", "industrial", "brownfield", "construction", "education", "religious", "institutional",
             "garages", "railway_yard")
OTHER_GREEN = ("grass", "garden", "allotments", "meadow", "village_green", "scrub", "flowerbed", "greenfield")
SQUARE_LAND = ("pedestrian", "square", "plaza")
SLIVER_M2 = 5.0     # unknown ground smaller than this, or thinner than SLIVER_W_M on average (twice its area over its outline), is a sliver
SLIVER_W_M = 2.0    # between sources' edges (a path, a park, a parcel, a bridge almost meeting): it joins its neighbour
MIN_M2 = 0.5        # a piece of ground smaller than this is left to its neighbours (a sliver between two sources' edges)


def parcels(con):
    """space.parcel: a city's parcels, the property lines (Vancouver `property-parcel-polygons`, from the unit's city file next to the space
    database; "much of the land base at survey accuracy"), read by the partition (the street reaches them) and by the ground (plots).
    Empty where the city has none."""
    con.execute("CREATE OR REPLACE TABLE space.parcel (parcel_id VARCHAR, name VARCHAR, geometry GEOMETRY)")
    (path,) = con.execute("SELECT path FROM duckdb_databases() WHERE database_name = current_database()").fetchone()
    city = path[:-len(".space.duckdb")] + ".vancouver.json" if path and path.endswith(".space.duckdb") else None
    if not city or not os.path.exists(city):
        return 0
    fc = (json.load(open(city)).get("property-parcel-polygons") or {}).get("features", [])
    rows = [(f"pl{(f['properties'] or {}).get('site_id') or (f['properties'] or {}).get('tax_coord') or i}",
             " ".join(str(x) for x in ((f["properties"] or {}).get("civic_number"), (f["properties"] or {}).get("streetname")) if x),
             json.dumps(f["geometry"])) for i, f in enumerate(fc) if f.get("geometry")]
    if rows:
        con.executemany("INSERT INTO space.parcel VALUES (?, ?, ST_MakeValid(ST_GeomFromGeoJSON(?)))", rows)
    return len(rows)


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
        ("structure", [(f"w{i}", n, g(w)) for i, n, w in rows(f"SELECT osm_id, name, {m('geom')} FROM osm.features.sites WHERE kind = 'bridge'")],
         "osm", "mapped"),
        ("green", land(PUBLIC_GREEN), "osm", "mapped"),
    ]
    plots = [([(i, n, g(w)) for i, n, w in rows(f"SELECT parcel_id, name, {m()} FROM space.parcel")], "vancouver", "surveyed")]
    plots += [([(i, n, g(w)) for i, n, w in rows(f"SELECT lot_id, name, {m()} FROM space.lot")], "osm", "mapped"),
              ([(f"w{i}", n, g(w)) for i, n, w in rows(f"SELECT osm_id, name, {m('geom')} FROM osm.features.sites WHERE kind = 'construction'")],
               "osm", "mapped"),
              (land(PLOT_LAND), "osm", "mapped"),
              ([(i, n, g(w)) for i, n, w in rows(f"""SELECT source_id, name, {m()} FROM space.element
                                                   WHERE type = 'building' AND level_min <= 0 AND level_max >= 0""")], "osm", "mapped")]
    order += [("plot", items, src, meth) for items, src, meth in plots]
    order.append(("green", land(OTHER_GREEN), "osm", "mapped"))
    # the measured path spaces and plazas after the plots and the green: a footpath through a park is the park's, a plaza in a parcel
    # the plot's; they take what no parcel or green holds (a greenway, a public plaza)
    order += [
        ("structure", [(u, None, g(w)) for u, w in rows(f"SELECT unit_id, {m()} FROM space.unit WHERE level > 0")], "urbanstyle", "derived"),
        ("path", [(c_, n, g(w)) for c_, n, w in rows(f"SELECT container_id, name, {m()} FROM space.container WHERE kind = 'path' AND level = 0")],
         "urbanstyle", "measured"),
        ("square", [(c_, n, g(w)) for c_, n, w in rows(f"SELECT container_id, name, {m()} FROM space.container WHERE kind = 'plaza' AND level = 0")],
         "urbanstyle", "measured"),
    ]

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
    left = []
    # what is left that a path or a road runs through is that path's or that street's ground (a greenway's corridor, a road under a
    # bridge's ramp): by the line with the most length in it
    lines = [(t, f"w{o}", n, g(w)) for t, o, n, w in rows(f"""SELECT type, osm_id, name, {m()} FROM space.element
                                                             WHERE type IN ('road', 'walkway', 'cycleway') AND level_min = 0""")]
    ltree = shapely.STRtree([x[3] for x in lines]) if lines else None
    kept = []
    for p in rest:
        on = sorted(((p.intersection(lines[k][3]).length, k) for k in (ltree.query(p) if ltree is not None else [])), reverse=True)
        if on and on[0][0] > 1.0:
            t, ref, name, _ = lines[on[0][1]]
            out.append((f"g0-{'street' if t == 'road' else 'path'}-{ref}-{round(p.centroid.x)}-{round(p.centroid.y)}",
                        "street" if t == "road" else "path", name, "osm", "mapped", ref, p))
        else:
            kept.append(p)
    rest = kept
    tree = shapely.STRtree([x[6] for x in out]) if out else None
    has_parcels = bool(rows("SELECT 1 FROM space.parcel LIMIT 1"))
    for p in rest:      # a sliver joins the neighbour it shares the most edge with; where a city's parcels exist, ground outside them that
        #                 touches a street is right-of-way: it joins that street (a junction's cut or a ramp's edge stopped short of it)
        near = sorted(((p.boundary.intersection(out[k][6].buffer(0.05)).length, k) for k in (tree.query(p.buffer(0.05)) if tree is not None else [])),
                      reverse=True)
        streets = [(L, k) for L, k in near if out[k][1] == "street" and L > 0.5]
        row = has_parcels and streets
        if ((p.area < SLIVER_M2 or 2 * p.area / p.length < SLIVER_W_M) and near and near[0][0] > 0.1) or row:
            k = streets[0][1] if row else near[0][1]
            out[k] = out[k][:6] + (poly(shapely.union_all([out[k][6], p.buffer(0.01)], grid_size=0.01)),)
        else:
            left.append(p)
    for p in sorted(left, key=lambda p: (round(p.centroid.x), round(p.centroid.y))):     # stable for the same data
        out.append((f"g0-unknown-{round(p.centroid.x)}-{round(p.centroid.y)}", "unknown", None, "urbanstyle", "derived", None, p))
    con.execute("""CREATE OR REPLACE TABLE space.ground (ground_id VARCHAR, level INT, type VARCHAR, name VARCHAR, source VARCHAR,
                   method VARCHAR, ref VARCHAR, geometry GEOMETRY)""")
    if out:
        con.executemany(f"""INSERT INTO space.ground VALUES (?, 0, ?, ?, ?, ?, ?,
                            ST_Transform(ST_GeomFromWKB(?), '{epsg}', 'EPSG:4326', always_xy := true))""",
                        [(i, t, n, s, me, r, shapely.to_wkb(p)) for i, t, n, s, me, r, p in out])
    return len(out)


# layer 1: the surfaces inside each ground item (docs/design/space-layers.md). A street's from its parts (space.part), grouped by the kerb
STREET_SURFACE = {**dict.fromkeys(("lane", "bus lane", "cycle lane", "carriageway", "junction area", "ring", "shoulder", "parking", "no parking",
                                   "bus zone", "crosswalk", "cycle crossing"), "roadway"),
                  **dict.fromkeys(("sidewalk", "furnishing", "open", "bus stop", "tree pit", "driveway"), "pedestrian realm"),
                  "island": "median"}
VERGE_LAND = ("grass", "flowerbed", "planting")       # OSM green mapped inside a street: a verge
GARDEN_LAND = ("garden", "grass", "allotments", "flowerbed")
PLAY_LAND = ("playground", "pitch", "dog_park")
ONE_SURFACE = {"path": "path", "rail": "track bed", "structure": "under bridge", "square": "paved", "water": "water"}


def surfaces(con, epsg):
    """space.surface: layer 1. Every ground item is covered exactly by its surfaces, one row per kind of surface in it, id
    `<ground id>:<kind>`: in a street the roadway, the pedestrian realm, the median (from its parts) and a verge (OSM's grass in the street);
    in a plot its buildings, car park, construction site, garden (OSM) and the yard (the rest); in green play (playgrounds, pitches), path
    (its footpaths, 2 m) and lawn (the rest); a path, a track bed, the ground under a bridge, a paved square. What no source names in a
    street or a green joins the surface it shares the most edge with."""
    import duckdb
    import shapely
    m = lambda col="geometry": f"ST_AsWKB(ST_Transform({col}, 'EPSG:4326', '{epsg}', always_xy := true))"
    g = lambda w: shapely.make_valid(shapely.from_wkb(bytes(w)))
    poly = lambda x: shapely.union_all([p for p in shapely.get_parts(x) if p.geom_type == "Polygon"] or [shapely.Polygon()])

    def rows(sql):
        try:
            return con.execute(sql).fetchall()
        except duckdb.CatalogException:
            return []

    def layer(sql):         # [(geometry, ref)] with a tree, for clipping to each ground item
        items = [(g(w), r) for r, w in rows(sql)]
        return items, (shapely.STRtree([x for x, _ in items]) if items else None)

    def inside(src, G):
        items, tree = src
        return [(x, r) for x, r in ([items[k] for k in tree.query(G)] if tree is not None else [])]

    parts = {}
    for u, t, w in rows(f"SELECT unit_id, type, {m()} FROM space.part"):
        if t in STREET_SURFACE:
            parts.setdefault(u, {}).setdefault(STREET_SURFACE[t], []).append(g(w))
    land = lambda kinds: layer(f"SELECT 'w' || osm_id, {m('geom')} FROM osm.features.land WHERE kind IN {tuple(kinds) + ('',)}")
    verge, garden, play = land(VERGE_LAND), land(GARDEN_LAND), land(PLAY_LAND)
    blds = layer(f"SELECT source_id, {m()} FROM space.element WHERE type = 'building' AND level_min <= 0 AND level_max >= 0")
    lots = layer(f"SELECT lot_id, {m()} FROM space.lot")
    sites = layer(f"SELECT 'w' || osm_id, {m('geom')} FROM osm.features.sites WHERE kind = 'construction'")
    walks = layer(f"SELECT 'w' || osm_id, ST_AsWKB(ST_Buffer(ST_Transform(geometry, 'EPSG:4326', '{epsg}', always_xy := true), 1.0)) "
                  f"FROM space.element WHERE type IN ('walkway', 'cycleway') AND level_min = 0")
    out = []
    for gid, typ, ref, w in rows(f"SELECT ground_id, type, ref, {m()} FROM space.ground"):
        G = poly(g(w))
        claims = []         # (surface kind, geometry, source, method, refs), in the order they take the ground
        if typ == "street":
            for kind in ("roadway", "median", "pedestrian realm"):
                if parts.get(ref, {}).get(kind):
                    claims.append((kind, shapely.union_all(parts[ref][kind]), "urbanstyle", "derived", None))
            v = inside(verge, G)
            if v:       # a verge takes the pedestrian realm's ground where OSM maps grass, never the roadway's
                claims.insert(2, ("verge", shapely.union_all([x for x, _ in v]), "osm", "mapped", ", ".join(r for _, r in v)))
            if not claims:      # a piece of right-of-way a road runs through, no space's parts in it
                claims.append(("roadway", G, "osm", "mapped", ref))
        elif typ == "plot":
            for kind, src, s, me in (("building", blds, "osm", "mapped"), ("car park", lots, "osm", "mapped"),
                                     ("construction site", sites, "osm", "mapped"), ("garden", garden, "osm", "mapped")):
                hits = inside(src, G)
                if hits:
                    claims.append((kind, shapely.union_all([x for x, _ in hits]), s, me, ", ".join(r for _, r in hits)))
            claims.append(("yard", G, "urbanstyle", "derived", None))      # the rest of the plot
        elif typ == "green":
            for kind, src in (("play", play), ("path", walks)):
                hits = inside(src, G)
                if hits:
                    claims.append((kind, shapely.union_all([x for x, _ in hits]), "osm", "mapped", ", ".join(r for _, r in hits)))
            claims.append(("lawn", G, "urbanstyle", "derived", None))
        else:
            claims.append((ONE_SURFACE.get(typ, typ), G, "urbanstyle", "derived", None))
        taken, mine = shapely.Polygon(), []
        for kind, geom, s, me, r in claims:
            try:
                piece = poly(poly(geom.intersection(G, grid_size=0.01)).difference(taken, grid_size=0.01))
            except shapely.errors.GEOSException:
                continue
            if piece.area < MIN_M2:
                continue
            taken = shapely.union_all([taken, piece], grid_size=0.01)
            mine.append([f"{gid}:{kind}", gid, kind, s, me, r, piece])
        rest = poly(G.difference(taken, grid_size=0.01)) if mine else shapely.Polygon()
        for p in (shapely.get_parts(rest) if not rest.is_empty else []):     # what no source names joins its neighbour in this item
            if p.area < 0.01:
                continue
            best = max(mine, key=lambda x: p.boundary.intersection(x[6].buffer(0.05)).length)
            best[6] = poly(shapely.union_all([best[6], p], grid_size=0.01))
        out += mine
    con.execute("""CREATE OR REPLACE TABLE space.surface (surface_id VARCHAR, ground_id VARCHAR, level INT, type VARCHAR, source VARCHAR,
                   method VARCHAR, ref VARCHAR, geometry GEOMETRY)""")
    if out:
        con.executemany(f"""INSERT INTO space.surface VALUES (?, ?, 0, ?, ?, ?, ?,
                            ST_Transform(ST_GeomFromWKB(?), '{epsg}', 'EPSG:4326', always_xy := true))""",
                        [(i, gi, k, s, me, r, shapely.to_wkb(p)) for i, gi, k, s, me, r, p in out])
    return len(out)
