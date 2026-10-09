# Network first: subsections, spaces, and what is inside them (preview)

<p class="lead">Divide the roads first, then give every piece its own space: one road (or one pair of parallel roads), one intersection or one roundabout per space, each divided into lanes, crosswalks, sidewalks and markings.</p>

Status (2026-10-08): a preview, built on Monaco, on the `network-first` branch. The older containers (`space.container`), strips and checks
are still built beside it. Whether this approach can come close enough to reality is an open question (see "Where it stands").

## Step 1: divide the roads (`subsections.py`, `space.subsection`)

A section (one street between two junctions) is split where the **cross-section** changes (road class, width, one-way) or the **building
frontage** changes on either side (buildings start or stop, or the facade steps back or forward by more than 3 m; read on the building line,
buildings closed by 3 m; a change counts when it lasts 12 m). Two close parallel runs (within 15 m and 25°, for 70 % of the shorter, no
building between) are one corridor: the shorter follows the longer. A junction's own roads (a roundabout ring, a short link between its nodes)
belong to the junction. Ids `<section id>/<k>`.

## Step 2: one space each (`spaces.py`, `space.unit`, `space.cut`)

**Intersections** are cut at the block corners: the building-line vertex nearest the junction in the angle between two arms. Corners on both
sides: the cut joins them; one corner: the cut runs through it along the street on its other side (the prolongation of that building line);
none: square to the arm at the crossing street's half-width + 1 m. A crosswalk the cut runs through, or one starting at most 6 m beyond it,
is the junction's own and stays whole (one part, one id): the cut moves out past it to the stop line (1.5 + 2 m beyond the crossing), square across the arm (`how` =
`crosswalk`; 2026-10-09). A cut takes at most half the street to the next junction. The intersection
is the area its cuts enclose, minus the buildings: its core (nodes, the roads between them) and every arriving road up to its cut are its own;
of the rest it takes what the roads' spaces do not hold. A junction holding a roundabout's ring is a **roundabout**, a kind of its own.
Which nodes form one junction is `space.junction` (`intersection_id`, `node_id`, `level`, `cluster_id`): the container step's groups of close
nodes (`space.arm`), except that a group holding a roundabout's ring keeps only the ring and what lies within 12 m of it (an entry's splitter
island); a farther node that is a real junction is an intersection of its own (`i<level>-<its smallest node>`), and the roads between it and
the ring are roads again. Sainte-Dévote: 4,210 m² before (it held the junctions around it), 909 m² now; Monaco: 16 junctions split off.
Where a road crosses a **divided road**, the junctions on its two one-way carriageways (running opposite ways, joined by a link shorter
than 20 m) are one intersection: apart, the one between the carriageways was a sliver. Monaco: 4 such crossings (not at a roundabout).

**No street left to nobody.** The building line never closes a street: buildings closed by 3 m, except within 1.5 m of a road's
line (a street narrower than 6 m between facades kept its space). A road whose ribbon is cut away keeps its road surface as its
space; a subsection whose road the junctions took entirely is dropped and its scrap joins a neighbour. Then a final sweep: road
surface no space holds, and small holes the spaces enclose (at most 300 m², spaces along 90 % of their edge, not a block's garden),
join the neighbouring space they share the longest border with. Monaco: road centre line outside every space 1,095 m -> 22 m.

A **subsection's** space is a ribbon parallel to its road: a side with buildings reaches 4 m past the facade line and the building line is its
edge; an open side reaches the cap (or halfway to a parallel road with no building between). Square cuts at the splits, the arm's cut at a
junction. Every unit is one valid polygon; no two overlap (checks U1-U7).

## Step 3: inside each space (`parts.py`)

See [The inside of a space](space-parts.md): lanes, junction box, roundabout island and circulating lanes, crosswalks, cycle and bus lanes,
sidewalks; markings at real size; the roadway and the turns each lane may make from SUMO; widths per arm and across each subsection, each with its source (measured from mapped sidewalks or
crossings, tagged, or estimated). Checks U8-U10.

## Where it stands

The geometry is consistent (every check but U10 passes), but the result is only as real as the data: Monaco's OpenStreetMap has one road
width, no sidewalk widths and almost no kerb lines, so most kerbs and lanes are inferred. Next: compare a few junctions with the aerial photo
and with **osm2streets** (A/B Street), an open implementation of the same idea, and with **CityGML 3.0 Transportation** as the reference
definition (Road, Section, Intersection, TrafficSpace, AuxiliaryTrafficSpace), then decide whether to build on osm2streets, aim for an honest
schematic, or move the pilot to an area with surveyed kerbs.
