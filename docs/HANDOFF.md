# Handoff: the street at level 0, 2026-10-23

Status: written at the end of the 2026-10-15/16 session, updated in the night of 2026-10-16 after the Monaco fails and after the
data-structure design. Read `AGENTS.md`
first, then this note, then `docs/notes/street-rules.md` and `docs/notes/sections.md`.

## The state on 2026-10-23 (read this first)

Branch network-first, pushed. The dashboard on port 8785 serves `data/monaco.duckdb` and `viz/monaco.html`: the Monaco build with
all the rules below (its bridges from `structure --above-ground`; the page's own `bridge3d.json` from `dashboard` is the old deck3d
model and is replaced by the flat solve after each page build: see step 7 below). Older builds are kept as `data/monaco-1022a`,
`-1022b`, `-1023a`, `-1023b`, `-1023c`, `-1023d` (`.duckdb`) and `viz/monaco-<same>.html`. The work tools of the last session are in `data/bg/`
(not in git): `rebuild.sh` (Monaco from the division into `data/monaco-r.*`, its checks, the flat bridges and the page),
`wcheck.py` / `wdiff.py` (W1, W2 by cause, and the places gone and new between two builds), `onejoint.py` (one place drawn),
`hcompare.py` (a bridge model's heights against IGN's points), `rebuild2.sh` (the same into `data/monaco-r2.*`), `mouthsort.py`
(W2's junction-mouth places by cause), `w2where.py` (where along a joint the two sides differ).

Done on 2026-10-22/23 (the design is in `docs/design/levels.md`, `stretches.md`, `dashboard.md`; the history in
`docs/notes/sections.md`, "The roadway meets", and `docs/notes/bridge-heights.md`):

- Bridges: heights from a few measured points (IGN), z = sea level; no ground grid. The dashboard's flat map has its own solve
  (`structure --above-ground`). At a crossing of two measured decks the measured separation is the gap (Avenue de France on IGN).
- Dashboard: G, the last button of the level row, fades or hides everything but the carriageway.
- Levels: a building passage is at the lowest level above every way under it (Avenue Pasteur).
- Division: a walking way sets a road's room only beside the road (A3 124 -> 0); a road end's heading over 3 m or the whole short
  piece (T junctions at short pieces); two sections that end at one node with no junction are cut on the bisector (bends).
- Checks W1 (a gap in the roadway along a street) and W2 (a step or shift at a joint across a street); `work.dropped` (roads that
  lose all their roadway, and why).
- Division: a slit (a piece of a space no part covers, roadway round it) is roadway (W2 48 -> 35, 13 places gone and none new;
  W1 1 -> 0). W2 marks the step itself, not the middle of the joint.
- Reverted: no fillet at an arm's mouth (Monaco: 24 shifts gone, 27 new; sharp corners in compact junctions). Not kept: W2 with
  islands counted as carriageway (W2 48 -> 119).

Monaco now: fails A1 35, J1 1, M1 4, U4 1, U5 1, U8 1, U9 1, W2 35, and the old deck3d model's bridge checks (BR2 4, BR5 1, BR7 2 + 1,
BR9 2, BR11 40 + 1, the same as before; the step models: all D checks pass but Larvotto's D8, closed). (J1, U4, U5: one place, n25194212, the T of Rue de
Millo's 2.6 m piece, Rue Saige and a parking entrance; the node lies 1 m outside its junction, where the street's edge cut it).

Open, in order:
1. W2 at junction mouths (27 of W2's 35): about 17 where the mouth is wider or narrower than its arm with walking side there (7 of
   them at a block's corner near the mouth), 6 slits inside a space that touch walking side or an island (the slit rule rightly
   leaves them), 4 median noses at a joint (probably correct). Four changes on the fillets did not help (the fillet rule, the crumb
   rule, no fillet beside a lone arm, a fillet narrowing to 0 at the stop line); the next one needs Kaveh.
2. W2: a 6.3 m piece between a bend and a junction is cut on a slant at the junction (n25193892); islands that do not line up at a cut.
3. Bridges: Avenue de France's a1 middle 2.4 m under its IGN point (that point has no deck return: it may be the ground); Larvotto's
   D8 jogs are closed (Kaveh, 2026-10-23): notches of a few centimetres at the two ends of the slit between the two decks, not seen on
   the dashboard; they stay as they are.
4. Step 7 (the dashboard of the area with the step models): `dashboard`/`page.py` still take their bridges from deck3d, because its
   2D bridge layer reads deck3d's flat parts; the step models have none. Kept as it is for now (Kaveh, 2026-10-23): at
   Larvotto the 2D outline of the old model and the 3D outline of the new one are almost the same.
