# Design notes

<p class="lead">How urbanstyle came to be built the way it is: the problems, the options and what was decided.</p>

- [One unit in full](unit-dossier.md): the new direction: one intersection or street section with every source, in a
  structure with provenance; three units in Stockholm and Vancouver.
- [What the sources hold](source-inventory.md): every source around a unit counted against what reaches our
  tables (the dossier's `inventory`), the gaps by topic (parking, bus stops, building use, ...) and a general rule for each.
- [Street space](street-space.md): **read first.** Definitions, sources, the cross-section algorithm, levels,
  containers, zones, rail and stations, links between levels, parameters and results.
- [Street space specification](street-space-spec.md): sections and intersections as a formal partition, its
  axioms and the invariants `urbanstyle check` runs.
- [Sections and intersections, version 2](section-intersection-v2.md): the replacement of Voronoi and hulls by
  offset corridors and straight arm cuts.
- [Network first (preview)](network-first.md): divide the roads into subsections, then one space per subsection, intersection and
  roundabout, cut at the block corners.
- [The inside of a space](space-parts.md): lanes, junction area, crosswalks, sidewalks, markings and widths, with their sources.
- [Mapillary observations](mapillary.md): street-level signs, signals, street lights and parking from Mapillary's photos.
- [Street objects](street-objects.md): what goes inside a street space: axis and `(s, t)`, strips, objects,
  boundaries, and the order of work.
- [Objects, step 1](street-objects-step1.md): the point-object taxonomy and `space.object`.
- [Strips, first version](street-strips-v1.md): how each container is filled with typed bands.
- [Glossary](glossary.md): every word, column and id in one place.

Research:

- [How others partition a street space](partitioning-research.md): CityGML, IFC, OpenDRIVE, and whether an
  intersection belongs to a street.
- [How other software handles levels](levels-research.md): stacking order versus a real vertical coordinate.
