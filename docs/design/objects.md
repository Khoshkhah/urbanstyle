# Street objects

<p class="lead">What stands in the street: lamps, signals, signs, benches, bins, trees, bus stops, crossings, entrances and barriers,
from every source, one object per real thing, each with its class, its position and the id it has in each source.</p>

## Reads

OSM's nodes with their tags. A city's surveyed objects (poles, signals, meters, hydrants, trees, catch basins, manholes). Mapillary's
detections, for validation only. A transit timetable (GTFS) for the stops.

## The classes

An OSM node gets one class, `group.class`. The first rule that matches wins, in this order.

| Class | Rule |
|---|---|
| `crossing.signalised` | `highway=crossing` with `crossing=traffic_signals` or `crossing:signals=yes` |
| `crossing.zebra` | `highway=crossing` with `crossing` in `zebra`, `uncontrolled`, `marked`, or `crossing_ref=zebra` |
| `crossing.other` | any other `highway=crossing`; `railway=crossing` |
| `furniture.signal` | `highway=traffic_signals` |
| `furniture.lamp` | `highway=street_lamp` |
| `furniture.sign` | `traffic_sign` set, or `highway` in `stop`, `give_way` |
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

A node with no matching rule is counted in the inventory and not kept. A city's objects get the class of their dataset.

## Level, space and part

- The level comes from a `level` tag, else a `layer` tag, else 0, clamped to the kept levels.
- The object stands in the space of that level that contains its point, and in the part that contains it. An object outside every
  space keeps the distance to the nearest space within 60 m.
- Each object keeps a short set of attributes from its tags (height, material, direction, capacity, lit, surface, ref, tactile paving,
  kerb, crossing, colour, operator, and the tags of its class). Everything else stays in the source, reachable by the object's id.

## One object per real thing

Several sources describe the same thing: a city's surveyed pole, OSM's node and Mapillary's detections of one street light. Objects
of one class within 10 m of each other join into one match, nearest first, at most one per source. Two Mapillary detections seen in
periods that do not overlap are one object detected again. The match takes its position and height from the best source, in this
order: a city's survey, the national road register, OSM, Mapillary. Every source's id stays in the match.

Mapillary validates and builds nothing: its positions are too rough to place a thing. A detection confirms an object of a source with
a real position; what Mapillary alone sees is a check row, not an object. The page hides the detections until they are ticked.

## Sizes

Every object has a width and a height: a source's measurement where there is one (a tree survey's trunk diameter and height), else
urbanstyle's chosen size for its class. The 3D models are built from them. A pole or a sign inside a deck stands on the deck at its
height; a tree, a manhole or a drain stays on the ground.

## Bus stops

A stop on the sidewalk is a waiting area, 8 m to each side of its pole and 3 m deep, with what it has (shelter, bench, bin, lit,
wheelchair) and its timetable: the routes and the departures on a weekday, from the timetable by the stop's number. The kerb strip in
front of it, 20 m behind the pole and 2 m past it, is a bus zone with no parking.

## Writes

`urban.object`: one row per real thing, with its `uid`, its kind (`group.class`), its level, space and part, its size with the
source and method of each value, every source's id, and its best source ([The tables](tables.md)); the dossier's
`object` and `match`. An object's `uid` comes from the registry; its profile is its best source and that source's record id, so a
rebuild gives the same object the same `uid` ([The tables](tables.md#the-registry-urbanregistry)).

## On the page

One layer per group, off at start. A space in focus shows the objects that stand in it. A click on an object opens its fields and
every source's id. The 3D view draws one model per object at its size.
