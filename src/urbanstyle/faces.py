"""Rank 1 with the groups of a SimReady build: one face per group and level (SimReady decision D24).

`urbanstyle faces DB GROUPS OUT --crs EPSG` reads the street ground of an urbanstyle build (`urban.ground`, kind
`street`, level 0) and the groups that SimReady's `grouping` step writes (GROUPS, a Parquet file, one row per
member), and writes the faces (OUT, a Parquet file) that SimReady's `import-kerb` reads as bounds:

- `ground`: the street face between the buildings at level 0, cut at each landing (below);
- `bridge`, `tunnel`: one face per structure group and level, the members' reference lines widened by half their
  width (`width_m`) to each side, with flat ends;
- `roundabout`: one face per ring: the ground face within `reach_m` + 1 m of the ring, less the central island
  (the ring's centre line moved inwards by half the ring's width, the inner lane border);
- `twin`: the line along which the ground face of a twin pair is split (the midline of the two reference lines; on
  a shared reference line, the line itself). It is a line, not a polygon, and is not a bound.

A landing is a member end that the build marks (`landing_start`, `landing_end`: the chain meets the ground there).
At a landing the chain's face ends on the cross-section line square to the member's end, between the two points at
half the width; the ground face gets a piece of the same width behind that line and loses what lies ahead of it
within `reach_m` (and within the member's length). The cuts come first and the pieces after, so that the cut of
one landing never removes the piece of another on a short chain. So the two faces meet on one line with the same two edge points, and the bound runs on across the
landing (D24). That line is not a bound: the road passes it. `edges` holds each face's bounds, the boundary less
those lines.

The groups file (GROUPS), one row per member: `group_id` BIGINT, `kind` (`bridge`, `tunnel`, `roundabout`,
`twin`), `level` INTEGER, `carriageway_id` BIGINT, `edge_ids` BIGINT[] (the duckOSM edges of the member),
`twin_carriageway_id` BIGINT, `width_m` DOUBLE, `landing_start`, `landing_end` BOOLEAN, `geometry` (WKB
LINESTRING in the CRS of `--crs`, the member's reference line in its travel direction).

The faces file (OUT): `face_id` VARCHAR, `group_id` BIGINT (NULL for the ground), `kind`, `level`, `carriageway_id`
(NULL but on a twin line), `method` (`street_edge`, `deck_edge`, `tunnel_edge`, `ring_edge`, NULL for a twin line),
`geometry` (WKB, in the CRS of `--crs`), `edges` (WKB MULTILINESTRING, the bounds). The Parquet key-value metadata
holds `urbanstyle_faces` (the version of this step) and `urbanstyle_ground` (the version of the build it read).
"""
import pathlib
import subprocess

LANDING_BACK_M = 5.0      # ponytail: the ground piece behind a landing is 5 m long; the approach's own width if it matters
LAND_EPS = 1e-6           # the landing line's half-thickness when it is cut out of a boundary
METHOD = {"bridge": "deck_edge", "tunnel": "tunnel_edge", "roundabout": "ring_edge"}


def version():
    """urbanstyle's version with the last commit of this file (`.dirty` when the file has changes)."""
    from . import __version__
    here = pathlib.Path(__file__)
    try:
        sha = subprocess.run(["git", "-C", here.parent, "log", "-1", "--format=%h", "--", here.name],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "-C", here.parent, "status", "--porcelain", "--", here.name],
                               capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        sha = dirty = ""
    return __version__ + (f"+{sha}" if sha else "") + (".dirty" if dirty else "")


def _frame(line, at_start):
    """The landing point, the unit vector into the chain and the left normal at one end of a member."""
    import numpy as np
    c = np.asarray(line.coords)
    p, q = (c[0], c[1]) if at_start else (c[-1], c[-2])
    u = (q - p) / np.hypot(*(q - p))
    return p, u, np.array([-u[1], u[0]])


