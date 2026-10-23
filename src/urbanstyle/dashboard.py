"""Dashboard for a built urbanstyle db: a roadstyle map (basemap picker, Google Street View window) with the
buildings and street spaces as overlays, and a left panel with the hierarchy tree and the level buttons.

    urbanstyle dashboard data/monaco.duckdb viz/monaco.html      # needs roadstyle (pip install urbanstyle[dashboard])

The roads are drawn faintly: roadstyle's Street View follows a clicked road. Serve the page over http for Street View.
"""
import json
import os

import duckdb
import geopandas as gpd
import pandas as pd
import roadstyle as rs
from shapely import wkb

from urbanstyle.parts import KERB_TOP_M, LINE, RAISED

from .container import LEVELS  # noqa: E402  (the levels the build keeps)


def frame(con, sql):
    df = con.execute(sql).fetchdf()
    # (a NULL geometry can come back as NA: an older DuckDB reads a NULL geometry of a newer one so; it is no shape)
    df["geometry"] = [None if g is None or g is pd.NA or (isinstance(g, float) and g != g) else wkb.loads(bytes(g)) for g in df["geometry"]]
    df = df[df["geometry"].notna()]
    return gpd.GeoDataFrame(df, geometry="geometry", crs=4326)


BLOCK_POPUP = ["block_id", "area_m2", "source", "method", "sides"]
KIND_COLORS = {
    # layer 0
    "street": "#94a3b8", "block": "#d4a373",
    # layer 1: the street's pieces, and the land in the blocks
    "subsection": "#bfdbfe", "intersection": "#f97316",
    "building": "#a8a29e", "yard": "#f3e9d2", "alley": "#cfc8c0", "green": "#6cc070", "path": "#e0a96d", "car park": "#22b8cf",
    "construction site": "#fcd34d", "square": "#fbcfe8", "rail": "#64748b", "structure": "#8b5e3c", "water": "#38bdf8", "unknown": "#ff00ff",
    "plot": "#a16207",
    # layer 2: surfaces (a kind of layer 1 keeps its colour)
    "roadway": "#6b7280", "pedestrian realm": "#e5e7eb", "median": "#84cc16", "verge": "#86efac", "garden": "#4caf50", "lawn": "#a7d7a0",
    "play": "#f472b6", "track bed": "#64748b", "under bridge": "#8b5e3c", "paved": "#fbcfe8",
    # layer 3: parts (the roadway's darker greys, the pedestrian realm's light ones)
    "lane": "#4b5563", "shoulder": "#9ca3af", "junction area": "#374151", "island": "#84cc16", "barrier": "#cfc8bd", "furnishing": "#a8a29e", "sidewalk": "#e5e7eb",
    "frontage": "#fde4cf",
}
BLOCK_COLOR = KIND_COLORS["block"]
PATH_COLORS = {"sidewalk": "#c4b5fd", "footway": "#8b5cf6", "path": "#8b5cf6", "pedestrian": "#c4b5fd", "steps": "#b45309",
               "cycleway": "#059669", "crossing": "#f8fafc"}     # paths lie on every layer: violets (and a cycleway green, a crossing white)


def blocks_frame(con):
    """The blocks (work.block, docs/design/blocks.md) with their street sides in one line each: the road, its distance and what set it."""
    try:
        return frame(con, """SELECT ST_AsWKB(b.geometry) AS geometry, b.block_id, b.level, round(b.area_m2) AS area_m2, b.source, b.method,
            s.sides FROM work.block b LEFT JOIN (SELECT block_id, string_agg(coalesce(name, class) || ': ' || distance_m || ' m from ' || basis
              || CASE WHEN unpulled_m IS NOT NULL THEN ' (was ' || unpulled_m || ' m, ' || building || ')' ELSE '' END, '; ' ORDER BY name)
              AS sides FROM work.block_side GROUP BY 1) s USING (block_id)""")
    except duckdb.CatalogException:     # built before the blocks
        return None


ON_PARTS = ("crosswalk", "cycle crossing", "bus zone", "driveway")     # on the parts, not between them (docs/design/space-layers.md, layer 3)
BLOCK_NEAR_DEG = 0.0004    # blocks this near (about 30-45 m: across a street) get different colours
BLOCK_PALETTE = ["#e6a157", "#7fb3d5", "#82c99a", "#d98cb3", "#c9b458", "#9e8fd1", "#e08a7a", "#6fc2bf"]


def block_colors(blocks):
    """Each block a colour of BLOCK_PALETTE that no block touching it has (greedy, in id order), so neighbours tell apart in 2D (one
    colour for all read as one area: Kaveh, 2026-10-13, "I can't distinguish different blocks")."""
    import shapely
    gs = list(blocks.geometry)
    tree = shapely.STRtree(gs)
    col = {}
    for k in sorted(range(len(gs)), key=lambda k: str(blocks["block_id"].iloc[k])):
        near = {col[j] for j in tree.query(gs[k].buffer(BLOCK_NEAR_DEG)) if j in col}     # (across a street too: grid blocks never touch)
        col[k] = next((c for c in BLOCK_PALETTE if c not in near), BLOCK_PALETTE[k % len(BLOCK_PALETTE)])
    return blocks.assign(color=[col[k] for k in range(len(gs))])


def tree_data(con, epsg):
    q = lambda sql: con.execute(sql).fetchall()
    by_level = dict(q("""SELECT l, count(*) FROM work.element, generate_series(level_min, level_max) t(l)
                         WHERE type = 'building' GROUP BY l ORDER BY l"""))
    tree = {"buildings": {"total": sum(1 for _ in q("SELECT 1 FROM work.element WHERE type = 'building'")), "byLevel": by_level},
            "containers": {}}
    for l, c, n, r, w, cy, m, k, rl, sid, *bb in q("""SELECT level, container_id, name, n_road, n_walkway, n_cycleway, mean_width_m, kind, n_rail, street_id,
            ST_XMin(geometry), ST_YMin(geometry), ST_XMax(geometry), ST_YMax(geometry)
            FROM work.container ORDER BY level, name NULLS LAST"""):
        tree["containers"].setdefault(l, []).append({"id": c, "n": n, "r": r, "w": w, "c": cy, "m": m, "k": k, "t": rl, "s": sid, "b": bb})
    tree["stations"] = [{"id": i, "n": n, "k": k, "l": l, "b": [x - 0.0012, y - 0.0007, x + 0.0012, y + 0.0007]}
                        for i, n, k, l, x, y in q("SELECT id, name, kind, level, ST_X(geometry), ST_Y(geometry) FROM work.station ORDER BY level, name")]
    area = lambda col="geometry": f"ST_Area(ST_Transform({col}, 'EPSG:4326', '{epsg}', always_xy := true))"
    tree["info"] = {}   # container id -> area, zone areas, mean widths, quality, objects by class: what the focus panel shows
    for cid, a, m, o, ks, nh, wh in q(f"""SELECT container_id, {area()}, mean_width_m, open_share, kerb_share, narrow_half_m, wide_half_m FROM work.container"""):
        tree["info"][cid] = {"a": round(a), "m": m, "o": o, "ks": ks, "nh": nh, "wh": wh, "z": {}, "ob": {}}
    for cid, z, a in q(f"SELECT container_id, zone, {area()} FROM work.zone"):
        if cid in tree["info"]:
            tree["info"][cid]["z"][z] = round(a)
    try:
        for cid, ty, a in q(f"SELECT container_id, type, sum({area()}) FROM work.strip GROUP BY ALL"):
            if cid in tree["info"]:
                tree["info"][cid].setdefault("st", {})[ty] = round(a)
    except duckdb.CatalogException:
        pass
    for cid, cls, n in q("SELECT container_id, class, count(*) FROM work.object WHERE container_id IS NOT NULL GROUP BY ALL"):
        if cid in tree["info"]:
            tree["info"][cid]["ob"][cls] = n
    tree["secarms"] = {}                  # section id -> the intersections it meets (their crossings and signals belong to its view)
    for sid, iid in q("SELECT DISTINCT section_id, intersection_id FROM work.arm WHERE section_id IS NOT NULL"):
        tree["secarms"].setdefault(sid, []).append(iid)
    tree["arms"] = {}                     # intersection id -> the street groups that meet there (an intersection is in several)
    for iid, sid in q("SELECT DISTINCT intersection_id, street_id FROM work.arm WHERE street_id IS NOT NULL"):
        tree["arms"].setdefault(iid, []).append(sid)
    tree["streets"] = {sid: {"n": n, "l": l, "ns": ns, "ni": ni} for sid, l, n, ns, ni in
                       q("SELECT street_id, level, name, n_section, n_intersection FROM work.street")}
    for cid, ids, n, m in q("SELECT container_id, list(building_id ORDER BY length_m DESC), count(*), sum(length_m) FROM work.boundary GROUP BY 1"):
        if cid in tree["info"]:
            tree["info"][cid]["bb"] = ids
            tree["info"][cid]["bn"] = [n, round(m)]
    tree["objects"] = {}
    for cls, n in q("SELECT class, count(*) FROM work.object GROUP BY 1 ORDER BY 1"):
        tree["objects"].setdefault(cls.split(".")[0], {})[cls] = n
    tree["links"] = {}
    for ty, a, b, n in q("SELECT type, level_a, level_b, count(*) FROM work.link GROUP BY ALL ORDER BY ALL"):
        tree["links"].setdefault(ty, {})[f"{a},{b}"] = n
    return tree


# the parts of a space (parts.py): a colour per type, lanes by direction
PART_COLORS = {"lane circulating": "#4b5260", "ring": "#4b5260", "junction area": "#4b5260", "lane in": "#4b5260", "lane out": "#454c59", "lane forward": "#4b5260", "lane backward": "#454c59",
               "lane both": "#4b5260", "lane": "#4b5260", "shoulder": "#5c6370", "parking": "#64748b", "no parking": "#4b5260", "bus zone": "#7f1d1d",
               "parking lot": "#94a3b8", "paved": "#4b5260", "bus lane": "#9b2c2c",
               "cycle lane": "#2f855a", "cycle crossing": "#38a169", "crosswalk": "#6b7280", "island": "#8fbf6f",
               "sidewalk": "#d8d2c6", "furnishing": "#b9a58b", "frontage": "#ece6da", "open": "#e9e4d6", "bus stop": "#93c5fd",
               "tree pit": "#6b4f2a", "driveway": "#a8a29e", "verge": "#c9c4b8", "bridge deck": "#c9c4b8"}   # asphalt, paving; crosswalks are asphalt under their zebra bars
SEEN_COLORS = {"parking": "#2563eb", "no parking": "#9333ea", "give way": "#f97316", "stop": "#dc2626", "traffic light": "#ef4444",
               "street light": "#facc15", "bin": "#65a30d", "bench": "#84cc16", "lane arrow": "#06b6d4", "zebra": "#ffffff"}
PHOTOS_PER_SPACE = 6
# painted and built lines, at real size: type, colour, width in metres, dash
# painted and built lines: type, colour, dash; drawn at the width stored on the mark (parts.LINE, work.mark.width_m)
# (a dash is in line widths: a lane line 0.12 m wide, 3 m painted and 6 m gap, as TAC's manual for Canada (MUTCDC) paints it, is [25, 50];
# the line between the two directions is yellow and solid. A guide line is no paint: SUMO's move through a junction, thin amber dots)
MARKS = [(t, c, LINE[t], d) for t, c, d in (("guide line", "#f59e0b", [1, 4]), ("arrow", "#ffffff", None), ("kerb", "#9ca3af", None),
         ("centre line", "#facc15", None), ("lane line", "#ffffff", [25, 50]), ("edge line", "#ffffff", None), ("stop line", "#ffffff", None),
         ("give-way line", "#ffffff", [1, 1]), ("zebra", "#ffffff", None), ("crossing line", "#ffffff", None), ("barrier", "#6b7280", None), ("parking line", "#ffffff", [8, 8]))]
