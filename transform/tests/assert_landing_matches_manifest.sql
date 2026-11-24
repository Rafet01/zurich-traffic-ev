-- Reconciliation: every loaded file has exactly as many landed rows as the manifest says it kept,
-- and the control totals of a vehicle stock file add up to every valid row read.
with landed as (
    select
        _source_sha256 as source_sha256,
        count(*) as rows_landed
    from {{ source('bronze', 'traffic_counts_landing') }}
    group by 1
    union all
    select
        _source_sha256 as source_sha256,
        count(*) as rows_landed
    from {{ source('bronze', 'vehicle_stock_landing') }}
    group by 1
),

totals as (
    select
        _source_sha256 as source_sha256,
        sum(vehicle_count) as rows_in_totals
    from {{ source('bronze', 'vehicle_stock_totals_landing') }}
    group by 1
)

select
    m.dataset,
    m.source_file,
    m.rows_read,
    m.rows_kept,
    m.rows_rejected,
    coalesce(l.rows_landed, 0) as rows_landed,
    t.rows_in_totals
from {{ ref('stg_ingest__manifest') }} as m
left join landed as l on m.source_sha256 = l.source_sha256
left join totals as t on m.source_sha256 = t.source_sha256
where
    m.status = 'loaded'
    and (
        m.rows_kept <> coalesce(l.rows_landed, 0)
        or (m.dataset = 'vehicle_stock' and m.rows_read - m.rows_rejected <> coalesce(t.rows_in_totals, -1))
    )
