-- Warns if the newest month loaded is more than 5 months old (Census publishes with a lag).
{{ config(severity='warn') }}
select max(month) as latest_month
from {{ ref('int_supplier_month') }}
having max(month) < current_date - interval 5 month
