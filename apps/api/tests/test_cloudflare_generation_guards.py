from datetime import datetime, timezone
from types import SimpleNamespace

from app.services import cloudflare_channel_service as cloudflare_service
from app.services.cloudflare.cloudflare_channel_service import (
    _build_cloudflare_render_metadata,
    _default_prompt_for_stage,
    _is_blossom_topic_keyword,
    _quality_gate_fail_reasons,
    _resolve_cloudflare_requested_models,
    _sanitize_cloudflare_public_body,
    _would_exceed_blossom_cap,
)
from app.services.providers.base import RuntimeProviderConfig


def test_cloudflare_quality_gate_fail_reasons() -> None:
    reasons = _quality_gate_fail_reasons(
        similarity_score=75.0,
        seo_score=58.0,
        geo_score=55.0,
        ctr_score=59.0,
        similarity_threshold=70.0,
        min_seo_score=60.0,
        min_geo_score=60.0,
        min_ctr_score=60.0,
    )
    assert reasons == ["similarity_threshold", "seo_below_min", "geo_below_min", "ctr_below_min"]


def test_sanitize_cloudflare_public_body_removes_trace_leaks_and_appends_closing_record() -> None:
    cleaned = _sanitize_cloudflare_public_body(
        "<p><strong>Quick brief.</strong> internal note</p><h2>본문</h2><p>현장 내용</p>",
        category_slug="여행과-기록",
        title="서울 산책",
    )

    assert "Quick brief" not in cleaned
    assert "internal note" not in cleaned
    assert "<h2>마무리 기록</h2>" in cleaned


def test_default_prompt_for_stage_prefers_channel_prompt_files() -> None:
    prompt = _default_prompt_for_stage(
        {
            "id": "cat-donggri-travel",
            "slug": "여행과-기록",
            "name": "여행과 기록",
            "description": "여행 동선, 장소 기록, 현장 팁을 다루는 카테고리",
        },
        "article_generation",
    )

    assert "This category is only for actual places" in prompt
    assert "마무리 기록" in prompt


def test_build_cloudflare_render_metadata_uses_hamni_viewpoint() -> None:
    article_output = SimpleNamespace(
        series_variant="us-stock-dialogue-v1",
        company_name="IonQ",
        ticker="IONQ",
        exchange="NYSE",
        chart_provider="tradingview",
        chart_symbol="NYSE:IONQ",
        chart_interval="1D",
        slide_sections=[],
    )

    metadata = _build_cloudflare_render_metadata(
        article_output=article_output,
        planner_brief={},
        title="아이온큐 흐름 점검",
    )

    assert metadata["viewpoints"] == ["동그리", "햄니"]


def test_cloudflare_blossom_cap_allows_bootstrap_pick() -> None:
    counter = {"total_topics": 0, "blossom_topics": 0}
    assert _would_exceed_blossom_cap(counter=counter, is_blossom=True, cap_ratio=0.2) is False


def test_cloudflare_blossom_cap_ratio_boundary() -> None:
    counter = {"total_topics": 4, "blossom_topics": 0}
    assert _would_exceed_blossom_cap(counter=counter, is_blossom=True, cap_ratio=0.2) is False
    counter = {"total_topics": 4, "blossom_topics": 1}
    assert _would_exceed_blossom_cap(counter=counter, is_blossom=True, cap_ratio=0.2) is True


def test_cloudflare_blossom_keyword_detection_supports_korean_variants() -> None:
    assert _is_blossom_topic_keyword("왕벚꽃 개화 시기와 산책 코스") is True
    assert _is_blossom_topic_keyword("겹벚꽃 사진 명소 정리") is True


def test_cloudflare_topic_provider_order_keeps_standard_provider_for_regular_generation() -> None:
    runtime = RuntimeProviderConfig(
        provider_mode="live",
        openai_api_key="test-openai",
        openai_text_model="gpt-4.1-mini",
        openai_image_model="gpt-image-1",
        topic_discovery_provider="gemini",
        topic_discovery_model="gpt-4.1-mini",
        gemini_api_key="test-gemini",
        gemini_model="gemini-2.5-flash",
        blogger_access_token="",
        default_publish_mode="draft",
    )

    assert cloudflare_service._build_cloudflare_topic_provider_order(runtime) == ["gemini"]


def test_cloudflare_topic_provider_switches_on_repeated_category_mismatch() -> None:
    should_switch = cloudflare_service._should_switch_cloudflare_topic_provider(
        current_provider_hint="gemini",
        fallback_provider_hint="openai",
        selected_on_attempt=0,
        discovered_topics=[{"keyword": "The Mary Celeste unsolved mystery"}],
        attempt_reject_breakdown={"category_mismatch": 3},
        consecutive_category_mismatch_attempts=2,
    )

    assert should_switch is True


