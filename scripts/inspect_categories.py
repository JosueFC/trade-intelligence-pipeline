import duckdb

c = duckdb.connect("data/trade.duckdb", read_only=True)

print(c.execute("""
    select hs4 as category, i_commodity as hs10, max(commodity_desc) as description,
           count(distinct cty_code) as countries,
           round(sum(try_cast(gen_val_mo as double)) / 1e6, 1) as value_usd_millions
    from raw.census_imports
    where month = '2026-06' and hs4 in ('392010', '4015', '630790')
      and cty_code != '-'
    group by 1, 2
    order by hs4, sum(try_cast(gen_val_mo as double)) desc
""").df().to_string(index=False))