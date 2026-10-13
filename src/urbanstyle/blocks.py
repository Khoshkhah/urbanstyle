"""Blocks (docs/design/blocks.md, step 1): the land between the streets at level 0, from which the street is divided.

    bounding roads  OSM's public streets at level 0 (STREET, with their links); a road on a deck at level 1 only where nothing at ground
                    level passes under it. Service roads (alleys, driveways, parking aisles), paths and rail lie inside blocks
    chains          the bounding roads joined end to end between junctions, simplified by SIMPLIFY_M
    faces           the areas the chains enclose, closed by the edge of the area (the clip's box)
    street side     each side of a chain within a face gets one distance from the road line, so the block's edge there runs parallel to
                    the road: the parcels' median line (a city's `space.parcel`), else OSM's sidewalks + SIDEWALK_BACK_M, else half the
                    class's right-of-way (HALF_ROW); pulled in to the nearest parcel (and, where no parcel sets the side, to the
                    nearest building), so no plot is cut; a building is drawn whole even where its OSM outline reaches over the line
    block           what is left of a face, if at least MIN_BLOCK_M2 and MIN_BLOCK_W_M wide; corners are sharp (each edge line runs on
                    past the junction)

space.block       block_id, level, area_m2, source, method, geometry. Id `b<level>-w<way><side>`: the smallest OSM way among its bounding
                  roads and the side of that way it lies on (l / r), `.2`, `.3` ... where one way bounds several blocks on that side
space.block_side  one row per street side of a block: the way, the distance and what set it (`basis`: parcels, sidewalks, class,
                  building or parcel), the distance before a building or a parcel pulled it in, that building or parcel
space.area        the edge of the area (the clip's box), for the checks
space.city_block  a city's own block outlines (Vancouver `block-outlines`), only to cross-check ours (check B6), never as input
"""
import json
import os
import statistics

STREET = ("motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street", "pedestrian")
HALF_ROW = {"motorway": 18, "trunk": 16, "primary": 15, "secondary": 12, "tertiary": 10, "unclassified": 10, "residential": 10,
            "living_street": 8, "pedestrian": 10}  # half right-of-way by class where neither parcels nor sidewalks give it (chosen)
SIMPLIFY_M = 1.0        # OSM's small wiggles are not the street's shape
STEP_M = 5.0            # lines square to the road, every
REACH_M = 25.0          # looked for out to
HIT_CAP = 1.5           # a parcel or sidewalk counts within this many times the class's half right-of-way (not the next street's)
SIDEWALK_BACK_M = 1.0   # a sidewalk is drawn along its middle: the property line is about this far behind it
ALONG_COS = 0.82        # a sidewalk runs along the road: within ~35 degrees
MIN_BLOCK_M2, MIN_BLOCK_W_M = 400.0, 8.0    # a thinner or smaller piece (between a divided road's carriageways) is street
PARCEL_CLOSE_M = 6.0    # a block's parcels are closed across gaps narrower than twice this (a back lane, a slit between two parcels)
LANE_LEAST_M = 3.0      # a lane is at least this wide: a road's carriageway is never inside a block
PARCEL_SHARE = 0.8      # ... if they cover at least this share of the block the roads give; else (a park, a rail yard) that block stays


def _city(con):
    (path,) = con.execute("SELECT path FROM duckdb_databases() WHERE database_name = current_database()").fetchone()
    city = path[:-len(".space.duckdb")] + ".vancouver.json" if path and path.endswith(".space.duckdb") else None
    return json.load(open(city)) if city and os.path.exists(city) else {}


