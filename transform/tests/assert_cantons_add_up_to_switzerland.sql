-- The canton mart and the region mart take different routes to the national total; per snapshot they must agree,
-- and every canton appears once per snapshot.
with cantons as (
    select
        stock_date,
        sum(cars)                    as cars,
        sum(battery_electric)        as battery_electric,
        count(*)                     as canton_rows,
        count(distinct canton)       as cantons
    from {{ ref('mart_ev_share_by_canton') }}
    group by stock_date
)

select
    c.stock_date,
    c.cars,
    r.cars as national_cars,
    c.battery_electric,
    r.battery_electric as national_battery_electric,
    c.canton_rows,
    c.cantons
from cantons as c
left join {{ ref('mart_ev_share_by_region') }} as r
    on c.stock_date = r.stock_date and r.region_code = 'schweiz'
where
    r.cars is null
    or c.cars <> r.cars
    or c.battery_electric <> r.battery_electric
    or c.canton_rows <> c.cantons
