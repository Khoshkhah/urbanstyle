"""Make a DuckDB file of the model `urban` from the Parquet tables of the Rust chain (`urbanstyle-build`), so that the dashboard opens it.

    python scripts/load_rust_tables.py RUST_DIR OUT.duckdb TEMPLATE.duckdb [NAME [PASS0_DIR]]

RUST_DIR: the chain's output (`data/rust-monaco`); one Parquet file per table, the shape of each row as GeoJSON in `__g` (lon/lat).
TEMPLATE: any build of the Python code (a cut is enough); it gives the columns and their types of every table.
A table the chain does not write is empty (the `urban` tables joint, link, station, observed, photo, and every `work` table the page
reads), `urban.meta` is the template's with the area name changed, and a shape column other than `geometry` (an axis, a kerb) is NULL:
the chain leaves it out, as the page's publisher does. Columns that do not fit the template's type become NULL and are listed.
"""
import os
import sys

import duckdb


def main(rust, out, template, name="monaco-rust", pass0=None):
    if os.path.exists(out):
        os.remove(out)
    c = duckdb.connect(out)
    c.sql("install spatial; load spatial")
    c.sql(f"attach '{template}' as t (read_only)")
    for s in ("urban", "work"):
        c.sql(f"create schema if not exists {s}")
    tables = c.sql("select table_schema, table_name from information_schema.tables where table_catalog = 't' "
                   "and table_schema in ('urban', 'work') and table_type = 'BASE TABLE' order by 1, 2").fetchall()
    lost = []
    for schema, t in tables:
        cols = c.sql(f"describe t.{schema}.{t}").fetchall()
        f = os.path.join(rust, t + ".parquet")
        if schema == "urban" and os.path.exists(f):
            have = {r[0] for r in c.sql(f"describe select * from '{f}'").fetchall()}
            sel = []
            for n, ty, *_ in cols:
                if n == "geometry" and "__g" in have:
                    sel.append("ST_GeomFromGeoJSON(__g) AS geometry")
                elif ty.startswith("GEOMETRY"):
                    sel.append(f'NULL::GEOMETRY AS "{n}"')
                elif n in have:
                    sel.append(f'TRY_CAST("{n}" AS {ty}) AS "{n}"')
                else:
                    sel.append(f'NULL::{ty} AS "{n}"')
            c.sql(f'create table urban."{t}" as select {", ".join(sel)} from \'{f}\'')
            for n, ty, *_ in cols:
                if n in have and not ty.startswith("GEOMETRY"):
                    bad = c.sql(f'select count(*) from \'{f}\' where "{n}" is not null and "{n}" is distinct from TRY_CAST(TRY_CAST("{n}" AS {ty}) AS VARCHAR)').fetchone()[0] \
                        if ty not in ("VARCHAR", "BIGINT", "INTEGER", "DOUBLE", "BOOLEAN") else 0
                    if bad:
                        lost.append(f"{t}.{n} ({ty}): {bad} rows")
            n = c.sql(f'select count(*) from urban."{t}"').fetchone()[0]
            print(f"urban.{t}: {n} rows from Parquet")
        else:
            c.sql(f'create table {schema}."{t}" as select * from t.{schema}."{t}" where false')
            if schema == "urban" and t == "meta":
                c.sql(f'insert into urban.meta select * from t.urban.meta')
                cs = [r[0] for r in c.sql("describe urban.meta").fetchall()]
                if "key" in cs and "value" in cs:
                    c.sql(f"update urban.meta set value = '{name}' where key in ('area', 'name')")
    for line in lost:
        print("  not kept:", line)
    # the page reads the elements from work.element (its `type` is the model's `kind`); the lots are in work.lot
    have = {r[0] for r in c.sql("describe urban.element").fetchall()}
    wcols = [r[0] for r in c.sql("describe work.element").fetchall()]
    sel = ["kind AS type" if n == "type" else n for n in wcols if n == "type" or n in have]
    ins = [n for n in wcols if n == "type" or n in have]
    c.sql(f"insert into work.element ({', '.join(ins)}) select {', '.join(sel)} from urban.element where kind <> 'lot'")
    print("work.element:", c.sql("select count(*) from work.element").fetchone()[0], "rows from urban.element")
    # the chain writes the elements of buildings and lots only: the road lines the page draws are duckOSM's driving edges (pass 0,
    # lon/lat). One line for each OSM way and direction pair: the edge with is_reverse false.
    if pass0:
        f = os.path.join(pass0, "edges_driving.parquet")
        c.sql(f"""insert into work.element (source, source_id, type, level_min, level_max, level_src, name, class, geometry, width_m, osm_id,
                  oneway, width_src)
                  select 'osm', edge_id::VARCHAR, 'road',
                         coalesce(try_cast(layer AS INTEGER), 0), coalesce(try_cast(layer AS INTEGER), 0),
                         CASE WHEN bridge IS NOT NULL AND bridge <> 'no' THEN 'bridge' WHEN tunnel IS NOT NULL AND tunnel <> 'no' THEN 'tunnel' END,
                         name, highway, geometry, NULL, osm_id::VARCHAR, oneway, NULL
                  from '{f}' where not is_reverse""")
        print("work.element roads:", c.sql("select count(*) from work.element where type = 'road'").fetchone()[0])
    # the page takes the area's longitude from work.container: one row, the area's own outline
    c.sql("insert into work.container (container_id, geometry) select 'rust', geometry from urban.area limit 1") \
        if "container_id" in {r[0] for r in c.sql("describe work.container").fetchall()} else None
    c.close()
    print("wrote", out)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], a[1], a[2], a[3] if len(a) > 3 else "monaco-rust", a[4] if len(a) > 4 else None)
