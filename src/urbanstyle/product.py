"""The model: the schema `urban`, written from the build's intermediate tables in `work` (docs/design/tables.md). The last step of every
build (container._finish), before meta.py. Each table is written with the columns of the chapter, in its order; tests/test_product.py
holds the chapter and a build side by side.

    rank 0  area             a<level>: the area of each level
            element          the input: roads, walkways, cycleways, rail, buildings, car parks (work.element, work.lot)
    rank 1  ground           the street (its connected pieces), the plots (the blocks), the paths (the corridors)
    rank 2  stretch          the sections (their subsections chained) and the intersections
            plot_piece       the pieces of each plot (work.ground, less the street and the paths)
            joint            the tag changes along the sections (work.change)
            street, arm      the named streets; each section that arrives at an intersection
    rank 3  space            the subsections and the intersections (work.unit, work.subsection), with axes and links
            junction         the junction nodes of each intersection
    rank 4  side             the driving and the walking side of each space (its parts joined), the kerb
    rank 5  part             the parts, with their place (s, t) on the space's axis, a lane's axis and links
    rank 6  mark             the marks, on the part that holds them
            turn, approach   SUMO's moves, the lanes into each intersection
    tree    object           one row per real thing from every source (objects.matched_objects)
            link, station, surface, observed, photo
"""
import json
import os
import re

import duckdb

# the parts of the walking side (rank 4); every other part is on the driving side
WALKING = ("sidewalk", "furnishing", "frontage", "driveway", "island", "verge", "bus stop", "tree pit", "steps", "ramp", "handrail",
           "bollard", "open")
# the parts of a subsection that have no axis of their own: they cross the space or stand in it
NO_AXIS = ("crosswalk", "cycle crossing", "driveway", "tree pit", "bus stop", "junction area")
TOUCH_M = 0.5        # two lanes share a joint or a stop line when their outlines touch along at least this length
TURN_M = 1.5        # a turn's guide line starts in the lane nearest its first point, and ends in the lane nearest its last, within this
END_M = 15.0         # an intersection is at a section's end when it lies this near the end of the section's axis
NEAR_M = 60.0        # a street object outside every space names the nearest space within this distance (container.OBJECT_NEAR_M)

V, I, B, D, G, J = "VARCHAR", "INTEGER", "BIGINT", "DOUBLE", "GEOMETRY", "JSON"
COLUMNS = {      # the columns of docs/design/tables.md, in its order
    "area": [("area_id", V), ("kind", V), ("rank", I), ("parent_id", V), ("level", I), ("name", V), ("uid", V), ("source", V), ("method", V),
             ("ref", V), ("geometry", G)],
    "element": [("element_id", V), ("kind", V), ("class", V), ("subtype", V), ("name", V), ("osm_id", B), ("source_id", V), ("uid", V),
                ("oneway", "BOOLEAN"), ("lanes_forward", I), ("lanes_backward", I), ("width_m", D), ("width_src", V), ("level_min", I),
                ("level_max", I), ("level_src", V), ("floors", I), ("height_m", D), ("use", V), ("use_source", V), ("use_method", V),
                ("ground_use", V), ("ground_source", V), ("ground_method", V), ("source", V), ("geometry", G)],
    "ground": [("ground_id", V), ("kind", V), ("rank", I), ("parent_id", V), ("level", I), ("name", V), ("uid", V), ("sides", J), ("width_m", D),
               ("width_source", V), ("width_method", V), ("source", V), ("method", V), ("ref", V), ("geometry", G)],
    "stretch": [("stretch_id", V), ("kind", V), ("rank", I), ("parent_id", V), ("level", I), ("name", V), ("uid", V), ("street_id", V),
                ("ways", "VARCHAR[]"), ("nodes", "BIGINT[]"), ("class", V), ("oneway", "BOOLEAN"), ("length_m", D), ("axis", G),
                ("source", V), ("method", V), ("ref", V), ("geometry", G)],
    "plot_piece": [("piece_id", V), ("kind", V), ("rank", I), ("parent_id", V), ("level", I), ("name", V), ("uid", V), ("width_m", D),
                   ("width_source", V), ("width_method", V), ("surfaces", "VARCHAR[]"), ("source", V), ("method", V), ("ref", V),
                   ("geometry", G)],
    "joint": [("section_id", V), ("level", I), ("subsection_a", V), ("subsection_b", V), ("way_a", V), ("way_b", V), ("lanes_a", V),
              ("lanes_b", V), ("width_a", D), ("width_b", D), ("class", V), ("note", V), ("geometry", G)],
    "street": [("street_id", V), ("name", V), ("level", I), ("sections", "VARCHAR[]"), ("intersections", "VARCHAR[]"), ("geometry", G)],
    "arm": [("intersection_id", V), ("street_id", V), ("section_id", V), ("way", V), ("level", I)],
    "space": [("space_id", V), ("kind", V), ("rank", I), ("parent_id", V), ("level", I), ("name", V), ("uid", V), ("axis", G), ("s_from", D),
              ("s_to", D), ("width_m", D), ("oneway", "BOOLEAN"), ("length_m", D), ("left_extra", D), ("predecessors", "VARCHAR[]"),
              ("successors", "VARCHAR[]"), ("source", V), ("method", V), ("ref", V), ("geometry", G)],
    "junction": [("intersection_id", V), ("node_id", B), ("level", I), ("cluster_id", V), ("space_id", V)],
    "side": [("side_id", V), ("kind", V), ("rank", I), ("parent_id", V), ("level", I), ("name", V), ("uid", V), ("kerb", G), ("kerb_source", V),
             ("kerb_method", V), ("source", V), ("method", V), ("ref", V), ("geometry", G)],
    "part": [("part_id", V), ("kind", V), ("rank", I), ("parent_id", V), ("level", I), ("name", V), ("uid", V), ("space_id", V), ("arm", V),
             ("direction", V), ("lane", I), ("lane_id", V), ("axis", G), ("s_from", D), ("s_to", D), ("t_from", D), ("t_to", D),
             ("predecessors", "VARCHAR[]"), ("successors", "VARCHAR[]"), ("width_m", D), ("width_source", V), ("width_method", V),
             ("length_m", D), ("position_source", V), ("position_method", V), ("position_ref", V), ("road", V), ("road_class", V),
             ("speed", D), ("surface", V), ("lit", V), ("road_lanes", V), ("oneway", V), ("holds", V), ("rule", V), ("source", V),
             ("method", V), ("ref", V), ("geometry", G)],
    "mark": [("mark_id", V), ("kind", V), ("rank", I), ("parent_id", V), ("level", I), ("name", V), ("uid", V), ("parent_rank", I), ("space_id", V),
             ("s_from", D), ("s_to", D), ("t_from", D), ("t_to", D), ("width_m", D), ("width_source", V), ("width_method", V),
             ("length_m", D), ("source", V), ("method", V), ("ref", V), ("geometry", G)],
    "turn": [("space_id", V), ("level", I), ("from_edge", V), ("from_lane", I), ("to_edge", V), ("to_lane", I), ("turn", V),
             ("vehicles", V), ("condition", V), ("source", V), ("geometry", G)],
    "approach": [("intersection_id", V), ("level", I), ("from_edge", V), ("lane", I), ("moves", I), ("ways", V), ("arrow", "BOOLEAN"),
                 ("no_arrow_because", V)],
    "object": [("object_id", V), ("kind", V), ("uid", V), ("level", I), ("space_id", V), ("part_id", V), ("near_m", D), ("name", V),
               ("attrs", J), ("width_m", D), ("width_source", V), ("width_method", V), ("height_m", D), ("height_source", V),
               ("height_method", V), ("sources", V), ("refs", V), ("source", V), ("method", V), ("geometry", G)],
    "link": [("link_id", V), ("kind", V), ("level_from", I), ("level_to", I), ("node_id", B), ("station_id", V), ("geometry", G)],
    "station": [("station_id", V), ("kind", V), ("name", V), ("level", I), ("geometry", G)],
    "surface": [("surface_id", V), ("ground_id", V), ("kind", V), ("level", I), ("source", V), ("method", V), ("ref", V), ("geometry", G)],
    "observed": [("feature_id", V), ("kind", V), ("group", V), ("first_seen", "TIMESTAMP"), ("last_seen", "TIMESTAMP"), ("source", V),
                 ("geometry", G)],
    "photo": [("photo_id", V), ("captured", "TIMESTAMP"), ("compass", D), ("is_pano", "BOOLEAN"), ("sequence", V), ("geometry", G)],
}
UID_LATER = ("area", "ground", "stretch", "plot_piece", "space", "side", "part", "mark")
RANKED = (("area", "area_id"), ("ground", "ground_id"), ("stretch", "stretch_id"), ("plot_piece", "piece_id"), ("space", "space_id"),
          ("side", "side_id"), ("part", "part_id"), ("mark", "mark_id"))


