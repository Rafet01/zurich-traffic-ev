"""Stream one ASTRA vehicle stock snapshot (all registered vehicles in Switzerland) and land two outputs.

Source: ASTRA open data, https://opendata.astra.admin.ch/ivzod/1000-Fahrzeuge_IVZ/1300-Fahrzeugbestaende/
  1320-Datensaetze_monatlich/best_ogd.txt               current month (new layout since Nov 2026)
  1320-Datensaetze_monatlich/1323-Vorjahrsdaten/BEST-YYYYMMDD.txt   half-yearly history since 2019
Each file is ~1.7-2.1 GB, tab-separated, one row per vehicle, no holder data, PLZ masked to "80..".

One pass over the bytes produces:
  1. vehicle rows (canonical columns, raw strings, lineage) for the focus cantons and vehicle types,
  2. control totals: number of vehicles per canton x vehicle type x fuel for ALL rows of the file.
The totals give the national picture at a fraction of the size, and let dbt reconcile the kept rows.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    HashingReader,
    ManifestEntry,
    ParquetSink,
    RemoteInfo,
    already_loaded,
    append_manifest,
    file_name,
    head,
    header_fingerprint,
    is_remote,
    now_utc,
    open_source,
    text_stream,
    unchanged_since_last_load,
)
from vehicle_layouts import CANONICAL_COLUMNS, resolve  # noqa: E402

DATASET = "vehicle_stock"
PASSENGER_CARS = "001"  # Fahrzeugart_Code of "Personenwagen"
C = {c: i for i, c in enumerate(CANONICAL_COLUMNS)}

# The files can contain quote characters inside values (model names): no CSV quoting at all.
csv.field_size_limit(1 << 20)


def stock_date_from_data(data_as_of: str | None) -> date | None:
    """'01.07.2022' -> 2022-07-01; '31.10.2026' (end of month) -> 2026-11-01. Same moment, one convention."""
    if not data_as_of:
        return None
    d = datetime.strptime(data_as_of.strip(), "%d.%m.%Y").date()
    return d + timedelta(days=1) if (d + timedelta(days=1)).day == 1 else d


def stock_date_from_name(name: str) -> date | None:
    m = re.search(r"(\d{8})\.txt$", name, flags=re.IGNORECASE)
    return datetime.strptime(m.group(1), "%Y%m%d").date() if m else None


def stock_date_from_http(remote: RemoteInfo | None) -> date | None:
    if not remote or not remote.last_modified:
        return None
    return parsedate_to_datetime(remote.last_modified).date().replace(day=1)


def ingest(
    uri: str,
    focus_cantons: set[str],
    landing_dir: Path,
    totals_dir: Path,
    manifest_path: Path,
    keep_vehicle_types: frozenset[str] = frozenset({PASSENGER_CARS}),
    stock_date: date | None = None,
    skip_unchanged: bool = True,
) -> ManifestEntry:
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
        header = text.readline().rstrip("\r\n").split("\t")
        try:
            layout, positions = resolve(header)
        except ValueError:
            text.read()  # drain so the hash still covers the whole file
            entry = _entry(
                source_file,
                uri,
                hashing.sha256.hexdigest(),
                hashing.bytes_read,
                ingested_at,
                "failed_schema",
                header=header,
                remote=remote,
            )
            append_manifest(manifest_path, entry)
            raise

        sink = ParquetSink(tmp_path, CANONICAL_COLUMNS, source_file, ingested_at)
        totals: Counter[tuple[str, str, str]] = Counter()
        rows_read = rejected = 0
        data_as_of = None
        width = len(header)
        for row_number, row in enumerate(csv.reader(text, delimiter="\t", quoting=csv.QUOTE_NONE), start=1):
            rows_read += 1
            if len(row) != width:
                rejected += 1
                continue
            values = [(row[p].strip() or None) if p is not None else None for p in positions]
            canton, vtype, fuel = values[C["canton"]], values[C["vehicle_type_code"]], values[C["fuel_code"]]
            totals[(canton or "", vtype or "", fuel or "")] += 1
            data_as_of = data_as_of or values[C["data_as_of"]]
            if canton in focus_cantons and vtype in keep_vehicle_types:
                sink.add(values, row_number)
        sink.close()

    sha = hashing.sha256.hexdigest()
    resolved, source = _resolve_stock_date(stock_date, data_as_of, source_file, remote)
    common = dict(
        header=header,
        layout=layout,
        remote=remote,
        rows_read=rows_read,
        rows_kept=sink.rows,
        rows_rejected=rejected,
        partition_key=resolved,
        partition_key_source=source,
    )
    if already_loaded(manifest_path, DATASET, sha):
        sink.discard()
        entry = _entry(source_file, uri, sha, hashing.bytes_read, ingested_at, "skipped_duplicate", **common)
        append_manifest(manifest_path, entry)
        return entry

    partition = f"stock_date={resolved or 'unknown'}"
    out_path = landing_dir / partition / f"{sha[:16]}.parquet"
    totals_path = totals_dir / partition / f"{sha[:16]}.parquet"
    sink.finish(out_path, sha)
    _write_totals(totals, totals_path, source_file, sha, ingested_at)
    entry = _entry(
        source_file,
        uri,
        sha,
        hashing.bytes_read,
        ingested_at,
        "loaded",
        output_path=str(out_path),
        totals_path=str(totals_path),
        **common,
    )
    append_manifest(manifest_path, entry)
    return entry


def _resolve_stock_date(override, data_as_of, source_file, remote) -> tuple[str | None, str | None]:
    for value, source in (
        (override, "argument"),
        (stock_date_from_data(data_as_of), "data (Datenstand)"),
        (stock_date_from_name(source_file), "file name"),
        (stock_date_from_http(remote), "http Last-Modified"),
    ):
        if value:
            return value.isoformat(), source
    return None, None


def _write_totals(totals: Counter, path: Path, source_file: str, sha: str, ingested_at: str) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    keys = sorted(totals)
    table = pa.table(
        {
            "canton": [k[0] or None for k in keys],
            "vehicle_type_code": [k[1] or None for k in keys],
            "fuel_code": [k[2] or None for k in keys],
            "vehicle_count": pa.array([totals[k] for k in keys], pa.int64()),
            "_source_file": [source_file] * len(keys),
            "_source_sha256": [sha] * len(keys),
            "_ingested_at": [ingested_at] * len(keys),
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression="zstd")


def _entry(
    source_file,
    uri,
    sha,
    nbytes,
    ingested_at,
    status,
    *,
    header=None,
    layout=None,
    remote=None,
    rows_read=0,
    rows_kept=0,
    rows_rejected=0,
    partition_key=None,
    partition_key_source=None,
    output_path=None,
    totals_path=None,
) -> ManifestEntry:
    return ManifestEntry(
        dataset=DATASET,
        source_file=source_file,
        source_uri=uri,
        sha256=sha,
        bytes=nbytes,
        layout=layout,
        header_sha256=header_fingerprint(header) if header else None,
        delimiter="\t" if header else None,
        rows_read=rows_read,
        rows_kept=rows_kept,
        rows_rejected=rows_rejected,
        partition_key=partition_key,
        partition_key_source=partition_key_source,
        output_path=output_path,
        totals_path=totals_path,
        http_last_modified=remote.last_modified if remote else None,
        http_etag=remote.etag if remote else None,
        ingested_at=ingested_at,
        status=status,
        header=header or [],
    )


def load_focus_cantons(regions_seed: Path) -> set[str]:
    with regions_seed.open(newline="", encoding="utf-8") as f:
        return {r["canton"].strip() for r in csv.DictReader(f) if r["canton"].strip()}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("sources", nargs="+", help="local paths or https URLs of BEST-*.txt / best_ogd.txt files")
    p.add_argument("--regions", type=Path, default=Path("transform/seeds/regions.csv"))
    p.add_argument("--landing-dir", type=Path, default=Path("data/landing/vehicle_stock"))
    p.add_argument("--totals-dir", type=Path, default=Path("data/landing/vehicle_stock_totals"))
    p.add_argument("--manifest", type=Path, default=Path("data/manifest.jsonl"))
    p.add_argument("--stock-date", type=date.fromisoformat, help="override the snapshot date (YYYY-MM-DD)")
    p.add_argument("--force", action="store_true", help="download even if ETag/Last-Modified are unchanged")
    args = p.parse_args(argv)

    cantons = load_focus_cantons(args.regions)
    failures = 0
    for uri in args.sources:
        try:
            e = ingest(
                uri,
                cantons,
                args.landing_dir,
                args.totals_dir,
                args.manifest,
                stock_date=args.stock_date,
                skip_unchanged=not args.force,
            )
            print(
                f"{e.status:18} {e.source_file}  stock_date={e.partition_key} layout={e.layout} "
                f"read={e.rows_read:,} kept={e.rows_kept:,} rejected={e.rows_rejected}"
            )
        except Exception as exc:  # keep going, but report and exit non-zero
            failures += 1
            print(f"FAILED {uri}: {exc}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
