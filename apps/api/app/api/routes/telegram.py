from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.api import TelegramTestRead, TelegramTestRequest
from app.services.telegram_service import send_telegram_test_message

router = APIRouter()


@router.post("/test", response_model=TelegramTestRead)
def post_telegram_test(payload: TelegramTestRequest, db: Session = Depends(get_db)) -> dict:
    return send_telegram_test_message(db, message=payload.message)
