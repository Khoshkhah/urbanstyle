"""The space container: buildings, street space and the links between levels, from one duckOSM database.

    urbanstyle build <duckosm.duckdb> <out.duckdb>      # then: urbanstyle dashboard <out.duckdb> <out.html>

space.element: one row per element with an integer level span [level_min, level_max].
Ground floor = level 0, upper floors positive, basement floors negative.
Buildings come from duckOSM's features.buildings (built on a copy if the database has none); roads, walkways and
cycleways from its mode schemas, rail and stations from its features. Overture is not used (docs/design/street-space.md, "Sources").
"""

import duckdb

LEVELS = (-2, 2)  # ponytail: only these levels are kept; spans are clamped to them
FLOOR_M = 3.0  # ponytail: flat 3 m/floor when only height is known; per-class heights if it matters

BUILD = f"""
CREATE SCHEMA IF NOT EXISTS space;
CREATE OR REPLACE TABLE space.element AS
SELECT 'osm' AS source, left(osm_type, 1) || osm_id AS source_id, 'building' AS type,
  CASE WHEN under THEN -coalesce(fl, ug, 1) ELSE coalesce(mn, 0) - coalesce(ug, 0) END AS level_min,
  CASE WHEN under THEN -1 ELSE coalesce(fl, round(h / {FLOOR_M})::INT, 1) - 1 + coalesce(mn, 0) END AS level_max,
  CASE WHEN fl IS NOT NULL THEN 'num_floors' WHEN h IS NOT NULL THEN 'height' ELSE 'default' END AS level_src,
  name, kind AS class, geom AS geometry,
  NULL::DOUBLE AS width_m, NULL::BIGINT AS osm_id, NULL::VARCHAR AS zone, NULL::VARCHAR AS container_id,
  NULL::BIGINT AS src, NULL::BIGINT AS dst, NULL::VARCHAR AS subtype, NULL::BOOLEAN AS oneway
FROM (SELECT *, try_cast(tags['building:levels'] AS INT) AS fl, try_cast(tags['building:levels:underground'] AS INT) AS ug,
        try_cast(tags['building:min_level'] AS INT) AS mn,
        try_cast(nullif(regexp_extract(tags['height'], '^[0-9]+([.][0-9]+)?', 0), '') AS DOUBLE) AS h,
        coalesce(tags['location'] = 'underground', false) AS under
      FROM osm.features.buildings);
"""

# ponytail: widths are lane count x 3.25 m, else a flat width per road class; use width_m from Overture/GMNS if corridors matter.
# Roads from duckOSM. A way keeps one row per direction, so dedupe on its two end nodes. A walkway is a
# walking edge no car road shares; a cycleway is a cycling edge neither share.
ROADS = """
INSERT INTO space.element
SELECT 'osm', edge_id::VARCHAR, t,
  coalesce(try_cast(layer AS INT), CASE WHEN coalesce(bridge, 'no') <> 'no' THEN 1 WHEN coalesce(tunnel, 'no') <> 'no' THEN -1 ELSE 0 END),
  coalesce(try_cast(layer AS INT), CASE WHEN coalesce(bridge, 'no') <> 'no' THEN 1 WHEN coalesce(tunnel, 'no') <> 'no' THEN -1 ELSE 0 END),
  CASE WHEN try_cast(layer AS INT) IS NOT NULL THEN 'layer' WHEN coalesce(bridge, 'no') <> 'no' THEN 'bridge'
       WHEN coalesce(tunnel, 'no') <> 'no' THEN 'tunnel' ELSE 'default' END,
  name, highway, geometry,
  CASE t WHEN 'walkway' THEN CASE highway WHEN 'pedestrian' THEN 4 WHEN 'steps' THEN 1.5 WHEN 'platform' THEN 3 ELSE 2 END
         WHEN 'cycleway' THEN 2.5
         ELSE coalesce(lanes * 3.25, CASE highway WHEN 'motorway' THEN 14 WHEN 'trunk' THEN 12 WHEN 'primary' THEN 10
              WHEN 'secondary' THEN 8 WHEN 'tertiary' THEN 7 WHEN 'service' THEN 3.5 WHEN 'living_street' THEN 5 ELSE 6 END) END,
  e.osm_id, CASE t WHEN 'walkway' THEN 'pedestrian_realm' ELSE 'travelway' END, NULL, source, target,
  CASE WHEN rw.tags['footway'] = 'crossing' OR rw.tags['highway'] = 'crossing' THEN 'crossing' WHEN rw.tags['footway'] = 'sidewalk' THEN 'sidewalk' END,
  coalesce(e.oneway, false)   -- the edge is kept in one direction only (twins are merged); arrows are right only for a genuine one-way road
FROM (
  SELECT DISTINCT ON (t, osm_id, least(source, target), greatest(source, target)) * FROM (
    SELECT 'road' t, * FROM osm.driving.edges
    UNION ALL BY NAME SELECT 'walkway' t, * FROM osm.walking.edges WHERE osm_id NOT IN (SELECT osm_id FROM osm.driving.edges)
    UNION ALL BY NAME SELECT 'cycleway' t, * FROM osm.cycling.edges
      WHERE osm_id NOT IN (SELECT osm_id FROM osm.driving.edges UNION SELECT osm_id FROM osm.walking.edges))) e
LEFT JOIN osm.raw.ways rw ON rw.osm_id = e.osm_id;
"""

CLAMP = f"""
-- roads, walkways, rail: a layer outside the kept range is shown at the nearest kept level (a metro at layer -3 sits at -2);
-- only buildings lying entirely outside are dropped
UPDATE space.element SET level_min = greatest(least(level_min, {LEVELS[1]}), {LEVELS[0]}),
                         level_max = greatest(least(level_min, {LEVELS[1]}), {LEVELS[0]}) WHERE type <> 'building';
DELETE FROM space.element WHERE level_min > {LEVELS[1]} OR level_max < {LEVELS[0]};
UPDATE space.element SET level_min = greatest(level_min, {LEVELS[0]}), level_max = least(level_max, {LEVELS[1]});
"""

