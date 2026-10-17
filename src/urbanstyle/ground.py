"""Layer 0 of docs/design/space-layers.md: the ground. Every piece of the area at level 0 is exactly one item of `urban.ground`, of one
type: water, rail, street, path, square, structure, green, plot, unknown. Built in that order, each kind taking only ground no earlier kind took; within a
kind, its sources in the order listed. What is left is `unknown`: check G1 reports it, to be traced to a missing rule.

    water   OSM water areas, and the sea (duckOSM's features.ocean, from the coastline)
    rail    OSM railway land (landuse=railway); the rail lines' own beds
    street  our street spaces (urban.unit)
    path    the corridor of a pedestrian way between the blocks (blocks.path_sql, docs/design/paths.md) and the measured path spaces (urban.container `path`)
    square  OSM pedestrian areas (highway=pedestrian + area=yes, the way's own polygon), squares; the measured plazas (urban.container `plaza`)
    structure  the land under a bridge (OSM man_made=bridge), whose deck is a level up; and, after the plots and the green, any land
            under a street space of a higher level (a deck OSM maps as a bridge, without its outline)
    green   public green: parks, playgrounds, pitches, recreation grounds, woods (before plots: a park is a parcel too)
    plot    a city's parcels; else car parks (urban.lot), construction sites, OSM land use (residential, retail, ...), and a building
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
ALLEY_W_M = 6.0      # an alley's width where OSM gives none (chosen: Vancouver's lanes are 6 m)
ALLEY_MIN_W_M = 2.0  # an alley (ground between parcels a road runs through) is at least this wide; narrower, a sliver between parcels
MIN_M2 = 0.5        # a piece of ground smaller than this is left to its neighbours (a sliver between two sources' edges)


def parcels(con):
    """urban.parcel: a city's parcels, the property lines (Vancouver `property-parcel-polygons`, from the unit's city file next to the space
    database; "much of the land base at survey accuracy"), read by the partition (the street reaches them) and by the ground (plots).
    Empty where the city has none."""
    con.execute("CREATE OR REPLACE TABLE urban.parcel (parcel_id VARCHAR, name VARCHAR, geometry GEOMETRY)")
    (path,) = con.execute("SELECT path FROM duckdb_databases() WHERE database_name = current_database()").fetchone()
    city = path[:-len(".urban.duckdb")] + ".vancouver.json" if path and path.endswith(".urban.duckdb") else None
    if not city or not os.path.exists(city):
        return 0
    fc = (json.load(open(city)).get("property-parcel-polygons") or {}).get("features", [])
    rows = [(f"pl{(f['properties'] or {}).get('site_id') or (f['properties'] or {}).get('tax_coord') or i}",
             " ".join(str(x) for x in ((f["properties"] or {}).get("civic_number"), (f["properties"] or {}).get("streetname")) if x),
             json.dumps(f["geometry"])) for i, f in enumerate(fc) if f.get("geometry")]
    if rows:
        con.executemany("INSERT INTO urban.parcel VALUES (?, ?, ST_MakeValid(ST_GeomFromGeoJSON(?)))", rows)
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

    area = [g(w) for (w,) in rows(f"SELECT {m()} FROM osm_boundary")]
    area = shapely.union_all(area) if area else shapely.box(*shapely.union_all(
        [g(w) for (w,) in rows(f"SELECT {m()} FROM urban.element")]).bounds)
    # (not an area OSM maps under the ground, layer < 0: Monaco's station is in a tunnel, landuse=railway on layer -3; Kaveh, 2026-10-13)
    land = lambda kinds: [(f"w{i}" if t == "way" else f"r{i}", n, g(w)) for i, t, n, w in rows(
        f"""SELECT osm_id, osm_type, name, {m('geom')} FROM osm.features.land l WHERE kind IN {tuple(kinds) + ('',)}
            AND NOT EXISTS (SELECT 1 FROM osm.raw.ways w WHERE l.osm_type = 'way' AND w.osm_id = l.osm_id AND try_cast(w.tags['layer'] AS INT) < 0)""")]
    # (type, items [(ref, name, geometry)], source, method), in the order they take the ground
    order = [
        # (and the sea: OSM maps it only by its coastline, duckOSM's features.ocean makes it an area; Monaco's harbours were yards,
        # Kaveh, 2026-10-13)
        ("water", [(f"w{i}", n, g(w)) for i, n, w in rows(f"SELECT osm_id, name, {m('geom')} FROM osm.features.water_polygons")]
         + [(f"{'w' if t == 'way' else 'r'}{i}", n or "sea", g(w)) for i, t, n, w in rows(f"SELECT osm_id, osm_type, name, {m('geom')} FROM osm.features.ocean")],
         "osm", "mapped"),
        ("rail", land(("railway",)) + [(f"w{i}", n, g(w).buffer(max(wd or 4.0, 3.0) / 2, cap_style="flat")) for i, n, w, wd in rows(
            f"SELECT osm_id, name, {m()}, width_m FROM urban.element WHERE type = 'rail' AND level_min = 0")], "osm", "mapped"),
        ("street", [(u, None, g(w)) for u, w in rows(f"SELECT unit_id, {m()} FROM urban.unit WHERE level = 0")], "urbanstyle", "derived"),
        # (a pedestrian area, highway=pedestrian + area=yes: OSM's own polygon from the way's nodes; duckOSM's land has no such kind.
        # Place d'Armes was a block with a path ring round it, 2026-10-16)
        ("square", land(SQUARE_LAND) + [(f"w{i}", n, g(w)) for i, n, w in rows(f"""SELECT w.osm_id, w.tags['name'],
            {m("ST_MakePolygon(ST_MakeLine(list(ST_Point(n.lon, n.lat) ORDER BY u.i) || [first(ST_Point(n.lon, n.lat) ORDER BY u.i)]))")}
            FROM osm.raw.ways w, unnest(w.refs) WITH ORDINALITY AS u(ref, i) JOIN osm.raw.nodes n ON n.osm_id = u.ref
            WHERE w.tags['highway'] = 'pedestrian' AND w.tags['area'] = 'yes' AND w.refs[1] = w.refs[-1]
            AND coalesce(try_cast(w.tags['layer'] AS INT), 0) = 0 GROUP BY w.osm_id, w.tags['name'] HAVING count(*) >= 4""")], "osm", "mapped"),
        ("structure", [(f"w{i}", n, g(w)) for i, n, w in rows(f"SELECT osm_id, name, {m('geom')} FROM osm.features.sites WHERE kind = 'bridge'")],
         "osm", "mapped"),
        ("green", land(PUBLIC_GREEN), "osm", "mapped"),
    ]
    plots = [([(i, n, g(w)) for i, n, w in rows(f"SELECT parcel_id, name, {m()} FROM urban.parcel")], "vancouver", "surveyed")]
    plots += [([(i, n, g(w)) for i, n, w in rows(f"SELECT lot_id, name, {m()} FROM urban.lot")], "osm", "mapped"),
              ([(f"w{i}", n, g(w)) for i, n, w in rows(f"SELECT osm_id, name, {m('geom')} FROM osm.features.sites WHERE kind = 'construction'")],
               "osm", "mapped"),
              (land(PLOT_LAND), "osm", "mapped"),
              ([(i, n, g(w)) for i, n, w in rows(f"""SELECT source_id, name, {m()} FROM urban.element
                                                   WHERE type = 'building' AND level_min <= 0 AND level_max >= 0""")], "osm", "mapped")]
    order += [("plot", items, src, meth) for items, src, meth in plots[:1]]       # the city's parcels
    # blocks first, with parcels: the ground between the parcels that a road runs through is an alley (a back lane, a driveway), before
    # OSM's land use (a residential area drawn over the whole block, its lanes too) can take it
    blocks_ = [g(w) for (w,) in rows(f"SELECT {m()} FROM urban.block WHERE level = 0")]
    if blocks_ and plots[0][0]:
        gaps = poly(shapely.union_all(blocks_).difference(shapely.union_all([x for *_, x in plots[0][0]]), grid_size=0.01))
        # only ground at least ALLEY_MIN_W_M wide: the slivers between parcels (a line drawn twice) are no lane; they join a plot later
        gaps = shapely.get_parts(poly(gaps.buffer(-ALLEY_MIN_W_M / 2, join_style="mitre").buffer(ALLEY_MIN_W_M / 2, join_style="mitre").intersection(gaps, grid_size=0.01)))
        roads_ = [(f"w{o}", n, g(w), wd) for o, n, w, wd in rows(f"""SELECT e.osm_id, e.name, {m('e.geometry')}, try_cast(w.tags['width'] AS DOUBLE)
                  FROM urban.element e LEFT JOIN osm.raw.ways w USING (osm_id) WHERE e.type = 'road' AND e.level_min = 0""")]
        rt = shapely.STRtree([x[2] for x in roads_]) if roads_ else None
        lane = []
        for p in gaps:
            on = sorted(((p.intersection(roads_[k][2]).length, k) for k in (rt.query(p) if rt is not None else [])), reverse=True)
            if on and on[0][0] > 5.0:
                # the alley is the road itself, as wide as OSM says (else ALLEY_W_M), inside the gap: not the whole gap, which can be most
                # of a block where the city's parcels are missing (w37127121: 5,000 m2 of buildings and yards; Kaveh, 2026-10-14)
                ks = [k for ln_, k in on if ln_ > 5.0]
                band = shapely.union_all([roads_[k][2].buffer((roads_[k][3] or ALLEY_W_M) / 2, cap_style="flat") for k in ks])
                ref, name, *_ = roads_[ks[0]]
                for q in shapely.get_parts(poly(p.intersection(band, grid_size=0.01))):
                    lane.append((f"{ref}-{round(q.centroid.x)}-{round(q.centroid.y)}", name, q))
        order.append(("alley", lane, "osm+vancouver", "derived"))      # an OSM road through a gap between the city's parcels
    order += [("plot", items, src, meth) for items, src, meth in plots[1:]]
    # OSM's driveways (duckOSM's driving network; not in urban.element): a drivable strip inside the block, as wide as OSM's width or
    # DRIVEWAY_M, kind alley; a parking aisle stays its car park's
    from .parts import DRIVEWAY_M
    drives = [(f"w{o}", n, g(w).buffer((wd or DRIVEWAY_M) / 2, cap_style="flat")) for o, n, wd, w in rows(f"""SELECT e.osm_id, any_value(w.tags['name']),
                  any_value(try_cast(w.tags['width'] AS DOUBLE)), ST_AsWKB(ST_Union_Agg(ST_Transform(e.geometry, 'EPSG:4326', '{epsg}', always_xy := true)))
                  FROM osm.driving.edges e JOIN osm.raw.ways w USING (osm_id) WHERE w.tags['service'] = 'driveway'
                  AND coalesce(w.tags['layer'], '0') = '0' AND coalesce(w.tags['tunnel'], 'no') = 'no' GROUP BY e.osm_id""")]
    order.append(("driveway", drives, "osm", "mapped"))
    order.append(("green", land(OTHER_GREEN), "osm", "mapped"))
    # the measured path spaces after the plots and the green: a footpath through a park is the park's; they take what no parcel or green
    # holds (a greenway). (No square from urbanstyle's own plaza rule, 2026-10-11: no source maps them; a square is OSM's.)
    order += [
        ("structure", [(u, None, g(w)) for u, w in rows(f"SELECT unit_id, {m()} FROM urban.unit WHERE level > 0")], "urbanstyle", "derived"),
        ("path", [(c_, n, g(w)) for c_, n, w in rows(f"SELECT container_id, name, {m()} FROM urban.container WHERE kind = 'path' AND level = 0")],
         "urbanstyle", "measured"),
    ]

    # blocks first (docs/design/blocks.md): the street is exactly the street spaces, and every other kind only fills the blocks
    blocks = [g(w) for (w,) in rows(f"SELECT {m()} FROM urban.block WHERE level = 0")]
    land_ = poly(shapely.union_all(blocks).intersection(area, grid_size=0.01)) if blocks else None
    if land_ is not None:
        # inside the blocks: no plots (a city's parcels cut buildings into pieces; they set the block edges and find the alleys, and are
        # not shown). Each building whole, before every other kind; then the land by its own kind; the rest of the ground is yard
        first = lambda t: [o for o in order if o[0] == t][:1]
        greens = [o for o in order if o[0] == "green"]
        # (after the street, before the blocks' kinds: the pedestrian ways' corridors, the ground's kind path, paths.md)
        corridors = [("path", [(c_, n, g(w)) for c_, n, w in rows(f"SELECT corridor_id, name, {m()} FROM urban.corridor")], "urbanstyle", "derived")]
        order = (first("street") + corridors + [("building",) + plots[4]] + first("water") + first("rail") + first("square") + first("structure")
                 + greens[:1] + [o for o in order if o[0] == "alley"] + [("car park",) + plots[1], ("construction site",) + plots[2]]
                 + [("alley",) + o[1:] for o in order if o[0] == "driveway"]
                 + greens[1:] + order[-2:-1])     # the structures; (footpaths are not ground: they lie on it, whole, in urban.path)
    else:
        order = [o for o in order if o[0] != "driveway"]
    taken, out = shapely.Polygon(), []
    for typ, items, src, meth in order:
        within = land_ if land_ is not None and typ != "street" and not (typ == "path" and src == "urbanstyle" and meth == "derived") else area
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
    # (every piece of what is left, whatever its size: the kinds partition the area exactly, rank 1 of steps.md; a sliver dropped here
    # was a gap, 32 m2 of them on Monaco, 2026-10-16)
    rest = [p for p in shapely.get_parts(poly(area.difference(taken, grid_size=0.01))) if p.area > 0]
    left = []
    # what is left that a path or a road runs through is that path's or that street's ground (a greenway's corridor, a road under a
    # bridge's ramp): by the line with the most length in it
    lines = [(t, f"w{o}", n, g(w), wd) for t, o, n, w, wd in rows(f"""SELECT e.type, e.osm_id, e.name, {m('e.geometry')},
                    try_cast(w.tags['width'] AS DOUBLE) FROM urban.element e LEFT JOIN osm.raw.ways w USING (osm_id)
                    WHERE e.type IN ('road', 'walkway', 'cycleway') AND e.level_min = 0""")]
    ltree = shapely.STRtree([x[3] for x in lines]) if lines else None
    kept = []
    for p in rest:
        on = sorted(((p.intersection(lines[k][3]).length, k) for k in (ltree.query(p) if ltree is not None else [])), reverse=True)
        if on and on[0][0] > 1.0:
            t, ref, name, *_ = lines[on[0][1]]
            # inside a block a road is a back lane, a driveway, a parking aisle: an alley, not the street
            in_block = land_ is not None and p.intersection(land_).area > 0.5 * p.area
            # in a block a road through it is an alley, a footpath's ground is yard (urban.path lies on it, whole); between the blocks a
            # pedestrian way's corridor (blocks.path_sql cut it out of the blocks, paths.md) is path
            kind = ("alley" if t == "road" else "yard") if in_block else ("street" if t == "road" else "path")
            if kind == "alley":
                # the alley is the road itself, as wide as OSM says (else ALLEY_W_M), not the whole piece: where a city's parcels are
                # missing, the piece is most of a block (w37127121: 2,938 m2 of buildings' yards; Kaveh, 2026-10-14). The rest is
                # what is left
                band = shapely.union_all([lines[k][3].buffer((lines[k][4] or ALLEY_W_M) / 2, cap_style="flat") for L_, k in on
                                          if L_ > 1.0 and lines[k][0] == "road"])
                lane_ = poly(p.intersection(band, grid_size=0.01))
                for q in shapely.get_parts(lane_):
                    if q.area >= MIN_M2:
                        out.append((f"g0-alley-{ref}-{round(q.centroid.x)}-{round(q.centroid.y)}", "alley", name, "osm", "mapped", ref, q))
                kept += [q for q in shapely.get_parts(poly(p.difference(lane_, grid_size=0.01))) if q.area > 0]
                continue
            out.append((f"g0-{kind}-{ref}-{round(p.centroid.x)}-{round(p.centroid.y)}", kind, name, "osm", "mapped", ref, p))
        else:
            kept.append(p)
    rest = kept
    tree = shapely.STRtree([x[6] for x in out]) if out else None
    has_parcels = bool(rows("SELECT 1 FROM urban.parcel LIMIT 1"))
    for p in rest:      # a sliver joins the neighbour it shares the most edge with; where a city's parcels exist, ground outside them that
        #                 touches a street is right-of-way: it joins that street (a junction's cut or a ramp's edge stopped short of it)
        near = sorted(((p.boundary.intersection(out[k][6].buffer(0.05)).length, k) for k in (tree.query(p.buffer(0.05)) if tree is not None else [])),
                      reverse=True)
        streets = [(L, k) for L, k in near if out[k][1] == "street" and L > 0.5]
        row = has_parcels and streets and land_ is None     # blocks first: land never joins the street
        if land_ is not None:
            near = [(L, k) for L, k in near if out[k][1] != "street"] or near
        # a building's ground item is its footprint, exactly: a strip beside it joins another neighbour, or stays (a yard)
        near = [(L, k) for L, k in near if out[k][1] != "building"]
        if ((p.area < SLIVER_M2 or 2 * p.area / p.length < SLIVER_W_M) and near and near[0][0] > 0.1) or row:
            k = streets[0][1] if row else near[0][1]
            out[k] = out[k][:6] + (poly(shapely.union_all([out[k][6], p], grid_size=0.01)),)     # (on the grid, no buffer: a buffer overlapped the neighbours)
        else:
            left.append(p)
    for p in sorted(left, key=lambda p: (round(p.centroid.x), round(p.centroid.y))):     # stable for the same data
        # blocks first: private ground no other kind holds is a yard (a garden, a forecourt, a paved lot); else unknown (G1)
        kind = "yard" if land_ is not None and p.intersection(land_).area > 0.5 * p.area else "unknown"
        out.append((f"g0-{kind}-{round(p.centroid.x)}-{round(p.centroid.y)}", kind, None, "urbanstyle", "derived", None, p))
    # the partition made exact, as one planar construction (rank 1 of steps.md, Kaveh 2026-10-16: "they must partition rank 0"):
    # every outline noded together, the faces polygonized, each face given to the first item (the order is the precedence) that holds its
    # inner point, a face no item holds to the neighbour it shares the most edge with, then each item's faces merged. Faces share their
    # edges, so no hairline is left: pieces snapped to the grid on their own left 7 km of hairlines, 36 m2 of gaps and 12 m2 of overlaps
    out = [o for o in out if o[1] != "unknown"]      # (an unknown sliver is an orphan face below: it joins its neighbour, G1 0)
    noded = shapely.unary_union([area.boundary] + [o[6].boundary for o in out])
    faces = [f for f in shapely.get_parts(shapely.polygonize(shapely.get_parts(noded))) if f.area > 0 and area.contains(f.representative_point())]
    itree = shapely.STRtree([o[6] for o in out]) if out else None
    mine = [[] for _ in out]
    orphans = []
    for f in faces:
        rp = f.representative_point()
        ks = sorted(k for k in (itree.query(rp) if itree is not None else []) if out[k][6].covers(rp))
        if ks:
            mine[ks[0]].append(f)
        else:
            orphans.append(f)
    ftree = shapely.STRtree(faces)
    owner = {}
    for k, fs in enumerate(mine):
        for f in fs:
            owner[id(f)] = k
    for f in orphans:       # (the neighbour face it shares the most edge with, that has an owner)
        near = sorted(((f.boundary.intersection(faces[j].boundary).length, id(faces[j])) for j in ftree.query(f) if id(faces[j]) in owner), reverse=True)
        if near and near[0][0] > 0:
            mine[owner[near[0][1]]].append(f)
    # (one polygon per ground item, a row per piece: the page's street objects and the surfaces read one outline each)
    merged = []
    for o, fs in zip(out, mine):
        if not fs:
            continue
        pieces = [q for q in shapely.get_parts(poly(shapely.unary_union(fs))) if q.geom_type == "Polygon" and not q.is_empty]
        merged += [o[:6] + (pieces[0],)] if len(pieces) == 1 else [(f"{o[0]}/{k_ + 1}",) + o[1:6] + (q,) for k_, q in enumerate(pieces)]
    out = merged
    con.execute("""CREATE OR REPLACE TABLE urban.ground (ground_id VARCHAR, level INT, type VARCHAR, name VARCHAR, source VARCHAR,
                   method VARCHAR, ref VARCHAR, geometry GEOMETRY)""")
    if out:
        con.executemany(f"""INSERT INTO urban.ground VALUES (?, 0, ?, ?, ?, ?, ?,
                            ST_Transform(ST_GeomFromWKB(?), '{epsg}', 'EPSG:4326', always_xy := true))""",
                        [(i, t, n, s, me, r, shapely.to_wkb(p)) for i, t, n, s, me, r, p in out])
    return len(out)


# layer 1: the surfaces inside each ground item (docs/design/space-layers.md). A street's from its parts (urban.part), grouped by the kerb
STREET_SURFACE = {**dict.fromkeys(("lane", "bus lane", "cycle lane", "paved", "junction area", "ring", "shoulder", "parking", "no parking",
                                   "bus zone", "crosswalk", "cycle crossing"), "roadway"),
                  **dict.fromkeys(("sidewalk", "furnishing", "frontage", "open", "bus stop", "tree pit", "driveway"), "pedestrian realm"),
                  "island": "median", "barrier": "median"}       # (a barrier between two carriageways stands where a median would)
VERGE_LAND = ("grass", "flowerbed", "planting")       # OSM green mapped inside a street: a verge
GARDEN_LAND = ("garden", "grass", "allotments", "flowerbed")
PLAY_LAND = ("playground", "pitch", "dog_park")
ONE_SURFACE = {"alley": "roadway", "building": "building", "car park": "car park", "construction site": "construction site", "path": "path", "rail": "track bed", "structure": "under bridge", "square": "paved", "water": "water"}


def surfaces(con, epsg):
    """urban.surface: layer 1. Every ground item is covered exactly by its surfaces, one row per piece of each kind of surface in it, id
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
    for u, t, s_, w in rows(f"SELECT unit_id, type, source, {m()} FROM urban.part"):
        if t in STREET_SURFACE:
            parts.setdefault(u, {}).setdefault(STREET_SURFACE[t], []).append(g(w))
            psrc.setdefault((u, STREET_SURFACE[t]), set()).update((s_ or "urbanstyle").split("+"))
    land = lambda kinds: layer(f"SELECT 'w' || osm_id, {m('geom')} FROM osm.features.land WHERE kind IN {tuple(kinds) + ('',)}")
    verge, garden, play = land(VERGE_LAND), land(GARDEN_LAND), land(PLAY_LAND)
    blds = layer(f"SELECT source_id, {m()} FROM urban.element WHERE type = 'building' AND level_min <= 0 AND level_max >= 0")
    lots = layer(f"SELECT lot_id, {m()} FROM urban.lot")
    sites = layer(f"SELECT 'w' || osm_id, {m('geom')} FROM osm.features.sites WHERE kind = 'construction'")
    walks = layer(f"SELECT 'w' || osm_id, ST_AsWKB(ST_Buffer(ST_Transform(geometry, 'EPSG:4326', '{epsg}', always_xy := true), 1.0)) "
                  f"FROM urban.element WHERE type IN ('walkway', 'cycleway') AND level_min = 0")
    out = []
    for gid, typ, ref, g_src, g_meth, w in rows(f"SELECT ground_id, type, ref, source, method, {m()} FROM urban.ground"):
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
    con.execute("""CREATE OR REPLACE TABLE urban.surface (surface_id VARCHAR, ground_id VARCHAR, level INT, type VARCHAR, source VARCHAR,
                   method VARCHAR, ref VARCHAR, geometry GEOMETRY)""")
    if out:
        con.executemany(f"""INSERT INTO urban.surface VALUES (?, ?, 0, ?, ?, ?, ?,
                            ST_Transform(ST_GeomFromWKB(?), '{epsg}', 'EPSG:4326', always_xy := true))""",
                        [(i, gi, k, s, me, r, shapely.to_wkb(p)) for i, gi, k, s, me, r, p in out])
    return len(out)


