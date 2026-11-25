"""Check the live portals without downloading the big files: is every file still listed where the ingest looks
for it, and does its header still match what the ingest expects? Reads only the first 64 KB of each file.

    python scripts/check_sources.py        # exit 1 on any problem; Markdown summary on GitHub Actions

Runs weekly in GitHub Actions (.github/workflows/sources.yml), so a renamed column or a moved directory shows up
before the next real ingest fails on it.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))

from common import USER_AGENT, detect_delimiter, header_fingerprint  # noqa: E402
from sources import (  # noqa: E402
    ASTRA_HISTORY_DIR,
    ASTRA_STOCK_DIR,
    TRAFFIC_PACKAGE_API,
    _get,
    traffic_files,
    vehicle_stock_files,
)
from traffic import EXPECTED_COLUMNS  # noqa: E402
from vehicle_layouts import resolve  # noqa: E402

PROBE_BYTES = 65536


def probe(url: str) -> tuple[str, int | None]:
    """First line of the file and its total size (from Content-Range or Content-Length)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Range": f"bytes=0-{PROBE_BYTES - 1}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        chunk = resp.read(PROBE_BYTES)  # if the server ignores Range, stop reading here anyway
        size = re.search(r"/(\d+)$", resp.headers.get("Content-Range") or "")
        total = int(size.group(1)) if size else int(resp.headers.get("Content-Length") or 0) or None
    return chunk.decode("utf-8-sig", errors="replace").split("\n", 1)[0].rstrip("\r"), total


def check_traffic_header(line: str) -> str | None:
    header = next(csv.reader([line], delimiter=detect_delimiter(line)))
    missing = [c for c in EXPECTED_COLUMNS if c not in header]
    return f"missing columns {missing}" if missing else None


def check_stock_header(line: str) -> tuple[str | None, str | None]:
    header = line.split("\t")
    try:
        layout, _ = resolve(header)
        return layout, None
    except ValueError as exc:
        return None, str(exc)


def main() -> int:
    rows: list[tuple[str, str, str, str]] = []  # (file, size, result, detail)
    problems: list[str] = []

    traffic = traffic_files(json.loads(_get(TRAFFIC_PACKAGE_API)))
    years = [y for _, _, y in traffic]
    if not traffic or date.today().year not in years:
        problems.append(f"traffic: current year missing from the package (years found: {years})")
    for name, url, _year in traffic:
        try:
            line, size = probe(url)
            error = check_traffic_header(line)
        except Exception as exc:  # report every file, then fail
            size, error = None, f"{type(exc).__name__}: {exc}"
        rows.append((name, _mb(size), "ok" if not error else "FAIL", error or "21 expected columns"))
        if error:
            problems.append(f"{name}: {error}")

    stock = vehicle_stock_files(_get(ASTRA_STOCK_DIR).decode(), _get(ASTRA_HISTORY_DIR).decode())
    names = [n for n, _ in stock]
    if "best_ogd.txt" not in names or len(names) < 10:
        problems.append(f"vehicle stock: expected best_ogd.txt and >= 10 history files, found {names}")
    for name, url in stock:
        try:
            line, size = probe(url)
            layout, error = check_stock_header(line)
            header = line.split("\t")
            detail = error or f"layout {layout}, {len(header)} columns, header {header_fingerprint(header)}"
        except Exception as exc:
            size, error = None, f"{type(exc).__name__}: {exc}"
            detail = error
        rows.append((name, _mb(size), "ok" if not error else "FAIL", detail))
        if error:
            problems.append(f"{name}: {error}")

    report = ["| File | Size | Check | Detail |", "|---|---|---|---|"] + [f"| {' | '.join(r)} |" for r in rows]
    report += ["", f"{len(rows)} files checked, {len(problems)} problem(s)."] + [f"- {p}" for p in problems]
    print("\n".join(report))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("## Live sources\n\n" + "\n".join(report) + "\n")
    return 1 if problems else 0


def _mb(size: int | None) -> str:
    return f"{size / 1e6:,.0f} MB" if size else "?"


if __name__ == "__main__":
    raise SystemExit(main())
