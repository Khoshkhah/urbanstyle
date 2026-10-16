# Glossary

The words used in `docs/design/street-space.md`, `docs/design/street-objects.md`, the code and the dashboard, in one place. When a word is also
a column or a table name it is written in `code`. "Built" says whether it exists in the data today.

## Space and hierarchy

| term | meaning | built |
|---|---|---|
| **level** | an integer floor of the area: 0 is the ground, +1 one floor above, -1 one below. From OSM's `layer` tag, else a bridge is 1 and a tunnel -1; outside `LEVELS` clamped to the nearest kept level. Never "layer": that word is OSM's tag, or one of the model's layers of `space-layers.md` (ground, surfaces). | yes |
| **ground** | level 0: the street the network step builds (`steps.md`). A level-1 way with nothing at level 0 passing under it is ground too, and loses its level-1 copy. | yes |
| **deck** | a road or path at a level above the ground: what a bridge carries. Drawn 6 m a level above the ground when it has no bridge model. | yes |
| **bridge** | the structure that carries a deck: in the model a profile (`<name>.bridge.json`, `bridge-profile.md`) and the 3D model made from it (`bridges-3d.md`). A bridge way is an OSM way a profile lists. | yes |
| **tunnel** | a road or path at a level below the ground, in a tube. Drawn flat under the ground until `tunnels-3d.md` is built. | yes |
| **tube** | the space of a tunnel or of a deck: its roadway and a narrow walkway, no blocks (`space-parts.md`). | yes |
| **portal** | the node where a tunnel's way meets a ground way; the tunnel's lanes and the ground's lanes touch there. | yes |
| **landing** | the node where a deck's way meets a ground way: the bridge's end on the ground (`bridge-profile.md`). | yes |
| **street space** | the whole open strip of a street from the building (or wall) on one side to the one on the other: the right-of-way. It is *measured*, not drawn: see **section (cross-section)** | yes |
| **ROW** | right-of-way. Another name for the street space; also the name used by the street-design guides (Seattle, NACTO) | yes |
| **container** | one row of `space.container`: a named, non-overlapping piece of the street space at one level. Every point of the street space is in exactly one container. Its `kind` is `street`, `path`, `rail` or `intersection` | yes |
| **street** | a *group*, not a container: the roads of one level that share a name and are connected, divided at every junction into sections, plus the intersections it arrives at (`space.street`). Id `k<level>-<smallest OSM way id>`. One intersection can belong to several streets | yes |
| **section** | a container of kind `section`: the roads of one street between two junctions, with the walkways and cycleways that run along them (at least 60% of their length within 15 m). Id `s<level>-<smallest edge id>`. The CityGML `Section` | yes |
| **path space** | a connected network of footpaths and cycleways with no road within 15 m (park paths, alleys, steps). Id `p<level>-<smallest OSM way id>` | yes |
| **rail space** | a connected network of rail lines at one level, with a strip for the structure. Id `r<level>-<smallest OSM way id>` | yes |
| **intersection** | a container of its own at a junction (a node where 3 or more road elements meet), shared by the streets that meet there: the free space between the straight cuts across its arms (each at half the widest other arm's width + 1 m from the node), bounded by building faces, clipped to the street space. Junction nodes closer than 15 m are one intersection (while the cluster stays under 30 m across). Id `i<level>-<smallest OSM node id>`, stable across rebuilds | yes |
| **arm** | one road arriving at an intersection (`space.arm`): it links an intersection to a section and to a street group | yes |
| **junction** | a node with three or more road edges; a node with two is a continuation | yes; at level 0 (`network.py`, 2026-10-16) a node where 3 or more road ends meet and a road ends, two roads merge or fork, or two streams cross (`sections.md` rules 1-2) |
| **connector** | a road between two junction nodes shorter than 40 m (`CONNECTOR_M`), or one of `_link` ways only, not a bridge way: no section; its carriageway belongs to one intersection with both nodes, named in the junction area's `ref` (`sections.md` rule 3, 2026-10-16) | yes |
| **zone** | what a part of a container is for: `travelway`, `pedestrian_realm` or `track`. One row of `space.zone` per container and zone | yes |
| **travelway** | the part of the street space where vehicles move. Measured out to the kerb where a sidewalk is found, else the lane width | yes |
| **side** | rank 4 of the street's hierarchy (`steps.md`): the two halves of a space, the driving side (the frame, kerb to kerb: the roadway) and the walking side (the rest, kerb to block edge); `space.side`, agreed 2026-10-16, to be built | no |
| **pedestrian realm** | the rest of the street space beside the travelway: sidewalk, furnishing strip, open ground. Still a remainder, but its inner edge is the measured kerb where one was found | yes |
| **track** | the zone of a rail space: the tracks plus a strip for the tunnel or embankment | yes |
| **element** | one centerline or building in `space.element`: a `road`, `walkway`, `cycleway`, `rail` or `building`, with its level, width and OSM ids | yes |
| **link** | a place where you change level: a node where elements of two levels meet, or a station entrance. Types `ramp`, `stairs`, `elevator`, `entrance`, `connection` (shown as *Other level change*) | yes |
| **station** | a rail, subway or tram station (`space.station`); its level comes from its own tag, else from the tracks beside it | yes |
| **entrance** | a subway or train-station entrance; tied to its station by name (within 600 m) or by being the nearest station of its kind (within 250 m) | yes |
| **axis** | the reference line of a container: its centerlines merged end to end (the midline between the carriageways of a dual road). Positions are given as `s` and `t` along it | not yet |
| **strip** | one band across the street space with a type, a width and a provenance (`space.strip`): sidewalk, parking, cycle lane, travel lane... | not yet |
| **object** | a thing standing in the street space: a bench, a lamp, a tree, a crossing... (`space.object`). Has a `group.class` such as `furniture.bench`. Today: point objects from OSM nodes | yes |
| **boundary** | what bounds the street space on a side: a building, wall, fence, hedge, retaining wall, or open (`space.boundary`) | not yet |

## Blocks first (2026-10-10, designed and tested, not in the pipeline yet)

The words of [Blocks first](blocks.md). Its **section** and **intersection** are cut from the blocks, not from the road network as the
containers' above.

| term | meaning | built |
|---|---|---|
| **block** | the land between the streets: a face the level-0 public streets enclose, less each street's half width; where a city has parcels, the face's parcels joined and closed across gaps narrower than 12 m. `space.block`, id `b<level>-w<way><side>`; each street side in `space.block_side` | yes (step 1) |
| **bounding road** | an OSM public street at level 0 (motorway down to residential, living street, pedestrian, their links) that bounds blocks; a service road (alley, driveway, parking aisle) lies inside a block | test |
| **chain** | the bounding roads joined end to end between two junctions | test |
| **face** | an area the chains enclose, closed by the edge of the area; a block is what is left of it | test |
| **street side** | one side of one chain within one face: it gets one distance from the road line, so the block's edge there runs parallel to the road. The distance comes from the parcels, else the sidewalks, else the road class, pulled in to the nearest building | test |
| **share** | the part of the street nearest to one block | test |
| **middle line** | where two blocks' shares meet: the line down the middle of the street between them | test |
| **facing stretch** | the part of a middle line where a line square to it meets block A on one side and block B on the other, each on a side running along it | test |
| **street neighbours** | two blocks that face each other across one street for at least as long as the street is wide; one section each | test |
| **corner neighbours** | two blocks whose shares meet but that do not face each other long enough (diagonal across a junction); their ground is intersection | test |
| **cut** | a straight line square to the middle line, from one block to the other, 3 m inside each end of a facing stretch (`ARM_M`) | test |
| **street opening** | where the edge of the area crosses a street (shorter than 40 m): the outside is no neighbour there | test |
| **subsection** | a piece of a section between two cuts where its lanes, width or frontage change, at least 12 m long. Id `<section id>/<k>`. At level 0 (`network.py`, 2026-10-15) a section is the road between two junctions, whatever OSM ways it is made of, named by its longest way (`s0-w<way>[.n]`); its subsections `/1`, `/2`, ... are the stretches with one cross-section inside the section's **frame**, and a lane the next subsection has not ends in a **taper** over 15 m | yes |
| **merge shift** (`subsection.left_extra`) | how far a section's lanes sit off the OSM line (left +) because the section keeps the through arm's kerb at a merge or fork (`sections.md`, the rules from the spots, 1); the lanes' `position_ref` says which arm joins or leaves where. 0 everywhere else | yes |
| **frame** | the driving part of a section between its two kerbs: one width for the whole section, the lanes and the strips a source gives at its widest place (`sections.md` rule 6, 2026-10-16; `subsection.width_m`). The lanes stay centred on their own way's line inside it; the rest is paved roadway (part `carriageway`, its `ref` names the frame). It changes only at a `real` change, with a kerb taper over 15 m | yes |
| **change** (`space.change`) | one row per place along a section where OSM's tags change (a joint between two subsections), with its class (`sections.md` section 3): `turn pocket` (the same total with another split, or `turn:lanes` naming a turn lane within 80 m of a junction), `merge` / `fork` (the lanes of a road that joins or leaves at a junction within 80 m), `parking` (a parking or cycle strip starts or stops), `real` (an OSM `width` on both sides, different), `unknown` (the total changes with no evidence: the frame keeps the wider count), `none` (another tag changes). Columns: the two subsections and ways, the lanes as forward + backward in the section's direction, each side's own width, `note`, the point. Check J4 | yes |
| **axis** (of a subsection) | the middle line between its two blocks, straightened: every strip inside it runs parallel to it, at an offset (left +) | yes |
| **shoulder** | the roadway between a carriageway's lanes and its kerb or median: at least 0.3 m (the gutter), wider where the lanes leave room | yes |
| **carriageway** (part) | roadway between two roadways where no lane is: a strip narrower than 8 m that touches no block and has no kerb, object or path mapped on it in OSM (`network.GAP_M`) | yes |
| **buffer / furnishing**, **clear path / sidewalk**, **frontage** | NACTO's zones of the pedestrian realm, from the kerb out: where trees, poles and furniture stand; the walking path (1.8 m around OSM's sidewalk line); the rest up to the block | yes |
| **yard** (ground kind) | layer 0 inside a block that no other kind holds: private open ground around the buildings (a garden, a forecourt, a paved area). Inside the blocks there are no plots: each building is a ground item, whole | yes |
| **alley** (ground kind) | layer 0 inside a block that a road runs through and no plot, green or path holds: a back lane, a driveway, a parking aisle. Not street: the street is the street spaces | yes |
| **access** | an opening of a car park or a back lane onto a street: the section it opens onto, its driveway apron there, the OSM way of its driveway or aisle. A car park or lane with openings onto two streets connects them; it still lies inside one block. An `open` car park side (no barrier mapped) has the whole side as its access, a `closed` one (fence, wall, hedge, bollards) only its driveways and gaps | designed |

