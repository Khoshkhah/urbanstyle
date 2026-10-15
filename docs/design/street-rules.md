# The agreed street rules

Status: agreed with Kaveh on 2026-10-14. Each rule has a check. `urbanstyle check DB` runs the checks at level 0, and a broken rule
is a FAIL with links to the places (`?at=`).

| # | Rule | Check |
|---|---|---|
| 1 | **OSM geometry first.** The lanes of each carriageway lie centred on its own OSM line. The number of lanes is OSM's `lanes`. If OSM gives no number, a two-way road has one lane in each direction, never one shared lane. The width is OSM's `width`, else the number of lanes × the chosen lane width. | A1 |
| 2 | **No object without a source.** A parking lane, a bike lane, a barrier in a median or a shoulder that fills a width is only where OSM or a city says so. | A2 |
| 3 | **The kerb is a result.** The kerb is the outer edge of the lanes and of the items that have a source. Kerb evidence (catch basins, poles, sidewalk lines) only checks the result. It does not move the lanes. | A1 |
| 4 | **Connections only at shared OSM nodes.** Two roads that share no node stay apart, also when they touch. | J1 |
| 5 | **Junctions from the network** (`junctions.md`). A junction is only at a node where 3 or more road ends meet. Its core is where its arms overlap, each arm reaches to its stop line and is cut square across its line there, and its corners are round. It is never "the street left over" between sections, and never a circle round the node. | J1, J2 |
| 6 | **Blocks follow the footways** (`blocks.md`), piece by piece, with sharp corners. A block never covers a carriageway. A pedestrian street lies inside a block. | A3 |
| 7 | **Crosswalks from OSM.** Every crossing way over the roadway, and every crossing node on a road with no crossing way, is a crosswalk part cut from the lanes. Its paint comes from `crossing:markings`: zebra bars, two crossing lines, or none. A crossing with no markings mapped gets the part and no paint. | X1 |
| 8 | **Lines carry the lane count's source.** No source maps a painted line. A lane line is drawn only between lanes OSM counts (`lanes`), with that source and method `derived`. The centre line between the two directions is drawn also where the count is chosen, as urbanstyle's own (`chosen`). | M1 |
| 10 | **Sections between junctions; continuity at their joints.** A section is the road from junction to junction, whatever OSM ways it is made of; it is cut into subsections where the cross-section changes. Lanes that run on through a joint keep their position (the subsection's line is moved sideways by up to 2 m for it, OSM's drawing error); the kerb opposite a merging road continues straight; a lane that ends narrows to nothing over 15 m (chosen). | A1 (2 m), R4 (INFO) |
| 11 | **Block edges follow the footway.** A block side runs 1 m behind the footway line, simplified by 0.5 m: straight where the footway is straight, bending only where it bends, never with the road. | B6 (INFO) |
| 12 | **A barrier continues from a bridge landing.** A bridge whose corrections name a median barrier keeps it on the ground along the landing way's lanes, on the side where a roadway of the other direction runs within 8 m, until that roadway ends or a junction begins. Source `urbanstyle corrections`, method `continued`. The strip it runs along is an island, not paved roadway. | – |
| 13 | **Not every shared node is a junction.** The road ends at a node are paired into streams (an end continues into the end most opposite to it, within 45°). The node is a junction only where an end has no continuation or two streams cross. Two roads that merge into one (a Y) make no junction: the lanes join side by side. | J1 |
| 9 | **Kerb evidence reports, it does not move.** A city's catch basins stand at the kerb. Where our kerb is far from them, the check says so, and the lanes stay where OSM puts them. | K1 |

## The checks

| Check | Fails when |
|---|---|
| A1 | The middle of a carriageway's lanes (one OSM way in one space) is more than 2 m from its OSM line (the line's drawing error, as the straight rule). The value is the median over cross lines every 5 m, outside the 15 m transition at each joint. |
| A2 | A parking lane or a cycle lane has the source `urbanstyle`, so no real source gives it. |
| A3 | A road line at level 0 (a street class) has a stretch longer than 2 m with no roadway under it (lane, junction area, carriageway, bridge deck, bus lane or zone, parking, shoulder, cycle lane, crosswalk). The area's edge (2 m) is not counted. |
| J1 | An intersection at level 0 holds no junction node: a node where 3 or more road ends meet (a road that runs through the node counts 2). |
| J2 | A junction area has a piece larger than 40 m² and than a tenth of the junction outside its arms' bands. An arm's band is its subsection's line as drawn, as wide as its roadway plus 2.5 m on each side, run on 25 m past its ends. A corner fillet of 4 m is at most 40 m² (a 30° corner), and a traffic circle's ring is under a tenth, so they do not count. |
| X1 | A crossing way over the roadway has crosswalk parts on less than 80 % of its stretch over the roadway. |
| M1 | A lane line, or a centre line with a real source, lies in a space whose lanes have the source `urbanstyle` (a chosen count). |
| K1 | (INFO) The kerb of a subsection is more than 1.5 m from the city's catch basins (the median over 2 or more basins within 6 m of the roadway). With no catch basins in the area the check says "no kerb evidence here". |

The ids A1-A3 are not L1-L3, because L1 and L2 are the checks of layer 1 (the surfaces).

## Results on 2026-10-14 (the builds before these rules were applied)

| Check | Monaco | Broadway × Granville |
|---|---|---|
| A1 | 324 | 86 |
| A2 | 161 | 54 |
| A3 | 251 | 5 |
| J1 | 18 | 0 |
