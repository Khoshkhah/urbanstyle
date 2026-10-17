# The design

<p class="lead">How urbanstyle models a city's street space, and how it builds the model from open data.</p>

The model is a hierarchy of six ranks over the area of a level. Each rank partitions the rank above it, with no overlap and no gap.
Every value in the model names its source and its method. The chapters:

1. [The model](model.md): the ranks, the levels, the words and the ids.
2. [The tables](tables.md): one table per rank, with its columns.
3. [Rank 1, the ground](ground.md): the blocks, the corridors, the street and the other kinds of ground.
4. [Rank 2, the stretches](stretches.md): the junctions, the sections, the subsections and the intersections.
5. [Ranks 3 and 4, the units and their sides](units.md): the partition of the street into units, the kerb, the driving side and
   the walking side.
6. [Ranks 5 and 6, the parts and the marks](parts.md): the lanes, the strips, the crosswalks, the sidewalk zones, the painted lines
   and the turns.
7. [Street objects](objects.md): what stands in the street, from every source, one object per real thing.
8. [Levels, bridges and tunnels](levels.md): the decks, the tubes, the links between levels and the bridge model.
9. [Sources and provenance](sources.md): the sources, the methods, which source wins, and the pilot dossier.
10. [The format](format.md): the requirements of the published format.
11. [The dashboard](dashboard.md): the page, the panel, the layers by rank, the AI agent and the online version.
12. [Glossary](glossary.md): every word, table, column and id in one place.

The research behind the design is in its own section: how the standards layer a street, how they partition it, how software handles
levels, and how urbanstyle's format relates to the standards.
