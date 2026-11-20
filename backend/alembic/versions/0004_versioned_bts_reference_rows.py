"""Allow time-versioned BTS reference rows with source checksums."""

from alembic import op
import sqlalchemy as sa


revision = "0004_bts_ref_versioning"
down_revision = "0003_bts_reference_data"
branch_labels = None
depends_on = None


_EMPTY_REFERENCE_TABLES_GUARD = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM bts_reference_releases LIMIT 1)
       OR EXISTS (SELECT 1 FROM bts_carrier_references LIMIT 1)
       OR EXISTS (SELECT 1 FROM bts_airport_references LIMIT 1) THEN
        RAISE EXCEPTION
            'Cannot alter the BTS reference schema while reference releases or records exist; a data-preserving conversion is required.';
    END IF;
END $$;
"""


def upgrade() -> None:
    # No truthful fingerprint/checksum can be derived from the old schema.
    # Refuse to alter any installed reference data instead of fabricating values.
    op.execute(sa.text(_EMPTY_REFERENCE_TABLES_GUARD))

    # The new unique (agency, dataset, checksum) index covers agency/dataset
    # prefix lookups, so the previous two-column index is redundant.
    op.drop_index(
        "ix_bts_reference_releases_source_dataset",
        table_name="bts_reference_releases",
    )

    op.drop_constraint(
        "uq_bts_carrier_references_release_dot_carrier_id",
        "bts_carrier_references",
        type_="unique",
    )
    op.drop_constraint(
        "ck_bts_carrier_references_carrier_code_namespace",
        "bts_carrier_references",
        type_="check",
    )
    op.drop_constraint(
        "uq_bts_airport_references_release_dot_airport_id",
        "bts_airport_references",
        type_="unique",
    )
    op.drop_constraint(
        "uq_bts_airport_references_release_dot_airport_seq_id",
        "bts_airport_references",
        type_="unique",
    )

    op.alter_column(
        "bts_carrier_references",
        "reporting_carrier_code",
        new_column_name="carrier_code",
        existing_type=sa.String(length=8),
        existing_nullable=True,
    )
    op.alter_column(
        "bts_carrier_references",
        "reporting_carrier_code_namespace",
        new_column_name="carrier_code_namespace",
        existing_type=sa.String(length=40),
        existing_nullable=False,
        existing_server_default="BTS_REPORTING_CARRIER_CODE",
        server_default="IATA_CARRIER_CODE",
    )

    op.add_column(
        "bts_reference_releases",
        sa.Column("source_artifact_sha256", sa.String(length=64), nullable=False),
    )
    op.add_column(
        "bts_carrier_references",
        sa.Column("row_fingerprint", sa.String(length=64), nullable=False),
    )
    op.add_column(
        "bts_carrier_references",
        sa.Column("unique_carrier_code", sa.String(length=8), nullable=True),
    )
    op.add_column(
        "bts_airport_references",
        sa.Column("row_fingerprint", sa.String(length=64), nullable=False),
    )

    op.create_check_constraint(
        "ck_bts_reference_releases_source_artifact_sha256_format",
        "bts_reference_releases",
        "source_artifact_sha256 ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "ck_bts_carrier_references_row_fingerprint_format",
        "bts_carrier_references",
        "row_fingerprint ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "ck_bts_airport_references_row_fingerprint_format",
        "bts_airport_references",
        "row_fingerprint ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "ck_bts_carrier_references_carrier_code_namespace",
        "bts_carrier_references",
        "carrier_code_namespace = 'IATA_CARRIER_CODE'",
    )

    op.create_unique_constraint(
        "uq_bts_reference_releases_source_dataset_checksum",
        "bts_reference_releases",
        ["source_agency", "dataset_name", "source_artifact_sha256"],
    )
    op.create_unique_constraint(
        "uq_bts_carrier_references_release_row_fingerprint",
        "bts_carrier_references",
        ["release_id", "row_fingerprint"],
    )
    op.create_unique_constraint(
        "uq_bts_airport_references_release_row_fingerprint",
        "bts_airport_references",
        ["release_id", "row_fingerprint"],
    )

    op.create_index(
        "ix_bts_carrier_references_carrier_code",
        "bts_carrier_references",
        ["carrier_code"],
    )
    op.create_index(
        "ix_bts_carrier_references_unique_carrier_code",
        "bts_carrier_references",
        ["unique_carrier_code"],
    )
    op.create_index(
        "ix_bts_airport_references_bts_airport_code",
        "bts_airport_references",
        ["bts_airport_code"],
    )


def downgrade() -> None:
    # The old schema cannot retain these provenance fields or represent
    # multiple dated versions for one DOT identity. Require an empty dataset.
    op.execute(sa.text(_EMPTY_REFERENCE_TABLES_GUARD))

    op.drop_index(
        "ix_bts_airport_references_bts_airport_code",
        table_name="bts_airport_references",
    )
    op.drop_index(
        "ix_bts_carrier_references_unique_carrier_code",
        table_name="bts_carrier_references",
    )
    op.drop_index(
        "ix_bts_carrier_references_carrier_code",
        table_name="bts_carrier_references",
    )

    op.drop_constraint(
        "uq_bts_airport_references_release_row_fingerprint",
        "bts_airport_references",
        type_="unique",
    )
    op.drop_constraint(
        "uq_bts_carrier_references_release_row_fingerprint",
        "bts_carrier_references",
        type_="unique",
    )
    op.drop_constraint(
        "uq_bts_reference_releases_source_dataset_checksum",
        "bts_reference_releases",
        type_="unique",
    )
    op.drop_constraint(
        "ck_bts_carrier_references_carrier_code_namespace",
        "bts_carrier_references",
        type_="check",
    )
    op.drop_constraint(
        "ck_bts_airport_references_row_fingerprint_format",
        "bts_airport_references",
        type_="check",
    )
    op.drop_constraint(
        "ck_bts_carrier_references_row_fingerprint_format",
        "bts_carrier_references",
        type_="check",
    )
    op.drop_constraint(
        "ck_bts_reference_releases_source_artifact_sha256_format",
        "bts_reference_releases",
        type_="check",
    )

    op.drop_column("bts_airport_references", "row_fingerprint")
    op.drop_column("bts_carrier_references", "unique_carrier_code")
    op.drop_column("bts_carrier_references", "row_fingerprint")
    op.drop_column("bts_reference_releases", "source_artifact_sha256")
    op.alter_column(
        "bts_carrier_references",
        "carrier_code_namespace",
        new_column_name="reporting_carrier_code_namespace",
        existing_type=sa.String(length=40),
        existing_nullable=False,
        existing_server_default="IATA_CARRIER_CODE",
        server_default="BTS_REPORTING_CARRIER_CODE",
    )
    op.alter_column(
        "bts_carrier_references",
        "carrier_code",
        new_column_name="reporting_carrier_code",
        existing_type=sa.String(length=8),
        existing_nullable=True,
    )

    op.create_check_constraint(
        "ck_bts_carrier_references_carrier_code_namespace",
        "bts_carrier_references",
        "reporting_carrier_code_namespace = 'BTS_REPORTING_CARRIER_CODE'",
    )
    op.create_unique_constraint(
        "uq_bts_carrier_references_release_dot_carrier_id",
        "bts_carrier_references",
        ["release_id", "dot_carrier_id"],
    )
    op.create_unique_constraint(
        "uq_bts_airport_references_release_dot_airport_id",
        "bts_airport_references",
        ["release_id", "dot_airport_id"],
    )
    op.create_unique_constraint(
        "uq_bts_airport_references_release_dot_airport_seq_id",
        "bts_airport_references",
        ["release_id", "dot_airport_seq_id"],
    )
    op.create_index(
        "ix_bts_reference_releases_source_dataset",
        "bts_reference_releases",
        ["source_agency", "dataset_name"],
    )
