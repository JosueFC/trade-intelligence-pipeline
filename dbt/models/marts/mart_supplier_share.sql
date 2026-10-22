-- Share of each category's import value by supplier country, plus the change vs 12 months earlier.
with base as (
    select
        *,
        import_value_usd / sum(import_value_usd) over (partition by month, hs4) as share
    from {{ ref('int_supplier_month') }}
)
select
    cur.month,
    cur.hs4,
    coalesce(lab.label, cur.hs4)                        as category_label,
    cur.cty_code,
    cur.cty_name,
    cur.import_value_usd,
    cur.unit_price_usd,
    cur.price_unit,
    cur.share,
    prev.share                                          as share_12m_ago,
    (cur.share - prev.share) * 100                      as share_change_pp,
    rank() over (partition by cur.month, cur.hs4 order by cur.import_value_usd desc) as supplier_rank
from base cur
left join {{ ref('category_labels') }} lab on lab.hs4 = cur.hs4
left join base prev
  on  prev.hs4 = cur.hs4
  and prev.cty_code = cur.cty_code
  and prev.month = cur.month - interval 12 month
