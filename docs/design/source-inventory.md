# What the sources hold, and what reaches us

Status (2026-10-09): agreed. Built: the inventory step; parking (below).

Every source we can reach holds much more than urbanstyle uses. Looking at one junction (W Broadway × Granville St) showed it:
parking, bus stops and what a building is used for were missing although the sources have them. Patching those one by one
would miss the rest, so the unit dossier now **counts it**: for every source, what it holds around the unit and how much of it
reaches our tables. A gap is then a number, not an impression, and it shows up by itself in any new area.

## The inventory step (built)

`src/urbanstyle/inventory.py`, called by `urbanstyle unit` (dossier step 1), writes the dossier table `inventory`:

| column | meaning |
|---|---|
| `source`, `layer` | `osm` (node tag, road and path tag, building tag, area), `mapillary` (map feature), `vancouver` (dataset) |
| `item` | an OSM tag key, a Mapillary class, a city dataset |
| `n` | how many there are in the unit's neighbourhood (the clip) |
| `n_ours` | how many of them reach our tables (an OSM node as a `space.object`, a way or building as a `space.element`, a Mapillary feature in a class we keep, a city record in a dataset we read) |
| `read` | whether our code reads the value: an OSM key read by urbanstyle or duckOSM (found in the code itself) or kept in an object's attrs |
| `values` | the commonest values (OSM) or the fields filled (city) |

Nothing is kept by hand: counts come from the data, `read` from the code. Mapillary is now fetched in full (all classes); only the
classes we use are loaded into `space.observed`, the rest are counted.

Broadway × Granville, first run: OSM nodes carry 235 different keys (28 read), roads and paths 84 (26 read); Mapillary has 68
classes, 3,516 detections, of which we keep 11 classes, 623 detections.

## The sources

| source | reach | licence | role |
|---|---|---|---|
| OpenStreetMap via duckOSM | world | ODbL | the base: network, tags, objects |
| SUMO (from duckOSM) | world | EPL (tool) | lanes, junction shapes, moves |
| Mapillary | world | CC BY-SA (stays local) | what the street shows: signs, poles, markings |
| Overture Maps (duckOverture) | world | CDLA / ODbL | **cross-validation only** (agreed 2026-10-09): ML building heights, places |
| City of Vancouver open data | city | OGL-Vancouver | surveyed objects, rules, legal lines |
| City of Vancouver VanMap (`maps.vancouver.ca` Hosted layers) | city | public, not published as open data; agreed to use (2026-10-09) | layers the portal lacks |
| Metro Vancouver open data (ArcGIS hub) | region | OGL | 2025 imagery, 2 m land cover, lidar, office inventory |
| TransLink GTFS | region | open | bus stops, routes, frequency |
| City traffic cameras | 219 junctions | public | today's state, with a time stamp |

## The gaps, by topic, and the rule for each

