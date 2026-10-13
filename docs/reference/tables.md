# Tables

This page lists every table that `urbanstyle build` writes in the `space` schema of an area's DuckDB file. It also lists the two tables
that `urbanstyle serve` adds in memory.

The columns, the types and the row counts come from `data/units/broadway-granville.space.duckdb` (built 2026-10-12). To get them again,
open the file read-only, then run `DESCRIBE space.<table>` and `SELECT count(*) FROM space.<table>`. For the id formats, see [Ids](ids.md).

## Common columns

- `geometry` is in lon/lat (EPSG:4326). The build measures in UTM and converts each result back to lon/lat.
- `level` is the integer level of the city, from -2 to 2. Level 0 is the ground.
- A column that ends in `_m` is in metres. A column that ends in `_m2` is in square metres.

## Provenance columns

Most rows say who gave the data, how the source got it, and which item of the source it is. [Sources and methods](../design/provenance.md)
gives the rules that select a source.

| column | meaning |
|---|---|
| `source` | Who gave the data: `osm`, `vancouver`, `sumo`, `gtfs`, `mapillary` or `urbanstyle`. A `+` joins the sources of a row that uses more than one, for example `osm+vancouver`. `urbanstyle corrections (corrections/lanes.json)` marks a value from that corrections file. |
| `method` | How the source got the value (see the next table). |
| `ref` | The item in its own source (`w336755856`, `n6460776254`), or the items that urbanstyle made the row from. Some values are short text, for example `w336755856 lanes=2`. |

| `method` | meaning |
|---|---|
| `mapped` | Mappers drew it, or a register keeps it. |
| `measured` | urbanstyle measured it from mapped lines, for example a kerb from the OSM sidewalk lines. |
| `observed` | A photo shows it (Mapillary). |
| `derived` | urbanstyle calculated it from other data by a rule. |
| `chosen` | urbanstyle's own value for a type, where no source gives one. |

This file also holds two other `method` values. `approximate` (in `space.element.ground_method`) means that the source says its
positions are approximate. `corrected` (in `space.part` and `space.mark`) means a value from `corrections/lanes.json`.

Some columns give the provenance of one field only:

| columns | table | provenance of |
|---|---|---|
| `width_source`, `width_method` | `part`, `mark`, `path` | the width |
| `position_source`, `position_method`, `position_ref` | `part` | the position of the part's edge (the kerb, the block's edge) |
| `use_source`, `use_method` | `element` | the use of a building |
| `ground_source`, `ground_method` | `element` | the use of a building's ground floor |
| `level_src` | `element` | the level span, the floors and the height |
| `width_src` | `element` | the width of a road, a walkway or a cycleway, in words |
| `basis`, `method` | `block_side` | the distance from the road to the block's edge |

Three tables use their own words in `source`. `space.strip` uses `tag`, `measured` and `default`. `space.width` uses `urbanstyle` and
`measured one side`. `space.turn` uses `sumo`.

## All tables

