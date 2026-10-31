"""Chunk-free, local Spark analytics for the historical BTS flight dataset."""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from pyspark.errors import PySparkException
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    ByteType,
    DoubleType,
    StringType,
    StructField,
    StructType,
)
from pyspark.sql.window import Window
from pyspark.storagelevel import StorageLevel

from pipelines.spark.bts_validation import EXPECTED_METRICS
from pipelines.spark.session import create_spark_session


DEFAULT_INPUT_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "processed"
    / "bts_ontime_2024_01.parquet"
)
DEFAULT_OUTPUT_DIRECTORY = DEFAULT_INPUT_PATH.parent / "analytics"
DEFAULT_MIN_ROUTE_FLIGHTS = 30
PERCENTILE_ACCURACY = 1_000
DELAY_PERCENTILES = (0.50, 0.90, 0.95, 0.99)

ANALYTICS_INPUT_SCHEMA = StructType(
    [
        StructField("Reporting_Airline", StringType(), True),
        StructField("Origin", StringType(), True),
        StructField("Dest", StringType(), True),
        StructField("CRSDepTime", DoubleType(), True),
        StructField("DepTime", DoubleType(), True),
        StructField("DepDelay", DoubleType(), True),
        StructField("CRSArrTime", DoubleType(), True),
        StructField("ArrTime", DoubleType(), True),
        StructField("ArrDelay", DoubleType(), True),
        StructField("Cancelled", DoubleType(), True),
        StructField("Diverted", DoubleType(), True),
        StructField("day_of_week", ByteType(), True),
    ]
)

OUTPUT_NAMES = {
    "airline": "airline_analytics.parquet",
    "origin": "origin_airport_analytics.parquet",
    "destination": "destination_airport_analytics.parquet",
    "route": "route_analytics.parquet",
    "hourly": "hourly_analytics.parquet",
    "day_of_week": "day_of_week_analytics.parquet",
    "delay_distribution": "delay_distribution.parquet",
}


def _count(condition: F.Column, name: str) -> F.Column:
    return F.coalesce(F.sum(F.when(condition, 1).otherwise(0)), F.lit(0)).alias(name)


def _valid_measurement(name: str) -> F.Column:
    value = F.col(name)
    return (
        value.isNotNull()
        & ~F.isnan(value)
        & value.between(-1_440, 10_080)
    )


def _hour_from_hhmm(name: str) -> F.Column:
    """Parse a numeric HHMM value; reject malformed clocks and map 2400 to 0."""
    value = F.col(name)
    valid = (
        value.isNotNull()
        & ~F.isnan(value)
        & value.between(0, 2_400)
        & (value == F.floor(value))
        & (F.pmod(value, F.lit(100)) < 60)
        & ((F.floor(value / 100) < 24) | value.eqNullSafe(F.lit(2_400)))
    )
    return F.when(valid, F.pmod(F.floor(value / 100), F.lit(24)).cast("int"))


def read_analytics_input(spark: SparkSession, input_path: Path) -> DataFrame:
    """Read only verified analytics columns, avoiding the nanosecond date field."""
    if not input_path.is_file():
        raise FileNotFoundError(f"BTS Parquet dataset not found: {input_path}")
    try:
        import pyarrow.parquet as parquet

        schema = parquet.ParquetFile(input_path).schema_arrow
    except (OSError, pa.ArrowException) as exc:
        raise ValueError(f"Unable to inspect Parquet metadata at {input_path}: {exc}") from exc

    fields = {field.name: field.type for field in schema}
    expected_types = {
        "Reporting_Airline": pa.types.is_string,
        "Origin": pa.types.is_string,
        "Dest": pa.types.is_string,
        "day_of_week": pa.types.is_integer,
    }
    numeric_fields = {
        "CRSDepTime",
        "DepTime",
        "DepDelay",
        "CRSArrTime",
        "ArrTime",
        "ArrDelay",
        "Cancelled",
        "Diverted",
    }
    missing = {field.name for field in ANALYTICS_INPUT_SCHEMA}.difference(fields)
    if missing:
        raise ValueError(
            f"Parquet schema is missing analytics columns: {sorted(missing)}"
        )
    invalid = [
        name
        for name, predicate in expected_types.items()
        if not predicate(fields[name])
    ]
    invalid.extend(
        name
        for name in numeric_fields
        if not pa.types.is_floating(fields[name])
        and not pa.types.is_integer(fields[name])
    )
    if invalid:
        raise ValueError(
            f"Parquet analytics columns have unexpected types: {sorted(invalid)}"
        )

    return spark.read.schema(ANALYTICS_INPUT_SCHEMA).parquet(
        input_path.resolve().as_uri()
    )


