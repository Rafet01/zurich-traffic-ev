-- The passenger-car rows kept for the focus cantons must add up to the control totals of the same file,
-- per canton and fuel. A mismatch means the row filter and the totals disagree.
with rows_kept as (
    select
        stock_date,
        canton,
        coalesce(fuel_code, '') as fuel_code,
        count(*) as cars
    from {{ ref('stg_vehicle_stock__cars') }}
    group by all
),

totals as (
    select
        stock_date,
        canton,
        coalesce(fuel_code, '') as fuel_code,
        sum(vehicle_count) as cars
    from {{ ref('stg_vehicle_stock__totals') }}
    where
        vehicle_type_code = '{{ var("passenger_car_type_code") }}'
        and canton in (
            select r.canton from {{ ref('stg_seed__regions') }} as r
            where r.canton is not null
        )
    group by all
)

select
    coalesce(r.stock_date, t.stock_date) as stock_date,
    coalesce(r.canton, t.canton)         as canton,
    coalesce(r.fuel_code, t.fuel_code)   as fuel_code,
    r.cars                               as cars_in_rows,
    t.cars                               as cars_in_totals
from rows_kept as r
full outer join totals as t
    on r.stock_date = t.stock_date and r.canton = t.canton and r.fuel_code = t.fuel_code
where coalesce(r.cars, -1) <> coalesce(t.cars, -1)
