{#
  Small adapter-dispatched helpers so the same models run on DuckDB (local) and on
  Spark / Databricks (dbt-databricks falls back to the spark__ versions).
  Everything else in the models sticks to SQL all engines share (count_if, percentile_cont, group by all).
#}

{# 'dd.mm.yyyy' -> date #}
{% macro parse_dmy_date(col) -%}{{ return(adapter.dispatch('parse_dmy_date')(col)) }}{%- endmacro %}
{% macro default__parse_dmy_date(col) -%}cast(try_strptime({{ col }}, '%d.%m.%Y') as date){%- endmacro %}
{% macro spark__parse_dmy_date(col) -%}to_date(try_to_timestamp({{ col }}, 'd.M.yyyy')){%- endmacro %}

{# Whole-string regex match. #}
{% macro regex_full_match(col, pattern) -%}{{ return(adapter.dispatch('regex_full_match')(col, pattern)) }}{%- endmacro %}
{% macro default__regex_full_match(col, pattern) -%}regexp_full_match({{ col }}, '{{ pattern }}'){%- endmacro %}
{% macro spark__regex_full_match(col, pattern) -%}({{ col }} rlike '^(?:{{ pattern }})$'){%- endmacro %}

{# 'weekday' | 'saturday' | 'sunday' #}
{% macro day_type(date_col) -%}{{ return(adapter.dispatch('day_type')(date_col)) }}{%- endmacro %}
{% macro default__day_type(date_col) -%}
case isodow({{ date_col }}) when 7 then 'sunday' when 6 then 'saturday' else 'weekday' end
{%- endmacro %}
{% macro spark__day_type(date_col) -%}
case dayofweek({{ date_col }}) when 1 then 'sunday' when 7 then 'saturday' else 'weekday' end
{%- endmacro %}

{#
  Number of local wall-clock hours in a day in Europe/Zurich: 23 on the last Sunday of March
  (02:00 does not exist), 25 on the last Sunday of October (02:00 happens twice), else 24.
#}
{% macro hours_in_local_day(date_col) -%}
case
    when extract(month from {{ date_col }}) = 3 and extract(day from {{ date_col }}) >= 25
        and {{ day_type(date_col) }} = 'sunday' then 23
    when extract(month from {{ date_col }}) = 10 and extract(day from {{ date_col }}) >= 25
        and {{ day_type(date_col) }} = 'sunday' then 25
    else 24
end
{%- endmacro %}
