# From each rank to the next

The model is a hierarchy of six ranks over the area of a level. Rank 0 is the area. Rank 1 is the ground. Rank 2 is the stretches.
Rank 3 is the spaces. Rank 4 is the sides. Rank 5 is the parts. Rank 6 is the marks. Each rank partitions the rank above it, with
no overlap and no gap. This chapter gives the algorithm from each rank to the next. For each step it says what the step reads, what
it does, what it writes and which check tests it.

## Rank 0 to rank 1: the area to the ground

**Reads.** The edge of the area (`space.area`). OSM's roads, walkways, buildings, land use, water and rail (`space.element`).

**Does.**

1. *The blocks* (`blocks.py`). The bounding lines are the streets and the pedestrian ways. A street is a road of one of the eight
   street classes, with its links, or a named service road with no service kind. A pedestrian way is a pedestrian street, a footway,
   steps or a path that is not a crossing, not a sidewalk and not a pedestrian area. The bounding lines are chained between junctions
   and polygonized with the edge of the area. The result is the faces. From each face the roads' strips are cut. On each street side
   the edge of the block follows OSM's sidewalk line 1 m behind it, with the line's own shape, to the corner. Where OSM maps no
   sidewalk line, the edge stands 1.5 m behind the carriageway. A building nearer than the edge pulls the edge in to its wall. A piece
   under 400 m² or narrower than 8 m is street. Then the pedestrian ways' strips are cut. A strip is as wide as OSM's width, else 4 m
   for a pedestrian street and 3 m for the others. Every piece that is left is a block. A piece under 10 m² or narrower than 2 m joins
   the corridor beside it.
