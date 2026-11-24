"""Three DAGs, connected by Airflow assets instead of fixed times:

  traffic_counts_daily     07:30 every day   City of Zurich publishes yesterday's counts by 07:00
  vehicle_stock_monthly    09:00 on the 2nd  ASTRA publishes the new monthly snapshot on the 1st
  warehouse_build          whenever one of the two above actually landed new data
                           -> (Databricks load) -> dbt build (models + tests)

The ingest DAGs only emit their asset when a file was really loaded; a day on which the
source did not change (same ETag / Last-Modified, or same bytes) does not rebuild the warehouse.
Manual runs can pass {"sources": [...]} to (re)load specific files, e.g. older years or snapshots.
"""

from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import Asset, Param, dag, get_current_context, task

try:  # Airflow >= 3.1 task SDK
    from airflow.sdk.exceptions import AirflowSkipException
except ImportError:  # pragma: no cover
    from airflow.exceptions import AirflowSkipException

PROJECT_DIR = Path(os.environ.get("PROJECT_DIR", Path(__file__).resolve().parents[2]))
DATA_DIR = PROJECT_DIR / "data"
DBT_BIN = os.environ.get("DBT_BIN", "dbt")
DBT_TARGET = os.environ.get("DBT_TARGET", "dev")
LOADER_PYTHON = os.environ.get("LOADER_PYTHON", sys.executable)
MANIFEST = DATA_DIR / "manifest.jsonl"

# The project's own modules live next to the DAGs, not in site-packages.
sys.path.insert(0, str(PROJECT_DIR / "ingest"))

TRAFFIC_LANDED = Asset(name="traffic_counts_landing", uri=f"file://{DATA_DIR}/landing/traffic_counts")
STOCK_LANDED = Asset(name="vehicle_stock_landing", uri=f"file://{DATA_DIR}/landing/vehicle_stock")

DEFAULT_ARGS = {"retries": 3, "retry_delay": timedelta(minutes=5), "retry_exponential_backoff": True}
TZ = "Europe/Zurich"


def _sources_param(default_cap: int):
    return {
        "sources": Param([], type="array", description="Explicit file paths/URLs. Empty = whatever is new."),
        "max_files": Param(default_cap, type="integer", minimum=1, description="Safety cap per run."),
    }


@task(outlets=[TRAFFIC_LANDED])
def announce_traffic(results: list[dict]) -> int:
    return _announce(results)


@task(outlets=[STOCK_LANDED])
def announce_stock(results: list[dict]) -> int:
    return _announce(results)


def _announce(results: list[dict]) -> int:
    loaded = [r for r in results if r["status"] == "loaded"]
    for r in results:
        print(f"{r['status']:18} {r['source_file']} partition={r['partition_key']} kept={r['rows_kept']}")
    if not loaded:
        # skipped -> no asset event -> no warehouse rebuild for unchanged sources
        raise AirflowSkipException("no new data landed")
    return len(loaded)


@dag(
    dag_id="traffic_counts_daily",
    schedule="30 7 * * *",
    start_date=pendulum.datetime(2026, 11, 1, tz=TZ),
    catchup=False,  # the yearly file always contains the whole year; nothing to catch up per day
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    params=_sources_param(default_cap=3),
    tags=["traffic", "ingest"],
    doc_md=__doc__,
)
def traffic_counts_daily():
    @task
    def find_files() -> list[str]:
        import json

        from common import read_manifest
        from sources import TRAFFIC_PACKAGE_API, _get, select_traffic, traffic_files

        params = get_current_context()["params"]
        if params["sources"]:
            return list(params["sources"])
        files = traffic_files(json.loads(_get(TRAFFIC_PACKAGE_API)))
        return select_traffic(files, read_manifest(MANIFEST))[-params["max_files"] :]

    # One file at a time: the manifest is a single append-only file, so parallel
    # writers could race on the duplicate check. (Parallelism = move it to a table.)
    @task(max_active_tis_per_dag=1)
    def ingest_file(source: str) -> dict:
        from dataclasses import asdict

        from traffic import ingest

        entry = ingest(source, DATA_DIR / "landing" / "traffic_counts", MANIFEST)
        return {k: v for k, v in asdict(entry).items() if k != "header"}

    announce_traffic(ingest_file.expand(source=find_files()))


@dag(
    dag_id="vehicle_stock_monthly",
    schedule="0 9 2 * *",
    start_date=pendulum.datetime(2026, 11, 1, tz=TZ),
    catchup=False,  # history comes from the half-yearly archive files via the "sources" param
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    params=_sources_param(default_cap=2),  # each snapshot is ~1.9 GB to stream
    tags=["vehicle-stock", "ingest"],
    doc_md=__doc__,
)
def vehicle_stock_monthly():
    @task
    def find_files() -> list[str]:
        from common import read_manifest
        from sources import ASTRA_HISTORY_DIR, ASTRA_STOCK_DIR, _get, select_vehicle_stock, vehicle_stock_files

        params = get_current_context()["params"]
        if params["sources"]:
            return list(params["sources"])
        files = vehicle_stock_files(_get(ASTRA_STOCK_DIR).decode(), _get(ASTRA_HISTORY_DIR).decode())
        return select_vehicle_stock(files, read_manifest(MANIFEST))[-params["max_files"] :]

    @task(max_active_tis_per_dag=1, execution_timeout=timedelta(hours=1))
    def ingest_file(source: str) -> dict:
        from dataclasses import asdict

        from vehicle_stock import ingest, load_focus_cantons

        cantons = load_focus_cantons(PROJECT_DIR / "transform" / "seeds" / "regions.csv")
        entry = ingest(
            source,
            cantons,
            DATA_DIR / "landing" / "vehicle_stock",
            DATA_DIR / "landing" / "vehicle_stock_totals",
            MANIFEST,
        )
        return {k: v for k, v in asdict(entry).items() if k != "header"}

    announce_stock(ingest_file.expand(source=find_files()))


@dag(
    dag_id="warehouse_build",
    schedule=(TRAFFIC_LANDED | STOCK_LANDED),
    start_date=pendulum.datetime(2026, 11, 1, tz=TZ),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 0},
    tags=["dbt", "databricks"],
    doc_md=__doc__,
)
def warehouse_build():
    # Only for the Databricks target: upload to the Unity Catalog volume + COPY INTO bronze.
    # Runs with the dbt virtualenv's Python, which has the Databricks SDK and SQL connector.
    load_to_warehouse = BashOperator(
        task_id="load_to_warehouse",
        bash_command=(
            f'if [ "{DBT_TARGET}" = "databricks" ]; then '
            f"cd '{PROJECT_DIR}' && '{LOADER_PYTHON}' load/databricks_load.py; "
            f'else echo "skipped: target {DBT_TARGET} reads the landed Parquet files directly"; fi'
        ),
        retries=2,
    )

    dbt_build = BashOperator(
        task_id="dbt_build",
        # Own target path: dbt's partial-parse cache stores absolute paths, so sharing target/ with
        # runs outside the container (other mount point) makes dbt look for seeds in the wrong place.
        bash_command=(
            f"cd '{PROJECT_DIR / 'transform'}' && "
            f"'{DBT_BIN}' build --profiles-dir . --target {DBT_TARGET} --target-path target/airflow"
        ),
        env={"DATA_DIR": str(DATA_DIR)},  # used by the local Spark target
        append_env=True,
        retries=0,  # a failing data test should stop the run, not be retried
    )

    load_to_warehouse >> dbt_build


traffic_counts_daily()
vehicle_stock_monthly()
warehouse_build()