def prepare_analytics_frame(source: DataFrame) -> DataFrame:
    """Normalize identifiers and add validated times and eligibility flags."""
    frame = source
    for key in ("Reporting_Airline", "Origin", "Dest"):
        trimmed = F.trim(F.col(key))
        frame = frame.withColumn(
            key,
            F.when(
                F.col(key).isNotNull() & (F.length(trimmed) > 0), trimmed
            ).otherwise(F.lit(None).cast("string")),
        )

    frame = (
        frame.withColumn(
            "route",
            F.when(
                F.col("Origin").isNotNull() & F.col("Dest").isNotNull(),
                F.concat_ws("-", F.col("Origin"), F.col("Dest")),
            ),
        )
        .withColumn("scheduled_departure_hour", _hour_from_hhmm("CRSDepTime"))
        .withColumn("actual_departure_hour", _hour_from_hhmm("DepTime"))
        .withColumn("scheduled_arrival_hour", _hour_from_hhmm("CRSArrTime"))
        .withColumn("actual_arrival_hour", _hour_from_hhmm("ArrTime"))
        .withColumn(
            "valid_day_of_week",
            F.when(F.col("day_of_week").between(0, 6), F.col("day_of_week")),
        )
    )

    departure_delay_valid = _valid_measurement("DepDelay")
    arrival_delay_valid = _valid_measurement("ArrDelay")
    operating_departure = F.col("Cancelled").eqNullSafe(F.lit(0))
    operating_arrival = (
        operating_departure & F.col("Diverted").eqNullSafe(F.lit(0))
    )
    return (
        frame.withColumn(
            "eligible_departure",
            operating_departure & departure_delay_valid,
        )
        .withColumn(
            "eligible_arrival",
            operating_arrival & arrival_delay_valid,
        )
        .withColumn(
            "delayed_departure",
            operating_departure
            & departure_delay_valid
            & (F.col("DepDelay") > 15),
        )
        .withColumn(
            "delayed_arrival",
            operating_arrival
            & arrival_delay_valid
            & (F.col("ArrDelay") > 15),
        )
    )


def summarize_source(frame: DataFrame) -> dict[str, int]:
    """Measure dataset totals and completeness in one Spark aggregation."""
    cancelled = F.col("Cancelled") == 1
    diverted = F.col("Diverted") == 1
    unknown_status = (
        ~F.coalesce(F.col("Cancelled").isin(0, 1), F.lit(False))
        | ~F.coalesce(F.col("Diverted").isin(0, 1), F.lit(False))
    )
    metrics = frame.agg(
        F.count(F.lit(1)).alias("total_flights"),
        _count(cancelled, "cancelled_flights"),
        _count(diverted, "diverted_flights"),
        _count(
            F.col("eligible_arrival"), "eligible_delay_records"
        ),
        _count(F.col("delayed_arrival"), "delayed_flights"),
        _count(
            F.col("eligible_arrival") & (F.col("ArrDelay") <= 15),
            "non_delayed_eligible_flights",
        ),
        _count(cancelled & diverted, "both_cancelled_and_diverted"),
        _count(unknown_status, "unknown_status"),
        _count(F.col("eligible_arrival") == F.lit(False), "non_eligible_rows"),
        _count(
            F.col("Reporting_Airline").isNull(), "missing_airline"
        ),
        _count(F.col("Origin").isNull(), "missing_origin"),
        _count(F.col("Dest").isNull(), "missing_destination"),
        _count(F.col("route").isNull(), "missing_route"),
        _count(F.col("valid_day_of_week").isNull(), "invalid_day_of_week"),
        *[
            _count(
                F.col(column).isNotNull() & F.col(hour).isNull(),
                f"invalid_{column.lower()}",
            )
            for column, hour in (
                ("CRSDepTime", "scheduled_departure_hour"),
                ("DepTime", "actual_departure_hour"),
                ("CRSArrTime", "scheduled_arrival_hour"),
                ("ArrTime", "actual_arrival_hour"),
            )
        ],
        _count(
            (F.col("Cancelled") == 0)
            & (F.col("Diverted") == 0)
            & ~_valid_measurement("ArrDelay"),
            "operating_rows_without_valid_arrival_delay",
        ),
    ).first()
    return {name: int(metrics[name]) for name in metrics.asDict()}


