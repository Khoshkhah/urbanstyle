# SimReady's roadway as the input of urbanstyle

Proposal, 2026-11-06. Kaveh decided the open points on 2026-11-06 (see "Decisions"). No code is changed.

Kaveh's direction (2026-11-06): urbanstyle takes the results of the SimReady project and does not make them again.
SimReady's decision D28 (2026-10-29) gives the same direction: "urbanstyle later takes SimReady's result as its input."
SimReady does not read urbanstyle (D28, D37), so the data goes in one direction only. This note replaces the method of
`simready-faces.md`: SimReady now makes its own faces, and `faces.py` has no user.

## What SimReady makes

SimReady's Rust build writes one DuckDB file per area, `../simready/out/<area>-rust/build.duckdb`, schema `sim`. On
2026-11-06 there are builds for Monaco, Tartu and Granville. There is no build for Södermalm. The Monaco build has these
tables:

| `sim` table | Rows (Monaco) | What it holds |
|---|---|---|
| `carriageway` | 2,093 | one directed road line, with its duckOSM `edge_ids`, its twin and its junction |
| `lane_section`, `lane` | 3,116, 3,677 | the lanes of each stretch, with width, use, turn and taper |
| `junction`, `island` | 681, 185 | the junction areas and the islands |
| `stop_line` | 2,960 | the stop lines and the give-way lines |
| `movement` | 2,761 | the lane-to-lane moves through each junction, with the path |
| `structure`, `structure_group` | 212, 56 | the bridges, tunnels and rings, with their levels |
| `elevation_profile` | 57,492 | the height of each carriageway every few metres |
| `kerb_line`, `street_face` | 6,537, 99 | the bounds of the roadway and one face per group and level |
| `signal_plan`, `signal_phase` | 13, 25 | the traffic signals |
| `attribute`, `event` | 79,884, 9,556 | each value with its rule, its source and its method |

Each row has the columns `ev_status`, `ev_method`, `ev_confidence` and, in most tables, `ev_source_ids`. These columns
give the real source of each value, as urbanstyle's rule on provenance needs.

## What urbanstyle stops making

| urbanstyle now | Replaced by |
|---|---|
| the road lines, the junction nodes and the sections in `network.py` | `carriageway`, `lane_section`, `junction` |
| the lanes from OSM, measured again by SUMO (`subsections.py`, `sumo.py`, `from_sumo`) | `lane` |
| the stop lines, the islands, the junction areas | `stop_line`, `island`, `junction` |
| the turns from SUMO (`turns.py`) | `movement` |
| the levels and the deck heights of the bridges (`bridge_profile.py`, `bridge_heights.py`) | `structure`, `structure_group`, `elevation_profile` |
| the faces per group and level (`faces.py`) | `street_face` |

After the change, urbanstyle does not run `netconvert`.

## What urbanstyle keeps

urbanstyle keeps everything outside the roadway: the buildings, the lots, the blocks, the ground (layer 0), the surfaces
(layer 1), the pedestrian realm from the roadway bound to the block side, the paths, the street objects, the strips, the
`urban` schema, its checks and the dashboard.

The pedestrian realm starts at SimReady's roadway bound. In `sim.kerb_line`, the roles are `bound` (the edge of the
roadway: 3,413 rows in Monaco), `kerb` (a kerb from a sidewalk way, a structure width or an OSM barrier: 1,793 rows),
`face_end` (the end of a band) and `unused`. D28 says that `bound` is the bound of the roadway, not the kerb.

The walking side comes from sources only (`rules-review-2026-11-12.md`, accepted by Kaveh 2026-11-12). It is cut at each
section's ends, and each piece goes to the space whose roadway it touches most. Then:

- the part of a piece inside a roundabout's central island (SimReady's `island`, kind `central`, with no `junction_id`) is an
  `island`. A roundabout's interior that is a block already stays the block;
- a piece is a `sidewalk`, whole, from the roadway to the street's edge, where an OSM footway or cycleway of its level runs in it
  for `WALK_IN_M` (2 m) or more, or where the nearest road's sidewalk tag (within `SIDE_TAG_M`, 25 m) covers its side;