class Writer:
    """The geometry helpers of one build: metres in `epsg` inside, lon/lat in the tables."""

    def __init__(self, con, epsg):
        import pyproj
        import shapely
        self.con, self.epsg, self.shapely = con, epsg, shapely
        self.back = pyproj.Transformer.from_crs(epsg, "EPSG:4326", always_xy=True).transform

    def rows(self, sql, params=None):
        try:
            return self.con.execute(sql, params or []).fetchall()
        except (duckdb.CatalogException, duckdb.BinderException):     # (a table or a column an older input does not have)
            return []

    def m(self, col="geometry"):
        return f"ST_AsWKB(ST_Transform({col}, 'EPSG:4326', '{self.epsg}', always_xy := true))"

    def g(self, w):
        return None if w is None else self.shapely.make_valid(self.shapely.from_wkb(bytes(w)))

    def ll(self, geom):
        import shapely.ops
        if geom is None or geom.is_empty:
            return None
        return self.shapely.to_wkb(shapely.ops.transform(self.back, geom))

    def table(self, name, rows):
        """urban.<name> with its COLUMNS; rows give the values in that order, geometry as shapely in metres."""
        cols = COLUMNS[name]
        if name in UID_LATER:       # (a rank table's uid comes from the registry, meta.write_registry: the rows leave it out)
            k = [c for c, _ in cols].index("uid")
            rows = [tuple(r[:k]) + (None,) + tuple(r[k:]) for r in rows]
        self.con.execute(f'CREATE OR REPLACE TABLE urban."{name}" ({", ".join(f"{q(c)} {t}" for c, t in cols)})')
        if not rows:
            return 0
        marks = ", ".join("ST_GeomFromWKB(?)" if t == G else "?" for _, t in cols)
        conv = [(lambda v: self.ll(v)) if t == G else ((lambda v: None if v is None else (v if isinstance(v, str) else json.dumps(v)))
                                                       if t == J else (lambda v: v)) for _, t in cols]
        self.con.executemany(f'INSERT INTO urban."{name}" VALUES ({marks})', [[f(v) for f, v in zip(conv, r)] for r in rows])
        for c, t in cols:       # (ST_GeomFromWKB(NULL) gives a geometry that is not NULL and has no shape: make it NULL)
            if t == G:
                self.con.execute(f'UPDATE urban."{name}" SET {q(c)} = NULL WHERE {q(c)} IS NOT NULL AND ST_AsWKB({q(c)}) IS NULL')
        return len(rows)


def q(c):
    return f'"{c}"'


def _st(axis, geom):
    """(s_from, s_to, t_from, t_to) of `geom` on `axis`: s along, t across, left positive (docs/design/tables.md, "The axes")."""
    import shapely
    pts = [shapely.Point(c) for c in shapely.get_coordinates(geom)]       # (any geometry, a collection with a multi-part in it too)
    if not pts or axis is None or axis.length == 0:
        return None, None, None, None
    ss, ts = [], []
    for pt in pts:
        s = axis.project(pt)
        a, b = axis.interpolate(max(s - 0.5, 0)), axis.interpolate(min(s + 0.5, axis.length))
        side = (b.x - a.x) * (pt.y - a.y) - (b.y - a.y) * (pt.x - a.x)
        ss.append(s)
        ts.append((1 if side >= 0 else -1) * pt.distance(axis.interpolate(s)))
    return min(ss), max(ss), min(ts), max(ts)


def _touch(a, b):
    """The length along which the outlines of a and b meet."""
    return a.buffer(0.05).intersection(b.boundary).length


