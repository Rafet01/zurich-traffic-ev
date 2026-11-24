-- One-time Databricks setup (run in a SQL editor / notebook attached to a SQL warehouse).
-- Unity Catalog medallion layout: bronze (raw landed data), silver (cleaned), gold (marts).
-- Change the catalog name if yours is not `workspace` (the default catalog in Free Edition workspaces).

use catalog workspace;

create schema if not exists bronze comment 'Raw landed rows of both sources, control totals and the ingest manifest';
create schema if not exists silver comment 'Typed, cleaned data (dbt staging + intermediate)';
create schema if not exists gold   comment 'Marts answering the traffic and EV questions (dbt marts)';

-- Files uploaded by load/databricks_load.py before COPY INTO.
create volume if not exists bronze.landing comment 'Landed Parquet files and the ingest manifest';

-- Same columns as the landed Parquet: raw strings + lineage. Typing happens in dbt (silver).
create table if not exists bronze.traffic_counts_landing (
    msid string, msname string, zsid string, zsname string, achse string, hnr string, hoehe string,
    ekoord string, nkoord string, richtung string, knummer string, kname string, anzdetektoren string,
    d1id string, d2id string, d3id string, d4id string, messungdatzeit string, lieferdat string,
    anzfahrzeuge string, anzfahrzeugestatus string,
    _source_file string, _source_sha256 string, _source_row_number bigint, _ingested_at string
) comment 'City of Zurich traffic counts, one row per measuring point and hour; (_source_sha256, _source_row_number) = exact CSV line';

create table if not exists bronze.vehicle_stock_landing (
    vehicle_class string, vehicle_type_code string, vehicle_type string, brand string, fuel_code string,
    fuel string, hybrid_code string, plugin_hybrid string, power_kw string, co2_wltp string,
    first_registration_year string, first_registration_month string, first_registration_date string,
    used_import_code string, registration_status_code string, canton string, plz_masked string,
    country_code string, data_as_of string,
    _source_file string, _source_sha256 string, _source_row_number bigint, _ingested_at string
) comment 'ASTRA vehicle stock, passenger cars in the focus cantons, canonical columns over six source layouts';

create table if not exists bronze.vehicle_stock_totals_landing (
    canton string, vehicle_type_code string, fuel_code string, vehicle_count bigint,
    _source_file string, _source_sha256 string, _ingested_at string
) comment 'Vehicles per canton x vehicle type x fuel for every row of each ASTRA file (control totals)';

-- In a team you would grant per layer, e.g.:
-- grant use schema, select on schema bronze to `data-engineers`;
-- grant use schema, select on schema gold to `analysts`;
