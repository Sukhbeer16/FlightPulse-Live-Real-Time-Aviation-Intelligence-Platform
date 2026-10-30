"""Validate Phase 2 BTS Parquet data with standalone local PySpark."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from pyspark.errors import PySparkException
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, NumericType, StructField, StructType

from pipelines.spark.session import create_spark_session


EXPECTED_METRICS = {
    "total_flights": 547_271,
    "cancelled_flights": 20_389,
    "diverted_flights": 1_512,
    "eligible_delay_records": 525_370,
    "delayed_flights": 122_508,
    "non_delayed_eligible_flights": 402_862,
}
REQUIRED_NUMERIC_COLUMNS = {"Cancelled", "Diverted", "ArrDelay"}
METRIC_SCHEMA = StructType(
    [
        StructField("Cancelled", DoubleType(), True),
        StructField("Diverted", DoubleType(), True),
        StructField("ArrDelay", DoubleType(), True),
    ]
)
DEFAULT_DATASET_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "processed"
    / "bts_ontime_2024_01.parquet"
)


def validate_schema(schema: StructType) -> None:
    """Require the numeric fields used by the validation aggregations."""
    fields = {field.name: field.dataType for field in schema.fields}
    missing = REQUIRED_NUMERIC_COLUMNS.difference(fields)
    if missing:
        raise ValueError(f"Parquet schema is missing required columns: {sorted(missing)}")
    invalid = sorted(
        name
        for name in REQUIRED_NUMERIC_COLUMNS
        if not isinstance(fields[name], NumericType)
    )
    if invalid:
        raise ValueError(f"Expected numeric BTS columns, got incompatible types: {invalid}")


def calculate_metrics(frame: DataFrame) -> dict[str, int]:
    """Calculate null-safe counts from BTS status and arrival-delay columns."""
    validate_schema(frame.schema)
    cancelled = F.col("Cancelled") == F.lit(1)
    diverted = F.col("Diverted") == F.lit(1)
    eligible = (
        (F.col("Cancelled") == F.lit(0))
        & (F.col("Diverted") == F.lit(0))
        & F.col("ArrDelay").isNotNull()
    )
    delayed = eligible & (F.col("ArrDelay") > F.lit(15))
    non_delayed = eligible & (F.col("ArrDelay") <= F.lit(15))
    result: Any = frame.agg(
        F.count(F.lit(1)).alias("total_flights"),
        F.coalesce(F.sum(F.when(cancelled, 1).otherwise(0)), F.lit(0)).alias(
            "cancelled_flights"
        ),
        F.coalesce(F.sum(F.when(diverted, 1).otherwise(0)), F.lit(0)).alias(
            "diverted_flights"
        ),
        F.coalesce(F.sum(F.when(eligible, 1).otherwise(0)), F.lit(0)).alias(
            "eligible_delay_records"
        ),
        F.coalesce(F.sum(F.when(delayed, 1).otherwise(0)), F.lit(0)).alias(
            "delayed_flights"
        ),
        F.coalesce(F.sum(F.when(non_delayed, 1).otherwise(0)), F.lit(0)).alias(
            "non_delayed_eligible_flights"
        ),
    ).first()
    return {name: int(result[name]) for name in EXPECTED_METRICS}


def validate_bts_parquet(
    spark: SparkSession, dataset_path: Path
) -> dict[str, int]:
    """Read the Phase 2 Parquet, print schema/sample, and return measured metrics."""
    if not dataset_path.is_file():
        raise FileNotFoundError(f"BTS Parquet dataset not found: {dataset_path}")

    # Spark 4.0 cannot infer Arrow's TIMESTAMP(NANOS) FlightDate column.
    # Project only the verified metric columns without rewriting the source.
    frame = spark.read.schema(METRIC_SCHEMA).parquet(dataset_path.resolve().as_uri())
    validate_schema(frame.schema)
    print("Spark schema for the required BTS metric columns:")
    frame.printSchema()
    print("Sample rows:")
    frame.show(5, truncate=40)
    return calculate_metrics(frame)


def main(argv: list[str] | None = None) -> int:
    """Run the standalone local Spark validation and compare Phase 2 counts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_DATASET_PATH)
    args = parser.parse_args(argv)
    spark: SparkSession | None = None
    try:
        spark = create_spark_session()
        metrics = validate_bts_parquet(spark, args.input.expanduser())
        print("Measured metrics:")
        for name, value in metrics.items():
            expected = EXPECTED_METRICS[name]
            print(f"  {name}: {value:,} (expected {expected:,})")
            if value != expected:
                print(
                    f"Metric mismatch for {name}: actual {value}, expected {expected}.",
                    file=sys.stderr,
                )
                return 1
        print("All Spark metrics match the verified Phase 2 counts.")
        return 0
    except (OSError, ValueError, RuntimeError, PySparkException) as exc:
        print(f"Spark validation failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if spark is not None:
            spark.stop()


if __name__ == "__main__":
    raise SystemExit(main())