def assert_source_reconciliation(metrics: dict[str, int]) -> None:
    """Reject incomplete, overlapping, or unexpected Phase 2 source data."""
    for name, expected in EXPECTED_METRICS.items():
        actual = metrics[name]
        if actual != expected:
            raise ValueError(
                f"Source reconciliation failed for {name}: "
                f"expected {expected}, found {actual}."
            )

    if metrics["both_cancelled_and_diverted"] or metrics["unknown_status"]:
        raise ValueError(
            "Cancellation/diversion status contains overlapping or unknown flags."
        )
    if any(
        metrics[name]
        for name in (
            "missing_airline",
            "missing_origin",
            "missing_destination",
            "missing_route",
            "invalid_day_of_week",
            "operating_rows_without_valid_arrival_delay",
        )
    ):
        raise ValueError(
            "Required analytics keys or eligible arrival delays are invalid; "
            "refusing to silently drop records."
        )

    reconciled = (
        metrics["cancelled_flights"]
        + metrics["diverted_flights"]
        + metrics["eligible_delay_records"]
        + metrics["operating_rows_without_valid_arrival_delay"]
    )
    if reconciled != metrics["total_flights"]:
        raise ValueError(
            "Source rows do not reconcile to cancelled, diverted, eligible, "
            "and missing-operating-arrival-delay records."
        )
    if (
        metrics["delayed_flights"] + metrics["non_delayed_eligible_flights"]
        != metrics["eligible_delay_records"]
    ):
        raise ValueError("Eligible arrival-delay classes do not reconcile.")


def _rate(numerator: str, denominator: str, name: str) -> F.Column:
    return F.when(F.col(denominator) > 0, F.col(numerator) / F.col(denominator)).alias(
        name
    )


def build_airline_analytics(frame: DataFrame) -> DataFrame:
    """Aggregate flight, delay, cancellation, diversion, and median by airline."""
    result = frame.groupBy("Reporting_Airline").agg(
        F.count(F.lit(1)).alias("total_flights"),
        _count(F.col("eligible_arrival"), "eligible_delay_records"),
        _count(F.col("delayed_arrival"), "delayed_flights"),
        _count(F.col("Cancelled") == 1, "cancelled_flights"),
        _count(F.col("Diverted") == 1, "diverted_flights"),
        F.avg(F.when(F.col("eligible_arrival"), F.col("ArrDelay"))).alias(
            "average_arrival_delay_minutes"
        ),
        F.percentile_approx(
            F.when(F.col("eligible_arrival"), F.col("ArrDelay")),
            0.5,
            PERCENTILE_ACCURACY,
        ).alias("median_arrival_delay_minutes"),
    )
    return result.withColumn(
        "delay_rate", _rate("delayed_flights", "eligible_delay_records", "delay_rate")
    ).withColumn(
        "cancellation_rate",
        _rate("cancelled_flights", "total_flights", "cancellation_rate"),
    )


def build_origin_airport_analytics(frame: DataFrame) -> DataFrame:
    """Aggregate departure outcomes by origin airport."""
    result = frame.groupBy("Origin").agg(
        F.count(F.lit(1)).alias("total_departures"),
        _count(F.col("eligible_departure"), "eligible_departure_records"),
        _count(F.col("delayed_departure"), "delayed_departures"),
        _count(F.col("Cancelled") == 1, "cancelled_departures"),
        _count(F.col("Diverted") == 1, "diverted_departures"),
        F.avg(F.when(F.col("eligible_departure"), F.col("DepDelay"))).alias(
            "average_departure_delay_minutes"
        ),
    )
    return result.withColumn(
        "departure_delay_rate",
        _rate("delayed_departures", "eligible_departure_records", "departure_delay_rate"),
    )


