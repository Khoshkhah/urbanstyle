# How other software handles different levels (research)

Question: our model has integer levels -2 … 2 (a level per element, a street space per level). How do others represent the vertical
dimension? Sources are linked; claims not found in a source are not made.

## 1. Relative stacking order (a small integer that says "above" or "below")

| system | what it stores | notes |
|---|---|---|
| **OpenStreetMap** [`layer=*`](https://wiki.openstreetmap.org/wiki/Key:layer) | an integer on a way: the vertical relationship **between two intersecting features**; unmarked ways are 0 | "valid exactly only in the precise location where the ways cross or overlap"; it says nothing about height (a low bridge is layer 1, Mount Everest is layer 0); meant to be used with `bridge`, `tunnel`, `highway=steps`, `elevator`, `covered` or `indoor` |
| OSM `level=*` | the floor inside a structure (walkways, stations, multi-storey buildings) | a different meaning from `layer`: the physical arrangement of floors, not a crossing order |
| **HERE** map data [Z-levels](https://docs.here.com/gis-data-suite/docs/zlevel-crossings) | an integer from **-4 to +5** at every **node or shape point** of a link, 0 = grade | "a relative value, not an absolute height": how many navigable or hydro features lie above or below it. The `Z_Level_Crossings` table records where links cross without meeting, so a router knows there is **no traversable intersection** there ([HERE KB](https://docs.here.com/here-kb/docs/are-different-z-level-values-for-the-same-bridge-or-tunnel-location-correct-according-to-here-specifications)) |
| **Overture Maps** [`level_rules`](https://docs.overturemaps.org/schema/reference/transportation/types/segment/level_rule/) | a Z-order on a road segment, with an optional **linearly referenced range** (`between`) it applies to; 0 is the visual (ground) level | stacking order: level 0 above level -1, ground above tunnels |
| **OpenMapTiles** [transportation](https://openmaptiles.org/layers/transportation) | `brunnel` (`bridge` / `tunnel` / `ford`) plus a z-index | stacked bridges and tunnels need a z-index to draw correctly; the style grows about four times when it is used ([MapTiler](https://www.maptiler.com/news/2018/04/openmaptiles-3-8)) |

## 2. A real vertical coordinate (3D)

| system | what it stores | notes |
|---|---|---|
| **OpenDRIVE** ([elevation profile](https://maliput.readthedocs.io/en/latest/html/deps/maliput_malidrive/html/structmalidrive_1_1xodr_1_1_elevation_profile.html)) | `z(s)`, a cubic polynomial along the road's reference line | where roads overlap at different heights the surface height is ambiguous; OpenSCENARIO 1.3 added `verticalRoadSelection` (default 0: the top-most road) ([issue](https://gitlab.eclipse.org/eclipse/openpass/openscenario1_engine/-/issues/65)) |
| **CityGML 3.0** ([overview](https://portal.fis.tum.de/en/publications/citygml-30-new-functions-open-up-new-applications/)) | 3D geometry on every space; buildings get building units and **storeys** | the transportation module adds the section / intersection concept and links, and areas shared by several transport modes |

## 3. What this says about our model

1. **Our integer levels are the first family**: a relative stacking order, as in OSM, HERE and Overture, not an elevation. That is the
   normal choice for a map of streets. We keep the *source* of each level (`level_src`: `layer`, `bridge`, `tunnel`, `default`), which
   OSM's own guidance (use `layer` only with a structure) makes meaningful.
2. **Levels connect only at shared nodes.** In OSM, HERE and Overture, two ways at different levels are connected only where they
   share a node; crossing in plan view is **not** an intersection. This is exactly our rule: an intersection exists only at one
   level, and a connection between levels is a **link**.
3. **Where they differ from us**
   - HERE stores the level per node and Overture per range along a segment; we store it per element (an edge between junctions),
     which is enough because edges are split where anything changes.
   - HERE spans -4 … +5; we keep -2 … 2 and show anything beyond at the nearest kept level (a documented choice).
   - OSM `level` (floors inside a structure) and `layer` (crossing order) are different things; for an **object** we read `level`
     first and `layer` second as our level, which is right for a station platform and may be wrong for an odd tag.
4. **The one idea we do not have: the crossing record.** HERE keeps a table of where links cross at different levels without
   connecting. We store connections (`space.link`) but not these **grade separations**: that a bridge at level 1 passes over a
   street at level 0 between two points. A `space.stack(level_a, level_b, geometry)` of such overlaps would let the dashboard
   say what is above a street space at level 0, and it is what OpenDRIVE's "top-most road" ambiguity is about.
