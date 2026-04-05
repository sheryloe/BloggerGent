from __future__ import annotations

from types import SimpleNamespace

from app.models.entities import PostStatus
from app.tasks import pipeline


def test_format_planner_brief_for_prompt_includes_bundle_and_guardrails() -> None:
    rendered = pipeline._format_planner_brief_for_prompt(
        {
            "topic": "Seoul spring river walk",
            "audience": "first-time travelers",
            "information_level": "practical",
            "category_name": "Travel",
            "bundle_key": "seoul-river-walk-2026-04-08",
            "facts": ["night shuttle available", "weekday crowd lower"],
            "prohibited_claims": ["guaranteed entry"],
            "context_notes": "double-check official notices",
        }
    )

    assert "Bundle key: seoul-river-walk-2026-04-08" in rendered
    assert "Confirmed facts:" in rendered
    assert "Prohibited claims:" in rendered
    assert "double-check official notices" in rendered


def test_build_bundle_language_url_map_requires_published_or_scheduled() -> None:
    article_en = SimpleNamespace(
        blog=SimpleNamespace(
            blogger_url="https://donggri-korea.blogspot.com/",
            slug="donggri-korea",
            name="EN",
            primary_language="en",
        ),
        blogger_post=SimpleNamespace(
            post_status=PostStatus.PUBLISHED,
            published_url="https://donggri-korea.blogspot.com/2026/04/en.html",
        ),
    )
    article_ja_draft = SimpleNamespace(
        blog=SimpleNamespace(
            blogger_url="https://donggri-kankoku.blogspot.com/",
            slug="donggri-kankoku",
            name="JA",
            primary_language="ja",
        ),
        blogger_post=SimpleNamespace(
            post_status=PostStatus.DRAFT,
            published_url="https://donggri-kankoku.blogspot.com/2026/04/ja.html",
        ),
    )
    article_es = SimpleNamespace(
        blog=SimpleNamespace(
            blogger_url="https://donggri-corea.blogspot.com/",
            slug="donggri-corea",
            name="ES",
            primary_language="es",
        ),
        blogger_post=SimpleNamespace(
            post_status=PostStatus.SCHEDULED,
            published_url="https://donggri-corea.blogspot.com/2026/04/es.html",
        ),
    )

    url_map = pipeline._build_bundle_language_url_map([article_en, article_ja_draft, article_es])

    assert url_map == {
        "en": "https://donggri-korea.blogspot.com/2026/04/en.html",
        "es": "https://donggri-corea.blogspot.com/2026/04/es.html",
    }
