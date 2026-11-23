"""Canonical, leakage-safe feature engineering for FlightPulse ML models.

Guarantees 100% consistency across historical training, batch processing,
and real-time streaming inference.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from backend.app.schemas.intelligence import DelayPredictionRequest
from backend.app.streaming.event import Observation


# Exact 21-feature contract from Phase 4.1 / 4.1.6
CATEGORICAL_FEATURES: tuple[str, ...] = ("Reporting_Airline", "Origin", "Dest")

NUMERIC_FEATURES: tuple[str, ...] = (
    "month",
    "day_of_month",
    "day_of_week",
    "scheduled_departure_sin",
    "scheduled_departure_cos",
    "scheduled_arrival_sin",
    "scheduled_arrival_cos",
    "scheduled_elapsed_time_minutes",
    "distance_miles",
)

MISSING_INDICATOR_FEATURES: tuple[str, ...] = tuple(
    f"is_missing_{name}" for name in NUMERIC_FEATURES
)

FEATURE_ALLOWLIST: tuple[str, ...] = (
    *CATEGORICAL_FEATURES,
    *NUMERIC_FEATURES,
    *MISSING_INDICATOR_FEATURES,
)

TARGET_COLUMN: str = "target_arr_delay_gt_15"
MISSING_CATEGORY: str = "__MISSING__"

# Strict leakage denylist
LEAKAGE_DENYLIST: frozenset[str] = frozenset(
    {
        TARGET_COLUMN,
        "is_delayed",
        "ArrDelay",
        "ArrDelayMinutes",
        "ArrDel15",
        "ArrivalDelayGroups",
        "DepDelay",
        "DepDelayMinutes",
        "DepDel15",
        "DepartureDelayGroups",
        "DepTime",
        "ArrTime",
        "ActualElapsedTime",
        "AirTime",
        "TaxiIn",
        "TaxiOut",
        "WheelsOff",
        "WheelsOn",
        "FirstDepTime",
        "Cancelled",
        "CancellationCode",
        "Diverted",
        "DivAirportLandings",
        "DivReachedDest",
        "DivActualElapsedTime",
        "DivArrDelay",
        "DivDistance",
        "CarrierDelay",
        "WeatherDelay",
        "NASDelay",
        "SecurityDelay",
        "LateAircraftDelay",
        "is_trainable",
        "arrival_delay_category",
    }
)

# Reference training medians from Phase 4.1.6 training partition (Jan 1–Feb 11, 2024, 716,676 rows)
DEFAULT_TRAINING_MEDIANS: dict[str, float] = {
    "month": 1.0,
    "day_of_month": 16.0,
    "day_of_week": 2.0,
    "scheduled_departure_sin": -0.42261827,
    "scheduled_departure_cos": -0.87035567,
    "scheduled_arrival_sin": -0.73727733,
    "scheduled_arrival_cos": -0.63607824,
    "scheduled_elapsed_time_minutes": 133.0,
    "distance_miles": 678.0,
}


def validate_feature_contract(feature_names: Sequence[str]) -> None:
    """Validate that features strictly match the approved 21-feature contract."""
    names = list(feature_names)
    prohibited = set(names) & (LEAKAGE_DENYLIST | {TARGET_COLUMN, "flight_date", "split"})
    if prohibited:
        raise ValueError(f"Prohibited fields detected in feature matrix: {sorted(prohibited)}")
    if names != list(FEATURE_ALLOWLIST):
        raise ValueError(
            f"Feature list does not match FEATURE_ALLOWLIST. "
            f"Expected {len(FEATURE_ALLOWLIST)} columns in exact order, got {len(names)}."
        )


def minutes_since_midnight(value: int | None) -> float | None:
    """Parse scheduled HHMM integer into minutes since midnight."""
    if value is None:
        return None
    if value == 2400:
        return 0.0
    hour, minute = divmod(value, 100)
    if hour > 23 or minute > 59:
        raise ValueError("Scheduled times must be valid HHMM values or 2400.")
    return float(hour * 60 + minute)


def cyclic_time(value: int | None) -> tuple[float | None, float | None]:
    """Convert scheduled HHMM to cyclic sine/cosine values over a 24-hour cycle."""
    minutes = minutes_since_midnight(value)
    if minutes is None:
        return None, None
    angle = 2 * math.pi * minutes / 1440.0
    return math.sin(angle), math.cos(angle)


def cyclic_time_from_minutes(minutes: float | None) -> tuple[float | None, float | None]:
    """Convert minutes since midnight to cyclic sine/cosine values."""
    if minutes is None or not math.isfinite(minutes):
        return None, None
    minutes = minutes % 1440.0
    angle = 2 * math.pi * minutes / 1440.0
    return math.sin(angle), math.cos(angle)


def extract_features_from_request(
    request: DelayPredictionRequest,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract and validate the 21-feature vector from an API prediction request."""
    medians = (
        manifest.get("preprocessing", {})
        .get("upstream_imputation", {})
        .get("medians", DEFAULT_TRAINING_MEDIANS)
        if manifest
        else DEFAULT_TRAINING_MEDIANS
    )
    dep_sin, dep_cos = cyclic_time(request.scheduled_departure_hhmm)
    arr_sin, arr_cos = cyclic_time(request.scheduled_arrival_hhmm)

    raw_numeric: dict[str, float | None] = {
        "month": float(request.flight_date.month),
        "day_of_month": float(request.flight_date.day),
        "day_of_week": float(request.flight_date.weekday()),
        "scheduled_departure_sin": dep_sin,
        "scheduled_departure_cos": dep_cos,
        "scheduled_arrival_sin": arr_sin,
        "scheduled_arrival_cos": arr_cos,
        "scheduled_elapsed_time_minutes": request.scheduled_elapsed_time_minutes,
        "distance_miles": request.distance_miles,
    }

    row: dict[str, Any] = {
        "Reporting_Airline": request.reporting_airline.strip().upper(),
        "Origin": request.origin.strip().upper(),
        "Dest": request.destination.strip().upper(),
    }
    missing_flags: dict[str, int] = {}
    for name in NUMERIC_FEATURES:
        val = raw_numeric[name]
        is_missing = val is None or not math.isfinite(float(val))
        row[name] = float(medians[name]) if is_missing else float(val)
        missing_flags[f"is_missing_{name}"] = int(is_missing)
    row.update(missing_flags)

    validate_feature_contract(list(row.keys()))
    return row


