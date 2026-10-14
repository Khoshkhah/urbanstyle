"""`urbanstyle dashboard DB OUT [--bridge PROFILE]` (docs/design/dashboard.md, "How the page is made"): the dashboard page of one area.
The page holds the area's data only: roadstyle's map (MapLibre) with the current model's layers, every one hidden at first, and the
area's own values for the engine (window.US_CFG). The engine (engine.js), the panel (panel.js, panel.css) and the bridges' models
(bridge3d.json) lie beside it: urbanstyle serve gives the first three from the package on every request, urbanstyle publish copies them.
So every area runs the same script. The data helpers stay in dashboard.py."""
import json
import os

ENGINE, PANEL_JS, PANEL_CSS = "urbanstyle-engine.js", "urbanstyle-panel.js", "urbanstyle-panel.css"     # (their names beside the page)
ASSETS = {ENGINE: "engine.js", PANEL_JS: "panel.js", PANEL_CSS: "panel.css"}       # beside the page -> in the package


def _frames(con, db, bridges):
    """Every layer of the page as a GeoDataFrame (lon / lat), and the bridge models."""
    import duckdb
    import geopandas as gpd
    import pandas as pd
    from . import dashboard as d
    ep = d.epsg_of(con)
    f = lambda sql: d.frame(con, sql)
    out = {}
    out["edges"] = f("""SELECT ST_AsWKB(geometry) AS geometry, class AS highway, name, level_min AS level, type, container_id,
        CASE WHEN level_src = 'bridge' THEN 'yes' END AS bridge, CASE WHEN level_src = 'tunnel' THEN 'yes' END AS tunnel,
        level_min AS layer, try_cast(source_id AS BIGINT) AS edge_id, coalesce(oneway, false) AS oneway, round(width_m, 2) AS width_m, width_src
        FROM space.element WHERE type <> 'building'""")
    out["edges"]["edge_id"] = out["edges"]["edge_id"].astype("Int64")
    out["buildings"] = f("""SELECT ST_AsWKB(geometry) AS geometry, source_id AS id, source, name, class, level_min, level_max, level_src,
        CASE WHEN coalesce(class, 'yes') = 'yes' THEN 'building' ELSE 'building (' || class || ')' END AS type,
        -- its real size (space.element floors, height_m: before levels are clamped to LEVELS), else one floor
        coalesce(floors, greatest(level_max, 0) + 1) AS floors, coalesce(height_m, round((greatest(level_max, 0) + 1) * 3.2, 1)) AS height_m,
        "use" || ' (' || use_source || ', ' || use_method || ')' AS "use", ground_use || ' (' || ground_source || ', ' || ground_method || ')' AS ground_floor,
        uses AS evidence FROM space.element WHERE type = 'building'""")
    gm = f"ST_Transform(geometry, 'EPSG:4326', '{ep}', always_xy := true)"
    out["ground"] = f(f"""SELECT ST_AsWKB(geometry) AS geometry, ground_id, type, name, source, method, ref, level,
        round(ST_Area({gm}), 1) AS area_m2, {d.ALLEY_W.format(t='type', g=gm)} FROM space.ground""")
    out["ground"]["color"] = out["ground"]["type"].map(d.GROUND_COLORS).fillna("#9ca3af")
    blocks = d.blocks_frame(con)
    out["blocks"] = d.block_colors(blocks) if blocks is not None and len(blocks) else None
    out["lots"] = f("SELECT ST_AsWKB(geometry) AS geometry, lot_id AS id, type, name, operator, parking, access, fee, level FROM space.lot")
    out["rails"] = f("SELECT ST_AsWKB(geometry) AS geometry, source_id AS id, name, class, level_min AS level FROM space.element WHERE type = 'rail'")
    out["stations"] = f("SELECT ST_AsWKB(geometry) AS geometry, id, name, kind, level FROM space.station")
    out["links"] = f("""SELECT ST_AsWKB(geometry) AS geometry, node_id, level_a, level_b, type, assumed, station_id, match, round(dist_m) AS dist_m
        FROM space.link""")
    # the street: its spaces (a subsection or an intersection each), the subsections' axes and breaks, the cuts
    units = f(f"""SELECT ST_AsWKB(geometry) AS geometry, unit_id, kind, section_id, level, color,
        round(ST_Area({gm}))::INT AS area_m2 FROM space.unit""")
    sub = units[units.kind == "subsection"]
    out["sections"] = sub.dissolve(by=["section_id", "level"], as_index=False)[["section_id", "level", "geometry"]] if len(sub) else sub
    out["intersections"], out["subsections"] = units[units.kind != "subsection"], sub
    out["axes"] = f("""SELECT ST_AsWKB(geometry) AS geometry, subsection_id, section_id, level, class, width_m, oneway, length_m, "left", "right",
        starts_at, color FROM space.subsection""")
    out["breaks"] = f("""SELECT ST_AsWKB(ST_StartPoint(geometry)) AS geometry, subsection_id, section_id, level, starts_at FROM space.subsection
        WHERE starts_at <> 'section end'""")
    out["cuts"] = f("""SELECT ST_AsWKB(geometry) AS geometry, intersection_id, edge_id, level, how, length_m,
        CASE how WHEN 'block corners' THEN '#16a34a' WHEN 'one corner' THEN '#f59e0b' WHEN 'crosswalk' THEN '#2563eb' ELSE '#6b7280' END AS color
        FROM space.cut""")
    # inside the spaces: the parts and the painted lines; the kerbs as stones 0.25 m wide for 3D
    parts = f(f"""SELECT ST_AsWKB(geometry) AS geometry, unit_id, part_id, level, type, coalesce(arm, '') AS arm, coalesce(direction, '') AS direction,
        lane, lane_id, width_m, length_m, source, method, ref, road, road_class, speed, surface, lit, road_lanes, oneway, holds, rule,
        width_source, width_method, position_source, position_method, position_ref, round(ST_Area({gm}), 1) AS area_m2
        FROM space.part ORDER BY level""")      # (upper levels drawn last)
    parts["color"] = [d.PART_COLORS.get(f"{t} {r}".strip(), d.PART_COLORS.get(t, "#999999")) for t, r in zip(parts["type"], parts["direction"])]
    out["parts"] = parts
    marks = f("""SELECT ST_AsWKB(geometry) AS geometry, unit_id, level, type, coalesce(arm, '') AS arm, length_m, width_m, width_source,
        width_method, source, method, ref FROM space.mark ORDER BY level""")
    out["marks"] = marks
    kerbs = marks[marks["type"] == "kerb"].copy()
    kerbs = kerbs.set_geometry(kerbs.to_crs(ep).buffer(d.LINE["kerb"] / 2, cap_style="flat").to_crs(4326))
    kerbs["kerb_id"] = [f"kerb-{k}" for k in range(len(kerbs))]
    out["kerbs3d"] = kerbs
    # the bridges: each profile's model (3D, bridge3d.py), and every part of it flat, with its id (2D)
    ms, under = d.bridge_models(con, bridges, db) if bridges else ([], set())
    out["models"], out["under"] = ms, sorted(under)
    out["bridge2d"] = gpd.GeoDataFrame([{**{k: (v if isinstance(v, (str, int, float)) or v is None else str(v)) for k, v in pr.items()},
                                         "color": d.PART_COLORS.get(key) or d.PART_COLORS.get(key.split(" ")[0]) or
                                         {"barrier median": "#cfc8bd", "median": "#6b7280", "buffer": "#c4b5a0"}.get(key, "#9ca3af"), "geometry": g}
                                        for mm in ms for pr, key, g in mm["flat"]], geometry="geometry", crs=4326) if ms else None
    # a bridge deck at ground level (division: a way OSM tags bridge=yes) is the bridge model's: the page draws of it only what the model
    # does not cover (between the model's wall and the street beside it), so nothing lies twice and nothing is left open
    deck = parts["type"] == "bridge deck"
    if deck.any() and out["bridge2d"] is not None:
        import numpy as np
        import shapely
        import geopandas as gpd_
        model = shapely.union_all(shapely.buffer(shapely.make_valid(np.asarray(out["bridge2d"].to_crs(ep).geometry)), 0.05))
        rest = shapely.buffer(shapely.buffer(shapely.difference(shapely.make_valid(np.asarray(parts[deck].to_crs(ep).geometry)), model), -0.05), 0.05)
        parts.loc[deck, "geometry"] = gpd_.GeoSeries(rest, crs=ep).to_crs(4326).values
        out["parts"] = parts = parts[~(deck & parts.geometry.is_empty)]
    # the street objects, one per real object from every source: in 2D a dot where it stands, in 3D its model
    place = d.placer(con, ep)
    try:
        mobjs = d.matched_objects(con, ep, db)
        furn = d.furniture_3d(con, ep, place, mobjs, d.bridge_decks(bridges or [], ep, ms))
        dots = furn.assign(a=furn.to_crs(ep).area).sort_values("a").drop_duplicates("refs").drop(columns=["a"])
        dots = dots.set_geometry(dots.to_crs(ep).centroid.to_crs(4326))
        dots["color"] = dots["class"].str.split(".").str[0].map(d.DOT_COLORS).fillna("#6b7280")
    except Exception as e:      # the page goes without street objects rather than failing
        print("no street objects:", e)
        furn, mobjs = gpd.GeoDataFrame({"class": []}, geometry=[], crs=4326), []
        dots = furn
    out["furn"], out["dots"] = furn, dots
    # Mapillary's detections, for validation only (CC BY-SA, stays local): green where it confirms an object, orange where nothing does
    try:
        seen = f("""SELECT ST_AsWKB(any_value(o.geometry)) AS geometry, o.feature_id, any_value(o.class) AS class, any_value(o.grp) AS grp,
            any_value(o.last_seen)::DATE::VARCHAR AS last_seen, coalesce(min(u.unit_id), '') AS space,
            coalesce(min(u.level) FILTER (WHERE u.level = 0), min(u.level), 0) AS level FROM space.observed o
            LEFT JOIN space.unit u ON ST_Intersects(u.geometry, ST_Buffer(o.geometry, 0.00003)) GROUP BY o.feature_id""")
        from .unit import MATCH_M
        conf = {r: (o[1], o[5].split(", ")[0]) for o in mobjs for r in o[5].split(", ")}
        seen["type"] = [d.type_of(d.SEEN_CLASS.get(g, g)) for g in seen["grp"]]
        seen["status"] = [f"confirms {d.type_of(conf[str(i)][0])} {conf[str(i)][1]}" if str(i) in conf else
                          f"not confirmed: no surveyed or mapped {t} within {MATCH_M:.0f} m" for i, t in zip(seen["feature_id"], seen["type"])]
        seen["color"] = ["#16a34a" if s.startswith("confirms") else "#f97316" for s in seen["status"]]
    except duckdb.CatalogException:
        seen = pd.DataFrame({"grp": []})
    out["seen"] = seen
    return out