PANEL = """
<style>.co-lg{display:none}  /* no road legend: the panel says what is drawn */
body.u3d .rs-tip{display:none!important}#map{left:340px!important}body.us-off #map{left:0!important}body.us-off #us{display:none}
#usfold{position:fixed;top:6px;left:304px;z-index:6;width:28px;height:28px;border:1px solid #cbd5e1;border-radius:6px;background:#fff;cursor:pointer;
  font:15px/1 system-ui;color:#475569;box-shadow:0 1px 3px #0002}body.us-off #usfold{left:8px}.ov-ctrl{display:none!important}  /* roadstyle's own Layers box: the panel list replaces it */
#us{position:fixed;top:0;left:0;bottom:0;width:340px;overflow:auto;padding:8px;box-sizing:border-box;background:#fafafa;
    border-right:1px solid #ddd;font:13px sans-serif;z-index:5}
#us details{margin-left:14px}#us summary{cursor:pointer;padding:1px 3px;border-radius:3px}
#us summary i{color:#777;font-style:normal;font-size:11px}#us summary.on{background:#dbeafe}
#us summary.leaf{list-style:none;margin-left:-4px}#us>#tree>details{margin-left:0}
#us #chips{margin:6px 0;display:flex;flex-wrap:wrap;gap:4px 10px}#us #chips label{cursor:pointer;white-space:nowrap}#us #chips .sw{display:inline-block;width:12px;height:12px;margin-right:4px;vertical-align:-2px;border:1px solid #0004;border-radius:2px}#us #more{margin:4px 0}#us #more>summary{cursor:pointer;font-weight:600;color:#374151}#us .gh{margin-top:6px}#us #lg{margin:6px 0;font-size:12px;line-height:1.55}#us #lg b{display:block;margin-top:5px}#us #lg label{display:block;cursor:pointer}#us #lg i{color:#777;font-style:normal;font-size:11px}#us #lg .nb b{display:inline;margin:0}#us #lg .nb{margin-top:6px;padding:4px 6px;background:#fff7e0;border:1px solid #f0d890;border-radius:4px;color:#554}#us #lg input{margin:0 5px 0 0;vertical-align:-2px}#us #lg span.sw{display:inline-block;width:11px;height:11px;margin:0 4px 0 0;vertical-align:-1px;border:1px solid #0003}#us #lg span.ci{border-radius:50%}#us #lg span.ln{height:3px;margin-top:4px;vertical-align:2px}#us #jump{margin:4px 0;font-size:12px}#us #jump:empty{display:none}#us #jump{background:#eef6ff;border:1px solid #b6d4fe;border-radius:4px;padding:4px 6px}#us #jump button{margin:0 2px;padding:1px 8px}#us #focus{margin:6px 0;font-size:12px;border:2px solid #7c3aed;border-radius:5px;padding:6px 8px;background:#faf5ff}#us #focus:empty{display:none}#us #focus h4{margin:0 0 4px;font-size:13px}#us #focus table{border-collapse:collapse;width:100%}#us #focus td{padding:1px 4px}#us #focus td:last-child{text-align:right}#us #focus button{margin:4px 0 0;padding:2px 10px}#us #focus .sw{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:-1px}#us #lv button{margin:1px;padding:2px 8px}#us #lv .on{background:#1a73e8;color:#fff}#us #q{width:100%;box-sizing:border-box;margin:6px 0}
</style>
<button id=usfold title="Hide the panel">&laquo;</button>
<div id=us><b>urbanstyle</b> &middot; street space by level
<div id=lv>level: __LEVELBTNS__</div>
<label title="3D view only: the ground follows the hill (public 30 m terrain: rough, roads and buildings do not sit right on it)"><input type=checkbox id=terrain3d> rough terrain</label>
<label id=allbox title="2D is a map: roads as lines, objects as dots. Tick to draw the real-size road surface in 2D too (lanes, crosswalks, sidewalks, markings), as 3D always does"><input type=checkbox id=allparts> road surface in 2D</label>
<label title="Mapillary's detections, for validation only: their positions are too rough to make an object (a median 6 m off the city's surveyed poles). Green: it confirms a surveyed or mapped object; orange: nothing confirms it"><input type=checkbox id=mlybox> Mapillary detections (validation)</label>
<div id=jump></div>
<div id=focus></div>
<div id=chips></div>
<details id=more><summary>More layers</summary><div id=lg></div></details>
<input id=q placeholder="find a street, or type an id (s0-123, p0-4, i0-5) + Enter"><div id=tree></div></div>
<script>
const NEWU=__NEWU__, MK=__MARKS__, tree=__TREE__, LV=__LEVELS__, LK=__LINKDEF__, HAS=__HAS__, OB=__OBJDEF__, KD=__KINDS__, SD=__STRIPS__;
const setOv=(lab,on)=>{if(lab.startsWith('Link: ')||lab.startsWith('Objects: ')||lab.startsWith('Strip: ')||lab.startsWith('Mark: ')||['Pedestrian realm','Travelway','Buildings',...KD.map(k=>k.lab)].includes(lab)||HAS.includes(lab))rsSetOverlay(lab,on)};           // LK: [{t, lab, c, d}] link types present in this area
const LKLAB=Object.fromEntries(LK.map(k=>[k.t,k.lab]));
// Layers in groups: [title, rows]. A row: key, name, colour, swatch shape, what it is. Only the street spaces and the buildings start ticked;
// everything else is off until ticked, or shown automatically when a street space is in focus.
const GROUPS=[
  ['Street spaces',KD.map(k=>['c:'+k.k,k.lab,k.c,'',({section:'a stretch of a street between two intersections',intersection:'where streets meet',path:'footpaths away from any road',rail:'tracks and their structure',plaza:'a wide open space framed by buildings'})[k.k]||''])],
  ['Inside a street space (shown in focus)',[
    ['travelway','Travelway','#6b7280','','where vehicles move: out to the nearest sidewalk where one is found, else the lane width'],
    ['pedestrian','Pedestrian realm','#f8c4b4','','the rest: sidewalk, furnishing, frontage'],
    ['track','Track','#f0abfc','','the tracks of a rail space']]],
  ['Buildings',[['buildings','Buildings','#3b82f6','','footprints that have a floor at the selected level']]],
  ['Objects (shown in focus)',OB.map(o=>['o:'+o.g,o.g,o.c,'ci',({furniture:'lamps, signs, benches, bins, bollards, bike parking, vending, post boxes',vegetation:'trees',transit:'bus stops and platforms',crossing:'zebra, signalised and other crossings',kerb:'kerb points',access:'building and car-park entrances',barrier:'other barrier points'})[o.g]||''])],
  ['Network',[['r:road','Road centerline','#555','ln','click one for Street View'],['r:walkway','Walkway centerline','#a16207','ln','footway, steps, crossing'],['r:cycleway','Cycleway centerline','#16a34a','ln',''],
    ['rail','Rail line','#c026d3','ln',''],['stations','Station','#0d9488','ci','']].concat(LK.map(k=>['k:'+k.t,'Link: '+k.lab,k.c,'ci',k.d]))]];
const show={}; GROUPS.forEach(g=>g[1].forEach(r=>show[r[0]]=(r[0].startsWith('c:')&&!HAS.includes('Spaces'))||r[0]==='buildings'||r[0].startsWith('r:')));   // roads start drawn (2D is a map); with the new spaces (work.unit) the old containers start hidden
const row=r=>`<label><input type=checkbox data-k="${r[0]}" ${show[r[0]]?'checked':''}><span class="sw ${r[3]}" style="background:${r[2]}"></span>${r[1]}${r[4]?` <i>${r[4]}</i>`:''}</label>`;
document.getElementById('chips').innerHTML=GROUPS[0][1].concat(GROUPS[2][1]).map(r=>`<label title="${r[4]}"><input type=checkbox data-k="${r[0]}" ${show[r[0]]?'checked':''}><span class="sw" style="background:${r[2]}"></span>${r[1]}</label>`).join('');   // (each its real state: all were drawn ticked)
document.getElementById('lg').innerHTML=GROUPS.slice(1).map((g,i)=>`<div class=gh><label><input type=checkbox data-g="${i+1}"><b>${g[0]}</b></label></div>`+g[1].map(row).join('')).join('')+
  '<div class=nb>Everything else on the map (streets, icons, labels) is the <b>basemap</b>, not our data. Change or hide it with the basemap button at the top right.</div>';
const setKey=(k,v)=>{show[k]=v; document.querySelectorAll(`input[data-k="${k}"]`).forEach(i=>i.checked=v)};
const onChange=e=>{const d=e.target.dataset;
  if(d.k)setKey(d.k,e.target.checked);
  else if(d.g){GROUPS[+d.g][1].forEach(r=>setKey(r[0],e.target.checked))}   // a group's own checkbox switches all its rows
  else return; apply()};
document.getElementById('lg').onchange=onChange; document.getElementById('chips').onchange=onChange;
const span=l=>p=>p.level_min<=l&&p.level_max>=l;
let sel={t:'root',l:0};
function apply(){
  const {t,l,cid,zone}=sel, cs=sel.cids, showB=['root','bld','bldL','ctr','ctrL','stn'].includes(t), showZ=t!=='bld'&&t!=='bldL';
  const focused=t==='street'||t==='zone';
  // 2D is a map (roads as lines, objects as dots); "road surface in 2D" ticked: every space's real-size ground and markings too
  const ALL=HAS.includes('Parts')&&document.getElementById('allparts').checked;
  // an intersection with a new space in focus: exactly that space (its area, cuts, road pieces, bounding buildings, what stands inside)
  const IX=focused&&!sel.gid&&NEWU.inter[cid]?cid:null;
  // the roads as lines, every one of the level, focused or not (a focus only highlights); a road type unticked in the tree stays out
  rsFilter(rsQuery(p=>p.level===l&&show['r:'+p.type]===true));
  setMask(focused); setLabels(focused?cs:null); renderFocus();
  // buildings: all of them in the overview; in focus only the ones that bound the focused containers
  const bb=new Set(); if(IX)(NEWU.inter[IX].bb||[]).forEach(b=>bb.add(b[0])); else if(focused)[...cs].forEach(id=>(info(id).bb||[]).forEach(b=>bb.add(b)));
  setOv('Buildings',focused||(showB&&show.buildings));
  if(focused) rsFilter(rsQuery(p=>bb.has(p.id),'Buildings'),'Buildings');
  else if(showB) rsFilter(t==='bld'?null:rsQuery(span(l),'Buildings'),'Buildings');
  const NEW=HAS.includes('Spaces');   // the new spaces replace the old containers in focus; their checkboxes still bring them back
  KD.forEach(k=>{setOv(k.lab,showZ&&t!=='zone'&&((focused&&!NEW)||show['c:'+k.k]));
    if(showZ&&t!=='zone') rsFilter(rsQuery(p=>p.level===l&&(!cs||cs.has(p.cid)),k.lab),k.lab)});
  const ex=new Set(cs||[]); if(t==='street'&&cs)[...cs].forEach(id=>(tree.secarms[id]||[]).forEach(i=>ex.add(i)));   // a section's crossings and signals sit in its intersections
  const stripsOn=t==='street'&&SD.length>0&&!NEW;   // a focused street space is shown as its strips (lanes, sidewalk, ...) instead of its two zones
  SD.forEach(s=>{const lab='Strip: '+s.t; setOv(lab,stripsOn); if(stripsOn) rsFilter(rsQuery(p=>p.level===l&&ex.has(p.cid),lab),lab)});
  [['Travelway','travelway','travelway'],['Pedestrian realm','pedestrian_realm','pedestrian'],['Track','track','track']].forEach(([lab,z,k])=>{
    const on=showZ&&!stripsOn&&(!zone||zone===z)&&((focused&&!NEW)||show[k]); setOv(lab,on);
    if(on&&(lab!=='Track'||HAS.includes('Track'))) rsFilter(rsQuery(p=>p.level===l&&(!cs||cs.has(p.cid))&&(!zone||p.zone===z),lab),lab)});
  const here=['root','ctr','ctrL','lnk','stn','station'].includes(t);
  if(HAS.includes('Rail')){setOv('Rail',here&&show.rail===true); if(here) rsFilter(rsQuery(p=>p.level===l,'Rail'),'Rail')}
  if(HAS.includes('Station')){setOv('Station',here&&show.stations===true);
    if(here) rsFilter(rsQuery(t==='station'?(p=>p.id===sel.sid):(p=>p.level===l),'Station'),'Station')}
  OB.forEach(o=>{const lab='Objects: '+o.g, detail=t==='street'||t==='zone', pick=t==='obj'||t==='objs',
      on=detail?false:pick?(t==='objs'||sel.grp===o.g):(['root','ctr','ctrL'].includes(t)&&show['o:'+o.g]===true);
    setOv(lab,on&&(pick||show['o:'+o.g]===true));
    if(on) rsFilter(rsQuery(p=>p.level===l&&(!sel.cls||p.class===sel.cls)&&!(sel.hide&&sel.hide.has(p.class)),lab),lab)});
  if(HAS.includes('Objects')){const on=t==='street'||t==='zone'; setOv('Objects',on);
    if(on) rsFilter(rsQuery(p=>p.level===l&&(IX?p.unit===IX:ex.has(p.cid))&&!(sel.hide&&sel.hide.has(p.class)),'Objects'),'Objects')}
  // subsections (lines, a colour each) and the points where a section is split: a focused section shows its own, a focused intersection those of its sections
  const ownSec=sid=>!focused||cs.has(sid)||(tree.secarms[sid]||[]).some(i=>cs.has(i));
  if(HAS.includes('Spaces')){setOv('Spaces',!ALL); rsFilter(rsQuery(p=>p.level===l&&(IX?p.unit_id===IX:ownSec(p.section_id)),'Spaces'),'Spaces')}
  const inside=IX||(focused&&!sel.gid&&HAS.includes('Parts')&&NEWU.sec[cid]);   // a space shown with its parts: its painted lines, not the subsection lines
  ['Subsection axes','Subsection breaks'].forEach(lab=>{if(HAS.includes(lab)){setOv(lab,!inside&&!ALL); if(!inside&&!ALL)rsFilter(rsQuery(p=>p.level===l&&ownSec(p.section_id),lab),lab)}});
  if(HAS.includes('Cuts')){setOv('Cuts',!ALL); rsFilter(rsQuery(p=>p.level===l&&(IX?p.intersection_id===IX:(!focused||cs.has(p.intersection_id)||[...cs].some(s=>(tree.secarms[s]||[]).includes(p.intersection_id)))),'Cuts'),'Cuts')}
  if(HAS.includes('Junction roads')){const jr=!!IX&&!HAS.includes('Parts');   // with its parts shown, the lanes and markings draw the roads
    setOv('Junction roads',jr); if(jr)rsFilter(rsQuery(p=>p.unit_id===IX,'Junction roads'),'Junction roads')}
  // the inside of the focused space(s): an intersection's parts, or a section's subsections' parts, with their painted lines
  const PU=IX?new Set([IX,...(NEWU.inter[IX].adj||[])]):(focused&&!sel.gid&&NEWU.sec[cid])?new Set(NEWU.sec[cid].map(x=>x[0])):null;   // an intersection with the roads arriving at it
  // the level's own spaces, and in the flat view the bridges just above it too (drawn last, on top): in 3D they are decks in the air
  const flat=map.getPitch()<=5, inL=lab=>rsQuery(p=>p.level===l||(flat&&p.level===l+1),lab);
  // tilted: the ground of every space of the level (its roadway, lane lines and arrows), not only the focused one's: the buildings around
  // must not stand on empty ground
  // the real-size ground and markings in 2D only when "road surface in 2D" is ticked (3D draws its own, always)
  const wide=ALL, PF=null;
  if(HAS.includes('Parts')){setOv('Parts',wide); if(wide){rsFilter(inL('Parts'),'Parts'); setOv('Spaces',false)}}
  MK.forEach(t=>{const lab='Mark: '+t; setOv(lab,!!PF||wide); if(PF)rsFilter(rsQuery(p=>PF.has(p.unit_id),lab),lab); else if(wide)rsFilter(inL(lab),lab)});
  // Mapillary's detections: validation only, shown when ticked (green: confirms an object; orange: nothing confirms it)
  if(HAS.includes('Mapillary')){const on=document.getElementById('mlybox').checked; setOv('Mapillary',on);
    if(on&&PU)rsFilter(rsQuery(p=>PU.has(p.unit),'Mapillary'),'Mapillary'); else if(on)rsFilter(inL('Mapillary'),'Mapillary')}
  // the base map shows the streets at ground level: on another level it fades, so that level's own spaces stand out
  map.getStyle().layers.filter(x=>x.source==='bm'&&x.type==='raster').forEach(x=>map.setPaintProperty(x.id,'raster-opacity',l===0?1:0.3));
  if(OVERLAYS.some(o=>o.label==='Ground'))rsFilter(rsQuery(p=>p.level===l,'Ground'),'Ground');   // the ground of the level viewed only
  if(OVERLAYS.some(o=>o.label==='Blocks'))rsFilter(rsQuery(p=>p.level===l,'Blocks'),'Blocks');   // blocks are at level 0 only
  up3d(PU,l,ALL);
  LK.forEach(k=>{const lab='Link: '+k.lab, one=t==='links',
      on=one?k.t===sel.type:['root','ctr','ctrL','lnk'].includes(t)&&show['k:'+k.t]===true;
    setOv(lab,on&&(one||show['k:'+k.t]===true));
    if(on) rsFilter(rsQuery(one?(p=>p.level_a===sel.a&&p.level_b===sel.b):(p=>p.level_a===l||p.level_b===l),lab),lab)});
  if(t==='links'){const lab='Link: '+LKLAB[sel.type], ids=rsQuery(p=>p.level_a===sel.a&&p.level_b===sel.b,lab); if(ids.length)rsFocus(ids,{maxZoom:17},lab)}
  document.querySelectorAll('#lv button').forEach(b=>b.classList.toggle('on',+b.dataset.l===l));
}
let active=null;
function node(label,count,s,kids,bbox){
  const d=document.createElement('details'), m=document.createElement('summary');
  m.innerHTML=`${label} <i>${count??''}</i>`; d.append(m); if(!kids)m.classList.add('leaf');
  m.addEventListener('click',()=>{sel=s.t==='street'?{...s,hide:new Set()}:s;if(active)active.classList.remove('on');m.classList.add('on');active=m;apply();
    if(bbox)map.fitBounds([[bbox[0],bbox[1]],[bbox[2],bbox[3]]],{padding:80,maxZoom:s.t==='street'?23:18})});
  if(kids){let done=false;d.addEventListener('toggle',()=>{if(d.open&&!done){done=true;kids().forEach(k=>d.append(k))}})}
  return d}
const lv=Object.keys(tree.buildings.byLevel).map(Number).sort((a,b)=>a-b);
const label=c=>c.k==='intersection'?'Intersection: '+(c.n||'(unnamed)'):c.k==='path'?'Path space'+(c.n?': '+c.n:''):c.k==='rail'?'Rail space'+(c.n?': '+c.n:''):c.k==='plaza'?'Plaza'+(c.n?': '+c.n:''):'Section'+(c.n?': '+c.n:'');
function containerNode(c){const l=c.l, z=[], one=new Set([c.id]);
  if(c.r)z.push(node('travelway',`${c.r} roads`,{t:'zone',l,cid:c.id,cids:one,zone:'travelway'}));
  if(c.w||c.c)z.push(node('pedestrian realm',`${c.w} walkways${c.c?`, ${c.c} cycleways`:''}`,{t:'zone',l,cid:c.id,cids:one,zone:'pedestrian_realm'}));
  if(c.t)z.push(node('track',`${c.t} rail`,{t:'zone',l,cid:c.id,cids:one,zone:'track'}));
  const d=node(label(c)+(c.m?` · ${Math.round(c.m)} m wide`:''),
    [c.r&&`${c.r} roads`,c.w&&`${c.w} walkways`,c.c&&`${c.c} cycleways`,c.t&&`${c.t} rail`].filter(Boolean).join(', ')+` · ${c.id}`,{t:'street',l,cid:c.id,cids:one},()=>z,c.b);
  d.dataset.name=((c.n||'')+' '+c.id).toLowerCase();return d}
const kindNodes=(l,k)=>(tree.containers[l]||[]).filter(c=>c.k===k).map(c=>containerNode(byId[c.id]));
const armsOf={}; Object.entries(tree.arms).forEach(([i,a])=>a.forEach(g=>(armsOf[g]=armsOf[g]||[]).push(i)));
// a street group: its sections, and the intersections it arrives at (an intersection is listed in every group that meets there)
function groupNodes(l){const bySid={}; (tree.containers[l]||[]).filter(c=>c.k==='section').forEach(c=>(bySid[c.s]=bySid[c.s]||[]).push(c.id));
  return Object.entries(bySid).map(([gid,secs])=>{const st=tree.streets[gid]||{}, inter=(armsOf[gid]||[]).filter(i=>byId[i]&&byId[i].l===l), cids=new Set([...secs,...inter]);
    const d=node(st.n||'(unnamed street)',`${secs.length} sections, ${inter.length} intersections · ${gid}`,{t:'street',l,gid,cids},
      ()=>[...secs.map(i=>containerNode(byId[i])),...inter.map(i=>containerNode(byId[i]))],union(cids));
    d.dataset.name=((st.n||'')+' '+gid).toLowerCase(); return d}).sort((a,b)=>a.dataset.name.localeCompare(b.dataset.name))}
const levelNodes=l=>{const n=k=>(tree.containers[l]||[]).filter(c=>c.k===k).length, out=[];
  const ng=new Set((tree.containers[l]||[]).filter(c=>c.k==='section').map(c=>c.s)).size;
  if(ng)out.push(node('Streets',`${ng} streets, ${n('section')} sections`,{t:'ctrL',l},()=>groupNodes(l)));
  if(n('intersection'))out.push(node('Intersections',n('intersection'),{t:'ctrL',l},()=>kindNodes(l,'intersection')));
  if(n('path'))out.push(node('Path spaces',n('path'),{t:'ctrL',l},()=>kindNodes(l,'path')));
  if(n('plaza'))out.push(node('Plazas',n('plaza'),{t:'ctrL',l},()=>kindNodes(l,'plaza')));
  if(n('rail'))out.push(node('Rail spaces',n('rail'),{t:'ctrL',l},()=>kindNodes(l,'rail')));
  return out};
const root=node('Pilot area',null,{t:'root',l:0},()=>[
  node('Buildings',tree.buildings.total,{t:'bld',l:0},()=>lv.map(l=>node(`level ${l}`,tree.buildings.byLevel[l],{t:'bldL',l}))),
  node('Objects',Object.values(tree.objects).reduce((n,o)=>n+Object.values(o).reduce((x,y)=>x+y,0),0),{t:'objs',l:0},()=>Object.entries(tree.objects).map(([g,o])=>
    node(g,Object.values(o).reduce((x,y)=>x+y,0),{t:'obj',l:0,grp:g},()=>Object.entries(o).map(([cls,n])=>node(cls.split('.')[1].replace(/_/g,' '),n,{t:'obj',l:0,grp:g,cls}))))),
  node('Stations',tree.stations.length,{t:'stn',l:0},()=>tree.stations.map(x=>node(`${x.n||'(unnamed)'} · level ${x.l}`,`${x.k} · ${x.id}`,{t:'station',l:x.l,sid:x.id},null,x.b))),
  node('Links',Object.values(tree.links).reduce((n,o)=>n+Object.values(o).reduce((x,y)=>x+y,0),0),{t:'lnk',l:0},()=>Object.entries(tree.links).map(([ty,o])=>
    node(LKLAB[ty]||ty,Object.values(o).reduce((x,y)=>x+y,0),{t:'lnk',l:0},()=>Object.entries(o).map(([k,n])=>{const [a,b]=k.split(',').map(Number);
      return node(`level ${a} ↔ ${b}`,n,{t:'links',type:ty,a,b,l:a})})))),
  node('Containers',null,{t:'ctr',l:0},()=>[node('Movement container',Object.values(tree.containers).reduce((n,a)=>n+a.length,0),{t:'ctr',l:0},
    ()=>LV.map(l=>node(`level ${l}`,(tree.containers[l]||[]).length,{t:'ctrL',l},()=>levelNodes(l))))])]);
document.getElementById('tree').append(root); root.open=true;
document.getElementById('q').oninput=e=>{const v=e.target.value.toLowerCase();
  document.querySelectorAll('#tree details[data-name]').forEach(d=>d.style.display=d.dataset.name.includes(v)?'':'none')};
document.getElementById('q').onchange=e=>{const v=e.target.value.trim().toLowerCase();       // exact container id: select it and zoom there
  for(const [lvl,arr] of Object.entries(tree.containers)){const c=arr.find(c=>c.id.toLowerCase()===v);
    if(c){focusOn(c.id);return}}
  if(HAS.includes('Spaces')){const v0=e.target.value.trim(); if(rsQuery(q=>q.unit_id===v0,'Spaces').length){focusUnit({unit_id:v0,section_id:v0.split('/')[0]});return}}
  if(tree.streets[e.target.value.trim()])focusGroup(e.target.value.trim())};
document.getElementById('lv').onclick=e=>{const l=e.target.dataset.l; if(l===undefined)return;
  sel=(sel.t==='street'||sel.t==='zone')?{t:'ctrL',l:+l}:sel.t==='links'?{t:'lnk',l:+l}:{...sel,l:+l}; apply()};
// clicking a link or a station on the map: offer buttons that jump to the level(s) it joins
document.addEventListener('rs:select',e=>{const d=e.detail||{}, p=d.properties||{}, box=document.getElementById('jump');
  let levels=null, what='';
  if(p.level_a!==undefined&&p.level_b!==undefined){levels=[p.level_a,p.level_b]; what=`${p.type||'link'} ${p.node_id||''}: levels ${p.level_a} and ${p.level_b}`}
  else if(p.kind&&p.id&&p.level!==undefined&&!p.cid){levels=[p.level]; what=`station ${p.name||p.id}: level ${p.level}`}
  if(!levels){box.innerHTML='';return}
  box.innerHTML=`${what} &rarr; go to level `+levels.map(l=>`<button data-j="${l}">${l}</button>`).join('');
  box.dataset.sid=p.kind&&p.id&&!p.cid?p.id:''});
document.getElementById('jump').onclick=e=>{const j=e.target.dataset.j; if(j===undefined)return;
  const sid=document.getElementById('jump').dataset.sid;
  sel=sid?{t:'station',l:+j,sid}:{t:'lnk',l:+j}; apply()};
// ---- focus mode: one street space and what is in it; everything else is dimmed or hidden
const OBJCOL=Object.fromEntries(OB.map(o=>[o.g,o.c]));
const info=id=>tree.info[id]||{};
const byId={}; Object.entries(tree.containers).forEach(([l,a])=>a.forEach(c=>byId[c.id]={...c,l:+l}));
Object.entries(NEWU.inter).forEach(([id,it])=>{if(!byId[id]){const m=id.match(/^i(-?\d+)-/);   // a junction of the new spaces only (split off a roundabout's group)
  byId[id]={id,k:'intersection',n:[...new Set((it.w||[]).map(r=>r[0]).filter(Boolean))].join(' / '),l:m?+m[1]:0,b:it.b}}});
const union=cids=>{let b=null; cids.forEach(id=>{const c=byId[id]; if(c&&c.b)b=b?[Math.min(b[0],c.b[0]),Math.min(b[1],c.b[1]),Math.max(b[2],c.b[2]),Math.max(b[3],c.b[3])]:[...c.b]}); return b};
const groupCids=sid=>{const st=tree.streets[sid]; if(!st)return new Set();
  const secs=Object.values(byId).filter(c=>c.s===sid).map(c=>c.id), inter=Object.entries(tree.arms).filter(([i,a])=>a.includes(sid)).map(([i])=>i);
  return new Set([...secs,...inter].filter(id=>byId[id]))};
function fit(b){if(b)map.fitBounds([[b[0],b[1]],[b[2],b[3]]],{padding:70,maxZoom:23})}
function focusOn(cid){const c=byId[cid]; if(!c)return; sel={t:'street',l:c.l,cid,cids:new Set([cid]),hide:new Set()}; apply(); fit((NEWU.inter[cid]||{}).b||c.b)}
function focusGroup(gid){const cids=groupCids(gid), st=tree.streets[gid]; if(!st||!cids.size)return; sel={t:'street',l:st.l,gid,cids,hide:new Set()}; apply(); fit(union(cids))}
function focusOff(){sel={t:'ctrL',l:sel.l}; apply()}
function renderFocus(){const box=document.getElementById('focus'), {t,cid,gid}=sel;
  if(t!=='street'&&t!=='zone'){box.innerHTML='';return}
  const ids=[...sel.cids], parts=ids.map(id=>byId[id]).filter(Boolean), f=(x,d=1)=>x==null?'n/a':(+x).toFixed(d), c=gid?null:byId[cid];
  const sum=fn=>parts.reduce((a,p)=>a+(fn(p)||0),0), z={}, ob={};
  ids.forEach(id=>{const i=info(id); Object.entries(i.z||{}).forEach(([k,v])=>z[k]=(z[k]||0)+v)});
  const exi=new Set(ids); if(!gid)ids.forEach(id=>(tree.secarms[id]||[]).forEach(i=>exi.add(i)));
  const nix=!gid&&NEWU.inter[cid];
  if(nix)Object.assign(ob,nix.ob||{}); else exi.forEach(id=>Object.entries(info(id).ob||{}).forEach(([k,v])=>ob[k]=(ob[k]||0)+v));
  const area=ids.reduce((a,id)=>a+(info(id).a||0),0), tot=Object.values(z).reduce((a,b)=>a+b,0)||1;
  const kind={section:'street section',path:'path space',rail:'rail space',plaza:'plaza',intersection:'intersection'};
  const zrow=Object.entries(z).map(([k,v])=>`<tr><td>${k.replace('_',' ')}</td><td>${v.toLocaleString()} m&sup2; · ${Math.round(100*v/tot)}%</td></tr>`).join('');
  const obs=Object.entries(ob).sort((a,b)=>b[1]-a[1]), nob=obs.reduce((a,b)=>a+b[1],0);
  const st={}; ids.forEach(id=>Object.entries(info(id).st||{}).forEach(([k,v])=>st[k]=(st[k]||0)+v));
  const strow=SD.filter(x=>st[x.t]).map(x=>`<tr><td><span class=sw style="background:${x.c}"></span>${x.lab}</td><td>${st[x.t].toLocaleString()} m&sup2;</td></tr>`).join('');
  const orows=obs.map(([k,n])=>`<tr><td><label><input type=checkbox data-cls="${k}" ${sel.hide&&sel.hide.has(k)?'':'checked'}><span class=sw style="background:${OBJCOL[k.split('.')[0]]||'#999'}"></span>${k.split('.')[0]} &middot; ${k.split('.')[1].replace(/_/g,' ')}</label></td><td>${n}</td></tr>`).join('');
  const counts=[sum(p=>p.r)&&`${sum(p=>p.r)} roads`,sum(p=>p.w)&&`${sum(p=>p.w)} walkways`,sum(p=>p.c)&&`${sum(p=>p.c)} cycleways`,sum(p=>p.t)&&`${sum(p=>p.t)} rail`].filter(Boolean).join(', ');
  const bbn=ids.reduce((a,id)=>{const b=info(id).bn; return b?[a[0]+b[0],a[1]+b[1]]:a},[0,0]);
  let head, extra='';
  if(gid){const st=tree.streets[gid], ns=parts.filter(p=>p.k==='section').length, ni=parts.filter(p=>p.k==='intersection').length;
    head=`Focus: street ${st.n||'(unnamed)'} <small>${gid}</small>`; extra=`<div>${ns} sections and ${ni} intersections · ${area.toLocaleString()} m&sup2;</div>`}
  else{const i=info(cid), nu=NEWU.inter[cid]||NEWU.sec[cid];
    head=`Focus: ${(NEWU.inter[cid]||{}).rb?'Roundabout: ':c.k==='intersection'?'Intersection: ':''}${c.n||'(unnamed)'} <small>${cid}</small>`;
    extra=nu?`<div>${kind[c.k]||c.k}, level ${c.l}</div>`+newBlock(cid):
      `<div>${kind[c.k]||c.k}, level ${c.l} · ${area.toLocaleString()} m&sup2;${c.m?` · ${f(c.m,0)} m wide`:''}</div>`+
      (i.nh!=null?`<div>half-widths: narrow side ${f(i.nh)} m, wide side ${f(i.wh)} m · open share ${f(i.o,2)} · kerb found ${f(i.ks,2)}</div>`:'');
    // the street(s) this belongs to: a section is in one street group, an intersection in several (one per street that meets there)
    const gs=c.k==='intersection'?(tree.arms[cid]||[]):(c.s?[c.s]:[]);
    if(gs.length)extra+=`<div>${c.k==='intersection'?'meets':'part of'}: `+gs.map(g=>`<button data-gid="${g}">${(tree.streets[g]||{}).n||'(unnamed)'}</button>`).join(' ')+`</div>`}
  const isNew=!gid&&(NEWU.inter[cid]||NEWU.sec[cid]);   // the new spaces describe themselves; the old container's numbers are left out
  box.innerHTML=`<h4>${head}</h4>${extra}<div>${counts}</div>`+(isNew?'':`
    <div>bounded by <b>${bbn[0]}</b> building${bbn[0]===1?'':'s'} (${bbn[1]} m of edge); the rest of its edge is open ground, a wall or another street space. The bounding buildings are shown.</div>
    <table>${strow||zrow}</table>`)+`
    <b>Inside${exi.size>ids.length&&!nix?' and at its intersections':''} (${nob} objects)</b><table>${orows||'<tr><td>no objects</td><td></td></tr>'}</table>
    <label><input type=checkbox id=bmshow ${bmDim?'checked':''}> keep the basemap visible (dimmed)</label><br>
    <button id=exitfocus>Exit focus (Esc)</button>`;
  document.getElementById('exitfocus').onclick=focusOff; document.getElementById('bmshow').onchange=e=>{bmDim=e.target.checked; setMask(true)}}
document.getElementById('allparts').onchange=()=>apply();
document.getElementById('mlybox').onchange=()=>apply();
// the side panel folds away (the map takes the whole width); remembered in this browser
function fold(off){document.body.classList.toggle('us-off',off); const b=document.getElementById('usfold');
  b.innerHTML=off?'&raquo;':'&laquo;'; b.title=off?'Show the panel':'Hide the panel'; try{localStorage.setItem('us-panel-off',off?'1':'')}catch(e){}
  setTimeout(()=>map.resize(),0)}
document.getElementById('usfold').onclick=()=>fold(!document.body.classList.contains('us-off'));
try{if(localStorage.getItem('us-panel-off'))fold(true)}catch(e){}
document.getElementById('terrain3d').onchange=()=>draw3d();
document.getElementById('focus').onclick=e=>{const g=e.target.dataset.gid; if(g)focusGroup(g)};
// the new spaces (work.unit): an intersection's area and how each arm was cut; a section's subsections, one row each
const CUTCOL={'block corners':'#16a34a','one corner':'#f59e0b','crosswalk':'#2563eb'}, PCOL=__PCOL__;
function newBlock(cid){const it=NEWU.inter[cid], ss=NEWU.sec[cid];
  if(it){const bl=it.bb||[], bm=Math.round(bl.reduce((a,b)=>a+b[1],0));
    return `<div><b>${it.rb?'Roundabout':'Intersection'} space</b> · ${it.a.toLocaleString()} m&sup2; · bounded by <b>${bl.length}</b> building${bl.length===1?'':'s'} (${bm} m of edge), the rest by its cuts</div>`+
      `<div><b>Arms</b> (widths at the cut, m)</div><table><tr><th></th><th>total</th><th>road</th><th>left</th><th>right</th><th>lanes in/out</th><th>turns</th></tr>`+
      (it.w||[]).map(([n,t,c,l,r,i,o,s,tu])=>`<tr><td>${n}</td><td>${t}</td><td>${c}</td><td>${l}</td><td>${r}</td><td>${i} / ${o}${s==='default'?' *':''}</td><td>${tu||''}</td></tr>`).join('')+
      `</table><div style="font-size:11px;color:#666">left / right: pedestrian realm, seen from the junction · * lane count urbanstyle's (no lanes tag) · turns: each lane coming in, from the right, the ways it may go (SUMO)</div>`+partsTable(cid)+
      photoBlock(cid)+`<div><b>Cuts</b></div><table>`+
    it.cuts.map(([how,len])=>`<tr><td><span class=sw style="background:${CUTCOL[how]||'#6b7280'}"></span>${how}</td><td>${len} m</td></tr>`).join('')+'</table>'}
  return `<div><b>New spaces</b> · ${ss.length} subsection${ss.length===1?'':'s'} · ${ss.reduce((a,x)=>a+x[1],0).toLocaleString()} m&sup2;</div><table>`+
    ss.map(([id,a,len,l,r,col])=>{const w=(NEWU.subw||{})[id];
      return `<tr><td><span class=sw style="background:${col}"></span>${id.split('/')[1]} · ${len} m</td><td>${a.toLocaleString()} m&sup2; · ${l} | ${r}`+
        (w?`<br><small>across: ${w[1]} m = ${w[3]} + road ${w[2]} + ${w[4]} · lanes ${w[5]} fwd / ${w[6]} back</small>`:'')+`</td></tr>`}).join('')+'</table>'+
    partsTable(...ss.map(x=>x[0]))+photoBlock(...ss.map(x=>x[0]))}
function photoBlock(...uids){const ps=uids.flatMap(u=>(NEWU.photos||{})[u]||[]).sort((a,b)=>b[1].localeCompare(a[1])).slice(0,6);   // the newest photos taken in the space
  return ps.length?`<div><b>Photos</b> (Mapillary, newest first)</div><div>`+ps.map(([id,d,pano])=>`<a href="https://www.mapillary.com/app/?pKey=${id}&focus=photo" target="_blank">${d}${pano?' 360&deg;':''}</a>`).join(' · ')+
    `</div><div style="font-size:11px;color:#666">photos and the Mapillary layer: &copy; Mapillary contributors, CC BY-SA 4.0</div>`:''}
function partsTable(...uids){const t={}; uids.forEach(u=>Object.entries((NEWU.parts||{})[u]||{}).forEach(([k,v])=>t[k]=(t[k]||0)+v));
  const rows=Object.entries(t).sort((a,b)=>b[1]-a[1]);
  return rows.length?`<div><b>Parts</b></div><table>`+rows.map(([k,v])=>`<tr><td><span class=sw style="background:${PCOL[k]||PCOL[k.split(' ')[0]]||'#999'}"></span>${k}</td><td>${Math.round(v).toLocaleString()} m&sup2;</td></tr>`).join('')+'</table>':''}
document.getElementById('focus').onchange=e=>{const k=e.target.dataset.cls; if(!k)return; sel.hide=sel.hide||new Set(); e.target.checked?sel.hide.delete(k):sel.hide.add(k); apply()};
// Esc: first deselects what is selected (3D: the lane or object; 2D: roadstyle's selection), then leaves a focus
document.addEventListener('keydown',e=>{if(e.key!=='Escape')return;
  if(in3d&&deselect3d())return;
  if(!in3d&&typeof _sel!=='undefined'&&_sel){rsDeselect(); document.querySelectorAll('.maplibregl-popup').forEach(x=>x.remove()); return}
  if(sel.t==='street'||sel.t==='zone')focusOff()});
// clicking a street space (or one of its zones) on the map focuses it
// Two views of the same data, each its own set of layers. 2D: roadstyle's overlays (their wanted visibility is ov.visible, kept by the
// panel and the layer list in both views). 3D (tilt the map, roadstyle's 3D button): the u3d-* layers below, made from the same sources:
// every space's ground on the level (the roadway flat, sidewalks and islands raised), its painted lines, the buildings to their floors,
// the levels above as bridge decks, and one model per street object. Switching shows one set and hides the other; nothing else.
const RAISE=__RAISED__;   // parts.RAISED: the parts above the roadway, their top (m)
const LEVEL_M=3.2, DECK_M=6, SLAB_M=0.6;   // a building's floor; a bridge level's height above the one viewed, its deck's thickness
const ovSrc=lab=>(OVERLAYS.find(o=>o.label===lab)||{}).source;
const byKey=(key,table,dflt)=>['match',['get',key],...Object.entries(table).flatMap(([k,v])=>[k,v]),dflt];
const NOT_IN_3D=['Mark: kerb'];   // the raised sidewalk's edge is the kerb; the guide lines (lane to lane through a junction) stay
let lv3d=0, in3d=false, roads2d={};
const U3D=[];
function up3d(PU,l,all){lv3d=l; if(in3d)draw3d()}
// terrain in 3D, only when ticked (off by default): public terrain tiles on AWS (Terrarium, about 30 m detail) are too coarse for Monaco's
// terraces and stacked streets - roads sink into the hill, buildings float. A fine terrain (1-5 m) is needed before it can be on by default.
const DEM_TILES='https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png';
function terrain(on){if(!map.setTerrain)return;
  if(on&&!map.getSource('u3d-dem'))map.addSource('u3d-dem',{type:'raster-dem',tiles:[DEM_TILES],tileSize:256,encoding:'terrarium',maxzoom:15,
    attribution:'Terrain: <a href="https://registry.opendata.aws/terrain-tiles/" target="_blank">AWS Terrain Tiles</a>'});
  const now=!!map.getTerrain&&!!map.getTerrain(); if(on!==now)map.setTerrain(on?{source:'u3d-dem',exaggeration:1}:null)}
function draw3d(){
  map.setLight({anchor:'viewport',intensity:0.15});   // a soft light: white walls stay near-white (MapLibre's 0.5 made them grey, Kaveh 2026-10-13)
  terrain(in3d&&document.getElementById('terrain3d').checked);
  const add=(spec,filter)=>{if(!spec.source)return; if(!map.getLayer(spec.id)){map.addLayer(spec); U3D.push(spec.id)}
    map.setFilter(spec.id,filter); map.setLayoutProperty(spec.id,'visibility',in3d?'visible':'none')};
  const lvl=['==',['get','level'],lv3d];
  const own=['all',lvl,['!',['in',['get','unit_id'],['literal',window.brUnits||[]]]]];   // (on a bridge: the model lays them on its deck)
  add({id:'u3d-gnd',type:'fill',source:ovSrc('Ground'),paint:{'fill-color':['get','color'],'fill-opacity':1}},['all',lvl,['!=',['get','type'],'street']]);   // the ground beside the street
  add({id:'u3d-lot',type:'fill',source:ovSrc('Parking lots'),paint:{'fill-color':'#a8b0ba','fill-opacity':1}},lvl);   // a car park: paved, flush
  add({id:'u3d-ground',type:'fill',source:ovSrc('Parts'),paint:{'fill-color':['get','color'],'fill-opacity':1}},
      ['all',own,['!',['in',['get','type'],['literal',Object.keys(RAISE)]]]]);
  OVERLAYS.filter(o=>o.label.startsWith('Mark: ')&&!NOT_IN_3D.includes(o.label)).forEach(o=>{   // the paint, as in 2D, on the 3D ground
    const l2=map.getStyle().layers.find(x=>x.id===o.layers[0]); if(!l2)return;
    add({id:'u3d-'+o.layers[0],type:l2.type,source:o.source,paint:l2.paint||{},layout:Object.assign({},l2.layout||{},{visibility:'none'})},own)});
  // the kerb: a stone 0.25 m wide along the roadway's edge
  add({id:'u3d-kerb',type:'fill-extrusion',source:ovSrc('Kerbs 3D'),paint:{'fill-extrusion-color':'#8f8b86','fill-extrusion-opacity':1,
      'fill-extrusion-height':__KERBTOP__}},own);     // a grey stone, standing 5 cm above the sidewalk: the kerb reads as a line
  add({id:'u3d-raised',type:'fill-extrusion',source:ovSrc('Parts'),paint:{'fill-extrusion-color':['get','color'],'fill-extrusion-opacity':1,
      'fill-extrusion-height':byKey('type',RAISE,0)}},['all',own,['in',['get','type'],['literal',Object.keys(RAISE)]]]);
  add({id:'u3d-bld',type:'fill-extrusion',source:ovSrc('Buildings'),paint:{'fill-extrusion-color':'#ffffff','fill-extrusion-opacity':0.92,'fill-extrusion-vertical-gradient':false,
      'fill-extrusion-height':['get','height_m'],'fill-extrusion-base':['*',['max',['get','level_min'],0],LEVEL_M]}},     // its real height
      ['>=',['get','level_max'],0]);
  const up=['*',['-',['get','level'],lv3d],DECK_M];   // bridges: the levels above, as decks in the air
  add({id:'u3d-deck',type:'fill-extrusion',source:ovSrc('Parts'),paint:{'fill-extrusion-color':['get','color'],'fill-extrusion-opacity':1,
      'fill-extrusion-base':['-',up,SLAB_M],'fill-extrusion-height':['+',up,byKey('type',RAISE,0)]}},
      ['all',['>',['get','level'],lv3d],['!',['in',['get','unit_id'],['literal',window.brUnits||[]]]]]);   // (a bridge's 3D model replaces its deck)
  add({id:'u3d-furn',type:'fill-extrusion',source:ovSrc('Street objects 3D'),paint:{'fill-extrusion-color':['get','color'],'fill-extrusion-opacity':1,
      'fill-extrusion-base':['get','base'],'fill-extrusion-height':['get','height']}},lvl);
  bind3d();
}
function setView(){const t=map.getPitch()>5; document.body.classList.toggle('u3d',t);
  if(t!==in3d){in3d=t;
    if(t){map.getStyle().layers.forEach(x=>{if(/^roads-/.test(x.id)){roads2d[x.id]=map.getLayoutProperty(x.id,'visibility')||'visible';
            map.setLayoutProperty(x.id,'visibility','none')}});
          OVERLAYS.forEach(o=>(o.layers||[]).forEach(id=>{if(map.getLayer(id))map.setLayoutProperty(id,'visibility','none')}))}
    else{U3D.forEach(id=>{if(map.getLayer(id))map.setLayoutProperty(id,'visibility','none')}); tip3d.remove();
         Object.entries(roads2d).forEach(([id,v])=>{if(map.getLayer(id))map.setLayoutProperty(id,'visibility',v)});
         OVERLAYS.forEach(o=>(o.layers||[]).forEach(id=>{if(map.getLayer(id))map.setLayoutProperty(id,'visibility',o.visible?'visible':'none')}))}}
  if(in3d)draw3d()}
// in 3D a 2D overlay switched on (by the panel or the layer list) is only remembered (ov.visible), not drawn
document.addEventListener('rs:overlaychange',e=>{if(!in3d)return; const o=OVERLAYS.find(o=>o.label===e.detail.overlay);
  ((o&&o.layers)||[]).forEach(id=>{if(map.getLayer(id))map.setLayoutProperty(id,'visibility','none')})});
// in 3D: the mouse over a lane, a sidewalk or a street object lights it up (light purple) and names its type (a small tooltip, nothing
// more); a click selects it (deep purple); the two purples of 2D (roadstyle's hover_color, select_color; Kaveh, 2026-10-13: the yellow
// and orange were a construction site's and an intersection's colours) and opens its popup, the same fields as in 2D; a click on nothing clears the selection
let bound3d=false, hov3d=null, sel3d=null, hovT=0;     // hovered / selected: an object's refs or a part's part_id
const HOVER_MS=300;   // the mouse rests this long on a thing before it lights up and names itself (a passing mouse lights nothing)
const tip3d=new maplibregl.Popup({closeButton:false,closeOnClick:false,offset:12,className:'u3d-tip'}), OBJ_POPUP=__OBJPOPUP__;
// a popup for the selected thing (`who`: its refs or part_id); closing it deselects it
const pop3d=(e,p,fields,who)=>setTimeout(()=>{if(sel3d!==who)return;     // deselected meanwhile (a quick second click)
  document.querySelectorAll('.maplibregl-popup:not(.u3d-tip)').forEach(x=>x.remove());
  const pp=new maplibregl.Popup({closeButton:true,maxWidth:'320px'}).setLngLat(e.lngLat).setHTML('<table>'+
    fields.filter(k=>p[k]!==undefined&&p[k]!==null&&p[k]!=='').map(k=>`<tr><td><b>${k}</b></td><td>${p[k]}</td></tr>`).join('')+'</table>');
  pp.on('close',()=>{if(sel3d===who){sel3d=null; paint3d()}});    // (Popup.on does not return the popup: no chaining)
  pp.addTo(map)},0);
// (the Explore panel selects a thing as a click in 3D does: its part_id, ground_id, building or car park id; urbanstyle serve)
window.pick3d=(v,obj)=>{sel3d=v??null; selObj=!!obj; paint3d()};     // (obj: a street object: the buildings fade)
function deselect3d(){if(sel3d===null)return false; sel3d=null; paint3d();
  document.querySelectorAll('.maplibregl-popup:not(.u3d-tip)').forEach(x=>x.remove()); return true}
// layer -> [its colour property, the key of a feature, its own colour, its popup fields]
const L3D={'u3d-furn':['fill-extrusion-color','refs',['get','color'],OBJ_POPUP],
  'u3d-bld':['fill-extrusion-color','id','#ffffff',__BLDPOPUP__],     // (white, no dark base: Kaveh, 2026-10-13)
  'u3d-lot':['fill-color','id','#a8b0ba',__LOTPOPUP__],
  'u3d-gnd':['fill-color','ground_id',['get','color'],__GROUNDPOPUP__],
  'u3d-kerb':['fill-extrusion-color','kerb_id','#8f8b86',['type','unit_id','arm','length_m','source','method','ref']],
  'u3d-ground':['fill-color','part_id',['get','color'],null],'u3d-raised':['fill-extrusion-color','part_id',['get','color'],null]};
// (xpMarked: the Explore panel's results that are 3D things themselves, orange (Kaveh, 2026-10-13: the list apart from the one selected): in 3D they are not drawn a second time)
let xpMarked=[], xpFocus=null;
window.mark3d=ids=>{xpMarked=ids||[]; paint3d()};
// (one street space in focus, the Explore panel: its parts in their own colours, all else faint; Kaveh, 2026-10-13: "zooming to a
// section or an intersection was the first goal")
// (xpFocus: {unit, blds} for a street space, {parts, ground, blds, lots, objs} for a block: what keeps its colours; null: no focus)
window.focus3d=f=>{xpFocus=f||null; paint3d()};
// (a street object's key is refs, the ids of all its sources, "n64, vancouver-3": one source's id, as the Explore panel gives, finds it)
function paint3d(){Object.entries(L3D).forEach(([id,[prop,key,base]])=>{if(!map.getLayer(id))return;
  const is=key==='refs'?v=>['in',', '+v+', ',['concat',', ',['get','refs'],', ']]:v=>['==',['get',key],v];
  const marked=!xpMarked.length?false:key==='refs'?['any',...xpMarked.map(is)]:['in',['get',key],['literal',xpMarked]];
  // (in the space in focus its own colours win over the results' orange; outside it all is faint. A street object belongs to the space
  // it stands in, its `space`: Kaveh, 2026-10-13, "show all objects in that space too")
  const fk={'u3d-ground':'unit_id','u3d-raised':'unit_id','u3d-kerb':'unit_id','u3d-furn':'space'}[id];
  // (a focus: {units, parts, ground, blds, lots, objs}, any of them: a street space, a block, or a group from Browse)
  const F=xpFocus, lit=(k,vs)=>vs&&vs.length?['in',['get',k],['literal',vs]]:false, units=F?(F.units||(F.unit?[F.unit]:[])):[];
  let inF=false;
  if(F){if(id==='u3d-bld')inF=lit('id',F.blds); else if(id==='u3d-gnd')inF=lit('ground_id',F.ground); else if(id==='u3d-lot')inF=lit('id',F.lots);
    else{const a=[fk&&lit(fk,units),['u3d-ground','u3d-raised'].includes(id)&&lit('part_id',F.parts),
      id==='u3d-furn'&&(F.objs||[]).length&&['any',...F.objs.map(is)]].filter(Boolean); inF=a.length?['any',...a]:false}}
  // (crosswalks keep their colours in every focus, as the painted lines do: Kaveh, 2026-10-13)
  const always=['u3d-ground','u3d-raised'].includes(id)?['in',['get','type'],['literal',['crosswalk','cycle crossing']]]:false;
  map.setPaintProperty(id,prop,['case',is(sel3d||'\u0000'),'#7c4dff',is(hov3d||'\u0000'),'#b388ff',inF,base,marked,'#ff9100',always,base,
    !F?base:'#ebe8e3'])}); bldFade()}
// buildings fade by their opacity: out of a focus (white walls in a faint grey read as no change, Kaveh 2026-10-13), and all of them
// while a street object is selected (a building can stand between it and the camera). Those in focus, selected or lit stay whole: a
// second layer over the same buildings
// (the level's look from the panel: full, fade or off)
let selObj=false, bldG='full'; window.bldLook=g=>{bldG=g; bldFade()};
function bldFade(){const b=map.getLayer('u3d-bld'); if(!b)return; const fade=bldG==='fade'||!!xpFocus||(sel3d!==null&&selObj), on=in3d&&bldG!=='off';
  if(!map.getLayer('u3d-bld-on'))map.addLayer({id:'u3d-bld-on',type:'fill-extrusion',source:b.source,paint:{'fill-extrusion-opacity':0.92,
    'fill-extrusion-vertical-gradient':false,'fill-extrusion-height':['get','height_m'],'fill-extrusion-base':map.getPaintProperty('u3d-bld','fill-extrusion-base')}},map.getLayer('u3d-furn')?'u3d-furn':undefined);
  if(!U3D.includes('u3d-bld-on'))U3D.push('u3d-bld-on');     // (a 3D layer: setView hides it in 2D)
  const keep=['any',['in',['get','id'],['literal',(xpFocus&&xpFocus.blds)||[]]],['==',['get','id'],sel3d??'\u0000'],['==',['get','id'],hov3d??'\u0000']];
  map.setFilter('u3d-bld-on',['all',map.getFilter('u3d-bld')||true,keep]);
  map.setPaintProperty('u3d-bld-on','fill-extrusion-color',map.getPaintProperty('u3d-bld','fill-extrusion-color'));
  map.setLayoutProperty('u3d-bld','visibility',on?'visible':'none'); map.setLayoutProperty('u3d-bld-on','visibility',on&&fade?'visible':'none');
  map.setPaintProperty('u3d-bld','fill-extrusion-opacity',fade?0.25:0.92)}
function bind3d(){if(bound3d||!map.getLayer('u3d-furn'))return; bound3d=true;
  const groundPop=(OVERLAYS.find(o=>o.label==='Parts')||{}).popup||[];
  let took=0;     // the topmost layer under the mouse takes the click: an object before the ground under it
  Object.entries(L3D).forEach(([id,[prop,key,base,fields]])=>{
    map.on('mousemove',id,e=>{const f=e.features&&e.features[0]; if(!f||(window.brAt&&window.brAt(e.point)))return; map.getCanvas().style.cursor='pointer';
      const top=map.queryRenderedFeatures(e.point,{layers:Object.keys(L3D).filter(x=>map.getLayer(x))})[0];
      if(!top||top.layer.id!==id)return;
      const k=f.properties[key], ll=e.lngLat, t=f.properties.type;
      if(hov3d===k){tip3d.setLngLat(ll); return}                       // lit already: the tooltip follows the mouse
      if(hov3d!==null){hov3d=null; paint3d(); tip3d.remove()}          // another thing: the last one off at once
      clearTimeout(hovT); hovT=setTimeout(()=>{hov3d=k; paint3d(); tip3d.setLngLat(ll).setText(t).addTo(map)},HOVER_MS)});  // lit once the mouse rests
    map.on('mouseleave',id,()=>{clearTimeout(hovT); hov3d=null; map.getCanvas().style.cursor=''; paint3d(); tip3d.remove()});
    map.on('click',id,e=>{if(Date.now()-took<50||(window.brAt&&window.brAt(e.point)))return; took=Date.now(); const p=e.features[0].properties;
      if(sel3d===p[key]){deselect3d(); return}          // a click on the selected one deselects it
      if(window.xpOnPick&&window.xpOnPick(id,p,e))return;      // (the Explore panel selects it: its card and its short popup)
      if(window.brDeselect)window.brDeselect();       // (a bridge part selected before: off, its popup closed)
      sel3d=p[key]; selObj=id==='u3d-furn'; paint3d(); pop3d(e,p,fields||groundPop,p[key])})});
  map.on('click',e=>{if(!in3d)return; const hit=map.queryRenderedFeatures(e.point,{layers:Object.keys(L3D).filter(x=>map.getLayer(x))});
    if(!hit.length)deselect3d();
    svHere()})}       // 3D hides the road lines roadstyle's Street View follows: any click moves an open window to the nearest road
map.on('pitchend',()=>{setView(); apply()});   // the view follows the tilt: 3D's own layers, or 2D's
// Street View: roadstyle's window follows clicks on a road's centre line only; in a space most clicks land on its parts, lines or
// Mapillary points (overlays). While the window is open such a click moves it too: to the road nearest the spot, looking along it.
let downAt=null; map.on('mousedown',e=>downAt=e.lngLat); map.on('touchstart',e=>downAt=e.lngLat);
// the road nearest a spot, from the map's road data (the roads need not be drawn: the overview hides them), looking along it,
// and a bridge model's own roads (its axes, window.brAxes): the map's roads need not reach the bridge. {x, y, h (heading), d, name}
window.nearRoad=at=>{
  const src=map.getSource('roads'), data=src&&src.serialize&&src.serialize().data, lines=(window.brAxes||[]).slice();
  ((data&&data.features)||[]).forEach(f=>{const g=f.geometry; if(!g)return;
    (g.type==='LineString'?[g.coordinates]:g.type==='MultiLineString'?g.coordinates:[]).forEach(cs=>lines.push({cs,name:(f.properties||{}).name}))});
  const k=Math.cos(at.lat*Math.PI/180), X=at.lng*k, Y=at.lat;
  let best=null;
  lines.forEach(({cs,name})=>{
    for(let i=0;i<cs.length-1;i++){const ax=cs[i][0]*k, ay=cs[i][1], bx=cs[i+1][0]*k, by=cs[i+1][1], dx=bx-ax, dy=by-ay, L=dx*dx+dy*dy||1e-18;
      const t=Math.max(0,Math.min(1,((X-ax)*dx+(Y-ay)*dy)/L)), px=ax+t*dx, py=ay+t*dy, d=(X-px)**2+(Y-py)**2;
      if(!best||d<best.d)best={d,x:px/k,y:py,h:(Math.atan2(dx,dy)*180/Math.PI+360)%360,name}}});
  return best&&Math.sqrt(best.d)*111320<=40?best:null};      // (none within 40 m)
function svHere(name){const w=document.querySelector('.rs-svw'); if(!w||w.hidden||!downAt)return;
  const best=nearRoad(downAt); if(!best)return;
  if(window.rsSetStreetViewMarkerAt)rsSetStreetViewMarkerAt(best.x,best.y,best.h);
  const url=`https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${best.y.toFixed(6)},${best.x.toFixed(6)}&heading=${Math.round(best.h)}`;
  document.dispatchEvent(new CustomEvent('rs:select',{detail:{sv:true,properties:{name:best.name||'Street View'},streetView:url}}))}
document.addEventListener('rs:select',e=>{const d=e.detail||{}, p=d.properties||{};
  if(d.sv)return;                     // our own Street View move (svHere)
  if(d.overlay&&['Parts','Spaces','Mapillary','Cuts','Junction roads'].concat(MK.map(t=>'Mark: '+t)).includes(d.overlay))
    setTimeout(()=>svHere(p.arm||p.name||p.type||p.grp),0);
  // a click on a road inside a new space: the space under the click decides (roads cross every intersection, so the road would
  // otherwise always win and open its section)
  const under=!d.overlay&&(d.overlays||[]).find(o=>o.label==='Spaces');
  if(under){focusUnit(under.properties);return}
  if(d.overlay==='Cuts'&&p.intersection_id){focusUnit({unit_id:p.intersection_id,section_id:p.intersection_id});return}   // a cut opens its intersection
  if([...KD.map(k=>k.lab),'Travelway','Pedestrian realm','Track'].includes(d.overlay)&&p.cid&&!(sel.cids&&sel.cids.has(p.cid)))focusOn(p.cid);
  else if(!d.overlay&&p.container_id&&!(sel.cids&&sel.cids.has(p.container_id)))focusOn(p.container_id)   // a centerline click (Street View) focuses its street space too
  else if(['Spaces','Sections','Intersections','Subsections','Subsection axes','Subsection breaks'].includes(d.overlay))focusUnit(p)});
// a new space (work.unit) or a subsection line: focus its section (or its intersection); a section only the new division has: zoom to the space
function focusUnit(p){const id=[p.section_id,p.unit_id].find(x=>x&&byId[x]);
  if(id){if(!(sel.cids&&sel.cids.has(id)))focusOn(id);return}
  const ids=rsQuery(q=>q.unit_id===(p.unit_id||p.subsection_id),'Spaces'); if(ids.length)rsFocus(ids,{maxZoom:19},'Spaces')}
let maskReady=false, bmDim=false, labels0;   // bmDim: keep the basemap visible, dimmed, in focus
function setLabels(cs){if(!map.getLayer('roads-labels'))return; if(labels0===undefined)labels0=map.getFilter('roads-labels')||null;
  map.setFilter('roads-labels',cs?['all',...(labels0?[labels0]:[]),['in',['get','container_id'],['literal',[...cs]]]]:labels0)}   // street names: the focused container's only
let arrowsOff=false;   // one-way arrows cannot be limited to a container, so the focus view hides them; roadstyle re-shows them, hence the 'idle' check
function enforceArrows(){map.getStyle().layers.filter(l=>/^roads-arrows/.test(l.id)).forEach(l=>{
  if(map.getLayoutProperty(l.id,'visibility')!==(arrowsOff?'none':'visible'))map.setLayoutProperty(l.id,'visibility',arrowsOff?'none':'visible')})}
function hideEnds(){map.getStyle().layers.filter(l=>/^roads-ends/.test(l.id)).forEach(l=>{   // roadstyle's round end caps: a dot at the end of every centerline
  if(map.getLayoutProperty(l.id,'visibility')!=='none')map.setLayoutProperty(l.id,'visibility','none')})}
map.on('idle',()=>{hideEnds(); if(arrowsOff)enforceArrows()});
function setMask(on){
  if(!maskReady){const first=map.getStyle().layers.find(l=>/^(ov\d|roads-)/.test(l.id)); if(!first)return;
    map.addSource('focus-world',{type:'geojson',data:{type:'Feature',geometry:{type:'Polygon',coordinates:[[[-180,-85],[180,-85],[180,85],[-180,85],[-180,-85]]]}}});
    map.addLayer({id:'focus-mask',type:'fill',source:'focus-world',paint:{'fill-color':'#ffffff','fill-opacity':0.93},layout:{visibility:'none'}},first.id); maskReady=true}
  map.setLayoutProperty('focus-mask','visibility',on?'visible':'none');
  arrowsOff=on; enforceArrows();
  map.setPaintProperty('focus-mask','fill-opacity',bmDim?0.6:0.93)}   // the basemap's own arrows and labels would show through a light veil
map.setMaxZoom(24);
// in focus the objects are drawn as their real footprints (polygons, metres): one 'Objects' layer coloured by class
const OCOL=__OBJCOLORS__;
function paintObjects(){const ov=(window.RS_OVERLAYS||[]).find(x=>x.label==='Objects'); if(!ov)return;
  const m=['match',['get','class']]; Object.entries(OCOL).forEach(([k,v])=>m.push(k,v)); m.push('#888888');
  const base=['case',['==',['get','part'],'trunk'],'#78350f',m];
  ov.layers.forEach(id=>{const l=map.getLayer(id); if(!l||l.type!=='fill')return; const e=map.getPaintProperty(id,'fill-color');
    // roadstyle's colour is a 'case' on hover / select with the overlay colour last: swap only that last colour for ours
    if(Array.isArray(e)&&e[0]==='case'&&!Array.isArray(e[e.length-1])){const c=e.slice(); c[c.length-1]=base; map.setPaintProperty(id,'fill-color',c)}})}
map.on('idle',paintObjects);   // the basemap scales its last real tile level; our layers stay sharp
let tries=0;   // overlay data loads after the map's own load event: wait until it can be queried
// start once the data is in: the buildings and the roads (filtering the roads before they are loaded would hide them all)
(function start(){ if((rsQuery(()=>true,'Buildings').length===0||rsQuery(()=>true).length===0)&&tries++<100){setTimeout(start,200);return} apply(); fromHash() })();
// direct link: viz/<area>.html?c=<container id> (or #c=<container id>) focuses that container; ?c= survives link openers that drop the #
function fromHash(){
  // ?at=lon,lat,zoom,pitch,bearing opens the map there (the issue list's links: a pitch over 0 is the 3D view)
  const at=location.search.match(/[?&]at=([^&]+)/);
  if(at){const [x,y,z,p,b]=decodeURIComponent(at[1]).split(',').map(Number); map.jumpTo({center:[x,y],zoom:z||19,pitch:p||0,bearing:b||0});
    setView(); apply(); return}
  const m=location.hash.match(/^#c=(.+)$/)||location.search.match(/[?&]c=([^&]+)/); if(!m)return;
  const id=decodeURIComponent(m[1]); if(byId[id])return focusOn(id);
  // a new space (a subsection, an intersection) or one of its parts (<space>#<n>): the space in focus, then the part
  const go=()=>{focusUnit({unit_id:id.split('#')[0]});
    if(id.includes('#'))setTimeout(()=>{const ids=rsQuery(q=>q.part_id===id,'Parts'); if(ids.length)rsFocus(ids,{maxZoom:20},'Parts')},600)};
  if(map.loaded())go(); else map.once('idle',go)}
window.addEventListener('hashchange',fromHash);
</script>
"""


