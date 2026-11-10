# urbanstyle in the browser, in Rust

Proposal, 2026-11-07. Kaveh agreed the four decisions (2026-11-07). Steps 1 and 2 are done (see "Status").

Kaveh's target (2026-11-07): all of urbanstyle runs in the browser, so it is Rust (WebAssembly) only, with no Python. SimReady's
pipeline already runs so (`../simready/rust`: `duckosm-sim`, `duckosm-sim-wasm`; geo 0.33, rstar, i_overlay; no GEOS).

## What it means

- The Python code is the reference and the prototype, as in SimReady's decision D30: Python runs on small clips, and Rust writes the
  golden files of the whole area. A rule is first right in Python, then in Rust.
- A step that runs in the browser cannot call GEOS (shapely), SUMO, or DuckDB's spatial SQL functions (`ST_*`). Plain SQL is
  possible in DuckDB-WASM. Geometry is `geo`, `rstar` and `i_overlay`.
- The time of a step is the time in the browser (WASM is about 1.5 to 2 times slower than native Rust).

## What to port, and what not

| Python module | Lines | Port? | What it needs |
|---|---|---|---|
| `sr_blocks.py` (the blocks from SimReady's face) | 153 | yes, first | union, difference, buffer, buffer by a negative distance, nearest, an index |
| `simready.py` (the division: spaces, walking side, crosswalks, marks) | 527 | yes | the same, and cutting a polygon by lines (polygonize), substring, offset curve |
| `ground.py`, `paths.py` (rank 1 and the paths) | 640 | yes | the same, and a planar partition of all outlines (polygonize) |
| `product.py`, `meta.py` (the model `urban`, the registry) | 1,040 | yes | the tables as Arrow or Parquet; the axes of a space (line locate and interpolate); a stable id |
| `checks.py` | 807 | yes, last | the same predicates |
| `engine.js`, `panel.js` (the page) | | already the browser | they read the same tables |
| the old SQL containers (`CONTAINER`, `STATIONS`, strips), `network.py`, `turns.py`, `sumo.py`, `subsections.py`, `spaces.py`, `parts.py` | | no | their results come from SimReady, or they are removed from a SimReady build |
| `blocks.py` (the rays) | | no | SimReady's face replaces it |

Still needed from the old containers step, and not in SimReady: the elements and their levels (SQL on duckOSM's tables), the street
objects, the links (stairs, ramps), the named streets (`street`, `arm`), and the building use. Each needs a new source or a port of its
own SQL. This is the largest open question.

## The geometry, and what the Python code uses now

The four files above call shapely 100 times, mostly `union_all`, `get_parts`, `make_valid`, `to_wkb`. The ones with no direct
equivalent in `geo`:

- `polygonize` (the cuts across the walking side, the planar partition in `ground.py`): write it, or use SimReady's own if it has one.
- `make_valid`, `set_precision` and `grid_size=0.01` in the overlays: the Python code uses them to keep hairlines out. The Rust code
  must not need them: make the polygons valid by construction, and snap once at the end (a rule to agree).
- `line_merge`, `offset_curve`, `substring`, `clip_by_rect`: small, write them.
- `buffer`: SimReady's `street_space.rs` has a `buffer` on `geo` (a line, and a polygon by a negative distance). Use the same.

## The order

1. A crate with the geometry helpers and their tests against shapely on the Casino cut (the same helpers: `poly`, difference,
   intersection, buffer, indexed neighbours).
2. The blocks (`sr_blocks`): small, and it checks the helpers.
3. The division (`simready`): the walking side, the crosswalks, the marks.
4. The ground and the paths.
5. The model writer and the registry.
6. The checks.

After each step: the Python reference on the Casino cut and the Rust result must agree (a tolerance by area, as SimReady's clip
check), and the Monaco golden file is written by Rust.

## Decisions for Kaveh

1. The code lives in urbanstyle's own workspace (`rust/`), as SimReady's does (D35), with the crates of the same versions. SimReady's
   crates are libraries that it can use by path. Yes or no?
2. The Python code stops getting speed work now (the fixes of 2026-11-07 stay). Python is kept correct, not fast.
3. What replaces the old containers step for the elements, the street objects, the links and the named streets: SimReady's tables, or
   a port of the SQL?
4. The time budget for each step in the browser (the division was asked to stay under 1 minute).

## Status (2026-11-07)

The code is in `rust/` (its own workspace; geo 0.33.1, rstar 0.12.2; builds for `wasm32-unknown-unknown`). Run
`cd rust && CARGO_BUILD_JOBS=2 cargo test --release --offline --workspace`. The tests read data that Python writes and that is not in git
(`rust/tools/export_geo_fixture.py`, `rust/tools/export_blocks_fixture.py`, to `data/cuts/`); without it they say so and pass.

**Step 1, `urbanstyle-geo`:** the helpers (union, difference, intersection, buffer, mitre buffer, flat-cap line buffer, `wide`,
an index of boxes, project and interpolate). 4 tests against shapely on the Casino cut: the booleans agree to 1e-6, the buffers within
0.3%, `wide` within 0.5%. The street of the cut (union, difference, intersection) takes 3 ms.

**Step 2, `urbanstyle-blocks`:** the port of `sr_blocks.py`. On a square kilometre of Monaco (SimReady's build of 2026-11-07 18:34),
against the Python reference: 88 blocks (88), all 85 blocks of 100 m2 or more match to 1%, 95% of the 355 sides agree to 5 cm (the
others to 1.1 m, and the measuring is shapely's own on our blocks: 0 of 359 differ), 83 of 85 ids equal, 181 corridors (181) with the
same area to 0.03%. It takes 1.7 s native (street 0.55 s, blocks 0.24 s, sides 0.14 s, corridors 0.77 s). For Monaco, 5.4 times the
area, I expect about 9 s native and 14 to 18 s in the browser: over the budget of 10 s. The street (the union of 3,000 lane polygons and
the overlays with the face) is the next thing to make faster.

**What the port found** (each is in the code, with its reason):

- `i_overlay` states the mitre limit as the smallest interior angle, not as shapely's ratio: `2*asin(1/limit)`. A limit of 5 read as 5
  radians bevelled every corner.
- A union of polygons that wind the other way loses them (a lane drawn the other way round vanished from the street): orient the input
  (`ops::orient`, `Input::oriented`).
- GEOS gives a polygon whose outline touches itself as two polygons: `ops::normalize` does the same after every overlay.
- The Python overlays snap to a 1 cm grid, so a hairline neck that joins two pieces of land at the area's edge is gone there. The port
  opens those pieces by 1 cm (`HAIRLINE_M`).
- `clip` can give a line in several pieces, in any direction: they are merged and put in the direction of the line, or the sample points
  move.
- An overlay with one big polygon for each of 475 paths took 4 s: each path is measured against the lanes and blocks near it, from
  indexes. The lanes, junction areas and drive lanes are inputs as lists of polygons for this.
- The block ids and `b0-e<k>` numbers depend on the order of the pieces: the port sorts them by their centroids.

**Step 3, `urbanstyle-division`:** the port of `simready.py` (spaces, roadway parts, the walking side cut at the section ends, the
crosswalks, the marks, the rows). On the same square kilometre, against the Python reference: 324 of 324 spaces; the area of each part
type within 0.01% for lanes, junction areas, crosswalks, bus and cycle lanes (the same counts), within 0.25% for frontage, furnishing
and sidewalk, and 2.6% for islands; all marks equal except the kerb (+3.0% in length); the 185 junction rows, 557 turns and 349
approaches are equal. The tests assert these limits (`tests/division_cut.rs`). What differs is who owns a piece of the walking side
when two units touch it for nearly the same length: the Python overlays snap to 1 cm, so the two codes can pick different units.
It takes 1.8 s native for the kilometre (6.4 s at first). Two changes did it: the cuts are clipped to the realm with an index of its edges
(`index::SegIndex`, in place of one clip against a polygon of 30,000 edges), and the length of an outline near the street's edge or near a
roadway comes from the segments (`index::NearIndex`: the part of a segment inside the capsule of another is one interval), in place of
a buffer of 100,000 pieces. Both give the same numbers as the first code. What is left is spread evenly: the street and the realm
(0.43 s), the slice (0.37 s), the kerb and the bands (0.38 s), the owners (0.29 s), the crosswalks (0.15 s). For Monaco I expect about
10 s native, so 15 to 20 s in the browser: still over the budget of 10 s. The crate builds for `wasm32-unknown-unknown`.

**Step 4, the ground and the paths (`urbanstyle-ground`, `urbanstyle-paths`):** `ground.build` is split in Python into `gather` (the SQL: the area,
the kinds in the order they take the ground, the blocks' land, the road and path lines) and `assemble` (the geometry), and the crate
ports `assemble`. On the same kilometre: every kind has the area of the Python result to 0.01% (building, water, green, street, path,
alley, yard, car park, square, structure), no matched item differs by more than 1%, and the rows cover the area once (0.01 m2 of gaps
and of overlaps). It takes 1.8 s native. The Python `assemble` is not exactly repeatable (a few alleys differ by metres between two
runs), so the test uses limits. What the port found:

- `ops::normalize` rebuilt a pinched polygon from rings that wind the other way, and a later union filled its holes (the left-over
  ground came back 2,400 m2 too large, and yards lay over buildings). `normalize` now orients its output.
- Pieces that touch leave slits of a millionth of a metre between them. They join the left-over ground, make its outline 4 times as long,
  and a normal piece then looks like a sliver. The Python 1 cm grid has no such slits. The port opens the left-over ground by 1 cm
  (`HAIRLINE_M`), as it does in the blocks.
- The final polygonize of Python is a sequence of differences here: each item is cut by the pieces taken before it, so the items do not
  overlap, and the ground no item holds joins the neighbour it shares the most edge with (`NearIndex`).

The paths (`paths.build` is split in Python the same way: `gather`, `assemble`): `urbanstyle-paths` cuts each path item at its path
junction nodes. On the same kilometre, against Python: 387 spaces (387), 383 faces matched by area inside each id, the same area (18,875
m2), kind, nodes, links and length for each; the way that names a face differs for 13 (two ways of the same length tie), and 4 ids of the
248 take another way's name. It takes 0.04 s.

**Monaco, all of it (2026-11-07, native, from `data/monaco-sr3.duckdb`):** the four steps ran on the whole of Monaco. The first run took 76 s
(blocks 24.4, division 13.2, ground 38.4, paths 0.2): three parts grew faster than the area, so the estimate (the kilometre's time times
5.4) was wrong by a factor of 2.5. Each had the same cause, an overlay of a small piece with a polygon of thousands of edges, or a search
that looks at everything. After the fixes:

| Step | Before | After | Against Python |
|---|---|---|---|
| Blocks | 24.4 s | 9.0 s | 244 of 245 blocks match (one of 1,620 m2 comes out 1,150 m2); 701 corridors of 701, same area |
| Division | 13.2 s | 5.9 s | 1,472 of 1,472 spaces; parts within 0.3% (islands 1.2%); kerb +3.2%; one crosswalk fewer |
| Ground | 38.4 s | 14.0 s | every kind within 0.5%; 0.3 m2 of gaps and overlaps |
| Paths | 0.2 s | 0.2 s | 1,514 of 1,527 faces match by area |
| All | 76 s | 29 s | |

The second run was on a busy machine (load average 8 to 17), so the times are the slower ones. In the browser this is 45 to 60 s, at the
target of 60 s. The fixes:

- `ops::clip_by`: a piece is cut by the edges of the other polygon near it (`slice`), and each part is kept by a point inside it. The
  corridors (17.9 to 0.8 s) and the ground's clip of 4,000 buildings to the blocks (25 s) used an overlay with a polygon of 20,000 edges.
- `NearIndex::nearest_tag`: the unit nearest to a piece that touches no roadway (it measured the distance to every line of every unit:
  7.6 to 0.3 s). `NearIndex` also splits long segments into pieces of 10 m, as the box of a long edge meets most queries.
- The ground stopped inside `i_overlay` on Monaco (a difference against pieces that share edges, the tiles of one piece); the pieces
  are now joined first.
- A result that is the input unchanged must be oriented too, or a later union loses it (the winding trap, again).

The Monaco ground has one more item than the Python ground: a building of 4,905 m2 (`r11384697`) that the Python `assemble` drops (it
skips an item after a GEOS error). The limits of the tests are those of the kilometre, so on Monaco they fail on these differences only
(one block, one crosswalk, that building, the ties of the paths).

**Step 5, the model writer (`product.py`, 720 lines; plan, 2026-11-07).** `product.write` makes the tables of `urban` from `work`. Its parts,
by what each needs:

| Part | Python | Needs | Slice |
|---|---|---|---|
| The axes: (s, t) of a part or a mark on its space's axis, a part's own axis | `_st`, `_chain`, `shift_line` | `lines::project`, `interpolate`, `substring`, a vertex-by-vertex shift | 1 |
| Sections: the subsections of a section chained into one axis, the space rows | `write` | the chain | 1 |
| Parts under 2 m2 join the part of their side with the longest shared edge | `write` | `NearIndex`, `ops::union` | 1 |
| Parts, marks (s, t, axis, ids) | `write` | the above | 1 |
| Rank 1 (street pieces, plots, paths), plot pieces, path spaces | `write` | `ops`, `best` (inner point, covers) | 2 |
| Sections' ends at intersections, nodes, predecessors and successors, lane links, turns, approaches | `write` | `NearIndex`, nearest part | 2 |
| Intersections cut into one piece per junction node; roundabout ring and centre | `cut_intersection` | a cell of the nodes (the half planes between nodes, no Voronoi crate), a ring polygon | 3 |
| Elements, lots, street and arm (named streets), joints, links, stations, surfaces, objects, observed, photos | `write`, `_objects` | the old container step's tables: no Rust source yet | 4 (decision) |
| `uid` of the registry, `urban.meta`, `urban.style`, `urban.code` | `meta.py` | the kept ids of the last build | 5 |

**Slice 1 is done** (`rust/urbanstyle-model`): its test feeds the Python `work` rows to the Rust code and compares with `urban.space`,
`urban.part` and `urban.mark` of the same build, so a difference is the port's, not the division's. On the cut: 188 spaces, 1,458 parts and
931 marks, all equal ((s, t) to a millimetre, the area of each part, the length of each part axis); 28 ms. On Monaco: 827, 6,711 and
4,427, all equal but one part axis length; 0.2 s. The parts under 2 m2 are joined as in Python. **Slice 2 is done** (same crate, `rank1.rs`, `stretch.rs`; 2026-11-07). The test compares with `urban.ground`, `plot_piece`, `stretch`, `arm`,
`street`, the path rows of `space` and `part`, and the links inside a section (the links that run into an intersection come with slice 3):

| Table | Cut (188 subsections) | Monaco (827) |
|---|---|---|
| `ground` (street pieces, plots, paths) | 365 of 365 | 1,374 of 1,374, but one tunnel piece (level -1) is split in two in Rust, so 4 numbers and 9 parents of stretches there differ |
| `plot_piece` | 1,200 of 1,200 | 6,369 of 6,369 |
| `stretch` (sections, intersections, path spaces) | 711 of 711, every field | 2,999 of 2,999; 2 roundabout flags (a ring line of about 5 m), 9 parents |
| `arm` | 325 of 325 | 1,481 of 1,481 |
| `street` | 93 of 93 | 388 of 388; 1 name (two names tie) |
| path `space` and `part` | 387 of 387 | 1,527 of 1,527 |
| lane links and subsection links in a section | all equal | all equal |

The model takes 0.12 s for the cut and 1.2 s for Monaco. Two traps again: a polygon wound the other way is lost in a union (the input is
oriented once, `Input::oriented`), and a candidate that only shares an edge with the child is still a candidate for its parent.

**Slice 3 is done** (same crate, `intersect.rs`, the new part of `lib.rs`; 2026-11-07): the intersections cut into one piece per junction
node (a roundabout: its ring sectors and its centre), their parts cut the same way (one junction area for each piece, parts under 2 m2
joined), the links of the spaces (a subsection to the piece its axis reaches, a piece to its arms and neighbours), the lane links at the
sections' ends and through the intersections by SUMO's moves, the junction rows, the marks of the intersections, the sides with their
kerb, the turns and the approaches. The cell of a node is the intersection of the half planes between it and the other nodes, so no
Voronoi code is needed.

| Table | Cut | Monaco |
|---|---|---|
| Pieces of intersections (kind, parent, links, area) | 180 of 180 | 880 of 880; the name of 2 differs |
| `junction` | 185 of 185 | 897 of 897 |
| `part`, all (id, space, side, links) | 3,126 of 3,126, links all equal; 5 areas differ by 0.6 m2 (one intersection) | 13,685 of 13,685, links all equal; the same 5 areas |
| `side` (area, kerb length, source) | 1,107 of 1,107 | 4,854 of 4,854 |
| `mark`, all | 2,395 of 2,395; the part of 13 zebra marks differs | 10,475 of 10,475; 50 |
| `turn` | 557 of 557 | 2,644 of 2,646 |
| `approach` | 349 of 349 | 1,646 of 1,646 |

The model takes 0.2 s for the cut and 1.6 s for Monaco. A zebra mark that lies on two parts goes to either: the two codes pick differently.

Open decisions for slice 4 and for the output: where the elements, the named streets and the objects come from (SimReady's tables, or a port
of the SQL), and how the tables reach the page (Arrow or Parquet in the browser: the `arrow` and `parquet` crates build for wasm, with a
larger download).

**Slice 4, option A (page first; Kaveh chose it 2026-11-07).** Done: 4a, the layer-1 surfaces (`urbanstyle-ground/src/surfaces.rs`, test
`tests/surfaces_cut.rs`, fixture `rust/tools/export_surface_fixture.py`). The cut: 2,065 of 2,065 surface ids, 2,503 pieces matched, area
998,814 against 998,822 m2; Monaco: 9,986 ids against 9,980, every kind within 0.01%, 1.0 s. One known difference: the Monaco build used an OSM
database with no garden polygons, so Python has no `garden` surface (4,616 m2 in Rust, taken from `yard`); garden and yard are compared together.
Done: 4b, the building and lot rows of `element` (`urbanstyle-model/src/elements.rs`; levels from the tags as in `BUILD` and `CLAMP`, floors, height,
and the use rules of `buildings.py` without the Vancouver data; exporter `export_element_fixture.py`). The cut: 695 of 695 rows, every field.
Monaco: 4,184 rows against 4,183 (one more building), 14 `ground_use` values differ where two business types tie (the order of the points
differs between the two OSM database versions); 7 ms. Done: 4c, the street objects (`objects.rs`; the class of an OSM node by its tags, its
level, its space and part, the nearest space within 60 m, the size of its class; exporter `export_object_fixture.py`). The cut: 530 of 530,
every field. Monaco: 2,373 of 2,373; one `near_m` differs by 0.01 m (rounding); 40 ms. The matching of several sources (`unit.match`) is not
ported: with OSM as the only source each node is its own object. Mapillary and a city's survey are not read.
DuckDB facts used: `try_cast('3.5' AS INT)` gives 4 (round half away from zero), `try_cast('3;4' AS INT)` gives NULL.
Slice 4 is done; the tables the page never reads (link, station, joint, observed, photo) are left to the Python build.

**Step 6, the checks (`checks.py`, 807 lines about 50 checks; group 1 done 2026-11-09).** The checks are SQL on spatial functions over the `work`
tables. The crate `urbanstyle-checks` runs them on the geometry of a build as stored. Group 1, the partitions, `partitions()`: U1 to U9 (the
spaces overlap, are valid and one part, have their nodes and lines right, and are covered by their parts), U11 to U13 (the approaches), G1 to G3
(the ground partitions the area), L1 and L2 (the surfaces cover their ground item), B1, B7 and B8 (the blocks). Against `urban.check` of
Python for the same build, all 20 counts are equal, on the cut (U1 21, U2 50, B1 103, ...) and on Monaco (U1 95, U2 247, U6 34, B1 516, ...).
On Monaco they take 6 s native; B1 and B7 went from 19 s to 0.6 s with `ops::clip_by` (a building against a block of thousands of edges). The
largest part left is G3, the union of 9,000 ground items (3.5 s). Fixture: `rust/tools/export_check_fixture.py`.
**Group 2, the roadway checks (2026-11-09; `roadway.rs`):** R2 (guide lines off the roadway), R3 (OSM lanes that do not fit), W1 (a street line between
two pieces of roadway with none under it), W2 (the roadway reaches a joint at different points on its two sides), W3 (the levels join where
streets of two levels meet), R4 (lane edges at a joint). Against Python, on the cut / on Monaco: R2 3 / 42 (equal), R3 0 / 0, W1 2 / 17, W3 18 / 122
(equal); W2 3 against 4 / 43 against 42 and R4 79 (equal) / 471 against 479 (borderline joints at the 0.2 m limit and the 0.1 m reading). They add
1 s on Monaco. New helpers: `SegIndex::distance`, `NearIndex::pieces_within` (the parts of a ring along another outline: the shared edge of two
spaces). Not ported: R1 (0 in both builds; it reads `work.change`, which the SimReady path does not have), U10 (0; reads `work.cut`), the
checks of the old container step (P1 to P7, S1, S2, I1 to I4, C2: `work.container` is not in the new model), the rules A1 to A3, J1 to J4, K1, K2,
M1, X1, and the bridge checks BR1 to BR12. The fixture has the guide lines, the roads and the sections too.

**Group 3, the street rules (2026-11-09; `rules.rs`):** A2, A3, J1, J2, J3, K2, M1, X1 (level 0). Against Python, on the cut / on Monaco: A2 0 / 0, M1 0 / 0,
X1 0 / 0, J1 57 / 216, J2 6 / 20, J3 4 / 10, K2 580 / 2,994 (all equal); A3 6 (equal) / 52 against 54. Together with the partitions (group 1) and the
roadway (group 2), the Rust crate runs 34 of the 52 checks of Python; on Monaco all of them take about 9 s native. Not ported, and why: A1 (lanes off
their OSM line: 0 in every build), K1 (a city's catch basins: none in Monaco), J4 and R1 (`work.change`), U10 (`work.cut`), the checks of the old
container step (P1 to P7, S1, S2, I1 to I4, C2) and the bridge checks BR1 to BR12.

**Step 5, the registry (`meta.py`; 2026-11-09; `urbanstyle-model/src/registry.rs`, `style.rs`).** The profile of every thing of the model (the facts that do not
change from build to build, as text), the uid kept from the last build for a profile that is still there and a new one for a new profile (the caller
gives the uid generator and the clock), the manifest rows (`meta()`: version, time, inputs, and every crate's chosen numbers from its `chosen()`),
and `urban.style` and `urban.code` (generated from the Python lists by `rust/tools/gen_style.py`). Against Python: on the cut all 10,876 things have
Python's kind and profile, all uids are kept (0 new), the registry has 10,489 rows (Python 10,489), the style (71) and code (43) rows are equal.
On Monaco 49,334 of 49,514 uids are kept: the profiles of the tunnel street pieces (one piece split in two shifts the `#n` of the rest, 8 things)
and of 168 unnamed intersections (the build's older OSM database had roundabout rings for two intersections that the current one lacks: the kind
`roundabout` and `intersection` count apart, so every later unnamed intersection shifts by one) differ. 33 ms for 49,000 things.

**The whole build in one chain (2026-11-09; `rust/urbanstyle-build`, `urbanstyle-tables`).** `urbanstyle-build DIR PREFIX OUT_DIR` runs the blocks, the
division, the building rows, the ground, the surfaces, the paths, the model, the street objects, the checks and the registry, each step on what the step
before it made, and writes the 20 tables of the page as Parquet (`urbanstyle-tables`: the layout of `publish._tables`, GeoJSON in lon/lat from the UTM
zone 32 inverse; 187 MB for Monaco). The raw inputs (SimReady's tables, duckOSM's features) are still the JSON files of the Python exporters
(`read.rs`): one second for Monaco. Readers of the tables themselves are the one part not done.

Monaco, all of it, native, one thread, 2.4 GB (the last run):

| Step | s |
|---|---|
| read and parse the JSON files | 1.1 |
| blocks | 7.2 |
| division | 5.2 |
| ground | 27.2 |
| surfaces | 7.2 |
| paths | 1.0 |
| model, elements, objects, registry | 4.6 |
| checks (34) | 13.6 |
| Parquet tables | 3.4 |
| **all** | **70.3** (wall 70.7) |

In the browser (1.5 to 2 times slower) this is about 105 to 140 s: over the target of 60 s. The ground is the largest part (27 s: the kinds take the
ground 11 s, the ground a road or path runs through 6.5 s, the partition 3.4 s), then the checks (G1 to G3 6 s), the blocks and the surfaces.

What joining the steps needed (each is in the code with its reason): the division gives the turn and approach rows and the lane parts' road; its parts are
snapped to the 1 cm grid, opened by 1 cm (what `set_precision` does) and the space is the closed union of them (`ops::snap`); each ground piece cut by a
neighbour is opened by 1 cm and a multi-part item is closed by 1 cm, and a polygon under 0.001 m2 is no row (else the chain made 4 times Python's rows from
hairlines); the street pieces of rank 1 are closed by 1 cm (`close_gaps_m`); W2 reads two edges 5 mm apart as one. A union of one multipolygon alone
dropped polygons: `snap` unions with an empty set. Against Python the chain gives, on the cut: the same units, blocks, corridors, sections, intersections,
roundabouts, turns and approaches, and the same counts for U1, U4, U6, U12, B7, R2, R4, W1, W3, A3, J1, J2, J3 (U2 54 for 50, B1 101 for 103, K2 563 for
580, W2 19 for 4); on Monaco, U1 95, U4 1, U5 1, U6 34, U8 1, U9 9, U12 95, G2 0, G3 0, L1 0, L2 0, B7 2, R2 42, W1 17, W3 122, J1 216, J2 20, J3 10 (equal),
and U2 261 (247), B1 518 (516), R4 489 (479), A3 52 (54), K2 3,162 (2,994), W2 137 (42). W2 is not tuned: the edges of the snapped spaces no longer
coincide exactly.

**The ground without a loop (2026-11-09).** The kinds no longer take the ground item after item. `urbanstyle-ground` cuts the area once with the outlines
of all items (`ops::slice`) into faces. It gives each face to the first item, in the order of the kinds, whose outline holds a point of the face. An item
that wins under `MIN_M2` takes nothing and leaves its faces to the next. Before, each item took the union of all earlier pieces near it (7 s of the 11.6 s
of this step on Monaco). Now the step takes 5.7 s, and the step for the ground that a road or path runs through takes 2.4 s, down from 7.3 s (one
`SegIndex` for each polygon, not for each line). These times come from a machine at load 20; the run of the whole chain was not timed on a quiet machine.
Against Python on Monaco the area of every kind is within 0.5%, and all checks give the same counts as before. The cut tests pass. The Monaco ground
test fails with the old code too (one extra building). Checks are off in a build unless you give `--checks`.

**Speed, 2026-11-09 (later).** The blocks step measures the sides with a `SegIndex` of the area and of each piece (6.8 s to 0.16 s). The surfaces step gives the small left-over pieces to the nearest surface in one batch (9.1 s to 5 s). A try to cut the surface claims with one arrangement (v3) gave other counts (roadway 1662, not 1747), so it is removed. `urbanstyle-build` skips the checks unless you pass `--checks`. Monaco, whole chain native, no checks, load about 4: **41 s** (ground 13, surfaces 7.6, division 5.4, model 5.1, tables 3.6, blocks 3.3, paths 1.4, read 1.4). With `--checks` the checks add about 14 s. The check counts equal the Python list, except K2 (3160, Python 3162). Browser estimate: 60 to 80 s.

**Slivers, 2026-11-09 (night).** The slivers step of the ground joins them to their item in one union per item, and its index of joined rings has a big part and a small part (rebuilt after 64 rings): 1.44 s to 0.26 s CPU. `URBANSTYLE_TIMING=cpu` prints the CPU time of each thread, which a busy machine does not stretch. K2 changes between 3160 and 3162 from run to run, with the same code.

**Division bands, 2026-11-09 (night).** The walking side cuts the furnishing, sidewalk and frontage bands of all the pieces of a unit in one overlay each, then gives every part to the piece it lies in. Before, each piece was overlaid with the buffer of the unit's whole kerb. The lap "kerb and bands" went from about 3.4 s to 2.35 s CPU. What is left in it: the kerb line cut (0.76 s) and the two kerb buffers (0.75 s). The division tests pass and the check counts are the same.

**Surfaces, 2026-11-09 (night).** A ground item whose claimed pieces fill it skips the left-over difference (the "green" items: 0.8 s). The street items cost 5.6 s of the 7 s: claims 1.0, take 1.6, left-over difference 2.3, join 0.7. Keeping the union of the taken pieces as one running union was slower and changed the counts (roadway 1753, not 1747), so it is removed. The ground partition keeps its gaps in an ordered map: the ground rows are now 1534 in every run. The marks still change by 1 between runs (10230 or 10231): the cause is in the division or the model, not found.

**Same output on every run, 2026-11-09 (night).** Two things changed the output between runs: `lines::merge` joined pairs in the order of a hash map (the start of a closed ring changed), and `NearIndex::covered_by_tag` added floats in the order of a hash map. Both are ordered now. Three runs give the same Parquet files (12 files compared by hash). `geo` is built without its default features, so `i_overlay` does not use `rayon` (the browser has no threads either): Monaco takes the same time, about 41 s on a quiet machine, so the native time is a fair guide for the browser. All workspace tests pass, the `wasm32` build works, and the check counts equal the Python list (K2 3162).

**First reader, 2026-11-10: the division input from Parquet.** The new crate `urbanstyle-simready` has `wkb` (the geometry columns), `table` (a Parquet file with typed columns by name) and `division::read` (the carriageways, lanes, junctions, islands, stop lines, moves and the faces of the other levels, from SimReady's `<area>-rust/*.parquet` and duckOSM's `edges_driving.parquet`). SimReady's geometry is WKB in UTM metres, so no projection is needed. Monaco: 0.13 s, against 1.4 s for the JSON fixture. The test `tests/division_read.rs` compares with the fixture: the 1,590 carriageways are the same (line, way, class, level; the lines differ by 4 nm at most). The Parquet files are of a later SimReady build than the fixture, so 961 of the 2,960 lanes with the same id have other lines, 229 another width (3.5 m default, not 3.25 m) and 59 lane ids are new. The 1,999 lanes with the same lines have the same ground (279,000 m2, 2 m2 apart). The `wasm32` build works. **Open:** duckOSM's files are Zstandard, and the C library does not build for the browser (`zstd` is native-only in `Cargo.toml`): in the browser the reader needs Snappy files from duckOSM, or a pure-Rust decoder. The chain does not use the reader yet: the blocks, the corridors and the crossings still come from the fixture. **Next readers:** the blocks input (SimReady's lanes and junctions, OSM's paths), the ground, the paths and the objects.

**Second reader, 2026-11-10: the blocks input and the area.** `urbanstyle_geo::utm` projects longitude and latitude to UTM (the series of Karney, millimetres over a zone): the 402 corners of Monaco's boundary (`boundary_main.parquet`, read by `urbanstyle_simready::boundary`) are 4 nm from the PROJ result of the Python code. `urbanstyle_simready::blocks::read` gives the face, the lanes of the streets and of the drives, the junction areas and the street lines. The test `tests/blocks_read.rs` against the blocks fixture: 1,430 street lines and the same 757 ways; lanes 2,413 (2,414), drives 526 (529), junctions 596 (595); the face is 0.25% smaller (792,957 m2, 794,907 m2). The files are of a later SimReady build than the fixture, which explains the small differences. Not read yet: the paths of the blocks step (OSM's footways: `work.element` and the way tags), the crossings of the division, and every input of the other steps.

**Third reader, 2026-11-10: OSM's pedestrian ways and nodes.** `urbanstyle_simready::osm` reads duckOSM's `raw_ways.parquet` (tags, line as WKB) and `raw_nodes.parquet` in UTM (0.13 s for Monaco). Against the fixtures: the 376 crossing ways are the same ways; the 770 crossing nodes are the same nodes, 4 nm apart; of the 1,984 paths of the blocks step, 1,734 are read the same, 44 real ways are extra and 1 is missing. 249 paths are duckOSM's virtual walking edges (a negative id, the way of the same id without the minus, through an open pedestrian area). The pass-0 folder holds only the driving graph, so those cannot be read. **Needed from duckOSM:** the walking graph as a Parquet file (`edges_walking.parquet`, with the virtual edges), as `edges_driving.parquet` is; it is another session's project, so this note records the need only. The rules for a walking way (`osm::walking`, `level`) are written from the Python SQL (`container.ROADS`): a footpath's highway value, not a driving way, not a parking aisle or a driveway, the level from `layer`, `bridge`, `tunnel`.

**Readers in the chain, 2026-11-10.** `urbanstyle-build DIR PREFIX OUT --simready DIR --pass0 DIR` makes the blocks input and the division input from the tables; the other steps still read their fixtures. The chain runs to the end. Monaco, with checks, against the fixture run: spaces 3,000 (3,124), parts 12,651 (13,231), ground rows 1,377 (1,534), surfaces 12,463 (12,630); the checks are close (U1 92 against 95, W2 148 against 137, K2 3,172 against 3,162). The differences come from the 249 virtual walking edges that the paths lack (path sections 999 against 1,092, path ground rows 670 against 769) and from the later SimReady build (roadway surfaces 1,779 against 1,747: lane width 3.5 m). The step "read the tables" takes 0.78 s; "read the JSON files" took 2.4 s for the inputs of the blocks and the division and the rest.

**Readers for the elements, ground, layers and objects, 2026-11-10.** `rust/tools/export_features_parquet.py` dumps duckOSM's `features.*` tables to `features-<name>.parquet` (a stand-in: duckOSM should write them). `urbanstyle_simready::features` makes the buildings (4,147, same ids and area), the points (666) and the lots (37) of the `element` step; `ground::read` the kinds of OSM ground (water 155, squares 17, bridges 5, green 106 and 158, car parks 37, construction sites 11, driveways 61: counts and areas the same, the driveways 0.9% larger because `geo` approximates the arcs of a round join more coarsely than shapely) and the lines (2,167 roads against 2,169; the walking lines are whole ways, 2,421, against 5,015 edges in the Python); `features::surface_layers` the verges (111), gardens (149), play land (59) and sites (11); `osm::object_nodes` the 4,462 object nodes. All with the same areas and tags. With `--features DIR` the chain reads all of them. Monaco, whole chain, with checks, nothing from Python but the paths, model and check inputs: 3,000 spaces, 1,373 ground rows, 12,400 surfaces, 76 s on the busy machine. **Still from the JSON fixtures:** the input of the paths step, of the model (the named streets and arms, `work.street` and `work.arm`) and of the checks.

**Model inputs from the tables, 2026-11-10.** The places of the junction nodes (`osm::node_points`, from the driving edges), the `width` tags of the ways (`osm::way_widths`) and the roundabout lines (`osm::roundabouts`) come from duckOSM's files. The chain then gives 3,018 spaces (52 roundabout stretches, 53 ring sectors: the pass-0 build has two roundabouts in the area more than the database of the Python reference). **Monaco, whole chain, with checks, 53 s** on a calmer machine (blocks 3.4, division 5.3, ground 11.7, surfaces 6.1, model 6.1, checks 14.3, tables 3.1, read the tables 0.3; the JSON fixtures that are still read cost 1.3 s). **Still from fixtures:** `work.street` and `work.arm` (`way_street`, `name_street`), the input of the paths step (the walking graph with the node numbers of its edges) and the roads of the checks (the same graph).

**Next:** readers of SimReady's tables (Parquet or Arrow) in place of the JSON fixtures; the ground, the checks and the blocks to get under 60 s in the
browser; W2 on snapped spaces; the old SQL tables for the named streets and arms (`work.street`, `work.arm`: still read from the fixture).
