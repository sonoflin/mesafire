/* Mesa Fire & Medical — Station Coverage & Buildout Plan (v4)
   Interactive: drag/add/delete stations with snap-to-road + LIVE network-isochrone
   coverage recompute in the browser. Mesa-first lens, real Mesa data, mobile-first. */

const COLORS={existing:"#0ea5e9",committed:"#f59e0b","proposed-2028":"#7c3aed",
  "proposed-buildout":"#db2777","mutual-aid":"#64748b",user:"#0d9488"};
const STATUS_LABEL={existing:"Existing",committed:"Funded — 2024 bond",
  "proposed-2028":"Proposed — 2028 bond","proposed-buildout":"Buildout forecast",
  "mutual-aid":"Mutual aid (sister agency)",user:"Added by you"};
const STATUS_CLS={existing:"ex",committed:"co","proposed-2028":"p28","proposed-buildout":"bu",user:"user"};
const PHASES={funded:["existing","committed"],bond2028:["existing","committed","proposed-2028"],
  buildout:["existing","committed","proposed-2028","proposed-buildout"]};
const DEV_COLORS={Residential:"#16a34a",Employment:"#2563eb",Industrial:"#92400e",
  "Mixed-use":"#7c3aed",Mixed:"#7c3aed",Commercial:"#0891b2",Civic:"#475569",Aviation:"#0e7490"};
const VALHALLA="https://valhalla1.openstreetmap.de/isochrone",
      OSRM="https://router.project-osrm.org/nearest/v1/driving";
/* Emergency-speed assumption (see FAQ). 1.0 = model travel at routed auto speed, which
   matches ISO's first-due-engine rule (1.5 road mi in 4 min ≈ 22.5 mph). Raise toward ~1.2–1.3
   to credit code-3 (lights/siren) speed on arterials; lower to be more conservative. Tunable
   here AND in scripts/iso.py — keep them in sync, and clear data/iso_cache.json if you change it.
   Best practice is to calibrate this to Mesa's measured 90th-percentile travel times (CAD). */
const SPEED_FACTOR=1.0;

const state={phase:"funded",strategy:"mesa",base:"map",band4:true,band8:false,gaps:false,mutual:false,
  dev:false,pop:false,islands:true,edit:false,warnBuilt:true,adding:false};
const EAST_VALLEY=L.latLngBounds([33.12,-112.12],[33.68,-111.38]);  // Phoenix East Valley
const CELL_SQMI=0.09;  // ~0.3mi grid cell area

let MAP,DATA={},GRID=[],TOTAL=0,NC=0,COV={},MA4=[],MA8=[],LIVE=[],userSeq=0,ISOCACHE={};
let grp={},BASE_MAP,BASE_SAT;

(async function init(){
  try{
    const j=u=>fetch(u).then(r=>r.json());
    const [stations,coverage,gaps,boundary,metrics,mutual,developments,blockgroups,islands,grid]=await Promise.all([
      j("data/stations.json"),j("data/coverage.geojson"),j("data/gaps.geojson"),j("data/mesa_boundary.geojson"),
      j("data/metrics.json"),j("data/mutual_aid.json"),j("data/developments.json"),
      j("data/blockgroups_mesa.geojson"),j("data/county_islands.geojson"),j("data/demand_grid.json")]);
    DATA={stations,coverage,gaps,boundary,metrics,mutual,developments,blockgroups,islands};
    GRID=grid.cells;TOTAL=grid.total;NC=grid.ncells;
  }catch(err){document.body.innerHTML=`<div style="padding:30px;font-family:sans-serif">Could not load data.<br>
    Run <code>python -m http.server</code> in this folder, open <code>http://localhost:8000</code>.<br><br><small>${err}</small></div>`;throw err;}
  indexCoverage(); buildMap(); buildLive(); buildStaticLayers(); buildPanels(); wireUI(); refresh();
  // console API (useful for QA / the city's own devs)
  window.MESA={liveMetrics,reset:resetPlan,addAt:(la,lo)=>doAdd({lat:la,lng:lo}),
    move:(id,la,lo)=>{const s=LIVE.find(x=>x.id===id);return s&&handleMove(s,la,lo);},
    del:(id)=>{const s=LIVE.find(x=>x.id===id);if(s)removeStation(s);},
    get live(){return LIVE;},state};
})();

/* ---------- geometry ---------- */
function bboxOf(ring){let x0=1e9,y0=1e9,x1=-1e9,y1=-1e9;for(const c of ring){if(c[0]<x0)x0=c[0];if(c[0]>x1)x1=c[0];if(c[1]<y0)y0=c[1];if(c[1]>y1)y1=c[1];}return[x0,y0,x1,y1];}
function prep(geom){const parts=[];if(!geom)return parts;const polys=geom.type==="MultiPolygon"?geom.coordinates:[geom.coordinates];
  for(const p of polys){if(p&&p[0])parts.push({o:p[0],h:p.slice(1),bb:bboxOf(p[0])});}return parts;}
function inRing(lon,lat,r){let inside=false,n=r.length,j=n-1;for(let i=0;i<n;i++){const xi=r[i][0],yi=r[i][1],xj=r[j][0],yj=r[j][1];
  if(((yi>lat)!==(yj>lat))&&(lon<(xj-xi)*(lat-yi)/(yj-yi)+xi))inside=!inside;j=i;}return inside;}
function contains(parts,lon,lat){for(const p of parts){const b=p.bb;if(lon<b[0]||lon>b[2]||lat<b[1]||lat>b[3])continue;
  if(inRing(lon,lat,p.o)&&!p.h.some(h=>inRing(lon,lat,h)))return true;}return false;}
