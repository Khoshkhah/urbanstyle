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

## A bridge on a hillside: elevations from the few measured points (2026-10-22)

The flat model puts the ground at 0 m everywhere. On a slope this is wrong: Avenue de la Costa's two road ends are 2 m apart in
elevation, and the ground under its middle is 9 m lower than the deck. The flat model gave a deck 2 m high at its middle; IGN measures 9.2 m.

LiDAR gives only the few points of the heights section: the deck at each junction and at each branch middle, the road at each ground
end, each with `deck_elev` and `ground_elev` (elevations, IGN69). When a profile's heights section has a `ground_elev`, `bridge_surface`
works in elevations:

- z = 0 is sea level, so all bridges of an area share one base on one page.
- A ground end keeps its road's measured elevation. A measured `deck_elev` holds the deck at its junction or at its branch middle. The
  rule fills in between: up from the lowest ground end at `GRADE`.
- The ground under the bridge is known only at the measured points. Between them it is their mean, weighted by inverse distance
  (`_Ground`). It sets where the slab's sides and the piers stop. It is not a lower limit for the deck.
- An edge at most `LAND_GROUND_M` (0.5 m) above this ground is a landing, with no parapet. Without measured ground the limit is 0.05 m.
- The slab's bottom is at least `UNDER_M` (0.1 m) under its top.

A point in the air (an axis middle, or a node that is no ground end) with no deck-class points: its `ground_elev` is the deck's
elevation, not the ground. IGN classes some decks as ground (Boulevard du Larvotto: every point; Avenue de France: some junctions).

The dashboard's map is flat: its ground is z = 0 everywhere. `urbanstyle structure ... --above-ground` writes the dashboard's file
from its own solve in heights above the ground: road ends at 0, the measured clearances (`mid_m`, `deck_m`), the same smoothness and
grade limits. Nothing is subtracted after the solve: a ground subtracted from a solved deck bends it (the inverse-distance ground made
waves), and one plane per bridge loses the clearance (and fails where the road ends lie on one line). The limit of a flat map: a clearance
that the grade limit cannot reach from the road ends is not reached (Costa: 1.9 m, IGN 9.2 m; w572934026: 2.7 m, IGN 9.6 m). The
elevation viewer shows these bridges as they are.

No ground grid is used. A trial with a grid of IGN's ground points (2026-10-22) was removed: IGN classes some decks and walls as ground,
so the grid came up through the decks, and it needed three more rules to hide this.

Monaco, all ten bridges: the decks are within 0.5 m of IGN's points, except Avenue de France (junction n21927897 1.5 m above, a6 1.0 m,
a3 and a10 0.7 m). All checks pass but Boulevard du Larvotto's D8 jogs (as before). A profile with no `ground_elev` is built as before
(Granville: tests/test_bridge_step5.py).

## Sources

Every height that the file or the rule gives is marked `source: urbanstyle`, `method: chosen`, and `rule` tells which key gave it.
Measured heights (LiDAR) keep their own source. Do not mix the two in one axis.

## Limits

- The tool does not check heights against the ground. Set `max_m` so that the deck is clear of the roads under it.
- Where axes meet in the air, give them the same height at the node (use `from`). The 3D model blends small differences smoothly.
