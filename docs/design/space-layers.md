# Layers: the whole area, and the inside of a street, as a hierarchy

Status: agreed 2026-10-10; being built in the order below. Since 2026-10-10 layer 0 is to be built **blocks first** (see "Blocks first"
below and [Blocks first](blocks.md)): agreed and tested, not built. Step 1 built (`ground.py`, `space.ground`, `space.parcel`), on Broadway ×
Granville's neighbourhood (640,106 m² at level 0): plot 60.7 %, street 36.5 %, green 1.9 %, structure 0.5 %, rail 0.3 %, path 0.1 %,
**unknown 0** (G1); no overlaps (G2). With it the street reaches the property line where a city has parcels ([Plots](plots.md), step 2):
the street spaces' width at the city's 125 right-of-way points is now the city's own (ours / theirs: median 1.00, middle half 0.99-1.07,
76 % within 15 %; before, out to the building faces: median 2.47, 18 % within 15 %).
Layer 1 built (`ground.surfaces`, `space.surface`): 1,838 surfaces covering every ground item exactly (L1, L2): in streets the
roadway (159,454 m²) and the pedestrian realm (74,021 m²); in plots buildings (217,480 m²), yards, construction sites, car parks, gardens;
in green lawn, paths, play. The page `urbanstyle layers DB OUT` shows layer 0 and layer 1 each alone, with the hierarchy in the popups.

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
2. `rail`: OSM railway corridors (`landuse=railway`), a rail line's own bed.
3. `street`: our street spaces (`space.unit`: sections and intersections).
4. `square`: OSM pedestrian areas, squares; `structure`: the land under a bridge (OSM `man_made=bridge`).
5. public `green` (parks, playgrounds, pitches, recreation grounds, woods), then `plot`: a city's parcels where it has them (Vancouver
   `property-parcel-polygons`, `space.parcel`); car parks (`space.lot`), construction sites, OSM `landuse` areas (residential, retail, ...),
   a building no plot holds.
6. `green`: the rest of the green, OSM `landuse=grass`, gardens, allotments. Public green (parks, playgrounds, pitches, recreation grounds,
   woods) comes before `plot`: a city park is a parcel too, and would otherwise be a plot.
   Then `structure` again: land under a street space of a higher level (a deck OSM maps as a bridge without its outline); `path`: the
   measured path spaces (a greenway, a connector) and `square`: the measured plazas, after the plots and the green (a footpath through a
   park is the park's). What is left that a path or a road runs through is that path's or that street's.
7. `unknown`: what is left, reported by G1, each piece with its area and its neighbours, so it can be traced to a missing rule; but a
   sliver (under 5 m², or thinner than 2 m on average) joins the neighbour it shares the most edge with, and where a city has parcels,
   ground outside them that touches a street is right-of-way and joins that street.

A street's ground is fixed by the street's own rules (cuts, the building line); a plot's by its parcel, or by its buildings and land use;
the order above decides where two sources claim the same ground. The ground of one level is independent of another's (a bridge deck at
level 1 over a street at level 0).

### Blocks first: how layer 0 is built from 2026-10-10 (agreed, not built)

[Blocks first](blocks.md) changes how layer 0 is built, not what the layers are. Instead of each kind taking ground in the order above,
with the street taken from `space.unit` (cut from the road network), the area at level 0 is first split in two halves that fit exactly:

```
the area (level 0)
├── blocks                    the land: the faces of the public streets, less each street's half width
│   └── water, rail, square, structure, green, plot, path     the order above, applied inside each block
└── the street                everything outside the blocks
    ├── section               between two neighbouring blocks
    │   └── subsection        where its lanes, width or frontage change (the layer-0 street item)
    └── intersection          the rest of the street
```

- **The street is the ground outside the blocks**, so the two halves cover the area with no gap and no overlap; G1 (`unknown`) is left
  only inside blocks, where no land rule claims a piece.
- **A block is a group, not a layer**, as a street name group (`k<level>-<way>`) is. Each land item of layer 0 names its block
  (`block_id`); each street item names its section, and its street group as today.
- **Layer 0's street items are the subsections and the intersections.** A section with no change is one subsection. The section is their
  group (as a block is for land).
- **Inside a block**, today's rules (steps 1, 2 and 4-7 above) divide the land: plots from a city's parcels, car parks, construction sites,
  land use and buildings; green; squares; paths. Back lanes, parking aisles and driveways lie inside blocks, and so do park paths and rail
  lines, which bound no block. A car park's side onto a street is `open` or `closed` ([Blocks first](blocks.md), "What lies inside a block").
- **Other levels** (bridges, tunnels) have no blocks: their street is the deck or the tube, as today.

### Layers 1-2 in a street

- **Subsection and intersection are the parents.** Layers 1-5 sit inside each subsection or intersection. A subsection is cut along the
  street exactly where the lane count, a lane's type or its rules change, or the width or the frontage changes, so its surfaces divide it
  across (roadway, pedestrian realm, median, verge) and each lane is one whole item from one end of the subsection to the other. An
  overlay may lie across a cut (a crosswalk reaching past an intersection's 3 m into the arm) and names everything it lies on.

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
`g0-street-s0-2002513880381972879/1`); with blocks first, a block `b<level>-w<way><side>`, a section `s<level>-<block a>~<block b>`, a
subsection `<section id>/<k>`, an intersection `i<level>-<node>` ([Blocks first](blocks.md), "Ids"), and a ground item of the street
`g0-street-<subsection or intersection id>`; for items in a space, `<space id>:<type>:<key>`, the key from the source: a lane `<OSM way>:<direction>:
<lane from the kerb>:<n-th piece along>`, a crosswalk its OSM id, the junction area nothing (`i0-571700151:junction area`), a pedestrian zone
`<side>:<zone>`, a tree pit its tree's id. A rebuild on the same data gives the same ids.

## Tables

- `space.ground` (new): `ground_id`, `level`, `type`, `name`, `source`, `method`, `ref`, `geometry`; with blocks first also `block_id`
  (land) or `section_id` (street).
- `space.block` (blocks first): `block_id`, `level`, the street sides with their distance and its source, `geometry`.
- `space.section` (blocks first): `section_id`, the two blocks, the facing stretch, the two cuts, `geometry`; `space.ground` holds its
  subsections.
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

With blocks first, the checks B1-B6 of [Blocks first](blocks.md) come in (no building cut, the street pieces covering the street, no
piece under 2 m wide, every section between two cuts and as long as its street is wide; B6 the match with a city's blocks).

U14 goes (G1 covers it). U1-U7 (the spaces) and U10-U13 (the roadway at cuts, the approaches) stay.

## The page

The map draws layer by layer (ground, surfaces, bands, overlays, markings, objects), each a toggle; in 3D the same, at height. The panel's
tree is the hierarchy: level -> ground item -> surface -> bands, with each item's overlays and relations ("crossed by crosswalk w...",
"continues to ..."). A click selects one item and lights its parent, children and related items.

## Order of work

1. Layer 0, the ground, with G1 / G2 (no change inside the street yet): every piece of the area gets a kind; the page draws it. Built.
   Then, blocks first ([Blocks first](blocks.md)): (a) the blocks (`space.block`, B1, B6); (b) the street as the ground outside them,
   sections and intersections (B2-B5), replacing the cutting in `spaces.py`; (c) the land rules inside each block; (d) subsections, the
   layer-0 street items. G1 / G2 and the checks before and after on Broadway × Granville.
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
