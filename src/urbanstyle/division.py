"""The division built top down, rank by rank (docs/design/division-top-down.md, 2026-10-16). Rank 3 first: one partition of rank 1's
street into the spaces.

    rank 1   the street of the level: the area less the blocks and the corridors (work.area, work.block, work.corridor), one polygon
    cuts     every arm's stop line (work.mark, type `stop line`: where a section's lanes enter the junction) and every joint between two
             subsections of a section (the end of one subsection's axis where the next begins), each run square to its road across the
             street to the blocks' edges (CUT_M each way)
    rank 3   the street noded with the cuts and polygonized: each face is one space, whole, corners included. A face between a junction's
             arm cuts is that intersection's, a face between two cuts along a road is that section's: the roadway (the old parts of type
             lane, paved, junction area, crosswalk) with the most area inside the face owns it; a face with no roadway in it joins the
             neighbour it shares the most edge with

work.space3   space_id (the owner's unit id of rank 2/3, `#n` where an owner's faces lie apart), kind (subsection / intersection),
               section_id, level, faces, area_m2, geometry. The old `work.unit` stays beside it until the new division replaces it.
Check U14: the spaces of rank 3 add up to the street (gap under 1 m2) and overlap by under 0.05 m2 (the same test as G2, G3 for rank 1).
"""
CUT_M = 60.0        # a cut runs this far to each side of its road, across the street to the blocks (as network.CUT_M)
MIN_FACE_M2 = 0.01  # a face smaller than this is a hairline of the noding


