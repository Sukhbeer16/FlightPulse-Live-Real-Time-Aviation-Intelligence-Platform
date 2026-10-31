"""Small synthetic Spark tests for the historical analytics transformations."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from pyspark.sql import SparkSession

from pipelines.spark.aviation_analytics import (
    ANALYTICS_INPUT_SCHEMA,
    _write_grouped_parquet,
    build_airline_analytics,
    build_day_of_week_analytics,
    build_delay_distribution,
    build_destination_airport_analytics,
    build_hourly_analytics,
    build_origin_airport_analytics,
    build_route_analytics,
    prepare_analytics_frame,
    read_analytics_input,
)
from pipelines.spark.session import create_spark_session


@pytest.fixture(scope="session")
def spark() -> SparkSession:
    session = create_spark_session(app_name="FlightPulseTests")
    yield session
    session.stop()


@pytest.fixture
def analytics_frame(spark: SparkSession):
    rows = [
        ("AA", "AAA", "BBB", 815, 830, 20, 1010, 1030, 20, 0, 0, 0),
        ("AA", "AAA", "CCC", 1260, 900, 15, 1100, 1105, 15, 0, 0, 0),
        ("AA", "AAA", "BBB", 2400, None, None, 2400, None, None, 0, 0, 6),
        ("BB", "BBB", "AAA", 500, 510, 10, 700, 710, -5, 0, 0, 6),
        ("BB", "BBB", "AAA", 600, 630, 30, 800, 830, 180, 0, 1, 1),
        ("BB", "BBB", "AAA", 700, 715, 15, 900, 915, 60, 1, 0, 1),
        ("AA", "AAA", "BBB", 700, 725, 25, 900, 945, None, 0, 0, 2),
        ("AA", "AAA", "BBB", 800, 815, 100, 900, 945, 181, 0, 0, 2),
        ("AA", "AAA", "BBB", 900, None, None, 1000, 1030, 30, 0, 0, 2),
    ]
    normalized_rows = [
        tuple(
            float(value)
            if value is not None and 3 <= index <= 10
            else value
            for index, value in enumerate(row)
        )
        for row in rows
    ]
    return prepare_analytics_frame(
        spark.createDataFrame(normalized_rows, ANALYTICS_INPUT_SCHEMA)
    )


def test_airline_metrics_and_null_delay_eligibility(analytics_frame) -> None:
    metrics = {
        row["Reporting_Airline"]: row
        for row in build_airline_analytics(analytics_frame).collect()
    }

    assert metrics["AA"]["total_flights"] == 6
    assert metrics["AA"]["eligible_delay_records"] == 4
    assert metrics["AA"]["delayed_flights"] == 3
    assert metrics["AA"]["cancelled_flights"] == 0
    assert metrics["AA"]["diverted_flights"] == 0
    assert metrics["AA"]["delay_rate"] == pytest.approx(0.75)
    assert metrics["BB"]["total_flights"] == 3
    assert metrics["BB"]["eligible_delay_records"] == 1
    assert metrics["BB"]["cancelled_flights"] == 1
    assert metrics["BB"]["diverted_flights"] == 1
    assert metrics["BB"]["cancellation_rate"] == pytest.approx(1 / 3)


def test_origin_and_destination_measures_are_separate(analytics_frame) -> None:
    origins = {row["Origin"]: row for row in build_origin_airport_analytics(analytics_frame).collect()}
    destinations = {
        row["Dest"]: row
        for row in build_destination_airport_analytics(analytics_frame).collect()
    }

    assert origins["AAA"]["total_departures"] == 6
    assert origins["AAA"]["eligible_departure_records"] == 4
    assert origins["AAA"]["delayed_departures"] == 3
    assert origins["BBB"]["total_departures"] == 3
    assert origins["BBB"]["cancelled_departures"] == 1
    assert origins["BBB"]["diverted_departures"] == 1
    assert destinations["BBB"]["total_arrivals"] == 5
    assert destinations["BBB"]["eligible_arrivals"] == 3
    assert destinations["BBB"]["delayed_arrivals"] == 3
    assert destinations["AAA"]["eligible_arrivals"] == 1


def test_route_metrics_and_minimum_sample_filter(analytics_frame) -> None:
    routes = build_route_analytics(analytics_frame)
    all_routes = {row["route"]: row for row in routes.collect()}
    assert len(all_routes) == 3
    assert all_routes["AAA-BBB"]["total_flights"] == 5
    assert all_routes["AAA-BBB"]["eligible_flights"] == 3
    assert all_routes["AAA-BBB"]["delayed_flights"] == 3
    assert all_routes["AAA-BBB"]["cancellation_rate"] == 0
    assert routes.filter("total_flights >= 4").count() == 1


def test_hourly_scheduled_actual_times_and_invalid_clock_handling(
    analytics_frame,
) -> None:
    rows = build_hourly_analytics(analytics_frame).collect()
    hourly = {
        (row["time_basis"], row["hour"]): row
        for row in rows
    }

    assert ("scheduled_departure", 12) not in hourly
    assert hourly[("scheduled_departure", 8)]["flights_in_hour"] == 2
    assert hourly[("scheduled_departure", 0)]["flights_in_hour"] == 1
    assert hourly[("scheduled_departure", 0)]["eligible_delay_records"] == 0
    assert hourly[("actual_departure", 8)]["flights_in_hour"] == 2
    assert hourly[("scheduled_arrival", 10)]["eligible_delay_records"] == 2
    assert hourly[("actual_arrival", 10)]["eligible_delay_records"] == 2


def test_day_of_week_aggregation(analytics_frame) -> None:
    rows = {
        row["day_of_week"]: row
        for row in build_day_of_week_analytics(analytics_frame).collect()
    }
    assert rows[0]["total_flights"] == 2
    assert rows[1]["total_flights"] == 2
    assert rows[2]["total_flights"] == 3
    assert rows[6]["total_flights"] == 2
    assert sum(row["total_flights"] for row in rows.values()) == 9


def test_delay_distribution_thresholds_percentiles_and_nulls(
    analytics_frame,
) -> None:
    rows = build_delay_distribution(analytics_frame).collect()
    categories = {
        (row["delay_type"], row["category"]): row
        for row in rows
        if row["statistic"] == "category"
    }
    percentiles = [row for row in rows if row["statistic"] == "percentile"]

    assert categories[("arrival", "early")]["flight_count"] == 1
    assert categories[("arrival", "on_time")]["flight_count"] == 1
    assert categories[("arrival", "delayed")]["flight_count"] == 2
    assert categories[("arrival", "extreme")]["flight_count"] == 1
    assert sum(
        row["flight_count"] or 0
        for row in rows
        if row["statistic"] == "category" and row["delay_type"] == "departure"
    ) == 6
    assert len(percentiles) == 8
    assert all(row["delay_minutes"] is not None for row in percentiles)


def test_explicit_projection_reads_nanos_timestamp_without_rewriting_source(
    spark: SparkSession, tmp_path: Path
) -> None:
    fields = {
        "Reporting_Airline": pa.array(["AA"], type=pa.string()),
        "Origin": pa.array(["AAA"], type=pa.string()),
        "Dest": pa.array(["BBB"], type=pa.string()),
        "CRSDepTime": pa.array([800.0], type=pa.float64()),
        "DepTime": pa.array([805.0], type=pa.float64()),
        "DepDelay": pa.array([5.0], type=pa.float64()),
        "CRSArrTime": pa.array([1000.0], type=pa.float64()),
        "ArrTime": pa.array([1005.0], type=pa.float64()),
        "ArrDelay": pa.array([5.0], type=pa.float64()),
        "Cancelled": pa.array([0.0], type=pa.float64()),
        "Diverted": pa.array([0.0], type=pa.float64()),
        "day_of_week": pa.array([0], type=pa.int8()),
        "Month": pa.array([1], type=pa.int8()),
        "month": pa.array([1], type=pa.int8()),
        "FlightDate": pa.array([1_730_000_000_000_000_000], type=pa.timestamp("ns")),
    }
    source = tmp_path / "nanos-input.parquet"
    pq.write_table(pa.table(fields), source)

    projected = read_analytics_input(spark, source)

    assert projected.count() == 1
    assert "FlightDate" not in projected.columns
    assert projected.schema["ArrDelay"].dataType.simpleString() == "double"


def test_grouped_parquet_writer_creates_readable_zstd_output(
    analytics_frame, tmp_path: Path
) -> None:
    output = tmp_path / "airline_analytics.parquet"
    table = _write_grouped_parquet(build_airline_analytics(analytics_frame), output)
    reopened = pq.read_table(output)

    assert table.num_rows == 2
    assert reopened.num_rows == 2
    assert pq.ParquetFile(output).metadata.row_group(0).column(0).compression == "ZSTD"
