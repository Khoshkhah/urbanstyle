"""The `urbanstyle` command: build, check, quality, dashboard, layers, mapillary, unit, bridge, serve, publish, ..."""
import argparse
import sys


from .schema import migrate  # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(prog="urbanstyle", description="Space containers from a duckOSM database.")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build the space schema from a duckOSM database")
    b.add_argument("osm", help="duckOSM .duckdb (a copy with features is made next to OUT if it has none)")
    b.add_argument("out", help="output .duckdb")
    b.add_argument("--bridge", action="extend", nargs="+", default=[], metavar="PROFILE",
                   help="a bridge profile (<name>.bridge.json): its ways are the bridge model's, the ground draws none of them")
    b.add_argument("--from", dest="start", choices=["blocks", "division", "ground"], help="only the street division and the steps after it, from the copy "
                   "the last full build kept (OUT.before-division): for a fix in network.py; `ground`: the ground steps only, from OUT.before-ground")
    ck = sub.add_parser("check", help="conformance checks; exit 1 if a hard check fails")
    ck.add_argument("db", nargs="+")
    ck.add_argument("--bridge", action="extend", nargs="+", default=[], help="bridge profiles: the bridge model's checks too (BR1-BR12)")
    sub.add_parser("quality", help="shape quality of the sections").add_argument("db", nargs="+")
    d = sub.add_parser("dashboard", help="an offline HTML map with the hierarchy tree (needs roadstyle)")
    d.add_argument("db")
    d.add_argument("out")
    d.add_argument("--bridge", action="extend", nargs="+", metavar="PROFILE",
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
    bt = sub.add_parser("bridge-terrain", help="the ground round a bridge from LiDAR ground points, as a grid the profile names (the conda env `lidar`)")
    bt.add_argument("profile", help="a <name>.bridge.json: it gets the key terrain")
    bt.add_argument("out", help="the grid, an .npz file")
    bt.add_argument("--lidar", nargs="+", required=True, help="LiDAR tiles (.laz, .copc.laz) with classified ground points")
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
    b3.add_argument("--bridge", action="extend", nargs="+", required=True, help="a bridge profile, as for the dashboard")
    st = sub.add_parser("structure", help="the bridges' structure only (rank 0 of docs/notes/bridges-ranks.md: one height surface, slab, approach, parapet, piers), to the page's bridge3d.json")
    st.add_argument("db", help="the unit's space db (the roads' levels)")
    st.add_argument("out", help="the JSON file beside the page, e.g. viz/cut-france.bridge3d.json")
    st.add_argument("--bridge", action="extend", nargs="+", required=True, help="a bridge profile, as for the dashboard")
    st.add_argument("--rank0", action="store_true", help="the surface only, nothing on it")
    st.add_argument("--no-lidar", action="store_true", help="ignore the profile's measured heights: the rules alone")
    st.add_argument("--plan", help="also write a 2D plan of each bridge (centre lines, widths, edges) to this HTML file")
    st.add_argument("--gmns", help="the bridge's SUMO (duckOSM GMNS): the structure on the accepted steps 1 to 4 (docs/notes/bridge-steps.md, step 5)")
    sv = sub.add_parser("serve", help="the dashboard page with the Explore panel (search, filters, AI questions) on a local server")
    sv.add_argument("db", help="the unit's space db")
    sv.add_argument("page", help="a page `urbanstyle dashboard` built, e.g. viz/broadway-granville-v92.html (its folder is served)")
    sv.add_argument("--bridge", action="extend", nargs="+", default=[], help="a bridge profile: its parts can be searched too")
    sv.add_argument("--port", type=int, default=8784, help="8784: the port Street View's key allows")
    pb = sub.add_parser("publish", help="the dashboard as static files for a web site with no server (docs/design/online-dashboard.md)")
    pb.add_argument("db", help="the unit's space db")
    pb.add_argument("out_dir", help="the folder to write: index.html, static.js, bridge3d.json, data/")
    pb.add_argument("--bridge", action="extend", nargs="+", default=[], help="a bridge profile, as for the dashboard")
    a = p.parse_args(argv)
    for key in ('db', 'dbs', 'out'):     # (an old database: its schema renamed first)
        for path in ([getattr(a, key)] if isinstance(getattr(a, key, None), str) else (getattr(a, key, None) or [])):
            if path and str(path).endswith('.duckdb') and a.cmd not in ('build', 'unit') and __import__('os').path.exists(path):
                migrate(path)

    if a.cmd == "build":
        from .container import build, counts, with_features
        c = build(with_features(a.osm, a.out.replace(".duckdb", ".osm.duckdb")), a.out, a.start, a.bridge)
        print("level  type       n")
        for l, t, n in counts(c):
            print(f"{l:>5}  {t:<9} {n}")
        print("links:", c.execute("SELECT type, level_a, level_b, count(*) FROM work.link GROUP BY ALL ORDER BY ALL").fetchall())
        print("next: urbanstyle dashboard", a.out, "viz/<area>.html")
    elif a.cmd == "check":
        from .checks import bridge, run
        from .meta import write_checks
        failed = False
        for i, x in enumerate(a.db):      # each database gets its rows in urban.check; the bridges' rows go to the first
            rows = []
            failed |= run(x, rows)
            if i == 0:
                for b in a.bridge:
                    failed |= bridge(b, x, rows)
            write_checks(x, rows)
        return 1 if failed else 0
    elif a.cmd == "quality":
        from .quality import run
        for x in a.db:
            run(x)
    elif a.cmd == "unit":
        from .unit import main as unit
        unit(a.name, a.at[0], a.at[1], a.osm, a.city, not a.no_mapillary, a.vancouver, a.gtfs)
    elif a.cmd == "layers":
        from .dashboard import layers
        print(layers(a.db, a.out))
    elif a.cmd == "bridge-heights":
        from .bridge_heights import write as heights
        print(heights(a.profile, a.heights, a.out), "axes ->", a.out)
    elif a.cmd == "bridge-terrain":
        from .bridge_terrain import write as terrain
        print(terrain(a.profile, a.out, a.lidar))
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
    elif a.cmd == "structure":
        import duckdb
        con = duckdb.connect(a.db, read_only=True)
        con.execute("LOAD spatial")
        from .bridge_surface import models
        from .dashboard import write_bridge3d
        ms, _ = models(con, a.bridge, rank0=a.rank0, lidar=not a.no_lidar, gmns=a.gmns)
        if len(ms) > 1:     # (an area's file: all bridges in the first one's frame, so the viewer shows them where they are)
            import math as _m
            def merc(lon, lat):
                return _m.radians(lon) * 6378137.0, _m.log(_m.tan(_m.pi / 4 + _m.radians(lat) / 2)) * 6378137.0
            (X0, Y0), k0 = merc(*ms[0]["origin"]), _m.cos(_m.radians(ms[0]["origin"][1]))
            for m in ms[1:]:
                X, Y = merc(*m["origin"]); dx, dy = (X - X0) * k0, (Y - Y0) * k0
                mv = lambda v: [round(v[0] + dx, 2), round(v[1] + dy, 2)] + list(v[2:])
                m["verts"] = [mv(v) for v in m["verts"]]
                for s_ in m["surf"]:
                    s_["v"] = [mv(v) for v in s_["v"]]
                for q in m["piers"] + m.get("truss", []):
                    q["a"], q["b"] = mv(q["a"]), mv(q["b"])
                m["origin"] = ms[0]["origin"]
        for m in ms:
            print(m["name"], m["solve"], "structures:", m["structures"])
            for c in m["checks"]:
                print(f"  {c[0]} {'fail' if c[2] and c[3] else 'pass' if not c[2] else 'info'} {c[2]}  {c[1]}")
        print(write_bridge3d(ms, a.out))
        import os as _os
        import shutil as _sh
        _sh.copy(_os.path.join(_os.path.dirname(__file__), "rank0.html"), _os.path.join(_os.path.dirname(_os.path.abspath(a.out)), "rank0.html"))
        print("viewer:", "rank0.html?m=" + _os.path.basename(a.out))
        if a.plan:
            import json as _json
            from .bridge_surface import plan_html
            for pf in a.bridge:
                print(plan_html(con, _json.load(open(pf)), a.plan))
    elif a.cmd == "bridge3d":
        import duckdb
        from .dashboard import bridge_models, write_bridge3d
        con = duckdb.connect(a.db, read_only=True)
        con.execute("LOAD spatial")
        print(write_bridge3d(bridge_models(con, a.bridge, a.db)[0], a.out))
    elif a.cmd == "bridge":
        from .bridge_profile import write
        print("\n".join(write(a.osm, a.gmns, a.name, a.out_dir)))
    elif a.cmd == "mapillary":
        from .mapillary import main as mly
        mly(a.db, a.osm)
    else:
        from .page import build as dash      # the dashboard: one page, one panel (page.py)
        dash(a.db, a.out, a.bridge)
    return 0


if __name__ == "__main__":
    sys.exit(main())