def test_cloudflare_topic_template_switches_to_default_after_repeated_mismatch() -> None:
    should_switch = cloudflare_service._should_switch_cloudflare_topic_template(
        current_topic_prompt_template="welfare prompt",
        default_topic_prompt_template="productivity prompt",
        selected_on_attempt=0,
        discovered_topics=[{"keyword": "Government subsidy application guide for first-time households"}],
        attempt_reject_breakdown={"category_mismatch": 3},
        consecutive_category_mismatch_attempts=2,
    )

    assert should_switch is True


def test_cloudflare_quality_gate_relaxes_geo_threshold_for_dev_category() -> None:
    thresholds = cloudflare_service._effective_quality_thresholds_for_category(
        "개발과-프로그래밍",
        {
            "enabled": 1.0,
            "similarity_threshold": 70.0,
            "min_seo_score": 60.0,
            "min_geo_score": 60.0,
        },
    )

    assert thresholds["min_geo_score"] == 40.0


def test_cloudflare_requested_models_use_large_for_prompt_stage() -> None:
    runtime = RuntimeProviderConfig(
        provider_mode="live",
        openai_api_key="test-openai",
        openai_text_model="gpt-4.1-mini",
        openai_image_model="gpt-image-1",
        topic_discovery_provider="openai",
        topic_discovery_model="gpt-4.1",
        gemini_api_key="",
        gemini_model="gemini-2.5-flash",
        blogger_access_token="",
        default_publish_mode="draft",
    )

    topic_model, article_model, prompt_model = _resolve_cloudflare_requested_models(
        settings_map={
            "article_generation_model": "gpt-5.4",
            "topic_discovery_model": "gpt-4.1",
            "openai_text_model": "gpt-4.1-mini",
        },
        runtime=runtime,
    )

    assert topic_model == "gpt-5.4"
    assert article_model == "gpt-5.4"
    assert prompt_model == "gpt-5.4"


def test_cloudflare_requested_models_fallback_to_topic_model_when_article_missing() -> None:
    runtime = RuntimeProviderConfig(
        provider_mode="live",
        openai_api_key="test-openai",
        openai_text_model="gpt-4.1-mini",
        openai_image_model="gpt-image-1",
        topic_discovery_provider="openai",
        topic_discovery_model="gpt-4.1",
        gemini_api_key="",
        gemini_model="gemini-2.5-flash",
        blogger_access_token="",
        default_publish_mode="draft",
    )

    topic_model, article_model, prompt_model = _resolve_cloudflare_requested_models(
        settings_map={
            "article_generation_model": "",
            "topic_discovery_model": "gpt-4.1",
            "openai_text_model": "gpt-4.1-mini",
        },
        runtime=runtime,
    )

    assert topic_model == "gpt-4.1"
    assert article_model == "gpt-4.1"
    assert prompt_model == "gpt-4.1"


def test_cloudflare_generation_keeps_standard_topic_provider_even_when_openai_key_exists() -> None:
    runtime = RuntimeProviderConfig(
        provider_mode="live",
        openai_api_key="test-openai",
        openai_text_model="gpt-4.1-mini",
        openai_image_model="gpt-image-1",
        topic_discovery_provider="gemini",
        topic_discovery_model="gpt-4.1",
        gemini_api_key="test-gemini",
        gemini_model="gemini-2.5-flash",
        blogger_access_token="",
        default_publish_mode="draft",
    )

    assert cloudflare_service._resolve_cloudflare_topic_provider_order_for_generation(runtime) == ["gemini"]


def test_list_cloudflare_posts_computes_fallback_scores_from_detail(monkeypatch) -> None:
    class _EmptyResult:
        def scalars(self):
            return self

        def all(self):
            return []

    class _FakeDB:
        def execute(self, _stmt):
            return _EmptyResult()

    monkeypatch.setattr(cloudflare_service, "get_settings_map", lambda _db: {"cloudflare_blog_api_base_url": "https://api.example.com"})
    monkeypatch.setattr(
        cloudflare_service,
        "list_cloudflare_categories",
        lambda _db: [{"id": "cat-dev", "slug": "개발과-프로그래밍", "name": "개발과 프로그래밍", "isLeaf": True}],
    )
    monkeypatch.setattr(
        cloudflare_service,
        "_list_remote_posts",
        lambda _values: [
            {
                "id": "post-1",
                "slug": "dev-post",
                "title": "Cursor 자동화 워크플로우 실전 가이드",
                "excerpt": "개발 자동화 실전 정리",
                "publicUrl": "https://dongriarchive.com/ko/post/dev-post",
                "status": "published",
                "category": {"id": "cat-dev", "slug": "개발과-프로그래밍", "name": "개발과 프로그래밍"},
                "tags": [],
            }
        ],
    )
    monkeypatch.setattr(cloudflare_service, "_fetch_remote_site_settings", lambda _values: {"siteTitle": "Dongri Archive"})
    monkeypatch.setattr(cloudflare_service, "_public_site_base_url", lambda _values: "https://dongriarchive.com")
    monkeypatch.setattr(cloudflare_service, "_normalize_base_url", lambda value: str(value or "").strip())
    monkeypatch.setattr(
        cloudflare_service,
        "_fetch_integration_post_detail",
        lambda _db, _remote_id: {
            "id": "post-1",
            "title": "Cursor 자동화 워크플로우 실전 가이드",
            "excerpt": "개발 자동화 실전 정리",
            "content": "<h2>문제</h2><p>이 글은 Cursor 자동화 워크플로우와 실제 설정 단계를 정리합니다.</p>"
            "<h2>설정</h2><h3>도구</h3><p>workflow automation guide</p>"
            "<h2>비교</h2><h3>무료 vs 유료</h3><p>plan checklist source official evidence</p>"
            "<a href='https://dongriarchive.com/ko/post/other'>내부 링크</a>"
            "<a href='/ko/post/another'>관련 글</a>",
        },
    )

    from app.services import content_ops_service

    monkeypatch.setattr(
        content_ops_service,
        "compute_seo_geo_scores",
        lambda **_kwargs: {"seo_score": 81, "geo_score": 84, "ctr_score": 83},
    )

    rows = cloudflare_service.list_cloudflare_posts(_FakeDB())

    assert len(rows) == 1
    assert rows[0]["seo_score"] == 81
    assert rows[0]["geo_score"] == 84
    assert rows[0]["ctr"] == 83


