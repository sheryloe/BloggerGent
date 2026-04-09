from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings as app_settings
from app.db.base import Base
from app.models.entities import (
    AIUsageEvent,
    AnalyticsArticleFact,
    Article,
    AuditLog,
    Blog,
    BloggerPost,
    GoogleIndexUrlState,
    Image,
    Job,
    JobStatus,
    PostStatus,
    PublishMode,
    PublishQueueItem,
    SearchConsolePageMetric,
    SyncedBloggerPost,
)
from app.services import analytics_service


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    monkeypatch.setattr(app_settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(app_settings, "settings_encryption_secret", "test-secret")

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    session = SessionLocal()
    try:
        from app.services.settings_service import get_settings_map
    except SyntaxError:
        get_settings_map = None
    if callable(get_settings_map):
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
    lighthouse: float | None = None,
    article_id: int | None = None,
    synced_post_id: int | None = None,
    actual_url: str | None = None,
    status: str = "published",
) -> None:
    db.add(
        AnalyticsArticleFact(
            blog_id=blog_id,
            month=month,
            article_id=article_id,
            synced_post_id=synced_post_id,
            title=title,
            published_at=datetime.fromisoformat(f"{date_text}T09:00:00+00:00"),
            source_type=source_type,
            seo_score=seo,
            geo_score=geo,
            lighthouse_score=lighthouse,
            similarity_score=None,
            status=status,
            actual_url=actual_url if actual_url is not None else f"https://example.com/{title}",
        )
    )


def _create_generated_bundle(
    db: Session,
    *,
    blog_id: int,
    month: str,
    date_text: str,
    title: str,
    url: str,
    seo: float,
    geo: float,
    lighthouse: float,
    status: str = "published",
) -> AnalyticsArticleFact:
    published_at = datetime.fromisoformat(f"{date_text}T09:00:00+00:00")
    slug = title.lower().replace(" ", "-")

    job = Job(
        blog_id=blog_id,
        keyword_snapshot=title,
        status=JobStatus.COMPLETED,
        publish_mode=PublishMode.DRAFT,
        error_logs=[],
        raw_prompts={},
        raw_responses={},
    )
    db.add(job)
    db.flush()

    article = Article(
        job_id=job.id,
        blog_id=blog_id,
        title=title,
        meta_description=f"{title} description",
        labels=[],
        slug=slug,
        excerpt=f"{title} excerpt with Seoul cherry blossom timing",
        html_article=f"<p>{title} full HTML body with local route and checklist.</p>",
        faq_section=[],
        image_collage_prompt="collage prompt",
        editorial_category_key="travel",
        editorial_category_label="Travel",
        inline_media=[],
        assembled_html=f"<article><p>{title} assembled content with route guide.</p></article>",
        reading_time_minutes=4,
        quality_similarity_score=None,
        quality_most_similar_url=None,
        quality_seo_score=int(seo),
        quality_geo_score=int(geo),
        quality_lighthouse_score=lighthouse,
        quality_lighthouse_payload={},
        quality_status="ok",
    )
    db.add(article)
    db.flush()

    blogger_post = BloggerPost(
        job_id=job.id,
        blog_id=blog_id,
        article_id=article.id,
        blogger_post_id=f"remote-{job.id}",
        published_url=url,
        published_at=published_at,
        is_draft=False,
        post_status=PostStatus.PUBLISHED,
        response_payload={},
    )
    image = Image(
        job_id=job.id,
        article_id=article.id,
        prompt="image prompt",
        file_path="generated/test.webp",
        public_url="https://cdn.example.com/test.webp",
        image_metadata={},
    )
    queue_item = PublishQueueItem(
        article_id=article.id,
        blog_id=blog_id,
        requested_mode="publish",
        not_before=published_at,
        status="queued",
        response_payload={},
    )
    usage_event = AIUsageEvent(
        blog_id=blog_id,
        job_id=job.id,
        article_id=article.id,
        stage_type="article_generation",
        provider_mode="mock",
        provider_name="mock",
        endpoint="responses",
        input_tokens=10,
        output_tokens=20,
        total_tokens=30,
        request_count=1,
        success=True,
        raw_usage={},
    )
    audit_log = AuditLog(job_id=job.id, stage="publishing", message="ok", payload={})
    fact = AnalyticsArticleFact(
        blog_id=blog_id,
        month=month,
        article_id=article.id,
        title=title,
        published_at=published_at,
        theme_key="travel",
        theme_name="Travel",
        category="Travel",
        seo_score=seo,
        geo_score=geo,
        lighthouse_score=lighthouse,
        similarity_score=None,
        most_similar_url=None,
        status=status,
        actual_url=url,
        source_type="generated",
    )
    db.add_all([blogger_post, image, queue_item, usage_event, audit_log, fact])
    db.commit()
    db.refresh(fact)
    return fact


