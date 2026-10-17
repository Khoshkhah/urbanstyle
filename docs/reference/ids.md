# Ids

This page lists the id schemes in the `space` tables and in the bridge model. For each scheme it gives the pattern, an example from
`data/units/broadway-granville.urban.duckdb`, and the code that makes it.

In the patterns, `<level>` is the integer level (-2 to 2). A negative level keeps its minus sign, so `p-1-37127178` is a path space at
level -1. For the tables and their columns, see [Tables](tables.md).

## Summary

| scheme | pattern | example | tables |
|---|---|---|---|
| duckOSM edge | `<edge_id>` | `721492229101496909` | `element`, `arm`, `turn`, `approach` |
| section container | `s<level>-<edge_id>` | `s0-2002513880381972879` | `container`, `zone`, `strip`, `arm` |
| path space | `p<level>-<way>` | `p0-1009155995` | `container` |
| rail space | `r<level>-<way>` | none in this file | `container` |
| intersection container | `i<level>-<node>` | `i0-245673105` | `container`, `arm` |
| plaza | `z<level>-<id>.<k>` | `z0-1027057143247166638.1` | `container` |
| street | `k<level>-<way>` | `k0-48524371` | `street`, `container`, `arm` |
| block | `b<level>-w<way><side>` | `b0-w336778027l` | `block`, `block_side` |
| city block | `cb<lon><lat>` | `cb-123.14209+49.26666` | `city_block` |
| level-0 section | `s0-<block>~<block>` | `s0-edge~w336755750l` | `unit`, `subsection` |
| level-0 intersection | `i0-<node>` | `i0-1908456303` | `unit`, `junction`, `cut`, `turn` |
| subsection | `<section id>/<k>` | `s0-edge~w336755750l/1` | `subsection`, `unit` |
| part | `<unit id>#<n>` | `s0-edge~w336755750l/1#8` | `part` |
| strip | `<container id>.<n>` | `s0-2002513880381972879.1` | `strip` |
| lane | `<edge_id>_<lane_num>` | `2739184379877144356_1` | `part.lane_id` |
| ground item | `g0-<type>-...` | `g0-building-w326974348` | `ground`, `surface`, `path.on` |
| surface | `<ground id>:<type>` | `g0-building-w326974348:building` | `surface` |
| OSM item | `n<node>`, `w<way>`, `r<relation>` | `n13950936172`, `w917506545` | `object`, `element`, `path`, `lot` |
| city record | `pl<site id>`, `vb<id>`, `<dataset>-<index>` | `plVAS1118`, `vb6524529`, `public-trees-18` | `parcel`, `element`, `street_object` |
| Mapillary | `<feature id>`, `<image id>` | `1442040979927404` | `observed`, `photo`, `street_object` |
| bridge part | `<lane_id> <axis>.<section>`, `<type> w<way>`, `<type> @<x>,<y>` | `641676206441300162_3 a1.0` | `bridge_part` |

## duckOSM edge ids

duckOSM gives each directed edge of its road networks an `edge_id`. The id is a content hash: `hash(osm_id, source, target) >> 1`,
a 63-bit BIGINT. An edge that does not change keeps its id when duckOSM builds the area again. The two directions of a two-way road
have different ids, because `source` and `target` change places.

- Example: `721492229101496909` (`work.arm.edge_id`).
- Made by: duckOSM, `graph_simplifier._rekey_edges`.

urbanstyle keeps the edge id as text (VARCHAR) in `work.element.source_id`, `work.arm.edge_id`, `work.turn.from_edge`,
`work.turn.to_edge` and `work.approach.from_edge`. duckOSM keeps it as BIGINT.

A duckOSM connector edge joins a loose path end to the network. Its `osm_id` is negative: `-min(a, b)` of the two ways that it joins.

## Containers

`container.py` (`street_owner()` and the `CONTAINER` SQL) makes the container ids in `work.container`. The number after the level is
the smallest id among the elements of the container.

| kind | pattern | example | the number is |
|---|---|---|---|
| section | `s<level>-<edge_id>` | `s0-2002513880381972879` | the smallest duckOSM edge id of its roads |
| path space | `p<level>-<way>` | `p0-1009155995` | the smallest OSM way id of its walkways and cycleways |
| rail space | `r<level>-<way>` | none in this file | the smallest OSM way id of its rail lines |
| intersection | `i<level>-<node>` | `i0-245673105` | the smallest OSM node id of its junction nodes |
| plaza | `z<level>-<id>.<k>` | `z0-1027057143247166638.1` | the id of the section or path space that it was cut from, without its letter |

These rules change the base id:

