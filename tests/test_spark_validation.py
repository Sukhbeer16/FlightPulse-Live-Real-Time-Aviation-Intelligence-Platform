"""Lightweight tests for standalone local Spark and BTS metric semantics."""

from __future__ import annotations

import pytest
from pyspark.sql import SparkSession
from pyspark.sql.types import DoubleType, IntegerType, StructField, StructType

from pipelines.spark.bts_validation import (
    DEFAULT_DATASET_PATH,
    METRIC_SCHEMA,
    calculate_metrics,
    validate_schema,
)
from pipelines.spark.session import create_spark_session


@pytest.fixture(scope="session")
def spark() -> SparkSession:
    """Share one small local Spark session across these tests."""
    session = create_spark_session(app_name="FlightPulseTests")
    yield session
    session.stop()


def test_spark_session_uses_local_resource_defaults(spark: SparkSession) -> None:
    assert spark.sparkContext.master == "local[2]"
    assert spark.sparkContext.appName == "FlightPulseTests"
    assert spark.conf.get("spark.sql.shuffle.partitions") == "2"
    assert spark.conf.get("spark.driver.memory") == "2g"


def test_schema_requires_actual_numeric_bts_columns() -> None:
    schema = StructType(
        [
            StructField("Cancelled", DoubleType(), True),
            StructField("Diverted", DoubleType(), True),
            StructField("ArrDelay", DoubleType(), True),
        ]
    )

    validate_schema(schema)
    with pytest.raises(ValueError, match="missing required columns"):
        validate_schema(StructType([StructField("ArrDelay", DoubleType(), True)]))
    with pytest.raises(ValueError, match="incompatible types"):
        validate_schema(
            StructType(
                [
                    StructField("Cancelled", IntegerType(), True),
                    StructField("Diverted", IntegerType(), True),
                    StructField("ArrDelay", StructType(), True),
                ]
            )
        )


def test_parquet_readability_and_null_safe_metrics(spark: SparkSession) -> None:
    parquet = spark.read.schema(METRIC_SCHEMA).parquet(
        DEFAULT_DATASET_PATH.resolve().as_uri()
    )
    validate_schema(parquet.schema)
    sample = parquet.limit(1).collect()
    assert len(sample) == 1
    assert set(parquet.columns) == {"Cancelled", "Diverted", "ArrDelay"}

    schema = StructType(
        [
            StructField("Cancelled", DoubleType(), True),
            StructField("Diverted", DoubleType(), True),
            StructField("ArrDelay", DoubleType(), True),
        ]
    )
    rows = [
        (0.0, 0.0, 20.0),
        (0.0, 0.0, 15.0),
        (0.0, 0.0, -3.0),
        (0.0, 0.0, None),
        (1.0, 0.0, None),
        (0.0, 1.0, 55.0),
        (None, 0.0, 25.0),
    ]
    fixture = spark.createDataFrame(rows, schema)
    assert fixture.count() == 7
    metrics = calculate_metrics(fixture)
    assert metrics == {
        "total_flights": 7,
        "cancelled_flights": 1,
        "diverted_flights": 1,
        "eligible_delay_records": 3,
        "delayed_flights": 1,
        "non_delayed_eligible_flights": 2,
    }
