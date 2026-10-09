"""A subsection as a Streetmix street (streetmix.net, schema version 35): its cross-section across the middle, left to right.

    python -m urbanstyle.streetmix data/monaco.duckdb 's0-908826265278346607/7' [--post]

A subsection is uniform along its length by construction (it is split where the cross-section or the frontage changes), so one
Streetmix profile describes it. The line across its middle is read part by part (space.part) and each part becomes a Streetmix segment
with its width; neighbours of the same kind are merged. Streetmix looks along the street: `outbound` lanes run away from the viewer, so with
right-hand traffic a subsection's forward lanes are outbound and on the right. The buildings either side become its boundaries.
--post creates the street on streetmix.net (anonymous, public by its link) and prints the link.
"""
import json
import math
import sys
import uuid

KERB_M = 0.15   # a sidewalk's height above the road
PARKING_MIN_M = 1.5   # a shoulder narrower than this is a painted strip, not a parking lane


def _segment(typ, direction, side, extra, width=0.0):
    """(Streetmix type, variantString) for one of our parts; `side` 'left' / 'right' of the street seen along it."""
    way = "outbound" if direction in ("forward", "out") else "inbound"
    if typ == "lane":
        return "drive-lane", f"{way}|car"
    if typ == "bus lane":
        return "bus-lane", f"{way}|shared|typical"
    if typ == "cycle lane":
        return "bike-lane", f"{'inbound' if side == 'left' else 'outbound'}|green|road"
    if typ == "shoulder":       # wide enough to park in, else a painted strip
        return ("parking-lane", f"{'inbound' if side == 'left' else 'outbound'}|{side}") if width >= PARKING_MIN_M else ("divider", "striped-buffer")
    if typ == "island":
        return "divider", "median"
    if typ == "furnishing":
        return ("sidewalk-tree", "big") if "tree" in extra else ("sidewalk-lamp", f"{'right' if side == 'left' else 'left'}|modern")
    if typ == "open":
        return "sidewalk", "empty"
    if typ in ("carriageway", "crosswalk", "junction box"):
        return "drive-lane", f"{way}|car"
    return "sidewalk", "normal"


