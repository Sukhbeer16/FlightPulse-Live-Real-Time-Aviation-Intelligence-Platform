"""Lightweight Kafka ingestion for the local app; Spark remains an alternative consumer."""
import argparse
import sqlite3
from contextlib import closing

from backend.app.config.settings import get_settings
from backend.app.streaming.event import Observation
from backend.app.streaming.store import database
from backend.app.services.alerts import create_observation_alert


def ingest(key, value, partition, offset):
    path = database()
    path.parent.mkdir(parents=True, exist_ok=True)
    event = None
    with closing(sqlite3.connect(path, timeout=10)) as db, db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS observations(source TEXT, aircraft TEXT, observed INTEGER,
            velocity REAL, vertical_rate REAL, payload TEXT, PRIMARY KEY(source,aircraft,observed))""")
        db.execute("""CREATE TABLE IF NOT EXISTS rejected(partition INTEGER, offset INTEGER, reason TEXT,
            payload BLOB, PRIMARY KEY(partition,offset))""")
        db.execute("""CREATE TABLE IF NOT EXISTS windows(source TEXT, aircraft TEXT, start INTEGER, records INTEGER,
            speed_total REAL, speed_count INTEGER, peak_rate REAL, PRIMARY KEY(source,aircraft,start))""")
        db.execute("CREATE INDEX IF NOT EXISTS observations_recent ON observations(source, observed DESC)")
        db.execute("CREATE TABLE IF NOT EXISTS consumer_health(name TEXT PRIMARY KEY, processed_at REAL, partition INTEGER, offset INTEGER)")
        try:
            event = Observation.model_validate_json(value or b"")
            if key != event.state.icao24.encode():
                raise ValueError("Kafka key differs from observation")
        except ValueError as error:
            db.execute("INSERT OR IGNORE INTO rejected VALUES(?,?,?,?)", (partition, offset, type(error).__name__, value))
            event = None
        if event:
            state = event.state
            inserted = db.execute("INSERT OR IGNORE INTO observations VALUES(?,?,?,?,?,?)", (
                event.source, state.icao24, state.last_contact, state.velocity_mps, state.vertical_rate_mps, event.model_dump_json()))
            if inserted.rowcount:
                peak = None if state.vertical_rate_mps is None else abs(state.vertical_rate_mps)
                db.execute("""INSERT INTO windows VALUES(?,?,?,?,?,?,?) ON CONFLICT(source,aircraft,start)
                    DO UPDATE SET records=records+1, speed_total=speed_total+excluded.speed_total,
                    speed_count=speed_count+excluded.speed_count,
                    peak_rate=coalesce(max(peak_rate,excluded.peak_rate),peak_rate,excluded.peak_rate)""",
                    (event.source, state.icao24, state.last_contact // 300 * 300, 1,
                     state.velocity_mps or 0, int(state.velocity_mps is not None), peak))
        import time
        db.execute("INSERT OR REPLACE INTO consumer_health VALUES(?,?,?,?)", ("kafka-consumer", time.time(), partition, offset))
    if event:
        # Replay also repairs an interrupted alert write; the alert ID is deterministic.
        create_observation_alert(event)


def main():
    from confluent_kafka import Consumer, KafkaException
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Exit after an idle poll (10 seconds).")
    args = parser.parse_args()
    consumer = Consumer({"bootstrap.servers": get_settings().kafka_bootstrap_servers,
                         "group.id": "flightpulse-app-v1", "enable.auto.commit": False,
                         "auto.offset.reset": "earliest"})
    consumer.subscribe(["flight-states"])
    try:
        while True:
            message = consumer.poll(10)
            if message is None:
                if args.once:
                    break
                continue
            if message.error():
                raise KafkaException(message.error())
            ingest(message.key(), message.value(), message.partition(), message.offset())
            consumer.commit(message=message, asynchronous=False)
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
