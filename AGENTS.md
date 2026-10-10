# AGENTS.md

Rules for AI coding agents (Claude Code, Codex, Cursor, Copilot, Gemini, …) working on this repository.

## What this is

urbanstyle builds a level-aware **space container** for the Stockholm (Södermalm) and Monaco pilots from one duckOSM
database: buildings, the street space between them (right-of-way) split into travelway and pedestrian realm, and the
links between levels (−2 … 2). Design and decisions: `docs/design/street-space.md` (**read it first**). What goes
*inside* a street space (objects, strips, boundaries, the (s, t) standard): `docs/design/street-objects.md`. How others
partition a street space and whether an intersection belongs to a street: `docs/design/partitioning-research.md`.
The order of work: `docs/plan.md`.

## Layout

- `src/urbanstyle/container.py` is SQL generation: `BUILD` (buildings), `ROADS`, `CLAMP` (levels −2…2), `CONTAINER`
  (street space by cross-section rays, then the partition into streets, path spaces and intersections, zones,
  containers), `LINKS`, `RAIL`, `STATIONS`, `OBJECTS`. Everything lands in the `space` schema: `element`, `container`,
  `zone`, `link`, `street`, `arm`, `station`, `object`, `strip`. A container is a section (a stretch of a street
  between two junctions), a path space, a rail space, a plaza or an intersection; ids are `s<level>-<edge>`,
  `p<level>-<way>`, `r<level>-<way>`, `i<level>-<node>`. A street is a group of sections plus the intersections it
  arrives at (`space.street`, `space.arm`, id `k<level>-<way>`). `street_owner()` (python) decides which street each
  element belongs to.
- `src/urbanstyle/strips.py` (called at the end of `build`) fills every container with typed bands in `space.strip`
  (`docs/design/street-strips-v1.md`; check C2). `space.object` holds the point objects (taxonomy in
  `docs/design/street-objects-step1.md`).
- `src/urbanstyle/checks.py`: the invariants of `docs/design/street-space-spec.md` section 8. `quality.py`: section
  shape over a whole area.
- `src/urbanstyle/dashboard.py` only reads those tables; it builds a roadstyle map (overlays for buildings, zones,
  links, strips, objects) plus a tree panel driven by roadstyle's `rs*` JS API. Layer ids differ per overlay: always
  pass the overlay label.
- `src/urbanstyle/subsections.py`, `spaces.py` and `parts.py` (called at the end of `build`): the network-first partition, a preview
  (`docs/design/network-first.md`, `docs/design/space-parts.md`): `space.subsection` (roads divided where cross-section or frontage
  changes), `space.unit` (one space per subsection and per intersection, cut at the block corners, `space.cut`), and inside each space
  `space.part` (lanes in/out or forward/backward, junction area, crosswalks, cycle lanes, sidewalk bands), `space.mark` (kerb, centre,
  lane, stop and give-way lines, turn arrows), `space.width` (widths per arm / across each subsection) and `space.turn` (lane-to-lane moves
  at intersections). The roadway (lanes, junction shapes, turns) comes from SUMO: the subsections measure the lanes, `sumo.py` runs
  duckOSM's `to_sumo` with them, `from_sumo()` fills every unit; without SUMO `classic()` builds the roadway from bands. `urbanstyle check`
  U1-U9 test them.
- `src/urbanstyle/mapillary.py`: `urbanstyle mapillary DB [--osm OSM]` fetches Mapillary's features and photos into `DB.mapillary.json`
  (token: `$MAPILLARY_TOKEN` or `~/.config/mapillary/token`, never in the repo) and loads `space.observed` / `space.photo`; `build`
  loads that file when present (`docs/design/mapillary.md`). CC BY-SA: the data stays local.
- `src/urbanstyle/cli.py`: the `urbanstyle build | check | quality | dashboard | mapillary` command.
- `docs/`: the MkDocs site (`mkdocs.yml`); `docs/design/` the design notes. `docs/img/sodermalm.jpg` and `section.jpg` are screenshots of the dashboard
  (`viz/sodermalm-rs0.18.1.html` and `#c=s0-1277220079715399641`, 1600 × 1000): pictures in the docs come from the
  dashboard, never from a separate drawing script.

## Commands

