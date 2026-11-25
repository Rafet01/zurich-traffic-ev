# Traffic and electric cars in Zurich and Zug

An end-to-end data engineering project on two Swiss open data sources with **different grains**:

* **Motor traffic counts of the City of Zurich**: vehicles per hour at ~200 measuring points, one CSV per year
  since 2012 (~450 MB each, the current year regenerated every morning).
* **The ASTRA vehicle stock**: every registered vehicle in Switzerland as one row, a ~1.9 GB file per snapshot
  (archive snapshots every 6-12 months since July 2019, plus the current month), without holder data, postcode masked to two digits.

Both are streamed, fingerprinted and landed as Parquet, then modelled with **dbt** into answers.

**Stack:** Python (streaming ingest, PyArrow) · Parquet · dbt · DuckDB · Apache Spark · Databricks
(Unity Catalog, Delta, COPY INTO) · Apache Airflow 3 (asset-driven scheduling) · Streamlit · Docker ·
GitHub Actions · pytest · ruff · sqlfluff

One dbt project, three engines, same results:

| Target | What it is | Account needed |
|---|---|---|
| `dev` | DuckDB file on your laptop | no |
| `spark` | Apache Spark in-process (pyspark), the engine Databricks runs on | no (Java 17+) |
| `databricks` | Databricks SQL warehouse, Unity Catalog, Delta tables | yes (Free Edition is enough) |

CI builds every model on DuckDB and on Spark and then compares all gold tables row by row
(`scripts/compare_engines.py`). That check already caught two engine differences the tests did not:
dbt-spark loads an empty seed cell as the string `'None'`, and a cross-database `datediff` needed parentheses.

## Questions

1. **Where and when** is rush-hour traffic in Zurich heaviest? (`gold.mart_peak_hours`, `gold.mart_busiest_sites_at_peak`)
2. **Does the share of electric cars grow faster in Zug than in Zurich?** (`gold.mart_ev_share_by_region`,
   `gold.mart_ev_growth_zug_vs_zurich`)
3. How do the two fit together month by month? (`gold.mart_traffic_vs_ev_monthly`)

## Architecture

```
data.stadt-zuerich.ch                     ingest/ (Python, one streaming pass per file)        transform/ (dbt)
┌──────────────────────────┐   ┌──────────────────────────────────────────────┐   ┌───────────────────────────────────┐
│ ..._OD2031_<year>.csv    │──▶│ traffic.py: SHA-256 of the exact bytes,      │   │ bronze  landed rows, control      │
│ hour x measuring point   │   │ column check, lineage per row                │──▶│         totals, ingest manifest   │
└──────────────────────────┘   │                                              │   │ silver  typed counts (+ DST fold),│
opendata.astra.admin.ch        │ vehicle_stock.py: header layout -> canonical │   │         complete days, cars per   │
┌──────────────────────────┐   │ columns, keep passenger cars in ZH/ZG,       │   │         region                    │
│ BEST-YYYYMMDD.txt        │──▶│ AND count every row per canton x type x fuel │   │ gold    peak hours, busiest       │
│ best_ogd.txt (current)   │   │ (control totals for all of Switzerland)      │   │         sites, BEV share + growth,│
│ one row per vehicle      │   │ -> manifest.jsonl (hash, layout, rows, ...)  │   │         monthly as-of join, DQ    │
└──────────────────────────┘   └──────────────────────────────────────────────┘   └───────────────────────────────────┘
                                        data/landing/**/*.parquet ──(databricks target)──▶ load/: UC volume ──▶ COPY INTO

Airflow 3:  traffic_counts_daily (07:30) ──┐
                                           ├─ assets ─▶ warehouse_build: load_to_warehouse ─▶ dbt_build (run + tests)
            vehicle_stock_monthly (2nd) ───┘           (only runs when an ingest DAG really landed new data)
```

* **Stream, never store.** A 1.9 GB vehicle file is hashed, parsed and filtered in one pass; only the rows we need
  (passenger cars in Zurich and Zug) and a few hundred control totals are written.
* **Manifest.** `data/manifest.jsonl` logs every attempt: dataset, file, URL, SHA-256, bytes, matched layout, header
  fingerprint, rows read / kept / rejected, partition (year or stock date) and where it came from, HTTP ETag and
  Last-Modified, status. Same bytes again = `skipped_duplicate`; unchanged ETag/Last-Modified = `skipped_unchanged`
  (no 450 MB download for nothing); unknown header = `failed_schema`.
