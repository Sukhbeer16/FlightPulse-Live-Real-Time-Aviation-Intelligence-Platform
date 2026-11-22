# FlightPulse local architecture

## Feature-to-file map

| Dashboard or service | Entry point | Data and evidence |
|---|---|---|
| Overview | frontend/src/features/intelligence/IntelligenceDashboard.tsx | January BTS aggregates, historical record drawer, labelled sample series |
| Live Tracking | frontend/src/pages/LiveTrackingPage.tsx | Independent historical and OpenSky requests, MapLibre and Three.js views |
| Delay Prediction | frontend/src/features/intelligence/DelayPredictionTool.tsx | Four selectable saved model pipelines behind POST /api/v1/predictions/delay |
| Anomaly Detection and Disruption Intelligence | frontend/src/features/intelligence/HistoricalAssessment.tsx | Eligible BTS row, scheduled features, observed delay, Isolation Forest and operational risk factors |
| Historical Analytics | frontend/src/pages/HistoricalAnalyticsPage.tsx and frontend/src/features/tracker/HistoricalSearch.tsx | January reports and searchable January/February source files |
| Alerts | backend/app/services/alerts.py and frontend/src/features/alerts/AlertsCenter.tsx | Explicitly requested demonstration assessments, in-memory for the current API process |
| Assistant | frontend/src/pages/AssistantPage.tsx | Planned feature |
| Settings and System Status | frontend/src/pages/SettingsPage.tsx and frontend/src/pages/SystemStatusPage.tsx | API location, backend connectivity, provider and stream status |
| Historical API | backend/app/services/processed_historical.py | DuckDB reads local Parquet with parameterized filters, deterministic sorting, source filename and stable one-based row number |
| Provider API | backend/app/services/opensky.py and backend/app/api/v1/live.py | Server-side OAuth, bounded snapshots, source time and provider state |
| Streaming | backend/app/streaming/{producer,event,job,store}.py | OpenSky → Kafka → Spark → SQLite → FastAPI → System Status |
| Catalog | backend/app/database and backend/alembic/versions | PostgreSQL and PostGIS, migrations through 0006_bts_ref_lifecycle |
| Batch and ML | pipelines, backend/app/services/{delay_prediction,anomaly_detection,risk_intelligence}.py | Existing BTS preparation, reports, 21-feature inference and risk explanation |

The historical and streaming paths can run independently. Historical queries read the two source files in place and use at most two DuckDB threads per query. Each flight retains its original BTS airport codes. PostgreSQL serves the reference catalog. SQLite holds only streaming results, rejected inputs and consumer metrics. An OpenSky callsign match is a candidate, and schedule-based models require schedule data.

## Start and stop from PowerShell

Run commands from the repository root. On this checkout the repaired interpreter is .venv/Scripts/python.exe. For a fresh installation, use Python 3.11 and install requirements.txt, requirements-dev.txt and requirements-streaming.txt in the local environment. Install frontend packages with npm ci in frontend. Copy .env.example to .env only for a fresh setup and supply the actual local database connection. Preserve an existing .env.

1. On the database host, start its existing PostgreSQL 18 service from an elevated PowerShell. Run the health request after starting FastAPI.

   ~~~powershell
   Get-Service *postgres*
   Start-Service postgresql-x64-18
   Invoke-RestMethod http://127.0.0.1:8000/api/v1/health/database
   ~~~

2. Start Kafka in its own terminal. These paths match the test installation. Set them to the extracted distributions when using another machine.

   ~~~powershell
   $env:KAFKA_HOME="$env:TEMP/kafka_2.13-4.0.1"
   $env:JAVA_HOME="$env:TEMP/jdk-21.0.13.1+2"
   .\scripts\kafka.ps1 start
   ~~~

3. In the Spark terminal, initialize topics and start the consumer. The first run downloads the matching Maven connector.

   ~~~powershell
   $env:KAFKA_HOME="$env:TEMP/kafka_2.13-4.0.1"
   $env:JAVA_HOME="$env:TEMP/jdk-21.0.13.1+2"
   $env:HADOOP_HOME="$env:TEMP/flightpulse-native/hadoop-3.4.1"
   .\scripts\kafka.ps1 topics
   .\scripts\spark.ps1
   ~~~

4. In the backend terminal:

   ~~~powershell
   .\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
   ~~~

5. In the frontend terminal:

   ~~~powershell
   Set-Location frontend
   npm.cmd run dev -- --host 127.0.0.1 --strictPort
   ~~~

6. In the ingestion terminal, after configuring the OpenSky credentials:

   ~~~powershell
   .\.venv\Scripts\python.exe -m backend.app.streaming.producer --bounds 40 -75 42 -72 --interval 120
   ~~~

Open http://127.0.0.1:5173. Stop ingestion first with Ctrl+C, then Spark, Kafka, Vite and Uvicorn with Ctrl+C in each terminal. Stop a dedicated database service with Stop-Service postgresql-x64-18 when other applications have finished using it.
