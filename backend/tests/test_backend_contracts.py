"""Focused contracts for backend endpoints that do not need a database."""

import io
import json
from urllib.error import HTTPError
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app.api.v1 import analytics
from backend.app.main import app
from backend.app.schemas.intelligence import DelayPredictionRequest
from backend.app.services import opensky
from backend.app.services.delay_prediction import FEATURES, _feature_row
from backend.app.services import processed_historical
from backend.app.services import alerts


client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_opensky_cache():
    opensky.clear_state_cache()
    yield
    opensky.clear_state_cache()


def test_historical_analytics_report_is_labeled_and_uses_compact_data(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        analytics,
        "get_historical_report",
        lambda report: [{"route": "JFK-LAX", "total_flights": 42}],
    )

    response = client.get("/api/v1/analytics/routes")

    assert response.status_code == 200
    assert response.json() == {
        "data_kind": "historical_aggregate",
        "report": "routes",
        "source_period": "2024-01",
        "data": [{"route": "JFK-LAX", "total_flights": 42}],
    }


def test_anomaly_contract_and_demo_alert_listing_do_not_fabricate_data() -> None:
    alerts.clear_alerts()
    anomaly = client.get("/api/v1/intelligence/anomalies")
    alert_response = client.get("/api/v1/alerts")

    assert anomaly.status_code == alert_response.status_code == 200
    assert anomaly.json()["status"] == "unavailable"
    assert anomaly.json()["reason"]
    assert alert_response.json()["data_kind"] == "operational_alerts"
    assert alert_response.json()["data"] == []


def test_live_state_endpoint_rejects_expensive_global_area_before_upstream() -> None:
    response = client.get(
        "/api/v1/live/states?lamin=-90&lomin=-180&lamax=90&lomax=180"
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_prediction_rejects_invalid_hhmm_without_loading_model() -> None:
    response = client.post(
        "/api/v1/intelligence/delay-predictions",
        json={
            "reporting_airline": "AA",
            "origin": "JFK",
            "destination": "LAX",
            "flight_date": "2024-02-01",
            "scheduled_departure_hhmm": 1260,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_opensky_normalizes_state_vector_without_scheduling_claims(monkeypatch) -> None:
    state = [
        "abc123",
        "UAL123  ",
        "United States",
        1_700_000_000,
        1_700_000_001,
        -73.78,
        40.64,
        10_000.0,
        False,
        230.0,
        270.0,
        -1.0,
        None,
        10_300.0,
        "1234",
        False,
        0,
        2,
    ]

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    monkeypatch.setattr(opensky, "_access_token", lambda: None)
    monkeypatch.setattr(
        opensky,
        "urlopen",
        lambda request, timeout: Response(
            json.dumps({"time": 1_700_000_002, "states": [state]}).encode()
        ),
    )

    source_time, states = opensky.get_live_states(
        lamin=40, lomin=-75, lamax=42, lomax=-72
    )

    assert source_time == 1_700_000_002
    assert states[0].icao24 == "abc123"
    assert states[0].longitude == -73.78
    assert states[0].category == 2


def test_opensky_propagates_upstream_rate_limit_retry(monkeypatch) -> None:
    monkeypatch.setattr(opensky, "_access_token", lambda: None)

    def rate_limited(*args, **kwargs):
        raise HTTPError(
            opensky.API_URL,
            429,
            "rate limited",
            {"X-Rate-Limit-Retry-After-Seconds": "75"},
            None,
        )

    monkeypatch.setattr(opensky, "urlopen", rate_limited)
    try:
        opensky.get_live_states(lamin=40, lomin=-75, lamax=42, lomax=-72)
    except opensky.OpenSkyUnavailable as error:
        assert error.retry_after == "75"
    else:
        raise AssertionError("OpenSky rate limit was not reported.")


def test_opensky_refreshes_once_after_expired_authenticated_token(monkeypatch) -> None:
    responses = iter(("old-token", "new-token"))
    seen_authorizations = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    def urlopen(request, timeout):
        seen_authorizations.append(request.headers.get("Authorization"))
        if len(seen_authorizations) == 1:
            raise HTTPError(opensky.API_URL, 401, "expired", {}, None)
        return Response(json.dumps({"time": 123, "states": []}).encode())

    monkeypatch.setattr(opensky, "_access_token", lambda: next(responses))
    monkeypatch.setattr(opensky, "urlopen", urlopen)

    source_time, states = opensky.get_live_states(
        lamin=40, lomin=-75, lamax=42, lomax=-72
    )

    assert source_time == 123
    assert states == []
    assert seen_authorizations == ["Bearer old-token", "Bearer new-token"]


def test_prediction_features_match_saved_training_contract() -> None:
    request = DelayPredictionRequest(
        reporting_airline="aa",
        origin="jfk",
        destination="lax",
        flight_date="2024-02-01",
        scheduled_departure_hhmm=2400,
        scheduled_arrival_hhmm=None,
        scheduled_elapsed_time_minutes=330,
        distance_miles=None,
    )
    medians = {
        "month": 1,
        "day_of_month": 11,
        "day_of_week": 3,
        "scheduled_departure_sin": -0.2,
        "scheduled_departure_cos": -0.4,
        "scheduled_arrival_sin": -0.3,
        "scheduled_arrival_cos": -0.5,
        "scheduled_elapsed_time_minutes": 130,
        "distance_miles": 690,
    }
    row = _feature_row(
        request,
        {"preprocessing": {"upstream_imputation": {"medians": medians}}},
    )

    assert set(row) == set(FEATURES)
    assert row["Reporting_Airline"] == "AA"
    assert row["Origin"] == "JFK"
    assert row["scheduled_departure_sin"] == 0
    assert row["scheduled_departure_cos"] == 1
    assert row["scheduled_arrival_cos"] == -0.5
    assert row["is_missing_scheduled_arrival_sin"] == 1
    assert row["distance_miles"] == 690
    assert row["is_missing_distance_miles"] == 1


def test_processed_parquet_search_streams_and_preserves_local_times(
    monkeypatch, tmp_path
) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    source_directory = tmp_path / "processed" / "monthly"
    source_directory.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "FlightDate": [
                    datetime(2024, 2, 1),
                    datetime(2024, 2, 1),
                    datetime(2024, 2, 2),
                ],
                "Reporting_Airline": ["AA", "UA", "AA"],
                "Origin": ["JFK", "EWR", "JFK"],
                "Dest": ["LAX", "SFO", "LAX"],
                "Flight_Number_Reporting_Airline": ["001", "2", "003"],
                "CRSDepTime": [2400, 930, 15],
                "DepTime": [None, 945, 30],
                "CRSArrTime": [300, 1200, 330],
                "ArrTime": [None, 1215, 400],
                "DepDelay": [None, 15.0, 15.0],
                "ArrDelay": [None, 10.0, 20.0],
                "Cancelled": [1, 0, 0],
                "Diverted": [0, 0, 0],
                "CancellationCode": ["A", None, None],
            }
        ),
        source_directory / processed_historical.SOURCE_FILE,
    )
    monkeypatch.setattr(
        processed_historical,
        "get_settings",
        lambda: SimpleNamespace(data_directory=tmp_path),
    )

    flights, total = processed_historical.search_processed_flights(
        page=1, page_size=10, airline_code="aa", delayed=True
    )

    assert total == 1
    assert flights[0].source_row_number == 3
    assert flights[0].flight_number == "003"
    assert flights[0].scheduled_departure_local_hhmm == 15
    assert flights[0].arrival_delay_minutes == 20.0
    assert flights[0].data_kind == "historical_bts"
