-- Traffic per month, City of Zurich. The set of measuring points changes over the years, so volumes
-- are reported per point (average over complete days), together with how many points contributed.
select
    month_start,
    count(distinct measuring_point_id)                              as measuring_points,
    count_if(is_complete)                                           as complete_point_days,
    count(*)                                                        as point_days,
    round(avg(case when is_complete then vehicles end), 1)          as avg_daily_vehicles_per_point,
    round(avg(case when is_complete and day_type = 'weekday' then vehicles end), 1)
        as avg_working_day_vehicles_per_point,
    round(sum(hours_measured) / sum(hours_delivered), 4)            as share_hours_measured,
    round(sum(hours_imputed) / sum(hours_delivered), 4)             as share_hours_imputed,
    round(sum(hours_missing) / sum(hours_delivered), 4)             as share_hours_missing
from {{ ref('int_traffic_point_days') }}
group by all
