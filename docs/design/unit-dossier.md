# One unit in full: the unit dossier

<p class="lead">Instead of dividing a whole city into spaces and then filling them, take one unit of a city (one intersection or
one street section), gather everything that can be known about it, from every source, in as much detail as exists, and give it
a clean structure. Then generalize the recipe to the rest of the city.</p>

Status (2026-10-09): **proposal, to agree with Kaveh before coding.** It replaces the city-wide approach of the network-first
preview (the partition into spaces stays, as the way a unit's outline is found; the SUMO and Mapillary work stays, as sources).

## Why

The city-wide work produced a good-looking map and 3D view, but every unit was filled the same thin way, and the time went into
corner cases across the whole city. One unit at full detail answers the real questions: what can be known about a piece of
street, how well, from which source, and in what structure. Two cities make the answer general rather than local.

## The three units

| unit | city | why |
|---|---|---|
| **Skanstull**: Götgatan × Ringvägen intersection | Stockholm (Södermalm) | busy junction; the longest traffic series in Kaveh's data are on its arms (Götgatan, Skansbrogatan, Johanneshovsbron) |
| **W Broadway × Granville St** intersection | Vancouver | major signalised junction with transit; inside the 1 m lidar area |
| **A block of W 4th Ave**, Kitsilano (Vine St to Yew St, to confirm) | Vancouver | shopping street: parking, street trees, furniture; inside the lidar area |

Each unit's outline comes from urbanstyle's partition (cut at the block corners, out to the facades), built for these places
only. Vancouver becomes a pilot area for this purpose (a roadmap step, `docs/plan.md`).

## Step 1: the source inventory

For each unit, every source is checked and recorded: **what it gives here, how precise, how recent, its licence, and whether it
can be fetched automatically.** The table is a result in itself: it shows what is knowable about one piece of street.

| source | Stockholm | Vancouver | gives (to check per unit) |
|---|---|---|---|
| OpenStreetMap (duckOSM) | ✓ | ✓ | roads, tags (lanes, width, sidewalks), crossings, some objects |
| SUMO (from duckOSM) | ✓ | ✓ | lane geometry, junction shape, lane-to-lane moves |
| Mapillary | ✓ | ✓ | photos, signs, lights, markings, positions 1-5 m |
| Aerial / orthophoto | Lantmäteriet 0.16 m (CC BY 4.0, login) | City of Vancouver 7.5 cm, 2022 (open) | kerb lines, markings, trees from above |
| Elevation | Lantmäteriet 1 m ground model (CC BY 4.0, login) | **have**: 1 m DTM/DSM; city lidar 2022 point clouds (open) | ground, kerb and building heights |
| Road register | NVDB (fetched by fetching-sweden-data) | - | carriageway width, lanes, speed, for some roads |
| City open data | Stockholm stad (parking rules LTF, flow map, ...) | City of Vancouver open data, no key (`--vancouver`): trees with heights, light poles, signals, parking meters and their rules, right-of-way widths, condition ratings, building heights | objects and rules, often surveyed |
| Traffic | Trafikverket gantries, tube counts (Kaveh's stack) | to look for | flows per edge or lane, by hour |
| Street View | view only | view only | manual check (its terms forbid extracting data) |

"(open?)" marks sources whose availability and licence are checked first, not assumed.

## Step 2: the structure

One self-contained dossier per unit (a DuckDB file, exportable to GeoPackage). Everything is in metres in the local UTM zone,
with a real height (z) from the elevation data. **Every item carries its provenance:** the source, the date of the data, the
method (`surveyed`, `mapped`, `measured` here, `derived`, `estimated`, `checked by hand`) and a confidence.

| table | holds |
|---|---|
| `unit` | id, kind (intersection / street section), name, city, outline, levels |
| `source` | every source used: name, origin (URL, query), licence, fetched when, how |
| `surface` | the ground, split by use: lane, bus lane, cycle lane, parking, sidewalk, furnishing, island, planting, ... with its top height |
| `line` | kerbs and markings: lane lines, stop lines, zebras, arrows; type, pattern, colour, width |
| `object` | street furniture and trees: class, position (x, y, z), height, facing, attributes |
| `match` | the real objects: the objects of all sources that stand for one thing (a surveyed pole, an OSM node, two Mapillary detections of one lamp); position and height from the best source, every source's id |
| `lane` / `movement` | each lane (road, direction, number from the right, width, allowed modes) and each move from lane to lane, with its signal or priority |
| `rule` | regulations and where they apply: parking times and fees, loading zones, speed, no stopping |
| `observation` | timed data: traffic counts per edge or lane and hour, photos with their position and view, sensor readings |
| `check` | each verification against reality: what was checked, how (photo, Street View, site visit), the result, when |

Every table maps to **CityGML 3.0 Transportation** (Road / Section / Intersection, TrafficSpace and AuxiliaryTrafficSpace with
their TrafficArea, Marking, Hole) and to CityFurniture and Vegetation, so a unit can be exported to the standard later.

**Matching** (`unit.match`, 2026-10-09): objects of one class within 10 m of a member join it, nearest first, at most one per source; two
Mapillary features seen in periods that do not overlap are one object detected again from newer photos (at Broadway × Granville one lamp
was seen as `1098977867852801` until 2021-01-22 and as `2642214999294836` from that day, 8 m apart). Groups that are one object are then
merged. Position and height come from the best source (a city's survey, then OSM, then Mapillary); confidence is that any one source is
right. Greedy, for one unit; a whole city needs a spatial index.

## Step 3: build each unit, then judge it

The dossier is filled source by source, best source first for each layer (a surveyed city layer before OSM, OSM before a
guess). Then it is compared with reality (photos, Street View, or a visit) and the differences are listed in `check`.

**The recipe is recorded as it is made:** for every item, how it was obtained, and whether a machine did it or a person.
Generalizing to the rest of the city later is running the machine steps everywhere and seeing what the hand steps cost.

## Done when

1. the source inventory table is filled for all three units;
2. each unit's dossier holds every layer above that a source covers, with provenance on every item;
3. a side-by-side of each unit against reality, with the remaining differences listed;
4. the recipe: each step, automatic or by hand, and what it would take to repeat it for a whole city.

## Not now

The whole-city partition, its checks and its dashboard stay as they are (the network-first preview); no new city-wide work until
the three units are done.
