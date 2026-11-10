"""Blocks from SimReady's street face (docs/notes/simready-input.md, "The blocks from SimReady's street face"). The same tables as
blocks.py (work.block, work.block_side, work.corridor, work.area, work.city_block), for a build with --simready: SimReady builds the
street by the block method (its decision D28), so the blocks are not made twice. blocks.py stays for a build with no SimReady.

    street     SimReady's ground face and its roundabouts' faces at level 0 (simready.read), less the strips of the drives (an unnamed
               service way is no street, blocks.street_sql): their lanes and DRIVE_BUF_M, except within DRIVE_KEEP_M of a street's
               lanes or junction areas, where the driveway crosses the pedestrian side
    blocks     the area less the street; a piece under MIN_BLOCK_M2 or thinner than MIN_BLOCK_W_M is street (as blocks.py); a piece cut
               by the area's edge is kept from EDGE_BLOCK_M2. Id b0-w<smallest way><l|r>, `.2` ... where the id repeats
    sides      one row per OSM way of a street carriageway within SIDE_REACH_M of a block: the median distance from its line
    corridors  each pedestrian way (blocks.path_sql) that does not run along a street's lanes within SIDEWALK_ZONE_M: a strip of its width
               inside the street, less the lanes and the junction areas. Id c0-w<way>
"""
STEP_M = 5.0              # the carriageways' lines are measured this often for the sides
SIDE_REACH_M = 25.0       # a block is a side of a road when it lies within this of it
DRIVE_BUF_M = 4.0         # a drive's own strip: its lanes and the kerb (chosen)
DRIVE_KEEP_M = 7.0        # within this of a street's lanes or junction areas a drive's strip stays street: the driveway across the pedestrian side (chosen)
EDGE_BLOCK_M2 = 10.0      # a block cut by the area's edge is kept from this size: the edge is the clip, not a street


from . import bulk


