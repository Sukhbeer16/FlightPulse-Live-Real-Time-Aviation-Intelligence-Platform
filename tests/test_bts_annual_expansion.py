"""Tests for safe, month-scoped BTS annual dataset expansion."""

import zipfile
from pathlib import Path

import pandas as pd
import pytest

from pipelines.ingestion.bts_annual_expansion import (
    _month_paths,
    _month_metrics,
    _source_exclusion_counts,
    _validate_reconciliation,
)
from pipelines.ingestion.bts_ingestion import _validate_bts_archive
from pipelines.ingestion.data_cleaning import clean_dataframe
from pipelines.ingestion.data_validation import validate_csv


def _bts_row(day: str, flight_number: str = "100") -> dict[str, str]:
    return {
        "FlightDate": day,
        "Reporting_Airline": "AA",
        "Flight_Number_Reporting_Airline": flight_number,
        "Origin": "JFK",
        "Dest": "LAX",
        "CRSDepTime": "745",
        "Cancelled": "0",
        "Diverted": "0",
        "ArrDelay": "10",
        "Distance": "2475",
        "CRSElapsedTime": "375",
    }


def test_month_paths_match_bts_archive_member_naming(tmp_path: Path, monkeypatch) -> None:
    from pipelines.ingestion import bts_annual_expansion

    monkeypatch.setattr(bts_annual_expansion, "RAW_DIRECTORY", tmp_path / "raw")
    monkeypatch.setattr(
        bts_annual_expansion, "MONTHLY_DIRECTORY", tmp_path / "processed" / "monthly"
    )

    archive_name, csv_name, archive_path, csv_path, parquet_path = _month_paths(2)

    assert archive_name.endswith("_2024_2.zip")
    assert csv_name.endswith("_(1987_present)_2024_2.csv")
    assert archive_path.name == archive_name
    assert csv_path.name == csv_name
    assert parquet_path.name == "bts_ontime_2024_02.parquet"


def test_month_scoped_validation_uses_requested_reporting_period(
    tmp_path: Path,
) -> None:
    rows = pd.DataFrame(
        [
            _bts_row("2024-02-01"),
            _bts_row("2024-01-31", "101"),
            _bts_row("not-a-date", "102"),
        ]
    )
    path = tmp_path / "february.csv"
    rows.to_csv(path, index=False)

    report = validate_csv(path, chunksize=1, year=2024, month=2)

    assert report["reporting_month"] == 2
    assert report["out_of_scope_date_rows"] == 1
    assert report["invalid_date_rows"] == 1


def test_month_scoped_cleaning_preserves_only_requested_month() -> None:
    frame = pd.DataFrame(
        [
            _bts_row("2024-02-01"),
            _bts_row("2024-01-31", "101"),
        ]
    )

    result = clean_dataframe(frame, year=2024, month=2)

    assert len(result) == 1
    assert result["FlightDate"].dt.month.tolist() == [2]


def test_source_exclusions_are_disjoint_and_explicit() -> None:
    frame = pd.DataFrame(
        [
            _bts_row("2024-02-01"),
            _bts_row("", "101"),
            _bts_row("invalid", "102"),
            _bts_row("2024-03-01", "103"),
            {
                **_bts_row("2024-02-02", "104"),
                "Dest": "",
            },
        ]
    )

    retained, excluded = _source_exclusion_counts(frame, 2024, 2)

    assert len(retained) == 1
    assert excluded == {
        "missing_date": 1,
        "invalid_date": 1,
        "out_of_reporting_period": 1,
        "missing_flight_identity": 1,
    }


def test_month_metrics_reconcile_target_and_disjoint_statuses() -> None:
    frame = pd.DataFrame(
        {
            "Cancelled": [0.0, 1.0, 0.0, 0.0],
            "Diverted": [0.0, 0.0, 1.0, 0.0],
            "ArrDelay": [15.0, None, None, 16.0],
            "Reporting_Airline": ["AA", "AA", "DL", "DL"],
            "Origin": ["JFK", "JFK", "ATL", "ATL"],
            "Dest": ["LAX", "LAX", "ORD", "ORD"],
        }
    )

    metrics = _month_metrics(frame, validate=True)

    assert metrics["total_records"] == 4
    assert metrics["cancelled"] == 1
    assert metrics["diverted"] == 1
    assert metrics["eligible_arrival"] == 2
    assert metrics["delayed"] == 1
    assert metrics["non_delayed"] == 1
    assert metrics["null_arrival_delay"] == 2


def test_reconciliation_rejects_mismatched_flight_counts() -> None:
    with pytest.raises(ValueError, match="reconciliation failed"):
        _validate_reconciliation(
            {
                "total_records": 10,
                "cancelled": 2,
                "diverted": 1,
                "eligible_arrival": 6,
                "delayed": 2,
                "non_delayed": 4,
                "cancelled_and_diverted_overlap": 0,
            }
        )


def test_month_archive_validator_checks_the_expected_member(tmp_path: Path) -> None:
    member = (
        "On_Time_Reporting_Carrier_On_Time_Performance_"
        "(1987_present)_2024_2.csv"
    )
    archive_path = tmp_path / "february.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, "FlightDate\n2024-02-01\n")

    _validate_bts_archive(archive_path, member)
    with pytest.raises(ValueError, match="Expected exactly"):
        _validate_bts_archive(archive_path, "incorrect.csv")
