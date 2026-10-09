"""space.unit: one clean space per subsection and one per intersection (step 2 of the network-first partition; the roads were
divided into subsections first, see subsections.py).

INTERSECTION: each arm is cut at the block corners. The corner between two neighbouring arms is the building-line vertex nearest the
junction inside the angle between them (closer than CORNER_MAX_M, and not on either road). An arm with a corner on both sides is cut
by the straight line joining them; with one corner, by the line through it along the street on the corner's other side (the
prolongation of that street's building line: on a T junction the classic rectangle); with none, square to the arm at the
crossing street's half-width + CROSS_MARGIN_M. The intersection is the whole area its cuts enclose (the polygon they span, minus the
building line): its core (the nodes, the roads between them at a dogleg or a roundabout) and every arriving road from its node up to its
cut are its own, and of the rest it takes everything the arriving roads' spaces (which end on the cuts) do not hold.

Every arm's cut is kept in space.cut (one line per arm, `how`: block corners, one corner or distance).

SUBSECTION: a subsection has one kind of frontage on each side, so its space is a parallel ribbon: a side with buildings reaches
FACADE_SLACK_M past the facade line and the building line cut out of it is the edge itself; an open side reaches the cap (or halfway
to a parallel street of another section). Its ends: square across the road at a split (the neighbour shares that line), the arm's cut
at a junction. A space holds its own road; where two spaces overlap (the halves of a dual road, an open corner) the overlap goes
to the nearer road.
"""
import math

BLINE_M = 3.0
CORNER_MAX_M = 25.0
CORNER_SECTOR_MAX_DEG = 160.0   # a wider angle between two arms (the straight side of a T) has no block corner
CROSS_MARGIN_M = 1.0
FACADE_SLACK_M = 4.0            # >= subsections.STEP_BACK_M: a facade varies by at most that within a subsection
PARALLEL_COS = 0.85
FAR_M = 300.0


def _reach(w):
    return min(1.5 * w + 8, 25.0)


def _halfplane(p, v, n, along=FAR_M, depth=FAR_M):
    """The n side of the line through p with direction v: a rectangle `along` either way along the line and `depth` deep."""
    import shapely
    (px, py), (vx, vy), (nx, ny) = p, v, n
    return shapely.Polygon([(px - vx * along, py - vy * along), (px + vx * along, py + vy * along),
                            (px + vx * along + nx * depth, py + vy * along + ny * depth), (px - vx * along + nx * depth, py - vy * along + ny * depth)])


def _clean(g):
    """Polygons only, valid, simplified by 5 cm (a repair can leave lines and points behind; simplify after it can undo it)."""
    import shapely
    g = shapely.make_valid(g)
    g = shapely.union_all([p for p in shapely.get_parts(g) if p.geom_type in ("Polygon", "MultiPolygon")] or [shapely.Polygon()])
    return shapely.set_precision(shapely.make_valid(g.simplify(0.05)).buffer(0), 0.01)   # on a 1 cm grid: stays valid through lon/lat


def _one(g, line=None):
    """One connected polygon: the part holding most of the road (or the largest part)."""
    import shapely
    parts = [p for p in shapely.get_parts(g) if not p.is_empty]
    if len(parts) <= 1:
        return g
    key = (lambda p: (p.intersection(line).length, p.area)) if line is not None else (lambda p: p.area)
    return max(parts, key=key)


def _unit(x, y):
    h = math.hypot(x, y) or 1.0
    return x / h, y / h


def _run_length(edge, from_node, roads, by_node, limit=80.0):
    """Length of the street from `from_node` along `edge` to the next junction or dead end (through nodes where only two roads meet)."""
    total, node, e, seen = 0.0, from_node, edge, set()
    while e is not None and e not in seen and total < limit:
        seen.add(e)
        g, src, dst, _ = roads[e]
        total += g.length
        node = dst if src == node else src
        nxt = [x for x in by_node.get(node, ()) if x != e]
        e = nxt[0] if len(nxt) == 1 else None
    return total