- every other piece is `unmapped`: one flat part, with no bands and no kerb;
- the kerb mark runs only where a sidewalk meets the roadway.

The ground at level 0 under a bridge is `unmapped`: no source, SimReady included, describes it.

Who owns what, agreed with SimReady on 2026-11-12: urbanstyle owns the street's edge at level 0 (the blocks and the corridors)
and the walking side; SimReady owns the roadway, the islands (the central ones too), the lane ends at the junction areas and the
edges of the faces off level 0 (decks, tunnels). SimReady cuts each face off level 0 to its final lanes, junction areas and
islands (SimReady 39cd5bc). Off level 0, urbanstyle takes every SimReady carriageway and junction in the face, service roads too:
the faces hold every road of their bridge or tunnel chain. At level 0 it takes the streets only, because the blocks hold the drives,
aisles and alleys there. A junction area is cut by the section lanes of its own level only.

## The edge ids

urbanstyle joins SimReady's rows to its own by duckOSM's `edge_id`. The two projects must read the same duckOSM
database. On 2026-11-06 they do not:

- urbanstyle's Monaco build reads `../duckOSM/monaco.duckdb` (Monaco only). Of SimReady's 3,645 edge ids, 2,738 are in
  that database. SimReady has 907 more, mostly in the 300 m ring round Monaco. 27 urbanstyle edges are not in SimReady.
- SimReady's pass 0 reads `wide-cut.osm.pbf` (Monaco plus 300 m) with duckOSM's overrides, by duckosm-rust. Its result,
  `../simready/build/monaco/pass0-rust/monaco.duckdb`, has the driving network only, with no buildings, footways or
  features.
- `../duckOSM/data/monaco-wide/monaco-wide.duckdb` has 3,641 of the 3,645 SimReady edge ids. It also has the schemas
  `features`, `walking` and `cycling` that urbanstyle needs. urbanstyle's bridge profiles already read it.

The cause of the 4 other ids (found 2026-11-06): SimReady applies two override files, duckOSM's
`osm_overrides/osm_overrides.yaml` and its own `areas/monaco/osm_overrides.yaml`, and merges them into
`build/monaco/pass0-rust/osm_overrides.yaml`. The area file makes Impasse de la Fontaine a small roundabout (Kaveh's
review, 2026-11-03): way 200502086 keeps its west part, and the new ways 9000200502086 (the ring) and 9000200502087
(the east part) replace the rest. `monaco-wide.duckdb` is from 2026-10-17, before these overrides, so it has 6 edges
of the old way and not the 4 edges of the new ways.

The new input database, `../duckOSM/data/monaco-wide/monaco-wide.simready.duckdb`, has the same pbf, the same
boundary and SimReady's merged overrides file:

```bash
cd ../duckOSM && W=data/monaco-wide
.venv/bin/duckosm build -p $W/wide-cut.osm.pbf -o $W/monaco-wide.simready.duckdb -b $W/boundary.geojson \
  --fixes ../simready/build/monaco/pass0-rust/osm_overrides.yaml -m driving -m walking -m cycling
```

Result: all 3,645 driving edges and all 2,216 driving nodes are the same as in SimReady's pass 0, and all 3,645
SimReady edge ids are in it. The database also has `features` (4,146 buildings), `walking` and `cycling`.
`monaco-wide.duckdb` stays as it is, because the bridge profiles read it.

Rule: urbanstyle's Monaco build reads `monaco-wide.simready.duckdb` and keeps Monaco's boundary as its area. When
SimReady's overrides change, rebuild this database with the command above. A new check finds each SimReady edge id
that is not in the input database, and the build stops if there is one.

Vancouver: SimReady's `granville` area is Granville Island with a 500 m buffer, from `vancouver_city.osm.pbf`.
urbanstyle's unit is Broadway × Granville. Before the Vancouver unit can use SimReady, find out if the area covers the
unit. If it does not, SimReady needs a build of a new area. That is SimReady's decision.

## How urbanstyle reads SimReady

- A new module, `src/urbanstyle/simready.py`, written new (not a patch of `network.py`). It attaches the SimReady build
  read-only and writes the level-0 and level-1 rows of `work.unit`, `work.part`, `work.mark`, `work.junction` and
  `work.turn` from it.
