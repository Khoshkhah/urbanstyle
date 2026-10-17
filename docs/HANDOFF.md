# Handoff: the street at level 0, 2026-10-16

Status: written at the end of the 2026-10-15/16 session, updated in the night of 2026-10-16 after the Monaco fails and after the
data-structure design. Read `AGENTS.md`
first, then this note, then `docs/notes/street-rules.md` and `docs/notes/sections.md`.

## Where the work stands

- **The data structure as design (2026-10-16 night, commit c04d878, main = network-first):** `docs/design/tables.md` gives the full
  structure: the same columns in the same order in every rank table (`<thing>_id`, `kind`, `rank`, `parent_id`, `level`, `name`, the
  thing's values, `source`, `method`, `ref`, `geometry`; `kind` everywhere, no `type`), the area with the id `a<level>`, the view
  `urban.item` over every rank (`id`, `rank`, `kind`, `parent_id`, `level`, `geometry`), the manifest `urban.meta` (`key`, `kind`:
  build / input / chosen, `value`, `note`), the check rows `urban.check` (`check_id`, `kind`, `status`, `count`, `what`, `items`,
  `checked`), the registry `urban.registry` of R6 (`profile`, `uid`, `kind`, `first_seen`, `last_seen`; `uid` on each thing with a
  profile), `predecessors` and `successors` on spaces and lanes, an `axis` with `s_from`, `s_to`, `t_from`, `t_to` on every linear
  thing, and the table `urban.code` (our kinds in CityGML 3.0, OpenDRIVE, OpenSidewalks, IFC 4.3). The glossary and the model's id
  table follow. The site builds with `mkdocs build --strict`. Kaveh stopped the session there: documentation only, no code.
  **Nothing of it is in the code yet.** None of `urban.item`, `urban.meta`, `urban.check`, `urban.registry`, `urban.code`, `uid`,
  the axes or the links exists in a build. The next steps, in order, each tested on Vancouver only: (1) `urban.meta`, `urban.check`
  and the view `urban.item` on today's tables, with tests; `urbanstyle check` computes read-only, then opens the file for a moment
  to write `urban.check` (the server holds no lock; a build does). The view on today's tables: rank 1 = `urban.ground` street and
  path rows plus `urban.block` as the plots; rank 2 = the other `urban.ground` rows as plot pieces (parent: the block that contains
  them), the sections as the union of their subsections' spaces (`urban.subsection.section_id`; today's `urban.container` sections
  have other ids and are the old step), the intersections; rank 3 = `urban.unit` (parent: `section_id`, or itself for an
  intersection); rank 4 does not exist in the data, so the parts hang on their space; rank 6 = `urban.mark` with no id of its own
  (make `<space>:<kind>:<n>` in the view) and no part link. The chosen values: every module-level number constant of the build modules
  with the comment on its line. (2) The registry: a build reads `urban.registry` from the file it replaces, keeps every known profile's
  `uid` and gives a new profile a `uuid4`; street objects first (profile `osm:n<node>`), then buildings (`osm:w<way>`,
  `vancouver:vb<id>`). (3) The check faults on the panel: `/api/meta` gives the rows of `urban.check` that are not `pass`, the panel
  lists them with their places as links that fly the map there.
- **A trap for the next build (found 2026-10-16 night, not fixed):** the code finds a pilot's city files by the output's name ending
  `.urban.duckdb` (`buildings.py`, `ground.py`, `blocks.py`, `parts.py`, `dashboard.py`, since commit c024a08), but the Vancouver
  file is `data/units/broadway-granville.space.duckdb`. A rebuild to that name gets no parcels, no kerb evidence, no bikeways and no
  storefronts, and nothing fails. Before the next Vancouver build: rename the file and its sidecars (`.space.duckdb.mapillary.json`,
  `.before-division`, `.before-ground`) to `.urban.duckdb`, or build to `broadway-granville.urban.duckdb`, and point
  `scratch/serve.sh` there.

