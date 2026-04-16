from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CobotTelemetryRaw(Base):
    __tablename__ = "cobot_telemetry_raw"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid4)

    robot_id: Mapped[str] = mapped_column(String(100), nullable=False)
    line_id: Mapped[str] = mapped_column(String(100), nullable=False)
    station_id: Mapped[str] = mapped_column(String(100), nullable=False)

    produced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    source_ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("idx_raw_robot_time", "robot_id", "produced_at"),
    )


class CobotTelemetryLatest(Base):
    __tablename__ = "cobot_telemetry_latest"

    robot_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    line_id: Mapped[str] = mapped_column(String(100), nullable=False)
    station_id: Mapped[str] = mapped_column(String(100), nullable=False)

    produced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CobotMeasurement(Base):
    __tablename__ = "cobot_measurements"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cobot_telemetry_raw.event_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    robot_id: Mapped[str] = mapped_column(String(100), nullable=False)
    line_id: Mapped[str] = mapped_column(String(100), nullable=False)
    station_id: Mapped[str] = mapped_column(String(100), nullable=False)
    produced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    cycle_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    power_watts: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    program_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)

    good_parts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reject_parts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    temperature_c: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    vibration_mm_s: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)

    __table_args__ = (
        Index("idx_meas_robot_time", "robot_id", "produced_at"),
    )


class CobotAasSyncStatus(Base):
    __tablename__ = "cobot_aas_sync_status"

    event_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cobot_telemetry_raw.event_id", ondelete="CASCADE"),
        primary_key=True,
    )
    robot_id: Mapped[str] = mapped_column(String(100), nullable=False)
    sync_status: Mapped[str] = mapped_column(String(20), nullable=False)  # PENDING/SUCCESS/FAILED
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CobotAccessAudit(Base):
    __tablename__ = "cobot_access_audit"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    actor_type: Mapped[str] = mapped_column(String(30), nullable=False)  # human/service/partner
    actor_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_resource: Mapped[str] = mapped_column(String(200), nullable=False)
    result: Mapped[str] = mapped_column(String(20), nullable=False)  # success/denied/failed

    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("idx_audit_event_time", "event_time"),
        Index("idx_audit_action_result", "action", "result"),
    )