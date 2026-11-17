# The line between SimReady and urbanstyle

Decision, 2026-11-17 (Kaveh). This note gives the job of each project, the line between SimReady and urbanstyle, and what
urbanstyle is for at this time. It replaces the scope in `simready-input.md` ("What urbanstyle keeps") and the order of work in
`docs/plan.md` before this date.

## The decision

1. SimReady makes the street: all its geometry, for every mode, on every level. urbanstyle starts after SimReady and reads the
   street from it.
2. At this time, urbanstyle has one goal: to make SimReady better. The street code of urbanstyle is the comparison for SimReady.
3. urbanstyle's own job is the city round the street, and the one model and format of both. That job starts again when SimReady's
   street is stable.

Kaveh's words: "at the moment urbanstyle has many part that must be in simready and I only keep it in that way [so that I] can
compare both result together and improve result of simready"; "whole process for drawing street and roads and find a good geometry
for them is in simready. and urbanstyle starts after that"; "at the moment the only goal of [urbanstyle] is helping to simready to
make it better".

## One job for each project

| Project | Job |
|---|---|
| duckOSM | the facts from OSM: the networks, the buildings, the land use, the ground (one DTM for each area), the tiles |
| SimReady | the street: where people and vehicles move |
| urbanstyle | the city round the street: where things are. Also the one model of both, with its ids, checks and format |
| roadstyle | the drawing: the map, the 3D scene, the terrain, the parts of the dashboard |

Data goes in one direction: duckOSM, then SimReady, then urbanstyle. roadstyle draws the results of all three. SimReady does not
read urbanstyle (SimReady's decisions D28 and D37).

## The line is the street's edge

The street is the space between the blocks. Its edge at level 0 is the block side. Above and below level 0, its edge is the edge of
SimReady's street face.

| Inside the street: SimReady | Outside the street: urbanstyle |
|---|---|
| lanes, also the parking, bus and cycle lanes on the carriageway | blocks: plots, buildings and the use of each building |
| junction areas, stop lines, turns, signals | ground kinds and surfaces inside the blocks |
| islands and medians | street objects (lamps, trees, signs, bus stops), matched across the sources |
| sidewalks, crosswalks, cycle tracks, driveways across a sidewalk | the model `urban`: ranks, ids, the source of each value, the checks |
| bridges, tunnels, heights, the conformed ground | the format (the CityGML profile as a CityJSON Extension) |
| the street face on every level | the panel (Find, Filter, Ask) |

An earlier line was the roadway bound (`sim.kerb_line`, role `bound`), with the walking side in urbanstyle. That line does not
hold. SimReady's simulators also move pedestrians and bikes, and SimReady cannot get the sidewalks from urbanstyle. SimReady
already makes the blocks and the street face (its step `street-space`), so it has the two sides of the walking side.

Two agreements of 2026-11-12 (`rules-review-2026-11-12.md`, section 7) change with this line. The street's edge at level 0 and
the walking side were urbanstyle's results. They are now SimReady's to make, and urbanstyle's results are the comparison.

## What urbanstyle does at this time

1. Compare the two results place by place, in the browser ("How the two results are compared").
2. Keep the reader of SimReady's output in a state that works (`simready.py`, `sr_blocks.py`, the crate `urbanstyle-simready`), so
   that the comparison page shows the newest SimReady build.

A fault in a street shape (a lane, a junction, a sidewalk, a crosswalk, a deck, a tunnel) is a finding for SimReady. Do not
correct it in urbanstyle.

## How the two results are compared

Kaveh, 2026-11-17: "both access to browser and they can see their result and compare them and give the best decision for updating
simready rules".

1. Each project shows its result of the same place in the browser, with the same `?at=` link.
2. The SimReady session and the urbanstyle session open the pages in the headless browser. Kaveh opens them in Chrome.
3. For each difference, the two sessions say which result is better, with the evidence: the aerial photo, OSM or a measured value.
4. SimReady records the decision by its own rules: a row in `rules/*.csv` with the source `urbanstyle` and a status (`adopted`,
   `candidate` or `rejected`). urbanstyle does not change its street code.

Two limits:

- No page shows the two results together as layers. There are two pages: urbanstyle's dashboard and SimReady's review page
  (port 8801).
- The headless browser is very slow at street zoom (`AGENTS.md`, "Things that bite"). A session compares layer counts and
  pictures in `viz/review/`, not screenshots at high zoom.

## The comparison code

These modules make street geometry. They stay in the repository as the comparison and get no new rule:

- the roadway: `network.py`, `subsections.py`, `spaces.py`, `parts.py`, `sumo.py`, `turns.py`, `division.py`;
- the bridges and the tunnels: the `bridge_*.py` modules, `bridge2d.py`, `bridge3d.py`, `deck3d.py`, `tunnel3d.py`, `faces.py`;
- the walking side of the SimReady build: the rule of 2026-11-12 in `simready.py`.

A change there is permitted only when the comparison does not run without it. A comparison part is deleted when SimReady's result
is better at that part.

The list is from the module names. It is not checked against what the SimReady build imports (for example the elements and their
levels in `container.py`). Make that check before a module is deleted.

## What stops

- New street rules, and corrections to street shapes, in urbanstyle.
- The bridge and tunnel models (Granville, Monaco). Their open items become findings for SimReady.
- The open items on the roadway of `docs/HANDOFF.md` (W2, the junction mouths, the Granville landing).
- The format, the second city and the Rust port of new steps. They wait for a stable street from SimReady.

## When urbanstyle's own job starts again

It starts when SimReady's street is stable and has the sidewalks and the crosswalks. Then urbanstyle adds the blocks, the
buildings, the objects, the model and the format on that street, in Rust for the browser (`rust-browser.md`).

## Open points

- **The walking side is SimReady's (Kaveh accepted, 2026-11-17), but SimReady's docs do not say it yet.** The decision:
  "SimReady makes the walking side of the street (sidewalks, crosswalks, cycle tracks, driveways) as shapes with their sources.
  urbanstyle's walking side is the comparison." SimReady's D28 says only that SimReady builds its own street space and that
  urbanstyle is a comparison. Its open item `P7.gltf-sidewalks` gives the sidewalk as the street face less the roadway. The
  SimReady session records the decision in `../simready/docs/decisions.md` and puts the work in its plan.
- **Paths that are not along a street** (through a park, a square, stairs). A pedestrian simulation needs them. Proposal:
  urbanstyle keeps them at this time, and SimReady takes them later. Not decided.
- **The design chapters** (`docs/design/`) give the street as urbanstyle's own result. They change when a part of SimReady's
  street replaces urbanstyle's part.
