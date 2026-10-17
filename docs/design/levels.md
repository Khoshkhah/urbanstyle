# Levels, bridges and tunnels

<p class="lead">The decks above the ground and the tubes below it, the links between levels, and the bridge model: one profile per
bridge with the source of every value, and a 3D model drawn from the profile alone.</p>

## The levels

A level is an integer floor of the area, -2 to 2, 0 the ground ([The model](model.md), "The levels"). Each level but 0 has its own
units: a deck or a tube, the roadway and a narrow walkway, with no blocks. The links between levels (`space.link`) are the only
joins between levels: a ramp, stairs, an elevator, an entrance, or a connection where a road's level changes at a node.

The page gives each level a button with three states: full, faded, hidden. In 3D a deck with no bridge model is drawn 6 m a level
above the ground; a tunnel is drawn under the ground of level 0 and shows where level 0 is faded or hidden.

## The bridge profile

One file per bridge, `<name>.bridge.json`, holds all that the 3D model needs. Scripts make the file; nobody edits it by hand. A
measurement is a script that replaces a value with its source and method.

The profile uses the words of road design:

- **Axis:** a reference line along the deck, one chain of OSM road ways on the deck between two branch points. A bridge with ramps
  has several axes. A position on the deck is `(s, t)`: `s` along the axis from its start, `t` across it, left positive.
- **Vertical profile:** the height of the deck top along the axis, as points `(s, z)`, linear between them.
- **Section:** a length of the axis where the cross-section does not change. A new section starts where the bands change.
- **Band:** one strip across a section: a lane with its id, direction, use and turn, at its offset `t` and its width.

| Value | Source |
|---|---|
| the deck outline | OSM's `man_made=bridge` outline; without one, the union of the sections, each as wide as its bands (derived) |
| the lanes | duckOSM's GMNS export, whose lanes come from SUMO, so the bridge and the street have the same lanes; the count is OSM's, mapped per direction, or derived by GMNS from the total, or chosen (one each way) |
| the offset `t` of a band | the GMNS lane line's offset from the axis at the middle of the section (derived) |
| a cycleway or footway band | a path within 25 m of the axis, parallel to it within 26°, nearer to this axis than to another |
| the heights | LiDAR where there is some; else a heights file; else the network rule below (chosen) |
| the deck thickness, the parapet, the piers | chosen: 1.8 m, 1.1 m, a pier every 50 m where the deck is 3 m or more above the ground, 1.5 m thick |
| a lane's end | where SUMO ends it at a junction; the profile's connectors hold SUMO's paths from lane to lane through a fork or a merge on the deck |
| the paths | every path on the deck, along its own OSM line |

Where OSM's bridge way ends in the air, the ramp continues on fill along the OSM road that continues it, to the next junction, 150 m
at most. The LiDAR measures the heights along it. Where the lanes' chosen widths reach over a path beside them, the lanes narrow to
the path's edge; the count does not change.

## Heights from LiDAR

At a station every 10 m along each axis:

1. The window is 10 m along the axis and as wide as the lane bands there. Vegetation, water and noise returns are left out.
2. Where gaps of 2 m or more split the heights, only the cluster with the most returns is kept: the deck seen from above.
3. The deck top is the 25 % quantile of that cluster, so the cars on the deck lie above it.
4. The ground is the median of the ground and water returns within 30 m.
5. The profile stores the deck top above one smooth reference ground for the whole bridge: the ground and water samples weighted
   over 60 m and pinned to the deck at each landing. A station with fewer than 20 returns keeps the chosen value.

The deck thickness and the piers stay chosen: from above, the survey does not see the deck's underside.

## Heights from a file

Where there is no LiDAR, a heights file sets the heights of each axis: a list of `[s, height]` points, rounded with a vertical curve at
each inside point; or a ramp that starts at the height of another axis and goes down at a grade to the ground; or the default rule
with its grade (5 %), its highest height (27 m) and its curve length (60 m). Every height from the file is `urbanstyle, chosen`, with
the key that gave it.

## Heights from the network rule

Without LiDAR and without a file, each deck height comes from one rule over all the bridge ways of the area as one network. A node is
on the ground where a road that is not on a bridge also uses it. For each point, D is the shortest distance along the network to a node
on the ground. The height is the smaller of 27 m and 5 % of D. At a node where branches meet in the air, every branch gets the same
height.

## The 3D model

The model reads only the profile. It draws the deck (the outline triangulated, each point at the height of the vertical profile of the
nearest axis, as thick as the profile says), the parapet along the outline, one ribbon per band at the deck's height, the painted lines
(an edge line at the outer edge of each run of lanes, lane lines between lanes of one direction, the centre line between the
directions), the arrows and the guide lines, and a wall across the deck at each pier down to the ground. The heights of two axes blend
only where they meet at a fork or lie side by side within 4.5 m at the same height. Near a landing the deck gets thinner and meets
the street flush; the sides of a landing on fill go down to the ground as walls. On a landing, the bridge lane takes the edges of the
street's lane under it.

The model is drawn on top of the flat map, through the map's projection, so it lies within 0.01 m of the street's lanes. A click on
a lane or a path opens its fields and the source and method of its count, its width and its height.

## Tunnels

A tunnel's lanes and the ground's lanes touch at the portal node, and a connection in `space.link` joins the levels there. In 3D the
tube is drawn at its depth, 6 m a level below the ground, a chosen value; over the last 30 m before a portal the tube rises to the
ground, so the tunnel lane meets the ground lane at the node in plan and in height. A ramp or stairs between two levels slope from the
height of their upper end to the height of their lower end; an elevator is a vertical shaft.

## Checks

| Check | Tests |
|---|---|
| BR1 to BR8 | the bridge model: no guard on a lane, no holes, no guard gaps, no path on a path, no slivers, no lanes of two axes overlapping, every lane with an arrow, no steps at landings |
| BR9 | every piece of the deck is covered by a part |
| BR10 | a lane meets a path only at a crosswalk or with a barrier between them |
| BR11 | no step in the deck's height |
| BR12 | no surveyed or mapped street object stands inside a lane near the ground |
| T1 to T3 | a tunnel lane and the ground lane touch at the portal in plan and in height; no tunnel lane rises above the ground before its portal |
