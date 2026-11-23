param([ValidateSet('start','topics','health','stop')][string]$Action='start')
$ErrorActionPreference='Stop'
Set-Location (Join-Path $PSScriptRoot '..')
if (!$env:KAFKA_HOME) { throw 'Set KAFKA_HOME to the extracted Kafka 4.0.1 directory.' }
$lib=Join-Path $env:KAFKA_HOME 'libs/*'
$java=Join-Path $env:JAVA_HOME 'bin/java.exe'
$dir=(New-Item -ItemType Directory -Force data/streaming/broker).FullName
$config=Join-Path $dir 'server.properties'
$logDir=(Join-Path $dir 'logs').Replace('\','/')
if ($Action -eq 'start') {
@"
process.roles=broker,controller
node.id=1
controller.quorum.voters=1@127.0.0.1:9093
listeners=PLAINTEXT://127.0.0.1:9092,CONTROLLER://127.0.0.1:9093
advertised.listeners=PLAINTEXT://127.0.0.1:9092
controller.listener.names=CONTROLLER
listener.security.protocol.map=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT
inter.broker.listener.name=PLAINTEXT
log.dirs=$logDir
offsets.topic.replication.factor=1
transaction.state.log.replication.factor=1
transaction.state.log.min.isr=1
log.retention.hours=24
log.segment.bytes=16777216
auto.create.topics.enable=false
"@ | Set-Content $config -Encoding ASCII
    if (!(Test-Path -LiteralPath (Join-Path $logDir 'meta.properties'))) {
        $cluster=& $java -cp $lib kafka.tools.StorageTool random-uuid | Select-Object -Last 1
        if ($LASTEXITCODE) { throw 'Kafka cluster ID generation failed' }
        & $java -cp $lib kafka.tools.StorageTool format -t $cluster -c $config
        if ($LASTEXITCODE) { throw 'Kafka storage initialization failed' }
    }
    & $java -Xms128m -Xmx384m -cp $lib kafka.Kafka $config
} elseif ($Action -eq 'topics') {
    foreach ($topic in 'flight-states','flight-predictions','flight-anomalies','flight-alerts') {
        & $java -cp $lib org.apache.kafka.tools.TopicCommand --bootstrap-server 127.0.0.1:9092 --create --if-not-exists --topic $topic --partitions 1 --replication-factor 1
        if ($LASTEXITCODE) { throw "Failed to create $topic" }
    }
} elseif ($Action -eq 'health') {
    & $java -cp $lib org.apache.kafka.tools.TopicCommand --bootstrap-server 127.0.0.1:9092 --describe
} else {
    Write-Output 'Press Ctrl+C in the terminal running the broker to shut it down.'
}
exit $LASTEXITCODE
