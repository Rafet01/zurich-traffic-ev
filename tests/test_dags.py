from pathlib import Path

import pytest

pytest.importorskip("airflow")
from airflow.dag_processing.dagbag import DagBag  # noqa: E402

DAGS = Path(__file__).resolve().parents[1] / "orchestration" / "dags"


def test_dags_import_and_are_wired_by_assets():
    bag = DagBag(dag_folder=str(DAGS))
    assert bag.import_errors == {}
    assert set(bag.dag_ids) == {"traffic_counts_daily", "vehicle_stock_monthly", "warehouse_build"}
    build = bag.dags["warehouse_build"]
    assert build.get_task("dbt_build").upstream_task_ids == {"load_to_warehouse"}
    for dag_id in ("traffic_counts_daily", "vehicle_stock_monthly"):
        dag = bag.dags[dag_id]
        assert dag.catchup is False
        announce = [t for t in dag.tasks if t.task_id.startswith("announce")]
        assert len(announce) == 1 and announce[0].outlets
