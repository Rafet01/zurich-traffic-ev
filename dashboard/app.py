"""A small dashboard on the gold tables of the DuckDB warehouse.

    pip install -r requirements-dashboard.txt
    make dashboard            # = streamlit run dashboard/app.py

Reads `data/warehouse.duckdb` (or $WAREHOUSE) read-only, so it can stay open while dbt rebuilds.
Every chart answers one of the README questions and names the gold table it comes from.
"""

from __future__ import annotations

import os
from pathlib import Path

import altair as alt
import duckdb
import pandas as pd
import pydeck as pdk
import streamlit as st

WAREHOUSE = Path(os.environ.get("WAREHOUSE", Path(__file__).resolve().parents[1] / "data" / "warehouse.duckdb"))

QUERIES = {
    "ev_share": """
        select region_code, region_name, stock_date, is_reliable, cars, battery_electric,
               share_battery_electric, share_electrified
        from gold.mart_ev_share_by_region
        order by region_code, stock_date""",
    "ev_growth": """
        select region_code, region_name, snapshots, first_stock_date, last_stock_date, years,
               first_share, last_share, share_growth_pp_per_year, battery_electric_cagr, rank_by_pp_per_year
        from gold.mart_ev_growth_zug_vs_zurich
        order by rank_by_pp_per_year""",
    "peak_hours": """
        select direction_group, day_type, hour_of_day, days_observed, avg_vehicles_per_point,
               share_of_daily_traffic, busiest_rank
        from gold.mart_peak_hours
        order by direction_group, day_type, hour_of_day""",
    "busiest_sites": """
        select measuring_point_id, counting_site_name, street, direction, direction_group, latitude, longitude,
               working_days, avg_vehicles_per_hour_am_peak, avg_vehicles_per_hour_pm_peak,
               avg_vehicles_per_hour_all_day, busiest_hour_of_day, heavier_peak, rank_am_peak, rank_pm_peak
        from gold.mart_busiest_sites_at_peak
        order by rank_pm_peak""",
    "data_quality": """
        select dataset, source_file, partition_key, layout, status, is_current_version, rows_read, rows_kept,
               rows_rejected, share_hours_measured, share_hours_missing, plz2_coverage, ingested_at, ingest_seconds
        from gold.mart_data_quality
        order by dataset, partition_key""",
}

# Categorical slots in a fixed order (colour follows the entity, never its rank), light and dark steps.
PALETTE = {
    "light": ["#257de0", "#f47230", "#00b894", "#f2a600"],
    "dark": ["#338ced", "#e76624", "#00a888", "#d28e05"],
}
REGION_ORDER = ["kanton_zg", "kanton_zh", "stadt_zh", "schweiz"]
DAY_TYPE_ORDER = ["weekday", "saturday", "sunday", "holiday"]
DAY_TYPE_LABEL = {"weekday": "Working day", "saturday": "Saturday", "sunday": "Sunday", "holiday": "Public holiday"}
DIRECTION_LABEL = {"inbound": "Into the city", "outbound": "Out of the city", "named": "Other (named direction)"}


@st.cache_data(ttl=600)
def load(name: str, path: str) -> pd.DataFrame:
    with duckdb.connect(path, read_only=True) as con:
        return con.execute(QUERIES[name]).df()


def theme() -> str:
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except AttributeError:  # older Streamlit
        return "light"


def colour_scale(domain: list[str], labels: dict[str, str] | None = None) -> alt.Scale:
    return alt.Scale(domain=[(labels or {}).get(d, d) for d in domain], range=PALETTE[theme()][: len(domain)])


