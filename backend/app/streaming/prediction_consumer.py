"""Real-time Kafka streaming consumer for ML delay prediction.

Subscribes to 'flight-states', performs feature extraction, runs ML inference,
publishes predictions to 'flight-predictions', and stores results for the API.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from typing import Any

from confluent_kafka import Consumer, KafkaException, Producer
from pydantic import ValidationError

from backend.app.config.settings import get_settings
from backend.app.feature_engineering.features import extract_features_from_live_observation
from backend.app.machine_learning.model_service import MLModelService, get_model_service
from backend.app.streaming.event import FlightPredictionEvent, Observation
from backend.app.streaming.store import store_prediction, store_rejected_prediction

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("prediction_consumer")

INPUT_TOPIC = "flight-states"
OUTPUT_TOPIC = "flight-predictions"
CONSUMER_GROUP = "flightpulse-prediction-v1"


def process_message(
    key: bytes | None,
    value: bytes | None,
    partition: int,
    offset: int,
    producer: Producer | None = None,
    model_service: MLModelService | None = None,
) -> FlightPredictionEvent | None:
    """Validate, transform, predict, and emit a single Kafka flight state message."""
    if model_service is None:
        model_service = get_model_service()

    # 1. Parse and validate message
    try:
        if not value:
            raise ValueError("Empty Kafka message payload")
        observation = Observation.model_validate_json(value)
        expected_key = observation.state.icao24.encode()
        if key is not None and key != expected_key:
            raise ValueError(f"Key mismatch: expected {expected_key.decode()}, got {key.decode(errors='replace')}")
    except (ValidationError, ValueError, Exception) as exc:
        reason = f"{type(exc).__name__}: {str(exc)[:120]}"
        logger.warning("Rejected Kafka message at p=%d o=%d: %s", partition, offset, reason)
        store_rejected_prediction(partition, offset, reason, value)
        return None

    # 2. Real-time feature engineering
    try:
        manifest = model_service.load_manifest()
        feature_dict = extract_features_from_live_observation(observation, manifest)
    except Exception as exc:
        reason = f"FeatureExtractionError: {str(exc)[:120]}"
        logger.warning("Feature extraction failed for %s at p=%d o=%d: %s",
                       observation.state.icao24, partition, offset, reason)
        store_rejected_prediction(partition, offset, reason, value)
        return None

    # 3. Model inference
    try:
        pred_result = model_service.predict_delay_probability(feature_dict, model_name="best")
        contributions = model_service.compute_feature_contributions(feature_dict, model_name="best")
    except Exception as exc:
        reason = f"InferenceError: {str(exc)[:120]}"
        logger.warning("Inference failed for %s at p=%d o=%d: %s",
                       observation.state.icao24, partition, offset, reason)
        store_rejected_prediction(partition, offset, reason, value)
        return None

    # 4. Construct prediction event
    state = observation.state
    timestamp = state.last_contact or observation.source_time
    prediction_event = FlightPredictionEvent(
        flight_id=state.icao24,
        callsign=state.callsign,
        source=observation.source,
        timestamp=timestamp,
        prediction=pred_result["prediction"],
        predicted_class=pred_result["predicted_class"],
        delay_probability=pred_result["delay_probability"],
        threshold=pred_result["threshold"],
        model_id=pred_result["model_id"],
        model_version=pred_result["model_version"],
        prediction_timestamp=datetime.now(timezone.utc).isoformat(),
        latency_ms=pred_result["latency_ms"],
        features={
            "top_contributions": contributions,
            "Reporting_Airline": feature_dict.get("Reporting_Airline"),
            "Origin": feature_dict.get("Origin"),
            "Dest": feature_dict.get("Dest"),
        },
    )

    # 5. Publish to Kafka output topic if producer is supplied
    if producer is not None:
        try:
            producer.produce(
                topic=OUTPUT_TOPIC,
                key=state.icao24.encode("utf-8"),
                value=prediction_event.model_dump_json().encode("utf-8"),
            )
            producer.poll(0)
        except Exception as exc:
            logger.error("Failed to produce prediction to Kafka: %s", exc)

    # 6. Store prediction in local database for API query
    try:
        store_prediction(prediction_event)
    except Exception as exc:
        logger.error("Failed to store prediction in SQLite: %s", exc)

    return prediction_event


def main():
    parser = argparse.ArgumentParser(description="FlightPulse real-time ML delay prediction consumer")
    parser.add_argument("--once", action="store_true", help="Exit after polling available messages or idle timeout.")
    parser.add_argument("--bootstrap-servers", default=None, help="Kafka bootstrap servers override.")
    parser.add_argument("--timeout", type=float, default=10.0, help="Poll timeout in seconds.")
    args = parser.parse_args()

    settings = get_settings()
    bootstrap_servers = args.bootstrap_servers or settings.kafka_bootstrap_servers

    logger.info("Initializing ML Model Service...")
    model_service = get_model_service()
    best_name, threshold, meta = model_service.select_best_model()
    logger.info("Selected model: %s (threshold: %.4f, validation F2: %.4f)",
                best_name, threshold, meta.get("metric_value", 0.0))

    logger.info("Connecting to Kafka cluster at %s...", bootstrap_servers)
    consumer = Consumer({
        "bootstrap.servers": bootstrap_servers,
        "group.id": CONSUMER_GROUP,
        "enable.auto.commit": False,
        "auto.offset.reset": "earliest",
    })

    producer = Producer({
        "bootstrap.servers": bootstrap_servers,
        "enable.idempotence": True,
        "delivery.timeout.ms": 15000,
    })

    consumer.subscribe([INPUT_TOPIC])
    logger.info("Subscribed to '%s'. Publishing predictions to '%s'.", INPUT_TOPIC, OUTPUT_TOPIC)

    processed_count = 0
    delayed_count = 0

    try:
        while True:
            msg = consumer.poll(args.timeout)
            if msg is None:
                if args.once:
                    logger.info("Idle poll reached with --once flag. Exiting.")
                    break
                continue

            if msg.error():
                logger.error("Kafka error: %s", msg.error())
                if args.once:
                    break
                continue

            event = process_message(
                msg.key(),
                msg.value(),
                msg.partition(),
                msg.offset(),
                producer=producer,
                model_service=model_service,
            )

            # Acknowledge offset
            consumer.commit(message=msg, asynchronous=False)

            if event is not None:
                processed_count += 1
                if event.prediction == 1:
                    delayed_count += 1
                if processed_count % 50 == 0:
                    logger.info(
                        "Processed %d predictions (delayed: %d, delay_rate: %.2f%%)",
                        processed_count, delayed_count, 100.0 * delayed_count / processed_count
                    )
    except KeyboardInterrupt:
        logger.info("Consumer interrupted by user.")
    finally:
        producer.flush(10)
        consumer.close()
        logger.info("Consumer shut down cleanly. Total predictions emitted: %d", processed_count)


if __name__ == "__main__":
    main()
