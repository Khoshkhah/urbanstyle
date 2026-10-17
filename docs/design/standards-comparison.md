# Our format and the standards

The question: before we write a versioned specification of our format ("an open format for city street
space, plus an open tool that builds it from open data"), how does it compare with the standards that exist? The facts on each standard
were checked against its specification, schema or repository; the sources are at the end. Where a fact was not checked,
the text says so.

## Summary

1. **No standard does what we do in one model.** Each standard covers one use: CityGML 3.0 the city in 3D, OpenDRIVE driving simulation,
   IFC 4.3 design and construction, OSM, Overture, GMNS and INSPIRE the network, OpenSidewalks the walking network, CDS the kerb rules.
2. **Our division of the street is the division of CityGML 3.0 and IFC 4.3.** A street is sections and intersections, and an
   intersection is shared by the streets that meet there. Inside, the parts are lanes, sidewalks, kerbs, medians and markings. So an
   export to these standards keeps our division.
3. **Some things only we have.** No standard gives the source and the method of each value. No standard has numbered levels for streets.
   No standard puts the street between blocks, or checks its own data with fixed rules.
4. **Some things they have that we lack.** Lane links for routing, signals with national codes, solid 3D, a model of time and versions,
   rules for stable ids, kerb rules by time of day, external code lists, and a formal schema with validation.
5. **Recommendation.** Do not write a new standard from zero. Write our format as a profile of CityGML 3.0 (encoded as a CityJSON
   Extension) for the street space, and add to it what only we have. Export to OpenDRIVE for simulation and to OpenSidewalks or OSM for
   walking. Add an IFC export only when a project hand-over needs it.

## 1. The standards in short

| Standard | Purpose | Version (2026-10) | Body | Licence of the specification | Encoding |
|---|---|---|---|---|---|
| **CityGML 3.0** (Transportation module) | the city in 3D: buildings, transportation, furniture, land use | 3.0 (2021); GML encoding 2023 | OGC | royalty-free | GML; CityJSON |
| **CityJSON 2.0** | the JSON encoding of CityGML 3.0, a subset | 2.0.2 (2026-03) | OGC community standard, TU Delft | CC0 | JSON, JSON Lines |
| **ASAM OpenDRIVE** | road networks for driving simulation | 1.9.0 (2026-05) | ASAM | free download with registration, ASAM terms (not an open licence) | XML (.xodr) |
| **Lanelet2** | maps for automated driving (Autoware) | 1.2.3 (2026-06) | FZI, open source | BSD-3 | OSM XML |
| **IFC 4.3** | design and construction of roads and bridges (BIM) | ISO 16739-1:2024; IFC 5 in alpha | buildingSMART, ISO | CC BY-ND 4.0 (text); free to use | STEP (.ifc), ifcXML |
| **OGC LandInfra / InfraGML** | civil engineering design (alignments, cross-sections) | 1.0 (2016–2017) | OGC | royalty-free | GML; little used |
| **INSPIRE Transport Networks** | EU road and rail networks | TG 3.2 (2024); the binding rules may be repealed (2025 proposal) | EU | free | GML |
| **GMNS** | networks for traffic models | 0.97 (2026-03) | Zephyr, FHWA | Apache-2.0 | CSV with table schemas |
| **OpenStreetMap** | the open world map | tagging conventions | OSM Foundation | data ODbL | PBF, XML |
| **Overture Maps** (transportation) | an open map from many sources | schema 2.0 (2026-09), monthly releases | Overture Maps Foundation | schema CC BY 4.0; data ODbL | GeoParquet |
| **OpenSidewalks** | the walking network: sidewalks, crossings, kerb ramps | 0.3, a draft (2026-01) | Taskar Center (US DOT TDEI) | CC BY-ND 4.0 (no derivative works) | GeoJSON with JSON Schema |
| **Curb Data Specification (CDS)** | kerb zones and their rules by time | 1.1.0 (2025-10) | Open Mobility Foundation | CC BY 4.0 | JSON REST API |

## 2. Side by side

| Topic | Ours | CityGML 3.0 | OpenDRIVE 1.9 | IFC 4.3 | OSM, Overture | OpenSidewalks |
|---|---|---|---|---|---|---|
| **The street along** | section → subsections; the street between two blocks | `Road` → `Section` | `road` with lane sections | `IfcRoad` → `IfcRoadPart` (longitudinal: `ROADSEGMENT`) | a line, split where a tag changes | edges of a graph |
| **The junction** | intersection, its own space, shared by the streets that meet there (`urban.arm`) | `Intersection`, "shared by several roads" | `junction`, roads end at it; `crossing` junctions | `INTERSECTION`, `ROUNDABOUT` road parts | a node | a node |
| **Across the street** | parts: lanes, shoulders, medians, pedestrian zones, kerbs | `TrafficSpace` / `AuxiliaryTrafficSpace`, granularity `lane` or `way` | lanes with id, left + / right −, width polynomials | lateral road parts: `TRAFFICLANE`, `SIDEWALK`, `SHOULDER`, `CENTRALRESERVE`, … | tags on the line: `lanes`, `sidewalk`, `width`; Overture: widths only | sidewalk edges |
| **The pedestrian realm** | sidewalk zones (NACTO), crossings, pedestrian corners | `TrafficArea` with a function code | `walking` lanes, `crossPath`, the junction boundary | `SIDEWALK`, `PEDESTRIAN_CROSSING` | `footway=sidewalk` lines, crossing nodes | the main subject: sidewalks, crossings, kerb ramps |
| **Kerbs** | a part with its height | `AuxiliaryTrafficArea` | lane type `curb`, road mark `curb` | `IfcKerb` (physical) | `barrier=kerb` nodes | kerb nodes (raised, lowered, flush) |
| **Markings** | `urban.mark`: lines, stop lines, arrows, zebras | `Marking` surfaces | `roadMark` per lane | `IfcSurfaceFeature` (`LINEMARKING`, …) | few tags | no |
| **Street objects** | one object per real thing, matched from all sources, with every source's id | `CityFurniture` | `object` (pole, tree, barrier, …) and `signal` with country codes | `IfcSign`, `IfcSignal`, others | nodes with tags; Overture: none | trees, benches, poles, hydrants, … |
| **Land beside the street** | blocks, ground cover, surfaces, parcels, buildings | `LandUse`, `Building` | `building` object only | not in the road model | areas with tags | buildings |
| **Bridges and levels** | numbered levels −2 … 2; the bridge profile: axes, heights from LiDAR, piers | a road on a bridge is also the bridge's roof (`CityObjectRelation`); no levels | elevation along s; `bridge`, `tunnel` objects; no levels | `IfcBridge` parts; vertical facility parts | `layer` (an order only), `bridge` flag | none |
| **3D** | the 3D model from the data (decks, kerbs, objects); not solids | LOD 0–3, solids | elevation, superelevation, shape, OpenCRG | full solids, swept along the alignment | none | `incline` only |
| **Positions** | lon / lat, and (s, t) along each subsection's axis, **t positive to the left** | coordinates only, no linear referencing | (s, t, h), t positive to the left | alignment + `IfcPointByDistanceExpression`, lateral offset positive to the left | coordinates; Overture `between` ranges 0–1 | coordinates |
| **Source of each value** | **every value: source and method** (mapped, measured, observed, derived, chosen), and the reference | none per value; external references per object | `dataQuality` per element: error in metres, source type, processing | per object or property set (`IfcOwnerHistory`, `Pset_Uncertainty`) | OSM: free text `source`; **Overture: `sources` per value** (dataset, record id, date, confidence), no method | per dataset only |
| **Time** | not yet (planned: source dates) | bitemporal dates on every feature; a versioning module | the header date; temporary lane layers and objects | the owner history only | OSM: `check_date`, element history; Overture: monthly releases | per dataset |
| **Ids** | content ids (`s0-…`, `i0-…`, `b0-…`, part ids) | `gml:id` and an `identifier` that stays across versions | ids in the file | GUIDs | OSM ids; Overture GERS ids with a registry | ids in the file |
| **Checks** | fixed rules on the data (B, G, L, R, U, BR), each fault with a link | schema validation | schema (XSD) and rule ids | schema, model view definitions | none; tools such as validators | JSON Schema |

## 3. Our things in each standard

This table is the core of an export: one lookup for each of our kinds.

| Ours | CityGML 3.0 | OpenDRIVE | IFC 4.3 | OSM | OpenSidewalks |
|---|---|---|---|---|---|
| street (`k0-…`) | `Road` | the roads of one name | `IfcRoad` | a named way | no |
| section, subsection (`s0-…`) | `Section` | a road, lane sections | `IfcRoadPart` `ROADSEGMENT` | way pieces | no |
| intersection (`i0-…`) | `Intersection` | `junction` | `IfcRoadPart` `INTERSECTION` | the node | the node |
| lane | `TrafficSpace` (granularity `lane`) + `TrafficArea` | lane, type `driving` | `TRAFFICLANE` | `lanes`, `turn:lanes` | no |
| cycle lane | `TrafficSpace`, usage bicycle | lane, type `biking` | `TRAFFICLANE` + property (no own value) | `cycleway=*` | no |
| shoulder, parking | `TrafficSpace` / `AuxiliaryTrafficSpace` | `shoulder`, `parking` | `SHOULDER`, `PARKINGBAY` | `parking:*` | no |
| median, island | `AuxiliaryTrafficSpace` | `median` | `CENTRALRESERVE`, `TRAFFICISLAND` | `area:highway=traffic_island` | traffic island edge |
| sidewalk zones | `TrafficSpace`, function sidewalk | `walking` lanes | `SIDEWALK` | `footway=sidewalk` | sidewalk edges |
| kerb | `AuxiliaryTrafficArea` | `curb` lane | `IfcKerb` | `barrier=kerb` | kerb nodes |
| crosswalk | `TrafficSpace` + `Marking` | `crossPath` + `crosswalk` object | `PEDESTRIAN_CROSSING` | `highway=crossing` | crossing edges |
| line, arrow, zebra | `Marking` | `roadMark` | `IfcSurfaceFeature` | rarely | no |
| street object | `CityFurniture` | `object`, `signal` | `IfcSign`, `IfcSignal`, … | node | point |
| block, ground, surface | `LandUse` | no | no | areas | no |
| building | `Building` | `building` object | not in the road model | `building=*` | building |
| bridge deck, pier | `Bridge`, `BridgePart` | `bridge` object + elevation | `IfcBridge`, `DECK`, `PIER` | `bridge=yes`, `layer` | no |
| level | `relativeToTerrain` (words) | none (z) | `VERTICAL` facility part | `layer` | none |
| source and method of a value | an Extension | `dataQuality` (per element) | `Pset_Uncertainty` (per object) | `source:*` (text) | per dataset |

## 4. What we can take over

1. **CityGML 3.0's names and its two-level division.** `Section`, `Intersection`, `TrafficSpace`, `AuxiliaryTrafficSpace`,
   `Marking`. The SIG3D code lists for `function` and `usage` (the guideline points to them for 3.0).
2. **Lane links for routing.** CityGML's `predecessor` / `successor` and OpenDRIVE's lane links. We have them in part
   (`urban.turn`, the joints of `division.join_lanes`); they should be one table.
3. **OpenDRIVE's walking model.** `walking` lanes, `crossPath` from sidewalk to sidewalk, and the junction boundary. Our crosswalk
   already follows `crossPath`.
4. **Signals with country codes** (OpenDRIVE: `country`, `type`, `subtype`). Our signs have only a class.
5. **Overture's `sources` shape.** A list per feature, each entry naming the value it is about (a JSON Pointer), the dataset, the
   record id, the date and a confidence. With our `method` added, it is the source model we need.
6. **A model of time.** CityGML's two times (when the data changed, when the real thing changed), and CDS's rule: a new geometry
   gets a new id, and the old one stays with a link to the new one. This is the planned "source dates" work.
7. **Stable ids with a registry** (Overture GERS: first seen, last seen, last changed).
8. **Kerb rules by time of day** (CDS) for parking and loading, when a city gives them.
9. **A formal schema** (JSON Schema, as CityJSON Extensions and OpenSidewalks use) and a validator that runs our checks.

## 5. What is ours alone

1. **The source and the method of every value.** No standard has it. OpenDRIVE and IFC have it for a whole element or object, Overture
   for each value but without the method. This is the core of the format, and the reason a city can trust or fix a value.
2. **Numbered levels** −2 … 2 for every street space, with the links between levels. The standards use heights only (OpenDRIVE,
   IFC), words (CityGML `relativeToTerrain`) or an order (OSM `layer`, Overture `level_rules`).
3. **The street between two blocks.** The street space is the ground outside the blocks, divided between neighbouring blocks. The
   standards start from the road line or from a design; none uses the blocks as the frame.
4. **One object per real thing from all sources**, with every source's id and what each source says of it.
5. **Checks with links.** Fixed rules on the data (for example a lane with no arrow, deck that no part covers) that every build runs.
6. **A build from open data only.** OpenDRIVE and IFC files come from design tools or surveys; ours comes from OSM, a city's open data,
   LiDAR and SUMO, with each source named.

## 6. Recommendation for the specification

1. **The base: CityGML 3.0, encoded as a CityJSON Extension.** CityJSON is open (CC0), JSON, has a JSON Schema and tools, and allows
   extensions with new objects and attributes. CityJSON leaves out `Section`, `Intersection` and the space classes; our Extension adds
   them back, with the names of CityGML 3.0, so a CityGML 3.0 export keeps them.
2. **Our additions, as Extension attributes:** `sources` (Overture's shape plus `method`), `level`, (s, t) along the subsection's axis
   with t positive to the left (as OpenDRIVE and IFC), the block and ground layers, and the check results.
3. **Exports, by use:**
   - OpenDRIVE 1.9 for driving simulation (SUMO, CARLA, esmini): lanes, junctions, `crossPath`, objects, signals, bridges.
   - OpenSidewalks or OSM for walking and accessibility. OpenSidewalks' licence (CC BY-ND) allows an export, but not an extension
     of its schema.
   - GMNS for traffic models (duckOSM already writes it).
   - IFC 4.3 only for a project hand-over. IFC has no value for a cycle lane, and it is made for design, not for an inventory of
     streets as they are.
4. **Not as a base:** OpenDRIVE (not an open licence, made for vehicles), IFC (per project), LandInfra (little used), INSPIRE (network
   only, and its binding rules may be repealed), OpenSidewalks (no derivative works).

Next step, if agreed: a versioned specification (`docs/design/format.md`), with the JSON Schema of the Extension and a validator.

## Sources

- CityGML 3.0 Conceptual Model: https://docs.ogc.org/is/20-010/20-010.html; transportation schema:
  https://schemas.opengis.net/citygml/transportation/3.0/transportation.xsd; GML encoding: https://docs.ogc.org/is/21-006r2/21-006r2.html;
  TUM guideline: https://tum-gis.github.io/road2citygml3/guideline/guideline.html; SIG3D code lists:
  https://www.sig3d.org/codelists/standard/transportation/
- CityJSON: https://www.cityjson.org/specs/2.0.2/, https://www.cityjson.org/citygml/v30/
- LandInfra: https://docs.ogc.org/is/15-111r1/15-111r1.html; InfraGML Roads: https://docs.ogc.org/is/16-104r2/16-104r2.html
- OpenDRIVE 1.9.0: https://publications.pages.asam.net/standards/ASAM_OpenDRIVE/ASAM_OpenDRIVE_Specification/v1.9.0/specification/index.html
- Lanelet2: https://github.com/fzi-forschungszentrum-informatik/Lanelet2; Autoware vector map:
  https://docs.autoware.org/main/design/autoware-architecture-v1/components/map/map-requirements/vector-map-requirements-overview/
- GMNS: https://zephyr-data-specs.github.io/GMNS/spec/
- IFC 4.3: https://github.com/buildingSMART/IFC4.3.x-development (IfcRoadPartTypeEnum, IfcFacilityUsageEnum,
  IfcPointByDistanceExpression, Pset_Uncertainty); IFC 5: https://github.com/buildingSMART/IFC5-development
- INSPIRE TN: https://github.com/INSPIRE-MIF/technical-guidelines/tree/main/data/tn; the 2025 revision:
  https://oeil.europarl.europa.eu/oeil/en/document-summary?id=1878164
- ISO 19148: https://www.iso.org/standard/75150.html
- OSM: https://wiki.openstreetmap.org/wiki/Key:area:highway, https://wiki.openstreetmap.org/wiki/Key:sidewalk,
  https://wiki.openstreetmap.org/wiki/Key:check_date; osm2streets: https://github.com/a-b-street/osm2streets
- Overture: https://docs.overturemaps.org/schema/reference/transportation/types/segment/level_rule/, https://docs.overturemaps.org/gers/
- CDS: https://github.com/openmobilityfoundation/curb-data-specification/blob/main/curbs/README.md
- OpenSidewalks: https://github.com/OpenSidewalks/OpenSidewalks-Schema
- Mapillary: https://www.mapillary.com/developer/api-documentation
