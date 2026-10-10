# How standards layer a street (research)

Status: research, 2026-10-10. Why: our parts are one flat layer in which a later part cuts an earlier one ("a part takes only ground no
earlier part took"), so a crosswalk cuts every lane it crosses, SUMO's nodes break lanes, and a junction's area is what is left over:
around Broadway × Granville 301 of 1,056 lane pieces in junctions are under 5 m², 274 lanes are in several pieces, 42 of 104 junctions
have their area in 2-8 pieces. The question: how do the standards structure a street, what lies on what, and what type and shape has
each thing.

Read from the specifications (links per row); where a detail is not in a normative text it says so. OpenDRIVE read at 1.9.0 (1.8.0's
pages are gone), whose pages mark the version each feature came in.

## 1. The comparison

| | hierarchy | what tiles (no overlap) | what overlays (lies on top) | a crosswalk over lanes | a lane's continuity |
|---|---|---|---|---|---|
| **OGC CityGML 3.0** Transportation ([OGC 20-010](https://docs.ogc.org/is/20-010/20-010.html), [XSD](https://schemas.opengis.net/citygml/transportation/3.0/transportation.xsd); modelling guideline [Road2CityGML3](https://tum-gis.github.io/road2citygml3/), informative) | Road / Track / Railway / Waterway → Section, Intersection (an intersection shared by several roads) → TrafficSpace, AuxiliaryTrafficSpace (granularity `way` or `lane`) → their boundary surfaces TrafficArea, AuxiliaryTrafficArea; Marking and Hole on the road / section / intersection; Square for plazas and car parks | the standard says nothing; the guideline: TrafficAreas "should not have overlapping geometries" | Markings ("independent of level of granularity", may span several areas), Holes (a manhole may span several objects) | guideline: its own TrafficArea with two functions, `driving lane` + `crosswalk`: **lanes are cut** | `predecessor` / `successor` between traffic spaces; no lane id kept across a section, a crosswalk or an intersection |
| **IFC 4.3** road ([IFC4.x source](https://github.com/buildingSMART/IFC4.x-development); the HTML site refused us) | IfcRoad → IfcRoadPart (any depth; `UsageType` LONGITUDINAL, LATERAL, REGION, VERTICAL) → elements contained in exactly one part (IfcPavement, IfcCourse, IfcKerb, IfcSign, IfcSignal) | not stated (only IfcSpace may be restricted to non-overlapping) | IfcSurfaceFeature (markings) adhered to the pavement, never a spatial part; IfcSpatialZone "non-hierarchical and potentially overlapping" | not specified; the schema states overlaps as relations: IfcRelInterferesElements `Crosses` / `PassesOver` (its own example: a road-rail level crossing) | the alignment (linear placement); no lane graph |
| **ASAM OpenDRIVE** 1.8-1.9 ([spec](https://publications.pages.asam.net/standards/ASAM_OpenDRIVE/ASAM_OpenDRIVE_Specification/v1.9.0/specification/)) | road (reference line) → laneSection (a new one where the lane count changes) → left / center / right lanes (ids ±1, ±2 from the centre); objects and signals on the road; junctions separate, holding connecting roads | the lanes of a lane section, across | objects (outline in road coordinates, `validity fromLane toLane`): crosswalk, parkingSpace, roadMark, trafficIsland, roadSurface; signals (stop lines); a temporary lane layer "on top of" the permanent one | an object of type crosswalk over the lanes (lanes not split), or, recommended for simulation, a `crossPath` (1.8) linking walking lanes in a junction | lane `predecessor` / `successor` across sections and roads; `laneLink` through junctions |
| **Lanelet2** ([paper](https://www.mrt.kit.edu/z/publ/download/2018/Poggenhans2018Lanelet2.pdf), [docs](https://github.com/fzi-forschungszentrum-informatik/Lanelet2/tree/master/lanelet2_core/doc)) | physical layer (points, linestrings) → relational layer (lanelets, areas, regulatory elements) → topological layer (routing graphs) | nothing required; neighbouring lanelets share their bounds | "lanelets can also overlap or intersect"; regulatory elements (signals, right of way, speed) referenced by the lanelets they govern | a lanelet of subtype `crosswalk` lying across the road lanelets, which stay whole; the routing graph records the **conflict** | successive lanelets share bound end points; a lanelet is cut only where its rules or topology change |
| **OpenStreetMap** ([area:highway](https://wiki.openstreetmap.org/wiki/Key:area:highway), [Street area](https://wiki.openstreetmap.org/wiki/Proposal:Street_area), [lanes](https://wiki.openstreetmap.org/wiki/Key:lanes), [street parking](https://wiki.openstreetmap.org/wiki/Street_parking)) | the routable line; lanes as counts and `*:lanes` attributes; areas, sidewalks, parking as separate objects | none prescribed | lane areas drawn inside their road's area (the proposal); junction areas separate where three or more lines meet | a crossing way and a crossing node; an area optional | the way is split where the lane count changes |
| **NACTO / GDCI** ([sidewalks](https://globaldesigningcities.org/publication/global-street-design-guide/designing-streets-people/designing-for-pedestrians/sidewalks/)), **Streetmix** ([segments](https://docs.streetmix.net/contributing/code/reference/segments)) | an ordered cross-section: frontage, clear path, street furniture, buffer (NACTO / GDCI); "a sequence of non-overlapping segments" (Streetmix) | the bands across | furniture and markings placed in a segment | not in the cross-section (intersections are separate chapters) | none (1-D) |

## 2. What they agree on

1. **A strict no-overlap rule holds only across a cross-section**: the lanes of a lane section (OpenDRIVE), a cross-section's segments
   (Streetmix), the sidewalk's zones (NACTO). Everything else is another layer, overlapping that one.
2. **The lane is what continues.** It is cut only where its count, type or rules change (OpenDRIVE's lane sections, Lanelet2's atomic
   lanelets), never where a crosswalk lies on it, and its pieces are chained by predecessor / successor (all three that model lanes).
3. **A crosswalk is an overlay that names what it crosses**, not a cutter: an object with a lane range (OpenDRIVE), an overlapping lanelet
   with a conflict relation (Lanelet2), an interference relation (IFC). Only CityGML's guideline cuts, and it then needs two functions on
   one piece to say what the overlap was.
4. **The junction is its own area, where lanes may overlap**: OpenDRIVE's junction (connecting roads overlap freely; a boundary since
   1.8), Lanelet2's overlapping lanelets, CityGML's Intersection, OSM's junction area.
5. **Paint is attached, never cut into the surface**: markings on lane borders or on objects (OpenDRIVE), linestrings (Lanelet2), surfaces
   independent of granularity (CityGML), surface features on the pavement (IFC).
6. **Rules are their own things that point at what they govern**: signals with validity (OpenDRIVE), regulatory elements (Lanelet2).

## 3. Types and shapes: where they differ

| thing | CityGML 3.0 | IFC 4.3 | OpenDRIVE | Lanelet2 | ours today |
|---|---|---|---|---|---|
| a lane | TrafficSpace (`lane`) + TrafficArea, function driving_lane / cyclepath / bus... | IfcRoadPart TRAFFICLANE | lane, type driving / biking / walking / parking / shoulder / curb / median / border / ... (a strip from the reference line) | lanelet (two bounds), subtype road / bus_lane / bicycle_lane / walkway ... | part `lane` (a polygon, cut into pieces) |
| a crosswalk | TrafficArea function crosswalk (cut, + driving_lane) | PEDESTRIAN_CROSSING | object `crosswalk` (outline + stripes) or crossPath | lanelet `crosswalk` (overlapping) | part `crosswalk` (cuts lanes) |
| the junction's area | Intersection (class: T, 4-way, roundabout) | INTERSECTION / ROUNDABOUT | junction (boundary since 1.8) | overlapping lanelets with virtual bounds | part `junction area` (what is left) |
| street parking | TrafficArea function parking_lay_by | PARKINGBAY / LAYBY | lane type parking, or object parkingSpace | area `parking` | part `parking` |
| a bus stop | TrafficArea function bus_lay_by | BUS_STOP | (object / signal) | (regulatory element) | parts `bus stop`, `bus zone` |
| kerb | AuxiliaryTrafficArea kerbstone / low kerbstone | IfcKerb | lane type curb; roadMark curb | linestring curbstone (high / low) | mark `kerb` |
| median, island | AuxiliaryTrafficArea raised_median, traffic_island | CENTRALRESERVE, TRAFFICISLAND, REFUGEISLAND | lane type median; object trafficIsland | area traffic_island | part `island` |
| sidewalk | TrafficArea footpath | SIDEWALK | lane type walking | lanelet walkway | parts sidewalk, furnishing, open |
| markings | Marking (class stop, crosswalk, lane_solid, arrows ...) | IfcSurfaceFeature LINEMARKING, SYMBOLMARKING ... | roadMark, object markings, signals for stop lines | linestrings stop_line, zebra_marking, arrow ... | marks (lines) |
| manhole, drain | Hole | (element) | object | — | object |

Each standard's own lists: CityGML guideline functions (TrafficArea: 1 driving_lane, 2 footpath, 3 cyclepath, 7 parking_lay_by, 20
crosswalk, 32 bus_lay_by, ...; AuxiliaryTrafficArea: 1010 shoulder, 1020 green_area, 1220 kerbstone, 1300 traffic_island, 1400
raised_median, ...; Marking: 15 crosswalk, 16 stop, 121-125 arrows, 131 lane_broken, 132 lane_solid, ...); IfcRoadPartTypeEnum (BICYCLECROSSING,
BUS_STOP, CARRIAGEWAY, CENTRALISLAND, CENTRALRESERVE, HARDSHOULDER, INTERSECTION, LAYBY, PARKINGBAY, PASSINGBAY, PEDESTRIAN_CROSSING,
RAILWAYCROSSING, REFUGEISLAND, ROADSEGMENT, ROADSIDE, ROUNDABOUT, SHOULDER, SIDEWALK, SOFTSHOULDER, TRAFFICISLAND, TRAFFICLANE, ...);
OpenDRIVE e_laneType (driving, biking, walking, parking, curb, median, border, shoulder, restricted, stop, entry, exit, slipLane, shared,
roadWorks, tram, rail, none) and e_objectType (crosswalk, parkingSpace, roadMark, trafficIsland, roadSurface, barrier, pole, tree, ...);
Lanelet2 subtypes (lanelet: road, highway, play_street, emergency_lane, bus_lane, bicycle_lane, exit, walkway, shared_walkway, crosswalk,
stairs; area: parking, freespace, vegetation, keepout, building, traffic_island; linestring: curbstone, stop_line, zebra_marking, arrow,
virtual, ...).

## 4. Recommendation

Follow the model the lane-level standards share (OpenDRIVE, Lanelet2, IFC's relations), keep CityGML's names for the containers and for
export:

| layer | what | rule | standard |
|---|---|---|---|
| 0 space | road, section, intersection, square (car parks, plazas) | as now (`space.unit`, `space.lot`) | CityGML Road / Section / Intersection / Square |
| 1 surface | roadway and pedestrian realm, split at the kerb | tiles its space | CityGML TrafficSpace / AuxiliaryTrafficSpace (`way`) |
| 2 bands | across a section: lanes (one per lane from the space's edge to the next change of count, type or rule, chained by predecessor / successor), shoulders and kerb strips, medians; the pedestrian realm's zones: frontage, clear path, furniture, buffer; in a junction: one junction area | tiles its surface, across only | OpenDRIVE lanes and types; NACTO / GDCI zones; CityGML Intersection |
| 3 overlays | crosswalks and cycle crossings (with the lanes they cross), parking and bus zones (with the lane or strip they use), tree pits, driveway aprons | lie on bands, cut nothing, name what they lie on | OpenDRIVE objects with lane validity; Lanelet2 conflicting lanelets; IFC `Crosses` |
| 4 markings and rules | lines and symbols on a lane's border or an overlay; signals, signs and turn rules pointing at the lanes they govern | attached | OpenDRIVE roadMark / signals; Lanelet2 linestrings and regulatory elements; CityGML Marking |
| 5 objects | furniture, trees, utilities, each in the band or overlay it stands in | points with a size | CityGML CityFurniture, Hole |

Types: our own names, each mapped to OpenDRIVE (lane and object types), CityGML (function codes) and IFC (road part types) in one table,
so an export to any of the three is a lookup. Where the three disagree on a thing's kind or shape (a crosswalk is an area in CityGML, an
object or a path in OpenDRIVE, a lanelet in Lanelet2), we keep the richest: the crosswalk's area as an overlay **and** its walking path
across the lanes. An export to CityGML can cut lanes at crosswalks as its guideline asks; the cut is derived from the layers, not stored.

Checks change with it: every layer covers its parent exactly and nothing overlaps within a layer (per layer, as U8 / U9 today); every
overlay names at least one band it lies on; every lane piece has a predecessor or successor unless it starts or ends at a junction or an
edge.

Not decided here: the design note for building it (`space-layers.md`), the stable ids that come with it, and the order of work.
