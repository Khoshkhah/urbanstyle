# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

urbanstyle builds a level-aware **space container** for the Stockholm/Monaco pilots from one duckOSM
database: buildings, the street space between them (right-of-way) split into travelway and pedestrian
realm, and the links between levels (-2 … 2). Design and decisions: `docs/street-space.md` (read it first). What goes *inside* a street space (objects, strips, boundaries, the
(s, t) standard): `docs/street-objects.md`, a design that is not built yet. How others partition a street space and whether an intersection belongs to a
street: `docs/partitioning-research.md`.

## Commands

```bash
P=/home/kaveh/projects/duckOSM/.venv/bin/python        # duckdb + spatial; has no recent roadstyle
$P -m pytest -q tests                                  # 4 tests, offline, <1 s
$P -m pytest -q tests/test_levels.py::test_street_space_width      # one test

# build a container (Monaco ~1 min, Södermalm ~3 min); Södermalm has no features schema, so a copy
# data/sodermalm.osm.duckdb is made and its features built from raw.*
$P urbanstyle.py ../duckOSM/monaco.duckdb data/monaco.duckdb
$P urbanstyle.py ../duckOSM/data/db/sodermalm.duckdb data/sodermalm.duckdb

# dashboard: system python3 (roadstyle 0.13.1 from PyPI, pulls ortools + scipy), then serve it; Street View needs http
python3 dashboard.py data/monaco.duckdb viz/monaco.html
(cd viz && python3 -m http.server 8765)
```

## Architecture

- `urbanstyle.py` is SQL generation: `BUILD` (buildings), `ROADS`, `CLAMP` (levels -2…2), `CONTAINER`
  (street space by cross-section rays, then the partition into streets, path spaces and intersections, zones, containers), `LINKS`, `RAIL`, `STATIONS`, `OBJECTS`. Everything lands in the `space` schema:
  `element`, `container`, `zone`, `link`. A container is a section (a stretch of a street between two junctions), a path space, a rail space or an intersection;
  ids are `s<level>-<edge>`, `p<level>-<way>`, `r<level>-<way>`, `i<level>-<node>`. A street is a group of sections plus the
  intersections it arrives at (`space.street`, `space.arm`, id `k<level>-<way>`). `strips.py` (called at the end of `build`) fills every container with typed bands in `space.strip` (docs/street-strips-v1.md; check C2 in `checks.py`). `space.station` holds the stations, `space.object` the point objects (taxonomy in `docs/street-objects-step1.md`). `street_owner()` (python) decides which street each element belongs to.
- `dashboard.py` only reads those tables; it builds a roadstyle map (overlays for buildings, zones, links) plus a
  tree panel driven by roadstyle's `rs*` JS API. Layer ids differ per overlay: always pass the overlay label.

## Things that bite

- Headless browser tests (playwright, software GL) are very slow at street zoom (minutes): the JS is idle, the renderer stalls.
  Check the DOM, `rsQuery` counts and `map.getFilter`, not screenshots at high zoom. Use `wait_until="domcontentloaded"`.

- `CONTAINER` is a `str.format` template: any literal `{` `}` in it must be doubled. It is split at the `-- VORONOI-SPLIT`
  marker: `voronoi_owner()` (shapely, lazy import) runs between the two halves and fills `vown`. Container outlines are simplified by
  0.05 m on purpose; larger tolerances bring the overlaps back.
- A "sidewalk" is geometric (a walkway/cycleway attached to a road, not a crossing or steps), not the `footway=sidewalk` tag: the
  tag covers only 6-9% of the walking ways. The travelway is measured to the nearest sidewalk (`hit_sw`, `twh`, `twq`).
- On a GeoDataFrame, `df.type` is the geometry-type attribute; use `df["type"]` for our `type` column.
- Containers are metric (UTM) inside the SQL and stored in lon/lat; the UTM zone comes from the mean longitude.
- The cross-section reach cap, widths and margins are flat guesses (see `docs/street-space.md`); the
  `open_share` column says how much of a width was capped rather than measured.
- roadstyle ids are not `edge_id`s (ids past 2**53); query with `rsQuery`, never pass `edge_id` to `rsSelect`.
