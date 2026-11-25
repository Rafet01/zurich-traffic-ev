"""Load landed Parquet files and the ingest manifest into Databricks (Unity Catalog, bronze layer).

Idempotent by construction:
  * a Parquet file is only uploaded to the volume if it is not there yet (file names contain the
    source sha256, so a regenerated traffic year or a new snapshot is a new file),
  * COPY INTO skips files it has already loaded into the Delta table,
  * the manifest table is rebuilt from the uploaded manifest.jsonl in one atomic CREATE OR REPLACE
    (Delta), so dbt never sees a half-written manifest.

Connection: the same environment variables as the dbt profile
(DATABRICKS_HOST, DATABRICKS_HTTP_PATH, DATABRICKS_TOKEN, DATABRICKS_CATALOG).
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path

MANIFEST_COLUMNS = [
    "dataset",
    "source_file",
    "source_uri",
    "sha256",
    "bytes",
    "layout",
    "header_sha256",
    "delimiter",
    "rows_read",
    "rows_kept",
    "rows_rejected",
    "partition_key",
    "partition_key_source",
    "output_path",
    "totals_path",
    "http_last_modified",
    "http_etag",
    "ingested_at",
    "status",
    "duration_seconds",
]

# (manifest field with the local path, folder in the volume, bronze table)
TARGETS = {
    "traffic_counts": [("output_path", "traffic_counts", "traffic_counts_landing")],
    "vehicle_stock": [
        ("output_path", "vehicle_stock", "vehicle_stock_landing"),
        ("totals_path", "vehicle_stock_totals", "vehicle_stock_totals_landing"),
    ],
}


@dataclass(frozen=True)
class Plan:
    uploads: list[tuple[str, str, bool]]  # (local path, volume path, overwrite)
    statements: list[str]


def load_manifest(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def build_plan(manifest: list[dict], manifest_path: Path, catalog: str) -> Plan:
    """Everything the load does, as data. Pure function, unit-testable without Databricks."""
    volume = f"/Volumes/{catalog}/bronze/landing"
    uploads: list[tuple[str, str, bool]] = []
    for m in manifest:
        if m["status"] != "loaded":
            continue
        for field, folder, _table in TARGETS[m["dataset"]]:
            if m.get(field):
                local = Path(m[field])
                # flat layout in the volume: COPY INTO would otherwise infer a partition column from year=...
                uploads.append((str(local), f"{volume}/{folder}/{m['partition_key']}_{local.name}", False))
    uploads.append((str(manifest_path), f"{volume}/manifest/manifest.jsonl", True))

    statements = [
        f"copy into {catalog}.bronze.{table} "
        f"from '{volume}/{folder}/' "
        "fileformat = parquet pattern = '*.parquet' "
        "format_options ('mergeSchema' = 'false') copy_options ('mergeSchema' = 'false')"
        for targets in TARGETS.values()
        for _field, folder, table in targets
    ]
    statements.append(
        f"create or replace table {catalog}.bronze.ingest_manifest as "
        f"select {', '.join(MANIFEST_COLUMNS)} from read_files('{volume}/manifest/manifest.jsonl', format => 'json')"
    )
    return Plan(uploads, statements)


def run(plan: Plan) -> None:
    from databricks import sql
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.errors import NotFound

    w = WorkspaceClient()  # reads DATABRICKS_HOST / DATABRICKS_TOKEN (or a configured profile)
    for local, remote, overwrite in plan.uploads:
        if not overwrite:
            try:
                w.files.get_metadata(remote)
                print(f"exists  {remote}")
                continue
            except NotFound:
                pass
        with open(local, "rb") as f:
            w.files.upload(remote, f, overwrite=overwrite)
        print(f"upload  {remote}")

    with (
        sql.connect(
            server_hostname=os.environ["DATABRICKS_HOST"].removeprefix("https://"),
            http_path=os.environ["DATABRICKS_HTTP_PATH"],
            access_token=os.environ["DATABRICKS_TOKEN"],
        ) as conn,
        conn.cursor() as cur,
    ):
        for statement in plan.statements:
            cur.execute(statement)
            if statement.startswith("copy into"):
                print(statement.split(" from ")[0] + ":", cur.fetchall())


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--manifest", type=Path, default=Path("data/manifest.jsonl"))
    p.add_argument("--catalog", default=os.environ.get("DATABRICKS_CATALOG", "workspace"))
    p.add_argument("--dry-run", action="store_true", help="print the plan instead of running it")
    args = p.parse_args()
    plan = build_plan(load_manifest(args.manifest), args.manifest, args.catalog)
    if args.dry_run:
        for local, remote, overwrite in plan.uploads:
            print(f"upload {local} -> {remote}{' (overwrite)' if overwrite else ''}")
        for s in plan.statements:
            print(s)
        return
    run(plan)


if __name__ == "__main__":
    main()
