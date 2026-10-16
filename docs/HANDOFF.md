# Handoff: the street at level 0, 2026-10-16

Status: written at the end of the 2026-10-15/16 session, updated in the night of 2026-10-16 after the Monaco fails. Read `AGENTS.md`
first, then this note, then `docs/design/street-rules.md` and `docs/design/sections.md`.

## Where the work stands

- `main` and `network-first` are one (2026-10-16, night): steps 2 and 3 of `sections.md`, the rules from the Vancouver spots, the
  dashboard's first-3D-draw fix, and the rules from the Monaco fails (`sections.md`, "The rules from the Monaco fails").
- Vancouver (`data/units/broadway-granville.space.duckdb`) is rebuilt with the final code: no count changed. Its fails: I3 1 (the
  old container step) and one BR12 (an object inside a bridge lane at the on-ramp foot, -123.135954 49.266514), as before.
- Monaco (`data/monaco.duckdb`) is rebuilt with the final code (`build --from division`: division 28 min, ground 7 min). From the
  start of the night to its end: U1 3, U4 3, U5 3, U6 2, U8 1, R1 4, J1 3, J2 1 all to 0; A3 12 to 1; A1 8 to 5; X1 0. Left: A1 5,
  A3 1, BR3 4 (Avenue de France), BR5 2 + 3 (Avenue de la Costa, Boulevard du Ténao); see the open items. Its page is
  `viz/monaco.html`, served on port 8785.
- Two servers run on this machine: Vancouver on port 8784, Monaco on port 8785. One server serves one area: its `/api/` answers
  for one database (levels, tree, search). Street View works on 8784 only, because of the key's restriction.
- Monaco cuts: `scratch/cut-monaco.py NAME LON LAT TAG SRC [RADIUS]` (a 250 m cut of `../duckOSM/monaco.duckdb`, a full build in 1-2
  min, the checks; the bridge profiles whose axes reach the cut go with it). `scratch/plot-place.py DB LON LAT RADIUS OUT.png` draws
  one place (parts, lines, units, junction nodes) into `viz/review/`. The Monaco duckOSM database is from an older duckOSM (no turn
  tables): the clip warns and goes on.
- Pictures of the night: `viz/review/monaco-*.png` (http://localhost:8785/review/monaco-spelugues.png and the others: before, and
  `-cut` after).

## The rules added this session

All in `docs/design/street-rules.md` (rules 7 to 13) and `docs/design/pipeline.md`. In short:

1. A junction arm is cut square at its stop line, never by a circle round the node (J2).
2. A node is a junction only where a road ends or two streams cross. A merge (a ramp into a road) is a joint, not a junction.
3. A section is the road between two junctions, whatever OSM ways it is made of, named by its longest way. Subsections where
   the cross-section changes.
4. Continuity at a joint: lanes that run on keep their position. The subsection's line is moved sideways by up to 2 m, OSM's
   drawing error. The kerb opposite a merging road continues. The piece at a bridge landing is the fixed one of its section.
5. Crosswalk parts for every crossing way and node, their paint from `crossing:markings` (X1).
6. Lines only between mapped lanes. The centre line of a chosen count is urbanstyle's own (M1).
7. A barrier named in a bridge's corrections continues on the ground along the landing way. The strip it runs along is an island.
8. A strip between two roadways is paved roadway, unless a kerb, an object, a path or a barrier is mapped on it. A corner touch of
   under 2 m is no contact with a block.
9. Block edges follow the footway, 1 m behind it, simplified by 0.5 m. Footways before parcels.
10. The kerb is one line per level, the roadway's outer edge, cut by the spaces, dropped at alley and driveway mouths (K2).
11. K1 reports where the kerb is far from the city's catch basins. It never moves anything.

## Corrections to OSM (data, not code)

`corrections/lanes.json`: w299511148 (3 lanes), w1210125710 (2 + 3), w1210125711 (2 + 2), read by Kaveh from the 2018 aerial
photo, with the older Granville Bridge entries. `corrections/bridges.json`: the Granville Bridge only. These are the only
place-specific inputs. The code names no place.

## The agreed direction (2026-10-16, evening)

`docs/design/sections.md`: one frame per section, merges and forks are junctions, a connector under 40 m belongs to the
intersection, every lane-count change classified before it touches the frame (J4), the line-moving rules removed. This comes before
every item below. Its order of work:

- Step 2 (rules 1-4: merges and forks as junctions, connectors, the intersection's area) is in `network.py` since 2026-10-16, tested on
  two 250 m cuts of the Vancouver unit only (`data/cuts/west8th`, `data/cuts/rampfoot`; the review page
  `viz/review/sections-step2/index.html`). Every hard check passes on both cuts. The unit and Monaco are not rebuilt with it.
  To judge, from the review page: the West 8th T on Fir Street's east carriageway stays its own intersection (OSM maps no road between
  the two carriageways), and a chain of merge nodes makes one intersection 80-90 m long (the on-ramp foot, West 4th × West 6th,
  Granville × West 6th). New INFO rows: K2 4 loose kerb ends at the ramp foot, R2 1 guide line, not looked at.
