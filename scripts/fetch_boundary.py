"""
Build Mesa's authoritative city boundary + county islands from the City's OWN GIS
(BaseMap/cityboundary), replacing the earlier OpenStreetMap approximation.

Mesa models the incorporated city as ~29 separate polygons; the unincorporated
"county islands" (served by Rural Metro) are the gaps ENCLOSED by those polygons.
We union the polygons (shapely); the union's interior holes ARE the county islands.
This is materially more accurate than OSM, especially in SE Mesa.

Writes:
  data/mesa_boundary.geojson  -> the unioned city limits (MultiPolygon WITH island holes)
  data/county_islands.geojson -> the island polygons (for display)

Run:  python scripts/fetch_boundary.py   (requires shapely)
"""
import json, os, math, urllib.request
from shapely.geometry import shape, mapping, Polygon
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def P(*a): return os.path.join(HERE, *a)
URL = ("https://gis.mesaaz.gov/mesaaz/rest/services/BaseMap/cityboundary/MapServer/0/query"
       "?where=1%3D1&outFields=*&returnGeometry=true&outSR=4326&f=geojson")

def mpl(lat): return 69.0*math.cos(math.radians(lat))
def ring_sqmi(coords):
    a=0
    for i in range(len(coords)-1):
        a+=coords[i][0]*coords[i+1][1]-coords[i+1][0]*coords[i][1]
    mlat=sum(p[1] for p in coords)/len(coords)
    return abs(a)/2.0*69.0*mpl(mlat)

def main():
    req=urllib.request.Request(URL,headers={"User-Agent":"mesa-fire/1.0"})
    fc=json.load(urllib.request.urlopen(req,timeout=120))
    polys=[shape(f["geometry"]) for f in fc["features"] if f.get("geometry")]
    print(f"city polygons: {len(polys)}")
    union=unary_union([p.buffer(0) for p in polys]).buffer(0)
    union=union.simplify(0.00015, preserve_topology=True)
    geoms=list(union.geoms) if union.geom_type=="MultiPolygon" else [union]

    # boundary (with holes) for masking + outline
    json.dump({"type":"FeatureCollection","features":[
        {"type":"Feature","properties":{"name":"City of Mesa (incorporated)"},"geometry":mapping(union)}]},
        open(P("data","mesa_boundary.geojson"),"w"),separators=(",",":"))

    # county islands = interior rings (holes) of the union, above a small area floor
    islands=[]
    for g in geoms:
        for interior in g.interiors:
            coords=[list(c) for c in interior.coords]
            sq=ring_sqmi(coords)
            if sq>0.008:
                islands.append((coords,round(sq,2)))
    json.dump({"type":"FeatureCollection","features":[
        {"type":"Feature","properties":{"kind":"county-island","sqmi":sq},
         "geometry":{"type":"Polygon","coordinates":[c]}} for c,sq in islands]},
        open(P("data","county_islands.geojson"),"w"),separators=(",",":"))

    se=[sq for c,sq in islands if (sum(p[1] for p in c)/len(c))<33.37 and (sum(p[0] for p in c)/len(c))>-111.72]
    print(f"county islands: {len(islands)} (total {round(sum(s for _,s in islands),1)} sq mi)")
    print(f"  sizes sq mi: {sorted([s for _,s in islands],reverse=True)}")
    print(f"  SE-Mesa islands (lat<33.37, lon>-111.72): {sorted(se,reverse=True)}")
    print("Wrote data/mesa_boundary.geojson (authoritative) and data/county_islands.geojson")

if __name__=="__main__":
    main()
