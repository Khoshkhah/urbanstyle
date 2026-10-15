# Blocks first: blocks, then sections, intersections and subsections

<p class="lead">Divide the ground at street level into blocks first. Then divide the street between them: one section for each pair of
neighbouring blocks, cut at two positions; the rest of the street is the intersections; a section is divided further into subsections
where its cross-section changes.</p>

Status: agreed 2026-10-10 and tested on Broadway × Granville (`scripts/blocks_test.py`, page `viz/broadway-granville-neighbours.html`).
**Step 1 is built** (2026-10-10): `blocks.py` makes `space.block` and `space.block_side` in every build; `urbanstyle check` reports B1 and
B6; on Broadway × Granville 51 blocks (436,540 m²), B1 3 buildings (59 m²), B6 47 of the city's 51 blocks matched (median overlap 0.97),
the same as the test. **Steps 2-4 and the inside are built too** (2026-10-10, `division.py`): at level 0 the street spaces (`space.unit`)
are the sections' subsections and the intersections, no longer `spaces.py`'s, and their parts are strips parallel to each subsection's
axis, no longer `parts.py`'s (see "The inside of a subsection and an intersection" below). Subsections are cut where the carriageways
or lanes change; cuts where the width or the frontage changes are not built yet.

## In short

| word | what it is |
|---|---|
| **block** | the land between the streets: the area the street lines enclose, less each street's half width. Every building is wholly inside one block |
| **share** | every point of the street belongs to the block nearest to it; that is the block's share of the street |
| **middle line** | where two blocks' shares meet: the line down the middle of the street between them |
| **neighbours** | two blocks that face each other across one street, with only street between them, for a stretch at least as long as the street is wide |
| **section** | the street between two neighbouring blocks, cut at two positions: 3 m inside each end of the stretch where they face each other |
| **intersection** | the street that is in no section: the open ground between the block corners, and 3 m into each street arriving there |
| **subsection** | a piece of a section between two cuts where its cross-section changes (lanes, width, what is beside it) |

## Why

Until now the street was cut from the road network: a cut across every road that arrives at a junction, at the block corners
([Network first](network-first.md)). The road network is not a clean map of streets. A divided street is two lines, one junction is
several nodes, and ramps add more. Each of these made its own cut, and two cuts that nearly coincide or cross leave a sliver. Around
Broadway × Granville the last version of that test had 18 pieces narrower than 2 m, sections with no cut or one, and crossing cuts on
Fir and Hemlock, where each street is drawn as two one-way carriageways. Every fix added a special case.

The blocks do not have this problem: a divided street has one block on each side, like any other street. So the road lines are used
only to make the blocks, and the street is divided from the blocks alone.

Two other ideas were tried and rejected:

- **Grow each road's strip until it touches a building.** Buildings stand back from the property line (here a median 1.7 m, a quarter of
  them 3.9 m or more), and 55 of 226 street sides have no building at all (parks, car parks, construction sites). The street took 35,863 m²
  of the city's block ground, against 5,008 m² with the rule below.
- **Use a city's block outlines as input.** See [Cross-validation](#cross-validation-with-a-citys-blocks): they cut 114 of OSM's buildings
  and have 251 m of our streets inside them. Our blocks are the method everywhere; a city's blocks only check them.

## Step 1: blocks

1. **Bounding roads.** OSM's public streets at level 0: motorway down to residential, living street and pedestrian street, with their
   links. Service roads (alleys, driveways, parking aisles), paths and rail do not bound blocks: an alley lies inside its block. A road
   on a deck at level 1 bounds blocks only when nothing at ground level passes under it (a temporary deck over works, not a bridge).
