"""Runs the dashboard script headlessly against the warehouse built by `make demo`.

Skipped when Streamlit or the warehouse is missing (plain `make test`); CI runs it after the demo
build with REQUIRE_DASHBOARD=1, so a skip there would be a failure.
"""

import os
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "dashboard" / "app.py"
WAREHOUSE = Path(os.environ.get("WAREHOUSE", APP.parents[1] / "data" / "warehouse.duckdb"))
REQUIRED = os.environ.get("REQUIRE_DASHBOARD") == "1"


def _skip(reason: str):
    if REQUIRED:
        pytest.fail(reason)
    pytest.skip(reason)


@pytest.fixture()
def app():
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        _skip("streamlit not installed (requirements-dashboard.txt)")
    if not WAREHOUSE.exists():
        _skip(f"no warehouse at {WAREHOUSE}; run make demo")
    return AppTest.from_file(str(APP), default_timeout=60)


def test_dashboard_renders_every_section(app):
    app.run()
    assert not app.exception, app.exception
    assert not app.error, [e.value for e in app.error]
    headers = [h.value for h in app.header]
    assert headers == [
        "Does the share of electric cars grow faster in Zug than in Zurich?",
        "When is rush hour in Zurich?",
        "Where is it busiest?",
    ]
    assert [h.value for h in app.subheader] == ["Zug and Zurich among all cantons"]
    regions = [m.label for m in app.metric]
    assert "Canton of Zug" in regions and "Canton of Zurich" in regions


def test_switching_peak_and_direction_keeps_working(app):
    app.run()
    app.radio(key="peak").set_value("am").run()
    assert not app.exception, app.exception
    table = app.dataframe[0].value
    assert list(table["rank_am_peak"]) == sorted(table["rank_am_peak"])
