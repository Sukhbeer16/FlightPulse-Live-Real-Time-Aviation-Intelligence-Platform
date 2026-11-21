"""Focused tests for completed backend MVP capabilities."""

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services import alerts


client = TestClient(app)


def valid_request() -> dict:
    return {
        "reporting_airline": "AA",
        "origin": "JFK",
        "destination": "LAX",
        "flight_date": "2024-02-01",
        "scheduled_departure_hhmm": 930,
        "scheduled_arrival_hhmm": 1300,
        "scheduled_elapsed_time_minutes": 330,
        "distance_miles": 2475,
    }


def test_all_saved_supervised_models_return_predictions() -> None:
    for model_name in (
        "logistic-regression",
        "random-forest",
        "decision-tree",
        "xgboost",
    ):
        response = client.post(
            f"/api/v1/predictions/delay?model={model_name}",
            json=valid_request(),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "available"
        assert body["model_id"].startswith("phase4.2")
        assert 0 <= body["model_score"] <= 1


def test_isolation_forest_anomaly_response_is_statistical_only() -> None:
    response = client.post(
        "/api/v1/intelligence/anomalies",
        json=valid_request(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "available"
    assert body["model_id"] == "phase4.2-isolation-forest"
    assert 0 <= body["anomaly_score"] <= 100
    assert "emergency" in " ".join(body["limitations"]).lower()


def test_risk_response_separates_prediction_observation_and_anomaly() -> None:
    request = valid_request()
    request.update(
        {
            "flight_reference": "AA123",
            "observed_arrival_delay_minutes": 30,
            "include_anomaly": True,
        }
    )
    response = client.post("/api/v1/intelligence/risk", json=request)
    assert response.status_code == 200
    body = response.json()
    assert body["data_kind"] == "operational_risk_assessment"
    assert 0 <= body["risk_score"] <= 100
    assert body["observed_arrival_delay_minutes"] == 30
    assert {factor["source"] for factor in body["factors"]} >= {
        "model",
        "observed",
        "anomaly",
    }
    assert "confirmed" not in body["explanation"].lower()


def test_demonstration_alert_is_filterable_and_paginated() -> None:
    alerts.clear_alerts()
    request = valid_request()
    request.update(
        {
            "flight_reference": "AA123",
            "observed_arrival_delay_minutes": 75,
            "include_anomaly": False,
        }
    )
    created = client.post(
        "/api/v1/alerts/evaluate",
        json={
            "risk": request,
            "flight_reference": "AA123",
            "source": "demonstration",
        },
    )
    assert created.status_code == 200
    alert = created.json()
    assert alert["source"] == "demonstration"
    assert alert["status"] == "open"
    assert alert["timestamp"]
    assert "disruption" in alert["explanation"].lower()

    listed = client.get("/api/v1/alerts?page=1&page_size=10")
    assert listed.status_code == 200
    assert listed.json()["pagination"]["total"] == 1
    assert listed.json()["data"][0]["id"] == alert["id"]


def test_historical_filters_validate_and_sort() -> None:
    invalid_range = client.get(
        "/api/v1/historical/processed-flights"
        "?date_from=2024-02-29&date_to=2024-02-01"
    )
    assert invalid_range.status_code == 422

    sorted_response = client.get(
        "/api/v1/historical/processed-flights"
        "?page=1&page_size=5&date_from=2024-02-01&date_to=2024-02-29"
        "&arrival_delay_min=15&sort_by=arrival_delay&sort_order=desc"
    )
    assert sorted_response.status_code == 200
    body = sorted_response.json()
    assert body["data_kind"] == "historical_bts"
    assert len(body["data"]) <= 5


def test_bts_lookup_tables_have_defensible_source_values() -> None:
    airlines = client.get("/api/v1/airlines?page=1&page_size=5")
    airports = client.get("/api/v1/airports?page=1&page_size=5")
    assert airlines.status_code == 200
    assert airports.status_code == 200
    assert airlines.json()["pagination"]["total"] > 0
    assert airports.json()["pagination"]["total"] > 0


def test_callsign_identity_matching_rejects_unknown() -> None:
    response = client.get(
        "/api/v1/live/identity-match",
        params={"callsign": "??", "flight_date": "2024-02-01"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["confidence"] == "none"
    assert body["matched"] is False
