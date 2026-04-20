from __future__ import annotations

"""
Telemetry domain service: validation, persistence, audit trail, and AAS sync queue.

`server.app` should call `save_telemetry` for HTTP ingestion so behavior stays aligned
with DB tables (`checksum_sha256`, `cobot_access_audit`, `cobot_aas_sync_status`).
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from .schemas import TelemetryIn


ALLOWED_STATUS = {"idle", "running", "paused", "fault", "maintenance"}


class ValidationError(Exception):
    pass


def _normalize_payload(item: TelemetryIn) -> dict[str, Any]:
    payload = item.model_dump(mode="json")

    if not payload.get("produced_at"):
        payload["produced_at"] = datetime.now(timezone.utc).isoformat()

    return payload


def _checksum(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_telemetry(item: TelemetryIn) -> None:
    if item.cycle_time_ms < 0:
        raise ValidationError("cycle_time_ms must be >= 0")

    if item.power_watts < 0:
        raise ValidationError("power_watts must be >= 0")

    if item.good_parts is not None and item.good_parts < 0:
        raise ValidationError("good_parts must be >= 0")

    if item.reject_parts is not None and item.reject_parts < 0:
        raise ValidationError("reject_parts must be >= 0")

    if item.temperature_c is not None and item.temperature_c < -100:
        raise ValidationError("temperature_c looks invalid")

    if item.vibration_mm_s is not None and item.vibration_mm_s < 0:
        raise ValidationError("vibration_mm_s must be >= 0")

    if item.status not in ALLOWED_STATUS:
        raise ValidationError(f"status must be one of {sorted(ALLOWED_STATUS)}")

    if item.produced_at is not None:
        now = datetime.now(timezone.utc)
        produced_at = item.produced_at

        if produced_at.tzinfo is None:
            produced_at = produced_at.replace(tzinfo=timezone.utc)

        # 미래 시각 허용 오차 5분
        if produced_at > now.replace(microsecond=0) and (produced_at - now).total_seconds() > 300:
            raise ValidationError("produced_at is too far in the future")


def record_audit(
    db: Session,
    *,
    actor_type: str,
    actor_id: str | None,
    action: str,
    target_resource: str,
    result: str,
    correlation_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    sql = text("""
        INSERT INTO cobot_access_audit (
            actor_type, actor_id, action, target_resource, result, correlation_id, details
        )
        VALUES (
            :actor_type, :actor_id, :action, :target_resource, :result, :correlation_id, CAST(:details AS jsonb)
        )
    """)

    db.execute(
        sql,
        {
            "actor_type": actor_type,
            "actor_id": actor_id,
            "action": action,
            "target_resource": target_resource,
            "result": result,
            "correlation_id": correlation_id,
            "details": json.dumps(details or {}, ensure_ascii=False),
        },
    )


def save_telemetry(
    db: Session,
    *,
    item: TelemetryIn,
    source_ip: str | None,
    request_id: str | None,
) -> dict[str, Any]:
    validate_telemetry(item)

    payload = _normalize_payload(item)
    produced_at = item.produced_at or datetime.now(timezone.utc)
    checksum = _checksum(payload)

    raw_sql = text("""
        INSERT INTO cobot_telemetry_raw (
            event_id, robot_id, line_id, station_id, produced_at,
            payload, schema_version, source_ip, content_type, request_id, checksum_sha256
        )
        VALUES (
            :event_id, :robot_id, :line_id, :station_id, :produced_at,
            CAST(:payload AS jsonb), :schema_version, :source_ip, 'application/json', :request_id, :checksum_sha256
        )
        ON CONFLICT (event_id) DO NOTHING
        RETURNING event_id
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

    sync_sql = text("""
        INSERT INTO cobot_aas_sync_status (
            event_id, robot_id, sync_status, retry_count, updated_at
        )
        VALUES (
            :event_id, :robot_id, 'PENDING', 0, NOW()
        )
        ON CONFLICT (event_id)
        DO NOTHING
    """)

    params = {
        "event_id": str(item.event_id),
        "robot_id": item.robot_id,
        "line_id": item.line_id,
        "station_id": item.station_id,
        "produced_at": produced_at,
        "payload": json.dumps(payload, ensure_ascii=False),
        "schema_version": item.schema_version,
        "source_ip": source_ip,
        "request_id": request_id,
        "checksum_sha256": checksum,
        "cycle_time_ms": item.cycle_time_ms,
        "power_watts": item.power_watts,
        "program_name": item.program_name,
        "status": item.status,
        "good_parts": item.good_parts,
        "reject_parts": item.reject_parts,
        "temperature_c": item.temperature_c,
        "vibration_mm_s": item.vibration_mm_s,
    }

    inserted = db.execute(raw_sql, params).scalar_one_or_none()
    is_duplicate = inserted is None

    if not is_duplicate:
        db.execute(latest_sql, params)
        db.execute(meas_sql, params)
        db.execute(sync_sql, params)

    record_audit(
        db,
        actor_type="service",
        actor_id="telemetry-api",
        action="ingest_telemetry",
        target_resource=f"robot:{item.robot_id}",
        result="success",
        correlation_id=request_id,
        details={
            "event_id": str(item.event_id),
            "duplicate": is_duplicate,
            "source_ip": source_ip,
        },
    )

    return {
        "accepted": True,
        "event_id": str(item.event_id),
        "duplicate": is_duplicate,
    }