2. **Chains.** The bounding roads joined end to end between junctions, with OSM's small wiggles taken out (simplified by 1 m).
3. **Faces.** The areas the chains enclose, closed by the edge of the area.
4. **One edge per street side.** Each side of each chain gets **one distance** from the road line, so the block's edge on that side runs
   parallel to the road. The distance comes from the best source that has it, measured on lines square to the road every 5 m, inside
   that face only:
   - **the sidewalks** (2026-10-14: first, because most areas, Monaco among them, have no parcels; one rule reads every area the same
     way): the median distance to OSM's sidewalk lines that run along the road (within 35°), plus 1 m (a sidewalk is drawn along its
     middle), when at least 3 lines reach one. A sidewalk line counts only when it is at most 8 m beyond the carriageway (OSM's lanes ×
     3.25 m): there is room for a parking lane and a verge, but a park path further away is not a sidewalk (2026-10-14);
   - **else the parcels** (a city's property lots, `space.parcel`): the median distance to the nearest parcel, when at least half the
     lines reach one;
   - **else the road class**: half the usual right-of-way for that class (living street 8 m; residential, unclassified, tertiary and
     pedestrian 10 m; secondary 12 m; primary 15 m; trunk 16 m; motorway 18 m).
   
   Each line's hit is taken only when it is within 1.5 × the class's half width, so a parcel or sidewalk of the next street does not count.
   **The edge follows the sidewalks piece by piece** (2026-10-14): each line square to the road (every 2.5 m) ends 1 m behind the
   sidewalk it reaches, the median of it and its two neighbours (one line that reaches another path makes no spike). Within 10 m of a
   junction (`CORNER_M`) the edge goes straight on at the distance it has there, so two edges meet in a sharp corner: an edge rounded
   round a corner's sidewalk left the division no intersection there (i0-877917415).
5. **No parcel is cut** (2026-10-10). The distance is pulled in to the nearest parcel on that side, so a block holds its parcels whole.
   Where the sidewalks set the side (2026-10-14), a parcel does not move it: the sidewalks are the edge.
   **Where parcels set the side, an OSM building does not move it:** the parcel line is surveyed, and an OSM outline (drawn from an
   aerial photo, a tall building's roof shifted) can be a few metres off. Such a building is drawn whole and reaches over the edge
   (check B1 counts them: 99 at Broadway × Granville, 1,771 m²). Where no parcel sets the side, the nearest building still pulls it in,
   but only by more than 1.5 m (`ROOF_M`, 2026-10-13): OSM often draws a building by its roof, which reaches over the sidewalk
   (Avenue Pasteur, Monaco, building w49209427, seen in Street View). A building nearer by 1.5 m or less does not move the edge.
   Result: 194 of 201 sides set by parcels; the match with the city's blocks (B6) 47 of 51, median overlap 0.99 (was 0.97).
6. **Sharp corners.** Each edge line is continued past the junction, so two edges meet in a corner, as two parallel offsets do. The
   city's own blocks have sharp corners too: over 320 corners of rectangular blocks, the median rounding is 0.02 m.
7. **What is a block.** What is left of each face, less its parts narrower than 8 m, is a block if it is at least 400 m². A part
   narrower than 8 m (the strip between a divided road's two carriageways, also as a thin tail of a wider piece) is street
   (2026-10-14: the two one-way ways of Fir Street made a block 190 m long and 2.7 m wide).
8. **Where a city has parcels, the block is its parcels** (2026-10-11). Only in a face where no side is set by sidewalks (2026-10-14). A parallel edge is one straight line, so where the parcels
   along it step back (land a city keeps for its street in front of some lots), the block held ground that no parcel holds. So, in each
   face:
   - take the parcels that lie more than half in the face (for a parcel that the area's edge cuts: half of its part inside the area);
   - join them and close every gap narrower than 12 m (a back lane, a slit between two parcels): grow by 6 m, then shrink by 6 m;
   - that shape is the block, and the street is all of the face that is not in a block.

   The block's edge is the parcels' front. It crosses a lane's mouth in a straight line from parcel corner to parcel corner, and a lane
   or a slit stays inside the block. If the joined parcels cover less than 80 % of the block from the parallel edges (a park, a rail
   yard with no parcel), that face keeps the parallel edges. `space.block_side.basis` is `parcels (joined)` for such a side.

   Until 2026-10-11 the street grew into its blocks after the cuts, up to the parcels' front ("step 3b"). Each street piece grew
   separately, so each special case (a lane mouth, a slit, a corner strip, a crumb) needed its own rule. It is removed: the parcels
   now set the block before the cuts, and the cuts need no change.

   With sidewalks first (2026-10-14), Broadway × Granville: 51 blocks (454,828 m²); 201 street sides, 186 from sidewalks, 11 from a
   parcel, 4 from the class; B1 113 → 25 buildings over an edge; B6 47 of 51, median overlap 0.93 (was 1.00). The edges fall within
   about 1 m of the parcels' on almost every block. The block b0-w74226311r.2 (508 m²) is gone.

   Broadway × Granville: 52 blocks (427,492 m²), none in more than one part; 217 street sides, 210 from the joined parcels, 5 from a
   parcel, 2 from sidewalks; the street is one piece; B6 47 of the city's 51 blocks, median overlap 1.00. The four not matched: two
   slivers of a city block at the area's edge (547 m², 226 m²), and two city blocks that an OSM road divides into two of ours.

Which side of a road a face lies on is tested at the middle of the road's stretch along that face. A road that runs past the edge of
the area has its own middle outside the face; tested there, the road got no strip, and the blocks closed over the street's end.

## What lies inside a block: car parks and lanes

A block divides land, not traffic: its edge is where the public street ends. Whatever is not a public street lies inside a block, even when
one can drive through it from one street to another.

- **OSM's tag decides.** Aisles and driveways (`service=parking_aisle`, `driveway`) and back lanes (`service=alley`) are inside a block. A
  way tagged as a public street (`residential`, `unclassified`, ...) is a bounding road and divides the block, even where it runs through a
  car park. Vancouver's own blocks do the same: 86 % of the length of its lanes lies inside its blocks.
- **An off-street car park** (`space.lot`) is a plot of its block (layer 0), its surface a `car park` (layer 1). Around Broadway ×
  Granville: 16 car parks, 8,080 m²; 14 wholly inside a block, 2 crossing a block's edge (40 m² of 1,129 m², 5 m² of 268 m²), none in the
  street.
- **A car park over the block's edge** (proposed, to be agreed): the part outside the block is street. The edge is the property line, and
  OSM often draws a car park over the sidewalk. Unlike a building, a car park does not pull the edge in: drawn 1-2 m over the line, it
  would move the whole street side.
- **A multi-storey car park** is a building (`building=parking`): wholly inside its block. **An underground one** is at level -1, its own
  level; its ramps are links between levels.
- **Parking in the street** (a parking lane, street-side bays) is not in a block: it is a band of the roadway (layer 2) or a parking zone
  lying on it (layer 3).

**Connections (access).** A car park or a lane that opens onto two streets connects them. The connection is kept, without dividing the
block:

- in the street, each opening is a **driveway apron** in the section it opens onto (a part of the sidewalk, as in `parts.py` today), and
  the section lists its **access points**;
- the car park or lane lists its **access**: each opening, the section it opens onto and the OSM way of its driveway or aisle. A car park
  with two openings reads "connects section A and section B";
- as a route for traffic, the connection belongs to the road network, not to the ground: SUMO's network leaves parking aisles out today;
  adding them for through-traffic would not change the blocks.

**Open car parks.** Many surface car parks have nothing along the street (no fence, wall or kerb): one can walk or drive in from any
point. Such a car park still lies inside its block: the block's edge is the property line, and being open does not make the land
street. (Angle-parking bays on the city's own land, outside the parcels, are street already: a parking zone, as above.)

- **Each side of a car park that faces a street has a boundary type** (the glossary's `boundary`):
  - `open`: no barrier along it. Its access is the whole side, a stretch of the section it faces, not a point;
  - `closed`: a mapped fence, wall, hedge or line of bollards runs along it (OSM `barrier=*`). Its access is its driveways and the gaps
    in the barrier, as above.
  
  Where no barrier is mapped, the side is `open` (urbanstyle's own, `chosen`); it is `closed` only on evidence.
- **The street knows it.** An open side is a frontage of its own (`car park, open`), so the stretch of street in front of it is a
  subsection of its own (step 5). Its sidewalk is flush there (no kerb) where the data shows a lowered kerb along it.
- **Connections.** An open car park touching two streets reads "open to section A along 40 m, open to section B along 25 m"; a closed one
  lists its openings.

## Step 2: neighbours

1. **Shares.** Every point of the street belongs to the block nearest to it (a Voronoi diagram of points 1 m apart along every block's
   outline). The outside of the area is one more "block", but only where a street runs **along** the edge of the area. Where a street
   **leaves** the area (the edge crosses the street, an opening shorter than 40 m), the outside has no share: the two blocks' shares run
   on to the edge.
2. **Middle line.** Where two shares meet. Pieces whose ends are within 5 cm are one line (rounding gaps).
3. **Facing.** Along the middle line, every 0.5 m, a line square to it is cast to both sides. It **faces** where the first thing it meets
   on one side is block A and on the other block B, and it meets each on a side that runs along the middle line (within 30°). Past a
   corner, the line meets the block's next side at a slant: that is not facing.
4. **Street neighbours** face each other over a stretch long enough for a section (step 3). **Corner neighbours** only touch: their
   shares meet, but they do not face each other for long enough. Diagonal blocks across a junction are corner neighbours; they get no
   section, and their ground is the intersection.

## Step 3: sections

1. Each stretch where two blocks face each other is cut at **two positions, 3 m inside each end**. The 3 m (`ARM_M`, chosen) is the part
   of each arriving street that belongs to the intersection: its crosswalk and stop line. An end at the edge of the area gets no cut;
   the section runs on to the edge.
2. A cut is a straight line square to the middle line, from block A to block B.
3. **A section is at least as long as its street is wide** (length between its cuts, width block to block at its middle). A shorter one
   is part of the junction: it gets no cuts and its ground stays in the intersection. A section cut short by the edge of the area stays
   a section: the street goes on outside.
4. The street is divided by all the cuts. A piece holding the middle of a facing stretch is that pair's section. A piece that
   meets fewer than three sections (the end of a street at the edge of the area) joins the section it shares the longest edge with.

## Step 4: intersections

The rest of the street. Each piece meets three or more sections. Its edges are the block corners and the cuts of the streets arriving
there, so it reaches 3 m into each arm.

## Step 5: subsections (designed, not built)

A section is one strip between two blocks, with one direction: its middle line. A subsection is a stretch of it with one cross-section.

1. **Where to cut.** Along the middle line, the section is cut where, for at least 12 m:
   - the **lanes** change: the number of lanes, their use (bus, turn, parking) or one-way (OSM's lane tags, SUMO's lanes);
   - the **width** changes: block to block, by more than 1 m;
   - the **frontage** changes on either side: a building, a car park, a park, a construction site or a yard begins or ends (layer 0's
     plots, [Layers](space-layers.md)).
2. **The cut** is straight, square to the middle line, block to block, as the section's own cuts.
3. **No short pieces.** A subsection is at least 12 m long; changes closer together are one cut, at their middle. No cut is closer than
   12 m to the section's own cuts.
4. A section with no change is one subsection.

## The inside of a subsection and an intersection (built)

Each layer is made from its parent's shape by lines parallel to its axis, never by clipping polygons against each other, so it has no
crumbs: a strip under 5 m² joins its neighbour.

- **A subsection**, across its axis (the middle line between its two blocks), from one block to the other: pedestrian realm, kerb,
  roadway, kerb, pedestrian realm.
  - **Kerb (top-down, 2026-10-10)**: one kerb on each side of a whole **section**, shared by its subsections, from the evidence along
    the section's whole length: OSM's and the city's sidewalk lines (the kerb 1 m before them), the city's catch basins (in the gutter, the
    kerb 0.3 m behind them); the kerb stays 0.4 m on the road's side of the city's poles, trees and parking meters. The evidence nearest
    the road holds (the median of what lies within 2 m of it); a footway on a median is no evidence. Else the carriageway's edge. The
    side of a sidewalk line or a catch basin comes from the carriageways, not from the axis (2026-10-11): the axis is the middle line
    between the blocks, and a street off that middle can have a sidewalk near the axis. The
    subsections share the section's axis. Broadway × Granville: 237 of 286 kerb lines measured; the roadway's edge at the joints between
    subsections moves by a median 0 m (was 0.91 m), 4 joints over 0.5 m (was 20).
  - **Roadway (top-down)**: the width between the kerbs is measured first; the cross-section that fits it best is chosen: 1-6 travel
    lanes (3.0-3.7 m), a parking lane (2.2-2.6 m) and a bike lane (1.5-2.0 m) on each side or not, a gutter (0.3 m) at each kerb. The
    evidence is a hint, not a fact: OSM's lane count (else one lane each way, a weaker hint), OSM's parking and cycleway tags, the city's
    parking meters near a kerb, its painted or protected bikeways. Each element is widened within its range to fill the width; what is
    left is the gutters. Each lane's `rule` says the fit ("fit: 2 lanes (OSM: 2), parking left, parking right"); `space.width.osm_lanes`
    keeps OSM's count to compare (Broadway × Granville: the fit agrees with OSM on 74 of 86 subsections).
  - **Pedestrian realm**, NACTO's zones from the kerb out: **buffer** (`furnishing`: where trees and poles stand, else 1 m, chosen,
    where no sidewalk is mapped), **clear path** (`sidewalk`: 1.8 m around OSM's sidewalk line, else after the buffer), **frontage**
    (the rest to the block, if at least 0.75 m).
- **An intersection**: at each block corner, the pedestrian corner is the ground beyond both arms' kerbs (on that block's side); the
  rest is **one junction area**; the kerb's corner is rounded by 4 m.
- **Marks** (2026-10-11), each stored as its middle line and drawn at its width (`parts.LINE`):
  - kerbs; lane lines (dashed) between lanes in one direction, centre lines between the two directions, and a solid **edge line**
    between the travel lanes and a parking or bike lane;
  - a **stop line** 1 m before the end of each section at an intersection, across the lanes going toward it;
  - **crosswalks**: for each marked OSM crossing (a crossing way, else a crossing point with no way within 6 m), a band 3 m wide
    over the roadway and its zebra bars across it (0.5 m wide, 0.5 m apart). They lie on the lanes and the junction area and cut
    nothing. An unmarked crossing (`crossing=unmarked`, `crossing:markings=no`) gets no bars;
  - **arrows**: a turn arrow before the stop line of each lane that comes into a junction (its heads from SUMO, below); a straight
    arrow in the middle of each lane of a subsection that is 20 m or longer. No arrow touches a crosswalk.
- **Lanes across the joints.** Every edge in a subsection (kerbs, medians, the line between two carriageways, lanes) has a value at each
  of its two ends and runs straight between them. Two subsections share the values at their joint. One OSM way in one section gets one
  fit, made from the median width over its subsections. A median that meets the line between two carriageways closes onto it; a median
  on one side only closes at the joint (a carriageway joins). Check R1 counts the joints where the roadway edges differ by more than
  0.1 m: 17 before, 0 after.
- **Every item meets its continuation at a joint** (2026-10-11, `division.join_lanes`, check R4). The kerbs and medians alone do not
  make the lanes meet: each subsection puts its lanes in the middle of its own room, so a lane moved sideways where a neighbour had
  other lanes, another carriageway or other shoulders. Now `division.py` first makes the layout of each subsection (its items and their
  edges at its two ends), then joins each joint, then makes the parts:
  1. The items of the two sides (lanes by direction of travel, cycle lanes, parking) are matched in order, with the most overlap.
     A lane moved sideways by less than 1 m (`JOIN_M`) still matches. Each pair gets the mean of its edges on the two sides.
  2. Between two pairs, what matters is whether an island lies between them on each side (one carriageway, or two that meet at a
     painted line, is no island):
     - no island on either side: the two pairs meet at one point, and items on one side only start or stop there at zero width (a
       **taper**); items on both sides (a lane that becomes a cycle lane) each fill the same room;
     - an island on both sides: the island stays; an item inside it on one side only opens at zero width in its own middle (a ramp
       lane that joins between two carriageways);
     - an island on one side only: it closes at the joint (as in pass 2), unless the other side has items there, which then fill the room.
  3. Each median then lies between the items of its two carriageways.

  The same applies where two sections of one street meet with no intersection between them (their spaces share 2 m of edge or more,
  their axes there are within about 30° of one line); there the kerbs also meet half way. The offsets of one side are converted to the
  frame of the other (`t_A = ±t_B + c`). A taper's `width_m` is its full width, and its `rule` says that it is a taper. A strip under
  5 m² never joins a lane or a shoulder, and a shoulder never joins another strip, so the lanes keep their shape to the joint.
  Broadway × Granville: R4 234 -> 5 edges with no partner; R1 1 -> 0; R2 19 -> 16; R3 1 -> 1; no hole over 1 m² and no lane wider
  than 5 m anywhere (before and after).
- **A section's axis is OSM's road line** (2026-10-14). The middle line between the two blocks still finds the section (where its two
  blocks face each other, and its cuts), but the lines inside it (kerbs, lanes, painted lines) are offsets of the OSM line of the
  section's main road (the road with the most length in it), clipped to the section. Before, they were offsets of the middle line: where
  one block's edge is slanted (a set-back, a plaza, a car park), the middle line slanted and every lane with it, although OSM's road runs
  straight (West 6th Avenue, s0-w23189661l.6~w74226311r/3: lanes 1.3 m off, 2° off; Kaveh, 2026-10-13). The blocks now set only how
  far each side reaches. Where the road's line covers less than 80 % of the section (`ROAD_AXIS_SHARE`), the middle line stays the
  axis. Offsets are to the millimetre (`moved`): an offset of 0 is the axis itself (GEOS failed on an offset of 8e-12 m).
  Vancouver: R4 16 -> 9, R1 3 -> 2, U12 6 -> 3, U10 6 -> 10, R3 2 -> 3 (INFO).
- **A crossing point with no road line through it** (OSM cuts Pine Street at the Arbutus Greenway; the crossing is a node of the greenway
  only) takes its direction from the path it lies on: the walk goes along the path, across the road. A marked crossing on a path where
  no roadway is near gets its zebra bars across that path (`PATH_CROSS_W_M`, 4 m, where OSM gives no width).
- **A section's axis follows its road past the middle between the blocks** (2026-10-11, `division.follow_road`). Where a block steps back
  (the entrance of a service road), the middle line between the two blocks bends away or stops 5 m or more before the section's end.
  The axis then runs on along the OSM line of the section's main road, moved to start at the axis end, to the section's edge (30 m at
  most). Before, the lanes ran straight on past the end of the axis and left the road where it bends (West 5th Avenue at Granville
  Street: the lane ended 4 m beside the next section's lane).
- **Roads only for buses** (2026-10-11). duckOSM does not put a road only for buses (`vehicle=bus`, `psv=yes`) in its driving network,
  and urbanstyle stores it as a `walkway` of street class. `division.py` takes it as a carriageway: its lanes and `oneway` come from its
  own OSM tags (`lanes`, `lanes:forward`, `lanes:backward`, `oneway`), and it is no sidewalk line for the kerbs. Before, it had two lanes
  in two directions (`chosen`) and its own line set a kerb (West 5th Avenue west of Granville Street).
- **A mapped lane count is never changed** (2026-10-11). Where OSM has a `lanes` tag (read from duckOSM's driving network), the fit
  keeps it; the width decides only the lane widths and the parking and bike lanes that OSM does not map. Where the width cannot hold
  OSM's lanes, our kerb is probably wrong: check R3 lists it. Carriageways side by side with no median share their roadway by their
  lane counts. Where OSM's lane count changes (a turn lane before a junction), the street is cut, also for a piece of 5 m to 12 m.
- **Kerbs never inside OSM's carriageway**: a kerb, and a block made from parcels, stay at least half of the carriageway's lanes x 3.0 m
  from its OSM line; poles on a median do not pull the kerbs in.
- **A two-way street one lane wide** (a yield street) has one lane for both directions (`direction = both`), and no arrow.
- **Bus zones.** Where an OSM bus stop (joined to the GTFS timetable by its number, `ref` = `stop_code`) or a GTFS stop that OSM does not
  have stands within 5 m of a parking lane, the parking lane is a `bus zone` from 20 m behind the stop pole to 2 m past it, in the
  travel direction. Its `rule` gives the routes and the departures.
- **Driveways.** Where a road inside a block crosses the pedestrian realm of a subsection (an alley; OSM's driveways and parking aisles
  from duckOSM's driving network, which `space.element` leaves out), or at an OSM parking entrance within 15 m of a car park, the realm
  there is a `driveway` and the kerb is open. On the ground (layer 0), an OSM driveway inside a block is a drivable strip of kind
  `alley` (OSM's `width`, else 3.5 m), after the buildings and the car parks.
- **SUMO on our lanes.** After the lanes are fitted, duckOSM's driving network goes to SUMO (`sumo.network`) with our lane count and
  width for each direction of each OSM way, where its edge runs. SUMO decides which lane goes on to which. Each connection is a
  `guide line` (`source sumo`) from our in-lane, at its stop line, to our out-lane where it leaves the junction, a curve between the two
  directions, pulled toward the junction's middle where it would leave the roadway (check R2); a move that passes SUMO edges inside our
  junction (a divided road crossing another) is followed to its out-lane. A SUMO edge finds our lane by geometry (it ends in our
  junction, runs the lane's way, lane number from the right), not by OSM way id; `space.turn` holds it (the road piece and the lane from the right, as `parts.py` wrote them). The heads of each turn arrow
  are its lane's moves (`osm+sumo`, `mapped`, where OSM has `turn:lanes`). `space.approach` lists every lane that comes into a junction
  (checks U11-U13). Broadway × Granville: 489 guide lines; of the 238 lanes that come into a junction, 215 have a move.
- **Where each part comes from.** Every part has `source`, `method` and `ref` for what it is, `width_source` and `width_method` for its
  width, and `position_source`, `position_method` and `position_ref` for what set its edge (the kerb, the block's edge). For example: a
  lane is `osm / mapped` (`w… lanes=2`) where the width holds OSM's count, `urbanstyle / derived` where the width holds another count,
  `urbanstyle / chosen` where OSM has no `lanes` tag; a parking lane is `vancouver / mapped` (the meters' ids) or `osm / mapped` (the
  tag), else `urbanstyle / derived` (the width holds it); a kerb is `measured`, with the OSM sidewalk ways and the city's catch basins,
  poles, trees and meters it came from. Broadway × Granville: 807 parts from OSM, 239 from the city, 9 from GTFS, 668 urbanstyle's own
  (mostly the gutters, the pedestrian corners and lanes where OSM has no lane count).
- **A deck at level 1 that crosses nothing at ground level** (Broadway over the subway works) is the street at ground level, as for the
  blocks; its old level-1 spaces are dropped.

Broadway × Granville, level 0, before (cut from the road network, `parts.py`) and after:

| | before | after |
|---|---|---|
| spaces | 352 | 164 (124 subsections, 40 intersections) |
| parts | 5,845 | 1,314 |
| parts under 5 m² | 1,739 | 0 |
| parts thinner than 1.5 m | 1,011 | 214 (shoulders 0.3-1.5 m wide: the gutter, on purpose) |
| street surfaces (layer 1) in several pieces | 277 of 666 | 0 of 612 |
| edges under 30 cm in the parts | 28,634 | 1,253 |
| U10: cuts where the roadway differs on the two sides | 96 | 2 |

Every check on the spaces, the parts, the ground and the surfaces passes (U1-U9, G1-G2, L1-L2).

## Blocks in the layers

Blocks first changes how [layer 0](space-layers.md) is built, not what the layers are:

```
the area (level 0)
├── blocks                    the land
│   └── water, rail, square, structure, green, plot, path     the land rules of layer 0, inside each block
└── the street                everything outside the blocks
    ├── section               between two neighbouring blocks
    │   └── subsection        the layer-0 street item
    └── intersection          the rest of the street, also a layer-0 street item
```

- Blocks and the street cover the area with no gap and no overlap. G1 (`unknown` ground) can be left only inside a block.
- A block is a group (as a street name group is), not a layer: each land item names its block, each street item its section.
- Layers 1-5 sit inside each subsection or intersection. A subsection is cut where the lanes, the width or the frontage change, so its
  lanes (layer 2) are whole items from one end to the other, and its surfaces (layer 1) divide it across: roadway, pedestrian realm,
  median, verge. Overlays (layer 3) may lie across a cut and name what they lie on; markings and objects (layers 4-5) name the
  subsection or intersection they are in.
- Other levels (bridges, tunnels) have no blocks: their street follows the deck or the tube.

## Ids

The test used each piece's centre point as its id, which changes when anything moves. Proposed stable ids:

| item | id | example |
|---|---|---|
| block | `b<level>-w<way><side>`: the smallest OSM way id among its bounding roads, and the side of that way it lies on (`l` / `r`); `.2`, `.3` ... where one way bounds several blocks on that side, in order of their centres (built) | `b0-w132047930l`, `b0-w132047930l.2` |
| section | `s<level>-<block a>~<block b>`, the two blocks in order; `/k` when one pair has more than one | `s0-w5045123l~w5045180r` |
| intersection | `i<level>-<smallest OSM node id inside it>` (as today) | `i0-11102738098` |
| subsection | `<section id>/<k>`, k from the section's start | `s0-w5045123l~w5045180r/2` |

## Values

All are urbanstyle's own; none comes from a source.

| value | | method |
|---|---|---|
| a chain is simplified by | 1 m | chosen |
| lines square to the road, every | 5 m | chosen |
| looked for out to | 25 m | chosen |
| a hit counts within | 1.5 × the class's half width | chosen |
| the back of a sidewalk | its line + 1 m | chosen |
| a sidewalk line counts within | 8 m beyond the carriageway (`SIDEWALK_ZONE_M`) | chosen |
| half right-of-way by class | living street 8 m; residential, unclassified, tertiary, pedestrian 10 m; secondary 12 m; primary 15 m; trunk 16 m; motorway 18 m | chosen |
| a block is at least | 400 m², 8 m wide | chosen |
| parcels are closed across gaps narrower than | 12 m (grow 6 m, shrink 6 m) | chosen |
| the joined parcels set the block if they cover at least | 80 % of the block from the parallel edges | chosen |
| points along an outline for the shares | 1 m apart | chosen |
| facing tested every | 0.5 m | chosen |
| facing: a side runs along the middle line within | 30° | chosen |
| a street opening at the area's edge is shorter than | 40 m | chosen |
| an intersection reaches into each arm | 3 m | chosen |
| a section is at least | as long as its street is wide | derived |
| a subsection is at least | 12 m (designed) | chosen |
| a width change counts from | 1 m (designed) | chosen |

## Checks (proposed)

| check | what | today |
|---|---|---|
| B1 | no building cut by a block's edge (built, reported) | 3 buildings, 59 m², all at the edge of the area or the Granville ramps |
| B2 | the street pieces cover the street exactly: no gap, no overlap | 0, 0 |
| B3 | no piece narrower than 2 m | 0 |
| B4 | every section ends at two cuts, or at the edge of the area | yes |
| B5 | every section at least as long as its street is wide (except at the area's edge) | yes |
| B6 (info) | how well our blocks match a city's blocks, where it has them (built: `space.city_block`, from the unit's city file) | 47 of 51, median overlap 0.97 |

## Cross-validation with a city's blocks

Decided 2026-10-10: our blocks are the method in every city; a city's block outlines (Vancouver's `block-outlines`) are used only to check
them, never as input. A city's parcels may still set the block's edge (step 1).

Broadway × Granville:

| | the city's blocks | ours |
|---|---|---|
| blocks | 51 | 51 (436,540 m²) |
| city blocks matched by one of ours (overlap ≥ 0.8) | | 47 of 51; overlap median 0.97, lowest quarter 0.96 |
| distance between their edges and ours | | median 0.3 m; 90 % within 1.4 m |
| OSM buildings cut by a block's edge | 114 (2,238 m²) | 3 (59 m²) |
| our bounding roads running inside a block | 251 m (W 5th Ave under the bridge, Birch St) | 0 m |
| corner points per block (median) | 20 | 5 |
| parcel land given to the street | 82 m² | 2,228 m² |

The four city blocks we do not match all touch the edge of the area. The 2,228 m² of parcel land is where an OSM building stands over the
property line (OSM's buildings are drawn a little off the city's survey) and the edge was pulled in to it.

Where the edges come from: 260 street sides, 190 from parcels, 9 from sidewalks, 61 from the road class; 83 pulled in to a building.

## Result on Broadway × Granville

| | |
|---|---|
| neighbour pairs (shares meet) | 116, 7 of them with the outside |
| sections | 92; 76 fill their rectangle ≥ 95 %, 84 ≥ 85 % |
| intersections | 40, each meeting 3 or more sections |
| pieces narrower than 2 m | 0 |

Before (cuts from the road network, last version): 120 sections, 54 intersections, 18 pieces narrower than 2 m.

## Open points

- **The Granville Bridge ramps.** No blocks face each other there for long, so the ramps are a few large intersections. It is one
  complex junction; whether to divide it more is open.
- **A thin strip at the top edge** (39 m², between a block and the edge of the area) is a section with the outside; it should probably
  be part of the intersection beside it.
- **Levels.** Only level 0. Bridges and tunnels (levels 1, -1) have their own street, without blocks: their spaces follow the deck.
- **Stable ids** as above, and the move into the pipeline: `blocks.py` (step 1), the cutting in `spaces.py` from the blocks (steps 2-4),
  then subsections (step 5); `urbanstyle check` before and after.

## A barrier through a junction (2026-10-11)

**Problem.** Intersection i0-616471133 (Fir Street × West 8th Avenue) is one area across three roads: Fir Street northbound
(w48524379), the Granville Bridge ramp's road (w473319095) and Fir Street southbound (w48524371). No block lies between them, so the
division makes one junction from all the street space there. But OSM has two junctions: W 8th Ave from the east meets Fir Street
northbound at n4707734005, and W 8th Ave to the west meets Fir Street southbound at n616471133. On the page, the joined area connected
W 8th Ave east to W 8th Ave west, and that move does not exist.

**Rule** (`division.py`, "barriers").

1. Two carriageways have an island between them (`island`, "two carriageways apart") on both sides of an intersection.
2. OSM gives the two ways no node in common in that intersection.
3. Then a barrier (part type `barrier`, `BARRIER_W_M` = 0.5 m wide, 0.8 m high in 3D) joins the facing ends of the two islands across
   the intersection. The parts that it crosses are cut to give it room.
4. A SUMO move that crosses a barrier is not drawn, and it is not a head of a turn arrow.

**Result on Broadway × Granville.** Two barriers: i0-616471133 (w473319095 and w48524379) and i0-255687224 (w48524371 and w48524379,
at West 7th Avenue). 4 moves are not drawn: the move from W 8th Ave east to W 8th Ave west, and U-turns across the space between the
two Fir Street roads. Checks before and after: U12 2 → 6 (approaches with no straight move: those moves were false). R1 0 → 1, R4 5 → 7
and U11 7 → 8 come from the lane corrections (`corrections/lanes.json`), not from the barriers.
