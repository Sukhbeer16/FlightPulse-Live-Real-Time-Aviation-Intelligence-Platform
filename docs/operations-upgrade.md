# Flight explorer, forecasts, alerts and live Kafka

The existing app now has three separate map sources: **Live radar**, **Dataset flights**, and **Kafka stream**. Dataset rows are historical evidence, not present-day aircraft positions.

## Forecasts

The delay page returns one forecast. `POST /api/v1/predictions/delay` defaults to `model=best`. The backend ranks the four deployed Phase 4.2 artifacts using validation F2, then PR-AUC, recall and precision, following the saved experiment's selection rule. It selects the highest-ranked loadable artifact, reports any skipped artifacts, and fails explicitly if no valid report/model exists. Individual model endpoints remain available for research clients.

The current winner is balanced logistic regression. Selection uses held-out validation performance, not whichever model gives the largest prediction for a flight. The saved model remains experimental: its test recall was about 0.059 at threshold 0.5. This change does not retrain or calibrate it, establish production accuracy, or turn a score into a delay duration.

Choose a dataset record to fill the full schedule and distance inputs, or enter a custom schedule. Local sensitivity factors compare the selected model's output against training-median numeric inputs or unknown categorical values. They describe associations, not causes. Binary logistic contributions now use the correct coefficient row.

## Dataset identities and delay explanations

Historical search now exposes the source's carrier, weather, national-airspace, security and late-aircraft delay minutes. Missing cause fields stay missing. The UI displays positive recorded causes and their minutes, or states that no specific cause was reported.

Airline names are joined using `DOT_ID_Reporting_Airline` against `data/reference/Carrier_Decode.zip`. Airport names and coordinates use exact airport sequence IDs against `Master_Coordinate.zip`. These are existing local BTS reference archives; missing reference rows are not guessed. No historical record is attached to an unrelated live callsign.

The dataset map supports airport, carrier, flight-number, date and delay filters, with server-side pagination. Lines connect recorded origin and destination airports. Plane icons mark schematic route midpoints; they are not actual historical tracks or live positions. Overlapping routes share marker locations; every flight remains selectable in the list. Records without reference coordinates remain in the list.

## Persistent alerts and delivery

Alerts live in `data/operations/alerts.sqlite`, survive API restarts, and support open → acknowledged → resolved workflows. Historical alerts use deterministic source-file/row IDs; telemetry review alerts use provider/aircraft/five-minute-window IDs. Replays do not duplicate alerts or reopen a resolved record.

- `POST /api/v1/alerts/historical`: accepts only `source_file` and `source_row_number`, reloads the actual source record, and rejects missing/on-time records. Historical alerts are explicitly labelled historical.
- `GET /api/v1/alerts`: paginated filters for severity and status. The current inbox displays the latest 100 records.
- `PATCH /api/v1/alerts/{id}`: acknowledge or resolve; an acknowledgement cannot reopen a resolved alert.
- Existing `/alerts/evaluate` is retained as an explicitly labelled demonstration endpoint. The main user flows no longer use it.

Click **Enable desktop alerts** to request browser notification permission. New non-demonstration alerts can produce OS notifications while the app is open, with a 15-second polling interval. Browser storage remembers delivered IDs; the inbox remains authoritative. This is not a background push service when the browser is closed. The same control pauses desktop delivery.

For real email, set these backend `.env` values locally:

```dotenv
SMTP_HOST=your-smtp-host
SMTP_PORT=587
SMTP_USERNAME=your-smtp-user
SMTP_PASSWORD=your-smtp-password
SMTP_FROM=your-verified-sender
ALERT_EMAIL_TO=your-recipient
```

The worker requires STARTTLS and a valid server certificate. Recipient and credentials are server configuration, never browser inputs. Restart the API after configuration, then run:

```powershell
.\.venv\Scripts\python.exe -m backend.app.services.alert_delivery
```

New alerts are queued when SMTP host, sender and recipient are configured. The worker persists attempts, leases one delivery at a time, and retries failures with exponential backoff up to five attempts. The inbox distinguishes in-app, queued, failed and SMTP-accepted messages. SMTP acceptance does not prove inbox delivery. Delivery is at-least-once: a worker crash after SMTP acceptance but before the database update can result in a duplicate email; a stable Message-ID aids reconciliation. Previously created in-app-only alerts are not automatically emailed on later configuration.

