# The format and the standards

This page explains why urbanstyle's format is a profile of CityGML 3.0, and how it relates to the other standards for streets. The
full research, with sources, is in [Our format and the standards](../design/standards-comparison.md). The requirements are in
[The format](../design/format.md).

## Each standard answers one question

| Standard | Its question |
|---|---|
| CityGML 3.0, CityJSON | What is the city made of, in 3D? |
| ASAM OpenDRIVE | Where can a simulated vehicle drive? |
| IFC 4.3 | How is this road or bridge designed and built? |
| OpenStreetMap, Overture, GMNS, INSPIRE | How is the network connected? |
| OpenSidewalks | Where can a person walk, and can they? |
| Curb Data Specification | What can a vehicle do at this kerb, and when? |

No standard answers "what is in this street, and how sure are we of it?" That is urbanstyle's question.

## Why CityGML 3.0

CityGML 3.0 divides a road the same way urbanstyle does: into sections and intersections, an intersection shared by the roads that
meet there, and inside them the spaces of traffic (`TrafficSpace`) and the spaces beside it (`AuxiliaryTrafficSpace`). It is an
open OGC standard, and cities already use it for buildings. Japan's PLATEAU publishes the 3D models of many cities in it.

urbanstyle writes it as **CityJSON**: the JSON encoding of CityGML, under CC0, with a JSON Schema, a validator and extensions. An
extension adds what only urbanstyle has, with names that start with `+`:

- `+sources`: the source, method and accuracy of each value;
- `+level`: the level of each space;
- the position (s, t) along each subsection;
- the blocks and the ground.

## Two views in one file

A sidewalk is an area in CityGML, and a line in a walking network such as OpenSidewalks. The format keeps both: each sidewalk and
crossing has its area and its center line, with the same id, and the lines join into a graph at kerb nodes. Their details use
OpenStreetMap's keys (`kerb`, `tactile_paving`, `incline`, `width`, `surface`), as OpenSidewalks does. So an export to OpenSidewalks
only rewrites, and adds or guesses nothing.

## The other standards are exports

- **OpenDRIVE** for driving simulation in SUMO, CARLA and esmini. It is not under an open licence, and it is made for vehicles.
- **OpenSidewalks** and **OpenStreetMap** for walking and accessibility. OpenSidewalks' licence (CC BY-ND) allows data in its
  format, but no change to its schema.
- **GMNS** for traffic models. duckOSM already writes it.
- **IFC 4.3** only for a project's hand-over. It is made for design, not for an inventory of streets as they are.

## Ids that stay

An id must not change when a source changes, or links from outside break. urbanstyle gives each thing a **profile** made only of
facts that do not change: for a sidewalk, its street, the two intersections at the ends of its section, its side, and its place from
the kerb. A registry maps each profile to an id. At each build, an equal profile gets the same id. Overture keeps its ids stable in
the same way, with a registry, but its matching rules are its own. urbanstyle's rules are written in the format, so anyone can check
them.
