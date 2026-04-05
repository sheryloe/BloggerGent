from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes import settings as settings_route
from app.core.config import settings as app_settings
from app.db.base import Base
from app.models.entities import AnalyticsArticleFact, Blog, PublishMode
from app.services import analytics_service
from app.services.settings_service import get_settings_map


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


def _create_fact(
    db: Session,
    *,
    blog_id: int,
    month: str,
    date_text: str,
    title: str,
    source_type: str,
    seo: float | None,
    geo: float | None,
    status: str = "published",
) -> None:
    db.add(
        AnalyticsArticleFact(
            blog_id=blog_id,
            month=month,
            title=title,
            published_at=datetime.fromisoformat(f"{date_text}T09:00:00+00:00"),
            source_type=source_type,
            seo_score=seo,
            geo_score=geo,
            similarity_score=None,
            status=status,
            actual_url=f"https://example.com/{title}",
        )
    )


def test_integrated_without_report_excludes_heavy_payload(db: Session) -> None:
    blog = _create_blog(db, blog_id=1)
    _create_fact(db, blog_id=blog.id, month="2026-04", date_text="2026-04-01", title="a", source_type="generated", seo=80, geo=70)
    _create_fact(db, blog_id=blog.id, month="2026-04", date_text="2026-04-02", title="b", source_type="synced", seo=None, geo=None)
    db.commit()

    payload = analytics_service.get_integrated_dashboard(
        db,
        range_name="month",
        month="2026-04",
        blog_id=blog.id,
        include_report=False,
    )

    assert payload.report is None
    assert payload.kpis.total_posts == 2


def test_daily_summary_aggregates_by_date(db: Session) -> None:
    blog = _create_blog(db, blog_id=2)
    _create_fact(db, blog_id=blog.id, month="2026-04", date_text="2026-04-03", title="a", source_type="generated", seo=90, geo=80)
    _create_fact(db, blog_id=blog.id, month="2026-04", date_text="2026-04-03", title="b", source_type="synced", seo=None, geo=None)
    _create_fact(db, blog_id=blog.id, month="2026-04", date_text="2026-04-04", title="c", source_type="generated", seo=70, geo=60)
    db.commit()

    response = analytics_service.get_blog_daily_summary(db, blog_id=blog.id, month="2026-04")

    assert len(response.items) == 2
    assert response.items[0].date == "2026-04-03"
    assert response.items[0].total_posts == 2
    assert response.items[0].generated_posts == 1
    assert response.items[0].synced_posts == 1
    assert response.items[1].date == "2026-04-04"
    assert response.items[1].avg_seo == 70.0


def test_articles_filter_sort_and_pagination(db: Session) -> None:
    blog = _create_blog(db, blog_id=3)
    _create_fact(db, blog_id=blog.id, month="2026-04", date_text="2026-04-05", title="a", source_type="generated", seo=70, geo=55)
    _create_fact(db, blog_id=blog.id, month="2026-04", date_text="2026-04-05", title="b", source_type="generated", seo=95, geo=88)
    _create_fact(db, blog_id=blog.id, month="2026-04", date_text="2026-04-05", title="c", source_type="generated", seo=85, geo=75)
    _create_fact(db, blog_id=blog.id, month="2026-04", date_text="2026-04-05", title="d", source_type="synced", seo=None, geo=None)
    db.commit()

    response = analytics_service.get_blog_monthly_articles(
        db,
        blog_id=blog.id,
        month="2026-04",
        date="2026-04-05",
        source_type="generated",
        sort="seo",
        dir="desc",
        page=1,
        page_size=2,
    )

    assert response.total == 3
    assert response.page == 1
    assert response.page_size == 2
    assert [item.title for item in response.items] == ["b", "c"]


def test_blogger_config_without_remote_skips_external_calls(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    call_counter = {"blogs": 0, "sc": 0, "ga4": 0}

    def _count_blogs(*_args, **_kwargs):
        call_counter["blogs"] += 1
        return []

    def _count_sc(*_args, **_kwargs):
        call_counter["sc"] += 1
        return []

    def _count_ga4(*_args, **_kwargs):
        call_counter["ga4"] += 1
        return []

    monkeypatch.setattr(settings_route, "list_blogger_blogs", _count_blogs)
    monkeypatch.setattr(settings_route, "list_search_console_sites", _count_sc)
    monkeypatch.setattr(settings_route, "list_analytics_properties", _count_ga4)

    payload = settings_route.get_blogger_settings(include_remote=False, db=db)

    assert payload["remote_loaded"] is False
    assert payload["available_blogs"] == []
    assert payload["search_console_sites"] == []
    assert payload["analytics_properties"] == []
    assert call_counter == {"blogs": 0, "sc": 0, "ga4": 0}
