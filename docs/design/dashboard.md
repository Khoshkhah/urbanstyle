# The dashboard: its design

Status: step 1, local only (2026-10-13). Agreed with Kaveh: cities first, a local version first.

## Purpose

A city planner asks questions about the street, for example:

- Where are the sidewalks narrower than 1.8 m?
- Which crossings have no kerb ramp?
- How much of this street is for cars, and how much is for people?

The dashboard answers on the map, in 2D and in 3D, with numbers and with the source of each part.

## Command

```bash
urbanstyle serve DB [--bridge PROFILE] [--page viz/PAGE.html] [--port 8784]
```

## How the page is made (2026-10-13)

One dashboard, the same for every area (Kaveh: "they must run the same script").

| File | What it holds | Where it comes from |
|---|---|---|
| the page, `viz/<area>.html` | the area's data only: roadstyle's map with the current model's layers, and `window.US_CFG` (the area's own values for the engine) | `urbanstyle dashboard DB OUT` (`page.py`) |
| `urbanstyle-engine.js` | the map engine: 3D, levels, bridges, Street View, links | `engine.js` in the package |
| `urbanstyle-panel.js`, `urbanstyle-panel.css` | the panel: Find, Filter, Ask, Layers, levels, cards; it makes its own HTML | `panel.js`, `panel.css` in the package |

- `urbanstyle serve` serves the page as it is, gives the three files from the package on every request, and the panel's data
  (`/api/...`). A change to the engine or the panel shows on the next reload, in every area, with no page rebuilt.
- `urbanstyle publish` copies the three files beside the page, with the panel's data as files (no server).
- **The first look:** every layer starts hidden, and a "Loading" veil covers the page. The panel waits until the layers' data and its
  server's first answer are in, sets every layer (its defaults, the levels, the grey buildings), and then lifts the veil. So nothing on
  the page changes in front of the user while it loads. On a page with bridges, the engine also waits for the bridge script's list of
  the spaces the models replace (`window.brUnits`, from the 10 MB model file) before it opens a `?at=` link in 3D, and the bridge
  script draws 3D again when the list lands: a 3D view drawn before it showed a replaced space as a flat deck over the model.
- Opened as a file with no server, the page lifts the veil and shows the map alone.

## The page

One panel, docked on the left, with one way of working. The « button folds the panel away, and the map then takes the full width.

1. **Get a result list** with one of three tabs: Find (type a name or an id, or browse the tree under the box), Filter or Ask. The results are orange on the map.
2. **Select one thing** with a click on a result, on a tree item, or on the map, in 2D or 3D. It is deep purple (no popup: it held
   only the name and the id, and it covered the thing; 2026-10-13), and its **card** opens at the top of the results: its fields, and buttons to the things it leads to (a part's space, a space's parts or section, a bridge part's axis,
   all objects of one class).
3. **Add layers** in Layers, under the level row: the data's own layers (street space data, strips, links, painted lines, survey
   objects), each one on its own, and the options (terrain, road surface in 2D, Mapillary). All are off at start, and the map is quiet:
   the basemap, the buildings in grey and the bridge.

**The tree** (in Find, under the search box) is the area's tree, the street first and then the land beside it: streets → sections
and intersections → subsections → parts; the bridge by axis; street objects by group and class (from every source: OSM, the city's
survey, Mapillary); blocks; buildings by level; the ground by type. A click on a group's name lists all its things, and a click on one thing selects it. **Tick boxes** put a list together from
parts of the tree: the list is everything ticked, each thing once; ticking a group ticks all under it.
**Find** with an exact id (`s0-…`, `i0-…`, a part's or an object's id) selects that thing at once.

**A group in focus** (a street, a section, a class of objects from the tree): its things keep their colours in 3D, and for street
spaces also the buildings that frame them and the objects that stand in them (within 1 m).

**A street space in focus.** When a section, subsection or intersection is selected, the map zooms to it. In 3D its parts, kerbs and
painted lines, the street objects that stand in it and the buildings that frame it (within 5 m of its edge) keep their own colours,
and everything else is faint: other spaces, buildings, objects, the ground and, for a space on
the ground, the bridge. Closing the card brings everything back.

