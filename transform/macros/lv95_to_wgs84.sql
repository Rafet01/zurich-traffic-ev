{#
  Swiss LV95 (EPSG:2056) -> WGS84 latitude/longitude in degrees, with swisstopo's approximate formulas
  ("Näherungsformeln für die Transformation zwischen Schweizer Projektionskoordinaten und WGS84"),
  accurate to about 1 metre: plenty for a map of counting sites. Plain arithmetic, so it runs on every engine.
#}
{% macro _lv95_aux(east, north) -%}
    {%- set y = "((" ~ east ~ ") - 2600000) / 1000000.0" -%}
    {%- set x = "((" ~ north ~ ") - 1200000) / 1000000.0" -%}
    {{ return({'y': y, 'x': x}) }}
{%- endmacro %}

{% macro lv95_to_wgs84_lat(east, north) -%}
    {%- set a = _lv95_aux(east, north) -%}
    {%- set y, x = a['y'], a['x'] -%}
    ((16.9023892 + 3.238272 * {{ x }} - 0.270978 * {{ y }} * {{ y }} - 0.002528 * {{ x }} * {{ x }}
      - 0.0447 * {{ y }} * {{ y }} * {{ x }} - 0.0140 * {{ x }} * {{ x }} * {{ x }}) * 100 / 36)
{%- endmacro %}

{% macro lv95_to_wgs84_lon(east, north) -%}
    {%- set a = _lv95_aux(east, north) -%}
    {%- set y, x = a['y'], a['x'] -%}
    ((2.6779094 + 4.728982 * {{ y }} + 0.791484 * {{ y }} * {{ x }} + 0.1306 * {{ y }} * {{ x }} * {{ x }}
      - 0.0436 * {{ y }} * {{ y }} * {{ y }}) * 100 / 36)
{%- endmacro %}
