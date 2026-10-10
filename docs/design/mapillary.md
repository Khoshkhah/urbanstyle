# Street-level observations from Mapillary

> **Since 2026-10-10: validation only.** Mapillary's positions are too rough to place things (street lights a median 6 m from the
> city's surveyed poles at Broadway × Granville, 20 % more than 11 m): a detection confirms an object of a source with a real
> position, builds no object, parking or stop line, and what it alone sees becomes a `check` row (`unit.CONFIRM_ONLY`). What
> follows describes the earlier use.

<p class="lead">What Mapillary's photos saw (signs, signals, street lights, parking) fills in what OpenStreetMap does not map, above all parking.</p>

Status (2026-10-08): agreed with Kaveh, built on Monaco. Code: `src/urbanstyle/mapillary.py`, used in `parts.py`.

## Why

Monaco's OpenStreetMap has 28 street lights, 22 traffic lights, no parking-lane tags and no sidewalk widths. Mapillary (street-level
photos, CC BY-SA 4.0) detects objects in its photos and places each on the map from several photos (a *map feature*, about 1-5 m off).
In Monaco: 16,000 photos (most 2017-2019, 2,900 in 2025) and, among others, 1,337 street lights, 170 parking signs, 162 no-parking /
no-stopping signs, 117 give-way and 26 stop signs, 76 traffic lights, 135 painted lane arrows. Google Street View cannot be used: its
terms forbid extracting data from it.

## How

`urbanstyle mapillary DB [--osm OSM]` fetches, for the area of a built database, the features of the groups below and every photo
position into `DB.mapillary.json` (a token from `$MAPILLARY_TOKEN` or `~/.config/mapillary/token`), and loads them as
`space.observed` (feature_id, class, grp, first_seen, last_seen, source, geometry) and `space.photo` (photo_id, captured, compass,
is_pano, sequence, geometry). `build` loads the file again when it is there; `--osm` rebuilds the parts at once. The data stays in the
local database, not in the repository.

| group | Mapillary classes | used for |
|---|---|---|
| `parking`, `no parking` | parking signs and meters; no-parking and no-stopping signs | which shoulders are parking |
| `give way`, `stop`, `traffic light` | yield and stop signs, traffic lights | stop and give-way lines at junctions |
| `street light`, `bin`, `bench` | the objects | the furnishing strip of the sidewalk |
| `lane arrow`, `zebra` | painted arrows and zebras | kept for checking SUMO's turns and the crosswalks (not used yet) |

Each feature joins the objects on the level of the nearest road.

## Parking

A **shoulder** is the strip between SUMO's outer lane and the measured kerb ([the roadway from SUMO](space-parts.md#the-roadway-from-sumo)).
What it is, first rule that holds:

1. an OSM street-parking area (`amenity=parking` with `parking=lane` or `street_side`) on it: `parking` (`source` osm);
2. an OSM motorcycle-parking point on it: `parking` (osm);
3. the nearest Mapillary parking or no-parking sign within 8 m: `parking` or `no parking` (mapillary);
4. else `shoulder`: its use is not known.

A parking or no-parking strip has an edge line along the lane. OSM parking areas inside a space and off the roadway become parts too:
`parking` (along the kerb) or `parking lot`; underground, multi-storey and rooftop ones are left out.

Monaco: 157 parking strips (111 from signs, 46 from OSM), 165 no-parking strips, 585 shoulders of unknown use, 34 parking lots. With
the signs and signals, stop lines went from 44 to 78 and give-way lines from 150 to 171; furnishing strips from 419 to 845.

## Dashboard

A focused space shows the features inside it (layer *Mapillary*, coloured by group) and its newest photos as links to Mapillary's
viewer, with the attribution "© Mapillary contributors, CC BY-SA 4.0".

## Limits

Feature positions are 1-5 m off, so a sign can be matched to the wrong side of a narrow street. A sign speaks for the whole shoulder
of that road direction, though parking often stops and starts along it. Coverage has gaps (Saint-Michel x Genets has no feature).
Widths are not measured from the photos (that needs camera poses and kerb detection, a later step).
