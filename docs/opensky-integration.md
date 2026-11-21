# OpenSky integration

Create an API client in your OpenSky account. Put OPENSKY_CLIENT_ID and OPENSKY_CLIENT_SECRET in the repository-root .env, or set those environment variables for the backend and producer processes. Restart both after changing credentials. Only the backend requests access tokens using client credentials. The client checks expiry before reuse and requests a new token once after a state request returns 401. No token or client secret belongs in VITE variables. [Official REST API](https://openskynetwork.github.io/opensky-api/rest.html)

The map and producer are separate callers. Select a small region and a polling interval appropriate for the account quota. Requests have a ten-second upstream timeout. Each process caches up to eight regional snapshots, limits snapshot size, validates provider timestamps and coordinates, and keeps the newest state for each ICAO24. Within a process, requests share the rate-limit cooldown. Production scheduling across multiple workers would need a shared quota budget.

~~~powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/live/provider-status'
$r = Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/live/states?lamin=40&lomin=-75&lamax=42&lomax=-72'
$r | Select-Object source,source_time,cached,count
$r.states | Select-Object -First 3 icao24,callsign,latitude,longitude,last_contact
~~~

An empty successful response means the provider returned no state vectors for that box. A failed request returns an error. The status endpoint records the last successful provider snapshot for this API process, and the cached flag distinguishes cache hits. The map requires coordinates and can consequently show fewer aircraft than the API. The ingestion service publishes only authenticated observations. OpenSky telemetry supplies neither scheduled arrival delay nor the historical model feature set. No authenticated provider timestamp was available during this audit.
