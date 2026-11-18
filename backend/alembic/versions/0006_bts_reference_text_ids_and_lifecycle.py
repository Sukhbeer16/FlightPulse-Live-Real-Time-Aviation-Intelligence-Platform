"""Preserve BTS identifiers as text and track reference release lifecycle."""

from alembic import op
import sqlalchemy as sa


revision = "0006_bts_ref_lifecycle"
down_revision = "0005_bts_reference_raw_values"
branch_labels = None
depends_on = None


_NO_REFERENCE_ROWS_GUARD = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM bts_carrier_references LIMIT 1)
       OR EXISTS (SELECT 1 FROM bts_airport_references LIMIT 1) THEN
        RAISE EXCEPTION
            'Cannot convert BTS DOT identifiers from integer to text while reference rows exist; original leading-zero formatting may already be lost and requires manual review.';
    END IF;
END $$;
"""

_EMPTY_REFERENCE_TABLES_GUARD = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM bts_reference_releases LIMIT 1)
       OR EXISTS (SELECT 1 FROM bts_carrier_references LIMIT 1)
       OR EXISTS (SELECT 1 FROM bts_airport_references LIMIT 1) THEN
        RAISE EXCEPTION
            'Cannot downgrade BTS reference identifier and lifecycle schema while release or reference rows exist; conversion would lose lifecycle data or may not preserve identifier text.';
    END IF;
END $$;
"""


def upgrade() -> None:
    # An integer-to-text cast cannot recover any leading zeroes previously lost.
    op.execute(sa.text(_NO_REFERENCE_ROWS_GUARD))

    op.alter_column(
        "bts_carrier_references",
        "dot_carrier_id",
        existing_type=sa.Integer(),
        type_=sa.Text(),
        existing_nullable=False,
        postgresql_using="dot_carrier_id::text",
    )
    op.alter_column(
        "bts_airport_references",
        "dot_airport_id",
        existing_type=sa.Integer(),
        type_=sa.Text(),
        existing_nullable=False,
        postgresql_using="dot_airport_id::text",
    )
    op.alter_column(
        "bts_airport_references",
        "dot_airport_seq_id",
        existing_type=sa.Integer(),
        type_=sa.Text(),
        existing_nullable=True,
        postgresql_using="dot_airport_seq_id::text",
    )

    # Nullable with no default keeps existing releases explicitly legacy/unknown.
    op.add_column(
        "bts_reference_releases",
        sa.Column("status", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "bts_reference_releases",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_bts_reference_releases_status_valid",
        "bts_reference_releases",
        "status IS NULL OR status IN ('pending', 'failed', 'complete')",
    )
    op.create_check_constraint(
        "ck_bts_reference_releases_completion_timestamp_matches_status",
        "bts_reference_releases",
        """CASE
            WHEN status IS NULL THEN completed_at IS NULL
            WHEN status = 'complete' THEN completed_at IS NOT NULL
            ELSE completed_at IS NULL
        END""",
    )


def downgrade() -> None:
    # Reverting could discard status/completion information and narrow arbitrary
    # source identifiers. Require all three reference tables to be empty.
    op.execute(sa.text(_EMPTY_REFERENCE_TABLES_GUARD))

    op.drop_constraint(
        "ck_bts_reference_releases_completion_timestamp_matches_status",
        "bts_reference_releases",
        type_="check",
    )
    op.drop_constraint(
        "ck_bts_reference_releases_status_valid",
        "bts_reference_releases",
        type_="check",
    )
    op.drop_column("bts_reference_releases", "completed_at")
    op.drop_column("bts_reference_releases", "status")

    op.alter_column(
        "bts_airport_references",
        "dot_airport_seq_id",
        existing_type=sa.Text(),
        type_=sa.Integer(),
        existing_nullable=True,
        postgresql_using="dot_airport_seq_id::integer",
    )
    op.alter_column(
        "bts_airport_references",
        "dot_airport_id",
        existing_type=sa.Text(),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="dot_airport_id::integer",
    )
    op.alter_column(
        "bts_carrier_references",
        "dot_carrier_id",
        existing_type=sa.Text(),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="dot_carrier_id::integer",
    )
