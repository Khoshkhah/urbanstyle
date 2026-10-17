"""The street objects, one per real thing (docs/design/objects.md): OSM's objects, a city's survey and Mapillary's detections, matched
by unit.match. The build writes urban.object from them (product.py); the page and the server draw them. No roadstyle here: the build
runs without it."""
import json
import os

import duckdb

from urbanstyle.mapillary import CLASS_OF as _CLASS_OF

SEEN_CLASS = {g: c for g, c in _CLASS_OF.items() if c.startswith("furniture.")}     # the observations that are street objects


NOT_OBJECTS = ("crossing.", "kerb.")   # points of the network, drawn as ground and paint (crosswalks, kerbs), not as objects


def _fields(attrs):
    """A source's own fields of an object, as "key: value; ...", without the empty ones and positions."""
    try:
        d = json.loads(attrs) if isinstance(attrs, str) else (attrs or {})
    except ValueError:
        return str(attrs or "")
    return "; ".join(f"{k}: {v}" for k, v in d.items() if v not in (None, "", "None") and k not in ("geo_point_2d", "geom")) if isinstance(d, dict) else str(d)


def matched_objects(con, epsg, db):
    """The area's street objects, one per real object (unit.match): OSM's objects, Mapillary's points and, where a unit's dossier lies
    next to `db`, its city objects. [(id, class, level, grp, point in metres, refs, sources, height or None, details)]: the id,
    position and level of its best source, every source's id, a measured height where a source has one, what each source says of it
    ("vancouver: common_name: CHERRY; height_m: 7.6 | osm: natural: tree") and how each got it, in the order of refs ("vancouver:
    approximate; mapillary: observed": OSM mapped, Mapillary observed, a city by its own accuracy note, unit.VAN_METHOD). Each class is matched within its level. Crossing and
    kerb points are left out (NOT_OBJECTS): they are drawn as the crosswalk and the kerb."""
    import shapely
    from urbanstyle.unit import CONFIDENCE, match
    to_m = lambda col="geometry", crs="EPSG:4326": f"ST_AsWKB(ST_Transform({col}, '{crs}', '{epsg}', always_xy := true))"
    info = {}                                       # id -> what its source says of it (tags, a city's fields, when photos saw it)
    items = []
    for oid, cls, lv, w, attrs in con.execute(f"SELECT object_id, class, level, {to_m()}, attrs::VARCHAR FROM work.object").fetchall():
        if not cls.startswith(NOT_OBJECTS):
            items.append((oid, cls, lv, None, "osm", shapely.from_wkb(bytes(w)), None, "mapped", None))
            info[str(oid)] = _fields(attrs)
    seen = {}
    try:
        for fid, val, grp, a, b, w in con.execute(f"SELECT feature_id, class, grp, first_seen, last_seen, {to_m()} FROM work.observed").fetchall():
            if grp in SEEN_CLASS:
                items.append((fid, SEEN_CLASS[grp], 0, grp, "mapillary", shapely.from_wkb(bytes(w)), None, "observed", None))
                seen[fid] = (a, b)
                info[str(fid)] = f"{val}; " * bool(val) + (f"seen {a:%Y-%m-%d} .. {b:%Y-%m-%d}" if a and b else "")
    except duckdb.CatalogException:
        pass
    dos, city = db.replace(".urban.duckdb", ".duckdb"), db.replace(".urban.duckdb", ".vancouver.json")
    if city != db and os.path.exists(city):         # a city's surveyed objects around the unit, all of them (the dossier holds the unit's)
        import pyproj
        from urbanstyle.unit import VAN_OBJECT, van_method
        fwd = pyproj.Transformer.from_crs("EPSG:4326", epsg, always_xy=True).transform
        for ds, fc in json.load(open(city)).items():
            for i, ft in enumerate(fc["features"]):
                if ds in VAN_OBJECT and ft["geometry"] and ft["geometry"]["type"] == "Point":
                    h, d = ((ft["properties"] or {}).get(k) for k in ("height_m", "diameter_cm"))
                    items.append((f"{ds}-{i}", VAN_OBJECT[ds], 0, None, "vancouver", shapely.Point(fwd(*ft["geometry"]["coordinates"][:2])),
                                  float(h) if isinstance(h, (int, float)) and h > 0 else None, van_method(ds, ft["properties"]),
                                  d / 100 if isinstance(d, (int, float)) and d > 0 else None))
                    info[f"{ds}-{i}"] = _fields(ft["properties"])
    elif dos != db and os.path.exists(dos):
        con.execute(f"ATTACH IF NOT EXISTS '{dos}' AS dos (READ_ONLY)")
        crs = con.execute("SELECT crs FROM dos.unit").fetchone()[0]
        items += [(oid, cls, 0, None, src, shapely.from_wkb(bytes(w)), h, meth, wd) for oid, cls, src, w, h, meth, wd in con.execute(
            f"""SELECT object_id, class, source, {to_m(crs=crs)}, CASE WHEN height_source <> 'urbanstyle' THEN height_m END, method,
                CASE WHEN width_source <> 'urbanstyle' THEN width_m END FROM dos.object WHERE source NOT IN ('osm', 'mapillary')""").fetchall()]
    if not items:
        return []
    m = duckdb.connect()
    m.execute("LOAD spatial")
    m.execute("CREATE TABLE object (object_id VARCHAR, class VARCHAR, source VARCHAR, height_m DOUBLE, confidence DOUBLE, geometry GEOMETRY)")
    m.executemany("INSERT INTO object VALUES (?, ?, ?, NULL, ?, ST_GeomFromWKB(?))",       # confidence: by how the source got it (method)
                  [(str(oid), f"{cls}@{lv}", src, CONFIDENCE.get(meth, 0.5), shapely.to_wkb(p)) for oid, cls, lv, _, src, p, _h, meth, _w in items])
    match(m, {str(k): v for k, v in seen.items()})
    by_id = {str(i[0]): i for i in items}
    out = []
    for refs, sources in m.execute("SELECT refs, sources FROM match").fetchall():
        oid, cls, lv, grp, _, p, _h, _m, _w = by_id[refs.split(", ")[0]]      # the best source's
        # a measured height and width (a city's tree: height, trunk), from any source, with who measured them and how
        hr = next((r for r in refs.split(", ") if by_id[r][6]), None)
        wr = next((r for r in refs.split(", ") if by_id[r][8]), None)
        h = (by_id[hr][6], f"{by_id[hr][4]} ({by_id[hr][7]})") if hr else None
        wd = (by_id[wr][8], f"{by_id[wr][4]} ({by_id[wr][7]})") if wr else None
        details = " | ".join(f"{by_id[r][4]}: {info[r]}" for r in refs.split(", ") if info.get(r))
        methods = "; ".join(f"{by_id[r][4]}: {by_id[r][7]}" for r in refs.split(", "))      # in the order of refs
        out.append((oid, cls, lv, grp, p, refs, sources, h, details, methods, wd))
    return out