```bash
P=/home/kaveh/projects/duckOSM/.venv/bin/python        # duckdb + spatial + duckOSM; has no recent roadstyle
$P -m pytest -q                                        # 26 tests, offline (the turns test needs netconvert) (pythonpath=src from pyproject), ~10 s
$P -m pytest -q tests/test_levels.py::test_street_space_width      # one test

# build a container (Monaco ~1 min; Södermalm ~18 min and ~7 GB: check free memory first). Södermalm has no
# features schema, so a copy data/sodermalm.osm.duckdb is made and its features built from raw.*
PYTHONPATH=src $P -m urbanstyle build ../duckOSM/monaco.duckdb data/monaco.duckdb
PYTHONPATH=src $P -m urbanstyle build ../duckOSM/data/db/sodermalm.duckdb data/sodermalm.duckdb
PYTHONPATH=src $P -m urbanstyle check data/monaco.duckdb data/sodermalm.duckdb

# dashboard: system python3 (roadstyle 0.13.1 from PyPI), then serve it; Street View needs http
PYTHONPATH=src python3 -m urbanstyle dashboard data/monaco.duckdb viz/monaco.html
(cd viz && python3 -m http.server 8765)                # viz/<area>.html#c=<container id> opens one container
# Street View's linked panorama: GOOGLE_MAPS_KEY (the roadstyle conda env sets it on activate; its Google restriction must allow
# http://localhost:8765/*). Clicks inside a focused space move the Street View window too (svHere in dashboard.py).

# docs
mkdocs build --strict                                  # needs pip install ".[docs]"
```

## Things that bite

- Headless browser tests (playwright, software GL) are very slow at street zoom (minutes): the JS is idle, the
  renderer stalls. Check the DOM, `rsQuery` counts and `map.getFilter`, not screenshots at high zoom. Use
  `wait_until="domcontentloaded"`.
- `CONTAINER` is a `str.format` template: any literal `{` `}` in it must be doubled. It is split at the
  `-- STREETS-SPLIT` and `-- INTERSECTIONS-SPLIT` markers: `street_owner()` and `intersection_shapes()` (shapely,
  lazy import) run between the parts. Container outlines are simplified by 0.05 m on purpose; larger tolerances
  bring the overlaps back.
- A "sidewalk" is geometric (a walkway/cycleway attached to a road, not a crossing or steps), not the
  `footway=sidewalk` tag: the tag covers only 6-9% of the walking ways. The travelway is measured to the nearest
  sidewalk (`hit_sw`, `twh`, `twq`).
- On a GeoDataFrame, `df.type` is the geometry-type attribute; use `df["type"]` for our `type` column.
- Containers are metric (UTM) inside the SQL and stored in lon/lat; the UTM zone comes from the mean longitude.
- The cross-section reach cap, widths and margins are flat guesses (see `docs/design/street-space.md`); the
  `open_share` column says how much of a width was capped rather than measured.
- roadstyle ids are not `edge_id`s (ids past 2**53); query with `rsQuery`, never pass `edge_id` to `rsSelect`.
- The dashboard's panel script shares the page's global scope with roadstyle's: a top-level name roadstyle already uses (`srcOf`,
  `map`, `OVERLAYS`, ...) throws and silently kills the WHOLE panel. Check new globals in a headless load (page errors) before shipping.
- Tilting the map (roadstyle's 3D button) shows only what exists, at real size (`draw3d` and `tilt2d` in dashboard.py): every space's
  ground on the level (the roadway flat with its painted lines, sidewalks and islands raised), buildings by floors x 3.2 m, the levels above
  as bridge decks 6 m a level, and one 3D object per real thing (`matched_objects`: OSM, Mapillary and a city's survey matched by
  `unit.match`; `furniture_3d`: lamp, signal, sign, tree at its surveyed height, bench, bin, meter, manhole, drain, ...; placed off the
  roadway by `placer`, except covers in the ground). The 2D symbols (centre lines, dots, icons, guide lines, the kerb line, cuts,
  footprints) are hidden while tilted and come back when flat; a hover shows only an object's type, a click its popup. Terrain only when
  "rough terrain" is ticked: the public AWS Terrain Tiles (~30 m) are too coarse for Monaco and broke the map; needs a 1-5 m terrain.
  "every space in detail" (on by default) shows every space's parts with nothing focused.
- Heavy imports (shapely, pandas, geopandas, roadstyle) stay inside functions so the CLI starts fast.

## Rules

- The repo is public. Commits use the GitHub noreply address (repo-local `user.email`), never a personal email.
- Work on the two pilots, Monaco and Södermalm; a new area is a roadmap step, not a side effect.
- A change to how containers are cut: run `urbanstyle check` on both pilots and report the counts before and after.
- Non-trivial features: write a design note in `docs/design/` and agree it before coding; update `docs/plan.md`.
- Keep `docs/design/glossary.md` in step with new words, columns and ids.
