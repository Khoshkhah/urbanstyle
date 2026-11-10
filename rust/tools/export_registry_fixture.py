"""The test data of the registry (meta.py): for every thing of a finished build its table, id, registry kind, profile and uid (the table's
`uid` joined to `urban.registry`), the area's name, and the rows of `urban.style` and `urban.code`.

    python rust/tools/export_registry_fixture.py URBAN_DB OUT.json

Run it with the duckOSM environment. The file is not in git."""
import json
import sys

import duckdb

urban, out = sys.argv[1:3]
con = duckdb.connect(urban, read_only=True)
TABLES = [("area", "area_id", ""), ("ground", "ground_id", ""), ("stretch", "stretch_id", ""), ("plot_piece", "piece_id", ""), ("space", "space_id", ""),
          ("side", "side_id", ""), ("part", "part_id", ""), ("mark", "mark_id", ""), ("object", "object_id", ""), ("element", "element_id", "WHERE x.kind = 'building'")]
things = []
for t, col, where in TABLES:
    things += [{"table": t, "id": i, "kind": k, "profile": p, "uid": u} for i, k, p, u in con.execute(
        f"SELECT x.{col}, r.kind, r.profile, r.uid FROM urban.{t} x JOIN urban.registry r ON r.uid = x.uid {where}").fetchall()]
json.dump({
    "things": things,
    "area_name": con.execute("SELECT name FROM urban.area LIMIT 1").fetchone()[0],
    "registry": [list(map(str, r)) for r in con.execute("SELECT profile, uid, kind, first_seen, last_seen FROM urban.registry").fetchall()],
    "style": [list(r) for r in con.execute('SELECT "table", rank, kind, draw_order, form, colour, dash, raise_m FROM urban.style').fetchall()],
    "code": [list(r) for r in con.execute("SELECT kind, citygml, opendrive, opensidewalks, ifc FROM urban.code").fetchall()],
}, open(out, "w"), default=str)
print(f"{len(things)} things -> {out}")
