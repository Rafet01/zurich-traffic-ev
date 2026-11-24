from pathlib import Path

from databricks_load import build_plan

MANIFEST = [
    {"dataset": "traffic_counts", "status": "loaded", "partition_key": "2026",
     "output_path": "data/landing/traffic_counts/year=2026/aa.parquet", "totals_path": None},
    {"dataset": "vehicle_stock", "status": "loaded", "partition_key": "2026-11-01",
     "output_path": "data/landing/vehicle_stock/stock_date=2026-11-01/bb.parquet",
     "totals_path": "data/landing/vehicle_stock_totals/stock_date=2026-11-01/bb.parquet"},
    {"dataset": "traffic_counts", "status": "skipped_unchanged", "partition_key": None, "output_path": None},
    {"dataset": "vehicle_stock", "status": "failed_schema", "partition_key": None, "output_path": None},
]  # fmt: skip


def test_only_loaded_files_are_uploaded_flat_and_never_overwritten():
    plan = build_plan(MANIFEST, Path("data/manifest.jsonl"), "workspace")
    vol = "/Volumes/workspace/bronze/landing"
    assert plan.uploads == [
        ("data/landing/traffic_counts/year=2026/aa.parquet", f"{vol}/traffic_counts/2026_aa.parquet", False),
        ("data/landing/vehicle_stock/stock_date=2026-11-01/bb.parquet", f"{vol}/vehicle_stock/2026-11-01_bb.parquet",
         False),
        ("data/landing/vehicle_stock_totals/stock_date=2026-11-01/bb.parquet",
         f"{vol}/vehicle_stock_totals/2026-11-01_bb.parquet", False),
        ("data/manifest.jsonl", f"{vol}/manifest/manifest.jsonl", True),
    ]  # fmt: skip


def test_copy_into_each_bronze_table_before_the_manifest_is_replaced():
    statements = build_plan(MANIFEST, Path("m.jsonl"), "workspace").statements
    assert [s.split(" from ")[0] for s in statements[:3]] == [
        "copy into workspace.bronze.traffic_counts_landing",
        "copy into workspace.bronze.vehicle_stock_landing",
        "copy into workspace.bronze.vehicle_stock_totals_landing",
    ]
    assert all("mergeSchema' = 'false'" in s for s in statements[:3])
    assert statements[-1].startswith("create or replace table workspace.bronze.ingest_manifest")
