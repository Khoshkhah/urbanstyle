#!/usr/bin/env python3
# Usage (roadstyle-current env): python scripts/bridge_roadstyle_page.py DUCKOSM_DB_WITH_GROUND OUT.html [PROFILES...]   (from the repo root;
# the db needs main.elevation_grid and main.elevation_metadata: copy them from duckOSM's pass-0 folder when the db has none)
"""A roadstyle 3D page of an area with its bridges: roadstyle's engine makes the profile of each bridge group (``rs.bridge_profile``),
urbanstyle gives its input as elevations (``parameters.z_reference = "elevation"``, roadstyle PR 179):

- a free end of a group: the area's ground there (duckOSM's grid, interpolated as the page draws it);
- a junction: urbanstyle's deck there, base + height (``data/bridges-*/<name>.bridge.json``, ``urbanstyle bridge-ground``);
- interior points only where a deck must clear something (urbanstyle's clearances: 5.5 m over a road, a lower deck's height and the
  gap over a deck): one at the start and one at the end of each clearance, at the base plus the clearance; elsewhere roadstyle's engine
  draws each chain from node to node (Kaveh, 2026-11-12: a group needs heights at its junctions, and points only where it must clear).

Writes OUT.html and OUT.profile.json (the input given to roadstyle)."""
import glob
import json
import sys
import warnings

import geopandas as gpd
import numpy as np
import shapely
from pyproj import Transformer

import roadstyle as rs
import roadstyle.duckosm as d

DB, OUT = sys.argv[1], sys.argv[2]
FILES = sys.argv[3:] or sorted(glob.glob("data/bridges-monaco/*.bridge.json"))
AXIS_M = 15.0           # a node belongs to an axis that passes this near it
JOIN_M = 10.0           # two clearances this near each other are one

roads, _, _ = d.read(DB, "driving", levels="auto")
df = roads.to_pandas()
df = df[df["driving"].fillna(False)]
edges = gpd.GeoDataFrame(df.drop(columns="geometry"), geometry=shapely.from_wkb(df["geometry"]), crs=4326)

# the area's ground: duckOSM's grid, interpolated between its points (as the page's terrain)
import duckdb
g = duckdb.connect(DB, read_only=True).execute("SELECT col, row, lon, lat, z FROM main.elevation_grid").df()
nc, nr = g.col.max() + 1, g.row.max() + 1
Z = np.full((nr, nc), np.nan)
Z[g.row, g.col] = g.z
lon0, lat0 = g.lon[(g.col == 0) & (g.row == 0)].iloc[0], g.lat[(g.col == 0) & (g.row == 0)].iloc[0]
dlon = g.lon[(g.col == 1) & (g.row == 0)].iloc[0] - lon0
dlat = g.lat[(g.col == 0) & (g.row == 1)].iloc[0] - lat0


def ground_at(lon, lat):
    x, y = (lon - lon0) / dlon, (lat - lat0) / dlat
    i, j = min(max(int(np.floor(y)), 0), nr - 2), min(max(int(np.floor(x)), 0), nc - 2)
    fx, fy = x - j, y - i
    return float(Z[i, j] * (1 - fx) * (1 - fy) + Z[i, j + 1] * fx * (1 - fy) + Z[i + 1, j] * (1 - fx) * fy + Z[i + 1, j + 1] * fx * fy)


# urbanstyle's decks: each axis with its elevation (base + height) at its grade points and every metre
axes, ground_facts = [], None
for f in FILES:
    P = json.load(open(f))
    ground_facts = ground_facts or P.get("ground")
    to_m = Transformer.from_crs("EPSG:4326", P["crs"], always_xy=True).transform
    for a in P["axes"]:
        if "base" not in a:
            continue
        line = shapely.LineString(a["line"]["value"])
        v, b = np.array(a["vertical"]["points"]), np.array(a["base"]["points"])
        elev = lambda s, v=v, b=b: float(np.interp(s, b[:, 0], b[:, 1]) + np.interp(s, v[:, 0], v[:, 1]))
        base = lambda s, b=b: float(np.interp(s, b[:, 0], b[:, 1]))
        runs = {}           # what the deck must clear: {what: [s from, s to, height above the base]}
        for c in a["vertical"].get("clearances", []):
            s_ = line.project(shapely.Point(c["at"]))
            r = runs.setdefault(c["over"], [s_, s_, c["z"]])
            r[0], r[1], r[2] = min(r[0], s_), max(r[1], s_), max(r[2], c["z"])
        joined = []         # (clearances that overlap or lie within JOIN_M of each other are one thing to clear: one start, one end)
        for r in sorted(runs.values()):
            if joined and r[0] <= joined[-1][1] + JOIN_M:
                joined[-1] = [joined[-1][0], max(joined[-1][1], r[1]), max(joined[-1][2], r[2])]
            else:
                joined.append(list(r))
        axes.append({"id": f"{f.split('/')[-1][:-12]}:{a['id']}", "line": line, "to_m": to_m, "elev": elev, "base": base,
                     "runs": joined})


