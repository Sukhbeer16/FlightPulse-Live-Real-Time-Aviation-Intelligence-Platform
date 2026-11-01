# Phase 4.1.6 — Combined January–February ML Feature Dataset

This phase creates a separate leakage-safe feature dataset from the validated
January and February 2024 BTS Parquet files. It prepares data only; it does not
train or evaluate a model. The unfinished annual expansion is deferred, and
the incomplete March download is not an input.

## Inputs and eligibility

The pipeline reads only the 11 source columns needed for eligibility, target,
date splitting, and the existing Phase 4.1 allowlisted features. It streams
each Parquet file in 50,000-row Arrow batches; it does not combine the full
source in Pandas or modify either monthly Parquet file.

A row is eligible when `Cancelled == 0`, `Diverted == 0`, and `ArrDelay` is
non-null. The target `target_arr_delay_gt_15` is 1 when `ArrDelay > 15` and 0
otherwise. Arrival delay is used only for eligibility and target generation.
Reconciliation is enforced against the independently audited counts:

| Metric | January | February | Combined |
|---|---:|---:|---:|
| Source rows | 547,271 | 519,221 | 1,066,492 |
| Cancelled | 20,389 | 3,002 | 23,391 |
| Diverted | 1,512 | 950 | 2,462 |
| Eligible | 525,370 | 515,269 | 1,040,639 |
| Delayed (`ArrDelay > 15`) | 122,508 | 78,789 | 201,297 |
| Non-delayed (`ArrDelay <= 15`) | 402,862 | 436,480 | 839,342 |

Unknown cancellation/diversion flags, overlapping status flags, missing dates,
out-of-month records, unexpected daily coverage, and any count mismatch stop
generation rather than silently dropping data.

## Feature and leakage contract

The exact 21-feature allowlist is reused from
`pipelines/ml/feature_dataset.py`:

- Categorical: `Reporting_Airline`, `Origin`, `Dest`.
- Numeric: `month`, `day_of_month`, `day_of_week`,
  `scheduled_departure_sin`, `scheduled_departure_cos`,
  `scheduled_arrival_sin`, `scheduled_arrival_cos`,
  `scheduled_elapsed_time_minutes`, and `distance_miles`.
- Nine `is_missing_<numeric feature>` indicators.

Only scheduled times and scheduled flight characteristics are used.
`ArrDelay`, departure/arrival actuals, flight-progress measurements,
cancellation/diversion outcomes and details, and delay causes are excluded
from the feature matrix. The target is separate. `flight_date` and `split` are
metadata, not features. HHMM parsing, category normalization, numeric bounds,
and missing-value handling reuse the Phase 4.1 helpers.

## Chronological partitions and imputation

Partitions use the following inclusive date boundaries; all flights on one
calendar date receive the same label:

| Partition | Dates | Rows | Delayed | Non-delayed |
|---|---|---:|---:|---:|
| Train | Jan 1–Feb 11 | 716,676 | 150,800 | 565,876 |
| Validation | Feb 12–20 | 159,176 | 26,526 | 132,650 |
| Test | Feb 21–29 | 164,787 | 23,971 | 140,816 |

Numeric imputation medians are calculated from eligible training rows only.
Validation and test feature values do not contribute to fitting those
medians. Missing categories use the existing `__MISSING__` sentinel; numeric
missingness indicators are retained. The manifest records the training row
count and fitted medians.

January's observed delayed rate is 23.32%, compared with 15.29% in February.
This two-month dataset supports a forward-in-time holdout, not claims of
seasonal or year-over-year generalization.

## Outputs and rerun

The outputs are distinct from the January-only artifacts and are Git-ignored:

- `data/processed/ml/flight_delay_features_2024_01_02.parquet`
- `data/processed/ml/feature_manifest_2024_01_02.json`

The manifest records source paths and SHA-256 checksums, source and partition
counts, date coverage, target and feature definitions, leakage exclusions,
train-only imputation metadata, and the output checksum. The pipeline refuses
to overwrite either combined output and checks that its source files and
existing January/Phase 3.2 artifacts remain unchanged.

Run from the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pipelines.ml.combined_feature_dataset
```

No Spark, Hadoop, Cloudera, or model-training process is started.
