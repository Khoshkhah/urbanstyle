# The dashboard

<p class="lead">One page for every area, with one panel: Find, Filter and Ask, the layers by rank, the levels, and a card for the
selected thing, in 2D and in 3D. The page is served locally with a server, or published as static files with no server.</p>

## Purpose

A planner asks questions about the street: where the sidewalks are narrower than 1.8 m, which crossings have no kerb ramp, how much
of a street is for cars and how much for people. The dashboard answers on the map, with numbers and with the source of each part.

## How the page is made

| File | What it holds | Where it comes from |
|---|---|---|
| the page, `viz/<area>.html` | the area's data only: the map with the model's layers, and the area's own values for the engine | `urbanstyle dashboard DB OUT` |
| `urbanstyle-engine.js` | the map engine: 3D, levels, bridges, Street View, links | the package |
| `urbanstyle-panel.js`, `urbanstyle-panel.css` | the panel: Find, Filter, Ask, Layers, levels, cards | the package |

`urbanstyle serve` serves the page as it is, gives the three files from the package on every request, and answers the panel's data
requests. A change to the engine or the panel shows on the next reload, in every area, with no page rebuilt. `urbanstyle publish`
copies the three files beside the page, with the panel's data as files.

Every layer starts hidden, and a veil covers the page until the layers' data and the server's first answer are in. The panel then sets
every layer and lifts the veil, so nothing changes in front of the user while the page loads.

## The panel

1. **Get a result list** with one of three tabs. Find: a name, an id, or the area's tree under the box. Filter: one layer and conditions
   on its fields. Ask: a question in plain words to the AI agent. The results are orange on the map. The list shows the count, the
   total length and area, and the count of each type; it can be saved as CSV or GeoJSON.
2. **Select one thing** with a click on a result, on a tree item, or on the map, in 2D or 3D. It is deep purple, and its card opens
   at the top of the results: its fields, and buttons to the things it leads to (a part's space, a space's parts or section, a bridge
   part's axis, all objects of one class). The thing under the mouse is light purple.
3. **Add layers** in Layers. All are off at start: the map shows the base map, the buildings in grey and the bridge.

**The tree** is the area's tree: the named streets, their sections and intersections, the subsections, the parts; the bridge by axis;
the street objects by group and class; the blocks; the buildings by level; the ground by kind. Tick boxes put a list together from
parts of the tree. An exact id in Find selects that thing at once.

**A space in focus.** When a section, subsection or intersection is selected, the map zooms to it. In 3D its parts, kerbs and painted
lines, the objects that stand in it and the buildings that frame it keep their colours, and everything else is faint.

**Levels.** Each level that has streets has one button with three states: full, faded, hidden. Level 0 is the base map, the
buildings, and in 3D the ground with its parts, kerbs and objects. Level 1 is the bridge and the decks. 2D starts with level 1 faded;
3D starts with all levels full. In 3D a tunnel's parts lie under the ground of level 0 and show when level 0 is faded or hidden.

**G.** The last button of the level row has the same three states for everything that is not a road, on every level. A road is the
carriageway: the road lines, and the parts lane, junction area, bus lane, ring, cycle lane, shoulder, parking, crosswalk and cycle
crossing, with the painted lines on them. Everything else goes with G: the base map, buildings, ground, sidewalks, islands, kerbs,
street objects, paths, the outlines of the spaces, and a bridge model's slab, sides, parapets, piers and truss. A thing gets the
stronger of its level's state and G's. With G hidden, only the road network and its links from level to level are shown.

**Low buildings** (3D): each building at most 3 m high, so it does not hide the streets.

## The layers

The Layers list is the hierarchy by rank. One box per rank; under it the layers of that rank. A rank's box ticked shows every layer of
the rank; a click on it turns them all off when any is on, all on when none is.

| Rank | Layers |
|---|---|
| 0 | the area (`urban.area`), the road lines, the buildings, the rail, the stations |
| 1 | the street, the plots and the paths (`urban.ground`); the footways, every footpath whole at its width, lying on the ground |
| 2 | the sections, the intersections, the path sections and the path intersections (`urban.stretch`); the plot's pieces: building, yard, alley, car park, construction site, green, water, rail, square, structure (`urban.plot_piece`) |
| 3 | the spaces (`urban.space`), their axes, the cuts |
| 4 | the driving side and the walking side (`urban.side`) |
| 5 | one box per part kind, the driving side first, then the walking side (`urban.part`) |
| 6 | one box per mark kind (`urban.mark`) |
| on top | the street objects, the objects on the parts, the bridge in 2D, the links, Mapillary's detections (validation) |

The page draws the model: each layer of a rank is one table of `urban`, and its card shows the row of that table, with its parent,
its `uid`, and its `(s, t)` and links where it has them. Each kind has the colour of `urban.style`.

A kind box filters its layer to that kind. A kind the area has none of is greyed, "none here". The 3D view draws the parts, the kerbs,
the painted lines, the buildings at their height, the bridge models and one model per street object; a hover lights a thing and names
its type, a click selects it.

## The AI agent

The agent answers only from the data and gives the source of what it says. It has two tools: one read-only SQL query at a time
(`SELECT` or `WITH`, at most 200 rows), and a query whose result goes to the map and the results list (at most 2000 features). The
answer shows the queries it used, so a planner can check them. If no table holds the data, the agent says which data is missing.
The model is Claude when an Anthropic key is set, else Gemini when a Gemini key is set. The keys stay on the server, never in the
repository or the page.

## The dashboard online

The published dashboard runs in the browser with no server. The panel's data are files made at publish time: the meta and the tree
as JSON, the layers as Parquet files with the geometry as GeoJSON text and each row's length and area. Search and Filter run as SQL in
the browser with DuckDB-WASM. Ask calls Gemini from the browser with a key that belongs to a separate project with no billing, placed in
the page by the site's workflow from a repository secret and restricted to the site's address; a visitor can give their own key, kept
in the browser only. Street View uses a second map key restricted to the site's address. The base map's key comes from a secret too;
without it, a keyless base map is used.

Published: the tables of the `urban` schema, the buildings, the street objects and the bridge model, with their licences named on the page. Not
published: Mapillary's detections and photos (CC BY-SA, kept local) and the local map key. The page and the Parquet files go up as
the assets of a release, not into the repository.

## Limits

- The server is for local use: no login and no limit on the API cost.
- The SQL check accepts one `SELECT` or `WITH` statement; it refuses statements that write and functions that read files.