# ROW hierarchy (the CityGML / IFC / OpenDRIVE pattern, docs/design/partitioning-research.md): a STREET (roads of one level that share a name and are
# connected) is divided at every junction into SECTIONS, the stretches between two intersections; the intersections are containers of their
# own, shared by the streets that meet there (space.arm). A section holds its roads, every carriageway of a dual road, and the walkways
# and cycleways that run along them (>= ALONG_MIN of their length within NEAR_M). Other containers: a PATH space (footpaths away from any
# road) and a RAIL space. Ids: s<level>-<smallest edge id> (section), p/r<level>-<smallest way id>, i<level>-<smallest node id>.
# Street space = measured cross-sections (docs/design/street-space.md): ground elements get rays every STEP_M metres to the first
# building face on each side; bridges and tunnels are the structure itself.
NEAR_M = 15
ALONG_MIN = 0.6  # share of a walkway's length that must lie within NEAR_M of a road for it to join that street
STEP_M = 3  # section spacing along a centerline
CAP_MAX_M = 25  # ponytail: reach cap is min(1.5 x width + 8, CAP_MAX_M); a section that hits no building is marked open
CORNER_REACH_M = 12  # an intersection fills the free space around its cut corners out to the building faces, at most this far from their hull
CUT_FAR_M = 200  # the half-plane beyond an arm's cut line (m) that is not the intersection
INTERSECTION_M = 4  # the smallest an intersection can be: a disc of max half-width + this around its node
BLINE_M = 3  # the building line: buildings closed by this, so a gap between two buildings narrower than twice this is frontage, not street space
FACADE_SLACK_M = 4  # a side bounded by buildings: the outline ribbon reaches this far past its (smoothed) facade line; the building line cut out of it is the edge
SMOOTH_SAMPLES = 4  # a side's measured distance is the median over this many samples (3 m apart) each way: facade steps shorter than ~2x this vanish
CROSS_MARGIN_M = 1  # an arm is cut this far beyond the edge of the crossing street
ARM_SETBACK_M = 3  # an arriving road's corner points are taken this far (plus its half-width) from the junction node
DUAL_CARRIAGEWAY_M = 40  # the two halves of a dual carriageway: one-way roads of one name, opposite directions, at most this far apart ...
DUAL_ALONGSIDE = 0.6  # ... with at least this share of the shorter-side road running alongside the other
DUAL_ANTIPARALLEL_DEG = 135  # ... and their directions at least this far apart
MERGE_NODES_M = 15  # junction nodes closer than this form one intersection (dog-legs, roundabouts, short links) ...
MERGE_DIAMETER_M = 30  # ... as long as the cluster stays this small across: a row of driveways along one street is not one intersection
SIDEWALK_HALF_M = 1.0  # a sidewalk line is 2 m wide: the kerb is this far before it
BOUND_TOL_M = 4  # a building bounds a container when its face is within this of the container's edge (the edge is smoothed a little)
PARALLEL_COS = 0.85  # a street's centerline stops a ray halfway when it runs within about 30 degrees of the ray's own street
PLAZA_CORE_M = 3  # the ribbon around an element (half-width + this) is street
PLAZA_OPEN_M = 4  # a plaza is at least twice this wide
PLAZA_MIN_M2 = 150
PLAZA_BUILT = 0.3  # share of a plaza's outline that must run along building faces
PARAPET_M = 1  # bridge/tunnel street space = centerline buffered by width/2 + this; buildings do not bound a deck
CONTAINER = """
CREATE OR REPLACE TEMP TABLE m AS SELECT rowid AS eid, level_min AS level, level_src, type, class, subtype, osm_id, source_id, oneway, name, width_m, zone, src, dst,
  ST_Transform(geometry, 'EPSG:4326', '{epsg}', always_xy := true) AS g FROM space.element WHERE type <> 'building';
CREATE OR REPLACE TEMP TABLE rbuf AS SELECT eid, level, g, ST_Buffer(g, {near}) AS bg FROM m WHERE type = 'road';
-- a walkway or cycleway runs along a road when at least ALONG_MIN of its length lies within NEAR_M of it; one that only passes close
-- (a park path, a bike path leaving the street) is not part of that street
CREATE OR REPLACE TEMP TABLE near AS SELECT eid, road_eid FROM (
  SELECT w.eid, r.eid AS road_eid, row_number() OVER (PARTITION BY w.eid ORDER BY ST_Distance(w.g, r.g)) rn
  FROM m w JOIN rbuf r ON r.level = w.level AND ST_Intersects(w.g, r.bg)
  WHERE w.type IN ('walkway', 'cycleway') AND ST_Length(ST_Intersection(w.g, r.bg)) >= {along} * ST_Length(w.g)) WHERE rn = 1;
-- STREETS-SPLIT (python fills own(eid, cid): which street or path space each element belongs to)
CREATE OR REPLACE TEMP TABLE assigned AS
SELECT m.*, own.cid, near.road_eid IS NOT NULL AS attached FROM m JOIN own USING (eid) LEFT JOIN near USING (eid);
UPDATE space.element e SET container_id = a.cid FROM assigned a WHERE e.rowid = a.eid;
CREATE OR REPLACE TEMP TABLE bm AS SELECT l AS level, source_id AS bid, ST_Transform(geometry, 'EPSG:4326', '{epsg}', always_xy := true) AS g
  FROM space.element, generate_series(level_min, level_max) t(l) WHERE type = 'building';
-- The building line bounds every section and intersection: the buildings closed by {bline} m, so a gap narrower than twice that between two
-- buildings is frontage, not street space. The closing never covers an element's own ribbon: a footpath through a passage stays open.
CREATE OR REPLACE TEMP TABLE bline AS
SELECT level, d.geom AS g FROM (
  SELECT b.level, unnest(ST_Dump(ST_MakeValid(ST_Union(b.u, CASE WHEN e.g IS NULL THEN b.c ELSE ST_Difference(b.c, e.g) END)))) AS d
  FROM (SELECT level, u, ST_MakeValid(ST_Buffer(ST_Buffer(u, {bline}), -{bline})) AS c FROM (SELECT level, ST_Union_Agg(g) AS u FROM bm GROUP BY level)) b
  LEFT JOIN (SELECT level, ST_Union_Agg(ST_Buffer(g, width_m / 2 + 0.5)) AS g FROM assigned GROUP BY level) e USING (level));
-- a sidewalk is a walkway or cycleway that runs along a road (within NEAR_M), not a crossing, steps or a passage
CREATE OR REPLACE TEMP TABLE sw AS SELECT level, g FROM assigned
WHERE type IN ('walkway', 'cycleway') AND attached AND coalesce(subtype, '') <> 'crossing'
  AND coalesce(class, '') NOT IN ('steps', 'corridor', 'platform', 'elevator');
CREATE OR REPLACE TEMP TABLE ground AS SELECT eid, cid, level, type, width_m, g, ST_Length(g) AS len,
  least(1.5 * width_m + CASE WHEN type = 'road' THEN 8 ELSE 4 END, {cap_max}) AS cap
FROM assigned WHERE level = 0 AND level_src NOT IN ('bridge', 'tunnel') AND ST_Length(g) > 0.5;
CREATE OR REPLACE TEMP TABLE pts AS
SELECT e.eid, e.cid, e.level, e.type, e.width_m, e.cap, i, ST_LineInterpolatePoint(e.g, i::DOUBLE / e.n) AS p,
  ST_LineInterpolatePoint(e.g, greatest(i::DOUBLE / e.n - 1.5 / e.len, 0)) AS pa,
  ST_LineInterpolatePoint(e.g, least(i::DOUBLE / e.n + 1.5 / e.len, 1)) AS pb
FROM (SELECT *, ceil(len / {step})::INT AS n FROM ground) e, generate_series(0, e.n) t(i);
CREATE OR REPLACE TEMP TABLE rays AS
SELECT eid, cid, level, type, width_m, cap, i, s, px, py, nx, ny,
  ST_MakeLine(ST_Point(px, py)::GEOMETRY, ST_Point(px + s * nx * cap, py + s * ny * cap)::GEOMETRY) AS ray
FROM (SELECT *, -dy / h AS nx, dx / h AS ny FROM (SELECT *, sqrt(dx * dx + dy * dy) AS h FROM
        (SELECT *, ST_X(p) AS px, ST_Y(p) AS py, ST_X(pb) - ST_X(pa) AS dx, ST_Y(pb) - ST_Y(pa) AS dy FROM pts)) WHERE h > 0),
  (VALUES (1), (-1)) v(s);
CREATE OR REPLACE TEMP TABLE hit_b AS
SELECT r.eid, r.i, r.s, min(ST_Distance(ST_Point(r.px, r.py)::GEOMETRY, TRY(ST_Intersection(r.ray, b.g)))) AS d
FROM rays r JOIN bm b ON b.level = r.level AND ST_Intersects(r.ray, b.g) GROUP BY r.eid, r.i, r.s;
-- Where two streets run side by side their corridors would overlap. Instead of a diagram, a ray stops halfway to the next street's centerline
-- when that centerline runs roughly parallel (a crossing street does not stop it): the border is then a smooth line parallel to both streets.
CREATE OR REPLACE TEMP TABLE gdir AS
SELECT eid, cid, level, g, (ST_X(ST_EndPoint(g)) - ST_X(ST_StartPoint(g))) / ST_Length(g) AS ex, (ST_Y(ST_EndPoint(g)) - ST_Y(ST_StartPoint(g))) / ST_Length(g) AS ey FROM ground;
CREATE OR REPLACE TEMP TABLE hit_m AS
SELECT r.eid, r.i, r.s, min(ST_Distance(ST_Point(r.px, r.py)::GEOMETRY, TRY(ST_Intersection(r.ray, o.g)))) / 2 AS d
FROM rays r JOIN gdir o ON o.level = r.level AND o.cid <> r.cid AND ST_Intersects(r.ray, o.g)
WHERE abs(r.ny * o.ex - r.nx * o.ey) >= {parallel} AND r.cid LIKE 's%' AND o.cid LIKE 's%' GROUP BY r.eid, r.i, r.s;   -- streets only: a path space yields to a street (rank step)
-- the halfway line counts only when no building stands between the two streets (else the building is the nearer edge anyway)
CREATE OR REPLACE TEMP TABLE hit_m AS
SELECT m.* FROM hit_m m LEFT JOIN hit_b b USING (eid, i, s) WHERE b.d IS NULL OR b.d > 2 * m.d;
CREATE OR REPLACE TEMP TABLE hit AS
SELECT eid, i, s, min(d) AS d FROM (SELECT * FROM hit_b UNION ALL SELECT * FROM hit_m) GROUP BY eid, i, s;
CREATE OR REPLACE TEMP TABLE hit_sw AS
SELECT r.eid, r.i, r.s, min(ST_Distance(ST_Point(r.px, r.py)::GEOMETRY, TRY(ST_Intersection(r.ray, w.g)))) AS d
FROM rays r JOIN sw w ON w.level = r.level AND ST_Intersects(r.ray, w.g) WHERE r.type = 'road' GROUP BY r.eid, r.i, r.s;
CREATE OR REPLACE TEMP TABLE twh AS
SELECT r.eid, r.cid, r.level, r.i, r.s, r.px, r.py, r.nx, r.ny, h.d IS NOT NULL AS kerb,
  median(CASE WHEN h.d IS NULL THEN r.width_m / 2 ELSE least(greatest(h.d - {sw_half}, 1.5), r.width_m / 2 + 6) END)
    OVER (PARTITION BY r.eid, r.s ORDER BY r.i ROWS BETWEEN 2 PRECEDING AND 2 FOLLOWING) AS h
FROM rays r LEFT JOIN hit_sw h ON h.eid = r.eid AND h.i = r.i AND h.s = r.s WHERE r.type = 'road';
CREATE OR REPLACE TEMP TABLE twsect AS
SELECT eid, level, i,
  any_value(CASE WHEN s = 1 THEN ST_Point(px + nx * h, py + ny * h)::GEOMETRY END) AS lp,
  any_value(CASE WHEN s = -1 THEN ST_Point(px - nx * h, py - ny * h)::GEOMETRY END) AS rp
FROM twh GROUP BY eid, level, i;
CREATE OR REPLACE TEMP TABLE twq AS
SELECT level, ST_Buffer(ST_MakeValid(ST_MakePolygon(ST_MakeLine([lp, lp2, rp2, rp, lp]))), 0.05) AS g
FROM (SELECT *, lead(lp) OVER w AS lp2, lead(rp) OVER w AS rp2 FROM twsect WINDOW w AS (PARTITION BY eid ORDER BY i))
WHERE lp2 IS NOT NULL;
CREATE OR REPLACE TEMP TABLE half AS
SELECT r.eid, r.cid, r.level, r.i, r.s, r.px, r.py, r.nx, r.ny, h.d IS NULL AS open,
  greatest(CASE WHEN avg((h.d IS NOT NULL)::INT) OVER (PARTITION BY r.eid, r.s) >= 0.5
                THEN median(coalesce(h.d, r.cap)) OVER (PARTITION BY r.eid, r.s ORDER BY r.i ROWS BETWEEN {smooth} PRECEDING AND {smooth} FOLLOWING)
                ELSE r.cap END, r.width_m / 2) AS h
FROM rays r LEFT JOIN hit h ON h.eid = r.eid AND h.i = r.i AND h.s = r.s;
CREATE OR REPLACE TEMP TABLE sect AS
SELECT eid, cid, level, i,
  any_value(CASE WHEN s = 1 THEN ST_Point(px + nx * h, py + ny * h)::GEOMETRY END) AS lp,
  any_value(CASE WHEN s = -1 THEN ST_Point(px - nx * h, py - ny * h)::GEOMETRY END) AS rp,
  bool_or(open) AS o, sum(h) AS w,
  least(max(CASE WHEN s = 1 THEN h END), max(CASE WHEN s = -1 THEN h END)) AS lo,
  greatest(max(CASE WHEN s = 1 THEN h END), max(CASE WHEN s = -1 THEN h END)) AS hi,
  bool_or(CASE WHEN s = 1 THEN open END) <> bool_or(CASE WHEN s = -1 THEN open END) AS o1
FROM half GROUP BY eid, cid, level, i;
-- The OUTLINE is not the measured width: a side bounded by buildings reaches {slack} m past its facade line, and the building line cut out of
-- it below is the edge itself (no samples, no smoothing); an open side reaches the cap. Neither passes halfway to a parallel street.
CREATE OR REPLACE TEMP TABLE ribh AS
SELECT r.eid, r.cid, r.level, r.i, r.s, r.px, r.py, r.nx, r.ny,
  greatest(least(CASE WHEN avg((h.d IS NOT NULL)::INT) OVER (PARTITION BY r.eid, r.s) >= 0.5 THEN f.h + {slack} ELSE r.cap END,
                 coalesce(m.d, r.cap)), r.width_m / 2) AS h
FROM rays r JOIN half f ON f.eid = r.eid AND f.i = r.i AND f.s = r.s
LEFT JOIN hit h ON h.eid = r.eid AND h.i = r.i AND h.s = r.s
LEFT JOIN hit_m m ON m.eid = r.eid AND m.i = r.i AND m.s = r.s;
CREATE OR REPLACE TEMP TABLE rsect AS
SELECT eid, cid, level, i,
  any_value(CASE WHEN s = 1 THEN ST_Point(px + nx * h, py + ny * h)::GEOMETRY END) AS lp,
  any_value(CASE WHEN s = -1 THEN ST_Point(px - nx * h, py - ny * h)::GEOMETRY END) AS rp
FROM ribh GROUP BY eid, cid, level, i;
CREATE OR REPLACE TEMP TABLE jn AS
SELECT level, node, any_value(p) AS p, max(width_m) AS w FROM (
  SELECT level, src AS node, ST_StartPoint(g) AS p, width_m FROM assigned WHERE type = 'road' AND src IS NOT NULL
  UNION ALL SELECT level, dst, ST_EndPoint(g), width_m FROM assigned WHERE type = 'road' AND dst IS NOT NULL)
GROUP BY level, node HAVING count(*) >= 3 OR (level, node) IN (SELECT level, b FROM dualnodes);
-- Intersections follow the standards' physical intersection area (docs/design/partitioning-research.md): each road arriving at a junction
-- node gives two corner points, its left and right edge at about max half-width + ARM_SETBACK_M from the node; the intersection is the
-- hull of those corners and the nodes, joined to a small disc, and junction nodes closer than MERGE_NODES_M are one intersection.
CREATE OR REPLACE TEMP TABLE arms AS
SELECT j.level, j.node, a.eid, a.source_id AS edge_id, a.cid AS street, a.osm_id, e.endpoint, ST_Length(a.g) AS len, ceil(ST_Length(a.g) / {step})::INT AS n,
  a.width_m, j.w
FROM jn j JOIN (SELECT eid, level, src AS node, 'start' AS endpoint FROM assigned WHERE type = 'road' AND src IS NOT NULL
                UNION ALL SELECT eid, level, dst, 'end' FROM assigned WHERE type = 'road' AND dst IS NOT NULL) e
  ON e.level = j.level AND e.node = j.node
JOIN assigned a ON a.eid = e.eid;
-- A street's section follows the building faces where buildings bound a side (the measured distance, lightly smoothed); a side that is mostly open
-- is one smooth parallel line at the reach. Each end is cut straight across the street at the arm's setback from the junction node: sample k from the node.
-- Where an arm is cut: on the edge of the crossing street, i.e. half the measured width of the widest OTHER arm at the node, plus {cross_margin} m
-- (never less than half the arm's own nominal width + setback, never more than half its length or 25 m). The width of an arm is what its
-- rays measured 12 to 30 m from the node (nearer, the rays run into the crossing street), else over the whole edge.
CREATE OR REPLACE TEMP TABLE armw AS
SELECT ar.level, ar.node, ar.eid, ar.endpoint, ar.len, ar.n, ar.w,
  coalesce(avg(hh.hs) FILTER (WHERE (CASE WHEN ar.endpoint = 'start' THEN hh.i * ar.len / ar.n ELSE ar.len - hh.i * ar.len / ar.n END) BETWEEN 12 AND 30), avg(hh.hs)) AS wid
FROM arms ar JOIN (SELECT eid, i, sum(h) AS hs FROM half GROUP BY eid, i) hh ON hh.eid = ar.eid GROUP BY ar.level, ar.node, ar.eid, ar.endpoint, ar.len, ar.n, ar.w;
CREATE OR REPLACE TEMP TABLE armk AS
SELECT a.*, least(greatest(round(least(greatest(coalesce(o.maxw, 0) / 2 + {cross_margin}, a.w / 2 + {setback}), a.len / 2, 25) * a.n / a.len), 1), greatest(floor(a.n / 2.0), 1))::INT AS k
FROM armw a LEFT JOIN (SELECT x.level, x.node, x.eid, max(y.wid) AS maxw FROM armw x JOIN armw y ON y.level = x.level AND y.node = x.node AND y.eid <> x.eid GROUP BY x.level, x.node, x.eid) o
  ON o.level = a.level AND o.node = a.node AND o.eid = a.eid;
CREATE OR REPLACE TEMP TABLE trim AS
SELECT eid, max(CASE WHEN endpoint = 'start' THEN k END) AS clo, min(CASE WHEN endpoint = 'end' THEN n - k END) AS chi FROM armk GROUP BY eid;
CREATE OR REPLACE TEMP TABLE quads AS
SELECT cid, level, ST_Buffer(ST_MakeValid(ST_MakePolygon(ST_MakeLine([lp, lp2, rp2, rp, lp]))), 0.05) AS g  -- 5 cm: keeps the union robust
FROM (SELECT s.*, lead(lp) OVER w AS lp2, lead(rp) OVER w AS rp2 FROM rsect s LEFT JOIN trim t USING (eid)
      WHERE (t.clo IS NULL OR s.i >= t.clo) AND (t.chi IS NULL OR s.i <= t.chi) WINDOW w AS (PARTITION BY s.eid ORDER BY s.i))
WHERE lp2 IS NOT NULL;
-- Joints: where an element continues into another (a node of degree 2, neither a junction nor a dead end), its ribbon runs on past the node
-- by its own reach, so a bend leaves no wedge on its outer side; the overlap with the next element goes in the union (same container) or
-- to the rank step below (another container).
CREATE OR REPLACE TEMP TABLE ndeg AS
SELECT level, node, count(*) AS n FROM (SELECT level, src AS node FROM ground JOIN assigned USING (eid, cid, level) WHERE src IS NOT NULL
  UNION ALL SELECT level, dst FROM ground JOIN assigned USING (eid, cid, level) WHERE dst IS NOT NULL) GROUP BY level, node;
CREATE OR REPLACE TEMP TABLE joints AS
SELECT j.cid, j.level, ST_MakeValid(ST_MakePolygon(ST_MakeLine([
    ST_Point(lx, ly), ST_Point(lx + e * tx * L, ly + e * ty * L), ST_Point(rx + e * tx * L, ry + e * ty * L), ST_Point(rx, ry), ST_Point(lx, ly)]::GEOMETRY[]))) AS g
FROM (SELECT r.eid, r.cid, r.level, CASE WHEN r.i = 0 THEN -1 ELSE 1 END AS e, any_value(r.ny) AS tx, -any_value(r.nx) AS ty, max(r.h) AS L,
        any_value(CASE WHEN r.s = 1 THEN r.px + r.nx * r.h END) AS lx, any_value(CASE WHEN r.s = 1 THEN r.py + r.ny * r.h END) AS ly,
        any_value(CASE WHEN r.s = -1 THEN r.px - r.nx * r.h END) AS rx, any_value(CASE WHEN r.s = -1 THEN r.py - r.ny * r.h END) AS ry
      FROM ribh r JOIN (SELECT eid, max(i) AS n FROM ribh GROUP BY eid) m USING (eid) WHERE r.i = 0 OR r.i = m.n GROUP BY r.eid, r.cid, r.level, r.i) j
JOIN assigned a USING (eid)
JOIN ndeg d ON d.level = j.level AND d.node = CASE WHEN j.e = -1 THEN a.src ELSE a.dst END
WHERE d.n = 2 AND (j.level, d.node) NOT IN (SELECT level, node FROM jn);
CREATE OR REPLACE TEMP TABLE quads AS SELECT cid, level, g FROM quads UNION ALL SELECT cid, level, g FROM joints;
CREATE OR REPLACE TEMP TABLE struct_e AS SELECT eid FROM assigned WHERE eid NOT IN (SELECT eid FROM ground);
CREATE OR REPLACE TEMP TABLE struct AS
SELECT cid, level, ST_Buffer(g, width_m / 2 + {parapet}) AS g FROM assigned WHERE eid NOT IN (SELECT eid FROM ground);
CREATE OR REPLACE TEMP TABLE ss0 AS
SELECT cid, level, ST_Union_Agg(g) AS g FROM quads GROUP BY cid, level;
-- The ribbons minus the building line: where buildings bound a side, the edge IS their faces. The elements' own widths are added back so a
-- footpath through an arcade survives, and only the pieces connected to the container's own elements are kept (a ribbon reaching past a thin
-- building leaves a piece behind it). Structures (a deck has no building beside it) are added after, as they are.
CREATE OR REPLACE TEMP TABLE ssp0 AS
SELECT s.cid, s.level, w.g AS wg,
  ST_CollectionExtract(ST_MakeValid(ST_Union(CASE WHEN b.g IS NULL THEN s.g ELSE ST_Difference(s.g, b.g) END, coalesce(w.g, s.g))), 3) AS g
FROM ss0 s
LEFT JOIN (SELECT cid, level, ST_Union_Agg(ST_Buffer(g, width_m / 2)) AS g FROM assigned WHERE eid NOT IN (SELECT eid FROM struct_e) GROUP BY cid, level) w USING (cid, level)
LEFT JOIN (SELECT s.cid, ST_Union_Agg(m.g) AS g FROM ss0 s JOIN bline m ON m.level = s.level AND ST_Intersects(s.g, m.g) GROUP BY s.cid) b ON b.cid = s.cid;
CREATE OR REPLACE TEMP TABLE ssp AS
SELECT cid, level, ST_Union_Agg(d.geom) AS g FROM (SELECT cid, level, wg, unnest(ST_Dump(g)) AS d FROM ssp0)
WHERE wg IS NULL OR ST_Intersects(d.geom, wg) GROUP BY cid, level;
CREATE OR REPLACE TEMP TABLE ss AS
SELECT cid, level, ST_Union_Agg(g) AS g FROM (SELECT cid, level, g FROM ssp UNION ALL SELECT cid, level, g FROM struct) GROUP BY cid, level;
-- partition (docs/design/street-space.md): street space = union of the measured pieces, minus intersections, cut by nearest
-- centerline. Everything is clipped against the few neighbouring pieces, never against one level-wide polygon (that was 9x slower).
CREATE OR REPLACE TEMP TABLE armsec AS
SELECT level, node, eid, CASE WHEN endpoint = 'start' THEN k ELSE n - k END AS i FROM armk;
CREATE OR REPLACE TEMP TABLE armpts AS
SELECT r.level, r.node, r.eid, h.px + h.s * h.nx * h.h AS x, h.py + h.s * h.ny * h.h AS y
FROM armsec r JOIN half h ON h.eid = r.eid AND h.i = r.i;
-- INTERSECTIONS-SPLIT (python fills icomp(level, cid, g) and jcluster(level, node, cid): the hull per cluster of junction nodes)
CREATE OR REPLACE TEMP TABLE inter AS
SELECT c.cid, c.level, ST_CollectionExtract(ST_MakeValid(CASE WHEN b.g IS NULL THEN c.g ELSE ST_Difference(c.g, b.g) END), 3) AS g FROM icomp c
LEFT JOIN (SELECT c2.cid, ST_Union_Agg(m.g) AS g FROM icomp c2 JOIN bline m ON m.level = c2.level AND ST_Intersects(c2.g, m.g) GROUP BY c2.cid) b ON b.cid = c.cid;
CREATE OR REPLACE TEMP TABLE inter1 AS
SELECT cid, level, g FROM (SELECT cid, level, d.geom AS g, row_number() OVER (PARTITION BY cid ORDER BY ST_Area(d.geom) DESC) AS rn
  FROM (SELECT cid, level, unnest(ST_Dump(g)) AS d FROM inter)) WHERE rn = 1;
CREATE OR REPLACE TEMP TABLE iinfo AS
SELECT c.cid, count(DISTINCT a.osm_id) AS n_road,
  array_to_string(list_slice(list_sort(list_distinct(list(a.name) FILTER (WHERE a.name IS NOT NULL))), 1, 3), ' x ') AS name
FROM icomp c JOIN assigned a ON a.level = c.level AND a.type = 'road' AND ST_Intersects(c.g, a.g) GROUP BY c.cid;
-- A container is its OWN measured corridor (ss) minus the intersections: a section is the corridor along its street, ending on the straight cuts
-- of its two intersections. Corridors of different streets no longer overlap (rays stop halfway), so there is nothing to divide.
CREATE OR REPLACE TEMP TABLE near_i AS
SELECT s.cid, ST_Union_Agg(c.g) AS g FROM ss s JOIN inter1 c ON c.level = s.level AND ST_Intersects(s.g, c.g) GROUP BY s.cid;
CREATE OR REPLACE TEMP TABLE sec0 AS
SELECT s.cid, s.level, CASE WHEN i.g IS NULL THEN s.g ELSE ST_Difference(s.g, i.g) END AS g FROM ss s LEFT JOIN near_i i USING (cid);
CREATE OR REPLACE TEMP TABLE reg AS
SELECT cid, level, CASE WHEN cid LIKE 'p%' THEN 'path' WHEN cid LIKE 'r%' THEN 'rail' ELSE 'section' END AS kind, ST_CollectionExtract(ST_MakeValid(g), 3) AS g FROM sec0
UNION ALL
SELECT cid, level, 'intersection', ST_CollectionExtract(ST_MakeValid(g), 3) FROM inter1;
DELETE FROM reg WHERE g IS NULL OR ST_IsEmpty(g) OR ST_Area(g) < 1.0;   -- slivers under 1 m2 are not containers
-- P4 (docs/design/street-space-spec.md): a container is ONE connected polygon. A region of several parts becomes one container per part: the part
-- holding the most element length keeps the id, the others get <id>.<k>; elements move to the part they lie in.
CREATE OR REPLACE TEMP TABLE parts0 AS
SELECT cid AS orig, level, kind, row_number() OVER () AS pid, d.geom AS g
FROM (SELECT cid, level, kind, unnest(ST_Dump(g)) AS d FROM reg);
CREATE OR REPLACE TEMP TABLE partlen AS
SELECT p.pid, coalesce(sum(ST_Length(ST_Intersection(a.g, p.g))), 0) AS len,
  coalesce(sum(CASE WHEN a.type = 'road' THEN ST_Length(ST_Intersection(a.g, p.g)) END), 0) AS rlen
FROM parts0 p LEFT JOIN assigned a ON a.cid = p.orig AND ST_Intersects(a.g, p.g) GROUP BY p.pid;
-- the part with the most road keeps the id; a part with no road at all is a path space, not a section; an intersection's small extra parts go
CREATE OR REPLACE TEMP TABLE reg2 AS
SELECT CASE WHEN kind = 'section' AND rlen = 0 THEN 'p' || substr(orig, 2) || '.' || (rk - 1) WHEN rk = 1 THEN orig ELSE orig || '.' || (rk - 1) END AS cid,
  orig, level, CASE WHEN kind = 'section' AND rlen = 0 THEN 'path' ELSE kind END AS kind, g FROM (
  SELECT p.*, l.rlen, row_number() OVER (PARTITION BY p.orig ORDER BY l.rlen DESC, l.len DESC, ST_Area(p.g) DESC, p.pid) AS rk
  FROM parts0 p JOIN partlen l USING (pid));
CREATE OR REPLACE TEMP TABLE reg AS SELECT * FROM reg2 WHERE ST_Area(g) >= 1.5 AND NOT (kind = 'intersection' AND cid <> orig AND ST_Area(g) < 30);
CREATE OR REPLACE TEMP TABLE reassign AS
SELECT a.eid, arg_max(p.cid, ST_Length(ST_Intersection(a.g, p.g))) AS cid
FROM assigned a JOIN reg p ON p.orig = a.cid AND p.cid <> p.orig AND ST_Intersects(a.g, p.g) GROUP BY a.eid;
UPDATE assigned SET cid = r.cid FROM reassign r WHERE assigned.eid = r.eid;
-- a part kept as a section whose roads all went to a neighbouring part (it only touched them) has no road: it is a path space
CREATE OR REPLACE TEMP TABLE norod AS
SELECT r.cid FROM reg r WHERE r.kind = 'section' AND NOT EXISTS (SELECT 1 FROM assigned a WHERE a.cid = r.cid AND a.type = 'road');
UPDATE assigned SET cid = 'p' || substr(cid, 2) WHERE cid IN (SELECT cid FROM norod);
UPDATE reg SET kind = 'path', cid = 'p' || substr(cid, 2) WHERE cid IN (SELECT cid FROM norod);
UPDATE space.element e SET container_id = a.cid FROM assigned a WHERE e.rowid = a.eid;
INSERT INTO street_of SELECT r.cid, s.street_id FROM reg r JOIN street_of s ON s.cid = r.orig WHERE r.cid <> r.orig AND r.kind = 'section';
-- a street's numbers come from its roads' sections only (a sidewalk's own short rays would dilute them); a path space uses its footpaths
CREATE OR REPLACE TEMP TABLE stat AS SELECT a.cid, avg(s.w) AS mean_width_m, avg(s.o::INT) AS open_share,
  avg(s.lo) AS narrow_half_m, avg(s.hi) AS wide_half_m, avg(s.o1::INT) AS one_side_open_share
FROM sect s JOIN assigned a ON a.eid = s.eid JOIN ground g ON g.eid = s.eid
WHERE g.type = 'road' OR NOT EXISTS (SELECT 1 FROM ground r2 JOIN assigned ra ON ra.eid = r2.eid WHERE ra.cid = a.cid AND r2.type = 'road') GROUP BY a.cid;
CREATE OR REPLACE TEMP TABLE kstat AS SELECT a.cid, avg(t.kerb::INT) AS kerb_share FROM twh t JOIN assigned a ON a.eid = t.eid GROUP BY a.cid;
-- Plaza: a wide open part of a section or path space that is framed by buildings. The ribbons around the container's own elements (half-width +
-- {plaza_core} m) are street; what is left, after opening by {plaza_open} m (so it is at least twice that wide), is a plaza when it is big enough
-- and a good share of its outline runs along building faces (open ground beside a road in a park is not a plaza).
CREATE OR REPLACE TEMP TABLE zcore AS SELECT cid, ST_Union_Agg(ST_Buffer(g, greatest(width_m / 2, 1.5) + {plaza_core})) AS g FROM assigned GROUP BY cid;
CREATE OR REPLACE TEMP TABLE zparts AS
SELECT cid AS parent, level, row_number() OVER () AS pid, d.geom AS g FROM (
  SELECT r.cid, r.level, unnest(ST_Dump(ST_Buffer(ST_Buffer(CASE WHEN c.g IS NULL THEN r.g ELSE ST_Difference(r.g, c.g) END, -{plaza_open}), {plaza_open}))) AS d
  FROM reg r LEFT JOIN zcore c USING (cid) WHERE r.kind IN ('section', 'path')) WHERE ST_Area(d.geom) >= {plaza_min};
CREATE OR REPLACE TEMP TABLE zkeep AS
SELECT p.pid, p.parent, p.level, p.g, row_number() OVER (PARTITION BY p.parent ORDER BY ST_Area(p.g) DESC) AS k FROM zparts p
JOIN (SELECT z.pid, coalesce(sum(ST_Length(ST_Intersection(ST_Boundary(z.g), ST_Buffer(b.g, 1.5)))), 0) / ST_Perimeter(z.g) AS built
      FROM zparts z LEFT JOIN bm b ON b.level = z.level AND ST_Intersects(z.g, ST_Buffer(b.g, 1.5)) GROUP BY z.pid, z.g) q USING (pid) WHERE q.built >= {plaza_built};
UPDATE reg SET g = ST_CollectionExtract(ST_MakeValid(ST_Difference(reg.g, z.g)), 3) FROM (SELECT parent, ST_Union_Agg(g) AS g FROM zkeep GROUP BY parent) z WHERE reg.cid = z.parent;
INSERT INTO reg (cid, orig, level, kind, g) SELECT 'z' || substr(parent, 2) || '.' || k, 'z' || substr(parent, 2) || '.' || k, level, 'plaza', g FROM zkeep;
-- Any residual overlap (a few m2 at most) goes to the container of the higher rank: intersection, section, path, rail; then the smaller id.
CREATE OR REPLACE TEMP TABLE rnk AS SELECT cid, level, g, CASE kind WHEN 'intersection' THEN 0 WHEN 'section' THEN 1 WHEN 'path' THEN 2 WHEN 'plaza' THEN 2 ELSE 3 END AS rk FROM reg;
CREATE OR REPLACE TEMP TABLE overl AS
SELECT a.cid, ST_Union_Agg(ST_CollectionExtract(ST_MakeValid(ST_Intersection(a.g, b.g)), 3)) AS g
FROM rnk a JOIN rnk b ON a.level = b.level AND a.cid <> b.cid AND (b.rk < a.rk OR (b.rk = a.rk AND b.cid < a.cid)) AND ST_Intersects(a.g, b.g)
GROUP BY a.cid;
UPDATE reg SET g = ST_CollectionExtract(ST_MakeValid(ST_Difference(reg.g, o.g)), 3) FROM overl o WHERE reg.cid = o.cid AND ST_Area(o.g) > 0.01;
DELETE FROM reg WHERE g IS NULL OR ST_IsEmpty(g) OR ST_Area(g) < 1.5;
-- The buildings that BOUND a container: those whose face lies along its edge (within 1 m; 4 m for an intersection, whose hull edge is a chord across each corner), at least 2 m of it. Walls and fences join later.
CREATE OR REPLACE TABLE space.boundary AS
SELECT container_id, level, 'building' AS kind, building_id, round(length_m, 1) AS length_m FROM (
  SELECT r.cid AS container_id, r.level, b.bid AS building_id, sum(ST_Length(ST_Intersection(ST_Boundary(r.g), ST_Buffer(b.g, {bound_tol})))) AS length_m
  FROM reg r JOIN bm b ON b.level = r.level AND ST_Intersects(r.g, ST_Buffer(b.g, {bound_tol})) GROUP BY r.cid, r.level, b.bid) WHERE length_m >= 2.0;
CREATE OR REPLACE TEMP TABLE rb AS SELECT level, ST_Union_Agg(g) AS g FROM (
  SELECT level, g FROM twq
  UNION ALL SELECT level, ST_Buffer(g, width_m / 2) FROM assigned WHERE type = 'road' AND eid NOT IN (SELECT eid FROM ground)) GROUP BY level;
CREATE OR REPLACE TABLE space.zone AS
SELECT container_id, level, zone, ST_MakeValid(ST_Transform(ST_MakeValid(ST_SimplifyPreserveTopology(g, 0.05)), '{epsg}', 'EPSG:4326', always_xy := true)) AS geometry
FROM (SELECT x.cid AS container_id, x.level, 'travelway' AS zone, ST_CollectionExtract(ST_MakeValid(ST_Intersection(x.g, b.g)), 3) AS g
      FROM reg x JOIN rb b USING (level) WHERE x.kind <> 'rail'
      UNION ALL
      SELECT x.cid, x.level, 'pedestrian_realm', ST_CollectionExtract(ST_MakeValid(CASE WHEN b.g IS NULL THEN x.g ELSE ST_Difference(x.g, b.g) END), 3)
      FROM reg x LEFT JOIN rb b USING (level) WHERE x.kind <> 'rail'
      UNION ALL SELECT cid, level, 'track', g FROM reg WHERE kind = 'rail')
WHERE g IS NOT NULL AND NOT ST_IsEmpty(g);
-- arm: which streets meet at which intersection. An intersection belongs to every street group that arrives at it (many-to-many, as in
-- CityGML: it is not a subsection of one street); the section is the stretch of that street that arrives.
CREATE OR REPLACE TABLE space.arm AS
SELECT DISTINCT jc.cid AS intersection_id, asg.cid AS section_id, so.street_id, a.osm_id, a.edge_id, a.node AS node_id, a.level
FROM arms a JOIN assigned asg ON asg.eid = a.eid JOIN jcluster jc ON jc.level = a.level AND jc.node = a.node LEFT JOIN street_of so ON so.cid = asg.cid;
-- dead ends: a node where only one road edge ends; counted per section
CREATE OR REPLACE TEMP TABLE deg1 AS SELECT level, node FROM (SELECT level, src AS node FROM assigned WHERE type = 'road' AND src IS NOT NULL
  UNION ALL SELECT level, dst FROM assigned WHERE type = 'road' AND dst IS NOT NULL) GROUP BY level, node HAVING count(*) = 1;
CREATE OR REPLACE TEMP TABLE deadends AS SELECT a.cid, count(DISTINCT d.node) AS n FROM assigned a
  JOIN deg1 d ON d.level = a.level AND (d.node = a.src OR d.node = a.dst) WHERE a.type = 'road' GROUP BY a.cid;
CREATE OR REPLACE TEMP TABLE cnt AS SELECT cid AS container_id, coalesce(mode(name) FILTER (WHERE type = 'road'), mode(name)) AS n, count_if(type = 'road') n_road,
  count_if(type = 'walkway') n_walkway, count_if(type = 'cycleway') n_cycleway, count_if(type = 'rail') n_rail FROM assigned GROUP BY cid;
CREATE OR REPLACE TABLE space.container AS
SELECT x.cid AS container_id, x.level, x.kind, so.street_id, ish.shape, ish.n_arms, bd.n_buildings, bd.boundary_m,
  CASE WHEN x.kind = 'section' THEN coalesce(de.n, 0) END AS n_dead_ends,
  CASE WHEN x.kind = 'section' THEN (SELECT count(DISTINCT a.intersection_id) FROM space.arm a WHERE a.section_id = x.cid) END AS n_intersections, CASE WHEN x.kind = 'intersection' THEN ii.name ELSE c.n END AS name,
  coalesce(c.n_road, ii.n_road, 0) AS n_road, coalesce(c.n_walkway, 0) AS n_walkway, coalesce(c.n_cycleway, 0) AS n_cycleway, coalesce(c.n_rail, 0) AS n_rail,
  st.mean_width_m, st.open_share, st.narrow_half_m, st.wide_half_m, st.one_side_open_share, ks.kerb_share,
  ST_MakeValid(ST_Transform(ST_MakeValid(ST_SimplifyPreserveTopology(x.g, 0.05)), '{epsg}', 'EPSG:4326', always_xy := true)) AS geometry
FROM reg x LEFT JOIN cnt c ON c.container_id = x.cid LEFT JOIN iinfo ii ON ii.cid = x.orig LEFT JOIN stat st ON st.cid = x.cid LEFT JOIN kstat ks ON ks.cid = x.cid LEFT JOIN (SELECT container_id, count(*) AS n_buildings, sum(length_m) AS boundary_m FROM space.boundary GROUP BY 1) bd ON bd.container_id = x.cid
LEFT JOIN street_of so ON so.cid = x.cid LEFT JOIN ishape ish ON ish.cid = x.orig AND x.kind = 'intersection' LEFT JOIN deadends de ON de.cid = x.cid;
-- Simplifying neighbours one by one moves a long shared edge by up to 5 cm on each side (15 m2 over 300 m): settle those overlaps on the final
-- geometries, the lower-ranked container (intersection, section, path, rail; then the larger id) giving way.
CREATE OR REPLACE TEMP TABLE crnk AS
SELECT container_id, level, geometry AS g, CASE kind WHEN 'intersection' THEN 0 WHEN 'section' THEN 1 WHEN 'path' THEN 2 WHEN 'plaza' THEN 2 ELSE 3 END AS rk FROM space.container;
CREATE OR REPLACE TEMP TABLE coverl AS
SELECT a.container_id, ST_Union_Agg(ST_CollectionExtract(ST_MakeValid(ST_Intersection(a.g, b.g)), 3)) AS g
FROM crnk a JOIN crnk b ON a.level = b.level AND a.container_id <> b.container_id
  AND (b.rk < a.rk OR (b.rk = a.rk AND b.container_id < a.container_id)) AND ST_Intersects(a.g, b.g) GROUP BY a.container_id;
UPDATE space.container c SET geometry = ST_CollectionExtract(ST_MakeValid(ST_Difference(c.geometry, o.g)), 3) FROM coverl o
WHERE c.container_id = o.container_id AND ST_Area(o.g) > 2e-11;
CREATE OR REPLACE TEMP TABLE onepart AS
SELECT container_id, geom FROM (SELECT container_id, d.geom AS geom, row_number() OVER (PARTITION BY container_id ORDER BY ST_Area(d.geom) DESC) AS rn
  FROM (SELECT container_id, unnest(ST_Dump(geometry)) AS d FROM space.container WHERE ST_NumGeometries(geometry) > 1)) WHERE rn = 1;
UPDATE space.container c SET geometry = f.geom FROM onepart f WHERE c.container_id = f.container_id;
-- simplification and the overlap step can leave a sliver: drop containers under 1 m2 (their elements are given to a neighbour below)
DELETE FROM space.container WHERE ST_IsEmpty(geometry) OR ST_Area(ST_Transform(geometry, 'EPSG:4326', '{epsg}', always_xy := true)) < 1.0;
DELETE FROM space.zone WHERE container_id NOT IN (SELECT container_id FROM space.container);
-- the zones were cut before the final overlap clean-up: clip them to the container's final shape so zones and strips add up to it
UPDATE space.zone z SET geometry = ST_CollectionExtract(ST_MakeValid(ST_Intersection(z.geometry, c.geometry)), 3) FROM space.container c WHERE c.container_id = z.container_id;
DELETE FROM space.zone WHERE geometry IS NULL OR ST_IsEmpty(geometry);
DELETE FROM space.boundary WHERE container_id NOT IN (SELECT container_id FROM space.container);
-- a street group: its sections, and the intersections it arrives at (an intersection counts for every street that meets there)
CREATE OR REPLACE TABLE space.street AS
SELECT s.street_id, s.level, mode(s.name) AS name, count(*) AS n_section,
  (SELECT count(DISTINCT a.intersection_id) FROM space.arm a WHERE a.street_id = s.street_id AND a.level = s.level) AS n_intersection
FROM space.container s WHERE s.kind = 'section' GROUP BY s.street_id, s.level;
-- a short road or footpath whose whole section was taken by an intersection (or shrank to a sliver) now belongs to that intersection
UPDATE space.element e SET container_id = i.cid
FROM (SELECT e2.rowid AS rid, min(c.container_id) AS cid FROM space.element e2
      JOIN space.container c ON c.level = e2.level_min AND c.kind = 'intersection' AND ST_Intersects(c.geometry, e2.geometry)
      WHERE e2.type <> 'building' AND e2.container_id NOT IN (SELECT container_id FROM space.container) GROUP BY e2.rowid) i
WHERE e.rowid = i.rid;
UPDATE space.element e SET container_id = n.cid
FROM (SELECT e2.rowid AS rid, arg_min(c.container_id, ST_Distance(c.geometry, e2.geometry)) AS cid FROM space.element e2
      JOIN space.container c ON c.level = e2.level_min AND ST_Intersects(ST_Buffer(e2.geometry, 0.0002), c.geometry)
      WHERE e2.type <> 'building' AND e2.container_id NOT IN (SELECT container_id FROM space.container) GROUP BY e2.rowid) n
WHERE e.rowid = n.rid;
"""


