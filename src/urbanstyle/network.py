"""Steps 2-7 of docs/design/pipeline.md: the street at level 0 from the road network, data first. It writes the same level-0 rows as
division.py (space.unit, part, mark, subsection, junction) and replaces it when URBANSTYLE_DIVISION=network.

    roads        OSM's street roads at level 0 (not paths, not pedestrian streets, not the ways of a bridge that has a profile)
    carriageway  each road's lanes from OSM (`lanes`, per direction from duckOSM's driving network; a two-way road one lane each way at
                 least), centred on its own OSM line, LANE_M each or OSM `width` shared; parking and bike lanes beside them only where
                 OSM tags them; the kerb is its outer edge (a result, never guessed)
    junctions    at each node where 3 or more road ends meet (a road through it counts 2): the arms' carriageways where they overlap, out
                 to each arm's crosswalk (OSM, within CROSS_NEAR_M) or JUNC_ARM_M past the overlap, corners rounded by KERB_RADIUS_M;
                 junctions that overlap are one (id i0-<smallest node>)
    sections     each road from junction to junction (id s0-w<way>[.n], one subsection /1 each): its carriageway less the junctions
    pedestrian   the street (the area less the blocks) less the roadway, each piece to the nearest roadway (section or junction):
                 furnishing FURNISH_M, sidewalk CLEAR_M, the rest frontage (chosen widths)
    marks        kerbs (the roadway's edge facing the pedestrian side), lane lines, centre lines
"""
import json
import math

STREET = ("motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street")
LANE_M = 3.25           # a lane where OSM gives no width (chosen)
LANE_RANGE = (2.5, 4.5)  # a lane from OSM's width shared by its lanes, kept in this range
PARK_M, BIKE_M = 2.4, 1.75  # a parking lane, a bike lane (chosen)
FURNISH_M, CLEAR_M = 1.0, 1.8   # the pedestrian side: the furnishing zone at the kerb, the clear path (chosen)
KERB_RADIUS_M = 4.0
JUNC_ARM_M, CROSS_NEAR_M, CROSS_HALF_M, ARM_LEN_M = 3.0, 15.0, 1.5, 80.0
SAMPLE_M = 1.5
STOP_BACK_M = 1.0       # a stop line stands this far before the junction (chosen, as division.py)
CROSSWALK_M, ZEBRA_BAR_M, ZEBRA_GAP_M = 3.0, 0.5, 0.5     # a crosswalk where OSM gives no width; its bars (as parts.py)          # the roadway's edge sampled this often to share the pedestrian side out
COLORS = {"subsection": "#94a3b8", "intersection": "#fbbf24"}
YES_PARK = ("parallel", "diagonal", "perpendicular", "lane", "street_side", "on_street", "half_on_kerb", "on_kerb", "marked", "yes")
YES_BIKE = ("lane", "track", "buffered_lane", "opposite_lane", "opposite_track")
ARM_M = 3.0             # a junction reaches this far into each arm (bridge_lidar reads it)
GAP_M = 8.0             # a strip between two roadways narrower than this (a block is at least this wide) is roadway, unless OSM maps a kerb, an object or a path on it
STRAIGHT_M = 2.0        # a road between two junctions whose OSM line stays this near the straight line between its ends is drawn straight
                        # (chosen: OSM's drawing error; Fir Street, Kaveh 2026-10-14)
ISLAND_MIN_M2 = 4.0     # a pedestrian piece that touches no block and is smaller than this is no island: it is part of the sidewalk (chosen)
from .parts import ARROW_M  # noqa: E402

def straight(ln):
    """ln as the straight line between its ends where it stays within STRAIGHT_M of that line, else ln (a real curve)."""
    import shapely
    ch = shapely.LineString([ln.coords[0], ln.coords[-1]])
    return ch if ch.length > 0.5 and ln.hausdorff_distance(ch) <= STRAIGHT_M else ln


# the level-0 tables this module writes, with their columns and types (other levels: spaces.py, parts.py)
V, D, I, G_ = "VARCHAR", "DOUBLE", "INTEGER", "GEOMETRY"
SCHEMA = {
    "unit": dict(unit_id=V, kind=V, section_id=V, level=I, color=V, geometry=G_),
    "part": dict(unit_id=V, part_id=V, level=I, type=V, arm=V, direction=V, lane=I, lane_id=V, width_m=D, width_source=V, width_method=V, length_m=D,
                 source=V, method=V, ref=V, position_source=V, position_method=V, position_ref=V, road=V, road_class=V, speed=V, surface=V, lit=V, road_lanes=V, oneway=V, holds=V, rule=V, geometry=G_),
    "mark": dict(unit_id=V, level=I, type=V, arm=V, length_m=D, width_m=D, width_source=V, width_method=V, source=V, method=V, ref=V, geometry=G_),
    "width": dict(unit_id=V, level="BIGINT", edge=V, arm=V, total_m=D, carriageway_m=D, left_m=D, right_m=D, lanes_in="BIGINT", lanes_out="BIGINT",
                  lane_m=D, source=V, osm_lanes="BIGINT"),
    "subsection": dict(subsection_id=V, section_id=V, level=I, **{"class": V}, width_m=D, oneway="BOOLEAN", length_m=D, left=V, right=V, left_m=D,
                       right_m=D, left_extra=D, right_extra=D, with_sections=V, starts_at=V, color=V, geometry=G_),
    "cut": dict(intersection_id=V, edge_id=V, level=I, how=V, length_m=D, geometry=G_),
    "junction": dict(intersection_id=V, node_id="BIGINT", level=I, cluster_id=V),
    "turn": dict(unit_id=V, level=I, from_edge=V, from_lane=I, to_edge=V, to_lane=I, turn=V, source=V, vehicles=V, condition=V, geometry=G_),
    "approach": dict(unit_id=V, level=I, from_edge=V, lane=I, moves=I, ways=V, arrow="BOOLEAN", no_arrow_because=V),
}


