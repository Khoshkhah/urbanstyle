# Strips, first version (step 4 of `street-objects.md`)

`space.strip` fills each container completely with typed bands, so a focused street space looks like a street plan instead of two
grey zones. Built by `strips.py`, called at the end of `urbanstyle.build()`. Terms are in `docs/glossary.md`.

## What is built

Every strip is cut from the container's own zones (`space.zone`, now clipped to the container's final shape), so the strips of a
container add up to its travelway plus pedestrian realm: no gap, no overlap. Check **C2** in `checks.py` tests this on every build.

| container | zone | strips |
|---|---|---|
| section | travelway | `travel`, one band per lane: `lanes` tag, else width / 3.25 m; one-way and two-way roads lay them out either side of the centerline, the outer lanes run on to the kerb; whatever a lane band does not take is `travel` with no side |
| section | pedestrian realm | `cycle` (measured cycleway lines), `frontage` (within 1.2 m of a building), `furnishing` (within 1.8 m of the kerb), `open` (more than 6 m from both: only reached by the reach cap), `sidewalk` (the rest) |
| intersection | travelway / pedestrian realm | `travel` / `sidewalk` |
| path | whole | `sidewalk` / `cycle` from the walkway and cycleway lines, the rest `open` |
| plaza, rail | whole | `plaza`, `track` |

Columns: `strip_id` (`<container_id>.<n>`), `container_id`, `level`, `type`, `side` (`left`, `right`, `center` for lane bands, else
NULL), `width_m` (mean width: area / length of its road), `source` (`tag`: lanes or width tagged; `measured`: a measured line;
`default`: a flat guess), `geometry`.

## Dashboard

Focusing a street space shows its strips (asphalt grey lanes, green cycle, tan sidewalk, darker tan furnishing and frontage, pale open
ground) instead of the two zones, with a legend and areas in the side panel. A focused **section** also shows the strips and objects of the
intersections it meets (`tree.secarms`), because its crossings and signals sit there.

Objects are drawn as their **real footprints** (`object_shapes()` in `dashboard.py`, class table `OBJ_SHAPES`), not as dots or icons: a tree is a
4 m canopy with a trunk, a bench a 1.8 x 0.5 m rectangle turned to run along the nearest road, a signal a pole with its head on the road
side, bins, bollards, lamps and signs small discs, a crossing a set of zebra stripes (0.5 m every 1 m) across the road. Colours are by class.
In the city overview and when a class is picked in the tree the old point markers are still used, because a bench is smaller than a pixel there.

## Limits (honest)

- No axis and no (s, t) yet, so strips have no `s_from` / `s_to`; each lane band covers one road element's stretch.
- Parking strips do not exist: Södermalm has no parking tags on its roads. Cycle lanes come only from separate cycleway lines (19 tagged
  ways); bus lanes, tram tracks in the road and medians are not separated out.
- Lane count is a tag on about 21% of Södermalm roads and 48% of Monaco's; elsewhere it is width / 3.25 m, marked `default`.
- Objects have no orientation of their own: a rectangle is turned to run along the nearest road, which is right for benches and entrances only most of the time. A node mapped in the middle of the carriageway (many traffic signals are) is drawn where the data puts it.
