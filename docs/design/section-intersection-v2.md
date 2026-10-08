# Sections and intersections, version 2 (proposal)

Status: **built** (2026-10-04, with the changes noted in `street-space.md`; `plaza` kind and `space.strip` added, boundaries/C1 classification not built). Replaces the "own corridor + Voronoi + hull" method of `street-space.md`. Triggered by review of
`s0-5500360657416984491` (a section whose two ends are lumpy), `s0-2074815943689890030` (a slip-road blob) and
`s0-4052587228318142800` (an open plaza strip).

## Why the current method gives lumpy shapes

1. The edge of a container is wherever 3 m rays happened to stop. Where there is no building the edge is the **reach cap**, so it
   is a guess, and every ray ends a little differently.
2. An intersection is the hull of arm corner points, then **clipped to that ragged edge**; the section ends are whatever is left.
3. Where two corridors overlap, a **Voronoi diagram** of centerline points decides who owns what: its borders have no relation to
   how a street is built.

The rule behind all three: the *outline* of a container comes from measurements, so it inherits their noise.

## Principle

**Cut with straight lines, bound with what is real.** A container's outline is made of only two kinds of edge:

- a **real edge**: a building face (or, later, a wall or fence), taken as it is, and
- a **cut**: a straight line, perpendicular to a centerline, placed by a rule.

Where there is neither (open ground), the edge is an **edge-of-reach line**: one smooth offset curve of the centerline
(a buffer of `width/2 + margin`), never a ray-by-ray outline. No Voronoi diagram, no hull of corner points.

## Algorithm

Per level, in metric coordinates.

1. **Street space U.** Union of, for each road/walkway/cycleway element, its *offset corridor*: the centerline buffered by
   `reach(element)` (flat cap, as now `1.5*width+8`, at most 25 m), minus the buildings. A building-free side therefore ends in a
   smooth offset line, and a built-up side in the building face.
2. **Cuts at junctions.** For each junction cluster and each arm, one straight cut line across the arm, perpendicular to the
   arm's centerline at `d = half-width + setback` from the node, long enough to span U (extended until it leaves U).
3. **Intersection** = the part of U that contains the junction cluster and is bounded by the arms' cuts: `U` minus the half-spaces
   beyond each cut, keep the connected piece around the node. Its edges are building faces and straight cuts, so a T-junction is
   a clean T. A roundabout is the piece inside the cuts of its outer arms, island included.
4. **Sections** = what remains of U after removing every intersection, *per street chain*: the corridor of the chain's own
   elements (step 1 for that chain only), minus intersections. A section ends exactly on two straight cuts.
5. **Where two chains' corridors overlap** (parallel streets, a service lane next to a road) there is no Voronoi: the overlap
   goes to the chain whose centerline is **nearest by perpendicular distance along the ray that made it**, i.e. each ray stops at
   the **halfway point to the nearest other chain's centerline** (a ray-length rule, not a diagram). The border is then a smooth
   offset curve, parallel to both streets.
6. **Open areas** (plazas, slip-road gores, wide junction mouths) where nothing bounds the offset corridor: capped at `reach`, kept
   smooth. These are later given the `plaza` kind (planned) rather than stretched into a section.
7. **Boundary list** (`space.boundary`) is then read straight off the real edges of the outline: the building faces that are part of
   it, no tolerance needed.

## Why it is cleaner

- Outlines are made of straight cuts, building faces and offset curves: no ray jitter, no hull chord.
- The two ends of a section are perpendicular to the street, as in osm2streets, CityGML and the traffic-engineering definition
  (curb-return prolongations).
- Every edge has a reason that can be shown on the dashboard: *building face*, *cut at intersection X*, *halfway to street Y*,
  *edge of reach*.

## What is kept

Ids, kinds, `space.arm`, `space.street`, dual-carriageway merging, the along-rule for walkways, levels, the invariants P1–P7, S1,
S2, I1–I4. New check: **C1**, every edge segment of a container is classified (building face / cut / midway / reach) and the share
of `reach` edge per container is reported.

## Work

1. Offset corridors and building subtraction per element (no rays for the outline; rays remain only to measure width and kerb).
2. Cut lines per arm; intersection as the cut piece of U; roundabouts.
3. Sections as chain corridor minus intersections; the halfway rule for overlaps.
4. Remove Voronoi (`voronoi_owner`, `sp`, `vown`) and the hull code (`intersection_shapes`' hull step); keep `ishape` labels.
5. Re-run tests (rewrite the shape tests that name the hull), checks on both pilots, dashboards; update the glossary and spec.

## Decisions needed

1. Go ahead with this replacement (it rebuilds both pilots and changes every container outline)?
2. Open ground beyond the reach cap: keep a smooth offset edge now and add `plaza` later (proposed), or add `plaza` first?
