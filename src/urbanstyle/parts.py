"""The inside of every new space (space.unit): its parts, its marks and the widths of its edges (docs/design/space-parts.md).

space.part   the parts that cover a unit exactly: junction area, lane (in / out of a junction, forward / backward along a subsection),
             bus lane, cycle lane, crosswalk, cycle crossing, carriageway (roadway no lane took), sidewalk, furnishing, open
space.mark   lines on it, at real size: kerb, centre line, lane line, stop line, give-way line, zebra (one bar of a crosswalk)
space.width  per intersection arm (at its cut) and per subsection (across its middle): total, roadway and sidewalk widths, lanes, lane width

Widths are MEASURED where the data allows and say so (`source`): a road's kerbs from its mapped sidewalks (`measured`, or `measured one
side`), else from a crossing path across it (`crossing`), else estimated from its lanes (`estimated`); the roadway runs kerb to kerb, the
centre line of a two-way road in its middle, each side's lanes sharing that side's width equally. A lanes tag sets the count (`tag`); else the measured width / LANE_M sets it, at
least one lane each way on a two-way road. Cycle and bus lanes come from the cycleway tags (on the correct side of the way's direction).
The sidewalk runs from the kerb to the building face (measured); a furnishing strip only where street furniture stands, out to it.
Right-hand traffic: lanes coming into a junction lie on the left of the arm seen from the junction, a subsection's forward lanes on the
right of its road.
"""
import math

LANE_M = 3.0           # (kept for reference) a typical lane
LANE_FIT_M = 3.5       # untagged: as many whole lanes as fit at this width; what is left is shoulder (parking, a hard strip)
MIN_LANE_M, MAX_LANE_M = 2.5, 3.75   # a two-way road narrower than 2 x MIN is one lane used both ways; a side wider than its lanes x MAX has a shoulder
EST_LANE_M = 3.25      # a lane's width when nothing is measured
SIDEWALK_HALF_M = 1.0  # a sidewalk is mapped along its middle: the kerb lies this much nearer the road
KERB_SEARCH_M = 12.0   # how far from a road its sidewalks are looked for (a sidewalk farther away is not this road's)
CROSSWALK_M = 3.0
# how a part was made -> (where its data comes from, how it was obtained): space.part `source`, `method`; `ref` is the source's own id
PROV = {"sumo": ("sumo", "derived"), "measured": ("osm", "measured"), "measured one side": ("osm", "measured"), "crossing": ("osm", "measured"),
        "tag": ("osm", "mapped"), "osm": ("osm", "mapped"), "mapillary": ("mapillary", "observed"), "estimated": ("urbanstyle", "estimated"),
        "rule": ("urbanstyle", "derived")}   # rule: drawn from a rule, e.g. every roundabout entry gives way
SAME_CROSSING_M = 6.0  # a crossing point this close to a mapped crossing path is that crossing, not a second one
CYCLE_M = 1.5          # a cycle lane at the roadway's edge
BUS_M = 3.2            # a bus lane (shared with bikes: cycleway=share_busway)
TRACK_M = 2.0          # a mapped cycle track
OPEN_M = 6.0           # pedestrian ground farther than this from both the kerb and the buildings is open ground, not sidewalk
FURNITURE = ("vegetation.tree", "furniture.lamp", "furniture.bench", "furniture.waste", "furniture.sign", "furniture.signal",
             "furniture.bike_parking", "furniture.post_box", "furniture.bollard", "furniture.hydrant", "furniture.advertising",
             "furniture.shelter", "furniture.vending", "furniture.water", "furniture.charging", "transit.stop")
FURNISH_ALONG_M = 6.0  # a furnishing strip runs this far along the kerb either side of a piece of street furniture
CONTROL_M = 35.0       # a stop / give-way sign or a signal this close to the junction, beside an arm, puts a line across its in lanes
MIN_M2 = 0.3
KERB_RADIUS_M = 3.0    # the radius of a junction's kerb around a block corner
BAND_PAD_M = 12.0      # a road's bands are drawn this far past its unit and trimmed to it: they reach a slanted cut exactly
ZEBRA_BAR_M, ZEBRA_GAP_M = 0.5, 0.5
ARROW_M = 3.0          # a painted lane arrow's length
ARROW_GAP_M = 1.5      # no two arrows closer than about this
POCKET_MAX_M2 = 30.0   # a pocket of ground smaller than this, the roadway nearly all round it, is roadway (unless a refuge is mapped)
ROADWAY_GAP_M = 1.2    # a gap narrower than this between two roadways is roadway too (a real island or median is wider)
OFF_GROUND_M = 1.5     # a tunnel's or a bridge's space reaches this far past its roadway (a narrow walkway), not out to open ground
SIGN_M = 8.0           # a Mapillary parking / no-parking sign this close to a shoulder says what it is (its position is ~1-5 m off)
SHOULDER_MAX_M = 2.5   # a shoulder beside SUMO's lanes is at most a parking lane; a wider measured kerb is left to the pedestrian realm


def _unit(x, y):
    h = math.hypot(x, y) or 1.0
    return x / h, y / h


def lane_overrides(con):
    """{osm way: lanes (both ways together)} from duckOSM's OSM fixes (`osm_overrides/osm_overrides.yaml` beside the duckOSM
    database, or $URBANSTYLE_OSM_OVERRIDES): the corrections duckOSM's next build makes, applied here without rebuilding it. A rule's
    `lanes` is per direction (doubled on a two-way way), `lanes_forward` / `lanes_backward` add up."""
    import os
    from pathlib import Path
    try:
        import yaml
        path = os.environ.get("URBANSTYLE_OSM_OVERRIDES")
        if not path:
            (db,) = con.execute("SELECT path FROM duckdb_databases() WHERE database_name = 'osm'").fetchone()
            path = Path(db).parent / "osm_overrides" / "osm_overrides.yaml"
        rules = (yaml.safe_load(Path(path).read_text()) or {}).get("overrides") or []
    except Exception:
        return {}
    out = {}
    for r in rules:
        if "lanes" not in r and "lanes_forward" not in r and "lanes_backward" not in r:
            continue
        try:
            (ow,) = con.execute("SELECT coalesce(tags['oneway'] IN ('yes', '1', 'true', '-1') OR tags['junction'] IN ('roundabout', 'circular'), false) "
                                "FROM osm.raw.ways WHERE osm_id = ?", [r["osm_id"]]).fetchone()
        except Exception:
            continue        # the way is not in this area
        if "lanes" in r:
            out[r["osm_id"]] = int(r["lanes"]) * (1 if ow else 2)
        else:
            out[r["osm_id"]] = int(r.get("lanes_forward") or 0) + (0 if ow else int(r.get("lanes_backward") or 0))
    return out


