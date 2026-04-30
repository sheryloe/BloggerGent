import pytest

from app.services import article_pattern_service, cloudflare_channel_service


EXPECTED_CLOUDFLARE_ALLOWED_PATTERNS = {
    "개발과-프로그래밍": (
        "dev-info-deep-dive",
        "dev-curation-top-points",
        "dev-insider-field-guide",
        "dev-expert-perspective",
        "dev-experience-synthesis",
    ),
    "일상과-메모": (
        "daily-01-reflective-monologue",
        "daily-02-insight-memo",
        "daily-03-habit-tracker",
        "daily-04-emotional-reflection",
    ),
    "여행과-기록": (
        "route-first-story",
        "spot-focus-review",
        "seasonal-special",
        "logistics-budget",
        "hidden-gem-discovery",
    ),
    "삶을-유용하게": (
        "life-hack-tutorial",
        "benefit-audit-report",
        "efficiency-tool-review",
        "comparison-verdict",
    ),
    "삶의-기름칠": (
        "life-hack-tutorial",
        "benefit-audit-report",
        "efficiency-tool-review",
        "comparison-verdict",
    ),
    "동그리의-생각": (
        "thought-social-context",
        "thought-tech-culture",
        "thought-generation-note",
        "thought-personal-question",
    ),
    "미스테리아-스토리": (
        "case-timeline",
        "evidence-breakdown",
        "legend-context",
        "scene-investigation",
        "scp-dossier",
    ),
    "주식의-흐름": (
        "stock-cartoon-summary",
        "stock-technical-analysis",
        "stock-macro-intelligence",
        "stock-corporate-event-watch",
        "stock-risk-timing",
    ),
    "나스닥의-흐름": (
        "nasdaq-technical-deep-dive",
        "nasdaq-macro-impact",
        "nasdaq-big-tech-whale-watch",
        "nasdaq-hypothesis-scenario",
    ),
    "크립토의-흐름": (
        "crypto-cartoon-summary",
        "crypto-on-chain-analysis",
        "crypto-protocol-deep-dive",
        "crypto-regulatory-macro",
        "crypto-market-sentiment",
    ),
    "축제와-현장": (
        "info-deep-dive",
        "curation-top-points",
        "insider-field-guide",
        "expert-perspective",
        "experience-synthesis",
    ),
    "문화와-공간": (
        "info-deep-dive",
        "curation-top-points",
        "insider-field-guide",
        "expert-perspective",
        "experience-synthesis",
    ),
}


def test_select_cloudflare_article_pattern_uses_category_specific_travel_patterns(monkeypatch) -> None:
    class _FakeResult:
        def scalar_one(self):
            return 2

    class _FakeDb:
        def execute(self, *_args, **_kwargs):
            return _FakeResult()

    monkeypatch.setattr(
        article_pattern_service,
        "_recent_cloudflare_pattern_ids",
        lambda db, category_slug, limit=3: ("route-first-story", "spot-focus-review"),
    )

    selection = article_pattern_service.select_cloudflare_article_pattern(
        _FakeDb(),
        category_slug="여행과-기록",
    )

    assert selection.pattern_id == "hidden-gem-discovery"
    assert selection.allowed_pattern_ids == (
        "route-first-story",
        "spot-focus-review",
        "seasonal-special",
        "logistics-budget",
        "hidden-gem-discovery",
    )
    assert selection.selection_note == "default_rotation"
    assert selection.pattern_version == article_pattern_service.ARTICLE_PATTERN_VERSION


def test_select_cloudflare_mysteria_pattern_blocks_threepeat(monkeypatch) -> None:
    class _FakeResult:
        def scalar_one(self):
            return 0

    class _FakeDb:
        def execute(self, *_args, **_kwargs):
            return _FakeResult()

    monkeypatch.setattr(
        article_pattern_service,
        "_recent_cloudflare_pattern_ids",
        lambda db, category_slug, limit=12: (
            "case-timeline",
            "case-timeline",
            "case-timeline",
        ),
    )

    selection = article_pattern_service.select_cloudflare_article_pattern(
        _FakeDb(),
        category_slug="미스테리아-스토리",
    )

    assert selection.pattern_id == "evidence-breakdown"
    assert selection.pattern_id != "case-timeline"
    assert "blocked_threepeat=case-timeline" in selection.selection_note
    assert selection.pattern_version == article_pattern_service.ARTICLE_PATTERN_VERSION


def test_cloudflare_default_prompt_uses_cloudflare_travel_contract() -> None:
    prompt = cloudflare_channel_service._default_prompt_for_stage(
        {
            "id": "travel",
            "slug": "여행과-기록",
            "name": "여행과-기록",
            "description": "경험형 여행 기록",
        },
        "article_generation",
    )

    assert "pros and cons" not in prompt
    assert "Cloudflare 내부 여행 기록" in prompt
    assert "Do not mention Antigravity, Codex, Gemini, BloggerGent" in prompt
    assert "inline_collage_prompt: return an empty string" in prompt


def test_select_cloudflare_article_pattern_supports_nasdaq_category(monkeypatch) -> None:
    class _FakeResult:
        def scalar_one(self):
            return 0

    class _FakeDb:
        def execute(self, *_args, **_kwargs):
            return _FakeResult()

    monkeypatch.setattr(
        article_pattern_service,
        "_recent_cloudflare_pattern_ids",
        lambda db, category_slug, limit=3: (),
    )

    selection = article_pattern_service.select_cloudflare_article_pattern(
        _FakeDb(),
        category_slug="나스닥의-흐름",
    )

    assert selection.pattern_id == "nasdaq-technical-deep-dive"
    assert selection.allowed_pattern_ids == (
        "nasdaq-technical-deep-dive",
        "nasdaq-macro-impact",
        "nasdaq-big-tech-whale-watch",
        "nasdaq-hypothesis-scenario",
    )


@pytest.mark.parametrize("category_slug,expected_ids", EXPECTED_CLOUDFLARE_ALLOWED_PATTERNS.items())
def test_cloudflare_pattern_map_covers_all_prompt_categories(category_slug: str, expected_ids: tuple[str, ...]) -> None:
    assert category_slug in cloudflare_channel_service.CLOUDFLARE_PROMPT_CATEGORY_PATH_MAP
    assert article_pattern_service._CLOUDFLARE_PATTERN_MAP[category_slug] == expected_ids
    assert article_pattern_service.ARTICLE_PATTERN_VERSION == 4


def test_cloudflare_mysteria_aliases_do_not_contain_garbage_placeholders() -> None:
    aliases = article_pattern_service.MYSTERIA_CATEGORY_SLUG_ALIASES
    assert "?????????????" not in aliases
    assert article_pattern_service.MYSTERIA_CATEGORY_SLUG in aliases
    assert "miseuteria-seutori" in aliases


def test_cloudflare_romanized_category_aliases_match_canonical_patterns() -> None:
    for canonical, aliases in article_pattern_service.CLOUDFLARE_CATEGORY_SLUG_ALIASES.items():
        assert canonical in article_pattern_service._CLOUDFLARE_PATTERN_MAP
        for alias in aliases:
            assert alias in article_pattern_service._CLOUDFLARE_PATTERN_MAP
            assert (
                article_pattern_service._CLOUDFLARE_PATTERN_MAP[alias]
                == article_pattern_service._CLOUDFLARE_PATTERN_MAP[canonical]
            )
            if alias != canonical:
                assert alias in cloudflare_channel_service.CLOUDFLARE_PROMPT_CATEGORY_PATH_MAP
