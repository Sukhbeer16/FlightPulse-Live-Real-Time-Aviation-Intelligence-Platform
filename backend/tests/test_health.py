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