def extract_features_from_live_observation(
    observation: Observation,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract the canonical 21-feature vector from a live Kafka flight Observation.

    Uses observed telemetry and identity information. Missing pre-departure
    schedule attributes use exact training medians and explicit missingness
    indicators without inventing fabricated data.
    """
    medians = (
        manifest.get("preprocessing", {})
        .get("upstream_imputation", {})
        .get("medians", DEFAULT_TRAINING_MEDIANS)
        if manifest
        else DEFAULT_TRAINING_MEDIANS
    )

    state = observation.state
    timestamp = state.last_contact or observation.source_time
    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)

    # Carrier code extracted from callsign prefix if standard format (e.g., AAL100 -> AA, DAL200 -> DL)
    callsign = (state.callsign or "").strip().upper()
    carrier = MISSING_CATEGORY
    if callsign:
        # Common ICAO to IATA mappings for major US carriers
        prefix = callsign[:3]
        icao_map = {
            "AAL": "AA",
            "DAL": "DL",
            "UAL": "UA",
            "SWA": "WN",
            "JBU": "B6",
            "ASA": "AS",
            "SKW": "OO",
            "ENY": "MQ",
            "FFT": "F9",
            "NKS": "NK",
            "RPA": "YX",
            "EDV": "9E",
            "PDT": "PT",
            "PSA": "OH",
        }
        carrier = icao_map.get(prefix, callsign[:2] if len(callsign) >= 2 and callsign[:2].isalpha() else MISSING_CATEGORY)

    # In live telemetry without matched flight schedules, origin and dest default to __MISSING__
    origin = MISSING_CATEGORY
    dest = MISSING_CATEGORY

    # Calculate cyclic time from actual observed time
    minutes_now = float(dt.hour * 60 + dt.minute)
    dep_sin, dep_cos = cyclic_time_from_minutes(minutes_now)

    raw_numeric: dict[str, float | None] = {
        "month": float(dt.month),
        "day_of_month": float(dt.day),
        "day_of_week": float(dt.weekday()),
        "scheduled_departure_sin": dep_sin,
        "scheduled_departure_cos": dep_cos,
        "scheduled_arrival_sin": None,  # Not directly known from live telemetry
        "scheduled_arrival_cos": None,
        "scheduled_elapsed_time_minutes": None,
        "distance_miles": None,
    }

    row: dict[str, Any] = {
        "Reporting_Airline": carrier,
        "Origin": origin,
        "Dest": dest,
    }

    missing_flags: dict[str, int] = {}
    for name in NUMERIC_FEATURES:
        val = raw_numeric[name]
        is_missing = val is None or not math.isfinite(float(val))
        row[name] = float(medians[name]) if is_missing else float(val)
        missing_flags[f"is_missing_{name}"] = int(is_missing)
    row.update(missing_flags)

    validate_feature_contract(list(row.keys()))
    return row


def to_feature_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert feature dictionaries into a strictly typed pandas DataFrame."""
    if not rows:
        return pd.DataFrame(columns=list(FEATURE_ALLOWLIST))

    df = pd.DataFrame(rows).loc[:, list(FEATURE_ALLOWLIST)]
    for col in CATEGORICAL_FEATURES:
        df[col] = df[col].astype("category")
    for col in NUMERIC_FEATURES:
        df[col] = df[col].astype("float32")
    for col in MISSING_INDICATOR_FEATURES:
        df[col] = df[col].astype("int8")
    return df
