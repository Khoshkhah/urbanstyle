"""`urbanstyle serve DB PAGE [--bridge PROFILE] [--port 8784]` (docs/design/dashboard.md): the dashboard on a local web server. The page's
folder (viz/) is served as it is; the page's engine and panel come from the package; the panel gets its data from /api/: search,
filters, the tree, the focus and the AI agent's answers."""
import json
import os
import re
import threading
import time
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

MODEL = "claude-opus-5-5"
GEMINI_MODEL = "gemini-flash-latest"    # (when no Anthropic key is set and GEMINI_API_KEY is; the free tier has no Pro model)
# (the free tier: 20 requests a day for each model, one question up to 12: when one model's day is used up, the next)
# (Lite last: quick and right on counts, but it misread the widths' source in a test, 2026-10-13: "measured by OSM" for urbanstyle's own)
GEMINI_NEXT = ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.8-flash", "gemini-3.5-flash", "gemini-3-flash-preview",
               "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-lite-latest"]
ROW_LIMIT = 2000        # features one query gives the map
SQL_ROWS = 200          # rows run_sql gives the agent
AGENT_TURNS = 12        # model calls for one question
# the layers the panel searches and filters: name -> (table, id column, the rows of the table it holds)
LAYERS = {     # the panel's layers: the model's tables (urban), as views with the old id names the panel uses beside the model's own
    "Street parts": ("urban.l_part", "part_id", None),
    "Painted lines": ("urban.l_mark", "mark_id", None),
    "Street objects": ("work.street_object", "id", None),     # (one per real object, every source: as the 3D page draws them)
    "Buildings": ("urban.l_building", "source_id", None),
    "Car parks": ("urban.l_lot", "lot_id", None),
    "Ground": ("urban.l_ground", "ground_id", None),
    "Surfaces": ("urban.l_surface", "surface_id", None),
    "Blocks": ("urban.l_block", "block_id", None),
    "Street spaces": ("urban.l_space", "unit_id", None),
    "Sides": ("urban.l_side", "side_id", None),
    "Stretches": ("urban.l_stretch", "stretch_id", None),
    "Bridge parts": ("work.bridge_part", "id", None),
}
# the views behind LAYERS: each table of the model with the names the panel's buttons and cards read (unit_id, section_id, type, ...)
LAYER_VIEWS = {
    "l_part": "SELECT *, space_id AS unit_id, kind AS type FROM urban.part",
    "l_mark": "SELECT *, space_id AS unit_id, kind AS type FROM urban.mark",
    "l_building": "SELECT *, kind AS type FROM urban.element WHERE kind = 'building'",
    "l_lot": "SELECT *, element_id AS lot_id, class AS type FROM urban.element WHERE kind = 'lot'",
    "l_ground": """SELECT ground_id, kind, kind AS type, rank, parent_id, level, name, uid, width_m, width_source, width_method, source, method,
                   ref, geometry FROM urban.ground UNION ALL SELECT piece_id, kind, kind, rank, parent_id, level, name, uid, width_m, width_source,
                   width_method, source, method, ref, geometry FROM urban.plot_piece""",
    "l_surface": "SELECT *, kind AS type FROM urban.surface",
    "l_block": "SELECT *, ref AS block_id FROM urban.ground WHERE kind = 'plot'",
    "l_space": "SELECT *, space_id AS unit_id, CASE WHEN kind = 'subsection' THEN parent_id END AS section_id FROM urban.space",
    "l_side": "SELECT *, kind AS type FROM urban.side",
    "l_stretch": "SELECT *, kind AS type FROM urban.stretch",
}
SEARCH_COLS = ("name", "road", "class", "type", "use", "ref", "osm", "kind", "subtype", "axis", "details", "sources", "edge_id", "lane_id")
KIND_COLS = ("type", "class", "kind", "use")      # a result's label: its type, then its name
NAME_COLS = ("name", "road")
# a query the agent writes: one SELECT or WITH, nothing that writes, loads or reads files
NOT_READ_ONLY = re.compile(r"\b(attach|detach|copy|install|load|pragma|create|insert|update|delete|drop|alter|export|import|call|set|"
                           r"checkpoint|vacuum)\b|\bread_\w+|\bglob\s*\(|\bst_read\w*|\bsniff_csv", re.I)


