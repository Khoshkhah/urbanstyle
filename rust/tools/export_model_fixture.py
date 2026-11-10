"""The test data of urbanstyle-model (slice 1: the axes, the sections, the parts and the marks of the subsections): the `work` rows that
product.write reads (units, subsections, parts, marks) and the rows of `urban` that it made from them.

    python rust/tools/export_model_fixture.py URBAN_DB OUT.json [OSM_DB]

URBAN_DB is a finished build (a cut or Monaco). Run it with the duckOSM environment. The file is not in git."""
import json
import sys

import duckdb
import shapely

urban, out = sys.argv[1:3]
osm = sys.argv[3] if len(sys.argv) > 3 else None
EPSG = "EPSG:32632"
con = duckdb.connect(urban, read_only=True)
con.execute("LOAD spatial")
m = lambda col="geometry": f"ST_AsWKB(ST_Transform({col}, 'EPSG:4326', '{EPSG}', always_xy := true))"
g = lambda w: None if w is None else shapely.make_valid(shapely.from_wkb(bytes(w)))
ring = lambda r: [list(c) for c in r.coords]
poly = lambda p: [ring(p.exterior)] + [ring(r) for r in p.interiors]
mp = lambda x: [poly(p) for p in shapely.get_parts(x) if p.geom_type == "Polygon" and not p.is_empty] if x is not None else []
mls = lambda x: [[list(c) for c in l.coords] for l in shapely.get_parts(x) if l.geom_type == "LineString"] if x is not None else []
alen = lambda w: None if w is None or g(w) is None else g(w).length

if osm:
    con.execute(f"ATTACH '{osm}' AS osm (READ_ONLY)")
units = con.execute(f"SELECT unit_id, kind, section_id, level, {m()} FROM work.unit").fetchall()
subs = con.execute(f"SELECT subsection_id, section_id, level, class, width_m, oneway, length_m, left_extra, {m()} FROM work.subsection").fetchall()
parts = con.execute(f"SELECT part_id, unit_id, type, direction, lane, road, ref, {m()} FROM work.part").fetchall()
marks = con.execute(f"SELECT unit_id, type, level, source, method, {m()} FROM work.mark").fetchall()
turns = con.execute(f"SELECT unit_id, level, from_edge, from_lane, to_edge, to_lane, turn, source, vehicles, condition, {m()} FROM work.turn").fetchall()
approaches = con.execute("SELECT unit_id, level, from_edge, lane, moves, ways, arrow, no_arrow_because FROM work.approach").fetchall()
sub_ids = {s[0] for s in subs}
ground = con.execute(f"SELECT ground_id, type, level, name, source, method, ref, {m()} FROM work.ground").fetchall()
blocks = con.execute(f"SELECT block_id, level, source, method, {m()} FROM work.block").fetchall()
bsides = con.execute("SELECT block_id, way_id, name, class, distance_m, basis, method FROM work.block_side").fetchall()
corr = con.execute("SELECT corridor_id, name, width_m, width_source, width_method FROM work.corridor").fetchall()
surf = con.execute("SELECT surface_id, ground_id FROM work.surface").fetchall()
node_pt = {n: g(w) for n, w in con.execute(f"""SELECT src, {m('ST_StartPoint(geometry)')} FROM work.element WHERE type = 'road' AND src IS NOT NULL
                                             UNION SELECT dst, {m('ST_EndPoint(geometry)')} FROM work.element WHERE type = 'road' AND dst IS NOT NULL""").fetchall()}
jn = con.execute("SELECT intersection_id, node_id, level, cluster_id FROM work.junction").fetchall()
way_street = con.execute("SELECT street_id, osm_id FROM work.arm WHERE osm_id IS NOT NULL").fetchall()
name_street = con.execute("SELECT street_id, name, level FROM work.street WHERE name IS NOT NULL").fetchall()
pspace = con.execute(f"""SELECT space_id, kind, ground_id, level, name, class, ways, nodes, width_m, width_source, width_method, length_m, predecessors,
                         successors, {m('axis')}, {m()} FROM work.path_space""").fetchall()
rb = [g(w) for (w,) in con.execute(f"SELECT {m()} FROM osm.driving.edges WHERE junction IN ('roundabout', 'circular')").fetchall()] if osm else []
owidth = {}
if osm:
    owidth = {f"w{o}": float(w_) for o, w_ in con.execute("""SELECT osm_id, try_cast(regexp_extract(tags['width'], '[0-9.]+') AS DOUBLE)
                                                         FROM osm.raw.ways WHERE tags['width'] IS NOT NULL""").fetchall() if w_}

