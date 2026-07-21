#!/usr/bin/env python3
"""
Fetch the latest German greenhouse-gas emissions (KSG sectors) from the
Umweltbundesamt (UBA) SDMX API and write data.json for the dashboard.

Source: https://daten.uba.de/release/rest  (DataCube DF_CLIMATE_EMISSIONS_GHG_TRENDS_KSG)
Licence of the data: Datenlizenz Deutschland – Namensnennung 2.0 (dl-de/by-2-0)

Uses only the Python standard library (no pip install needed).
"""
import csv
import datetime
import io
import json
import re
import sys
import urllib.request

AGENCY = "UBA"
FLOW = "DF_CLIMATE_EMISSIONS_GHG_TRENDS_KSG"
BASE = "https://daten.uba.de/release/rest"
FALLBACK_VERSION = "2026.1"

SECTORS = ["ENERGIEWIRTSCHAFT", "INDUSTRIE", "GEBAEUDE", "VERKEHR",
           "LANDWIRTSCHAFT", "ABFALLWIRTSCHAFT_SONSTIGES"]
LABELS = {
    "ENERGIEWIRTSCHAFT": "Energiewirtschaft",
    "INDUSTRIE": "Industrie",
    "GEBAEUDE": "Gebäude",
    "VERKEHR": "Verkehr",
    "LANDWIRTSCHAFT": "Landwirtschaft",
    "ABFALLWIRTSCHAFT_SONSTIGES": "Abfallwirtschaft & Sonstiges",
}
TOTAL = "TOTAL_WITHOUT_LULUCF"
# Legally fixed targets (Bundes-Klimaschutzgesetz) – static, not in the data source.
TARGETS = [{"year": 2030, "value": 438}, {"year": 2040, "value": 150}, {"year": 2045, "value": 0}]


def http_get(url, accept="*/*"):
    req = urllib.request.Request(url, headers={"User-Agent": "gh-action-dashboard", "Accept": accept})
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read().decode("utf-8")


def latest_version():
    try:
        txt = http_get(f"{BASE}/dataflow/{AGENCY}/{FLOW}/latest?detail=allstubs",
                       accept="application/vnd.sdmx.structure+json")
        m = re.search(r'"version"\s*:\s*"([^"]+)"', txt)
        if m:
            print("Discovered dataflow version:", m.group(1))
            return m.group(1)
    except Exception as e:
        print("Version discovery failed, using fallback:", e, file=sys.stderr)
    return FALLBACK_VERSION


def fetch_csv(version):
    key = ".A." + "+".join(SECTORS + [TOTAL]) + ".GHG.KT_CO2_EQ"
    url = f"{BASE}/data/{AGENCY},{FLOW},{version}/{key}?startPeriod=1990&format=csv"
    return http_get(url, accept="application/vnd.sdmx.data+csv")


def parse(csv_text):
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = list(reader)
    cols = reader.fieldnames or []
    codes = set(SECTORS) | {TOTAL}
    # locate the sector dimension column, the time column and the value column generically
    sector_col = next((c for c in cols if {str(r.get(c)) for r in rows} & codes), None)
    time_col = "TIME_PERIOD" if "TIME_PERIOD" in cols else next(c for c in cols if "TIME" in c.upper())
    val_col = "OBS_VALUE" if "OBS_VALUE" in cols else next(c for c in cols if "VALUE" in c.upper())
    if not sector_col:
        raise RuntimeError("Could not locate sector column in SDMX-CSV; columns=%s" % cols)

    def series(code):
        out = {}
        for r in rows:
            if str(r.get(sector_col)) != code:
                continue
            m = re.search(r"(\d{4})", str(r.get(time_col, "")))
            try:
                v = float(r.get(val_col))
            except (TypeError, ValueError):
                continue
            if m:
                out[int(m.group(1))] = int(round(v / 1000.0))  # kt -> Mt
        return out

    return series


def build():
    version = latest_version()
    series = parse(fetch_csv(version))

    total_map = series(TOTAL)
    if not total_map:
        raise RuntimeError("No total emissions returned – aborting to keep last good data.json")
    years_total = sorted(total_map)
    total = [total_map[y] for y in years_total]

    sec = {c: series(c) for c in SECTORS}
    common = sorted(set.intersection(*[set(sec[c]) for c in SECTORS]))
    sectors = {LABELS[c]: [sec[c][y] for y in common] for c in SECTORS}

    data = {
        "updated": datetime.date.today().isoformat(),
        "source_version": version,
        "source": "Umweltbundesamt (UBA), DataCube DF_CLIMATE_EMISSIONS_GHG_TRENDS_KSG, dl-de/by-2-0",
        "unit": "Mt CO2-Aeq. (ohne LULUCF)",
        "years_total": years_total,
        "total": total,
        "preliminary_last": True,
        "targets": TARGETS,
        "years_sector": common,
        "sectors": sectors,
    }
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Wrote data.json: version={version}, "
          f"total {years_total[0]}-{years_total[-1]} (latest {total[-1]} Mt), "
          f"sectors {common[0]}-{common[-1]}")


if __name__ == "__main__":
    build()