class Area:
    """One unit's space db, read-only, plus its bridges' parts (work.bridge_part), behind one lock."""

    def __init__(self, db, bridges=()):
        import duckdb
        self.lock = threading.Lock()
        self.con = c = duckdb.connect()
        c.execute("LOAD spatial")
        # the space db read into memory, then let go: a DuckDB file is held by readers or by one writer, never both across processes,
        # so a server that kept the file open blocked every build, and every build stopped the server (Kaveh, 2026-10-16: "every
        # time I want to check something in the dashboard it's down"). A rebuilt db shows after a restart.
        c.execute(f"ATTACH '{db}' AS unit (READ_ONLY)")
        for sch in ("work", "urban"):       # the build's intermediate tables (the page draws them) and the model
            c.execute(f"CREATE SCHEMA {sch}")
            for (t,) in c.execute("SELECT table_name FROM information_schema.tables WHERE table_catalog = 'unit' "
                                  "AND table_schema = ? AND table_type = 'BASE TABLE'", [sch]).fetchall():
                c.execute(f'CREATE TABLE {sch}."{t}" AS SELECT * FROM unit.{sch}."{t}"')
        c.execute("DETACH unit")
        if c.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'urban' AND table_name = 'part'").fetchone()[0]:
            for v, sql in LAYER_VIEWS.items():
                c.execute(f"CREATE VIEW urban.{v} AS {sql}")
            c.execute("CREATE VIEW urban.item AS " + " UNION ALL ".join(f"SELECT {i} AS id, rank, kind, parent_id, level, geometry FROM urban.{t}"
                      for t, i in (("area", "area_id"), ("ground", "ground_id"), ("stretch", "stretch_id"), ("plot_piece", "piece_id"),
                                   ("space", "space_id"), ("side", "side_id"), ("part", "part_id"), ("mark", "mark_id"))))
        lon = c.execute("SELECT avg(ST_X(ST_Centroid(geometry))) FROM work.container").fetchone()[0]
        self.epsg = f"EPSG:{32600 + int((lon + 180) // 6) + 1}"
        self.name = os.path.basename(db).split(".")[0]
        self._bridge_parts(bridges, db)
        self._street_objects(db)
        self.cols = {}
        for name, (t, _, _) in LAYERS.items():
            try:
                self.cols[name] = [(n, ty) for n, ty, *_ in c.execute(f"DESCRIBE {t}").fetchall()]
            except Exception:
                pass

    def _bridge_parts(self, bridges, db=None):
        """work.bridge_part: every part of each bridge's model (the flat outlines bridge2d draws), with its id and fields."""
        c = self.con
        # (a lane's duckOSM edge and GMNS lane ids as their own fields, to find and to quote: Kaveh, 2026-10-14)
        c.execute("""CREATE TABLE work.bridge_part (id VARCHAR, type VARCHAR, kind VARCHAR, bridge VARCHAR, axis VARCHAR, direction VARCHAR,
                     width_m DOUBLE, osm VARCHAR, edge_id VARCHAR, lane_id VARCHAR, source VARCHAR, method VARCHAR, fields JSON,
                     geometry GEOMETRY)""")
        if not bridges:
            return
        import shapely
        from .dashboard import bridge_models
        ms = bridge_models(c, bridges, db)[0]
        num = lambda v: float(v) if isinstance(v, (int, float)) else None
        rows = [(p.get("id"), p.get("type") or key, key, m["name"], p.get("axis"), p.get("direction"), num(p.get("width_m")),
                 str(p["osm"]) if p.get("osm") else None, str(p["edge_id"]) if p.get("edge_id") else None, p.get("lane_id"), p.get("source"),
                 p.get("method"), json.dumps(p, default=str), shapely.to_wkb(g))
                for m in ms for p, key, g in m["flat"]]
        c.executemany("INSERT INTO work.bridge_part VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ST_GeomFromWKB(?))", rows)

    def _street_objects(self, db):
        """work.street_object: the area's street objects, one per real object, matched from every source (OSM, the city's survey,
        Mapillary: dashboard.matched_objects), as the 3D page draws them; id: every source's id ("public-trees-0, n123"), the 3D key.
        work.object alone held OSM's (200 trees of 800; Kaveh, 2026-10-13: "street objects doesn't show all trees")."""
        import pyproj
        import shapely
        import shapely.ops
        from .dashboard import matched_objects
        c = self.con
        c.execute("""CREATE TABLE work.street_object (id VARCHAR, class VARCHAR, type VARCHAR, level INTEGER, sources VARCHAR,
                     height_m DOUBLE, details VARCHAR, methods VARCHAR, geometry GEOMETRY)""")
        to_ll = pyproj.Transformer.from_crs(self.epsg, "EPSG:4326", always_xy=True).transform
        rows = [(refs, cls, cls.split(".")[-1].replace("_", " "), lv, srcs, h[0] if h else None, details or None, methods,
                 shapely.to_wkb(shapely.ops.transform(to_ll, p)))
                for oid, cls, lv, grp, p, refs, srcs, h, details, methods, wd in matched_objects(c, self.epsg, db)]
        c.executemany("INSERT INTO work.street_object VALUES (?, ?, ?, ?, ?, ?, ?, ?, ST_GeomFromWKB(?))", rows)

    def meta(self):
        """Each layer: its count and its fields, for the filters (a field with 40 values or fewer lists them)."""
        out = {}
        with self.lock:
            for name, (t, idc, base) in LAYERS.items():
                if name not in self.cols:
                    continue
                w = f" WHERE {base}" if base else ""
                n = self.con.execute(f"SELECT count(*) FROM {t}{w}").fetchone()[0]
                if not n:
                    continue
                fields = []
                for col, ty in self.cols[name]:
                    if ty.startswith("GEOMETRY") or ty == "JSON":
                        continue
                    if ty in ("DOUBLE", "FLOAT", "INTEGER", "BIGINT"):
                        lo, hi = self.con.execute(f'SELECT min("{col}"), max("{col}") FROM {t}{w}').fetchone()
                        if lo is not None:
                            fields.append({"name": col, "kind": "number", "min": lo, "max": hi})
                        continue
                    vals = self.con.execute(f'SELECT CAST("{col}" AS VARCHAR) v, count(*) FROM {t}{w} GROUP BY 1 ORDER BY 2 DESC LIMIT 41').fetchall()
                    vals = [[v, k] for v, k in vals if v is not None]
                    if vals:
                        fields.append({"name": col, "kind": "choice", "values": vals} if len(vals) <= 40 else {"name": col, "kind": "text"})
                out[name] = {"count": n, "fields": fields}
        return out

    def tree(self, node=""):
        """Browse: the children of one node of the area's tree. Each: {id, label, count, kids (has children), layer, where (its things,
        for /api/query)}; a leaf ("item:<layer>:<id>") is one thing. Streets -> sections and intersections -> subsections -> parts;
        buildings by level; street objects by group and class; the bridge by axis; the ground by type; blocks."""
        q = lambda sql, a=(): self.con.execute(sql, list(a)).fetchall()
        kid = lambda i, label, n, kids, layer, where: {"id": i, "label": label, "count": n, "kids": kids, "layer": layer, "where": where}
        item = lambda layer, i, label: kid(f"item:{layer}:{i}", label, None, False, layer, [{"field": LAYERS[layer][1], "op": "=", "value": i}])
        ids = lambda layer, field, vs: [{"field": field, "op": "in", "value": vs}]
        with self.lock:
            if node == "":
                cnt = lambda t, w="": q(f"SELECT count(*) FROM {t} {w}")[0][0]
                # (the street and what is in it first, then the land beside it: streets, the bridge above them, their objects; blocks,
                # their buildings, the ground)
                out = [kid("streets", "Streets", len(self._streets()), True, "Street spaces", []),
                       kid("bridge", "Bridge", cnt("work.bridge_part"), True, "Bridge parts", []),
                       kid("obj", "Street objects", cnt("work.street_object"), True, "Street objects", []),
                       kid("blocks", "Blocks", cnt("work.block"), True, "Blocks", []),
                       kid("bld", "Buildings", cnt("work.element", "WHERE type = 'building'"), True, "Buildings", []),
                       kid("ground", "Ground", cnt("urban.l_ground"), True, "Ground", [])]
                return [k for k in out if k["count"]]
            if node == "streets":
                return [kid(f"street:{name}", name, len(us), True, "Street spaces", ids("Street spaces", "unit_id", us))
                        for name, us in sorted(self._streets().items())]
            if node.startswith("street:"):
                name = node[7:]
                secs = q("""SELECT section_id, list(DISTINCT unit_id ORDER BY unit_id) FROM work.unit WHERE kind = 'subsection' AND unit_id IN
                            (SELECT unit_id FROM work.part WHERE road = ?) GROUP BY 1 ORDER BY 1""", [name])
                ints = q("""SELECT a.intersection_id, (SELECT count(*) FROM work.part p WHERE p.unit_id = a.intersection_id) FROM
                            (SELECT DISTINCT a.intersection_id FROM work.arm a JOIN work.street s USING (street_id) WHERE s.name = ?) a
                            WHERE a.intersection_id IN (SELECT unit_id FROM work.unit) ORDER BY 1""", [name])
                return ([kid(f"sec:{sid}", f"Section {sid}", len(us), True, "Street spaces", ids("Street spaces", "unit_id", us)) for sid, us in secs] +
                        [kid(f"unit:{iid}", f"Intersection {iid}", n, True, "Street parts", ids("Street parts", "unit_id", [iid])) for iid, n in ints])
            if node.startswith("sec:"):
                return [kid(f"unit:{uid}", f"Subsection {uid}", n, True, "Street parts", ids("Street parts", "unit_id", [uid])) for uid, n in
                        q("""SELECT u.unit_id, count(p.part_id) FROM work.unit u LEFT JOIN work.part p USING (unit_id) WHERE u.section_id = ?
                             GROUP BY 1 ORDER BY 1""", [node[4:]])]
            if node.startswith("unit:"):
                return [item("Street parts", pid, " ".join(x for x in (t, d) if x)) for pid, t, d in
                        q("SELECT part_id, type, direction FROM work.part WHERE unit_id = ? ORDER BY type, part_id", [node[5:]])]
            if node == "bld":
                spans = q("SELECT level_min, level_max FROM work.element WHERE type = 'building'")
                ls = sorted({l for lo, hi in spans for l in range(lo, hi + 1)})
                return [kid(f"bldl:{l}", f"Level {l}", sum(lo <= l <= hi for lo, hi in spans), True, "Buildings",
                            [{"field": "level_min", "op": "<=", "value": l}, {"field": "level_max", "op": ">=", "value": l}]) for l in ls]
            if node.startswith("bldl:"):
                l = int(node[5:])
                return [item("Buildings", i, lab) for i, lab in q("""SELECT source_id, coalesce(name, use, class, 'building') FROM work.element
                        WHERE type = 'building' AND level_min <= ? AND level_max >= ? ORDER BY 2, 1 LIMIT 500""", [l, l])]
            if node == "obj":
                return [kid(f"objg:{g}", g, n, True, "Street objects", [{"field": "class", "op": "contains", "value": g + "."}]) for g, n in
                        q("SELECT split_part(class, '.', 1), count(*) FROM work.street_object GROUP BY 1 ORDER BY 2 DESC")]
            if node.startswith("objg:"):
                return [kid(f"objc:{c}", c.split(".", 1)[-1].replace("_", " "), n, True, "Street objects", [{"field": "class", "op": "=", "value": c}])
                        for c, n in q("SELECT class, count(*) FROM work.street_object WHERE class LIKE ? GROUP BY 1 ORDER BY 2 DESC", [node[5:] + ".%"])]
            if node.startswith("objc:"):
                return [item("Street objects", i, lab) for i, lab in
                        q("SELECT id, coalesce(left(details, 60), type) FROM work.street_object WHERE class = ? ORDER BY 2 LIMIT 1000", [node[5:]])]
            # (more than one bridge: each bridge, then its axes; their axes share names, a1, a2, ...: Monaco's 11, 2026-10-13)
            brs = q("SELECT bridge, count(*) FROM work.bridge_part GROUP BY 1 ORDER BY 1") if node == "bridge" else []
            if node == "bridge" and len(brs) > 1:
                return [kid(f"brb:{b}", b, n, True, "Bridge parts", [{"field": "bridge", "op": "=", "value": b}]) for b, n in brs]
            if node == "bridge" or node.startswith("brb:"):
                b = node[4:] if node.startswith("brb:") else brs[0][0] if brs else ""
                return [kid(f"bra:{b}|{a}", f"Axis {a}", n, True, "Bridge parts",
                            [{"field": "bridge", "op": "=", "value": b}, {"field": "axis", "op": "=", "value": a}]) for a, n in
                        q("SELECT axis, count(*) FROM work.bridge_part WHERE bridge = ? AND axis IS NOT NULL GROUP BY 1 ORDER BY 1", [b])]
            if node.startswith("bra:"):
                b, a = node[4:].split("|", 1)
                return [item("Bridge parts", i, t) for i, t in
                        q("SELECT id, type FROM work.bridge_part WHERE bridge = ? AND axis = ? ORDER BY 2, 1", [b, a])]
            if node == "ground":
                return [kid(f"grt:{t}", t, n, True, "Ground", [{"field": "type", "op": "=", "value": t}]) for t, n in
                        q("SELECT type, count(*) FROM urban.l_ground GROUP BY 1 ORDER BY 2 DESC")]
            if node.startswith("grt:"):
                return [item("Ground", i, lab) for i, lab in q("SELECT ground_id, coalesce(name, type) FROM urban.l_ground WHERE type = ? ORDER BY 2, 1 LIMIT 500",
                                                               [node[4:]])]
            if node == "blocks":
                return [item("Blocks", i, i) for (i,) in q("SELECT block_id FROM work.block ORDER BY 1")]
        return []

    def _streets(self):
        """Each street's name -> its street spaces: the subsections whose parts carry the name, and the intersections its arms reach."""
        if not hasattr(self, "_st"):
            st = {}
            for name, u in self.con.execute("""SELECT DISTINCT p.road, p.unit_id FROM work.part p JOIN work.unit u USING (unit_id)
                                               WHERE p.road IS NOT NULL AND u.kind = 'subsection'""").fetchall():
                st.setdefault(name, set()).add(u)
            for name, u in self.con.execute("""SELECT DISTINCT s.name, a.intersection_id FROM work.arm a JOIN work.street s USING (street_id)
                                               WHERE s.name IS NOT NULL AND a.intersection_id IN (SELECT unit_id FROM work.unit)""").fetchall():
                st.setdefault(name, set()).add(u)
            self._st = {k: sorted(v) for k, v in st.items()}
        return self._st

    def focus(self, layer, fid):
        """What belongs to a street space or a block, for the 3D focus (the rest faint): a space its parts, kerbs, painted lines, the
        objects that stand in it (by unit) and the buildings that frame it; a block what stands inside it (by its centre): ground,
        buildings, car parks, objects, parts. None for other layers."""
        if layer == "Street spaces":         # (one space, or a street's or a section's: ids, comma-separated)
            ids = [i for i in fid.split(",") if i]
            utm = lambda g: f"ST_Transform({g}, 'EPSG:4326', '{self.epsg}', always_xy := true)"
            with self.lock:
                objs = [i for (i,) in self.con.execute(f"""SELECT DISTINCT o.id FROM work.street_object o, urban.space u WHERE u.space_id IN
                        (SELECT unnest(?::VARCHAR[])) AND ST_DWithin({utm('o.geometry')}, {utm('u.geometry')}, 1.0)""", [ids]).fetchall()]
            return {"units": ids, "blds": sorted({b for u in ids for b in self.bounding(u)}), "objs": objs}
        if layer != "Blocks":
            return None
        inside = lambda t, idc, extra="": [i for (i,) in self.con.execute(
            f"SELECT x.{idc} FROM {t} x, work.block b WHERE b.block_id = ? {extra} AND ST_Within(ST_Centroid(x.geometry), b.geometry)", [fid]).fetchall()]
        with self.lock:
            return {"unit": None, "parts": inside("work.part", "part_id"), "ground": inside("work.ground", "ground_id"),
                    "blds": inside("work.element", "source_id", "AND x.type = 'building'"), "lots": inside("work.lot", "lot_id"),
                    "objs": inside("work.street_object", "id")}

    def bounding(self, unit_id, reach_m=10.0):
        """The buildings that frame a street space: those seen from it. The shortest line from the space to a building is reach_m or
        shorter, and no other building nearer the space and no other street space is on it: the front row, also behind a front yard
        (a 5 m reach missed the set-back ones, Kaveh 2026-10-13: "5 meters is not enough"; 40 m was "too high"). 10 m: of the buildings
        seen within 40 m, 507 stand within 5 m, 179 at 5-10 m, then only about 40 in each 5 m further out."""
        import shapely
        if not hasattr(self, "_frame"):
            utm = f"ST_AsWKB(ST_Transform(geometry, 'EPSG:4326', '{self.epsg}', always_xy := true))"
            with self.lock:
                us = self.con.execute(f"SELECT space_id, level, {utm} FROM urban.space").fetchall()     # (the model's spaces: the sub-intersections too)
                bs = self.con.execute(f"SELECT source_id, {utm} FROM work.element WHERE type = 'building'").fetchall()
            units = {u: (lv, shapely.from_wkb(bytes(g))) for u, lv, g in us}
            ids, geoms = [b for b, _ in bs], [shapely.from_wkb(bytes(g)) for _, g in bs]
            streets = {lv: shapely.union_all([g for l2, g in units.values() if l2 == lv]) for lv in {l for l, _ in units.values()}}
            self._frame = (units, ids, geoms, shapely.STRtree(geoms), streets, {})
        units, ids, geoms, tree, streets, seen = self._frame
        if unit_id not in units:
            return []
        if unit_id not in seen:
            lv, ug = units[unit_id]
            others = streets[lv].difference(ug.buffer(0.5))
            out = []
            for j in tree.query(ug.buffer(reach_m)):
                line = shapely.shortest_line(geoms[j], ug)
                if line.length > reach_m:
                    continue
                d = geoms[j].distance(ug)
                if any(k != j and geoms[k].intersects(line) and geoms[k].distance(ug) < d for k in tree.query(line)):
                    continue                                      # another building in front of it
                if line.length > 1 and shapely.LineString([line.coords[0], line.interpolate(line.length - 1).coords[0]]).intersects(others):
                    continue                                      # across another street space
                out.append(ids[j])
            seen[unit_id] = sorted(out)
        return seen[unit_id]

    def checks(self):
        """The rows of urban.check that are not a pass (`urbanstyle check` writes them), faults first; [] before a check ran."""
        with self.lock:
            try:
                rows = self.con.execute("""SELECT check_id, status, count, what, items[1:50] FROM urban.check WHERE status <> 'pass'
                                           ORDER BY status = 'info', check_id""").fetchall()
            except Exception:
                return []
        return [{"id": i, "status": s, "count": n, "what": w, "at": [list(map(float, x.split(","))) for x in (at or [])]}
                for i, s, n, w, at in rows]

    def street_levels(self):
        """The levels that hold a street space (the 3D view's levels: a building's floors go with the ground)."""
        with self.lock:
            return sorted(l for (l,) in self.con.execute("SELECT DISTINCT level FROM work.unit").fetchall())

    def levels(self):
        """The levels that hold something: a street space, or a building's floor."""
        with self.lock:
            ls = {l for (l,) in self.con.execute("SELECT DISTINCT level FROM work.unit").fetchall()}
            for lo, hi in self.con.execute("SELECT DISTINCT level_min, level_max FROM work.element WHERE type = 'building'").fetchall():
                ls |= set(range(lo, hi + 1))
        return sorted(ls)

    def features(self, sql, args=(), layer=None, limit=ROW_LIMIT):
        """The rows of `sql` (it has a `geometry` column, lon / lat) as GeoJSON features, and their totals: count, length (m), area (m2)
        and the count of each type."""
        utm = f"ST_Transform(geometry, 'EPSG:4326', '{self.epsg}', always_xy := true)"
        q = (f"SELECT * EXCLUDE (geometry), ST_AsGeoJSON(geometry) AS __g, ST_Length({utm}) AS __len, ST_Area({utm}) AS __area "
             f"FROM ({sql}) WHERE geometry IS NOT NULL")
        with self.lock:
            cur = self.con.execute(f"SELECT count(*), sum(__len), sum(__area) FROM ({q})", list(args))
            n, length, area = cur.fetchone()
            cur = self.con.execute(f"{q} LIMIT {limit}", list(args))
            names = [d[0] for d in cur.description]
            rows = cur.fetchall()
        feats, kinds = [], {}
        idc = LAYERS[layer][1] if layer in LAYERS else None
        for r in rows:
            p = {k: (v if isinstance(v, (str, int, float, bool)) or v is None else str(v)) for k, v in zip(names, r)}
            g = json.loads(p.pop("__g"))
            ln_, ar_ = p.pop("__len"), p.pop("__area")      # (each its own, for the panel to add up a list it puts together)
            fid = p.get(idc) if idc else next((p[k] for k in ("id", "part_id", "object_id", "source_id", "unit_id") if p.get(k)), None)
            lab = " · ".join(str(x) for x in (next((p[k] for k in KIND_COLS if p.get(k)), None), next((p[k] for k in NAME_COLS if p.get(k)), None))
                             if x) or layer or ""
            t = p.get("type") or p.get("class") or p.get("kind") or ""
            kinds[t] = kinds.get(t, 0) + 1
            feats.append({"type": "Feature", "geometry": g, "properties": {**p, "_id": fid, "_label": lab, "_layer": layer or "", "_m": round(ln_ or 0, 1), "_m2": round(ar_ or 0, 1)}})
        return {"type": "FeatureCollection", "features": feats, "total": n, "length_m": round(length or 0, 1),
                "area_m2": round(area or 0, 1), "kinds": sorted(kinds.items(), key=lambda kv: -kv[1]), "sql": sql}

    def query(self, layer, where=(), bbox=None):
        """The rows of one layer that meet every condition {field, op, value} (op: = != >= <= contains in), in bbox [w, s, e, n] if given."""
        t, _, base = LAYERS[layer]
        cols = dict(self.cols[layer])
        conds, args = ([base] if base else []), []
        for f in where:
            col, op, v = f["field"], f["op"], f.get("value")
            if col not in cols:
                raise ValueError(f"no field {col} in {layer}")
            num = cols[col] in ("DOUBLE", "FLOAT", "INTEGER", "BIGINT")
            if op == "contains":
                conds.append(f'CAST("{col}" AS VARCHAR) ILIKE ?')
                args.append(f"%{v}%")
            elif op == "in":
                conds.append(f'CAST("{col}" AS VARCHAR) IN (SELECT unnest(?::VARCHAR[]))')
                args.append([str(x) for x in v])
            elif op in ("=", "!=", ">=", "<="):
                conds.append(f'{"" if num else "CAST("}"{col}"{"" if num else " AS VARCHAR)"} {"<>" if op == "!=" else op} ?')
                args.append(float(v) if num else str(v))
            else:
                raise ValueError(f"no operator {op}")
        if bbox:
            conds.append("ST_Intersects(geometry, ST_MakeEnvelope(?, ?, ?, ?))")
            args += [float(x) for x in bbox]
        sql = f"SELECT * FROM {t}" + (" WHERE " + " AND ".join(conds) if conds else "")
        return self.features(sql, args, layer)

    def search(self, q, per_layer=50):
        """Names, ids, types and OSM references that hold q, in every layer: one result list, by layer."""
        out = {"type": "FeatureCollection", "features": [], "total": 0, "length_m": 0, "area_m2": 0, "kinds": [], "sql": None}
        kinds = {}
        for name, (t, idc, base) in LAYERS.items():
            cols = [c for c, ty in self.cols.get(name, []) if (c == idc or c in SEARCH_COLS) and ty == "VARCHAR"]
            if not cols:
                continue
            sql = f"SELECT * FROM {t} WHERE ({' OR '.join(f'{c} ILIKE ?' for c in cols)})" + (f" AND {base}" if base else "")
            r = self.features(sql, [f"%{q}%"] * len(cols), name, per_layer)
            if r["total"]:
                out["features"] += r["features"]
                out["total"] += r["total"]
                out["length_m"] += r["length_m"]
                out["area_m2"] += r["area_m2"]
                kinds[name] = r["total"]
        out["kinds"] = sorted(kinds.items(), key=lambda kv: -kv[1])
        return out

    def run_sql(self, sql):
        """The agent's query: at most SQL_ROWS rows as JSON text; geometry as short WKT."""
        sql = read_only(sql)
        with self.lock:
            cols = self.con.execute(f"DESCRIBE ({sql})").fetchall()
            sel = ", ".join(f'left(ST_AsText("{n}"), 120) AS "{n}"' if ty.startswith("GEOMETRY") else f'"{n}"' for n, ty, *_ in cols)
            cur = self.con.execute(f"SELECT {sel} FROM ({sql}) LIMIT {SQL_ROWS + 1}")
            names = [d[0] for d in cur.description]
            rows = cur.fetchall()
        more = len(rows) > SQL_ROWS
        rows = [{k: (v if isinstance(v, (str, int, float, bool)) or v is None else str(v)) for k, v in zip(names, r)} for r in rows[:SQL_ROWS]]
        return json.dumps({"rows": rows, "more_rows": more}, default=str)

    def schema(self):
        """The tables for the agent: columns and types, row counts, and the values of type-like columns."""
        lines = []
        with self.lock:
            tables = [t for (t,) in self.con.execute("SELECT table_name FROM information_schema.tables WHERE table_catalog = 'memory' "
                                                     "AND table_schema = 'work' ORDER BY 1").fetchall()]
            for t in tables:
                cols = self.con.execute(f'DESCRIBE work."{t}"').fetchall()
                n = self.con.execute(f'SELECT count(*) FROM work."{t}"').fetchone()[0]
                lines.append(f"work.{t} ({n} rows): " + ", ".join(f"{c} {ty}" for c, ty, *_ in cols))
                for c, ty, *_ in cols:
                    if c in ("type", "class", "kind", "source", "method", "direction", "use", "level") and ty in ("VARCHAR", "INTEGER"):
                        vals = self.con.execute(f'SELECT DISTINCT CAST("{c}" AS VARCHAR) FROM work."{t}" WHERE "{c}" IS NOT NULL LIMIT 31').fetchall()
                        vs = [v for (v,) in vals]
                        lines.append(f"  {c}: " + ", ".join(vs[:30]) + (" ..." if len(vs) > 30 else ""))
        return "\n".join(lines)