* **Lineage.** Every landed row carries `_source_file`, `_source_sha256`, `_source_row_number`:
  `traffic_count_id` and `vehicle_record_id` point to one exact line in one exact file.
* **Reconciliation.** dbt tests check that landed rows equal the manifest, that control totals add up to every
  valid row read, and that the kept cars per canton and fuel equal the totals of the same file.

## The grain problem

| | Traffic | Vehicle stock |
|---|---|---|
| Time | one hour (local time, no offset) | one snapshot (every 6-12 months 2019-2026, monthly from now on) |
| Space | one measuring point (LV95 coordinates, City of Zurich) | canton, and a postcode masked to 2 digits |
| Unit | vehicles passing | vehicles registered |

The project does not pretend they are the same: traffic is aggregated to *complete* point-days and then months;
car shares are taken **as of** the month (latest reliable snapshot on or before its first day, its age reported,
nothing interpolated). Regions are a seed (`regions.csv`): Canton of Zurich, Canton of Zug, Switzerland, and the
City of Zurich approximated by postcodes `80xx`. A monthly signal is also derived from a single snapshot:
the BEV share among cars by month of first registration (survivors only, documented as such).

## Data pitfalls this project handles

| Pitfall | What goes wrong if ignored | How it's handled |
|---|---|---|
| **Six different headers** in the ASTRA files 2019-2026 (57-64 columns, typos `Erstinvekehrsetzung_Kanton` and `Erstinverkehrsetzung_Monat]`, trailing `V58`, a complete renaming in Nov 2026 where `Treibstoff` switches from fuel *name* to fuel *code*) | Silent misparse or a pipeline that only works on one year | Two layout families, aliases per canonical column, resolved per file, layout + header fingerprint in the manifest, unit test per real header |
| **Postcode precision changes**: `80..` in most files, `8...` (one digit) in July 2022 | City of Zurich drops to 0 cars, a fake collapse | Per-snapshot coverage of two-digit postcodes; postcode regions below 95% are kept but flagged, without numbers |
| **Plug-in hybrids not identifiable** before mid-2022 (`Hybridcode`), then `Pluginhybrid` in the new layout | Inconsistent "EV" definition over time | Headline metric = battery-electric only (fuel code `E`), the same in every file; `is_plug_in_hybrid` is null where unknown |
| Snapshot date: `Datenstand` `01.07.2022` vs `31.10.2026`, sometimes absent, sometimes empty on the first rows | Off-by-one-month joins | One convention (first day of the month the stock is valid for); source of the date recorded (data, file name, HTTP header, argument) |
| Free-text fields (model names) may contain quote characters in a tab-separated file | With default CSV quoting, a value starting with `"` swallows the following columns | No quoting at all (`QUOTE_NONE`, unit-tested); rows with the wrong number of fields are counted as rejected |
| **Daylight saving time**: local times without offset, 23-hour day in March, the hour 02:00 twice in October | Duplicate keys, wrong daily totals, "missing" hours | `dst_fold` from the file order; a day is complete when it has exactly 23/24/25 hours with a value; tests for both |
| Missing hours (`Fehlend`) and city-imputed hours (`Imputiert`) | Outages look like quiet days; imputed values look measured | Only complete days enter volumes; shares measured / imputed / missing per month and per file |
| Measuring points come and go over 15 years | Total city traffic "grows" because points were added | Volumes reported per measuring point, with the number of contributing points |
| Public holidays behave like Sundays | Rush hour diluted | Holiday seed for the canton of Zurich (generated, Easter-based dates); day type `holiday` |
| The current year's file and the current snapshot are rewritten in place | Re-downloading 2 GB daily, or double counting | ETag/Last-Modified check before download; only the newest file per year / stock date is used |
| Company and leasing cars are registered where the holder sits (Zug hosts many company seats) | Zug's EV share may reflect fleets more than residents | Open question for the real-data run; vehicles are counted where they are registered (`Inverkehrsetzung_Kanton`) |

## Running it

### Locally (DuckDB, nothing to sign up for)

```bash
python -m venv .venv && . .venv/bin/activate
make setup
make lint test        # ruff, sqlfluff, pytest
make demo             # end-to-end on synthetic files in the real layouts (no download)

make ingest-traffic         # all yearly CSVs not loaded yet (~450 MB each)
make ingest-vehicle-stock   # all snapshots not loaded yet (~1.9 GB each)
make build                  # dbt seed + run + test
```

Results land in `data/warehouse.duckdb`, e.g.

