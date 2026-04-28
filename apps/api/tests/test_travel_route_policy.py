from __future__ import annotations

from app.services.content.travel_blog_policy import (
    TRAVEL_TEXT_ROUTE_API,
    TRAVEL_TEXT_ROUTE_CODEX,
    TRAVEL_TEXT_ROUTE_GEMINI,
    build_travel_asset_object_key,
    build_travel_policy_config,
    get_travel_blog_policy,
    normalize_travel_asset_category_key,
    normalize_travel_text_generation_route,
    travel_text_generation_route_chain,
    travel_text_generation_route_setting_key,
)


def test_normalize_travel_route_accepts_gemini() -> None:
    assert normalize_travel_text_generation_route("gemini_cli") == TRAVEL_TEXT_ROUTE_GEMINI
    assert normalize_travel_text_generation_route("GEMINI_CLI") == TRAVEL_TEXT_ROUTE_GEMINI


def test_travel_route_chain_is_stable() -> None:
    assert travel_text_generation_route_chain(TRAVEL_TEXT_ROUTE_CODEX) == (
        TRAVEL_TEXT_ROUTE_CODEX,
        TRAVEL_TEXT_ROUTE_GEMINI,
        TRAVEL_TEXT_ROUTE_API,
    )
    assert travel_text_generation_route_chain(TRAVEL_TEXT_ROUTE_GEMINI) == (
        TRAVEL_TEXT_ROUTE_GEMINI,
        TRAVEL_TEXT_ROUTE_CODEX,
        TRAVEL_TEXT_ROUTE_API,
    )
    assert travel_text_generation_route_chain(TRAVEL_TEXT_ROUTE_API) == (
        TRAVEL_TEXT_ROUTE_API,
        TRAVEL_TEXT_ROUTE_CODEX,
        TRAVEL_TEXT_ROUTE_GEMINI,
    )


def test_build_travel_policy_config_uses_gemini_route_models() -> None:
    policy = get_travel_blog_policy(blog_id=34)
    assert policy is not None
    values = {travel_text_generation_route_setting_key(policy.blog_id): "gemini_cli"}
    article_config = build_travel_policy_config(policy, stage_type="article_generation", values=values)
    image_prompt_config = build_travel_policy_config(policy, stage_type="image_prompt_generation", values=values)

    assert isinstance(article_config, dict)
    assert article_config["text_generation_route"] == "gemini_cli"
    assert article_config["planner_provider_hint"] == "gemini_cli"
    assert article_config["planner_provider_model"] == "gemini-2.5-pro"
    assert article_config["pass_provider_model"] == "gemini-2.5-flash"

    assert isinstance(image_prompt_config, dict)
    assert image_prompt_config["text_generation_route"] == "gemini_cli"
    assert image_prompt_config["provider_hint"] == "gemini_cli"
    assert image_prompt_config["provider_model"] == "gemini-2.5-flash"


def test_travel_asset_category_maps_food_to_travel_path() -> None:
    policy = get_travel_blog_policy(blog_id=34)
    assert policy is not None

    assert normalize_travel_asset_category_key("food") == "travel"
    assert normalize_travel_asset_category_key("uncategorized") == "travel"
    assert normalize_travel_asset_category_key("culture") == "culture"

    object_key = build_travel_asset_object_key(
        policy=policy,
        category_key="food",
        post_slug="sample-post",
        asset_role="hero",
    )
    assert object_key == "assets/travel-blogger/travel/sample-post.webp"
