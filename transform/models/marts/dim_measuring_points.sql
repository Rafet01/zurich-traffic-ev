-- One row per measuring point with its latest attributes and the period it delivered data.
with ranked as (
    select
        *,
        row_number() over (
            partition by measuring_point_id
            order by hour_start_local desc, source_row_number desc
        ) as recency
    from {{ ref('stg_traffic__hourly_counts') }}
),

coverage as (
    select
        measuring_point_id,
        min(hour_start_local)       as first_hour_local,
        max(hour_start_local)       as last_hour_local,
        count(*)                    as hours_delivered,
        count_if(count_status = 'measured') / count(*) as share_measured
    from {{ ref('stg_traffic__hourly_counts') }}
    group by all
)

select
    r.measuring_point_id,
    r.counting_site_id,
    r.counting_site_name,
    r.street,
    r.house_number,
    r.direction,
    r.direction_group,
    r.lv95_east,
    r.lv95_north,
    round({{ lv95_to_wgs84_lat('r.lv95_east', 'r.lv95_north') }}, 6) as latitude,
    round({{ lv95_to_wgs84_lon('r.lv95_east', 'r.lv95_north') }}, 6) as longitude,
    r.detector_count,
    c.first_hour_local,
    c.last_hour_local,
    c.hours_delivered,
    c.share_measured
from ranked as r
inner join coverage as c on r.measuring_point_id = c.measuring_point_id
where r.recency = 1
