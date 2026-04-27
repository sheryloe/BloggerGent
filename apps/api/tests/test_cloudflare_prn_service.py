from __future__ import annotations

from app.models.entities import CloudflareCategoryPersonaPack
from app.services.cloudflare.cloudflare_prn_service import (
    build_prn_prompt_block,
    preview_cloudflare_prn_titles,
    rerank_prn_after_article,
    score_prn_title_candidate,
)


def _pack() -> CloudflareCategoryPersonaPack:
    return CloudflareCategoryPersonaPack(
        managed_channel_id=1,
        category_slug="gaebalgwa-peurogeuraeming",
        pack_key="dev-operator-automation-v1",
        display_name="실무 자동화 운영자",
        primary_reader="AI 도구를 팀 운영 기준으로 판단해야 하는 개발 리더",
        reader_problem="도구 도입이 팀 개발 방식과 디버깅 흐름에 미치는 영향을 알고 싶다",
        tone_summary="실무 메모와 편집자 해설",
        trust_style="공식 문서와 릴리스 노트 기반",
        topic_guidance=["MCP", "에이전트", "IDE", "CLI", "배포 자동화", "관측성", "디버깅"],
        title_rules={
            "preferred_frames": ["주제+연도+실무 결과", "문제+체크리스트/가이드/플레이북"],
            "banned_frames": ["입문 튜토리얼", "근거 없는 생산성 찬양"],
        },
        ctr_rules={
            "allowed_hooks": ["팀 운영 영향", "비용", "디버깅", "도입 체크리스트"],
            "forbidden_hooks": ["충격", "무조건", "최고"],
        },
        category_emphasis=["팀 운영 영향", "비용", "디버깅 가능성", "도입 체크리스트"],
        sanitized_profiles=[],
        attribution="NVIDIA Nemotron-Personas-Korea, CC BY 4.0",
        version=1,
        is_active=True,
        is_default=True,
    )


def test_prn_preview_generates_distinct_title_candidates() -> None:
    preview = preview_cloudflare_prn_titles(
        keyword="IDE/CLI 워크플로 변화 총정리",
        category_slug="gaebalgwa-peurogeuraeming",
        category_name="개발과 프로그래밍",
        persona_pack=_pack(),
        article_pattern_id="dev-insider-field-guide",
        article_pattern_version=3,
        existing_titles=[],
    )

    assert preview["enabled"] is True
    assert preview["selected_title"]
    assert len(preview["candidates"]) >= 4
    assert len({item["title"] for item in preview["candidates"]}) == len(preview["candidates"])
    assert preview["selected_score"] >= 70


def test_prn_rejects_clickbait_and_duplicate_titles() -> None:
    result = score_prn_title_candidate(
        title="IDE/CLI 워크플로 충격 최고 비밀",
        keyword="IDE/CLI 워크플로",
        category_slug="gaebalgwa-peurogeuraeming",
        persona_pack=_pack(),
        article_pattern_id="dev-insider-field-guide",
        article_pattern_version=3,
        existing_titles=["IDE/CLI 워크플로 충격 최고 비밀"],
        rank=1,
    )

    assert result["decision"] == "reject"
    assert "banned_hook" in result["rejection_reason"]
    assert result["forbidden_hygiene"] < 70


def test_prn_prompt_block_locks_pattern_and_keeps_faq_optional() -> None:
    preview = preview_cloudflare_prn_titles(
        keyword="OpenAI API 비용 모니터링",
        category_slug="gaebalgwa-peurogeuraeming",
        category_name="개발과 프로그래밍",
        persona_pack=_pack(),
        article_pattern_id="dev-insider-field-guide",
        article_pattern_version=3,
        existing_titles=[],
    )
    block = build_prn_prompt_block(preview)

    assert "PRN" in block
    assert "Locked pattern id: dev-insider-field-guide" in block
    assert "FAQ optional" in block


def test_prn_rerank_keeps_public_payload_sanitized() -> None:
    preview = preview_cloudflare_prn_titles(
        keyword="MCP 에이전트 도입",
        category_slug="gaebalgwa-peurogeuraeming",
        category_name="개발과 프로그래밍",
        persona_pack=_pack(),
        article_pattern_id="dev-insider-field-guide",
        article_pattern_version=3,
        existing_titles=[],
    )
    reranked = rerank_prn_after_article(
        preview,
        article_title="MCP 에이전트 도입 가이드 2026 | 팀 운영 기준부터 디버깅까지",
        article_excerpt="팀 운영, 비용, 디버깅 기준을 함께 정리합니다.",
        article_body="실무 운영 체크리스트와 디버깅 기준, 배포 자동화 판단 기준을 포함합니다.",
        persona_fit_score=86,
        quality_gate={"scores": {"ctr_score": 84}},
    )

    assert reranked["selected_title"]
    assert reranked["selected_score"] >= preview["selected_score"]
    serialized = str(reranked)
    for forbidden in ("exact_age", "gender", "district", "religion", "politics"):
        assert forbidden not in serialized
