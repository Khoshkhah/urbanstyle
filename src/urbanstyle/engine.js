// The dashboard's map engine (page.py writes it into the page, the panel explore.html drives it; docs/design/dashboard.md): two views of
// the same data, each its own set of layers. 2D: roadstyle's overlays (their wanted visibility is ov.visible, which the panel keeps).
// 3D (tilted; roadstyle's 3D button or the panel's): the u3d-* layers made from the same sources: every space's ground on the level (the
// roadway flat, sidewalks and islands raised, kerbstones), its painted lines, the buildings to their real height, the levels above as
// decks, and one model per street object. Switching shows one set and hides the other.
// Hooks for the panel: pick3d, mark3d, focus3d, bldLook, nearRoad (window.*); the bridges' own (brPick, brMark, ...) come with the bridge model.
// The page's own data comes in window.US_CFG (page.py); this file is the same for every area, loaded from the server (or beside the
// page, online), so every dashboard runs the same script (Kaveh, 2026-10-13: "they must run the same script")
const C=window.US_CFG;
const MK=C.marks;      // the painted lines' types in this area ("Mark: <type>" layers)
const RAISE=C.raised;   // parts.RAISED: the parts above the roadway, their top (m)
const LEVEL_M=3.2, DECK_M=6, SLAB_M=0.6;   // a building's floor; a bridge level's height above the one viewed, its deck's thickness
const ovSrc=lab=>(OVERLAYS.find(o=>o.label===lab)||{}).source;
const byKey=(key,table,dflt)=>['match',['get',key],...Object.entries(table).flatMap(([k,v])=>[k,v]),dflt];
const NOT_IN_3D=['Mark: kerb'];   // the raised sidewalk's edge is the kerb; the guide lines (lane to lane through a junction) stay
let lv3d=0, in3d=false, roads2d={};
const U3D=[];
// terrain in 3D, only when ticked (off by default): public terrain tiles on AWS (Terrarium, about 30 m detail) are too coarse for Monaco's
// terraces and stacked streets - roads sink into the hill, buildings float. A fine terrain (1-5 m) is needed before it can be on by default.
const DEM_TILES='https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png';
function terrain(on){if(!map.setTerrain)return;
  if(on&&!map.getSource('u3d-dem'))map.addSource('u3d-dem',{type:'raster-dem',tiles:[DEM_TILES],tileSize:256,encoding:'terrarium',maxzoom:15,
    attribution:'Terrain: <a href="https://registry.opendata.aws/terrain-tiles/" target="_blank">AWS Terrain Tiles</a>'});
  const now=!!map.getTerrain&&!!map.getTerrain(); if(on!==now)map.setTerrain(on?{source:'u3d-dem',exaggeration:1}:null)}
