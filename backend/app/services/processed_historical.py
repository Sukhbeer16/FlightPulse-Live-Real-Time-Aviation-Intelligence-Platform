"""Bounded, read-only record search over the existing February BTS Parquet."""

from __future__ import annotations

from datetime import date, datetime
from math import isfinite
from pathlib import Path
from typing import Any
import sqlite3
import tempfile

from backend.app.config.settings import get_settings
from backend.app.schemas.historical import ProcessedParquetFlightRead


SOURCE_FILE = "bts_ontime_2024_02.parquet"
SOURCE_PERIOD = "2024-02"
BATCH_SIZE = 4_096
MAX_SOURCE_BYTES = 512 * 1024 * 1024
MAX_SOURCE_ROWS = 5_000_000
REQUIRED_COLUMNS = {"FlightDate", "Reporting_Airline", "Origin", "Dest"}
OPTIONAL_COLUMNS = (
    "Flight_Number_Reporting_Airline",
    "CRSDepTime",
    "DepTime",
    "CRSArrTime",
    "ArrTime",
    "DepDelay",
    "ArrDelay",
    "Cancelled",
    "Diverted",
    "CancellationCode",
)


class HistoricalParquetUnavailable(RuntimeError):
    """The bounded historical source file is missing or incompatible."""


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise HistoricalParquetUnavailable("A source flight date is invalid.")


def _as_string(value: Any) -> str | None:
    return None if value is None else str(value)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if isfinite(result) else None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    return int(number) if number is not None and number.is_integer() else None


def _matches(
    row: dict[str, Any],
    *,
    flight_number: str | None,
    airline_code: str | None,
    origin: str | None,
    destination: str | None,
    flight_date: date | None,
    cancelled: bool | None,
    diverted: bool | None,
    delayed: bool | None,
    flight_identifier: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    departure_delay_min: float | None = None,
    departure_delay_max: float | None = None,
    arrival_delay_min: float | None = None,
    arrival_delay_max: float | None = None,
) -> bool:
    def code_matches(field: str, query: str | None) -> bool:
        return query is None or (
            row.get(field) is not None
            and str(row[field]).strip().upper() == query.strip().upper()
        )

    if not code_matches("Reporting_Airline", airline_code):
        return False
    if not code_matches("Origin", origin) or not code_matches("Dest", destination):
        return False
    source_flight_number = row.get("Flight_Number_Reporting_Airline")
    if flight_identifier is not None:
        identifier = str(source_flight_number).strip() if source_flight_number is not None else ""
        if identifier != flight_identifier.strip():
            return False
    if flight_number is not None and (
        source_flight_number is None or str(source_flight_number) != flight_number
    ):
        return False
    row_date = _as_date(row.get("FlightDate"))
    if flight_date is not None and row_date != flight_date:
        return False
    if date_from is not None and row_date < date_from:
        return False
    if date_to is not None and row_date > date_to:
        return False
    row_cancelled = _as_int(row.get("Cancelled"))
    row_diverted = _as_int(row.get("Diverted"))
    if cancelled is not None and row_cancelled != int(cancelled):
        return False
    if diverted is not None and row_diverted != int(diverted):
        return False
    if delayed is not None:
        arrival_delay = _as_float(row.get("ArrDelay"))
        if arrival_delay is None or (arrival_delay > 15) != delayed:
            return False
    departure_delay = _as_float(row.get("DepDelay"))
    arrival_delay = _as_float(row.get("ArrDelay"))
    if departure_delay_min is not None and (
        departure_delay is None or departure_delay < departure_delay_min
    ):
        return False
    if departure_delay_max is not None and (
        departure_delay is None or departure_delay > departure_delay_max
    ):
        return False
    if arrival_delay_min is not None and (
        arrival_delay is None or arrival_delay < arrival_delay_min
    ):
        return False
    if arrival_delay_max is not None and (
        arrival_delay is None or arrival_delay > arrival_delay_max
    ):
        return False
    return True


