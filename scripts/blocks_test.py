"""Blocks first, the test (docs/design/blocks.md): blocks from the roads, then the street divided between neighbouring blocks.

    python3 scripts/blocks_test.py CITY SPACE OSM OUT.html [DEBUG.png]

CITY    a folder with a city's block-outlines.geojson and lanes.geojson, used only to cross-check (never as input); Vancouver's from
        https://opendata.vancouver.ca/api/explore/v2.1/catalog/datasets/<name>/exports/geojson
            ?where=within_distance(geom, geom'POINT(-123.1386 49.2633)', 650m)
        (here: data/units/broadway-granville.city/)
SPACE   a built unit (urbanstyle unit / build): space.element (roads, walkways, buildings), space.parcel
OSM     the unit's duckOSM clip (main.boundary: the edge of the area)
OUT     the page: city blocks, our blocks, sections, intersections, the neighbours' middle lines (roadstyle; system python3)
DEBUG   optional: a plain picture of blocks, cuts and intersections, for checking by eye

Steps (each in the design note):
1. blocks         the faces of the level-0 public streets; each street side one edge parallel to the road, at the parcels' median line,
                  else the sidewalks + 1 m, else half the class's right-of-way; pulled in to the nearest building; sharp corners
2. neighbours     every street point belongs to its nearest block (its share); where two shares meet is their middle line; they face
                  each other where a line square to it meets one block on each side, each on a side running along it
3. sections       one per facing stretch, cut at two positions ARM_M inside its ends; at least as long as the street is wide
4. intersections  the rest of the street
Prints the numbers of the design note's tables. Not part of the pipeline yet (docs/plan.md, "Blocks first").
"""
import json
import statistics
import sys

import duckdb
import shapely
from shapely.ops import nearest_points

CITY, SPACE, OSM, OUT = sys.argv[1:5]
DEBUG = sys.argv[5] if len(sys.argv) > 5 else None
SIDEWALK_BACK_M = 1.0       # a sidewalk is mapped along its middle: the property line is about this far behind it
REACH_M = 25.0              # sidewalks looked for this far from a road
HALF_ROW = {"motorway": 18, "trunk": 16, "primary": 15, "secondary": 12, "tertiary": 10, "unclassified": 10, "residential": 10,
            "living_street": 8}  # half right-of-way by class where no sidewalk is mapped (66 ft = 20 m for a residential street)
MIN_BLOCK_M2, MIN_BLOCK_W_M = 400.0, 8.0
R_M = 35.0
ARM_M = 3.0         # urbanstyle's chosen: how far an intersection reaches into each arm past the block corner
c = duckdb.connect()
c.execute("LOAD spatial")
poly = lambda x: shapely.union_all([p for p in shapely.get_parts(x) if p.geom_type == "Polygon"] or [shapely.Polygon()])
to_m = lambda gj: shapely.from_wkb(c.execute("SELECT ST_AsWKB(ST_Transform(ST_GeomFromGeoJSON(?), 'EPSG:4326', 'EPSG:32610', always_xy := true))",
                                             [json.dumps(gj)]).fetchone()[0])
s = duckdb.connect(SPACE, read_only=True)
s.execute("LOAD spatial")
m = "ST_AsWKB(ST_Transform(geometry, 'EPSG:4326', 'EPSG:32610', always_xy := true))"
o = duckdb.connect(OSM, read_only=True)
o.execute("LOAD spatial")
box = shapely.from_wkb(o.execute("SELECT ST_AsWKB(ST_Transform(geometry, 'EPSG:4326', 'EPSG:32610', always_xy := true)) FROM main.boundary").fetchone()[0])

# a street bounds blocks by its class, whatever network it is in (a residential street closed to cars still has its right-of-way); a
# road on a deck bounds them when nothing at ground level passes under it (a temporary deck over works), not a real bridge
STREET = ("motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street", "pedestrian")
cand = [(cl, n, src, dst, shapely.from_wkb(w), lv) for cl, n, src, dst, w, lv in s.execute(f"""SELECT class, name, src, dst, {m}, level_min
          FROM space.element WHERE type IN ('road', 'walkway') AND replace(class, '_link', '') IN {STREET}
            AND level_min IN (0, 1)""").fetchall()]
