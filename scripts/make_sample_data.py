"""Load SYNTHETIC trade data into the raw table so you can build and test dbt models and the
dashboard before touching the real API. It mimics the real HS10 shape (several HS10 codes per
category, quantities with units, a "TOTAL FOR ALL COUNTRIES" row that reconciles with the countries)
and deliberately includes the messy cases real Census data has. Uses the production loader.

    python -m scripts.make_sample_data

Adversarial cases (each one exercises a path the clean data would never reach):
  * a country that disappears (ITALY stops reporting after 2025-06)
  * a month with a null unit and zero quantity (CHINA, 2024-03)
  * a unit switch inside one product (INDIA reports KG instead of pieces, 2025-02, 8517)
  * a zero-value row (MEXICO, 2023-05)
  * an injected price spike that the alert model must find (INDIA, 6403, 2025-11)
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
    codes = HS10.get(hs4) or [f"{hs4}{n:06d}" for n in (1, 2)]   # two HS10 codes per category
    for n, hs10 in enumerate(codes, start=1):
        total = 0.0
        for ci, (code, name) in enumerate(COUNTRIES):
            if name == "ITALY" and month >= "2025-07":
                continue                                        # country disappears
            trend = 1 + (0.02 * mi if ci == 0 else -0.01 * mi if ci == 1 else 0.0)
            qty = max(1000, random.gauss(25000, 4000) * trend / (1 + ci * 0.25))
            price = base * (0.8 + 0.4 * (n - 1)) * random.gauss(1, 0.04)
            if code == "5330" and month == "2025-11" and hs4 == "6403":
                price *= 1.9                                    # injected anomaly for the alert model
            val, row_unit, row_qty = qty * price, unit, qty
            if name == "CHINA" and month == "2024-03":
                row_unit, row_qty = "-", 0                      # null unit, zero quantity
            if name == "INDIA" and month == "2025-02" and hs4 == "8517" and n == 1:
                row_unit, row_qty = "KG", qty / 20              # unit switch within one product
            if name == "MEXICO" and month == "2023-05":
                val, row_qty = 0.0, 0                           # zero-value row
            total += val
            rows.append([code, name, hs10, f"SAMPLE {hs10}", f"{val:.0f}", f"{row_qty:.0f}", row_unit, "HS10", "DET"])
        # the API's own total row, which must reconcile with the countries above
        rows.append(["-", "TOTAL FOR ALL COUNTRIES", hs10, f"SAMPLE {hs10}", f"{total:.0f}", "1", unit, "HS10", "DET"])
    return rows


if __name__ == "__main__":
    con = connect()
    n = 0
    for m in MONTHS:
        for hs4 in CATS:
            n += load_partition(con, m, hs4, build(m, hs4))
    print(f"loaded {n} synthetic rows")
