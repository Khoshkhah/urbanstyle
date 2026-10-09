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
PART_COLORS = {"lane circulating": "#4b5260", "ring": "#4b5260", "junction box": "#4b5260", "lane in": "#4b5260", "lane out": "#454c59", "lane forward": "#4b5260", "lane backward": "#454c59",
               "lane both": "#4b5260", "lane": "#4b5260", "shoulder": "#5c6370", "parking": "#64748b", "no parking": "#4b5260",
               "parking lot": "#94a3b8", "carriageway": "#4b5260", "bus lane": "#9b2c2c",
               "cycle lane": "#2f855a", "cycle crossing": "#38a169", "crosswalk": "#4b5260", "island": "#8fbf6f",
               "sidewalk": "#d8d2c6", "furnishing": "#b9a58b", "open": "#e9e4d6"}   # asphalt, paving; crosswalks are asphalt under their zebra bars
SEEN_COLORS = {"parking": "#2563eb", "no parking": "#9333ea", "give way": "#f97316", "stop": "#dc2626", "traffic light": "#ef4444",
               "street light": "#facc15", "bin": "#65a30d", "bench": "#84cc16", "lane arrow": "#06b6d4", "zebra": "#ffffff"}
PHOTOS_PER_SPACE = 6
# painted and built lines, at real size: type, colour, width in metres, dash
MARKS = [("guide line", "#e5e7eb", 0.1, [2, 3]), ("arrow", "#ffffff", 0.15, None), ("kerb", "#9ca3af", 0.2, None), ("centre line", "#ffffff", 0.15, [3, 2]), ("lane line", "#ffffff", 0.12, [3, 3]),
         ("edge line", "#ffffff", 0.12, None), ("stop line", "#ffffff", 0.4, None), ("give-way line", "#ffffff", 0.35, [1, 1]),
         ("zebra", "#ffffff", 0.5, None)]
