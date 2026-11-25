PY ?= python
DATA_DIR ?= $(CURDIR)/data
export DATA_DIR
DBT = cd transform && dbt

.PHONY: setup setup-spark lint test fixtures holidays ingest-traffic ingest-vehicle-stock build build-spark compare-engines demo load-databricks airflow dashboard benchmark

setup:                ## install pipeline + dev tools (DuckDB)
	$(PY) -m pip install -r requirements-dev.txt

setup-spark:          ## add local Spark + dbt-databricks (needs Java 17+)
	$(PY) -m pip install -r requirements-spark.txt

lint:                 ## Python (ruff) and SQL (sqlfluff, dbt templater)
	ruff check . && ruff format --check .
	cd transform && sqlfluff lint models tests

test:                 ## unit tests (ingest, layouts, sources, Databricks load plan, DAGs if Airflow is installed)
	$(PY) -m pytest -q

fixtures:             ## synthetic files in the real layouts (no download needed)
	$(PY) tests/make_fixtures.py tests/fixtures

holidays:             ## regenerate the public holiday seed
	$(PY) scripts/make_holidays.py

ingest-traffic:       ## stream every yearly traffic CSV not loaded yet (+ the current year if it changed)
	$(PY) pipeline.py ingest-traffic

ingest-vehicle-stock: ## stream every vehicle stock snapshot not loaded yet (~1.9 GB each, ~1 min per file)
	$(PY) pipeline.py ingest-vehicle-stock

build:                ## dbt seeds, models and data tests (DBT_TARGET=dev|spark|databricks)
	$(DBT) build --profiles-dir .

build-spark:          ## same models on local Apache Spark (Databricks' engine)
	cd transform && DBT_TARGET=spark dbt build --profiles-dir .

compare-engines:      ## after build + build-spark: assert both engines produced identical gold tables
	cd transform && $(PY) ../scripts/compare_engines.py

load-databricks:      ## upload landed Parquet to a Unity Catalog volume + COPY INTO bronze
	$(PY) load/databricks_load.py

demo:                 ## end-to-end on the synthetic files (fixtures -> ingest -> dbt build)
	$(PY) pipeline.py demo

benchmark:            ## time both ingests on large synthetic files (~1 GB in /tmp, nothing downloaded)
	$(PY) pipeline.py benchmark

dashboard:            ## Streamlit dashboard on the gold tables (pip install -r requirements-dashboard.txt)
	$(PY) pipeline.py dashboard

airflow:              ## local Airflow UI on http://localhost:8080
	docker compose up --build
