-- Fails if a restricted category contains an HS10 product that is not on its allowlist.
select s.hs4, s.hs10
from {{ ref('stg_census_imports') }} s
where s.hs4 in (select hs4 from {{ ref('category_allowlist') }})
  and s.hs10 not in (select hs10 from {{ ref('category_allowlist') }} a where a.hs4 = s.hs4)
group by 1, 2
