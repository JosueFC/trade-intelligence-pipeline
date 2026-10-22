-- Grain: month x category (HS4) x country.
--
-- Shares use the full import value. Unit price is computed ONLY from HS10 lines that report a
-- quantity in the category's dominant unit (e.g. pairs for footwear), so units are never mixed.
-- Caveat: a supplier's average price also reflects its product mix across the HS10 codes.
with unit_by_value as (
    select hs4, quantity_unit, sum(import_value_usd) as v
    from {{ ref('stg_census_imports') }}
    where quantity > 0 and quantity_unit is not null
    group by 1, 2
),
dominant_unit as (
    select hs4, quantity_unit as price_unit
    from unit_by_value
    qualify row_number() over (partition by hs4 order by v desc) = 1
)
select
    s.month,
    s.hs4,
    s.cty_code,
    max(s.cty_name)                                                     as cty_name,
    sum(s.import_value_usd)                                             as import_value_usd,
    max(d.price_unit)                                                   as price_unit,
    sum(case when s.quantity > 0 and s.quantity_unit = d.price_unit
             then s.import_value_usd end)                               as priced_value_usd,
    sum(case when s.quantity > 0 and s.quantity_unit = d.price_unit
             then s.quantity end)                                       as priced_quantity,
    sum(case when s.quantity > 0 and s.quantity_unit = d.price_unit
             then s.import_value_usd end)
      / nullif(sum(case when s.quantity > 0 and s.quantity_unit = d.price_unit
                        then s.quantity end), 0)                        as unit_price_usd
from {{ ref('stg_census_imports') }} s
left join dominant_unit d on s.hs4 = d.hs4
group by 1, 2, 3
