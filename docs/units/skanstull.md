# Skanstull: Götgatan × Ringvägen

<p class="lead">The first unit of the unit dossier (<a href="../../design/unit-dossier/">one unit in full</a>): where Götgatan meets
Ringvägen at the south end of Södermalm, Stockholm.</p>

**Where:** 59.30776 N, 18.07660 E. The junction is four nodes within about 10 m: both Götgatan and Ringvägen have a separate
carriageway per direction here, so it is the crossing of two divided roads. The Söderleden tunnel runs underneath (level -1).

## Source inventory

Everything within 120 m of the junction centre, counted 2026-10-09.

| source | where it comes from | what it has here | gaps |
|---|---|---|---|
| **OpenStreetMap** | duckOSM `sodermalm.duckdb` (raw tags) | 43 road ways: `lanes` on 29, `turn:lanes` on 10, parking rules (`parking:*` with zones, fees, times) on ~17, `sidewalk*` on ~15, `width` on 7, `maxspeed`, `surface`, `lit`; 12 cycleways, 55 footways, 10 steps; 18 crossings (12 with traffic signals), 10 traffic signals, 7 street lamps, 6 bus stops, 6 subway entrances, 31 building entrances; 35 buildings, 32 with floor counts | no kerb lines, no building heights, few widths, few lamps |
| **NVDB** (Trafikverket) | `fetching-sweden-data` → `sodermalm_traffic.duckdb` | 155 segments: speed limits (30-70), road width on 44 (3.2-11.5 m), surface, street names; 5 junctions (signal-controlled yes/no); 3 prohibited turns | no lane counts, no traffic volumes (AADT) here |
| **Traffic** | `sensor-matching` observations; Trafikverket sensors; city flow map | Götgatan: hourly flows on 4 edges, 2010-2023 (~231,000 rows); Ringvägen: 5 edges, sparse (2013-2026); Söderleden tunnel below: 5 Trafikverket sensor sites, hourly 2026; city flow map: 34 segments | Ringvägen thinly counted; nothing per lane at the surface junction |
| **Mapillary** | API, `urbanstyle mapillary` (CC BY-SA) | 228 street lights, 77 traffic lights, 26 lane arrows, 21 zebras, 30 no-parking and 22 parking signs, 24 bins, 11 benches, 3 give-way and 2 stop signs; **1,220 photos** (407 from 2025, 167 panoramas) | positions 1-5 m off |
| SUMO | from duckOSM (`to_sumo`) | lane geometry, junction shape, lane-to-lane moves (counts and widths from the sources above) | only as good as its inputs |
| **Stockholm Trafikkontoret, street features** | `openstreetgs.stockholm.se` WFS / OGC API Features, free key by e-mail; CC0 (in the metadata checked) | light fittings, signal posts and lanterns, push buttons, bollards, litter bins, bike parking, bike routes, speed humps; annual counts | surveyed points (accuracy not stated); its NVDB layers go in autumn 2026 |
| **Stockholm Trafikkontoret, traffic rules (LTF)** | `openparking.stockholm.se` LTF-Tolken API and WFS `ltfr:*`, same key; "licence-free" (per-dataset licence unconfirmed) | where and when parking is allowed, street cleaning, loading and special bays, turn bans, bus lanes | |
| **Lantmäteriet orthophoto** | STAC `orto-o2-2025`, Geotorget login and special terms; CC BY 4.0 | aerial photo at **0.16 m**, 31 May 2025: lane markings, crossings and kerb lines visible | the only open source of kerb lines; they must be traced from it |
| **Lantmäteriet ground model** | STAC `dtm-cog` (1 m), Geotorget login; CC BY 4.0 | ground height, 1 m grid (laser 2020-2025) | too coarse for kerbs; the national point cloud is paid |
| Stockholm stad Baskarta (kerbs, trees, surfaces in 3D), 8 cm orthophoto, 2025 point cloud | not open (paid, city licence) | would give kerbs, trees and heights directly | out of reach unless bought |
| Stockholm Stadskarta "infrastruktur" polygons | dataportalen download; licence unconfirmed | sidewalk, refuge island, centre strip, road area | generalised (1:2000-1:6000) |
| Street View | view only | for checking by hand | its terms forbid extracting data |

Checked by a research pass on the providers' own endpoints, 2026-10-09; anything marked unconfirmed is checked again
before use. Street trees, kerbs and road surfaces are **not open** for this site (only an oak register).

**What this says so far:** the furniture is best seen by Mapillary (228 street lights against OSM's 7); the lanes and parking rules by
OSM; widths partly by NVDB; traffic richly on Götgatan only. Still missing from every source on disk: kerb lines, building and
ground heights, surveyed positions of objects. Of these, the city's open street features give surveyed positions (lights,
signals, bins, bollards), the 0.16 m orthophoto shows the kerb lines and markings (to trace), and the 1 m ground model gives the
slope; building heights and trees stay open questions.
