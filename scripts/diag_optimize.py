"""
Diagnostic: is the buildout truly maximizing MESA coverage? Compares two objectives with a
DENSE candidate net (far more sites than the production seeding), using real isochrones:
  C) pure Mesa serviceable demand covered  (maximize Mesa coverage)
  E) demand x coverage-efficiency          (current production objective)
Reports the picks and the final Mesa 4-min coverage each objective achieves.
"""
import json, math, os, statistics
import iso
HERE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def P(*a): return os.path.join(HERE,*a)
MI=69.0
def mpl(l): return 69.0*math.cos(math.radians(l))
def miles(a,b,c,d): return math.hypot((c-a)*MI,(d-b)*mpl((a+c)/2))
def bbox(r):
    xs=[c[0] for c in r];ys=[c[1] for c in r];return(min(xs),min(ys),max(xs),max(ys))
def prep(g):
    out=[];polys=g["coordinates"] if g["type"]=="MultiPolygon" else [g["coordinates"]]
    for p in polys:
        if p and p[0]: out.append((p[0],p[1:],bbox(p[0])))
    return out
def inr(lon,lat,r):
    ins=False;n=len(r);j=n-1
    for i in range(n):
        xi,yi=r[i];xj,yj=r[j]
        if((yi>lat)!=(yj>lat)) and (lon<(xj-xi)*(lat-yi)/(yj-yi)+xi): ins=not ins
        j=i
    return ins
def contains(parts,lon,lat):
    for o,h,bb in parts:
        if lon<bb[0] or lon>bb[2] or lat<bb[1] or lat>bb[3]: continue
        if inr(lon,lat,o) and not any(inr(lon,lat,x) for x in h): return True
    return False
NS=[(-111.857,"Alma School"),(-111.842,"Country Club"),(-111.833,"Center"),(-111.825,"Mesa Dr"),
 (-111.805,"Stapley"),(-111.789,"Gilbert"),(-111.771,"Lindsay"),(-111.755,"Val Vista"),(-111.737,"Greenfield"),
 (-111.720,"Higley"),(-111.705,"Recker"),(-111.684,"Power"),(-111.670,"Sossaman"),(-111.662,"Hawes"),
 (-111.636,"Ellsworth"),(-111.618,"Crismon"),(-111.601,"Signal Butte"),(-111.583,"Meridian")]
EW=[(33.466,"McDowell"),(33.451,"McKellips"),(33.437,"Brown"),(33.422,"University"),(33.4155,"Main"),
 (33.407,"Broadway"),(33.393,"Southern"),(33.378,"Baseline"),(33.364,"Guadalupe"),(33.350,"Elliot"),
 (33.336,"Warner"),(33.321,"Ray"),(33.307,"Williams Field"),(33.293,"Pecos"),(33.278,"Germann")]
def xst(lat,lon): return f"{min(NS,key=lambda r:abs(r[0]-lon))[1]} & {min(EW,key=lambda r:abs(r[0]-lat))[1]}"

def main():
    grid=json.load(open(P("data","demand_grid.json")));GR=grid["cells"];NC=grid["ncells"];TOT=grid["total"]
    stations=json.load(open(P("data","stations.json")))
    cov={f"{f['properties']['station_id']}|{f['properties']['strategy']}|{f['properties']['band']}":f["geometry"] for f in json.load(open(P("data","coverage.geojson")))["features"]}
    bnd=prep(json.load(open(P("data","mesa_boundary.geojson")))["features"][0]["geometry"])
    funded=[s for s in stations if s["status"] in ("existing","committed")]
    fparts=[prep(cov[f"{s['id']}|all|4min"]) for s in funded if f"{s['id']}|all|4min" in cov]
    def covered_mask(parts_list):
        m=bytearray(NC)
        for parts in parts_list:
            for i in range(NC):
                if not m[i]:
                    c=GR[i]
                    if contains(parts,c[1],c[0]): m[i]=1
        return m
    base=covered_mask(fparts)
    def newcov(parts,mask):
        idx=[];b=0.0
        for i in range(NC):
            if not mask[i]:
                c=GR[i]
                if contains(parts,c[1],c[0]): b+=c[2];idx.append(i)
        return b,idx
    def eff(parts):
        x0=min(p[2][0] for p in parts);x1=max(p[2][2] for p in parts);y0=min(p[2][1] for p in parts);y1=max(p[2][3] for p in parts)
        sy=0.1/MI;sx=0.1/mpl((y0+y1)/2);t=s=0;y=y0
        while y<=y1:
            x=x0
            while x<=x1:
                if contains(parts,x,y):
                    t+=1
                    if contains(bnd,x,y): s+=1
                x+=sx
            y+=sy
        return s/t if t else 1.0
    # dense candidate net
    def far(la,lo,pts,d=1.6): return all(miles(la,lo,p[0],p[1])>=d for p in pts)
    fpts=[(s["lat"],s["lon"]) for s in funded]
    unc=[(GR[i][0],GR[i][1],GR[i][2]) for i in range(NC) if not base[i]]
    def near(la,lo): return sum(w for a,b,w in unc if abs(a-la)<0.02 and abs(b-lo)<0.024 and miles(la,lo,a,b)<=1.2)
    cand=[(GR[i][0],GR[i][1],near(GR[i][0],GR[i][1])) for i in range(NC) if far(GR[i][0],GR[i][1],fpts)]
    cand=[c for c in cand if c[2]>0];cand.sort(key=lambda c:-c[2])
    seeds=[];
    for la,lo,_ in cand:
        if far(la,lo,[(s[0],s[1]) for s in seeds],0.45): seeds.append((la,lo))
        if len(seeds)>=70: break
    print(f"dense candidate sites: {len(seeds)} (production used 30)")
    S=[]
    for k,(la,lo) in enumerate(seeds):
        g=iso.get(la,lo);pr=prep(g["4"]);S.append({"la":la,"lo":lo,"p":pr,"eff":eff(pr)})
        if (k+1)%15==0: print(f"  iso {k+1}/{len(seeds)}")
    def greedy(useEff,n=6):
        mask=bytearray(base);picks=[];used=set()
        for _ in range(n):
            best=None
            for j,sd in enumerate(S):
                if j in used: continue
                if not far(sd["la"],sd["lo"],[(p["la"],p["lo"]) for p in picks]): continue
                b,idx=newcov(sd["p"],mask);score=b*(sd["eff"] if useEff else 1)
                if best is None or score>best[0]: best=(score,b,j,idx,sd["eff"])
            if not best or best[1]<=0: break
            _,b,j,idx,e=best;used.add(j)
            for i in idx: mask[i]=1
            picks.append({"la":S[j]["la"],"lo":S[j]["lo"],"benefit":b,"eff":e})
        covA=100*sum(mask)/NC
        covD=100*sum(GR[i][2] for i in range(NC) if mask[i])/TOT
        return picks,covA,covD
    for useEff,label in [(True,"E) demand x efficiency (CURRENT)"),(False,"C) pure Mesa demand (max coverage)")]:
        picks,covA,covD=greedy(useEff)
        print(f"\n=== {label} ===  final Mesa 4-min: area {covA:.1f}%  demand {covD:.1f}%  ({len(picks)} stations)")
        for i,p in enumerate(picks):
            print(f"  {i+1}. {xst(p['la'],p['lo']):26s} +{100*p['benefit']/TOT:.2f}% demand  eff {round(100*p['eff'])}%")
    base_cov=100*sum(base)/NC
    print(f"\nFunded baseline Mesa 4-min area: {base_cov:.1f}%")

if __name__=="__main__": main()