function maskUnion(partsList){const m=new Uint8Array(NC);for(const parts of partsList){if(!parts.length)continue;
  for(let i=0;i<NC;i++){if(!m[i]){const c=GRID[i];if(contains(parts,c[1],c[0]))m[i]=1;}}}return m;}
function pct(mask){let a=0,d=0;for(let i=0;i<NC;i++){if(mask[i]){a++;d+=GRID[i][2];}}return{area:100*a/NC,dem:100*d/TOTAL};}
function ringArea(r){let a=0;for(let i=0;i<r.length-1;i++)a+=r[i][0]*r[i+1][1]-r[i+1][0]*r[i][1];
  const ml=r.reduce((s,c)=>s+c[1],0)/r.length;return Math.abs(a)/2*69*69*Math.cos(ml*Math.PI/180);}
function shoelaceSqmi(parts){let t=0;for(const p of parts){t+=ringArea(p.o);for(const h of p.h)t-=ringArea(h);}return t;}
function liveStat(parts4){  // per-station: Mesa demand %, Mesa area sq mi, efficiency %
  let cells=0,dem=0;for(let i=0;i<NC;i++){const c=GRID[i];if(contains(parts4,c[1],c[0])){cells++;dem+=c[2];}}
  const mesaArea=cells*CELL_SQMI,tot=shoelaceSqmi(parts4);
  return {demPct:100*dem/TOTAL,mesaArea,eff:tot>0?Math.min(100,Math.round(100*mesaArea/tot)):100};}

/* ---------- coverage index + live model ---------- */
function indexCoverage(){
  for(const f of DATA.coverage.features){const p=f.properties;COV[`${p.station_id}|${p.strategy}|${p.band}`]=f.geometry;}
  for(const a of DATA.mutual){const g4=COV[`${a.id}|all|4min`],g8=COV[`${a.id}|all|8min`];if(g4)MA4.push(prep(g4));if(g8)MA8.push(prep(g8));}
}
function mkLive(s,g4,g8){return{id:s.id,name:s.name,address:s.address,note:s.note,status:s.status,
  strategy:s.strategy||"all",lat:s.lat,lon:s.lon,
  builtFlag:(s.status==="existing"||s.status==="committed"),
  editable:(s.status==="proposed-2028"||s.status==="proposed-buildout"||s.status==="user"),
  g4,g8,parts4:prep(g4),parts8:prep(g8),edited:false,
  captured_pct_of_city:s.captured_pct_of_city,efficiency_pct:s.efficiency_pct,
  nearest_station:s.nearest_station,gap_to_nearest_mi:s.gap_to_nearest_mi,priority:s.priority};}
function buildLive(){LIVE=[];userSeq=0;
  for(const s of DATA.stations){
    let key;
    if(s.status==="existing"||s.status==="committed")key="all";
    else if(s.status.startsWith("proposed")){if(s.strategy!==state.strategy)continue;key=s.strategy;}
    else continue;
    const g4=COV[`${s.id}|${key}|4min`],g8=COV[`${s.id}|${key}|8min`];
    if(g4&&g8)LIVE.push(mkLive(s,g4,g8));
  }}
function visibleLive(){return LIVE.filter(s=>s.status==="user"||PHASES[state.phase].includes(s.status));}
function liveMetrics(){const vs=visibleLive();let p4=vs.map(s=>s.parts4),p8=vs.map(s=>s.parts8);
  if(state.strategy==="aid"){p4=p4.concat(MA4);p8=p8.concat(MA8);}
  return{a4:pct(maskUnion(p4)).area,a8:pct(maskUnion(p8)).area,n:vs.length};}

