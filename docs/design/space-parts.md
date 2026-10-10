# The inside of a space: parts, marks and widths

<p class="lead">Every new space (an intersection or a subsection, <code>space.unit</code>) is divided into the parts you see on the street, with the lines painted on it and the width of every edge.</p>

Status (2026-10-08): agreed with Kaveh; built for intersections, roundabouts and subsections; the roadway now comes from SUMO (below). Widths are measured from mapped sidewalks and crossings where they exist (see parts.py); the fixed sidewalk bands of the first version are gone. Built on the network-first spaces
([network first](network-first.md)).

## Parts (`space.part`)

The parts of a unit cover it exactly: no gaps, no overlaps (check U8). Each has a `type`, an `arm` (the road it belongs to, at an
intersection), a `direction` for a lane (`in` / `out` of the junction, or `forward` / `backward` along a subsection), a width where it has
one, and its provenance (2026-10-09; before, one `source` word mixed the two): `source`, where its data comes from (`osm`, `sumo`,
`mapillary`, `urbanstyle` for a default); `method`, how it was obtained (`mapped`: lanes / width tagged; `measured`: from a mapped line, a
crossing, a sidewalk, the kerb; `derived`: SUMO's lanes and junction shapes; `observed`: a Mapillary sign; `estimated`: a default); and `ref`,
the source's own id where there is one (the OSM way of a crosswalk or of the road a lane belongs to, the OSM node of a crossing point). A part of a road (a lane, a shoulder) also carries what is known of its road: `road`, `road_class`, `speed`,
`surface`, `lit`, `road_lanes`, `oneway`, from the road's OSM way; where OSM says nothing, a stated default (50 km/h in built-up areas,
asphalt), labelled as such.

| type | what | where it comes from |
|---|---|---|
| `junction area` | the shared turning area of an intersection, where the arms' carriageways meet | the carriageway minus every arm's own lanes |
| `lane` | one traffic lane, `in` or `out` (intersection), `forward` / `backward` (subsection) | lanes tag, else carriageway width / 3.25 m; two-way roads split either side of the centreline, right-hand traffic |
| `crosswalk` | a pedestrian crossing over the carriageway, 3 m wide | a mapped crossing path; else a crossing point, square across its road |
| `cycle crossing` / `cycle lane` | a cycle track over / along the carriageway, 2 m wide | mapped cycleways |
| `island` | a refuge in the carriageway; a roundabout's central island | island tags (rare); the ring's line |
| `ring` | a roundabout's circulating roadway, one part | the ring's line ± half its roadway, with SUMO's roadway |
| `shoulder` | beside the outer lane, out to the measured kerb: parking or a hard strip | measured kerb minus SUMO's lanes |
| `sidewalk`, `furnishing`, `frontage` | the pedestrian realm: kerb side (1.8 m), building side (1.2 m), the rest | the space minus the carriageway, as `strips.py` bands it |
| `open` | ground beyond the reach of any measurement | the rest |

The **carriageway** is the measured travelway (`space.zone`, measured to the kerb where a sidewalk was found, else lanes × lane width).

At an **intersection**, each arm's lanes are the part of the carriageway that only that arm's road covers (its centreline ± half its
carriageway width); where two arms' carriageways meet, and the turning corners between them, is the junction area. Crosswalks are cut
out of lanes and box. The pedestrian realm falls apart into one **corner** per block corner.

## Marks (`space.mark`)

Lines painted or built on the street: `kerb` (where carriageway meets pedestrian realm), `stop line` / `give-way line` (across an arm's
`in` lanes at the junction side of its approach, where a stop or give-way sign or a traffic signal stands on that arm), `lane line`
(between two lanes of one direction), `centre line` (between the two directions).

## The roadway from SUMO

Status (2026-10-08): built on Monaco. The roadway (lanes and junction shapes) is drawn by **SUMO** rather than built here from bands
around the OSM centrelines, which left steps at the cuts and blobs at complex junctions.

1. The subsections are built first, the classic way: they measure every road's kerbs and its lanes per direction (count and width).
2. duckOSM writes its driving network for SUMO (`duckosm.sumo.to_sumo`: SUMO edge id = duckOSM `edge_id`, the legal turns from its
   `edge_graph`) with those lanes: the median count and width per direction; a tagged bus lane is one more lane at the right
   (`bus lane`), a tagged cycle lane SUMO's bike lane (1.5 m). A road no subsection measured (a roundabout's ring, a junction's own
   link) gets the estimate. One-way roads are centred on their line; a two-way road's directions lie either side of it. `netconvert` joins close junctions into one and rounds the kerb
   corners (`src/urbanstyle/sumo.py`, in our UTM zone).