ground_lines = [g for *_, g, lv in cand if lv == 0] + [shapely.from_wkb(w) for (w,) in s.execute(f"SELECT {m} FROM space.element WHERE type = 'rail' AND level_min = 0").fetchall()]
gtree = shapely.STRtree(ground_lines)
over_something = lambda g: any(ground_lines[k].crosses(g) for k in gtree.query(g))
roads = [(cl, n, src, dst, g) for cl, n, src, dst, g, lv in cand if lv == 0 or not over_something(g)]
side = [shapely.from_wkb(w) for (w,) in s.execute(f"SELECT {m} FROM space.element WHERE type = 'walkway' AND level_min = 0 AND coalesce(subtype, '') <> 'crossing'").fetchall()]
stree = shapely.STRtree(side)

# chains: the bounding roads merged between junctions, OSM's small wiggles taken out
SIMPLIFY_M = 1.0
rtr0 = shapely.STRtree([g for *_, g in roads])
chains = []
for g in shapely.get_parts(shapely.line_merge(shapely.union_all([g for *_, g in roads]))):
    if g.length < 1:
        continue
    k = max(rtr0.query(g), key=lambda k: roads[k][4].intersection(g.buffer(0.1)).length)
    chains.append(dict(geom=g.simplify(SIMPLIFY_M), cl=roads[k][0], name=roads[k][1], sides={}))
parcels = [shapely.from_wkb(w) for (w,) in s.execute(f"SELECT {m} FROM space.parcel").fetchall()]
PU = shapely.union_all(parcels) if parcels else None
bmeta = s.execute(f"SELECT {m}, source, osm_id, class, subtype, level_min, level_max FROM space.element WHERE type = 'building' AND level_min <= 0 AND level_max >= 0").fetchall()
blds_all = [shapely.make_valid(shapely.from_wkb(r[0])) for r in bmeta]
bldtree = shapely.STRtree(blds_all)


