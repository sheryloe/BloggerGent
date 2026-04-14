from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings as app_settings
from app.db.base import Base
from app.models.entities import (
    Article,
    Blog,
    BloggerPost,
    ContentReviewAction,
    ContentReviewItem,
    Job,
    JobStatus,
    PostStatus,
    PublishMode,
    SyncedBloggerPost,
)
from app.services import content_ops_service as content_ops
from app.services import telegram_service, training_service
from app.services.integrations.settings_service import get_settings_map, upsert_settings


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _long_html(word_count: int = 1200) -> str:
    body = " ".join(f"word{i}" for i in range(word_count))
    return f"<p>{body}</p>"


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    storage_root = tmp_path / "storage"
    monkeypatch.setattr(app_settings, "storage_root", str(storage_root))
    monkeypatch.setattr(app_settings, "settings_encryption_secret", "test-secret")

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    session = TestingSessionLocal()
    get_settings_map(session)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def create_blog(db: Session, *, name: str = "Ops Blog", slug: str = "ops-blog", blogger_blog_id: str | None = None) -> Blog:
    blog = Blog(
        name=name,
        slug=slug,
        description="test blog",
        content_category="tech",
        primary_language="ko",
        profile_key="custom",
        target_audience="operators",
        content_brief="content ops",
        blogger_blog_id=blogger_blog_id,
        blogger_url="https://example.com",
        publish_mode=PublishMode.DRAFT,
        is_active=True,
        target_reading_time_min_minutes=6,
        target_reading_time_max_minutes=8,
    )
    db.add(blog)
    db.commit()
    db.refresh(blog)
    return blog


def create_article(
    db: Session,
    *,
    blog: Blog,
    slug: str,
    title: str | None = None,
    meta_description: str = "A valid meta description that is long enough for testing purposes and safe review flows.",
    excerpt: str = "A valid excerpt that is long enough for the review target and stable test coverage.",
    faq_section: list[dict[str, str]] | None = None,
    html_article: str | None = None,
    post_status: PostStatus | None = None,
) -> Article:
    job = Job(
        blog_id=blog.id,
        keyword_snapshot=f"keyword-{slug}",
        status=JobStatus.COMPLETED,
        publish_mode=PublishMode.DRAFT,
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
        title=title or f"Article {slug}",
        meta_description=meta_description,
        labels=["ops", slug],
        slug=slug,
        excerpt=excerpt,
        html_article=html_article or _long_html(),
        faq_section=faq_section if faq_section is not None else [{"question": "Q1", "answer": "A1"}, {"question": "Q2", "answer": "A2"}],
        image_collage_prompt="editorial cover",
        inline_media=[],
        assembled_html=None,
        reading_time_minutes=7,
    )
    db.add(article)
    db.commit()
    db.refresh(article)

    if post_status is not None:
        blogger_post = BloggerPost(
            job_id=job.id,
            blog_id=blog.id,
            article_id=article.id,
            blogger_post_id=f"remote-{slug}",
            published_url=f"https://example.com/{slug}",
            published_at=_utc_now(),
            is_draft=post_status == PostStatus.DRAFT,
            post_status=post_status,
            scheduled_for=None,
            response_payload={},
        )
        db.add(blogger_post)
        db.commit()

    db.refresh(article)
    return article


