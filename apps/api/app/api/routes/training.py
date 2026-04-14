from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.api import (
    TrainingControlPayload,
    TrainingScheduleUpdate,
    TrainingStatusRead,
)
from app.services.content.training_service import (
    TrainingServiceError,
    request_pause_run,
    resume_training_run,
    serialize_training_status,
    start_training_run,
    update_training_schedule,
)
from app.tasks.training import run_training_session

router = APIRouter()


def _raise_http(exc: TrainingServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/status", response_model=TrainingStatusRead)
def get_training_status(db: Session = Depends(get_db)) -> dict:
    return serialize_training_status(db)


@router.post("/start", response_model=TrainingStatusRead)
def start_training(payload: TrainingControlPayload, db: Session = Depends(get_db)) -> dict:
    try:
        run = start_training_run(
            db,
            session_hours=payload.session_hours,
            save_every_minutes=payload.save_every_minutes,
            trigger_source="manual",
        )
    except TrainingServiceError as exc:
        _raise_http(exc)
    run_training_session.apply_async(args=[run.id], queue="training")
    return serialize_training_status(db)


@router.post("/pause", response_model=TrainingStatusRead)
def pause_training(db: Session = Depends(get_db)) -> dict:
    try:
        request_pause_run(db)
    except TrainingServiceError as exc:
        _raise_http(exc)
    return serialize_training_status(db)


@router.post("/resume", response_model=TrainingStatusRead)
def resume_training(payload: TrainingControlPayload, db: Session = Depends(get_db)) -> dict:
    try:
        run = resume_training_run(
            db,
            session_hours=payload.session_hours,
            save_every_minutes=payload.save_every_minutes,
        )
    except TrainingServiceError as exc:
        _raise_http(exc)
    run_training_session.apply_async(args=[run.id], queue="training")
    return serialize_training_status(db)


@router.put("/schedule", response_model=TrainingStatusRead)
def save_schedule(payload: TrainingScheduleUpdate, db: Session = Depends(get_db)) -> dict:
    try:
        update_training_schedule(
            db,
            enabled=payload.enabled,
            time=payload.time,
            timezone_name=payload.timezone,
        )
    except TrainingServiceError as exc:
        _raise_http(exc)
    return serialize_training_status(db)

