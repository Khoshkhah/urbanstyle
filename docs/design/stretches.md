# Rank 2: the stretches

<p class="lead">The street of a level divided along the road network into sections, from junction to junction, and intersections,
where the arms of one or more junction nodes meet. A section is cut into subsections where its cross-section changes.</p>

## Reads

The road network of the level: duckOSM's driving edges with OSM's tags (`lanes`, `lanes:forward`, `lanes:backward`, `oneway`, `width`,
`turn:lanes`, `parking:*`, `cycleway*`). The street of rank 1. The bridge profiles, for the ways a bridge model draws.

## The junction nodes

A junction node is an OSM node where three or more road ends meet. A road that runs through the node counts two ends. The ends are
paired into streams: an end continues into the most opposite end within 45°. An end's direction is taken over 3 m of its line, or
over the whole piece where the piece is shorter. The node is a junction in three cases:

- an end has no continuation (a road ends there, a T junction);
- two ends continue into one (a merge or a fork: a Y, a ramp that joins a road, a slip lane that leaves a road);
- two streams cross (their ends alternate round the node).

A two-way road that splits into its two one-way carriageways, one arriving and one leaving, is no merge or fork: each direction
keeps its own carriageway. The node is a joint.

Two streams that only touch, as two one-way lines of one street drawn into one node, make no junction. A node that only the ways of
a bridge and the ramps from it reach is the bridge's node, not the ground's. A landing keeps its junction, because a road of level 0
is there. Two roads that share no OSM node stay apart, also where they touch.

## The connectors

A road piece between two junction nodes is a connector where the two junctions' cores overlap on it: the stop line of each node on
that piece lies at or beyond the other node's stop line, so no section fits between them. Each node's stop line on the piece lies
at its core, how far the other arms' roadways overlap the piece from the node, plus 3 m. A `_link` piece between two junction nodes
and every piece of a roundabout's ring are connectors too. A connector belongs to one intersection together with both nodes. An
intersection can hold several nodes and connectors. A short piece whose stop lines do not meet is a short section between two
intersections. A section whose roadway outside the intersections is under 20 m² is no section: that roadway joins the
intersection it touches, and only that roadway.

## The runs and the sections

A run is one OSM way with one cross-section, split at the junction nodes. A section is the road from one junction to the next,
whatever OSM ways it is made of: the runs chained end to end across every node that is no junction. Every section ends at every
junction it reaches. The longest way names the section (`s0-w<way>`); a second chain of the same way gets `.2`. Two sections that
end at one node that is no junction (a bend sharper than 45°) are cut on the bisector of their directions there, as at a joint inside a
section: both frames run on past the node to the bisector, so the corner is filled with no notch and no overlap.

**A divided road is one section.** Two runs pair when all of these hold: both are one-way; both carry the same name; they lie side
by side (the middle of each line projects onto the inside of the other, 2 m or more away from it; each end of each line is within
30 m of the other line; the lines stay within 30 m over 80 % of their length); no block lies between their lines. The pair is one
section and one space. Each carriageway keeps its own lanes and kerbs on its own line. The median between them is an island of the
space. Two one-way streets of one name with buildings between them stay two sections. A boulevard whose carriageways are more than
30 m apart stays two sections, and the land between them is green of rank 1.

## The subsections and the joints

A section is cut into subsections where the paint differs: a lane count, a turn pocket, a parking strip, an island. The id is
`<section>/<k>`. Every joint of a section, a place where OSM's tags change, is classified before it touches anything (`urban.joint`, check J4):

| Change in the data | Class | The frame | Inside the frame |
|---|---|---|---|
| the total is the same, the split between the directions differs | turn pocket | no change | the centre line moves over 15 m |
| the total changes by the lanes of a road that merges or forks at a node | merge, fork | no change | the lane blends into the neighbour at the node |
| the total changes with `turn:lanes` naming a turn lane within 80 m of an intersection | turn pocket | no change | the median or the parking narrows for the pocket |
| a parking tag or a city's meters start or stop | parking | no change | the parking strip starts or stops |
| a median, an island way, a barrier way or a bridge's barrier starts | island | no change | a strip inside the frame |
| the total changes, none of the above, and OSM `width` changes with it on both sides | real | the frame changes, with a kerb taper over 15 m | |
| the room between the street's edges changes the frame | room | the frame changes at the joint | |
| the total changes, none of the above, no width evidence | unknown | the frame keeps the wider count | the lane ends; paved roadway beside it |
| the lanes, the width and the strips are the same | none | no change | |

