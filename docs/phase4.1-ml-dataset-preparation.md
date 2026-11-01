# Phase 4.1 — ML Dataset Preparation and Feature Engineering

This phase creates a leakage-safe dataset for predicting whether an eligible
flight arrives more than 15 minutes late. It prepares data only; no estimator
is trained.

## Input, target, and eligibility

Input is `data/processed/bts_ontime_2024_01.parquet`, read with PyArrow using
an explicit projection of 11 needed columns. This avoids Spark 4.0's
nanosecond `FlightDate` inference issue and avoids loading the 117-column
source schema or converting flight rows to Pandas. The source remains
unchanged.

A row is eligible only when `Cancelled == 0`, `Diverted == 0`, and `ArrDelay`
is non-null. The target `target_arr_delay_gt_15` is 1 when `ArrDelay > 15` and
0 otherwise. `ArrDelay` is used only to establish eligibility and create the
target; it is never in the feature allowlist. Cancelled, diverted, and
missing-delay rows are not emitted.

The pipeline verifies the following measured population before writing:

| Metric | Rows |
|---|---:|
| Source flights | 547,271 |
| Cancelled | 20,389 |
| Diverted | 1,512 |
| Cancelled/diverted overlap | 0 |
| Eligible feature/target rows | 525,370 |
| Delayed target (1) | 122,508 |
| Non-delayed target (0) | 402,862 |

Both `547,271 = 20,389 + 1,512 + 525,370` and
`525,370 = 122,508 + 402,862` are checked. Unknown cancellation/diversion
flags, non-finite target values, or any mismatch stop the pipeline rather than
silently dropping records.

## Feature selection and leakage audit

The feature matrix is explicitly allowlisted in
`pipelines/ml/feature_dataset.py`. It contains these 21 columns:

| Feature | Meaning |
|---|---|
| `Reporting_Airline`, `Origin`, `Dest` | Categorical carrier and airport codes |
| `month`, `day_of_month`, `day_of_week` | Calendar features derived from `FlightDate` |
| `scheduled_departure_sin`, `scheduled_departure_cos` | Cyclic encoding of scheduled `CRSDepTime` |
| `scheduled_arrival_sin`, `scheduled_arrival_cos` | Cyclic encoding of scheduled `CRSArrTime` |
| `scheduled_elapsed_time_minutes` | Scheduled `CRSElapsedTime`, range-checked |
| `distance_miles` | Scheduled route distance, range-checked |
| `is_missing_<numeric feature>` | Missingness indicator for each of the nine numeric features |

The stored dataset also includes `flight_date`, `split`, and the target as
non-feature metadata. `FlightDate` is used to establish chronological
partitions and derive calendar values; the raw date is not a model feature.
`Airline` is absent from the source; `Reporting_Airline` is used instead.
Source `Month`, `DayofMonth`, and `DayOfWeek` exist as strings, but the
calendar features are derived consistently from `FlightDate`.

The explicit leakage denylist includes:

- Arrival outcome/label fields: `ArrDelay`, `ArrDelayMinutes`, `ArrDel15`,
  `ArrivalDelayGroups`, `is_delayed`, and the target column itself.
- Post-departure progress/outcomes: `DepTime`, `DepDelay`,
  `DepDelayMinutes`, `DepDel15`, `DepartureDelayGroups`, `WheelsOff`,
  `WheelsOn`, `TaxiOut`, `TaxiIn`, `ActualElapsedTime`, `AirTime`, and
  `FirstDepTime`.
- Disruption outcomes: `Cancelled`, `CancellationCode`, `Diverted`,
  `DivAirportLandings`, `DivReachedDest`, `DivActualElapsedTime`,
  `DivArrDelay`, `DivDistance`, and the `Div1`–`Div5` diversion-detail fields.
- Delay-cause fields: `CarrierDelay`, `WeatherDelay`, `NASDelay`,
  `SecurityDelay`, and `LateAircraftDelay`.
- Existing target/eligibility derivatives: `is_trainable` and
  `arrival_delay_category`.

Other source columns are excluded by default because only the allowlist is
selected. In particular, flight date remains split metadata; the pre-departure
scheduled blocks `DepTimeBlk`/`ArrTimeBlk` are redundant with the scheduled
clock fields; `route` is redundant with origin/destination; and tail/flight
numbers and airport IDs/names are omitted to avoid high-cardinality or
duplicative identifiers. The source `Year`/`Quarter` have no useful variation
in this one-month dataset.

Tests assert that the emitted feature columns exactly match the allowlist and
that the target and prohibited outcome fields cannot enter the feature matrix.

## Time, categories, and missing values

Scheduled HHMM values are parsed as numeric integral values. Examples:
`5 -> 00:05`, `30 -> 00:30`, `745 -> 07:45`, `2359 -> 23:59`, and
`2400 -> 00:00`. Negative values, fractional values, non-finite values,
minutes >= 60, and values beyond 2400 become missing.

Scheduled times are represented by sine/cosine pairs over a 24-hour cycle,
avoiding a false linear jump between 23:59 and 00:00. Categorical strings are
trimmed; null and blank categories use the explicit `__MISSING__` category.
Numeric features are checked against the Phase 2 bounds (elapsed time 0–2,000
minutes, distance 0–20,000 miles); invalid or absent values are imputed using
the median calculated from the training partition only. A matching numeric
missingness indicator is retained. No target information or validation/test
feature statistics are used to fit preprocessing values. No ordinal encoding
or learned category mapping is applied; categorical codes remain strings for
a future train-fitted one-hot encoder.

## Chronological partitions and limitation

`FlightDate` covers every calendar day from 2024-01-01 through 2024-01-31, with
no null dates. The reproducible date boundaries are:

| Partition | Dates (inclusive) | Rows | Delayed | Non-delayed |
|---|---|---:|---:|---:|
| Train | Jan 1–21 | 354,632 | 93,985 | 260,647 |
| Validation | Jan 22–26 | 85,898 | 18,246 | 67,652 |
| Test | Jan 27–31 | 84,840 | 10,277 | 74,563 |

This is a forward-in-time, within-month holdout; no random split is used.
Every partition contains January 2024 data, so it does not demonstrate
generalization across seasons, years, carrier schedules, or changing
operating conditions. Before model evaluation, add additional BTS months and
prefer a later month or year as an independent chronological test period.

## Output, validation, and rerun

Generated files are Git-ignored under `data/processed/ml/`:

- `flight_delay_features.parquet` — 525,370 records with three metadata
  columns, the target, and the 21 allowlisted features.
- `feature_manifest.json` — source SHA-256, verified counts, feature and
  leakage lists, train-only imputation medians, and date split boundaries and
  counts.

The projection and Arrow operations keep processing bounded for the 8 GB
Windows laptop; they do not start Spark, Hadoop, or any other service. Current
source feature columns contain no nulls or invalid times, but missing-value
behavior is also tested with synthetic examples.

Run from the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pipelines.ml.feature_dataset
```

The pipeline is deterministic for the same source file and code. Its
reconciliation checks run before output files are written. No model training
or Phase 4.2 work is included.
