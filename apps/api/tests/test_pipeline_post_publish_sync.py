from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings as app_settings
from app.db.base import Base
from app.models.entities import Article, Blog, BloggerPost, Job, JobStatus, PostStatus, PublishMode, SyncedBloggerPost
from app.tasks import pipeline


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


def test_pending_blogger_post_publish_sync_uses_pending_status() -> None:
    result = pipeline._build_pending_blogger_post_publish_sync(
        published_post_status=PostStatus.DRAFT,
        published_url="https://example.blogspot.com/draft",
        remote_post_id="draft-1",
    )

    assert result["provider"] == "blogger"
    assert result["status"] == "pending_sync"
    assert result["score_summary"]["count"] == 0
    assert result["score_rows"] == []


def test_finalize_blogger_post_publish_sync_returns_score_rows(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published_at = datetime(2026, 4, 29, tzinfo=timezone.utc)
    blog = Blog(
        name="Pipeline Blog",
        slug="pipeline-blog",
        content_category="tech",
        primary_language="ko",
        profile_key="custom",
        is_active=True,
        blogger_blog_id="remote-blog",
        blogger_url="https://pipeline.blogspot.com",
    )
    job = Job(
        blog=blog,
        keyword_snapshot="Codex 5.5",
        status=JobStatus.PUBLISHING,
        publish_mode=PublishMode.PUBLISH,
    )
    article = Article(
        job=job,
        blog=blog,
        title="Codex 5.5 Workflow Checklist 2026",
        meta_description="Codex 5.5 workflow checklist.",
        labels=["Development"],
        slug="codex-55-workflow",
        excerpt="Codex 5.5 workflow checklist for setup, testing, publish, and sync.",
        html_article="<h2>Workflow</h2><p>Codex guide checklist timeline command testing publish sync.</p>",
        assembled_html="<h1>Codex 5.5 Workflow Checklist 2026</h1><h2>Workflow</h2><p>Codex guide checklist timeline command testing publish sync.</p>",
        faq_section=[],
        image_collage_prompt="workflow cover",
        quality_seo_score=91,
        quality_geo_score=88,
        quality_lighthouse_score=93,
    )
    blogger_post = BloggerPost(
        job=job,
        blog=blog,
        article=article,
        blogger_post_id="post-77",
        published_url="https://pipeline.blogspot.com/2026/04/codex-55-workflow.html",
        published_at=published_at,
        is_draft=False,
        post_status=PostStatus.PUBLISHED,
    )
    synced_post = SyncedBloggerPost(
        blog=blog,
        remote_post_id="post-77",
        title=article.title,
        url=blogger_post.published_url,
        status="live",
        published_at=published_at,
        updated_at_remote=published_at,
        labels=["Development"],
        content_html=article.assembled_html,
        excerpt_text=article.excerpt,
    )
    db.add_all([blog, job, article, blogger_post, synced_post])
    db.commit()
    db.refresh(article)
    db.refresh(blogger_post)

    called_blog_ids: list[int] = []

    def _fake_sync(_db: Session, sync_blog: Blog) -> dict:
        called_blog_ids.append(sync_blog.id)
        return {"blog_id": sync_blog.id, "count": 1, "score_rows": [], "score_summary": {"count": 0}}

    from app.services.blogger import blogger_sync_service

    monkeypatch.setattr(blogger_sync_service, "sync_blogger_posts_for_blog", _fake_sync)

    result = pipeline._finalize_blogger_post_publish_sync(
        db,
        blog=blog,
        article=article,
        blogger_post=blogger_post,
        published_url=blogger_post.published_url,
        remote_post_id=blogger_post.blogger_post_id,
    )

    assert called_blog_ids == [blog.id]
    assert result["status"] == "ok"
    assert result["score_summary"]["count"] == 1
    assert result["score_rows"][0]["provider"] == "blogger"
    assert result["score_rows"][0]["remote_post_id"] == "post-77"
    assert result["score_rows"][0]["seo_score"] == 91
    assert result["score_rows"][0]["geo_score"] == 88
    assert result["score_rows"][0]["lighthouse_score"] == 93
