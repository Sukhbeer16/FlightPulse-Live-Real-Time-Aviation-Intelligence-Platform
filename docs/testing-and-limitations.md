# Local verification and limitations

> The operations upgrade supersedes the earlier audit below. See [current implementation and verification](operations-upgrade.md). The latest backend run passed 98 tests, with the PostgreSQL-dependent catalog test excluded. The public ADS-B to Kafka to consumer to API path returned 144 fresh aircraft. The current Edge smoke check passed all routes and 149 map tile requests without page errors. Older results below describe the earlier audit.

## Runtime and repository

The supplied checkout was under the Vansh account. The copied .venv referenced a missing interpreter under the 6EIN account. The environment launcher was repaired with Python 3.11.15 and the existing Python 3.11 packages. The backed-up environment is already tracked by Git in this checkout. It was left intact. The audit did not create a commit or retrain a saved model.

Both Parquet files were readable. The February source had 519,221 rows, and January had 547,271. The combined search returned 1,066,492 rows. Compact January reports and five saved model artifacts were present. The repository contains six migrations ending at 0006_bts_ref_lifecycle. No local PostgreSQL service was visible and the configured server did not accept a connection. The installed server version, PostGIS extension, applied migration, 2,891/20,298 imported reference rows and 1,620/6,893 canonical records remain unverified here.

## Results

| Feature | Classification | Evidence |
|---|---|---|
| Frontend and 2D map | IMPLEMENTED AND VERIFIED | TypeScript and Vite build passed. Headless Edge received successful OSM tiles, loaded the roster and exercised the map switches. |
| Historical search | IMPLEMENTED AND VERIFIED | Both files queried locally. Browser selected date and origin, paginated filtered records, and rendered the recorded flight details. |
| Historical assessments and alerts | IMPLEMENTED AND VERIFIED | Selecting February source row 2 returned observed delay −29 minutes, logistic score 0.428, Isolation Forest score 58.59 and operational risk 34.44/100. Edge created and then listed an explicitly labelled demonstration alert. Alerts are held in the API process until restart. |
| Delay models | IMPLEMENTED AND VERIFIED | Browser submissions returned logistic regression 0.421225, decision tree 0.118303, random forest 0.185522 and XGBoost 0.197874 for the form inputs. The random forest uses one worker for inference after Windows rejected a multiprocessing pipe in the restricted environment. |
| Provider client and API | IMPLEMENTED BUT NOT EXTERNALLY VERIFIED | Tests exercise normalization, duplicates, invalid coordinates, token reuse/expiry, retry on 401, rate limits and cache hits. |
| Authenticated live aircraft and last update | BLOCKED BY MISSING CREDENTIALS OR DATA | Both backend credential settings were empty. No authenticated response, aircraft count or successful update timestamp can be reported. Physical aircraft rendering in 2D/3D remains externally unverified. |
| Kafka | IMPLEMENTED AND VERIFIED | Single-node KRaft broker started, all three topics were created, labelled events received acknowledgements, and the broker restarted with existing storage. |
| Spark and API integration | IMPLEMENTED AND VERIFIED | Checkpoint 0 consumed a simulation. After restart, offsets 1 and 2 contained a duplicate and a malformed record. Checkpoint 1 committed with one original observation and one rejected offset. A later labelled run returned two unique observations, mean speed 150 m/s and peak absolute vertical rate 31 m/s through FastAPI. OpenSky output stayed separate. |
| PostgreSQL catalog | BLOCKED BY MISSING CREDENTIALS OR DATA | Configured PostgreSQL instance unavailable on this host. Catalog contents could not be confirmed. |
| Live schedule-derived disruption or emergency confirmation | NOT IMPLEMENTED | OpenSky provides no authoritative schedule or incident feed. Movement flags and historical risk factors have separate meanings. |
| Aviation Assistant and Phase 4.5 | NOT IMPLEMENTED | Assistant placeholder retained. ML comparison, tuning and final selection remain deferred. |

## Test commands

Run from the project root. Spark batch tests require JAVA_HOME and HADOOP_HOME as described in spark-streaming.md. Include both bin directories on PATH and set PYSPARK_PYTHON to the project interpreter.

~~~powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
.\.venv\Scripts\python.exe -m pytest tests -q
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe scripts/browser_smoke.py
.\.venv\Scripts\python.exe -m scripts.stream_smoke publish
.\scripts\spark.ps1 -Once
.\.venv\Scripts\python.exe -m scripts.stream_smoke verify
~~~

The final Edge run passed all ten routes and received 73 successful OSM tile responses. It forced a historical request failure, retried successfully, checked the 3D orbital view, and observed the missing-credentials state. Across Kafka offsets 0 through 6, seven test records produced four unique SIMULATION observations and one quarantined malformed record. The remaining two inputs were duplicates.

The browser script requires Playwright for Python and Microsoft Edge. Start Vite and FastAPI before running it. The streaming check requires a running broker, initialized topics and FastAPI. Run one Spark consumer per checkpoint. The smoke check writes only SIMULATION records and a local test receipt.

The backend suite reported 89 passed and one failed. The failing test was test_bts_lookup_tables_have_defensible_source_values and requires the populated database. Starlette emitted a TestClient deprecation warning. All 96 separate data-pipeline tests passed. On Windows Spark emitted shutdown-hook warnings about locked temporary JAR directories after successful checkpoint commits. No cleanup of unrelated temporary directories was attempted.

## Browser coverage

- Overview displayed historical KPIs and allowed inspection of a BTS row. Historical Analytics displayed the January report and filtered, paginated records.
- Live Tracking loaded the historical roster and the keyless map, opened its filters, and switched views. The request failure/retry path is covered in scripts/browser_smoke.py. Authenticated marker movement remains blocked.
- Delay Prediction exercised all four supervised models. Anomaly Detection and Disruption Intelligence both displayed inference results for different selected historical rows.
- Alerts displayed the demonstration alert. Settings and System Status rendered configuration and connectivity information. The Assistant rendered its planned-feature screen.
- Smoke coverage verifies the named interactions. It does not constitute a load test or a measured memory ceiling for simultaneous services.
