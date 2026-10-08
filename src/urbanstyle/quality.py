"""Shape quality of sections, over a whole area (not one container at a time).

    urbanstyle quality data/monaco.duckdb [more.duckdb]

For every section with at least two bounding buildings: `facade` = share of its outline (the straight cut ends excluded by looking only at
points within 1 m of a building or farther than 1 m from one) lying on a building face (within 0.5 m); `rect` = area / area of its minimum
rotated rectangle. A section between two straight facades should have both near 1.
"""

import duckdb
import numpy as np
import shapely


def run(path):
    c = duckdb.connect(path, read_only=True)
    c.execute("LOAD spatial")
    lon = c.execute("SELECT avg(ST_X(ST_Centroid(geometry))) FROM space.container").fetchone()[0]
    t = f"ST_AsWKB(ST_Transform(geometry, 'EPSG:4326', 'EPSG:{32600 + int((lon + 180) // 6) + 1}', always_xy := true))"
    secs = c.execute(f"SELECT container_id, {t} FROM space.container WHERE kind = 'section' AND n_buildings >= 2 AND level = 0").fetchall()
    bl = shapely.from_wkb([r[0] for r in c.execute(f"SELECT {t} FROM space.element WHERE type = 'building'").fetchall()])
    tree = shapely.STRtree(bl)
    fac, rect = [], []
    for cid, w in secs:
        g = shapely.from_wkb(bytes(w))
        g = max(shapely.get_parts(g), key=lambda p: p.area)
        near = shapely.union_all(bl[tree.query(g.buffer(2))])
        edge = g.exterior
        on = edge.intersection(near.buffer(0.5)).length
        fac.append(on / edge.length)
        rect.append(g.area / shapely.minimum_rotated_rectangle(g).area)
    q = lambda a: " ".join(f"{np.percentile(a, p):.2f}" for p in (10, 25, 50, 75, 90))
    print(f"{path}: {len(secs)} sections with 2+ bounding buildings\n  facade share  p10 p25 p50 p75 p90: {q(fac)}\n  rectangularity p10 p25 p50 p75 p90: {q(rect)}")

