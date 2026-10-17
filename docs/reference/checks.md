# Checks

This page lists every data check that `urbanstyle check` runs, as `src/urbanstyle/checks.py` and `src/urbanstyle/bridge3d.py` define them. For each check, it gives the id, what the check counts and the check type.

## How a check reports

Each check counts the items that break one rule. `urbanstyle check` prints one line for each check: id, status, count and description.

| Type | Count 0 | Count more than 0 |
|---|---|---|
| Fault | `PASS` | `FAIL` |
| Informative | `PASS` | `INFO` |

The exit code is 1 if one or more fault checks fail, else 0. Informative checks never change the exit code.

The database checks measure in meters, in the UTM zone of the mean longitude. Before an overlap check, each shape shrinks by 0.01 m. A check group runs only when its tables exist.

| Group | Command | Code | Runs when |
|---|---|---|---|
| [Containers](#containers) | `urbanstyle check DB` | `checks.run` | always |
| [Strips](#strips) | `urbanstyle check DB` | `checks.run` | always |
| [Spaces](#spaces) | `urbanstyle check DB` | `checks.unit_checks`, `checks.part_checks` | `urban.unit` exists (U8, U9: `urban.part` also exists) |
| [Roadway](#roadway) | `urbanstyle check DB` | `checks.part_checks`, `checks.roadway_mismatch`, `checks.roadway_joints`, `checks.lane_joints` | `urban.unit` and `urban.part` exist |
| [Approaches](#approaches) | `urbanstyle check DB` | `checks.approach_checks` | `urban.unit`, `urban.part` and `urban.approach` exist |
| [Ground](#ground) | `urbanstyle check DB` | `checks.ground_checks` | the roadway checks run and `urban.ground` exists |
| [Surfaces](#surfaces) | `urbanstyle check DB` | `checks.surface_checks` | the ground checks run and `urban.surface` exists |
| [Blocks](#blocks) | `urbanstyle check DB` | `checks.block_checks` | the ground checks run and `urban.block` exists |
| [Bridge](#bridge) | `urbanstyle check DB --bridge PROFILE` | `bridge3d.model_checks`, called by `checks.bridge` | a profile is given with `--bridge` |

## Containers

These checks test the containers in `urban.container` and their arms in `urban.arm`.

| Id | What it counts | Type |
|---|---|---|
| P1 | Pairs of containers on one level that overlap by more than 0.5 m2. | Fault |
| P3 | Containers that are invalid, empty or smaller than 1 m2. | Fault |
| P4 | Containers with more than one part. | Fault |
| P5 | Elements (not buildings) with no container, or with a container id that does not exist. | Fault |
| P6 | Containers with a kind that is not in `KINDS`: `section`, `intersection`, `path`, `rail`, `plaza`. | Fault |
| P7 | Container ids that occur more than one time. | Fault |
| S1 | Sections with no road (`n_road = 0`) or no `street_id`. | Fault |
| S2 | Sections that meet more than two intersections. | Fault |
| I1 | Intersections with fewer than 3 arms. | Fault |
| I2 | Intersections where all arms have one `street_id`. A loop road is the one correct case. | Informative |
| I3 | Intersections with an area of less than 30 m2 or more than 10,000 m2. | Fault |
| I4 | Arm nodes more than 3 m from their intersection. | Informative |

## Strips

This check tests the strips in `urban.strip`.

| Id | What it counts | Type |
|---|---|---|
| C2 | Sections and intersections whose strips do not add up to their area, within 3% or 1.5 m2. | Fault |

## Spaces

These checks test the network-first spaces in `urban.unit` and their parts in `urban.part`.

| Id | What it counts | Type |
|---|---|---|
| U1 | Pairs of spaces on one level that overlap by more than 0.5 m2. | Fault |
| U2 | Spaces that are invalid, empty or in more than one part. | Fault |
| U3 | Junctions in `urban.junction` whose intersection has no space. | Fault |
| U4 | Junction nodes more than 0.5 m outside their own intersection space. | Fault |
| U5 | Junction nodes inside a subsection space on the same level. | Fault |
| U6 | Subsection lines that go more than 1 m into an intersection or roundabout space. | Fault |
| U7 | Subsections in `urban.subsection` with no space. | Fault |
| U8 | Spaces whose parts do not add up to the space area, within 3% or 1.5 m2. | Fault |
| U9 | Pairs of parts of one space that overlap by more than 0.5 m2. | Fault |

## Roadway

These checks test the roadway parts in `urban.part` and the marks in `urban.mark`, mostly at level 0.

| Id | What it counts | Type |
|---|---|---|
| U10 | Cuts in `urban.cut` where the roadway width on the intersection side and on the subsection side differ by more than 0.5 m. | Informative |
| R1 | Joints between two subsections of one section where the roadway edges differ by more than 0.1 m. | Informative |
| R2 | Guide lines (SUMO moves) at level 0 that go more than 0.5 m out of the roadway. | Informative |
| R3 | Subsections with an OSM lane at level 0 narrower than 2.75 m. The OSM lane count does not fit between the kerbs. | Informative |
| R4 | Edges between lanes, cycle lanes, parking and bus zones at a subsection joint, with no matching edge on the other side. | Informative |

R4 samples each joint every 0.1 m, 0.3 m into each side. An edge matches when the other side has an edge within two samples (0.2 m). A taper has zero width at the joint, so it has no edge there.

## Approaches

These checks test the lanes that enter each junction, in `urban.approach`. A missing move can be correct, for example a turn restriction or a T junction.

| Id | What it counts | Type |
|---|---|---|
| U11 | Lanes that enter a junction with no move. | Informative |
| U12 | Approaches with no straight move for all traffic, at intersections with 4 or more approaches. | Informative |
| U13 | Lanes with a move for all traffic but no turn arrow, because the lane piece is under 4 m or another arrow is in the way. | Informative |

## Ground

These checks test layer 0, the ground items in `urban.ground`.

| Id | What it counts | Type |
|---|---|---|
| G1 | Ground items of type `unknown`. The line also gives their total area. | Informative |
| G2 | Pairs of ground items on one level that overlap by more than 0.5 m2. | Fault |

## Surfaces

These checks test layer 1, the surfaces in `urban.surface`.

| Id | What it counts | Type |
|---|---|---|
| L1 | Ground items whose surfaces do not cover them, within 3% or 1.5 m2. | Fault |
| L2 | Pairs of surfaces of one ground item that overlap by more than 0.5 m2. | Fault |

## Blocks

These checks test the blocks in `urban.block`, inside the area edge in `urban.area`.

| Id | What it counts | Type |
|---|---|---|
| B1 | Buildings at level 0 that go more than 1 m2 over the edge of a block. The line also gives the total area outside. | Informative |
| B6 | City blocks in `urban.city_block` that one of our blocks matches, with an overlap (intersection over union) of 0.8 or more. | Informative |

B6 runs only when `urban.city_block` has rows. It uses only the city blocks with more than 50 m2 inside the area. The line also gives the number of city blocks and the median overlap. B6 counts matches, not faults.

## Bridge

These checks test the 3D model of a bridge profile, as the dashboard page draws it. They measure in meters, in the CRS of the profile. The lanes at level 0 of the first `DB`, within 50 m of the deck, give the landings.

| Id | What it counts | Constant | Type |
|---|---|---|---|
| BR1 | Guard pieces (barrier or railing) more than 0.5 m inside a lane. | `GUARD_ON_LANE_M` | Fault |
| BR2 | Holes in the deck. | | Fault |
| BR3 | Stretches of the deck edge longer than 1 m with no barrier, not at a road end on the ground. | | Fault |
| BR4 | Pairs of paths (sidewalks or cycle lanes) that overlap by more than 0.1 m2. | | Fault |
| BR5 | Path pieces narrower than 0.5 m. | `PATH_MIN_M` | Fault |
| BR6 | Pairs of lanes of two different axes that overlap by more than 1 m2. | | Fault |
| BR7 | Lanes with no arrow mark. | | Fault |
| BR8 | Steps of more than 1 m in the deck width where a landing starts. | | Fault |
| BR9 | Pieces of deck larger than 0.5 m2 that no part covers. | `FREE_CHECK_M2` | Fault |
| BR10 | Stretches longer than 1.5 m where a lane meets a path with no barrier, not at a crosswalk. | `BAR_CHECK_M` | Fault |
| BR11 | Steps of more than 0.2 m in the deck height between two points 0.5 m apart. | `HEIGHT_STEP_M`, `STEP_CHECK_M` | Fault |

For each bridge check with a count more than 0, `urbanstyle check` also prints up to five `?at=x,y,20,60,0` lines. Each line opens the dashboard page at that point in 3D.
