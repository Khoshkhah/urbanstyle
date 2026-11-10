# The page on roadstyle's dashboard (0.28)

Proposal, 2026-11-06. Built on the Casino cut (2026-11-06); not committed.

Kaveh's direction (2026-11-06): the page uses the newest dashboard UX of roadstyle.

## What the page is now

`page.py` calls `rs.render_edges` (roadstyle's map page) and puts urbanstyle's own panel on it: `panel.js` (533 lines) and
`panel.css` make their own HTML (`#xp`), with a fold button, the level and 2D/3D buttons, Checks, Layers, the tabs Find,
Filter and Ask, the selected thing's card and the result list. The map's controls are MapLibre's column (+, -, compass,
2D, Street View, 3D, layers, buildings).

## What roadstyle 0.28 gives

`rs.render_dashboard` (docs/guides/dashboard-layout.md, dashboard-panel.md, dashboard-parts.md in roadstyle):

- The panel at the left, empty, with its frame: the title, the theme button (light and dark) and the hide button. A page
  adds its sections with `dashboard={"panel": {"sections": [...]}}` or `rs.sections.add` from its script. A section with a
  `label` is a card (the card standard: a 44 px title row, a chevron, `fold`, `note`).
- The toolbox at the right edge: theme, navigate (one button: zoom, turn, tilt), Street View, Google 3D, base map, roads,
  3D buildings, colour and legend, settings, credits.
- The shared parts: tabs, chips, buttons, text boxes, tables and lists that scroll, a hover box, a help window, the
  theme tokens.

## The proposal

1. `page.py` calls `rs.render_dashboard` with the same map keywords and overlays. urbanstyle's fold button, 2D/3D buttons
   and the map's control column go: the toolbox has them (navigate, 3D buildings, Street View, Google 3D, base map).
2. `panel.js` keeps its logic and names (`xp...`), and puts its blocks into roadstyle's panel as cards, in this order:
   - **View**: the level buttons (full, faded, hidden), a card that does not fold;
   - **Find, Filter, Ask**: one card with roadstyle's tabs;
   - **Selected**: the selected thing's card;
   - **Results**: the list, with CSV, GeoJSON, Clear, Focus;
   - **Layers** and **Checks**: cards that fold, closed at first.
3. `panel.css` keeps only what roadstyle's parts do not give; the colours come from roadstyle's theme tokens, so the dark
   theme works.
4. `publish.py` and `static.js` (the docs site's copy) follow the same page.

## The order of work

1. A cut page with the new frame and today's blocks as cards, no change in what they do. Pictures of the old page and the
   new page, side by side, at the same place; the headless sweep (page errors, every card, 2D and 3D).
2. After Kaveh agrees: the details of each card, then `publish`, then `docs/design/dashboard.md`.

## Open question

The level buttons: a card of the panel (as above), or a tool of the toolbox (`rs.tools`, "Add a tool")?

## Kaveh's corrections (2026-11-06)

- The 2D / 3D switch stays: roadstyle's two-way switch (`rs-seg`) in the View card, beside the levels.
- The buildings' opacity is in the toolbox: the base-map box's "3D buildings" row and its opacity slider act on urbanstyle's
  own buildings (`engine.js`: `bldRow`, `bldOp`). The base map's own building layers get a filter that keeps nothing, so
  they never draw and roadstyle's row and slider stay.
- Every block is a roadstyle part: `rs-tabs`, `rs-seg`, plain and primary buttons, `rs-chip`, `rs-callout`, `rs-scroll` with
  `rs-table`, the theme tokens. `panel.css` holds only the layout of urbanstyle's own blocks and its data colours (the
  selection's purple, a failed check's red).
- roadstyle's dashboard code comes from its compiled extension (`_rust.abi3.so`): a source checkout at 0.28 with an older
  build gives an older dashboard. Build it with `rust/roadstyle-py/build.py`, or with cargo and an atomic rename while
  other processes have the old file open.
