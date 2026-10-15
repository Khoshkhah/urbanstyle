# Handoff: the street at level 0, 2026-10-16

Status: written at the end of the 2026-10-15/16 session. Read `AGENTS.md` first, then this note, then `docs/design/street-rules.md`.

## Where the work stands

- Branch `network-first` and `main` are at the same commit (7d6015a). Every change of the session is committed and pushed.
- Vancouver (`data/units/broadway-granville.space.duckdb`) is built with the final code. Every rule check passes (A1-A3, J1-J2,
  X1, M1, U1-U13, G, L). The one fail, I3, is in the old container step and was there before.
- Monaco (`data/monaco.duckdb`) is built with the code of commit cc5f19c, before the island and kerb rules. Its fails are listed
  below. It must be rebuilt before anything else is done on it.
- Two servers run on this machine: Vancouver on port 8784, Monaco on port 8785. One server serves one area: its `/api/` answers
  for one database (levels, tree, search). Street View works on 8784 only, because of the key's restriction.

## The rules added this session

All in `docs/design/street-rules.md` (rules 7 to 13) and `docs/design/pipeline.md`. In short:

1. A junction arm is cut square at its stop line, never by a circle round the node (J2).
2. A node is a junction only where a road ends or two streams cross. A merge (a ramp into a road) is a joint, not a junction.
3. A section is the road between two junctions, whatever OSM ways it is made of, named by its longest way. Subsections where
   the cross-section changes.
4. Continuity at a joint: lanes that run on keep their position. The subsection's line is moved sideways by up to 2 m, OSM's
   drawing error. The kerb opposite a merging road continues. The piece at a bridge landing is the fixed one of its section.
5. Crosswalk parts for every crossing way and node, their paint from `crossing:markings` (X1).
6. Lines only between mapped lanes. The centre line of a chosen count is urbanstyle's own (M1).
7. A barrier named in a bridge's corrections continues on the ground along the landing way. The strip it runs along is an island.
8. A strip between two roadways is paved roadway, unless a kerb, an object, a path or a barrier is mapped on it. A corner touch of
   under 2 m is no contact with a block.
9. Block edges follow the footway, 1 m behind it, simplified by 0.5 m. Footways before parcels.
10. The kerb is one line per level, the roadway's outer edge, cut by the spaces, dropped at alley and driveway mouths (K2).
11. K1 reports where the kerb is far from the city's catch basins. It never moves anything.

## Corrections to OSM (data, not code)

`corrections/lanes.json`: w299511148 (3 lanes), w1210125710 (2 + 3), w1210125711 (2 + 2), read by Kaveh from the 2018 aerial
photo, with the older Granville Bridge entries. `corrections/bridges.json`: the Granville Bridge only. These are the only
place-specific inputs. The code names no place.

## Open items, in the order I would take them

1. **Monaco.** Rebuild with the current code (`build --from division`, about 10 min), then the fails of the last build, rule by rule:
   U1 12, U4/U5 4, U6 3, U8 11, U9 12, A1 6, A3 49. The A3 rise comes from the continuity shift: the check reads the OSM line with a
   0.3 m cover. Bridges: BR3 4 on Avenue de France, BR5 2 + 3 on Avenue de la Costa and Boulevard du Ténao.
2. **Lane width against a measured footway.** West of Fir Street's three southbound lanes the lanes (3 x 3.25 m, moved 1.62 m) reach
   the footway-set block edge by 0.3 m, so no sidewalk strip is left. Decide: a narrower chosen lane width, or lanes that give way
   to a measured footway. Kaveh has not decided.
3. **The part type `carriageway`.** It means "paved roadway with no lane" and uses the same word as the lanes' band. Rename it to
   `paved` in network.py, dashboard.py (PART_COLORS), checks.py, ground.py and the glossary, in one commit.
4. **The bridge landing's axis.** The bridge model straightens its axis by its own rule; the ground's drawn line differs by about
   0.7 m at the Granville ramp. The lanes are blended onto the ground over 30 m already. If a step still shows, give the landing
   the ground subsection's drawn line.
5. **Driveways.** The ground step does not cut driveways out of the sidewalk yet.
6. **Kaveh's unexplained items.** "Remove s0-w473723210/2 and i0-11251856779": that is the northbound Fir Street lane north of
   Broadway and the Broadway junction. Ask what he sees before touching them.

## How to run

```bash
P=/home/kaveh/projects/duckOSM/.venv/bin/python
# Vancouver, from the division step (about 1 min), then the checks
PYTHONPATH=src $P -m urbanstyle build data/units/broadway-granville.osm.duckdb data/units/broadway-granville.space.duckdb --from division --bridge data/bridges-measured/granville-bridge.bridge.json
PYTHONPATH=src $P -m urbanstyle check data/units/broadway-granville.space.duckdb
# the page: the CARTO key and the Street View key must be in the environment when the page is built; then the server
export CARTO_API_KEY="$(grep -o 'CARTO_API_KEY="[^"]*"' ~/.bashrc | cut -d'"' -f2)"; source ~/miniconda3/envs/roadstyle/etc/conda/activate.d/google_maps_key.sh
PYTHONPATH=src:../roadstyle/src python3 -m urbanstyle dashboard data/units/broadway-granville.space.duckdb viz/broadway-granville.html --bridge data/bridges-measured/granville-bridge.bridge.json
PYTHONPATH=src:../roadstyle/src python3 -m urbanstyle serve data/units/broadway-granville.space.duckdb viz/broadway-granville.html --bridge data/bridges-measured/granville-bridge.bridge.json --port 8784
```

Rebuild the page after every data rebuild: the page embeds the data. A stale page shows old faults.

## Things that cost hours this session

- A `pkill -f` or `pgrep -f` pattern that is also in your own command line kills your own shell (exit 144). Use a pattern with
  a bracket, `urbanstyle buil[d]`, or kill by PID.
- Long chains (build, check, page, server) must run under `setsid nohup`, else a later command kills them.
- A Python patch that asserts and fails prints nothing when its output is in a background task. Check the "PATCHED OK" line before
  building on it. Commit 41c9237 claimed a fix that was not in the file.
- `shapely.offset_curve` with a negative distance returns a reversed or empty line. Move a line by its own normals (`shift_line`).
- Two areas' pages in one `viz/` folder shared `bridge3d.json`; now each page has `<page>.bridge3d.json`.
- The Monaco division ran for hours twice: 120 m cut lines crossing each other inside the blocks (now clipped to the realm first),
  and the whole area's block edge buffered for every pedestrian piece (now indexed once). Profile with
  `faulthandler.dump_traceback_later` when a step is silent for more than its usual time.

## Review pictures

`viz/review/` (git-ignored, served at `/review/`): `vancouver-review-2026-10-15.html` (the morning review),
`vancouver-fixes-2026-10-15.html` (the first fixes, before and after), `r1015*/` (parts over the city's 2018 aerial photo, drawn by
a scratch script that reads `space.part`, `space.mark`, `space.block` and `space.unit`).
