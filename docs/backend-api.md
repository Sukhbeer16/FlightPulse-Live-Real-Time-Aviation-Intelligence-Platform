# FlightPulse backend API

The API is served by `backend.app.main:app` and exposes versioned routes at
`/api/v1`. OpenAPI and Swagger UI are available at `/openapi.json` and `/docs`.
The configured Vite origins are `http://localhost:5173` and
`http://127.0.0.1:5173`; GET and POST are allowed.

## Architecture and local setup

The FastAPI application registers versioned routers under `backend/app/api/v1`.
Routers validate requests and response schemas; SQLAlchemy sessions are
request-scoped, while historical Parquet and saved model artifacts are read by
bounded service functions. PostgreSQL/PostGIS stores catalogs, operational
flights, and versioned BTS reference releases. BTS reference imports are kept
separate from historical flight ingestion.

Use Python 3.11 from the repository root. Create a virtual environment only if
one is not already available, then install the existing dependencies:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip check
```

Configure the ignored root `.env` with `DATABASE_URL`, for example
`postgresql+psycopg://<user>:<password>@localhost:5432/flightpulse`. Optional
OpenSky credentials are `OPENSKY_CLIENT_ID` and `OPENSKY_CLIENT_SECRET`; without
them the service uses anonymous access. Never commit `.env` or credentials.

Start PostgreSQL, ensure PostGIS is installed, and enable/check the extension
once in the `flightpulse` database:

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
SELECT PostGIS_Full_Version();
```

Inspect and apply pending migrations without dropping the database:

```powershell
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic heads
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Import each verified BTS reference archive through the existing transactional
importer (each dataset commits independently):

```powershell
@'
from sqlalchemy.orm import Session
from backend.app.database.session import get_engine
from backend.app.data_ingestion.bts_reference_csv import (
    CARRIER_DECODE_DATASET,
    MASTER_COORDINATE_DATASET,
)
from backend.app.data_ingestion.bts_reference_importer import import_reference_zip

engine = get_engine()
for archive, dataset in (
    ("data/reference/Carrier_Decode.zip", CARRIER_DECODE_DATASET),
    ("data/reference/Master_Coordinate.zip", MASTER_COORDINATE_DATASET),
):
    with Session(engine) as session:
        print(import_reference_zip(session, archive, dataset))
engine.dispose()
'@ | .\.venv\Scripts\python.exe -
```

## Health and catalogs

| Method and path | Purpose |
|---|---|
| `GET /health` | Process liveness metadata. |
| `GET /api/v1/health` | Versioned liveness metadata. |
| `GET /api/v1/health/database` | Executes a lightweight `SELECT 1`; does not expose the database URL. |
| `GET /api/v1/flights` | Operational flight search, database filtered and paginated. |
| `GET /api/v1/flights/{flight_id}` | Operational flight detail. |
| `GET /api/v1/airlines` | Paginated airline catalog search. |
| `GET /api/v1/airlines/{airline_code}` | Airline detail. |
| `GET /api/v1/airports` | Paginated airport catalog search. |
| `GET /api/v1/airports/{iata_code}` | Airport detail. |
| `GET /api/v1/models` | Saved model availability, feature contract, and evaluation metadata. |
| `POST /api/v1/predictions/delay?model=random-forest` | Run a selected saved supervised delay model. |
| `POST /api/v1/intelligence/delay-predictions/{model_name}` | Named logistic, random forest, decision tree or XGBoost inference. |
| `POST /api/v1/intelligence/anomalies` | Statistical outlier inference from the saved Isolation Forest. |
| `POST /api/v1/anomalies` | Short alias for anomaly inference. |
| `POST /api/v1/intelligence/risk` | Transparent combined risk assessment. |
| `POST /api/v1/risk` | Short alias for risk assessment. |
| `POST /api/v1/alerts/evaluate` | Create an explicitly labeled demonstration alert. |
| `GET /api/v1/alerts` | Filter and paginate demonstration alerts. |
| `GET /api/v1/live/flights` | Frontend alias for bounded live OpenSky state vectors. |
| `GET /api/v1/live/identity-match` | Safe historical callsign/flight-number candidate matching. |

Example operational search:

```text
GET /api/v1/flights?page=1&page_size=20&airline_code=UA&origin=EWR&flight_date=2024-02-01
```

404, validation, and service errors use an `error` envelope. Validation details
omit raw submitted values.

## Historical BTS records and aggregates

`GET /api/v1/historical/flights` and
`GET /api/v1/historical/flights/{flight_id}` query the dedicated
`historical_bts_flights` tables. Filters include `airline_code`, `origin`,
`destination`, `date_from`, `date_to`, `cancelled`, `diverted`, and
`delayed` (arrival delay greater than 15 minutes). Times remain BTS local HHMM
values. The separate BTS reference import does not populate these flight rows;
until historical flight ingestion is implemented, the response may be empty.

