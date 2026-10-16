# AGENTS.md

Rules for AI coding agents (Claude Code, Codex, Cursor, Copilot, Gemini, …) working on this repository.

## What this is

urbanstyle builds a level-aware **space container** for the Stockholm (Södermalm) and Monaco pilots from one duckOSM
database: buildings, the street space between them (right-of-way) split into travelway and pedestrian realm, and the
links between levels (−2 … 2). Design and decisions: `docs/design/street-space.md` (**read it first**). What goes
*inside* a street space (objects, strips, boundaries, the (s, t) standard): `docs/design/street-objects.md`. How others
partition a street space and whether an intersection belongs to a street: `docs/design/partitioning-research.md`.
The order of work: `docs/plan.md`. The state at the last session's end and the open items: `docs/HANDOFF.md` (read it before
starting work). The agreed model of sections, intersections and the frame, which the code is being brought to:
`docs/design/sections.md` (2026-10-16).

## Layout

- `src/urbanstyle/container.py` is SQL generation: `BUILD` (buildings), `ROADS`, `CLAMP` (levels −2…2), `CONTAINER`
  (street space by cross-section rays, then the partition into streets, path spaces and intersections, zones,
  containers), `LINKS`, `RAIL`, `STATIONS`, `OBJECTS`. Everything lands in the `space` schema: `element`, `container`,
  `zone`, `link`, `street`, `arm`, `station`, `object`, `strip`. A container is a section (a stretch of a street
  between two junctions), a path space, a rail space, a plaza or an intersection; ids are `s<level>-<edge>`,
  `p<level>-<way>`, `r<level>-<way>`, `i<level>-<node>`. A street is a group of sections plus the intersections it
  arrives at (`space.street`, `space.arm`, id `k<level>-<way>`). `street_owner()` (python) decides which street each
  element belongs to.
- `space.lot` (`LOTS` in container.py): off-street car parks, plots beside the street like buildings; the partition reads both as the
  building line; parking aisles are left out of the roads.
