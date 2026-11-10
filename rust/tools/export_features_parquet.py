"""Dump duckOSM's `features` tables as Parquet files (Snappy, geometry as WKB in longitude and latitude), the form the Rust readers of
urbanstyle-simready read. Until duckOSM writes them itself (docs/notes/rust-browser.md), this is the stand-in.

    python rust/tools/export_features_parquet.py OSM_DB OUT_DIR

OSM_DB is a duckOSM database with a `features` schema (../duckOSM/monaco-wide.duckdb). Run it with the duckOSM environment."""
import os
import sys

import duckdb

db, out = sys.argv[1:3]
os.makedirs(out, exist_ok=True)
con = duckdb.connect(db, read_only=True)
con.execute("LOAD spatial")
for (t,) in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'features' ORDER BY 1").fetchall():
    cols = [c for (c,) in con.execute(f"SELECT column_name FROM information_schema.columns WHERE table_schema = 'features' AND table_name = '{t}'").fetchall()]
    sel = ", ".join(f"ST_AsWKB({c}) AS {c}" if c in ("geom", "geometry") else c for c in cols)
    n = con.execute(f"COPY (SELECT {sel} FROM features.{t}) TO '{out}/features-{t}.parquet' (FORMAT parquet, COMPRESSION snappy)").fetchone()[0]
    print(f"{t}: {n} rows")
