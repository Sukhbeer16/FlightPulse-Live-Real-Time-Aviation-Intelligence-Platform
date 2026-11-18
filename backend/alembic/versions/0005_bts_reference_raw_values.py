"""Preserve raw BTS reference values and fingerprint schema versions."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005_bts_reference_raw_values"
down_revision = "0004_versioned_bts_reference_rows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bts_reference_releases",
        sa.Column("fingerprint_schema_version", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "bts_carrier_references",
        sa.Column(
            "source_values",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "bts_airport_references",
        sa.Column(
            "source_values",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("bts_airport_references", "source_values")
    op.drop_column("bts_carrier_references", "source_values")
    op.drop_column("bts_reference_releases", "fingerprint_schema_version")
