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
   roundabout ring. Roads that share no node do not make a junction, also when they touch.
2. **Core.** The area where the carriageways of its arms overlap. An arm is a road line from the node, as wide as OSM's `width`, else
   its lanes × 3.25 m (chosen).
3. **Reach.** Each arm reaches from the core to its stop line: the far edge of a crosswalk that OSM maps across the arm within 15 m
   of the core, else 3 m past the core (`JUNC_ARM_M`, chosen).
4. **Corners.** Between two neighbouring arms the edge is rounded by 4 m (`KERB_RADIUS_M`, chosen).
5. **Divided roads.** Each carriageway is its own road line. A side road that joins one carriageway makes a junction with that
   carriageway only. The median and the other carriageway are not in it, because they are not arms at that node.
6. **The rest.** The street that the old method gave to a junction and that the new shape leaves goes to the section whose road runs
   through it, else to the section it shares the longest edge with. A piece that touches no section stays in the junction.

Junctions whose shapes overlap are one junction (a complex junction with several nodes).

## Checks

- J1: every junction holds a junction node.
- J2: no junction reaches beyond its arms' stop lines.
- J3: every road line at level 0 lies on a lane or a junction area.

## Where in the code

`src/urbanstyle/network.py` (step 5 of `pipeline.md`), which replaces the old division (2026-10-14).

## Step 2: sections along each road

Done in `network.py` (2026-10-14). Each section runs along its own road between junctions, so two roads that share no node are two
sections, also where they lie close together (Ruelle Saint-Jean beside Boulevard du Larvotto); their lanes do not meet.