- `src/urbanstyle/blocks.py` (called before `ground.build`): the blocks of `docs/design/blocks.md` (step 1): `space.block` (id
  `b<level>-w<way><side>`), `space.block_side` (each street side's distance and what set it: parcels, sidewalks, class, building),
  `space.area` (the area's edge), `space.city_block` (a city's own blocks, only for check B6).
- `src/urbanstyle/network.py` (after `blocks.build`): the street at level 0 from the road network, data first (`docs/design/pipeline.md`
  steps 2-7, rules in `docs/design/street-rules.md`, junctions in `docs/design/junctions.md`): lanes from OSM centred on each road's OSM
  line; parking and bike lanes only from OSM or a city's meters and bikeways; the kerb is the lanes' outer edge (never guessed); junctions
  only at nodes of 3+ road ends where a road ends, merges, forks or two streams cross, each arm cut square at its stop line; a road under 40 m or a
  `_link` between two junction nodes is a connector inside the intersection (`docs/design/sections.md` rules 1-4, 2026-10-16); sections along each road between junctions, the OSM ways chained
  (`s0-w<way>[.n]/<k>`: the longest way names it, `/k` its subsections where the cross-section changes), one frame per section (the widest
  cross-section, no line moved, no kerb taper; every tag change classified in `space.change`: `docs/design/sections.md` rules 5-8 and section 3, 2026-10-16; at a merge or fork the wider
  section keeps the through arm's kerb, `subsection.left_extra`; an island begins where the strip between two frames is 2 m wide: the rules
  from the Vancouver spots, 2026-10-16); the
  pedestrian side shared to the nearest roadway, a piece between roadways an island; stop lines, crosswalk parts with their paint from
  `crossing:markings`. It writes the level-0 rows of `space.unit`, `part`, `mark`, `subsection`, `junction`
  (other levels: `spaces.py`, `parts.py`; a level-1 way it puts on the ground loses its level-1 copy). `src/urbanstyle/turns.py` (after
  `network.build`): SUMO's lane-to-lane moves at level 0 (`space.turn`, `guide line` and `arrow` marks). There is one version: the old block-first division is
  removed (2026-10-14).
- `src/urbanstyle/ground.py` (called at the end of `build`): layer 0 of `docs/design/space-layers.md`, `space.ground`: every piece of the
  area at level 0 is water, rail, street, path, square, structure, green, plot or unknown (checks G1, G2); `space.parcel`, a city's
  parcels, is the property line the street reaches (`subsections.building_line`). `ground.surfaces`: layer 1, `space.surface`, the
  surfaces covering each ground item (roadway, pedestrian realm, median, verge; building, yard, car park, ...; checks L1, L2).
  `urbanstyle layers DB OUT.html` (`dashboard.layers`) shows, one at a time and in this order, the blocks, the street spaces
  (sections, subsections, intersections), layer 0, layer 1 and the parts; in each, its kinds can be ticked or shown alone; the main dashboard has a
  `Blocks` overlay (off at first, level 0).
- `src/urbanstyle/buildings.py` (called in `build`): each building's `use` and `ground_use` with their source and method, from OSM's
  `building` tag, the shops OSM maps inside it and a city's storefronts (`<unit>.vancouver.json`); `uses` lists the evidence.
- `src/urbanstyle/strips.py` (called at the end of `build`) fills every container with typed bands in `space.strip`
  (`docs/design/street-strips-v1.md`; check C2). `space.object` holds the point objects (taxonomy in
  `docs/design/street-objects-step1.md`).
- `src/urbanstyle/checks.py`: the invariants of `docs/design/street-space-spec.md` section 8. `quality.py`: section
  shape over a whole area.
- The dashboard, one for every area (2026-10-13; `docs/design/dashboard.md`, "How the page is made"): `src/urbanstyle/page.py`
  (`urbanstyle dashboard DB viz/<area>.html`) writes the page with the area's data only (roadstyle's map with the current model's
  layers, all hidden at first, and `window.US_CFG`); the map engine `engine.js` (3D, levels, bridges, Street View) and the panel
  `panel.js` + `panel.css` are not in the page: `serve` gives them from the package on every request (`page.ASSETS`), `publish` copies
  them beside the page. A change to the engine or the panel needs a reload, not a page build. The panel sets the first look under a
  veil (`#xpveil`), then lifts it. `dashboard.py` keeps the data helpers (matched objects, 3D furniture, bridge models), its old page
  (`main`: no longer used) and the layers page. Old page builds are in `data/old-pages/`, not served. Layer ids differ per overlay:
  always pass the overlay label.
