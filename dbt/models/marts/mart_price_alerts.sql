-- Price alerts are detected PER PRODUCT (HS10) and supplier country, comparing each month with
-- the same product's own trailing 12 months, in the same quantity unit. This avoids false alarms caused by a country's
-- product mix changing (the average price of a mixed basket moves even when no price does).
{% set min_months = 6 %}
{% set z_threshold = var('price_alert_z', 4) %}
{% set min_value = var('alert_min_value_usd', 100000) %}
{% set min_pct = var('alert_min_pct', 0.10) %}
with lines as (
    select
        month, hs4, hs10, cty_code,
        max(commodity_desc)                                  as product,
        max(cty_name)                                        as cty_name,
        quantity_unit                                        as price_unit,
        sum(import_value_usd)                                as import_value_usd,
        sum(quantity)                                        as quantity,
        sum(import_value_usd) / nullif(sum(quantity), 0)     as unit_price_usd
    from {{ ref('stg_census_imports') }}
    where quantity > 0 and quantity_unit is not null
    group by month, hs4, hs10, cty_code, quantity_unit   -- never add quantities of different units
),
hist as (
    select
        *,
        avg(unit_price_usd)         over w as trailing_mean,
        stddev_samp(unit_price_usd) over w as trailing_sd,
        count(unit_price_usd)       over w as trailing_n
    from lines
    window w as (
        partition by hs10, cty_code, price_unit    -- a unit change starts a new series
        order by month
        range between interval 12 month preceding and interval 1 month preceding
    )
)
select
    month, hs4, hs10, product, cty_code, cty_name, price_unit,
    import_value_usd, unit_price_usd, trailing_mean, trailing_sd, trailing_n,
    (unit_price_usd - trailing_mean) / nullif(trailing_sd, 0)  as z_score,
    case when trailing_n >= {{ min_months }}
          and import_value_usd >= {{ min_value }}
          and abs(unit_price_usd / nullif(trailing_mean, 0) - 1) >= {{ min_pct }}
          and abs((unit_price_usd - trailing_mean) / nullif(trailing_sd, 0)) >= {{ z_threshold }}
         then true else false end                              as is_alert
from hist
