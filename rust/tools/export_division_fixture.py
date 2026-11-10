"""The test data of urbanstyle-division: the inputs of simready.build for a cut, as the Python reference reads them (simready.read_all, the
blocks and corridors, OSM's crossings), and what the reference made (work.unit, part, mark, subsection, junction, turn, approach).

    python rust/tools/export_division_fixture.py URBAN_DB OSM_DB SIMREADY_DB OUT.json

URBAN_DB is a cut built with --simready from that SimReady build (data/cuts/NAME.urban.duckdb), OSM_DB its input (NAME.osm.duckdb).
Run it with the duckOSM environment and PYTHONPATH=src. The file is not in git."""
import json
import sys

import duckdb
import shapely

from urbanstyle import network, simready as sr

urban, osm, simready, out = sys.argv[1:5]
EPSG = "EPSG:32632"
con = duckdb.connect(urban, read_only=True)
con.execute("LOAD spatial")
con.execute(f"ATTACH '{osm}' AS osm (READ_ONLY)")
m = lambda col="geometry": f"ST_AsWKB(ST_Transform({col}, 'EPSG:4326', '{EPSG}', always_xy := true))"
g = lambda w: shapely.make_valid(shapely.force_2d(shapely.from_wkb(bytes(w))))
ring = lambda r: [list(c) for c in r.coords]
poly = lambda p: [ring(p.exterior)] + [ring(r) for r in p.interiors]
mp = lambda x: [poly(p) for p in shapely.get_parts(x) if p.geom_type == "Polygon"]
lines = lambda x: [[list(c) for c in l.coords] for l in shapely.get_parts(x) if l.geom_type == "LineString"]
line = lambda x: [list(c) for c in x.coords]

R = sr.read_all(con, EPSG, simready)
edge_osm = R["edge_osm"]


def way_of(c):
    es = [e for e in c["edges"] if e in edge_osm]
    return edge_osm[max(es, key=lambda e: edge_osm[e][1] or 0)][0] if es else None


blocks = shapely.union_all([g(w) for (w,) in con.execute(f"SELECT {m()} FROM work.block WHERE level = 0").fetchall()] or [shapely.Polygon()])
corridors = shapely.union_all([g(w) for (w,) in con.execute(f"SELECT {m()} FROM work.corridor").fetchall()] or [shapely.Polygon()])
xways = [(o, g(w)) for o, w in con.execute(f"""SELECT osm_id, {m()} FROM work.element WHERE type IN ('walkway', 'cycleway') AND level_min = 0
                                                 AND subtype = 'crossing'""").fetchall()]
xtags = {o: dict(t or {}) for o, t in con.execute("SELECT osm_id, tags FROM osm.raw.ways WHERE osm_id IN (SELECT unnest(?::BIGINT[]))",
                                                    [[o for o, _ in xways]]).fetchall()} if xways else {}
xnodes = [(o, dict(t or {}), x, y) for o, t, x, y in con.execute(f"""SELECT osm_id, tags, ST_X(p), ST_Y(p) FROM (SELECT osm_id, tags,
             ST_Transform(ST_Point(lon, lat), 'EPSG:4326', '{EPSG}', always_xy := true) AS p FROM osm.raw.nodes WHERE tags['highway'] = 'crossing')""").fetchall()]

# what the reference made
area_of = lambda w: g(w).area
units = [{"id": u, "kind": k, "section": s, "level": lv, "area": area_of(w)} for u, k, s, lv, w in
         con.execute(f"SELECT unit_id, kind, section_id, level, {m()} FROM work.unit").fetchall()]
parts = {}
for u, t, w in con.execute(f"SELECT unit_id, type, {m()} FROM work.part").fetchall():
    a = parts.setdefault(f"{u}|{t}", [0, 0.0])
    a[0] += 1
    a[1] += area_of(w)
marks = {}
for u, t, w in con.execute(f"SELECT unit_id, type, {m()} FROM work.mark").fetchall():
    a = marks.setdefault(f"{u}|{t}", [0, 0.0])
    a[0] += 1
    a[1] += g(w).length
expect = {
    "units": units, "parts": parts, "marks": marks,
    "subsections": [{"id": s, "section": sec, "level": lv, "length": ln, "width": wd, "class": cl} for s, sec, lv, ln, wd, cl in
                    con.execute("SELECT subsection_id, section_id, level, length_m, width_m, class FROM work.subsection").fetchall()],
    "junctions": [[i, n, lv] for i, n, lv in con.execute("SELECT intersection_id, node_id, level FROM work.junction").fetchall()],
    "turns": con.execute("SELECT count(*) FROM work.turn").fetchone()[0], "approaches": con.execute("SELECT count(*) FROM work.approach").fetchone()[0],
}
json.dump({
    "consts": {"cut_m": network.CUT_M, "clear_m": network.CLEAR_M, "furnish_m": network.FURNISH_M, "crosswalk_m": network.CROSSWALK_M,
               "zebra_bar_m": network.ZEBRA_BAR_M, "zebra_gap_m": network.ZEBRA_GAP_M, "xwalk_max_m": network.XWALK_MAX_M,
               "edge_touch_m": sr.EDGE_TOUCH_M},
    "input": {
        "area": mp(R["area"]), "blocks": mp(blocks), "corridors": mp(corridors),
        "carriageways": [{"id": cid, "way": way_of(c), "twin": c["twin"], "shared": bool(c["shared"]), "highway": c["highway"], "name": c["name"],
                          "oneway": bool(c["oneway"]), "edges": [int(e) for e in c["edges"] or []], "ring": c["ring"] is not None, "inside": c["inside"], "level": c["level"], "line": line(c["line"])}
                         for cid, c in R["cws"].items()],
        "lanes": [{"id": lid, "cid": L["cid"], "n": L["n"], "role": L["role"], "turn": L["turn"], "w": L["w"], "method": L["method"], "srcs": L["srcs"] or [],
                   "left": line(L["left"]), "right": line(L["right"]), "geom": mp(L["geom"])} for lid, L in R["lanes"].items()],
        "junctions": [{"id": j, "nodes": d["nodes"], "kind": d["kind"], "control": d["control"], "level": d["level"], "method": d["method"], "area": mp(d["area"])}
                      for j, d in R["juncs"].items()],
        "islands": [{"j": x["j"], "kind": x["kind"], "level": x["level"], "method": x["method"], "geom": mp(x["geom"])} for x in R["islands"]],
        "stops": [{"cid": x["cid"], "j": x["j"], "method": x["method"], "lines": lines(x["geom"])} for x in R["stops"]],
        "moves": [{"j": x["j"], "fl": x["fl"], "tl": x["tl"], "fc": x["fc"], "tc": x["tc"], "turn": x["turn"], "uses": x["uses"] or [], "method": x["method"],
                   "lines": lines(x["geom"])} for x in R["moves"]],
        "faces": [{"level": lv, "geom": mp(w)} for lv, w in R["faces"]],
        "crossing_ways": [{"id": o, "lines": lines(x), "tags": xtags.get(o, {})} for o, x in xways],
        "crossing_nodes": [{"id": o, "tags": t, "xy": [x, y]} for o, t, x, y in xnodes],
    },
    "expect": expect,
}, open(out, "w"), default=str)
print(f"{len(units)} units, {len(parts)} part groups, {len(marks)} mark groups, {len(R['lanes'])} lanes, {len(xways)} crossing ways -> {out}")
