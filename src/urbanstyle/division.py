"""The street divided between the blocks (docs/design/blocks.md, steps 2-5) and the inside of each piece (layers 1-2 of
docs/design/space-layers.md), at level 0. It replaces the level-0 spaces of `spaces.py` and their parts of `parts.py`.

    shares        every point of the street (the area less the blocks) belongs to its nearest block; the outside of the area is one
                  more block (-1), except across a street opening (where a street leaves the area)
    middle line   where two shares meet
    section       where a line square to the middle line meets block a on one side and block b on the other, each on a side running
                  along it (within FACE_DEG): cut at two positions ARM_M inside the ends of that stretch (none at the area's edge);
                  at least as long as the street is wide. Id `s<level>-<block a>~<block b>`
    intersection  the street left: the open space between the corners and ARM_M into each arm. Id `i<level>-<smallest OSM node in it>`
    subsection    a section cut across where its carriageways or lanes change, for SUB_MIN_M at least. Id `<section>/<k>`
    inside        each subsection in strips parallel to its axis (the middle line): pedestrian realm, kerb, roadway (its lanes, one
                  whole lane each, a shoulder, a median between carriageways), kerb, pedestrian realm. Each intersection: one junction
                  area, and a pedestrian corner at each block corner where the kerbs of its two arms meet (rounded by KERB_RADIUS_M)
    marks         kerbs, lane lines, centre lines, stop lines, and zebra bars where OSM maps a crossing over the roadway

Every value no source gives is urbanstyle's own, chosen (docs/design/provenance.md).
"""
import json
import math
import statistics

STEP_M, SAMPLE_M, RAY_M, FACE_DEG = 1.0, 0.5, 80.0, 30.0   # shares: points along outlines; facing tested every; how far; along within
MAX_POINTS = 60000       # the shares from at most this many points
OPENING_M = 40.0         # an edge of the area crossing a street, shorter than this, is a street opening: the outside is no neighbour there
ARM_M = 3.0              # an intersection reaches into each arm past the block corner (its crosswalk, stop line)
SUB_MIN_M = 12.0         # a subsection is at least this long: changes closer together are one cut
LANE_M = 3.25            # a lane's width where nothing measures it
LANE_RANGE = (2.75, 4.0)     # a lane measured kerb to kerb, if it falls in this range; else LANE_M and a shoulder
SIDEWALK_HALF_M = 1.0    # a sidewalk is drawn along its middle: the kerb is about this far before its line
OBJECT_BACK_M = 0.5      # a tree or a pole stands at least this far behind the kerb
MIN_REALM_M = 1.5        # the pedestrian realm keeps at least this between the kerb and the block
MEDIAN_MIN_M = 1.0       # carriageways farther apart than this have a median between them
KERB_RADIUS_M = 4.0      # a corner's kerb is rounded by this
SHOULDER_EDGE_M = 0.3    # every carriageway keeps a shoulder this wide at each edge (the gutter); more where the lanes leave room
FURNISH_M = (1.0, 0.6, 2.5)  # the pedestrian realm's buffer (furniture) zone at the kerb: where nothing stands in it; at least; at most
CLEAR_M = 1.8            # the clear path, where nothing measures it
FRONTAGE_MIN_M = 0.75    # a frontage or buffer zone narrower than this is the clear path's
PIECE_MIN_M2 = 5.0       # a strip smaller than this (in a very short subsection) joins the neighbouring strip it shares the most edge with
ZEBRA = (0.5, 1.0, 3.0)      # a zebra bar: width, spacing, length along the traffic
STOP_BACK_M = 1.0        # a stop line stands this far before the section's end at an intersection
STREET = ("motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street", "pedestrian")
LINE = {"kerb": 0.15, "lane line": 0.12, "centre line": 0.12, "stop line": 0.4, "zebra": 0.5}
COLORS = {"subsection": "#94a3b8", "intersection": "#fbbf24"}
V, D, I, G_ = "VARCHAR", "DOUBLE", "INTEGER", "GEOMETRY"
SCHEMA = {
    "unit": dict(unit_id=V, kind=V, section_id=V, level=I, color=V, geometry=G_),
    "part": dict(unit_id=V, part_id=V, level=I, type=V, arm=V, direction=V, lane=I, width_m=D, width_source=V, width_method=V, length_m=D,
                 source=V, method=V, ref=V, road=V, road_class=V, speed=V, surface=V, lit=V, road_lanes=V, oneway=V, holds=V, rule=V, geometry=G_),
    "mark": dict(unit_id=V, level=I, type=V, arm=V, length_m=D, width_m=D, width_source=V, width_method=V, source=V, method=V, ref=V, geometry=G_),
    "width": dict(unit_id=V, level="BIGINT", edge=V, arm=V, total_m=D, carriageway_m=D, left_m=D, right_m=D, lanes_in="BIGINT", lanes_out="BIGINT",
                  lane_m=D, source=V),
    "subsection": dict(subsection_id=V, section_id=V, level=I, **{"class": V}, width_m=D, oneway="BOOLEAN", length_m=D, left=V, right=V, left_m=D,
                       right_m=D, left_extra=D, right_extra=D, with_sections=V, starts_at=V, color=V, geometry=G_),
    "cut": dict(intersection_id=V, edge_id=V, level=I, how=V, length_m=D, geometry=G_),
    "junction": dict(intersection_id=V, node_id="BIGINT", level=I, cluster_id=V),
    "turn": dict(unit_id=V, level=I, from_edge=V, from_lane=I, to_edge=V, to_lane=I, turn=V, source=V, vehicles=V, condition=V, geometry=G_),
    "approach": dict(unit_id=V, level=I, from_edge=V, lane=I, moves=I, ways=V, arrow="BOOLEAN", no_arrow_because=V),
}