def mark_aas_sync_success(db: Session, *, event_id: str, robot_id: str) -> None:
    sql = text("""
        INSERT INTO cobot_aas_sync_status (
            event_id, robot_id, sync_status, synced_at, retry_count, updated_at
        )
        VALUES (
            :event_id, :robot_id, 'SUCCESS', NOW(), 0, NOW()
        )
        ON CONFLICT (event_id)
        DO UPDATE SET
            sync_status = 'SUCCESS',
            synced_at = NOW(),
            last_error = NULL,
            updated_at = NOW()
    """)
    db.execute(sql, {"event_id": event_id, "robot_id": robot_id})


def mark_aas_sync_failed(db: Session, *, event_id: str, robot_id: str, error: str) -> None:
    sql = text("""
        INSERT INTO cobot_aas_sync_status (
            event_id, robot_id, sync_status, last_error, retry_count, updated_at
        )
        VALUES (
            :event_id, :robot_id, 'FAILED', :last_error, 1, NOW()
        )
        ON CONFLICT (event_id)
        DO UPDATE SET
            sync_status = 'FAILED',
            last_error = :last_error,
            retry_count = cobot_aas_sync_status.retry_count + 1,
            updated_at = NOW()
    """)
    db.execute(sql, {"event_id": event_id, "robot_id": robot_id, "last_error": error})


def get_latest_telemetry(db: Session, robot_id: str | None = None) -> dict[str, Any]:
    if robot_id:
        row = db.execute(
            text("""
                SELECT robot_id, line_id, station_id, produced_at, payload, updated_at
                FROM cobot_telemetry_latest
                WHERE robot_id = :robot_id
            """),
            {"robot_id": robot_id},
        ).mappings().first()

        if not row:
            return {"items": []}

        return {"items": [dict(row)]}

    rows = db.execute(
        text("""
            SELECT robot_id, line_id, station_id, produced_at, payload, updated_at
            FROM cobot_telemetry_latest
            ORDER BY updated_at DESC
            LIMIT 100
        """)
    ).mappings().all()

    return {"items": [dict(r) for r in rows]}


def get_telemetry_history(
    db: Session,
    *,
    robot_id: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    if robot_id:
        rows = db.execute(
            text("""
                SELECT event_id, robot_id, line_id, station_id, produced_at, payload, received_at
                FROM cobot_telemetry_raw
                WHERE robot_id = :robot_id
                ORDER BY produced_at DESC
                LIMIT :limit
            """),
            {"robot_id": robot_id, "limit": limit},
        ).mappings().all()
    else:
        rows = db.execute(
            text("""
                SELECT event_id, robot_id, line_id, station_id, produced_at, payload, received_at
                FROM cobot_telemetry_raw
                ORDER BY produced_at DESC
                LIMIT :limit
            """),
            {"limit": limit},
        ).mappings().all()

    return {"items": [dict(r) for r in rows]}