def test_list_cloudflare_posts_merges_scheme_variant_duplicates(monkeypatch) -> None:
    state_row = SimpleNamespace(
        url="https://dongriarchive.com/ko/post/busan-sand-festival-guide",
        index_status="indexed",
        index_coverage_state="submitted_and_indexed",
        last_checked_at=datetime(2026, 4, 7, 4, 0, tzinfo=timezone.utc),
        next_eligible_at=None,
        last_error=None,
        updated_at=datetime(2026, 4, 7, 4, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 4, 7, 4, 0, tzinfo=timezone.utc),
    )

    class _StateResult:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return self

        def all(self):
            return list(self._rows)

    class _FakeDB:
        def execute(self, _stmt):
            return _StateResult([state_row])

    monkeypatch.setattr(cloudflare_service, "get_settings_map", lambda _db: {"cloudflare_blog_api_base_url": "https://api.example.com"})
    monkeypatch.setattr(
        cloudflare_service,
        "list_cloudflare_categories",
        lambda _db: [{"id": "cat-dev", "slug": "dev-tools", "name": "Dev Tools", "isLeaf": True}],
    )
    monkeypatch.setattr(
        cloudflare_service,
        "_list_remote_posts",
        lambda _values: [
            {
                "id": "post-a",
                "slug": "busan-sand-festival-guide",
                "title": "2026 Busan Haeundae Sand Festival Guide",
                "excerpt": "Error payload with missing quality",
                "publicUrl": "http://dongriarchive.com/ko/post/busan-sand-festival-guide?utm_source=x",
                "status": "error",
                "seoScore": 88,
                "geoScore": 77,
                "category": {"id": "cat-dev", "slug": "dev-tools", "name": "Dev Tools"},
                "tags": [{"name": "festival"}],
                "createdAt": "2026-04-07T01:00:00Z",
                "updatedAt": "2026-04-07T02:00:00Z",
                "publishedAt": "2026-04-07T02:00:00Z",
            },
            {
                "id": "post-b",
                "slug": "busan-sand-festival-guide",
                "title": "2026 Busan Haeundae Sand Festival Guide",
                "excerpt": "Published payload",
                "publicUrl": "https://dongriarchive.com/ko/post/busan-sand-festival-guide",
                "status": "published",
                "lighthouseScore": 82,
                "category": {"id": "cat-dev", "slug": "dev-tools", "name": "Dev Tools"},
                "tags": [{"name": "travel"}],
                "createdAt": "2026-04-07T01:30:00Z",
                "updatedAt": "2026-04-07T03:00:00Z",
                "publishedAt": "2026-04-07T03:00:00Z",
            },
        ],
    )
    monkeypatch.setattr(cloudflare_service, "_fetch_remote_site_settings", lambda _values: {"siteTitle": "Dongri Archive"})
    monkeypatch.setattr(cloudflare_service, "_public_site_base_url", lambda _values: "https://dongriarchive.com")
    monkeypatch.setattr(cloudflare_service, "_normalize_base_url", lambda value: str(value or "").strip())

    rows = cloudflare_service.list_cloudflare_posts(_FakeDB())

    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "published"
    assert row["published_url"] == "https://dongriarchive.com/ko/post/busan-sand-festival-guide"
    assert row["seo_score"] == 88
    assert row["geo_score"] == 77
    assert row["lighthouse_score"] == 82
    assert row["index_status"] == "indexed"
    assert row["index_coverage_state"] == "submitted_and_indexed"
    assert row["labels"] == ["travel", "festival"]
