import os
import requests

URL = "https://api.census.gov/data/timeseries/intltrade/imports/hs"
KEY = os.environ.get("CENSUS_API_KEY")
MONTH = "2026-06"

EXPERIMENTS = {
    "A: HS4 shipping weight":      dict(get="CTY_CODE,CTY_NAME,GEN_VAL_MO,VES_WGT_MO,AIR_WGT_MO,CNT_WGT_MO", COMM_LVL="HS4", I_COMMODITY="6403"),
    "B: HS6 footwear 640399":      dict(get="CTY_CODE,CTY_NAME,I_COMMODITY,GEN_VAL_MO,GEN_QY1_MO,UNIT_QY1", COMM_LVL="HS6", I_COMMODITY="640399"),
    "C: HS6 smartphones 851713":   dict(get="CTY_CODE,CTY_NAME,I_COMMODITY,GEN_VAL_MO,GEN_QY1_MO,UNIT_QY1", COMM_LVL="HS6", I_COMMODITY="851713"),
    "D: HS10 wildcard 6403*":      dict(get="CTY_CODE,CTY_NAME,I_COMMODITY,GEN_VAL_MO,GEN_QY1_MO,UNIT_QY1", COMM_LVL="HS10", I_COMMODITY="6403*"),
}

for name, p in EXPERIMENTS.items():
    params = dict(p, time=MONTH, SUMMARY_LVL="DET")
    if KEY:
        params["key"] = KEY
    print(f"\n=== {name} ===")
    try:
        r = requests.get(URL, params=params, timeout=90)
    except Exception as e:
        print("request failed:", e)
        continue
    print("HTTP", r.status_code)
    if r.status_code != 200 or not r.text.strip():
        print(r.text[:300])
        continue
    data = r.json()
    header, rows = data[0], data[1:]
    print("columns:", header)
    print("rows:", len(rows))
    qty_cols = [c for c in header if c.endswith("QY1_MO") or c.endswith("WGT_MO")]
    for c in qty_cols:
        i = header.index(c)
        nz = sum(1 for row in rows if row[i] not in ("0", "", None))
        print(f"  non-zero {c}: {nz}")
    for row in rows[:3]:
        print("  sample:", row)