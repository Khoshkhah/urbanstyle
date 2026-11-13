"""The street from SimReady's roadway (docs/notes/simready-input.md). It replaces network.py and turns.py in a build with --simready:
SimReady makes the roadway (lanes, junctions, islands, stop lines, moves, levels), urbanstyle makes the rest of the street space.

It reads SimReady's build (`../simready/out/<area>-rust/build.duckdb`, schema sim) read-only and writes the rows of network.py's tables
(network.SCHEMA) at every level:

    sections      each carriageway that is not inside a junction, with its twin (the other direction): one section, one subsection,
                  one space (id s<level>-w<way>/1: the way of its longest edge); its lanes from SimReady's lane boundaries
    intersections each SimReady junction (id i<level>-<smallest node>): its area, the lanes of the carriageways inside it, its islands
    pedestrian    the street (the area less the blocks and the corridors; on another level, SimReady's street faces of that level) less
                  the roadway, cut across at each section's ends, each piece to the space whose roadway it touches most: each piece
                  whole a sidewalk where an OSM footway or cycleway of that level runs in it or its road's sidewalk tag says so, else one
                  flat part, unmapped, that no source describes; the kerb only where a sidewalk meets the roadway
    marks         the lane lines between the lanes of one carriageway and the centre line between two directions on one line (both
                  from SimReady's lane boundaries), the kerb (the roadway's edge facing the pedestrian side), the stop line where the
                  junction has signals or a stop sign and the give-way line where it has a yield sign, and one guide line per move
    turns         SimReady's moves (work.turn) and the lanes into each junction (work.approach)

Every row from SimReady has source `simready` and SimReady's own method (`ev_method`); the pedestrian bands are urbanstyle's (derived).
"""
WALK_IN_M = 2.0         # an OSM footway runs in a walking-side piece when this much of it lies inside (chosen: more than a crossing's end)
SIDE_TAG_M = 25.0       # a walking-side piece takes the sidewalk tag of the nearest road within this distance (chosen: half a wide street)
LEVELS = (-2, 2)        # urbanstyle's levels (container.CLAMP); SimReady's lower tunnels go to the lowest
LANE_TYPE = {"through": "lane", "pocket": "lane", "merge": "lane", "bike": "cycle lane", "bus": "bus lane", "parking": "parking",
             "median": "island"}


from . import bulk


def is_street(highway, name, edges, service_kind):
    """blocks.street_sql's rule on a SimReady carriageway: a street class with its links, or a service road with a street's name and no
    service=* kind (service_kind: the duckOSM edges that have one). An unnamed service road, a car park's aisle or a drive, is no street,
    though SimReady gives it lanes."""
    from .network import STREET
    return (highway or "").removesuffix("_link") in STREET or (highway == "service" and bool(name) and not service_kind & set(edges or []))


def read(con, epsg, path, area):
    """SimReady's street at level 0 inside `area` (metres, `epsg`), for sr_blocks.py: `face` (its ground face and its roundabouts' faces),
    `lanes` and `junctions` (the streets' lanes and junction areas), `drives` (the lanes of the ways that are no street: unnamed service
    ways), and `streets`: one dict per street carriageway with its OSM way, name, class and line."""
    import shapely
    g = lambda w: shapely.make_valid(shapely.force_2d(shapely.from_wkb(bytes(w))))
    con.execute("DETACH DATABASE IF EXISTS sr")
    con.execute(f"ATTACH '{path}' AS sr (READ_ONLY)")
    (crs,), = con.execute("SELECT crs FROM sr.sim.project").fetchall()
    tr = (lambda col: col) if crs == epsg else (lambda col: f"ST_Transform({col}, '{crs}', '{epsg}', always_xy := true)")
    aw = shapely.to_wkb(area)
    service_kind = {e for (e,) in con.execute("SELECT edge_id FROM osm.driving.edges WHERE service IS NOT NULL").fetchall()}
    edge_way = dict(con.execute("SELECT edge_id, osm_id FROM osm.driving.edges").fetchall())
    edge_len = dict(con.execute("SELECT edge_id, length_m FROM osm.driving.edges").fetchall())
    cws = {}
    for cid, hw, nm, es, inside, w in con.execute(f"""SELECT carriageway_id, highway, name, edge_ids, inside_junction_id, ST_AsWKB(ST_Force2D({tr('reference_line')}))
                 FROM sr.sim.carriageway WHERE level = 0 AND ST_Intersects({tr('reference_line')}, ST_GeomFromWKB(?))""", [aw]).fetchall():
        es = [e for e in (es or []) if e in edge_way]
        way = edge_way[max(es, key=lambda e: edge_len.get(e) or 0)] if es else None
        cws[cid] = dict(street=is_street(hw, nm, es, service_kind), way=way, name=nm, cl=hw, inside=inside, line=g(w))
    street_ids = [c for c, d in cws.items() if d["street"]]
    lanes = {True: [], False: []}
    for cid, bl, br in con.execute(f"""SELECT carriageway_id, ST_AsWKB(ST_Force2D({tr('boundary_left')})), ST_AsWKB(ST_Force2D({tr('boundary_right')})) FROM sr.sim.lane
                                      WHERE carriageway_id IN (SELECT unnest(?::BIGINT[]))""", [list(cws)]).fetchall():
        bl, br = shapely.from_wkb(bytes(bl)), shapely.from_wkb(bytes(br))
        if bl.length and br.length:
            lanes[cws[cid]["street"]].append(shapely.make_valid(shapely.Polygon(list(bl.coords) + list(br.coords)[::-1])))
    ends = {n for (n,) in con.execute("""SELECT unnest([from_node_id, to_node_id]) FROM sr.sim.carriageway WHERE carriageway_id IN (SELECT unnest(?::BIGINT[]))""", [street_ids]).fetchall()}
    inside = {d["inside"] for c, d in cws.items() if d["street"] and d["inside"] is not None}
    juncs = [g(w) for j, ns, w in con.execute(f"""SELECT junction_id, node_ids, ST_AsWKB(ST_Force2D({tr('area')})) FROM sr.sim.junction
                 WHERE level = 0 AND ST_Intersects({tr('area')}, ST_GeomFromWKB(?))""", [aw]).fetchall() if j in inside or ends & set(ns)]
    face = [g(w) for (w,) in con.execute(f"""SELECT ST_AsWKB(ST_Force2D({tr('geometry')})) FROM sr.sim.street_face
                 WHERE level = 0 AND kind IN ('ground', 'roundabout')""").fetchall()]
    con.execute("DETACH DATABASE sr")
    u = lambda xs: shapely.union_all(xs or [shapely.Polygon()])
    return dict(face=shapely.make_valid(u(face)).intersection(area), lanes=u(lanes[True]), drives=u(lanes[False]), junctions=u(juncs),
                lane_list=lanes[True], drive_list=lanes[False], junction_list=juncs,      # (the same, one polygon each: the Rust port indexes them)
                streets=[dict(way=d["way"], name=d["name"], cl=d["cl"], line=d["line"]) for d in cws.values() if d["street"] and d["way"] is not None])


