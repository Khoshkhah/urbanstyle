"""One unit in full: its dossier (docs/design/unit-dossier.md).

    urbanstyle unit skanstull --at 18.07660 59.30776 --osm data/sodermalm.osm.duckdb \\
        --nvdb ../fetching-sweden-data/data/processed/sodermalm_traffic.duckdb \\
        --flows '../sensor-matching/areas/sodermalm/observations/*.parquet'
    urbanstyle unit broadway-granville --at -123.13860 49.26330 --osm ../duckOSM/data/db/vancouver_city.duckdb --vancouver

1. clip   a small duckOSM database around the unit (CLIP_M), so urbanstyle builds only its neighbourhood: its outline (the
          partition), SUMO's lanes and the parts, in about a minute;
   A database without duckOSM's features (Södermalm, Vancouver) gets a copy with them first: data/<its name>.osm.duckdb.
2. build  urbanstyle on the clip (Mapillary loaded when `<out>.mapillary.json` is there);
3. dossier  the unit's own file, `data/units/<name>.duckdb`: the tables of the design note, every row with its provenance
          (`source`, `method`, `observed`, `confidence`). Geometry in metres (the local UTM zone, `unit.crs`).

Methods: `surveyed` (a city's own survey), `mapped` (OSM, a register), `measured` (measured here from mapped lines),
`observed` (seen in photos: Mapillary), `derived` (computed from other rows, e.g. SUMO's lanes), `estimated` (a default),
`checked` (verified by hand).
"""
import datetime
import glob
import os

CLIP_M = 400.0      # the neighbourhood built around a unit: enough for its arms, its neighbours and their cuts
FLOW_M = 60.0       # traffic counted on a road this close to the unit belongs to it
CONFIDENCE = {"surveyed": 0.9, "recorded": 0.7, "mapped": 0.7, "measured": 0.6, "observed": 0.5, "derived": 0.5, "approximate": 0.4,
              "estimated": 0.3, "checked": 1.0}
HEIGHT = {"furniture.lamp": 7.6, "furniture.signal": 3.3, "furniture.sign": 2.6, "furniture.bench": 0.9, "furniture.waste": 1.0,
          "furniture.bollard": 0.9, "vegetation.tree": 7.5, "transit.stop": 2.7, "furniture.post_box": 1.2, "furniture.parking_meter": 1.5,
          "furniture.hydrant": 0.8, "furniture.water": 1.0, "furniture.map_stand": 2.4, "utility.manhole": 0.0, "utility.catch_basin": 0.0,
          "utility.junction_box": 0.0}

# City of Vancouver open data (Opendatasoft Explore API v2.1, no key; Open Government Licence - Vancouver): the city's surveyed
# layers, fetched by `opendata_vancouver` and loaded by `dossier`. Dataset -> object class; the other datasets give rules and observations.
VAN_API = "https://opendata.vancouver.ca/api/explore/v2.1/catalog/datasets"
VAN_OBJECT = {"public-trees": "vegetation.tree", "street-lighting-poles": "furniture.lamp",
              "parking-meters": "furniture.parking_meter", "water-hydrants": "furniture.hydrant", "drinking-fountains": "furniture.water",
              "wayfinding-map-stands": "furniture.map_stand", "sewer-manholes": "utility.manhole", "sewer-catch-basins": "utility.catch_basin",
              "street-lighting-junction-boxes": "utility.junction_box"}
VAN_OTHER = ("traffic-signals", "disability-parking", "right-of-way-widths", "bikeways", "sidewalk-condition-rating", "pavement-condition-rating",
             "pavement-condition-rating-major-road-network-2023", "intersection-traffic-movement-counts", "directional-traffic-count-locations")

MATCH_M = 10.0      # objects of one class from two sources this close are one real object (Mapillary's positions are 1-5 m off, often more)
RANK = {"vancouver": 0, "nvdb": 1, "osm": 2, "mapillary": 3}   # whose position a matched object takes: a city's survey, a map, photos