- **Committed and pushed 9d225d3 (2026-10-16 evening), main = network-first:** the design as chapters by rank in `docs/design/`
  (the public site holds only the design as it is: no history, no names, no dates; the 31 old notes are in `docs/notes/`, off the
  site), and every rule of the day (paths at rank 1, no parcels, the room rule, the sidewalk strips, one partition, divided roads,
  `paved`, the rank 1 and rank 3 layers of the top-down division on the Vancouver page). Monaco's final build with every rule
  failed on 2026-10-16 19:42 on one junction whose roadway the strip cut emptied (guarded), then twice on the database's lock while
  its server was loading. Monaco's database is in a half state (old schema `space`, no level-0 division): run `monaco-final.sh` (the
  scratchpad) or a full build when no server is loading it; the first command on it renames the schema to `urban` (commit c024a08).

- `main` and `network-first` are one (2026-10-16): steps 2 and 3 of `sections.md`, the rules from the Vancouver spots, the dashboard's
  first-3D-draw fix, the rules from the Monaco fails (`sections.md`), the service-road rule, the servers that hold no lock, and the
  document of the model: `docs/notes/steps.md` (the hierarchy by rank, the steps, the dependencies, the levels, the words).
- Vancouver (`data/units/broadway-granville.space.duckdb`) is rebuilt with the final code: no count changed. Its fails: I3 1 (the
  old container step) and one BR12 (an object inside a bridge lane at the on-ramp foot, -123.135954 49.266514), as before.
- Monaco (`data/monaco.duckdb`) is rebuilt in full on 2026-10-16 afternoon from duckOSM's rebuilt database (its 57 overrides applied,
  issue 10: 1 lane on the Larvotto and Princesse Grace one-way ways) with the service-road rule (street-rules 16). From the start of
  the night to its end: U1 3, U4 3, U5 3, U6 2, U8 1, R1 4, J1 3, J2 1 all to 0; A3 12 to 1 (Avenue Marquet, 7.413697 43.727264);
  A1 8 to 1 (Avenue Princesse Grace near Boulevard d'Italie, 7.437639 43.749326); X1 0. The bridge model's own checks on the 14
  regenerated profiles: BR5 2 + 3 (Avenue de la Costa, bridge w1388235621), BR7 1 + 1 and BR11 1 (Avenue de France, bridge
  w572934026): bridge model work, one part at a time with Kaveh. Its page is `viz/monaco.html`, served on port 8784.
- Agreed on 2026-10-16 afternoon, not built yet, in this order: (1) rule 3 of `sections.md` tightened: a connector joins two
  junctions only where their cores overlap, or it is a `_link`, or both nodes lie on one closed loop of one-way pieces (a
  roundabout, a kind of its own); the Sainte-Dévote cluster i0-25197679 (10 nodes, 3,200 m²) is the test, with West 8th and the
  Granville ramp foot as the places that must stay one intersection each. (2) The side as rank 4 of the hierarchy: `space.side`
  (driving, walking) and `side_id` on `space.part` (`steps.md` section 1). (3) The network rules for every level, then the tunnels
  in 3D (`tunnels-3d.md`). (4) The part type `carriageway` renamed `paved`: done 2026-10-16 evening.
- Two servers run on this machine: Monaco on port 8784, Vancouver on port 8785 (`scratch/serve.sh monaco|vancouver`). One server
  serves one area: its `/api/` answers for one database (levels, tree, search). Street View works on 8784 only, because of the
  key's restriction (Kaveh adds `http://localhost:8785/*` to the key's referrers himself).
- **Paths, rank 1 (2026-10-16 evening, `paths.md` rules 1-2, 5 at rank 1):** Kaveh: "if you are adding path in rank 1, the area must
  partition by paths, blocks and streets". Built: `blocks.py` cuts the blocks by the pedestrian ways too (`path_sql`: a
  pedestrian street, a footway, steps or a path, named or not, Kaveh's word of 16:40; `PATH_W` 4 / 3 m where OSM gives no width; not
  a crossing, a sidewalk, one that runs along a road inside its sidewalk zone, or a pedestrian area, which is a square), one strip per path chain (`pstrip`), the same strip up to the roads' carriageways is `space.corridor`;
  `network.py` keeps the corridor out of the street, less the sidewalk's width at the roadway (the mouth, rule 5); `ground.py` gives
  the corridors the kind `path`. The faults met on the Rue Princesse Caroline cut and their rules: a path's edge run on 50 m past a
  T of paths (`ext_at`: to the widest path's far edge), a corridor from the raw line against a block from the chain (one strip for
  both), one corridor per way (several element rows per way gave duplicate ids, L1). The cut: U2 0, G1-G3 0, L1 0 (A3 1 as before).
  `build --from blocks` reruns the blocks and the steps after them from OUT.before-division. Ranks 2-3 of `paths.md` (path sections,
  path intersections, a square as a path intersection) are not built. Vancouver has no pedestrian way: nothing changes there.
