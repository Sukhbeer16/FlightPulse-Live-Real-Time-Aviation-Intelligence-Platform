"""Publish normalized snapshots. Run with --simulation for one labelled test event."""

import argparse
import logging
import time
from backend.app.config.settings import get_settings
from backend.app.schemas.live import LiveStateVector
from backend.app.services.opensky import OpenSkyUnavailable, get_live_states
from backend.app.streaming.event import Observation
from backend.app.services.airspace import get_airspace


def adsb_snapshot(south, west, north, east):
    """Convert the app's public ADS-B feed to the versioned SI-unit contract."""
    snapshot = get_airspace((south+north)/2, (west+east)/2)
    timestamp = int(snapshot["time"] / 1000)
    states = []
    for row in snapshot["aircraft"]:
        # Some ADS-B identifiers carry a '~' prefix and are not valid ICAO24.
        if len(row["id"]) != 6 or not all(c in '0123456789abcdef' for c in row["id"].lower()):
            continue
        if not (south <= row["lat"] <= north and west <= row["lon"] <= east):
            continue
        observed = int(row["observed"] / 1000)
        states.append(LiveStateVector(
            icao24=row["id"].lower(), callsign=row["callsign"], origin_country="Not supplied",
            time_position=observed, last_contact=observed, longitude=row["lon"], latitude=row["lat"],
            on_ground=row["ground"], barometric_altitude_m=None if row["altitude"] is None else row["altitude"] * .3048,
            geometric_altitude_m=None, velocity_mps=None if row["speed"] is None else row["speed"] / 1.94384,
            true_track_degrees=row["heading"], vertical_rate_mps=None if row["verticalRate"] is None else row["verticalRate"] / 196.85,
            squawk=row["squawk"], spi=False, position_source=0,
        ))
    return timestamp, states


def publish(producer, source, timestamp, states):
    errors = []

    def acknowledged(error, message):
        if error:
            errors.append(str(error))

    for state in states:
        event = Observation(
            version=1, source=source, source_time=timestamp, state=state
        )
        producer.produce(
            "flight-states",
            key=state.icao24,
            value=event.model_dump_json(),
            on_delivery=acknowledged,
        )
        producer.poll(0)
    if producer.flush(35) or errors:
        raise RuntimeError(f"Kafka delivery incomplete: {errors[:1]}")


def main():
    from confluent_kafka import Producer
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation", action="store_true")
    parser.add_argument("--provider", choices=["opensky", "adsb-lol"], default="opensky")
    parser.add_argument("--once", action="store_true", help="Publish one provider snapshot and exit.")
    parser.add_argument(
        "--bounds",
        nargs=4,
        type=float,
        default=[40, -75, 42, -72],
        metavar=("S", "W", "N", "E"),
    )
    parser.add_argument("--interval", type=int, default=120)
    args = parser.parse_args()
    south, west, north, east = args.bounds
    if not (
        -90 <= south < north <= 90
        and -180 <= west < east <= 180
        and (north - south) * (east - west) <= 400
        and args.interval >= 10
    ):
        parser.error(
            "Use a valid region up to 400 square degrees and interval >= 10 seconds"
        )
    settings = get_settings()
    producer = Producer(
        {
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "enable.idempotence": True,
            "delivery.timeout.ms": 30000,
        }
    )
    if args.simulation:
        now = int(time.time())
        state = LiveStateVector(
            icao24="000001",
            callsign="SIM",
            origin_country="SIMULATION",
            time_position=now,
            last_contact=now,
            latitude=40,
            longitude=-74,
            on_ground=False,
            velocity_mps=100,
            true_track_degrees=None,
            vertical_rate_mps=None,
            geometric_altitude_m=None,
            barometric_altitude_m=None,
            squawk=None,
            spi=False,
            position_source=0,
        )
        publish(producer, "SIMULATION", now, [state])
        return
    if args.provider == "opensky" and not (settings.opensky_client_id and settings.opensky_client_secret):
        parser.error("Configure both OpenSky OAuth credentials in the backend .env")
    delay = args.interval
    while True:
        try:
            if args.provider == "adsb-lol":
                timestamp, states = adsb_snapshot(south, west, north, east)
            else:
                timestamp, states = get_live_states(lamin=south, lomin=west, lamax=north, lomax=east)
            publish(producer, "adsb_lol" if args.provider == "adsb-lol" else "opensky", timestamp, states)
            print(f"Delivered {len(states)} {args.provider} observations at source time {timestamp}.", flush=True)
            if args.once:
                return
            delay = args.interval
        except OpenSkyUnavailable as exc:
            if exc.status_code in (400, 401, 403):
                raise SystemExit("Provider rejected authentication or access") from None
            delay = max(
                min(900, delay * 2),
                int(exc.retry_after) if (exc.retry_after or "").isdigit() else 0,
            )
            logging.warning("OpenSky unavailable; next attempt in %d seconds", delay)
            if args.once:
                raise SystemExit("Provider unavailable; no snapshot delivered") from None
        except (OSError, ValueError):
            if args.once:
                raise SystemExit("ADS-B provider unavailable; no snapshot delivered") from None
            delay = min(900, delay * 2)
            logging.warning("ADS-B provider unavailable; next attempt in %d seconds", delay)
        time.sleep(delay)


if __name__ == "__main__":
    main()