def export(con, sid, epsg):
    """The Streetmix street (its `data.street`) of subsection `sid`."""
    import shapely
    m = lambda col="geometry": f"ST_AsWKB(ST_Transform({col}, 'EPSG:4326', '{epsg}', always_xy := true))"
    g = lambda w: shapely.make_valid(shapely.from_wkb(bytes(w)))
    sec, line_w, left_m, right_m, level = con.execute(f"""SELECT section_id, {m()}, left_m, right_m, level FROM space.subsection
                                                          WHERE subsection_id = ?""", [sid]).fetchone()
    line = g(line_w)
    unit = g(con.execute(f"SELECT {m()} FROM space.unit WHERE unit_id = ?", [sid]).fetchone()[0])
    t = line.length / 2
    mid, q0, q1 = line.interpolate(t), line.interpolate(max(t - 1, 0)), line.interpolate(min(t + 1, line.length))
    h = math.hypot(q1.x - q0.x, q1.y - q0.y) or 1.0
    tx, ty = (q1.x - q0.x) / h, (q1.y - q0.y) / h
    nx, ny = -ty, tx                                                     # the left normal
    cross = shapely.LineString([(mid.x + nx * 60, mid.y + ny * 60), (mid.x - nx * 60, mid.y - ny * 60)])   # left to right
    trees = [g(w) for (w,) in con.execute(f"SELECT {m()} FROM space.object WHERE class = 'vegetation.tree' AND level = ?", [level]).fetchall()]
    pieces = []      # (offset of the middle, left positive; width; part type; direction; what stands on it)
    for typ, d, w in con.execute(f"SELECT type, coalesce(direction, ''), {m()} FROM space.part WHERE unit_id = ?", [sid]).fetchall():
        poly = g(w)
        for seg in shapely.get_parts(cross.intersection(poly)):
            if seg.geom_type != "LineString" or seg.length < 0.05:
                continue
            c = seg.interpolate(0.5, normalized=True)
            extra = "tree" if any(p.distance(poly) < 0.5 for p in trees) else ""
            pieces.append(((c.x - mid.x) * nx + (c.y - mid.y) * ny, seg.length, typ, d, extra))
    pieces.sort(key=lambda p: -p[0])                                     # left (largest offset) first
    segments = []
    for off, w, typ, d, extra in pieces:
        st, var = _segment(typ, d, "left" if off > 0 else "right", extra, w)
        elev = KERB_M if st.startswith("sidewalk") else 0.0
        if segments and segments[-1]["type"] == st and segments[-1]["variantString"] == var:
            segments[-1]["width"] = round(segments[-1]["width"] + w, 2)
        else:
            segments.append({"id": uuid.uuid4().hex[:21], "type": st, "variantString": var, "width": round(w, 2),
                             "elevation": elev, "slope": {"on": False, "values": []}})

    def boundary(bounded, end):
        if not bounded:
            return {"id": uuid.uuid4().hex[:21], "variant": "grass", "floors": 1, "elevation": KERB_M}
        floors, known = con.execute(f"""SELECT max(level_max) + 1, bool_or(level_src <> 'default') FROM space.element WHERE type = 'building'
                                 AND level_min <= 0 AND ST_DWithin({m().replace('ST_AsWKB(', '(')}, ST_GeomFromText(?), 3)""", [end.wkt]).fetchone()
        return {"id": uuid.uuid4().hex[:21], "variant": "narrow", "floors": int(floors) if known else 4, "elevation": KERB_M}   # height unknown: 4
    inside = cross.intersection(unit)
    ends = shapely.get_parts(inside)
    left_end = shapely.Point(ends[0].coords[0]) if len(ends) else mid
    right_end = shapely.Point(ends[-1].coords[-1]) if len(ends) else mid
    name = con.execute("SELECT any_value(name) FROM space.container WHERE container_id = ?", [sec]).fetchone()[0] or sid
    lon, lat = con.execute(f"SELECT ST_X(p), ST_Y(p) FROM (SELECT ST_Transform(ST_GeomFromText(?), '{epsg}', 'EPSG:4326', always_xy := true) AS p)",
                           [mid.wkt]).fetchone()
    bl, br = boundary(left_m is not None, left_end), boundary(right_m is not None, right_end)
    return {
        "schemaVersion": 35, "id": str(uuid.uuid4()), "units": 0, "width": round(sum(s["width"] for s in segments), 2),
        "name": name, "location": {"latlng": {"lat": round(lat, 6), "lng": round(lon, 6)}, "label": f"{name}, Monaco",
                                   "hierarchy": {"country": "Monaco", "street": name}, "wofId": None, "geometryId": None, "intersectionId": None},
        "userUpdated": True, "skybox": "day", "weather": None, "showAnalytics": False, "editCount": 0,
        "boundary": {"left": bl, "right": br},
        "leftBuildingVariant": bl["variant"], "leftBuildingHeight": bl["floors"], "rightBuildingVariant": br["variant"], "rightBuildingHeight": br["floors"],
        "segments": segments,
    }


def post(street):
    """Create the street on streetmix.net (anonymous: public to anyone with its link). Returns the link."""
    import datetime
    import urllib.request
    body = json.dumps({"name": street["name"], "clientUpdatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                       "data": {"street": street}}).encode()
    req = urllib.request.Request("https://streetmix.net/api/v1/streets", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "urbanstyle"})
    made = json.load(urllib.request.urlopen(req, timeout=60))
    return f"https://streetmix.net/-/{made['namespacedId']}", made


if __name__ == "__main__":
    import duckdb
    db, sid = sys.argv[1], sys.argv[2]
    con = duckdb.connect(db, read_only=True)
    con.execute("LOAD spatial")
    lon = con.execute("SELECT avg(ST_X(ST_Centroid(geometry))) FROM space.unit").fetchone()[0]
    street = export(con, sid, f"EPSG:{32600 + int((lon + 180) // 6) + 1}")
    print(json.dumps(street, indent=1))
    if "--post" in sys.argv:
        url, made = post(street)
        print(url)