def _intersections(level, arms, roads, node_xy, bparts, btree, ring_edges=frozenset()):
    """{intersection id: polygon}, {(intersection id, edge id): (point on the cut, cut direction, far normal, node xy, arm direction,
    how it was cut, the cut as a line)}."""
    import shapely
    from shapely.ops import nearest_points
    regions, cuts = {}, {}
    by_node = {}
    for e, (_, src, dst, _) in roads.items():
        by_node.setdefault(src, []).append(e)
        by_node.setdefault(dst, []).append(e)
    by_i = {}
    for iid, node, edge in arms:
        by_i.setdefault(iid, []).append((node, edge))
    for iid, members in by_i.items():
        nodes = {n for n, _ in members}
        pts = [node_xy[n] for n in nodes if n in node_xy]
        if not pts:
            continue
        cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
        arm = []
        for node, edge in members:
            r = roads.get(edge)
            if r is None or node not in node_xy:
                continue
            g, src, dst, w = r
            if src in nodes and dst in nodes:          # a road inside the junction (a roundabout ring, a short link) is not an arm
                continue
            at_start = src == node
            d = min(10.0, g.length / 2)
            q = g.interpolate(d if at_start else g.length - d)
            nx_, ny_ = node_xy[node]
            ux, uy = _unit(q.x - nx_, q.y - ny_)
            arm.append(dict(edge=edge, node=node, p=(nx_, ny_), u=(ux, uy), hw=w / 2, len=_run_length(edge, node, roads, by_node), g=g,
                            bearing=math.degrees(math.atan2(uy, ux)) % 360))
        if len(arm) < 2:
            continue
        arm.sort(key=lambda a: a["bearing"])
        c = shapely.Point(cx, cy)
        near = [bparts[k] for k in btree.query(c.buffer(CORNER_MAX_M))] if btree is not None else []
        verts = [xy for b in near for ring in [b.exterior, *b.interiors] for xy in ring.coords]
        corner = []
        for i, a in enumerate(arm):
            b = arm[(i + 1) % len(arm)]
            span = (b["bearing"] - a["bearing"]) % 360
            best = None
            if 0 < span < CORNER_SECTOR_MAX_DEG:
                for x, y in verts:
                    dist = math.hypot(x - cx, y - cy)
                    rel = (math.degrees(math.atan2(y - cy, x - cx)) - a["bearing"]) % 360
                    if dist > CORNER_MAX_M or not (3 < rel < span - 3):
                        continue
                    pt = shapely.Point(x, y)
                    if pt.distance(a["g"]) < a["hw"] + 0.5 or pt.distance(b["g"]) < b["hw"] + 0.5:
                        continue
                    if best is None or dist < best[0]:
                        best = (dist, (x, y))
            corner.append(best[1] if best else None)   # corner[i]: between arm i and arm i+1 (counter-clockwise)
        others = lambda a: max([o["hw"] for o in arm if o is not a] or [0])
        for i, a in enumerate(arm):
            ux, uy = a["u"]
            ccw, cw = corner[i], corner[i - 1]
            if ccw and cw:
                p, v, how = cw, _unit(ccw[0] - cw[0], ccw[1] - cw[1]), "block corners"
            elif ccw or cw:    # the prolongation of the crossing street's building line: parallel to the arm on the corner's other side
                p, v, how = ccw or cw, arm[(i + 1) % len(arm)]["u"] if ccw else arm[i - 1]["u"], "one corner"
            else:
                p, v, how = None, (-uy, ux), "distance"
            nx, ny = -v[1], v[0]
            if nx * ux + ny * uy < 0:
                nx, ny = -nx, -ny
            s = None
            if p is not None:     # where the cut crosses the arm's axis: it must lie along the arm, not behind the node or past its end
                den = ux * nx + uy * ny
                s = ((p[0] - a["p"][0]) * nx + (p[1] - a["p"][1]) * ny) / den if abs(den) > 0.2 else None
            if p is not None and s is None:
                how = "distance (corner cut runs along the arm)"
            elif p is not None and s < 1.0:
                how = f"distance (corner cut behind the node, {s:.1f} m)"
            elif p is not None and s > min(a["len"] / 2, 35.0):
                how = f"distance (corner cut too far, {s:.1f} m of {a['len']:.0f} m)"
            if s is None or not (1.0 <= s <= min(a["len"] / 2, 35.0)):   # at most half the road: the junction at its other end has the rest
                d0 = min(max(others(a) + CROSS_MARGIN_M, a["hw"] + 3.0), a["len"] / 2)
                p, v = (a["p"][0] + ux * d0, a["p"][1] + uy * d0), (-uy, ux)
                nx, ny = ux, uy
                s = d0
            # the cut runs from the arm's axis both ways to the first building line (a block corner lies on it) or to the reach
            X = shapely.Point(a["p"][0] + ux * s, a["p"][1] + uy * s)
            ends = []
            for sg in (1, -1):
                ray = shapely.LineString([X, (X.x + sg * v[0] * _reach(2 * a["hw"]), X.y + sg * v[1] * _reach(2 * a["hw"]))])
                hit = shapely.union_all([ray.intersection(b) for b in near if ray.intersects(b)])
                ends.append(nearest_points(X, hit)[1] if not hit.is_empty else shapely.Point(ray.coords[-1]))
            a.update(cut=(p, v, (nx, ny)), s=s, ends=ends, X=X)
            cuts[(iid, a["edge"])] = (p, v, (nx, ny), a["p"], a["u"], how, shapely.LineString(ends))
        # the intersection is the polygon its cuts span (each from block corner to block corner, or to a facade or the reach)
        region = shapely.MultiPoint([pt for a in arm for pt in a["ends"]] + [shapely.Point(p) for p in pts]).convex_hull
        if near:
            region = region.difference(shapely.union_all(near))
        # never beyond a cut: the junction's core (its nodes, the roads between them at a dogleg or a roundabout) and every arriving
        # road from its node up to its cut. The intersection is the whole area its cuts enclose, these road pieces included.
        touching = {ed for _, ed in members} | {e for n in nodes for e in by_node.get(n, ())}
        ring = {e for e in touching if e in ring_edges}           # a roundabout: its whole ring is its own (never a road's space)
        inner = [roads[e][0].buffer(roads[e][3] / 2) for e in touching
                 if e in roads and ((roads[e][1] in nodes and roads[e][2] in nodes) or e in ring)]
        pieces = [shapely.LineString([a["p"], (a["X"].x, a["X"].y)]).buffer(a["hw"], cap_style="flat") for a in arm if a["s"] > 0.1]
        # a spread-out junction (a dogleg, a roundabout) holds together: the ground its nodes span, minus the buildings, is core too
        span = shapely.MultiPoint(pts).convex_hull.buffer(1.5)
        core = shapely.union_all([shapely.Point(p).buffer(1.5) for p in pts] + inner + pieces + [span.difference(shapely.union_all(near)) if near else span])
        region = shapely.union_all([region, core])   # the junction's own road surface is its own even under a building (an arcade)
        if len(nodes) == 1:   # one node: a cut is a hard edge, nothing beyond it (at a dogleg the strips would cut into the other nodes' ground)
            beyond = []
            for a in arm:
                e1, e2 = a["ends"]
                beyond.append(_halfplane(((e1.x + e2.x) / 2, (e1.y + e2.y) / 2), a["cut"][1], a["cut"][2], along=e1.distance(e2) / 2 + 0.5))
            region = region.difference(shapely.union_all(beyond).difference(core))
        regions[iid] = (region, core, pts, bool(ring))     # build() makes the intersection: what the arriving roads' spaces leave of the region
    return regions, cuts


