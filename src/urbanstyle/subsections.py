"""space.subsection: each section's roads divided into subsections, as lines (step 1 of the network-first partition: divide the
roads, then make a space for each piece).

A section (the stretch of one street between two junctions) is split where
- the cross-section changes: road class, width (lanes) or one-way differs from one road edge to the next;
- the building frontage changes, on either side: buildings start or stop, or the facade steps back or forward by more than
  STEP_BACK_M. Frontage is read from the building line (buildings closed by BLINE_M, so a gap narrower than twice that is not a
  change), by a ray every STEP_M metres out to the reach. A change counts only when it lasts MIN_M metres, and no subsection is
  shorter than that.

Two close parallel runs are one corridor: a run that lies alongside a longer one (within PAIR_M, directions within PAIR_DEG, for
PAIR_SHARE of its own length, no building between) follows it: it gets no subsections of its own, and the longer run's subsections
reach across it (`left_extra` / `right_extra`: how much farther the space reaches on that side; `with_sections`: the followers'
sections). The halves of a dual carriageway, or a road and the service lane beside it, become one space.

Ids: <section id>/<k>, k = 1, 2, ... along each run of the section's roads.
"""
import math

STEP_M = 3.0
DIVIDED_LINK_M = 20.0   # a link this short between the two carriageways of a divided road joins their junctions into one
SPLIT_M = 12.0     # a node of a roundabout's group farther than this from its ring is a junction of its own (an entry's splitter island is nearer)
MIN_M = 12.0
STEP_BACK_M = 3.0
BLINE_M = 3.0
ROAD_KEEP_M = 1.5    # the building line stays this far off a road's line: a narrow street between facades is not closed
PAIR_M = 15.0
PAIR_DEG = 25.0
PAIR_SHARE = 0.7
COLORS = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42d4f4", "#f032e6", "#9a6324"]


def _reach(width_m):
    return min(1.5 * width_m + 8, 25.0)