`GET /api/v1/historical/processed-flights` streams the available February 2024
processed BTS Parquet file in 4,096-row batches and supports paginated
flight-number, airline, route, date, cancellation, diversion, and delay
filters. It projects only response fields and retains only the requested page
in memory. Its `source_row_number` is a file-position reference, not a flight
identifier. Every time is labeled as source-local HHMM and is not converted to
UTC. The route scans the file on each request; it is suitable for this
development dataset, not a high-volume query service.

Supported Parquet filters include `flight_number` or `flight_identifier`,
`airline_code`, `origin`, `destination`, `flight_date`, `date_from`,
`date_to`, `cancelled`, `diverted`, `delayed`, `departure_delay_min/max`,
and `arrival_delay_min/max`. Sorting supports `source_row`, `flight_date`,
`flight_number`, `departure_delay`, and `arrival_delay`, with `asc` or `desc`.
Sorted requests use bounded temporary SQLite storage and do not retain the
complete matched dataset in API process memory.

The analytics endpoints read compact, precomputed Parquet aggregates under
`data/processed/analytics/`; they do not copy aggregate or flight history into
PostgreSQL. `GET /api/v1/analytics/overview` calculates overview totals from
`airline_analytics.parquet`. `GET /api/v1/analytics/{report}` supports:
`airlines`, `origin-airports`, `destination-airports`, `routes`, `hourly`,
`day-of-week`, and `delay-distribution`. Every response is labeled
`data_kind: historical_aggregate` and `source_period: 2024-01`.

## Live tracking

`GET /api/v1/live/states?lamin=40&lomin=-75&lamax=42&lomax=-72` fetches current
OpenSky state vectors for a bounded region (maximum 400 square degrees). The
endpoint optionally uses `OPENSKY_CLIENT_ID` and `OPENSKY_CLIENT_SECRET` from
`.env`; without them it uses the provider's anonymous access. Upstream timeouts,
authorization failures, malformed responses, and rate limits return a
structured 503; rate-limit retry information is passed in `Retry-After` when
provided. Responses are cached per region for at most 10 seconds (bounded to
eight regions and 2,000 state vectors each). These ADS-B/Mode S observations
are not confirmed commercial flight schedules, delay labels, destinations, or
airline operational states. A callsign by itself is not used as a unique
flight identity.

## Predictions, anomalies, and alerts

`GET /api/v1/models` reports the saved Phase 4.2 Logistic Regression, Random
Forest, Decision Tree, and XGBoost artifacts when their binaries, runtime
versions, and 21-feature input ordering validate. Logistic Regression, Random
Forest, Decision Tree, and XGBoost expose shared delay-prediction inference
routes. The saved Isolation Forest is available for statistical outlier
inference, trained reproducibly on 100,000 approved 21-feature rows.

`POST /api/v1/intelligence/delay-predictions` accepts pre-departure route,
date, scheduled local HHMM, elapsed-time, and distance fields. It lazily loads
the saved Phase 4.2 logistic-regression artifact only when requested, verifies
its declared scikit-learn version and feature contract, and returns an
uncalibrated relative model score for BTS arrival delay greater than 15
minutes. The model was trained on January-February 2024. Its held-out test
recall was 0.0590 at threshold 0.5, so this score is not operationally
validated. The response includes the top five signed logistic-logit feature
contributions; they explain the fitted association for this input, not causes.
Missing or incompatible artifacts return `status: unavailable`; no model is
retrained.

`POST /api/v1/intelligence/anomalies` runs the saved Isolation Forest and
returns a relative statistical outlier score. It is not calibrated as an
aviation emergency, disruption, or confirmed incident detector.

`POST /api/v1/intelligence/risk` combines 60 percent of the selected Logistic
Regression delay score, documented observed-arrival-delay points, and 15
percent of an optional anomaly score. Its thresholds are low below 40,
medium from 40 to below 70, high from 70 to below 85, and elevated from 85
to 100. These categories describe model evidence, not confirmed operational
disruption.

`POST /api/v1/alerts/evaluate` and `GET /api/v1/alerts` create and retrieve
explicit `demonstration` alerts only. No live provider feed or fake live alert
is generated. OpenSky squawk values remain observed fields and are never used
as emergency evidence.

## Catalog lookups and identity matching

Canonical airline and airport lookup tables were populated only from verified
source fields. Carrier rows require a non-ambiguous 2- or 3-character source
`CARRIER` value and matching `CARRIER_NAME`. Master Coordinate rows require
`AIRPORT_IS_LATEST=1` and a source name. Airport IATA/ICAO columns remain null;
a BTS airport code is not represented as IATA or ICAO. Latitudes and longitudes
are stored as PostGIS points only when valid numeric source fields are present.

`GET /api/v1/live/identity-match` parses callsign format and searches the
February 2024 historical Parquet for an exact airline/flight-number/date
candidate. A single route candidate receives `medium` confidence; multiple
routes receive `uncertain` and are rejected. This is an historical candidate
match, not a live schedule or aircraft identity confirmation.

## Run locally

From the repository root, configure the ignored `.env`, start PostgreSQL, then
run:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

Visit `http://127.0.0.1:8000/docs` for interactive Swagger documentation.
Run the backend tests with:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -q
```
