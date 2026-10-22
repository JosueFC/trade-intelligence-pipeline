-- Fails if supplier shares for a month x category do not add to 100%.
select month, hs4, sum(share) as total_share
from {{ ref('mart_supplier_share') }}
group by 1, 2
having abs(sum(share) - 1) > 0.001
