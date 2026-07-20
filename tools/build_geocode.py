#!/usr/bin/env python3
"""Build the compact offline reverse-geocoding dataset for the Plate scanner.

Source: kelvins/US-Cities-Database (public domain-ish, ~30k US cities with
CITY, STATE_CODE, LATITUDE, LONGITUDE). We reduce it to a tiny binary-ish JSON
the browser loads once and searches with a brute-force nearest-neighbour scan
(30k points -> sub-millisecond, done at most once per logged sighting).

Output format (../geocode-us.json), designed for small size + fast parse:
{
  "v": 1,                         # dataset format version
  "n": 29880,                     # number of cities
  "names": ["Boston", ...],       # city name per index
  "st":    ["MA", ...],           # 2-letter state code per index
  "lat":   [42.3584, ...],        # latitude  (4 dp)
  "lon":   [-71.0598, ...]        # longitude (4 dp)
}
Parallel arrays keep JSON compact (no repeated object keys). Coords rounded to
4 dp (~11 m) which is far finer than city-level resolution.

Usage:
  py -3.11 tools/build_geocode.py            # downloads source, writes ../geocode-us.json
  py -3.11 tools/build_geocode.py local.csv  # use an already-downloaded CSV
"""
import csv, io, json, os, sys, urllib.request

SRC_URL = "https://raw.githubusercontent.com/kelvins/US-Cities-Database/main/csv/us_cities.csv"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "geocode-us.json"))
DATASET_VERSION = 1


def load_rows(arg):
    if arg and os.path.exists(arg):
        with open(arg, "r", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    print(f"Downloading {SRC_URL} ...")
    with urllib.request.urlopen(SRC_URL, timeout=60) as r:
        text = r.read().decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def main():
    rows = load_rows(sys.argv[1] if len(sys.argv) > 1 else None)
    names, st, lat, lon = [], [], [], []
    for row in rows:
        try:
            la = round(float(row["LATITUDE"]), 4)
            lo = round(float(row["LONGITUDE"]), 4)
        except (KeyError, ValueError):
            continue
        city = (row.get("CITY") or "").strip()
        state = (row.get("STATE_CODE") or "").strip()
        if not city or not state:
            continue
        names.append(city)
        st.append(state)
        lat.append(la)
        lon.append(lo)

    data = {"v": DATASET_VERSION, "n": len(names),
            "names": names, "st": st, "lat": lat, "lon": lon}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"), ensure_ascii=False)
    kb = os.path.getsize(OUT) / 1024
    print(f"Wrote {OUT}: {len(names)} cities, {kb:.0f} KB")


if __name__ == "__main__":
    main()
