from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings as app_settings
from app.db.base import Base
from app.models.entities import (
    AnalyticsArticleFact,
    Blog,
    GoogleIndexRequestLog,
    GoogleIndexUrlState,
    PublishMode,
    SearchConsolePageMetric,
    SyncedBloggerPost,
)
from app.services import analytics_service
from app.services import google_indexing_service as indexing_service
from app.services.settings_service import get_settings_map, upsert_settings


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""
        self.content = b"{}"

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict:
        return self._payload


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


def _create_blog(db: Session, *, blog_id: int, slug: str, site_url: str | None = None) -> Blog:
    blog = Blog(
        id=blog_id,
        name=f"Blog {blog_id}",
        slug=slug,
        content_category="custom",
        primary_language="ko",
        profile_key="custom",
        publish_mode=PublishMode.DRAFT,
        is_active=True,
        search_console_site_url=site_url,
    )
    db.add(blog)
    db.commit()
    db.refresh(blog)
    return blog


def _create_post(db: Session, *, blog_id: int, remote_id: str, url: str) -> SyncedBloggerPost:
    now = datetime.now(timezone.utc)
    post = SyncedBloggerPost(
        blog_id=blog_id,
        remote_post_id=remote_id,
        title=f"Post {remote_id}",
        url=url,
        status="live",
        published_at=now,
        updated_at_remote=now,
        labels=[],
        content_html="",
        excerpt_text="",
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


def test_request_respects_cooldown_and_force(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    blog = _create_blog(db, blog_id=1, slug="blog-one")
    url = "https://example.com/jobs/entry-1"
    cooldown_until = datetime.now(timezone.utc) + timedelta(days=3)
    db.add(GoogleIndexUrlState(blog_id=blog.id, url=url, next_eligible_at=cooldown_until, index_status="pending"))
    db.commit()

    publish_payload = {
        "urlNotificationMetadata": {
            "latestUpdate": {
                "notifyTime": "2026-03-29T01:00:00Z",
            }
        }
    }
    monkeypatch.setattr(
        indexing_service,
        "authorized_google_request",
        lambda *_args, **_kwargs: FakeResponse(200, publish_payload),
    )

    skipped = indexing_service.request_single_url_indexing(
        db,
        blog=blog,
        url=url,
        force=False,
        trigger_mode="manual",
        policy_mode="mixed",
        cooldown_days=7,
    )
    assert skipped["status"] == "skipped"
    assert skipped["reason"] == "cooldown"
    assert db.query(GoogleIndexRequestLog).count() == 0

    forced = indexing_service.request_single_url_indexing(
        db,
        blog=blog,
        url=url,
        force=True,
        trigger_mode="manual",
        policy_mode="mixed",
        cooldown_days=7,
    )
    assert forced["status"] == "ok"
    log = db.query(GoogleIndexRequestLog).filter(GoogleIndexRequestLog.request_type == "publish").one()
    assert log.is_force is True


def test_publish_failure_records_log_and_error(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    blog = _create_blog(db, blog_id=2, slug="blog-two")
    url = "https://example.com/jobs/failing-entry"

    failure_payload = {"error": {"message": "quota exceeded"}}
    monkeypatch.setattr(
        indexing_service,
        "authorized_google_request",
        lambda *_args, **_kwargs: FakeResponse(500, failure_payload),
    )

    result = indexing_service.request_single_url_indexing(
        db,
        blog=blog,
        url=url,
        force=True,
        trigger_mode="manual",
        policy_mode="mixed",
        cooldown_days=7,
    )

    assert result["status"] == "failed"
    log = db.query(GoogleIndexRequestLog).filter(GoogleIndexRequestLog.request_type == "publish").one()
    assert log.success is False
    assert log.http_status == 500

    state = db.query(GoogleIndexUrlState).filter(GoogleIndexUrlState.blog_id == blog.id, GoogleIndexUrlState.url == url).one()
    assert state.last_error is not None


def test_la_quota_boundary_counts_only_current_la_day(db: Session) -> None:
    blog = _create_blog(db, blog_id=3, slug="blog-three")
    db.add_all(
        [
            GoogleIndexRequestLog(
                blog_id=blog.id,
                url="https://example.com/jobs/a",
                request_type="publish",
                trigger_mode="auto",
                is_force=False,
                success=True,
                http_status=200,
                request_payload={},
                response_payload={},
                created_at=datetime(2026, 4, 4, 8, 0, tzinfo=timezone.utc),
            ),
            GoogleIndexRequestLog(
                blog_id=blog.id,
                url="https://example.com/jobs/b",
                request_type="publish",
                trigger_mode="auto",
                is_force=False,
                success=True,
                http_status=200,
                request_payload={},
                response_payload={},
                created_at=datetime(2026, 4, 4, 6, 30, tzinfo=timezone.utc),
            ),
        ]
    )
    db.commit()

    remaining = indexing_service.remaining_publish_quota_for_la_day(
        db,
        5,
        now=datetime(2026, 4, 4, 20, 0, tzinfo=timezone.utc),
    )
    assert remaining == 4


def test_quota_snapshot_reports_usage_like_free_tier_counter(db: Session) -> None:
    blog = _create_blog(db, blog_id=31, slug="blog-thirty-one")
    now = datetime(2026, 4, 4, 20, 0, tzinfo=timezone.utc)

    upsert_settings(
        db,
        {
            "google_indexing_daily_quota": "5",
            "blogger_token_scope": "https://www.googleapis.com/auth/indexing",
        },
    )
    db.add_all(
        [
            GoogleIndexRequestLog(
                blog_id=blog.id,
                url="https://example.com/jobs/p1",
                request_type="publish",
                trigger_mode="manual",
                is_force=False,
                success=True,
                http_status=200,
                request_payload={},
                response_payload={},
                created_at=datetime(2026, 4, 4, 8, 0, tzinfo=timezone.utc),
            ),
            GoogleIndexRequestLog(
                blog_id=blog.id,
                url="https://example.com/jobs/p2",
                request_type="publish",
                trigger_mode="manual",
                is_force=False,
                success=True,
                http_status=200,
                request_payload={},
                response_payload={},
                created_at=datetime(2026, 4, 4, 9, 0, tzinfo=timezone.utc),
            ),
            GoogleIndexRequestLog(
                blog_id=blog.id,
                url="https://example.com/jobs/i1",
                request_type="inspection",
                trigger_mode="manual",
                is_force=False,
                success=True,
                http_status=200,
                request_payload={},
                response_payload={},
                created_at=datetime(2026, 4, 4, 10, 0, tzinfo=timezone.utc),
            ),
        ]
    )
    db.commit()

    quota = indexing_service.get_google_blog_indexing_quota(db, blog_id=blog.id, now=now)

    assert quota["publish_used"] == 2
    assert quota["publish_limit"] == 5
    assert quota["publish_remaining"] == 3
    assert quota["inspection_used"] == 1
    assert quota["inspection_limit"] == 2000
    assert quota["inspection_qpm_limit"] == 600


def test_refresh_state_merges_inspection_and_metadata(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    blog = _create_blog(db, blog_id=4, slug="blog-four", site_url="sc-domain:example.com")
    url = "https://example.com/posts/alpha"

    def _fake_google_request(_db, method: str, target: str, **kwargs):
        if method == "GET" and target == indexing_service.INDEXING_METADATA_URL:
            return FakeResponse(
                200,
                {
                    "latestUpdate": {
                        "notifyTime": "2026-03-30T00:00:00Z",
                    }
                },
            )
        if method == "POST" and target == indexing_service.URL_INSPECTION_INSPECT_URL:
            return FakeResponse(
                200,
                {
                    "inspectionResult": {
                        "indexStatusResult": {
                            "verdict": "PASS",
                            "coverageState": "Submitted and indexed",
                            "indexingState": "INDEXING_ALLOWED",
                            "lastCrawlTime": "2026-03-31T00:00:00Z",
                        }
                    }
                },
            )
        raise AssertionError(f"Unexpected request: {method} {target}")

    monkeypatch.setattr(indexing_service, "authorized_google_request", _fake_google_request)

    state = indexing_service.refresh_single_url_state(db, blog=blog, url=url, trigger_mode="manual")
    assert state.index_status == "indexed"
    assert state.last_notify_time is not None
    assert state.last_crawl_time is not None

    logs = db.query(GoogleIndexRequestLog).filter(GoogleIndexRequestLog.url == url).all()
    assert len(logs) == 2
    assert {log.request_type for log in logs} == {"metadata", "inspection"}


def test_scheduler_enforces_global_cap_with_blog_allocation(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    blog_one = _create_blog(db, blog_id=11, slug="blog-eleven")
    blog_two = _create_blog(db, blog_id=12, slug="blog-twelve")
    for index in range(5):
        _create_post(db, blog_id=blog_one.id, remote_id=f"b1-{index}", url=f"https://example.com/jobs/b1-{index}")
        _create_post(db, blog_id=blog_two.id, remote_id=f"b2-{index}", url=f"https://example.com/jobs/b2-{index}")

    upsert_settings(
        db,
        {
            "automation_google_indexing_enabled": "true",
            "google_indexing_policy_mode": "mixed",
            "google_indexing_daily_quota": "4",
            "google_indexing_cooldown_days": "7",
            "google_indexing_blog_quota_map": '{"11": 3, "12": 3}',
            "blogger_token_scope": "https://www.googleapis.com/auth/indexing",
        },
    )

    monkeypatch.setattr(indexing_service, "refresh_search_console_ctr_cache", lambda *_args, **_kwargs: {"status": "ok", "rows": 0})
    monkeypatch.setattr(indexing_service, "refresh_indexing_status_for_blog", lambda *_args, **_kwargs: {"status": "ok", "requested": 0})

    call_counter = {"11": 0, "12": 0}

    def _fake_request_single(db_sess, *, blog: Blog, url: str, force: bool, trigger_mode: str, policy_mode: str, cooldown_days: int):
        call_counter[str(blog.id)] += 1
        return {"status": "ok", "blog_id": blog.id, "url": url}

    monkeypatch.setattr(indexing_service, "request_single_url_indexing", _fake_request_single)

    result = indexing_service.run_google_indexing_schedule(
        db,
        now=datetime(2026, 4, 4, 12, 0, tzinfo=timezone.utc),
    )

    assert result["attempted"] == 4
    assert call_counter["11"] == 3
    assert call_counter["12"] == 1


def test_manual_request_respects_daily_quota(db: Session) -> None:
    blog = _create_blog(db, blog_id=13, slug="blog-thirteen")
    url = "https://example.com/jobs/manual-quota"
    now = datetime.now(timezone.utc)

    upsert_settings(
        db,
        {
            "google_indexing_daily_quota": "1",
            "blogger_token_scope": "https://www.googleapis.com/auth/indexing",
        },
    )
    db.add(
        GoogleIndexRequestLog(
            blog_id=blog.id,
            url="https://example.com/jobs/already-used",
            request_type="publish",
            trigger_mode="manual",
            is_force=False,
            success=True,
            http_status=200,
            request_payload={},
            response_payload={},
            created_at=now,
        )
    )
    db.commit()

    result = indexing_service.request_indexing_for_url(
        db,
        blog_id=blog.id,
        url=url,
        force=False,
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "daily_quota_exhausted"
    assert db.query(GoogleIndexRequestLog).filter(GoogleIndexRequestLog.request_type == "publish").count() == 1


def test_blog_batch_request_runs_test_and_applies_quota(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    blog = _create_blog(db, blog_id=14, slug="blog-fourteen", site_url="sc-domain:example.com")
    for index in range(6):
        _create_post(db, blog_id=blog.id, remote_id=f"b14-{index}", url=f"https://example.com/jobs/b14-{index}")

    upsert_settings(
        db,
        {
            "google_indexing_daily_quota": "2",
            "google_indexing_policy_mode": "mixed",
            "google_indexing_cooldown_days": "7",
            "blogger_token_scope": "https://www.googleapis.com/auth/indexing",
        },
    )

    refresh_calls = {"count": 0}

    def _fake_refresh(*_args, **_kwargs):
        refresh_calls["count"] += 1
        return {"status": "ok", "requested": 0, "refreshed": 0, "failed": 0, "results": []}

    def _fake_request_single(_db, *, blog: Blog, url: str, force: bool, trigger_mode: str, policy_mode: str, cooldown_days: int):
        return {
            "status": "ok",
            "blog_id": blog.id,
            "url": url,
            "index_status": "submitted",
        }

    monkeypatch.setattr(indexing_service, "refresh_indexing_status_for_blog", _fake_refresh)
    monkeypatch.setattr(indexing_service, "request_single_url_indexing", _fake_request_single)

    result = indexing_service.request_indexing_for_blog(
        db,
        blog_id=blog.id,
        count=5,
        run_test=True,
        force=False,
    )

    assert result["status"] in {"ok", "partial"}
    assert result["planned_count"] == 2
    assert result["attempted"] == 2
    assert result["success"] == 2
    assert refresh_calls["count"] == 1


def test_analytics_articles_include_ctr_and_index_fields(db: Session) -> None:
    blog = _create_blog(db, blog_id=21, slug="blog-twenty-one")
    url = "https://example.com/posts/enriched"
    now = datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc)

    db.add(
        AnalyticsArticleFact(
            blog_id=blog.id,
            month="2026-04",
            title="Enriched Post",
            published_at=now,
            seo_score=82,
            geo_score=76,
            similarity_score=12,
            status="published",
            actual_url=url,
            source_type="generated",
        )
    )
    db.add(
        GoogleIndexUrlState(
            blog_id=blog.id,
            url=url,
            index_status="indexed",
            index_coverage_state="Submitted and indexed",
            last_crawl_time=now,
            last_notify_time=now,
            last_checked_at=now,
        )
    )
    db.add(
        SearchConsolePageMetric(
            blog_id=blog.id,
            url=url,
            ctr=0.1234,
            clicks=12,
            impressions=100,
            fetched_at=now,
        )
    )
    db.commit()

    response = analytics_service.get_blog_monthly_articles(db, blog_id=blog.id, month="2026-04")
    assert len(response.items) == 1
    row = response.items[0]
    assert row.ctr == pytest.approx(0.1234)
    assert row.index_status == "indexed"
    assert row.index_coverage_state == "Submitted and indexed"
    assert row.last_notify_time is not None
    assert row.index_last_checked_at is not None
