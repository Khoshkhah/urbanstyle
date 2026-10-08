"""space.strip: how each street space is filled (docs/design/street-objects.md section 4.2, first version).

Called at the end of urbanstyle.build(). Everything is cut from the container's own zones, so the strips of a container add up to its
travelway and pedestrian realm: nothing is left unfilled and nothing overlaps.

section      travelway  -> `travel` lane bands: the road's lanes (tag `lanes`, else width / LANE_M) laid out either side of its centerline,
                           the outer lanes running on to the kerb, then `travel` for whatever is left
             pedestrian -> `cycle` (measured cycleway lines), `frontage` (within FRONTAGE_M of a building), `furnishing` (within FURNISHING_M of
                           the kerb), `open` (more than OPEN_M from both: reached only by the reach cap), `sidewalk` (the rest)
intersection travelway -> `travel`, pedestrian realm -> `sidewalk`
path         walkway / cycleway lines -> `sidewalk` / `cycle`, the rest `open`
plaza        the whole container -> `plaza`;   rail: the whole container -> `track`

Every row says where it came from: `tag` (lanes or width tagged), `measured` (a measured line: cycleway), `default`.
No axis and no (s, t) yet, so no s_from / s_to: that is step 3 of the plan.
"""
import math

LANE_M = 3.25
FRONTAGE_M = 1.2
FURNISHING_M = 1.8
OPEN_M = 6.0
MIN_M2 = 0.5
EXT_M = 30.0   # how far an outer lane may run on towards the kerb before it is clipped to the travelway