def build_destination_airport_analytics(frame: DataFrame) -> DataFrame:
    """Aggregate arrival outcomes by scheduled destination airport."""
    result = frame.groupBy("Dest").agg(
        F.count(F.lit(1)).alias("total_arrivals"),
        _count(F.col("eligible_arrival"), "eligible_arrivals"),
        _count(F.col("delayed_arrival"), "delayed_arrivals"),
        F.avg(F.when(F.col("eligible_arrival"), F.col("ArrDelay"))).alias(
            "average_arrival_delay_minutes"
        ),
        F.percentile_approx(
            F.when(F.col("eligible_arrival"), F.col("ArrDelay")),
            0.5,
            PERCENTILE_ACCURACY,
        ).alias("median_arrival_delay_minutes"),
    )
    return result.withColumn(
        "arrival_delay_rate",
        _rate("delayed_arrivals", "eligible_arrivals", "arrival_delay_rate"),
    )


def build_route_analytics(frame: DataFrame) -> DataFrame:
    """Aggregate arrival delay and cancellation outcomes by origin-destination."""
    result = frame.groupBy("route").agg(
        F.count(F.lit(1)).alias("total_flights"),
        _count(F.col("eligible_arrival"), "eligible_flights"),
        _count(F.col("delayed_arrival"), "delayed_flights"),
        _count(F.col("Cancelled") == 1, "cancelled_flights"),
        F.avg(F.when(F.col("eligible_arrival"), F.col("ArrDelay"))).alias(
            "average_arrival_delay_minutes"
        ),
        F.percentile_approx(
            F.when(F.col("eligible_arrival"), F.col("ArrDelay")),
            0.5,
            PERCENTILE_ACCURACY,
        ).alias("median_arrival_delay_minutes"),
    )
    return result.withColumn(
        "delay_rate", _rate("delayed_flights", "eligible_flights", "delay_rate")
    ).withColumn(
        "cancellation_rate",
        _rate("cancelled_flights", "total_flights", "cancellation_rate"),
    )


def _build_hourly_event(
    frame: DataFrame,
    time_basis: str,
    event_type: str,
    hour_column: str,
    eligible_column: str,
    delayed_column: str,
    delay_column: str,
) -> DataFrame:
    events = frame.filter(F.col(hour_column).isNotNull())
    grouped = events.groupBy(hour_column).agg(
        F.count(F.lit(1)).alias("flights_in_hour"),
        _count(F.col(eligible_column), "eligible_delay_records"),
        _count(F.col(delayed_column), "delayed_flights"),
        F.avg(F.when(F.col(eligible_column), F.col(delay_column))).alias(
            "average_delay_minutes"
        ),
        F.percentile_approx(
            F.when(F.col(eligible_column), F.col(delay_column)),
            0.5,
            PERCENTILE_ACCURACY,
        ).alias("median_delay_minutes"),
    )
    return (
        grouped.withColumn(
            "delay_rate",
            _rate("delayed_flights", "eligible_delay_records", "delay_rate"),
        )
        .withColumn("event_type", F.lit(event_type))
        .withColumn("time_basis", F.lit(time_basis))
        .withColumnRenamed(hour_column, "hour")
        .select(
            "event_type",
            "time_basis",
            "hour",
            "flights_in_hour",
            "eligible_delay_records",
            "delayed_flights",
            "delay_rate",
            "average_delay_minutes",
            "median_delay_minutes",
        )
    )


