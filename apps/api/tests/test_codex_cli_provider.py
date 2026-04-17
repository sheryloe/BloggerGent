from __future__ import annotations

import json

from app.services.providers import codex_cli
from app.services.providers.base import RuntimeProviderConfig


def _runtime() -> RuntimeProviderConfig:
    return RuntimeProviderConfig(
        provider_mode="live",
        openai_api_key="",
        openai_text_model="gpt-4.1-2025-04-14",
        openai_image_model="gpt-image-1",
        topic_discovery_provider="openai",
        topic_discovery_model="gpt-4.1-2025-04-14",
        gemini_api_key="",
        gemini_model="gemini-2.5-flash",
        blogger_access_token="",
        default_publish_mode="draft",
        text_runtime_kind="codex_cli",
        text_runtime_model="gpt-5.4",
        image_runtime_kind="openai_image",
        codex_job_timeout_seconds=900,
    )


def test_generate_article_uses_inline_codex_execution(monkeypatch) -> None:
    captured: dict = {}

    def _fake_submit_codex_text_job(**kwargs):
        captured.update(kwargs)
        return {
            "content": json.dumps(
                {
                    "title": "Cloudflare SEO 리팩토링 체크리스트 완성 가이드",
                    "meta_description": "기존 Cloudflare 게시글을 같은 주제로 다시 정리할 때 SEO와 CTR을 함께 끌어올리는 실전 리팩토링 방법을 정리합니다.",
                    "labels": ["cloudflare", "seo"],
                    "slug": "cloudflare-seo-refactor-guide",
                    "excerpt": "기존 글의 주제를 유지하면서 구조와 문장을 정리해 검색 성과를 끌어올리는 흐름을 설명합니다.",
                    "html_article": (
                        "<section><h2>도입</h2><p>기존 글의 주제를 유지한 채 구조를 다시 정리하는 방법을 설명합니다. "
                        "검색 의도와 클릭 기대를 맞추는 문장 재구성이 핵심입니다. 문단의 시작은 문제를 명확히 제시하고, "
                        "중간은 실행 순서와 선택 기준을 짧은 문장으로 정리합니다.</p>"
                        "<p>이 문서는 리팩토링 흐름, 문단 구조, FAQ 위치, HTML 출력 제약까지 포함해 실제 게시 전 단계에서 "
                        "바로 사용할 수 있게 구성합니다. 마지막에는 적용 후 검증 항목과 실패 시 복구 포인트까지 함께 제시합니다.</p></section>"
                    ),
                    "faq_section": [],
                    "image_collage_prompt": "Keep existing post images and do not create new assets. Focus on the article rewrite only.",
                    "article_pattern_id": "refactor-seo",
                    "article_pattern_version": 1,
                }
            )
        }

    monkeypatch.setattr(codex_cli, "submit_codex_text_job", _fake_submit_codex_text_job)

    provider = codex_cli.CodexCLITextProvider(runtime=_runtime(), model="gpt-5.4")
    payload, _response = provider.generate_article("cloudflare seo", "rewrite prompt")

    assert payload.slug == "cloudflare-seo-refactor-guide"
    assert captured["inline"] is True
    assert captured["response_kind"] == "json_schema"


def test_discover_topics_uses_inline_codex_execution(monkeypatch) -> None:
    captured: dict = {}

    def _fake_submit_codex_text_job(**kwargs):
        captured.update(kwargs)
        return {
            "content": json.dumps(
                {
                    "topics": [
                        {
                            "keyword": "cloudflare seo 리팩토링",
                            "reason": "기존 게시글 개선 수요가 높음",
                            "trend_score": 84.0,
                        }
                    ]
                }
            )
        }

    monkeypatch.setattr(codex_cli, "submit_codex_text_job", _fake_submit_codex_text_job)

    provider = codex_cli.CodexCLITextProvider(runtime=_runtime(), model="gpt-5.4")
    payload, _response = provider.discover_topics("topic prompt")

    assert payload.topics[0].keyword == "cloudflare seo 리팩토링"
    assert captured["inline"] is True
    assert captured["response_kind"] == "json_schema"
