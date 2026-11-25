"""How fast is the streaming ingest? Generates large synthetic files in the real layouts and times both ingests.

    python pipeline.py benchmark                                      # defaults: one traffic year, 2M vehicles
    python scripts/benchmark_ingest.py --out /tmp/bench --vehicle-rows 6000000

Traffic: 217 measuring points x 365 days x 24 hours (about one real yearly file). Vehicle stock: the current
BEST layout, with the empty columns of the fixture rows filled so a row is about as wide as a real one.
Prints input size, rows, seconds, MB/s and rows/s per file, the size of what was landed and the peak
memory of each ingest (each runs in its own process). Nothing is downloaded; the real-run timings land in the manifest
(`duration_seconds`) and in gold.mart_data_quality.
"""

from __future__ import annotations

import argparse
import random
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "ingest"), str(ROOT / "tests")]

import make_fixtures as fx  # noqa: E402
import traffic  # noqa: E402
import vehicle_stock  # noqa: E402

# Filler for columns the fixture leaves empty (colour, body, dimensions, weights, approvals, ...),
# so a synthetic row is about as wide as a real one (assumed ~300 bytes; the real width is in the
# manifest after the first real run: bytes / rows_read).
FILLER = ["schwarz", "Limousine", "4", "5", "1998", "1560", "2100", "4720", "1840", "1450", "ABC123",
          "1K1F1234", "2", "0", "WLTP", "Euro 6d", "1"]  # fmt: skip


def traffic_file(path: Path, points: int, days: int) -> Path:
    templates = fx.MEASURING_POINTS
    fx.MEASURING_POINTS = [
        (f"Z{i:03d}M00{1 + i % 2}", f"Z{i:03d}", *t[2:9], ())
        for i, t in ((i, templates[i % len(templates)]) for i in range(points))
    ]
    try:
        return fx.write_traffic(path, 2025, date(2025, 1, 1), days, date(2026, 1, 15))
    finally:
        fx.MEASURING_POINTS = templates


def vehicle_file(path: Path, rows: int) -> Path:
    header = list(fx.BEST_CURRENT)
    rnd = random.Random(42)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write("\t".join(header) + "\r\n")
        for _ in range(rows):
            row = fx._row(header, fx._vehicle(rnd, 2026), "01.01.2026")
            row = [v or FILLER[i % len(FILLER)] for i, v in enumerate(row)]
            f.write("\t".join(row) + "\r\n")
    return path


def _peak_memory_mb() -> float | None:
    try:
        import resource  # Unix only
    except ImportError:
        return None
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / 1024 / 1024 if sys.platform == "darwin" else rss / 1024  # bytes on macOS, KiB on Linux


def run(label: str, src: Path, fn) -> dict:
    t0 = time.perf_counter()
    entry = fn()
    seconds = time.perf_counter() - t0
    peak = _peak_memory_mb()
    mb = src.stat().st_size / 1e6
    landed = sum(p.stat().st_size for p in Path(entry.output_path).parent.glob("*.parquet")) / 1e6
    r = dict(file=label, mb=mb, rows=entry.rows_read, kept=entry.rows_kept, seconds=seconds, landed_mb=landed)
    print(
        f"{label:14} {mb:8.0f} MB  {entry.rows_read:>10,} rows  {seconds:6.1f} s  "
        f"{mb / seconds:6.1f} MB/s  {entry.rows_read / seconds:>9,.0f} rows/s  "
        f"kept {entry.rows_kept:,} -> {landed:.0f} MB Parquet  peak memory "
        + (f"{peak:.0f} MB" if peak is not None else "n/a")
    )
    return r


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out", type=Path, required=True, help="scratch directory (several hundred MB)")
    p.add_argument("--traffic-points", type=int, default=217)
    p.add_argument("--traffic-days", type=int, default=365)
    p.add_argument("--vehicle-rows", type=int, default=2_000_000)
    p.add_argument("--only", choices=["traffic", "vehicle-stock"], help=argparse.SUPPRESS)
    args = p.parse_args()

    out = args.out
    tsrc = out / "src" / "sid_dav_verkehrszaehlung_miv_OD2031_2025.csv"
    vsrc = out / "src" / "BEST-20260101.txt"
    manifest = out / f"manifest-{args.only}.jsonl"
    manifest.unlink(missing_ok=True)  # a rerun on the same bytes would otherwise be skipped as a duplicate
    if args.only == "traffic":
        run("traffic", tsrc, lambda: traffic.ingest(str(tsrc), out / "landing" / "traffic_counts", manifest))
        return 0
    if args.only == "vehicle-stock":
        landing = out / "landing"
        run(
            "vehicle stock",
            vsrc,
            lambda: vehicle_stock.ingest(
                str(vsrc), {"ZH", "ZG"}, landing / "vehicle_stock", landing / "vehicle_stock_totals", manifest
            ),
        )
        return 0

    t0 = time.perf_counter()
    traffic_file(tsrc, args.traffic_points, args.traffic_days)
    vehicle_file(vsrc, args.vehicle_rows)
    print(f"generated test files in {time.perf_counter() - t0:.0f} s\n")
    # Each ingest in a fresh process, so the peak memory printed belongs to that ingest alone.
    for only in ("traffic", "vehicle-stock"):
        subprocess.run([sys.executable, __file__, "--out", str(out), "--only", only], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