def nearest_axis(*lonlats):
    """The axis that passes nearest to all the points, and each point's place along it; None when one is farther than AXIS_M."""
    best = None
    for ax in axes:
        qs = [shapely.Point(ax["to_m"](*ll)) for ll in lonlats]
        far = max(ax["line"].distance(q) for q in qs)
        if far < AXIS_M and (best is None or far < best[0]):
            best = (far, ax, [ax["line"].project(q) for q in qs])
    return None if best is None else (best[1], best[2])


prof = rs.bridge_profile(edges)                     # roadstyle's groups, nodes and chains of these roads
groups, notes = [], []
for grp in prof["groups"]:
    where = {n["id"]: n["lonlat"] for n in grp["nodes"]}
    nodes = []
    for n in grp["nodes"]:
        if n["kind"] == "ground":
            nodes.append({"id": n["id"], "z_m": round(ground_at(*n["lonlat"]), 2), "source": "duckOSM", "method": "mapped"})
            hit = nearest_axis(n["lonlat"])
            if hit and hit[0]["elev"](hit[1][0]) - ground_at(*n["lonlat"]) > 1.0:
                notes.append(f"{n['id']}: a free end for roadstyle, but urbanstyle's deck {hit[0]['id']} is "
                             f"{hit[0]['elev'](hit[1][0]) - ground_at(*n['lonlat']):.1f} m above the ground there")
        else:
            hit = nearest_axis(n["lonlat"])
            if hit is None:
                notes.append(f"{n['id']}: no urbanstyle axis within {AXIS_M} m: roadstyle's rule fills it")
                continue
            nodes.append({"id": n["id"], "z_m": round(hit[0]["elev"](hit[1][0]), 2), "source": "urbanstyle", "method": "derived"})
    chains = []
    for c in grp["chains"]:
        hit = nearest_axis(where[c["from"]], where[c["to"]])
        if hit is None:
            continue
        ax, (a0, a1) = hit
        lo, hi = sorted((a0, a1))
        at = {}
        for s_lo, s_hi, zc in ax["runs"]:
            for s in (s_lo, s_hi):
                sc = abs(s - a0)
                if lo + 1.0 < s < hi - 1.0 and 1.0 < sc < c["length_m"] - 1.0:
                    k = round(sc)
                    # (a clearance that no allowed grade reaches, "met": false in the profile: the height urbanstyle's deck reaches there)
                    z = min(ax["base"](s) + zc, ax["elev"](s))
                    at[k] = max(at.get(k, (0, -1e9)), (round(sc, 2), round(z, 2)), key=lambda q: q[1])
        pts = [{"s": s, "z_m": z, "source": "urbanstyle", "method": "derived"} for s, z in sorted(at.values())]
        # each point rounded by a vertical curve, urbanstyle's rule (bridge_profile.fit_alignment): 0.9 of the shorter grade beside it
        ss = [0.0] + [q["s"] for q in pts] + [c["length_m"]]
        for k, q in enumerate(pts, start=1):
            q["curve_m"] = round(min(80.0, 0.9 * min(ss[k] - ss[k - 1], ss[k + 1] - ss[k])), 1)
        if pts:
            chains.append({"id": c["id"], "points": pts})
    groups.append({"nodes": nodes, "chains": chains})
given = {"parameters": {"curve": "design", "z_reference": "elevation"},
         "ground": {k: ground_facts[k] for k in ("id", "source", "product", "vertical_datum")}, "groups": groups}
json.dump(given, open(OUT.replace(".html", "") + ".profile.json", "w"), indent=1)
print(f"{len(groups)} groups, {sum(len(x['nodes']) for x in groups)} nodes, {sum(len(c['points']) for x in groups for c in x['chains'])} points where a deck must clear")
print("\n".join(notes) or "no notes")
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    rs.bridge_profile(edges, given)                 # roadstyle's engine checks the input and fills the rest
    page = rs.render_dashboard(edges, view_3d=True, bridge_profile=given, ground=d.ground(DB))
    for x in w:
        print("roadstyle:", str(x.message)[:220])
page.save(OUT)
print("saved", OUT)
