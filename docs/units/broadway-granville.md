# W Broadway × Granville St

<p class="lead">The second unit of the unit dossier (<a href="../../design/unit-dossier/">one unit in full</a>): where West Broadway
meets Granville Street in Fairview, Vancouver.</p>

**Where:** 49.263611 N, 123.138546 W (OSM node 11102738098, unit `i0-11102738098`). Both are major roads (Granville is trunk, Broadway primary on one
side of it and secondary on the other), crossing at a signalised junction with signalised crosswalks on all four arms and bus stops on its corners. It lies inside the 1 m lidar
area on disk.

```bash
urbanstyle unit broadway-granville --at -123.138546 49.263611 --osm ../duckOSM/data/db/vancouver_city.duckdb --city Vancouver --vancouver
```

## Source inventory

Everything within 120 m of the junction centre, counted 2026-10-09.

| source | where it comes from | what it has here | gaps |
|---|---|---|---|
| **OpenStreetMap** | duckOSM `vancouver_city.duckdb` (raw tags) | 16 road ways (4 trunk, 4 primary, 4 secondary, 4 residential) and 12 service ways: `lanes` on 13, `turn:lanes` on 4, `maxspeed` on 15, `surface`, `lit`; 27 footways (12 tagged `footway=sidewalk`); 14 crossings (8 with traffic signals), 5 traffic signals, 6 bus stops, 6 benches, 9 bike parkings, 2 post boxes; 36 buildings, 19 with floor counts | no `width`, no `parking:*`, no kerb lines, no lamps |
| **City of Vancouver open data** | Opendatasoft Explore API v2.1, no key; `urbanstyle unit --vancouver` → `<unit>.vancouver.json`; Open Government Licence - Vancouver | **surveyed objects:** 38 street trees (species, **height 3-14 m**, trunk diameter; updated 2026-10-05), 55 street-light poles, 2 traffic signals, 37 parking meters, 4 hydrants, 19 catch basins, 27 manholes, 11 lighting junction boxes, 1 drinking fountain, 3 wayfinding stands. **Rules:** each meter's rates, time limits and loading-zone hours. **Roads:** 15 right-of-way widths (legal, property line to property line), 2 bikeways, 30 pavement and 16 sidewalk condition ratings | right-of-way widths come without a unit (66, 80, 99 are feet, others look like metres); no kerb lines, no markings, no signal timings |
| **City buildings** | same API: `building-footprints-2009` (62 here), `building-footprints-2015` (40, 2D only) | 2009 outlines with **heights**: ground, roof, average and maximum height (4-54 m) and roof type | 2009 and 2015, not updated; not loaded into the dossier yet |
| **City frontage** | same API: `storefronts-inventory`, `property-parcel-polygons` | 401 ground-floor businesses (name, category, year recorded); 49 parcels | not loaded yet |
| **Traffic** | same API: `intersection-traffic-movement-counts`, `directional-traffic-count-locations` | **turning counts at this very junction** ("by lane and direction", per the dataset); 6 mid-block directional count locations on the arms | the counts themselves sit behind a VanMap link (`app.vancouver.ca/vanmapmtc_net/#130650`): to open by hand, check the dates and whether they can be downloaded |
| **Mapillary** | API, `urbanstyle mapillary` (CC BY-SA) | 47 street lights, 15 bins, 12 traffic lights, 3 parking signs, 2 stop signs, 2 left-turn arrows, 2 benches, 1 parking meter; **559 photos** (106 from 2024, 374 from 2021, none panoramic) | positions 1-5 m off; few markings detected |
| SUMO | from duckOSM (`to_sumo`) | lane geometry, junction shape, lane-to-lane moves | only as good as its inputs |
| **City orthophoto** | `orthophoto-imagery-2022` (tiles as MrSID / ECW); Open Government Licence - Vancouver | aerial photo at **7.5 cm**, June 2022: kerb lines, lane markings, crosswalks, tree crowns | must be traced; MrSID / ECW need GDAL with the right drivers |
| **City lidar** | `lidar-2022` (LAS tiles `489000_5456000` and `490000_5456000` here, zipped); on disk: 1 m DTM and DSM, `duckOSM/data/dem/granville_island-1m-*.tif` | ground and surface heights at 1 m; the point cloud is classified (ground, low and high vegetation, buildings) | 1 m is too coarse for kerbs; the point cloud may show them (to try) |
| `elevation-contour-lines-1-metre-contours` | same API | 9 contours | coarser than the DTM |
| Street View | view only | for checking by hand | its terms forbid extracting data |

**What this says so far:** Vancouver publishes, openly and without a key, most of what Stockholm keeps closed: street trees with their
heights and species, every street-light pole, parking meters with their rules, building heights and a 7.5 cm orthophoto. For street
furniture the city's survey and Mapillary agree in kind (55 poles against Mapillary's 47 lights); OSM maps no lamps here. OSM has no
widths and no parking rules here, so the city fills both gaps. Kerb lines and markings are open from no source as vectors: they are
in the orthophoto, and perhaps in the lidar points.

## The dossier

`data/units/broadway-granville.duckdb`, built 2026-10-09 in about 1.5 minutes. The unit is the junction box and its four crosswalks
(680 m²), so most of the city's objects (trees, meters) sit just outside it, on the arms. Whether the outline should reach out to the
stop lines or the block corners is the open question the Skanstull unit raised as well.

| table | rows | of which from the city |
|---|---|---|
| object | 30 | 2 street lights, 1 signal, 2 catch basins, 1 manhole |
| rule | 19 | 6 right-of-way widths |
| observation | 64 | 7 sidewalk and 3 pavement ratings, 1 turning-count link, 5 count locations |
