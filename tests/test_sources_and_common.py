import json
from datetime import date

from common import ManifestEntry, RemoteInfo, append_manifest, unchanged_since_last_load
from make_holidays import easter_sunday, zurich_holidays
from sources import select_traffic, select_vehicle_stock, traffic_files, vehicle_stock_files

PACKAGE = {
    "result": {
        "resources": [
            {"url": "https://data.stadt-zuerich.ch/dataset/x/download/sid_dav_verkehrszaehlung_miv_OD2031_2026.csv"},
            {"url": "https://data.stadt-zuerich.ch/dataset/x/download/sid_dav_verkehrszaehlung_miv_OD2031_2012.csv"},
            {"url": "https://data.stadt-zuerich.ch/dataset/x/download/sid_dav_verkehrszaehlung_miv_od2031_alle_jahre.parquet"},
            {"url": "https://data.stadt-zuerich.ch/dataset/x/download/Zaehlstellen_Detail.zip"},
        ]
    }
}  # fmt: skip
CURRENT_HTML = (
    '<a href="?C=N;O=D">Name</a><a href="1323-Vorjahrsdaten/">x</a><a href="BEST.txt">x</a><a href="best_ogd.txt">x</a>'
)
HISTORY_HTML = '<a href="BEST-20260101.txt">a</a><a href="BEST-20190701.txt">b</a><a href="BEST_ANH-20260101.txt">c</a>'


def test_traffic_files_only_yearly_csvs_sorted():
    files = traffic_files(PACKAGE)
    assert [(n[-8:], y) for n, _, y in files] == [("2012.csv", 2012), ("2026.csv", 2026)]


def test_select_traffic_reloads_current_year_only():
    files = traffic_files(PACKAGE)
    manifest = [{"dataset": "traffic_counts", "status": "loaded", "source_file": n} for n, _, _ in files]
    assert [u[-8:] for u in select_traffic(files, manifest, today=date(2026, 11, 24))] == ["2026.csv"]
    assert len(select_traffic(files, [], today=date(2026, 11, 24))) == 2


def test_vehicle_stock_files_history_then_current():
    files = vehicle_stock_files(CURRENT_HTML, HISTORY_HTML)
    assert [n for n, _ in files] == ["BEST-20190701.txt", "BEST-20260101.txt", "best_ogd.txt"]
    manifest = [{"dataset": "vehicle_stock", "status": "loaded", "source_file": "BEST-20190701.txt"}]
    assert [u.rsplit("/", 1)[1] for u in select_vehicle_stock(files, manifest)] == ["BEST-20260101.txt", "best_ogd.txt"]


def _loaded(uri, etag, last_modified, nbytes):
    return ManifestEntry("traffic_counts", "f.csv", uri, "aa", nbytes, None, None, ",", 1, 1, 0, "2026", "file name",
                         "p", None, last_modified, etag, "2026-11-24T06:00:00+00:00", "loaded")  # fmt: skip


def test_unchanged_remote_file_is_detected(tmp_path):
    m = tmp_path / "manifest.jsonl"
    append_manifest(m, _loaded("https://x/f.csv", '"abc"', "Mon, 23 Nov 2026 11:14:58 GMT", 100))
    assert unchanged_since_last_load(m, "https://x/f.csv", RemoteInfo(None, '"abc"', 100))
    assert not unchanged_since_last_load(m, "https://x/f.csv", RemoteInfo(None, '"def"', 100))
    assert not unchanged_since_last_load(m, "https://x/f.csv", RemoteInfo(None, '"abc"', 101))
    assert not unchanged_since_last_load(m, "https://x/other.csv", RemoteInfo(None, '"abc"', 100))
    assert json.loads(m.read_text())["http_etag"] == '"abc"'


def test_holidays():
    assert easter_sunday(2026) == date(2026, 4, 5) and easter_sunday(2025) == date(2025, 4, 20)
    names = dict(zurich_holidays(2026))
    assert names[date(2026, 4, 3)] == "Karfreitag" and names[date(2026, 5, 14)] == "Auffahrt"
    assert len(names) == 10
