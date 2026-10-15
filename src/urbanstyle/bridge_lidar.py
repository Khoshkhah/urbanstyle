"""A bridge's heights measured from airborne LiDAR (docs/design/bridge-profile.md, "Heights from LiDAR"): rule 6 of the profile, a
script that replaces a chosen value with a measured one and says so.

    urbanstyle bridge-measure PROFILE OUT --lidar TILE.parquet [TILE.parquet ...]

Every STEP_M along each axis: the deck top is a low quantile of the returns inside the axis's lane bands (vegetation, water and noise
left out; where gaps of GAP_M or more split them, only the cluster with the most returns: the deck, not the water or the street under it
seen past its edge, not a lamp post on it; cars on the deck stay above the quantile); the ground is the median of the ground and water returns within GROUND_R_M. The vertical
profile is the deck top above that ground (the dashboard's map is flat: its ground is z = 0). Where the window holds fewer than MIN_PTS
returns, the chosen value stays and the profile says where. Needs ducklidar (the conda env `lidar`): the tiles are its Parquet sidecars.
"""
import json
import math

STEP_M = 10.0       # a station every this along each axis
HALF_M = 5.0        # the window runs this far along the axis each side of the station
GAP_M = 2.0         # a vertical gap this wide splits the deck from what lies under it
DECK_Q = 0.25       # the deck top: this quantile of the returns above the gap (cars on the deck lie above it)
GROUND_R_M = 30.0   # the ground under a station: ground and water returns this near
MIN_PTS = 20        # fewer returns than this in a window: no measurement there
REF_SIGMA_M = 60.0  # the bridge's reference ground: the ground samples weighted over this (a Gaussian)
LAND_SIGMA_M = 30.0 # ... and each landing's deck, over this
LAND_W = 25.0       # ... with this weight against one ground sample, so a landing is at 0
LAND_TAPER_M = 60.0 # a landing's last metres: the height left by the reference ground goes to 0 over this
EXT_MAX_M = 150.0   # a ramp runs on along the road that continues it to the next junction, at most this far
CLOSE_M = 3.0       # a landing's deck is closed across gaps narrower than twice this
PATH_NEAR_M = 4.0   # a landing takes OSM's paths along it this far beyond its lanes
NEAR_M = 12.0       # ... a junction of other roads this near beside it counts too (the ramp passes between two, e.g. Fir Street x W 8th)
NOT_ROADS = ("footway", "cycleway", "path", "steps", "pedestrian", "track", "corridor", "bridleway", "construction", "proposed",
             "elevator", "platform", "service")     # a way of these does not make a junction (a driveway, an alley: blocks.py's too)
SKIP = (3, 4, 5, 7, 9, 18)      # ASPRS low, medium, high vegetation, low noise, water, high noise: not the deck
GROUND = (2, 9)                 # ground, water


def deck_top(z):
    """The deck top from the heights of the returns in one window: the returns split at every vertical gap of GAP_M or more, the
    cluster with the most returns (the deck, seen from above; not the street or the water under it, not a lamp post on it), its DECK_Q
    quantile."""
    import numpy as np
    z = np.sort(np.asarray(z, dtype=float))
    if len(z) < MIN_PTS:
        return None
    cuts = np.flatnonzero(np.diff(z) >= GAP_M) + 1
    z = max(np.split(z, cuts), key=len)
    return float(np.quantile(z, DECK_Q))


def _sample(dl, tiles, x, y, ux, uy, lo, hi):
    """(deck top, ground, returns in the window) at (x, y) on an axis of direction (ux, uy), the deck's bands from lo to hi across it; a
    height is None where the window holds fewer than MIN_PTS returns."""
    import numpy as np
    r = max(GROUND_R_M, HALF_M + max(abs(lo), abs(hi)))
    d = dl.read(tiles, (x - r, y - r, x + r, y + r))
    dx, dy = d["x"] - x, d["y"] - y
    along, across = dx * ux + dy * uy, -dx * uy + dy * ux       # across: + left, as the profile's t
    cls = d["classification"]
    win = (np.abs(along) <= HALF_M) & (across >= lo) & (across <= hi) & ~np.isin(cls, SKIP)
    gnd = np.isin(cls, GROUND) & (dx * dx + dy * dy <= GROUND_R_M ** 2)
    return deck_top(d["z"][win]), (float(np.median(d["z"][gnd])) if gnd.sum() >= MIN_PTS else None), int(win.sum())


