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
  <img src="https://raw.githubusercontent.com/Khoshkhah/urbanstyle/main/docs/img/hero.png" alt="Monte Carlo built by urbanstyle: travel lanes in grey, sidewalks, furnishing and frontage strips in sand tones, buildings in charcoal, street trees in green" width="900">
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
```

## What you get

- **A measured street space.** Cross-section rays every 3 m out to the building faces: the right-of-way as it is, not a buffer of constant width.
- **A clean partition.** Sections, intersections, path spaces, rail spaces and plazas: no overlaps, no gaps, one connected polygon each, checked on every build.
- **Levels −2 … 2.** Bridges over, tunnels and metro stations under, and the ramps, stairs, lifts and entrances that link them.
- **Strips and objects.** Every container filled with typed bands (travel, cycle, sidewalk, furnishing, frontage) and the trees, lamps, benches and crossings that stand in it.
- **Stable ids.** `s0-<edge>` for a section, `i0-<node>` for an intersection: the same after every rebuild.

<p align="center">
  <img src="https://raw.githubusercontent.com/Khoshkhah/urbanstyle/main/docs/img/partition.png" alt="The same patch by container kind: sections in violet, intersections in amber, path spaces in green, plazas in red" width="900"><br>
  <sub>The partition: sections violet, intersections amber, path spaces green, plazas red.</sub>
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

Alpha. Monaco and Södermalm (Stockholm) are the two pilots and pass the hard checks. Boundaries (walls, fences), the
axis with `(s, t)` positions and a cross-section detail view are next: see the
[roadmap](https://khoshkhah.github.io/urbanstyle/plan/).

## For AI agents

[`AGENTS.md`](AGENTS.md) has the layout, the commands and the project's rules. The docs as text:
[`llms.txt`](https://khoshkhah.github.io/urbanstyle/llms.txt) and [`llms-full.txt`](https://khoshkhah.github.io/urbanstyle/llms-full.txt).

## License

MIT