- The option `--simready PATH` on `build` and on `scripts/cut.sh` names the file. Without the option, the build stops
  with an error. The build does not use the old modules (see "Decisions", item 3).
- urbanstyle copies no SimReady code and changes nothing in SimReady (SimReady's rule D35). A fault in SimReady's
  roadway goes to SimReady as a report. urbanstyle does not correct it.
- Each row keeps SimReady's `ev_method` and `ev_source_ids`, with `source = simready`.
- `urban.meta` records the path and, from `sim.project`, `simready_version`, `built_at`, `duckosm_version` and
  `osm_timestamp`.

## The checks

- The checks of the roadway that SimReady already does stop in urbanstyle: R1-R4 (the roadway at the joints), J3 (the
  connectors), U11-U13 (the lanes into each junction) and the SUMO part of U1-U10. SimReady's own results are in
  `sim.check_result`.
- The checks of urbanstyle's own parts stay: G1-G3, L1-L2, B1, B6-B8, W1-W3 and the dashboard sweep.
- New checks: every SimReady carriageway in the area has a unit; every SimReady lane is in one part; no sidewalk band
  overlaps the roadway between the `bound` lines.

## The blocks from SimReady's street face (Kaveh, 2026-11-06: "Yes, switch")

The Casino cut gave 84% of urbanstyle's street inside SimReady's street face, and SimReady's own review (2026-11-06-street-blocks.md)
reached the same number: SimReady now builds the street by urbanstyle's block method. In a SimReady build the blocks are no longer made
twice. `sr_blocks.py` (new; `blocks.py` stays as it is, for a build with no SimReady and for comparison) takes:

- **The street** at level 0: SimReady's ground face and its roundabout faces (`sim.street_face`, kinds `ground` and `roundabout`).
- **The drives** (an unnamed service way: `simready.is_street` false) are no street (`blocks.street_sql`). SimReady gives them lanes and
  a face along them. Their strip (lanes + `DRIVE_BUF_M`) is taken out of the street, except within `DRIVE_KEEP_M` of a street's lanes or
  junction areas, where the driveway crosses the pedestrian side (chosen values).
- **The blocks** are the box less the street. A block under `MIN_BLOCK_M2`, or thinner than `MIN_BLOCK_W_M`, is street (as `blocks.py`);
  a block cut by the area's edge is kept from `EDGE_BLOCK_M2`.
- **The sides** (`work.block_side`): for each street carriageway of SimReady near a block, one row per OSM way: the median distance
  from the carriageway's line to the block, `basis` `simready face`. The block's id is `b0-w<smallest way><l|r>` as before.
- **The corridors** (the paths): each pedestrian way (`blocks.path_sql`) that does not run along a street's lanes within
  `SIDEWALK_ZONE_M`, as a strip of its width inside the street, less the lanes and the junction areas.

The old branch of `blocks.py` that read SimReady's lanes is removed (it set the sides by rays).

- **The street holds SimReady's roadway**: its lanes and junction areas that its face leaves out (365 m2 in 33 spaces on the Casino
  cut, 236 m2 of it over a face of another level: a junction area at a node on a road that SimReady has in a tunnel or a cutting). A
  space is cut from rank 1's street (check B7).

Result on the Casino cut (2026-11-06), the build with `--simready`, against the same cut before this change:

| | before | now |
|---|---|---|
| B7: spaces reaching into a block | 43 places, 351 m2 | 0 |
| X1: crossings with no crosswalk | 42 | 0 |
| street (with paths) in SimReady's face | 61,624 m2, IoU 0.63 | 67,014 m2, IoU 0.81 |
| distance road to street edge within 1 m of SimReady's | 41% of 2,179 rays | 87% of 2,276 rays |
| the whole build | 352 s | 184 s (blocks 10 s, division 40 s) |