## Measuring the street space

| term | meaning |
|---|---|
| **section (cross-section)** | a measuring line cast out left and right from a centerline every 3 m. (Not the CityGML `Section`, which is a stretch of road.) |
| **ray** | one half of a section: it runs from the centerline until it meets a building (or, for the travelway, a sidewalk) |
| **building face** | the wall of a building that a ray stops at; the edge of the street space on that side |
| **reach cap** | the longest a ray may go: `1.5 × width + 8 m` for roads, `+ 4 m` for walkways and cycleways, never more than 25 m. A ray that hits nothing within it is **open** |
| **open** | a side where the ray reached the cap without meeting a building: the edge there is the cap, not a real boundary |
| `open_share` | share of a container's road sections with at least one open side |
| `one_side_open_share` | share with exactly one open side: a lopsided street |
| **capped street space** | a container with `open_share ≥ 0.5`, tinted yellow on the dashboard: its edge and width are approximate |
| `narrow_half_m`, `wide_half_m` | mean distance from the centerline to the nearer and to the farther side |
| `mean_width_m` | mean total width of the street space across the road's sections |
| **kerb** | the edge of the travelway toward the sidewalk. Measured as 1 m before the nearest sidewalk line. As a mark (`space.mark`): where a raised part (sidewalk, furnishing, open ground, bus stop, island) meets flush ground in a space |
| **sidewalk** | in this project a walkway or cycleway that runs along a road (within 15 m), and is not a crossing, steps, a corridor, a platform or an elevator. A geometric rule, because only 6-9% of walking ways carry `footway=sidewalk` |
| `kerb_share` | share of a street's road sections where a sidewalk was found; where it was not, the travelway is the lane-width guess |
| **lane width** | `lanes × 3.25 m`, else a flat width by road class (motorway 14 m … service 3.5 m) |
| **structure** | a bridge, tunnel, or any element not at level 0: its street space is the line buffered by `width/2 + 1 m`, with no rays |
| **physical intersection area** | traffic engineering: the area within the four corners of a junction, bounded by the prolongation of the curb lines (curb returns), extended to the far side of a marked crosswalk. What our `intersection` containers should approximate |
| **functional intersection area** | the physical area plus the approach upstream (reaction, manoeuvre and queue-storage distance) and its auxiliary lanes. Not modelled |
| **partition** | cutting the street space into containers so that none overlap and the areas add up to the whole |
| **arm cut** | the straight line across an arriving street that ends a section and bounds an intersection |
| **provenance** | where a value came from: `measured` (a line or kerb in the data), `tag` (an OSM tag), `default` (a flat guess) |