5. Tunnel entrances (2026-10-23 evening): a sweep of the whole roadway (G hidden) found a gap at 107 of 119 nodes where a road changes
   level below the ground. Two ways failed and are kept as patches in the session's scratch: (1) building the tunnel levels with
   network.py (as the decks) closes the gaps but drops short tunnel ways (sliver and junction rules made for the ground); (2) running
   the older builder's tunnel roadway on to the node fills some gaps with odd shapes and splits spaces (U2). The gaps have three
   causes: the older builder's tunnel spaces stop 1-3 m short; a short level-0 piece from a portal node to the ground road has no
   roadway (dropped as a sliver); and nodes where three levels meet. Needs Kaveh's choice of approach.
6. Narrow roads: 33 stretches inside the area whose roadway is under 2 m wide on average (probably lanes squeezed by the room rule).

## Bridges: the words and the order of the steps (2026-10-19, read this first)

**2026-10-22, night.** Accepted and frozen: the cover rules 1 to 3 (the pedestrian realm, a straight-on connector is a lane, path
links), the width rule (a path counts only where its branch's lanes are the nearest) and duckOSM's lane taper at a plain joint of a
two-way road (duckOSM 5d227bb). The bridge's GMNS is built again so: `duckosm build --pbf ../duckOSM/data/maps/metro_vancouver.osm.pbf
-b data/granville-bridge.boundary.geojson -o data/granville-bridge.osm.duckdb -m driving --fixes ../duckOSM/osm_overrides/osm_overrides.yaml`,
then `duckosm gmns data/granville-bridge.osm.duckdb --out data/granville-bridge.gmns.duckdb -m driving` (the boundary is a 2 m buffer
round the old GMNS links; with the taper off it gives the same bridge lanes within 0.18 m). Also installed: a carriageway goes straight
on from its two-way road through OSM's V (duckOSM 220c7fb; Hemlock, a10 into a11 and a12; the aerial photo shows one deck with a median
barrier). The 1 m S-wiggle at Hemlock is gone (duckOSM 2044c4f: through OSM's V a carriageway lane is one smooth curve). At the a4 fork the
lanes go where Kaveh gave them (duckOSM f8d1cc0: arrows #24, the lane-split rule), and step 4 draws a move that goes straight on but
sideways as one smooth curve (`bridge_forks._smooth_moves`; step 3 measures the widths from SUMO's moves as given, `bands()`). The two `merge_to_left` lanes that do not end (w256879265,
w1419040131) are overrides in duckOSM (known issue #23, 2c9da68): Kaveh chose B1 from the aerial photo.

**2026-10-22, evening.** Each branch is on its smooth centre line with one width and one constant offset (c1ef74c), and step 3b rounds
each corner where a fork's side meets a branch's edge with a short fillet (`bridge_forks._fillet_corners`, `bridge-steps.md`, "Step 3b:
the corners at a fork"); the bridge ends and the gore tips stay square. References saved again. Not accepted by Kaveh yet.

**2026-10-22, later.** The fork is one straight-sided piece from the trunk's end to each arm's cross-section at its branch point
(`bridge-steps.md`, "Step 2: the shape of a fork"): the bump at the south fork is gone. Open, listed with their causes in the session of
2026-10-22: the cover does not fill the deck beside the paths (one width per branch; the street rule for the pedestrian realm is
proposed), SUMO's 47 m junction at the south fork drawn as connectors (a straight-on connector should be a lane), the eight sideways
path stubs (links, not bands), the lane kink at a lane gain (duckOSM).

**2026-10-22.** Steps 1 to 5 are frozen and accepted (references in `tests/reference/`, tests `test_bridge_steps.py` and
`test_bridge_step5.py`). Step 3 changed at Kaveh's word ("keep one width, from all the bands"): the width is the widest cross-section,
and the strip's middle follows the bands' middle (`bridge_forks._one_width`, `_strip_along`); the references were saved again. Step 6 (the
cover: `bridge_forks.cover_items`, `urbanstyle structure ... --gmns`) is built on rank 0 and matches the old model at every fork; not
accepted yet. The servers must be started again after a restart of the machine: `viz/` on 8784 (`python3 -m http.server`), the Granville
cut's `serve` on 8786, the old dashboard on 8788.

**2026-10-20, after the background session (30b4d6d).** Kaveh: "do the best for the project in general, not a special case". Step 3's
width is now exact (`_extent_exact`: every corner point of the branch's own bands, along the whole axis from the taper's end at a fork,
FORK_TAPER_M), not sampled every 2 m. The step 3b sliver rule (SLIVER_M) is removed: it was a workaround for the sampling and it made the
last jog. Granville: 0 jogs and 0 holes in the smooth outline; 9 m2 of two paths lie outside, both more than BESIDE_M (3 m) from the
lanes (a path that moves away from the road is not deck, by the agreed rule). Reference saved again with Kaveh's permission.
Steps 3b and 4 are not accepted yet.

**State at the end of 2026-10-19/20.** Steps 1 to 3 are made and shown in 2D; none is frozen yet (Kaveh has not accepted them).
- `src/urbanstyle/bridge_forks.py`: step 1 (`forks`: junction nodes, carriageway pairs, forks, branch points), steps 2 and 3
  (`partition`: branches and forks on OSM's own lines, `_osm_axis`), and the 2D dashboard (`dashboard`, `viz/bridge2d-granville.html`):
  a layer for each step, SUMO's lanes and connectors from GMNS, OSM's paths, and the old bridge3d model for comparison.
- The profile's axis lines are NOT OSM's lines (the LiDAR step added landings and moved them up to 0.6 m): read OSM's way lines.
- Step 4 (the bands) takes SUMO's lanes. SUMO's input was fixed in duckOSM (branch geoparquet-export, commits 29b2df4 and 8088deb): the
  lane counts as OSM overrides, the lane arrows at the north fork, no turn-back on a bridge, two-way roads centred on their line, and one
  lane placement for GMNS and SUMO. SUMO for a bridge: build its edges from the PBF (`duckosm build --pbf ... -b <bridge area>`, 7 s) and
  `duckosm gmns` on it (a few seconds), not the whole city. Granville's: `data/granville-bridge.gmns.duckdb` (not in git).
- The city databases (`data/vancouver_city.osm.duckdb`, `.gmns.duckdb`) have the lane overrides but not the new SUMO rules.
- 2026-10-20: Kaveh accepted steps 1 to 3; they are frozen (`tests/reference/granville-bridge-steps-1-3.json`,
  `tests/test_bridge_steps.py`). At Kaveh's request, step 3's widths come from each branch's own step-4 bands (a path counts within 3 m
  of the lanes or of a path that counts), and a fork starts at its trunk's full cross-section (the arms' own strips 20 m from the node).
- Step 4 (`bridge_forks.step4`) reads only SUMO's lanes and connectors (`data/granville-bridge.gmns.duckdb`) and OSM's paths.
  Not accepted yet.
- Step 3b (`bridge_forks.step3b`, not accepted yet): the union of the branches and forks, with the slivers of the step-4 bands within
  1.5 m (not past a bridge end), closed and opened by 3 m; each jog left becomes a straight taper (the hull of the outline 10 m on each
  side of the corner). Granville: jogs 2 -> 1, band pieces outside the outline 3 -> 0. The jog left is 9.8 m from a3's bridge end
  (the a3 sidewalk lies 1.1 m outside b3 there, inside the taper reach of the square end).
- Open: `bridge_cover.py` still makes its own lanes (step 4 must read SUMO's lanes and OSM's paths); smoothing (step 3b); a8's east
  sidewalk lies on its lanes (lane widths are SUMO's 3.25 m by class); `corrections/lanes.json` is now in duckOSM's overrides too.

`docs/notes/bridge-steps.md` is agreed with Kaveh: a bridge level is divided into branches and forks; junction nodes, carriageway
pairs and branch points are found by its rules (Granville: 10 branches, 4 forks); the work goes in seven steps (1 to 4 and a 2D
dashboard in 2D, then rank 0, the cover, the dashboard in 3D), and each step is frozen when Kaveh accepts it. Where the notes below
disagree with it, that note is right.

## Bridges: the state on 2026-10-17 (read this first)

**End of the session, 2026-10-18 (read this first).** Code at commit 077ec1f (network-first, not pushed). Kaveh ended the session
tired: the rank-0 outline still has kinks and bulges at the four forks (main span south, north split, Connector, Hemlock loop start),
and every per-place rule added in the last rounds made another place worse; the last uncommitted round (a fork rule) was reverted.
The cover from the profile (lanes, barriers, cycle lane) is worse than the old bridge3d model's at the junctions. Lane counts must be the
profile's with corrections/lanes.json (bridge3d.correct_sections), as the old model: done. Open proposal, not decided: keep the old
model's deck outline and lanes (bridge3d) and lift them onto the new height surface with its OSM ends, instead of building a new outline
from branch bands. Do not add more per-place rules to bridge_surface.py's outline; agree an approach with Kaveh first.

**Rank 0 without LiDAR (2026-10-18):** the same pipeline, and now the same plan: the outline comes from the network only (no wall inside a
level, every gap under 12 m is deck), and decks that are joined into one deck carry one surface: the solve couples the heights of two
axes of one level wherever the other band lies within this one's half width plus 12 m (`_couplings`, `W_COUPLE` 100), except within 10 m
of a ground node; a solve node every 10 m (`NODE_STEP_M`). Kaveh: "a branching point is where two bridge branches really separate, not
where the lane geometry branches". Both Granville models: D1-D8 all 0. Without LiDAR the crest is 27 m by the top rule, the Hemlock link 7-12 m
(LiDAR: 11-18 m).

**Granville rank 0 accepted by Kaveh (2026-10-18):** the LiDAR model as built by `urbanstyle structure ... --plan viz/plan-granville.html`.
Branches from the network; two one-way lines side by side from a shared node are one road over the stretch they run together
(`_merge_carriageways`, `PAIR_M` 14 m, at least `PAIR_MIN_M` 40 m), and a road that goes straight on with about the same width joins the
branch it continues; a carriageway split keeps the wider road's edges; heights one continuous blend. D1-D8 all 0. Known and left as
they are at his word: the 4th Ave / Fir ramps merged over their shared start (13.1 m), the leftover pieces' labels, one dashed transition
at the Connector junction. The 2D plan (`plan_html`) is the review tool: centre lines, one band per branch, transitions, the edge.

**Rank 0 from the network (Kaveh: "one line geometry and a width for each branch, not piece by piece"):** `_branches` chains the axes
at each node (the two ends that go straight on, |cos| over 0.7, with widths within 3 m or 25 %) into branches: Granville has 11 (the main
span a1+a8 738 m at 32.6 m, each ramp one line). Each branch = its line widened by its one width (`_strip`, square ends); `_transitions`
blends a narrower branch from the wider branch's edge line onto its own edge where it leaves the wider one's end (smoothstep over 30 m);
the union, gaps under 12 m closed where no steeper than 45 degrees, smoothing, walls, holes filled. Heights: one continuous blend over
the axes' bands (1 / (distance + 0.5 m)^2). LiDAR Granville: D1-D8 all 0. Viewer: `viz/rank0.html?v=25&m=cut-granville.bridge3d.json`.

**After that (Opus 5.5 session):** axes joined end to end with nothing else at the joint and going straight on are one road with one shared
width and offset (no step, shift or narrowing at such a joint); at a real branch the narrower axis starts at the wider deck's width and
eases to its own along a cosine S-curve over 30 m (`BRANCH_TAPER_M`). Gap closing and edge smoothing were missing from the file and are
back. LiDAR Granville: every check D1-D8 at 0, no notch, one slab. Rules-only: 84 steep faces at the a3/a9/a10 junction, 9 jogs.

**Final state, 2026-10-17 night.** The structure of each level = the union of its axis bands (one fixed width per axis, square ends; at a
node where a wider band ends, one straight-sided piece over 20 m to the narrower band); every gap under 12 m closed where the deck across it is
no steeper than 45 degrees; no notch or bump under 3 m; walls (slits) where two bands differ by more than 1 m; holes filled. LiDAR Granville:
D1, D3-D8 at 0, D2 2 (two 0.3 m slivers at a11). Rules-only Granville: 86 steep faces at the a3/a9/a10 junction (the rules give two decks
of one level 10 m apart in height there; LiDAR separates them) and 4 jogs. Pictures `viz/review/lidar-*.png`.

**Last, 2026-10-17 night: the single rule.** Kaveh: "every axis must have a fixed width, clean and smooth, without steps or breaks";
"the width of a bridge changes only at its branches"; "no bumps, no steps"; "no hole". `bridge_surface.py` now: each axis one band of one
width (`_axis_width`: the widest of its lanes plus 0.5 m and the paths beside it, a feature under 20 m not counted), square ends; the
structure is the union of the bands; a wall (slit) where two bands of different heights touch; every hole filled; nothing else (the outline
widening, the gore fill, the edge smoothing and the branch taper were written and removed again at his word). Checks D1-D8 (D8: edge
jogs, a branch zone of 10 m round a node excepted). LiDAR Granville: D1-D7 at 0, D8 12 (the width steps at two junctions). Rules-only
Granville: D2 9 and D3 1 at the Seymour end, D8 12. Open with Kaveh: steps at branches as they are or tapered; the thin gap between
the Hemlock loop's two carriageways; Granville has no clearance input over the water (the 27 m top stands in for it). The viewer's
address needs a new `v=` after every change.

**Later, 2026-10-17 night: rank 0 after Kaveh's review of Granville.** His rules, now in `bridge_surface.py`: the start and end of a
bridge come from OSM (`_trim_to_osm`: the LiDAR landings in the profile give heights only, no length); no hole in a structure; no special
piece at the ends (one slab to the landing, bottom at max(h − 1.8, 0)); no step in the edge (`_axis_strip`: the width every 2 m from the
lanes and the paths beside them, tapered over 20 m, square caps to the last segment); a wye between two strips that meet is deck where their
heights agree and the gap is under 12 m (`GORE_M`), open where they differ; OSM's outline adds width only beside the strips; the parapet
runs to the landing (only the 0 m cap is open); piers only under 3 m or more; a plain drag in the viewer moves the map. `--no-lidar`
writes the rules-only model (`viz/cut-granville-nolidar.bridge3d.json`: within 0.3 m of the LiDAR one). Checks D1-D7 all 0 on Granville
(D7: parapet pieces under 3 m). Kaveh has not reviewed Monaco yet; the Monaco model is rebuilt with the same rules.

**Night, 2026-10-17: rank 0 of the bridge is built and under Kaveh's review.** The note `docs/notes/bridges-ranks.md` is agreed
(also on the site). The new module `src/urbanstyle/bridge_surface.py` makes the structure (rank 0): one height solve for all nodes of a
profile (`_solve`, SLSQP: 0 on the ground, at most 18 % along a road, 6 % where it can, the clearances as strong wishes, the clearance
between two decks that cross as a pair, LiDAR heights held), the structures per level with the ramp cut of rule 4 as a slit, the OSM
outline as the edge where OSM maps one, one height surface per structure (`_Surface`: the strip a point lies in, blended; all axes
outside every strip), the slab with its bottom at max(h − 1.8, 0) to the landing in ONE piece (a separate fill piece showed every
seam and was removed), the sides, the parapet along the edge except at landings and joints, the piers (3 m or higher) and the truss from
`bridge_structure`, and the checks D1, D2, D3, D4 (info), D6. `urbanstyle structure DB OUT.json --bridge P` writes it in the page's
model format (`--rank0`: the bare surface, not what Kaveh means by rank 0). `URBANSTYLE_BRIDGE3D=structure` makes `dashboard`/`serve`
use it. **The viewer** `viz/rank0.html?v=5&m=cut-granville.bridge3d.json[&b=NAME]` shows the model alone over a ground grid (plain
drag moves, right-drag turns): Kaveh reviews rank 0 there, not on the dashboard. State of the review: Granville clean at the fork, the
north junction, the main span and the ramp ends; Avenue de France has 19 unmet clearances (Saint-Roman, terrain). Rules added during
the review and their reasons are in the comments of `bridge_surface.py`. Next: Kaveh's remaining findings on rank 0, then the cover
(ranks 1 to 6) reading the surface.

**Evening, 2026-10-17: the direction changed.** Kaveh: the bridge must be built like the street, top down by rank. The note for
agreement is `docs/notes/bridges-ranks.md`: the deck is rank 1 of its level, one piece with one height surface; ranks 2 to 6 read
their heights from it and choose nothing. The three-step deck3d plan of this evening is withdrawn. Nothing of it is coded.

The work in progress is the bridges on two test cuts. The plan that Kaveh agreed is `docs/notes/bridges-street-model.md`: one
street model on every level. `network.py` runs once for each road level (the deck edge is the street edge). The new `deck3d.py`
lifts the parts and marks to the profile heights. The old `bridge3d.py` stays until both cuts pass. Nothing of this is committed
after 89042a0. The changed files are in `git status` (`bridge_structure.py` is new).

### The test loop (never a full build)

- `scripts/cut.sh AREA NAME LON LAT [RADIUS]` with `PORT=...`: a small square plus each near bridge deck buffered 60 m. Monaco's
  profiles come from `../duckOSM/data/monaco-wide/monaco-wide.duckdb`, so a bridge is whole even when it leaves the square.
- `data/cuts/redo.sh NAME PORT`: the division and the steps after it, the checks and the page (~2 min).
- `data/cuts/page.sh NAME` with `PORT=...`: the page only, and a restart of its server.
- A deck3d change on Granville only: `urbanstyle bridge3d data/cuts/granville.urban.duckdb viz/cut-granville.bridge3d.json --bridge
  data/bridges-measured/granville-bridge.bridge.json` (`data/cuts/NAME.bridges` lists the profiles of each cut), then reload the page (seconds, not minutes). Kaveh asked for this path for every
  Granville bridge fix.
- The cuts: Monaco Avenue de France `http://localhost:8784/cut-france.html`, Granville Bridge `http://localhost:8786/cut-granville.html`.
- Before you send a link, look at the page in the headless browser: `scripts/views.py URL TAG lon:lat:zoom:pitch:bearing ...` writes
  `viz/review/TAG-k.png`. Kaveh rejected links twice that showed faults at once.
- Google 3D: roadstyle v0.22.1 with `google_3d=True`. It needs `GOOGLE_MAPS_KEY` when the page is built. The key accepts ports
  8784 and 8786.

### State at the session's end (2026-10-17, evening)

- Granville: the cut build finished (34 min). `urban.check`: BR1 and BR4 to BR11 pass. BR2 fails with 2 holes in the deck at the
  north end (`-123.128561,49.275521` and `-123.128963,49.275421`: the Howe and Seymour forks). BR3 fails with one guard gap at
  `-123.138412,49.267759` (the Hemlock loop, a11 and a12). BR12 fails with one street object inside a lane at `-123.135954,49.266514`
  (the south start of a3, the Granville Connector). The junction `i1-2625030369` is gone. The 3D model has no steep face
  (`scripts/steep.py PAGE.bridge3d.json`: a face that is not a guard, over 1 m high and steeper than 45 degrees). Pictures:
  `viz/review/granville-0..6.png` (`scripts/views.py URL TAG lon:lat:zoom:pitch:bearing ...`).
- The server restart at the end of `scripts/cut.sh` did not survive the end of the session: the page was built, but port 8786 had no
  server and `granville.serve.log` was empty. A server started from a tool shell with `setsid nohup ... &` died too. `setsid -f`
  keeps it alive.
- Monaco, Avenue de France: the rule that put axis a2 on the ground in its middle is the ground set of `bridge_profile.py` (`ground`,
  before `_to_ground`): every node of a highway that is not a bridge counted, paths included. Two nodes grounded a2: the crossing
  w939530781 at 57.6 m (a footway with no `layer` tag, mapped across the deck) and the hairpin node n21929088 at 36.6 m, where the
  ground road Avenue de France w4246253 joins. Fixed: a path (`PATHS`) makes no ground node (one line in `bridge_profile.py`; the
  note `docs/notes/bridge-profile.md`). Steep faces on the France cut: 132 before, 61 after. The 13 Monaco profiles rebuilt from the
  wide db differ only in a2, a4 and a5 of avenue-de-france, and in the end of the 2 m steps bridge w785311713 (0 to 0.14 m: its end
  touches a footway only; a known limit). Only avenue-de-france's profile is installed in `data/bridges-monaco/`; the old 13 are in
  `data/cuts/bridges-monaco-2026-10-17-before-path-rule/`.
- The hairpin node is not a rule fault. It is the upper street of Saint-Roman. Beside the one-lane bridge way w4230082 (layer 2) OSM
  maps a bus platform 2.4 m away, two crossings, steps, the Chapelle Saint-Roman 6 m away and apartments 4 m away: there the layer-2
  deck is the ground of the upper town, and Avenue Princesse Grace (layer 1, a1) and the lower roads lie 5 to 10 m below it. The
  model has no terrain, so one flat 0 m cannot hold both. The 61 steep faces left are of two kinds: the step between two decks side by
  side with different heights (a2 climbing from the hairpin beside a4: 25 faces near `7.43841,43.75192`), and the short ramps between
  a deck and the ground (a7, a9: 14 m long, 2.5 m high, 18 %, walls to their neighbours a1 and a10). This needs Kaveh's decision
  (terrain: a ground height per node; or the hairpin deck kept in the air and the ground road w4246253 treated as a ramp).
- Tried and reverted: every loose end of the bridge network as a ground node (Kaveh's rule, every bridge end on the ground). It put
  the dead end of the emergency-access spur w156780352 on Pont Sainte-Dévote on the ground (2.4 m to 0 m). A loose end of a service
  spur on a deck is in the air, so the loose ends count only in a group with no ground node, as before.
- Monaco, also open and unchanged: the box with walls near the crosswalk (`viz/review/sweep-hairpin-0.png`, centre), the guard at the
  end of axis a8 (BR13).
- Pictures of the hairpin after the fix: `viz/review/sweep-hairpin-0..9.png` (8 bearings at zoom 18.8, two closer).

### Kaveh's rules for this work

- Answer every message at once. Run every build in the background.
- Every bridge end is open, and every end is at level 0 on the ground.
- Decks have the same style as the ground (paved and shoulder colours too).
- LiDAR only sets the parameters of the height rule. The profile is filled as if there were no LiDAR.
- An OSM fault goes to duckOSM's `osm_overrides.yaml` (building w138590891 is removed there, duckOSM commit 8fb38bb, not pushed).
- Code a new rule only after Kaveh agrees with it.

## Where the work stands

- **The data structure (2026-10-16 night).** Kaveh: the data structure is the product; the dashboard only shows it. Order he set:
  the document first, then the code to it, then one run.
  - The document: `docs/design/tables.md` gives every table of the model with one row per column, its type and its meaning, the
    rules of the axes, (s, t) and the links, and the working schema. `docs/design/drawing.md` (Kaveh's "level order for each table"
    is the draw order: the levels from the lowest up, then `draw_order` in `urban.style`). A helper made both easier to read
    (a reading guide, a diagram of the tables, one lane followed up the tree, SQL examples) with no column changed.
  - The code: the build's steps write the schema `work` (every `urban.` of the old steps renamed); the last step `product.py`
    writes `urban` exactly as the chapter, then `meta.py` the registry with `uid`, `urban.meta`, `urban.style`, `urban.code`;
    `urban.item` is a plain view over the eight rank tables; `urbanstyle check` tests `work` and writes `urban.check`.
    `schema.migrate` moves an older file's intermediate tables to `work` and keeps its registry. The object matching moved from
    `dashboard.py` to `objects.py` (the build runs without roadstyle). `tests/test_product.py` compares the chapter with a build,
    table by table, column by column, type by type: a change to one without the other fails.
  - What the data fills today, column by column: the lanes in an intersection carry no edge, so a lane's link through an
    intersection comes from the guide line's two ends; the links at an arm need the same road name on both lanes; `urban.street`
    and the sections' `street_id` come from the old step's arms (by the section's way, else by name); the part kind `carriageway`
    in old data has no style row. Not built: the path sections and path intersections (no rank 2-3 for paths yet), the uids of
    the other R6 kinds.
  - Second round (2026-10-16 late): every rank table has `uid` (the registry gives every kind a profile: `meta.profiles`, with #2,
    #3 for equal profiles in one build; a thing that is both a stretch and a space has one uid); the paths at ranks 2-5
    (`paths.py`: each path item cut at its path junction nodes, `work.path_space`; a path space has one walking side and one part,
    `path` or `steps`); the page's rank layers read `urban` (Ground = rank 1 + plot pieces, Sections and Intersections =
    `urban.stretch`, Spaces, Sides, Parts, Marks; colours from `urban.style`) and the server's layers are views over `urban` with
    the old id names beside the model's (`serve.LAYER_VIEWS`: the panel's buttons still read `unit_id`, `section_id`, `type`; the
    next step renames them in the panel and drops the aliases); (s, t) explained with a drawing in the chapter.
  - The paths (2026-10-16 night, Kaveh on g0-path-c0-w1018344891.2 and the block at Birch Street): the blocks' faces come from the roads
    only, so the 400 m2 / 8 m filter of the roads' blocks no longer drops a block between footways (8 new blocks in Vancouver, 76 to
    84; that path item 251 to 72 m2); the cutting strip is the corridor; leftover land is never given to a path; a path junction
    is a node inside a path item with 3+ path ends, cut across its own corridor only, pieces under 2 m2 join a neighbour (727 path
    spaces to 218). Open, reported, not changed: (1) the junction area in pieces: 41 of 44 intersections have 2+ junction-area
    parts (i0-432423756: 7, from 0.1 to 1,093 m2), the crosswalks and islands cut it; proposed: one junction area per intersection,
    and any part under 2 m2 joins its neighbour. (2) Pine Street s0-w1419312038/1: OSM maps 20 m of Pine Street as footway
    w961476753 where the greenway w336803184 crosses, so the road strips end in round caps that bulge the street's edge into the
    blocks; proposed: a road that goes on as a footway in its own line keeps its edges straight through. (3) An island spur from a
    3D picture of Kaveh's, place not found (candidates s0-w390721481/1#4, s0-w341691651/1#6, i0-430951364#5): ask for the part id.
  - Sub-intersections (2026-10-17, Kaveh: "if junctions partition intersection, we should consider them as sub intersection"): an
    intersection is rank 2 only; rank 3 cuts it into one sub-intersection per junction node (product.cut_intersection: the ground
    nearer to its node, a Voronoi cell clipped to the intersection), a roundabout (a ring of duckOSM junction=roundabout ways; every
    ring piece is a connector, network.py) into ring sectors and its centre (the islands inside the ring). The intersection's parts
    are cut along the same lines, one junction area per sub-intersection, a part under 2 m2 joins its neighbour. Tested on a 200 m
    Monaco cut at the Rond-Point du Portier (data/cuts/portier, picture viz/review/portier-roundabout.png): one roundabout, 8 ring
    sectors; its checks equal the same cut built with the code before the change (A3 21 in both). Rond-Point du Portier's south way
    w353889272 is not tagged roundabout in OSM: that piece is a section. The server's focus (3D) still finds spaces in work.unit, so a
    sub-intersection has a card but no focus.
  - The tighter connector rule (2026-10-17, agreed 2026-10-16): a short road between two junction nodes is a connector only where
    the two nodes' stop lines on it meet or cross (reach = core + JUNC_ARM_M at each end, network.reach_at); a `_link` and a
    roundabout ring stay connectors. Test place: Granville at West 6th (i0-432423756, five nodes chained by short pieces).
  - Islands at least 2 m wide (2026-10-17, Kaveh's 3D picture of a spur): a piece of a strip between roadways thinner than JGAP_M is
    paved whatever OSM maps on it, unless a barrier runs along it (network.on_barrier). The spurs were 1.1 m strips on Granville
    north of West 6th (s0-w341691651/1#6, #7, i0-432423756#12) kept as islands because a sidewalk line and kerb points lie on them.
  - A build `--from division` starts from OUT.before-division, which only a full build or (since 2026-10-17) `--from blocks` writes;
    Vancouver's copy was from 2026-10-15 and a `--from division` build lost the blocks and the paths: use `--from blocks`.
  - The stop line along a crosswalk (2026-10-17): where a crosswalk sets an arm's stop line, the line and the arm's roadway end run
    along the crosswalk, 1.5 m beyond its far edge, at its own angle (network.py, arm_cuts with a direction). Corners still reach the
    block edge; the footways set no edge of the intersection.
  - Kerbs (2026-10-17, s0-w74226330/1:kerb:1): a walking-side sliver under 2 m2 that touches no block is paved roadway
    (network.SLIVER_ROAD_M2), and no kerb runs along a cut between two spaces (crossing a cut it stays whole).
  - Open, asked and waiting for Kaveh: whether a `_link` (a ramp) stays a connector or is cut like every arm (Kaveh: "intersection
    building is in rank 2, there are no ramps there"; my change was undone, he had not decided); parking on w390721485 and w74226330
    (Street View shows cars parked; OSM has no parking tag: proposed an override in duckOSM); the paved part (still not agreed).
  - Night of 2026-10-17, background session (Kaveh away): Vancouver rebuilt from the blocks step with every rule of the night and
    checked on the data. Verified: the short kerb across the road at the Granville ramp foot and its two walking-side slivers are gone
    (viz/review/kerb-after.png; s0-w74226330/1:kerb:1 is now the 26.9 m kerb along the road); Fir Street at West Broadway ends along
    its north, south and west crosswalks, the east side is cut square to Fir's two one-way carriageways because that crosswalk lies
    inside their core (viz/review/fir-broadway-crosswalks.png). Found and fixed (a351104): the connector rule left a 4.2 m section
    between i0-877917634 and i0-877917571 whose small leftover joined a junction with its WHOLE frame, so the two intersections
    overlapped by 34.5 m2 (U1); now only the leftover roadway joins (stretches.md: a section under 20 m2 of roadway joins the
    intersection it touches). Check J3 followed the old 40 m rule (7 false faults): it now tests the agreed rule. Vancouver's checks
    now: I3 1, A1 4, BR12 1. A1's four places are the two known faults of item 0a (Fir southbound w299511148 and West 6th's
    three-lane piece), each counted in two sections since the connector rule split them (a ramp-foot cut with the connector rule off
    counts West 6th once); the proposal of 0a still waits for Kaveh.
  - Monaco, the same night: the full build with a351104 stopped after the blocks step (a junction with an empty shape had no centre
    to give its name). Fixed in bb7d9da: a junction with no shape is not made (its shape was empty before the cut at the street's
    edge, so no roadway is lost). Then `build --from division`, the checks and the page ran to the end; the page is on port 8784.
    The checks FAIL: A3 499 (1 in item 1 below), A1 27 (5), U4 1, U5 1, U6 1, J1 1, J3 1, M1 2, BR7 1 + 1, BR11 1, BR5 2 + 3 (the
    same as before); BR3 is gone. Cause of A3 (found on a 300 m cut at 7.4280 43.7390, `data/cuts/lost157`, A3 53 there): the room
    rule. The room of a run is the least distance from its whole line to the street's edge, and a footway that ends at the road
    (its 2 m strip, rule 5 of the room rule) touches the road's line. Then the room is 0 on both sides for the whole run, the frame
    has no width, and the junctions take the road with no roadway part (Avenue de l'Hermitage w4229537, 157 m; Square Beaumarchais
    w95825511 and w176477342; on the full build also Avenue de Grande-Bretagne w157719645 south of i0-1789813053, probably the same
    cause, not traced there). The commits since b0d9983 do not cause it (the
    cut with b0d9983 and the guard: A3 53 too). A test, not committed: a room that ignores the edge pieces that touch the line
    itself gives the cut A3 0 and every other hard check passes, but A1 3 -> 8. Not changed: it changes the agreed room rule. To
    decide with Kaveh (item 0b).
  - No traffic in urbanstyle (Kaveh): `unit --nvdb` and `--flows` removed, the city's traffic counts and the dossier's speed rule
    removed; NVDB is out of the sources. The part's `speed` comes from duckOSM's edges (`maxspeed_kmh`), never from raw tags and with
    no chosen default. Open (duckOSM work): the widths, `surface`, `lit` and the lane tags are still read from raw OSM tags
    (`container.ROADS`, `ground.py` alleys, `parts.py`); they belong in duckOSM's tables.
  - Not built: a square as a path intersection (stretches.md says so; squares stay plot pieces); Vancouver has 681 path sections and
    46 path intersections from 144 path items, not looked at on the page yet.
  - An older DuckDB (the system python3's) reads a NULL geometry that the newer one wrote as "not NULL with no shape":
    `dashboard.frame` drops such values, and page queries filter on `ST_AsWKB(x) IS NOT NULL`.
  - Vancouver's files are `data/units/broadway-granville.urban.duckdb*`; the code finds a pilot's city files by that name.
  - The site that port 8784 shows at `/docs/` is a copy in `viz/docs/`: after `mkdocs build`, run `rsync -a --delete site/ viz/docs/`.
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
- Vancouver (`data/units/broadway-granville.urban.duckdb`) is rebuilt with the final code: no count changed. Its fails: I3 1 (the
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

0b. **The room and the footways that touch a road (Monaco A3 499, 2026-10-17).** A walkway strip that touches a road's line sets that
   run's room to 0 on both sides, so the whole road gets no roadway. Proposals, not built: (a) the room ignores the edge pieces that
   touch the line itself (on the cut: A3 53 -> 0, A1 3 -> 8); (b) only walkways that run beside the road (a sidewalk line) are strips,
   not a footway that ends at the road; (c) the room is measured per piece of the run, not as one least value. Kaveh decides.

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
scratch/serve.sh vancouver     # the same on 8785 from data/units/broadway-granville.urban.duckdb
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
PYTHONPATH=src $P -m urbanstyle build data/units/broadway-granville.osm.duckdb data/units/broadway-granville.urban.duckdb --from division --bridge data/bridges-measured/granville-bridge.bridge.json
PYTHONPATH=src $P -m urbanstyle check data/units/broadway-granville.urban.duckdb --bridge data/bridges-measured/granville-bridge.bridge.json
PYTHONPATH=src:../roadstyle/src python3 -m urbanstyle dashboard data/units/broadway-granville.urban.duckdb viz/broadway-granville.html --bridge data/bridges-measured/granville-bridge.bridge.json
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
