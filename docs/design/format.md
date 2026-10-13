# The urbanstyle format: requirements

Status: requirements, 2026-10-13. This note collects what the versioned specification of the format must meet. The research behind it is
[Our format and the standards](standards-comparison.md). Each requirement says whether it is **agreed** with Kaveh or **proposed**.

## What the format is

An open format for city street space: the street between the blocks, divided into sections, intersections and parts, with its
markings, objects, bridges and levels, and the source of every value. urbanstyle builds it from open data. DuckDB stays the working
store (the dashboard, the checks and the agent read it); the format is what urbanstyle publishes and exchanges, written by an export
command (planned: `urbanstyle export DB OUT`).

## Requirements

### R1. A profile of CityGML 3.0, encoded as a CityJSON Extension (agreed 2026-10-13)

- The encoding is CityJSON 2.0: one `.city.json` file for an area, or `.city.jsonl` (CityJSON Sequence) for a large area.
- The names and the structure are those of the CityGML 3.0 Transportation module: `Road`, `Section`, `Intersection`, `TrafficSpace`,
  `AuxiliaryTrafficSpace`, `TrafficArea`, `AuxiliaryTrafficArea`, `Marking`, `CityFurniture`, `Bridge`, `Building`, `LandUse`.
- CityJSON leaves out `Section`, `Intersection` and the space classes. The Extension adds them back with the CityGML 3.0 names, so that
  an export to CityGML 3.0 (GML) keeps them.
- What only urbanstyle has goes into Extension attributes (names start with `+`): `+sources`, `+level`, (s, t), the blocks and the
  ground layers, and the results of the checks.
- The Extension has a JSON Schema. Every published file passes CityJSON's validator (cjval) with it.

### R2. The source and the method of every value (agreed: the core of urbanstyle)

- `+sources` is a list on each object. Each entry names the value it is about (a JSON Pointer, as in Overture: `""` for the whole
  object, `/geometry`, `/attributes/width`), and gives `source` (osm, a city's dataset, LiDAR, SUMO, Mapillary, urbanstyle), the
  record id, the date of the source, and `method`: mapped, measured, observed, derived or chosen.
- A value that no source gives is urbanstyle's own: `source` urbanstyle, `method` derived or chosen. It is never called a default.

### R3. Both views in one file: areas (CityGML) and the walking graph (OpenSidewalks) (agreed 2026-10-13)

- **One thing, two shapes, one id.** Each sidewalk, crossing and footway carries its area (a LOD2 surface: the CityGML view) and its
  centre line (a LOD0 line: an OpenSidewalks edge).
- **The graph.** `predecessor` and `successor` (CityGML 3.0) link the lines. A kerb where a crossing meets a sidewalk is a node object
  of its own (`+KerbNode`), with its own id.
- **OSM's keys for the details of walking**, in the attributes: `kerb` (raised, lowered, flush, rolled), `tactile_paving`,
  `crossing:markings`, `incline`, `width`, `surface`. OpenSidewalks uses OSM's keys too, so no value needs a translation.
- **The OpenSidewalks export is a rewrite only:** the lines, the nodes and the OSM-key attributes, with nothing added or guessed. The
  build validates the export against the OpenSidewalks JSON Schema, so a drift between the two shows at once.
- OpenSidewalks has no levels and no bridges: a sidewalk on a bridge is exported as a normal edge with its incline (from our heights);
  its level stays in the urbanstyle file only.
- Licence: OpenSidewalks' schema is CC BY-ND 4.0. The export writes data that follows the schema; it does not change the schema.

### R4. Positions (agreed: as built)

- Coordinates in a projected CRS (the area's UTM zone), with CityJSON's integer vertices and `transform`.
- (s, t) along each subsection's axis: s in metres from its start, t in metres across, **positive to the left** (as OpenDRIVE and IFC;
  INSPIRE uses the opposite sign).

### R5. Levels (agreed: as built)

- `+level`: an integer, −2 … 2, 0 the ground. The links between levels (ramps, stairs, lifts) are objects of their own.
- CityGML's `relativeToTerrain` is also filled, from the level, for tools that read only CityGML.

### R6. Stable ids from profiles (agreed 2026-10-13)

The idea (Kaveh): every thing has a **profile**, made only of facts that do not change. The id belongs to the profile.

- **The registry** (a table for each area, kept from build to build): `profile → id`, with `first_seen` and `last_seen`.
- **At each build, for each thing:** make its profile and look it up in the registry. If an equal profile is there, the thing takes
  that id. If not, it is a new thing: it gets a new id (a UUID), and its profile and id go into the registry.
- **The profiles**, kind by kind:

  | Kind | Profile |
  |---|---|
  | street object (tree, lamp, bench, …) | its source and the source's own record id (`city public-trees 152690`, `osm n13983466896`) |
  | building | its OSM or city building id |
  | intersection | the names of the streets that meet there (`Granville St + W Broadway`) |
  | section | its street's name and the two intersections at its ends |
  | subsection | its section and its number along it (1, 2, …) |
  | lane, sidewalk zone, other part | its subsection, its side and its place from the kerb (lane 1, 2, …) |
  | block | the names of the streets around it |

  For example, the sidewalk on the east side of Granville Street between West Broadway and West 8th Avenue has the profile
  `Granville St | W Broadway–W 8th Ave | subsection 1 | east | sidewalk`. When a way is split in OSM, nothing in it changes, and the
  id stays.
- **When a profile changes, the id changes.** A street that is renamed, or a new intersection on a section, makes a new thing: that is
  correct, because it is a different thing then. The registry keeps the old profile with its `last_seen`.
- **First task: real source ids.** A city object's id today is its row in our download (`public-trees-0`), which can change at the
  next download. It must be the city's own record id (the tree's `asset_id`, for example 152690). OSM ids are already the source's own.