PATH_KINDS = {"sidewalk": "sidewalk", "crossing": "crossing", "steps": "steps"}   # by OSM subtype; else the class (footway, cycleway, path, ...)


def paths(con, epsg):
    """urban.path: every footpath at level 0, whole (one item per OSM way, at its own width, PATH_W_M where OSM gives none), lying on the
    ground and naming what it lies on (`on`: the ground items it crosses). A path is not cut by a block's edge: only the public ways
    (blocks.path_sql) have ground of their own, the kind `path` between the blocks; the others lie on a yard, a park, a sidewalk."""
    import duckdb
    import shapely
    m = lambda col="geometry": f"ST_AsWKB(ST_Transform({col}, 'EPSG:4326', '{epsg}', always_xy := true))"
    try:
        ways = con.execute(f"""SELECT osm_id, any_value(subtype), any_value(class), any_value(name), max(width_m), {m('ST_Union_Agg(geometry)')}
                              FROM urban.element WHERE type IN ('walkway', 'cycleway') AND level_min = 0 GROUP BY osm_id""").fetchall()
        ground = [(i, shapely.make_valid(shapely.from_wkb(bytes(w)))) for i, w in con.execute(f"SELECT ground_id, {m()} FROM urban.ground").fetchall()]
    except duckdb.CatalogException:
        return 0
    gt = shapely.STRtree([x for _, x in ground]) if ground else None
    rows = []
    for oid, sub_, cl, name, wd, w in ways:
        gm = shapely.from_wkb(bytes(w)).buffer(max(wd or PATH_W_M, 1.0) / 2, cap_style="flat")
        on = [ground[k][0] for k in (gt.query(gm) if gt is not None else []) if ground[k][1].intersection(gm).area > 0.5]
        rows.append((f"w{oid}", PATH_KINDS.get(sub_ or "", cl), name, round(wd or PATH_W_M, 2), "osm" if wd else "urbanstyle",
                     "mapped" if wd else "chosen", ",".join(sorted(on)), shapely.to_wkb(gm)))
    con.execute("""CREATE OR REPLACE TABLE urban.path (path_id VARCHAR, kind VARCHAR, name VARCHAR, width_m DOUBLE, width_source VARCHAR,
                   width_method VARCHAR, "on" VARCHAR, geometry GEOMETRY)""")
    if rows:
        con.executemany(f"""INSERT INTO urban.path VALUES (?, ?, ?, ?, ?, ?, ?,
                            ST_Transform(ST_GeomFromWKB(?), '{epsg}', 'EPSG:4326', always_xy := true))""", rows)
    return len(rows)
