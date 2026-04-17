from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def _risk_level(score: float) -> str:
    if score >= 70:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


def _clamp(value: float, min_value: float = 0.0, max_value: float = 100.0) -> float:
    return max(min_value, min(max_value, value))


def get_predictive_maintenance(
    db: Session,
    *,
    robot_id: str | None = None,
    window_hours: int = 24,
) -> dict:
    sql = text(
        """
        SELECT
            robot_id,
            COUNT(*) AS sample_count,
            MAX(produced_at) AS last_seen_at,
            AVG(temperature_c) AS avg_temperature_c,
            AVG(vibration_mm_s) AS avg_vibration_mm_s,
            AVG(CASE WHEN status = 'fault' THEN 1.0 ELSE 0.0 END) AS fault_ratio
        FROM cobot_measurements
        WHERE produced_at >= NOW() - (:window_hours * INTERVAL '1 hour')
          AND (:robot_id IS NULL OR robot_id = :robot_id)
        GROUP BY robot_id
        ORDER BY robot_id
        """
    )

    rows = db.execute(sql, {"robot_id": robot_id, "window_hours": window_hours}).mappings().all()

    items: list[dict] = []
    for row in rows:
        avg_temp = float(row["avg_temperature_c"] or 0.0)
        avg_vib = float(row["avg_vibration_mm_s"] or 0.0)
        fault_ratio = float(row["fault_ratio"] or 0.0)

        # Simple baseline scoring for predictive maintenance.
        risk_score = _clamp(
            ((avg_temp - 45.0) * 1.5)
            + ((avg_vib - 1.2) * 30.0)
            + (fault_ratio * 100.0 * 0.5)
            + 25.0
        )

        items.append(
            {
                "robot_id": row["robot_id"],
                "window_hours": window_hours,
                "sample_count": int(row["sample_count"] or 0),
                "last_seen_at": row["last_seen_at"],
                "risk_score": round(risk_score, 2),
                "risk_level": _risk_level(risk_score),
                "avg_temperature_c": round(avg_temp, 3),
                "avg_vibration_mm_s": round(avg_vib, 3),
                "fault_ratio": round(fault_ratio, 5),
                "recommended_action": (
                    "Inspect motor/bearing and schedule preventive maintenance"
                    if risk_score >= 70
                    else "Continue monitoring"
                ),
            }
        )

    return {
        "window_hours": window_hours,
        "items": items,
        "notes": [
            "This endpoint implements predictive maintenance only.",
            "Risk score is a heuristic baseline and should be calibrated on real failure history.",
        ],
    }
