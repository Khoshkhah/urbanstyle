# Drawing the tables

<p class="lead">How a viewer draws the model: which table and which kind lies above which, the colour and the form of each kind, the
levels, and what is shown as a list and not on the map. The rules hold for any viewer: the dashboard, QGIS, or a page of its own.</p>

## The style is in the data

A build writes `urban.style`: one row per table and kind, with its draw order, its form, its colour and its dash. A viewer reads the
style from the database and needs no rule of its own. The dashboard reads the same table.

| Column | Meaning |
|---|---|
| `table` | the table of the thing |
| `rank` | the rank of the table, or none for a thing on the tree |
| `kind` | the kind; for a street object, its group (`furniture`, `vegetation`, `utility`, `transit`, `access`, `barrier`) |
| `draw_order` | where the kind lies in the stack of one level: a lower number is drawn first, a higher number on top of it |
| `form` | polygon, line or point |
| `colour` | the fill of a polygon, the colour of a line or a point |
| `dash` | a dashed line: the metres drawn and the metres left out; none for a full line |
| `raise_m` | in 3D, the height of the kind's top above the ground of its level: a sidewalk, an island, the kerb |

## The draw order

The order of drawing has two keys. The first key is the level: the levels are drawn from the lowest up, so a deck lies over the
ground and the ground lies over a tunnel. The second key is `draw_order`, inside one level.

The draw order follows the ranks. Each rank has its own band of numbers, and a lower rank always lies above a higher one:

| Band | Rank | What lies there |
|---|---|---|
| 0 | 0 | the area |
| 10 to 19 | 1 | the plots, the paths, the street |
| 20 to 29 | 2 | the plot pieces (the building on top), the sections and the intersections |
| 30 to 39 | 3 | the spaces |
| 40 to 49 | 4 | the walking side, the driving side |
| 50 to 59 | 5 | the parts: the walking side's bands first, then the paved roadway, the strips, the lanes, the islands and the crosswalks on top |
| 60 to 69 | 6 | the marks: the kerb, the lines, the stop lines, the zebras, the arrows, the guide lines, the barriers |
| 70 | on the tree | the street objects |
| 80 | on the tree | the links between the levels |

Inside a band, two kinds that never overlap share a number. A crosswalk lies over the lanes it crosses, and a zebra lies over the
crosswalk.

## One rank filled, the ranks above it as outlines

The ranks partition each other, so a rank filled hides the ranks below it. A viewer fills one rank at a time and draws the ranks above
it as outlines, in the colour of their kind. Two examples:

- The parts filled, with the spaces and the sections as outlines: the lanes, and the spaces that they lie in.
- The ground filled, with the area as an outline: the street, the plots and the paths.

The marks and the street objects are drawn over any filled rank, because they lie on the parts.

## The levels

- The level in view is drawn full. Another level is faded or hidden.
- In 2D every level lies flat. The levels are drawn in their order, so the level above lies on top.
- In 3D a level lies 6 m above the level below it. A deck is drawn at its bridge model's heights where the model gives them. A tunnel
  is drawn flat under the ground of level 0, and it shows when level 0 is faded or hidden.
- In 3D a building stands at its height (`height_m`). A part stands at its kind's `raise_m` above its level: the roadway at 0, the
  parts of the walking side and the islands above it, up to the kerb's top.

## The tree as a list

`urban.item` holds every rank in one table. A viewer that shows the tree lists it by `parent_id`: the area, its ground, the stretches
and the plot pieces, the spaces, the sides, the parts and the marks. A selected thing shows its row from its own table, its parent
and its children. Its `uid`, where it has one, is the id to keep in a link or a note, because it stays the same from build to build.

## What is not on the map

| Table | How a viewer shows it |
|---|---|
| `urban.meta` | a list: the version, the date of the build, the input files, the chosen values with their names |
| `urban.check` | a list: each check with its status and its count; a failed check's places as links that move the map there |
| `urban.registry` | not shown; the `uid` of a thing shows on its card |
| `urban.code` | on a thing's card: its kind in each standard |
| `urban.style` | not shown; it is how the rest is drawn |
