# Methodology — Mesa Fire & Medical Station Coverage & Buildout Plan (v3)

*An independent, reproducible planning model built on public + City of Mesa data. This is
decision-support for discussion, not an official Mesa Fire & Medical Department (MFMD)
document. Stations 223/224 reflect the City's funded 2024-bond plans; 225–230 are
analytical forecasts from the model below.*

---

## 1. The question

The 2024 Public Safety Bond passed, funding **223** (Lehi / Val Vista & McDowell) and
**224** (Hawes & Elliot, SE). Mesa is weighing a **2028 bond for two more**, plus the
stations needed for full buildout. The model answers: given a real 4-minute drive-time
standard and real demand, **where should those stations go — and why there?** — with a
default lens that prioritizes **Mesa coverage for Mesa residents.**

---

## 2. The standard of cover

Mesa operates to **NFPA 1710**: ~3 min dispatch+turnout, then **≤4 min** first-due engine
travel and **≤8 min** for the full first-alarm assignment, met 90% of the time.
Independently, **ISO** wants a first-due engine within **1.5 road miles**. Travel time is
the only segment a station's *location* changes, so siting is about travel-time geography.

---

## 3. Coverage = network drive-time isochrones (not circles)

**You cannot expect the same 4-minute radius everywhere**, because a circle assumes equal
speed in every direction. Real reach is shaped by (1) street connectivity — the dense 1-mi
grid in the core vs. the sparse, curvilinear streets of SE Mesa; (2) road class & speed; and
(3) barriers — the Salt River, canals, the US-60/Loop 202/SR-24 freeways, the airport.

So every coverage area is a **true street-network drive-time isochrone** computed on the live
OpenStreetMap network by the **Valhalla** engine (4- and 8-minute polygons per station).
Switching from circles to real roads dropped modeled 8-minute coverage from ~96% to ~90% —
the honest part, concentrated where the buildout street grid doesn't exist yet.

*Costing & speed (validated):* coverage uses Valhalla's `auto` profile (posted/road-class
speeds with turn & intersection penalties). Measured against real routes this yields an
effective **~22–27 mph**, i.e. ~**1.4–1.7 road miles in 4 minutes** — which is *not* a bug: it
matches the fire standard. ISO's first-due-engine rule of **1.5 road miles** implies
`1.5 ÷ (4⁄60 h) ≈ 22.5 mph`, almost exactly what Valhalla produces. A Google-Maps drive time
looks farther (~28–35 mph) because it's a light-traffic *passenger-car* ETA; a 30-ton apparatus
accelerates slowly from stops and slows/clears every intersection even under lights-and-siren, so
a car ETA over-states an engine's reach. The assumption is exposed as a tunable **`SPEED_FACTOR`**
(default 1.0 = ISO-aligned; raise to ~1.2–1.3 to credit code-3 speed) in both `js/app.js` and
`scripts/iso.py`; the gold-standard calibration is Mesa's measured 90th-percentile CAD travel
times. See the in-app **FAQ** tab. Population/call-volume are **not** baked into a station's reach
shape — a 4-minute drive is a 4-minute drive; those belong in the demand surface (§5) and in
concurrency/reliability (§9).

---

## 4. Two planning lenses (the Mesa-first default)

The Council and public prioritize spending Mesa dollars on Mesa residents, so the model runs
**two strategies** and **defaults to Mesa-only**:

- **Mesa only (default):** gaps and station siting count **Mesa engines only**. A Mesa
  neighborhood >4 min from a *Mesa* station is a gap, even if a neighbor could reach it.
- **+ Mutual aid:** also counts the **30 sister-jurisdiction stations** within 3.5 mi of the
  border (Gilbert, Tempe, Chandler, Queen Creek, Scottsdale, Apache Junction, SRPMIC, Rural
  Metro) when finding *true* gaps — so the model won't propose a Mesa station where a neighbor
  already covers in 4 min. **We never site Mesa stations to fill neighbors' gaps.**

Mutual aid reaches only ~1.4% of Mesa's area within its own 4 minutes (edges, not the
interior), so the two lenses produce similar — but not identical — priorities. Sister
stations are always shown distinctly (grey diamonds) regardless of lens.

---

## 5. Demand — built on the City of Mesa's own data

A **0.30-mile grid**, masked to the municipal boundary. Each cell's demand is:

```
demand = max( population_score , placetype_intensity )
population_score = block-group population density ÷ citywide median density (capped at 3)
```

