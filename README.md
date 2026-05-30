# Mesa Fire & Medical — Station Coverage & Buildout Plan

A **mobile-first web map** showing where Mesa Fire & Medical's next stations should go.
Coverage is modeled as **real street-network drive-time isochrones** (not circles) against
Mesa's **NFPA 1710** standard. Demand is built from the **City of Mesa's own data**
(block-group population + General Plan 2050 land use), with a **Mesa-first** default lens and
optional **mutual-aid** awareness.

> ⚠️ **Independent decision-support model, not an official MFMD document.** Stations 223/224
> reflect the City's funded 2024-bond plans; 225–230 are analytical forecasts.
> See [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).

## What it shows

- **22 existing + 2 funded** stations (223/224, 2024 bond) with **4-min** / **8-min**
  **network isochrones**.
- A **phase switch** — *Current → + 2028 Bond (225, 226) → Full Buildout (+227–230)*.
- A **planning-lens toggle** — **Mesa only** (default; Mesa engines only) vs **+ Mutual aid**
  (counts 30 sister-agency stations to find *true* gaps, never to fill neighbors' gaps; switching
  to this lens also shows the sister stations + their grey coverage). Each lens has its own
  recommendation set.
- **Mobile-friendly chrome**: the map is bounded to the **Phoenix East Valley**; layer controls
  live in a **collapsible panel** (a layers button — open by default on desktop, tucked away on
  mobile); a **Map / Satellite** basemap toggle; and **Help** (header) opens a combined
  **FAQ + Methodology** dialog. Clicking any station shows live stats — its 4-min reach in sq mi,
  the % of Mesa demand it serves, and the % of its reach on Mesa-served land.
- **Coverage efficiency** — sites are scored by *serviceable demand × the share of each
  station's 4-min reach that serves Mesa*, so the model pulls stations inland and won't waste
  coverage across the border. Efficiency is shown on every recommendation.
- **County islands** — the **15** unincorporated Rural-Metro pockets (from Mesa's authoritative
  city boundary) are drawn hatched and excluded from the serviceable area, so no station is wasted
  on non-Mesa land.
- **Layers**: coverage gaps, mutual-aid stations (grey diamonds), **planned developments**
  (13 real projects), and a **population-density** choropleth from Mesa's block groups.
- **Live what-if editing** (✎ Edit): **drag** proposed stations (they **snap to the road network**),
  **add** stations by tapping the map, or **delete** any (built stations warn you — toggleable) —
  and the **real network-isochrone coverage recomputes in the browser instantly**. **Reset** returns
  to the optimized model. Isochrones come live from Valhalla and snapping from OSRM (both
  CORS-enabled, so it works on a static site with no backend). A `window.MESA` console API
  (`liveMetrics`, `addAt`, `move`, `del`, `reset`) is exposed for QA/scripting.
- A **"Why here"** panel with the numbers behind each recommendation, and an **About** dialog
  with full methodology and sources.

### Headline result — area % of the serviceable city (Mesa-only lens / incl. mutual aid)

| Phase | 4-min | 8-min |
|---|---|---|
| Current (22 + 223/224) | 51.6% / 52.8% | 91.2% / 93.2% |
| + 2028 bond (225, 226) | 54.9% / 56.2% | 91.2% / 93.2% |
| + Buildout (227–230) | 58.4% / 60.0% | 91.7% / 93.8% |

The objective is **maximize Mesa demand covered**; coverage efficiency (share of a station's reach
on Mesa-served land) is a *reported* metric and a light tie-breaker, not a penalty — so a high-demand
border site like 227 (Power & Ray) is still chosen because it covers the most Mesa residents.
Percentages are of the *serviceable* area (incorporated Mesa minus the 15 county islands).

> 8-min coverage is lower than a circle model would suggest (~96%) because real road reach
> is shorter and irregular in sparse SE Mesa — that's the honesty gain from isochrones.

## Run it locally

No build step, no dependencies for the web app — it's plain HTML/CSS/JS + Leaflet.
You only need a static file server (browsers block `fetch()` on `file://`):

