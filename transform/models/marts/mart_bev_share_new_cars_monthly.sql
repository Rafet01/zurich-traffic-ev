-- Monthly signal from a half-yearly/monthly stock: in the LATEST snapshot, the battery-electric share
-- among cars by month of first registration. Caveat: only cars still registered (and registered in this
-- region today) are counted, so older months are thinned out by scrapping and moving.
with latest as (
    select max(stock_date) as stock_date
    from {{ ref('stg_vehicle_stock__cars') }}
),

cars as (
    select
        c.*,
        make_date(c.first_registration_year, c.first_registration_month, 1)
            as registration_month
    from {{ ref('stg_vehicle_stock__cars') }} as c
    inner join latest as l on c.stock_date = l.stock_date
    where c.first_registration_year >= 2015 and c.first_registration_month between 1 and 12
)

select
    r.region_code,
    c.registration_month,
    max(c.stock_date)                                           as stock_date,
    count(*)                                                    as cars_still_registered,
    count_if(c.is_battery_electric)                             as battery_electric,
    round(count_if(c.is_battery_electric) / count(*), 4)        as share_battery_electric
from cars as c
inner join {{ ref('stg_seed__regions') }} as r
    on not r.is_national and c.canton = r.canton and (r.plz2 is null or c.plz2 = r.plz2)
group by all