# how good a city record's position is, in the city's own words (each dataset's "Data accuracy" note, read 2026-10-09): surveyed
# ("survey accuracy"), approximate ("approximate locations", "shown for entire block faces", "the approximate centre of the
# intersection", "follow street centrelines") or recorded (a register, accuracy not stated). A record that calls itself approximate
# (a catch basin's label "Catch Basin (location approximate)") is approximate whatever its dataset says.
VAN_METHOD = {"street-lighting-poles": "surveyed", "sewer-manholes": "surveyed", "sewer-catch-basins": "surveyed",
              "street-lighting-junction-boxes": "surveyed", "traffic-signals": "approximate", "parking-meters": "approximate",
              "drinking-fountains": "approximate", "wayfinding-map-stands": "approximate", "disability-parking": "approximate",
              "right-of-way-widths": "approximate", "bikeways": "approximate", "intersection-traffic-movement-counts": "approximate",
              "directional-traffic-count-locations": "approximate", "public-trees": "recorded", "water-hydrants": "recorded"}


def van_method(ds, props):
    """The method of a city record (VAN_METHOD), approximate where the record says so itself."""
    if any(isinstance(v, str) and "approximate" in v.lower() for v in (props or {}).values()):
        return "approximate"
    return VAN_METHOD.get(ds, "recorded")


def van_meter_rule(p):
    """A Vancouver parking meter's rule in words, from its record: "pay $4.50/h 9am-6pm (2 Hr), $1.50/h 6pm-10pm (4 Hr); no parking ..."."""
    pay = [f"{r}/h {when}" + (f" ({lim})" if lim else "") for r, lim, when in
           ((p.get("rate_9am_6pm"), p.get("time_limit_9am_6pm"), "9am-6pm"), (p.get("rate_6pm_10pm"), p.get("time_limit_6pm_10pm"), "6pm-10pm")) if r]
    pay += [f"flat {p['flat_rate']}"] if p.get("flat_rate") else []
    no = [f"rush hours {p[k]}" for k in ("am_rush_hours", "pm_rush_hours") if p.get(k)]
    no += [" ".join(str(p[f"prohibition_{i}_{x}"]) for x in ("days", "time") if p.get(f"prohibition_{i}_{x}")) for i in (1, 2) if p.get(f"prohibition_{i}_time")]
    who = "" if p.get("vehicle_type") in (None, "Any Vehicle") else f" ({p['vehicle_type']})"
    return "pay " + ", ".join(pay or ["(rates not given)"]) + who + ("; no parking " + ", ".join(no) if no else "")


def group_objects(rows, seen):
    """The real objects among `rows` [(object_id, class, source, height_m, confidence, point in metres)] of several sources:
    [[class, [(object_id, source, point, height_m, confidence)]]], each group's members best source first (RANK). The rules of `match`."""
    newest = lambda oid: -(seen[oid][1].timestamp() if seen.get(oid, (None, None))[1] else 0)
    rows = sorted(rows, key=lambda r: (RANK.get(r[2], 9), newest(r[0])))
    apart = lambda a, b: a is not None and b is not None and None not in (*a, *b) and (a[1] <= b[0] or b[1] <= a[0])
    # members a and b may be one object: no source twice, unless two Mapillary features seen at different times
    fits = lambda a, b: all(x[1] != y[1] or (x[1] == "mapillary" and apart(seen.get(x[0]), seen.get(y[0]))) for x in a for y in b)
    groups = []     # [class, [(object_id, source, point, height, confidence)]]
    for oid, cls, src, h, conf, p in rows:     # ponytail: greedy and O(objects x groups), fine for one unit; a tree for a whole city
        best = None
        for g in groups:
            if g[0] != cls:
                continue
            d = min(p.distance(m[2]) for m in g[1])
            if d <= MATCH_M and (best is None or d < best[0]) and fits([(oid, src)], g[1]):
                best = (d, g)
        if best is None:
            best = (0, [cls, []])
            groups.append(best[1])
        best[1][1].append((oid, src, p, h, conf))
    merged = True   # then two groups that are one object (each joined a different neighbour first) become one
    while merged:
        merged = False
        for i, j in ((i, j) for i in range(len(groups)) for j in range(i + 1, len(groups))):
            a, b = groups[i], groups[j]
            if a[0] == b[0] and min(x[2].distance(y[2]) for x in a[1] for y in b[1]) <= MATCH_M and fits(a[1], b[1]):
                a[1] = sorted(a[1] + b[1], key=lambda m: (RANK.get(m[1], 9), newest(m[0])))
                del groups[j]
                merged = True
                break
    return groups


