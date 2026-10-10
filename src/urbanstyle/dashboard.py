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

LEVELS = (-2, 2)


def frame(con, sql):
    df = con.execute(sql).fetchdf()
    df["geometry"] = [wkb.loads(bytes(g)) for g in df["geometry"]]
    return gpd.GeoDataFrame(df, geometry="geometry", crs=4326)


def tree_data(con, epsg):
    q = lambda sql: con.execute(sql).fetchall()
    by_level = dict(q("""SELECT l, count(*) FROM space.element, generate_series(level_min, level_max) t(l)
                         WHERE type = 'building' GROUP BY l ORDER BY l"""))
    tree = {"buildings": {"total": sum(1 for _ in q("SELECT 1 FROM space.element WHERE type = 'building'")), "byLevel": by_level},
            "containers": {}}
    for l, c, n, r, w, cy, m, k, rl, sid, *bb in q("""SELECT level, container_id, name, n_road, n_walkway, n_cycleway, mean_width_m, kind, n_rail, street_id,
            ST_XMin(geometry), ST_YMin(geometry), ST_XMax(geometry), ST_YMax(geometry)
            FROM space.container ORDER BY level, name NULLS LAST"""):
        tree["containers"].setdefault(l, []).append({"id": c, "n": n, "r": r, "w": w, "c": cy, "m": m, "k": k, "t": rl, "s": sid, "b": bb})
    tree["stations"] = [{"id": i, "n": n, "k": k, "l": l, "b": [x - 0.0012, y - 0.0007, x + 0.0012, y + 0.0007]}
                        for i, n, k, l, x, y in q("SELECT id, name, kind, level, ST_X(geometry), ST_Y(geometry) FROM space.station ORDER BY level, name")]
    area = lambda col="geometry": f"ST_Area(ST_Transform({col}, 'EPSG:4326', '{epsg}', always_xy := true))"
    tree["info"] = {}   # container id -> area, zone areas, mean widths, quality, objects by class: what the focus panel shows
    for cid, a, m, o, ks, nh, wh in q(f"""SELECT container_id, {area()}, mean_width_m, open_share, kerb_share, narrow_half_m, wide_half_m FROM space.container"""):
        tree["info"][cid] = {"a": round(a), "m": m, "o": o, "ks": ks, "nh": nh, "wh": wh, "z": {}, "ob": {}}
    for cid, z, a in q(f"SELECT container_id, zone, {area()} FROM space.zone"):
        if cid in tree["info"]:
            tree["info"][cid]["z"][z] = round(a)
    try:
        for cid, ty, a in q(f"SELECT container_id, type, sum({area()}) FROM space.strip GROUP BY ALL"):
            if cid in tree["info"]:
                tree["info"][cid].setdefault("st", {})[ty] = round(a)
    except duckdb.CatalogException:
        pass
    for cid, cls, n in q("SELECT container_id, class, count(*) FROM space.object WHERE container_id IS NOT NULL GROUP BY ALL"):
        if cid in tree["info"]:
            tree["info"][cid]["ob"][cls] = n
    tree["secarms"] = {}                  # section id -> the intersections it meets (their crossings and signals belong to its view)
    for sid, iid in q("SELECT DISTINCT section_id, intersection_id FROM space.arm WHERE section_id IS NOT NULL"):
        tree["secarms"].setdefault(sid, []).append(iid)
    tree["arms"] = {}                     # intersection id -> the street groups that meet there (an intersection is in several)
    for iid, sid in q("SELECT DISTINCT intersection_id, street_id FROM space.arm WHERE street_id IS NOT NULL"):
        tree["arms"].setdefault(iid, []).append(sid)
    tree["streets"] = {sid: {"n": n, "l": l, "ns": ns, "ni": ni} for sid, l, n, ns, ni in
                       q("SELECT street_id, level, name, n_section, n_intersection FROM space.street")}
    for cid, ids, n, m in q("SELECT container_id, list(building_id ORDER BY length_m DESC), count(*), sum(length_m) FROM space.boundary GROUP BY 1"):
        if cid in tree["info"]:
            tree["info"][cid]["bb"] = ids
            tree["info"][cid]["bn"] = [n, round(m)]
    tree["objects"] = {}
    for cls, n in q("SELECT class, count(*) FROM space.object GROUP BY 1 ORDER BY 1"):
        tree["objects"].setdefault(cls.split(".")[0], {})[cls] = n
    tree["links"] = {}
    for ty, a, b, n in q("SELECT type, level_a, level_b, count(*) FROM space.link GROUP BY ALL ORDER BY ALL"):
        tree["links"].setdefault(ty, {})[f"{a},{b}"] = n
    return tree


# the parts of a space (parts.py): a colour per type, lanes by direction
PART_COLORS = {"lane circulating": "#4b5260", "ring": "#4b5260", "junction area": "#4b5260", "lane in": "#4b5260", "lane out": "#454c59", "lane forward": "#4b5260", "lane backward": "#454c59",
               "lane both": "#4b5260", "lane": "#4b5260", "shoulder": "#5c6370", "parking": "#64748b", "no parking": "#4b5260", "bus zone": "#7f1d1d",
               "parking lot": "#94a3b8", "carriageway": "#4b5260", "bus lane": "#9b2c2c",
               "cycle lane": "#2f855a", "cycle crossing": "#38a169", "crosswalk": "#4b5260", "island": "#8fbf6f",
               "sidewalk": "#d8d2c6", "furnishing": "#b9a58b", "open": "#e9e4d6", "bus stop": "#93c5fd"}   # asphalt, paving; crosswalks are asphalt under their zebra bars
SEEN_COLORS = {"parking": "#2563eb", "no parking": "#9333ea", "give way": "#f97316", "stop": "#dc2626", "traffic light": "#ef4444",
               "street light": "#facc15", "bin": "#65a30d", "bench": "#84cc16", "lane arrow": "#06b6d4", "zebra": "#ffffff"}
PHOTOS_PER_SPACE = 6
# painted and built lines, at real size: type, colour, width in metres, dash
MARKS = [("guide line", "#e5e7eb", 0.1, [2, 3]), ("arrow", "#ffffff", 0.15, None), ("kerb", "#9ca3af", 0.2, None), ("centre line", "#ffffff", 0.15, [3, 2]), ("lane line", "#ffffff", 0.12, [3, 3]),
         ("edge line", "#ffffff", 0.12, None), ("stop line", "#ffffff", 0.4, None), ("give-way line", "#ffffff", 0.35, [1, 1]),
         ("zebra", "#ffffff", 0.5, None)]
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
const show={}; GROUPS.forEach(g=>g[1].forEach(r=>show[r[0]]=(r[0].startsWith('c:')&&!HAS.includes('Spaces'))||r[0]==='buildings'||r[0].startsWith('r:')));   // roads start drawn (2D is a map); with the new spaces (space.unit) the old containers start hidden
const row=r=>`<label><input type=checkbox data-k="${r[0]}" ${show[r[0]]?'checked':''}><span class="sw ${r[3]}" style="background:${r[2]}"></span>${r[1]}${r[4]?` <i>${r[4]}</i>`:''}</label>`;
document.getElementById('chips').innerHTML=GROUPS[0][1].concat(GROUPS[2][1]).map(r=>`<label title="${r[4]}"><input type=checkbox data-k="${r[0]}" checked><span class="sw" style="background:${r[2]}"></span>${r[1]}</label>`).join('');
document.getElementById('lg').innerHTML=GROUPS.slice(1).map((g,i)=>`<div class=gh><label><input type=checkbox data-g="${i+1}"><b>${g[0]}</b></label></div>`+g[1].map(row).join('')).join('')+
  '<div class=nb>Everything else on the map (streets, icons, labels) is the <b>basemap</b>, not our data. Change or hide it with the basemap button at the top right.</div>';
