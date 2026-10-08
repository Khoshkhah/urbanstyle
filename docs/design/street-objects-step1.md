# Step 1: objects in the street space (specification)

Part of `docs/design/street-objects.md` (section 6, step 1). Terms are in `docs/design/glossary.md`. This step builds `space.object` for
**point objects from OSM nodes** and shows them on the dashboard. Boundaries (walls, fences), the axis and `(s, t)`, the strips
and the detail view are later steps and are not touched here.

## Decisions this step relies on (agreed)

- The taxonomy v1 of `street-objects.md` is used as is.
- Building entrances are objects (`access.entrance`), not only an attribute of a building.
- The axis of a dual carriageway will be the midline (step 3); nothing in this step needs it.

## Input

`osm.raw.nodes` (`osm_id`, `lat`, `lon`, `tags`), and the finished `space.container` and `space.zone`. Nodes whose tags match no
taxonomy rule are ignored and counted (`amenity_other`, `man_made_other`, `leisure_other` in the inventory).

## Classification

First matching rule wins, in this order:

| class | rule |
|---|---|
| `crossing.signalised` | `highway=crossing` and (`crossing=traffic_signals` or `crossing:signals=yes`) |
| `crossing.zebra` | `highway=crossing` and (`crossing` in `zebra`, `uncontrolled`, `marked` or `crossing_ref=zebra`) |
| `crossing.other` | any other `highway=crossing`; `railway=crossing` |
| `furniture.signal` | `highway=traffic_signals` |
| `furniture.lamp` | `highway=street_lamp` |
| `furniture.sign` | `traffic_sign` or `traffic_sign:forward` set, or `highway` in `stop`, `give_way` |
| `transit.stop` | `highway=bus_stop`, or `public_transport` in `platform`, `stop_position` |
| `furniture.shelter` | `amenity=shelter` |
| `furniture.bench` | `amenity=bench` or `leisure=picnic_table` |
| `furniture.waste` | `amenity` in `waste_basket`, `waste_disposal`, `recycling` |
| `furniture.bike_parking` | `amenity=bicycle_parking` |
| `furniture.vending` | `amenity` in `vending_machine`, `ticket_validator` |
| `furniture.post_box` | `amenity=post_box` |
| `furniture.water` | `amenity` in `drinking_water`, `fountain`, or `man_made=water_tap` |
| `furniture.charging` | `amenity=charging_station` |
| `furniture.hydrant` | `emergency=fire_hydrant` |
| `furniture.advertising` | `advertising` set |
| `furniture.bollard` | `barrier=bollard` |
| `kerb.node` | `kerb` set, or `barrier=kerb` |
| `barrier.other` | any other `barrier` |
| `vegetation.tree` | `natural=tree` |
| `access.parking_entrance` | `amenity=parking_entrance` |
| `access.entrance` | `entrance` set |

## Level, container and zone

- **Level**: from a `level` tag, else a `layer` tag (a Unicode minus counts as a minus), else 0; clamped to -2 … 2. A first
  integer is taken from a value like `-1;0`.
- **Container**: the container at that level whose area contains the point. Containers do not overlap, so there is at most one;
  a point exactly on a shared edge takes the smallest `container_id`.
- **Zone**: the `zone` polygon of that container that contains the point (`travelway`, `pedestrian_realm`, `track`), else NULL.
- **Outside every container**: `container_id` and `zone` are NULL, and `near_m` is the distance in metres to the nearest container at that
  level if within 60 m (else NULL). Such objects are kept, not dropped.

## Output: `space.object`