def search_processed_flights(
    *,
    page: int,
    page_size: int,
    flight_number: str | None = None,
    airline_code: str | None = None,
    origin: str | None = None,
    destination: str | None = None,
    flight_date: date | None = None,
    cancelled: bool | None = None,
    diverted: bool | None = None,
    delayed: bool | None = None,
    flight_identifier: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    departure_delay_min: float | None = None,
    departure_delay_max: float | None = None,
    arrival_delay_min: float | None = None,
    arrival_delay_max: float | None = None,
    sort_by: str = "source_row",
    sort_order: str = "asc",
) -> tuple[list[ProcessedParquetFlightRead], int]:
    """Scan in fixed-size projected Arrow batches; retain only the requested page."""
    path = get_settings().data_directory / "processed" / "monthly" / SOURCE_FILE
    try:
        if not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
            raise HistoricalParquetUnavailable(
                "The processed historical source is unavailable."
            )
        import pyarrow.parquet as parquet

        parquet_file = parquet.ParquetFile(path)
        if parquet_file.metadata.num_rows > MAX_SOURCE_ROWS:
            raise HistoricalParquetUnavailable(
                "The processed source exceeds the configured row limit."
            )
        if REQUIRED_COLUMNS - set(parquet_file.schema.names):
            raise HistoricalParquetUnavailable(
                "The processed source schema is missing required flight fields."
            )
        columns = [
            "FlightDate",
            "Reporting_Airline",
            "Origin",
            "Dest",
            *[name for name in OPTIONAL_COLUMNS if name in parquet_file.schema.names],
        ]
        start = (page - 1) * page_size
        stop = start + page_size
        total = 0
        selected: list[ProcessedParquetFlightRead] = []
        source_row_number = 0
        requires_sort = sort_by != "source_row" or sort_order == "desc"
        temp_database: sqlite3.Connection | None = None
        temp_path: str | None = None
        if requires_sort:
            temp_file = tempfile.NamedTemporaryFile(
                prefix="flightpulse-historical-sort-", suffix=".sqlite", delete=False
            )
            temp_path = temp_file.name
            temp_file.close()
            temp_database = sqlite3.connect(temp_path)
            temp_database.execute(
                """
                CREATE TABLE matches (
                    source_row INTEGER PRIMARY KEY,
                    flight_date TEXT,
                    flight_number TEXT,
                    reporting_airline TEXT,
                    origin TEXT,
                    destination TEXT,
                    scheduled_dep INTEGER,
                    actual_dep INTEGER,
                    scheduled_arr INTEGER,
                    actual_arr INTEGER,
                    dep_delay REAL,
                    arr_delay REAL,
                    cancelled INTEGER,
                    diverted INTEGER,
                    cancellation_code TEXT
                )
                """
            )
        for batch in parquet_file.iter_batches(
            batch_size=BATCH_SIZE, columns=columns
        ):
            values = batch.to_pydict()
            for offset in range(batch.num_rows):
                source_row_number += 1
                row = {name: values[name][offset] for name in columns}
                _as_date(row["FlightDate"])
                if not _matches(
                    row,
                    flight_number=flight_number,
                    airline_code=airline_code,
                    origin=origin,
                    destination=destination,
                    flight_date=flight_date,
                    cancelled=cancelled,
                    diverted=diverted,
                    delayed=delayed,
                    flight_identifier=flight_identifier,
                    date_from=date_from,
                    date_to=date_to,
                    departure_delay_min=departure_delay_min,
                    departure_delay_max=departure_delay_max,
                    arrival_delay_min=arrival_delay_min,
                    arrival_delay_max=arrival_delay_max,
                ):
                    continue
                flight_read = ProcessedParquetFlightRead(
                    source_file=SOURCE_FILE,
                    source_row_number=source_row_number,
                    flight_date=_as_date(row["FlightDate"]),
                    reporting_airline=_as_string(
                        row.get("Reporting_Airline")
                    ),
                    flight_number=_as_string(
                        row.get("Flight_Number_Reporting_Airline")
                    ),
                    origin_bts_code=_as_string(row.get("Origin")),
                    destination_bts_code=_as_string(row.get("Dest")),
                    scheduled_departure_local_hhmm=_as_int(
                        row.get("CRSDepTime")
                    ),
                    actual_departure_local_hhmm=_as_int(row.get("DepTime")),
                    scheduled_arrival_local_hhmm=_as_int(
                        row.get("CRSArrTime")
                    ),
                    actual_arrival_local_hhmm=_as_int(row.get("ArrTime")),
                    departure_delay_minutes=_as_float(row.get("DepDelay")),
                    arrival_delay_minutes=_as_float(row.get("ArrDelay")),
                    cancelled=_as_int(row.get("Cancelled")),
                    diverted=_as_int(row.get("Diverted")),
                    cancellation_code=_as_string(row.get("CancellationCode")),
                )
                if temp_database is not None:
                    temp_database.execute(
                        "INSERT INTO matches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            source_row_number,
                            flight_read.flight_date.isoformat(),
                            flight_read.flight_number,
                            flight_read.reporting_airline,
                            flight_read.origin_bts_code,
                            flight_read.destination_bts_code,
                            flight_read.scheduled_departure_local_hhmm,
                            flight_read.actual_departure_local_hhmm,
                            flight_read.scheduled_arrival_local_hhmm,
                            flight_read.actual_arrival_local_hhmm,
                            flight_read.departure_delay_minutes,
                            flight_read.arrival_delay_minutes,
                            flight_read.cancelled,
                            flight_read.diverted,
                            flight_read.cancellation_code,
                        ),
                    )
                elif start <= total < stop:
                    selected.append(
                        flight_read
                    )
                total += 1
        if temp_database is not None:
            temp_database.commit()
            total = int(temp_database.execute("SELECT count(*) FROM matches").fetchone()[0])
            column = {
                "source_row": "source_row",
                "flight_date": "flight_date",
                "flight_number": "flight_number",
                "departure_delay": "dep_delay",
                "arrival_delay": "arr_delay",
            }[sort_by]
            direction = "DESC" if sort_order == "desc" else "ASC"
            rows = temp_database.execute(
                f"SELECT * FROM matches ORDER BY {column} {direction}, source_row ASC LIMIT ? OFFSET ?",
                (page_size, start),
            ).fetchall()
            temp_database.close()
            Path(temp_path).unlink(missing_ok=True)
            selected = [
                ProcessedParquetFlightRead(
                    source_file=SOURCE_FILE,
                    source_row_number=int(row[0]),
                    flight_date=_as_date(row[1]),
                    reporting_airline=row[3],
                    flight_number=row[2],
                    origin_bts_code=row[4],
                    destination_bts_code=row[5],
                    scheduled_departure_local_hhmm=row[6],
                    actual_departure_local_hhmm=row[7],
                    scheduled_arrival_local_hhmm=row[8],
                    actual_arrival_local_hhmm=row[9],
                    departure_delay_minutes=row[10],
                    arrival_delay_minutes=row[11],
                    cancelled=row[12],
                    diverted=row[13],
                    cancellation_code=row[14],
                )
                for row in rows
            ]
        return selected, total
    except HistoricalParquetUnavailable:
        raise
    except Exception as error:
        raise HistoricalParquetUnavailable(
            "The processed historical source could not be read."
        ) from error
