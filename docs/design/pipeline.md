# How the street map is made

Status: agreed with Kaveh on 2026-10-14. This is the order of the steps, data first. The rules behind each step are in
`street-rules.md`. The junction rules are in `junctions.md`.

The main change from the old order: the kerb is a result, not an input. Before, the division guessed the kerb first (from sidewalk
lines, catch basins, the road class or the block edge) and then fitted the lanes into it. A wrong kerb then moved the lanes off the
OSM line, added parking or shoulders to fill the space, broke the lane joints and gave junctions a bad shape.

## The steps

1. **Blocks.** The land between the streets.
    - The street roads at level 0 make the faces. Paths and pedestrian streets do not make faces.
    - Each block edge follows the footway, 1 m behind it, simplified by 0.5 m so that it is straight where the footway is straight
      and bends only where the footway bends. It never bends with the road where the road bends away from the footway. Where no
      footway is, the edge follows the parcels, else the carriageway plus 1.5 m.
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
    - out to each arm's stop line: the far edge of a crosswalk that OSM maps across the arm within 15 m, else 3 m past the core; the
      arm is cut square across its own line there, never by a circle round the node;
    - corners rounded by 4 m (chosen).
    - Junctions that overlap are one junction.
6. **Sections.** Each road from the edge of one junction to the edge of the next: the OSM ways chained where two of them meet at a node
   that is no junction (OSM splits a road at a crossing node or where its lanes change). The section is named by its longest way
   (`s0-w<way>[.n]`). It is cut into subsections (`/1`, `/2`, ...) where its cross-section changes; ways with one cross-section are one
   subsection. At the joint the two roadways are cut on the bisector of their directions.
    - **Continuity.** The lanes that run on through a joint keep their position. The kerb on the side where no road merges
      continues straight; where the width is the same on both sides, both kerbs continue and only the centre line moves (a turn
      pocket). Where OSM's line of the next way is not the centre of its lanes by up to 2 m (the line's drawing error), the whole
      subsection's line is moved sideways by that much, so its lanes, kerbs and lines continue the previous subsection's. The fixed
      piece of a section is the one at a bridge landing (the bridge's lanes and the ground's meet there), else the first; the shifts
      run away from it to both ends. A lane on the side a road merges from is that road's lane running on: it has no taper.
    - **Transition.** A larger step, or a width change with no merging road, slides over 15 m (chosen) in the subsection with fewer
      lanes: a lane the neighbour has not opens from the kerb, a lane this subsection has not narrows to nothing; the parking lanes
      follow the lanes' outer edge; a step between the two kerbs that is left is a carriageway taper. Never a kerb across a lane.
    - A subsection whose roadway outside the junctions is under 20 m² (a sliver between a junction and a crossing node) joins the
      junction it touches.
7. **Pedestrian side.** From each kerb out to the block edge: the furnishing zone, the sidewalk (on OSM's sidewalk line) and the
   frontage. A junction's corners take the sidewalks of their two arms.
    - A strip between two roadways that is narrower than 8 m and touches a block by less than 2 m (a corner touch is no contact: the
      gore where a slip lane leaves a junction) is paved roadway with no lane (part `carriageway`). It is an island only where OSM maps a
      kerb, an object (a tree, a sign, a pole) or a path along it, or where a barrier runs along it (rule 12 of `street-rules.md`).
    - A piece that touches no block and is smaller than 4 m² is not an island. It is part of the sidewalk.
8. **Crosswalks, lines and arrows.**
    - A crosswalk part for every crossing way over the roadway, 3 m wide (chosen) or OSM's `width`, and for every crossing node on a
      road that no crossing way maps: a band across that road's carriageway. The lanes and the junction area give way to it.
    - Its paint from `crossing:markings`: zebra bars (also for `zebra`, `marked`, `uncontrolled` and `yes`), two crossing lines
      (`lines`, `dashes`, `dots`; `ladder` gets both), none for `unmarked` or `no`, and none where no markings are mapped.
    - Lane lines only between lanes OSM counts (`lanes`), with the count's source. The centre line between the two directions also
      where the count is chosen, as urbanstyle's own (source `urbanstyle`, method `chosen`). Stop lines 1 m before the junction. Turn
      arrows from SUMO's moves.
9. **Bridges and tunnels.**
    - A bridge model comes from its profile. Its heights come from LiDAR, else from the network rule (`bridge-profile.md`, "Heights
      with no measurement").
    - The bridge lanes meet the ground lanes at their ends.
10. **Checks.** One check for each agreed rule (`street-rules.md`):
    - A1: lanes on their OSM line;
    - A2: no parking or bike lane without a source;
    - A3: every road line on a roadway;
    - J1: every junction on a real junction node; J2: no junction reaching outside its arms;
    - X1: every crossing way over the roadway has its crosswalk; M1: no line where the lane count is chosen;
    - K1: kerb evidence (the city's catch basins) is only compared with the result and reported. It never moves anything.
11. **Ground and dashboard.** The ground layers, then the dashboard page.

## What changes in the code

Steps 2 to 7 are new code. Today `division.py` makes them from the blocks. Steps 1 and 8 to 11 stay, with today's fixes.

The new code is tested on small cuts (250 m round each reported place, about 15 s each) and on both pilots before it replaces the old
division. Every reported place is shown before and after on the review page.
