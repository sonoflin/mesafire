"""
Mesa Fire station coverage + siting model (v3).

Real-data demand + dual siting strategy:
  * DEMAND is now built from the City of Mesa's OWN data: block-group population density
    (Planning/Demographics) blended with adopted General Plan 2050 placetype intensity
    (Planning/GeneralPlan) so that planned growth counts even where today's population ~0.
  * COVERAGE is real street-network drive-time isochrones (Valhalla, see iso.py).
  * SITING runs TWO strategies:
      - "mesa"  (default): find gaps & site stations on MESA coverage only — Mesa tax
                 dollars prioritized for Mesa residents.
      - "aid"   : also count mutual-aid (sister) coverage when finding true gaps.
  * Stations 223/224 are the funded 2024-bond network; the model then proposes the 2028
    bond pair and a buildout sequence, separately for each strategy.

Run:  python scripts/build_coverage.py
"""
import json, math, os, statistics
import iso

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def P(*a): return os.path.join(HERE, *a)

# ---- parameters ----
GRID_MI=0.30; MIN_SPACING_MI=1.60; N_2028=2; N_BUILDOUT=4
# N_BUILDOUT is the DEFAULT buildout size (the "Full Buildout" phase = 2028 pair + 4 = 6 total).
# We actually COMPUTE up to N_BUILDOUT_MAX buildout stations so the in-app stepper can reveal
# more if the city has appetite/funding — the greedy still stops early once a pick adds less
# than BENEFIT_FLOOR of total demand, so we never invent low-value stations.
N_BUILDOUT_MAX=8
BENEFIT_FLOOR=0.004; MAX_CANDIDATES=55; DENS_CAP=3.0   # stop buildout below 0.4% of TOTAL demand
EFF_TIEBREAK=0.15   # objective = Mesa demand covered, with a light (<=15%) efficiency tie-break
PLACETYPE_W={
 "Downtown":3.0,"Urban Center":2.8,"Regional Center":2.6,"Regional Employment Center":2.4,
 "Local Employment Center":2.0,"Neighborhood Center":1.9,"Urban Residential":1.9,
 "Mixed Residential":1.5,"Traditional Residential":1.0,"Industrial":1.2,
 "Rural Residential":0.4,"Parks Open Space":0.15,"Unknown":0.3}

MI_PER_DEG_LAT=69.0
def mi_per_deg_lon(lat): return 69.0*math.cos(math.radians(lat))
def miles(a,b,c,d):
    return math.hypot((c-a)*MI_PER_DEG_LAT,(d-b)*mi_per_deg_lon((a+c)/2))

# ---- point-in-polygon ----
def in_ring(lon,lat,ring):
    inside=False;n=len(ring);j=n-1
    for i in range(n):
        xi,yi=ring[i][0],ring[i][1];xj,yj=ring[j][0],ring[j][1]
        if ((yi>lat)!=(yj>lat)) and (lon<(xj-xi)*(lat-yi)/(yj-yi)+xi): inside=not inside
        j=i
    return inside
def in_rings(lon,lat,rings):           # even-odd across all rings (holes + multipolygon)
    inside=False
    for ring in rings:
        n=len(ring);j=n-1
        for i in range(n):
            xi,yi=ring[i][0],ring[i][1];xj,yj=ring[j][0],ring[j][1]
            if ((yi>lat)!=(yj>lat)) and (lon<(xj-xi)*(lat-yi)/(yj-yi)+xi): inside=not inside
            j=i
    return inside
def bbox(ring):
    xs=[c[0] for c in ring];ys=[c[1] for c in ring];return (min(xs),min(ys),max(xs),max(ys))
def prep(geom):                         # isochrone geometry -> [(outer,holes,bbox)]
    parts=[];polys=geom["coordinates"] if geom["type"]=="MultiPolygon" else [geom["coordinates"]]
    for poly in polys:
        if poly and poly[0]: parts.append((poly[0],poly[1:],bbox(poly[0])))
    return parts
def contains(parts,lon,lat):
    for outer,holes,bb in parts:
        if lon<bb[0] or lon>bb[2] or lat<bb[1] or lat>bb[3]: continue
        if in_ring(lon,lat,outer) and not any(in_ring(lon,lat,h) for h in holes): return True
    return False

