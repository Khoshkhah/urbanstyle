# The faces of SimReady's groups (rank 1 per group and level)

SimReady's decision D24 (Kaveh, 2026-10-27): urbanstyle's rank 1 runs after SimReady's step `grouping`, with the groups as
its input, and gives one face per group and level. SimReady's `import-kerb` reads each face's edges as bounds of the face's
level. The step is `src/urbanstyle/faces.py`, run as `urbanstyle faces DB GROUPS OUT --crs EPSG`.

## The input and the output

- DB: an urbanstyle build. The step reads its street ground at level 0 (`urban.ground`, kind `street`), the face between
  the buildings. It does not build the area again.
- GROUPS: the groups file that SimReady's build writes, one Parquet row per member: `group_id`, `kind` (`bridge`, `tunnel`,
  `roundabout`, `twin`), `level`, `carriageway_id`, `edge_ids` (the duckOSM edges of the member), `twin_carriageway_id`,
  `width_m`, `landing_start`, `landing_end`, `geometry` (the member's reference line, WKB, in the CRS of `--crs`). The
  columns are SimReady's decision of its item `P7.urbanstyle-groups`.
- OUT: the faces, one Parquet row per face: `face_id`, `group_id`, `kind`, `level`, `carriageway_id`, `method`,
  `geometry`, `edges` (the bounds). The key-value metadata holds the version of the step and of the build it read.

## The faces

- `ground` (`street_edge`): the street ground at level 0, cut at each landing.
- `bridge` (`deck_edge`), `tunnel` (`tunnel_edge`): one face per group and level: each member's line widened by half its
  width to each side, flat at a landing, round at a joint.
- `roundabout` (`ring_edge`): the ground within the reach of the ring (25 m and 1 m more), less the central island (the
  ring's centre line moved inwards by half the ring's width).
- `twin`: the line along which the ground face of a twin pair is split (the midline; on a shared reference line, the
  line itself). It is not a bound: SimReady's midline rule gives the same line ray by ray.

At a landing (a member end that the build marks), the chain's face ends on the line square to the member's end, between
the two points at half the width. The ground face loses what lies ahead of that line (within the reach and the member's
length) and gets a piece of the chain's width 5 m long behind it. The cuts come first, the pieces after, so that a short
chain keeps the ground piece of its far landing. The two faces then meet on one line with the same two edge points, and
the landing line itself is not a bound. SimReady's check `kerb-landing-gap` measures the result: on Monaco 161 of 173
landings meet; the 12 others are tubes that start at one node in two directions, or tubes side by side.

## What is left

- The ground face is the build's own (its OSM extract and its date). A build of the area with the groups from the
  start would make the ground faces of the groups in the same partition.
- A measured deck (a bridge profile from LiDAR) is not read yet; every chain face is from the width.
