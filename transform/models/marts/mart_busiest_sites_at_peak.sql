-- WHERE is rush-hour traffic heaviest? Working days only (no weekends, no public holidays),
-- complete days only. Peak windows are configurable in dbt_project.yml.
with hourly as (
    select h.*
    from {{ ref('int_traffic_hourly') }} as h
    inner join {{ ref('int_traffic_point_days') }} as d
        on h.measuring_point_id = d.measuring_point_id and h.local_date = d.local_date
    where d.is_complete and h.day_type = 'weekday'
),

per_point as (
    select
        measuring_point_id,
        count(distinct local_date) as working_days,
        avg(case
            when hour_of_day >= {{ var('am_peak_start_hour') }} and hour_of_day < {{ var('am_peak_end_hour') }}
                then vehicle_count
        end)                       as avg_vehicles_per_hour_am_peak,
        avg(case
            when hour_of_day >= {{ var('pm_peak_start_hour') }} and hour_of_day < {{ var('pm_peak_end_hour') }}
                then vehicle_count
        end)                       as avg_vehicles_per_hour_pm_peak,
        avg(vehicle_count)         as avg_vehicles_per_hour_all_day
    from hourly
    group by all
),

busiest_hour as (
    select
        measuring_point_id,
        hour_of_day,
        row_number() over (partition by measuring_point_id order by avg(vehicle_count) desc) as rn
    from hourly
    group by measuring_point_id, hour_of_day
)

select
    p.measuring_point_id,
    m.counting_site_id,
    m.counting_site_name,
    m.street,
    m.direction,
    m.direction_group,
    m.lv95_east,
    m.lv95_north,
    p.working_days,
    round(p.avg_vehicles_per_hour_am_peak, 1)                         as avg_vehicles_per_hour_am_peak,
    round(p.avg_vehicles_per_hour_pm_peak, 1)                         as avg_vehicles_per_hour_pm_peak,
    round(p.avg_vehicles_per_hour_all_day, 1)                         as avg_vehicles_per_hour_all_day,
    round(
        greatest(p.avg_vehicles_per_hour_am_peak, p.avg_vehicles_per_hour_pm_peak)
        / nullif(p.avg_vehicles_per_hour_all_day, 0), 2
    )              as peak_to_day_ratio,
    b.hour_of_day                                                     as busiest_hour_of_day,
    case when p.avg_vehicles_per_hour_am_peak >= p.avg_vehicles_per_hour_pm_peak then 'am' else 'pm' end
        as heavier_peak,
    rank() over (order by p.avg_vehicles_per_hour_am_peak desc)       as rank_am_peak,
    rank() over (order by p.avg_vehicles_per_hour_pm_peak desc)       as rank_pm_peak
from per_point as p
inner join {{ ref('dim_measuring_points') }} as m on p.measuring_point_id = m.measuring_point_id
inner join busiest_hour as b on p.measuring_point_id = b.measuring_point_id and b.rn = 1
