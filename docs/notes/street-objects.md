# Street objects and the fill of a street space (design, not yet built)

Goal: select any street space on the dashboard and see it in detail: how it is **filled** (strips across it) and
**what stands in it** (objects), stored in one standard form. `docs/design/street-space.md` says how the street space itself
(the container) is measured; this document is about what goes inside it.

## 1. What a street space contains (our data, 2026-10-02)

Node objects of duckOSM's `raw.nodes` that fall inside a level-0 container, by zone (container → `space.zone`):

| class (OSM tag) | Monaco in space (travelway / ped. realm) | Södermalm in space (travelway / ped. realm) |
|---|---|---|
| crossing (`highway=crossing`) | 544 (523 / 21) | 597 (563 / 34) |
| building entrance (`entrance=*`) | 89 (6 / 83) | 3,200 (7 / 3,193) |
| tree (`natural=tree`) | 498 (55 / 443) | 190 (39 / 151) |
| bench | 220 (32 / 188) | 410 (13 / 397) |
| other barrier nodes | 75 | 624 |
| waste basket | 124 (15 / 109) | 220 (10 / 210) |
| bollard | 125 (29 / 96) | 20 (2 / 18) |
| bus stop + PT platform/stop | 212 | 175 |
| traffic signals | 22 (21 / 1) | 218 (204 / 14) |
| street lamp | 28 (11 / 17) | 175 (47 / 128) |
| bicycle parking | 22 | 208 |
| vending machine / ticket | 59 | 115 |
| post box, kerb nodes, road-sign nodes, traffic signs, drinking water, charging, hydrants, advertising, shelter | 1 to 83 each | 0 to 71 each |
| **all node objects inside a street space** | **2,604** | **6,491** |

They land where the zones predict: crossings in the travelway, trees, benches, bins and bollards in the pedestrian realm.
That is a first confirmation that the travelway / pedestrian-realm split means something.

Lines and areas are not counted as objects yet but matter more than they look: **fences 928, walls 179, retaining walls 151,
hedges 70** on Södermalm (Monaco: 57 retaining walls, 25 walls, 8 fences). A wall or fence is a street-space *boundary* just like
a building face, and the street-space measurement ignores them today (see "Boundaries" below). There are also
parking areas (38 / 81), tree rows (1 / 17) and kerb lines (5 / 0).

## 2. What the roads say about their own cross-section

Share of driving ways carrying each tag (`raw.ways`):

| tag | Monaco (1,033 ways) | Södermalm (2,403 ways) |
|---|---|---|
| `surface` | 72% | 97% |
| `oneway` | 58% | 51% |
| `lanes` | 48% | 21% |
| `maxspeed` | 32% | 83% |
| `sidewalk` (any value) | 22% | 35% (623 `both`, 103 `separate`) |
| `cycleway` (any key) | 11% | 22% (lane 69, track 15, shared 18, separate 75) |
| `parking:*` | 0% | about 40% (lane 679) |
| `width` | 0% | 19% |

The tags describe the cross-section for a fraction of the roads and say nothing about widths of the rest. So the strips cannot
be built from tags alone: **geometry carries the fill and tags refine it where they exist**, and every strip must say which
of the two it came from.

## 3. How others store this

