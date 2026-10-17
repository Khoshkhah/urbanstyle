"""The data about the data (docs/design/tables.md): the manifest `urban.meta`, the registry of stable ids `urban.registry` with `uid` on
the things it knows, the style `urban.style`, the codes `urban.code` and the check rows `urban.check`. The model itself is product.py's.

    urban.meta      key, kind (build, input, chosen), value, note: the version and the date of the build, every input file with its
                    date, every chosen value (a module-level number of a build module) with its name and the comment on its line
    urban.registry  profile, uid, kind, first_seen, last_seen (requirement R6): kept from build to build
    urban.style     table, rank, kind, draw_order, form, colour, dash, raise_m: how a viewer draws each kind (docs/design/drawing.md)
    urban.code      kind, citygml, opendrive, opensidewalks, ifc: our kinds in the standards
    urban.check     check_id, kind (fault, info), status (pass, fail, info), count, what, items, checked: `urbanstyle check` writes it
"""
import ast
import datetime
import glob
import os
import subprocess

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
# the modules a build runs: their module-level numbers are the build's chosen values
BUILD_MODULES = ("container", "blocks", "buildings", "strips", "subsections", "spaces", "parts", "network", "turns", "ground", "sumo")
# the things with a profile (R6): kind -> (table, profile, which rows)
PROFILES = {      # kind -> (table, profile, which rows); `x.` is the thing's own row
    "street object": ("urban.object", "x.source || ':' || x.object_id", "TRUE"),
    "building": ("urban.element", "x.source || ':' || x.source_id", "x.kind = 'building'"),
}


