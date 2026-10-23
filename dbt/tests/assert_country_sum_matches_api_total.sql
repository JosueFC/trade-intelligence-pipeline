-- Reconciliation: for each month x HS10 product, the sum of the individual countries we keep must
-- match the API's own "TOTAL FOR ALL COUNTRIES" row (code '-') within 1%.
-- This can catch a dropped country, a wrong filter, a partial load or a silent API change.
-- Severity is 'warn' until we have watched it on real data (rounding or Census suppression may
-- legitimately cause small differences); change it to 'error' once it has been quiet for a while.
{{ config(severity='warn') }}
with api_totals as (
    select month, hs4, i_commodity as hs10, try_cast(gen_val_mo as double) as api_total
    from {{ source('raw', 'census_imports') }}
    where cty_code = '-' and summary_lvl = 'DET'
),
country_sums as (
    select month, hs4, i_commodity as hs10, sum(try_cast(gen_val_mo as double)) as country_sum
    from {{ source('raw', 'census_imports') }}
    where cty_code <> '-' and summary_lvl = 'DET'
    group by 1, 2, 3
)
select
    t.month, t.hs4, t.hs10, t.api_total, s.country_sum,
    abs(coalesce(s.country_sum, 0) - t.api_total) / t.api_total as relative_difference
from api_totals t
left join country_sums s on s.month = t.month and s.hs4 = t.hs4 and s.hs10 = t.hs10
where t.api_total >= 100000
  and abs(coalesce(s.country_sum, 0) - t.api_total) / t.api_total > 0.01
