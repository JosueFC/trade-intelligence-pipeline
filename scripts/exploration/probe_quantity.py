"""Check which product levels (HS4, HS6, HS10) report quantities or weights.
This showed that quantities exist only at HS10, which is why ingestion works at HS10.

    python scripts/exploration/probe_quantity.py [YYYY-MM]
"""
import datetime as dt
import os
import sys

import requests

URL = "https://api.census.gov/data/timeseries/intltrade/imports/hs"
KEY = os.environ.get("CENSUS_API_KEY")
if len(sys.argv) > 1:
    MONTH = sys.argv[1]
else:
    d = dt.date.today().replace(day=1) - dt.timedelta(days=100)   # a month that is certainly published
    MONTH = f"{d.year:04d}-{d.month:02d}"

EXPERIMENTS = {
    "A: HS4 shipping weight": dict(get="CTY_CODE,CTY_NAME,GEN_VAL_MO,VES_WGT_MO,AIR_WGT_MO,CNT_WGT_MO",
                                   COMM_LVL="HS4", I_COMMODITY="6403"),
    "B: HS6 footwear 640399": dict(get="CTY_CODE,CTY_NAME,I_COMMODITY,GEN_VAL_MO,GEN_QY1_MO,UNIT_QY1",
                                   COMM_LVL="HS6", I_COMMODITY="640399"),
    "C: HS10 wildcard 6403*": dict(get="CTY_CODE,CTY_NAME,I_COMMODITY,GEN_VAL_MO,GEN_QY1_MO,UNIT_QY1",
                                   COMM_LVL="HS10", I_COMMODITY="6403*"),
}

print("month:", MONTH)
for name, p in EXPERIMENTS.items():
    params = dict(p, time=MONTH, SUMMARY_LVL="DET")
    if KEY:
        params["key"] = KEY
    print(f"\n=== {name} ===")
    r = requests.get(URL, params=params, timeout=(15, 180))
    print("HTTP", r.status_code)
    if r.status_code != 200 or not r.text.strip():
        print(r.text[:300])
        continue
    header, rows = r.json()[0], r.json()[1:]
    print("rows:", len(rows))
    for col in [c for c in header if c.endswith("QY1_MO") or c.endswith("WGT_MO")]:
        i = header.index(col)
        print(f"  non-zero {col}:", sum(1 for row in rows if row[i] not in ("0", "", None)))
    for row in rows[:2]:
        print("  sample:", row)
