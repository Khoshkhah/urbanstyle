# Glossary

The words used in `docs/design/street-space.md`, `docs/design/street-objects.md`, the code and the dashboard, in one place. When a word is also
a column or a table name it is written in `code`. "Built" says whether it exists in the data today.

## Space and hierarchy

| term | meaning | built |
|---|---|---|
| **level** | an integer floor of the city: 0 = ground, positive = above (bridges, upper floors), negative = below (tunnels, basements, metro). Only -2 … 2 are kept; a road, walkway, rail line or station beyond that range is shown at the nearest kept level, a building lying wholly outside is dropped | yes |
| **street space** | the whole open strip of a street from the building (or wall) on one side to the one on the other: the right-of-way. It is *measured*, not drawn: see **section (cross-section)** | yes |
| **ROW** | right-of-way. Another name for the street space; also the name used by the street-design guides (Seattle, NACTO) | yes |
| **container** | one row of `space.container`: a named, non-overlapping piece of the street space at one level. Every point of the street space is in exactly one container. Its `kind` is `street`, `path`, `rail` or `intersection` | yes |
| **street** | a *group*, not a container: the roads of one level that share a name and are connected, divided at every junction into sections, plus the intersections it arrives at (`space.street`). Id `k<level>-<smallest OSM way id>`. One intersection can belong to several streets | yes |
| **section** | a container of kind `section`: the roads of one street between two junctions, with the walkways and cycleways that run along them (at least 60% of their length within 15 m). Id `s<level>-<smallest edge id>`. The CityGML `Section` | yes |
| **path space** | a connected network of footpaths and cycleways with no road within 15 m (park paths, alleys, steps). Id `p<level>-<smallest OSM way id>` | yes |
| **rail space** | a connected network of rail lines at one level, with a strip for the structure. Id `r<level>-<smallest OSM way id>` | yes |
| **intersection** | a container of its own at a junction (a node where 3 or more road elements meet), shared by the streets that meet there: the free space between the straight cuts across its arms (each at half the widest other arm's width + 1 m from the node), bounded by building faces, clipped to the street space. Junction nodes closer than 15 m are one intersection (while the cluster stays under 30 m across). Id `i<level>-<smallest OSM node id>`, stable across rebuilds | yes |
| **arm** | one road arriving at an intersection (`space.arm`): it links an intersection to a section and to a street group | yes |
| **junction** | a node with three or more road edges; a node with two is a continuation | yes |
| **zone** | what a part of a container is for: `travelway`, `pedestrian_realm` or `track`. One row of `space.zone` per container and zone | yes |
| **travelway** | the part of the street space where vehicles move. Measured out to the kerb where a sidewalk is found, else the lane width | yes |
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
| `space.*` | the tables this project writes: `element`, `container`, `zone`, `link`, `station`, `object` (and, planned, `axis`, `strip`, `boundary`); the network-first preview adds `subsection`, `unit`, `cut`, `part`, `mark`, `width`, `turn` |
| `space.junction` | the nodes of each junction of the network-first spaces: the container step's groups (`cluster_id`), a roundabout's group cut back to its ring ([network first](network-first.md)) |
| `space.observed`, `space.photo` | Mapillary's map features (`grp`: parking, no parking, give way, stop, traffic light, street light, bin, bench, lane arrow, zebra) and photo positions ([Mapillary observations](mapillary.md)) |
| `parking`, `no parking` (part types) | a shoulder where parking is mapped or signed; one where signs forbid it |
| **lot (`space.lot`)** | an off-street car park (OSM `amenity=parking` on the ground, not `parking=lane` / `street_side` / ...): private ground beside the street, like a building's plot. Id `w<way>`, with name, operator, parking, access, fee. The street space stops at its edge; its parking aisles (`service=parking_aisle`) are no street (2026-10-10) |
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

## Unit dossier

| term | meaning |
|---|---|
| **unit dossier** | everything known about one unit (an intersection or a street section) from every source, in `data/units/<name>.duckdb`, every row with its `source`, `method` and `confidence` (`docs/design/unit-dossier.md`) |
| **match** | one real object that several sources describe: the city's surveyed pole, OSM's node and Mapillary's detections of one street light are one `match` row (`match_id` `m<k>`, `sources`, `refs`: every source's own id); `object.match_id` links each source's object to it |
| **floors, height_m** | `space.element`: a building's real floors (`building:levels`, else from `height`) and height (`height`, else floors x 3 m), kept beside its clamped `level_min` / `level_max` (-2..2); 3D draws a building at its real height |
| **road information on a part** | `space.part` `road`, `road_class`, `speed`, `surface`, `lit`, `road_lanes`, `oneway`: what is known of the road a lane or shoulder belongs to (its OSM way, `ref`); a value OSM lacks is a stated default ("50 km/h (default in built-up areas; not in OSM)", "asphalt (assumed; not in OSM)") |
| **use, ground_use (`space.element`)** | what a building is used for (residential, retail, commercial, office, civic, industrial, ancillary, or mixed: homes or offices over shops) and its ground floor (retail, food & drink, services, leisure, civic, office, vacant, residential), each with `use_source` / `use_method` and `ground_source` / `ground_method`; `uses` lists the evidence: the OSM tag, the shops OSM maps inside, a city's storefronts (one business in both counts once). The popup shows them as use, ground_floor, evidence |
| **approach (`space.approach`)** | a lane coming into a junction: its moves, the ways it may go for all traffic, its turn arrow or why it has none; checks U11-U13 count what looks wrong |
| **furnishing strip, `holds`** | the strip by the kerb where street furniture stands (`space.part` type `furnishing`), only where some does; `holds` says what stands in it ("2 tree, 1 lamp"), each real object once whatever sources map it (OSM, Mapillary, a city's survey: `unit.group_objects`), `ref` their ids, `source` whose |
| **bus stop, bus zone (parts)** | a bus stop's waiting area on the sidewalk, and the kerb strip where its bus stops (no parking); the stop's tags in `holds`, its timetable (routes, buses per hour, from GTFS) in `rule` |
| **GTFS** | General Transit Feed Specification: an operator's timetable as open files (stops, routes, trips, times); `urbanstyle unit --gtfs URL` reads each stop's routes and weekday departures (`gtfs.py`) |
| **`width_m`, `length_m` (on a part)** | a lane's or kerb strip's measured width, else the width and length of the rectangle of the part's area and perimeter (`parts.strip_size`) |
| **confirmation (Mapillary)** | a source too rough to place things (`unit.CONFIRM_ONLY`: Mapillary) only confirms an object of a source with a real position (it joins its `match`); a group it alone sees is no object but a `check` row ("not confirmed"); the dashboard's "Mapillary detections (validation)" shows every detection, green where it confirms, orange where nothing does |
| **`rule` (on a part)** | the rules that apply to a part, in words, from their source: a parking strip's rates, time limits and rush-hour bans from the parking meters beside it |
| **inventory (dossier table)** | what each source holds around a unit (`source`, `layer`, `item`: an OSM key, a Mapillary class, a city dataset; `n`) and how much reaches our tables (`n_ours`), whether our code reads it (`read`); a gap is many items, nothing read |
| **vehicles, condition (turns)** | `space.turn`: who may make a move (NULL: all traffic; else e.g. `bus,taxi`) and when a time rule binds (e.g. `Mo-Su 07:00-19:00`), from duckOSM's turn rules |
| **junction area** | the roadway inside an intersection where the arms' carriageways meet and the turning corners between them (`space.part` type `junction area`, called "junction box" before 2026-10-09): an area of our model, nothing painted on the road; not the city's street-lighting junction box (type "electrical box", a lid in the pavement) |
| **ref** | an object's id in its own source (OSM node, Mapillary feature, a city's asset), kept so every drawn object leads back to where it came from |
| **source / method** | on every part, object and dossier row: where its data comes from (`osm`, `sumo`, `mapillary`, `vancouver`, `urbanstyle`) and how it was obtained (`surveyed`, `mapped`, `measured`, `derived`, `observed`, `estimated`, `checked`) |

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
