# Bridges in 3D

<p class="lead">A bridge drawn as a 3D model on the dashboard (three.js), from OSM, with the values that no source gives marked as our own.</p>

Status: built 2026-10-11 for the Granville Bridge (`urbanstyle dashboard DB OUT --bridge data/vancouver_city.osm.duckdb "Granville Bridge"`,
`bridge3d.py`). The model is drawn only; it is not stored in the space tables.

## From OSM (mapped)

- **The deck:** the outline of the bridge (`man_made=bridge` with the bridge's name), triangulated.
- **The roads on it:** every road with `bridge=*` that lies more than 60 % on the outline; their lanes from `lanes` (and
  `lanes:forward`); a lane line between lanes, an edge line at each side, the centre line between the two directions.
- **The paths on it:** cycleways and footways (the Granville Connector), as a ribbon.
- **The ends:** the nodes where a road on the bridge meets a road that is not a bridge. There the deck is at the ground.

## urbanstyle's own (chosen)

OSM gives no heights, no lane widths and no piers.

| value | | method |
|---|---|---|
| the deck rises from its ends at | 5 % | chosen |
| the deck is at most | 27 m above its ends | chosen |
| deck and girders | 1.8 m thick | chosen |
| parapet | 1.1 m | chosen |
| a pier | every 50 m along the longest road, where the deck is 3 m or more above the ground | chosen |
| a lane | 3.3 m wide | chosen |

LiDAR can measure the deck's height and the piers; then these values become `measured`.

## On the page

A three.js layer (MapLibre's custom layer) draws the model in metres from its origin; a box at the bottom right turns it on and off.
The OSM database must hold the whole bridge (the unit's own clip holds only its ramps).
