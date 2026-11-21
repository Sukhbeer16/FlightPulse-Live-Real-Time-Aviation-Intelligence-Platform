"""Paged, read-only queries over the January and February BTS Parquet sources."""

from datetime import date
from pathlib import Path

import duckdb
import pyarrow.parquet as parquet

from backend.app.config.settings import get_settings
from backend.app.schemas.historical import ProcessedParquetFlightRead

SOURCE_FILE = "bts_ontime_2024_02.parquet"
SOURCE_PERIOD = "2024-01 to 2024-02"
COLUMNS = {
    "FlightDate": ("flight_date", "DATE"),
    "Reporting_Airline": ("reporting_airline", "VARCHAR"),
    "Origin": ("origin_bts_code", "VARCHAR"),
    "Dest": ("destination_bts_code", "VARCHAR"),
    "Flight_Number_Reporting_Airline": ("flight_number", "VARCHAR"),
    "CRSDepTime": ("scheduled_departure_local_hhmm", "INTEGER"),
    "DepTime": ("actual_departure_local_hhmm", "INTEGER"),
    "CRSArrTime": ("scheduled_arrival_local_hhmm", "INTEGER"),
    "ArrTime": ("actual_arrival_local_hhmm", "INTEGER"),
    "DepDelay": ("departure_delay_minutes", "DOUBLE"),
    "ArrDelay": ("arrival_delay_minutes", "DOUBLE"),
    "Cancelled": ("cancelled", "INTEGER"),
    "Diverted": ("diverted", "INTEGER"),
    "CancellationCode": ("cancellation_code", "VARCHAR"),
    "Distance": ("distance_miles", "DOUBLE"),
    "CRSElapsedTime": ("scheduled_elapsed_time_minutes", "DOUBLE"),
}


class HistoricalParquetUnavailable(RuntimeError):
    pass


def source_query(path):
    with parquet.ParquetFile(path) as file:
        if path.stat().st_size > 512 * 1024**2 or file.metadata.num_rows > 5_000_000:
            raise HistoricalParquetUnavailable(
                "Parquet source exceeds local query limits"
            )
        names = set(file.schema.names)
    if not {"FlightDate", "Reporting_Airline", "Origin", "Dest"} <= names:
        raise HistoricalParquetUnavailable("Missing required BTS columns")
    fields = [
        f"CAST({name if name in names else 'NULL'} AS {kind}) AS {alias}"
        for name, (alias, kind) in COLUMNS.items()
    ]
    return (
        "SELECT ? AS source_file, file_row_number + 1 AS source_row_number, "
        + ", ".join(fields)
        + " FROM read_parquet(?, file_row_number=true)"
    )


def search_processed_flights(
    *,
    page,
    page_size,
    flight_number=None,
    airline_code=None,
    origin=None,
    destination=None,
    flight_date: date | None = None,
    cancelled=None,
    diverted=None,
    delayed=None,
    flight_identifier=None,
    date_from=None,
    date_to=None,
    departure_delay_min=None,
    departure_delay_max=None,
    arrival_delay_min=None,
    arrival_delay_max=None,
    sort_by="source_row",
    sort_order="asc",
):
    root = get_settings().data_directory / "processed"
    paths = [
        p
        for p in (root / "monthly" / SOURCE_FILE, root / "bts_ontime_2024_01.parquet")
        if p.is_file()
    ]
    if not paths:
        raise HistoricalParquetUnavailable("No monthly BTS source is available")
    try:
        union = " UNION ALL ".join(source_query(path) for path in paths)
        params = [value for path in paths for value in (path.name, str(path))]
        filters = []
        for expression, value in (
            ("flight_number = ?", flight_number),
            ("flight_number = ?", flight_identifier),
            ("upper(reporting_airline) = upper(?)", airline_code),
            ("upper(origin_bts_code) = upper(?)", origin),
            ("upper(destination_bts_code) = upper(?)", destination),
            ("flight_date = ?", flight_date),
            ("flight_date >= ?", date_from),
            ("flight_date <= ?", date_to),
            ("cancelled = ?", cancelled),
            ("diverted = ?", diverted),
            ("(arrival_delay_minutes > 15) = ?", delayed),
            ("departure_delay_minutes >= ?", departure_delay_min),
            ("departure_delay_minutes <= ?", departure_delay_max),
            ("arrival_delay_minutes >= ?", arrival_delay_min),
            ("arrival_delay_minutes <= ?", arrival_delay_max),
        ):
            if value is not None:
                filters.append(expression)
                params.append(value.strip() if isinstance(value, str) else value)
        query = f" FROM ({union}) AS flights"
        if filters:
            query += " WHERE " + " AND ".join(filters)
        column = {
            "source_row": "source_file DESC, source_row_number",
            "flight_date": "flight_date",
            "flight_number": "flight_number",
            "departure_delay": "departure_delay_minutes",
            "arrival_delay": "arrival_delay_minutes",
        }[sort_by]
        direction = {"asc": "ASC", "desc": "DESC"}[sort_order]
        with duckdb.connect(config={"threads": 2, "memory_limit": "256MB"}) as db:
            total = db.execute("SELECT count(*)" + query, params).fetchone()[0]
            cursor = db.execute(
                "SELECT *"
                + query
                + f" ORDER BY {column} {direction}, source_file, source_row_number LIMIT ? OFFSET ?",
                [*params, page_size, (page - 1) * page_size],
            )
            fields = [column[0] for column in cursor.description]
            return [
                ProcessedParquetFlightRead(**dict(zip(fields, row)))
                for row in cursor.fetchall()
            ], total
    except (duckdb.Error, OSError, ValueError) as exc:
        raise HistoricalParquetUnavailable(
            "Historical source could not be queried"
        ) from exc
