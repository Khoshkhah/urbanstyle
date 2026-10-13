"""`urbanstyle publish DB OUT_DIR [--bridge PROFILE]` (docs/design/online-dashboard.md): the dashboard as static files, for a web site
with no server. OUT_DIR gets index.html (the page with the Explore panel; no Mapillary data, the keys as placeholders that the site's
deploy fills from its secrets), bridge3d.json, static.js (the panel's /api/ in the browser: DuckDB-WASM, Gemini) and data/: meta.json,
tree.json, focus.json and one Parquet file per space table, its geometry as GeoJSON text with its length, area, centre and bounds."""
import glob
import json
import os
import shutil
import tempfile

# the deploy replaces these with the site's secrets (GitHub: CARTO_DEMO_KEY, GOOGLE_MAPS_DEMO_KEY, GEMINI_DEMO_KEY)
KEYS = {"CARTO_API_KEY": "__CARTO_DEMO_KEY__", "GOOGLE_MAPS_KEY": "__GOOGLE_MAPS_DEMO_KEY__"}
GEMINI = "__GEMINI_DEMO_KEY__"
LOCAL_ONLY = ("observed", "photo")      # Mapillary's detections and photos: CC BY-SA, they stay local (docs/design/mapillary.md)
PLAIN = ("VARCHAR", "DOUBLE", "FLOAT", "INTEGER", "BIGINT", "BOOLEAN", "SMALLINT", "TINYINT")

SYSTEM = """You answer questions about the street space of one area ({area}), for a city's planners. Your only source is the area's
tables below (DuckDB, in the planner's browser). urbanstyle built them from open data: OpenStreetMap, the city's open data, LiDAR and
SUMO. Every row names its source and method (mapped, measured, derived, chosen).

Rules:
- Look at the data with run_sql before you answer. Every number in your answer comes from a query. You have at most {turns} steps:
  use few, well-aimed queries, and write the answer as soon as you have it.
- Use show_on_map for the things your answer is about, so the planner sees them on the map.
- If no table holds what is asked, say which data is missing. Do not guess, and do not use your own knowledge of the place.
- Say where the data comes from (the source and method columns), and say when a value is chosen rather than mapped or measured.
- Answer in short, plain English: the answer first, then the numbers, then the source.

There is no spatial extension: no ST_ functions. A table with shapes has these columns instead: __g (the shape as GeoJSON text, lon /
lat), __len (its length in metres), __area (its area in m2), __x and __y (its centre, lon and lat), __w, __s, __e, __n (its bounds).
show_on_map needs __g in its query. level 0 is the ground, 1 a bridge above it. space.part holds the street's parts (lanes, sidewalks,
crossings, ...) with width_m; space.street_object the street objects (signs, lights, trees, ...), one per real object from every
source (use it to count them; space.object holds OSM's alone); space.element the buildings and roads; space.bridge_part the parts of
the bridge model.

Tables:
{schema}"""


def _clean_copy(db, tmp):
    """The space db and the files beside it that the page reads, in tmp, without Mapillary's tables."""
    import duckdb
    base = os.path.basename(db).replace(".space.duckdb", "").replace(".duckdb", "")
    for f in glob.glob(os.path.join(os.path.dirname(os.path.abspath(db)), base + ".*")):
        name = os.path.basename(f)
        if f == os.path.abspath(db) or ".bak" in name or ".rebuilt" in name or name.endswith(".mapillary.json"):
            continue
        os.symlink(f, os.path.join(tmp, name))
    out = os.path.join(tmp, os.path.basename(db))
    shutil.copy(db, out)
    con = duckdb.connect(out)
    for t in LOCAL_ONLY:
        con.execute(f"DROP TABLE IF EXISTS space.{t}")
    con.close()
    return out


def _tree(area):
    """Every node of the area's tree: node id -> its children."""
    out, todo = {}, [""]
    while todo:
        node = todo.pop()
        kids = area.tree(node)
        out[node] = kids
        todo += [k["id"] for k in kids if k["kids"]]
    return out


def _focus(area):
    """What each street space and each block holds in focus (the server's /api/focus, made once)."""
    with area.lock:
        units = [u for (u,) in area.con.execute("SELECT unit_id FROM space.unit").fetchall()]
        blocks = [b for (b,) in area.con.execute("SELECT block_id FROM space.block").fetchall()]
    return {"Street spaces": {u: area.focus("Street spaces", u) for u in units}, "Blocks": {b: area.focus("Blocks", b) for b in blocks}}