- **Still to decide:** the profile of a street with no name (an alley, a ramp), and of things in two intersections with the same
  street names (two crossings of the same two streets).
- **The id** goes in CityGML's `identifier`. **The readable code** (`s0-…`, `i0-…`, `b0-…`) stays as a label for people and the
  dashboard; it can change between builds. **External ids** (OSM, the city's records, Overture's GERS) go in `externalReference`.

### R8. The accuracy of every value (agreed 2026-10-13)

- Each `+sources` entry has `accuracy`: how far the value can be from the truth, in metres for a position or a width, or as a
  confidence from 0 to 1 for a class or a count.
- The accuracy comes from the source itself, where the source gives it: a city's record says "survey accuracy" or "approximate
  location" (we read these notes already); LiDAR heights are about ±0.1 m; Mapillary's positions lie a median 6 m from the city's
  surveyed poles (measured at Broadway × Granville). Where a source gives none (OSM), the value is urbanstyle's own class, with
  `method` chosen.
- A value that urbanstyle derives (a width between two edges) gets the accuracy of its inputs, combined.
- OpenDRIVE (`dataQuality`) and IFC (`Pset_Uncertainty`) record the same, but only for a whole element or object.

### R7. Exports (agreed: by use)

- OpenDRIVE 1.9 for driving simulation (SUMO, CARLA, esmini): lanes, junctions, `crossPath`, objects, signals, bridges.
- OpenSidewalks (R3) and OSM for walking and accessibility.
- GMNS for traffic models (duckOSM already writes it).
- IFC 4.3 only for a project hand-over.

## Still open

- An adjustment of the values with the connections between sources (R8 gives the weights): see the plan.

- Time: the date of each source value (R2) and two builds compared by stable id (R6): planned as "source dates".
- Signals with national codes (OpenDRIVE's `country`, `type`, `subtype`).
- Kerb rules by time of day (CDS), where a city gives them.
- The code lists for `function` and `usage` (CityGML defines them outside the standard; the SIG3D lists are the starting point).
