select
    region_code,
    stock_date,
    share_battery_electric,
    share_electrified
from {{ ref('mart_ev_share_by_region') }}
where
    share_battery_electric < 0 or share_battery_electric > 1
    or share_electrified < share_battery_electric or share_electrified > 1