def build(con, epsg, simready):
    import statistics
    import time
    _t = [time.time()]

    def tick(label):
        print(f"  blocks: {label} {time.time() - _t[0]:.0f} s", flush=True)
        _t[0] = time.time()
    import duckdb
    import shapely
    import shapely.ops
    from .blocks import PATH_W, SIDEWALK_ZONE_M, MIN_BLOCK_M2, city_blocks, path_sql, wide
    from . import simready as sr

    m = lambda col="geometry": f"ST_AsWKB(ST_Transform({col}, 'EPSG:4326', '{epsg}', always_xy := true))"
    g = lambda w: shapely.make_valid(shapely.from_wkb(bytes(w)))
    # (a polygon or a multipolygon is as it is: the union of its parts, made again, took 43 ms for each big operand of an overlay)
    poly = lambda x: x if x.geom_type in ("Polygon", "MultiPolygon") else shapely.union_all(
        [p for q in shapely.get_parts(x) for p in shapely.get_parts(q) if p.geom_type == "Polygon"] or [shapely.Polygon()])
    D = lambda a, b: shapely.difference(poly(a), poly(b), grid_size=0.01)         # (polygons only, on a 1 cm grid: SimReady's polygons share edges)
    I = lambda a, b: shapely.intersection(poly(a), poly(b), grid_size=0.01)
    to_ll = f"ST_Transform(ST_GeomFromWKB(?), '{epsg}', 'EPSG:4326', always_xy := true)"

    def rows(sql):
        try:
            return con.execute(sql).fetchall()
        except duckdb.CatalogException:
            return []
    con.execute("""CREATE OR REPLACE TABLE work.block (block_id VARCHAR, level INT, area_m2 DOUBLE, source VARCHAR, method VARCHAR,
                   geometry GEOMETRY)""")
    con.execute("""CREATE OR REPLACE TABLE work.block_side (block_id VARCHAR, way_id BIGINT, name VARCHAR, class VARCHAR,
                   distance_m DOUBLE, basis VARCHAR, method VARCHAR, unpulled_m DOUBLE, building VARCHAR)""")
    con.execute("""CREATE OR REPLACE TABLE work.corridor (corridor_id VARCHAR, way_id BIGINT, name VARCHAR, class VARCHAR, width_m DOUBLE,
                   width_source VARCHAR, width_method VARCHAR, geometry GEOMETRY)""")
    city_blocks(con)
    area = [g(w) for (w,) in rows(f"SELECT {m()} FROM osm_boundary")]
    box = shapely.union_all(area) if area else shapely.box(*shapely.union_all([g(w) for (w,) in rows(f"SELECT {m()} FROM work.element")]).bounds)
    con.execute("CREATE OR REPLACE TABLE work.area (geometry GEOMETRY)")
    con.execute(f"INSERT INTO work.area VALUES ({to_ll})", [shapely.to_wkb(box)])

    # ---- the street: SimReady's face less the drives' strips
    tick("the area")
    r = sr.read(con, epsg, simready, box)
    tick("read SimReady's face")
    street_zone = shapely.union_all([r["lanes"], r["junctions"]])
    drives = poly(D(r["drives"].buffer(DRIVE_BUF_M), street_zone.buffer(DRIVE_KEEP_M)))
    face = poly(D(r["face"], drives))
    # (the street holds SimReady's own roadway: its lanes and junction areas that its face leaves out, a few m2 each, mostly a junction area
    # at a node on a road that SimReady has in a cutting or a tunnel. A space is cut from rank 1's street, check B7)
    roadway = poly(I(shapely.union_all([r["lanes"], r["junctions"]]), box))
    outside = poly(D(roadway, face))
    face = poly(shapely.union_all([face, roadway]))

    tick("the street")
    # ---- the blocks: the area less the street; a thin or small piece is street
    edge = box.boundary.buffer(0.05)
    pieces = []
    for q in shapely.get_parts(poly(D(box, face))):
        if q.geom_type != "Polygon" or q.is_empty:
            continue
        cut = q.boundary.intersection(edge).length > 1.0           # (cut by the area's edge)
        for p in shapely.get_parts(wide(q) if not cut else q):
            if p.geom_type == "Polygon" and p.area >= (EDGE_BLOCK_M2 if cut else MIN_BLOCK_M2):
                pieces.append(p)
    blocks = pieces
    street = poly(D(box, shapely.union_all(blocks or [shapely.Polygon()])))

    tick("the blocks")
    # ---- the sides: for each street carriageway, its line every STEP_M, the nearest block within SIDE_REACH_M
    sides = {}                    # (block, way) -> [distances]
    meta = {}                     # way -> (name, class, a line)
    pts, owner = [], []
    for c in r["streets"]:
        ln = c["line"].intersection(box)
        for part in shapely.get_parts(ln):
            if part.geom_type != "LineString" or part.length < 1:
                continue
            for t in [k * STEP_M for k in range(int(part.length // STEP_M) + 1)] + [part.length]:
                pts.append(part.interpolate(t)); owner.append(c["way"])
            meta.setdefault(c["way"], (c["name"], c["cl"], part))
    if blocks and pts:
        tree = shapely.STRtree(blocks)
        idx, dist = tree.query_nearest(pts, max_distance=SIDE_REACH_M, return_distance=True, all_matches=False)
        for i, b, d in zip(idx[0], idx[1], dist):
            sides.setdefault((int(b), owner[int(i)]), []).append(float(d))
    by_block = {}
    for (b, way), ds in sides.items():
        by_block.setdefault(b, []).append((way, round(statistics.median(ds), 2)))
    side_rows, block_rows, used = [], [], {}
    for b, q in enumerate(blocks):
        ws = sorted(by_block.get(b, []))
        if ws:
            way = ws[0][0]; line = meta[way][2]
            nq = shapely.ops.nearest_points(line, q)[1]
            s_ = line.project(nq); a_, b_ = line.interpolate(max(s_ - 1, 0)), line.interpolate(min(s_ + 1, line.length))
            left = (b_.x - a_.x) * (nq.y - a_.y) - (b_.y - a_.y) * (nq.x - a_.x) > 0
            bid = f"b0-w{way}{'l' if left else 'r'}"
        else:
            bid = f"b0-e{b}"
        used[bid] = used.get(bid, 0) + 1
        bid += f".{used[bid]}" if used[bid] > 1 else ""
        block_rows.append((bid, round(q.area, 1), shapely.to_wkb(q)))
        side_rows += [(bid, way, meta[way][0], meta[way][1], d, "simready face", "derived", None, None) for way, d in ws]
    if block_rows:
        bulk.executemany(con, f"INSERT INTO work.block VALUES (?, 0, ?, 'simready', 'derived', {to_ll})", [(a, b, c) for a, b, c in block_rows])
    if side_rows:
        bulk.executemany(con, "INSERT INTO work.block_side VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", side_rows)

    tick("the sides")
    # ---- the corridors: each pedestrian way that is no sidewalk, a strip of its width inside the street, less the roadway
    paths_ = [(cl, n, oid, g(w), wd) for cl, n, oid, w, wd in rows(f"""SELECT any_value(e.class), any_value(e.name), e.osm_id,
              {m('ST_Union_Agg(e.geometry)')}, max(try_cast(w.tags['width'] AS DOUBLE)) FROM work.element e LEFT JOIN osm.raw.ways w USING (osm_id)
              WHERE {path_sql('e')} AND coalesce(w.tags['area'], 'no') <> 'yes' GROUP BY e.osm_id""")]
    zone = r["lanes"].buffer(SIDEWALK_ZONE_M)
    corridors, seen = [], {}
    for cl, n, oid, x, wd in paths_:
        if x.length and x.intersection(zone).length > 0.5 * x.length:
            continue                                               # (a sidewalk, not a path)
        wid, src, meth = (wd, "osm", "mapped") if wd else (PATH_W[cl], "urbanstyle", "chosen")
        q = poly(D(I(x.buffer(wid / 2), street), roadway))
        if q.is_empty or q.area < 0.5:
            continue
        cid = f"c0-w{oid}"
        seen[cid] = seen.get(cid, 0) + 1
        corridors.append((cid + (f".{seen[cid]}" if seen[cid] > 1 else ""), oid, n, cl, wid, src, meth, shapely.to_wkb(q)))
    if corridors:
        bulk.executemany(con, f"INSERT INTO work.corridor VALUES (?, ?, ?, ?, ?, ?, ?, {to_ll})", corridors)
    tick("the corridors")
    print(f"  blocks: {len(block_rows)} from SimReady's face, {len(corridors)} corridors; the street {street.area:,.0f} m2; SimReady's roadway outside its face: {outside.area:,.0f} m2", flush=True)
    return len(block_rows)
