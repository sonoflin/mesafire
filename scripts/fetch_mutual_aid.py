"""
Fetch neighboring-jurisdiction ("sister") fire stations near Mesa for mutual-aid
context, from OpenStreetMap via Overpass. Writes data/mutual_aid.json.

Mesa does NOT site its stations to fill neighbors' gaps, but in the Phoenix Valley's
automatic/mutual-aid system the closest unit responds across city lines — so a station
in Gilbert or Tempe just across the border can backfill a Mesa edge, and Mesa units
answer into their areas too. We keep sister stations within ~3.5 mi of the Mesa boundary.

Run:  python scripts/fetch_mutual_aid.py
"""
import json, math, os, urllib.request, urllib.parse

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def P(*a): return os.path.join(HERE, *a)

BBOX = (33.15, -112.05, 33.60, -111.45)   # S, W, N, E — SE Valley
NEAR_MI = 3.5                              # keep stations within this of Mesa's edge
EPS = ["https://overpass-api.de/api/interpreter",
       "https://overpass.kumi.systems/api/interpreter"]

MI_PER_DEG_LAT = 69.0
def mi_per_deg_lon(lat): return 69.0 * math.cos(math.radians(lat))
def miles(a, b):  # a,b = (lat,lon)
    mlat = (a[0]+b[0])/2
    return math.hypot((b[0]-a[0])*MI_PER_DEG_LAT, (b[1]-a[1])*mi_per_deg_lon(mlat))

def jurisdiction(tags):
    s = ((tags.get("operator") or "") + " " + (tags.get("name") or "")).lower()
    table = [("mesa","Mesa"),("gilbert","Gilbert"),("chandler","Chandler"),
             ("tempe","Tempe"),("queen creek","Queen Creek"),("apache junction","Apache Junction"),
             ("scottsdale","Scottsdale"),("salt river","Salt River (SRPMIC)"),("srpmic","Salt River (SRPMIC)"),
             ("gila river","Gila River"),("phoenix","Phoenix"),
             ("rural/metro","Rural Metro"),("rural metro","Rural Metro"),
             ("superstition","Superstition Fire & Medical")]
    for key, name in table:
        if key in s: return name
    return tags.get("operator") or tags.get("name") or "Other"

def load_boundary_rings():
    fc = json.load(open(P("data","mesa_boundary.geojson")))
    g = fc["features"][0]["geometry"]
    polys = g["coordinates"] if g["type"]=="MultiPolygon" else [g["coordinates"]]
    # outer rings, as (lat,lon) vertex lists (subsampled for speed)
    rings = []
    for poly in polys:
        ring = [(c[1], c[0]) for c in poly[0]]
        rings.append(ring[::3] if len(ring) > 300 else ring)
    return rings

def in_ring(lon, lat, ring_lonlat):
    inside=False; n=len(ring_lonlat); j=n-1
    for i in range(n):
        xi,yi=ring_lonlat[i]; xj,yj=ring_lonlat[j]
        if ((yi>lat)!=(yj>lat)) and (lon < (xj-xi)*(lat-yi)/(yj-yi)+xi): inside=not inside
        j=i
    return inside

def main():
    q = (f"[out:json][timeout:90];"
         f"( node[amenity=fire_station]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});"
         f"  way[amenity=fire_station]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]}); );"
         f"out center tags;")
    els = None
    for ep in EPS:
        try:
            data = urllib.parse.urlencode({"data": q}).encode()
            req = urllib.request.Request(ep, data=data, headers={"User-Agent":"mesa-fire-planning/1.0"})
            els = json.load(urllib.request.urlopen(req, timeout=95)).get("elements", [])
            print(f"Overpass {ep.split('//')[1][:24]} -> {len(els)} stations"); break
        except Exception as e:
            print(f"  {ep} failed: {e}")
    if not els: raise SystemExit("Overpass unavailable")

    boundary = json.load(open(P("data","mesa_boundary.geojson")))["features"][0]["geometry"]
    bpolys = boundary["coordinates"] if boundary["type"]=="MultiPolygon" else [boundary["coordinates"]]
    def inside_mesa(lat, lon):
        return any(in_ring(lon, lat, poly[0]) for poly in bpolys)
    rings = load_boundary_rings()
    def dist_to_edge(lat, lon):
        return min(miles((lat,lon), v) for ring in rings for v in ring)

    seen=set(); out=[]
    for e in els:
        lat = e.get("lat") or (e.get("center") or {}).get("lat")
        lon = e.get("lon") or (e.get("center") or {}).get("lon")
        if lat is None: continue
        tags = e.get("tags", {})
        jur = jurisdiction(tags)
        if jur == "Mesa": continue                 # Mesa is the authority; use our own roster
        if inside_mesa(lat, lon): continue          # skip anything inside the city
        if dist_to_edge(lat, lon) > NEAR_MI: continue
        key = (round(lat,4), round(lon,4))
        if key in seen: continue
        seen.add(key)
        out.append({
            "name": tags.get("name") or f"{jur} Fire Station",
            "jurisdiction": jur,
            "lat": round(lat,6), "lon": round(lon,6),
        })

    out.sort(key=lambda s:(s["jurisdiction"], s["name"]))
    json.dump(out, open(P("data","mutual_aid.json"),"w",encoding="utf-8"), indent=2)
    from collections import Counter
    c = Counter(s["jurisdiction"] for s in out)
    print(f"Kept {len(out)} sister stations within {NEAR_MI} mi of Mesa:")
    for k,v in c.most_common(): print(f"   {v:2d}  {k}")

if __name__ == "__main__":
    main()
