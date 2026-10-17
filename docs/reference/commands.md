# Commands

This page lists every `urbanstyle` command, as `src/urbanstyle/cli.py` defines it. For each command, it gives the arguments, the options, the output and one example.

## Run the command

The package installs the `urbanstyle` script (`urbanstyle.cli:main` in `pyproject.toml`). From a checkout, `PYTHONPATH=src python -m urbanstyle` is the same command.

The commands need different Python environments:

| Commands | Environment | Why |
|---|---|---|
| `build`, `check`, `quality`, `unit`, `mapillary`, `bridge`, `bridge-heights`, `bridge2d` | The duckOSM venv, `../duckOSM/.venv/bin/python` | It has duckdb, the `spatial` extension and duckOSM. `build` uses `duckosm.features` when the input has no `features` schema. |
| `dashboard`, `layers`, `bridge3d`, `serve` | The system `python3` with `PYTHONPATH=src:../roadstyle/src` | `src/urbanstyle/dashboard.py` imports roadstyle. `bridge3d` and `serve` import from `dashboard.py`. |
| `bridge-measure` | The conda env `lidar` with `../ducklidar/src` on `PYTHONPATH` | It reads ducklidar's Parquet tiles. |

All commands use positional arguments for the input and output paths. The examples use the Vancouver unit `broadway-granville` and the Granville Bridge.

## build

`build` makes the `urban` schema in a new DuckDB database from a duckOSM database.

```text
urbanstyle build osm out [--from division]
```

| Argument or option | Meaning | Default |
|---|---|---|
| `osm` | The duckOSM `.duckdb`. If it has no `features` schema, `build` copies it to `<out without .duckdb>.osm.duckdb` and builds the features in the copy. | required |
| `out` | The output `.duckdb`. | required |
| `--from division` | Run only the street division and the steps after it (the ground, the surfaces, the paths), from the copy that the last full build kept, `<out>.before-division`. Use it after a change to `division.py` or `ground.py`. | none: all steps |

Output: the database `out` with the `urban` schema. `build` prints the number of elements for each level and type, the links by type and level pair, and the next command (`urbanstyle dashboard`). If `<out>.mapillary.json` exists, `build` loads it. `build` prints the time of each step, and a full build keeps `<out>.before-division`.

Code: `container.build`, `container.with_features`, `container.counts`.

```bash
urbanstyle build ../duckOSM/monaco.duckdb data/monaco.duckdb
```

## check

`check` runs the conformance checks on one or more built databases. With `--bridge`, it also runs the bridge model checks.

```text
urbanstyle check db [db ...] [--bridge BRIDGE [BRIDGE ...]]
```

| Argument or option | Meaning | Default |
|---|---|---|
| `db` | One or more built `.duckdb` files. | required |
| `--bridge` | One or more bridge profiles (`<name>.bridge.json`). For each profile, `check` also runs the bridge model checks BR1 to BR11. The lanes at level 0 of the first `db` give the landings. | none |

Output: for each database and each profile, one line for each check: id, status (`PASS`, `FAIL` or `INFO`), count and description. A bridge check that is not zero also prints up to five `?at=x,y,20,60,0` lines, which open the dashboard at that point. The exit code is 1 if a hard check fails, else 0. The checks are in [Checks](checks.md).

Code: `checks.run`, `checks.bridge`.

```bash
urbanstyle check data/units/broadway-granville.urban.duckdb --bridge data/bridges-measured/granville-bridge.bridge.json
```

## quality

`quality` measures the shape of the sections in one or more built databases.

```text
urbanstyle quality db [db ...]
```

| Argument | Meaning | Default |
|---|---|---|
| `db` | One or more built `.duckdb` files. | required |

Output: for each database, the number of level-0 sections with two or more bounding buildings, and the 10th, 25th, 50th, 75th and 90th percentiles of two values. `facade` is the share of the section outline that lies within 0.5 m of a building. `rect` is the section area divided by the area of its minimum rotated rectangle.