def build(con, epsg):
    import pandas as pd
    import shapely
    to_m = f"ST_AsWKB(ST_Transform(geometry, 'EPSG:4326', '{epsg}', always_xy := true))"
    subs = con.execute(f"""SELECT subsection_id, section_id, level, width_m, left_m, right_m, left_extra, right_extra, with_sections, color, {to_m}
                           FROM space.subsection""").fetchall()
    road_rows = con.execute(f"""SELECT source_id, level_min, src, dst, width_m, container_id, {to_m} FROM space.element
                                WHERE type = 'road' AND ST_Length(geometry) > 0""").fetchall()
    try:    # roundabout rings: their road edges and their nodes (a junction holding one is a roundabout, a space of its own kind)
        ring_osm = {r[0] for r in con.execute("SELECT osm_id FROM osm.raw.ways WHERE tags['junction'] IN ('roundabout', 'circular')").fetchall()}
    except Exception:
        ring_osm = set()
    ring_edges = {r[0] for r in con.execute("SELECT source_id, osm_id FROM space.element WHERE type = 'road'").fetchall() if r[1] in ring_osm}
    arm_rows = con.execute("""SELECT DISTINCT j.intersection_id, a.node_id, a.edge_id, a.level FROM space.arm a
                              JOIN space.junction j ON j.cluster_id = a.intersection_id AND j.node_id = a.node_id AND j.level = a.level""").fetchall()
    blds = con.execute(f"SELECT l, {to_m} FROM space.element, generate_series(level_min, level_max) t(l) WHERE type = 'building'").fetchall()
    rows, cut_rows, clipped = [], [], []
    for lv in sorted({s[2] for s in subs} | {a[3] for a in arm_rows}):
        u = shapely.union_all([shapely.from_wkb(bytes(b[1])) for b in blds if b[0] == lv]) if blds else shapely.Polygon()
        bparts = list(shapely.get_parts(u.buffer(BLINE_M).buffer(-BLINE_M))) if not u.is_empty else []
        btree = shapely.STRtree(bparts) if bparts else None
        bline = shapely.union_all(bparts) if bparts else shapely.Polygon()
        roads, node_xy, sec_lines = {}, {}, []
        for eid, l, src, dst, w, cid, g in road_rows:
            if l != lv:
                continue
            g = shapely.from_wkb(bytes(g))
            roads[eid] = (g, src, dst, w)
            node_xy[src], node_xy[dst] = g.coords[0], g.coords[-1]
            sec_lines.append((cid, g))
        regions, cuts = _intersections(lv, [(a[0], a[1], a[2]) for a in arm_rows if a[3] == lv], roads, node_xy, bparts, btree, ring_edges)
        # the cut at each junction end: found by the junction node the subsection ends on, and the arm that leaves it in its direction
        cut_at = {}
        for (iid, edge), (p, v, n, nxy, u, how, seg) in cuts.items():
            cut_at.setdefault((round(nxy[0], 1), round(nxy[1], 1)), []).append((iid, p, v, n, u))
            cut_rows.append((iid, edge, lv, how, round(seg.length, 1), shapely.to_wkb(seg)))
        sec_tree = shapely.STRtree([g for _, g in sec_lines]) if sec_lines else None
        spaces = []
        for sid, sec, l, w, lm, rm, lx, rx, withs, color, g in subs:
            if l != lv:
                continue
            line = shapely.from_wkb(bytes(g))
            own = {sec, *(withs.split(",") if withs else [])}     # its section and the parallel ones it carries
            ext = []
            for side, d, more in ((1, lm, lx), (-1, rm, rx)):
                e = d + FACADE_SLACK_M if d is not None else _reach(w) + (more or 0)
                # halfway to a parallel road of another section, when no building stands between
                hits = []
                for t in [line.length * f for f in (0.2, 0.5, 0.8)]:
                    p0, p1 = line.interpolate(max(t - 1.5, 0)), line.interpolate(min(t + 1.5, line.length))
                    tx, ty = _unit(p1.x - p0.x, p1.y - p0.y)
                    nx, ny = -ty * side, tx * side
                    c = line.interpolate(t)
                    ray = shapely.LineString([(c.x, c.y), (c.x + nx * e * 2, c.y + ny * e * 2)])
                    for k in sec_tree.query(ray, predicate="intersects"):
                        ocid, og = sec_lines[k]
                        if ocid in own:
                            continue
                        oc = og.interpolate(og.project(c))
                        q0, q1 = og.interpolate(max(og.project(c) - 1.5, 0)), og.interpolate(min(og.project(c) + 1.5, og.length))
                        ox, oy = _unit(q1.x - q0.x, q1.y - q0.y)
                        if abs(tx * ox + ty * oy) < PARALLEL_COS:
                            continue
                        dd = c.distance(ray.intersection(og))
                        bhit = [c.distance(ray.intersection(b)) for b in (bparts[j] for j in btree.query(ray, predicate="intersects"))] if btree else []
                        if not bhit or min(bhit) > dd:
                            hits.append(dd / 2)
                if len(hits) >= 2:
                    e = min(e, sorted(hits)[len(hits) // 2])
                ext.append(max(e, w / 2))
            rib = shapely.union_all([line.buffer(ext[0], single_sided=True, cap_style="flat", join_style="mitre", mitre_limit=2.0),
                                     line.buffer(-ext[1], single_sided=True, cap_style="flat", join_style="mitre", mitre_limit=2.0)])
            # junction ends: the line runs on to the node; cut it at its own arm's cut (the arm leaving the node in its direction)
            for end, inner in ((line.coords[0], line.interpolate(min(5.0, line.length))), (line.coords[-1], line.interpolate(max(line.length - 5.0, 0)))):
                cands = cut_at.get((round(end[0], 1), round(end[1], 1)), [])
                if cands:
                    dx, dy = _unit(inner.x - end[0], inner.y - end[1])
                    iid, p, v, n, u = max(cands, key=lambda c: c[4][0] * dx + c[4][1] * dy)
                    # only the junction's side of the cut, near the junction: a long curving road must not lose its middle
                    rib = rib.difference(_halfplane(p, v, (-n[0], -n[1]), along=CORNER_MAX_M + 25, depth=CORNER_MAX_M + 15))
            rib = rib.difference(bline)
            parts = [x for x in shapely.get_parts(rib) if x.intersection(line).length > 0.5]
            if parts:   # the road's own surface belongs to its space even where it passes under a building: one connected piece
                road = line.buffer(w / 2, cap_style="flat").intersection(rib.envelope.buffer(1))
                spaces.append([sid, sec, line, _clean(shapely.union_all(parts + [road])), color])
        # the intersection: the junction's core and its road pieces are its own; then everything inside its cuts that no arriving
        # road's space holds, so no ground between the cuts is left to nobody
        polys = {}
        stree = shapely.STRtree([x[3] for x in spaces]) if spaces else None
        for iid, (region, core, _, _rb) in regions.items():
            for k in (stree.query(core) if stree is not None else []):
                spaces[k][3] = _one(spaces[k][3].difference(core), spaces[k][2])
        for iid, (region, core, _, _rb) in regions.items():
            around = [spaces[k][3] for k in stree.query(region)] if stree is not None else []
            left = region.difference(shapely.union_all(around)) if around else region
            parts = [g for g in shapely.get_parts(left) if g.intersects(core)]
            if parts:
                polys[iid] = shapely.union_all(parts)
        # overlaps between spaces (the halves of a dual road, an open corner): each point goes to the nearer road
        tree = shapely.STRtree([s[3] for s in spaces]) if spaces else None
        for i, j in zip(*tree.query([s[3] for s in spaces], predicate="intersects")) if tree else []:
            if i >= j:
                continue
            a, b = spaces[i], spaces[j]
            ov = a[3].intersection(b[3])
            if ov.area < 0.05:
                continue
            pts_a = [a[2].interpolate(t) for t in range(0, int(a[2].length) + 1)]
            pts_b = [b[2].interpolate(t) for t in range(0, int(b[2].length) + 1)]
            cells = shapely.get_parts(shapely.voronoi_polygons(shapely.MultiPoint(pts_a + pts_b), extend_to=ov.envelope.buffer(10)))
            mine = shapely.union_all([cl for cl in cells if any(cl.contains(p) for p in pts_a)])
            a[3] = a[3].difference(ov.difference(mine))
            b[3] = b[3].difference(ov.intersection(mine))
        # two junctions whose spaces overlap (close nodes not merged into one): only the overlap is divided, each point of it going to the
        # junction with the nearer node, so every junction keeps all its own nodes
        ids = list(polys)
        itree = shapely.STRtree([polys[i] for i in ids]) if ids else None
        for a, b in zip(*itree.query([polys[i] for i in ids], predicate="intersects")) if itree else []:
            ia, ib = ids[a], ids[b]
            ov = polys[ia].intersection(polys[ib]) if a < b else shapely.Polygon()
            if ov.area < 0.05:
                continue
            pa, pb = regions[ia][2], regions[ib][2]
            cells = shapely.get_parts(shapely.voronoi_polygons(shapely.MultiPoint(pa + pb), extend_to=ov.envelope.buffer(50)))
            mine = shapely.union_all([cl for cl in cells if any(cl.contains(shapely.Point(q)) for q in pa)])
            polys[ia] = polys[ia].difference(ov.difference(mine))
            polys[ib] = polys[ib].difference(ov.intersection(mine))
        for iid, gm in polys.items():
            rb = regions.get(iid, (None, None, None, False))[3]      # a roundabout is a space of its own kind
            rows.append((iid, "roundabout" if rb else "intersection", iid, lv, "#f9a8d4" if rb else "#fbbf24", shapely.to_wkb(_one(_clean(gm)))))
        # a cut, as stored, is only the part of its line that bounds its intersection
        for k, r in enumerate(cut_rows):
            if r[2] == lv and r[0] in polys:
                seg = shapely.from_wkb(r[5]).intersection(polys[r[0]].buffer(0.3))
                seg = max((x for x in shapely.get_parts(seg) if x.geom_type == "LineString"), key=lambda x: x.length, default=None)
                if seg is not None:
                    cut_rows[k] = r[:4] + (round(seg.length, 1), shapely.to_wkb(seg))
        for sid, sec, line, gm, color in spaces:     # an intersection always wins where a subsection touches it
            near = [polys[i] for i in polys if polys[i].intersects(gm)]
            gm = _clean(gm.difference(shapely.union_all(near))) if near else _clean(gm)
            gm = _one(gm, line)
            if not gm.is_empty:
                rows.append((sid, "subsection", sec, lv, color, shapely.to_wkb(gm)))
                # the subsection's road ends at its cut: inside the junction the road is the intersection's
                inside = [x for x in shapely.get_parts(line.intersection(gm.buffer(0.01))) if x.geom_type == "LineString"]
                if inside:
                    clipped.append((sid, shapely.to_wkb(max(inside, key=lambda x: x.length))))
    cdf = pd.DataFrame(cut_rows, columns=["intersection_id", "edge_id", "level", "how", "length_m", "wkb"])
    con.execute(f"""CREATE OR REPLACE TABLE space.cut AS
        SELECT intersection_id, edge_id, level::INT AS level, how, length_m,
               ST_Transform(ST_GeomFromWKB(wkb::BLOB), '{epsg}', 'EPSG:4326', always_xy := true) AS geometry FROM cdf""")
    ldf = pd.DataFrame(clipped, columns=["subsection_id", "wkb"])
    con.execute(f"""UPDATE space.subsection s SET geometry = ST_Transform(ST_GeomFromWKB(l.wkb::BLOB), '{epsg}', 'EPSG:4326', always_xy := true),
                     length_m = round(ST_Length(ST_GeomFromWKB(l.wkb::BLOB)), 1)
                     FROM ldf l WHERE s.subsection_id = l.subsection_id""")
    df = pd.DataFrame(rows, columns=["unit_id", "kind", "section_id", "level", "color", "wkb"])
    con.execute(f"""CREATE OR REPLACE TABLE space.unit AS
        SELECT unit_id, kind, section_id, level::INT AS level, color,
               ST_CollectionExtract(ST_MakeValid(ST_Transform(ST_GeomFromWKB(wkb::BLOB), '{epsg}', 'EPSG:4326', always_xy := true)), 3) AS geometry FROM df""")
    # a subsection that lies wholly inside its intersection has no space of its own: its road is the intersection's piece, not a subsection
    con.execute("DELETE FROM space.subsection WHERE subsection_id NOT IN (SELECT unit_id FROM space.unit)")