# Rail: duckOSM's features.streets (railway lines) as elements of type 'rail'. Level like roads (layer, else bridge +1, tunnel -1);
# a Unicode minus in a layer tag (U+2212) is read as a minus. src/dst are the first and last node of the way.
RAIL = """
INSERT INTO space.element
SELECT 'osm', left(s.osm_type, 1) || s.osm_id, 'rail', s.lvl, s.lvl,
  CASE WHEN s.lay IS NOT NULL THEN 'layer' WHEN coalesce(s.tags['bridge'], 'no') <> 'no' THEN 'bridge'
       WHEN coalesce(s.tags['tunnel'], 'no') <> 'no' THEN 'tunnel' ELSE 'default' END,
  s.name, s.kind, s.geom, CASE s.kind WHEN 'tram' THEN 3.0 ELSE 4.0 END, s.osm_id, 'track', NULL, w.refs[1], w.refs[-1], NULL, false
FROM (SELECT *, try_cast(replace(tags['layer'], '\u2212', '-') AS INT) AS lay,
        coalesce(try_cast(replace(tags['layer'], '\u2212', '-') AS INT),
                 CASE WHEN coalesce(tags['bridge'], 'no') <> 'no' THEN 1 WHEN coalesce(tags['tunnel'], 'no') <> 'no' THEN -1 ELSE 0 END) AS lvl
      FROM osm.features.streets
      WHERE osm_type = 'way' AND ST_GeometryType(geom) = 'LINESTRING'
        AND kind IN ('rail', 'subway', 'tram', 'light_rail', 'narrow_gauge', 'funicular', 'monorail')) s
LEFT JOIN osm.raw.ways w ON w.osm_id = s.osm_id;
"""

