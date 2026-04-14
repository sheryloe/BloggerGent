from app.services import cloudflare_performance_service


def test_cloudflare_performance_page_filters_and_summarizes(monkeypatch) -> None:
    rows = [
        {
            "channel_id": "dongriarchive",
            "channel_name": "Dongri Archive",
            "canonical_category_slug": "dev-programming",
            "canonical_category_name": "Development and Programming",
            "category_slug": "dev-programming",
            "category_name": "Development and Programming",
            "title": "Codex Refactor Field Notes",
            "published_url": "https://archive.example.dev/dev-1",
            "published_at": "2026-04-10T02:00:00+09:00",
            "seo_score": 91.0,
            "geo_score": 68.0,
            "ctr": 83.0,
            "lighthouse_score": 79.0,
            "index_status": "indexed",
            "live_image_count": 2,
            "live_webp_count": 2,
            "live_png_count": 0,
            "live_other_image_count": 0,
            "live_image_issue": None,
            "live_image_audited_at": "2026-04-10T02:10:00+09:00",
            "article_pattern_id": "problem-solution",
            "article_pattern_version": 1,
            "status": "published",
            "quality_status": "warning",
        },
        {
            "channel_id": "dongriarchive",
            "channel_name": "Dongri Archive",
            "canonical_category_slug": "travel-notes",
            "canonical_category_name": "Travel Notes",
            "category_slug": "travel-notes",
            "category_name": "Travel Notes",
            "title": "Busan Coastal Walk Route",
            "published_url": "https://archive.example.dev/travel-1",
            "published_at": "2026-04-10T03:00:00+09:00",
            "seo_score": 92.0,
            "geo_score": 90.0,
            "ctr": 86.0,
            "lighthouse_score": 88.0,
            "index_status": "submitted",
            "live_image_count": 2,
            "live_webp_count": 1,
            "live_png_count": 1,
            "live_other_image_count": 0,
            "live_image_issue": None,
            "live_image_audited_at": "2026-04-10T03:10:00+09:00",
            "article_pattern_id": "experience-diary",
            "article_pattern_version": 1,
            "status": "published",
            "quality_status": "ok",
        },
    ]
    monkeypatch.setattr(cloudflare_performance_service, "list_synced_cloudflare_posts", lambda _db, include_non_published=True: rows)

    summary = cloudflare_performance_service.get_cloudflare_performance_summary(object(), month="2026-04")
    page = cloudflare_performance_service.get_cloudflare_performance_page(
        object(),
        month="2026-04",
        category="dev-programming",
        low_score_only=True,
        page=1,
        page_size=20,
    )

    assert summary["total"] == 2
    assert summary["low_score_count"] == 1
    assert summary["refactor_candidate_count"] == 1
    assert summary["lighthouse_below_70_count"] == 0
    assert len(summary["available_categories"]) == 2

    assert page["total"] == 1
    assert page["items"][0]["category_slug"] == "dev-programming"
    assert page["items"][0]["live_webp_count"] == 2
    assert page["items"][0]["live_png_count"] == 0
    assert page["items"][0]["article_pattern_id"] == "problem-solution"
    assert page["items"][0]["refactor_candidate"] is True