/* ---------- map ---------- */
function buildMap(){
  MAP=L.map("map",{zoomControl:false,maxBounds:EAST_VALLEY,maxBoundsViscosity:0.85,minZoom:10}).setView([33.40,-111.72],11);
  L.control.zoom({position:"bottomright"}).addTo(MAP);
  BASE_MAP=L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",{
    attribution:'&copy; OpenStreetMap &copy; CARTO | Isochrones: Valhalla | Demand & boundary: City of Mesa GIS | Independent analysis — not an official Mesa FMD plan',
    subdomains:"abcd",maxZoom:19,bounds:EAST_VALLEY});
  BASE_SAT=L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",{
    attribution:'Imagery &copy; Esri, Maxar, Earthstar Geographics | Isochrones: Valhalla | Demand: City of Mesa GIS',
    maxZoom:19,bounds:EAST_VALLEY});
  BASE_MAP.addTo(MAP);
  ["pop","cov8","covma","cov4","island","gaps"].forEach((p,i)=>MAP.createPane(p).style.zIndex=400+i*5);
  grp.boundary=L.geoJSON(DATA.boundary,{style:{color:"#334155",weight:2,fill:false,dashArray:"4 4",opacity:.7}}).addTo(MAP);
  MAP.fitBounds(grp.boundary.getBounds(),{padding:[20,20]});
  grp.cov4=L.layerGroup();grp.cov8=L.layerGroup();grp.covma=L.layerGroup();
  grp.markers=L.layerGroup().addTo(MAP);grp.mutualMk=L.layerGroup();
  MAP.on("click",e=>{if(state.adding)doAdd(e.latlng);});
}
function buildStaticLayers(){
  grp.pop=L.geoJSON(DATA.blockgroups,{pane:"pop",style:f=>({pane:"pop",stroke:true,color:"#fff",weight:.4,
    fillColor:densColor(f.properties.dens),fillOpacity:.55})});
  grp.island=L.geoJSON(DATA.islands,{pane:"island",style:{pane:"island",color:"#475569",weight:1.2,dashArray:"3 3",
    fillColor:"#64748b",fillOpacity:.28},onEachFeature:(f,l)=>l.bindPopup(
    `<div class="lp"><span class="tag" style="background:#64748b22;color:#475569">County island</span>
     <b style="display:block;margin-top:4px">Unincorporated Maricopa County</b>
     <div class="a">Served by Rural Metro — excluded from Mesa's serviceable area, so no station is wasted on it.</div></div>`)}).addTo(MAP);
  grp.gaps=L.geoJSON(DATA.gaps,{pane:"gaps",pointToLayer:(f,ll)=>L.circleMarker(ll,{pane:"gaps",
    radius:3+Math.min(f.properties.w,3)*1.5,weight:0,fillColor:"#ef4444",fillOpacity:.45}),
    filter:f=>state.strategy==="mesa"||f.properties.ag4});
  // mutual-aid markers + coverage
  for(const a of DATA.mutual){
    const icon=L.divIcon({className:"",iconSize:[16,16],iconAnchor:[8,8],html:`<div class="mamark"></div>`});
    L.marker([a.lat,a.lon],{icon,zIndexOffset:-300}).bindPopup(
      `<div class="lp"><span class="tag" style="background:#64748b22;color:#475569">Mutual aid · ${a.jurisdiction}</span>
       <b style="display:block;margin-top:4px">${a.name}</b><div class="a">Sister-agency station — automatic/mutual aid</div></div>`).addTo(grp.mutualMk);
    const g4=COV[`${a.id}|all|4min`];if(g4)L.geoJSON(g4,{pane:"covma",style:covStyle("mutual-aid","4min")}).addTo(grp.covma);
  }
  grp.dev=L.layerGroup();
  for(const d of DATA.developments){const c=DEV_COLORS[d.type.split(/[ \/]/)[0]]||"#0b1220";
    const icon=L.divIcon({className:"",iconSize:[22,22],iconAnchor:[11,11],html:`<div class="devmark" style="background:${c}">▰</div>`});
    L.marker([d.lat,d.lon],{icon,zIndexOffset:200}).bindPopup(
      `<div class="lp"><span class="tag" style="background:${c}22;color:${c}">${d.type} · ${d.status}</span>
       <b style="display:block;margin-top:4px">${d.name}</b><div class="a">${d.magnitude}</div>
       <div style="font-size:12.5px;color:#475569">${d.note}</div></div>`,{maxWidth:260}).addTo(grp.dev);}
}
function densColor(d){return d>10000?"#7f1d1d":d>6000?"#dc2626":d>3500?"#f97316":d>1800?"#fbbf24":d>600?"#fde68a":"#f1f5f9";}
function covStyle(status,band){const c=COLORS[status];
  if(status==="mutual-aid")return{pane:"covma",color:c,weight:1.1,opacity:.6,dashArray:"2 4",fillColor:c,fillOpacity:.10};
  if(band==="4min")return{color:c,weight:1.6,opacity:.9,fillColor:c,fillOpacity:.17};
  return{color:c,weight:1,opacity:.45,dashArray:"3 4",fillColor:c,fillOpacity:.05};}

/* ---------- render live stations ---------- */
function stationMarker(s){
  const c=COLORS[s.status],sz=s.status==="existing"?27:32;
  const editing=state.edit&&s.editable;
  const ring=s.status!=="existing"?`box-shadow:0 0 0 3px ${c}40,0 2px 6px rgba(0,0,0,.4);`:"";
  const icon=L.divIcon({className:"",iconSize:[sz,sz],iconAnchor:[sz/2,sz/2],
    html:`<div class="stmark${editing?' editing':''}" style="width:${sz}px;height:${sz}px;background:${c};${ring}">${s.id}</div>`});
  const m=L.marker([s.lat,s.lon],{icon,draggable:editing,autoPan:true});
  m.bindPopup(popupHtml(s),{maxWidth:300});
  m.on("popupopen",()=>{const b=document.getElementById("del-"+s.id);if(b)b.onclick=()=>{MAP.closePopup();removeStation(s);};});
  if(editing)m.on("dragend",()=>{const ll=m.getLatLng();handleMove(s,ll.lat,ll.lng);});
  s._marker=m;return m;}
function popupHtml(s){
  const c=COLORS[s.status],lbl=STATUS_LABEL[s.status];
  const st=liveStat(s.parts4);
  const eff=(s.efficiency_pct!=null&&!s.edited)?s.efficiency_pct:st.eff;
  const chips=`<div class="chips">
    <span class="chip"><b>${st.mesaArea.toFixed(1)}</b> sq mi in Mesa</span>
    <span class="chip"><b>${st.demPct.toFixed(1)}%</b> of Mesa demand</span>
    <span class="chip"><b>${eff}%</b> of reach on Mesa land</span></div>`;
  const chips2=(s.priority!=null&&!s.edited)
    ?`<div class="chips"><span class="chip">Priority&nbsp;#${s.priority}</span><span class="chip">nearest #${s.nearest_station}: ${s.gap_to_nearest_mi}&nbsp;mi</span></div>`:"";
  let desc;
  if(s.edited) desc="You moved this — snapped to the road network and coverage recomputed live.";
  else if(s.status==="user") desc="You added this — coverage recomputed live against the real demand grid.";
  else if(s.status==="proposed-2028") desc="Recommended for the 2028 bond — fills one of the largest remaining 4-minute gaps in Mesa.";
  else if(s.status==="proposed-buildout") desc="Buildout-phase forecast — the next-best Mesa-coverage location after the 2028 pair.";
  else desc=s.note||"";
  const del=state.edit?`<button class="del" id="del-${s.id}">🗑 Delete station ${s.id}${s.builtFlag?" (real station)":""}</button>`:"";
  const title=s.status==="user"?"New station (you added)":`Station ${s.id} — ${(s.name||"").replace(/^(2028 Bond|Buildout) — /,'')}`;
  return `<div class="lp"><span class="tag" style="background:${c}22;color:${c}">${lbl}</span>
    <b style="display:block;margin-top:4px">${title}</b>
    <div class="a">${s.address||"placed by you"}</div>
    ${chips}${chips2}${desc?`<div class="desc">${desc}</div>`:""}${del}</div>`;}