- **Every footway a path, no parcels (2026-10-16, 16:40-17:00):** Kaveh: "footway is part of paths in rank 1" and "I prefer not to
  use the parcels at all": `blocks.path_sql` takes every footway, steps and path that is not a crossing, a sidewalk (tagged, or along a
  road inside its sidewalk zone) or a pedestrian area; the parcels set no edge, pull nothing in and make no block (rule 8 of blocks.md
  is history). `steps.md`, "The walking ways in the hierarchy", holds the rules in his words' order: which walkway is which, the
  sidewalk line as a measurement of the block edge, the paths and the blocks, what is not built. Open, proposed to him: the block edge
  as the far side of the sidewalk strip everywhere the line runs (no 10 m corner rule, no 0.5 m simplification, no building pull-in,
  a check instead) and the sidewalk part placed by the line.
- **The room rule and `paved` (2026-10-16, 17:00-17:30):** Kaveh found s0-w473754701.2/2 reaching 84 m² into b0-w23189661l.4 (West
  Broadway's 6-lane frame at its 4-lane piece) and ruled: a partition has no overlap. Built (`sections.md`, "The room rule", rule 17):
  the street's edge of rank 1 caps every kerb, chosen lane widths narrow to fit (2.75 m least, `narrowed`), the change class `room`,
  every unit, part and mark cut from the street; checks B7 and B8. The part type `carriageway` is `paved` everywhere (data, checks,
  page, docs). Both pilots rebuilt after it (Monaco `--from division`, 36 min).
- **The sidewalk strip and the corners (2026-10-16, 17:20-17:40; Kaveh on i0-11251856779 "why did it not use the footways", and "do
  it, also fix all overlapping in the same rank"):** `sections.md` room rule 5: the sidewalk lines' strips are part of the street's
  edge (the kerb and the junction's roadway end at the strip's near side, the block's edge is its far side); the block edge follows
  the line with no simplification and round the corner (`blocks.CORNER_M` 0, `EDGE_SIMPLIFY_M` 0); the strip is the sidewalk part,
  the band to the kerb the furnishing zone; a corridor ends at the street's edge (no mouth of street in a garden path's slot,
  s0-w627712113/1); the roads' blocks are filtered before the paths cut them (West 8th, s0-w1318007190.2/1). U1 and U9 at 0.05 m².
  Then (17:40) the one partition of the walking side (`sections.md` room rule 6): the street cut only by the stop lines and the joints,
  each face to the roadway with the most area in it, corners to the intersection (Kaveh on Fir Street at West 8th: "why do the sections
  and intersections not have a clean shape?"; i0-250765180). Then (18:15) a divided road is one section (`dual-carriageways.md`:
  Fir Street's two one-way carriageways north of Broadway, the zig-zag through the median), a path-cut sliver joins its corridor
  (b0-w336755750l.9), a walking-side piece goes to the roadway of its own face that it touches most (Pine Street s0-w1419312038/1
  had its lanes alone). Still open: rule 3 tightened (i0-245673105, four nodes chained by 35 and
  37 m pieces, and Sainte-Dévote); the `paved` part.
- **Vancouver, final build of 2026-10-16 (18:36, served on 8785):** every rule of the day; 5 divided roads paired (Fir Street north
  of Broadway among them, one section s0-w473723210/2 of 18.5 m with its median an island); rank 3 adds up to rank 1's street to 1 m²;
  B7 0, U1 0, U9 0, G1-G3 0. Fails: I3 1 and BR12 1 (as before), A1 2 (West 6th s0-w1202371350/1 and Fir south-bound w299511148, corrected
  to 3 lanes: lanes cut by the room on one side, see 0a). INFO: B8 61 spaces with narrowed lanes, K1 29 (the kerbs now follow the
  sidewalk strips, the basins no longer mark them), R4 45. Counts against the afternoon: B1 20 → 29, B6 47 → 44, R4 61 → 45.
  The corners at Broadway × Fir: the sidewalk beyond each arm's stop line (the crosswalk's far edge) is the section's, and only the
  kerb return between the two stop lines is the intersection's; that is the one-partition rule as written, verified with the
  division's prints on a scratch build (a build without the city's data, under another name, gives different stop lines and different
  corners: build under the unit's name).
- **The division top down, rank by rank (2026-10-16, 19:00-19:30):** Kaveh: the hierarchy is the specification, the code must be built
  in its order, no excuse; "I want to test each rank one by one in Vancouver first; when the result of each rank is ready I want to
  see it on the dashboard"; "not Monaco yet". Notes: `docs/notes/division-top-down.md` (the construction and the order of work),
  `docs/notes/ranks-algorithm.md` (one chapter per step from each rank to the next, what is built that way today and what not).
  Built: rank 1 as the page layer "Street (rank 1)" (page.py: the area less the blocks and the corridors, whole); rank 3 as
  `division.py` (new module: the street cut by the stop lines and the joints, each face to the roadway with the most area in it) and
  the layer "Spaces (rank 3, top down)" from `space.space3` on the Vancouver page, with three findings in the note (the 1 cm noding,
  sections through a T junction, 886 m² of street with no roadway). Next: Kaveh judges rank 1 and rank 3 on 8785; then rank 4 (the
  kerb, `space.side`), 5, 6; then `network.py` goes.
- **The panel by rank (2026-10-16 evening):** the layer list is the hierarchy of `steps.md` by rank (`panel.js` LYTREE, KINDS; the
  Area overlay in `page.py`); a kind the area has none of is greyed "none here"; a rank's click: all off when any is on, else all on.
- Monaco cuts: `scratch/cut-monaco.py NAME LON LAT TAG SRC [RADIUS]` (a 250 m cut of `../duckOSM/monaco.duckdb`, a full build in 1-2
  min, the checks; the bridge profiles whose axes reach the cut go with it). `scratch/plot-place.py DB LON LAT RADIUS OUT.png` draws
  one place (parts, lines, units, junction nodes) into `viz/review/`. The Monaco duckOSM database is from an older duckOSM (no turn
  tables): the clip warns and goes on.
- Pictures of the night: `viz/review/monaco-*.png` (http://localhost:8785/review/monaco-spelugues.png and the others: before, and
  `-cut` after).

## The rules added this session

All in `docs/notes/street-rules.md` (rules 7 to 13) and `docs/notes/pipeline.md`. In short:

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

`docs/notes/sections.md`: one frame per section, merges and forks are junctions, a connector under 40 m belongs to the
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

0a. **A1 at West 6th's three-lane piece (s0-w1202371350/1, -123.133965 49.266206, Vancouver, since the strip rule):** OSM draws the
   line along the north kerb; three lanes centred on it, narrowed to 2.75 m, still pass the sidewalk line there and are cut, so their
   middle is off the line. Proposed, not built: where one side's room is less than the lanes' half width, the lanes shift away from
   that edge as far as the other side's room allows, the shift recorded like a merge shift (`mshift`), A1 expecting it.

0. **The `paved` part is not agreed.** Kaveh, 2026-10-16 17:15, on s0-w473754701.2/2#10: "I am not convinced about that paved part; we
   will come back to it later." Today it is the frame's rest beyond the lanes and the strips (the one-frame-per-section rule); after
   the room rule, look at what is left of it on both pilots and decide with him whether the part exists at all.

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
# a fix in network.py: `build ... --from division` (Monaco 36 min); in ground.py: `--from ground` (7 min); or a 250 m cut in 1-2 min:
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