KINDS = [("section", "Old: sections", "#a78bfa", "#6d28d9"), ("intersection", "Old: intersections", "#fbbf24", "#b45309"),
         ("path", "Old: path spaces", "#6ee7b7", "#047857"), ("rail", "Old: rail spaces", "#f9a8d4", "#be185d"), ("plaza", "Old: plazas", "#f43f5e", "#9f1239")]   # kind, overlay label, fill, outline
POP = ["cid", "name", "kind", "shape", "level", "n_buildings", "width_m", "narrow_half_m", "wide_half_m", "open_share", "one_side_open", "kerb_share",
       "n_road", "n_walkway", "n_cycleway"]


def epsg_of(con):
    lon = con.execute("SELECT avg(ST_X(ST_Centroid(geometry))) FROM work.container").fetchone()[0]
    return f"EPSG:{32600 + int((lon + 180) // 6) + 1}"


# class -> (shape, size in metres, fill colour); shape: circle (radius), rect (length along the nearest road x width across), signal (pole + head),
# stripes (a zebra crossing). Sizes are the real ones, so the street reads like a plan drawing.
OBJ_SHAPES = {
    "vegetation.tree": ("circle", 2.0, "#86efac"), "furniture.lamp": ("circle", 0.3, "#f59e0b"), "furniture.signal": ("signal", 0.3, "#dc2626"),
    "furniture.sign": ("circle", 0.22, "#2563eb"), "furniture.bench": ("rect", (1.8, 0.5), "#a16207"), "furniture.waste": ("circle", 0.3, "#4b5563"),
    "furniture.bike_parking": ("rect", (1.8, 0.7), "#0891b2"), "furniture.shelter": ("rect", (3.0, 1.5), "#94a3b8"), "furniture.vending": ("rect", (0.8, 0.6), "#7c3aed"),
    "furniture.post_box": ("rect", (0.5, 0.4), "#b91c1c"), "furniture.water": ("circle", 0.3, "#38bdf8"), "furniture.charging": ("rect", (1.0, 0.5), "#16a34a"),
    "furniture.hydrant": ("circle", 0.25, "#ef4444"), "furniture.advertising": ("rect", (1.2, 0.3), "#ec4899"), "furniture.bollard": ("circle", 0.15, "#111827"),
    "transit.stop": ("circle", 0.4, "#2563eb"), "access.entrance": ("rect", (1.2, 0.35), "#db2777"), "access.parking_entrance": ("rect", (3.0, 0.5), "#be185d"),
    "kerb.node": ("circle", 0.15, "#6b7280"), "barrier.other": ("circle", 0.2, "#78350f"),
    "crossing.zebra": ("stripes", 0, "#ffffff"), "crossing.signalised": ("stripes", 0, "#ffffff"), "crossing.other": ("stripes", 0, "#f3f4f6")}


