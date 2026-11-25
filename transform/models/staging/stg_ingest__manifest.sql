-- One row per ingest attempt. is_current_version marks the newest loaded file per dataset and partition
-- (traffic: one file per year, regenerated daily; vehicle stock: one snapshot per stock date).
select
    dataset,
    source_file,
    source_uri,
    sha256                                       as source_sha256,
    bytes                                        as source_bytes,
    layout,
    header_sha256,
    rows_read,
    rows_kept,
    rows_rejected,
    cast(partition_key as {{ dbt.type_string() }}) as partition_key,
    partition_key_source,
    cast(ingested_at as timestamp)               as ingested_at,
    cast(duration_seconds as double)             as duration_seconds,
    status,
    status = 'loaded'
    and row_number() over (
        partition by dataset, cast(partition_key as {{ dbt.type_string() }}), status = 'loaded'
        order by ingested_at desc
    ) = 1                                        as is_current_version
from {{ source('bronze', 'ingest_manifest') }}
