from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings as app_settings
from app.db.base import Base
from app.models.entities import Blog, ContentItem, GoogleIndexUrlState, MetricFact, PublicationRecord, PublishMode, SearchConsolePageMetric
from app.services import metric_ingestion_service
from app.services import platform_oauth_service
from app.services import platform_publish_service
from app.services import workspace_service
from app.services.platform.platform_oauth_service import build_platform_authorization_url, complete_google_platform_oauth, refresh_platform_access_token
from app.services.platform.platform_publish_service import mark_content_item_publish_queued, process_platform_publish_queue
from app.services.platform.platform_service import (
    create_content_item,
    ensure_managed_channels,
    get_channel_credential,
    get_managed_channel_by_channel_id,
    list_platform_integrations,
    upsert_platform_credential,
)
from app.services.integrations.secret_service import decrypt_secret_value
from app.services.integrations.settings_service import get_settings_map, upsert_settings
from app.services.ops.usage_service import record_usage_event


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, *, headers: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}
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
    upsert_settings(
        session,
        {
            "blogger_client_id": "google-client-id",
            "blogger_client_secret": "google-client-secret",
        },
    )
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _create_blog(
    db: Session,
    *,
    blog_id: int,
    slug: str,
    blogger_url: str = "https://example.com",
    blogger_blog_id: str | None = None,
    search_console_site_url: str | None = None,
    ga4_property_id: str | None = None,
    profile_key: str = "custom",
) -> Blog:
    blog = Blog(
        id=blog_id,
        name=f"Blog {blog_id}",
        slug=slug,
        content_category="custom",
        primary_language="ko",
        profile_key=profile_key,
        publish_mode=PublishMode.DRAFT,
        is_active=True,
        blogger_blog_id=blogger_blog_id or f"remote-{blog_id}",
        blogger_url=blogger_url,
        search_console_site_url=search_console_site_url,
        ga4_property_id=ga4_property_id,
    )
    db.add(blog)
    db.commit()
    db.refresh(blog)
    return blog


