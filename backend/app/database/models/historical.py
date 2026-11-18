"""Immutable BTS release metadata and source-faithful historical flight rows."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database.base import Base
from backend.app.database.models.airline import Airline
from backend.app.database.models.airport import Airport


class BTSRelease(Base):
    """Checksum-identified, immutable processing release for a BTS dataset."""

    __tablename__ = "bts_releases"
    __table_args__ = (
        UniqueConstraint(
            "dataset_name",
            "reporting_period",
            "source_file_sha256",
            name="uq_bts_releases_dataset_period_checksum",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    dataset_name: Mapped[str] = mapped_column(String(120), nullable=False)
    # A monthly period is represented by its first day (for example 2024-01-01).
    reporting_period: Mapped[date] = mapped_column(Date, nullable=False)
    source_file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    processing_version: Mapped[str] = mapped_column(String(64), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending", server_default="pending"
    )
    supersedes_release_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("bts_releases.id", ondelete="RESTRICT")
    )

    supersedes: Mapped[BTSRelease | None] = relationship(
        remote_side=lambda: [BTSRelease.id],
        foreign_keys=[supersedes_release_id],
    )
    flights: Mapped[list["HistoricalBTSFlight"]] = relationship(
        back_populates="release"
    )


class HistoricalBTSFlight(Base):
    """One source-faithful historical BTS row within an immutable release."""

    __tablename__ = "historical_bts_flights"
    __table_args__ = (
        UniqueConstraint(
            "release_id",
            "row_fingerprint",
            name="uq_historical_bts_flights_release_row_fingerprint",
        ),
        Index(
            "ix_historical_bts_flights_release_date",
            "release_id",
            "flight_date",
        ),
        Index(
            "ix_historical_bts_flights_carrier_date",
            "reporting_dot_carrier_id",
            "flight_date",
        ),
        Index(
            "ix_historical_bts_flights_route_date",
            "origin_bts_code",
            "destination_bts_code",
            "flight_date",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    release_id: Mapped[UUID] = mapped_column(
        ForeignKey("bts_releases.id", ondelete="RESTRICT"), nullable=False
    )
    # SHA-256 over canonicalized source-row values; this is an ingestion key,
    # not a BTS-issued or public flight identifier.
    row_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    reporting_airline_code: Mapped[str] = mapped_column(String(3), nullable=False)
    reporting_dot_carrier_id: Mapped[int | None] = mapped_column(Integer)
    reporting_flight_number: Mapped[str | None] = mapped_column(String(16))
    flight_date: Mapped[date] = mapped_column(Date, nullable=False)

    # These are BTS DOT codes, not asserted IATA or ICAO codes.
    origin_bts_code: Mapped[str] = mapped_column(String(3), nullable=False)
    destination_bts_code: Mapped[str] = mapped_column(String(3), nullable=False)
    origin_dot_airport_id: Mapped[int | None] = mapped_column(Integer)
    destination_dot_airport_id: Mapped[int | None] = mapped_column(Integer)
    origin_dot_airport_seq_id: Mapped[int | None] = mapped_column(Integer)
    destination_dot_airport_seq_id: Mapped[int | None] = mapped_column(Integer)

    # Store source HHMM integers so local values and 2400 are preserved.
    scheduled_departure_hhmm: Mapped[int | None] = mapped_column(SmallInteger)
    actual_departure_hhmm: Mapped[int | None] = mapped_column(SmallInteger)
    scheduled_arrival_hhmm: Mapped[int | None] = mapped_column(SmallInteger)
    actual_arrival_hhmm: Mapped[int | None] = mapped_column(SmallInteger)

    departure_delay_minutes: Mapped[int | None] = mapped_column(Integer)
    arrival_delay_minutes: Mapped[int | None] = mapped_column(Integer)
    cancelled: Mapped[int | None] = mapped_column(SmallInteger)
    diverted: Mapped[int | None] = mapped_column(SmallInteger)
    cancellation_code: Mapped[str | None] = mapped_column(String(1))

    # Optional canonical references are separate from the preserved BTS IDs.
    airline_id: Mapped[str | None] = mapped_column(
        ForeignKey("airlines.code", ondelete="SET NULL")
    )
    origin_airport_id: Mapped[int | None] = mapped_column(
        ForeignKey("airports.id", ondelete="SET NULL")
    )
    destination_airport_id: Mapped[int | None] = mapped_column(
        ForeignKey("airports.id", ondelete="SET NULL")
    )

    release: Mapped[BTSRelease] = relationship(back_populates="flights")
    airline: Mapped[Airline | None] = relationship(
        "Airline", foreign_keys=[airline_id]
    )
    origin_airport: Mapped[Airport | None] = relationship(
        "Airport", foreign_keys=[origin_airport_id]
    )
    destination_airport: Mapped[Airport | None] = relationship(
        "Airport", foreign_keys=[destination_airport_id]
    )