# street furniture that stands on the pavement: a point of it on the roadway or inside a building is moved out (Mapillary's are 1-5 m off)
SNAP = ("furniture.lamp", "furniture.sign", "furniture.signal", "furniture.waste", "furniture.bench", "furniture.post_box", "furniture.vending",
        "furniture.advertising", "furniture.bike_parking", "transit.stop", "vegetation.tree")
from urbanstyle.objects import NOT_OBJECTS, SEEN_CLASS, _fields, matched_objects  # noqa: E402,F401  (the street objects, one per real thing)
SIGN_COLOR = {"give way": "#dc2626", "stop": "#b91c1c", "parking": "#1d4ed8", "no parking": "#2563eb"}
KERB_BACK_M = 0.5     # a pole moved off the roadway stands this far behind the kerb
ALLEY_BACK_M = 0.3    # a pole moved out of an alley stands this far beside it
FACADE_SNAP_M = 3.0   # a point this far inside a building is at its facade (mapped a little off); deeper is indoors


# an object's popup and tooltip, the same in 2D and in 3D: the tooltip names its type, the popup says what it is and who knows it
DOT_COLORS = {"furniture": "#4f46e5", "vegetation": "#16a34a", "utility": "#6b7280", "transit": "#0891b2", "access": "#db2777", "barrier": "#78350f"}
# layer 0, the ground (work.ground): its kinds' colours; unknown in red, to be found
GROUND_COLORS = {k: KIND_COLORS[k] for k in ("street", "alley", "building", "yard", "car park", "construction site", "square", "rail", "plot", "green", "water", "path", "structure", "unknown")}
GROUND_POPUP = ["ground_id", "type", "name", "width_m", "width_method", "source", "method", "ref", "area_m2"]
# an alley's width: twice its area over its perimeter (a long strip's mean width; no source measures it)
ALLEY_W = ("CASE WHEN {t} = 'alley' THEN round(2 * ST_Area({g}) / ST_Perimeter({g}), 1) END AS width_m, "
           "CASE WHEN {t} = 'alley' THEN 'urbanstyle, derived: twice its area over its perimeter' END AS width_method")
LOT_POPUP = ["type", "name", "operator", "parking", "access", "fee", "id"]     # an off-street car park (work.lot), 2D and 3D
BLD_POPUP = ["type", "name", "use", "ground_floor", "evidence", "class", "floors", "height_m", "level_src", "source", "id"]     # a building's popup, the same in 2D and 3D
DOOR_WALL_M = 3.0   # an entrance this near a building's wall is a door in that wall (turned along it)
BR_POPUP = ["id", "type", "direction", "lane", "lane_id", "edge_id", "osm", "name", "use", "turn", "width_m", "width_source", "width_method",
            "source", "method", "landing", "axis", "section_m", "height", "connector", "from_lane", "to_lane", "marked"]   # a bridge item's 3D popup
DECK_EDGE_M = 0.5   # a street light on a bridge deck stands this far inside its edge (on the barrier)
DECK_NEAR_M = 1.0   # ... also one this near outside the edge
DECK_EDGE_CLS = ("furniture.lamp", "furniture.sign", "furniture.signal")   # (what stands at a deck's edge)
OBJ_POPUP, OBJ_TIP = ["type", "width_m", "height_m", "size_from", "details", "sources", "method", "refs", "space"], ["type"]
TYPE_NAME = {"crossing.zebra": "zebra crossing", "crossing.signalised": "signalised crossing", "crossing.other": "crossing", "kerb.node": "kerb",
             "transit.stop": "transit stop", "access.entrance": "entrance", "access.parking_entrance": "parking entrance", "barrier.other": "barrier",
             "utility.junction_box": "electrical box"}     # a street-lighting junction box: a lid in the pavement, not the junction area


def sign_kind(cls, details):
    """A sign's or a signal's type as people say it, from what its sources say (details: "osm: highway: stop | mapillary:
    regulatory--stop--g1; seen ..."): "stop sign", "no left turn sign"; any other class as type_of says."""
    import re
    t = type_of(cls)
    if cls not in ("furniture.sign", "furniture.signal") or not details:
        return t
    m = re.search(r"traffic_sign: ([^;|]+)", details) or re.search(r"highway: (stop|give_way)", details)
    if m:
        return f"{m.group(1).strip().replace('_', ' ')} {t}"
    m = re.search(r"(regulatory|warning|information|complementary)--([a-z0-9-]+?)--g\d", details)     # Mapillary's value
    return f"{m.group(2).replace('-', ' ')} {t}" if m else t


def type_of(cls):
    """A class as people say it: furniture.lamp -> lamp, utility.catch_basin -> catch basin, crossing.zebra -> zebra crossing."""
    return TYPE_NAME.get(cls, str(cls).split(".")[-1].replace("_", " "))


def placer(con, epsg):
    """place(point, level, cls) -> where a piece of street furniture stands: off the roadway (onto the nearest pavement, KERB_BACK_M behind
    the kerb) and out of the buildings (at the facade), else where it was mapped. Points in metres (epsg)."""
    import shapely
    from shapely.ops import nearest_points
    to_m = f"ST_AsWKB(ST_Transform(geometry, 'EPSG:4326', '{epsg}', always_xy := true))"
    road, walk, bld, pit = {}, {}, {}, {}
    try:
        for lv, t, w, ref in con.execute(f"SELECT level, type, {to_m}, ref FROM work.part").fetchall():
            (walk if t in RAISED else road).setdefault(lv, []).append(shapely.from_wkb(bytes(w)))
            if t == "tree pit":     # a street tree stands in the middle of its pit (parts.py placed both)
                pit.update({i: shapely.from_wkb(bytes(w)).centroid for i in (ref or "").split(", ") if i})
    except duckdb.CatalogException:
        pass
    for lv, w in con.execute(f"SELECT l, {to_m} FROM work.element, generate_series(level_min, level_max) t(l) WHERE type = 'building'").fetchall():
        bld.setdefault(lv, []).append(shapely.from_wkb(bytes(w)))
    alley = {}          # the alleys (work.ground): a pole mapped in one stands just beside it (city lamps stood in their middle)
    try:
        for lv, w in con.execute(f"SELECT level, {to_m} FROM work.ground WHERE type = 'alley'").fetchall():
            alley.setdefault(lv, []).append(shapely.from_wkb(bytes(w)))
    except duckdb.CatalogException:
        pass
    trees = {k: {lv: (shapely.STRtree(v), v) for lv, v in d.items()} for k, d in (("road", road), ("walk", walk), ("bld", bld), ("alley", alley))}

    def hit(kind, p, lv):
        t = trees[kind].get(lv)
        return [t[1][k] for k in t[0].query(p, predicate="within")] if t else []

    def place(p, lv, cls, refs=""):
        trunk = [pit[i] for i in (refs or "").split(", ") if i in pit]
        if cls == "vegetation.tree" and trunk:
            return trunk[0]
        if cls not in SNAP:
            return p
        for kind, gap, near in (("road", KERB_BACK_M, "walk"), ("alley", ALLEY_BACK_M, None), ("bld", 0.3, None)):
            inside = hit(kind, p, lv)
            if not inside:
                continue
            if near:            # onto the nearest pavement within 8 m
                t = trees["walk"].get(lv)
                cand = [t[1][k] for k in t[0].query(p.buffer(8))] if t else []
                if not cand:
                    return p
                q = nearest_points(shapely.union_all(cand), p)[0]
            else:               # out to the facade, if just inside it (deeper is indoors: it stays); out of an alley to its side
                q = nearest_points(inside[0].exterior, p)[0]
                if kind == "bld" and q.distance(p) > FACADE_SNAP_M:
                    return p
            dx, dy = q.x - p.x, q.y - p.y
            h = (dx * dx + dy * dy) ** 0.5 or 1.0
            return shapely.Point(q.x + dx / h * gap, q.y + dy / h * gap)
        return p
    return place


def bridge_decks(bridges, epsg, models=()):
    """Each bridge profile's deck (bridge3d.surface), in `epsg` metres; with the bridges' models, each deck's final outline (deck_ll):
    street lights stand at its edge (on the profile's first outline they stood in lanes and in the air, Kaveh, 2026-10-12)."""
    import shapely
    import shapely.geometry
    import shapely.ops
    from .bridge3d import surface
    out = []
    for i_, b in enumerate(bridges):
        P = json.load(open(b))
        if P["crs"] != epsg:            # the profile in the dashboard's metres
            import pyproj
            f = pyproj.Transformer.from_crs(P["crs"], epsg, always_xy=True).transform
            P = json.loads(json.dumps(P))
            P["deck"]["outline"]["value"] = [list(f(x, y)) for x, y in P["deck"]["outline"]["value"]]
            P["deck"]["outline"]["holes"] = [[list(f(x, y)) for x, y in h] for h in P["deck"]["outline"].get("holes") or []]
            for a in P["axes"]:
                a["line"]["value"] = [list(f(*q[:2])) for q in a["line"]["value"]]
        d_ = surface(P)
        if i_ < len(models) and models[i_].get("deck_ll"):
            import pyproj
            f_ = pyproj.Transformer.from_crs(4326, epsg, always_xy=True).transform
            d_["deck"] = shapely.ops.transform(f_, shapely.geometry.shape(models[i_]["deck_ll"]))
        out.append(d_)
    return out


