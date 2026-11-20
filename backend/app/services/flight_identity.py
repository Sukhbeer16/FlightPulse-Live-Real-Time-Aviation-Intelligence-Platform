"""Safe, explicit-confidence matching against historical BTS identifiers."""

from __future__ import annotations

from datetime import date, datetime

import pyarrow.parquet as parquet

from backend.app.config.settings import get_settings
from backend.app.services.opensky import parse_callsign_flight_identity


SOURCE_FILE = "bts_ontime_2024_02.parquet"
BATCH_SIZE = 4096


def match_historical_callsign(
    callsign: str,
    flight_date: date,
) -> dict[str, object]:
    parsed = parse_callsign_flight_identity(callsign)
    if parsed is None:
        return {
            "callsign": callsign.strip().upper(),
            "flight_date": flight_date.isoformat(),
            "confidence": "none",
            "matched": False,
            "candidate_count": 0,
            "explanation": (
                "Callsign format did not provide an explicit airline prefix and numeric flight number."
            ),
        }
    airline_code, flight_number = parsed
    path = get_settings().data_directory / "processed" / "monthly" / SOURCE_FILE
    if not path.is_file():
        return {
            "callsign": callsign.strip().upper(),
            "flight_date": flight_date.isoformat(),
            "confidence": "none",
            "matched": False,
            "candidate_count": 0,
            "explanation": "Historical flight records are unavailable for matching.",
        }
    candidates: set[tuple[str, str, str, str]] = set()
    try:
        parquet_file = parquet.ParquetFile(path)
        required = {
            "FlightDate",
            "Reporting_Airline",
            "Flight_Number_Reporting_Airline",
            "Origin",
            "Dest",
        }
        if not required.issubset(set(parquet_file.schema.names)):
            raise ValueError("missing historical identity fields")
        for batch in parquet_file.iter_batches(
            batch_size=BATCH_SIZE,
            columns=[
                "FlightDate",
                "Reporting_Airline",
                "Flight_Number_Reporting_Airline",
                "Origin",
                "Dest",
            ],
        ):
            values = batch.to_pydict()
            for index in range(batch.num_rows):
                source_date = values["FlightDate"][index]
                if isinstance(source_date, datetime):
                    source_date = source_date.date()
                if source_date != flight_date:
                    continue
                reporting_airline = values["Reporting_Airline"][index]
                source_flight_number = values[
                    "Flight_Number_Reporting_Airline"
                ][index]
                if (
                    reporting_airline is not None
                    and str(reporting_airline).strip().upper() == airline_code
                    and source_flight_number is not None
                    and str(source_flight_number).strip() == flight_number
                ):
                    candidates.add(
                        (
                            airline_code,
                            flight_number,
                            str(values["Origin"][index] or "").strip(),
                            str(values["Dest"][index] or "").strip(),
                        )
                    )
    except Exception:
        return {
            "callsign": callsign.strip().upper(),
            "flight_date": flight_date.isoformat(),
            "confidence": "uncertain",
            "matched": False,
            "candidate_count": 0,
            "explanation": "Historical matching could not be completed safely.",
        }
    if len(candidates) == 1:
        _, number, origin, destination = next(iter(candidates))
        return {
            "callsign": callsign.strip().upper(),
            "flight_date": flight_date.isoformat(),
            "confidence": "medium",
            "matched": True,
            "airline_code": airline_code,
            "flight_number": number,
            "origin": origin or None,
            "destination": destination or None,
            "candidate_count": 1,
            "explanation": (
                "A single historical airline/flight-number/route candidate matched "
                "the date. This is not live schedule confirmation."
            ),
        }
    if len(candidates) > 1:
        return {
            "callsign": callsign.strip().upper(),
            "flight_date": flight_date.isoformat(),
            "confidence": "uncertain",
            "matched": False,
            "candidate_count": len(candidates),
            "explanation": (
                "Multiple historical route candidates were found; ambiguous matches are rejected."
            ),
        }
    return {
        "callsign": callsign.strip().upper(),
        "flight_date": flight_date.isoformat(),
        "confidence": "none",
        "matched": False,
        "candidate_count": 0,
        "explanation": "No historical candidate matched the callsign identity and date.",
    }
