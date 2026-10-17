# The division built top down, rank by rank

Status: design, 2026-10-16 evening. Kaveh: "we created the hierarchy to build the code on it; when you agreed and wrote the document,
you had to fix the code accordingly. There is no excuse." The first work after the commit of 2026-10-16: a new module, not a patch
of `network.py`.

## Why

The division of today (`network.py`) is built bottom up: the roadway of each road from OSM's lanes first, the junction shapes from
the arms, and the walking side as what is left over, shared out piece by piece. The hierarchy of `steps.md` reads the other way: rank
1 the ground, rank 2 the stretches, rank 3 the spaces, rank 4 the sides, rank 5 the parts, rank 6 the marks. Every fault reported on
2026-10-16 (a space in a block, a corner to the wrong space, a zig-zag through a median, a section with its lanes alone, a step at
every stop line) was a seam between two of the old constructions, and every fix moved the next seam. One construction in the order of
the hierarchy has no seams: each rank partitions the rank above it, by construction, and a check per rank tests the claim.

## The construction

**Rank 1, the street.** The area less the blocks and the corridors (`blocks.py`, unchanged): one polygon, the street of the level.
The sidewalk strips (OSM's sidewalk lines) lie inside it.

**Rank 2, the stretches.** From the road network, unchanged in its rules: the junction nodes (`sections.md` rules 1 to 4), the runs
chained into sections (rule 5), the connectors. Each section has an axis (its ways' lines) and two ends; each intersection has a node
cluster and its arms. Nothing is drawn yet.

**Rank 3, the spaces: one partition of the street.** Every arm of every intersection gets its stop line (the far edge of OSM's
crossing, else the core plus the reach), a cut square to the arm run across the street to the block's edge on both sides; every joint
between two subsections gets its cut the same way. The street polygon noded with all the cuts and polygonized is the partition: each
face is one space. A face lies between a junction's arm cuts: that intersection's. A face lies between two cuts along one road: that
section's (subsection's). A face with no axis in it (a widening with no lane) joins the neighbour it shares the most edge with. The
unit of rank 3 is the face, whole, corners included. Check: the spaces add up to the street exactly (U1 at 0.05 m², a new U14: the
union of the spaces is the street, gap under 1 m²).

**Rank 4, the sides.** Inside each space the kerb splits the driving side from the walking side. The kerb is, in this order: the
near side of a sidewalk strip where OSM maps the line; else the lanes' outer edge plus the strips a source gives (OSM's parking and
cycle lanes, the city's meters), the lane widths chosen or OSM's, narrowed to fit the room (the room rule); never a guess. In an
intersection the driving side is the arms' roadways joined to the stop lines with the corners at the kerb; the walking side is the
rest of the face, the corners included. A piece of the walking side that touches no block is an island of that space. `space.side`:
one row per side per space, id `<unit id>:d` / `<unit id>:w`.

**Rank 5, the parts.** Inside the driving side: the lanes (OSM's count, centred on the way's line, moved only by a merge shift),
the strips, the paved rest, the junction area, the crosswalks (OSM's crossings) and the islands. Inside the walking side: the
sidewalk strip, the furnishing band between the kerb and the strip (measured), the frontage beyond it, the driveways across it.
The parts of a side partition the side (U9 at 0.05 m²).

**Rank 6, the marks.** The kerb line (the side's border), the centre, lane, stop and give-way lines, the turn arrows and guide
lines, as today, cut to their space.

## What goes

The walking side shared out by "the roadway it touches most" and the one-partition zones of today (`sections.md` room rule 6), the
fillets of `KERB_RADIUS_M` where a sidewalk line exists, the pedestrian corner going to a section, the divided-road pairing as a
special case (two carriageways in one face between the same cuts fall into one space by construction, when their axes are one
section). `network.py` stays until the new module passes every check the old one passes; then it is removed, not kept beside.

## Tests

The places of 2026-10-16 on Vancouver: Fir Street at West 8th (the bites), Fir Street north of Broadway (the median), i0-250765180
(the corners), i0-11251856779, Pine Street s0-w1419312038/1 (a section with its lanes alone), West 10th s0-w1271599948/1 (the steps
at the stop lines), West Broadway s0-w473754701.2/2 (the frame in the block), West 8th s0-w1318007190.2/1 (the path slots). Vancouver
only, until Kaveh says Monaco ("not Monaco yet", 2026-10-16). Every check of today passes with the same or better counts; U14 is new.

## Order of work

Kaveh, 2026-10-16: "I want to test each rank one by one in Vancouver first." So one rank at a time, each built, checked, drawn and
put on the Vancouver dashboard, and judged by him before the next starts:

1. This note agreed.
2. **Rank 1** on the page as one item per level, the street polygon whole (the area less the blocks and the corridors), with the
   sidewalk strips drawn on it; check G1 to G3 as today. Judged.
3. **Rank 3**: `division.py` (new) cuts the street by the stop lines and the joints into the spaces, whole, corners included; the
   page shows the spaces alone; checks U1 (0.05 m²) and the new U14 (the spaces add up to the street). Judged.
   *First run on Vancouver, 2026-10-16 19:25 (`space.space3`, the page's layer "Spaces (rank 3, top down)" under Rank 3):* 162 stop
   lines and 18 joints cut the street into 198 faces and 154 spaces (112 sections' spaces, 42 intersections'), no two overlapping; the
   spaces add up to 183,171 m² of the street's 184,057 m². Three findings: (a) a cut clipped exactly to the street ended a float away
   from the boundary and did not node with it (162 cuts made 42 faces); each cut now passes the boundary by 1 cm. (b) 16 old sections run
   through a T junction, so their faces lie on both sides of the intersection's face: each half is its own space here (`#2`), and
   rank 2 must end every section at every junction, T junctions included. (c) 886 m² of rank 1's street, 14 pieces, hold no roadway
   (a strip between blocks with no road, the area's edge): no space can own them; either rank 1 gives them another kind or the nearest
   space takes them, Kaveh's call.
4. **Rank 4**: the kerb in each space, the driving side and the walking side (`space.side`); the page shows the sides; a check that
   the two sides partition each space. Judged.
5. **Rank 5**: the parts inside each side, with the old parts code where it fits; U9. Judged.
6. **Rank 6**: the marks. Judged.
7. `network.py` removed; `steps.md` and `sections.md` say the construction.
8. Monaco, when Kaveh says so.
