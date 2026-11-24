-- No measuring point may deliver more hours on a day than the day has (23 / 24 / 25 with DST).
select
    measuring_point_id,
    local_date,
    hours_delivered,
    hours_expected
from {{ ref('int_traffic_point_days') }}
where hours_delivered > hours_expected
