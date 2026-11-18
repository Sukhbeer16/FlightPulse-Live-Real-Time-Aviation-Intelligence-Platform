"""Database-metadata checks for BTS source identity constraints."""

import ast
from pathlib import Path

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from backend.app.database.models import (
    BTSAirportReference,
    BTSCarrierReference,
    BTSReferenceRelease,
)


def _unique_column_sets(model: type) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in model.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _check_sql(model: type) -> set[str]:
    return {
        str(constraint.sqltext)
        for constraint in model.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }


def _model_check_sql(model: type, name_suffix: str) -> str:
    return next(
        str(constraint.sqltext)
        for constraint in model.__table__.constraints
        if isinstance(constraint, CheckConstraint)
        and constraint.name.endswith(name_suffix)
    )


def _migration_check_sql(migration_text: str, constraint_name: str) -> str:
    syntax_tree = ast.parse(migration_text)
    for node in ast.walk(syntax_tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "create_check_constraint" or len(node.args) < 3:
            continue
        if ast.literal_eval(node.args[0]) == constraint_name:
            return ast.literal_eval(node.args[2])
    raise AssertionError(f"Migration constraint not found: {constraint_name}")


def _lifecycle_constraints_accept(status: str | None, has_completed_at: bool) -> bool:
    """Evaluate the documented status whitelist and CASE outcomes statically."""
    status_is_allowed = status is None or status in {
        "pending",
        "failed",
        "complete",
    }
    if status is None:
        completion_timestamp_matches = not has_completed_at
    elif status == "complete":
        completion_timestamp_matches = has_completed_at
    else:
        completion_timestamp_matches = not has_completed_at
    return status_is_allowed and completion_timestamp_matches


def _normalize_sql(sql: str) -> str:
    return " ".join(sql.split()).lower()


def test_multiple_carrier_versions_per_dot_identity_are_supported() -> None:
    """Carrier versions use their source-row fingerprint, not DOT ID, as identity."""
    unique_sets = _unique_column_sets(BTSCarrierReference)
    assert ("release_id", "row_fingerprint") in unique_sets
    assert ("release_id", "dot_carrier_id") not in unique_sets


def test_multiple_airport_versions_per_dot_identity_are_supported() -> None:
    """Neither stable airport ID nor AirportSeqID is assumed unique here."""
    unique_sets = _unique_column_sets(BTSAirportReference)
    assert ("release_id", "row_fingerprint") in unique_sets
    assert ("release_id", "dot_airport_id") not in unique_sets
    assert ("release_id", "dot_airport_seq_id") not in unique_sets


def test_carrier_code_fields_and_namespaces_are_separate() -> None:
    """Carrier and UniqueCarrier remain distinct from canonical Airline codes."""
    assert (
        "carrier_code_namespace = 'IATA_CARRIER_CODE'"
        in _check_sql(BTSCarrierReference)
    )
    assert "carrier_code" in BTSCarrierReference.__table__.c
    assert "unique_carrier_code" in BTSCarrierReference.__table__.c
    assert "airline_code" in BTSCarrierReference.__table__.c
    assert "reporting_carrier_code" not in BTSCarrierReference.__table__.c


def test_airport_source_code_namespace_is_distinct_from_iata_and_icao() -> None:
    """The DOT airport code cannot be confused with canonical airport codes."""
    assert (
        "airport_code_namespace = 'BTS_DOT_AIRPORT_CODE'"
        in _check_sql(BTSAirportReference)
    )
    assert "bts_airport_code" in BTSAirportReference.__table__.c
    assert "airport_code_namespace" in BTSAirportReference.__table__.c
    assert "iata_code" not in BTSAirportReference.__table__.c
    assert "icao_code" not in BTSAirportReference.__table__.c


def test_fingerprints_are_release_scoped() -> None:
    """Source row fingerprints are unique only within their immutable release."""
    assert ("release_id", "row_fingerprint") in _unique_column_sets(
        BTSCarrierReference
    )
    assert ("release_id", "row_fingerprint") in _unique_column_sets(
        BTSAirportReference
    )


def test_release_artifact_checksum_is_unique_by_source_and_dataset() -> None:
    """Distinct sources and datasets may reuse bytes without identity collision."""
    assert (
        "source_agency",
        "dataset_name",
        "source_artifact_sha256",
    ) in _unique_column_sets(BTSReferenceRelease)
    assert BTSReferenceRelease.__table__.c.source_artifact_sha256.nullable is False


def test_raw_source_values_are_nullable_jsonb() -> None:
    """Raw ordered source values can be added without backfilling old rows."""
    assert isinstance(BTSCarrierReference.__table__.c.source_values.type, JSONB)
    assert BTSCarrierReference.__table__.c.source_values.nullable is True
    assert isinstance(BTSAirportReference.__table__.c.source_values.type, JSONB)
    assert BTSAirportReference.__table__.c.source_values.nullable is True


def test_fingerprint_schema_version_is_nullable_without_a_default() -> None:
    """Existing releases need no invented fingerprint-version value."""
    column = BTSReferenceRelease.__table__.c.fingerprint_schema_version
    assert column.nullable is True
    assert column.server_default is None
    assert column.default is None


def test_raw_source_values_preserve_ordered_header_value_pairs() -> None:
    """Source header/value pairs remain ordered and empty text remains text."""
    source_values = [
        ["AIRPORT_ID", "10001"],
        ["AIRPORT", "01A"],
        ["AIRPORT_THRU_DATE", ""],
    ]
    reference = BTSAirportReference(source_values=source_values)

    assert reference.source_values == source_values
    assert reference.source_values[0] == ["AIRPORT_ID", "10001"]
    assert reference.source_values[1] == ["AIRPORT", "01A"]
    assert reference.source_values[2] == ["AIRPORT_THRU_DATE", ""]


def test_canonical_mappings_are_nullable_and_validity_is_checked() -> None:
    """Unresolved mappings remain valid, with inverted date ranges rejected."""
    assert BTSCarrierReference.__table__.c.airline_code.nullable is True
    assert BTSAirportReference.__table__.c.airport_id.nullable is True
    assert any(
        "valid_to >= valid_from" in sql for sql in _check_sql(BTSCarrierReference)
    )
    assert any(
        "valid_to >= valid_from" in sql for sql in _check_sql(BTSAirportReference)
    )


def test_reference_foreign_keys_preserve_provenance_and_null_canonical_links() -> None:
    """Release rows are retained; deleted canonical records only clear the mapping."""
    carrier_fks = [
        constraint
        for constraint in BTSCarrierReference.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    ]
    airport_fks = [
        constraint
        for constraint in BTSAirportReference.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    ]

    assert {
        fk.ondelete for constraint in carrier_fks for fk in constraint.elements
    } == {"RESTRICT", "SET NULL"}
    assert {
        fk.ondelete for constraint in airport_fks for fk in constraint.elements
    } == {"RESTRICT", "SET NULL"}
    assert BTSReferenceRelease.__table__.c.source_agency.nullable is False
    assert BTSReferenceRelease.__table__.c.dataset_name.nullable is False
    assert BTSReferenceRelease.__table__.c.retrieved_at.nullable is True


def test_dot_identifiers_use_unbounded_text_columns() -> None:
    """Source identifiers retain their lexical form without length assumptions."""
    assert isinstance(BTSCarrierReference.__table__.c.dot_carrier_id.type, Text)
    assert BTSCarrierReference.__table__.c.dot_carrier_id.nullable is False
    assert isinstance(BTSAirportReference.__table__.c.dot_airport_id.type, Text)
    assert BTSAirportReference.__table__.c.dot_airport_id.nullable is False
    assert isinstance(BTSAirportReference.__table__.c.dot_airport_seq_id.type, Text)
    assert BTSAirportReference.__table__.c.dot_airport_seq_id.nullable is True


def test_release_lifecycle_preserves_legacy_unknown_state() -> None:
    """Legacy releases remain nullable; completion requires a timestamp."""
    release_table = BTSReferenceRelease.__table__
    assert release_table.c.status.nullable is True
    assert release_table.c.status.default is None
    assert release_table.c.status.server_default is None
    assert release_table.c.completed_at.nullable is True
    checks = _check_sql(BTSReferenceRelease)
    assert any(
        "status IS NULL OR status IN ('pending', 'failed', 'complete')" in sql
        for sql in checks
    )


@pytest.mark.parametrize(
    ("status", "has_completed_at", "expected"),
    [
        (None, False, True),
        (None, True, False),
        ("pending", False, True),
        ("pending", True, False),
        ("failed", False, True),
        ("failed", True, False),
        ("complete", False, False),
        ("complete", True, True),
        ("unknown", False, False),
        ("unknown", True, False),
    ],
)
def test_release_lifecycle_truth_table_and_orm_migration_parity(
    status: str | None, has_completed_at: bool, expected: bool
) -> None:
    """All lifecycle combinations follow the NULL-safe CASE contract."""
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0006_bts_reference_text_ids_and_lifecycle.py"
    )
    migration_text = migration_path.read_text(encoding="utf-8")
    expected_completion_sql = """CASE
        WHEN status IS NULL THEN completed_at IS NULL
        WHEN status = 'complete' THEN completed_at IS NOT NULL
        ELSE completed_at IS NULL
    END"""
    orm_completion_sql = _model_check_sql(
        BTSReferenceRelease, "completion_timestamp_matches_status"
    )
    migration_completion_sql = _migration_check_sql(
        migration_text,
        "ck_bts_reference_releases_completion_timestamp_matches_status",
    )
    assert _normalize_sql(orm_completion_sql) == _normalize_sql(
        expected_completion_sql
    )
    assert _normalize_sql(migration_completion_sql) == _normalize_sql(
        expected_completion_sql
    )

    expected_status_sql = (
        "status IS NULL OR status IN ('pending', 'failed', 'complete')"
    )
    orm_status_sql = _model_check_sql(BTSReferenceRelease, "status_valid")
    migration_status_sql = _migration_check_sql(
        migration_text, "ck_bts_reference_releases_status_valid"
    )
    assert _normalize_sql(orm_status_sql) == _normalize_sql(expected_status_sql)
    assert _normalize_sql(migration_status_sql) == _normalize_sql(expected_status_sql)

    result = _lifecycle_constraints_accept(status, has_completed_at)
    assert isinstance(result, bool)
    assert result is expected


