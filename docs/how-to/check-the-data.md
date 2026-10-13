# Check the data

Every build can have faults: a gap between two spaces, a lane that does not meet its continuation, a guard on a lane of a bridge.
`urbanstyle check` tests the data against fixed rules and reports each fault.

## Run the checks

```bash
urbanstyle check data/monaco.duckdb
```

Each check prints one line: its id, what it tests, PASS or FAIL, and the count of faults. The command exits with 1 if a hard check
fails, so it can stop a script or a CI job.

## Check a bridge too

```bash
urbanstyle check data/units/broadway-granville.space.duckdb --bridge data/bridges-measured/granville-bridge.bridge.json
```

This adds the checks BR1 to BR11 of the bridge model: guards on lanes, holes, gaps in the guards, paths on paths, thin paths, lanes
of two axes that overlap, lanes with no arrow, steps in the deck's width or height, deck that no part covers, and a lane next to a
path with no barrier.

## Find a fault on the map

A failed check lists where its faults are. The bridge checks give links with `?at=lon,lat,zoom,pitch,bearing`. Open such a link
on the dashboard's page to go to the fault.

## Check the shape of the sections

```bash
urbanstyle quality data/monaco.duckdb
```

This reports how rectangular the sections are, and how much of each lies on a building's facade. It reports, but it does not fail.

## Related

- Every check and what it tests: [Checks](../reference/checks.md).