- The cuts: `scratch/cut.py NAME LON LAT TAG SRC` (clip, full build about 1 min, checks; `SRC` the source tree, so a `before` build
  runs from `git archive HEAD src`), `scratch/compare.py NAME LON LAT [RADIUS] [OUT]` (before / after picture into
  `viz/review/sections-step2/`). `scratch/` is git-ignored.
- Step 3 (the frame per section, rules 5-8; the change classes of section 3 in `space.change`; J3 and J4; the shift, the one-sided merge
  heading and the taper wedges removed; A1 at 0.5 m; R1 a FAIL except at a `real` change) is in `network.py` since 2026-10-16 (steps 6b
  and 6c), tested on the same two cuts only: every hard check passes. The review page `viz/review/sections-step2/step3.html`. The code's
  reading of the table is in `sections.md`, "How step 3 reads the table". To judge there: a piece narrower than its section's frame
  gets paved roadway on both sides (the lanes stay centred on the OSM line: West Broadway's 4-lane piece east of Granville, 1.6 m
  each side over 118 m; Hemlock Street north of West 7th); the strip between Fir Street's carriageways south of West 8th is one island
  now (the taper wedge split it before, and the lower piece was paved roadway). Not detected yet: the island and guardrail class; the
  kerb evidence narrowing a frame. The `real` class and its kerb taper have no case in the cuts (untested).
- The `before` build of a cut must see `corrections/`: `corrections.py` reads it beside the source tree (`src/../corrections`), so link
  `corrections/` next to the scratch copy of `src`, or the before build has no corrected lane counts (Fir Street 4 instead of 5).
- The Vancouver unit is rebuilt with steps 2 and 3 (2026-10-16, evening) and Kaveh checked it spot by spot on his dashboard. Each
  spot got one rule, listed in `sections.md`, "The rules from the Vancouver spots": the merge or fork keeps the far kerb (the bump at
  West 8th, the one lane move, `subsection.left_extra`), an island begins where the strip is 2 m wide (the spike at West 4th × West
  6th), a paved strip inside an intersection is junction area, the meters' parking only where the meters stand, an island's tip across
  spaces (Fir × Broadway). Kaveh accepted all of them on the dashboard. The unit's final check: every rule check passes but I3 (the old
  container step) and one BR12 (an object inside a bridge lane at the on-ramp foot, -123.135954 49.266514), not looked at.
- Lesson of the evening: a spot Kaveh reports gets changed on his dashboard before any plan, cut or other area; a hard reload shows
  it. The rebuild chain (`build --from division`, the page with the keys, the server on 8784, the checks) is `scratch/chain.sh`; it must
  stop the server and any running check first, both hold the database.
- Step 4 next: Monaco rebuilt (`build --from division`), the checks before and after, its page on 8785; then the J4 table of the unit.

## Open items, in the order I would take them

1. **Monaco, what is left.** A1 5: four carriageways where a neighbour's lanes or its cycle lane lie in our lane's space and our lane
   is cut at its edge, so its middle moves by half the overlap (Boulevard du Larvotto at the tunnel pair, 7.419119 43.735712, twice;
   Avenue Princesse Grace 7.432746 43.746376 and 7.437639 43.749326). A conflict to decide, not a silent cut: split the overlap at
   the midline and let A1 expect half of it (as it does for `left_extra`), or keep the lanes centred and narrow them. Kaveh has not
   decided. One more on a closed one-way loop, Avenue des Ligures 7.418656 43.725372, whose near lane is half width for 20 m: cause
   not established. A3 1: Avenue Marquet 7.413697 43.727264, the lane 1.65 m off its line, not looked at. The bridges: BR3 4 on
   Avenue de France (deck edges with no parapet among its 27 connectors), BR5 2 + 3 on Avenue de la Costa and Boulevard du Ténao
   (the model fills the free deck beside a 3 m lane with a path, and slivers under 0.5 m stay): bridge model rules, one part at a
   time with Kaveh, as on Granville.
2. **Lane width against a measured footway.** West of Fir Street's three southbound lanes the lanes (3 x 3.25 m, moved 1.62 m) reach
   the footway-set block edge by 0.3 m, so no sidewalk strip is left. Decide: a narrower chosen lane width, or lanes that give way
   to a measured footway. Kaveh has not decided.
3. **The part type `carriageway`.** It means "paved roadway with no lane" and uses the same word as the lanes' band. Rename it to
   `paved` in network.py, dashboard.py (PART_COLORS), checks.py, ground.py and the glossary, in one commit.
4. **The bridge landing's axis.** The bridge model straightens its axis by its own rule; the ground's drawn line differs by about
   0.7 m at the Granville ramp. The lanes are blended onto the ground over 30 m already. If a step still shows, give the landing
   the ground subsection's drawn line.
5. **Driveways.** The ground step does not cut driveways out of the sidewalk yet.
6. **Kaveh's unexplained items.** "Remove s0-w473723210/2 and i0-11251856779": that is the northbound Fir Street lane north of
   Broadway and the Broadway junction. Ask what he sees before touching them.

## How to run

