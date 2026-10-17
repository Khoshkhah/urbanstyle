"""The schema of urbanstyle's tables is `urban`. A database written with the old schema name, `space`, is renamed the first time a
command opens it with write access: every table is copied into `urban` and the old schema is dropped."""
import duckdb

SCHEMA = "urban"
OLD = "space"


def migrate(path):
    """Rename the schema `space` to `urban` in the database at `path`, when it has the old one. Returns True when it renamed."""
    try:
        con = duckdb.connect(path)
    except duckdb.IOException:       # (in use by a writer or by readers: the caller works with what is there)
        return False
    try:
        schemas = {r[0] for r in con.execute("SELECT schema_name FROM information_schema.schemata").fetchall()}
        if OLD not in schemas or SCHEMA in schemas:
            return False
        con.execute("LOAD spatial")
        con.execute(f"CREATE SCHEMA {SCHEMA}")
        for (t,) in con.execute(f"SELECT table_name FROM information_schema.tables WHERE table_schema = '{OLD}'").fetchall():
            con.execute(f'CREATE TABLE {SCHEMA}."{t}" AS SELECT * FROM {OLD}."{t}"')
        con.execute(f"DROP SCHEMA {OLD} CASCADE")
        con.execute("CHECKPOINT")
        print(f"  schema: {OLD} renamed {SCHEMA} in {path}", flush=True)
        return True
    finally:
        con.close()
