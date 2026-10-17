# The tables

<p class="lead">One table per rank, and the tables that lie on the tree. Every row names its parent in the rank above, and the rows
of one parent partition it. Every row that holds a value names the value's source and method.</p>

All tables are in the `space` schema of an area's DuckDB file. Geometry is stored in lon/lat (EPSG:4326); the build measures in the
area's UTM zone. `level` is the integer level, -2 to 2. The columns `source`, `method` and `ref` say who gave a row, how they got it
and which of their items it is ([Sources and provenance](sources.md)).

## Rank 0

### `space.area`

The whole area of a level: one row per level.

| Column | Meaning |
|---|---|
| `level` | the level |
| `geometry` | the area: the clip's box, or OSM's boundary |

### `space.element`

The elements duckOSM gives: one row per road, walkway, cycleway or rail piece, and per building or car park.

| Column | Meaning |
|---|---|
| `element_id` | `w<way>` for a piece of a way; `b<id>` for a building |
| `type` | road, walkway, cycleway, rail, building, lot |
| `class`, `subtype` | OSM's `highway` or `railway` value; `footway=*` or `service=*` |
| `name`, `osm_id`, `source_id` | the name; the OSM way; the source's own id |
| `oneway`, `lanes_forward`, `lanes_backward`, `width_m`, `width_src` | from OSM's tags; where the width comes from |
| `level_min`, `level_max`, `level_src` | the level span and where it comes from (layer, bridge, tunnel, chosen) |
| `floors`, `height_m`, `use`, `ground_use`, with their sources and methods | a building's floors, height and use |
| `geometry` | the line, or the footprint |

## Rank 1

### `space.ground`

Every piece of the area of a level is one row: the street, a plot or a path. The three partition the area (checks G1 to G3).

| Column | Meaning |
|---|---|
| `ground_id` | `g<level>-street-<n>`, `g<level>-plot-<block>`, `g<level>-path-<corridor>` |
| `kind` | street, plot, path |
| `level` | the level |
| `parent_id` | the area |
| `name` | a street's name; a path's name |
| `source`, `method`, `ref` | urbanstyle, derived: the area less the blocks and the corridors; the block or the corridor it is |
| `sides` | a plot: its street sides, each with the way, the distance from the road line and what set it (sidewalks, carriageway, path width, building) |
| `width_m`, `width_source`, `width_method` | a path: OSM's width or the chosen one |
| `geometry` | the item, one polygon |

## Rank 2

### `space.stretch`

A stretch of the street or of a path: a section, an intersection, a path section, a path intersection.

| Column | Meaning |
|---|---|
| `stretch_id` | `s<level>-w<way>` (a second chain `.2`), `i<level>-<node>`, `p<level>-w<way>`, `q<level>-<node>` |
| `kind` | section, intersection, path section, path intersection |
| `level` | the level |
| `parent_id` | the street or the path of rank 1 |
| `street_id` | the named street a section belongs to |
| `ways` | the OSM ways, in order |
| `nodes` | the junction nodes: the two ends of a section, the cluster of an intersection |
| `class`, `name`, `oneway`, `length_m` | from the ways |
| `axis` | a section's line, its ways chained |
| `geometry` | the stretch's face of the street, cut by the stop lines; its spaces partition it |

### `space.plot_piece`

A piece of a plot, inside its block. The pieces of one block partition it.

| Column | Meaning |
|---|---|
| `piece_id` | `g<level>-<kind>-<ref>` |
| `kind` | building, yard, alley, car park, construction site, green, water, rail, square, structure |
| `level` | the level |
| `parent_id` | the plot |
| `name` | from the source |
| `source`, `method`, `ref` | OSM, mapped, the way; urbanstyle, derived, for a yard or an alley |
| `width_m`, `width_source`, `width_method` | an alley's width |
| `surfaces` | the surfaces that cover it (`space.surface`) |
| `geometry` | the piece, one polygon |

### `space.change`

One row per joint of a section where OSM's tags change, with its class.

| Column | Meaning |
|---|---|
| `section_id`, `subsection_a`, `subsection_b` | the section and the two subsections that meet |
| `way_a`, `way_b`, `lanes_a`, `lanes_b`, `width_a`, `width_b` | the two ways and their lanes and widths |
| `class` | turn pocket, merge, fork, parking, island, real, room, unknown, none |
| `note` | the evidence |
| `geometry` | the joint |

### `space.street` and `space.arm`

The named street, a group of stretches, and the arms that link an intersection to its named streets.

| Table | Columns |
|---|---|
| `space.street` | `street_id` (`k<level>-<way>`), `name`, `level`, `sections`, `intersections`, `geometry` |
| `space.arm` | `intersection_id`, `street_id`, `section_id`, `way` |

## Rank 3

### `space.unit`

One space per subsection, per intersection, per path section and per path intersection.

