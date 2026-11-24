-- One row per ingested file (current or superseded) with the checks a reviewer would ask for first.
with traffic as (
    select
        source_sha256,
        count_if(count_status = 'measured') / count(*)  as share_hours_measured,
        count_if(count_status = 'imputed') / count(*)   as share_hours_imputed,
        count_if(count_status = 'missing') / count(*)   as share_hours_missing,
        count(distinct measuring_point_id)              as measuring_points
    from {{ ref('stg_traffic__hourly_counts') }}
    group by all
),

stock as (
    select
        source_sha256,
        avg(case when plz2 is not null then 1.0 else 0.0 end) as plz2_coverage,
        avg(case when is_plug_in_hybrid is null then 0.0 else 1.0 end) as plug_in_hybrid_identifiable
    from {{ ref('stg_vehicle_stock__cars') }}
    group by all
),

stock_totals as (
    select
        source_sha256,
        sum(vehicle_count)                                                   as vehicles_in_file,
        sum(case when not is_swiss_canton then vehicle_count else 0 end)     as vehicles_outside_cantons,
        sum(case when is_unmapped_fuel_code then vehicle_count else 0 end)   as vehicles_unmapped_fuel
    from {{ ref('stg_vehicle_stock__totals') }}
    group by all
)

select
    m.dataset,
    m.source_file,
    m.source_sha256,
    m.partition_key,
    m.partition_key_source,
    m.layout,
    m.header_sha256,
    m.status,
    m.is_current_version,
    m.ingested_at,
    m.source_bytes,
    m.rows_read,
    m.rows_kept,
    m.rows_rejected,
    round(t.share_hours_measured, 4)    as share_hours_measured,
    round(t.share_hours_imputed, 4)     as share_hours_imputed,
    round(t.share_hours_missing, 4)     as share_hours_missing,
    t.measuring_points,
    round(s.plz2_coverage, 4)           as plz2_coverage,
    round(s.plug_in_hybrid_identifiable, 4) as plug_in_hybrid_identifiable,
    st.vehicles_in_file,
    st.vehicles_outside_cantons,
    st.vehicles_unmapped_fuel
from {{ ref('stg_ingest__manifest') }} as m
left join traffic as t on m.source_sha256 = t.source_sha256
left join stock as s on m.source_sha256 = s.source_sha256
left join stock_totals as st on m.source_sha256 = st.source_sha256
where m.status = 'loaded'
