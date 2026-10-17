"""Blocks (docs/design/blocks.md, step 1): the land between the streets at level 0, from which the street is divided.

    bounding roads  OSM's public streets at level 0 (STREET, with their links); a road on a deck at level 1 only where nothing at ground
                    level passes under it; and the pedestrian ways (PATH_W, docs/design/paths.md), each side at half its width.
                    Service roads (alleys, driveways, parking aisles), the other footways and rail lie inside blocks
    chains          the bounding roads joined end to end between junctions, simplified by SIMPLIFY_M
    faces           the areas the chains enclose, closed by the edge of the area (the clip's box)
    street side     each side of a chain within a face gets one distance from the road line, so the block's edge there runs parallel to
                    the road: OSM's sidewalks + SIDEWALK_BACK_M, else MIN_EDGE_M behind the carriageway; pulled in to the nearest
                    building; a building is drawn whole even where its OSM outline reaches over the line. A city's parcels
                    (`urban.parcel`) set no edge, pull nothing in and replace no block (Kaveh, 2026-10-16: "don't use the parcels at all")
    block           what is left of a face: its parts at least MIN_BLOCK_W_M wide, if at least MIN_BLOCK_M2; corners are sharp (each edge line runs on
                    past the junction)

urban.block       block_id, level, area_m2, source, method, geometry. Id `b<level>-w<way><side>`: the smallest OSM way among its bounding
                  roads and the side of that way it lies on (l / r), `.2`, `.3` ... where one way bounds several blocks on that side
urban.block_side  one row per street side of a block: the way, the distance and what set it (`basis`: sidewalks, carriageway, path
                  width or building), the distance before a building pulled it in, that building
urban.corridor    each pedestrian way's own ground between the blocks (paths.md rule 3, at rank 1: the way's width, up to the roads'
                  carriageways), id `c0-w<way>`; the road's street never takes it (network.py), the ground's kind `path` is it
urban.area        the edge of the area (the clip's box), for the checks
urban.city_block  a city's own block outlines (Vancouver `block-outlines`), only to cross-check ours (check B6), never as input
"""
import json
import os
import statistics

STREET = ("motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street")


def street_sql(e="e"):
    """SQL: the road `e` (a urban.element) is a street: a street class, with its links, or a service road that carries a street's name
    and no service=* kind (its subtype). Monaco tags whole quays and boulevard pieces as service, 39 ways, 3.5 km: Boulevard Albert
    1er, Quai Antoine 1er, Avenue des Ligures (Kaveh, 2026-10-16). An unnamed service road, an alley, a driveway, a parking aisle
    stays a service road: a driveway across the pedestrian side, no space of its own (docs/design/street-rules.md)."""
    return (f"(replace(coalesce({e}.class, ''), '_link', '') IN {STREET} OR ({e}.type = 'road' AND {e}.class = 'service' "
            f"AND {e}.name IS NOT NULL AND {e}.subtype IS NULL))")     # (a road: a named service way cars cannot use, a pedestrian allée, is no street)
# a pedestrian way cuts the blocks like a road, as wide as OSM says, else PATH_W (docs/design/paths.md rules 1-2, the trial of 2026-10-16;
# before it, 2026-10-14, a pedestrian street lay inside its block as a footway does): a pedestrian street, a footway, steps or a path,
# named or not (Kaveh, 2026-10-16: "footway is part of paths in rank 1"); not a crossing, not a sidewalk (tagged, or running along a road
# inside its sidewalk zone: build() leaves those out), not a pedestrian area (a square)
PATH_W = {"pedestrian": 4.0, "footway": 3.0, "steps": 3.0, "path": 3.0}


def path_sql(e="e"):
    """SQL: the walkway `e` (a urban.element at level 0) is a pedestrian way that cuts the blocks (PATH_W)."""
    return (f"({e}.type = 'walkway' AND {e}.level_min = 0 AND coalesce({e}.subtype, '') NOT IN ('crossing', 'sidewalk') AND NOT {street_sql(e)} "
            f"AND {e}.class IN ('pedestrian', 'footway', 'steps', 'path'))")


HALF_ROW = {"motorway": 18, "trunk": 16, "primary": 15, "secondary": 12, "tertiary": 10, "unclassified": 10, "residential": 10,
            "living_street": 8, "pedestrian": 10}  # half right-of-way by class (the cap of a sidewalk hit, HIT_CAP; chosen)
