# Sources and provenance

<p class="lead">Every item urbanstyle stores says who gave it, how they got it and which of their items it is. A value that no source
gives is urbanstyle's own, with its method, never a default.</p>

## Source: who

| Source | What | Licence | How it reaches urbanstyle | A `ref` |
|---|---|---|---|---|
| `osm` | OpenStreetMap, through duckOSM | ODbL 1.0 | duckOSM's database of the area | `w473723207`, `n12180788022` |
| `vancouver` | City of Vancouver open data | Open Government Licence - Vancouver | `urbanstyle unit --vancouver`: every dataset within 400 m of a pilot | `public-trees-86`, `vb6531793` |
| `nvdb` | Trafikverket NVDB (Sweden) | CC0 1.0 | `unit --nvdb` | NVDB's link id |
| `gtfs` | a transit timetable | the operator's terms | `unit --gtfs` | `gtfs<stop_id>` |
| `mapillary` | Mapillary's detections in street photos | CC BY-SA 4.0, kept local | `urbanstyle mapillary` | `mly<feature id>` |
| `sumo` | SUMO's netconvert, run on duckOSM's network | EPL 2.0 (the tool) | `sumo.py` | |
| `urbanstyle` | urbanstyle's own rules | MIT | the build | the item it was made from |

OSM's faults (a wrong lane count, a missing `layer`) are corrected in duckOSM's override file, not in urbanstyle, so every rebuild
repeats the correction.

## Method: how

| Method | Meaning | Confidence | Examples |
|---|---|---|---|
| `surveyed` | measured on the ground by the source's own survey | 0.9 | a city's parcels, street-light poles, catch basins |
| `mapped` | drawn by mappers, or kept in a register of mapped things | 0.7 | OSM roads, buildings, land use, car parks |
| `recorded` | in a register whose accuracy the source does not state | 0.7 | a city's trees, hydrants |
| `measured` | measured by urbanstyle from mapped lines | 0.6 | a kerb from OSM's sidewalk lines, a width kerb to kerb |
| `derived` | computed by urbanstyle from other data by a rule | 0.5 | the units, SUMO's lanes, a yard |
| `observed` | seen in photos | 0.5 | Mapillary's detections |
| `approximate` | the source itself says its positions are approximate | 0.4 | a city's traffic signals, parking meters |
| `chosen` | urbanstyle's own value, one for a type | 0.3 | a lane 3.25 m, a crosswalk 3 m, a tree pit 1.5 m |
| `narrowed` | a chosen width narrowed to fit the room between the street's edges | 0.3 | a lane 2.75 m |
| `checked` | verified by hand | 1.0 | |

The confidence follows from the method. A matched object's confidence is the chance that at least one of its sources is right.
A city's own words decide its method: a dataset whose accuracy note says "survey accuracy" is `surveyed`, one that says
"approximate" is `approximate`, one with no note is `recorded`.

## Which source wins

- **An object seen by several sources** takes its position and height from the best one: a city's survey, then the national road
  register, then OSM, then Mapillary. Every source's id stays with the object.
- **The ground** takes its kinds in a fixed order of precedence ([Rank 1](ground.md)). The first to claim a piece keeps it.
- **A part's width or an object's size:** a source's measurement where there is one, else urbanstyle's chosen value.
- **A building's height:** OSM's `height`, else a city's LiDAR where its roof parts still cover the footprint, else OSM's floors times
  3 m (derived), else one floor (chosen).
- **The kerb:** the near side of OSM's sidewalk strip where the line is mapped, else the lanes' outer edge. A city's kerb evidence
  (catch basins) checks the result and widens an outer lane for parking; it never moves a lane.

## Where each table keeps it

| Table | Columns |
|---|---|
| `space.ground`, `space.surface` | `source`, `method`, `ref` |
| `space.part`, `space.mark` | `source`, `method`, `ref`; `width_source`, `width_method`; a part's `position_source`, `position_method`, `position_ref` |
| `space.element` (buildings) | `source`, `level_src`, `use_source`, `use_method`, `ground_source`, `ground_method` |
| `space.object` | `source`, `method`, `ref` |
| the dossier's `object` | `source`, `method`, `observed`, `confidence`; `width_source`, `width_method`, `height_source`, `height_method` |
| the dossier's `source` | one row per source used: name, origin, licence, method, date fetched |

## The inventory

For every source, the pilot dossier counts what the source holds around the pilot and how much of it reaches the tables: for each OSM
key, Mapillary class or city dataset, the count in the neighbourhood, the count that reaches a table, and whether the code reads the
value. A gap is a number, not an impression, and it shows up by itself in any new area.

## The pilot dossier

A pilot is one intersection or one street section studied in full. Its dossier is one self-contained database, in metres in the local UTM zone, with
everything that can be known about the pilot from every source, each row with its source, method and confidence:

| Table | Holds |
|---|---|
| `unit` | id, kind, name, city, outline, levels |
| `source` | every source used |
| `inventory` | what each source holds and what reaches the tables |
| `surface`, `line`, `object`, `match` | the ground by use, the kerbs and markings, the objects, the real objects behind them |
| `lane`, `movement` | each lane and each move from lane to lane |
| `rule` | regulations and where they apply: parking times and fees, loading zones, speed |
| `observation` | timed data: traffic counts, photos |
| `check` | each verification against reality |

Each table maps to CityGML 3.0 Transportation, CityFurniture and Vegetation, so a pilot can be exported to the format.
