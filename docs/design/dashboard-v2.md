# Dashboard v2: explore the street space

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

The command serves the folder of the page (`viz/`) on a local web server. It adds the Explore panel to the page and gives the panel
its data through `/api/...`. A page that `urbanstyle dashboard` builds stays usable without the server. It then has no Explore panel.

## The page

One panel, docked on the left, with one way of working. The « button folds the panel away, and the map then takes the full width.

1. **Get a result list** with one of three tabs: Find (type a name or an id, or browse the tree under the box), Filter or Ask. The results are orange on the map.
2. **Select one thing** with a click on a result, on a tree item, or on the map, in 2D or 3D. It is deep purple, a short popup at it
   gives its name, layer and id (closing it deselects), and its **card** opens at the top of the results: its fields, and buttons to the things it leads to (a part's space, a space's parts or section, a bridge part's axis,
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
as a light outline over the street), and 3D starts with all levels full. Each view keeps its own choice. Tunnels (levels −1, −2) are to
be added with the second city (Södermalm).

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
