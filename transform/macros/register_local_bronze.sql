{#
  Local Spark (dbt-spark, session mode) has no loader: expose the landed Parquet files and the
  manifest as bronze views so the models can run unchanged. No-op on every other target.
  DATA_DIR must be an absolute path (the Makefile sets it).
#}
{% macro register_local_bronze() %}
    {% if execute and target.type == 'spark' %}
        {% set data_dir = env_var('DATA_DIR') %}
        {% set views = {
            'traffic_counts_landing': 'parquet.`' ~ data_dir ~ '/landing/traffic_counts/*/*.parquet`',
            'vehicle_stock_landing': 'parquet.`' ~ data_dir ~ '/landing/vehicle_stock/*/*.parquet`',
            'vehicle_stock_totals_landing': 'parquet.`' ~ data_dir ~ '/landing/vehicle_stock_totals/*/*.parquet`',
            'ingest_manifest': 'json.`' ~ data_dir ~ '/manifest.jsonl`',
        } %}
        {% do run_query("create schema if not exists bronze") %}
        {% for name, location in views.items() %}
            {% do run_query("create or replace view bronze." ~ name ~ " as select * from " ~ location) %}
        {% endfor %}
    {% endif %}
{% endmacro %}
