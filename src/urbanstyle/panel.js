// urbanstyle's panel (docs/design/dashboard.md): Find, Filter, Ask, Layers, the levels, the cards. The same file for every area: the
// server gives it (urbanstyle serve) or it lies beside the page (urbanstyle publish). It makes its own HTML, sets the map's first look and
// then lifts the page's veil. Every name is inside one function, so nothing meets roadstyle's globals.
(()=>{
const B=document.body, resize=()=>setTimeout(()=>M()&&M().resize(),0);
B.classList.add('xp');
B.insertAdjacentHTML('beforeend',`<button id=xpfold title="hide the panel">&laquo;</button>
<div id=xp>
  <header><b>urbanstyle <span id=xparea style="font-weight:400;color:#64748b"></span></b></header>
  <div id=xpview>level <span id=xplk></span><span class=sp></span><button id=xp2d>2D</button><button id=xp3d>3D</button></div>
  <details id=xpchecks><summary>Checks</summary><div id=xpchk></div></details>
  <details id=xplayers><summary>Layers <span class=xp3dl>(2D only)</span></summary><h5>Options</h5><div id=xpopts><label title="3D view only: each building at most 3 m high, so the streets are not hidden (also while a street object is selected)"><input type=checkbox id=lowbld> low buildings</label><label title="2D is a map: roads as lines, objects as dots. Tick to draw the real-size road surface in 2D too (lanes, crosswalks, sidewalks, markings), as 3D always does"><input type=checkbox id=allparts> road surface in 2D</label><label title="Mapillary's detections, for validation only: their positions are too rough to make an object. Green: it confirms a surveyed or mapped object; orange: nothing confirms it"><input type=checkbox id=mlybox> Mapillary detections (validation)</label></div><div id=xplys></div></details>
  <div id=xptabs><button data-t=s class=on>Find</button><button data-t=f>Filter</button><button data-t=a>Ask</button></div>
  <div class="xptab on" id=xp-s><div class=xprow><input id=xpq style="flex:1" placeholder="a street, a type, an OSM way, or an id (s0-…, i0-…)"><button class=xpgo id=xpqgo>Find</button></div>
    <div id=xpbr title="browse: a group lists its things, one thing is selected"></div></div>
  <div class=xptab id=xp-f>
    <div class=xprow><select id=xplayer style="flex:1"></select></div>
    <div id=xpconds></div>
    <div class=xprow><button class=xplink id=xpadd>+ condition</button><label style="flex:1;text-align:right"><input type=checkbox id=xpinview> only in the map view</label></div>
    <div class=xprow><button class=xpgo id=xpfgo>Show</button></div>
  </div>
  <div class=xptab id=xp-a>
    <div id=xpchat></div>
    <div id=xpexs></div>
    <div class=xprow style="justify-content:flex-end"><button class=xplink id=xpnew title="forget the questions so far: the next one starts afresh">New conversation</button></div>
    <div class=xprow><textarea id=xpask rows=2 style="flex:1;resize:vertical" placeholder="Ask about the street, e.g. where are the sidewalks narrower than 1.8 m?"></textarea><button class=xpgo id=xpaskgo>Ask</button></div>
  </div>
  <div id=xpres><div id=xpcard></div><div id=xpsum style="color:#64748b;font-weight:400">Find (type, or browse the tree), filter or ask: the results show here (orange) and on the map.</div><div id=xpkinds></div>
    <div class=xprow id=xpacts style="display:none"><button class=xplink id=xpcsv>CSV</button><button class=xplink id=xpgeo>GeoJSON</button><button class=xplink id=xpclr>Clear</button><button class=xplink id=xpfocus title="3D: the things of the list in their own colors, everything else faint">Focus</button></div>
    <div id=xplist></div></div>
</div>`);
const M=()=>typeof map!=="undefined"?map:null;
// (the Ask conversation: its id and its chat kept in this browser, so a reload goes on with it; the server keeps its memory)
const store={get:k=>{try{return localStorage.getItem(k)}catch(e){return null}},set:(k,v)=>{try{localStorage.setItem(k,v)}catch(e){}}};
const newId=()=>Math.random().toString(36).slice(2);
let session=store.get('xp-session')||newId(); store.set('xp-session',session);
const $=id=>document.getElementById(id), COL='#ff9100', SRC='xp-res';
let meta=null, last=null, offline=false;   // (offline: no server, the page as plain files)
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const km=m=>m>=1000?(m/1000).toFixed(2)+' km':Math.round(m)+' m';
// the results on the map: one GeoJSON source, a fill, a line and a dot layer in orange (one thing selected: deep purple), in 2D and in 3D, on top
function layers(){const m=M(); if(!m||!m.isStyleLoaded||!m.isStyleLoaded())return false;
  if(!m.getSource(SRC))m.addSource(SRC,{type:'geojson',data:last||{type:'FeatureCollection',features:[]}});
  const add=(id,spec)=>{if(!m.getLayer(id))m.addLayer({id,source:SRC,...spec})};
  add('xp-fill',{type:'fill',filter:['==',['geometry-type'],'Polygon'],paint:{'fill-color':COL,'fill-opacity':0.35}});     // (2D only: vis)
  add('xp-line',{type:'line',paint:{'line-color':COL,'line-width':3}});
  add('xp-pt',{type:'circle',filter:['==',['geometry-type'],'Point'],paint:{'circle-color':COL,'circle-radius':6,'circle-stroke-color':'#fff','circle-stroke-width':2}});
  top(); vis(); return true}
// the results above every other layer but the bridge's (3D adds its ground layers later, on top; the bridge keeps the top: brAdd);
// style._order, not getStyle(): getStyle leaves out custom layers such as the bridge
const XP=['xp-fill','xp-line','xp-pt'];
function top(){const m=M(), ids=[...m.style._order], i=Math.min(...XP.map(x=>ids.indexOf(x)).filter(k=>k>=0));
  if(!ids.slice(i).some(x=>!XP.includes(x)&&!x.startsWith('br3d-')))return;
  [...XP,'xp-hov-fill','xp-hov-line','xp-hov-pt','xp-sel-fill','xp-sel-line','xp-sel-pt'].forEach(x=>m.getLayer(x)&&m.moveLayer(x)); ids.filter(x=>x.startsWith('br3d-')).forEach(x=>m.moveLayer(x))}
// 2D and 3D apart (Kaveh, 2026-10-13: "the circle markers and footprints belong to 2D"): 2D draws the results as shapes and dots; 3D
// draws none of them and colours the 3D objects themselves (mark3d: buildings, street parts, ground, car parks, street objects; brMark)
const SELF3D=['Street parts','Buildings','Ground','Car parks','Street objects'];
function vis(){const m=M(); if(!m)return; const d3=typeof in3d!=='undefined'&&in3d;
  XP.forEach(x=>{if(m.getLayer(x))m.setLayoutProperty(x,'visibility',d3?'none':'visible')})}
// (only the newest results: an older list that waited for a busy map came late and took the place of the new one, 2026-10-13: the
// whole bridge orange after "Axis a1", and a lane's row selected a crosswalk)
let mapSeq=0;
function onMap(fc,my){if(my===undefined)my=++mapSeq; else if(my!==mapSeq)return; last=fc;
  if(!layers())return setTimeout(()=>onMap(fc,my),500); M().getSource(SRC).setData(fc); vis();
  if(window.mark3d)window.mark3d(fc.features.filter(f=>SELF3D.includes(f.properties._layer)).map(f=>f.properties._id));
  if(window.brMark)window.brMark(fc.features.filter(f=>f.properties._layer==='Bridge parts').map(f=>f.properties._id))}
function bounds(fs){let b=[180,90,-180,-90]; const walk=c=>typeof c[0]==='number'?(b=[Math.min(b[0],c[0]),Math.min(b[1],c[1]),Math.max(b[2],c[0]),Math.max(b[3],c[1])]):c.forEach(walk);
  fs.forEach(f=>f.geometry&&walk(f.geometry.coordinates)); return b[0]<=b[2]?[[b[0],b[1]],[b[2],b[3]]]:null}
function fly(fs){const b=bounds(fs); if(!b)return;
  // one street object in 3D: the camera looks along the street it stands in, so the buildings stand at the sides, not in front of it
  const p=fs.length===1&&fs[0].properties, at={lng:(b[0][0]+b[1][0])/2,lat:(b[0][1]+b[1][1])/2},
    r=p&&p._layer==='Street objects'&&typeof in3d!=='undefined'&&in3d&&window.nearRoad&&nearRoad(at);
  if(r){const now=M().getBearing(), h=Math.abs(((r.h-now+540)%360)-180)<=90?r.h:(r.h+180)%360;      // (of the two ways along it, the nearer)
    return M().flyTo({center:[at.lng,at.lat],zoom:19.5,pitch:60,bearing:h,duration:900})}
  M().fitBounds(b,{padding:60,maxZoom:19,duration:700})}     // (the map starts beside the panel)
// the one thing selected: deep purple where it stands (2D: the map's own selection is roadstyle's; 3D: pick3d; the bridge: brPick) and its
// card at the top of the results: its fields, and the spaces and parts it leads to (a click on one: select it, or list it)
const shut=()=>{document.querySelectorAll('.maplibregl-popup:not(.u3d-tip)').forEach(x=>x.remove());
  $('xpcard').classList.remove('on');
  if(window.brDeselect)window.brDeselect(); if(window.pick3d)window.pick3d(null); if(focusU)focus(null); selSrc()};
const pick=p=>{if(p._layer==='Bridge parts'){if(window.brPick)window.brPick(p._id)}
  else if(p._layer==='Street spaces'||p._layer==='Blocks')focus(p._id,p._layer); else if(window.pick3d)window.pick3d(p._id,p._layer==='Street objects')};
// a street space selected: in focus in 3D, its parts and painted lines as they are, all else faint (the bridge too, for a space on the
// ground); the panel's card closed: all back
// the focus in 3D: what keeps its colours, all else faint. A selected street space or block (focusU, focusF: from the server), else a
// group from Browse (groupF: its results); selecting one thing inside a group keeps the group's focus
let focusU=null, focusF=null, groupF=null;
function focus(u,layer){if((u||null)!==focusU){focusF=null; if(u)get(`/api/focus?layer=${encodeURIComponent(layer||'Street spaces')}&id=${encodeURIComponent(u)}`)
    .then(f=>{if(focusU===u){focusF=f; paintFocus()}})}
  focusU=u||null; paintFocus()}
// (an empty list is no focus: the last tick box cleared left all faint, 2026-10-13)
function specOf(fc){if(!(fc.features||[]).length)return null; const f={units:[],parts:[],ground:[],blds:[],lots:[],objs:[],bridge:0},
    K={'Street spaces':'units','Street parts':'parts','Ground':'ground','Buildings':'blds','Car parks':'lots','Street objects':'objs'};
  (fc.features||[]).forEach(x=>{const p=x.properties, k=K[p._layer]; if(k)f[k].push(p._id); if(p._layer==='Bridge parts')f.bridge++}); return f}
const eff=()=>focusU?(focusF||{units:[]}):groupF;
function paintFocus(){const F=eff(); if(window.focus3d)window.focus3d(F); const m=M(); if(!m)return;
  applyLooks()}
// (2D: the selected one in deep purple over the orange results: its own source)
function selSrc(f){const m=M(); if(!m)return; if(!m.isStyleLoaded())return setTimeout(()=>selSrc(f),200); const fc={type:'FeatureCollection',features:f?[f]:[]};
  if(!m.getSource('xp-sel')){m.addSource('xp-sel',{type:'geojson',data:fc});
    m.addLayer({id:'xp-sel-fill',source:'xp-sel',type:'fill',filter:['==',['geometry-type'],'Polygon'],paint:{'fill-color':'#7c4dff','fill-opacity':0.45}});
    m.addLayer({id:'xp-sel-line',source:'xp-sel',type:'line',paint:{'line-color':'#7c4dff','line-width':4}});
    m.addLayer({id:'xp-sel-pt',source:'xp-sel',type:'circle',filter:['==',['geometry-type'],'Point'],paint:{'circle-color':'#7c4dff','circle-radius':8,'circle-stroke-color':'#fff','circle-stroke-width':2}})}
  else m.getSource('xp-sel').setData(fc);
  const d3=typeof in3d!=='undefined'&&in3d; ['xp-sel-fill','xp-sel-line','xp-sel-pt'].forEach(x=>m.getLayer(x)&&m.setLayoutProperty(x,'visibility',d3?'none':'visible'))}
let selF=null;
// select one thing: deep purple and its card (all its fields); the same in 2D and 3D, from the panel or from a click on the map (at:
// where it was clicked; from the panel the map flies to it). No popup: it held only the name and the id, and it covered the thing; a
// hidden panel opens for the card (Kaveh, 2026-10-13). The card's ×, Esc or a second click deselects
function select(f,at){shut(); if(!f)return; selF=f; const p=f.properties; pick(p); selSrc(f); if(!at)fly([f]); card(f);
  if(B.classList.contains('xp-off'))$('xpfold').click()}
// a click on the map in 3D (the 3D page's own handlers ask first: xpOnPick): its layer and id, then select as above
const PICK3D={'u3d-furn':['Street objects','refs','id'],'u3d-bld':['Buildings','id','source_id'],'u3d-gnd':['Ground','ground_id','ground_id'],
  'u3d-lot':['Car parks','id','lot_id'],'u3d-ground':['Street parts','part_id','part_id'],'u3d-raised':['Street parts','part_id','part_id'],
  bridge:['Bridge parts','id','id']};
[-5,-4,-3,-2,-1].forEach(l=>PICK3D['u3d-tun'+l]=['Street parts','part_id','part_id']); [1,2,3,4,5].forEach(l=>PICK3D['u3d-deck'+l]=['Street parts','part_id','part_id']);
window.xpOnPick=(lid,p,e)=>{if(offline)return false; const at=e&&e.lngLat?[e.lngLat.lng,e.lngLat.lat]:null;
  // (a kerb: no table of its own on the server; its fields as the 3D page has them, in the card, not a popup: Kaveh, 2026-10-14)
  if(lid==='u3d-kerb'&&p&&p.kerb_id!=null){select({type:'Feature',geometry:null,properties:{...p,_layer:'Kerbs',_label:'kerb',_id:p.kerb_id}},at); return true}
  const k=PICK3D[lid]; if(!k||!p||p[k[1]]==null||!meta)return false;
  post('/api/query',{layer:k[0],where:[{field:k[2],op:'=',value:String(p[k[1]])}]}).then(fc=>{if(fc.features&&fc.features[0])select(fc.features[0],at)});
  return true};
function card(f){const p=f.properties, rows=Object.entries(p).filter(([k,v])=>!k.startsWith('_')&&v!==null&&v!==''&&k!=='fields')
    .map(([k,v])=>`<tr><td>${esc(k)}</td><td>${esc(String(v).slice(0,160))}</td></tr>`).join('');
  const go=[];
  if(p.unit_id&&p._layer!=='Street spaces')go.push(`<button data-sel="Street spaces|unit_id|${esc(p.unit_id)}">its space ${esc(p.unit_id)}</button>`);
  if(p._layer==='Street spaces')go.push(`<button data-res="Street parts|unit_id|${esc(p._id)}">its parts</button>`);
  if(p._layer==='Street spaces'&&p.section_id)go.push(`<button data-res="Street spaces|section_id|${esc(p.section_id)}">its section</button>`);
  if(p._layer==='Bridge parts'&&p.axis)go.push(`<button data-res="Bridge parts|axis|${esc(p.axis)}">all of axis ${esc(p.axis)}</button>`);
  if(p._layer==='Street objects'&&p.class)go.push(`<button data-res="Street objects|class|${esc(p.class)}">all ${esc(String(p.class).split('.').pop().replace(/_/g,' '))}</button>`);
  $('xpcard').innerHTML=`<div class=h><b>${esc(p._label)}</b><small>${esc(p._layer)}</small><button title="deselect">&times;</button></div>`+
    `<table>${rows}</table>`+(go.length?`<div class=go>${go.join('')}</div>`:'');
  $('xpcard').classList.add('on'); $('xpres').scrollTop=0}
$('xpcard').onclick=e=>{if(e.target.matches('.h button')){shut(); return}
  const b=e.target.closest('button'); if(!b)return; const [layer,field,value]=(b.dataset.sel||b.dataset.res||'').split('|'); if(!layer)return;
  (b.dataset.sel?post:(u,x)=>latest(post(u,x)))('/api/query',{layer,where:[{field,op:'=',value}]}).then(fc=>{if(b.dataset.sel){if(fc.features[0])select(fc.features[0])}
    else{show(fc,b.textContent); if(selF)card(selF)}}).catch(stale)};
// one rule for every list, from any tab (Kaveh, 2026-10-13): its things are orange and all else keeps its colors. Focus (the list's
// things in their own colors, all else faint) only with the list's Focus button, or for one selected space or block (focus())
let listSpec=null;
function listFocus(on){groupF=on&&listSpec?listSpec:null; $('xpfocus').classList.toggle('on',!!groupF); paintFocus();
  // (street spaces in focus: also the buildings that frame them and the objects that stand in them, from the server)
  const g=groupF; if(g&&g.units.length&&!g.more)post('/api/focus',{layer:'Street spaces',ids:g.units}).then(f=>{if(groupF!==g||!f)return;
    g.more=1; g.blds=[...new Set([...g.blds,...(f.blds||[])])]; g.objs=[...new Set([...g.objs,...(f.objs||[])])]; paintFocus()})}
function show(fc,title){
  if(fc.error){$('xpsum').textContent='Error: '+fc.error; return}
  listSpec=specOf(fc); listFocus(false);
  onMap(fc); const n=fc.total, s=fc.features.length;
  $('xpsum').style.cssText=''; $('xpsum').textContent=(title?title+': ':'')+n+(n===1?' thing':' things')+(s<n?` (first ${s} shown)`:'')+
    (fc.length_m?' · '+km(fc.length_m):'')+(fc.area_m2?' · '+Math.round(fc.area_m2).toLocaleString()+' m²':'');
  $('xpkinds').innerHTML=(fc.kinds||[]).slice(0,12).map(([k,v])=>`<span>${esc(k||'other')} ${v}</span>`).join('');
  $('xpacts').style.display=s?'flex':'none';
  $('xplist').innerHTML=fc.features.slice(0,300).map((f,i)=>`<div data-i=${i}>${esc(f.properties._label)}<small>${esc(f.properties._layer)} · ${esc(f.properties._id??'')}</small></div>`).join('');
  if(s)fly(fc.features)}
$('xplist').onclick=e=>{const d=e.target.closest('[data-i]'); if(!d||!last)return; const f=last.features[+d.dataset.i];
  if(f&&f.properties._check){const [x,y]=f.geometry.coordinates; goPlace(x,y); return}      // (a check's place: the marker and the thing there)
  select(f)};
// (on a web site with no server, the page's own /api/: XP_STATIC, urbanstyle publish)
const S=window.XP_STATIC;
// the checks that do not pass (urban.check, `urbanstyle check`): each with its places as links that move the map there
function checksBox(cs){const box=$('xpchecks'); if(!cs.length){box.style.display='none'; return}
  const nf=cs.filter(c=>c.status==='fail').length; box.querySelector('summary').textContent=`Checks: ${nf} fail, ${cs.length-nf} info`;
  $('xpchk').innerHTML=cs.map((c,k)=>`<div class="xpck ${c.status}" data-k=${k} title="click: every place of this check in the result list"><b>${esc(c.id)}</b> ${esc(c.status)} ${c.count}<small>${esc(c.what)}</small>`+
    c.at.map((p,k)=>`<button class=xplink data-at="${p[0]},${p[1]}">${k+1}</button>`).join('')+'</div>').join('');
  // a place of a fault: the map flies there, a red marker stays on the exact point, and the thing at it is selected with its card
  // (Kaveh, 2026-10-17: "it only zooms on the issue location without selecting it, so it is hard to find what is the exact issue")
  // a click on a check (its id or its text): every place of it in the result list, one row each (Kaveh, 2026-10-17: "put them into
  // selected list, every issue when click on it"); a row, like a place's button, goes to that place
  $('xpchk').onclick=e=>{const a=e.target.dataset.at;
    if(a){const [x,y]=a.split(',').map(Number); $('xpchk').querySelectorAll('button.on').forEach(b=>b.classList.remove('on'));
      e.target.classList.add('on'); goPlace(x,y); return}
    const row=e.target.closest('.xpck'); if(!row)return; const c=cs[+row.dataset.k]; if(!c||!c.at.length)return;
    show({type:'FeatureCollection',total:c.count,features:c.at.map((p,k)=>({type:'Feature',geometry:{type:'Point',coordinates:p},
      properties:{_label:`${c.id} place ${k+1}`,_layer:`Check ${c.id}`,_id:`${p[0].toFixed(6)},${p[1].toFixed(6)}`,_check:c.id}}))},`${c.id} ${c.what}`)}}
// a place of a fault: the map flies there, a red marker stays on the exact point, and the thing at it is selected with its card
// (Kaveh, 2026-10-17: "it only zooms on the issue location without selecting it, so it is hard to find what is the exact issue")
function goPlace(x,y){const m=M(); if(window.xpCheckPin)window.xpCheckPin.remove();
  if(typeof maplibregl!=='undefined')window.xpCheckPin=new maplibregl.Marker({color:'#dc2626'}).setLngLat([x,y]).addTo(m);
  m.once('moveend',()=>setTimeout(()=>{if(is3d())return; const pt=m.project([x,y]); noXPhit=true; try{m.fire('click',{point:pt,lngLat:{lng:x,lat:y},originalEvent:{}})}finally{noXPhit=false}},300));
  m.flyTo({center:[x,y],zoom:19.5,duration:800})}
const get=u=>S?S.api(u):fetch(u).then(r=>r.json()), post=(u,b)=>S?S.api(u,b):fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}).then(r=>r.json());
// (a result list from the newest request only: a slow answer to an older one is dropped)
let rq=0; const latest=pr=>{const n=++rq; return pr.then(r=>{if(n!==rq)throw 'stale'; return r})}, stale=e=>{if(e!=='stale')throw e};
const wait=t=>{$('xpsum').innerHTML=`<span class=xpwait>${t}</span>`; $('xpkinds').innerHTML=''; $('xplist').innerHTML=''};
// search
// search; an exact id (s0-…, i0-…, a part's or an object's id) goes straight to that thing: selected, its card open
const find=()=>{const q=$('xpq').value.trim(); if(!q)return; wait('Searching...'); latest(get('/api/search?q='+encodeURIComponent(q))).then(fc=>{
  show(fc,'“'+q+'”'); const ORDER=['Street spaces','Street parts','Street objects','Buildings','Bridge parts','Car parks','Ground','Surfaces','Blocks'];
  const hit=(fc.features||[]).filter(f=>String(f.properties._id)===q&&ORDER.includes(f.properties._layer))      // (a painted line carries its space's id)
    .sort((a,b)=>ORDER.indexOf(a.properties._layer)-ORDER.indexOf(b.properties._layer))[0]; if(hit)select(hit)}).catch(stale)};
