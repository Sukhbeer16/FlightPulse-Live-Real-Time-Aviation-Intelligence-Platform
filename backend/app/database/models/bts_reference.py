"""Versioned BTS/DOT reference identities and source provenance."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database.base import Base
from backend.app.database.models.airline import Airline
from backend.app.database.models.airport import Airport


class BTSReferenceRelease(Base):
    """Provenance envelope for one imported BTS reference-data release."""

    __tablename__ = "bts_reference_releases"
    __table_args__ = (
        UniqueConstraint(
            "source_agency",
            "dataset_name",
            "source_artifact_sha256",
            name="uq_bts_reference_releases_source_dataset_checksum",
        ),
        CheckConstraint(
            "source_artifact_sha256 ~ '^[0-9a-f]{64}$'",
            name="source_artifact_sha256_format",
        ),
        CheckConstraint(
            "status IS NULL OR status IN ('pending', 'failed', 'complete')",
            name="status_valid",
        ),
        CheckConstraint(
            """CASE
                WHEN status IS NULL THEN completed_at IS NULL
                WHEN status = 'complete' THEN completed_at IS NOT NULL
                ELSE completed_at IS NULL
            END""",
            name="completion_timestamp_matches_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source_agency: Mapped[str] = mapped_column(String(80), nullable=False)
    dataset_name: Mapped[str] = mapped_column(String(120), nullable=False)
    source_artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint_schema_version: Mapped[str | None] = mapped_column(
        String(40), nullable=True
    )
    # NULL preserves the unknown lifecycle state of releases created before
    # lifecycle tracking; new importer code must explicitly set "pending".
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_release: Mapped[str | None] = mapped_column(String(120))
    effective_date: Mapped[date | None] = mapped_column(Date)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    carriers: Mapped[list[BTSCarrierReference]] = relationship(
        back_populates="release"
    )
    airports: Mapped[list[BTSAirportReference]] = relationship(
        back_populates="release"
    )


class BTSCarrierReference(Base):
    """Carrier identity as represented by a particular BTS source release."""

    __tablename__ = "bts_carrier_references"
    __table_args__ = (
        UniqueConstraint(
            "release_id",
            "row_fingerprint",
            name="uq_bts_carrier_references_release_row_fingerprint",
        ),
        CheckConstraint(
            "row_fingerprint ~ '^[0-9a-f]{64}$'",
            name="row_fingerprint_format",
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="valid_dates",
        ),
        CheckConstraint(
            "carrier_code_namespace = 'IATA_CARRIER_CODE'",
            name="carrier_code_namespace",
        ),
        Index("ix_bts_carrier_references_dot_carrier_id", "dot_carrier_id"),
        Index("ix_bts_carrier_references_carrier_code", "carrier_code"),
        Index(
            "ix_bts_carrier_references_unique_carrier_code", "unique_carrier_code"
        ),
        Index("ix_bts_carrier_references_airline_code", "airline_code"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    release_id: Mapped[UUID] = mapped_column(
        ForeignKey("bts_reference_releases.id", ondelete="RESTRICT"),
        nullable=False,
    )
    row_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_values: Mapped[list[list[str | None]] | None] = mapped_column(
        JSONB, nullable=True
    )
    # Keep the DOT identifier's original lexical form, including leading zeroes.
    dot_carrier_id: Mapped[str] = mapped_column(Text, nullable=False)
    # Carrier is the IATA code; UniqueCarrier is a separate BTS-disambiguated code.
    carrier_code: Mapped[str | None] = mapped_column(String(8))
    carrier_code_namespace: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="IATA_CARRIER_CODE"
    )
    unique_carrier_code: Mapped[str | None] = mapped_column(String(8))
    carrier_name: Mapped[str | None] = mapped_column(String(200))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    airline_code: Mapped[str | None] = mapped_column(
        ForeignKey("airlines.code", ondelete="SET NULL")
    )

    release: Mapped[BTSReferenceRelease] = relationship(back_populates="carriers")
    airline: Mapped[Airline | None] = relationship()


class BTSAirportReference(Base):
    """Airport identity and source code in a particular BTS release."""

    __tablename__ = "bts_airport_references"
    __table_args__ = (
        UniqueConstraint(
            "release_id",
            "row_fingerprint",
            name="uq_bts_airport_references_release_row_fingerprint",
        ),
        CheckConstraint(
            "row_fingerprint ~ '^[0-9a-f]{64}$'",
            name="row_fingerprint_format",
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="valid_dates",
        ),
        CheckConstraint(
            "airport_code_namespace = 'BTS_DOT_AIRPORT_CODE'",
            name="airport_code_namespace",
        ),
        Index("ix_bts_airport_references_dot_airport_id", "dot_airport_id"),
        Index("ix_bts_airport_references_dot_airport_seq_id", "dot_airport_seq_id"),
        Index("ix_bts_airport_references_bts_airport_code", "bts_airport_code"),
        Index("ix_bts_airport_references_airport_id", "airport_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    release_id: Mapped[UUID] = mapped_column(
        ForeignKey("bts_reference_releases.id", ondelete="RESTRICT"),
        nullable=False,
    )
    row_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_values: Mapped[list[list[str | None]] | None] = mapped_column(
        JSONB, nullable=True
    )
    dot_airport_id: Mapped[str] = mapped_column(Text, nullable=False)
    dot_airport_seq_id: Mapped[str | None] = mapped_column(Text)
    bts_airport_code: Mapped[str | None] = mapped_column(String(3))
    airport_code_namespace: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="BTS_DOT_AIRPORT_CODE"
    )
    airport_name: Mapped[str | None] = mapped_column(String(200))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    airport_id: Mapped[int | None] = mapped_column(
        ForeignKey("airports.id", ondelete="SET NULL")
    )

    release: Mapped[BTSReferenceRelease] = relationship(back_populates="airports")
    airport: Mapped[Airport | None] = relationship()
