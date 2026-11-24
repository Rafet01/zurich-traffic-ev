"""Stream one yearly traffic-count CSV of the City of Zurich and land it as Parquet.

Source: "Daten der Verkehrszählung zum motorisierten Individualverkehr (Stundenwerte)", one CSV per year
(sid_dav_verkehrszaehlung_miv_OD2031_<year>.csv, ~450 MB). One row = one measuring point, one hour.
The file of the current year is regenerated every morning, so the same URL returns new bytes daily.

One pass over the bytes: SHA-256 of the exact file, CSV parse, column check, lineage per row.
All values are kept as strings; typing happens in dbt.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    HashingReader,
    ManifestEntry,
    ParquetSink,
    already_loaded,
    append_manifest,
    detect_delimiter,
    file_name,
    head,
    header_fingerprint,
    is_remote,
    now_utc,
    open_source,
    text_stream,
    unchanged_since_last_load,
    year_from_name,
)

DATASET = "traffic_counts"

# Attributes documented on data.stadt-zuerich.ch (dataset sid_dav_verkehrszaehlung_miv_od2031), checked 2026-11-24.
EXPECTED_COLUMNS = [
    "MSID",  # measuring point (Messstelle), e.g. Z001M001
    "MSName",
    "ZSID",  # counting site (Zählstelle), groups one or more measuring points
    "ZSName",
    "Achse",  # street
    "HNr",
    "Hoehe",
    "EKoord",  # LV95 east
    "NKoord",  # LV95 north
    "Richtung",  # direction: einwärts / auswärts / a named place
    "Knummer",  # traffic light installation
    "Kname",
    "AnzDetektoren",
    "D1ID",
    "D2ID",
    "D3ID",
    "D4ID",
    "MessungDatZeit",  # start of the hour, local time, ISO 8601 without offset
    "LieferDat",  # delivery date of the whole file
    "AnzFahrzeuge",  # vehicles in that hour; empty when AnzFahrzeugeStatus = Fehlend
    "AnzFahrzeugeStatus",  # Gemessen | Imputiert | Fehlend
]

TS_IDX = EXPECTED_COLUMNS.index("MessungDatZeit")


def ingest(uri: str, landing_dir: Path, manifest_path: Path, skip_unchanged: bool = True) -> ManifestEntry:
    source_file = file_name(uri)
    ingested_at = now_utc()

    if skip_unchanged and is_remote(uri):
        remote = head(uri)
        if unchanged_since_last_load(manifest_path, uri, remote):
            entry = _entry(source_file, uri, None, 0, ingested_at, "skipped_unchanged", remote=remote)
            append_manifest(manifest_path, entry)
            return entry

    tmp_path = landing_dir / f".tmp-{source_file}.parquet"
    stream, remote = open_source(uri)
    with stream as raw:
        hashing = HashingReader(raw)
        text = text_stream(hashing)
        header_line = text.readline()
        delimiter = detect_delimiter(header_line)
        header = next(csv.reader([header_line], delimiter=delimiter))
        missing = [c for c in EXPECTED_COLUMNS if c not in header]
        if missing:
            text.read()  # drain so the hash still covers the whole file
            entry = _entry(
                source_file,
                uri,
                hashing.sha256.hexdigest(),
                hashing.bytes_read,
                ingested_at,
                "failed_schema",
                header=header,
                delimiter=delimiter,
                remote=remote,
            )
            append_manifest(manifest_path, entry)
            raise ValueError(f"{source_file}: missing expected columns {missing}")

        idx = [header.index(c) for c in EXPECTED_COLUMNS]
        sink = ParquetSink(tmp_path, EXPECTED_COLUMNS, source_file, ingested_at)
        rows_read = rejected = 0
        first_ts = None
        # _source_row_number = 1-based data row number in the source file (header excluded).
        # Row order matters: on the autumn DST night the 02:00 hour appears twice, summer time first.
        for row_number, row in enumerate(csv.reader(text, delimiter=delimiter), start=1):
            rows_read += 1
            if len(row) != len(header):
                rejected += 1
                continue
            values = [row[i] if row[i] != "" else None for i in idx]
            first_ts = first_ts or values[TS_IDX]
            sink.add(values, row_number)
        sink.close()

    sha = hashing.sha256.hexdigest()
    year = year_from_name(source_file) or (first_ts[:4] if first_ts else None)
    common = dict(
        header=header,
        delimiter=delimiter,
        remote=remote,
        rows_read=rows_read,
        rows_kept=sink.rows,
        rows_rejected=rejected,
        partition_key=year,
        partition_key_source="file name" if year_from_name(source_file) else "data",
    )
    if already_loaded(manifest_path, DATASET, sha):
        sink.discard()
        entry = _entry(source_file, uri, sha, hashing.bytes_read, ingested_at, "skipped_duplicate", **common)
        append_manifest(manifest_path, entry)
        return entry

    out_path = landing_dir / f"year={year or 'unknown'}" / f"{sha[:16]}.parquet"
    sink.finish(out_path, sha)
    entry = _entry(
        source_file, uri, sha, hashing.bytes_read, ingested_at, "loaded", output_path=str(out_path), **common
    )
    append_manifest(manifest_path, entry)
    return entry


def _entry(
    source_file,
    uri,
    sha,
    nbytes,
    ingested_at,
    status,
    *,
    header=None,
    delimiter=None,
    remote=None,
    rows_read=0,
    rows_kept=0,
    rows_rejected=0,
    partition_key=None,
    partition_key_source=None,
    output_path=None,
) -> ManifestEntry:
    return ManifestEntry(
        dataset=DATASET,
        source_file=source_file,
        source_uri=uri,
        sha256=sha,
        bytes=nbytes,
        layout="od2031" if header else None,
        header_sha256=header_fingerprint(header) if header else None,
        delimiter=delimiter,
        rows_read=rows_read,
        rows_kept=rows_kept,
        rows_rejected=rows_rejected,
        partition_key=partition_key,
        partition_key_source=partition_key_source,
        output_path=output_path,
        totals_path=None,
        http_last_modified=remote.last_modified if remote else None,
        http_etag=remote.etag if remote else None,
        ingested_at=ingested_at,
        status=status,
        header=header or [],
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("sources", nargs="+", help="local paths or https URLs of yearly *_OD2031_<year>.csv files")
    p.add_argument("--landing-dir", type=Path, default=Path("data/landing/traffic_counts"))
    p.add_argument("--manifest", type=Path, default=Path("data/manifest.jsonl"))
    p.add_argument("--force", action="store_true", help="download even if ETag/Last-Modified are unchanged")
    args = p.parse_args(argv)

    failures = 0
    for uri in args.sources:
        try:
            e = ingest(uri, args.landing_dir, args.manifest, skip_unchanged=not args.force)
            print(
                f"{e.status:18} {e.source_file}  read={e.rows_read:,} kept={e.rows_kept:,} rejected={e.rows_rejected}"
            )
        except Exception as exc:  # keep going, but report and exit non-zero
            failures += 1
            print(f"FAILED {uri}: {exc}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
