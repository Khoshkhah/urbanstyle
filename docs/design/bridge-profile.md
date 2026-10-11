# Bridge profile

<p class="lead">One file per bridge that holds all that the 3D model needs: the deck outline, the road axes on the deck, the height
of the deck along each axis, the lanes and paths across it, and the piers. Each value has its source and its method. One script makes
the file for any bridge; the dashboard draws the model from the file only.</p>

Status: agreed and built 2026-10-11 (`bridge_profile.py`, `bridge3d.py`). It replaces the values that `bridge3d.py` calculated in the
code (`docs/design/bridges-3d.md`). On Vancouver, `--all` writes 81 profiles in 2 s: 39 with an OSM outline, 42 with a derived
outline. The Granville Bridge has 12 axes and 25 sections.

## Why

Now `bridge3d.py` reads OSM and calculates the model in one step. You cannot see how it gets each lane count, each width or each
height. You can only read the code. A profile file shows each value with its source, and a measurement (LiDAR, the aerial photo) can
replace a chosen value in the file without a change to the model code.

## What the profile uses

The profile uses the standard terms of road design (OpenDRIVE, IFC 4.3 alignment), as `street-objects.md` does:

- **Axis:** a reference line along the deck. A position on the deck is `(s, t)`: `s` is the distance along the axis from its start,
  `t` is the lateral offset (left of the axis is positive).
- **Vertical profile:** the height of the deck top on the axis, as points `(s, z)`, linear between the points.
- **Section:** a length of the axis, from `s0` to `s1`, where the cross-section does not change.
- **Band:** one strip across a section, from left to right: a lane, a bike lane, a footway, a median, a kerb, a parapet. Each band
  has its centre offset `t` and its width.

A bridge with ramps, for example the Granville Bridge, has more than one axis. Each OSM chain of road ways on the deck between two
branch points is one axis.

## The file

`<name>.bridge.json`, in metres, in the UTM zone of the bridge (`crs`). `z` is the height above `z_datum`.

```json
{
  "format": "urbanstyle.bridge/1",
  "name": "Granville Bridge",
  "crs": "EPSG:32610",
  "z_datum": {"value": "ground at the ends", "source": "urbanstyle", "method": "chosen"},
  "made": {"by": "urbanstyle bridge", "date": "2026-10-11",
           "inputs": ["data/vancouver_city.osm.duckdb", "data/vancouver_city.gmns.duckdb"]},
  "deck": {
    "outline":   {"value": [[491203.1, 5457402.7], "..."], "source": "osm w123456 (man_made=bridge)", "method": "mapped"},
    "thickness": {"value": 1.8, "source": "urbanstyle", "method": "chosen"},
    "parapet":   {"value": 1.1, "source": "urbanstyle", "method": "chosen"}
  },
  "axes": [{
    "id": "a1",
    "ways": ["w1419040127", "w1419040129", "w1419040132"],
    "line": {"value": [[491210.4, 5457390.2], "..."], "source": "osm", "method": "mapped"},
    "length_m": 812.4,
    "ends": [{"s": 0.0, "ground": true, "node": "n2730151"}, {"s": 812.4, "ground": true, "node": "n2730199"}],
    "vertical": {"points": [[0.0, 0.0], [540.0, 27.0], [812.4, 0.0]], "source": "urbanstyle", "method": "chosen"},
    "sections": [{
      "s0": 0.0, "s1": 210.3,
      "links": ["8511077704723192952", "8511077704723192953"],
      "bands": [
        {"type": "lane", "lane_id": "8511077704723192953_2", "direction": "backward", "use": "auto", "turn": null,
         "t": 4.9, "source": "osm lanes; duckOSM GMNS divides them between the two directions", "method": "derived",
         "width": {"value": 3.25, "source": "duckOSM GMNS (road class)", "method": "chosen"}},
        {"type": "lane", "lane_id": "8511077704723192952_1", "direction": "forward", "use": "auto", "turn": "through",
         "t": -1.6, "source": "osm lanes; duckOSM GMNS divides them between the two directions", "method": "derived",
         "width": {"value": 3.25, "source": "duckOSM GMNS (road class)", "method": "chosen"}},
        {"type": "cycleway", "way": "w1316244489", "t": -8.2, "source": "osm w1316244489", "method": "mapped",
         "width": {"value": 3.0, "source": "urbanstyle", "method": "chosen"}}
      ]
    }]
  }],
  "piers": [{"axis": "a1", "s": 25.0, "width": 1.5, "source": "urbanstyle", "method": "chosen"}]
}
```

## Rules

1. **The lanes come from duckOSM's GMNS export.** Its lanes come from SUMO (duckOSM 0.4.0), so the bridge and the street at
   level 0 have the same lanes. A band names its `lane_id`, and its width keeps the source that GMNS gives: `osm width:lanes` and
   `mapped`, or `duckOSM GMNS (road class)` and `chosen`. The lane count is never changed (see
   `feedback-never-change-mapped-counts`). Each lane band also says where the lane count comes from:
   - `mapped`: OSM's `lanes` on a one-way way, or `lanes:forward` and `lanes:backward`;
   - `derived`: OSM's `lanes` on a two-way way, divided between the two directions by GMNS;
   - `chosen`: no `lanes` tag, so GMNS sets one lane in each direction.
