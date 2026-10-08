# How others partition a street space (research)

Two questions from the Rosenlundsgatan review: (1) how do others cut a street space into pieces, and (2) is the **intersection**
a part of a street or a space of its own? Sources are linked; where a source did not give a detail it says so. The IFC page itself could not be fetched (HTTP 403); its definitions here come from a search summary of it.

## 1. The comparison

| system | the piece along a street | the piece at a junction | relation of the junction to the streets | how the junction's shape is found |
|---|---|---|---|---|
| **CityGML 3.0** Transportation ([3DCityDB model](https://3dcitydb-docs.readthedocs.io/en/latest/3dcitydb/uml/transportation.html), [TUM / ISPRS](https://isprs-annals.copernicus.org/articles/VI-4-W1-2020/29/2020/isprs-annals-VI-4-W1-2020-29-2020.pdf)) | `Section`: a regular stretch of a road, track or railway | `Intersection` (also a roundabout) | a road is divided into sections **and** intersections; one intersection **can belong to several roads**, so shared space is not stored twice | not prescribed; the standard is a data model, with a centerline and an area per level of detail |
| **IFC 4.3** ([IfcRoadPartTypeEnum](https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/HTML/lexical/IfcRoadPartTypeEnum.htm), via a [search summary](https://bimcorner.com/?p=32284)) | `ROADSEGMENT`: a longitudinal segment of uniform characteristics, or a transition | `INTERSECTION`: an "at-grade junction where two or more roads meet or cross" | both are **road parts** of an `IfcRoad`; lateral parts (carriageway, traffic lane, sidewalk) hang below | not prescribed |
| **OpenDRIVE** ([junction elements](https://commonroad-scenario-designer.readthedocs.io/en/latest/api/map_conversion/opendrive/opendrive.opendrive_parser.elements/)) | `road`, with lane sections | `junction`: a separate element holding **connecting roads** that join an *incoming road* to another | roads end at a junction; the junction is **not part of any one road** | the connecting roads are authored, not derived |
| **osm2streets** (A/B Street, [README](https://github.com/a-b-street/osm2streets)) | a road: a thickened line with lanes left to right | an intersection: a **separate polygon**, "each road polygon intersecting at a perpendicular angle" | roads are trimmed to the intersection polygon; many roads share one intersection | consolidation steps: collapse an unnecessary intersection between two roads, merge dog-leg intersections and **short roads between close intersections into one logical intersection**, merge dual carriageways ("sausage links") into one road, snap parallel cycle tracks and footways to the road. The trimming algorithm itself is not described in the README |
| **Traffic engineering** ([MoDOT](https://epg.modot.org/index.php/Functional_Intersection_Area)) | the road between junctions | the **physical** intersection area, and a larger **functional** area | the physical area is "within the four corners": bounded by the prolongation of the lateral curb lines (the curb returns); where a crosswalk is marked on the departure side, the area extends to its far side, and likewise to a marked stop line on an approach. The functional area adds the upstream approach (perception-reaction, manoeuvre and queue-storage distance) and any auxiliary lanes | geometric: curb lines, crosswalks, stop lines |
| **Skeleton / polygon methods** ([dense junctions, IJGI 2019](https://p.gyb.elementfx.com/2220-9964/8/7/303); for centerlines from road polygons see also [Haunert and Sester 2008](https://www1.pub.informatik.uni-wuerzburg.de/pub/haunert/pdf/HaunertSester2008.pdf), not read in detail) | skeleton segments between junction nodes | a junction found as the cluster of skeleton nodes / triangles of a constrained Delaunay triangulation of the road polygon where the local width is large (the "Type III" triangles) | derived from the road polygon, not from a node | from the polygon's own width |
| **our current model** | `street`, `path`, `rail` container | `intersection` container: a disc, radius `max half-width + 4 m`, around each junction node, merged where discs overlap | a **separate** container of the same level as streets; not linked to the streets that meet there | the disc, clipped to the street space |

## 2. Is the intersection a subsection of a street, or separate?

**Separate, and shared.** In every system above the junction is its own piece of the partition, on the same level as the
stretches of road, and it belongs to *several* streets at once:

- CityGML 3.0 says it outright: an intersection can belong to multiple roads, to avoid storing shared space twice.
- IFC makes `INTERSECTION` one of the road parts beside `ROADSEGMENT`.
- OpenDRIVE keeps the junction outside the roads: roads end where it begins.
- osm2streets stores an intersection as its own polygon that several road polygons meet.

So our model is right to make an intersection a **separate container** of the same kind of level as a street section. What it
lacks is the **relation**: a junction is "of" all the streets that meet there, and today nothing says which. A street's full
extent, in the sense of the standards, is its sections **and** the intersections it passes through.

## 3. Where our shape differs

1. **A disc is not a junction.** The standards bound the junction by curb returns, crosswalks and stop lines; osm2streets by the
   perpendicular cuts of the arriving roads. A disc of `half-width + 4 m` is smaller than the real junction space wherever several
   streets meet at an angle or a crossing sits further out. The rest of the junction space is then divided among the arriving
   streets by nearest centerline, which produces the bulges and spikes seen at Rosenlundsgatan.
2. **No consolidation.** osm2streets merges dog-legs and short links between nearby junctions, collapses a "junction" of two
   roads, and merges dual carriageways into one road. We make a container per junction node and merge only overlapping discs.
3. **The functional area is not modelled.** Probably not needed for a street-space map; the physical area is what matters.
4. **Plazas.** A square with no centerline is, in the skeleton methods, a wide cluster; we give it to the nearest street or path.

## 4. Proposal

Keep the intersection a separate container, and change how it is found and how it is related:

1. **Shape from the arms.** For each junction node and each arriving road, take the road's measured cross-section at a distance
   `d` from the node (`d = max half-width + a crossing setback of about 3 m`): its left and right end points. The intersection
   is the hull of those corner points and the node, clipped to the street space. This follows the curb returns, as the
   standards describe and as osm2streets' perpendicular cuts do, instead of a disc.
2. **Consolidate.** Merge junction nodes closer than about 15 m (dog-legs, the nodes of a roundabout, the two ends of a short
   link) into one intersection; keep the dual carriageways of one street as one street, as now.
3. **Relate.** Add `space.arm(intersection_id, street_id, arm_s)`: which streets meet at which intersection, and where the street
   enters it. A street's extent for display is its sections plus the intersections on its arms, which answers "the intersection
   is part of what?" without making it a subsection of one street.
4. **Plazas later.** A large open piece of the street space with no road through it becomes its own kind (`plaza`), found by
   morphological opening (erode then dilate) of the street space.

Not proposed: a functional (upstream) area, and a hand-drawn junction geometry as in OpenDRIVE.

## 5. Decisions needed

1. Keep the intersection as a separate container, shared by the streets that meet there, and add the `arm` relation?
2. Replace the disc by the hull of the arms' cross-section corners, with merging of junctions closer than 15 m?
3. Add a `plaza` kind (step later), or give open pieces to the nearest street as now?

## 6. Decisions and status (2026-10-02)

Agreed: do the standard approach. Built: the intersection stays a separate container, shared by the streets that meet there, with
`space.arm`; its shape is the hull of the arms' corner points (not a disc) with junction nodes under 15 m merged; and a street is
divided at every intersection into sections, with the street kept as a group of its sections and the intersections it arrives at.
Not built: a `plaza` kind for open squares.