- `src/urbanstyle/subsections.py`, `spaces.py` and `parts.py` (called at the end of `build`): the network-first partition, a preview
  (`docs/design/network-first.md`, `docs/design/space-parts.md`): `space.subsection` (roads divided where cross-section or frontage
  changes), `space.unit` (one space per subsection and per intersection, cut at the block corners, `space.cut`), and inside each space
  `space.part` (lanes in/out or forward/backward, junction area, crosswalks, cycle lanes, sidewalk bands), `space.mark` (kerb, centre,
  lane, stop and give-way lines, turn arrows), `space.width` (widths per arm / across each subsection) and `space.turn` (lane-to-lane moves
  at intersections). The roadway (lanes, junction shapes, turns) comes from SUMO: the subsections measure the lanes, `sumo.py` runs
  duckOSM's `to_sumo` with them, `from_sumo()` fills every unit; without SUMO `classic()` builds the roadway from bands. `urbanstyle check`
  U1-U10 test them; U11-U13 report the lanes entering each junction (`space.approach`),
  G1-G2 the ground (`space.ground`), L1-L2 the surfaces (`space.surface`), B1 and B6 the blocks (`space.block`); A1-A3, J1-J2, X1, M1, K1 the
  agreed street rules (`docs/design/street-rules.md`); R1-R4 the roadway at
  level 0: R1 its edges at the joints (a step only at a `real` change), R4 the lanes that meet their continuation there (tapers); J3 every connector
  inside an intersection, J4 (INFO) the tag changes along the sections with their classes.
  `urbanstyle check DB --bridge PROFILE` adds BR1-BR8, the bridge model's own checks (`bridge3d.model_checks`: guard on a lane,
  holes, guard gaps, paths on paths, slivers, lanes of two axes overlapping, lanes with no arrow, steps at landings) and BR9-BR11 (deck no
  part covers, a lane meeting a path with no barrier but at a crosswalk, steps in the deck's height) and BR12 (a surveyed or OSM street object standing inside a lane near the ground: the lane is wrong there), each with `?at=` links.
- `src/urbanstyle/mapillary.py`: `urbanstyle mapillary DB [--osm OSM]` fetches Mapillary's features and photos into `DB.mapillary.json`
  (token: `$MAPILLARY_TOKEN` or `~/.config/mapillary/token`, never in the repo) and loads `space.observed` / `space.photo`; `build`
  loads that file when present (`docs/design/mapillary.md`). CC BY-SA: the data stays local. Mapillary is for validation only
  (`unit.CONFIRM_ONLY`, 2026-10-10): it builds no object, part or line; it confirms the objects of sources with real positions, and what
  it alone sees is a `check` row; on the page it is hidden until "Mapillary detections (validation)" is ticked.
- `src/urbanstyle/bridge_profile.py`: `urbanstyle bridge OSM_DB GMNS_DB OUT_DIR [--name NAME]` writes one `<name>.bridge.json` per road
  bridge (`docs/design/bridge-profile.md`): deck outline, axes, vertical profiles, sections, bands (lanes from duckOSM's GMNS export:
  `duckosm gmns OSM --out GMNS -m driving`), piers, each value with its source and method. `bridge3d.py` draws the 3D model from the
  profile only: `urbanstyle dashboard DB OUT --bridge PROFILE` (`docs/design/bridges-3d.md`).
- `src/urbanstyle/bridge_lidar.py`: `urbanstyle bridge-measure PROFILE OUT --lidar TILE.parquet ...` replaces a profile's chosen deck heights
  with the ones measured from airborne LiDAR (ducklidar's Parquet tiles; run it in the conda env `lidar` with `../ducklidar/src` on the
  path): the deck top above the ground every 10 m along each axis, each station in `vertical.stations` (`docs/design/bridge-profile.md`).
- `src/urbanstyle/bridge_heights.py`: `urbanstyle bridge-heights PROFILE HEIGHTS OUT` sets a profile's heights from a small heights file where
  there is no LiDAR: points per axis, a ramp from another axis down to the ground, or the default rule (`docs/design/bridge-heights.md`).
- `src/urbanstyle/serve.py` and `panel.js`: `urbanstyle serve DB PAGE [--bridge PROFILE] [--port 8784]` serves `viz/` with one panel
  (`docs/design/dashboard.md`): Find (search, an exact id, the area's tree with tick boxes), Filter, Ask (an AI agent: Claude with
  `ANTHROPIC_API_KEY` or `~/.config/anthropic/key`, else Gemini with `GEMINI_API_KEY`, never keys in the repo); results orange,
  the selected thing deep purple with its card (no popup); levels full / faded / hidden in 2D and 3D; a street space, block
  or tree group in focus in 3D: the buildings that frame it (`Area.bounding`: seen from it within 10 m) solid, the other buildings
  see-through (`bldFade`), painted lines and crosswalks never faint. A street object selected in 3D: the camera along its street (`nearRoad`). The server reads the space db read-only, adds `space.bridge_part` and `space.street_object` (every
  source, as 3D draws them); the panel's names start with `xp`, inside one function (roadstyle's globals).
- `src/urbanstyle/publish.py` and `static.js`: `urbanstyle publish DB OUT_DIR [--bridge PROFILE]`, the dashboard as static files for the
  docs site (`docs/design/online-dashboard.md`): Parquet files, DuckDB-WASM and Gemini in the browser; no Mapillary; the keys as
  placeholders that `.github/workflows/docs.yml` fills from the repository's secrets, from the release `demo-data` (`demo.tar.gz`).
- The format and the standards: `docs/design/standards-comparison.md` (research), `docs/design/format.md` (requirements: a CityGML 3.0
  profile as a CityJSON Extension; ids from profiles).
