from app.services.content import article_pattern_service


class _FakeDb:
    pass


def test_travel_pattern_selection_ignores_source_preference(monkeypatch) -> None:
    monkeypatch.setattr(
        article_pattern_service,
        "_recent_blogger_pattern_ids",
        lambda db, blog_id, editorial_category_key, limit=8: (),
    )

    selection = article_pattern_service.select_blogger_article_pattern(
        _FakeDb(),
        blog_id=37,
        profile_key="korea_travel",
        editorial_category_key="travel",
        preferred_pattern_id="travel-01-hidden-path-route",
        preferred_selection_note="preferred_pattern_inherited",
        pattern_context_key="travel-en-735|nodeul-island",
    )

    assert selection.selection_note.startswith("travel_blog_specific_deterministic_random;")
    assert "preferred_pattern_inherited" not in selection.selection_note


def test_travel_pattern_selection_blocks_third_consecutive_pattern(monkeypatch) -> None:
    monkeypatch.setattr(
        article_pattern_service,
        "_recent_blogger_pattern_ids",
        lambda db, blog_id, editorial_category_key, limit=8: (
            "travel-05-smart-traveler-log",
            "travel-05-smart-traveler-log",
        ),
    )

    selection = article_pattern_service.select_blogger_article_pattern(
        _FakeDb(),
        blog_id=37,
        profile_key="korea_travel",
        editorial_category_key="travel",
        pattern_context_key="travel-en-736|boramae",
    )

    assert selection.pattern_id != "travel-05-smart-traveler-log"
    assert "blocked_threepeat=travel-05-smart-traveler-log" in selection.selection_note


def test_travel_pattern_selection_is_blog_specific_for_same_sync_group(monkeypatch) -> None:
    monkeypatch.setattr(
        article_pattern_service,
        "_recent_blogger_pattern_ids",
        lambda db, blog_id, editorial_category_key, limit=8: (),
    )

    selections = {
        article_pattern_service.select_blogger_article_pattern(
            _FakeDb(),
            blog_id=blog_id,
            profile_key="korea_travel",
            editorial_category_key="travel",
            pattern_context_key="travel-en-735|nodeul-island",
        ).pattern_id
        for blog_id in (34, 36, 37)
    }

    assert len(selections) >= 2
