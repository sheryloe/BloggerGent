from __future__ import annotations

from app.services.cloudflare.cloudflare_persona_service import (
    FORBIDDEN_PERSONA_FIELD_KEYS,
    build_persona_prompt_block,
    default_cloudflare_persona_pack_payload,
    score_persona_fit,
)
from app.models.entities import CloudflareCategoryPersonaPack


def test_default_persona_pack_keeps_pilot_active_and_safe_profiles() -> None:
    payload = default_cloudflare_persona_pack_payload(
        {"slug": "yeohaenggwa-girog", "id": "yeohaenggwa-girog", "name": "여행과 기록"}
    )

    assert payload["pack_key"] == "travel-practical-local-v1"
    assert payload["is_active"] is True
    assert payload["is_default"] is True
    assert payload["attribution"] == "NVIDIA Nemotron-Personas-Korea, CC BY 4.0"
    profile_keys = set().union(*(profile.keys() for profile in payload["sanitized_profiles"]))
    assert profile_keys.isdisjoint(FORBIDDEN_PERSONA_FIELD_KEYS)


def test_persona_prompt_block_preserves_category_pattern_rules() -> None:
    pack = CloudflareCategoryPersonaPack(
        managed_channel_id=1,
        category_slug="yeohaenggwa-girog",
        pack_key="travel-practical-local-v1",
        display_name="현장형 한국 로컬 가이드",
        primary_reader="방문 여부를 판단하려는 독자",
        reader_problem="동선과 혼잡을 알고 싶다",
        tone_summary="실용적",
        trust_style="확인 가능한 정보",
        topic_guidance=["동선", "교통"],
        title_rules={"preferred_frames": ["장소+상황"], "banned_frames": ["과장형"]},
        ctr_rules={"allowed_hooks": ["시간 절약"], "forbidden_hooks": ["낚시성"]},
        category_emphasis=["시간대", "예산"],
        version=1,
        is_active=True,
        is_default=True,
    )

    block = build_persona_prompt_block(pack, stage="article_generation")

    assert "Persona must not change category scope" in block
    assert "allowed_article_patterns" in block
    assert "article_pattern_id" in block
    assert "Do not mention dataset" in block


def test_persona_fit_score_penalizes_sensitive_or_hype_terms() -> None:
    pack = CloudflareCategoryPersonaPack(
        managed_channel_id=1,
        category_slug="yeohaenggwa-girog",
        pack_key="travel-practical-local-v1",
        display_name="현장형 한국 로컬 가이드",
        primary_reader="방문 여부를 판단하려는 독자",
        reader_problem="동선과 혼잡을 알고 싶다",
        tone_summary="실용적",
        trust_style="확인 가능한 정보",
        topic_guidance=["동선", "교통", "예산"],
        title_rules={},
        ctr_rules={},
        category_emphasis=["시간대", "예산"],
        version=1,
        is_active=True,
        is_default=True,
    )

    clean = score_persona_fit(
        pack,
        title="서울 전시 방문 동선과 시간대 체크",
        body_html="<h2>핵심 요약</h2><p>방문 시간, 예산, 이동 동선, 예약 기준을 비교합니다.</p>",
        excerpt="동선과 혼잡 기준",
        labels=["여행"],
        article_pattern_id="travel-01-hidden-path-route",
    )
    risky = score_persona_fit(
        pack,
        title="무조건 가야 하는 충격 필수 코스",
        body_html="<p>남성 여성 나이 출신 학력 기준으로 반드시 추천합니다.</p>",
        excerpt="",
        labels=[],
        article_pattern_id=None,
    )

    assert clean["score"] is not None
    assert risky["score"] is not None
    assert clean["score"] > risky["score"]
