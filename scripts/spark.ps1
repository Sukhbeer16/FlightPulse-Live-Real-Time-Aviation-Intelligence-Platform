param([switch]$Once)
$ErrorActionPreference='Stop'
Set-Location (Join-Path $PSScriptRoot '..')
if (!(Test-Path "$env:HADOOP_HOME/bin/winutils.exe") -or !(Test-Path "$env:HADOOP_HOME/bin/hadoop.dll")) {
    throw 'Set HADOOP_HOME to the Hadoop 3.4.1 Windows native directory.'
}
if (!(Test-Path "$env:JAVA_HOME/bin/java.exe")) { throw 'Set JAVA_HOME to the full JDK.' }
$env:PATH="$env:HADOOP_HOME/bin;$env:JAVA_HOME/bin;$env:PATH"
$env:SPARK_LOCAL_IP='127.0.0.1'
$env:PYSPARK_PYTHON=(Resolve-Path .venv/Scripts/python.exe).Path
$env:PYSPARK_SUBMIT_ARGS='--driver-memory 512m pyspark-shell'
$ErrorActionPreference="Continue"
if ($Once) { & $env:PYSPARK_PYTHON -m backend.app.streaming.job --once }
else { & $env:PYSPARK_PYTHON -m backend.app.streaming.job }
exit $LASTEXITCODE