## Data and ids

| term | meaning |
|---|---|
| **duckOSM** | the project that turns an OSM extract into a DuckDB file: `raw.*` (nodes, ways), `driving` / `walking` / `cycling` (edges), `features.*` (buildings, streets, public transport). The only source for this project; Overture is kept in mind for what OSM lacks |
| **Overture** | Overture Maps, a second open map source; not used here (see the Sources section of `street-space.md`) |
| **edge** | one directed piece of a road network between two nodes; a two-way street is two edges. `space.element` keeps one per way piece |
| **OSM way / node** | the OSM line / point objects. A way id is part of every container id |
| **id formats** | `s0-123` street, `p0-123` path space, `r0-123` rail space, `i0-123` intersection (level, then an OSM id); `n123` / `w123` an OSM node / way as an object or building |
| `space.*` | the tables this project writes: `element`, `container`, `zone`, `link`, `station`, `object` (and, planned, `axis`, `strip`, `boundary`); the network-first preview adds `subsection`, `unit`, `cut`, `part`, `mark`, `width`, `turn`, `change` |
| `space.junction` | the nodes of each junction of the network-first spaces: the container step's groups (`cluster_id`), a roundabout's group cut back to its ring ([network first](network-first.md)) |
| `space.observed`, `space.photo` | Mapillary's map features (`grp`: parking, no parking, give way, stop, traffic light, street light, bin, bench, lane arrow, zebra) and photo positions ([Mapillary observations](mapillary.md)) |
| `parking`, `no parking` (part types) | a shoulder where parking is mapped or signed; one where signs forbid it |
| **lot (`space.lot`)** | an off-street car park (OSM `amenity=parking` on the ground, not `parking=lane` / `street_side` / ...): private ground beside the street, like a building's plot. Id `w<way>`, with name, operator, parking, access, fee. The street space stops at its edge; its parking aisles (`service=parking_aisle`) are no street (2026-10-10) |
| `verge` (part type) | the raised ground by the kerb where OSM maps no sidewalk; nobody walks on it |
| `bridge deck` (part type) | at level 0, the band of a way that a bridge profile models (`build --bridge`): the bridge model draws it; the page draws only what the model does not cover |
| `ring`, `shoulder` (part types) | a roundabout's circulating roadway as one part; the strip between the outer lane and the measured kerb (parking, a hard strip) |
| `space.turn` | one row per lane-to-lane move through an intersection: `from_edge`/`from_lane` → `to_edge`/`to_lane` (lanes counted from the right), `turn` left / straight / right, `source` `sumo` ([the roadway from SUMO](space-parts.md#the-roadway-from-sumo)) |
| **linear referencing** | giving a position as `s` (distance along a reference line) and `t` (offset across it), as OpenDRIVE and IFC do |
| `s`, `t` | distance along the axis in metres from its start, and signed lateral offset (left positive) |
| **UTM** | the metric coordinate system the measuring runs in; results are stored in lon/lat |

## Axis and (s, t), explained

The **axis** is one line down the middle of a street container: its centerlines joined end to end (for a dual carriageway, the
midline between the two carriageways). It gives the street a direction, from its start to its end.

A position relative to the axis is two numbers, **(s, t)**:

```
                       t = +4 m   (4 m to the left of the axis)
                           *  a bench
    left side              |
   - - - - - - - - - - - - | - - - - - - - - - - - - - - - -   edge of the street space
    ───────────────  AXIS  ───────────────────────────────────►
    s = 0 (start)           s = 120 m
   - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    right side
```

- `s`: distance along the axis from its start, in metres.
- `t`: distance across it, in metres; positive to the left of the direction of travel, negative to the right.

"Bench: s = 120, t = +4" means 120 m from the start of the street and 4 m left of its middle. Latitude and longitude say where
something is on the Earth; (s, t) says where it is *in the street*. That lets us draw a cross-section at any `s`, list objects in
order along the street, and ask for everything within 2 m of the kerb. OpenDRIVE and IFC 4.3 position road objects the same way.
Not built yet (step 3 of `street-objects.md`).

## Bridge profile

The words of `docs/design/bridge-profile.md` (`bridge_profile.py`, `<name>.bridge.json`).

| term | meaning |
|---|---|
| **bridge profile** | one JSON file per bridge (`urbanstyle.bridge/1`): its deck outline, axes, vertical profiles, sections, bands and piers, each value with its source and method. Scripts make it; nobody edits it by hand. The 3D model reads only this file |
| **axis** (of a bridge) | one chain of OSM road ways on the deck between two branch points, the reference line of `(s, t)`. A bridge with ramps has more than one (`a1`, `a2`, ...) |
| **vertical profile** | the height of the deck top along an axis, as points `(s, z)`, linear between the points; `z` above the profile's `z_datum` |
| **section** (of a bridge axis) | a length of the axis, `s0` to `s1`, where its bands do not change: a new one starts at each end of a GMNS link. Not the street's section container |
| **station (LiDAR)** | a point every 10 m along a bridge's axis where `bridge-measure` reads the deck top and the ground from the LiDAR returns; `vertical.stations` lists each one with its returns, its heights (CGVD28) and its method (`measured`, or `chosen` with fewer than 20 returns) |
| **CGVD28** | the vertical datum of the City of Vancouver LiDAR 2022 (Canadian Geodetic Vertical Datum of 1928, Metro Vancouver geoid): the heights in `vertical.stations` |
| **band** | one strip across a section: a lane (with its GMNS `lane_id`), a cycleway or a footway, at offset `t` (left of the axis positive) with its width |
| **z_datum** | what `z` is measured from: now "ground at the ends" (chosen); a LiDAR measurement gives a survey datum |

## Unit dossier

| term | meaning |
|---|---|
| **unit dossier** | everything known about one unit (an intersection or a street section) from every source, in `data/units/<name>.duckdb`, every row with its `source`, `method` and `confidence` (`docs/design/unit-dossier.md`) |
| **match** | one real object that several sources describe: the city's surveyed pole, OSM's node and Mapillary's detections of one street light are one `match` row (`match_id` `m<k>`, `sources`, `refs`: every source's own id); `object.match_id` links each source's object to it |
| **floors, height_m** | `space.element`: a building's real floors (`building:levels`, else from `height`) and height (OSM `height`, else a city's LiDAR (Vancouver 2009, `level_src` says so), else floors x 3 m); a building OSM lacks may come from a city's outlines (`source` = the city, id `vb<object id>`), kept beside its clamped `level_min` / `level_max` (-2..2); 3D draws a building at its real height |
| **road information on a part** | `space.part` `road`, `road_class`, `speed`, `surface`, `lit`, `road_lanes`, `oneway`: what is known of the road a lane or shoulder belongs to (its OSM way, `ref`); a value OSM lacks is urbanstyle's chosen one, saying so ("50 km/h (urbanstyle, chosen: the limit in built-up areas; not in OSM)", "asphalt (urbanstyle, chosen; not in OSM)") |
| **use, ground_use (`space.element`)** | what a building is used for (residential, retail, commercial, office, civic, industrial, ancillary, or mixed: homes or offices over shops) and its ground floor (retail, food & drink, services, leisure, civic, office, vacant, residential), each with `use_source` / `use_method` and `ground_source` / `ground_method`; `uses` lists the evidence: the OSM tag, the shops OSM maps inside, a city's storefronts (one business in both counts once). The popup shows them as use, ground_floor, evidence |
| **approach (`space.approach`)** | a lane coming into a junction: its moves, the ways it may go for all traffic, its turn arrow or why it has none; checks U11-U13 count what looks wrong |
| **furnishing strip, `holds`** | the strip by the kerb where street furniture stands (`space.part` type `furnishing`), only where some does; `holds` says what stands in it ("2 tree, 1 lamp"), each real object once whatever sources map it (OSM, Mapillary, a city's survey: `unit.group_objects`), `ref` their ids, `source` whose |
| **parcel (`space.parcel`)** | a city's land parcel (Vancouver `property-parcel-polygons`, id `pl<site id>`): the property line; the street reaches it, the ground's plots are them |
| **surface (`space.surface`), layer 1** | the surfaces covering a ground item exactly, one row per kind, id `<ground id>:<kind>`: a street's roadway, pedestrian realm, median, verge; a plot's building, car park, construction site, garden, yard; a green's play, path, lawn; a path, a track bed, the ground under a bridge, a paved square |
| **ground (`space.ground`), layer 0** | every piece of the area at level 0 is one item of one kind: `street` (our spaces), `path`, `square`, `structure` (land under a bridge), `rail`, `plot` (a city's parcel, a car park, a construction site, an OSM land use, a building no plot holds), `green`, `water`, or `unknown` (check G1); id `g0-<kind>-<source id>` ([Layers](space-layers.md)) |
| **tree pit, driveway (parts)** | a street tree's pit in the furnishing strip (1.5 m square, urbanstyle's chosen size); a driveway's apron across the sidewalk (kerb lowered). A driveway and a car park's aisle are no street |
| **bus stop, bus zone (parts)** | a bus stop's waiting area on the sidewalk, and the kerb strip where its bus stops (no parking); the stop's tags in `holds`, its timetable (routes, buses per hour, from GTFS) in `rule` |
| **GTFS** | General Transit Feed Specification: an operator's timetable as open files (stops, routes, trips, times); `urbanstyle unit --gtfs URL` reads each stop's routes and weekday departures (`gtfs.py`) |
| **`width_m`, `length_m` (on a part)** | a lane's or kerb strip's measured width, else the width and length of the rectangle of the part's area and perimeter (`parts.strip_size`) |
| **confirmation (Mapillary)** | a source too rough to place things (`unit.CONFIRM_ONLY`: Mapillary) only confirms an object of a source with a real position (it joins its `match`); a group it alone sees is no object but a `check` row ("not confirmed"); the dashboard's "Mapillary detections (validation)" shows every detection, green where it confirms, orange where nothing does |
| **`rule` (on a part)** | the rules that apply to a part, in words, from their source: a parking strip's rates, time limits and rush-hour bans from the parking meters beside it |
| **inventory (dossier table)** | what each source holds around a unit (`source`, `layer`, `item`: an OSM key, a Mapillary class, a city dataset; `n`) and how much reaches our tables (`n_ours`), whether our code reads it (`read`); a gap is many items, nothing read |
| **vehicles, condition (turns)** | `space.turn`: who may make a move (NULL: all traffic; else e.g. `bus,taxi`) and when a time rule binds (e.g. `Mo-Su 07:00-19:00`), from duckOSM's turn rules |
| **junction area** | the roadway inside an intersection where the arms' carriageways meet and the turning corners between them (`space.part` type `junction area`, called "junction box" before 2026-10-09): an area of our model, nothing painted on the road; not the city's street-lighting junction box (type "electrical box", a lid in the pavement) |
| **ref** | an object's id in its own source (OSM node, Mapillary feature, a city's asset), kept so every drawn object leads back to where it came from |
| **source / method** ([Sources and methods](provenance.md)) | on every part, object and dossier row: where its data comes from (`osm`, `sumo`, `mapillary`, `vancouver`, `urbanstyle`) and how it was obtained (`surveyed`, `mapped`, `measured`, `derived`, `observed`, `chosen`, `checked`). A value no source gives is urbanstyle's own: `derived` (calculated from other data) or `chosen` (one value for a type); never a "default" |
| **position_source, position_method, position_ref** | `space.part`: what set a part's edge (the kerb's evidence, the block's edge): e.g. `osm+vancouver`, `measured`, the OSM sidewalk ways and the city's catch basins |
| **guide line** (mark) | a SUMO connection drawn through a junction, from an in-lane at its stop line to an out-lane; `space.turn` holds the same move |
| **R1** (check) | joints between two subsections where the roadway's edge steps by more than 0.1 m; a FAIL since 2026-10-16 (the frame is one width), except at a `real` change |
| **J3, J4** (checks) | J3: a connector not inside an intersection (or a bridge deck); J4 (INFO): the tag changes along the sections, with their classes (`space.change`) |
| **R4** (check) | edges between lanes, cycle lanes and parking at a joint (of one section, or of two sections with no intersection between them) with no edge on the other side: read every 0.1 m along the joint, 0.3 m into each side, within 0.25 m |
| **A1, A2, A3, J1, J2, X1, M1, K1** (checks) | the agreed street rules (`street-rules.md`): A1 a carriageway's lanes more than 0.5 m off their OSM line; A2 a parking or cycle lane with no real source; A3 a road line with no roadway under it; J1 an intersection with no junction node (3 or more road ends); J2 a junction area reaching over 5 m² outside its arms' bands; X1 a crossing way over the roadway with no crosswalk part; M1 a lane or centre line where the lane count is chosen; K1 (INFO) a subsection's kerb over 1.5 m from the city's catch basins |
| **crosswalk** (part) | `space.part` type `crosswalk`: an OSM crossing way over the roadway (3 m wide, or OSM `width`), or a band across a road at a crossing node that no way maps; cut from the lanes and the junction area; its paint by `crossing:markings` |
| **barrier** (mark) | `space.mark` type `barrier` (0.3 m): a guardrail on the ground continued from a bridge whose corrections name a median barrier (`street-rules.md` rule 12); drawn like a kerbstone in 3D |
| **parking line** (mark) | `space.mark` type `parking line` (0.12 m, dashed): the chosen lane's edge inside an outer lane widened to the city's kerb evidence, where cars park in the lane (`part.holds = parking`) |
| **crossing line** (mark) | `space.mark` type `crossing line`: one of the two lines along a crosswalk's edges where `crossing:markings` is `lines`, `dashes`, `dots` or `ladder` (0.15 m) |
| **lane_id** (`space.part`) | a lane's id in duckOSM's GMNS export, `<edge_id>_<lane_num>` (`gmns_driving.lane.lane_id`): the directed duckOSM edge under the lane's middle in its direction of travel, and its number from the left of that direction (1 = the leftmost); a lane both ways has both ids (`;`); empty for a road not in duckOSM's driving network (a road only for buses) |
| **taper** | a lane (or cycle lane, parking strip) that starts or stops at zero width at a joint, where the next subsection has no such item (`division.join_lanes`); its `width_m` is its full width and its `rule` says it is a taper |
| **R2, R3** (checks) | R2: guide lines leaving the roadway by more than 0.5 m; R3: subsections where OSM's lane count does not fit between our kerbs (a lane under 2.75 m) |
| **width_source, width_method; size_from** | where a part's or a mark's width comes from (`space.part`, `space.mark`, the dossier's `surface`, `line`, `lane`); an object's width and height and their sources (`size_from` on the page; the dossier's `object`: `width_source`, `height_source`, ...) |

## Dashboard

| term | meaning |
|---|---|
| **layer list** | the checkbox list at the top of the left panel; one row per drawn thing, with its colour and meaning |
| **tree** | the hierarchy under it: Pilot area → Buildings / Stations / Links / Containers, levels inside each branch |
| **basemap** | the map under our layers (CARTO Voyager by default); its streets, icons and labels are not our data |
| **centerline** | a faint line for a road, walkway or cycleway, kept so roadstyle's Street View can follow a clicked road |
| **focus** | selecting one street space (click it or its centerline on the map, or choose it in the tree, or type its id): the map shows only that container, its zones, centerlines and objects, the basemap is dimmed around it, and a panel lists what is inside (area, widths, zones, objects by class, each with a checkbox). Exit with the button or Esc. The map zooms in to level 23 at most; the basemap scales its last real tile level beyond its own limit |
| **jump button** | the buttons shown after clicking a link or a station that switch to the level(s) it joins |

## Terms from the standards

| term | where | meaning |
|---|---|---|
| **TrafficSpace / AuxiliaryTrafficSpace** | CityGML 3.0 | the space used by traffic / the space beside it (kerbs, green strips) |
| **Section / Intersection** | CityGML 3.0 | a stretch of road / the area where roads meet; what our `street` and `intersection` containers follow |
| **CityFurniture** | CityGML 3.0 | immovable street objects: lamps, signs, benches, bus stops, bins |
| **lane section** | OpenDRIVE | a stretch of road with a fixed set of lanes |
| **frontage, pedestrian, furnishing, curb zone** | NACTO / Seattle | the four bands of the pedestrian realm, from the building to the kerb |
| **flex zone** | Seattle | the band for parking, loading and bus stops between the pedestrian realm and the travelway |
| **segment** | Streetmix | one typed band of a cross-section with a width and a recommended minimum and maximum |
| **IfcRoadPart** | IFC 4.3 | a longitudinal or lateral part of a road |
