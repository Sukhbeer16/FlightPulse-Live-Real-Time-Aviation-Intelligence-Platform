# FlightPulse Live architecture

## Design goals

- Keep ingestion, processing, feature engineering, model work, streaming,
  anomaly detection, persistence, API, and UI responsibilities separate.
- Make the API and frontend independently runnable during early development.
- Introduce infrastructure only when a specific workload needs it.
- Keep credentials, raw datasets, and trained model artifacts outside source
  control.

## Component boundaries

```text
External flight-data providers
           |
           v
   Data ingestion -------> Data processing -------> Feature engineering
           |                       |                         |
           |                       |                         v
           |                       |                 Machine learning
           |                       |                         |
           v                       v                         v
        Streaming ----------> Anomaly detection ------> Database
                                                            |
                                                            v
React + TypeScript UI <------ FastAPI backend API <----------+
```

The diagram shows logical responsibilities, not a requirement to deploy all
components at once. The initial implementation contains a FastAPI health
endpoint and a UI health check. The package directories establish boundaries
for future code; they do not imply that integrations or data sources are
already implemented.

## Initial application

- `backend/app/config/` loads and validates environment-backed settings with
  Pydantic Settings.
- `backend/app/api/` contains HTTP routes. `/health` and
  `/api/v1/health` report process-level status and configured service metadata.
- `backend/app/main.py` builds the FastAPI app and configures local-development
  CORS origins.
- `frontend/` is a separate Vite application and reads its backend URL from
  `VITE_API_BASE_URL`, falling back to `http://127.0.0.1:8000`.
- `backend/tests/` verifies the health responses without external services.

The health endpoint indicates that the API process can respond. It does not
claim that a database, data provider, or other dependency is available.

## Data and service evolution

1. Select and document a licensed flight-data source and its rate limits,
   terms, and failure behavior before implementing an ingestion adapter.
2. Keep raw input and normalized processing outputs distinct. Validate
   schemas and timestamps at ingestion boundaries.
3. Begin with local Python processing. Measure memory and runtime before
   selecting Pandas or adding Spark local mode.
4. Persist derived data in PostgreSQL when the first queryable application
   data use case is defined; evaluate PostGIS only for required spatial
   queries.
5. Add Kafka and a streaming consumer only when continuous ingestion and
   replay/backpressure requirements justify their operational cost.
6. Add Hadoop/Hive only for a demonstrated historical-data workload that
   cannot be served effectively by the simpler local and PostgreSQL path.
7. Version training data and model artifacts outside Git; define model
   evaluation, inference, and monitoring requirements before adopting MLflow.

## Historical BTS ingestion (Phase 2)

- `pipelines/ingestion/bts_ingestion.py` downloads the official BTS January
  2024 archive using a resumable partial file, preserves its ZIP and original
  CSV under `data/raw/`, and records checksums/provenance beside the CSV.
- `data_validation.py` inspects the actual header and scans the CSV in chunks.
  Exact full-row duplicate fingerprints are indexed in a temporary SQLite
  file, not kept in process memory.
- `data_cleaning.py` cleans bounded CSV chunks; `feature_creation.py` derives
  calendar, scheduled-departure, route, duration, and delay-label fields.
- The raw source is never edited. Processed data is Zstandard-compressed
  Parquet under `data/processed/`; those data directories are git-ignored.
- Measured quality results are written to `docs/data_quality_report.md`;
  EDA tables and PNG charts are generated under `reports/eda/2024-01/`.
- The delay target is null for cancelled, diverted, unknown-status, or missing
  arrival-delay records. Training-frame creation selects only scheduled and
  calendar predictors and excludes actual times and realized outcomes.
- If direct BTS retrieval is unavailable, an operator can download the CSV
  from TranStats and pass it to the pipeline. The sidecar distinguishes this
  manual, operator-supplied provenance from automated BTS archive download.

This phase adds pandas, PyArrow, and Matplotlib only; it does not install or
start Spark, Kafka, Hadoop, or a database.

## Local resource profile

Start only the FastAPI process and Vite development server initially. Run
infrastructure one service at a time, prefer bounded sample datasets, and use
Spark local mode if/when Spark is introduced. Do not start Kafka, Spark,
Hadoop, and a database together by default. Resource and service choices should
be revisited with measured memory use and project needs.

## Configuration and trust boundaries

Backend settings are read from environment variables and a local `.env` file.
`.env.example` contains non-secret development defaults. Never expose secrets
through Vite `VITE_*` variables: those values are bundled into browser code.
The development CORS allowlist is configured in the backend environment and
should be restricted to the deployed UI origins for production.
