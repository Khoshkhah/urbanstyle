# Changelog

## 0.1.0 (unreleased)

Network-first partition, preview (docs/design/network-first.md, space-parts.md; branch `network-first`):

- `space.subsection`: sections split where the cross-section or the building frontage changes; close parallel roads are one corridor.
- `space.unit` / `space.cut`: one space per subsection, intersection and roundabout; intersections cut at the block corners.
- `space.part` / `space.mark` / `space.width`: lanes, junction box, roundabout island, crosswalks, cycle and bus lanes, sidewalks;
  markings at real size; widths with their source (measured from sidewalks or crossings, tagged, estimated).
- Checks U1-U10. Dashboard: the new spaces, their parts and markings, `?c=` links, clicks on spaces.
- Fixed: the halfway-to-a-parallel-street rule applied even with a building between the two streets.


First packaged version.

- `src/urbanstyle/` package with one command, `urbanstyle build | check | quality | dashboard` (the former
  `urbanstyle.py`, `checks.py`, `quality.py` and `dashboard.py` scripts).
- The `space` schema: elements by level (−2 … 2); the street space by cross-section rays; the partition into
  sections, intersections, path spaces, rail spaces and plazas; zones; strips; point objects; stations and links
  between levels.
- Docs site (MkDocs Material) with dashboard screenshots of Södermalm, tests on Python 3.10–3.13 in CI, logo.
