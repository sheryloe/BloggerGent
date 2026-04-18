from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

from app.db.base import Base
from app.models.entities import ManagedChannel, SyncedCloudflarePost
from app.services.cloudflare import cloudflare_post_dedupe_service as dedupe_service
from app.services.cloudflare.cloudflare_asset_policy import ensure_cloudflare_channel_metadata


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _create_channel(db: Session, *, local_root: Path) -> ManagedChannel:
    channel = ManagedChannel(
        provider="cloudflare",
        channel_id="cloudflare:dongriarchive",
        display_name="Dongri Archive",
        status="active",
        channel_metadata=ensure_cloudflare_channel_metadata({"local_asset_root": str(local_root)}),
        is_enabled=True,
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return channel


def _create_post(
    db: Session,
    *,
    channel: ManagedChannel,
    remote_post_id: str,
    slug: str,
    title: str,
    published_at: datetime,
    category_slug: str = "개발과-프로그래밍",
) -> SyncedCloudflarePost:
    row = SyncedCloudflarePost(
        managed_channel_id=channel.id,
        remote_post_id=remote_post_id,
        slug=slug,
        title=title,
        url=f"https://dongriarchive.com/ko/post/{slug}",
        status="published",
        category_slug=category_slug,
        canonical_category_slug=category_slug,
        category_name=category_slug,
        canonical_category_name=category_slug,
        excerpt_text="excerpt",
        thumbnail_url=f"https://img.example.com/{slug}.webp",
        labels=[category_slug],
        published_at=published_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_dedupe_cloudflare_posts_dry_run_reports_keep_and_delete_counts(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = _create_channel(db, local_root=tmp_path / "storage" / "images" / "Cloudflare")
    now = datetime(2026, 4, 17, 10, 0, tzinfo=timezone.utc)
    _create_post(
        db,
        channel=channel,
        remote_post_id="remote-new",
        slug="ai-governance-2026",
        title="AI 코딩 도구 거버넌스 체크리스트 2026 | 개발팀 생산성과 검증 품질을 동시에 지키는 운영 기준",
        published_at=now,
    )
    _create_post(
        db,
        channel=channel,
        remote_post_id="remote-old",
        slug="ai-governance-2026-old",
        title="AI 코딩 도구 거버넌스 체크리스트 2026 | 개발팀 생산성과 검증 품질을 동시에 지키는 운영 기준",
        published_at=now - timedelta(days=1),
    )
    _create_post(
        db,
        channel=channel,
        remote_post_id="remote-unique",
        slug="another-post",
        title="다른 글",
        published_at=now - timedelta(days=2),
    )

    monkeypatch.setattr(dedupe_service, "sync_cloudflare_posts", lambda *_args, **_kwargs: {"status": "ok", "count": 3})

    result = dedupe_service.dedupe_cloudflare_posts(db, mode="dry_run")

    assert result["status"] == "ok"
    assert result["total_live_count"] == 3
    assert result["duplicate_group_count"] == 1
    assert result["keep_count"] == 1
    assert result["delete_candidate_count"] == 1
    assert result["deleted_count"] == 0
    assert result["keep_items"][0]["remote_post_id"] == "remote-new"
    assert result["delete_candidates"][0]["remote_post_id"] == "remote-old"
    assert Path(result["report_path"]).exists()
    assert Path(result["csv_path"]).exists()


def test_dedupe_cloudflare_posts_execute_deletes_remote_and_resyncs(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = _create_channel(db, local_root=tmp_path / "storage" / "images" / "Cloudflare")
    now = datetime(2026, 4, 17, 10, 0, tzinfo=timezone.utc)
    keeper = _create_post(
        db,
        channel=channel,
        remote_post_id="remote-new",
        slug="ai-governance-2026",
        title="AI 코딩 도구 거버넌스 체크리스트 2026 | 개발팀 생산성과 검증 품질을 동시에 지키는 운영 기준",
        published_at=now,
    )
    loser = _create_post(
        db,
        channel=channel,
        remote_post_id="remote-old",
        slug="ai-governance-2026-old",
        title="AI 코딩 도구 거버넌스 체크리스트 2026 | 개발팀 생산성과 검증 품질을 동시에 지키는 운영 기준",
        published_at=now - timedelta(days=1),
    )
    deleted_remote_ids: list[str] = []
    sync_calls = {"count": 0}

    def _fake_sync(session: Session, *, include_non_published: bool = False) -> dict[str, int | str]:
        sync_calls["count"] += 1
        if sync_calls["count"] == 2:
            row = session.get(SyncedCloudflarePost, loser.id)
            if row is not None:
                session.delete(row)
                session.commit()
        return {"status": "ok", "count": 2 if sync_calls["count"] == 2 else 3}

    monkeypatch.setattr(dedupe_service, "sync_cloudflare_posts", _fake_sync)
    monkeypatch.setattr(
        dedupe_service,
        "_integration_request",
        lambda *_args, **kwargs: deleted_remote_ids.append(str(kwargs["path"]).split("/")[-1]) or {"data": {"ok": True}},
    )
    monkeypatch.setattr(dedupe_service, "_integration_data_or_raise", lambda payload: payload["data"])

    result = dedupe_service.dedupe_cloudflare_posts(db, mode="execute")

    assert result["status"] == "ok"
    assert result["deleted_count"] == 1
    assert result["delete_failed_count"] == 0
    assert result["remaining_live_count"] == 1
    assert deleted_remote_ids == ["remote-old"]
    assert db.get(SyncedCloudflarePost, keeper.id) is not None
    assert db.get(SyncedCloudflarePost, loser.id) is None


def test_dedupe_cloudflare_posts_execute_keeps_local_row_when_remote_delete_fails(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = _create_channel(db, local_root=tmp_path / "storage" / "images" / "Cloudflare")
    now = datetime(2026, 4, 17, 10, 0, tzinfo=timezone.utc)
    _create_post(
        db,
        channel=channel,
        remote_post_id="remote-new",
        slug="ai-governance-2026",
        title="AI 코딩 도구 거버넌스 체크리스트 2026 | 개발팀 생산성과 검증 품질을 동시에 지키는 운영 기준",
        published_at=now,
    )
    loser = _create_post(
        db,
        channel=channel,
        remote_post_id="remote-old",
        slug="ai-governance-2026-old",
        title="AI 코딩 도구 거버넌스 체크리스트 2026 | 개발팀 생산성과 검증 품질을 동시에 지키는 운영 기준",
        published_at=now - timedelta(days=1),
    )

    monkeypatch.setattr(dedupe_service, "sync_cloudflare_posts", lambda *_args, **_kwargs: {"status": "ok", "count": 2})
    monkeypatch.setattr(dedupe_service, "_integration_request", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("delete failed")))

    result = dedupe_service.dedupe_cloudflare_posts(db, mode="execute")

    assert result["status"] == "failed"
    assert result["deleted_count"] == 0
    assert result["delete_failed_count"] == 1
    assert result["remaining_live_count"] == 2
    assert len(result["failed_items"]) == 1
    assert db.get(SyncedCloudflarePost, loser.id) is not None
