# Bridge heights without LiDAR

A bridge profile (`urbanstyle bridge`) gives each axis a vertical profile: grade points `[s, height]` and a vertical curve at each
inside point. LiDAR (`urbanstyle bridge-measure`) can replace these heights with measured ones. Where there is no LiDAR, a person can
set the heights with a small heights file instead.

## Command

```bash
urbanstyle bridge-heights PROFILE HEIGHTS OUT
```

The command reads the profile and the heights file, and writes a new profile to `OUT`. Only the `vertical` of each axis changes.

## The heights file

One entry for each bridge, by its name:

```json
{"Granville Bridge": {
  "default": {"grade": 0.05, "max_m": 27.0, "curve_m": 60.0},
  "a1": [[0, 27], [340, 39], [550, 22.7]],
  "a2": {"from": "a4", "to_ground": true}}}
```

| Key | Value | Effect |
|---|---|---|
| `default.grade` | slope, 0.05 = 5 % | The slope of a ramp up from the ground and down to it. |
| `default.max_m` | metres | The highest height that the rule gives (the clearance of the bridge). |
| `default.curve_m` | metres | The length of the vertical curve at each inside point (smooth crests and sags). |
| `<axis>`: list of `[s, height]` | metres | These points, in order of s. The tool rounds each inside point with a vertical curve. |
| `<axis>`: `{"from": axis, "to_ground": true}` | | The axis starts at the height of the other axis where they meet, and goes down at `grade` to the ground at its far end. If the axis is too short for `grade`, it goes down more steeply, so that it reaches the ground at its end. |

An axis that the file does not name gets the default rule: from each end on the ground it goes up at `grade` to `max_m`, and stays
at `max_m` between. An axis with no end on the ground goes straight between the heights of the axes that it meets (where the file
gives them), else it stays at `max_m`.

## The heights section of a profile (2026-10-22)

A profile can hold its known heights in one section, `heights`: a few numbers, never one per metre. Anyone can add to it: a person,
LiDAR, a survey. The model pulls the deck to these heights; everywhere else the rule (the grade from the ground ends) and the smoothest
line fill in. A profile with no `heights` section works as before.

```json
"heights": {
  "n21918825": {"deck_m": 9.0, "source": "manual", "method": "chosen"},
  "a2": {"mid_m": 6.5, "source": "manual", "method": "chosen"},
  "a1": {"points": [[0, 27.0], [340, 39.0], [550, 22.7]], "curves": [0, 60, 0],
         "source": "City of Vancouver LiDAR 2022", "method": "measured"}
}
```

| Key | Value | Meaning |
|---|---|---|
| an OSM node, `n<id>` | `deck_m` | The deck's height above the ground at that node: a junction, or an end. Every axis that ends there takes it. One number for each junction is the simplest use. |
| an axis id, `a<k>` | `mid_m` | The deck's height above the ground at the middle of that axis (a branch). With one height for each junction, this is the simplest full input: a few numbers for a whole bridge. |
| an axis id, `a<k>` | `points`, `curves` | The axis's line between its first and its last point: straight grades `[s, height]`, each inside point rounded by a vertical curve of the length in `curves` (0: a corner). Outside the first and the last point, the rule fills in. |
| every entry | `source`, `method` | Who gave it. `method` is `measured` (LiDAR, a survey) or `chosen` (a person). |

The tools write into this section:

- `urbanstyle bridge-heights PROFILE HEIGHTS OUT`: a node key in the heights file (`"n21918825": 9.0`) becomes a node entry; an axis
  with one number (`"a2": 6.5`) gets that height at its middle; an axis list becomes that axis's points. All `chosen`.
- `urbanstyle bridge-measure`: the points fitted to the LiDAR stations become each axis's entry, `measured` (Granville: 82 points on
  12 axes from 350 stations).

Granville's profile has its section from its LiDAR fit; its model is the same as before (tests/test_bridge_step5.py).

Not yet used: the ground's own height (`ground_m`) and heights above sea level. The model still stands on a flat ground at 0 m; they come
with a ground model (Monaco: IGN LiDAR HD, docs/HANDOFF.md).

## Sources

Every height that the file or the rule gives is marked `source: urbanstyle`, `method: chosen`, and `rule` tells which key gave it.
Measured heights (LiDAR) keep their own source. Do not mix the two in one axis.

## Limits

- The tool does not check heights against the ground. Set `max_m` so that the deck is clear of the roads under it.
- Where axes meet in the air, give them the same height at the node (use `from`). The 3D model blends small differences smoothly.
