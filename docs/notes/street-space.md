# Street space

The first goal of urbanstyle: **calculate the street space at every level** (-2 … 2) from
data we already have (duckOSM centerlines, Overture buildings).

## Definitions

| Term | Meaning |
|---|---|
| **Street space** | The whole open strip of a street, from the building face on one side to the building face on the other (the right-of-way, ROW). |
| **Travelway** | The part of the street space where vehicles move (car, bus, bike lanes). |
| **Pedestrian realm** | The part of the street space beside the travelway where people walk. |

`street space = travelway + pedestrian realm`. Only the street space is *measured* in this step.
The two zones are cut out of it afterwards (see [Zones](#zones)).

Why this hierarchy: Seattle's *Streets Illustrated* (pedestrian realm ↔ flex ↔ travelway ↔ flex ↔
pedestrian realm), NACTO sidewalk zones, and CityGML 3.0 Transportation (`TransportationSpace` →
`Section`/`Intersection` → `TrafficSpace`/`AuxiliaryTrafficSpace`).

## Sources (decided)

**duckOSM only.** Centerlines come from its `driving` / `walking` / `cycling` schemas, buildings from
`features.buildings` (tags `building:levels`, `height`, `building:min_level`, `location=underground`;
built on a copy from `raw.*` when the database has no `features`). Overture is not used. On both pilots
it has only 3-8% more footprints than OSM; its extra value is floor and height values, and
`width_m` is too sparse to matter (7% of Södermalm, under 1% of Monaco). Keep it in mind where it
adds information, for example rail, water or buildings OSM lacks.

## Inputs

- `space.element` (centerlines): roads, walkways, cycleways, each with `level`,
  `level_src` (`layer` / `bridge` / `tunnel` / `default`), `width_m` and the node ids `src` / `dst`.
- `space.element` (buildings): footprints with a level span `level_min..level_max`.

## Algorithm

Done in a metric CRS (UTM), per element, grouped into containers (see Containers below; walkways and cycleways
within 15 m of that road at the same level join it).

### Ground elements (level 0, not a bridge or tunnel): measure the cross-sections

1. **Sections.** Every 3 m along the centerline (at least both end points), cast a ray
   perpendicular to the line to the left and to the right. The ray length is the **reach cap**
   `cap = min(1.5 × width_m + 8, 25)` m.
2. **Stop at a building face.** Each ray stops at the first building that has a floor at this
   level. Its length is the half-width on that side. A ray that hits nothing within the cap is
   marked **open** and gets the cap. A building crossed at distance 0 (a passage under a building)
   gives no information; the half-width falls back to `width_m / 2`.
3. **Never narrower than the road.** `half-width = max(measured, width_m / 2)`.
4. **Smooth.** Rolling median over five neighbouring sections, per side, so one odd section does
   not make a spike.
5. **Polygon.** Join the left and right end points of each pair of neighbouring sections into a
   quad, and union all quads of the container.

Measured per container: `mean_width_m` (mean of left + right) and `open_share` (share of sections
that hit nothing).

### Structure elements (level ≠ 0, or `level_src` is `bridge` / `tunnel`)

Buildings do not bound a deck or a tunnel, so no rays are cast. The street space is the
centerline buffered by `width_m / 2 + 1 m` (parapet or wall allowance).

### Levels

Obstacles are chosen per level: at level L only buildings with a floor at L count. A bridge at
+1 does not change the street space beneath it at 0.

## Containers: sections, path spaces, rail spaces and intersections; streets as groups

The structure follows CityGML, IFC and OpenDRIVE (`docs/design/partitioning-research.md`): a street is divided at every junction into
**sections**, the stretches between two intersections; **intersections** are pieces of their own, shared by the streets that meet
there. A **street** is a *group* of its sections and of the intersections it arrives at; one intersection can be in several groups.

- **Street** (a group, `space.street`): the roads of one level that share a **name** and are connected by a shared node, so
  both carriageways of a boulevard and every way of a long street belong to one street. An unnamed road is its own way. Id
  `k<level>-<smallest OSM way id>`. It holds sections and, through `space.arm`, intersections.
- **Section** (container kind `section`): the roads of one street between two junction nodes (a junction node is one where 3 or more
  road edges meet; roads of the same street that share a node that is *not* a junction are one section), with the walkways and cycleways
  that run along them: at least 60% of a footpath's length within 15 m of that road. A path that only passes close (a park path, a bike
  path leaving the street) does not join. Id `s<level>-<smallest edge id>`; its `street_id` is the street it belongs to.
