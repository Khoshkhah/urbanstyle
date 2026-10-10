"""What each building is used for (docs/design/source-inventory.md, building use): `use` for the whole building and `ground_use`
for its ground floor, each with its source and method, and `uses` naming the evidence.

Evidence, strongest first: OSM's `building:use` or a specific `building` value (apartments, office, church, ...); the shops,
cafés and offices OSM maps inside the footprint; a city's storefront inventory (Vancouver: one point per business, at its parcel's
centre, "accurate to the block", so `approximate`). A residential or office building with businesses on its ground floor is `mixed`.
"""
import json
import os
from collections import Counter

KEYS = ("building:use", "building", "amenity", "shop", "disused:shop", "vacant", "healthcare", "craft", "leisure", "office",
        "level", "name")    # the OSM keys read here (for the source inventory)
CITY_OVER = 0.3     # a city outline overlapping OSM's buildings by more than this share of its area is one OSM already has
MIN_FLOOR_M = 2.0   # a LiDAR height under this per OSM floor is from before the building changed: OSM's floors win
LIDAR_COVER = 0.6   # a building takes a city LiDAR height where the measured roof parts cover this share of its footprint (else it changed)
STORE_M = 10.0      # a storefront (at its parcel's centre) belongs to the building it falls in, else the nearest one this close

# OSM building / building:use value -> use; values not here (yes, roof, ...) say nothing
USE = {**dict.fromkeys(("apartments", "residential", "house", "detached", "semidetached_house", "terrace", "dormitory", "bungalow",
                        "houseboat"), "residential"),
       **dict.fromkeys(("retail", "supermarket", "kiosk"), "retail"), "commercial": "commercial", "office": "office",
       **dict.fromkeys(("industrial", "warehouse", "manufacture"), "industrial"),
       **dict.fromkeys(("church", "chapel", "mosque", "temple", "synagogue", "religious", "hospital", "community_hall", "theatre",
                        "fire_station", "government", "public", "civic", "school", "college", "university", "library", "museum",
                        "kindergarten", "police", "transportation", "train_station"), "civic"),
       **dict.fromkeys(("garage", "garages", "parking", "carport", "shed", "service"), "ancillary")}
FOOD = {"restaurant", "cafe", "fast_food", "bar", "pub", "ice_cream", "food_court", "biergarten"}
SERVICE_SHOP = {"hairdresser", "beauty", "massage", "laundry", "dry_cleaning", "tattoo", "travel_agency", "copyshop", "optician"}
SERVICE = {"bank", "doctors", "dentist", "clinic", "pharmacy", "veterinary", "post_office", "bureau_de_change", "money_transfer"}
LEISURE = {"cinema", "theatre", "nightclub", "arts_centre", "gym", "fitness_centre", "sports_centre", "dance"}
CIVIC = {"place_of_worship", "library", "school", "kindergarten", "community_centre", "townhall", "police", "fire_station", "courthouse"}
# a city's storefront category -> ground use (Vancouver's general_business_category)
CITY = {"Comparison Goods": "retail", "Convenience Goods": "retail", "Automotive Goods & Services": "retail",
        "Food & Beverage": "food & drink", "Service Commercial": "services", "Entertainment and Leisure": "leisure",
        "Vacant": "vacant", "Vacant UC": "vacant"}


def poi_use(t):
    """The use an OSM point inside a building stands for (retail, food & drink, services, leisure, civic, office, vacant), or None
    for what is no business (a bench, a post box, a parking entrance)."""
    a, s = t.get("amenity"), t.get("shop")
    if s in ("vacant", "no") or t.get("disused:shop") or t.get("vacant"):
        return "vacant"
    if a in FOOD:
        return "food & drink"
    if s in SERVICE_SHOP or a in SERVICE or t.get("healthcare") or t.get("craft"):
        return "services"
    if s:
        return "retail"
    if a in LEISURE or t.get("leisure") in LEISURE:
        return "leisure"
    if a in CIVIC or t.get("amenity") == "social_facility":
        return "civic"
    if t.get("office"):
        return "office"
    return None


def city_stores(path):
    """A city's storefronts of its latest inventory year: [(use, name, what, (lon, lat))]."""
    fc = json.load(open(path)).get("storefronts-inventory", {}).get("features", [])
    year = max((f["properties"].get("year_recorded") or "" for f in fc), default=None)
    return [(CITY.get(p.get("general_business_category"), "retail"), p.get("business_name"),
             f"{p.get('business_name')} ({p.get('general_business_category')}, {year})",
             tuple(f["geometry"]["coordinates"][:2]))
            for f in fc if f["geometry"] and (p := f["properties"]).get("year_recorded") == year]


