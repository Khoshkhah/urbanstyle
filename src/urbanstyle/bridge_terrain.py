"""The ground under and round a bridge, from airborne LiDAR's ground points (docs/notes/bridge-heights.md, "A bridge on a hillside").

    urbanstyle bridge-terrain PROFILE OUT.npz --lidar TILE.copc.laz [TILE.copc.laz ...]

The class-2 (ground) points PAD_M round the axes, on a STEP_M grid in the profile's CRS: linear interpolation, and the nearest point in the
holes (under a deck, where no ground point is seen). Elevations as the tiles give them (IGN LiDAR HD: IGN69). The profile gets the key
"terrain" with the grid's path. Needs laspy, pyproj and scipy (the conda env `lidar`).
"""
import json

PAD_M = 40.0        # the grid reaches this far past the axes
STEP_M = 1.0        # the grid's cell
SEEN_M = 1.5        # a cell with a ground point this near is seen; the others are filled
TILE_CRS = 2154     # IGN LiDAR HD's tiles: Lambert-93


def write(profile, out, tiles):
    import numpy as np
    import laspy
    import pyproj
    from scipy.interpolate import griddata
    from scipy.spatial import cKDTree
    P = json.load(open(profile))
    xs = [q[0] for a in P["axes"] for q in a["line"]["value"]]
    ys = [q[1] for a in P["axes"] for q in a["line"]["value"]]
    x0, x1, y0, y1 = min(xs) - PAD_M, max(xs) + PAD_M, min(ys) - PAD_M, max(ys) + PAD_M
    to_t = pyproj.Transformer.from_crs(P["crs"], TILE_CRS, always_xy=True)
    back = pyproj.Transformer.from_crs(TILE_CRS, P["crs"], always_xy=True)
    cx, cy = to_t.transform([x0, x1, x0, x1], [y0, y0, y1, y1])
    bx0, bx1, by0, by1 = min(cx), max(cx), min(cy), max(cy)
    pts = []
    for f in tiles:
        with laspy.open(f) as fh:
            h = fh.header
            if h.maxs[0] < bx0 or h.mins[0] > bx1 or h.maxs[1] < by0 or h.mins[1] > by1:
                continue
            for ch in fh.chunk_iterator(5_000_000):
                x, y, c = np.asarray(ch.x), np.asarray(ch.y), np.asarray(ch.classification)
                m = (c == 2) & (x >= bx0) & (x <= bx1) & (y >= by0) & (y <= by1)
                if m.any():
                    pts.append(np.c_[x[m], y[m], np.asarray(ch.z)[m]])
    if not pts:
        raise SystemExit(f"{profile}: no ground point in the tiles")
    G = np.vstack(pts)
    ux, uy = back.transform(G[:, 0], G[:, 1])
    gx, gy = np.meshgrid(np.arange(x0, x1, STEP_M), np.arange(y0, y1, STEP_M))
    Z = griddata(np.c_[ux, uy], G[:, 2], (gx, gy), method="linear")
    tree = cKDTree(np.c_[ux, uy])
    hole = np.isnan(Z)
    if hole.any():
        Z[hole] = G[tree.query(np.c_[gx[hole], gy[hole]])[1], 2]
    seen = np.isfinite(tree.query(np.c_[gx.ravel(), gy.ravel()], distance_upper_bound=SEEN_M)[0]).reshape(Z.shape)
    np.savez_compressed(out, x0=x0, y0=y0, step=STEP_M, z=Z.astype(np.float32), seen=seen,
                        source="LiDAR ground points (class 2): " + ", ".join(f.split("/")[-1] for f in tiles))
    P["terrain"] = out
    json.dump(P, open(profile, "w"), indent=1)
    return f"{len(G)} ground points, grid {Z.shape}, z {Z.min():.1f} to {Z.max():.1f} m, seen {seen.mean():.0%}"
