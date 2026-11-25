-- Regions seed with empty cells as real NULLs on every engine. DuckDB loads an empty CSV cell as NULL,
-- dbt-spark loads it as the string 'None' (found by scripts/compare_engines.py), so both are normalised here.
select
    region_code,
    region_name,
    case when trim(canton) in ('', 'None') then null else trim(canton) end as canton,
    case when trim(plz2) in ('', 'None') then null else trim(plz2) end     as plz2,
    is_national
from {{ ref('regions') }}
