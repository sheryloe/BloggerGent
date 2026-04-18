from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

from app.db.base import Base
from app.models.entities import ManagedChannel, SyncedCloudflarePost
from app.services.cloudflare import cloudflare_asset_rebuild_service as rebuild_service
from app.services.cloudflare.cloudflare_asset_policy import (
    assert_cloudflare_asset_scope,
    ensure_cloudflare_channel_metadata,
    get_cloudflare_asset_policy,
)


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


def _write_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), color=(32, 120, 200)).save(path)


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
    slug: str,
    category_slug: str,
    thumbnail_url: str,
    remote_post_id: str = "remote-1",
) -> SyncedCloudflarePost:
    row = SyncedCloudflarePost(
        managed_channel_id=channel.id,
        remote_post_id=remote_post_id,
        slug=slug,
        title=slug.replace("-", " ").title(),
        url=f"https://dongriarchive.com/ko/post/{slug}",
        status="published",
        category_slug=category_slug,
        canonical_category_slug=category_slug,
        category_name=category_slug,
        canonical_category_name=category_slug,
        excerpt_text="excerpt",
        thumbnail_url=thumbnail_url,
        labels=[category_slug],
        render_metadata={"hero_only": True},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_cloudflare_asset_scope_guard_blocks_outside_root_and_unknown_category(db: Session, tmp_path: Path) -> None:
    local_root = tmp_path / "storage" / "images" / "Cloudflare"
    channel = _create_channel(db, local_root=local_root)
    policy = get_cloudflare_asset_policy(channel)

    with pytest.raises(ValueError):
        assert_cloudflare_asset_scope(policy=policy, category_slug="not-allowed")
    with pytest.raises(ValueError):
        assert_cloudflare_asset_scope(policy=policy, local_path=tmp_path / "outside" / "post.webp")


def test_purge_cloudflare_target_categories_preserves_manifests_and_source_pool(db: Session, tmp_path: Path) -> None:
    storage_root = tmp_path / "storage" / "images"
    local_root = storage_root / "Cloudflare"
    target_dir = local_root / "여행과-기록"
    manifest_path = local_root / "_manifests" / "keep.json"
    source_path = storage_root / "travel-post.png"
    old_path = target_dir / "old-inline-3x2.png"
    _write_image(source_path)
    _write_image(old_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({"ok": True}), encoding="utf-8")

    channel = _create_channel(db, local_root=local_root)
    policy = get_cloudflare_asset_policy(channel)
    purged = rebuild_service.purge_cloudflare_target_categories(policy=policy, category_slugs=["여행과-기록"])

    assert purged == [str(target_dir)]
    assert manifest_path.exists()
    assert source_path.exists()
    assert list(target_dir.iterdir()) == []


def test_rebuild_cloudflare_assets_dry_run_reports_matches_and_breakdowns(db: Session, tmp_path: Path) -> None:
    storage_root = tmp_path / "storage" / "images"
    local_root = storage_root / "Cloudflare"
    source_path = storage_root / "travel-post.png"
    _write_image(source_path)

    channel = _create_channel(db, local_root=local_root)
    _create_post(
        db,
        channel=channel,
        slug="travel-post",
        category_slug="여행과-기록",
        thumbnail_url="https://api.dongriarchive.com/assets/media/posts/2026/04/travel-post-inline-3x2/travel-post-inline-3x2.png",
    )

    result = rebuild_service.rebuild_cloudflare_assets(db, mode="dry_run")

    assert result["status"] == "ok"
    assert result["matched_count"] == 1
    assert result["heuristic_matched_count"] == 0
    assert result["unresolved_count"] == 0
    assert result["legacy_scheme_breakdown"]["legacy_media_posts"] == 1
    assert Path(result["report_path"]).exists()
    assert Path(result["csv_path"]).exists()
    item = result["items"][0]
    assert item["match_source"] == "exact_slug"
    assert Path(item["resolved_target_path"]).name == "travel-post.webp"


def test_rebuild_cloudflare_assets_leaves_low_confidence_fallback_unresolved(db: Session, tmp_path: Path) -> None:
    storage_root = tmp_path / "storage" / "images"
    local_root = storage_root / "Cloudflare"
    _write_image(storage_root / "alpha-guide.png")
    _write_image(storage_root / "beta-notes.png")

    channel = _create_channel(db, local_root=local_root)
    _create_post(
        db,
        channel=channel,
        slug="market-brief",
        category_slug="주식의-흐름",
        thumbnail_url="https://api.dongriarchive.com/assets/media/posts/2026/04/market-brief/market-brief.png",
    )

    result = rebuild_service.rebuild_cloudflare_assets(db, mode="dry_run", use_fallback_heuristic=True)

    assert result["matched_count"] == 0
    assert result["heuristic_matched_count"] == 0
    assert result["unresolved_count"] == 1
    assert result["unresolved"][0]["reason"] in {"low_confidence", "ambiguous_match"}


def test_rebuild_cloudflare_assets_reports_legacy_evidence_without_auto_accept(db: Session, tmp_path: Path) -> None:
    storage_root = tmp_path / "storage" / "images"
    local_root = storage_root / "Cloudflare"
    source_path = storage_root / "legacy-asset.png"
    _write_image(source_path)
    manifest_path = local_root / "_manifests" / "classification.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "source": str(source_path),
                        "target_category": "여행과-기록",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    channel = _create_channel(db, local_root=local_root)
    _create_post(
        db,
        channel=channel,
        slug="different-post",
        category_slug="여행과-기록",
        thumbnail_url="https://api.dongriarchive.com/assets/assets/media/cloudflare/dongri-archive/yeohaenggwa-girog/2026/04/legacy-asset/cover-abc123.webp",
    )

    result = rebuild_service.rebuild_cloudflare_assets(
        db,
        mode="dry_run",
        use_legacy_evidence=True,
        legacy_evidence_can_auto_accept=False,
    )

    assert result["matched_count"] == 0
    assert result["unresolved_count"] == 1
    assert result["url_asset_exact_count"] == 1
    assert result["manifest_category_hit_count"] == 1
    unresolved = result["unresolved"][0]
    assert unresolved["url_asset_slug"] == "legacy-asset"
    assert unresolved["legacy_object_slug"] == "legacy-asset"
    assert unresolved["manifest_category_hit"] is True
    assert unresolved["evidence_score"] > 0
    assert "url_asset_exact" in unresolved["evidence_sources"]
    assert "manifest_category_hit" in unresolved["evidence_sources"]


def test_rebuild_cloudflare_assets_execute_writes_slug_webp_without_live_cutover(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_root = tmp_path / "storage" / "images"
    local_root = storage_root / "Cloudflare"
    source_path = storage_root / "dev-post.png"
    stale_path = local_root / "개발과-프로그래밍" / "stale-inline-3x2.png"
    _write_image(source_path)
    _write_image(stale_path)

    channel = _create_channel(db, local_root=local_root)
    row = _create_post(
        db,
        channel=channel,
        slug="dev-post",
        category_slug="개발과-프로그래밍",
        thumbnail_url="https://api.dongriarchive.com/assets/assets/media/cloudflare/dongri-archive/gaebalgwa-peurogeuraeming/2026/04/dev-post/cover-abc123.webp",
    )
    policy = get_cloudflare_asset_policy(channel)
    expected_object_key = rebuild_service.build_cloudflare_r2_object_key(
        policy=policy,
        category_slug="개발과-프로그래밍",
        post_slug="dev-post",
        published_at=row.published_at,
    )
    captured: dict[str, object] = {}

    def _fake_upload(
        _db: Session,
        *,
        object_key: str | None = None,
        filename: str,
        content: bytes,
        bucket_override: str | None = None,
        public_base_url_override: str | None = None,
        prefix_override: str | None = None,
    ):
        captured["object_key"] = object_key or ""
        captured["filename"] = filename
        captured["content_size"] = len(content)
        captured["bucket_override"] = bucket_override
        return (
            "https://img.example.com/assets/media/cloudflare/dongri-archive/gaebalgwa-peurogeuraeming/2026/04/dev-post/dev-post.webp",
            {"object_key": object_key, "bucket": bucket_override or "dongriarchive-cloudflare"},
            {"cloudflare": {"original_url": "https://img.example.com/assets/media/cloudflare/dongri-archive/gaebalgwa-peurogeuraeming/2026/04/dev-post/dev-post.webp"}},
        )

    monkeypatch.setattr(rebuild_service, "upload_binary_to_cloudflare_r2", _fake_upload)
    monkeypatch.setattr(
        rebuild_service,
        "_update_live_post_cover",
        lambda *_args, **_kwargs: pytest.fail("_update_live_post_cover should not run when update_live_posts=False"),
    )
    monkeypatch.setattr(rebuild_service, "sync_cloudflare_posts", lambda *_args, **_kwargs: pytest.fail("sync_cloudflare_posts should not run"))

    result = rebuild_service.rebuild_cloudflare_assets(
        db,
        mode="execute",
        purge_target=True,
        bucket_override="dongriarchive-cloudflare",
        update_live_posts=False,
    )

    target_path = local_root / "개발과-프로그래밍" / "dev-post.webp"
    assert result["uploaded_count"] == 1
    assert result["updated_count"] == 0
    assert result["failed_count"] == 0
    assert target_path.exists()
    assert not stale_path.exists()
    assert captured["object_key"] == expected_object_key
    assert captured["bucket_override"] == "dongriarchive-cloudflare"
    assert result["bucket_name"] == "dongriarchive-cloudflare"
    assert result["bucket_verified"] is True
    assert result["sample_uploaded_keys"] == [expected_object_key]
    assert row.thumbnail_url.endswith("cover-abc123.webp")
    assert result["items"][0]["resolved_public_url"].endswith("/dev-post/dev-post.webp")
    assert result["items"][0]["status"] == "uploaded"


def test_rebuild_cloudflare_assets_remote_fetch_gate_disables_on_500_preflight(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeResponse:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code

    storage_root = tmp_path / "storage" / "images"
    local_root = storage_root / "Cloudflare"
    source_path = storage_root / "travel-post.png"
    _write_image(source_path)

    channel = _create_channel(db, local_root=local_root)
    _create_post(
        db,
        channel=channel,
        slug="travel-post",
        category_slug="여행과-기록",
        thumbnail_url="https://api.dongriarchive.com/assets/media/posts/2026/04/travel-post/travel-post.webp",
    )

    monkeypatch.setattr(rebuild_service.httpx, "head", lambda *_args, **_kwargs: _FakeResponse(500))
    monkeypatch.setattr(rebuild_service.httpx, "get", lambda *_args, **_kwargs: _FakeResponse(500))
    monkeypatch.setattr(
        rebuild_service,
        "upload_binary_to_cloudflare_r2",
        lambda *_args, **_kwargs: (
            "https://img.example.com/assets/media/cloudflare/dongri-archive/yeohaenggwa-girog/2026/04/travel-post/travel-post.webp",
            {"object_key": _kwargs["object_key"], "bucket": "dongriarchive-cloudflare"},
            {"cloudflare": {"original_url": "https://img.example.com/assets/media/cloudflare/dongri-archive/yeohaenggwa-girog/2026/04/travel-post/travel-post.webp"}},
        ),
    )
    monkeypatch.setattr(
        rebuild_service,
        "_update_live_post_cover",
        lambda *_args, **_kwargs: pytest.fail("_update_live_post_cover should not run when update_live_posts=False"),
    )

    result = rebuild_service.rebuild_cloudflare_assets(
        db,
        mode="execute",
        bucket_override="dongriarchive-cloudflare",
        allow_remote_thumbnail_fetch=True,
        update_live_posts=False,
    )

    assert result["uploaded_count"] == 1
    assert result["remote_fetch_enabled"] is False
    assert result["remote_fetch_attempted_count"] == 0
    assert result["remote_fetch_success_count"] == 0
    assert result["remote_fetch_preflight_count"] == 1
    assert result["remote_fetch_preflight_success_count"] == 0
    assert result["remote_fetch_status_breakdown"] == {"500": 1}


def test_rebuild_cloudflare_assets_execute_can_update_live_posts_when_enabled(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_root = tmp_path / "storage" / "images"
    local_root = storage_root / "Cloudflare"
    source_path = storage_root / "dev-post.png"
    _write_image(source_path)

    channel = _create_channel(db, local_root=local_root)
    row = _create_post(
        db,
        channel=channel,
        slug="dev-post",
        category_slug="개발과-프로그래밍",
        thumbnail_url="https://api.dongriarchive.com/assets/assets/media/cloudflare/dongri-archive/gaebalgwa-peurogeuraeming/2026/04/dev-post/cover-abc123.webp",
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        rebuild_service,
        "upload_binary_to_cloudflare_r2",
        lambda *_args, **_kwargs: (
            "https://img.example.com/assets/media/cloudflare/dongri-archive/gaebalgwa-peurogeuraeming/2026/04/dev-post/dev-post.webp",
            {"object_key": _kwargs["object_key"], "bucket": "dongriarchive-cloudflare"},
            {"cloudflare": {"original_url": "https://img.example.com/assets/media/cloudflare/dongri-archive/gaebalgwa-peurogeuraeming/2026/04/dev-post/dev-post.webp"}},
        ),
    )
    monkeypatch.setattr(
        rebuild_service,
        "_fetch_integration_post_detail",
        lambda *_args, **_kwargs: {
            "title": "Dev Post",
            "contentMarkdown": "# Dev Post\n\n<p>body</p>\n\n<p><img src=\"https://img.example.com/old-inline.webp\" alt=\"inline\" /></p>",
            "excerpt": "excerpt",
            "seoTitle": "Dev Post",
            "seoDescription": "excerpt",
            "status": "published",
            "category": {"slug": "개발과-프로그래밍"},
            "tagNames": ["개발과-프로그래밍"],
        },
    )

    def _fake_integration_request(*_args, **kwargs):
        captured["payload"] = kwargs["json_payload"]
        return {"data": kwargs["json_payload"]}

    monkeypatch.setattr(rebuild_service, "_integration_request", _fake_integration_request)
    monkeypatch.setattr(rebuild_service, "_integration_data_or_raise", lambda payload: payload["data"])
    monkeypatch.setattr(rebuild_service, "sync_cloudflare_posts", lambda *_args, **_kwargs: {"status": "ok", "count": 1})

    result = rebuild_service.rebuild_cloudflare_assets(
        db,
        mode="execute",
        update_live_posts=True,
        bucket_override="dongriarchive-cloudflare",
    )

    assert result["uploaded_count"] == 1
    assert result["updated_count"] == 1
    assert "<img" not in str(captured["payload"]["content"])
    assert row.thumbnail_url.endswith("/dev-post/dev-post.webp")


def test_rebuild_cloudflare_assets_ignores_cover_files_without_thumbnail_fallback(
    db: Session,
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "storage" / "images"
    local_root = storage_root / "Cloudflare"
    _write_image(storage_root / "cover-travel-post.png")

    channel = _create_channel(db, local_root=local_root)
    _create_post(
        db,
        channel=channel,
        slug="travel-post",
        category_slug="여행과-기록",
        thumbnail_url="https://api.dongriarchive.com/assets/media/posts/2026/04/travel-post/travel-post.webp",
    )

    result = rebuild_service.rebuild_cloudflare_assets(
        db,
        mode="dry_run",
        ignore_filename_patterns=["cover"],
        allow_thumbnail_fallback=False,
    )

    assert result["matched_count"] == 0
    assert result["heuristic_matched_count"] == 0
    assert result["unresolved_count"] == 1
    assert result["ignore_filename_patterns"] == ["cover"]
    assert result["allow_thumbnail_fallback"] is False


def test_rebuild_cloudflare_assets_uses_root_pool_only(db: Session, tmp_path: Path) -> None:
    storage_root = tmp_path / "storage" / "images"
    local_root = storage_root / "Cloudflare"
    _write_image(storage_root / "travel-post.png")
    _write_image((storage_root / "Travel") / "travel-post.png")
    _write_image((storage_root / "mystery") / "travel-post.png")
    _write_image((storage_root / "Cloudflare" / "여행과-기록") / "travel-post.png")

    channel = _create_channel(db, local_root=local_root)
    _create_post(
        db,
        channel=channel,
        slug="travel-post",
        category_slug="여행과-기록",
        thumbnail_url="https://api.dongriarchive.com/assets/media/posts/2026/04/travel-post/travel-post.webp",
    )

    result = rebuild_service.rebuild_cloudflare_assets(
        db,
        mode="dry_run",
        source_scope="cloudflare_only_root_pool",
    )

    assert result["candidate_count"] == 1
    assert result["matched_count"] == 1
    assert result["items"][0]["resolved_local_source"].endswith("travel-post.png")


def test_select_matches_accepts_slug_similarity_gap_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    post = {
        "remote_post_id": "remote-1",
        "slug": "travel-post",
        "title": "Travel Post",
        "category_slug": "여행과-기록",
        "legacy_url_scheme": "legacy_media_posts",
        "row": object(),
    }
    ranked = [
        {
            "path": "a.png",
            "score": 88.0,
            "match_source": "slug_similarity",
            "reason": "slug_similarity",
            "role": "hero",
            "source_kind": "storage_pool",
        },
        {
            "path": "b.png",
            "score": 82.0,
            "match_source": "slug_similarity",
            "reason": "slug_similarity",
            "role": "hero",
            "source_kind": "storage_pool",
        },
    ]
    monkeypatch.setattr(rebuild_service, "_rank_candidates_for_post", lambda *_args, **_kwargs: ranked)

    matched, unresolved = rebuild_service._select_matches(
        [post],
        [],
        use_fallback_heuristic=True,
        source_category_history={},
        stem_category_history={},
        use_legacy_evidence=True,
    )

    assert len(matched) == 1
    assert matched[0]["match_source"] == "slug_similarity_gap"
    assert matched[0]["confidence"] == 88.0
    assert unresolved == []


def test_select_matches_marks_small_gap_as_ambiguous(monkeypatch: pytest.MonkeyPatch) -> None:
    post = {
        "remote_post_id": "remote-1",
        "slug": "travel-post",
        "title": "Travel Post",
        "category_slug": "여행과-기록",
        "legacy_url_scheme": "legacy_media_posts",
        "row": object(),
    }
    ranked = [
        {
            "path": "a.png",
            "score": 88.0,
            "match_source": "slug_similarity",
            "reason": "slug_similarity",
            "role": "hero",
            "source_kind": "storage_pool",
        },
        {
            "path": "b.png",
            "score": 84.5,
            "match_source": "slug_similarity",
            "reason": "slug_similarity",
            "role": "hero",
            "source_kind": "storage_pool",
        },
    ]
    monkeypatch.setattr(rebuild_service, "_rank_candidates_for_post", lambda *_args, **_kwargs: ranked)

    matched, unresolved = rebuild_service._select_matches(
        [post],
        [],
        use_fallback_heuristic=True,
        source_category_history={},
        stem_category_history={},
        use_legacy_evidence=True,
    )

    assert matched == []
    assert len(unresolved) == 1
    assert unresolved[0]["reason"] == "ambiguous_match"
