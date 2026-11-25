-- Passenger cars per region and stock date. Two routes, one grain:
--   * canton and national regions from the control totals (every row of every file),
--   * postcode regions (City of Zurich = 80xx) from the vehicle rows, because only those carry a postcode.
with region_cantons as (
    select
        r.region_code,
        t.stock_date,
        sum(t.vehicle_count)                                              as cars,
        sum(case when t.is_battery_electric then t.vehicle_count else 0 end) as battery_electric,
        sum(case when t.is_electrified then t.vehicle_count else 0 end)    as electrified
    from {{ ref('stg_vehicle_stock__totals') }} as t
    inner join {{ ref('stg_seed__regions') }} as r
        on
            r.plz2 is null
            and ((not r.is_national and t.canton = r.canton) or (r.is_national and t.is_swiss_canton))
    where t.vehicle_type_code = '{{ var("passenger_car_type_code") }}'
    group by all
),

plz_coverage as (
    -- share of cars in the canton whose masked postcode has two digits, per snapshot
    select
        stock_date,
        canton,
        avg(case when plz2 is not null then 1.0 else 0.0 end) as plz2_coverage
    from {{ ref('stg_vehicle_stock__cars') }}
    group by all
),

region_postcodes as (
    select
        r.region_code,
        c.stock_date,
        count(*)                          as cars,
        count_if(c.is_battery_electric)   as battery_electric,
        count_if(c.is_electrified)        as electrified
    from {{ ref('stg_vehicle_stock__cars') }} as c
    inner join {{ ref('stg_seed__regions') }} as r
        on r.plz2 is not null and c.canton = r.canton and c.plz2 = r.plz2
    group by all
)

select
    region_code,
    stock_date,
    cars,
    battery_electric,
    electrified,
    cast(null as double) as plz2_coverage,  -- not applicable: cantons come from the totals
    true                 as is_reliable
from region_cantons

union all

select
    r.region_code,
    cov.stock_date,
    coalesce(p.cars, 0)                                          as cars,
    coalesce(p.battery_electric, 0)                              as battery_electric,
    coalesce(p.electrified, 0)                                   as electrified,
    cast(cov.plz2_coverage as double)                            as plz2_coverage,
    cov.plz2_coverage >= {{ var('min_plz2_coverage') }}          as is_reliable
from {{ ref('stg_seed__regions') }} as r
inner join plz_coverage as cov on r.plz2 is not null and r.canton = cov.canton
left join region_postcodes as p on r.region_code = p.region_code and cov.stock_date = p.stock_date
