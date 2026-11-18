"""Add immutable BTS release and historical flight tables."""

from alembic import op
import sqlalchemy as sa


revision = "0002_historical_bts_foundation"
down_revision = "0001_initial_catalog_and_flights"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bts_releases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_name", sa.String(length=120), nullable=False),
        sa.Column("reporting_period", sa.Date(), nullable=False),
        sa.Column("source_file_sha256", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("processing_version", sa.String(length=64), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("supersedes_release_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["supersedes_release_id"],
            ["bts_releases.id"],
            name="fk_bts_releases_supersedes_release_id_bts_releases",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_bts_releases"),
        sa.UniqueConstraint(
            "dataset_name",
            "reporting_period",
            "source_file_sha256",
            name="uq_bts_releases_dataset_period_checksum",
        ),
    )

    op.create_table(
        "historical_bts_flights",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column("row_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("reporting_airline_code", sa.String(length=3), nullable=False),
        sa.Column("reporting_dot_carrier_id", sa.Integer(), nullable=True),
        sa.Column("reporting_flight_number", sa.String(length=16), nullable=True),
        sa.Column("flight_date", sa.Date(), nullable=False),
        sa.Column("origin_bts_code", sa.String(length=3), nullable=False),
        sa.Column("destination_bts_code", sa.String(length=3), nullable=False),
        sa.Column("origin_dot_airport_id", sa.Integer(), nullable=True),
        sa.Column("destination_dot_airport_id", sa.Integer(), nullable=True),
        sa.Column("origin_dot_airport_seq_id", sa.Integer(), nullable=True),
        sa.Column("destination_dot_airport_seq_id", sa.Integer(), nullable=True),
        sa.Column("scheduled_departure_hhmm", sa.SmallInteger(), nullable=True),
        sa.Column("actual_departure_hhmm", sa.SmallInteger(), nullable=True),
        sa.Column("scheduled_arrival_hhmm", sa.SmallInteger(), nullable=True),
        sa.Column("actual_arrival_hhmm", sa.SmallInteger(), nullable=True),
        sa.Column("departure_delay_minutes", sa.Integer(), nullable=True),
        sa.Column("arrival_delay_minutes", sa.Integer(), nullable=True),
        sa.Column("cancelled", sa.SmallInteger(), nullable=True),
        sa.Column("diverted", sa.SmallInteger(), nullable=True),
        sa.Column("cancellation_code", sa.String(length=1), nullable=True),
        sa.Column("airline_id", sa.String(length=3), nullable=True),
        sa.Column("origin_airport_id", sa.Integer(), nullable=True),
        sa.Column("destination_airport_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["airline_id"],
            ["airlines.code"],
            name="fk_historical_bts_flights_airline_id_airlines",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["destination_airport_id"],
            ["airports.id"],
            name="fk_historical_bts_flights_destination_airport_id_airports",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["origin_airport_id"],
            ["airports.id"],
            name="fk_historical_bts_flights_origin_airport_id_airports",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["bts_releases.id"],
            name="fk_historical_bts_flights_release_id_bts_releases",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_historical_bts_flights"),
        sa.UniqueConstraint(
            "release_id",
            "row_fingerprint",
            name="uq_historical_bts_flights_release_row_fingerprint",
        ),
    )
    op.create_index(
        "ix_historical_bts_flights_release_date",
        "historical_bts_flights",
        ["release_id", "flight_date"],
    )
    op.create_index(
        "ix_historical_bts_flights_carrier_date",
        "historical_bts_flights",
        ["reporting_dot_carrier_id", "flight_date"],
    )
    op.create_index(
        "ix_historical_bts_flights_route_date",
        "historical_bts_flights",
        ["origin_bts_code", "destination_bts_code", "flight_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_historical_bts_flights_route_date",
        table_name="historical_bts_flights",
    )
    op.drop_index(
        "ix_historical_bts_flights_carrier_date",
        table_name="historical_bts_flights",
    )
    op.drop_index(
        "ix_historical_bts_flights_release_date",
        table_name="historical_bts_flights",
    )
    op.drop_table("historical_bts_flights")
    op.drop_table("bts_releases")