SIMPLIFY_M = 1.0        # OSM's small wiggles are not the street's shape
STEP_M = 2.5            # lines square to the road, every (a block's edge follows the sidewalks at this step)
REACH_M = 25.0          # looked for out to
HIT_CAP = 1.5           # a sidewalk counts within this many times the class's half right-of-way (not the next street's)
SIDEWALK_BACK_M = 1.0   # a sidewalk is drawn along its middle: the property line is about this far behind it
EDGE_SIMPLIFY_M = 0.0   # a block edge that follows a footway is the footway's own shape (Kaveh, 2026-10-16: no simplification; 0.5 m until then)
ALONG_COS = 0.82        # a sidewalk runs along the road: within ~35 degrees
CORNER_M = 0.0          # the edge follows the sidewalks to the junction too, round the corner as the line curves (Kaveh, 2026-10-16: the
                        # sidewalk line is the kerb data at a corner; until then 10 m: a sharp corner, as the city's blocks have)
SIDEWALK_ZONE_M = 8.0   # a footway is a street's sidewalk only this near its carriageway: room for a parking lane and a verge (chosen)
MIN_EDGE_M = 1.5        # a side with nothing that sets it ends this far behind the carriageway (chosen: the kerb and a strip)
LANE_M = 3.25           # a lane where OSM gives no width (as network.py)
ROOF_M = 1.5            # a building pulls the street's edge in only by more than this: a roof reaches about this far over the wall
                        # (Avenue Pasteur, Monaco: the footprint of w49209427 is its roof, over the sidewalk; Kaveh, 2026-10-13)
MIN_BLOCK_M2, MIN_BLOCK_W_M = 400.0, 8.0    # a thinner or smaller piece (between a divided road's carriageways) is street
MIN_PLOT_M2, MIN_PLOT_W_M = 10.0, 2.0       # a piece the paths' cuts leave under this (a sliver between two footways 3 m apart) is no plot: it
                                            # joins the corridor it shares the most edge with (b0-w336755750l.9, 6 m2; Kaveh, 2026-10-16)
LANE_LEAST_M = 3.0      # a lane is at least this wide: a road's carriageway is never inside a block


def _city(con):
    (path,) = con.execute("SELECT path FROM duckdb_databases() WHERE database_name = current_database()").fetchone()
    city = path[:-len(".urban.duckdb")] + ".vancouver.json" if path and path.endswith(".urban.duckdb") else None
    return json.load(open(city)) if city and os.path.exists(city) else {}


def city_blocks(con):
    """urban.city_block: a city's own block outlines, kept only to cross-check ours (B6)."""
    con.execute("CREATE OR REPLACE TABLE urban.city_block (city_block_id VARCHAR, geometry GEOMETRY)")
    fc = (_city(con).get("block-outlines") or {}).get("features", [])
    rows = []
    for f in fc:
        pt = (f.get("properties") or {}).get("geo_point_2d") or {}
        if f.get("geometry") and pt:        # the city gives its blocks no id: their centre point is one
            rows.append((f"cb{pt['lon']:.5f}{pt['lat']:+.5f}", json.dumps(f["geometry"])))
    if rows:
        con.executemany("INSERT INTO urban.city_block VALUES (?, ST_MakeValid(ST_GeomFromGeoJSON(?)))", rows)
    return len(rows)


