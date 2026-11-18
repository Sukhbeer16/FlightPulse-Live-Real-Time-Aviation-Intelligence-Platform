"""Airport reference entity with an optional PostGIS point."""

from datetime import datetime

from geoalchemy2 import Geography
from sqlalchemy import DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database.base import Base


class Airport(Base):
    """Airport reference data and WGS 84 location."""

    __tablename__ = "airports"
    __table_args__ = (
        Index("ix_airports_location", "location", postgresql_using="gist"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    iata_code: Mapped[str | None] = mapped_column(String(3), unique=True)
    icao_code: Mapped[str | None] = mapped_column(String(4), unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    city: Mapped[str | None] = mapped_column(String(120))
    country_code: Mapped[str | None] = mapped_column(String(2))
    location: Mapped[object | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    origin_flights: Mapped[list["Flight"]] = relationship(
        back_populates="origin_airport", foreign_keys="Flight.origin_airport_id"
    )
    destination_flights: Mapped[list["Flight"]] = relationship(
        back_populates="destination_airport",
        foreign_keys="Flight.destination_airport_id",
    )
