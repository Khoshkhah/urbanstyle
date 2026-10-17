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
    ("urban.part", 5, "path", 50, "polygon", "#e0a96d", None),
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


def profiles(con):
    """[(registry kind, table, id column, id, profile)] for every thing of the model (docs/design/tables.md, "urban.registry"): its
    facts that do not change, as text; two things of one kind with one profile get #2, #3 in the order of their ids."""
    import json
    q = lambda sql: con.execute(sql).fetchall()
    names = lambda xs: "|".join(sorted({x for x in xs if x}))
    out = []
    area = {i: f"area:{n}:{lv}" for i, n, lv in q("SELECT area_id, name, level FROM urban.area")}
    out += [("area", "area", "area_id", i, p) for i, p in area.items()]
    secnames = {}
    for par, n in q("SELECT parent_id, name FROM urban.stretch WHERE kind = 'section'"):
        secnames.setdefault(par, []).append(n)
    ground = {}
    for i, k, lv, sides, ref in q("SELECT ground_id, kind, level, sides::VARCHAR, ref FROM urban.ground"):
        if k == "street":
            ground[i] = f"street:{lv}:{names(secnames.get(i, []))}"
        elif k == "plot":
            ground[i] = f"plot:{lv}:{names(x.get('name') for x in json.loads(sides or '[]'))}"
        else:
            ground[i] = "osm:" + ref.split("-", 1)[-1].split(".")[0] if ref else f"path:{i}"
        out.append((k, "ground", "ground_id", i, ground[i]))
    stretch, kinds = {}, {}
    for i, k, lv, n, ways, nodes in q("SELECT stretch_id, kind, level, name, ways, nodes FROM urban.stretch WHERE kind <> 'section'"):
        stretch[i] = (f"intersection:{lv}:{names((n or '').split(' / '))}" if k == "intersection" else
                      f"osm:{ways[0]}" if k == "path section" and ways else f"osm:n{i.split('-', 1)[1].split('.')[0]}" if k == "path intersection"
                      else f"{k}:{i}")
        kinds[i] = k
    ends = {}
    for i_, sec in q("SELECT intersection_id, section_id FROM urban.arm"):
        ends.setdefault(sec, []).append(stretch.get(i_, i_))
    for i, lv, n in q("SELECT stretch_id, level, name FROM urban.stretch WHERE kind = 'section'"):
        stretch[i] = f"section:{lv}:{n or ''}:" + "+".join(sorted(ends.get(i, [])))
        kinds[i] = "section"
    out += [(kinds[i], "stretch", "stretch_id", i, p) for i, p in stretch.items()]
    for i, k, par, ref, src in q("SELECT piece_id, kind, parent_id, ref, source FROM urban.plot_piece"):
        mapped = src and src != "urbanstyle" and ref and ref[:1] in "wnr" and ref[1:].split("/")[0].isdigit()
        out.append(("plot piece", "plot_piece", "piece_id", i, f"{src.split('+')[0]}:{ref.split('/')[0]}" if mapped else f"{ground.get(par, par)}:{k}"))
    space = {}
    for i, k, par in q("SELECT space_id, kind, parent_id FROM urban.space"):
        space[i] = f"{stretch.get(par, par)}/{i.rsplit('/', 1)[1]}" if k == "subsection" else stretch.get(i, i)
        out.append((k, "space", "space_id", i, space[i]))
    side = {i: f"{space.get(par, par)}:{i[-1]}" for i, par in q("SELECT side_id, parent_id FROM urban.side")}
    out += [("side", "side", "side_id", i, p) for i, p in side.items()]
    for i, k, par, d, n in q("SELECT part_id, kind, parent_id, direction, lane FROM urban.part"):
        out.append(("part", "part", "part_id", i, f"{side.get(par, par)}:lane:{d}:{n}" if k == "lane" else f"{side.get(par, par)}:{k}"))
    out += [("mark", "mark", "mark_id", i, f"{space.get(sp, sp)}:{k}") for i, k, sp in q("SELECT mark_id, kind, space_id FROM urban.mark")]
    out += [("street object", "object", "object_id", i, f"{src}:{i}") for i, src in q("SELECT object_id, source FROM urban.object")]
    out += [("building", "element", "element_id", i, f"{src}:{sid}") for i, src, sid in
            q("SELECT element_id, source, source_id FROM urban.element WHERE kind = 'building'")]
    seen, res = {}, []
    for kind, t, col, i, p in sorted(out, key=lambda r: (r[0], r[4], r[3])):
        key = (kind, p, t)
        seen[key] = seen.get(key, 0) + 1
        res.append((kind, t, col, i, p + (f"#{seen[key]}" if seen[key] > 1 else "")))
    return res


def write_registry(con, old, built):
    """Every profile the build has keeps its uid from `old`; a new profile gets a new UUID. `uid` goes on each thing's row. A thing that
    is both a stretch and a space (an intersection, a path section, a path intersection) has one profile, so one uid."""
    con.execute("""CREATE OR REPLACE TABLE urban.registry (profile VARCHAR, uid VARCHAR, kind VARCHAR, first_seen TIMESTAMP,
                   last_seen TIMESTAMP)""")
    if old:
        con.executemany("INSERT INTO urban.registry VALUES (?, ?, ?, ?, ?)", old)
    con.execute("CREATE OR REPLACE TEMP TABLE _thing (kind VARCHAR, tbl VARCHAR, col VARCHAR, id VARCHAR, profile VARCHAR)")
    rows = profiles(con)
    if rows:
        con.executemany("INSERT INTO _thing VALUES (?, ?, ?, ?, ?)", rows)
    con.execute("""INSERT INTO urban.registry SELECT DISTINCT t.profile, NULL, t.kind, ?, ? FROM _thing t
                   WHERE NOT EXISTS (SELECT 1 FROM urban.registry r WHERE r.kind = t.kind AND r.profile = t.profile)""", [built, built])
    con.execute("UPDATE urban.registry SET uid = uuid()::VARCHAR WHERE uid IS NULL")
    con.execute("""UPDATE urban.registry r SET last_seen = ? FROM _thing t WHERE r.kind = t.kind AND r.profile = t.profile""", [built])
    for t, col in {(r[1], r[2]) for r in rows}:
        con.execute(f"""UPDATE urban."{t}" AS x SET uid = r.uid FROM _thing t JOIN urban.registry r ON r.kind = t.kind AND r.profile = t.profile
                        WHERE t.tbl = ? AND t.id = x.{col}""", [t])
    con.execute("DROP TABLE _thing")


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