def arrow_shape(tip, h, ways):
    """A painted lane arrow (parts.py's shape): a shaft ARROW_M long to `tip` along unit h, a head for each of `ways` (straight, left,
    right)."""
    import shapely
    hx, hy = h
    tail = (tip[0] - hx * ARROW_M, tip[1] - hy * ARROW_M)
    fork = (tail[0] + hx * ARROW_M * 0.45, tail[1] + hy * ARROW_M * 0.45)
    pieces, heads = [[tail, tip if "straight" in ways else fork]], []
    if "straight" in ways:
        heads.append((tip, (hx, hy)))
    for w in ("left", "right"):
        if w in ways:
            sx, sy = (-hy, hx) if w == "left" else (hy, -hx)
            end = (fork[0] + hx * 0.7 + sx * 1.0, fork[1] + hy * 0.7 + sy * 1.0)
            pieces.append([fork, end])
            d = math.hypot(end[0] - fork[0], end[1] - fork[1])
            heads.append((end, ((end[0] - fork[0]) / d, (end[1] - fork[1]) / d)))
    for (px, py), (dx, dy) in heads:
        pieces.append([(px - dx * 0.8 - dy * 0.4, py - dy * 0.8 + dx * 0.4), (px, py), (px - dx * 0.8 + dy * 0.4, py - dy * 0.8 - dx * 0.4)])
    return shapely.MultiLineString(pieces)