$('xpqgo').onclick=find; window.xpFind=q=>{$('xpq').value=q; find()}; $('xpq').onkeydown=e=>{if(e.key==='Enter')find()};
// filter: one layer, conditions on its fields
const ops={number:['>=','<=','=','!='],choice:['=','!=','contains'],text:['contains','=','!=']};
function cond(){const L=meta.layers[$('xplayer').value]; if(!L)return; const d=document.createElement('div'); d.className='xprow';
  d.innerHTML=`<select class=xpfield>${L.fields.map(f=>`<option>${esc(f.name)}</option>`).join('')}</select><select class=xpop></select><span class=xpval style="display:flex"></span><button class=xplink title=remove>&times;</button>`;
  const fld=d.querySelector('.xpfield'), op=d.querySelector('.xpop'), val=d.querySelector('.xpval');
  const set=()=>{const f=L.fields.find(x=>x.name===fld.value); op.innerHTML=ops[f.kind].map(o=>`<option>${o}</option>`).join('');
    val.innerHTML=f.kind==='choice'?`<select style="flex:1;width:100%">${f.values.map(([v,n])=>`<option value="${esc(v)}">${esc(v)} (${n})</option>`).join('')}</select>`
      :`<input style="flex:1;width:100%" ${f.kind==='number'?`type=number step=any placeholder="${f.min} – ${f.max}"`:''}>`};
  fld.onchange=set; set(); d.querySelector('button').onclick=()=>d.remove(); $('xpconds').appendChild(d)}