# urban.style: how a viewer draws each kind (docs/design/drawing.md). Within a level the things are drawn in `draw_order`, lowest first;
# the levels are drawn from the lowest up. table, rank, kind, draw_order, form (polygon, line, point), colour, dash (metres on, off)
STYLE = [
    ("urban.area", 0, "area", 0, "polygon", "#f8fafc", None),
    ("urban.ground", 1, "plot", 10, "polygon", "#a16207", None),
    ("urban.ground", 1, "path", 11, "polygon", "#e0a96d", None),
    ("urban.ground", 1, "street", 12, "polygon", "#94a3b8", None),
    ("urban.plot_piece", 2, "yard", 20, "polygon", "#f3e9d2", None),
    ("urban.plot_piece", 2, "green", 21, "polygon", "#6cc070", None),
    ("urban.plot_piece", 2, "water", 21, "polygon", "#38bdf8", None),
    ("urban.plot_piece", 2, "alley", 22, "polygon", "#cfc8c0", None),
    ("urban.plot_piece", 2, "car park", 22, "polygon", "#22b8cf", None),
    ("urban.plot_piece", 2, "construction site", 22, "polygon", "#fcd34d", None),
    ("urban.plot_piece", 2, "square", 22, "polygon", "#fbcfe8", None),
    ("urban.plot_piece", 2, "rail", 23, "polygon", "#64748b", None),
    ("urban.plot_piece", 2, "structure", 23, "polygon", "#8b5e3c", None),
    ("urban.plot_piece", 2, "building", 24, "polygon", "#a8a29e", None),
    ("urban.stretch", 2, "section", 25, "polygon", "#bfdbfe", None),
    ("urban.stretch", 2, "path section", 25, "polygon", "#e0a96d", None),
    ("urban.stretch", 2, "intersection", 26, "polygon", "#f97316", None),
    ("urban.stretch", 2, "path intersection", 26, "polygon", "#fb923c", None),
    ("urban.space", 3, "subsection", 30, "polygon", "#bfdbfe", None),
    ("urban.space", 3, "path section", 30, "polygon", "#e0a96d", None),
    ("urban.space", 3, "intersection", 31, "polygon", "#f97316", None),
    ("urban.space", 3, "path intersection", 31, "polygon", "#fb923c", None),
    ("urban.side", 4, "walking", 40, "polygon", "#e5e7eb", None),
    ("urban.side", 4, "driving", 41, "polygon", "#6b7280", None),
    ("urban.part", 5, "frontage", 50, "polygon", "#ece6da", None),
    ("urban.part", 5, "sidewalk", 51, "polygon", "#d8d2c6", None),
    ("urban.part", 5, "furnishing", 52, "polygon", "#b9a58b", None),
    ("urban.part", 5, "verge", 52, "polygon", "#c9c4b8", None),
    ("urban.part", 5, "driveway", 53, "polygon", "#a8a29e", None),
    ("urban.part", 5, "bus stop", 54, "polygon", "#93c5fd", None),
    ("urban.part", 5, "tree pit", 54, "polygon", "#6b4f2a", None),
    ("urban.part", 5, "steps", 54, "polygon", "#5b21b6", None),
    ("urban.part", 5, "ramp", 54, "polygon", "#c4b5fd", None),
    ("urban.part", 5, "bridge deck", 55, "polygon", "#c9c4b8", None),
    ("urban.part", 5, "paved", 55, "polygon", "#4b5260", None),
    ("urban.part", 5, "shoulder", 56, "polygon", "#5c6370", None),
    ("urban.part", 5, "parking", 56, "polygon", "#64748b", None),
    ("urban.part", 5, "no parking", 56, "polygon", "#4b5260", None),
    ("urban.part", 5, "bus zone", 56, "polygon", "#7f1d1d", None),
    ("urban.part", 5, "lane", 57, "polygon", "#4b5260", None),
    ("urban.part", 5, "junction area", 57, "polygon", "#4b5260", None),
    ("urban.part", 5, "bus lane", 58, "polygon", "#9b2c2c", None),
    ("urban.part", 5, "cycle lane", 58, "polygon", "#2f855a", None),
    ("urban.part", 5, "island", 59, "polygon", "#8fbf6f", None),
    ("urban.part", 5, "crosswalk", 59, "polygon", "#6b7280", None),
    ("urban.part", 5, "cycle crossing", 59, "polygon", "#38a169", None),
    ("urban.part", 5, "handrail", 59, "line", "#6b7280", None),
    ("urban.part", 5, "bollard", 59, "point", "#6b7280", None),
    ("urban.mark", 6, "kerb", 60, "line", "#9ca3af", None),
    ("urban.mark", 6, "edge line", 61, "line", "#ffffff", None),
    ("urban.mark", 6, "lane line", 61, "line", "#ffffff", [3.0, 6.0]),
    ("urban.mark", 6, "centre line", 61, "line", "#facc15", None),
    ("urban.mark", 6, "parking line", 61, "line", "#ffffff", [1.0, 1.0]),
    ("urban.mark", 6, "stop line", 62, "line", "#ffffff", None),
    ("urban.mark", 6, "give-way line", 62, "line", "#ffffff", [0.6, 0.6]),
    ("urban.mark", 6, "crossing line", 63, "line", "#ffffff", None),
    ("urban.mark", 6, "zebra", 63, "polygon", "#ffffff", None),
    ("urban.mark", 6, "arrow", 64, "polygon", "#ffffff", None),
    ("urban.mark", 6, "guide line", 65, "line", "#f59e0b", [0.2, 0.8]),
    ("urban.mark", 6, "barrier", 66, "line", "#6b7280", None),
    ("urban.object", None, "furniture", 70, "point", "#4f46e5", None),
    ("urban.object", None, "vegetation", 70, "point", "#16a34a", None),
    ("urban.object", None, "utility", 70, "point", "#6b7280", None),
    ("urban.object", None, "transit", 70, "point", "#0891b2", None),
    ("urban.object", None, "access", 70, "point", "#db2777", None),
    ("urban.object", None, "barrier", 70, "point", "#78350f", None),
    ("urban.link", None, "link", 80, "point", "#7c3aed", None),
]


