"""The pictures in docs/img/ (README and docs home), drawn from a built Monaco container.

    python3 docs/build_images.py data/monaco.duckdb      # needs matplotlib, geopandas and roadstyle (for the kind colours)

hero.png: one patch of Monaco, level 0, every container filled with its strips, the buildings and the trees.
partition.png: the same patch by container kind (section, intersection, path, plaza).
"""
import sys

import duckdb
import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from shapely import wkb  # noqa: E402

from urbanstyle.dashboard import KINDS  # noqa: E402

BBOX = (7.4225, 43.7368, 7.4305, 43.7418)   # lon/lat: Monte Carlo, around the casino
STRIPS = {"travel": "#5b6472", "cycle": "#2e9d5b", "sidewalk": "#e6d5c3", "furnishing": "#c9a27e", "frontage": "#b08968",
          "open": "#efe9dc", "plaza": "#f4a6b4", "track": "#e879f9"}   # as in the dashboard's strip overlays
BUILDING, BG = "#3b3f4a", "#f7f5f0"


def frame(con, sql, epsg):
    df = con.execute(sql.format(bbox="ST_MakeEnvelope({}, {}, {}, {})".format(*BBOX))).df()
    return gpd.GeoDataFrame(df.drop(columns="g"), geometry=[wkb.loads(bytes(g)) for g in df.g], crs="EPSG:4326").to_crs(epsg)


def save(ax, fig, path):
    ax.set_axis_off()
    ax.set_xlim(*XL)
    ax.set_ylim(*YL)
    fig.savefig(path, dpi=110, bbox_inches="tight", pad_inches=0, facecolor=BG)
    print("wrote", path)


if __name__ == "__main__":
    con = duckdb.connect(sys.argv[1], read_only=True)
    con.execute("LOAD spatial")
    epsg = f"EPSG:{32600 + int((BBOX[0] + 180) // 6) + 1}"
    hit = "level = 0 AND ST_Intersects(geometry, {bbox})"
    strips = frame(con, f"SELECT type, ST_AsWKB(geometry) g FROM space.strip WHERE {hit}", epsg)
    conts = frame(con, f"SELECT kind, ST_AsWKB(geometry) g FROM space.container WHERE {hit}", epsg)
    blds = frame(con, "SELECT ST_AsWKB(geometry) g FROM space.element WHERE type = 'building' AND level_min <= 0 AND level_max >= 0"
                      " AND ST_Intersects(geometry, {bbox})", epsg)
    trees = frame(con, f"SELECT ST_AsWKB(geometry) g FROM space.object WHERE class = 'vegetation.tree' AND {hit}", epsg)
    box = gpd.GeoSeries(gpd.points_from_xy(BBOX[::2], BBOX[1::2]), crs="EPSG:4326").to_crs(epsg)
    XL, YL = sorted(box.x), sorted(box.y)

    fig, ax = plt.subplots(figsize=(12, 12 * (YL[1] - YL[0]) / (XL[1] - XL[0])))
    fig.patch.set_facecolor(BG)
    for t, c in STRIPS.items():
        strips[strips["type"] == t].plot(ax=ax, color=c, linewidth=0)
    conts.boundary.plot(ax=ax, color="#ffffff", linewidth=0.6)
    blds.plot(ax=ax, color=BUILDING, linewidth=0)
    trees.plot(ax=ax, color="#4d7c0f", markersize=10)
    save(ax, fig, "docs/img/hero.png")

    fig, ax = plt.subplots(figsize=(12, 12 * (YL[1] - YL[0]) / (XL[1] - XL[0])))
    fig.patch.set_facecolor(BG)
    for k, _, fill, line in KINDS:
        conts[conts["kind"] == k].plot(ax=ax, color=fill, edgecolor=line, linewidth=0.7)
    blds.plot(ax=ax, color=BUILDING, linewidth=0)
    save(ax, fig, "docs/img/partition.png")
