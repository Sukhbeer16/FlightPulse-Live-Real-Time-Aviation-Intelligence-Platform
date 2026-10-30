# FlightPulse Live

FlightPulse Live is an incremental aviation intelligence platform for live
aircraft tracking, historical flight-data processing, delay prediction,
anomaly detection, and disruption analysis.

The initial version is deliberately small: a FastAPI health endpoint and a
React frontend that checks the backend. Kafka, Spark, Hadoop, PostgreSQL, and
ML dependencies are not installed or started by default. Add each component
only when its development phase requires it, which keeps the local setup
practical on an 8 GB laptop.

## Project layout

```text
backend/
  app/
    api/                 Versioned HTTP API
    config/              Environment-backed settings
    data_ingestion/      Flight data source integrations
    data_processing/     Batch and streaming transformations
    feature_engineering/ Features derived from flight and airport data
    machine_learning/    Training, evaluation, and inference
    streaming/           Streaming application integrations
    anomaly_detection/   Operational anomaly detection
    database/            Persistence and database integrations
    main.py              FastAPI application
  tests/
pipelines/
  ingestion/            BTS download, validation, cleaning, and features
tests/                  Data pipeline unit/integration tests
data/
  raw/                   Ignored original archives and CSVs
  processed/             Ignored derived Parquet files
docs/
  architecture.md
  data_dictionary.md
  data_quality_report.md
  development-roadmap.md
notebooks/
  01_historical_data_exploration.ipynb
frontend/
  src/
```

## Requirements

- Python 3.11
- Node.js 20 LTS or newer, with npm
- Windows PowerShell (commands below use PowerShell syntax)

The API and frontend run without credentials, flight data, or infrastructure
services. The historical-data pipeline requires the official BTS download or
a manually exported BTS CSV.

## Setup

From the repository root:

```powershell
Copy-Item .env.example .env
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

If PowerShell blocks virtual-environment activation, use
`.\.venv\Scripts\python.exe` in place of `python` in the commands below.

Install frontend dependencies independently:

```powershell
Set-Location frontend
npm install
Set-Location ..
```

## Run the applications

Start the backend in one terminal from the repository root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

The API is available at `http://127.0.0.1:8000`; its health endpoint is
`http://127.0.0.1:8000/health` and interactive API documentation is at
`http://127.0.0.1:8000/docs`.

Start the frontend in a second terminal:

```powershell
Set-Location frontend
npm run dev
```

Open the Vite URL printed in the terminal (normally `http://localhost:5173`).
The frontend health check uses `VITE_API_BASE_URL` from `frontend/.env.local`
if set, and otherwise checks `http://127.0.0.1:8000`.

## Verify

Run backend tests from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Check the frontend production build:

```powershell
Set-Location frontend
npm run build
```

## Phase 2 — BTS January 2024 historical data

The pipeline uses the official BTS On-Time Reporting Carrier On-Time
Performance monthly archive for January 2024. The archive and extracted CSV are
preserved under ignored `data/raw/`; cleaned, Zstandard-compressed Parquet is
written under ignored `data/processed/`. A JSON provenance sidecar records the
source, acquisition time, and SHA-256 checksums. Processing uses 50,000-row
chunks by default and stores exact-duplicate tracking on disk.

Install the pipeline dependencies from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Download and retain the official BTS archive and CSV:

```powershell
.\.venv\Scripts\python.exe -m pipelines.ingestion.bts_ingestion download
```

The repository includes a data-quality-report starter file. Process the CSV
and explicitly replace that starter with measured results:

```powershell
.\.venv\Scripts\python.exe -m pipelines.ingestion.bts_ingestion process --overwrite
```

One command can download and process; `--overwrite` is needed when generated
outputs already exist:

```powershell
.\.venv\Scripts\python.exe -m pipelines.ingestion.bts_ingestion all --overwrite
```

If automated downloading is unavailable or too slow, visit the
[BTS TranStats website](https://www.transtats.bts.gov/), open **On-Time :
Reporting Carrier On-Time Performance (1987-present)**, select year **2024**
and month **January**, and export/download the CSV. Then import and process it
without changing the original:

```powershell
.\.venv\Scripts\python.exe -m pipelines.ingestion.bts_ingestion process --input "C:\path\to\the\downloaded.csv" --overwrite
```

The pipeline copies a manually supplied CSV into `data/raw/` without
overwriting a different file of the same name. Its provenance sidecar records
manual import and clearly marks that the source was operator-supplied rather
than independently verified. An interrupted automated archive download keeps
its `.part` file; rerunning `download` attempts an HTTP range resume.

After processing, the measured quality report is at
[`docs/data_quality_report.md`](docs/data_quality_report.md), the data
dictionary is at [`docs/data_dictionary.md`](docs/data_dictionary.md), and
tables/plots are under the ignored `reports/eda/2024-01/` directory. Open
[`notebooks/01_historical_data_exploration.ipynb`](notebooks/01_historical_data_exploration.ipynb)
in VS Code to inspect those measured outputs. No dataset, statistics, or
notebook output is fabricated or committed.

Run the pipeline tests with:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## DVC — processed BTS dataset

The January 2024 Parquet dataset is versioned with DVC metadata while the
dataset itself remains ignored by Git. Install the development tools and
initialize DVC only once per clone:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\dvc.exe init
.\.venv\Scripts\dvc.exe add data/processed/bts_ontime_2024_01.parquet
```

Commit `.dvc/`, `data/processed/bts_ontime_2024_01.parquet.dvc`, and
`.gitignore`; do not force-add the Parquet binary. Check the tracked dataset
state with:

```powershell
.\.venv\Scripts\dvc.exe status
.\.venv\Scripts\dvc.exe diff
```

DVC stores content-addressed copies in the local `.dvc/cache/` directory by
default. This local cache is ignored and is not shared with GitHub. To make
the data available to other machines, configure an authenticated DVC remote
storage location in a later setup, push the cache with `dvc push`, and restore
it on a clone with `dvc pull` (or `dvc checkout` after the DVC cache has been
obtained). Until a shared remote is configured, a fresh clone has the DVC
pointer but cannot restore the Parquet content.

## Configuration

Copy `.env.example` to `.env` and adjust values for local development.
Settings are validated by Pydantic Settings when the backend starts.
Frontend-specific variables belong in `frontend/.env.local`; do not put
secrets in frontend variables because Vite exposes them to browser code.

## Resource-conscious development

- Run the API and frontend first; they do not require infrastructure services.
- Use small, representative samples for data-processing work and avoid
  committing datasets or trained model files.
- Begin with local Python processing. Adopt Spark local mode only when the
  workload benefits from it.
- Introduce PostgreSQL, Kafka, Spark, and Hadoop/Hive individually, and stop
  each service when it is not in use. See the [development roadmap](docs/development-roadmap.md)
  and [architecture](docs/architecture.md).

## Data and credentials

Do not commit credentials, `.env` files, raw or processed datasets, or trained
model binaries. Obtain flight data only from an appropriately licensed source
and document its provenance and permitted use before integrating it.
