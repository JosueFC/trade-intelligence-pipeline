import duckdb

c = duckdb.connect("data/trade.duckdb", read_only=True)

print("--- Row counts ---")
print(c.execute("""
    select count(*) as total,
           sum(case when try_cast(gen_val_mo as double) = 0 then 1 else 0 end) as zero_value_rows,
           sum(case when try_cast(gen_qy1_mo as double) = 0 then 1 else 0 end) as zero_qty_rows
    from raw.census_imports
""").df().to_string(index=False))

print("\n--- Distinct countries (look for non-countries) ---")
print(c.execute("""
    select cty_code, cty_name, count(*) as rows
    from raw.census_imports group by 1, 2 order by 1
""").df().to_string(index=False))

print("\n--- Top 5 suppliers, latest month, per category ---")
print(c.execute("""
    select hs4, cty_name, round(share * 100, 1) as share_pct, round(unit_price_usd, 2) as unit_price
    from mart_supplier_share
    where month = (select max(month) from mart_supplier_share) and supplier_rank <= 5
    order by hs4, supplier_rank
""").df().to_string(index=False))