"""Reusable resource-conscious Spark session configuration."""

from __future__ import annotations

import os
import sys

from pyspark.sql import SparkSession


def create_spark_session(
    app_name: str = "FlightPulse",
    master: str | None = None,
    driver_memory: str | None = None,
    log_level: str | None = None,
) -> SparkSession:
    """Create a local Spark session with conservative, environment overrides."""
    selected_master = master or os.getenv("FLIGHTPULSE_SPARK_MASTER", "local[2]")
    if not selected_master.startswith("local"):
        raise ValueError("FlightPulse Spark is configured for standalone local mode only.")

    selected_memory = driver_memory or os.getenv(
        "FLIGHTPULSE_SPARK_DRIVER_MEMORY", "2g"
    )
    selected_log_level = log_level or os.getenv("FLIGHTPULSE_SPARK_LOG_LEVEL", "WARN")
    python_executable = sys.executable
    os.environ["PYSPARK_PYTHON"] = python_executable
    os.environ["PYSPARK_DRIVER_PYTHON"] = python_executable

    spark = (
        SparkSession.builder.appName(app_name)
        .master(selected_master)
        .config("spark.driver.memory", selected_memory)
        .config("spark.default.parallelism", "2")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.sql.adaptive.enabled", "true")
        .config("spark.pyspark.python", python_executable)
        .config("spark.pyspark.driver.python", python_executable)
        .config("spark.ui.enabled", "false")
        .config("spark.driver.host", "127.0.0.1")
        .config("spark.driver.bindAddress", "127.0.0.1")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel(selected_log_level)
    return spark
