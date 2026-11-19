# Phase 8.2.2.4: Transactional BTS Reference Importer

The importer is implemented in
`backend.app.data_ingestion.bts_reference_importer.import_reference_zip`.
It handles one ZIP and one release per call. Use a fresh SQLAlchemy session
with no active transaction; each dataset commits or rolls back independently.
The importer calls the existing ZIP preflight, then rechecks the checksum,
member list, and ZIP CRC while staging the CSV in an automatically cleaned
system temporary directory. It streams rows through
`iter_reference_csv`, uses fingerprint schema v1, and writes bounded batches
(default 500 rows) inside one release transaction.

The importer does not connect canonical Airline or Airport records. It does
not load coordinates, infer source names, or map unresolved date headers into
normalized validity columns. Original ordered `[header, value]` pairs are
stored in `source_values`; DOT IDs remain text. The verified normalized
projection is:

| Dataset field | Reference column |
|---|---|
| Carrier `AIRLINE_ID` | `dot_carrier_id` |
| Carrier `CARRIER` | `carrier_code` (`IATA_CARRIER_CODE`) |
| Carrier `UNIQUE_CARRIER` | `unique_carrier_code` |
| Carrier `CARRIER_NAME` | `carrier_name` |
| Airport `AIRPORT_ID` | `dot_airport_id` |
| Airport `AIRPORT_SEQ_ID` | `dot_airport_seq_id` |
| Airport `AIRPORT` | `bts_airport_code` (`BTS_DOT_AIRPORT_CODE`) |

Carrier date aliases, airport date aliases, airport display-name aliases,
carrier entity/region values, airport lifecycle flags, and all remaining
source fields stay in raw ordered values. Optional blank normalized fields are
NULL; the original blank strings remain unchanged in JSONB.

## Release and retry behavior

- A release is identified by source agency `BTS`, the stable dataset
  identifier, and the verified source ZIP SHA-256.
- A new release starts explicitly as `pending` with the v1 fingerprint schema.
- Rows are unique by `(release_id, row_fingerprint)`. Exact duplicate source
  rows are counted and stored once; no DOT ID, carrier code, airport code, or
  sequence ID is used for deduplication.
- The release becomes `complete` and receives `completed_at` only after full
  parsing, preflight/import count reconciliation, row-count reconciliation,
  and a final source archive integrity/checksum check.
- A database or import failure rolls back the release transaction, then records
  a `failed` release in a separate transaction. Rows written by the failed
  attempt are rolled back; pre-existing rows from an older attempt are not
  deleted and must pass fingerprint/source-value and final-count reconciliation
  on retry. If failed-state recording itself cannot reach the database, the
  importer raises an error explaining that status could not be persisted.
- A retry of a `failed` or `pending` release uses the same release key and
  unique fingerprint constraint. Existing fingerprints are checked against
  their raw source values before continuing. A matching `complete` release is
  returned as already complete only after its schema version, row count, every
  source fingerprint, and raw source values are verified; completed releases
  are never downgraded or overwritten.
- A legacy release with NULL lifecycle/version metadata is left unchanged and
  rejected for manual review. A failed preflight is rejected before database
  work and creates no release row.

No global transaction spans both datasets. Invoke the function once for
Carrier Decode and once for Master Coordinate; each release is atomic on its
own. The importer has no CLI entry point. A later controlled invocation can
call the function from a Python script after database configuration and
migrations are ready.

## Tests and limits

Focused tests use temporary generated ZIPs and a transaction-aware in-memory
store fake. They cover successful completion, retry, exact duplicate
fingerprints, failure rollback and failed status, and preservation of
concurrent carrier entities and airport versions. They do not connect to
PostgreSQL. PostgreSQL `ON CONFLICT DO NOTHING` is used only on the existing
release-scoped fingerprint unique constraints; database integration remains to
be verified before any real import.