def ev_section(path: str) -> None:
    st.header("Does the share of electric cars grow faster in Zug than in Zurich?")
    growth = load("ev_growth", path)
    share = load("ev_share", path)
    if growth.empty:
        st.info("No vehicle stock loaded yet. Run `make ingest-vehicle-stock` and `make build`.")
        return

    cols = st.columns(len(growth))
    for col, row in zip(cols, growth.itertuples(), strict=True):
        cagr = "n/a" if pd.isna(row.battery_electric_cagr) else f"{row.battery_electric_cagr:.0%} BEVs per year"
        col.metric(
            row.region_name,
            f"{row.last_share:.1%}",
            f"{row.share_growth_pp_per_year:+.2f} pp per year",
            help=f"{row.snapshots} snapshots, {row.first_stock_date:%b %Y} to {row.last_stock_date:%b %Y}; {cagr}",
        )

    names = dict(zip(share.region_code, share.region_name, strict=False))
    regions = [r for r in REGION_ORDER if r in names]
    # Unreliable snapshots stay in as gaps (null share), so the line does not bridge them.
    plotted = share.assign(
        region=lambda d: d.region_code.map(names),
        share_battery_electric=lambda d: d.share_battery_electric.where(d.is_reliable),
    )
    base = alt.Chart(plotted).encode(
        x=alt.X("stock_date:T", title="Stock date"),
        y=alt.Y(
            "share_battery_electric:Q", title="Battery-electric share of passenger cars", axis=alt.Axis(format="%")
        ),
        color=alt.Color(
            "region:N",
            scale=colour_scale(regions, names),
            legend=alt.Legend(title=None, orient="top", labelLimit=0),
        ),
    )
    chart = alt.layer(
        base.mark_line(strokeWidth=2),
        base.mark_point(size=64, filled=True).encode(
            tooltip=[
                alt.Tooltip("region:N", title="Region"),
                alt.Tooltip("stock_date:T", title="Stock date", format="%b %Y"),
                alt.Tooltip("share_battery_electric:Q", title="BEV share", format=".1%"),
                alt.Tooltip("battery_electric:Q", title="BEVs", format=","),
                alt.Tooltip("cars:Q", title="Cars", format=","),
            ]
        ),
    ).properties(height=340)
    st.altair_chart(chart, width="stretch")
    unreliable = share[~share.is_reliable]
    if not unreliable.empty:
        dates = ", ".join(sorted({f"{d:%b %Y}" for d in unreliable.stock_date}))
        st.caption(f"Gap for postcode regions (too few two-digit postcodes in the file): {dates}.")
    st.caption(
        "Battery-electric only (fuel code E), the one definition that is identical in every ASTRA file. "
        "Cars are counted where they are registered. Source: `gold.mart_ev_share_by_region`, "
        "`gold.mart_ev_growth_zug_vs_zurich`."
    )


def peak_section(path: str) -> None:
    st.header("When is rush hour in Zurich?")
    peaks = load("peak_hours", path)
    if peaks.empty:
        st.info("No traffic counts loaded yet. Run `make ingest-traffic` and `make build`.")
        return
    groups = [g for g in DIRECTION_LABEL if g in set(peaks.direction_group)]
    group = (
        st.segmented_control("Direction", groups, default=groups[0], format_func=DIRECTION_LABEL.get, key="direction")
        or groups[0]
    )
    day_types = [d for d in DAY_TYPE_ORDER if d in set(peaks.day_type)]
    data = peaks[peaks.direction_group == group].assign(day=lambda d: d.day_type.map(DAY_TYPE_LABEL))

    am, pm = (6, 9), (16, 19)
    bands = pd.DataFrame({"start": [am[0], pm[0]], "end": [am[1], pm[1]], "label": ["AM peak", "PM peak"]})
    band_layer = (
        alt.Chart(bands)
        .mark_rect(opacity=0.08, color="gray")
        .encode(x="start:Q", x2="end:Q", tooltip=[alt.Tooltip("label:N", title="Window")])
    )
    lines = alt.Chart(data).encode(
        x=alt.X("hour_of_day:Q", title="Hour of day (local time, start of hour)", scale=alt.Scale(domain=[0, 23])),
        y=alt.Y("avg_vehicles_per_point:Q", title="Vehicles per hour per measuring point"),
        color=alt.Color(
            "day:N",
            scale=colour_scale(day_types, DAY_TYPE_LABEL),
            legend=alt.Legend(title=None, orient="top", labelLimit=0),
        ),
    )
    chart = alt.layer(
        band_layer,
        lines.mark_line(strokeWidth=2),
        lines.mark_point(size=40, filled=True, opacity=0.9).encode(
            tooltip=[
                alt.Tooltip("day:N", title="Day type"),
                alt.Tooltip("hour_of_day:Q", title="Hour"),
                alt.Tooltip("avg_vehicles_per_point:Q", title="Vehicles / hour / point", format=",.0f"),
                alt.Tooltip("share_of_daily_traffic:Q", title="Share of the day", format=".1%"),
                alt.Tooltip("days_observed:Q", title="Days"),
            ]
        ),
    ).properties(height=340)
    st.altair_chart(chart, width="stretch")
    st.caption(
        "Complete days only; public holidays of the canton of Zurich are their own day type. "
        "Shaded: the rush-hour windows used in the marts (06-09 and 16-19). Source: `gold.mart_peak_hours`."
    )