- **CityGML 3.0** ([modules](https://3dcitydb-docs.readthedocs.io/en/latest/3dcitydb/uml/city-furniture.html)): a road is a
  `TransportationSpace` made of `Section`s and `Intersection`s with `TrafficSpace` / `AuxiliaryTrafficSpace`; street objects are
  `CityFurniture` (lanterns, traffic lights and signs, benches, bus stops, bins) with a `class` attribute, trees are
  `SolitaryVegetationObject`. We already follow the container part.
- **OpenDRIVE** ([lane types and s/t](https://sumo.dlr.de/docs/Networks/Import/OpenDRIVE.html)): everything hangs on a
  **reference line**; a position is `(s, t)` = distance along it and lateral offset; a road is a sequence of lane sections, each a
  fixed set of typed lanes (driving, sidewalk, parking, shoulder, border...); objects and signals are placed by `(s, t)`.
- **Streetmix** ([segments](https://streetmix.readthedocs.io/en/latest/technical/segment-definitions/)): a cross-section is an
  ordered list of typed **segments**, each with a width and recommended minimum and maximum widths (a parallel parking lane:
  2.4 m, min 2.1 m, max 3.0 m).
- **IFC 4.3** ([road parts](https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/HTML/lexical/IfcRoadPartTypeEnum.htm)):
  `IfcRoad` → `IfcRoadPart` (longitudinal segments, lateral parts) with elements positioned by `IfcLinearPlacement` along an
  alignment.
- **Seattle / NACTO** ([zones](https://streetsillustrated.seattle.gov/street-type-standards/row-allocation/row_zones-03/)):
  frontage, pedestrian, furnishing, curb zone, flex zone (parking, loading), travelway.

What we take: **(s, t) linear referencing on a reference line** (OpenDRIVE, IFC), **typed ordered strips with a width and a
provenance** (OpenDRIVE, Streetmix), **object `class` plus free attributes** (CityGML), and **the zone vocabulary** (NACTO).

## 4. The proposed standard

Four tables next to the existing `space.element`, `space.container`, `space.zone`, `space.link`, `space.station`. Names and
columns are a proposal to be agreed.

### 4.1 `space.axis`: the reference line of a container

| column | meaning |
|---|---|
| `container_id` | the street (`s0-…`), path (`p0-…`) or rail (`r0-…`) space; intersections have no axis |
| `geometry` | the container's centerline as one line: its roads' centerlines merged end to end, longest chain first; for a dual carriageway the line midway between the two, otherwise the main road |
| `length_m` | length of the line |

`s` = metres along `geometry` from its start, `t` = signed metres to its left (positive) or right (negative). A container with
no single chain (a star of footpaths) gets one axis per chain, numbered.

### 4.2 `space.strip`: how the street space is filled

Ordered strips across the street space, from the left edge to the right edge, repeated per stretch of road where the make-up
changes (a lane section).

| column | meaning |
|---|---|
| `strip_id` | `<container_id>.<n>` |
| `container_id`, `level` | |
| `type` | one of the strip types below |
| `side` | `left`, `right` or `center` of the axis |
| `s_from`, `s_to` | the stretch of the axis it covers |
| `width_m` | mean width |
| `source` | `measured` (from a measured line or the measured kerb), `tag` (from `lanes`, `parking`, `cycleway`, `sidewalk`), or `default` (a flat guess) |
| `geometry` | the polygon |

Strip types (v1), a merge of NACTO, OpenDRIVE and Streetmix: `frontage`, `sidewalk`, `furnishing`, `kerb` (a line, width 0),
`parking`, `cycle`, `transit`, `travel` (driving lane), `median` (island), `track` (rail), `shoulder`, `open` (street space with
no known use: the part reached only by the reach cap).

How it is filled, from the kerb outward: the travelway is already measured out to the kerb where a sidewalk exists. Inside it,
`lanes`, `lanes:forward/backward`, `cycleway:*`, `bus:lanes` and `parking:lane:*` give the make-up; widths are the Streetmix
defaults unless `width` is tagged; the sum is scaled to the measured width, and the strips say `source = tag` or `default`.
Outside the kerb: the sidewalk strip comes from the measured sidewalk line, the rest up to the boundary is `furnishing`
(where objects stand) and `frontage` (the 1 m strip at the boundary), and anything beyond a reach cap is `open`.

### 4.3 `space.object`: what stands in it

| column | meaning |
|---|---|
| `object_id` | stable: `<osm type letter><osm id>`, e.g. `n123456`, `w98765` |
| `class` | `group.class` from the taxonomy below |
| `geometry` | point, line or polygon, lon/lat |
| `container_id`, `strip_id`, `zone`, `level` | where it sits |
| `s_m`, `t_m` | position along and across the axis (for lines and polygons: the centroid) |
| `side` | `left` / `right` of the axis |
| `attrs` | JSON of the few tags worth keeping (see below), never the whole tag set |
| `source` | `osm` (or `overture`) |

Taxonomy v1 (OSM tag → class); a short list, extended only when data needs it:

| group.class | OSM tags |
|---|---|
| `furniture.lamp` | `highway=street_lamp` |
| `furniture.signal` | `highway=traffic_signals` |
| `furniture.sign` | `traffic_sign=*`, `highway=stop`, `give_way` |
| `furniture.bench` | `amenity=bench`, `leisure=picnic_table` |
| `furniture.waste` | `amenity=waste_basket`, `waste_disposal`, `recycling` |
| `furniture.bike_parking` | `amenity=bicycle_parking` |
| `furniture.shelter` | `amenity=shelter`, `public_transport=platform` with a shelter |
| `furniture.vending` | `amenity=vending_machine`, `ticket_validator` |
| `furniture.post_box` | `amenity=post_box` |
| `furniture.water` | `amenity=drinking_water`, `fountain` |
| `furniture.charging` | `amenity=charging_station` |
| `furniture.hydrant` | `emergency=fire_hydrant` |
| `furniture.advertising` | `advertising=*` |
| `furniture.bollard` | `barrier=bollard` |
| `vegetation.tree` | `natural=tree` (`vegetation.tree_row` for a way) |
| `transit.stop` | `highway=bus_stop`, `public_transport=stop_position` |
| `crossing.zebra` / `crossing.signalised` / `crossing.other` | `highway=crossing` + `crossing=*` |
| `kerb.node` | `kerb=*`, `barrier=kerb` |
| `access.entrance` | `entrance=*` (a building door onto the street space) |
| `access.parking_entrance` | `amenity=parking_entrance` |
| `barrier.wall` / `barrier.fence` / `barrier.hedge` / `barrier.other` | `barrier=*` ways |

`attrs` keeps, when present: `height`, `material`, `direction` / `angle`, `capacity`, `lit`, `covered`, `surface`, `name`, `ref`,
`level`, `tactile_paving`, `kerb`, `crossing`, `traffic_signals:sound`. Anything else is left in `raw.*` and reachable through
the OSM id.

### 4.4 `space.boundary`: what bounds the street space

The street-space edge is a building face where a ray hit a building, and the reach cap everywhere else. Walls, fences,
hedges and retaining walls are the missing third kind. `space.boundary` stores the edge as typed pieces: `kind` (`building`,
`wall`, `fence`, `hedge`, `retaining_wall`, `open`), `side`, `s_from`, `s_to`, geometry, `source`. Treating walls and fences as
obstacles in the ray measurement also **lowers the capped (`open`) share** that the quality section of `street-space.md`
reports (79-84% of sections today), and gives the detail view an honest edge.

### 4.5 Rules that apply to all four

- Every row has a stable id, a `container_id`, a `level`, a `source` and, where derived, a `source`-style provenance such as
  `measured` / `tag` / `default`. Nothing is stored without saying where it came from.
- Objects outside every container keep `container_id = NULL` and a `near_m` to the nearest one; they are not dropped.
- An object on a level-0 street space belongs to level 0; objects on a bridge or in a tunnel take the structure's level.
- Geometry is lon/lat; `s`, `t`, `width_m` are metres. Counts and widths are re-derived on every build, never edited by hand.

## 5. What the detail view would show

Selecting a street space opens a panel with: the **plan** (the strips coloured by type, objects as symbols by class), a
**cross-section** at the cursor's `s` (strips left to right with widths and `source` marks, objects as icons at their `t`),
and a **table** of its objects (class, side, `s`, attributes) that highlights on the map when you click a row.

## 6. Proposed order of work

1. **Objects** (done, see `street-objects-step1.md`): `space.object` for nodes, with the taxonomy, `container_id` and zone, shown in
   the dashboard by group, with an Objects branch in the tree. Monaco 2,548 objects (2,303 inside a street space), Södermalm 7,402
   (6,359 inside).
2. **Boundaries**: add walls, fences and hedges as obstacles in the ray measurement and store `space.boundary`; re-measure the
   capped share.
3. **Axis and `(s, t)`**: build `space.axis` and add `s_m` / `t_m` to the objects.
4. **Strips**: fill the street space (section 4.2), with `source` on every strip.
5. **Detail view**: the panel in section 5.
6. Line and area objects (tree rows, parking areas, kerb lines).

## 7. Decisions (agreed 2026-10-02)

1. **Axis of a dual carriageway**: the midline between the two carriageways (step 3).
2. **Taxonomy v1** (section 4.3) is the starting list; classes are added only when data needs them.
3. **Walls and fences are boundaries** (step 2): they become obstacles in the ray measurement and rows of `space.boundary`.
4. **Building entrances are objects** (`access.entrance`) in `space.object`.

Step 1 is specified in `docs/design/street-objects-step1.md`; the words are in `docs/design/glossary.md`.
