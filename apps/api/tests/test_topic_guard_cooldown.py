from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings as app_settings
from app.db.base import Base
from app.models.entities import Blog, PublishMode, TopicMemory
from app.services.integrations.settings_service import get_settings_map, upsert_settings
from app.services.content.topic_guard_service import TopicDescriptor, evaluate_topic_guard


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


def _create_blog(db: Session, *, blog_id: int) -> Blog:
    blog = Blog(
        id=blog_id,
        name=f"Blog {blog_id}",
        slug=f"blog-{blog_id}",
        content_category="custom",
        primary_language="ko",
        profile_key="custom",
        publish_mode=PublishMode.DRAFT,
        is_active=True,
    )
    db.add(blog)
    db.commit()
    db.refresh(blog)
    return blog


def test_same_topic_cooldown_blocks_even_when_angle_differs(db: Session) -> None:
    blog = _create_blog(db, blog_id=1)
    upsert_settings(
        db,
        {
            "same_cluster_cooldown_hours": "24",
            "same_topic_cooldown_days": "3",
            "same_angle_cooldown_days": "7",
            "topic_guard_enabled": "true",
        },
    )

    db.add(
        TopicMemory(
            blog_id=blog.id,
            source_type="generated",
            source_id="post-1",
            title="BTS Concert Info 2026",
            canonical_url="https://dongdonggri.blogspot.com/2026/04/bts-concert-info-2026.html",
            published_at=datetime.now(timezone.utc) - timedelta(days=2),
            topic_cluster_key="bts-concert-info-2026",
            topic_cluster_label="BTS Concert Info 2026",
            topic_angle_key="ticket-guide",
            topic_angle_label="Ticket Guide",
            entity_names=["BTS"],
            evidence_excerpt="ticket guide",
        )
    )
    db.commit()

    descriptor = TopicDescriptor(
        topic_cluster_key="bts-concert-info-2026",
        topic_cluster_label="BTS Concert Info 2026",
        topic_angle_key="venue-transport",
        topic_angle_label="Venue Transport",
        entity_names=["BTS"],
        evidence_excerpt="transport",
        distinct_reason="different angle",
    )

    violation = evaluate_topic_guard(
        db,
        blog_id=blog.id,
        descriptor=descriptor,
        target_datetime=datetime.now(timezone.utc),
    )

    assert violation is not None
    assert violation.reason_code == "same_topic_cooldown"