Code: `quality.run`.

```bash
urbanstyle quality data/monaco.duckdb
```

## dashboard

`dashboard` writes an offline HTML map of a built database, with the hierarchy tree.

```text
urbanstyle dashboard db out [--bridge PROFILE]
```

| Argument or option | Meaning | Default |
|---|---|---|
| `db` | A built `.duckdb`. | required |
| `out` | The HTML file to write. | required |
| `--bridge PROFILE` | A bridge profile (`<name>.bridge.json`) to draw as a 3D model. You can give the option more than one time. | none |

Output: the HTML page `out`. With `--bridge`, `dashboard` also writes `bridge3d.json` in the folder of `out`. The page reads that file when it opens. The Street View panel uses the `GOOGLE_MAPS_KEY` environment variable at build time.

Code: `dashboard.main`.

```bash
urbanstyle dashboard data/units/broadway-granville.urban.duckdb viz/broadway-granville.html --bridge data/bridges-measured/granville-bridge.bridge.json
```

## layers

`layers` writes an offline HTML page that shows the layers of a built database, one at a time.

```text
urbanstyle layers db out
```

| Argument | Meaning | Default |
|---|---|---|
| `db` | A built `.duckdb`. | required |
| `out` | The HTML file to write. | required |

Output: the HTML page `out` with the blocks, the street spaces, layer 0 (ground), layer 1 (surfaces) and the parts. `layers` prints the path of `out`.

Code: `dashboard.layers`.

```bash
urbanstyle layers data/units/broadway-granville.urban.duckdb viz/broadway-granville-layers.html
```

## mapillary

`mapillary` gets the Mapillary map features and photo positions for the area of a built database.

```text
urbanstyle mapillary db [--osm OSM]
```

| Argument or option | Meaning | Default |
|---|---|---|
| `db` | A built `.duckdb`. Its area is the extent of `work.unit`. | required |
| `--osm` | The duckOSM `.duckdb` that `db` came from. With it, `mapillary` builds the parts again at once. | none |

Output: `<db>.mapillary.json` next to `db`, and the tables `work.observed` and `work.photo` in `db`. `mapillary` prints the number of features and photos. The token comes from `$MAPILLARY_TOKEN`, else from `~/.config/mapillary/token`. If there is no token, the command stops.

Code: `mapillary.main`.

```bash
urbanstyle mapillary data/monaco.duckdb --osm ../duckOSM/monaco.duckdb
```

## unit

`unit` clips the area around one point, builds it and writes the dossier of the unit nearest that point.

```text
urbanstyle unit name --at LON LAT --osm OSM [--city CITY] [--no-mapillary] [--vancouver] [--gtfs GTFS]
```

| Argument or option | Meaning | Default |
|---|---|---|
| `name` | The unit name. All files go to `data/units/<name>.*`. | required |
| `--at LON LAT` | A point of the junction or the street. | required |
| `--osm` | The duckOSM `.duckdb`. If it has no `features` schema, `unit` makes a copy with features in `data/`. | required |
| `--city` | The city name, written to the `unit` table. | `""` |
| `--no-mapillary` | Do not get Mapillary features and photos. | off |
| `--vancouver` | Add the City of Vancouver open data (trees, lamps, meters and more). | off |
| `--gtfs` | The URL of a GTFS feed. It gives the routes and the buses per hour of each stop. | none |

Output, in `data/units/`:

- `<name>.osm.duckdb`: the clipped duckOSM area, 400 m around the point (`CLIP_M`).
- `<name>.urban.duckdb`: the built `urban` schema.
- `<name>.duckdb`: the dossier, with the tables `unit`, `source`, `road`, `surface`, `line`, `object`, `match`, `lane`, `movement`, `rule`, `observation` and `check`.
- `<name>.urban.duckdb.mapillary.json`, unless `--no-mapillary` is set.
- `<name>.vancouver.json` with `--vancouver`, and `<name>.gtfs.json` with `--gtfs`. The GTFS feed itself goes to `data/gtfs/<host>.zip`.

