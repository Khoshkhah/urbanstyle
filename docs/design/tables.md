# The tables

<p class="lead">One table per rank, and the tables that lie on the tree. Every row names its parent in the rank above, and the rows
of one parent partition it. Every row that holds a value names the value's source and method.</p>

All tables are in the `urban` schema of an area's DuckDB file. Geometry is stored in lon/lat (EPSG:4326); the build measures in the
area's UTM zone. `level` is the integer level, -2 to 2. The columns `source`, `method` and `ref` say who gave a row, how they got it
and which of their items it is ([Sources and provenance](sources.md)).

## The common columns

Every rank table has the same columns in the same order. The thing's own values stand between `name` and `source`.

| Column | Meaning |
|---|---|
| `<thing>_id` | the readable id of the thing ([The ids](model.md#the-ids)) |
| `kind` | what the thing is, one word from the rank's list |
| `rank` | the rank, 0 to 6 |
| `parent_id` | the id of the thing of the rank above that holds it; the area for rank 1 |
| `level` | the level |
| `name` | the thing's name, from its source, or none |
| the thing's values | its widths, its lengths, its lanes, with `<value>_source` and `<value>_method` where a value has its own source |
| `source`, `method`, `ref` | who gave the row, how, and which of their items it is |
| `geometry` | the thing: one polygon for a thing of rank 1 to 5, a line or a shape for a mark |

Each `<thing>_id` is unique in its table; an intersection is a stretch and a space, so `urban.item`'s key is the id with the rank.
A column that ends in `_m` is in metres, `_m2` in square metres. A thing with a profile in the registry has one more column, `uid`,
its stable id ([The registry](#the-registry-urbanregistry)).

## Rank 0

### `urban.area`

The whole area of a level: one row per level.

| Column | Meaning |
|---|---|
| `area_id` | `a<level>` |
| `kind` | area |
| `rank` | 0 |
| `parent_id` | none |
| `level` | the level |
| `name` | the area's name |
| `source`, `method`, `ref` | the clip's box, chosen; or OSM's boundary, mapped |
| `geometry` | the area, one polygon |

### `urban.element`

The elements duckOSM gives: one row per road, walkway, cycleway or rail piece, and per building or car park. The elements are the
input of the build, not a rank: they keep duckOSM's columns.

| Column | Meaning |
|---|---|
| `element_id` | `w<way>` for a piece of a way; `b<id>` for a building |
| `kind` | road, walkway, cycleway, rail, building, lot |
| `class`, `subtype` | OSM's `highway` or `railway` value; `footway=*` or `service=*` |
| `name`, `osm_id`, `source_id` | the name; the OSM way; the source's own id |
| `uid` | a building's stable id, from the registry |
| `oneway`, `lanes_forward`, `lanes_backward`, `width_m`, `width_src` | from OSM's tags; where the width comes from |
| `level_min`, `level_max`, `level_src` | the level span and where it comes from (layer, bridge, tunnel, chosen) |
| `floors`, `height_m`, `use`, `ground_use`, with their sources and methods | a building's floors, height and use |
| `geometry` | the line, or the footprint |

## Rank 1

### `urban.ground`

Every piece of the area of a level is one row: the street, a plot or a path. The three partition the area (checks G1 to G3).

| Column | Meaning |
|---|---|
| `ground_id` | `g<level>-street-<n>`, `g<level>-plot-<block>`, `g<level>-path-<corridor>` |
| `kind` | street, plot, path |
| `rank` | 1 |
| `parent_id` | the area |
| `level` | the level |
| `name` | a street's name; a path's name |
| `sides` | a plot: its street sides, each with the way, the distance from the road line and what set it (sidewalks, carriageway, path width, building) |
| `width_m`, `width_source`, `width_method` | a path: OSM's width or the chosen one |
| `source`, `method`, `ref` | urbanstyle, derived: the area less the blocks and the corridors; the block or the corridor it is |
| `geometry` | the item, one polygon |

## Rank 2

### `urban.stretch`

A stretch of the street or of a path: a section, an intersection, a path section, a path intersection.

| Column | Meaning |
|---|---|
| `stretch_id` | `s<level>-w<way>` (a second chain `.2`), `i<level>-<node>`, `p<level>-w<way>`, `q<level>-<node>` |
| `kind` | section, intersection, path section, path intersection |
| `rank` | 2 |
| `parent_id` | the street or the path of rank 1 |
| `level` | the level |
| `name` | the name of the ways |
| `street_id` | the named street a section belongs to |
| `ways` | the OSM ways, in order |
| `nodes` | the junction nodes: the two ends of a section, the cluster of an intersection |
| `class`, `oneway`, `length_m` | from the ways |
| `axis` | a section's line, its ways chained, from its start node to its end node |
| `source`, `method`, `ref` | OSM, mapped, the ways; the cut by the stop lines is urbanstyle's, derived |
| `geometry` | the stretch's face of the street, cut by the stop lines; its spaces partition it |

### `urban.plot_piece`

A piece of a plot, inside its block. The pieces of one block partition it.

| Column | Meaning |
|---|---|
| `piece_id` | `g<level>-<kind>-<ref>` |
| `kind` | building, yard, alley, car park, construction site, green, water, rail, square, structure |
| `rank` | 2 |
| `parent_id` | the plot |
| `level` | the level |
| `name` | from the source |
| `width_m`, `width_source`, `width_method` | an alley's width |
| `surfaces` | the surfaces that cover it (`urban.surface`) |
| `source`, `method`, `ref` | OSM, mapped, the way; urbanstyle, derived, for a yard or an alley |
| `geometry` | the piece, one polygon |

### `urban.joint`

One row per joint of a section, where OSM's tags change, with its class.

| Column | Meaning |
|---|---|
| `section_id`, `subsection_a`, `subsection_b` | the section and the two subsections that meet |
| `way_a`, `way_b`, `lanes_a`, `lanes_b`, `width_a`, `width_b` | the two ways and their lanes and widths |
| `class` | turn pocket, merge, fork, parking, island, real, room, unknown, none |
| `note` | the evidence |
| `geometry` | the joint |

### `urban.street` and `urban.arm`

The named street, a group of stretches, and the arms that link an intersection to its named streets.

| Table | Columns |
|---|---|
| `urban.street` | `street_id` (`k<level>-<way>`), `name`, `level`, `sections`, `intersections`, `geometry` |
| `urban.arm` | `intersection_id`, `street_id`, `section_id`, `way` |

## Rank 3

### `urban.space`

One space per subsection, per intersection, per path section and per path intersection.

| Column | Meaning |
|---|---|
| `space_id` | `s<level>-w<way>/<k>`, `i<level>-<node>`, `p<level>-w<way>`, `q<level>-<node>` |
| `kind` | subsection, intersection, path section, path intersection |
| `rank` | 3 |
| `parent_id` | its stretch |
| `level` | the level |
| `name` | the stretch's name |
| `axis` | a subsection's line: the piece of its section's axis, from `s_from` to `s_to` |
| `s_from`, `s_to` | where the space lies along its section's axis, in metres from the section's start |
| `width_m`, `oneway`, `length_m`, `left_extra` | the frame's width; one-way; the length; the merge shift |
| `predecessors`, `successors` | the spaces before and after it along the street: a subsection's neighbours, or the intersection at its end; an intersection's: the subsections at its arms |
| `source`, `method`, `ref` | the ways, mapped; the cut by the joints is urbanstyle's, derived |
| `geometry` | the space, one polygon |

### `urban.junction`

The junction nodes of each intersection.

| Column | Meaning |
|---|---|
| `intersection_id`, `node_id`, `level`, `cluster_id` | |

## Rank 4

### `urban.side`

The two sides of a space. They partition the space (check S1). An island is a part of the walking side, not a side.

| Column | Meaning |
|---|---|
| `side_id` | `<space>:d`, `<space>:w` |
| `kind` | driving, walking |
| `rank` | 4 |
| `parent_id` | its space |
| `level` | the level |
| `name` | none |
| `kerb` | the driving side: the line of its kerb, with `kerb_source` and `kerb_method` (OSM's sidewalk line, measured; the lanes' edge, derived) |
| `source`, `method`, `ref` | what set the kerb |
| `geometry` | the side, one polygon |

## Rank 5

### `urban.part`

A piece of a side, of one kind.

| Column | Meaning |
|---|---|
| `part_id` | `<space>#<n>` |
| `kind` | lane, paved, parking, no parking, shoulder, bus lane, cycle lane, junction area, crosswalk, cycle crossing, bridge deck, island, sidewalk, furnishing, frontage, driveway, bus stop, bus zone, tree pit; a path's surface, steps, ramp, handrail, bollard |
| `rank` | 5 |
| `parent_id` | its side |
| `level` | the level |
| `name` | none |
| `space_id` | its space |
| `arm`, `direction`, `lane`, `lane_id` | a lane's road, direction (forward, backward, in, out), number from the middle, GMNS id |
| `axis` | a lane's or a band's middle line, in the direction of travel; none for a junction area or a crosswalk |
| `s_from`, `s_to`, `t_from`, `t_to` | where the part lies on its space's axis: along, and across |
| `predecessors`, `successors` | a lane: the lanes that continue it in the spaces before and after; through an intersection, the lanes its turns reach |
| `width_m`, `length_m`, `width_source`, `width_method` | its width and length, and where the width comes from |
| `position_source`, `position_method`, `position_ref` | what set its edge |
| `road`, `road_class`, `speed`, `surface`, `lit`, `road_lanes`, `oneway` | what is known of the road a lane belongs to |
| `holds`, `rule` | what stands in it; the rules that apply (parking rates and hours, a timetable) |
| `source`, `method`, `ref` | where the part comes from |
| `geometry` | the part, one polygon |

## Rank 6

### `urban.mark`

A painted line, an arrow, a zebra or the kerb line, on a part.

| Column | Meaning |
|---|---|
| `mark_id` | `<space>:<kind>:<n>` |
| `kind` | kerb, lane line, centre line, edge line, parking line, stop line, give-way line, zebra, crossing line, arrow, guide line, barrier |
| `rank` | 6 |
| `parent_id`, `parent_rank` | the part it lies on (rank 5), or, for the kerb line, the driving side whose border it is (rank 4) |
| `level` | the level |
| `name` | none |
| `space_id` | its space |
| `s_from`, `s_to`, `t_from`, `t_to` | where the mark lies on its space's axis |
| `width_m`, `width_source`, `width_method`, `length_m` | the mark's width and length |
| `source`, `method`, `ref` | where it comes from |
| `geometry` | its middle line, or its shape |

### `urban.turn` and `urban.approach`

The lane-to-lane moves through each intersection and the lanes that come into it.

| Table | Columns |
|---|---|
| `urban.turn` | `space_id`, `from_edge`, `from_lane`, `to_edge`, `to_lane`, `turn` (left, straight, right), `vehicles`, `condition`, `source`, `geometry` |
| `urban.approach` | `space_id`, `level`, `from_edge`, `lane`, `moves`, `ways`, `arrow`, `no_arrow_because` |

## The axes and (s, t)

Every linear thing has an `axis`: its middle line, from its start to its end. A section's axis is its ways chained. A subsection's
axis is the piece of the section's axis it covers. A lane's axis runs in its direction of travel. A thing's place on its parent's
axis is `(s, t)`: `s` in metres along the axis from its start, `t` in metres across it, positive to the left ([The format](format.md),
R4). `s_from` and `s_to` give the range along, `t_from` and `t_to` the range across. A part's `t` is measured from its space's
axis, so the lanes of one space are ordered by `t_from`.

## The view over the tree: `urban.item`

One view over every rank: `id`, `rank`, `kind`, `parent_id`, `level`, `geometry`. A query over the tree joins the view to itself on
`parent_id`. The view holds the area, the ground, the stretches and the plot pieces, the spaces, the sides, the parts and the marks.
The things on the tree (objects, links, stations) are not in it.

## The manifest: `urban.meta`

One row per fact about the build, so a database says what made it and from what.

| Column | Meaning |
|---|---|
| `key` | the name: `version`, `built`, `input.<name>`, `chosen.<module>.<NAME>` |
| `kind` | build, input, chosen |
| `value` | the value, as text |
| `note` | an input: its date; a chosen value: what it is for, in the words of the code |

The chosen values are every value no source gives, with the name the code uses, so a reader finds each one in the code and in the
notes ([Sources and provenance](sources.md), method `chosen`).

## The checks: `urban.check`

One row per check per build. `urbanstyle check` writes the rows and prints them ([Checks](../reference/checks.md)).

| Column | Meaning |
|---|---|
| `check_id` | the check's id, `U1`, `G2`, `BR12` |
| `kind` | fault, info |
| `status` | pass, fail, info |
| `count` | the number of faulty things |
| `what` | what the check counts |
| `items` | the faulty things: their ids, or where they are (lon, lat) when the check finds a place |
| `checked` | when the check ran |

## The registry: `urban.registry`

The stable ids of the format's requirement R6 ([The format](format.md)). Every thing with a profile, made only of facts that do not
change, has one id for as long as the profile lasts. The registry is kept from build to build: a build reads the registry of the
database it replaces, gives every profile it knows its id again, and gives a new profile a new id.

| Column | Meaning |
|---|---|
| `profile` | the profile, as text: `osm:n13983466896`, `vancouver:vb6509215` |
| `uid` | the id, a UUID |
| `kind` | what the thing is: street object, building, intersection, section, subsection, part, block |
| `first_seen` | the build that first had the profile |
| `last_seen` | the build that last had it |

The thing's own row carries the id in `uid`. The readable id (`s0-…`, `i0-…`, `n…`) stays as the label.

## The style: `urban.style`

One row per table and kind: how a viewer draws it. The levels are drawn from the lowest up; inside a level, the things are drawn in
`draw_order`, lowest first ([Drawing the tables](drawing.md)).

| Column | Meaning |
|---|---|
| `table`, `rank`, `kind` | the table, its rank, and the kind |
| `draw_order` | the place in the stack of one level: rank 0 at 0, rank 1 from 10, rank 2 from 20, and so on to the marks from 60; the street objects at 70, the links at 80 |
| `form` | polygon, line or point |
| `colour` | the fill of a polygon, the colour of a line or a point |
| `dash` | a dashed line: the metres drawn and the metres left out |
| `raise_m` | in 3D, the height of the kind's top above the ground of its level |

## The codes of the standards: `urban.code`

One row per kind of ours, with its code in each standard. An export reads this table; a reader of a standard finds our kind in it. Its columns: `kind`, `citygml`,
`opendrive`, `opensidewalks`, `ifc`; none where the standard has no code.

| Ours | CityGML 3.0 | OpenDRIVE | OpenSidewalks | IFC 4.3 |
|---|---|---|---|---|
| named street | `Road` | the roads of one name | none | `IfcRoad` |
| section, subsection | `Section` | a road, its lane sections | none | `IfcRoadPart`, `ROADSEGMENT` |
| intersection | `Intersection` | `junction` | the node | `IfcRoadPart`, `INTERSECTION` |
| lane | `TrafficSpace`, granularity `lane`; `TrafficArea` | lane, type `driving` | none | `TRAFFICLANE` |
| bus lane | `TrafficSpace`, usage bus | lane, type `bus` | none | `TRAFFICLANE` |
| cycle lane, cycle crossing | `TrafficSpace`, usage bicycle | lane, type `biking` | none | `TRAFFICLANE` |
| shoulder | `AuxiliaryTrafficSpace` | lane, type `shoulder` | none | `SHOULDER` |
| parking, no parking, bus zone | `AuxiliaryTrafficSpace` | lane, type `parking` | none | `PARKINGBAY` |
| paved, junction area | `TrafficSpace` | lane, type `driving` | none | `TRAFFICLANE` |
| island | `AuxiliaryTrafficSpace` | lane, type `median` | traffic island edge | `TRAFFICISLAND` |
| sidewalk, furnishing, frontage | `TrafficSpace`, function sidewalk | lane, type `walking` | sidewalk edge | `SIDEWALK` |
| driveway | `TrafficSpace`, function driveway | lane, type `walking` | sidewalk edge | `SIDEWALK` |
| crosswalk | `TrafficSpace`; `Marking` | `crossPath`; object `crosswalk` | crossing edge | `PEDESTRIAN_CROSSING` |
| bridge deck | `BridgePart` | object `bridge` | none | `IfcBridgePart`, `DECK` |
| kerb | `AuxiliaryTrafficArea` | lane, type `curb` | kerb node | `IfcKerb` |
| lane line, centre line, edge line, parking line | `Marking` | `roadMark` | none | `IfcSurfaceFeature` |
| stop line, give-way line, zebra, crossing line, arrow, guide line | `Marking` | `roadMark`; `object` | none | `IfcSurfaceFeature` |
| barrier | `AuxiliaryTrafficArea` | object `barrier` | none | `IfcRailing` |
| street object | `CityFurniture` | `object`, `signal` | point | `IfcSign`, `IfcSignal`, `IfcFurniture` |
| plot, plot piece, path | `LandUse` | none | none | none |
| building | `Building` | object `building` | building | `IfcBuilding` |
| level | `relativeToTerrain` | none | none | `VERTICAL` facility part |

## On the tree

### `urban.object`

What stands in the street: one row per real thing.

| Column | Meaning |
|---|---|
| `object_id` | `n<node>`, `w<way>`, or the source's own id |
| `kind` | `group.class` ([Street objects](objects.md)) |
| `uid` | its stable id, from the registry |
| `level`, `space_id`, `part_id` | where it stands; `near_m` when it stands outside every space |
| `name`, `attrs` | the name; a short set of attributes |
| `width_m`, `height_m`, with their sources and methods | its size |
| `sources`, `refs` | every source that describes it and its id in each |
| `source`, `method` | the best source and its method |
| `geometry` | the point |

### `urban.link`

A join between two levels at a node.

| Column | Meaning |
|---|---|
| `link_id`, `kind` (ramp, stairs, elevator, entrance, connection), `level_from`, `level_to`, `node`, `geometry` | |

### `urban.station`

A rail, subway or tram station with its level and its entrances.

### `urban.surface`

The surfaces that cover a ground item or a plot piece exactly: `surface_id` (`<item>:<kind>`), `ground_id`, `kind` (roadway,
pedestrian realm, median, verge, building, car park, construction site, garden, yard, lawn, play, path, track bed, under bridge,
paved, water), `source`, `method`, `ref`, `geometry` (checks L1, L2).

### `urban.observed` and `urban.photo`

Mapillary's detections and photo positions, kept local, for validation only.

## The bridge model

A bridge is not in the tables: it is a profile file, `<name>.bridge.json`, with the deck outline, the axes, the vertical profiles, the
sections, the bands and the piers, each value with its source and method ([Levels, bridges and tunnels](levels.md)). The server adds
`urban.bridge_part` in memory from the model, so the panel can find the model's lanes and paths.

## The pilot dossier

A pilot's dossier is its own database with the tables `unit`, `source`, `inventory`, `surface`, `line`, `object`, `match`, `lane`,
`movement`, `rule`, `observation` and `check` ([Sources and provenance](sources.md)).