- A container must be one polygon. If a region has more than one piece, the piece with the most road keeps the id. Each other piece
  gets `.<k>`, from `.1`: `s0-2053129043072737807.1`.
- A piece of a section with no road is a path space. It keeps the section's number with the letter `p`: `p0-990552329813747873.2`.
- A path space that starts at a duckOSM connector edge has a negative way id: `p0--1148011239`.
- An intersection with no real node takes the smallest absolute value of its virtual node ids.

## Streets

A street is the group of connected roads of one level that share a name (`work.street`).

- Pattern: `k<level>-<way>`, where `<way>` is the smallest OSM way id among its roads.
- Examples: `k0-48524371`, `k1-473723205`.
- Made by: `container.py`, `street_owner()`.

## Blocks

A block is the land between the streets at level 0 (`work.block`).

- Pattern: `b<level>-w<way><side>`. `<way>` is the smallest OSM way id among the roads that bound the block. `<side>` is `l` or `r`: the
  side of that way that the block is on.
- Examples: `b0-w336778027l`, `b0-w336795531r`.
- If one way bounds more than one block on one side, the next blocks get `.2`, `.3` and so on: `b0-w336755750l.2`.
- If no bounding way is found, the id is `b0-x<X>y<Y>`, from the block's centre in UTM metres. This file has none.
- Made by: `blocks.py`, `build()`.

A city block (`work.city_block`) has no id in the city's data. urbanstyle makes one from its centre point: `cb` with the longitude and
the latitude to 5 decimals, for example `cb-123.14209+49.26666`. `blocks.city_blocks()` makes it.

## Level-0 sections and intersections

At level 0, `division.py` divides the street between the blocks. It makes new section and intersection ids for `work.unit`,
`work.subsection`, `work.part` and `work.mark`. These sections are not rows of `work.container`.

| item | pattern | example |
|---|---|---|
| section | `s0-<block>~<block>` | `s0-edge~w336755750l` |
| section, second of a pair | `s0-<block>~<block>.<n>` | `s0-w74271358r~w74271358r.2` |
| intersection | `i0-<node>` | `i0-1908456303` |

- `<block>` is the block id without `b0-`, or `edge` for the edge of the area. The two names are in sort order.
- If two blocks face each other on more than one section, the second section gets `.2`, the third `.3` and so on.
- An intersection takes the smallest OSM node id inside it. With no node inside, the id is `i0-x<X>y<Y>`, from its centre in UTM metres.
  A second intersection with the same id gets `.2`. This file has neither case.
- `work.junction` lists the nodes of each level-0 intersection.

## Subsections

A subsection is a piece of a section (`work.subsection`, `work.unit`).

- Pattern: `<section id>/<k>`, with `k` = 1, 2, ... along the section.
- Example at level 0: `s0-edge~w336755750l/1`. `division.py` makes it.
- Example at level 1: `s1-1211493292939381263/1`. `subsections.py` makes it from the section container's id.

## Parts

A part is one piece of the inside of a unit (`work.part`).

- Pattern: `<unit id>#<n>`, with `n` = 1, 2, ... in the order that the code adds the parts to the unit.
- Examples: `s0-edge~w336755750l/1#8` (a lane), `i0-1908456303#1`.
- Made by: `division.py` (`add()`) at level 0, `parts.py` at other levels.

`work.mark` has no id. Its `unit_id` links it to its unit.

## Strips

A strip is one band of a container (`work.strip`).

- Pattern: `<container id>.<n>`, with `n` = 1, 2, ... in each container.
- Examples: `s0-2002513880381972879.1`, `p-1-37127178.1`.
- Made by: `strips.py`.

## Lanes

`work.part.lane_id` is a lane's id in duckOSM's GMNS export (`gmns_driving.lane.lane_id`).

- Pattern: `<edge_id>_<lane_num>`. `<edge_id>` is the directed duckOSM edge under the lane's middle, in its direction of travel.
  `<lane_num>` is the lane's number from the left of that direction (1 = the leftmost).
- Example: `2739184379877144356_1`.
- A lane used in both directions has both ids, joined by `;`. This file has none.
- The value is NULL for a road that is not in duckOSM's driving network.
- Made by: duckOSM (`duckosm gmns`). `division.gmns_lane()` finds the edge for each lane.

## Ground items and surfaces

A ground item is one piece of layer 0 (`work.ground`). `ground.py` (`build()`) makes the id in one of four forms:

