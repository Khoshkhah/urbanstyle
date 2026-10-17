# Glossary

The words of the model, the code and the dashboard, in one place. When a word is also a table or a column, it is written in `code`.
[The model](model.md) gives the words of the hierarchy with the other names one hears for them.

## The hierarchy

| Term | Meaning |
|---|---|
| **level** | an integer floor of the area: 0 the ground, 1 one floor above, -1 one below; -2 to 2 are kept (`level`, `level_min`, `level_max`, `level_src`) |
| **rank** | a position in the hierarchy: 0 the level, 1 the ground, 2 the stretches, 3 the spaces, 4 the sides, 5 the parts, 6 the marks |
| **area** | the whole area of a level (`urban.area`) |
| **element** | one centre line or building in `urban.element`: a road, walkway, cycleway, rail line or building, with its level, width and OSM id |
| **ground** | rank 1: every piece of the area is street, plot or path (`urban.ground`); a plot's pieces, rank 2, are building, yard, alley, car park, construction site, green, water, rail, square, structure |
| **block** | the land between the streets and the pedestrian ways: a face the level-0 streets and pedestrian ways enclose, less each street side's distance and each path's half width (`urban.block`, `b<level>-w<way><side>`) |
| **block side** | one side of one road chain within one face, with its distance from the road line and what set it (`urban.block_side`: sidewalks, carriageway, path width, building) |
| **bounding line** | a street or a pedestrian way of level 0 that bounds blocks |
| **street** (rank 1) | the area less the blocks and the corridors; also the kind of ground |
| **named street** | a group of sections that share a name and a node, with the intersections they arrive at (`urban.street`, `k<level>-<way>`); not a rank |
| **pedestrian way** | a pedestrian street, a footway, steps or a path at level 0 that is not a crossing, not a sidewalk and not a pedestrian area; it cuts the blocks at its width |
| **corridor** | a pedestrian way's own ground between the blocks, up to the street's edge (`urban.corridor`, `c<level>-w<way>`); the ground kind path |
| **sidewalk line** | a walkway at level 0 that is no crossing and has no corridor: OSM's line of a sidewalk; its strip, OSM's width or 2 m, is the sidewalk part |
| **sidewalk zone** | the band a road's sidewalk can lie in: the carriageway widened by 8 m on each side |
| **alley** (ground) | a service road inside a block: the road's line at OSM's width or 6 m |
| **yard** (ground) | the ground inside a block that no other kind holds |
| **square** (a plot's piece) | OSM's pedestrian area or square |
| **structure** (a plot's piece) | the ground under a deck |
| **surface** | one row of `urban.surface`: the surfaces that cover a ground item exactly (`<ground>:<kind>`) |
| **junction node** | an OSM node where three or more road ends meet and a road ends, two ends merge or fork, or two streams cross |
| **stream** | a road end paired with the most opposite end within 45° at a node |
| **connector** | a road piece under 40 m, or a `_link`, between two junction nodes: it belongs to one intersection with both nodes |
| **run** | one OSM way with one cross-section, split at the junction nodes |
| **section** | the road from one junction to the next, its runs chained (`s<level>-w<way>`, a second chain `.2`) |
| **divided road** | a street whose two one-way carriageways run side by side with a median between them: one section and one space |
| **subsection** | a piece of a section with one cross-section (`<section>/<k>`); its axis and its area in `urban.space` |
| **joint** | where two subsections of a section meet |
| **joint** (`urban.joint`) | one row per joint of a section, with its class: turn pocket, merge, fork, parking, island, real, room, unknown, none |
| **intersection** | the space where the arms of one or more junction nodes meet (`i<level>-<node>`); its own stretch and its own space |
| **arm** | a run whose line ends at a junction node, within 1 m |
| **core** | how far the other arms' lanes overlap an arm from its node |
| **stop line** | the line across an arm where its lanes enter the junction: the far edge of OSM's crossing within 15 m of the core, else 3 m past the core |
| **cut** | a stop line or a joint run square to its road across the street to the blocks' edges; the lines that cut the street into spaces |
| **space** | the area of a subsection or of an intersection, block edge to block edge (`urban.space`); rank 3 |
| **side** | the driving side or the walking side of a space (`urban.side`, `<space>:d`, `<space>:w`); rank 4; the two partition the space |
| **frame** | one width for a whole section: its lanes and strips at its widest place (`subsection.width_m`); the driving side's shape in a section |
| **room** | the least distance from a run's line to the street's edge on one side; it caps the frame's kerb there |
| **kerb** | the boundary between the roadway and the walking side: the near side of the sidewalk strip where OSM maps the line, else the lanes' outer edge |
| **kerb evidence** | a city's catch basins, poles and sidewalk lines: they check the kerb and widen an outer lane for parking; they never move a lane |
| **merge shift** | how far a section's lanes sit off the OSM line because it keeps the through arm's kerb at a merge or fork (`subsection.left_extra`) |
| **roadway** | the lanes, the paved roadway and the strips; the driving side |
| **walking side** | the space less the roadway, kerb to block edge |
| **part** | one piece of one side, of one type (`urban.part`, `<space>#<n>`); rank 5 |
| **lane** | one traffic lane, OSM's count, centred on the way's line, 3.25 m or OSM's width, narrowed to 2.75 m at least where the room is less |
| **paved** | the paved rest of the frame where no lane or strip is; a strip under 8 m between two roadways with nothing on it |
| **strip** | a band beside the lanes that a source gives: parking, no parking, shoulder, bus lane, cycle lane |
| **junction area** | the roadway of an intersection where the arms' roadways meet, with the corners and the connectors |
| **crosswalk** | the roadway under a crossing way, 3 m or OSM's width; its paint from `crossing:markings` |
| **island** | a piece of the walking side between two roadways that touches no block; it begins where the strip is 2 m wide |
| **furnishing**, **sidewalk**, **frontage** | the three bands of the walking side from the kerb: where furniture stands; the clear path; the rest to the block's edge |
| **driveway** | a service road's crossing of the walking side to the roadway, at OSM's width or 5 m |
| **bus stop**, **bus zone** | a stop's waiting area on the sidewalk; the kerb strip where its bus stops |
| **tree pit** | a street tree's pit, 1.5 m square, in the furnishing zone |
| **mark** | a painted line, an arrow, a zebra or the kerb line on a part (`urban.mark`); rank 6 |
| **guide line** | SUMO's path through a junction from an in-lane to an out-lane; `urban.turn` holds the move |
| **turn** | one lane-to-lane move through an intersection (`urban.turn`): from, to, left/straight/right, the vehicles, the time rule |
| **approach** | a lane coming into a junction: its moves and its arrow (`urban.approach`) |
| **street object** | a thing that stands in the street (`urban.object`): a `group.class` such as `furniture.bench` |
| **match** | one real object that several sources describe, with every source's id |
| **link** | a ramp, stairs, an elevator, an entrance or a connection between two levels at a shared node (`urban.link`) |
| **station**, **entrance** | a rail, subway or tram station and its entrance (`urban.station`) |
| **lot** | an off-street car park (`urban.lot`), a piece of its block |
| **deck**, **tube**, **portal**, **landing** | a road above the ground; the area of a deck or a tunnel; where a tunnel meets the ground; where a deck meets the ground |

## The bridge model

| Term | Meaning |
|---|---|
| **bridge profile** | one JSON file per bridge: the deck outline, the axes, the vertical profiles, the sections, the bands and the piers, each value with its source and method; scripts make it; the 3D model reads only this file |
| **axis** (of a bridge) | one chain of OSM road ways on the deck between two branch points; the reference line of `(s, t)` |
| **vertical profile** | the height of the deck top along an axis, as points `(s, z)` |
| **section** (of an axis) | a length of the axis where its bands do not change |
| **band** | one strip across a section: a lane with its GMNS lane id, at offset `t` with its width |
| **station** (LiDAR) | a point every 10 m along an axis where the deck top and the ground are read from the LiDAR returns |
| **z_datum** | what `z` is measured from |

## Positions

| Term | Meaning |
|---|---|
| **(s, t)** | a position along a reference line: `s` metres from its start, `t` metres across, left positive; as OpenDRIVE and IFC |
| **UTM** | the metric coordinate system the build measures in; results are stored in lon/lat |

## Data and ids

| Term | Meaning |
|---|---|
| **duckOSM** | the project that turns an OSM extract into a DuckDB file: the raw nodes and ways, the driving, walking and cycling networks, the feature layers |
| **edge** | one directed piece of a road network between two nodes |
| **GMNS** | duckOSM's export of the network with its lanes, as SUMO makes them |
| `urban.*` | the tables urbanstyle writes, one per rank: `area`, `ground`, `stretch`, `plot_piece`, `space`, `side`, `part`, `mark`; on the tree: `element`, `joint`, `junction`, `street`, `arm`, `turn`, `approach`, `object`, `link`, `station`, `surface`, `observed`, `photo` ([The tables](tables.md)) |
| **common columns** | the columns every rank table has, in this order: `<thing>_id`, `kind`, `rank`, `parent_id`, `level`, `name`, the thing's values, `source`, `method`, `ref`, `geometry` |
| `urban.item` | the view over every rank: `id`, `rank`, `kind`, `parent_id`, `level`, `geometry` |
| `urban.meta` | the manifest of a build: its version and date, the input files with their dates, every chosen value with its name |
| `urban.check` | one row per check per build: its status, its count and the faulty things |
| `urban.registry` | the stable ids: one row per profile, with `uid`, `first_seen` and `last_seen` |
| **profile** | the facts of a thing that do not change, as text; its `uid` belongs to the profile (requirement R6) |
| `uid` | a thing's stable id, a UUID from the registry; the readable id stays as its label |
| `urban.style` | how a viewer draws each table and kind: `draw_order`, form, colour, dash, `raise_m` ([Drawing the tables](drawing.md)) |
| **draw order** | the place of a kind in the stack of one level: lower first; the levels themselves are drawn from the lowest up |
| `urban.code` | our kinds with their codes in CityGML 3.0, OpenDRIVE, OpenSidewalks and IFC 4.3 |
| **axis** | a linear thing's middle line, from its start to its end; `s_from`, `s_to`, `t_from`, `t_to` place a thing on its parent's axis |
| **predecessors**, **successors** | the spaces, or the lanes, that come before and after a space or a lane along the street |
| **source**, **method**, **ref** | who gave a value, how they got it, which of their items it is ([Sources and provenance](sources.md)) |
| **pilot dossier** | everything known about one pilot, an intersection or a street section studied in full, from every source, in one database, each row with its source, method and confidence |
| **inventory** | what each source holds around a pilot and how much reaches the tables |

## Terms from the standards

| Term | Where | Meaning |
|---|---|---|
| **TrafficSpace**, **AuxiliaryTrafficSpace** | CityGML 3.0 | the area used by traffic; the area beside it |
| **Section**, **Intersection** | CityGML 3.0 | a stretch of road; the area where roads meet |
| **CityFurniture** | CityGML 3.0 | immovable street objects |
| **lane section** | OpenDRIVE | a stretch of road with a fixed set of lanes |
| **frontage, pedestrian, furnishing, curb zone** | NACTO, Seattle | the bands of the walking side, from the building to the kerb |
| **segment** | Streetmix | one typed band of a cross-section with a width |
| **IfcRoadPart** | IFC 4.3 | a longitudinal or lateral part of a road |
