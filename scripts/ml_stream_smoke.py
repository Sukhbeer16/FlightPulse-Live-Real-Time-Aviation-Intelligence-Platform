"""End-to-End Real-Time ML Streaming Smoke Test for FlightPulse.

Proves that the trained ML delay model is connected to the Kafka streaming pipeline.
Supports both live Kafka broker testing and self-contained integration smoke testing.

Usage:
    python scripts/ml_stream_smoke.py --mode standalone
    python scripts/ml_stream_smoke.py --mode live --bootstrap-servers 127.0.0.1:9092
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pydantic import ValidationError

from backend.app.config.settings import get_settings
from backend.app.feature_engineering.features import (
    FEATURE_ALLOWLIST,
    extract_features_from_live_observation,
)
from backend.app.machine_learning.model_service import get_model_service
from backend.app.schemas.live import LiveStateVector
from backend.app.streaming.event import FlightPredictionEvent, Observation
from backend.app.streaming.prediction_consumer import process_message
from backend.app.streaming.store import latest_predictions, store_prediction


def generate_test_observation(
    callsign: str = "AAL100",
    carrier: str = "AA",
    origin: str = "JFK",
    dest: str = "LAX",
) -> Observation:
    now = int(time.time())
    aircraft = secrets.token_hex(3)
    return Observation(
        version=1,
        source="SIMULATION",
        source_time=now,
        state=LiveStateVector(
            icao24=aircraft,
            callsign=callsign,
            origin_country="United States",
            time_position=now,
            last_contact=now,
            longitude=-73.78,
            latitude=40.64,
            barometric_altitude_m=3200.0,
            on_ground=False,
            velocity_mps=215.0,
            true_track_degrees=88.0,
            vertical_rate_mps=1.5,
            geometric_altitude_m=None,
            squawk="1200",
            spi=False,
            position_source=0,
            category=None,
        ),
    )


def run_standalone_smoke_test(batch_size: int = 100) -> dict[str, Any]:
    print("\n" + "=" * 70)
    print(" FLIGHTPULSE REAL-TIME ML STREAMING SMOKE TEST (STANDALONE)")
    print("=" * 70)

    # Step 1: Verify Trained Model
    print("\n[Step 1/6] Loading production model and preprocessor...")
    model_service = get_model_service()
    best_name, threshold, meta = model_service.select_best_model()
    print(f" -> Active model candidate: {best_name}")
    print(f" -> Validation F2 score:   {meta.get('metric_value', 0.0):.4f}")
    print(f" -> Decision threshold:    {threshold:.6f}")

    # Step 2: Generate Live Flight Event
    print("\n[Step 2/6] Generating simulated live flight state vector...")
    obs = generate_test_observation(callsign="DAL456")
    icao24 = obs.state.icao24
    key_bytes = icao24.encode("utf-8")
    payload_bytes = obs.model_dump_json().encode("utf-8")
    print(f" -> ICAO24 Key:            {icao24}")
    print(f" -> Callsign:              {obs.state.callsign}")
    print(f" -> Source Time:           {obs.source_time} UTC")
    print(f" -> Payload size:          {len(payload_bytes)} bytes")

    # Step 3: Stream Consumer Processing
    print("\n[Step 3/6] Streaming Consumer: Validation -> Features -> ML Inference...")
    t_start = time.perf_counter()
    pred_event = process_message(
        key=key_bytes,
        value=payload_bytes,
        partition=0,
        offset=101,
        producer=None,
        model_service=model_service,
    )
    t_end = time.perf_counter()

    kafka_processing_ms = round((t_end - t_start) * 1000.0, 3)
    assert pred_event is not None, "Failed to produce prediction event!"

    print(f" -> Prediction:            {pred_event.predicted_class.upper()} (flag={pred_event.prediction})")
    print(f" -> Delay Probability:     {pred_event.delay_probability:.4f} (threshold={pred_event.threshold:.4f})")
    print(f" -> Model Version:         {pred_event.model_version}")
    print(f" -> Model Inference Time:  {pred_event.latency_ms:.3f} ms")
    print(f" -> Total Processing Time: {kafka_processing_ms:.3f} ms")

    # Step 4: Verify Schema & Topic Serialization
    print("\n[Step 4/6] Verifying prediction event topic contract...")
    serialized = pred_event.model_dump_json().encode("utf-8")
    deserialized = FlightPredictionEvent.model_validate_json(serialized)
    assert deserialized.flight_id == icao24
    assert deserialized.prediction == pred_event.prediction
    print(f" -> Output topic schema:   'flight-predictions' [VALIDATED]")

    # Step 5: Verify Persistence & API Query
    print("\n[Step 5/6] Verifying persistence and API retrieval...")
    records = latest_predictions(limit=5, flight_id=icao24)
    assert len(records) > 0, "Prediction not found in storage!"
    print(f" -> Stored records found:  {len(records)} for aircraft {icao24}")

    # Step 6: Throughput & Latency Benchmark
    print(f"\n[Step 6/6] Benchmarking throughput over {batch_size} events...")
    latencies = []
    t_bench_start = time.perf_counter()
    for i in range(batch_size):
        test_obs = generate_test_observation()
        t0 = time.perf_counter()
        ev = process_message(
            key=test_obs.state.icao24.encode(),
            value=test_obs.model_dump_json().encode(),
            partition=0,
            offset=1000 + i,
            producer=None,
            model_service=model_service,
        )
        latencies.append((time.perf_counter() - t0) * 1000.0)
    t_bench_total = time.perf_counter() - t_bench_start

    throughput = round(batch_size / t_bench_total, 1)
    mean_lat = round(float(sum(latencies) / len(latencies)), 2)
    p95_lat = round(float(sorted(latencies)[int(len(latencies) * 0.95)]), 2)

    print(f" -> Mean Event Latency:    {mean_lat} ms")
    print(f" -> P95 Event Latency:     {p95_lat} ms")
    print(f" -> System Throughput:     {throughput} events/sec")
    print("\n" + "=" * 70)
    print(" SMOKE TEST PASSED: Real-time ML model successfully connected!")
    print("=" * 70)

    return {
        "status": "PASSED",
        "model": best_name,
        "mean_latency_ms": mean_lat,
        "p95_latency_ms": p95_lat,
        "throughput_eps": throughput,
    }


def run_live_broker_smoke_test(bootstrap_servers: str = "127.0.0.1:9092") -> None:
    print(f"\n[Live Broker Test] Connecting to Kafka at {bootstrap_servers}...")
    from confluent_kafka import Consumer, Producer

    producer = Producer({"bootstrap.servers": bootstrap_servers, "enable.idempotence": True})
    obs = generate_test_observation(callsign="LIVE_TEST")
    key = obs.state.icao24.encode("utf-8")
    val = obs.model_dump_json().encode("utf-8")

    def ack(err, msg):
        if err:
            raise RuntimeError(f"Failed delivery: {err}")
        print(f"Published test event to 'flight-states' [p={msg.partition()} o={msg.offset()}]")

    producer.produce("flight-states", key=key, value=val, on_delivery=ack)
    producer.flush(15)

    print("Now run the prediction consumer:")
    print(f"  .\\.venv\\Scripts\\python.exe -m backend.app.streaming.prediction_consumer --once")


def main():
    parser = argparse.ArgumentParser(description="FlightPulse ML streaming smoke test")
    parser.add_argument("--mode", choices=["standalone", "live"], default="standalone")
    parser.add_argument("--bootstrap-servers", default="127.0.0.1:9092")
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()

    if args.mode == "standalone":
        res = run_standalone_smoke_test(batch_size=args.batch_size)
        sys.exit(0 if res["status"] == "PASSED" else 1)
    else:
        run_live_broker_smoke_test(args.bootstrap_servers)


if __name__ == "__main__":
    main()