def build(con, epsg, bridges=()):
    import duckdb
    import numpy as np
    import shapely
    from shapely.ops import substring

    m = lambda col="geometry": f"ST_AsWKB(ST_Transform({col}, 'EPSG:4326', '{epsg}', always_xy := true))"
    g = lambda w: shapely.make_valid(shapely.from_wkb(bytes(w)))
    poly = lambda x: shapely.union_all([p for q in shapely.get_parts(x) for p in shapely.get_parts(q) if p.geom_type == "Polygon"]
                                       or [shapely.Polygon()])
    to_ll = f"ST_Transform(ST_GeomFromWKB(?), '{epsg}', 'EPSG:4326', always_xy := true)"

    def rows(sql, args=None):
        try:
            return con.execute(sql, args or []).fetchall()
        except duckdb.CatalogException:
            return []

    # ---- 2. the road network
    bridge_ways = {int(w[1:]) for pf in bridges for a in json.load(open(pf)).get("axes", []) for w in a.get("ways", [])}
    cand = [(oid, nm, cl, bool(ow), s_, d_, g(w), lv) for oid, nm, cl, ow, s_, d_, w, lv in rows(f"""SELECT osm_id, name, class, coalesce(oneway, false),
                 src, dst, {m()}, level_min FROM space.element WHERE type IN ('road', 'walkway') AND level_min IN (0, 1)
                 AND replace(class, '_link', '') IN {STREET}""")]
    # (a level-1 deck is the street at ground level where nothing at level 0 passes under it, as for the blocks; the ways of a bridge that
    # has a profile are the bridge model's: one 'bridge deck' part on their band, no lanes)
    ground_lines = [c[6] for c in cand if c[7] == 0] + [g(w) for (w,) in rows(f"SELECT {m()} FROM space.element WHERE type = 'rail' AND level_min = 0")]
    gl_tree = shapely.STRtree(ground_lines) if ground_lines else None
    keep_ = [c for c in cand if c[7] == 0 or gl_tree is None or not any(ground_lines[k].crosses(c[6]) for k in gl_tree.query(c[6]))]
    edges = [c[:7] for c in keep_]
    l1_ground = {c[0] for c in keep_ if c[7] == 1} - bridge_ways      # (drawn here on the ground: no copy at level 1, below)
    edges = [e for e in edges if e[6].geom_type == "LineString" and e[6].length > 0.2]
    oids = sorted({e[0] for e in edges})
    tags = {o: dict(t or {}) for o, t in rows("SELECT osm_id, tags FROM osm.raw.ways WHERE osm_id IN (SELECT unnest(?::BIGINT[]))", [oids])}
    try:        # (duckOSM's lanes per direction; a network without them: OSM's tags alone)
        lanes = {(o, bool(r)): int(n) for o, r, n in con.execute("""SELECT osm_id, is_reverse, median(lanes) FROM osm.driving.edges
                                                                    WHERE lanes IS NOT NULL GROUP BY 1, 2""").fetchall()}
    except duckdb.Error:
        lanes = {}
    from .corrections import lanes as corrected, per_direction
    CORR = corrected()
    for o, (tg_c, _) in CORR.items():
        f_c, b_c = per_direction(tg_c, (o, True) not in lanes)
        lanes[(o, False)] = f_c
        if b_c:
            lanes[(o, True)] = b_c
    num = lambda v: int(v) if str(v or "").isdigit() else None
    from .blocks import _city
    city = _city(con)

    def city_geoms(name):
        out = []
        for f in (city.get(name) or {}).get("features", []):
            if f.get("geometry"):
                (w,) = con.execute(f"SELECT ST_AsWKB(ST_Transform(ST_GeomFromGeoJSON(?), 'EPSG:4326', '{epsg}', always_xy := true))",
                                   [json.dumps(f["geometry"])]).fetchone()
                out.append((f.get("properties") or {}, g(w)))
        return out
    meters = [(f"parking-meters:{pr.get('meter_id')}", x) for pr, x in city_geoms("parking-meters")]
    bikeways = [(f"bikeways:{pr.get('object_id')}", x) for pr, x in city_geoms("bikeways")
                if any(k in str(pr.get("bikeway_type") or "") for k in ("Painted", "Protected", "Separated"))]
    meter_t = shapely.STRtree([x for _, x in meters]) if meters else None
    bike_t = shapely.STRtree([x for _, x in bikeways]) if bikeways else None

    def cross_section(oid, ow):
        """(forward lanes, backward lanes, lane width, its source, extras {+1: [(type, w, source)], -1: [...]}, lane source)."""
        tg = tags.get(oid, {})
        f, b = lanes.get((oid, False)), lanes.get((oid, True))
        n = num(tg.get("lanes"))
        if f is None and b is None:
            if ow:
                f, b = n or 1, 0
            else:
                f = num(tg.get("lanes:forward")) or (n // 2 if n and n >= 2 else 1)
                b = num(tg.get("lanes:backward")) or ((n - f) if n and n > f else 1)
        if ow:
            f, b = max(f or 1, 1), 0
        else:       # (a two-way road has a lane each way at least)
            f, b = max(f or 1, 1), max(b or 1, 1)
        lsrc = ("corrections", "corrected") if oid in CORR else ("osm", "mapped") if (n or (oid, False) in lanes) else ("urbanstyle", "chosen")
        wd = None
        try:
            wd = float(str(tg.get("width", "")).replace("m", "").strip()) if tg.get("width") else None
        except ValueError:
            wd = None
        lw, wsrc = (min(max(wd / (f + b), LANE_RANGE[0]), LANE_RANGE[1]), ("osm", "mapped")) if wd else (LANE_M, ("urbanstyle", "chosen"))
        ex = {1: [], -1: []}
        side = lambda s: 1 if s == "left" else -1          # (OSM's left of the way is our + side: the line runs the way's way)
        for k, v in tg.items():
            if k.startswith("cycleway") and k.count(":") <= 1 and v in YES_BIKE:
                for s in (("left", "right") if k in ("cycleway", "cycleway:both") else (k.split(":")[1],) if ":" in k else ()):
                    if s in ("left", "right"):
                        ex[side(s)].append(("cycle lane", BIKE_M, ("osm", "mapped", f"w{oid} {k}={v}")))
        for k, v in tg.items():
            if (k.startswith("parking:") and k.count(":") == 1 or k.startswith("parking:lane:") and k.count(":") == 2) and v in YES_PARK:
                s = k.split(":")[-1]
                for s2 in (("left", "right") if s == "both" else (s,)):
                    if s2 in ("left", "right"):
                        ex[side(s2)].append(("parking", PARK_M, ("osm", "mapped", f"w{oid} {k}={v}")))
        return f, b, lw, wsrc, ex, lsrc

    # ---- the junction nodes (3+ road ends; a road through counts 2)
    tree = shapely.STRtree([e[6] for e in edges])
    node_id = {}
    for oid, nm, cl, ow, s_, d_, ln in edges:
        for nid, q in ((s_, ln.coords[0]), (d_, ln.coords[-1])):
            if nid is not None:
                node_id.setdefault((round(q[0], 1), round(q[1], 1)), nid)

    def deg(p):
        d = 0
        for k in tree.query(p.buffer(0.5)):
            ln = edges[k][6]
            if ln.distance(p) <= 0.5:
                s = ln.project(p)
                d += 1 if (s < 0.5 or s > ln.length - 0.5) else 2
        return d
    jn = []
    for e in edges:
        for q in (e[6].coords[0], e[6].coords[-1]):
            p = shapely.Point(q)
            if all(p.distance(o) > 1.0 for o in jn) and deg(p) >= 3:
                jn.append(p)

    # ---- 3-4. carriageways: runs of one way with one cross-section, split at the junction nodes
    groups = {}
    for oid, nm, cl, ow, s_, d_, ln in edges:
        groups.setdefault((oid, nm, cl, ow), []).append(ln)
    def band(line, t1, t2):
        """The strip between offsets t1 < t2 (left +) of line, flat at its ends."""
        side = lambda d: line.buffer(d, single_sided=True, cap_style="flat", join_style="mitre", mitre_limit=3.0) if abs(d) > 1e-6 \
            else shapely.Polygon()
        if t1 >= 0:
            x = side(t2).difference(side(t1))
        elif t2 <= 0:
            x = side(t1).difference(side(t2))
        else:
            x = shapely.union_all([side(t2), side(t1)])
        return poly(shapely.make_valid(x))
    runs = []       # dict(oid, name, class, oneway, line, f, b, lw, ex, kl, kr)
    jtree = shapely.STRtree(jn) if jn else None
    for (oid, nm, cl, ow), ls in groups.items():
        merged = shapely.line_merge(shapely.union_all(ls))
        for ln in shapely.get_parts(merged):
            if ln.geom_type != "LineString" or ln.length < 0.5:
                continue
            cuts = sorted({0.0, ln.length} | {ln.project(jn[k]) for k in (jtree.query(ln.buffer(0.6)) if jtree is not None else [])
                                                if ln.distance(jn[k]) < 0.6})
            for a, b_ in zip(cuts, cuts[1:]):
                if b_ - a < 0.5:
                    continue
                piece = substring(ln, a, b_)
                f, b, lw, wsrc, ex, lsrc = cross_section(oid, ow)
                W = (f + b) * lw
                tg_ = tags.get(oid, {})
                no_ = lambda pre, s: any(tg_.get(k) in ("no", "none", "separate", "no_parking", "no_stopping")
                                         for k in (f"{pre}:{s}", f"{pre}:both", f"{pre}:lane:{s}", f"{pre}:lane:both"))
                for sg, s in ((1, "left"), (-1, "right")):      # (the city's meters and bikeways along a side; OSM's "no" there wins)
                    t0 = sg * W / 2
                    zone = band(piece, min(t0, t0 + sg * 6.0), max(t0, t0 + sg * 6.0))
                    if not any(e[0] == "parking" for e in ex[sg]) and not no_("parking", s) and meter_t is not None:
                        ms = [meters[k][0] for k in meter_t.query(zone) if zone.contains(meters[k][1])]
                        if ms:
                            ex[sg].append(("parking", PARK_M, ("vancouver", "mapped", ", ".join(ms[:3]))))
                    if not any(e[0] == "cycle lane" for e in ex[sg]) and not no_("cycleway", s) and bike_t is not None:
                        bw = [bikeways[k][0] for k in bike_t.query(zone) if bikeways[k][1].intersection(zone).length > 10]
                        if bw:
                            ex[sg].append(("cycle lane", BIKE_M, ("vancouver", "mapped", ", ".join(bw[:3]))))
                kl = W / 2 + sum(w for _, w, _ in ex[1])
                kr = -W / 2 - sum(w for _, w, _ in ex[-1])
                runs.append(dict(oid=oid, name=nm, cl=cl, ow=ow, line=straight(piece), f=f, b=b, lw=lw, wsrc=wsrc, lsrc=lsrc, ex=ex, kl=kl, kr=kr, W=W))

    for r in runs:
        r["cw"] = band(r["line"], r["kr"], r["kl"])

    # ---- 5. junctions
    crossings = [g(w) for (w,) in rows(f"""SELECT {m()} FROM space.element WHERE type IN ('walkway', 'cycleway') AND level_min = 0
                                            AND subtype = 'crossing'""")]
    rtree = shapely.STRtree([r["line"] for r in runs]) if runs else None
    jshapes = []
    for n in jn:
        arms = [runs[k] for k in (rtree.query(n.buffer(1.0)) if rtree is not None else []) if runs[k]["line"].distance(n) < 1.0]
        out = []
        for i, r in enumerate(arms):
            cw = r["cw"].intersection(n.buffer(ARM_LEN_M))
            others = shapely.union_all([a["cw"] for j, a in enumerate(arms) if j != i]) if len(arms) > 1 else shapely.Polygon()
            ov = cw.intersection(others)
            core = max((n.distance(shapely.Point(c)) for q in shapely.get_parts(ov) if q.geom_type == "Polygon" for c in q.exterior.coords),
                       default=0.0)
            reach = core + JUNC_ARM_M
            for x in crossings:
                hit = x.intersection(cw)
                if hit.is_empty:
                    continue
                d = n.distance(hit)
                if core - CROSS_HALF_M <= d <= core + CROSS_NEAR_M:
                    far = max((n.distance(shapely.Point(c)) for q in shapely.get_parts(hit) if q.geom_type == "LineString" for c in q.coords),
                              default=d)
                    reach = max(reach, far + CROSS_HALF_M)
            out.append(cw.intersection(n.buffer(reach)))
        if out:
            J = shapely.union_all(out).buffer(KERB_RADIUS_M, join_style="round").buffer(-KERB_RADIUS_M, join_style="round")
            jshapes.append((n, poly(J)))
    area = shapely.union_all([g(w) for (w,) in rows(f"SELECT {m()} FROM space.area")] or [shapely.Polygon()])
    blocks = shapely.union_all([g(w) for (w,) in rows(f"SELECT {m()} FROM space.block WHERE level = 0")] or [shapely.Polygon()])
    street = poly(area.difference(blocks)) if not area.is_empty else shapely.Polygon()
    clusters = []       # [nodes, shape]
    for n, J in jshapes:
        hit = [c for c in clusters if c[1].intersects(J)]
        for c in hit:
            clusters.remove(c)
        clusters.append([[n] + [x for c in hit for x in c[0]], shapely.union_all([J] + [c[1] for c in hit])])
    junctions = []
    for ns, J in clusters:
        ids = sorted(node_id.get((round(p.x, 1), round(p.y, 1))) or 0 for p in ns)
        nid = next((i for i in ids if i), None)
        jid = f"i0-{nid}" if nid else f"i0-x{round(J.centroid.x)}y{round(J.centroid.y)}"
        junctions.append(dict(id=jid, nodes=[i for i in ids if i], geom=poly(J.intersection(area)) if not area.is_empty else J))
    J_all = shapely.union_all([j["geom"] for j in junctions] or [shapely.Polygon()])

    # ---- 6. sections: each run's carriageway less the junctions
    seen = {}
    for r in runs:
        base = f"s0-w{r['oid']}"
        seen[base] = seen.get(base, 0) + 1
        r["sid"] = base if seen[base] == 1 else f"{base}.{seen[base]}"
        r["sub"] = f"{r['sid']}/1"
        r["road_g"] = poly(r["cw"].difference(J_all))
        if not area.is_empty:
            r["road_g"] = poly(r["road_g"].intersection(area))
    runs = [r for r in runs if not r["road_g"].is_empty and r["road_g"].area > 0.5]
    taken = shapely.Polygon()
    for r in sorted(runs, key=lambda r: (-(r["f"] + r["b"]), STREET.index(r["cl"].replace("_link", "")) if r["cl"].replace("_link", "") in STREET else 99)):
        r["road_g"] = poly(r["road_g"].difference(taken))
        taken = shapely.union_all([taken, r["road_g"]])
    runs = [r for r in runs if not r["road_g"].is_empty and r["road_g"].area > 0.5]
    roadway = shapely.union_all([r["road_g"] for r in runs] + [J_all])

    # ---- 7. the pedestrian side: the street less the roadway, each piece to the nearest roadway
    realm = poly(street.difference(roadway)) if not street.is_empty else shapely.Polygon()
    edge_ = shapely.union_all([blocks.boundary, area.boundary]) if not area.is_empty else blocks.boundary
    # (a strip narrower than GAP_M between two roadways, away from the blocks, is one paved surface with them: our chosen lane widths
    # leave it, no source makes it an island (Fir Street's two one-way ways, Kaveh 2026-10-14); it is an island only where OSM maps a
    # kerb, an object or a path along it)
    gaps = []
    if not realm.is_empty:
        thin = poly(roadway.buffer(GAP_M / 2).buffer(-GAP_M / 2).intersection(realm))     # (the roadway closed over its narrow gaps)
        objs = [g(w) for (w,) in rows(f"""SELECT {m()} FROM space.object WHERE level = 0 AND source = 'osm'
                                          AND class NOT LIKE 'crossing.%' AND class NOT LIKE 'access.%'""")]
        objs += [g(w) for (w,) in rows(f"""SELECT {m()} FROM space.element WHERE type IN ('walkway', 'cycleway') AND level_min = 0
                                           AND coalesce(subtype, '') <> 'crossing'""")]
        o_tree = shapely.STRtree(objs) if objs else None
        for q in shapely.get_parts(thin):
            if (q.area > 0.5 and q.distance(edge_) > 0.3
                    and (o_tree is None or not any(objs[i].intersection(q.buffer(0.2)).length > 2.0 or (objs[i].geom_type == "Point" and q.buffer(0.2).contains(objs[i]))
                                                     for i in o_tree.query(q.buffer(0.2))))):
                gaps.append(q)
    owners = [(r["sub"], r["road_g"]) for r in runs] + [(j["id"], j["geom"]) for j in junctions]
    gaps_u = shapely.union_all([q for q in gaps if q.area >= 2.0]) if gaps else shapely.Polygon()     # (shared out below, as the realm)
    pts, lab = [], []
    for k, (_, G) in enumerate(owners):
        for q in shapely.get_parts(G):
            ring = q.exterior
            for i in range(max(int(ring.length // SAMPLE_M), 4)):
                pts.append(ring.interpolate(i * SAMPLE_M))
                lab.append(k)
    share = {}
    if pts and not realm.is_empty:
        cells = shapely.get_parts(shapely.voronoi_polygons(shapely.MultiPoint(pts), extend_to=realm.buffer(50)))
        ptree = shapely.STRtree(pts)
        by = {}
        for cell in cells:
            k = next((lab[i] for i in ptree.query(cell) if cell.contains(pts[i])), None)
            if k is not None:
                by.setdefault(k, []).append(cell)
        for k, cs in by.items():
            share[k] = poly(realm.intersection(shapely.union_all(cs)))
        # (a share's piece that does not touch its own roadway goes to the space it touches most: no space in two pieces, U2)
        for _ in range(3):
            moved = []
            for k in list(share):
                keep_ = []
                for q in shapely.get_parts(share[k]):
                    if q.boundary.intersection(owners[k][1].buffer(0.05)).length > 0.5 or q.area < 0.05:     # (along an edge, not a corner)
                        keep_.append(q)
                    else:
                        moved.append(q)
                share[k] = poly(shapely.union_all(keep_ or [shapely.Polygon()]))
            for q in moved:
                best, bl = None, 0.0
                for k, (_, G) in enumerate(owners):
                    U_ = shapely.union_all([G, share.get(k, shapely.Polygon())])
                    if U_.distance(q) < 0.05:
                        l_ = U_.boundary.intersection(q.boundary.buffer(0.05)).length
                        if l_ > bl:
                            best, bl = k, l_
                if best is not None:
                    share[best] = poly(shapely.union_all([share.get(best, shapely.Polygon()), q]))

    gap_ref = f"between two roadways, narrower than {GAP_M} m, no kerb, object or path mapped on it: one paved surface"

    gap_of = {}     # (each roadway's share of the strips between roadways: its carriageway parts, no pedestrian side there)
    if not gaps_u.is_empty:
        for k in list(share):
            gk = [q for q in shapely.get_parts(poly(share[k].intersection(gaps_u))) if q.area > 0.5]
            if gk:
                gap_of[k] = gk
                share[k] = poly(share[k].difference(shapely.union_all(gk)))     # (exactly the pieces taken: a buffer of gaps_u lost some)

    # ---- parts and marks
    units, parts, marks, subrows, junction_rows = [], [], [], [], []
    pid = {}

    def add(uid, typ, geom, **kw):
        geom = poly(geom)
        if geom.is_empty or geom.area < 0.05:
            return
        pid[uid] = pid.get(uid, 0) + 1
        parts.append(dict(unit_id=uid, part_id=f"{uid}#{pid[uid]}", type=typ, geom=geom, **kw))

    def mark(uid, typ, geom, src="urbanstyle", method="derived", ref=None):
        for q in shapely.get_parts(geom):
            if q.geom_type == "LineString" and q.length > 0.5:
                marks.append((uid, typ, q, src, method, ref))

    def axis_out(ln):       # (a subsection's axis stops at the junctions' edges)
        x_ = ln.difference(J_all) if not J_all.is_empty else ln
        ps_ = [q for q in shapely.get_parts(x_) if q.geom_type == "LineString"]
        return max(ps_, key=lambda q: q.length) if ps_ else ln

    def ped(uid, G, R):
        """The pedestrian side R of roadway G: furnishing, sidewalk, frontage; a piece that touches no block or the area's edge lies
        between roadways only: an island (a median of a divided road, a traffic island), not a sidewalk."""
        if R.is_empty:
            return
        isl = [q for q in shapely.get_parts(R) if q.distance(edge_) > 0.3 and q.area >= ISLAND_MIN_M2 and not q.buffer(-0.5).is_empty]
        if isl:
            add(uid, "island", shapely.union_all(isl), source="osm", method="derived",
                ref="between roadways only: a median or a traffic island (no block reaches it)")
            R = poly(R.difference(shapely.union_all(isl)))
            if R.is_empty:
                return
        f_ = poly(R.intersection(G.buffer(FURNISH_M)))
        s_ = poly(R.intersection(G.buffer(FURNISH_M + CLEAR_M)).difference(f_))
        rest = poly(R.difference(G.buffer(FURNISH_M + CLEAR_M)))
        pv = dict(source="urbanstyle", method="chosen", width_source="urbanstyle", width_method="chosen")
        add(uid, "furnishing", f_, width_m=FURNISH_M, ref=f"{FURNISH_M} m from the kerb", **pv)
        add(uid, "sidewalk", s_, width_m=CLEAR_M, ref=f"the clear path, {CLEAR_M} m", **pv)
        add(uid, "frontage", rest, ref="the rest to the block's edge", **pv)

    for k, r in enumerate(runs):
        G, ln, uid = r["road_g"], r["line"], r["sub"]
        R = share.get(k, shapely.Polygon())
        U = poly(shapely.union_all([G, R] + gap_of.get(k, [])))
        units.append((uid, "subsection", r["sid"], U))
        for q in gap_of.get(k, []):
            add(uid, "carriageway", q, source="osm", method="derived", ref=gap_ref)
        tg = tags.get(r["oid"], {})
        common = dict(road=r["name"], road_class=r["cl"], road_lanes=str(r["f"] + r["b"]), oneway=r["ow"])
        lsrc = r["lsrc"]
        lane_ref = f"w{r['oid']} lanes={tg.get('lanes', '')}" if lsrc[0] == "osm" else f"w{r['oid']} has no lanes tag: one each way (chosen)"
        if r["oid"] in bridge_ways:     # (the bridge model draws its lanes)
            add(uid, "bridge deck", G, width_m=round(r["kl"] - r["kr"], 2), source="osm", method="mapped",
                ref=f"w{r['oid']} bridge=yes: drawn by the bridge model", **common)
            ped(uid, G, R)
            subrows.append((uid, r["sid"], r["cl"], round(r["kl"] - r["kr"], 2), r["ow"], round(ln.length, 1), None, None, "section end", axis_out(ln)))
            continue
        t = -r["W"] / 2
        for i in range(r["f"] + r["b"]):        # right to left: forward lanes, then backward
            fwd = i < r["f"]
            add(uid, "lane", band(ln, t, t + r["lw"]).intersection(G), direction="forward" if fwd else "backward",
                lane=(r["f"] - i) if fwd else (i - r["f"] + 1), width_m=round(r["lw"], 2), width_source=r["wsrc"][0], width_method=r["wsrc"][1],
                source=lsrc[0], method=lsrc[1], ref=lane_ref, position_source="osm", position_method="mapped",
                position_ref=f"w{r['oid']}: the lanes' middle on its OSM line", **common)
            if i > 0:
                mark(uid, "centre line" if i == r["f"] else "lane line", ln.offset_curve(t).intersection(G.buffer(0.01)), lsrc[0], lsrc[1], lane_ref)
            t += r["lw"]
        for sg in (1, -1):          # parking and bike lanes, only from OSM's tags
            t0 = r["W"] / 2 if sg > 0 else -r["W"] / 2
            for typ, w, pv in sorted(r["ex"][sg], key=lambda e: e[0] != "cycle lane"):
                t1 = t0 + sg * w
                add(uid, typ, band(ln, min(t0, t1), max(t0, t1)).intersection(G), width_m=w, width_source="urbanstyle", width_method="chosen",
                    source=pv[0], method=pv[1], ref=pv[2], **common)
                t0 = t1
        mark(uid, "kerb", G.boundary.intersection(R.buffer(0.05)) if not R.is_empty else shapely.LineString(), "urbanstyle", "derived",
             f"the edge of w{r['oid']}'s lanes")
        for at_end in (True, False):    # a stop line across the lanes that enter a junction, STOP_BACK_M before it
            q_ = shapely.Point(ln.coords[-1] if at_end else ln.coords[0])
            if J_all.is_empty or J_all.distance(q_) > 0.5:
                continue
            # (only the junction at this end: the junction at the other end moved the stop line back ~10 m, Kaveh 2026-10-15)
            jp_ = shapely.union_all([q for q in shapely.get_parts(J_all) if q.distance(q_) <= 0.5])
            pc_ = [p for p in shapely.get_parts(ln.intersection(jp_)) if p.geom_type == "LineString" and p.distance(q_) < 0.5]
            inside = sum(p.length for p in pc_)
            s_j = (ln.length - inside) if at_end else inside       # (where the line leaves the junction)
            s_ = max(min(s_j - STOP_BACK_M if at_end else s_j + STOP_BACK_M, ln.length), 0.0)
            lo_, hi_ = (-r["W"] / 2, -r["W"] / 2 + r["f"] * r["lw"]) if at_end else (-r["W"] / 2 + r["f"] * r["lw"], r["W"] / 2)
            if hi_ - lo_ < 0.5:
                continue
            p_ = ln.interpolate(s_)
            a_, b_ = ln.interpolate(max(s_ - 1, 0)), ln.interpolate(min(s_ + 1, ln.length))
            h_ = math.hypot(b_.x - a_.x, b_.y - a_.y) or 1
            nx, ny = -(b_.y - a_.y) / h_, (b_.x - a_.x) / h_
            mark(uid, "stop line", shapely.LineString([(p_.x + nx * lo_, p_.y + ny * lo_), (p_.x + nx * hi_, p_.y + ny * hi_)]).intersection(G.buffer(0.01)),
                 "urbanstyle", "derived", "where the lanes enter the junction")
        ped(uid, G, R)
        subrows.append((uid, r["sid"], r["cl"], round(r["kl"] - r["kr"], 2), r["ow"], round(ln.length, 1), None, None, "section end", axis_out(ln)))
    for j in junctions:
        k = len(runs) + junctions.index(j)
        R = share.get(k, shapely.Polygon())
        units.append((j["id"], "intersection", None, poly(shapely.union_all([j["geom"], R] + gap_of.get(k, [])))))
        for q in gap_of.get(k, []):
            add(j["id"], "carriageway", q, source="osm", method="derived", ref=gap_ref)
        add(j["id"], "junction area", j["geom"], source="osm", method="derived",
            ref="the junction of " + ", ".join(f"n{i}" for i in j["nodes"]) if j["nodes"] else "the arms' carriageways where they meet")
        mark(j["id"], "kerb", j["geom"].boundary.intersection(R.buffer(0.05)) if not R.is_empty else shapely.LineString())
        ped(j["id"], j["geom"], R)
        junction_rows += [(j["id"], i, 0, j["id"]) for i in j["nodes"]]

    # zebras: OSM's marked crossings over the roadway, bars ZEBRA_BAR_M wide every ZEBRA_BAR_M + ZEBRA_GAP_M, as long as the crosswalk
    unmarked = {o for (o,) in rows("SELECT osm_id FROM osm.raw.ways WHERE tags['crossing'] = 'unmarked' OR tags['crossing:markings'] = 'no'")}
    uu = [(u[0], u[3]) for u in units]
    utree = shapely.STRtree([x for _, x in uu]) if uu else None
    for oid, x in [(o, g(w)) for o, w in rows(f"""SELECT osm_id, {m()} FROM space.element WHERE type IN ('walkway', 'cycleway') AND level_min = 0
                                                AND subtype = 'crossing'""")]:
        if oid in unmarked:
            continue
        for seg in shapely.get_parts(x.intersection(roadway)):
            if seg.geom_type != "LineString" or seg.length < 1.0:
                continue
            (x0, y0), (x1, y1) = seg.coords[0], seg.coords[-1]
            h_ = math.hypot(x1 - x0, y1 - y0) or 1
            ux, uy = (x1 - x0) / h_, (y1 - y0) / h_
            d = ZEBRA_BAR_M / 2
            while d < seg.length:
                c_ = seg.interpolate(d)
                bar = shapely.LineString([(c_.x - uy * CROSSWALK_M / 2, c_.y + ux * CROSSWALK_M / 2), (c_.x + uy * CROSSWALK_M / 2, c_.y - ux * CROSSWALK_M / 2)])
                k_ = next((k for k in (utree.query(c_) if utree is not None else []) if uu[k][1].contains(c_)), None)
                if k_ is not None:
                    mark(uu[k_][0], "zebra", bar.intersection(roadway), "osm", "mapped", f"w{oid}")
                d += ZEBRA_BAR_M + ZEBRA_GAP_M

    # ---- write (the level-0 rows of division.py's tables, each table with division's columns and types)
    for t, cols in SCHEMA.items():
        have = {c for (c,) in rows(f"SELECT column_name FROM information_schema.columns WHERE table_schema = 'space' AND table_name = '{t}'")}
        q_ = lambda c: f'"{c}"'
        if have:
            con.execute(f"CREATE OR REPLACE TABLE space.{t} AS SELECT " + ", ".join(
                (f"CAST({q_(c)} AS {ty}) AS {q_(c)}" if c in have else f"CAST(NULL AS {ty}) AS {q_(c)}") for c, ty in cols.items()) + f" FROM space.{t}")
        else:
            con.execute(f"CREATE TABLE space.{t} (" + ", ".join(f"{q_(c)} {ty}" for c, ty in cols.items()) + ")")
    for t in ("part", "mark", "width", "turn", "approach"):
        try:
            con.execute(f"DELETE FROM space.{t} WHERE level = 0")
        except duckdb.Error:
            pass
    for t in ("cut", "junction", "subsection"):
        try:
            con.execute(f"DELETE FROM space.{t} WHERE level = 0")
        except duckdb.Error:
            pass
    con.execute("DELETE FROM space.unit WHERE level = 0")
    # a level-1 way this step puts on the ground (nothing passes under it) has no space at level 1 too (spaces.py made one: West
    # Broadway's deck drawn in the air over its own street, s0-w473723218/1; Kaveh 2026-10-15)
    eids = [str(e) for (e,) in rows("SELECT DISTINCT edge_id FROM osm.driving.edges WHERE osm_id IN (SELECT unnest(?::BIGINT[]))",
                                    [sorted(l1_ground)])] if l1_ground else []
    if eids:
        for t in ("part", "mark", "width", "turn", "approach", "unit"):
            try:
                con.execute(f"DELETE FROM space.{t} WHERE level >= 1 AND regexp_extract(unit_id, '^s1-(-?[0-9]+)/', 1) IN (SELECT unnest(?::VARCHAR[]))", [eids])
            except duckdb.Error:
                pass
        try:
            con.execute("DELETE FROM space.subsection WHERE level >= 1 AND regexp_extract(subsection_id, '^s1-(-?[0-9]+)/', 1) IN (SELECT unnest(?::VARCHAR[]))", [eids])
        except duckdb.Error:
            pass
    from .parts import LINE
    clean = lambda x: poly(shapely.make_valid(shapely.set_precision(x, 0.01)))      # (on a 1 cm grid, valid: as division.py's)
    units = [(u, k, s_, clean(x)) for u, k, s_, x in units]
    units = [u for u in units if not u[3].is_empty and u[3].area > 0.5]
    for p_ in parts:
        p_["geom"] = clean(p_["geom"])
    parts = [p_ for p_ in parts if not p_["geom"].is_empty and p_["geom"].area > 0.05]
    # each space in one piece: its largest; every other piece (split off by the snapping, or a corner crumb) goes to the space it shares the
    # longest edge with, its parts too; a crumb under 5 m2 that touches no other space is dropped (U2)
    U_ = {u: [k, s_, x] for u, k, s_, x in units}
    ut_ = shapely.STRtree([U_[u][2] for u in U_]); ul_ = list(U_)
    by_u = {}
    for p_ in parts:
        by_u.setdefault(p_["unit_id"], []).append(p_)
    for u in ul_:
        ps_ = sorted(shapely.get_parts(U_[u][2]), key=lambda q: -q.area)
        if len(ps_) < 2:
            continue
        U_[u][2] = ps_[0]
        for q in ps_[1:]:
            best, bl = None, 0.05
            for k in ut_.query(q.buffer(0.1)):
                v = ul_[k]
                if v == u:
                    continue
                l_ = U_[v][2].boundary.intersection(q.boundary.buffer(0.05)).length
                if l_ > bl:
                    best, bl = v, l_
            if best is None and q.area < 5.0:
                for p_ in by_u.get(u, []):
                    p_["geom"] = clean(p_["geom"].difference(q))
                continue
            if best is None:
                U_[u][2] = shapely.union_all([U_[u][2], q])
                continue
            U_[best][2] = clean(shapely.union_all([U_[best][2], q]))
            for p_ in by_u.get(u, []):
                inq = clean(p_["geom"].intersection(q))
                if not inq.is_empty and inq.area > 0.05:
                    p_["geom"] = clean(p_["geom"].difference(q))
                    pid[best] = pid.get(best, 0) + 1
                    np_ = dict(p_, unit_id=best, part_id=f"{best}#{pid[best]}", geom=inq)
                    parts.append(np_)
                    by_u.setdefault(best, []).append(np_)
    units = [(u, v[0], v[1], v[2]) for u, v in U_.items()]
    # parts of one space with the same type, source and lane that touch are one part (the pedestrian side and the strips between
    # roadways are shared out in SAMPLE_M cells: one part per cell drew "bricks", i0-414553083; Kaveh 2026-10-15)
    groups_ = {}
    for p_ in parts:
        groups_.setdefault((p_["unit_id"], p_["type"], p_.get("ref"), p_.get("direction"), p_.get("lane")), []).append(p_)
    parts = []
    for (u, *_), ps_ in groups_.items():
        if len(ps_) == 1:
            parts += ps_
            continue
        one = clean(shapely.union_all([p_["geom"] for p_ in ps_]).buffer(0.02).buffer(-0.02))     # (mitre joins lost a whole strip)
        if one.is_empty or one.area < 0.9 * sum(p_["geom"].area for p_ in ps_):
            parts += ps_        # (the closing failed: keep the pieces as they are)
            continue
        for i, q in enumerate(shapely.get_parts(one)):
            if i < len(ps_):
                parts.append(dict(ps_[i], geom=q))
            else:
                pid[u] = pid.get(u, 0) + 1
                parts.append(dict(ps_[0], part_id=f"{u}#{pid[u]}", geom=q))
    parts = [p_ for p_ in parts if not p_["geom"].is_empty and p_["geom"].area > 0.05]
    urows = [(u, k, s, COLORS[k], shapely.to_wkb(x)) for u, k, s, x in units if not x.is_empty]
    if urows:       # (a map with no street at level 0: nothing to write)
        con.executemany(f"INSERT INTO space.unit (unit_id, kind, section_id, level, color, geometry) VALUES (?, ?, ?, 0, ?, {to_ll})", urows)
    if junction_rows:
        con.executemany("INSERT INTO space.junction (intersection_id, node_id, level, cluster_id) VALUES (?, ?, ?, ?)", junction_rows)
    if subrows:
        con.executemany(f"""INSERT INTO space.subsection (subsection_id, section_id, level, class, width_m, oneway, length_m, "left", "right",
                            starts_at, color, geometry) VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?, '#e6194b', {to_ll})""",
                        [(a, b, c, d, e, f, h, i, j, shapely.to_wkb(x)) for a, b, c, d, e, f, h, i, j, x in subrows])
    if parts:
        con.executemany(f"""INSERT INTO space.part (unit_id, part_id, level, type, arm, direction, lane, lane_id, width_m, width_source, width_method,
                            length_m, source, method, ref, position_source, position_method, position_ref, road, road_class, road_lanes, oneway, rule,
                            geometry) VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {to_ll})""",
                        [(p["unit_id"], p["part_id"], p["type"], p.get("arm"), p.get("direction"), p.get("lane"), p.get("lane_id"), p.get("width_m"),
                          p.get("width_source") or "urbanstyle", p.get("width_method"), round(p["geom"].length / 2, 1), p.get("source") or "urbanstyle",
                          p.get("method") or "derived", p.get("ref"), p.get("position_source"), p.get("position_method"), p.get("position_ref"),
                          p.get("road"), p.get("road_class"), p.get("road_lanes"), p.get("oneway"), p.get("rule"), shapely.to_wkb(p["geom"])) for p in parts])
    if marks:
        con.executemany(f"""INSERT INTO space.mark (unit_id, level, type, length_m, width_m, width_source, width_method, source, method, ref, geometry)
                            VALUES (?, 0, ?, ?, ?, 'urbanstyle', 'chosen', ?, ?, ?, {to_ll})""",
                        [(u, t, round(x.length, 1), LINE.get(t), s_, me, rf, shapely.to_wkb(x)) for u, t, x, s_, me, rf in marks])
    return dict(sections=len(runs), intersections=len(junctions), parts=len(parts), marks=len(marks))
