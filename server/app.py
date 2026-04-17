from __future__ import annotations

from fastapi import FastAPI, Depends, HTTPException, Request, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from .db import SessionLocal
from .schemas import TelemetryIn
from .repository import upsert_telemetry
from .predictive_maintenance import get_predictive_maintenance

app = FastAPI(title="Catena-X Cobot Telemetry Server", version="1.0.0")


def get_db():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/v1/cobot/telemetry")
def ingest(item: TelemetryIn, request: Request, db: Session = Depends(get_db)):
    request_id = request.headers.get("X-Request-Id")
    source_ip = request.client.host if request.client else None
    upsert_telemetry(db, item, source_ip=source_ip, request_id=request_id)
    return {"accepted": True, "event_id": str(item.event_id)}


@app.get("/api/v1/cobot/telemetry/latest")
def latest(robot_id: str | None = None, db: Session = Depends(get_db)):
    if robot_id:
        row = db.execute(
            text("SELECT robot_id, produced_at, payload FROM cobot_telemetry_latest WHERE robot_id=:robot_id"),
            {"robot_id": robot_id}
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="not found")
        return dict(row)

    rows = db.execute(
        text("SELECT robot_id, produced_at, payload FROM cobot_telemetry_latest ORDER BY updated_at DESC LIMIT 100")
    ).mappings().all()
    return {"items": [dict(x) for x in rows]}


@app.get("/api/v1/cobot/telemetry")
def history(
    robot_id: str | None = None,
    limit: int = Query(default=20, le=1000),
    db: Session = Depends(get_db)
):
    if robot_id:
        rows = db.execute(
            text("""
                SELECT event_id, robot_id, produced_at, payload
                FROM cobot_telemetry_raw
                WHERE robot_id=:robot_id
                ORDER BY produced_at DESC
                LIMIT :limit
            """),
            {"robot_id": robot_id, "limit": limit}
        ).mappings().all()
    else:
        rows = db.execute(
            text("""
                SELECT event_id, robot_id, produced_at, payload
                FROM cobot_telemetry_raw
                ORDER BY produced_at DESC
                LIMIT :limit
            """),
            {"limit": limit}
        ).mappings().all()

    return {"items": [dict(x) for x in rows]}


@app.get("/api/v1/cobot/predictive-maintenance")
def predictive_maintenance(
    robot_id: str | None = None,
    window_hours: int = Query(default=24, ge=1, le=24 * 30),
    db: Session = Depends(get_db),
):
    return get_predictive_maintenance(
        db,
        robot_id=robot_id,
        window_hours=window_hours,
    )