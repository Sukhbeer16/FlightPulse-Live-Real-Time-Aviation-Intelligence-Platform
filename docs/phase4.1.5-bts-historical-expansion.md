# Phase 4.1.5 — Historical BTS dataset expansion

This phase adds official BTS On-Time Reporting Carrier On-Time Performance
monthly archives for 2024-02 through 2024-12, while retaining the original
January source files, processed dataset, Phase 3.2 analytics, and January-only
Phase 4.1 feature artifact. It prepares historical data only; no model is
trained.

## Acquisition and monthly validation

The pipeline uses the official BTS PREZIP URL pattern:

`https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2024_{month}.zip`

For each missing month, the pipeline checks the official response and
advertised nonzero size, downloads the archive through the existing resumable
downloader, checks the exact month-specific CSV member and ZIP CRC, extracts
the CSV without replacing an existing source, and records archive/CSV
SHA-256 provenance. An HTTP 404/410 is recorded as an unavailable month;
network/server errors and malformed data stop the run rather than being
silently treated as unavailable.

CSV validation uses 50,000-row chunks and the existing disk-backed
exact-duplicate tracker. Monthly source headers must match the preserved
January BTS header. Dates outside the requested month reject that archive;
missing/unparseable dates, missing identity, exact duplicates, and duplicate
rows made identical by normalization are counted as separate exclusions.
Invalid numeric values and missing fields are described in the existing
chunked quality scan; invalid measurements remain null after cleaning.

The per-month JSON validation report records the raw source count, retained
count, disjoint exclusion reasons, exact duplicate count, cancellation and
diversion counts, eligible arrival-delay records, delayed/non-delayed target
counts, null arrival delays, airline/airport/route counts, schema, and source
checksums. Retained rows must satisfy:

`retained records = cancelled + diverted + eligible arrival-delay records`

`eligible arrival-delay records = ArrDelay > 15 + ArrDelay <= 15`

Cancelled/diverted overlap and unknown status flags are rejected. Raw rows
excluded for quality issues are included in source-versus-retained
reconciliation, not silently discarded.

## Annual and ML outputs

Monthly cleaned Parquet files and their reports are written under ignored
`data/processed/monthly/`. The annual, schema-checked,
Zstandard-compressed Parquet is `data/processed/bts_ontime_2024.parquet`;
`bts_ontime_2024_manifest.json` lists included/unavailable months, source
filenames and checksums, row counts, schema, validation status, and
processing time. Exact duplicates are checked within each month. Since each
month is validated to contain dates only in its distinct calendar month,
cross-month exact duplicates cannot occur.

The annual ML output is separate from the January-only artifact:

- `data/processed/ml/flight_delay_features_2024.parquet`
- `data/processed/ml/feature_manifest_2024.json`

It reuses the Phase 4.1 21-feature allowlist and leakage denylist. Eligibility
remains `Cancelled == 0`, `Diverted == 0`, and non-null `ArrDelay`; the target
is `ArrDelay > 15`. Scheduled-time parsing, cyclic features, categorical
preservation, numeric range checks, and missingness indicators use the same
Phase 4.1 rules. Numeric medians are calculated only from eligible training
months. Neither raw `FlightDate` nor the split label is a model feature.

Months are assigned chronologically as whole-month groups: approximately
two-thirds of included months are training, one-sixth validation, and all
remaining months final test. With all 12 months this is January–August train,
September–October validation, and November–December test. If fewer months are
available, the same deterministic proportions apply, with at least one month
per partition. Split boundaries and class counts are written to the feature
manifest. A single year does not establish year-over-year or seasonal
generalization.

## Run and resource use

From the repository root in PowerShell, run the sequential acquisition,
monthly processing, annual build, and annual feature preparation:

```powershell
.\.venv\Scripts\python.exe -m pipelines.ingestion.bts_annual_expansion
```

The pipeline does not use Spark, Hadoop, Hive, Kafka, or model-training
libraries. It processes one monthly CSV at a time and uses bounded Pandas
chunks and PyArrow Parquet batches. Existing January data and generated
analytics are never rewritten. Validated existing monthly/annual outputs are
reused only after checksums, schema, and row counts pass; incomplete or stale
outputs cause an explicit error.
