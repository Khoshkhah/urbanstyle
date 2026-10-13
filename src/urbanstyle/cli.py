"""The `urbanstyle` command: build, check, quality, dashboard, layers, mapillary, unit, bridge, serve, publish, ..."""
import argparse
import sys


def main(argv=None):
    p = argparse.ArgumentParser(prog="urbanstyle", description="Space containers from a duckOSM database.")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build the space schema from a duckOSM database")
    b.add_argument("osm", help="duckOSM .duckdb (a copy with features is made next to OUT if it has none)")
    b.add_argument("out", help="output .duckdb")
    b.add_argument("--from", dest="start", choices=["division"], help="only the street division and the steps after it, from the copy "
                   "the last full build kept (OUT.before-division): for a fix in division.py or ground.py")
    ck = sub.add_parser("check", help="conformance checks; exit 1 if a hard check fails")
    ck.add_argument("db", nargs="+")
    ck.add_argument("--bridge", nargs="+", default=[], help="bridge profiles: the bridge model's checks too (BR1-BR11)")
    sub.add_parser("quality", help="shape quality of the sections").add_argument("db", nargs="+")
    d = sub.add_parser("dashboard", help="an offline HTML map with the hierarchy tree (needs roadstyle)")
    d.add_argument("db")
    d.add_argument("out")
    d.add_argument("--bridge", action="append", metavar="PROFILE",
                   help="draw a bridge as a 3D model from its profile (<name>.bridge.json, `urbanstyle bridge`)")
    ly = sub.add_parser("layers", help="an offline HTML page of the layers: 0 the ground, 1 the surfaces (needs roadstyle)")
    ly.add_argument("db")
    ly.add_argument("out")
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
    u.add_argument("--gtfs", help="a GTFS feed's URL (public transport timetable, e.g. TransLink's): each stop's routes and buses per hour")
    br = sub.add_parser("bridge", help="write bridge profiles (docs/design/bridge-profile.md)")
    br.add_argument("osm", help="duckOSM .duckdb that holds all of the bridge")
    br.add_argument("gmns", help="its GMNS export (`duckosm gmns OSM --out GMNS -m driving`): the lanes")
    br.add_argument("out_dir")
    br.add_argument("--name", help="the bridge's OSM name (man_made=bridge); without it, every road bridge")
    bm = sub.add_parser("bridge-measure", help="measure a bridge profile's heights from LiDAR (ducklidar Parquet tiles; the conda env `lidar`)")
    bm.add_argument("profile", help="a <name>.bridge.json (`urbanstyle bridge`)")
    bm.add_argument("out", help="the measured profile: a .json file or a directory")
    bm.add_argument("--lidar", nargs="+", required=True, help="ducklidar Parquet tiles that cover the bridge")
    bm.add_argument("--osm", help="the duckOSM .duckdb of the profile: a ramp that OSM ends in the air runs on along the road that continues it")
    bh = sub.add_parser("bridge-heights", help="set a bridge profile's heights from a small heights file, no LiDAR (docs/design/bridge-heights.md)")
    bh.add_argument("profile", help="a <name>.bridge.json (`urbanstyle bridge`)")
    bh.add_argument("heights", help="the heights file: {bridge name: {default: {grade, max_m, curve_m}, axis: [[s, height], ...] | {from, to_ground}}}")
    bh.add_argument("out", help="the profile with these heights")
    b2 = sub.add_parser("bridge2d", help="the bridge model in 2D, every part with its id, as GeoJSON for viz/bridge2d.html (seconds)")
    b2.add_argument("profile", help="a <name>.bridge.json (measured)")
    b2.add_argument("out", help="the GeoJSON file, e.g. viz/bridge2d.geojson")
    b2.add_argument("--db", help="a unit's space db: its street's lanes for the landings")
    b3 = sub.add_parser("bridge3d", help="only the bridges' 3D models, to viz/bridge3d.json, which the dashboard page reads: reload the page")
    b3.add_argument("db", help="the unit's space db (its street's lanes for the landings)")
    b3.add_argument("out", help="the JSON file beside the page, e.g. viz/bridge3d.json")
    b3.add_argument("--bridge", action="append", required=True, help="a bridge profile, as for the dashboard")
    sv = sub.add_parser("serve", help="the dashboard page with the Explore panel (search, filters, AI questions) on a local server")
    sv.add_argument("db", help="the unit's space db")
    sv.add_argument("page", help="a page `urbanstyle dashboard` built, e.g. viz/broadway-granville-v92.html (its folder is served)")
    sv.add_argument("--bridge", action="append", default=[], help="a bridge profile: its parts can be searched too")
    sv.add_argument("--port", type=int, default=8784, help="8784: the port Street View's key allows")
    pb = sub.add_parser("publish", help="the dashboard as static files for a web site with no server (docs/design/online-dashboard.md)")
    pb.add_argument("db", help="the unit's space db")
    pb.add_argument("out_dir", help="the folder to write: index.html, static.js, bridge3d.json, data/")
    pb.add_argument("--bridge", action="append", default=[], help="a bridge profile, as for the dashboard")
    a = p.parse_args(argv)

    if a.cmd == "build":
        from .container import build, counts, with_features
        c = build(with_features(a.osm, a.out.replace(".duckdb", ".osm.duckdb")), a.out, a.start)
        print("level  type       n")
        for l, t, n in counts(c):
            print(f"{l:>5}  {t:<9} {n}")
        print("links:", c.execute("SELECT type, level_a, level_b, count(*) FROM space.link GROUP BY ALL ORDER BY ALL").fetchall())
        print("next: urbanstyle dashboard", a.out, "viz/<area>.html")
    elif a.cmd == "check":
        from .checks import bridge, run
        return 1 if any([run(x) for x in a.db] + [bridge(b, a.db[0]) for b in a.bridge]) else 0
    elif a.cmd == "quality":
        from .quality import run
        for x in a.db:
            run(x)
    elif a.cmd == "unit":
        from .unit import main as unit
        unit(a.name, a.at[0], a.at[1], a.osm, a.nvdb, a.flows, a.city, not a.no_mapillary, a.vancouver, a.gtfs)
    elif a.cmd == "layers":
        from .dashboard import layers
        print(layers(a.db, a.out))
    elif a.cmd == "bridge-heights":
        from .bridge_heights import write as heights
        print(heights(a.profile, a.heights, a.out), "axes ->", a.out)
    elif a.cmd == "bridge-measure":
        from .bridge_lidar import write as measure
        print(measure(a.profile, a.out, a.lidar, a.osm))
    elif a.cmd == "bridge2d":
        from .bridge2d import write as write2d
        print(write2d(a.profile, a.out, a.db), "parts ->", a.out)
    elif a.cmd == "serve":
        from .serve import serve
        serve(a.db, a.page, a.bridge, a.port)
    elif a.cmd == "publish":
        from .publish import publish
        fs = publish(a.db, a.out_dir, a.bridge)
        print(f"{len(fs)} files -> {a.out_dir}")
    elif a.cmd == "bridge3d":
        import duckdb
        from .dashboard import bridge_models, write_bridge3d
        con = duckdb.connect(a.db, read_only=True)
        con.execute("LOAD spatial")
        print(write_bridge3d(bridge_models(con, a.bridge)[0], a.out))
    elif a.cmd == "bridge":
        from .bridge_profile import write
        print("\n".join(write(a.osm, a.gmns, a.name, a.out_dir)))
    elif a.cmd == "mapillary":
        from .mapillary import main as mly
        mly(a.db, a.osm)
    else:
        from .dashboard import main as dash
        dash(a.db, a.out, a.bridge)
    return 0


if __name__ == "__main__":
    sys.exit(main())
