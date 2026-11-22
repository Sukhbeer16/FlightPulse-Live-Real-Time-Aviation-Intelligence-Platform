# Operational alert inbox

Alerts are persisted in ignored `data/operations/alerts.sqlite`. Historical
alerts reload a real BTS row; telemetry review alerts require a fresh,
airborne provider observation with an absolute vertical rate above 30 m/s.
The latter is a review flag, not an emergency or delay. Statistical model
output does not automatically create a high-severity operational alert.

Historical IDs are deterministic from source file and row; telemetry IDs
use provider, ICAO address and five-minute observation window. Reprocessing
cannot duplicate or reopen an alert. The status path is open → acknowledged
→ resolved. Status changes record update, acknowledgement and resolution
times. A resolved alert cannot be acknowledged again.

`GET /api/v1/alerts` provides server-side pagination and filters for status,
severity, type, search and demonstration inclusion. `GET /api/v1/alerts/counts`
counts the full operational store, excluding demonstration alerts by default.
The UI exposes these filters, page controls, evidence details, acknowledge
and resolve actions. It refreshes every 15 seconds. The demonstration
`POST /api/v1/alerts/evaluate` remains explicitly labelled and is excluded
from ordinary operational counts.

Browser notifications require a grant and an open tab. Optional email
delivery uses server-side SMTP settings and a separate worker; an SMTP
acceptance is not proof of mailbox delivery. See `operations-upgrade.md` for
configuration and retry semantics. The inbox has no per-user authentication
and should remain bound to localhost in this setup.
