"""Compare SimReady's junction areas with urbanstyle's blocks (docs/notes/scope.md).

A junction area is roadway, so no part of it can be in a block. The script gives the
area of each level-0 junction of a SimReady build that is inside urbanstyle's own blocks.

    python scripts/compare_junction_blocks.py SIMREADY_BUILD.duckdb URBANSTYLE.duckdb [MIN_M2] [NODE ...]

MIN_M2 (1.0): the smallest area in a block that is a row. NODE: OSM node ids to print always.
"""
import sys

import duckdb


def main(sim, urb, min_m2=1.0, nodes=()):
    c = duckdb.connect()
    c.sql("install spatial; load spatial")
    c.sql(f"attach '{sim}' as s (read_only); attach '{urb}' as u (read_only)")
    lon = c.sql("select avg(st_x(st_centroid(geometry))) from u.work.block").fetchone()[0]
    utm = f"EPSG:{32601 + int((lon + 180) // 6)}"  # northern hemisphere: the two pilots and Vancouver
    c.sql(f"""create table blocks as select block_id id, st_transform(geometry, 'EPSG:4326', '{utm}', true) g
              from u.work.block where level = 0""")
    c.sql("create index bi on blocks using rtree (g)")
    rows = c.sql("""
        select j.junction_id, j.node_ids, j.case_id, round(j.area_m2, 1) area_m2,
               round(sum(st_area(st_intersection(j.area, b.g))), 1) in_block_m2,
               list(distinct b.id) blocks,
               round(st_x(st_transform(st_centroid(j.area), $utm, 'EPSG:4326', true)), 6) lon,
               round(st_y(st_transform(st_centroid(j.area), $utm, 'EPSG:4326', true)), 6) lat
        from s.sim.junction j join blocks b on st_intersects(j.area, b.g)
        where j.level = 0 group by all order by in_block_m2 desc""", params={"utm": utm}).fetchall()
    total, n = c.sql("select round(sum(area_m2)), count(*) from s.sim.junction where level = 0").fetchone()
    hit = [r for r in rows if r[4] >= min_m2]
    # whole in a block: a junction of drives or aisles, which urbanstyle has no street for. SimReady keeps these
    # as roadway (its rule GD.drive-network-in-block, rejected), so they are counted apart
    whole = [r for r in hit if r[4] >= 0.9 * r[3]]
    print(f"{n} junctions at level 0, {total:.0f} m2; {len(hit)} have {min_m2} m2 or more in a block, "
          f"{sum(r[4] for r in hit):.0f} m2 in all; of these {len(whole)} are whole in a block (90 % or more), "
          f"{sum(r[4] for r in whole):.0f} m2")
    for r in rows:
        if r[4] >= min_m2 or set(r[1]) & set(nodes):
            print(f"n{','.join(map(str, r[1]))} {r[2]} area {r[3]} in_block {r[4]} at {r[6]},{r[7]} {r[5][:3]}")
    for node in set(nodes) - {x for r in rows for x in r[1]}:
        print(f"n{node}: no part in a block")


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], a[1], float(a[2]) if len(a) > 2 else 1.0, [int(x) for x in a[3:]])