- `src/urbanstyle/cli.py`: the `urbanstyle build | check | quality | dashboard | layers | mapillary | unit | bridge | bridge-measure | bridge-heights | bridge3d | serve` command.
- `docs/`: the MkDocs site (`mkdocs.yml`); `docs/design/` the design notes. `docs/img/sodermalm.jpg` and `section.jpg` are screenshots of the dashboard
  (`viz/sodermalm-rs0.18.1.html` and `#c=s0-1277220079715399641`, 1600 × 1000): pictures in the docs come from the
  dashboard, never from a separate drawing script.

## Commands

```bash
P=/home/kaveh/projects/duckOSM/.venv/bin/python        # duckdb + spatial + duckOSM; has no recent roadstyle
$P -m pytest -q                                        # 31 tests, offline (the turns test needs netconvert) (pythonpath=src from pyproject), ~10 s
$P -m pytest -q tests/test_levels.py::test_street_space_width      # one test
URBANSTYLE_BRIDGE_TESTS=1 $P -m pytest -q tests/test_bridge_rules.py   # the bridge's rules BR1-BR12 on the real bridge (~3.5 min, local data/)

# build a container (Monaco ~20 min and ~2.5 GB, measured 2026-10-13; Södermalm ~7 GB: check free memory first). Södermalm has no
# features schema, so a copy data/sodermalm.osm.duckdb is made and its features built from raw.*
PYTHONPATH=src $P -m urbanstyle build ../duckOSM/monaco.duckdb data/monaco.duckdb
PYTHONPATH=src $P -m urbanstyle build ../duckOSM/data/db/sodermalm.duckdb data/sodermalm.duckdb
PYTHONPATH=src $P -m urbanstyle check data/monaco.duckdb data/sodermalm.duckdb
# a fix in network.py or ground.py: only those steps, from the copy the last full build kept (OUT.before-division): Monaco minutes,
# not 27 min; the build prints each step's time
PYTHONPATH=src $P -m urbanstyle build ../duckOSM/monaco.duckdb data/monaco.duckdb --from division
# an area with bridges (every area whose roads reach level 1): their profiles first, then every later step with --bridge. Without them
# a deck is drawn flat in the air with no lanes (`dashboard` warns). Monaco, 2026-10-14: 11 profiles in 1 s, the checks ~2 min
../duckOSM/.venv/bin/duckosm gmns ../duckOSM/monaco.duckdb --out data/monaco_gmns.duckdb -m driving     # the lanes (GMNS)
PYTHONPATH=src $P -m urbanstyle bridge ../duckOSM/monaco.duckdb data/monaco_gmns.duckdb data/bridges-monaco   # one profile per road bridge
#   heights: LiDAR where there is some (`bridge-measure`), else `bridge-heights` with a heights file; the profile's own rule otherwise
PYTHONPATH=src $P -m urbanstyle build ../duckOSM/monaco.duckdb data/monaco.duckdb --bridge data/bridges-monaco/*.bridge.json
PYTHONPATH=src $P -m urbanstyle check data/monaco.duckdb --bridge data/bridges-monaco/*.bridge.json        # BR1-BR12 per bridge
#   (every command takes --bridge with one or more profiles, and the option can repeat)

# dashboard: system python3 with the development roadstyle (../roadstyle/src; PyPI's 0.13.1 lacks `color_col`), then serve it; Street View
# needs http. The CARTO base map needs CARTO_API_KEY in the environment when the page is BUILT (~/.bashrc exports it; a non-interactive
# shell does not read it: `export CARTO_API_KEY=...` first, else the tiles say API KEY REQUIRED)
PYTHONPATH=src:../roadstyle/src python3 -m urbanstyle dashboard data/monaco.duckdb viz/monaco.html
(cd viz && python3 -m http.server 8784 --bind 127.0.0.1)   # viz/<area>.html#c=<container id> opens one container
# Street View's linked panorama: GOOGLE_MAPS_KEY, set when the page is BUILT (the roadstyle conda env sets it on activate; with the
# system python3: `source ~/miniconda3/envs/roadstyle/etc/conda/activate.d/google_maps_key.sh` first). Its Google restriction allows
# http://localhost:8784/* only: serve the pages on port 8784. Clicks inside a focused space move the Street View window too (svHere in dashboard.py).

# a bridge change: only its model, to viz/<page>.bridge3d.json, which that page reads when it opens (reload the page). The model is
# kept in data/cache/ (key: the profile, the street's lanes, corrections/*.json and bridge3d.py with the modules it reads): with no change
# there, the page builds in ~30 s and this in ~2 s
PYTHONPATH=src $P -m urbanstyle bridge3d data/units/broadway-granville.space.duckdb viz/broadway-granville.bridge3d.json --bridge data/bridges-measured/granville-bridge.bridge.json

# the dashboard with its panel (search, filters, the tree, the AI agent): system python3 with roadstyle; then http://localhost:8784/
# One server serves ONE area (its /api/ answers for that db: levels, tree, search): a second area's page in the same viz/ needs its own
# server on another port (Monaco: --port 8785), else the page shows the first area's levels (2026-10-16).
PYTHONPATH=src:../roadstyle/src python3 -m urbanstyle serve data/units/broadway-granville.space.duckdb viz/<page>.html --bridge data/bridges-measured/granville-bridge.bridge.json
PYTHONPATH=src python3 -m pytest -q tests/test_serve.py    # the Gemini test needs google-genai: the system python3 has it, the venv not

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
- 2D and 3D are two views of the same data, two separate layer sets (`setView`, `draw3d` in dashboard.py); switching shows one set
  and hides the other. 2D is a map: roads as lines, one dot per street object, building footprints, spaces and cuts as outlines; the
  real-size road surface only with "road surface in 2D". 3D (roadstyle's 3D button) is the street: every space's ground on the level
  (roadway flat, sidewalks and islands raised, kerbstones), the painted lines and the lane-to-lane guide lines, buildings at their real
  height (`space.element.floors`, `height_m`: before levels are clamped to -2..2), bridge decks 6 m a level, one model per street
  object (`matched_objects`: OSM, Mapillary and a city's survey matched by `unit.match`; `furniture_3d`). In 3D a hover lights a lane,
  kerb, building or object and names its type; a click selects it and opens its popup (the same fields as in 2D: OBJ_POPUP,
  BLD_POPUP, the Parts popup; with `urbanstyle serve` no popup, the panel's card); Esc, a second click or closing the popup deselects. A hover lights a thing only once the mouse rests on it
  300 ms (HOVER_MS; in 2D roadstyle's `hover_delay_ms`). Street View in 3D: every click moves an open window to the nearest road or bridge axis (svHere, `window.brAxes`),
  because 3D hides the road lines roadstyle's Street View follows. 2D overlays' wanted visibility is roadstyle's
  `ov.visible`; a 3D layer is never drawn in 2D. Terrain only when "rough terrain" is ticked: the public AWS Terrain Tiles (~30 m) are
  too coarse for Monaco and broke the map; needs a 1-5 m terrain.
  Tunnels in 3D (`u3d-tun`): flat under level 0's ground (the map draws nothing below 0); they show where level 0 is faded or hidden.
  "low buildings" (and a selected street object): buildings at most `LOW_M` (3 m) high. Each level but 0 has its own 3D layer (`u3d-deck<l>`,
  `u3d-tun<l>`), so every level button fades or hides its own level in 3D.
- A unit's city data (`<unit>.vancouver.json`, the dossier `<unit>.duckdb`, `<unit>.space.duckdb.mapillary.json`) is found by the
  output's file name: build to `<unit>.space.duckdb` in the same folder (or link those files beside a scratch build of that name).
  A build named otherwise gets no parcels, no kerb evidence from the city and no bikeways, and nothing fails (2026-10-14).
- Heavy imports (shapely, pandas, geopandas, roadstyle) stay inside functions so the CLI starts fast.

## Rules

- The repo is public. Commits use the GitHub noreply address (repo-local `user.email`), never a personal email.
- Work on the two pilots, Monaco and Södermalm; a new area is a roadmap step, not a side effect.
- A change to how containers are cut: run `urbanstyle check` on both pilots and report the counts before and after.
- Non-trivial features: write a design note in `docs/design/` and agree it before coding; update `docs/plan.md`.
- Keep `docs/design/glossary.md` in step with new words, columns and ids.
