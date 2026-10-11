# Sources and methods

Every item urbanstyle stores says **who** gave it (`source`), **how** they got it (`method`) and **which** of their items it is (`ref`).
This page is the vocabulary, the rules that pick a source, and where each table keeps it. Status: in use, 2026-10-10.

## Source: who

| source | what | licence | how it reaches us | `ref` looks like |
|---|---|---|---|---|
| `osm` | OpenStreetMap, through duckOSM | ODbL 1.0 | duckOSM's database of the area (`build`, `unit`) | `w473723207` (a way), `n12180788022` (a node) |
| `vancouver` | City of Vancouver open data | Open Government Licence - Vancouver | `urbanstyle unit --vancouver`: every dataset within 400 m (600 m for parcels and building footprints) into `<unit>.vancouver.json` | `public-trees-86`, `pl030585457` (a parcel), `vb6531793` (a building outline) |
| `nvdb` | Trafikverket NVDB (Sweden) | CC0 1.0 | `unit --nvdb` | NVDB's link id |
| `gtfs` | a transit timetable (TransLink) | the operator's terms | `unit --gtfs` | `gtfs<stop_id>` |
| `mapillary` | Mapillary's detections in street photos | CC BY-SA 4.0, kept local | `urbanstyle mapillary` | `mly<feature id>` |
| `sumo` | SUMO's netconvert, run on duckOSM's network | EPL 2.0 (the tool) | `sumo.py` | — |
| `urbanstyle` | our own rules | MIT | the build | the item it was made from (a space id, a part id) |

A value that comes from no outside source is **urbanstyle's own**, `source = urbanstyle`; it is never called a default.

## Method: how

| method | meaning | confidence | examples |
|---|---|---|---|
| `surveyed` | measured on the ground by the source's own survey | 0.9 | the city's parcels ("much of the land base at survey accuracy"), street-light poles, manholes, catch basins |
| `mapped` | drawn by mappers, or kept in a register of mapped things | 0.7 | OSM roads, buildings, land use, car parks, construction sites, parks |
| `recorded` | in a register whose accuracy the source does not state | 0.7 | the city's trees, hydrants |
| `measured` | measured by urbanstyle from mapped lines | 0.6 | a kerb from OSM's sidewalk lines, a lane's width kerb to kerb, a path space around OSM's walkways |
| `derived` | computed by urbanstyle from other data by a rule | 0.5 | street spaces (from the roads and the property line), SUMO's lanes, a yard (the rest of a parcel), the land under a deck |
| `observed` | seen in photos | 0.5 | Mapillary's detections (they confirm, they build nothing) |
| `approximate` | the source itself says its positions are approximate | 0.4 | the city's traffic signals ("the approximate centre of the intersection"), parking meters ("shown for entire block faces"), the 2009 and 2015 building outlines |
| `chosen` | urbanstyle's own value, one for a type | 0.3 | a lane 3.25 m where nothing is measured, a crosswalk 3 m, a tree pit 1.5 m, a sidewalk 0.15 m high, a light pole 7.6 m |
| `checked` | verified by hand | 1.0 | none yet |

`confidence` (`unit.CONFIDENCE`) follows from the method; a matched object's is `1 - ∏(1 - c)` over its sources.

### A city's own words decide its method

Each Vancouver dataset's "Data accuracy" note sets its method (`unit.VAN_METHOD`): surveyed for street-light poles, manholes, catch
basins, lighting junction boxes; approximate for traffic signals, parking meters, drinking fountains, wayfinding stands, disability
parking, right-of-way widths, bikeways, traffic counts; recorded for trees and hydrants. A record that calls itself approximate (a catch
basin "location approximate") is approximate whatever its dataset says. The city's right-of-way widths are in feet unless marked "(m)".

## Which source wins

- **An object seen by several sources** (`unit.match`) takes its position and height from the best one: the city's survey, then NVDB,
  then OSM, then Mapillary (`unit.RANK`); every source and id stays in `sources` and `refs`.
- **Layer 0, the ground** ([Layers](space-layers.md)): the kinds take the ground in a fixed order (water, rail, street, square,
  structure, public green, plot, other green, structure under decks, path, square); within plots, the city's parcels first, then car
  parks, construction sites, OSM land use, buildings. The first to claim a piece keeps it.
- **A part's width or an object's size**: a source's measurement where there is one, else urbanstyle's `chosen` value.
- **Building height**: OSM `height`, else the city's 2009 LiDAR (approximate; only where its roof parts still cover the footprint and
  OSM's floor count agrees), else OSM floors x 3 m (derived), else one floor (chosen).

## Where each table keeps it

| table | columns |
|---|---|
| `space.ground` (layer 0) | `source`, `method`, `ref` |
| `space.surface` (layer 1) | `source`, `method`, `ref` (the ids of what it was made from) |
| `space.part` | `source`, `method`, `ref`; `width_source`, `width_method` |
| `space.mark` | `source`, `method`, `ref`; `width_source`, `width_method` |
| `space.element` (buildings) | `source`; `level_src` (where floors and height come from); `use_source`, `use_method`, `ground_source`, `ground_method` |
| the dossier's `object` | `source`, `method`, `observed`, `confidence`; `width_source`, `width_method`, `height_source`, `height_method` |
| the page's street objects | `sources`, `method` (each source's), `refs`, `size_from` |
| the dossier's `source` | one row per source used: name, origin, licence, method, date fetched |

## Layer 0 today (Broadway × Granville)

| kind | source, method | items |
|---|---|---|
| plot from a parcel | vancouver, surveyed | 534 |
| street, structure, right-of-way pieces | urbanstyle, derived | 355 |
| plot from OSM (car park, site, land use, building), green, rail | osm, mapped | 78 |
| path | urbanstyle, measured | 4 |

A known error: a plot made from one of the city's building outlines would say `vancouver, mapped`; it must say `approximate` (the city's
own note on its 2009 and 2015 outlines). None is in this unit's layer 0 today; it is fixed with the next step.

Next step (being built): each ground item also keeps its `rule` (which step of the order made it), `kept` (how much of its own source it
kept, and what earlier kinds took) and `evidence` (every source that covers it, with the share it covers, whether it won or not).