| topic | what the sources hold (Broadway × Granville) | what we have | proposed rule |
|---|---|---|---|
| **parking** (built 2026-10-09: Broadway × Granville 86 parking parts → 215, 165 with their meters' rules, 0 → 40 no parking, unknown kerb strips 672 → 504; still to add: VanMap permit zones and car-share bays, no parking in front of a bus stop) | OSM `parking:left/both` on 20 ways, 27 lots, 29 garage entrances; city 37 meters (rates, hours), disability bays, permit zones (VanMap), car-share bays, motorcycle parking, parking tickets per block; Mapillary 25 parking signs, 18 meters, 14 no-parking signs | a shoulder is parking only by an OSM parking area or a Mapillary sign | a kerb lane is parking where OSM's `parking:*` says so, or a meter stands beside it (pay parking, the meter's rates and hours), or a sign says so; disability / car-share / motorcycle bays as parts of it; no parking where a no-parking sign or a bus stop is |
| **bus stops** | OSM 17 stops (stop number, shelter, bench, bin, lit, kerb height, wheelchair, trolleybus); TransLink GTFS routes and frequency | points without details, not drawn on the unit page | a `bus stop` part on the sidewalk (the waiting area, its shelter / bench / bin), the kerb lane in front of it no parking, routes and buses per hour from GTFS |
| **building use** | OSM `building` (apartments 191, retail 61, commercial 44, office 18, `yes` 54); ~380 shops and services inside; city storefronts (1,008 near), business licences, heritage, schools, libraries, non-market housing, zoning, property tax report (land use per parcel); Metro Vancouver office inventory | the raw `building` value, shown as "class" | a building `use` (residential, retail, office, mixed, civic, ...) and its ground-floor use, each with its source: the OSM tag where specific, else the shops inside it, the city's storefronts and licences, zoning |
| **crossings, accessibility** | OSM crossing markings, signals, push buttons (59), sound (50) and vibration aids, tactile paving (235), `wheelchair` | crossing / zebra / signalised | carried on the crosswalk part: markings, signal, button, sound, tactile paving |
| **kerbs** | OSM `kerb` raised / lowered / flush (102 nodes); city kerb bulges; lidar heights | kerb points without type | a kerb's height class along its line (lowered at crossings), bulges as part of the sidewalk |
| **signs and signals** | Mapillary 577 sign fronts, regulatory classes (no entry, keep right, no parking, ...), 51 pedestrian signals; city turn-rule register, signal types, speed-limit segments | stop / give-way / parking signs, signals | every regulatory sign class kept; pedestrian signals on the crosswalks; the city register checks `space.turn` (automatic `check` rows) |
| **poles, utilities** | Mapillary 383 utility poles, 33 junction boxes, 30 manholes, 21 hydrants, 9 catch basins; OSM hydrant type and position | from the city survey and OSM only | Mapillary's classes join `unit.group_objects` like the others |
| **trolleybus** | OSM `trolley_wire` on 40 ways (Broadway, Granville) | nothing | overhead wires along those roads (3D), a road attribute |
| **frontage** | 87 entrances, shops, cafés (`outdoor_seating`), storefronts, Overture places | entrances | the use of each building face at the sidewalk (shop, café, lobby, blank wall) |
| **construction** | OSM construction sites (6); city road-ahead projects ("Broadway Subway", to 2027-12); cameras | nothing | a unit inside a construction project or site is flagged, with the project and its end date |
| **surface and height** | Metro Vancouver 2 m land cover (paved, grass, trees); city and region lidar 2022; city 1 m DEM | guesses | ground between two roadways is an island where the land cover says grass or trees, roadway where paved; heights of kerbs, buildings, trees from lidar |
| **condition** | OSM `smoothness`; city pavement and sidewalk ratings; 311 requests (sidewalk repair, potholes, lights out) | ratings in the dossier only | on the parts they rate |

## City of Vancouver open data: all 200 datasets

Checked 2026-10-09. 68 have no location (budgets, council, census, staff pay, ...) and are left out, except the ones marked below.

- **Used** (15): public-trees, street-lighting-poles, parking-meters, water-hydrants, drinking-fountains, wayfinding-map-stands,
  sewer-manholes, sewer-catch-basins, street-lighting-junction-boxes, traffic-signals, disability-parking, right-of-way-widths,
  bikeways, sidewalk- and pavement-condition-rating, intersection-traffic-movement-counts, directional-traffic-count-locations.
- **To use, street** : lidar-2022 (and 2013, 2018), digital-elevation-model, elevation contours, orthophoto-imagery-2022 (MrSID /
  ECW: needs a converter), property-parcel-polygons, property-cadastral-boundaries, property-tie-lines, property-easements,
  block-outlines, building-lines, public-streets, non-city-streets, lanes (alleys), street-intersections, one-way-streets,
  truck-routes, snow-removal-routes, greenways, motorcycle-parking, electric-vehicle-charging-stations,
  shared-e-scooter-stations, rapid-transit-lines and -stations, railways, public-washrooms, public-art, food-vendors,
  street-lighting-service-panels and -conduits, water-control-valves, water and sewer mains (underground), road-ahead (current
  closures, under construction, upcoming), city-project-package-street, web-cam-url-links, 3-1-1-service-requests, graffiti;
  without location but joinable: bike-racks (by address), parking-tickets (by block), property-tax-report (by parcel).
- **To use, buildings**: storefronts-inventory, business-licences, property-addresses, heritage-sites, schools, libraries,
  community-centres, cultural-spaces, non-market-housing, city-owned-properties, zoning-districts-and-labels,
  issued-building-permits, building-footprints-2015 (outlines only).
- **Context only**: parks, local-area-boundary, business-improvement-areas, view-cones, noise-control-areas, designated-floodplain,
  district lots, legal lot numbers, block numbers, facet grid, shoreline, 1912 fire insurance map.
- **Not relevant**: capital plans and budgets, council and elections, voting places, staff pay, animal control, census profiles,
  cemetery index, Olympic 2010 plans, food programs, shelters, rental standards, water quality reports, older footprints and
  licences, dashboard tables.

VanMap layers the portal lacks (Hosted): TrafficTurnRestriction, TrafficSpeedLimitSegment, TrafficCrosswalk, Traffic4WayStop,
stTrafficSignal, Curb_Bulges, Diverters, stTrafficCalmingArea, Pop_up_Plazas, littercontainer, slPosterCylinder,
stCarShareParking, stChargingStation, stMotorcycleParkingNonMetered, StreetVendors, stWirelessFacilities,
ResidentialParkingPermitZones, lsPropertyLine, lsBuildingLine, lsCityBlockArea, stBridgesRelatedStructures. Benches, bus shelters
and bike racks need a token.

Metro Vancouver (hub): 2025 imagery 7.5 cm (MrSID download only), classified and bare-earth lidar 2022, land cover 2020 at 2 m,
tree canopy and impervious surface, office building inventory 2022, generalized land use 2016.

## Order (proposed)

1. parking; 2. bus stops (with GTFS); 3. building use; 4. crossing and kerb details; 5. every Mapillary class we can place;
6. the city's turn-rule register as automatic checks; 7. land cover and lidar (islands, heights); 8. the rest of the table.

Each rule is general: it names the kind of evidence, not the place, and runs wherever that kind of source exists.