def create_synced_post(
    db: Session,
    *,
    blog: Blog,
    remote_post_id: str,
    title: str = "Live Post",
    content_html: str | None = None,
    excerpt_text: str = "A synced excerpt that is long enough for the default live review target.",
    labels: list[str] | None = None,
) -> SyncedBloggerPost:
    post = SyncedBloggerPost(
        blog_id=blog.id,
        remote_post_id=remote_post_id,
        title=title,
        url=f"https://example.com/{remote_post_id}",
        status="live",
        published_at=_utc_now(),
        updated_at_remote=_utc_now(),
        labels=labels or ["ops"],
        author_display_name="tester",
        replies_total_items=0,
        content_html=content_html or _long_html(),
        thumbnail_url=None,
        excerpt_text=excerpt_text,
        synced_at=_utc_now(),
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


def _idle_verification_payload() -> dict[str, SimpleNamespace]:
    return {
        "head_meta_description_status": SimpleNamespace(key="head_meta_description", status="idle", message="idle"),
        "og_description_status": SimpleNamespace(key="og_description", status="idle", message="idle"),
        "twitter_description_status": SimpleNamespace(key="twitter_description", status="idle", message="idle"),
    }


def test_review_article_draft_auto_applies_safe_low_risk_patch(db: Session) -> None:
    blog = create_blog(db, slug="draft-blog")
    article = create_article(
        db,
        blog=blog,
        slug="draft-auto-fix",
        meta_description="short",
        excerpt="too short",
        faq_section=[],
        html_article=_long_html(1200),
    )

    item = content_ops.review_article_draft(db, article.id, trigger="test")
    refreshed_article = db.get(Article, article.id)
    actions = db.execute(
        select(ContentReviewAction).where(ContentReviewAction.item_id == item.id).order_by(ContentReviewAction.id.asc())
    ).scalars().all()

    assert item.approval_status == content_ops.APPROVAL_AUTO_APPROVED
    assert item.apply_status == content_ops.APPLY_APPLIED
    assert refreshed_article is not None
    assert len(refreshed_article.meta_description) >= 60
    assert len(refreshed_article.excerpt) >= 70
    assert len(refreshed_article.faq_section) >= 2
    assert [action.action for action in actions] == ["review", "auto_apply"]


def test_review_article_publish_state_auto_applies_only_safe_publish_patch(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blog = create_blog(db, slug="publish-blog", blogger_blog_id="blog-1")
    article = create_article(
        db,
        blog=blog,
        slug="publish-auto-fix",
        meta_description="short",
        post_status=PostStatus.PUBLISHED,
    )

    provider_calls: list[dict[str, str]] = []
    sync_calls: list[int] = []

    class ProviderStub:
        def update_post(self, **kwargs):
            provider_calls.append(kwargs)
            return (
                {
                    "id": kwargs["post_id"],
                    "url": f"https://example.com/{article.slug}",
                    "published": _utc_now().isoformat(),
                    "isDraft": False,
                    "postStatus": "published",
                },
                {"ok": True},
            )

    monkeypatch.setattr(content_ops, "verify_article_seo_meta", lambda _article: _idle_verification_payload())
    monkeypatch.setattr(content_ops, "get_blogger_provider", lambda _db, _blog: ProviderStub())
    monkeypatch.setattr(
        content_ops,
        "sync_article_search_description",
        lambda _db, _article: SimpleNamespace(
            status="updated",
            message="synced",
            editor_url="https://editor.example.com",
            cdp_url="http://cdp.example.com",
        ),
    )

    item = content_ops.review_article_publish_state(db, article.id, trigger="test")
    refreshed_article = db.get(Article, article.id)
    refreshed_post = db.get(BloggerPost, article.blogger_post.id if article.blogger_post else 0)

    assert item.approval_status == content_ops.APPROVAL_AUTO_APPROVED
    assert item.apply_status == content_ops.APPLY_APPLIED
    assert refreshed_article is not None
    assert len(refreshed_article.meta_description) >= 60
    assert len(provider_calls) == 1
    assert provider_calls[0]["meta_description"] == refreshed_article.meta_description
    assert refreshed_post is not None
    assert refreshed_post.response_payload["search_description_sync"]["status"] == "updated"
    assert refreshed_post.response_payload["search_description_sync"]["message"] == "synced"


def test_sync_live_content_reviews_skips_unchanged_synced_posts(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    blog = create_blog(db, slug="live-blog", blogger_blog_id="blog-2")
    post = create_synced_post(db, blog=blog, remote_post_id="live-1")

    item = content_ops.review_synced_post(db, post.id, trigger="seed")
    monkeypatch.setattr(content_ops, "sync_blogger_posts_for_blog", lambda _db, _blog: {"blog_id": _blog.id, "count": 1})

    result = content_ops.sync_live_content_reviews(db)
    items = db.execute(
        select(ContentReviewItem).where(
            ContentReviewItem.source_type == content_ops.SOURCE_SYNCED_POST,
            ContentReviewItem.source_id == str(post.id),
            ContentReviewItem.review_kind == content_ops.REVIEW_KIND_LIVE,
        )
    ).scalars().all()

    assert item.id == items[0].id
    assert result["status"] == "ok"
    assert result["changed_count"] == 0
    assert len(items) == 1


def test_live_review_apply_is_blocked_and_never_calls_provider(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    blog = create_blog(db, slug="blocked-live-blog", blogger_blog_id="blog-3")
    post = create_synced_post(
        db,
        blog=blog,
        remote_post_id="live-unsafe",
        content_html="<p>short body</p>",
        excerpt_text="short",
        labels=[],
    )
    item = content_ops.review_synced_post(db, post.id, trigger="test")

    provider_called = {"value": False}

    def fail_provider(*args, **kwargs):
        provider_called["value"] = True
        raise AssertionError("provider should not be called")

    monkeypatch.setattr(content_ops, "get_blogger_provider", fail_provider)

    with pytest.raises(content_ops.ContentOpsError, match="awaiting approval"):
        content_ops.apply_content_review(db, item.id, actor="tester", channel="test")

    approved = content_ops.approve_content_review(db, item.id, actor="tester", channel="test")
    with pytest.raises(content_ops.ContentOpsError, match="Only article-backed review items support apply in v1"):
        content_ops.apply_content_review(db, approved.id, actor="tester", channel="test")

    assert provider_called["value"] is False


def test_poll_telegram_ops_commands_ignores_unauthorized_chat_and_logs_it(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    upsert_settings(
        db,
        {
            "telegram_bot_token": "bot-token",
            "telegram_chat_id": "12345",
        },
    )

    messages: list[str] = []

    monkeypatch.setattr(
        telegram_service,
        "_get_telegram_updates",
        lambda **kwargs: [
            {
                "update_id": 1,
                "message": {
                    "text": "/ops status",
                    "chat": {"id": "99999"},
                    "from": {"username": "intruder"},
                },
            }
        ],
    )
    monkeypatch.setattr(
        telegram_service,
        "_post_telegram_message",
        lambda **kwargs: messages.append(kwargs["text"]) or {"delivery_status": "sent"},
    )

    caplog.set_level(logging.WARNING)
    result = telegram_service.poll_telegram_ops_commands(db)
    settings_map = get_settings_map(db)

    assert result == {"status": "ok", "processed": 0, "ignored": 1}
    assert messages == []
    assert settings_map["content_ops_telegram_update_offset"] == "2"
    assert "Ignoring unauthorized Telegram ops command" in caplog.text


def test_learning_snapshot_excludes_rejected_items(db: Session) -> None:
    blog = create_blog(db, slug="learning-blog")
    approved_article = create_article(db, blog=blog, slug="learning-approved")
    rejected_article = create_article(db, blog=blog, slug="learning-rejected")

    approved_item = ContentReviewItem(
        blog_id=blog.id,
        source_type=content_ops.SOURCE_ARTICLE,
        source_id=str(approved_article.id),
        source_title=approved_article.title,
        review_kind=content_ops.REVIEW_KIND_DRAFT,
        content_hash="approved-hash",
        quality_score=95,
        risk_level=content_ops.RISK_LOW,
        issues=[],
        proposed_patch={},
        approval_status=content_ops.APPROVAL_APPROVED,
        apply_status=content_ops.APPLY_APPLIED,
        learning_state=content_ops.LEARNING_APPROVED,
        last_reviewed_at=_utc_now(),
    )
    rejected_item = ContentReviewItem(
        blog_id=blog.id,
        source_type=content_ops.SOURCE_ARTICLE,
        source_id=str(rejected_article.id),
        source_title=rejected_article.title,
        review_kind=content_ops.REVIEW_KIND_DRAFT,
        content_hash="rejected-hash",
        quality_score=55,
        risk_level=content_ops.RISK_MEDIUM,
        issues=[{"code": "needs_work"}],
        proposed_patch={},
        approval_status=content_ops.APPROVAL_REJECTED,
        apply_status=content_ops.APPLY_SKIPPED,
        learning_state=content_ops.LEARNING_REJECTED,
        last_reviewed_at=_utc_now(),
    )
    db.add_all([approved_item, rejected_item])
    db.commit()
    db.refresh(approved_item)
    db.refresh(rejected_item)

    manifest = content_ops.build_learning_snapshot(db)
    rows = [
        json.loads(line)
        for line in Path(manifest["dataset_path"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert {row["source_id"] for row in rows} == {str(approved_article.id)}
    assert manifest["eligible_review_ids"] == [approved_item.id]


def test_training_run_uses_curated_learning_snapshot_when_real_engine_disabled(db: Session) -> None:
    blog = create_blog(db, slug="training-blog")
    article = create_article(db, blog=blog, slug="training-approved")

    approved_item = ContentReviewItem(
        blog_id=blog.id,
        source_type=content_ops.SOURCE_ARTICLE,
        source_id=str(article.id),
        source_title=article.title,
        review_kind=content_ops.REVIEW_KIND_DRAFT,
        content_hash="training-hash",
        quality_score=99,
        risk_level=content_ops.RISK_LOW,
        issues=[],
        proposed_patch={},
        approval_status=content_ops.APPROVAL_APPROVED,
        apply_status=content_ops.APPLY_APPLIED,
        learning_state=content_ops.LEARNING_APPROVED,
        last_reviewed_at=_utc_now(),
    )
    db.add(approved_item)
    db.commit()
    db.refresh(approved_item)

    content_ops.build_learning_snapshot(db)
    assert training_service.is_real_training_engine_enabled(db) is False

    run = training_service.start_training_run(db, session_hours=1, save_every_minutes=20, trigger_source="test")
    started = training_service.mark_run_started(db, run_id=run.id, task_id="task-1")
    checkpoint_path = training_service.create_checkpoint(db, run_id=started.id, reason="test")

    manifest = json.loads(Path(run.dataset_manifest_path).read_text(encoding="utf-8"))

    assert Path(run.dataset_jsonl_path).is_file()
    assert Path(run.dataset_manifest_path).is_file()
    assert Path(checkpoint_path).is_file()
    assert manifest["sources"]["content_ops_curated_learning"] == 1
