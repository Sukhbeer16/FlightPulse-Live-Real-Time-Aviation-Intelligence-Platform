# Development roadmap

The roadmap is incremental. Each phase should have a defined data source,
acceptance criteria, and resource budget before adding infrastructure.

## Phase 0 — Runnable foundation

- Independently run the FastAPI backend and React frontend.
- Load backend configuration from environment variables.
- Expose and test service health checks.
- Keep runtime dependencies small and avoid external services.

**Exit criteria:** backend tests pass, frontend production build succeeds,
and the UI can report backend health.

## Phase 1 — Data contract and ingestion

- Choose an appropriately licensed live and/or historical flight-data source.
- Document access terms, update cadence, rate limits, fields, and provenance.
- Define validated internal flight and airport schemas.
- Implement one ingestion adapter with explicit timeouts, retries, and
  observable failures; do not fabricate production flight records.

**Exit criteria:** source data can be acquired reproducibly and validated
without committing credentials or datasets.

## Phase 2 — Historical processing and storage

- Build a small, reproducible batch pipeline and schema-quality checks.
- Start with local Python processing; profile representative data and memory.
- Add PostgreSQL when persistent query requirements are clear.
- Evaluate PostGIS only for concrete spatial-query needs.

**Exit criteria:** repeatable processing results and tested persistence/query
behavior on a bounded dataset.

## Phase 3 — Flight intelligence UI and API

- Define API contracts for flight positions, airport status, and airline
  disruption summaries based on available source data.
- Add map interactions and filters to the frontend.
- Add pagination, validation, and operational logging where the API needs
  them.

**Exit criteria:** UI features use real, sourced data and recover visibly
from API/provider failures.

## Phase 4 — Delay prediction

- Define a prediction target, time horizon, and leakage-safe evaluation split.
- Establish a simple baseline before testing scikit-learn or XGBoost models.
- Version data/metrics and introduce MLflow only if experiment tracking is
  useful for the workflow.
- Serve predictions only after evaluation and freshness requirements are met.

**Exit criteria:** documented evaluation results and reproducible inference
with explicit model/version metadata.

## Phase 5 — Streaming and anomaly detection

- Define latency, replay, ordering, and delivery requirements first.
- Introduce Kafka and a single consumer/producer path only when justified.
- Start Spark in local mode for a measured processing requirement; bound its
  memory use and avoid running unrelated infrastructure concurrently.
- Validate anomaly rules/models against real historical behavior before
  notifying users.

**Exit criteria:** streaming behavior is observable, replayable where needed,
and tested against representative sourced events.

## Phase 6 — Scale and operations

- Add Hadoop/Hive only if measured historical analytics needs warrant it.
- Add containerization and CI checks for reproducible builds and tests.
- Document service startup order, resource limits, backups, and recovery.
- Review data licensing, privacy, access control, and retention requirements.

**Exit criteria:** deployment and recovery procedures are documented and
validated for the chosen operating environment.
