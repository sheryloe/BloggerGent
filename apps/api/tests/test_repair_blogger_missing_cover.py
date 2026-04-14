from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings as app_settings
from app.db.base import Base
from app.models.entities import (
    Article,
    Blog,
    BloggerPost,
    Image,
    Job,
    JobStatus,
    PostStatus,
    PublishMode,
    SyncedBloggerPost,
)
from app.services.blogger.blogger_live_audit_service import BloggerLiveImageAuditResult

repair_script = importlib.import_module("scripts.repair_blogger_missing_cover")


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


def _audit_result(
    *,
    missing_cover: bool,
    broken_image: bool = False,
    inline_present: bool = False,
    renderable_urls: tuple[str, ...] = (),
) -> BloggerLiveImageAuditResult:
    issue_codes: list[str] = []
    if missing_cover:
        issue_codes.extend(["empty_figure", "missing_cover"])
    if broken_image:
        issue_codes.append("broken_image")
    return BloggerLiveImageAuditResult(
        live_image_count=0,
        live_unique_image_count=0,
        live_duplicate_image_count=0,
        live_webp_count=0,
        live_png_count=0,
        live_other_image_count=0,
        live_cover_present=not missing_cover,
        live_inline_present=inline_present,
        live_image_issue=",".join(issue_codes) if issue_codes else None,
        source_fragment="",
        raw_image_count=0,
        empty_figure_count=1 if missing_cover else 0,
        raw_figure_count=1,
        renderable_image_urls=renderable_urls,
    )


def _create_bundle(
    db: Session,
    tmp_path: Path,
    *,
    blog_id: int,
    title: str,
    slug: str,
    url: str,
    with_image: bool,
    synced_thumbnail_url: str = "https://img.test/thumb.webp",
) -> tuple[Blog, Article, BloggerPost]:
    blog = Blog(
        id=blog_id,
        name=f"Blog {blog_id}",
        slug=f"blog-{blog_id}",
        content_category="travel",
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
        meta_description=f"{title} desc",
        labels=["Mystery"],
        slug=slug,
        excerpt=f"{title} excerpt",
        html_article="<article><figure></figure><section><p>Body</p></section></article>",
        faq_section=[],
        image_collage_prompt="hero prompt",
        inline_media=[{"image_url": "https://img.test/inline.webp"}],
        assembled_html="<article><figure></figure><section><p>Body</p></section></article>",
        render_metadata={},
        reading_time_minutes=4,
        quality_lighthouse_payload={},
    )
    db.add(article)
    db.commit()
    db.refresh(article)

    if with_image:
        image_path = tmp_path / f"{slug}.png"
        image_path.write_bytes(b"fake")
        image = Image(
            job_id=job.id,
            article_id=article.id,
            prompt="hero prompt",
            file_path=str(image_path),
            public_url="https://img.test/hero.webp",
            width=1536,
            height=1024,
            provider="mock",
            image_metadata={"delivery": {"cloudflare": {"original_url": "https://img.test/hero-original.webp"}}},
        )
        db.add(image)
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
        content_html=article.assembled_html,
        thumbnail_url=synced_thumbnail_url,
        excerpt_text=article.excerpt,
    )
    db.add(synced)
    db.commit()
    db.refresh(article)
    db.refresh(blogger_post)
    return blog, article, blogger_post