def city(con):
    """A city's building footprints (Vancouver: `building-footprints-2015`, outlines traced from the 2015 orthophotos;
    `building-footprints-2009`, roof parts with heights from the 2009 LiDAR; both "approximate", not updated), read from the unit's
    city file next to the space database. Run right after BUILD, before the street space is measured.

    - An outline overlapping no OSM building (less than CITY_OVER of it) becomes a building, source the city, unless something newer
      says it is gone or never was one: it lies in an OSM construction site, or a road crosses it.
    - A building whose footprint the 2009 roof parts cover (LIDAR_COVER) takes their height, the highest part's, unless OSM maps a
      `height`; its floors stay OSM's `building:levels` where mapped, else height / FLOOR_M. OSM is newer: where its floors need
      more than MIN_FLOOR_M a floor beyond the measured height, the building changed since 2009 and the LiDAR height is not used."""
    import duckdb
    from urbanstyle.container import FLOOR_M
    (path,) = con.execute("SELECT path FROM duckdb_databases() WHERE database_name = current_database()").fetchone()
    path = path[:-len(".space.duckdb")] + ".vancouver.json" if path and path.endswith(".space.duckdb") else None
    if not path or not os.path.exists(path):
        return
    data = json.load(open(path))
    rows = [(ds, str((f["properties"] or {}).get("object_id") or (f["properties"] or {}).get("id") or i), json.dumps(f["geometry"]),
             (f["properties"] or {}).get("hgt_agl")) for ds in ("building-footprints-2015", "building-footprints-2009")
            for i, f in enumerate((data.get(ds) or {}).get("features", [])) if f.get("geometry")]     # the city's own ids
    if not rows:
        return
    con.execute("CREATE OR REPLACE TEMP TABLE cfp (ds VARCHAR, i VARCHAR, g GEOMETRY, h DOUBLE)")
    con.executemany("INSERT INTO cfp VALUES (?, ?, ST_MakeValid(ST_GeomFromGeoJSON(?)), ?)", rows)
    try:    # only where OSM's data reaches (a clip's box): beyond it, OSM lacking a building says nothing
        con.execute("DELETE FROM cfp WHERE NOT ST_Intersects(ST_Centroid(g), (SELECT ST_Union_Agg(geometry) FROM osm.main.boundary))")
    except duckdb.CatalogException:     # a whole duckOSM database, not a clip: the city's file covers less than it
        pass
    try:
        con.execute("CREATE OR REPLACE TEMP TABLE site AS SELECT geom FROM osm.features.sites WHERE kind = 'construction'")
    except duckdb.CatalogException:
        con.execute("CREATE OR REPLACE TEMP TABLE site (geom GEOMETRY)")
    # outlines OSM lacks (shares of areas in lon/lat: a ratio, so degrees do)
    con.execute(f"""INSERT INTO space.element BY NAME
        SELECT 'vancouver' AS source, 'vb' || c.i AS source_id, 'building' AS type, 0 AS level_min, 0 AS level_max,
               'chosen' AS level_src, c.g AS geometry, 1 AS floors
        FROM cfp c WHERE c.ds = 'building-footprints-2015'
          AND coalesce((SELECT sum(ST_Area(ST_Intersection(c.g, e.geometry))) FROM space.element e
                        WHERE e.type = 'building' AND e.source = 'osm' AND ST_Intersects(c.g, e.geometry)), 0) < {CITY_OVER} * ST_Area(c.g)
          AND NOT EXISTS (SELECT 1 FROM site s WHERE ST_Intersects(s.geom, ST_Centroid(c.g)))
          AND NOT EXISTS (SELECT 1 FROM space.element r WHERE r.type = 'road' AND ST_Intersects(r.geometry, c.g))""")
    # heights from the 2009 LiDAR where its roof parts still cover the footprint
    con.execute(f"""CREATE OR REPLACE TEMP TABLE lidar AS
        SELECT e.source_id, max(c.h) AS h FROM space.element e JOIN cfp c ON c.ds = 'building-footprints-2009' AND c.h IS NOT NULL
          AND ST_Intersects(e.geometry, ST_Centroid(c.g))
        WHERE e.type = 'building' GROUP BY e.source_id, e.geometry
        HAVING sum(ST_Area(ST_Intersection(c.g, e.geometry))) >= {LIDAR_COVER} * ST_Area(e.geometry)""")
    con.execute(f"""UPDATE space.element e SET height_m = round(l.h, 1),
            floors = CASE WHEN e.level_src = 'num_floors' THEN e.floors ELSE greatest(1, round(l.h / {FLOOR_M})::INT) END,
            level_max = CASE WHEN e.level_src = 'num_floors' THEN e.level_max ELSE e.level_min + greatest(1, round(l.h / {FLOOR_M})::INT) - 1 END,
            level_src = CASE WHEN e.level_src = 'num_floors' THEN 'num_floors; height: city LiDAR 2009 (approximate)'
                             ELSE 'city LiDAR 2009 (approximate)' END
        FROM lidar l WHERE e.source_id = l.source_id AND e.type = 'building' AND e.level_src <> 'height'
          -- OSM is newer than the 2009 LiDAR: where its floors need more height than measured, the building changed since
          AND NOT (e.level_src = 'num_floors' AND l.h < {MIN_FLOOR_M} * e.floors)""")