def read_only(sql):
    """sql, if it is one SELECT or WITH statement that writes, loads and reads nothing outside the tables; else ValueError."""
    s = sql.strip().rstrip(";").strip()
    if ";" in s:
        raise ValueError("one statement only")
    if not re.match(r"(?is)^\s*(select|with)\b", s):
        raise ValueError("only SELECT or WITH")
    if NOT_READ_ONLY.search(re.sub(r"'[^']*'", "''", s)):
        raise ValueError("this query writes, loads or reads files: not allowed")
    return s


SYSTEM = """You answer questions about the street space of one area ({area}), for a city's planners. Your only source is the area's
database below (DuckDB with the spatial extension). urbanstyle built it from open data: OpenStreetMap, the city's open data, LiDAR and
SUMO. Every row names its source and method (mapped, measured, derived, chosen).

Rules:
- Look at the data with run_sql before you answer. Every number in your answer comes from a query. You have at most {turns} steps:
  use few, well-aimed queries, and write the answer as soon as you have it.
- Use show_on_map for the things your answer is about, so the planner sees them on the map.
- If no table holds what is asked, say which data is missing. Do not guess, and do not use your own knowledge of the place.
- Say where the data comes from (the source and method columns), and say when a value is chosen rather than mapped or measured.
- Answer in short, plain English: the answer first, then the numbers, then the source.

Geometry is in lon / lat (EPSG:4326). For metres use ST_Transform(geometry, 'EPSG:4326', '{epsg}', always_xy := true), for example
ST_Length(...) or ST_Area(...). level 0 is the ground, 1 a bridge above it. work.part holds the street's parts (lanes, sidewalks,
crossings, ...) with width_m; work.street_object the street objects (signs, lights, trees, ...), one per real object from every
source (use it to count them; work.object holds OSM's alone); work.element the buildings and roads;
work.bridge_part the parts of the bridge model.

Tables:
{schema}"""