2. *The corridors.* The strip of each pedestrian way, up to the edge of the street, is its corridor (`space.corridor`).
3. *The street.* The area less the blocks and the corridors is the street of the level, one polygon per connected piece.
4. *The other kinds* (`ground.py`). Water, rail, square (OSM's pedestrian areas), green and structure (the ground under a deck). In
   a block, its pieces: building, yard, alley, car park and construction site. All outlines are noded and polygonized as one planar
   partition. Each face goes to the first kind in the order of precedence that holds it. A face that no kind holds joins its
   neighbour.

**Writes.** `space.block`, `space.block_side`, `space.corridor`, `space.ground`.

**Checks.** G1: no piece has an unknown kind. G2: no two kinds overlap by more than 0.05 m². G3: the area less the union of the
kinds is under 1 m². B1 (INFO): the buildings that reach over the edge of a block.

## Rank 1 to rank 2: the street to its stretches

**Reads.** The road network, which is duckOSM's driving edges with OSM's tags, and the street of rank 1.

**Does.**

1. *Junction nodes* (`sections.md`, rules 1 to 3). A junction node is a node where three or more road ends meet. The ends are paired
   into streams. An end continues into the most opposite end within 45°. The node is a junction where an end has no continuation,
   where two ends continue into one (a merge or a fork), or where two streams cross. A node that only the ways of a bridge reach is
   not a junction. A road piece under 40 m between two junction nodes, or a `_link`, is a connector. The two nodes of a connector are
   one intersection.
2. *Sections.* A section is the road from junction to junction, with its OSM ways chained. Every section ends at every junction it
   reaches, a T junction included. The longest way names the section (`s0-w<way>`). A second chain of the same way gets `.2`. Two
   one-way carriageways of one street that lie side by side with no block between them are one section (`dual-carriageways.md`).
3. *Subsections.* A section is cut where its cross-section changes. Every tag change along the section is classified as turn pocket,
   merge, fork, parking, real, room, unknown or none. Only a real change or a room change starts a new frame piece. The subsections
   are `s0-w<way>/<k>`.
4. *Intersections.* One intersection per junction node, or per cluster of nodes that connectors join, `i0-<node>`.

**Writes.** `space.junction` (node, intersection), `space.subsection` (axis, section, class, width), `space.change` (every tag change
with its class).

**Checks.** J1 to J4 (the junctions and the connectors), K1.

## Rank 2 to rank 3: the stretches to the spaces

**Reads.** The street polygon of rank 1. The axes and the junctions of rank 2. The stop lines.

**Does.**

1. *The stop line of each arm.* The stop line is where the lanes of a section enter a junction. It is the far edge of OSM's crossing
   on that arm. Where there is no crossing, it is the core of the junction plus a short reach. The stop line is a straight line square
   to the arm.
2. *The cuts.* Each stop line and each joint between two subsections is run square to its road across the whole street, to the edges
   of the blocks on both sides. A cut is 60 m long to each side. It is clipped to the street and passes the boundary of the street by
   1 cm, so that the noding joins them.
3. *The partition.* The street polygon is noded with all the cuts and polygonized. Each face is one space, whole, with its corners.
4. *The owner of each face.* A face between the arm cuts of a junction is the space of that intersection. A face between two cuts
   along one road is the space of that subsection. The roadway with the most area inside the face owns the face. The roadway is the
   lanes and the junction area. A face with no roadway in it joins the neighbour it shares the most edge with.

**Writes.** `space.unit`, one row per space, subsection or intersection, with its section.

**Checks.** U1: no two spaces overlap by more than 0.05 m². U14: the spaces add up to the street, with a gap under 1 m². U2: a space
is one polygon. B7: no space reaches into a block.

## Rank 3 to rank 4: a space to its two sides

**Reads.** Each space of rank 3. OSM's lanes and widths. OSM's sidewalk lines. OSM's parking and cycle lanes. The meters of a city.

**Does.**

1. *The kerb.* Where OSM maps a sidewalk line, the kerb is the near side of its strip. The strip has the line's own shape and is 1 m
   from the line, or half of OSM's width. Where OSM maps no sidewalk line, the kerb is the outer edge of the lanes plus the strips
   that a source gives. Each lane is 3.25 m, a chosen value, or OSM's width shared by the lanes. Where the room between the edges of
   the street is less, the lanes narrow, down to 2.75 m. The kerb is never a guess. The lane count is OSM's. The lanes stay centred on
   the line of the way.
2. *The two sides.* The driving side is the part of the space inside the kerb. In a section it is the frame between the two stop
   lines. In an intersection it is the roadways of the arms joined, with the corners at the kerb. The walking side is the rest of the
   space, with the corners. A piece of the walking side that touches no block is an island of that space.

**Writes.** `space.side`: `<unit id>:d` for the driving side, `<unit id>:w` for the walking side, `<unit id>:i<n>` for an island.

**Checks.** S1: the two sides of a space add up to the space, with no overlap. R1: the kerb steps only at a real change or a room
change.

## Rank 4 to rank 5: a side to its parts

**Reads.** The two sides of each space. OSM's lanes, turn lanes, parking lanes, cycle lanes, crossings and crossing markings. The
meters, the bikeways and the survey of a city.

**Does.**

1. *The driving side.* The lanes: OSM's count, lane 1 at the middle of the road, each lane at the chosen or the mapped width. The
   strips that a source gives: parking, cycle lane, bus lane, shoulder. The paved rest of the frame. In an intersection, the junction
   area. The crosswalks: OSM's crossings over the roadway, 3 m wide or OSM's width. The islands.
2. *The walking side.* The sidewalk is the strip of OSM's sidewalk line. Where OSM maps no line, the sidewalk is a 1.8 m band from
   the kerb. The furnishing zone lies between the kerb and the sidewalk. It is measured where OSM maps the line, and 1 m wide, a
   chosen value, where not. The frontage lies beyond the sidewalk, to the edge of the block. A driveway is where a service road
   crosses the walking side to the roadway.
3. *The source of each part.* Each part names its source and its method: `osm` mapped, `vancouver` surveyed, `urbanstyle` chosen or
   derived.

**Writes.** `space.part`: type, side, lane, width, source, method, ref.

**Checks.** U9: the parts of a space do not overlap by more than 0.05 m². U8: the parts cover the space. A1: the middle of the
lanes is on the line. B8 (INFO): the spaces whose lanes narrowed. X1: the crossings.

## Rank 5 to rank 6: the parts to the marks

**Reads.** The parts of each space. SUMO's lane-to-lane moves (`turns.py`). OSM's `crossing:markings`.

**Does.** The kerb line is the border of the driving side, one line per level, cut to each space and dropped at the mouth of a
driveway. The centre line and the lane lines lie between the lanes. The stop line and the give-way line are where the lanes enter a
junction. The bars of a crosswalk come from its markings. The turn arrows and the guide lines come from SUMO's moves.

**Writes.** `space.mark`, `space.turn`, `space.approach`.

**Checks.** M1. R2: the guide lines stay inside the roadway. U11 to U13: the approaches.

## The page

Each rank is one group of the Layers panel of the dashboard (`dashboard.md`), Rank 0 to Rank 6. Each layer is under its rank.