| form | when | example |
|---|---|---|
| `g0-<type>-<ref>` | an item from one source item | `g0-building-w326974348`, `g0-green-w37055182` |
| `g0-street-<unit id>` | a street item: one unit | `g0-street-s0-edge~w336755750l/1`, `g0-street-i0-1908456303` |
| `g0-<type>-<ref>-<X>-<Y>` | a piece that a road or a path runs through | `g0-alley-w45132516-489821-5456405` |
| `g0-<type>-<X>-<Y>` | a piece that no source names | `g0-yard-489522-5456870` |

`<ref>` is the source item: an OSM way or relation, a city outline (`vb<id>`) or a unit id. `<X>` and `<Y>` are the piece's centre in
UTM metres, rounded.

A surface is one piece of layer 1 (`work.surface`). `ground.surfaces()` makes its id.

- Pattern: `<ground id>:<type>`, with `/<n>` where the surface has more than one piece.
- Examples: `g0-building-w326974348:building`, `g0-street-s0-edge~w336755750l/1:roadway`,
  `g0-street-s0-edge~w336755750l/1:pedestrian realm/1`.

## OSM items

An OSM item has its type letter and its OSM id: `n` for a node, `w` for a way, `r` for a relation.

| table | id | example |
|---|---|---|
| `work.object` | `object_id`, an OSM node | `n13950936172` |
| `work.element`, buildings | `source_id`, a way or a relation | `w326974348`, `r4139550` |
| `work.element`, rail | `source_id`, a way | none in this file |
| `work.path` | `path_id`, a way | `w917506545` |
| `work.lot` | `lot_id`, a way | `w1008302252` |
| `work.station` | `id`, a node or a way | none in this file |

A road, walkway or cycleway in `work.element` has its duckOSM edge id as `source_id`, not its OSM way. Its OSM way is in `osm_id`.

## City records

The City of Vancouver's open data reaches urbanstyle through `<unit>.vancouver.json`.

| item | pattern | example | made by |
|---|---|---|---|
| parcel | `pl<site id>` | `plVAS1118` | `ground.parcels()` |
| building outline | `vb<object id>` | `vb6524529` | `buildings.city()` |
| street object | `<dataset>-<index>` | `public-trees-18`, `street-lighting-poles-0` | `dashboard.matched_objects()` |

A parcel with no site id takes its `tax_coord`, else its index in the file. A street object's `<index>` is its place in the dataset's
list in the city file. It is not the city's own asset id.

## Mapillary

- `work.observed.feature_id`: Mapillary's map feature id, for example `1442040979927404`.
- `work.photo.photo_id`: Mapillary's image id, for example `599219062288532`.
- `work.photo.sequence`: Mapillary's sequence id, for example `xN3vq5ajPRGlTB8ewLpO7I`.

## Street objects

`work.street_object` is one real object that more than one source can show. `urbanstyle serve` makes it in memory.

- Pattern: the ids of the object in all of its sources, joined by `, `.
- Examples: `public-trees-18, n14190549035` (a city tree and an OSM node), `n4879505023, 1953492915056162, 1953492925056161` (an OSM
  node and two Mapillary features), `street-lighting-poles-0` (one source).
- Made by: `dashboard.matched_objects()`, from `unit.match`.

## Bridge parts

`work.bridge_part` holds the parts of a bridge's 3D model. `urbanstyle serve --bridge PROFILE` makes it in memory. `bridge3d.py` gives
each part its id.

| part | pattern | example |
|---|---|---|
| lane | `<lane_id> <axis>.<section>` | `641676206441300162_3 a1.0` |
| lane added on the bridge | `<lane_id>+<k> <axis>.<section>` | `1211493292939381263_1+1 a2.0` |
| lane that joins two lanes | `<lane_id>><lane_id> <axis>.<section>` | `4747140365369135178_1>4865609269725927722_2 a9.1` |
| path | `<type> w<way>` | `footway w871038540`, `shared path w1383685288` |
| other part | `<type> @<x>,<y>` | `barrier @88,189` |

- `<axis>` is the bridge axis in the bridge profile (`a1`, `a2`, ...). `<section>` is the section's index along that axis, from 0.
- `<x>,<y>` is the part's place in metres east and north of the bridge's middle.
- If one id occurs again, the next parts get ` #2`, ` #3` and so on: `footway w871038559 #2`.
- A crosswalk takes its path's id with no number. The crosswalk rows of one path share one id.

## Stable ids (planned)

Most ids on this page come from the smallest OSM or duckOSM id in a group, or from a count. If the source data changes, the id of a thing
can change. Requirement R6 of [the format](../design/format.md#r6-stable-ids-from-profiles) gives the plan: ids that
come from profiles, kept in a registry from build to build. That page gives the rules.
