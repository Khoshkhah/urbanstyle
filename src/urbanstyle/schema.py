"""The schemas of an area's database (docs/design/tables.md): `urban`, the model, which the build's last step writes (product.py), and
`work`, the build's intermediate tables. A database of an older build kept its intermediate tables in `space`, then in `urban`; the
first command that opens it with write access moves them to `work`."""
import duckdb

SCHEMA = "urban"
WORK = "work"
OLD = "space"
# the model's own tables: everything else in an old `urban` is an intermediate table
MODEL = ("area", "element", "ground", "stretch", "plot_piece", "joint", "street", "arm", "space", "junction", "side", "part", "mark", "turn",
         "approach", "object", "link", "station", "surface", "observed", "photo", "item", "meta", "check", "registry", "style", "code")


def migrate(path):
    """Move the intermediate tables of an older database at `path` to `work`. Returns True when it moved any."""
    try:
        con = duckdb.connect(path)
    except duckdb.IOException:       # (in use by a writer or by readers: the caller works with what is there)
        return False
    try:
        schemas = {r[0] for r in con.execute("SELECT schema_name FROM information_schema.schemata").fetchall()}
        tables = lambda s: [t for (t,) in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = ? "
                                                       "AND table_type = 'BASE TABLE'", [s]).fetchall()]
        if WORK in schemas:
            return False
        if OLD in schemas:
            src, move = OLD, tables(OLD)
        elif SCHEMA in schemas and "unit" in tables(SCHEMA):     # an `urban` that holds the build's intermediate tables
            src, move = SCHEMA, [t for t in tables(SCHEMA) if t not in ("meta", "check", "registry", "style", "code", "item")]
        else:
            return False
        con.execute("LOAD spatial")
        con.execute(f"CREATE SCHEMA {WORK}")
        for t in move:
            con.execute(f'CREATE TABLE {WORK}."{t}" AS SELECT * FROM {src}."{t}"')
        if src == OLD:
            con.execute(f"DROP SCHEMA {OLD} CASCADE")
        else:                        # (the model's tables of that build go too, the next build writes them; the registry stays: its uids)
            for t in tables(SCHEMA):
                if t != "registry":
                    con.execute(f'DROP TABLE {SCHEMA}."{t}"')
            for (v,) in con.execute("SELECT view_name FROM duckdb_views() WHERE schema_name = ? AND NOT internal", [SCHEMA]).fetchall():
                con.execute(f'DROP VIEW {SCHEMA}."{v}"')
        con.execute("CHECKPOINT")
        print(f"  schema: {len(move)} tables of {src} moved to {WORK} in {path}", flush=True)
        return True
    finally:
        con.close()
