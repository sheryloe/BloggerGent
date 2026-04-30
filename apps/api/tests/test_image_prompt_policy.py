from app.services.content.image_prompt_policy import is_valid_collage_prompt, should_reuse_article_collage_prompts


def test_valid_collage_prompt_accepts_realistic_article_output_prompt() -> None:
    prompt = (
        "Realistic editorial 4x3 collage with twelve distinct travel panels, visible white gutters, "
        "single flattened final image, natural light, no text, and no logo."
    )

    assert is_valid_collage_prompt(prompt) is True


def test_valid_collage_prompt_rejects_jsonish_payload() -> None:
    prompt = '{"image_collage_prompt": "travel collage"}'

    assert is_valid_collage_prompt(prompt) is False


def test_should_reuse_article_collage_prompts_requires_both_prompts_when_inline_is_enabled() -> None:
    reuse, hero_valid, inline_valid = should_reuse_article_collage_prompts(
        hero_prompt=(
            "Realistic editorial 4x3 collage with twelve distinct market panels, visible white gutters, "
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
            "Documentary-style 4x3 collage with twelve distinct mystery panels, white gutters, "
            "single flattened final image, no text, no logo, no gore."
        ),
        inline_prompt="",
        inline_required=False,
    )

    assert reuse is True
    assert hero_valid is True
    assert inline_valid is True


def test_should_reuse_article_collage_prompts_can_accept_non_collage_dev_hero() -> None:
    reuse, hero_valid, inline_valid = should_reuse_article_collage_prompts(
        hero_prompt=(
            "Representative 16:9 developer workflow cover image with official docs, release notes, IDE, "
            "CLI, runtime cues, logs, and architecture artifacts, no logo, no watermark."
        ),
        inline_prompt="",
        inline_required=False,
        hero_requires_collage=False,
    )

    assert reuse is True
    assert hero_valid is True
    assert inline_valid is True


def test_valid_collage_prompt_rejects_contact_sheet_language() -> None:
    prompt = "Create a contact sheet of separate images with panels, no text, no logo."

    assert is_valid_collage_prompt(prompt) is False


def test_valid_collage_prompt_rejects_single_hero_without_panel_structure() -> None:
    prompt = "Create one single hero shot of a Seoul street with no panel collage structure, no text, no logo."

    assert is_valid_collage_prompt(prompt) is False