PANEL = """
<style>#map{left:340px!important}.ov-ctrl{display:none!important}  /* roadstyle's own Layers box: the panel list replaces it */
#us{position:fixed;top:0;left:0;bottom:0;width:340px;overflow:auto;padding:8px;box-sizing:border-box;background:#fafafa;
    border-right:1px solid #ddd;font:13px sans-serif;z-index:5}
#us details{margin-left:14px}#us summary{cursor:pointer;padding:1px 3px;border-radius:3px}
#us summary i{color:#777;font-style:normal;font-size:11px}#us summary.on{background:#dbeafe}
#us summary.leaf{list-style:none;margin-left:-4px}#us>#tree>details{margin-left:0}
#us #chips{margin:6px 0;display:flex;flex-wrap:wrap;gap:4px 10px}#us #chips label{cursor:pointer;white-space:nowrap}#us #chips .sw{display:inline-block;width:12px;height:12px;margin-right:4px;vertical-align:-2px;border:1px solid #0004;border-radius:2px}#us #more{margin:4px 0}#us #more>summary{cursor:pointer;font-weight:600;color:#374151}#us .gh{margin-top:6px}#us #lg{margin:6px 0;font-size:12px;line-height:1.55}#us #lg b{display:block;margin-top:5px}#us #lg label{display:block;cursor:pointer}#us #lg i{color:#777;font-style:normal;font-size:11px}#us #lg .nb b{display:inline;margin:0}#us #lg .nb{margin-top:6px;padding:4px 6px;background:#fff7e0;border:1px solid #f0d890;border-radius:4px;color:#554}#us #lg input{margin:0 5px 0 0;vertical-align:-2px}#us #lg span.sw{display:inline-block;width:11px;height:11px;margin:0 4px 0 0;vertical-align:-1px;border:1px solid #0003}#us #lg span.ci{border-radius:50%}#us #lg span.ln{height:3px;margin-top:4px;vertical-align:2px}#us #jump{margin:4px 0;font-size:12px}#us #jump:empty{display:none}#us #jump{background:#eef6ff;border:1px solid #b6d4fe;border-radius:4px;padding:4px 6px}#us #jump button{margin:0 2px;padding:1px 8px}#us #focus{margin:6px 0;font-size:12px;border:2px solid #7c3aed;border-radius:5px;padding:6px 8px;background:#faf5ff}#us #focus:empty{display:none}#us #focus h4{margin:0 0 4px;font-size:13px}#us #focus table{border-collapse:collapse;width:100%}#us #focus td{padding:1px 4px}#us #focus td:last-child{text-align:right}#us #focus button{margin:4px 0 0;padding:2px 10px}#us #focus .sw{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:-1px}#us #lv button{margin:1px;padding:2px 8px}#us #lv .on{background:#1a73e8;color:#fff}#us #q{width:100%;box-sizing:border-box;margin:6px 0}
</style>
<div id=us><b>urbanstyle</b> &middot; street space by level
<div id=lv>level: __LEVELBTNS__</div>
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
const show={}; GROUPS.forEach(g=>g[1].forEach(r=>show[r[0]]=(r[0].startsWith('c:')&&!HAS.includes('Spaces'))||r[0]==='buildings'));   // with the new spaces (space.unit) the old containers start hidden
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
  // an intersection with a new space in focus: exactly that space (its area, cuts, road pieces, bounding buildings, what stands inside)
  const IX=focused&&!sel.gid&&NEWU.inter[cid]?cid:null;
  // centerlines: hidden in the overview (Street View needs one clicked: focus a street space, or tick them); in focus, the container's own
  // (an intersection shows its own road pieces instead: the Junction roads layer, clipped to it)
  rsFilter(rsQuery(p=>!IX&&p.level===l&&(focused?cs.has(p.container_id):show['r:'+p.type]===true)));
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
  if(HAS.includes('Spaces')){setOv('Spaces',true); rsFilter(rsQuery(p=>p.level===l&&(IX?p.unit_id===IX:ownSec(p.section_id)),'Spaces'),'Spaces')}
  const inside=IX||(focused&&!sel.gid&&HAS.includes('Parts')&&NEWU.sec[cid]);   // a space shown with its parts: its painted lines, not the subsection lines
  ['Subsections','Subsection breaks'].forEach(lab=>{if(HAS.includes(lab)){setOv(lab,!inside); if(!inside)rsFilter(rsQuery(p=>p.level===l&&ownSec(p.section_id),lab),lab)}});
  if(HAS.includes('Cuts')){setOv('Cuts',true); rsFilter(rsQuery(p=>p.level===l&&(IX?p.intersection_id===IX:(!focused||cs.has(p.intersection_id)||[...cs].some(s=>(tree.secarms[s]||[]).includes(p.intersection_id)))),'Cuts'),'Cuts')}
  if(HAS.includes('Junction roads')){const jr=!!IX&&!HAS.includes('Parts');   // with its parts shown, the lanes and markings draw the roads
    setOv('Junction roads',jr); if(jr)rsFilter(rsQuery(p=>p.unit_id===IX,'Junction roads'),'Junction roads')}
  // the inside of the focused space(s): an intersection's parts, or a section's subsections' parts, with their painted lines
  const PU=IX?new Set([IX,...(NEWU.inter[IX].adj||[])]):(focused&&!sel.gid&&NEWU.sec[cid])?new Set(NEWU.sec[cid].map(x=>x[0])):null;   // an intersection with the roads arriving at it
  if(HAS.includes('Parts')){setOv('Parts',!!PU); if(PU){rsFilter(rsQuery(p=>PU.has(p.unit_id),'Parts'),'Parts'); setOv('Spaces',false)}}
  MK.forEach(t=>{const lab='Mark: '+t; setOv(lab,!!PU); if(PU)rsFilter(rsQuery(p=>PU.has(p.unit_id),lab),lab)});
  if(HAS.includes('Mapillary')){setOv('Mapillary',!!PU); if(PU)rsFilter(rsQuery(p=>PU.has(p.unit),'Mapillary'),'Mapillary')}
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
document.getElementById('focus').onclick=e=>{const g=e.target.dataset.gid; if(g)focusGroup(g)};
// the new spaces (space.unit): an intersection's area and how each arm was cut; a section's subsections, one row each
const CUTCOL={'block corners':'#16a34a','one corner':'#f59e0b'}, PCOL=__PCOL__;
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
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&(sel.t==='street'||sel.t==='zone'))focusOff()});
// clicking a street space (or one of its zones) on the map focuses it
// Street View: roadstyle's window follows clicks on a road's centre line only; in a space most clicks land on its parts, lines or
// Mapillary points (overlays). While the window is open such a click moves it too: to the road nearest the spot, looking along it.
let downAt=null; map.on('mousedown',e=>downAt=e.lngLat); map.on('touchstart',e=>downAt=e.lngLat);
function svHere(name){const w=document.querySelector('.rs-svw'); if(!w||w.hidden||!downAt||!window.rsSetStreetViewMarkerAt)return;
  const k=Math.cos(downAt.lat*Math.PI/180), dist=s=>Math.hypot((s.lng-downAt.lng)*k,s.lat-downAt.lat);
  let best=null;   // the snap prefers roads running the way one looks: try four ways, keep the nearest road
  [0,90,180,270].forEach(h=>{rsSetStreetViewMarkerAt(downAt.lng,downAt.lat,h); const s=rsGetStreetViewSpot(); if(s&&s.onRoad&&(!best||dist(s)<dist(best.s)))best={h,s}});
  if(!best)return;
  rsSetStreetViewMarkerAt(downAt.lng,downAt.lat,best.h); const s=rsGetStreetViewSpot();
  const url=`https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${s.lat.toFixed(6)},${s.lng.toFixed(6)}&heading=${Math.round(s.roadHeading||0)}`;
  document.dispatchEvent(new CustomEvent('rs:select',{detail:{sv:true,properties:{name:name||(s.properties||{}).name||'Street View'},streetView:url}}))}
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
(function start(){ if(rsQuery(()=>true,'Buildings').length===0&&tries++<100){setTimeout(start,200);return} apply(); fromHash() })();
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


def object_shapes(con, epsg):
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


def main(db, out):
    con = duckdb.connect(db, read_only=True)
    con.execute("LOAD spatial")
    edges = frame(con, """SELECT ST_AsWKB(geometry) AS geometry, class AS highway, name, level_min AS level, type, container_id,
        CASE WHEN level_src = 'bridge' THEN 'yes' END AS bridge, CASE WHEN level_src = 'tunnel' THEN 'yes' END AS tunnel,
        level_min AS layer, try_cast(source_id AS BIGINT) AS edge_id, coalesce(oneway, false) AS oneway FROM space.element WHERE type <> 'building'""")
    edges["edge_id"] = edges["edge_id"].astype("Int64")
    buildings = frame(con, """SELECT ST_AsWKB(geometry) AS geometry, source_id AS id, name, class, level_min, level_max, level_src
        FROM space.element WHERE type = 'building'""")
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
    shapes = object_shapes(con, epsg_of(con))

    ogroups = [(g, c) for g, c in (("furniture", "#4f46e5"), ("vegetation", "#65a30d"), ("transit", "#0891b2"), ("crossing", "#eab308"),
                                   ("kerb", "#6b7280"), ("access", "#db2777"), ("barrier", "#78350f")) if (objects.grp == g).any()]
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
            CASE how WHEN 'block corners' THEN '#16a34a' WHEN 'one corner' THEN '#f59e0b' ELSE '#6b7280' END AS color FROM space.cut""")
        ep = epsg_of(con)
        jroads = frame(con, """SELECT ST_AsWKB(ST_CollectionExtract(ST_Intersection(e.geometry, u.geometry), 2)) AS geometry, u.unit_id, e.level_min AS level,
            e.name, e.class FROM space.element e JOIN space.unit u ON u.kind IN ('intersection', 'roundabout') AND u.level = e.level_min AND ST_Intersects(e.geometry, u.geometry)
            WHERE e.type = 'road'""")
        jroads = jroads[~jroads.geometry.is_empty]
        try:    # the inside of each space (parts.py): parts, marks, widths
            pts_ = frame(con, f"""SELECT ST_AsWKB(geometry) AS geometry, unit_id, part_id, level, type, coalesce(arm, '') AS arm,
                coalesce(direction, '') AS direction, lane, width_m, source,
                round(ST_Area(ST_Transform(geometry, 'EPSG:4326', '{ep}', always_xy := true)), 1) AS area_m2 FROM space.part""")
            pts_["color"] = [PART_COLORS.get(f"{t} {d}".strip(), PART_COLORS.get(t, "#999999")) for t, d in zip(pts_["type"], pts_["direction"])]
            marks = frame(con, "SELECT ST_AsWKB(geometry) AS geometry, unit_id, level, type, coalesce(arm, '') AS arm, length_m FROM space.mark")
            uwidths = con.execute("SELECT unit_id, edge, arm, total_m, carriageway_m, left_m, right_m, lanes_in, lanes_out, source FROM space.width").fetchall()
        except duckdb.CatalogException:
            pts_, marks, uwidths = pd.DataFrame({"type": []}), pd.DataFrame({"type": []}), []
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
        unit_of, ubld, ubounds = {}, [], {}
    try:        # Mapillary (mapillary.py): what its photos saw, and the photos nearest each space (CC BY-SA, © Mapillary contributors)
        seen = frame(con, """SELECT ST_AsWKB(any_value(o.geometry)) AS geometry, o.feature_id, any_value(o.class) AS class, any_value(o.grp) AS grp,
            any_value(o.last_seen)::DATE::VARCHAR AS last_seen, coalesce(min(u.unit_id), '') AS unit FROM space.observed o
            LEFT JOIN space.unit u ON ST_Intersects(u.geometry, ST_Buffer(o.geometry, 0.00003)) GROUP BY o.feature_id""")
        seen["color"] = seen["grp"].map(SEEN_COLORS).fillna("#f59e0b")
        photos = {}
        for uid, pid, when, pano in con.execute("""SELECT u.unit_id, p.photo_id, p.captured::DATE::VARCHAR, p.is_pano FROM space.unit u
                JOIN space.photo p ON ST_Intersects(u.geometry, p.geometry) ORDER BY u.unit_id, p.captured DESC""").fetchall():
            if len(photos.setdefault(uid, [])) < PHOTOS_PER_SPACE:
                photos[uid].append([pid, when, bool(pano)])
    except duckdb.CatalogException:
        seen, photos = pd.DataFrame({"grp": []}), {}
    shapes["unit"] = shapes["object_id"].map(unit_of)
    objects["unit"] = objects["object_id"].map(unit_of)
    has = [lab for lab, df in (("Track", track), ("Rail", rails), ("Station", stations), ("Objects", shapes), ("Spaces", units), ("Parts", pts_), ("Cuts", cuts), ("Junction roads", jroads), ("Subsections", subs),
                               ("Subsection breaks", brk), ("Mapillary", seen)) if len(df)]   # overlays present in this area
    links = frame(con, "SELECT ST_AsWKB(geometry) AS geometry, node_id, level_a, level_b, type, assumed, station_id, match, round(dist_m) AS dist_m FROM space.link")
    # type, name shown, colour, what it is. Colours differ from every other layer's on purpose.
    defs = [("ramp", "Ramp", "#f59e0b", "a bridge or tunnel is involved"), ("stairs", "Stairs", "#0f172a", "steps join two levels"),
            ("elevator", "Elevator", "#06b6d4", "a lift"), ("entrance", "Station entrance", "#ef4444", "tied to its station (by name, else the nearest); level -1 is assumed only when no station is found"),
            ("connection", "Other level change", "#ec4899", "ways on different layers meet, no ramp, stairs or lift tagged")]
    defs = [d for d in defs if (links["type"] == d[0]).any()]
    o = lambda g, **kw: rs.Overlay(g, placement="under", **kw)
    m = rs.render_edges(
        edges, palette="mono", basemap="voyager", name="urbanstyle",
        street_view_key=os.environ.get("GOOGLE_MAPS_KEY"),   # Street View's linked panorama (the key is written into the page: restrict it in Google Cloud) settings={"config": {"fill_opacity": 0.35, "casing_opacity": 0.2}}, road_popup=["edge_id", "container_id", "name", "type", "highway", "level"],
        color_options={"Roads": {"color_by": "type", "colors": {"road": "#555", "walkway": "#a16207", "cycleway": "#16a34a"}}},
        overlays=[o(streets[streets.kind == k], color=c, opacity=0.8, outline=dark, width=1.2, label=lab, popup=POP, tooltip=["cid", "name"])
                  for k, lab, c, dark in KINDS if (streets.kind == k).any()] + [
                  o(zones[zones.zone == "pedestrian_realm"], color="#f8c4b4", opacity=0.9, outline="#e8a898", label="Pedestrian realm",
                    popup=["cid", "name", "level", "zone"], tooltip=["cid", "zone"]),
                  o(zones[zones.zone == "travelway"], color="#6b7280", opacity=0.9, outline="#4b5563", label="Travelway",
                    popup=["cid", "name", "level", "zone"], tooltip=["cid", "zone"]),
                  o(buildings, color="#3b82f6", opacity=0.85, outline="#334", label="Buildings",
                    popup=["id", "name", "class", "level_min", "level_max", "level_src"], tooltip=["id", "name"])]
                 + [o(track, color="#f0abfc", opacity=0.7, outline="#c026d3", label="Track", popup=["cid", "name", "level", "zone"],
                      tooltip=["cid", "zone"])] * (len(track) > 0)
                 + [o(strips[strips["type"] == t], color=c, opacity=0.97, outline=dark, width=0.4, label=f"Strip: {t}", popup=["cid", "type", "side", "width_m", "source", "level"],
                      tooltip=["cid", "type"]) for t, lab, c, dark in sdefs]
                 + [rs.Overlay(rails, kind="line", placement="over", color="#c026d3", width=3, label="Rail", popup=["id", "name", "class", "level"],
                               tooltip=["id", "name"])] * (len(rails) > 0)
                 + [o(shapes, color="#888888", opacity=0.92, outline="#374151", width=0.4, label="Objects", popup=["object_id", "class", "cid", "level"], tooltip=["class", "object_id"])] * (len(shapes) > 0)
                 + [rs.Overlay(stations, kind="circle", placement="over", color="#0d9488", radius=9, label="Station",
                               popup=["id", "name", "kind", "level"], tooltip=["id", "name"])] * (len(stations) > 0)
                 + [rs.Overlay(objects[objects.grp == g], kind="circle", placement="over", color=c, radius=4, label=f"Objects: {g}",
                               popup=["object_id", "class", "cid", "zone", "level", "name", "attrs", "near_m"], tooltip=["class", "object_id"])
                    for g, c in ogroups]
                 + [rs.Overlay(links[links["type"] == t], kind="circle", placement="over", color=c, radius=6, label=f"Link: {name}",
                               popup=["node_id", "type", "level_a", "level_b", "assumed", "station_id", "match", "dist_m"], tooltip=["node_id", "type"]) for t, name, c, _ in defs]
                 + [o(units, color="#a78bfa", color_col="color", opacity=0.45, outline="#1f2937", width=1.2, label="Spaces",
                      popup=["unit_id", "kind", "section_id", "level"], tooltip=["unit_id", "kind"])] * (len(units) > 0)
                 + [o(pts_, color="#999999", color_col="color", opacity=0.95, outline="#475569", width=0, label="Parts", visible=False,
                      popup=["part_id", "type", "arm", "direction", "lane", "width_m", "area_m2", "source"], tooltip=["type", "direction", "arm"])] * (len(pts_) > 0)
                 + [rs.Overlay(marks[marks["type"] == t], kind="line", placement="over", color=c, width_m=w, dash=dash, label=f"Mark: {t}", visible=False,
                               popup=["unit_id", "type", "arm", "length_m"], tooltip=["type", "arm"]) for t, c, w, dash in MARKS if (marks["type"] == t).any()]
                 + [rs.Overlay(seen, kind="circle", placement="over", color="#f59e0b", color_col="color", radius=5, label="Mapillary", visible=False,
                               popup=["feature_id", "grp", "class", "last_seen", "unit"], tooltip=["grp", "class"])] * (len(seen) > 0)
                 + [rs.Overlay(jroads, kind="line", placement="over", color="#374151", width=7, label="Junction roads", visible=False,
                               popup=["unit_id", "name", "class"], tooltip=["name", "class"])] * (len(jroads) > 0)
                 + [rs.Overlay(cuts, kind="line", placement="over", color="#6b7280", color_col="color", width=4, label="Cuts",
                               popup=["intersection_id", "edge_id", "how", "length_m"], tooltip=["how", "length_m"])] * (len(cuts) > 0)
                 + [rs.Overlay(subs, kind="line", placement="over", color="#e6194b", color_col="color", width=5, label="Subsections",
                               popup=["subsection_id", "section_id", "class", "width_m", "oneway", "length_m", "left", "right", "starts_at"],
                               tooltip=["subsection_id", "length_m"])] * (len(subs) > 0)
                 + [rs.Overlay(brk, kind="circle", placement="over", color="#111827", radius=5, label="Subsection breaks",
                               popup=["subsection_id", "starts_at"], tooltip=["subsection_id", "starts_at"])] * (len(brk) > 0))
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
            for uid, edge, lane, turn in con.execute("SELECT DISTINCT unit_id, from_edge, from_lane, turn FROM space.turn ORDER BY 1, 2, 3").fetchall():
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
    panel = (PANEL.replace("__PCOL__", json.dumps(PART_COLORS)).replace("__NEWU__", json.dumps(newu)).replace("__MARKS__", json.dumps([t for t, *_ in MARKS if len(marks) and (marks["type"] == t).any()])).replace("__TREE__", json.dumps(tree_data(con, epsg)).replace("</", "<\\/"))
             .replace("__LEVELS__", json.dumps(list(range(LEVELS[0], LEVELS[1] + 1)))).replace("__LINKDEF__", json.dumps([{"t": t, "lab": n, "c": c, "d": d} for t, n, c, d in defs]))
             .replace("__KINDS__", json.dumps([{"k": k, "lab": lab, "c": c} for k, lab, c in kinds])).replace("__OBJDEF__", json.dumps([{"g": g, "c": c} for g, c in ogroups])).replace("__OBJCOLORS__", json.dumps({k: v[2] for k, v in OBJ_SHAPES.items()})).replace("__STRIPS__", json.dumps([{"t": t, "lab": lab, "c": c} for t, lab, c, _ in sdefs])).replace("__HAS__", json.dumps(has)).replace("__LEVELBTNS__", "".join(f'<button data-l="{l}">{l}</button>' for l in range(LEVELS[0], LEVELS[1] + 1))))
    open(out, "w").write(m.html.replace("</body>", panel + "</body>"))

