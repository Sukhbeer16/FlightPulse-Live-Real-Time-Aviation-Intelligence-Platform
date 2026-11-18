# Phase 8.2.1: BTS Reference CSV Parsing Contract

The backend utility in `app/data_ingestion/bts_reference_csv.py` streams the
Carrier Decode and Master Coordinate CSV exports. It requires the exact source
header names and order recorded in the module. UTF-8 is decoded strictly; a
UTF-8 BOM is accepted. Each CSV cell remains its original string, including
leading zeroes, whitespace, empty strings, and date text. No date or identifier
conversion is performed. Rows with malformed CSV syntax or an incorrect field
count are rejected.

Every parsed row exposes its original ordered `[header, value]` pairs for a
future JSONB insert. Header aliases whose meanings remain unresolved are kept
only in these raw pairs; this parser does not populate normalized reference
fields.

## Fingerprint schema v1

The version tag is `flightpulse-bts-reference-row-v1`. Stable dataset
identifiers are `bts-aviation-support:carrier-decode` and
`bts-aviation-support:master-coordinate`. Serialization is deterministic:

1. Encode each metadata/header string as UTF-8, preceded by its unsigned
   8-byte big-endian byte length. Serialize the version tag, dataset identifier,
   then the unsigned 8-byte big-endian header count.
2. For every header in exact source order, serialize the length-prefixed header.
   Then serialize its value with an explicit marker: `0x00` for null, or `0x01`
   followed by the length-prefixed UTF-8 text for a string.
3. Hash the resulting bytes with SHA-256 and return lowercase hexadecimal.

CSV parsing produces strings, so a blank cell is `""` and uses the text marker
plus a zero byte length. It is not converted to null. The fingerprint helper
supports explicit `None` separately, using the null marker. No trimming,
Unicode normalization, case folding, date parsing, or numeric conversion occurs.
Any change to this serialization requires a new fingerprint schema version.

This phase provides parsing and fingerprinting only. Database insertion,
reference-release management, and source artifact handling remain future work.

The focused tests pin the v1 fingerprint with an independently encoded golden
vector and a fixed SHA-256 digest. Parser cases cover commas, escaped quotes,
and embedded newlines in quoted cells, including exact source-value pair
preservation.
