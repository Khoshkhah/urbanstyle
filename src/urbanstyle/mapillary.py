"""Street-level observations from Mapillary (docs/design/mapillary.md).

    urbanstyle mapillary data/monaco.duckdb [--osm ../duckOSM/monaco.duckdb]

Mapillary detects objects in its photos and places each on the map from several of them (a "map feature", about 1-5 m off). For the
area of a built database, the features urbanstyle uses (parking and no-parking signs, give-way and stop signs, traffic lights, street
lights, bins, benches, painted lane arrows, zebras) and the photo positions are fetched once into `<db>.mapillary.json` next to it, then
loaded as `space.observed` and `space.photo`; `build` loads that file again when it exists. With --osm the parts are rebuilt at once.
The token: $MAPILLARY_TOKEN, else ~/.config/mapillary/token (a free client token from mapillary.com/dashboard/developers).
Mapillary data is CC BY-SA 4.0 (attribution: "© Mapillary contributors"); it stays in the local database, not in this repository.
"""
import json
import os
import sys
import time

API = "https://graph.mapillary.com"
STEP = 0.001        # degrees: a box of 0.005 came back incomplete and different on each call (28 or 99 of 153 photos); 0.001 is complete

# Mapillary's class -> our group; only these are kept
GROUPS = {"information--parking--g1": "parking", "information--parking--g5": "parking", "object--traffic-sign--information-parking": "parking",
          "object--parking-meter": "parking meter", "regulatory--no-parking--g1": "no parking", "regulatory--no-stopping--g1": "no parking",
          "regulatory--yield--g1": "give way", "regulatory--stop--g1": "stop", "object--street-light": "street light",
          "object--trash-can": "bin", "object--bench": "bench", "marking--discrete--crosswalk-zebra": "zebra"}
for _v in ("object--traffic-light--general-upright", "object--traffic-light--general-upright-front", "object--traffic-light--general-horizontal",
           "object--traffic-light--general-horizontal-front", "object--traffic-light--pedestrians"):
    GROUPS[_v] = "traffic light"


# our group -> our object class: the one table every reader of space.observed uses (parts, the dossier, the dashboard)
CLASS_OF = {"street light": "furniture.lamp", "traffic light": "furniture.signal", "give way": "furniture.sign", "stop": "furniture.sign",
            "parking": "furniture.sign", "no parking": "furniture.sign", "parking meter": "furniture.parking_meter", "bin": "furniture.waste",
            "bench": "furniture.bench", "zebra": "marking.zebra", "lane arrow": "marking.arrow"}


def group(value):
    """Our group of a Mapillary class, or None. A sign's variants (--g1, --g9, ...) are one group."""
    if value.startswith("marking--discrete--arrow--"):
        return "lane arrow"
    if value.startswith(("regulatory--no-parking--", "regulatory--no-stopping--")):
        return "no parking"
    if value.startswith("information--parking--"):
        return "parking"
    return GROUPS.get(value)


def token():
    t = os.environ.get("MAPILLARY_TOKEN")
    path = os.path.expanduser("~/.config/mapillary/token")
    if not t and os.path.exists(path):
        t = open(path).read().strip()
    if not t:
        sys.exit("no Mapillary token: set MAPILLARY_TOKEN or write it to ~/.config/mapillary/token")
    return t


def _get(endpoint, bbox, fields, tok):
    import urllib.parse
    import urllib.request
    url = f"{API}/{endpoint}?" + urllib.parse.urlencode({"bbox": ",".join(f"{v:.6f}" for v in bbox), "fields": fields, "limit": 2000})
    out = []
    while url:
        for k in range(4):
            try:
                d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": f"OAuth {tok}"}), timeout=60))
                break
            except Exception as e:      # a busy server: wait and retry, then give up on this box (the rest still counts)
                if k == 3:
                    print(f"  skipped {endpoint} {bbox}: {str(e)[:100]}", file=sys.stderr)
                    return out
                time.sleep(2 * (k + 1))
        out += d.get("data", [])
        url = d.get("paging", {}).get("next")
    return out


def fetch(bbox, path):
    """Fetch every map feature (all classes: the unit's source inventory counts them; `load` keeps ours) and all photo positions in
    bbox (w, s, e, n) into the json file `path`."""
    tok, feats, photos = token(), {}, {}
    w, s, e, n = bbox
    y = s
    while y < n:
        x = w
        while x < e:
            b = (x, y, min(x + STEP, e), min(y + STEP, n))
            for r in _get("map_features", b, "id,object_value,geometry,first_seen_at,last_seen_at", tok):
                feats[r["id"]] = r
            for r in _get("images", b, "id,captured_at,geometry,compass_angle,is_pano,sequence", tok):
                photos[r["id"]] = r
            x += STEP
        y += STEP
    json.dump({"bbox": bbox, "fetched": time.strftime("%Y-%m-%d"), "features": list(feats.values()), "photos": list(photos.values())}, open(path, "w"))
    return len(feats), len(photos)


def load(con, path):
    """`space.observed` (feature_id, class, grp, first_seen, last_seen, geometry) and `space.photo` (photo_id, captured, compass,
    is_pano, sequence, geometry) from the json file."""
    import pandas as pd
    d = json.load(open(path))
    obs = pd.DataFrame([(f["id"], f["object_value"], group(f["object_value"]), f.get("first_seen_at"), f.get("last_seen_at"),
                         *f["geometry"]["coordinates"]) for f in d["features"]],
                       columns=["feature_id", "class", "grp", "first_seen", "last_seen", "lon", "lat"])
    ph = pd.DataFrame([(p["id"], p.get("captured_at"), p.get("compass_angle"), bool(p.get("is_pano")), p.get("sequence"), *p["geometry"]["coordinates"])
                       for p in d["photos"]], columns=["photo_id", "captured", "compass", "is_pano", "sequence", "lon", "lat"])
    con.execute("CREATE SCHEMA IF NOT EXISTS space")
    con.execute("""CREATE OR REPLACE TABLE space.observed AS SELECT feature_id::VARCHAR AS feature_id, class, grp, left(first_seen, 19)::TIMESTAMP AS first_seen,
                   left(last_seen, 19)::TIMESTAMP AS last_seen, 'mapillary' AS source, ST_Point(lon, lat) AS geometry FROM obs
                   WHERE grp IS NOT NULL""")     # the classes we use (GROUPS)
    con.execute("""CREATE OR REPLACE TABLE space.photo AS SELECT photo_id::VARCHAR AS photo_id, make_timestamp(captured::BIGINT * 1000) AS captured,
                   compass, is_pano, sequence, ST_Point(lon, lat) AS geometry FROM ph""")
    return int(obs.grp.notna().sum()), len(ph)


def main(db, osm=None):
    import duckdb
    con = duckdb.connect(db)
    con.execute("LOAD spatial")
    w, s, e, n = con.execute("SELECT min(ST_XMin(geometry)), min(ST_YMin(geometry)), max(ST_XMax(geometry)), max(ST_YMax(geometry)) FROM space.unit").fetchone()
    path = db + ".mapillary.json"
    nf, nph = fetch((w, s, e, n), path)
    print(f"{db}: {nf} Mapillary features, {nph} photos -> {path}")
    load(con, path)
    if osm:
        from urbanstyle import parts
        con.execute(f"ATTACH '{osm}' AS osm (READ_ONLY)")
        lon = (w + e) / 2
        parts.build(con, f"EPSG:{32600 + int((lon + 180) // 6) + 1}")
        print("parts rebuilt with them")
    else:
        print("run `urbanstyle build` again (or this with --osm) to use them in the parts")