def build(con, epsg):
    import pandas as pd
    import shapely
    from shapely.ops import substring

    tr = lambda col="geometry": f"ST_AsWKB(ST_Transform({col}, 'EPSG:4326', '{epsg}', always_xy := true))"
    g = lambda w: shapely.make_valid(shapely.from_wkb(bytes(w)))

    def safe(op, a, b):     # a set operation that survives slightly invalid input: retry on a 1 cm grid
        try:
            return shapely.make_valid(getattr(shapely, op)(a, b))
        except shapely.errors.GEOSException:
            return shapely.make_valid(getattr(shapely, op)(shapely.make_valid(a), shapely.make_valid(b), grid_size=0.01))

    def area(geom):         # the polygons of a result only (a repair can leave lines and points beside them)
        ps = [p for p in shapely.get_parts(shapely.make_valid(geom)) if p.geom_type in ("Polygon", "MultiPolygon")] if geom is not None else []
        return shapely.union_all(ps) if ps else shapely.Polygon()

    def polys(geom):
        return [p for p in shapely.get_parts(shapely.make_valid(geom)) if p.geom_type == "Polygon" and p.area >= MIN_M2]

    def side(d, line):      # within |d| m of the line, on its left (d > 0) or right (d < 0)
        return line.buffer(d, single_sided=True, cap_style="flat") if abs(d) > 1e-6 else shapely.Polygon()

    def band(line, a, b):   # between offsets a < b from the line (left positive)
        if a >= 0:
            return safe("difference", side(b, line), side(a, line))
        if b <= 0:
            return safe("difference", side(a, line), side(b, line))
        return safe("union", side(a, line), side(b, line))

    def num(v):
        try:
            return float(str(v).split(";")[0])
        except (TypeError, ValueError):
            return None

    def direction(line, t):
        q0, q1 = line.interpolate(max(t - 1, 0)), line.interpolate(min(t + 1, line.length))
        return _unit(q1.x - q0.x, q1.y - q0.y)

    # ---- inputs
    units = [(uid, kind, sec, lv, g(w)) for uid, kind, sec, lv, w in con.execute(
        f"SELECT unit_id, kind, section_id, level, {tr()} FROM space.unit").fetchall()]
    edge_kind = {"lane": "cycle lane", "opposite_lane": "cycle lane", "share_busway": "bus lane"}
    tags, sides = {}, {}
    try:
        for osm, lanes, width, cl, cr, refs in con.execute("""SELECT osm_id, tags['lanes'], tags['width'],
                coalesce(tags['cycleway:left'], tags['cycleway:both'], tags['cycleway']), coalesce(tags['cycleway:right'], tags['cycleway:both'], tags['cycleway']),
                refs FROM osm.raw.ways WHERE tags['highway'] IS NOT NULL""").fetchall():
            tags[osm] = (num(lanes), num(width))
            if edge_kind.get(cl) or edge_kind.get(cr):
                sides[osm] = (edge_kind.get(cl), edge_kind.get(cr), list(refs or []))
    except Exception:       # no OSM database attached (a rebuild of the parts alone): counts from the widths, no cycle / bus lanes
        pass
    for osm, n in lane_overrides(con).items():      # lane counts duckOSM's OSM fixes correct
        tags[osm] = (float(n), tags.get(osm, (None, None))[1])
    try:
        ring_osm = {r[0] for r in con.execute("SELECT osm_id FROM osm.raw.ways WHERE tags['junction'] IN ('roundabout', 'circular')").fetchall()}
    except Exception:
        ring_osm = set()
    roads = {}
    for eid, osm, lv, w, ow, src, dst, cid, name, wk in con.execute(f"""SELECT source_id, osm_id, level_min, coalesce(width_m, 6), coalesce(oneway, false),
            src, dst, container_id, name, {tr()} FROM space.element WHERE type = 'road' AND ST_Length(geometry) > 0""").fetchall():
        roads[eid] = dict(osm=osm, level=lv, w=w, oneway=ow, src=src, dst=dst, cid=cid, name=name or "(unnamed)", g=g(wk))
    rtree_ids = list(roads)
    rtree = shapely.STRtree([roads[e]["g"] for e in rtree_ids]) if rtree_ids else None
    prows = con.execute(f"SELECT type, coalesce(subtype, ''), level_min, {tr()}, osm_id FROM space.element WHERE type IN ('walkway', 'cycleway')").fetchall()
    paths = [(typ, sub, lv, g(w)) for typ, sub, lv, w, _ in prows]
    path_osm = {id(p[3]): f"w{r[4]}" for p, r in zip(paths, prows) if r[4] is not None}   # a path's OSM way, by its geometry
    ptree = shapely.STRtree([p[3] for p in paths]) if paths else None
    objs = [(oid, cls, lv, ctl, g(w)) for oid, cls, lv, ctl, w in con.execute(f"""SELECT object_id, class, level,
            CASE WHEN class = 'furniture.signal' THEN 'signal' WHEN json_extract_string(attrs, '$.highway') IN ('stop', 'give_way')
                 THEN json_extract_string(attrs, '$.highway') END, {tr()}
            FROM space.object WHERE class LIKE 'crossing.%' OR class IN {FURNITURE}
               OR json_extract_string(attrs, '$.highway') IN ('stop', 'give_way')""").fetchall()]
    # street-level observations (mapillary.py, where fetched): signs, signals and street furniture join the objects (stop / give-way
    # lines, the furnishing strip); on the level of the nearest road. Parking signs also decide which shoulders are parking.
    seen = []
    try:
        seen = [(fid, grp, g(w)) for fid, grp, w in con.execute(f"SELECT feature_id, grp, {tr()} FROM space.observed").fetchall()]
    except Exception:       # not fetched for this area
        pass
    as_object = {"street light": ("furniture.lamp", None), "bin": ("furniture.waste", None), "bench": ("furniture.bench", None),
                 "traffic light": ("furniture.signal", "signal"), "give way": ("furniture.sign", "give_way"), "stop": ("furniture.sign", "stop"),
                 "parking": ("furniture.sign", None), "no parking": ("furniture.sign", None)}
    for fid, grp, p in seen:
        if grp in as_object and rtree is not None:
            objs.append((f"mly{fid}", as_object[grp][0], roads[rtree_ids[rtree.nearest(p)]]["level"], as_object[grp][1], p))
    signs = [(grp, p) for _, grp, p in seen if grp in ("parking", "no parking")]
    sgtree = shapely.STRtree([p for _, p in signs]) if signs else None
    # parking mapped in OSM: areas (along the kerb: parking=lane / street_side; else a lot; not underground or multi-storey) and
    # motorcycle parking points
    lots, moto = [], []
    try:
        lots = [(kind_ in ("lane", "street_side"), g(w)) for kind_, w in con.execute(f"""SELECT tags['parking'], {tr('geom')} FROM osm.features.sites
                WHERE kind = 'parking' AND coalesce(tags['parking'], '') NOT IN ('underground', 'multi-storey', 'rooftop')""").fetchall()]
        moto = [g(w) for (w,) in con.execute(f"SELECT {tr('geom')} FROM osm.features.pois WHERE kind = 'motorcycle_parking'").fetchall()]
    except Exception:
        pass
    lot_tree = shapely.STRtree([x for _, x in lots]) if lots else None
    moto_tree = shapely.STRtree(moto) if moto else None

    def parking_of(strip):
        """(part type, source) of a shoulder strip: parking where OSM maps street parking or motorcycle parking on it, else as the
        nearest Mapillary parking / no-parking sign within SIGN_M says; else a shoulder of unknown use."""
        if lot_tree is not None and any(lots[k][0] for k in lot_tree.query(strip.buffer(1.0), predicate="intersects")):
            return "parking", "osm"
        if moto_tree is not None and len(moto_tree.query(strip.buffer(3.0), predicate="intersects")):
            return "parking", "osm"
        near = sorted(((signs[k][1].distance(strip), signs[k][0]) for k in sgtree.query(strip.buffer(SIGN_M))), key=lambda t: t[0]) if sgtree is not None else []
        if near:
            return ("parking" if near[0][1] == "parking" else "no parking"), "mapillary"
        return "shoulder", "measured"

    otree = shapely.STRtree([o[4] for o in objs]) if objs else None
    blds = [(lv, g(w)) for lv, w in con.execute(f"SELECT l, {tr()} FROM space.element, generate_series(level_min, level_max) t(l) WHERE type = 'building'").fetchall()]
    btree = shapely.STRtree([b[1] for b in blds]) if blds else None
    cuts = {}
    for iid, eid, w in con.execute(f"SELECT intersection_id, edge_id, {tr()} FROM space.cut").fetchall():
        cuts.setdefault(iid, []).append((eid, g(w)))
    sub_of = {r[0]: (r[1], g(r[2])) for r in con.execute(f"SELECT subsection_id, with_sections, {tr()} FROM space.subsection").fetchall()}

    def kerbs(ln, level, r):
        """(left, right, source): where the kerbs of road `r` (its line `ln`) are. From the mapped sidewalks either side: a sidewalk is
        mapped along its middle, so the kerb is SIDEWALK_HALF_M nearer the road (`measured`; one side only: the same both ways, `measured
        one side`). Else from a crossing path across it: its length minus two half sidewalks is kerb to kerb (`crossing`). Else estimated."""
        near = [paths[k] for k in ptree.query(ln.buffer(KERB_SEARCH_M))] if ptree is not None else []
        sw = [p[3] for p in near if p[2] == level and p[1] != "crossing"]
        swu = shapely.union_all(sw) if sw else None
        L, R = [], []
        n = max(2, min(15, int(ln.length // 2) + 1))
        for i in range(n):
            t = ln.length * (i + 0.5) / n
            c = ln.interpolate(t)
            tx, ty = direction(ln, t)
            for s_, out in ((1, L), (-1, R)):
                if swu is None:
                    continue
                ray = shapely.LineString([(c.x, c.y), (c.x - s_ * ty * KERB_SEARCH_M, c.y + s_ * tx * KERB_SEARCH_M)])
                hit = safe("intersection", ray, swu)
                if not hit.is_empty:
                    d = c.distance(hit) - SIDEWALK_HALF_M
                    if d >= MIN_LANE_M / 2:
                        out.append(d)
        enough = max(2, n // 3)
        hl = sorted(L)[len(L) // 2] if len(L) >= enough else None
        hr = sorted(R)[len(R) // 2] if len(R) >= enough else None
        if hl and hr:
            return hl, hr, "measured"
        if hl or hr:                    # one side measured; the other side's half of the estimated roadway (not a mirror of a far sidewalk)
            el, er = estimate(r)
            return (hl or el), (hr or er), "measured one side"
        most = 2.5 * sum(estimate(r))       # a longer crossing way runs over more than this road (or along it): not its width
        spans = [seg.length - 2 * SIDEWALK_HALF_M for typ, sb, lv, cl in near if lv == level and sb == "crossing" and cl.intersects(ln)
                 for seg in [cl] if MIN_LANE_M <= seg.length - 2 * SIDEWALK_HALF_M <= most]
        if spans:
            t = sorted(spans)[len(spans) // 2]
            return t / 2, t / 2, "crossing"
        return (*estimate(r), "estimated")

    def estimate(r):
        """(left, right) half-widths of a road's roadway from its tags or width_m when nothing is measured."""
        nl, wt = tags.get(r["osm"], (None, None))
        if wt:
            return wt / 2, wt / 2
        n = int(nl) if nl and nl >= 1 else max(1 if r["oneway"] else 2, round(r["w"] / EST_LANE_M))
        return n * EST_LANE_M / 2, n * EST_LANE_M / 2

    def same_way_direction(r, ln):
        """Does `ln` run the way the OSM way runs (its left is the way's left)?"""
        refs = sides.get(r["osm"], (None, None, []))[2]
        e_fwd = True
        if r["src"] in refs and r["dst"] in refs:
            e_fwd = refs.index(r["src"]) < refs.index(r["dst"])          # the element's own geometry runs src -> dst
        g0, g1 = r["g"].coords[0], r["g"].coords[-1]
        l0, l1 = ln.coords[0], ln.coords[-1]
        along = (g1[0] - g0[0]) * (l1[0] - l0[0]) + (g1[1] - g0[1]) * (l1[1] - l0[1]) >= 0
        return along == e_fwd

    parts, marks, widths, count, claimed = [], [], [], {}, {}

    def add(uid, level, typ, geom, how, arm=None, direction=None, lane=None, width=None, ref=None):
        # a part takes only ground no earlier part of this unit took: no overlaps by construction (priority = the order of the calls)
        def precise(op, a, b):     # on a 1 cm grid: exact enough, robust where floating point is not (else the plain overlay)
            try:
                return area(getattr(shapely, op)(a, b, grid_size=0.01))
            except shapely.errors.GEOSException:
                return area(safe(op, a, b))
        if uid in claimed and geom is not None and not geom.is_empty:
            geom = precise("difference", area(geom), claimed[uid])
        got = polys(geom) if geom is not None else []
        if got:
            new = shapely.union_all(got)
            claimed[uid] = precise("union", claimed[uid], new) if uid in claimed else area(new)
        for p in got:
            n = count[uid] = count.get(uid, 0) + 1
            parts.append((uid, f"{uid}#{n}", level, typ, arm, direction, lane, round(width, 2) if width else None, *PROV.get(how, (how, None)), ref,
                          shapely.to_wkb(p)))
        return shapely.union_all(got) if got else shapely.Polygon()

    def mark(uid, level, typ, geom, arm=None, how="sumo", ref=None):
        if geom is None or geom.is_empty:
            return
        lines = [x for x in shapely.get_parts(geom) for x in (shapely.get_parts(x) if x.geom_type.startswith("Multi") else [x])
                 if x.geom_type == "LineString"]
        for ln in (shapely.get_parts(shapely.line_merge(shapely.MultiLineString(lines))) if len(lines) > 1 else lines):
            if ln.geom_type == "LineString" and ln.length >= 0.3:
                marks.append((uid, level, typ, arm, round(ln.length, 1), *PROV.get(how, (how, None)), ref, shapely.to_wkb(ln)))

    def wref(edge):
        """The OSM way of the road a SUMO edge was built from."""
        e = elem_of.get(edge)
        return f"w{roads[e]['osm']}" if e in roads else None

    def ordered_by(ctl):
        """(how, ref) of a stop or give-way line: the signs and signals that order it (OSM's objects, Mapillary's detections), or a rule."""
        ids = [str(o[0]) for o in ctl if o[0]]
        if not ids:
            return "rule", None
        return ("mapillary" if all(i.startswith("mly") for i in ids) else "osm"), ", ".join(ids)

    def zebra(uid, level, poly, walk, how, ref):
        """The white bars of a crosswalk: parallel to the road (square to the walking direction), ZEBRA_BAR_M wide, ZEBRA_GAP_M apart."""
        if poly.is_empty:
            return
        wx, wy = walk
        c = poly.centroid
        L = max(poly.bounds[2] - poly.bounds[0], poly.bounds[3] - poly.bounds[1]) + 2
        k = -L
        while k <= L:
            mx, my = c.x + wx * k, c.y + wy * k
            bar = shapely.LineString([(mx - wy * L, my + wx * L), (mx + wy * L, my - wx * L)])
            mark(uid, level, "zebra", safe("intersection", bar, poly.buffer(-0.1)), how=how, ref=ref)
            k += ZEBRA_BAR_M + ZEBRA_GAP_M

    def across_road(seg, axes):     # does a path piece run across the nearest road (more than 45 degrees to it), not along it?
        if not axes:
            return True
        m = seg.interpolate(0.5, normalized=True)
        ln = min(axes, key=lambda a: a.distance(m))
        tx, ty = direction(ln, ln.project(m))
        sx, sy = _unit(seg.coords[-1][0] - seg.coords[0][0], seg.coords[-1][1] - seg.coords[0][1])
        return abs(tx * sx + ty * sy) < math.cos(math.radians(45))

    def crossings(uid, level, U, C, axes):
        """Crosswalks and cycle crossings over the roadway C: mapped crossing paths (the pieces that run across a road, not along it),
        else crossing points square across the nearest of `axes` [line]. Draws the zebra bars. Returns the ground they took."""
        near = [paths[k] for k in ptree.query(U)] if ptree is not None else []
        mapped, taken = [], shapely.Polygon()
        paths_here = [ln for typ, sub, lv, ln in near if lv == level and sub == "crossing"]   # every mapped crossing, drawn or not
        for typ, sub, lv, ln in near:
            if lv != level or not (sub == "crossing" or typ == "cycleway"):
                continue
            on = safe("intersection", ln, C.buffer(1.0))
            for seg in [x for x in shapely.get_parts(on) if x.geom_type == "LineString" and x.length >= 1.0 and across_road(x, axes)]:
                w = CROSSWALK_M if typ == "walkway" else CYCLE_M
                got = add(uid, level, "crosswalk" if typ == "walkway" else "cycle crossing", safe("intersection", seg.buffer(w / 2, cap_style="flat"), C), "measured",
                          width=w, ref=path_osm.get(id(ln)))
                if typ == "walkway":
                    zebra(uid, level, got, _unit(seg.coords[-1][0] - seg.coords[0][0], seg.coords[-1][1] - seg.coords[0][1]), "measured", path_osm.get(id(ln)))
                taken = safe("union", taken, got)
                mapped.append(seg)
        for oid, cls, lv, ctl, p in ([objs[k] for k in otree.query(U)] if otree is not None else []):
            # a crossing point makes a crosswalk only where no crossing is mapped as a path (even one not drawn here: along the road, or in
            # the next space), or the same crossing is drawn twice
            if lv != level or not cls.startswith("crossing.") or not p.within(U) or any(p.distance(m) < SAME_CROSSING_M for m in mapped + paths_here) or not axes:
                continue
            ln = min(axes, key=lambda a: a.distance(p))
            t = ln.project(p)
            tx, ty = direction(ln, t)
            c, L, H = ln.interpolate(t), 30.0, CROSSWALK_M / 2
            rect = shapely.Polygon([(c.x - tx * H - ty * L, c.y - ty * H + tx * L), (c.x + tx * H - ty * L, c.y + ty * H + tx * L),
                                    (c.x + tx * H + ty * L, c.y + ty * H - tx * L), (c.x - tx * H + ty * L, c.y - ty * H - tx * L)])
            got = add(uid, level, "crosswalk", safe("intersection", rect, C), "estimated", width=CROSSWALK_M, ref=oid)
            zebra(uid, level, got, (-ty, tx), "estimated", oid)
            taken = safe("union", taken, got)
        return taken

    # painted arrows, one shape for all (paint_arrow): a shaft ARROW_M long to its tip and a head for each way the lane may go. Two arrows
    # in one lane (less than ARROW_GAP_M apart across it) keep ARROW_M + ARROW_GAP_M between their tips along it, so they never overlap;
    # this also keeps two roads mapped on top of each other from painting two arrows in one spot. A turn arrow (at a junction) says more
    # than a plain direction arrow: it takes the place of one in its way.
    approach_rows = []      # (unit, level, road, lane, moves, ways open to all, arrow painted, why not): space.approach
    arrow_tips = {}         # (level, cell) -> [arrow record]; a record: [x, y, kind, indices of its pieces in `marks`]
    ARROW_CELL = ARROW_M + ARROW_GAP_M

    def paint_arrow(uid, level, tip, h, ways, arm=None, kind="direction", how="sumo", ref=None):
        hx, hy = h
        cx, cy = int(tip[0] // ARROW_CELL), int(tip[1] // ARROW_CELL)
        clash = [a for i in (-1, 0, 1) for j in (-1, 0, 1) for a in arrow_tips.get((level, cx + i, cy + j), [])
                 if abs((tip[0] - a[0]) * hx + (tip[1] - a[1]) * hy) < ARROW_CELL and abs((tip[0] - a[0]) * -hy + (tip[1] - a[1]) * hx) < ARROW_GAP_M]
        if clash and (kind != "turn" or any(a[2] == "turn" for a in clash)):
            return False
        for a in clash:                 # a turn arrow replaces the direction arrows in its way
            for k in a[3]:
                marks[k] = None
            for cell in arrow_tips.values():
                if a in cell:
                    cell.remove(a)
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
                heads.append((end, _unit(end[0] - fork[0], end[1] - fork[1])))
        for (px, py), (dx, dy) in heads:
            pieces.append([(px - dx * 0.8 - dy * 0.4, py - dy * 0.8 + dx * 0.4), (px, py), (px - dx * 0.8 + dy * 0.4, py - dy * 0.8 - dx * 0.4)])
        idx = []
        for pc in pieces:
            piece = shapely.LineString(pc)
            idx.append(len(marks))
            marks.append((uid, level, "arrow", arm, round(piece.length, 1), *PROV.get(how, (how, None)), ref, shapely.to_wkb(piece)))
        arrow_tips.setdefault((level, cx, cy), []).append([tip[0], tip[1], kind, idx])
        return True

    def arrow(uid, level, ln, off, t_tip, sgn, arm=None, how="sumo", ref=None):
        """A direction arrow in a lane (straight on): its tip at `t_tip` along `ln`, `off` m to the left of it, pointing along `ln`
        (sgn = 1) or back (sgn = -1)."""
        if ln.length < ARROW_M + 1:
            return
        c = ln.interpolate(t_tip)
        tx, ty = direction(ln, t_tip)
        paint_arrow(uid, level, (c.x - ty * off, c.y + tx * off), (tx * sgn, ty * sgn), {"straight"}, arm, how=how, ref=ref)

    def turn_arrow(uid, level, ap, off, ways, arm=None, ref=None):
        """A turn arrow in a lane coming into a junction, its tip 1 m before the stop position (`ap` runs out from it), `off` m to the
        left of `ap`; a head for each way the lane may go: straight on, left, right."""
        if ap.length < ARROW_M + 1:      # its tip 1 m before the stop position: SUMO's last piece of a lane may be short (lanes split)
            return False
        c = ap.interpolate(1.0)
        tx, ty = direction(ap, 1.0)
        return paint_arrow(uid, level, (c.x - ty * off, c.y + tx * off), (-tx, -ty), ways, arm, kind="turn", how="sumo", ref=ref)

    def curve(pa, ha, pb, hb):  # a quadratic curve from pa (heading ha) to pb (heading hb), its control where the two headings meet
        cr = ha[0] * hb[1] - ha[1] * hb[0]
        dx, dy = pb[0] - pa[0], pb[1] - pa[1]
        u, v = ((dx * hb[1] - dy * hb[0]) / cr, (ha[0] * dy - ha[1] * dx) / cr) if abs(cr) > 0.2 else (-1, -1)
        q = (pa[0] + u * ha[0], pa[1] + u * ha[1]) if u > 0 and v > 0 else ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)
        return shapely.LineString([((1 - t) ** 2 * pa[0] + 2 * (1 - t) * t * q[0] + t * t * pb[0],
                                    (1 - t) ** 2 * pa[1] + 2 * (1 - t) * t * q[1] + t * t * pb[1]) for t in [i / 12 for i in range(13)]])

    def lane_set(uid, level, C, ln, r, right, left, one, arm=None, half=None, arrows="middle"):
        """The lanes of road `r` (its line `ln`) in the roadway C, each side's measured width shared equally among that side's lanes;
        a tagged cycle or bus lane takes the outer edge of its side first. Lanes come back as (direction, polygon, from, to offsets). Two-way: `right` lanes on the right of the line, `left` on its
        left; one-way: all `one`. `half`: (left, right, source) measured elsewhere (an arm's approach). Returns ([(direction, polygon)],
        lanes right, lanes left, lane width, source)."""
        hl, hr, src = half if half else kerbs(ln, level, r)
        nl, _ = tags.get(r["osm"], (None, None))
        sl, sr, _ = sides.get(r["osm"], (None, None, []))
        if sl or sr:                                     # the way's left / right, seen along `ln`
            sl, sr = (sl, sr) if same_way_direction(r, ln) else (sr, sl)
        out = []
        for kind, s in ((sl, 1), (sr, -1)):              # a cycle or bus lane at the outer edge of its side
            if kind:
                h = hl if s == 1 else hr
                w = min(BUS_M if kind == "bus lane" else CYCLE_M, max(h - 2.5, 0))
                if w <= 0:
                    continue
                a, b = (h - w, h + 30) if s == 1 else (-h - 30, -h + w)
                got = add(uid, level, kind, safe("intersection", band(ln, a, b), C), "tag", arm=arm, width=w, ref=f"w{r['osm']}")
                mark(uid, level, "lane line", safe("intersection", shapely.offset_curve(ln, (h - w) * s), C), arm, how="tag", ref=f"w{r['osm']}")
                if s == 1:
                    hl -= w
                else:
                    hr -= w
        # bands across the roadway, right to left: (from, to, type, direction). A lane is MIN_LANE_M .. MAX_LANE_M wide; what a side
        # has beyond its lanes is a shoulder at the kerb (parking, a hard strip); a two-way road too narrow for a lane each way is one
        # lane used both ways (a narrow street).
        bands_ = []
        if not r["oneway"] and hl + hr < 2 * MIN_LANE_M:
            bands_.append((-hr, hl, "lane", "both"))
        elif r["oneway"]:
            n = int(nl) if nl and nl >= 1 else max(1, int((hl + hr) / LANE_FIT_M))
            wl = min((hl + hr) / n, MAX_LANE_M)
            spare = hl + hr - n * wl
            if spare > 0.3:                                # right-hand traffic: the shoulder is on the right
                bands_.append((-hr, -hr + spare, "shoulder", None))
            bands_ += [(-hr + spare + i * wl, -hr + spare + (i + 1) * wl, "lane", one) for i in range(n)]
        else:   # the centre line in the middle of the roadway (the mapped line need not be), the lanes split evenly either side
            total, c0 = hl + hr, (hl - hr) / 2
            per = max(1, int(total / 2 / LANE_FIT_M))     # untagged: whole lanes per direction; the rest is shoulder (parking)
            n = int(nl) if nl and nl >= 2 else 2 * per
            n_r, n_l = n // 2, n - n // 2
            wr, wl_ = min(total / 2 / n_r, MAX_LANE_M), min(total / 2 / n_l, MAX_LANE_M)
            if total / 2 - n_r * wr > 0.3:
                bands_.append((-hr, c0 - n_r * wr, "shoulder", None))
            bands_ += [(c0 - (n_r - i) * wr, c0 - (n_r - i - 1) * wr, "lane", right) for i in range(n_r)]
            bands_ += [(c0 + i * wl_, c0 + (i + 1) * wl_, "lane", left) for i in range(n_l)]
            if total / 2 - n_l * wl_ > 0.3:
                bands_.append((c0 + n_l * wl_, hl, "shoulder", None))
        inside = safe("intersection", ln, C.buffer(0.3))               # the line may run on past the unit: arrows only inside it
        la = max((x for x in shapely.get_parts(shapely.line_merge(inside) if inside.geom_type == "MultiLineString" else inside)
                  if x.geom_type == "LineString" and not x.is_empty), key=lambda x: x.length, default=None)
        if la is not None and ln.project(shapely.Point(la.coords[0])) > ln.project(shapely.Point(la.coords[-1])):
            la = shapely.LineString(la.coords[::-1])
        lanes_only = [x for x in bands_ if x[2] == "lane"]
        wl = sum(x[1] - x[0] for x in lanes_only) / max(len(lanes_only), 1)
        n_r = sum(x[3] in (right, "both") for x in lanes_only); n_l = sum(x[3] in (left, "both") for x in lanes_only)
        lsrc = src if not nl else "tag"
        for i, (a0, b0, typ, d) in enumerate(bands_):
            a1 = a0 - 30 if i == 0 else a0                 # the outer bands run on to the (irregular) kerb
            b1 = b0 + 30 if i == len(bands_) - 1 else b0
            got = add(uid, level, typ, safe("intersection", band(ln, a1, b1), C), lsrc, arm=arm, direction=d,
                      lane=i + 1 if typ == "lane" else None, width=b0 - a0, ref=f"w{r['osm']}")
            if typ == "lane":
                out.append((d, got, a0, b0))
                sgn = 1 if d == right else (-1 if d == left else 0)          # `right` lanes run along the line, `left` lanes back
                if sgn and la is not None and la.length >= ARROW_M + 2:
                    t = (la.length / 2 + sgn * ARROW_M / 2 if arrows == "middle" else
                         (1.0 if sgn < 0 else la.length - 1.0))           # ends: an arm's in lanes point at the junction, out lanes away
                    arrow(uid, level, la, (a0 + b0) / 2, t, sgn, arm, how=lsrc, ref=f"w{r['osm']}")
        for (a0, b0, t0, d0), (a1, b1, t1, d1) in zip(bands_, bands_[1:]):     # the painted line between two bands
            line = shapely.offset_curve(ln, b0) if abs(b0) > 1e-6 else ln
            kind = "centre line" if (t0 == t1 == "lane" and d0 != d1) else ("lane line" if t0 == t1 == "lane" else "edge line")
            mark(uid, level, kind, safe("intersection", line, C), arm, how=lsrc, ref=f"w{r['osm']}")
        return out, n_r, n_l, wl, src if not nl else "tag"

    def pedestrian(uid, level, U, C, corner_of=None, kerb_near=None):
        """The pedestrian realm U - C: a furnishing strip by the kerb only where street furniture stands (out to it), open ground far
        from both kerb and buildings, sidewalk the rest. Measured: it runs from the kerb to the building faces."""
        P = area(safe("difference", U, C))
        if P.is_empty:
            return
        near = [b for k in (btree.query(U.buffer(OPEN_M)) if btree is not None else []) for lv, b in [blds[k]] if lv == level]
        B = shapely.union_all(near) if near else shapely.Polygon()
        # the kerb: the level's, near by, when given (so two neighbouring spaces judge their shared ground alike), else its own
        kerb = kerb_near if kerb_near is not None and not kerb_near.is_empty else (C.boundary if not C.is_empty else shapely.LineString())
        furn = [o for o in ([objs[k] for k in otree.query(P)] if otree is not None else []) if o[2] == level and o[1] in FURNITURE and o[4].within(P)]
        for k, piece in enumerate(polys(P), start=1):
            grp = corner_of(piece, k) if corner_of else None
            here = [o[4] for o in furn if o[4].within(piece)]
            if here and not kerb.is_empty:
                d = min(max(sorted(p.distance(kerb) for p in here)[int(0.8 * (len(here) - 1))] + 0.6, 0.8), 4.0)
                strip = safe("intersection", safe("intersection", piece, kerb.buffer(d)), shapely.union_all([p.buffer(FURNISH_ALONG_M) for p in here]))
                add(uid, level, "furnishing", strip, "measured", arm=grp, width=d)
            reach = [x.buffer(OPEN_M) for x in (B, kerb) if not x.is_empty]
            far = safe("difference", piece, shapely.union_all(reach)) if reach else shapely.Polygon()
            add(uid, level, "open", far, "measured", arm=grp)
            add(uid, level, "sidewalk", piece, "measured", arm=grp)

    def across(uid, line_or_cut, ln, C, inside):
        """Widths along a cross line: (roadway, pedestrian left, pedestrian right), left / right seen along `ln`."""
        left = right = 0.0
        for seg in shapely.get_parts(safe("difference", inside, C.buffer(0.05))):
            if seg.geom_type != "LineString" or seg.is_empty:
                continue
            m = seg.interpolate(0.5, normalized=True)
            t = ln.project(m)
            tx, ty = direction(ln, t)
            q = ln.interpolate(t)
            if tx * (m.y - q.y) - ty * (m.x - q.x) > 0:
                left += seg.length
            else:
                right += seg.length
        return round(safe("intersection", inside, C.buffer(0.05)).length, 1), round(left, 1), round(right, 1)

    def line_in(r, U, pad=0.5):
        piece = safe("intersection", r["g"], U.buffer(pad))
        return max((x for x in shapely.get_parts(shapely.line_merge(piece) if piece.geom_type == "MultiLineString" else piece)
                    if x.geom_type == "LineString" and not x.is_empty), key=lambda x: x.length, default=None)

    counts = {}     # road (edge id) -> [(lanes src -> dst, lanes dst -> src, lane width)] in its subsections
    turn_rows = []
    measured = {}   # road (edge id) -> [(left, right)] measured mid-block in its subsections, sides seen along the road's own geometry

    def along_own(r, ln):    # does `ln` run the way the road's own geometry (src -> dst) runs?
        g0, g1, l0, l1 = r["g"].coords[0], r["g"].coords[-1], ln.coords[0], ln.coords[-1]
        return (g1[0] - g0[0]) * (l1[0] - l0[0]) + (g1[1] - g0[1]) * (l1[1] - l0[1]) >= 0

    directed, elem_of, bus_edges, shoulders = {}, {}, set(), {}     # shoulders: directed edge -> (right, left) m beyond its lanes   # (osm way, from node, to node) -> directed duckOSM edge; directed edge -> road element

    def sumo_roadway():
        """SUMO's roadway (sumo.network) on duckOSM's driving network, each direction of a road with the lanes measured in its
        subsections (count and width; a tagged bus lane is one more lane at its right, a cycle lane SUMO's bike lane). None without SUMO."""
        from urbanstyle import sumo
        try:
            dir_edges = con.execute("SELECT edge_id::VARCHAR, source, target, osm_id, coalesce(is_reverse, false) FROM osm.driving.edges").fetchall()
        except Exception as e:
            sumo.log.warning(f"no SUMO roadway: no duckOSM driving network ({type(e).__name__})")
            return None
        own = {(r["osm"], min(r["src"], r["dst"]), max(r["src"], r["dst"])): e for e, r in roads.items()}
        # the two halves of a divided road: two one-way ways in opposite directions closer than the roadway is wide
        ones = [e for e, r in roads.items() if r["oneway"]]
        otr = shapely.STRtree([roads[e]["g"] for e in ones]) if ones else None
        halves = {}     # a half -> [(the other half, distance between their lines)]
        for e in ones:
            g_, w_ = roads[e]["g"], sum(estimate(roads[e]))
            for t in (0.25, 0.5, 0.75):
                m = g_.interpolate(t, normalized=True)
                tx, ty = direction(g_, g_.length * t)
                for k in otr.query(m.buffer(w_)):
                    f = ones[k]
                    gf = roads[f]["g"]
                    if f != e and roads[f]["level"] == roads[e]["level"] and gf.distance(m) < w_:
                        fx, fy = direction(gf, gf.project(m))
                        if tx * fx + ty * fy < -0.8:
                            halves.setdefault(e, []).append((f, gf.distance(m)))
                            halves.setdefault(f, []).append((e, gf.distance(m)))     # the narrower half too
        attrs, room, ends_of = {}, {}, {}
        for de, s_, t_, osm, rev in dir_edges:
            directed[(osm, s_, t_)] = de
            e = own.get((osm, min(s_, t_), max(s_, t_)))
            if e is None:
                continue
            elem_of[de] = e
            ends_of[de] = (s_, t_)
            if not counts.get(e):       # no subsection measured it (a roundabout's ring, a junction's own link): estimated
                k = max(1, round(sum(estimate(roads[e])) / EST_LANE_M))
                counts[e] = [(k, 0, EST_LANE_M) if roads[e]["oneway"] else (max(1, k // 2), max(1, k // 2), EST_LANE_M)]
            if counts.get(e):
                c = sorted(counts[e])[len(counts[e]) // 2]
                n = c[0] if (s_, t_) == (roads[e]["src"], roads[e]["dst"]) else c[1]
                if n > 0:
                    attrs[de] = {"numLanes": n, "width": round(min(max(c[2], MIN_LANE_M), MAX_LANE_M), 2)}
                    sl, sr, _ = sides.get(osm, (None, None, []))
                    extra = sl if rev else sr                     # what the way has on this direction's right
                    if extra == "bus lane":
                        attrs[de]["numLanes"] = n + 1
                        bus_edges.add(de)
                    elif extra == "cycle lane":
                        attrs[de]["bikeLaneWidth"] = CYCLE_M
                    ms = measured.get(e)
                    if ms:      # the kerbs measured either side of the line
                        hl = sorted(m[0] for m in ms)[len(ms) // 2]
                        hr = sorted(m[1] for m in ms)[len(ms) // 2]
                        if (s_, t_) != (roads[e]["src"], roads[e]["dst"]):
                            hl, hr = hr, hl
                        room[de] = (hl, hr, bool(c[0] and c[1]))
        # each half of a divided road is centred on its own line (OSM draws a carriageway along its middle). Where the lines run closer
        # than the two roadways' half widths, the halves are pushed apart, each by half the overlap, and meet: no ground between them,
        # as where only paint parts the directions
        wide = lambda de: attrs[de]["numLanes"] * attrs[de]["width"] + attrs[de].get("bikeLaneWidth", 0)
        de_of = {e: de for de, e in elem_of.items()}
        shift = {}
        for e, near in halves.items():
            de = de_of.get(e)
            over = sorted((wide(de) + wide(de_of[f])) / 2 - gap for f, gap in near if de in attrs and de_of.get(f) in attrs)
            if over and over[len(over) // 2] > 0.1:
                shift[de] = over[len(over) // 2] / 2
        for de, s in shift.items():
            r = roads[elem_of[de]]
            ahead = ends_of[de] == (r["src"], r["dst"])
            moved = shapely.offset_curve(r["g"] if ahead else r["g"].reverse(), -s)       # to the right of the way it runs
            if moved.geom_type == "LineString":
                (wkt,) = con.execute(f"SELECT ST_AsText(ST_Transform(ST_GeomFromText(?), '{epsg}', 'EPSG:4326', always_xy := true))",
                                     [moved.wkt]).fetchone()
                attrs[de]["shape"] = " ".join(f"{x:.7f},{y:.7f}" for x, y in shapely.from_wkt(wkt).coords)
        for de, (hl, hr, two_way) in room.items():   # the measured kerbs beyond the lanes: a shoulder. Two-way: each direction right of
            L = wide(de)                              # its line, out to its own kerb; one-way: centred on it (a half: only its right)
            if two_way:
                sr, sl = hr - L, 0.0
            elif elem_of[de] in halves:
                sr, sl = hr - L / 2 - shift.get(de, 0.0), 0.0
            else:
                sr, sl = hr - L / 2, hl - L / 2
            if max(sr, sl) > 0.3:
                shoulders[de] = tuple(min(x, SHOULDER_MAX_M) if x > 0.3 else 0.0 for x in (sr, sl))
        return sumo.network(con, attrs, epsg)

    refuges = []        # mapped refuge islands: crossings tagged crossing:island=yes (ways and nodes)
    try:
        refuges = [g(w) for (w,) in con.execute(f"""SELECT {tr()} FROM space.element WHERE osm_id IN
                       (SELECT osm_id FROM osm.raw.ways WHERE tags['crossing:island'] = 'yes')""").fetchall()]
        refuges += [g(w) for (w,) in con.execute(f"""SELECT {tr('ST_Point(lon, lat)')} FROM osm.raw.nodes WHERE tags['crossing:island'] = 'yes'""").fetchall()]
    except Exception:
        pass
    reshaped = {}       # unit id -> its new outline (a tunnel or a bridge cut back to its tube)
    jnodes = {}         # intersection -> its nodes
    for iid, w in con.execute(f"""SELECT j.intersection_id, {tr('n.p')} FROM space.junction j JOIN (SELECT src AS node, ST_StartPoint(geometry) AS p
            FROM space.element WHERE type = 'road' UNION SELECT dst, ST_EndPoint(geometry) FROM space.element WHERE type = 'road') n ON n.node = j.node_id""").fetchall():
        jnodes.setdefault(iid, []).append(g(w))

    def from_sumo(net):
        """Every unit's parts on SUMO's roadway: its lanes (each at its own width, numbered from the right) and junction shapes are the
        roadway; to it come the mapped crosswalks, a roundabout's island, the markings, the turns (space.turn) and the pedestrian realm
        out to the buildings (docs/design/space-parts.md, "The roadway from SUMO")."""
        lane_type = {"driving": "lane", "bus": "bus lane", "bike": "cycle lane"}
        way = {"s": "straight", "l": "left", "L": "left", "r": "right", "R": "right"}      # SUMO's dir; "t", a u-turn, is left out
        # where a road only continues (its OSM way split there, no junction of ours), each lane runs on into the same lane of the next
        # piece: SUMO ends one and starts the other, which left the lane and its lines broken at the join
        import re
        real = {str(n) for (n,) in con.execute("SELECT node_id FROM space.junction").fetchall()}
        is_join = lambda j: not any(n in real for n in re.findall(r"\d+", j))
        into_j, out_j = {}, {}
        for edge, (fj, tj) in net["ends"].items():
            into_j.setdefault(tj, []).append(edge)
            out_j.setdefault(fj, []).append(edge)
        start = {(e, i): xy[0] for e, i, n, w, k, xy in net["lanes"] if xy}
        nlan = {}
        for e, i, n, w, k, xy in net["lanes"]:
            nlan[e] = n
        stitched = []
        for edge, i, n, w, kind_, xy in net["lanes"]:
            tj = net["ends"][edge][1]
            if xy and is_join(tj):
                nxt = [b for b in out_j.get(tj, []) if net["ends"][b][1] != net["ends"][edge][0] and nlan.get(b) == n]   # not its own way back
                if len(nxt) == 1 and (nxt[0], i) in start:
                    xy = list(xy) + [start[(nxt[0], i)]]
            stitched.append((edge, i, n, w, kind_, xy))
        lanes, by_edge = [], {}
        for edge, i, n, w, kind_, xy in stitched:
            e = elem_of.get(edge)
            ln = shapely.LineString(xy) if len(xy) >= 2 else None
            if e is None or ln is None or ln.length == 0:     # a lane SUMO's junction shape nearly covers still carries its moves
                continue
            x = dict(edge=edge, i=i, n=n, w=w, ln=ln, poly=ln.buffer(w / 2, cap_style="flat"), level=roads[e]["level"],
                     typ="bus lane" if kind_ == "driving" and i == 0 and edge in bus_edges else lane_type[kind_])
            lanes.append(x)
            by_edge.setdefault(edge, []).append(x)
        sh = []         # shoulders: beside the outer lanes, stopping short of the junctions (parking stops before a corner)
        for edge, (sr, sl) in shoulders.items():
            xs = sorted(by_edge.get(edge, []), key=lambda x: x["i"])
            if not xs:
                continue
            for w_, x, sgn in ((sr, xs[0], -1), (sl, xs[-1], 1)):
                base = shapely.offset_curve(x["ln"], sgn * x["w"] / 2)
                if w_ <= 0 or base.is_empty or base.geom_type != "LineString" or base.length < 8:
                    continue
                base = substring(base, KERB_RADIUS_M, base.length - KERB_RADIUS_M)
                poly = base.buffer(sgn * w_, single_sided=True, cap_style="flat")
                sh.append(dict(edge=edge, w=w_, level=x["level"], poly=poly, base=base, kind=parking_of(poly)))
        votes = {}      # a junction is on the level of the roads that meet there
        for edge, ends in net["ends"].items():
            for j in ends:
                if edge in elem_of:
                    votes.setdefault(j, []).append(roads[elem_of[edge]]["level"])
        juncs = [dict(id=j, poly=area(shapely.Polygon(xy)), level=max(set(votes[j]), key=votes[j].count))
                 for j, xy in net["junctions"].items() if len(xy) >= 3 and j in votes]
        juncs = [j for j in juncs if not j["poly"].is_empty]
        # where a road only continues (its way is split there, no junction of ours), SUMO's shape is a blob: a clean join of the lane
        # ends meeting there instead
        ends_at = {}
        for edge, (fj, tj) in net["ends"].items():
            for jj in (fj, tj):
                ends_at.setdefault(jj, []).extend(by_edge.get(edge, []))
        for j in juncs:
            if not any(n in real for n in re.findall(r"\d+", j["id"])):
                near = [area(safe("intersection", x["poly"], j["poly"].buffer(3.0))) for x in ends_at.get(j["id"], [])]
                hull = shapely.union_all([g for g in near if not g.is_empty] or [shapely.Polygon()]).convex_hull
                j["poly"] = area(hull) if not hull.is_empty else j["poly"]
        road_of = {}    # level -> the roadway: lanes and junctions, closed over gaps narrower than ROADWAY_GAP_M (between two roads drawn side by
        #                 side, between neighbouring lanes at a bend): no kerb in the middle of the road
        for lv in {x["level"] for x in lanes} | {j["level"] for j in juncs}:
            road_of[lv] = area(shapely.union_all([x["poly"] for x in lanes + sh if x["level"] == lv] + [j["poly"] for j in juncs if j["level"] == lv])
                               .buffer(ROADWAY_GAP_M / 2, join_style="mitre").buffer(-ROADWAY_GAP_M / 2, join_style="mitre"))
        ltree = shapely.STRtree([x["poly"] for x in lanes]) if lanes else None
        road_parts = {lv: list(shapely.get_parts(g_)) for lv, g_ in road_of.items()}
        road_trees = {lv: shapely.STRtree(v) for lv, v in road_parts.items() if v}

        # the level's kerb as short segments, indexed once: a space takes the stretch near it
        kerb_segs = {}
        for lv, g_ in road_of.items():
            segs = []
            for poly in shapely.get_parts(g_):
                for ring in [poly.exterior, *poly.interiors]:
                    cs = list(ring.coords)
                    segs += [shapely.LineString(cs[k:k + 2]) for k in range(len(cs) - 1)]
            kerb_segs[lv] = (segs, shapely.STRtree(segs)) if segs else ([], None)

        def kerb_at(lv, U_):
            segs, t = kerb_segs.get(lv, ([], None))
            near = [segs[k] for k in t.query(U_.buffer(OPEN_M + 2))] if t is not None else []
            return shapely.MultiLineString(near) if near else None

        def road_near(lv, U_):
            t = road_trees.get(lv)
            near = [road_parts[lv][k] for k in t.query(U_.buffer(1))] if t is not None else []
            return shapely.union_all(near).buffer(0.05) if near else shapely.Polygon()
        jtree = shapely.STRtree([j["poly"] for j in juncs]) if juncs else None
        stree = shapely.STRtree([x["poly"] for x in sh]) if sh else None
        by_ends = {v: k for k, v in net["ends"].items()}
        into = {}       # junction -> the lanes that end there
        for x in lanes:
            into.setdefault(net["ends"][x["edge"]][1], []).append(x)

        def onward(edge, k):
            """The junction a lane reaches going on (k=1) or back (k=0): on through the nodes where its road only continues."""
            for _ in range(20):
                f0, t0 = net["ends"][edge]
                j = t0 if k else f0
                nxt = [b for b in (out_j if k else into_j).get(j, []) if net["ends"][b][k] != (f0 if k else t0)] if is_join(j) else []
                if len(nxt) != 1:
                    return j
                edge = nxt[0]
            return j

        def lane_back(x):
            """A lane from its end back along its road, on through the nodes where the road only continues, as one line."""
            cs, edge = list(x["ln"].coords[::-1]), x["edge"]
            for _ in range(20):
                f0, t0 = net["ends"][edge]
                prev = [b for b in into_j.get(f0, []) if net["ends"][b][0] != t0] if is_join(f0) else []
                p_ = [y for y in by_edge.get(prev[0], []) if y["i"] == x["i"]] if len(prev) == 1 else []
                if not p_:
                    break
                cs += list(p_[0]["ln"].coords[::-1])
                edge = prev[0]
            return shapely.LineString(cs)
        utree = shapely.STRtree([u[4] for u in units])

        def unit_at(pt, level, default):     # the unit a point lies in
            return next((units[k][0] for k in utree.query(pt) if units[k][3] == level and units[k][4].distance(pt) < 0.1), default)
        # when a move is closed (or open) only at some times: duckOSM's turn rules with a condition, by its directed edges
        import duckdb
        cond = {}
        for q in ("SELECT from_edge, to_edge, condition FROM osm.driving.turn_permission WHERE condition IS NOT NULL",
                  "SELECT from_edge, to_edge, condition FROM osm.driving.turn_path_restrictions WHERE condition IS NOT NULL"):
            try:
                for fe, te, c_ in con.execute(q).fetchall():
                    cond[(str(fe), str(te))] = c_
            except duckdb.Error:        # a duckOSM build from before these tables
                pass
        conns = {}
        for f, fl, t, tl, dr, xy, veh in net["conns"]:
            conns.setdefault((f, fl), []).append((t, tl, dr, xy, veh))

        def longest(geom):
            return max((x for x in shapely.get_parts(shapely.line_merge(geom) if geom.geom_type == "MultiLineString" else geom)
                        if x.geom_type == "LineString" and not x.is_empty), key=lambda x: x.length, default=None)

        for uid, kind, sec, level, U in units:
            rb, sub = kind == "roundabout", kind == "subsection"
            C = area(safe("intersection", road_of.get(level, shapely.Polygon()), U))
            # a small pocket of ground the roadway nearly surrounds (a wedge where two roads meet at an angle) is roadway, unless a refuge
            # island is mapped there
            small = [q for q in polys(safe("difference", U, C)) if q.area < POCKET_MAX_M2 and not any(q.intersects(i) for i in refuges)]
            Cb = road_near(level, U) if small else None    # the level's roadway, also beyond this space's edge (only when there is a pocket)
            pockets = [q for q in small if q.boundary.intersection(Cb).length >= 0.85 * q.boundary.length]
            if pockets:
                C = area(safe("union", C, shapely.union_all(pockets)))
            if level != 0 and not C.is_empty:     # a tunnel or a bridge is a tube: its roadway and a narrow walkway, not the open ground
                tube = max(polys(safe("intersection", U, C.buffer(OFF_GROUND_M))), key=lambda x: x.area, default=None)   # beside it
                if tube is not None and all(tube.distance(q) < 0.5 for q in jnodes.get(uid, [])):   # a junction keeps all its nodes
                    U = tube
                    reshaped[uid] = U
                    C = area(safe("intersection", C, U))
            own = [e for e in (rtree_ids[k] for k in rtree.query(U))] if rtree is not None else []
            own = [e for e in own if roads[e]["level"] == level]
            taken = crossings(uid, level, U, C, [x for x in (line_in(roads[e], U) for e in own) if x is not None])
            if rb:          # the island: the ground the ring's line encloses, less half the ring's roadway (SUMO's junction shapes reach into it)
                ring_e = [e for e in own if roads[e]["osm"] in ring_osm]
                ring = [x for x in (line_in(roads[e], U, pad=BAND_PAD_M) for e in ring_e) if x is not None]
                enclosed = shapely.union_all(list(shapely.get_parts(shapely.polygonize(ring))) or [shapely.Polygon()])
                half = max((sum(estimate(roads[e])) / 2 for e in ring_e), default=0)
                C = area(safe("union", C, safe("intersection", enclosed.buffer(half), U)))     # the ring's roadway, round, whatever SUMO's pieces
                island = add(uid, level, "island", safe("intersection", enclosed.buffer(-half - 2).buffer(2), U), "measured")
                taken = safe("union", taken, island)
                C = area(safe("difference", C, island))
            jq = [juncs[k] for k in jtree.query(U) if juncs[k]["level"] == level] if jtree is not None else []
            # its junctions: not a node where a road only continues (a crosswalk splits the way there), whose road runs on through
            jhere = {j["id"] for j in jq if not is_join(j["id"]) and U.buffer(0.5).contains(j["poly"].representative_point())}
            line = sub_of.get(uid, (None, None))[1]
            mine = []       # (lane, direction, its line inside the unit)
            for x in ([lanes[k] for k in ltree.query(U) if lanes[k]["level"] == level] if ltree is not None else []):
                fj, tj = onward(x["edge"], 0), onward(x["edge"], 1)
                if sub:
                    d = "forward" if line is None or line.project(shapely.Point(x["ln"].coords[-1])) >= line.project(shapely.Point(x["ln"].coords[0])) else "backward"
                else:
                    d = ("circulating" if rb else None) if fj in jhere and tj in jhere else "in" if tj in jhere else "out" if fj in jhere else None
                piece = safe("intersection", x["poly"], U)
                if d == "circulating":          # a roundabout's ring is one part (the ring), its lanes only painted
                    got = piece
                else:
                    got = add(uid, level, x["typ"], piece, "sumo", arm=None if sub else roads[elem_of[x["edge"]]]["name"],
                              direction=d, lane=x["i"] + 1, width=x["w"], ref=f"w{roads[elem_of[x['edge']]]['osm']}" if x["edge"] in elem_of else None)
                if not area(got).is_empty:
                    mine.append((x, d, longest(safe("intersection", x["ln"], U)), area(got).area))
            for x in ([sh[k] for k in stree.query(U) if sh[k]["level"] == level] if stree is not None else []):
                got = add(uid, level, x["kind"][0], safe("intersection", x["poly"], U), x["kind"][1], width=x["w"], ref=wref(x["edge"]))
                if not got.is_empty and x["kind"][0] != "shoulder":     # the line between the lane and the parking strip
                    mark(uid, level, "edge line", safe("intersection", x["base"], U), ref=wref(x["edge"]))
            add(uid, level, "carriageway" if sub else "ring" if rb else "junction area", C, "sumo")   # the rest of the roadway, one part
            for street, lot in ([lots[k] for k in lot_tree.query(U)] if lot_tree is not None and level == 0 else []):
                add(uid, level, "parking" if street else "parking lot", safe("difference", safe("intersection", lot, U), C), "osm")
            names = [(roads[e]["name"], roads[e]["g"]) for e, _ in cuts.get(uid, []) if e in roads]
            pedestrian(uid, level, U, C, None if sub or not names else
                       lambda piece, k: " / ".join(nm for nm, _ in sorted(names, key=lambda t: t[1].distance(piece))[:2]), kerb_near=kerb_at(level, U))
            # markings
            mark(uid, level, "kerb", safe("intersection", C.boundary, U.buffer(-0.05)))
            paint = safe("difference", C.buffer(0.05), taken)             # not across a crosswalk
            own_secs = {sec, *((sub_of.get(uid, ("", None))[0] or "").split(","))} if sub else set()
            for x, d, inside, got_m2 in mine:
                arm = None if sub else roads[elem_of[x["edge"]]]["name"]
                left = shapely.offset_curve(x["ln"], x["w"] / 2)          # the lane's left edge
                if x["i"] < x["n"] - 1:
                    mark(uid, level, "lane line", safe("intersection", left, paint), arm, ref=wref(x["edge"]))
                else:               # the leftmost lane of a two-way road: the centre line, drawn by one of its two directions
                    twin = by_ends.get(tuple(reversed(net["ends"][x["edge"]])))
                    if twin is not None and x["edge"] < twin:
                        mark(uid, level, "centre line", safe("intersection", left, paint), arm, ref=wref(x["edge"]))
                # an arrow on a lane of this space's own road (not on one that only crosses or touches it), where the lane has ground here
                mine_road = d == "circulating" or roads[elem_of[x["edge"]]]["cid"] in own_secs
                if (sub or d == "circulating") and mine_road and got_m2 >= 2 * x["w"] and x["typ"] != "cycle lane" and inside is not None \
                        and inside.length >= ARROW_M + 2:
                    arrow(uid, level, inside, 0.0, inside.length / 2 + ARROW_M / 2, 1, ref=wref(x["edge"]))
            # the lanes coming into this junction (SUMO's, wherever its junction shape ends: maybe beyond the cut, in a subsection):
            # the ways each may go (space.turn, a guide line, a turn arrow) and a stop / give-way line where it enters the junction.
            # An arrow or a line belongs to the unit it lies in.
            # every road ending at the junction is an approach, whatever its level: roads that share a node meet there (a bridge whose
            # deck ends at the junction, as on West Broadway at Granville), a road passing over a junction never shares its node
            for x in ([] if sub else [x for j in jhere for x in into.get(j, [])]):
                if x["typ"] == "cycle lane" or net["ends"][x["edge"]][0] in jhere:
                    continue
                arm = roads[elem_of[x["edge"]]]["name"]
                moves = [(t, tl, way[dr], xy, veh) for t, tl, dr, xy, veh in conns.get((x["edge"], x["i"]), []) if dr in way]
                for t, tl, w_, xy, veh in moves:
                    if len(xy) >= 2:
                        g_ = shapely.LineString(xy)
                        if not rb:          # a roundabout has no guide lines: the ring shows the way round
                            mark(uid, level, "guide line", safe("intersection", g_, U), arm, ref=wref(x["edge"]))
                        turn_rows.append((uid, level, elem_of[x["edge"]], x["i"] + 1, elem_of.get(t, t), tl + 1, w_, "sumo", veh,
                                          cond.get((str(x["edge"]), str(t))), shapely.to_wkb(g_)))
                back = lane_back(x)                                           # from the junction back along the lane
                ways_all = {m[2] for m in moves if m[4] is None}              # the arrow shows the ways open to all traffic (not a bus-only turn)
                painted = bool(ways_all and back.length >= ARROW_M + 1 and not rb and
                               turn_arrow(unit_at(back.interpolate(1.0), level, uid), level, back, 0.0, ways_all, arm, ref=wref(x["edge"])))
                why = (None if painted else "no move" if not moves else "roundabout" if rb else "for some vehicles only" if not ways_all
                       else "lane piece under 4 m" if back.length < ARROW_M + 1 else "another arrow in the way")
                approach_rows.append((uid, level, elem_of[x["edge"]], x["i"] + 1, len(moves), ",".join(sorted(ways_all)), painted, why))
                end = shapely.Point(x["ln"].coords[-1])
                near = [objs[k] for k in otree.query(end.buffer(CONTROL_M))] if otree is not None else []
                ctl = [o for o in near if o[3] and o[2] == level and o[4].distance(x["ln"]) <= x["w"] + 6]
                if rb:
                    ctl = [(None, None, level, "give_way", None)]      # at a roundabout every entry gives way to the ring
                if ctl:
                    t0 = max(x["ln"].length - 0.3, 0)
                    c, (tx, ty), h = x["ln"].interpolate(t0), direction(x["ln"], t0), x["w"] / 2
                    mark(unit_at(c, level, uid), level, "give-way line" if all(o[3] == "give_way" for o in ctl) else "stop line",
                         shapely.LineString([(c.x - ty * h, c.y + tx * h), (c.x + ty * h, c.y - tx * h)]), arm, *ordered_by(ctl))
            # widths: at each arm's cut, or across the middle of a subsection
            if not sub:
                for eid, cut in cuts.get(uid, []):
                    r = roads.get(eid)
                    ln = line_in(r, U) if r is not None else None
                    if ln is None:
                        continue
                    if shapely.Point(ln.coords[0]).distance(cut) < shapely.Point(ln.coords[-1]).distance(cut):
                        ln = shapely.LineString(ln.coords[::-1])          # from the junction out to the cut
                    road_w, left, right = across(uid, cut, ln, C, cut)
                    node, far = (r["dst"], r["src"]) if not along_own(r, ln) else (r["src"], r["dst"])
                    li = [x for x in by_edge.get(directed.get((r["osm"], far, node)), []) if x["typ"] != "cycle lane"]
                    lo = [x for x in by_edge.get(directed.get((r["osm"], node, far)), []) if x["typ"] != "cycle lane"]
                    ws = [x["w"] for x in li + lo]
                    srcs = sorted(m[2] for m in measured.get(eid, [])) or ["estimated"]
                    widths.append((uid, level, eid, r["name"], round(cut.length, 1), road_w, left, right, len(li), len(lo),
                                   round(sum(ws) / len(ws), 2) if ws else None, srcs[0]))
            elif line is not None and line.length > 0:
                mid = line.interpolate(0.5, normalized=True)
                tx, ty = direction(line, line.length / 2)
                inside = safe("intersection", shapely.LineString([(mid.x + ty * 60, mid.y - tx * 60), (mid.x - ty * 60, mid.y + tx * 60)]), U)
                road_w, left, right = across(uid, inside, line, C, inside)
                hit = [(x, d) for x, d, _, _ in mine if x["typ"] != "cycle lane" and x["poly"].intersects(inside)]
                ws = [x["w"] for x, _ in hit]
                srcs = sorted({m[2] for e in own for m in measured.get(e, [])}) or ["estimated"]
                widths.append((uid, level, "middle", None, round(inside.length, 1), road_w, left, right, sum(d == "forward" for _, d in hit),
                               sum(d == "backward" for _, d in hit), round(sum(ws) / len(ws), 2) if ws else None, srcs[0]))

    def classic(uid, kind, sec, level, U):
        """The parts of one unit built around the OSM centrelines (the roadway as bands of the measured widths): the subsections always
        (they measure every road's kerbs and lanes, SUMO's input), the junctions when SUMO is not there."""
        if kind in ("intersection", "roundabout"):
            rb = kind == "roundabout"
            arms = []
            for eid, cut in cuts.get(uid, []):
                r = roads.get(eid)
                ln = line_in(r, U) if r is not None else None
                if ln is None:
                    continue
                if shapely.Point(ln.coords[0]).distance(cut) < shapely.Point(ln.coords[-1]).distance(cut):
                    ln = shapely.LineString(ln.coords[::-1])          # from the junction out to the cut
                lx = line_in(r, U, pad=BAND_PAD_M)                    # the same road run on past the cut: its bands reach a slanted cut
                if lx is not None and shapely.Point(lx.coords[0]).distance(shapely.Point(ln.coords[0])) > shapely.Point(lx.coords[-1]).distance(shapely.Point(ln.coords[0])):
                    lx = shapely.LineString(lx.coords[::-1])
                # the arm's roadway as measured mid-block on the same road (its subsections), else on its approach, else estimated
                ms = measured.get(eid)
                if ms:
                    # the road's widths in the subsection that meets this cut, so arm and road line up there (else the road's median)
                    at = min(ms, key=lambda x: x[3].distance(cut))
                    if at[3].distance(cut) < 0.5:
                        lm, rm, src_ = at[0], at[1], at[2]
                    else:
                        lm, rm = sorted(x[0] for x in ms)[len(ms) // 2], sorted(x[1] for x in ms)[len(ms) // 2]
                        src_ = sorted(x[2] for x in ms)[0]
                    hl, hr = (lm, rm) if along_own(r, ln) else (rm, lm)
                else:
                    hl, hr, src_ = kerbs(ln, level, r)
                ends_here = not along_own(r, ln)     # the arm runs out from the junction: a one-way road running the other way comes in
                arms.append(dict(eid=eid, r=r, ln=ln, lx=lx or ln, cut=cut, hl=hl, hr=hr, src=src_,
                                 one="in" if ends_here else "out", name=r["name"]))
            # the roadway of a junction, built from its arms as on the street: each arm's roadway up to the junction, the kerbs of
            # neighbouring arms joined around each block corner with a rounded corner
            C = shapely.Polygon()
            if arms:
                cx = sum(a["ln"].coords[0][0] for a in arms) / len(arms); cy = sum(a["ln"].coords[0][1] for a in arms) / len(arms)
                kerb_pts, bodies = [], []
                for a in arms:
                    end = shapely.Point(a["ln"].coords[-1])
                    tx, ty = direction(a["ln"], a["ln"].length)
                    kerb_pts += [(end.x - ty * a["hl"], end.y + tx * a["hl"]), (end.x + ty * a["hr"], end.y - tx * a["hr"])]
                    bodies.append(band(a["lx"], -a["hr"], a["hl"]))
                kerb_pts.sort(key=lambda q: math.atan2(q[1] - cy, q[0] - cx))
                star = shapely.make_valid(shapely.Polygon(kerb_pts)) if len(kerb_pts) >= 3 else shapely.Polygon()
                ring = []     # a roundabout's ring: its road edges inside the space, each with its roadway band
                if rb:
                    for e in (rtree_ids[k] for k in rtree.query(U)):
                        r_ = roads[e]
                        if r_["osm"] in ring_osm and r_["level"] == level:
                            lr = line_in(r_, U, pad=BAND_PAD_M)
                            if lr is not None:
                                hl_, hr_ = estimate(r_)
                                ring.append((e, lr, hl_, hr_))
                road = shapely.union_all([star] + bodies + [band(lr, -hr_, hl_) for e, lr, hl_, hr_ in ring]).buffer(KERB_RADIUS_M).buffer(-KERB_RADIUS_M)
                # next to each cut the roadway is only what the arms' road bands cover (the same bands the roads beyond the cuts are drawn
                # with): arm and road meet without a step; the kerb outline and its rounding shape only the corners farther in
                all_bodies = shapely.union_all(bodies)
                for a in arms:
                    zone = safe("intersection", a["cut"].buffer(KERB_RADIUS_M + 1.0), U)
                    road = safe("union", safe("difference", road, zone), safe("intersection", safe("intersection", road, all_bodies), zone))
                C = area(safe("intersection", road, U))
            taken = crossings(uid, level, U, C, [a["ln"] for a in arms])
            if rb and ring:
                # the central island: the ground the ring encloses, outside its roadway (not roadway, however the outline was drawn)
                enclosed = shapely.union_all([pg for pg in shapely.get_parts(shapely.polygonize([lr for _, lr, _, _ in ring]))] or [shapely.Polygon()])
                ringway = shapely.union_all([band(lr, -hr_, hl_) for _, lr, hl_, hr_ in ring])
                island = safe("intersection", safe("difference", enclosed, ringway), U)
                if not island.is_empty:
                    taken = safe("union", taken, add(uid, level, "island", island, "measured"))
                    C = area(safe("difference", C, island))
                # the circulating lanes, in the ring's driving direction (a ring is one-way along its own geometry)
                for e, lr, hl_, hr_ in ring:
                    lanes_r, *_ = lane_set(uid, level, safe("difference", C, taken), lr, roads[e], "circulating", "circulating", "circulating",
                                           arm="ring", half=(hl_, hr_, "estimated"))
                    taken = safe("union", taken, shapely.union_all([x[1] for x in lanes_r] or [shapely.Polygon()]))
            bodies = {a["eid"]: band(a["lx"], -a["hr"], a["hl"]) for a in arms}
            arm_lanes = {}
            for a in arms:
                # an arm's lanes run straight from its cut into the junction, as far as no other arm's roadway (and no crosswalk on it)
                # lies across them: the stop position. Same widths and offsets as the road's lanes beyond the cut.
                others = [bodies[b["eid"]] for b in arms if b is not a]
                ln = a["lx"]
                block = safe("intersection", bodies[a["eid"]], safe("union", shapely.union_all(others) if others else shapely.Polygon(), taken))
                pts = shapely.get_coordinates(block) if not block.is_empty else []
                s_stop = min(max([ln.project(shapely.Point(q)) for q in pts] or [0.0]), max(a["ln"].length - 1.0, 0))
                ap = substring(ln, s_stop, ln.length) if s_stop > 0 else ln
                a["s_stop"], a["ap"] = s_stop, ap
                # seen from the junction (the line runs outwards): right-hand traffic drives out on the right and comes in on the left
                lanes, n_r, n_l, wl, src = lane_set(uid, level, safe("difference", C, taken), ap, a["r"], "out", "in", a["one"], arm=a["name"],
                                                    half=(a["hl"], a["hr"], a["src"]), arrows="ends")
                arm_lanes[a["eid"]] = (lanes, wl, src)
                taken = safe("union", taken, shapely.union_all([x[1] for x in lanes] or [shapely.Polygon()]))
            box = add(uid, level, "junction area", safe("difference", C, taken), "measured")
            # guide lines through the junction area (a dashed line on the map): from every lane coming in to every lane out on another arm
            # (which lane may go where is known only from SUMO)
            def lane_ends(a, ways):     # an arm's lanes one way, each with its middle at the stop position
                c0 = a["ap"].interpolate(0)
                tx, ty = direction(a["ap"], 0)
                return [(c0.x - ty * (lo + hi) / 2, c0.y + tx * (lo + hi) / 2) for d, p, lo, hi in arm_lanes.get(a["eid"], ([], 0, ""))[0]
                        if d in (ways, "both")], (tx, ty)
            live = [a for a in arms if "ap" in a] if not rb else []      # a roundabout: its circulating lanes show the way round
            for a in live:
                ins, (tx, ty) = lane_ends(a, "in")
                for b in live:
                    outs, hb = lane_ends(b, "out") if b is not a else ([], None)
                    for pa, pb in ((x, y) for x in ins for y in outs):
                        mark(uid, level, "guide line", safe("intersection", curve(pa, (-tx, -ty), pb, hb), C), how="rule")
            for a in arms:      # stop / give-way lines: across the in lanes, at the stop position, where a sign or a signal says so
                near = [objs[k] for k in otree.query(a["ln"].buffer(max(a["hl"], a["hr"]) + 6))] if otree is not None else []
                ctl = [o for o in near if o[3] and o[2] == level and o[4].distance(shapely.Point(a["ln"].coords[0])) <= CONTROL_M]
                if rb:
                    ctl = [(None, None, level, "give_way", None)]      # at a roundabout every entry gives way to the ring
                ins = [(lo, hi) for d, p, lo, hi in arm_lanes.get(a["eid"], ([], 0, ""))[0] if d in ("in", "both")]
                if ctl and ins and "ap" in a:
                    lo, hi = min(x[0] for x in ins), max(x[1] for x in ins)
                    c0 = a["ap"].interpolate(0.2)
                    tx, ty = direction(a["ap"], 0.2)
                    mark(uid, level, "give-way line" if all(o[3] == "give_way" for o in ctl) else "stop line",
                         shapely.LineString([(c0.x - ty * lo, c0.y + tx * lo), (c0.x - ty * hi, c0.y + tx * hi)]), a["name"], *ordered_by(ctl))
            mark(uid, level, "kerb", safe("intersection", C.boundary, U.buffer(-0.05)), how="measured")

            def corner_of(piece, k):    # a corner takes the names of the two arms it lies between
                near_arms = sorted(arms, key=lambda a: a["ln"].distance(piece))[:2]
                return " / ".join(a["name"] for a in near_arms) if near_arms else f"corner {k}"
            pedestrian(uid, level, U, C, corner_of)
            for a in arms:      # widths at the cut
                road_w, left, right = across(uid, a["cut"], a["ln"], C, a["cut"])
                lanes, wl, src = arm_lanes.get(a["eid"], ([], 0, a["src"]))
                widths.append((uid, level, a["eid"], a["name"], round(a["cut"].length, 1), road_w, left, right,
                               sum(x[0] in ("in", "both") for x in lanes), sum(x[0] in ("out", "both") for x in lanes), round(wl, 2), src))
        else:   # a subsection: its road (and a parallel one it carries) in lanes, crossings, the pedestrian realm
            line = sub_of.get(uid, (None, None))[1]
            own = [e for e in (rtree_ids[k] for k in rtree.query(U)) if roads[e]["level"] == level and roads[e]["g"].intersection(U).length > 1.0]
            lines, halves = {}, {}
            for e in sorted(own, key=lambda e: -roads[e]["g"].intersection(U).length):
                ln, lx = line_in(roads[e], U), line_in(roads[e], U, pad=BAND_PAD_M)
                if ln is None:
                    continue
                if line is not None and line.project(shapely.Point(ln.coords[-1])) < line.project(shapely.Point(ln.coords[0])):
                    ln = shapely.LineString(ln.coords[::-1])   # along the subsection, so forward / backward agree on its pieces
                if lx is not None and line is not None and line.project(shapely.Point(lx.coords[-1])) < line.project(shapely.Point(lx.coords[0])):
                    lx = shapely.LineString(lx.coords[::-1])
                lines[e], halves[e] = (lx or ln), kerbs(ln, level, roads[e])      # bands run on past the unit (a slanted cut); kerbs measured inside
                hl, hr, src_ = halves[e]
                measured.setdefault(e, []).append(((hl, hr, src_) if along_own(roads[e], ln) else (hr, hl, src_)) + (U,))
            # the roadway runs kerb to kerb along each of its roads
            C = area(safe("intersection", shapely.union_all([band(lines[e], -halves[e][1], halves[e][0]) for e in lines] or [shapely.Polygon()]), U))
            taken = crossings(uid, level, U, C, list(lines.values()))
            near = [paths[k] for k in ptree.query(U)] if ptree is not None else []
            track = shapely.union_all([safe("intersection", ln.buffer(TRACK_M / 2, cap_style="flat"), U) for typ, sb, lv, ln in near
                                       if typ == "cycleway" and sb != "crossing" and lv == level] or [shapely.Polygon()])
            add(uid, level, "cycle lane", track, "measured", width=TRACK_M)
            ulanes, wls, srcs = [], [], set()
            for e, ln in lines.items():
                one = "forward" if along_own(roads[e], ln) else "backward"     # a one-way road runs the way its own geometry runs
                lanes, n_r, n_l, wl, src = lane_set(uid, level, safe("difference", C, taken), ln, roads[e], "forward", "backward",
                                                    one if roads[e]["oneway"] else "forward", half=halves[e])
                ulanes += lanes; wls.append(wl); srcs.add(src)
                nf, nb = (sum(x[0] in (d, "both") for x in lanes) for d in ("forward", "backward"))
                counts.setdefault(e, []).append(((nf, nb) if along_own(roads[e], ln) else (nb, nf)) + (wl,))   # lanes src -> dst, dst -> src
                taken = safe("union", taken, shapely.union_all([x[1] for x in lanes] or [shapely.Polygon()]))
            add(uid, level, "carriageway", safe("difference", C, taken), "measured")
            mark(uid, level, "kerb", safe("intersection", C.boundary, U.buffer(-0.05)), how="measured")
            pedestrian(uid, level, U, C)
            if line is not None and line.length > 0:     # widths across the middle
                mid = line.interpolate(0.5, normalized=True)
                tx, ty = direction(line, line.length / 2)
                cross = shapely.LineString([(mid.x + ty * 60, mid.y - tx * 60), (mid.x - ty * 60, mid.y + tx * 60)])
                inside = safe("intersection", cross, U)
                road_w, left, right = across(uid, cross, line, C, inside)
                n_f = sum(d in ("forward", "both") and not p.is_empty and p.intersects(inside) for d, p, *_ in ulanes)    # the lanes the line across meets
                n_b = sum(d in ("backward", "both") and not p.is_empty and p.intersects(inside) for d, p, *_ in ulanes)
                widths.append((uid, level, "middle", None, round(inside.length, 1), road_w, left, right, n_f, n_b,
                               round(sum(wls) / len(wls), 2) if wls else None, sorted(srcs)[0] if srcs else "estimated"))

    for u in units:
        if u[1] == "subsection":
            classic(*u)
    net = sumo_roadway()
    if net:
        for acc in (parts, marks, widths, count, claimed, arrow_tips, approach_rows):     # the measuring pass's arrows too: else they block SUMO's
            acc.clear()
        from_sumo(net)
    else:
        for u in units:
            if u[1] != "subsection":
                classic(*u)

    if reshaped:
        rdf = pd.DataFrame([(u, shapely.to_wkb(g)) for u, g in reshaped.items()], columns=["unit_id", "wkb"])
        con.execute(f"""UPDATE space.unit u SET geometry = ST_Transform(ST_GeomFromWKB(r.wkb::BLOB), '{epsg}', 'EPSG:4326', always_xy := true)
                        FROM rdf r WHERE u.unit_id = r.unit_id""")
    pdf = pd.DataFrame(parts, columns=["unit_id", "part_id", "level", "type", "arm", "direction", "lane", "width_m", "source", "method", "ref", "wkb"])
    mdf = pd.DataFrame([m for m in marks if m is not None], columns=["unit_id", "level", "type", "arm", "length_m", "source", "method", "ref", "wkb"])   # None: an arrow replaced
    wdf = pd.DataFrame(widths, columns=["unit_id", "level", "edge", "arm", "total_m", "carriageway_m", "left_m", "right_m", "lanes_in", "lanes_out",
                                        "lane_m", "source"])
    to_ll = f"ST_Transform(ST_GeomFromWKB(wkb::BLOB), '{epsg}', 'EPSG:4326', always_xy := true)"
    # a part of a road (a lane, a shoulder) takes what is known of its road (its OSM way, `ref`): name, class, speed limit, surface,
    # lighting, the road's lane count. Where OSM says nothing, a stated default: 50 km/h, the limit in built-up areas in Canada, Sweden
    # and Monaco (not on a motorway), and asphalt; each value says where it comes from
    con.execute(f"""CREATE OR REPLACE TABLE space.part AS SELECT p.unit_id, p.part_id, p.level::INT AS level, p.type, p.arm, p.direction,
                    p.lane::INT AS lane, p.width_m::DOUBLE AS width_m, p.source, p.method, p.ref::VARCHAR AS ref,
                    e.name AS road, e.class AS road_class,
                    CASE WHEN e.osm_id IS NULL THEN NULL WHEN w.tags['maxspeed'] IS NOT NULL THEN w.tags['maxspeed'] || ' (OSM)'
                         WHEN e.class LIKE 'motorway%' THEN NULL ELSE '50 km/h (default in built-up areas; not in OSM)' END AS speed,
                    CASE WHEN e.osm_id IS NULL THEN NULL WHEN w.tags['surface'] IS NOT NULL THEN w.tags['surface'] || ' (OSM)'
                         ELSE 'asphalt (assumed; not in OSM)' END AS surface,
                    CASE WHEN e.osm_id IS NOT NULL THEN coalesce(w.tags['lit'], 'not in OSM') END AS lit,
                    w.tags['lanes'] AS road_lanes, CASE WHEN e.osm_id IS NOT NULL THEN coalesce(w.tags['oneway'], 'no') END AS oneway,
                    ST_CollectionExtract(ST_MakeValid({to_ll}), 3) AS geometry
                    FROM pdf p
                    LEFT JOIN (SELECT osm_id, any_value(name) AS name, any_value(class) AS class FROM space.element WHERE type = 'road' GROUP BY osm_id) e
                      ON p.ref = 'w' || e.osm_id
                    LEFT JOIN osm.raw.ways w ON w.osm_id = e.osm_id""")
    con.execute(f"""CREATE OR REPLACE TABLE space.mark AS SELECT unit_id, level::INT AS level, type, arm, length_m, source, method, ref::VARCHAR AS ref,
                    {to_ll} AS geometry FROM mdf""")
    con.execute("CREATE OR REPLACE TABLE space.width AS SELECT * FROM wdf")
    adf = pd.DataFrame(approach_rows, columns=["unit_id", "level", "from_edge", "lane", "moves", "ways", "arrow", "no_arrow_because"])
    con.execute("""CREATE OR REPLACE TABLE space.approach AS SELECT unit_id::VARCHAR AS unit_id, level::INT AS level, from_edge::VARCHAR AS from_edge,
                   lane::INT AS lane, moves::INT AS moves, ways::VARCHAR AS ways, arrow::BOOLEAN AS arrow, no_arrow_because::VARCHAR AS no_arrow_because
                   FROM adf""")
    tdf = pd.DataFrame(turn_rows, columns=["unit_id", "level", "from_edge", "from_lane", "to_edge", "to_lane", "turn", "source", "vehicles", "condition", "wkb"])
    con.execute(f"""CREATE OR REPLACE TABLE space.turn AS SELECT unit_id::VARCHAR AS unit_id, level::INT AS level, from_edge::VARCHAR AS from_edge,
                    from_lane::INT AS from_lane, to_edge::VARCHAR AS to_edge, to_lane::INT AS to_lane, turn::VARCHAR AS turn, source::VARCHAR AS source,
                    vehicles::VARCHAR AS vehicles,   -- NULL: open to all traffic; else the classes it is open to, e.g. bus,taxi
                    condition::VARCHAR AS condition, -- when a time rule binds (OSM restriction:conditional), e.g. Mo-Su 07:00-19:00
                    {to_ll} AS geometry FROM tdf""")
