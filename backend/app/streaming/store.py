"""Atomic microbatch sink. Kafka offsets and aircraft observation keys survive replays."""

import json
import sqlite3
from contextlib import closing
from typing import Any
from pydantic import ValidationError
from backend.app.config.settings import get_settings
from backend.app.streaming.event import Observation, FlightPredictionEvent


def database():
    return get_settings().data_directory / "streaming" / "observations.sqlite"


def store_batch(frame, batch_id):
    path = database()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS observations(
            source TEXT, aircraft TEXT, observed INTEGER, velocity REAL, vertical_rate REAL, payload TEXT,
            PRIMARY KEY(source, aircraft, observed))""")
        db.execute("""CREATE TABLE IF NOT EXISTS rejected(
            partition INTEGER, offset INTEGER, reason TEXT, payload BLOB, PRIMARY KEY(partition,offset))""")
        db.execute("""CREATE TABLE IF NOT EXISTS batch_metrics(
            batch INTEGER, partition INTEGER, first_offset INTEGER, last_offset INTEGER, records INTEGER,
            PRIMARY KEY(batch, partition))""")
        from pyspark.sql import functions as F

        metrics = frame.groupBy("partition").agg(
            F.min("offset"), F.max("offset"), F.count("*")
        )
        for partition, first, last, count in metrics.toLocalIterator():
            db.execute(
                "INSERT OR REPLACE INTO batch_metrics VALUES(?,?,?,?,?)",
                (batch_id, partition, first, last, count),
            )
        if not db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='windows'"
        ).fetchone():
            db.execute("""CREATE TABLE windows(source TEXT, aircraft TEXT, start INTEGER, records INTEGER,
                       speed_total REAL, speed_count INTEGER, peak_rate REAL, PRIMARY KEY(source,aircraft,start))""")
            db.execute("""INSERT INTO windows SELECT source, aircraft, observed/300*300, count(*),
                       coalesce(sum(velocity),0),count(velocity),max(abs(vertical_rate))
                       FROM observations GROUP BY source,aircraft,observed/300""")
        accepted = []
        events = []
        for record in frame.toLocalIterator():
            try:
                event = Observation.model_validate_json(bytes(record.value or b""))
                state = event.state
                if bytes(record.key or b"") != state.icao24.encode():
                    raise ValueError("Kafka key differs from observation")
            except (ValidationError, ValueError) as error:
                db.execute(
                    "INSERT OR IGNORE INTO rejected VALUES(?,?,?,?)",
                    (
                        record.partition,
                        record.offset,
                        type(error).__name__,
                        record.value,
                    ),
                )
                continue
            events.append(event)
            inserted = db.execute(
                "INSERT OR IGNORE INTO observations VALUES(?,?,?,?,?,?)",
                (
                    event.source,
                    state.icao24,
                    state.last_contact,
                    state.velocity_mps,
                    state.vertical_rate_mps,
                    event.model_dump_json(),
                ),
            )
            if inserted.rowcount:
                accepted.append(f"{record.partition}:{record.offset}")
        if accepted:
            payload = F.from_json(
                F.col("value").cast("string"),
                "source STRING, state STRUCT<icao24:STRING,last_contact:LONG,velocity_mps:DOUBLE,vertical_rate_mps:DOUBLE>",
            )
            observations = (
                frame.where(F.concat_ws(":", "partition", "offset").isin(accepted))
                .select(payload.alias("event"))
                .select("event.source", "event.state.*")
            )
            windows = (
                observations.groupBy(
                    "source",
                    "icao24",
                    F.window(F.timestamp_seconds("last_contact"), "5 minutes"),
                )
                .agg(
                    F.count("*").alias("n"),
                    F.sum("velocity_mps").alias("speed"),
                    F.count("velocity_mps").alias("speeds"),
                    F.max(F.abs("vertical_rate_mps")).alias("peak"),
                )
                .selectExpr(
                    "source",
                    "icao24",
                    "unix_timestamp(window.start)",
                    "n",
                    "speed",
                    "speeds",
                    "peak",
                )
            )
            for (
                source,
                aircraft,
                start,
                n,
                speed,
                speeds,
                peak,
            ) in windows.toLocalIterator():
                db.execute(
                    """INSERT INTO windows VALUES(?,?,?,?,?,?,?) ON CONFLICT(source,aircraft,start)
                    DO UPDATE SET records=records+excluded.records, speed_total=speed_total+excluded.speed_total,
                    speed_count=speed_count+excluded.speed_count, peak_rate=coalesce(max(peak_rate,excluded.peak_rate),
                    peak_rate,excluded.peak_rate)""",
                    (source, aircraft, start, n, speed or 0, speeds, peak),
                )
    from backend.app.services.alerts import create_observation_alert
    for event in events:
        create_observation_alert(event)


def latest_states(max_age=120):
    """Only fresh provider positions, never simulation or archived aircraft."""
    import time
    path = database()
    if not path.exists():
        return {"status": "awaiting_stream", "time": None, "aircraft": [], "transport": "kafka"}
    with closing(sqlite3.connect(path, timeout=5)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='observations'").fetchone():
            return {"status": "awaiting_stream", "time": None, "aircraft": [], "transport": "kafka"}
        latest = db.execute("SELECT max(observed) FROM observations WHERE source IN ('opensky','adsb_lol')").fetchone()[0]
        rows = db.execute("""SELECT payload FROM (SELECT payload, row_number() OVER
            (PARTITION BY aircraft ORDER BY observed DESC) AS rank FROM observations
            WHERE source IN ('opensky','adsb_lol') AND observed>=?) WHERE rank=1 LIMIT 2000""", (time.time() - max_age,)).fetchall()
    aircraft = []
    for row in rows:
        event = Observation.model_validate_json(row[0])
        s = event.state
        if s.longitude is None or s.latitude is None or s.time_position is None or time.time() - s.time_position > max_age:
            continue
        aircraft.append(dict(id=s.icao24, callsign=s.callsign or s.icao24.upper(), registration=None, type=None,
                             lon=s.longitude, lat=s.latitude, ground=s.on_ground,
                             altitude=None if s.barometric_altitude_m is None else s.barometric_altitude_m * 3.28084,
                             speed=None if s.velocity_mps is None else s.velocity_mps * 1.94384,
                             heading=s.true_track_degrees,
                             verticalRate=None if s.vertical_rate_mps is None else s.vertical_rate_mps * 196.85,
                             observed=s.last_contact * 1000, squawk=s.squawk, provider=event.source))
    return {"status": "available" if aircraft else "stale" if latest else "awaiting_stream",
            "time": latest * 1000 if latest else None, "aircraft": aircraft, "transport": "kafka"}


def summary(source):
    path = database()
    if not path.exists():
        return {"status": "awaiting_stream", "source": source, "windows": []}
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        if not db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='windows'"
        ).fetchone():
            return {"status": "awaiting_stream", "source": source, "windows": []}
        windows = db.execute(
            """SELECT start AS window_start, aircraft, records AS observations,
            speed_total/nullif(speed_count,0) AS mean_speed_mps, peak_rate AS max_abs_vertical_rate_mps,
            peak_rate > 30 AS rate_outlier FROM windows WHERE source=?
            ORDER BY start DESC, aircraft LIMIT 100""",
            (source,),
        ).fetchall()
    return {
        "status": "available",
        "source": source,
        "windows": [dict(row) for row in windows],
    }


def predictions_database():
    return get_settings().data_directory / "streaming" / "predictions.sqlite"


def store_prediction(event: FlightPredictionEvent) -> None:
    path = predictions_database()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=10)) as db, db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS flight_predictions (
            flight_id TEXT PRIMARY KEY,
            timestamp INTEGER NOT NULL,
            prediction INTEGER NOT NULL,
            predicted_class TEXT NOT NULL,
            delay_probability REAL NOT NULL,
            threshold REAL NOT NULL,
            model_id TEXT NOT NULL,
            model_version TEXT NOT NULL,
            prediction_timestamp TEXT NOT NULL,
            callsign TEXT,
            source TEXT NOT NULL,
            latency_ms REAL NOT NULL,
            payload TEXT NOT NULL
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_predictions_time ON flight_predictions(timestamp DESC)")
        db.execute("""INSERT OR REPLACE INTO flight_predictions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            event.flight_id,
            event.timestamp,
            event.prediction,
            event.predicted_class,
            event.delay_probability,
            event.threshold,
            event.model_id,
            event.model_version,
            event.prediction_timestamp,
            event.callsign,
            event.source,
            event.latency_ms,
            event.model_dump_json(),
        ))


