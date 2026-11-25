"""One entry point for every step, on Windows (PowerShell), macOS and Linux alike. The Makefile calls it too.

    python pipeline.py demo                    synthetic files in the real layouts -> ingest -> dbt build
    python pipeline.py ingest-traffic          every yearly traffic CSV not loaded yet (+ the current year if changed)
    python pipeline.py ingest-vehicle-stock    every vehicle stock snapshot not loaded yet (~1.9 GB each, streamed)
    python pipeline.py build [--target spark]  dbt seeds, models and data tests
    python pipeline.py dashboard               Streamlit on http://localhost:8501
    python pipeline.py benchmark               time both ingests on large synthetic files
    python pipeline.py findings [--write]      the answers from the gold tables, as Markdown (--write: into README)

The ingest commands also take explicit files or URLs, e.g. `python pipeline.py ingest-vehicle-stock D:\\BEST.txt`,
and `--dry-run` to only list what would be loaded. Paths are resolved from this file, not the working directory.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("DATA_DIR", ROOT / "data"))
MANIFEST = DATA / "manifest.jsonl"
FIXTURES = ROOT / "tests" / "fixtures"
sys.path[:0] = [str(ROOT / "ingest"), str(ROOT / "tests"), str(ROOT / "scripts")]


def ingest_traffic(files: list[str], force: bool = False, dry_run: bool = False) -> int:
    import sources
    import traffic
    from common import read_manifest

    if not files:
        found = sources.traffic_files(json.loads(sources._get(sources.TRAFFIC_PACKAGE_API)))
        files = sources.select_traffic(found, read_manifest(MANIFEST))
    print(f"traffic counts: {len(files)} file(s) to load")
    if dry_run or not files:
        print("\n".join(files))
        return 0
    args = [*files, "--landing-dir", str(DATA / "landing" / "traffic_counts"), "--manifest", str(MANIFEST)]
    return traffic.main(args + (["--force"] if force else []))


def ingest_vehicle_stock(files: list[str], force: bool = False, dry_run: bool = False) -> int:
    import sources
    import vehicle_stock
    from common import read_manifest

    if not files:
        found = sources.vehicle_stock_files(
            sources._get(sources.ASTRA_STOCK_DIR).decode(), sources._get(sources.ASTRA_HISTORY_DIR).decode()
        )
        files = sources.select_vehicle_stock(found, read_manifest(MANIFEST))
    print(f"vehicle stock: {len(files)} file(s) to load")
    if dry_run or not files:
        print("\n".join(files))
        return 0
    args = [
        *files,
        "--regions", str(ROOT / "transform" / "seeds" / "regions.csv"),
        "--landing-dir", str(DATA / "landing" / "vehicle_stock"),
        "--totals-dir", str(DATA / "landing" / "vehicle_stock_totals"),
        "--manifest", str(MANIFEST),
    ]  # fmt: skip
    return vehicle_stock.main(args + (["--force"] if force else []))


def _executable(name: str) -> str:
    """A console script of the active environment (dbt, streamlit), also when the venv is not activated."""
    here = Path(sys.executable).parent / (f"{name}.exe" if os.name == "nt" else name)
    found = str(here) if here.exists() else shutil.which(name)
    if not found:
        sys.exit(f"{name} not found: pip install -r requirements-dev.txt (or requirements-dashboard.txt)")
    return found


def build(target: str | None = None) -> int:
    cmd = [_executable("dbt"), "build", "--profiles-dir", "."]
    env = {**os.environ, "DATA_DIR": str(DATA)}
    if target:
        cmd += ["--target", target]
    return subprocess.run(cmd, cwd=ROOT / "transform", env=env).returncode


def fixtures() -> list[Path]:
    import make_fixtures

    return make_fixtures.write_all(FIXTURES)


def demo() -> int:
    files = fixtures()
    traffic_files = [str(p) for p in files if p.suffix == ".csv"]
    stock_files = [str(p) for p in files if p.suffix == ".txt"]
    # Rerunning is fine: files already loaded are skipped by their hash.
    rc = max(ingest_traffic(traffic_files), ingest_vehicle_stock(stock_files))
    return rc or build()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("ingest-traffic", "ingest-vehicle-stock"):
        s = sub.add_parser(name)
        s.add_argument("files", nargs="*", help="local paths or URLs; default: whatever is new at the source")
        s.add_argument("--force", action="store_true", help="download even if ETag/Last-Modified are unchanged")
        s.add_argument("--dry-run", action="store_true", help="only list the files that would be loaded")
    sub.add_parser("build").add_argument("--target", choices=["dev", "spark", "databricks"])
    sub.add_parser("fixtures")
    sub.add_parser("demo")
    sub.add_parser("dashboard")
    sub.add_parser("benchmark").add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "zte-bench")
    sub.add_parser("findings").add_argument("--write", action="store_true", help="replace the block in README.md")
    args = p.parse_args(argv)

    if args.command == "ingest-traffic":
        return ingest_traffic(args.files, args.force, args.dry_run)
    if args.command == "ingest-vehicle-stock":
        return ingest_vehicle_stock(args.files, args.force, args.dry_run)
    if args.command == "build":
        return build(args.target)
    if args.command == "fixtures":
        print("\n".join(str(f) for f in fixtures()))
        return 0
    if args.command == "demo":
        return demo()
    if args.command == "dashboard":
        return subprocess.run([sys.executable, "-m", "streamlit", "run", str(ROOT / "dashboard" / "app.py")]).returncode
    if args.command == "findings":
        import findings

        return findings.main(
            ["--warehouse", str(DATA / "warehouse.duckdb"), "--manifest", str(MANIFEST)]
            + (["--write"] if args.write else [])
        )
    if args.command == "benchmark":
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "benchmark_ingest.py"), "--out", str(args.out)]
        ).returncode
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
