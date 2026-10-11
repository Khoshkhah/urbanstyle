"""A bridge profile (docs/design/bridge-profile.md): one JSON file per bridge with its deck outline, its road axes, the height of the
deck along each axis, the lanes and paths across it (bands, from duckOSM's GMNS export) and its piers. Each value has its source and
method. `bridge3d.model` draws the 3D model from the file only.

    urbanstyle bridge profile OSM_DB GMNS_DB (NAME | --all) OUT_DIR
"""
import json
import re

FORMAT = "urbanstyle.bridge/1"
# urbanstyle's own values (chosen): no source gives them yet (LiDAR and the aerial photo will measure them)
GRADE = 0.05        # the deck rises 5 m in 100 m from where its roads meet a ground road
TOP_M = 27.0        # the deck at most this high above the ground at its ends
DECK_M = 1.8        # deck and girders, thick
RAIL_M = 1.1        # parapet height
PIER_M = 50.0       # a pier every, along the longest axis
PIER_MIN_M = 3.0    # no pier under a deck lower than this
PIER_W = 1.5        # a pier's thickness along the axis
PATH_W = {"cycleway": 3.0, "footway": 2.0, "path": 2.0, "pedestrian": 3.0}
STEP_M = 10.0       # the vertical profile is sampled this often (then collinear points are dropped)
ON_DECK = 0.6       # a road way is on the deck when this share of it lies within 5 m of the outline
PATHS = ("cycleway", "footway", "path", "pedestrian")
PATH_REACH_M = 25.0  # a path this near the axis, parallel to it (PARALLEL: the cosine of the angle), is a band of its section
PARALLEL = 0.9


def _val(value, source, method):
    return {"value": value, "source": source, "method": method}


def _slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def profiles(osm_db, gmns_db, name=None):
    """The profiles of the bridge called ``name`` (``man_made=bridge`` with that name), or of every road bridge when ``name`` is None:
    each outline with road ways on it, and each connected group of road ways with ``bridge=*`` outside every outline."""
    import duckdb
    import pyproj
    import shapely

    o = duckdb.connect(osm_db, read_only=True)
    g = duckdb.connect(gmns_db, read_only=True)
    g.execute("LOAD spatial")
    lon0, lat0 = o.execute("SELECT avg(lon), avg(lat) FROM raw.nodes").fetchone()
    epsg = (32600 if lat0 >= 0 else 32700) + int((lon0 + 180) // 6) + 1
    tr = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True).transform
    ways = o.execute("""SELECT osm_id, refs, tags FROM raw.ways WHERE tags['highway'] IS NOT NULL
                        AND coalesce(tags['bridge'], 'no') <> 'no'""").fetchall()
    outl = o.execute("SELECT osm_id, refs, tags FROM raw.ways WHERE tags['man_made'] = 'bridge'"
                     + (" AND tags['name'] = ?" if name else ""), [name] if name else []).fetchall()
    if name and not outl:
        raise ValueError(f"no man_made=bridge named {name!r} in {osm_db}")
    refs = {r for _, rs, _ in ways + outl for r in rs}
    pts = {i: tr(x, y) for i, y, x in o.execute(f"SELECT osm_id, lat, lon FROM raw.nodes WHERE osm_id IN "
                                                 f"(SELECT unnest(?::BIGINT[]))", [sorted(refs)]).fetchall()}
    ground = {r for (r,) in o.execute("""SELECT DISTINCT unnest(refs) FROM raw.ways WHERE tags['highway'] IS NOT NULL
                                         AND coalesce(tags['bridge'], 'no') = 'no'""").fetchall()}
    lines = {oid: (shapely.LineString([pts[r] for r in rs]), rs, dict(t)) for oid, rs, t in ways
             if len(rs) >= 2 and all(r in pts for r in rs)}
    found, used = [], set()
    for oid, rs, t in sorted(outl, key=lambda r: -len(r[1])):
        if len(rs) < 4 or any(r not in pts for r in rs):
            continue
        deck = shapely.make_valid(shapely.Polygon([pts[r] for r in rs]))
        deck = max(shapely.get_parts(deck), key=lambda p: p.area)
        near = deck.buffer(5.0)
        on = [w for w, (ln, _, tg) in lines.items() if w not in used and ln.intersection(near).length > ON_DECK * ln.length]
        if any(lines[w][2]["highway"] not in PATHS for w in on):
            used |= set(on)
            found.append((dict(t).get("name") or f"bridge w{oid}", deck, _val([[round(x, 2), round(y, 2)] for x, y in deck.exterior.coords],
                          f"osm w{oid} (man_made=bridge)", "mapped"), on))
    if not name:        # road bridges with no outline: the connected groups of the bridge ways left
        left = [w for w in lines if w not in used]
        group = {w: w for w in left}

        def root(w):
            while group[w] != w:
                group[w] = group[group[w]]
                w = group[w]
            return w
        at = {}
        for w in left:
            for r in lines[w][1]:
                if r in at:
                    group[root(w)] = root(at[r])
                at[r] = w
        groups = {}
        for w in left:
            groups.setdefault(root(w), []).append(w)
        for ws in groups.values():
            if any(lines[w][2]["highway"] not in PATHS for w in ws):
                nm = next((lines[w][2].get("name") for w in ws if lines[w][2].get("name")), None)
                found.append((nm or f"bridge w{min(ws)}", None, None, ws))
    names = {}
    out = []
    for nm, deck, outline, on in found:
        n = names[nm] = names.get(nm, 0) + 1
        out.append(_profile(g, tr, nm if n == 1 else f"{nm} {n}", epsg, deck, outline, on, lines, pts, ground, osm_db, gmns_db))
    return out


