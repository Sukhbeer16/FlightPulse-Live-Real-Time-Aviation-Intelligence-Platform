"""Creation of schedule-based features and leakage-safe training frames."""

from __future__ import annotations

import pandas as pd


PREDICTOR_COLUMNS = (
    "FlightDate",
    "Reporting_Airline",
    "Origin",
    "Dest",
    "CRSDepTime",
    "CRSArrTime",
    "Distance",
    "departure_hour",
    "day_of_week",
    "month",
    "route",
    "scheduled_flight_duration_minutes",
)

ACTUAL_OUTCOME_COLUMNS = {
    "DepTime",
    "DepDelay",
    "DepDelayMinutes",
    "DepDel15",
    "WheelsOff",
    "WheelsOn",
    "ArrTime",
    "ArrDelay",
    "ArrDelayMinutes",
    "ArrDel15",
    "Cancelled",
    "CancellationCode",
    "Diverted",
    "ActualElapsedTime",
    "AirTime",
    "TaxiOut",
    "TaxiIn",
    "CarrierDelay",
    "WeatherDelay",
    "NASDelay",
    "SecurityDelay",
    "LateAircraftDelay",
}


def create_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with calendar, schedule, route, and target features.

    Departure hour is derived from scheduled local departure time. Scheduled
    duration uses BTS's scheduled elapsed-time field; it is not inferred by
    subtracting local clock times across time zones.
    """
    result = frame.copy()

    if "FlightDate" in result.columns:
        dates = pd.to_datetime(result["FlightDate"], errors="coerce")
        result["FlightDate"] = dates
        result["day_of_week"] = dates.dt.dayofweek.astype("Int8")
        result["month"] = dates.dt.month.astype("Int8")

    if "CRSDepTime" in result.columns:
        departure_time = pd.to_numeric(result["CRSDepTime"], errors="coerce")
        hour = departure_time // 100
        minute = departure_time % 100
        valid = (
            departure_time.notna()
            & (departure_time >= 0)
            & (departure_time <= 2400)
            & (minute < 60)
            & ((hour < 24) | (departure_time == 2400))
        )
        result["departure_hour"] = (hour.where(valid) % 24).astype("Int8")

    if {"Origin", "Dest"}.issubset(result.columns):
        origin = result["Origin"].astype("string").str.strip()
        destination = result["Dest"].astype("string").str.strip()
        route = origin + "-" + destination
        result["route"] = route.where(
            origin.notna() & origin.ne("") & destination.notna() & destination.ne("")
        )

    if "CRSElapsedTime" in result.columns:
        duration = pd.to_numeric(result["CRSElapsedTime"], errors="coerce")
        result["scheduled_flight_duration_minutes"] = duration.where(
            duration.between(0, 2000)
        )
    else:
        result["scheduled_flight_duration_minutes"] = pd.NA

    cancelled_flag = (
        pd.to_numeric(result["Cancelled"], errors="coerce")
        if "Cancelled" in result
        else pd.Series(0, index=result.index)
    )
    diverted_flag = (
        pd.to_numeric(result["Diverted"], errors="coerce")
        if "Diverted" in result
        else pd.Series(0, index=result.index)
    )
    cancelled = cancelled_flag.eq(1)
    diverted = diverted_flag.eq(1)
    arrival_delay = (
        pd.to_numeric(result["ArrDelay"], errors="coerce")
        if "ArrDelay" in result
        else pd.Series(float("nan"), index=result.index)
    )
    eligible = (
        cancelled_flag.eq(0)
        & diverted_flag.eq(0)
        & arrival_delay.notna()
    ).fillna(False)

    labels = pd.Series(pd.NA, index=result.index, dtype="Int8")
    labels.loc[eligible] = arrival_delay.loc[eligible].gt(15).astype("int8")
    result["is_delayed"] = labels
    result["is_trainable"] = eligible

    category = pd.Series("unknown", index=result.index, dtype="string")
    operating = cancelled_flag.eq(0) & diverted_flag.eq(0)
    category.loc[operating & arrival_delay.lt(0)] = "early"
    category.loc[operating & arrival_delay.ge(0) & arrival_delay.le(15)] = "on_time"
    category.loc[operating & arrival_delay.gt(15)] = "delayed"
    category.loc[diverted] = "diverted"
    category.loc[cancelled] = "cancelled"
    result["arrival_delay_category"] = category

    return result


def create_training_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Select eligible labels and scheduled predictors without actual outcomes."""
    required = {"is_delayed", "is_trainable"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Feature frame is missing target fields: {sorted(missing)}")

    predictors = [column for column in PREDICTOR_COLUMNS if column in frame.columns]
    if not predictors:
        raise ValueError("No supported scheduled predictor columns are present.")
    if not {"FlightDate", "Reporting_Airline", "Origin", "Dest"}.issubset(predictors):
        raise ValueError("Training data needs date, airline, origin, and destination.")

    eligible = frame["is_trainable"].fillna(False).astype(bool)
    training = frame.loc[eligible, predictors + ["is_delayed"]].copy()
    leaked = ACTUAL_OUTCOME_COLUMNS.intersection(training.columns)
    if leaked:
        raise ValueError(f"Actual outcome columns cannot be predictors: {sorted(leaked)}")
    return training
