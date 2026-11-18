"""Create airline, airport, and flight tables with PostGIS support."""

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geography


revision = "0001_initial_catalog_and_flights"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "airlines",
        sa.Column("code", sa.String(length=3), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("code", name="pk_airlines"),
    )

    op.create_table(
        "airports",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("iata_code", sa.String(length=3), nullable=True),
        sa.Column("icao_code", sa.String(length=4), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column(
            "location",
            Geography(geometry_type="POINT", srid=4326),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_airports"),
        sa.UniqueConstraint("iata_code", name="uq_airports_iata_code"),
        sa.UniqueConstraint("icao_code", name="uq_airports_icao_code"),
    )
    op.create_index(
        "ix_airports_location", "airports", ["location"], postgresql_using="gist"
    )

    op.create_table(
        "flights",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("source_flight_id", sa.String(length=160), nullable=True),
        sa.Column("flight_number", sa.String(length=20), nullable=True),
        sa.Column("callsign", sa.String(length=16), nullable=True),
        sa.Column("airline_code", sa.String(length=3), nullable=True),
        sa.Column("origin_airport_id", sa.Integer(), nullable=True),
        sa.Column("destination_airport_id", sa.Integer(), nullable=True),
        sa.Column("scheduled_departure_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_arrival_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_departure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_arrival_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["airline_code"], ["airlines.code"],
            name="fk_flights_airline_code_airlines", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["origin_airport_id"], ["airports.id"],
            name="fk_flights_origin_airport_id_airports", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["destination_airport_id"], ["airports.id"],
            name="fk_flights_destination_airport_id_airports", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_flights"),
        sa.UniqueConstraint(
            "source", "source_flight_id", name="uq_flights_source_source_flight_id"
        ),
    )
    op.create_index(
        "ix_flights_scheduled_departure_at",
        "flights",
        ["scheduled_departure_at"],
    )
    op.create_index(
        "ix_flights_origin_destination_departure",
        "flights",
        ["origin_airport_id", "destination_airport_id", "scheduled_departure_at"],
    )
    op.create_index(
        "ix_flights_flight_number",
        "flights",
        ["flight_number"],
        postgresql_where=sa.text("flight_number IS NOT NULL"),
    )
    op.create_index(
        "ix_flights_callsign",
        "flights",
        ["callsign"],
        postgresql_where=sa.text("callsign IS NOT NULL"),
    )
    op.create_index(
        "ix_flights_airline_code",
        "flights",
        ["airline_code"],
        postgresql_where=sa.text("airline_code IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_flights_airline_code", table_name="flights")
    op.drop_index("ix_flights_callsign", table_name="flights")
    op.drop_index("ix_flights_flight_number", table_name="flights")
    op.drop_index("ix_flights_origin_destination_departure", table_name="flights")
    op.drop_index("ix_flights_scheduled_departure_at", table_name="flights")
    op.drop_table("flights")
    op.drop_index("ix_airports_location", table_name="airports")
    op.drop_table("airports")
    op.drop_table("airlines")
