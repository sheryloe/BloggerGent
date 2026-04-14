from __future__ import annotations

from types import SimpleNamespace

from app.services.content.multilingual_bundle_service import (
    build_language_switch_block,
    parse_planner_bundle_context,
    resolve_blog_bundle_language,
)


def test_resolve_blog_bundle_language_from_blogger_host() -> None:
    blog = SimpleNamespace(
        blogger_url="https://donggri-kankoku.blogspot.com/",
        slug="anything",
        name="Anything",
        primary_language="en",
    )
    assert resolve_blog_bundle_language(blog) == "ja"


def test_parse_planner_bundle_context_from_line_text() -> None:
    payload = parse_planner_bundle_context(
        """
bundle_key: april-08-jeju-night-walk
facts: shuttle starts from Jeju City Hall; event zone opens after sunset
prohibited_claims: guaranteed entry; fixed ticket price
notes: avoid absolute claims until official notice is confirmed
""".strip()
    )

    assert payload.bundle_key == "april-08-jeju-night-walk"
    assert payload.facts == ["shuttle starts from Jeju City Hall", "event zone opens after sunset"]
    assert payload.prohibited_claims == ["guaranteed entry", "fixed ticket price"]
    assert "avoid absolute claims" in payload.notes


def test_build_language_switch_block_marks_current_language() -> None:
    block = build_language_switch_block(
        current_language="es",
        urls_by_language={
            "en": "https://donggri-korea.blogspot.com/2026/04/sample.html",
            "ja": "https://donggri-kankoku.blogspot.com/2026/04/sample.html",
            "es": "https://donggri-corea.blogspot.com/2026/04/sample.html",
        },
    )

    assert "Lee esta gu" in block
    assert "English" in block
    assert "日本語" in block
    assert "Español (Página actual)" in block
