# Layers: the whole area, and the inside of a street, as a hierarchy

Status: agreed 2026-10-10; being built in the order below. Step 1 built (`ground.py`): Broadway × Granville's neighbourhood, 640,106 m²
at level 0: street 53.3 %, plot 44.7 %, green 1.3 %, rail 0.3 %, unknown 0.4 % (8 pieces, 2,517 m²; the largest, 1,515 m², West Broadway's
north side before the station site, right-of-way no street space reaches); no overlaps (G2). Basis: [How standards layer a street](layers-research.md).

## Why

Two problems with one cause: we describe space as one flat set of pieces.

- **Not the whole area.** Only street spaces, buildings and car parks exist; a yard, a plaza, a park, a construction site, the greenway are
  nothing, and blank on the map.
- **Crumbs inside the street.** Parts are one layer in which a later part cuts an earlier one: a crosswalk cuts every lane it crosses,
  SUMO's nodes break lanes, a junction's area is what is left over. Around Broadway × Granville 301 of 1,056 lane pieces in junctions are
  under 5 m², 274 lanes are in several pieces, 42 of 104 junctions have their area in 2-8 pieces; ids follow build order, so the same id
  names another part after a rebuild.

The standards (research note) agree on the cure: a strict no-overlap rule holds only within one layer of one parent; a lane continues and
is cut only where its count, type or rules change; a crosswalk, a parking zone, paint and rules lie on top and name what they lie on; the
junction is its own area; the top level covers all the ground (CityGML's top-level features: transportation, buildings, land use,
vegetation, water).

## The layers

Every item has a `layer`, a `parent_id` (the item it is part of, one layer up) and a `type`. Within one parent, the items of layers 0-2
cover it exactly and do not overlap; layers 3-5 lie on top and name what they lie on.

| layer | name | types | geometry | rule | parent |
|---|---|---|---|---|---|
| 0 | **ground** | `street`, `square`, `rail`, `plot`, `green`, `water`, `unknown` | polygon | at each level, the whole area: no gap, no overlap | the area (a level of a unit's neighbourhood) |
| 1 | **surface** | in a street: `roadway`, `cycle track`, `pedestrian realm`, `verge`, `median`, `track` (tram, rail in the street). In a plot: `building`, `car park`, `yard`, `garden`, `construction site`. In a square: `paved`, `green`. In green: `lawn`, `planting`, `path`, `play`. In rail: `track bed`, `path` | polygon | covers its ground item | a ground item |
| 2 | **bands** | in a roadway: `lane` (driving, bus, cycle, parking, turn ...), `shoulder`, `junction area`; in a pedestrian realm: `frontage`, `clear path`, `furniture`, `buffer` (NACTO / GDCI zones); in a cycle track: `lane` | polygon, and a centre line for a lane | covers its surface; across a road the lanes tile the roadway, each from the space's edge to the next change of count, type or rule | a surface item |
| 3 | **overlays** | `crosswalk`, `cycle crossing`, `parking zone`, `bus zone`, `no-parking zone`, `loading zone`, `tree pit`, `driveway apron`, `bus stop` (waiting area), `connection` (a lane-to-lane path through a junction) | polygon; a crosswalk also its walking line | lies on bands, cuts nothing; names every band it lies on (`on`) | the band or surface it lies on most |
| 4 | **markings and rules** | markings: `stop line`, `give-way line`, `lane line`, `edge line`, `centre line`, `zebra bar`, `arrow`, `kerb` (a line); rules: `signal`, `sign`, `turn rule`, `speed`, `parking rule` | marking: polygon of its real shape (a line with its width); rule: no geometry of its own | a marking is attached to a band's border or an overlay; a rule names the lanes it governs | the band, overlay or space it belongs to |
| 5 | **objects** | furniture, trees, utilities (as `space.object` today, `unit.SIZE`) | point with a width and a height | stands in one band or overlay | that band or overlay |

Types are our own names, each mapped in one table to OpenDRIVE (lane type, object type), CityGML (class and function code) and IFC
(IfcRoadPartTypeEnum, IfcSurfaceFeatureTypeEnum), so an export to any of them is a lookup. Where the standards disagree on a thing's kind or
shape we keep the richest form: a crosswalk is an overlay area **and** its walking line across the lanes (OpenDRIVE's crossPath).

### Layer 0: the ground

Built per level over the unit's neighbourhood (the clip's box), in this order, each kind taking only ground no earlier kind took:

1. `water`: OSM `natural=water`, `waterway` areas.
2. `rail`: OSM railway corridors (`landuse=railway`), a rail line's own space (`r<level>-<way>`).
3. `street`: our street spaces (`space.unit`: sections and intersections), as built today.
4. `square`: OSM pedestrian areas (`highway=pedestrian` + `area=yes`, `place=square`), plazas (`p` spaces today).
5. `plot`: a city's parcels where it has them (Vancouver `property-parcel-polygons`, [Plots](plots.md)); else buildings, car parks
   (`space.lot`), construction sites and OSM `landuse` areas (residential, retail, commercial ...) with what lies between them, block by
   block.
6. `green`: the rest of the green, OSM `landuse=grass`, gardens, allotments. Public green (parks, playgrounds, pitches, recreation grounds,
   woods) comes before `plot`: a city park is a parcel too, and would otherwise be a plot.
7. `unknown`: what is left. Reported (check G1), each piece with its area and its neighbours, so it can be traced to a missing rule.

A street's ground is fixed by the street's own rules (cuts, the building line); a plot's by its parcel, or by its buildings and land use;
the order above decides where two sources claim the same ground. The ground of one level is independent of another's (a bridge deck at
level 1 over a street at level 0).

