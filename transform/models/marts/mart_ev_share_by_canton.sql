-- Battery-electric share of passenger cars for all 26 cantons and every snapshot, from the control totals
-- (every row of every file, so no postcode or sampling caveats). Puts Zug and Zurich in context: rank among
-- the cantons, distance to the national share, and growth per year since the canton's first snapshot.
with cantons as (
    select
        stock_date,
        canton,
        sum(vehicle_count)                                                    as cars,
        sum(case when is_battery_electric then vehicle_count else 0 end)      as battery_electric
    from {{ ref('stg_vehicle_stock__totals') }}
    where is_swiss_canton and vehicle_type_code = '{{ var("passenger_car_type_code") }}'
    group by stock_date, canton
),

national as (
    select
        stock_date,
        sum(battery_electric) / nullif(sum(cars), 0) as national_share
    from cantons
    group by stock_date
),

shares as (
    select
        c.stock_date,
        c.canton,
        c.cars,
        c.battery_electric,
        c.battery_electric / nullif(c.cars, 0)                      as bev_share,
        n.national_share,
        min(c.stock_date) over (partition by c.canton)              as first_stock_date,
        max(c.stock_date) over ()                                   as latest_stock_date
    from cantons as c
    inner join national as n on c.stock_date = n.stock_date
),

firsts as (
    select
        canton,
        bev_share as first_share
    from shares
    where stock_date = first_stock_date
)

select
    s.canton,
    s.stock_date,
    s.cars,
    s.battery_electric,
    round(s.bev_share, 5)                                                         as share_battery_electric,
    round(100 * (s.bev_share - s.national_share), 3)                              as pp_above_national,
    rank() over (partition by s.stock_date order by s.bev_share desc)             as rank_in_snapshot,
    count(*) over (partition by s.stock_date)                                 as cantons_in_snapshot,
    s.first_stock_date,
    round(
        100 * (s.bev_share - f.first_share) * 12
        / nullif({{ dbt.datediff('s.first_stock_date', 's.stock_date', 'month') }}, 0), 3
    )                                                                         as growth_pp_per_year_since_first,
    s.stock_date = s.latest_stock_date                                        as is_latest_snapshot
from shares as s
inner join firsts as f on s.canton = f.canton
