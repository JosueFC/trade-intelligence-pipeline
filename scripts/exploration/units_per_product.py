"""Does any HS10 product report more than one quantity unit? If this prints rows, the unit-mixing
guard in mart_price_alerts is doing real work on your data.   python scripts/exploration/units_per_product.py
"""
import duckdb

c = duckdb.connect("data/trade.duckdb", read_only=True)
df = c.execute("""
    select i_commodity as hs10, max(commodity_desc) as description,
           string_agg(distinct unit_qy1, ', ') as units, count(distinct unit_qy1) as n_units
    from raw.census_imports
    where cty_code != '-' and unit_qy1 not in ('-', '')
    group by 1 having count(distinct unit_qy1) > 1
""").df()
print(df.to_string(index=False) if len(df) else "Every HS10 product reports exactly one quantity unit.")
