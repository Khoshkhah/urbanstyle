# The terrain page (2026-11-12)

Kaveh, 2026-11-12: "the tunnel box must show only in the terrain version", then "Yes, build it" (a terrain version of the Monaco
page). The flat page stays as it is, with no tunnel box.

## Why not the flat page on a terrain

A grid has one height at each point. Draped on Monaco's hills, a flat road shape takes the shape of the ground under it, and a grid
cannot hold a step between two roads, a bridge or a tunnel (duckOSM's ground standard, section 3; SimReady
`docs/7-plan/3d-map.md`). So the roadway in 3D is not urbanstyle's flat layers on the terrain.

## Who draws what (agreed with SimReady, 2026-11-12)

| Part | Drawn by | Source |
|---|---|---|
| the terrain | roadstyle (MapLibre terrain), page option `ground` | SimReady's conformed ground, resampled to a lon/lat grid by SimReady's adapter: `<area>.ground.json` beside its GLB |
| the roadway in 3D: lanes, junction areas, islands, kerbs, markings, bridge decks, tunnel boxes | roadstyle's `scene_3d` layer | SimReady's page tiles, `<area>.page.pmtiles` beside its GLB |
| the walking side, the ground kinds, the street objects | urbanstyle's layers, draped at level 0 | urbanstyle's build |
| the buildings | urbanstyle's own (the panel's cards); SimReady's tile part `buildings` off | OSM |
| the panel (find, cards, levels) | urbanstyle | urbanstyle's server |

On the terrain page urbanstyle's own 3D roadway layers, its deck models (`deck3d.py`) and its tunnel models (`tunnel3d.py`) are off:
nothing is drawn twice. The parts above level 0 that only urbanstyle has (sidewalks on a deck) are left out at first.

## The page

`urbanstyle dashboard DB OUT --terrain SIMREADY_GLTF_DIR`: the page with the options `view_3d`, `ground`, `terrain` and
`scene_3d`, the tiles linked beside the page. The engine keeps roadstyle's terrain on (on the flat page it turns it off).

## Open

- A click on SimReady's 3D roadway: its extras (lane_id, junction_id, carriageway_id) to urbanstyle's part ids, for the panel's card.
