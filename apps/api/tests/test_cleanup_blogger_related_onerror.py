from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings as app_settings
from app.db.base import Base
from app.models.entities import (
    Article,
    Blog,
    BloggerPost,
    Job,
    JobStatus,
    PostStatus,
    PublishMode,
    SyncedBloggerPost,
)

cleanup_script = importlib.import_module("scripts.cleanup_blogger_related_onerror")


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


def _create_bundle(
    db: Session,
    *,
    blog_id: int,
    title: str,
    slug: str,
    url: str,
) -> tuple[Blog, Article, SyncedBloggerPost]:
    blog = Blog(
        id=blog_id,
        name=f"Blog {blog_id}",
        slug=f"blog-{blog_id}",
        content_category="mystery",
        primary_language="en",
        profile_key="world_mystery",
        is_active=True,
        blogger_blog_id=f"remote-blog-{blog_id}",
        blogger_url=f"https://blog-{blog_id}.blogspot.com",
        publish_mode=PublishMode.PUBLISH,
    )
    db.add(blog)
    db.commit()
    db.refresh(blog)

    job = Job(
        blog_id=blog.id,
        keyword_snapshot=title,
        status=JobStatus.COMPLETED,
        publish_mode=PublishMode.PUBLISH,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    article = Article(
        job_id=job.id,
        blog_id=blog.id,
        title=title,
        meta_description=f"{title} description",
        labels=["Mystery"],
        slug=slug,
        excerpt=f"{title} excerpt",
        html_article="<article><p>Body</p></article>",
        faq_section=[],
        image_collage_prompt="hero prompt",
        inline_media=[],
        assembled_html=(
            "<article>"
            "<img src='https://example.com/body.webp' onerror=\"this.src='https://example.com/body.jpg';\" />"
            "<section class='related-posts'>"
            "<img src='https://example.com/related.webp' onerror=\"this.src='https://example.com/related.jpg';\" />"
            "</section>"
            "</article>"
        ),
        render_metadata={},
        reading_time_minutes=4,
        quality_lighthouse_payload={},
    )
    db.add(article)
    db.commit()
    db.refresh(article)

    blogger_post = BloggerPost(
        job_id=job.id,
        blog_id=blog.id,
        article_id=article.id,
        blogger_post_id=f"remote-post-{blog_id}",
        published_url=url,
        is_draft=False,
        post_status=PostStatus.PUBLISHED,
        response_payload={},
    )
    db.add(blogger_post)
    db.commit()
    db.refresh(blogger_post)

    synced = SyncedBloggerPost(
        blog_id=blog.id,
        remote_post_id=blogger_post.blogger_post_id,
        title=title,
        url=url,
        status="live",
        labels=["Mystery"],
        content_html=(
            "<article>"
            "<p>Lead</p>"
            "<section class='related-posts'>"
            "<img src='https://example.com/related.webp' onerror=\"this.src='https://example.com/related.jpg';\" />"
            "</section>"
            "</article>"
        ),
        thumbnail_url="https://example.com/thumb.webp",
        excerpt_text=f"{title} excerpt",
    )
    db.add(synced)
    db.commit()
    db.refresh(synced)
    return blog, article, synced


def test_sanitize_related_posts_onerror_scopes_to_related_section() -> None:
    html = (
        "<article>"
        "<img src='https://example.com/body.webp' onerror=\"this.src='https://example.com/body.jpg';\" />"
        "<section class='related-posts'>"
        "<img src='https://example.com/related.webp' onerror=\"this.src='https://example.com/related.jpg';\" />"
        "</section>"
        "</article>"
    )
    sanitized, removed_count, section_count = cleanup_script.sanitize_related_posts_onerror(html)

    assert removed_count == 1
    assert section_count == 1
    assert "body.jpg" in sanitized
    related_html = cleanup_script.RELATED_SECTION_RE.search(sanitized).group(0)
    assert "onerror=" not in related_html.lower()


def test_run_cleanup_dry_run_reports_targets(db: Session) -> None:
    _create_bundle(
        db,
        blog_id=35,
        title="Bell Island",
        slug="bell-island",
        url="https://dongdonggri.blogspot.com/2026/03/the-legend-and-reality-of-bell-island.html",
    )

    report = cleanup_script.run_cleanup(
        db,
        mode="dry-run",
        blog_ids=[35],
    )

    assert report["summary"]["targets"] == 1
    assert report["summary"]["dry_run_only"] == 1
    assert report["summary"]["updated"] == 0
    assert report["summary"]["failed"] == 0
    assert report["items"][0]["status"] == "needs_cleanup"
    assert report["items"][0]["content_onerror_removed"] == 1


def test_run_cleanup_apply_updates_remote_and_db(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _blog, article, synced = _create_bundle(
        db,
        blog_id=35,
        title="Bell Island",
        slug="bell-island",
        url="https://dongdonggri.blogspot.com/2026/03/the-legend-and-reality-of-bell-island.html",
    )

    class FakeProvider:
        def __init__(self) -> None:
            self.calls: list[dict[str, str]] = []

        def update_post(self, **kwargs):
            self.calls.append(kwargs)
            return {"id": kwargs["post_id"]}, {}

    provider = FakeProvider()
    monkeypatch.setattr(cleanup_script, "get_blogger_provider", lambda *_args, **_kwargs: provider)

    report = cleanup_script.run_cleanup(
        db,
        mode="apply",
        blog_ids=[35],
    )

    db.refresh(synced)
    db.refresh(article)
    assert report["summary"]["updated"] == 1
    assert report["summary"]["failed"] == 0
    assert len(provider.calls) == 1
    assert "onerror=" not in synced.content_html.lower()
    related_section = cleanup_script.RELATED_SECTION_RE.search(article.assembled_html).group(0)
    assert "onerror=" not in related_section.lower()
    assert "body.jpg" in article.assembled_html


def test_run_cleanup_apply_retries_deadlock(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_bundle(
        db,
        blog_id=35,
        title="Bell Island",
        slug="bell-island",
        url="https://dongdonggri.blogspot.com/2026/03/the-legend-and-reality-of-bell-island.html",
    )

    class FakeProvider:
        def __init__(self) -> None:
            self.calls: list[dict[str, str]] = []

        def update_post(self, **kwargs):
            self.calls.append(kwargs)
            return {"id": kwargs["post_id"]}, {}

    provider = FakeProvider()
    monkeypatch.setattr(cleanup_script, "get_blogger_provider", lambda *_args, **_kwargs: provider)

    original_commit = db.commit
    state = {"count": 0}

    def flaky_commit() -> None:
        if state["count"] == 0:
            state["count"] += 1
            raise OperationalError("deadlock detected", {}, Exception("deadlock detected"))
        original_commit()

    monkeypatch.setattr(db, "commit", flaky_commit)

    report = cleanup_script.run_cleanup(
        db,
        mode="apply",
        blog_ids=[35],
        max_retries=2,
        backoff_seconds=0.0,
    )

    assert report["summary"]["deadlock_retries"] == 1
    assert report["summary"]["updated"] == 1
    assert len(provider.calls) == 2
    assert report["summary"]["failed"] == 0
