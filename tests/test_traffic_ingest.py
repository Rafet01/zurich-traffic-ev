import csv
import hashlib
import json

import pyarrow.parquet as pq
import pytest
from traffic import EXPECTED_COLUMNS, ingest


def test_ingest_keeps_every_row_with_lineage(fixtures, tmp_path):
    src = fixtures / "traffic" / "sid_dav_verkehrszaehlung_miv_OD2031_2026.csv"
    e = ingest(str(src), tmp_path / "landing", tmp_path / "manifest.jsonl")

    assert e.status == "loaded"
    assert e.sha256 == hashlib.sha256(src.read_bytes()).hexdigest()
    assert e.partition_key == "2026" and e.partition_key_source == "file name"
    assert e.rows_read == e.rows_kept and e.rows_rejected == 0
    logged = json.loads((tmp_path / "manifest.jsonl").read_text().splitlines()[-1])
    assert logged["duration_seconds"] is not None and logged["duration_seconds"] >= 0

    landed = pq.read_table(e.output_path).to_pylist()
    with src.open(newline="", encoding="utf-8") as f:
        source_rows = list(csv.DictReader(f))
    assert len(landed) == len(source_rows)
    for row in landed[::97]:
        original = source_rows[row["_source_row_number"] - 1]
        assert all((original[c] or None) == row[c] for c in EXPECTED_COLUMNS)
        assert row["_source_sha256"] == e.sha256


def test_autumn_dst_hour_is_delivered_twice_in_order(fixtures, tmp_path):
    src = fixtures / "traffic" / "sid_dav_verkehrszaehlung_miv_OD2031_2025.csv"
    e = ingest(str(src), tmp_path / "landing", tmp_path / "manifest.jsonl")
    rows = [
        r
        for r in pq.read_table(e.output_path).to_pylist()
        if r["MSID"] == "Z001M001" and r["MessungDatZeit"] == "2025-10-26T02:00:00"
    ]
    assert len(rows) == 2
    assert rows[0]["_source_row_number"] < rows[1]["_source_row_number"]


def test_missing_values_stay_empty(fixtures, tmp_path):
    src = fixtures / "traffic" / "sid_dav_verkehrszaehlung_miv_OD2031_2026.csv"
    e = ingest(str(src), tmp_path / "landing", tmp_path / "manifest.jsonl")
    missing = [r for r in pq.read_table(e.output_path).to_pylist() if r["AnzFahrzeugeStatus"] == "Fehlend"]
    assert missing and all(r["AnzFahrzeuge"] is None for r in missing)


def test_reingest_same_bytes_is_noop(fixtures, tmp_path):
    src = fixtures / "traffic" / "sid_dav_verkehrszaehlung_miv_OD2031_2025.csv"
    manifest = tmp_path / "manifest.jsonl"
    first = ingest(str(src), tmp_path / "landing", manifest)
    second = ingest(str(src), tmp_path / "landing", manifest)
    assert (first.status, second.status) == ("loaded", "skipped_duplicate")
    assert len(list((tmp_path / "landing").rglob("*.parquet"))) == 1


def test_missing_column_is_rejected_and_logged(tmp_path):
    bad = tmp_path / "sid_dav_verkehrszaehlung_miv_OD2031_2027.csv"
    bad.write_text("MSID,MessungDatZeit,AnzFahrzeuge\nZ001M001,2027-01-01T00:00:00,5\n", encoding="utf-8", newline="")
    with pytest.raises(ValueError, match="missing expected columns"):
        ingest(str(bad), tmp_path / "landing", tmp_path / "manifest.jsonl")
    entry = json.loads((tmp_path / "manifest.jsonl").read_text())
    assert entry["status"] == "failed_schema"
    assert entry["sha256"] == hashlib.sha256(bad.read_bytes()).hexdigest()  # hash covers the whole file
