# Street space specification: sections and intersections

This is the **normative definition** of a section and an intersection, the rules that relate them, the invariants every build must
satisfy, and the plan for closing the gaps. `street-space.md` records how the current code works and what was measured;
`partitioning-research.md` records how the standards do it; `glossary.md` has the words. Where the code and this document differ, this
document is the target and the difference is listed in section 9.

Words in **bold** are defined in `glossary.md`. Notation: `L` is a level; `U(L)` is the **street space** of level `L`.

## 1. What is being defined

`U(L)` is the union of the free space around every movement element at level `L` (roads, walkways, cycleways, rail), measured out to
the first obstacle (building face, later wall or fence) or to the reach cap. A **container** is a piece of `U(L)`. This document
fixes which pieces exist, what each one is, and how pieces relate.

## 2. The partition axioms

Every build must satisfy all of these, for every level.

| id | axiom |
|---|---|
| P1 | **Disjoint.** No two containers of a level overlap (shared boundaries only). |
| P2 | **Exhaustive.** The containers together cover `U(L)`; nothing of `U(L)` is outside a container. |
| P3 | **Valid.** Every container is a valid, non-empty polygon of at least 1 m². |
| P4 | **Connected.** A container is **one connected polygon**, never a multi-part one. A region that falls into separate parts becomes separate containers. |
| P5 | **Owned elements.** Every element (road, walkway, cycleway, rail) points to exactly one container that exists, and lies in or touches it. |
| P6 | **One kind.** Every container has exactly one `kind`: `section`, `intersection`, `path`, `rail` (and `plaza`, planned). |
| P7 | **Stable ids.** An id is derived from OSM ids only, so a rebuild of the same data gives the same ids. |

## 3. Section

**What it is.** The stretch of one street between two **intersections** (or between an intersection and a dead end, or the whole
of an isolated road). The CityGML `Section` / IFC `ROADSEGMENT`.

