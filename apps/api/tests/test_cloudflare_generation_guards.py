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
    adsense_body_token_violations,
    count_korean_syllables_for_body,
    validate_no_adsense_tokens_in_body,
    validate_min_korean_syllables,
)
from app.services.providers.base import RuntimeProviderConfig


def test_cloudflare_quality_gate_fail_reasons() -> None:
    reasons = _quality_gate_fail_reasons(
        similarity_score=75.0,
        seo_score=58.0,
        geo_score=55.0,
        ctr_score=59.0,
        category_slug="여행과-기록",
        similarity_threshold=70.0,
        min_seo_score=60.0,
        min_geo_score=60.0,
        min_ctr_score=60.0,
        korean_syllable_count=1999,
        min_korean_syllable_required=2000,
    )

    assert reasons == [
        "similarity_threshold",
        "seo_below_min",
        "geo_below_min",
        "ctr_below_min",
        "korean_body_below_min",
    ]


def test_count_korean_syllables_for_body_ignores_markup_urls_images_and_non_korean() -> None:
    body = """
    <h2>제목</h2>
    <p>가나다 https://example.com 123 ABC</p>
    ![이미지설명](https://example.com/a.webp)
    ```python
    print("한글")
    ```
    <figure><img alt="숨은한글" /><figcaption>캡션한글</figcaption></figure>
    [링크한글](https://example.com)
    """

    assert count_korean_syllables_for_body(body) == len("제목가나다링크한글")


def test_validate_min_korean_syllables_uses_complete_hangul_syllables_only() -> None:
    assert validate_min_korean_syllables("가" * 2000) is True
    assert validate_min_korean_syllables("가" * 1999 + "abc123ㄱㄴ") is False


def test_validate_no_adsense_tokens_in_body_rejects_raw_adsense_code_and_placeholders() -> None:
    body = """
    <h2>본문</h2>
    <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js"></script>
    <ins class="adsbygoogle" data-ad-client="ca-pub-123" data-ad-slot="456"></ins>
    <!--ADSENSE:inline-1-->
    [AD_SLOT_1]
    광고 위치
    """

    assert validate_no_adsense_tokens_in_body(body) is False
    violations = adsense_body_token_violations(body)
    assert "<script" in violations
    assert "adsbygoogle" in violations
    assert "data-ad-client" in violations
    assert "data-ad-slot" in violations
    assert "ca-pub-" in violations
    assert "googlesyndication" in violations
    assert "<!--adsense" in violations
    assert "[ad_slot" in violations
    assert "광고 위치" in violations


def test_validate_no_adsense_tokens_in_body_allows_pure_article_content() -> None:
    body = "<h2>핵심 요약</h2><p>광고 수익 이야기가 아니라 본문 정책을 설명하는 문장입니다.</p>"

    assert validate_no_adsense_tokens_in_body(body) is True


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

    assert "[minimum_korean_body_gate]" in prompt
    assert "순수 한글 본문 2000글자 이상" in prompt
    assert "[adsense_body_policy]" in prompt
    assert "route-first-story" in prompt


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


def test_build_cloudflare_render_metadata_disables_body_ads_for_daily_memo() -> None:
    article_output = SimpleNamespace(slide_sections=[])

    metadata = _build_cloudflare_render_metadata(
        article_output=article_output,
        planner_brief={},
        title="아침 루틴 기록",
        category_slug="일상과-메모",
        body_markdown="<h2>장면</h2><p>" + ("가" * 2200) + "</p><h2>마무리 기록</h2><p>정리합니다.</p>",
    )

    assert metadata["body_ads"]["enabled"] is False
    assert metadata["body_ads"]["skip_reason"] == "category_policy_disabled"
    assert metadata["body_ads"]["structure"]["h2_count"] == 2


def test_build_cloudflare_render_metadata_disables_body_inline_ads_for_layout_managed_categories() -> None:
    article_output = SimpleNamespace(slide_sections=[])

    metadata = _build_cloudflare_render_metadata(
        article_output=article_output,
        planner_brief={},
        title="developer guide",
        category_slug="\uac1c\ubc1c\uacfc-\ud504\ub85c\uadf8\ub798\ubc0d",
        body_markdown="<h2>summary</h2><p>"
        + ("x" * 1100)
        + "</p><h2>operation</h2><p>"
        + ("x" * 1100)
        + "</p><h2>closing</h2><p>done.</p>",
    )

    assert metadata["body_ads"]["enabled"] is False
    assert metadata["body_ads"]["placements"] == []
    assert metadata["body_ads"]["skip_reason"] == "body_inline_ads_disabled_layout_managed"
    assert metadata["body_ads"]["structure"]["h2_count"] == 3


def test_build_cloudflare_render_metadata_does_not_plan_stock_second_slot_when_layout_managed() -> None:
    article_output = SimpleNamespace(slide_sections=[])
    long_body = "".join(f"<h2>section {idx}</h2><p>{'x' * 850}</p>" for idx in range(1, 6))

    metadata = _build_cloudflare_render_metadata(
        article_output=article_output,
        planner_brief={},
        title="stock market check",
        category_slug="\uc8fc\uc2dd\uc758-\ud750\ub984",
        body_markdown=long_body,
    )

    assert metadata["body_ads"]["enabled"] is False
    assert metadata["body_ads"]["placements"] == []
    assert metadata["body_ads"]["skip_reason"] == "body_inline_ads_disabled_layout_managed"
    assert metadata["body_ads"]["structure"]["h2_count"] == 5


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
