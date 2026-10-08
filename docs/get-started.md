# Get started

<p class="lead">From an OpenStreetMap extract to a street-space database and a map, in three commands.</p>

## Install

```bash
pip install "urbanstyle[dashboard,osm] @ git+https://github.com/Khoshkhah/urbanstyle"
```

`dashboard` brings roadstyle and geopandas, `osm` brings duckOSM. urbanstyle is not on PyPI yet; after the first
release this becomes `pip install "urbanstyle[dashboard,osm]"`.

The core needs only DuckDB (with its `spatial` extension, fetched on first use), shapely, numpy and pandas.

## 1. A duckOSM database

```bash
duckosm build --pbf monaco-latest.osm.pbf -o monaco.duckdb -m driving -m walking -m cycling
```

urbanstyle reads the road, walkway and cycleway edges of the mode schemas and the buildings, rail and stations of
the `features` schema. A database without `features` is fine: `build` copies it next to the output and builds the
layers from `raw.*` (that needs the `osm` extra).

## 2. Build the space

```bash
urbanstyle build monaco.duckdb data/monaco.duckdb
```

Monaco takes about a minute, Södermalm (Stockholm) about 18 minutes and 7 GB of memory. Everything lands in the
`space` schema of the output:

| table | one row per |
|---|---|
| `space.element` | building, road, walkway, cycleway or rail line, with its level span `level_min` … `level_max` |
| `space.container` | section, intersection, path space, rail space or plaza at one level, with its widths and shape |
| `space.street`, `space.arm` | street group, and each road that arrives at an intersection |
| `space.zone` | travelway, pedestrian realm or track of a container |
| `space.strip` | typed band: travel, cycle, sidewalk, furnishing, frontage, open, plaza, track |
| `space.object` | point object: tree, lamp, bench, signal, crossing, entrance… |
| `space.station`, `space.link` | station, and place where you change level (ramp, stairs, elevator, entrance) |

Ids are stable across rebuilds: `s<level>-<edge>` for a section, `i<level>-<node>` for an intersection,
`p…` path, `r…` rail, `k…` street.

## 3. Check and look

```bash
urbanstyle check data/monaco.duckdb       # one line per invariant; exit 1 if a hard one fails
urbanstyle quality data/monaco.duckdb     # how rectangular the sections are, how much of them lies on a facade
urbanstyle dashboard data/monaco.duckdb viz/monaco.html
cd viz && python3 -m http.server 8765     # Street View needs http, not file://
```

The dashboard is a [roadstyle](https://khoshkhah.github.io/roadstyle/) map with a tree of streets, sections and
intersections on the left, level buttons, and every overlay switchable. `#c=<container id>` in the URL opens one
container.

## From Python

```python
import urbanstyle

con = urbanstyle.build("monaco.duckdb", "data/monaco.duckdb")   # an open DuckDB connection
for level, kind, n in urbanstyle.counts(con):
    print(level, kind, n)
```