**Topological definition (the graph).** Take the road edges of one level. A **street** is a set of road edges that share a *name*
and are connected through shared nodes (an unnamed road is its own street per OSM way). A **junction node** is a node where three
or more road edges of the level meet. Remove the junction nodes: the edges of a street that remain connected form its
**sections**. Hence a section is a chain of road edges, possibly with both carriageways of a dual road (they connect at the
chain's ends), whose inner nodes all have exactly two road edges. A section ends at a junction node (an intersection), at a node
of degree one (a **dead end**), or at the data boundary.

**Contents.** The roads of the chain, and every walkway or cycleway that **runs along** them: its nearest road piece is in the
section and at least 60% of its length lies within 15 m of that piece. Nothing else.

**Geometric definition (the area).** A section is **its own measured corridor** minus the intersections:

```
corridor(c)      = ribbon along the elements of c: the measured building face where a side is bounded (>= 50% of samples hit),
                   else a smooth line at the reach cap; rays stop halfway to a parallel street's centerline
section area(c)  = corridor(c) − all intersections of L, then closed and opened by 2 m
```

So a wide corridor is not cut at an arbitrary midline between neighbours: the halfway rule applies only where two streets run parallel. Every point of `U(L)` is in some corridor, so the sections, intersections and path spaces still cover
`U(L)` without overlap. A section area that falls into several parts becomes one container per part (P4); a part with no road
assigned to it is a path space.

**Boundaries.** The edge of a container is made of pieces, and each piece is one of:

| piece | meaning | stored |
|---|---|---|
| **building** | a building face runs along the edge (within 1 m), at least 2 m of it | `space.boundary(container_id, level, kind='building', building_id, length_m)`, and `n_buildings`, `boundary_m` on the container |
| wall, fence, hedge | the same for barrier ways | planned (`street-objects.md`, step 2) |
| open | the reach cap ended the measurement: no obstacle was found | the rest of the edge; `open_share` says how much |
| neighbour | the edge is shared with another container (an arm cut, a cell border) | implicit: adjacent containers |

The dashboard's focus view shows the bounding buildings of the focused container and says how many there are.

**Identity.** `s<level>-<smallest edge id>` where the edge id is duckOSM's `edge_id` of the chain's edges. It carries `street_id`
(`k<level>-<smallest OSM way id>`), the group it belongs to.

**Attributes (stored).** `name`, `street_id`, counts of roads / walkways / cycleways, `mean_width_m`, `narrow_half_m`,
`wide_half_m`, `open_share`, `one_side_open_share`, `kerb_share`, area, its two zones.

**Cases.**

| case | rule |
|---|---|
| dual carriageway (two one-way ways of the same name, joined at both ends) | one section; both carriageways are in it |
| two streets that merely run side by side | two sections (different names or not connected) |
| a street that changes name at a node of degree two | two streets, hence two sections (the name decides) |
| an isolated road (no junction, no neighbour) | one section with no intersection |
| a footpath that leaves the street (less than 60% along it) | not in the section: a **path space** |
| a mid-block pedestrian crossing | an *object* (`crossing.*`) in the section, **not** an intersection |
| bridge or tunnel over or under another street | a different level: a different `U(L)`; a **link** where they connect, never an intersection |

## 4. Intersection

**What it is.** The area where two or more streets meet at grade. The CityGML `Intersection` / IFC `INTERSECTION`, and the
**physical intersection area** of traffic engineering: bounded by the prolongation of the curb lines (the *curb returns*) and, where
crossings are marked, by the far side of the crosswalk. It is **separate** from every street and **shared** by all the streets that
meet there; it is not a subsection of any one of them.

**Topological definition.** A **junction node** is a node with three or more road edges of the level. Junction nodes closer than
15 m to each other form one **cluster**, because a dog-leg, the ring of a roundabout and the two ends of a short link are one
junction to a driver. One cluster is one intersection. A node with two road edges is not a junction (the street continues); a node
where only walkways or cycleways meet is not a junction (it is part of a path space or of a section).

**Geometric definition (the area).**

```
arm cut(a)    = straight line across arm a, at (half the measured width of the widest OTHER arm + 1 m) from the node
intersection  = free space of U(L) between all arm cuts (each extended as a half-plane), bounded by building faces
                (hull of the cluster and arm corners only as a fallback); a cluster is at most 30 m across
```

**Boundaries.** Each arm is cut off from the intersection by the **arm cut**: the boundary of the intersection across the arriving
road, a straight line perpendicular to the road's centerline (osm2streets' perpendicular cut).

**Identity.** `i<level>-<smallest OSM node id of the cluster>` (a negative virtual node only if the cluster has no real node).

**Relations.** `space.arm(intersection_id, section_id, street_id, osm_id, node_id, level)`: one row per arriving road edge. An
intersection has at least three arms and is in the group of every street that arrives at it.

**Attributes (stored).** name (the arriving street names, up to three), number of roads meeting, area, zones, the objects inside
(signals, crossings, lamps).

**Cases.**

