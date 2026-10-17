# Tunnels in 3D

Status: proposed 2026-10-16, to agree before coding. The data is right; the 3D drawing is not.

## The fault

On the page a tunnel's lane ends as a dead end at its portal, and the ground lane that continues it ends there too (Kaveh,
2026-10-16, Tunnel Serravalle at Avenue du Port: `s-1-3223049329744887236/1#1` and `s0-w93091317/1#1`; every portal looks the
same). In the data the two lanes touch at the portal node, gap 0.0 m, and a `connection` link in `space.link` joins the levels
there. The 3D view draws every level below 0 flat under level 0's ground, at the ground's height: MapLibre draws no surface below
height 0 (`fill-extrusion-base` is 0 at least). So a tunnel lane lies on the ground lane's plane, its tube's walls stand at the
portal, and nothing descends.

## The model

One model per tunnel, drawn like a bridge's (`bridges-3d.md`, `bridge3d.py`): a three.js custom layer, which can draw below 0.

- **The tube.** The tunnel's lanes and its narrow walkways (`space.part` at the level, the tube of `space-parts.md`) at the level's
  depth: `DECK_M` (6 m) a level below the ground, the value the decks use above it. A chosen value, named as such; no source gives
  a tunnel's depth.
- **The portal ramp.** Over the last `RAMP_M` (30 m) before a portal node the tube rises to the ground, a straight slope, so the
  tunnel lane meets the ground lane at the node in plan and in height. The same at a portal into a deck above the ground.
- **The walls.** The tube's sides, from its floor to the ground, where the ground over it is street or plot; at the portal the
  cut's walls as kerbs (the Larvotto cuts, `known_osm_issues` 10, show that this is the ground's own shape too).
- **On the page.** The model is under the ground's parts. It shows where level 0 is faded or hidden, as the flat tunnels do now; the
  levels' buttons keep their meaning. The hover, the pick and the card work as for a bridge's parts (`brPick`, `brMark`).
- **Checks.** T1: a tunnel lane and the ground lane at its portal touch in plan (0.1 m). T2: their heights at the node are the same
  (0.1 m). T3: no tunnel lane rises above the ground before its portal.

## The links between levels

A link (`space.link`: a ramp, stairs, an elevator, a connection) is drawn as a buffered line at the height of its upper level, so a
car park's ramp from level 1 down to level -7 lies flat in the air beside the short bridge over its mouth (Kaveh, 2026-10-16). In
the model a ramp or stairs slope from the height of their upper end to the height of their lower end, 6 m a level, both clamped to
the levels the model keeps, and pass under the deck above them; an elevator is a vertical shaft; a connection has no shape. The
same slope as the portal ramp, in the same code.

## What is not in it

A tunnel's real depth and profile: no source we read gives it (LiDAR sees the ground, not the tube). The value is a choice until a
city's data gives it. A road sinking to a portal in an open cut (Boulevard du Larvotto) is the same ramp on the ground's own ways:
it needs the vertical profile of a level-0 way, which comes with this model.

## Order of work

1. This note agreed. 2. `tunnel3d.py`: the model from `space.part` and `space.link` (no profile file: a tunnel has no measured deck).
3. The page: the custom layer, the levels' buttons, hover and pick. 4. The checks T1-T3. 5. Monaco rebuilt and looked at, portal by
portal, with Kaveh.
