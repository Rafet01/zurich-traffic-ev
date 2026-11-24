-- (measuring point, local hour, DST fold) identifies an hourly count. Duplicates beyond the repeated
-- 02:00 hour of the autumn DST night would mean the file delivered a row twice.
select
    measuring_point_id,
    hour_start_local,
    dst_fold,
    count(*) as n
from {{ ref('int_traffic_hourly') }}
group by all
having count(*) > 1 or max(dst_fold) > 1
