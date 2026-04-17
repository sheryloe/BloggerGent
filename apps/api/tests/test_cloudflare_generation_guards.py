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
        title="봄 여행 정리",
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

    assert "[Category delta]" in prompt
    assert "Build the article around one real place" in prompt


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
        title="아이온큐 흐름 정리",
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
    assert _is_blossom_topic_keyword("경복궁 벚꽃 개화 시기 정리 코스") is True
    assert _is_blossom_topic_keyword("서울 벚꽃 사진 명소 정리") is True


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


def test_cloudflare_requested_models_keep_stage_specific_defaults() -> None:
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
            "image_prompt_generation_model": "gpt-5.4-mini-2026-03-17",
            "topic_discovery_model": "gpt-4.1",
            "openai_text_model": "gpt-4.1-mini",
        },
        runtime=runtime,
    )

    assert topic_model == "gpt-4.1"
    assert article_model == "gpt-5.4"
    assert prompt_model == "gpt-5.4-mini-2026-03-17"


def test_cloudflare_requested_models_fallback_to_small_default_when_article_missing() -> None:
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
    assert article_model == "gpt-5.4-mini-2026-03-17"
    assert prompt_model == "gpt-5.4-mini-2026-03-17"