def test_identifier_migration_guards_existing_rows_before_type_conversion() -> None:
    """Integer identifiers are not cast when existing formatting may be lost."""
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0006_bts_reference_text_ids_and_lifecycle.py"
    )
    migration = migration_path.read_text(encoding="utf-8")

    assert 'revision = "0006_bts_ref_lifecycle"' in migration
    assert 'down_revision = "0005_bts_reference_raw_values"' in migration
    assert 'sa.Column("status", sa.String(length=16), nullable=True)' in migration
    assert (
        'sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True)'
        in migration
    )
    assert "server_default=\"pending\"" not in migration
    assert "UPDATE bts_reference_releases SET status" not in migration

    upgrade_body = migration.split("def upgrade()", maxsplit=1)[1].split(
        "def downgrade()", maxsplit=1
    )[0]
    first_type_change = upgrade_body.index('"dot_carrier_id"')
    assert upgrade_body.index(
        "op.execute(sa.text(_NO_REFERENCE_ROWS_GUARD))"
    ) < first_type_change
    assert "FROM bts_carrier_references LIMIT 1" in migration
    assert "FROM bts_airport_references LIMIT 1" in migration
    assert "original leading-zero formatting may already be lost" in migration
    assert "postgresql_using=\"dot_carrier_id::text\"" in migration
    assert "postgresql_using=\"dot_airport_id::text\"" in migration
    assert "postgresql_using=\"dot_airport_seq_id::text\"" in migration

    downgrade_body = migration.split("def downgrade()", maxsplit=1)[1]
    assert downgrade_body.index(
        "op.execute(sa.text(_EMPTY_REFERENCE_TABLES_GUARD))"
    ) < downgrade_body.index("op.drop_constraint")
    assert "FROM bts_reference_releases LIMIT 1" in migration
