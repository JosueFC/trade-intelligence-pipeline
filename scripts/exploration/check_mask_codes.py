"""List every product line under 630790 whose description mentions a mask or respirator and whether
it is on the dbt allowlist. Lines marked MISSING should probably be added to
dbt/seeds/category_allowlist.csv.   python scripts/exploration/check_mask_codes.py
"""
import csv

import duckdb

allow = {r["hs10"] for r in csv.DictReader(open("dbt/seeds/category_allowlist.csv")) if r["hs4"] == "630790"}
c = duckdb.connect("data/trade.duckdb", read_only=True)
rows = c.execute("""
    select i_commodity as hs10, max(commodity_desc) as description,
           round(sum(try_cast(gen_val_mo as double)) / 1e6, 1) as usd_millions_total
    from raw.census_imports
    where hs4 = '630790' and cty_code != '-'
      and (commodity_desc ilike '%MASK%' or commodity_desc ilike '%RESPIRATOR%')
    group by 1 order by 3 desc
""").fetchall()
print(f"{'hs10':12} {'on allowlist':13} {'$M total':>9}  description")
for hs10, desc, usd in rows:
    print(f"{hs10:12} {'yes' if hs10 in allow else 'MISSING':13} {usd:>9}  {desc}")