function rebuild(){
  grp.cov4.clearLayers();grp.cov8.clearLayers();grp.markers.clearLayers();
  for(const s of visibleLive()){
    L.geoJSON(s.g8,{pane:"cov8",style:covStyle(s.status,"8min")}).addTo(grp.cov8);
    L.geoJSON(s.g4,{pane:"cov4",style:covStyle(s.status,"4min")}).addTo(grp.cov4);
    stationMarker(s).addTo(grp.markers);
  }
  applyLayers();
}
function applyLayers(){
  toggle(grp.cov4,state.band4);toggle(grp.cov8,state.band8);
  toggle(grp.covma,state.mutual);toggle(grp.mutualMk,state.mutual);
  toggle(grp.dev,state.dev);toggle(grp.pop,state.pop);toggle(grp.island,state.islands);
  if(state.gaps){grp.gaps.clearLayers();grp.gaps.addData({type:"FeatureCollection",
    features:DATA.gaps.features.filter(f=>state.strategy==="mesa"||f.properties.ag4)});grp.gaps.addTo(MAP);}
  else MAP.removeLayer(grp.gaps);
}
function toggle(layer,on){if(!layer)return;on?layer.addTo(MAP):MAP.removeLayer(layer);}

/* ---------- editing ---------- */
function toast(msg,ms=1900){const t=document.getElementById("toast");t.textContent=msg;t.classList.add("show");
  clearTimeout(t._t);t._t=setTimeout(()=>t.classList.remove("show"),ms);}
async function snapRoad(lat,lon){try{const r=await fetch(`${OSRM}/${lon},${lat}`);const j=await r.json();
  const w=j.waypoints&&j.waypoints[0];if(w&&w.location)return[w.location[1],w.location[0]];}catch(e){}return[lat,lon];}
async function fetchIso(lat,lon){const key=lat.toFixed(5)+","+lon.toFixed(5);if(ISOCACHE[key])return ISOCACHE[key];
  const t4=4*SPEED_FACTOR,t8=8*SPEED_FACTOR;
  const req={locations:[{lat,lon}],costing:"auto",contours:[{time:t4},{time:t8}],polygons:true,denoise:0.4,generalize:40};
  const r=await fetch(VALHALLA+"?json="+encodeURIComponent(JSON.stringify(req)));const j=await r.json();
  const byc={};for(const f of(j.features||[])){byc[Math.round(f.properties.contour*10)]=f.geometry;}
  const g4=byc[Math.round(t4*10)],g8=byc[Math.round(t8*10)];
  if(!g4||!g8)throw new Error("no iso");const res={g4,g8};ISOCACHE[key]=res;return res;}
async function handleMove(s,lat,lon){
  toast("Snapping to road & routing…",4000);
  try{const[sl,so]=await snapRoad(lat,lon);const iso=await fetchIso(sl,so);
    s.lat=sl;s.lon=so;s.g4=iso.g4;s.g8=iso.g8;s.parts4=prep(iso.g4);s.parts8=prep(iso.g8);s.edited=true;
    rebuild();updateLive();toast("Moved — coverage updated");}
  catch(e){toast("Couldn't route there — reverted");rebuild();}
}
async function doAdd(latlng){
  state.adding=false;document.getElementById("addBtn").classList.remove("arm");
  MAP.getContainer().style.cursor="";
  toast("Placing station — snapping & routing…",4000);
  try{const[sl,so]=await snapRoad(latlng.lat,latlng.lng);const iso=await fetchIso(sl,so);
    userSeq++;const id="N"+userSeq;
    const s={id,name:"New station",address:"placed by you (snapped to road)",note:"User-added — live coverage.",
      status:"user",strategy:"all",lat:sl,lon:so,builtFlag:false,editable:true,
      g4:iso.g4,g8:iso.g8,parts4:prep(iso.g4),parts8:prep(iso.g8),edited:true};
    LIVE.push(s);rebuild();updateLive();toast("Station added — coverage updated");}
  catch(e){toast("Couldn't route there — try a spot nearer a road");}
}
function removeStation(s){
  if(s.builtFlag&&state.warnBuilt){
    if(!confirm(`Station ${s.id} is an actual ${s.status==="committed"?"funded":"existing"} station.\nRemove it from the map anyway?\n\n(Turn off “Warnings” in the edit bar to skip this.)`))return;
  }
  LIVE=LIVE.filter(x=>x!==s);rebuild();updateLive();toast(`Station ${s.id} removed`);
}
function resetPlan(){buildLive();rebuild();updateLive();toast("Reset to the optimized model");}

/* ---------- live readout + refresh ---------- */
function updateLive(){
  const lm=liveMetrics(),base=DATA.metrics.strategies[state.strategy][state.phase];
  const d4=lm.a4-base.area4,d8=lm.a8-base.area8;
  const fmt=d=>Math.abs(d)<0.05?"":` <span class="delta ${d>=0?'up':'down'}">${d>=0?'▲':'▼'}${Math.abs(d).toFixed(1)}</span>`;
  document.getElementById("live4").innerHTML=lm.a4.toFixed(1)+"%"+fmt(d4);
  document.getElementById("live8").innerHTML=lm.a8.toFixed(1)+"%"+fmt(d8);
  document.getElementById("liveN").textContent=lm.n;
  renderOverview(lm);
}
function refresh(){rebuild();updateLive();}

