# Junctions from the road network

Status: agreed with Kaveh on 2026-10-14. Step 1 (this note): the junction's place and shape. Step 2 (later): the sections along each
road between junctions.

## Problem

A junction (an intersection space, `i0-...`) was "the street left over" after the division found sections between blocks that face
each other. It was not anchored on the road network. This works for a street grid (Vancouver), but not in general (Monaco):

- A junction can be much too long. `i0-1079750403` was 100 m long and took the sections on both sides of a small roundabout.
- A junction can be where no roads meet. `i0-x373563y4844515` was a 742 m² rectangle under a bridge, where two roads only continue
  through. Its id is a position because no junction node is in it.
- Its shape follows the blocks, not the roads.

## Rules

1. **Where.** A junction is only at an OSM node where 3 or more road ends meet (a road that runs through the node counts 2), or on a
   roundabout ring. Roads that share no node do not make a junction, also when they touch. And not every such node is a junction
   (2026-10-15): the road ends are paired into streams (an end continues into the end most opposite to it, within 45°); the node is a
   junction only where an end has no continuation (a road ends there: a T) or two streams cross each other (their ends alternate round
   the node). Where the streams only touch, as a ramp that joins a road or two one-way lines of one street drawn into one node, the
   roads run through the node as one section, with the lane transition of `pipeline.md` step 6. At a Y (two roads merging into one,
   the Granville ramp into Fir Street) two streams share the end they continue into: no junction, the merging road's lanes join the
   other's side by side, and a lane that opens at the joint never lies over the merging road's band.
7. **Arm bands inside the junction.** Each arm's roadway is the band of its own line from the node to its stop line, cut square there.
   A curved arm leaves a curved junction edge (the slip lane w48524371 at the Granville ramp, 2026-10-15): open, to be decided.
2. **Core.** The area where the carriageways of its arms overlap. An arm is a road line from the node, as wide as OSM's `width`, else
   its lanes × 3.25 m (chosen).
3. **Reach.** Each arm reaches from the core to its stop line: the far edge of a crosswalk that OSM maps across the arm within 15 m
   of the core, else 3 m past the core (`JUNC_ARM_M`, chosen). The core and the reach are stations along the arm's own line, and the
   arm is cut square across its line at the reach. Before 2026-10-15 the arm was cut by a circle round the node, so every junction
   had the radius of its widest road: at Broadway a side street's lanes stopped half a road width before Broadway's kerb line, the
   corners stood on the circle, and the crosswalk across Broadway fell outside the junction. Check J2 fails on such a shape.
4. **Corners.** Between two neighbouring arms the edge is rounded by 4 m (`KERB_RADIUS_M`, chosen).
5. **Divided roads.** Each carriageway is its own road line. A side road that joins one carriageway makes a junction with that
   carriageway only. The median and the other carriageway are not in it, because they are not arms at that node.
6. **The rest.** The street that the old method gave to a junction and that the new shape leaves goes to the section whose road runs
   through it, else to the section it shares the longest edge with. A piece that touches no section stays in the junction.

Junctions whose shapes overlap are one junction (a complex junction with several nodes).

## Checks

- J1: every junction holds a junction node.
- J2: no junction area has a piece over 5 m² outside its arms' bands (`street-rules.md`).
- A3: every road line at level 0 lies on a lane, a junction area or a crosswalk.

## Where in the code

`src/urbanstyle/network.py` (step 5 of `pipeline.md`), which replaces the old division (2026-10-14).

## Step 2: sections along each road

Done in `network.py` (2026-10-14). Each section runs along its own road between junctions, so two roads that share no node are two
sections, also where they lie close together (Ruelle Saint-Jean beside Boulevard du Larvotto); their lanes do not meet.
