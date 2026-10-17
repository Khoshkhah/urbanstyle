# Paths: the pedestrian ways as streets of their own

Status: a trial Kaveh agreed to 2026-10-16 ("I'm not sure it works well, but let's see"). Rank 1 is built (2026-10-16): rules 1 and 2
in `blocks.py` (`path_sql`, `PATH_W`): the public pedestrian ways cut the blocks, and each way's corridor between the blocks, up to the
roads' carriageways, is `space.corridor` and the ground kind `path`; the road's street does not take it (`network.py`). Rules 3 to 6
(path sections, intersections, spaces, sides; the mouth at the sidewalk) are not built: the corridor cuts through the road's
pedestrian side to the kerb, and a square stays a plain kind.

## Today

- Only roads cut the land into blocks. The blocks and the street spaces cover the whole area.
- A footway beside a road is the sidewalk, a band of the street's walking side. It has a space, the band.
- A footway through a block, a passage, stairs, a pedestrian lane, stays inside the block: a line in `space.path` drawn over a yard,
  with no width and no space. Monaco has 3,828 walkways at level 0, many of them real pedestrian streets and the escaliers between
  its levels.
- A pedestrian area is the ground kind `square`; a corridor of footpaths that no block and no street covers is the kind `path`:
  one piece in Monaco, 80 m².

## The rule

1. **A pedestrian way cuts a block** like a road does: `highway=pedestrian`, or a footway, steps or a path, named or not (Kaveh,
   2026-10-16: a footway is a path at rank 1). Not a crossing, not a sidewalk (tagged, or running along a road inside its sidewalk
   zone over half its length: that is the street's), not a pedestrian area (`area=yes`: a square).
2. **It has a width:** OSM's `width`, else a chosen one: 4 m for a pedestrian street, 3 m for a footway, the steps' own for stairs.
   The block side runs along the way's edge, as it runs 1 m behind a sidewalk's footway today.
3. **It is a street of its own kind, a path street:** junction nodes where paths meet (3 or more ends), stretches between them,
   path sections and path intersections at rank 2, one space each at rank 3, the ground kind `path` at rank 1.
4. **One side only:** a path has the walking side; its parts are the path's surface and what OSM maps on it: steps, a ramp, a
   handrail, a bollard.
5. **Where a path meets a road street** it ends at the street's walking side: the path's width cuts through the frontage band to
   the sidewalk, as a driveway does for a service road, so the mouth is open and the path and the sidewalk touch. Where it crosses
   the road, the crossing is the street's crosswalk, as today.

6. **A square** (an area OSM maps as pedestrian, the ground kind `square` at rank 1, cut out of the blocks and the streets as
   today) is the path intersection of the path streets that arrive at it: their sections end at its edge, and the square is one
   space at rank 3 with its walking side and its parts, as a roundabout's area is a road intersection. A square no path street
   reaches stays a plain kind with no stretches. Where a square touches a road street, its edge meets the street's walking side;
   a crossing over the road is the street's crosswalk.

## What does not change

A footway along a road stays the sidewalk band. The driving side, the frames, the junctions of the roads.

## Open

- The sidewalk band's width from the footway line's distance to the kerb, where OSM maps the line, instead of the chosen 1.8 m: a
  second decision.
- Whether a path street gets a frame (one width per stretch) like a road's: yes, I think, the same rule; the sources are fewer.
- The steps between levels: a path street at two levels, with a link at each end, or the link alone. Decide on the escaliers.

## Checks

- B1, B6 and G1-G3 as today (the blocks and the ground still partition the area).
- P1: every public pedestrian way has a path space; P2: no path space overlaps a street space or a block; P3: every path mouth
  touches the sidewalk.

## Test places (Monaco)

Rue Princesse Caroline (a pedestrian street between La Condamine's blocks), an escalier between Boulevard du Jardin Exotique and
the Rock, and a passage through a block at Monte-Carlo, each on a 250 m cut, before and after, then the whole area.
