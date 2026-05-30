"""
Pull the City of Mesa's OWN authoritative GIS into the model (no API key needed):

  * Block Groups (Planning/Demographics)  -> real population & housing per area
  * General Plan 2050 Placetypes (Planning/GeneralPlan) -> adopted future land-use
    intensity, which captures planned growth even where today's population is ~0.

Writes data/blockgroups.geojson (slim, for the population choropleth + demand) and
data/placetypes.json (compact rings, for the demand surface).

Run:  python scripts/fetch_city_data.py
"""
import json, os, urllib.request, urllib.parse

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def P(*a): return os.path.join(HERE, *a)
BASE = "https://gis.mesaaz.gov/mesaaz/rest/services/Planning/"
ENV  = "-111.92,33.25,-111.55,33.54"   # Mesa + a little margin (xmin,ymin,xmax,ymax)
OFFSET = 0.0004                          # geometry generalization in degrees (~40 m)

def get(url, t=120):
    r = urllib.request.Request(url, headers={"User-Agent":"mesa-fire-planning/1.0"})
    return json.load(urllib.request.urlopen(r, timeout=t))

def fetch(layer, fields):
    """Page through an ArcGIS layer, return list of GeoJSON features (generalized)."""
    feats=[]; offset=0; page=1000
    while True:
        q=("geometry="+ENV+"&geometryType=esriGeometryEnvelope&inSR=4326"
           "&spatialRel=esriSpatialRelIntersects&where=1%3D1"
           "&outFields="+",".join(fields)+"&returnGeometry=true&outSR=4326"
           "&maxAllowableOffset="+str(OFFSET)+
           "&resultOffset="+str(offset)+"&resultRecordCount="+str(page)+"&f=geojson")
        d=get(BASE+layer+"/query?"+q)
        fs=d.get("features",[])
        feats+=fs
        if len(fs)<page: break
        offset+=page
        if offset>40000: break
    return feats

def rings_of(geom):
    """Flatten a GeoJSON Polygon/MultiPolygon into a list of rings (even-odd ray casting)."""
    if not geom: return []
    if geom["type"]=="Polygon": return [r for r in geom["coordinates"]]
    if geom["type"]=="MultiPolygon": return [r for poly in geom["coordinates"] for r in poly]
    return []
def bbox_of(rings):
    xs=[c[0] for r in rings for c in r]; ys=[c[1] for r in rings for c in r]
    return [min(xs),min(ys),max(xs),max(ys)]
def rnd(rings,p=6): return [[[round(c[0],p),round(c[1],p)] for c in r] for r in rings]

def main():
    # ---- Block groups (population) ----
    print("Fetching block groups (population)...")
    bg=fetch("Demographics/MapServer/1",
             ["GEOID","TOTAL_POP","POP_PER_SQMI","TOTAL_HOUSING_UNITS","SQMI"])
    print(f"  {len(bg)} block groups")
    # slim geojson for choropleth + demand
    out=[]
    for f in bg:
        pr=f.get("properties",{}); g=f.get("geometry")
        if not g: continue
        out.append({"type":"Feature",
            "properties":{"pop":pr.get("TOTAL_POP") or 0,
                          "dens":pr.get("POP_PER_SQMI") or 0,
                          "hu":pr.get("TOTAL_HOUSING_UNITS") or 0},
            "geometry":g})
    json.dump({"type":"FeatureCollection","features":out},
              open(P("data","blockgroups.geojson"),"w"),separators=(",",":"))

    # ---- General Plan 2050 placetypes (future intensity) ----
    print("Fetching General Plan 2050 placetypes...")
    pt=fetch("GeneralPlan/MapServer/0",["Placetype"])
    print(f"  {len(pt)} placetype polygons")
    comp=[]
    for f in pt:
        g=f.get("geometry"); pr=f.get("properties",{})
        rings=rings_of(g)
        if not rings: continue
        comp.append({"pt":pr.get("Placetype") or "Unknown","r":rnd(rings),"bb":bbox_of(rings)})
    json.dump(comp,open(P("data","placetypes.json"),"w"),separators=(",",":"))

    # quick stats
    from collections import Counter
    c=Counter(x["pt"] for x in comp)
    print("  placetypes:",dict(c.most_common()))
    pops=[f["properties"]["pop"] for f in out]
    print(f"  total population in extent: {sum(pops):,} across {len(out)} BGs")
    print("Wrote data/blockgroups.geojson and data/placetypes.json")

if __name__=="__main__":
    main()