def _rect(p, u, n, a0, a1, b0, b1):
    from shapely.geometry import Polygon
    return Polygon([p + a * u + b * n for a, b in ((a0, b0), (a1, b0), (a1, b1), (a0, b1))])


def _bounds(face, cuts):
    """The boundary of a face less the landing lines: a MULTILINESTRING."""
    from shapely.geometry import LineString, MultiLineString
    b = face.boundary
    if cuts:
        from shapely.ops import unary_union
        b = b.difference(unary_union([c.buffer(LAND_EPS, cap_style="flat") for c in cuts]))
    parts = [g for g in getattr(b, "geoms", [b]) if isinstance(g, LineString) and not g.is_empty]
    return MultiLineString(parts)


def _midline(a, b, step=2.0):
    """The midline of two reference lines: the midpoints of a's points and their nearest points on b."""
    from shapely.geometry import LineString
    if a.equals(LineString(b.coords[::-1])) or a.equals(b):
        return a
    pts = [a.interpolate(min(i * step, a.length)) for i in range(int(a.length // step) + 2)]
    mids = []
    for p in pts:
        q = b.interpolate(b.project(p))
        m = ((p.x + q.x) / 2, (p.y + q.y) / 2)
        if not mids or mids[-1] != m:
            mids.append(m)
    return LineString(mids) if len(mids) > 1 else a


def build(db, groups, out, crs, reach_m=25.0):
    """Write the faces file. Returns the number of faces of each kind."""
    import duckdb
    import pyarrow as pa
    import pyarrow.parquet as pq
    import shapely
    from pyproj import Transformer
    from shapely import wkb
    from shapely.geometry import LineString, Point
    from shapely.ops import polygonize, transform, unary_union

    con = duckdb.connect(str(db), read_only=True)
    con.execute("LOAD spatial")
    ground_build = con.execute("SELECT value FROM urban.meta WHERE key = 'version'").fetchone()[0] + " built " + \
        con.execute("SELECT value FROM urban.meta WHERE key = 'built'").fetchone()[0]
    pieces = [wkb.loads(bytes(r[0])) for r in con.execute(
        "SELECT ST_AsWKB(geometry) FROM urban.ground WHERE kind = 'street' AND level = 0 ORDER BY ground_id").fetchall()]
    con.close()
    to_crs = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform
    ground = unary_union([transform(to_crs, g) for g in pieces])

    rows = pq.read_table(groups).to_pylist()
    for r in rows:
        r["line"] = wkb.loads(bytes(r["geometry"]))
    out_rows = []

    # the landings: a piece of the chain's width behind the line, and the ground ahead of it removed
    adds, cuts, lines = [], [], []
    for r in rows:
        if r["kind"] not in ("bridge", "tunnel"):
            continue
        for at_start, flag in ((True, r["landing_start"]), (False, r["landing_end"])):
            if not flag:
                continue
            p, u, n = _frame(r["line"], at_start)
            w = r["width_m"] / 2
            adds.append(_rect(p, u, n, -LANDING_BACK_M, 0.0, -w, w))
            # ahead of the line, over the member's length at most: a short chain keeps the far landing's ground
            cuts.append(_rect(p, u, n, 0.0, min(reach_m, r["line"].length), -reach_m, reach_m))
            lines.append(LineString([p - w * n, p + w * n]))
    # cut first, then add the pieces behind the lines, so that no cut removes another landing's piece
    ground = unary_union([ground.difference(unary_union(cuts))] + adds) if adds else ground
    out_rows.append(dict(face_id="g0", group_id=None, kind="ground", level=0, carriageway_id=None, method="street_edge",
                         geometry=ground, edges=_bounds(ground, lines)))

    by_group = {}
    for r in rows:
        by_group.setdefault((r["group_id"], r["kind"], r["level"]), []).append(r)
    for (gid, kind, level), members in sorted(by_group.items(), key=lambda kv: (kv[0][1], kv[0][0], kv[0][2])):
        if kind in ("bridge", "tunnel"):
            parts, caps = [], []
            for m in members:
                w = m["width_m"] / 2
                parts.append(m["line"].buffer(w, cap_style="flat", join_style="mitre", mitre_limit=2.0))
                for at_start, flag in ((True, m["landing_start"]), (False, m["landing_end"])):
                    p, u, n = _frame(m["line"], at_start)
                    if flag:
                        caps.append(LineString([p - w * n, p + w * n]))
                    else:      # a joint with another member, or a free end: round, so no wedge is missing
                        parts.append(Point(p).buffer(w, quad_segs=8))
            face = unary_union(parts)
            out_rows.append(dict(face_id=f"{kind[0]}{level}-{gid}", group_id=gid, kind=kind, level=level, carriageway_id=None,
                                 method=METHOD[kind], geometry=face, edges=_bounds(face, caps)))
        elif kind == "roundabout":
            ring = unary_union([m["line"] for m in members])
            inner = max(polygonize(ring), key=lambda g: g.area, default=None)
            w = max(m["width_m"] for m in members) / 2
            face = ground.intersection(ring.buffer(reach_m + 1.0, cap_style="flat"))
            if inner is not None:
                face = unary_union([face, inner.intersection(ground)])
                island = inner.buffer(-w)
                if not island.is_empty:
                    face = face.difference(island)
            out_rows.append(dict(face_id=f"r{level}-{gid}", group_id=gid, kind=kind, level=level, carriageway_id=None,
                                 method=METHOD[kind], geometry=face, edges=_bounds(face, [])))
        elif kind == "twin":
            a, b = sorted(members, key=lambda m: m["carriageway_id"])[:2] if len(members) > 1 else (members[0], members[0])
            out_rows.append(dict(face_id=f"t{level}-{gid}", group_id=gid, kind=kind, level=level,
                                 carriageway_id=a["carriageway_id"], method=None,
                                 geometry=_midline(a["line"], b["line"]), edges=None))

    def blob(g):
        return None if g is None else shapely.to_wkb(g)
    table = pa.Table.from_pylist([{**r, "geometry": blob(r["geometry"]), "edges": blob(r["edges"])} for r in out_rows],
                                 schema=pa.schema([("face_id", pa.string()), ("group_id", pa.int64()), ("kind", pa.string()),
                                                   ("level", pa.int32()), ("carriageway_id", pa.int64()),
                                                   ("method", pa.string()), ("geometry", pa.binary()), ("edges", pa.binary())]))
    table = table.replace_schema_metadata({"urbanstyle_faces": version(), "urbanstyle_ground": ground_build, "crs": crs})
    pq.write_table(table, out)
    counts = {}
    for r in out_rows:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    return counts


def demo():
    """A self-check on one bridge with a landing at each end: the two faces meet on the landing line."""
    import numpy as np
    from shapely.geometry import LineString, Point, Polygon
    line = LineString([(0, 0), (100, 0)])
    p, u, n = _frame(line, True)
    assert np.allclose(p, (0, 0)) and np.allclose(u, (1, 0)) and np.allclose(n, (0, 1))
    ground = Polygon([(-50, -20), (150, -20), (150, 20), (-50, 20)])
    piece = _rect(p, u, n, -LANDING_BACK_M, 0, -4, 4)
    cut = _rect(p, u, n, 0, 25, -25, 25)
    g = ground.difference(cut).union(piece)
    cap = LineString([(0, -4), (0, 4)])
    edges = _bounds(g, [cap])
    assert edges.distance(Point(0, 4)) < 1e-5 and edges.distance(Point(0, -4)) < 1e-5
    assert not edges.intersects(LineString([(-1, 0), (1, 0)]))     # the road passes the landing line
    assert _midline(line, LineString([(100, 10), (0, 10)])).distance(Point(50, 5)) < 1e-9


if __name__ == "__main__":
    demo()
    print("faces: demo ok")
