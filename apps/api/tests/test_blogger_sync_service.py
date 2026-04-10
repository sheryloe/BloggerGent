from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings as app_settings
from app.db.base import Base
from app.models.entities import Blog, SyncedBloggerPost
from app.services import analytics_service, blogger_sync_service
from app.services.blogger_live_audit_service import BloggerLiveImageAuditResult
from app.services.blogger_oauth_service import BloggerOAuthError
from app.services.topic_guard_service import rebuild_topic_memories_for_blog


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


def test_normalize_public_feed_post_extracts_core_fields() -> None:
    payload = blogger_sync_service._normalize_public_feed_post(
        {
            "id": {"$t": "tag:blogger.com,1999:blog-1.post-999"},
            "title": {"$t": "Bell Island Test"},
            "published": {"$t": "2026-04-10T00:00:00Z"},
            "updated": {"$t": "2026-04-10T01:00:00Z"},
            "content": {"$t": "<p>Hello world</p><img src='https://img.test/a.webp' />"},
            "link": [{"rel": "alternate", "href": "https://example.blogspot.com/2026/04/bell-island-test.html"}],
            "category": [{"term": "Mystery"}, {"term": "Archive"}],
            "author": [{"name": {"$t": "Donggri"}}],
        }
    )

    assert payload["remote_post_id"] == "999"
    assert payload["url"] == "https://example.blogspot.com/2026/04/bell-island-test.html"
    assert payload["labels"] == ["Mystery", "Archive"]
    assert payload["thumbnail_url"] == "https://img.test/a.webp"
    assert payload["author_display_name"] == "Donggri"


def test_sync_blogger_posts_falls_back_to_public_feed_when_api_project_is_deleted(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blog = Blog(
        id=34,
        name="Travel",
        slug="travel",
        content_category="travel",
        primary_language="en",
        profile_key="korea_travel",
        is_active=True,
        blogger_blog_id="remote-34",
        blogger_url="https://example.blogspot.com",
    )
    db.add(blog)
    db.commit()
    db.refresh(blog)

    monkeypatch.setattr(
        blogger_sync_service,
        "fetch_all_live_blogger_posts",
        lambda _db, _remote_blog_id: (_ for _ in ()).throw(
            BloggerOAuthError(
                "Failed to sync live Blogger posts.",
                detail="Project #732610567877 has been deleted.",
                status_code=403,
            )
        ),
    )
    monkeypatch.setattr(
        blogger_sync_service,
        "fetch_public_blogger_posts",
        lambda _blog_url: [
            {
                "remote_post_id": "999",
                "title": "Recovered Post",
                "url": "https://example.blogspot.com/2026/04/recovered-post.html",
                "status": "live",
                "published_at": None,
                "updated_at_remote": None,
                "labels": ["Travel"],
                "author_display_name": "Donggri",
                "replies_total_items": 0,
                "content_html": "<p>Recovered</p>",
                "thumbnail_url": None,
                "excerpt_text": "Recovered",
            }
        ],
    )
    monkeypatch.setattr(
        blogger_sync_service,
        "fetch_and_audit_blogger_post",
        lambda _url, client=None: BloggerLiveImageAuditResult(
            live_image_count=2,
            live_cover_present=True,
            live_inline_present=True,
            live_image_issue="",
            source_fragment="",
            raw_image_count=2,
            empty_figure_count=0,
            raw_figure_count=2,
            renderable_image_urls=[],
        ),
    )
    monkeypatch.setattr(blogger_sync_service, "rebuild_topic_memories_for_blog", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(analytics_service, "sync_synced_post_facts_for_blog", lambda *_args, **_kwargs: None)

    result = blogger_sync_service.sync_blogger_posts_for_blog(db, blog)
    synced = db.execute(select(SyncedBloggerPost).where(SyncedBloggerPost.blog_id == blog.id)).scalar_one()

    assert result["source"] == "public_feed"
    assert result["count"] == 1
    assert synced.remote_post_id == "999"
    assert synced.url == "https://example.blogspot.com/2026/04/recovered-post.html"
    assert synced.live_image_count == 2


def test_sync_connected_blogger_posts_returns_actual_refreshed_ids(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blog_with_id = Blog(
        id=41,
        name="With Remote Id",
        slug="with-remote-id",
        content_category="travel",
        primary_language="en",
        profile_key="korea_travel",
        is_active=True,
        blogger_blog_id="remote-41",
        blogger_url="https://with-id.blogspot.com",
    )
    blog_with_url_only = Blog(
        id=42,
        name="With URL Only",
        slug="with-url-only",
        content_category="travel",
        primary_language="en",
        profile_key="korea_travel",
        is_active=True,
        blogger_blog_id=None,
        blogger_url="https://url-only.blogspot.com",
    )
    db.add_all([blog_with_id, blog_with_url_only])
    db.commit()

    synced_ids: list[int] = []

    def _fake_sync_for_blog(_db: Session, blog: Blog):
        synced_ids.append(blog.id)
        return {"blog_id": blog.id, "count": 1}

    monkeypatch.setattr(blogger_sync_service, "sync_blogger_posts_for_blog", _fake_sync_for_blog)

    result = blogger_sync_service.sync_connected_blogger_posts(db)

    assert sorted(synced_ids) == [41, 42]
    assert sorted(result["refreshed_blog_ids"]) == [41, 42]
    assert result["skipped_blog_ids"] == []
    assert result["warnings"] == []
