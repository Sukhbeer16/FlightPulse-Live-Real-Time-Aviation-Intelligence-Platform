# Frontend and backend integration

Vite serves the React dashboard on port 5173. VITE_API_BASE_URL defaults to http://127.0.0.1:8000. The backend permits both standard localhost Vite origins. Restart Vite after changing its environment.

## Tracker

The tracker opens on a historical roster. BTS schedule records have no observed aircraft positions. Select the OpenSky control to request the configured API's regional state endpoint. The default map region request covers 40–42° N, 75–72° W. A successful response shows its provider time and updates every two minutes. The roster and markers use the same ICAO24 across updates. Aircraft without coordinates are excluded from both map views. Select a marker for observed details, or a historical roster entry for its BTS source record. The source-specific drawer avoids assigning a prediction or telemetry measurement to a historical row.

The tracker previously hard-coded four CARTO tile hosts and disabled attribution. The local dashboard uses the standard HTTPS OpenStreetMap raster endpoint with visible attribution and the existing MapLibre overlay styling. Browsers make normal viewport requests and retain ordinary HTTP caching. Public tiles are best-effort. [Tile provider usage policy](https://operations.osmfoundation.org/policies/tiles/)

## Historical and model contracts

GET /api/v1/historical/processed-flights accepts flight number, carrier, BTS origin/destination, exact date, date interval, cancellation, diversion, delay status, delay bounds, ordering and page parameters. Each record includes original source filename, row number, local scheduled times, distance, elapsed time and observed outcomes. Sorting includes deterministic source/row tie-breakers. A ten-row January 10 search for JFK returned 306 matches. Search queries have no OpenSky or database dependency.

The previous implementation converted and validated hundreds of thousands of Python row objects for a fifty-row page. Sorting also populated a temporary SQLite table. This work competed with a ten-second browser timeout, and initial tracker failures were swallowed. DuckDB now projects columns and applies filters, counts, orders and limits in the query engine. The tracker surfaces the error and provides a retry.

Delay Prediction sends the selected model name and scheduled features to the inference endpoint. Anomaly Detection and Disruption Intelligence share a historical assessment control. Risk inputs use actual scheduled time, elapsed time and distance from the selected BTS record. The observed arrival delay enters only the separate observed component of the risk score. Factors and component availability come from the server. A user can explicitly record a demonstration alert and inspect its explanation in Alerts.

Historical Analytics uses the January overview and carrier report. The existing multi-period delay trend and weekly activity series remain visibly labelled SAMPLE DATA. Settings links to measured service status. The Assistant remains a planned screen. No LLM or RAG dependency was introduced.
