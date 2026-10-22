-- Typed, cleaned view of the raw API rows. Grain: month x HS10 product x country.
-- Categories listed in seeds/category_allowlist.csv are restricted to those HS10 products
-- (e.g. masks inside the catch-all 630790); categories not listed keep every product.
with src as (
    select * from {{ source('raw', 'census_imports') }}
),
typed as (
    select
        cast(month || '-01' as date)                       as month,
        hs4,                                               -- the category we requested
        i_commodity                                        as hs10,
        commodity_desc,
        cty_code,
        cty_name,
        try_cast(gen_val_mo as double)                     as import_value_usd,
        try_cast(gen_qy1_mo as double)                     as quantity,
        nullif(nullif(unit_qy1, '-'), '')                  as quantity_unit,
        summary_lvl,
        _ingested_at
    from src
),
restricted as (
    select distinct hs4 from {{ ref('category_allowlist') }}
)
select t.*
from typed t
left join {{ ref('aggregate_country_codes') }} a on t.cty_code = a.cty_code
left join restricted r                            on t.hs4 = r.hs4
left join {{ ref('category_allowlist') }} al      on t.hs4 = al.hs4 and t.hs10 = al.hs10
where t.summary_lvl = 'DET'       -- individual countries only; drop country groupings (CGP)
  and a.cty_code is null          -- drop the "TOTAL FOR ALL COUNTRIES" row (code '-') and any extras
  and (r.hs4 is null or al.hs10 is not null)   -- allowlist applies only to restricted categories
  and t.import_value_usd is not null
  and t.import_value_usd >= 0