3. Every unit is then filled from SUMO's shapes: the roadway is SUMO's lanes (each at its width, numbered from the right) and junction
   shapes, closed over the slivers between lanes, plus the **shoulders**: where the measured kerb lies beyond SUMO's outer lane, a
   `shoulder` (parking, a hard strip; at most 2.5 m, stopping 3 m short of a junction). In it, in this order: mapped crosswalks
   (only the pieces that run across a road), a roundabout's island (the ground its ring's line encloses, less half the ring's
   roadway, rounded), the lanes (`in` / `out` of the junction, or `forward` / `backward` along a subsection), the shoulders, and the
   rest of the roadway as ONE part: the `junction area` of an intersection, the `ring` of a roundabout (its circulating lanes are
   painted on it, not separate parts; the ring is the ring's line ± half its roadway, round whatever SUMO's pieces), the
   `carriageway` of a subsection. Then the pedestrian realm out to the buildings as before. Parts from SUMO have `source` = `sumo`.
   The dashboard draws parts without outlines: the asphalt is one surface, and the lines on it are the marks.
   A **tunnel or a bridge** (a space off level 0) is a tube: no buildings bound it, so its space is cut back to its roadway and
   1.5 m beside it (a narrow walkway), not out to open ground; a junction keeps its whole space if the cut would lose one of its
   nodes. Where a road only continues (its OSM way is split there, no junction of ours), SUMO's junction shape is replaced by a
   clean join of the lane ends.
   Where a road only continues, each lane is also stitched into the same lane of the next piece, so lanes and their lines run on.
   A gap narrower than 1.2 m between two roadways, and a pocket under 30 m² the roadway nearly surrounds (85 % of its edge), are
   roadway: no kerb in the middle of the road (unless a refuge island is mapped: `crossing:island=yes`). Sidewalk, furnishing and
   open ground are judged from the kerb of the level's whole roadway, so two neighbouring spaces agree at their border.
   Arrows: a subsection paints them only on lanes of its own road, and no two arrows lie within 1.5 m (two roads mapped on top of
   each other). A crossing point within 6 m of a mapped crossing path is that crossing, not a second crosswalk.
   **Lane counts** come from OSM (`lanes`); where OSM is wrong, a rule in duckOSM's OSM fixes (`osm_overrides/osm_overrides.yaml`
   beside the duckOSM database) corrects it, read here at once (`lane_overrides`).
4. Marks: the kerb; lane lines between the lanes of one direction and the centre line between the two (not across a crosswalk); an
   arrow in the middle of each lane of a subsection; at each junction, for each lane coming in, a turn arrow with a head for each way it
   may go, a stop or give-way line where it enters the junction (a sign or signal nearby; every roundabout entry gives way), and SUMO's
   path through the junction for each move as a guide line (not at a roundabout: arrows round its ring show the way) and a row of
   **`space.turn`** (`unit_id`, `from_edge`, `from_lane`,
   `to_edge`, `to_lane`, `turn` left / straight / right from SUMO's direction, `source` `sumo`, `vehicles`: NULL for all traffic, else
   the classes the move is open to, e.g. `bus,taxi` (duckOSM's `turn_permission` and via-way restrictions, through SUMO's lane
   permissions), `condition`: when a time rule binds, e.g. `Mo-Su 07:00-19:00`). U-turns are left out. Turn arrows show the moves open
   to all traffic. A mark lies in
   the unit it is drawn in: SUMO's junction shape can end beyond a close cut, so an arrow or a stop line may lie in the subsection.

Without SUMO (no `pip install "duckosm[sumo]"`, or no `osm` database attached) every unit is built the classic way. Monaco:
1,181 turns (625 straight, 310 right, 246 left), 27 islands, lanes 2.5-3.75 m (median 3.25), 922 shoulders (median 1.7 m); checks
U1-U9 pass, U10 (roadway steps at cuts) 508 (583 before).

**The lanes entering each junction** (`space.approach`, 2026-10-10): one row per lane coming into a junction, with its number of moves,
the ways it may go for all traffic, whether it has a turn arrow and, if not, why (`no move`, `roundabout`, `for some vehicles only`,
`lane piece under 4 m`, `another arrow in the way`). Reported by `urbanstyle check`, not failed (a missing move may be the law):
U11 lanes with no move at all, U12 approaches with no straight move for all traffic at junctions of 4 or more approaches (at a T the
stem cannot go straight), U13 lanes with a move for all traffic but no arrow. Broadway x Granville neighbourhood: 573 lanes, 541 with
an arrow; U11 6, U12 32, U13 26 (all lane pieces under 4 m).

## Edges and widths

Per intersection arm: total width at the cut, carriageway width at the cut, lanes in / out, sidewalk width on each side. Per subsection:
the same across its middle, and what bounds each side (building faces and their length, or open). Shown in the dashboard panel when the
space is selected; the map then shows exactly its parts, marks and objects.

## Limits

Widths are mostly estimated: in Monaco 45 % of roads carry a lanes tag, 3 % a width tag, 14 a turn-lanes tag. Islands are mapped 3 times.
No parking yet. SUMO assigns lanes to turns from the lane counts alone: `turn:lanes` tags (14 in Monaco) are not read yet.
A crossing way longer than 2.5 × a road's estimated roadway is not used to measure it (it runs over more than that road).