# ---- spatial bucket index for many small polygons ----
class Index:
    def __init__(self,polys,getbb,B=0.01):
        self.B=B;self.polys=polys;self.idx={}
        for pi,p in enumerate(polys):
            x0,y0,x1,y1=getbb(p)
            for bx in range(int(math.floor(x0/B)),int(math.floor(x1/B))+1):
                for by in range(int(math.floor(y0/B)),int(math.floor(y1/B))+1):
                    self.idx.setdefault((bx,by),[]).append(pi)
    def candidates(self,lon,lat):
        return self.idx.get((int(math.floor(lon/self.B)),int(math.floor(lat/self.B))),[])

# ---- arterial labels ----
NS_ROADS=[(-111.857,"Alma School Rd"),(-111.842,"Country Club Dr"),(-111.833,"Center St"),
 (-111.825,"Mesa Dr"),(-111.805,"Stapley Dr"),(-111.789,"Gilbert Rd"),(-111.771,"Lindsay Rd"),
 (-111.755,"Val Vista Dr"),(-111.737,"Greenfield Rd"),(-111.720,"Higley Rd"),(-111.705,"Recker Rd"),
 (-111.684,"Power Rd"),(-111.670,"Sossaman Rd"),(-111.662,"Hawes Rd"),(-111.636,"Ellsworth Rd"),
 (-111.618,"Crismon Rd"),(-111.601,"Signal Butte Rd"),(-111.583,"Meridian Rd")]
EW_ROADS=[(33.466,"McDowell Rd"),(33.451,"McKellips Rd"),(33.437,"Brown Rd"),(33.422,"University Dr"),
 (33.4155,"Main St"),(33.407,"Broadway Rd"),(33.393,"Southern Ave"),(33.378,"Baseline Rd"),
 (33.364,"Guadalupe Rd"),(33.350,"Elliot Rd"),(33.336,"Warner Rd"),(33.321,"Ray Rd"),
 (33.307,"Williams Field Rd"),(33.293,"Pecos Rd"),(33.278,"Germann Rd")]
def cross_streets(lat,lon):
    return f"{min(NS_ROADS,key=lambda r:abs(r[0]-lon))[1]} & {min(EW_ROADS,key=lambda r:abs(r[0]-lat))[1]}"

def load_boundary_parts():
    g=json.load(open(P("data","mesa_boundary.geojson")))["features"][0]["geometry"]; return prep(g)

def rings_of(geom):
    if not geom: return []
    if geom["type"]=="Polygon": return list(geom["coordinates"])
    if geom["type"]=="MultiPolygon": return [r for poly in geom["coordinates"] for r in poly]
    return []