def build(con, epsg):
    import pandas as pd
    import shapely
    from shapely import STRtree

    g = lambda w: shapely.make_valid(shapely.from_wkb(bytes(w)))
    tr = f"ST_Transform(geometry, 'EPSG:4326', '{epsg}', always_xy := true)"
    kinds = {c: (k, lv) for c, k, lv in con.execute("SELECT container_id, kind, level FROM space.container").fetchall()}
    zone = {}
    for cid, z, w in con.execute(f"SELECT container_id, zone, ST_AsWKB({tr}) FROM space.zone").fetchall():
        zone.setdefault(cid, {})[z] = g(w)
    full = {cid: g(w) for cid, w in con.execute(f"SELECT container_id, ST_AsWKB({tr}) FROM space.container").fetchall()}
    els = {}
    for cid, typ, osm, wd, sub, cls, w in con.execute(
            f"SELECT container_id, type, osm_id, coalesce(width_m, 3), subtype, class, ST_AsWKB({tr}) FROM space.element WHERE type <> 'building' AND container_id IS NOT NULL ORDER BY osm_id, source_id").fetchall():
        els.setdefault(cid, []).append((typ, osm, wd, sub, cls, g(w)))
    tags = {r[0]: (r[1], r[2]) for r in con.execute("SELECT osm_id, tags['lanes'], tags['width'] FROM osm.raw.ways WHERE tags['highway'] IS NOT NULL").fetchall()}
    brows = con.execute("SELECT level, ST_AsWKB(g) FROM bm").fetchall()
    blevel = [r[0] for r in brows]
    bld = shapely.make_valid(shapely.from_wkb([bytes(r[1]) for r in brows])) if brows else []
    btree = STRtree(bld) if len(bld) else None

    def buildings(geom, level, pad):
        if btree is None:
            return shapely.Polygon()
        near = [bld[k] for k in btree.query(geom.buffer(pad)) if blevel[k] == level]
        return shapely.union_all(near) if near else shapely.Polygon()

    def num(v):
        try:
            return float(str(v).split(";")[0])
        except (TypeError, ValueError):
            return None

    def safe(op, a, b):   # a set operation that survives slightly invalid input: retry on a 1 cm grid
        try:
            return getattr(shapely, op)(a, b)
        except shapely.errors.GEOSException:
            return getattr(shapely, op)(shapely.make_valid(a), shapely.make_valid(b), grid_size=0.01)

    def side(d, line):   # the part of the plane within |d| m of the line, on its left (d > 0) or right (d < 0)
        return line.buffer(d, single_sided=True, cap_style="flat") if abs(d) > 1e-6 else shapely.Polygon()

    def band(line, a, b):
        if a >= 0:
            return safe("difference", side(b, line), side(a, line))
        if b <= 0:
            return safe("difference", side(a, line), side(b, line))
        return safe("union", side(a, line), side(b, line))

    rows, count = [], {}

    def put(cid, typ, geom, source, sd=None, length=None):
        for p in shapely.get_parts(shapely.make_valid(geom)):
            if p.geom_type != "Polygon" or p.area < MIN_M2:
                continue
            n = count[cid] = count.get(cid, 0) + 1
            rows.append((cid, kinds[cid][1], f"{cid}.{n}", typ, sd, round(p.area / max(length or 1.0, 1.0), 2), source, shapely.to_wkb(p)))

    def cut(geom, taken):   # geom minus what earlier strips took, polygons only
        return shapely.make_valid(geom if taken.is_empty else safe("difference", geom, taken))

    for cid, (kind, level) in kinds.items():
        z = zone.get(cid, {})
        whole = full[cid]
        # a repaired zone can leak outside the container (a ring that touches itself): keep both inside it, and the pedestrian realm off the travelway
        T = safe("intersection", z.get("travelway", shapely.Polygon()), whole)
        P = safe("difference", safe("intersection", z.get("pedestrian_realm", shapely.Polygon()), whole), T) if not T.is_empty else safe("intersection", z.get("pedestrian_realm", shapely.Polygon()), whole)
        if kind == "rail":
            put(cid, "track", whole, "default")
            continue
        if kind == "plaza":
            put(cid, "plaza", whole, "default")
            continue
        lines = els.get(cid, [])
        roads = [e for e in lines if e[0] == "road"]
        rlen = sum(e[5].length for e in roads) or sum(e[5].length for e in lines) or 1.0
        taken = shapely.Polygon()
        if kind == "section" and roads and not T.is_empty:
            for typ, osm, wd, sub, cls, ln in roads:
                lane_tag, width_tag = tags.get(osm, (None, None))
                nl, wtag = num(lane_tag), num(width_tag)
                n = int(nl) if nl and nl >= 1 else max(1, round(wd / LANE_M))
                wl = (wtag / n) if wtag else (wd / n if wd else LANE_M)
                src = "tag" if (nl or wtag) else "default"
                # lane offsets from the centerline: a one-way road's lanes are centred on it; a two-way road splits them either side
                if n == 1:
                    edges = [-wl / 2, wl / 2]
                else:
                    left = n // 2
                    edges = [-(n - left) * wl + i * wl for i in range(n + 1)]
                # the outer lanes run on to the kerb, but not past halfway to a neighbouring road of this container
                lim_l = lim_r = EXT_M
                for o in roads:
                    if o[5] is ln or o[1] == osm:
                        continue
                    d = ln.distance(o[5])
                    if 0 < d < 2 * EXT_M:
                        sl = shapely.shortest_line(ln, o[5])
                        a, b = shapely.Point(sl.coords[0]), shapely.Point(sl.coords[-1])
                        t = shapely.line_interpolate_point(ln, max(ln.project(a) - 1, 0)), shapely.line_interpolate_point(ln, min(ln.project(a) + 1, ln.length))
                        cross = (t[1].x - t[0].x) * (b.y - a.y) - (t[1].y - t[0].y) * (b.x - a.x)
                        if cross > 0:
                            lim_l = min(lim_l, d / 2)
                        else:
                            lim_r = min(lim_r, d / 2)
                edges[0], edges[-1] = -max(lim_r, abs(edges[0])), max(lim_l, abs(edges[-1]))
                for i in range(len(edges) - 1):
                    a, b = edges[i], edges[i + 1]
                    poly = cut(safe("intersection", band(ln, a, b), T), taken)
                    sd = "center" if n == 1 else ("left" if (a + b) / 2 > 0 else "right")
                    put(cid, "travel", poly, src, sd, ln.length)
                    taken = safe("union", taken, poly) if not poly.is_empty else taken
        if not T.is_empty:   # whatever travelway no lane band took (road ends, joints, a road with no centerline of its own here)
            put(cid, "travel", cut(T, taken), "default", None, rlen)
        if P.is_empty and kind != "path":
            continue
        if kind == "path":
            area = whole
            took = shapely.Polygon()
            for typ, osm, wd, sub, cls, ln in lines:
                if typ not in ("walkway", "cycleway"):
                    continue
                poly = cut(safe("intersection", ln.buffer(max(wd, 1.0) / 2), area), took)
                put(cid, "cycle" if typ == "cycleway" else "sidewalk", poly, "measured", None, ln.length)
                took = safe("union", took, poly) if not poly.is_empty else took
            put(cid, "open", cut(area, took), "default", None, rlen)
            continue
        bu = buildings(P, level, FRONTAGE_M + OPEN_M)
        took = shapely.Polygon()

        def take(typ, region, source):
            nonlocal took
            poly = cut(safe("intersection", region, P), took)
            put(cid, typ, poly, source, None, rlen)
            took = safe("union", took, poly) if not poly.is_empty else took

        if kind == "intersection":
            take("sidewalk", P, "default")
            continue
        cyc = [e for e in lines if e[0] == "cycleway"]
        if cyc:
            take("cycle", shapely.union_all([e[5].buffer(max(e[2], 1.5) / 2) for e in cyc]), "measured")
        take("frontage", bu.buffer(FRONTAGE_M) if not bu.is_empty else shapely.Polygon(), "default")
        take("furnishing", T.buffer(FURNISHING_M) if not T.is_empty else shapely.Polygon(), "default")
        near = safe("union", T.buffer(OPEN_M) if not T.is_empty else shapely.Polygon(), bu.buffer(OPEN_M) if not bu.is_empty else shapely.Polygon())
        far = safe("difference", P, near)
        take("open", far, "default")
        take("sidewalk", P, "measured" if any(e[0] == "walkway" for e in lines) else "default")

    df = pd.DataFrame(rows, columns=["container_id", "kind", "strip_id", "type", "side", "width_m", "source", "wkb"])
    con.execute(f"""CREATE OR REPLACE TABLE space.strip AS
        SELECT container_id::VARCHAR AS container_id, (SELECT level FROM space.container c WHERE c.container_id = d.container_id) AS level, strip_id::VARCHAR AS strip_id,
               type::VARCHAR AS type, side::VARCHAR AS side, width_m::DOUBLE AS width_m, source::VARCHAR AS source,
               ST_Transform(ST_GeomFromWKB(wkb::BLOB), '{epsg}', 'EPSG:4326', always_xy := true) AS geometry
        FROM df d""")
