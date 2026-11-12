# The bridge heights on the area's ground (proposal, 2026-11-12)

Status: a proposal. Kaveh decides before any code changes.

## The task

The standard of one ground for each area (duckOSM `docs/concepts/ground-reference.md`) says that every product stands on the area's
reference ground, a bare-earth model (DTM) that duckOSM records in `main.elevation_metadata`, and names its ground id. roadstyle now
draws our bridge decks on its map. Its `z_m` is metres above that ground, and a free end of a bridge is at 0 m. Our `.bridge.json`
names no ground:

| Area | Our heights stand on | The area's reference ground |
|---|---|---|
| Monaco | "ground at the ends": a flat ground at 0 m. IGN LiDAR's ground and deck points (IGN69) are kept in the `heights` section | FABDEM V1-2, 30 m, EGM2008, ground id `3e79bae1…` (duckOSM's pass-0 build, `elevation_grid_main.parquet`) |
| Vancouver | the City's LiDAR ground under the bridge, weighted over 60 m, 0 at each landing (CGVD28) | FABDEM V1-2 (SimReady's `areas/granville/area.yaml`). Granville's pass-0 build has no grid and no ground id yet |

## FABDEM against IGN LiDAR at the Monaco bridges

FABDEM, sampled at the 32 road ends of the ten Monaco bridge profiles, against IGN LiDAR's ground there (1 m point cloud, class 2):

- the median difference is +0.68 m (a part of it is the step between EGM2008 and IGN69);
- Boulevard du Larvotto: FABDEM is 4.5 m to 7.1 m above IGN at its four ends;
- Avenue Princesse Grace and Boulevard du Ténao: FABDEM is 4.0 m to 5.8 m below IGN;
- the two small bridges w156780352 and w572934026: FABDEM is **40 m to 45 m above** IGN (one 30 m cell spans a cliff).

The script is `dtm_vs_ign.py` in the session's scratch folder; it reads the profiles and the grid only.

![Two bridges in side view](http://localhost:8784/review/bridge-ground-2026-11-12.png)

## Two simple options, and why neither works with FABDEM

- **A. The deck is FABDEM plus our height above the ground.** The deck takes every bump of the 30 m grid: on Boulevard du Larvotto it
  goes up and down between 16 m and 32 m, but the real deck is smooth. The deck agrees with the drawn terrain only.
- **B. The deck has IGN's elevations.** The deck is right in reality, but its ends are 4 m to 7 m under the drawn terrain (Larvotto)
  and 45 m under it at w572934026: on the map the deck is in the ground.

The cause is the reference ground, not the bridge profile: a 30 m grid cannot hold Monaco's streets, cliffs and decks.

## Proposal

1. **A 1 m LiDAR DTM as the reference ground of each pilot area** (duckOSM's work, another session): Monaco from IGN LiDAR HD (the
   tiles are in `simready/build/lidar-monaco`), Vancouver from the City's LiDAR 2022. The DTM must have no decks in it: IGN classes some
   decks and walls as ground (Boulevard du Larvotto: every deck point), which ended our own grid trial of 2026-10-22. duckOSM decides how
   it makes the DTM. urbanstyle sends the table above to the duckOSM session as the reason.
2. **In urbanstyle, after that:** the profile reads the ground from duckOSM (`main.elevation_grid` and `main.elevation_metadata`, or the
   same files of a pass-0 folder), names it (`"ground": {"id", "source", "product", "vertical_datum"}`), and gives every height as
   metres above it. The deck is solved in elevations (the ground at each free end, the measured deck points, the rule between them, the
   clearance over a lower road at that road's elevation), then `z_m` = deck minus ground. A free end is 0 m by construction. The
   hillside clearances (Avenue de France) then use the real slope.
3. **Until then:** no change to the heights. Every free end of the ten Monaco profiles and of Granville's is within 0.5 m of 0 m
   already (checked 2026-11-12), so roadstyle's converter has no free end to correct.

## Open questions for Kaveh

- Agree that the reference ground, not the profile, is the first fix (step 1), and that urbanstyle asks the duckOSM session for it.
- Or: use FABDEM now (option A or B) and accept its errors until a better DTM comes.