# Stations: points from features.public_transport. Level: an explicit level/layer tag, else the level of the nearest rail line
# within ~60 m (a station sits where its tracks are), else -1 for a subway station, else 0. 0.0008 degrees is about 60-90 m.
STATIONS = f"""
CREATE OR REPLACE TABLE space.station AS
SELECT s.id, s.name, s.kind,
  greatest(least(coalesce(s.explicit, r.lvl, CASE WHEN s.kind = 'subway' THEN -1 END, 0), {LEVELS[1]}), {LEVELS[0]}) AS level, s.geometry
FROM (SELECT left(osm_type, 1) || osm_id AS id, name,
        CASE WHEN tags['station'] IS NOT NULL THEN tags['station'] WHEN tags['subway'] = 'yes' THEN 'subway' ELSE kind END AS kind,
        coalesce(try_cast(replace(tags['level'], '\u2212', '-') AS INT), try_cast(replace(tags['layer'], '\u2212', '-') AS INT)) AS explicit,
        geom AS geometry
      FROM osm.features.public_transport WHERE kind IN ('station', 'halt', 'tram_stop')) s
LEFT JOIN LATERAL (SELECT e.level_min AS lvl FROM space.element e WHERE e.type = 'rail' AND ST_Distance(e.geometry, s.geometry) < 0.0008
                   ORDER BY ST_Distance(e.geometry, s.geometry) LIMIT 1) r ON true;
"""