def store_rejected_prediction(partition: int, offset: int, reason: str, payload: bytes | None) -> None:
    path = predictions_database()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=10)) as db, db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS rejected_prediction_events (
            partition INTEGER,
            offset INTEGER,
            reason TEXT,
            payload BLOB,
            rejected_at REAL,
            PRIMARY KEY(partition, offset)
        )""")
        import time
        db.execute("INSERT OR REPLACE INTO rejected_prediction_events VALUES(?,?,?,?,?)",
                   (partition, offset, reason, payload, time.time()))


def latest_predictions(limit: int = 50, flight_id: str | None = None) -> list[dict[str, Any]]:
    path = predictions_database()
    if not path.is_file():
        return []
    with closing(sqlite3.connect(path, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='flight_predictions'").fetchone():
            return []
        if flight_id:
            rows = db.execute("SELECT payload FROM flight_predictions WHERE flight_id=? ORDER BY timestamp DESC LIMIT ?", (flight_id, limit)).fetchall()
        else:
            rows = db.execute("SELECT payload FROM flight_predictions ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
    return [json.loads(row[0]) for row in rows]


def prediction_metrics_summary() -> dict[str, Any]:
    path = predictions_database()
    if not path.is_file():
        return {"total_predictions": 0, "delayed_count": 0, "non_delayed_count": 0, "delayed_ratio": 0.0, "mean_delay_probability": 0.0, "mean_latency_ms": 0.0, "rejected_events": 0}
    with closing(sqlite3.connect(path, timeout=5)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='flight_predictions'").fetchone():
            return {"total_predictions": 0, "delayed_count": 0, "non_delayed_count": 0, "delayed_ratio": 0.0, "mean_delay_probability": 0.0, "mean_latency_ms": 0.0, "rejected_events": 0}
        total = db.execute("SELECT count(*) FROM flight_predictions").fetchone()[0]
        delayed = db.execute("SELECT count(*) FROM flight_predictions WHERE prediction=1").fetchone()[0]
        avg_prob = db.execute("SELECT avg(delay_probability) FROM flight_predictions").fetchone()[0] or 0.0
        avg_lat = db.execute("SELECT avg(latency_ms) FROM flight_predictions").fetchone()[0] or 0.0
        rejected = 0
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='rejected_prediction_events'").fetchone():
            rejected = db.execute("SELECT count(*) FROM rejected_prediction_events").fetchone()[0]
    return {
        "total_predictions": total,
        "delayed_count": delayed,
        "non_delayed_count": total - delayed,
        "delayed_ratio": round(delayed / total, 4) if total > 0 else 0.0,
        "mean_delay_probability": round(float(avg_prob), 4),
        "mean_latency_ms": round(float(avg_lat), 2),
        "rejected_events": rejected,
    }
