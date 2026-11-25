import json
from collections import Counter
from datetime import date

import make_fixtures as fx
import pyarrow.parquet as pq
import pytest
from common import RemoteInfo
from vehicle_layouts import CANONICAL_COLUMNS, resolve
from vehicle_stock import (
    ingest,
    load_focus_cantons,
    stock_date_from_data,
    stock_date_from_http,
    stock_date_from_name,
)

CANTONS = {"ZH", "ZG"}


@pytest.mark.parametrize(
    "header,layout",
    [
        (fx.BEST_2019_07, "astra_best"),  # typo "Erstinvekehrsetzung_Kanton", trailing "V58"
        (fx.BEST_2022_07, "astra_best"),
        (fx.BEST_2023_01, "astra_best"),  # "Erstinverkehrsetzung_Monat]"
        (fx.BEST_CURRENT, "astra_best"),
        (fx.OGD, "astra_ogd"),  # new names, Treibstoff holds the code
    ],
)
def test_every_known_header_resolves(header, layout):
    name, positions = resolve(header)
    assert name == layout
    by_col = dict(zip(CANONICAL_COLUMNS, positions, strict=True))
    assert header[by_col["fuel_code"]] in ("Treibstoff_Code", "Treibstoff")
    assert header[by_col["canton"]] in ("Inverkehrsetzung_Kanton", "Inverkehrsetzungskanton")
    if layout == "astra_best":
        assert by_col["first_registration_month"] is not None  # also with the stray "]"


def test_unknown_layout_is_rejected():
    with pytest.raises(ValueError, match="unknown vehicle stock layout"):
        resolve(["Kanton", "Treibstoff", "Anzahl"])


@pytest.mark.parametrize(
    "value,expected",
    [("01.07.2022", date(2022, 7, 1)), ("31.10.2026", date(2026, 11, 1)), ("", None)],
)
def test_stock_date_from_datenstand(value, expected):
    assert stock_date_from_data(value) == expected


def test_stock_date_fallbacks():
    assert stock_date_from_name("BEST-20190701.txt") == date(2019, 7, 1)
    assert stock_date_from_name("best_ogd.txt") is None
    assert stock_date_from_http(RemoteInfo(last_modified="Mon, 02 Nov 2026 07:56:00 GMT")) == date(2026, 11, 1)


@pytest.mark.parametrize("name", ["BEST-20190701.txt", "BEST-20220701.txt", "BEST-20230101.txt", "best_ogd.txt"])
def test_rows_and_totals_reconcile(fixtures, tmp_path, name):
    src = fixtures / "vehicle_stock" / name
    e = ingest(str(src), CANTONS, tmp_path / "rows", tmp_path / "totals", tmp_path / "manifest.jsonl")
    assert e.status == "loaded"

    rows = pq.read_table(e.output_path).to_pylist()
    totals = pq.read_table(e.totals_path).to_pylist()
    assert len(rows) == e.rows_kept
    assert sum(t["vehicle_count"] for t in totals) == e.rows_read - e.rows_rejected
    assert {r["canton"] for r in rows} <= CANTONS and {r["vehicle_type_code"] for r in rows} == {"001"}

    # kept rows per canton and fuel == control totals for passenger cars in the focus cantons
    from_rows = Counter((r["canton"], r["fuel_code"]) for r in rows)
    from_totals = {
        (t["canton"], t["fuel_code"]): t["vehicle_count"]
        for t in totals
        if t["canton"] in CANTONS and t["vehicle_type_code"] == "001"
    }
    assert dict(from_rows) == from_totals


def test_layout_specific_details(fixtures, tmp_path):
    def land(name):
        e = ingest(
            str(fixtures / "vehicle_stock" / name), CANTONS, tmp_path / "r", tmp_path / "t", tmp_path / "m.jsonl"
        )
        return e, pq.read_table(e.output_path).to_pylist()

    e2019, rows2019 = land("BEST-20190701.txt")
    assert e2019.rows_rejected == 1  # the truncated row
    assert e2019.partition_key == "2019-07-01" and e2019.partition_key_source == "file name"
    assert all(r["hybrid_code"] is None for r in rows2019)  # column did not exist yet

    e2022, rows2022 = land("BEST-20220701.txt")
    assert {len(r["plz_masked"]) for r in rows2022} == {4} and all(r["plz_masked"][1] == "." for r in rows2022)

    eogd, rows_ogd = land("best_ogd.txt")
    assert eogd.layout == "astra_ogd"
    assert eogd.partition_key == "2026-11-01" and eogd.partition_key_source == "data (Datenstand)"
    assert all(r["first_registration_date"] and r["first_registration_year"] is None for r in rows_ogd)


def test_quotes_inside_values_do_not_break_parsing(tmp_path):
    # a value starting with a quote would swallow the following tabs with default CSV quoting
    header = fx.BEST_CURRENT
    v = {"canton": "ZH", "plz": "80..", "vcode": "001", "vname": "Personenwagen", "fuel": "E", "hybrid": "N/A",
         "brand": "VW", "model": '"ID.3 Pro', "first": (2023, 5), "power": "150"}  # fmt: skip
    src = tmp_path / "BEST-20250101.txt"
    lines = "\t".join(header) + "\r\n" + "\t".join(fx._row(header, v, "")) + "\r\n"
    src.write_text(lines, encoding="utf-8", newline="")  # exact bytes, also on Windows
    e = ingest(str(src), CANTONS, tmp_path / "r", tmp_path / "t", tmp_path / "m.jsonl")
    assert (e.rows_read, e.rows_kept, e.rows_rejected) == (1, 1, 0)


def test_failed_schema_is_logged(tmp_path):
    bad = tmp_path / "BEST-20270101.txt"
    bad.write_text("Kanton\tAnzahl\r\nZH\t5\r\n", encoding="utf-8", newline="")
    with pytest.raises(ValueError):
        ingest(str(bad), CANTONS, tmp_path / "r", tmp_path / "t", tmp_path / "m.jsonl")
    assert json.loads((tmp_path / "m.jsonl").read_text())["status"] == "failed_schema"


def test_focus_cantons_come_from_the_regions_seed():
    from conftest import ROOT

    assert load_focus_cantons(ROOT / "transform" / "seeds" / "regions.csv") == {"ZH", "ZG"}
