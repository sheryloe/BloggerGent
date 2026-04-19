from __future__ import annotations

from types import SimpleNamespace

from app.services import cloudflare_channel_service as cloudflare_service
from app.tasks import pipeline


def test_blogger_trust_guard_applies_to_travel_profile() -> None:
    blog = SimpleNamespace(profile_key="korea_travel", content_category="travel")
    rendered = pipeline._append_blogger_seo_trust_guard("BASE", blog=blog, current_date="2026-04-04")

    assert rendered.startswith("BASE")
    assert "[SEO trust + source integrity guard]" in rendered
    assert 'As of 2026-04-04' in rendered
    assert "confirmed facts" in rendered
    assert "No verified source URL yet" not in rendered


def test_blogger_trust_guard_applies_to_mystery_profile() -> None:
    blog = SimpleNamespace(profile_key="world_mystery", content_category="mystery")
    rendered = pipeline._append_blogger_seo_trust_guard("BASE", blog=blog, current_date="2026-04-04")

    assert "[SEO trust + source integrity guard]" in rendered
    assert "fiction context" in rendered


def test_blogger_trust_guard_skips_other_profiles() -> None:
    blog = SimpleNamespace(profile_key="general", content_category="general")
    rendered = pipeline._append_blogger_seo_trust_guard("BASE", blog=blog, current_date="2026-04-04")
    assert rendered == "BASE"


def test_cloudflare_trust_guard_adds_base_rules() -> None:
    rendered = cloudflare_service._append_cloudflare_seo_trust_guard(
        "BASE",
        category_slug="문화와-공간",
        current_date="2026-04-04",
    )

    assert rendered.startswith("BASE")
    assert "[SEO trust + source integrity guard]" in rendered
    assert "target date 2026-04-04 (Asia/Seoul)" in rendered
    assert "concrete entities, dates, places, and reader actions" in rendered


def test_cloudflare_trust_guard_adds_analysis_rule_for_thought_category() -> None:
    rendered = cloudflare_service._append_cloudflare_seo_trust_guard(
        "BASE",
        category_slug="동그리의-생각",
        current_date="2026-04-04",
    )

    assert "possibilities, not certainties" in rendered