### Layers 1-2 in a street

- **Section**: the roadway is tiled across by its lanes and shoulders. A lane is **one item** from the space's edge to the next point
  where the lane count, its type or its rules change (where SUMO starts a new edge for that reason), and each lane item names its
  `predecessor` and `successor` lanes. A crosswalk, a node of SUMO's that changes nothing, a parking meter do **not** cut a lane.
- **Intersection**: the roadway is the incoming and outgoing lanes up to their stop lines, and **one** `junction area` for the rest. The
  lane-to-lane paths across it are `connection` overlays (they overlap each other, as connecting roads do in OpenDRIVE).
- **Pedestrian realm**: tiled into NACTO's zones from the kerb outwards: `buffer` (where parking or bus stops meet the kerb, if any),
  `furniture` (where street furniture and trees stand), `clear path`, `frontage` (between the clear path and the building or plot line).
  Today's `sidewalk` becomes the clear path, `furnishing` the furniture zone, `open` a wide clear path or frontage.

### Relations (`space.relation`)

One table of typed links between items: `crosses` (a crosswalk -> each lane), `lies_on` (an overlay -> its bands), `continues`
(a lane -> its successor; a connection -> its from and to lanes), `governs` (a rule -> the lanes it applies to), `attached_to` (a marking
-> its band or overlay), `stands_in` (an object -> its band or overlay), `conflicts` (two overlapping connections or a connection and a
crosswalk). Each relation has a source and a method, like every item.

### Ids

Stable, from what an item is, never from build order: `g<level>-<type>-<source id>` for ground (`g0-plot-pl030585457`,
`g0-street-s0-2002513880381972879/1`); for items in a space, `<space id>:<type>:<key>`, the key from the source: a lane `<OSM way>:<direction>:
<lane from the kerb>:<n-th piece along>`, a crosswalk its OSM id, the junction area nothing (`i0-571700151:junction area`), a pedestrian zone
`<side>:<zone>`, a tree pit its tree's id. A rebuild on the same data gives the same ids.

## Tables

- `space.ground` (new): `ground_id`, `level`, `type`, `name`, `source`, `method`, `ref`, `geometry`.
- `space.part`: gains `layer` (1, 2 or 3), `parent_id`, and for overlays `on` (the ids it lies on); its ids become the stable ones; the
  priority rule "a part takes only ground no earlier part took" stays only within one layer of one parent.
- `space.mark`, `space.object`: gain `parent_id`.
- `space.relation` (new): `from_id`, `relation`, `to_id`, `source`, `method`.
- The dossier copies them; CityGML / OpenDRIVE / IFC export maps them.

## Checks

| id | what | hard |
|---|---|---|
| G1 | ground left `unknown` at a level (m², pieces) | reported, to bring to 0 |
| G2 | ground items overlapping | yes |
| L1 | items of layers 1-2 not covering their parent exactly (3 % or 1.5 m²) | yes (replaces U8) |
| L2 | items of one layer overlapping within one parent | yes (replaces U9) |
| L3 | overlays naming no band they lie on; markings and objects with no parent | yes |
| L4 | lane items with neither predecessor nor successor, away from a space's edge or a junction | reported |
| L5 | lane items shorter than 2 m | reported |
| L6 | ids that changed between two builds of the same data | reported |

U14 goes (G1 covers it). U1-U7 (the spaces) and U10-U13 (the roadway at cuts, the approaches) stay.

## The page

The map draws layer by layer (ground, surfaces, bands, overlays, markings, objects), each a toggle; in 3D the same, at height. The panel's
tree is the hierarchy: level -> ground item -> surface -> bands, with each item's overlays and relations ("crossed by crosswalk w...",
"continues to ..."). A click selects one item and lights its parent, children and related items.

## Order of work

1. Layer 0, the ground, with G1 / G2 (no change inside the street yet): every piece of the area gets a kind; the page draws it.
2. Layers 1-2 in streets: surfaces; lanes as whole items with predecessor / successor; one junction area; pedestrian zones. L1, L2, L4, L5.
3. Layer 3 overlays and `space.relation`: crosswalks (area and walking line), parking, bus, tree pits, aprons, connections. L3.
4. Layers 4-5: markings and objects with their parent.
5. Stable ids (L6), then the page's hierarchy and selection.
6. Plots inside (yard, garden ... from land use and the city's parcels: [Plots](plots.md), step 2) and the type mapping table to
   OpenDRIVE, CityGML and IFC.

Each step ends with the checks before and after on Broadway × Granville and a page to look at.

## Not now

Linear referencing (s, t) along every section ([Street objects](street-objects.md) 4.1), time-dependent rules beyond what OSM and the city
give, export writers (only the mapping table).

## Decisions needed

1. The ground kinds and their order (water, rail, street, square, plot, green, unknown).
2. Pedestrian realm in NACTO's four zones, replacing sidewalk / furnishing / open.
3. Lanes cut only where count, type or rules change (not at crosswalks, not at SUMO's other nodes).
4. One relation table for crosses / lies_on / continues / governs / attached_to / stands_in / conflicts.
5. The order of work, starting with the ground.
