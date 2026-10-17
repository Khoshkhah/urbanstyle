# Ranks 5 and 6: the parts and the marks

<p class="lead">Each side of a space is covered exactly by its parts: lanes, strips, the paved rest, the junction area, the crosswalks
and the islands on the driving side; the furnishing zone, the sidewalk, the frontage and the driveways on the walking side. The marks
lie on the parts: the kerb line, the painted lines, the zebras, the arrows and the guide lines.</p>

## Reads

The two sides of each space. OSM's lanes, turn lanes, parking lanes, cycle lanes, crossings and crossing markings. A city's meters,
bikeways and survey. SUMO's lane-to-lane moves through each intersection.

## The parts of the driving side

| Part | What it is | Where it comes from |
|---|---|---|
| `lane` | one traffic lane: `forward` or `backward` along a subsection, `in` or `out` of an intersection; lane 1 is at the middle of the road | OSM's count; each lane 3.25 m (chosen) or OSM's width shared, narrowed where the room is less |
| `paved` | the paved rest of the frame where no lane or strip is; also a strip narrower than 8 m between two roadways with nothing mapped on it | the frame less the lanes and the strips |
| `parking`, `no parking`, `shoulder`, `bus lane`, `cycle lane` | a strip beside the lanes | only where OSM or a city maps it: `parking:*`, the city's meters where they stand, `cycleway*`, a bus lane tag; a strip of unknown use is a shoulder |
| `junction area` | the roadway of an intersection where the arms' roadways meet, with the turning corners and the connectors | the arms' roadways joined |
| `crosswalk`, `cycle crossing` | the roadway under a crossing way, 3 m wide or OSM's width; a crossing node with no crossing way gets a band across its road | OSM's crossings that run across the road (30° or more to the road's line, or at most 40 m over a junction area); the lanes and the junction area give way to them; a crossing is one object in one space |
| `island` | a piece of the walking side between two roadways that touches no block; a roundabout's central island | the rule of rank 4 |
| `bridge deck` | the band of a way that a bridge profile models | the bridge model draws its lanes |

Each part of a road also carries what is known of its road from OSM: `road`, `road_class`, `speed`, `surface`, `lit`, `road_lanes`,
`oneway`. A value OSM lacks is urbanstyle's chosen one and says so.

## The parts of the walking side

| Part | What it is | Where it comes from |
|---|---|---|
| `sidewalk` | the clear path | the strip of OSM's sidewalk line (2 m or OSM's width); where no line is mapped, a 1.8 m band from the kerb after the furnishing zone |
| `furnishing` | the zone between the kerb and the sidewalk, where trees, poles and furniture stand | measured where OSM maps the line; 1 m (chosen) where not |
| `frontage` | the rest, from the sidewalk to the block's edge | the walking side less the other parts |
| `driveway` | the apron where a service road crosses the walking side to the roadway, kerb lowered | the service road's line at OSM's width, else 5 m |
| `island` | see the driving side; a piece of the walking side that touches no block and touches an island is that island's, across spaces | |
| `bus stop`, `bus zone` | a stop's waiting area on the sidewalk and the kerb strip where its bus stops | OSM's stops tied to the timetable (GTFS) by stop number |
| `tree pit` | a street tree's pit, 1.5 m square, inside the furnishing zone | the tree of a city's survey or OSM |

A median barrier continued from a bridge landing runs along the landing way's lanes on the ground until the opposite roadway ends or
a junction begins; its strip is an island.

## The parts of a path

A path's space has the walking side only. Its parts are the path's surface and what OSM maps on it: `steps`, `ramp`, `handrail`,
`bollard`. A path has no marks.

## Widths and sizes

Every part has `width_m` and `length_m` with `width_source` and `width_method`: a lane's width `osm, mapped` or `urbanstyle,
chosen` or `narrowed`; a strip's `urbanstyle, derived`; a crosswalk's, a tree pit's or a driveway's `urbanstyle, chosen` unless OSM
maps a width; any other part's `urbanstyle, derived` from its shape. Parts lose what is thinner than 4 cm.

![The parts at Sainte-Dévote.](../img/steps/07-parts.png){ width=100% }

*The parts: the driving side in grey, the junction areas in orange, the walking side in greens.*

## The marks

| Mark | Where | Width |
|---|---|---|
| `kerb` | the border of the driving side: one line per level, cut to each space, dropped over 2.5 m on each side of a driveway's mouth | 0.25 m, 0.2 m high in 3D |
| `lane line` | between two lanes of one direction, only between lanes OSM counts | 0.12 m |
| `centre line` | between the two directions, also where the count is chosen | 0.12 m |
| `edge line` | at the outer edge of a run of lanes beside a parking or cycle strip | 0.12 m |
| `parking line` | at the chosen lane's edge inside an outer lane that holds parking | 0.12 m, dashed |
| `stop line`, `give-way line` | across an arm's lanes where they enter a junction, where a stop or give-way sign or a signal stands on the arm; every roundabout entry gives way; never on a crosswalk | 0.4 m, 0.35 m |
| `zebra`, `crossing line` | the paint of a crosswalk from `crossing:markings`: zebra bars (also `marked`, `uncontrolled`, `yes`), two crossing lines (`lines`, `dashes`, `dots`), both for `ladder`, none for `unmarked` or `no` | 0.5 m bars, 0.15 m lines |
| `arrow` | a straight arrow in the middle of each lane 20 m or longer; before the stop line, a turn arrow with one head per way the lane may go | 0.15 m |
| `guide line` | SUMO's path through the junction for each move, from an in-lane to an out-lane | 0.1 m |
| `barrier` | a guardrail continued from a bridge | 0.3 m |

A lane line carries the lane count's source. No source maps a painted line: a line is `derived` from the count where OSM maps the
count, and urbanstyle's own, `chosen`, where the count is chosen.

![The marks at Sainte-Dévote.](../img/steps/08-marks.png){ width=100% }

*The marks: lane, centre, stop and give-way lines, the zebras, the arrows and the guide lines through the junctions.*

## The turns

SUMO's netconvert runs on duckOSM's driving network with the subsections' lanes. Each lane-to-lane move through an intersection is
a row of `space.turn`: the from-edge and lane, the to-edge and lane, the turn (left, straight, right), the vehicles it is open to and
the time rule that binds it, from duckOSM's turn permissions and restrictions. U-turns are left out. The turn arrows show the moves
open to all traffic. Each lane that comes into a junction is a row of `space.approach`: its moves, the ways it may go, its arrow or why
it has none.

## Writes

`space.part`: one row per part with its side, its type, its width and its sources. `space.mark`: one row per mark with its part.
`space.turn` and `space.approach`: the moves and the lanes that come into each intersection ([The tables](tables.md)).

## Checks

| Check | Tests |
|---|---|
| U8 | the parts of a space cover it |
| U9 | the parts of a space do not overlap by more than 0.05 m² |
| A2 | no parking lane or cycle lane without a real source |
| A3 | every road line at level 0 lies on a roadway (a stretch over 2 m with none fails) |
| X1 | a crossing way over the roadway has crosswalk parts on at least 80 % of its stretch |
| M1 | no lane line where the lane count is chosen |
| R2 | guide lines stay inside the roadway (0.5 m) |
| R4 (INFO) | the lanes that meet no continuation at a joint |
| U11 to U13 (INFO) | lanes with no move, approaches with no straight move at a four-arm junction, lanes with a move but no arrow |
| K2 (INFO) | a kerb line that ends where no other kerb and no crosswalk is |
