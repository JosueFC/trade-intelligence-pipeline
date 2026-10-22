"""Load SYNTHETIC trade data into the raw table so you can build and test dbt models and the
dashboard before touching the real API. Mimics the real HS10 shape (several HS10 codes per HS4
category, quantities with units, a "TOTAL FOR ALL COUNTRIES" row). Uses the production loader.

    python -m scripts.make_sample_data
"""
import random

from ingest.census_imports import EXPECTED_COLUMNS, connect, load_partition, months_between

random.seed(42)
COUNTRIES = [
    ("5700", "CHINA"), ("2010", "MEXICO"), ("5330", "INDIA"), ("5830", "TAIWAN"),
    ("5520", "VIETNAM"), ("4280", "GERMANY"), ("5880", "JAPAN"), ("5800", "KOREA, SOUTH"),
    ("4120", "UNITED KINGDOM"), ("4759", "ITALY"), ("5600", "INDONESIA"), ("5490", "THAILAND"),
]
CATS = {"8517": ("NO", 60.0), "6403": ("PRS", 14.0), "9503": ("NO", 9.0), "630790": ("NO", 0.5)}  # unit, base price
# 630790 gets one allowlisted mask code and one non-mask code so the dbt allowlist is exercised
HS10 = {"630790": ["6307909870", "6307909891"]}
MONTHS = months_between("2023-01", "2025-12")


def build(month: str, hs4: str):
    unit, base = CATS[hs4]
    mi = MONTHS.index(month)
    rows = [EXPECTED_COLUMNS]
    tot_val = 0.0
    codes = HS10.get(hs4) or [f"{hs4}{n:06d}" for n in (1, 2)]   # two HS10 codes per category
    for n, hs10 in enumerate(codes, start=1):
        for ci, (code, name) in enumerate(COUNTRIES):
            trend = 1 + (0.02 * mi if ci == 0 else -0.01 * mi if ci == 1 else 0.0)
            qty = max(1000, random.gauss(25000, 4000) * trend / (1 + ci * 0.25))
            price = base * (0.8 + 0.4 * (n - 1)) * random.gauss(1, 0.04)
            if code == "5330" and month == "2025-11" and hs4 == "6403":
                price *= 1.9                            # injected anomaly for the alert model
            val = qty * price
            tot_val += val
            rows.append([code, name, hs10, f"SAMPLE {hs10}", f"{val:.0f}", f"{qty:.0f}", unit, "HS10", "DET"])
        rows.append(["-", "TOTAL FOR ALL COUNTRIES", hs10, f"SAMPLE {hs10}", f"{tot_val:.0f}", "1", unit, "HS10", "DET"])
    return rows


if __name__ == "__main__":
    con = connect()
    n = 0
    for m in MONTHS:
        for hs4 in CATS:
            n += load_partition(con, m, hs4, build(m, hs4))
    print(f"loaded {n} synthetic rows")