```bash
# from the project root
python -m http.server 8000
# then open http://localhost:8000
```

(Any static server works: `npx serve`, VS Code Live Server, etc.)

## Project layout

```
index.html               # app shell
css/styles.css           # mobile-first responsive styling
js/app.js                # Leaflet map, phases, strategy lens, layers, panels (vanilla JS)
data/
  stations.json          # stations: existing/committed/proposed (per strategy)  ← output
  mutual_aid.json        # sister-jurisdiction stations near the border          ← output
  coverage.geojson       # 4- & 8-min network isochrones per station             ← output
  gaps.geojson           # uncovered-demand points (tagged for both lenses)      ← output
  county_islands.geojson # unincorporated Rural-Metro pockets (excluded)         ← output
  metrics.json           # phased coverage stats, per strategy                   ← output
  demand_grid.json       # serviceable demand grid for LIVE in-browser recompute  ← output
  developments.json      # 13 curated major planned developments
  blockgroups.geojson    # raw Mesa-extent block groups (population)             ← fetched
  blockgroups_mesa.geojson # Mesa-only block groups for the choropleth           ← output
  placetypes.json        # General Plan 2050 placetype polygons (demand input)   ← fetched
  iso_cache.json         # cached Valhalla isochrones (cheap reruns)             ← cache
  mesa_boundary.geojson  # authoritative city limits w/ island holes (Mesa GIS)  ← output
scripts/
  geocode_stations.py    # geocodes the station roster (Census API)
  fetch_boundary.py      # Mesa GIS authoritative city limits + county islands (shapely)
  fetch_mutual_aid.py    # sister-agency stations from OSM (Overpass)
  fetch_city_data.py     # Mesa GIS: block-group population + GP2050 placetypes
  iso.py                 # cached Valhalla drive-time isochrone fetcher
  build_coverage.py      # real-data demand + dual-strategy MCLP on isochrones
docs/METHODOLOGY.md      # standard of cover, the math, sources, limitations
```

## Regenerate the analysis

Scripts use the **standard library + `requests` + `shapely`** (`pip install -r requirements.txt`).
Isochrones come from the public Valhalla server and are cached, so only new points hit the
network. Run from the project root, in order:

```bash
python scripts/geocode_stations.py   # -> data/stations.json (existing + funded 223/224)
python scripts/fetch_boundary.py     # -> mesa_boundary.geojson + county_islands.geojson (Mesa GIS)
python scripts/fetch_mutual_aid.py   # -> data/mutual_aid.json            (OSM / Overpass)
python scripts/fetch_city_data.py    # -> data/blockgroups.geojson, placetypes.json (Mesa GIS)
python scripts/build_coverage.py     # -> coverage/gaps/metrics + 2028 & buildout stations
                                      #    for BOTH the Mesa-only and +mutual-aid lenses
```

## Data we evaluated but did not use

Mesa's open data portal (`data.mesaaz.gov`) was reviewed for spatial demand. Its public fire
datasets are temporal performance metrics (e.g., *Fire 911 Calls Answered*); the large
*Fire/Medical Code 3 Incident Response Times by Percentile* dataset (~580k records) is **not
accessible via the API**. An internal export of that dataset is the highest-value next input —
it would give **actual incident density** (real demand) and **measured travel times** (to
calibrate the isochrone speeds). Until then, demand uses the authoritative population + General
Plan land-use surface.

All model knobs (grid size, station spacing, # of 2028/buildout stations, placetype weights,
mutual-aid search radius) live at the top of the scripts and are documented in the methodology.

## Deploy to GitHub Pages

It's a static site, so hosting is trivial:

```bash
git init
git add .
git commit -m "Mesa fire station coverage & buildout plan"
git branch -M main
git remote add origin <your-repo-url>
git push -u origin main
```

Then in the repo: **Settings → Pages → Build and deployment → Source: Deploy from a
branch → `main` / root**. Your map will be live at `https://<user>.github.io/<repo>/`.

## License / use

Built for the City of Mesa as planning decision-support. Data: OpenStreetMap (ODbL),
U.S. Census, and public City of Mesa / NFPA / ISO references cited in the methodology.