TOOLS = [
    {"name": "run_sql", "strict": True,
     "description": "Run one read-only DuckDB query (SELECT or WITH) on the area's tables. Returns at most 200 rows as JSON; geometry "
                    "comes back as short WKT text, so leave it out unless you need it.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["sql"],
                      "properties": {"sql": {"type": "string", "description": "One SELECT or WITH statement."}}}},
    {"name": "show_on_map", "strict": True,
     "description": "Show the rows of a query on the planner's map (2D and 3D) and in the results list, with their totals. The query must "
                    "return the column geometry, and should return an id and a name or type. Returns the count, total length and area.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["sql", "title"],
                      "properties": {"sql": {"type": "string", "description": "One SELECT or WITH statement that returns geometry."},
                                     "title": {"type": "string", "description": "A few words that say what is shown."}}}},
]


class Agent:
    """Questions in plain words, answered from the area's tables with run_sql and show_on_map, by Claude (an Anthropic key:
    ANTHROPIC_API_KEY or ~/.config/anthropic/key) or else by Gemini (GEMINI_API_KEY; model GEMINI_MODEL, or $URBANSTYLE_GEMINI_MODEL).
    The same tools and rules for both. One conversation per session id, append-only."""

    def __init__(self, area):
        self.area, self.sessions, self.system = area, {}, None
        self.gmodel, self.gused = os.environ.get("URBANSTYLE_GEMINI_MODEL", GEMINI_MODEL), set()      # (gused: models whose day is used up)

    def forget(self, sid):
        """A new conversation: this session's memory gone (both models')."""
        self.sessions.pop(sid, None)
        self.sessions.pop("gemini:" + sid, None)

    def ask(self, sid, question):
        """The answer, the queries, what is shown, and `fresh`: this session had no memory here before (a new one, or the server was
        restarted since: earlier questions are not in it)."""
        fresh = sid not in self.sessions and "gemini:" + sid not in self.sessions
        return {**self._ask(sid, question), "fresh": fresh}

    def _ask(self, sid, question):
        if self.system is None:
            self.system = SYSTEM.format(area=self.area.name, epsg=self.area.epsg, schema=self.area.schema(), turns=AGENT_TURNS)
        if not self._anthropic_key() and os.environ.get("GEMINI_API_KEY"):
            return self._ask_gemini(sid, question)
        return self._ask_claude(sid, question)

    @staticmethod
    def _anthropic_key():
        kf = os.path.expanduser("~/.config/anthropic/key")      # (never in the repo)
        return os.environ.get("ANTHROPIC_API_KEY") or (open(kf).read().strip() if os.path.exists(kf) else None)

    def _tool(self, name, args, run):
        """One tool call, for either model: its result as text; run collects the queries and what is shown on the map."""
        if name == "run_sql":
            run["queries"].append({"sql": args["sql"]})
            return self.area.run_sql(args["sql"])
        if name == "show_on_map":
            run["queries"].append({"sql": args["sql"], "title": args.get("title"), "map": True})
            shown = self.area.features(read_only(args["sql"]))
            shown["title"] = args.get("title")
            run["map"] = shown
            return json.dumps({"shown": len(shown["features"]), "total": shown["total"], "length_m": shown["length_m"],
                               "area_m2": shown["area_m2"], "kinds": shown["kinds"][:10]})
        raise ValueError(f"no tool {name}")

    def _ask_claude(self, sid, question):
        try:
            import anthropic
        except ImportError:
            return {"answer": "The AI agent needs the Anthropic SDK: pip install \"urbanstyle[serve]\".", "queries": [], "map": None}
        key = self._anthropic_key()
        client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
        msgs = self.sessions.setdefault(sid, [])
        msgs.append({"role": "user", "content": question})
        run = {"queries": [], "map": None}
        out_ = lambda answer: {"answer": answer, "queries": run["queries"], "map": run["map"]}
        for turn in range(AGENT_TURNS):
            last = turn == AGENT_TURNS - 1      # (the last step: an answer from what it found, no more tools)
            try:
                r = client.beta.messages.create(
                    model=MODEL, max_tokens=16000, output_config={"effort": "medium"},
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                    system=[{"type": "text", "text": self.system, "cache_control": {"type": "ephemeral"}}],
                    tools=TOOLS, messages=msgs, **({"tool_choice": {"type": "none"}} if last else {}))
            except anthropic.AuthenticationError:
                msgs.pop()
                return out_("The Anthropic API key is not valid.")
            except anthropic.RateLimitError:
                msgs.pop()
                return out_("The Anthropic API is busy (rate limit). Ask again in a minute.")
            except anthropic.APIStatusError as e:
                msgs.pop()
                return out_(f"The Anthropic API gave an error ({e.status_code}): {e.message}")
            except anthropic.APIConnectionError:
                msgs.pop()
                return out_("No connection to the Anthropic API.")
            except TypeError:          # (no credentials: the SDK finds no key when it sends)
                msgs.pop()
                return out_("The AI agent has no API key. Put an Anthropic key in ~/.config/anthropic/key (or set ANTHROPIC_API_KEY), "
                            "or set GEMINI_API_KEY, and ask again.")
            msgs.append({"role": "assistant", "content": r.content})
            if r.stop_reason == "refusal":
                return out_("The model declined this question.")
            if r.stop_reason != "tool_use":
                break
            results = []
            for b in r.content:
                if b.type != "tool_use":
                    continue
                try:
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": self._tool(b.name, b.input, run)})
                except Exception as e:
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": f"Error: {e}", "is_error": True})
            msgs.append({"role": "user", "content": results})
        text = "\n".join(b.text for b in r.content if b.type == "text").strip()
        return out_(text or "(no answer: the question needed more steps than allowed)")

    def _gorder(self):
        """The Gemini models in the order to try: the chosen one, then GEMINI_NEXT (the Flash models, the Lite ones last)."""
        first = os.environ.get("URBANSTYLE_GEMINI_MODEL", GEMINI_MODEL)
        return [first] + [m for m in GEMINI_NEXT if m != first]

    def _ask_gemini(self, sid, question):
        """The same agent on Gemini (google-genai): its function calls run as the tools above, their results go back as function
        responses; the model's whole turn is kept (with its thought signatures) in the session."""
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            return {"answer": "The Gemini agent needs the google-genai package: pip install google-genai.", "queries": [], "map": None}
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        # (each question from the best model whose day is not used up)
        self.gmodel = next((m for m in self._gorder() if m not in self.gused), self._gorder()[0])
        decls = [types.FunctionDeclaration(name=t["name"], description=t["description"], parameters_json_schema=t["input_schema"]) for t in TOOLS]
        config = types.GenerateContentConfig(system_instruction=self.system, tools=[types.Tool(function_declarations=decls)],
                                             automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
        hist = self.sessions.setdefault("gemini:" + sid, [])
        start = len(hist)          # (an error: the conversation back to before this question)
        hist.append(types.Content(role="user", parts=[types.Part(text=question)]))
        run = {"queries": [], "map": None}
        out_ = lambda answer: {"answer": answer, "queries": run["queries"], "map": run["map"]}
        text = ""
        last_cfg = config.model_copy(update={"tool_config": types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="NONE"))})
        for turn in range(AGENT_TURNS):
            r = None
            cfg = last_cfg if turn == AGENT_TURNS - 1 else config      # (the last step: an answer, no more tools)
            tried, waits = set(), 0      # (this request: models overloaded now, and waits for the per-minute limit)
            while True:
                try:
                    r = client.models.generate_content(model=self.gmodel, contents=hist, config=cfg)
                    break
                except Exception as e:
                    msg = str(e)
                    # (its day used up, or the model gone for this key: "404 no longer available", 2.5 Flash: not again today)
                    day = ("429" in msg and ("PerDay" in msg or "limit: 0" in msg)) or "404" in msg or "NOT_FOUND" in msg
                    busy = "503" in msg or "UNAVAILABLE" in msg
                    if day:
                        self.gused.add(self.gmodel)          # (its day used up: not again today)
                    elif busy:
                        tried.add(self.gmodel)               # (overloaded now: the next one for this request)
                    elif "429" in msg and waits < 3:         # (the per-minute limit: wait as asked, the same model)
                        waits += 1
                        m = re.search(r"retry in ([0-9.]+)s", msg)
                        time.sleep(min(float(m.group(1)) + 1 if m else 10.0, 60.0))
                        continue
                    nxt = next((m for m in self._gorder() if m not in self.gused and m not in tried), None)
                    if (day or busy) and nxt:
                        self.gmodel = nxt
                        continue
                    del hist[start:]
                    if day:
                        m = re.search(r"retry in ([0-9]+h)?([0-9]+m)?", msg)
                        when = f" It starts again in about {(m.group(1) or '') + (m.group(2) or '')}." if m and (m.group(1) or m.group(2)) else ""
                        return out_("Gemini's free daily quota is used up for every model this agent can use (20 requests a day each; one question "
                                    f"uses up to 12).{when} For more questions: enable billing on the Google project of the key, or set an "
                                    "Anthropic key.")
                    if busy:
                        return out_("Every Gemini model this agent can use is overloaded just now (Google: \"high demand\"). Ask again in a minute.")
                    return out_(f"The Gemini API gave an error: {msg[:300]}")
            cand = (r.candidates or [None])[0]
            if cand is None or cand.content is None:
                return out_(f"Gemini gave no answer ({getattr(cand, 'finish_reason', None) or getattr(r, 'prompt_feedback', None)}).")
            hist.append(cand.content)
            parts = cand.content.parts or []
            text = "\n".join(p.text for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False)).strip()
            calls = [p.function_call for p in parts if getattr(p, "function_call", None)]
            if not calls:
                break
            replies = []
            for fc in calls:
                try:
                    res = {"result": self._tool(fc.name, dict(fc.args or {}), run)}
                except Exception as e:
                    res = {"error": str(e)}
                replies.append(types.Part.from_function_response(name=fc.name, response=res))
            hist.append(types.Content(role="user", parts=replies))
        return out_(text or "(no answer: the question needed more steps than allowed)")