What still differs (10,217 m2 only in SimReady's face, 4,247 m2 only in urbanstyle's street): roads that SimReady has at another
level (Boulevard Louis II, Boulevard du Larvotto) are in its level 0 face and in urbanstyle's spaces of level -1; service ways;
and garden paths. Check B1 (INFO): 59 buildings reach over a block's edge, 4,181 m2; the largest is the Centre de Rencontre
International (layer -1, 675 m2 in the street), which urbanstyle puts at level 0.

## The blocks in a SimReady build, first trial (replaced by the section above)

`blocks.build(con, epsg, simready)` reads SimReady's roadway at level 0 (`simready.roadway`: the lanes of the streets):

- A street side that no sidewalk sets lies `MIN_EDGE_M` behind SimReady's lanes on that side (the 90th percentile of the
  square lines every `STEP_M`), not behind OSM's lane count times `LANE_M`. Its `basis` is `simready carriageway`.
- A building that stands on SimReady's roadway (over 1 m2 of it), or is nearer than SimReady's lanes, does not pull the
  side in: it is over or under the street (Monaco's port: buildings over Boulevard Louis II, the hall at `layer=-1` under
  Boulevard du Larvotto), or OSM draws it by its roof. It is drawn whole (check B1).
- A side that OSM's sidewalks set stays where they set it. Where SimReady's roadway reaches past it, B7 shows the place.

Casino cut, B7: 38 places (896 m2) with the old blocks, 18 places (598 m2) with these rules. No lane is in a block now.
All 18 are SimReady's junction areas. B1 (INFO) went from 42 to 46 buildings.

## Faults for SimReady, and the rules that fix them

urbanstyle's code does not change SimReady (SimReady's D35). The three rules below are in SimReady's `rules/design.csv`
as `candidate` rows (Kaveh, 2026-11-06), not committed there: `GD.drive-no-arm` (source `urbanstyle`),
`GD.continuation-area` (source `urbanstyle`) and `GD.corner-radius-room` (source `review`). A build applies `adopted`
rows only, so SimReady's build does not change until SimReady adopts and builds them. The places are on the Casino cut
(7.4278, 43.7395).

1. **A drive is no junction arm.** At 15 of the 16 SimReady junctions on the 18 B7 places (586 m2), an unnamed
   `highway=service` way, or one with a `service=*` kind (a drive, a car park entrance, an alley), meets the street, and
   SimReady makes it an arm: the junction area runs 10 to 20 m along it into the block. Largest: `i0-25239182` (179 m2,
   Avenue de Monte-Carlo with Place de l'Opéra's service ways), `i0-1684697734` (164 m2, Avenue des Spélugues with four
   service ways), `i0-21914809` (69 m2), `i0-1204288376` (41 m2). Proposed rule (junction-cut, junction-area): a node where
   only such a way meets a street is no junction; the street's lanes run on past it; the way joins the street by a
   connector at the street's kerb line, its mouth ends at that line, and it has no corner radius. A junction of streets
   that such a way also meets keeps the streets' arms only. The rule is `blocks.street_sql`'s (docs/design/street-rules.md):
   an unnamed service road is a drive across the pedestrian side, not a street.
2. **A continuation node has no junction area outside its lanes.** `i0-519323656` (case `JNC.continuation`, 2 arms,
   Boulevard Louis II goes on) has a junction area of 105 m2 that reaches 9.7 m2 into the block. Proposed rule: at a node
   where one road goes on (2 arms, no branch), the junction area is the lanes' own surface, or there is no junction
   (urbanstyle's rules 1-4, docs/notes/sections.md: a junction only where a road ends, merges, forks or two streams cross).
3. **The corner radius takes the room into account.** `curb_radius_right_turn_m` is 9 m for every pair of roads (the
   first value, from a worked example for two primary roads). At `i0-21912099` (Avenue de la Costa, Avenue Princesse
   Alice) the 9 m corners reach past OSM's sidewalk line (5.3 m from the road's line). Proposed rule: the radius by the
   smaller road's class, and never past a mapped sidewalk way or a building at that corner (the bounds `import-kerb`
   already finds). One place only: more places are needed before the value changes.

## Decisions (Kaveh, 2026-11-06)

1. Bridge heights: the build uses SimReady's heights (rules only, SimReady's D38). The heights that LiDAR measured
   (`bridge_lidar.py`) are a comparison, not a build input.
