"""The paths at ranks 2 and 3 (docs/design/stretches.md, "The paths"; docs/design/tables.md): each path item of rank 1 (a corridor's
ground, work.ground kind path) cut at its path junction nodes into path sections and path intersections. Called after ground.build.

    junction    a node inside a path item where three or more path ends meet (a path that runs through a node counts two); a node
                where a path meets a sidewalk or a road is none: there the path ends at the street's edge
    the cut     each path line that leaves a junction is cut square at `r` from the node, `r` half the widest path there, across its
                own corridor only: the piece of the cut line through that point, inside the path item
    a piece     under MIN_PIECE_M2 joins the piece it shares the longest edge with; a path with no junction stays one piece
    the faces   each path item noded with the cuts and polygonized: the face that holds a junction node is that node's path
                intersection, `q<level>-<node>`; every other face is a path section, named by the way with the most length in it,
                `p<level>-w<way>` (a second face of one way `.2`)

work.path_space   space_id, kind (path section, path intersection), ground_id, level, name, class, ways, nodes, width_m, width_source,
                  width_method, length_m, predecessors, successors, axis, geometry
"""
CUT_HALF_M = 30.0    # a cut line is drawn this far to each side, then only its piece through the cut point inside the path item is kept
MIN_PIECE_M2 = 2.0   # a piece of a path item smaller than this joins its neighbour (chosen)
END_M = 0.05         # a path line's end lies on a node when it is this near
MIN_FACE_M2 = 0.01   # a face smaller than this is a hairline of the noding
TOUCH_M = 0.5        # two faces are neighbours when their outlines meet along at least this length


