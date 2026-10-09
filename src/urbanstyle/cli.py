"""The `urbanstyle` command: build, check, quality, dashboard, mapillary, unit."""
import argparse
import sys


def main(argv=None):
    p = argparse.ArgumentParser(prog="urbanstyle", description="Space containers from a duckOSM database.")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build the space schema from a duckOSM database")
    b.add_argument("osm", help="duckOSM .duckdb (a copy with features is made next to OUT if it has none)")
    b.add_argument("out", help="output .duckdb")
    sub.add_parser("check", help="conformance checks; exit 1 if a hard check fails").add_argument("db", nargs="+")
    sub.add_parser("quality", help="shape quality of the sections").add_argument("db", nargs="+")
    d = sub.add_parser("dashboard", help="an offline HTML map with the hierarchy tree (needs roadstyle)")
    d.add_argument("db")
    d.add_argument("out")
    m = sub.add_parser("mapillary", help="fetch Mapillary's street-level features and photos for a built area (needs a token)")
    m.add_argument("db")
    m.add_argument("--osm", help="the duckOSM .duckdb it was built from: rebuild the parts with them now")
    u = sub.add_parser("unit", help="one unit in full: clip, build and write its dossier (docs/design/unit-dossier.md)")
    u.add_argument("name")
    u.add_argument("--at", nargs=2, type=float, metavar=("LON", "LAT"), required=True, help="a point of the junction or street")
    u.add_argument("--osm", required=True, help="duckOSM .duckdb (a copy with features is made when it has none)")
    u.add_argument("--nvdb", help="a .duckdb with NVDB's nvdb.road_network (fetching-sweden-data)")
    u.add_argument("--flows", help="glob of hourly flow parquet files (edge_id, date, hour, flow)")
    u.add_argument("--city", default="")
    u.add_argument("--no-mapillary", action="store_true")
    u.add_argument("--vancouver", action="store_true", help="add the City of Vancouver's open data (trees, lamps, meters, ...)")
    a = p.parse_args(argv)

    if a.cmd == "build":
        from .container import build, counts, with_features
        c = build(with_features(a.osm, a.out.replace(".duckdb", ".osm.duckdb")), a.out)
        print("level  type       n")
        for l, t, n in counts(c):
            print(f"{l:>5}  {t:<9} {n}")
        print("links:", c.execute("SELECT type, level_a, level_b, count(*) FROM space.link GROUP BY ALL ORDER BY ALL").fetchall())
        print("next: urbanstyle dashboard", a.out, "viz/<area>.html")
    elif a.cmd == "check":
        from .checks import run
        return 1 if any([run(x) for x in a.db]) else 0
    elif a.cmd == "quality":
        from .quality import run
        for x in a.db:
            run(x)
    elif a.cmd == "unit":
        from .unit import main as unit
        unit(a.name, a.at[0], a.at[1], a.osm, a.nvdb, a.flows, a.city, not a.no_mapillary, a.vancouver)
    elif a.cmd == "mapillary":
        from .mapillary import main as mly
        mly(a.db, a.osm)
    else:
        from .dashboard import main as dash
        dash(a.db, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