def build_hourly_analytics(frame: DataFrame) -> DataFrame:
    """Build separate scheduled/actual departure and arrival hourly patterns."""
    events = (
        ("scheduled_departure", "departure", "scheduled_departure_hour"),
        ("actual_departure", "departure", "actual_departure_hour"),
        ("scheduled_arrival", "arrival", "scheduled_arrival_hour"),
        ("actual_arrival", "arrival", "actual_arrival_hour"),
    )
    parts = []
    for basis, event_type, hour_column in events:
        if event_type == "departure":
            eligible_column, delayed_column, delay_column = (
                "eligible_departure",
                "delayed_departure",
                "DepDelay",
            )
        else:
            eligible_column, delayed_column, delay_column = (
                "eligible_arrival",
                "delayed_arrival",
                "ArrDelay",
            )
        parts.append(
            _build_hourly_event(
                frame,
                basis,
                event_type,
                hour_column,
                eligible_column,
                delayed_column,
                delay_column,
            )
        )
    return parts[0].unionByName(parts[1]).unionByName(parts[2]).unionByName(parts[3])


def build_day_of_week_analytics(frame: DataFrame) -> DataFrame:
    """Aggregate both departure and arrival measures by Monday-based weekday."""
    result = frame.filter(F.col("valid_day_of_week").isNotNull()).groupBy(
        "valid_day_of_week"
    ).agg(
        F.count(F.lit(1)).alias("total_flights"),
        _count(F.col("Cancelled") == 1, "cancelled_flights"),
        _count(F.col("Diverted") == 1, "diverted_flights"),
        _count(F.col("eligible_departure"), "eligible_departure_records"),
        _count(F.col("delayed_departure"), "delayed_departures"),
        _count(F.col("eligible_arrival"), "eligible_arrival_records"),
        _count(F.col("delayed_arrival"), "delayed_arrivals"),
        F.avg(F.when(F.col("eligible_departure"), F.col("DepDelay"))).alias(
            "average_departure_delay_minutes"
        ),
        F.avg(F.when(F.col("eligible_arrival"), F.col("ArrDelay"))).alias(
            "average_arrival_delay_minutes"
        ),
        F.percentile_approx(
            F.when(F.col("eligible_arrival"), F.col("ArrDelay")),
            0.5,
            PERCENTILE_ACCURACY,
        ).alias("median_arrival_delay_minutes"),
    )
    return (
        result.withColumnRenamed("valid_day_of_week", "day_of_week")
        .withColumn(
            "departure_delay_rate",
            _rate(
                "delayed_departures",
                "eligible_departure_records",
                "departure_delay_rate",
            ),
        )
        .withColumn(
            "arrival_delay_rate",
            _rate(
                "delayed_arrivals",
                "eligible_arrival_records",
                "arrival_delay_rate",
            ),
        )
    )


def build_delay_distribution(frame: DataFrame) -> DataFrame:
    """Create delay bands and approximate p50/p90/p95/p99 for each event."""
    arrivals = frame.filter(F.col("eligible_arrival")).select(
        F.lit("arrival").alias("delay_type"),
        F.col("ArrDelay").alias("delay_minutes"),
    )
    departures = frame.filter(F.col("eligible_departure")).select(
        F.lit("departure").alias("delay_type"),
        F.col("DepDelay").alias("delay_minutes"),
    )
    observed = arrivals.unionByName(departures)
    category = (
        F.when(F.col("delay_minutes") < 0, F.lit("early"))
        .when(F.col("delay_minutes") <= 15, F.lit("on_time"))
        .when(F.col("delay_minutes") <= 60, F.lit("delayed"))
        .when(F.col("delay_minutes") <= 180, F.lit("severe"))
        .otherwise(F.lit("extreme"))
    )
    categorized = observed.withColumn("category", category)
    window = Window.partitionBy("delay_type")
    category_rows = (
        categorized.groupBy("delay_type", "category")
        .agg(F.count(F.lit(1)).alias("flight_count"))
        .withColumn(
            "total_observed",
            F.sum("flight_count").over(window),
        )
        .select(
            "delay_type",
            F.lit("category").alias("statistic"),
            "category",
            F.col("flight_count").cast("long"),
            (F.col("flight_count") / F.col("total_observed")).alias("proportion"),
            F.lit(None).cast("double").alias("percentile"),
            F.lit(None).cast("double").alias("delay_minutes"),
            F.when(F.col("category") == "early", F.lit("delay < 0 minutes"))
            .when(F.col("category") == "on_time", F.lit("0 <= delay <= 15 minutes"))
            .when(F.col("category") == "delayed", F.lit("15 < delay <= 60 minutes"))
            .when(F.col("category") == "severe", F.lit("60 < delay <= 180 minutes"))
            .otherwise(F.lit("delay > 180 minutes"))
            .alias("definition"),
        )
    )

    percentile_columns = [
        F.percentile_approx(
            "delay_minutes", percentile, PERCENTILE_ACCURACY
        ).alias(f"p{int(percentile * 100)}")
        for percentile in DELAY_PERCENTILES
    ]
    percentile_summary = observed.groupBy("delay_type").agg(*percentile_columns)
    percentile_rows = None
    for percentile in DELAY_PERCENTILES:
        name = f"p{int(percentile * 100)}"
        current = percentile_summary.select(
            "delay_type",
            F.lit("percentile").alias("statistic"),
            F.lit(name).alias("category"),
            F.lit(None).cast("long").alias("flight_count"),
            F.lit(None).cast("double").alias("proportion"),
            F.lit(percentile).alias("percentile"),
            F.col(name).cast("double").alias("delay_minutes"),
            F.lit(
                f"Approximate {int(percentile * 100)}th percentile of observed eligible delay minutes; "
                f"Spark percentile_approx accuracy={PERCENTILE_ACCURACY}."
            ).alias("definition"),
        )
        percentile_rows = (
            current
            if percentile_rows is None
            else percentile_rows.unionByName(current)
        )
    assert percentile_rows is not None
    return category_rows.unionByName(percentile_rows)