def read_all(con, epsg, path):
    """SimReady's rows that reach into the area, as the division step reads them (`build` and rust/tools/export_division_fixture.py): the
    streets' carriageways, their lanes, the junctions, islands, stop lines, moves and the faces of the other levels. SimReady's build stays
    attached as `sr` (build detaches it). The input check stops the build if a driving edge of the area is not one of SimReady's."""
    import shapely
    # (2D: SimReady's lines carry their heights as Z; the levels give the height here, and a Z broke the checks' ?at= links)
    g = lambda w: shapely.make_valid(shapely.force_2d(shapely.from_wkb(bytes(w)))) if w is not None else None
    m = lambda col="geometry": f"ST_AsWKB(ST_Transform({col}, 'EPSG:4326', '{epsg}', always_xy := true))"
    poly = lambda x: x if x.geom_type in ("Polygon", "MultiPolygon") else shapely.union_all(
        [p for q in shapely.get_parts(x) for p in shapely.get_parts(q) if p.geom_type == "Polygon"] or [shapely.Polygon()])
    rows = lambda sql, a=None: con.execute(sql, a or []).fetchall()
    I = lambda a, b: shapely.intersection(poly(a), poly(b), grid_size=0.01)
    lv_of = lambda x: max(LEVELS[0], min(LEVELS[1], int(x or 0)))

    con.execute("DETACH DATABASE IF EXISTS sr")
    con.execute(f"ATTACH '{path}' AS sr (READ_ONLY)")
    (crs, ver, built, dver, osm_ts), = rows("SELECT crs, simready_version, built_at, duckosm_version, osm_timestamp FROM sr.sim.project")
    sm = (lambda col: f"ST_AsWKB({col})") if crs == epsg else (lambda col: f"ST_AsWKB(ST_Transform({col}, '{crs}', '{epsg}', always_xy := true))")
    area = shapely.union_all([g(w) for (w,) in rows(f"SELECT {m()} FROM work.area")] or [shapely.Polygon()])

    # ---- the input check: every driving edge of the area is one of SimReady's (both read the same duckOSM database)
    sim_edges = {e for (e,) in rows("SELECT DISTINCT unnest(edge_ids) FROM sr.sim.carriageway")}
    ours = {e: (o, ln) for e, o, ln in rows(f"""SELECT edge_id, osm_id, length_m FROM osm.driving.edges
                                               WHERE ST_Intersects(ST_Transform(geometry, 'EPSG:4326', '{epsg}', always_xy := true), ST_GeomFromWKB(?))""",
                                            [shapely.to_wkb(area)])}
    missing = sorted(set(ours) - sim_edges)
    if missing:
        raise SystemExit(f"simready: {len(missing)} driving edges of the area are not in SimReady's build ({path}), e.g. {missing[:5]}: "
                         "build the input database with SimReady's overrides (docs/notes/simready-input.md, 'The edge ids')")
    edge_osm = {e: (o, ln) for e, o, ln in rows("SELECT edge_id, osm_id, length_m FROM osm.driving.edges")}
    service_kind = {e for (e,) in rows("SELECT edge_id FROM osm.driving.edges WHERE service IS NOT NULL")}

    # ---- SimReady's rows that reach into the area
    aw = shapely.to_wkb(area)
    near = lambda col: f"ST_Intersects({col}, ST_GeomFromWKB(?))"
    if crs != epsg:
        near = lambda col: f"ST_Intersects(ST_Transform({col}, '{crs}', '{epsg}', always_xy := true), ST_GeomFromWKB(?))"
    cws = {r[0]: dict(edges=r[1], twin=r[2], shared=r[3], highway=r[4], name=r[5], oneway=r[6], ring=r[7], inside=r[8], level=lv_of(r[9]),
                      method=r[10], line=g(r[11]), ends=(r[12], r[13])) for r in rows(f"""
        SELECT carriageway_id, edge_ids, twin_carriageway_id, shared_line, highway, name, oneway, roundabout_id, inside_junction_id, level,
               ev_method, {sm('reference_line')}, from_node_id, to_node_id FROM sr.sim.carriageway WHERE {near('reference_line')}""", [aw])
           if is_street(r[4], r[5], r[1], service_kind)}     # (the streets only, by blocks.street_sql's rule)
    lanes = {}
    for r in rows(f"""SELECT lane_id, carriageway_id, lane_num, role, use, turn, width_start_m, width_end_m, ev_method, ev_source_ids,
                             {sm('boundary_left')}, {sm('boundary_right')} FROM sr.sim.lane
                      WHERE carriageway_id IN (SELECT unnest(?::BIGINT[]))""", [list(cws)]):
        lid, cid, n, role, use, turn, w0, w1, me, srcs, bl, br = r
        bl, br = g(bl), g(br)
        shape = shapely.make_valid(shapely.Polygon(list(bl.coords) + list(br.coords)[::-1])) if bl.length and br.length else shapely.Polygon()
        lanes[lid] = dict(cid=cid, n=n, role=role, use=use, turn=turn, w=round(((w0 or 0) + (w1 or w0 or 0)) / 2, 2), method=me,
                          srcs=srcs, left=bl, right=br, geom=poly(I(shape, area)))
    lanes_by_cw = {}
    for L in lanes.values():
        lanes_by_cw.setdefault(L["cid"], []).append(L)
    juncs = {r[0]: dict(nodes=r[1], kind=r[2], control=r[3], ring=r[4], level=lv_of(r[5]), method=r[6], area=g(r[7])) for r in rows(f"""
        SELECT junction_id, node_ids, kind, control, roundabout_id, level, ev_method, {sm('area')} FROM sr.sim.junction WHERE {near('area')}""", [aw])}
    # (a junction of service roads only is no street's junction: only one that a street carriageway ends at or runs inside)
    street_nodes = {n for c in cws.values() for n in c["ends"]}
    inside = {c["inside"] for c in cws.values()}
    juncs = {j: d for j, d in juncs.items() if j in inside or street_nodes & set(d["nodes"])}
    islands = [dict(j=r[0], kind=r[1], level=lv_of(r[2]), method=r[3], geom=g(r[4])) for r in rows(f"""
        SELECT junction_id, kind, level, ev_method, {sm('area')} FROM sr.sim.island WHERE {near('area')}""", [aw])]
    stops = [dict(cid=r[0], j=r[1], method=r[2], geom=g(r[3])) for r in rows(f"""
        SELECT carriageway_id, junction_id, ev_method, {sm('geometry')} FROM sr.sim.stop_line WHERE {near('geometry')}""", [aw])]
    moves = [dict(j=r[0], fl=r[1], tl=r[2], fc=r[3], tc=r[4], turn=r[5], uses=r[6], method=r[7], geom=g(r[8])) for r in rows(f"""
        SELECT junction_id, from_lane_id, to_lane_id, from_carriageway_id, to_carriageway_id, turn, allowed_uses, ev_method, {sm('path')}
        FROM sr.sim.movement WHERE {near('path')}""", [aw])]
    faces = [(lv_of(lv), g(w)) for lv, w in rows(f"SELECT level, {sm('geometry')} FROM sr.sim.street_face WHERE level <> 0 AND {near('geometry')}", [aw])]
    print(f"  simready: {len(cws)} carriageways, {len(lanes)} lanes, {len(juncs)} junctions, {len(islands)} islands, {len(moves)} moves "
          f"(SimReady {ver}, built {built})", flush=True)
    return dict(area=area, ver=ver, built=built, dver=dver, osm_ts=osm_ts, edge_osm=edge_osm, cws=cws, lanes=lanes, lanes_by_cw=lanes_by_cw, juncs=juncs,
                islands=islands, stops=stops, moves=moves, faces=faces)


