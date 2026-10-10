# Plots: the ground of the blocks, and where the street ends

Status: agreed 2026-10-10. Step 1 built: U14 and the fill rule (Broadway × Granville: 316 pieces, 14,289 m² of street ground in no
space -> 65 pieces, 6,372 m²; what is left is over 300 m² a piece or borders no space). Step 2 (parcels) not started.

## The problem

The street space ends at the building faces (a ribbon reaches 4 m past the facade line, and the building line is cut out of it) and,
since 2026-10-10, at the edges of car parks (`space.lot`). Everything else inside a block (gardens, yards, forecourts, passages, a
tower's plaza) is in no space and has no part: on the map it is blank. Separately, some street ground is left to no space: around
Broadway × Granville 5 pieces, 193 m², in the area west of the junction (the biggest 132 m², a strip in front of houses), and no check
measures it.

## The sources

| source | what | here |
|---|---|---|
| City of Vancouver `property-parcel-polygons` | every parcel (assessment land polygons; "much of the land base at survey accuracy"; weekly): address, `site_id`, `tax_coord` | 445 within 400 m |
| `property-tax-report` (by `tax_coord`) | zoning, land use, year built, values | not loaded |
| OSM `landuse`, `leisure`, grass (duckOSM `features.land`) | residential 40, retail 31, grass 8, park 5, allotments 3, playground 2, garden 2, ... | loaded, not used |
| our own | buildings with their use (`buildings.py`), car parks (`space.lot`) | built |

OSM has no parcels; Stockholm's (Lantmäteriet) need a login; Monaco's are not open. So the rule must fall back to today's where no
parcels exist.

## The rule

1. **Plots (`space.plot`)**: one row per parcel: id `pl<site_id>`, address, the buildings and the car park on it, its use (the
   buildings' use, the tax report's land use when loaded) and the source, method and date of each.
2. **The street ends at the property line.** Where parcels exist, the right-of-way is the ground outside every parcel: a space reaches
   to the parcel line, not to a facade + 4 m. A building over the line (an arcade) is handled as now (the road's own surface stays its
   space). Where there are no parcels, buildings and car parks bound the street as today.
3. **Plot ground**: inside a plot, what is not a building or a car park is one part per kind of ground: `garden`, `grass`,
   `playground`, `plaza` where an OSM area says so, else `yard` (cover unknown). Source osm (mapped) or urbanstyle (derived).
4. **No street ground left to no space**: a new check **U14** (INFO: street ground in no space, m² and pieces), and the rule that
   gives each such piece to the space it shares the longest border with (as the pockets between spaces today), at most 300 m² a
   piece; a larger one is reported, not given.

## Order

1. U14 and the fill rule (small; does not move the street's edge).
2. Parcels as the street's edge, and the plots with their ground (changes every space's outer edge: checks before and after on the
   unit).
3. Later: the tax report (zoning, land use), Metro Vancouver's 2 m land cover (grass, trees, paved) for the plots' ground.
