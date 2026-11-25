"""Check that DuckDB and Spark produced the same gold tables (run after `make build` and `make build-spark`).

  cd transform && python ../scripts/compare_engines.py

Spark is opened the way dbt-spark's session mode opens it (Hive metastore in the current directory),
so run this from transform/. Floats are compared after rounding, everything else exactly, as multisets.
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

DUCKDB_PATH = Path("../data/warehouse.duckdb")
DIGITS = 6


def normalise(value):
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (float, Decimal)):
        return round(float(value), DIGITS) + 0.0  # + 0.0 turns -0.0 into 0.0
    if isinstance(value, int):
        return float(value)  # DuckDB sums are HUGEINT/BIGINT, Spark's may be DECIMAL: compare numerically
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def table_rows(columns, rows) -> Counter:
    return Counter(tuple(normalise(v) for v in row) for row in rows)


def main() -> int:
    import duckdb
    from pyspark.sql import SparkSession

    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    spark = SparkSession.builder.enableHiveSupport().getOrCreate()
    spark.sparkContext.setLogLevel("ERROR")

    tables = [
        r[0] for r in con.sql("select table_name from information_schema.tables where table_schema = 'gold'").fetchall()
    ]
    failures = 0
    for table in sorted(tables):
        d = con.sql(f"select * from gold.{table}")
        d_cols = [c.lower() for c in d.columns]
        s = spark.table(f"gold.{table}")
        s_cols = [c.lower() for c in s.columns]
        if d_cols != s_cols:
            print(f"DIFF  {table}: columns differ\n  duckdb {d_cols}\n  spark  {s_cols}")
            failures += 1
            continue
        d_rows = table_rows(d_cols, d.fetchall())
        s_rows = table_rows(s_cols, [tuple(r) for r in s.collect()])
        if d_rows == s_rows:
            print(f"same  {table}: {sum(d_rows.values())} rows")
        else:
            failures += 1
            only_d, only_s = d_rows - s_rows, s_rows - d_rows
            print(f"DIFF  {table}: {sum(only_d.values())} rows only in DuckDB, {sum(only_s.values())} only in Spark")
            for row in list(only_d)[:3]:
                print("  duckdb:", row)
            for row in list(only_s)[:3]:
                print("  spark: ", row)
    spark.stop()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
