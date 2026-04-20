from __future__ import annotations

from fastapi import FastAPI, Depends, HTTPException, Request, Query
from sqlalchemy.orm import Session

from .db import SessionLocal
from .schemas import TelemetryIn
from .predictive_maintenance import get_predictive_maintenance
from .service import (
    ValidationError,
    get_latest_telemetry,
    get_telemetry_history,
    save_telemetry,
)

app = FastAPI(title="Catena-X Cobot Telemetry Server", version="1.0.0")


def get_db():
    """
    Write path: open a session, commit after the route handler succeeds.

    Used for POST /telemetry so inserts (raw, latest, measurements, audit) persist atomically.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db_read():
    """
    Read path: no commit — only rollback before close.

    Avoids issuing a COMMIT on pure SELECT endpoints (health still has no DB at all).
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/v1/cobot/telemetry")
def ingest(item: TelemetryIn, request: Request, db: Session = Depends(get_db)):
    request_id = request.headers.get("X-Request-Id")
    source_ip = request.client.host if request.client else None
    try:
        # Single ingestion pipeline: checksum, audit, duplicate-aware side effects.
        return save_telemetry(db, item=item, source_ip=source_ip, request_id=request_id)
    except ValidationError as exc:
        # Business rules beyond Pydantic (ranges, future produced_at window, etc.).
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/cobot/telemetry/latest")
def latest(robot_id: str | None = None, db: Session = Depends(get_db_read)):
    data = get_latest_telemetry(db, robot_id=robot_id)
    if robot_id:
        if not data["items"]:
            raise HTTPException(status_code=404, detail="not found")
        # Preserve previous contract: single-robot response is one object, not wrapped in {items}.
        return data["items"][0]
    return data


@app.get("/api/v1/cobot/telemetry")
def history(
    robot_id: str | None = None,
    limit: int = Query(default=20, le=1000),
    db: Session = Depends(get_db_read),
):
    return get_telemetry_history(db, robot_id=robot_id, limit=limit)


@app.get("/api/v1/cobot/predictive-maintenance")
def predictive_maintenance(
    robot_id: str | None = None,
    window_hours: int = Query(default=24, ge=1, le=24 * 30),
    db: Session = Depends(get_db_read),
):
    # Time window filter intentionally unchanged (per product decision).
    return get_predictive_maintenance(
        db,
        robot_id=robot_id,
        window_hours=window_hours,
    )
