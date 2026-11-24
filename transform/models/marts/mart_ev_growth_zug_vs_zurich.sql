-- Does the battery-electric share grow faster in Zug than in Zurich?
-- One row per region: first and last reliable snapshot, the share at both ends, and two growth measures:
--   * percentage points per year (absolute growth of the share),
--   * compound annual growth of the number of battery-electric cars (relative growth).
with reliable as (
    select *
    from {{ ref('mart_ev_share_by_region') }}
    where share_battery_electric is not null
),

ends as (
    select
        region_code,
        region_name,
        min(stock_date) as first_stock_date,
        max(stock_date) as last_stock_date,
        count(*)        as snapshots
    from reliable
    group by all
),

measured as (
    select
        e.region_code,
        e.region_name,
        e.snapshots,
        e.first_stock_date,
        e.last_stock_date,
        f.share_battery_electric                                       as first_share,
        l.share_battery_electric                                       as last_share,
        f.battery_electric                                             as first_battery_electric,
        l.battery_electric                                             as last_battery_electric,
        {{ dbt.datediff('e.first_stock_date', 'e.last_stock_date', 'month') }} / 12.0 as years
    from ends as e
    inner join reliable as f on e.region_code = f.region_code and e.first_stock_date = f.stock_date
    inner join reliable as l on e.region_code = l.region_code and e.last_stock_date = l.stock_date
)

select
    region_code,
    region_name,
    snapshots,
    first_stock_date,
    last_stock_date,
    round(years, 2)                                                         as years,
    first_share,
    last_share,
    round(100 * (last_share - first_share) / nullif(years, 0), 3)          as share_growth_pp_per_year,
    round(power(last_battery_electric / nullif(first_battery_electric, 0), 1 / nullif(years, 0)) - 1, 4)
        as battery_electric_cagr,
    rank() over (order by (last_share - first_share) / nullif(years, 0) desc) as rank_by_pp_per_year
from measured
