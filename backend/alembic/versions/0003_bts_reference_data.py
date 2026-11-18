"""Add versioned BTS/DOT carrier and airport reference data."""

from alembic import op
import sqlalchemy as sa


revision = "0003_bts_reference_data"
down_revision = "0002_historical_bts_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bts_reference_releases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_agency", sa.String(length=80), nullable=False),
        sa.Column("dataset_name", sa.String(length=120), nullable=False),
        sa.Column("source_release", sa.String(length=120), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_bts_reference_releases"),
    )
    op.create_index(
        "ix_bts_reference_releases_source_dataset",
        "bts_reference_releases",
        ["source_agency", "dataset_name"],
    )

    op.create_table(
        "bts_carrier_references",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column("dot_carrier_id", sa.Integer(), nullable=False),
        sa.Column("reporting_carrier_code", sa.String(length=8), nullable=True),
        sa.Column(
            "reporting_carrier_code_namespace",
            sa.String(length=40),
            server_default="BTS_REPORTING_CARRIER_CODE",
            nullable=False,
        ),
        sa.Column("carrier_name", sa.String(length=200), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("airline_code", sa.String(length=3), nullable=True),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="ck_bts_carrier_references_valid_dates",
        ),
        sa.CheckConstraint(
            "reporting_carrier_code_namespace = 'BTS_REPORTING_CARRIER_CODE'",
            name="ck_bts_carrier_references_carrier_code_namespace",
        ),
        sa.ForeignKeyConstraint(
            ["airline_code"],
            ["airlines.code"],
            name="fk_bts_carrier_references_airline_code_airlines",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["bts_reference_releases.id"],
            name="fk_bts_carrier_references_release_id_bts_reference_releases",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_bts_carrier_references"),
        sa.UniqueConstraint(
            "release_id",
            "dot_carrier_id",
            name="uq_bts_carrier_references_release_dot_carrier_id",
        ),
    )
    op.create_index(
        "ix_bts_carrier_references_dot_carrier_id",
        "bts_carrier_references",
        ["dot_carrier_id"],
    )
    op.create_index(
        "ix_bts_carrier_references_airline_code",
        "bts_carrier_references",
        ["airline_code"],
    )

    op.create_table(
        "bts_airport_references",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column("dot_airport_id", sa.Integer(), nullable=False),
        sa.Column("dot_airport_seq_id", sa.Integer(), nullable=True),
        sa.Column("bts_airport_code", sa.String(length=3), nullable=True),
        sa.Column(
            "airport_code_namespace",
            sa.String(length=32),
            server_default="BTS_DOT_AIRPORT_CODE",
            nullable=False,
        ),
        sa.Column("airport_name", sa.String(length=200), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("airport_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="ck_bts_airport_references_valid_dates",
        ),
        sa.CheckConstraint(
            "airport_code_namespace = 'BTS_DOT_AIRPORT_CODE'",
            name="ck_bts_airport_references_airport_code_namespace",
        ),
        sa.ForeignKeyConstraint(
            ["airport_id"],
            ["airports.id"],
            name="fk_bts_airport_references_airport_id_airports",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["bts_reference_releases.id"],
            name="fk_bts_airport_references_release_id_bts_reference_releases",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_bts_airport_references"),
        sa.UniqueConstraint(
            "release_id",
            "dot_airport_id",
            name="uq_bts_airport_references_release_dot_airport_id",
        ),
        sa.UniqueConstraint(
            "release_id",
            "dot_airport_seq_id",
            name="uq_bts_airport_references_release_dot_airport_seq_id",
        ),
    )
    op.create_index(
        "ix_bts_airport_references_dot_airport_id",
        "bts_airport_references",
        ["dot_airport_id"],
    )
    op.create_index(
        "ix_bts_airport_references_dot_airport_seq_id",
        "bts_airport_references",
        ["dot_airport_seq_id"],
    )
    op.create_index(
        "ix_bts_airport_references_airport_id",
        "bts_airport_references",
        ["airport_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_bts_airport_references_airport_id",
        table_name="bts_airport_references",
    )
    op.drop_index(
        "ix_bts_airport_references_dot_airport_seq_id",
        table_name="bts_airport_references",
    )
    op.drop_index(
        "ix_bts_airport_references_dot_airport_id",
        table_name="bts_airport_references",
    )
    op.drop_table("bts_airport_references")

    op.drop_index(
        "ix_bts_carrier_references_airline_code",
        table_name="bts_carrier_references",
    )
    op.drop_index(
        "ix_bts_carrier_references_dot_carrier_id",
        table_name="bts_carrier_references",
    )
    op.drop_table("bts_carrier_references")

    op.drop_index(
        "ix_bts_reference_releases_source_dataset",
        table_name="bts_reference_releases",
    )
    op.drop_table("bts_reference_releases")
