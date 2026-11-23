"""Comprehensive tests for FlightPulse real-time ML feature engineering, inference, and Kafka integration.

Validates all 12 core requirements:
1. Feature transformation
2. Leakage prevention
3. Model loading
4. Model inference
5. Kafka message validation
6. Kafka producer
7. Kafka consumer
8. Prediction event schema
9. Invalid Kafka messages
10. Missing features
11. Model unavailable
12. End-to-end Kafka -> feature processing -> ML prediction -> prediction topic
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from backend.app.anomaly_detection.detector import AnomalyDetector, get_anomaly_detector
from backend.app.config.settings import Settings
from backend.app.feature_engineering.features import (
    CATEGORICAL_FEATURES,
    DEFAULT_TRAINING_MEDIANS,
    FEATURE_ALLOWLIST,
    LEAKAGE_DENYLIST,
    MISSING_INDICATOR_FEATURES,
    NUMERIC_FEATURES,
    TARGET_COLUMN,
    cyclic_time,
    extract_features_from_live_observation,
    extract_features_from_request,
    minutes_since_midnight,
    to_feature_dataframe,
    validate_feature_contract,
)
from backend.app.machine_learning.model_service import (
    MLModelService,
    ModelLoadError,
    get_model_service,
)
from backend.app.schemas.intelligence import DelayPredictionRequest
from backend.app.schemas.live import LiveStateVector
from backend.app.streaming import prediction_consumer, store
from backend.app.streaming.event import FlightPredictionEvent, Observation


def sample_live_observation(
    icao24: str = "a1b2c3",
    callsign: str = "AAL100",
    lat: float = 40.64,
    lon: float = -73.78,
    speed_mps: float = 210.0,
    vertical_rate_mps: float = 0.0,
    altitude_m: float = 3000.0,
    source: str = "adsb_lol",
    age: int = 5,
) -> Observation:
    now = int(time.time()) - age
    return Observation(
        version=1,
        source=source,
        source_time=now,
        state=LiveStateVector(
            icao24=icao24,
            callsign=callsign,
            origin_country="United States",
            time_position=now,
            last_contact=now,
            longitude=lon,
            latitude=lat,
            barometric_altitude_m=altitude_m,
            on_ground=False,
            velocity_mps=speed_mps,
            true_track_degrees=90.0,
            vertical_rate_mps=vertical_rate_mps,
            geometric_altitude_m=None,
            squawk="1200",
            spi=False,
            position_source=0,
            category=None,
        ),
    )


# 1. Feature Transformation Tests
def test_feature_transformation_contract_and_order() -> None:
    obs = sample_live_observation()
    features = extract_features_from_live_observation(obs)

    assert list(features.keys()) == list(FEATURE_ALLOWLIST)
    assert len(features) == 21
    assert features["Reporting_Airline"] == "AA"
    assert features["month"] >= 1 and features["month"] <= 12
    assert features["day_of_week"] >= 0 and features["day_of_week"] <= 6
    assert -1.0 <= features["scheduled_departure_sin"] <= 1.0
    assert -1.0 <= features["scheduled_departure_cos"] <= 1.0

    df = to_feature_dataframe([features])
    assert list(df.columns) == list(FEATURE_ALLOWLIST)
    assert df["Reporting_Airline"].dtype.name == "category"
    assert df["month"].dtype.name == "float32"
    assert df["is_missing_month"].dtype.name == "int8"


# 2. Leakage Prevention Tests
def test_leakage_prevention_rejects_leakage_and_metadata() -> None:
    validate_feature_contract(FEATURE_ALLOWLIST)

    for field in sorted(LEAKAGE_DENYLIST):
        with pytest.raises(ValueError, match="Prohibited fields"):
            validate_feature_contract([*FEATURE_ALLOWLIST[:-1], field])

    with pytest.raises(ValueError, match="Prohibited fields"):
        validate_feature_contract([*FEATURE_ALLOWLIST[:-1], "flight_date"])
    with pytest.raises(ValueError, match="Prohibited fields"):
        validate_feature_contract([*FEATURE_ALLOWLIST[:-1], "split"])
    with pytest.raises(ValueError, match="Prohibited fields"):
        validate_feature_contract([*FEATURE_ALLOWLIST[:-1], TARGET_COLUMN])


# 3. Model Loading Tests
def test_model_loading_and_caching() -> None:
    service = get_model_service()
    pipeline, manifest, threshold = service.load_model("logistic-regression")
    assert pipeline is not None
    assert manifest is not None
    assert 0.0 < threshold < 1.0

    # Ensure caching works without reloading file
    p2, _, _ = service.load_model("logistic-regression")
    assert p2 is pipeline

    # Dynamic best candidate selection
    best_name, best_thresh, meta = service.select_best_model()
    assert best_name in {"logistic-regression", "random-forest", "decision-tree", "xgboost"}
    assert meta["compared_count"] == 4


# 4. Model Inference Tests
def test_model_inference_probabilities_and_thresholding() -> None:
    service = get_model_service()
    req = DelayPredictionRequest(
        reporting_airline="AA",
        origin="JFK",
        destination="LAX",
        flight_date=date(2024, 2, 15),
        scheduled_departure_hhmm=900,
        scheduled_arrival_hhmm=1230,
        scheduled_elapsed_time_minutes=390.0,
        distance_miles=2475.0,
    )
    features = extract_features_from_request(req)
    result = service.predict_delay_probability(features, model_name="logistic-regression")

    assert result["prediction"] in (0, 1)
    assert result["predicted_class"] in ("delayed", "not_delayed")
    assert 0.0 <= result["delay_probability"] <= 1.0
    assert result["latency_ms"] >= 0.0

    contributions = service.compute_feature_contributions(features, model_name="logistic-regression")
    assert isinstance(contributions, list)


# 5. Kafka Message Validation Tests
def test_kafka_message_validation() -> None:
    obs = sample_live_observation()
    json_bytes = obs.model_dump_json().encode("utf-8")
    parsed = Observation.model_validate_json(json_bytes)
    assert parsed.state.icao24 == "a1b2c3"

    # Future timestamps exceeding 60s tolerance rejected
    future_data = json.loads(json_bytes.decode())
    future_data["source_time"] = int(time.time()) + 120
    with pytest.raises(ValueError, match="exceeds provider clock tolerance"):
        Observation.model_validate(future_data)


# 6. Kafka Producer Tests
def test_kafka_producer_publishing() -> None:
    mock_producer = MagicMock()
    mock_producer.flush.return_value = 0
    obs = sample_live_observation()
    from backend.app.streaming.producer import publish

    publish(mock_producer, "adsb_lol", obs.source_time, [obs.state])
    assert mock_producer.produce.call_count == 1
    call_args = mock_producer.produce.call_args[1]
    assert call_args["key"] == "a1b2c3"
    assert "adsb_lol" in call_args["value"]


# 7. Kafka Consumer Processing Tests
def test_kafka_prediction_consumer_processing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(store, "get_settings", lambda: SimpleNamespace(data_directory=tmp_path))
    obs = sample_live_observation(icao24="123456", callsign="DAL200")
    key = b"123456"
    value = obs.model_dump_json().encode("utf-8")

    event = prediction_consumer.process_message(key, value, partition=0, offset=1)
    assert event is not None
    assert event.flight_id == "123456"
    assert event.callsign == "DAL200"
    assert 0.0 <= event.delay_probability <= 1.0
    assert event.prediction in (0, 1)

    # Verify persisted in SQLite
    preds = store.latest_predictions(limit=10)
    assert len(preds) == 1
    assert preds[0]["flight_id"] == "123456"


# 8. Prediction Event Schema Validation Tests
def test_prediction_event_schema_contract() -> None:
    event = FlightPredictionEvent(
        flight_id="abcdef",
        timestamp=1708450000,
        prediction=1,
        predicted_class="delayed",
        delay_probability=0.742,
        threshold=0.161,
        model_id="phase4.2-logistic-regression",
        model_version="2026-11-22T00:00:00Z",
        prediction_timestamp="2026-11-22T10:00:00Z",
        latency_ms=1.45,
        callsign="UAL500",
        source="adsb_lol",
    )
    payload = json.loads(event.model_dump_json())
    assert payload["flight_id"] == "abcdef"
    assert payload["prediction"] == 1
    assert payload["delay_probability"] == 0.742
    assert payload["latency_ms"] == 1.45


# 9. Invalid Kafka Messages Handling Tests
def test_invalid_kafka_messages_quarantined_not_crashed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(store, "get_settings", lambda: SimpleNamespace(data_directory=tmp_path))

    # Malformed JSON
    event1 = prediction_consumer.process_message(b"bad", b"not-valid-json", 0, 10)
    assert event1 is None

    # Key mismatch
    obs = sample_live_observation()
    event2 = prediction_consumer.process_message(b"wrong_key", obs.model_dump_json().encode(), 0, 11)
    assert event2 is None

    # Verify rejections recorded in rejected table
    with sqlite3.connect(store.predictions_database()) as db:
        count = db.execute("SELECT count(*) FROM rejected_prediction_events").fetchone()[0]
        assert count == 2


# 10. Missing Features Handling Tests
def test_missing_features_imputation_and_indicators() -> None:
    # Live observation without route/schedule features
    obs = sample_live_observation(callsign="")
    features = extract_features_from_live_observation(obs)

    # Missing categories are replaced with __MISSING__
    assert features["Reporting_Airline"] == "__MISSING__"
    assert features["Origin"] == "__MISSING__"
    assert features["Dest"] == "__MISSING__"

    # Missing numerics are imputed with training medians, with is_missing_* = 1
    assert features["distance_miles"] == DEFAULT_TRAINING_MEDIANS["distance_miles"]
    assert features["is_missing_distance_miles"] == 1
    assert features["is_missing_scheduled_elapsed_time_minutes"] == 1

    # Inference succeeds without error
    service = get_model_service()
    result = service.predict_delay_probability(features)
    assert 0.0 <= result["delay_probability"] <= 1.0


# 11. Model Unavailable Handling Tests
def test_model_unavailable_graceful_handling(tmp_path) -> None:
    service = MLModelService(model_directory=tmp_path / "non_existent")
    try:
        with pytest.raises(ModelLoadError):
            service.load_model("logistic-regression")
    finally:
        MLModelService(model_directory=None)


# 12. End-to-End Kafka Flow Integration Tests
def test_end_to_end_kafka_to_prediction_topic(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(store, "get_settings", lambda: SimpleNamespace(data_directory=tmp_path))
    mock_producer = MagicMock()

    obs = sample_live_observation(icao24="e2e001", callsign="SWA333")
    key = b"e2e001"
    value = obs.model_dump_json().encode("utf-8")

    event = prediction_consumer.process_message(
        key=key,
        value=value,
        partition=0,
        offset=42,
        producer=mock_producer,
    )
    assert event is not None
    assert event.flight_id == "e2e001"

    # Produced to flight-predictions topic
    assert mock_producer.produce.call_count == 1
    call_args = mock_producer.produce.call_args[1]
    assert call_args["topic"] == "flight-predictions"
    assert call_args["key"] == b"e2e001"

    # Queryable in store
    retrieved = store.latest_predictions(limit=5)
    assert len(retrieved) == 1
    assert retrieved[0]["flight_id"] == "e2e001"
    assert retrieved[0]["callsign"] == "SWA333"

    # Monitoring metrics summary
    metrics = store.prediction_metrics_summary()
    assert metrics["total_predictions"] == 1
    assert 0.0 <= metrics["mean_delay_probability"] <= 1.0


# 13. Anomaly Detection Separation Tests
def test_anomaly_detection_separated_from_delay_prediction() -> None:
    detector = get_anomaly_detector()
    obs = sample_live_observation()
    features = extract_features_from_live_observation(obs)

    # Anomaly scoring
    anomaly_res = detector.score_features(features)
    assert anomaly_res["task"] == "anomaly_detection"
    assert "anomaly_score" in anomaly_res
    assert 0.0 <= anomaly_res["anomaly_score"] <= 100.0

    # Operational telemetry checks
    normal_telemetry = detector.check_telemetry_anomaly(obs.state)
    assert not normal_telemetry["is_anomaly"]

    # Extreme vertical rate trigger
    abnormal_state = obs.state.model_copy(update={"vertical_rate_mps": -35.0})
    flagged = detector.check_telemetry_anomaly(abnormal_state)
    assert flagged["is_anomaly"]
    assert "Extreme vertical rate" in flagged["flags"][0]


# 14. Real-time Inference Latency Benchmark
def test_inference_latency_benchmark() -> None:
    service = get_model_service()
    obs = sample_live_observation()
    features = extract_features_from_live_observation(obs)

    # Warmup
    service.predict_delay_probability(features)

    # 50 iterations benchmark
    latencies = []
    for _ in range(50):
        t0 = time.perf_counter()
        res = service.predict_delay_probability(features)
        latencies.append((time.perf_counter() - t0) * 1000.0)

    mean_latency = float(np.mean(latencies))
    p95_latency = float(np.percentile(latencies, 95))
    assert mean_latency < 100.0, f"Average latency too high: {mean_latency:.2f} ms"
    assert p95_latency < 250.0, f"P95 latency too high: {p95_latency:.2f} ms"