| Column | Meaning |
|---|---|
| `unit_id` | `s<level>-w<way>/<k>`, `i<level>-<node>`, `p<level>-w<way>/<k>`, `q<level>-<node>` |
| `kind` | subsection, intersection, path section, path intersection |
| `level` | the level |
| `parent_id` | its stretch |
| `axis` | a subsection's line |
| `width_m`, `oneway`, `length_m`, `left_extra` | the frame's width; one-way; the length; the merge shift |
| `geometry` | the space, one polygon |

### `space.junction`

The junction nodes of each intersection.

| Column | Meaning |
|---|---|
| `intersection_id`, `node_id`, `level`, `cluster_id` | |

## Rank 4

### `space.side`

The two sides of a space, and its islands.

| Column | Meaning |
|---|---|
| `side_id` | `<unit>:d`, `<unit>:w`, `<unit>:i<n>` |
| `kind` | driving, walking, island |
| `parent_id` | its space |
| `kerb` | the driving side: the line of its kerb, with `kerb_source` and `kerb_method` (OSM's sidewalk line, measured; the lanes' edge, derived) |
| `geometry` | the side, one polygon |

## Rank 5

### `space.part`

A piece of a side, of one type.

| Column | Meaning |
|---|---|
| `part_id` | `<unit>#<n>` |
| `type` | lane, paved, parking, no parking, shoulder, bus lane, cycle lane, junction area, crosswalk, cycle crossing, bridge deck, island, sidewalk, furnishing, frontage, driveway, bus stop, bus zone, tree pit; a path's surface, steps, ramp, handrail, bollard |
| `parent_id` | its side |
| `unit_id`, `level` | its space and level |
| `arm`, `direction`, `lane`, `lane_id` | a lane's road, direction (forward, backward, in, out), number from the middle, GMNS id |
| `width_m`, `length_m`, `width_source`, `width_method` | its width and length, and where the width comes from |
| `source`, `method`, `ref` | where the part comes from |
| `position_source`, `position_method`, `position_ref` | what set its edge |
| `road`, `road_class`, `speed`, `surface`, `lit`, `road_lanes`, `oneway` | what is known of the road a lane belongs to |
| `holds`, `rule` | what stands in it; the rules that apply (parking rates and hours, a timetable) |
| `geometry` | the part, one polygon |

## Rank 6

### `space.mark`

A painted line, an arrow, a zebra or the kerb line, on a part.

| Column | Meaning |
|---|---|
| `mark_id` | `<unit>:<type>:<n>` |
| `type` | kerb, lane line, centre line, edge line, parking line, stop line, give-way line, zebra, crossing line, arrow, guide line, barrier |
| `parent_id` | its part |
| `unit_id`, `level` | its space and level |
| `width_m`, `width_source`, `width_method`, `length_m` | the mark's width and length |
| `source`, `method`, `ref` | where it comes from |
| `geometry` | its middle line, or its shape |

### `space.turn` and `space.approach`

The lane-to-lane moves through each intersection and the lanes that come into it.

| Table | Columns |
|---|---|
| `space.turn` | `unit_id`, `from_edge`, `from_lane`, `to_edge`, `to_lane`, `turn` (left, straight, right), `vehicles`, `condition`, `source`, `geometry` |
| `space.approach` | `unit_id`, `level`, `from_edge`, `lane`, `moves`, `ways`, `arrow`, `no_arrow_because` |

## On the tree

### `space.object`

What stands in the street: one row per real thing.

| Column | Meaning |
|---|---|
| `object_id` | `n<node>`, `w<way>`, or the source's own id |
| `class` | `group.class` ([Street objects](objects.md)) |
| `level`, `unit_id`, `part_id` | where it stands; `near_m` when it stands outside every space |
| `name`, `attrs` | the name; a short set of attributes |
| `width_m`, `height_m`, with their sources and methods | its size |
| `sources`, `refs` | every source that describes it and its id in each |
| `source`, `method` | the best source and its method |
| `geometry` | the point |

### `space.link`

A join between two levels at a node.

| Column | Meaning |
|---|---|
| `link_id`, `type` (ramp, stairs, elevator, entrance, connection), `level_from`, `level_to`, `node`, `geometry` | |

### `space.station`

A rail, subway or tram station with its level and its entrances.

### `space.surface`

The surfaces that cover a ground item or a plot piece exactly: `surface_id` (`<item>:<kind>`), `ground_id`, `type` (roadway,
pedestrian realm, median, verge, building, car park, construction site, garden, yard, lawn, play, path, track bed, under bridge,
paved, water), `source`, `method`, `ref`, `geometry` (checks L1, L2).

### `space.observed` and `space.photo`

Mapillary's detections and photo positions, kept local, for validation only.

## The bridge model

A bridge is not in the tables: it is a profile file, `<name>.bridge.json`, with the deck outline, the axes, the vertical profiles, the
sections, the bands and the piers, each value with its source and method ([Levels, bridges and tunnels](levels.md)). The server adds
`space.bridge_part` in memory from the model, so the panel can find the model's lanes and paths.

## The unit dossier

A unit's dossier is its own database with the tables `unit`, `source`, `inventory`, `surface`, `line`, `object`, `match`, `lane`,
`movement`, `rule`, `observation` and `check` ([Sources and provenance](sources.md)).