def test_complete_google_platform_oauth_stores_youtube_credential(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_managed_channels(db)
    channel = get_managed_channel_by_channel_id(db, "youtube:main")
    assert channel is not None

    monkeypatch.setattr(
        platform_oauth_service,
        "_google_token_request",
        lambda _payload: {
            "access_token": "youtube-access-token",
            "refresh_token": "youtube-refresh-token",
            "scope": " ".join(platform_oauth_service.YOUTUBE_OAUTH_SCOPES),
            "token_type": "Bearer",
            "expires_in": 3600,
        },
    )
    monkeypatch.setattr(
        platform_oauth_service,
        "_fetch_youtube_channel_identity",
        lambda _access_token: {
            "remote_resource_id": "UC12345",
            "display_name": "Main Channel",
            "base_url": "https://www.youtube.com/channel/UC12345",
            "subject": "Main Channel",
            "metadata": {"channel_id": "UC12345"},
        },
    )

    auth_url = build_platform_authorization_url(db, channel_id="youtube:main")
    state = parse_qs(urlparse(auth_url).query)["state"][0]
    result = complete_google_platform_oauth(db, code="oauth-code", state=state)

    refreshed = get_managed_channel_by_channel_id(db, "youtube:main")
    assert result["channel_id"] == "youtube:main"
    assert refreshed is not None
    assert refreshed.status == "connected"
    credential = get_channel_credential(refreshed)
    assert credential is not None
    assert decrypt_secret_value(credential.access_token_encrypted) == "youtube-access-token"
    assert credential.subject == "Main Channel"


def test_blogger_oauth_nonce_survives_channel_ensure_and_allows_completion(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_blog(
        db,
        blog_id=35,
        slug="the-midnight-archives",
        blogger_url="https://the-midnight-archives.example.com",
        blogger_blog_id="remote-35",
        profile_key="world_mystery",
    )
    ensure_managed_channels(db)

    monkeypatch.setattr(
        platform_oauth_service,
        "_google_token_request",
        lambda _payload: {
            "access_token": "blogger-access-token",
            "refresh_token": "blogger-refresh-token",
            "scope": " ".join(platform_oauth_service.GOOGLE_OAUTH_SCOPES),
            "token_type": "Bearer",
            "expires_in": 3600,
        },
    )
    monkeypatch.setattr(
        platform_oauth_service,
        "_list_blogger_blogs_with_token",
        lambda _access_token: [
            {
                "id": "remote-35",
                "name": "The Midnight Archives",
                "url": "https://the-midnight-archives.example.com",
                "description": "",
            }
        ],
    )

    auth_url = build_platform_authorization_url(db, channel_id="blogger:35")
    state = parse_qs(urlparse(auth_url).query)["state"][0]

    before_ensure = get_managed_channel_by_channel_id(db, "blogger:35")
    assert before_ensure is not None
    before_oauth = dict(before_ensure.channel_metadata or {}).get("oauth")
    before_nonce = str((before_oauth or {}).get("nonce") or "")
    assert before_nonce

    ensure_managed_channels(db)

    after_ensure = get_managed_channel_by_channel_id(db, "blogger:35")
    assert after_ensure is not None
    after_oauth = dict(after_ensure.channel_metadata or {}).get("oauth")
    after_nonce = str((after_oauth or {}).get("nonce") or "")
    assert after_nonce == before_nonce

    result = complete_google_platform_oauth(db, code="oauth-code", state=state)
    assert result["channel_id"] == "blogger:35"


def test_refresh_platform_access_token_updates_youtube_token(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_managed_channels(db)
    channel = get_managed_channel_by_channel_id(db, "youtube:main")
    assert channel is not None

    credential = upsert_platform_credential(
        db,
        channel=channel,
        provider="youtube",
        credential_key=channel.channel_id,
        subject="Main Channel",
        scopes=list(platform_oauth_service.YOUTUBE_OAUTH_SCOPES),
        access_token="expired-token",
        refresh_token="refresh-token",
        expires_at=datetime.now(UTC) - timedelta(minutes=10),
        token_type="Bearer",
        refresh_metadata={},
        is_valid=True,
        last_error=None,
    )
    assert decrypt_secret_value(credential.access_token_encrypted) == "expired-token"

    monkeypatch.setattr(
        platform_oauth_service,
        "_google_token_request",
        lambda _payload: {
            "access_token": "refreshed-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        },
    )
    monkeypatch.setattr(
        platform_oauth_service,
        "_fetch_youtube_channel_identity",
        lambda _access_token: {
            "remote_resource_id": "UC12345",
            "display_name": "Main Channel",
            "base_url": "https://www.youtube.com/channel/UC12345",
            "subject": "Main Channel",
            "metadata": {"channel_id": "UC12345"},
        },
    )

    refreshed = refresh_platform_access_token(db, channel_id="youtube:main")
    assert decrypt_secret_value(refreshed.access_token_encrypted) == "refreshed-token"


def test_list_platform_integrations_without_credentials(db: Session) -> None:
    ensure_managed_channels(db)
    integrations = list_platform_integrations(db)

    by_channel_id = {item["channel_id"]: item for item in integrations}
    assert "youtube:main" in by_channel_id
    assert "instagram:main" in by_channel_id
    assert by_channel_id["youtube:main"]["expires_at"] is None
    assert by_channel_id["instagram:main"]["expires_at"] is None


def test_mission_control_filters_disabled_and_unconfigured_default_channels(db: Session) -> None:
    active_blog = _create_blog(
        db,
        blog_id=21,
        slug="active-blog",
        blogger_url="https://active.example.com",
    )
    inactive_blog = _create_blog(
        db,
        blog_id=22,
        slug="inactive-blog",
        blogger_url="https://inactive.example.com",
    )
    inactive_blog.is_active = False
    db.add(inactive_blog)
    db.commit()

    ensure_managed_channels(db)
    payload = workspace_service.build_mission_control_payload(db, use_cache=False)
    channel_ids = {item["channel_id"] for item in payload["channels"]}

    assert f"blogger:{active_blog.id}" in channel_ids
    assert f"blogger:{inactive_blog.id}" not in channel_ids
    assert "youtube:main" not in channel_ids
    assert "instagram:main" not in channel_ids


def test_managed_channels_include_configured_cloudflare(db: Session) -> None:
    upsert_settings(
        db,
        {
            "cloudflare_channel_enabled": "true",
            "cloudflare_blog_api_base_url": "https://api.dongriarchive.com",
            "cloudflare_blog_m2m_token": "cf-token",
            "cloudflare_r2_public_base_url": "https://img.dongriarchive.com",
        },
    )

    ensure_managed_channels(db)
    channel = get_managed_channel_by_channel_id(db, "cloudflare:dongriarchive")
    assert channel is not None
    assert channel.provider == "cloudflare"
    assert channel.is_enabled is True
    assert channel.status == "connected"
    assert channel.oauth_state == "connected"
    assert channel.base_url == "https://img.dongriarchive.com"


def test_workspace_runtime_usage_groups_provider_buckets(db: Session) -> None:
    blog = _create_blog(db, blog_id=77, slug="usage-blog")

    record_usage_event(
        db,
        blog_id=blog.id,
        stage_type="article_generation",
        provider_name="gemini_cli",
        provider_model="gemini-2.5-pro",
        endpoint="cli:generate",
        input_tokens=120,
        output_tokens=80,
        estimated_cost_usd=0.12,
        request_count=2,
        success=True,
    )
    record_usage_event(
        db,
        blog_id=blog.id,
        stage_type="review",
        provider_name="codex-cli",
        provider_model="codex-latest",
        endpoint="cli:review",
        input_tokens=40,
        output_tokens=20,
        estimated_cost_usd=0.03,
        request_count=1,
        success=False,
        error_message="timeout",
    )

    payload = workspace_service.workspace_runtime_usage(db, days=7)
    by_key = {item["provider_key"]: item for item in payload["providers"]}

    assert payload["totals"]["request_count"] == 3
    assert payload["totals"]["input_tokens"] == 160
    assert payload["totals"]["output_tokens"] == 100
    assert payload["totals"]["total_tokens"] == 260
    assert payload["totals"]["error_count"] == 1
    assert by_key["gemini_cli"]["total_tokens"] == 200
    assert by_key["codex_cli"]["error_count"] == 1


def test_process_platform_publish_queue_uploads_youtube_video(db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_managed_channels(db)
    channel = get_managed_channel_by_channel_id(db, "youtube:main")
    assert channel is not None

    upsert_platform_credential(
        db,
        channel=channel,
        provider="youtube",
        credential_key=channel.channel_id,
        subject="Main Channel",
        scopes=list(platform_oauth_service.YOUTUBE_OAUTH_SCOPES),
        access_token="upload-token",
        refresh_token="refresh-token",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        token_type="Bearer",
        refresh_metadata={},
        is_valid=True,
        last_error=None,
    )

    video_file = tmp_path / "sample.mp4"
    video_file.write_bytes(b"video-bytes")
    thumbnail_file = tmp_path / "thumb.png"
    thumbnail_file.write_bytes(b"thumb-bytes")

    item = create_content_item(
        db,
        channel=channel,
        content_type="youtube_video",
        title="Test Upload",
        description="Video description",
        asset_manifest={
            "video_file_path": str(video_file),
            "thumbnail_file_path": str(thumbnail_file),
        },
        brief_payload={"tags": ["alpha", "beta"]},
    )
    mark_content_item_publish_queued(db, item)

    requests: list[tuple[str, str]] = []

    def _fake_authorized_request(_db, *, channel_id: str, method: str, url: str, **_kwargs):
        requests.append((method, url))
        if method == "POST" and url == platform_publish_service.YOUTUBE_UPLOAD_INIT_URL:
            return FakeResponse(200, {}, headers={"Location": "https://upload.example.com/session"})
        if method == "PUT" and url == "https://upload.example.com/session":
            return FakeResponse(200, {"id": "video-123"})
        if method == "POST" and url == platform_publish_service.YOUTUBE_THUMBNAIL_UPLOAD_URL:
            return FakeResponse(200, {"kind": "youtube#thumbnailSetResponse"})
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(platform_publish_service, "authorized_platform_request", _fake_authorized_request)
    result = process_platform_publish_queue(db, limit=5)

    refreshed = db.get(ContentItem, item.id)
    assert result["processed_count"] == 1
    assert refreshed is not None
    assert refreshed.lifecycle_status == "review"
    latest_publication = (
        db.query(PublicationRecord)
        .filter(PublicationRecord.content_item_id == item.id)
        .order_by(PublicationRecord.id.desc())
        .first()
    )
    assert latest_publication is not None
    assert latest_publication.publish_status == "uploaded_private"
    assert latest_publication.remote_url == "https://www.youtube.com/watch?v=video-123"
    assert requests[0][1] == platform_publish_service.YOUTUBE_UPLOAD_INIT_URL


def test_mark_content_item_publish_queued_sets_blocked_asset_on_missing_youtube_asset(db: Session) -> None:
    ensure_managed_channels(db)
    channel = get_managed_channel_by_channel_id(db, "youtube:main")
    assert channel is not None

    item = create_content_item(
        db,
        channel=channel,
        content_type="youtube_video",
        title="Missing video path",
        description="",
        asset_manifest={},
    )

    queued = mark_content_item_publish_queued(db, item)
    assert queued.lifecycle_status == "blocked_asset"
    assert queued.blocked_reason == "missing_video_file_path"
    publication_count = db.query(PublicationRecord).filter(PublicationRecord.content_item_id == item.id).count()
    assert publication_count == 0


def test_mark_content_item_publish_queued_is_idempotent_after_success(db: Session) -> None:
    ensure_managed_channels(db)
    channel = get_managed_channel_by_channel_id(db, "youtube:main")
    assert channel is not None

    item = create_content_item(
        db,
        channel=channel,
        content_type="youtube_video",
        title="Already published",
        description="",
    )
    db.add(
        PublicationRecord(
            content_item_id=item.id,
            managed_channel_id=channel.id,
            provider="youtube",
            remote_id="video-100",
            remote_url="https://www.youtube.com/watch?v=video-100",
            publish_status="published",
            published_at=datetime.now(UTC),
            response_payload={},
        )
    )
    db.commit()

    queued = mark_content_item_publish_queued(db, item)
    publication_count = db.query(PublicationRecord).filter(PublicationRecord.content_item_id == item.id).count()

    assert queued.id == item.id
    assert queued.lifecycle_status == "published"
    assert publication_count == 1


def test_process_platform_publish_queue_writes_failure_code_for_oauth_error(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_managed_channels(db)
    channel = get_managed_channel_by_channel_id(db, "youtube:main")
    assert channel is not None

    video_file = tmp_path / "sample.mp4"
    video_file.write_bytes(b"video-bytes")
    item = create_content_item(
        db,
        channel=channel,
        content_type="youtube_video",
        title="OAuth failure sample",
        description="",
        asset_manifest={"video_file_path": str(video_file)},
    )
    mark_content_item_publish_queued(db, item)

    def _raise_oauth_error(*_args, **_kwargs):
        raise platform_oauth_service.PlatformOAuthError("oauth failed", detail="token_expired", status_code=401)

    monkeypatch.setattr(platform_publish_service, "authorized_platform_request", _raise_oauth_error)
    result = process_platform_publish_queue(db, limit=5)

    latest_publication = (
        db.query(PublicationRecord)
        .filter(PublicationRecord.content_item_id == item.id)
        .order_by(PublicationRecord.id.desc())
        .first()
    )
    assert result["processed_count"] == 1
    assert result["processed"][0]["error_code"] == "AUTH_EXPIRED"
    assert latest_publication is not None
    assert latest_publication.publish_status == "failed"
    assert latest_publication.error_code == "AUTH_EXPIRED"
    assert latest_publication.response_payload.get("error_code") == "AUTH_EXPIRED"


def test_process_platform_publish_queue_blocks_instagram_without_live_capability(db: Session) -> None:
    ensure_managed_channels(db)
    upsert_settings(db, {"instagram_publish_api_enabled": "true"})
    channel = get_managed_channel_by_channel_id(db, "instagram:main")
    assert channel is not None

    item = create_content_item(
        db,
        channel=channel,
        content_type="instagram_image",
        title="IG Post",
        description="Caption",
        asset_manifest={"image_url": "https://img.example.com/post.png"},
    )
    mark_content_item_publish_queued(db, item)

    result = process_platform_publish_queue(db, limit=5)
    latest_publication = (
        db.query(PublicationRecord)
        .filter(PublicationRecord.content_item_id == item.id)
        .order_by(PublicationRecord.id.desc())
        .first()
    )

    assert result["processed_count"] == 1
    assert latest_publication is not None
    assert latest_publication.publish_status == "blocked"
    assert latest_publication.error_code == "CAPABILITY_BLOCKED"
    assert latest_publication.response_payload["reason"] == "instagram_publish_capability_missing"


def test_instagram_reel_poll_uses_exponential_backoff(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    sleep_calls: list[float] = []
    status_queue = ["IN_PROGRESS", "IN_PROGRESS", "FINISHED"]

    monkeypatch.setattr(platform_publish_service, "_instagram_poll_window_seconds", lambda _db: (60, 1.0, 10.0))
    monkeypatch.setattr(platform_publish_service.random, "uniform", lambda _a, _b: 0.0)
    monkeypatch.setattr(platform_publish_service.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    def _fake_authorized_request(_db, *, method: str, **_kwargs):
        assert method == "GET"
        status_code = status_queue.pop(0)
        return FakeResponse(200, {"status_code": status_code})

    monkeypatch.setattr(platform_publish_service, "authorized_platform_request", _fake_authorized_request)
    payload = platform_publish_service._poll_instagram_reel_container_ready(
        db,
        channel_id="instagram:main",
        creation_id="178900",
    )

    assert payload["status"] == "ready"
    assert payload["attempts"] == 3
    assert sleep_calls == [1.0, 1.8]


def test_create_content_item_reuses_manual_idempotency_key(db: Session) -> None:
    ensure_managed_channels(db)
    channel = get_managed_channel_by_channel_id(db, "instagram:main")
    assert channel is not None

    first = create_content_item(
        db,
        channel=channel,
        content_type="instagram_image",
        title="First title",
        idempotency_key="manual-ig-key",
    )
    second = create_content_item(
        db,
        channel=channel,
        content_type="instagram_image",
        title="Second title ignored",
        idempotency_key="manual-ig-key",
    )

    assert first.id == second.id
    assert second.title == "First title"


def test_workspace_content_item_asset_flow_transitions_to_ready_then_queued(
    db: Session,
    tmp_path: Path,
) -> None:
    ensure_managed_channels(db)
    channel = get_managed_channel_by_channel_id(db, "youtube:main")
    assert channel is not None

    item = create_content_item(
        db,
        channel=channel,
        content_type="youtube_video",
        title="Asset flow",
        description="",
        asset_manifest={},
    )
    blocked = mark_content_item_publish_queued(db, item)
    assert blocked.lifecycle_status == "blocked_asset"
    assert blocked.blocked_reason == "missing_video_file_path"

    video_file = tmp_path / "ready.mp4"
    video_file.write_bytes(b"video-bytes")
    refreshed_item = db.get(ContentItem, item.id)
    assert refreshed_item is not None
    ready_payload = workspace_service.update_content_item(
        db,
        refreshed_item,
        asset_manifest={"video_file_path": str(video_file)},
    )
    assert ready_payload["lifecycle_status"] == "ready_to_publish"
    assert ready_payload.get("blocked_reason") in {"", None}

    queue_target = db.get(ContentItem, item.id)
    assert queue_target is not None
    queued_payload = workspace_service.queue_content_item_publish(db, queue_target)
    assert queued_payload["lifecycle_status"] == "queued"
    latest_publication = (
        db.query(PublicationRecord)
        .filter(PublicationRecord.content_item_id == item.id)
        .order_by(PublicationRecord.id.desc())
        .first()
    )
    assert latest_publication is not None
    assert latest_publication.publish_status == "queued"


def test_sync_blogger_channel_metrics_writes_metric_facts(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    blog = _create_blog(
        db,
        blog_id=11,
        slug="blogger-metrics",
        blogger_url="https://example.com",
        search_console_site_url="sc-domain:example.com",
        ga4_property_id="123456789",
    )
    ensure_managed_channels(db)
    channel = get_managed_channel_by_channel_id(db, f"blogger:{blog.id}")
    assert channel is not None

    item = create_content_item(
        db,
        channel=channel,
        content_type="blog_article",
        title="Indexed Article",
        description="SEO article",
    )
    db.add(
        PublicationRecord(
            content_item_id=item.id,
            managed_channel_id=channel.id,
            provider="blogger",
            remote_id="post-1",
            remote_url="https://example.com/posts/indexed-article",
            publish_status="published",
            published_at=datetime.now(UTC),
            response_payload={},
        )
    )
    db.add(
        GoogleIndexUrlState(
            blog_id=blog.id,
            url="https://example.com/posts/indexed-article",
            index_status="indexed",
        )
    )
    db.add(
        SearchConsolePageMetric(
            blog_id=blog.id,
            url="https://example.com/posts/indexed-article",
            clicks=12,
            impressions=120,
            ctr=0.1,
            position=5.2,
        )
    )
    db.commit()

    monkeypatch.setattr(
        metric_ingestion_service,
        "refresh_indexing_for_blog",
        lambda _db, blog_id: {"status": "ok", "blog_id": blog_id},
    )
    monkeypatch.setattr(
        metric_ingestion_service,
        "query_search_console_performance",
        lambda _db, _site_url, *, days, row_limit: {
            "totals": {"clicks": 12.0, "impressions": 120.0, "ctr": 0.1, "position": 5.2},
            "top_pages": [
                {
                    "keys": ["https://example.com/posts/indexed-article"],
                    "clicks": 12.0,
                    "impressions": 120.0,
                    "ctr": 0.1,
                    "position": 5.2,
                }
            ],
        },
    )
    monkeypatch.setattr(
        metric_ingestion_service,
        "query_analytics_overview",
        lambda _db, _property_id, *, days, row_limit: {
            "totals": {"screenPageViews": 300.0, "sessions": 110.0, "activeUsers": 90.0},
            "top_pages": [
                {
                    "page_path": "/posts/indexed-article",
                    "screenPageViews": 300.0,
                    "sessions": 110.0,
                }
            ],
        },
    )

    result = metric_ingestion_service.sync_blogger_channel_metrics(db, channel_id=f"blogger:{blog.id}", days=28, refresh_indexing=True)
    refreshed = db.get(ContentItem, item.id)

    assert result["facts_written"] > 0
    assert db.query(MetricFact).filter(MetricFact.managed_channel_id == channel.id).count() > 0
    assert refreshed is not None
    assert refreshed.last_score["composite"] is not None
