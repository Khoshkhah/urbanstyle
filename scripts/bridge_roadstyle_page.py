#!/usr/bin/env python3
# Usage (roadstyle-current env): python scripts/bridge_roadstyle_page.py DUCKOSM_DB_WITH_GROUND OUT.html   (run from the repo root;
# the db needs main.elevation_grid and main.elevation_metadata: copy them from duckOSM's pass-0 folder when the db has none)
"""A roadstyle 3D page of Monaco: the area's ground (FABDEM, duckOSM) as terrain and the ten bridge profiles, each deck at its base plus
its height. roadstyle draws ground + z_m, so each point gets z_m = base + height - ground there."""
import glob, json, sys, warnings
import numpy as np, geopandas as gpd, shapely
from pyproj import Transformer
import roadstyle as rs
import roadstyle.duckosm as d

DB, OUT = sys.argv[1], sys.argv[2]
roads, _, _ = d.read(DB, "driving", levels="auto")
df = roads.to_pandas()
df = df[df["driving"].fillna(False)]
edges = gpd.GeoDataFrame(df.drop(columns="geometry"), geometry=shapely.from_wkb(df["geometry"]), crs=4326)
import duckdb
g = duckdb.connect(DB, read_only=True).execute("SELECT col, row, lon, lat, z FROM main.elevation_grid").df()
nc, nr = g.col.max() + 1, g.row.max() + 1
Z = np.full((nr, nc), np.nan); Z[g.row, g.col] = g.z
lon0, lat0 = g.lon[(g.col == 0) & (g.row == 0)].iloc[0], g.lat[(g.col == 0) & (g.row == 0)].iloc[0]
dlon = g.lon[(g.col == 1) & (g.row == 0)].iloc[0] - lon0; dlat = g.lat[(g.col == 0) & (g.row == 1)].iloc[0] - lat0
def dtm(lon, lat):
    x, y = (lon - lon0) / dlon, (lat - lat0) / dlat
    i, j = int(np.floor(y)), int(np.floor(x)); fy, fx = y - i, x - j
    i, j = min(max(i, 0), nr - 2), min(max(j, 0), nc - 2)
    return float(Z[i, j] * (1 - fx) * (1 - fy) + Z[i, j + 1] * fx * (1 - fy) + Z[i + 1, j] * (1 - fx) * fy + Z[i + 1, j + 1] * fx * fy)
to_ll = Transformer.from_crs("EPSG:32632", "EPSG:4326", always_xy=True).transform
merged = {"format": "urbanstyle.bridge/1", "crs": "EPSG:32632", "axes": []}
neg, report = 0, []
for f in sorted(glob.glob("data/bridges-monaco/*.bridge.json")):
    P = json.load(open(f))
    merged.setdefault("ground", P.get("ground")); merged.setdefault("z_datum", P.get("z_datum"))
    for a in P["axes"]:
        line = shapely.LineString(a["line"]["value"]); L = line.length
        v = np.array(a["vertical"]["points"]); b = np.array(a["base"]["points"]) if "base" in a else None
        def zz(s):
            ground = dtm(*to_ll(*line.interpolate(s).coords[0]))
            base = float(np.interp(s, b[:, 0], b[:, 1])) if b is not None else ground
            return base + float(np.interp(s, v[:, 0], v[:, 1])) - ground
        ss = sorted({*np.arange(0.0, L, 1.0).tolist(), L})
        samples = [[round(s, 2), round(zz(s), 3)] for s in ss]
        neg += sum(1 for _, z in samples if z < -0.05)
        pts = [[s, round(zz(s), 3)] for s, _ in a["vertical"]["points"]]
        merged["axes"].append({"id": f"{f.split('/')[-1][:-12]}:{a['id']}", "ways": a["ways"], "line": a["line"],
                               "vertical": {"points": pts, "curves": [0.0] * len(pts), "samples": samples, "source": "urbanstyle"}})
        e0, e1 = samples[0][1], samples[-1][1]
        report.append(f"{merged['axes'][-1]['id']:34} base {'yes' if b is not None else 'NO '}  z_m at the ends {e0:6.2f} {e1:6.2f}  lowest {min(z for _, z in samples):6.2f}")
print("\n".join(report)); print("samples below the ground (z_m < -0.05):", neg)
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    given = rs.bridge_profile_from_urbanstyle(edges, merged)
    for x in w: print("warning:", str(x.message)[:200])
ground = d.ground(DB)
page = rs.render_dashboard(edges, view_3d=True, bridge_profile=given, ground=ground)
page.save(OUT)
print("saved", OUT)