# ENTRANCE_NAME_M / ENTRANCE_NEAR_M: an entrance is tied to the station with its own name within the first distance, else to the
# nearest station of its kind within the second; otherwise it stays an assumed link to level -1. An entrance counts when it lies
# on a ground-level way (within about 7 m), not only at the end of one.
ENTRANCE_NAME_M = 600
ENTRANCE_NEAR_M = 250
# Links between levels (docs/design/street-space.md, "Links"): a node where elements of two different levels meet, plus subway
# entrances (the level below is assumed: rail and stations are not loaded yet). Type: elevator / stairs / ramp (a bridge or
# tunnel is involved) / connection (a layer change on its own).
LINKS = """
CREATE OR REPLACE TABLE space.link AS
WITH ends AS (
  SELECT src AS node, level_min AS lvl, class, level_src, ST_StartPoint(geometry) AS p FROM space.element WHERE type <> 'building' AND src IS NOT NULL
  UNION ALL
  SELECT dst, level_min, class, level_src, ST_EndPoint(geometry) FROM space.element WHERE type <> 'building' AND dst IS NOT NULL),
pairs AS (
  SELECT a.node, a.lvl AS level_a, b.lvl AS level_b, any_value(a.p) AS geometry,
    bool_or(a.class = 'steps' OR b.class = 'steps') AS stairs,
    bool_or(a.level_src IN ('bridge', 'tunnel') OR b.level_src IN ('bridge', 'tunnel')) AS structure
  FROM ends a JOIN ends b ON a.node = b.node AND a.lvl < b.lvl GROUP BY a.node, a.lvl, b.lvl),
found AS (
  SELECT p.node AS node_id, p.level_a, p.level_b,
    CASE WHEN n.tags['highway'] = 'elevator' THEN 'elevator' WHEN p.stairs THEN 'stairs' WHEN p.structure THEN 'ramp' ELSE 'connection' END AS type,
    false AS assumed, p.geometry, NULL::VARCHAR AS station_id, NULL::VARCHAR AS match, NULL::DOUBLE AS dist_m
  FROM pairs p LEFT JOIN osm.raw.nodes n ON n.osm_id = p.node),
entr AS (
  SELECT n.osm_id, n.lat, n.lon, lower(n.tags['name']) AS nm, n.tags['railway'] = 'subway_entrance' AS sub, ST_Point(n.lon, n.lat)::GEOMETRY AS p
  FROM osm.raw.nodes n
  WHERE n.tags['railway'] IN ('subway_entrance', 'train_station_entrance')   -- on a level-0 way: within 0.00008 degrees (about 7 m)
    AND EXISTS (SELECT 1 FROM space.element z WHERE z.type <> 'building' AND z.level_min = 0 AND ST_Distance(z.geometry, ST_Point(n.lon, n.lat)) < 0.00008)),
cand AS (  -- a subway entrance can only serve a subway station, a train-station entrance a station that is not one
  SELECT e.osm_id AS node, s.id, s.level, lower(s.name) = e.nm AS named, ST_Distance_Sphere(ST_Point(e.lon, e.lat), s.geometry) AS d
  FROM entr e JOIN space.station s ON e.sub = (s.kind = 'subway')),
best AS (
  SELECT * FROM (SELECT *, row_number() OVER (PARTITION BY node ORDER BY named DESC, d) AS rn FROM cand
                 WHERE (named AND d <= {name_m}) OR d <= {near_m}) WHERE rn = 1)
SELECT * FROM found
UNION ALL
SELECT e.osm_id, coalesce(b.level, -1), 0, 'entrance', b.id IS NULL, e.p, b.id, CASE WHEN b.named THEN 'name' WHEN b.id IS NOT NULL THEN 'nearest' END, b.d
FROM entr e LEFT JOIN best b ON b.node = e.osm_id
WHERE coalesce(b.level, -1) < 0
  AND NOT EXISTS (SELECT 1 FROM found f WHERE f.node_id = e.osm_id AND f.level_a = coalesce(b.level, -1) AND f.level_b = 0);
"""