def _write_grouped_parquet(frame: DataFrame, path: Path) -> pa.Table:
    """Write a bounded aggregate result as one atomic Zstandard Parquet file.

    Spark's Windows local filesystem writer requires winutils.exe to apply file
    permissions. Collecting only the grouped result (at most one row per
    airline/airport/route/hour/day or delay statistic) and writing it with
    PyArrow avoids adding a Hadoop distribution solely for local file writes.
    """
    table = frame.toArrow()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        pq.write_table(
            table,
            temporary,
            compression="zstd",
            use_dictionary=True,
            write_statistics=True,
        )
        temporary.replace(path)
    except (OSError, pa.ArrowException):
        temporary.unlink(missing_ok=True)
        raise
    return table


def _sum_arrow_column(table: pa.Table, name: str) -> int:
    if name not in table.column_names:
        return 0
    values = table[name].to_pylist()
    return sum(int(value or 0) for value in values)


def run_analytics(
    spark: SparkSession,
    input_path: Path = DEFAULT_INPUT_PATH,
    output_directory: Path = DEFAULT_OUTPUT_DIRECTORY,
    min_route_flights: int = DEFAULT_MIN_ROUTE_FLIGHTS,
) -> dict[str, Any]:
    """Run all historical analytics, writing outputs and enforcing reconciliation."""
    if min_route_flights < 1:
        raise ValueError("Minimum route sample size must be at least one flight.")

    started = time.perf_counter()
    raw = read_analytics_input(spark, input_path)
    frame = prepare_analytics_frame(raw).persist(StorageLevel.MEMORY_ONLY)
    try:
        source_metrics = summarize_source(frame)
        assert_source_reconciliation(source_metrics)

        summaries: dict[str, Any] = {}
        output_specs = (
            ("airline", build_airline_analytics(frame), ("total_flights",)),
            (
                "origin",
                build_origin_airport_analytics(frame),
                ("total_departures",),
            ),
            (
                "destination",
                build_destination_airport_analytics(frame),
                ("total_arrivals",),
            ),
            ("hourly", build_hourly_analytics(frame), ()),
            ("day_of_week", build_day_of_week_analytics(frame), ("total_flights",)),
            ("delay_distribution", build_delay_distribution(frame), ()),
        )

        for name, result, totals in output_specs:
            table = _write_grouped_parquet(
                result, output_directory / OUTPUT_NAMES[name]
            )
            row_count = table.num_rows
            summaries[name] = {
                "output_rows": row_count,
                **{
                    f"sum_{column}": _sum_arrow_column(table, column)
                    for column in totals
                },
            }

        route_groups = build_route_analytics(frame).persist(StorageLevel.MEMORY_ONLY)
        try:
            route_summary = route_groups.agg(
                F.count(F.lit(1)).alias("all_routes"),
                F.coalesce(F.sum("total_flights"), F.lit(0)).alias(
                    "all_route_flights"
                ),
                F.sum(
                    F.when(F.col("total_flights") >= min_route_flights, 1).otherwise(0)
                ).alias("retained_routes"),
                F.coalesce(
                    F.sum(
                        F.when(
                            F.col("total_flights") >= min_route_flights,
                            F.col("total_flights"),
                        ).otherwise(0)
                    ),
                    F.lit(0),
                ).alias("retained_route_flights"),
            ).first()
            all_routes = int(route_summary["all_routes"])
            all_route_flights = int(route_summary["all_route_flights"])
            if all_route_flights != source_metrics["total_flights"]:
                raise ValueError(
                    "Route aggregation does not reconcile to source rows: "
                    f"{all_route_flights} != {source_metrics['total_flights']}."
                )
            retained_routes = route_groups.filter(
                F.col("total_flights") >= min_route_flights
            )
            route_table = _write_grouped_parquet(
                retained_routes, output_directory / OUTPUT_NAMES["route"]
            )
            summaries["route"] = {
                "output_rows": route_table.num_rows,
                "all_routes": all_routes,
                "all_route_flights": all_route_flights,
                "retained_routes": int(route_summary["retained_routes"]),
                "retained_route_flights": int(
                    route_summary["retained_route_flights"]
                ),
                "minimum_flights": min_route_flights,
            }
        finally:
            route_groups.unpersist()

        for name, total_column, expected_total in (
            ("airline", "sum_total_flights", source_metrics["total_flights"]),
            (
                "origin",
                "sum_total_departures",
                source_metrics["total_flights"],
            ),
            (
                "destination",
                "sum_total_arrivals",
                source_metrics["total_flights"],
            ),
            (
                "day_of_week",
                "sum_total_flights",
                source_metrics["total_flights"],
            ),
        ):
            actual_total = summaries[name][total_column]
            if actual_total != expected_total:
                raise ValueError(
                    f"{name} analytics lost source rows: "
                    f"{actual_total} != {expected_total}."
                )

        return {
            "source_metrics": source_metrics,
            "outputs": summaries,
            "runtime_seconds": round(time.perf_counter() - started, 2),
        }
    finally:
        frame.unpersist()


