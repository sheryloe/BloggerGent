from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings as app_settings
from app.db.base import Base
from app.models.entities import ManualImageSlotStatus
from app.services.content.manual_image_service import (
    create_manual_image_slot,
    format_manual_image_slot_for_chat,
    is_manual_image_channel_locked,
    list_manual_image_slots,
    resolve_manual_image_defer_for_blog,
)


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    monkeypatch.setattr(app_settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(app_settings, "settings_encryption_secret", "test-secret")
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_create_manual_image_slot_assigns_serial_and_chat_format(db: Session) -> None:
    slot = create_manual_image_slot(
        db,
        provider="blogger",
        slot_role="hero",
        prompt="Create a 4x3 realistic travel collage with exactly 12 panels, no text.",
        remote_post_id="post-123",
        metadata={
            "title": "Seoul Evening Walk",
            "published_url": "https://example.com/seoul-evening-walk",
        },
    )

    assert slot.serial_code.startswith("BGIMG-")
    assert slot.serial_code.endswith("-000001")
    assert slot.status == ManualImageSlotStatus.PENDING

    chat_text = format_manual_image_slot_for_chat(slot)
    assert slot.serial_code in chat_text
    assert "provider: blogger" in chat_text
    assert "slot: hero" in chat_text
    assert "title: Seoul Evening Walk" in chat_text
    assert "prompt:\nCreate a 4x3 realistic travel collage with exactly 12 panels, no text." in chat_text


def test_create_manual_image_slot_is_idempotent_for_pending_remote_slot(db: Session) -> None:
    first = create_manual_image_slot(
        db,
        provider="cloudflare",
        slot_role="cover",
        prompt="first prompt",
        remote_post_id="cf-post-1",
        metadata={"title": "First"},
    )
    second = create_manual_image_slot(
        db,
        provider="cloudflare",
        slot_role="cover",
        prompt="second prompt",
        remote_post_id="cf-post-1",
        metadata={"title": "Second", "published_url": "https://example.com/post"},
    )

    pending = list_manual_image_slots(db)

    assert second.id == first.id
    assert second.serial_code == first.serial_code
    assert second.prompt == "second prompt"
    assert second.slot_metadata["title"] == "Second"
    assert len(pending) == 1


def test_manual_image_lock_for_blogger_targets() -> None:
    assert resolve_manual_image_defer_for_blog(blog_id=35, requested_defer_images=False) is True
    assert resolve_manual_image_defer_for_blog(blog_id=34, requested_defer_images=False) is True
    assert resolve_manual_image_defer_for_blog(blog_id=99, requested_defer_images=False) is False
    assert resolve_manual_image_defer_for_blog(blog_id=99, requested_defer_images=True) is True


def test_manual_image_lock_for_cloudflare_channel() -> None:
    assert is_manual_image_channel_locked("cloudflare:dongriarchive") is True
    assert is_manual_image_channel_locked("CLOUDFLARE:DONGRIARCHIVE") is True
    assert is_manual_image_channel_locked("cloudflare:other") is False
