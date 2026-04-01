from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings as app_settings
from app.db.base import Base
from app.models.entities import Article, Blog, BloggerPost, Job, JobStatus, PostStatus, PublishMode
from app.services import blogger_label_backfill_service as backfill_service
from app.services.article_service import ensure_article_editorial_labels
from app.services.settings_service import get_settings_map


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    storage_root = tmp_path / "storage"
    monkeypatch.setattr(app_settings, "storage_root", str(storage_root))
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


def _create_blog(db: Session, *, profile_key: str, blogger_blog_id: str) -> Blog:
    blog = Blog(
        name=f"Blog {profile_key}",
        slug=f"blog-{profile_key}",
        description="test blog",
        content_category="travel" if profile_key == "korea_travel" else "mystery",
        primary_language="en",
        profile_key=profile_key,
        target_audience="testers",
        content_brief="test brief",
        blogger_blog_id=blogger_blog_id,
        blogger_url="https://example.com",
        publish_mode=PublishMode.PUBLISH,
        is_active=True,
        target_reading_time_min_minutes=6,
        target_reading_time_max_minutes=8,
    )
    db.add(blog)
    db.commit()
    db.refresh(blog)
    return blog


def _create_article(db: Session, *, blog: Blog, title: str, labels: list[str], editorial_key: str, editorial_label: str) -> Article:
    job = Job(
        blog_id=blog.id,
        keyword_snapshot=title,
        status=JobStatus.COMPLETED,
        publish_mode=PublishMode.PUBLISH,
        error_logs=[],
        raw_prompts={},
        raw_responses={},
        attempt_count=1,
        max_attempts=3,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    article = Article(
        job_id=job.id,
        blog_id=blog.id,
        title=title,
        meta_description="A sufficiently long meta description for testing Blogger label backfill behavior.",
        labels=labels,
        slug=title.lower().replace(" ", "-"),
        excerpt="A sufficiently long excerpt for testing Blogger label backfill behavior.",
        html_article="<p>Body</p>",
        faq_section=[],
        image_collage_prompt="prompt",
        editorial_category_key=editorial_key,
        editorial_category_label=editorial_label,
        inline_media=[],
        assembled_html="<p>Body</p>",
        reading_time_minutes=4,
    )
    db.add(article)
    db.commit()
    db.refresh(article)

    blogger_post = BloggerPost(
        job_id=job.id,
        blog_id=blog.id,
        article_id=article.id,
        blogger_post_id=f"remote-{article.id}",
        published_url=f"https://example.com/{article.slug}",
        published_at=None,
        is_draft=False,
        post_status=PostStatus.PUBLISHED,
        scheduled_for=None,
        response_payload={},
    )
    db.add(blogger_post)
    db.commit()
    db.refresh(article)
    return article


def test_ensure_article_editorial_labels_prepends_category_without_duplicates(db: Session) -> None:
    blog = _create_blog(db, profile_key="korea_travel", blogger_blog_id="travel-blog")
    article = _create_article(
        db,
        blog=blog,
        title="Seoul Route",
        labels=["Travel", "Seoul", "travel", "Route"],
        editorial_key="travel",
        editorial_label="Travel",
    )

    labels = ensure_article_editorial_labels(db, article)

    assert labels[0] == "Travel"
    assert labels.count("Travel") == 1
    assert article.editorial_category_label == "Travel"


def test_blogger_editorial_label_backfill_dry_run_marks_missing_labels_processable(db: Session) -> None:
    blog = _create_blog(db, profile_key="korea_travel", blogger_blog_id="travel-blog")
    _create_article(
        db,
        blog=blog,
        title="Busan Evening Walk",
        labels=["Busan", "Evening walk"],
        editorial_key="travel",
        editorial_label="Travel",
    )

    result = backfill_service.dry_run_blogger_editorial_label_backfill(db, profile_keys=["korea_travel"])

    assert result["status"] == "ok"
    assert result["candidate_count"] == 1
    assert result["processable_count"] == 1
    assert result["items"][0]["target_labels"][0] == "Travel"


def test_blogger_editorial_label_backfill_execute_updates_remote_and_writes_report(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    blog = _create_blog(db, profile_key="world_mystery", blogger_blog_id="mystery-blog")
    article = _create_article(
        db,
        blog=blog,
        title="Dyatlov Revisited",
        labels=["Cold Case", "Soviet History"],
        editorial_key="case-files",
        editorial_label="Case Files",
    )
    provider_calls: list[dict] = []

    class DummyProvider:
        def update_post(self, **kwargs):
            provider_calls.append(kwargs)
            return {"id": kwargs["post_id"], "url": article.blogger_post.published_url, "postStatus": "published"}, {}

    monkeypatch.setattr(backfill_service, "get_blogger_provider", lambda _db, _blog: DummyProvider())
    monkeypatch.setattr(
        backfill_service,
        "sync_blogger_posts_for_blog",
        lambda _db, synced_blog: {"blog_id": synced_blog.id, "count": 1, "last_synced_at": "now"},
    )
    monkeypatch.setattr(
        backfill_service,
        "sync_google_sheet_snapshot",
        lambda _db, initial=False: {"status": "ok", "initial": initial},
    )

    result = backfill_service.execute_blogger_editorial_label_backfill(
        db,
        profile_keys=["world_mystery"],
        execution_id="unit-test",
    )

    db.refresh(article)
    assert result["status"] == "ok"
    assert result["updated_count"] == 1
    assert provider_calls[0]["labels"][0] == "Case Files"
    assert article.labels[0] == "Case Files"
    report_path = tmp_path / result["report_path"]
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["updated_count"] == 1