json.dump({
    "input": {
        "units": [{"id": u, "kind": k, "section": s, "level": lv, "geom": mp(g(w))} for u, k, s, lv, w in units],
        "subsections": [{"id": i, "section": sec, "level": lv, "class": cl, "width": wd, "oneway": ow, "length": ln, "left_extra": le,
                         "line": [list(c) for c in g(w).coords] if w is not None and g(w).geom_type == "LineString" else None}
                        for i, sec, lv, cl, wd, ow, ln, le, w in subs],
        "parts": [{"id": i, "unit": u, "type": t, "direction": d, "lane": ln, "road": rd, "ref": rf, "geom": mp(g(w))} for i, u, t, d, ln, rd, rf, w in parts],
        "marks": [{"unit": u, "type": t, "level": lv, "source": sr, "method": me, "lines": mls(g(w))} for u, t, lv, sr, me, w in marks],
        "turns": [{"unit": u, "level": lv, "from_edge": fe, "from_lane": fl, "to_edge": te, "to_lane": tl, "turn": tn, "source": sr, "vehicles": vh, "condition": cd, "lines": mls(g(w))}
                  for u, lv, fe, fl, te, tl, tn, sr, vh, cd, w in turns],
        "approaches": [{"unit": u, "level": lv, "from_edge": fe, "lane": ln, "moves": mv, "ways": wy, "arrow": ar, "no_arrow_because": nb} for u, lv, fe, ln, mv, wy, ar, nb in approaches],
        "ground": [{"id": i, "type": t, "level": lv, "name": n, "source": sr, "method": me, "ref": r, "geom": mp(g(w))} for i, t, lv, n, sr, me, r, w in ground],
        "blocks": [{"id": b, "level": lv, "source": sr, "method": me, "geom": mp(g(w))} for b, lv, sr, me, w in blocks],
        "block_sides": [{"block": b, "way": wy, "name": n, "class": c, "distance_m": d, "basis": bs, "method": me} for b, wy, n, c, d, bs, me in bsides],
        "corridors": [{"id": c, "name": n, "width": wd, "source": ws, "method": wm} for c, n, wd, ws, wm in corr],
        "surfaces": [{"id": i, "ground": gd} for i, gd in surf],
        "owidth": owidth,
        "junctions": [{"intersection": i, "node": n, "level": lv, "cluster": c} for i, n, lv, c in jn],
        "node_pt": {str(n): [p.x, p.y] for n, p in node_pt.items()},
        "way_street": [{"street": s_, "osm_id": o} for s_, o in way_street],
        "name_street": [{"street": s_, "name": n, "level": lv} for s_, n, lv in name_street],
        "roundabouts": [[list(c) for c in l.coords] for gm in rb for l in shapely.get_parts(gm) if l.geom_type == "LineString"],
        "path_spaces": [{"id": i, "kind": k, "ground": gd, "level": lv, "name": n, "class": c, "ways": w_, "nodes": nd, "width": wd, "ws": ws, "wm": wm,
                         "length": ln, "pred": pr, "succ": su, "axis": [list(c) for c in g(ax).coords] if ax is not None and g(ax).geom_type == "LineString" else None,
                         "geom": mp(g(w))} for i, k, gd, lv, n, c, w_, nd, wd, ws, wm, ln, pr, su, ax, w in pspace],
    },
    "expect": {
        "ground": [{"id": i, "kind": k, "parent": pr, "ref": r, "area": g(w).area, "width": wd, "ws": ws, "wm": wm, "name": n, "sides": sd, "source": sr, "method": me}
                   for i, k, pr, n, sd, wd, ws, wm, sr, me, r, w in con.execute(
                       f"SELECT ground_id, kind, parent_id, name, sides::VARCHAR, width_m, width_source, width_method, source, method, ref, {m()} FROM urban.ground").fetchall()],
        "path_spaces": [{"id": i, "kind": k, "parent": pr, "s_from": a, "s_to": b, "width": wd, "length": ln, "axis_len": alen(ax), "oneway": ow, "pred": pd, "succ": sc}
                        for i, k, pr, a, b, wd, ln, ow, pd, sc, ax in con.execute(
                            f"SELECT space_id, kind, parent_id, s_from, s_to, width_m, length_m, oneway, predecessors, successors, {m('axis')} FROM urban.space WHERE kind LIKE 'path %'").fetchall()],
        "path_parts": [{"id": i, "kind": k, "side": sd, "space": sp, "s_from": a, "s_to": b, "t_from": c, "t_to": d, "width": wd, "ws": ws, "length": ln, "axis_len": alen(ax)}
                       for i, k, sd, sp, a, b, c, d, wd, ws, ln, ax in con.execute(
                           f"SELECT part_id, kind, parent_id, space_id, s_from, s_to, t_from, t_to, width_m, width_source, length_m, {m('axis')} FROM urban.part WHERE kind IN ('path', 'steps')").fetchall()],
        "int_spaces": [{"id": i, "kind": k, "parent": pr, "level": lv, "name": n, "pred": pd, "succ": sc, "area": g(w).area}
                       for i, k, pr, lv, n, pd, sc, w in con.execute(
                           f"SELECT space_id, kind, parent_id, level, name, predecessors, successors, {m()} FROM urban.space WHERE kind IN ('sub-intersection', 'ring sector', 'centre')").fetchall()],
        "junction_rows": [{"intersection": i, "node": n, "level": lv, "cluster": c, "space": sp} for i, n, lv, c, sp in con.execute(
            "SELECT intersection_id, node_id, level, cluster_id, space_id FROM urban.junction").fetchall()],
        "all_parts": [{"id": i, "kind": k, "side": sd, "space": sp, "pred": pd, "succ": sc, "area": g(w).area, "lane": ln}
                      for i, k, sd, sp, pd, sc, ln, w in con.execute(
                          f"SELECT part_id, kind, parent_id, space_id, predecessors, successors, lane, {m()} FROM urban.part").fetchall()],
        "sides": [{"id": i, "kind": k, "parent": pr, "level": lv, "kerb_len": alen(kb), "ks": ks, "km": km, "area": g(w).area}
                  for i, k, pr, lv, kb, ks, km, w in con.execute(
                      f"SELECT side_id, kind, parent_id, level, {m('kerb')}, kerb_source, kerb_method, {m()} FROM urban.side").fetchall()],
        "all_marks": [{"id": i, "kind": k, "parent": pr, "prank": pk, "space": sp, "s_from": a, "t_from": c} for i, k, pr, pk, sp, a, c in con.execute(
            "SELECT mark_id, kind, parent_id, parent_rank, space_id, s_from, t_from FROM urban.mark").fetchall()],
        "turn_rows": [{"space": sp, "level": lv, "from_edge": fe, "from_lane": fl, "to_edge": te, "to_lane": tl, "turn": tn} for sp, lv, fe, fl, te, tl, tn in con.execute(
            "SELECT space_id, level, from_edge, from_lane, to_edge, to_lane, turn FROM urban.turn").fetchall()],
        "approach_n": con.execute("SELECT count(*) FROM urban.approach").fetchone()[0],
        "part_links": {i: [pd, sc] for i, pd, sc in con.execute("SELECT part_id, predecessors, successors FROM urban.part WHERE kind = 'lane'").fetchall()},
        "space_links": {i: [pd, sc] for i, pd, sc in con.execute("SELECT space_id, predecessors, successors FROM urban.space WHERE kind = 'subsection'").fetchall()},
        "stretches": [{"id": i, "kind": k, "parent": pr, "level": lv, "name": n, "street": st, "ways": w_, "nodes": nd, "class": c, "oneway": ow,
                       "length": ln, "axis_len": alen(ax), "area": g(w).area}
                      for i, k, pr, lv, n, st, w_, nd, c, ow, ln, ax, w in con.execute(
                          f"SELECT stretch_id, kind, parent_id, level, name, street_id, ways, nodes, class, oneway, length_m, {m('axis')}, {m()} FROM urban.stretch").fetchall()],
        "arms": [{"intersection": i, "street": s_, "section": sec, "way": w_, "level": lv} for i, s_, sec, w_, lv in con.execute(
            "SELECT intersection_id, street_id, section_id, way, level FROM urban.arm").fetchall()],
        "streets": [{"id": i, "name": n, "level": lv, "sections": sc, "intersections": it, "area": g(w).area} for i, n, lv, sc, it, w in con.execute(
            f"SELECT street_id, name, level, sections, intersections, {m()} FROM urban.street").fetchall()],
        "plot_pieces": [{"id": i, "kind": k, "parent": pr, "width": wd, "ws": ws, "wm": wm, "surfaces": sf, "area": g(w).area, "ref": r}
                        for i, k, pr, wd, ws, wm, sf, r, w in con.execute(
                            f"SELECT piece_id, kind, parent_id, width_m, width_source, width_method, surfaces, ref, {m()} FROM urban.plot_piece").fetchall()],
        "spaces": [{"id": i, "parent": p, "s_from": a, "s_to": b, "width": wd, "length": ln, "axis_len": alen(ax)}
                   for i, p, a, b, wd, ln, ax in con.execute(
                       f"SELECT space_id, parent_id, s_from, s_to, width_m, length_m, {m('axis')} FROM urban.space WHERE kind = 'subsection'").fetchall()],
        "parts": [{"id": i, "side": sd, "space": sp, "s_from": a, "s_to": b, "t_from": c, "t_to": d, "axis_len": alen(ax), "lane": ln,
                   "area": g(w).area}
                  for i, sd, sp, a, b, c, d, ln, ax, w in con.execute(
                      f"SELECT part_id, parent_id, space_id, s_from, s_to, t_from, t_to, lane, {m('axis')}, {m()} FROM urban.part").fetchall() if sp in sub_ids],
        "marks": [{"id": i, "space": sp, "kind": k, "s_from": a, "s_to": b, "t_from": c, "t_to": d}
                  for i, sp, k, a, b, c, d in con.execute(
                      "SELECT mark_id, space_id, kind, s_from, s_to, t_from, t_to FROM urban.mark").fetchall() if sp in sub_ids],
    },
}, open(out, "w"), default=str)
print(f"{len(subs)} subsections, {len(parts)} parts, {len(marks)} marks -> {out}")
