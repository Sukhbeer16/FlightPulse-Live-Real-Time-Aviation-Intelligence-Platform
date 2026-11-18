"""Scheduled and observed flight occurrence entity."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database.base import Base


class Flight(Base):
    """Source-backed flight occurrence; timestamps are stored in UTC."""

    __tablename__ = "flights"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "source_flight_id",
            name="uq_flights_source_source_flight_id",
        ),
        Index(
            "ix_flights_flight_number",
            "flight_number",
            postgresql_where=text("flight_number IS NOT NULL"),
        ),
        Index(
            "ix_flights_callsign",
            "callsign",
            postgresql_where=text("callsign IS NOT NULL"),
        ),
        Index(
            "ix_flights_airline_code",
            "airline_code",
            postgresql_where=text("airline_code IS NOT NULL"),
        ),
        Index("ix_flights_scheduled_departure_at", "scheduled_departure_at"),
        Index(
            "ix_flights_origin_destination_departure",
            "origin_airport_id",
            "destination_airport_id",
            "scheduled_departure_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    source_flight_id: Mapped[str | None] = mapped_column(String(160))
    flight_number: Mapped[str | None] = mapped_column(String(20))
    callsign: Mapped[str | None] = mapped_column(String(16))
    airline_code: Mapped[str | None] = mapped_column(
        ForeignKey("airlines.code", ondelete="SET NULL")
    )
    origin_airport_id: Mapped[int | None] = mapped_column(
        ForeignKey("airports.id", ondelete="SET NULL")
    )
    destination_airport_id: Mapped[int | None] = mapped_column(
        ForeignKey("airports.id", ondelete="SET NULL")
    )
    scheduled_departure_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    scheduled_arrival_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    actual_departure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    actual_arrival_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    status: Mapped[str | None] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    airline: Mapped["Airline | None"] = relationship(back_populates="flights")
    origin_airport: Mapped["Airport | None"] = relationship(
        back_populates="origin_flights", foreign_keys=[origin_airport_id]
    )
    destination_airport: Mapped["Airport | None"] = relationship(
        back_populates="destination_flights",
        foreign_keys=[destination_airport_id],
    )