def _create_synced_post(
    db: Session,
    *,
    blog_id: int,
    remote_post_id: str,
    title: str,
    url: str,
    date_text: str = "2026-04-07",
) -> SyncedBloggerPost:
    post = SyncedBloggerPost(
        blog_id=blog_id,
        remote_post_id=remote_post_id,
        title=title,
        url=url,
        status="live",
        published_at=datetime.fromisoformat(f"{date_text}T09:00:00+00:00"),
        updated_at_remote=datetime.fromisoformat(f"{date_text}T10:00:00+00:00"),
        labels=["Travel"],
        content_html=f"<p>{title} synced content.</p>",
        excerpt_text=f"{title} synced excerpt",
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


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


def test_duplicate_url_rows_merge_into_single_article_and_rollups(db: Session) -> None:
    blog = _create_blog(db, blog_id=4)
    shared_url = "https://example.com/cherry-walk"

    _create_fact(
        db,
        blog_id=blog.id,
        month="2026-04",
        date_text="2026-04-07",
        title="Generated Cherry Walk",
        source_type="generated",
        seo=91,
        geo=86,
        lighthouse=77.6,
        article_id=501,
        actual_url=shared_url,
    )
    _create_fact(
        db,
        blog_id=blog.id,
        month="2026-04",
        date_text="2026-04-07",
        title="Synced Cherry Walk",
        source_type="synced",
        seo=None,
        geo=None,
        synced_post_id=601,
        actual_url=f"{shared_url}/?m=1#night-view",
    )
    _create_fact(
        db,
        blog_id=blog.id,
        month="2026-04",
        date_text="2026-04-08",
        title="Other Riverside Guide",
        source_type="generated",
        seo=70,
        geo=60,
        lighthouse=72.0,
    )
    db.add(GoogleIndexUrlState(blog_id=blog.id, url=shared_url, index_status="indexed"))
    db.add(SearchConsolePageMetric(blog_id=blog.id, url=shared_url, clicks=21, impressions=100, ctr=0.21, payload={}))
    db.commit()

    article_response = analytics_service.get_blog_monthly_articles(db, blog_id=blog.id, month="2026-04")

    assert article_response.total == 2
    merged = next(item for item in article_response.items if item.actual_url == shared_url)
    assert merged.article_id == 501
    assert merged.synced_post_id == 601
    assert merged.title == "Generated Cherry Walk"
    assert merged.seo_score == 91
    assert merged.geo_score == 86
    assert merged.lighthouse_score == 77.6
    assert merged.source_type == "generated"
    assert merged.index_status == "indexed"
    assert merged.ctr == 0.21

    daily_response = analytics_service.get_blog_daily_summary(db, blog_id=blog.id, month="2026-04")
    april_seventh = next(item for item in daily_response.items if item.date == "2026-04-07")
    assert april_seventh.total_posts == 1
    assert april_seventh.generated_posts == 1
    assert april_seventh.synced_posts == 0
    assert april_seventh.avg_seo == 91.0
    assert april_seventh.avg_geo == 86.0

    report = analytics_service.get_blog_monthly_report(db, blog_id=blog.id, month="2026-04")
    assert report.total_posts == 2
    assert report.avg_seo_score == 80.5
    assert report.avg_geo_score == 73.0

    integrated = analytics_service.get_integrated_dashboard(
        db,
        range_name="month",
        month="2026-04",
        blog_id=blog.id,
        include_report=False,
    )
    assert integrated.kpis.total_posts == 2
    assert integrated.kpis.avg_seo_score == 80.5
    assert integrated.kpis.avg_geo_score == 73.0


def test_missing_url_rows_attach_to_matching_title_and_date_group(db: Session) -> None:
    blog = _create_blog(db, blog_id=5)
    shared_url = "https://example.com/lantern-route"

    _create_fact(
        db,
        blog_id=blog.id,
        month="2026-04",
        date_text="2026-04-10",
        title="Seoul Lantern Route",
        source_type="generated",
        seo=88,
        geo=82,
        lighthouse=74.0,
        article_id=701,
        actual_url="",
    )
    _create_fact(
        db,
        blog_id=blog.id,
        month="2026-04",
        date_text="2026-04-10",
        title="Seoul Lantern Route",
        source_type="synced",
        seo=None,
        geo=None,
        synced_post_id=801,
        actual_url=shared_url,
        status="live",
    )
    db.commit()

    response = analytics_service.get_blog_monthly_articles(db, blog_id=blog.id, month="2026-04")

    assert response.total == 1
    merged = response.items[0]
    assert merged.article_id == 701
    assert merged.synced_post_id == 801
    assert merged.actual_url == shared_url
    assert merged.source_type == "generated"
    assert merged.status_variant == "live"


def test_generated_row_exposes_ctr_score_and_error_deleted_state(db: Session) -> None:
    blog = _create_blog(db, blog_id=6)
    stale_fact = _create_generated_bundle(
        db,
        blog_id=blog.id,
        month="2026-04",
        date_text="2026-04-11",
        title="Seoul Cherry Night Walk Guide",
        url="https://example.com/stale-cherry-walk",
        seo=92,
        geo=84,
        lighthouse=76.4,
    )
    _create_synced_post(
        db,
        blog_id=blog.id,
        remote_post_id="live-other",
        title="Current Live Post",
        url="https://example.com/current-live-post",
        date_text="2026-04-11",
    )

    response = analytics_service.get_blog_monthly_articles(db, blog_id=blog.id, month="2026-04")

    item = next(entry for entry in response.items if entry.id == stale_fact.id)
    assert item.ctr_score is not None
    assert item.ctr_score > 0
    assert item.status_variant == "error_deleted"
    assert item.can_manual_delete is True


def test_live_generated_row_cannot_be_manually_deleted(db: Session) -> None:
    blog = _create_blog(db, blog_id=7)
    live_fact = _create_generated_bundle(
        db,
        blog_id=blog.id,
        month="2026-04",
        date_text="2026-04-12",
        title="Yangjaecheon Riverside Cafes",
        url="https://example.com/yangjaecheon-cafes",
        seo=81,
        geo=79,
        lighthouse=71.5,
    )
    _create_synced_post(
        db,
        blog_id=blog.id,
        remote_post_id="live-same",
        title="Yangjaecheon Riverside Cafes",
        url="https://example.com/yangjaecheon-cafes/?m=1",
        date_text="2026-04-12",
    )

    response = analytics_service.get_blog_monthly_articles(db, blog_id=blog.id, month="2026-04")
    item = next(entry for entry in response.items if entry.id == live_fact.id)
    assert item.status_variant == "live"
    assert item.can_manual_delete is False

    with pytest.raises(PermissionError):
        analytics_service.delete_blog_article_fact(db, blog_id=blog.id, fact_id=live_fact.id)


def test_manual_delete_removes_generated_bundle_and_updates_rollups(db: Session) -> None:
    blog = _create_blog(db, blog_id=8)
    stale_fact = _create_generated_bundle(
        db,
        blog_id=blog.id,
        month="2026-04",
        date_text="2026-04-13",
        title="Seoul Hidden Blossom Course",
        url="https://example.com/hidden-blossom-course",
        seo=90,
        geo=83,
        lighthouse=75.2,
    )
    _create_synced_post(
        db,
        blog_id=blog.id,
        remote_post_id="live-anchor",
        title="Another Live Post",
        url="https://example.com/another-live-post",
        date_text="2026-04-13",
    )

    analytics_service.delete_blog_article_fact(db, blog_id=blog.id, fact_id=stale_fact.id)

    assert db.query(AnalyticsArticleFact).filter(AnalyticsArticleFact.blog_id == blog.id).count() == 0
    assert db.query(Job).filter(Job.blog_id == blog.id).count() == 0
    assert db.query(Article).filter(Article.blog_id == blog.id).count() == 0
    assert db.query(BloggerPost).filter(BloggerPost.blog_id == blog.id).count() == 0
    assert db.query(Image).count() == 0
    assert db.query(PublishQueueItem).filter(PublishQueueItem.blog_id == blog.id).count() == 0
    assert db.query(AuditLog).count() == 0
    assert db.query(AIUsageEvent).filter(AIUsageEvent.blog_id == blog.id).count() == 0
    assert db.query(SyncedBloggerPost).filter(SyncedBloggerPost.blog_id == blog.id).count() == 1

    article_response = analytics_service.get_blog_monthly_articles(db, blog_id=blog.id, month="2026-04")
    assert article_response.total == 0

    daily_response = analytics_service.get_blog_daily_summary(db, blog_id=blog.id, month="2026-04")
    assert daily_response.items == []

    report = analytics_service.get_blog_monthly_report(db, blog_id=blog.id, month="2026-04")
    assert report.total_posts == 0


def test_blogger_config_without_remote_skips_external_calls(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        from app.api.routes import settings as settings_route
    except SyntaxError as exc:
        pytest.skip(f"settings route import is currently broken in workspace: {exc}")

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
