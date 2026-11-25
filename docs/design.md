# Design notes

## Source facts (verified 2026-11-24)

### Traffic counts, City of Zurich

* Dataset `sid_dav_verkehrszaehlung_miv_od2031` on data.stadt-zuerich.ch (also listed on opendata.swiss), CC0.
  One CSV per year since 2012, 380-505 MB each; an all-years Parquet (~73 MB) exists as well.
* Columns: `MSID, MSName, ZSID, ZSName, Achse, HNr, Hoehe, EKoord, NKoord, Richtung, Knummer, Kname, AnzDetektoren,
  D1ID, D2ID, D3ID, D4ID, MessungDatZeit, LieferDat, AnzFahrzeuge, AnzFahrzeugeStatus`. Comma-separated.
* `MessungDatZeit` = start of the hour, ISO 8601, local time without offset. On the spring DST day 02:00 is missing,
  on the autumn day it appears twice (checked in the 2026 file: 217 points x 2 rows at `2026-10-25T02:00:00`,
  and these are the only duplicate keys in the file).
* `AnzFahrzeugeStatus`: `Gemessen`, `Imputiert` (single missing hours, filled from the same hour in past years),
  `Fehlend` (longer outages, `AnzFahrzeuge` empty). 2026 so far: 96.6% measured, 3.3% missing, 0.1% imputed.
* 2026: 217 measuring points at 113 counting sites. `Richtung` is `einwärts`/`auswärts` for most points, a place name
  (e.g. `Bucheggplatz`) for others. `LieferDat` is the same for the whole file: the file is rebuilt daily.

### Vehicle stock, ASTRA

* The opendata.swiss dataset `motorfahrzeugbestand-nach-fahrzeugart-treibstoff-gemeinde-und-monat-seit-mai-2024`
  returns "not authorized" through the CKAN API and the portal (2026-11-24). The record-level ASTRA files are used.
* `https://opendata.astra.admin.ch/ivzod/1000-Fahrzeuge_IVZ/1300-Fahrzeugbestaende/1320-Datensaetze_monatlich/`:
  `best_ogd.txt` (1.8 GB, current month, new layout), `BEST.txt` (1.9 GB, old layout, current month),
  `BEST_ANDERE/ANH/MOTO.txt` (other vehicle groups) and `1323-Vorjahrsdaten/BEST-YYYYMMDD.txt` (1.6-1.9 GB each:
  2019-07, 2020-01, 2020-07, 2021-01, 2021-07, 2022-01, 2022-07, 2023-01, 2024-01, 2024-07, 2025-01, 2026-01).
* Tab-separated, UTF-8 without BOM, CRLF. One row per vehicle in circulation (`Inverkehrsetzung_Status_Code = I`).
* Header layouts: see `ingest/vehicle_layouts.py` (six variants, two families).
* `PLZ` is masked: `80..`; in `BEST-20220701.txt` only one digit: `8...`.
* Fuel codes seen: B Benzin, D Diesel, E Elektrisch, C Benzin/Elektrisch, F Diesel/Elektrisch,
  R Elektrisch mit Range Extender, N Erdgas, Y Erdgas/Benzin, Z LPG/Benzin, K Benzin/Ethanol, M Methanol, and blank.
  `Hybridcode` (since 2022-07): `NOVC-HEV`, `OVC-HEV`, `N/A` or empty; most hybrids are `N/A`.
* `Inverkehrsetzung_Kanton` contains the 26 cantons, `FL` and `-1` (unknown).

## Grain of each model

| Model | Grain |
|---|---|
| `stg_traffic__hourly_counts` | one source row = one measuring point, one local hour (two rows for the repeated DST hour) |
| `int_traffic_hourly` | same + `dst_fold`, day type (incl. public holidays) |
| `int_traffic_point_days` | measuring point x local day, with expected hours (23/24/25) and a completeness flag |
| `stg_vehicle_stock__cars` | one passenger car in a focus canton x stock date |
| `stg_vehicle_stock__totals` | stock date x canton x vehicle type x fuel (all of Switzerland) |
| `int_vehicle_stock_by_region` | region x stock date |
| `mart_peak_hours` | direction group x day type x hour of day |
| `mart_busiest_sites_at_peak` | measuring point |
| `mart_traffic_monthly` | month |
| `mart_ev_share_by_region` | region x stock date |
| `mart_ev_growth_zug_vs_zurich` | region |
| `mart_ev_share_by_canton` | canton x stock date (all 26 cantons, from the control totals) |
| `mart_bev_share_new_cars_monthly` | region x month of first registration (latest snapshot only) |
| `mart_traffic_vs_ev_monthly` | month (traffic months; car shares as of the month) |
| `mart_data_quality` | loaded file |

## Definitions (configurable in `dbt_project.yml`)

* Rush hours on working days: 06-09 and 16-19 local time. Working day = Monday-Friday and not a public holiday.
* Complete day: every hour that exists that day has a value (`Gemessen` or `Imputiert`).
* Electric car: fuel code `E` (battery-electric). "Electrified" adds R, C and F.
* City of Zurich = postcodes 80xx (approximation; reported only when >= 95% of the canton's cars have a two-digit postcode).
* Stock date: first day of the month the stock is valid for (`31.10.2026` -> `2026-11-01`).

## Known limitations

* Traffic counts are motor traffic only and only within the City of Zurich: there is no Zug traffic in this project.
* Vehicles are counted where they are registered, not where they drive.
* The new-registration signal is built from survivors in the latest snapshot (scrapped or moved cars are missing).
* Holidays: full-day cantonal holidays only, no school holidays, no Sechseläuten/Knabenschiessen afternoons.

## Work plan

1. Run `make ingest-traffic` and `make ingest-vehicle-stock` on a machine that can reach both portals (~25 GB to
   stream for all vehicle snapshots, a few minutes per file); check `gold.mart_data_quality`.
2. Write the findings for both questions into the README.
3. First run on Databricks Free Edition.
4. Dashboard (`dashboard/app.py`): done on synthetic data; check it on the real data.
