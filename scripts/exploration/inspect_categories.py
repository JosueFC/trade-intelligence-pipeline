"""List every HS10 product under each configured category for the latest loaded month, with its
description, number of supplier countries and import value. Used to build the dbt allowlist.

    python scripts/exploration/inspect_categories.py
"""
import duckdb
import yaml

codes = [c["hs4"] for c in yaml.safe_load(open("config/categories.yml"))["categories"]]
c = duckdb.connect("data/trade.duckdb", read_only=True)
month = c.execute("select max(month) from raw.census_imports").fetchone()[0]
print(f"month: {month}\n")
print(c.execute("""
    select hs4 as category, i_commodity as hs10, max(commodity_desc) as description,
           count(distinct cty_code) as countries,
           round(sum(try_cast(gen_val_mo as double)) / 1e6, 1) as value_usd_millions
    from raw.census_imports
    where month = ? and cty_code != '-' and hs4 in (select unnest(?))
    group by 1, 2
    order by hs4, sum(try_cast(gen_val_mo as double)) desc
""", [month, codes]).df().to_string(index=False))
