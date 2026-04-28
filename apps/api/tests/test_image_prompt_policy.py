from app.services.content.image_prompt_policy import is_valid_collage_prompt, should_reuse_article_collage_prompts


def test_valid_collage_prompt_accepts_realistic_article_output_prompt() -> None:
    prompt = (
        "Realistic editorial 5x4 collage with twenty distinct travel panels, visible white gutters, "
        "single flattened final image, natural light, no text, and no logo."
    )

    assert is_valid_collage_prompt(prompt) is True


def test_valid_collage_prompt_rejects_jsonish_payload() -> None:
    prompt = '{"image_collage_prompt": "travel collage"}'

    assert is_valid_collage_prompt(prompt) is False


def test_should_reuse_article_collage_prompts_requires_both_prompts_when_inline_is_enabled() -> None:
    reuse, hero_valid, inline_valid = should_reuse_article_collage_prompts(
        hero_prompt=(
            "Realistic editorial 5x4 collage with twenty distinct market panels, visible white gutters, "
            "single flattened final image, no text, no logo."
        ),
        inline_prompt="too short",
        inline_required=True,
    )

    assert reuse is False
    assert hero_valid is True
    assert inline_valid is False


def test_should_reuse_article_collage_prompts_skips_inline_requirement_when_disabled() -> None:
    reuse, hero_valid, inline_valid = should_reuse_article_collage_prompts(
        hero_prompt=(
            "Documentary-style 5x4 collage with twenty distinct mystery panels, white gutters, "
            "single flattened final image, no text, no logo, no gore."
        ),
        inline_prompt="",
        inline_required=False,
    )

    assert reuse is True
    assert hero_valid is True
    assert inline_valid is True
