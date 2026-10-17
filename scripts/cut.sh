#!/usr/bin/env bash
# A fast test of a change: build only a small square round one place, check it, write its page and serve it (about 2 min, not 30).
#   scripts/cut.sh AREA NAME LON LAT [RADIUS_M]      AREA: monaco | vancouver; RADIUS_M: half the square's side (default 250)
#   then open http://localhost:8786/cut-NAME.html (Street View works on port 8784 only)
# The cut has the full area's code and rules. Only its edges differ: roads that leave the square end there.
# Every bridge profile that comes near the square goes with it, whole.
set -e
cd "$(dirname "$0")/.."
area=$1 name=$2 lon=$3 lat=$4 radius=${5:-250} port=8786
P=/home/kaveh/projects/duckOSM/.venv/bin/python
case $area in
  monaco)    src=../duckOSM/monaco.duckdb; bridges="data/bridges-monaco/*.bridge.json" ;;
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
from urbanstyle import checks, cli, container, unit
base = f"data/cuts/{name}"
unit.clip(src, base + ".osm.duckdb", lon, lat, radius)
if area == "vancouver":        # the unit's own edge, and its city data, found by the output's file name
    con = duckdb.connect(base + ".osm.duckdb"); con.execute("LOAD spatial"); con.execute(f"ATTACH '{src}' AS s (READ_ONLY)")
    con.execute("UPDATE main.boundary SET geometry = ST_Intersection(geometry, (SELECT geometry FROM s.main.boundary))"); con.close()
    for f in ("vancouver.json", "urban.duckdb.mapillary.json"):
        s, d = src.replace(".osm.duckdb", "." + f), f"{base}.{f}"
        if os.path.exists(s) and not os.path.lexists(d):
            os.symlink(os.path.abspath(s), d)
near = []                      # the profiles with an axis point within 1.5 radius (UTM metres, each profile's own zone)
for pf in bridges:
    P = json.load(open(pf))
    X, Y = pyproj.Transformer.from_crs("EPSG:4326", P.get("crs", "EPSG:32632"), always_xy=True).transform(lon, lat)
    pts = [p for a in P.get("axes", []) for p in ((a.get("line") or {}).get("value") or [])]
    if any((p[0] - X) ** 2 + (p[1] - Y) ** 2 <= (radius * 1.5) ** 2 for p in pts):
        near.append(pf)
print("bridges:", [os.path.basename(b) for b in near], flush=True)
out = base + ".urban.duckdb"
for f in (out, out + ".before-division", out + ".before-ground"):
    if os.path.exists(f):
        os.remove(f)
container.build(base + ".osm.duckdb", out, bridges=near).close()
checks.run(out)
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
