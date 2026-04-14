from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings as app_settings
from app.db.base import Base
from app.models.entities import TelegramCommandEvent, TelegramDeliveryEvent
from app.services import telegram_service
from app.services.integrations.settings_service import get_settings_map, upsert_settings


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


def test_publish_notification_dedupes_on_normalized_url(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    upsert_settings(
        db,
        {
            "telegram_bot_token": "token",
            "telegram_chat_id": "100",
        },
    )

    sent_messages: list[str] = []

    def _fake_post(*, bot_token: str, chat_id: str, text: str, reply_markup=None):  # noqa: ANN001
        sent_messages.append(text)
        return {"delivery_status": "sent", "chat_id": chat_id, "message_id": len(sent_messages)}

    monkeypatch.setattr(telegram_service, "_post_telegram_message", _fake_post)

    first = telegram_service.send_telegram_post_notification(
        db,
        blog_name="Travel",
        article_title="Busan Night Walk",
        post_url="http://dongdonggri.blogspot.com/2026/04/busan-night-walk.html?utm_source=test",
        post_status="published",
    )
    second = telegram_service.send_telegram_post_notification(
        db,
        blog_name="Travel",
        article_title="Busan Night Walk",
        post_url="https://dongdonggri.blogspot.com/2026/04/busan-night-walk.html",
        post_status="published",
    )

    events = db.query(TelegramDeliveryEvent).order_by(TelegramDeliveryEvent.id.asc()).all()

    assert first["delivery_status"] == "sent"
    assert second["delivery_status"] == "skipped"
    assert len(sent_messages) == 1
    assert len(events) == 1
    assert events[0].dedupe_key == "publish:dongdonggri.blogspot.com/2026/04/busan-night-walk.html"
    assert events[0].event_payload["raw_url"] == "http://dongdonggri.blogspot.com/2026/04/busan-night-walk.html?utm_source=test"
    assert events[0].event_payload["normalized_url"] == "dongdonggri.blogspot.com/2026/04/busan-night-walk.html"


def test_publish_notification_retries_after_failed_delivery(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    upsert_settings(
        db,
        {
            "telegram_bot_token": "token",
            "telegram_chat_id": "100",
        },
    )

    responses = [
        {"delivery_status": "failed", "chat_id": "100", "error_code": 500, "error_message": "timeout"},
        {"delivery_status": "sent", "chat_id": "100", "message_id": 2},
    ]

    def _fake_post(*, bot_token: str, chat_id: str, text: str, reply_markup=None):  # noqa: ANN001
        return responses.pop(0)

    monkeypatch.setattr(telegram_service, "_post_telegram_message", _fake_post)

    first = telegram_service.send_telegram_post_notification(
        db,
        blog_name="Travel",
        article_title="Retry Test",
        post_url="https://dongdonggri.blogspot.com/2026/04/retry-test.html",
        post_status="published",
    )
    second = telegram_service.send_telegram_post_notification(
        db,
        blog_name="Travel",
        article_title="Retry Test",
        post_url="https://dongdonggri.blogspot.com/2026/04/retry-test.html",
        post_status="published",
    )

    events = db.query(TelegramDeliveryEvent).order_by(TelegramDeliveryEvent.id.asc()).all()

    assert first["delivery_status"] == "failed"
    assert second["delivery_status"] == "sent"
    assert len(events) == 2
    assert events[0].status == "failed"
    assert events[1].status == "sent"


def test_normalize_telegram_publish_url_sorts_query_and_strips_default_port() -> None:
    normalized = telegram_service.normalize_telegram_publish_url(
        "https://DongDongGri.Blogspot.com:443/2026/04/reorder-test.html?b=2&a=1&utm_source=test"
    )

    assert normalized == "dongdonggri.blogspot.com/2026/04/reorder-test.html?a=1&b=2"


def test_upsert_settings_keeps_openai_usage_hard_cap_enabled_true(db: Session) -> None:
    upsert_settings(
        db,
        {
            "openai_usage_hard_cap_enabled": "false",
        },
    )

    values = get_settings_map(db)

    assert values["openai_usage_hard_cap_enabled"] == "true"
