from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings as app_settings
from app.db.base import Base
from app.models.entities import Article, Blog, Job, JobStatus, PublishMode
from app.services.content import content_ops_service
from app.services.platform import publishing_service


@pytest.fixture()
def db(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Session:
    storage_root = tmp_path / "storage"
    monkeypatch.setattr(app_settings, "storage_root", str(storage_root))
    monkeypatch.setattr(app_settings, "settings_encryption_secret", "test-secret")

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _create_blog(db: Session, *, blog_id: int, slug: str) -> Blog:
    blog = Blog(
        id=blog_id,
        name=f"Blog {blog_id}",
        slug=slug,
        description="test",
        content_category="travel",
        primary_language="ja",
        profile_key="korea_travel",
        target_audience="traveler",
        content_brief="test",
        blogger_blog_id=f"blogger-{blog_id}",
        blogger_url=f"https://example{blog_id}.com",
        publish_mode=PublishMode.PUBLISH,
        is_active=True,
        target_reading_time_min_minutes=6,
        target_reading_time_max_minutes=8,
    )
    db.add(blog)
    db.commit()
    db.refresh(blog)
    return blog


def _create_article(db: Session, *, blog: Blog, title: str, slug: str) -> Article:
    job = Job(
        blog_id=blog.id,
        keyword_snapshot=f"kw-{slug}",
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
        meta_description="A long enough description for publish testing.",
        labels=["Travel", "Seoul", "Metro"],
        slug=slug,
        excerpt="A long enough excerpt for publish testing.",
        html_article="<p>Body</p>",
        faq_section=[{"question": "q", "answer": "a"}],
        image_collage_prompt="prompt",
        inline_media=[],
        assembled_html=None,
        reading_time_minutes=7,
    )
    db.add(article)
    db.commit()
    db.refresh(article)
    db.refresh(blog)
    return article


class _PublishProviderStub:
    def __init__(self) -> None:
        self.access_token = ""
        self.published: list[dict] = []

    def publish(self, **kwargs):
        self.published.append(dict(kwargs))
        return (
            {
                "id": f"new-{len(self.published)}",
                "url": f"https://example.com/{len(self.published)}",
                "published": "2026-04-14T00:00:00+00:00",
                "isDraft": False,
                "postStatus": "published",
                "scheduledFor": None,
            },
            {"ok": True},
        )


def _patch_publish_dependencies(monkeypatch: pytest.MonkeyPatch, provider: _PublishProviderStub) -> None:
    monkeypatch.setattr(
        publishing_service,
        "ensure_article_editorial_labels",
        lambda _db, article: list(article.labels or []),
    )
    monkeypatch.setattr(publishing_service, "validate_candidate_topic", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(publishing_service, "refresh_article_public_image", lambda _db, _article: "")
    monkeypatch.setattr(publishing_service, "rebuild_article_html", lambda _db, _article, _hero: "<p>Body</p>")
    monkeypatch.setattr(
        publishing_service,
        "ensure_trust_gate_appendix",
        lambda html: (html, {"passed": True, "reasons": []}),
    )
    monkeypatch.setattr(publishing_service, "enforce_publish_trust_requirements", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(publishing_service, "get_blogger_provider", lambda _db, _blog: provider)
    monkeypatch.setattr(publishing_service, "rebuild_topic_memories_for_blog", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(publishing_service, "record_mock_usage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(publishing_service, "_finalize_search_description_sync", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(content_ops_service, "review_article_publish_state", lambda *_args, **_kwargs: None)


def test_build_ctr_permalink_title_prefers_slug() -> None:
    article = SimpleNamespace(
        id=1,
        slug="how-to-navigate-seouls-yeonnam-dong-walking-routes-cafes-hidden-local-spots",
        labels=["Travel"],
    )

    title = publishing_service.build_ctr_permalink_title(article)

    assert title.startswith("Navigate Seouls Yeonnam Dong")
    assert title.endswith("Korea Travel Guide")
    assert len(title) <= publishing_service.CTR_PERMALINK_MAX_LENGTH


def test_build_ctr_permalink_title_falls_back_to_labels_and_id() -> None:
    labels_only = SimpleNamespace(id=11, slug="", labels=["Tokyo", "Food", "Guide"])
    fallback = SimpleNamespace(id=22, slug="", labels=["한글만"])

    assert publishing_service.build_ctr_permalink_title(labels_only).startswith("Tokyo Food Guide")
    assert publishing_service.build_ctr_permalink_title(fallback) == "Korea Travel Guide 22"


def test_sanitize_blogger_labels_for_article_replaces_mojibake_for_ja_blog() -> None:
    article = SimpleNamespace(blog_id=37)
    cleaned = publishing_service.sanitize_blogger_labels_for_article(
        article,
        ["??????", "Travel", "Seoul", "Travel"],
    )

    assert cleaned[0] == "旅行・お祭り"
    assert "??????" not in cleaned
    assert cleaned.count("Travel") == 1


def test_perform_publish_now_forces_ctr_title_for_blog_37(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    blog = _create_blog(db, blog_id=37, slug="ja-blog")
    article = _create_article(
        db,
        blog=blog,
        title="初めてのソウル散策",
        slug="how-to-navigate-seouls-yeonnam-dong-walking-routes-cafes-hidden-local-spots",
    )
    provider = _PublishProviderStub()
    _patch_publish_dependencies(monkeypatch, provider)

    expected_title = publishing_service.build_ctr_permalink_title(article)
    publishing_service.perform_publish_now(db, article=article)

    assert provider.published
    assert provider.published[0]["title"] == expected_title
    assert db.get(Article, article.id).title == expected_title


def test_perform_publish_now_keeps_original_title_for_non_target_blog(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blog = _create_blog(db, blog_id=34, slug="en-blog")
    article = _create_article(
        db,
        blog=blog,
        title="Original English Title",
        slug="seoul-night-tour-guide",
    )
    provider = _PublishProviderStub()
    _patch_publish_dependencies(monkeypatch, provider)

    publishing_service.perform_publish_now(db, article=article)

    assert provider.published
    assert provider.published[0]["title"] == "Original English Title"
    assert db.get(Article, article.id).title == "Original English Title"
