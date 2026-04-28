from app.services import article_pattern_service, cloudflare_channel_service


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