def build(con, epsg):
    import duckdb
    import shapely
    from shapely.ops import substring

    m = lambda col="geometry": f"ST_AsWKB(ST_Transform({col}, 'EPSG:4326', '{epsg}', always_xy := true))"
    g = lambda w: shapely.make_valid(shapely.from_wkb(bytes(w)))
    poly = lambda x: shapely.union_all([p for p in shapely.get_parts(x) if p.geom_type == "Polygon"] or [shapely.Polygon()])

    def rows(sql, args=None):
        try:
            return con.execute(sql, args or []).fetchall()
        except (duckdb.CatalogException, duckdb.BinderException):     # a database without that layer or column
            return []

    blocks = [(i, g(w)) for i, w in rows(f"SELECT block_id, {m()} FROM space.block WHERE level = 0 ORDER BY block_id")]
    area = rows(f"SELECT {m()} FROM space.area")
    if not blocks or not area:
        return 0
    box = g(area[0][0])
    bid = [i for i, _ in blocks]
    bgeo = [x for _, x in blocks]
    street = poly(box.difference(shapely.union_all(bgeo), grid_size=0.01))
    short = lambda k: "edge" if k == -1 else bid[k][3:] if bid[k].startswith("b0-") else bid[k]

    # ---- shares and middle lines
    openings = shapely.union_all([x for x in shapely.get_parts(shapely.line_merge(box.exterior.intersection(street.buffer(0.01))))
                                  if x.length < OPENING_M] or [shapely.Point()]).buffer(0.05)
    pts, owner, seen = [], [], set()
    edge_near = box.exterior.intersection(shapely.union_all(bgeo).buffer(2 * RAY_M))
    rings = [(k, b.exterior) for k, b in enumerate(bgeo)] + [(-1, x) for x in shapely.get_parts(shapely.line_merge(edge_near))
                                                            if x.geom_type == "LineString"]
    step = max(STEP_M, sum(r.length for _, r in rings) / MAX_POINTS)     # (a vast area: fewer points, coarser shares)
    for k, ring in rings:
        for i in range(max(4, int(ring.length / step))):
            q = ring.interpolate(i * ring.length / max(4, int(ring.length / step)))
            key = (round(q.x, 1), round(q.y, 1))
            if key in seen or (k == -1 and q.within(openings)):
                continue
            seen.add(key)
            pts.append(q)
            owner.append(k)
    cells = shapely.get_parts(shapely.voronoi_polygons(shapely.MultiPoint(pts), extend_to=box.buffer(200), ordered=True))
    regions = {}
    for c_, k in zip(cells, owner):
        regions.setdefault(k, []).append(c_)
    def merge(v):       # a block's cells are a coverage (they meet edge to edge): joined as one
        try:
            return shapely.coverage_union_all(v)
        except shapely.errors.GEOSException:
            return shapely.union_all([c.buffer(0.001) for c in v])
    regions = {k: merge(v).intersection(street) for k, v in regions.items()}
    rkeys = list(regions)
    rtree = shapely.STRtree([regions[k] for k in rkeys])
    mids = {}
    for a in rkeys:
        for j in rtree.query(regions[a].buffer(0.1)):
            b = rkeys[j]
            key = tuple(sorted((a, b)))
            if a == b or key in mids:
                continue
            x = regions[a].boundary.intersection(regions[b].boundary.buffer(0.05)).intersection(street.buffer(0.01))
            x = [p for p in shapely.get_parts(shapely.line_merge(x)) if p.geom_type == "LineString"]
            if x:   # pieces whose ends are within 5 cm are one line (rounding gaps where shares meet)
                x = shapely.line_merge(shapely.set_precision(shapely.union_all(x), 0.05))
                if x.length > 1:
                    mids[key] = x
    targets = [(k, b) for k, b in enumerate(bgeo)] + [(-1, box.exterior)]
    ttree = shapely.STRtree([t for _, t in targets])
    cosf = math.cos(math.radians(FACE_DEG))

    def tangent(line, s):
        a, b = line.interpolate(max(s - 1, 0)), line.interpolate(min(s + 1, line.length))
        dx, dy = b.x - a.x, b.y - a.y
        h = (dx * dx + dy * dy) ** .5 or 1
        return dx / h, dy / h

    def across(line, s):
        """At s along a line: the first thing met square to it on its left (1) and its right (-1): (owner or None, point, distance)."""
        p = line.interpolate(s)
        ux, uy = tangent(line, s)
        out = {}
        for sg in (1, -1):
            ray = shapely.LineString([(p.x, p.y), (p.x - sg * uy * RAY_M, p.y + sg * ux * RAY_M)])
            best = None
            for t in ttree.query(ray):
                ring = targets[t][1].exterior if targets[t][0] >= 0 else targets[t][1]
                x = ray.intersection(ring)
                for q in shapely.get_parts(x):
                    if q.is_empty:
                        continue
                    q = q if q.geom_type == "Point" else shapely.Point(q.coords[0])
                    if best is None or p.distance(q) < best[2]:
                        bt = ring.project(q)
                        e0, e1 = ring.interpolate(max(bt - 1, 0)), ring.interpolate(min(bt + 1, ring.length))
                        ex, ey = e1.x - e0.x, e1.y - e0.y
                        along = abs(ex * ux + ey * uy) / ((ex * ex + ey * ey) ** .5 or 1)
                        best = (targets[t][0] if along >= cosf else None, q, p.distance(q))
            out[sg] = best
        return out

    # ---- sections: two cuts per facing stretch
    secs = []       # dict(a, b, line, c0, c1, e0, e1, left, right): left / right = the block on the line's left / right
    cuts = []       # (line, section index, end 0 / 1)
    for (a, b), mline in mids.items():
        for line in shapely.get_parts(mline):
            if line.geom_type != "LineString":
                continue
            ss = [i * SAMPLE_M for i in range(int(line.length / SAMPLE_M) + 1)]
            ok = []
            for sv in ss:
                h = across(line, sv)
                ok.append(all(h.values()) and None not in (h[1][0], h[-1][0]) and {h[1][0], h[-1][0]} == {a, b})
            runs, start, prev = [], None, None
            for sv, v in zip(ss + [None], ok + [False]):
                if v and start is None:
                    start = sv
                if not v and start is not None:
                    runs.append((start, prev))
                    start = None
                prev = sv
            for s0, s1 in runs:
                e0 = line.interpolate(s0).distance(box.exterior) < 2.0
                e1 = line.interpolate(s1).distance(box.exterior) < 2.0
                c0, c1 = s0 + (0 if e0 else ARM_M), s1 - (0 if e1 else ARM_M)
                hm = across(line, (c0 + c1) / 2)
                width = hm[1][1].distance(hm[-1][1]) if all(hm.values()) else 0
                if c1 - c0 < 1 or (c1 - c0 < width and not (e0 or e1)):     # shorter than wide: part of the junction
                    continue
                left = hm[1][0]
                secs.append(dict(a=a, b=b, line=line, c0=c0, c1=c1, e0=e0, e1=e1, left=left, right=b if left == a else a))
                for cs_, edge, end in ((c0, e0, 0), (c1, e1, 1)):
                    if not edge:
                        h = across(line, cs_)
                        cuts.append((shapely.LineString([h[1][1].coords[0], h[-1][1].coords[0]]), len(secs) - 1, end))

    def extend(x, e):
        c = list(x.coords)
        out = lambda p, q: (p[0] + (p[0] - q[0]) / (math.dist(p, q) or 1) * e, p[1] + (p[1] - q[1]) / (math.dist(p, q) or 1) * e)
        return shapely.LineString([out(c[0], c[1])] + c + [out(c[-1], c[-2])])

    pieces = [x for x in shapely.get_parts(shapely.polygonize(list(shapely.get_parts(shapely.union_all(
        [street.boundary] + [extend(c, 0.05) for c, _, _ in cuts]))))) if x.representative_point().within(street) and x.area > 0.5]
    secgeo, rest = {}, []
    for x in pieces:
        hit = [i for i, s in enumerate(secs) if x.distance(s["line"].interpolate((s["c0"] + s["c1"]) / 2)) < 0.01]
        if hit:
            secgeo[hit[0]] = x
        else:
            rest.append(x)
    inter = []
    for x in rest:      # a piece meeting fewer than three sections is a street's end (at the area's edge): it joins its section
        touch = [(secgeo[i].boundary.intersection(x.boundary.buffer(0.05)).length, i) for i in secgeo if secgeo[i].distance(x) < 0.05]
        if 0 < len(touch) < 3:
            i = max(touch)[1]
            secgeo[i] = poly(shapely.union_all([secgeo[i], x], grid_size=0.01))
        else:
            inter.append(x)

    # ---- roads: carriageways (their offset, width, lanes along / against) for the subsections
    lanes = {}
    for oid, rev, ln in rows("SELECT osm_id, is_reverse, median(lanes) FROM osm.driving.edges WHERE lanes IS NOT NULL GROUP BY 1, 2"):
        lanes[(oid, bool(rev))] = int(ln)
    # the streets' roads: at level 0, and on a deck at level 1 where nothing at ground level passes under it (works, not a bridge), as
    # for the blocks: such a deck is the street at ground level
    cand = [(oid, n, cl, bool(ow), wd, src, dst, g(w), lv) for oid, n, cl, ow, wd, src, dst, w, lv in rows(f"""SELECT osm_id, name, class,
               coalesce(oneway, false), width_m, src, dst, {m()}, level_min FROM space.element WHERE type IN ('road', 'walkway')
               AND level_min IN (0, 1) AND replace(class, '_link', '') IN {STREET}""")]
    ground_lines = [c[7] for c in cand if c[8] == 0] + [g(w) for (w,) in rows(f"SELECT {m()} FROM space.element WHERE type = 'rail' AND level_min = 0")]
    gl_tree = shapely.STRtree(ground_lines) if ground_lines else None
    roads, decks = [], []
    for c in cand:
        if c[8] == 0 or gl_tree is None or not any(ground_lines[k].crosses(c[7]) for k in gl_tree.query(c[7])):
            roads.append(c[:8])
            if c[8] == 1:
                decks.append(c[7])
    road_tree = shapely.STRtree([r[7] for r in roads])
    walks = [g(w) for (w,) in rows(f"""SELECT {m()} FROM space.element WHERE type = 'walkway' AND level_min = 0
                                      AND coalesce(subtype, '') <> 'crossing'""")]
    walk_tree = shapely.STRtree(walks) if walks else None
    crossings = [(oid, g(w)) for oid, w in rows(f"""SELECT osm_id, {m()} FROM space.element WHERE type IN ('walkway', 'cycleway')
                                                  AND level_min = 0 AND subtype = 'crossing'""")]

    objs = [g(w) for (w,) in rows(f"SELECT {m()} FROM space.object WHERE level = 0")]
    otree = shapely.STRtree(objs) if objs else None

    def objects_in(ax, Q, sg):
        """The offsets (left +) of the street objects standing in Q on one side of the axis."""
        out = []
        for k in (otree.query(Q) if otree is not None else []):
            o = objs[k]
            if not Q.contains(o):
                continue
            q = ax.interpolate(ax.project(o))
            ux, uy = tangent(ax, ax.project(o))
            t = (o.x - q.x) * -uy + (o.y - q.y) * ux
            if t * sg > 0:
                out.append(t)
        return out

    def lanes_of(r, along):
        """(lanes going along the axis, lanes going against it) of road r, `along` whether the road's own direction is the axis's."""
        oid, n, cl, ow, wd = r[:5]
        f, bk = lanes.get((oid, False)), lanes.get((oid, True))
        tot = max(1, round((wd or LANE_M * 2) / LANE_M))
        if ow:
            f, bk = f or tot, 0
        else:
            f, bk = f or max(1, tot // 2), bk or max(1, tot - tot // 2)
        return (f, bk) if along else (bk, f)

    def profile(axis, P, s):
        """The carriageways crossed by the line square to the axis at s, left to right of nothing: [(offset, width, along, against, road)]."""
        p = axis.interpolate(s)
        ux, uy = tangent(axis, s)
        cross = shapely.LineString([(p.x - uy * RAY_M, p.y + ux * RAY_M), (p.x + uy * RAY_M, p.y - ux * RAY_M)]).intersection(P)
        out = []
        for k in road_tree.query(cross):
            r = roads[k]
            x = r[7].intersection(cross)
            if x.is_empty or x.geom_type != "Point":
                continue
            t = (x.x - p.x) * -uy + (x.y - p.y) * ux       # + left of the axis
            rt = r[7].project(x)
            rx, ry = tangent(r[7], rt)
            if abs(rx * ux + ry * uy) < cosf:              # a road crossing the section, not running along it
                continue
            fw = rx * ux + ry * uy > 0
            al, ag = lanes_of(r, fw)
            out.append((t, r[4] or (al + ag) * LANE_M, al, ag, r, fw))
        return sorted(out, key=lambda c: c[0])

    def offset_band(axis, t1, t2, P, margin=60.0):
        """The part of P between offsets t1 and t2 (left +) of the axis, run on past its ends."""
        ax = extend(axis, margin)
        side = lambda d: ax.buffer(d, single_sided=True, join_style="mitre") if abs(d) > 1e-6 else shapely.Polygon()   # 0 .. d
        if t1 >= 0:
            band = side(t2).difference(side(t1))
        elif t2 <= 0:
            band = side(t1).difference(side(t2))
        else:
            band = shapely.union_all([side(t2), side(t1)])
        return poly(shapely.make_valid(band).intersection(P, grid_size=0.01))

    def line_at(axis, t, P, width):
        """A painted line along the axis at offset t, inside P, of `width`."""
        x = extend(axis, 60.0).offset_curve(t).intersection(P)
        return poly(x.buffer(width / 2, cap_style="flat")) if not x.is_empty and x.length > 0.5 else None

    units, parts, marks, cut_rows, sub_rows, widths, junction = [], [], [], [], [], [], []
    names = {}
    section_ids = {}
    for i in sorted(secgeo, key=lambda i: (short(secs[i]["left"]), short(secs[i]["right"]))):
        s = secs[i]
        base = f"s0-{min(short(s['left']), short(s['right']))}~{max(short(s['left']), short(s['right']))}"
        names[base] = names.get(base, 0) + 1
        section_ids[i] = base + (f".{names[base]}" if names[base] > 1 else "")

    def straight(line):
        c = line.coords
        chord = shapely.LineString([c[0], c[-1]])
        return chord if max(chord.distance(shapely.Point(p)) for p in c) < 1.0 else line.simplify(0.5)

    sub_axis = {}       # subsection id -> (axis, left block, right block, kerbs (left, right), section index)
    for i, sid in section_ids.items():
        s, P = secs[i], secgeo[i]
        line = s["line"]
        a0 = 0.0 if s["e0"] else s["c0"]
        a1 = line.length if s["e1"] else s["c1"]
        axis = substring(line, a0, a1)
        if axis.geom_type != "LineString" or axis.length < 1:
            continue
        axis = straight(axis)
        # where its carriageways change (for SUB_MIN_M at least): the subsections
        keys = []
        for k in range(int(axis.length // 2) + 1):
            sv = min(k * 2.0, axis.length)
            pr = profile(axis, P, sv)
            keys.append((sv, tuple((round(c[0] / 2), c[2], c[3]) for c in pr)))
        runs = []
        for sv, key in keys:
            if runs and runs[-1][2] == key:
                runs[-1][1] = sv
            else:
                runs.append([sv, sv, key])
        while len(runs) > 1 and min(r[1] - r[0] for r in runs) < SUB_MIN_M:   # a short run joins the longer neighbour
            j = min(range(len(runs)), key=lambda j: runs[j][1] - runs[j][0])
            nb = j - 1 if j == len(runs) - 1 or (j > 0 and runs[j - 1][1] - runs[j - 1][0] >= runs[j + 1][1] - runs[j + 1][0]) else j + 1
            lo, hi = min(j, nb), max(j, nb)
            runs[lo] = [runs[lo][0], runs[hi][1], runs[nb][2]]
            del runs[hi]
        bounds = [0.0] + [(runs[j][1] + runs[j + 1][0]) / 2 for j in range(len(runs) - 1)] + [axis.length]
        pieces_ = [P]
        cutlines = []
        for sv in bounds[1:-1]:
            p = axis.interpolate(sv)
            ux, uy = tangent(axis, sv)
            cutlines.append(shapely.LineString([(p.x - uy * RAY_M, p.y + ux * RAY_M), (p.x + uy * RAY_M, p.y - ux * RAY_M)]))
        if cutlines:
            pieces_ = [x for x in shapely.get_parts(shapely.polygonize(list(shapely.get_parts(shapely.union_all(
                [P.boundary] + [c.intersection(P.buffer(0.05)) for c in cutlines]))))) if x.representative_point().within(P) and x.area > 0.5]
        for k in range(len(bounds) - 1):
            mid_pt = axis.interpolate((bounds[k] + bounds[k + 1]) / 2)
            Q = min(pieces_, key=lambda x: x.distance(mid_pt)) if pieces_ else P
            sub = f"{sid}/{k + 1}"
            sax = substring(axis, bounds[k], bounds[k + 1])
            sax = straight(sax) if sax.geom_type == "LineString" and sax.length >= 1 else axis
            sub_axis[sub] = (sax, s["left"], s["right"], i, Q)
            units.append((sub, "subsection", sid, Q))
            sub_rows.append((sub, sid, sax, Q, s, "section end" if k == 0 else "lanes change"))

    # ---- intersections: ids from the OSM junction nodes in them
    nodes = {}
    for r in roads:
        for nid, pt in ((r[5], r[7].coords[0]), (r[6], r[7].coords[-1])):
            if nid is not None:
                nodes.setdefault(nid, shapely.Point(pt))
    for nid, pt in rows(f"""SELECT src, {m('ST_StartPoint(geometry)')} FROM space.element WHERE type = 'road' AND level_min = 0 AND src IS NOT NULL
                           UNION SELECT dst, {m('ST_EndPoint(geometry)')} FROM space.element WHERE type = 'road' AND level_min = 0 AND dst IS NOT NULL"""):
        nodes.setdefault(nid, g(pt))
    ntree = shapely.STRtree(list(nodes.values()))
    nids = list(nodes)
    inter_ids, used = [], {}
    for x in inter:
        inside = sorted(nids[k] for k in ntree.query(x) if x.contains(nodes[nids[k]]))
        iid = f"i0-{inside[0]}" if inside else f"i0-x{round(x.centroid.x)}y{round(x.centroid.y)}"
        used[iid] = used.get(iid, 0) + 1
        if used[iid] > 1:
            iid += f".{used[iid]}"
        inter_ids.append(iid)
        units.append((iid, "intersection", None, x))
        junction += [(iid, n, 0, iid) for n in inside]
    for c_, j, end in cuts:
        if j not in section_ids:
            continue
        near = [inter_ids[k] for k, x in enumerate(inter) if x.distance(c_) < 0.1]
        rd = [str(r[0]) for k in road_tree.query(c_) for r in [roads[k]] if r[7].intersects(c_)]
        cut_rows.append((near[0] if near else None, rd[0] if rd else None, c_))

    # ---- the inside of each subsection: strips parallel to its axis
    kerbs_of = {}
    pid = {}

    def add(uid, typ, geom, **kw):
        for p in shapely.get_parts(geom):
            if p.geom_type != "Polygon" or p.area < 0.05:
                continue
            pid[uid] = pid.get(uid, 0) + 1
            parts.append(dict(unit_id=uid, part_id=f"{uid}#{pid[uid]}", type=typ, geom=p, **kw))

    def mark(uid, typ, geom, src="urbanstyle", method="derived", ref=None):
        if geom is not None and not geom.is_empty:
            marks.append((uid, typ, geom, src, method, ref))

    for sub, (ax, L, R, i, Q) in sub_axis.items():
        n = int(ax.length // 4) + 1
        prs = [profile(ax, Q, min(k * 4.0 + 2.0, ax.length)) for k in range(n)]
        prs = [p for p in prs if p] or [[]]
        # the carriageways: their offsets and widths, the median over the subsection (they run parallel to the axis)
        nc = statistics.median_low([len(p) for p in prs])
        same = [p for p in prs if len(p) == nc]
        cw = []
        for k in range(nc):
            cs = [p[k] for p in same]
            cw.append(dict(t=statistics.median([c[0] for c in cs]), w=statistics.median([c[1] for c in cs]), al=cs[0][2], ag=cs[0][3], road=cs[0][4],
                           fw=cs[0][5]))
        # the block on each side
        hs = [across(ax, min(k * 4.0 + 2.0, ax.length)) for k in range(n)]
        tl = statistics.median([h[1][2] for h in hs if h[1]] or [10.0])
        tr = -statistics.median([h[-1][2] for h in hs if h[-1]] or [10.0])
        # the kerbs: from OSM's sidewalks running along it (1 m before their line), else the carriageways' outer edges
        swl, swr = [], []
        if walk_tree is not None:
            ux, uy = tangent(ax, ax.length / 2)
            for k in walk_tree.query(Q):
                w = walks[k].intersection(Q)
                if w.is_empty or w.length < 5:
                    continue
                wl = max((p for p in shapely.get_parts(w) if p.geom_type == "LineString"), key=lambda p: p.length, default=None)
                if wl is None:
                    continue
                wx, wy = tangent(wl, wl.length / 2)
                if abs(wx * ux + wy * uy) < 0.82:
                    continue
                c_ = wl.interpolate(0.5, normalized=True)
                q = ax.interpolate(ax.project(c_))
                t = (c_.x - q.x) * -uy + (c_.y - q.y) * ux
                (swl if t > 0 else swr).append(t)
        outer_l = max([c["t"] + c["w"] / 2 for c in cw], default=0.0)
        outer_r = min([c["t"] - c["w"] / 2 for c in cw], default=0.0)
        if cw:
            kl = max(outer_l, min(swl) - SIDEWALK_HALF_M) if swl else outer_l
            kr = min(outer_r, max(swr) + SIDEWALK_HALF_M) if swr else outer_r
            # trees, poles and furniture stand behind the kerb: it runs OBJECT_BACK_M on the road's side of the innermost one
            ol = [t for t in objects_in(ax, Q, 1) if t > outer_l + OBJECT_BACK_M and (not swl or t < min(swl))]
            orr = [t for t in objects_in(ax, Q, -1) if t < outer_r - OBJECT_BACK_M and (not swr or t > max(swr))]
            if len(ol) >= 2:
                kl = min(kl, statistics.median_low(sorted(ol)[:max(2, len(ol) // 2)]) - OBJECT_BACK_M) if swl else kl
            if len(orr) >= 2:
                kr = max(kr, statistics.median_high(sorted(orr)[-max(2, len(orr) // 2):]) + OBJECT_BACK_M) if swr else kr
            kl_m, kr_m = ("measured" if swl else "chosen"), ("measured" if swr else "chosen")
            kl, kr = min(kl, tl - MIN_REALM_M), max(kr, tr + MIN_REALM_M)
            if kl <= kr:
                kl, kr = (tl + tr) / 2 + 0.01, (tl + tr) / 2 - 0.01
        else:
            kl = kr = None
        kerbs_of[sub] = (kl, kr, ax, L, R)
        road = cw[0]["road"] if cw else None
        common = dict(road=road[1] if road else None, road_class=road[2] if road else None,
                      road_lanes=sum(c["al"] + c["ag"] for c in cw) or None, oneway=all(c["ag"] == 0 or c["al"] == 0 for c in cw) if cw else None,
                      ref=",".join(sorted({f"w{c['road'][0]}" for c in cw})) or None)
        if kl is None:
            add(sub, "sidewalk", Q, width_m=round(tl - tr, 2), width_method="derived", direction=None, lane=None, **common)
            widths.append((sub, None, None, round(tl - tr, 2), 0.0, round(tl, 2), round(-tr, 2), 0, 0, None, "urbanstyle"))
            continue
        # the pedestrian realm on each side, in NACTO's zones from the kerb out: buffer (furnishing), clear path (sidewalk), frontage
        for sg, kerb, edge, line_t, arm in ((1, kl, tl, min(swl) if swl else None, "left"), (-1, kr, tr, max(swr) if swr else None, "right")):
            total = abs(edge - kerb)
            dist = lambda t: (t - kerb) * sg            # from the kerb, outwards
            band = lambda d1, d2, far=False: offset_band(ax, *sorted((kerb + sg * d1, kerb + sg * (d2 + (30 if far else 0)))), Q)
            if total < CLEAR_M:
                add(sub, "sidewalk", band(0, total, True), width_m=round(total, 2), width_method="derived", direction=None, lane=None, arm=arm, **common)
                continue
            ds = [dist(t) for t in objects_in(ax, Q, sg) if 0 < dist(t) < total]
            f, f_m = (min(max(2 * statistics.median(ds), FURNISH_M[1]), FURNISH_M[2]), "measured") if len(ds) >= 2 else (FURNISH_M[0], "chosen")
            if line_t is not None:      # the clear path around OSM's sidewalk line
                c0 = min(max(dist(line_t) - CLEAR_M / 2, 0.0), total - CLEAR_M)
                c_m = "measured"
            else:
                c0, c_m = min(f, total - CLEAR_M), "chosen"
            c1 = min(c0 + CLEAR_M, total)
            if total - c1 < FRONTAGE_MIN_M:
                c1 = total
            if c0 < FRONTAGE_MIN_M:         # no room for a buffer: the clear path reaches the kerb
                c0 = 0.0
            else:
                add(sub, "furnishing", band(0, c0), width_m=round(c0, 2), width_method=f_m if line_t is None else "derived", direction=None, lane=None, arm=arm, **common)
            add(sub, "sidewalk", band(c0, c1, c1 >= total), width_m=round(c1 - c0, 2), width_method=c_m, direction=None, lane=None, arm=arm, **common)
            if c1 < total:
                add(sub, "frontage", band(c1, total, True), width_m=round(total - c1, 2), width_method="derived", direction=None, lane=None, arm=arm, **common)
        mark(sub, "kerb", line_at(ax, kl, Q, LINE["kerb"]), method=kl_m)
        mark(sub, "kerb", line_at(ax, kr, Q, LINE["kerb"]), method=kr_m)
        # the roadway: carriageways right to left, a median between them, a shoulder where the kerb stands wider
        cw = sorted(cw, key=lambda c: c["t"])
        edges = []
        for k, c in enumerate(cw):
            lo = kr if k == 0 else (cw[k - 1]["t"] + cw[k - 1]["w"] / 2 + c["t"] - c["w"] / 2) / 2
            hi = kl if k == len(cw) - 1 else (c["t"] + c["w"] / 2 + cw[k + 1]["t"] - cw[k + 1]["w"] / 2) / 2
            edges.append([lo, hi])
        for k in range(len(cw) - 1):    # a median where two carriageways stand apart
            a_, b_ = cw[k]["t"] + cw[k]["w"] / 2, cw[k + 1]["t"] - cw[k + 1]["w"] / 2
            if b_ - a_ > MEDIAN_MIN_M:
                edges[k][1], edges[k + 1][0] = a_, b_
                add(sub, "island", offset_band(ax, a_, b_, Q), width_m=round(b_ - a_, 2), width_method="derived", direction=None, lane=None, **common)
                mark(sub, "kerb", line_at(ax, a_, Q, LINE["kerb"]))
                mark(sub, "kerb", line_at(ax, b_, Q, LINE["kerb"]))
        lin, lout = 0, 0
        for c, (lo, hi) in zip(cw, edges):
            nl = c["al"] + c["ag"]
            room = hi - lo
            inner = max(room - 2 * SHOULDER_EDGE_M, 0.5 * room)     # a shoulder at each edge (the gutter), the lanes between
            lw = inner / nl if LANE_RANGE[0] <= inner / nl <= LANE_RANGE[1] else min(LANE_M, inner / nl)
            lw_m = "measured" if (swl or swr) else "chosen"
            body = lw * nl
            # lanes going along the axis keep right (the axis's right is negative offsets); the rest, a shoulder at each edge, evenly
            spare = room - body
            start = lo + spare / 2
            if spare > 0.05:
                add(sub, "shoulder", offset_band(ax, lo, start, Q), width_m=round(spare / 2, 2), width_method="derived", direction=None, lane=None, **common)
                add(sub, "shoulder", offset_band(ax, start + body, hi, Q), width_m=round(spare / 2, 2), width_method="derived", direction=None, lane=None, **common)
            rd = c["road"]
            al_dir, ag_dir = ("forward", "backward") if c["fw"] else ("backward", "forward")     # relative to the OSM way
            for k in range(nl):
                t1, t2 = start + k * lw, start + (k + 1) * lw
                along = k < c["al"]
                add(sub, "lane", offset_band(ax, t1, t2, Q), width_m=round(lw, 2), width_method=lw_m,
                    direction=al_dir if along else ag_dir, lane=(k + 1) if along else (nl - k), **{**common, "ref": f"w{rd[0]}"})   # 1 at the kerb
                if k:
                    mark(sub, "centre line" if k == c["al"] else "lane line", line_at(ax, t1, Q, LINE["centre line"]), ref=f"w{rd[0]}")
            lin += c["ag"]
            lout += c["al"]
            # stop lines: across the lanes that run toward an end at an intersection, STOP_BACK_M before it
            for end, toward in ((ax.length, True), (0.0, False)):
                lanes_t = (start, start + c["al"] * lw) if toward else (start + c["al"] * lw, start + nl * lw)
                if lanes_t[1] - lanes_t[0] < 0.5:
                    continue
                sv = end - STOP_BACK_M if toward else end + STOP_BACK_M
                p = ax.interpolate(sv)
                if not any(x.distance(ax.interpolate(end)) < ARM_M + 1 for x in inter):
                    continue
                ux, uy = tangent(ax, sv)
                ln = shapely.LineString([(p.x - uy * lanes_t[0], p.y + ux * lanes_t[0]), (p.x - uy * lanes_t[1], p.y + ux * lanes_t[1])])
                mark(sub, "stop line", poly(ln.buffer(LINE["stop line"] / 2, cap_style="flat").intersection(Q)), ref=f"w{rd[0]}")
        widths.append((sub, None, None, round(tl - tr, 2), round(kl - kr, 2), round(tl - kl, 2), round(kr - tr, 2), lin, lout,
                       round(statistics.median([p["width_m"] for p in parts if p["unit_id"] == sub and p["type"] == "lane"] or [0]), 2), "urbanstyle"))

    # ---- the inside of each intersection: a pedestrian corner where two arms' kerbs meet at a block, the junction area the rest
    def _halfplane(ax, t, sg, at_end):
        """The side of the kerb line at offset t of the axis (left if sg = 1) that holds the block, as a large polygon near one end."""
        sv = ax.length if at_end else 0.0
        p = ax.interpolate(sv)
        ux, uy = tangent(ax, sv)
        nx, ny = -uy * sg, ux * sg                     # towards the block
        bx, by = p.x - uy * t, p.y + ux * t           # on the kerb line
        L_ = 200.0
        return shapely.Polygon([(bx - ux * L_, by - uy * L_), (bx + ux * L_, by + uy * L_),
                                (bx + ux * L_ + nx * L_, by + uy * L_ + ny * L_), (bx - ux * L_ + nx * L_, by - uy * L_ + ny * L_)])

    for iid, X in zip(inter_ids, inter):
        arms = []       # (subsection, at its end, its kerb offsets)
        for sub, (kl, kr, ax, L, R) in kerbs_of.items():
            if kl is None:
                continue
            for at_end in (False, True):
                if ax.interpolate(ax.length if at_end else 0.0).distance(X) < ARM_M + 1.5 and sub_axis[sub][4].distance(X) < 0.1:
                    arms.append((sub, at_end, kl, kr, ax, L, R))
        corners = []
        for k in set([a[5] for a in arms] + [a[6] for a in arms]):
            hp = []
            for sub, at_end, kl, kr, ax, L, R in arms:
                if k == L:
                    hp.append(_halfplane(ax, kl, 1, at_end))
                if k == R:
                    hp.append(_halfplane(ax, kr, -1, at_end))
            if not hp:
                continue
            c = X
            for h in hp:
                c = c.intersection(h)
            if k >= 0:      # only the corner of this block: near it
                c = c.intersection(bgeo[k].buffer(RAY_M / 2))
            corners.append(poly(c))
        walkway = poly(shapely.union_all(corners)) if corners else shapely.Polygon()
        roadway = poly(X.difference(walkway, grid_size=0.01))
        if not roadway.is_empty:    # the kerb's corner rounded
            roadway = poly(roadway.buffer(KERB_RADIUS_M, quad_segs=4, join_style="round").buffer(-KERB_RADIUS_M, quad_segs=4, join_style="round")
                           .intersection(X, grid_size=0.01))
            walkway = poly(X.difference(roadway, grid_size=0.01))
        add(iid, "junction area", roadway, width_m=None, width_method=None, direction=None, lane=None, road=None, road_class=None,
            road_lanes=None, oneway=None, ref=None)
        add(iid, "sidewalk", walkway, width_m=None, width_method="derived", direction=None, lane=None, road=None, road_class=None,
            road_lanes=None, oneway=None, ref=None)
        k_ = roadway.boundary.intersection(walkway.buffer(0.02)) if not roadway.is_empty and not walkway.is_empty else shapely.LineString()
        if not k_.is_empty and k_.length > 0.5:
            mark(iid, "kerb", poly(k_.buffer(LINE["kerb"] / 2, cap_style="flat").intersection(X)))
        widths.append((iid, None, None, None, None, None, None, None, None, None, "urbanstyle"))

    # ---- crosswalks: zebra bars where OSM maps a crossing over the roadway (they lie on lanes and the junction area, cutting nothing)
    roadway_parts = [(p["unit_id"], p["geom"]) for p in parts if p["type"] in ("lane", "shoulder", "junction area")]
    rwt = shapely.STRtree([x for _, x in roadway_parts]) if roadway_parts else None
    wz, gap, ln_ = ZEBRA
    for oid, cl in crossings:
        if rwt is None:
            break
        for k in rwt.query(cl):
            uid, RW = roadway_parts[k]
            seg = cl.intersection(RW)
            for s_ in shapely.get_parts(seg):
                if s_.geom_type != "LineString" or s_.length < 0.5:
                    continue
                for j in range(int(s_.length // gap) + 1):
                    sv = min(j * gap + gap / 2, s_.length)
                    p = s_.interpolate(sv)
                    ux, uy = tangent(s_, sv)
                    bar = shapely.LineString([(p.x - ux * wz / 2, p.y - uy * wz / 2), (p.x + ux * wz / 2, p.y + uy * wz / 2)])
                    mark(uid, "zebra", poly(bar.buffer(ln_ / 2, cap_style="flat").intersection(RW)), src="osm", method="mapped", ref=f"w{oid}")

    # ---- no crumbs: a strip under PIECE_MIN_M2 joins its neighbour in the same space (never a lane: a lane keeps its own)
    by_unit = {}
    for p in parts:
        by_unit.setdefault(p["unit_id"], []).append(p)
    for uid, ps in by_unit.items():
        for p in sorted(ps, key=lambda p: p["geom"].area):
            if p["geom"].area >= PIECE_MIN_M2 or p["type"] in ("lane", "junction area") or p.get("gone"):
                continue
            nb = [q for q in ps if q is not p and not q.get("gone") and q["geom"].distance(p["geom"]) < 0.05]
            if not nb:
                continue
            q = max(nb, key=lambda q: q["geom"].boundary.intersection(p["geom"].boundary.buffer(0.05)).length)
            q["geom"] = poly(shapely.union_all([q["geom"], p["geom"]], grid_size=0.01))
            p["gone"] = True
    parts = [p for p in parts if not p.get("gone")]

    # ---- write: the level-0 spaces and their insides replace those of spaces.py / parts.py
    to_ll = f"ST_Transform(ST_GeomFromWKB(?), '{epsg}', 'EPSG:4326', always_xy := true)"
    old = [u for (u,) in rows("SELECT unit_id FROM space.unit WHERE level = 0")]
    for t, cols in SCHEMA.items():      # each table with its types, whatever made it
        have = {c for (c,) in rows(f"SELECT column_name FROM information_schema.columns WHERE table_schema = 'space' AND table_name = '{t}'")}
        q_ = lambda c: f'"{c}"'
        if have:
            con.execute(f"CREATE OR REPLACE TABLE space.{t} AS SELECT " + ", ".join(
                (f"CAST({q_(c)} AS {ty}) AS {q_(c)}" if c in have else f"CAST(NULL AS {ty}) AS {q_(c)}") for c, ty in cols.items()) + f" FROM space.{t}")
        else:
            con.execute(f"CREATE TABLE space.{t} (" + ", ".join(f"{q_(c)} {ty}" for c, ty in cols.items()) + ")")
    turns = rows(f"SELECT rowid, {m('ST_Centroid(geometry)')} FROM space.turn WHERE level = 0")
    for t, col in (("part", "unit_id"), ("mark", "unit_id"), ("width", "unit_id"), ("approach", "unit_id")):
        try:
            con.execute(f"DELETE FROM space.{t} WHERE level = 0")
        except duckdb.Error:
            pass
    for t in ("cut", "junction", "subsection"):
        con.execute(f"DELETE FROM space.{t} WHERE level = 0")
    if turns:       # each turn to the new intersection holding its middle
        itree = shapely.STRtree(inter)
        moved = []
        for rid, w in turns:
            c_ = g(w)
            k = [k for k in itree.query(c_) if inter[k].distance(c_) < 1.0]
            moved.append((inter_ids[k[0]] if k else None, rid))
        con.executemany("UPDATE space.turn SET unit_id = ? WHERE rowid = ?", moved)
        con.execute("DELETE FROM space.turn WHERE level = 0 AND unit_id IS NULL")
    con.execute("DELETE FROM space.unit WHERE level = 0")
    if decks:       # a deck taken as the street at ground level: its old level-1 spaces go too
        dk = shapely.union_all(decks)
        gone = [u for u, w in rows(f"SELECT unit_id, {m()} FROM space.unit WHERE level = 1") if g(w).intersection(dk).length > 5.0]
        for u in gone:
            for t in ("part", "mark", "width", "turn", "approach"):
                try:
                    con.execute(f"DELETE FROM space.{t} WHERE unit_id = ?", [u])
                except duckdb.Error:
                    pass
            for t, col in (("cut", "intersection_id"), ("junction", "intersection_id"), ("subsection", "subsection_id")):
                try:
                    con.execute(f"DELETE FROM space.{t} WHERE {col} = ?", [u])
                except duckdb.Error:
                    pass
            con.execute("DELETE FROM space.unit WHERE unit_id = ?", [u])
    con.executemany(f"INSERT INTO space.unit (unit_id, kind, section_id, level, color, geometry) VALUES (?, ?, ?, 0, ?, {to_ll})",
                    [(u, k, s, COLORS[k], shapely.to_wkb(x)) for u, k, s, x in units])
    if cut_rows:
        con.executemany(f"INSERT INTO space.cut (intersection_id, edge_id, level, how, length_m, geometry) VALUES (?, ?, 0, 'block corner + 3 m', ?, {to_ll})",
                        [(i, e, round(c.length, 2), shapely.to_wkb(c)) for i, e, c in cut_rows])
    if junction:
        con.executemany("INSERT INTO space.junction (intersection_id, node_id, level, cluster_id) VALUES (?, ?, ?, ?)", junction)
    srow = []
    for sub, sid, sax, Q, s, why in sub_rows:
        kl, kr = kerbs_of.get(sub, (None, None))[:2]
        cl = next((p["road_class"] for p in parts if p["unit_id"] == sub and p.get("road_class")), None)
        ow = next((p["oneway"] for p in parts if p["unit_id"] == sub and p.get("oneway") is not None), None)
        srow.append((sub, sid, cl, None if kl is None else round(kl - kr, 2), ow, round(sax.length, 1),
                     bid[s["left"]] if s["left"] >= 0 else "edge", bid[s["right"]] if s["right"] >= 0 else "edge", why, shapely.to_wkb(sax)))
    if srow:
        con.executemany(f"""INSERT INTO space.subsection (subsection_id, section_id, level, class, width_m, oneway, length_m, "left", "right",
                            starts_at, color, geometry) VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?, '#e6194b', {to_ll})""", srow)
    if parts:
        con.executemany(f"""INSERT INTO space.part (unit_id, part_id, level, type, arm, direction, lane, width_m, width_source, width_method,
                            length_m, source, method, ref, road, road_class, road_lanes, oneway, geometry)
                            VALUES (?, ?, 0, ?, ?, ?, ?, ?, 'urbanstyle', ?, ?, 'urbanstyle', 'derived', ?, ?, ?, ?, ?, {to_ll})""",
                        [(p["unit_id"], p["part_id"], p["type"], p.get("arm"), p.get("direction"), p.get("lane"), p.get("width_m"),
                          p.get("width_method"), round(p["geom"].length / 2, 1), p.get("ref"), p.get("road"), p.get("road_class"),
                          p.get("road_lanes"), p.get("oneway"), shapely.to_wkb(p["geom"])) for p in parts])
    if marks:
        con.executemany(f"""INSERT INTO space.mark (unit_id, level, type, length_m, width_m, width_source, width_method, source, method, ref, geometry)
                            VALUES (?, 0, ?, ?, ?, 'urbanstyle', 'chosen', ?, ?, ?, {to_ll})""",
                        [(u, t, round(x.length / 2, 1), LINE.get(t), s_, me, r, shapely.to_wkb(x)) for u, t, x, s_, me, r in marks])
    if widths:
        con.executemany("""INSERT INTO space.width (unit_id, level, edge, arm, total_m, carriageway_m, left_m, right_m, lanes_in, lanes_out, lane_m, source)
                           VALUES (?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", widths)
    return dict(old_units=len(old), subsections=sum(1 for u in units if u[1] == "subsection"), intersections=len(inter),
                sections=len(section_ids), parts=len(parts), marks=len(marks))