def match(con, seen):
    """`match`: one row per real object, the objects of all sources that stand for it (`object.match_id`). Objects of one class within
    MATCH_M of a member join it, nearest first, at most one per source; except that two Mapillary features seen in periods that do not
    overlap (`seen`: id -> (first, last)) are one object detected again from newer photos. Position and height from the best source
    (RANK); confidence: any one of its sources right (1 - product of 1 - confidence)."""
    import shapely
    rows = [(oid, cls, src, h, conf, shapely.from_wkb(bytes(wkb))) for oid, cls, src, h, conf, wkb in
            con.execute("SELECT object_id, class, source, height_m, confidence::DOUBLE, ST_AsWKB(geometry) FROM object").fetchall()]
    groups = group_objects(rows, seen)
    con.execute("ALTER TABLE object ADD COLUMN match_id VARCHAR")
    con.execute("""CREATE TABLE match (match_id VARCHAR, class VARCHAR, n_sources INT, sources VARCHAR, refs VARCHAR, height_m DOUBLE,
                   confidence DOUBLE, geometry GEOMETRY)""")
    out, links = [], []
    for k, (cls, ms) in enumerate(groups):
        mid = f"m{k + 1}"
        srcs = sorted({m[1] for m in ms}, key=lambda x: RANK.get(x, 9))
        miss = 1.0
        for x in srcs:
            miss *= 1 - max(m[4] for m in ms if m[1] == x)
        out.append((mid, cls, len(srcs), ", ".join(srcs), ", ".join(m[0] for m in ms), ms[0][3], round(1 - miss, 2), shapely.to_wkb(ms[0][2])))
        links += [(mid, m[0]) for m in ms]
    con.executemany("INSERT INTO match VALUES (?, ?, ?, ?, ?, ?, ?, ST_GeomFromWKB(?))", out)
    con.executemany("UPDATE object SET match_id = ? WHERE object_id = ?", links)


def clip(src, out, lon, lat, radius=CLIP_M):
    """A duckOSM database holding only what lies within `radius` m of (lon, lat): the mode networks (edges, their nodes, the turn
    graph between kept edges and the turns open or closed to some vehicles), the raw tags of their ways, the raw nodes and the feature
    layers in the box."""
    import duckdb
    if os.path.exists(out):
        os.remove(out)
    con = duckdb.connect(out)
    con.execute("INSTALL spatial; LOAD spatial")
    con.execute(f"ATTACH '{src}' AS s (READ_ONLY)")
    dlat, dlon = radius / 111320, radius / (111320 * max(0.1, __import__("math").cos(__import__("math").radians(lat))))
    box = f"ST_MakeEnvelope({lon - dlon}, {lat - dlat}, {lon + dlon}, {lat + dlat})"
    for schema in ("driving", "walking", "cycling", "features", "raw", "main"):
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    for mode in ("driving", "walking", "cycling"):
        con.execute(f"CREATE TABLE {mode}.edges AS SELECT * FROM s.{mode}.edges WHERE ST_Intersects(geometry, {box})")
        con.execute(f"""CREATE TABLE {mode}.nodes AS SELECT * FROM s.{mode}.nodes WHERE node_id IN
                        (SELECT source FROM {mode}.edges UNION SELECT target FROM {mode}.edges)""")
        con.execute(f"""CREATE TABLE {mode}.edge_graph AS SELECT * FROM s.{mode}.edge_graph
                        WHERE from_edge IN (SELECT edge_id FROM {mode}.edges) AND to_edge IN (SELECT edge_id FROM {mode}.edges)""")
        for t in ("turn_permission", "turn_path_restrictions"):   # turns for some vehicles only, via-way restrictions (duckOSM)
            try:
                con.execute(f"""CREATE TABLE {mode}.{t} AS SELECT * FROM s.{mode}.{t}
                                WHERE from_edge IN (SELECT edge_id FROM {mode}.edges) AND to_edge IN (SELECT edge_id FROM {mode}.edges)""")
            except duckdb.CatalogException:     # without them every turn some vehicles may not take would be open to all
                if mode == "driving":           # (only driving has turn restrictions, so only it has via-way paths)
                    raise SystemExit(f"{src} has no {mode}.{t}: it was built by an older duckOSM; rebuild it (duckosm build)")
    con.execute("""CREATE TABLE raw.ways AS SELECT * FROM s.raw.ways WHERE osm_id IN
                   (SELECT osm_id FROM driving.edges UNION SELECT osm_id FROM walking.edges UNION SELECT osm_id FROM cycling.edges)""")
    con.execute(f"CREATE TABLE raw.nodes AS SELECT * FROM s.raw.nodes WHERE ST_Intersects(ST_Point(lon, lat), {box})")
    for (t,) in con.execute("SELECT table_name FROM duckdb_tables() WHERE database_name = 's' AND schema_name = 'features'").fetchall():
        con.execute(f"CREATE TABLE features.{t} AS SELECT * FROM s.features.{t} WHERE ST_Intersects(geom, {box})")
    con.execute(f"CREATE TABLE main.boundary AS SELECT {box} AS geometry")
    con.close()
    return out


