# The agreed street rules

Status: agreed with Kaveh on 2026-10-14. Each rule has a check. `urbanstyle check DB` runs the checks at level 0, and a broken rule
is a FAIL with links to the places (`?at=`).

| # | Rule | Check |
|---|---|---|
| 1 | **OSM geometry first.** The lanes of each carriageway lie centred on its own OSM line. The number of lanes is OSM's `lanes`. If OSM gives no number, a two-way road has one lane in each direction, never one shared lane. The width is OSM's `width`, else the number of lanes × the chosen lane width. | A1 |
| 2 | **No object without a source.** A parking lane, a bike lane, a barrier in a median or a shoulder that fills a width is only where OSM or a city says so. | A2 |
| 3 | **The kerb is a result.** The kerb is the outer edge of the lanes and of the items that have a source. Kerb evidence (catch basins, poles, sidewalk lines) only checks the result. It does not move the lanes. | A1 |
| 4 | **Connections only at shared OSM nodes.** Two roads that share no node stay apart, also when they touch. | J1 |
| 5 | **Junctions from the network** (`junctions.md`). A junction is only at a node where 3 or more road ends meet. Its core is where its arms overlap, it reaches to the crosswalk or stop line, and its corners are round. It is never "the street left over" between sections. | J1 |
| 6 | **Blocks follow the footways** (`blocks.md`), piece by piece, with sharp corners. A block never covers a carriageway. A pedestrian street lies inside a block. | A3 |

## The checks

| Check | Fails when |
|---|---|
| A1 | The middle of a carriageway's lanes (one OSM way in one space) is more than 0.5 m from its OSM line. The value is the median over cross lines every 5 m. |
| A2 | A parking lane or a cycle lane has the source `urbanstyle`, so no real source gives it. |
| A3 | A road line at level 0 (a street class) has a stretch longer than 2 m with no roadway under it (lane, junction area, carriageway, bridge deck, bus lane or zone, parking, shoulder, cycle lane). The area's edge (2 m) is not counted. |
| J1 | An intersection at level 0 holds no junction node: a node where 3 or more road ends meet (a road that runs through the node counts 2). |

The ids A1-A3 are not L1-L3, because L1 and L2 are the checks of layer 1 (the surfaces).

## Results on 2026-10-14 (the builds before these rules were applied)

| Check | Monaco | Broadway × Granville |
|---|---|---|
| A1 | 324 | 86 |
| A2 | 161 | 54 |
| A3 | 251 | 5 |
| J1 | 18 | 0 |
