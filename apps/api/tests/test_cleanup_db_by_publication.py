from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings as app_settings
from app.db.base import Base
from app.models.entities import AnalyticsArticleFact, Blog, ManagedChannel, SyncedBloggerPost, SyncedCloudflarePost

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "cleanup_db_by_publication.py"


def _load_cleanup_module():
    spec = importlib.util.spec_from_file_location("cleanup_db_by_publication_under_test", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def _add_blog(db: Session) -> Blog:
    blog = Blog(
        id=34,
        name="Live Blog",
        slug="live-blog",
        content_category="travel",
        primary_language="en",
        profile_key="korea_travel",
        blogger_blog_id="remote-blog-34",
        blogger_url="https://live.example.com",
        is_active=True,
    )
    db.add(blog)
    db.commit()
    return blog


def _add_fact(db: Session, *, blog_id: int, title: str, url: str | None, status: str, month: str = "2026-04"):
    fact = AnalyticsArticleFact(
        blog_id=blog_id,
        month=month,
        title=title,
        actual_url=url,
        status=status,
        published_at=datetime(2026, 4, 29, tzinfo=timezone.utc),
        source_type="generated",
        seo_score=80,
        geo_score=81,
        lighthouse_score=82,
    )
    db.add(fact)
    db.flush()
    return fact


def test_live_cleanup_normalizes_matched_facts_and_purges_non_live_facts(db: Session) -> None:
    cleanup = _load_cleanup_module()
    blog = _add_blog(db)
    db.add_all(
        [
            SyncedBloggerPost(
                blog_id=blog.id,
                remote_post_id="live-1",
                title="Live One",
                url="https://live.example.com/2026/04/live-one.html",
                status="LIVE",
            ),
            SyncedBloggerPost(
                blog_id=blog.id,
                remote_post_id="draft-1",
                title="Draft One",
                url="https://live.example.com/2026/04/draft-one.html",
                status="draft",
            ),
        ]
    )
    live_fact = _add_fact(
        db,
        blog_id=blog.id,
        title="Live Fact",
        url="http://live.example.com/2026/04/live-one.html?utm_source=test",
        status="published_live_validated",
    )
    stale_fact = _add_fact(
        db,
        blog_id=blog.id,
        title="Stale Fact",
        url="https://live.example.com/2026/04/stale.html",
        status="scheduled",
    )
    db.commit()

    audit, touched_months = cleanup._apply_blogger_live_fact_cleanup(db)
    db.flush()

    remaining = db.execute(select(AnalyticsArticleFact).order_by(AnalyticsArticleFact.id.asc())).scalars().all()
    assert audit["blogger_live_count"] == 1
    assert audit["blogger_non_live_synced_count"] == 1
    assert audit["facts_to_normalize"] == 1
    assert audit["facts_to_purge"] == 1
    assert audit["sample_normalize_fact_ids"] == [live_fact.id]
    assert audit["sample_purge_fact_ids"] == [stale_fact.id]
    assert touched_months == {(blog.id, "2026-04")}
    assert [row.id for row in remaining] == [live_fact.id]
    assert remaining[0].status == "published"


def test_canonical_audit_reports_cloudflare_published_and_lighthouse_missing(db: Session) -> None:
    cleanup = _load_cleanup_module()
    channel = ManagedChannel(
        provider="cloudflare",
        channel_id="dongri-archive",
        display_name="Dongri Archive",
        status="active",
    )
    db.add(channel)
    db.flush()
    db.add_all(
        [
            SyncedCloudflarePost(
                managed_channel_id=channel.id,
                remote_post_id="cf-live",
                title="Cloudflare Live",
                url="https://dongriarchive.com/ko/post/live",
                status="published",
                lighthouse_score=None,
            ),
            SyncedCloudflarePost(
                managed_channel_id=channel.id,
                remote_post_id="cf-draft",
                title="Cloudflare Draft",
                url="https://dongriarchive.com/ko/post/draft",
                status="draft",
                lighthouse_score=90,
            ),
        ]
    )
    db.commit()

    audit = cleanup._collect_cloudflare_published_audit(db)

    assert audit["cloudflare_published_count"] == 1
    assert audit["cloudflare_non_published_count"] == 1
    assert audit["score_missing"]["cloudflare_lighthouse_count"] == 1
    assert audit["score_missing"]["cloudflare_lighthouse_sample_remote_ids"] == ["cf-live"]


def test_live_sync_uses_cloudflare_published_default(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    cleanup = _load_cleanup_module()
    calls: list[bool] = []

    def _fake_sync(_db: Session, *, include_non_published: bool = False):
        calls.append(include_non_published)
        return {"status": "ok", "count": 1}

    monkeypatch.setattr(cleanup, "sync_cloudflare_posts", _fake_sync)

    result = cleanup._sync_live_sources(db, run_live_sync=True, scope="cloudflare")

    assert result["cloudflare"] == {"status": "ok", "count": 1}
    assert calls == [False]


def test_cleanup_command_rejects_post_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    cleanup = _load_cleanup_module()
    monkeypatch.setattr(sys, "argv", ["cleanup_db_by_publication.py", "--post", "live-1"])

    with pytest.raises(SystemExit) as exc_info:
        cleanup.parse_args()

    assert exc_info.value.code == 2


def test_cli_dry_run_skips_live_sync_by_default(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    cleanup = _load_cleanup_module()
    captured: dict[str, object] = {}

    def _fake_run_cleanup(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            report_path="report.json",
            cutoff_kst="2026-04-10T23:59:59+09:00",
            cutoff_utc="2026-04-10T14:59:59+00:00",
            scope="all",
            mode="dry-run",
            merged_group_count=0,
            merged_row_deleted_count=0,
            keeper_selection_rule="test",
            sample_merged_keys=[],
            canonical_live_audit={},
            blogger={},
            cloudflare={},
            touched_months=[],
        )

    monkeypatch.setattr(cleanup, "run_cleanup", _fake_run_cleanup)
    monkeypatch.setattr(sys, "argv", ["cleanup_db_by_publication.py", "--dry-run"])

    assert cleanup.main() == 0
    capsys.readouterr()

    assert captured["execute"] is False
    assert captured["run_live_sync"] is False
