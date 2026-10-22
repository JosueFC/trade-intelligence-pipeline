-- Fails (returns rows) if the month x hs4 x country grain has duplicates.
select month, hs4, cty_code, count(*) as n
from {{ ref('int_supplier_month') }}
group by 1, 2, 3
having count(*) > 1
