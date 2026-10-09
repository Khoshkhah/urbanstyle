# Roadmap

<p class="lead">Where urbanstyle stands (2026-10-08), what is open, and the order of work. Each step ends with something
you can check: a test, a <code>urbanstyle check</code> line, or a page to look at.</p>

## Where it stands

| | built | checked by |
|---|---|---|
| Buildings and network elements by level (−2 … 2) | yes | tests |
| Street space measured by cross-section rays | yes | tests, `open_share` |
| Partition: section, intersection, path, rail, plaza | yes | P1–P5, I1–I4 |
| Zones: travelway, pedestrian realm, track | yes | tests |
| Links between levels, stations, entrances | yes | tests |
| Point objects (`space.object`, taxonomy v1) | yes | street-objects-step1 |
| Strips, first version (no `s` / `t` yet) | yes | C2 |
| Boundaries (walls, fences, hedges) | no | |
| Axis and `(s, t)` | no | |
| Detail view (cross-section panel) | no | |
| Package, CLI, docs site, CI | yes (0.1.0, not yet released) | |
| Network-first spaces: subsections, intersections, roundabouts, their parts, marks, widths and turns (SUMO) | preview, Monaco | U1–U10 |

Monaco and Södermalm both pass the hard checks on their last full build. Section shape over Södermalm: median
rectangularity 0.79, 47 % of the outline on a facade (`urbanstyle quality`).

## Phase 0: get back to green

The work stopped in the middle of the gap fix (2026-10-04). Finish it before anything new.

1. **The failing test.** `test_a_container_records_the_buildings_that_bound_it` expects the bounded share of each
   building within 30–70 m; it gets 74.5 and 79.4. The gap fill (closing section + buildings by `GAP_M`) probably
   pushes the section onto more of each facade. Decide: is the new number right (change the test) or is the
   gap fill reaching too far (change the code)? *Done when:* 23 / 23 pass and CI is green.
2. **Rebuild Södermalm with the gap fix** (~18 min, ~7 GB: check free memory first). Level 0 must keep the baseline
   counts: 513 path, 52 plaza, 1248 section, 577 intersection. A drop in paths or plazas is the bug seen before.
   *Done when:* the counts match and `urbanstyle check` passes.
3. **Rebuild Monaco** (it was not rebuilt after the gap change) and re-run `check` and `quality` on both.
4. **The last gaps.** Two ~20 m² spots on `s0-1277220079715399641` are wider than the 3 m closing: a second rule
   (fill a spot that touches only one section and buildings) or a larger `GAP_M` limited to small areas.
   *Done when:* a gap measure (free space touching a section and a building) is a `checks.py` INFO line, and it falls.
5. **roadstyle 0.18.** Both dashboards build and load on roadstyle 0.18.1 (2026-10-08, the docs screenshots are
   from it). Once Kaveh has looked them over, raise the `dashboard` extra to `roadstyle>=0.18.1`.

## Phase 1: a public project like its siblings

6. **Docs site live.** Turn on GitHub Pages (Settings → Pages → GitHub Actions); the `docs` workflow is ready.
7. **Live map.** A `docs/build_maps.py` like lanestyle's: build Monaco in CI (duckOSM from PyPI, ~1 min) and publish
   the dashboard at `maps/monaco.html`, linked from the README.
8. **Gallery page.** Six dashboard screenshots: a section, a complex intersection, a plaza, a bridge
   over a tunnel, the objects, the strips.
9. **Release 0.1.0 to PyPI.** Add `release.yml` (trusted publishing, as in lanestyle), register the publisher on
   pypi.org, tag `v0.1.0`.
10. **Agent skill.** `skills/urbanstyle/SKILL.md` and `.claude-plugin/` as in the siblings: the install, the schema,
    the three commands and the traps on one page.
11. **A read API.** `urbanstyle.read(db, table, level=None)` → GeoDataFrame, so users do not write the
    WKB / CRS boilerplate the dashboard repeats.

## Phase 2: what is inside a street

The order of work agreed in [Street objects](design/street-objects.md#6-proposed-order-of-work).

12. **Boundaries** (step 2, WP8). Walls, fences and hedges become obstacles in the ray measurement and rows of
    `space.boundary`. *Done when:* the capped share (`open_share`) falls on both pilots and widths are re-measured.
13. **Axis and `(s, t)`** (step 3). `space.axis` per container (the midline of a dual carriageway); `s_m`, `t_m` on
    objects; `s_from`, `s_to` on strips, so a strip can start and stop along a street.
14. **Detail view** (step 5). Click a section: its cross-section drawn to scale, strips and objects by `(s, t)`.
15. **Line and area objects** (step 6): tree rows, parking areas, kerb lines.
16. **Open questions from the spec** (section 10): junction shapes (WP4), dead ends (WP5), one-way arrows in the
    dashboard (WP7). Check which are already done and close them in the spec.

## Phase 3: the family

17. **Lanes from duckOSM / lanestyle.** Strips now guess lanes from width / 3.25 m on 79 % of Södermalm's roads.
    duckOSM's GMNS lanes (the ones lanestyle draws) have per-lane widths and uses (bus, bike): read them for the
    `travel` and `cycle` strips, with `source = 'gmns'`.
18. **A mapstyle layer.** Draw containers and strips with mapstyle's themes (light, dark, satellite), so the street
    space sits in a full base map instead of a separate dashboard.
19. **A third area.** Tartu (duckOSM's `tartu`): no new parameters allowed. It shows which of the flat guesses
    (reach cap, margins, widths) are really Stockholm/Monaco-specific.

## Phase 4: scale

20. **Profile the Södermalm build** (18 min, 7 GB). The ray step and the Python `street_owner` /
    `intersection_shapes` are the suspects. Target: Södermalm under 5 minutes, then the whole Stockholm county.

## Decisions needed

- Phase 0.1: change the test or the gap fill?
- Phase 1.7: build the live map in CI (slower CI, nothing committed) or commit a small Monaco parquet (fast, ~10 MB)?
- Phase 3.17: should strips depend on duckOSM's GMNS output, or stay on the plain mode schemas?
