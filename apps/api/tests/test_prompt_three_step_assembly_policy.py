from __future__ import annotations

import json
from pathlib import Path

from app.core.config import settings
from app.services.content.travel_blog_policy import (
    TRAVEL_DEFAULT_TEXT_ROUTE,
    TRAVEL_IMAGE_POLICY_VERSION,
    TRAVEL_LOCKED_IMAGE_MODEL,
    resolve_travel_text_route_models,
)

TRAVEL_CHANNELS = {
    "donggri-s-hidden-korea-local-travel-culture": "blogger:34",
    "donggri-el-alma-de-corea": "blogger:36",
    "donggri-ri-han-fu-fu-nohan-guo-rokaruan-nei": "blogger:37",
}


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "prompts" / "channels").exists() and (parent / "apps" / "api").exists():
            return parent
    raise RuntimeError("Repository root not found from test path.")


def test_travel_channel_models_are_locked_to_planner_pass_and_image_policy() -> None:
    root = _repo_root()
    violations: list[str] = []
    for folder, channel_id in TRAVEL_CHANNELS.items():
        path = root / "prompts" / "channels" / "blogger" / folder / "channel.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("channel_id") != channel_id:
            violations.append(f"{path}: channel_id={payload.get('channel_id')}")
        steps = {str(item.get("stage_type") or ""): item for item in payload.get("steps", [])}
        topic_model = steps["topic_discovery"].get("provider_model")
        if topic_model not in {None, settings.topic_discovery_model}:
            violations.append(f"{path}: topic_discovery={steps['topic_discovery']['provider_model']}")
        route = steps["article_generation"].get("text_generation_route") or TRAVEL_DEFAULT_TEXT_ROUTE
        route_models = resolve_travel_text_route_models(str(route))
        if steps["article_generation"]["provider_model"] != route_models["pass_provider_model"]:
            violations.append(f"{path}: article_generation={steps['article_generation']['provider_model']}")
        if steps["article_generation"].get("planner_provider_model") != route_models["planner_provider_model"]:
            violations.append(f"{path}: planner_provider_model={steps['article_generation'].get('planner_provider_model')}")
        if steps["article_generation"].get("pass_provider_model") != route_models["pass_provider_model"]:
            violations.append(f"{path}: pass_provider_model={steps['article_generation'].get('pass_provider_model')}")
        if steps["article_generation"].get("structure_mode") != "kisungjeongyeol_4beat":
            violations.append(f"{path}: structure_mode={steps['article_generation'].get('structure_mode')}")
        image_route = steps["image_prompt_generation"].get("text_generation_route") or route
        image_route_models = resolve_travel_text_route_models(str(image_route))
        if steps["image_prompt_generation"]["provider_model"] != image_route_models["image_prompt_provider_model"]:
            violations.append(f"{path}: image_prompt_generation={steps['image_prompt_generation']['provider_model']}")
        if steps["image_generation"]["provider_model"] != TRAVEL_LOCKED_IMAGE_MODEL:
            violations.append(f"{path}: image_generation={steps['image_generation']['provider_model']}")
        if steps["image_generation"].get("locked_image_model") != TRAVEL_LOCKED_IMAGE_MODEL:
            violations.append(f"{path}: locked_image_model={steps['image_generation'].get('locked_image_model')}")
        if steps["image_generation"].get("image_policy_version") != TRAVEL_IMAGE_POLICY_VERSION:
            violations.append(f"{path}: image_policy_version={steps['image_generation'].get('image_policy_version')}")
    assert not violations, f"Travel channel policy violations: {violations}"


def test_travel_article_prompts_are_hero_only() -> None:
    root = _repo_root()
    violations: list[str] = []
    for folder in TRAVEL_CHANNELS:
        article_prompt = root / "prompts" / "channels" / "blogger" / folder / "travel_article_generation.md"
        text = article_prompt.read_text(encoding="utf-8")
        if "inline_collage_prompt" in text:
            violations.append(str(article_prompt))
        if "8-panel" not in text and "8 panel" not in text:
            violations.append(f"{article_prompt}: missing 8-panel rule")
    assert not violations, f"Travel prompt hero-only violations: {violations}"


def test_runtime_prompt_source_is_repo_root_only_for_travel_bloggers() -> None:
    root = _repo_root()
    violations: list[str] = []
    for folder in TRAVEL_CHANNELS:
        duplicate_dir = root / "apps" / "api" / "prompts" / "channels" / "blogger" / folder
        if duplicate_dir.exists():
            violations.append(str(duplicate_dir))
    assert not violations, f"Travel duplicate prompt trees should be removed: {violations}"