def main(argv: list[str] | None = None) -> int:
    """Run the standalone local aviation analytics pipeline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    parser.add_argument(
        "--min-route-flights",
        type=int,
        default=DEFAULT_MIN_ROUTE_FLIGHTS,
        help="Keep routes with at least this many source records (default: 30).",
    )
    args = parser.parse_args(argv)

    spark: SparkSession | None = None
    try:
        spark = create_spark_session()
        result = run_analytics(
            spark,
            args.input.expanduser(),
            args.output_dir.expanduser(),
            args.min_route_flights,
        )
        print("Source reconciliation:")
        for name, value in result["source_metrics"].items():
            print(f"  {name}: {value:,}")
        print("Analytics output row counts:")
        for name, details in result["outputs"].items():
            print(f"  {OUTPUT_NAMES[name]}: {details['output_rows']:,}")
            if name == "route":
                print(
                    "    routes before/after sample threshold: "
                    f"{details['all_routes']:,}/{details['retained_routes']:,}; "
                    f"retained records: {details['retained_route_flights']:,}/"
                    f"{details['all_route_flights']:,}"
                )
        print("Monthly analytics omitted: the source dataset covers January 2024.")
        print(f"Runtime: {result['runtime_seconds']:.2f} seconds")
        print(f"Outputs: {args.output_dir.resolve()}")
        return 0
    except (OSError, ValueError, RuntimeError, PySparkException) as exc:
        print(f"Aviation analytics failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if spark is not None:
            spark.stop()


if __name__ == "__main__":
    raise SystemExit(main())