def wide(b):
    """The parts of b at least MIN_BLOCK_W_M wide: a thinner tail (the strip between the two ways of a one-way pair) is street."""
    import shapely
    w = b.buffer(-MIN_BLOCK_W_M / 2, join_style="mitre").buffer(MIN_BLOCK_W_M / 2, join_style="mitre").intersection(b)
    return shapely.union_all([q for q in shapely.get_parts(w) if q.geom_type == "Polygon"] or [shapely.Polygon()])


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

    con.execute("""CREATE OR REPLACE TABLE urban.block (block_id VARCHAR, level INT, area_m2 DOUBLE, source VARCHAR, method VARCHAR,
                   geometry GEOMETRY)""")
    con.execute("""CREATE OR REPLACE TABLE urban.block_side (block_id VARCHAR, way_id BIGINT, name VARCHAR, class VARCHAR,
                   distance_m DOUBLE, basis VARCHAR, method VARCHAR, unpulled_m DOUBLE, building VARCHAR)""")
    con.execute("""CREATE OR REPLACE TABLE urban.corridor (corridor_id VARCHAR, way_id BIGINT, name VARCHAR, class VARCHAR, width_m DOUBLE,
                   width_source VARCHAR, width_method VARCHAR, geometry GEOMETRY)""")
    city_blocks(con)
    area = [g(w) for (w,) in rows(f"SELECT {m()} FROM osm_boundary")]
    box = shapely.union_all(area) if area else shapely.box(*shapely.union_all(
        [g(w) for (w,) in rows(f"SELECT {m()} FROM urban.element")]).bounds)
    con.execute("CREATE OR REPLACE TABLE urban.area (geometry GEOMETRY)")
    con.execute(f"INSERT INTO urban.area VALUES (ST_Transform(ST_GeomFromWKB(?), '{epsg}', 'EPSG:4326', always_xy := true))", [shapely.to_wkb(box)])

    # bounding roads; a deck at level 1 bounds blocks only where nothing at ground level passes under it (works, not a bridge)
    cand = [(cl, n, oid, g(w), lv) for cl, n, oid, w, lv in rows(f"""SELECT class, name, osm_id, {m()}, level_min FROM urban.element e
              WHERE type IN ('road', 'walkway') AND {street_sql('e')} AND level_min IN (0, 1)""")]
    ground_lines = [x for *_, x, lv in cand if lv == 0] + [g(w) for (w,) in rows(
        f"SELECT {m()} FROM urban.element WHERE type = 'rail' AND level_min = 0")]
    gtree = shapely.STRtree(ground_lines)
    roads = [(cl, n, oid, x) for cl, n, oid, x, lv in cand if lv == 0 or not any(ground_lines[k].crosses(x) for k in gtree.query(x))]
    # a bounding road's carriageway is street: OSM's lanes (else one each way), each
    # LANE_LEAST_M wide at least, either side of its line
    tags = {o: (ln, ow) for o, ln, ow in rows("""SELECT osm_id, tags['lanes'], tags['oneway'] FROM osm.raw.ways
                                                 WHERE osm_id IN (SELECT DISTINCT osm_id FROM urban.element WHERE type = 'road')""")}
    def lanes_of(oid):
        ln, ow = tags.get(oid, (None, None))
        try:
            return max(1, int(float(str(ln).split(";")[0])))
        except (TypeError, ValueError):
            return 1 if ow in ("yes", "-1") else 2
    road_cw = shapely.union_all([x.buffer(lanes_of(oid) * LANE_LEAST_M / 2, cap_style="flat") for cl, n, oid, x in roads] or [shapely.Polygon()])
    # the pedestrian ways, one per OSM way, each with its width (paths.md rules 1-2); they cut the faces and the blocks as the
    # roads do. One that runs along a road inside its sidewalk zone (over half its length) is that road's sidewalk, not a path
    paths_ = [(cl, n, oid, g(w), wd) for cl, n, oid, w, wd in rows(f"""SELECT any_value(e.class), any_value(e.name), e.osm_id,
              {m('ST_Union_Agg(e.geometry)')}, max(try_cast(w.tags['width'] AS DOUBLE)) FROM urban.element e LEFT JOIN osm.raw.ways w USING (osm_id)
              WHERE {path_sql('e')} AND coalesce(w.tags['area'], 'no') <> 'yes' GROUP BY e.osm_id""")]     # (a pedestrian area is a square, ground.py)
    # (the zone of the roads near each way, from a spatial index: the union's buffer recomputed for every way took Monaco's blocks step
    # from 2 minutes to over 25)
    cw_parts = list(shapely.get_parts(road_cw))
    cw_tree = shapely.STRtree(cw_parts) if cw_parts else None
    def in_zone(x):
        near_ = [cw_parts[k] for k in (cw_tree.query(x.buffer(SIDEWALK_ZONE_M)) if cw_tree is not None else [])]
        return x.intersection(shapely.union_all(near_).buffer(SIDEWALK_ZONE_M)).length if near_ else 0.0
    paths_ = [p for p in paths_ if in_zone(p[3]) <= 0.5 * p[3].length]
    pw = {oid: ((wd, "osm", "mapped") if wd else (PATH_W[cl], "urbanstyle", "chosen")) for cl, n, oid, x, wd in paths_}
    roads += [(cl, n, oid, x) for cl, n, oid, x, wd in paths_]
    if not roads:
        return 0
    # (a road of a street class is never a footway line, whatever its type: a private road duckOSM puts in the walking network only
    # measured its own centre line as its sidewalk, and its street came out 2 m wide; Route de l'Hopital w257071677, Kaveh, 2026-10-14)
    side = [g(w) for o, w in rows(f"""SELECT osm_id, {m()} FROM urban.element e WHERE type = 'walkway' AND level_min = 0
                                     AND coalesce(subtype, '') <> 'crossing' AND NOT {street_sql('e')}""") if o not in pw]
    stree = shapely.STRtree(side)
    bmeta = rows(f"""SELECT {m()}, source, coalesce(CAST(osm_id AS VARCHAR), source_id) FROM urban.element
                     WHERE type = 'building' AND level_min <= 0 AND level_max >= 0""")
    blds = [g(r[0]) for r in bmeta]
    btree = shapely.STRtree(blds)

    # chains: the bounding roads joined between junctions (a road within STRAIGHT_M of straight is straight, as network.py draws it)
    from .network import straight
    rtree = shapely.STRtree([x for *_, x in roads])
    chains = []
    # (the roads and the paths chained apart: a path that ends on a road is its own chain, with its own width)
    for group in ([x for cl, *_, x in roads if cl not in PATH_W], [x for cl, *_, x in roads if cl in PATH_W]):
        for x in (shapely.get_parts(shapely.line_merge(shapely.union_all(group))) if group else []):
            if x.length < 1:
                continue
            k = max(rtree.query(x), key=lambda k: roads[k][3].intersection(x.buffer(0.1)).length)
            chains.append(dict(geom=straight(x.simplify(SIMPLIFY_M)), cl=roads[k][0], name=roads[k][1], oid=roads[k][2]))

    def side_width(ch, sg, f):
        """One distance for a street side (sg 1 = left, -1 = right of the chain) inside face f: (distance, basis, method, unpulled,
        building)."""
        x, cl = ch["geom"], ch["cl"].replace("_link", "")
        if cl in PATH_W:        # a path's side: half its width (paths.md rule 2); no sidewalk, parcel or building moves it
            wd, src, meth = pw[ch["oid"]]
            return round(wd / 2, 2), "path width", meth, None, None
        cap = HIT_CAP * HALF_ROW.get(cl, 10)
        # (a footway is this street's sidewalk only within SIDEWALK_ZONE_M of its carriageway (OSM's lanes x LANE_M): a park path 10 m
        # from the kerb was taken for the sidewalk, and the park became street, s0-w37127120/1#6; Kaveh, 2026-10-14. The footway line
        # itself is measured: West 6th Avenue's footway, 5.2 m behind the lanes past parking and a verge, was left out, b0-w23189661l.6)
        oids_ = [r_[2] for r_ in (roads[k] for k in rtree.query(x.buffer(0.5))) if r_[2] is not None and r_[3].intersection(x.buffer(0.5)).length > 1]
        half = max((lanes_of(o_) for o_ in oids_), default=2) * LANE_M / 2
        cap_sw = min(cap, half + SIDEWALK_ZONE_M)
        n = max(2, int(x.length // STEP_M))
        sw, nray, at = [], 0, []      # at: (t, distance) of each line that reached a sidewalk
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
                if abs(dx * ex + dy * ey) / (h * ((ex * ex + ey * ey) ** .5 or 1)) >= ALONG_COS and q.distance(hp) <= cap_sw:
                    hits.append(q.distance(hp))
            if hits:
                sw.append(min(hits) + SIDEWALK_BACK_M)
                at.append((t, sw[-1]))
        if len(sw) >= 3:            # the footways set the edge
            d, basis, method = statistics.median(sw), "sidewalks", "measured"
        else:
            d, basis, method = half + MIN_EDGE_M, "carriageway", "derived"      # (no sidewalk or building: the street ends at its
                                                                                # carriageway, MIN_EDGE_M behind it; no guessed class width)
        zone = x.buffer(sg * REACH_M, single_sided=True).intersection(f)
        near = [(x.distance(blds[k].intersection(zone)), k) for k in btree.query(zone)
                if blds[k].intersects(zone) and not blds[k].intersects(x)]
        bd, bk = min(near, default=(1e9, None))
        if d - bd <= ROOF_M:        # a building at most ROOF_M nearer does not move the edge: OSM often draws a building by its roof
            bd = 1e9
        if bd < d:                  # the street ends at a wall, never inside a building
            return round(bd, 2), "building", "measured", round(d, 2), f"{bmeta[bk][1]}:{bmeta[bk][2]}"
        return round(d, 2), basis, method, None, None, (at if basis == "sidewalks" else None)

    def follow(x, sg, at, ends, ext):
        """The street between road line x and its sidewalks on side sg: each line square to the road out to its own distance (at:
        [(t, distance)]); within CORNER_M of an end straight on at the distance there, and past each junction end (ends) by ext[end]."""
        at = sorted(at)         # each line the median of it and its neighbours: one line that reaches another path is no spike
        at = [(t, statistics.median([d_ for _, d_ in at[max(k - 1, 0):k + 2]])) for k, (t, _) in enumerate(at)]
        ts = [(t, d_) for t, d_ in at if CORNER_M <= t <= x.length - CORNER_M] or [(x.length / 2, statistics.median([d_ for _, d_ in at]))]
        ts = [(0.0, ts[0][1])] + ts + [(x.length, ts[-1][1])]
        # (every STEP_M along the road and at its bends, the distance between the lines that hit a sidewalk interpolated: straight chords
        # between those lines cut across a curve, Avenue Saint-Laurent)
        import numpy as np
        tq = sorted({round(t, 3) for t in [k * STEP_M for k in range(int(x.length // STEP_M) + 1)] + [x.length]
                     + [x.project(shapely.Point(c)) for c in x.coords]})
        ts = list(zip(tq, np.interp(tq, [t for t, _ in ts], [d_ for _, d_ in ts])))
        road, edge = [], []
        for t, d_ in ts:
            a, b = x.interpolate(max(t - 1, 0)), x.interpolate(min(t + 1, x.length))
            dx, dy = b.x - a.x, b.y - a.y
            h = (dx * dx + dy * dy) ** .5 or 1
            q = x.interpolate(t)
            road.append((q.x, q.y))
            edge.append((q.x - sg * dy / h * d_, q.y + sg * dx / h * d_))
        # (the edge simplified by EDGE_SIMPLIFY_M: straight where the footway is straight, bending only where it bends; the footway's
        # own small wiggles are not the block's shape, b0-w23189661l.6; the edge never bends with the road where the road bends away
        # from the footway, b0-w48524371r: Kaveh 2026-10-15)
        edge = list(shapely.LineString(edge).simplify(EDGE_SIMPLIFY_M).coords)
        out_ = [shapely.make_valid(shapely.Polygon(road + edge[::-1]))]
        # past each junction end the EDGE runs straight on in its own last direction (the footway's), so two edges meet in a sharp
        # corner; it ran on in the road's end direction, which at a slip lane bending into the junction stuck a corner out of the
        # footway line, a bump in the sidewalk (b0-w48524371r at West 8th; Kaveh 2026-10-16)
        for e in (0, -1):
            if e in ends and len(edge) >= 2:
                p, q = (edge[0], edge[1]) if e == 0 else (edge[-1], edge[-2])
                dx, dy = p[0] - q[0], p[1] - q[1]
                h = (dx * dx + dy * dy) ** .5 or 1
                o = (p[0] + dx / h * ext[e], p[1] + dy / h * ext[e])
                d_ = ts[0 if e == 0 else -1][1]
                rp = road[0] if e == 0 else road[-1]
                ro = (rp[0] + dx / h * ext[e], rp[1] + dy / h * ext[e])
                out_.append(shapely.make_valid(shapely.Polygon([rp, ro, o, p])))
        return shapely.union_all(out_)

    def extend(x, ext, ends):
        """Line x run on past each end in ends by ext[end]."""
        c = list(x.coords)
        def out(p, q, e):
            dx, dy = p[0] - q[0], p[1] - q[1]
            h = (dx * dx + dy * dy) ** .5 or 1
            return (p[0] + dx / h * e, p[1] + dy / h * e)
        if 0 in ends:
            c = [out(c[0], c[1], ext[0])] + c
        if -1 in ends:
            c = c + [out(c[-1], c[-2], ext[-1])]
        return shapely.LineString(c)

    def touching(ch, e):
        """The other chains at chain ch's end e."""
        pt = shapely.Point(ch["geom"].coords[e])
        return [chains[j] for j in ctree.query(pt.buffer(0.1)) if chains[j] is not ch and chains[j]["geom"].distance(pt) < 0.1]

    def ext_at(ch, e, road_ext=2 * REACH_M):
        """How far a chain's edge runs on past its end e: where a road meets it, road_ext (2 REACH_M: two edges meet in a sharp corner at
        a junction); where only paths meet there, the widest path's half width, to that path's far edge (a path's edge run on 50 m cut a
        strip into the block past a T of paths: Rue Langle at Rue Princesse Caroline, 2026-10-16); at a dead end nothing."""
        touch = touching(ch, e)
        if any(c_["cl"] not in PATH_W for c_ in touch):
            return road_ext
        return max([pw[c_["oid"]][0] / 2 for c_ in touch] + [0.0])

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
    # a path chain's strip, the same in every face and the same as its corridor (an edge offset on one side cut a chord across a bend,
    # a wedge of street between the block and the corridor: Rue Princesse Antoinette, 2026-10-16): its width either side of the chain,
    # square at an end another chain meets (run on to that road's edge in the cut, to that path's far edge in the corridor), round at a
    # dead end
    pstrip, pcor = {}, {}
    for j, ch in enumerate(chains):
        if ch["cl"] not in PATH_W:
            continue
        x, hw = ch["geom"], pw[ch["oid"]][0] / 2
        ends_ = [e for e in (0, -1) if touching(ch, e)]
        discs = [shapely.Point(x.coords[e]).buffer(hw) for e in (0, -1) if e not in ends_]
        pstrip[j] = shapely.union_all([extend(x, {e: ext_at(ch, e) for e in ends_}, ends_).buffer(hw, cap_style="flat")] + discs)
        pcor[j] = shapely.union_all([extend(x, {e: ext_at(ch, e, 0.0) for e in ends_}, ends_).buffer(hw, cap_style="flat")] + discs)
    lines = shapely.union_all([ch["geom"] for ch in chains] + [box.boundary])      # (boundary: an area of several parts, Monaco)
    faces = [f for f in shapely.get_parts(shapely.polygonize(list(shapely.get_parts(shapely.line_merge(lines))))) if f.within(box.buffer(0.1))]
    out, road_strips, slivers = [], [], []    # (block geometry, its sides [(chain, side row)], face); the roads' strips; the paths' leftovers
    for f in faces:
        fb = f.boundary.buffer(0.05)
        strips, pstrips_f, srows = [], [], []
        road_strips.append(strips)
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
            ext = {e: ext_at(ch, e) for e in ends}
            ds = []
            for sg in sgs:
                r = side_width(ch, sg, f)
                at = r[5] if len(r) > 5 else None
                r = r[:5]
                ds.append(r[0])
                srows.append((j, r))
                if j in pstrip:
                    continue
                # the edge line runs on past a junction, so two edges meet in a corner, as two parallel offsets do
                if at:          # where sidewalks set it, the edge follows the footway, SIDEWALK_BACK_M behind it, simplified
                    strips.append(follow(x, sg, at, ends, ext))
                else:
                    strips.append(extend(x, ext, ends).buffer(sg * r[0], single_sided=True))
            if j in pstrip:
                pstrips_f.append(pstrip[j])
                continue
            for e in (0, -1):
                if e not in ends:       # a dead end inside the face
                    strips.append(shapely.Point(x.coords[e]).buffer(max(ds)))
        # (and never over a bounding road's carriageway: a sidewalk edge cut across a curve and covered Avenue Saint-Laurent; Kaveh,
        # 2026-10-14)
        cut_ = shapely.make_valid(shapely.union_all(strips)) if strips else shapely.Polygon()
        try:
            b = poly(f.difference(cut_, grid_size=0.01))
        except shapely.errors.GEOSException:      # (GEOS "ring edge missing" on the grid, a footway-following edge: off the grid)
            b = poly(f.difference(cut_))
        b = poly(shapely.make_valid(b).difference(road_cw))     # (no grid here: on the grid GEOS failed, "ring edge missing")
        # the roads' blocks first: a piece narrower than MIN_BLOCK_W_M or under MIN_BLOCK_M2 (between a divided road's carriageways)
        # is street. Then the paths cut them, and every piece they leave is a block, however small (two footways 2 m apart have ground
        # between them): the filter threw those pieces away and West 8th's frontage took them, s0-w1318007190.2/1; Kaveh, 2026-10-16
        roads_b = [p for p in shapely.get_parts(wide(b)) if p.area >= MIN_BLOCK_M2]
        pcut = shapely.make_valid(shapely.union_all(pstrips_f)) if pstrips_f else shapely.Polygon()
        for p0 in roads_b:
            for p in shapely.get_parts(poly(p0.difference(pcut))):
                if p.area < 0.5:
                    continue
                if p.area < MIN_PLOT_M2 or p.buffer(-MIN_PLOT_W_M / 2).is_empty:
                    slivers.append((p, srows, f))
                else:
                    out.append((p, srows, f))

    # a sliver the paths' cuts left joins the corridor it shares the most edge with (path ground); one that touches no corridor stays a block
    pkeys = [j for j in pcor]
    ptree_c = shapely.STRtree([pcor[j] for j in pkeys]) if pkeys else None
    sliver_of = {}
    for p, srows, f in slivers:
        best, bl = None, 0.0
        for k in (ptree_c.query(p.buffer(0.1)) if ptree_c is not None else []):
            l_ = pcor[pkeys[k]].boundary.intersection(p.buffer(0.05)).length
            if l_ > bl:
                best, bl = pkeys[k], l_
        if best is None:
            out.append((p, srows, f))
        else:
            sliver_of.setdefault(best, []).append(p)

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
    con.executemany(f"""INSERT INTO urban.block VALUES (?, 0, ?, 'urbanstyle', 'derived',
                        ST_Transform(ST_GeomFromWKB(?), '{epsg}', 'EPSG:4326', always_xy := true))""",
                    [(i, round(p.area, 1), shapely.to_wkb(p)) for i, (p, _, _) in zip(ids, out)])
    side_rows = []
    for n_, (i, (p, srows, f)) in enumerate(zip(ids, out)):
        for j, (d, basis, method, unpulled, bld) in srows:
            ch = chains[j]
            if ch["geom"].distance(p) > d + 1:      # a side of the face that this piece of it does not reach
                continue
            way = min((oid for cl, n, oid, x in (roads[k] for k in rtree.query(ch["geom"].buffer(0.5)))
                       if oid is not None and x.intersection(ch["geom"].buffer(0.5)).length > 1), default=None)
            side_rows.append((i, way, ch["name"], ch["cl"], d, basis, method, unpulled, bld))
    if side_rows:
        con.executemany("INSERT INTO urban.block_side VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", side_rows)
    # the corridors: each path chain's strip (pcor, the same shape the blocks were cut by), never over a road's carriageway. Id c0-w<way>
    # (the chain's way), `.2` where a way has several
    # (a corridor ends at the street's edge: the roads' street-side strips, the block edge the sidewalk lines set, are taken out, so the
    # walking side runs on past the path's mouth and the slot lies inside the block: the first metres of every garden path were street
    # and the frontage stepped into each, s0-w627712113/1; Kaveh, 2026-10-16)
    # (the street's pieces near each corridor from a spatial index: one difference with the union of every road strip took Monaco's
    # blocks step from 2 minutes to over 25)
    street_parts = [st for ss in road_strips for st in ss if not st.is_empty] + list(shapely.get_parts(road_cw))
    sp_tree = shapely.STRtree(street_parts) if street_parts else None
    corridors, seen_c = [], {}
    for j, ch in enumerate(chains):
        if j not in pcor:
            continue
        c0 = pcor[j].intersection(box)
        near_ = [street_parts[k] for k in (sp_tree.query(c0) if sp_tree is not None else [])]
        q = poly(shapely.union_all([c0.difference(shapely.make_valid(shapely.union_all(near_))) if near_ else c0] + sliver_of.get(j, [])))
        if q.is_empty:
            continue
        cid = f"c0-w{ch['oid']}"
        seen_c[cid] = seen_c.get(cid, 0) + 1
        corridors.append((cid + (f".{seen_c[cid]}" if seen_c[cid] > 1 else ""), ch["oid"], ch["name"], ch["cl"], *pw[ch["oid"]], shapely.to_wkb(q)))
    if corridors:
        con.executemany(f"""INSERT INTO urban.corridor VALUES (?, ?, ?, ?, ?, ?, ?,
                            ST_Transform(ST_GeomFromWKB(?), '{epsg}', 'EPSG:4326', always_xy := true))""", corridors)
    return len(out)