def _overlays(F):
    """The page's layers, in drawing order (the panel's Layers tree names them by these labels). Every one starts hidden: the panel
    sets the first look, then lifts the veil."""
    import roadstyle as rs
    from . import dashboard as d
    under = lambda g, **kw: rs.Overlay(g, placement="under", **kw)
    have = lambda g: g is not None and len(g) > 0
    links = F["links"]
    LINKS = [("ramp", "Ramp", "#f59e0b"), ("stairs", "Stairs", "#0f172a"), ("elevator", "Elevator", "#06b6d4"),
             ("entrance", "Station entrance", "#ef4444"), ("connection", "Other level change", "#ec4899")]
    parts, marks = F["parts"], F["marks"]
    on_parts = parts[parts["type"].isin(d.ON_PARTS)]
    ovs = []
    if have(F["bridge2d"]):
        ovs.append(rs.Overlay(F["bridge2d"], placement="over", color="#9ca3af", color_col="color", opacity=0.95, outline="#334155", width=0.6,
                              label="Bridge 2D", popup=d.BR_POPUP, tooltip=["id", "type"]))
    if have(F["ground"]):
        ovs.append(under(F["ground"], color=d.GROUND_COLORS["plot"], color_col="color", opacity=0.55, outline="#94a3b8", width=0.5, label="Ground",
                         popup=d.GROUND_POPUP, tooltip=["type", "name"]))
    if have(F["blocks"]):
        ovs.append(rs.Overlay(F["blocks"], placement="over", color=d.BLOCK_COLOR, color_col="color", opacity=0.45, outline="#5b3410", width=2.0,
                              label="Blocks", popup=d.BLOCK_POPUP, tooltip=["block_id"]))
    ovs.append(under(F["buildings"], color="#efede9", opacity=0.85, outline="#cdc8c1", label="Buildings", popup=d.BLD_POPUP, tooltip=["type"]))
    if have(F["lots"]):
        ovs.append(under(F["lots"], color="#a8b0ba", opacity=0.9, outline="#64748b", label="Parking lots", popup=d.LOT_POPUP, tooltip=["type"]))
    if have(F["rails"]):
        ovs.append(rs.Overlay(F["rails"], kind="line", placement="over", color="#c026d3", width=3, label="Rail", popup=["id", "name", "class", "level"],
                              tooltip=["id", "name"]))
    if have(F["stations"]):
        ovs.append(rs.Overlay(F["stations"], kind="circle", placement="over", color="#0d9488", radius=9, label="Station", popup=["id", "name", "kind", "level"],
                              tooltip=["id", "name"]))
    for t, name, c in LINKS:
        if have(links) and (links["type"] == t).any():
            ovs.append(rs.Overlay(links[links["type"] == t], kind="circle", placement="over", color=c, radius=6, label=f"Link: {name}",
                                  popup=["node_id", "type", "level_a", "level_b", "assumed", "station_id", "match", "dist_m"], tooltip=["node_id", "type"]))
    if have(F["sections"]):
        ovs.append(under(F["sections"], color="#a78bfa", opacity=0.35, outline="#4c1d95", width=2.2, label="Sections", popup=["section_id", "level"],
                         tooltip=["section_id"]))
    if have(F["intersections"]):
        ovs.append(under(F["intersections"], color="#fbbf24", opacity=0.45, outline="#b45309", width=2.2, label="Intersections",
                         popup=["unit_id", "kind", "level", "area_m2"], tooltip=["unit_id", "kind"]))
    if have(F["subsections"]):
        ovs.append(under(F["subsections"], color="#a78bfa", color_col="color", opacity=0.25, outline="#6d28d9", width=0.8, label="Subsections",
                         popup=["unit_id", "section_id", "level", "area_m2"], tooltip=["unit_id"]))
    if have(parts):
        ovs.append(under(parts, color="#999999", color_col="color", opacity=0.95, outline="#475569", width=0, label="Parts",
                         popup=["part_id", "type", "holds", "rule", "road", "road_class", "direction", "lane", "lane_id", "width_m", "length_m", "speed",
                                "surface", "lit", "road_lanes", "oneway", "area_m2", "source", "method", "ref", "width_source", "width_method",
                                "position_source", "position_method", "position_ref"], tooltip=["type", "direction", "arm"]))
    if have(on_parts):
        ovs.append(under(on_parts, color="#f97316", color_col="color", opacity=0.85, outline="#7c2d12", width=0.8, label="On the parts",
                         popup=["part_id", "type", "rule", "unit_id", "source", "method", "ref"], tooltip=["type"]))
    for t, c, w, dash in d.MARKS:
        if have(marks) and (marks["type"] == t).any():
            ovs.append(rs.Overlay(marks[marks["type"] == t], kind="line", placement="over", color=c, width_m=w, dash=dash, label=f"Mark: {t}",
                                  popup=["unit_id", "type", "arm", "length_m", "width_m", "width_source", "width_method", "source", "method", "ref"],
                                  tooltip=["type", "arm"]))
    if have(F["dots"]):
        ovs.append(rs.Overlay(F["dots"], kind="circle", placement="over", color="#4f46e5", color_col="color", radius=4, label="Street objects",
                              popup=d.OBJ_POPUP, tooltip=d.OBJ_TIP))
    if have(F["seen"]):
        ovs.append(rs.Overlay(F["seen"], kind="circle", placement="over", color="#f97316", color_col="color", radius=4, label="Mapillary",
                              popup=["type", "status", "last_seen", "feature_id", "space"], tooltip=["type"]))
    # drawn by 3D only (engine.js, draw3d): the street objects' models and the kerbstones
    if have(F["furn"]):
        ovs.append(under(F["furn"], color="#71717a", color_col="color", opacity=0, width=0, label="Street objects 3D",
                         popup=d.OBJ_POPUP, tooltip=d.OBJ_TIP))
    if have(F["kerbs3d"]):
        ovs.append(under(F["kerbs3d"], color="#cfcac2", opacity=0, width=0, label="Kerbs 3D",
                         popup=["type", "unit_id", "arm", "length_m"], tooltip=["type"]))
    # the helper lines: how the street was cut
    if have(F["cuts"]):
        ovs.append(rs.Overlay(F["cuts"], kind="line", placement="over", color="#6b7280", color_col="color", width=4, label="Cuts",
                              popup=["intersection_id", "edge_id", "how", "length_m"], tooltip=["how", "length_m"]))
    if have(F["axes"]):
        ovs.append(rs.Overlay(F["axes"], kind="line", placement="over", color="#e6194b", color_col="color", width=5, label="Subsection axes",
                              popup=["subsection_id", "section_id", "class", "width_m", "oneway", "length_m", "left", "right", "starts_at"],
                              tooltip=["subsection_id", "length_m"]))
    if have(F["breaks"]):
        ovs.append(rs.Overlay(F["breaks"], kind="circle", placement="over", color="#111827", radius=5, label="Subsection breaks",
                              popup=["subsection_id", "starts_at"], tooltip=["subsection_id", "starts_at"]))
    return ovs


