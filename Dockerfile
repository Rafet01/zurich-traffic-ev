# Airflow + this project's pipeline in one image.
# dbt (and the Databricks SDK/SQL connector it brings) lives in its own virtualenv so its
# dependencies never clash with Airflow's. The ingest task only needs pyarrow, which the
# official Airflow image already ships (pinned by Airflow's constraints).
FROM apache/airflow:3.3.2-python3.12

COPY requirements.txt requirements-databricks.txt /tmp/
RUN python -m venv /opt/airflow/dbt-venv \
 && /opt/airflow/dbt-venv/bin/pip install --no-cache-dir -r /tmp/requirements-databricks.txt

ENV PROJECT_DIR=/opt/project \
    DBT_BIN=/opt/airflow/dbt-venv/bin/dbt \
    LOADER_PYTHON=/opt/airflow/dbt-venv/bin/python \
    AIRFLOW__CORE__DAGS_FOLDER=/opt/project/orchestration/dags \
    AIRFLOW__CORE__LOAD_EXAMPLES=false