def junction_clusters(nodes, rings, extra=()):
    """nodes: [(level, node, x, y)] of junction nodes; rings: sets of node ids of roundabout ways. Returns ({(level, node): cluster id},
    {ids of roundabout clusters}). Junction nodes closer than MERGE_NODES_M form one cluster, and so do those of one roundabout. Id
    i<level>-<smallest node id> (a negative virtual node only if there is no real one). `extra`: (level, node, node) pairs that are one
    junction although far apart: the two halves of a dual carriageway meeting the same cross street."""
    import shapely
    from shapely import STRtree
    cid_by_node, ring_cids = {}, set()
    for level in sorted({n[0] for n in nodes}):
        ns = [n for n in nodes if n[0] == level]
        pts = shapely.points([n[2] for n in ns], [n[3] for n in ns])
        parent = list(range(len(ns)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        idx_of = {n[1]: i for i, n in enumerate(ns)}
        ring_idx = set()
        for ring in rings:
            on = [idx_of[n] for n in ring if n in idx_of]
            for i in on[1:]:
                parent[find(i)] = find(on[0])
            if len(on) >= 2:
                ring_idx.update(on)
        for lv, u, v in extra:
            if lv == level and u in idx_of and v in idx_of:
                parent[find(idx_of[u])] = find(idx_of[v])
        members = {}
        for i in range(len(ns)):
            members.setdefault(find(i), []).append(i)
        forced = {r for r, m in members.items() if len(m) > 1 or r in ring_idx}  # roundabouts and dual carriageways merge freely
        # the others: closest pairs first, while the merged cluster stays under MERGE_DIAMETER_M across
        a_idx, b_idx = STRtree(pts).query(pts, predicate="dwithin", distance=MERGE_NODES_M)
        pairs = sorted({(float(shapely.distance(pts[a], pts[b])), int(min(a, b)), int(max(a, b))) for a, b in zip(a_idx, b_idx) if a != b})
        for _, a, b in pairs:
            ra, rb = find(a), find(b)
            if ra == rb:
                continue
            both = members[ra] + members[rb]
            if ra in forced or rb in forced or max(shapely.distance(pts[i], pts[both]).max() for i in both) <= MERGE_DIAMETER_M:
                parent[ra] = rb
                members[rb] = both
                del members[ra]
                if ra in forced:
                    forced.add(rb)
        ring_roots = {find(i) for i in ring_idx}
        groups = {}
        for i in range(len(ns)):
            groups.setdefault(find(i), []).append(i)
        for root, g in groups.items():
            real = [ns[i][1] for i in g if ns[i][1] > 0]
            cid = f"i{level}-{min(real) if real else min(abs(ns[i][1]) for i in g)}"
            for i in g:
                cid_by_node[(level, ns[i][1])] = cid
            if root in ring_roots:
                ring_cids.add(cid)
    return cid_by_node, ring_cids


def street_owner(con):
    """own(eid, cid), street_of(cid, street_id) and dualnodes(level, a, b).

    STREET: the road edges of one level that share a name and are connected by a shared node (an unnamed road is its own way).
    JUNCTION NODE: a node with 3 or more road edges, or a node forced to be one by a dual carriageway (below).
    SECTION: the road edges of one street joined at nodes that are not junctions, i.e. the stretch between two junctions.
    DUAL CARRIAGEWAY (the halves of a divided road; docs/design/street-space-spec.md, section 3):
      1. pairs: two ONE-WAY road edges of one level and one name, in OPPOSITE directions (chord bearings at least DUAL_ANTIPARALLEL_DEG
         apart), within DUAL_CARRIAGEWAY_M of each other, with DUAL_ALONGSIDE of one lying within that distance of the other;
      2. a junction node of one half and the nearest end node of its partner within DUAL_CARRIAGEWAY_M are ONE junction (the cross street
         meets both halves), and that partner node becomes a junction node, so a side street on one half cuts both halves there;
      3. the section chains of the two halves that end at the same intersections are one section (merging every paired edge would
         chain through the whole stretch).
    A walkway or cycleway joins the section of its nearest road piece (see `near`); one with no road along it joins a path space, a
    connected network of such footpaths; rail lines form rail spaces.
    Ids: section = smallest edge id; street k<level>-<smallest way id>; path / rail = smallest way id."""
    import collections
    import math
    import pandas as pd
    import shapely
    from shapely import STRtree
    rows = con.execute("SELECT eid, level, type, osm_id, name, src, dst, source_id FROM m").fetchall()
    road_geo = {r[0]: r[1:] for r in con.execute("SELECT eid, ST_X(ST_StartPoint(g)), ST_Y(ST_StartPoint(g)), ST_X(ST_EndPoint(g)), ST_Y(ST_EndPoint(g)), "
                                                 "ST_AsWKB(g), oneway FROM m WHERE type = 'road'").fetchall()}
    near = dict(con.execute("SELECT eid, road_eid FROM near").fetchall())
    by_eid = {r[0]: r for r in rows}
    info = {eid: (typ, level, osm_id, sid) for eid, level, typ, osm_id, name, src, dst, sid in rows}
    degree, node_xy = collections.Counter(), {}
    for eid, level, typ, osm_id, name, src, dst, sid in rows:
        if typ == "road":
            for node, p in ((src, road_geo[eid][:2]), (dst, road_geo[eid][2:4])):
                if node is not None:
                    degree[(level, node)] += 1
                    node_xy[(level, node)] = p

    def find(p, x):
        while p.setdefault(x, x) != x:
            p[x] = p[p[x]]
            x = p[x]
        return x

    # 1. streets (and path / rail spaces)
    parent, first = {}, {}
    for eid, level, typ, osm_id, name, src, dst, sid in rows:
        if typ == "road":
            group = (level, name) if name else (level, "way", osm_id)
        elif eid not in near:
            group = (level, "rail" if typ == "rail" else "path")
        else:
            continue
        find(parent, eid)
        for node in (src, dst):
            if node is not None:
                other = first.setdefault((group, node), eid)
                if other != eid:
                    parent[find(parent, eid)] = find(parent, other)

    # 2. dual-carriageway pairs
    ids = [e for e, g in road_geo.items() if g[5] and by_eid[e][4]]
    geoms = [shapely.from_wkb(bytes(road_geo[e][4])) for e in ids]
    pairs = []
    if len(ids) > 1:
        bearing = lambda g: math.degrees(math.atan2(g.coords[-1][0] - g.coords[0][0], g.coords[-1][1] - g.coords[0][1]))
        share = lambda x, y: x.intersection(y.buffer(DUAL_CARRIAGEWAY_M)).length / max(x.length, 1e-9)
        i_idx, j_idx = STRtree(geoms).query(geoms, predicate="dwithin", distance=DUAL_CARRIAGEWAY_M)
        for i, j in zip(i_idx, j_idx):
            ri, rj = by_eid[ids[i]], by_eid[ids[j]]
            if i >= j or ri[1] != rj[1] or ri[4] != rj[4]:
                continue
            if abs((bearing(geoms[i]) - bearing(geoms[j]) + 180) % 360 - 180) < DUAL_ANTIPARALLEL_DEG:
                continue
            if max(share(geoms[i], geoms[j]), share(geoms[j], geoms[i])) >= DUAL_ALONGSIDE:
                pairs.append((ids[i], ids[j]))

    # 3. the junctions of the two halves are one junction; a junction on one half forces a junction on the other
    forced, node_pairs = set(), []
    for e, f in pairs:
        lv = by_eid[e][1]
        for a_edge, b_edge in ((e, f), (f, e)):
            b_ends = [n for n in (by_eid[b_edge][5], by_eid[b_edge][6]) if n is not None]
            for u in (by_eid[a_edge][5], by_eid[a_edge][6]):
                if u is None or degree[(lv, u)] < 3 or not b_ends:
                    continue
                v = min(b_ends, key=lambda n: math.dist(node_xy[(lv, u)], node_xy[(lv, n)]))
                if math.dist(node_xy[(lv, u)], node_xy[(lv, v)]) <= DUAL_CARRIAGEWAY_M:
                    node_pairs.append((lv, u, v))
                    if degree[(lv, v)] < 3:
                        forced.add((lv, v))
    is_junction = lambda lv, n: degree[(lv, n)] >= 3 or (lv, n) in forced

    # 4. sections: road edges of one street joined at nodes that are not junctions
    sec, sfirst = {}, {}
    for eid, level, typ, osm_id, name, src, dst, sid in rows:
        if typ != "road":
            continue
        find(sec, eid)
        for node in (src, dst):
            if node is not None and not is_junction(level, node):
                other = sfirst.setdefault((find(parent, eid), node), eid)
                if other != eid:
                    sec[find(sec, eid)] = find(sec, other)

    # 5. the chains of the two halves that end at the same intersections are one section
    rings = [set(r[0]) for r in con.execute("SELECT refs FROM osm.raw.ways WHERE tags['junction'] IN ('roundabout', 'circular')").fetchall()]
    cluster_of, _ = junction_clusters([(lv, nd, p[0], p[1]) for (lv, nd), p in node_xy.items() if is_junction(lv, nd)], rings, node_pairs)
    chains = collections.defaultdict(list)
    for eid in road_geo:
        chains[find(sec, eid)].append(eid)
    chain_of = {e: root for root, es in chains.items() for e in es}
    ends = {root: frozenset(cluster_of[(by_eid[es[0]][1], n)] for e in es for n in (by_eid[e][5], by_eid[e][6])
                            if (by_eid[es[0]][1], n) in cluster_of) for root, es in chains.items()}
    for e, f in pairs:
        ra, rb = find(sec, chain_of[e]), find(sec, chain_of[f])
        if ra != rb and ends[chain_of[e]] == ends[chain_of[f]]:
            sec[ra] = rb
            parent[find(parent, e)] = find(parent, f)
    con.execute("CREATE OR REPLACE TEMP TABLE dualnodes AS SELECT * FROM (VALUES (0, 0::BIGINT, 0::BIGINT)) t(level, a, b) WHERE false")
    if node_pairs:
        dn = pd.DataFrame(node_pairs, columns=["level", "a", "b"])
        con.execute("INSERT INTO dualnodes SELECT level::INT, a::BIGINT, b::BIGINT FROM dn")

    # 6. ids
    def num(x, default):
        try:
            return int(x)
        except (TypeError, ValueError):
            return default

    smallest_edge, smallest_way = {}, {}
    for eid in sec:
        r = find(sec, eid)
        smallest_edge[r] = min(smallest_edge.get(r, num(info[eid][3], eid)), num(info[eid][3], eid))
    for eid in parent:
        r = find(parent, eid)
        smallest_way[r] = min(smallest_way.get(r, info[eid][2]), info[eid][2])
    cid, street_of = {}, {}
    for eid in parent:
        typ, level, osm_id, sid = info[eid]
        if typ == "road":
            c = f"s{level}-{smallest_edge[find(sec, eid)]}"
            cid[eid] = c
            street_of[c] = f"k{level}-{smallest_way[find(parent, eid)]}"
        else:
            cid[eid] = f"{'r' if typ == 'rail' else 'p'}{level}-{smallest_way[find(parent, eid)]}"
    own = pd.DataFrame([(eid, cid[near.get(eid, eid)]) for eid in info], columns=["eid", "cid"])
    con.execute("CREATE OR REPLACE TEMP TABLE own AS SELECT eid::BIGINT AS eid, cid FROM own")
    st = pd.DataFrame(list(street_of.items()), columns=["cid", "street_id"])
    con.execute("CREATE OR REPLACE TEMP TABLE street_of AS SELECT cid::VARCHAR AS cid, street_id::VARCHAR AS street_id FROM st")


# Objects (docs/design/street-objects-step1.md): point objects from OSM nodes. First matching rule wins. Level = the node's level/layer tag
# (a Unicode minus counts as a minus), else 0. An object lies in the container of its level that contains it, and in that
# container's zone; outside every container it keeps NULLs and, within OBJECT_NEAR_M, the distance to the nearest one.
OBJECT_NEAR_M = 60
OBJECT_ATTRS = ("height", "material", "direction", "angle", "capacity", "lit", "covered", "surface", "ref", "level", "tactile_paving", "kerb",
                "crossing", "colour", "traffic_sign", "bin", "shelter", "bench", "amenity", "highway", "entrance", "barrier", "natural", "operator")
OBJECTS = """
CREATE OR REPLACE TABLE space.object AS
WITH c AS (
  SELECT osm_id, t, ST_Point(lon, lat)::GEOMETRY AS p,
    CASE
      WHEN t['highway'] = 'crossing' AND (t['crossing'] = 'traffic_signals' OR t['crossing:signals'] = 'yes') THEN 'crossing.signalised'
      WHEN t['highway'] = 'crossing' AND (t['crossing'] IN ('zebra', 'uncontrolled', 'marked') OR t['crossing_ref'] = 'zebra') THEN 'crossing.zebra'
      WHEN t['highway'] = 'crossing' OR t['railway'] = 'crossing' THEN 'crossing.other'
      WHEN t['highway'] = 'traffic_signals' THEN 'furniture.signal'
      WHEN t['highway'] = 'street_lamp' THEN 'furniture.lamp'
      WHEN t['traffic_sign'] IS NOT NULL OR t['traffic_sign:forward'] IS NOT NULL OR t['highway'] IN ('stop', 'give_way') THEN 'furniture.sign'
      WHEN t['highway'] = 'bus_stop' OR t['public_transport'] IN ('platform', 'stop_position') THEN 'transit.stop'
      WHEN t['amenity'] = 'shelter' THEN 'furniture.shelter'
      WHEN t['amenity'] = 'bench' OR t['leisure'] = 'picnic_table' THEN 'furniture.bench'
      WHEN t['amenity'] IN ('waste_basket', 'waste_disposal', 'recycling') THEN 'furniture.waste'
      WHEN t['amenity'] = 'bicycle_parking' THEN 'furniture.bike_parking'
      WHEN t['amenity'] IN ('vending_machine', 'ticket_validator') THEN 'furniture.vending'
      WHEN t['amenity'] = 'post_box' THEN 'furniture.post_box'
      WHEN t['amenity'] IN ('drinking_water', 'fountain') OR t['man_made'] = 'water_tap' THEN 'furniture.water'
      WHEN t['amenity'] = 'charging_station' THEN 'furniture.charging'
      WHEN t['emergency'] = 'fire_hydrant' THEN 'furniture.hydrant'
      WHEN t['advertising'] IS NOT NULL THEN 'furniture.advertising'
      WHEN t['barrier'] = 'bollard' THEN 'furniture.bollard'
      WHEN t['kerb'] IS NOT NULL OR t['barrier'] = 'kerb' THEN 'kerb.node'
      WHEN t['barrier'] IS NOT NULL THEN 'barrier.other'
      WHEN t['natural'] = 'tree' THEN 'vegetation.tree'
      WHEN t['amenity'] = 'parking_entrance' THEN 'access.parking_entrance'
      WHEN t['entrance'] IS NOT NULL THEN 'access.entrance'
    END AS class,
    greatest(least(coalesce(try_cast(regexp_extract(replace(coalesce(t['level'], t['layer'], ''), '\u2212', '-'), '-?[0-9]+', 0) AS INT), 0), {hi}), {lo}) AS level
  FROM (SELECT osm_id, lat, lon, tags AS t FROM osm.raw.nodes)),
o AS (SELECT * FROM c WHERE class IS NOT NULL),
inside AS (SELECT o.osm_id, min(ct.container_id) AS container_id
           FROM o JOIN space.container ct ON ct.level = o.level AND ST_Intersects(ct.geometry, o.p) GROUP BY o.osm_id),
zn AS (SELECT o.osm_id, min(z.zone) AS zone FROM o JOIN inside i USING (osm_id)
       JOIN space.zone z ON z.container_id = i.container_id AND ST_Intersects(z.geometry, o.p) GROUP BY o.osm_id),
near AS (SELECT o.osm_id, min(ST_Distance(ST_Transform(ct.geometry, 'EPSG:4326', '{epsg}', always_xy := true),
                                           ST_Transform(o.p, 'EPSG:4326', '{epsg}', always_xy := true))) AS d
         FROM o JOIN space.container ct ON ct.level = o.level AND ST_Intersects(ST_Buffer(o.p, 0.0012), ct.geometry)
         WHERE o.osm_id NOT IN (SELECT osm_id FROM inside) GROUP BY o.osm_id)
SELECT 'n' || o.osm_id AS object_id, o.class, o.level, i.container_id, z.zone,
  CASE WHEN i.container_id IS NULL AND n.d <= {near_m} THEN round(n.d, 1) END AS near_m, o.t['name'] AS name,
  to_json(map_from_entries(list_filter(map_entries(o.t), e -> list_contains({attrs}, e.key)))) AS attrs, 'osm' AS source, o.p AS geometry
FROM o LEFT JOIN inside i USING (osm_id) LEFT JOIN zn z USING (osm_id) LEFT JOIN near n USING (osm_id);
"""


def intersection_shapes(con):
    """icomp(level, cid, g), jcluster(level, node, cid) and ishape(cid, shape, n_arms).

    Junction nodes closer than MERGE_NODES_M (and within MERGE_DIAMETER_M across) form one cluster, and so do the junction nodes of one
    roundabout (a way tagged junction=roundabout or circular). Each road arriving at a cluster ends its section ribbon with a straight cut
    across the street, half-width + ARM_SETBACK_M from the node; the cut's two end points are the arm's corner points (`armpts`).
    The intersection is the street space between those cuts, bounded by the buildings: the free space around the nodes (at most
    CORNER_REACH_M from the hull of the nodes and corner points) with the building line cut out and everything beyond an arm's cut taken away,
    so its edges are building faces and straight cuts across the arms (the hull itself is only the fallback for very short arms). A roundabout adds its ring's width,
    a cluster with no arm keeps a small disc.
    Id: i<level>-<smallest node id>. Shape: roundabout, dogleg (several nodes), T, Y, cross or multi."""
    import math
    import pandas as pd
    import shapely
    nodes = con.execute("SELECT level, node, ST_X(p) AS x, ST_Y(p) AS y, w FROM jn ORDER BY level, node").fetchall()
    corners = {}
    for level, node, eid, x, y in con.execute("SELECT level, node, eid, x, y FROM armpts").fetchall():
        corners.setdefault((level, node), {}).setdefault(eid, []).append((x, y))
    rings = [set(r[0]) for r in con.execute("SELECT refs FROM osm.raw.ways WHERE tags['junction'] IN ('roundabout', 'circular')").fetchall()]
    extra = con.execute("SELECT level, a, b FROM dualnodes").fetchall()
    cid_by_node, ring_cids = junction_clusters([(n[0], n[1], n[2], n[3]) for n in nodes], rings, extra)
    brows = con.execute("SELECT level, ST_AsWKB(g) FROM bline").fetchall()   # the building line, as for the sections
    blevel = [r[0] for r in brows]
    bld = shapely.from_wkb([r[1] for r in brows]) if brows else []
    btree = shapely.STRtree(bld) if len(bld) else None
    inner = set()   # roads between two nodes of one cluster lie inside the intersection: they are not arms
    for eid, lv, a, b in con.execute("SELECT eid, level, src, dst FROM assigned WHERE type = 'road' AND src IS NOT NULL AND dst IS NOT NULL").fetchall():
        if cid_by_node.get((lv, a)) is not None and cid_by_node.get((lv, a)) == cid_by_node.get((lv, b)):
            inner.add(eid)
    rows, members, shapes, by_cid = [], [], [], {}
    for level, node, x, y, w in nodes:
        by_cid.setdefault(cid_by_node[(level, node)], []).append((level, node, x, y, w))
        members.append((level, node, cid_by_node[(level, node)]))
    for cid, idx in by_cid.items():
        level = idx[0][0]
        wmax = max(n[4] for n in idx)
        pts_c, bearings = [(n[2], n[3]) for n in idx], []
        for lv, node, x, y, w in idx:
            for eid, cs in corners.get((lv, node), {}).items():
                pts_c += cs
                bearings.append(math.degrees(math.atan2(sum(c[1] for c in cs) / len(cs) - y, sum(c[0] for c in cs) / len(cs) - x)) % 360)
        if len(pts_c) <= len(idx):  # no arm corners: a small disc around each node
            g = shapely.union_all([shapely.Point(n[2], n[3]).buffer(n[4] / 2 + INTERSECTION_M) for n in idx])
        else:
            ring_w = wmax / 2 if cid in ring_cids else 0.3
            hull = shapely.MultiPoint(pts_c).convex_hull.buffer(ring_w)
            reach = hull.buffer(CORNER_REACH_M)
            near = [bld[k] for k in btree.query(reach) if blevel[k] == level] if btree is not None else []
            bu = shapely.union_all(near) if near else shapely.Polygon()
            strips = []   # beyond each arm's cut, extended across the whole crossing: everything the arm's cut line leaves on the far side
            for lv, node, x, y, w in idx:
                for eid, cs in corners.get((lv, node), {}).items():
                    if len(cs) == 2 and eid not in inner:
                        (ax, ay), (bx, by) = cs
                        mx, my = (ax + bx) / 2, (ay + by) / 2
                        ux, uy = bx - ax, by - ay
                        h = math.hypot(ux, uy) or 1.0
                        ux, uy = ux / h, uy / h
                        nx, ny = -uy, ux
                        if nx * (mx - x) + ny * (my - y) < 0:
                            nx, ny = -nx, -ny        # pointing away from the node
                        L = CUT_FAR_M
                        strips.append(shapely.Polygon([(mx - ux * L, my - uy * L), (mx + ux * L, my + uy * L),
                                                       (mx + ux * L + nx * L, my + uy * L + ny * L), (mx - ux * L + nx * L, my - uy * L + ny * L)]))
            free = shapely.difference(shapely.difference(reach, bu), shapely.union_all(strips) if strips else shapely.Polygon())
            nodes_zone = shapely.union_all([shapely.Point(n[2], n[3]).buffer(1.5) for n in idx])
            parts = [p for p in shapely.get_parts(free) if p.intersects(nodes_zone)]
            g = shapely.union_all(parts) if parts else shapely.Polygon()
            if g.area < 0.5 * hull.area:   # the cuts left almost nothing around the nodes (very short arms): fall back to the hull
                g = shapely.union_all([g, shapely.difference(hull, bu)])
        rows.append((level, cid, shapely.to_wkb(shapely.make_valid(g))))
        gap = lambda a, b: abs((a - b + 180) % 360 - 180)   # angle between two bearings, 0..180
        if cid in ring_cids:
            shape = "roundabout"
        elif len(idx) > 1:
            shape = "dogleg"
        elif len(bearings) == 3:
            shape = "T" if max(gap(a, b) for a in bearings for b in bearings) >= 160 else "Y"
        elif len(bearings) == 4:
            pairs = sorted(gap(bearings[0], b) for b in bearings[1:])
            shape = "cross" if pairs[-1] >= 150 and max(gap(bearings[1], b) for b in bearings if b != bearings[1]) >= 150 else "multi"
        else:
            shape = "multi"
        shapes.append((cid, shape, len(bearings)))
    df = pd.DataFrame(rows, columns=["level", "cid", "wkb"])
    con.execute("CREATE OR REPLACE TEMP TABLE icomp AS SELECT level::INT AS level, cid::VARCHAR AS cid, ST_GeomFromWKB(wkb::BLOB) AS g FROM df")
    mem = pd.DataFrame(members, columns=["level", "node", "cid"])
    con.execute("CREATE OR REPLACE TEMP TABLE jcluster AS SELECT level::INT AS level, node::BIGINT AS node, cid::VARCHAR AS cid FROM mem")
    sh = pd.DataFrame(shapes, columns=["cid", "shape", "n_arms"])
    con.execute("CREATE OR REPLACE TEMP TABLE ishape AS SELECT cid::VARCHAR AS cid, shape::VARCHAR AS shape, n_arms::INT AS n_arms FROM sh")


def build(osm, out):
    con = duckdb.connect(out)
    con.execute("INSTALL spatial; LOAD spatial")
    con.execute(f"ATTACH '{osm}' AS osm (READ_ONLY)")
    con.execute(BUILD)
    con.execute(ROADS)
    con.execute(RAIL)
    con.execute(CLAMP)
    lon = con.execute("SELECT avg(ST_X(ST_Centroid(geometry))) FROM space.element").fetchone()[0]
    epsg = f"EPSG:{32600 + int((lon + 180) // 6) + 1}"  # northern-hemisphere UTM, metres
    fmt = dict(epsg=epsg, near=NEAR_M, along=ALONG_MIN, step=STEP_M, cap_max=CAP_MAX_M, parapet=PARAPET_M, bound_tol=BOUND_TOL_M, parallel=PARALLEL_COS, plaza_core=PLAZA_CORE_M, plaza_open=PLAZA_OPEN_M, plaza_min=PLAZA_MIN_M2, plaza_built=PLAZA_BUILT, int_margin=INTERSECTION_M, sw_half=SIDEWALK_HALF_M, setback=ARM_SETBACK_M, cross_margin=CROSS_MARGIN_M, smooth=SMOOTH_SAMPLES, bline=BLINE_M, slack=FACADE_SLACK_M)
    p1, rest = CONTAINER.split("-- STREETS-SPLIT")
    p2a, p2b = rest.split("-- INTERSECTIONS-SPLIT")
    con.execute(p1.format(**fmt))
    street_owner(con)
    con.execute(p2a.split("\n", 1)[1].format(**fmt))
    intersection_shapes(con)
    con.execute(p2b.split("\n", 1)[1].format(**fmt))
    con.execute(STATIONS)
    con.execute(LINKS.format(name_m=ENTRANCE_NAME_M, near_m=ENTRANCE_NEAR_M))
    con.execute(OBJECTS.format(lo=LEVELS[0], hi=LEVELS[1], epsg=epsg, near_m=OBJECT_NEAR_M, attrs=list(OBJECT_ATTRS)))
    from . import parts, spaces, strips, subsections  # lazy: shapely
    strips.build(con, epsg)
    subsections.build(con, epsg)   # the network-first partition (preview): roads divided into subsections, then one space each
    spaces.build(con, epsg)
    parts.build(con, epsg)         # ... and the inside of each space: parts, marks, widths
    return con


def with_features(osm, scratch):
    """The duckOSM db itself if it has a features schema, else a copy in `scratch` with the layers built from raw.*."""
    con = duckdb.connect(osm, read_only=True)
    has = con.execute("SELECT count(*) FROM information_schema.schemata WHERE schema_name = 'features'").fetchone()[0]
    con.close()
    if has:
        return osm
    import shutil
    from duckosm.features import FeaturesBuilder  # lazy: needs the duckOSM environment
    shutil.copy(osm, scratch)
    con = duckdb.connect(scratch)
    con.execute("LOAD spatial")
    FeaturesBuilder(con).run()
    con.close()
    return scratch


def counts(con, typ=None):
    """(level, n) for one element type, or (level, type, n) for all of them."""
    where = f"WHERE type = '{typ}'" if typ else ""
    cols, group = ("l, count(*)", "l") if typ else ("l, type, count(*)", "l, type")
    return con.execute(f"SELECT {cols} FROM space.element, generate_series(level_min, level_max) t(l) {where} GROUP BY {group} ORDER BY {group}").fetchall()

