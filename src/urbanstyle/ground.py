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
PATH_W_M = 2.0       # a footpath's width where OSM gives none (chosen)
ALLEY_MIN_W_M = 2.0  # an alley (ground between parcels a road runs through) is at least this wide; narrower, a sliver between parcels
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
    order += [("plot", items, src, meth) for items, src, meth in plots[:1]]       # the city's parcels
    # blocks first, with parcels: the ground between the parcels that a road runs through is an alley (a back lane, a driveway), before
    # OSM's land use (a residential area drawn over the whole block, its lanes too) can take it
    blocks_ = [g(w) for (w,) in rows(f"SELECT {m()} FROM space.block WHERE level = 0")]
    if blocks_ and plots[0][0]:
        gaps = poly(shapely.union_all(blocks_).difference(shapely.union_all([x for *_, x in plots[0][0]]), grid_size=0.01))
        # only ground at least ALLEY_MIN_W_M wide: the slivers between parcels (a line drawn twice) are no lane; they join a plot later
        gaps = shapely.get_parts(poly(gaps.buffer(-ALLEY_MIN_W_M / 2, join_style="mitre").buffer(ALLEY_MIN_W_M / 2, join_style="mitre").intersection(gaps, grid_size=0.01)))
        roads_ = [(f"w{o}", n, g(w)) for o, n, w in rows(f"SELECT osm_id, name, {m()} FROM space.element WHERE type = 'road' AND level_min = 0")]
        rt = shapely.STRtree([x for *_, x in roads_]) if roads_ else None
        lane = []
        for p in gaps:
            on = sorted(((p.intersection(roads_[k][2]).length, k) for k in (rt.query(p) if rt is not None else [])), reverse=True)
            if on and on[0][0] > 5.0:
                ref, name, _ = roads_[on[0][1]]
                lane.append((f"{ref}-{round(p.centroid.x)}-{round(p.centroid.y)}", name, p))
        order.append(("alley", lane, "osm+vancouver", "derived"))      # an OSM road through a gap between the city's parcels
    order += [("plot", items, src, meth) for items, src, meth in plots[1:]]
    # OSM's driveways (duckOSM's driving network; not in space.element): a drivable strip inside the block, as wide as OSM's width or
    # DRIVEWAY_M, kind alley; a parking aisle stays its car park's
    from .parts import DRIVEWAY_M
    drives = [(f"w{o}", n, g(w).buffer((wd or DRIVEWAY_M) / 2, cap_style="flat")) for o, n, wd, w in rows(f"""SELECT e.osm_id, any_value(w.tags['name']),
                  any_value(try_cast(w.tags['width'] AS DOUBLE)), ST_AsWKB(ST_Union_Agg(ST_Transform(e.geometry, 'EPSG:4326', '{epsg}', always_xy := true)))
                  FROM osm.driving.edges e JOIN osm.raw.ways w USING (osm_id) WHERE w.tags['service'] = 'driveway'
                  AND coalesce(w.tags['layer'], '0') = '0' AND coalesce(w.tags['tunnel'], 'no') = 'no' GROUP BY e.osm_id""")]
    order.append(("driveway", drives, "osm", "mapped"))
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

    # blocks first (docs/design/blocks.md): the street is exactly the street spaces, and every other kind only fills the blocks
    blocks = [g(w) for (w,) in rows(f"SELECT {m()} FROM space.block WHERE level = 0")]
    land_ = poly(shapely.union_all(blocks).intersection(area, grid_size=0.01)) if blocks else None
    if land_ is not None:
        # inside the blocks: no plots (a city's parcels cut buildings into pieces; they set the block edges and find the alleys, and are
        # not shown). Each building whole, before every other kind; then the land by its own kind; the rest of the ground is yard
        first = lambda t: [o for o in order if o[0] == t][:1]
        greens = [o for o in order if o[0] == "green"]
        order = (first("street") + [("building",) + plots[4]] + first("water") + first("rail") + first("square") + first("structure")
                 + greens[:1] + [o for o in order if o[0] == "alley"] + [("car park",) + plots[1], ("construction site",) + plots[2]]
                 + [("alley",) + o[1:] for o in order if o[0] == "driveway"]
                 + greens[1:] + order[-3:-2]
                 + order[-1:])     # (footpaths are not ground: they lie on it, whole, in space.path)
    else:
        order = [o for o in order if o[0] != "driveway"]
    taken, out = shapely.Polygon(), []
    for typ, items, src, meth in order:
        within = land_ if land_ is not None and typ != "street" else area
        for ref, name, geom in items:
            try:
                piece = poly(poly(geom.intersection(within, grid_size=0.01)).difference(taken, grid_size=0.01))
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
            # inside a block a road is a back lane, a driveway, a parking aisle: an alley, not the street
            in_block = land_ is not None and p.intersection(land_).area > 0.5 * p.area
            # in a block a road through it is an alley; a footpath is not ground (space.path lies on it, whole): its ground is yard
            kind = ("alley" if t == "road" else "yard") if in_block else ("street" if t == "road" else "path")
            out.append((f"g0-{kind}-{ref}-{round(p.centroid.x)}-{round(p.centroid.y)}", kind, name, "osm", "mapped", ref, p))
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
        row = has_parcels and streets and land_ is None     # blocks first: land never joins the street
        if land_ is not None:
            near = [(L, k) for L, k in near if out[k][1] != "street"] or near
        if ((p.area < SLIVER_M2 or 2 * p.area / p.length < SLIVER_W_M) and near and near[0][0] > 0.1) or row:
            k = streets[0][1] if row else near[0][1]
            out[k] = out[k][:6] + (poly(shapely.union_all([out[k][6], p.buffer(0.01)], grid_size=0.01)),)
        else:
            left.append(p)
    for p in sorted(left, key=lambda p: (round(p.centroid.x), round(p.centroid.y))):     # stable for the same data
        # blocks first: private ground no other kind holds is a yard (a garden, a forecourt, a paved lot); else unknown (G1)
        kind = "yard" if land_ is not None and p.intersection(land_).area > 0.5 * p.area else "unknown"
        out.append((f"g0-{kind}-{round(p.centroid.x)}-{round(p.centroid.y)}", kind, None, "urbanstyle", "derived", None, p))
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
                  **dict.fromkeys(("sidewalk", "furnishing", "frontage", "open", "bus stop", "tree pit", "driveway"), "pedestrian realm"),
                  "island": "median"}
