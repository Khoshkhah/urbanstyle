# Model a bridge

A bridge is drawn from its **profile**: a JSON file with the deck's outline, its axes, their heights along the way, the lanes and
paths across each axis, and the piers. Each value names its source and method. This guide makes a profile, sets its heights, and
draws it.

## Make the profiles

The lanes come from duckOSM's GMNS export, so make it first:

```bash
duckosm gmns vancouver.duckdb --out vancouver-gmns.duckdb -m driving
urbanstyle bridge vancouver.duckdb vancouver-gmns.duckdb data/bridges --name "Granville Bridge"
```

Without `--name`, the command writes one profile for each road bridge in the database (Vancouver has 81).

## Set the heights

A new profile has heights from a rule: up from each end on the ground at 5 %, to at most 27 m. Replace them with one of these.

- **From LiDAR**, if the area has airborne LiDAR as ducklidar Parquet tiles. Run it in the conda environment `lidar`:

    ```bash
    urbanstyle bridge-measure data/bridges/granville-bridge.bridge.json data/bridges-measured --lidar tiles/*.parquet --osm vancouver.duckdb
    ```

    This measures the deck's top above the ground every 10 m along each axis.

- **From a small heights file**, if there is no LiDAR. Give a few heights per axis, or a ramp down from another axis:

    ```bash
    urbanstyle bridge-heights data/bridges/granville-bridge.bridge.json heights.json data/bridges/granville-bridge.heights.bridge.json
    ```

    The file's keys are in [Heights from a file](../design/levels.md#heights-from-a-file).

## Draw it

```bash
urbanstyle dashboard data/units/broadway-granville.urban.duckdb viz/broadway-granville.html \
    --bridge data/bridges-measured/granville-bridge.bridge.json
urbanstyle serve data/units/broadway-granville.urban.duckdb viz/broadway-granville.html \
    --bridge data/bridges-measured/granville-bridge.bridge.json
```

The bridge shows in 3D at its measured heights. In 2D it is a flat layer, with every part and its id. The model is kept in
`data/cache/`, so a second build of the page takes seconds.

## Change only the bridge

After a change to the profile or to the bridge's corrections, write only the model. The page reads it when it opens:

```bash
urbanstyle bridge3d data/units/broadway-granville.urban.duckdb viz/bridge3d.json \
    --bridge data/bridges-measured/granville-bridge.bridge.json
```

Then reload the page.

## Check it

```bash
urbanstyle check data/units/broadway-granville.urban.duckdb --bridge data/bridges-measured/granville-bridge.bridge.json
```

See [Check the data](check-the-data.md).

## Related

- The profile's fields: [The bridge profile](../design/levels.md#the-bridge-profile).
- How the 3D model is made: [The 3D model](../design/levels.md#the-3d-model).
