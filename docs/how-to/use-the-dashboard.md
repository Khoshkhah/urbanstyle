# Use the dashboard

This guide opens an area in the dashboard and shows how to find things, filter them, and look at one street in focus.

## Open the dashboard

1. Make the page:

    ```bash
    urbanstyle dashboard data/monaco.duckdb viz/monaco.html
    ```

    To draw a bridge in 3D, add `--bridge` with its profile (see [Model a bridge](bridges.md)).

2. Start the server. It serves the folder of the page and gives the panel its data:

    ```bash
    urbanstyle serve data/monaco.duckdb viz/monaco.html
    ```

3. Open <http://localhost:8784/>.

The server uses port 8784 by default. Street View's linked panorama works only on this port, because the Google key allows it
only there. To have Street View, set `GOOGLE_MAPS_KEY` before you make the page.

A page that `urbanstyle dashboard` makes also opens without the server, as a file. It then shows the older panel, with no Find,
Filter or Ask.

## Know the panel

The panel is on the left. The « button folds it away, and the map then takes the full width.

- **Level and view.** Each level that has streets has a button. A click moves it to the next look: full (deep purple), faded (light
  purple), hidden (white). The levels combine. **2D** and **3D** switch the view.
- **Layers.** The data's own layers for 2D (street space data, strips, links, painted lines, survey objects), and the options
  (terrain for 3D, the road surface in 2D, Mapillary). All are off at first, so the map starts quiet.
- **Find, Filter, Ask.** Three ways to get a list of things. The list shows below the tabs, and on the map in orange.

## Find a thing

- Type a street name, a type (for example `hydrant`), an OSM id or an urbanstyle id, then press **Find**. An exact id selects that
  thing at once.
- Or open the tree under the search box: Streets, Bridge, Street objects, Blocks, Buildings, Ground.
  - A click on a group's name lists all of it.
  - The tick boxes put a list together from parts of the tree. A ticked group includes everything under it.
  - The arrow opens a group without listing it.

## Filter a layer

1. Open **Filter** and select a layer, for example **Street parts**.
2. Set one or more conditions, for example `type = sidewalk` and `width_m <= 1.8`.
3. To keep only what is on the screen, tick **only in the map view**.
4. Click **Show**.

## Look at one thing

Click a result in the list, a thing in the tree, or a thing on the map.

- The thing turns deep purple. If the panel is hidden, it opens.
- Its **card** opens above the list, with all its fields and buttons to related things: its space, its parts, its section, all
  objects of its class.
- The mouse resting on a thing for 300 ms lights it in light purple, and in 3D names its type.
- In 3D, a selected street object is seen along its street, and the buildings become see-through, so that no building hides it.
- To deselect, click the card's ×, press Esc, or click the thing again.

## See a street in focus

In 3D, select a section, a subsection, an intersection, a block, or a group from the tree (for example a whole street). It is then
in focus:

- its parts and kerbs keep their colors;
- the street objects that stand in it keep their colors;
- the buildings that frame it stay solid: the front row, the buildings you can see from the space within 10 m;
- everything else is faint, the other buildings are see-through, and so is the bridge when the focus is on the ground;
- painted lines, arrows, guide lines and crosswalks keep their colors everywhere.

Closing the card, or **Clear**, brings everything back.

## Save the results

**CSV** and **GeoJSON** under the list save the results with all their fields.

## Related

- [Ask questions](ask-questions.md) with the AI agent.
- The design of the panel: [Dashboard v2](../design/dashboard-v2.md).
