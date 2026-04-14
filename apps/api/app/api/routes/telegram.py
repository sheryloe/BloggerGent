from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps.admin_auth import require_admin_auth
from app.db.session import get_db
from app.schemas.api import (
    TelegramPollNowRead,
    TelegramSubscriptionsRead,
    TelegramSubscriptionsUpdate,
    TelegramTelemetryRead,
    TelegramTestRead,
    TelegramTestRequest,
)
from app.services.integrations.telegram_service import (
    get_telegram_telemetry,
    list_telegram_subscriptions,
    poll_telegram_ops_commands,
    send_telegram_test_message,
    update_telegram_subscriptions,
)

router = APIRouter(dependencies=[Depends(require_admin_auth)])


@router.post("/test", response_model=TelegramTestRead)
def post_telegram_test(payload: TelegramTestRequest, db: Session = Depends(get_db)) -> dict:
    return send_telegram_test_message(db, message=payload.message)


@router.post("/poll-now", response_model=TelegramPollNowRead)
def post_telegram_poll_now(db: Session = Depends(get_db)) -> dict:
    return poll_telegram_ops_commands(db)


@router.get("/subscriptions", response_model=TelegramSubscriptionsRead)
def get_telegram_subscriptions(
    chat_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return list_telegram_subscriptions(db, chat_id=chat_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/subscriptions", response_model=TelegramSubscriptionsRead)
def put_telegram_subscriptions(
    payload: TelegramSubscriptionsUpdate,
    db: Session = Depends(get_db),
) -> dict:
    try:
        return update_telegram_subscriptions(db, chat_id=payload.chat_id, subscriptions=payload.subscriptions)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/telemetry", response_model=TelegramTelemetryRead)
def get_telegram_telemetry_route(
    days: int = Query(default=7, ge=1, le=30),
    db: Session = Depends(get_db),
) -> dict:
    return get_telegram_telemetry(db, days=days)
