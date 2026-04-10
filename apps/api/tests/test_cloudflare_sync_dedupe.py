from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings as app_settings
from app.db.base import Base
from app.models.entities import ManagedChannel, SyncedCloudflarePost
from app.services import cloudflare_sync_service


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    monkeypatch.setattr(app_settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(app_settings, "settings_encryption_secret", "test-secret")

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_sync_cloudflare_posts_physically_dedupes_scheme_variants(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    channel = ManagedChannel(
        provider="cloudflare",
        channel_id="dongri-archive",
        display_name="Dongri Archive",
        status="active",
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)

    monkeypatch.setattr(cloudflare_sync_service, "ensure_managed_channels", lambda _db: None)
    monkeypatch.setattr(
        cloudflare_sync_service,
        "list_cloudflare_posts",
        lambda _db: [
            {
                "remote_id": "remote-http",
                "slug": "busan-sand-festival-guide",
                "title": "2026 Busan Haeundae Sand Festival Guide",
                "published_url": "http://dongriarchive.com/ko/post/busan-sand-festival-guide?utm_source=x",
                "status": "error",
                "published_at": "2026-04-07T01:00:00Z",
                "updated_at": "2026-04-07T02:00:00Z",
                "labels": ["festival"],
                "seo_score": 88,
            },
            {
                "remote_id": "remote-https",
                "slug": "busan-sand-festival-guide",
                "title": "2026 Busan Haeundae Sand Festival Guide",
                "published_url": "https://dongriarchive.com/ko/post/busan-sand-festival-guide",
                "status": "published",
                "published_at": "2026-04-07T01:00:00Z",
                "updated_at": "2026-04-07T03:00:00Z",
                "labels": ["travel"],
                "lighthouse_score": 82,
            },
        ],
    )

    result = cloudflare_sync_service.sync_cloudflare_posts(db, include_non_published=True)

    rows = db.execute(
        select(SyncedCloudflarePost).where(SyncedCloudflarePost.managed_channel_id == channel.id)
    ).scalars().all()
    assert result["count"] == 2
    assert result["dedupe"]["merged_group_count"] == 1
    assert result["dedupe"]["merged_row_deleted_count"] == 1
    assert len(rows) == 1
    row = rows[0]
    assert row.status == "published"
    assert row.url == "https://dongriarchive.com/ko/post/busan-sand-festival-guide"
    assert row.seo_score == 88
    assert row.lighthouse_score == 82
    assert row.labels == ["travel", "festival"]
