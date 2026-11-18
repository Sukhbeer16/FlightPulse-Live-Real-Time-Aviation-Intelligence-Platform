# Phase 6: BTS reference data foundation

## Identity and provenance

`BTSReferenceRelease` records the source agency, dataset, source artifact
SHA-256, and optional source-release, effective-date, and retrieval-time
metadata. The database records `imported_at` when a row is created. Release
identity is unique by agency, dataset, and artifact checksum; identical bytes
from a distinct dataset or agency therefore remain distinct releases.

`BTSCarrierReference` and `BTSAirportReference` hold source rows within a
release. They retain the DOT carrier and airport identities, and airport
sequence ID where present. Each row has a SHA-256 source-row fingerprint; only
`(release_id, row_fingerprint)` is unique. DOT IDs and codes are deliberately
not unique within a release, so separate historical versions are representable.
Airport sequence-ID uniqueness is not assumed. Reference rows point to their
release with `RESTRICT`. Optional canonical links to `Airline` and `Airport`
use `SET NULL`; deleting a local canonical record therefore does not erase a
source identity.

The source `Carrier` value is stored separately as an IATA carrier code, while
`UniqueCarrier` is kept in `unique_carrier_code`. Neither field replaces the
DOT `AirlineID`. The airport source code is explicitly namespaced as a DOT/BTS
code; `bts_airport_code` is not stored as an IATA or ICAO code. Source names
and validity dates remain separate from canonical catalog attributes.

## Raw source values and fingerprint version (Phase 8.1.5)

Each carrier and airport reference row has a nullable PostgreSQL JSONB
`source_values` field. When populated, it is an ordered array of two-element
`[header, value]` pairs using the original CSV headers and parsed cell text.
This keeps fields whose BTS aliases are not yet verified without assigning
them invented meanings. Empty strings remain empty strings; import code must
not silently change them to JSON null. The original source ZIP should also be
retained unchanged for byte-level provenance.

`BTSReferenceRelease.fingerprint_schema_version` records the version of the
row serialization used for its fingerprints. It is nullable and has no
default so earlier releases are not backfilled with an invented version. A
future importer must set it for new releases. Migration 0005 adds only these
three nullable columns; its downgrade removes only those columns.

## Intended authoritative sources and verification

- **Verified Carrier Decode fields:** `AirlineID`, `Carrier`, `UniqueCarrier`,
  `CarrierName`, `UniqueCarrierName`, and `StartDate`/`EndDate` are listed.
  BTS defines `AirlineID` as the DOT carrier identity, describes `Carrier` as
  an IATA code that can be reused, and describes `UniqueCarrier` as a
  disambiguated carrier code. The date fields describe carrier-code validity.
  See the [Carrier Decode field definitions](https://transtats.bts.gov/Fields.asp?gnoyr_VQ=GDH).
- **Verified Master Coordinate fields:** `AirportID`, `AirportSeqID`,
  `Airport`, `AirportName`, `AirportStartDate`, and `AirportEndDate` are listed.
  BTS defines the airport ID across years and sequence ID at a point in time;
  it defines `Airport` as a DOT-issued three-character alphanumeric code that
  can change or be reused. See the [Master Coordinate field definitions](https://transtats.bts.gov/Fields.asp?gnoyr_VQ=FLL).
- The accessible field pages provide descriptions, not physical source column
  types or representative records. Those types and observed row-level
  uniqueness still require validation against a small source sample. In
  particular, the model does not assume `AirportSeqID` uniqueness.
- BTS airport codes are not asserted to be IATA or ICAO. Canonical airport links
  require a separately verified crosswalk or manual review. No external
  crosswalk has been selected or loaded in this phase.

## Limitations and next work

Fingerprint canonicalization is intentionally not implemented here; a future
importer must define it from stable source fields and preserve original values.
Migration 0004 refuses to upgrade if reference-release or reference-record
rows already exist, because the old schema lacks checksums and fingerprints
that can be backfilled without inventing them. Its downgrade also refuses to
run while those rows exist, since the previous constraints cannot represent
multiple dated versions and the new provenance fields must not be discarded.

The application must decide how to map BTS carrier identities to existing
operational `Airline` rows and airport identities to `Airport` rows; ambiguous
and missing matches must stay unresolved. Actual physical source types and
representative values remain unverified. An ingestion implementation should
record source release/effective and retrieval metadata only when known, and
should not infer IANA timezones or populate canonical location fields from
unverified values.

## Text identifiers and release lifecycle (Phase 8.2.2.1)

Migration 0006 changes `dot_carrier_id`, `dot_airport_id`, and
`dot_airport_seq_id` to PostgreSQL `TEXT`. These are source identifiers, so
application code must preserve their original string form and must not coerce
them to integers. The migration refuses to upgrade when carrier or airport
reference rows exist: integer storage may already have removed leading zeroes,
and converting those values to text cannot restore the original formatting. If
that guard fires, stop for manual review against retained raw source values or
an authoritative BTS artifact. Do not delete, rewrite, or claim recovery of
unavailable original formatting. Downgrade also refuses to run while any
reference release or carrier/airport reference row exists, since it would
discard lifecycle state or narrow identifier values.

`BTSReferenceRelease.status` is nullable and has no database or application
default. `NULL` means the release predates lifecycle tracking and its state is
unknown; the migration does not label old releases pending or complete. New
importer-created releases must explicitly start as `pending`, become `failed`
on a failed attempt, and become `complete` only after rows and reconciliation
succeed. `completed_at` is nullable and is required exactly when status is
`complete`; `imported_at` remains a creation timestamp and is not a completion
signal.
