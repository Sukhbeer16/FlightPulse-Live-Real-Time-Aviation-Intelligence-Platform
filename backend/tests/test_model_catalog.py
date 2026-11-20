"""Tests for the model inventory endpoint."""

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services import model_catalog
from backend.app.services.delay_prediction import FEATURES


client = TestClient(app)


def test_model_catalog_reports_missing_artifacts_without_claiming_availability(
    monkeypatch, tmp_path
) -> None:
    model_directory = tmp_path / "processed" / "ml" / "phase4_2"
    model_directory.mkdir(parents=True)
    (model_directory / "experiment_manifest.json").write_text(
        json.dumps(
            {
                "features": {"allowlist": FEATURES},
                "model_selection": {
                    "selected_candidate": "logistic_regression_balanced"
                },
                "software_versions": {"scikit_learn": "unavailable"},
                "dataset": {"date_coverage": ["2024-01-01", "2024-02-29"]},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        model_catalog,
        "get_settings",
        lambda: SimpleNamespace(data_directory=tmp_path),
    )

    response = client.get("/api/v1/models")

    assert response.status_code == 200
    body = response.json()
    assert body["data_kind"] == "model_catalog"
    models = {item["model_id"]: item for item in body["models"]}
    assert len(models) == 5
    assert all(item["status"] == "unavailable" for item in models.values())
    assert models["isolation-forest"]["task"] == "anomaly_detection"
    assert "No trained Isolation Forest" in models["isolation-forest"]["reason"]


def test_model_catalog_treats_malformed_manifest_as_unavailable(
    monkeypatch, tmp_path
) -> None:
    model_directory = tmp_path / "processed" / "ml" / "phase4_2"
    model_directory.mkdir(parents=True)
    (model_directory / "experiment_manifest.json").write_text(
        json.dumps({"features": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        model_catalog,
        "get_settings",
        lambda: SimpleNamespace(data_directory=tmp_path),
    )

    response = client.get("/api/v1/models")

    assert response.status_code == 200
    assert all(
        model["status"] == "unavailable"
        for model in response.json()["models"]
    )
