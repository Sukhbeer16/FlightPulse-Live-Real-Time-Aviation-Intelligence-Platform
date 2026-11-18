# Phase 8.2.2.3: BTS Reference ZIP Dry-Run Preflight

`backend.app.data_ingestion.bts_reference_preflight.preflight_reference_zip`
validates one local Carrier Decode or Master Coordinate ZIP without connecting
to PostgreSQL or inserting data. It verifies the ZIP SHA-256 against the
approved local artifact checksum, checks all ZIP members and CRC values, and
requires exactly the expected CSV member. It reuses
`iter_reference_csv` for exact header, UTF-8, row-width, and v1 fingerprint
validation.

The preflight pins these source artifacts:

| Dataset identifier | ZIP path | Expected CSV member | Expected ZIP SHA-256 |
|---|---|---|---|
| `bts-aviation-support:carrier-decode` | `data/reference/Carrier_Decode.zip` | `T_CARRIER_DECODE.csv` | `1912da934d5dbfe2dfb92ce1a633c1a98ddc819e2f7f104cd14b708065d6ec81` |
| `bts-aviation-support:master-coordinate` | `data/reference/Master_Coordinate.zip` | `T_MASTER_CORD.csv` | `683659c7e701e9c8105a31f725833a01c246de9bef9895f83bec76f8c2943695` |

The existing parser accepts a filesystem path, so preflight copies only the
selected member in 1 MiB chunks to an automatically removed system temporary
directory. The source ZIP is never extracted into or modified under
`data/reference/`. CSV parsing is row streaming. Preflight retains fingerprint
strings and counters keyed by source identity rather than storing row bodies;
memory grows with the number of distinct fingerprints and observed identity
values, which is small relative to the local reference artifacts.

The report includes total successfully parsed rows, unique fingerprints, exact
duplicate occurrences, rejected/malformed rows, reconciliation, fingerprint
repeatability, and candidate identity groups. Candidate groups are reported
with a count and up to 20 sorted identity/count examples, without deduplicating
distinct fingerprints; repeated AirlineID, AirportID, or AirportSeqID values
may represent versions and are not automatically errors.
Rows with empty required DOT identity values are reported as incompatible with
the current non-null model columns. Carrier Decode requires `AIRLINE_ID`;
Master Coordinate requires both `AIRPORT_ID` and `AIRPORT_SEQ_ID`. An empty
value in either required airport identifier blocks `dry_run_ready`; preflight
does not derive or substitute identifiers. Identifiers remain strings.

The model compatibility result inspects SQLAlchemy metadata only. It does not
verify the live database schema or whether a matching release already exists;
`matching_release_status` remains explicitly unchecked without database access.
Structural CSV errors fail preflight. On a malformed row, parsing stops at the
first error, so row counts describe the successfully parsed prefix and the
report marks parsing/reconciliation as incomplete/failed rather than implying
full-file counts.

Focused tests cover duplicate expected member names, malformed rows after valid
rows, inconsistent count summaries, both required airport identifiers,
independent dataset reports, temporary-file cleanup, and source ZIP integrity
across successful and failed scans. Tests use generated temporary ZIP files.

Example use from the repository root:

```python
from backend.app.data_ingestion.bts_reference_csv import (
    CARRIER_DECODE_DATASET,
    MASTER_COORDINATE_DATASET,
)
from backend.app.data_ingestion.bts_reference_preflight import (
    preflight_reference_zip,
)

carrier_report = preflight_reference_zip(
    "data/reference/Carrier_Decode.zip", CARRIER_DECODE_DATASET
)
airport_report = preflight_reference_zip(
    "data/reference/Master_Coordinate.zip", MASTER_COORDINATE_DATASET
)
```

`dry_run_ready` is true only when checksum, ZIP integrity, member selection,
headers, complete row parsing, reconciliation, repeat fingerprints, model
metadata compatibility, and required identity presence all pass. Database
schema and release status must be checked separately before any future import;
this dry-run result alone does not authorize database insertion.
