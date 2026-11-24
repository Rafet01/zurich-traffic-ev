-- Monthly view combining both sources despite their different grains:
--   traffic: hourly per measuring point  -> aggregated to month (City of Zurich)
--   car stock: one snapshot per half-year (later per month) per region -> taken "as of" the month,
--              i.e. the latest reliable snapshot on or before the first day of the month.
-- Nothing is interpolated; stock_age_days says how old the snapshot behind each month is.
with snapshots as (
    select
        region_code,
        stock_date,
        share_battery_electric
    from {{ ref('mart_ev_share_by_region') }}
    where share_battery_electric is not null and region_code in ('stadt_zh', 'kanton_zh')
),

as_of as (
    select
        t.month_start,
        s.region_code,
        s.stock_date,
        s.share_battery_electric,
        row_number() over (partition by t.month_start, s.region_code order by s.stock_date desc) as rn
    from {{ ref('mart_traffic_monthly') }} as t
    inner join snapshots as s on t.month_start >= s.stock_date
)

select
    t.month_start,
    t.measuring_points,
    t.avg_daily_vehicles_per_point,
    t.avg_working_day_vehicles_per_point,
    t.share_hours_measured,
    city.share_battery_electric                                         as bev_share_city_of_zurich,
    city.stock_date                                                     as city_stock_date,
    {{ dbt.datediff('city.stock_date', 't.month_start', 'day') }}       as city_stock_age_days,
    canton.share_battery_electric                                       as bev_share_canton_of_zurich,
    canton.stock_date                                                   as canton_stock_date,
    new_cars.share_battery_electric                                     as bev_share_of_cars_first_registered_this_month
from {{ ref('mart_traffic_monthly') }} as t
left join as_of as city on t.month_start = city.month_start and city.region_code = 'stadt_zh' and city.rn = 1
left join as_of as canton on t.month_start = canton.month_start and canton.region_code = 'kanton_zh' and canton.rn = 1
left join {{ ref('mart_bev_share_new_cars_monthly') }} as new_cars
    on t.month_start = new_cars.registration_month and new_cars.region_code = 'stadt_zh'
