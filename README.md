<p align="center">
  <img src="https://raw.githubusercontent.com/Khoshkhah/urbanstyle/main/docs/img/logo.svg" alt="urbanstyle" width="96">
</p>

<h1 align="center">urbanstyle</h1>

<p align="center">
  <b>The street space of a city, level by level.</b><br>
  The right-of-way between the buildings, cut into sections and intersections, split into travelway and pedestrian realm, filled with strips and objects. From one duckOSM database.
</p>

<p align="center">
  <a href="https://github.com/Khoshkhah/urbanstyle/actions/workflows/test.yml"><img src="https://github.com/Khoshkhah/urbanstyle/actions/workflows/test.yml/badge.svg?branch=main" alt="Tests"></a>
  <a href="https://khoshkhah.github.io/urbanstyle/"><img src="https://img.shields.io/badge/docs-khoshkhah.github.io%2Furbanstyle-6a1b9a.svg" alt="Docs"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-3776AB.svg" alt="Python 3.10+">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT"></a>
</p>

<p align="center">
  <a href="https://khoshkhah.github.io/urbanstyle/"><b>Documentation</b></a> ·
  <a href="https://khoshkhah.github.io/urbanstyle/get-started/">Get started</a> ·
  <a href="https://khoshkhah.github.io/urbanstyle/plan/">Roadmap</a> ·
  <a href="https://khoshkhah.github.io/urbanstyle/design/street-space/">Design</a>
</p>

---

<p align="center">
  <img src="https://raw.githubusercontent.com/Khoshkhah/urbanstyle/main/docs/img/sodermalm.jpg" alt="The urbanstyle dashboard on Södermalm, Stockholm: the street space at level 0, sections in violet, intersections in amber, path spaces in green, plazas in red, buildings in blue, with the hierarchy tree on the left" width="900"><br>
  <sub>Södermalm, Stockholm, in the urbanstyle dashboard. Map data © OpenStreetMap contributors, base map © CARTO.</sub>
</p>

## Quick start

```bash
pip install "urbanstyle[dashboard,osm] @ git+https://github.com/Khoshkhah/urbanstyle"
```

```bash
duckosm build --pbf monaco-latest.osm.pbf -o monaco.duckdb -m driving -m walking -m cycling
urbanstyle build monaco.duckdb data/monaco.duckdb         # ~1 min for Monaco
urbanstyle check data/monaco.duckdb                       # the partition invariants: PASS / FAIL
urbanstyle dashboard data/monaco.duckdb viz/monaco.html   # an offline map with the hierarchy tree
urbanstyle unit broadway-granville --at -123.138546 49.263611 --osm vancouver_city.duckdb --vancouver \
    --gtfs https://gtfs-static.translink.ca/gtfs/google_transit.zip           # one unit in full: data/units/<name>.duckdb
```

## What you get

- **A measured street space.** Cross-section rays every 3 m out to the building faces: the right-of-way as it is, not a buffer of constant width.
- **A clean partition.** Sections, intersections, path spaces, rail spaces and plazas: no overlaps, no gaps, one connected polygon each, checked on every build.
- **Levels −2 … 2.** Bridges over, tunnels and metro stations under, and the ramps, stairs, lifts and entrances that link them.
- **Strips and objects.** Every container filled with typed bands (travel, cycle, sidewalk, furnishing, frontage) and the trees, lamps, benches and crossings that stand in it.
- **One unit in full.** One junction or street section with everything every source knows: lanes and turns (SUMO on duckOSM), kerbs, markings, parking with its rules, bus stops with their timetable, street objects matched across OSM, a city's survey and Mapillary, and each building's use and ground-floor use. Every item carries its source, method and confidence.
- **2D and 3D.** One page, two views of the same data: a map, and the street at real size where every lane, kerb, building and object can be selected.
- **Stable ids.** `s0-<edge>` for a section, `i0-<node>` for an intersection: the same after every rebuild.

<p align="center">
  <img src="https://raw.githubusercontent.com/Khoshkhah/urbanstyle/main/docs/img/section.jpg" alt="One section in focus in the dashboard: Dalslandsgatan, Södermalm, with its travel lane, cycle lane, sidewalk, furnishing and frontage strips, its entrances and the buildings that bound it" width="900"><br>
  <sub>Click a section: its strips, its objects and the buildings that bound it. Map data © OpenStreetMap contributors, base map © CARTO.</sub>
</p>

## The family

urbanstyle works on the same data as its siblings:

| | |
|---|---|
| [duckOSM](https://github.com/Khoshkhah/duckOSM) | `.osm.pbf` → a routable network in DuckDB; urbanstyle's input |
| [roadstyle](https://github.com/Khoshkhah/roadstyle) | styled, interactive road maps; draws urbanstyle's dashboard |
| [mapstyle](https://github.com/Khoshkhah/mapstyle) | the full base map |
| [lanestyle](https://github.com/Khoshkhah/lanestyle) | lane-level maps |
| **urbanstyle** | the space between the buildings |

## Status

Alpha. Since 2026-10-09 the work is **one unit in full**: W Broadway × Granville St in Vancouver, built from OSM, SUMO, the
City of Vancouver's open data, TransLink's timetable and Mapillary (for validation only), then compared with reality. Built so
far: parking, bus stops and building use; next are crossing and kerb details. The city-wide partition (Monaco and Södermalm, which
pass the hard checks) is paused. See the [roadmap](https://khoshkhah.github.io/urbanstyle/plan/).

## For AI agents

[`AGENTS.md`](AGENTS.md) has the layout, the commands and the project's rules. The docs as text:
[`llms.txt`](https://khoshkhah.github.io/urbanstyle/llms.txt) and [`llms-full.txt`](https://khoshkhah.github.io/urbanstyle/llms-full.txt).

## License

MIT