- **Path space**: a connected network of footpaths and cycleways with no road along them (park paths, alleys, steps). Id
  `p<level>-<smallest OSM way id>`.
- **Rail space**: a connected network of rail lines at one level (`railway` = rail, subway, tram, light_rail, narrow_gauge,
  funicular, monorail). Id `r<level>-<smallest OSM way id>`. A rail line is never attached to a road, even a tram in a street.
- **Intersection**: see below. Id `i<level>-<node>`: the smallest OSM node id among the junction nodes of the piece, so it is
  stable across rebuilds (a negative virtual node id is used only when the piece has no real node).

`space.arm(intersection_id, section_id, street_id, osm_id, node_id, level)` records which street (and which of its sections) arrives
at which intersection. Streets that are split by a different name or by a gap in the data are separate groups.

Earlier versions: one container per OSM way (cut streets into many pieces, split dual carriageways, gave footpaths containers of
their own), then one container per whole street (a multi-part polygon that hid the section structure and took in every footpath
that came near the road). The first was replaced after the Rosenlundsgatan review, the second after the research on how others
partition.

## Partition: sections and intersections (no overlaps)

Measuring each OSM way on its own double-counts the space: at level 0, **37% (Monaco) and 35%
(Södermalm) of the summed container area was counted twice** (6,250 and 10,354 overlapping pairs).
Every junction was measured by each street entering it, sidewalks overlapped the road beside them, and
the two carriageways of a dual road each measured the whole space between the buildings. CityGML
avoids this by making a street space a **partition** of `Section`s and `Intersection`s, and so do we.

Per level, in the metric CRS:

1. **Street space** `U` = the union of every measured street space above (rays and structures). This is
   the true street space; it has no double counting.
2. **Intersections** (the physical intersection area of traffic engineering, not a disc). A **junction** is a node where 3 or more
   road elements meet. Junction nodes closer than `MERGE_NODES_M` (15 m) form one cluster (a dog-leg, the nodes of a roundabout, the
   two ends of a short link), as long as the cluster stays under `MERGE_DIAMETER_M` (30 m) across. Each arm is **cut straight across
   the street**, at half the measured width of the widest *other* arm at the node plus `CROSS_MARGIN_M` (1 m). The intersection is the
   free space between those cuts (every cut extended as a half-plane), bounded by building faces; the hull of the corner points is
   only a fallback.
3. **Sections and path spaces.** A section follows the measured building faces where a side is bounded (at least 50% of its samples
   hit a building), and a smooth parallel line at the reach where it is open. Its ends are the straight cuts of step 2. Where two
   corridors overlap, each ray stops halfway to the centerline of the nearest parallel *street* (not path), so the border is a
   smooth line parallel to both. A final close then open by `SHAPE_M` (2 m) removes notches and spikes. There is **no Voronoi
   diagram** in the partition, and the hull is a fallback only (the method of `section-intersection-v2.md`).
4. Every point of `U` is now in exactly one container. Intersections are named after the streets that meet there. A container
   under 1 m² is dropped, and a road or footpath whose whole section went to an intersection belongs to that intersection.
5. **Zones** are cut from each container area: `travelway` = the measured travelway of the level, `pedestrian_realm` = the rest.

Check (in the tests and on both pilots): **zero overlapping pairs, and the summed area equals the union.**

### Partition results (2026-10-02, Voronoi/hull method; counts have changed since, `checks.py` prints the current table)

| Level 0 | Monaco before → after | Södermalm before → after |
|---|---|---|
| area counted twice | 37% → **0.00%** | 35% → **0.00%** |
| overlapping pairs (> 1 m²) | 6,250 → **0** | 10,354 → **1** (a 1 m² sliver) |
| containers | 1,922 → 1,940 (395 intersections) | 3,476 → 4,005 (675 intersections) |
| after the street rule (below) | 985 (507 streets, 83 path spaces, 395 intersections) | 1,419 (613 streets, 131 path spaces, 675 intersections) |
| build time | about 1 → 1.6 min | about 3 → 3.3 min |

What it took: (1) container outlines must be simplified by only 0.05 m; at 0.5 m each polygon is simplified on its own and
neighbours overlap again by about 3 m² each (0.2% of the area, 600 to 900 pairs); (2) every clip uses only the few
neighbouring pieces, never one level-wide polygon. The cost is page size: the dashboards are now 9.5 MB (Monaco) and
15.8 MB (Södermalm).

