from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings as app_settings
from app.db.base import Base
from app.models.entities import ContentItem
from app.services import metric_ingestion_service
from app.services.platform.platform_service import ensure_managed_channels, get_managed_channel_by_channel_id
from app.services.integrations.settings_service import get_settings_map, upsert_settings


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    monkeypatch.setattr(app_settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(app_settings, "settings_encryption_secret", "test-secret")

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


def test_apply_last_scores_normalizes_legacy_keys(db: Session) -> None:
    ensure_managed_channels(db)
    channel = get_managed_channel_by_channel_id(db, "youtube:main")
    assert channel is not None

    item = ContentItem(
        managed_channel_id=channel.id,
        blog_id=None,
        content_type="youtube_video",
        lifecycle_status="draft",
        title="sample",
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    updated = metric_ingestion_service._apply_last_scores(  # noqa: SLF001
        db,
        scores={
            item.id: {
                "ctr": 34.5,
                "watch_quality": 61.2,
                "traffic": 20.0,
            }
        },
    )
    assert updated == 1
    refreshed = db.get(ContentItem, item.id)
    assert refreshed is not None
    assert refreshed.last_score["seo_ctr"] == 34.5
    assert refreshed.last_score["watch_quality"] == 61.2
    assert refreshed.last_score["traffic_quality"] == 20.0
    assert refreshed.last_score["composite"] == round((34.5 + 61.2 + 20.0) / 3, 2)


def test_sync_channel_metrics_dispatches_to_youtube(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_managed_channels(db)
    called: dict[str, object] = {}

    def fake_sync(_db: Session, *, channel_id: str, days: int) -> dict:
        called["channel_id"] = channel_id
        called["days"] = days
        return {"status": "ok", "channel_id": channel_id, "provider": "youtube"}

    monkeypatch.setattr(metric_ingestion_service, "sync_youtube_channel_metrics", fake_sync)
    result = metric_ingestion_service.sync_channel_metrics(db, channel_id="youtube:main", days=14, refresh_indexing=False)
    assert result["provider"] == "youtube"
    assert called == {"channel_id": "youtube:main", "days": 14}


def test_run_workspace_metric_sync_schedule_includes_youtube_and_instagram(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_managed_channels(db)
    upsert_settings(
        db,
        {
            "workspace_metrics_sync_enabled": "true",
            "workspace_metrics_sync_interval_hours": "6",
            "workspace_metrics_lookback_days": "14",
        },
    )

    called_channel_ids: list[str] = []

    def fake_sync(_db: Session, *, channel_id: str, days: int, refresh_indexing: bool) -> dict:
        called_channel_ids.append(channel_id)
        return {
            "status": "ok",
            "channel_id": channel_id,
            "provider": channel_id.split(":", maxsplit=1)[0],
            "days": days,
            "refresh_indexing": refresh_indexing,
        }

    monkeypatch.setattr(metric_ingestion_service, "sync_channel_metrics", fake_sync)
    result = metric_ingestion_service.run_workspace_metric_sync_schedule(db, force=True)

    assert set(called_channel_ids) == {"youtube:main", "instagram:main"}
    assert result["processed_count"] == 2
    assert result["failed_count"] == 0