| column | type | meaning |
|---|---|---|
| `object_id` | VARCHAR | `n<osm node id>` |
| `class` | VARCHAR | `group.class` |
| `level` | INTEGER | |
| `container_id` | VARCHAR | NULL when outside |
| `zone` | VARCHAR | NULL when outside or in no zone |
| `near_m` | DOUBLE | metres to the nearest container when outside, else NULL |
| `name` | VARCHAR | the OSM `name`, if any |
| `attrs` | JSON | only these tags, when present: `height`, `material`, `direction`, `angle`, `capacity`, `lit`, `covered`, `surface`, `ref`, `level`, `tactile_paving`, `kerb`, `crossing`, `colour`, `traffic_sign`, `bin`, `shelter`, `bench`, `amenity`, `highway`, `entrance`, `barrier`, `natural`, `operator` |
| `source` | VARCHAR | `osm` |
| `geometry` | GEOMETRY | the point, lon/lat |

`s_m`, `t_m`, `side` and `strip_id` are added in steps 3 and 4. The OSM id is the only key back to `raw.nodes`.

## Dashboard

- One overlay per group (`furniture`, `vegetation`, `transit`, `crossing`, `kerb`, `access`, `barrier`), small circles, with a
  checkbox in the layer list.
- A tree branch **Objects → group → class** with counts at the selected level; clicking a class shows only that class.
- Selecting a **street space** (or a zone of it) in the tree shows the objects inside it.
- Popups show `object_id`, `class`, `container_id`, `zone`, `level` and `attrs`.

## Acceptance checks

1. Every object has exactly one class, one level and at most one container.
2. The count of objects inside containers per class matches the inventory in `street-objects.md` within a few percent (the
   inventory counted level 0 only and grouped some classes differently).
3. In the pilots the pedestrian realm holds most trees, benches, bins and bollards, the travelway most crossings and signals.
4. Objects outside every container are reported with their `near_m` distribution.
5. A unit test covers the classification order, the level rule, the container assignment and an object outside.

## Out of scope

Line and area objects (tree rows, parking areas, fences and walls), Overture objects, object heights or 3D, and any editing.

## Results (2026-10-02)

| | Monaco | Södermalm |
|---|---|---|
| objects | 2,548 | 7,402 |
| inside a container | 2,303 | 6,359 |
| outside every container | 245 (230 within 60 m, median 5.1 m) | 1,043 (1,019 within 60 m, median 2.5 m) |
| at levels other than 0 | 11 | 50 |

Acceptance checks: 1 holds (every object has one class and one level, no duplicate ids). 2 holds class by class against the
inventory (benches 220 and 410, bollards 125 and 20, bins 124 and 220, trees 498 and 190 inside a container). 3 holds: of 492
zebra crossings inside a container in Monaco, 474 are in the travelway; of 498 trees, 444 are in the pedestrian realm; Södermalm
likewise (208 of 225 zebra crossings in the travelway, 397 of 410 benches in the pedestrian realm). 4: see the table. 5: covered by
`test_objects`.

Largest classes inside a container: Monaco: tree 498, zebra crossing 492, transit stop 212, bench 220, bollard 125, bin 124;
Södermalm: building entrance 3,205, other barrier points 621, bench 410, signalised crossing 256, zebra crossing 225, bin 220.
Nodes with no taxonomy rule are ignored (about 200 `amenity_other` in Monaco, 800 on Södermalm, mostly shops and cafés).

Dashboard: seven overlays (one per group) that start **unticked**, since thousands of dots clutter the overview; selecting a street
space (or one of its zones) in the tree shows the objects inside it regardless. The busiest Monaco street, `s0-4230044`, holds 74.

## Focus mode (added after the first dashboard)

Showing every object at once is not useful, so the objects of a street space appear only when it is **focused**. Select a
container by clicking it, or its centerline, on the map, by choosing it in the tree, or by typing its id: the map then shows only
that container (street space, zones, its centerlines, its objects), the basemap is dimmed with a white veil, and the panel lists
its area, widths, zones and objects by class with a checkbox each. Esc or the button leaves it. The map allows zoom up to 24 and
focus fits to 23: past the basemap's last real tile level the basemap is scaled up and our layers stay sharp. The Objects layers
and the Objects tree branch remain for looking at one class everywhere.
