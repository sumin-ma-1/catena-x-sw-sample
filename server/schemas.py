from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Pose(BaseModel):
    x: float
    y: float
    z: float
    rx: float
    ry: float
    rz: float


class TelemetryIn(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    robot_id: str
    line_id: str
    station_id: str
    cycle_time_ms: int
    power_watts: float
    program_name: str
    status: Literal["idle", "running", "paused", "fault", "maintenance"]
    good_parts: int | None = None
    reject_parts: int | None = None
    temperature_c: float | None = None
    vibration_mm_s: float | None = None
    pose: dict[str, Any] | None = None
    joint_positions_deg: list[float] | None = None
    alarms: list[str] | None = None
    produced_at: datetime | None = None
    schema_version: str = "1.0.0"