// every level but 0 has its own layer in 3D (a deck above, a tunnel below), so each follows its own level button: full, faded or
// hidden (Kaveh, 2026-10-13: "fading in 3D only works for level 0")
const OTHER_LEVELS=[-5,-4,-3,-2,-1,1,2,3,4,5];
function draw3d(){
  map.setLight({anchor:'viewport',intensity:0.15});   // a soft light: white walls stay near-white (MapLibre's 0.5 made them grey, Kaveh 2026-10-13)
  terrain(in3d&&document.getElementById('terrain3d').checked);
  const add=(spec,filter)=>{if(!spec.source)return; if(!map.getLayer(spec.id)){map.addLayer(spec); U3D.push(spec.id)}
    map.setFilter(spec.id,filter); map.setLayoutProperty(spec.id,'visibility',in3d?'visible':'none')};
  const lvl=['==',['get','level'],lv3d];
  const own=['all',lvl,['!',['in',['get','unit_id'],['literal',window.brUnits||[]]]]];   // (on a bridge: the model lays them on its deck)
  // the tunnels (levels below 0): the map cannot draw under the ground, so their parts lie flat under level 0's ground: they show where
  // level 0 is faded or hidden (Kaveh, 2026-10-13: "monaco doesn't show tunnels"); one layer a level, the deepest first
  OTHER_LEVELS.filter(l=>l<0).forEach(l=>add({id:'u3d-tun'+l,type:'fill',source:ovSrc('Parts'),paint:{'fill-color':['get','color'],'fill-opacity':1}},
    ['==',['get','level'],l]));
  add({id:'u3d-gnd',type:'fill',source:ovSrc('Ground'),paint:{'fill-color':['get','color'],'fill-opacity':1}},['all',lvl,['!=',['get','type'],'street']]);   // the ground beside the street
  add({id:'u3d-lot',type:'fill',source:ovSrc('Parking lots'),paint:{'fill-color':'#a8b0ba','fill-opacity':1}},lvl);   // a car park: paved, flush
  add({id:'u3d-ground',type:'fill',source:ovSrc('Parts'),paint:{'fill-color':['get','color'],'fill-opacity':1}},
      ['all',own,['!',['in',['get','type'],['literal',Object.keys(RAISE)]]]]);
  OVERLAYS.filter(o=>o.label.startsWith('Mark: ')&&!NOT_IN_3D.includes(o.label)).forEach(o=>{   // the paint, as in 2D, on the 3D ground
    const l2=map.getStyle().layers.find(x=>x.id===o.layers[0]); if(!l2)return;
    add({id:'u3d-'+o.layers[0],type:l2.type,source:o.source,paint:l2.paint||{},layout:Object.assign({},l2.layout||{},{visibility:'none'})},own)});
  // the kerb: a stone 0.25 m wide along the roadway's edge
  add({id:'u3d-kerb',type:'fill-extrusion',source:ovSrc('Kerbs 3D'),paint:{'fill-extrusion-color':'#8f8b86','fill-extrusion-opacity':1,
      'fill-extrusion-height':C.kerbtop}},own);     // a grey stone, standing 5 cm above the sidewalk: the kerb reads as a line
  add({id:'u3d-raised',type:'fill-extrusion',source:ovSrc('Parts'),paint:{'fill-extrusion-color':['get','color'],'fill-extrusion-opacity':1,
      'fill-extrusion-height':byKey('type',RAISE,0)}},['all',own,['in',['get','type'],['literal',Object.keys(RAISE)]]]);
  add({id:'u3d-bld',type:'fill-extrusion',source:ovSrc('Buildings'),paint:{'fill-extrusion-color':'#ffffff','fill-extrusion-opacity':0.92,'fill-extrusion-vertical-gradient':false,
      'fill-extrusion-height':['get','height_m'],'fill-extrusion-base':['*',['max',['get','level_min'],0],LEVEL_M]}},     // its real height
      ['>=',['get','level_max'],0]);
  const up=['*',['-',['get','level'],lv3d],DECK_M];   // bridges: the levels above, as decks in the air
  OTHER_LEVELS.filter(l=>l>0).forEach(l=>add({id:'u3d-deck'+l,type:'fill-extrusion',source:ovSrc('Parts'),paint:{'fill-extrusion-color':['get','color'],
      'fill-extrusion-opacity':1,'fill-extrusion-base':['-',up,SLAB_M],'fill-extrusion-height':['+',up,byKey('type',RAISE,0)]}},
      ['all',['==',['get','level'],l],['!',['in',['get','unit_id'],['literal',window.brUnits||[]]]]]));   // (a bridge's 3D model replaces its deck)
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
const tip3d=new maplibregl.Popup({closeButton:false,closeOnClick:false,offset:12,className:'u3d-tip'}), OBJ_POPUP=C.objpopup;
// a popup for the selected thing (`who`: its refs or part_id); closing it deselects it
const pop3d=(e,p,fields,who)=>setTimeout(()=>{if(sel3d!==who)return;     // deselected meanwhile (a quick second click)
  document.querySelectorAll('.maplibregl-popup:not(.u3d-tip)').forEach(x=>x.remove());
  const pp=new maplibregl.Popup({closeButton:true,maxWidth:'320px'}).setLngLat(e.lngLat).setHTML('<table>'+
    fields.filter(k=>p[k]!==undefined&&p[k]!==null&&p[k]!=='').map(k=>`<tr><td><b>${k}</b></td><td>${p[k]}</td></tr>`).join('')+'</table>');
  pp.on('close',()=>{if(sel3d===who){sel3d=null; paint3d()}});    // (Popup.on does not return the popup: no chaining)
  pp.addTo(map)},0);
// (the Explore panel selects a thing as a click in 3D does: its part_id, ground_id, building or car park id; urbanstyle serve)
window.pick3d=(v,obj)=>{sel3d=v??null; selObj=!!obj; paint3d()};     // (obj: a street object: the buildings low)
function deselect3d(){if(sel3d===null)return false; sel3d=null; paint3d();
  document.querySelectorAll('.maplibregl-popup:not(.u3d-tip)').forEach(x=>x.remove()); return true}
// layer -> [its colour property, the key of a feature, its own colour, its popup fields]
const L3D={'u3d-furn':['fill-extrusion-color','refs',['get','color'],OBJ_POPUP],
  'u3d-bld':['fill-extrusion-color','id','#ffffff',C.bldpopup],     // (white, no dark base: Kaveh, 2026-10-13)
  'u3d-lot':['fill-color','id','#a8b0ba',C.lotpopup],
  'u3d-gnd':['fill-color','ground_id',['get','color'],C.groundpopup],
  'u3d-kerb':['fill-extrusion-color','kerb_id','#8f8b86',['type','unit_id','arm','length_m','source','method','ref']],
  'u3d-ground':['fill-color','part_id',['get','color'],null],'u3d-raised':['fill-extrusion-color','part_id',['get','color'],null]};
// the other levels' parts too: a tunnel's lanes (flat under the ground) and a deck's, hovered and picked like the ground's (Kaveh,
// 2026-10-16: "I can't select a tunnel lane, the hover doesn't work on them")
OTHER_LEVELS.forEach(l=>{L3D[l<0?'u3d-tun'+l:'u3d-deck'+l]=[l<0?'fill-color':'fill-extrusion-color','part_id',['get','color'],null]});
const isPart=id=>/^u3d-(ground|raised|tun-?\d+|deck\d+)$/.test(id);
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
  const fk=isPart(id)||id==='u3d-kerb'?'unit_id':id==='u3d-furn'?'space':undefined;
  // (a focus: {units, parts, ground, blds, lots, objs}, any of them: a street space, a block, or a group from Browse)
  const F=xpFocus, lit=(k,vs)=>vs&&vs.length?['in',['get',k],['literal',vs]]:false, units=F?(F.units||(F.unit?[F.unit]:[])):[];
  let inF=false;
  if(F){if(id==='u3d-bld')inF=lit('id',F.blds); else if(id==='u3d-gnd')inF=lit('ground_id',F.ground); else if(id==='u3d-lot')inF=lit('id',F.lots);
    else{const a=[fk&&lit(fk,units),isPart(id)&&lit('part_id',F.parts),
      id==='u3d-furn'&&(F.objs||[]).length&&['any',...F.objs.map(is)]].filter(Boolean); inF=a.length?['any',...a]:false}}
  // (crosswalks keep their colours in every focus, as the painted lines do: Kaveh, 2026-10-13)
  const always=isPart(id)?['in',['get','type'],['literal',['crosswalk','cycle crossing']]]:false;
  map.setPaintProperty(id,prop,['case',is(sel3d||'\u0000'),'#7c4dff',is(hov3d||'\u0000'),'#b388ff',inF,base,marked,'#ff9100',always,base,
    !F?base:'#ebe8e3'])}); bldFade()}
