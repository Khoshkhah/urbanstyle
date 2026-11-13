# Tunnel walls and roof (2026-11-12)

Kaveh, 2026-11-12: "you can always have walls and roof for tunnels. If there is a hill there, wall and roof will go to the hill and
underground. If there is no hill, they stand on the ground." Before this note, a tunnel in 3D was only its flat roadway under the
ground of level 0, with no walls and no roof.

## The rule

Every tunnel gets walls and a roof. The ground decides what shows:

- the part of the box that is under the ground is drawn only when level 0 is faded or hidden;
- the part of the box over the ground always shows.

A terrain added later changes nothing in this rule. The box then goes into the hill.

## The sources

| Value | Source |
|---|---|
| the tunnel's outline | SimReady's face of the tunnel's level (`work.face`), cut to the final roadway |
| the portals (open, no wall) | SimReady's `face_end` lines on that face (`work.face_end`) |
| the road's height | SimReady's `sim.elevation_profile.z_m` of the carriageway, at the station of the point on its reference line, linear between stations |
| the roof's height | the road's height plus the span's `clearance_m` (OSM `maxheight`: 32 of 157 tunnel spans in Monaco); else SimReady's criterion `tunnel_clearance_default_m`, 4.5 m |
| the ground over the tunnel | SimReady's conformed ground: the 2 m grid beside its GLB (`gltf/*.ground.asc`, the project CRS and datum, the same ground id), bilinear between grid points. Under a tunnel it is the DEM (FABDEM, 30 m); under level-0 roadway it is the road. With no such grid, no tunnel box |

The map has no terrain: the ground of level 0 is flat at 0 m. So each height of the box is drawn relative to the ground over it:
drawn z = z - ground z. A roof under the ground is drawn below 0; a roof over the ground stands up.

## How it is drawn

The box is a model in the same format as the decks (`deck3d.py`, `bridge3d.model`), drawn by the page's three.js layer, which can
draw below 0. The walls run along the face's ring less its `face_end` lines; the roof covers the face.

## Checks

- every tunnel face has a box, and every box has walls along the whole ring but its `face_end` lines;
- no roof is lower than the road under it plus 2 m.

## Result on Monaco (2026-11-12)

On a cut at Avenue de Fontvieille, 11% of the tunnel road pieces lie 0.5 m or more over the conformed ground, so their roof stands
up as blocks near the portals: FABDEM smooths Monaco's slopes. A few single points lie up to 22 m over it, where the conformed
ground has narrow pits (sent to SimReady). Kaveh, 2026-11-12: "Show it as it is." A better ground needs a better source (a LiDAR DTM).

## Open

- SimReady's own model (its GLB, part `tunnels`) follows the same rule (SimReady e2a99c1); its "covered" test moves to the
  conformed ground too.