def build(db, out, bridges=None):
    """Write the dashboard page of `db` to `out`, and the bridges' 3D models beside it (bridge3d.json)."""
    import duckdb
    import roadstyle as rs
    from . import dashboard as d
    from .parts import KERB_TOP_M, RAISED
    con = duckdb.connect(db, read_only=True)
    con.execute("LOAD spatial")
    # (with no bridge model, a deck is drawn flat in the air with no lanes: Monaco's page was built so, and no one saw why; Kaveh,
    # 2026-10-14)
    n_br = con.execute("SELECT count(DISTINCT osm_id) FROM space.element WHERE type = 'road' AND level_min > 0").fetchone()[0]
    if n_br and not bridges:
        print(f"WARNING: {n_br} road ways are on bridges but no --bridge profile is given: their decks are drawn flat in the air, with no "
              "lanes. Make the profiles first: `urbanstyle bridge OSM GMNS DIR`, then `--bridge DIR/*.bridge.json` (AGENTS.md)")
    F = _frames(con, db, bridges)
    ovs = _overlays(F)
    for o in ovs:
        o.visible = False      # (every layer hidden at first: the panel sets the first look, then lifts the veil)
    m = rs.render_edges(
        F["edges"], palette="mono", basemap="voyager", name="urbanstyle", filter_control=False,
        street_view_key=os.environ.get("GOOGLE_MAPS_KEY"),        # Street View's panorama (the key is in the page: restrict it in Google Cloud)
        settings={"config": {"fill_opacity": 0.35, "casing_opacity": 0.2}},
        road_popup=["edge_id", "container_id", "name", "type", "highway", "level", "width_m", "width_src"],
        color_options={"Roads": {"color_by": "type", "colors": {"road": "#555", "walkway": "#a16207", "cycleway": "#16a34a"}}},
        overlays=ovs)
    cfg = {"marks": [t for t, *_ in d.MARKS if len(F["marks"]) and (F["marks"]["type"] == t).any()], "raised": RAISED, "kerbtop": KERB_TOP_M,
           "objpopup": d.OBJ_POPUP, "bldpopup": d.BLD_POPUP, "lotpopup": d.LOT_POPUP, "groundpopup": d.GROUND_POPUP}
    tail = f'<script>window.US_CFG={json.dumps(cfg)};</script><script src="{ENGINE}"></script>'
    if F["models"]:      # the bridges' 3D models: written beside the page, which reads them when it opens
        col = {"deck": "#a8a29e", "girder": "#8f8b86", "rail": "#cfc8bd",
               "parts": {**d.PART_COLORS, **{f"mark {t}": c for t, c, *_ in d.MARKS}, "mark kerb": "#8f8b86", "barrier": "#cfc8bd", "railing": "#6b7280"}}
        d.write_bridge3d(F["models"], os.path.join(os.path.dirname(os.path.abspath(out)), "bridge3d.json"))
        tail += (d.BRIDGE_JS.replace("__BRNAMES__", ", ".join(mm["name"] for mm in F["models"])).replace("__BRCOL__", json.dumps(col))
                 .replace("__BRPOPUP__", json.dumps(d.BR_POPUP)).replace("__BRUNITS__", json.dumps(F["under"])))
    tail += f'<script src="{PANEL_JS}"></script>'
    # (the head's end, then the body tag after it: the words "<body>" and "</body>" also stand in roadstyle's code, before and after)
    html = m.html
    i = html.index("</head>")
    j = html.index("<body>", i)
    html = (html[:i] + f'<link rel="stylesheet" href="{PANEL_CSS}">' + html[i:j]
            + '<body class="xp"><div id="xpveil">Loading the street space...</div>' + html[j + len("<body>"):])
    head, end = html.rsplit("</body>", 1)
    open(out, "w").write(head + tail + "</body>" + end)
    return out