def build(con, epsg):
    """Add use, use_source, use_method, ground_use, ground_source, ground_method and uses to the buildings of space.element."""
    import duckdb
    import shapely
    m = lambda g: f"ST_AsWKB(ST_Transform({g}, 'EPSG:4326', '{epsg}', always_xy := true))"     # lon/lat -> metres
    bld = con.execute(f"""SELECT source_id, {m('geometry')}, b.tags FROM space.element e
                         LEFT JOIN osm.features.buildings b ON e.source_id = left(b.osm_type, 1) || b.osm_id
                         WHERE e.type = 'building'""").fetchall()
    ids = [r[0] for r in bld]
    geoms = [shapely.from_wkb(r[1]) for r in bld]
    tags = [dict(r[2] or {}) for r in bld]
    tree = shapely.STRtree(geoms)
    found = [[] for _ in bld]       # per building: (use, source, method, what, ground floor?, OSM name)
    try:
        pois = con.execute(f"SELECT tags, {m('geom')} FROM osm.features.pois").fetchall()
    except duckdb.CatalogException:     # a database without duckOSM's points of interest
        pois = []
    for t, w in pois:
        t = dict(t or {})
        u = poi_use(t)
        if u is None:
            continue
        p = shapely.from_wkb(w)
        for k in tree.query(p, predicate="within"):
            ground = (t.get("level") or "0").split(";")[0].strip() in ("0", "")
            found[k].append((u, "osm", "mapped", f"{t.get('name') or u} (OSM)", ground, (t.get("name") or "").lower()))
    (path,) = con.execute("SELECT path FROM duckdb_databases() WHERE database_name = current_database()").fetchone()
    city = path[:-len(".space.duckdb")] + ".vancouver.json" if path and path.endswith(".space.duckdb") else None
    if city and os.path.exists(city):
        stores = city_stores(city)
        pts = con.execute(f"SELECT {m('ST_Point(x, y)')} FROM (SELECT unnest(?::DOUBLE[]) AS x, unnest(?::DOUBLE[]) AS y)",
                          [[st[3][0] for st in stores], [st[3][1] for st in stores]]).fetchall() if stores else []
        for (u, name, what, _), (w,) in zip(stores, pts):
            p = shapely.from_wkb(w)
            k = tree.query_nearest(p, max_distance=STORE_M)
            if not len(k):
                continue
            f = found[k[0]]
            same = [i for i, x in enumerate(f) if x[5] and x[5] == (name or "").lower()]
            if same:        # a business OSM maps there too: one business, both sources, OSM's use and position
                x = f[same[0]]
                f[same[0]] = (x[0], "osm, vancouver", "mapped", f"{x[3][:-len(' (OSM)')]} (OSM; city {what[len(name):].strip(' ()')})", x[4], x[5])
            else:
                f.append((u, "vancouver", "approximate", what, True, None))
    rows = []
    for bid, t, f in zip(ids, tags, found):
        tag = t.get("building:use") or t.get("building")
        use = USE.get(tag)
        g = [x for x in f if x[4]]
        busy = Counter(x[0] for x in g if x[0] != "vacant")
        if busy:
            ground = busy.most_common(1)[0][0]
        elif g:
            ground = "vacant"
        else:
            ground = "residential" if use == "residential" else None
        gsrc = ", ".join(dict.fromkeys(s_ for x in g for s_ in x[1].split(", "))) or ("osm" if ground else None)
        gmeth = ("mapped" if all(x[2] == "mapped" for x in g) else "approximate") if g else ("derived" if ground else None)
        src, meth = ("osm", "mapped") if use else (None, None)
        if use in ("residential", "office") and busy:
            use, src, meth = "mixed", ", ".join(dict.fromkeys(["osm", *gsrc.split(", ")])), "derived"
        elif use is None and busy:      # a building OSM says nothing of: commercial where businesses fill its ground floor
            use, src, meth = "commercial", gsrc, "derived"
        tagtxt = f"OSM {'building:use' if t.get('building:use') else 'building'}={tag}" if tag else None
        rows.append((bid, use, src, meth, ground, gsrc, gmeth, "; ".join(filter(None, [tagtxt, *(x[3] for x in f)])) or None))
    for c in ("use", "use_source", "use_method", "ground_use", "ground_source", "ground_method", "uses"):
        con.execute(f'ALTER TABLE space.element ADD COLUMN IF NOT EXISTS "{c}" VARCHAR')
    con.execute("CREATE TEMP TABLE bu (id VARCHAR, u VARCHAR, us VARCHAR, um VARCHAR, g VARCHAR, gs VARCHAR, gm VARCHAR, w VARCHAR)")
    if rows:
        con.executemany("INSERT INTO bu VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    con.execute("""UPDATE space.element e SET "use" = u, use_source = us, use_method = um, ground_use = g, ground_source = gs,
                   ground_method = gm, uses = w FROM bu WHERE e.source_id = bu.id AND e.type = 'building'""")
    con.execute("DROP TABLE bu")
