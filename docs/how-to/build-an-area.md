# Build an area

This guide makes the street space of an area: a DuckDB file with the `urban` schema. There are two ways. `urbanstyle build` makes
a whole area from OpenStreetMap only. `urbanstyle unit` makes one junction or street in full, with a city's open data and a
timetable as well.

## Before you start

- duckOSM, to make the input database. `pip install "urbanstyle[osm]"` installs it.
- An OpenStreetMap extract (`.osm.pbf`) that covers the area, for example from Geofabrik.
- Time and memory: Monaco takes about 20 minutes and 2.5 GB. Södermalm (Stockholm) needs about 7 GB. Check the free memory before you
  build a large area.

## Make the duckOSM database

```bash
duckosm build --pbf monaco-latest.osm.pbf -o monaco.duckdb -m driving -m walking -m cycling
```

urbanstyle reads the road, walkway and cycleway networks and the `features` schema (buildings, rail, stations). If the database has
no `features` schema, `urbanstyle build` makes a copy beside the output and builds `features` from `raw.*`.

## Build a whole area

```bash
urbanstyle build monaco.duckdb data/monaco.duckdb
```

The output holds the `urban` schema: the blocks, the street spaces and their parts, the ground, the objects and the levels. The
tables are in [Tables](../reference/tables.md).

## Build one unit in full

A unit is one junction or one street section, with everything that the sources know about it.

```bash
urbanstyle unit broadway-granville --at -123.138546 49.263611 --osm vancouver_city.duckdb --vancouver \
    --gtfs https://gtfs-static.translink.ca/gtfs/google_transit.zip
```

- `--at` is a point of the junction or the street. The unit is the area around the junction nearest to it.
- `--vancouver` adds the City of Vancouver's open data: trees, lamps, parking meters, hydrants, manholes, storefronts and parcels.
- `--gtfs` adds each bus stop's routes and buses per hour from a public timetable.
- Mapillary's detections are added when a token is set (`$MAPILLARY_TOKEN` or `~/.config/mapillary/token`). They only confirm
  objects; they never make one. To skip them, add `--no-mapillary`.

The unit's files go to `data/units/`: `<name>.osm.duckdb` (the clipped OSM data), `<name>.urban.duckdb` (the street space) and
`<name>.duckdb` (the unit's summary, with its objects from every source).

## Next steps

- [Check the data](check-the-data.md).
- [Open it in the dashboard](use-the-dashboard.md).
- All the options of each command: [Commands](../reference/commands.md).