- **Population** comes from Mesa's **Planning/Demographics** block groups
  (`TOTAL_POP`, `POP_PER_SQMI`); citywide median density ≈ **3,110 people/sq mi**.
- **Placetype intensity** comes from Mesa's adopted **General Plan 2050** land use
  (6,306 placetype polygons): Downtown 3.0, Urban Center 2.8, Regional Center 2.6, Regional
  Employment 2.4, Local Employment 2.0, Neighborhood Center / Urban Residential 1.9, Mixed
  Residential 1.5, Industrial 1.2, Traditional Residential 1.0, Rural 0.4, Parks 0.15.

Taking the **max** means a cell counts by its *people today* **or** its *planned intensity*,
whichever is greater — so established neighborhoods register by population, and planned
Employment/Urban centers in SE Mesa register before they're built. This replaces the earlier
hand-drawn growth boxes entirely. A curated layer of **13 major real developments** (Eastmark,
Cadence, Hawes Crossing, Elliot Rd Tech Corridor, Google data center, Mesa Gateway, Downtown/
ASU, Riverview…) is shown for context; their intensity already flows in via the placetypes.

**Serviceable area & county islands.** Demand is masked to the **serviceable area** = the
incorporated city *minus* its county islands. We build this from **Mesa's own authoritative GIS**
(`BaseMap/cityboundary`), which models the city as **29 separate polygons**; we union them
(shapely) and the union's interior holes are the **15 county islands** (≈ **17.3 sq mi**, the
largest ~4.9 sq mi) — unincorporated Maricopa pockets served by **Rural Metro**, not Mesa FMD.
This is materially more accurate than the earlier OpenStreetMap approximation, especially in SE
Mesa. Islands are drawn hatched, generate **no demand**, and earn **no Mesa coverage credit**;
a station's efficiency score is also penalized for any 4-minute reach that bleeds into one — so
the model never wastes a station on them. (Mesa does staff one existing station that sits largely
within an island today.)

---

## 6. The siting model — Maximal Covering Location (MCLP)

A greedy **Maximal Covering Location Problem** on the isochrones, run **once per lens**:

1. Fix the committed network (22 existing + 2 funded). Mark every cell inside their 4-min
   isochrones as covered — and, in the **+ mutual aid** lens, cells inside sister isochrones too.
2. Candidate sites = **any serviceable cell** (interior *or* edge) ≥1.6 mi from a station and
   within ~1 mi of uncovered demand, thinned to ~0.5-mi spacing, capped at 30. Allowing
   *interior* sites — not just the uncovered cells themselves — lets the model pull a station
   inland off the border instead of stranding half its reach outside the city.
3. **Objective = maximize Mesa serviceable demand newly covered** within 4 minutes. **Coverage
   efficiency** — the fraction of a candidate's 4-minute isochrone **area** that lands on
   serviceable (Mesa-served) ground, measured by sampling the polygon — is applied only as a
   **light tie-break** (`score = benefit × (0.85 + 0.15·efficiency)`) and is reported on every
   recommendation. It is **not** a hard penalty: a high-demand site near the border (e.g. Power &
   Ray, ~39% efficient) is still chosen because it covers the most Mesa residents — reach that
   spills into a neighbor doesn't subtract any Mesa coverage (and Mesa runs mutual aid there).
   A truly wasteful corner site is avoided automatically, because it would cover little Mesa
   demand to begin with. *(An earlier version multiplied benefit by efficiency; a dense
   70-candidate test showed that cost ~0.4 pts of Mesa coverage, so it was reduced to a tie-break
   — "optimize Mesa coverage" is the governing objective.)*
4. Place the best, mark covered, repeat. **First two picks = the 2028 bond**; the rest are the
   buildout sequence (stop when marginal demand gain < ~1.5% of the remaining gap).

---

## 7. Results & narrative (Mesa-only lens)

### Coverage lift — area % of the *serviceable* city (Mesa-only / + mutual aid)

| Phase | 4-min | 8-min |
|---|---|---|
| Current (22 + funded 223/224) | 51.6% / 52.8% | 91.2% / 93.2% |
| **+ 2028 bond (225, 226)** | 54.9% / 56.2% | 91.2% / 93.2% |
| **+ Buildout (227–230)** | 58.4% / 60.0% | 91.7% / 93.8% |

(Percentages are of the serviceable area — incorporated Mesa minus the county islands.)

### Recommended stations (Mesa-only lens)