VERGE_LAND = ("grass", "flowerbed", "planting")       # OSM green mapped inside a street: a verge
GARDEN_LAND = ("garden", "grass", "allotments", "flowerbed")
PLAY_LAND = ("playground", "pitch", "dog_park")
ONE_SURFACE = {"alley": "roadway", "building": "building", "car park": "car park", "construction site": "construction site", "path": "path", "rail": "track bed", "structure": "under bridge", "square": "paved", "water": "water"}


def surfaces(con, epsg):
    """space.surface: layer 1. Every ground item is covered exactly by its surfaces, one row per piece of each kind of surface in it, id
    `<ground id>:<kind>` (`/<n>` where a kind is in several pieces): in a street the roadway, the pedestrian realm, the median (from its parts) and a verge (OSM's grass in the street);
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

    parts, psrc = {}, {}     # the parts of each street space by surface, and their sources
    for u, t, s_, w in rows(f"SELECT unit_id, type, source, {m()} FROM space.part"):
        if t in STREET_SURFACE:
            parts.setdefault(u, {}).setdefault(STREET_SURFACE[t], []).append(g(w))
            psrc.setdefault((u, STREET_SURFACE[t]), set()).update((s_ or "urbanstyle").split("+"))
    land = lambda kinds: layer(f"SELECT 'w' || osm_id, {m('geom')} FROM osm.features.land WHERE kind IN {tuple(kinds) + ('',)}")
    verge, garden, play = land(VERGE_LAND), land(GARDEN_LAND), land(PLAY_LAND)
    blds = layer(f"SELECT source_id, {m()} FROM space.element WHERE type = 'building' AND level_min <= 0 AND level_max >= 0")
    lots = layer(f"SELECT lot_id, {m()} FROM space.lot")
    sites = layer(f"SELECT 'w' || osm_id, {m('geom')} FROM osm.features.sites WHERE kind = 'construction'")
    walks = layer(f"SELECT 'w' || osm_id, ST_AsWKB(ST_Buffer(ST_Transform(geometry, 'EPSG:4326', '{epsg}', always_xy := true), 1.0)) "
                  f"FROM space.element WHERE type IN ('walkway', 'cycleway') AND level_min = 0")
    out = []
    for gid, typ, ref, g_src, g_meth, w in rows(f"SELECT ground_id, type, ref, source, method, {m()} FROM space.ground"):
        G = poly(g(w))
        claims = []         # (surface kind, geometry, source, method, refs), in the order they take the ground
        if typ == "street":
            for kind in ("roadway", "median", "pedestrian realm"):
                if parts.get(ref, {}).get(kind):
                    claims.append((kind, shapely.union_all(parts[ref][kind]), "+".join(sorted(psrc[(ref, kind)])), "derived", f"the parts of {ref}"))
            if not claims:      # a piece of right-of-way a road runs through (a back lane in a block), no space's parts in it
                claims.append(("roadway", G, "osm", "mapped", ref))
            v = inside(verge, G)
            if v:       # a verge takes the pedestrian realm's ground where OSM maps grass, never the roadway's
                claims.insert(min(2, len(claims)), ("verge", shapely.union_all([x for x, _ in v]), "osm", "mapped", ", ".join(r for _, r in v)))
        elif typ == "plot":
            for kind, src, s, me in (("building", blds, "osm", "mapped"), ("car park", lots, "osm", "mapped"),
                                     ("construction site", sites, "osm", "mapped"), ("garden", garden, "osm", "mapped")):
                hits = inside(src, G)
                if hits:
                    claims.append((kind, shapely.union_all([x for x, _ in hits]), s, me, ", ".join(r for _, r in hits)))
            claims.append(("yard", G, "urbanstyle", "derived", None))      # the rest of the plot
        elif typ == "yard":     # a yard: OSM's gardens and grass in it, the rest yard
            hits = inside(garden, G)
            if hits:
                claims.append(("garden", shapely.union_all([x for x, _ in hits]), "osm", "mapped", ", ".join(r for _, r in hits)))
            claims.append(("yard", G, "urbanstyle", "derived", None))
        elif typ == "green":
            for kind, src in (("play", play), ("path", walks)):
                hits = inside(src, G)
                if hits:
                    claims.append((kind, shapely.union_all([x for x, _ in hits]), "osm", "mapped", ", ".join(r for _, r in hits)))
            claims.append(("lawn", G, "urbanstyle", "derived", None))
        else:
            claims.append((ONE_SURFACE.get(typ, typ), G, g_src or "urbanstyle", g_meth or "derived", ref))      # the ground item's own
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
        for i, gi, k, s, me, r, p in mine:      # one item per piece: the sidewalk on each side, each building
            ps = sorted((x for x in shapely.get_parts(p) if x.area >= 0.01), key=lambda x: (round(x.centroid.x, 1), round(x.centroid.y, 1)))
            out += [[i if len(ps) == 1 else f"{i}/{n}", gi, k, s, me, r, x] for n, x in enumerate(ps, 1)]
    con.execute("""CREATE OR REPLACE TABLE space.surface (surface_id VARCHAR, ground_id VARCHAR, level INT, type VARCHAR, source VARCHAR,
                   method VARCHAR, ref VARCHAR, geometry GEOMETRY)""")
    if out:
        con.executemany(f"""INSERT INTO space.surface VALUES (?, ?, 0, ?, ?, ?, ?,
                            ST_Transform(ST_GeomFromWKB(?), '{epsg}', 'EPSG:4326', always_xy := true))""",
                        [(i, gi, k, s, me, r, shapely.to_wkb(p)) for i, gi, k, s, me, r, p in out])
    return len(out)


PATH_KINDS = {"sidewalk": "sidewalk", "crossing": "crossing", "steps": "steps"}   # by OSM subtype; else the class (footway, cycleway, path, ...)


def paths(con, epsg):
    """space.path: every footpath at level 0, whole (one item per OSM way, at its own width, PATH_W_M where OSM gives none), lying on the
    ground and naming what it lies on (`on`: the ground items it crosses). A path is not cut by a block's edge: it is not ground."""
    import duckdb
    import shapely
    m = lambda col="geometry": f"ST_AsWKB(ST_Transform({col}, 'EPSG:4326', '{epsg}', always_xy := true))"
    try:
        ways = con.execute(f"""SELECT osm_id, any_value(subtype), any_value(class), any_value(name), max(width_m), {m('ST_Union_Agg(geometry)')}
                              FROM space.element WHERE type IN ('walkway', 'cycleway') AND level_min = 0 GROUP BY osm_id""").fetchall()
        ground = [(i, shapely.make_valid(shapely.from_wkb(bytes(w)))) for i, w in con.execute(f"SELECT ground_id, {m()} FROM space.ground").fetchall()]
    except duckdb.CatalogException:
        return 0
    gt = shapely.STRtree([x for _, x in ground]) if ground else None
    rows = []
    for oid, sub_, cl, name, wd, w in ways:
        gm = shapely.from_wkb(bytes(w)).buffer(max(wd or PATH_W_M, 1.0) / 2, cap_style="flat")
        on = [ground[k][0] for k in (gt.query(gm) if gt is not None else []) if ground[k][1].intersection(gm).area > 0.5]
        rows.append((f"w{oid}", PATH_KINDS.get(sub_ or "", cl), name, round(wd or PATH_W_M, 2), "osm" if wd else "urbanstyle",
                     "mapped" if wd else "chosen", ",".join(sorted(on)), shapely.to_wkb(gm)))
    con.execute("""CREATE OR REPLACE TABLE space.path (path_id VARCHAR, kind VARCHAR, name VARCHAR, width_m DOUBLE, width_source VARCHAR,
                   width_method VARCHAR, "on" VARCHAR, geometry GEOMETRY)""")
    if rows:
        con.executemany(f"""INSERT INTO space.path VALUES (?, ?, ?, ?, ?, ?, ?,
                            ST_Transform(ST_GeomFromWKB(?), '{epsg}', 'EPSG:4326', always_xy := true))""", rows)
    return len(rows)