```bash
P=/home/kaveh/projects/duckOSM/.venv/bin/python
# the servers: Monaco on 8784 (Street View's key allows that port only), Vancouver on 8785. A server reads its db into memory at start
# and holds no lock on the file (serve.py, 2026-10-16), so a build runs behind a live page; a rebuild ends with `scratch/serve.sh <area>`,
# a 2 s restart. Kaveh asked for http://localhost:8785/* on the key's referrers, to get Street View on both.
scratch/serve.sh monaco        # kills the server on 8784 by PID and starts it again from data/monaco.duckdb and viz/monaco.html
scratch/serve.sh vancouver     # the same on 8785 from data/units/broadway-granville.space.duckdb
# an OSM fault (lanes, oneway, layer): into ../duckOSM/osm_overrides/osm_overrides.yaml + known_osm_issues.md, then (12 s)
(cd ../duckOSM && .venv/bin/duckosm build --config config/sample_monaco.yaml)     # writes ../duckOSM/monaco.duckdb (a copy .2026-10-04 is kept)
# then Monaco in full (about 1 h: the lanes, the profiles, the build, the checks, the page, the server)
../duckOSM/.venv/bin/duckosm gmns ../duckOSM/monaco.duckdb --out data/monaco_gmns.duckdb -m driving
PYTHONPATH=src $P -m urbanstyle bridge ../duckOSM/monaco.duckdb data/monaco_gmns.duckdb data/bridges-monaco
PYTHONPATH=src $P -m urbanstyle build ../duckOSM/monaco.duckdb data/monaco.duckdb --bridge data/bridges-monaco/*.bridge.json
PYTHONPATH=src $P -m urbanstyle check data/monaco.duckdb --bridge data/bridges-monaco/*.bridge.json
export CARTO_API_KEY="$(grep -o 'CARTO_API_KEY="[^"]*"' ~/.bashrc | cut -d'"' -f2)"; source ~/miniconda3/envs/roadstyle/etc/conda/activate.d/google_maps_key.sh
PYTHONPATH=src:../roadstyle/src python3 -m urbanstyle dashboard data/monaco.duckdb viz/monaco.html --bridge data/bridges-monaco/*.bridge.json
scratch/serve.sh monaco
# a fix in network.py or ground.py: `build ... --from division` (Monaco 36 min), or a 250 m cut in 1-2 min:
$P scratch/cut-monaco.py NAME LON LAT TAG src [RADIUS]      # data/cuts/NAME.space.duckdb, the checks printed
$P scratch/plot-place.py DB LON LAT RADIUS viz/review/NAME.png "title"     # a picture of one place, http://localhost:8784/review/NAME.png
# Vancouver, from the division step (about 1 min), then the checks and the page
PYTHONPATH=src $P -m urbanstyle build data/units/broadway-granville.osm.duckdb data/units/broadway-granville.space.duckdb --from division --bridge data/bridges-measured/granville-bridge.bridge.json
PYTHONPATH=src $P -m urbanstyle check data/units/broadway-granville.space.duckdb --bridge data/bridges-measured/granville-bridge.bridge.json
PYTHONPATH=src:../roadstyle/src python3 -m urbanstyle dashboard data/units/broadway-granville.space.duckdb viz/broadway-granville.html --bridge data/bridges-measured/granville-bridge.bridge.json
scratch/serve.sh vancouver
# the docs site: the duckOSM env has mkdocs-material; the system mkdocs has not
$P -m mkdocs build --strict
```

Rebuild the page after every data rebuild: the page embeds the data. A stale page shows old faults. Long chains run under `setsid nohup`
with their logs in scratch/; a chain never kills a server during a build (the server holds the last complete data in memory).

## Things that cost hours this session

- A `pkill -f` or `pgrep -f` pattern that is also in your own command line kills your own shell (exit 144; three times on
  2026-10-16, a bracket in the pattern does not help when the plain name is in your command too). Kill by PID from `ps -eo pid,args`,
  excluding `$$` and `$PPID`.
- Long chains (build, check, page, server) must run under `setsid nohup`, else a later command kills them.
- A Python patch that asserts and fails prints nothing when its output is in a background task. Check the "PATCHED OK" line before
  building on it. Commit 41c9237 claimed a fix that was not in the file.
- `shapely.offset_curve` with a negative distance returns a reversed or empty line. Move a line by its own normals (`shift_line`).
- Two areas' pages in one `viz/` folder shared `bridge3d.json`; now each page has `<page>.bridge3d.json`.
- The Monaco division ran for hours twice: 120 m cut lines crossing each other inside the blocks (now clipped to the realm first),
  and the whole area's block edge buffered for every pedestrian piece (now indexed once). Profile with
  `faulthandler.dump_traceback_later` when a step is silent for more than its usual time.

## Review pictures

`viz/review/` (git-ignored, served at `/review/`): `vancouver-review-2026-10-15.html` (the morning review),
`vancouver-fixes-2026-10-15.html` (the first fixes, before and after), `r1015*/` (parts over the city's 2018 aerial photo, drawn by
a scratch script that reads `space.part`, `space.mark`, `space.block` and `space.unit`).
