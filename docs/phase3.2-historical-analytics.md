# Phase 3.2 — Historical Aviation Analytics

FlightPulse's historical analytics pipeline reads the January 2024 BTS
Parquet dataset and writes compact analytical tables. Spark DataFrames perform
the filtering and aggregation; the original dataset is read-only.

## Architecture and execution

- Python 3.11, PySpark 4.0.5, and Eclipse Temurin Java 21.
- Standalone Spark runs locally with `local[2]`, a 2 GB driver, two shuffle
  partitions, and the existing shared configuration in
  `pipelines/spark/session.py`.
- `pipelines/spark/aviation_analytics.py` projects only fields needed by these
  metrics, normalizes identifiers and time values, calculates reusable
  eligibility flags, runs aggregations, and checks totals before writing.
- The source Parquet schema contains a nanosecond `FlightDate` timestamp, which
  Spark 4.0 cannot infer here, and both `Month` and `month` field names, which
  collide under Spark's default case-insensitive resolution. The reader checks
  Parquet metadata with PyArrow and applies an explicit schema to the required
  fields instead. The month fields are intentionally not projected: this input
  covers January 2024 only, so a month-to-month comparison is not meaningful.
  No source fields are changed or removed from the original dataset.
- On Windows without `winutils.exe`, Spark's local Parquet writer emits Hadoop
  permission warnings. The pipeline therefore converts only bounded grouped
  result tables to Arrow and writes Zstandard Parquet atomically with PyArrow;
  it never collects the flight-level dataset or converts it to Pandas.
- Generated analytics are under ignored `data/processed/analytics/`.

## Metric definitions

- A valid observed delay is non-null, not NaN, and between -1,440 and 10,080
  minutes, inclusive. Null or invalid values are excluded from delay
  denominators; they are never classified as on-time.
- An eligible arrival-delay record is not cancelled, not diverted, and has a
  valid `ArrDelay`. An eligible departure-delay record is not cancelled and
  has a valid `DepDelay`.
- A flight is delayed when its applicable arrival or departure delay is
  strictly greater than 15 minutes. Delay rates use eligible records as the
  denominator. Cancellation rates use all records for the group.
- Airline results include total and eligible flights, delayed, cancelled and
  diverted counts, arrival delay rate, cancellation rate, and mean/median
  eligible arrival delay. Airport departure and arrival measures are separate:
  origin statistics use departure delays; destination statistics use arrival
  delays. Airport cancellation/diversion counts are reported for departures.
- Routes use `Origin-Dest`. The default threshold keeps routes with at least
  30 source records; `--min-route-flights` changes this threshold. All-route
  totals are checked before filtering.
- Hourly results distinguish scheduled/actual departure and scheduled/actual
  arrival. The source `CRS*Time` values are scheduled and `*Time` values are
  actual. Numeric integral HHMM values with minutes below 60 are accepted;
  `2400` maps to hour 0. Null and malformed values are omitted only from that
  time-basis group.
- Weekday results use the source's Monday-based `day_of_week` values 0–6 and
  include separate eligible departure and arrival delay measures.
- Delay distribution rows report category counts and proportions separately
  for eligible arrivals and departures. Categories are `early` (<0),
  `on_time` (0–15), `delayed` (>15–60), `severe` (>60–180), and `extreme`
  (>180 minutes). Approximate p50, p90, p95, and p99 values use Spark
  `percentile_approx` with accuracy 1,000.
- Mean and median delay statistics apply only to eligible observations.
  Medians/percentiles are approximate Spark quantiles.

## Outputs

Each output is a Zstandard-compressed Parquet file. The generated files are
ignored by Git.

| Output | Rows | Description |
|---|---:|---|
| `airline_analytics.parquet` | 15 | Carrier-level totals, delay and cancellation metrics |
| `origin_airport_analytics.parquet` | 334 | Departure-side airport metrics |
| `destination_airport_analytics.parquet` | 334 | Arrival-side airport metrics |
| `route_analytics.parquet` | 4,256 | Routes meeting the default 30-record minimum |
| `hourly_analytics.parquet` | 96 | Four time bases across observed hours |
| `day_of_week_analytics.parquet` | 7 | Weekday departure and arrival measures |
| `delay_distribution.parquet` | 18 | Five delay bands and four percentiles for each delay type |

## Validation results

The completed run reconciled the BTS source to the previously verified Phase 2
metrics:

| Metric | Spark result | Phase 2 expected |
|---|---:|---:|
| Source flights | 547,271 | 547,271 |
| Cancelled | 20,389 | 20,389 |
| Diverted | 1,512 | 1,512 |
| Eligible arrival delay records | 525,370 | 525,370 |
| Delayed eligible arrivals (>15 min) | 122,508 | 122,508 |
| Non-delayed eligible arrivals (<=15 min) | 402,862 | 402,862 |

Airline, destination-airport, and the 4,256 retained route groups matched the
comparable Phase 2 EDA counts exactly. The scheduled-departure hourly groups
also matched all 24 Phase 2 hour counts. Phase 2 contains 5,666 routes; 1,410
below-threshold routes with 17,450 flights are excluded from the route output,
while all 547,271 source records reconcile before that ranking filter. The
origin-airport metrics are newly calculated departure-side measures and have
no directly comparable Phase 2 airport table.

The latest successful full run completed in 18.21 seconds as measured by the
pipeline (about 25.9 seconds wall time including startup/shutdown), on an 8 GB
Windows laptop. Peak process memory was not instrumented. No Spark data loss,
source mismatch, or memory failure was observed.

The test suite passed **44 tests**. `pip check` reported no broken
requirements. Pytest emitted one pre-existing Starlette/httpx deprecation
warning. Spark also emits expected Windows warnings because no Hadoop
`winutils.exe` or native Hadoop library is installed; the PyArrow output path
avoids the affected Spark writer.

## Run again

From the repository root in PowerShell, with the existing `.venv` and Temurin
Java 21 installed:

```powershell
$env:JAVA_HOME = "C:\Program Files\Eclipse Adoptium\jdk-21.0.13.9-hotspot"
$env:PATH = "$env:JAVA_HOME\bin;$env:PATH"
.\.venv\Scripts\python.exe -m pipelines.spark.aviation_analytics
```

To keep routes with at least 50 source records:

```powershell
.\.venv\Scripts\python.exe -m pipelines.spark.aviation_analytics --min-route-flights 50
```

These are batch historical analytics only. Kafka, Hive, streaming, model
training, APIs, and frontend integrations are outside this phase. Carrier,
airport, route, time, and delay-distribution features provide reusable inputs
for future delay prediction and operational airport intelligence.