$('xplayer').onchange=()=>{$('xpconds').innerHTML=''; cond()}; $('xpadd').onclick=cond;
$('xpfgo').onclick=()=>{const where=[...$('xpconds').children].map(d=>({field:d.querySelector('.xpfield').value,op:d.querySelector('.xpop').value,
    value:(d.querySelector('.xpval select')||d.querySelector('.xpval input')).value})).filter(w=>w.value!=='');
  let bbox=null; if($('xpinview').checked){const b=M().getBounds(); bbox=[b.getWest(),b.getSouth(),b.getEast(),b.getNorth()]}
  wait('Filtering...'); latest(post('/api/query',{layer:$('xplayer').value,where,bbox})).then(fc=>show(fc,$('xplayer').value)).catch(stale)};
// ask: the AI agent answers from the tables, shows what it found and the queries it used
const EX=['Where are the sidewalks narrower than 1.8 m?','How much of Granville Street is for cars, and how much for people?',
  'Which crossings are not marked?','How many street lights are on the bridge?','Which parts of the bridge have chosen widths, not mapped ones?'];
$('xpexs').innerHTML=EX.map(q=>`<span class=xpex>${esc(q)}</span>`).join('');
$('xpexs').onclick=e=>{if(e.target.classList.contains('xpex')){$('xpask').value=e.target.textContent; ask()}};
function ask(){const q=$('xpask').value.trim(); if(!q)return; $('xpask').value='';
  const chat=$('xpchat'); chat.insertAdjacentHTML('beforeend',`<div class=xpq>${esc(q)}</div><div class=xpa><span class=xpwait>Looking at the data...</span></div>`);
  const a=chat.lastElementChild; chat.scrollTop=chat.scrollHeight; $('xpexs').style.display='none';
  post('/api/ask',{session,question:q}).then(r=>{
    a.innerHTML=esc(r.answer||r.error||'')+(r.queries&&r.queries.length?`<details><summary>${r.queries.length} ${r.queries.length===1?'query':'queries'} used</summary>${
      r.queries.map(x=>`<pre>${x.title?esc(x.title)+' (on the map)\n':''}${esc(x.sql)}</pre>`).join('')}</details>`:'');
    if(r.fresh&&chat.querySelectorAll('.xpq').length>1)a.insertAdjacentHTML('afterbegin','<div style="font-size:11px;color:#b45309;margin-bottom:4px">'+
      'The agent has no memory of the questions above (the page was reloaded, or the server restarted): this one was answered on its own.</div>');
    store.set('xp-chat',chat.innerHTML); if(r.map)show(r.map,r.map.title); chat.scrollTop=chat.scrollHeight})
  .catch(e=>{a.textContent='Error: '+e})}
