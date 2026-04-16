from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.orm import Session

from .schemas import TelemetryIn


def upsert_telemetry(db: Session, item: TelemetryIn, source_ip: str | None, request_id: str | None) -> None:
    produced_at = item.produced_at or datetime.now(timezone.utc)

    raw_sql = text("""
        INSERT INTO cobot_telemetry_raw (
            event_id, robot_id, line_id, station_id, produced_at,
            payload, schema_version, source_ip, content_type, request_id
        )
        VALUES (
            :event_id, :robot_id, :line_id, :station_id, :produced_at,
            CAST(:payload AS jsonb), :schema_version, :source_ip, 'application/json', :request_id
        )
        ON CONFLICT (event_id) DO NOTHING
    """)

    latest_sql = text("""
        INSERT INTO cobot_telemetry_latest (
            robot_id, line_id, station_id, produced_at, payload, updated_at
        )
        VALUES (
            :robot_id, :line_id, :station_id, :produced_at, CAST(:payload AS jsonb), NOW()
        )
        ON CONFLICT (robot_id)
        DO UPDATE SET
            line_id = EXCLUDED.line_id,
            station_id = EXCLUDED.station_id,
            produced_at = EXCLUDED.produced_at,
            payload = EXCLUDED.payload,
            updated_at = NOW()
        WHERE cobot_telemetry_latest.produced_at <= EXCLUDED.produced_at
    """)

    meas_sql = text("""
        INSERT INTO cobot_measurements (
            event_id, robot_id, line_id, station_id, produced_at,
            cycle_time_ms, power_watts, program_name, status,
            good_parts, reject_parts, temperature_c, vibration_mm_s
        )
        VALUES (
            :event_id, :robot_id, :line_id, :station_id, :produced_at,
            :cycle_time_ms, :power_watts, :program_name, :status,
            :good_parts, :reject_parts, :temperature_c, :vibration_mm_s
        )
        ON CONFLICT (event_id) DO NOTHING
    """)

    params = {
        "event_id": str(item.event_id),
        "robot_id": item.robot_id,
        "line_id": item.line_id,
        "station_id": item.station_id,
        "produced_at": produced_at,
        "payload": item.model_dump_json(),
        "schema_version": item.schema_version,
        "source_ip": source_ip,
        "request_id": request_id,
        "cycle_time_ms": item.cycle_time_ms,
        "power_watts": item.power_watts,
        "program_name": item.program_name,
        "status": item.status,
        "good_parts": item.good_parts,
        "reject_parts": item.reject_parts,
        "temperature_c": item.temperature_c,
        "vibration_mm_s": item.vibration_mm_s,
    }

    db.execute(raw_sql, params)
    db.execute(latest_sql, params)
    db.execute(meas_sql, params)