def _bands_at(a, s):
    """The lane bands' extent across the axis at s: (right edge, left edge)."""
    sec = next((x for x in a["sections"] if x["s0"] - 0.01 <= s <= x["s1"] + 0.01), a["sections"][-1] if a["sections"] else None)
    bands = [b for b in (sec["bands"] if sec else []) if b["type"] == "lane"] or (sec["bands"] if sec else [])
    return (min((b["t"] - b["width"]["value"] / 2 for b in bands), default=-3.0),
            max((b["t"] + b["width"]["value"] / 2 for b in bands), default=3.0))


def _shift(a, d):
    """Every s of axis a moved by d (a piece added before its start)."""
    for sec in a["sections"]:
        sec["s0"], sec["s1"] = round(sec["s0"] + d, 2), round(sec["s1"] + d, 2)
        for b in sec["bands"]:
            for k in ("s_from", "s_to"):
                if k in b:
                    b[k] = round(b[k] + d, 2)
    for e in a["ends"]:
        e["s"] = round(e["s"] + d, 2) if e["s"] else 0.0


from .bridge_profile import PATH_W, SHARED_W      # noqa: E402  (the paths' chosen widths, as on the bridge)


def measure(profile, tiles, survey="City of Vancouver LiDAR 2022", osm_db=None):
    """The profile with each axis's vertical points measured where the LiDAR has returns (a new dict; `profile` is not changed):
    - the footprint is OSM's, the LiDAR gives heights only: where an axis's OSM bridge way ends on the ground, the ramp runs on (on
      fill) along the OSM road that continues it to the next junction (at most EXT_MAX_M; needs osm_db);
    - each height is the measured deck (in the survey's datum) above one reference ground for the whole bridge: the measured ground
      samples weighted over REF_SIGMA_M and pinned to the deck at every landing, so the deck stays as smooth as measured (the ground
      under it jumps: a street, an island, the water) and every landing is at 0 on the flat map."""
    import copy

    import ducklidar as dl
    import numpy as np
    import pyproj
    import shapely
    import shapely.ops
    from .bridge_profile import _z

    P = copy.deepcopy(profile)
    # ponytail: NAD83(CSRS) and WGS84 taken as one (no grid shift): about 1 m sideways, less than a lane; add a grid when it matters
    to_l = pyproj.Transformer.from_crs(P["crs"], "EPSG:26910", always_xy=True).transform
    to_ll_ = pyproj.Transformer.from_crs("EPSG:26910", "EPSG:4326", always_xy=True).transform     # the survey's frame to lon / lat
    unit = lambda ln, s: (lambda a0, b0: (lambda h: ((b0.x - a0.x) / h, (b0.y - a0.y) / h))(
        ((b0.x - a0.x) ** 2 + (b0.y - a0.y) ** 2) ** .5 or 1))(ln.interpolate(max(s - 1, 0)), ln.interpolate(min(s + 1, ln.length)))
    osm = None
    if osm_db:
        import duckdb
        osm = duckdb.connect(osm_db, read_only=True)
        from_ll = pyproj.Transformer.from_crs("EPSG:4326", P["crs"], always_xy=True).transform
    meas = {}       # axis id -> [(s, x, y, top, ground, n)] in the survey's frame
    for a in P["axes"]:
        ax = shapely.LineString([to_l(x, y) for x, y in a["line"]["value"]])
        rows = []
        for k in range(int(ax.length // STEP_M) + 1):
            s = min(k * STEP_M, ax.length)
            p = ax.interpolate(s)
            top, ground, n = _sample(dl, tiles, p.x, p.y, *unit(ax, s), *_bands_at(a, s))
            rows.append((s, p.x, p.y, top, ground, n))
        if ax.length - rows[-1][0] > 1.0:       # the last station at the very end
            p = ax.interpolate(ax.length)
            rows.append((ax.length, p.x, p.y, *_sample(dl, tiles, p.x, p.y, *unit(ax, ax.length), *_bands_at(a, ax.length))))
        # the footprint is OSM's, the LiDAR gives heights only: where OSM's bridge way ends, the ramp runs on (on fill) along the OSM road
        # that continues it, to the next junction (a node where another road meets it)
        for e in (0, 1):
            end = a["ends"][e]
            if osm is None or not end.get("ground") or not end.get("node"):
                continue
            node = int(end["node"][1:])
            if len([w_ for (w_,) in osm.execute("SELECT osm_id FROM raw.ways WHERE list_contains(refs, ?) AND tags['highway'] IS NOT NULL "
                                                 "AND tags['highway'] NOT IN (SELECT unnest(?::VARCHAR[]))", [node, list(NOT_ROADS)]).fetchall()
                    if f"w{w_}" not in a["ways"]]) >= 2:
                continue            # the bridge way ends at a junction already
            out = ax.coords[-1] if e else ax.coords[0]
            back = ax.interpolate(ax.length - 5.0 if e else 5.0)
            ox, oy = out[0] - back.x, out[1] - back.y
            # the OSM roads that continue it, way after way (a landing can lie past the end of the first), up to EXT_MAX_M
            chain, wids, starts, nd, dx_, dy_ = [], [], [], node, ox, oy      # starts: where each way begins along the chain
            while sum(math.dist(p_, q_) for p_, q_ in zip(chain, chain[1:])) < EXT_MAX_M:
                best = None
                for wid, refs in osm.execute("SELECT osm_id, refs FROM raw.ways WHERE tags['highway'] IS NOT NULL AND list_contains(refs, ?)",
                                             [nd]).fetchall():
                    if f"w{wid}" in a["ways"] or wid in wids:
                        continue
                    ll = dict(((i, (x, y)) for i, y, x in osm.execute("SELECT osm_id, lat, lon FROM raw.nodes WHERE osm_id IN (SELECT unnest(?::BIGINT[]))",
                                                                       [refs]).fetchall()))
                    k = refs.index(nd)
                    rs = refs[k:] if k < len(refs) - 1 else refs[:k + 1][::-1]      # away from the node
                    pts = [to_l(*from_ll(*ll[r])) for r in rs if r in ll]
                    if len(pts) < 2:
                        continue
                    cos = ((pts[1][0] - pts[0][0]) * dx_ + (pts[1][1] - pts[0][1]) * dy_) / (math.dist(pts[0], pts[1]) * math.hypot(dx_, dy_) or 1)
                    if cos > 0.7 and (best is None or cos > best[0]):
                        best = (cos, wid, pts, rs)
                if best is None:
                    break
                _, wid, pts, rs_ = best
                # the first node of the way (after its start) where another road meets it: the junction, the ramp's end
                k_ = next((i for i, r in enumerate(rs_[1:], 1) if osm.execute(
                    "SELECT count(*) FROM raw.ways WHERE list_contains(refs, ?) AND osm_id <> ? AND tags['highway'] IS NOT NULL "
                    "AND tags['highway'] NOT IN (SELECT unnest(?::VARCHAR[]))", [r, wid, list(NOT_ROADS)]).fetchone()[0]), None)
                wids.append(wid)
                starts.append(sum(math.dist(p_, q_) for p_, q_ in zip(chain, chain[1:])))
                pts = pts[:k_ + 1] if k_ is not None else pts
                chain = chain + (pts if not chain else pts[1:])
                dx_, dy_ = chain[-1][0] - chain[-2][0], chain[-1][1] - chain[-2][1]
                nd = rs_[-1]
                if k_ is not None:
                    nd = rs_[k_]
                    break
            if len(chain) < 2:
                continue
            road = shapely.LineString(chain)
            lo, hi = _bands_at(a, ax.length if e else 0.0)
            # it ends where the junction space begins: before each junction node on it or within NEAR_M beside it, by the crossing
            # street's half right-of-way (blocks.HALF_ROW) and the junction's reach into each arm (division.ARM_M), as the street is cut
            from .blocks import HALF_ROW
            from .network import ARM_M
            bx0, by0, bx1, by1 = road.buffer(NEAR_M).bounds
            (lo0, la0), (lo1, la1) = to_ll_(bx0, by0), to_ll_(bx1, by1)
            reach = min(road.length, EXT_MAX_M)
            for nid, lat, lon in osm.execute("SELECT osm_id, lat, lon FROM raw.nodes WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
                                             [min(la0, la1), max(la0, la1), min(lo0, lo1), max(lo0, lo1)]).fetchall():
                q = shapely.Point(to_l(*from_ll(lon, lat)))
                if road.distance(q) > NEAR_M:
                    continue
                others = [(w_, t_, r_) for w_, t_, r_ in osm.execute(
                    "SELECT osm_id, tags['highway'], refs FROM raw.ways WHERE list_contains(refs, ?) AND tags['highway'] IS NOT NULL "
                    "AND tags['highway'] NOT IN (SELECT unnest(?::VARCHAR[]))", [nid, list(NOT_ROADS)]).fetchall()
                    if w_ not in wids and f"w{w_}" not in a["ways"]]
                if len(others) < (1 if road.distance(q) < 0.5 else 2):      # a junction: another road meets the ramp's road, or two meet
                    continue
                sq = road.project(q)
                ux, uy = unit(road, sq)
                # the crossing street: the other road there that runs most across the ramp
                def across_(r_):
                    k = r_.index(nid)
                    nb = r_[k + 1] if k + 1 < len(r_) else r_[k - 1]
                    ll_ = osm.execute("SELECT lat, lon FROM raw.nodes WHERE osm_id = ?", [nb]).fetchone()
                    if ll_ is None:
                        return 0.0
                    px, py = to_l(*from_ll(ll_[1], ll_[0]))
                    h_ = math.hypot(px - q.x, py - q.y) or 1
                    return abs((px - q.x) / h_ * uy - (py - q.y) / h_ * ux)
                cls = max(others, key=lambda o_: across_(o_[2]))[1]
                reach = min(reach, sq - HALF_ROW.get(cls.replace("_link", ""), 10) - ARM_M)
            if reach < 1.0:
                continue
            wid = "+w".join(str(w_) for w_, s_ in zip(wids, starts) if s_ < reach)      # the ways the landing reaches
            piece = shapely.ops.substring(road, 0, reach)
            land_end_ = "end" if e else "start"
            ext = [to_back for to_back in piece.coords][1:]
            back_ll = pyproj.Transformer.from_crs("EPSG:26910", P["crs"], always_xy=True).transform
            ext_p = [[round(c, 2) for c in back_ll(x, y)] for x, y in ext]
            # the sidewalks and cycle paths along the landing (OSM's, at ground level: no bridge tag) go on with it: the bridge's paths
            # stopped where OSM's bridge way stops, and the landing had none
            pc = shapely.LineString([a["line"]["value"][-1 if e else 0]] + ext_p)
            reach_p = max(abs(lo), abs(hi))
            side_r = {1: reach_p, -1: reach_p}      # how far the deck reaches on each side of the landing's line (its paths' far edge)
            have = {f["way"] for f in P.get("paths", [])}
            bb = shapely.LineString([to_ll_(*to_l(x, y)) for x, y in pc.coords]).buffer(0.0003).bounds
            near_n = [n for (n,) in osm.execute("SELECT osm_id FROM raw.nodes WHERE lon BETWEEN ? AND ? AND lat BETWEEN ? AND ?",
                                                 [bb[0], bb[2], bb[1], bb[3]]).fetchall()]
            for wid_p, t_p, rs_p in osm.execute(
                    """SELECT osm_id, tags, refs FROM raw.ways WHERE tags['highway'] IN ('footway', 'cycleway', 'path')
                       AND coalesce(tags['footway'], '') <> 'crossing' AND coalesce(tags['cycleway'], '') <> 'crossing'
                       AND list_has_any(refs, ?::BIGINT[])""", [near_n]).fetchall():
                ll_p = dict(((i, (x, y)) for i, y, x in osm.execute("SELECT osm_id, lat, lon FROM raw.nodes WHERE osm_id IN (SELECT unnest(?::BIGINT[]))",
                                                                     [rs_p]).fetchall()))
                gp = shapely.LineString([from_ll(*ll_p[r]) for r in rs_p if r in ll_p]) if sum(r in ll_p for r in rs_p) > 1 else None
                if gp is None or f"w{wid_p}" in have:
                    continue
                gp = gp.intersection(pc.buffer(reach_p + PATH_NEAR_M, cap_style="flat"))
                for piece_p in shapely.get_parts(gp):
                    if piece_p.geom_type != "LineString" or piece_p.length < 5.0:
                        continue
                    (ax_, ay_), (bx_, by_) = piece_p.coords[0], piece_p.coords[-1]
                    q0, q1 = pc.interpolate(pc.project(shapely.Point(ax_, ay_))), pc.interpolate(pc.project(shapely.Point(bx_, by_)))
                    if math.hypot(q1.x - q0.x, q1.y - q0.y) < 0.8 * piece_p.length:
                        continue        # (not along the landing: a crossing or a path that leaves it)
                    hw = t_p.get("highway")
                    shared = t_p.get("foot") == "designated" and t_p.get("bicycle") == "designated"
                    P.setdefault("paths", []).append({
                        "way": f"w{wid_p}", "type": "shared path" if shared else "cycleway" if hw == "cycleway" else "footway",
                        "name": t_p.get("name"), "line": [[round(x, 2), round(y, 2)] for x, y in piece_p.coords],
                        "width": {"value": SHARED_W if shared else PATH_W.get(hw, 2.0), "source": "urbanstyle", "method": "chosen"},
                        "source": f"osm w{wid_p}", "method": "mapped", "footway": t_p.get("footway"), "crossing": None, "markings": None,
                        "foot": t_p.get("foot"), "bicycle": t_p.get("bicycle"), "segregated": t_p.get("segregated"), "cycleway": t_p.get("cycleway"),
                        "landing": f"{a['id']} {land_end_}"})
                    mp = piece_p.interpolate(0.5, normalized=True)
                    sm_ = pc.project(mp)
                    ta, tb = pc.interpolate(max(sm_ - 1, 0)), pc.interpolate(min(sm_ + 1, pc.length))
                    sd = 1 if (tb.x - ta.x) * (mp.y - ta.y) - (tb.y - ta.y) * (mp.x - ta.x) > 0 else -1
                    side_r[sd] = max(side_r[sd], piece_p.distance(pc) + 0.5 * (SHARED_W if shared else PATH_W.get(hw, 2.0)) + 0.3)
            # the deck goes on under it: the outline grows by the piece, as wide as the lanes and paths there (OSM's outline stops where
            # OSM's bridge way stops, so the measured landing had lanes and no deck)
            corridor = shapely.union_all([pc.buffer(side_r[1], cap_style="flat", single_sided=True),
                                          pc.buffer(-side_r[-1], cap_style="flat", single_sided=True)])
            # (a one-sided buffer leaves a wedge open on the outside of each bend of the line: the deck, its sidewalk and its guard had a
            # gap at each one; closed here, the ends kept square)
            corridor = corridor.buffer(CLOSE_M, join_style="mitre").buffer(-CLOSE_M, join_style="mitre").intersection(
                pc.buffer(max(side_r.values()) + 0.01, cap_style="flat"))
            grown = shapely.union_all([shapely.Polygon(P["deck"]["outline"]["value"]).buffer(0), corridor])
            grown = max(shapely.get_parts(grown), key=lambda g_: g_.area)
            P["deck"]["outline"]["value"] = [[round(x, 2), round(y, 2)] for x, y in grown.exterior.coords]
            if "measured landings" not in P["deck"]["outline"]["source"]:
                P["deck"]["outline"]["source"] += "; urbanstyle: the measured landings, as wide as their lanes"
                P["deck"]["outline"]["method"] += "+derived"
            # the landing is a section of its own: the bridge's lanes going on, on the OSM way it follows (a correction of that way's
            # lane count then applies to it: ramp a2 has 1 lane on the bridge, 2 on its landing w473319095)
            land_way = f"w{wids[0]}"
            if e:
                a["line"]["value"] += ext_p
                last = a["sections"][-1]
                old = last["s1"]
                new_sec = json.loads(json.dumps(last))
                new_sec.update(s0=old, s1=round(old + reach, 2))
                for b in new_sec["bands"]:
                    b.update(way=land_way, s_from=old, s_to=new_sec["s1"])
                a["sections"].append(new_sec)
                end["s"] = round(a["length_m"] + reach, 2)
            else:
                a["line"]["value"] = ext_p[::-1] + a["line"]["value"]
                _shift(a, reach)
                first = a["sections"][0]
                new_sec = json.loads(json.dumps(first))
                new_sec.update(s0=0.0, s1=round(reach, 2))
                for b in new_sec["bands"]:
                    b.update(way=land_way, s_from=0.0, s_to=new_sec["s1"])
                a["sections"].insert(0, new_sec)
            a["length_m"] = round(a["length_m"] + reach, 2)
            a.setdefault("landings", []).append({"end": "end" if e else "start", "way": f"w{wid}", "length_m": round(reach, 1),
                                                 "source": survey, "method": "measured",
                                                 "rule": f"OSM's bridge way ends; the road runs on (on fill) along w{wid} to where the next junction's "
                                                         f"space begins; the LiDAR measures its heights only"})
            end["node"] = None
            ax = shapely.LineString([to_l(x, y) for x, y in a["line"]["value"]])
            rows = []
            for k in range(int(ax.length // STEP_M) + 1):      # the stations again, on the longer axis
                s = min(k * STEP_M, ax.length)
                p = ax.interpolate(s)
                rows.append((s, p.x, p.y, *_sample(dl, tiles, p.x, p.y, *unit(ax, s), *_bands_at(a, s))))
            if ax.length - rows[-1][0] > 1.0:
                p = ax.interpolate(ax.length)
                rows.append((ax.length, p.x, p.y, *_sample(dl, tiles, p.x, p.y, *unit(ax, ax.length), *_bands_at(a, ax.length))))
        meas[a["id"]] = rows
    # one reference ground for the whole bridge: the ground samples over REF_SIGMA_M, pinned to the deck at every landing
    gx, gy, gz, gw = [], [], [], []
    for a in P["axes"]:
        rows = [r for r in meas[a["id"]] if r[3] is not None and r[4] is not None]
        for s, x, y, top, ground, n in rows:
            gx.append(x); gy.append(y); gz.append(ground); gw.append((1.0, REF_SIGMA_M))
        for e in (0, 1):
            if a["ends"][e].get("ground") and rows:
                s, x, y, top, ground, n = rows[-1] if e else rows[0]
                gx.append(x); gy.append(y); gz.append(top); gw.append((LAND_W, LAND_SIGMA_M))
    gx, gy, gz = np.array(gx), np.array(gy), np.array(gz)
    gwt, gsg = np.array([w for w, _ in gw]), np.array([s_ for _, s_ in gw])

    def ref(x, y):
        w = gwt * np.exp(-((gx - x) ** 2 + (gy - y) ** 2) / (2 * gsg ** 2))
        return float((w * gz).sum() / w.sum()) if w.sum() > 1e-9 else float(np.median(gz))
    n_meas = n_all = 0
    for a in P["axes"]:
        chosen = a["vertical"]["points"]
        pts, stations = [], []
        for s, x, y, top, ground, n in meas[a["id"]]:
            n_all += 1
            if top is None:
                pts.append([round(s, 2), round(_z(chosen, min(s, chosen[-1][0])), 2)])
                stations.append({"s": round(s, 2), "n": n, "method": "chosen"})
                continue
            n_meas += 1
            g0 = ref(x, y)
            pts.append([round(s, 2), round(max(top - g0, 0.0), 2)])
            stations.append({"s": round(s, 2), "n": n, "deck_m": round(top, 2), "ground_m": None if ground is None else round(ground, 2),
                             "ref_m": round(g0, 2), "method": "measured"})
        # a landing is at 0: what the reference ground leaves there goes to 0 over the last LAND_TAPER_M, smoothly (a cosine)
        L_ = pts[-1][0] if pts else 0.0
        for e in (0, 1):
            if a["ends"][e].get("ground") and pts:
                r = pts[-1][1] if e else pts[0][1]
                for q in pts:
                    d = (L_ - q[0]) if e else q[0]
                    if d < LAND_TAPER_M:
                        q[1] = round(max(q[1] - r * 0.5 * (1 + math.cos(math.pi * d / LAND_TAPER_M)), 0.0), 2)
        m_ = sum(st["method"] == "measured" for st in stations)
        a["vertical"] = {"points": pts, "curves": [], "samples": pts,
                         "source": survey if m_ else a["vertical"]["source"], "method": "derived" if m_ else "chosen",
                         "rule": f"grades and parabolic vertical curves fitted (within 0.25 m) to the deck top (the {DECK_Q:.0%} quantile of the returns in the lane bands, {2 * HALF_M:.0f} m along) above the "
                                 f"bridge's reference ground (the ground and water returns within {GROUND_R_M:.0f} m of every station, weighted over "
                                 f"{REF_SIGMA_M:.0f} m, pinned to the deck at each landing), every {STEP_M:.0f} m; {m_} of {len(stations)} stations "
                                 f"measured, the others keep the chosen value",
                         "stations": stations, "chosen_before": chosen}
    _fit_in_order(P)
    from .bridge_profile import place_piers
    P["piers"] = place_piers(P["axes"])       # again, on the measured heights
    P["z_datum"] = {"value": f"the bridge's reference ground: the measured ground and water under it, weighted over {REF_SIGMA_M:.0f} m and "
                             "0 at each landing (heights in CGVD28); a flat map's ground is z = 0", "source": survey, "method": "measured"}
    P.setdefault("made", {})["measured"] = {"by": "urbanstyle bridge-measure", "survey": survey, "tiles": list(tiles),
                                            "stations": n_all, "measured": n_meas}
    return P


def _fit_in_order(P, touch_m=1.5):
    """Each arm's heights in the standard form (grades and vertical curves, fitted to its samples), the arms in order: the longest first,
    free; then every arm whose end touches an arm already fitted, starting there with that arm's height and grade (in its own direction),
    so it leaves the fork smoothly. An arm that touches none is fitted free."""
    import shapely
    from .bridge_profile import fit_alignment, fit_from, grade, height
    lines = {a["id"]: shapely.LineString(a["line"]["value"]) for a in P["axes"]}
    unit = lambda ln, s: (lambda p, q: ((q.x - p.x) / (p.distance(q) or 1), (q.y - p.y) / (p.distance(q) or 1)))(
        ln.interpolate(max(s - 2, 0)), ln.interpolate(min(s + 2, ln.length)))
    todo = sorted(P["axes"], key=lambda a: -a["length_m"])
    done = []

    def put(a, pts, cur, rms, mx, parent=None):
        a["vertical"].update({"points": pts, "curves": cur, "fit": {"rms_m": round(rms, 3), "max_m": round(mx, 3)}})
        if parent:
            a["vertical"]["starts_from"] = parent
    first = todo.pop(0)
    put(first, *fit_alignment([tuple(q) for q in first["vertical"]["samples"]]))
    done.append(first)
    while todo:
        best = None
        for a in todo:
            ln = lines[a["id"]]
            for e in (0, 1):
                end = shapely.Point(ln.coords[-1] if e else ln.coords[0])
                for b in done:
                    lb = lines[b["id"]]
                    if lb.distance(end) <= touch_m:
                        best = best or (a, e, b, lb.project(end))
        if best is None:                    # touches no fitted arm (yet): free
            a = todo.pop(0)
            put(a, *fit_alignment([tuple(q) for q in a["vertical"]["samples"]]))
            done.append(a)
            continue
        a, e, b, sb = best
        todo.remove(a)
        ln, lb = lines[a["id"]], lines[b["id"]]
        z0 = height(b["vertical"], sb)
        ta, tb = unit(ln, ln.length if e else 0.0), unit(lb, sb)
        g_b = grade(b["vertical"], sb)
        g_a = g_b * (1 if ta[0] * tb[0] + ta[1] * tb[1] >= 0 else -1)      # the same slope, in a's own direction
        smp = [tuple(q) for q in a["vertical"]["samples"]]
        if e:       # it touches at its end: fit it from that end, then turn it back
            L = smp[-1][0]
            rev = [(round(L - s_, 2), z_) for s_, z_ in reversed(smp)]
            pts, cur, rms, mx = fit_from(rev, z0, -g_a)
            pts = [[round(L - s_, 2), z_] for s_, z_ in reversed(pts)]
            cur = list(reversed(cur))
        else:
            pts, cur, rms, mx = fit_from(smp, z0, g_a)
        put(a, pts, cur, rms, mx, b["id"])
        done.append(a)


def write(profile_path, out, tiles, osm_db=None):
    """Measure the profile at profile_path with the LiDAR tiles; write it to out (a file or a directory). Returns the path."""
    import os
    P = measure(json.load(open(profile_path)), tiles, osm_db=osm_db)
    if os.path.isdir(out) or not out.endswith(".json"):
        os.makedirs(out, exist_ok=True)
        out = os.path.join(out, os.path.basename(profile_path))
    with open(out, "w") as f:
        json.dump(P, f, indent=1)
    return out