## Output

`space.container` (one row per container and level): `kind` (`section`, `path`, `rail` or `intersection`), `street_id` (sections), `geometry`,
`mean_width_m`, `open_share` (both NULL for intersections and for structure containers), element counts
(for an intersection, the roads meeting there). `space.zone`: the two zones of each container.
A short element can lose its whole container area to a neighbouring intersection; its `container_id` then
points at no container row (8 elements on Södermalm, 16 on Monaco at the last run).

## Zones

The street space is cut into two zones:

- **Travelway**: where the road's own surface is. For each road section, a ray from the centerline stops at the
  nearest **sidewalk**, and the travelway reaches the kerb, `distance - SIDEWALK_HALF_M` (1 m), kept between 1.5 m and
  `lane width / 2 + 6 m` (room for parking and a bike lane). Where no sidewalk is found it falls back to the lane width
  (lanes × 3.25 m, else a width by class). Bridges, tunnels and very short roads use the lane width.
- **Pedestrian realm**: the rest of the street space (sidewalk, furnishing zone, frontage). It is still a remainder, but
  its inner edge is now the measured kerb wherever a sidewalk was found.

A **sidewalk** is a walkway or cycleway that runs along a road (within `NEAR_M`, 15 m of it), and is not a crossing
(`footway=crossing`, `highway=crossing`), steps, a corridor, a platform or an elevator. Only 6–9% of the walking ways are
tagged `footway=sidewalk` in these pilots, so tags alone would find too few; the tag is read (`element.subtype`) but
geometry decides.

**How much is measured.** `kerb_share` is the share of a street's road sections where a sidewalk was found. On level 0:
Monaco 27% on average (120 of 506 streets with a road have none), Södermalm 19% (146 of 613). Elsewhere the travelway is
the lane-width guess. The zone areas are about 24% travelway / 76% pedestrian realm in both pilots.

## Rail and stations

**Rail** comes from duckOSM's `features.streets` (railway lines) as elements of type `rail`. The level is read like a road's
(`layer`, else bridge +1, tunnel -1); a Unicode minus (U+2212) in a layer tag counts as a minus. Width is 4 m (tram 3 m).
Underground and elevated rail are structures: the street space is the line buffered by `width/2 + 1 m`, with no rays. Rail at
ground level is measured with rays like a footpath. A rail container's only zone is `track` (its whole area).

**Stations** come from `features.public_transport` (`station`, `halt`, `tram_stop`) into `space.station` (`id`, `name`,
`kind`, `level`, `geometry`). The level is, in order: an explicit `level` or `layer` tag, the level of the nearest rail line
within about 60-90 m, -1 for a subway station, else 0. So a station sits where its tracks are.

**Levels outside the kept range.** Roads, walkways, rail and stations whose level lies outside -2…2 are **shown at the
nearest kept level** (a metro at layer -3 sits at -2) instead of being dropped; only buildings lying entirely outside are
dropped. A tag layer -3 and one layer -5 therefore look the same.

First results: Monaco has 11 rail ways (7 at -2, 4 at -1), 3 rail spaces and one station, *Monaco - Monte Carlo*, at -2.
Södermalm has 59 rail and subway ways across all five levels, rail spaces at every level (12 at -2, 9 at -1, 14 at 0,
8 at +1, 5 at +2) and 7 stations, all at -2: the six metro stations (Hornstull, Mariatorget, Medborgarplatsen, Skanstull,
Slussen, Zinkensdamm) and *Stockholms södra*, whose tracks are mapped at layer -2 in OSM. Entrances are tied to their stations (see Links).

## Quality of the street space

Per container, for the road's sections: `mean_width_m`, `narrow_half_m` and `wide_half_m` (the nearer and the farther
side, from the centerline to the building face or the cap), `open_share` (a side reached the cap), `one_side_open_share`
(exactly one side reached it: a lopsided street) and `kerb_share`. The dashboard tints a street space **yellow ("capped")**
when `open_share >= 0.5`: its edge is the reach cap, not a building face, so its width and its pedestrian realm are
approximate. The cap for walkways and cycleways is `1.5 × width + 4` (roads `+ 8`), so footpaths no longer spill 11 m into
open ground; the total street space shrank by 7% (Monaco 121.7 → 112.8 ha) and 9% (Södermalm 307.4 → 278.3 ha).
Level 0, streets with a road: `open_share` 0.84 (Monaco) and 0.79 (Södermalm), `one_side_open_share` 0.33 and 0.31,
mean narrow half-width 10.0 m and 9.9 m, mean wide half-width 12.4 m and 12.2 m.