def build(con, epsg, level=0):
    import duckdb
    import shapely
    import shapely.ops
    from .blocks import PATH_W
    m = lambda col="geometry": f"ST_AsWKB(ST_Transform({col}, 'EPSG:4326', '{epsg}', always_xy := true))"
    g = lambda w: shapely.make_valid(shapely.from_wkb(bytes(w)))

    def rows(sql):
        try:
            return con.execute(sql).fetchall()
        except duckdb.CatalogException:
            return []
    con.execute("""CREATE OR REPLACE TABLE work.path_space (space_id VARCHAR, kind VARCHAR, ground_id VARCHAR, level INTEGER, name VARCHAR,
                   class VARCHAR, ways VARCHAR[], nodes BIGINT[], width_m DOUBLE, width_source VARCHAR, width_method VARCHAR,
                   length_m DOUBLE, predecessors VARCHAR[], successors VARCHAR[], axis GEOMETRY, geometry GEOMETRY)""")
    items = [(i, r, g(w)) for i, r, w in rows(f"SELECT ground_id, ref, {m()} FROM work.ground WHERE type = 'path' AND level = {level}")]
    if not items:
        return 0
    corr = {c: (nm, wd, ws, wm) for c, nm, wd, ws, wm in rows("SELECT corridor_id, name, width_m, width_source, width_method FROM work.corridor")}
    allp = shapely.union_all([x[2] for x in items])
    lines = []      # (way, class, name, src, dst, line): the path lines that lie in the paths' ground over half their length
    for oid, cl, nm, s_, d_, w in rows(f"""SELECT osm_id, class, name, src, dst, {m()} FROM work.element
                                          WHERE type IN ('walkway', 'cycleway') AND level_min <= {level} AND level_max >= {level}"""):
        ln = g(w)
        if ln.length > 0 and ln.intersection(allp).length > 0.5 * ln.length:
            lines.append((f"w{oid}", cl, nm, s_, d_, ln))
    # the junction nodes: three or more path ends at one node
    ends = {}
    for way, cl, nm, s_, d_, ln in lines:
        for node, pt in ((s_, ln.coords[0]), (d_, ln.coords[-1])):
            if node is not None:
                ends.setdefault(node, [pt, []])[1].append((way, ln))
    width = {}
    for c, (nm, wd, ws, wm) in corr.items():
        width[c] = wd
    item_w = {i: (corr.get(r, (None, None, None, None))[1] or PATH_W["footway"]) for i, r, _ in items}
    inner = allp.buffer(-0.25)       # (a node on a path item's edge, where a path meets the street, is no path junction)
    junctions = {n: shapely.Point(pt) for n, (pt, ls) in ends.items() if len(ls) >= 3 and inner.covers(shapely.Point(pt))}
    # the cuts: square across each path line at r from its junction
    cuts = []
    for n, pt in junctions.items():
        near = [w_ for i, r, gm in items if gm.distance(pt) < 1.0 for w_ in [item_w[i]]]
        r = max(near or [PATH_W["footway"]]) / 2
        for way, ln in ends[n][1]:
            s = 0.0 if shapely.Point(ln.coords[0]).distance(pt) < shapely.Point(ln.coords[-1]).distance(pt) else ln.length
            if ln.length <= r:
                continue
            at = r if s == 0.0 else ln.length - r
            p0, p1 = ln.interpolate(max(at - 0.5, 0)), ln.interpolate(min(at + 0.5, ln.length))
            dx, dy = p1.x - p0.x, p1.y - p0.y
            h = (dx * dx + dy * dy) ** 0.5 or 1.0
            c = ln.interpolate(at)
            nx, ny = -dy / h * CUT_HALF_M, dx / h * CUT_HALF_M
            cuts.append((c, shapely.LineString([(c.x - nx, c.y - ny), (c.x + nx, c.y + ny)])))
    # the faces of each path item
    out, count = [], {}
    for gid, ref, gm in items:
        mine = []
        for c, ln in cuts:      # only the piece of the cut through its own point, inside this item: across its own corridor
            if gm.distance(c) > 0.05:
                continue
            here = [q for q in shapely.get_parts(ln.intersection(gm.buffer(0.01))) if q.geom_type == "LineString" and q.distance(c) < 0.05]
            mine += here
        faces = [gm]
        if mine:
            net = shapely.union_all([gm.boundary] + [c for c in mine if not c.is_empty])
            faces = [f for f in shapely.get_parts(shapely.polygonize(shapely.get_parts(net))) if f.area > MIN_FACE_M2 and gm.covers(f.representative_point())]
            faces = faces or [gm]
            # a piece under MIN_PIECE_M2 joins the piece it shares the longest edge with
            changed = True
            while changed and len(faces) > 1:
                changed = False
                small = min(range(len(faces)), key=lambda k: faces[k].area)
                if faces[small].area < MIN_PIECE_M2:
                    f0 = faces.pop(small)
                    k = max(range(len(faces)), key=lambda k: f0.buffer(0.05).intersection(faces[k].boundary).length)
                    faces[k] = shapely.union_all([faces[k], f0]).buffer(0)
                    changed = True
        nm, wd, ws, wm = corr.get(ref, (None, None, None, None))
        if wd is None:
            wd, ws, wm = item_w[gid], "urbanstyle", "chosen"
        for f in faces:
            jn = [n for n, pt in junctions.items() if f.buffer(0.05).covers(pt)]
            inside = sorted(((ln.intersection(f).length, way, cl, ln) for way, cl, nm_, s_, d_, ln in lines), key=lambda x: -x[0])
            inside = [x for x in inside if x[0] > 0]
            if jn:
                base, kind = f"q{level}-{min(jn)}", "path intersection"
            elif inside:
                base, kind = f"p{level}-{inside[0][1]}", "path section"
            else:
                base, kind = f"p{level}-{ref}", "path section"
            count[base] = count.get(base, 0) + 1
            sid = base + (f".{count[base]}" if count[base] > 1 else "")
            axis, length, cl = None, None, (inside[0][2] if inside else None)
            if kind == "path section" and inside:
                part = inside[0][3].intersection(f)
                parts_ = [p for p in shapely.get_parts(part) if p.geom_type == "LineString"]
                if parts_:
                    axis = max(parts_, key=lambda p: p.length)
                    length = round(axis.length, 2)
            ways = list(dict.fromkeys(w_ for _, w_, _, _ in inside))
            nodes = sorted(jn) if jn else sorted(n for n, pt in junctions.items() if f.distance(pt) < 2 * max(wd, 1.0))
            out.append(dict(id=sid, kind=kind, ground=gid, name=nm, cls=cl, ways=ways, nodes=nodes, w=(wd, ws, wm), length=length,
                            axis=axis, geom=f))
    # the links: a path section's ends are the path intersections it touches, both ways
    for a in out:
        a["links"] = sorted(b["id"] for b in out if b is not a and b["kind"] != a["kind"]
                            and a["geom"].buffer(0.05).intersection(b["geom"].boundary).length >= TOUCH_M)
    import pyproj
    back = pyproj.Transformer.from_crs(epsg, "EPSG:4326", always_xy=True).transform
    ll = lambda x: None if x is None else shapely.to_wkb(shapely.ops.transform(back, x))
    con.executemany("INSERT INTO work.path_space VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ST_GeomFromWKB(?), ST_GeomFromWKB(?))",
                    [(a["id"], a["kind"], a["ground"], level, a["name"], a["cls"], a["ways"], a["nodes"], *a["w"], a["length"], a["links"],
                      a["links"], ll(a["axis"]), ll(a["geom"])) for a in out])
    con.execute("UPDATE work.path_space SET axis = NULL WHERE axis IS NOT NULL AND ST_AsWKB(axis) IS NULL")
    return len(out)