2. Södermalm waits for a SimReady build. urbanstyle does not build Södermalm on the old path in the meantime.
3. The old modules (`sumo.py`, `turns.py`, the roadway code in `network.py`, `bridge_profile.py`, `bridge_heights.py`,
   `faces.py`) stay in the repository. The build does not use them. They are for cross-validation: a comparison tool
   runs them on the same area and reports the differences from SimReady's roadway.

## The order of work

1. Find the cause of the 4 edge ids. Make the edge ids equal. Done 2026-11-06 (see "The edge ids").
2. Write `simready.py` and test it on a Monaco cut (`scripts/cut.sh`). First version 2026-11-06:
   `SIMREADY=../simready/out/monaco-rust/build.duckdb scripts/cut.sh monaco NAME LON LAT`. It takes the streets only, by
   `blocks.street_sql`'s rule (SimReady gives every service road lanes), and only the junctions that a street carriageway
   ends at or runs inside. Not in it yet: crosswalks, turn arrows, subsections where the lanes change along a section,
   SimReady's heights. Open faults on the Casino cut (7.4278, 43.7395): the blocks are set from urbanstyle's own
   carriageway widths, so SimReady's wider lanes reach into them (B7, 38 spaces); SimReady's junction areas keep the
   mouths of the service roads (spikes); SimReady's junction rule differs from rules 1-4 (J1, 35).
3. Show the cut and the current cut side by side at the same places, with pictures.
4. After Kaveh agrees, do a full Monaco build and run `urbanstyle check` before and after.
5. Put the design into its chapter in `docs/design/` and update `docs/plan.md` and `docs/design/glossary.md`.

## The Monaco build (2026-11-07)

`urbanstyle build ../duckOSM/data/monaco-wide/monaco-wide.simready.duckdb data/monaco-sr.duckdb --simready ../simready/out/monaco-rust/build.duckdb`
(Monaco plus the 300 m ring; 1,590 carriageways, 645 junctions, 297 blocks, 1,250 corridors, 949 crosswalks, 1,474 spaces). It took
about 5 hours: containers 500 s, blocks 404 s, division (simready) 5,449 s, ground 11,978 s. The cut of 500 m takes 184 s, so two
steps grow faster than the area (not known which part of them yet).

Checks against the newest old build (`data/monaco-r.duckdb`, 2026-10-27, Monaco without the ring, so the counts are not like for
like), both without the bridge checks:

- Better: A1 37 to 0, M1 4 to 0, U7 7 to 0, B8 195 to 0, J4 88 to 0, U13 33 to 0.
- Worse: U2 1 to 356 (spaces in more than one part: 24% of the spaces, as on the Casino cut), U1 0 to 91, W3 1 to 122, J1 0 to 215,
  A3 0 to 56, W1 2 to 19, U6 2 to 43, J2 0 to 20, J3 0 to 10, B7 0 to 2, U4 0 to 2, U5 0 to 1, U9 1 to 4.
- Failing checks: 10 before, 15 now.

The causes known so far: U2 and U1 are in `simready.py` (a space is the union of its parts, and the pieces of the walking side that a
space gets do not always touch); J1 is a difference of rules (SimReady makes a junction at nodes where urbanstyle's rules 1-4 do
not); W3 and A3 come from the levels (SimReady's level of a road against urbanstyle's). The page of the Monaco build is not made yet.

## SimReady's note on garden paths (Kaveh, 2026-11-07)

SimReady's note (`../simready/docs/reviews/2026-11-07-note-for-urbanstyle.md`): a footway inside a park, a garden or a building, or a
dead end, does not cut a block. SimReady applies these rules in its street face (its rows `path_*`). urbanstyle takes them from the
face and does not write them again: not in `sr_blocks.py`, and not in `blocks.py`. A build without SimReady (Vancouver) has no such
rule until SimReady has an area for it.

SimReady rewrites `out/<area>-rust/build.duckdb` (its build of 2026-11-07 10:53 has these rules; the one of 05:45 had not), and its
process holds a lock on the file. Use a copy for a long run: `urban.meta` and `work.simready_input` keep the build's time.
