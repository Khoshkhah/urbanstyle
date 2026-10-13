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

## Sources

Every height that the file or the rule gives is marked `source: urbanstyle`, `method: chosen`, and `rule` tells which key gave it.
Measured heights (LiDAR) keep their own source. Do not mix the two in one axis.

## Limits

- The tool does not check heights against the ground. Set `max_m` so that the deck is clear of the roads under it.
- Where axes meet in the air, give them the same height at the node (use `from`). The 3D model blends small differences smoothly.
