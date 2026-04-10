from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings as app_settings
from app.db.base import Base
from app.models.entities import TelegramCommandEvent, TelegramDeliveryEvent
from app.services import telegram_service
from app.services.settings_service import get_settings_map, upsert_settings


@pytest.fixture()
def db(tmp_path, monkeypatch) -> Session:
    monkeypatch.setattr(app_settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(app_settings, "settings_encryption_secret", "test-secret")

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)

    session = SessionLocal()
    get_settings_map(session)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_poll_telegram_help_command_updates_offset(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    upsert_settings(
        db,
        {
            "telegram_bot_token": "token",
            "telegram_chat_id": "100",
            "automation_telegram_enabled": "true",
        },
    )

    monkeypatch.setattr(
        telegram_service,
        "_get_telegram_updates",
        lambda **_kwargs: [
            {
                "update_id": 1,
                "message": {
                    "text": "/help",
                    "chat": {"id": "100"},
                    "from": {"id": "u1", "username": "ops"},
                },
            }
        ],
    )

    sent_messages: list[str] = []

    def _fake_post(*, bot_token: str, chat_id: str, text: str, reply_markup=None):  # noqa: ANN001
        sent_messages.append(text)
        return {"delivery_status": "sent", "chat_id": chat_id, "message_id": 10}

    monkeypatch.setattr(telegram_service, "_post_telegram_message", _fake_post)

    result = telegram_service.poll_telegram_ops_commands(db)
    values = get_settings_map(db)

    assert result["status"] == "ok"
    assert result["processed"] == 1
    assert "Bloggent 도움말 토픽" in sent_messages[0]
    assert values["content_ops_telegram_update_offset"] == "2"


def test_poll_telegram_rejects_unauthorized_chat(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    upsert_settings(
        db,
        {
            "telegram_bot_token": "token",
            "telegram_chat_id": "100",
        },
    )
    monkeypatch.setattr(
        telegram_service,
        "_get_telegram_updates",
        lambda **_kwargs: [
            {
                "update_id": 2,
                "message": {
                    "text": "/help ops",
                    "chat": {"id": "999"},
                    "from": {"id": "u2", "username": "intruder"},
                },
            }
        ],
    )
    monkeypatch.setattr(
        telegram_service,
        "_post_telegram_message",
        lambda **_kwargs: {"delivery_status": "sent", "chat_id": "999", "message_id": 1},
    )

    result = telegram_service.poll_telegram_ops_commands(db)
    event = db.query(TelegramCommandEvent).order_by(TelegramCommandEvent.id.desc()).first()

    assert result["ignored"] == 1
    assert event is not None
    assert event.status == "unauthorized"


def test_update_and_list_telegram_subscriptions(db: Session) -> None:
    upsert_settings(
        db,
        {
            "telegram_bot_token": "token",
            "telegram_chat_id": "100",
        },
    )

    updated = telegram_service.update_telegram_subscriptions(
        db,
        chat_id="100",
        subscriptions={"ops_queue": False, "custom_event": True},
    )
    listed = telegram_service.list_telegram_subscriptions(db, chat_id="100")

    assert updated["subscriptions"]["ops_queue"] is False
    assert updated["subscriptions"]["custom_event"] is True
    assert listed["subscriptions"]["ops_status"] is True
    assert listed["subscriptions"]["custom_event"] is True


def test_get_telegram_telemetry_aggregates_events(db: Session) -> None:
    now = datetime.now(timezone.utc)
    db.add(
        TelegramCommandEvent(
            chat_id="100",
            user_id="u1",
            username="ops",
            command="/help",
            status="ok",
            detail=None,
            event_payload={},
            created_at=now,
        )
    )
    db.add(
        TelegramCommandEvent(
            chat_id="100",
            user_id="u1",
            username="ops",
            command="/ops queue",
            status="error",
            detail="failure",
            event_payload={},
            created_at=now,
        )
    )
    db.add(
        TelegramDeliveryEvent(
            chat_id="100",
            message_type="command_reply",
            dedupe_key=None,
            status="sent",
            error_code=None,
            error_message=None,
            event_payload={},
            created_at=now,
            delivered_at=now,
        )
    )
    db.add(
        TelegramDeliveryEvent(
            chat_id="100",
            message_type="command_reply",
            dedupe_key=None,
            status="failed",
            error_code=400,
            error_message="bad request",
            event_payload={},
            created_at=now,
            delivered_at=None,
        )
    )
    db.commit()

    payload = telegram_service.get_telegram_telemetry(db, days=7)

    assert payload["command_events"] == 2
    assert payload["command_success"] == 1
    assert payload["command_failed"] == 1
    assert payload["deliveries_sent"] == 1
    assert payload["deliveries_failed"] == 1
    assert len(payload["top_commands"]) == 2
