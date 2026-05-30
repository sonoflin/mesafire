"""
Geocode Mesa Fire & Medical Department stations (existing + proposed) using the
free U.S. Census Bureau geocoder (no API key required), and write data/stations.json.

Run:  python scripts/geocode_stations.py
"""
import json, time, urllib.parse, urllib.request, sys, os

CENSUS = ("https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
          "?address={addr}&benchmark=Public_AR_Current&format=json")

# Existing stations 201-222. Addresses sourced from NERIS / Mesa Fire roster.
# status: existing | proposed-bond | proposed-buildout
# hazard: typical demand zone hazard class used for response-time band selection
STATIONS = [
    # --- EXISTING (22) ---
    ("201", "Glenwood",            "360 E 1st St, Mesa, AZ 85201",            "existing", "Downtown core / mixed-use; oldest station"),
    ("202", "McAfee Place",        "830 S Stapley Dr, Mesa, AZ 85204",        "existing", "Central-south residential"),
    ("203", "Alma Gardens",        "324 S Alma School Rd, Mesa, AZ 85202",    "existing", "West-central residential/commercial"),
    ("204", "Pace",                "1426 S Extension Rd, Mesa, AZ 85210",     "existing", "West-central; near US-60"),
    ("205", "Sunland Village",     "730 S Greenfield Rd, Mesa, AZ 85206",     "existing", "East-central; replacement funded"),
    ("206", "McAfee Heights",      "815 N Lindsay Rd, Mesa, AZ 85213",        "existing", "North-central residential"),
    ("207", "Dobson Ranch",        "2505 S Dobson Rd, Mesa, AZ 85202",        "existing", "Southwest residential"),
    ("208", "Falcon Field",        "7530 E McKellips Rd, Mesa, AZ 85207",     "existing", "Northeast; Falcon Field Airport/industrial"),
    ("209", "Golden Hills",        "7035 E Southern Ave, Mesa, AZ 85209",     "existing", "Southeast residential"),
    ("210", "Kingsborough Park",   "1502 S 24th St, Mesa, AZ 85204",          "existing", "South-central residential"),
    ("211", "Wintercone Park",     "2130 N Horne, Mesa, AZ 85203",            "existing", "North-central residential"),
    ("212", "Marbella",            "2430 S Ellsworth Rd, Mesa, AZ 85209",     "existing", "Far-east / SE residential"),
    ("213", "Adobe Hills",         "7816 E University Dr, Mesa, AZ 85207",    "existing", "East residential"),
    ("214", "Shadow Canyon",       "5950 E Virginia St, Mesa, AZ 85215",      "existing", "Northeast / Red Mountain"),
    ("215", "Williams Gateway",    "6353 S Downwind Ln, Mesa, AZ 85212",      "existing", "Phoenix-Mesa Gateway Airport / aircraft rescue"),
    ("216", "Valley View",         "7966 E McDowell Rd, Mesa, AZ 85207",      "existing", "East / NE foothills"),
    ("217", "Sunland Springs",     "10434 E Baseline Rd, Mesa, AZ 85209",     "existing", "Far-east SE residential"),
    ("218", "Santo Tomas",         "845 N Alma School Rd, Mesa, AZ 85201",    "existing", "North-central"),
    ("219", "Mountain Heights",    "3361 S Signal Butte Rd, Mesa, AZ 85212",  "existing", "SE Gateway residential/industrial"),
    ("220", "Granite Reef",        "32 S 58th St, Mesa, AZ 85206",            "existing", "East-central residential"),
    ("221", "Eastmark",            "9320 E Point Twenty Two Blvd, Mesa, AZ 85212","existing","Eastmark master-planned community"),
    ("222", "Northeast PSF",       "1333 N Power Rd, Mesa, AZ 85205",         "existing", "Northeast; opened 2025 (police + fire)"),
    # --- COMMITTED: funded by the passed 2024 Public Safety Bond (Question 2) ---
    ("223", "Lehi / Northeast",    "3310 E McDowell Rd, Mesa, AZ 85215",      "committed",
        "Funded (2024 bond). Val Vista & McDowell; fills the Lehi gap between the Salt River and McDowell. Construction starting ~winter 2025-26."),
    ("224", "Hawes & Elliot / SE", "3441 S 80th St, Mesa, AZ 85212",          "committed",
        "Funded (2024 bond). $12.3M; anchors SE Gateway growth (Hawes Crossing, Elliot Rd Tech Corridor). Completion ~fall 2026."),
]

# Coordinates the Census geocoder cannot resolve (verified via OSM Nominatim).
MANUAL = {
    "205": (33.401937, -111.736820),
    "222": (33.439835, -111.684376),
}

def geocode(addr):
    url = CENSUS.format(addr=urllib.parse.quote(addr))
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                d = json.load(r)
            m = d["result"]["addressMatches"]
            if m:
                c = m[0]["coordinates"]
                return round(c["y"], 6), round(c["x"], 6), m[0]["matchedAddress"]
            return None
        except Exception as e:
            print(f"   retry {attempt+1} ({e})", file=sys.stderr)
            time.sleep(2)
    return None

def main():
    out = []
    for num, name, addr, status, note in STATIONS:
        if num in MANUAL:
            lat, lon = MANUAL[num]; matched = addr + " (manual)"
            print(f"  {num} {name:22s} -> {lat}, {lon}  [manual]")
        else:
            res = geocode(addr)
            if res is None:
                print(f"!! FAILED: {num} {addr}", file=sys.stderr)
                lat = lon = None; matched = addr
            else:
                lat, lon, matched = res
                print(f"  {num} {name:22s} -> {lat}, {lon}")
        out.append({
            "id": num, "name": name, "address": addr, "matched_address": matched,
            "lat": lat, "lon": lon, "status": status, "note": note,
        })
        time.sleep(0.4)
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, "data", "stations.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"\nWrote {len(out)} stations -> {path}")

if __name__ == "__main__":
    main()
