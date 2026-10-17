# The format

<p class="lead">An open format for city street space: the street between the blocks, divided into sections, intersections, spaces
and parts, with its markings, objects, bridges and levels, and the source of every value. DuckDB is the working store; the format is
what urbanstyle publishes and exchanges, written by an export command.</p>

## R1. A profile of CityGML 3.0, encoded as a CityJSON Extension

- The encoding is CityJSON 2.0: one `.city.json` file for an area, or `.city.jsonl` (CityJSON Sequence) for a large area.
- The names and the structure are those of the CityGML 3.0 Transportation module: `Road`, `Section`, `Intersection`, `TrafficSpace`,
  `AuxiliaryTrafficSpace`, `TrafficArea`, `AuxiliaryTrafficArea`, `Marking`, `CityFurniture`, `Bridge`, `Building`, `LandUse`.
- CityJSON leaves out `Section`, `Intersection` and the space classes. The Extension adds them with the CityGML 3.0 names, so that an
  export to CityGML 3.0 (GML) keeps them.
- What only urbanstyle has goes into Extension attributes, whose names start with `+`: `+sources`, `+level`, the (s, t) positions,
  the blocks, the ground and the results of the checks.
- The Extension has a JSON Schema. Every published file passes CityJSON's validator with it.

## R2. The source and the method of every value

- `+sources` is a list on each object. Each entry names the value it is about (a JSON Pointer: `""` for the whole object,
  `/geometry`, `/attributes/width`) and gives `source`, the record id, the date of the source and `method`: mapped, measured,
  observed, derived or chosen.
- A value that no source gives is urbanstyle's own: `source` urbanstyle, `method` derived or chosen. It is never called a default.

## R3. Both views in one file: areas and the walking graph

- One thing, two shapes, one id. Each sidewalk, crossing and footway carries its area (a LOD2 surface, the CityGML view) and its
  centre line (a LOD0 line, an OpenSidewalks edge).
- `predecessor` and `successor` (CityGML 3.0) link the lines. A kerb where a crossing meets a sidewalk is a node object of its own
  (`+KerbNode`).
- The details of walking use OSM's keys in the attributes: `kerb`, `tactile_paving`, `crossing:markings`, `incline`, `width`,
  `surface`. OpenSidewalks uses OSM's keys too, so no value needs a translation.
- The OpenSidewalks export is a rewrite only: the lines, the nodes and the OSM-key attributes, with nothing added. The build validates
  the export against the OpenSidewalks JSON Schema.
- OpenSidewalks has no levels and no bridges: a sidewalk on a bridge is exported as a normal edge with its incline, and its level stays
  in the urbanstyle file only.

## R4. Positions

- Coordinates in a projected CRS, the area's UTM zone, with CityJSON's integer vertices and `transform`.
- (s, t) along each subsection's axis: s in metres from its start, t in metres across, positive to the left, as OpenDRIVE and IFC
  have it.

## R5. Levels

- `+level`: an integer, -2 to 2, 0 the ground. The links between levels are objects of their own.
- CityGML's `relativeToTerrain` is also filled, from the level, for tools that read only CityGML.

## R6. Stable ids from profiles

Every thing has a profile, made only of facts that do not change, and the id belongs to the profile.

- A registry per area, kept from build to build, maps each profile to an id, with `first_seen` and `last_seen`.
- At each build, each thing's profile is looked up in the registry. An equal profile gives the thing that id. A new profile gets a new
  id, a UUID, and the registry keeps it.
- The profiles, kind by kind, are in [The tables](tables.md#the-registry-urbanregistry): every thing of every rank has one.
- When a profile changes, the id changes: a renamed street or a new intersection on a section is a different thing. The registry
  keeps the old profile with its `last_seen`.
- A city object's id is the city's own record id. OSM ids are the source's own.
- The id goes in CityGML's `identifier`. The readable code (`s0-…`, `i0-…`, `b0-…`) stays as a label for people and the dashboard.
  External ids (OSM, a city's records, Overture's GERS) go in `externalReference`.

## R7. Exports

- OpenDRIVE 1.9 for driving simulation: lanes, junctions, crossing paths, objects, signals, bridges.
- OpenSidewalks and OSM for walking and accessibility.
- GMNS for traffic models (duckOSM writes it).
- IFC 4.3 for a project hand-over.

## R8. The accuracy of every value

- Each `+sources` entry has `accuracy`: how far the value can be from the truth, in metres for a position or a width, or as a
  confidence from 0 to 1 for a class or a count.
- The accuracy comes from the source itself where the source gives it: a city's record says "survey accuracy" or "approximate
  location"; LiDAR heights are about 0.1 m. Where a source gives none, the value carries urbanstyle's own class for that source.
- A value that urbanstyle derives gets the accuracy of its inputs, combined.
