# Bridges in 3D

<p class="lead">A bridge drawn as a 3D model on the dashboard (three.js), from its bridge profile only.</p>

Status: built 2026-10-11 for the Granville Bridge; since the same day, the model reads a [bridge profile](bridge-profile.md)
(`urbanstyle dashboard DB OUT --bridge data/bridges/granville-bridge.bridge.json`, `bridge3d.py`). The model is drawn only. It is not
stored in the space tables.

## What the model draws

| part | from the profile |
|---|---|
| the deck | the outline, triangulated; each point at the height of the vertical profile of the nearest axis; as thick as `deck.thickness` |
| the parapet | along the outline, `deck.parapet` high |
| the lanes, cycleways and footways | one ribbon per band of each section, between `t - width / 2` and `t + width / 2`, at the deck's height |
| the painted lines | an edge line at the outer edge of each run of lanes, a lane line between two lanes in one direction, the centre line between the two directions |
| the piers | a wall across the deck at each pier, from the bottom of the deck down to the ground |

A click on a lane or path opens its fields: the OSM way, the GMNS link and lane, the direction, the use, the turn arrow, the width, and
the source and method of the lane count, the width and the height. The profile says which values are `chosen`. On the Granville
Bridge these are the heights, the lane widths (GMNS's width for the road class), the deck thickness, the parapet and the piers. LiDAR
can measure the heights and the piers. Then these values become `measured`.

## On the page

A three.js layer (MapLibre's custom layer) draws the model in metres from its origin, the first point of the outline. A box at the
bottom right turns it on and off. A custom layer is not in `map.getStyle()`. To find it in a test, use `map.getLayer('br3d-<name>')`.
