# BTS On-Time Performance data dictionary

## Dataset and scope

This project uses the U.S. Department of Transportation Bureau of
Transportation Statistics (BTS) **On-Time Reporting Carrier On-Time
Performance** dataset. The original processed dataset is January 2024;
Phase 4.1.5 extends it with available official monthly archives through
December 2024. The official monthly archives are downloaded from the
[BTS TranStats website](https://www.transtats.bts.gov/) `PREZIP` endpoint.
Extracted source CSVs remain unchanged under `data/raw/`, with checksums and
acquisition provenance beside the raw files.

The pipeline uses the BTS source column names shown below. BTS can add or
change optional fields over time; the pipeline records the actual CSV header
and semantic validation results in `docs/data_quality_report.md`. The required
columns for cleaning and target creation are `FlightDate`,
`Reporting_Airline`, `Origin`, `Dest`, `Cancelled`, `Diverted`, and `ArrDelay`.
Other listed fields are inspected when present.

The preserved January 2024 archive header is the schema baseline for the
annual expansion. Each additional monthly CSV is checked against that exact
header before processing. The January source CSV itself remains
byte-for-byte unchanged.

## Source fields

| BTS field | Meaning | Validation / use |
|---|---|---|
| `FlightDate` | Local flight date | Required; parsed as a date and restricted to its reporting month. |
| `Reporting_Airline` | DOT reporting-carrier code | Required categorical identifier. |
| `Origin` | Origin airport code | Required categorical identifier. |
| `Dest` | Destination airport code | Required categorical identifier. |
| `CRSDepTime` | Scheduled local departure time (`HHMM`) | Validated as a 24-hour clock value; `2400` is accepted as midnight. |
| `DepTime` | Actual local departure time (`HHMM`) | Validated when present; post-departure outcome, never a predictor. |
| `DepDelay` | Departure delay in minutes | Range-checked when present; post-departure outcome, never a predictor. |
| `CRSArrTime` | Scheduled local arrival time (`HHMM`) | Validated as a 24-hour clock value; `2400` is accepted as midnight. |
| `ArrTime` | Actual local arrival time (`HHMM`) | Validated when present; post-arrival outcome, never a predictor. |
| `ArrDelay` | Arrival delay in minutes | Required for target creation; post-arrival label source, never a predictor. |
| `Cancelled` | Cancellation indicator (`0`/`1`) | Required; values outside `{0, 1}` are reported. |
| `Diverted` | Diversion indicator (`0`/`1`) | Required; values outside `{0, 1}` are reported. |
| `Distance` | Scheduled route distance in miles | Non-negative and broad upper-bound sanity check when present. |
| `CRSElapsedTime` | Scheduled elapsed time in minutes | Used as `scheduled_flight_duration_minutes`; not inferred from local clocks. |

Other BTS source columns are retained in the cleaned Parquet output, subject
to numeric conversion for fields used by cleaning and feature creation. The
raw input remains the authoritative source copy.

## Derived columns

| Derived field | Definition |
|---|---|
| `departure_hour` | Hour extracted from scheduled `CRSDepTime`; 2400 maps to 0; malformed or missing time is null. |
| `day_of_week` | Monday-based weekday number (`0` Monday through `6` Sunday) from `FlightDate`. |
| `month` | Calendar month number from `FlightDate` (1 for this scope). |
| `route` | `Origin-Dest`, for example `JFK-LAX`; missing endpoints are not filled. |
| `scheduled_flight_duration_minutes` | `CRSElapsedTime` after numeric conversion and a 0–2000-minute sanity check. |
| `arrival_delay_category` | `cancelled`, `diverted`, `early` (`ArrDelay < 0`), `on_time` (`0 <= ArrDelay <= 15`), `delayed` (`ArrDelay > 15`), or `unknown`. |
| `is_delayed` | Nullable integer target: `1` when `ArrDelay > 15`; `0` when `ArrDelay <= 15`; null for cancelled, diverted, unknown-status, or missing-delay flights. |
| `is_trainable` | True only when both status indicators are explicitly zero and `ArrDelay` is present; false otherwise. |

`create_training_frame` exports only scheduled/date/route predictors plus the
target and excludes actual departure/arrival times, delay measurements,
cancellation/diversion outcomes, and other post-event fields. Do not use
actual flight outcomes in predictive features.

Phase 4.1 produces the model-preparation dataset through
`pipelines/ml/feature_dataset.py`. It uses an explicit feature allowlist,
chronological January 2024 partitions, and train-only numeric imputation; its
21-feature schema, denylist, split metrics, and limitations are documented in
[`phase4.1-ml-dataset-preparation.md`](phase4.1-ml-dataset-preparation.md).
The older chunked-ingestion helper above remains useful for Phase 2 feature
creation, but the Phase 4.1 artifact is the audited model-dataset contract.
Phase 4.1.5 adds an annual dataset and a separate annual feature artifact
without changing the original January source, analytics, or January-only
feature dataset; see
[`phase4.1.5-bts-historical-expansion.md`](phase4.1.5-bts-historical-expansion.md)
for monthly validation, output manifests, and chronological split rules.

EDA cancellation percentages use records with a known `Cancelled` value (0 or
1) as the denominator; delay percentages use eligible, non-cancelled and
non-diverted flights with an observed arrival delay.

## Validation ranges and treatment

- Flight times must be numeric `HHMM` values from `0000` to `2359`, or `2400`;
  minute components must be whole numbers less than 60.
- Delay values are sanity-checked from -1,440 to 10,080 minutes.
- `Distance` is sanity-checked from 0 to 20,000 miles.
- Scheduled/actual elapsed-time fields are sanity-checked from 0 to 2,000
  minutes.
- Cancellation and diversion flags are expected to be 0 or 1.
- Empty/null measurements are counted, not imputed. Invalid numeric values are
  coerced to missing in the cleaned output; missing features remain missing.
-   Invalid/unparseable dates, dates outside the reporting month, rows missing
  flight identity fields, and exact duplicate input rows are excluded from
  processed data. Raw source bytes are never edited.

These are broad input sanity limits, not claims about the source's observed
minimums or maximums. Actual observed counts and schema are populated by the
pipeline; no statistics are estimated or fabricated in this document.
