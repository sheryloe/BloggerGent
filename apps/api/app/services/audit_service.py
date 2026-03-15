from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.entities import AuditLog, Job, LogLevel


def add_log(
    db: Session,
    *,
    job: Job | None,
    stage: str,
    message: str,
    level: LogLevel = LogLevel.INFO,
    payload: dict | None = None,
) -> AuditLog:
    entry = AuditLog(job_id=job.id if job else None, stage=stage, message=message, level=level, payload=payload or {})
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def count_logs_since(db: Session, *, stage: str, since: datetime) -> int:
    statement = select(func.count(AuditLog.id)).where(AuditLog.stage == stage, AuditLog.created_at >= since)
    return int(db.execute(statement).scalar_one() or 0)


def get_latest_log_for_stage(db: Session, *, stage: str) -> AuditLog | None:
    statement = select(AuditLog).where(AuditLog.stage == stage).order_by(desc(AuditLog.created_at), desc(AuditLog.id)).limit(1)
    return db.execute(statement).scalar_one_or_none()
