from app.services import article_pattern_service, cloudflare_channel_service


def test_select_cloudflare_article_pattern_avoids_recent_patterns(monkeypatch) -> None:
    class _FakeResult:
        def scalar_one(self):
            return 2

    class _FakeDb:
        def execute(self, *_args, **_kwargs):
            return _FakeResult()

    monkeypatch.setattr(
        article_pattern_service,
        "_recent_cloudflare_pattern_ids",
        lambda db, category_slug, limit=3: ("experience-diary", "route-timeline"),
    )

    selection = article_pattern_service.select_cloudflare_article_pattern(
        _FakeDb(),
        category_slug="여행과-기록",
    )

    assert selection.pattern_id == "spot-card-grid"
    assert selection.allowed_pattern_ids == (
        "experience-diary",
        "route-timeline",
        "spot-card-grid",
        "exhibition-field-guide",
    )


def test_cloudflare_default_prompt_avoids_report_style_sections() -> None:
    prompt = cloudflare_channel_service._default_prompt_for_stage(
        {
            "id": "travel",
            "slug": "여행과-기록",
            "name": "여행과 기록",
            "description": "경험형 여행 기록",
        },
        "article_generation",
    )

    assert "확인된 사실" not in prompt
    assert "미확인 또는 변동 가능 정보" not in prompt
    assert "pros and cons" not in prompt
    assert "This category is only for actual places" in prompt
    assert "Do not expose any internal helper phrases" in prompt
    assert "The final body section title must be exactly <h2>마무리 기록</h2>." in prompt


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

    assert selection.pattern_id == "two-voice-market-chat"
    assert selection.allowed_pattern_ids == ("two-voice-market-chat",)