2. **A new section starts where the bands change:** at the end of a GMNS link, or where a lane starts or stops. So you can see on the
   axis where the lane count changes and which link gives it.
3. **`t` is derived:** the offset of the GMNS lane line (`lane.geom`) from the axis, at the middle of the section. A cycleway or
   footway is a band of a section if it is less than 25 m from the axis, parallel to it (the angle is less than 26°) and nearer to
   this axis than to the other axes.
4. **The deck outline is OSM's `man_made=bridge`** where OSM has one. If OSM has no outline, the outline is the union of the
   sections, each as wide as its bands, with method `derived`.
5. **Every value has `source` and `method`** (`mapped`, `measured`, `derived`, `chosen`). A value that no source gives is
   urbanstyle's own, with method `chosen`.
6. **Scripts make the file. Nobody edits it by hand.** A measurement is a script that replaces a value and its source and method:
   for example, the vertical points from LiDAR (`measured`), or a lane width from the aerial photo.
7. **The model reads only the profile.** `bridge3d.py` makes the deck, the lanes and the lines on one height surface: at each point,
   the vertical profiles of the two nearest axes, each weighted by the distance to the other (within 40 m). So no lane steps where the
   nearest axis changes at a fork. The piers come from `piers`.
8. **A lane stops where SUMO ends it at a junction** (2026-10-11). Each lane band has `s_from` and `s_to`: the ends of its GMNS
   `lane.geom_cut`, projected onto the axis. Through a fork or a merge on the deck, the profile's `connectors` hold SUMO's paths from
   lane to lane (GMNS `lane_connector`, both lanes on the bridge's links), each with its width. Before, each axis drew its lanes to its
   OSM node, and at the forks the lanes of two axes lay on each other in 48 places, at different heights. Now 18 overlaps remain,
   where two ramps run close together after a fork: their OSM lines are closer than their lanes are wide.
9. **Every path on the deck is drawn** (2026-10-11). A path that is no band of an axis (it turns, crosses or joins) is in the
   profile's `paths`, along its own OSM line. Before, 12 paths were missing on the Granville Bridge, among them 111 m of the Granville
   Connector.

## Commands

```bash
duckosm gmns data/vancouver_city.osm.duckdb --out data/vancouver_city.gmns.duckdb -m driving       # once per area (Vancouver: 23 min, 2.7 GB)
urbanstyle bridge data/vancouver_city.osm.duckdb data/vancouver_city.gmns.duckdb data/bridges --name "Granville Bridge"
urbanstyle bridge data/vancouver_city.osm.duckdb data/vancouver_city.gmns.duckdb data/bridges        # every road bridge
urbanstyle dashboard DB OUT --bridge data/bridges/granville-bridge.bridge.json
```

Without `--name`, the command makes one file for each road bridge in the database: each `man_made=bridge` outline with road ways on it, and each
chain of road ways with `bridge=*` that has no outline.

The OSM database must hold all of the bridge: the clip of one unit holds only the ramps of the Granville Bridge.

## Heights from LiDAR (measured)

Status: built 2026-10-11 (`bridge_lidar.py`), on the Granville Bridge. This is rule 6: a script replaces the chosen heights and says
where they come from.

```bash
PYTHONPATH=src:../ducklidar/src ~/miniconda3/envs/lidar/bin/python -m urbanstyle bridge-measure \
    data/bridges/granville-bridge.bridge.json data/bridges-measured/ --lidar <ducklidar Parquet tiles>
```

**The survey.** City of Vancouver LiDAR 2022 (open data portal, dataset `lidar-2022`; Open Government Licence – Vancouver). It was flown on
7–9 September 2022, at about 49 points per m², with a vertical accuracy of 0.081 m (95 %). The horizontal datum is NAD83(CSRS) UTM zone
10N (EPSG:26910); the vertical datum is CGVD28 (GVRD). The tiles are 1 km × 1 km. The classes are unclassified, ground, low and high
vegetation, water, building, other and noise; there is no bridge class, so the deck is mostly in the class "unclassified". The
Granville Bridge needs four tiles: 489000_5456000, 489000_5457000, 490000_5457000 and 490000_5458000. The portal does not let a script
download them, so they come from tiles that are already on the disk, converted to ducklidar's Parquet sidecars.

**The rule.** At a station every 10 m along each axis:

1. The window is 10 m along the axis and as wide as the axis's lane bands there. Vegetation, water and noise returns are left out.
2. Where gaps of 2 m or more split the heights in the window, only the cluster with the most returns is kept: that is the deck seen from
   above. The street or the water under it, seen past the deck's edge, and a lamp post on the deck, are other clusters.
3. The deck top is the 25 % quantile of that cluster, so the cars on the deck lie above it.
4. The ground is the median of the ground and water returns within 30 m.
5. The profile stores the deck top above that ground, because the dashboard's map is flat (its ground is z = 0). A station with fewer
   than 20 returns keeps the chosen value; the profile says which stations are measured (`vertical.stations`, with the deck and the
   ground in CGVD28) and keeps the chosen points (`vertical.chosen_before`).

The deck thickness and the piers stay chosen: from above, the survey does not see the deck's underside.

**Result on the Granville Bridge.** All 311 stations of the 12 axes are measured. The main span's road is at 40.2 m (CGVD28) at its
highest point, 41.3 m above the water under it (−1.1 m during the survey); the chosen value was at most 27 m. The bridge is a deck truss
with 27.4 m of navigational clearance under the truss, so the road on top is higher than the clearance. The south ramp w35354210 is
35.0 m high where it crosses West 5th Avenue, about 8 m above that street (the chosen 5 % ramp gave 1 m to 2.5 m). Where OSM ends that
ramp (node 4846077906), the deck is still 6.8 m above the street beside it: the survey sees a structure there, not ground, so the ramp
reaches the ground farther south than OSM's bridge way says.

**Steps in the measured height.** The deck top is smooth along each axis, but the ground under it is not: the main span passes from
Granville Island (3.6 m) to the water (−1.1 m), so its height above the ground increases by about 4 m there. On a flat map this shows as
a step in the deck.

## urbanstyle's own values (chosen)

No source gives these values yet (`bridge_profile.py`). Each one is in the profile with method `chosen` and the rule that sets it.

| value | | rule |
|---|---|---|
| the deck's height | 5 % up from the nearest point where a road on the bridge meets a ground road, 27 m at most | `GRADE`, `TOP_M` |
| deck and girders | 1.8 m thick | `DECK_M` |
| parapet | 1.1 m | `RAIL_M` |
| a pier | every 50 m along the longest axis, where the deck is 3 m or more above the ground, 1.5 m thick | `PIER_M`, `PIER_MIN_M`, `PIER_W` |
| a cycleway, a footway | 3.0 m, 2.0 m wide | `PATH_W` |

## Not in version 1

- The cross slope of the deck (OpenDRIVE `lateralProfile`): the deck is flat across.
- The lane widths from the aerial photo. (The heights from LiDAR: see above.)
- The piers' real positions. They stay every 50 m (`chosen`) until a source gives them.

## Smooth heights, real landings, piers on every axis, drawn on top (2026-10-11)

- **One reference ground for the whole bridge.** The measured deck is smooth, but the ground under it jumps (a street, Granville
  Island, the water). Each height is now the measured deck above one smooth reference ground: the ground and water samples weighted
  over 60 m and pinned to the deck at each landing. A landing's last 60 m go to 0 smoothly. The axes agree where they meet.
- **A ramp that OSM ends in the air runs on to its measured landing**, along the OSM road that continues it, while the LiDAR still
  sees the deck above the ground (at most 150 m). Granville Bridge: a2 45 m, a8 70 m, a5, a6, a11, a12 5-10 m (`landings` on the axis).
- **The lanes and lines follow their own axis.** The deck blends two axes only where their heights agree within 1.5 m (a fork).
- **Piers along every axis** (`place_piers`), every 50 m where the deck is 3 m or more above the ground, none within 15 m of another;
  made again from the measured heights; each pier only as wide as its own road. Granville Bridge: 52 on 11 axes (before: 11, on the
  main span only).
- **The model is drawn on top.** The dashboard's flat layers (the street, the ground) have no depth test; added after the bridge, they
  painted over it, so on the page only the main span over the water showed. The bridge's layer now stays the top layer. The model's
  origin is the middle of the outline.

## Every landing meets the street (2026-10-11)

Some arms of the Granville Bridge did not touch the ground on the page. All arms that are not landings meet other arms at the same
height (five junctions: 27.0, 22.7, 18.2, 11.7 and 11.6 m). The landings had three faults:

1. **The deck stood on the street as a block.** The deck was always 1.8 m thick, so at a landing its bottom and its side walls were
   under the ground. The bridge is drawn over the flat map, which has no depth, so these parts showed as a block about 3 m high.
   Now the bottom of the deck never goes under the ground: near a landing the deck gets thinner and meets the street flush. A
   parapet is never higher than the deck is above the ground, so it ends where the deck lands.
2. **A landing stopped at the end of one OSM way.** The landing of a ramp that OSM ends in the air follows the OSM roads that
   continue it, way after way, not only the first way. a8 stopped after 70 m on w48525790, 4.0 m above the ground; it now lands
   after 90 m on w1416437416, where the LiDAR deck is 0.4 m above the ground. A landing names only the ways that it reaches.
3. **A landing had lanes and no deck.** OSM's outline stops where OSM's bridge way stops. Each measured landing now adds its
   piece to the deck outline, as wide as its lanes, with method `derived`. Before, a2 had 45 m and a8 had 90 m of lanes with no deck,
   and their decks ended 4.0 m and 8.5 m above the ground.

At every landing the LiDAR deck is now 0.0 to 0.5 m above the ground, and every lane has deck under it.