// buildings fade by their opacity out of a focus (white walls in a faint grey read as no change, Kaveh 2026-10-13). Those in focus,
// selected or lit stay whole: a
// second layer over the same buildings
// (the level's look from the panel: full, fade or off)
const LOW_M=3;
let selObj=false, bldG='full'; window.bldLook=g=>{bldG=g; bldFade()};
function bldFade(){const b=map.getLayer('u3d-bld'); if(!b)return; const fade=bldG==='fade'||!!xpFocus, on=in3d&&bldG!=='off';
  if(!map.getLayer('u3d-bld-on'))map.addLayer({id:'u3d-bld-on',type:'fill-extrusion',source:b.source,paint:{'fill-extrusion-opacity':0.92,
    'fill-extrusion-vertical-gradient':false,'fill-extrusion-height':['get','height_m'],'fill-extrusion-base':map.getPaintProperty('u3d-bld','fill-extrusion-base')}},map.getLayer('u3d-furn')?'u3d-furn':undefined);
  if(!U3D.includes('u3d-bld-on'))U3D.push('u3d-bld-on');     // (a 3D layer: setView hides it in 2D)
  const keep=['any',['in',['get','id'],['literal',(xpFocus&&xpFocus.blds)||[]]],['==',['get','id'],sel3d??'\u0000'],['==',['get','id'],hov3d??'\u0000']];
  map.setFilter('u3d-bld-on',['all',map.getFilter('u3d-bld')||true,keep]);
  map.setPaintProperty('u3d-bld-on','fill-extrusion-color',map.getPaintProperty('u3d-bld','fill-extrusion-color'));
  map.setLayoutProperty('u3d-bld','visibility',on?'visible':'none'); map.setLayoutProperty('u3d-bld-on','visibility',on&&fade?'visible':'none');
  map.setPaintProperty('u3d-bld','fill-extrusion-opacity',fade?0.25:0.92);
  // low buildings, LOW_M high at most, to see the streets: the panel's option "low buildings", and while a street object is selected
  // (a building can stand between it and the camera; Kaveh, 2026-10-13)
  const low=!!(document.getElementById('lowbld')||{}).checked||(sel3d!==null&&selObj),
    h=low?['min',['get','height_m'],['+',map.getPaintProperty('u3d-bld','fill-extrusion-base'),LOW_M]]:['get','height_m'];
  ['u3d-bld','u3d-bld-on'].forEach(id=>map.setPaintProperty(id,'fill-extrusion-height',h))}
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
map.on('pitchend',()=>setView());   // the view follows the tilt: 3D's own layers, or 2D's
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
// a click on a space's part, a painted line or a Mapillary point: an open Street View window moves to the road nearest it
document.addEventListener('rs:select',e=>{const d=e.detail||{}, p=d.properties||{};
  if(d.sv)return;                     // our own Street View move (svHere)
  if(d.overlay&&['Parts','Sections','Intersections','Subsections','Mapillary','Cuts'].concat(MK.map(t=>'Mark: '+t)).includes(d.overlay))
    setTimeout(()=>svHere(p.arm||p.name||p.type||p.grp),0)});