$('xpnew').onclick=()=>{post('/api/forget',{session}); session=newId(); store.set('xp-session',session); store.set('xp-chat','');
  $('xpchat').innerHTML=''; $('xpexs').style.display=''};
{const old=store.get('xp-chat'); if(old){$('xpchat').innerHTML=old; $('xpexs').style.display='none'}}      // (the chat so far, after a reload)
$('xpaskgo').onclick=ask; $('xpask').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault(); ask()}};
// export and clear
const save=(name,text,type)=>{const a=document.createElement('a'); a.href=URL.createObjectURL(new Blob([text],{type})); a.download=name; a.click()};
$('xpgeo').onclick=()=>last&&save('urbanstyle-results.geojson',JSON.stringify({type:'FeatureCollection',features:last.features}),'application/geo+json');
$('xpcsv').onclick=()=>{if(!last)return; const ks=[...new Set(last.features.flatMap(f=>Object.keys(f.properties)))];
  const q=v=>{v=String(v??''); return /[",\n]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v};
  save('urbanstyle-results.csv',[ks.join(','),...last.features.map(f=>ks.map(k=>q(f.properties[k])).join(','))].join('\n'),'text/csv')};
$('xpfocus').onclick=()=>listFocus(!groupF);
$('xpclr').onclick=()=>{shut(); selF=null; listSpec=null; listFocus(false); untick(); onMap({type:'FeatureCollection',features:[]}); $('xpsum').textContent=''; $('xpkinds').innerHTML=''; $('xplist').innerHTML=''; $('xpacts').style.display='none'};
$('xptabs').onclick=e=>{const t=e.target.dataset.t; if(!t)return; [...$('xptabs').children].forEach(b=>b.classList.toggle('on',b.dataset.t===t));
  document.querySelectorAll('.xptab').forEach(d=>d.classList.toggle('on',d.id==='xp-'+t))};
// the panel, folded (xp-off) or not; the map fills what is left
$('xpfold').onclick=()=>{const off=!B.classList.toggle('xp-off'); $('xpfold').innerHTML=off?'&laquo;':'&raquo;';
  $('xpfold').title=off?'hide the panel':'show the panel'; resize()};
// the layers on the map: the panel's own set (allow); at first the blocks, the buildings (grey: page.py), the sections, the intersections,
// the subsections and the bridge (Kaveh, 2026-10-13). The road centre lines are roadstyle's own layers (roads-*), the rest overlays.
const allow=new Set(['Blocks','Buildings','Sections','Intersections','Bridge 2D']);
const roadsOn=on=>{const m=M(); if(m&&!(typeof in3d!=='undefined'&&in3d))m.getStyle().layers.forEach(l=>{if(/^roads-/.test(l.id))m.setLayoutProperty(l.id,'visibility',on?'visible':'none')})};
const HIDE_LY=l=>/3D/.test(l);     // (3D's own layers: never in Layers, never drawn in 2D)
// (the layers as a tree, each under the one it is part of: blocks, sections and intersections cover the area (docs/design/space-layers.md);
// agreed with Kaveh, 2026-10-13. A group with ▸ opens to its types; its own box turns them all on or off)
// the layers, as the hierarchy of docs/design/steps.md, rank by rank (Kaveh, 2026-10-16: "an exact match to the hierarchy"). A node is
// [text, layer, note] (one layer), [text, null, note, kids] (a group: a rank, with its own box), or [text, layer, note, null, types]
// (the layer filtered to these types: a kind of the ground, a type of part). A layer filtered by types is drawn only where its
// KINDS set holds the type (levels2d applies it with the levels' filter).
const KINDS={Ground:new Set(),Parts:new Set(),Spaces:new Set(),Sides:new Set()};     // layer -> the types on (undefined: every type)
const typeOn=(label,p)=>{const k=KINDS[label]; return !k||k.has(p.type)};
const LYTREE=[
  ['Rank 0: the area',null,'the level, its whole area, with its content',[
    ['The area','Area','the whole area of the level'],['Road lines','Roads',"OSM's road and walkway centre lines"],['Buildings','Buildings',''],
    ['Rail lines','Rail',''],['Track','Track',''],['Stations','Station','']]],
  ['Rank 1: the ground',null,'the area cut into three kinds, the street, the plots and the paths, nothing left over',[
    ['street','Ground','the area less the blocks and the corridors: one item per connected piece',null,['street']],
    ['plot (the blocks)','Ground','the land between the streets and the paths',null,['plot']],['path (the corridors)','Ground','',null,['path']],
    ['the blocks, each its own colour','Blocks','the plots, with their street sides'],
    ['footways (on the ground)','Footways','every footpath at this level, whole, at its width: a sidewalk and a crossing lie on the street, every other footway, steps or path has its corridor in the kind path']]],
  ['Rank 2: the stretches of the street',null,'from junction to junction, and where the arms meet',[
    ['Sections, path sections','Sections',''],['Intersections, roundabouts, path intersections','Intersections','cut into sub-intersections at rank 3']]],
  ['Rank 2: the pieces of the plot',null,'',[
    ['building','Ground','',null,['building']],['yard','Ground','',null,['yard']],['alley','Ground','a service road inside the block',null,['alley']],
    ['car park','Ground','',null,['car park']],['construction site','Ground','',null,['construction site']],
    ['green','Ground','',null,['green']],['water','Ground','',null,['water']],['rail','Ground','',null,['rail']],['square','Ground','',null,['square']],
    ['structure','Ground','the ground under a bridge',null,['structure']]]],
  ['Rank 3: the spaces',null,'one per subsection and per intersection (an intersection is one space)',[
    ['subsection','Spaces','',null,['subsection']],['sub-intersection','Spaces','one per junction node of an intersection',null,['sub-intersection']],
    ['ring sector, centre','Spaces','a roundabout: one ring sector per arm, and its centre',null,['ring sector','centre']],
    ['path section','Spaces','',null,['path section']],['path intersection','Spaces','',null,['path intersection']],
    ['spaces, top down','Spaces (rank 3, top down)','rank 1\'s street cut by the stop lines and the joints: each face one space, corners included (division.py, the new construction)'],
    ['Subsection axes','Subsection axes','the axis of each subsection and path section: s runs along it'],
    ['Subsection breaks','Subsection breaks','where it starts'],['Cuts','Cuts','where one space ends and the next begins']]],
  ['Rank 4: the sides',null,'the driving side and the walking side of each space',[
    ['driving side','Sides','inside the kerb',null,['driving']],['walking side','Sides','outside the kerb, with the islands',null,['walking']]]],
  ['Rank 5: the parts, driving side',null,'',[
    ['lane','Parts','',null,['lane']],['paved','Parts','the paved rest of the frame beyond the lanes and the strips',null,['paved']],['junction area','Parts','',null,['junction area']],
    ['strips','Parts','parking, no parking, shoulder, bus lane, cycle lane, bus zone',null,['parking','no parking','shoulder','bus lane','cycle lane','bus zone']],
    ['crosswalk, cycle crossing','Parts','',null,['crosswalk','cycle crossing']],['bridge deck','Parts','',null,['bridge deck']]]],
  ['Rank 5: the parts, walking side',null,'',[
    ['furnishing','Parts','',null,['furnishing']],['sidewalk','Parts','',null,['sidewalk']],['frontage','Parts','',null,['frontage']],
    ['island','Parts','',null,['island']],['driveway','Parts','',null,['driveway']],['path, steps','Parts','the part of a path',null,['path','steps']]]],
  ['Rank 6: the marks',null,'',[['Painted lines','Mark: ','']]],
  ['On top',null,'lying on the tree, in no rank',[
    ['Street objects','Street objects','lamps, trees, signs'],['Crossings and driveways, drawn over the parts','On the parts',''],
    ['Bridges','Bridge 2D',''],['Links','Link: ','ramps, stairs, elevators'],['Mapillary','Mapillary','']]],
  ['Base map',null,'not the model',[['Positron','Positron',''],['Voyager','Voyager',''],['Light Gray','Light Gray',''],['Dark Matter','Dark Matter',''],
    ['OpenStreetMap','OpenStreetMap',''],['Satellite','Satellite',''],['Blank','Blank','']]]];
function layersList(){if(typeof OVERLAYS==='undefined')return; const all=['Roads',...OVERLAYS.map(o=>o.label)].filter(l=>!HIDE_LY(l)), used=new Set();
  const take=k=>k.endsWith(': ')?all.filter(l=>l.startsWith(k)):all.filter(l=>l===k);
  const sm=note=>note?`<small>${esc(note)}</small>`:'';
  const box=(l,txt,note,grp)=>{used.add(l); return `<label><input type=checkbox data-ly="${esc(l)}" ${grp?`data-grp="${esc(grp)}"`:''} ${allow.has(l)?'checked':''}>${esc(txt)}${sm(note)}</label>`};
  const kbox=(l,txt,note,types)=>{if(!take(l).length)return ''; used.add(l); const k=KINDS[l], on=allow.has(l)&&(!k||types.every(t=>k.has(t)));
    const n=typeof rsQuery==='function'?rsQuery(p=>types.includes(p.type),l).length:1;     // (a kind with nothing in this area: greyed, "none here")
    return `<label><input type=checkbox data-kind="${esc(l)}" data-types="${esc(types.join('|'))}" ${on?'checked':''}${n?'':' disabled'}>${esc(txt)}${sm(n?note:'none here'+(note?': '+note:''))}</label>`};
  const node=([txt,k,note,kids,types])=>{
    if(types)return kbox(k,txt,note,types);
    const sub=(kids||[]).map(node).join('');
    if(k&&k.endsWith(': ')){const ls=take(k); if(!ls.length)return ''; const on=ls.every(l=>allow.has(l));
      return `<details><summary><input type=checkbox data-all="${esc(k)}" ${on?'checked':''}> ${esc(txt)}${sm(note)}</summary><div class=lt>`+
        ls.map(l=>box(l,l.slice(k.length),'',k)).join('')+'</div></details>'}
    if(k)return take(k).length?box(k,txt,note):'';
    // a rank: its own box switches every layer and kind in it; ticked when any is on, half-ticked when not all (syncRanks)
    return `<div class=rk><div class=lg><label><input type=checkbox data-rank="${esc(txt)}"${sub?'':' disabled'}> ${esc(txt)}</label>${sm(note)}</div>`+(sub?`<div class=lt>${sub}</div>`:'')+'</div>'};
  $('xplys').innerHTML=LYTREE.map(node).join(''); syncRanks()}
function syncRanks(){$('xplys').querySelectorAll('.rk').forEach(rk=>{const b=rk.querySelector('input[data-rank]'), ls=[...rk.querySelectorAll('input[data-ly]:not([disabled]),input[data-kind]:not([disabled])')], n=ls.filter(c=>c.checked).length;
  if(b){b.checked=n>0; b.indeterminate=n>0&&n<ls.length}})}
// a rank's own box: every layer and kind in it on or off ("only rank 0": tick rank 0, untick the others)
$('xplys').addEventListener('click',e=>{const r=e.target.dataset&&e.target.dataset.rank; if(!r)return; e.stopPropagation();
  // (a box that shows ticked, any layer on, turns every layer in the rank off; a box with nothing on turns every layer on)
  const rk=e.target.closest('.rk'), ins=[...rk.querySelectorAll('input[data-ly]:not([disabled]),input[data-kind]:not([disabled])')], on=!ins.some(c=>c.checked);
  ins.forEach(c=>{if(c.checked!==on){c.checked=on; c.dispatchEvent(new Event('change',{bubbles:true}))}});
  rk.querySelectorAll('input[data-all]').forEach(c=>c.checked=on)},true);
// (a group's own box: all its types on or off)
$('xplys').addEventListener('click',e=>{const a=e.target.dataset&&e.target.dataset.all; if(!a)return; e.stopPropagation();
  const on=e.target.checked; $('xplys').querySelectorAll(`input[data-grp="${a}"]`).forEach(c=>{if(c.checked!==on){c.checked=on; c.dispatchEvent(new Event('change',{bubbles:true}))}})},true);
$('xplys').onchange=e=>{const t=e.target, l=t.dataset.ly, kl=t.dataset.kind; if(!l&&!kl)return; const on=t.checked;
  if(kl){const types=t.dataset.types.split('|'); KINDS[kl]=KINDS[kl]||new Set(); types.forEach(x=>on?KINDS[kl].add(x):KINDS[kl].delete(x));
    const vis=KINDS[kl].size>0; if(vis)allow.add(kl); else allow.delete(kl); rsSetOverlay(kl,vis); levels2d()}
  else{if(on)allow.add(l); else allow.delete(l); if(l==='Roads')roadsOn(on); else rsSetOverlay(l,on)}
  applyLooks(); syncRanks()};
// (the options keep their own code; what they switch on is allowed)
const optLy={allparts:()=>{KINDS.Parts=undefined; return ['Parts',...(typeof OVERLAYS!=='undefined'?OVERLAYS.filter(o=>o.label.startsWith('Mark: ')).map(o=>o.label):[])]},mlybox:()=>['Mapillary']};
$('xpopts').addEventListener('change',e=>{
  if(e.target.id==='lowbld'){if(typeof bldFade==='function')bldFade(); return}
  const f=optLy[e.target.id]; if(!f)return; f().forEach(l=>{e.target.checked?allow.add(l):allow.delete(l); rsSetOverlay(l,e.target.checked)}); levels2d(); setTimeout(layersList,100)},true);
// the tree (Find, server: /api/tree): a click on a name lists all of it (orange, a focus in 3D), on one thing selects it; the arrow opens.
// The tick boxes put a list together from parts of the tree (Kaveh, 2026-10-13: "if the user doesn't want the whole category"): the
// list is all that is ticked; a ticked group ticks all under it (greyed)
const ticked=new Map();      // node id -> its node (layer, where, label)
function branch(el,node){get('/api/tree?node='+encodeURIComponent(node)).then(kids=>{el.innerHTML='';
  const under=el.closest('.k')&&el.closest('.k').previousElementSibling, covered=!!(under&&under.querySelector('.cb')&&under.querySelector('.cb').checked);
  kids.forEach(k=>{const row=document.createElement('div'), sub=document.createElement('div'); row.className='n'; sub.className='k'; sub.style.display='none';
    row.innerHTML=`<span class=t>${k.kids?'▸':'•'}</span>${k.layer?`<input type=checkbox class=cb data-id="${esc(k.id)}" ${covered?'checked disabled':''}>`:''}<span class=l title="${esc(k.label)}">${esc(k.label)}</span>${k.count!=null?`<span class=c>${k.count}</span>`:''}`;
    const open=()=>{if(!k.kids)return; const shut_=sub.style.display!=='none'; sub.style.display=shut_?'none':''; row.querySelector('.t').textContent=shut_?'▸':'▾';
      if(!shut_&&!sub.dataset.done){sub.dataset.done=1; sub.textContent='…'; branch(sub,k.id)}};
    const cb=row.querySelector('.cb');
    if(cb)cb.onchange=()=>{if(cb.checked)ticked.set(k.id,k); else ticked.delete(k.id);
      sub.querySelectorAll('.cb').forEach(c=>{ticked.delete(c.dataset.id); c.checked=cb.checked; c.disabled=cb.checked}); combine()};   // (under it: in it, not ticked alone)
    row.onclick=e=>{if(e.target.classList.contains('cb'))return; if(e.target.classList.contains('t')){open(); return}
      document.querySelectorAll('#xpbr .n.on').forEach(x=>x.classList.remove('on')); row.classList.add('on');
      if(!k.layer){open(); return}
      if(!k.kids){post('/api/query',{layer:k.layer,where:k.where}).then(fc=>{if(fc.features&&fc.features[0])select(fc.features[0])}); return}
      untick(); if(sub.style.display==='none')open(); wait('Loading...');
      latest(post('/api/query',{layer:k.layer,where:k.where})).then(fc=>{show(fc,k.label,true);
        // (one space, an intersection or a subsection: its parts listed, and the space itself selected: in focus in 3D, as from Find;
        // Kaveh, 2026-10-13: "intersection not working")
        if(k.id.startsWith('unit:'))return post('/api/query',{layer:'Street spaces',where:[{field:'unit_id',op:'=',value:k.id.slice(5)}]})
          .then(f=>{if(f.features&&f.features[0])select(f.features[0],true)});
        if(selF&&$('xpcard').classList.contains('on'))card(selF)}).catch(stale)};
    el.appendChild(row); el.appendChild(sub)})})}
function untick(){ticked.clear(); document.querySelectorAll('#xpbr .cb').forEach(c=>{c.checked=false; c.disabled=false})}
// the list of all that is ticked (a group under a ticked group is in it once): its things once each, their totals added up
function combine(){
  const ks=[...ticked.values()];
  if(!ks.length){show({type:'FeatureCollection',features:[],total:0,length_m:0,area_m2:0,kinds:[]},'nothing ticked',true); return}
  wait('Loading...');
  latest(Promise.all(ks.map(k=>post('/api/query',{layer:k.layer,where:k.where})))).then(fcs=>{const seen=new Set(), fs=[], kinds={}; let more=0;
    fcs.forEach(fc=>{more+=Math.max(0,(fc.total||0)-(fc.features||[]).length);
      (fc.features||[]).forEach(f=>{const key=f.properties._layer+'|'+f.properties._id; if(seen.has(key))return; seen.add(key); fs.push(f);
        const t=f.properties.type||f.properties.class||f.properties.kind||''; kinds[t]=(kinds[t]||0)+1})});
    const sum=k=>Math.round(fs.reduce((a,f)=>a+(f.properties[k]||0),0)*10)/10;
    show({type:'FeatureCollection',features:fs,total:fs.length+more,length_m:sum('_m'),area_m2:sum('_m2'),kinds:Object.entries(kinds).sort((a,b)=>b[1]-a[1])},
      ks.length===1?ks[0].label:`${ks.length} ticked`,true)}).catch(stale)}
// the view: 2D / 3D (the tilt: setView follows it), and the levels: each level with streets full, faded or hidden, all together, the
// same in 2D and 3D (Kaveh, 2026-10-13). Each view keeps its own: 2D starts with the bridge (level 1) faded to an outline, 3D with all
// full. Level 0: the basemap and the buildings, and in 3D the ground with its parts, kerbs and objects; level 1: the bridge and decks.
// In 2D every layer shows only the levels not hidden (levels2d); at first level 0, level 1 faded, the others (tunnels, upper decks) hidden.
const LOOK=['full','fade','off'], LOOKS={'2d':{1:'fade'},'3d':{}}, FADE=0.2, orig={};
const d3=()=>typeof in3d!=='undefined'&&in3d, look=()=>LOOKS[d3()?'3d':'2d'];
function views(){$('xp2d').classList.toggle('on',!d3()); $('xp3d').classList.toggle('on',d3());
  const ls=(meta&&meta.street_levels)||[0], L=look();
  $('xplk').innerHTML=ls.map(l=>{const st=L[l]||'full';
    return `<button data-k="${l}" class="${st}" title="level ${l}: ${({full:'shown',fade:'faded',off:'hidden'})[st]} (a click: the next)">${l}</button>`}).join('')}
$('xplk').onclick=e=>{const l=e.target.dataset.k; if(l===undefined)return; const L=look(); L[l]=LOOK[(LOOK.indexOf(L[l]||'full')+1)%3]; views(); applyLooks()};
const OPA={fill:'fill-opacity','fill-extrusion':'fill-extrusion-opacity',line:'line-opacity',circle:'circle-opacity',raster:'raster-opacity'};
// 2D: each layer's things on the levels not hidden: by `level`, a building by its floors (level_min..level_max), a link by its two ends
function levels2d(){const m=M(); if(!m||d3()||typeof OVERLAYS==='undefined'||typeof rsFilter!=='function')return; const L=look(), on=l=>(L[l]||'full')!=='off';
  const keep=p=>p.level!=null?on(p.level):p.level_min!=null?Array.from({length:p.level_max-p.level_min+1},(_,i)=>p.level_min+i).some(on):p.level_a!=null?on(p.level_a)||on(p.level_b):true;
  // (a layer whose data is not in yet is left alone, and tried again: filtered while empty, it was hidden whole, and the map opened with
  // no data at all; Kaveh, 2026-10-13: "monaco-v8 not working at all")
  let waiting=rsQuery(()=>true).length===0;
  if(!waiting)rsFilter(rsQuery(p=>p.level==null||on(p.level)));      // the road centre lines
  OVERLAYS.forEach(o=>{if(o.label==='Bridge 2D'||/3D/.test(o.label))return;
    if(!rsQuery(()=>true,o.label).length){waiting=true; return}
    rsFilter(rsQuery(p=>keep(p)&&typeOn(o.label,p),o.label),o.label)});     // (and the kinds or types ticked in Layers)
  // a faded level: its things at FADE in every layer, by their level (only show / hide was done here, so levels -1, -2, -3 never
  // faded; Kaveh, 2026-10-14). Level 0 fades the basemap and the buildings, level 1 the bridge (applyLooks)
  // and drawn on top of the others: under an opaque level 0 a faint level below it was not seen (Kaveh, 2026-10-14)
  const faded=Object.keys(L).filter(l=>L[l]==='fade'&&+l!==0&&+l!==1).map(Number), m2=M();
  const SORT={fill:'fill-sort-key',line:'line-sort-key',circle:'circle-sort-key'};
  OVERLAYS.forEach(o=>{if(['Bridge 2D','Buildings'].includes(o.label)||/3D/.test(o.label))return;
    (o.layers||[]).forEach(id=>{const ly=m2.getLayer(id), k=ly&&OPA[ly.type]; if(!k)return;
      if(!(id+k in orig))orig[id+k]=m2.getPaintProperty(id,k)??1;
      const fd=['in',['coalesce',['get','level'],0],['literal',faded]];
      m2.setPaintProperty(id,k,faded.length?['case',fd,FADE,orig[id+k]]:orig[id+k]);
      if(SORT[ly.type])m2.setLayoutProperty(id,SORT[ly.type],faded.length?['case',fd,100,['coalesce',['get','level'],0]]:undefined)})});
  if(waiting&&lvTries++<60)setTimeout(levels2d,1000)}
let lvTries=0;
function applyLooks(){const m=M(); if(!m)return; if(!m.isStyleLoaded())return setTimeout(applyLooks,200); const L=look();
  const g=L[0]||'full', up=L[1]||'full';
  const keep=(id,k)=>{if(!(id+k in orig))orig[id+k]=m.getPaintProperty(id,k)??(k.endsWith('opacity')?1:null); return orig[id+k]};
  const set=(id,st,fadeTo)=>{const ly=m.getLayer(id); if(!ly)return; const k=OPA[ly.type]; const o=k&&keep(id,k);
    m.setLayoutProperty(id,'visibility',st==='off'?'none':'visible');
    if(k)m.setPaintProperty(id,k,st==='fade'?(fadeTo??FADE):o)};     // (painted lines, arrows and guide lines never fade in a focus: Kaveh, 2026-10-13)
  m.getStyle().layers.forEach(l=>{if(l.source==='bm'&&l.type==='raster'){const o=keep(l.id,'raster-opacity');
    m.setPaintProperty(l.id,'raster-opacity',g==='full'?o:g==='fade'?0.35:0.08)}});
  const ov=lab=>(typeof OVERLAYS!=='undefined'&&OVERLAYS.find(o=>o.label===lab)||{}).layers||[];
  if(d3()){const lv=id=>{const x=/^u3d-(deck|tun)(-?\d+)$/.exec(id); return x?+x[2]:null};     // (a deck or a tunnel: its own level's look)
    m.getStyle().layers.forEach(l=>{if(!l.id.startsWith('u3d-')||['u3d-bld','u3d-bld-on'].includes(l.id))return;
      const k=lv(l.id); set(l.id,k===null?g:(L[k]||'full'))});
    // (a faded tunnel above the ground, so it shows through: on top of the ground's parts, under the kerbs; else back under the ground)
    m.getStyle().layers.map(l=>l.id).filter(id=>/^u3d-tun-\d+$/.test(id)).forEach(id=>{const top=(L[lv(id)]||'full')==='fade';
      const to=top?(m.getLayer('u3d-kerb')?'u3d-kerb':undefined):(m.getLayer('u3d-gnd')?'u3d-gnd':undefined); if(to)m.moveLayer(id,to)});
    if(window.bldLook)window.bldLook(g);     // (the buildings: the 3D page fades them itself, by focus and selection too)
    const F=eff(), onBr=focusU?/^\w1-/.test(focusU):F&&F.bridge>0;      // (a focus on the ground: the bridge faint)
    const upF=F&&!onBr&&up==='full'?'fade':up;
    if(window.brOpacity)window.brOpacity(upF==='full'?1:upF==='fade'?0.25:0); return}
  levels2d();
  if(allow.has('Buildings'))ov('Buildings').forEach(id=>set(id,g));
  ov('Bridge 2D').forEach(id=>{const ly=m.getLayer(id); if(!ly)return;     // (faded: the light outline only)
    m.setLayoutProperty(id,'visibility',up==='off'||!allow.has('Bridge 2D')?'none':'visible');     // (its box in Layers, and the level)
    if(ly.type==='fill'){const o=keep(id,'fill-opacity'); m.setPaintProperty(id,'fill-opacity',up==='full'?o:0)}
    if(ly.type==='line'){const o=keep(id,'line-color'); m.setPaintProperty(id,'line-color',up==='full'?o:'#94a3b8')}})}
// (3D redraws its layers, draw3d, on every view change: the looks again after it)
if(typeof draw3d==='function'){const d3o=draw3d; draw3d=function(){d3o.apply(this,arguments); setTimeout(()=>{paintFocus(); selSrc(selF&&$('xpcard').classList.contains('on')?selF:null)},0)}}
$('xp2d').onclick=()=>M()&&M().easeTo({pitch:0,duration:600}); $('xp3d').onclick=()=>M()&&M().easeTo({pitch:60,duration:600});
// 2D: hover and click on the plan, as in 3D: the mouse resting HOVER2D ms on a thing of any layer shown lights the whole thing (light
// purple); a click selects it (deep purple) and opens its card in the panel; roadstyle's own popup and tooltip never show (Kaveh,
// 2026-10-13: "hover doesn't work", "the popup shows on the map instead of the side panel"). A layer the panel knows (OVMAP) gives its
// card from the server, with all its fields; any other (painted lines, street-object dots, cuts, links, Mapillary) from its own fields.
// (overlay label -> [the panel's layer, the overlay's id field, the server's field for it])
const HOVER2D=300, OVMAP={'Buildings':['Buildings','id','source_id'],'Bridge 2D':['Bridge parts','id','id'],'Spaces':['Street spaces','unit_id','unit_id'],
  'Parts':['Street parts','part_id','part_id'],'On the parts':['Street parts','part_id','part_id'],'Ground':['Ground','ground_id','ground_id'],
  'Parking lots':['Car parks','id','lot_id'],'Subsections':['Street spaces','unit_id','unit_id'],'Intersections':['Stretches','stretch_id','stretch_id'],
  'Sections':['Stretches','stretch_id','stretch_id'],'Subsection axes':['Street spaces','subsection_id','unit_id'],'Blocks':['Blocks','block_id','block_id'],
  'Street objects':['Street objects','refs','id'],'Sides':['Sides','side_id','side_id']};
const OWNKEY=['part_id','unit_id','refs','node_id','subsection_id','intersection_id','feature_id','id'];     // (a feature's own id, in this order)
const is3d=()=>typeof in3d!=='undefined'&&in3d;
const ovOf=f=>OVERLAYS.find(o=>(o.layers||[]).includes(f.layer.id));
function live2d(){const m=M(); if(!m||typeof OVERLAYS==='undefined')return [];
  const ids=[...XP,...OVERLAYS.filter(o=>!/3D/.test(o.label)).flatMap(o=>o.layers||[])];
  return ids.filter(id=>m.getLayer(id)&&m.getLayoutProperty(id,'visibility')!=='none')}
// [panel layer or the overlay's label, the thing's id, its key in the overlay, the server's field for it (none: not on the server)]
function ref(f){const p=f.properties; if(XP.includes(f.layer.id))return p._layer&&p._id!=null?[p._layer,String(p._id),'_id',LAYERS_ID[p._layer]||'id']:null;
  const o=ovOf(f); if(!o)return null; const mp=OVMAP[o.label];
  if(mp&&p[mp[1]]!=null)return [mp[0],String(p[mp[1]]),mp[1],mp[2]];
  const k=OWNKEY.find(k=>p[k]!=null&&p[k]!==''); return k?[o.label,String(p[k]),k,null]:null}
// (a click takes the smallest thing under the mouse, not the top layer: a sidewalk, not the street space drawn over it; Kaveh,
// 2026-10-13: "I click on a sidewalk and you say it is a space")
const RANK=['Street objects','On the parts','Parts','Bridge 2D','Buildings','Parking lots','Subsection axes','Sides','Spaces','Subsections','Intersections','Sections','Blocks','Ground'];
const rank=f=>{const o=XP.includes(f.layer.id)?null:ovOf(f), i=o?RANK.indexOf(o.label):-1; return o?(i<0?RANK.length:i):-1};
let noXPhit=false;     // (a check's place: the thing under the point, not the result dot drawn on it)
function hit2d(pt){const ls=live2d().filter(id=>!(noXPhit&&XP.includes(id))); if(!ls.length)return null;
  const hs=M().queryRenderedFeatures(pt,{layers:ls}).filter(ref); return hs.reduce((b,f)=>!b||rank(f)<rank(b)?f:b,null)}
// (the whole thing under the mouse, from the full data: the map draws a large area in tiles, and the drawn feature is only the tile's
// piece; one block lit in a different piece at every tile: Kaveh, 2026-10-13, b0-w4224972r.13)
const fullIdx={};
function full(f){const m=M(), r=ref(f); if(!r||!m)return f;
  if(f.source===SRC&&last)return last.features.find(x=>x.properties._layer===r[0]&&String(x.properties._id)===r[1])||f;
  const k=r[2], ck=f.source+'|'+k;
  if(!fullIdx[ck]){const s=m.getSource(f.source), d=s&&s.serialize&&s.serialize().data, ix=new Map();
    ((d&&d.features)||[]).forEach(x=>{const v=x.properties&&x.properties[k]; if(v==null)return; const a=ix.get(String(v)); a?a.push(x):ix.set(String(v),[x])});
    fullIdx[ck]=ix}
  const a=fullIdx[ck].get(r[1]); if(!a||!a.length)return f;
  return a.length===1?a[0]:{type:'Feature',geometry:{type:'GeometryCollection',geometries:a.map(x=>x.geometry)},properties:a[0].properties}}
function hovSrc(f){const m=M(); if(!m||!m.isStyleLoaded())return; const fc={type:'FeatureCollection',features:f?[{type:'Feature',geometry:f.geometry,properties:{}}]:[]};
  if(!m.getSource('xp-hov')){m.addSource('xp-hov',{type:'geojson',data:fc});
    m.addLayer({id:'xp-hov-fill',source:'xp-hov',type:'fill',filter:['==',['geometry-type'],'Polygon'],paint:{'fill-color':'#b388ff','fill-opacity':0.45}});
    m.addLayer({id:'xp-hov-line',source:'xp-hov',type:'line',paint:{'line-color':'#b388ff','line-width':4}});
    m.addLayer({id:'xp-hov-pt',source:'xp-hov',type:'circle',filter:['==',['geometry-type'],'Point'],paint:{'circle-color':'#b388ff','circle-radius':8}})}
  else m.getSource('xp-hov').setData(fc)}
let hovKey=null, hovT2=0;
function wire2d(){if(offline)return; const m=M();     // (no server: roadstyle's own hover and popups)
  m.on('mousemove',e=>{if(is3d()){if(hovKey){hovKey=null; hovSrc(null)} return}
    const f=hit2d(e.point), r=f&&ref(f), key=r?r[0]+'|'+r[1]:null; m.getCanvas().style.cursor=r?'pointer':'';
    if(key===hovKey)return; clearTimeout(hovT2); if(hovKey){hovKey=null; hovSrc(null)}
    if(r)hovT2=setTimeout(()=>{hovKey=key; hovSrc(full(f))},HOVER2D)});
  m.on('mouseout',()=>{clearTimeout(hovT2); hovKey=null; hovSrc(null)});
  m.on('click',e=>{if(is3d())return; const f=hit2d(e.point), r=f&&ref(f); if(!r)return; const at=[e.lngLat.lng,e.lngLat.lat];
    if(f.source===SRC){const g=full(f); if(g&&g.properties&&g.properties._layer)select(g,at); return}     // (a result: the list has it whole)
    if(r[3]){post('/api/query',{layer:r[0],where:[{field:r[3],op:'=',value:r[1]}]}).then(fc=>{if(fc.features&&fc.features[0])select(fc.features[0],at)}); return}
    const g=full(f), p=Object.fromEntries(Object.entries(f.properties).filter(([k])=>k!=='color'));     // (a layer the panel has no table for: its own fields)
    select({type:'Feature',geometry:g.geometry,properties:{...p,_layer:r[0],_id:r[1],_label:p.type||p.class||r[0]}},at)});
  // (roadstyle's own popup and its hover tooltip: off for every layer, the panel shows them)
  if(typeof OVERLAYS!=='undefined'&&!offline)OVERLAYS.forEach(o=>{o.interactive=false; o.tooltip=[]})}     // (no server: roadstyle's popups show the fields)
const LAYERS_ID={'Stretches':'stretch_id','Sides':'side_id','Buildings':'source_id','Bridge parts':'id','Street spaces':'unit_id','Street parts':'part_id','Ground':'ground_id','Car parks':'lot_id','Blocks':'block_id','Street objects':'id'};
// ---- the start: the server's first answer (meta) and the layers' data in, the first look set, then the veil lifted (nothing changes in
// front of the user while the page loads). No server (a page opened as a file): the map alone.
let tries=0;
const lift=()=>{const v=$('xpveil'); if(v)v.remove()};
function start(){const m=M(), data=typeof OVERLAYS!=='undefined'&&typeof rsQuery==='function'&&OVERLAYS.every(o=>/3D/.test(o.label)||rsQuery(()=>true,o.label).length);
  if((!m||!m.isStyleLoaded()||!meta||!data)&&tries++<150)return setTimeout(start,200);
  if(meta.street_levels===null){     // no server: the levels from the page's own data (every layer's `level`), so the level buttons still work
    const ls=new Set([0]), take=p=>{if(p.level!=null)ls.add(+p.level); return false};
    OVERLAYS.forEach(o=>{if(!/3D/.test(o.label))rsQuery(take,o.label)}); rsQuery(take);
    meta.street_levels=[...ls].sort((a,b)=>a-b); meta.street_levels.forEach(l=>{if(l!==0&&l!==1&&!(l in LOOKS['2d']))LOOKS['2d'][l]='off'})}
  OVERLAYS.forEach(o=>{if(!HIDE_LY(o.label))rsSetOverlay(o.label,allow.has(o.label))}); roadsOn(allow.has('Roads'));
  layersList(); views(); applyLooks(); wire2d();
  m.on('styledata',()=>{if(last)layers()});
  m.on('pitchend',()=>setTimeout(()=>{vis(); views(); applyLooks(); selSrc(selF&&$('xpcard').classList.contains('on')?selF:null)},50));
  m.once('idle',lift); setTimeout(lift,3000)}
get('/api/meta').then(mt=>{meta=mt; (mt.street_levels||[]).forEach(l=>{if(l!==0&&l!==1&&!(l in LOOKS['2d']))LOOKS['2d'][l]='off'});
  $('xparea').textContent='· '+mt.area; branch($('xpbr'),''); checksBox(mt.checks||[]);
  $('xplayer').innerHTML=Object.entries(mt.layers).map(([k,v])=>`<option value="${esc(k)}">${esc(k)} (${v.count})</option>`).join(''); cond(); start()})
  // (no server, the page as plain files: the panel stays for the layers, the view and the levels, read from the page's data (start);
  // the search, the tree, the filter and the agent need the server and are hidden; Kaveh, 2026-10-16: "it shows only level 0 and 1")
  .catch(()=>{offline=true; meta={area:'',layers:{},street_levels:null}; $('xparea').textContent='· no server: layers, view and levels only';
    ['xpq','xpbr','xpsum','xplayer','xpcond','xpask','xpcard'].forEach(id=>{const e=$(id); if(e)e.style.display='none'}); start()});
})();
