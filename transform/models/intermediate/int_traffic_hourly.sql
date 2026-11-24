-- Hourly counts with calendar attributes and an explicit daylight-saving "fold".
-- The source has local wall-clock times without offset. On the last Sunday of October the hour
-- 02:00 is delivered twice (summer time first, then winter time), so (point, hour) is not unique.
-- dst_fold = 0 for the first occurrence in the file, 1 for the repeated hour. Row order decides.
with counts as (
    select
        *,
        row_number() over (
            partition by measuring_point_id, hour_start_local
            order by source_row_number
        ) - 1 as dst_fold
    from {{ ref('stg_traffic__hourly_counts') }}
)

select
    c.traffic_count_id,
    c.measuring_point_id,
    c.counting_site_id,
    c.direction_group,
    c.hour_start_local,
    c.dst_fold,
    cast(c.hour_start_local as date)                           as local_date,
    cast(date_trunc('month', c.hour_start_local) as date)      as month_start,
    cast(extract(hour from c.hour_start_local) as integer)     as hour_of_day,
    case
        when h.holiday_date is not null then 'holiday'
        else {{ day_type('cast(c.hour_start_local as date)') }}
    end                                                        as day_type,
    h.holiday_name,
    c.vehicle_count,
    c.count_status,
    c.count_status <> 'missing'                                as has_value
from counts as c
left join {{ ref('zurich_public_holidays') }} as h
    on cast(c.hour_start_local as date) = h.holiday_date