def opendata_vancouver(lon, lat, out, radius=CLIP_M):
    """Every dataset of VAN_OBJECT and VAN_OTHER within `radius` m of (lon, lat), as one file {dataset: GeoJSON FeatureCollection}."""
    import json
    import urllib.parse
    import urllib.request
    where = f"within_distance(geom, geom'POINT({lon} {lat})', {radius:.0f}m)"
    data = {}
    for ds in (*VAN_OBJECT, *VAN_OTHER):
        with urllib.request.urlopen(f"{VAN_API}/{ds}/exports/geojson?" + urllib.parse.urlencode({"where": where}), timeout=120) as r:
            data[ds] = json.load(r)
    with open(out, "w") as f:
        json.dump(data, f)
    return out


def dossier(space_db, osm_db, unit_id, out, name, city, nvdb=None, flows=None, mapillary_json=None, vancouver_json=None):
    """The unit's dossier from a built neighbourhood (`space_db`, urbanstyle's tables) and the other sources."""
    import duckdb
    if os.path.exists(out):
        os.remove(out)
    con = duckdb.connect(out)
    con.execute("INSTALL spatial; LOAD spatial")
    con.execute(f"ATTACH '{space_db}' AS sp (READ_ONLY)")
    con.execute(f"ATTACH '{osm_db}' AS o (READ_ONLY)")
    if nvdb:
        con.execute(f"ATTACH '{nvdb}' AS nv (READ_ONLY)")
    lon = con.execute("SELECT ST_X(ST_Centroid(geometry)) FROM sp.space.unit WHERE unit_id = ?", [unit_id]).fetchone()[0]
    crs = f"EPSG:{32600 + int((lon + 180) // 6) + 1}"
    m = lambda g: f"ST_Transform({g}, 'EPSG:4326', '{crs}', always_xy := true)"
    today = datetime.date.today().isoformat()
    U = f"(SELECT geometry FROM sp.space.unit WHERE unit_id = '{unit_id}')"
    near = lambda g, d=0.5: f"ST_DWithin({m(g)}, {m(U)}, {d})"

    con.execute(f"""CREATE TABLE unit AS SELECT unit_id, kind, '{name}' AS name, '{city}' AS city, level, '{crs}' AS crs, '{today}' AS built,
                    {m('geometry')} AS geometry FROM sp.space.unit WHERE unit_id = '{unit_id}'""")
    sources = [("osm", "OpenStreetMap (duckOSM)", "https://www.openstreetmap.org", "ODbL 1.0", "mapped"),
               ("sumo", "SUMO netconvert on duckOSM, lanes and widths from urbanstyle", "https://eclipse.dev/sumo/", "EPL 2.0 (tool)", "derived"),
               ("urbanstyle", "urbanstyle partition, kerbs and parts", "https://github.com/Khoshkhah/urbanstyle", "MIT", "measured")]
    if nvdb:
        sources.append(("nvdb", "Trafikverket NVDB (Lastkajen)", "https://lastkajen.trafikverket.se", "CC0 1.0", "mapped"))
    if mapillary_json:
        sources.append(("mapillary", "Mapillary map features and photos", "https://www.mapillary.com", "CC BY-SA 4.0", "observed"))
    if flows:
        sources.append(("flows", "Hourly flows per edge (sensor-matching: Trafikverket, Stockholm tube counts)", flows, "per source", "surveyed"))
    if vancouver_json:
        sources.append(("vancouver", "City of Vancouver open data: " + ", ".join((*VAN_OBJECT, *VAN_OTHER)), VAN_API,
                        "Open Government Licence - Vancouver", "per dataset (VAN_METHOD)"))
    con.execute("CREATE TABLE source (source_id VARCHAR, name VARCHAR, origin VARCHAR, licence VARCHAR, method VARCHAR, fetched VARCHAR)")
    con.executemany("INSERT INTO source VALUES (?, ?, ?, ?, ?, ?)", [s_ + (today,) for s_ in sources])
    prov = lambda src, method, observed="NULL::VARCHAR": f"'{src}' AS source, '{method}' AS method, {observed} AS observed, {CONFIDENCE[method]} AS confidence"
    mconf = "CASE meth " + " ".join(f"WHEN '{k}' THEN {v}" for k, v in CONFIDENCE.items()) + " END"
    vprov = f"'vancouver' AS source, meth AS method, NULL::VARCHAR AS observed, {mconf} AS confidence"    # a city record: its own method

    # roads: the road pieces in or touching the unit, with what OSM and NVDB say of them
    con.execute(f"""CREATE TABLE road AS SELECT e.edge_id::VARCHAR AS road_id, e.osm_id, e.name, e.highway AS class, e.oneway, e.lanes AS lanes_per_direction,
                    w.tags['lanes'] AS lanes_tag, try_cast(w.tags['width'] AS DOUBLE) AS width_osm_m, w.tags['maxspeed'] AS maxspeed,
                    w.tags['turn:lanes'] AS turn_lanes, w.tags['surface'] AS surface, {prov('osm', 'mapped')}, {m('e.geometry')} AS geometry
                    FROM o.driving.edges e LEFT JOIN o.raw.ways w USING (osm_id) WHERE {near('e.geometry')}""")
    if nvdb:   # NVDB's measured carriageway width and speed limit, from its link nearest each road piece (within 5 m)
        con.execute(f"""ALTER TABLE road ADD COLUMN width_nvdb_m DOUBLE; ALTER TABLE road ADD COLUMN speed_nvdb VARCHAR;
            UPDATE road r SET width_nvdb_m = n.road_width_m, speed_nvdb = n.speed_limit_fwd FROM (
              SELECT r2.road_id, arg_min(l.road_width_m, ST_Distance(r2.geometry, {m('l.geom')})) AS road_width_m,
                     arg_min(l.speed_limit_fwd, ST_Distance(r2.geometry, {m('l.geom')})) AS speed_limit_fwd
              FROM road r2 JOIN nv.nvdb.road_network l ON ST_DWithin(r2.geometry, {m('l.geom')}, 5) GROUP BY 1) n WHERE r.road_id = n.road_id""")

    # surfaces and lines: urbanstyle's parts and marks of the unit, each part with its source, method and the source's id (parts.PROV)
    ccase = "CASE method " + " ".join(f"WHEN '{k}' THEN {v}" for k, v in CONFIDENCE.items()) + " ELSE 0.3 END"
    con.execute(f"""CREATE TABLE surface AS SELECT part_id AS surface_id, type, direction, arm, lane, width_m,
                    CASE WHEN type IN ('sidewalk', 'furnishing', 'open') THEN 0.15 WHEN type = 'island' THEN 0.2 ELSE 0.0 END AS top_m,
                    road, road_class, speed, surface, lit, holds, rule,
                    coalesce(source, 'urbanstyle') AS source, coalesce(method, 'estimated') AS method, ref, {ccase} AS confidence,
                    {m('geometry')} AS geometry FROM sp.space.part WHERE unit_id = '{unit_id}'""")
    con.execute(f"""CREATE TABLE line AS SELECT row_number() OVER () AS line_id, type, arm, length_m,
                    CASE type WHEN 'stop line' THEN 0.4 WHEN 'give-way line' THEN 0.35 WHEN 'zebra' THEN 0.5 ELSE 0.12 END AS width_m,
                    CASE WHEN type = 'kerb' THEN 'kerb' WHEN type = 'guide line' THEN 'virtual' ELSE 'paint' END AS kind,
                    source, method, ref, {ccase} AS confidence, {m('geometry')} AS geometry FROM sp.space.mark WHERE unit_id = '{unit_id}'""")

    # objects: what OSM maps and what Mapillary's photos see, in or by the unit, with a height
    hcase = "CASE class " + " ".join(f"WHEN '{k}' THEN {v}" for k, v in HEIGHT.items()) + " ELSE 1.0 END"
    con.execute(f"""CREATE TABLE object AS SELECT object_id, class, NULL::VARCHAR AS sign, {hcase} AS height_m, attrs::VARCHAR AS attrs,
                    {prov('osm', 'mapped')}, {m('geometry')} AS geometry FROM sp.space.object WHERE {near('geometry', 3)}""")
    from urbanstyle.mapillary import CLASS_OF
    ccase = "CASE grp " + " ".join(f"WHEN '{g}' THEN '{c}'" for g, c in CLASS_OF.items()) + " ELSE grp END"
    try:
        con.execute(f"""INSERT INTO object SELECT 'mly' || feature_id, {ccase},
                        CASE WHEN grp IN ('give way', 'stop', 'parking', 'no parking') THEN grp END,
                        {hcase.replace("CASE class", f"CASE {ccase}")}, class, {prov('mapillary', 'observed', 'last_seen::DATE::VARCHAR')}, {m('geometry')}
                        FROM sp.space.observed WHERE {near('geometry', 3)}""")
    except duckdb.CatalogException:     # Mapillary not fetched for this area
        pass
    if vancouver_json:  # the city's surveyed objects: a tree's own height and species, a meter's rates
        import json
        with open(vancouver_json) as f:
            van = json.load(f)
        con.execute("CREATE TEMP TABLE van (ds VARCHAR, i INT, p JSON, meth VARCHAR, geometry GEOMETRY)")   # i: its place in the fetched file
        con.executemany("INSERT INTO van VALUES (?, ?, ?, ?, ST_GeomFromGeoJSON(?))", [(ds, i, json.dumps(ft["properties"]), van_method(ds, ft["properties"]),
                        json.dumps(ft["geometry"])) for ds, fc in van.items() for i, ft in enumerate(fc["features"]) if ft["geometry"]])
        con.execute(f"""INSERT INTO object SELECT ds || '-' || i, class, NULL,
                        coalesce(try_cast(p->>'height_m' AS DOUBLE), {hcase}), p::VARCHAR, {vprov}, {m('geometry')}
                        FROM van JOIN (VALUES {", ".join(f"('{d}', '{c}')" for d, c in VAN_OBJECT.items())}) c(ds, class) USING (ds)
                        WHERE {near('geometry', 3)}""")
        # what the city says of each road piece, from its item nearest the piece (within 15 m): legal width, pavement, bikeway
        for col, ds, val in (("row_width", "right-of-way-widths", "(p->>'width') || ' (ft or m)'"), ("pavement", "%pavement-condition%", "p->>'pci_rating'"),
                             ("bikeway", "bikeways", "concat_ws(' ', p->>'bikeway_type', p->>'bikeway_direction')")):
            con.execute(f"""ALTER TABLE road ADD COLUMN {col} VARCHAR;
                UPDATE road r SET {col} = n.v FROM (SELECT r2.road_id, arg_min({val}, ST_Distance(r2.geometry, {m('v.geometry')})) AS v
                  FROM road r2 JOIN van v ON v.ds LIKE '{ds}' AND ST_DWithin(r2.geometry, {m('v.geometry')}, 15) GROUP BY 1) n WHERE r.road_id = n.road_id""")

    # lanes and moves: SUMO's (through urbanstyle's parts and turns)
    con.execute(f"""CREATE TABLE lane AS SELECT part_id AS lane_id, arm AS road_name, direction, lane AS lane_from_right, width_m, type AS kind,
                    {prov('sumo', 'derived')}, {m('geometry')} AS geometry FROM sp.space.part
                    WHERE unit_id = '{unit_id}' AND type IN ('lane', 'bus lane', 'cycle lane')""")
    con.execute(f"""CREATE TABLE movement AS SELECT from_edge, from_lane, to_edge, to_lane, turn, vehicles, condition, {prov('sumo', 'derived')}, {m('geometry')} AS geometry
                    FROM sp.space.turn WHERE unit_id = '{unit_id}'""")

    # rules: speed, parking and turn lanes from OSM's tags on the unit's roads; NVDB's prohibited turns
    con.execute(f"""CREATE TABLE rule AS
        SELECT 'speed' AS kind, maxspeed AS value, road_id AS applies_to, {prov('osm', 'mapped')}, geometry FROM road WHERE maxspeed IS NOT NULL
        UNION ALL SELECT 'turn lanes', turn_lanes, road_id, {prov('osm', 'mapped')}, geometry FROM road WHERE turn_lanes IS NOT NULL
        UNION ALL SELECT k, v, r.road_id, {prov('osm', 'mapped')}, r.geometry
            FROM road r JOIN (SELECT osm_id, unnest(map_keys(tags)) AS k, unnest(map_values(tags)) AS v FROM o.raw.ways) t ON t.osm_id = r.osm_id
            WHERE t.k LIKE 'parking:%'""")
    if nvdb:
        try:
            con.execute(f"""INSERT INTO rule SELECT 'prohibited turn', 'nvdb', NULL, {prov('nvdb', 'mapped')}, {m('geom')}
                            FROM nv.nvdb.prohibited_turns WHERE ST_DWithin({m('geom')}, {m(U)}, 5)""")
        except duckdb.Error:
            pass
    if vancouver_json:  # the city's parking rules (by the unit) and what it says of the unit's roads (within FLOW_M); its right-of-way
        # widths carry no unit: 66, 80, 99 are feet, 17.5 is metres
        con.execute(f"""INSERT INTO rule
            SELECT 'parking meter', concat_ws('; ', p->>'rate_9am_6pm' || ' ' || (p->>'time_limit_9am_6pm') || ' 9-18',
                   p->>'rate_6pm_10pm' || ' ' || (p->>'time_limit_6pm_10pm') || ' 18-22',
                   nullif(p->>'prohibition_1_zone', 'None') || ' ' || (p->>'prohibition_1_days') || ' ' || (p->>'prohibition_1_time')),
                   p->>'meter_id', {vprov}, {m('geometry')} FROM van WHERE ds = 'parking-meters' AND {near('geometry', 3)}
            UNION ALL SELECT 'disability parking', p->>'description', p->>'location', {vprov}, {m('geometry')}
                FROM van WHERE ds = 'disability-parking' AND {near('geometry', 3)}
            UNION ALL SELECT 'right-of-way width', (p->>'width') || ' (ft or m: not stated)', NULL, {vprov}, {m('geometry')}
                FROM van WHERE ds = 'right-of-way-widths' AND {near('geometry', FLOW_M)}
            UNION ALL SELECT 'bikeway', concat_ws(' ', p->>'bikeway_type', p->>'subtype', p->>'bikeway_direction'), p->>'street_name',
                {vprov}, {m('geometry')} FROM van WHERE ds = 'bikeways' AND {near('geometry', FLOW_M)}
            UNION ALL SELECT 'signalised junction', coalesce(p->>'type', 'traffic signals'), NULL, {vprov}, {m('geometry')}
                FROM van WHERE ds = 'traffic-signals' AND {near('geometry', FLOW_M)}""")

    # observations: hourly traffic on the unit's roads; the photos taken in it
    con.execute("CREATE TABLE observation (kind VARCHAR, subject VARCHAR, t VARCHAR, value DOUBLE, unit_of_value VARCHAR, source VARCHAR, method VARCHAR, observed VARCHAR, confidence DOUBLE, geometry GEOMETRY)")
    if flows and glob.glob(flows):
        con.execute(f"""INSERT INTO observation SELECT 'flow', f.edge_id::VARCHAR, f.date || ' ' || lpad(f.hour::VARCHAR, 2, '0') || ':00', f.flow, 'vehicles/hour',
                        'flows', 'surveyed', f.date, {CONFIDENCE['surveyed']}, NULL FROM read_parquet({glob.glob(flows)}) f
                        WHERE f.edge_id IN (SELECT edge_id FROM o.driving.edges WHERE {near('geometry', FLOW_M)})""")
    try:
        con.execute(f"""INSERT INTO observation SELECT 'photo', photo_id, captured::VARCHAR, compass, 'degrees (view)', 'mapillary', 'observed',
                        captured::DATE::VARCHAR, {CONFIDENCE['observed']}, {m('geometry')} FROM sp.space.photo WHERE {near('geometry', 3)}""")
    except duckdb.CatalogException:
        pass
    if vancouver_json:  # condition ratings (the rating in `subject`), the city's traffic counts (where; the data behind a link)
        con.execute(f"""INSERT INTO observation
            SELECT CASE ds WHEN 'sidewalk-condition-rating' THEN 'sidewalk condition' ELSE 'pavement condition' END,
                   coalesce(p->>'sidewalk_condition_index_rating', p->>'pci_rating'), NULL, NULL, 'rating', 'vancouver', meth, NULL,
                   {mconf}, {m('geometry')}
                FROM van WHERE ds LIKE '%condition-rating%' AND {near('geometry', 3)}
            UNION ALL SELECT CASE ds WHEN 'intersection-traffic-movement-counts' THEN 'turning counts' ELSE 'directional counts' END,
                   coalesce(p->>'url', p->>'location'), NULL, NULL, NULL, 'vancouver', meth, NULL, {mconf}, {m('geometry')}
                FROM van WHERE ds LIKE '%traffic-%count%' AND {near('geometry', FLOW_M)}""")
    try:
        seen = {k: (a, b) for k, a, b in con.execute("SELECT 'mly' || feature_id, first_seen, last_seen FROM sp.space.observed").fetchall()}
    except duckdb.CatalogException:
        seen = {}
    match(con, seen)
    con.execute("""CREATE TABLE "check" (item_table VARCHAR, item_id VARCHAR, how VARCHAR, result VARCHAR, note VARCHAR, by_whom VARCHAR, on_date VARCHAR)""")
    from urbanstyle.inventory import inventory
    inventory(con, mapillary_json if mapillary_json and os.path.exists(mapillary_json) else None,
              vancouver_json if vancouver_json and os.path.exists(vancouver_json) else None)   # what each source holds, what reaches us
    return con


