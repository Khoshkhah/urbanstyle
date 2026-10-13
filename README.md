<p align="center">
  <img src="https://raw.githubusercontent.com/Khoshkhah/urbanstyle/main/docs/img/logo.svg" alt="urbanstyle" width="96">
</p>

<h1 align="center">urbanstyle</h1>

<p align="center">
  <b>An open format for city street space, and an open tool that builds it from open data.</b>
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
  <a href="https://khoshkhah.github.io/urbanstyle/plan/">Roadmap</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/Khoshkhah/urbanstyle/main/docs/img/focus.jpg" alt="Granville Street in focus in the urbanstyle dashboard: its lanes, markings and trees in color, everything else faint" width="800"><br>
  <sub>Granville Street, Vancouver, in focus in the 3D view of the dashboard. Map data © OpenStreetMap contributors, base map © CARTO.</sub>
</p>

urbanstyle takes the space between the buildings of a city and divides it the way a street engineer does: into sections and
intersections, and each of these into lanes, sidewalk zones, kerbs, crossings and painted lines. The street objects stand in it,
and bridges carry it at their measured heights. Every value names its source and how it was found: mapped in OpenStreetMap,
measured from LiDAR, taken from a city's survey, observed in street-level photos, or derived by urbanstyle.

## Quick start

```bash
pip install "urbanstyle[dashboard,osm] @ git+https://github.com/Khoshkhah/urbanstyle"
duckosm build --pbf monaco-latest.osm.pbf -o monaco.duckdb -m driving -m walking -m cycling
urbanstyle build monaco.duckdb data/monaco.duckdb
urbanstyle dashboard data/monaco.duckdb viz/monaco.html
urbanstyle serve data/monaco.duckdb viz/monaco.html      # then open http://localhost:8784/
```

## What you get

- **The street space as areas, in 3D:** sections, intersections, subsections and parts, at levels −2 … 2.
- **One object for each real thing,** matched from OpenStreetMap, a city's open data and Mapillary, with every source's id.
- **The source and the method of every value,** and checks that run on every build.
- **A dashboard for planners:** find, filter and ask questions in plain words, in 2D and 3D, with a street, section or block in focus.
- **Bridges from a profile:** axes, lanes, paths, barriers, piers and the deck's heights from LiDAR.

## Status

Alpha. The pilot area is West Broadway × Granville Street in Vancouver, with Granville Bridge. The format is a set of agreed
requirements: a profile of CityGML 3.0, written as a CityJSON Extension. Its first specification and an export come next, then a
second city. See the [roadmap](https://khoshkhah.github.io/urbanstyle/plan/).

## The family

| | |
|---|---|
| [duckOSM](https://github.com/Khoshkhah/duckOSM) | an OSM extract becomes a routable network in DuckDB; urbanstyle's input |
| [roadstyle](https://github.com/Khoshkhah/roadstyle) | styled, interactive road maps; draws urbanstyle's dashboard |
| [mapstyle](https://github.com/Khoshkhah/mapstyle) | the full base map |
| [lanestyle](https://github.com/Khoshkhah/lanestyle) | lane-level maps |
| **urbanstyle** | the street space between the buildings |

## For AI agents

[`AGENTS.md`](AGENTS.md) has the layout, the commands and the project's rules. The docs as text:
[`llms.txt`](https://khoshkhah.github.io/urbanstyle/llms.txt) and [`llms-full.txt`](https://khoshkhah.github.io/urbanstyle/llms-full.txt).

## License

MIT