def handler(area, agent, viz, page):
    """The request handler: the page and the rest of viz/ as files; the engine and the panel (page.ASSETS) from the package, read on every
    request so every page runs the current script (docs/design/dashboard.md, "How the page is made"); and /api/."""
    from .page import ASSETS
    here = os.path.dirname(__file__)
    types = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}

    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=viz, **k)

        def log_message(self, fmt, *args):
            if "/api/" in str(args[0] if args else ""):
                super().log_message(fmt, *args)

        def _json(self, obj, code=200):
            b = json.dumps(obj, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path in ("/", "/index.html"):
                self.send_response(302)
                self.send_header("Location", "/" + page + ("?" + u.query if u.query else ""))
                self.end_headers()
            elif u.path.rsplit("/", 1)[-1] in ASSETS:          # the engine and the panel, from the package
                name = ASSETS[u.path.rsplit("/", 1)[-1]]
                b = open(os.path.join(here, name)).read().encode()
                self.send_response(200)
                self.send_header("Content-Type", types[os.path.splitext(name)[1]])
                self.send_header("Content-Length", str(len(b)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(b)
            elif u.path == "/api/meta":
                self._json({"area": area.name, "layers": area.meta(), "levels": area.levels(), "street_levels": area.street_levels(), "agent": True,
                            "checks": area.checks()})
            elif u.path == "/api/focus":
                qs = parse_qs(u.query)
                self._json(area.focus(qs.get("layer", [""])[0], qs.get("id", [""])[0]))
            elif u.path == "/api/tree":
                self._json(area.tree(parse_qs(u.query).get("node", [""])[0]))
            elif u.path == "/api/search":
                self._json(area.search(parse_qs(u.query).get("q", [""])[0]))
            else:
                super().do_GET()

        def do_POST(self):
            u = urlparse(self.path)
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            try:
                if u.path == "/api/focus":
                    return self._json(area.focus(body.get("layer", "Street spaces"), ",".join(body.get("ids", []))))
                if u.path == "/api/query":
                    self._json(area.query(body["layer"], body.get("where", []), body.get("bbox")))
                elif u.path == "/api/forget":
                    agent.forget(body.get("session", ""))
                    self._json({"ok": True})
                elif u.path == "/api/ask":
                    self._json(agent.ask(body.get("session") or str(uuid.uuid4()), body["question"]))
                else:
                    self._json({"error": "no such api"}, 404)
            except Exception as e:
                self._json({"error": str(e)}, 400)
    return H


def serve(db, page, bridges=(), port=8784):
    """Serve page (a file in viz/) with the Explore panel, on http://localhost:port, until stopped."""
    viz = os.path.dirname(os.path.abspath(page))
    area = Area(db, bridges)
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler(area, Agent(area), viz, os.path.basename(page)))
    print(f"urbanstyle serve: http://localhost:{port}/{os.path.basename(page)}  ({area.name}, {area.epsg}; Ctrl+C stops)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