A merging or forking arm is an arm of another section at a junction node within 80 m along the section, whose heading continues
into the section within 45° and whose lanes are the difference. A real change needs OSM `width` on both sides, differing by more
than 0.5 m, or by more than 0.1 m a lane with the same count. A turn pocket named by `turn:lanes` gets no parking from the city's
meters on its kerb side; parking OSM maps on the way stays.

## The intersections

One intersection per junction node, or per cluster of nodes that connectors join: `i0-<node>`, the smallest node id. Its nodes are
in `urban.junction`.

**A roundabout** is a closed ring of one-way ways that OSM tags `junction=roundabout` (in duckOSM's edges). Every piece of its ring
is a connector, however long, so the whole ring with all its nodes is one intersection of kind `roundabout`.

## The geometry of a stretch

Rank 2 cuts the street of rank 1 by the stop lines alone. The stop line of each arm is where its lanes enter the junction: the far edge
of OSM's crossing on that arm within 15 m of the core, else 3 m past the core. Where a crosswalk lies on the arm, the stop line runs along the crosswalk, 1.5 m beyond its far edge, at the crosswalk's own angle, so the crosswalk lies whole inside the intersection and the intersection's edge follows it. Where no crosswalk lies on the arm, the stop line is square to the road. Each stop line runs across the whole street to the edges of the blocks on both sides, 60 m to each side, and the arm's roadway ends on the same line. The street polygon noded with these cuts and polygonized
gives the faces of rank 2: the face between a junction's arm cuts is that intersection, with its corners; the face between two
intersections along a road is that section. The roadway with the most area inside a face names its owner; a face with no roadway joins
the neighbour it shares the most edge with. The stretches partition the street.

## The paths

A path is a street for walking. A path junction node is a node inside a path's ground where three or more path ends meet; a path
that runs through the node counts two ends. A node where a path meets a sidewalk or a road is no path junction. A path section is
the path from one path junction to the next (`p0-w<way>`); a path intersection is where the paths meet (`q0-<node>`). Each path
that leaves a junction is cut square across its own corridor only, at half the width of the widest path there. A path with no
junction is one path section, and a piece under 2 m² joins the piece it shares the longest edge with. A square is the path intersection of the paths that reach it: their sections end at its edge. A square that no path
reaches is a plain piece of its plot. Where a path meets a road, the path section ends at the street's edge, and a crossing over the
road is the street's crosswalk.

## The named street

A named street (`k0-<way>`, `urban.street`) is a group of stretches: the sections that share a name and a node, with the
intersections they arrive at. An unnamed road is its own named street. It is not a rank: an intersection belongs to every named
street that arrives at it.

![The stretches at Broadway and Granville.](../img/vancouver/03-stretches.png){ width=100% }

*Rank 2 in the street: the sections (blue) and the intersections (orange), each cut by the stop lines; the path sections and path intersections in the paths.*

![The spaces with their axes.](../img/vancouver/04-spaces.png){ width=100% }

*Rank 3: the spaces, each subsection with its axis (red), along which `s` is measured.*

## Writes

`urban.stretch`: one row per section, intersection, path section and path intersection, with its ways, its nodes and its axis.
`urban.junction`: the junction nodes of each intersection. `urban.joint`: every joint of a section with its class and the lanes on
both sides. `urban.street` and `urban.arm`: the named streets and their arms ([The tables](tables.md)).

## Checks

| Check | Tests |
|---|---|
| J1 | every intersection holds a junction node |
| J2 | no intersection has a piece over 40 m² and over a tenth of its area outside its arms' bands |
| J3 | every connector lies inside an intersection or on a bridge deck |
| J4 (INFO) | the tag changes along the sections, with the count per class |
| W1 | on every level, no street's line has a stretch of 0.1 m or more between two pieces of roadway with no roadway under it |
| W2 | on every level, where two spaces meet across a street, the roadway reaches the joint at the same points on both sides (0.2 m); a street's dead end is no joint, and a stretch where one side has roadway and the other side an island is a median's nose, no step |
| W3 | where streets of two levels meet at a node (a tunnel's entrance, a ramp onto a deck), the roadway of each level reaches the node (0.5 m) from each of its streets |
| K1 (INFO) | the kerb of a subsection against the city's catch basins: a difference over 1.5 m |
