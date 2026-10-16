# The agreed street rules

Status: agreed with Kaveh on 2026-10-14. Each rule has a check. `urbanstyle check DB` runs the checks at level 0, and a broken rule
is a FAIL with links to the places (`?at=`).

| # | Rule | Check |
|---|---|---|
| 1 | **OSM geometry first.** The lanes of each carriageway lie centred on its own OSM line. The number of lanes is OSM's `lanes`. If OSM gives no number, a two-way road has one lane in each direction, never one shared lane. The width is OSM's `width`, else the number of lanes × the chosen lane width. | A1 |
| 2 | **No object without a source.** A parking lane, a bike lane, a barrier in a median or a shoulder that fills a width is only where OSM or a city says so. | A2 |
| 3 | **The kerb is a result.** The kerb is the outer edge of the lanes and of the items that have a source. Kerb evidence (catch basins, poles, sidewalk lines) only checks the result. It does not move the lanes. One addition (2026-10-16): where no source gives a lane width and the city's catch basins lie beyond the chosen lanes by 0.3 to 3 m on a side, the outer lane on that side widens to them, as one lane that holds parking, drawn with a dashed line at the chosen lane's edge. Not on a ramp or a through road (`_link`, motorway, trunk), and not toward another road within reach (the basins stand in a median's gutter there). The lane count stays OSM's, the lanes do not move. Beyond 3 m nothing changes and K1 reports it. | A1, K1 |
| 4 | **Connections only at shared OSM nodes.** Two roads that share no node stay apart, also when they touch. | J1 |
| 5 | **Junctions from the network** (`junctions.md`, `sections.md` rules 1-4). A junction is only at a node where 3 or more road ends meet. Its core is where its arms overlap, each arm reaches to its stop line and is cut square across its line there, and its corners are round. A road under 40 m, or a `_link`, between two junction nodes is a connector: it belongs to one intersection with both nodes (2026-10-16). It is never "the street left over" between sections, and never a circle round the node. | J1, J2 |
| 6 | **Blocks follow the footways** (`blocks.md`), piece by piece, with sharp corners. A block never covers a carriageway. A pedestrian street lies inside a block. | A3 |
| 7 | **Crosswalks from OSM.** Every crossing way over the roadway, and every crossing node on a road with no crossing way, is a crosswalk part cut from the lanes. Its paint comes from `crossing:markings`: zebra bars, two crossing lines, or none. A crossing with no markings mapped gets the part and no paint. | X1 |
| 8 | **Lines carry the lane count's source.** No source maps a painted line. A lane line is drawn only between lanes OSM counts (`lanes`), with that source and method `derived`. The centre line between the two directions is drawn also where the count is chosen, as urbanstyle's own (`chosen`). | M1 |
| 10 | **Sections between junctions; one frame per section** (`sections.md` rules 5-8, 2026-10-16). A section is the road from junction to junction, whatever OSM ways it is made of; it is cut into subsections where the paint changes. Its frame is one width for the whole section: the lanes and the strips a source gives at its widest place. The lanes stay centred on their own way's line; the rest of the frame is paved roadway with no lane. No line is moved sideways and no kerb tapers, except at a `real` change (an OSM `width` on both sides), where the frame changes with a kerb taper over 15 m (chosen). Every tag change along a section is classified first (`sections.md` section 3: turn pocket, merge, fork, parking, real, unknown, none) and `space.change` keeps the row. A lane that ends narrows to nothing over 15 m (chosen) inside the frame. | A1 (0.5 m), R1, J4, R4 (INFO) |
| 11 | **Block edges follow the footway.** A block side runs 1 m behind the footway line, simplified by 0.5 m: straight where the footway is straight, bending only where it bends, never with the road. | B6 (INFO) |
| 12 | **A barrier continues from a bridge landing.** A bridge whose corrections name a median barrier keeps it on the ground along the landing way's lanes, on the side where a roadway of the other direction runs within 8 m, until that roadway ends or a junction begins. Source `urbanstyle corrections`, method `continued`. The strip it runs along is an island, not paved roadway. | – |
| 13 | **Not every shared node is a junction.** The road ends at a node are paired into streams (an end continues into the end most opposite to it, within 45°). The node is a junction where an end has no continuation, where two ends continue into one (a merge or a fork, a Y, whatever the angle; `sections.md` rule 2, 2026-10-16: until then a Y was a joint inside a section) or where two streams cross. Two streams that only touch (two one-way lines of one street drawn into one node) make no junction. | J1 |
| 14 | **A merge or fork keeps the far kerb** (`sections.md`, the rules from the spots, 1). The section whose lanes are the through arm's plus the merging arm's keeps the through arm's kerb away from the merging arm: its lanes sit half the merging lanes' width off the OSM line, recorded in `subsection.left_extra`. The one lane move. | A1 (expects it) |
| 15 | **Islands.** An island begins where the strip between two frames is 2 m wide; a thinner bare tail is paved roadway, cut square. A paved strip inside an intersection is junction area. A walking piece touching no block that touches an island is that island's, across spaces. Meters give parking only where they stand. | U9, K2 |
| 9 | **Kerb evidence reports, it does not move.** A city's catch basins stand at the kerb. Where our kerb is far from them, the check says so, and the lanes stay where OSM puts them. | K1 |

## The checks

| Check | Fails when |
|---|---|
| A1 | The middle of a carriageway's lanes (one OSM way in one space) is more than 0.5 m from its OSM line. The value is the median over cross lines every 5 m, outside the 15 m transition at each joint. (2 m until 2026-10-16, the tolerance of the continuity shift.) |
| J3 | A connector (a road under 40 m, or a `_link`, between two junction nodes) has more than 1 m of its line outside every intersection space and every bridge deck. |
| J4 | (INFO) The number of tag changes along the sections (`space.change`), with the count per class; the links go to the `unknown` ones first. |
| R1 | Two subsections of one section meet with a step over 0.1 m in the roadway's edge. A joint at a `real` change does not count. (INFO until 2026-10-16.) |
| A2 | A parking lane or a cycle lane has the source `urbanstyle`, so no real source gives it. |
| A3 | A road line at level 0 (a street class) has a stretch longer than 2 m with no roadway under it (lane, junction area, carriageway, bridge deck, bus lane or zone, parking, shoulder, cycle lane, crosswalk). The area's edge (2 m) is not counted. |
| J1 | An intersection at level 0 holds no junction node: a node where 3 or more road ends meet (a road that runs through the node counts 2). |
| J2 | A junction area has a piece larger than 40 m² and than a tenth of the junction outside its arms' bands. An arm's band is its subsection's line as drawn, as wide as its roadway plus 2.5 m on each side, run on 25 m past its ends. A corner fillet of 4 m is at most 40 m² (a 30° corner), and a traffic circle's ring is under a tenth, so they do not count. |
| X1 | A crossing way over the roadway has crosswalk parts on less than 80 % of its stretch over the roadway. |
| M1 | A lane line, or a centre line with a real source, lies in a space whose lanes have the source `urbanstyle` (a chosen count). |
| K2 | (INFO) A kerb line ends where no other kerb and no crosswalk is within 0.3 m. |
| K1 | (INFO) The kerb of a subsection is more than 1.5 m from the city's catch basins (the median over 2 or more basins within 6 m of the roadway). With no catch basins in the area the check says "no kerb evidence here". |

The ids A1-A3 are not L1-L3, because L1 and L2 are the checks of layer 1 (the surfaces).

## Results on 2026-10-14 (the builds before these rules were applied)

| Check | Monaco | Broadway × Granville |
|---|---|---|
| A1 | 324 | 86 |
| A2 | 161 | 54 |
| A3 | 251 | 5 |
| J1 | 18 | 0 |