# urban.code: our kinds with their codes in the standards (docs/design/tables.md, "The codes of the standards"): kind, CityGML 3.0,
# OpenDRIVE 1.9, OpenSidewalks, IFC 4.3; None where the standard has no code
_C = [
    (("named street",), "Road", "the roads of one name", None, "IfcRoad"),
    (("section", "subsection"), "Section", "road, lane section", None, "IfcRoadPart ROADSEGMENT"),
    (("intersection",), "Intersection", "junction", "node", "IfcRoadPart INTERSECTION"),
    (("lane",), "TrafficSpace granularity=lane; TrafficArea", "lane type=driving", None, "TRAFFICLANE"),
    (("bus lane",), "TrafficSpace usage=bus", "lane type=bus", None, "TRAFFICLANE"),
    (("cycle lane", "cycle crossing"), "TrafficSpace usage=bicycle", "lane type=biking", None, "TRAFFICLANE"),
    (("shoulder",), "AuxiliaryTrafficSpace", "lane type=shoulder", None, "SHOULDER"),
    (("parking", "no parking", "bus zone"), "AuxiliaryTrafficSpace", "lane type=parking", None, "PARKINGBAY"),
    (("paved", "junction area"), "TrafficSpace", "lane type=driving", None, "TRAFFICLANE"),
    (("island",), "AuxiliaryTrafficSpace", "lane type=median", "traffic island edge", "TRAFFICISLAND"),
    (("sidewalk", "furnishing", "frontage"), "TrafficSpace function=sidewalk", "lane type=walking", "sidewalk edge", "SIDEWALK"),
    (("driveway",), "TrafficSpace function=driveway", "lane type=walking", "sidewalk edge", "SIDEWALK"),
    (("crosswalk",), "TrafficSpace; Marking", "crossPath; object crosswalk", "crossing edge", "PEDESTRIAN_CROSSING"),
    (("bridge deck",), "BridgePart", "object bridge", None, "IfcBridgePart DECK"),
    (("kerb",), "AuxiliaryTrafficArea", "lane type=curb", "kerb node", "IfcKerb"),
    (("lane line", "centre line", "edge line", "parking line"), "Marking", "roadMark", None, "IfcSurfaceFeature"),
    (("stop line", "give-way line", "zebra", "crossing line", "arrow", "guide line"), "Marking", "roadMark; object", None, "IfcSurfaceFeature"),
    (("barrier",), "AuxiliaryTrafficArea", "object barrier", None, "IfcRailing"),
    (("street object",), "CityFurniture", "object; signal", "point", "IfcSign; IfcSignal; IfcFurniture"),
    (("plot", "plot piece", "path"), "LandUse", None, None, None),
    (("building",), "Building", "object building", "building", "IfcBuilding"),
    (("level",), "relativeToTerrain", None, None, "VERTICAL facility part"),
]
CODE = [(k, *rest) for ks, *rest in _C for k in ks]


def write_code(con):
    con.execute("""CREATE OR REPLACE TABLE urban.code (kind VARCHAR, citygml VARCHAR, opendrive VARCHAR, opensidewalks VARCHAR,
                   ifc VARCHAR)""")
    con.executemany("INSERT INTO urban.code VALUES (?, ?, ?, ?, ?)", CODE)


