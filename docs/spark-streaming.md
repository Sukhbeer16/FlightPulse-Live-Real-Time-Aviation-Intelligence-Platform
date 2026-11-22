# Spark Structured Streaming

The tested runtime used PySpark 4.0.5, Scala 2.13, a full Java 21 JDK and Hadoop 3.4.1 native Windows libraries. The Spark Kafka connector version follows the installed PySpark version. JAVA_HOME must point to a full JDK containing jdk.incubator.vector. HADOOP_HOME/bin must contain compatible winutils.exe and hadoop.dll. The audit used the SHA-256-verified community native build aa8098a433e6d63b865074468aa2da1aa9329ef33c9e9af799037f382ce50b82. [Spark Kafka connector](https://spark.apache.org/docs/4.0.1/streaming/structured-streaming-kafka-integration.html) · [Windows native build](https://github.com/zehelh/winutils/releases/tag/hadoop-3.4.1)

Run scripts/spark.ps1 continuously or scripts/spark.ps1 -Once to drain available records and exit. The job uses two local threads, two shuffle partitions, a 512 MB driver heap and at most 500 Kafka offsets per microbatch. The checkpoint lives in data/streaming/checkpoint. Spark resumes committed offsets on restart. Preserve the SQLite database with the checkpoint.

Validation checks schema version, source, key, clock, coordinates and normalized telemetry. Duplicate source/ICAO24/last-contact keys contribute once. Malformed inputs are stored in rejected with original bytes and partition/offset so an operator can inspect them. Batch metrics preserve consumed offset ranges. SQLite transactions bind observations, rejects and metrics to window updates; a failed write causes the microbatch to fail.

Five-minute UTC event-time windows aggregate each source and aircraft separately. The API returns observation count, mean reported speed, peak absolute vertical rate and a review flag above 30 m/s. Missing rates stay unknown. This fixed threshold is a movement-screening rule. It has no calibrated severity or emergency interpretation. The historical Isolation Forest needs carrier, route and schedule features that state vectors do not supply.

~~~powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/live/stream-summary
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/live/stream-summary?source=SIMULATION'
~~~

System Status reads the OpenSky summary. The API limits results to the latest 100 aircraft/window combinations. Local SQLite persists observations until the operator archives them.