| # | Station | Site | New Mesa demand <4 min | Efficiency (reported) |
|---|---|---|---|---|
| 2028-1 | **225** | Higley Rd & McKellips Rd | +2.0% | 100% |
| 2028-2 | **226** | Greenfield Rd & University Dr | +1.8% | 96% |
| build-1 | 227 | Power Rd & Ray Rd | +1.2% | 39% |
| build-2 | 228 | Signal Butte Rd & Ray Rd | +1.1% | 80% |
| build-3 | 229 | Recker Rd & Southern Ave | +0.8% | 85% |
| build-4 | 230 | Alma School Rd & Guadalupe Rd | +0.8% | 69% |

The 2028 pair are **interior** stations filling dense, established >4-minute holes. The buildout
sequence is ordered by **Mesa demand covered**, so **227 (Power & Ray)** leads it — it covers the
most Mesa residents of any remaining site even though only ~39% of its 4-minute reach is on Mesa
land (the rest reaches into Gilbert/Queen Creek, which doesn't reduce Mesa coverage and is useful
for Mesa's own mutual-aid responses). Efficiency is reported for transparency and used only to
break near-ties. The **+ mutual aid** lens keeps the same 2028 pair — confirming Mesa's biggest
holes are interior and not something a neighbor can backfill.

---

## 8. Interactive what-if editing (live)

The map is not just a static result — planners can test their own placements and watch the
**real** coverage update:

- **Drag** a proposed (or added) station: it is **snapped to the road network** (OSRM `nearest`),
  a fresh **4- and 8-minute Valhalla isochrone** is fetched for the snapped point, and the
  citywide coverage % is **recomputed in the browser** against the serviceable demand grid
  (`data/demand_grid.json`, 1,569 cells) by point-in-isochrone test.
- **Add** a station by tapping the map (same snap + isochrone + recompute).
- **Delete** any station; built (existing/funded) stations show a light warning that can be
  toggled off.
- **Reset** restores the optimized model.

This runs entirely client-side on a static site: both Valhalla (`valhalla1.openstreetmap.de`)
and OSRM (`router.project-osrm.org`) return `Access-Control-Allow-Origin: *`, so no backend is
needed. For heavy/Production use the city should point these at a **self-hosted** Valhalla/OSRM
(or OpenRouteService) instance for rate limits and SLA. Live coverage uses the same point-in-
isochrone math as the offline model, so an unedited map reports identical numbers.

## 9. Limitations & next refinements

1. **Real incident demand & speed calibration (highest value).** We explored Mesa's open data
   portal (`data.mesaaz.gov`) for usable spatial demand. The public fire datasets are temporal
   performance metrics (e.g., *Fire 911 Calls Answered*) plus a large *Fire/Medical Code 3
   Incident Response Times by Percentile* dataset (~580k records) — which is **not accessible via
   the API** (restricted/derived view). That dataset is exactly the right input: an internal
   export would let us replace the land-use demand proxy with **actual incident density** and
   calibrate Valhalla speeds to **measured 90th-percentile travel times**. Until then we use the
   authoritative population + General Plan land-use surface (§5). Also add concurrency/reliability
   (a busy station can't make its own 4-minute call).
2. **Greenfield reach is understated** — SE isochrones are small because the street grid isn't
   built yet; re-run as roads come online.
3. **Finer demand** — add parcel-level dwelling units / jobs and adopted MAG population &
   employment forecasts on top of the General Plan placetypes.
4. **Mutual-aid availability** — treat neighbor coverage probabilistically (units get busy).

---

## 10. Data sources

- **Stations & addresses:** Mesa FMD / NERIS registry.
- **Population & land use:** City of Mesa GIS — `Planning/Demographics` (block groups),
  `Planning/GeneralPlan` (General Plan 2050 placetypes).
- **223 / 224:** City of Mesa 2024 Public Safety Bond (Question 2) program.
- **Standard of cover:** NFPA 1710; ISO FSRS; MFMD community assessment (FireCARES/NFORS).
- **City boundary & county islands:** City of Mesa GIS (`BaseMap/cityboundary`), unioned with shapely.
- **Isochrones:** Valhalla routing engine on OpenStreetMap.
- **Sister (mutual-aid) stations:** OpenStreetMap (Overpass).
- **Geocoding:** U.S. Census Bureau (Nominatim fallback).

Parameters live at the top of the scripts and are echoed into
[`data/metrics.json`](../data/metrics.json).
