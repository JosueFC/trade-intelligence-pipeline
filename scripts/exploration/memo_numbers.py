"""Numbers for the findings memo: supplier shares for the SAME months (Jan-Aug) of each year, so 2026
(data through August) compares fairly with 2023-2025.

    python scripts/exploration/memo_numbers.py
"""
import duckdb
import pandas as pd

LAST_MONTH = 8          # compare January..August of every year
c = duckdb.connect("data/trade.duckdb", read_only=True)
df = c.execute("""
    select year(s.month) as yr, s.hs4, coalesce(l.label, s.hs4) as category, s.cty_name,
           sum(s.import_value_usd) as value
    from int_supplier_month s
    left join category_labels l on l.hs4 = s.hs4
    where month(s.month) <= ?
    group by 1, 2, 3, 4
""", [LAST_MONTH]).df()

years = sorted(df["yr"].unique())
for (hs4, category), g in df.groupby(["hs4", "category"]):
    g = g.copy()
    totals = g.groupby("yr")["value"].sum()
    g["share"] = g["value"] / g["yr"].map(totals) * 100
    hhi = g.groupby("yr")["share"].apply(lambda s: (s ** 2).sum())
    print("=" * 78)
    print(f"{category}  [{hs4}]   (Jan-Aug of each year)")
    print("total import value, $M: " + "   ".join(f"{y}: {totals[y] / 1e6:,.0f}" for y in years))
    print("HHI (0-10000):          " + "   ".join(f"{y}: {hhi[y]:,.0f}" for y in years))
    piv = g.pivot(index="cty_name", columns="yr", values="share").fillna(0).round(1)
    last = years[-1]
    piv["change_pp"] = (piv[last] - piv[years[0]]).round(1)
    out = piv.sort_values(last, ascending=False).head(7)
    out.columns = [f"{c}" if isinstance(c, str) else f"{int(c)} %" for c in out.columns]
    print(out.to_string())
    movers = piv.sort_values("change_pp")
    print("biggest losers :", ", ".join(f"{n} ({v:+.1f}pp)" for n, v in movers["change_pp"].head(3).items()))
    print("biggest gainers:", ", ".join(f"{n} ({v:+.1f}pp)" for n, v in movers["change_pp"].tail(3)[::-1].items()))
print()
print(pd.Timestamp.today().date(), "- shares are of import value; each year covers January to", LAST_MONTH)
