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


def city_stores(path, fwd):
    """A city's storefronts of its latest inventory year: [(use, name, what, point)]."""
    import shapely
    fc = json.load(open(path)).get("storefronts-inventory", {}).get("features", [])
    year = max((f["properties"].get("year_recorded") or "" for f in fc), default=None)
    return [(CITY.get(p.get("general_business_category"), "retail"), p.get("business_name"),
             f"{p.get('business_name')} ({p.get('general_business_category')}, {year})",
             shapely.Point(fwd(*f["geometry"]["coordinates"][:2])))
            for f in fc if f["geometry"] and (p := f["properties"]).get("year_recorded") == year]


def build(con, epsg):
    """Add use, use_source, use_method, ground_use, ground_source, ground_method and uses to the buildings of space.element."""
    import duckdb
    import pyproj
    import shapely
    from shapely.ops import transform
    fwd = pyproj.Transformer.from_crs("EPSG:4326", epsg, always_xy=True).transform
    bld = con.execute("""SELECT source_id, ST_AsWKB(geometry), b.tags FROM space.element e
                         LEFT JOIN osm.features.buildings b ON e.source_id = left(b.osm_type, 1) || b.osm_id
                         WHERE e.type = 'building'""").fetchall()
    ids = [r[0] for r in bld]
    geoms = [transform(fwd, shapely.from_wkb(r[1])) for r in bld]
    tags = [dict(r[2] or {}) for r in bld]
    tree = shapely.STRtree(geoms)
    found = [[] for _ in bld]       # per building: (use, source, method, what, ground floor?, OSM name)
    try:
        pois = con.execute("SELECT tags, ST_AsWKB(geom) FROM osm.features.pois").fetchall()
    except duckdb.CatalogException:     # a database without duckOSM's points of interest
        pois = []
    for t, w in pois:
        t = dict(t or {})
        u = poi_use(t)
        if u is None:
            continue
        p = transform(fwd, shapely.from_wkb(w))
        for k in tree.query(p, predicate="within"):
            ground = (t.get("level") or "0").split(";")[0].strip() in ("0", "")
            found[k].append((u, "osm", "mapped", f"{t.get('name') or u} (OSM)", ground, (t.get("name") or "").lower()))
    (path,) = con.execute("SELECT path FROM duckdb_databases() WHERE database_name = current_database()").fetchone()
    city = path[:-len(".space.duckdb")] + ".vancouver.json" if path and path.endswith(".space.duckdb") else None
    if city and os.path.exists(city):
        for u, name, what, p in city_stores(city, fwd):
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