def test_run_repair_apply_reassembles_when_db_hero_exists(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_bundle(
        db,
        tmp_path,
        blog_id=35,
        title="Bell Island",
        slug="bell-island",
        url="https://dongdonggri.blogspot.com/2026/03/the-legend-and-reality-of-bell-island.html",
        with_image=True,
    )

    monkeypatch.setattr(repair_script, "fetch_and_audit_blogger_post", lambda *_args, **_kwargs: _audit_result(missing_cover=True))
    monkeypatch.setattr(repair_script, "refresh_article_public_image", lambda *_args, **_kwargs: "https://img.test/rebuilt-hero.webp")
    monkeypatch.setattr(repair_script, "rebuild_article_html", lambda *_args, **_kwargs: "<article>rebuilt</article>")
    monkeypatch.setattr(repair_script, "upsert_article_blogger_post", lambda *_args, **_kwargs: None)

    class FakeProvider:
        def __init__(self) -> None:
            self.calls: list[dict[str, str]] = []

        def update_post(self, **kwargs):
            self.calls.append(kwargs)
            return {"id": kwargs["post_id"], "url": kwargs["meta_description"], "published": None}, {}

    provider = FakeProvider()
    monkeypatch.setattr(repair_script, "get_blogger_provider", lambda *_args, **_kwargs: provider)

    report = repair_script.run_repair(db, mode="apply")

    assert report["summary"]["targets"] == 1
    assert report["summary"]["repaired"] == 1
    assert report["summary"]["report_only"] == 0
    assert report["items"][0]["status"] == "reassembled"
    assert report["items"][0]["resolved_hero_url"] == "https://img.test/rebuilt-hero.webp"
    assert len(provider.calls) == 1


def test_run_repair_apply_normalizes_broken_cloudflare_png_urls_from_r2(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blog, article, blogger_post = _create_bundle(
        db,
        tmp_path,
        blog_id=35,
        title="Bell Island",
        slug="bell-island",
        url="https://dongdonggri.blogspot.com/2026/03/the-legend-and-reality-of-bell-island.html",
        with_image=True,
    )
    synced = db.execute(select(SyncedBloggerPost).where(SyncedBloggerPost.blog_id == blog.id)).scalar_one()

    article.image.public_url = "https://api.dongriarchive.com/assets/media/posts/2026/03/bell-island/bell-island.png"
    article.image.image_metadata = {
        "delivery": {
            "cloudflare": {
                "original_url": "https://api.dongriarchive.com/assets/media/posts/2026/03/bell-island/bell-island.png",
                "object_key": "media/posts/2026/03/bell-island/bell-island.png",
                "public_base_url": "https://api.dongriarchive.com/assets",
                "transform_enabled": False,
            }
        }
    }
    article.inline_media = [
        {
            "slot": "mystery-inline-3x2",
            "image_url": "https://api.dongriarchive.com/assets/media/posts/2026/03/bell-island-inline-3x2/bell-island-inline-3x2.png",
            "delivery": {
                "cloudflare": {
                    "original_url": "https://api.dongriarchive.com/assets/media/posts/2026/03/bell-island-inline-3x2/bell-island-inline-3x2.png",
                    "object_key": "media/posts/2026/03/bell-island-inline-3x2/bell-island-inline-3x2.png",
                    "public_base_url": "https://api.dongriarchive.com/assets",
                    "transform_enabled": False,
                }
            },
        }
    ]
    synced.thumbnail_url = article.image.public_url
    db.add_all([article.image, article, synced])
    db.commit()

    monkeypatch.setattr(
        repair_script,
        "fetch_and_audit_blogger_post",
        lambda *_args, **_kwargs: _audit_result(
            missing_cover=False,
            broken_image=True,
            inline_present=True,
            renderable_urls=(
                "https://api.dongriarchive.com/assets/media/posts/2026/03/bell-island/bell-island.png",
                "https://api.dongriarchive.com/assets/media/posts/2026/03/bell-island-inline-3x2/bell-island-inline-3x2.png",
            ),
        ),
    )
    monkeypatch.setattr(
        repair_script,
        "_load_r2_index",
        lambda _db: (
            "https://api.dongriarchive.com",
            {
                "2026/03": {
                    "bell-island": ["media/posts/2026/03/bell-island/bell-island.webp"],
                    "bell-island-inline-3x2": [
                        "media/posts/2026/03/bell-island-inline-3x2/bell-island-inline-3x2.webp"
                    ],
                }
            },
        ),
    )
    monkeypatch.setattr(repair_script, "refresh_article_public_image", lambda *_args, **_kwargs: pytest.fail("refresh should not be called"))
    monkeypatch.setattr(repair_script, "rebuild_article_html", lambda *_args, **_kwargs: "<article>rebuilt</article>")
    monkeypatch.setattr(repair_script, "upsert_article_blogger_post", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(repair_script, "_is_public_image_url_healthy", lambda *_args, **_kwargs: False)

    class FakeProvider:
        def __init__(self) -> None:
            self.calls: list[dict[str, str]] = []

        def update_post(self, **kwargs):
            self.calls.append(kwargs)
            return {"id": kwargs["post_id"], "url": kwargs["meta_description"], "published": None}, {}

    provider = FakeProvider()
    monkeypatch.setattr(repair_script, "get_blogger_provider", lambda *_args, **_kwargs: provider)

    report = repair_script.run_repair(db, mode="apply")

    db.refresh(article.image)
    db.refresh(article)
    db.refresh(synced)

    assert report["summary"]["targets"] == 1
    assert report["summary"]["repaired"] == 1
    assert report["items"][0]["status"] == "reassembled"
    assert report["items"][0]["resolved_hero_url"] == "https://api.dongriarchive.com/assets/media/posts/2026/03/bell-island/bell-island.webp"
    assert article.image.public_url.endswith(".webp")
    assert article.inline_media[0]["image_url"].endswith(".webp")
    assert synced.thumbnail_url.endswith(".webp")
    assert len(provider.calls) == 1


def test_run_repair_reports_r2_candidate_without_updating_when_db_hero_missing(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_bundle(
        db,
        tmp_path,
        blog_id=34,
        title="Roanoke Colony",
        slug="roanoke-colony",
        url="https://donggri-korea.blogspot.com/2026/03/the-roanoke-colony.html",
        with_image=False,
    )

    monkeypatch.setattr(repair_script, "fetch_and_audit_blogger_post", lambda *_args, **_kwargs: _audit_result(missing_cover=True))
    monkeypatch.setattr(
        repair_script,
        "_load_r2_index",
        lambda _db: (
            "https://img.test",
            {
                "2026/03": {
                    "roanoke-colony": [
                        "media/posts/2026/03/roanoke-colony/cover.webp",
                        "media/posts/2026/03/roanoke-colony/inline.webp",
                    ]
                }
            },
        ),
    )

    provider_calls: list[dict[str, str]] = []
    monkeypatch.setattr(repair_script, "get_blogger_provider", lambda *_args, **_kwargs: provider_calls.append({}) or object())

    report = repair_script.run_repair(db, mode="dry-run")

    assert report["summary"]["targets"] == 1
    assert report["summary"]["report_only"] == 1
    assert report["summary"]["repaired"] == 0
    assert report["items"][0]["status"] == "report_only"
    assert report["items"][0]["r2_match"]["matched"] is True
    assert report["items"][0]["r2_match"]["cover_url"] == "https://img.test/assets/media/posts/2026/03/roanoke-colony/cover.webp"
    assert provider_calls == []


def test_run_repair_marks_ambiguous_strict_match(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_bundle(
        db,
        tmp_path,
        blog_id=35,
        title="Dyatlov Pass",
        slug="dyatlov-pass",
        url="https://dongdonggri.blogspot.com/2026/03/dyatlov-pass.html",
        with_image=False,
    )

    monkeypatch.setattr(repair_script, "fetch_and_audit_blogger_post", lambda *_args, **_kwargs: _audit_result(missing_cover=True))
    monkeypatch.setattr(
        repair_script,
        "_load_r2_index",
        lambda _db: (
            "https://img.test",
            {
                "2026/03": {
                    "dyatlov-pass-incident": ["media/posts/2026/03/dyatlov-pass-incident/cover.webp"],
                    "dyatlov-pass-mystery": ["media/posts/2026/03/dyatlov-pass-mystery/cover.webp"],
                }
            },
        ),
    )

    report = repair_script.run_repair(db, mode="dry-run")

    assert report["summary"]["ambiguous"] == 1
    assert report["items"][0]["status"] == "strict_ambiguous"
    assert report["items"][0]["r2_match"]["reason"] == "strict_ambiguous"


def test_run_repair_marks_no_candidate_when_r2_match_is_missing(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_bundle(
        db,
        tmp_path,
        blog_id=35,
        title="Hope Diamond",
        slug="hope-diamond",
        url="https://dongdonggri.blogspot.com/2026/03/hope-diamond.html",
        with_image=False,
    )

    monkeypatch.setattr(repair_script, "fetch_and_audit_blogger_post", lambda *_args, **_kwargs: _audit_result(missing_cover=True))
    monkeypatch.setattr(repair_script, "_load_r2_index", lambda _db: ("https://img.test", {"2026/03": {}}))

    report = repair_script.run_repair(db, mode="dry-run")

    assert report["summary"]["no_candidate"] == 1
    assert report["items"][0]["status"] == "no_candidate"


def test_run_repair_skips_empty_figure_when_cover_is_present(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_bundle(
        db,
        tmp_path,
        blog_id=35,
        title="Wow Signal",
        slug="wow-signal",
        url="https://dongdonggri.blogspot.com/2026/03/the-mystery-of-wow-signal-unexplained.html",
        with_image=True,
    )

    monkeypatch.setattr(
        repair_script,
        "fetch_and_audit_blogger_post",
        lambda *_args, **_kwargs: BloggerLiveImageAuditResult(
            live_image_count=0,
            live_unique_image_count=0,
            live_duplicate_image_count=0,
            live_webp_count=0,
            live_png_count=0,
            live_other_image_count=0,
            live_cover_present=True,
            live_inline_present=False,
            live_image_issue="empty_figure,missing_inline",
            source_fragment="",
            raw_image_count=1,
            empty_figure_count=1,
            raw_figure_count=2,
            renderable_image_urls=("https://img.test/hero.webp",),
        ),
    )

    report = repair_script.run_repair(db, mode="dry-run")

    assert report["summary"]["targets"] == 0
    assert report["items"] == []
