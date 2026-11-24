-- Documented rule: AnzFahrzeuge is empty exactly when AnzFahrzeugeStatus = Fehlend.
select
    traffic_count_id,
    count_status,
    vehicle_count
from {{ ref('stg_traffic__hourly_counts') }}
where (count_status = 'missing') <> (vehicle_count is null)
