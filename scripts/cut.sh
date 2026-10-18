#!/usr/bin/env bash
# A fast test of a change: build only a small square round one place, check it, write its page and serve it (about 2 min, not 30).
#   scripts/cut.sh AREA NAME LON LAT [RADIUS_M]      AREA: monaco | vancouver; RADIUS_M: half the square's side (default 250)
#   then open http://localhost:8784/cut-NAME.html: port 8784, the only one Street View's Google key allows (it stops the server that ran
#   there; PORT=... serves elsewhere, with no Street View)
# The cut has the full area's code and rules. Only its edges differ: roads that leave the square end there.
# Every bridge profile that comes near the square goes with it, whole, and the square grows to hold it and the roads that join it.
# Monaco's cut comes from duckOSM's wide database (the region round Monaco), so the roads past the border are there too.
set -e
cd "$(dirname "$0")/.."
area=$1 name=$2 lon=$3 lat=$4 radius=${5:-250} port=${PORT:-8784}
P=/home/kaveh/projects/duckOSM/.venv/bin/python
case $area in
  monaco)    src=../duckOSM/data/monaco-wide/monaco-wide.duckdb; bridges="data/bridges-monaco/*.bridge.json" ;;
  vancouver) src=data/units/broadway-granville.osm.duckdb; bridges=data/bridges-measured/granville-bridge.bridge.json ;;
  *) echo "AREA: monaco or vancouver"; exit 2 ;;
esac
mkdir -p data/cuts
export CARTO_API_KEY="${CARTO_API_KEY:-$(grep -o 'CARTO_API_KEY="[^"]*"' ~/.bashrc | cut -d'"' -f2)}"
k=~/miniconda3/envs/roadstyle/etc/conda/activate.d/google_maps_key.sh; [ -f $k ] && source $k
t0=$(date +%s)
PYTHONPATH=src:../roadstyle/src $P - "$area" "$name" "$lon" "$lat" "$radius" "$src" $bridges <<'PY'
import glob, json, os, sys
area, name, lon, lat, radius, src, bridges = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5]), sys.argv[6], sys.argv[7:]
import duckdb, pyproj
from urbanstyle import cli, container, unit
base = f"data/cuts/{name}"
near = []                      # the profiles with an axis point within 1.5 radius (UTM metres, each profile's own zone)
for pf in bridges:
    P = json.load(open(pf))
    X, Y = pyproj.Transformer.from_crs("EPSG:4326", P.get("crs", "EPSG:32632"), always_xy=True).transform(lon, lat)
    pts = [p for a in P.get("axes", []) for p in ((a.get("line") or {}).get("value") or [])]
    if any((p[0] - X) ** 2 + (p[1] - Y) ** 2 <= (radius * 1.5) ** 2 for p in pts):
        near.append(pf)
print("bridges:", [os.path.basename(b) for b in near], flush=True)
lon0, lat0 = lon, lat           # (the place itself: the cut's small square is round it)
# the square grows to hold every bridge it takes, whole, and the roads that join it (MARGIN_M round its axes)
MARGIN_M = 60.0
box = [(lon, lat, radius)]
for pf in near:
    P = json.load(open(pf)); t = pyproj.Transformer.from_crs(P["crs"], "EPSG:4326", always_xy=True).transform
    box += [(*t(p[0], p[1]), MARGIN_M) for a in P["axes"] for p in a["line"]["value"]]
import math
k = 111320.0; c = math.cos(math.radians(lat))
x0 = min(x - r / (k * c) for x, _, r in box); x1 = max(x + r / (k * c) for x, _, r in box)
y0 = min(y - r / k for _, y, r in box); y1 = max(y + r / k for _, y, r in box)
lon, lat = (x0 + x1) / 2, (y0 + y1) / 2
radius = max((x1 - x0) / 2 * k * c, (y1 - y0) / 2 * k, radius)
print(f"cut: {2 * radius:.0f} m square round {lon:.5f}, {lat:.5f}", flush=True)
# Vancouver's roads from the whole city's database, so a bridge that leaves the unit is whole (as Monaco's wide database)
CITY = "../duckOSM/data/db/vancouver_city.duckdb"
unit.clip(CITY if area == "vancouver" and os.path.exists(CITY) else src, base + ".osm.duckdb", lon, lat, radius)
# the cut's area: the small square round the place, and each bridge's deck with DECK_MARGIN_M round it (the roads that join it); not the
# whole square that holds the bridges: Granville's 1.4 km square built a whole neighbourhood's ground and took 15 to 30 minutes
import shapely, shapely.ops
from urbanstyle.bridge_profile import deck_polygon
DECK_MARGIN_M = 60.0
k_ = 111320.0
r0 = float(sys.argv[5])
small = shapely.box(lon0 - r0 / (k_ * math.cos(math.radians(lat0))), lat0 - r0 / k_, lon0 + r0 / (k_ * math.cos(math.radians(lat0))), lat0 + r0 / k_)
decks = []
for pf in near:
    P = json.load(open(pf)); tr_ = pyproj.Transformer.from_crs(P["crs"], "EPSG:4326", always_xy=True).transform
    decks.append(shapely.ops.transform(tr_, deck_polygon(P).buffer(DECK_MARGIN_M)))
keep = shapely.union_all([small] + decks)
con = duckdb.connect(base + ".osm.duckdb"); con.execute("LOAD spatial")
con.execute("UPDATE main.boundary SET geometry = ST_Intersection(geometry, ST_GeomFromText(?))", [keep.wkt])
if area == "vancouver":        # (and only where the unit has its city data: its own edge, or a bridge's deck)
    con.execute(f"ATTACH '{src}' AS s (READ_ONLY)")
    con.execute("UPDATE main.boundary SET geometry = ST_Intersection(geometry, ST_Union((SELECT geometry FROM s.main.boundary), ST_GeomFromText(?)))",
                [shapely.union_all(decks).wkt if decks else "POLYGON EMPTY"])
con.close()
if area == "vancouver":        # the unit's city data, found by the output's file name
    for f in ("vancouver.json", "urban.duckdb.mapillary.json"):
        s_, d = src.replace(".osm.duckdb", "." + f), f"{base}.{f}"
        if os.path.exists(s_) and not os.path.lexists(d):
            os.symlink(os.path.abspath(s_), d)
out = base + ".urban.duckdb"
for f in (out, out + ".before-division", out + ".before-ground"):
    if os.path.exists(f):
        os.remove(f)
container.build(base + ".osm.duckdb", out, bridges=near).close()
try:                           # the checks, with the bridges' own (BR1-BR12), into urban.check: the page's check list
    cli.main(["check", out] + (["--bridge"] + near if near else []))
except SystemExit:
    pass
with open(base + ".bridges", "w") as f:
    f.write(" ".join(near))
cli.main(["dashboard", out, f"viz/cut-{name}.html"] + (["--bridge"] + near if near else []))
PY
echo "built in $(( $(date +%s) - t0 )) s"
for p in $(pgrep -f "urbanstyle serv[e].*--port $port"); do kill $p; done; sleep 1      # (the last cut's server)
PYTHONPATH=src:../roadstyle/src setsid nohup $P -m urbanstyle serve data/cuts/$name.urban.duckdb viz/cut-$name.html \
  $(cat data/cuts/$name.bridges | sed 's/^./--bridge &/') --port $port > data/cuts/$name.serve.log 2>&1 &
for i in $(seq 60); do [ "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:$port/cut-$name.html)" = 200 ] && break; sleep 2; done
echo "UP http://localhost:$port/cut-$name.html  ($(( $(date +%s) - t0 )) s)"
