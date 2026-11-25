"""Building blocks shared by both ingest jobs: hashing while streaming, the manifest, opening sources.

Both sources are large text files (the yearly traffic CSV is ~450 MB, a vehicle stock snapshot ~1.9 GB).
They are never stored: every byte is hashed while it is parsed, and only the rows we keep are written.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

USER_AGENT = "zurich-traffic-ev/0.1 (open data portfolio project)"


class HashingReader(io.RawIOBase):
    """Wraps a binary stream and hashes every byte that passes through."""

    def __init__(self, raw):
        self._raw = raw
        self.sha256 = hashlib.sha256()
        self.bytes_read = 0

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        chunk = self._raw.read(len(buffer))
        if not chunk:
            return 0
        n = len(chunk)
        buffer[:n] = chunk
        self.sha256.update(chunk)
        self.bytes_read += n
        return n


def text_stream(hashing: HashingReader) -> io.TextIOWrapper:
    # newline="" lets the csv module handle \r\n (the ASTRA files use CRLF) itself.
    return io.TextIOWrapper(io.BufferedReader(hashing, buffer_size=1 << 20), encoding="utf-8-sig", newline="")


@dataclass
class RemoteInfo:
    """What the server says about a file before we download it (used to skip unchanged files)."""

    last_modified: str | None = None
    etag: str | None = None
    content_length: int | None = None


def is_remote(uri: str) -> bool:
    return uri.startswith(("http://", "https://"))


def open_source(uri: str):
    """Open a local path or URL as a binary stream. Returns (stream, RemoteInfo)."""
    if is_remote(uri):
        req = urllib.request.Request(uri, headers={"User-Agent": USER_AGENT})
        resp = urllib.request.urlopen(req, timeout=300)
        return resp, _remote_info(resp.headers)
    return open(uri, "rb"), RemoteInfo()


def head(uri: str) -> RemoteInfo:
    req = urllib.request.Request(uri, method="HEAD", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return _remote_info(resp.headers)


def _remote_info(headers) -> RemoteInfo:
    length = headers.get("Content-Length")
    return RemoteInfo(headers.get("Last-Modified"), headers.get("ETag"), int(length) if length else None)


@dataclass
class ManifestEntry:
    dataset: str  # traffic_counts | vehicle_stock
    source_file: str
    source_uri: str
    sha256: str | None
    bytes: int
    layout: str | None  # which known header layout matched
    header_sha256: str | None  # fingerprint of the exact header line, to spot silent drift
    delimiter: str | None
    rows_read: int
    rows_kept: int
    rows_rejected: int  # rows with the wrong number of fields
    partition_key: str | None  # traffic: year; vehicle stock: stock date (YYYY-MM-DD)
    partition_key_source: str | None  # where partition_key came from (data, file name, http header, argument)
    output_path: str | None
    totals_path: str | None
    http_last_modified: str | None
    http_etag: str | None
    ingested_at: str
    status: str  # loaded | skipped_duplicate | skipped_unchanged | failed_schema
    duration_seconds: float | None = None  # wall clock from ingested_at to the manifest write (incl. download)
    header: list[str] = field(default_factory=list)


def now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def read_manifest(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_manifest(path: Path, entry: ManifestEntry) -> None:
    if entry.duration_seconds is None:
        started = datetime.fromisoformat(entry.ingested_at)
        entry.duration_seconds = max(0.0, round((datetime.now(UTC) - started).total_seconds(), 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")


def already_loaded(manifest_path: Path, dataset: str, sha256: str) -> bool:
    return any(
        m["dataset"] == dataset and m["sha256"] == sha256 and m["status"] == "loaded"
        for m in read_manifest(manifest_path)
    )


def unchanged_since_last_load(manifest_path: Path, uri: str, remote: RemoteInfo) -> bool:
    """True if the last successful load of this URL saw the same ETag / Last-Modified / size."""
    loads = [m for m in read_manifest(manifest_path) if m["source_uri"] == uri and m["status"] == "loaded"]
    if not loads or not (remote.etag or remote.last_modified):
        return False
    last = loads[-1]
    same_etag = remote.etag is not None and remote.etag == last.get("http_etag")
    same_date = remote.last_modified is not None and remote.last_modified == last.get("http_last_modified")
    same_size = remote.content_length is None or remote.content_length == last.get("bytes")
    return (same_etag or same_date) and same_size


def header_fingerprint(header: list[str]) -> str:
    return hashlib.sha256("\t".join(header).encode("utf-8")).hexdigest()[:16]


def file_name(uri: str) -> str:
    # URLs and POSIX paths use "/", Windows paths "\\"
    return re.split(r"[/\\]", uri.rstrip("/\\"))[-1]


def detect_delimiter(header_line: str, candidates: str = ",;\t") -> str:
    return max(candidates, key=header_line.count)


def year_from_name(name: str) -> str | None:
    m = re.search(r"_(\d{4})\.csv$", name, flags=re.IGNORECASE)
    return m.group(1) if m else None


class ParquetSink:
    """Writes kept rows (all strings) plus lineage columns in batches to a temporary Parquet file.

    The file hash is only known after the last byte has been read, so `_source_sha256` is filled in
    by `finish()`, which rewrites the file batch by batch to its final location (memory stays flat).
    """

    LINEAGE = ["_source_file", "_source_sha256", "_source_row_number", "_ingested_at"]

    def __init__(self, tmp_path: Path, columns: list[str], source_file: str, ingested_at: str, batch_size=100_000):
        import pyarrow as pa
        import pyarrow.parquet as pq

        self._pa, self._pq = pa, pq
        self.columns = columns
        self.schema = pa.schema(
            [(c, pa.string()) for c in columns]
            + [
                ("_source_file", pa.string()),
                ("_source_sha256", pa.string()),
                ("_source_row_number", pa.int64()),
                ("_ingested_at", pa.string()),
            ]
        )
        self.tmp_path = tmp_path
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        self._writer = pq.ParquetWriter(tmp_path, self.schema, compression="zstd")
        self._batch: dict[str, list] = {c: [] for c in columns + ["_source_row_number"]}
        self._source_file, self._ingested_at, self._batch_size = source_file, ingested_at, batch_size
        self.rows = 0

    def add(self, values: list[str | None], row_number: int) -> None:
        for c, v in zip(self.columns, values, strict=True):
            self._batch[c].append(v)
        self._batch["_source_row_number"].append(row_number)
        self.rows += 1
        if len(self._batch["_source_row_number"]) >= self._batch_size:
            self._flush()

    def _flush(self) -> None:
        n = len(self._batch["_source_row_number"])
        if n == 0:
            return
        cols = {c: self._batch[c] for c in self.columns}
        cols["_source_file"] = [self._source_file] * n
        cols["_source_sha256"] = [None] * n
        cols["_source_row_number"] = self._batch["_source_row_number"]
        cols["_ingested_at"] = [self._ingested_at] * n
        self._writer.write_table(self._pa.table(cols, schema=self.schema))
        for v in self._batch.values():
            v.clear()

    def close(self) -> None:
        self._flush()
        self._writer.close()

    def finish(self, out_path: Path, sha256: str) -> None:
        # Batch by batch: a traffic year keeps all ~1.9M rows, which would take over 1 GB as one Arrow table.
        idx = self.schema.get_field_index("_source_sha256")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with (
            self._pq.ParquetFile(self.tmp_path) as source,  # closed before unlink: Windows cannot delete open files
            self._pq.ParquetWriter(out_path, self.schema, compression="zstd") as writer,
        ):
            for batch in source.iter_batches(batch_size=self._batch_size):
                sha = self._pa.array([sha256] * batch.num_rows, self._pa.string())
                writer.write_table(self._pa.Table.from_batches([batch]).set_column(idx, "_source_sha256", sha))
        self.tmp_path.unlink()

    def discard(self) -> None:
        self.tmp_path.unlink(missing_ok=True)