def city_blocks(con):
    """space.city_block: a city's own block outlines, kept only to cross-check ours (B6)."""
    con.execute("CREATE OR REPLACE TABLE space.city_block (city_block_id VARCHAR, geometry GEOMETRY)")
    fc = (_city(con).get("block-outlines") or {}).get("features", [])
    rows = []
    for f in fc:
        pt = (f.get("properties") or {}).get("geo_point_2d") or {}
        if f.get("geometry") and pt:        # the city gives its blocks no id: their centre point is one
            rows.append((f"cb{pt['lon']:.5f}{pt['lat']:+.5f}", json.dumps(f["geometry"])))
    if rows:
        con.executemany("INSERT INTO space.city_block VALUES (?, ST_MakeValid(ST_GeomFromGeoJSON(?)))", rows)
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

    con.execute("""CREATE OR REPLACE TABLE space.block (block_id VARCHAR, level INT, area_m2 DOUBLE, source VARCHAR, method VARCHAR,
                   geometry GEOMETRY)""")
    con.execute("""CREATE OR REPLACE TABLE space.block_side (block_id VARCHAR, way_id BIGINT, name VARCHAR, class VARCHAR,
                   distance_m DOUBLE, basis VARCHAR, method VARCHAR, unpulled_m DOUBLE, building VARCHAR)""")
    city_blocks(con)
    area = [g(w) for (w,) in rows(f"SELECT {m()} FROM osm_boundary")]
    box = shapely.union_all(area) if area else shapely.box(*shapely.union_all(
        [g(w) for (w,) in rows(f"SELECT {m()} FROM space.element")]).bounds)
    con.execute("CREATE OR REPLACE TABLE space.area (geometry GEOMETRY)")
    con.execute(f"INSERT INTO space.area VALUES (ST_Transform(ST_GeomFromWKB(?), '{epsg}', 'EPSG:4326', always_xy := true))", [shapely.to_wkb(box)])

    # bounding roads; a deck at level 1 bounds blocks only where nothing at ground level passes under it (works, not a bridge)
    cand = [(cl, n, oid, g(w), lv) for cl, n, oid, w, lv in rows(f"""SELECT class, name, osm_id, {m()}, level_min FROM space.element
              WHERE type IN ('road', 'walkway') AND replace(class, '_link', '') IN {STREET} AND level_min IN (0, 1)""")]
    ground_lines = [x for *_, x, lv in cand if lv == 0] + [g(w) for (w,) in rows(
        f"SELECT {m()} FROM space.element WHERE type = 'rail' AND level_min = 0")]
    gtree = shapely.STRtree(ground_lines)
    roads = [(cl, n, oid, x) for cl, n, oid, x, lv in cand if lv == 0 or not any(ground_lines[k].crosses(x) for k in gtree.query(x))]
    if not roads:
        return 0
    side = [g(w) for (w,) in rows(f"""SELECT {m()} FROM space.element WHERE type = 'walkway' AND level_min = 0
                                     AND coalesce(subtype, '') <> 'crossing'""")]
    stree = shapely.STRtree(side)
    pmeta = rows(f"SELECT parcel_id, {m()} FROM space.parcel")
    parcels = [g(w) for _, w in pmeta]
    ptree = shapely.STRtree(parcels) if parcels else None
    PU = shapely.union_all(parcels) if parcels else None
    PUin = PU.buffer(-0.1) if PU is not None else None
    bmeta = rows(f"""SELECT {m()}, source, coalesce(CAST(osm_id AS VARCHAR), source_id) FROM space.element
                     WHERE type = 'building' AND level_min <= 0 AND level_max >= 0""")
    blds = [g(r[0]) for r in bmeta]
    btree = shapely.STRtree(blds)

    # chains: the bounding roads joined between junctions
    rtree = shapely.STRtree([x for *_, x in roads])
    chains = []
    for x in shapely.get_parts(shapely.line_merge(shapely.union_all([x for *_, x in roads]))):
        if x.length < 1:
            continue
        k = max(rtree.query(x), key=lambda k: roads[k][3].intersection(x.buffer(0.1)).length)
        chains.append(dict(geom=x.simplify(SIMPLIFY_M), cl=roads[k][0], name=roads[k][1]))

    def side_width(ch, sg, f):
        """One distance for a street side (sg 1 = left, -1 = right of the chain) inside face f: (distance, basis, method, unpulled,
        building)."""
        x, cl = ch["geom"], ch["cl"].replace("_link", "")
        cap = HIT_CAP * HALF_ROW.get(cl, 10)
        n = max(2, int(x.length // STEP_M))
        par, sw, nray = [], [], 0
        for i in range(n):
            t = x.length * (i + .5) / n
            a, b = x.interpolate(max(t - 1, 0)), x.interpolate(min(t + 1, x.length))
            dx, dy = b.x - a.x, b.y - a.y
            h = (dx * dx + dy * dy) ** .5 or 1
            q = x.interpolate(t)
            ray = shapely.LineString([(q.x, q.y), (q.x - sg * dy / h * REACH_M, q.y + sg * dx / h * REACH_M)]).intersection(f)
            if ray.is_empty:
                continue
            nray += 1
            if PU is not None and not PUin.contains(q):
                hit = ray.intersection(PU)
                if not hit.is_empty and q.distance(hit) <= cap:
                    par.append(q.distance(hit))
            hits = []
            for k in stree.query(ray):
                hit = side[k].intersection(ray)
                if hit.is_empty:
                    continue
                hp = hit if hit.geom_type == "Point" else shapely.get_parts(hit)[0]
                hp = hp if hp.geom_type == "Point" else shapely.Point(hp.coords[0])
                tt = side[k].project(hp)
                a2, b2 = side[k].interpolate(max(tt - 1, 0)), side[k].interpolate(min(tt + 1, side[k].length))
                ex, ey = b2.x - a2.x, b2.y - a2.y
                if abs(dx * ex + dy * ey) / (h * ((ex * ex + ey * ey) ** .5 or 1)) >= ALONG_COS and q.distance(hp) + SIDEWALK_BACK_M <= cap:
                    hits.append(q.distance(hp))
            if hits:
                sw.append(min(hits) + SIDEWALK_BACK_M)
        if nray and len(par) >= max(2, nray / 2):
            d, basis, method = statistics.median(par), "parcels", "measured"
        elif len(sw) >= 3:
            d, basis, method = statistics.median(sw), "sidewalks", "measured"
        else:
            d, basis, method = float(HALF_ROW.get(cl, 10)), "class", "chosen"
        zone = x.buffer(sg * REACH_M, single_sided=True).intersection(f)
        near = [(x.distance(blds[k].intersection(zone)), k) for k in btree.query(zone)
                if blds[k].intersects(zone) and not blds[k].intersects(x)]
        bd, bk = min(near, default=(1e9, None))
        # a plot is like a building: the street ends at its line, never inside it (a parcel the road line itself crosses is no limit)
        pnear = [(x.distance(parcels[k].intersection(zone)), k) for k in (ptree.query(zone) if ptree is not None else [])
                 if parcels[k].intersects(zone) and not parcels[k].intersects(x) and not parcels[k].intersection(zone).is_empty]
        pd, pk = min(pnear, default=(1e9, None))
        if basis == "parcels":      # a surveyed property line is the edge: an OSM outline (drawn from photos, often shifted) does not move it
            bd = 1e9
        if min(bd, pd) < d:
            if bd <= pd:    # the street ends at a wall, never inside a building
                return round(bd, 2), "building", "measured", round(d, 2), f"{bmeta[bk][1]}:{bmeta[bk][2]}"
            return round(pd, 2), "parcel", "measured", round(d, 2), f"vancouver:{pmeta[pk][0]}"
        return round(d, 2), basis, method, None, None

    def extend(x, e, ends):
        c = list(x.coords)
        def out(p, q):
            dx, dy = p[0] - q[0], p[1] - q[1]
            h = (dx * dx + dy * dy) ** .5 or 1
            return (p[0] + dx / h * e, p[1] + dy / h * e)
        if 0 in ends:
            c = [out(c[0], c[1])] + c
        if -1 in ends:
            c = c + [out(c[-1], c[-2])]
        return shapely.LineString(c)

    def left_of(x, f):
        """Whether face f lies left of line x, tested at the middle of x's stretch along f."""
        here = x.intersection(f.boundary.buffer(0.05))
        here = max((p for p in shapely.get_parts(here) if p.geom_type == "LineString"), key=lambda p: p.length, default=x)
        mid = x.interpolate(x.project(here.interpolate(0.5, normalized=True)))
        a, b = x.interpolate(max(x.project(mid) - 1, 0)), x.interpolate(min(x.project(mid) + 1, x.length))
        dx, dy = b.x - a.x, b.y - a.y
        h = (dx * dx + dy * dy) ** .5 or 1
        return {sg for sg in (1, -1) if shapely.Point(mid.x - sg * dy / h * 0.5, mid.y + sg * dx / h * 0.5).within(f)}

    ctree = shapely.STRtree([ch["geom"] for ch in chains])
    lines = shapely.union_all([ch["geom"] for ch in chains] + [box.exterior])
    faces = [f for f in shapely.get_parts(shapely.polygonize(list(shapely.get_parts(shapely.line_merge(lines))))) if f.within(box.buffer(0.1))]
    out = []        # (block geometry, its sides [(chain, side row)], face)
    for f in faces:
        fb = f.boundary.buffer(0.05)
        strips, srows = [], []
        for j in ctree.query(f.buffer(0.1)):
            ch = chains[j]
            x = ch["geom"]
            on_edge = x.intersection(fb).length > 1
            inside = x.intersection(f.buffer(-0.1)).length > 1
            if not on_edge and not inside:
                continue
            sgs = [1, -1] if inside else sorted(left_of(x, f))
            if not sgs:
                continue
            ends = [e for e, p in ((0, x.coords[0]), (-1, x.coords[-1])) if shapely.Point(p).distance(f.boundary) < 0.05]
            ds = []
            for sg in sgs:
                r = side_width(ch, sg, f)
                ds.append(r[0])
                # the edge line runs on past a junction, so two edges meet in a corner, as two parallel offsets do
                strips.append(extend(x, 2 * REACH_M, ends).buffer(sg * r[0], single_sided=True))
                srows.append((j, r))
            for e in (0, -1):
                if e not in ends:       # a dead end inside the face
                    strips.append(shapely.Point(x.coords[e]).buffer(max(ds)))
        b = poly(f.difference(shapely.union_all(strips) if strips else shapely.Polygon(), grid_size=0.01))
        for p in shapely.get_parts(b):
            if p.area >= MIN_BLOCK_M2 and p.buffer(-MIN_BLOCK_W_M / 2).area > 0:
                out.append((p, srows, f))

    # where a city has parcels, a block is its face's parcels joined and closed across every gap narrower than 2 x PARCEL_CLOSE_M (a back
    # lane, a slit): its edge is the parcels' front. A face whose parcels cover less than PARCEL_SHARE of its block (a park, a rail yard
    # with no parcel) keeps the block from the roads
    by_face = {}
    for p, srows, f in out:
        by_face.setdefault(id(f), (f, srows, []))[2].append(p)
    out, from_parcels = [], set()
    # a bounding road's carriageway is street, even where the city's parcels cover it: OSM's lanes (else one each way), each
    # LANE_LEAST_M wide at least, either side of its line
    tags = {o: (ln, ow) for o, ln, ow in rows("""SELECT osm_id, tags['lanes'], tags['oneway'] FROM osm.raw.ways
                                                 WHERE osm_id IN (SELECT DISTINCT osm_id FROM space.element WHERE type = 'road')""")}
    def lanes_of(oid):
        ln, ow = tags.get(oid, (None, None))
        try:
            return max(1, int(float(str(ln).split(";")[0])))
        except (TypeError, ValueError):
            return 1 if ow in ("yes", "-1") else 2
    carriage = shapely.union_all([x.buffer(lanes_of(oid) * LANE_LEAST_M / 2, cap_style="flat") for cl, n, oid, x in roads])
    for f, srows, road_blocks in by_face.values():
        mine = [parcels[k] for k in (ptree.query(f) if ptree is not None else []) if parcels[k].intersection(f).area > 0.5 * parcels[k].intersection(box).area]   # (a parcel cut by the area's edge: its part inside)
        joined = poly(shapely.union_all(mine).buffer(PARCEL_CLOSE_M, join_style="mitre").buffer(-PARCEL_CLOSE_M, join_style="mitre")
                      .intersection(f, grid_size=0.01).difference(carriage, grid_size=0.01)) if mine else shapely.Polygon()
        if mine and joined.area >= PARCEL_SHARE * sum(b.area for b in road_blocks):
            for q in shapely.get_parts(joined):
                if q.area >= MIN_BLOCK_M2 and q.buffer(-MIN_BLOCK_W_M / 2).area > 0:
                    out.append((shapely.Polygon(q.exterior), srows, f))     # (a hole would be a courtyard: still the block's)
                    from_parcels.add(len(out) - 1)
        else:
            out += [(b, srows, f) for b in road_blocks]

    # ids: the smallest OSM way among the bounding roads and the side of that way the block lies on
    ids = []
    for p, srows, f in out:
        best = None
        for cl, n, oid, x in (roads[k] for k in rtree.query(f.buffer(0.1))):
            if oid is None or x.intersection(f.boundary.buffer(0.05)).length < 1:
                continue
            sgs = left_of(x, f)
            if len(sgs) == 1 and (best is None or oid < best[0]):
                best = (oid, "l" if 1 in sgs else "r")
        ids.append(f"b0-w{best[0]}{best[1]}" if best else f"b0-x{round(p.centroid.x)}y{round(p.centroid.y)}")
    seen = {}
    order = sorted(range(len(out)), key=lambda i: (ids[i], round(out[i][0].centroid.x, 1), round(out[i][0].centroid.y, 1)))
    for i in order:
        seen[ids[i]] = seen.get(ids[i], 0) + 1
        if seen[ids[i]] > 1:
            ids[i] += f".{seen[ids[i]]}"

    if not out:
        return 0
    con.executemany(f"""INSERT INTO space.block VALUES (?, 0, ?, 'urbanstyle', 'derived',
                        ST_Transform(ST_GeomFromWKB(?), '{epsg}', 'EPSG:4326', always_xy := true))""",
                    [(i, round(p.area, 1), shapely.to_wkb(p)) for i, (p, _, _) in zip(ids, out)])
    side_rows = []
    for n_, (i, (p, srows, f)) in enumerate(zip(ids, out)):
        for j, (d, basis, method, unpulled, bld) in srows:
            ch = chains[j]
            if n_ in from_parcels:      # the edge is the parcels' front: its distance from the road, as measured
                d, basis, method, unpulled, bld = round(ch["geom"].distance(p), 2), "parcels (joined)", "measured", None, None
            if ch["geom"].distance(p) > d + 1:      # a side of the face that this piece of it does not reach
                continue
            way = min((oid for cl, n, oid, x in (roads[k] for k in rtree.query(ch["geom"].buffer(0.5)))
                       if oid is not None and x.intersection(ch["geom"].buffer(0.5)).length > 1), default=None)
            side_rows.append((i, way, ch["name"], ch["cl"], d, basis, method, unpulled, bld))
    if side_rows:
        con.executemany("INSERT INTO space.block_side VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", side_rows)
    return len(out)
