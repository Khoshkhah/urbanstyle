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
7. **The model reads only the profile.** `bridge3d.py` makes the deck top from the vertical profile of the nearest axis, the lanes and
   lines from the bands, and the piers from `piers`.

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
- The measurement scripts (LiDAR, aerial photo). Version 1 makes the format and the chosen values, so that the measurements have a
  place to go.
- The piers' real positions. They stay every 50 m (`chosen`) until a source gives them.
