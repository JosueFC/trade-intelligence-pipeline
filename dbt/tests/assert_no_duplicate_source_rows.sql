-- Fails if staging holds more than one row for the same month x category x HS10 product x country.
-- Duplicates can come from a repeated API response or overlapping prefixes in config/categories.yml.
-- (The old grain test ran on a GROUP BY output, where duplicates are impossible by construction.)
select month, hs4, hs10, cty_code, count(*) as n
from {{ ref('stg_census_imports') }}
group by 1, 2, 3, 4
having count(*) > 1