/* ---------- panels ---------- */
function buildPanels(){renderOverview();renderStations();renderWhy();renderHelp();}
function renderHelp(){
  const m=DATA.metrics;
  const qa=[
    ["Why is our 4-minute area smaller than Google Maps says?",
     `Because we model a <b>fire engine</b>, not a car in light traffic. Our reach is ~1.4–1.7 road miles in 4 minutes
      (~22–27 mph effective), which matches the fire-service standard: ISO's first-due-engine rule of <b>1.5 road
      miles</b> works out to 1.5 ÷ (4⁄60 h) ≈ <b>22.5 mph</b>. Google shows ~28–35 mph because it's a passenger-car ETA.
      A 30-ton apparatus accelerates slowly from each stop and must slow/clear every intersection — even running
      lights-and-siren — so a car ETA over-states how far an engine actually gets.`],
    ["What speed does the model assume, exactly?",
     `Coverage uses real street-network drive times from the <b>Valhalla</b> routing engine on OpenStreetMap
      (the <code>auto</code> profile, which applies posted/road-class speeds plus turn &amp; intersection penalties).
      A tunable <b>speed factor</b> (default <b>1.0</b>, ISO-aligned) lets analysts credit code-3 speed (e.g. 1.2–1.3)
      if Mesa's data supports it — set it in <code>js/app.js</code> and <code>scripts/iso.py</code>.`],
    ["What's counted in the 4 and 8 minutes?",
     `<b>Travel time only.</b> NFPA 1710's full clock is ~1 min alarm processing + ~1–1.5 min turnout + travel. The
      4-minute band is the first-due engine's travel; the 8-minute band is the full first-alarm assignment / EMS travel.
      Dispatch and turnout are fixed by staffing/process, not by station location, so they're not in the map.`],
    ["Why isochrones instead of circles?",
     `A circle assumes equal speed in every direction. Real reach follows the street grid and is blocked or bent by
      barriers — the Salt River, canals, the US-60 / Loop 202 / SR-24 freeways, and the airport — so every station's
      4-minute shape is irregular and different. That's why we draw true drive-time polygons.`],
    ["What drives “demand” (where coverage is needed)?",
     `A 0.3-mile grid over the serviceable city, each cell weighted by the greater of its <b>block-group population
      density</b> (Mesa Planning/Demographics; citywide median ≈ ${Number(m.median_density).toLocaleString()}/sq mi) and
      its <b>General Plan 2050 placetype intensity</b> — so built neighborhoods count by their people and planned
      Employment/Urban centers count before they're built.`],
    ["What are county islands and mutual aid?",
     `<b>County islands</b> (${m.counts.county_islands}) are unincorporated Maricopa pockets served by Rural Metro —
      excluded from Mesa's serviceable area so no station is wasted on them. <b>Mutual aid</b> (${m.counts.mutual_aid}
      sister stations) is shown for context and, in the “+ Mutual aid” lens, used only to find Mesa's true gaps — never
      to justify a Mesa station covering a neighbor's gap.`],
    ["How are the recommended sites chosen?",
     `A greedy <b>Maximal Covering Location</b> model: with the 22 existing + 2 funded stations fixed, each new station is
      placed where it <b>captures the most still-uncovered Mesa demand</b> within 4 minutes, at ≥1.6 mi spacing. Coverage
      efficiency (the share of its reach on Mesa-served ground) is a <i>light tie-breaker</i> only. First two picks = the
      2028 bond; the rest = the buildout sequence, each capturing less new demand than the last.`],
    ["Why pick a station near the border (e.g. Power & Ray) if much of its reach is outside Mesa?",
     `Because it covers the <b>most Mesa residents</b> of the remaining options — most of Mesa's interior is already inside
      4 minutes, so the largest unmet demand sits in the growing SE/edge areas. Reach that extends into Gilbert or Queen
      Creek doesn't subtract any Mesa coverage (and Mesa answers mutual-aid calls there anyway). We <i>report</i> that
      station's efficiency (e.g. “39% serves Mesa”) for transparency, but we don't reject it for it — rejecting it would
      mean covering fewer Mesa residents. A truly wasteful corner site is avoided automatically because it would cover little
      Mesa demand in the first place.`],
    ["How does the live editor recompute coverage?",
     `When you drag or add a station it's snapped to the road network (OSRM) and a fresh Valhalla isochrone is fetched;
      your browser then re-tests every demand-grid cell against the new coverage. The math is identical to the offline
      model, so an unedited map reports the same numbers.`],
    ["Biggest caveat / how to make it even better?",
     `Feed in Mesa's <b>CAD incident data</b>: actual incident locations would replace the land-use demand proxy, and
      measured 90th-percentile travel times would calibrate the speed factor precisely. Also note greenfield SE reach is
      understated today because those roads aren't built yet — re-run as the network grows.`],
  ];
  document.getElementById("mFaq").innerHTML=
    `<p class="lead" style="margin-top:0">What drives the response-time / coverage areas — for future Mesa analysts.</p>`+
    qa.map(([q,a])=>`<div class="faq-item"><div class="faq-q">${q}</div><div class="faq-a">${a}</div></div>`).join("");
  document.getElementById("mMethod").innerHTML=`
   <p class="lead" style="margin-top:0">An independent planning model for Mesa's next fire stations, on public + City of Mesa data. <b>Not</b> an official Mesa FMD document.</p>
   <h3>Standard of cover</h3><p><b>NFPA 1710</b>: ~3 min dispatch+turnout, then <b>4 min</b> first-engine travel and <b>8 min</b> full first-alarm, 90% of the time; ISO wants an engine within <b>1.5 road miles</b>.</p>
   <h3>Coverage = network isochrones</h3><p>Each station's 4- &amp; 8-min reach is computed on the real OSM street network (Valhalla) — not a circle — so it reflects road connectivity, speeds, and barriers (Salt River, freeways, airport). In <b>Edit</b> mode, moved/added stations are snapped to the road network (OSRM) and re-routed live.</p>
   <h3>Demand — the City's own data</h3><p>0.3-mi grid, each cell = max(block-group population density ÷ citywide median, General Plan 2050 placetype intensity). Masked to the <b>serviceable area</b> (incorporated Mesa from <code>BaseMap/cityboundary</code>) minus the ${m.counts.county_islands} county islands.</p>
   <h3>Two lenses</h3><p><b>Mesa only (default):</b> counts Mesa engines only. <b>+ Mutual aid:</b> also counts ${m.counts.mutual_aid} sister stations to find true gaps — never to fill neighbors' gaps. (Switching the lens also shows the sister stations &amp; their coverage.)</p>
   <h3>Siting objective</h3><p>Greedy <b>Maximal Covering Location</b>: each new station maximizes still-uncovered <b>Mesa demand</b> reached in 4 minutes, at ≥1.6 mi spacing. Coverage efficiency (share of reach on Mesa land) is a light tie-breaker and a reported stat — never a hard penalty — so a high-demand border site is still chosen because it covers the most Mesa residents. First two picks = 2028 bond; rest = buildout.</p>
   <h3>Live editing</h3><p>Drag a proposed/added station (snaps to road), or add/delete any (built stations warn unless you turn warnings off). Coverage % recomputes in your browser against the real demand grid. <b>Reset</b> returns to the optimized model.</p>
   <h3>Limitations &amp; next</h3><ul><li>Highest value: feed real CAD incident locations (for demand) + measured 90th-pct travel times (to calibrate speeds). Mesa's portal exposes performance metrics but not an accessible spatial incident feed today.</li><li>Greenfield isochrones understate future reach (unbuilt roads).</li></ul>
   <h3>Sources</h3><p>Stations: Mesa FMD/NERIS. Population, land use, boundary &amp; islands: City of Mesa GIS. Isochrones: Valhalla/OSM. Snap: OSRM. Sister stations: OSM. 223/224: 2024 Public Safety Bond.</p>`;
}
function renderOverview(lm){
  const m=DATA.metrics,pane=document.querySelector('[data-pane="overview"]');
  const S=m.strategies[state.strategy],base=S.funded;
  lm=lm||liveMetrics();
  const phaseLabel={funded:"Current (22 + funded 223/224)",bond2028:"+ 2028 bond (225 & 226)",buildout:"Full buildout (+227–230)"}[state.phase];
  pane.innerHTML=`
    <p class="lead">Where Mesa's next stations should go — on a <b>real street-network 4-minute drive</b> (NFPA 1710),
    with demand from the <b>City's own data</b> (block-group population + General Plan 2050 land use). Default lens is
    <b>Mesa-only</b>, so Mesa dollars serve Mesa residents. Tap <b>✎ Edit</b> to drag, add or remove stations and watch
    coverage update live.</p>
    <div style="font-size:12px;color:#5b6675;margin-bottom:9px">Lens: <b>${state.strategy==="mesa"?"Mesa only":"Counting mutual aid"}</b> · Showing: <b>${phaseLabel}</b></div>
    <div class="metric-row">
      <div class="metric"><div class="big">${lm.a4.toFixed(1)}%</div><div class="lbl">City area within a 4-min engine drive (live)</div>
        ${state.phase!=="funded"?`<div class="delta up">▲ ${(lm.a4-base.area4).toFixed(1)} pts vs today</div>`:""}</div>
      <div class="metric"><div class="big">${lm.a8.toFixed(1)}%</div><div class="lbl">City area within an 8-min full alarm (live)</div>
        ${state.phase!=="funded"?`<div class="delta up">▲ ${(lm.a8-base.area8).toFixed(1)} pts vs today</div>`:""}</div>
    </div>
    <h2 class="sec">Optimized model — 4-min coverage by phase</h2>
    ${bar("Current (incl. 223/224)",base.area4)}
    ${bar("+ 2028 bond (225, 226)",S.bond2028.area4)}
    ${bar("+ Buildout (227–230)",S.buildout.area4)}
    <h2 class="sec">Optimized for Mesa coverage</h2>
    <p class="lead" style="margin-top:0">Sites are chosen to <b>maximize the Mesa demand reached within 4 minutes</b>
    (greedy Maximal Covering Location). <b>Coverage efficiency</b> — the share of a station's reach on Mesa-served ground —
    is a <i>light tie-breaker</i> and a reported stat, not a hard penalty: a border station still covers all of its Mesa
    residents, and reach spilling into a neighbor isn't subtracted (Mesa runs mutual aid there too). The
    <b>${m.counts.county_islands} county islands</b> (Rural Metro) are excluded, so none is wasted on non-Mesa land.</p>
    <h2 class="sec">Demand: real city data</h2>
    <p class="lead" style="margin-top:0">Each 0.3-mi cell = max(block-group population density ÷ citywide median ≈
    ${Number(m.median_density).toLocaleString()}/sq mi, General Plan 2050 placetype intensity). Toggle <b>Population density</b>
    and <b>Planned developments</b> to see the inputs.</p>
    <h2 class="sec">Legend</h2>
    <div class="legend">
      <div class="li"><span class="dot" style="background:#0ea5e9"></span><b>4 min</b> first-due · <span class="dot" style="background:#7dd3fc;margin-left:4px"></span><b>8 min</b> full alarm</div>
      <div class="li"><span class="dot" style="background:#ef4444"></span>Coverage gaps (demand &gt; 4 min)</div>
      <div class="li"><span class="dot ex"></span>Existing · <span class="dot co"></span>Funded 223/224 · <span class="dot p28"></span>2028 · <span class="dot bu"></span>Buildout</div>
      <div class="li"><span class="dot" style="background:#0d9488"></span>Added by you · <span class="dot ma"></span>Mutual aid (${m.counts.mutual_aid}) · <span class="dot" style="background:repeating-linear-gradient(45deg,#cbd5e1,#cbd5e1 2px,#fff 2px,#fff 4px);border:1px dashed #475569"></span>County island</div>
    </div>
    <p class="lead" style="font-size:11.5px;color:#9aa6b5;margin-top:14px">Independent planning model — not an official Mesa FMD
    document. Funded 223/224 reflect city plans; 225–230 are analytical forecasts. Tap <b>？ Help</b> for the FAQ &amp; methodology.</p>`;
}
function bar(label,val){return `<div style="margin:9px 0"><div style="display:flex;justify-content:space-between;font-size:12.5px;font-weight:700">
  <span>${label}</span><span>${val}%</span></div><div class="bar"><i style="width:${val}%;background:linear-gradient(90deg,#0ea5e9,#7c3aed)"></i></div></div>`;}