```sql
select * from gold.mart_ev_growth_zug_vs_zurich order by rank_by_pp_per_year;
select * from gold.mart_peak_hours where busiest_rank = 1;
```

### Dashboard

```bash
pip install -r requirements-dashboard.txt
make dashboard     # Streamlit on http://localhost:8501, reads data/warehouse.duckdb read-only
```

Three views, one per question: battery-electric share per region over the snapshots (with the growth in
percentage points per year as headline numbers), the average day profile per day type with the rush-hour
windows shaded, and a map of the busiest measuring points at the morning or evening peak. Each view names the
gold table it reads. CI runs the dashboard headlessly against the demo warehouse (`tests/test_dashboard.py`).

### With Airflow (Docker)

```bash
make airflow       # docker compose up --build, UI on http://localhost:8080
```

Trigger `traffic_counts_daily` or `vehicle_stock_monthly` with `{"sources": ["<path or URL>", ...]}` to load
specific years or snapshots; `warehouse_build` follows automatically through the assets.

### On Apache Spark (no account)

```bash
make setup-spark   # pyspark + dbt-spark + dbt-databricks; needs Java 17+
make build-spark   # same models and tests, executed by Spark
```

### On Databricks

1. Run `load/databricks_setup.sql` once in a SQL editor: `bronze`/`silver`/`gold` schemas, a Unity Catalog volume
   and the three bronze Delta tables.
2. `pip install -r requirements-databricks.txt`, copy `.env.example` to `.env` and fill in host, SQL warehouse
   HTTP path and token.
3. `make load-databricks` (upload + `COPY INTO`, both idempotent) and `DBT_TARGET=databricks make build`.

## Performance

`make benchmark` generates a year of traffic counts (217 measuring points x 365 days x 24 hours) and two
million vehicle rows in the real layouts and times both ingests, each in its own process
(4-vCPU cloud container, Python 3.13, nothing downloaded):

| File | Size | Rows | Time | Throughput | Kept | Peak memory |
|---|---|---|---|---|---|---|
| Traffic, one year | 406 MB | 1.90 M | 18 s | 23 MB/s, 105k rows/s | all rows, 10 MB Parquet | 0.4 GB |
| Vehicle stock | 638 MB | 2.00 M | 15 s | 42 MB/s, 130k rows/s | 0.6 M cars in ZH/ZG, 4 MB Parquet | 0.3 GB |

So a 1.9 GB vehicle snapshot is about 45 s of parsing and the full history (13 snapshots, 15 traffic years)
about 15 minutes; on a connection slower than about 200-300 Mbit/s the download is the bottleneck, not the parser. Memory does not grow
with the file. The benchmark found one place where it did: rewriting a landed file to stamp the SHA-256 read it
into memory whole, 1.4 GB for a traffic year; it is now rewritten batch by batch. Every real run records its own
wall-clock time in the manifest (`duration_seconds`, shown in `gold.mart_data_quality`).

## Data sources and licences

* City of Zurich, Dienstabteilung Verkehr: [Daten der Verkehrszählung zum motorisierten Individualverkehr
  (Stundenwerte)](https://data.stadt-zuerich.ch/dataset/sid_dav_verkehrszaehlung_miv_od2031), CC0.
* Federal Roads Office ASTRA: [vehicle data](https://www.astra.admin.ch/de/fahrzeugdaten), open government data
  on the [ASTRA data platform](https://opendata.astra.admin.ch/ivzod/) (`1300-Fahrzeugbestaende`).
  The opendata.swiss dataset "Motorfahrzeugbestand nach Fahrzeugart, Treibstoff, Gemeinde und Monat" that this
  project first planned to use is no longer publicly readable (checked 2026-11-24), so the project works from
  the record-level ASTRA files instead; municipality-level detail is replaced by canton + two-digit postcode.

`tests/make_fixtures.py` generates **synthetic** data in the official layouts (verbatim headers); the numbers in
the fixtures are invented.

## Status and roadmap

- [x] Streaming ingest for both sources with hashing, manifest, lineage and control totals
- [x] Six real ASTRA header layouts resolved and unit-tested
- [x] dbt models and tests on DuckDB and Spark; Databricks loader; medallion layout
- [x] Three Airflow DAGs wired by assets; Docker image; CI that runs the DAGs inside the image
- [ ] First full run on the real files (15 traffic years, 13 vehicle snapshots) and findings in this README
- [x] Map of the busiest measuring points (LV95 -> WGS84) in a small Streamlit dashboard
- [ ] Optional: canton-level comparison with all 26 cantons (the control totals already contain them)