// roadstyle's round end caps (a dot at the end of every centre line): hidden
function hideEnds(){map.getStyle().layers.filter(l=>/^roads-ends/.test(l.id)).forEach(l=>{
  if(map.getLayoutProperty(l.id,'visibility')!=='none')map.setLayoutProperty(l.id,'visibility','none')})}
map.on('idle',hideEnds);
map.setMaxZoom(24);
// Esc: deselects what is selected (3D: the lane or object; 2D: roadstyle's own selection)
document.addEventListener('keydown',e=>{if(e.key!=='Escape')return;
  if(in3d&&deselect3d())return;
  if(!in3d&&typeof _sel!=='undefined'&&_sel){rsDeselect(); document.querySelectorAll('.maplibregl-popup').forEach(x=>x.remove())}});
// links: ?at=lon,lat,zoom,pitch,bearing opens the map there (a pitch over 0 is the 3D view); ?c=<id> or #c=<id> finds that thing in the
// panel (a space, a part, an object). After the overlays' data is in (it loads after the map's own load event) and, on a page with
// bridges (#br3don), after their models' list of the spaces they replace (window.brUnits, a 10 MB fetch): drawn before it lands, the
// first 3D view showed a replaced space as a flat deck over the model (the Granville on-ramp; Kaveh, 2026-10-16)
let tries=0;
(function start(){if((rsQuery(()=>true,'Buildings').length===0||rsQuery(()=>true).length===0||(document.getElementById('br3don')&&!window.brUnits))&&tries++<100){setTimeout(start,200);return} fromHash()})();
function fromHash(){
  const at=location.search.match(/[?&]at=([^&]+)/);
  if(at){const [x,y,z,p,b]=decodeURIComponent(at[1]).split(',').map(Number); map.jumpTo({center:[x,y],zoom:z||19,pitch:p||0,bearing:b||0}); setView()}
  const m=location.hash.match(/^#c=(.+)$/)||location.search.match(/[?&]c=([^&]+)/);
  if(m)setTimeout(()=>window.xpFind&&window.xpFind(decodeURIComponent(m[1])),500)}
window.addEventListener('hashchange',fromHash);