function renderStations(){
  const pane=document.querySelector('[data-pane="stations"]');
  const g=(t,st)=>{const list=DATA.stations.filter(s=>s.status===st&&(st.startsWith("proposed")?s.strategy===state.strategy:true));
    if(!list.length)return"";const cls=STATUS_CLS[st];
    return `<h2 class="sec">${t} (${list.length})</h2>`+list.map(s=>{
      const pill=st==="committed"?'<span class="pill co">Funded</span>':st==="proposed-2028"?'<span class="pill p28">2028</span>':st==="proposed-buildout"?'<span class="pill bu">Forecast</span>':'';
      return `<div class="st" data-id="${s.id}"><div class="num ${cls}">${s.id}</div><div class="meta">
        <b>${s.name.replace(/^(2028 Bond|Buildout) — /,'')}</b>${pill}<div>${s.address}</div></div></div>`;}).join("");};
  let html=`<div style="font-size:12px;color:#5b6675;margin-bottom:6px">Proposals for the <b>${state.strategy==="mesa"?"Mesa-only":"+ mutual aid"}</b> lens.</div>`;
  html+=g("Proposed — 2028 bond","proposed-2028")+g("Buildout forecast","proposed-buildout")+g("Funded — 2024 bond","committed")+g("Existing stations","existing");
  const byJur={};DATA.mutual.forEach(a=>(byJur[a.jurisdiction]=byJur[a.jurisdiction]||[]).push(a));
  html+=`<h2 class="sec">Mutual-aid sister stations (${DATA.mutual.length})</h2>`;
  Object.keys(byJur).sort().forEach(j=>html+=`<div class="st"><div class="num ma">◆</div><div class="meta"><b>${j}</b><div>${byJur[j].length} within 3.5 mi of Mesa</div></div></div>`);
  pane.innerHTML=html;
  pane.querySelectorAll(".st[data-id]").forEach(el=>el.addEventListener("click",()=>focusStation(el.dataset.id)));
}
function renderWhy(){
  const pane=document.querySelector('[data-pane="why"]');
  const f=DATA.stations.filter(s=>s.status==="committed");
  const b=DATA.stations.filter(s=>s.status==="proposed-2028"&&s.strategy===state.strategy).sort((x,y)=>x.priority-y.priority);
  const bo=DATA.stations.filter(s=>s.status==="proposed-buildout"&&s.strategy===state.strategy).sort((x,y)=>x.priority-y.priority);
  const clean=a=>a.replace('~ ','').replace(', Mesa, AZ (analytical site)','');
  let html=`<p class="lead">Recommendations for the <b>${state.strategy==="mesa"?"Mesa-only":"+ mutual aid"}</b> lens — a greedy
   <b>Maximal Covering Location</b> model that <b>maximizes Mesa demand reached within 4 minutes</b> at ≥1.6 mi spacing. Coverage
   efficiency (“% serves Mesa”, shown below) is a light tie-breaker, not a penalty — so a high-demand border site like Power &amp; Ray
   is still chosen, because it covers the most Mesa residents even though some reach spills across the line. Use <b>✎ Edit</b> to test your own placements.</p>
   <h2 class="sec">Already funded (2024 bond)</h2>`;
  f.forEach(s=>html+=`<div class="why co"><h3>Station ${s.id} — ${s.name}</h3><span class="stat">${clean(s.address)}</span><p>${s.note}</p></div>`);
  html+=`<h2 class="sec">Recommended for the 2028 bond — next two</h2>`;b.forEach(s=>html+=card(s,"p28",clean));
  html+=`<h2 class="sec">Beyond 2028 — buildout sequence</h2>`;bo.forEach(s=>html+=card(s,"",clean));
  pane.innerHTML=html;
}
function card(s,cls,clean){const e=s.efficiency_pct>=85?"#15a34a":s.efficiency_pct>=70?"#ca8a04":"#dc2626";
  return `<div class="why ${cls}"><h3>#${s.priority} · Station ${s.id} — ${s.name.replace(/^(2028 Bond|Buildout) — /,'')}</h3>
    <span class="stat">📍 ${clean(s.address)}</span><span class="stat">+${s.captured_pct_of_city}% demand &lt;4 min</span>
    <span class="stat" style="color:${e}">${s.efficiency_pct}% serves Mesa</span>
    <span class="stat">gap to #${s.nearest_station}: ${s.gap_to_nearest_mi} mi</span><p>${s.note}</p></div>`;}
