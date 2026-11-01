"""Reusable row cleaning and bounded-memory CSV-to-Parquet processing."""

from __future__ import annotations

import calendar
from collections.abc import Iterator
from pathlib import Path

import pandas as pd

from pipelines.ingestion.feature_creation import create_features


REQUIRED_COLUMNS = {
    "FlightDate",
    "Reporting_Airline",
    "Origin",
    "Dest",
    "Cancelled",
    "Diverted",
    "ArrDelay",
}
NUMERIC_COLUMNS = {
    "CRSDepTime",
    "DepTime",
    "DepDelay",
    "CRSArrTime",
    "ArrTime",
    "ArrDelay",
    "Cancelled",
    "Diverted",
    "Distance",
    "CRSElapsedTime",
    "ActualElapsedTime",
}
NUMERIC_RANGES = {
    "Distance": (0, 20_000),
    "CRSElapsedTime": (0, 2_000),
    "ActualElapsedTime": (0, 2_000),
    "DepDelay": (-1_440, 10_080),
    "ArrDelay": (-1_440, 10_080),
}
TIME_COLUMNS = {"CRSDepTime", "DepTime", "CRSArrTime", "ArrTime"}
BOOLEAN_COLUMNS = {"Cancelled", "Diverted"}


def clean_dataframe(
    frame: pd.DataFrame,
    year: int = 2024,
    month: int = 1,
) -> pd.DataFrame:
    """Clean one chunk without imputing source values or altering the raw file.

    Invalid dates, out-of-scope dates, and missing flight identity fields are
    excluded. Other unavailable/invalid measurements remain null after numeric
    coercion so that downstream users can see missingness rather than invented
    values.
    """
    missing = REQUIRED_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(f"Input is missing required BTS columns: {sorted(missing)}")

    result = frame.copy()
    for column in ("Reporting_Airline", "Origin", "Dest"):
        result[column] = result[column].astype("string").str.strip()

    result["FlightDate"] = pd.to_datetime(result["FlightDate"], errors="coerce")
    for column in NUMERIC_COLUMNS.intersection(result.columns):
        result[column] = pd.to_numeric(result[column], errors="coerce").astype("float64")

    for column, (lower, upper) in NUMERIC_RANGES.items():
        if column in result:
            result[column] = result[column].where(
                result[column].between(lower, upper)
            )
    for column in BOOLEAN_COLUMNS.intersection(result.columns):
        result[column] = result[column].where(result[column].isin([0, 1]))

    for column in TIME_COLUMNS.intersection(result.columns):
        time_value = result[column]
        hour = time_value // 100
        minute = time_value % 100
        valid_time = (
            time_value.isna()
            | (
                time_value.between(0, 2400)
                & (minute < 60)
                & minute.mod(1).eq(0)
                & ((hour < 24) | time_value.eq(2400))
            )
        )
        result.loc[~valid_time, column] = pd.NA

    if year < 1987 or not 1 <= month <= 12:
        raise ValueError("Expected a valid BTS reporting year and month.")
    period_start = pd.Timestamp(year=year, month=month, day=1)
    last_day = calendar.monthrange(year, month)[1]
    period_end = pd.Timestamp(year=year, month=month, day=last_day) + pd.Timedelta(
        days=1, microseconds=-1
    )
    in_period = result["FlightDate"].between(
        period_start, period_end
    )
    identity_present = (
        result["Reporting_Airline"].notna()
        & result["Reporting_Airline"].ne("")
        & result["Origin"].notna()
        & result["Origin"].ne("")
        & result["Dest"].notna()
        & result["Dest"].ne("")
    )
    result = result.loc[result["FlightDate"].notna() & in_period & identity_present]
    result = result.drop_duplicates(keep="first")

    if result.empty:
        return create_features(result.reset_index(drop=True))
    return create_features(result.reset_index(drop=True))


def read_csv_chunks(
    path: Path,
    chunksize: int = 50_000,
    drop_columns: set[str] | None = None,
) -> Iterator[pd.DataFrame]:
    """Yield CSV records in bounded chunks using BTS-friendly UTF-8 decoding."""
    if chunksize < 1:
        raise ValueError("chunksize must be a positive integer.")
    if not path.is_file():
        raise FileNotFoundError(f"CSV file not found: {path}")
    if path.suffix.lower() != ".csv":
        raise ValueError(f"Expected a CSV input file, got: {path.name}")
    try:
        for chunk in pd.read_csv(
            path,
            chunksize=chunksize,
            encoding="utf-8-sig",
            low_memory=False,
            dtype="string",
        ):
            drop = drop_columns.intersection(chunk.columns) if drop_columns else set()
            yield chunk.drop(columns=drop)
    except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        raise ValueError(f"Unable to read valid BTS CSV input {path}: {exc}") from exc
