# Local Kafka

Use Apache Kafka 4.0.1 for Scala 2.13 and a full Java 21 JDK. Extract the binary archive after verifying its SHA-512 against the Apache release. The PowerShell launcher uses the Java classpath wildcard directly to avoid the Windows batch command-length limit. [Apache distribution](https://archive.apache.org/dist/kafka/4.0.1/)

Set `KAFKA_HOME` and `JAVA_HOME` in each terminal as shown below. Run `scripts/kafka.ps1 start` in one terminal and `scripts/kafka.ps1 topics` in another. Ctrl+C stops the broker. Restart with the same configuration. The launcher preserves storage identity under `data/streaming/broker`, binds only to loopback and uses a 384 MB maximum heap.

```powershell
$env:KAFKA_HOME="$env:TEMP/kafka_2.13-4.0.1"
$env:JAVA_HOME="$env:TEMP/jdk-21.0.13.1+2"
.\scripts\kafka.ps1 start
```

In a separate terminal, repeat the environment assignments, then run:

```powershell
.\scripts\kafka.ps1 topics
.\.venv\Scripts\python.exe -m backend.app.streaming.producer --provider adsb-lol --interval 30
```

In a third terminal run `.\.venv\Scripts\python.exe -m backend.app.streaming.consumer`.
The backend and frontend commands are in [operations-upgrade.md](operations-upgrade.md).

The concrete reliability problems were that the producer defaulted to
credentialed OpenSky even on an unconfigured laptop, and an interrupted Kafka
delivery stopped the continuous producer. The default is now the public
`adsb-lol` adapter, while `--provider opensky` still requires OAuth. Continuous
delivery failures retry with bounded backoff; `--once` fails visibly. A stopped
broker or consumer still leaves the Kafka view with no fresh positions. The
local restart test retained all topics and offsets;
the public provider delivered 149 observations before restart and 148 after
restart, both persisted and returned fresh by the API. A later running
consumer delivered 156 fresh observations to the API and browser. Temporary
`Coordinator load in progress` notices during broker startup retried and
did not lose those acknowledged deliveries. Provider errors or a stopped
consumer still require process supervision; this development setup has no
Windows service manager.
The new credential-free default was also checked with `producer --once`:
159 events were acknowledged, consumed and returned fresh by the API.

All three topics have one partition and one replica. flight-states carries UTF-8 JSON keyed by ICAO24. flight-anomalies and flight-alerts are reserved. Current processing writes validated results to SQLite. Each event contains version 1, source, integer source_time in UTC epoch seconds, and the complete normalized state. Live and SIMULATION observations remain distinct in storage and API responses. The producer waits for acknowledgements with a bounded delivery timeout and fails visibly on undelivered events.

~~~powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-streaming.txt
.\.venv\Scripts\python.exe -m backend.app.streaming.producer --simulation
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/live/stream-summary?source=SIMULATION'
~~~

One invocation emits one explicitly labelled test event. Keep the broker data and Spark checkpoint together across restarts. Retention is 24 hours. A consumer outage exceeding available offsets raises a data-loss error.

## Application consumer and public provider

The application now supports `--provider adsb-lol` as well as OpenSky, a lightweight Kafka consumer, fresh-position API and persistent review alerts. See [operations-upgrade.md](operations-upgrade.md) for the complete commands and delivery semantics. `flight-alerts` and `flight-anomalies` remain reserved: the consumer writes its alerts to the durable application inbox, not those topics.
