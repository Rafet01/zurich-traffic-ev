-- swisstopo reference point: LV95 2'600'000 / 1'200'000 (old Bern observatory) = 46.9510811 N, 7.4386372 E,
-- and every measuring point must lie inside the City of Zurich (catches swapped or garbled coordinates).
select
    'reference' as what,
    cast(null as {{ dbt.type_string() }}) as measuring_point_id,
    {{ lv95_to_wgs84_lat('2600000.0', '1200000.0') }} as latitude,
    {{ lv95_to_wgs84_lon('2600000.0', '1200000.0') }} as longitude
where
    abs({{ lv95_to_wgs84_lat('2600000.0', '1200000.0') }} - 46.9510811) > 0.000001
    or abs({{ lv95_to_wgs84_lon('2600000.0', '1200000.0') }} - 7.4386372) > 0.000001

union all

select
    'outside the city' as what,
    measuring_point_id,
    latitude,
    longitude
from {{ ref('dim_measuring_points') }}
where
    latitude is not null
    and (latitude not between 47.32 and 47.44 or longitude not between 8.44 and 8.63)