def _chain(lines):
    """Lines end to end, each turned to continue the one before: one line, each line's (s_from, s_to) on it, and the lines as turned."""
    import shapely
    coords, ranges, turned = [], [], []
    for ln in lines:
        c = list(ln.coords)
        if coords and shapely.Point(c[-1]).distance(shapely.Point(coords[-1])) < shapely.Point(c[0]).distance(shapely.Point(coords[-1])):
            c = c[::-1]
        turned.append(shapely.LineString(c))
        s0 = shapely.LineString(coords).length if len(coords) > 1 else 0.0
        coords += c[1:] if coords and shapely.Point(c[0]).distance(shapely.Point(coords[-1])) < 0.01 else c
        ranges.append((s0, s0 + ln.length))
    return (shapely.LineString(coords) if len(coords) > 1 else None), ranges, turned


MIN_PART_M2 = 2.0    # a part under this joins the part of its side it shares the longest edge with (docs/design/parts.md)


def cut_intersection(geom, nodes, rings=(), islands=()):
    """An intersection's rank 3 (docs/design/spaces.md): [(key, geometry)], one piece per junction node (key: the node), the ground
    nearer to that node than to the intersection's other nodes; a roundabout (its ring's lines `rings`) also its centre (key
    "centre"): the islands inside the ring. A piece of a node's cell that lies apart joins the piece it shares the longest edge with."""
    import shapely
    centre = None
    if rings:
        inside = shapely.union_all(list(shapely.get_parts(shapely.polygonize(shapely.get_parts(shapely.line_merge(shapely.union_all(list(rings))))))) or [shapely.Polygon()])
        isl = [x for x in islands if not inside.is_empty and inside.contains(x.representative_point())]
        if isl:
            centre = shapely.union_all(isl).intersection(geom)
            centre = centre if centre.area >= MIN_PART_M2 else None
    rest = geom.difference(centre) if centre is not None else geom
    pts = {}
    for k, pt in nodes.items():         # (two nodes at one place: one piece, the smaller id)
        if not any(pt.distance(q) < 0.01 for q in pts.values()):
            pts[k] = pt
    if len(pts) <= 1:
        out = [(next(iter(pts), None), rest)]
    else:
        vor = list(shapely.get_parts(shapely.voronoi_polygons(shapely.MultiPoint(list(pts.values())), extend_to=geom.envelope.buffer(100))))
        cells, loose = {}, []
        for k, pt in pts.items():
            cell = next((c for c in vor if c.covers(pt)), None)
            got = [q for q in shapely.get_parts(rest.intersection(cell)) if q.geom_type == "Polygon" and q.area > 0.01] if cell is not None else []
            if got:
                got.sort(key=lambda q: -q.area)
                cells[k] = got[0]
                loose += got[1:]
        for q in loose:
            k = max(cells, key=lambda k_: q.buffer(0.05).intersection(cells[k_].boundary).length)
            cells[k] = shapely.union_all([cells[k], q])
        out = list(cells.items())
    if centre is not None:
        out.append(("centre", centre))
    return out


def _k(space_id):
    return int(space_id.rsplit("/", 1)[1]) if "/" in space_id and space_id.rsplit("/", 1)[1].isdigit() else 0


