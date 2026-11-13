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
| the ground over the tunnel | duckOSM's `elevation_grid` of the same ground id (SimReady's pass-0 folder), as `bridge_profile._ground_z` reads it |

The map has no terrain: the ground of level 0 is flat at 0 m. So each height of the box is drawn relative to the ground over it:
drawn z = z - ground z. A roof under the ground is drawn below 0; a roof over the ground stands up.

## How it is drawn

The box is a model in the same format as the decks (`deck3d.py`, `bridge3d.model`), drawn by the page's three.js layer, which can
draw below 0. The walls run along the face's ring less its `face_end` lines; the roof covers the face.

## Checks

- every tunnel face has a box, and every box has walls along the whole ring but its `face_end` lines;
- no roof is lower than the road under it plus 2 m.

## Open

- SimReady's own model (its GLB, part `tunnels`) draws a shell only where the ground covers the roof. If the GLB must follow this
  rule too, that is SimReady's change.