def main(name, lon, lat, osm, nvdb=None, flows=None, city="", mapillary=True, vancouver=False):
    """Clip, build and write the dossier of the unit holding the junction nearest (lon, lat)."""
    from urbanstyle.container import build, with_features
    os.makedirs("data/units", exist_ok=True)
    base = f"data/units/{name}"
    osm = with_features(osm, "data/" + os.path.basename(osm).replace(".duckdb", ".osm.duckdb"))
    clip(osm, base + ".osm.duckdb", lon, lat)
    if vancouver:
        opendata_vancouver(lon, lat, base + ".vancouver.json")
    if mapillary:
        from urbanstyle import mapillary as mly
        r = CLIP_M / 111320
        mly.fetch((lon - r * 2, lat - r, lon + r * 2, lat + r), base + ".space.duckdb.mapillary.json")
    con = build(base + ".osm.duckdb", base + ".space.duckdb")
    # the unit: the intersection or subsection holding the point
    unit_id = con.execute("""SELECT unit_id FROM space.unit WHERE level = 0 ORDER BY ST_Distance(geometry, ST_Point(?, ?)), kind <> 'intersection' LIMIT 1""",
                          [lon, lat]).fetchone()[0]
    con.close()
    d = dossier(base + ".space.duckdb", base + ".osm.duckdb", unit_id, base + ".duckdb", name, city, nvdb, flows,
                base + ".space.duckdb.mapillary.json" if mapillary else None, base + ".vancouver.json" if vancouver else None)
    counts = {t: d.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in
              ("unit", "source", "road", "surface", "line", "object", "match", "lane", "movement", "rule", "observation", "check")}
    print(f"{name}: unit {unit_id} -> {base}.duckdb")
    print("  " + ", ".join(f"{t} {n}" for t, n in counts.items()))
    return unit_id