def _tables(area, data):
    """One Parquet file per space table, as the browser reads it; and the schema text for the agent."""
    c, lines, files = area.con, [], {}
    utm = f"ST_Transform(geometry, 'EPSG:4326', '{area.epsg}', always_xy := true)"
    tables = [t for (t,) in c.execute("SELECT table_name FROM information_schema.tables WHERE table_catalog = 'memory' "
                                     "AND table_schema = 'space' ORDER BY 1").fetchall()]
    for t in tables:
        cols = c.execute(f'DESCRIBE space."{t}"').fetchall()
        sel, geo = [], False
        for n, ty, *_ in cols:
            if ty.startswith("GEOMETRY"):
                if n == "geometry":
                    geo = True
                continue                      # (another shape column: left out)
            sel.append(f'"{n}"' if ty in PLAIN else f'CAST("{n}" AS VARCHAR) AS "{n}"')
        if geo:
            sel += ["ST_AsGeoJSON(geometry) AS __g", f"ST_Length({utm}) AS __len", f"ST_Area({utm}) AS __area",
                    "ST_X(ST_Centroid(geometry)) AS __x", "ST_Y(ST_Centroid(geometry)) AS __y", "ST_XMin(geometry) AS __w",
                    "ST_YMin(geometry) AS __s", "ST_XMax(geometry) AS __e", "ST_YMax(geometry) AS __n"]
        if not sel:
            continue
        path = os.path.join(data, t + ".parquet")
        with area.lock:
            c.execute(f'COPY (SELECT {", ".join(sel)} FROM space."{t}") TO \'{path}\' (FORMAT PARQUET)')
            n = c.execute(f'SELECT count(*) FROM space."{t}"').fetchone()[0]
            desc = c.execute(f"DESCRIBE SELECT * FROM '{path}'").fetchall()
        files[t] = t + ".parquet"
        lines.append(f"space.{t} ({n} rows): " + ", ".join(f"{a} {b}" for a, b, *_ in desc))
        for a, b, *_ in desc:
            if a in ("type", "class", "kind", "source", "method", "direction", "use", "level") and b in ("VARCHAR", "INTEGER"):
                vs = [v for (v,) in c.execute(f"SELECT DISTINCT CAST(\"{a}\" AS VARCHAR) FROM '{path}' WHERE \"{a}\" IS NOT NULL LIMIT 31").fetchall()]
                lines.append(f"  {a}: " + ", ".join(vs[:30]) + (" ..." if len(vs) > 30 else ""))
    return files, "\n".join(lines)


def publish(db, out_dir, bridges=()):
    """Write the static dashboard of `db` to out_dir; returns the files written."""
    from . import page as page_
    from .serve import AGENT_TURNS, GEMINI_MODEL, GEMINI_NEXT, LAYERS, ROW_LIMIT, SEARCH_COLS, SQL_ROWS, Area
    data = os.path.join(out_dir, "data")
    os.makedirs(data, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        clean = _clean_copy(db, tmp)
        old = {k: os.environ.get(k) for k in KEYS}
        os.environ.update(KEYS)        # (the page gets placeholders, never the local keys)
        page = os.path.join(out_dir, "index.html")
        try:
            page_.build(clean, page, list(bridges) or None)
        finally:
            for k, v in old.items():
                os.environ.pop(k) if v is None else os.environ.__setitem__(k, v)
        area = Area(clean, bridges)
        files, schema = _tables(area, data)
        meta = {"area": area.name, "layers": area.meta(), "levels": area.levels(), "street_levels": area.street_levels(), "agent": True,
                "epsg": area.epsg, "files": files,
                "panel": {name: {"table": t, "id": idc, "base": base, "cols": area.cols.get(name, [])} for name, (t, idc, base) in LAYERS.items()},
                "search_cols": list(SEARCH_COLS), "row_limit": ROW_LIMIT, "sql_rows": SQL_ROWS, "turns": AGENT_TURNS,
                "gemini_models": [GEMINI_MODEL] + [m for m in GEMINI_NEXT if m != GEMINI_MODEL],
                "system": SYSTEM.format(area=area.name, turns=AGENT_TURNS, schema=schema)}
        json.dump(meta, open(os.path.join(data, "meta.json"), "w"), default=str)
        json.dump(_tree(area), open(os.path.join(data, "tree.json"), "w"), default=str)
        json.dump(_focus(area), open(os.path.join(data, "focus.json"), "w"), default=str)
    here = os.path.dirname(__file__)
    shutil.copy(os.path.join(here, "static.js"), os.path.join(out_dir, "static.js"))
    cfg = (f"<script>window.XP_STATIC_CFG={{gemini:'{GEMINI}',data:'data/'}};window.XP_STATIC_READY=new Promise(r=>window.XP_STATIC_RESOLVE=r);"
           "window.XP_STATIC={api:(u,b)=>window.XP_STATIC_READY.then(f=>f(u,b))};</script><script type=module src=\"static.js\"></script>")
    html = open(page).read().replace("<head>", "<head>" + cfg, 1)      # (the static /api/ before the panel's script runs)
    open(page, "w").write(html)
    return sorted(os.path.relpath(f, out_dir) for f in glob.glob(os.path.join(out_dir, "**", "*"), recursive=True) if os.path.isfile(f))
