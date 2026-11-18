"""Airline reference entity."""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database.base import Base


class Airline(Base):
    """Carrier reference data keyed by its source carrier code."""

    __tablename__ = "airlines"

    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    flights: Mapped[list["Flight"]] = relationship(back_populates="airline")
