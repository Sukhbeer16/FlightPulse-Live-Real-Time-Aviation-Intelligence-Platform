"""Publish labelled test data to the local development broker and verify it after a Spark drain."""

import argparse
import json
import time
from urllib.request import urlopen

from confluent_kafka import Producer
from backend.app.streaming.producer import publish
from backend.app.schemas.live import LiveStateVector
from backend.app.streaming.store import database


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["publish", "verify"])
    args = parser.parse_args()
    receipt = database().parent / "simulation-smoke.json"
    if args.action == "publish":
        now = int(time.time())
        start = now // 300 * 300 - 300
        import secrets

        aircraft = secrets.token_hex(3)
        common = dict(
            icao24=aircraft,
            callsign="SIMTEST",
            origin_country="SIMULATION",
            latitude=40,
            longitude=-74,
            barometric_altitude_m=None,
            geometric_altitude_m=None,
            on_ground=False,
            true_track_degrees=None,
            squawk=None,
            spi=False,
            position_source=0,
        )
        a = LiveStateVector(
            **common,
            last_contact=start + 1,
            time_position=start + 1,
            velocity_mps=100,
            vertical_rate_mps=None,
        )
        b = LiveStateVector(
            **common,
            last_contact=start + 2,
            time_position=start + 2,
            velocity_mps=200,
            vertical_rate_mps=31,
        )
        producer = Producer(
            {"bootstrap.servers": "127.0.0.1:9092", "enable.idempotence": True}
        )
        publish(producer, "SIMULATION", now, [a, b, a])
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps({"aircraft": aircraft, "start": start}))
    else:
        case = json.loads(receipt.read_text())
        with urlopen(
            "http://127.0.0.1:8000/api/v1/live/stream-summary?source=SIMULATION",
            timeout=10,
        ) as response:
            windows = json.load(response)["windows"]
        row = next(
            row
            for row in windows
            if row["aircraft"] == case["aircraft"]
            and row["window_start"] == case["start"]
        )
        assert row["observations"] == 2 and row["mean_speed_mps"] == 150, row
        assert row["rate_outlier"] == 1 and row["max_abs_vertical_rate_mps"] == 31, row
        print(row)


if __name__ == "__main__":
    main()
