# How the street map is made

Status: agreed with Kaveh on 2026-10-14. This is the order of the steps, data first. The rules behind each step are in
`street-rules.md`. The junction rules are in `junctions.md`.

The main change from the old order: the kerb is a result, not an input. Before, the division guessed the kerb first (from sidewalk
lines, catch basins, the road class or the block edge) and then fitted the lanes into it. A wrong kerb then moved the lanes off the
OSM line, added parking or shoulders to fill the space, broke the lane joints and gave junctions a bad shape.

## The steps

1. **Blocks.** The land between the streets.
    - The street roads at level 0 make the faces. Paths and pedestrian streets do not make faces.
    - Each block edge follows the footways piece by piece, 1 m behind each footway. Where no footway is, the edge follows the
      parcels, else half the road class's width.
    - Corners are sharp. A block never covers a carriageway.
2. **Road network.**
    - The street roads at level 0 from OSM. The ways of a bridge that has a profile go to the bridge model.
    - Each road is split at its junction nodes: nodes where 3 or more road ends meet (a road that runs through the node counts 2).
    - Two roads connect only at a node that they share in OSM.
3. **Carriageways.**
    - The lanes come from OSM `lanes`. A two-way road with no `lanes` tag gets one lane in each direction.
    - The lanes are centred on the road's own OSM line. Each lane is 3.25 m wide (chosen), or the road is as wide as OSM `width`.
    - Parking, bike and bus lanes are added beside the lanes only where OSM or a city says so.
4. **Kerbs.** The outer edge of step 3, on each side. The kerb is never guessed.
5. **Junctions.** At each junction node:
    - the area where the arms' carriageways overlap (the core);
    - out to each arm's stop line: the far edge of a crosswalk that OSM maps across the arm within 15 m, else 3 m past the core;
    - corners rounded by 4 m (chosen).
    - Junctions that overlap are one junction.
6. **Sections.** Each road from the edge of one junction to the edge of the next. A section is cut into subsections where its lanes
   change.
7. **Pedestrian side.** From each kerb out to the block edge: the furnishing zone, the sidewalk (on OSM's sidewalk line) and the
   frontage. A junction's corners take the sidewalks of their two arms.
8. **Crosswalks, lines and arrows.** Crosswalks from OSM's crossings; lane lines, centre lines and stop lines; turn arrows from
   SUMO's moves.
9. **Bridges and tunnels.**
    - A bridge model comes from its profile. Its heights come from LiDAR, else from the network rule (`bridge-profile.md`, "Heights
      with no measurement").
    - The bridge lanes meet the ground lanes at their ends.
10. **Checks.** One check for each agreed rule (`street-rules.md`):
    - A1: lanes on their OSM line;
    - A2: no parking or bike lane without a source;
    - A3: every road line on a roadway;
    - J1: every junction on a real junction node.
    - Kerb evidence (catch basins, poles, sidewalk lines) is only compared with the result. It never moves anything.
11. **Ground and dashboard.** The ground layers, then the dashboard page.

## What changes in the code

Steps 2 to 7 are new code. Today `division.py` makes them from the blocks. Steps 1 and 8 to 11 stay, with today's fixes.

The new code is tested on small cuts (250 m round each reported place, about 15 s each) and on both pilots before it replaces the old
division. Every reported place is shown before and after on the review page.
