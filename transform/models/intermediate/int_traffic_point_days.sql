-- One row per measuring point and local day. A day is complete when every hour that exists that day
-- (23, 24 or 25 because of DST) has a value; only complete days are used for daily volumes.
with days as (
    select
        measuring_point_id,
        counting_site_id,
        direction_group,
        local_date,
        month_start,
        day_type,
        count(*)                            as hours_delivered,
        count_if(count_status = 'measured') as hours_measured,
        count_if(count_status = 'imputed')  as hours_imputed,
        count_if(count_status = 'missing')  as hours_missing,
        count_if(has_value)                 as hours_with_value,
        sum(vehicle_count)                  as vehicles
    from {{ ref('int_traffic_hourly') }}
    group by measuring_point_id, counting_site_id, direction_group, local_date, month_start, day_type
)

select
    *,
    {{ hours_in_local_day('local_date') }}                         as hours_expected,
    hours_with_value = {{ hours_in_local_day('local_date') }}      as is_complete
from days