def _frontage(line, width_m, bline, tree, extra=(0.0, 0.0)):
    """Per sample along `line`: (distance to the building line on the left, on the right), None where there is none within reach
    (plus `extra` on that side, where a following run lies)."""
    import shapely
    n = max(int(line.length // STEP_M), 1)
    out = []
    for i in range(n + 1):
        d = min(i * STEP_M, line.length)
        p, q = line.interpolate(max(d - 1.5, 0)), line.interpolate(min(d + 1.5, line.length))
        tx, ty = q.x - p.x, q.y - p.y
        h = math.hypot(tx, ty) or 1.0
        nx, ny = -ty / h, tx / h
        c = line.interpolate(d)
        pair = []
        for s, more in ((1, extra[0]), (-1, extra[1])):
            r = _reach(width_m) + more
            ray = shapely.LineString([(c.x, c.y), (c.x + s * nx * r, c.y + s * ny * r)])
            hits = [bline[k] for k in tree.query(ray, predicate="intersects")]
            pair.append(min((c.distance(ray.intersection(b)) for b in hits), default=None))
        out.append((d, pair[0], pair[1]))
    return out


def _breaks(samples, length):
    """Positions (m along the line) where the frontage changes on either side."""
    k = max(int(MIN_M // STEP_M), 1)
    cuts = []
    for side in (1, 2):
        cat = [s[side] is not None for s in samples]
        # runs shorter than MIN_M take the category of the run before them
        i = 0
        while i < len(cat):
            j = i
            while j < len(cat) and cat[j] == cat[i]:
                j += 1
            if j - i < k and i > 0:
                for m in range(i, j):
                    cat[m] = cat[i - 1]
            i = j
        ref = None
        for i in range(1, len(samples)):
            if cat[i] != cat[i - 1]:
                cuts.append(samples[i][0])
                ref = None
                continue
            if not cat[i]:
                continue
            win = [samples[m][side] for m in range(i, min(i + k, len(samples))) if samples[m][side] is not None]
            if ref is None:
                ref = sorted(win)[len(win) // 2] if win else None
                continue
            now = sorted(win)[len(win) // 2] if win else ref
            if abs(now - ref) > STEP_BACK_M:      # a step back or forward that lasts MIN_M
                cuts.append(samples[i][0])
                ref = now
    cuts = sorted(c for c in cuts if MIN_M <= c <= length - MIN_M)
    kept = []
    for c in cuts:
        if not kept or c - kept[-1] >= MIN_M:
            kept.append(c)
    return kept


def _dir(line, t):
    """Unit direction of `line` at distance t along it."""
    p, q = line.interpolate(max(t - 1.5, 0)), line.interpolate(min(t + 1.5, line.length))
    h = math.hypot(q.x - p.x, q.y - p.y) or 1.0
    return (q.x - p.x) / h, (q.y - p.y) / h


def _followers(runs, bparts, btree):
    """{index of a run: (index of the longer run it follows, side 1 left / -1 right of that run, extra reach on that side)}.
    A run that is followed never follows another one itself: no chains."""
    import shapely
    lines = [r[5] for r in runs]
    tree = shapely.STRtree(lines)
    cos_min = math.cos(math.radians(PAIR_DEG))
    out, leads = {}, set()
    for b in sorted(range(len(runs)), key=lambda i: lines[i].length):          # the shortest look for a longer run to follow
        if b in leads:
            continue
        best = None
        for a in tree.query(lines[b].buffer(PAIR_M)):
            if a == b or a in out or lines[a].length < lines[b].length:
                continue
            n = max(int(lines[b].length // 5), 1)
            sides, ds = [], []
            for i in range(n + 1):
                t = lines[b].length * i / n
                q = lines[b].interpolate(t)
                ta = lines[a].project(q)
                pa = lines[a].interpolate(ta)
                (bx, by), (ax, ay) = _dir(lines[b], t), _dir(lines[a], ta)
                d = q.distance(pa)
                if d > PAIR_M or abs(bx * ax + by * ay) < cos_min:
                    continue
                gap = shapely.LineString([pa, q])
                if btree is not None and d > 0.5 and any(bparts[k].intersects(gap) for k in btree.query(gap)):
                    continue        # a building between them: two streets, not one corridor
                sides.append(1 if ax * (q.y - pa.y) - ay * (q.x - pa.x) > 0 else -1)
                ds.append(d)
            share = len(ds) / (n + 1)
            if share >= PAIR_SHARE and (best is None or share > best[0]):
                best = (share, a, 1 if sum(sides) >= 0 else -1, sorted(ds)[len(ds) // 2] + runs[b][3] / 2)
        if best:
            out[b] = best[1:]
            leads.add(best[1])
    return out


def building_line(blds, roads):
    """The building line of one level, as polygons: the buildings closed by BLINE_M (a gap narrower than twice that is no way through),
    except along a road: a street narrower than that between two facades stays open, ROAD_KEEP_M either side of its line (the buildings
    themselves always stay)."""
    import shapely
    u = shapely.union_all(blds) if len(blds) else shapely.Polygon()
    if u.is_empty:
        return []
    closed = u.buffer(BLINE_M).buffer(-BLINE_M)
    if len(roads):
        closed = shapely.union_all([closed.difference(shapely.union_all([r.buffer(ROAD_KEEP_M, cap_style="flat") for r in roads])), u])
    return [p for p in shapely.get_parts(shapely.make_valid(closed)) if p.geom_type == "Polygon" and not p.is_empty]


def junctions(con, epsg):
    """space.junction (intersection_id, node_id, level, cluster_id): which junction each node belongs to in the network-first spaces.
    The container step groups close nodes into one intersection (space.arm, cluster_id). Two changes:
    - a group holding a roundabout's ring is cut back to the ring and what lies within SPLIT_M of it (an entry's splitter island):
      farther nodes are junctions of their own (each connected group of them, id i<level>-<its smallest node>), and the roads between
      them and the ring are roads again;
    - the two junctions where a road crosses the two carriageways of a divided road (each on a one-way carriageway, the two running
      opposite ways, joined by a link shorter than DIVIDED_LINK_M) are one junction (not a roundabout's)."""
    import math
    import shapely
    to_m = lambda col: f"ST_AsWKB(ST_Transform({col}, 'EPSG:4326', '{epsg}', always_xy := true))"
    members = con.execute("SELECT DISTINCT intersection_id, node_id, level FROM space.arm").fetchall()
    out = {(iid, n, lv): iid for iid, n, lv in members}
    try:
        ring_osm = {r[0] for r in con.execute("SELECT osm_id FROM osm.raw.ways WHERE tags['junction'] IN ('roundabout', 'circular')").fetchall()}
    except Exception:
        ring_osm = set()
    edges = [(sid, s_, d, osm, bool(ow), lv, shapely.from_wkb(bytes(g)), shapely.from_wkb(bytes(ps)), shapely.from_wkb(bytes(pd_)))
             for sid, s_, d, osm, ow, lv, g, ps, pd_ in con.execute(f"""SELECT source_id, src, dst, osm_id, coalesce(oneway, false), level_min, {to_m('geometry')},
                 {to_m('ST_StartPoint(geometry)')}, {to_m('ST_EndPoint(geometry)')} FROM space.element WHERE type = 'road' AND src IS NOT NULL AND dst IS NOT NULL""").fetchall()]
    xy, degree, ring_g, at = {}, {}, {}, {}
    for e in edges:
        _, s_, d, osm, _, _, g, ps, pd_ = e
        xy[s_], xy[d] = ps, pd_
        for n in (s_, d):
            degree[n] = degree.get(n, 0) + 1
            at.setdefault(n, []).append(e)
            if osm in ring_osm:
                ring_g.setdefault(n, []).append(g)
    clusters = {}
    for iid, n, lv in members:
        clusters.setdefault((iid, lv), set()).add(n)
    rings = set()       # the junctions holding a roundabout's ring
    for (iid, lv), nodes in clusters.items():
        on_ring = {n for n in nodes if n in ring_g}
        if not on_ring:
            continue
        rings.add(iid)
        ring = shapely.union_all([g for n in on_ring for g in ring_g[n]])
        off = {n for n in nodes - on_ring if n in xy and xy[n].distance(ring) > SPLIT_M}
        comp = {n: n for n in off}          # connected groups of the far nodes, by the roads between them
        find = lambda n: n if comp[n] == n else find(comp[n])
        for _, s_, d, *_ in edges:
            if s_ in off and d in off:
                comp[find(s_)] = find(d)
        groups = {}
        for n in off:
            groups.setdefault(find(n), []).append(n)
        for grp in groups.values():
            if max(degree.get(n, 0) for n in grp) >= 3:     # a real junction (a bend in a road stays with the roundabout)
                for n in grp:
                    out[(iid, n, lv)] = f"i{lv}-{min(grp)}"
    # a divided road's crossing: the junctions on its two carriageways are one
    jof = {(n, lv): new for (iid, n, lv), new in out.items()}

    def travel(e, n):       # a one-way road's direction of travel near node n
        g = e[6]
        t = 0 if n == e[1] else g.length
        a, b = g.interpolate(max(t - 4, 0)), g.interpolate(min(t + 4, g.length))
        h = math.hypot(b.x - a.x, b.y - a.y) or 1.0
        return (b.x - a.x) / h, (b.y - a.y) / h
    merged = {}
    find = lambda j: j if merged.get(j, j) == j else find(merged[j])
    for e in edges:
        sid, s_, d, osm, _, lv, g, *_ = e
        A, B = jof.get((s_, lv)), jof.get((d, lv))
        if not A or not B or A == B or osm in ring_osm or g.length >= DIVIDED_LINK_M or A in rings or B in rings:
            continue
        if any(ra is not e and rb is not e and ra[4] and rb[4] and ra[5] == lv == rb[5]
               and sum(p * q for p, q in zip(travel(ra, s_), travel(rb, d))) < -0.8 for ra in at[s_] for rb in at[d]):
            a, b = sorted((find(A), find(B)))
            if a != b:
                merged[b] = a
    out = {k: find(v) for k, v in out.items()}
    import pandas as pd
    df = pd.DataFrame([(new, n, lv, iid) for (iid, n, lv), new in out.items()], columns=["intersection_id", "node_id", "level", "cluster_id"])
    con.execute("""CREATE OR REPLACE TABLE space.junction AS SELECT intersection_id::VARCHAR AS intersection_id, node_id::BIGINT AS node_id,
                   level::INT AS level, cluster_id::VARCHAR AS cluster_id FROM df""")


def build(con, epsg):
    import pandas as pd
    import shapely
    from shapely.ops import substring
    junctions(con, epsg)
    to_m = f"ST_AsWKB(ST_Transform(geometry, 'EPSG:4326', '{epsg}', always_xy := true))"
    # a road keeps its own section even where the container step handed a short one to its intersection (the arm still names the section)
    roads = con.execute(f"""SELECT coalesce(CASE WHEN e.container_id LIKE 's%' THEN e.container_id END, a.section_id) AS sid, e.level_min AS level,
                                   e.class, e.width_m, e.oneway, {to_m.replace('geometry', 'e.geometry')} AS g, e.osm_id
                            FROM space.element e LEFT JOIN (SELECT edge_id, min(section_id) AS section_id FROM space.arm GROUP BY 1) a ON a.edge_id = e.source_id
                            WHERE e.type = 'road' AND ST_Length(e.geometry) > 0
                              -- a road between two nodes of one junction (a roundabout ring, a short link) is part of the intersection
                              AND NOT EXISTS (SELECT 1 FROM space.junction x JOIN space.junction y USING (intersection_id) WHERE x.node_id = e.src AND y.node_id = e.dst)""").fetchall()
    roads = [r for r in roads if r[0] is not None]
    try:    # a roundabout's ring belongs to the roundabout, never to a subsection
        ring_osm = {r[0] for r in con.execute("SELECT osm_id FROM osm.raw.ways WHERE tags['junction'] IN ('roundabout', 'circular')").fetchall()}
        roads = [r for r in roads if r[6] not in ring_osm]
    except Exception:
        pass
    blds = con.execute(f"SELECT l, {to_m} FROM space.element, generate_series(level_min, level_max) t(l) WHERE type = 'building'").fetchall()
    blines = {}
    for lv in {r[1] for r in roads}:
        parts = building_line([shapely.from_wkb(bytes(b[1])) for b in blds if b[0] == lv], [shapely.from_wkb(bytes(r[5])) for r in roads if r[1] == lv])
        blines[lv] = (parts, shapely.STRtree(parts) if parts else None)

    rows = []
    groups = {}
    for cid, lv, cls, w, ow, g, _osm in roads:
        groups.setdefault((cid, lv), {}).setdefault((cls, round(w or 0, 2), bool(ow)), []).append(shapely.from_wkb(bytes(g)))
    allruns = []      # (section, level, class, width, oneway, line)
    for (cid, lv), keys in groups.items():
        for (cls, w, ow), lines in keys.items():
            merged = shapely.line_merge(shapely.MultiLineString(lines)) if len(lines) > 1 else lines[0]
            allruns += [(cid, lv, cls, w, ow, ln) for ln in shapely.get_parts(merged)]
    follows = {}
    for lv in {r[1] for r in allruns}:
        idx = [i for i, r in enumerate(allruns) if r[1] == lv]
        parts, tree = blines.get(lv, ([], None))
        for b, (a, side, extra) in _followers([allruns[i] for i in idx], parts, tree).items():
            follows[idx[b]] = (idx[a], side, extra)
    extra_of, with_of = {}, {}
    for b, (a, side, extra) in follows.items():
        e = extra_of.setdefault(a, [0.0, 0.0])
        e[0 if side == 1 else 1] = max(e[0 if side == 1 else 1], extra)
        with_of.setdefault(a, set()).add(allruns[b][0])
    by_sec = {}
    for i, r in enumerate(allruns):
        if i not in follows:
            by_sec.setdefault((r[0], r[1]), []).append(i)
    for (cid, lv), idxs in by_sec.items():
        k = 0
        runs = [allruns[i][2:] + (i,) for i in idxs]
        ends_of = lambda ln: [shapely.Point(ln.coords[0]), shapely.Point(ln.coords[-1])]
        for cls, w, ow, ln, ri in sorted(runs, key=lambda r: -r[3].length):
            extra = tuple(extra_of.get(ri, (0.0, 0.0)))
            withs = ",".join(sorted(with_of.get(ri, set()) - {cid}))
            # a run that starts where another run of this section ends starts at a cross-section change, else at a section end
            start_kind = "cross-section" if any(ends_of(ln)[0].distance(p) < 0.5 for r in runs if r[3] is not ln for p in ends_of(r[3])) else "section end"
            parts, tree = blines.get(lv, ([], None))
            samples = _frontage(ln, w, parts, tree, extra) if tree is not None else [(0.0, None, None), (ln.length, None, None)]
            cuts = _breaks(samples, ln.length)
            ends = [0.0] + cuts + [ln.length]
            for a, b in zip(ends, ends[1:]):
                k += 1
                piece = [s for s in samples if a <= s[0] <= b]
                dist = lambda m: (lambda v: sorted(v)[len(v) // 2] if v else None)([s[m] for s in piece if s[m] is not None]
                                                                                  if sum(s[m] is not None for s in piece) * 2 >= len(piece) else [])
                side = lambda m: "open" if dist(m) is None else f"building {dist(m):.1f} m"
                rows.append((f"{cid}/{k}", cid, lv, cls, w, ow, round(b - a, 1), side(1), side(2), dist(1), dist(2), extra[0], extra[1], withs,
                             start_kind if a == 0 else "frontage",
                             COLORS[(k - 1) % len(COLORS)], shapely.to_wkb(substring(ln, a, b))))
    df = pd.DataFrame(rows, columns=["subsection_id", "section_id", "level", "class", "width_m", "oneway", "length_m", "left", "right",
                                     "left_m", "right_m", "left_extra", "right_extra", "with_sections", "starts_at", "color", "wkb"])
    con.execute(f"""CREATE OR REPLACE TABLE space.subsection AS
        SELECT subsection_id, section_id, level::INT AS level, class, width_m, oneway, length_m, "left", "right", left_m::DOUBLE AS left_m,
               right_m::DOUBLE AS right_m, left_extra::DOUBLE AS left_extra, right_extra::DOUBLE AS right_extra, with_sections, starts_at, color,
               ST_Transform(ST_GeomFromWKB(wkb::BLOB), '{epsg}', 'EPSG:4326', always_xy := true) AS geometry FROM df""")
