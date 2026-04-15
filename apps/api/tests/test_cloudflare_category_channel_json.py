from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings as app_settings
from app.db.base import Base
from app.services import channel_prompt_service
from app.services.integrations.settings_service import get_settings_map


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    monkeypatch.setattr(app_settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(app_settings, "settings_encryption_secret", "test-secret")
    monkeypatch.setattr(channel_prompt_service, "_prompt_root", lambda: tmp_path / "prompts")
    (tmp_path / "prompts").mkdir(parents=True, exist_ok=True)

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    session = SessionLocal()
    get_settings_map(session)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_cloudflare_category_channel_json_uses_english_keys_and_korean_values(
    db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        channel_prompt_service,
        "get_cloudflare_overview",
        lambda _db: {"channel_name": "동그리 아카이브", "site_title": "동그리 아카이브"},
    )
    monkeypatch.setattr(
        channel_prompt_service,
        "get_cloudflare_prompt_bundle",
        lambda _db: {
            "stages": ["topic_discovery", "article_generation", "image_prompt_generation"],
            "categories": [{"slug": "여행과-기록", "name": "여행과 기록"}],
            "templates": [
                {
                    "id": "travel-topic",
                    "categorySlug": "여행과-기록",
                    "categoryName": "여행과 기록",
                    "stage": "topic_discovery",
                    "name": "여행과 기록 | 주제 발굴",
                    "objective": "실제 장소와 동선 중심 주제를 찾습니다.",
                    "content": "Travel discovery prompt",
                    "providerModel": "gpt-5.4",
                    "isEnabled": True,
                },
                {
                    "id": "travel-article",
                    "categorySlug": "여행과-기록",
                    "categoryName": "여행과 기록",
                    "stage": "article_generation",
                    "name": "여행과 기록 | 본문 작성",
                    "objective": "실제 장소와 동선 중심 본문을 씁니다.",
                    "content": "Travel article prompt",
                    "providerModel": "gpt-5.4",
                    "isEnabled": True,
                },
                {
                    "id": "travel-image",
                    "categorySlug": "여행과-기록",
                    "categoryName": "여행과 기록",
                    "stage": "image_prompt_generation",
                    "name": "여행과 기록 | 이미지 프롬프트",
                    "objective": "실제 장소 분위기에 맞는 이미지 프롬프트를 만듭니다.",
                    "content": "Travel image prompt",
                    "providerModel": "gpt-5.4",
                    "isEnabled": True,
                },
            ],
        },
    )

    channel_prompt_service.build_prompt_flow(db, "cloudflare:dongriarchive", sync_backup=True)

    path = (
        tmp_path
        / "prompts"
        / "channels"
        / "cloudflare"
        / "dongri-archive"
        / "동그리의 기록"
        / "yeohaenggwa-girog"
        / "channel.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["channel_id"] == "cloudflare:dongriarchive::여행과-기록"
    assert payload["root_channel_id"] == "cloudflare:dongriarchive"
    assert payload["channel_name"] == "동그리 아카이브 | 동그리의 기록 | 여행과 기록"
    assert payload["provider"] == "cloudflare"
    assert payload["backup_directory"] == "channels/cloudflare/dongri-archive/동그리의 기록/yeohaenggwa-girog"
    assert all(key in payload for key in ("channel_id", "root_channel_id", "channel_name", "provider", "backup_directory", "backup_files", "steps"))
    assert payload["steps"][0]["stage_label"] == "주제 발굴"
    assert payload["steps"][0]["name"] == "여행과 기록 | 주제 발굴"