| table | group | rows in Broadway × Granville |
|---|---|---|
| [`area`](#spacearea) | the area and its blocks | 1 |
| [`block`](#spaceblock) | the area and its blocks | 52 |
| [`block_side`](#spaceblock_side) | the area and its blocks | 217 |
| [`city_block`](#spacecity_block) | the area and its blocks | 79 |
| [`container`](#spacecontainer) | the street space | 405 |
| [`zone`](#spacezone) | the street space | 727 |
| [`boundary`](#spaceboundary) | the street space | 1236 |
| [`street`](#spacestreet) | the street space | 82 |
| [`arm`](#spacearm) | the street space | 476 |
| [`junction`](#spacejunction) | the street space | 218 |
| [`unit`](#spaceunit) | the street space | 186 |
| [`subsection`](#spacesubsection) | the street space | 145 |
| [`cut`](#spacecut) | the street space | 167 |
| [`part`](#spacepart) | the street space | 1834 |
| [`mark`](#spacemark) | the street space | 1941 |
| [`width`](#spacewidth) | the street space | 186 |
| [`turn`](#spaceturn) | the street space | 519 |
| [`approach`](#spaceapproach) | the street space | 255 |
| [`ground`](#spaceground) | the ground | 866 |
| [`surface`](#spacesurface) | the ground | 1387 |
| [`path`](#spacepath) | the ground | 404 |
| [`parcel`](#spaceparcel) | the ground | 958 |
| [`lot`](#spacelot) | the ground | 16 |
| [`element`](#spaceelement) | buildings and elements | 1977 |
| [`object`](#spaceobject) | objects | 1068 |
| [`observed`](#spaceobserved) | objects | 637 |
| [`photo`](#spacephoto) | objects | 4199 |
| [`strip`](#spacestrip) | objects | 3870 |
| [`link`](#spacelink) | levels | 15 |
| [`station`](#spacestation) | levels | 0 |

## The area and its blocks

`blocks.py` writes these tables. [Blocks first](../design/blocks.md) gives the design.

### space.area

One row: the edge of the area. It comes from the `boundary` table of the duckOSM database, else from the box around all elements. The
checks read it.

Key: none (one row).

| column | type | meaning |
|---|---|---|
| `geometry` | GEOMETRY | The edge of the area (polygon). |

### space.block

One row is one block: the land between the streets at level 0. A block is a face that the public streets enclose, less each street's half width.

Key: `block_id`. Provenance: `source`, `method` (see [Provenance columns](#provenance-columns)).

| column | type | meaning |
|---|---|---|
| `block_id` | VARCHAR | The block's id, `b<level>-w<way><side>`. |
| `level` | INTEGER | Always 0. |
| `area_m2` | DOUBLE | The block's area. |
| `source` | VARCHAR | `urbanstyle` in this file. |
| `method` | VARCHAR | `derived` in this file. |
| `geometry` | GEOMETRY | The block's outline (polygon). |

### space.block_side

One row is one street side of one block. Each side gets one distance from the road line, so the block's edge runs parallel to the road.

Key: none. A block can have two sides on one way. Provenance: `basis`, `method` (see [Provenance columns](#provenance-columns)).

| column | type | meaning |
|---|---|---|
| `block_id` | VARCHAR | The block (`space.block`). |
| `way_id` | BIGINT | The smallest OSM way id along this street side. |
| `name` | VARCHAR | The street's name. |
| `class` | VARCHAR | The street's OSM `highway` class. |
| `distance_m` | DOUBLE | The distance from the road line to the block's edge. |
| `basis` | VARCHAR | What set the distance: `parcels (joined)`, `parcel`, `sidewalks`, `class` or `building`. |
| `method` | VARCHAR | How the distance was found. `measured` for all rows in this file. |
| `unpulled_m` | DOUBLE | The distance before a building or a parcel pulled the edge in. NULL where nothing pulled it. |
| `building` | VARCHAR | The building or the parcel that pulled the edge in, for example `vancouver:pl015234321`. |

### space.city_block

One row is one block outline from the city's open data (Vancouver `block-outlines`). Check B6 compares these with `space.block`. The
build does not use them as input.

Key: `city_block_id`.

| column | type | meaning |
|---|---|---|
| `city_block_id` | VARCHAR | The id, `cb<lon><lat>` from the block's centre point. |
| `geometry` | GEOMETRY | The city's block outline (polygon). |

## The street space

`container.py` writes `container`, `zone`, `boundary`, `street` and `arm`. `subsections.py`, `spaces.py` and `parts.py` write the other
tables of this group. At level 0, `division.py` then replaces the rows of `unit`, `subsection`, `cut`, `junction`, `part`, `mark`,
`width`, `turn` and `approach`. In this file, `unit`, `subsection`, `part`, `mark` and `width` hold rows at levels 0 and 1 only.

### space.container

One row is one container: a piece of the street space at one level that no other container overlaps. Its `kind` is `section`,
`intersection`, `path`, `plaza` or `rail`. This file has 217 sections, 104 intersections, 64 path spaces and 20 plazas, at levels -1,
0 and 1. It has no rail space.

Key: `container_id`.

| column | type | meaning |
|---|---|---|
| `container_id` | VARCHAR | The container's id. |
| `level` | INTEGER | The level. |
| `kind` | VARCHAR | `section`, `intersection`, `path`, `plaza` or `rail`. |
| `street_id` | VARCHAR | The street group of a section (`space.street`). NULL for other kinds. |
| `shape` | VARCHAR | The shape of an intersection: `cross`, `T`, `Y`, `dogleg` or `multi`. NULL for other kinds. |
| `n_arms` | INTEGER | The number of arms of an intersection. |
| `n_buildings` | BIGINT | The number of buildings that bound the container (`space.boundary`). |
| `boundary_m` | DOUBLE | The total length of those building faces. |
| `n_dead_ends` | BIGINT | Section only: the nodes where only one road edge ends. |
| `n_intersections` | BIGINT | Section only: the intersections that the section arrives at. |
| `name` | VARCHAR | The most frequent road name. For an intersection, up to three road names joined by ` x `. |
| `n_road` | HUGEINT | The number of road elements in the container. |
| `n_walkway` | HUGEINT | The number of walkway elements. |
| `n_cycleway` | HUGEINT | The number of cycleway elements. |
| `n_rail` | HUGEINT | The number of rail elements. |
| `mean_width_m` | DOUBLE | The mean total width across the road's cross-sections. |
| `open_share` | DOUBLE | The share of road cross-sections with at least one open side (no building within the reach cap). |
| `narrow_half_m` | DOUBLE | The mean distance from the centerline to the nearer side. |
| `wide_half_m` | DOUBLE | The mean distance from the centerline to the farther side. |
| `one_side_open_share` | DOUBLE | The share of road cross-sections with exactly one open side. |
| `kerb_share` | DOUBLE | The share of road cross-sections where a sidewalk was found. |
| `geometry` | GEOMETRY | The container's outline (polygon or multipolygon). |

### space.zone

One row is one zone of one container: what that part of the container is for.

Key: `container_id`, `zone`.

| column | type | meaning |
|---|---|---|
| `container_id` | VARCHAR | The container (`space.container`). |
| `level` | INTEGER | The level. |
| `zone` | VARCHAR | `travelway`, `pedestrian_realm` or `track`. |
| `geometry` | GEOMETRY | The zone's area (polygon or multipolygon). |

### space.boundary

One row is one building that bounds one container. The building's face lies along the container's edge for at least 2 m.

Key: `container_id`, `building_id`.

| column | type | meaning |
|---|---|---|
| `container_id` | VARCHAR | The container (`space.container`). |
| `level` | INTEGER | The level. |
| `kind` | VARCHAR | What bounds the container. `building` for all rows. |
| `building_id` | VARCHAR | The building's `source_id` in `space.element`. |
| `length_m` | DOUBLE | The length of the building's face along the container's edge. |

### space.street

One row is one street group: the connected roads of one level that share a name. A street holds its sections and the intersections that
it arrives at.

Key: `street_id`.

| column | type | meaning |
|---|---|---|
| `street_id` | VARCHAR | The street's id, `k<level>-<way>`. |
| `level` | INTEGER | The level. |
| `name` | VARCHAR | The most frequent name of its sections. NULL for 56 streets with no name. |
| `n_section` | BIGINT | The number of its sections. |
| `n_intersection` | BIGINT | The number of intersections that it arrives at. |

### space.arm

One row is one road edge that arrives at an intersection. An arm links an intersection to a section and to a street group.

Key: none. One row per intersection, section, road edge and node.

| column | type | meaning |
|---|---|---|
| `intersection_id` | VARCHAR | The intersection container. |
| `section_id` | VARCHAR | The section container that arrives. |
| `street_id` | VARCHAR | The street group of that section. |
| `osm_id` | BIGINT | The OSM way of the road. |
| `edge_id` | VARCHAR | The duckOSM edge id of the road edge, as text. |
| `node_id` | BIGINT | The junction node where the edge arrives. |
| `level` | INTEGER | The level. |

### space.junction

One row is one node of one intersection. `subsections.py` writes it from the container step's node groups. At level 0, `division.py`
writes the OSM junction nodes inside each new intersection.

Key: `intersection_id`, `node_id`.

| column | type | meaning |
|---|---|---|
| `intersection_id` | VARCHAR | The intersection. |
| `node_id` | BIGINT | The node. |
| `level` | INTEGER | The level. |
| `cluster_id` | VARCHAR | The container step's node group. At level 0 it is the same as `intersection_id`. |

### space.unit

One row is one space: a subsection or an intersection. The units of one level cover the street space with no overlap. This file has 136
subsections and 41 intersections at level 0, and 9 subsections at level 1.

Key: `unit_id`.

| column | type | meaning |
|---|---|---|
| `unit_id` | VARCHAR | The unit's id: a subsection id or an intersection id. |
| `kind` | VARCHAR | `subsection` or `intersection`. |
| `section_id` | VARCHAR | The section of a subsection. NULL for an intersection. At level 0 the section comes from the blocks and is not a row of `space.container`. |
| `level` | INTEGER | The level. |
| `color` | VARCHAR | The color that the dashboard uses for the unit. |
| `geometry` | GEOMETRY | The unit's area (polygon). |

### space.subsection

One row is one subsection: a piece of a section between two cuts, where the lanes, the width or the frontage change.

Key: `subsection_id`.

| column | type | meaning |
|---|---|---|
| `subsection_id` | VARCHAR | The subsection's id, `<section id>/<k>`. |
| `section_id` | VARCHAR | The section. |
| `level` | INTEGER | The level. |
| `class` | VARCHAR | The road's OSM `highway` class. |
| `width_m` | DOUBLE | Level 0: the mean width from kerb to kerb. Other levels: the road element's width. |
| `oneway` | BOOLEAN | True for a one-way road. |
| `length_m` | DOUBLE | The length of the subsection's line. |
| `left` | VARCHAR | Level 0: the block on the left, or `edge` (the edge of the area). Other levels: `open` or `building <d> m`. |
| `right` | VARCHAR | The same for the right side. |
| `left_m` | DOUBLE | Other levels: the distance to the building line on the left. NULL where the side is open, and at level 0. |
| `right_m` | DOUBLE | The same for the right side. |
| `left_extra` | DOUBLE | Other levels: how much farther the space reaches on the left, where a parallel road follows this one. NULL at level 0. |
| `right_extra` | DOUBLE | The same for the right side. |
| `with_sections` | VARCHAR | Other levels: the sections of the parallel roads that follow this one. NULL at level 0. |
| `starts_at` | VARCHAR | Why the subsection starts: `section end`, `lanes change` or `frontage`. |
| `color` | VARCHAR | The color that the dashboard uses. |
| `geometry` | GEOMETRY | Level 0: the subsection's axis. Other levels: its piece of road (linestring). |

### space.cut

One row is one cut: a straight line across a street that ends a section and bounds an intersection. All rows in this file are at level 0.
There, a cut runs from block to block, 3 m past the block corner.

Key: none. One row per cut.

| column | type | meaning |
|---|---|---|
| `intersection_id` | VARCHAR | The intersection that the cut bounds. NULL (7 rows) where no intersection touches the cut. |
| `edge_id` | VARCHAR | Level 0: the OSM way id of the road that the cut crosses. Other levels: the duckOSM edge id. |
| `level` | INTEGER | The level. |
| `how` | VARCHAR | How the cut was placed. `block corner + 3 m` for all rows in this file. |
| `length_m` | DOUBLE | The cut's length. |
| `geometry` | GEOMETRY | The cut (linestring). |

### space.part

One row is one part of a unit: a lane, a shoulder, a sidewalk, a junction area and so on. The parts of a unit cover it with no
overlap. This file has 1800 parts at level 0 and 34 at level 1.

Key: `part_id`. Provenance: `source`, `method`, `ref`, `width_source`, `width_method`, `position_source`, `position_method`,
`position_ref` (see [Provenance columns](#provenance-columns)).

| column | type | meaning |
|---|---|---|
| `unit_id` | VARCHAR | The unit (`space.unit`). |
| `part_id` | VARCHAR | The part's id, `<unit id>#<n>`. |
| `level` | INTEGER | The level. |
| `type` | VARCHAR | In this file: `lane`, `sidewalk`, `shoulder`, `frontage`, `parking`, `driveway`, `furnishing`, `junction area`, `island`, `cycle lane`, `bus zone`, `verge`, `barrier`. |
| `arm` | VARCHAR | Level 0: the side of the subsection's axis (`left` or `right`) of a sidewalk, furnishing or frontage part. NULL for other parts. |
| `direction` | VARCHAR | A lane's direction along the axis: `forward`, `backward`, or `both` for a lane used both ways. |
| `lane` | INTEGER | A lane's number from the right of its direction of travel. |
| `lane_id` | VARCHAR | The lane's id in duckOSM's GMNS export, `<edge_id>_<lane_num>`. Two ids joined by `;` for a lane used both ways. NULL for a road not in duckOSM's driving network. |
| `width_m` | DOUBLE | The part's width. |
| `width_source` | VARCHAR | The source of the width. |
| `width_method` | VARCHAR | The method of the width. |
| `length_m` | DOUBLE | The part's length. At level 0 it is half the length of the part's outline. |
| `source` | VARCHAR | The source of the part. |
| `method` | VARCHAR | The method of the part. |
| `ref` | VARCHAR | The source item, for example `w336755856 lanes=2`. |
| `position_source` | VARCHAR | The source of the part's edge. |
| `position_method` | VARCHAR | The method of the part's edge. |
| `position_ref` | VARCHAR | The items that set the edge, for example the OSM sidewalk way and the block. |
| `road` | VARCHAR | The name of the road that the part belongs to. |
| `road_class` | VARCHAR | That road's OSM `highway` class. |
| `speed` | VARCHAR | That road's speed limit, with its source in parentheses. Level 1 only in this file. |
| `surface` | VARCHAR | That road's surface, with its source in parentheses. Level 1 only in this file. |
| `lit` | VARCHAR | That road's OSM `lit` value, or `not in OSM`. Level 1 only in this file. |
| `road_lanes` | VARCHAR | That road's lane count. |
| `oneway` | VARCHAR | Whether that road is one-way: `true` or `false` at level 0, the OSM `oneway` value at level 1. |
| `holds` | VARCHAR | What stands in the part (a furnishing strip), or the OSM tag that applies to a shoulder. |
| `rule` | VARCHAR | The rules that apply to the part, in words: the lane fit, a taper, a bus stop's timetable, parking rates. |
| `geometry` | GEOMETRY | The part's area (polygon or multipolygon). |

### space.mark

One row is one line in a unit: a painted line, an arrow, a kerb or a guide line through a junction.

Key: none. `unit_id` links each mark to its unit. Provenance: `source`, `method`, `ref`, `width_source`, `width_method` (see
[Provenance columns](#provenance-columns)).

| column | type | meaning |
|---|---|---|
| `unit_id` | VARCHAR | The unit (`space.unit`). |
| `level` | INTEGER | The level. |
| `type` | VARCHAR | In this file: `guide line`, `arrow`, `kerb`, `lane line`, `stop line`, `edge line`, `centre line`, `zebra`. |
| `arm` | VARCHAR | The intersection arm of the mark. NULL for all rows in this file. |
| `length_m` | DOUBLE | The line's length. |
| `width_m` | DOUBLE | The line's width. |
| `width_source` | VARCHAR | `urbanstyle` for all rows. |
| `width_method` | VARCHAR | `chosen` for all rows. |
| `source` | VARCHAR | The source of the line. |
| `method` | VARCHAR | The method of the line. |
| `ref` | VARCHAR | The source item, or the rule that made the line. |
| `geometry` | GEOMETRY | The line (linestring or multilinestring). |

### space.width

One row gives the widths of one unit. At level 0 there is one row per unit. At level 1 the widths are measured across the middle of a
subsection.

Key: `unit_id`, `edge`. Provenance: `source` (see [Provenance columns](#provenance-columns)).

| column | type | meaning |
|---|---|---|
| `unit_id` | VARCHAR | The unit (`space.unit`). |
| `level` | BIGINT | The level. |
| `edge` | VARCHAR | Where the widths are measured: `middle` (across a subsection), or the edge id of an intersection arm. NULL at level 0. |
| `arm` | VARCHAR | The road name of an intersection arm. NULL for all rows in this file. |
| `total_m` | DOUBLE | The width across the whole space. |
| `carriageway_m` | DOUBLE | The width from kerb to kerb. |
| `left_m` | DOUBLE | The width from the left kerb to the space's edge. |
| `right_m` | DOUBLE | The width from the right kerb to the space's edge. |
| `lanes_in` | BIGINT | At an arm: the lanes into the junction. Level 0: the lanes against the axis. Other levels: the forward lanes. |
| `lanes_out` | BIGINT | At an arm: the lanes out of the junction. Level 0: the lanes along the axis. Other levels: the backward lanes. |
| `lane_m` | DOUBLE | The lane width: the median at level 0, the mean at other levels. |
| `source` | VARCHAR | `urbanstyle` or `measured one side` in this file. |
| `osm_lanes` | BIGINT | OSM's lane count. |

The 41 intersection rows at level 0 have NULL in all width columns.

### space.turn

One row is one lane-to-lane move through an intersection. SUMO's `netconvert` makes the moves from duckOSM's network.

Key: `unit_id`, `from_edge`, `from_lane`, `to_edge`, `to_lane`.

| column | type | meaning |
|---|---|---|
| `unit_id` | VARCHAR | The intersection (`space.unit`). |
| `level` | INTEGER | The level. |
| `from_edge` | VARCHAR | The duckOSM edge id of the road that the move comes from. |
| `from_lane` | INTEGER | The lane that the move comes from, counted from the right (1 = the rightmost). |
| `to_edge` | VARCHAR | The duckOSM edge id of the road that the move goes to. |
| `to_lane` | INTEGER | The lane that the move goes to, counted from the right. |
| `turn` | VARCHAR | `left`, `straight` or `right`. |
| `source` | VARCHAR | `sumo` for all rows. |
| `vehicles` | VARCHAR | The vehicles that can make the move, for example `bus,taxi`. NULL: all traffic. |
| `condition` | VARCHAR | The time when a rule applies, for example `Mo-Su 07:00-19:00`. NULL for all rows in this file. |
| `geometry` | GEOMETRY | The move's guide line (linestring). |

### space.approach

One row is one lane that comes into a junction: its moves and its turn arrow. Checks U11 to U13 read it.

Key: none. One row per intersection, incoming edge and lane.

| column | type | meaning |
|---|---|---|
| `unit_id` | VARCHAR | The intersection (`space.unit`). |
| `level` | INTEGER | The level. |
| `from_edge` | VARCHAR | The duckOSM edge id of the incoming road. NULL for 7 rows. |
| `lane` | INTEGER | The lane, counted from the right. |
| `moves` | INTEGER | The number of moves from this lane (`space.turn`). |
| `ways` | VARCHAR | The ways that all traffic can go, joined by commas: `left`, `straight`, `right`. |
| `arrow` | BOOLEAN | True if the lane has a painted turn arrow. |
| `no_arrow_because` | VARCHAR | Why the lane has no arrow: `no move` or `another arrow in the way`. |

## The ground

`ground.py` writes these tables, except `space.lot`, which `container.py` writes. [Layers](../design/space-layers.md) gives the design.

### space.ground

One row is one ground item: layer 0. Every piece of the area at level 0 is in exactly one ground item.

Key: `ground_id`. Provenance: `source`, `method`, `ref` (see [Provenance columns](#provenance-columns)).

| column | type | meaning |
|---|---|---|
| `ground_id` | VARCHAR | The item's id, `g0-<type>-...`. |
| `level` | INTEGER | Always 0. |
| `type` | VARCHAR | In this file: `building`, `street`, `yard`, `alley`, `car park`, `green`, `construction site`, `rail`, `structure`. The code can also write `water`, `path`, `square`, `plot` and `unknown`. |
| `name` | VARCHAR | The name in the source. |
| `source` | VARCHAR | The source. |
| `method` | VARCHAR | The method. |
| `ref` | VARCHAR | The source item. For a street item, the unit id. |
| `geometry` | GEOMETRY | The item's area (polygon or multipolygon). |

### space.surface

One row is one surface that covers part of a ground item: layer 1. The surfaces of a ground item cover it exactly.

Key: `surface_id`. Provenance: `source`, `method`, `ref` (see [Provenance columns](#provenance-columns)).

| column | type | meaning |
|---|---|---|
| `surface_id` | VARCHAR | The surface's id, `<ground id>:<type>`, with `/<n>` where the surface has more than one piece. |
| `ground_id` | VARCHAR | The ground item (`space.ground`). |
| `level` | INTEGER | Always 0. |
| `type` | VARCHAR | In this file: `building`, `pedestrian realm`, `roadway`, `yard`, `lawn`, `median`, `car park`, `path`, `construction site`, `play`, `under bridge`, `track bed`. |
| `source` | VARCHAR | The source. |
| `method` | VARCHAR | The method. |
| `ref` | VARCHAR | The source items, or `the parts of <unit id>`. |
| `geometry` | GEOMETRY | The surface's area (polygon). |

### space.path

One row is one footpath or cycleway at level 0, whole, as one OSM way at its width. A path lies on the ground and is not a ground item.

Key: `path_id`. Provenance: `width_source`, `width_method` (see [Provenance columns](#provenance-columns)).

| column | type | meaning |
|---|---|---|
| `path_id` | VARCHAR | The OSM way, `w<way>`. |
| `kind` | VARCHAR | `sidewalk`, `crossing` or `steps` from the OSM subtype, else the OSM class (`footway`, `cycleway`, `path`, ...). |
| `name` | VARCHAR | The way's name. |
| `width_m` | DOUBLE | The path's width. |
| `width_source` | VARCHAR | `osm` for all rows in this file. |
| `width_method` | VARCHAR | `mapped` for all rows in this file. |
| `on` | VARCHAR | The ground items that the path lies on, joined by commas. |
| `geometry` | GEOMETRY | The path's area: its line, widened to its width (polygon or multipolygon). |

### space.parcel

One row is one land parcel from the city's open data (Vancouver `property-parcel-polygons`). A parcel is the property line that the street
reaches. The table is empty where the area has no city file `<unit>.vancouver.json`.

Key: `parcel_id`.

| column | type | meaning |
|---|---|---|
| `parcel_id` | VARCHAR | The parcel's id, `pl<site id>`. |
| `name` | VARCHAR | The civic number and the street name. |
| `geometry` | GEOMETRY | The parcel's outline (polygon). |

### space.lot

One row is one off-street car park from OSM (`amenity=parking` on the ground). A lot is private ground beside the street, as a building's
plot is.

Key: `lot_id`.

| column | type | meaning |
|---|---|---|
| `lot_id` | VARCHAR | The OSM way, `w<way>`. |
| `type` | VARCHAR | `parking lot` for all rows. |
| `name` | VARCHAR | OSM `name`. |
| `parking` | VARCHAR | OSM `parking`, else `surface`. |
| `access` | VARCHAR | OSM `access`. |
| `fee` | VARCHAR | OSM `fee`. |
| `operator` | VARCHAR | OSM `operator`, else `brand`. |
| `level` | INTEGER | Always 0. |
| `geometry` | GEOMETRY | The car park's outline (polygon). |

## Buildings and elements

### space.element

One row is one element: a building, or a piece of a road, walkway, cycleway or rail line. `container.py` writes it. `buildings.py` adds a
city's building outlines that OSM does not have, and sets the use columns. This file has 961 walkways, 561 roads, 432 buildings and 23
cycleways.

Key: `source_id`. Provenance: `source`, `level_src`, `width_src`, `use_source`, `use_method`, `ground_source`, `ground_method` (see
[Provenance columns](#provenance-columns)).

| column | type | meaning |
|---|---|---|
| `source` | VARCHAR | `osm`, or `vancouver` for a city building outline. |
| `source_id` | VARCHAR | A building: `w<way>`, `r<relation>` or `vb<id>`. A road, walkway or cycleway: its duckOSM edge id. Rail: `w<way>`. |
| `type` | VARCHAR | `road`, `walkway`, `cycleway`, `rail` or `building`. |
| `level_min` | INTEGER | The lowest level, clamped to -2 … 2. |
| `level_max` | INTEGER | The highest level, clamped to -2 … 2. |
| `level_src` | VARCHAR | Where the levels come from: `layer`, `bridge`, `tunnel`, `num_floors`, `height`, the city's LiDAR, or `chosen`. |
| `name` | VARCHAR | The OSM name. |
| `class` | VARCHAR | The OSM `highway` value of a line, or the `building` value of a building. |
| `geometry` | GEOMETRY | A line (linestring) or a building outline (polygon). |
| `width_m` | DOUBLE | The width of a road, walkway, cycleway or rail line. NULL for a building. |
| `osm_id` | BIGINT | The OSM way of a line. A negative id is a duckOSM connector edge. NULL for a building. |
| `zone` | VARCHAR | The zone of a line: `travelway`, `pedestrian_realm` or `track`. NULL for a building. |
| `container_id` | VARCHAR | The container that holds the line. NULL for a building. |
| `src` | BIGINT | The node at the start of the line. |
| `dst` | BIGINT | The node at the end of the line. |
| `subtype` | VARCHAR | `sidewalk` or `crossing` for a walkway. |
| `oneway` | BOOLEAN | True for a one-way road. |
| `floors` | INTEGER | A building's real number of floors, before the clamp to -2 … 2. |
| `height_m` | DOUBLE | A building's real height. |
| `width_src` | VARCHAR | Where `width_m` comes from, in words. |
| `use` | VARCHAR | What the building is used for: `residential`, `retail`, `commercial`, `office`, `civic`, `industrial`, `ancillary` or `mixed`. |
| `use_source` | VARCHAR | The source of `use`. |
| `use_method` | VARCHAR | The method of `use`. |
| `ground_use` | VARCHAR | The use of the ground floor: `residential`, `retail`, `food & drink`, `services`, `leisure`, `office`, `civic` or `vacant`. |
| `ground_source` | VARCHAR | The source of `ground_use`. |
| `ground_method` | VARCHAR | The method of `ground_use`. |
| `uses` | VARCHAR | The evidence for the uses: the OSM tag, the shops in the building, the city's storefronts. |

## Objects

### space.object

One row is one point object from an OSM node: a bench, a tree, a crossing, a sign and so on. `container.py` writes it.

Key: `object_id`.

| column | type | meaning |
|---|---|---|
| `object_id` | VARCHAR | The OSM node, `n<node>`. |
| `class` | VARCHAR | The object's `group.class`, for example `furniture.bench`. |
| `level` | INTEGER | The node's `level` or `layer` tag, else 0. |
| `container_id` | VARCHAR | The container that holds the object. NULL outside every container. |
| `zone` | VARCHAR | The zone that holds the object. |
| `near_m` | DOUBLE | Outside every container: the distance to the nearest one, up to 60 m. |
| `name` | VARCHAR | OSM `name`. |
| `attrs` | JSON | The node's OSM tags that urbanstyle reads. |
| `source` | VARCHAR | `osm` for all rows. |
| `geometry` | GEOMETRY | The object's position (point). |

### space.observed

One row is one map feature that Mapillary detects in street photos. The build loads it from `<db>.mapillary.json` when that file exists.
`urbanstyle mapillary` also writes it. Mapillary data confirms objects. It makes no object, part or line.

Key: `feature_id`.

| column | type | meaning |
|---|---|---|
| `feature_id` | VARCHAR | Mapillary's feature id. |
| `class` | VARCHAR | Mapillary's class, for example `object--street-light`. |
| `grp` | VARCHAR | The group that urbanstyle reads it as, for example `street light`. |
| `first_seen` | TIMESTAMP | The first photo that shows it. |
| `last_seen` | TIMESTAMP | The last photo that shows it. |
| `source` | VARCHAR | `mapillary` for all rows. |
| `geometry` | GEOMETRY | The feature's position (point). |

### space.photo

One row is one Mapillary photo position. It comes from the same file as `space.observed`.

Key: `photo_id`.

| column | type | meaning |
|---|---|---|
| `photo_id` | VARCHAR | Mapillary's image id. |
| `captured` | TIMESTAMP | When the photo was taken. |
| `compass` | DOUBLE | The camera's compass angle, in degrees. |
| `is_pano` | BOOLEAN | True for a panorama. |
| `sequence` | VARCHAR | Mapillary's sequence id. |
| `geometry` | GEOMETRY | The camera's position (point). |

### space.strip

One row is one band of a container: a travel lane, a sidewalk, a frontage and so on. `strips.py` writes it. The strips of a container
add up to its travelway and pedestrian realm.

Key: `strip_id`. Provenance: `source`, with its own words (see [Provenance columns](#provenance-columns)).

| column | type | meaning |
|---|---|---|
| `container_id` | VARCHAR | The container (`space.container`). |
| `level` | INTEGER | The container's level. |
| `strip_id` | VARCHAR | The strip's id, `<container id>.<n>`. |
| `type` | VARCHAR | In this file: `travel`, `sidewalk`, `frontage`, `furnishing`, `open`, `plaza`, `cycle`. A rail space has `track`. |
| `side` | VARCHAR | `left`, `right` or `center` of the road. NULL where no side applies. |
| `width_m` | DOUBLE | The strip's area divided by its length. |
| `source` | VARCHAR | `tag` (an OSM lanes or width tag), `measured` (a measured line) or `default`. |
| `geometry` | GEOMETRY | The strip's area (polygon). |

## Levels

`container.py` writes these tables.

### space.link

One row is one place where a person or a vehicle changes level: a node where elements of two levels meet, or a station entrance.

Key: `node_id`, `level_a`, `level_b`.

| column | type | meaning |
|---|---|---|
| `node_id` | BIGINT | The node. |
| `level_a` | INTEGER | The lower level. |
| `level_b` | INTEGER | The higher level. |
| `type` | VARCHAR | `ramp`, `stairs`, `elevator`, `entrance` or `connection`. This file has 13 `connection` rows and 2 `ramp` rows. |
| `assumed` | BOOLEAN | True for an entrance with no station found. Its level below is assumed to be -1. |
| `geometry` | GEOMETRY | The node's position (point). |
| `station_id` | VARCHAR | The station of an entrance (`space.station`). |
| `match` | VARCHAR | How the entrance was tied to its station: `name` or `nearest`. |
| `dist_m` | DOUBLE | The distance from the entrance to its station. |

`station_id`, `match` and `dist_m` are NULL for all rows in this file.

### space.station

One row is one rail, subway or tram station from OSM. Its level comes from its own tag, else from the rail line beside it.

Key: `id`. This table is empty in this file.

| column | type | meaning |
|---|---|---|
| `id` | VARCHAR | The OSM item, for example `n<node>`. |
| `name` | VARCHAR | OSM `name`. |
| `kind` | VARCHAR | The station's kind, for example `subway`. |
| `level` | INTEGER | The station's level. |
| `geometry` | GEOMETRY | The station's position. |

## Tables that urbanstyle serve adds

`urbanstyle serve DB PAGE [--bridge PROFILE]` opens the area's file read-only. It adds two tables in memory, in a `space` schema of its
own (`serve.Area`). It does not write them to the file. The counts below come from Broadway × Granville with
`data/bridges-measured/granville-bridge.bridge.json`.

### space.bridge_part

One row is one part of a bridge's model, as the flat outlines that `bridge2d` draws. The table is empty with no `--bridge` profile.
This file gives 266 rows with 214 different ids: the rows of one crosswalk share its path's id.

Key: none. Provenance: `source`, `method` (see [Provenance columns](#provenance-columns)).

| column | type | meaning |
|---|---|---|
| `id` | VARCHAR | The part's id: a lane id with its axis, `<type> w<way>`, or `<type> @<x>,<y>`. |
| `type` | VARCHAR | The part's type, for example `lane`, `crosswalk`, `barrier`, `footway`. |
| `kind` | VARCHAR | The model's key for the part, for example `lane forward`, `mark zebra`, `sidewalk`. |
| `bridge` | VARCHAR | The bridge's name. |
| `axis` | VARCHAR | The bridge axis, `a1`, `a2`, ... NULL for a part with no axis. |
| `direction` | VARCHAR | A lane's direction: `forward` or `backward`. |
| `width_m` | DOUBLE | The part's width. |
| `osm` | VARCHAR | The OSM way, `w<way>`. |
| `source` | VARCHAR | The source, in words, for example `duckOSM GMNS (lanes from SUMO)`. |
| `method` | VARCHAR | The method. |
| `fields` | JSON | All fields of the part in the model. |
| `geometry` | GEOMETRY | The part's outline. |

### space.street_object

One row is one real street object, matched from every source: OSM, the city's survey and Mapillary. The 3D page draws the same objects
(`dashboard.matched_objects`). The Broadway × Granville file gives 2616 rows.

Key: `id`.

| column | type | meaning |
|---|---|---|
| `id` | VARCHAR | The ids of the object in all of its sources, joined by `, `, for example `public-trees-18, n14190549035`. |
| `class` | VARCHAR | The object's `group.class`, for example `vegetation.tree`. |
| `type` | VARCHAR | The last part of `class` in words, for example `tree`. |
| `level` | INTEGER | The level. |
| `sources` | VARCHAR | The sources, joined by `, `, for example `vancouver, osm`. |
| `height_m` | DOUBLE | A measured height, where a source gives one. |
| `details` | VARCHAR | What each source says of the object. A vertical bar separates the sources. |
| `methods` | VARCHAR | The method of each source, for example `vancouver: recorded; osm: mapped`. |
| `geometry` | GEOMETRY | The object's position in lon/lat (point). |