const setKey=(k,v)=>{show[k]=v; document.querySelectorAll(`#us input[data-k="${k}"]`).forEach(i=>i.checked=v)};
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
  ['Subsections','Subsection breaks'].forEach(lab=>{if(HAS.includes(lab)){setOv(lab,!inside&&!ALL); if(!inside&&!ALL)rsFilter(rsQuery(p=>p.level===l&&ownSec(p.section_id),lab),lab)}});
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
  document.querySelectorAll('#us details[data-name]').forEach(d=>d.style.display=d.dataset.name.includes(v)?'':'none')};
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
// the new spaces (space.unit): an intersection's area and how each arm was cut; a section's subsections, one row each
const CUTCOL={'block corners':'#16a34a','one corner':'#f59e0b','crosswalk':'#2563eb'}, PCOL=__PCOL__;
function newBlock(cid){const it=NEWU.inter[cid], ss=NEWU.sec[cid];
  if(it){const bl=it.bb||[], bm=Math.round(bl.reduce((a,b)=>a+b[1],0));
    return `<div><b>${it.rb?'Roundabout':'Intersection'} space</b> · ${it.a.toLocaleString()} m&sup2; · bounded by <b>${bl.length}</b> building${bl.length===1?'':'s'} (${bm} m of edge), the rest by its cuts</div>`+
      `<div><b>Arms</b> (widths at the cut, m)</div><table><tr><th></th><th>total</th><th>road</th><th>left</th><th>right</th><th>lanes in/out</th><th>turns</th></tr>`+
      (it.w||[]).map(([n,t,c,l,r,i,o,s,tu])=>`<tr><td>${n}</td><td>${t}</td><td>${c}</td><td>${l}</td><td>${r}</td><td>${i} / ${o}${s==='default'?' *':''}</td><td>${tu||''}</td></tr>`).join('')+
      `</table><div style="font-size:11px;color:#666">left / right: pedestrian realm, seen from the junction · * lanes estimated (no lanes tag) · turns: each lane coming in, from the right, the ways it may go (SUMO)</div>`+partsTable(cid)+
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
  terrain(in3d&&document.getElementById('terrain3d').checked);
  const add=(spec,filter)=>{if(!spec.source)return; if(!map.getLayer(spec.id)){map.addLayer(spec); U3D.push(spec.id)}
    map.setFilter(spec.id,filter); map.setLayoutProperty(spec.id,'visibility',in3d?'visible':'none')};
  const lvl=['==',['get','level'],lv3d];
  add({id:'u3d-ground',type:'fill',source:ovSrc('Parts'),paint:{'fill-color':['get','color'],'fill-opacity':1}},
      ['all',lvl,['!',['in',['get','type'],['literal',Object.keys(RAISE)]]]]);
  OVERLAYS.filter(o=>o.label.startsWith('Mark: ')&&!NOT_IN_3D.includes(o.label)).forEach(o=>{   // the paint, as in 2D, on the 3D ground
    const l2=map.getStyle().layers.find(x=>x.id===o.layers[0]); if(!l2)return;
    add({id:'u3d-'+o.layers[0],type:l2.type,source:o.source,paint:l2.paint||{},layout:Object.assign({},l2.layout||{},{visibility:'none'})},lvl)});
  // the kerb: a stone 0.25 m wide along the roadway's edge
  add({id:'u3d-kerb',type:'fill-extrusion',source:ovSrc('Kerbs 3D'),paint:{'fill-extrusion-color':'#8f8b86','fill-extrusion-opacity':1,
      'fill-extrusion-height':0.2}},lvl);     // a grey stone, standing 5 cm above the sidewalk: the kerb reads as a line
  add({id:'u3d-raised',type:'fill-extrusion',source:ovSrc('Parts'),paint:{'fill-extrusion-color':['get','color'],'fill-extrusion-opacity':1,
      'fill-extrusion-height':byKey('type',RAISE,0)}},['all',lvl,['in',['get','type'],['literal',Object.keys(RAISE)]]]);
  add({id:'u3d-bld',type:'fill-extrusion',source:ovSrc('Buildings'),paint:{'fill-extrusion-color':'#e7e2d8','fill-extrusion-opacity':0.92,
      'fill-extrusion-height':['get','height_m'],'fill-extrusion-base':['*',['max',['get','level_min'],0],LEVEL_M]}},     // its real height
      ['>=',['get','level_max'],0]);
  const up=['*',['-',['get','level'],lv3d],DECK_M];   // bridges: the levels above, as decks in the air
  add({id:'u3d-deck',type:'fill-extrusion',source:ovSrc('Parts'),paint:{'fill-extrusion-color':['get','color'],'fill-extrusion-opacity':1,
      'fill-extrusion-base':['-',up,SLAB_M],'fill-extrusion-height':['+',up,byKey('type',RAISE,0)]}},['>',['get','level'],lv3d]);
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
// in 3D: the mouse over a lane, a sidewalk or a street object lights it up (yellow) and names its type (a small tooltip, nothing more);
// a click selects it (orange) and opens its popup, the same fields as in 2D; a click on nothing clears the selection
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
function deselect3d(){if(sel3d===null)return false; sel3d=null; paint3d();
  document.querySelectorAll('.maplibregl-popup:not(.u3d-tip)').forEach(x=>x.remove()); return true}
// layer -> [its colour property, the key of a feature, its own colour, its popup fields]
const L3D={'u3d-furn':['fill-extrusion-color','refs',['get','color'],OBJ_POPUP],
  'u3d-bld':['fill-extrusion-color','id','#e7e2d8',__BLDPOPUP__],
  'u3d-kerb':['fill-extrusion-color','kerb_id','#8f8b86',['type','unit_id','arm','length_m','source','method','ref']],
  'u3d-ground':['fill-color','part_id',['get','color'],null],'u3d-raised':['fill-extrusion-color','part_id',['get','color'],null]};
function paint3d(){Object.entries(L3D).forEach(([id,[prop,key,base]])=>{if(!map.getLayer(id))return;
  map.setPaintProperty(id,prop,['case',['==',['get',key],sel3d||'\u0000'],'#f97316',['==',['get',key],hov3d||'\u0000'],'#facc15',base])})}
function bind3d(){if(bound3d||!map.getLayer('u3d-furn'))return; bound3d=true;
  const groundPop=(OVERLAYS.find(o=>o.label==='Parts')||{}).popup||[];
  let took=0;     // the topmost layer under the mouse takes the click: an object before the ground under it
  Object.entries(L3D).forEach(([id,[prop,key,base,fields]])=>{
    map.on('mousemove',id,e=>{const f=e.features&&e.features[0]; if(!f)return; map.getCanvas().style.cursor='pointer';
      const top=map.queryRenderedFeatures(e.point,{layers:Object.keys(L3D).filter(x=>map.getLayer(x))})[0];
      if(!top||top.layer.id!==id)return;
      const k=f.properties[key], ll=e.lngLat, t=f.properties.type;
      if(hov3d===k){tip3d.setLngLat(ll); return}                       // lit already: the tooltip follows the mouse
      if(hov3d!==null){hov3d=null; paint3d(); tip3d.remove()}          // another thing: the last one off at once
      clearTimeout(hovT); hovT=setTimeout(()=>{hov3d=k; paint3d(); tip3d.setLngLat(ll).setText(t).addTo(map)},HOVER_MS)});  // lit once the mouse rests
    map.on('mouseleave',id,()=>{clearTimeout(hovT); hov3d=null; map.getCanvas().style.cursor=''; paint3d(); tip3d.remove()});
    map.on('click',id,e=>{if(Date.now()-took<50)return; took=Date.now(); const p=e.features[0].properties;
      if(sel3d===p[key]){deselect3d(); return}          // a click on the selected one deselects it
      sel3d=p[key]; paint3d(); pop3d(e,p,fields||groundPop,p[key])})});
  map.on('click',e=>{if(!in3d)return; const hit=map.queryRenderedFeatures(e.point,{layers:Object.keys(L3D).filter(x=>map.getLayer(x))});
    if(!hit.length)deselect3d();
    svHere()})}       // 3D hides the road lines roadstyle's Street View follows: any click moves an open window to the nearest road
map.on('pitchend',()=>{setView(); apply()});   // the view follows the tilt: 3D's own layers, or 2D's
// Street View: roadstyle's window follows clicks on a road's centre line only; in a space most clicks land on its parts, lines or
// Mapillary points (overlays). While the window is open such a click moves it too: to the road nearest the spot, looking along it.
let downAt=null; map.on('mousedown',e=>downAt=e.lngLat); map.on('touchstart',e=>downAt=e.lngLat);
function svHere(name){const w=document.querySelector('.rs-svw'); if(!w||w.hidden||!downAt)return;
  // the road nearest the spot, from the map's road data (the roads need not be drawn: the overview hides them), looking along it
  const src=map.getSource('roads'), data=src&&src.serialize&&src.serialize().data; if(!data||!data.features)return;
  const k=Math.cos(downAt.lat*Math.PI/180), X=downAt.lng*k, Y=downAt.lat;
  let best=null;
  data.features.forEach(f=>{const g=f.geometry; if(!g)return; (g.type==='LineString'?[g.coordinates]:g.type==='MultiLineString'?g.coordinates:[]).forEach(cs=>{
    for(let i=0;i<cs.length-1;i++){const ax=cs[i][0]*k, ay=cs[i][1], bx=cs[i+1][0]*k, by=cs[i+1][1], dx=bx-ax, dy=by-ay, L=dx*dx+dy*dy||1e-18;
      const t=Math.max(0,Math.min(1,((X-ax)*dx+(Y-ay)*dy)/L)), px=ax+t*dx, py=ay+t*dy, d=(X-px)**2+(Y-py)**2;
      if(!best||d<best.d)best={d,x:px/k,y:py,h:(Math.atan2(dx,dy)*180/Math.PI+360)%360,name:(f.properties||{}).name}}})});
  if(!best||Math.sqrt(best.d)*111320>40)return;      // no road within 40 m
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
  else if(['Spaces','Subsections','Subsection breaks'].includes(d.overlay))focusUnit(p)});
// a new space (space.unit) or a subsection line: focus its section (or its intersection); a section only the new division has: zoom to the space
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
function fromHash(){const m=location.hash.match(/^#c=(.+)$/)||location.search.match(/[?&]c=([^&]+)/); if(m)focusOn(decodeURIComponent(m[1]))}
window.addEventListener('hashchange',fromHash);
</script>
"""


KINDS = [("section", "Sections", "#a78bfa", "#6d28d9"), ("intersection", "Intersections", "#fbbf24", "#b45309"),
         ("path", "Path spaces", "#6ee7b7", "#047857"), ("rail", "Rail spaces", "#f9a8d4", "#be185d"), ("plaza", "Plazas", "#f43f5e", "#9f1239")]   # kind, overlay label, fill, outline
POP = ["cid", "name", "kind", "shape", "level", "n_buildings", "width_m", "narrow_half_m", "wide_half_m", "open_share", "one_side_open", "kerb_share",
       "n_road", "n_walkway", "n_cycleway"]


def epsg_of(con):
    lon = con.execute("SELECT avg(ST_X(ST_Centroid(geometry))) FROM space.container").fetchone()[0]
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
from urbanstyle.mapillary import CLASS_OF as _CLASS_OF
from urbanstyle.parts import RAISED
SEEN_CLASS = {g: c for g, c in _CLASS_OF.items() if c.startswith("furniture.")}     # the observations that are street objects
SIGN_COLOR = {"give way": "#dc2626", "stop": "#b91c1c", "parking": "#1d4ed8", "no parking": "#2563eb"}
KERB_BACK_M = 0.5     # a pole moved off the roadway stands this far behind the kerb
FACADE_SNAP_M = 3.0   # a point this far inside a building is at its facade (mapped a little off); deeper is indoors


# an object's popup and tooltip, the same in 2D and in 3D: the tooltip names its type, the popup says what it is and who knows it
DOT_COLORS = {"furniture": "#4f46e5", "vegetation": "#16a34a", "utility": "#6b7280", "transit": "#0891b2", "access": "#db2777", "barrier": "#78350f"}
BLD_POPUP = ["type", "name", "use", "ground_floor", "evidence", "class", "floors", "height_m", "level_src", "id"]     # a building's popup, the same in 2D and 3D
OBJ_POPUP, OBJ_TIP = ["type", "height_m", "details", "sources", "method", "refs", "space"], ["type"]
TYPE_NAME = {"crossing.zebra": "zebra crossing", "crossing.signalised": "signalised crossing", "crossing.other": "crossing", "kerb.node": "kerb",
             "transit.stop": "transit stop", "access.entrance": "entrance", "access.parking_entrance": "parking entrance", "barrier.other": "barrier",
             "utility.junction_box": "electrical box"}     # a street-lighting junction box: a lid in the pavement, not the junction area


def type_of(cls):
    """A class as people say it: furniture.lamp -> lamp, utility.catch_basin -> catch basin, crossing.zebra -> zebra crossing."""
    return TYPE_NAME.get(cls, str(cls).split(".")[-1].replace("_", " "))


def placer(con, epsg):
    """place(point, level, cls) -> where a piece of street furniture stands: off the roadway (onto the nearest pavement, KERB_BACK_M behind
    the kerb) and out of the buildings (at the facade), else where it was mapped. Points in metres (epsg)."""
    import shapely
    from shapely.ops import nearest_points
    to_m = f"ST_AsWKB(ST_Transform(geometry, 'EPSG:4326', '{epsg}', always_xy := true))"
    road, walk, bld = {}, {}, {}
    try:
        for lv, t, w in con.execute(f"SELECT level, type, {to_m} FROM space.part").fetchall():
            (walk if t in ("sidewalk", "furnishing", "open", "island", "parking lot", "bus stop") else road).setdefault(lv, []).append(shapely.from_wkb(bytes(w)))
    except duckdb.CatalogException:
        pass
    for lv, w in con.execute(f"SELECT l, {to_m} FROM space.element, generate_series(level_min, level_max) t(l) WHERE type = 'building'").fetchall():
        bld.setdefault(lv, []).append(shapely.from_wkb(bytes(w)))
    trees = {k: {lv: (shapely.STRtree(v), v) for lv, v in d.items()} for k, d in (("road", road), ("walk", walk), ("bld", bld))}

    def hit(kind, p, lv):
        t = trees[kind].get(lv)
        return [t[1][k] for k in t[0].query(p, predicate="within")] if t else []

    def place(p, lv, cls):
        if cls not in SNAP:
            return p
        for kind, gap, near in (("road", KERB_BACK_M, "walk"), ("bld", 0.3, None)):
            inside = hit(kind, p, lv)
            if not inside:
                continue
            if near:            # onto the nearest pavement within 8 m
                t = trees["walk"].get(lv)
                cand = [t[1][k] for k in t[0].query(p.buffer(8))] if t else []
                if not cand:
                    return p
                q = nearest_points(shapely.union_all(cand), p)[0]
            else:               # out to the facade, if just inside it (deeper is indoors: it stays)
                q = nearest_points(inside[0].exterior, p)[0]
                if q.distance(p) > FACADE_SNAP_M:
                    return p
            dx, dy = q.x - p.x, q.y - p.y
            h = (dx * dx + dy * dy) ** 0.5 or 1.0
            return shapely.Point(q.x + dx / h * gap, q.y + dy / h * gap)
        return p
    return place


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
    for oid, cls, lv, w, attrs in con.execute(f"SELECT object_id, class, level, {to_m()}, attrs::VARCHAR FROM space.object").fetchall():
        if not cls.startswith(NOT_OBJECTS):
            items.append((oid, cls, lv, None, "osm", shapely.from_wkb(bytes(w)), None, "mapped"))
            info[str(oid)] = _fields(attrs)
    seen = {}
    try:
        for fid, grp, a, b, w in con.execute(f"SELECT feature_id, grp, first_seen, last_seen, {to_m()} FROM space.observed").fetchall():
            if grp in SEEN_CLASS:
                items.append((fid, SEEN_CLASS[grp], 0, grp, "mapillary", shapely.from_wkb(bytes(w)), None, "observed"))
                seen[fid] = (a, b)
                info[str(fid)] = f"seen {a:%Y-%m-%d} .. {b:%Y-%m-%d}" if a and b else ""
    except duckdb.CatalogException:
        pass
    dos, city = db.replace(".space.duckdb", ".duckdb"), db.replace(".space.duckdb", ".vancouver.json")
    if city != db and os.path.exists(city):         # a city's surveyed objects around the unit, all of them (the dossier holds the unit's)
        import pyproj
        from urbanstyle.unit import VAN_OBJECT, van_method
        fwd = pyproj.Transformer.from_crs("EPSG:4326", epsg, always_xy=True).transform
        for ds, fc in json.load(open(city)).items():
            for i, ft in enumerate(fc["features"]):
                if ds in VAN_OBJECT and ft["geometry"] and ft["geometry"]["type"] == "Point":
                    h = (ft["properties"] or {}).get("height_m")
                    items.append((f"{ds}-{i}", VAN_OBJECT[ds], 0, None, "vancouver", shapely.Point(fwd(*ft["geometry"]["coordinates"][:2])),
                                  float(h) if isinstance(h, (int, float)) else None, van_method(ds, ft["properties"])))
                    info[f"{ds}-{i}"] = _fields(ft["properties"])
    elif dos != db and os.path.exists(dos):
        con.execute(f"ATTACH IF NOT EXISTS '{dos}' AS dos (READ_ONLY)")
        crs = con.execute("SELECT crs FROM dos.unit").fetchone()[0]
        items += [(oid, cls, 0, None, src, shapely.from_wkb(bytes(w)), h, meth) for oid, cls, src, w, h, meth in con.execute(
            f"SELECT object_id, class, source, {to_m(crs=crs)}, height_m, method FROM dos.object WHERE source NOT IN ('osm', 'mapillary')").fetchall()]
    m = duckdb.connect()
    m.execute("LOAD spatial")
    m.execute("CREATE TABLE object (object_id VARCHAR, class VARCHAR, source VARCHAR, height_m DOUBLE, confidence DOUBLE, geometry GEOMETRY)")
    m.executemany("INSERT INTO object VALUES (?, ?, ?, NULL, ?, ST_GeomFromWKB(?))",       # confidence: by how the source got it (method)
                  [(str(oid), f"{cls}@{lv}", src, CONFIDENCE.get(meth, 0.5), shapely.to_wkb(p)) for oid, cls, lv, _, src, p, _h, meth in items])
    match(m, {str(k): v for k, v in seen.items()})
    by_id = {str(i[0]): i for i in items}
    out = []
    for refs, sources in m.execute("SELECT refs, sources FROM match").fetchall():
        oid, cls, lv, grp, _, p, _h, _m = by_id[refs.split(", ")[0]]      # the best source's
        h = next((by_id[r][6] for r in refs.split(", ") if by_id[r][6]), None)   # a measured height (a city's tree), from any source
        details = " | ".join(f"{by_id[r][4]}: {info[r]}" for r in refs.split(", ") if info.get(r))
        methods = "; ".join(f"{by_id[r][4]}: {by_id[r][7]}" for r in refs.split(", "))      # in the order of refs
        out.append((oid, cls, lv, grp, p, refs, sources, h, details, methods))
    return out


def furniture_3d(con, epsg, place, objs):
    """The 3D view's street furniture, each a few stacked blocks turned to its road: a street light (pole, arm over the road, lamp), a
    traffic light (pole, signal head), a sign (pole, plate in its colour), a tree (trunk, crown), a bench (seat, back), a bin, a bollard.
    one per real object (`objs`: matched_objects), where it stands (place). Polygons in lon/lat: base, height, colour, level, and the
    object they draw in OBJ_POPUP's fields (type, sources, refs: every source's id, space), the same as in 2D."""
    import math
    import shapely
    from shapely.ops import transform
    import pyproj
    to_m = lambda col="geometry": f"ST_AsWKB(ST_Transform({col}, 'EPSG:4326', '{epsg}', always_xy := true))"
    roads = con.execute(f"SELECT level_min, {to_m()} FROM space.element WHERE type = 'road'").fetchall()
    rg = [shapely.from_wkb(bytes(r[1])) for r in roads]
    rtree = shapely.STRtree(rg)
    units = con.execute(f"SELECT unit_id, level, {to_m()} FROM space.unit").fetchall()
    ug = [shapely.from_wkb(bytes(u[2])) for u in units]
    utree = shapely.STRtree(ug)
    out = []
    for oid, cls, lv, grp, p, refs, sources, measured, details, methods in objs:
        if not cls.startswith("utility."):       # a manhole, a drain, a lid lies in the ground where it is mapped (a roadway too)
            p = place(p, lv, cls)
        cand = [k for k in rtree.query(p.buffer(25)) if roads[k][0] == lv]
        ux, uy = 0.0, 1.0           # towards the road
        if cand:
            q = rg[min(cand, key=lambda k: rg[k].distance(p))].interpolate(rg[min(cand, key=lambda k: rg[k].distance(p))].project(p))
            h = math.hypot(q.x - p.x, q.y - p.y)
            if h > 0.1:
                ux, uy = (q.x - p.x) / h, (q.y - p.y) / h
        ax, ay = -uy, ux            # along the road

        def blk(off, L, W, b, t, col):     # a block centred `off` m towards the road, L along it, W across
            cx, cy = p.x + ux * off, p.y + uy * off
            pts = [(cx + ax * a * L / 2 + ux * c * W / 2, cy + ay * a * L / 2 + uy * c * W / 2) for a, c in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
            out.append((shapely.Polygon(pts), b, t, col, cls, lv, refs, sources, None, details, methods))
        if cls == "furniture.lamp":
            blk(0, 0.22, 0.22, 0, 7.6, "#52525b"); blk(0.8, 0.12, 1.6, 7.35, 7.5, "#52525b"); blk(1.6, 0.35, 0.6, 7.05, 7.35, "#fde68a")
        elif cls == "furniture.signal":
            blk(0, 0.16, 0.16, 0, 2.3, "#3f3f46"); blk(0.12, 0.32, 0.28, 2.3, 3.3, "#111827"); blk(0.27, 0.2, 0.04, 3.0, 3.2, "#ef4444")
        elif cls == "furniture.sign":
            blk(0, 0.08, 0.08, 0, 2.05, "#9ca3af"); blk(0.05, 0.65, 0.05, 2.0, 2.65, SIGN_COLOR.get(grp, "#2563eb"))
        elif cls == "furniture.waste":
            blk(0, 0.5, 0.5, 0, 1.0, "#3f6212")
        elif cls == "furniture.bench":
            blk(0, 1.8, 0.45, 0.4, 0.48, "#92400e"); blk(-0.2, 1.8, 0.07, 0.48, 0.9, "#92400e"); blk(0, 0.08, 0.4, 0, 0.4, "#44403c")
        elif cls == "furniture.bollard":
            blk(0, 0.18, 0.18, 0, 0.9, "#374151")
        elif cls == "vegetation.tree":         # at its measured height where a source has one (a city's tree survey), else 7.5 m
            top = measured or 7.5
            blk(0, 0.35, 0.35, 0, top * 0.35, "#78350f")
            out.append((p.buffer(max(1.2, top * 0.27), quad_segs=4), top * 0.35, top, "#4d9a52", cls, lv, refs, sources, top, details, methods))
        elif cls == "utility.manhole":          # in the ground: a cast-iron cover, 0.6 m across
            out.append((p.buffer(0.3, quad_segs=6), 0, 0.04, "#3f3f46", cls, lv, refs, sources, 0, details, methods))
        elif cls == "utility.catch_basin":      # a drain grate at the kerb, 0.6 m along the road, 0.4 m across
            blk(0, 0.6, 0.4, 0, 0.04, "#27272a")
        elif cls == "utility.junction_box":     # a lid in the pavement
            blk(0, 0.45, 0.3, 0, 0.04, "#71717a")
        elif cls == "furniture.parking_meter":
            blk(0, 0.08, 0.08, 0, 1.15, "#6b7280"); blk(0, 0.22, 0.16, 1.15, 1.5, "#1f2937")
        elif cls == "furniture.map_stand":      # a wayfinding stand: a panel 1 m wide, 2.4 m high
            blk(0, 1.0, 0.15, 0, 2.4, "#1e3a8a")
        elif cls == "furniture.bike_parking":   # a row of stands, 2 m along the kerb
            blk(0, 2.0, 0.6, 0, 0.8, "#94a3b8")
        elif cls == "access.entrance":          # a door in the facade
            blk(0, 1.2, 0.2, 0, 2.2, "#78350f")
        elif cls == "access.parking_entrance":  # a garage door
            blk(0, 3.0, 0.2, 0, 2.4, "#52525b")
        elif cls == "barrier.other":            # a short piece of wall or fence
            blk(0, 1.5, 0.25, 0, 1.0, "#6b7280")
        elif cls == "transit.stop":
            blk(0, 0.1, 0.1, 0, 2.4, "#9ca3af"); blk(0.05, 0.45, 0.05, 2.0, 2.7, "#1d4ed8")
            if "shelter: yes" in (details or ""):      # its shelter (OSM shelter=yes), behind the pole, away from the road
                blk(-1.2, 3.0, 0.08, 0, 2.4, "#cbd5e1"); blk(-0.6, 3.2, 1.4, 2.4, 2.55, "#94a3b8")
        elif cls == "furniture.shelter":
            blk(0, 3.0, 0.08, 0, 2.4, "#cbd5e1"); blk(0.6, 3.2, 1.6, 2.4, 2.55, "#94a3b8")
        elif cls in ("furniture.post_box", "furniture.vending", "furniture.hydrant", "furniture.advertising", "furniture.charging", "furniture.water"):
            size = {"furniture.post_box": (0.5, 0.4, 1.2, "#b91c1c"), "furniture.vending": (0.8, 0.6, 1.8, "#7c3aed"), "furniture.hydrant": (0.3, 0.3, 0.8, "#ef4444"),
                    "furniture.advertising": (1.2, 0.3, 2.2, "#ec4899"), "furniture.charging": (0.5, 0.3, 1.5, "#16a34a"), "furniture.water": (0.3, 0.3, 1.0, "#38bdf8")}[cls]
            blk(0, size[0], size[1], 0, size[2], size[3])
    back = pyproj.Transformer.from_crs(epsg, "EPSG:4326", always_xy=True).transform
    rows = []
    tops = {}                                   # an object's height: the top of its highest block
    for g, b, t, *_, refs, sources, top, details, methods in out:
        tops[refs] = max(tops.get(refs, 0), t)
    for g, b, t, col, cls, lv, refs, sources, top, details, methods in out:
        top = tops[refs]
        hits = [units[k][0] for k in utree.query(g.centroid) if units[k][1] == lv and ug[k].distance(g.centroid) < 0.5]
        rows.append((cls, type_of(cls), b, t, col, lv, hits[0] if hits else "", refs, sources, methods, round(top, 1), details, transform(back, g)))
    return gpd.GeoDataFrame([r[:12] for r in rows], columns=["class", "type", "base", "height", "color", "level", "space", "refs", "sources",
                                                             "method", "height_m", "details"], geometry=[r[12] for r in rows], crs=4326)


def object_shapes(con, epsg, place=None):
    """One polygon (or several) per object at its real size, turned to run along the nearest road. Returns a GeoDataFrame in lon/lat."""
    import math
    import shapely
    from shapely import STRtree
    tr = f"ST_Transform(geometry, 'EPSG:4326', '{epsg}', always_xy := true)"
    roads = con.execute(f"SELECT level_min, coalesce(width_m, 6.5), ST_AsWKB({tr}) FROM space.element WHERE type = 'road'").fetchall()
    geoms = shapely.from_wkb([bytes(r[2]) for r in roads])
    tree = STRtree(geoms)
    rows = []
    for oid, cls, level, cid, w in con.execute(f"SELECT object_id, class, level, container_id, ST_AsWKB({tr}) FROM space.object").fetchall():
        shape, size, _ = OBJ_SHAPES.get(cls, ("circle", 0.25, "#888888"))
        p = shapely.from_wkb(bytes(w))
        if place is not None:
            p = place(p, level, cls)
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


DOSSIER_COLORS = {"osm": "#2563eb", "mapillary": "#f59e0b", "vancouver": "#16a34a", "nvdb": "#9333ea"}


def dossier_layers(con, db):
    """A unit's dossier (unit.py) next to its built neighbourhood (`<unit>.space.duckdb` -> `<unit>.duckdb`): its roads and its objects
    from every source, each with all it knows (`info`: the source's own attributes), and the real objects they were matched into
    (`match`: one per object, with every source's id), to click on. Empty frames without a dossier."""
    path = db.replace(".space.duckdb", ".duckdb")
    empty = gpd.GeoDataFrame({"source": []}, geometry=[], crs=4326)
    if path == db or not os.path.exists(path):
        return empty, empty, empty
    con.execute(f"ATTACH IF NOT EXISTS '{path}' AS dos (READ_ONLY)")
    crs = con.execute("SELECT crs FROM dos.unit").fetchone()[0]
    ll = f"ST_AsWKB(ST_Transform(geometry, '{crs}', 'EPSG:4326', always_xy := true)) AS geometry"
    roads = frame(con, f"SELECT * EXCLUDE (geometry, osm_id), {ll} FROM dos.road")
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
    return roads, objs, matches


def main(db, out):
    con = duckdb.connect(db, read_only=True)
    con.execute("LOAD spatial")
    edges = frame(con, """SELECT ST_AsWKB(geometry) AS geometry, class AS highway, name, level_min AS level, type, container_id,
        CASE WHEN level_src = 'bridge' THEN 'yes' END AS bridge, CASE WHEN level_src = 'tunnel' THEN 'yes' END AS tunnel,
        level_min AS layer, try_cast(source_id AS BIGINT) AS edge_id, coalesce(oneway, false) AS oneway FROM space.element WHERE type <> 'building'""")
    edges["edge_id"] = edges["edge_id"].astype("Int64")
    buildings = frame(con, """SELECT ST_AsWKB(geometry) AS geometry, source_id AS id, name, class, level_min, level_max, level_src,
        CASE WHEN coalesce(class, 'yes') = 'yes' THEN 'building' ELSE 'building (' || class || ')' END AS type,
        -- its real size (space.element floors, height_m: before levels are clamped to -2..2), else one floor
        coalesce(floors, greatest(level_max, 0) + 1) AS floors, coalesce(height_m, round((greatest(level_max, 0) + 1) * 3.2, 1)) AS height_m,
        -- what it is used for, its ground floor, each with its source and method (buildings.py), and the evidence
        "use" || ' (' || use_source || ', ' || use_method || ')' AS "use", ground_use || ' (' || ground_source || ', ' || ground_method || ')' AS ground_floor,
        uses AS evidence FROM space.element WHERE type = 'building'""")
    zones = frame(con, """SELECT ST_AsWKB(z.geometry) AS geometry, z.level, z.zone, z.container_id AS cid, c.name
        FROM space.zone z JOIN space.container c USING (container_id)""")
    streets = frame(con, """SELECT ST_AsWKB(geometry) AS geometry, container_id AS cid, name, level, round(mean_width_m, 1) AS width_m,
        round(open_share, 2) AS open_share, round(narrow_half_m, 1) AS narrow_half_m, round(wide_half_m, 1) AS wide_half_m,
        round(one_side_open_share, 2) AS one_side_open, round(kerb_share, 2) AS kerb_share, n_road, n_walkway, n_cycleway, kind, shape, n_buildings FROM space.container""")
    kinds = [(k, lab, c) for k, lab, c, _ in KINDS if (streets.kind == k).any()]   # the kinds present in this area
    rails = frame(con, "SELECT ST_AsWKB(geometry) AS geometry, source_id AS id, name, class, level_min AS level FROM space.element WHERE type = 'rail'")
    stations = frame(con, "SELECT ST_AsWKB(geometry) AS geometry, id, name, kind, level FROM space.station")
    objects = frame(con, """SELECT ST_AsWKB(geometry) AS geometry, object_id, class, split_part(class, '.', 1) AS grp, level, container_id AS cid, zone,
        name, attrs::VARCHAR AS attrs, near_m FROM space.object""")
    try:
        strips = frame(con, """SELECT ST_AsWKB(geometry) AS geometry, container_id AS cid, level, type, coalesce(side, '') AS side, round(width_m, 1) AS width_m, source FROM space.strip""")
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
        furn = furniture_3d(con, epsg_of(con), place, mobjs)
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
    lon = con.execute("SELECT avg(ST_X(ST_Centroid(geometry))) FROM space.container").fetchone()[0]
    epsg = f"EPSG:{32600 + int((lon + 180) // 6) + 1}"   # the metric zone, as in urbanstyle.build
    track = zones[zones.zone == "track"]
    try:
        subs = frame(con, """SELECT ST_AsWKB(geometry) AS geometry, subsection_id, section_id, level, class, width_m, oneway, length_m, "left", "right",
            starts_at, color FROM space.subsection""")
        brk = frame(con, """SELECT ST_AsWKB(ST_StartPoint(geometry)) AS geometry, subsection_id, section_id, level, starts_at FROM space.subsection
            WHERE starts_at <> 'section end'""")
        units = frame(con, f"""SELECT ST_AsWKB(geometry) AS geometry, unit_id, kind, section_id, level, color,
            round(ST_Area(ST_Transform(geometry, 'EPSG:4326', '{epsg_of(con)}', always_xy := true)))::INT AS area_m2 FROM space.unit""")
        cuts = frame(con, """SELECT ST_AsWKB(geometry) AS geometry, intersection_id, edge_id, level, how, length_m,
            CASE how WHEN 'block corners' THEN '#16a34a' WHEN 'one corner' THEN '#f59e0b' WHEN 'crosswalk' THEN '#2563eb' ELSE '#6b7280' END AS color FROM space.cut""")
        ep = epsg_of(con)
        jroads = frame(con, """SELECT ST_AsWKB(ST_CollectionExtract(ST_Intersection(e.geometry, u.geometry), 2)) AS geometry, u.unit_id, e.level_min AS level,
            e.name, e.class FROM space.element e JOIN space.unit u ON u.kind IN ('intersection', 'roundabout') AND u.level = e.level_min AND ST_Intersects(e.geometry, u.geometry)
            WHERE e.type = 'road'""")
        jroads = jroads[~jroads.geometry.is_empty]
        try:    # the inside of each space (parts.py): parts, marks, widths
            pcols = {r[0] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'space' AND table_name = 'part'").fetchall()}
            holds = ", ".join(c if c in pcols else f"NULL AS {c}" for c in ("holds", "rule"))     # (columns of 2026-10-09 on)
            length = "length_m" if "length_m" in pcols else "NULL AS length_m"
            pts_ = frame(con, f"""SELECT ST_AsWKB(geometry) AS geometry, unit_id, part_id, level, type, coalesce(arm, '') AS arm,
                coalesce(direction, '') AS direction, lane, width_m, {length}, source, method, ref, road, road_class, speed, surface, lit, road_lanes, oneway,
                {holds}, round(ST_Area(ST_Transform(geometry, 'EPSG:4326', '{ep}', always_xy := true)), 1) AS area_m2 FROM space.part ORDER BY level""")   # upper levels drawn last
            pts_["color"] = [PART_COLORS.get(f"{t} {d}".strip(), PART_COLORS.get(t, "#999999")) for t, d in zip(pts_["type"], pts_["direction"])]
            marks = frame(con, "SELECT ST_AsWKB(geometry) AS geometry, unit_id, level, type, coalesce(arm, '') AS arm, length_m, source, method, ref FROM space.mark ORDER BY level")
            kerbs3d = marks[marks["type"] == "kerb"].copy()     # 3D's kerbstones: each kerb line as a strip 0.25 m wide
            kerbs3d = kerbs3d.set_geometry(kerbs3d.to_crs(ep).buffer(0.125, cap_style="flat").to_crs(4326))
            kerbs3d["kerb_id"] = [f"kerb-{k}" for k in range(len(kerbs3d))]
            uwidths = con.execute("SELECT unit_id, edge, arm, total_m, carriageway_m, left_m, right_m, lanes_in, lanes_out, source FROM space.width").fetchall()
        except duckdb.CatalogException:
            pts_, marks, uwidths = pd.DataFrame({"type": []}), pd.DataFrame({"type": []}), []
            kerbs3d = gpd.GeoDataFrame({"type": []}, geometry=[], crs=4326)
        unit_of = dict(con.execute("""SELECT o.object_id, min(u.unit_id) FROM space.object o JOIN space.unit u ON u.level = o.level
            AND ST_Intersects(u.geometry, o.geometry) GROUP BY 1""").fetchall())
        ubld = con.execute(f"""SELECT u.unit_id, b.source_id, round(ST_Length(ST_Intersection(ST_Boundary(ST_Transform(u.geometry, 'EPSG:4326', '{ep}', always_xy := true)),
              ST_Buffer(ST_Transform(b.geometry, 'EPSG:4326', '{ep}', always_xy := true), 1.0))), 1) AS m
            FROM space.unit u JOIN space.element b ON b.type = 'building' AND b.level_min <= u.level AND b.level_max >= u.level
              AND ST_Intersects(ST_Buffer(u.geometry, 0.00002), b.geometry) WHERE u.kind IN ('intersection', 'roundabout')""").fetchall()
        ubounds = {r[0]: [round(x, 7) for x in r[1:]] for r in con.execute(
            "SELECT unit_id, ST_XMin(geometry), ST_YMin(geometry), ST_XMax(geometry), ST_YMax(geometry) FROM space.unit WHERE kind IN ('intersection', 'roundabout')").fetchall()}
    except duckdb.CatalogException:
        subs = brk = units = cuts = jroads = pd.DataFrame()
        pts_, marks, uwidths = pd.DataFrame({"type": []}), pd.DataFrame({"type": []}), []
        kerbs3d = gpd.GeoDataFrame({"type": []}, geometry=[], crs=4326)
        unit_of, ubld, ubounds = {}, [], {}
    try:        # Mapillary (mapillary.py): what its photos saw, and the photos nearest each space (CC BY-SA, © Mapillary contributors)
        seen = frame(con, """SELECT ST_AsWKB(any_value(o.geometry)) AS geometry, o.feature_id, any_value(o.class) AS class, any_value(o.grp) AS grp,
            any_value(o.last_seen)::DATE::VARCHAR AS last_seen, coalesce(min(u.unit_id), '') AS unit,
            coalesce(min(u.level) FILTER (WHERE u.level = 0), min(u.level), 0) AS level FROM space.observed o
            LEFT JOIN space.unit u ON ST_Intersects(u.geometry, ST_Buffer(o.geometry, 0.00003)) GROUP BY o.feature_id""")
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
        for uid, pid, when, pano in con.execute("""SELECT u.unit_id, p.photo_id, p.captured::DATE::VARCHAR, p.is_pano FROM space.unit u
                JOIN space.photo p ON ST_Intersects(u.geometry, p.geometry) ORDER BY u.unit_id, p.captured DESC""").fetchall():
            if len(photos.setdefault(uid, [])) < PHOTOS_PER_SPACE:
                photos[uid].append([pid, when, bool(pano)])
    except duckdb.CatalogException:
        seen, photos = pd.DataFrame({"grp": []}), {}
    droads, dobjs, dmatch = dossier_layers(con, db)
    shapes["unit"] = shapes["object_id"].map(unit_of)
    objects["unit"] = objects["object_id"].map(unit_of)
    has = [lab for lab, df in (("Track", track), ("Rail", rails), ("Station", stations), ("Spaces", units), ("Parts", pts_), ("Cuts", cuts), ("Junction roads", jroads), ("Subsections", subs),
                               ("Subsection breaks", brk), ("Street objects", dots), ("Mapillary", seen)) if len(df)]   # overlays present in this area
    links = frame(con, "SELECT ST_AsWKB(geometry) AS geometry, node_id, level_a, level_b, type, assumed, station_id, match, round(dist_m) AS dist_m FROM space.link")
    # type, name shown, colour, what it is. Colours differ from every other layer's on purpose.
    defs = [("ramp", "Ramp", "#f59e0b", "a bridge or tunnel is involved"), ("stairs", "Stairs", "#0f172a", "steps join two levels"),
            ("elevator", "Elevator", "#06b6d4", "a lift"), ("entrance", "Station entrance", "#ef4444", "tied to its station (by name, else the nearest); level -1 is assumed only when no station is found"),
            ("connection", "Other level change", "#ec4899", "ways on different layers meet, no ramp, stairs or lift tagged")]
    defs = [d for d in defs if (links["type"] == d[0]).any()]
    o = lambda g, **kw: rs.Overlay(g, placement="under", **kw)
    m = rs.render_edges(
        edges, palette="mono", basemap="voyager", name="urbanstyle", filter_control=False,   # no road-class filter window
        street_view_key=os.environ.get("GOOGLE_MAPS_KEY"),   # Street View's linked panorama (the key is written into the page: restrict it in Google Cloud) settings={"config": {"fill_opacity": 0.35, "casing_opacity": 0.2}}, road_popup=["edge_id", "container_id", "name", "type", "highway", "level"],
        color_options={"Roads": {"color_by": "type", "colors": {"road": "#555", "walkway": "#a16207", "cycleway": "#16a34a"}}},
        overlays=[o(streets[streets.kind == k], color=c, opacity=0.8, outline=dark, width=1.2, label=lab, popup=POP, tooltip=["cid", "name"])
                  for k, lab, c, dark in KINDS if (streets.kind == k).any()] + [
                  o(zones[zones.zone == "pedestrian_realm"], color="#f8c4b4", opacity=0.9, outline="#e8a898", label="Pedestrian realm",
                    popup=["cid", "name", "level", "zone"], tooltip=["cid", "zone"]),
                  o(zones[zones.zone == "travelway"], color="#6b7280", opacity=0.9, outline="#4b5563", label="Travelway",
                    popup=["cid", "name", "level", "zone"], tooltip=["cid", "zone"]),
                  o(buildings, color="#3b82f6", opacity=0.85, outline="#334", label="Buildings",
                    popup=BLD_POPUP, tooltip=["type"])]
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
                 + [o(units, color="#a78bfa", color_col="color", opacity=0.45, outline="#1f2937", width=1.2, label="Spaces",
                      popup=["unit_id", "kind", "section_id", "level"], tooltip=["unit_id", "kind"])] * (len(units) > 0)
                 + [o(pts_, color="#999999", color_col="color", opacity=0.95, outline="#475569", width=0, label="Parts", visible=False,
                      popup=["part_id", "type", "holds", "rule", "road", "road_class", "direction", "lane", "width_m", "length_m", "speed", "surface", "lit", "road_lanes", "oneway",
                              "area_m2", "source", "method", "ref"], tooltip=["type", "direction", "arm"])] * (len(pts_) > 0)
                 + [rs.Overlay(marks[marks["type"] == t], kind="line", placement="over", color=c, width_m=w, dash=dash, label=f"Mark: {t}", visible=False,
                               popup=["unit_id", "type", "arm", "length_m", "source", "method", "ref"], tooltip=["type", "arm"]) for t, c, w, dash in MARKS if (marks["type"] == t).any()]
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
                 + [rs.Overlay(subs, kind="line", placement="over", color="#e6194b", color_col="color", width=5, label="Subsections",
                               popup=["subsection_id", "section_id", "class", "width_m", "oneway", "length_m", "left", "right", "starts_at"],
                               tooltip=["subsection_id", "length_m"])] * (len(subs) > 0)
                 + [rs.Overlay(brk, kind="circle", placement="over", color="#111827", radius=5, label="Subsection breaks",
                               popup=["subsection_id", "starts_at"], tooltip=["subsection_id", "starts_at"])] * (len(brk) > 0)
                 + [rs.Overlay(droads, kind="line", placement="over", color="#0f766e", width=6, label="Dossier roads",
                               popup=[c for c in droads.columns if c != "geometry"], tooltip=["name", "class"])] * (len(droads) > 0)
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
        for iid, sid in con.execute("""SELECT DISTINCT c.intersection_id, s.unit_id FROM space.cut c JOIN space.unit s ON s.kind = 'subsection' AND s.level = c.level
                AND ST_Intersects(ST_Buffer(c.geometry, 0.00001), s.geometry)""").fetchall():
            if iid in newu["inter"]:          # the roads arriving at it: the subsections beyond its cuts (not every space that touches it)
                newu["inter"][iid].setdefault("adj", []).append(sid)
        ways = {}           # (intersection, arm edge) -> its in lanes, rightmost first, and the ways each may go (SUMO's turns, space.turn)
        try:
            for uid, edge, lane, turn in con.execute("SELECT DISTINCT unit_id, from_edge, from_lane, turn FROM space.turn WHERE vehicles IS NULL ORDER BY 1, 2, 3").fetchall():
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
    panel = (PANEL.replace("__PCOL__", json.dumps(PART_COLORS)).replace("__RAISED__", json.dumps(RAISED)).replace("__OBJPOPUP__", json.dumps(OBJ_POPUP)).replace("__BLDPOPUP__", json.dumps(BLD_POPUP)).replace("__NEWU__", json.dumps(newu)).replace("__MARKS__", json.dumps([t for t, *_ in MARKS if len(marks) and (marks["type"] == t).any()])).replace("__TREE__", json.dumps(tree_data(con, epsg)).replace("</", "<\\/"))
             .replace("__LEVELS__", json.dumps(list(range(LEVELS[0], LEVELS[1] + 1)))).replace("__LINKDEF__", json.dumps([{"t": t, "lab": n, "c": c, "d": d} for t, n, c, d in defs]))
             .replace("__KINDS__", json.dumps([{"k": k, "lab": lab, "c": c} for k, lab, c in kinds])).replace("__OBJDEF__", json.dumps([{"g": g, "c": c} for g, c in ogroups])).replace("__OBJCOLORS__", json.dumps({k: v[2] for k, v in OBJ_SHAPES.items()})).replace("__STRIPS__", json.dumps([{"t": t, "lab": lab, "c": c} for t, lab, c, _ in sdefs])).replace("__HAS__", json.dumps(has)).replace("__LEVELBTNS__", "".join(f'<button data-l="{l}">{l}</button>' for l in range(LEVELS[0], LEVELS[1] + 1))))
    open(out, "w").write(m.html.replace("</body>", panel + "</body>"))