def write(con, epsg, out=None):
    """Every table of urban from work. The tables of an older build that are not the model's are dropped."""
    import shapely
    from .network import shift_line
    from .schema import MODEL
    W = Writer(con, epsg)
    con.execute("CREATE SCHEMA IF NOT EXISTS urban")
    for (t,) in W.rows("SELECT table_name FROM information_schema.tables WHERE table_schema = 'urban' AND table_type = 'BASE TABLE'"):
        if t not in MODEL:
            con.execute(f'DROP TABLE urban."{t}"')
    con.execute("DROP VIEW IF EXISTS urban.item")
    g = W.g

    # ---- the working rows, in metres
    units = {u: dict(kind=k, section=s, level=lv, geom=g(w)) for u, k, s, lv, w in
             W.rows(f"SELECT unit_id, kind, section_id, level, {W.m()} FROM work.unit")}
    subs = {s: dict(section=sec, level=lv, cls=cl, width=wd, oneway=ow, length=ln, left_extra=le, line=g(w)) for s, sec, lv, cl, wd, ow, ln, le, w in
            W.rows(f"SELECT subsection_id, section_id, level, class, width_m, oneway, length_m, left_extra, {W.m()} FROM work.subsection")}
    pcols = [c for c, _ in W.rows("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'work' "
                                  "AND table_name = 'part' ORDER BY ordinal_position") if c != "geometry"]
    # (a part's shape made valid can come back as a collection: a sliver that touches itself after the round trip to metres. A part is a polygon.)
    polygonal = lambda x: x if x is None or x.geom_type in ("Polygon", "MultiPolygon") else shapely.union_all(
        [p_ for q_ in shapely.get_parts(x) for p_ in shapely.get_parts(q_) if p_.geom_type == "Polygon"] or [shapely.Polygon()])
    parts = [dict(zip(pcols, r[:-1]), geom=polygonal(g(r[-1]))) for r in W.rows(f"SELECT {', '.join(q(c) for c in pcols)}, {W.m()} FROM work.part")]
    mcols = [c for c, _ in W.rows("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'work' "
                                  "AND table_name = 'mark' ORDER BY ordinal_position") if c != "geometry"]
    marks = [dict(zip(mcols, r[:-1]), geom=g(r[-1])) for r in W.rows(f"SELECT {', '.join(q(c) for c in mcols)}, {W.m()} FROM work.mark")]
    wground = [dict(id=i, kind=t, level=lv, name=n, source=s, method=me, ref=r, geom=g(w)) for i, t, lv, n, s, me, r, w in
               W.rows(f"SELECT ground_id, type, level, name, source, method, ref, {W.m()} FROM work.ground")]
    levels = sorted({u["level"] for u in units.values()} | {x["level"] for x in wground} | {0})

    def best(child, cands):
        """The candidate (id, geometry) that holds the most of `child`: the one that covers its inner point, else the largest overlap."""
        if not cands or child is None:
            return None
        pt = child.representative_point()
        inside = [c for c in cands if c[1].covers(pt)]
        if inside:
            return min(inside, key=lambda c: c[1].area)[0]
        near = [c for c in cands if c[1].intersects(child)]
        if not near:
            return None
        return max(near, key=lambda c: c[1].intersection(child).area if child.area else -c[1].distance(pt))[0]

    # ---- rank 0: the area
    area = shapely.union_all([g(w) for (w,) in W.rows(f"SELECT {W.m()} FROM work.area")] or [shapely.Polygon()])
    has_boundary = bool(W.rows("SELECT 1 FROM duckdb_views() WHERE view_name = 'osm_boundary'"))
    name = os.path.basename(out).split(".")[0] if out else None
    W.table("area", [(f"a{lv}", "area", 0, None, lv, name, "osm" if has_boundary else "urbanstyle", "mapped" if has_boundary else "chosen",
                      "boundary" if has_boundary else "the box round the elements", area) for lv in levels])

    # ---- the elements
    lanes = {}
    for oid, s_, t_, n in W.rows("SELECT osm_id, source, target, lanes FROM osm.driving.edges"):
        lanes[(oid, s_, t_)] = n
    els, seen_way = [], {}
    for r in W.rows(f"""SELECT type, class, subtype, name, osm_id, source_id, NULL AS uid, oneway, src, dst, width_m, width_src, level_min, level_max,
                        level_src, floors, height_m, use, use_source, use_method, ground_use, ground_source, ground_method, source, {W.m()}
                        FROM work.element ORDER BY type, osm_id, src, dst"""):
        (typ, cls, sub, nm, oid, sid, uid, ow, src, dst, wd, wsrc, lmin, lmax, lsrc, fl, h, use, us, um, gu, gs, gm, source, w) = r
        if typ == "building" or oid is None:
            eid = sid
        else:
            seen_way[oid] = seen_way.get(oid, 0) + 1
            eid = f"w{oid}" + (f".{seen_way[oid]}" if seen_way[oid] > 1 else "")
        fw = lanes.get((oid, src, dst)) if typ == "road" else None
        bw = lanes.get((oid, dst, src)) if typ == "road" else None
        els.append((eid, typ, cls, sub, nm, oid, sid, None, ow, fw, bw, wd, wsrc, lmin, lmax, lsrc, fl, h, use, us, um, gu, gs, gm, source, g(w)))
    els += [(lid, "lot", t, None, nm, None, lid, None, None, None, None, None, None, lv, lv, "layer", None, None, None, None, None, None,
             None, None, "osm", g(w)) for lid, t, nm, lv, w in W.rows(f"SELECT lot_id, type, name, level, {W.m()} FROM work.lot")]
    W.table("element", els)

    # ---- rank 1: the street, the plots, the paths
    street_pieces = {}
    rows1 = []
    for lv in levels:
        pieces = [x["geom"] for x in wground if x["level"] == lv and x["kind"] == "street"] or [u["geom"] for u in units.values() if u["level"] == lv]
        polys = sorted((p for p in shapely.get_parts(shapely.union_all(pieces)) if p.geom_type == "Polygon"), key=lambda p: -p.area) if pieces else []
        street_pieces[lv] = [(f"g{lv}-street-{n}", p) for n, p in enumerate(polys, 1)]
        rows1 += [(i, "street", 1, f"a{lv}", lv, None, None, None, None, None, "urbanstyle", "derived",
                   "the area less the blocks and the corridors" if lv == 0 else "the spaces of the level", p) for i, p in street_pieces[lv]]
    sides = {}
    for b, way, nm, cl, dist, basis, meth in W.rows("SELECT block_id, way_id, name, class, distance_m, basis, method FROM work.block_side"):
        sides.setdefault(b, []).append(dict(way=f"w{way}", name=nm, **{"class": cl}, distance_m=dist, set_by=basis, method=meth))
    plots = {}
    for b, lv, s, me, w in W.rows(f"SELECT block_id, level, source, method, {W.m()} FROM work.block"):
        pid = f"g{lv}-plot-{b}"
        plots.setdefault(lv, []).append((pid, g(w)))
        rows1.append((pid, "plot", 1, f"a{lv}", lv, None, sides.get(b), None, None, None, s or "urbanstyle", me or "derived", b, plots[lv][-1][1]))
    corr = {c: (nm, wd, ws, wm) for c, nm, wd, ws, wm in W.rows("SELECT corridor_id, name, width_m, width_source, width_method FROM work.corridor")}
    for x in wground:
        if x["kind"] == "path":
            nm, wd, ws, wm = corr.get(x["ref"], (x["name"], None, None, None))
            rows1.append((x["id"], "path", 1, f"a{x['level']}", x["level"], nm, None, wd, ws, wm, x["source"], x["method"], x["ref"], x["geom"]))
    W.table("ground", rows1)

    # ---- rank 2 and 3: sections, intersections, subsections
    by_section = {}
    for s, d in subs.items():
        by_section.setdefault(d["section"], []).append(s)
    lane_parts = [p for p in parts if p["type"] == "lane"]
    ways_of, roads_of = {}, {}
    for p in parts:
        for w_ in re.findall(r"\bw(\d+)", str(p.get("ref") or "")):
            ways_of.setdefault(p["unit_id"], []).append((p["geom"].centroid, f"w{w_}"))
        if p["type"] == "lane" and p.get("road"):
            roads_of.setdefault(p["unit_id"], []).append(p["road"])
    common = lambda xs: max(set(xs), key=xs.count) if xs else None
    inters = {u: d for u, d in units.items() if d["kind"] == "intersection"}
    node_pt = {n: g(w) for n, w in W.rows(f"""SELECT src, {W.m('ST_StartPoint(geometry)')} FROM work.element WHERE type = 'road' AND src IS NOT NULL
                                             UNION SELECT dst, {W.m('ST_EndPoint(geometry)')} FROM work.element WHERE type = 'road' AND dst IS NOT NULL""")}
    jnodes = {}
    for i_, n, lv, cl in W.rows("SELECT intersection_id, node_id, level, cluster_id FROM work.junction"):
        jnodes.setdefault(i_, []).append(n)
    way_street = {f"w{o}": s for s, o in W.rows("SELECT street_id, osm_id FROM work.arm WHERE osm_id IS NOT NULL")}
    name_street = {(n, lv): s for s, n, lv in W.rows("SELECT street_id, name, level FROM work.street WHERE name IS NOT NULL")}

    sections, space_rows, preds, succs = {}, {}, {}, {}
    for sec, ids in by_section.items():
        ids = sorted(ids, key=_k)
        ids = [s for s in ids if subs[s]["line"] is not None] + [s for s in ids if subs[s]["line"] is None]
        axis, ranges, turned = _chain([subs[s]["line"] for s in ids if subs[s]["line"] is not None])
        lv = subs[ids[0]]["level"]
        geom = shapely.union_all([units[s]["geom"] for s in ids if s in units] or [shapely.Polygon()])
        ways = []
        for s in ids:
            for pt, w_ in sorted(ways_of.get(s, []), key=lambda x: axis.project(x[0]) if axis is not None else 0):
                if w_ not in ways:
                    ways.append(w_)
        naming = re.match(r"s-?\d+-(w\d+)", sec)
        if not ways and naming:
            ways = [naming.group(1)]
        nm = common(sum((roads_of.get(s, []) for s in ids), []))
        ends = [None, None]
        if axis is not None:
            for e, pt in enumerate((shapely.Point(axis.coords[0]), shapely.Point(axis.coords[-1]))):
                near = [(d["geom"].distance(pt), i_) for i_, d in inters.items() if d["level"] == lv and d["geom"].distance(pt) < END_M]
                ends[e] = min(near)[1] if near else None
        nodes = []
        for e, i_ in enumerate(ends):
            if i_ and axis is not None:
                pt = shapely.Point(axis.coords[0 if e == 0 else -1])
                cand = [n for n in jnodes.get(i_, []) if n in node_pt]
                nodes.append(min(cand, key=lambda n: node_pt[n].distance(pt)) if cand else None)
            else:
                nodes.append(None)
        street_id = way_street.get(naming.group(1)) if naming else None
        street_id = street_id or name_street.get((nm, lv))
        sections[sec] = dict(level=lv, axis=axis, ids=ids, ways=ways, name=nm, ends=ends, nodes=nodes, street=street_id, geom=geom,
                             cls=common([subs[s]["cls"] for s in ids if subs[s]["cls"]]), oneway=all(subs[s]["oneway"] for s in ids),
                             length=axis.length if axis is not None else None)
        for j, s in enumerate(ids):
            preds[s] = [ids[j - 1]] if j else ([ends[0]] if ends[0] else [])
            succs[s] = [ids[j + 1]] if j + 1 < len(ids) else ([ends[1]] if ends[1] else [])
            if s in units:
                sl = subs[s]
                space_rows[s] = [s, "subsection", 3, sec, sl["level"], nm, turned[j] if j < len(turned) else None,
                                 *(ranges[j] if j < len(ranges) else (None, None)),
                                 sl["width"], sl["oneway"], sl["length"], sl["left_extra"]]

    # ---- rank 3 of an intersection: its sub-intersections, one per junction node; a roundabout's ring sectors and centre
    rb_lines = [g(w) for (w,) in W.rows(f"SELECT {W.m()} FROM osm.driving.edges WHERE junction IN ('roundabout', 'circular')")]
    subint, sub_of = {}, {}
    for i_, d in inters.items():
        rings = [ln for ln in rb_lines if ln.intersection(d["geom"]).length > 5.0]
        d["roundabout"] = bool(rings)
        nodes = {n: node_pt[n] for n in jnodes.get(i_, []) if n in node_pt}
        isl = [p["geom"] for p in parts if p["unit_id"] == i_ and p["type"] == "island"]
        for key, gm in cut_intersection(d["geom"], nodes, rings, isl):
            sid = f"{i_}/{key if key is not None else i_.split('-', 1)[1]}"
            subint[sid] = dict(parent=i_, kind="centre" if key == "centre" else ("ring sector" if rings else "sub-intersection"),
                               node=key, level=d["level"], geom=gm)
            sub_of.setdefault(i_, []).append(sid)
    near_sub = lambda i_, pt: min(sub_of[i_], key=lambda sid: subint[sid]["geom"].distance(pt)) if sub_of.get(i_) else i_
    # the intersections' parts cut along the same lines (a part never crosses a cut); one junction area per sub-intersection
    split, n_of = [], {}
    for p in parts:
        if p["unit_id"] not in sub_of:
            split.append(p)
            continue
        for sid in sub_of[p["unit_id"]]:
            piece = p["geom"].intersection(subint[sid]["geom"])
            piece = [q for q in shapely.get_parts(piece) if q.geom_type == "Polygon" and q.area > 0.01]
            if piece:
                split.append(dict(p, unit_id=sid, geom=shapely.union_all(piece), orig=p["part_id"]))
    ja = {}
    for p in split:
        if p["unit_id"] in subint and p["type"] == "junction area":
            ja.setdefault(p["unit_id"], []).append(p)
    keep = {id(v[0]) for v in ja.values()}
    for sid, ps in ja.items():
        ps[0]["geom"] = shapely.union_all([x["geom"] for x in ps])
    split = [p for p in split if not (p["unit_id"] in subint and p["type"] == "junction area" and id(p) not in keep)]
    # a part under MIN_PART_M2 joins the part of its side it shares the longest edge with
    side_of = lambda p: (p["unit_id"], p["type"] in WALKING)
    by_side = {}
    for p in split:
        by_side.setdefault(side_of(p), []).append(p)
    gone = set()
    for p in sorted(split, key=lambda p: p["geom"].area):
        if p["geom"].area >= MIN_PART_M2:
            break
        nb = [x for x in by_side[side_of(p)] if x is not p and id(x) not in gone]
        if not nb:
            continue
        best_ = max(nb, key=lambda x: p["geom"].buffer(0.05).intersection(x["geom"].boundary).length)
        if p["geom"].buffer(0.05).intersection(best_["geom"].boundary).length <= 0:
            continue
        best_["geom"] = shapely.union_all([best_["geom"], p["geom"]])
        gone.add(id(p))
    parts = [p for p in split if id(p) not in gone]
    for p in sorted([p for p in parts if p["unit_id"] in subint], key=lambda p: (p["unit_id"], p["orig"])):
        n_of[p["unit_id"]] = n_of.get(p["unit_id"], 0) + 1
        p["part_id"] = f"{p['unit_id']}#{n_of[p['unit_id']]}"
    lane_parts = [p for p in parts if p["type"] == "lane"]
    for mk in marks:            # an intersection's mark lies in the sub-intersection that holds its middle
        if mk["unit_id"] in sub_of:
            mk["unit_id"] = near_sub(mk["unit_id"], mk["geom"].representative_point())
    for i_ in inters:
        units.pop(i_, None)
    for sid, sd in subint.items():
        units[sid] = dict(kind=sd["kind"], section=None, level=sd["level"], geom=sd["geom"])
    # the links: a section's end goes to the sub-intersection its axis reaches; a sub-intersection's from its arms and its neighbours
    for sec, sd in sections.items():
        sd["ends_sub"] = [near_sub(i_, shapely.Point(sd["axis"].coords[0 if e == 0 else -1])) if i_ and sd["axis"] is not None else i_
                          for e, i_ in enumerate(sd["ends"])]
        if sd["ids"]:
            if sd["ends_sub"][0]:
                preds[sd["ids"][0]] = [sd["ends_sub"][0]]
            if sd["ends_sub"][1]:
                succs[sd["ids"][-1]] = [sd["ends_sub"][1]]
    sp, ss = dict(preds), dict(succs)
    for sid in subint:
        nb = [o for o in sub_of[subint[sid]["parent"]] if o != sid and _touch(subint[sid]["geom"], subint[o]["geom"]) >= TOUCH_M]
        preds[sid] = sorted({s for s, v in ss.items() if sid in v} | {s for s, v in sp.items() if sid in v and not subs[s]["oneway"]} | set(nb))
        succs[sid] = sorted({s for s, v in sp.items() if sid in v} | {s for s, v in ss.items() if sid in v and not subs[s]["oneway"]} | set(nb))

    iname = lambda i_: " / ".join(sorted(set(roads_of.get(i_, [])))) or None
    rows2 = []
    for sec, d in sections.items():
        par = best(d["geom"], street_pieces.get(d["level"], []))
        rows2.append((sec, "section", 2, par, d["level"], d["name"], d["street"], d["ways"], [n for n in d["nodes"] if n is not None],
                      d["cls"], d["oneway"], d["length"], d["axis"], "urbanstyle", "derived", ",".join(d["ways"]), d["geom"]))
    for i_, d in inters.items():
        ways = list(dict.fromkeys(w_ for _, w_ in ways_of.get(i_, [])))
        rows2.append((i_, "roundabout" if d["roundabout"] else "intersection", 2, best(d["geom"], street_pieces.get(d["level"], [])), d["level"], iname(i_), None, ways,
                      sorted(jnodes.get(i_, [])), None, None, None, None, "urbanstyle", "derived", ",".join(ways), d["geom"]))
    paths = [dict(zip(("id", "kind", "ground", "level", "name", "cls", "ways", "nodes", "wd", "ws", "wm", "length", "pred", "succ"), r[:-2]),
                  axis=g(r[-2]), geom=g(r[-1])) for r in W.rows(f"""SELECT space_id, kind, ground_id, level, name, class, ways, nodes, width_m,
                  width_source, width_method, length_m, predecessors, successors, {W.m('axis')}, {W.m()} FROM work.path_space""")]
    for x in paths:
        rows2.append((x["id"], x["kind"], 2, x["ground"], x["level"], x["name"], None, x["ways"], x["nodes"], x["cls"],
                      False if x["kind"] == "path section" else None, x["length"], x["axis"], "urbanstyle", "derived", ",".join(x["ways"]), x["geom"]))
    W.table("stretch", rows2)

    # plot pieces
    surf_of = {}
    for sid, gid in W.rows("SELECT surface_id, ground_id FROM work.surface"):
        surf_of.setdefault(gid, []).append(sid)
    owidth = {f"w{o}": float(w_) for o, w_ in W.rows("""SELECT osm_id, try_cast(regexp_extract(tags['width'], '[0-9.]+') AS DOUBLE)
                                                      FROM osm.raw.ways WHERE tags['width'] IS NOT NULL""") if w_}
    from .ground import ALLEY_W_M
    pieces = []
    for x in wground:
        if x["kind"] in ("street", "path"):
            continue
        wd = ws = wm = None
        if x["kind"] == "alley":
            way = (re.search(r"w\d+", str(x["ref"] or x["id"])) or [None])[0]
            wd, ws, wm = (owidth[way], "osm", "mapped") if way in owidth else (ALLEY_W_M, "urbanstyle", "chosen")
        pieces.append((x["id"], x["kind"], 2, best(x["geom"], plots.get(x["level"], [])), x["level"], x["name"], wd, ws, wm,
                       sorted(surf_of.get(x["id"], [])), x["source"], x["method"], x["ref"], x["geom"]))
    W.table("plot_piece", pieces)
    W.table("joint", [(sec, lv, a, b, wa, wb, la, lb, xa, xb, cl, nt, g(w)) for sec, lv, a, b, wa, wb, la, lb, xa, xb, cl, nt, w in W.rows(
        f"SELECT section_id, level, subsection_a, subsection_b, way_a, way_b, lanes_a, lanes_b, width_a, width_b, class, note, {W.m()} FROM work.change")])

    # the arms and the named streets
    arms = []
    for i_, d in inters.items():
        for sec, sd in sections.items():
            if i_ in sd["ends"]:
                naming = re.match(r"s-?\d+-(w\d+)", sec)
                arms.append((i_, sd["street"], sec, naming.group(1) if naming else None, d["level"]))
    W.table("arm", arms)
    streets = {}
    for sec, sd in sections.items():
        if sd["street"]:
            streets.setdefault(sd["street"], dict(level=sd["level"], sections=[], inters=set(), names=[]))
            streets[sd["street"]]["sections"].append(sec)
            streets[sd["street"]]["inters"] |= {e for e in sd["ends"] if e}
            if sd["name"]:
                streets[sd["street"]]["names"].append(sd["name"])
    W.table("street", [(k, common(v["names"]), v["level"], sorted(v["sections"]), sorted(v["inters"]),
                        shapely.union_all([sections[s]["geom"] for s in v["sections"]] + [inters[i_]["geom"] for i_ in v["inters"]]))
                       for k, v in streets.items()])

    # ---- rank 3: the spaces
    rows3 = []
    for u, d in units.items():
        ways = list(dict.fromkeys(w_ for _, w_ in ways_of.get(subint[u]["parent"] if u in subint else u, [])))
        if u in space_rows:
            rows3.append((*space_rows[u], preds.get(u, []), succs.get(u, []), "urbanstyle", "derived", ",".join(ways), d["geom"]))
        elif u in subint:
            i_ = subint[u]["parent"]
            rows3.append((u, subint[u]["kind"], 3, i_, d["level"], iname(i_), None, None, None, None, None, None, None, preds.get(u, []),
                          succs.get(u, []), "urbanstyle", "derived", ",".join(ways), d["geom"]))
        else:       # a space whose subsection has no row (a level with no subsections)
            rows3.append((u, d["kind"], 3, d["section"] or u, d["level"], None, None, None, None, None, None, None, None, [], [],
                          "urbanstyle", "derived", ",".join(ways), d["geom"]))
    for x in paths:
        rows3.append((x["id"], x["kind"], 3, x["id"], x["level"], x["name"], x["axis"], 0.0 if x["axis"] is not None else None,
                      x["length"], x["wd"], False if x["kind"] == "path section" else None, x["length"], None, x["pred"], x["succ"],
                      "urbanstyle", "derived", ",".join(x["ways"]), x["geom"]))
    W.table("space", rows3)
    W.table("junction", [(i_, n, lv, cl, f"{i_}/{n}" if f"{i_}/{n}" in subint else (near_sub(i_, node_pt[n]) if n in node_pt else None))
                          for i_, n, lv, cl in W.rows("SELECT intersection_id, node_id, level, cluster_id FROM work.junction")])
    axis_of = {u: space_rows[u][6] for u in space_rows}
    s0_of = {u: space_rows[u][7] for u in space_rows}

    # ---- rank 5 first (rank 4 is its parts joined)
    for p in parts:
        p["side"] = f"{p['unit_id']}:{'w' if p['type'] in WALKING else 'd'}"
        ax = axis_of.get(p["unit_id"])
        st = _st(ax, p["geom"]) if ax is not None else (None,) * 4
        off = s0_of.get(p["unit_id"]) or 0.0
        p["st"] = tuple(None if v is None else round(v + off if i < 2 else v, 3) for i, v in enumerate(st))
        p["axis"] = None
        if ax is not None and st[0] is not None and p["type"] not in NO_AXIS and st[1] - st[0] > 0.5:
            import shapely.ops
            piece = shapely.ops.substring(ax, st[0], st[1])
            if piece.geom_type == "LineString" and piece.length > 0:
                a_ = shift_line(piece, (st[2] + st[3]) / 2)
                p["axis"] = a_.reverse() if p.get("direction") == "backward" else a_
        p["pred"], p["succ"] = set(), set()
    # a road part's speed limit: duckOSM's, the largest on its way's edges (km/h)
    speed = {f"w{o}": v for o, v in W.rows("SELECT osm_id, max(maxspeed_kmh) FROM osm.driving.edges WHERE maxspeed_kmh IS NOT NULL GROUP BY 1")}
    for p in parts:
        w_ = re.match(r"(w\d+)", str(p.get("ref") or ""))
        p["ref_way"] = w_.group(1) if w_ and p["type"] not in WALKING else None
    # the lane links: at a joint, at an arm, through an intersection (docs/design/tables.md, "The links")
    by_unit = {}
    for p in lane_parts:
        by_unit.setdefault(p["unit_id"], []).append(p)

    def link(a, b):
        a["succ"].add(b["part_id"])
        b["pred"].add(a["part_id"])
    for sec, sd in sections.items():
        ids = sd["ids"]
        for s1, s2 in zip(ids, ids[1:]):
            for a in by_unit.get(s1, []):
                for b in by_unit.get(s2, []):
                    if a.get("direction") == b.get("direction") and a.get("lane") == b.get("lane") and _touch(a["geom"], b["geom"]) >= TOUCH_M:
                        link(a, b) if a.get("direction") != "backward" else link(b, a)
        for e, i_ in enumerate(sd["ends_sub"]):
            if not i_:
                continue
            s_end = ids[0] if e == 0 else ids[-1]
            for a in by_unit.get(s_end, []):
                for b in by_unit.get(i_, []):
                    if a.get("road") == b.get("road") and _touch(a["geom"], b["geom"]) >= TOUCH_M:
                        into = (e == 1) == (a.get("direction") != "backward")        # the lane runs into the intersection
                        link(a, b) if into else link(b, a)
    # a turn starts in the lane that arrives (in the subsection before the stop line, or in the intersection) and ends in the lane
    # that leaves: the lanes of the intersection and of the subsections at its arms
    for u, w in W.rows(f"SELECT unit_id, {W.m()} FROM work.turn"):
        ln = g(w)
        mine = sub_of.get(u, [u])
        cands = [p for s_ in mine for p in by_unit.get(s_, [])] + [p for s_ in mine for s in set(preds.get(s_, [])) | set(succs.get(s_, []))
                                                                   if s not in mine for p in by_unit.get(s, [])]
        if ln is None or ln.is_empty or not cands:
            continue
        ln = next(iter(shapely.get_parts(ln)))
        a_pt, b_pt = shapely.Point(ln.coords[0]), shapely.Point(ln.coords[-1])
        near = lambda pt: min(cands, key=lambda p: p["geom"].distance(pt))
        a, b = near(a_pt), near(b_pt)
        if a is not b and a["geom"].distance(a_pt) < TURN_M and b["geom"].distance(b_pt) < TURN_M:
            link(a, b)
    for x in paths:
        st = _st(x["axis"], x["geom"]) if x["axis"] is not None else (None,) * 4
        parts.append({"part_id": f"{x['id']}#1", "type": "steps" if x["cls"] == "steps" else "path", "side": f"{x['id']}:w",
                      "level": x["level"], "unit_id": x["id"], "axis": x["axis"], "st": tuple(None if v is None else round(v, 3) for v in st),
                      "pred": set(), "succ": set(), "width_m": x["wd"], "width_source": x["ws"], "width_method": x["wm"],
                      "length_m": x["length"], "source": "urbanstyle", "method": "derived", "ref": ",".join(x["ways"]), "geom": x["geom"]})
    W.table("part", [(p["part_id"], p["type"], 5, p["side"], p["level"], None, p["unit_id"], p.get("arm"), p.get("direction"), p.get("lane"),
                      p.get("lane_id"), p["axis"], *p["st"], sorted(p["pred"]), sorted(p["succ"]), p.get("width_m"), p.get("width_source"),
                      p.get("width_method"), p.get("length_m"), p.get("position_source"), p.get("position_method"), p.get("position_ref"),
                      p.get("road"), p.get("road_class"), speed.get(p.get("ref_way")), p.get("surface"), p.get("lit"), p.get("road_lanes"), p.get("oneway"),
                      p.get("holds"), p.get("rule"), p.get("source"), p.get("method"), p.get("ref"), p["geom"]) for p in parts])

    # ---- rank 4: the sides, with the kerb
    kerbs = {}
    for mk in marks:
        if mk["type"] == "kerb":
            kerbs.setdefault(mk["unit_id"], []).append(mk)
    sides4 = {}
    for p in parts:
        sides4.setdefault(p["side"], [p["unit_id"], p["level"], []])[2].append(p["geom"])
    rows4 = []
    for sid, (u, lv, gs) in sides4.items():
        k = kerbs.get(u, []) if sid.endswith(":d") else []
        kline = shapely.union_all([x["geom"] for x in k]) if k else None
        rows4.append((sid, "walking" if sid.endswith(":w") else "driving", 4, u, lv, None, kline,
                      common([x.get("source") for x in k if x.get("source")]), common([x.get("method") for x in k if x.get("method")]),
                      "urbanstyle", "derived", None, shapely.union_all(gs)))
    W.table("side", rows4)

    # ---- rank 6: the marks
    pby = {}
    for p in parts:
        pby.setdefault(p["unit_id"], []).append((p["part_id"], p["geom"]))
    seq, rows6 = {}, []
    for mk in sorted(marks, key=lambda m: (m["unit_id"] or "", m["type"] or "", m["geom"].centroid.x, m["geom"].centroid.y)):
        u, t = mk["unit_id"], mk["type"]
        seq[(u, t)] = seq.get((u, t), 0) + 1
        if t == "kerb":
            par, prank = f"{u}:d", 4
        else:
            par, prank = best(mk["geom"], pby.get(u, [])), 5
        ax = axis_of.get(u)
        st = _st(ax, mk["geom"]) if ax is not None else (None,) * 4
        off = s0_of.get(u) or 0.0
        st = tuple(None if v is None else round(v + off if i < 2 else v, 3) for i, v in enumerate(st))
        rows6.append((f"{u}:{t}:{seq[(u, t)]}", t, 6, par, mk["level"], None, prank, u, *st, mk.get("width_m"), mk.get("width_source"),
                      mk.get("width_method"), mk.get("length_m"), mk.get("source"), mk.get("method"), mk.get("ref"), mk["geom"]))
    W.table("mark", rows6)
    first_pt = lambda gm: shapely.Point(next(iter(shapely.get_parts(gm))).coords[0]) if gm is not None and not gm.is_empty else None
    W.table("turn", [(near_sub(u, first_pt(g(w))) if first_pt(g(w)) is not None else u, lv, fe, fl, te, tl, tn, vh, cd, src, g(w))
                     for u, lv, fe, fl, te, tl, tn, src, vh, cd, w in W.rows(
        f"SELECT unit_id, level, from_edge, from_lane, to_edge, to_lane, turn, source, vehicles, condition, {W.m()} FROM work.turn")])
    W.table("approach", W.rows("SELECT unit_id, level, from_edge, lane, moves, ways, arrow, no_arrow_because FROM work.approach"))

    # ---- on the tree
    _objects(W, con, epsg, out, units, parts)
    links, seen = [], {}
    for n, la, lb, t, sid, w in W.rows(f"SELECT node_id, level_a, level_b, type, station_id, {W.m()} FROM work.link ORDER BY node_id, level_a, level_b"):
        seen[n] = seen.get(n, 0) + 1
        links.append((f"{n}" + (f".{seen[n]}" if seen[n] > 1 else ""), t, la, lb, n, sid, g(w)))
    W.table("link", links)
    W.table("station", [(i_, k, nm, lv, g(w)) for i_, nm, k, lv, w in W.rows(f"SELECT id, name, kind, level, {W.m()} FROM work.station")])
    W.table("surface", [(s, gid, k, lv, src, me, r, g(w)) for s, gid, lv, k, src, me, r, w in W.rows(
        f"SELECT surface_id, ground_id, level, type, source, method, ref, {W.m()} FROM work.surface")])
    W.table("observed", [(f, k, gr, a, b, s, g(w)) for f, k, gr, a, b, s, w in W.rows(
        f"SELECT feature_id, class, grp, first_seen, last_seen, source, {W.m()} FROM work.observed")])
    W.table("photo", [(i_, c, cp, pn, sq, g(w)) for i_, c, cp, pn, sq, w in W.rows(
        f"SELECT photo_id, captured, compass, is_pano, sequence, {W.m()} FROM work.photo")])

    # ---- the view over the tree
    con.execute("CREATE OR REPLACE VIEW urban.item AS " + " UNION ALL ".join(
        f"SELECT {idc} AS id, rank, kind, parent_id, level, geometry FROM urban.{t}" for t, idc in RANKED))
    return {t: con.execute(f'SELECT count(*) FROM urban."{t}"').fetchone()[0] for t in COLUMNS}


