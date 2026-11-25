-- Battery-electric share of the passenger car stock per region and snapshot, and its change since the
-- previous reliable snapshot of the same region (half-yearly until 2026, then monthly).
-- Postcode regions in snapshots with too few two-digit postcodes are kept, flagged, without numbers.
with shares as (
    select
        s.region_code,
        r.region_name,
        s.stock_date,
        s.cars,
        s.battery_electric,
        s.electrified,
        s.plz2_coverage,
        s.is_reliable,
        s.battery_electric / nullif(s.cars, 0) as share_battery_electric,
        s.electrified / nullif(s.cars, 0)      as share_electrified
    from {{ ref('int_vehicle_stock_by_region') }} as s
    inner join {{ ref('stg_seed__regions') }} as r on s.region_code = r.region_code
),

previous as (
    select
        region_code,
        stock_date,
        lag(stock_date) over (partition by region_code order by stock_date)             as previous_stock_date,
        lag(share_battery_electric) over (partition by region_code order by stock_date) as previous_share,
        lag(battery_electric) over (partition by region_code order by stock_date)       as previous_battery_electric
    from shares
    where is_reliable
)

select
    s.region_code,
    s.region_name,
    s.stock_date,
    s.is_reliable,
    s.plz2_coverage,
    p.previous_stock_date,
    case when s.is_reliable then s.cars end                                         as cars,
    case when s.is_reliable then s.battery_electric end                             as battery_electric,
    case when s.is_reliable then s.electrified end                                  as electrified,
    case when s.is_reliable then round(s.share_battery_electric, 5) end             as share_battery_electric,
    case when s.is_reliable then round(s.share_electrified, 5) end                  as share_electrified,
    {{ dbt.datediff('p.previous_stock_date', 's.stock_date', 'month') }}            as months_since_previous,
    round(100 * (s.share_battery_electric - p.previous_share), 3)                   as change_pp,
    round(
        100 * (s.share_battery_electric - p.previous_share) * 12
        / nullif({{ dbt.datediff('p.previous_stock_date', 's.stock_date', 'month') }}, 0), 3
    )                                                                               as change_pp_per_year,
    s.battery_electric - p.previous_battery_electric                                as battery_electric_added
from shares as s
left join previous as p on s.region_code = p.region_code and s.stock_date = p.stock_date