def main():
    stations=json.load(open(P("data","stations.json"),encoding="utf-8"))
    stations=[s for s in stations if s["status"] in ("existing","committed")]
    aid=json.load(open(P("data","mutual_aid.json"),encoding="utf-8"))
    bpart=load_boundary_parts()

    # ---- county islands: authoritative, from scripts/fetch_boundary.py (Mesa GIS) ----
    # The city boundary itself (mesa_boundary.geojson) already carries these as holes, so
    # contains(bpart, ...) excludes them from the serviceable area automatically.
    islands=json.load(open(P("data","county_islands.geojson")))["features"]
    print(f"County islands (excluded from serviceable area): {len(islands)}")

    # serviceable area = inside city boundary AND not inside any island (islands are holes,
    # so contains(bpart, ...) already excludes them). Coverage efficiency uses this.
    def efficiency(parts4):
        """Fraction of a 4-min isochrone's AREA that falls on Mesa-served (serviceable) land."""
        if not parts4: return 1.0
        x0=min(bb[0] for _,_,bb in parts4); x1=max(bb[2] for _,_,bb in parts4)
        y0=min(bb[1] for _,_,bb in parts4); y1=max(bb[3] for _,_,bb in parts4)
        sy=0.1/MI_PER_DEG_LAT; sx=0.1/mi_per_deg_lon((y0+y1)/2)
        tot=serv=0; y=y0
        while y<=y1:
            x=x0
            while x<=x1:
                if contains(parts4,x,y):
                    tot+=1
                    if contains(bpart,x,y): serv+=1
                x+=sx
            y+=sy
        return serv/tot if tot else 1.0

    # ---- demand inputs: block groups (pop density) + placetypes (future intensity) ----
    bg=json.load(open(P("data","blockgroups.geojson")))["features"]
    BG=[{"r":rings_of(f["geometry"]),"dens":f["properties"]["dens"] or 0} for f in bg if f.get("geometry")]
    for b in BG: b["bb"]=bbox([c for r in b["r"] for c in r])
    bgIdx=Index(BG,lambda b:b["bb"])
    PT=json.load(open(P("data","placetypes.json")))   # [{pt,r,bb}]
    ptIdx=Index(PT,lambda p:p["bb"])
    def dens_at(lon,lat):
        for pi in bgIdx.candidates(lon,lat):
            b=BG[pi];bb=b["bb"]
            if bb[0]<=lon<=bb[2] and bb[1]<=lat<=bb[3] and in_rings(lon,lat,b["r"]): return b["dens"]
        return 0
    def pt_at(lon,lat):
        for pi in ptIdx.candidates(lon,lat):
            p=PT[pi];bb=p["bb"]
            if bb[0]<=lon<=bb[2] and bb[1]<=lat<=bb[3] and in_rings(lon,lat,p["r"]): return p["pt"]
        return None

    # ---- grid + demand ----
    xs=[bb[0] for _,_,bb in bpart]+[bb[2] for _,_,bb in bpart]
    ys=[bb[1] for _,_,bb in bpart]+[bb[3] for _,_,bb in bpart]
    lon_min,lon_max,lat_min,lat_max=min(xs),max(xs),min(ys),max(ys)
    raw=[]; lat=lat_min
    while lat<=lat_max:
        dlon=GRID_MI/mi_per_deg_lon(lat);lon=lon_min
        while lon<=lon_max:
            if contains(bpart,lon,lat):
                raw.append([lat,lon,dens_at(lon,lat),pt_at(lon,lat)])
            lon+=dlon
        lat+=GRID_MI/MI_PER_DEG_LAT
    dvals=[r[2] for r in raw if r[2]>0]
    DNORM=statistics.median(dvals) if dvals else 1.0
    cells=[]
    for la,lo,dens,pt in raw:
        pop_score=min(dens/DNORM,DENS_CAP) if DNORM else 0
        fut=PLACETYPE_W.get(pt,PLACETYPE_W["Unknown"])
        cells.append([la,lo,max(pop_score,fut,0.1)])
    total=sum(c[2] for c in cells); area_cells=len(cells)
    print(f"Grid {area_cells} cells | demand {total:.0f} | median BG density {DNORM:.0f}/sqmi")

    # ---- isochrones ----
    def fetch_all(items,kind):
        out={}
        for i,s in enumerate(items):
            g=iso.get(s["lat"],s["lon"])
            out[s.get("id") or f"{kind}{i}"]={"4":prep(g["4"]),"8":prep(g["8"]),"g4":g["4"],"g8":g["8"]}
            if (i+1)%12==0 or i==len(items)-1: print(f"  {kind} iso {i+1}/{len(items)}")
        return out
    print("Isochrones (cached)...")
    ISO=fetch_all(stations,"st")
    for i,a in enumerate(aid): a["id"]=f"aid{i}"
    AISO=fetch_all(aid,"aid")

    def mask(dicts,band):
        m=[False]*len(cells)
        for d in dicts:
            p=d[band]
            for i,(clat,clon,_) in enumerate(cells):
                if not m[i] and contains(p,clon,clat): m[i]=True
        return m
    def OR(a,b): return [x or y for x,y in zip(a,b)]
    def area_pct(m): return round(100*sum(1 for x in m if x)/area_cells,1)
    def dem_pct(m): return round(100*sum(c[2] for c,x in zip(cells,m) if x)/total,1)

    ex=[s["id"] for s in stations if s["status"]=="existing"]
    com=[s["id"] for s in stations if s["status"]=="committed"]
    funded=ex+com; aidids=[a["id"] for a in aid]
    fund4=mask([ISO[i] for i in funded],"4"); fund8=mask([ISO[i] for i in funded],"8")
    aid4=mask([AISO[i] for i in aidids],"4"); aid8=mask([AISO[i] for i in aidids],"8")
    fund4a=OR(fund4,aid4); fund8a=OR(fund8,aid8)
    print(f"Funded 4-min: Mesa {area_pct(fund4)}% | +aid {area_pct(fund4a)}% (aid alone {area_pct(aid4)}%)")

    # ---- greedy MCLP for one strategy ----
    stpts=stations  # have lat/lon
    def far(lat,lon,placed,d=MIN_SPACING_MI):
        return all(miles(lat,lon,s["lat"],s["lon"])>=d for s in placed)
    def run(covered_init):
        covered=list(covered_init)
        unc=[(cells[i][0],cells[i][1],cells[i][2]) for i in range(len(cells)) if not covered[i]]
        def near_unc(lat,lon):              # serviceable demand still uncovered within ~1 mi
            s=0.0
            for la,lo,w in unc:
                if abs(la-lat)<0.016 and abs(lo-lon)<0.020 and miles(lat,lon,la,lo)<=1.0: s+=w
            return s
        # Candidate sites = ANY serviceable cell (interior OR edge) ≥1.6 mi from a station and
        # near uncovered demand. Allowing interior cells lets the model pull a station inward
        # off the border instead of stranding half its reach outside the city.
        cand=[(c[0],c[1],near_unc(c[0],c[1])) for c in cells if far(c[0],c[1],stations)]
        cand=[c for c in cand if c[2]>0]; cand.sort(key=lambda c:-c[2])
        seeds=[]
        for la,lo,_ in cand:
            if far(la,lo,[{"lat":s[0],"lon":s[1]} for s in seeds],0.5): seeds.append((la,lo))
            if len(seeds)>=MAX_CANDIDATES: break
        SEED={}
        for j,(la,lo) in enumerate(seeds):
            g=iso.get(la,lo);p4=prep(g["4"])
            SEED[j]={"lat":la,"lon":lo,"4":p4,"g4":g["4"],"g8":g["8"],"eff":efficiency(p4)}
        remaining=sum(c[2] for c,x in zip(cells,covered) if not x)
        chosen=[];placed=[{"lat":s["lat"],"lon":s["lon"]} for s in stations]
        for pick in range(N_2028+N_BUILDOUT_MAX):
            best=None  # (score, benefit, j, idxs)
            for j,sd in SEED.items():
                if any(c["seed"]==j for c in chosen): continue
                if not far(sd["lat"],sd["lon"],placed): continue
                b=0.0;idxs=[]
                for i,(clat,clon,w) in enumerate(cells):
                    if not covered[i] and contains(sd["4"],clon,clat): b+=w;idxs.append(i)
                # coverage-first: maximize Mesa demand covered, light efficiency tie-break only
                score=b*((1-EFF_TIEBREAK)+EFF_TIEBREAK*sd["eff"])
                if best is None or score>best[0]: best=(score,b,j,idxs)
            if not best or best[1]<=0: break
            score,b,j,idxs=best;frac=b/total if total else 0
            if pick>=N_2028 and frac<BENEFIT_FLOOR: break
            for i in idxs: covered[i]=True
            remaining-=b
            sd=SEED[j];la,lo=sd["lat"],sd["lon"]
            nearest=min(stations+chosen,key=lambda s:miles(la,lo,s["lat"],s["lon"]))
            gap=miles(la,lo,nearest["lat"],nearest["lon"])
            chosen.append({"id":str(225+len(chosen)),"seed":j,"lat":round(la,6),"lon":round(lo,6),
                "captured":round(b,1),"pct":round(100*b/total,2),"eff":round(100*sd["eff"]),
                "near":nearest["id"],"gap":round(gap,2),"g4":sd["g4"],"g8":sd["g8"]})
            placed.append({"lat":la,"lon":lo})
        return chosen

    def package(chosen,strategy):
        out=[]
        for k,c in enumerate(chosen):
            status="proposed-2028" if k<N_2028 else "proposed-buildout"
            lbl=("2028 Bond" if k<N_2028 else "Buildout")
            out.append({"id":c["id"],"name":f"{lbl} — {cross_streets(c['lat'],c['lon'])}",
                "address":f"~ {cross_streets(c['lat'],c['lon'])}, Mesa, AZ (analytical site)",
                "lat":c["lat"],"lon":c["lon"],"status":status,"strategy":strategy,
                "priority":k+1,"captured_pct_of_city":c["pct"],"nearest_station":c["near"],
                "gap_to_nearest_mi":c["gap"],"efficiency_pct":c["eff"],
                "note":(f"Pulls {c['pct']}% of citywide demand inside a 4-min drive that "
                        f"{'no Mesa engine' if strategy=='mesa' else 'no Mesa or mutual-aid engine'} reaches "
                        f"today. {c['eff']}% of its 4-min reach serves Mesa (the rest spills onto "
                        f"county/neighboring land). Nearest station #{c['near']} is {c['gap']} mi away."),
                "_g4":c["g4"],"_g8":c["g8"]})
        return out

    print("Strategy: Mesa-only ...")
    mesa=package(run(fund4),"mesa")
    for s in mesa: print(f"  {s['id']} {s['status'][9:]:9s} {s['name'][12:]:28s} +{s['captured_pct_of_city']}%")
    print("Strategy: +mutual aid ...")
    aidstrat=package(run(fund4a),"aid")
    for s in aidstrat: print(f"  {s['id']} {s['status'][9:]:9s} {s['name'][12:]:28s} +{s['captured_pct_of_city']}%")
    newall=mesa+aidstrat

    # ---- stations.json ----
    stout=stations+[{k:v for k,v in s.items() if not k.startswith("_")} for s in newall]
    json.dump(stout,open(P("data","stations.json"),"w",encoding="utf-8"),indent=2)

    # ---- coverage.geojson ----
    feats=[]
    def add(stid,status,strat,g4,g8):
        feats.append({"type":"Feature","properties":{"station_id":stid,"status":status,"strategy":strat,"band":"8min"},"geometry":g8})
        feats.append({"type":"Feature","properties":{"station_id":stid,"status":status,"strategy":strat,"band":"4min"},"geometry":g4})
    for s in stations: add(s["id"],s["status"],"all",ISO[s["id"]]["g4"],ISO[s["id"]]["g8"])
    for s in newall:   add(s["id"],s["status"],s["strategy"],s["_g4"],s["_g8"])
    for a in aid:      add(a["id"],"mutual-aid","all",AISO[a["id"]]["g4"],AISO[a["id"]]["g8"])
    json.dump({"type":"FeatureCollection","features":feats},open(P("data","coverage.geojson"),"w"),separators=(",",":"))
    json.dump(aid,open(P("data","mutual_aid.json"),"w",encoding="utf-8"),indent=2)

    # ---- demand grid for live (in-browser) coverage recompute as the user edits stations ----
    json.dump({"total":round(total,2),"ncells":area_cells,"grid_mi":GRID_MI,
               "cells":[[round(c[0],5),round(c[1],5),round(c[2],3)] for c in cells]},
              open(P("data","demand_grid.json"),"w"),separators=(",",":"))

    # ---- gaps.geojson (vs funded; tagged for both strategies) ----
    gfeats=[]
    for (clat,clon,w),mc4,mc8,ac4,ac8 in zip(cells,fund4,fund8,fund4a,fund8a):
        if not mc4:                       # uncovered by Mesa funded network (superset)
            gfeats.append({"type":"Feature",
                "properties":{"w":round(w,2),"mn8":(not mc8),"ag4":(not ac4),"an8":(not ac8)},
                "geometry":{"type":"Point","coordinates":[round(clon,5),round(clat,5)]}})
    json.dump({"type":"FeatureCollection","features":gfeats},open(P("data","gaps.geojson"),"w"),separators=(",",":"))

    # ---- Mesa-only block groups for choropleth (keep those whose centroid is in-city) ----
    mesa_bg=[]
    for f in bg:
        rings=rings_of(f.get("geometry"))
        pts=[c for r in rings for c in r]
        if not pts: continue
        clon=sum(c[0] for c in pts)/len(pts); clat=sum(c[1] for c in pts)/len(pts)
        if contains(bpart,clon,clat): mesa_bg.append(f)
    json.dump({"type":"FeatureCollection","features":mesa_bg},open(P("data","blockgroups_mesa.geojson"),"w"),separators=(",",":"))

    # ---- metrics ----
    prep_new={s["id"]+s["strategy"]:{"4":prep(s["_g4"]),"8":prep(s["_g8"])} for s in newall}
    def phase(strat_new_ids,strat):
        d=[ISO[i] for i in funded]+[prep_new[i+strat] for i in strat_new_ids]
        m4=mask(d,"4");m8=mask(d,"8")
        if strat=="aid": m4=OR(m4,aid4);m8=OR(m8,aid8)
        return {"area4":area_pct(m4),"area8":area_pct(m8),"dem4":dem_pct(m4),"dem8":dem_pct(m8)}
    def strat_metrics(newset,strat):
        b=[s["id"] for s in newset if s["status"]=="proposed-2028"]
        bu=[s["id"] for s in sorted(newset,key=lambda s:s["priority"]) if s["status"]=="proposed-buildout"]
        # cumulative coverage as each buildout station is added (k = number of buildout stations,
        # k=0 == just the 2028 pair). Lets the in-app stepper show exact numbers per count live.
        seq=[phase(b+bu[:k],strat) for k in range(len(bu)+1)]
        return {"funded":phase([],strat),"bond2028":phase(b,strat),
                "buildout":phase(b+bu[:N_BUILDOUT],strat),       # default 6-station view
                "buildout_seq":seq,"buildout_default":N_BUILDOUT,"buildout_max":len(bu)}
    metrics={
        "params":{"engine":"Valhalla auto isochrone","grid_mi":GRID_MI,"min_spacing_mi":MIN_SPACING_MI,
                  "demand":"max(block-group pop density / median, GP2050 placetype intensity)"},
        "counts":{"existing":len(ex),"committed":len(com),"bond2028":N_2028,"buildout":N_BUILDOUT,
                  "buildout_max":len(mesa)-N_2028,"mutual_aid":len(aid),"county_islands":len(islands)},
        "avg_efficiency":{"mesa":round(sum(s["efficiency_pct"] for s in mesa)/max(1,len(mesa))),
                          "aid":round(sum(s["efficiency_pct"] for s in aidstrat)/max(1,len(aidstrat)))},
        "funded_compare":{"area4_mesa":area_pct(fund4),"area4_aid":area_pct(fund4a)},
        "mutual_aid_only":{"area4":area_pct(aid4),"dem4":dem_pct(aid4)},
        "strategies":{"mesa":strat_metrics(mesa,"mesa"),"aid":strat_metrics(aidstrat,"aid")},
        "total_demand":round(total,1),"area_cells":area_cells,"median_density":round(DNORM,0),
        "gap_cells":len(gfeats),"n_blockgroups_mesa":len(mesa_bg),"n_developments":len(json.load(open(P("data","developments.json")))),
    }
    json.dump(metrics,open(P("data","metrics.json"),"w"),indent=2)

    print("\n=== MESA-ONLY strategy (default) area% ===")
    for ph in ("funded","bond2028","buildout"):
        p=metrics["strategies"]["mesa"][ph];print(f"  {ph:9s} 4-min {p['area4']}%  8-min {p['area8']}%")
    print("=== +MUTUAL-AID strategy ===")
    for ph in ("funded","bond2028","buildout"):
        p=metrics["strategies"]["aid"][ph];print(f"  {ph:9s} 4-min {p['area4']}%  8-min {p['area8']}%")
    print(f"Wrote stations.json (+{len(newall)}), coverage.geojson ({len(feats)}), gaps ({len(gfeats)}), "
          f"blockgroups_mesa ({len(mesa_bg)}), metrics.json")

if __name__=="__main__":
    main()
