-- One row per measuring point and local hour, typed and renamed. Current file version per year only.
with current_files as (
    select source_sha256
    from {{ ref('stg_ingest__manifest') }}
    where dataset = 'traffic_counts' and is_current_version
)

select
    -- lineage: every row can be traced back to file hash + row number
    l._source_sha256 || ':' || cast(l._source_row_number as {{ dbt.type_string() }}) as traffic_count_id,
    l._source_file                                     as source_file,
    l._source_sha256                                   as source_sha256,
    l._source_row_number                               as source_row_number,

    l.msid                                             as measuring_point_id,
    nullif(l.msname, 'Unbekannt')                      as measuring_point_name,
    l.zsid                                             as counting_site_id,
    l.zsname                                           as counting_site_name,
    l.achse                                            as street,
    nullif(l.hnr, 'Unbekannt')                         as house_number,
    try_cast(l.ekoord as double)                       as lv95_east,
    try_cast(l.nkoord as double)                       as lv95_north,
    l.richtung                                         as direction,
    case lower(l.richtung)
        when 'einwärts' then 'inbound'
        when 'auswärts' then 'outbound'
        else 'named'                                   -- towards a named place, e.g. 'Bucheggplatz'
    end                                                as direction_group,
    nullif(l.knummer, 'Unbekannt')                     as traffic_light_id,
    try_cast(l.anzdetektoren as integer)               as detector_count,

    -- start of the hour, local wall-clock time without offset (see int_traffic_hourly for DST)
    cast(l.messungdatzeit as timestamp)                as hour_start_local,
    cast(l.lieferdat as date)                          as delivered_on,
    try_cast(l.anzfahrzeuge as integer)                as vehicle_count,
    case l.anzfahrzeugestatus
        when 'Gemessen' then 'measured'
        when 'Imputiert' then 'imputed'                -- filled in by the city from the same hour in past years
        when 'Fehlend' then 'missing'
    end                                                as count_status
from {{ source('bronze', 'traffic_counts_landing') }} as l
inner join current_files as f on l._source_sha256 = f.source_sha256