def side_width(ch, sg, f):
    """The block edge on one side (sg 1 = left, -1 = right) of a chain, inside face f: one distance for the whole side, so the edge runs
    parallel to the road. The parcels' line, else the sidewalks' back, else the class; never past the nearest building."""
    g, cl = ch["geom"], ch["cl"].replace("_link", "")
    cap = 1.5 * HALF_ROW.get(cl, 10)
    n = max(2, int(g.length // 5))
    par, sw, rays = [], [], 0
    for i in range(n):
        t = g.length * (i + .5) / n
        a, b = g.interpolate(max(t - 1, 0)), g.interpolate(min(t + 1, g.length))
        dx, dy = b.x - a.x, b.y - a.y
        h = (dx * dx + dy * dy) ** .5 or 1
        q = g.interpolate(t)
        ray = shapely.LineString([(q.x, q.y), (q.x - sg * dy / h * REACH_M, q.y + sg * dx / h * REACH_M)]).intersection(f)
        if ray.is_empty:
            continue
        rays += 1
        if PU is not None and not PU.buffer(-0.1).contains(q):
            x = ray.intersection(PU)
            if not x.is_empty and q.distance(x) <= cap:
                par.append(q.distance(x))
        hits = []
        for k in stree.query(ray):
            x = side[k].intersection(ray)
            if x.is_empty:
                continue
            hp = x if x.geom_type == "Point" else shapely.get_parts(x)[0]
            if hp.geom_type != "Point":
                hp = shapely.Point(hp.coords[0])
            tt = side[k].project(hp)
            a2, b2 = side[k].interpolate(max(tt - 1, 0)), side[k].interpolate(min(tt + 1, side[k].length))
            ex, ey = b2.x - a2.x, b2.y - a2.y
            he = (ex * ex + ey * ey) ** .5 or 1
            if abs(dx * ex + dy * ey) / (h * he) >= 0.82 and q.distance(hp) + SIDEWALK_BACK_M <= cap:
                hits.append(q.distance(hp))
        if hits:
            sw.append(min(hits) + SIDEWALK_BACK_M)
    if rays and len(par) >= max(2, rays / 2):
        d, src = statistics.median(par), "parcels"
    elif len(sw) >= 3:
        d, src = statistics.median(sw), "sidewalks"
    else:
        d, src = HALF_ROW.get(cl, 10), "class"
    zone = g.buffer(sg * REACH_M, single_sided=True).intersection(f)
    near = [(g.distance(blds_all[k].intersection(zone)), k) for k in bldtree.query(zone)
            if blds_all[k].intersects(zone) and not blds_all[k].intersects(g)]
    bd, bk = min(near, default=(1e9, None))
    if bd < d:
        bb = blds_all[bk]
        inpar = bb.intersection(PU).area / bb.area if PU is not None else 0
        return round(bd, 2), src + f" (pulled in to a building: {d:.1f} -> {bd:.1f} m; {bmeta[bk][1:5]}, {bb.area:.0f} m2, {inpar:.0%} on parcels)"
    return round(d, 2), src


def extend(g, e, ends):
    c = list(g.coords)
    def out(p, q):
        dx, dy = p[0] - q[0], p[1] - q[1]
        h = (dx * dx + dy * dy) ** .5 or 1
        return (p[0] + dx / h * e, p[1] + dy / h * e)
    if 0 in ends:
        c = [out(c[0], c[1])] + c
    if -1 in ends:
        c = c + [out(c[-1], c[-2])]
    return shapely.LineString(c)


ctree = shapely.STRtree([ch["geom"] for ch in chains])
lines = shapely.union_all([ch["geom"] for ch in chains] + [box.exterior])
faces = [f for f in shapely.get_parts(shapely.polygonize(list(shapely.get_parts(shapely.line_merge(lines))))) if f.within(box.buffer(0.1))]
blocks, binfo = [], []
for f in faces:
    fb = f.boundary.buffer(0.05)
    strips, info = [], []
    for j in ctree.query(f.buffer(0.1)):
        ch = chains[j]
        g = ch["geom"]
        on_edge = g.intersection(fb).length > 1
        inside = g.intersection(f.buffer(-0.1)).length > 1
        if not on_edge and not inside:
            continue
        # which side of the road the face is on: tested at the middle of the road's stretch along this face (a road that runs on past
        # the area's edge has its own middle outside the face)
        here = g.intersection(fb if on_edge else f)
        here = max((x for x in shapely.get_parts(here) if x.geom_type == "LineString"), key=lambda x: x.length, default=g)
        mid = g.interpolate(g.project(here.interpolate(0.5, normalized=True)))
        a, b = g.interpolate(max(g.project(mid) - 1, 0)), g.interpolate(min(g.project(mid) + 1, g.length))
        dx, dy = b.x - a.x, b.y - a.y
        h = (dx * dx + dy * dy) ** .5 or 1
        sgs = [1, -1] if inside else [sg for sg in (1, -1) if shapely.Point(mid.x - sg * dy / h * 0.5, mid.y + sg * dx / h * 0.5).within(f)]
        if not sgs:
            continue
        ends = [e for e, p in ((0, g.coords[0]), (-1, g.coords[-1])) if shapely.Point(p).distance(f.boundary) < 0.05]
        for sg in sgs:
            d, src = side_width(ch, sg, f)
            ch["sides"][sg] = (d, src)
            # the line runs on past a junction so two edges meet in a corner, as two parallel offsets do
            strips.append(extend(g, 2 * REACH_M, ends).buffer(sg * d, single_sided=True))
            info.append(f"{ch['name'] or ch['cl']} ({ch['cl']}): {d:.1f} m from {src}")
        for e in (0, -1):
            if e not in ends:
                strips.append(shapely.Point(g.coords[e]).buffer(max(ch["sides"][sg][0] for sg in sgs)))
    b = poly(f.difference(shapely.union_all(strips) if strips else shapely.Polygon(), grid_size=0.01))
    for p in shapely.get_parts(b):
        if p.area >= MIN_BLOCK_M2 and p.buffer(-MIN_BLOCK_W_M / 2).area > 0:
            blocks.append(p)
            binfo.append("; ".join(sorted(set(info))))
B = shapely.union_all(blocks)
street = poly(box.difference(B, grid_size=0.01))

# compare with the city's blocks
import datetime, os
fetched = datetime.date.fromtimestamp(os.path.getmtime(f"{CITY}/block-outlines.geojson")).isoformat()
cityinfo = []
for f in json.load(open(f"{CITY}/block-outlines.geojson"))["features"]:
    full = shapely.make_valid(to_m(f["geometry"]))
    pt = f["properties"]["geo_point_2d"]
    cid = f"cb-{pt['lon']:.5f}-{pt['lat']:.5f}"         # the city gives its blocks no id: their centre point is one
    for k, p in enumerate(shapely.get_parts(poly(full.intersection(box)))):
        if p.area > 50:
            cityinfo.append(dict(id=cid + (f"/{k + 1}" if k else ""), geom=p, full_m2=round(full.area), clipped=p.area < full.area - 1))
city = [x["geom"] for x in cityinfo]
lanes_ = [to_m(f["geometry"]) for f in json.load(open(f"{CITY}/lanes.geojson"))["features"] if f["geometry"]]
dtree = shapely.STRtree(blocks)
ious, d50, d90, matched = [], [], [], 0
match_of = {}
for cb in city:
    best = max(((cb.intersection(blocks[k]).area, k) for k in dtree.query(cb)), default=(0, None))
    if best[1] is None:
        ious.append(0.0)
        continue
    db = blocks[best[1]]
    iou = best[0] / cb.union(db).area
    ious.append(iou)
    matched += iou >= 0.8
    match_of[best[1]] = max(match_of.get(best[1], (None, 0)), (cityinfo[city.index(cb)]["id"], round(iou, 2)), key=lambda t: t[1])
    pts = [cb.exterior.interpolate(x, normalized=True) for x in [i / 40 for i in range(40)]]
    dd = sorted(p.distance(db.boundary) for p in pts)
    d50.append(dd[len(dd) // 2])
    d90.append(dd[int(.9 * len(dd))])
    cityinfo[city.index(cb)].update(match=best[1], iou=round(iou, 2), d50=round(dd[len(dd) // 2], 1), d90=round(dd[int(.9 * len(dd))], 1))
print(f"roads {len(roads)} chains {len(chains)}, street sides {sum(len(ch['sides']) for ch in chains)}: edge from parcels {sum(1 for ch in chains for d in ch['sides'].values() if d[1].startswith('parcels'))}, sidewalks {sum(1 for ch in chains for d in ch['sides'].values() if d[1].startswith('sidewalks'))}, class {sum(1 for ch in chains for d in ch['sides'].values() if d[1].startswith('class'))}; pulled in to a building {sum(1 for ch in chains for d in ch['sides'].values() if 'pulled' in d[1])}; "
      f"faces {len(faces)}; derived blocks {len(blocks)} ({B.area:,.0f} m2); city blocks {len(city)} ({shapely.union_all(city).area:,.0f} m2)")
print(f"city blocks matched by a derived one with overlap >= 0.8: {matched} of {len(city)}; overlap per block median {statistics.median(ious):.2f}, "
      f"lowest quarter {sorted(ious)[len(ious) // 4]:.2f}")
print(f"edge distance city -> derived, per block: median of medians {statistics.median(d50):.1f} m, median of 90th percentiles {statistics.median(d90):.1f} m")
print(f"derived block area outside city blocks {B.difference(shapely.union_all(city)).area:,.0f} m2; city block area missed {shapely.union_all(city).difference(B).area:,.0f} m2")

btree = shapely.STRtree(blocks)
# sections and intersections from the blocks' neighbours (the road lines only made the blocks):
#   region        every point of the street belongs to its nearest block; the outside of our area is one more "block" (-1)
#   neighbours    two blocks whose regions share a border; that border is the street's middle line between them
#   section       along the middle line, the stretch where a line square to it reaches block a on one side and block b on the other;
#                 cut at two positions, ARM_M inside each end (not at the area's edge)
#   intersection  the street left over: the open space between the corners and ARM_M into each arm
STEP, SAMPLE, RAY, FACE_DEG = 1.0, 0.5, 80.0, 30.0
import math
pts, owner, seen = [], [], set()
# where a street leaves the area, the area's edge crosses it: that opening is no neighbour, the two blocks' shares run on to the edge
OPENING_M = 40.0
openings = shapely.union_all([x for x in shapely.get_parts(shapely.line_merge(box.exterior.intersection(street.buffer(0.01))))
                              if x.length < OPENING_M]).buffer(0.05)
for k, ring in [(k, b.exterior) for k, b in enumerate(blocks)] + [(-1, box.exterior)]:
    n_ = max(4, int(ring.length / STEP))
    for i in range(n_):
        q = ring.interpolate(i * ring.length / n_)
        key = (round(q.x, 1), round(q.y, 1))
        if key in seen:                 # a block's edge on the area's edge: the block keeps the point
            continue
        if k == -1 and q.within(openings):
            continue
        seen.add(key)
        pts.append(q)
        owner.append(k)
cells = shapely.get_parts(shapely.voronoi_polygons(shapely.MultiPoint(pts), extend_to=box.buffer(200), ordered=True))
regions = {}
for c_, k in zip(cells, owner):
    regions.setdefault(k, []).append(c_)
regions = {k: shapely.union_all(v, grid_size=0.01).intersection(street) for k, v in regions.items()}
rtree5 = shapely.STRtree(list(regions.values()))
rkeys = list(regions)
mid = {}
for i, a in enumerate(rkeys):
    for j in rtree5.query(regions[a].buffer(0.1)):
        b = rkeys[j]
        if b <= a and not (a == -1 and b != -1) or a == b:
            continue
        key = tuple(sorted((a, b)))
        if key in mid:
            continue
        m_ = shapely.line_merge(regions[a].boundary.intersection(regions[b].boundary.buffer(0.05)).intersection(street.buffer(0.01)))
        # pieces whose ends are within 5 cm are one line (the regions' borders meet with rounding gaps)
        m_ = shapely.line_merge(shapely.set_precision(shapely.union_all([x for x in shapely.get_parts(m_) if x.geom_type == "LineString"]), 0.05))
        if m_.length > 1:
            mid[key] = m_
targets = [(k, blocks[k]) for k in range(len(blocks))] + [(-1, box.exterior)]
ttree = shapely.STRtree([t for _, t in targets])


def across(line, s):
    """At s along the middle line: the first thing hit square to it on either side, as (owner, point) twice."""
    p = line.interpolate(s)
    a, b = line.interpolate(max(s - 1, 0)), line.interpolate(min(s + 1, line.length))
    dx, dy = b.x - a.x, b.y - a.y
    h = (dx * dx + dy * dy) ** .5 or 1
    out = []
    for sg in (1, -1):
        ray = shapely.LineString([(p.x, p.y), (p.x - sg * dy / h * RAY, p.y + sg * dx / h * RAY)])
        best = None
        for t in ttree.query(ray):
            x = ray.intersection(targets[t][1].boundary if targets[t][0] >= 0 else targets[t][1])
            if x.is_empty:
                continue
            for q in shapely.get_parts(x):
                q = q if q.geom_type == "Point" else shapely.Point(q.coords[0])
                if best is None or p.distance(q) < best[2]:
                    # a side faces the street only where it runs along the middle line (within FACE_DEG); a line that passes a
                    # corner and meets the next side at a slant (a cross street, the area's edge where a street leaves it) does not
                    ring = targets[t][1].exterior if targets[t][0] >= 0 else targets[t][1]
                    bt = ring.project(q)
                    e0_, e1_ = ring.interpolate(max(bt - 1, 0)), ring.interpolate(min(bt + 1, ring.length))
                    ex, ey = e1_.x - e0_.x, e1_.y - e0_.y
                    along = abs(ex * dx + ey * dy) / (((ex * ex + ey * ey) ** .5 or 1) * h)
                    best = (targets[t][0] if along >= math.cos(math.radians(FACE_DEG)) else None, q, p.distance(q))
        out.append(best)
    return out


cuts, secpts, pairinfo, nopair, facing, cutpair, shortpairs = [], [], [], 0, {}, [], []
for (a, b), m_ in mid.items():
    for line in shapely.get_parts(m_):
        ss = [i * SAMPLE for i in range(int(line.length / SAMPLE) + 1)]
        ok = []
        for sv in ss:
            h_ = across(line, sv)
            ok.append(all(h_) and None not in (h_[0][0], h_[1][0]) and {h_[0][0], h_[1][0]} == {a, b})
        runs, start = [], None
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
            width = hm[0][1].distance(hm[1][1]) if all(hm) else 0
            # a section is at least as long as its street is wide; a shorter one is part of the junction (no cuts: its ground stays
            # in the intersection). One cut short by the area's edge stays: the street goes on outside.
            if c1 - c0 < 1 or (c1 - c0 < width and not (e0 or e1)):
                nopair += 1
                shortpairs.append((a, b, round(c1 - c0, 1), round(width, 1)))
                continue
            for cs_, edge in ((c0, e0), (c1, e1)):
                if not edge:
                    h_ = across(line, cs_)
                    cuts.append(shapely.LineString([h_[0][1], h_[1][1]]))
                    cutpair.append((a, b, round(cs_, 1), round(line.length, 1)))
            secpts.append(line.interpolate((c0 + c1) / 2))
            facing[(a, b)] = facing.get((a, b), 0) + s1 - s0
            pairinfo.append((a, b, round(c1 - c0, 1)))
over = [extend(cu, 0.05, (0, -1)) for cu in cuts]
pieces = [x for x in shapely.get_parts(shapely.polygonize(list(shapely.get_parts(shapely.union_all([street.boundary] + over)))))
          if x.representative_point().within(street) and x.area > 0.5]
secs, sinfo, rest = [], [], []
for x in pieces:
    hit = [i for i, p in enumerate(secpts) if x.distance(p) < 0.01]
    if hit:
        secs.append(x)
        sinfo.append([pairinfo[i] for i in hit])
    else:
        rest.append(x)
print(f"neighbour pairs {len(mid)} (with the area's outside {sum(1 for k in mid if -1 in k)}); sections {len(secs)}; pairs too short for a section {nopair} (of them shorter than the street is wide: {sum(1 for x in shortpairs if x[2] >= 1)}); "
      f"pieces holding two pairs' sections {sum(1 for v in sinfo if len(v) > 1)}")
sections = secs
from collections import Counter
print("street pieces outside sections, by sections touched:", sorted(Counter(sum(1 for y in secs if y.distance(x) < 0.05) for x in rest).items()))
JOIN = True
keep = []
for x in rest:
    touch = [(y.boundary.intersection(x.boundary.buffer(0.05)).length, mi) for mi, y in enumerate(secs) if y.distance(x) < 0.05]
    if JOIN and 0 < len(touch) < 3:
        mi = max(touch)[1]
        secs[mi] = poly(shapely.union_all([secs[mi], x], grid_size=0.01))
    else:
        keep.append(x)
print(f"leftovers joined to a section: {len(rest) - len(keep)}")
rest = keep
ends_at = {}
for j, ch in enumerate(chains):
    for e_ in (0, -1):
        ends_at.setdefault(tuple(round(v, 2) for v in ch["geom"].coords[e_]), []).append((j, e_))
junctions = {p: arms for p, arms in ends_at.items() if len(arms) >= 3}
inter = rest
nocut = 0
ncut = lambda x: sum(1 for cu in cuts if cu.intersection(x.boundary.buffer(0.02)).length > 0.5 * cu.length)
print(f"rest of the street {len(rest)} pieces: intersections (touch 3+ sections) {sum(1 for x in rest if sum(1 for y in sections if y.distance(x) < 0.05) >= 3)}, "
      f"touch none {sum(1 for x in rest if not any(y.distance(x) < 0.05 for y in sections))}; narrower than 2 m: {sum(1 for x in rest + sections if x.buffer(-1).is_empty)}")
fill = sorted(x.area / x.minimum_rotated_rectangle.area for x in sections)
print(f"sections filling their rectangle: >= 95% {sum(1 for v in fill if v >= .95)}, 85-95% {sum(1 for v in fill if .85 <= v < .95)}, less {sum(1 for v in fill if v < .85)}; "
      f"street area: sections {sum(x.area for x in sections):,.0f} m2, rest {sum(x.area for x in rest):,.0f} m2")
print(f"vertices per block: derived median {statistics.median([len(b.exterior.coords) for b in blocks])}, city median {statistics.median([len(x.exterior.coords) for x in city])}")
sys.path[:0] = ["src", "../roadstyle/src"]
import geopandas as gpd
import roadstyle as rs
back = lambda geoms: gpd.GeoSeries(geoms, crs=32610).to_crs(4326)
pal = ["#cbd5e1", "#e2e8f0", "#d1d5db", "#e5e7eb", "#d6d3d1", "#dbeafe"]
fr = lambda kind, geoms, col, **kw: gpd.GeoDataFrame({"kind": kind, "area_m2": [round(g.area) for g in geoms], "color": col, **kw}, geometry=back(geoms))
ptree = shapely.STRtree(parcels) if parcels else None
ltree_ = shapely.STRtree(lanes_) if lanes_ else None
rtree_ = shapely.STRtree([g for *_, g in roads])
around = lambda b: binfo[blocks.index(b)]
did = lambda b: f"db-{b.centroid.x:.0f}-{b.centroid.y:.0f}"
cgdf = gpd.GeoDataFrame({"kind": "city block", "id": [x["id"] for x in cityinfo], "source": "vancouver: block-outlines (property)",
                         "fetched": fetched, "area_m2": [round(x["geom"].area) for x in cityinfo], "full_area_m2": [x["full_m2"] for x in cityinfo],
                         "clipped": ["yes, at the edge of our area" if x["clipped"] else "no" for x in cityinfo],
                         "parcels": [sum(1 for k in ptree.query(x["geom"]) if parcels[k].representative_point().within(x["geom"])) if ptree else 0 for x in cityinfo],
                         "lanes_m": [round(sum(x["geom"].intersection(lanes_[k]).length for k in ltree_.query(x["geom"]))) if ltree_ else 0 for x in cityinfo],
                         "derived_match": [did(blocks[x["match"]]) if x.get("match") is not None else "none" for x in cityinfo],
                         "overlap": [x.get("iou", 0) for x in cityinfo], "edge_dist_m": [f"median {x.get('d50', '-')}, 90% {x.get('d90', '-')}" for x in cityinfo],
                         "color": "#fde68a"}, geometry=back(city))
dgdf = gpd.GeoDataFrame({"kind": "derived block", "id": [did(b) for b in blocks], "source": "osm: derived from the road topology",
                         "method": "faces of the level-0 public streets; each side of a street one edge parallel to it (parcels, sidewalks or class), never through a building", "area_m2": [round(b.area) for b in blocks],
                         "edges": binfo, "city_match": [match_of.get(k, ("none", 0))[0] for k in range(len(blocks))],
                         "overlap": [match_of.get(k, ("none", 0))[1] for k in range(len(blocks))], "color": "#a78bfa"}, geometry=back(blocks))
nm = lambda k: "the area's edge" if k == -1 else did(blocks[k])
mlines = [(k, ln) for k, m_ in mid.items() for ln in shapely.get_parts(m_) if ln.geom_type == "LineString"]
mgdf = gpd.GeoDataFrame({"kind": ["street neighbours" if facing.get(k, 0) >= 2 * ARM_M + 1 else "corner neighbours" for k, _ in mlines],
                         "blocks": [f"{nm(k[0])} / {nm(k[1])}" for k, _ in mlines], "facing_m": [round(facing.get(k, 0), 1) for k, _ in mlines],
                         "rule": "street neighbours: face each other across one street for 7 m or more; corner neighbours: their shares touch, they do not face",
                         "middle_line_m": [round(ln.length, 1) for _, ln in mlines],
                         "color": ["#16a34a" if facing.get(k, 0) >= 2 * ARM_M + 1 else "#dc2626" for k, _ in mlines]},
                        geometry=back([ln.buffer(0.6, cap_style="flat") for _, ln in mlines]))
layers = [("City blocks (the truth)", cgdf),
          ("Derived blocks (from roads)", dgdf),
          ("Sections (from derived blocks)", gpd.GeoDataFrame({"kind": "section", "id": [f"sec-{x.centroid.x:.0f}-{x.centroid.y:.0f}" for x in sections],
              "street": [max(((x.intersection(ch["geom"]).length, ch["name"] or ch["cl"]) for ch in chains), default=(0, ""))[1] for x in sections], "cuts": [ncut(x) for x in sections],
              "street_from": "osm (the bounding road in it)", "method": "between two neighbouring blocks, cut at two positions 3 m inside the stretch where they face each other",
              "neighbours": ["; ".join(f"{nm(i[0])} / {nm(i[1])} (facing {facing.get((i[0], i[1]), 0):.0f} m)" for i in v) for v in sinfo],
              "area_m2": [round(x.area) for x in sections],
              "color": [pal[i % len(pal)] for i in range(len(sections))]}, geometry=back(sections))),
          ("Intersections (from derived blocks)", gpd.GeoDataFrame({"kind": "intersection", "id": [f"int-{x.centroid.x:.0f}-{x.centroid.y:.0f}" for x in inter],
              "streets": [" / ".join(sorted({ch["name"] or ch["cl"] for ch in chains if ch["geom"].distance(x) < 1})) for x in inter],
              "method": "the street left between the sections",
              "blocks": [", ".join(did(b) for b in blocks if b.distance(x) < 0.5) for x in inter], "area_m2": [round(x.area) for x in inter],
              "color": "#fb923c"}, geometry=back(inter))),
          ("Neighbours: middle lines (green street, red corner)", mgdf)]
sd = lambda ch, sg: f"{ch['sides'][sg][0]:.1f} m ({ch['sides'][sg][1]})" if sg in ch["sides"] else "-"
rd = gpd.GeoDataFrame({"highway": [ch["cl"] for ch in chains], "name": [ch["name"] for ch in chains], "edge_id": range(len(chains)),
                       "left_edge": [sd(ch, 1) for ch in chains], "right_edge": [sd(ch, -1) for ch in chains]}, geometry=back([ch["geom"] for ch in chains]))
ov = lambda lab, g, vis: rs.Overlay(g, placement="under", color=g["color"].iloc[0], color_col="color", opacity=0.6 if "Derived" in lab else 0.95 if "Neighbours" in lab else 0.85,
                                    outline="#334155", width=0.8, label=lab, visible=vis, popup=[c_ for c_ in g.columns if c_ not in ("geometry", "color")],
                                    tooltip=["kind", "id"] if "id" in g else ["kind"])
mp = rs.render_edges(rd, palette="mono", basemap="voyager", name="blocks from roads", filter_control=False, road_popup=["name", "highway", "left_edge", "right_edge"],
                     overlays=[ov(lab, g, vis) for (lab, g), vis in zip(layers, (False, True, True, True, True))])
open(OUT, "w").write(mp.html)
print(OUT)

# the city blocks no derived block matches: why
print("\nunmatched city blocks:")
inv = lambda p: c.execute("SELECT ST_X(g), ST_Y(g) FROM (SELECT ST_Transform(ST_Point(?, ?), 'EPSG:32610', 'EPSG:4326', always_xy := true) g)", [p.x, p.y]).fetchone()
for x in cityinfo:
    if x.get("iou", 0) >= 0.8:
        continue
    cb = x["geom"]
    over = sorted(((cb.intersection(blocks[k]).area, k) for k in dtree.query(cb) if cb.intersection(blocks[k]).area > 20), reverse=True)
    why = []
    if x["clipped"]:
        why.append("clipped at the edge of our area")
    if not over:
        why.append("no derived block there at all")
    elif len(over) > 1:
        why.append(f"split into {len(over)} derived blocks")
    else:
        db = blocks[over[0][1]]
        if db.area > 1.3 * cb.area:
            others = [y["id"] for y in cityinfo if y is not x and y["geom"].intersection(db).area > 0.2 * y["geom"].area]
            why.append(f"merged with {len(others)} other city block(s) into one derived block ({db.area:,.0f} m2): " + ", ".join(others[:3]))
        elif db.area < 0.7 * cb.area:
            why.append(f"derived block much smaller ({db.area:,.0f} m2)")
    inside = [roads[k] for k in rtree_.query(cb) if roads[k][4].intersection(cb.buffer(-3)).length > 5]
    if inside:
        why.append("a bounding road runs through the city block: " + ", ".join(sorted({f"{r[1] or '(no name)'} ({r[0]})" for r in inside})))
    lon, lat = inv(cb.representative_point())
    print(f"  {x['id']}: {cb.area:,.0f} m2, overlap {x.get('iou', 0):.2f}, at {lon:.5f},{lat:.5f} -> " + "; ".join(why or ["edges far apart"]))

# buildings cut by a derived block's edge
bl = [shapely.from_wkb(w) for (w,) in s.execute(f"SELECT {m} FROM space.element WHERE type = 'building' AND level_min <= 0 AND level_max >= 0").fetchall()]
bl = [poly(shapely.make_valid(g).intersection(box)) for g in bl]   # a building past the edge of the area counts only inside it
btr = shapely.STRtree(bl)
cut_n, cut_m2, worst = 0, 0.0, []
for b in blocks:
    for k in btr.query(b):
        inside = bl[k].intersection(b).area
        out_ = bl[k].area - inside
        if inside > 1 and out_ > 1:
            cut_n += 1
            cut_m2 += out_
            worst.append((round(out_, 1), did(b)))
print(f"\nbuildings cut by a derived block's edge: {cut_n} ({cut_m2:,.0f} m2 of building outside its block); worst: {sorted(worst, reverse=True)[:5]}")
target = [b for b in blocks if did(b) == "db-490147-5457086"]
if target:
    b = target[0]
    print("db-490147-5457086:", around(b))
    for k in btr.query(b):
        inside = bl[k].intersection(b).area
        if inside > 1 and bl[k].area - inside > 1:
            print(f"   a building of {bl[k].area:.0f} m2 with {bl[k].area - inside:.0f} m2 outside the block")

print("\nsides pulled in to a building, by how much:")
pl = sorted(((float(d[1].split(" -> ")[0].split(": ")[-1]) - d[0], ch["name"] or ch["cl"], d) for ch in chains for d in ch["sides"].values() if "pulled" in d[1]), reverse=True)
print("  >3 m:", sum(1 for x in pl if x[0] > 3), " 1-3 m:", sum(1 for x in pl if 1 <= x[0] <= 3), " <1 m:", sum(1 for x in pl if x[0] < 1))
for x in pl[:8]:
    print("  ", round(x[0], 1), x[1], x[2])
if DEBUG:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(16, 16))
    def draw(gs, **kw):
        for gg in gs:
            for pp in shapely.get_parts(gg):
                if pp.geom_type == "Polygon":
                    ax.fill(*pp.exterior.xy, **kw)
                else:
                    ax.plot(*pp.xy, **{k: v for k, v in kw.items() if k in ("color", "lw")})
    draw(blocks, color="#ddd6fe", lw=0.5)
    bad = [x for x in inter if x.buffer(-1).is_empty or not any(y.distance(x) < 0.05 for y in sections)]
    draw([x for x in inter if x not in bad], color="#fb923c")
    draw(sections, color="#e5e7eb")
    draw(bad, color="#ef4444")
    draw(cuts, color="k", lw=1)
    draw([ch["geom"] for ch in chains], color="#2563eb", lw=0.6)
    for p in junctions:
        ax.plot(*p, "o", ms=3, color="#2563eb")
    ax.set_aspect("equal")
    fig.savefig(DEBUG, dpi=80, bbox_inches="tight")