function focusStation(id){const s=DATA.stations.find(x=>x.id===id&&(x.strategy==="all"||x.strategy===state.strategy))||DATA.stations.find(x=>x.id===id);
  if(!s||s.lat==null)return;
  if(s.status==="proposed-buildout")setPhase("buildout");else if(s.status==="proposed-2028"&&state.phase==="funded")setPhase("bond2028");
  MAP.flyTo([s.lat,s.lon],14,{duration:.6});
  const live=LIVE.find(x=>x.id===id);setTimeout(()=>{if(live&&live._marker)live._marker.openPopup();},650);
  if(window.matchMedia("(max-width:759px)").matches)collapsePanel(true);}

/* ---------- state changes ---------- */
function setPhase(p){state.phase=p;syncBtns();refresh();}
function setStrategy(s){state.strategy=s;state.mutual=(s==="aid");  // lens drives sister-station visibility
  buildLive();syncBtns();refresh();renderStations();renderWhy();}
function setBase(b){state.base=b;
  if(b==="sat"){MAP.removeLayer(BASE_MAP);BASE_SAT.addTo(MAP);}else{MAP.removeLayer(BASE_SAT);BASE_MAP.addTo(MAP);}
  BASE_MAP.bringToBack&&BASE_MAP.bringToBack();BASE_SAT.bringToBack&&BASE_SAT.bringToBack();syncBtns();}