def write_style(con):
    """urban.style from STYLE, with each part's raise in 3D (parts.RAISED) and the kerb's top (parts.KERB_TOP_M)."""
    from .parts import KERB_TOP_M, RAISED
    raise_m = lambda t, k: KERB_TOP_M if (t, k) == ("urban.mark", "kerb") else (RAISED.get(k, 0.0) if t in ("urban.part", "urban.mark") else 0.0)
    con.execute("""CREATE OR REPLACE TABLE urban.style ("table" VARCHAR, rank INTEGER, kind VARCHAR, draw_order INTEGER, form VARCHAR,
                   colour VARCHAR, dash DOUBLE[], raise_m DOUBLE)""")
    con.executemany("INSERT INTO urban.style VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [(*r, raise_m(r[0], r[2])) for r in STYLE])


def version():
    """The package's version, with the git commit of the source tree (`+dirty` when it has changes) where there is one."""
    from . import __version__
    try:
        sha = subprocess.run(["git", "-C", HERE, "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "-C", HERE, "status", "--porcelain", "--", HERE], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        sha = dirty = ""
    return __version__ + (f"+{sha}" if sha else "") + (".dirty" if dirty else "")


def chosen():
    """[(module.NAME, value, the comment on its line)]: every module-level number of the build modules."""
    out = []
    for mod in BUILD_MODULES:
        path = os.path.join(HERE, mod + ".py")
        src = open(path).read()
        lines = src.splitlines()
        num = lambda v: isinstance(v, ast.Constant) and isinstance(v.value, (int, float)) and not isinstance(v.value, bool) or (
            isinstance(v, ast.UnaryOp) and isinstance(v.op, ast.USub) and num(v.operand))
        for node in ast.parse(src).body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            t, v = node.targets[0], node.value
            pairs = [(t, v)] if isinstance(t, ast.Name) else (
                list(zip(t.elts, v.elts)) if isinstance(t, ast.Tuple) and isinstance(v, ast.Tuple) and len(t.elts) == len(v.elts) else [])
            note = lines[node.lineno - 1].split("#", 1)[1].strip() if "#" in lines[node.lineno - 1] else ""
            for tn, tv in pairs:
                if isinstance(tn, ast.Name) and tn.id.isupper() and num(tv):
                    out.append((f"{mod}.{tn.id}", ast.literal_eval(tv), note))
    return out


def inputs(osm, out, bridges=()):
    """[(name, path)]: the files a build reads that exist: the duckOSM database, the bridge profiles, the corrections, and a pilot's
    city files found by the output's name (`<pilot>.urban.duckdb`: `<pilot>.vancouver.json`, `.gtfs.json`, the dossier)."""
    fs = [("osm", osm)] + [(f"bridge.{os.path.basename(b).split('.')[0]}", b) for b in bridges]
    fs += [(f"corrections.{os.path.basename(p)}", p) for p in sorted(glob.glob(os.path.join(HERE, "..", "..", "corrections", "*.json")))]
    fs.append(("mapillary", out + ".mapillary.json"))
    if out.endswith(".urban.duckdb"):
        stem = out[:-len(".urban.duckdb")]
        fs += [("vancouver", stem + ".vancouver.json"), ("gtfs", stem + ".gtfs.json"), ("dossier", stem + ".duckdb")]
    return [(n, os.path.abspath(p)) for n, p in fs if os.path.exists(p)]


def write_meta(con, osm, out, bridges, built):
    con.execute("CREATE OR REPLACE TABLE urban.meta (key VARCHAR, kind VARCHAR, value VARCHAR, note VARCHAR)")
    day = lambda p: datetime.datetime.fromtimestamp(os.path.getmtime(p)).isoformat(timespec="seconds")
    rows = [("version", "build", version(), "urbanstyle's version and the git commit of its source"),
            ("built", "build", built.isoformat(timespec="seconds"), "the time the build ended")]
    rows += [(f"input.{n}", "input", p, day(p)) for n, p in inputs(osm, out, bridges)]
    rows += [(f"chosen.{k}", "chosen", repr(v), note) for k, v, note in chosen()]
    con.executemany("INSERT INTO urban.meta VALUES (?, ?, ?, ?)", rows)


def old_registry(path):
    """The registry rows of the database at `path` before a build replaces it; [] where there is none."""
    if not os.path.exists(path):
        return []
    try:
        c = duckdb.connect(path, read_only=True)
    except duckdb.Error:
        return []
    try:
        return c.execute("SELECT profile, uid, kind, first_seen, last_seen FROM urban.registry").fetchall()
    except duckdb.Error:
        return []
    finally:
        c.close()


def write_registry(con, old, built):
    """Every profile the build has keeps its uid from `old`; a new profile gets a new UUID. `uid` goes on each thing's row."""
    con.execute("""CREATE OR REPLACE TABLE urban.registry (profile VARCHAR, uid VARCHAR, kind VARCHAR, first_seen TIMESTAMP,
                   last_seen TIMESTAMP)""")
    if old:
        con.executemany("INSERT INTO urban.registry VALUES (?, ?, ?, ?, ?)", old)
    for kind, (table, profile, where) in PROFILES.items():
        have = f"SELECT DISTINCT {profile} AS p FROM {table} x WHERE {where} AND {profile} IS NOT NULL"
        con.execute(f"""INSERT INTO urban.registry SELECT p, uuid()::VARCHAR, ?, ?, ? FROM ({have})
                        WHERE p NOT IN (SELECT profile FROM urban.registry WHERE kind = ?)""", [kind, built, built, kind])
        con.execute(f"UPDATE urban.registry SET last_seen = ? WHERE kind = ? AND profile IN ({have})", [built, kind])
        con.execute(f"""UPDATE {table} AS x SET uid = r.uid FROM urban.registry r
                        WHERE r.kind = ? AND r.profile = {profile} AND {where}""", [kind])


def _has(con, table):
    return con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'work' AND table_name = ?", [table]).fetchone()[0]


def finish(con, epsg, osm, out, bridges, old):
    """The build's last step: the model (product.py), the registry and its uids, the manifest, the style and the codes. Returns the
    row count of each table of the model."""
    from . import product
    built = datetime.datetime.now()
    n = product.write(con, epsg, out)
    write_registry(con, old, built)
    write_meta(con, osm, out, bridges, built)
    write_style(con)
    write_code(con)
    return n


def write_checks(path, rows):
    """urban.check in the database at `path`: one row per check of this run, [(id, what, count, hard, places)]. The rows of an earlier
    run go."""
    now = datetime.datetime.now()
    con = duckdb.connect(path)
    try:
        con.execute("CREATE SCHEMA IF NOT EXISTS urban")
        con.execute("""CREATE OR REPLACE TABLE urban.check (check_id VARCHAR, kind VARCHAR, status VARCHAR, count INTEGER, what VARCHAR,
                       items VARCHAR[], checked TIMESTAMP)""")
        con.executemany("INSERT INTO urban.check VALUES (?, ?, ?, ?, ?, ?, ?)", [
            (cid, "fault" if hard else "info", "pass" if not value else ("fail" if hard else "info"), int(value), what,
             [f"{x:.6f},{y:.6f}" for x, y in (at[0] if at else [])], now) for cid, what, value, hard, *at in rows])
    finally:
        con.close()