def _profile(g, tr, name, epsg, deck, outline, on, lines, pts, ground, osm_db, gmns_db):
    import datetime

    import shapely
    import shapely.ops
    from shapely import wkt as _w

    roads = [w for w in on if lines[w][2]["highway"] not in PATHS]
    paths = [w for w in on if lines[w][2]["highway"] in PATHS]
    merged = shapely.line_merge(shapely.union_all([lines[w][0] for w in roads]))
    parts = sorted(shapely.get_parts(merged), key=lambda a: -a.length)
    ends = [shapely.Point(pts[r]) for w in roads for r in lines[w][1] if r in ground]
    grounded = shapely.MultiPoint(ends)
    if not ends:        # no road on it meets a ground road: the ends of its longest axis
        ends = [shapely.Point(parts[0].coords[0]), shapely.Point(parts[0].coords[-1])]
    ends = shapely.MultiPoint(ends)
    # the GMNS links of the road ways, their lanes
    utm = lambda wkt: shapely.ops.transform(tr, _w.loads(wkt))      # GMNS is in lon/lat
    links = g.execute("""SELECT link_id, osm_id, ST_AsText(geom) FROM gmns_driving.link
                         WHERE osm_id IN (SELECT unnest(?::BIGINT[]))""", [roads]).fetchall()
    lanes = {}
    for lane_id, lk, num, use, width, turn, gw, gc in g.execute("""SELECT lane_id, link_id, lane_num, allowed_uses, width, turn, ST_AsText(geom),
            ST_AsText(geom_cut) FROM gmns_driving.lane WHERE link_id IN (SELECT unnest(?::BIGINT[])) AND geom IS NOT NULL""",
            [[r[0] for r in links]]).fetchall():
        lanes.setdefault(lk, []).append((lane_id, num, use, width, turn, utm(gw), utm(gc) if gc else None))
    # SUMO's paths from lane to lane through each junction on the deck (GMNS lane_connector: both lanes on the bridge's links)
    on_deck = {lid for ls in lanes.values() for lid, *_ in ls}
    connectors = [{"id": cid, "from": fl, "to": tl, "width": _val(round(w, 2), "duckOSM GMNS (SUMO's internal lane)", "derived"),
                   "line": [[round(x, 2), round(y, 2)] for x, y in utm(gw).coords], "source": "sumo, via duckOSM GMNS lane_connector",
                   "method": "derived"}
                  for cid, fl, tl, w, gw in g.execute("""SELECT connector_id, from_lane_id, to_lane_id, width, ST_AsText(geom)
                      FROM gmns_driving.lane_connector WHERE from_lane_id IN (SELECT unnest(?::VARCHAR[]))
                      AND to_lane_id IN (SELECT unnest(?::VARCHAR[])) AND geom IS NOT NULL""", [sorted(on_deck), sorted(on_deck)]).fetchall()]
    tr_link = {lk: (osm, utm(gw)) for lk, osm, gw in links}
    axes = []
    for k, ax in enumerate(parts):
        ways = sorted((w for w in roads if lines[w][0].intersection(ax.buffer(0.5)).length > 0.9 * lines[w][0].length),
                      key=lambda w: ax.project(lines[w][0].interpolate(0.5, normalized=True)))
        if not ways:
            continue
        L = ax.length
        zs = [(s, min(TOP_M, GRADE * ends.distance(ax.interpolate(s)))) for s in [i * STEP_M for i in range(int(L // STEP_M) + 1)] + [L]]
        axes.append({"id": f"a{k + 1}", "ways": [f"w{w}" for w in ways],
                     "line": _val([[round(x, 2), round(y, 2)] for x, y in ax.coords], "osm: " + ", ".join(f"w{w}" for w in ways), "mapped"),
                     "length_m": round(L, 2),
                     "ends": [{"s": s, "ground": not grounded.is_empty and grounded.distance(p) < 0.5, "node": next(
                         (f"n{r}" for w in ways for r in lines[w][1] if shapely.Point(pts[r]).distance(p) < 0.05), None)}
                         for s, p in ((0.0, shapely.Point(ax.coords[0])), (round(L, 2), shapely.Point(ax.coords[-1])))],
                     "vertical": {"points": _collinear_out([[round(s, 2), round(z, 2)] for s, z in zs]), "source": "urbanstyle",
                                  "method": "chosen", "rule": f"{GRADE:.0%} up from the nearest end where a road on it meets a ground road, "
                                                              f"at most {TOP_M} m"},
                     "sections": _sections(ax, ways, tr_link, lanes, paths, lines, parts)})
    piers = []
    if axes:
        ax = parts[0]
        vert = axes[0]["vertical"]["points"]
        s = PIER_M / 2
        while s < ax.length:
            if _z(vert, s) - DECK_M >= PIER_MIN_M:
                piers.append({"axis": axes[0]["id"], "s": round(s, 2), "width": PIER_W, "source": "urbanstyle", "method": "chosen",
                              "rule": f"every {PIER_M} m along the longest axis, where the deck is {PIER_MIN_M} m or more above the ground"})
            s += PIER_M
    if outline is None:     # no OSM outline: the sections, each as wide as its bands
        polys = []
        for a, ax in zip(axes, parts):
            for sec in a["sections"]:
                if sec["bands"]:
                    lo = min(b["t"] - b["width"]["value"] / 2 for b in sec["bands"])
                    hi = max(b["t"] + b["width"]["value"] / 2 for b in sec["bands"])
                    piece = shapely.ops.substring(ax, sec["s0"], sec["s1"])
                    polys.append(shapely.Polygon(list(piece.offset_curve(hi).coords) + list(piece.offset_curve(lo).coords)[::-1]).buffer(0))
        deck = shapely.union_all(polys) if polys else merged.buffer(4)
        deck = max(shapely.get_parts(deck), key=lambda p: p.area)
        outline = _val([[round(x, 2), round(y, 2)] for x, y in deck.exterior.coords], "urbanstyle: the sections, each as wide as its bands",
                       "derived")
    # the paths on the deck that are no band of an axis (they turn, cross or join): each along its own OSM line
    banded = {b["way"] for a in axes for sec in a["sections"] for b in sec["bands"] if b["type"] != "lane"}
    free = [{"way": f"w{w}", "type": "cycleway" if lines[w][2]["highway"] == "cycleway" else "footway", "name": lines[w][2].get("name"),
             "line": [[round(x, 2), round(y, 2)] for x, y in lines[w][0].coords], "width": _val(PATH_W[lines[w][2]["highway"]], "urbanstyle", "chosen"),
             "source": f"osm w{w}", "method": "mapped"} for w in paths if f"w{w}" not in banded]
    return {"format": FORMAT, "name": name, "crs": f"EPSG:{epsg}",
            "z_datum": _val("ground at the ends", "urbanstyle", "chosen"),
            "made": {"by": "urbanstyle bridge profile", "date": datetime.date.today().isoformat(), "inputs": [osm_db, gmns_db]},
            "deck": {"outline": outline, "thickness": _val(DECK_M, "urbanstyle", "chosen"), "parapet": _val(RAIL_M, "urbanstyle", "chosen")},
            "axes": axes, "connectors": connectors, "paths": free, "piers": piers}


def _collinear_out(ps, tol=0.01):
    """The points (s, z) without the ones on the straight line between their neighbours."""
    out = [ps[0]]
    for p, q in zip(ps[1:-1], ps[2:]):
        a = out[-1]
        if abs(a[1] + (q[1] - a[1]) * (p[0] - a[0]) / ((q[0] - a[0]) or 1) - p[1]) > tol:
            out.append(p)
    return out + ps[-1:] if len(ps) > 1 else out


def _z(points, s):
    """The height of a vertical profile at s, linear between its points."""
    for (s0, z0), (s1, z1) in zip(points, points[1:]):
        if s <= s1:
            return z0 + (z1 - z0) * max(0.0, s - s0) / ((s1 - s0) or 1)
    return points[-1][1]


def _offset(ax, s, geom):
    """The signed offset (left of the axis positive) of geom from the axis at s."""
    import shapely
    p = ax.interpolate(s)
    a, b = ax.interpolate(max(s - 1, 0)), ax.interpolate(min(s + 1, ax.length))
    q = shapely.ops.nearest_points(p, geom)[1]
    side = (b.x - a.x) * (q.y - p.y) - (b.y - a.y) * (q.x - p.x)
    return round((1 if side >= 0 else -1) * p.distance(q), 2)


def _sections(ax, ways, links, lanes, paths, lines, axes):
    """The axis cut where the bands change: at each end of a GMNS link along it. Each section's bands from left to right: the lanes of
    the links over its middle, and the paths beside it: within PATH_REACH_M, parallel to it, and nearer to it than to any other axis."""
    import shapely
    import shapely.ops
    width_src = {}      # the ways whose lane widths OSM gives (width:lanes)
    for w in ways:
        t = lines[w][2]
        width_src[w] = any(k.startswith("width:lanes") for k in t)
    mine = [(lk, osm, gm) for lk, (osm, gm) in links.items() if osm in ways
            and gm.intersection(ax.buffer(1.0)).length > 0.8 * gm.length]
    cuts = sorted({0.0, round(ax.length, 2)} | {round(ax.project(shapely.Point(c)), 2) for _, _, gm in mine for c in (gm.coords[0], gm.coords[-1])})
    cuts = [c for i, c in enumerate(cuts) if i == 0 or c - cuts[i - 1] > 0.5]
    out = []
    for s0, s1 in zip(cuts, cuts[1:]):
        sm = (s0 + s1) / 2
        pm = ax.interpolate(sm)
        bands = []
        for lk, osm, gm in mine:
            a, b = ax.project(shapely.Point(gm.coords[0])), ax.project(shapely.Point(gm.coords[-1]))
            if not min(a, b) - 0.01 <= sm <= max(a, b) + 0.01:
                continue
            d = "forward" if b > a else "backward"
            src, how = _lane_count(lines[osm][2])
            for lane_id, num, use, width, turn, lg, cut in lanes.get(lk, []):
                # where SUMO ends the lane at a junction (GMNS geom_cut): the band stops there, a connector goes on
                ca, cb = sorted((ax.project(shapely.Point(cut.coords[0])), ax.project(shapely.Point(cut.coords[-1])))) if cut else (s0, s1)
                bands.append({"type": "lane", "lane_id": lane_id, "link": str(lk), "way": f"w{osm}", "direction": d, "lane": num, "use": use,
                              "turn": turn, "t": _offset(ax, sm, lg), "source": src, "method": how,
                              "s_from": round(max(s0, ca), 2), "s_to": round(min(s1, cb), 2),
                              "width": _val(width, "osm width:lanes" if width_src.get(osm) else "duckOSM GMNS (road class)",
                                            "mapped" if width_src.get(osm) else "chosen")})
        for w in paths:
            ln = lines[w][0]
            q = shapely.ops.nearest_points(pm, ln)[1]
            if pm.distance(q) > PATH_REACH_M or min(axes, key=lambda x: x.distance(q)) is not ax or abs(_cos(ax, sm, ln, q)) < PARALLEL:
                continue
            hw = lines[w][2]["highway"]
            bands.append({"type": "cycleway" if hw == "cycleway" else "footway", "way": f"w{w}", "name": lines[w][2].get("name"),
                          "t": _offset(ax, sm, ln), "source": f"osm w{w}", "method": "mapped",
                          "width": _val(PATH_W[hw], "urbanstyle", "chosen")})
        bands.sort(key=lambda b: -b["t"])
        out.append({"s0": s0, "s1": s1, "links": sorted({b["link"] for b in bands if "link" in b}), "bands": bands})
    return out


def _cos(ax, s, ln, q):
    """The cosine of the angle between the axis at s and the line ln at its point q."""
    a, b = ax.interpolate(max(s - 1, 0)), ax.interpolate(min(s + 1, ax.length))
    d = ln.project(q)
    c, e = ln.interpolate(max(d - 1, 0)), ln.interpolate(min(d + 1, ln.length))
    u, v = (b.x - a.x, b.y - a.y), (e.x - c.x, e.y - c.y)
    return (u[0] * v[0] + u[1] * v[1]) / ((u[0] ** 2 + u[1] ** 2) ** .5 * (v[0] ** 2 + v[1] ** 2) ** .5 or 1)


def _lane_count(tags):
    """Where a way's lanes in each direction come from: OSM's tags, or GMNS where OSM does not say."""
    if "lanes" not in tags:
        return "duckOSM GMNS: no lanes tag, one lane each way", "chosen"
    if tags.get("oneway") in ("yes", "-1") or {"lanes:forward", "lanes:backward"} & set(tags):
        return "osm lanes" + (", lanes:forward, lanes:backward" if "lanes:forward" in tags else ""), "mapped"
    return "osm lanes; duckOSM GMNS divides them between the two directions", "derived"


def write(osm_db, gmns_db, name, out_dir):
    """Write one <slug>.bridge.json per bridge into out_dir; returns the paths."""
    import os
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for p in profiles(osm_db, gmns_db, name):
        path = os.path.join(out_dir, f"{_slug(p['name'])}.bridge.json")
        with open(path, "w") as f:
            json.dump(p, f, indent=1)
        paths.append(path)
    return paths