| case | rule |
|---|---|
| T, Y, cross, multi-leg junction | one intersection, one arm per road edge |
| dog-leg (two T-junctions under 15 m apart) | one intersection |
| roundabout | one intersection: the cluster of its ring nodes; its central island is part of it (the ring road runs around it) |
| dual carriageway crossing a street | one intersection (the crossing street's nodes with each carriageway are under 15 m apart) when close, else two |
| slip lane / filter lane | part of the intersection when it lies within the cuts, else a section |
| junction of walkways only | not an intersection |
| a street that ends in another street (T) | the end street has an arm; the through street has two |
| dead end | not an intersection; the section just ends |
| a bridge crossing over | no intersection (different level) |
| open square with streets leading into it | planned `plaza` kind (section 7); today it is split among the nearest sections |

## 5. Relations and cardinalities

```
street (group) 1 ──< section        a section is in exactly one street
street (group) >──< intersection    through space.arm: an intersection is in every street that arrives at it
section        >──< intersection    through space.arm: a section meets 0, 1 or 2 intersections (its two ends)
```

A street's **extent** for display is its sections plus the intersections it arrives at. A section is *between* intersections; the
intersection is not inside any section. The street has no geometry of its own: it is the union of its members.

## 6. Other kinds

- **Path space** (`p`): a connected network of footpaths and cycleways with no road along them (park paths, alleys, steps).
- **Rail space** (`r`): a connected network of rail lines at one level, with a strip for the structure; its zone is `track`.
- Both obey P1 to P7 (including **one connected polygon**: a disconnected path network is several path spaces).

## 7. Planned kind: plaza

An open piece of `U(L)` that is wide in every direction and has streets leading into it (a square, a market, a forecourt) is a
**plaza**: neither a section nor an intersection. Found by morphological opening of `U(L)` with a radius larger than a street's
half-width, then taking the blobs not already in an intersection. Not built; until then it is split among the nearest sections and
shows up as an unusually wide, `open` section.

## 8. Invariants checked on every build

`checks.py` computes these from the finished database and reports pass or fail with the numbers.

| id | check | from |
|---|---|---|
| P1 | pairs of containers overlapping by more than 0.5 m² (after a 1 cm inward buffer): 0 | P1 |
| P3 | invalid, empty or under 1 m² containers: 0 | P3 |
| P4 | containers with more than one part: 0 | P4 |
| P5 | elements without a container, or pointing at a missing one: 0 | P5 |
| P6 | containers whose `kind` is not one of the allowed values: 0 | P6 |
| P7 | duplicate container ids: 0 | P7 |
| S1 | sections with no road, or no `street_id`: 0 | section |
| S2 | sections that meet more than two intersections: 0 | section |
| I1 | intersections with fewer than 3 arms: 0 | intersection |
| I2 | intersections with only one street group: reported (a loop road is the only legitimate case) | intersection |
| I3 | intersection area outside 30 to 10,000 m²: 0 | intersection |
| I4 | junction nodes inside no intersection: reported | intersection |

## 9. Conformance of the current build (2026-10-02, level 0)

See the table `checks.py` prints, copied into `street-space.md` after each run. Known gaps, with their cause:

| gap | cause | work package |
|---|---|---|
| **P4**: about 30% of sections, 30% of path spaces and most rail spaces are multi-part | a section's nearest-centerline cells can be separated by a building or by another container's cells | WP2 |
| no dead-end handling | a section ending at a degree-one node simply ends | WP5 |
| walls and fences ignored as obstacles | only buildings stop a ray (buildings are recorded as boundaries; walls and fences are not) | WP8 |

## 10. Plan

In this order; each has an acceptance test that is one of the invariants above or a named case.

| wp | work | accept when |
|---|---|---|
| WP1 | `checks.py`: run the invariants of section 8 on a database, print pass or fail | it runs on both pilots and the report is in `street-space.md` |
| WP2 | split every multi-part container into one container per connected part; the part that holds the most element length keeps the id, the others get `<id>.<k>` and the same `street_id` | P4 = 0 on both pilots, P1 and P5 still 0 |
| WP3 (done) | arm cuts: build each intersection from per-arm perpendicular cuts instead of a hull | for T, cross and Y test junctions the cut is within 10° of perpendicular; I1 to I4 hold |
| WP4 | junction classification: store `shape` (`T`, `Y`, `cross`, `multi`, `roundabout`, `dogleg`) and number of arms | the cases of section 4 each have a test and the right `shape` |
| WP5 | dead ends and isolated roads: store `n_ends` on sections and mark dead ends | section meets 0, 1 or 2 intersections; a cul-de-sac test |
| WP6 (done) | `plaza` kind | an open square test becomes a plaza, not an open section |
| WP7 | one-way flag and direction handled in the street-view and arrows (dashboard) | no arrows on two-way roads, none in focus |
| WP8 | walls and fences as obstacles (`street-objects.md`, step 2) | capped share falls; widths re-measured |
| WP9 | strips (`street-objects.md`, step 4) | strips cover the street space |

## 11. Decisions I propose to take unless you object

1. **P4 is a hard rule**: one container is one connected polygon; disconnected parts become separate sections with ids `<id>.<k>`
   and the same `street_id`.
2. The **arm cut is perpendicular** to the arriving road, at `max half-width + 3 m` from the node.
3. A **roundabout** is one intersection that includes its island.
4. A junction needs **three or more arms**; an apparent junction of two is a continuation, not an intersection.
5. **Plazas** are their own kind, built after WP2 to WP5.
