"""Streamlit dashboard over the dbt marts.   streamlit run dashboard/app.py"""
import os

import duckdb
import plotly.express as px
import streamlit as st

DB = os.environ.get("TRADE_DB", "data/trade.duckdb")
st.set_page_config(page_title="Supplier trade intelligence", layout="wide")


@st.cache_data(ttl=300)   # re-read after a dbt rebuild without restarting Streamlit
def q(sql: str, params: tuple = ()):
    con = duckdb.connect(DB, read_only=True)
    try:
        return con.execute(sql, list(params)).df()
    finally:
        con.close()


st.title("Which supplier countries are gaining or losing ground?")
cats = q("select distinct hs4, category_label from mart_supplier_share order by 1")
label = st.sidebar.selectbox("Product category", cats["category_label"].tolist())
hs4 = cats.loc[cats["category_label"] == label, "hs4"].iloc[0]

share = q("select * from mart_supplier_share where hs4 = ? order by month", (hs4,))
latest = share["month"].max()
st.caption(f"Latest month loaded: {latest:%Y-%m}. US general imports by country of origin, "
           "Census Bureau international trade API.")

top = share[share["month"] == latest].nsmallest(10, "supplier_rank")
keep = top["cty_code"].tolist()

c1, c2 = st.columns(2)
with c1:
    st.subheader("Share gained or lost vs 12 months ago (top 10 suppliers)")
    chg = top.dropna(subset=["share_change_pp"]).sort_values("share_change_pp").copy()
    chg["direction"] = chg["share_change_pp"].apply(lambda v: "Gained" if v >= 0 else "Lost")
    fig = px.bar(chg, x="share_change_pp", y="cty_name", orientation="h", color="direction",
                 color_discrete_map={"Gained": "#2a9d8f", "Lost": "#e76f51"},
                 labels={"share_change_pp": "Share change (percentage points)", "cty_name": ""})
    fig.update_layout(showlegend=False)
    st.plotly_chart(fig, width="stretch")
with c2:
    prods = q("""
        select hs10, max(product) as product, max(price_unit) as unit, sum(import_value_usd) as v
        from mart_price_alerts where hs4 = ? group by 1 order by v desc
    """, (hs4,))
    choice = st.selectbox("Product (HS10)", prods["hs10"].tolist(),
                          format_func=lambda c: f"{prods.loc[prods.hs10 == c, 'product'].iloc[0]} ({c})")
    unit = prods.loc[prods["hs10"] == choice, "unit"].iloc[0]
    st.subheader(f"Unit price by origin, one product (USD per {unit})")
    ctl1, ctl2 = st.columns([3, 1])
    with ctl1:
        min_val = st.select_slider("Hide origin-months with trade below",
                                   options=[10_000, 50_000, 100_000, 250_000, 500_000], value=50_000,
                                   format_func=lambda v: f"${v:,.0f}")
    with ctl2:
        log_axis = st.checkbox("Log price axis", value=False)
    lines = q("""
        select month, cty_name, unit_price_usd, import_value_usd
        from mart_price_alerts where hs10 = ? and import_value_usd >= ?
    """, (choice, min_val))
    if len(lines):
        big = lines.groupby("cty_name")["import_value_usd"].sum().nlargest(8).index
        fig2 = px.line(lines[lines["cty_name"].isin(big)], x="month", y="unit_price_usd",
                       color="cty_name", labels={"unit_price_usd": f"USD / {unit}", "cty_name": ""})
        if log_axis:
            fig2.update_yaxes(type="log")
        st.plotly_chart(fig2, width="stretch")
    else:
        st.info("No origin-months above this trade threshold for this product.")
    st.caption("Each line is one product from one origin, so changes are like-for-like. "
               "Spikes at small trade volumes usually come from quantity or unit reporting, not real prices; "
               "raise the threshold or use the log axis. Top 8 origins by value.")

st.subheader("Share of import value over time (today's top 10 suppliers)")
st.plotly_chart(px.area(share[share["cty_code"].isin(keep)], x="month", y="share", color="cty_name",
                        labels={"share": "Share of category import value", "cty_name": ""}),
                width="stretch")

st.subheader("Price alerts: a product's price vs its own trailing 12 months (|z| >= 4 and a 10%+ move)")
alerts = q("""
    select month, cty_name as country, hs10, product, price_unit as unit,
           round(unit_price_usd, 2) as price, round(trailing_mean, 2) as trailing_avg,
           round((unit_price_usd / trailing_mean - 1) * 100) as pct_vs_avg,
           round(z_score, 1) as z_score, round(import_value_usd) as import_value_usd
    from mart_price_alerts
    where hs4 = ? and is_alert
    order by month desc, abs(z_score) desc
    limit 50
""", (hs4,))
if len(alerts):
    alerts["month"] = alerts["month"].dt.strftime("%Y-%m")
    st.dataframe(alerts, width="stretch", hide_index=True)
    st.caption("Very large jumps (3x or more) often reflect a change in the quantity unit reported "
               "rather than a real price move. Check the raw data before drawing conclusions.")
else:
    st.info("No alerts for this category.")
