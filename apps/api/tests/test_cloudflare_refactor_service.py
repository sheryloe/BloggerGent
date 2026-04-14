import inspect

import pytest

from app.services import cloudflare_refactor_service


def test_refactor_cloudflare_low_score_posts_dry_run_filters_candidates(monkeypatch) -> None:
    rows = [
        {
            "remote_id": "post-1",
            "canonical_category_slug": "dev",
            "canonical_category_name": "Development",
            "category_slug": "dev",
            "category_name": "Development",
            "title": "Codex Workflow Rewrite",
            "published_url": "https://archive.example.dev/dev-1",
            "published_at": "2026-04-10T02:00:00+09:00",
            "seo_score": 79.0,
            "geo_score": 85.0,
            "ctr": 88.0,
            "lighthouse_score": 91.0,
            "article_pattern_id": "problem-solution",
            "article_pattern_version": 1,
            "status": "published",
        },
        {
            "remote_id": "post-2",
            "canonical_category_slug": "travel",
            "canonical_category_name": "Travel",
            "category_slug": "travel",
            "category_name": "Travel",
            "title": "Busan Walk Memo",
            "published_url": "https://archive.example.dev/travel-1",
            "published_at": "2026-04-10T03:00:00+09:00",
            "seo_score": 92.0,
            "geo_score": 90.0,
            "ctr": 86.0,
            "lighthouse_score": 84.0,
            "article_pattern_id": "experience-diary",
            "article_pattern_version": 1,
            "status": "published",
        },
        {
            "remote_id": "post-3",
            "canonical_category_slug": "dev",
            "canonical_category_name": "Development",
            "category_slug": "dev",
            "category_name": "Development",
            "title": "Old March Post",
            "published_url": "https://archive.example.dev/dev-2",
            "published_at": "2026-03-28T02:00:00+09:00",
            "seo_score": 60.0,
            "geo_score": 60.0,
            "ctr": 60.0,
            "lighthouse_score": 60.0,
            "article_pattern_id": "problem-solution",
            "article_pattern_version": 1,
            "status": "published",
        },
    ]

    monkeypatch.setattr(cloudflare_refactor_service, "get_settings_map", lambda _db: {"schedule_timezone": "Asia/Seoul"})
    monkeypatch.setattr(cloudflare_refactor_service, "sync_cloudflare_posts", lambda _db, include_non_published=True: {"status": "ok"})
    monkeypatch.setattr(cloudflare_refactor_service, "list_synced_cloudflare_posts", lambda _db, include_non_published=True: rows)

    result = cloudflare_refactor_service.refactor_cloudflare_low_score_posts(
        object(),
        execute=False,
        threshold=80.0,
        month="2026-04",
        category_slugs=["dev"],
        limit=10,
        sync_before=True,
    )

    assert result["status"] == "ok"
    assert result["total_candidates"] == 1
    assert result["processed_count"] == 1
    assert result["items"][0]["remote_id"] == "post-1"
    assert result["items"][0]["action"] == "dry_run"


def test_refactor_cloudflare_low_score_posts_reports_parallel_workers_when_supported(monkeypatch) -> None:
    service_params = inspect.signature(cloudflare_refactor_service.refactor_cloudflare_low_score_posts).parameters
    if "parallel_workers" not in service_params:
        pytest.skip("Cloudflare refactor parallel_workers is not implemented yet.")

    rows = [
        {
            "remote_id": "post-1",
            "canonical_category_slug": "travel",
            "canonical_category_name": "Travel",
            "category_slug": "travel",
            "category_name": "Travel",
            "title": "Codex Workflow Rewrite",
            "published_url": "https://archive.example.dev/dev-1",
            "published_at": "2026-04-10T02:00:00+09:00",
            "seo_score": 79.0,
            "geo_score": 85.0,
            "ctr": 88.0,
            "lighthouse_score": 91.0,
            "article_pattern_id": "problem-solution",
            "article_pattern_version": 1,
            "status": "published",
        }
    ]

    monkeypatch.setattr(cloudflare_refactor_service, "get_settings_map", lambda _db: {"schedule_timezone": "Asia/Seoul"})
    monkeypatch.setattr(cloudflare_refactor_service, "sync_cloudflare_posts", lambda _db, include_non_published=True: {"status": "ok"})
    monkeypatch.setattr(cloudflare_refactor_service, "list_synced_cloudflare_posts", lambda _db, include_non_published=True: rows)

    result = cloudflare_refactor_service.refactor_cloudflare_low_score_posts(
        object(),
        execute=False,
        threshold=80.0,
        month="2026-04",
        category_slugs=["travel"],
        limit=10,
        sync_before=True,
        parallel_workers=4,
    )

    assert result["status"] == "ok"
    assert result["processed_count"] == 1
    assert result["parallel_workers"] == 4
