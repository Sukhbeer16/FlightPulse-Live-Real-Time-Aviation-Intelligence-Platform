# Local Kafka

Use Apache Kafka 4.0.1 for Scala 2.13 and a full Java 21 JDK. Extract the binary archive after verifying its SHA-512 against the Apache release. The PowerShell launcher uses the Java classpath wildcard directly to avoid the Windows batch command-length limit. [Apache distribution](https://archive.apache.org/dist/kafka/4.0.1/)

Set KAFKA_HOME and JAVA_HOME in each terminal as shown in project-architecture.md. Run scripts/kafka.ps1 start in one terminal and scripts/kafka.ps1 topics then scripts/kafka.ps1 health in another. Ctrl+C stops the broker. Restart with the same configuration. The launcher preserves storage identity under data/streaming/broker, binds only to loopback and uses a 384 MB maximum heap.

All three topics have one partition and one replica. flight-states carries UTF-8 JSON keyed by ICAO24. flight-anomalies and flight-alerts are reserved. Current processing writes validated results to SQLite. Each event contains version 1, source, integer source_time in UTC epoch seconds, and the complete normalized state. Live and SIMULATION observations remain distinct in storage and API responses. The producer waits for acknowledgements with a bounded delivery timeout and fails visibly on undelivered events.

~~~powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-streaming.txt
.\.venv\Scripts\python.exe -m backend.app.streaming.producer --simulation
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/live/stream-summary?source=SIMULATION'
~~~

One invocation emits one explicitly labelled test event. Keep the broker data and Spark checkpoint together across restarts. Retention is 24 hours. A consumer outage exceeding available offsets raises a data-loss error.