def _objects(W, con, epsg, out, units, parts):
    """urban.object: one row per real thing from every source (objects.matched_objects); a thing only Mapillary sees is not a row. Its
    size: a source's measurement, else urbanstyle's chosen size for its class (unit.SIZE)."""
    import shapely
    from .objects import matched_objects
    from .unit import SIZE
    osm = {o: (nm, at) for o, nm, at in W.rows("SELECT object_id, name, attrs::VARCHAR FROM work.object")}
    ulist = [(u, d["level"], d["geom"]) for u, d in units.items()]
    plist = [(p["part_id"], p["unit_id"], p["geom"]) for p in parts]
    rows = []
    for oid, cls, lv, grp, p, refs, sources, h, details, methods, wd in matched_objects(con, epsg, out or ""):
        if sources == "mapillary":
            continue
        inside = [u for u, l_, gm in ulist if l_ == lv and gm.covers(p)]
        near_m = None
        if inside:
            space = inside[0]
        else:
            cand = [(gm.distance(p), u) for u, l_, gm in ulist if l_ == lv and gm.distance(p) <= NEAR_M]
            space, near_m = (min(cand)[1], round(min(cand)[0], 2)) if cand else (None, None)
        part = next((pid for pid, u, gm in plist if u == space and gm.covers(p)), None) if inside else None
        w0, h0 = SIZE.get(cls, (None, None))
        meas = lambda x: (x[1].split(" (")[0], x[1].split(" (")[1].rstrip(")")) if x and " (" in x[1] else ("urbanstyle", "chosen")
        ws, wm = meas(wd) if wd else ("urbanstyle", "chosen")
        hs, hm = meas(h) if h else ("urbanstyle", "chosen")
        src = sources.split(", ")[0]
        nm, at = osm.get(str(oid), (None, None))
        rows.append((str(oid), cls, None, lv, space, part, near_m, nm, at, wd[0] if wd else w0, ws if (wd or w0) else None,
                     wm if (wd or w0) else None, h[0] if h else h0, hs if (h or h0) else None, hm if (h or h0) else None, sources, refs, src,
                     methods.split("; ")[0].split(": ", 1)[-1], p))
    W.table("object", rows)
