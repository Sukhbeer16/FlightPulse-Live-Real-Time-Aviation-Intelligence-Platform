# BTS On-Time Performance data dictionary

## Dataset and scope

This project uses the U.S. Department of Transportation Bureau of
Transportation Statistics (BTS) **On-Time Reporting Carrier On-Time
Performance** dataset for **January 2024 only**. The official monthly archive
is downloaded from the [BTS TranStats website](https://www.transtats.bts.gov/)
`PREZIP` endpoint; the extracted CSV is kept unchanged under `data/raw/`. A
SHA-256 checksum and acquisition provenance are written beside the raw file.

The pipeline uses the BTS source column names shown below. BTS can add or
change optional fields over time; the pipeline records the actual CSV header
and semantic validation results in `docs/data_quality_report.md`. The required
columns for cleaning and target creation are `FlightDate`,
`Reporting_Airline`, `Origin`, `Dest`, `Cancelled`, `Diverted`, and `ArrDelay`.
Other listed fields are inspected when present.

The official January 2024 archive header was inspected. It contains 110 CSV
header cells: 109 named BTS fields and one trailing blank header (which pandas
labels `Unnamed: 109`). The validation report records the full observed header;
cleaning removes this parser-generated field only when it is entirely empty in
that chunk. The source CSV itself is preserved byte-for-byte.

## Source fields

| BTS field | Meaning | Validation / use |
|---|---|---|
| `FlightDate` | Local flight date | Required; parsed as a date and restricted to January 2024. |
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
- Invalid/unparseable dates, dates outside January 2024, rows missing flight
  identity fields, and exact duplicate input rows are excluded from processed
  data. Raw source bytes are never edited.

These are broad input sanity limits, not claims about the source's observed
minimums or maximums. Actual observed counts and schema are populated by the
pipeline; no statistics are estimated or fabricated in this document.