function syncBtns(){document.querySelectorAll(".phase").forEach(b=>b.classList.toggle("active",b.dataset.phase===state.phase));
  document.querySelectorAll(".lensbtn").forEach(b=>b.classList.toggle("active",b.dataset.strat===state.strategy));
  document.querySelectorAll("#baseSeg .segbtn").forEach(b=>b.classList.toggle("active",b.dataset.base===state.base));}
function collapsePanel(c){document.getElementById("panel").classList.toggle("collapsed",c);}
function setEdit(on){state.edit=on;state.adding=false;
  document.getElementById("editToggle").classList.toggle("on",on);
  document.getElementById("editToggle").textContent=on?"✓ Done":"✎ Edit";
  document.getElementById("editBar").classList.toggle("hidden",!on);
  document.getElementById("addBtn").classList.remove("arm");MAP.getContainer().style.cursor="";
  if(on&&window.matchMedia("(max-width:759px)").matches)collapsePanel(true);
  rebuild();updateLive();}

function wireUI(){
  document.querySelectorAll(".phase").forEach(b=>b.addEventListener("click",()=>setPhase(b.dataset.phase)));
  document.querySelectorAll(".lensbtn").forEach(b=>b.addEventListener("click",()=>setStrategy(b.dataset.strat)));
  document.querySelectorAll("#baseSeg .segbtn").forEach(b=>b.addEventListener("click",()=>setBase(b.dataset.base)));
  const onlyLayers=()=>applyLayers();
  const chk=(id,k)=>document.getElementById(id).addEventListener("change",e=>{state[k]=e.target.checked;onlyLayers();});
  chk("band4","band4");chk("band8","band8");chk("gapsChk","gaps");chk("devChk","dev");chk("popChk","pop");chk("islandChk","islands");
  // layers FAB
  const lp=document.getElementById("layersPanel"),lb=document.getElementById("layersBtn");
  const setLayers=open=>{lp.classList.toggle("open",open);lb.classList.toggle("active",open);};
  lb.addEventListener("click",()=>setLayers(!lp.classList.contains("open")));
  document.getElementById("layersClose").addEventListener("click",()=>setLayers(false));
  if(!window.matchMedia("(max-width:759px)").matches) setLayers(true);   // open by default on desktop
  // panel tabs
  document.querySelectorAll(".ptab").forEach(t=>t.addEventListener("click",()=>{
    document.querySelectorAll(".ptab").forEach(x=>x.classList.remove("active"));
    document.querySelectorAll(".tabpane").forEach(x=>x.classList.remove("active"));
    t.classList.add("active");document.querySelector(`[data-pane="${t.dataset.tab}"]`).classList.add("active");
    if(window.matchMedia("(max-width:759px)").matches)collapsePanel(false);}));
  document.getElementById("panelHandle").addEventListener("click",()=>document.getElementById("panel").classList.toggle("collapsed"));
  // edit
  document.getElementById("editToggle").addEventListener("click",()=>setEdit(!state.edit));
  document.getElementById("addBtn").addEventListener("click",()=>{state.adding=!state.adding;
    document.getElementById("addBtn").classList.toggle("arm",state.adding);
    MAP.getContainer().style.cursor=state.adding?"crosshair":"";
    toast(state.adding?"Tap the map to drop a station":"Add cancelled");});
  document.getElementById("resetBtn").addEventListener("click",resetPlan);
  document.getElementById("warnBtn").addEventListener("click",()=>{state.warnBuilt=!state.warnBuilt;
    const b=document.getElementById("warnBtn");b.textContent=`⚠︎ Warnings: ${state.warnBuilt?"On":"Off"}`;b.setAttribute("aria-pressed",state.warnBuilt);});
  // help modal (FAQ + methodology tabs)
  const modal=document.getElementById("modal");
  document.getElementById("helpBtn").addEventListener("click",()=>modal.classList.remove("hidden"));
  document.getElementById("modalClose").addEventListener("click",()=>modal.classList.add("hidden"));
  modal.addEventListener("click",e=>{if(e.target.id==="modal")modal.classList.add("hidden");});
  document.querySelectorAll(".mtab").forEach(t=>t.addEventListener("click",()=>{
    document.querySelectorAll(".mtab").forEach(x=>x.classList.remove("active"));t.classList.add("active");
    document.getElementById("mFaq").classList.toggle("hidden",t.dataset.mtab!=="faq");
    document.getElementById("mMethod").classList.toggle("hidden",t.dataset.mtab!=="method");}));
}
