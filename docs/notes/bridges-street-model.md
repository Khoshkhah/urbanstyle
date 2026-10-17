# Bridges on the street model (working note, 2026-10-17, for agreement)

## The problem

Three pieces of code make the street on a bridge today:

| Level | Code | Rules |
|---|---|---|
| 0, the ground | `network.py` | the agreed street rules (`street-rules.md`, `sections.md`) |
| 1 and up, the street spaces and parts | `spaces.py`, `parts.py` | the older preview rules |
| 1 and up, the 3D bridge | `bridge3d.py` (3,300 lines) | its own lanes, junction areas, deck, guards and fills, from the profile |

The 3D bridge is a separate engine. Most of its rules are fixes for the Granville Bridge. On the Avenue de France interchange
(a spiral with three decks that cross, short ramps, a road that touches the ground in the middle of an axis) each fix made a new
fault: decks torn between two heights, guards across road ends, spikes, raised fill across a road, guards that cross each other.

## The decision

One street model for every level. A bridge is the street of its level, made by the same rules as the ground, and lifted to the
heights of its profile. The profile gives only the heights and the structure.

## The steps

1. **The division on every level.** `network.py` runs once for each level that has roads (0, 1, 2, ...), each time on the roads
   of that level only. On a deck, the street's edge is the deck's edge: OSM's `man_made=bridge` outline, else the union of the
   sections, each as wide as its lanes. Buildings, plots and a city's data do not limit a deck. The output is the same tables as
   on the ground (`unit`, `part`, `mark`, `subsection`, `junction`), with the level. `spaces.py` and `parts.py` stop making
   level 1 and up.
2. **The heights.** A new module, `deck3d.py`, lifts every part and mark of level 1 and up to its height. A point of a part takes
   the height of the profile axis its space belongs to, at its projection `s` on that axis. Where axes meet at a node, they have
   the same height there (the profile rule), so the parts meet with no step. The height rule stays as agreed: the grade, the
   clearances at crossings and over buildings, at most 12 % to the ground, 0 at every point on the ground.
3. **The structure.** `deck3d.py` also makes the deck:
   - **The slab.** One slab under each space, at that space's heights, as thick as the profile says. Two spaces that cross
     at different heights each have their own slab, so no slab joins two heights.
   - **The guards.** A guard runs along each space's outer edge, where no other space of its level touches it, as a kerb
     does on the ground. A space touches the next space at its joint, and a road end touches the road it continues as, so no
     guard ever crosses a road.
   - **The piers.** The piers come from the profile.
4. **The page.** In 3D the page draws level 1 and up from `deck3d.py` only. The flat copy of a deck at 6 m a level stops.
5. **The checks.** BR1-BR12 stay where they still apply. Three new checks:
   - no guard across the end of a lane;
   - every point on the ground at 0;
   - every crossing at its clearance, else listed as not met.
6. **The old model.** `bridge3d.py` stays until the new model passes on both test cuts. Then it is removed.

## The test

Two cuts, each built in about 2.5 minutes:

```bash
scripts/cut.sh monaco france 7.43802 43.75163
scripts/cut.sh vancouver granville -123.1366 49.2668
```

The new model passes when the checks pass on both, and when the pictures at the places Kaveh reported show no fault:

- the crossing of a1 and a3;
- the ramp ends a7 and a9;
- Boulevard du Ténao's ends;
- lane 5760949368357087765_2 a1.1 at Avenue Princesse Grace;
- the Granville Bridge's landings.

## Open questions

1. **Granville's own data.** The Granville Bridge has measured LiDAR heights and hand-checked corrections
   (`corrections/bridges.json`: a truss, a median guardrail). They stay as inputs of its profile.
2. **Paths on a deck.** Footways and cycleways on a deck follow the same path rules as on the ground (rank 1 path items, path
   spaces).
