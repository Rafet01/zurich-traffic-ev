-- Vehicles per canton x vehicle type x fuel for every row of each current snapshot file (all of Switzerland).
with current_files as (
    select
        source_sha256,
        cast(partition_key as date) as stock_date
    from {{ ref('stg_ingest__manifest') }}
    where dataset = 'vehicle_stock' and is_current_version
)

select
    f.stock_date,
    t._source_sha256                                   as source_sha256,
    t.canton,
    -- the 26 cantons; FL = Liechtenstein, '-1' = unknown
    coalesce({{ regex_full_match('t.canton', '[A-Z]{2}') }} and t.canton <> 'FL', false) as is_swiss_canton,
    t.vehicle_type_code,
    t.fuel_code,
    coalesce(ft.powertrain, 'other')                   as powertrain,
    coalesce(ft.is_battery_electric, false)            as is_battery_electric,
    coalesce(ft.is_electrified, false)                 as is_electrified,
    ft.fuel_code is null and t.fuel_code is not null   as is_unmapped_fuel_code,
    t.vehicle_count
from {{ source('bronze', 'vehicle_stock_totals_landing') }} as t
inner join current_files as f on t._source_sha256 = f.source_sha256
left join {{ ref('fuel_types') }} as ft on t.fuel_code = ft.fuel_code