## Links between levels

`space.link`: a **link** is a node where elements of two different levels meet, or a station entrance. Columns: `node_id`,
`level_a < level_b`, `type`, `assumed`, `geometry` (the node), and for entrances `station_id`, `match`, `dist_m`.

| type | rule |
|---|---|
| `elevator` | the node is tagged `highway=elevator` |
| `stairs` | one of the elements is `highway=steps` |
| `ramp` | a bridge or tunnel is involved |
| `connection` | any other level change (a `layer` tag on its own); shown as **Other level change** |
| `entrance` | `railway=subway_entrance` or `railway=train_station_entrance` on a level-0 way (within about 7 m). Tied to a station: the station with the same name within 600 m, else the nearest station of its kind (subway entrance → subway station, train-station entrance → another station) within 250 m. The link then goes from the station's level to 0, with `assumed = false`, `station_id`, `match` (`name` or `nearest`) and `dist_m`. With no station found it stays an **assumed** link to level -1. |

Södermalm has 18 entrance links: 16 tied to a station by name (Skanstull 7, Hornstull 3, Medborgarplatsen 3, Slussen 1,
Zinkensdamm 1, Mariatorget 1), so they link level 0 to -2; 2 stay assumed (no subway station within 250 m). Monaco has 4
train-station entrances: 2 tied to *Monaco - Monte Carlo* (74 m and 150 m, nearest), 2 assumed (484 m and 550 m away). Of the 26
entrance nodes on Södermalm, 8 are not on a level-0 way and give no link.

Other links: Monaco 551 in all before the rail work (connection 316, stairs 111, ramp 76, elevator 48). A node shared by three
or more levels produces several pairs, including non-adjacent ones (for example -2 / 1); these are hubs and are kept as they
are. Elevators and unlayered stairs that join two points of the same integer level are not links (the height difference is in
the terrain, not in our levels).

## Parameters

`STEP_M = 3` (section spacing), `CAP = min(1.5 × width + 8, 25)` m, `PARAPET_M = 1`,
`INTERSECTION_M = 4`, `CROSS_MARGIN_M = 1`, `MERGE_NODES_M = 15`, `MERGE_DIAMETER_M = 30`, `SHAPE_M = 2`, `ENTRANCE_NAME_M = 600`, `ENTRANCE_NEAR_M = 250`, `SIDEWALK_HALF_M = 1`,
`SMOOTH = ±2 sections`, `NEAR_M = 15` and `ALONG_MIN = 0.6` (walkway-to-road join). All are flat guesses, set at the top
of `src/urbanstyle/container.py`; measured widths (Overture `width_m`, GMNS) can replace `width_m` later.

## Validation

- A unit test with a street between two buildings 10 m and 6 m from the centerline: the measured
  mean width must come out near 16 m.
- Sanity check on both pilots: the street space always covers the road itself (width ≥ `width_m`),
  and the share of `open` sections is reported per level.

## First results (2026-10-02)

Run: `urbanstyle build <duckosm.duckdb> data/<area>.duckdb`, then `urbanstyle dashboard data/<area>.duckdb viz/<area>.html`
(about 1 min for Monaco, 3 min for Södermalm). Tests: `pytest tests`, 3 passing, including the
10 m / 6 m street that measures about 16 m wide and not open.

| Level 0 | Monaco | Södermalm |
|---|---|---|
| containers | 1,634 | 3,476 |
| median street-space width | 21.5 m | 20.7 m |
| share of sections that hit no building (`open`) | 0.84 | 0.78 |

Levels -2, -1, 1, 2 are structure containers (tunnels and bridges): geometry only, no measured
width. All geometries are valid and non-empty.

**Reading these numbers honestly:** most sections reach the cap without meeting a building, so a
median width of about 21 m mostly reflects the cap, not a measured facade-to-facade distance. The
width is only trustworthy where `open_share` is low. Residential streets alone still show about 53%
open sections in Monaco, and footways in yards and terraces add open sections of their own. To
reduce the spill into open ground, the next tuning step is a smaller cap for walkways and
cycleways (for example `1.5 × width + 4`), and treating `open_share` as a quality flag in the
viewer.