**Levels.** Each level that has streets has one button with three states, in three colours: full (deep purple), faded (light purple)
and hidden (white, crossed out). A click moves it to the next state, and the levels combine. Level 0 is the basemap and the buildings,
and in 3D also the ground, its parts, kerbs and objects. Level 1 is the bridge and the decks. 2D starts with level 1 faded (the bridge
as a light outline over the street), and 3D starts with all levels full. Each view keeps its own choice. In 2D the tunnels (levels −1,
−2) are hidden at first. In 3D the map cannot draw under the ground, so the tunnels' parts lie flat under the ground of level 0. To see
them, fade or hide level 0.

**Low buildings** (an option, 3D only): each building is at most 3 m high, so it does not hide the streets. The buildings are also
low while a street object is selected, because a building can stand between the object and the camera.

## The Explore panel

Explore has three tabs and one results list.

| Tab | What it does |
|---|---|
| Search | Finds names, ids, types and OSM references in all layers. It needs no AI. |
| Filter | One layer, and conditions on its fields (`=`, `≠`, `≥`, `≤`, contains). It can also limit the results to the map view. |
| Ask | A question in plain words to the AI agent. |

The results list shows the count, the total length and the total area, and the count of each type. A click on a result moves the map to
it, selects it and opens its fields. The results can be saved as CSV or GeoJSON.

Colours: the results are orange, the one thing selected is deep purple, and the thing under the mouse is light purple.

2D and 3D are apart. 2D draws the results as shapes and dots. 3D draws no shapes and no dots: it colours the 3D objects themselves
(buildings, street parts, the ground, car parks, street objects and bridge parts). A result with no 3D form (a painted line, a block,
a surface, a street space) shows only in 2D and in the list.

## Layers

The Layers panel is a tree, in the order of `docs/design/space-layers.md` (agreed 2026-10-13): Blocks (Buildings, Car parks);
Street: Sections (Subsections), Intersections, Parts (Crosswalks, bus zones, driveways; Painted lines; Street objects); Between
levels: Bridges, Links; Land use: Ground; How it was cut: Subsection axes, Subsection breaks, Cuts; Sources: Road centre lines, Track,
Rail, Stations. The old model (containers by cross-section rays, its travelway, pedestrian realm and strips) is not in it.

The tables the panel reads:
Street parts (`space.part`), painted lines (`space.mark`), street objects (`space.object`), buildings (`space.element`), car parks
(`space.lot`), ground (`space.ground`), surfaces (`space.surface`), blocks (`space.block`), street spaces (`space.unit`) and bridge
parts (`space.bridge_part`). The server makes `space.bridge_part` when it starts, from the bridge model (`bridge3d.model`, cached).

## The AI agent

- Model: Claude Opus 5.5 (`claude-opus-5-5`) through the Anthropic Python SDK, with server-side fallbacks (`fallbacks: "default"`),
  when an Anthropic key is set (`ANTHROPIC_API_KEY` or `~/.config/anthropic/key`). Else Gemini through `google-genai`, when
  `GEMINI_API_KEY` is set: `gemini-flash-latest`, or the model in `URBANSTYLE_GEMINI_MODEL`. The keys stay on the server.
- Gemini's free tier has no Pro model and allows 5 requests a minute and 20 a day for each model; one question uses up to 12. The
  agent waits and tries again when Gemini asks it to; when a model's day is used up, it goes on with the next Flash model, and the
  Lite models last (quick, but in a test one misread the source of the widths). In its last step it may not call tools, so it always gives an answer.
- Tools:
  - `run_sql`: one read-only query (`SELECT` or `WITH`), at most 200 rows.
  - `show_on_map`: a query that returns `geometry`. Its result goes to the map and to the results list.
- The agent answers only from the data. It gives the source of what it says. If no table holds the data, it says which data is missing.
- The answer shows the queries that the agent used, so that a planner can check them.

## Limits

- Local use only: no login and no limit on API cost.
- The SQL check accepts only one `SELECT` or `WITH` statement. It refuses statements that write, and functions that read files.
- A query returns at most 2000 features to the map.

## Next steps

To decide after the local version: a public demo (hosting, login, cost limit), drawn areas as filters, and saved questions.
