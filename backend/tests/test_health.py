"""Tests for the API health endpoint."""

import pytest
from fastapi.testclient import TestClient

from backend.app.config.settings import Settings
from backend.app.main import app

client = TestClient(app)


def test_settings_are_loaded_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Application settings honor environment-provided values."""
    monkeypatch.setenv("APP_NAME", "FlightPulse Test API")
    monkeypatch.setenv("CORS_ORIGINS", '["https://ui.example.test"]')

    settings = Settings(_env_file=None)

    assert settings.app_name == "FlightPulse Test API"
    assert settings.cors_origins == ["https://ui.example.test"]


def test_health_endpoint_returns_service_status() -> None:
    """The health endpoint exposes the configured service metadata."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "FlightPulse Live API",
        "version": "0.1.0",
        "environment": "development",
    }


def test_versioned_health_endpoint_is_available() -> None:
    """Health checks are also available under the configured API prefix."""
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_database_health_failure_uses_safe_error_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Database health failures do not expose the database URL or driver error."""
    from backend.app.api import routes

    class UnavailableEngine:
        def connect(self):
            raise RuntimeError("private connection details")

    monkeypatch.setattr(routes, "get_engine", lambda: UnavailableEngine())
    response = client.get("/api/v1/health/database")

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "service_unavailable",
            "message": "Database unavailable.",
            "details": None,
        }
    }
    assert "private connection details" not in response.text


def test_database_health_success_checks_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.api import routes

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, statement):
            assert str(statement) == "SELECT 1"

    class Engine:
        def connect(self):
            return Connection()

    monkeypatch.setattr(routes, "get_engine", lambda: Engine())
    response = client.get("/api/v1/health/database")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}


def test_validation_errors_use_consistent_envelope_without_echoing_value() -> None:
    """Validation responses expose field locations but not raw submitted values."""
    response = client.get("/api/v1/flights?page=0")

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    assert body["message"] == "Request validation failed."
    assert body["details"][0]["location"] == ["query", "page"]
    assert "input" not in body["details"][0]


def test_cors_allows_vite_post_preflight() -> None:
    response = client.options(
        "/api/v1/intelligence/delay-predictions",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "POST" in response.headers["access-control-allow-methods"]
