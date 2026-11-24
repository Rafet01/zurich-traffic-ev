-- WHEN is traffic heaviest? Average vehicles per measuring point for every hour of the day,
-- by direction and day type, on complete days only (no outage hours dragging averages down).
with hourly as (
    select h.*
    from {{ ref('int_traffic_hourly') }} as h
    inner join {{ ref('int_traffic_point_days') }} as d
        on h.measuring_point_id = d.measuring_point_id and h.local_date = d.local_date
    where d.is_complete
),

by_hour as (
    select
        direction_group,
        day_type,
        hour_of_day,
        count(*)                                                     as point_hours,
        count(distinct local_date)                                   as days_observed,
        avg(vehicle_count)                                           as avg_vehicles_per_point,
        percentile_cont(0.5) within group (order by vehicle_count)  as median_vehicles_per_point,
        sum(vehicle_count)                                           as vehicles
    from hourly
    group by all
)

select
    direction_group,
    day_type,
    hour_of_day,
    point_hours,
    days_observed,
    round(avg_vehicles_per_point, 1)                                 as avg_vehicles_per_point,
    median_vehicles_per_point,
    round(vehicles / sum(vehicles) over (partition by direction_group, day_type), 4) as share_of_daily_traffic,
    rank() over (partition by direction_group, day_type order by avg_vehicles_per_point desc) as busiest_rank
from by_hour
