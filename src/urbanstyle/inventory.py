"""The source inventory (unit dossier, step 1): what every source holds around a unit, and how much of it reaches urbanstyle's data.

One row per source, layer and item (an OSM tag key, a Mapillary class, a city dataset): `n` items in the unit's neighbourhood (the
clip), `n_ours` of them in our tables (an OSM node as a `space.object`, a way or a building as a `space.element`, a Mapillary feature
in a class we keep, a city record in a dataset we read), `read` whether our code reads the item's value (an OSM key read by urbanstyle
or duckOSM, or kept in an object's attrs), and `values`, the commonest values. A row with many items and nothing read is a gap
(docs/design/source-inventory.md). Nothing here is kept by hand: the counts come from the data, `read` from the code itself."""
import collections
import json
import re
from pathlib import Path


def keys_read():
    """The OSM keys our code reads: tags['key'] in urbanstyle's and duckOSM's source, the object attrs kept (OBJECT_ATTRS)."""
    from urbanstyle.container import OBJECT_ATTRS
    files = list(Path(__file__).parent.glob("*.py"))
    try:
        import duckosm
        files += list(Path(duckosm.__file__).parent.rglob("*.py"))
    except ImportError:
        pass
    pat = re.compile(r"""tags\[\s*['"]([\w:]+)['"]\s*\]|tags->>\s*'([\w:]+)'|\$\.([\w:]+)""")
    found = {g for f in files for m in pat.finditer(f.read_text(errors="ignore")) for g in m.groups() if g}
    return found | set(OBJECT_ATTRS)


def top(counter, k=3):
    return ", ".join(f"{v} {n}" for v, n in counter.most_common(k))


def inventory(con, mapillary_json=None, city_json=None):
    """The `inventory` table of a dossier (`con` has the space db as `sp` and the clipped duckOSM db as `o`)."""
    read = keys_read()
    rows = []
    # OSM: every tag key on the nodes, roads and paths, and buildings of the neighbourhood
    layers = (("node tag", """SELECT tags, 'n' || osm_id IN (SELECT object_id FROM sp.space.object) FROM o.raw.nodes
                               WHERE cardinality(tags) > 0 AND ST_Intersects(ST_Point(lon, lat), (SELECT geometry FROM o.main.boundary))"""),
              ("road and path tag", """SELECT tags, osm_id IN (SELECT osm_id FROM sp.space.element) FROM o.raw.ways"""),
              ("building tag", """SELECT tags, left(osm_type, 1) || osm_id IN (SELECT source_id FROM sp.space.element WHERE type = 'building')
                                   FROM o.features.buildings"""))
    for layer, sql in layers:
        n, ours, vals = collections.Counter(), collections.Counter(), collections.defaultdict(collections.Counter)
        for tags, mine in con.execute(sql).fetchall():
            for k, v in (tags or {}).items():
                n[k] += 1
                ours[k] += bool(mine)
                vals[k][v] += 1
        got = read | ({"building"} if layer == "building tag" else set())    # a building's class is duckOSM's kind: its building tag
        rows += [("osm", layer, k, c, ours[k], k in got, top(vals[k])) for k, c in n.items()]
    for kind, c in con.execute("SELECT kind, count(*) FROM o.features.sites GROUP BY 1").fetchall():    # areas: parking lots, sites
        rows.append(("osm", "area", kind, c, None, None, None))
    if mapillary_json:
        from urbanstyle.mapillary import group
        n = collections.Counter(f["object_value"] for f in json.load(open(mapillary_json))["features"])
        rows += [("mapillary", "map feature", v, c, c if group(v) else 0, bool(group(v)), None) for v, c in n.items()]
    if city_json:
        from urbanstyle.unit import VAN_OBJECT, VAN_OTHER
        for ds, fc in json.load(open(city_json)).items():
            fields = collections.Counter(k for ft in fc["features"] for k, v in (ft["properties"] or {}).items() if v not in (None, ""))
            used = ds in VAN_OBJECT or ds in VAN_OTHER
            rows.append(("vancouver", "dataset", ds, len(fc["features"]), len(fc["features"]) if used else 0, used,
                         "fields: " + ", ".join(fields)))
    con.execute("""CREATE TABLE inventory (source VARCHAR, layer VARCHAR, item VARCHAR, n INT, n_ours INT, read BOOLEAN, "values" VARCHAR)""")
    con.executemany("INSERT INTO inventory VALUES (?, ?, ?, ?, ?, ?, ?)", sorted(rows, key=lambda r: (r[0], r[1], -r[3])))
    return len(rows)