def build(con, epsg, path):
    import time
    _t = [time.time()]

    def tick(label):
        print(f"  simready: {label} {time.time() - _t[0]:.0f} s", flush=True)
        _t[0] = time.time()
    import duckdb
    import shapely
    import shapely.ops
    from .network import COLORS, CUT_M, SCHEMA
    from .parts import LINE

    # (2D: SimReady's lines carry their heights as Z; the levels give the height here, and a Z broke the checks' ?at= links)
    g = lambda w: shapely.make_valid(shapely.force_2d(shapely.from_wkb(bytes(w)))) if w is not None else None
    m = lambda col="geometry": f"ST_AsWKB(ST_Transform({col}, 'EPSG:4326', '{epsg}', always_xy := true))"
    to_ll = f"ST_Transform(ST_GeomFromWKB(?), '{epsg}', 'EPSG:4326', always_xy := true)"
    # (a polygon or a multipolygon is as it is: the union of its parts, made again, took 43 ms for each big operand of an overlay)
    poly = lambda x: x if x.geom_type in ("Polygon", "MultiPolygon") else shapely.union_all(
        [p for q in shapely.get_parts(x) for p in shapely.get_parts(q) if p.geom_type == "Polygon"] or [shapely.Polygon()])
    lines = lambda x: [p for p in shapely.get_parts(shapely.line_merge(shapely.union_all([q for q in shapely.get_parts(x)
                       if q.geom_type in ("LineString", "MultiLineString")] or [shapely.LineString()]))) if p.geom_type == "LineString" and p.length > 0.2]
    rows = lambda sql, a=None: con.execute(sql, a or []).fetchall()
    # (polygons only, on a 1 cm grid: SimReady's polygons touch along shared edges, and a clip at the area's edge leaves lines too)
    D = lambda a, b: shapely.difference(poly(a), poly(b), grid_size=0.01)
    I = lambda a, b: shapely.intersection(poly(a), poly(b), grid_size=0.01)
    lv_of = lambda x: max(LEVELS[0], min(LEVELS[1], int(x or 0)))

    R = read_all(con, epsg, path)
    con.execute("CREATE OR REPLACE TABLE work.simready_input AS SELECT ? AS path, ? AS simready_version, ? AS built_at, ? AS duckosm_version, "
                "? AS osm_timestamp", [path, R["ver"], R["built"], R["dver"], R["osm_ts"]])
    area, edge_osm, cws, lanes, lanes_by_cw, juncs, islands, stops, moves, faces = (R[k] for k in (
        "area", "edge_osm", "cws", "lanes", "lanes_by_cw", "juncs", "islands", "stops", "moves", "faces"))
    tick("read SimReady's rows")

    # ---- the spaces: one per section (a carriageway and its twin) and one per junction
    def way_of(cid):
        es = [e for e in cws[cid]["edges"] if e in edge_osm]
        return edge_osm[max(es, key=lambda e: edge_osm[e][1] or 0)][0] if es else None
    used, unit_of_cw, units = {}, {}, {}

    def new_id(base):
        used[base] = used.get(base, 0) + 1
        return base + (f".{used[base]}" if used[base] > 1 else "")
    jid = {}
    for j, d in sorted(juncs.items()):
        jid[j] = new_id(f"i{d['level']}-{min(d['nodes'])}")
        units[jid[j]] = dict(kind="intersection", section=None, level=d["level"], parts=[], marks=[], cws=[])
    for cid in sorted(cws):
        c = cws[cid]
        if cid in unit_of_cw:
            continue
        if c["inside"] is not None and c["inside"] in jid:
            unit_of_cw[cid] = jid[c["inside"]]
            units[jid[c["inside"]]]["cws"].append(cid)
            continue
        pair = [cid] + ([c["twin"]] if c["twin"] in cws and c["twin"] not in unit_of_cw and cws[c["twin"]]["inside"] is None else [])
        sid = new_id(f"s{c['level']}-w{way_of(cid)}")
        uid = sid + "/1"
        units[uid] = dict(kind="subsection", section=sid, level=c["level"], parts=[], marks=[], cws=pair)
        for x in pair:
            unit_of_cw[x] = uid

    def part(uid, typ, geom, **kw):
        units[uid]["parts"].append(dict(type=typ, geom=geom, **kw))

    def mark(uid, typ, geom, source="simready", method=None, ref=None):
        for ln in lines(geom):
            units[uid]["marks"].append((typ, ln, source, method, ref))

    # the lanes
    for lid, L in sorted(lanes.items()):
        uid = unit_of_cw.get(L["cid"])
        if uid is None or L["geom"].is_empty:
            continue
        c, u = cws[L["cid"]], units[uid]
        typ = "ring" if c["ring"] is not None and u["kind"] == "intersection" else LANE_TYPE.get(L["role"], "lane")
        part(uid, typ, L["geom"], direction="forward" if L["cid"] == u["cws"][0] or u["kind"] == "intersection" else "backward",
             lane=L["n"], lane_id=str(lid), width_m=L["w"], width_source="simready", width_method=L["method"], source="simready",
             method=L["method"], ref=f"c{L['cid']} lane {L['n']} ({L['role']}) w{way_of(L['cid'])}: " + ", ".join(L["srcs"] or []),
             road=c["name"], road_class=c["highway"], oneway="yes" if c["oneway"] else "no")
    sp = [(u["level"], p["geom"]) for u in units.values() if u["kind"] == "subsection" for p in u["parts"] if not p["geom"].is_empty]
    section_parts = [x for _, x in sp]
    sp_level = [lv for lv, _ in sp]
    sp_tree = shapely.STRtree(section_parts) if section_parts else None      # (each junction against the lanes near it: the union of every lane for each of them took hours)
    # the junctions: the area less the lanes inside it, the islands and the sections' lanes
    for j, d in juncs.items():
        uid = jid[j]
        isl = [x for x in islands if x["j"] == j]
        for x in isl:
            part(uid, "island", poly(I(x["geom"], area)), source="simready", method=x["method"], ref=f"island {x['kind']} of junction {j}")
        area_j = poly(I(d["area"], area))
        # (the sections' lanes of the junction's own level only: a bridge's lanes overhead cut a hole in the junction area under it)
        taken = shapely.union_all([p["geom"] for p in units[uid]["parts"]] + [section_parts[k] for k in (sp_tree.query(area_j) if sp_tree is not None else [])
                                                                             if sp_level[k] == units[uid]["level"]])
        part(uid, "junction area", poly(D(area_j, taken)), source="simready", method=d["method"],
             ref=f"junction {j} ({d['kind']}, {d['control']})")

    tick("spaces and the roadway parts")
    # ---- the pedestrian side, level by level
    blocks = shapely.union_all([g(w) for (w,) in rows(f"SELECT {m()} FROM work.block WHERE level = 0")] or [shapely.Polygon()])
    corridors = shapely.union_all([g(w) for (w,) in rows(f"SELECT {m()} FROM work.corridor")] or [shapely.Polygon()])
    # OSM's sidewalk tags on the roads (sidewalk=left|right|both|yes, sidewalk:<side>=yes): a road's side with a sidewalk mapped as a tag,
    # with no line of its own. Each edge in the way's own direction, so a piece's side of it is known
    def sw_sides(t):
        t = t or {}
        sides = set()
        for side in ("left", "right"):
            v = t.get(f"sidewalk:{side}") or t.get("sidewalk:both")
            if (v == "yes") if v else t.get("sidewalk") in ("both", "yes", side):
                sides.add(side)
        return sides
    lv_of_way = {}
    for o, lo in rows("SELECT osm_id, level_min FROM work.element WHERE type = 'road' AND osm_id IS NOT NULL"):
        lv_of_way.setdefault(o, lo)
    tagged = [(o, sw_sides(t), g(w)) for o, t, w in rows(f"""SELECT e.osm_id, w.tags, {m('e.geometry')} FROM osm.driving.edges e
              JOIN osm.raw.ways w USING (osm_id) WHERE NOT e.is_reverse""")]
    tagged = [x for x in tagged if x[1] and x[2] is not None and not x[2].is_empty]
    for lv in sorted({u["level"] for u in units.values()}):
        ids = [u for u in units if units[u]["level"] == lv]
        sw_lv = [x for x in tagged if lv_of_way.get(x[0], 0) == lv]
        sw_tree = shapely.STRtree([x[2] for x in sw_lv]) if sw_lv else None

        def tag_says(x):
            """The OSM way whose sidewalk tag covers the side of its road that the piece x lies on (the nearest tagged road within
            SIDE_TAG_M), else None."""
            if sw_tree is None:
                return None
            p = x.representative_point()
            k = sw_tree.nearest(p)
            o, sides, ln = sw_lv[int(k)]
            if ln.distance(p) > SIDE_TAG_M:
                return None
            s_ = ln.project(p)
            a, b = ln.interpolate(max(s_ - 0.5, 0)), ln.interpolate(min(s_ + 0.5, ln.length))
            side = "left" if (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x) > 0 else "right"
            return o if side in sides else None
        road = {u: poly(shapely.union_all([p["geom"] for p in units[u]["parts"]] or [shapely.Polygon()])) for u in ids}
        road_all = shapely.union_all(list(road.values()) or [shapely.Polygon()])
        if lv == 0:
            street = poly(D(D(area, blocks), corridors))
        else:
            street = poly(I(shapely.union_all([f for l_, f in faces if l_ == lv] or [shapely.Polygon()]), area))
        realm = poly(D(street, road_all))
        if realm.is_empty:
            continue
        # the cuts: each section's two ends, across the street (its first and last lane's ends joined, run CUT_M to each side)
        cuts = []
        realm_b = realm.buffer(0.01)
        TILE_M, MARGIN_M = 150.0, 90.0       # (a cut runs CUT_M each way from its end: it meets only the realm within MARGIN_M of the tile that holds its end)
        tiles = {}

        def local_realm(x, y):
            key = (int(x // TILE_M), int(y // TILE_M))
            if key not in tiles:
                x0, y0 = key[0] * TILE_M, key[1] * TILE_M
                tiles[key] = shapely.clip_by_rect(realm_b, x0 - MARGIN_M, y0 - MARGIN_M, x0 + TILE_M + MARGIN_M, y0 + TILE_M + MARGIN_M)
            return tiles[key]
        for u in ids:
            if units[u]["kind"] != "subsection":
                continue
            for cid in units[u]["cws"]:
                ls = sorted((L for L in lanes_by_cw.get(cid, []) if L["left"].length), key=lambda L: L["n"])
                if not ls:
                    continue
                for k in (0, -1):
                    a, b = shapely.Point(ls[0]["left"].coords[k]), shapely.Point(ls[-1]["right"].coords[k])
                    d_ = a.distance(b)
                    if d_ < 0.5:
                        continue
                    ux, uy = (b.x - a.x) / d_, (b.y - a.y) / d_
                    cut = shapely.LineString([(a.x - ux * CUT_M, a.y - uy * CUT_M), (b.x + ux * CUT_M, b.y + uy * CUT_M)])
                    end = shapely.LineString([a, b]).buffer(0.5)
                    keep = [q for q in shapely.get_parts(cut.intersection(local_realm((a.x + b.x) / 2, (a.y + b.y) / 2))) if q.geom_type == "LineString"]
                    # (only the pieces that start at this end: a cut does not run on through the next street's sidewalk)
                    cuts += [q for q in keep if q.distance(end) < 1.0]
        pieces = [q for q in shapely.get_parts(shapely.ops.polygonize(shapely.union_all([realm.boundary] + cuts)))
                  if q.area > 0.05 and realm.contains(q.representative_point())] if cuts else list(shapely.get_parts(realm))
        # the walking side from sources only (docs/notes/rules-review-2026-11-12.md, Kaveh: "go ahead"): a piece is a sidewalk where an
        # OSM footway or cycleway line of this level runs in it (the corridors are out of the street already) or where its road's sidewalk
        # tag says so; the rest, which no source describes, is one flat part, `unmapped`, with no bands and no kerb
        walks = [(o, c_, w_, g(w)) for o, c_, w_, w in rows(f"""SELECT osm_id, class, width_m, {m()} FROM work.element
                 WHERE type IN ('walkway', 'cycleway') AND level_min = ? AND geometry IS NOT NULL""", [lv])]
        walks = [x for x in walks if x[3] is not None and not x[3].is_empty]
        walk_tree = shapely.STRtree([x[3] for x in walks]) if walks else None
        rtree_ids = [u for u in ids if not road[u].is_empty]
        tree = shapely.STRtree([road[u].boundary for u in rtree_ids]) if rtree_ids else None
        share = {}
        for q in pieces:
            if tree is None:
                break
            qb = q.buffer(0.3)
            cand = tree.query(qb)
            touch = [(road[rtree_ids[i]].boundary.intersection(qb).length, rtree_ids[i]) for i in cand]
            touch = [t for t in touch if t[0] > 0.05]
            owner = max(touch)[1] if touch else rtree_ids[int(tree.nearest(q))]
            share.setdefault(owner, []).append(q)
        # a roundabout's central island (SimReady's, with no junction of its own: agreed with SimReady, 2026-11-12): an island where it
        # lies in the street (a roundabout's interior that is a block already stays the block)
        central = poly(shapely.union_all([x["geom"] for x in islands if x["j"] is None and x["level"] == lv] or [shapely.Polygon()]))
        for u, qs in share.items():
            rest = poly(shapely.union_all(qs))
            walked = []
            for x in shapely.get_parts(poly(I(rest, central))):
                if x.area > 0.05:
                    part(u, "island", x, source="simready", method="island-extraction", ref="a roundabout's central island")
            rest = poly(D(rest, central))
            # each piece of the walking side is one thing, whole, from the roadway to the street's edge: the sidewalk of an OSM footway or
            # cycleway line that runs in it (the longest), else of the sidewalk tag of the road on its side, else unmapped
            for x in list(shapely.get_parts(rest)):
                if x.area <= 0.05:
                    continue
                inside = [(walks[k][3].intersection(x).length, k) for k in (walk_tree.query(x) if walk_tree is not None else [])]
                inside = [t for t in inside if t[0] >= WALK_IN_M]
                if inside:
                    o, c_, w_, _ = walks[max(inside)[1]]
                    ref = f"w{o} ({c_}) on level {lv} runs in it"
                else:
                    o = tag_says(x)
                    ref = f"w{o}'s sidewalk tag on this side"
                if o is not None:
                    part(u, "sidewalk", x, width_source="urbanstyle", width_method="derived", source="osm", method="mapped",
                         ref=ref + "; its width the room between the roadway and the street's edge")
                    walked.append(x)
                    rest = poly(D(rest, x))
            if walked:          # the kerb only where a sidewalk meets the roadway
                kerb = road[u].boundary.intersection(shapely.union_all(walked).buffer(0.05))
                mark(u, "kerb", kerb, "simready", "the roadway's edge", "the edge of SimReady's roadway where an OSM sidewalk meets it")
            for x in shapely.get_parts(rest):
                if x.area > 0.05:
                    part(u, "unmapped", x, source="urbanstyle", method="derived",
                         ref="the street less SimReady's roadway and OSM's sidewalks: no source describes it")

    tick("the walking side")
    # ---- the crosswalks (network.py's rules, 8a): OSM's crossing ways over SimReady's roadway, CROSSWALK_M wide or OSM `width`, and a crossing
    # node on a street with no crossing way at it (a band across that carriageway). Their paint from `crossing:markings`. Each is a part
    # of its own, cut from the lanes and the junction area it lies on (SimReady gives no crosswalk: its stop lines wait before them)
    import math
    from shapely.ops import substring
    from .network import markings, num_f, CROSSWALK_M, ZEBRA_BAR_M, ZEBRA_GAP_M, XWALK_MAX_M
    ROADX = ("lane", "junction area", "ring", "cycle lane", "bus lane", "parking")
    road0 = {u: poly(shapely.union_all([p["geom"] for p in d["parts"] if p["type"] in ROADX] or [shapely.Polygon()]))
             for u, d in units.items() if d["level"] == 0}
    xways = [(o, g(w)) for o, w in rows(f"""SELECT osm_id, {m()} FROM work.element WHERE type IN ('walkway', 'cycleway') AND level_min = 0
                                             AND subtype = 'crossing'""")]
    xtags = {o: dict(t or {}) for o, t in rows("SELECT osm_id, tags FROM osm.raw.ways WHERE osm_id IN (SELECT unnest(?::BIGINT[]))",
                                                [[o for o, _ in xways]])} if xways else {}
    xnodes = [(o, dict(t or {}), shapely.Point(x, y)) for o, t, x, y in rows(f"""SELECT osm_id, tags, ST_X(p), ST_Y(p) FROM (SELECT osm_id, tags,
                 ST_Transform(ST_Point(lon, lat), 'EPSG:4326', '{epsg}', always_xy := true) AS p FROM osm.raw.nodes WHERE tags['highway'] = 'crossing')""")]
    xw_tree = shapely.STRtree([x for _, x in xways]) if xways else None
    cw0 = [(cid, c["line"]) for cid, c in cws.items() if c["level"] == 0 and c["line"] is not None and not c["line"].is_empty]
    rt = shapely.STRtree([ln for _, ln in cw0]) if cw0 else None
    lane_u = {}
    for L in lanes.values():
        lane_u.setdefault(L["cid"], []).append(L["geom"])
    lane_u = {cid: poly(shapely.union_all(v)) for cid, v in lane_u.items()}
    xw = []     # [(polygon, markings, ref, axis line, width)]

    def crosses_road(seg):
        """The crossing piece runs across the road, not along it: a piece that crosses a road's line meets it at 30 degrees or more; one that
        crosses no line (over a junction area, or from a median) is a crossing when it is no longer than XWALK_MAX_M."""
        ks = [k for k in (rt.query(seg) if rt is not None else []) if cw0[k][1].intersects(seg)]
        if not ks:
            return seg.length <= XWALK_MAX_M
        ln = cw0[ks[0]][1]
        hit = ln.intersection(seg)
        mid = next((q for q in shapely.get_parts(hit) if q.geom_type == "Point"), hit.centroid)
        s_, t_ = ln.project(mid), seg.project(mid)
        a_, b_ = ln.interpolate(max(s_ - 1, 0)), ln.interpolate(min(s_ + 1, ln.length))
        xa, xb = seg.interpolate(max(t_ - 1, 0)), seg.interpolate(min(t_ + 1, seg.length))
        h1, h2 = math.hypot(xb.x - xa.x, xb.y - xa.y) or 1, math.hypot(b_.x - a_.x, b_.y - a_.y) or 1
        return abs((xb.x - xa.x) * (b_.x - a_.x) + (xb.y - xa.y) * (b_.y - a_.y)) / (h1 * h2) < math.cos(math.radians(30))
    rparts = [rd for rd in road0.values() if not rd.is_empty]      # (the road polygon of each space, from an index: the roadway is one connected
    rp_tree = shapely.STRtree(rparts) if rparts else None          # polygon, and its buffer for each of 946 crossings took 270 s)
    for oid, x in xways:
        w = num_f(xtags.get(oid, {}).get("width")) or CROSSWALK_M
        near_rw = shapely.union_all([rparts[k] for k in (rp_tree.query(x.buffer(0.3 + w)) if rp_tree is not None else [])] or [shapely.Polygon()])
        for seg in shapely.get_parts(x.intersection(near_rw.buffer(0.3))):
            if seg.geom_type == "LineString" and seg.length >= 1.0 and crosses_road(seg):
                xw.append((poly(I(seg.buffer(w / 2, cap_style="flat"), near_rw)), markings(xtags.get(oid, {})), f"w{oid}", seg, w))
    for oid, tg, p in xnodes:
        if xw_tree is not None and any(xways[k][1].distance(p) < 2.0 for k in xw_tree.query(p.buffer(2.0))):
            continue        # (a crossing way maps it)
        bands, seg0 = [], None      # (one crosswalk per node: the node can end two carriageways, OSM splits a way at a crossing)
        for k in (rt.query(p.buffer(1.0)) if rt is not None else []):
            cid, ln = cw0[k]
            if ln.distance(p) > 1.0:
                continue
            s_ = ln.project(p)
            seg = substring(ln, max(s_ - CROSSWALK_M / 2, 0.0), min(s_ + CROSSWALK_M / 2, ln.length))
            if seg.length < 0.5:
                continue
            rd = shapely.union_all([lane_u.get(c, shapely.Polygon()) for c in (cid, cws[cid]["twin"]) if c in lane_u] or [shapely.Polygon()])
            bands.append(I(seg.buffer(25, cap_style="flat"), rd))
            seg0 = seg0 if seg0 is not None and seg0.length >= seg.length else seg
        if bands:
            across = poly(shapely.union_all(bands))
            (x0, y0), (x1, y1) = seg0.coords[0], seg0.coords[-1]
            h_ = math.hypot(x1 - x0, y1 - y0) or 1
            nx, ny = -(y1 - y0) / h_, (x1 - x0) / h_         # (the bars run across the road: the crossing's own direction)
            walk = shapely.LineString([(p.x - nx * 30, p.y - ny * 30), (p.x + nx * 30, p.y + ny * 30)]).intersection(across.buffer(0.1))
            walk = max(shapely.get_parts(walk), key=lambda q: q.length, default=seg0) if not walk.is_empty else seg0
            xw.append((across, markings(tg), f"n{oid}", walk, CROSSWALK_M))
    # two crosswalks on one spot: the marked one keeps its shape, the next gives way to it
    rank = {"zebra": 0, "ladder": 0, "ladder:skewed": 0, "skewed": 0, "lines": 1, "dashes": 1, "dots": 1, "surface": 2, "pictograms": 2, "unknown": 3, "no": 4}
    xw.sort(key=lambda x: (rank.get(x[1], 3), -x[0].area))
    taken_l, taken_tree, n_xw = [], None, 0
    r0_ids = [u for u, rd in road0.items() if not rd.is_empty]
    r0_tree = shapely.STRtree([road0[u] for u in r0_ids]) if r0_ids else None
    for X, mk, ref, seg, w in xw:
        near_t = [taken_l[k] for k in (taken_tree.query(X) if taken_tree is not None else [])]
        X = poly(D(X, shapely.union_all(near_t))) if near_t else X
        if X.area < 0.5:
            continue
        owned = False
        for u in ([r0_ids[k] for k in r0_tree.query(X)] if r0_tree is not None else []):
            rd = road0[u]
            piece = poly(I(X, rd))
            if piece.area < 0.5:
                continue
            owned = True
            part(u, "crosswalk", piece, width_m=w, width_source="osm" if w != CROSSWALK_M else "urbanstyle", width_method="mapped" if w != CROSSWALK_M else "chosen",
                 source="osm", method="mapped" if w != CROSSWALK_M else "derived",
                 ref=f"{ref} crossing:markings={mk}" if mk != "unknown" else f"{ref}: a crossing, its paint not mapped")
            if mk in ("zebra", "ladder", "ladder:skewed", "skewed"):      # (bars square to the walking direction, ZEBRA_GAP_M apart)
                (x0, y0), (x1, y1) = seg.coords[0], seg.coords[-1]
                h_ = math.hypot(x1 - x0, y1 - y0) or 1
                ux, uy = (x1 - x0) / h_, (y1 - y0) / h_
                d = ZEBRA_BAR_M / 2
                while d < seg.length:
                    c_ = seg.interpolate(d)
                    bar = shapely.LineString([(c_.x - uy * w / 2, c_.y + ux * w / 2), (c_.x + uy * w / 2, c_.y - ux * w / 2)])
                    mark(u, "zebra", bar.intersection(piece.buffer(0.01)), "osm", "mapped", f"{ref} crossing:markings={mk}")
                    d += ZEBRA_BAR_M + ZEBRA_GAP_M
            if mk in ("lines", "dashes", "ladder", "ladder:skewed", "skewed", "dots"):
                for side_ in (w / 2 - 0.1, -w / 2 + 0.1):
                    mark(u, "crossing line", seg.offset_curve(side_).intersection(piece.buffer(0.01)), "osm", "mapped", f"{ref} crossing:markings={mk}")
        if owned:
            taken_l.append(X); n_xw += 1; taken_tree = shapely.STRtree(taken_l)
    xs = [q for X_ in taken_l for q in shapely.get_parts(X_) if q.geom_type == "Polygon"]
    if xs:      # (the roadway gives way to the crosswalks: no two parts of one space overlap; each part against the crosswalks near it)
        xs_tree = shapely.STRtree(xs)
        for u, d in units.items():
            if d["level"] == 0:
                for p_ in d["parts"]:
                    if p_["type"] in ROADX:
                        near_x = [xs[k] for k in xs_tree.query(p_["geom"])]
                        if near_x:
                            p_["geom"] = poly(D(p_["geom"], shapely.union_all(near_x)))
    print(f"  simready: {n_xw} crosswalks", flush=True)

    tick("the crosswalks")
    # ---- the marks inside the roadway
    by_cw = {}
    for L in lanes.values():
        by_cw.setdefault(L["cid"], []).append(L)
    for cid, ls in by_cw.items():
        uid = unit_of_cw.get(cid)
        if uid is None:
            continue
        ls.sort(key=lambda L: L["n"])
        drive = [L for L in ls if L["role"] in ("through", "pocket", "merge", "bus", "bike")]
        for a, b in zip(drive, drive[1:]):
            if b["n"] == a["n"] + 1:
                mark(uid, "lane line", a["right"].intersection(area), method=a["method"], ref=f"c{cid}: between lanes {a['n']} and {b['n']}")
        c = cws[cid]
        u = units[uid]
        if c["shared"] and c["twin"] in cws and u["kind"] == "subsection" and cid == u["cws"][0] and ls:
            mark(uid, "centre line", ls[0]["left"].intersection(area), method=ls[0]["method"], ref=f"c{cid} and c{c['twin']}: the line between the two directions")
    paint = {"signal": "stop line", "stop": "stop line", "yield": "give-way line"}
    for s in stops:
        typ = paint.get((juncs.get(s["j"]) or {}).get("control"))
        uid = unit_of_cw.get(s["cid"])
        if typ and uid:
            mark(uid, typ, s["geom"].intersection(area), method=s["method"], ref=f"c{s['cid']} at junction {s['j']} ({juncs[s['j']]['control']})")
    for mv in moves:
        if mv["j"] in jid and mv["geom"] is not None:
            mark(jid[mv["j"]], "guide line", mv["geom"].intersection(area), method=mv["method"], ref=f"c{mv['fc']} to c{mv['tc']} ({mv['turn']})")

    tick("the marks")
    # ---- write (network.py's tables and columns)
    for t, cols in SCHEMA.items():
        con.execute(f"CREATE OR REPLACE TABLE work.{t} (" + ", ".join(f'"{c}" {ty}' for c, ty in cols.items()) + ")")
    clean = lambda x: poly(shapely.make_valid(shapely.set_precision(x, 0.01)))
    junc_road = {}
    for u in units.values():
        if u["kind"] == "intersection":
            junc_road.setdefault(u["level"], []).extend(p["geom"] for p in u["parts"] if p["type"] in ("junction area", "lane", "ring", "island"))
    junc_trees = {lv: (v, shapely.STRtree(v)) for lv, v in junc_road.items()}
    urows, prows, mrows, srows, jrows = [], [], [], [], []
    for uid, u in units.items():
        n = 0
        for p in u["parts"]:
            p["geom"] = clean(p["geom"])
            if p["geom"].area <= 0.05:
                continue
            n += 1
            prows.append((uid, f"{uid}#{n}", u["level"], p["type"], None, p.get("direction"), p.get("lane"), p.get("lane_id"), p.get("width_m"),
                          p.get("width_source") or "urbanstyle", p.get("width_method"), round(p["geom"].length / 2, 1), p["source"], p["method"],
                          p.get("ref"), p.get("road"), p.get("road_class"), p.get("oneway"), shapely.to_wkb(p["geom"])))
        geom = clean(shapely.union_all([p["geom"] for p in u["parts"]] or [shapely.Polygon()]))
        if geom.is_empty or geom.area <= 0.5:
            continue
        urows.append((uid, u["kind"], u["section"], u["level"], COLORS[u["kind"]], shapely.to_wkb(geom)))
        for typ, ln, s_, me, rf in u["marks"]:
            mrows.append((uid, u["level"], typ, round(ln.length, 1), LINE.get(typ), s_, me, rf, shapely.to_wkb(ln)))
        if u["kind"] == "subsection":
            c = cws[u["cws"][0]]
            axis = c["line"].intersection(area)
            jv, jt = junc_trees.get(u["level"], ([], None))
            near_j = [jv[k] for k in (jt.query(axis) if jt is not None else [])]
            axis = axis.difference(shapely.union_all(near_j)) if near_j else axis     # (it stops at the junctions)
            axis = max(lines(axis), key=lambda x: x.length) if lines(axis) else None
            if axis is None and lines(c["line"].intersection(area)):    # (a section inside a junction: its line as SimReady gives it)
                axis = max(lines(c["line"].intersection(area)), key=lambda x: x.length)
            width = round(sum(p.get("width_m") or 0 for p in u["parts"] if p.get("lane") is not None), 2)
            srows.append((uid, u["section"], u["level"], c["highway"], width, bool(c["oneway"] and len(u["cws"]) == 1),
                          round(axis.length, 1) if axis is not None else None, shapely.to_wkb(axis) if axis is not None else None))
    for j, d in juncs.items():
        if any(r[0] == jid[j] for r in urows):
            jrows += [(jid[j], n, d["level"], jid[j]) for n in d["nodes"]]
    bulk.executemany(con, f"INSERT INTO work.unit (unit_id, kind, section_id, level, color, geometry) VALUES (?, ?, ?, ?, ?, {to_ll})", urows)
    bulk.executemany(con, f"""INSERT INTO work.part (unit_id, part_id, level, type, arm, direction, lane, lane_id, width_m, width_source, width_method,
                        length_m, source, method, ref, road, road_class, oneway, geometry) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {to_ll})""", prows)
    bulk.executemany(con, f"""INSERT INTO work.mark (unit_id, level, type, length_m, width_m, width_source, width_method, source, method, ref, geometry)
                        VALUES (?, ?, ?, ?, ?, 'urbanstyle', 'chosen', ?, ?, ?, {to_ll})""", mrows)
    bulk.executemany(con, f"""INSERT INTO work.subsection (subsection_id, section_id, level, class, width_m, oneway, length_m, color, geometry)
                        VALUES (?, ?, ?, ?, ?, ?, ?, '#e6194b', CASE WHEN ? IS NULL THEN NULL ELSE {to_ll} END)""",
                    [r[:7] + (r[7], r[7]) for r in srows])
    bulk.executemany(con, "INSERT INTO work.junction (intersection_id, node_id, level, cluster_id) VALUES (?, ?, ?, ?)", jrows)

    tick("write the spaces, parts and marks")
    # ---- the moves (work.turn) and the lanes into each junction (work.approach)
    written = {r[0] for r in urows}
    edge_end = lambda cid, k: str(cws[cid]["edges"][k]) if cid in cws and cws[cid]["edges"] else f"c{cid}"
    trows, app = [], {}
    for mv in moves:
        uid = jid.get(mv["j"])
        if uid not in written or mv["geom"] is None or mv["geom"].is_empty:
            continue
        fl, tl = lanes.get(mv["fl"], {}), lanes.get(mv["tl"], {})
        trows.append((uid, juncs[mv["j"]]["level"], edge_end(mv["fc"], -1), fl.get("n"), edge_end(mv["tc"], 0), tl.get("n"), mv["turn"],
                      "simready", ";".join(mv["uses"] or []), None, shapely.to_wkb(mv["geom"])))
        a = app.setdefault((uid, juncs[mv["j"]]["level"], edge_end(mv["fc"], -1), fl.get("n")), [0, set(), fl.get("turn")])
        a[0] += 1
        a[1].add(mv["turn"])
    bulk.executemany(con, f"""INSERT INTO work.turn (unit_id, level, from_edge, from_lane, to_edge, to_lane, turn, source, vehicles, condition, geometry)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {to_ll})""", trows)
    bulk.executemany(con, "INSERT INTO work.approach (unit_id, level, from_edge, lane, moves, ways, arrow, no_arrow_because) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [(u, lv, e, n, k, ";".join(sorted(w)), bool(t and t not in ("none", "")), None if t and t not in ("none", "") else "SimReady gives no turn arrow")
                     for (u, lv, e, n), (k, w, t) in app.items()])
    con.execute("DETACH DATABASE sr")
    print(f"  simready: {len(urows)} spaces, {len(prows)} parts, {len(mrows)} marks, {len(trows)} moves", flush=True)
    return dict(spaces=len(urows), parts=len(prows), marks=len(mrows), turns=len(trows))