`unit` prints the unit id, the dossier path and the row count of each dossier table.

Code: `unit.main`, `unit.dossier`.

```bash
urbanstyle unit broadway-granville --at -123.138546 49.263611 --osm ../duckOSM/data/db/vancouver_city.duckdb --city Vancouver --vancouver \
    --gtfs https://gtfs-static.translink.ca/gtfs/google_transit.zip
```

## bridge

`bridge` writes one bridge profile for each road bridge in a duckOSM database.

```text
urbanstyle bridge osm gmns out_dir [--name NAME]
```

| Argument or option | Meaning | Default |
|---|---|---|
| `osm` | The duckOSM `.duckdb` that holds all of the bridge. | required |
| `gmns` | The GMNS export of `osm` (`duckosm gmns OSM --out GMNS -m driving`). It gives the lanes. | required |
| `out_dir` | The folder for the profiles. `bridge` makes it if it does not exist. | required |
| `--name` | The OSM name of one bridge (`man_made=bridge`). Without it, `bridge` writes every road bridge. | none |

Output: one `<slug>.bridge.json` for each bridge in `out_dir`. `bridge` prints the path of each file. The format is in [The bridge profile](../design/levels.md#the-bridge-profile).

Code: `bridge_profile.write`.

```bash
urbanstyle bridge data/vancouver_city.osm.duckdb data/vancouver_city.gmns.duckdb data/bridges --name "Granville Bridge"
```

## bridge-measure

`bridge-measure` replaces the deck heights of a bridge profile with heights measured from airborne LiDAR.

```text
urbanstyle bridge-measure profile out --lidar LIDAR [LIDAR ...] [--osm OSM]
```

| Argument or option | Meaning | Default |
|---|---|---|
| `profile` | A `<name>.bridge.json` from `urbanstyle bridge`. | required |
| `out` | The measured profile: a `.json` file or a folder. In a folder, the file name is the name of `profile`. | required |
| `--lidar` | One or more ducklidar Parquet tiles that cover the bridge. | required |
| `--osm` | The duckOSM `.duckdb` of the profile. If OSM ends a ramp in the air, the ramp continues along the road that continues it. | none |

Output: the measured profile. `bridge-measure` prints its path.

Code: `bridge_lidar.write`.

```bash
PYTHONPATH=src:../ducklidar/src ~/miniconda3/envs/lidar/bin/python -m urbanstyle bridge-measure \
    data/bridges/granville-bridge.bridge.json data/bridges-measured/ --lidar <ducklidar Parquet tiles>
```

## bridge-heights

`bridge-heights` sets the heights of a bridge profile from a heights file, with no LiDAR.

```text
urbanstyle bridge-heights profile heights out
```

| Argument | Meaning | Default |
|---|---|---|
| `profile` | A `<name>.bridge.json` from `urbanstyle bridge`. | required |
| `heights` | The heights file: `{bridge name: {default: {grade, max_m, curve_m}, axis: [[s, height], ...] or {from, to_ground}}}`. | required |
| `out` | The profile with these heights. | required |

Output: the profile `out`. Only the `vertical` of each axis changes. `bridge-heights` prints the number of axes and the path of `out`. The file format is in [Bridge heights without LiDAR](../design/levels.md#heights-from-a-file).

Code: `bridge_heights.write`.

```bash
urbanstyle bridge-heights data/bridges/granville-bridge.bridge.json data/bridges/granville-heights.example.json data/bridges/granville-bridge.heights.bridge.json
```

## bridge2d

`bridge2d` writes the bridge model in 2D as GeoJSON, with the id of each part.

```text
urbanstyle bridge2d profile out [--db DB]
```

| Argument or option | Meaning | Default |
|---|---|---|
| `profile` | A measured `<name>.bridge.json`. | required |
| `out` | The GeoJSON file. `viz/bridge2d.html` reads `viz/bridge2d.geojson`. | required |
| `--db` | The space database of a unit. The level-0 lanes within 50 m of the deck give the landings. | none |

Output: a GeoJSON `FeatureCollection`, one feature for each part, with the properties `kind` and `color`. `bridge2d` prints the number of parts and the path of `out`.

Code: `bridge2d.write`.

```bash
urbanstyle bridge2d data/bridges-measured/granville-bridge.bridge.json viz/bridge2d.geojson --db data/units/broadway-granville.urban.duckdb
```

## bridge3d

`bridge3d` writes only the 3D models of the bridges, for a dashboard page that already exists.

```text
urbanstyle bridge3d db out --bridge BRIDGE [--bridge BRIDGE ...]
```

| Argument or option | Meaning | Default |
|---|---|---|
| `db` | The space database of a unit. The lanes of its street give the landings. | required |
| `out` | The JSON file next to the dashboard page, for example `viz/bridge3d.json`. | required |
| `--bridge` | A bridge profile, as for `dashboard`. You can give the option more than one time. | required |

Output: the JSON file `out`. The dashboard page reads it when it opens, so a page reload shows the change. `bridge3d` prints the path of `out`.

Code: `dashboard.bridge_models`, `dashboard.write_bridge3d`.

```bash
urbanstyle bridge3d data/units/broadway-granville.urban.duckdb viz/bridge3d.json --bridge data/bridges-measured/granville-bridge.bridge.json
```

## serve

`serve` serves a dashboard page with the Explore panel (search, filters and AI questions) on a local web server.

```text
urbanstyle serve db page [--bridge BRIDGE] [--port PORT]
```

| Argument or option | Meaning | Default |
|---|---|---|
| `db` | The space database of a unit. | required |
| `page` | A page that `urbanstyle dashboard` built. `serve` serves the folder of the page. | required |
| `--bridge` | A bridge profile. Its parts are also in the search. You can give the option more than one time. | none |
| `--port` | The port on `127.0.0.1`. The Street View key allows port 8784 only. | `8784` |

Output: `serve` prints the page URL, `http://localhost:<port>/<page>`, and runs until Ctrl+C. The AI questions use an Anthropic key (`ANTHROPIC_API_KEY` or `~/.config/anthropic/key`). If there is no Anthropic key, they use Gemini (`GEMINI_API_KEY`).

Code: `serve.serve`.

```bash
urbanstyle serve data/units/broadway-granville.urban.duckdb viz/broadway-granville.html --bridge data/bridges-measured/granville-bridge.bridge.json
```

## publish

`publish` writes the dashboard as static files, for a web site with no server. In the browser, Find and Filter use DuckDB-WASM on the
area's Parquet files, and Ask calls Gemini.

```text
urbanstyle publish db out_dir [--bridge BRIDGE]
```

| Argument or option | Meaning | Default |
|---|---|---|
| `db` | The space database of a unit. | required |
| `out_dir` | The folder to write. | required |
| `--bridge` | A bridge profile. You can give the option more than one time. | none |

Output: `out_dir/index.html` (the page with the panel), `static.js`, `bridge3d.json`, and `data/`: `meta.json`, `tree.json`,
`focus.json` and one Parquet file per `space` table. Mapillary's tables are left out (CC BY-SA). The keys are placeholders:
`__CARTO_DEMO_KEY__`, `__GOOGLE_MAPS_DEMO_KEY__` and `__GEMINI_DEMO_KEY__`. The site's deploy replaces them with its secrets
(`.github/workflows/docs.yml`). A visitor can also give their own Gemini key in the Ask tab.

Code: `publish.publish`. Design: [The dashboard online](../design/dashboard.md#the-dashboard-online).

```bash
urbanstyle publish data/units/broadway-granville.urban.duckdb demo --bridge data/bridges-measured/granville-bridge.bridge.json
tar -czf demo.tar.gz -C demo . && gh release upload demo-data demo.tar.gz --clobber
```