## Live Kafka without credentials

The installed public ADS-B adapter can feed Kafka without an OpenSky account. In separate terminals, from the project root:

```powershell
# Terminal 1: use your actual installed Kafka and Java paths
$env:KAFKA_HOME="$env:TEMP/kafka_2.13-4.0.1"
$env:JAVA_HOME="$env:TEMP/jdk-21.0.13.1+2"
.\scripts\kafka.ps1 start
```

```powershell
# Terminal 2: create topics, then publish live regional snapshots
$env:KAFKA_HOME="$env:TEMP/kafka_2.13-4.0.1"
$env:JAVA_HOME="$env:TEMP/jdk-21.0.13.1+2"
.\scripts\kafka.ps1 topics
.\.venv\Scripts\python.exe -m backend.app.streaming.producer --provider adsb-lol --interval 30
```

```powershell
# Terminal 3: persist events before committing Kafka offsets
.\.venv\Scripts\python.exe -m backend.app.streaming.consumer
```

Start the existing API and frontend normally, and select **Kafka stream** on the map. `--bounds S W N E` selects a region, subject to the producer's existing bounds limit. The public provider fetches an 80-nautical-mile radius around the region center and filters to the bounds; it does not promise full coverage of a large box. Provider availability and rate limits still apply.

`--provider opensky` uses the existing OAuth-backed provider and requires `OPENSKY_CLIENT_ID` and `OPENSKY_CLIENT_SECRET`. `--once` publishes one snapshot and exits. `--simulation` emits one explicitly labelled test event. The public provider normalizes feet/knots/feet-per-minute to the shared SI-unit event contract.

The lightweight consumer is an alternative to the existing Spark consumer. Use one consumer path for a deployment. Both use the durable observation/window store and create review alerts from fresh, airborne vertical rates above ±30 m/s. This rule calls for telemetry review; it does not establish a flight delay or emergency. Historical arrival-delay models are not applied to state vectors that lack schedule features.

`GET /api/v1/live/stream-states` reads actual consumed provider events. Only positions and contacts under two minutes old appear; simulation is excluded. Missing data returns `awaiting_stream`; old data returns `stale`. The UI never silently substitutes the direct radar feed into the Kafka view. Kafka does not supply authoritative flight schedules; confirmed present-day delay causes require a separate schedule/operations source.

The local stack uses a single broker and SQLite. Kafka observations, rejects and aggregates are durable but have no automated database retention policy. Back up the store alongside checkpoints; archive old data as operational volume grows. Authentication, per-user inboxes and distributed deployment are outside this upgrade. Keep this configuration bound to localhost.

## Verification

On 22 November 2026, the local Kafka 4.0.1 broker accepted a fresh public
ADS-B snapshot of 144 observations. The lightweight consumer persisted the
events, and `GET /api/v1/live/stream-states` returned 144 fresh aircraft with
`adsb_lol` provenance and provider callsigns. The two local monthly BTS files
contained 1,066,492 records; all 100 records on the sampled first page resolved
carrier and both airport names from the local BTS reference archives. The
dataset explorer now starts unfiltered and paginates across all records.
Provider callsigns are shown as supplied; an aircraft without one is labelled
by its ICAO address rather than assigned an invented flight name.
The Edge smoke check passed all routes with 149 successful OpenStreetMap tile
responses and no page errors.

The backend regression suite, production frontend build, and local HTTP flows were exercised. A labelled simulation event passed through the real broker. Public ADS-B snapshots delivered observations through Kafka; the consumer persisted them and `/live/stream-states` returned fresh positions with `adsb_lol` provenance. Dataset name/coordinate/cause enrichment, selected-model scoring, explanation output, and historical alert creation/listing were checked through the running HTTP API.

Automated tests cover ranking and unavailable-model fallback, malformed metrics, source-backed alert creation, persistence and lifecycle, replay deduplication, stale/simulation exclusion, public-provider unit conversion and SMTP failure/retry/success bookkeeping. SMTP delivery tests use a test sender; no email was sent because SMTP was unconfigured. Authenticated OpenSky was not tested because credentials were absent. The PostgreSQL catalog test remains dependent on the unavailable local database. The later Edge smoke check covered page navigation and selected interactions; native desktop notification delivery was not verified.

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q --tb=short -k "not bts_lookup_tables_have_defensible_source_values"
npm.cmd --prefix frontend run build
```
