import json

import pytest
from common import file_name

import pipeline


@pytest.mark.parametrize(
    "uri",
    [
        "https://opendata.astra.admin.ch/ivzod/1000-Fahrzeuge_IVZ/1300-Fahrzeugbestaende/1320-Datensaetze_monatlich/1323-Vorjahrsdaten/BEST-20260101.txt",
        "/home/me/data/BEST-20260101.txt",
        r"C:\Users\me\Downloads\BEST-20260101.txt",
        r"D:\astra/BEST-20260101.txt",
    ],
)
def test_file_name_from_urls_and_posix_and_windows_paths(uri):
    assert file_name(uri) == "BEST-20260101.txt"


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "DATA", tmp_path)
    monkeypatch.setattr(pipeline, "MANIFEST", tmp_path / "manifest.jsonl")
    return tmp_path


def test_ingest_commands_land_into_the_data_dir(fixtures, data_dir):
    traffic = sorted(str(p) for p in (fixtures / "traffic").glob("*.csv"))
    stock = sorted(str(p) for p in (fixtures / "vehicle_stock").glob("*.txt"))
    assert pipeline.main(["ingest-traffic", *traffic]) == 0
    assert pipeline.main(["ingest-vehicle-stock", *stock]) == 0

    entries = [json.loads(line) for line in (data_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [e["status"] for e in entries] == ["loaded"] * (len(traffic) + len(stock))
    assert len(list((data_dir / "landing" / "traffic_counts").rglob("*.parquet"))) == len(traffic)
    assert len(list((data_dir / "landing" / "vehicle_stock_totals").rglob("*.parquet"))) == len(stock)
    assert not list(data_dir.rglob(".tmp-*")), "temporary files must be removed"


def test_dry_run_lists_and_writes_nothing(fixtures, data_dir, capsys):
    src = str(next((fixtures / "traffic").glob("*.csv")))
    assert pipeline.main(["ingest-traffic", "--dry-run", src]) == 0
    assert src in capsys.readouterr().out
    assert not (data_dir / "manifest.jsonl").exists()
