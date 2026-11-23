"""System verification script: tests all endpoints and services via FastAPI TestClient."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from backend.app.main import app

def main():
    client = TestClient(app)

    print("\n--- 1. API Health Check ---")
    resp = client.get("/health")
    print(f"GET /health: {resp.status_code} -> {resp.json()}")
    assert resp.status_code == 200

    print("\n--- 2. Model Catalog ---")
    resp = client.get("/api/v1/models")
    assert resp.status_code == 200
    models = resp.json().get("models", [])
    print(f"GET /api/v1/models: {resp.status_code} -> {len(models)} models available:")
    for m in models:
        print(f"  * {m['algorithm']:<22} ID: {m['model_id']:<45} Inference: {m['inference_supported']}")

    print("\n--- 3. Streaming Predictions Endpoints ---")
    resp = client.get("/api/v1/live/predictions?limit=3")
    assert resp.status_code == 200
    preds = resp.json().get("predictions", [])
    print(f"GET /api/v1/live/predictions: {resp.status_code} -> {len(preds)} predictions in store")
    if preds:
        p = preds[0]
        print(f"  Sample Prediction: Flight {p.get('flight_id')} ({p.get('callsign')}) -> {p.get('predicted_class')} (prob={p.get('delay_probability')}, threshold={p.get('threshold')})")

    resp = client.get("/api/v1/live/predictions/metrics")
    assert resp.status_code == 200
    print(f"GET /api/v1/live/predictions/metrics: {resp.status_code} -> {resp.json()}")

    print("\n--- 4. Pre-Departure Delay Prediction API ---")
    sample_request = {
        "reporting_airline": "AA",
        "origin": "JFK",
        "destination": "LAX",
        "flight_date": "2024-02-15",
        "scheduled_departure_hhmm": 830,
        "scheduled_arrival_hhmm": 1145,
        "scheduled_elapsed_time_minutes": 375.0,
        "distance_miles": 2475.0,
    }
    resp = client.post("/api/v1/intelligence/delay-predictions", json=sample_request)
    assert resp.status_code == 200
    data = resp.json()
    print(f"POST /api/v1/intelligence/delay-predictions: {resp.status_code}")
    print(f"  * Model ID:         {data.get('model_id')}")
    print(f"  * Predicted Class:  {data.get('predicted_class')}")
    print(f"  * Probability:      {data.get('model_score')}")
    print(f"  * Threshold:        {data.get('threshold')}")
    print(f"  * Top Factor:       {data.get('feature_contributions', [{}])[0] if data.get('feature_contributions') else 'None'}")

    print("\n--- 5. Anomaly Detection API ---")
    resp = client.post("/api/v1/intelligence/anomalies", json=sample_request)
    assert resp.status_code == 200
    data = resp.json()
    print(f"POST /api/v1/intelligence/anomaly-detection: {resp.status_code}")
    print(f"  * Model ID:         {data.get('model_id')}")
    print(f"  * Anomaly Score:    {data.get('anomaly_score')}/100")
    print(f"  * Outlier Flag:     {data.get('is_statistical_outlier')}")
    print(f"  * Interpretation:   {data.get('score_interpretation')}")

    print("\n>>> System Verification PASSED: All operational services and endpoints healthy! <<<\n")

if __name__ == "__main__":
    main()