def build(con, epsg, level=0):
    import duckdb
    import shapely
    m = lambda col="geometry": f"ST_AsWKB(ST_Transform({col}, 'EPSG:4326', '{epsg}', always_xy := true))"
    g = lambda w: shapely.make_valid(shapely.from_wkb(bytes(w)))
    poly = lambda x: shapely.union_all([p for p in shapely.get_parts(x) if p.geom_type == "Polygon"] or [shapely.Polygon()])

    def rows(sql, params=None):
        try:
            return con.execute(sql, params or []).fetchall()
        except duckdb.CatalogException:
            return []

    # ---- rank 1: the street
    area = shapely.union_all([g(w) for (w,) in rows(f"SELECT {m()} FROM work.area")] or [shapely.Polygon()])
    blocks = shapely.union_all([g(w) for (w,) in rows(f"SELECT {m()} FROM work.block WHERE level = ?", [level])] or [shapely.Polygon()])
    corridors = shapely.union_all([g(w) for (w,) in rows(f"SELECT {m()} FROM work.corridor")] or [shapely.Polygon()])
    street = poly(area.difference(blocks).difference(corridors))
    if street.is_empty:
        return 0

    # ---- the cuts: the stop lines and the joints, each square to its road, CUT_M each way
    cuts = []
    for (w,) in rows(f"SELECT {m()} FROM work.mark WHERE level = ? AND type = 'stop line'", [level]):
        ln = g(w)
        if ln.geom_type != "LineString" or ln.length < 0.5:
            continue
        a, b = ln.coords[0], ln.coords[-1]
        # (the stop line runs across the road: the cut is the stop line itself, run on to CUT_M each way)
        dx, dy = b[0] - a[0], b[1] - a[1]
        h = (dx * dx + dy * dy) ** .5 or 1
        cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        cuts.append(shapely.LineString([(cx - dx / h * CUT_M, cy - dy / h * CUT_M), (cx + dx / h * CUT_M, cy + dy / h * CUT_M)]))
    # the joints: where one subsection's axis ends and the next of the same section begins
    axes = {}
    for sid, uid, w in rows(f"SELECT section_id, subsection_id, {m()} FROM work.subsection WHERE level = ?", [level]):
        axes.setdefault(sid, []).append((uid, g(w)))
    for sid, lst in axes.items():
        if len(lst) < 2:
            continue
        ends = [(uid, shapely.Point(ln.coords[0]), shapely.Point(ln.coords[-1]), ln) for uid, ln in lst if ln.geom_type == "LineString" and len(ln.coords) >= 2]
        for i, (ua, a0, a1, la) in enumerate(ends):
            for ub, b0, b1, lb in ends[i + 1:]:
                for pa, pb in ((a1, b0), (a0, b1), (a1, b1), (a0, b0)):
                    if pa.distance(pb) < 0.5:
                        t = la.project(pa)
                        q1, q2 = la.interpolate(max(t - 1, 0)), la.interpolate(min(t + 1, la.length))
                        dx, dy = q2.x - q1.x, q2.y - q1.y
                        h = (dx * dx + dy * dy) ** .5 or 1
                        cuts.append(shapely.LineString([(pa.x + dy / h * CUT_M, pa.y - dx / h * CUT_M), (pa.x - dy / h * CUT_M, pa.y + dx / h * CUT_M)]))
                        break

    # ---- rank 3: the partition
    # (each cut clipped to the street widened by 1 cm, so its ends pass the street's boundary: a cut clipped exactly to the street ended a
    # float away from the boundary, the noding did not join them, and 162 cuts made 42 faces instead of 168)
    stree = shapely.STRtree(list(shapely.get_parts(street)))
    cl = [q for c_ in cuts for k in stree.query(c_) for q in shapely.get_parts(c_.intersection(stree.geometries[k].buffer(0.01)))
          if q.geom_type == "LineString" and q.length > 0.01]
    faces = [f for f in shapely.get_parts(shapely.polygonize(shapely.get_parts(shapely.unary_union([street.boundary] + cl))))
             if f.area > MIN_FACE_M2 and street.contains(f.representative_point())]
    # the roadways of rank 2/3's spaces, from the old parts: who owns a face
    road = {}
    for uid, w in rows(f"""SELECT unit_id, ST_AsWKB(ST_Union_Agg(ST_Transform(geometry, 'EPSG:4326', '{epsg}', always_xy := true)))
                            FROM work.part WHERE level = ? AND type IN ('lane', 'paved', 'junction area', 'crosswalk', 'cycle crossing', 'bridge deck') GROUP BY unit_id""", [level]):
        road[uid] = g(w)
    kind = dict(rows(f"SELECT unit_id, kind FROM work.unit WHERE level = ?", [level]))
    sect = dict(rows(f"SELECT unit_id, section_id FROM work.unit WHERE level = ?", [level]))
    rids = list(road)
    rtree = shapely.STRtree([road[u] for u in rids]) if rids else None
    owner = []
    for f in faces:
        best, ba = None, 0.5
        for k in (rtree.query(f) if rtree is not None else []):
            a_ = road[rids[k]].intersection(f).area
            if a_ > ba:
                best, ba = rids[k], a_
        owner.append(best)
    # a face with no roadway joins the neighbour it shares the most edge with (a few rounds: a chain of such faces)
    ftree = shapely.STRtree(faces)
    for _ in range(4):
        for i, f in enumerate(faces):
            if owner[i] is not None:
                continue
            best, bl = None, 0.0
            for k in ftree.query(f.buffer(0.1)):
                if k != i and owner[k] is not None:
                    l_ = f.boundary.intersection(faces[k].buffer(0.05)).length
                    if l_ > bl:
                        best, bl = owner[k], l_
            owner[i] = best
    spaces = {}
    for f, o in zip(faces, owner):
        spaces.setdefault(o, []).append(f)
    con.execute("""CREATE OR REPLACE TABLE work.space3 (space_id VARCHAR, kind VARCHAR, section_id VARCHAR, level INT, faces INT, area_m2 DOUBLE,
                   geometry GEOMETRY)""")
    out = []
    for o, fs in spaces.items():
        if o is None:
            continue
        u = poly(shapely.union_all(fs))
        parts = [p for p in shapely.get_parts(u) if p.geom_type == "Polygon" and p.area > MIN_FACE_M2]
        for n, p in enumerate(sorted(parts, key=lambda p: -p.area), 1):
            # (an owner whose faces are apart: a through road at a T junction is one old section with the junction's face between its two
            # halves; each half is its own space here, `#n`; rank 2 should end every section at every junction)
            out.append((o if len(parts) == 1 else f"{o}#{n}", kind.get(o, "subsection"), sect.get(o), level, len(fs), round(p.area, 1), shapely.to_wkb(p)))
    if out:
        con.executemany(f"""INSERT INTO work.space3 VALUES (?, ?, ?, ?, ?, ?, ST_Transform(ST_GeomFromWKB(?), '{epsg}', 'EPSG:4326', always_xy := true))""", out)
    orphan = sum(f.area for f, o in zip(faces, owner) if o is None)
    print(f"  division (top down): rank 3: {len(faces)} faces, {len(cuts)} cuts, {len(out)} spaces, {orphan:.1f} m2 with no owner", flush=True)
    return len(out)
