"""Rows into a DuckDB table in one statement (Arrow), in place of `con.executemany`: DuckDB's executemany runs one statement for each row
(about 5 ms each, 22,000 rows of Monaco's parts and marks took 100 s). The same statement text is used: each `?` of the VALUES list is
a column of the Arrow table (in the order of the `?`), and the rest of the list (a literal, ST_GeomFromWKB(?), a CASE ...) is the
expression of the SELECT. A statement or rows that this cannot read go to `executemany` as before."""
import re

_HEAD = re.compile(r"^\s*INSERT\s+INTO\s+(.+?)\s+VALUES\s*\((.*)\)\s*;?\s*$", re.S | re.I)


def _split(s):
    """The top-level items of a comma list (commas inside parentheses and quotes do not split)."""
    out, depth, quote, cur = [], 0, None, []
    for ch in s:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    out.append("".join(cur).strip())
    return out


def executemany(con, sql, rows):
    """`con.executemany(sql, rows)` for an INSERT ... VALUES (...), in one statement."""
    rows = list(rows)
    if not rows:
        return
    m = _HEAD.match(sql)
    try:
        if not m:
            raise ValueError("not an INSERT ... VALUES")
        import pyarrow as pa
        target, values = m.group(1), m.group(2)
        n = len(rows[0])
        if values.count("?") != n or any(len(r) != n for r in rows):
            raise ValueError("the placeholders and the row length differ")
        i = iter(range(n))
        exprs = ", ".join(re.sub(r"\?", lambda _: f"c{next(i)}", e) for e in _split(values))
        table = pa.table({f"c{k}": pa.array([r[k] for r in rows]) for k in range(n)})
    except Exception:
        con.executemany(sql, rows)
        return
    con.register("_bulk_rows", table)
    try:
        con.execute(f"INSERT INTO {target} SELECT {exprs} FROM _bulk_rows")
    finally:
        con.unregister("_bulk_rows")