def sites_section(path: str) -> None:
    st.header("Where is it busiest?")
    sites = load("busiest_sites", path)
    if sites.empty:
        st.info("No complete working days yet.")
        return
    peak = st.radio("Peak", ["pm", "am"], horizontal=True, format_func=lambda p: f"{p.upper()} peak", key="peak")
    value = f"avg_vehicles_per_hour_{peak}_peak"
    rank = f"rank_{peak}_peak"
    sites = sites.sort_values(rank).assign(
        radius=lambda d: 40 + 160 * d[value] / d[value].max(),
        label=lambda d: d.counting_site_name + " · " + d.direction,
        volume=lambda d: d[value].round(0),
    )
    rgb = [int(PALETTE[theme()][0][i : i + 2], 16) for i in (1, 3, 5)]
    layer = pdk.Layer(
        "ScatterplotLayer",
        sites,
        get_position="[longitude, latitude]",
        get_radius="radius",
        get_fill_color=[*rgb, 170],
        get_line_color=[255, 255, 255],
        line_width_min_pixels=2,
        stroked=True,
        pickable=True,
    )
    view = pdk.ViewState(latitude=sites.latitude.mean(), longitude=sites.longitude.mean(), zoom=12)
    st.pydeck_chart(
        pdk.Deck(
            layers=[layer],
            initial_view_state=view,
            map_style=None,  # Streamlit's default basemap, no token needed
            tooltip={"text": "{label}\n{volume} vehicles per hour at the peak"},
        )
    )
    st.dataframe(
        sites[["measuring_point_id", "counting_site_name", "direction", rank, value, "busiest_hour_of_day"]],
        hide_index=True,
        column_config={
            rank: st.column_config.NumberColumn("Rank"),
            value: st.column_config.NumberColumn("Vehicles / hour", format="%.0f"),
            "busiest_hour_of_day": st.column_config.NumberColumn("Busiest hour"),
        },
    )
    st.caption(
        "Average vehicles per hour on complete working days. Coordinates converted from LV95 to WGS84 in dbt "
        "(swisstopo approximation, about 1 m). Source: `gold.mart_busiest_sites_at_peak`."
    )


def quality_section(path: str) -> None:
    with st.expander("Loaded files and data quality"):
        st.dataframe(
            load("data_quality", path),
            hide_index=True,
            column_config={
                "share_hours_measured": st.column_config.NumberColumn("Measured", format="percent"),
                "share_hours_missing": st.column_config.NumberColumn("Missing", format="percent"),
                "plz2_coverage": st.column_config.NumberColumn("2-digit postcodes", format="percent"),
            },
        )
        st.caption("Source: `gold.mart_data_quality`, one row per loaded file, built from the ingest manifest.")


def main() -> None:
    st.set_page_config(page_title="Zurich traffic and electric cars", layout="wide")
    st.title("Traffic and electric cars in Zurich and Zug")
    path = str(WAREHOUSE)
    if not WAREHOUSE.exists():
        st.error(f"No warehouse at `{path}`. Run `make demo` (synthetic data) or the ingest + `make build` first.")
        st.stop()
    st.caption(f"Gold tables from `{WAREHOUSE.name}`. Run `make demo` first to see it on synthetic data.")
    ev_section(path)
    peak_section(path)
    sites_section(path)
    quality_section(path)


main()