def furniture_3d(con, epsg, place, objs, decks=()):
    """The 3D view's street furniture, each a few stacked blocks turned to its road: a street light (pole, arm over the road, lamp), a
    traffic light (pole, signal head), a sign (pole, plate in its colour), a tree (trunk, crown), a bench (seat, back), a bin, a bollard.
    one per real object (`objs`: matched_objects), where it stands (place). Polygons in lon/lat: base, height, colour, level, and the
    object they draw in OBJ_POPUP's fields (type, sources, refs: every source's id, space), the same as in 2D. `decks`: each bridge's
    deck (bridge3d.surface, in `epsg`): a pole or a sign that stands inside one stands on it, at its height (a city's survey gives no
    level: its lamps along a ramp's edges are on the ramp); a tree, a manhole or a drain stays on the ground under it."""
    import math
    import shapely
    from shapely.ops import transform
    import pyproj
    to_m = lambda col="geometry": f"ST_AsWKB(ST_Transform({col}, 'EPSG:4326', '{epsg}', always_xy := true))"
    roads = con.execute(f"SELECT level_min, {to_m()}, class FROM work.element WHERE type = 'road'").fetchall()
    rg = [shapely.from_wkb(bytes(r[1])) for r in roads]
    rtree = shapely.STRtree(rg)
    # the buildings' footprints: an entrance's door lies along the wall it is on (OSM maps it on the building's outline)
    # (only the area of a repaired outline: make_valid can give an area with lines, which has no wall; Monaco's r11384697)
    area_of = lambda g: shapely.union_all([q for q in shapely.get_parts(g) if q.geom_type in ("Polygon", "MultiPolygon")])
    bg = [area_of(shapely.make_valid(shapely.from_wkb(bytes(w)))) for (w,) in con.execute(
        f"SELECT {to_m()} FROM work.element WHERE type = 'building' AND level_min <= 0 AND level_max >= 0").fetchall()]
    btree = shapely.STRtree(bg) if bg else None
    units = con.execute(f"SELECT unit_id, level, {to_m()} FROM work.unit").fetchall()
    ug = [shapely.from_wkb(bytes(u[2])) for u in units]
    utree = shapely.STRtree(ug)
    out = []
    from urbanstyle.unit import SIZE
    sizes = {}      # refs -> (width, height, where they come from): what the popup shows is what is drawn
    for oid, cls, lv, grp, p, refs, sources, measured, details, methods, mwidth in objs:
        W0, H0 = SIZE.get(cls, (0.3, 1.0))
        W, H = (mwidth or (W0, None))[0], (measured or (H0, None))[0]
        sizes[refs] = (W, H, f"width {W:.2f} m: {mwidth[1] if mwidth else 'urbanstyle (chosen)'}; "
                             f"height {H:.2f} m: {measured[1] if measured else 'urbanstyle (chosen)'}")
        # on a deck: what no source puts at a level (a city's survey, Mapillary) and lies on one; what OSM maps keeps OSM's level (a stop
        # sign on West 7th Avenue's cycleway under ramp a2 went up onto the bridge)
        ground_ = cls.startswith(("utility.", "vegetation.")) or (sources.split(", ")[0] == "osm" and lv <= 0)
        on = None if ground_ else next((d for d in decks if d["deck"].contains(p)), None)
        if on is None and not ground_ and cls in DECK_EDGE_CLS:    # a street light (sign, signal) just outside a deck's edge: on its barrier
            on = next((d for d in decks if d["deck"].exterior.distance(p) < DECK_NEAR_M), None)
        if on is not None and cls in DECK_EDGE_CLS and (not on["deck"].contains(p) or on["deck"].exterior.distance(p) > DECK_EDGE_M):
            # a street light, a sign or a signal on a deck stands at its edge: a city's survey places a pole roughly (on Granville
            # Bridge's ramps two fell on the roadway, where the aerial photo shows them on the barrier) and OSM maps a stop sign on the
            # road's line (n12797102124, in the middle of the lane)
            q_ = on["deck"].exterior.interpolate(on["deck"].exterior.project(p))
            h_ = math.hypot(p.x - q_.x, p.y - q_.y) or 1
            k_ = 1 if on["deck"].contains(p) else -1            # (from outside: inwards)
            p = shapely.Point(q_.x + k_ * (p.x - q_.x) / h_ * DECK_EDGE_M, q_.y + k_ * (p.y - q_.y) / h_ * DECK_EDGE_M)
            sizes[refs] = (*sizes[refs][:2], sizes[refs][2] + "; position: moved to the deck's edge (urbanstyle, derived)")
        dz = on["z"](p.x, p.y) if on else 0.0
        if not cls.startswith("utility.") and not on:       # a manhole, a drain, a lid lies in the ground where it is mapped (a roadway too)
            p = place(p, lv, cls, refs)
        cand = [k for k in rtree.query(p.buffer(25)) if roads[k][0] == lv]
        ux, uy = 0.0, 1.0           # towards the road
        if on is not None:          # on a deck: towards the bridge's own nearest road (its axis), not a street on the ground
            ln_ = min((a_ for a_, _ in on["axes"]), key=lambda a_: a_.distance(p))
            q = ln_.interpolate(ln_.project(p))
            h = math.hypot(q.x - p.x, q.y - p.y)
            if h > 0.1:
                ux, uy = (q.x - p.x) / h, (q.y - p.y) / h
        elif cand:
            # (to the nearest street; to a service road, an alley, a driveway or a parking aisle, only with no street near: 40 of 492
            # lamps turned their backs to the street, to an alley behind them; Kaveh, 2026-10-13)
            st_ = [k for k in cand if roads[k][2] != "service"] or cand
            q = rg[min(st_, key=lambda k: rg[k].distance(p))].interpolate(rg[min(st_, key=lambda k: rg[k].distance(p))].project(p))
            h = math.hypot(q.x - p.x, q.y - p.y)
            if h > 0.1:
                ux, uy = (q.x - p.x) / h, (q.y - p.y) / h
        if cls.startswith("access.") and btree is not None:     # an entrance: along the wall of the building it is on, facing out of it
            near = [k for k in btree.query(p.buffer(DOOR_WALL_M)) if bg[k].boundary.distance(p) <= DOOR_WALL_M]
            if near:
                wall = bg[min(near, key=lambda k: bg[k].boundary.distance(p))].boundary
                wall = min(shapely.get_parts(wall), key=lambda w_: w_.distance(p))
                d_ = wall.project(p)
                a_, b_ = wall.interpolate(max(d_ - 0.5, 0)), wall.interpolate(min(d_ + 0.5, wall.length))
                h = math.hypot(b_.x - a_.x, b_.y - a_.y)
                if h > 0.1:
                    tx, ty = (b_.x - a_.x) / h, (b_.y - a_.y) / h
                    ux, uy = -ty, tx
                    on = wall.interpolate(d_)
                    if bg[min(near, key=lambda k: bg[k].boundary.distance(p))].contains(shapely.Point(on.x + ux * 0.3, on.y + uy * 0.3)):
                        ux, uy = -ux, -uy           # out of the building, not into it
        ax, ay = -uy, ux            # along the road (an entrance: along its wall)

        def blk(off, L, W, b, t, col, along=0.0):     # a block centred `off` m towards the road (and `along` it), L along it, W across
            cx, cy = p.x + ux * off + ax * along, p.y + uy * off + ay * along
            pts = [(cx + ax * a * L / 2 + ux * c * W / 2, cy + ay * a * L / 2 + uy * c * W / 2) for a, c in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
            out.append((shapely.Polygon(pts), b + dz, t + dz, col, cls, lv, refs, sources, None, details, methods))
        if cls == "furniture.lamp":             # pole W wide, H high; its arm and lamp over the road
            blk(0, W, W, 0, H, "#52525b"); blk(0.8, 0.12, 1.6, H - 0.25, H - 0.1, "#52525b"); blk(1.6, 0.35, 0.6, H - 0.55, H - 0.25, "#fde68a")
        elif cls == "furniture.signal":         # pole W wide; its signal head the top metre
            blk(0, W, W, 0, H - 1.0, "#3f3f46"); blk(0.12, 0.32, 0.28, H - 1.0, H, "#111827"); blk(0.27, 0.2, 0.04, H - 0.3, H - 0.1, "#ef4444")
        elif cls == "furniture.sign":           # a plate W wide at the top, on a post
            blk(0, 0.08, 0.08, 0, H - 0.6, "#9ca3af"); blk(0.05, W, 0.05, H - 0.65, H, SIGN_COLOR.get(grp, "#2563eb"))
        elif cls == "furniture.waste":         # a round bin W across, its rim darker
            out.append((p.buffer(W / 2, quad_segs=6), dz, H - 0.05 + dz, "#3f6212", cls, lv, refs, sources, None, details, methods))
            out.append((p.buffer(W / 2 + 0.02, quad_segs=6), H - 0.05 + dz, H + dz, "#1a2e05", cls, lv, refs, sources, None, details, methods))
        elif cls == "furniture.hydrant":       # a round red body W across, its cap and side nozzles
            out.append((p.buffer(W / 2, quad_segs=6), dz, H - 0.15 + dz, "#dc2626", cls, lv, refs, sources, None, details, methods))
            out.append((p.buffer(W / 2.6, quad_segs=6), H - 0.15 + dz, H + dz, "#991b1b", cls, lv, refs, sources, None, details, methods))
            blk(0, W * 1.6, 0.1, H * 0.55, H * 0.7, "#991b1b")
        elif cls == "furniture.bench":          # W long: seat, back, legs
            blk(0, W, 0.45, 0.4, 0.48, "#92400e"); blk(-0.2, W, 0.07, 0.48, H, "#92400e"); blk(0, 0.08, 0.4, 0, 0.4, "#44403c")
        elif cls == "furniture.bollard":
            blk(0, W, W, 0, H, "#374151")
        elif cls == "vegetation.tree":          # trunk W thick (a city's survey: the trunk's diameter); the crown from the height (derived)
            blk(0, W, W, 0, H * 0.35, "#78350f")
            R_ = max(1.2, H * 0.27)           # the crown in three layers, widest in the middle: it reads as a round crown (Kaveh, 2026-10-15)
            for r_, z0, z1, col in ((0.72, 0.35, 0.55, "#3f8a44"), (1.0, 0.55, 0.8, "#4d9a52"), (0.6, 0.8, 1.0, "#5aa85f")):
                out.append((p.buffer(R_ * r_, quad_segs=5), H * z0, H * z1, col, cls, lv, refs, sources, H, details, methods))
        elif cls == "utility.manhole":          # in the ground: a cover W across
            out.append((p.buffer(W / 2, quad_segs=6), 0, H, "#3f3f46", cls, lv, refs, sources, 0, details, methods))
        elif cls == "utility.catch_basin":      # a drain grate at the kerb, W along the road
            blk(0, W, 0.4, 0, H, "#27272a")
        elif cls == "utility.junction_box":     # a lid in the pavement
            blk(0, W, 0.3, 0, H, "#71717a")
        elif cls == "furniture.parking_meter":
            blk(0, 0.08, 0.08, 0, H - 0.35, "#6b7280"); blk(0, W, 0.16, H - 0.35, H, "#1f2937")
        elif cls == "furniture.map_stand":      # a wayfinding panel W wide
            blk(0, W, 0.15, 0, H, "#1e3a8a")
        elif cls == "furniture.bike_parking":   # a row of inverted-U stands W along the kerb, one each 0.8 m, each across it (a bike
            k_ = max(1, round(W / 0.8))           # parks along a stand): two posts and the bar between them, in steel
            for i_ in range(k_):
                a_ = (i_ - (k_ - 1) / 2) * 0.8
                blk(-0.3, 0.05, 0.05, 0, H, "#9ca3af", a_); blk(0.3, 0.05, 0.05, 0, H, "#9ca3af", a_)
                blk(0, 0.05, 0.65, H - 0.05, H, "#9ca3af", a_)
        elif cls == "access.entrance":          # a door in the facade
            blk(0, W, 0.2, 0, H, "#78350f")
        elif cls == "access.parking_entrance":  # a garage door
            blk(0, W, 0.2, 0, H, "#52525b")
        elif cls == "barrier.other":            # a short piece of wall or fence
            blk(0, W, 0.25, 0, H, "#6b7280")
        elif cls == "transit.stop":             # a pole with its plate W wide at the top
            blk(0, 0.1, 0.1, 0, H - 0.3, "#9ca3af"); blk(0.05, W, 0.05, H - 0.7, H, "#1d4ed8")
            if "shelter: yes" in (details or ""):      # its shelter (OSM shelter=yes), behind the pole, away from the road
                blk(-1.2, 3.0, 0.08, 0, 2.4, "#cbd5e1"); blk(-0.6, 3.2, 1.4, 2.4, 2.55, "#94a3b8")
        elif cls == "furniture.shelter":
            blk(0, W, 0.08, 0, H - 0.15, "#cbd5e1"); blk(0.6, W + 0.2, 1.6, H - 0.15, H, "#94a3b8")
        else:                                   # a post box, a vending machine, a hydrant, an advertising column, a charger, a fountain
            across = {"furniture.post_box": 0.4, "furniture.vending": 0.6, "furniture.hydrant": 0.3, "furniture.advertising": 0.3}.get(cls, 0.3)
            col = {"furniture.post_box": "#b91c1c", "furniture.vending": "#7c3aed", "furniture.hydrant": "#ef4444", "furniture.advertising": "#ec4899",
                   "furniture.charging": "#16a34a", "furniture.water": "#38bdf8"}.get(cls, "#9ca3af")
            blk(0, W, across, 0, H, col)
    back = pyproj.Transformer.from_crs(epsg, "EPSG:4326", always_xy=True).transform
    rows = []
    tops = {}                                   # an object's height: the top of its highest block
    for g, b, t, *_, refs, sources, top, details, methods in out:
        tops[refs] = max(tops.get(refs, 0), t)
    for g, b, t, col, cls, lv, refs, sources, top, details, methods in out:
        top = tops[refs]
        hits = [units[k][0] for k in utree.query(g.centroid) if units[k][1] == lv and ug[k].distance(g.centroid) < 0.5]
        W, H, size_from = sizes[refs]
        rows.append((cls, sign_kind(cls, details), b, t, col, lv, hits[0] if hits else "", refs, sources, methods, round(H, 2), round(W, 2), size_from, details,
                     transform(back, g)))
    return gpd.GeoDataFrame([r[:14] for r in rows], columns=["class", "type", "base", "height", "color", "level", "space", "refs", "sources",
                                                             "method", "height_m", "width_m", "size_from", "details"], geometry=[r[14] for r in rows], crs=4326)


def object_shapes(con, epsg, place=None):
    """One polygon (or several) per object at its real size, turned to run along the nearest road. Returns a GeoDataFrame in lon/lat."""
    import math
    import shapely
    from shapely import STRtree
    tr = f"ST_Transform(geometry, 'EPSG:4326', '{epsg}', always_xy := true)"
    roads = con.execute(f"SELECT level_min, coalesce(width_m, 6.5), ST_AsWKB({tr}) FROM work.element WHERE type = 'road'").fetchall()
    geoms = shapely.from_wkb([bytes(r[2]) for r in roads])
    tree = STRtree(geoms)
    rows = []
    for oid, cls, level, cid, w in con.execute(f"SELECT object_id, class, level, container_id, ST_AsWKB({tr}) FROM work.object").fetchall():
        shape, size, _ = OBJ_SHAPES.get(cls, ("circle", 0.25, "#888888"))
        p = shapely.from_wkb(bytes(w))
        if place is not None:
            p = place(p, level, cls, oid)
        cand = [k for k in tree.query(p.buffer(15)) if roads[k][0] == level]
        tx, ty, rw = 1.0, 0.0, 6.5
        toward = (0.0, 1.0)
        if cand:
            k = min(cand, key=lambda i: geoms[i].distance(p))
            line, rw = geoms[k], roads[k][1]
            d = line.project(p)
            a, b = line.interpolate(max(d - 1, 0)), line.interpolate(min(d + 1, line.length))
            h = math.hypot(b.x - a.x, b.y - a.y) or 1.0
            tx, ty = (b.x - a.x) / h, (b.y - a.y) / h
            c = line.interpolate(d)
            hh = math.hypot(c.x - p.x, c.y - p.y) or 1.0
            toward = ((c.x - p.x) / hh, (c.y - p.y) / hh)
        nx, ny = -ty, tx
        box = lambda cx, cy, L, W: shapely.Polygon([(cx - tx * L / 2 - nx * W / 2, cy - ty * L / 2 - ny * W / 2), (cx + tx * L / 2 - nx * W / 2, cy + ty * L / 2 - ny * W / 2),
                                                    (cx + tx * L / 2 + nx * W / 2, cy + ty * L / 2 + ny * W / 2), (cx - tx * L / 2 + nx * W / 2, cy - ty * L / 2 + ny * W / 2)])
        if shape == "circle":
            geom = p.buffer(size, quad_segs=4)
        elif shape == "rect":
            geom = box(p.x, p.y, *size)
        elif shape == "signal":   # a pole and its head on the road side
            geom = shapely.union(p.buffer(size, quad_segs=3), box(p.x + toward[0] * 0.55, p.y + toward[1] * 0.55, 0.5, 0.5))
        else:   # stripes 0.5 m wide every 1 m across the road, 3.2 m long along it, centred on the road
            c = p
            if cand:
                c = geoms[min(cand, key=lambda i: geoms[i].distance(p))].interpolate(geoms[min(cand, key=lambda i: geoms[i].distance(p))].project(p))
            length = min(max(rw + 1.0, 5.0), 24.0)
            geom = shapely.MultiPolygon([box(c.x + nx * (-length / 2 + 0.5 + i), c.y + ny * (-length / 2 + 0.5 + i), 3.2, 0.5) for i in range(int(length))])
        rows.append((oid, cls, cls.split(".")[0], level, cid, "", geom))
        if cls == "vegetation.tree":
            rows.append((oid, cls, "vegetation", level, cid, "trunk", p.buffer(0.2, quad_segs=3)))
    return gpd.GeoDataFrame(rows, columns=["object_id", "class", "grp", "level", "cid", "part", "geometry"], geometry="geometry", crs=epsg).to_crs(4326)


DOSSIER_COLORS = {"osm": "#2563eb", "mapillary": "#f59e0b", "vancouver": "#16a34a"}


def dossier_layers(con, db):
    """A unit's dossier (unit.py) next to its built neighbourhood (`<unit>.urban.duckdb` -> `<unit>.duckdb`): its objects
    from every source, each with all it knows (`info`: the source's own attributes), and the real objects they were matched into
    (`match`: one per object, with every source's id), to click on. Empty frames without a dossier."""
    path = db.replace(".urban.duckdb", ".duckdb")
    empty = gpd.GeoDataFrame({"source": []}, geometry=[], crs=4326)
    if path == db or not os.path.exists(path):
        return empty, empty
    con.execute(f"ATTACH IF NOT EXISTS '{path}' AS dos (READ_ONLY)")
    crs = con.execute("SELECT crs FROM dos.unit").fetchone()[0]
    ll = f"ST_AsWKB(ST_Transform(geometry, '{crs}', 'EPSG:4326', always_xy := true)) AS geometry"
    objs = frame(con, f"""SELECT object_id, class, source, method, confidence::DOUBLE AS confidence, height_m, sign, observed, attrs,
                          coalesce(match_id, '') AS match_id, {ll} FROM dos.object""")
    try:
        matches = frame(con, f"SELECT match_id, class, n_sources, sources, refs, height_m, confidence, {ll} FROM dos.match")
        matches["color"] = matches["n_sources"].map({1: "#9ca3af", 2: "#2563eb"}).fillna("#16a34a")   # more sources agree: bluer, greener
        matches["type"], matches["space"] = matches["class"].map(type_of), ""
    except duckdb.CatalogException:     # a dossier from before the matching
        matches = empty

    def info(a):    # the source's attributes, "key: value; ...", without the empty ones
        try:
            d = json.loads(a)
        except (TypeError, ValueError):
            return a or ""
        return "; ".join(f"{k}: {v}" for k, v in d.items() if v not in (None, "", "None") and k != "geo_point_2d") if isinstance(d, dict) else str(d)
    objs["info"] = objs.pop("attrs").map(info)
    return objs, matches


# a bridge as a 3D model (bridge3d.py) in a three.js layer on the map: its deck, parapets, piers, lanes and paths; a box on the map turns it
# on and off. Names start with br (the page's global scope is roadstyle's too)
BRIDGE_JS = """<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<label id=br3dbox style="position:absolute;right:10px;bottom:40px;z-index:5;background:#fff;padding:3px 8px;border-radius:4px;font:12px sans-serif;
  box-shadow:0 1px 3px #0003"><input type=checkbox id=br3don checked> bridges in 3D (__BRNAMES__)</label>
<script>fetch('bridge3d.json',{cache:'no-store'}).then(r=>r.json()).then(BR=>{const BC=__BRCOL__; window.brUnits=__BRUNITS__;   // brUnits: the old level-1 spaces the models replace (draw3d)
if(typeof draw3d==='function'&&document.body.classList.contains('u3d'))draw3d();   // (3D drawn before the list landed: again, without them)
window.brAxes=BR.flatMap(M=>M.axes.map(cs=>({cs,name:M.name})));     // the bridges' roads, for Street View (svHere)
const hex=c=>parseInt(c.slice(1),16);
function brLayer(M){const o=maplibregl.MercatorCoordinate.fromLngLat(M.origin,0), s=o.meterInMercatorCoordinateUnits();
  const T=new THREE.Matrix4().makeTranslation(o.x,o.y,o.z).scale(new THREE.Vector3(s,-s,s)); let renderer,scene,camera; const pick=[];
  const L={id:'br3d-'+M.name, type:'custom', renderingMode:'3d', pick,
    onAdd(map,gl){camera=new THREE.Camera(); scene=new THREE.Scene(); L.camera=camera; L.scene=scene;
      scene.add(new THREE.AmbientLight(0xffffff,0.7)); const d=new THREE.DirectionalLight(0xffffff,0.45); d.position.set(-0.5,-1,2); scene.add(d);
      const P=new THREE.BufferAttribute(new Float32Array(M.verts.flat()),3);
      const mesh=(faces,color)=>{const g=new THREE.BufferGeometry(); g.setAttribute('position',P); g.setIndex(faces.flat()); g.computeVertexNormals();
        scene.add(new THREE.Mesh(g,new THREE.MeshLambertMaterial({color:hex(color),side:THREE.DoubleSide})))};
      mesh(M.deck,BC.deck); mesh(M.sides,BC.girder); mesh(M.rails,BC.rail);
      // the surface, as the street: each part (or the model's own lane or path where the street has none) and each painted line on the
      // deck, in the street's colours; a part keeps its fields for the popup (paint shares one material per colour)
      // (a strong depth offset over the deck: seen from far, the depth buffer cannot tell 0.1 m apart and the deck showed through in teeth)
      const mats={}, paint=c=>mats[c]||(mats[c]=new THREE.MeshLambertMaterial({color:hex(c),side:THREE.DoubleSide,polygonOffset:true,polygonOffsetFactor:-4,polygonOffsetUnits:-16}));
      M.surf.forEach(sf=>{const g=new THREE.BufferGeometry(); g.setAttribute('position',new THREE.BufferAttribute(new Float32Array(sf.v.flat()),3));
        g.setIndex(sf.f.flat()); g.computeVertexNormals(); const c=BC.parts[sf.key]||BC.parts[sf.key.split(' ')[0]]||'#999999';
        const m=new THREE.Mesh(g,sf.props?new THREE.MeshLambertMaterial({color:hex(c),side:THREE.DoubleSide,polygonOffset:true,polygonOffsetFactor:-2,polygonOffsetUnits:-8}):paint(c));
        if(sf.props){m.userData=sf.props; m.baseHex=hex(c); pick.push(m)} if(/^(lane|mark)/.test(sf.key))m.isRoad=true; scene.add(m)});   // (a lane or its paint: a road; the rest goes with G)
      M.piers.forEach(q=>{const [ax,ay]=q.a,[bx,by]=q.b, m=new THREE.Mesh(new THREE.BoxGeometry(Math.hypot(bx-ax,by-ay),q.t,q.h),new THREE.MeshLambertMaterial({color:hex(BC.girder)}));
        m.position.set((ax+bx)/2,(ay+by)/2,q.h/2); m.rotation.z=Math.atan2(by-ay,bx-ax); scene.add(m)});
      // the steel truss under a span (bridge3d: truss): each member a box from a to b, in the photos' blue-grey, all one instanced mesh;
      // a member in a plane (n, its normal) longer than 3 m is a lattice, as in the photos: two thin flanges w apart and a zig-zag
      // lacing between them about every metre (Kaveh, 2026-10-12)
      const tm=[], put=(A,B,ty,tz,y)=>{const d=B.clone().sub(A), L=d.length(); if(L<0.05) return; d.divideScalar(L);
        const yy=(y?y.clone():new THREE.Vector3().crossVectors(d,Math.abs(d.z)<0.9?new THREE.Vector3(0,0,1):new THREE.Vector3(1,0,0))).normalize();
        tm.push(new THREE.Matrix4().makeBasis(d,yy,d.clone().cross(yy)).scale(new THREE.Vector3(L,ty,tz)).setPosition(A.clone().add(B).multiplyScalar(0.5)))};
      (M.truss||[]).forEach(q=>{const A=new THREE.Vector3(...q.a), B=new THREE.Vector3(...q.b), L=A.distanceTo(B);
        if(!q.n||L<=3) return put(A,B,q.w,q.w);
        const d=B.clone().sub(A).divideScalar(L), o=d.clone().cross(new THREE.Vector3(q.n[0],q.n[1],0)).normalize().multiplyScalar(q.w/2), m=Math.round(L);
        put(A.clone().add(o),B.clone().add(o),0.12,q.w,o); put(A.clone().sub(o),B.clone().sub(o),0.12,q.w,o);
        for(let i=0;i<m;i++) put(A.clone().addScaledVector(d,L*i/m).addScaledVector(o,i%2?-1:1),A.clone().addScaledVector(d,L*(i+1)/m).addScaledVector(o,i%2?1:-1),0.08,0.08)});
      const steel=new THREE.InstancedMesh(new THREE.BoxGeometry(1,1,1),new THREE.MeshLambertMaterial({color:hex(BC.truss||'#8b9aa5')}),tm.length);
      tm.forEach((m,i)=>steel.setMatrixAt(i,m)); scene.add(steel);
      scene.traverse(o=>{o.frustumCulled=false});   // the map's matrix is the camera: three.js's own culling dropped the parts far from the origin
      renderer=new THREE.WebGLRenderer({canvas:map.getCanvas(),context:gl,antialias:true}); renderer.autoClear=false},
    render(gl,args){const mm=args&&args.defaultProjectionData?args.defaultProjectionData.mainMatrix:args;
      camera.projectionMatrix=new THREE.Matrix4().fromArray(mm).multiply(T); renderer.resetState(); renderer.render(scene,camera)}};
  return L}
const LAYERS={}, ray=new THREE.Raycaster();
// the lane (or path) under a point of the map: a ray from the camera through it, in the model's own metres
function brHit(pt){const c=map.getCanvas(), x=pt.x/c.clientWidth*2-1, y=1-pt.y/c.clientHeight*2; let best=null;
  Object.values(LAYERS).forEach(L=>{if(!L.camera||!map.getLayer(L.id)||map.getLayoutProperty(L.id,'visibility')==='none')return;
    const inv=L.camera.projectionMatrix.clone().invert(), a=new THREE.Vector3(x,y,-1).applyMatrix4(inv), b=new THREE.Vector3(x,y,1).applyMatrix4(inv);
    ray.set(a,b.sub(a).normalize()); const h=ray.intersectObjects(L.pick)[0]; if(h&&(!best||h.distance<best.distance))best=h});
  return best&&best.object}
const brName=p=>p.part_id?`${p.type}${p.direction?' · '+p.direction:''} · ${p.part_id}`:p.type==='lane'?`lane ${p.lane} · ${p.direction} · ${p.name||p.osm}`:`${p.type} · ${p.name||p.osm}`;
// hover and selection as on the street (bind3d): a lane, a path or a crosswalk lights up light purple once the mouse rests on it HOVER_MS and
// names its type; a click selects it (deep purple) and opens its popup (BR_POPUP: its duckOSM edge_id and lane_id, OSM way, widths and their
// sources); a second click, a click on nothing, Esc or closing the popup deselects. The street under a bridge takes no hover or click
// there (window.brAt)
const BR_POPUP=__BRPOPUP__;
const brTip=new maplibregl.Popup({closeButton:false,closeOnClick:false,offset:12,className:'u3d-tip'}); let brLit=null, brSel=null, brPop=null, brT=0;
// (the Explore panel's results among the bridge's parts, by id, in orange: window.brMark, urbanstyle serve)
let brMarked=new Set();
function brPaint(){Object.values(LAYERS).forEach(L=>(L.pick||[]).forEach(m=>m.material.color.setHex(m===brSel?0x7c4dff:m===brLit?0xb388ff:
  brMarked.has(m.userData.id)?0xff9100:m.baseHex)));
  map.triggerRepaint()}
window.brMark=ids=>{brMarked=new Set(ids||[]); brPaint()};
// a street object under the mouse takes the hover and the click before the bridge: objects are small, the mouse on one means it
// (Kaveh, 2026-10-13: a lamp by the ramp could not be clicked, the bridge's lanes took every click)
const objAt=pt=>!!map.getLayer('u3d-furn')&&map.queryRenderedFeatures(pt,{layers:['u3d-furn']}).length>0;
window.brAt=pt=>brOn()&&!objAt(pt)&&!!brHit(pt);
let brQ=false, brLast=null;
map.on('mousemove',e=>{brLast=e; if(brQ)return; brQ=true; requestAnimationFrame(()=>{brQ=false; const m=brOn()&&!objAt(brLast.point)?brHit(brLast.point):null;
  if(m)map.getCanvas().style.cursor='pointer';
  if(m&&m===brLit){brTip.setLngLat(brLast.lngLat); return}                  // lit already: the tooltip follows the mouse
  clearTimeout(brT); if(brLit){brLit=null; brPaint(); brTip.remove()}       // another thing: the last one off at once
  if(m)brT=setTimeout(()=>{brLit=m; brPaint(); brTip.setLngLat(brLast.lngLat).setText(m.userData.type).addTo(map)},HOVER_MS)})});
const brDeselect=()=>{if(!brSel)return false; brSel=null; brPaint(); if(brPop){const p_=brPop; brPop=null; p_.remove()} return true};
window.brDeselect=brDeselect;
// (a level's look in 3D, the Explore panel: the bridge full, faded or hidden: 1, 0.25 or 0)
window.brOpacity=a=>{Object.values(LAYERS).forEach(L=>{if(!L.scene)return; L.scene.visible=a>0;
  L.scene.traverse(o=>{(Array.isArray(o.material)?o.material:o.material?[o.material]:[]).forEach(m=>{m.transparent=a<1; m.opacity=a;
    m.depthWrite=a>=1; m.needsUpdate=true})})}); map.triggerRepaint()};
// (G, the Explore panel's last level button: everything but the roads full, faded or hidden; here the slab, sides, parapets, piers,
// truss and paths, not the lanes and their paint; after brOpacity, which sets the level's look on the whole model)
window.brGLook=g=>{if(g==='full')return; Object.values(LAYERS).forEach(L=>{if(!L.scene)return; L.scene.traverse(o=>{if(!(o.isMesh||o.isInstancedMesh)||o.isRoad)return;
  o.visible=g!=='off'; (Array.isArray(o.material)?o.material:[o.material]).forEach(m=>{m.transparent=true; m.opacity=Math.min(m.opacity,0.15); m.depthWrite=false; m.needsUpdate=true})})});
  map.triggerRepaint()};
window.brPick=id=>{let hit=null; Object.values(LAYERS).forEach(L=>(L.pick||[]).forEach(m=>{if(m.userData.id===id)hit=m})); brSel=hit; brPaint(); return !!hit};
map.on('click',e=>{const m=brOn()&&!objAt(e.point)?brHit(e.point):null; if(!m||m===brSel){brDeselect(); return}
  if(window.xpOnPick&&window.xpOnPick('bridge',m.userData,e))return;      // (the Explore panel selects it)
  deselect3d(); brSel=m; brPaint(); if(brPop){const p_=brPop; brPop=null; p_.remove()}
  const p=m.userData, rows=BR_POPUP.filter(k=>p[k]!==undefined&&p[k]!==null&&p[k]!=='').map(k=>`<tr><td><b>${k}</b></td><td>${p[k]}</td></tr>`).join('');
  const pp=new maplibregl.Popup({closeButton:true,maxWidth:'320px'}).setLngLat(e.lngLat).setHTML('<table>'+rows+'</table>');
  pp.on('close',()=>{if(brPop===pp){brPop=null; brSel=null; brPaint()}}); brPop=pp; pp.addTo(map)});
document.addEventListener('keydown',e=>{if(e.key==='Escape')brDeselect()});
// (added again whenever the style is rebuilt: a basemap or a view switch drops custom layers)
// (in the 3D view only: in 2D the bridges are the flat "Bridge 2D" layer, every part with its id)
const brOn=()=>document.getElementById('br3don').checked&&(typeof in3d==='undefined'||in3d);
map.on('pitchend',()=>Object.keys(LAYERS).forEach(id=>{if(map.getLayer(id))map.setLayoutProperty(id,'visibility',brOn()?'visible':'none')}));
// the bridge stays the top layer: a flat layer drawn after it (the street, the ground) has no depth test and painted over it, and the page
// adds its layers after this one
const brAdd=()=>{if(!map.isStyleLoaded())return; BR.forEach(M=>{const id='br3d-'+M.name; if(!map.getLayer(id)){
  try{LAYERS[id]=brLayer(M); map.addLayer(LAYERS[id]); if(!brOn())map.setLayoutProperty(id,'visibility','none')}catch(e){console.error('bridge 3D:',e)}}
  const ord=map.style._order; if(ord[ord.length-1]!==id&&map.getLayer(id))map.moveLayer(id)})};
const brGo=()=>{if(typeof map==='undefined'||!map.isStyleLoaded||!map.isStyleLoaded()||typeof THREE==='undefined')return setTimeout(brGo,300);
  brAdd(); map.on('styledata',brAdd); map.on('idle',brAdd);
  document.getElementById('br3don').onchange=()=>{BR.forEach(M=>{if(map.getLayer('br3d-'+M.name))map.setLayoutProperty('br3d-'+M.name,'visibility',brOn()?'visible':'none')});
    window.brUnits=brOn()?__BRUNITS__:[]; if(typeof draw3d==='function'&&document.body.classList.contains('u3d'))draw3d()}};
brGo()}).catch(e=>console.error('bridge 3D: viz/bridge3d.json',e));</script>"""


def bridge_models(con, bridges, db=None):
    """Each bridge profile's 3D model with the street around it: (models, the level > 0 units they replace). The model is deck3d's: the
    street of the deck levels, made by network.py, at the profile's heights (docs/notes/bridges-street-model.md). URBANSTYLE_BRIDGE3D=old
    gives the old separate model (bridge3d.model) until deck3d passes on both test cuts."""
    if os.environ.get("URBANSTYLE_BRIDGE3D") == "structure":      # rank 0 only: the structure from one height surface (bridges-ranks.md)
        from .bridge_surface import models
        return models(con, bridges)
    if os.environ.get("URBANSTYLE_BRIDGE3D") != "old":
        from .deck3d import models
        return models(con, bridges)
    import shapely
    from .bridge3d import model
    ms, under = [], set()
    for b in bridges:
        P_ = json.load(open(b))
        from .bridge_profile import deck_polygon
        ol = deck_polygon(P_)
        to_crs = f"ST_Transform(geometry, 'EPSG:4326', '{P_['crs']}', always_xy := true)"
        # the street spaces above level 0 on this bridge: their parts and marks lie on the deck; their flat 3D drawing is hidden.
        # Those on the deck's outline, and those of the axes' own ways: a ramp runs on beyond OSM's deck outline, and its level-1
        # space was drawn as a flat deck over the model (Avenue de France, axis a8 and the ramps; Kaveh, 2026-10-16)
        ways = sorted({int(w[1:]) for a in P_.get("axes", []) for w in a.get("ways", [])})
        cids = [c_ for (c_,) in con.execute("SELECT DISTINCT container_id FROM work.element WHERE type = 'road' AND level_min > 0 "
                                            "AND osm_id IN (SELECT unnest(?::BIGINT[]))", [ways]).fetchall() if c_]
        us = [u for u, sec, w in con.execute(f"SELECT unit_id, section_id, ST_AsWKB({to_crs}) FROM work.unit WHERE level > 0").fetchall()
              if shapely.from_wkb(bytes(w)).intersects(ol) or sec in cids or any(u.startswith(c_ + "/") for c_ in cids)]
        under |= set(us)
        pf = ["part_id", "unit_id", "level", "type", "direction", "lane", "lane_id", "width_m", "road", "source", "method", "ref", "rule"]
        have = {r[0] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'work' AND table_name = 'part'").fetchall()}
        sel = ", ".join(c if c in have else f"NULL AS {c}" for c in pf)
        parts_ = [(dict(zip(pf, r[:-1])), shapely.from_wkb(bytes(r[-1]))) for r in con.execute(
            f"SELECT {sel}, ST_AsWKB({to_crs}) FROM work.part WHERE unit_id IN (SELECT unnest(?::VARCHAR[]))", [us]).fetchall()]
        marks_ = [(t, shapely.from_wkb(bytes(w))) for t, w in con.execute(
            f"SELECT type, ST_AsWKB({to_crs}) FROM work.mark WHERE unit_id IN (SELECT unnest(?::VARCHAR[]))", [us]).fetchall()]
        # the street's lanes at level 0 near the bridge: a bridge lane that lands on one meets it exactly
        ground_ = [shapely.from_wkb(bytes(w)) for (w,) in con.execute(
            f"SELECT ST_AsWKB({to_crs}) FROM work.part WHERE level = 0 AND type = 'lane'").fetchall()]
        ground_ = [g for g in ground_ if g.distance(ol) < 50]
        # (the level-1 parts are not laid on the deck: parts.py makes them from rules OSM does not support there, e.g. a "no parking"
        # strip from parking:both=no, a sidewalk OSM says is not there; the model's lanes and paths follow GMNS and OSM)
        ms.append(_cached_model(P_, ground_, bridge_poles(con, P_['crs'], ol, db)))
    return ms, under


def bridge_poles(con, crs, outline, db=None, near=50.0):
    """The street's surveyed poles near a bridge (a city's lamps and poles, OSM's; not Mapillary alone: its positions are too rough),
    [(x, y)] in the bridge profile's crs: its lanes keep clear of them (bridge3d.POLE_CLEAR_M)."""
    import pyproj
    import shapely
    ep = epsg_of(con)
    to = pyproj.Transformer.from_crs(ep, crs, always_xy=True).transform
    out = []
    for oid, cls, lv, grp, p, refs, sources, *_ in matched_objects(con, ep, db or ""):
        if not str(cls).startswith(("furniture.lamp", "furniture.pole", "furniture.traffic_signal", "furniture.sign")):
            continue
        if set(s_.strip() for s_ in str(sources).split(",")) <= {"mapillary"}:
            continue
        x, y = to(p.x, p.y)
        if shapely.Point(x, y).distance(outline) < near:
            out.append((round(x, 2), round(y, 2)))
    return sorted(out)


def _cached_model(P_, ground_, poles_=()):
    """bridge3d.model(P_) with the street's lanes ground_, from data/cache/ when nothing it reads has changed since: the profile, those
    lanes, the corrections and the model's code (bridge3d.py and the modules it reads). A change to the page only needs no new model
    (Kaveh, 2026-10-13: four minutes for each small change)."""
    import glob
    import hashlib
    import pickle
    import shapely
    from .bridge3d import model
    here = os.path.dirname(os.path.abspath(__file__))
    h = hashlib.sha1(json.dumps(P_, sort_keys=True).encode())
    for g in ground_:
        h.update(shapely.to_wkb(g))
    h.update(json.dumps(list(poles_)).encode())
    # (the model's own code only: a change to the page, the server or the CLI needs no new model)
    for f in [os.path.join(here, m) for m in ("bridge3d.py", "bridge_profile.py", "corrections.py", "parts.py")] + \
            sorted(glob.glob(os.path.join(here, "..", "..", "corrections", "*.json"))):
        h.update(open(f, "rb").read())
    path = os.path.join(here, "..", "..", "data", "cache", f"bridge3d-{h.hexdigest()[:16]}.pkl")
    if os.path.exists(path):
        return pickle.load(open(path, "rb"))
    m = model(P_, None, None, ground_, poles=list(poles_))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pickle.dump(m, open(path, "wb"))
    return m


def write_bridge3d(ms, out):
    """The bridges' models as the page draws them, to `out` (viz/bridge3d.json): the page reads this file when it opens, so a change to
    a bridge only needs this file written again (`urbanstyle bridge3d`), not the whole page."""
    page_ms = [{k: v for k, v in mm.items() if k not in ("lanes", "lines", "flat")} for mm in ms]     # (the page draws `surf`)
    tmp = out + ".tmp"
    with open(tmp, "w") as f:
        json.dump(page_ms, f, separators=(",", ":"))
    os.replace(tmp, out)
    return out


def main(db, out, bridges=None):
    con = duckdb.connect(db, read_only=True)
    con.execute("LOAD spatial")
    edges = frame(con, """SELECT ST_AsWKB(geometry) AS geometry, class AS highway, name, level_min AS level, type, container_id,
        CASE WHEN level_src = 'bridge' THEN 'yes' END AS bridge, CASE WHEN level_src = 'tunnel' THEN 'yes' END AS tunnel,
        level_min AS layer, try_cast(source_id AS BIGINT) AS edge_id, coalesce(oneway, false) AS oneway, round(width_m, 2) AS width_m, width_src
        FROM work.element WHERE type <> 'building'""")
    edges["edge_id"] = edges["edge_id"].astype("Int64")
    buildings = frame(con, """SELECT ST_AsWKB(geometry) AS geometry, source_id AS id, source, name, class, level_min, level_max, level_src,
        CASE WHEN coalesce(class, 'yes') = 'yes' THEN 'building' ELSE 'building (' || class || ')' END AS type,
        -- its real size (work.element floors, height_m: before levels are clamped to LEVELS), else one floor
        coalesce(floors, greatest(level_max, 0) + 1) AS floors, coalesce(height_m, round((greatest(level_max, 0) + 1) * 3.2, 1)) AS height_m,
        -- what it is used for, its ground floor, each with its source and method (buildings.py), and the evidence
        "use" || ' (' || use_source || ', ' || use_method || ')' AS "use", ground_use || ' (' || ground_source || ', ' || ground_method || ')' AS ground_floor,
        uses AS evidence FROM work.element WHERE type = 'building'""")
    try:    # layer 0: every piece of the area, by kind
        gm_ = f"ST_Transform(geometry, 'EPSG:4326', '{epsg_of(con)}', always_xy := true)"
        ground = frame(con, f"""SELECT ST_AsWKB(geometry) AS geometry, ground_id, type, name, source, method, ref, level,
            round(ST_Area({gm_}), 1) AS area_m2, {ALLEY_W.format(t='type', g=gm_)} FROM work.ground""")
        ground["color"] = ground["type"].map(GROUND_COLORS).fillna("#9ca3af")
    except duckdb.CatalogException:     # built before the ground layer
        ground = None
    blocks = blocks_frame(con)     # the land between the streets
    try:    # off-street car parks: beside the street, not in it
        lots = frame(con, """SELECT ST_AsWKB(geometry) AS geometry, lot_id AS id, type, name, operator, parking, access, fee, level FROM work.lot""")
    except duckdb.CatalogException:     # built before car parks were lots
        lots = buildings.iloc[:0]
    zones = frame(con, """SELECT ST_AsWKB(z.geometry) AS geometry, z.level, z.zone, z.container_id AS cid, c.name
        FROM work.zone z JOIN work.container c USING (container_id)""")
    streets = frame(con, """SELECT ST_AsWKB(geometry) AS geometry, container_id AS cid, name, level, round(mean_width_m, 1) AS width_m,
        round(open_share, 2) AS open_share, round(narrow_half_m, 1) AS narrow_half_m, round(wide_half_m, 1) AS wide_half_m,
        round(one_side_open_share, 2) AS one_side_open, round(kerb_share, 2) AS kerb_share, n_road, n_walkway, n_cycleway, kind, shape, n_buildings FROM work.container""")
    kinds = [(k, lab, c) for k, lab, c, _ in KINDS if (streets.kind == k).any()]   # the kinds present in this area
    rails = frame(con, "SELECT ST_AsWKB(geometry) AS geometry, source_id AS id, name, class, level_min AS level FROM work.element WHERE type = 'rail'")
    stations = frame(con, "SELECT ST_AsWKB(geometry) AS geometry, id, name, kind, level FROM work.station")
    objects = frame(con, """SELECT ST_AsWKB(geometry) AS geometry, object_id, class, split_part(class, '.', 1) AS grp, level, container_id AS cid, zone,
        name, attrs::VARCHAR AS attrs, near_m FROM work.object""")
    try:
        strips = frame(con, """SELECT ST_AsWKB(geometry) AS geometry, container_id AS cid, level, type, coalesce(side, '') AS side, round(width_m, 1) AS width_m, source FROM work.strip""")
    except duckdb.CatalogException:
        strips = pd.DataFrame({"type": []})
    # type, name shown, fill, outline: asphalt, green cycle lane, tan sidewalk bands
    sdefs = [d for d in (("travel", "Travel lane", "#5b6472", "#3f4753"), ("cycle", "Cycle lane", "#2e9d5b", "#1f6f40"), ("sidewalk", "Sidewalk", "#e6d5c3", "#cdb79f"),
                         ("furnishing", "Furnishing (kerb side)", "#c9a27e", "#a8835f"), ("frontage", "Frontage (building side)", "#b08968", "#8f6c4e"),
                         ("open", "Open ground", "#efe9dc", "#d8d0bd"), ("plaza", "Plaza", "#f4a6b4", "#d97c8f"), ("track", "Track", "#e879f9", "#a21caf"))
             if (strips["type"] == d[0]).any()]
    place = placer(con, epsg_of(con))
    shapes = object_shapes(con, epsg_of(con), place)
    try:
        mobjs = matched_objects(con, epsg_of(con), db)
        ms_early = bridge_models(con, bridges, db) if bridges else ([], set())
        furn = furniture_3d(con, epsg_of(con), place, mobjs, bridge_decks(bridges or [], epsg_of(con), ms_early[0]))
        # 2D: one dot per real object, where its model stands (its smallest block: the pole, the trunk, the cover), coloured by kind
        dots = furn.assign(a=furn.to_crs(epsg_of(con)).area).sort_values("a").drop_duplicates("refs").drop(columns=["a"])
        dots = dots.set_geometry(dots.to_crs(epsg_of(con)).centroid.to_crs(4326))
        dots["color"] = dots["class"].str.split(".").str[0].map(DOT_COLORS).fillna("#6b7280")
    except Exception as e:      # the 3D view goes without street furniture rather than the page failing
        print("no 3D street furniture:", e)
        furn, mobjs = gpd.GeoDataFrame({"class": []}, geometry=[], crs=4326), []
        dots = furn
    # every object's popup says where it comes from and which real object it is: all the sources that know it and their ids
    real = {r: (o[5], o[6]) for o in mobjs for r in o[5].split(", ")}
    def provenance(df, key, source, types, space="unit"):     # OBJ_POPUP's fields: type, the real object's sources and ids, its space
        df["type"] = list(types)
        df["sources"] = [real.get(str(k), ("", source))[1] for k in df[key]]
        df["refs"] = [real.get(str(k), (str(k), ""))[0] for k in df[key]]
        df["space"] = df[space].fillna("") if space in df else ""
    provenance(objects, "object_id", "osm", map(type_of, objects["class"]))
    provenance(shapes, "object_id", "osm", map(type_of, shapes["class"]))

    ogroups = []        # objects are one layer now ("Street objects", every source matched), not a layer per OSM group
    lon = con.execute("SELECT avg(ST_X(ST_Centroid(geometry))) FROM work.container").fetchone()[0]
    epsg = f"EPSG:{32600 + int((lon + 180) // 6) + 1}"   # the metric zone, as in urbanstyle.build
    track = zones[zones.zone == "track"]
    try:
        subs = frame(con, """SELECT ST_AsWKB(geometry) AS geometry, subsection_id, section_id, level, class, width_m, oneway, length_m, "left", "right",
            starts_at, color FROM work.subsection""")
        brk = frame(con, """SELECT ST_AsWKB(ST_StartPoint(geometry)) AS geometry, subsection_id, section_id, level, starts_at FROM work.subsection
            WHERE starts_at <> 'section end'""")
        units = frame(con, f"""SELECT ST_AsWKB(geometry) AS geometry, unit_id, kind, section_id, level, color,
            round(ST_Area(ST_Transform(geometry, 'EPSG:4326', '{epsg_of(con)}', always_xy := true)))::INT AS area_m2 FROM work.unit""")
        cuts = frame(con, """SELECT ST_AsWKB(geometry) AS geometry, intersection_id, edge_id, level, how, length_m,
            CASE how WHEN 'block corners' THEN '#16a34a' WHEN 'one corner' THEN '#f59e0b' WHEN 'crosswalk' THEN '#2563eb' ELSE '#6b7280' END AS color FROM work.cut""")
        ep = epsg_of(con)
        jroads = frame(con, """SELECT ST_AsWKB(ST_CollectionExtract(ST_Intersection(e.geometry, u.geometry), 2)) AS geometry, u.unit_id, e.level_min AS level,
            e.name, e.class FROM work.element e JOIN work.unit u ON u.kind IN ('intersection', 'roundabout') AND u.level = e.level_min AND ST_Intersects(e.geometry, u.geometry)
            WHERE e.type = 'road'""")
        jroads = jroads[~jroads.geometry.is_empty]
        try:    # the inside of each space (parts.py): parts, marks, widths
            pcols = {r[0] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'work' AND table_name = 'part'").fetchall()}
            holds = ", ".join(c if c in pcols else f"NULL AS {c}" for c in ("holds", "rule", "width_source", "width_method", "position_source",
                                                                            "position_method", "position_ref", "lane_id"))     # (newer columns)
            length = "length_m" if "length_m" in pcols else "NULL AS length_m"
            pts_ = frame(con, f"""SELECT ST_AsWKB(geometry) AS geometry, unit_id, part_id, level, type, coalesce(arm, '') AS arm,
                coalesce(direction, '') AS direction, lane, width_m, {length}, source, method, ref, road, road_class, speed, surface, lit, road_lanes, oneway,
                {holds}, round(ST_Area(ST_Transform(geometry, 'EPSG:4326', '{ep}', always_xy := true)), 1) AS area_m2 FROM work.part ORDER BY level""")   # upper levels drawn last
            pts_["color"] = [PART_COLORS.get(f"{t} {d}".strip(), PART_COLORS.get(t, "#999999")) for t, d in zip(pts_["type"], pts_["direction"])]
            marks = frame(con, "SELECT ST_AsWKB(geometry) AS geometry, unit_id, level, type, coalesce(arm, '') AS arm, length_m, width_m, width_source, width_method, source, method, ref FROM work.mark ORDER BY level")
            kerbs3d = marks[marks["type"] == "kerb"].copy()     # 3D's kerbstones: each kerb line as a strip 0.25 m wide
            kerbs3d = kerbs3d.set_geometry(kerbs3d.to_crs(ep).buffer(LINE["kerb"] / 2, cap_style="flat").to_crs(4326))
            kerbs3d["kerb_id"] = [f"kerb-{k}" for k in range(len(kerbs3d))]
            uwidths = con.execute("SELECT unit_id, edge, arm, total_m, carriageway_m, left_m, right_m, lanes_in, lanes_out, source FROM work.width").fetchall()
        except duckdb.CatalogException:
            pts_, marks, uwidths = pd.DataFrame({"type": []}), pd.DataFrame({"type": []}), []
            kerbs3d = gpd.GeoDataFrame({"type": []}, geometry=[], crs=4326)
        unit_of = dict(con.execute("""SELECT o.object_id, min(u.unit_id) FROM work.object o JOIN work.unit u ON u.level = o.level
            AND ST_Intersects(u.geometry, o.geometry) GROUP BY 1""").fetchall())
        ubld = con.execute(f"""SELECT u.unit_id, b.source_id, round(ST_Length(ST_Intersection(ST_Boundary(ST_Transform(u.geometry, 'EPSG:4326', '{ep}', always_xy := true)),
              ST_Buffer(ST_Transform(b.geometry, 'EPSG:4326', '{ep}', always_xy := true), 1.0))), 1) AS m
            FROM work.unit u JOIN work.element b ON b.type = 'building' AND b.level_min <= u.level AND b.level_max >= u.level
              AND ST_Intersects(ST_Buffer(u.geometry, 0.00002), b.geometry) WHERE u.kind IN ('intersection', 'roundabout')""").fetchall()
        ubounds = {r[0]: [round(x, 7) for x in r[1:]] for r in con.execute(
            "SELECT unit_id, ST_XMin(geometry), ST_YMin(geometry), ST_XMax(geometry), ST_YMax(geometry) FROM work.unit WHERE kind IN ('intersection', 'roundabout')").fetchall()}
    except duckdb.CatalogException:
        subs = brk = units = cuts = jroads = pd.DataFrame()
        pts_, marks, uwidths = pd.DataFrame({"type": []}), pd.DataFrame({"type": []}), []
        kerbs3d = gpd.GeoDataFrame({"type": []}, geometry=[], crs=4326)
        unit_of, ubld, ubounds = {}, [], {}
    try:        # Mapillary (mapillary.py): what its photos saw, and the photos nearest each space (CC BY-SA, © Mapillary contributors)
        seen = frame(con, """SELECT ST_AsWKB(any_value(o.geometry)) AS geometry, o.feature_id, any_value(o.class) AS class, any_value(o.grp) AS grp,
            any_value(o.last_seen)::DATE::VARCHAR AS last_seen, coalesce(min(u.unit_id), '') AS unit,
            coalesce(min(u.level) FILTER (WHERE u.level = 0), min(u.level), 0) AS level FROM work.observed o
            LEFT JOIN work.unit u ON ST_Intersects(u.geometry, ST_Buffer(o.geometry, 0.00003)) GROUP BY o.feature_id""")
        # every detection, for validation (hidden until "Mapillary detections" is ticked): Mapillary makes no object (unit.CONFIRM_ONLY);
        # a detection confirms the object of a surveyed or mapped source it matched, else nothing confirms it
        from urbanstyle.unit import MATCH_M
        conf = {r: (o[1], o[5].split(", ")[0]) for o in mobjs for r in o[5].split(", ")}
        seen["status"] = [f"confirms {type_of(conf[str(f)][0])} {conf[str(f)][1]}" if str(f) in conf else
                          f"not confirmed: no surveyed or mapped {type_of(SEEN_CLASS.get(g, g))} within {MATCH_M:.0f} m"
                          for f, g in zip(seen["feature_id"], seen["grp"])]
        seen["color"] = ["#16a34a" if t.startswith("confirms") else "#f97316" for t in seen["status"]]
        provenance(seen, "feature_id", "mapillary", [type_of(SEEN_CLASS.get(g, g)) for g in seen["grp"]])
        import pyproj
        fwd, back = (pyproj.Transformer.from_crs(a, b, always_xy=True).transform for a, b in (("EPSG:4326", epsg_of(con)), (epsg_of(con), "EPSG:4326")))
        from shapely.ops import transform as _tf
        seen["geometry"] = [_tf(back, place(_tf(fwd, g), lv, SEEN_CLASS.get(grp, ""))) for g, lv, grp in zip(seen.geometry, seen["level"], seen["grp"])]   # where it stands
        photos = {}
        for uid, pid, when, pano in con.execute("""SELECT u.unit_id, p.photo_id, p.captured::DATE::VARCHAR, p.is_pano FROM work.unit u
                JOIN work.photo p ON ST_Intersects(u.geometry, p.geometry) ORDER BY u.unit_id, p.captured DESC""").fetchall():
            if len(photos.setdefault(uid, [])) < PHOTOS_PER_SPACE:
                photos[uid].append([pid, when, bool(pano)])
    except duckdb.CatalogException:
        seen, photos = pd.DataFrame({"grp": []}), {}
    dobjs, dmatch = dossier_layers(con, db)
    shapes["unit"] = shapes["object_id"].map(unit_of)
    objects["unit"] = objects["object_id"].map(unit_of)
    has = [lab for lab, df in (("Track", track), ("Rail", rails), ("Station", stations), ("Spaces", units), ("Parts", pts_), ("Cuts", cuts), ("Junction roads", jroads), ("Subsection axes", subs),
                               ("Subsection breaks", brk), ("Street objects", dots), ("Mapillary", seen)) if len(df)]   # overlays present in this area
    links = frame(con, "SELECT ST_AsWKB(geometry) AS geometry, node_id, level_a, level_b, type, assumed, station_id, match, round(dist_m) AS dist_m FROM work.link")
    # type, name shown, colour, what it is. Colours differ from every other layer's on purpose.
    defs = [("ramp", "Ramp", "#f59e0b", "a bridge or tunnel is involved"), ("stairs", "Stairs", "#0f172a", "steps join two levels"),
            ("elevator", "Elevator", "#06b6d4", "a lift"), ("entrance", "Station entrance", "#ef4444", "tied to its station (by name, else the nearest); level -1 is assumed only when no station is found"),
            ("connection", "Other level change", "#ec4899", "ways on different layers meet, no ramp, stairs or lift tagged")]
    defs = [d for d in defs if (links["type"] == d[0]).any()]
    o = lambda g, **kw: rs.Overlay(g, placement="under", **kw)
    try:
        ms, under = ms_early
    except NameError:
        ms, under = bridge_models(con, bridges, db) if bridges else ([], set())
    # the bridges in 2D (Kaveh, 2026-10-12: "a 2D version of the bridge, everything with an id"): every part of each model, flat, with its id
    bridge2d = gpd.GeoDataFrame([{**{k: (v if isinstance(v, (str, int, float)) or v is None else str(v)) for k, v in pr.items()},
                                  "color": PART_COLORS.get(key) or PART_COLORS.get(key.split(" ")[0]) or {"barrier median": "#cfc8bd", "median": "#6b7280",
                                  "buffer": "#c4b5a0"}.get(key, "#9ca3af"), "geometry": g} for mm in ms for pr, key, g in mm["flat"]],
                                geometry="geometry", crs=4326) if ms else None
    m = rs.render_edges(
        edges, palette="mono", basemap="voyager", name="urbanstyle", filter_control=False,   # no road-class filter window
        street_view_key=os.environ.get("GOOGLE_MAPS_KEY"),
        settings={"config": {"fill_opacity": 0.35, "casing_opacity": 0.2}}, road_popup=["edge_id", "container_id", "name", "type", "highway", "level", "width_m", "width_src"],   # Street View's linked panorama (the key is written into the page: restrict it in Google Cloud)
        color_options={"Roads": {"color_by": "type", "colors": {"road": "#555", "walkway": "#a16207", "cycleway": "#16a34a"}}},
        overlays=([rs.Overlay(bridge2d, placement="over", color="#9ca3af", color_col="color", opacity=0.95, outline="#334155", width=0.6,
                              label="Bridge 2D", popup=BR_POPUP, tooltip=["id", "type"])] if bridge2d is not None and len(bridge2d) else []) +
                 ([o(ground, color=GROUND_COLORS["plot"], color_col="color", opacity=0.55, outline="#94a3b8", width=0.5, label="Ground", popup=GROUND_POPUP,
                     tooltip=["type", "name"])] if ground is not None and len(ground) else []) +
                 ([rs.Overlay(block_colors(blocks), placement="over", color=BLOCK_COLOR, color_col="color", opacity=0.45, outline="#5b3410", width=2.0, label="Blocks", visible=False,
                              popup=BLOCK_POPUP, tooltip=["block_id"])] if blocks is not None and len(blocks) else []) +
                 [o(streets[streets.kind == k], color=c, opacity=0.8, outline=dark, width=1.2, label=lab, popup=POP, tooltip=["cid", "name"])
                  for k, lab, c, dark in KINDS if (streets.kind == k).any()] + [
                  o(zones[zones.zone == "pedestrian_realm"], color="#f8c4b4", opacity=0.9, outline="#e8a898", label="Pedestrian realm",
                    popup=["cid", "name", "level", "zone"], tooltip=["cid", "zone"]),
                  o(zones[zones.zone == "travelway"], color="#6b7280", opacity=0.9, outline="#4b5563", label="Travelway",
                    popup=["cid", "name", "level", "zone"], tooltip=["cid", "zone"]),
                  o(buildings, color="#3b82f6", opacity=0.85, outline="#334", label="Buildings",
                    popup=BLD_POPUP, tooltip=["type"])]
                 + [o(lots, color="#a8b0ba", opacity=0.9, outline="#64748b", label="Parking lots", popup=LOT_POPUP, tooltip=["type"])] * (len(lots) > 0)
                 + [o(track, color="#f0abfc", opacity=0.7, outline="#c026d3", label="Track", popup=["cid", "name", "level", "zone"],
                      tooltip=["cid", "zone"])] * (len(track) > 0)
                 + [o(strips[strips["type"] == t], color=c, opacity=0.97, outline=dark, width=0.4, label=f"Strip: {t}", popup=["cid", "type", "side", "width_m", "source", "level"],
                      tooltip=["cid", "type"]) for t, lab, c, dark in sdefs]
                 + [rs.Overlay(rails, kind="line", placement="over", color="#c026d3", width=3, label="Rail", popup=["id", "name", "class", "level"],
                               tooltip=["id", "name"])] * (len(rails) > 0)
                 + [rs.Overlay(stations, kind="circle", placement="over", color="#0d9488", radius=9, label="Station",
                               popup=["id", "name", "kind", "level"], tooltip=["id", "name"])] * (len(stations) > 0)
                 + [rs.Overlay(links[links["type"] == t], kind="circle", placement="over", color=c, radius=6, label=f"Link: {name}",
                               popup=["node_id", "type", "level_a", "level_b", "assumed", "station_id", "match", "dist_m"], tooltip=["node_id", "type"]) for t, name, c, _ in defs]
                 # (blocks, sections and intersections cover the area; a section is its subsections, each a space: Kaveh, 2026-10-13)
                 + ([o(units[units.kind == "subsection"].dissolve(by=["section_id", "level"], as_index=False)[["section_id", "level", "geometry"]],
                       color="#a78bfa", opacity=0.35, outline="#4c1d95", width=2.2, label="Sections", popup=["section_id", "level"], tooltip=["section_id"]),
                     o(units[units.kind != "subsection"], color="#fbbf24", opacity=0.45, outline="#b45309", width=2.2, label="Intersections",
                       popup=["unit_id", "kind", "level", "area_m2"], tooltip=["unit_id", "kind"]),
                     o(units[units.kind == "subsection"], color="#a78bfa", color_col="color", opacity=0.25, outline="#6d28d9", width=0.8,
                       label="Subsections", popup=["unit_id", "section_id", "level", "area_m2"], tooltip=["unit_id"])] if len(units) else [])
                 + [o(units, color="#a78bfa", color_col="color", opacity=0.45, outline="#1f2937", width=1.2, label="Spaces",
                      popup=["unit_id", "kind", "section_id", "level"], tooltip=["unit_id", "kind"])] * (len(units) > 0)
                 + [o(pts_, color="#999999", color_col="color", opacity=0.95, outline="#475569", width=0, label="Parts", visible=False,
                      popup=["part_id", "type", "holds", "rule", "road", "road_class", "direction", "lane", "lane_id", "width_m", "length_m", "speed", "surface", "lit", "road_lanes", "oneway",
                              "area_m2", "source", "method", "ref", "width_source", "width_method", "position_source", "position_method", "position_ref"],
                      tooltip=["type", "direction", "arm"])] * (len(pts_) > 0)
                 + [o(pts_[pts_["type"].isin(ON_PARTS)], color="#f97316", color_col="color", opacity=0.85, outline="#7c2d12", width=0.8,
                      label="On the parts", visible=False, popup=["part_id", "type", "rule", "unit_id", "source", "method", "ref"],
                      tooltip=["type"])] * bool(len(pts_) and pts_["type"].isin(ON_PARTS).any())
                 + [rs.Overlay(marks[marks["type"] == t], kind="line", placement="over", color=c, width_m=w, dash=dash, label=f"Mark: {t}", visible=False,
                               popup=["unit_id", "type", "arm", "length_m", "width_m", "width_source", "width_method", "source", "method", "ref"], tooltip=["type", "arm"]) for t, c, w, dash in MARKS if (marks["type"] == t).any()]
                 # the street objects, one per real object, from the same data in both views: in 2D a dot where it stands, coloured by kind;
                 # in 3D (draw3d) its model, from the blocks below (never drawn in 2D)
                 + [rs.Overlay(dots, kind="circle", placement="over", color="#4f46e5", color_col="color", radius=4, label="Street objects",
                               popup=OBJ_POPUP, tooltip=OBJ_TIP)] * (len(dots) > 0)
                 + [rs.Overlay(seen, kind="circle", placement="over", color="#f97316", color_col="color", radius=4, label="Mapillary", visible=False,
                               popup=["type", "status", "last_seen", "feature_id", "space"], tooltip=["type"])] * (len(seen) > 0)
                 + [o(furn, color="#71717a", color_col="color", opacity=0, width=0, label="Street objects 3D", visible=False,
                      popup=OBJ_POPUP, tooltip=OBJ_TIP)] * (len(furn) > 0)
                 + [o(kerbs3d, color="#cfcac2", opacity=0, width=0, label="Kerbs 3D", visible=False,
                      popup=["type", "unit_id", "arm", "length_m"], tooltip=["type"])] * (len(kerbs3d) > 0)      # drawn only by 3D (draw3d)
                 + [rs.Overlay(jroads, kind="line", placement="over", color="#374151", width=7, label="Junction roads", visible=False,
                               popup=["unit_id", "name", "class"], tooltip=["name", "class"])] * (len(jroads) > 0)
                 + [rs.Overlay(cuts, kind="line", placement="over", color="#6b7280", color_col="color", width=4, label="Cuts",
                               popup=["intersection_id", "edge_id", "how", "length_m"], tooltip=["how", "length_m"])] * (len(cuts) > 0)
                 + [rs.Overlay(subs, kind="line", placement="over", color="#e6194b", color_col="color", width=5, label="Subsection axes",
                               popup=["subsection_id", "section_id", "class", "width_m", "oneway", "length_m", "left", "right", "starts_at"],
                               tooltip=["subsection_id", "length_m"])] * (len(subs) > 0)
                 + [rs.Overlay(brk, kind="circle", placement="over", color="#111827", radius=5, label="Subsection breaks",
                               popup=["subsection_id", "starts_at"], tooltip=["subsection_id", "starts_at"])] * (len(brk) > 0)
                 + [rs.Overlay(dobjs[dobjs.source == s], kind="circle", placement="over", color=DOSSIER_COLORS.get(s, "#6b7280"), radius=6,
                               label=f"Dossier objects: {s}", visible=len(dmatch) == 0,
                               popup=["object_id", "class", "source", "method", "confidence", "height_m", "sign", "observed", "match_id", "info"],
                               tooltip=["class", "source"]) for s in sorted(set(dobjs.source))]
)
    newu = {"inter": {}, "sec": {}, "photos": photos}
    if len(units):
        ua = dict(zip(units.unit_id, units.area_m2))
        for iid, how, ln in zip(cuts.intersection_id, cuts.how, cuts.length_m):
            newu["inter"].setdefault(iid, {"a": int(ua.get(iid, 0)), "cuts": []})["cuts"].append([how, float(ln)])
        for iid, kd in zip(units.unit_id, units.kind):
            if kd in ("intersection", "roundabout"):
                newu["inter"].setdefault(iid, {"a": int(ua[iid]), "cuts": []})["rb"] = kd == "roundabout"
        for iid, bid, along in ubld:                  # the buildings that bound it, and how much of its edge runs along them
            if iid in newu["inter"] and along and along >= 1.0:
                newu["inter"][iid].setdefault("bb", []).append([bid, float(along)])
        for oid, iid in unit_of.items():               # what stands inside it, by class
            if iid in newu["inter"]:
                cls = objects.loc[objects.object_id == oid, "class"]
                if len(cls):
                    ob = newu["inter"][iid].setdefault("ob", {}); ob[cls.iloc[0]] = ob.get(cls.iloc[0], 0) + 1
        for iid, b in ubounds.items():
            if iid in newu["inter"]:
                newu["inter"][iid]["b"] = b
        for iid, sid in con.execute("""SELECT DISTINCT c.intersection_id, s.unit_id FROM work.cut c JOIN work.unit s ON s.kind = 'subsection' AND s.level = c.level
                AND ST_Intersects(ST_Buffer(c.geometry, 0.00001), s.geometry)""").fetchall():
            if iid in newu["inter"]:          # the roads arriving at it: the subsections beyond its cuts (not every space that touches it)
                newu["inter"][iid].setdefault("adj", []).append(sid)
        ways = {}           # (intersection, arm edge) -> its in lanes, rightmost first, and the ways each may go (SUMO's turns, work.turn)
        try:
            for uid, edge, lane, turn in con.execute("SELECT DISTINCT unit_id, from_edge, from_lane, turn FROM work.turn WHERE vehicles IS NULL ORDER BY 1, 2, 3").fetchall():
                ways.setdefault((uid, edge), {}).setdefault(lane, set()).add(turn)
        except duckdb.CatalogException:
            pass
        sym = {"left": "\u21b0", "straight": "\u2191", "right": "\u21b1"}
        for uid, edge, arm, tot, cw, lw, rw, li, lo, src in uwidths:     # edges and their widths
            tgt = newu["inter"].get(uid) if uid.startswith("i") else newu.setdefault("subw", {})
            row = [arm or "", tot, cw, lw, rw, li, lo, src,
                   " ".join("".join(sym[t] for t in ("left", "straight", "right") if t in w) for _, w in sorted(ways.get((uid, edge), {}).items()))]
            if uid.startswith("i") and tgt is not None:
                tgt.setdefault("w", []).append(row)
            elif not uid.startswith("i"):
                tgt[uid] = row
        if len(pts_):                                                     # the area of each kind of part, per unit
            for uid, typ, d, a in zip(pts_.unit_id, pts_["type"], pts_.direction, pts_.area_m2):
                pa = newu.setdefault("parts", {}).setdefault(uid, {})
                key = f"{typ} {d}".strip()
                pa[key] = round(pa.get(key, 0) + float(a), 1)
        for r in subs.assign(k=subs.subsection_id.str.split("/").str[-1].astype(int)).sort_values(["section_id", "k"]).itertuples():
            if r.subsection_id in ua:
                newu["sec"].setdefault(r.section_id, []).append([r.subsection_id, int(ua[r.subsection_id]), float(r.length_m), r.left, r.right, r.color])
    panel = (PANEL.replace("__PCOL__", json.dumps(PART_COLORS)).replace("__RAISED__", json.dumps(RAISED)).replace("__KERBTOP__", json.dumps(KERB_TOP_M)).replace("__OBJPOPUP__", json.dumps(OBJ_POPUP)).replace("__BLDPOPUP__", json.dumps(BLD_POPUP)).replace("__LOTPOPUP__", json.dumps(LOT_POPUP)).replace("__GROUNDPOPUP__", json.dumps(GROUND_POPUP)).replace("__NEWU__", json.dumps(newu)).replace("__MARKS__", json.dumps([t for t, *_ in MARKS if len(marks) and (marks["type"] == t).any()])).replace("__TREE__", json.dumps(tree_data(con, epsg)).replace("</", "<\\/"))
             .replace("__LEVELS__", json.dumps(list(range(LEVELS[0], LEVELS[1] + 1)))).replace("__LINKDEF__", json.dumps([{"t": t, "lab": n, "c": c, "d": d} for t, n, c, d in defs]))
             .replace("__KINDS__", json.dumps([{"k": k, "lab": lab, "c": c} for k, lab, c in kinds])).replace("__OBJDEF__", json.dumps([{"g": g, "c": c} for g, c in ogroups])).replace("__OBJCOLORS__", json.dumps({k: v[2] for k, v in OBJ_SHAPES.items()})).replace("__STRIPS__", json.dumps([{"t": t, "lab": lab, "c": c} for t, lab, c, _ in sdefs])).replace("__HAS__", json.dumps(has)).replace("__LEVELBTNS__", "".join(f'<button data-l="{l}">{l}</button>' for l in range(LEVELS[0], LEVELS[1] + 1))))
    if bridges:     # [bridge profile]: each as a 3D model (bridge3d.py), its surface drawn as the street
        under = sorted(under)
        col = {"deck": "#a8a29e", "girder": "#8f8b86", "rail": "#cfc8bd",      # the deck: bare concrete, not a lane's colour (it looked like lanes)
               "parts": {**PART_COLORS, **{f"mark {t}": c for t, c, *_ in MARKS}, "mark kerb": "#8f8b86", "barrier": "#cfc8bd", "railing": "#6b7280"}}
        write_bridge3d(ms, os.path.join(os.path.dirname(os.path.abspath(out)), "bridge3d.json"))     # (the page reads it, beside it)
        panel += (BRIDGE_JS.replace("__BRNAMES__", ", ".join(mm["name"] for mm in ms))
                  .replace("__BRCOL__", json.dumps(col)).replace("__BRPOPUP__", json.dumps(BR_POPUP)).replace("__BRUNITS__", json.dumps(under)))
    open(out, "w").write(m.html.replace("</body>", panel + "</body>"))



# the layers page (docs/design/space-layers.md): layer 0 the ground, layer 1 the surfaces, each alone, with the hierarchy in the popups
LAYER_COLORS = {0: GROUND_COLORS, 1: KIND_COLORS}
LAYER_LABELS = {0: "Layer 0: ground", 1: "Layer 1: surfaces", 2: "Blocks", 3: "Street spaces", 4: "Layer 2: parts"}
LAYER_ORDER = [(2, "1 · blocks"), (3, "2 · sections, intersections"), (0, "3 · layer 0 · ground"), (1, "4 · layer 1 · surfaces"),
               (4, "5 · layer 2 · parts")]     # the order to check them in: each stands on the one before
SPACE_PALETTE = ["#93c5fd", "#a5b4fc", "#99f6e4", "#bae6fd", "#c7d2fe", "#a7f3d0", "#bfdbfe", "#ddd6fe"]
LAYERS_PANEL = """
<style>.ov-ctrl{display:none!important}
#ly{position:fixed;top:10px;left:10px;z-index:6;width:340px;max-height:calc(100vh - 40px);overflow:auto;background:#fff;border:1px solid #cbd5e1;
  border-radius:8px;padding:10px 12px;font:13px system-ui;box-shadow:0 2px 8px #0002}#ly h3{margin:0 0 4px;font-size:14px}
#ly ul{list-style:none;margin:0;padding-left:18px}#ly>div>ul{padding-left:0}#ly li{margin:3px 0}
#ly .tw{display:inline-block;width:14px;cursor:pointer;color:#475569;user-select:none}#ly .tw.no{cursor:default}
#ly .sw{display:inline-block;width:11px;height:11px;border:1px solid #64748b;margin:0 5px 0 3px;vertical-align:-1px}
#ly .n{color:#64748b;font-size:11px;margin-left:4px}#ly input{margin:0 2px 0 0;vertical-align:-2px}#ly .lay{font-weight:700}#ly .br{font-weight:600}
#ly .only{font-size:11px;margin-left:6px;color:#1e3a8a;cursor:pointer;visibility:hidden}#ly li>div:hover>.only{visibility:visible}
#ly .note{color:#64748b;font-size:11px;margin:1px 0 4px 32px}#ly p{margin:0 0 6px;color:#64748b;font-size:11px}.lytip .maplibregl-popup-content{padding:3px 7px;font:12px system-ui}</style>
<div id=ly><h3>urbanstyle · layers</h3><p>Each layer divides the one above it. Tick a layer to draw it; tick the next to draw it on top
(the layers under it stay drawn beneath, their edges as dark lines: untick a kind and the layer under it shows). ▸ opens a layer to see what is in it, without drawing anything; "only" draws that one alone.</p>
<div id=lytree></div><div id=lyhere style="margin-top:8px;padding-top:6px;border-top:1px solid #e2e8f0;font-size:12px;color:#334155"></div>
<div id=lysel style="margin-top:6px;padding-top:6px;border-top:1px solid #e2e8f0;font-size:12px;color:#0f172a;display:none">
<b>clicked</b> <button id=lycopy style="font-size:11px;margin-left:6px;cursor:pointer">copy</button>
<pre id=lyseltext style="white-space:pre-wrap;user-select:text;font:12px ui-monospace,monospace;margin:4px 0 0;background:#f8fafc;padding:4px;border-radius:4px"></pre></div></div>
<script>
(function(){const T=__LYTREE__;
const on=new Set(), open=new Set(['0']);       // the leaves drawn ("overlay|value"); the nodes opened
const leaves=n=>n.leaf?[n]:(n.children||[]).flatMap(leaves), key=x=>x.ov+'|'+x.val;
const orig={};      // each overlay's own fill opacity and outline, to restore when it is the top layer again
function layersOf(ov){return map.getStyle().layers.filter(x=>x.source===(OVERLAYS.find(o=>o.label===ov)||{}).source)}
function apply(){if(typeof light==='function')light(null); const drawn=T.map((t,i)=>leaves(t).some(x=>on.has(key(x)))?i:-1).filter(i=>i>=0), top=Math.max(-1,...drawn);
  T.forEach((t,i)=>{const ovs=[...new Set(leaves(t).map(x=>x.ov))];
    ovs.forEach(ov=>{const vis=drawn.includes(i); rsSetOverlay(ov,vis); if(!vis)return;
      const vals=new Set(leaves(t).filter(x=>x.ov===ov&&on.has(key(x))).map(x=>x.val));
      rsFilter(rsQuery(p=>vals.has(String(p.node)),ov),ov);       // a layer's ticks apply to that layer only
      layersOf(ov).forEach(L=>{if(!(L.id in orig))orig[L.id]=L.type==='fill'?map.getPaintProperty(L.id,'fill-opacity'):
                                 [map.getPaintProperty(L.id,'line-color'),map.getPaintProperty(L.id,'line-width')];
        if(L.type==='fill')map.setPaintProperty(L.id,'fill-opacity',orig[L.id]);     // every ticked layer stays filled: a hidden kind shows the layer under it
        if(L.type==='line'){map.setPaintProperty(L.id,'line-color',i===top?orig[L.id][0]:t.edge);
          map.setPaintProperty(L.id,'line-width',i===top?orig[L.id][1]:2.4-0.5*i); if(i!==top)map.moveLayer(L.id)}})})})}
function draw(){const box=document.getElementById('lytree'); box.innerHTML=''; const root=document.createElement('ul'); box.append(root);
  const node=(n,ul,id,depth)=>{const li=document.createElement('li'), row=document.createElement('div'), ls=leaves(n), lsOn=n.leaf?ls:ls.filter(x=>!x.off),
      all=lsOn.length>0&&lsOn.every(x=>on.has(key(x))), some=ls.some(x=>on.has(key(x)));
    const tw=document.createElement('span'); tw.className='tw'+(n.children?'':' no'); tw.textContent=n.children?(open.has(id)?'▾':'▸'):'';
    tw.onclick=()=>{if(!n.children)return; open.has(id)?open.delete(id):open.add(id); draw()};
    const cb=document.createElement('input'); cb.type='checkbox'; cb.checked=all; cb.indeterminate=some&&!all;
    cb.onchange=()=>{ls.forEach(x=>cb.checked?(n.leaf||!x.off)&&on.add(key(x)):on.delete(key(x))); draw(); apply()};
    const lab=document.createElement('span'); lab.className=depth===0?'lay':n.children?'br':'';
    lab.innerHTML=(n.c?`<span class=sw style="background:${n.c}"></span>`:' ')+n.label+(n.n!=null?`<span class=n>${n.n} · ${n.a.toLocaleString()} m²</span>`:'');
    if(n.children)lab.style.cursor='pointer', lab.onclick=tw.onclick;
    const only=document.createElement('span'); only.className='only'; only.textContent='only';
    only.onclick=()=>{on.clear(); lsOn.forEach(x=>on.add(key(x))); draw(); apply()};
    row.append(tw,cb,lab,only); li.append(row); ul.append(li);
    if(depth===0&&n.note&&open.has(id)){const d=document.createElement('div'); d.className='note'; d.textContent=n.note; li.append(d)}
    if(n.children&&open.has(id)){const u=document.createElement('ul'); n.children.forEach((c,j)=>node(c,u,id+'.'+j,depth+1)); li.append(u)}};
  T.forEach((t,i)=>node(t,root,String(i),0))}
// what is under the mouse in every layer drawn, from the top layer down (a block under its plots, a subsection under its lanes)
const ID=['part_id','surface_id','unit_id','ground_id','block_id','street_id','kind'], what=p=>{const i=ID.find(k=>p[k]!=null); return (p.type||p.kind||'')+(i&&i!=='kind'?' '+p[i]:'')};
const SKIP=new Set(['node','p0','p1','p2','color','_rsid','geometry']);
function at(point,full){const src={}; OVERLAYS.forEach(o=>src[o.source]=o.label); const seen={};
  map.queryRenderedFeatures(point).forEach(f=>{const lab=src[f.source]; if(!lab||seen[lab]||f.layer.id.startsWith('lyhl')||map.getLayoutProperty(f.layer.id,'visibility')==='none')return;
    seen[lab]=full?what(f.properties)+'\\n'+Object.entries(f.properties).filter(([k,v])=>!SKIP.has(k)&&v!==null&&v!=='').map(([k,v])=>`   ${k}: ${v}`).join('\\n'):what(f.properties)});
  return T.map((t,i)=>[i,[...new Set(leaves(t).map(x=>x.ov))].filter(ov=>seen[ov]).map(ov=>seen[ov])]).filter(r=>r[1].length).reverse()}
// the top item under the mouse (the highest layer drawn there): its outline lit, its name in a label; a click opens its popup
const lyOf={}; T.forEach((t,i)=>leaves(t).forEach(x=>lyOf[x.ov]=i));
function top(point){const src={}; OVERLAYS.forEach(o=>src[o.source]=o.label); let best=null;
  map.queryRenderedFeatures(point).forEach(f=>{const lab=src[f.source]; if(!lab||f.layer.id.startsWith('lyhl')||map.getLayoutProperty(f.layer.id,'visibility')==='none')return;
    if(f.layer.type==='fill'&&(!best||lyOf[lab]>lyOf[best.lab]))best={f,lab}}); return best}
const esc=v=>String(v).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'})[c]);
// the lit item is drawn from its own source by its id (not from the tiles' clipped pieces, which filled as stray triangles)
const NONE=['==',['id'],-1];
OVERLAYS.forEach(o=>{map.addLayer({id:'lyhlf-'+o.source,type:'fill',source:o.source,filter:NONE,paint:{'fill-color':'#ffffff','fill-opacity':0.55}});
  map.addLayer({id:'lyhl-'+o.source,type:'line',source:o.source,filter:NONE,paint:{'line-color':'#111827','line-width':3}})});
let lit=null; function light(t){const k=t?t.f.source+'|'+t.f.id:null; if(k===lit)return;
  if(lit){const s=lit.split('|')[0]; map.setFilter('lyhlf-'+s,NONE); map.setFilter('lyhl-'+s,NONE)}
  lit=k; if(t){const f=['==',['id'],t.f.id]; map.setFilter('lyhlf-'+t.f.source,f); map.setFilter('lyhl-'+t.f.source,f)}}
const tip=new maplibregl.Popup({closeButton:false,closeOnClick:false,offset:12,className:'lytip'});
// every move is followed: the latest position is handled once per frame (a skipped move left the label on the last item)
let last=null, queued=false; map.on('mousemove',e=>{last=e; if(!queued){queued=true; requestAnimationFrame(()=>{queued=false; hover(last)})}});
function hover(e){const rows=at(e.point);
  document.getElementById('lyhere').innerHTML=rows.length?'<b>here:</b><br>'+rows.map(([i,v])=>`layer ${i}: ${v.join(', ')}`).join('<br>'):'';
  const t=top(e.point); light(t);
  map.getCanvas().style.cursor=t?'pointer':'';
  if(t)tip.setLngLat(e.lngLat).setHTML(`<b>layer ${lyOf[t.lab]}</b> · ${esc(what(t.f.properties))}`).addTo(map); else tip.remove()}
map.on('mouseout',()=>{tip.remove(); light(null)});
let pop=null;
map.on('click',e=>{const t=top(e.point); if(pop)pop.remove(); if(!t)return; const rows=at(e.point);
  const fields=Object.entries(t.f.properties).filter(([k,v])=>!SKIP.has(k)&&v!==null&&v!=='').map(([k,v])=>`<tr><td style="color:#64748b;padding-right:6px">${esc(k)}</td><td>${esc(v)}</td></tr>`).join('');
  const under=rows.filter(([i])=>i<lyOf[t.lab]).map(([i,v])=>`<div style="color:#475569">in layer ${i}: ${esc(v.join(', '))}</div>`).join('');
  pop=new maplibregl.Popup({maxWidth:'360px'}).setLngLat(e.lngLat).setHTML(`<b>layer ${lyOf[t.lab]}</b> · ${esc(what(t.f.properties))}<table style="font-size:12px;margin-top:4px">${fields}</table>${under}`).addTo(map)});
// a click pins what is there, in every layer drawn, as text to copy (with the point's coordinates)
map.on('click',e=>{const rows=at(e.point,true); if(!rows.length)return;
  document.getElementById('lyseltext').textContent=rows.map(([i,v])=>`layer ${i}: ${v.join(', ')}`).join('\\n')+`\\nat ${e.lngLat.lng.toFixed(6)}, ${e.lngLat.lat.toFixed(6)}`;
  document.getElementById('lysel').style.display='block'});
document.getElementById('lycopy').onclick=()=>{const t=document.getElementById('lyseltext').textContent;
  (navigator.clipboard?navigator.clipboard.writeText(t):Promise.reject()).catch(()=>{const r=document.createRange(); r.selectNode(document.getElementById('lyseltext'));
    getSelection().removeAllRanges(); getSelection().addRange(r); document.execCommand('copy')}); document.getElementById('lycopy').textContent='copied'; setTimeout(()=>document.getElementById('lycopy').textContent='copy',1200)};
// only the layers and the base map: the road network's own lines would read as more kinds
function lyBare(){const mine=new Set(OVERLAYS.map(o=>o.source));
  map.getStyle().layers.forEach(x=>{if(x.source&&x.source!=='bm'&&!mine.has(x.source))map.setLayoutProperty(x.id,'visibility','none')})}
// a direct link: layers.html?u=<id> (or #u=<id>), any id of a space, a part, a ground item or a surface: the map goes to it, lights it, and
// the panel lists all its fields (its sources too)
function lyGoTo(id){for(const o of OVERLAYS){const s=map.getSource(o.source), g=s&&s._data&&s._data.geojson;
    const f=g&&g.features&&g.features.find(x=>Object.values(x.properties||{}).includes(id)); if(!f)continue;
    let b=[180,90,-180,-90]; const walk=c=>{if(typeof c[0]==='number'){b=[Math.min(b[0],c[0]),Math.min(b[1],c[1]),Math.max(b[2],c[0]),Math.max(b[3],c[1])]}else c.forEach(walk)};
    walk(f.geometry.coordinates); map.fitBounds([[b[0],b[1]],[b[2],b[3]]],{padding:120,maxZoom:20,duration:0});
    lySV({lng:(b[0]+b[2])/2,lat:(b[1]+b[3])/2});
    if(f.id!=null)light({f:{source:o.source,id:f.id}});
    document.getElementById('lyseltext').textContent=`${o.label}`+Object.entries(f.properties).filter(([k,v])=>!SKIP.has(k)&&v!==null&&v!=='').map(([k,v])=>`\n${k}: ${v}`).join('');
    document.getElementById('lysel').style.display='block'; return}}
// Street View: the road lines are hidden here, and roadstyle's Street View follows a click on a road line; so every click (and a direct
// link) moves it to the road nearest the spot, looking along it (as svHere does on the dashboard)
function lySV(ll){const src=map.getSource('roads'), data=src&&src.serialize&&src.serialize().data; if(!data||!data.features)return;
  const k=Math.cos(ll.lat*Math.PI/180), X=ll.lng*k, Y=ll.lat; let best=null;
  data.features.forEach(f=>{const g=f.geometry; if(!g)return; (g.type==='LineString'?[g.coordinates]:g.type==='MultiLineString'?g.coordinates:[]).forEach(cs=>{
    for(let i=0;i<cs.length-1;i++){const ax=cs[i][0]*k, ay=cs[i][1], bx=cs[i+1][0]*k, by=cs[i+1][1], dx=bx-ax, dy=by-ay, L=dx*dx+dy*dy||1e-18;
      const t=Math.max(0,Math.min(1,((X-ax)*dx+(Y-ay)*dy)/L)), px=ax+t*dx, py=ay+t*dy, d=(X-px)**2+(Y-py)**2;
      if(!best||d<best.d)best={d,x:px/k,y:py,h:(Math.atan2(dx,dy)*180/Math.PI+360)%360,name:(f.properties||{}).name}}})});
  if(!best||Math.sqrt(best.d)*111320>40)return;
  if(window.rsSetStreetViewMarkerAt)rsSetStreetViewMarkerAt(best.x,best.y,best.h);
  const url=`https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${best.y.toFixed(6)},${best.x.toFixed(6)}&heading=${Math.round(best.h)}`;
  document.dispatchEvent(new CustomEvent('rs:select',{detail:{properties:{name:best.name||'Street View'},streetView:url}}))}
map.on('click',e=>lySV(e.lngLat));
const lyLink=()=>{const u=new URLSearchParams(location.search).get('u')||(location.hash.startsWith('#u=')?decodeURIComponent(location.hash.slice(3)):null); if(u)lyGoTo(u)};
window.addEventListener('hashchange',lyLink);
const go=()=>{if(typeof rsSetOverlay==='function'&&typeof map!=='undefined'&&map.loaded&&map.loaded()){lyBare(); leaves(T[0]).filter(x=>!x.off).forEach(x=>on.add(key(x))); draw(); apply(); lyLink()}
  else setTimeout(go,300)}; go()})();
</script>"""
OV = {"street": "Layer 0: street", "blocks": "Layer 0: blocks", "spaces": "Layer 1: street spaces", "land": "Layer 1: land",
      "parcels": "Layer 1: parcels (property lines)", "paths": "Paths (whole)",
      "surf": "Layer 2: surfaces", "parts": "Layer 3: parts"}
GROUND_NOTE = {"building": "each building, whole", "yard": "private ground around the buildings", "car park": "an off-street car park",
               "construction site": "a building site", "green": "parks, playgrounds, grass",
               "alley": "a road inside a block: a back lane, a driveway, a parking aisle", "path": "a footpath or a greenway away from the street",
               "rail": "a railway's ground", "structure": "the land under a bridge", "square": "a pedestrian square",
               "water": "water", "unknown": "no rule claims it (check G1)"}
PART_GROUPS = [("roadway", ("lane", "shoulder", "junction area", "parking", "bus lane", "cycle lane", "paved")), ("median", ("island",)),
               ("pedestrian realm", ("furnishing", "sidewalk", "frontage", "tree pit", "driveway", "bus stop", "open"))]
PART_NAMES = {"furnishing": "buffer (furnishing)", "sidewalk": "clear path (sidewalk)"}


def layers(db, out):
    """The layers page: a strict hierarchy, each layer dividing the one above it. Layer 0: the area into street and blocks. Layer 1: the
    street into its sections (subsections) and intersections, the blocks into plots, green, alleys ... Layer 2: each of those into its
    surfaces. Layer 3: the street's surfaces into parts (lanes, shoulders, the junction area, the pedestrian zones). Layers stack: the top
    one drawn filled, the ones under it as outlines; each opens (without drawing) to its kinds."""
    con = duckdb.connect(db, read_only=True)
    con.execute("LOAD spatial")
    ep = epsg_of(con)
    a = lambda col="geometry": f"round(ST_Area(ST_Transform({col}, 'EPSG:4326', '{ep}', always_xy := true)), 1)"
    edges = frame(con, """SELECT ST_AsWKB(geometry) AS geometry, class AS highway, name, level_min AS level, type,
        try_cast(source_id AS BIGINT) AS edge_id FROM work.element WHERE type = 'road' AND level_min = 0""")
    edges["edge_id"] = edges["edge_id"].astype("Int64")
    # layer 0's street: each connected piece of the street spaces is one item, with an id and what it holds
    import shapely
    us = frame(con, f"""SELECT ST_AsWKB(geometry) AS geometry, unit_id, kind, section_id, {a()} AS area_m2 FROM work.unit WHERE level = 0""")
    # joined within a few centimetres (the spaces meet edge to edge only to the grid of their geometry)
    net = shapely.union_all([shapely.make_valid(g_).buffer(0.000001, join_style="mitre") for g_ in us.geometry]).buffer(-0.000001, join_style="mitre") \
        if len(us) else shapely.Polygon()
    net = shapely.get_parts(net)
    net = sorted(net, key=lambda g: -g.area)
    rows_ = []
    for k, gm in enumerate(net, 1):
        inside = us[[gm.intersects(x.representative_point()) for x in us.geometry]]
        rows_.append(dict(geometry=gm, street_id=f"street-{k}", node="street", kind="street", area_m2=round(float(inside["area_m2"].sum())),
                          sections=int(inside["section_id"].nunique()), subsections=int((inside["kind"] == "subsection").sum()),
                          intersections=int((inside["kind"] == "intersection").sum())))
    street = gpd.GeoDataFrame(rows_, geometry="geometry", crs=4326)
    blocks = blocks_frame(con)
    blocks["node"] = "block"
    spaces = frame(con, f"""SELECT ST_AsWKB(u.geometry) AS geometry, u.unit_id, u.kind, u.kind AS node, 'street' AS p0, u.section_id, {a('u.geometry')} AS area_m2,
        s."left" AS block_left, s."right" AS block_right, s.width_m AS kerb_to_kerb_m, s.starts_at AS cut_because,
        w.total_m AS block_to_block_m, w.lanes_out AS lanes_along, w.lanes_in AS lanes_against
        FROM work.unit u LEFT JOIN work.subsection s ON s.subsection_id = u.unit_id LEFT JOIN work.width w ON w.unit_id = u.unit_id
        WHERE u.level = 0""")
    spaces["color"] = [KIND_COLORS[k] for k in spaces["kind"]]
    try:    # every footpath whole, lying on the layers (work.path)
        paths_ = frame(con, f"""SELECT ST_AsWKB(geometry) AS geometry, path_id, kind, kind AS node, name, width_m, width_source, width_method,
            "on", {a()} AS area_m2 FROM work.path""")
        paths_["color"] = [PATH_COLORS.get(k, "#8b5cf6") for k in paths_["kind"]]
    except duckdb.CatalogException:
        paths_ = None
    try:    # a city's parcels, as lines only: shown on request, they never cut or hide a building
        parcels = frame(con, f"""SELECT ST_AsWKB(p.geometry) AS geometry, p.parcel_id, p.name AS address, 'plot' AS node, {a('p.geometry')} AS area_m2
            FROM work.parcel p, work.area ar WHERE ST_Intersects(p.geometry, ar.geometry)""")
    except duckdb.CatalogException:
        parcels = None
    # a building is drawn whole: its own outline, even where it reaches over the block's edge (the ground item stops at the edge)
    whole = """CASE WHEN g.type = 'building' AND e.geometry IS NOT NULL THEN e.geometry ELSE {col} END"""
    land = frame(con, f"""SELECT ST_AsWKB({whole.format(col='g.geometry')}) AS geometry, g.ground_id, g.type, g.type AS node, 'block' AS p0,
        g.name, g.source, g.method, g.ref, {a('g.geometry')} AS area_m2,
        {ALLEY_W.format(t='g.type', g=f"ST_Transform(g.geometry, 'EPSG:4326', '{ep}', always_xy := true)")}
        FROM work.ground g LEFT JOIN work.element e ON e.type = 'building' AND e.source_id = g.ref WHERE g.type <> 'street'""")
    land["color"] = land["type"].map(LAYER_COLORS[0]).fillna("#9ca3af")
    surf = frame(con, f"""SELECT ST_AsWKB(CASE WHEN s.type = 'building' AND g.type = 'building' AND e.geometry IS NOT NULL THEN e.geometry
        ELSE s.geometry END) AS geometry, s.surface_id, s.type, g.type AS ground_type,
        CASE WHEN g.type <> 'street' THEN g.type WHEN g.ground_id LIKE 'g0-street-i%' THEN 'intersection' ELSE 'subsection' END || ':' || s.type AS node,
        CASE WHEN g.type = 'street' THEN 'street' ELSE 'block' END AS p0,
        CASE WHEN g.type <> 'street' THEN g.type WHEN g.ground_id LIKE 'g0-street-i%' THEN 'intersection' ELSE 'subsection' END AS p1,
        s.ground_id, s.source, s.method, s.ref,
        {a('s.geometry')} AS area_m2 FROM work.surface s JOIN work.ground g USING (ground_id)
        LEFT JOIN work.element e ON e.type = 'building' AND e.source_id = g.ref""")
    surf["color"] = surf["type"].map(LAYER_COLORS[1]).fillna("#9ca3af")
    lid = "p.lane_id" if con.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema = 'work' AND table_name = 'part' "
                                     "AND column_name = 'lane_id'").fetchone()[0] else "NULL AS lane_id"
    parts_ = frame(con, f"""SELECT ST_AsWKB(p.geometry) AS geometry, p.part_id, p.type, p.type AS node, 'street' AS p0, u.kind AS p1,
        p.unit_id, p.direction, p.lane, p.road, p.road_class, p.source, p.method, p.ref, p.width_m, p.width_source, p.width_method,
        p.position_source, p.position_method, p.position_ref, p.rule, {lid}, {a('p.geometry')} AS area_m2
        FROM work.part p JOIN work.unit u USING (unit_id) WHERE p.level = 0""")
    from .ground import STREET_SURFACE
    parts_["p2"] = ["street:" + STREET_SURFACE.get(t, "roadway") for t in parts_["type"]]
    parts_["color"] = [KIND_COLORS.get(t, "#999999") for t in parts_["type"]]

    def leaf(ov, df, val, label, color):
        sel = df[df["node"] == val]
        return dict(leaf=True, ov=OV[ov], val=val, label=label, c=color, n=len(sel), a=int(round(sel["area_m2"].sum())))

    def branch(label, children, **kw):
        ch = [c for c in children if c and (not c.get("leaf") or c["n"])]
        return dict(label=label, children=ch, n=sum(0 if c.get("outline") else c["n"] for c in ch),
                    a=sum(0 if c.get("outline") else c["a"] for c in ch), **kw) if ch else None
    by = lambda df: df.groupby("type")["area_m2"].sum().sort_values(ascending=False).index.tolist()
    n_street = len(street)
    tree = [
        branch("Layer 0 · street and blocks", [
            dict(leaf("street", street, "street", "street", KIND_COLORS["street"]), n=n_street),
            leaf("blocks", blocks, "block", "blocks", BLOCK_COLOR)],
            edge="#111827", note="The area at street level in two: the street, and the blocks (the land between the streets)."),
        branch("Layer 1 · street spaces and land", [
            branch("in the street", [leaf("spaces", spaces, "subsection", "sections (cut into subsections)", KIND_COLORS["subsection"]),
                                     leaf("spaces", spaces, "intersection", "intersections", KIND_COLORS["intersection"])]),
            branch("in the blocks", [leaf("land", land, t, f"{t}: {GROUND_NOTE.get(t, '')}".rstrip(": "), LAYER_COLORS[0].get(t, "#9ca3af"))
                                     for t in by(land)]
                   + ([dict(leaf("parcels", parcels, "plot", "parcels (property lines): the city's parcels, outlines only, off at first", KIND_COLORS["plot"]),
                            off=True, outline=True)] if parcels is not None and len(parcels) else []))],
            edge="#1e3a8a", note="The street into sections (each between two neighbouring blocks, cut into subsections) and intersections; "
                                 "the blocks into buildings (each whole), yards, alleys, green, car parks ... (layer 0 of space-layers.md)."),
        branch("Layer 2 · surfaces", [
            branch("in the street", [branch(name, [leaf("surf", surf, f"{k}:{t}", t, LAYER_COLORS[1].get(t, "#9ca3af")) for t in by(surf[surf["p1"] == k])])
                                     for name, k in (("sections", "subsection"), ("intersections", "intersection"))]),
            branch("in the blocks", [branch(k, [leaf("surf", surf, f"{k}:{t}", t, LAYER_COLORS[1].get(t, "#9ca3af")) for t in by(surf[surf["p1"] == k])])
                                     for k in by(land)])],
            edge="#7c2d12", note="Each item of layer 1 covered by its surfaces: roadway, pedestrian realm, median; building, yard, car park ..."),
        branch("Layer 3 · parts", [branch(g_, [leaf("parts", parts_, t, PART_NAMES.get(t, t), KIND_COLORS.get(t, "#999999")) for t in ts])
                                   for g_, ts in PART_GROUPS]
               + [branch("other", [leaf("parts", parts_, t, t, KIND_COLORS.get(t, "#999999"))
                                   for t in sorted(set(parts_["type"]) - {t for _, ts in PART_GROUPS for t in ts})])],
            edge="#374151", note="The street's surfaces into parts: lanes, shoulders, the junction area; the pedestrian realm's buffer, clear "
                                 "path and frontage. (The blocks have no parts yet.)"),
    ]
    if paths_ is not None and len(paths_):     # not a layer of the hierarchy: whole footpaths lying on all of them
        tree.append(branch("Paths · whole, on top of the layers", [leaf("paths", paths_, k, k, PATH_COLORS.get(k, "#8b5cf6"))
                                                                    for k in by(paths_.assign(type=paths_["kind"]))],
                           edge="#4c1d95", note="Every footpath whole (one item per OSM way, at its width): sidewalks, footways, cycleways, "
                                                "steps, crossings. A path is not cut by a block's edge: it lies on the street and the blocks "
                                                "and names what it lies on."))
    tree = [t for t in tree if t]
    # no map popups here: a click pins every layer's item in the panel (the map's own popup took the lowest layer)
    o = lambda g, **kw: rs.Overlay(g, placement="under", visible=False, popup=[], **kw)
    ovs = [o(street, color=KIND_COLORS["street"], opacity=0.85, outline="#475569", width=1.0, label=OV["street"]),
           o(block_colors(blocks), color=BLOCK_COLOR, color_col="color", opacity=0.6, outline="#5b3410", width=2.0, label=OV["blocks"]),
           o(spaces, color=KIND_COLORS["subsection"], color_col="color", opacity=0.85, outline="#1e3a8a", width=1.2, label=OV["spaces"]),
           o(land, color=LAYER_COLORS[0]["plot"], color_col="color", opacity=0.85, outline="#475569", width=0.6, label=OV["land"]),
           o(surf, color=LAYER_COLORS[1]["building"], color_col="color", opacity=0.9, outline="#334155", width=0.4, label=OV["surf"]),
           o(parts_, color="#4b5260", color_col="color", opacity=0.95, outline="#1f2937", width=0.3, label=OV["parts"])]
    if paths_ is not None and len(paths_):
        ovs.append(rs.Overlay(paths_, placement="over", visible=False, popup=[], color="#8b5cf6", color_col="color", opacity=0.9,
                              outline="#4c1d95", width=0.6, label=OV["paths"]))
    if parcels is not None and len(parcels):
        ovs.append(rs.Overlay(parcels, placement="over", visible=False, popup=[], color=KIND_COLORS["plot"], opacity=0.0, outline=KIND_COLORS["plot"], width=1.6,
                              label=OV["parcels"]))
    m = rs.render_edges(edges, palette="mono", basemap="voyager", name="urbanstyle layers", filter_control=False,
                        street_view_key=os.environ.get("GOOGLE_MAPS_KEY"), overlays=ovs)
    open(out, "w").write(m.html.replace("</body>", LAYERS_PANEL.replace("__LYTREE__", json.dumps(tree)) + "</body>"))
    return out