## Known limits

- Only buildings (and, later, water) are obstacles. Walls, fences and parcels are not in the data.
- Widths come from lane counts or road class, not from surveys.
- Levels below 0 now contain tunnels, rail and metro stations, but still almost no building floors.

## Dashboard

`urbanstyle dashboard data/<area>.duckdb viz/<area>.html` (needs roadstyle: `pip install urbanstyle[dashboard]`),
then serve `viz/` (`python3 -m http.server 8765`); Street View loads only over http.

Built on roadstyle's `render_edges`: its basemap picker, Street View window and Layers control come for
free. The buildings, the two zones and the links are overlays; the roads are drawn faintly, because
roadstyle's Street View follows a clicked road. The left panel starts with the **layer list**: one checkbox per drawn thing (street space, travelway, pedestrian realm,
buildings, the three centerline types, each link type), each with its colour and a one-line meaning, plus a note that
everything else on the map is the basemap. Link types are named Ramp, Stairs, Elevator, Station entrance and Other level
change (`connection` in the data). Below it is the hierarchy: Pilot area →
Buildings / Stations / Containers / Links, with levels inside each branch, and the level buttons
(-2 … 2) at the top. Click a node to filter and zoom the map.

## Street rule results (2026-10-02)

Level 0, after grouping by street: Monaco 1,940 → **985** containers, Södermalm 4,005 → **1,419**; still no overlaps
(0 pairs, 0.00% counted twice). The long Götgatan on Södermalm, which was cut into pieces such as `m0-1456305944`,
`m0-1288178518` and `m0-141258079`, is one container `s0-20289548` (59 roads, 96 walkways, 41 cycleways). Short
disconnected pieces with the same name remain separate (for example `s0-1225531861`).

## Dashboard additions (2026-10-02)

- **Jump between levels.** Clicking a link marker shows, at the top of the left panel, `ramp 1238671024: levels -1 and 0 → go to
  level [-1] [0]`; the buttons switch to that level. Clicking a station offers its level and keeps the station selected.
- **Speed.** In a headless test browser the first draw at street zoom took one to two minutes. A CPU profile showed the page's
  JavaScript idle for 117 of 125 s (long tasks under 3 s in all), and the console warned of GPU stalls on `ReadPixels`: the wait is the
  headless browser's **software** renderer, not the page's own code. Hiding the outline layers or most overlays only trimmed it
  (110 s and 88 s), so no single layer is to blame. It has not been measured on a real GPU, and nothing was changed for it.

## Along rule (2026-10-02)

First version: any footpath that came within 15 m of a road joined that road's street. A street next to a park then grew arms through
the park (Rosenlundsgatan, `s0-22744754`: 45 attached footpaths and cycleways, 7 of which had only 1-44% of their length within
15 m of the road, among them cycleways of 96, 77 and 72 m). Now a footpath joins a street only if at least `ALONG_MIN` (60%) of its
length lies within `NEAR_M` of one road piece. Path spaces on Södermalm at level 0 rose from 131 to 282 as park and bike paths became
their own containers; the arms of Rosenlundsgatan are gone (its container now has 5 parts, was 7).

## Sections and arm-based intersections (2026-10-02)

Level 0 with the current method (ribbons, straight cuts, plazas; `checks.py` run 2026-10-04 on both pilots, all hard checks PASS):

| | Monaco | Södermalm |
|---|---|---|
| containers (all levels) | 1,665 | 2,657 |
| level 0 | 648 sections of 501 streets, 289 intersections, 417 path spaces, 20 plazas | 1,248 sections of 634 streets, 577 intersections, 513 path spaces, 52 plazas, 8 rail spaces |
| overlapping pairs (P1), multi-part containers (P4), elements with no container (P5) | 0, 0, 0 | 0, 0, 0 |
| intersections with one street group (I2, info) | 17 | 43 |
| arm nodes more than 3 m from their intersection (I4, info) | 20 | 39 |

The Götgatan figures below are from the old method and not re-measured.

Götgatan on Södermalm is one street group (`k0-20289548`) of 17 sections and 11 intersections, 32,486 m², with 147 objects.
Slivers (old hull method): a hull meeting a section left 12 tiny invalid polygons on each pilot; containers under 1 m² are now dropped and every
stored geometry is made valid.
