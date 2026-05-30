"""
Network drive-time isochrones via the public Valhalla routing engine (real OSM road
network, barrier-aware, no API key). Results are cached to data/iso_cache.json so the
model is cheap to re-run and only new points hit the network.

Costing note: Valhalla 'auto' free-flow speeds are used as a proxy for code-3 emergency
response on uncongested roads. This is a defensible, conservative stand-in for true
apparatus speed (which can exceed limits but slows at intersections). See METHODOLOGY.md.
"""
import json, math, os, time, urllib.request, urllib.parse

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(HERE, "data", "iso_cache.json")
ENDPOINT = "https://valhalla1.openstreetmap.de/isochrone"
CONTOURS = [4, 8]                 # response-time bands (minutes)
# Emergency-speed assumption (see the in-app FAQ). 1.0 = travel at routed auto speed, which
# matches ISO's first-due-engine rule (1.5 road mi in 4 min ~= 22.5 mph). Raise toward ~1.2-1.3
# to credit code-3 speed once calibrated to Mesa CAD travel times. MUST match js/app.js SPEED_FACTOR.
# If you change it, delete data/iso_cache.json so isochrones are refetched.
SPEED_FACTOR = 1.0
MI_PER_DEG_LAT = 69.0

_cache = None
def _load():
    global _cache
    if _cache is None:
        _cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    return _cache
def _save():
    json.dump(_cache, open(CACHE, "w"), separators=(",", ":"))

def _key(lat, lon): return f"{round(lat,5)},{round(lon,5)}"

def _circle(lat, lon, r_mi, n=48):
    ring=[]
    for i in range(n+1):
        t=2*math.pi*i/n
        dlat=(r_mi/MI_PER_DEG_LAT)*math.cos(t)
        dlon=(r_mi/(MI_PER_DEG_LAT*math.cos(math.radians(lat))))*math.sin(t)
        ring.append([round(lon+dlon,6),round(lat+dlat,6)])
    return {"type":"Polygon","coordinates":[ring]}

def _fetch(lat, lon):
    times=[c*SPEED_FACTOR for c in CONTOURS]   # scale travel time by the emergency-speed factor
    req={"locations":[{"lat":lat,"lon":lon}],"costing":"auto",
         "contours":[{"time":t} for t in times],
         "polygons":True,"denoise":0.4,"generalize":40}
    url=ENDPOINT+"?json="+urllib.parse.quote(json.dumps(req))
    r=urllib.request.Request(url,headers={"User-Agent":"mesa-fire-planning/1.0"})
    d=json.load(urllib.request.urlopen(r,timeout=45))
    byc={}
    for f in d.get("features",[]):
        c=f["properties"].get("contour")
        if c is None: continue
        byc[round(c*10)]=f["geometry"]
    out={str(band):byc.get(round(t*10)) for band,t in zip(CONTOURS,times)}
    if not out.get("4") or not out.get("8"): raise ValueError("missing contour")
    return out

def get(lat, lon, retries=3):
    """Return {'4': geom, '8': geom, 'approx': bool}. Cached."""
    c=_load(); k=_key(lat,lon)
    if k in c: return c[k]
    last=None
    for i in range(retries):
        try:
            geoms=_fetch(lat,lon)
            geoms["approx"]=False
            c[k]=geoms; _save(); time.sleep(1.1)
            return geoms
        except Exception as e:
            last=e; time.sleep(2+2*i)
    # fallback: circuity-adjusted circles so the model still runs
    geoms={"4":_circle(lat,lon,1.5/1.30),"8":_circle(lat,lon,3.6/1.30),"approx":True}
    c[k]=geoms; _save()
    print(f"   ! isochrone fallback (circle) for {k}: {last}")
    return geoms
