"""Single-node Structured Streaming ingestion, with bounded microbatches."""

import argparse
from pyspark import __version__
from pyspark.sql import SparkSession
from backend.app.config.settings import get_settings
from backend.app.streaming.store import database, store_batch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process all currently available offsets and exit",
    )
    args = parser.parse_args()
    trigger = {"availableNow": True} if args.once else {"processingTime": "10 seconds"}
    settings = get_settings()
    spark = (
        SparkSession.builder.master("local[2]")
        .appName("FlightPulse")
        .config(
            "spark.jars.packages",
            f"org.apache.spark:spark-sql-kafka-0-10_2.13:{__version__}",
        )
        .config("spark.sql.shuffle.partitions", "2")
        .getOrCreate()
    )
    try:
        stream = (
            spark.readStream.format("kafka")
            .option("subscribe", "flight-states")
            .option("kafka.bootstrap.servers", settings.kafka_bootstrap_servers)
            .option("startingOffsets", "earliest")
            .option("maxOffsetsPerTrigger", 500)
            .load()
        )
        query = (
            stream.select("key", "value", "partition", "offset")
            .writeStream.foreachBatch(store_batch)
            .option(
                "checkpointLocation", str(database().parent.resolve() / "checkpoint")
            )
            .trigger(**trigger)
            .start()
        )
        query.awaitTermination()
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
