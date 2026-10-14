# The street from SUMO

Status (2026-10-13): proposed. Kaveh agreed on the principle (rules 1 to 4). The inputs, the outputs and the open questions are for
review. No code is written yet.

## Why the rules change

At level 0, `division.py` makes the lanes, the shoulders and the sidewalks as strips parallel to the axis of each subsection. That axis
is the middle line between the two blocks, not the OSM road line. Thus:

- Where the two blocks are not at the same distance from the road, the axis bends, and the lanes bend with it. On Avenue Princesse
  Grace (OSM way 503633031) the lanes show a curve that the road does not have.
- The strips of two subsections do not meet at the joint between them. The checks R1 and R4 count these steps, and
  `division.join_lanes` with its tapers tries to close them.
- Each new fault got its own fix (for example, the run-on of the axis into a street's end), and the exceptions add up.

SUMO's `netconvert` makes lanes along the road line, at their real widths. Its lanes are continuous from one junction to the next. It
also makes junction shapes, sidewalks, crossings and walking areas. We already use it for the lane connections at level 0, and the
other levels used its roadway before (`space-parts.md`, "The roadway from SUMO").

## The rules

1. **SUMO makes all the geometry of the street:** lanes (driving, bus, cycle), sidewalks, junction areas, crossings, walking areas and
   the lane-to-lane connections.
2. **Nobody edits SUMO's output.** If a shape is wrong, change SUMO's input or a `netconvert` setting, and run `netconvert` again.
3. **Each input value has a source:** OSM, a city's data or a measurement. A value that no source gives is urbanstyle's own, with
   `method` = `chosen`, as everywhere in the model.
4. **We split SUMO's parts only at the cuts between the street spaces** (sections and intersections), so that each part belongs to one
   space. We do not change a part in any other way.

What stays ours: the blocks, the cut of the street into sections and intersections, the ground, and the ground between the outer edge
of SUMO's street and the block edge (the frontage).

## SUMO's input

duckOSM writes the network for `netconvert` (`duckosm.sumo.to_sumo`). The table gives each input, where it goes in SUMO's files, and its
source, strongest source first.

| Input | In SUMO | Source |
|---|---|---|
| road line | edge `shape` | duckOSM's driving edges (OSM) |
| lanes, each direction | edge `numLanes` | OSM `lanes`, `lanes:forward`, `lanes:backward` |
| lane width | lane `width` | OSM `width:lanes`; else OSM `width` over the lanes; else a city's data; else chosen by road class |
| lane use | lane `allow` | OSM `busway`, `bus:lanes`, `cycleway`, `bicycle:lanes` |
| lanes on the road line | edge `spreadType` | `roadCenter` for a two-way road, `center` for a one-way road: OSM draws a road along its middle |
| sidewalk | a lane at index 0 with `allow="pedestrian"`, at its width | OSM `sidewalk=*` on the road; or a separate footway along the road (`sidewalk=separate`, as in Monaco) |
| sidewalk width | that lane's `width` | OSM `sidewalk:width`, the footway's `width`; else measured from the separate footway; else chosen |
| crossing | `<crossing>` in the node file | OSM `footway=crossing` ways and `highway=crossing` nodes; no crossing that OSM does not map |
| one junction from close nodes | `<join nodes="..."/>` in the node file | our intersection: the nodes between the same block corners |
| junction outline | node `shape` | only where SUMO's own shape is wrong (open question 3) |
| corner radius | node `radius` | chosen |
| lane connections | the connection file, and duckOSM's turn rules | OSM `turn:lanes`, turn restrictions (duckOSM `edge_graph`, `turn_permission`) |

`netconvert` settings: `junctions.join`, `junctions.corner-detail`, `walkingareas` on, `crossings.guess` off (no source-less crossings),
`sidewalks.guess` off (sidewalks come only from the inputs above).

## SUMO's output in our tables

| SUMO | `space.part` type |
|---|---|
| a lane that lets cars through | `lane` |
| a bus lane, a bike lane | `bus lane`, `cycle lane` |
| a sidewalk lane | `sidewalk` |
| a crossing | `crosswalk` |
| a walking area | `pedestrian corner` |
| a junction shape, less its crossings and walking areas | `junction area` |

Each part has `source` = `sumo`, `method` = `derived`, and `ref` gives the inputs it came from (for example, `w8056051 lanes=2,
width:lanes`). The painted lines (lane lines, centre lines, stop lines) come from the edges of SUMO's lanes. A part of SUMO's street that
crosses a block edge is not cut: a check reports it, because it shows a wrong input (a lane or a sidewalk too wide) or a wrong block
edge.

## What this replaces

- In `division.py`: the strips along the subsection axis (lanes, shoulders, sidewalks, medians), `join_lanes`, the tapers, and the
  run-on of the axis (`follow_road`, `run_on`).
- The checks R1 and R4 (steps at the joints): SUMO's lanes have no joints between subsections.

The blocks, the sections, the intersections and the ground do not change.

## Open questions

1. **A separate footway far from the road.** In Monaco, a footway can lie 7 m from the road line. Is the ground between the kerb and the
   footway part of the sidewalk lane, or a verge (a lane with `disallow="all"`)? A test on Avenue Princesse Grace can decide.
2. **The footway as its own way.** When a separate footway becomes a road's sidewalk lane, it must not also stay a path of its own in
   SUMO's network, or the street has the sidewalk two times.
3. **Junction outlines.** Where SUMO's junction shape is wrong, the outline can come from our intersection (between the block
   corners). That is our geometry, given to SUMO as input. The first test shows if it is necessary.
4. **The ground between two carriageways.** Two one-way OSM ways (Avenue Princesse Grace) are two SUMO edges. The ground between them is a
   median, but SUMO does not make it. It stays ours, between the inner edges of SUMO's two roadways.
5. **Levels other than 0.** Bridges have their own model (`bridge3d.py`). These rules are for level 0 first.

## Order of work

1. Test the inputs and settings on Monaco: Avenue Princesse Grace (two carriageways, separate footways), Place Sainte-Dévote and
   Rond-Point de l'Hôpital (complex junctions). Look at the result on the dashboard with Kaveh.
2. Agree on the open questions.
3. Write the inputs in duckOSM (`to_sumo`) and the output in `division.py`. Remove the strips that SUMO replaces.
4. Run `urbanstyle check` on Monaco and Vancouver, and report the counts before and after.
