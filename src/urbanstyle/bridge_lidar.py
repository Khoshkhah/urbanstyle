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

STEP_M = 10.0       # a station every this along each axis
HALF_M = 5.0        # the window runs this far along the axis each side of the station
GAP_M = 2.0         # a vertical gap this wide splits the deck from what lies under it
DECK_Q = 0.25       # the deck top: this quantile of the returns above the gap (cars on the deck lie above it)
GROUND_R_M = 30.0   # the ground under a station: ground and water returns this near
MIN_PTS = 20        # fewer returns than this in a window: no measurement there
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


def measure(profile, tiles, survey="City of Vancouver LiDAR 2022"):
    """The profile with each axis's vertical points measured where the LiDAR has returns (a new dict; `profile` is not changed)."""
    import copy

    import ducklidar as dl
    import numpy as np
    import pyproj
    import shapely
    from .bridge_profile import _z

    P = copy.deepcopy(profile)
    # ponytail: NAD83(CSRS) and WGS84 taken as one (no grid shift): about 1 m sideways, less than a lane; add a grid when it matters
    tr = pyproj.Transformer.from_crs(P["crs"], "EPSG:26910", always_xy=True).transform
    n_meas = n_all = 0
    for a in P["axes"]:
        ax = shapely.LineString([tr(x, y) for x, y in a["line"]["value"]])
        chosen = a["vertical"]["points"]
        pts, stations = [], []
        for k in range(int(ax.length // STEP_M) + 1):
            s = min(k * STEP_M, ax.length)
            sec = next((x for x in a["sections"] if x["s0"] - 0.01 <= s <= x["s1"] + 0.01), a["sections"][-1] if a["sections"] else None)
            bands = [b for b in (sec["bands"] if sec else []) if b["type"] == "lane"] or (sec["bands"] if sec else [])
            lo = min((b["t"] - b["width"]["value"] / 2 for b in bands), default=-3.0)
            hi = max((b["t"] + b["width"]["value"] / 2 for b in bands), default=3.0)
            p = ax.interpolate(s)
            a0, b0 = ax.interpolate(max(s - 1, 0)), ax.interpolate(min(s + 1, ax.length))
            ux, uy = b0.x - a0.x, b0.y - a0.y
            h = (ux * ux + uy * uy) ** .5 or 1
            ux, uy = ux / h, uy / h
            r = max(GROUND_R_M, HALF_M + max(abs(lo), abs(hi)))
            d = dl.read(tiles, (p.x - r, p.y - r, p.x + r, p.y + r))
            dx, dy = d["x"] - p.x, d["y"] - p.y
            along, across = dx * ux + dy * uy, -dx * uy + dy * ux       # across: + left, as the profile's t
            cls = d["classification"]
            win = (np.abs(along) <= HALF_M) & (across >= lo) & (across <= hi) & ~np.isin(cls, SKIP)
            gnd = np.isin(cls, GROUND) & (dx * dx + dy * dy <= GROUND_R_M ** 2)
            top = deck_top(d["z"][win])
            ground = float(np.median(d["z"][gnd])) if gnd.sum() >= MIN_PTS else None
            n_all += 1
            if top is None or ground is None:
                pts.append([round(s, 2), round(_z(chosen, s), 2)])
                stations.append({"s": round(s, 2), "n": int(win.sum()), "method": "chosen"})
                continue
            n_meas += 1
            pts.append([round(s, 2), round(max(top - ground, 0.0), 2)])
            stations.append({"s": round(s, 2), "n": int(win.sum()), "deck_m": round(top, 2), "ground_m": round(ground, 2), "method": "measured"})
        meas = sum(st["method"] == "measured" for st in stations)
        a["vertical"] = {"points": pts, "source": survey if meas else a["vertical"]["source"], "method": "measured" if meas else "chosen",
                         "rule": f"the deck top (the {DECK_Q:.0%} quantile of the returns in the lane bands, {2 * HALF_M:.0f} m along) above the "
                                 f"median ground and water return within {GROUND_R_M:.0f} m, every {STEP_M:.0f} m; {meas} of {len(stations)} "
                                 f"stations measured, the others keep the chosen value",
                         "stations": stations, "chosen_before": chosen}
    P["z_datum"] = {"value": "the ground under the deck: the median ground and water return within 30 m of each station (heights in "
                             "CGVD28); a flat map's ground is z = 0", "source": survey, "method": "measured"}
    P.setdefault("made", {})["measured"] = {"by": "urbanstyle bridge-measure", "survey": survey, "tiles": list(tiles),
                                            "stations": n_all, "measured": n_meas}
    return P


def write(profile_path, out, tiles):
    """Measure the profile at profile_path with the LiDAR tiles; write it to out (a file or a directory). Returns the path."""
    import os
    P = measure(json.load(open(profile_path)), tiles)
    if os.path.isdir(out) or not out.endswith(".json"):
        os.makedirs(out, exist_ok=True)
        out = os.path.join(out, os.path.basename(profile_path))
    with open(out, "w") as f:
        json.dump(P, f, indent=1)
    return out
