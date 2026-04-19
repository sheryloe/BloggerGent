from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings as app_settings
from app.db.base import Base
from app.models.entities import Article, Blog, BloggerPost, ContentItem, Image, Job, PostStatus
from app.services.content.travel_translation_state_service import (
    refresh_travel_translation_state,
    resolve_travel_source_image_reuse,
    seed_article_travel_sync_fields,
)


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


def _create_blog(db: Session, *, blog_id: int, slug: str, language: str) -> Blog:
    blog = Blog(
        id=blog_id,
        name=f"Travel {language.upper()}",
        slug=slug,
        content_category="travel",
        primary_language=language,
        profile_key="korea_travel",
        is_active=True,
    )
    db.add(blog)
    db.commit()
    db.refresh(blog)
    return blog


def _create_job(db: Session, *, job_id: int, blog_id: int, keyword: str) -> Job:
    job = Job(
        id=job_id,
        blog_id=blog_id,
        keyword_snapshot=keyword,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _create_article(db: Session, *, article_id: int, job: Job, blog: Blog, slug: str, title: str) -> Article:
    article = Article(
        id=article_id,
        job_id=job.id,
        blog_id=blog.id,
        title=title,
        meta_description="x" * 60,
        labels=["Travel", "Guide"],
        slug=slug,
        excerpt="y" * 60,
        html_article="<p>body</p>" * 40,
        faq_section=[],
        image_collage_prompt="z" * 60,
        render_metadata={},
    )
    article.blog = blog
    db.add(article)
    db.commit()
    db.refresh(article)
    return article


def test_seed_article_travel_sync_fields_uses_content_item_source_article_id(db: Session) -> None:
    en_blog = _create_blog(db, blog_id=34, slug="travel-en", language="en")
    es_blog = _create_blog(db, blog_id=36, slug="travel-es", language="es")
    en_job = _create_job(db, job_id=101, blog_id=en_blog.id, keyword="source")
    es_job = _create_job(db, job_id=102, blog_id=es_blog.id, keyword="localized")
    en_article = _create_article(db, article_id=201, job=en_job, blog=en_blog, slug="busan-night-view", title="Busan Night View")
    es_article = _create_article(db, article_id=202, job=es_job, blog=es_blog, slug="vista-nocturna-busan", title="Vista Nocturna de Busan")

    content_item = ContentItem(
        managed_channel_id=1,
        idempotency_key="travel-es-1",
        blog_id=es_blog.id,
        job_id=es_job.id,
        source_article_id=en_article.id,
        content_type="blogger_post",
        lifecycle_status="draft",
        title=es_article.title,
        description="desc",
        body_text="body",
        asset_manifest={},
        brief_payload={},
        review_notes=[],
        approval_status="pending",
    )
    db.add(content_item)
    db.commit()

    seed_article_travel_sync_fields(db, es_article, commit=True)
    db.refresh(es_article)

    assert es_article.travel_sync_role == "localized_es"
    assert es_article.travel_sync_source_article_id == en_article.id
    assert es_article.travel_sync_group_key == f"travel-en-{en_article.id}"


def test_refresh_travel_translation_state_updates_master_ready_flag(db: Session) -> None:
    en_blog = _create_blog(db, blog_id=34, slug="travel-en", language="en")
    es_blog = _create_blog(db, blog_id=36, slug="travel-es", language="es")
    ja_blog = _create_blog(db, blog_id=37, slug="travel-ja", language="ja")
    en_job = _create_job(db, job_id=201, blog_id=en_blog.id, keyword="source")
    es_job = _create_job(db, job_id=202, blog_id=es_blog.id, keyword="localized-es")
    ja_job = _create_job(db, job_id=203, blog_id=ja_blog.id, keyword="localized-ja")

    en_article = _create_article(db, article_id=301, job=en_job, blog=en_blog, slug="busan-cafe-route", title="Busan Cafe Route")
    es_article = _create_article(db, article_id=302, job=es_job, blog=es_blog, slug="ruta-cafes-busan", title="Ruta de Cafes en Busan")
    ja_article = _create_article(db, article_id=303, job=ja_job, blog=ja_blog, slug="busan-cafe-route-ja", title="釜山カフェ散策")

    es_article.travel_sync_source_article_id = en_article.id
    ja_article.travel_sync_source_article_id = en_article.id
    db.add_all([es_article, ja_article])
    db.commit()

    db.add_all(
        [
            BloggerPost(
                job_id=en_job.id,
                blog_id=en_blog.id,
                article_id=en_article.id,
                blogger_post_id="remote-en",
                published_url="https://en.example/post",
                is_draft=False,
                post_status=PostStatus.PUBLISHED,
                response_payload={},
            ),
            BloggerPost(
                job_id=es_job.id,
                blog_id=es_blog.id,
                article_id=es_article.id,
                blogger_post_id="remote-es",
                published_url="https://es.example/post",
                is_draft=False,
                post_status=PostStatus.PUBLISHED,
                response_payload={},
            ),
            BloggerPost(
                job_id=ja_job.id,
                blog_id=ja_blog.id,
                article_id=ja_article.id,
                blogger_post_id="remote-ja",
                published_url="https://ja.example/post",
                is_draft=False,
                post_status=PostStatus.SCHEDULED,
                response_payload={},
            ),
        ]
    )
    from app.models.entities import SyncedBloggerPost

    db.add_all(
        [
            SyncedBloggerPost(blog_id=es_blog.id, remote_post_id="remote-es", title="ES", url="https://es.example/post", status="live"),
            SyncedBloggerPost(blog_id=ja_blog.id, remote_post_id="remote-ja", title="JA", url="https://ja.example/post", status="live"),
        ]
    )
    db.commit()

    payload = refresh_travel_translation_state(db, blog_ids=(34, 36, 37), write_report=False)
    source_article = db.execute(select(Article).where(Article.id == en_article.id)).scalar_one()

    assert payload["summary"]["ready_count"] == 1
    assert source_article.travel_sync_es_article_id == es_article.id
    assert source_article.travel_sync_ja_article_id == ja_article.id
    assert source_article.travel_sync_es_status == "published"
    assert source_article.travel_sync_ja_status == "scheduled"
    assert source_article.travel_all_languages_ready is True


def test_resolve_travel_source_image_reuse_returns_source_payload(db: Session) -> None:
    en_blog = _create_blog(db, blog_id=34, slug="travel-en", language="en")
    es_blog = _create_blog(db, blog_id=36, slug="travel-es", language="es")
    en_job = _create_job(db, job_id=301, blog_id=en_blog.id, keyword="source")
    es_job = _create_job(db, job_id=302, blog_id=es_blog.id, keyword="localized")
    en_article = _create_article(db, article_id=401, job=en_job, blog=en_blog, slug="busan-harbor-night", title="Busan Harbor Night")
    es_article = _create_article(db, article_id=402, job=es_job, blog=es_blog, slug="noche-puerto-busan", title="Noche en el Puerto de Busan")

    db.add(
        Image(
            job_id=en_job.id,
            article_id=en_article.id,
            prompt="hero prompt",
            file_path="D:/travel/source.webp",
            public_url="https://api.dongriarchive.com/assets/travel-blogger/travel/busan-harbor-night.webp",
            width=1024,
            height=1024,
            provider="mock",
            image_metadata={"delivery": {"public_url": "https://api.dongriarchive.com/assets/travel-blogger/travel/busan-harbor-night.webp"}},
        )
    )
    es_article.travel_sync_source_article_id = en_article.id
    db.add(es_article)
    db.commit()

    payload = resolve_travel_source_image_reuse(db, es_article)

    assert payload is not None
    assert payload["source_article_id"] == en_article.id
    assert payload["public_url"] == "https://api.dongriarchive.com/assets/travel-blogger/travel/busan-harbor-night.webp"
    assert payload["metadata"]["travel_sync_reused"] is True


def test_resolve_travel_source_image_reuse_allows_non_english_source(db: Session) -> None:
    en_blog = _create_blog(db, blog_id=34, slug="travel-en", language="en")
    ja_blog = _create_blog(db, blog_id=37, slug="travel-ja", language="ja")
    ja_job = _create_job(db, job_id=401, blog_id=ja_blog.id, keyword="source-ja")
    en_job = _create_job(db, job_id=402, blog_id=en_blog.id, keyword="localized-en")
    ja_article = _create_article(db, article_id=501, job=ja_job, blog=ja_blog, slug="busan-night-ja", title="釜山ナイトガイド")
    en_article = _create_article(db, article_id=502, job=en_job, blog=en_blog, slug="busan-night-en", title="Busan Night Guide")

    db.add(
        Image(
            job_id=ja_job.id,
            article_id=ja_article.id,
            prompt="ja hero prompt",
            file_path="D:/travel/source-ja.webp",
            public_url="https://api.dongriarchive.com/assets/travel-blogger/travel/busan-night-ja.webp",
            width=1024,
            height=1024,
            provider="mock",
            image_metadata={"delivery": {"public_url": "https://api.dongriarchive.com/assets/travel-blogger/travel/busan-night-ja.webp"}},
        )
    )
    en_article.travel_sync_source_article_id = ja_article.id
    db.add(en_article)
    db.commit()

    payload = resolve_travel_source_image_reuse(db, en_article)

    assert payload is not None
    assert payload["source_article_id"] == ja_article.id
    assert payload["source_blog_id"] == ja_blog.id
    assert payload["public_url"] == "https://api.dongriarchive.com/assets/travel-blogger/travel/busan-night-ja.webp"
