-- One row per registered passenger car in the focus cantons, for the current file of each stock date.
-- Values come from six different header layouts, already mapped to canonical columns during ingest.
with current_files as (
    select
        source_sha256,
        cast(partition_key as date) as stock_date,
        layout
    from {{ ref('stg_ingest__manifest') }}
    where dataset = 'vehicle_stock' and is_current_version
)

select
    l._source_sha256 || ':' || cast(l._source_row_number as {{ dbt.type_string() }}) as vehicle_record_id,
    l._source_file                                     as source_file,
    l._source_sha256                                   as source_sha256,
    l._source_row_number                               as source_row_number,
    f.stock_date,
    f.layout                                           as source_layout,

    l.vehicle_type_code,
    l.vehicle_type,
    l.brand,
    l.fuel_code,
    l.fuel                                             as fuel_name,
    coalesce(ft.powertrain, 'other')                   as powertrain,
    coalesce(ft.is_battery_electric, false)            as is_battery_electric,
    coalesce(ft.is_electrified, false)                 as is_electrified,
    -- plug-in hybrids are only identifiable since 2022 (Hybridcode) / Nov 2026 (Pluginhybrid)
    case
        when l.hybrid_code = 'OVC-HEV' or l.plugin_hybrid = '1' then true
        when l.hybrid_code is null and l.plugin_hybrid is null then null
        else false
    end                                                as is_plug_in_hybrid,
    try_cast(l.power_kw as integer)                    as power_kw,

    -- first registration: year/month columns in the old layout, one dd.mm.yyyy date in the new one
    coalesce(
        try_cast(l.first_registration_year as integer),
        extract(year from {{ parse_dmy_date('l.first_registration_date') }})
    )                                                  as first_registration_year,
    coalesce(
        try_cast(l.first_registration_month as integer),
        extract(month from {{ parse_dmy_date('l.first_registration_date') }})
    )                                                  as first_registration_month,
    l.used_import_code,

    l.registration_status_code,
    l.canton,
    l.plz_masked,
    -- postcode is masked: '80..' (two digits) in most files, '8...' (one digit) in July 2022
    case when {{ regex_full_match('l.plz_masked', '[0-9]{2}[.]{2}') }} then left(l.plz_masked, 2) end
        as plz2,
    l.country_code
from {{ source('bronze', 'vehicle_stock_landing') }} as l
inner join current_files as f on l._source_sha256 = f.source_sha256
left join {{ ref('fuel_types') }} as ft on l.fuel_code = ft.fuel_code
