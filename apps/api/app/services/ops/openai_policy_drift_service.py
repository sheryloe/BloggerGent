from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.content.travel_blog_policy import (
    TRAVEL_DEFAULT_TEXT_ROUTE,
    TRAVEL_IMAGE_PROMPT_MODEL,
    TRAVEL_LOCKED_IMAGE_MODEL,
    resolve_travel_text_route_models,
)

OFFICIAL_OPENAI_POLICY_URLS: tuple[str, ...] = (
    "https://help.openai.com/en/articles/10306912-sharing-feedback-evaluation-and-fine-tuning-data-and-api-inputs-and-outputs-with-openai",
    "https://openai.com/api/pricing/",
    "https://developers.openai.com/api/docs/guides/tools-image-generation",
)

_THREE_STEP_BLOCK = "[3-Step Article Assembly]"
_EXPECTED_STAGE_MODELS = {
    "topic_discovery": "gpt-5.4-2026-03-05",
    "article_generation": "gpt-5.4-mini-2026-03-17",
    "image_prompt_generation": "gpt-5.4-mini-2026-03-17",
    "image_generation": "gpt-image-1",
}
_TRAVEL_CHANNEL_FOLDERS = {
    "donggri-s-hidden-korea-local-travel-culture",
    "donggri-el-alma-de-corea",
    "donggri-ri-han-fu-fu-nohan-guo-rokaruan-nei",
}
_MYSTERY_CHANNEL_FOLDERS = {"the-midnight-archives"}
_PROMPT_SYNC_IGNORED_KEYS = {
    "the-midnight-archives/mystery_article_generation.md",
}


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "prompts" / "channels").exists() and (parent / "apps" / "api" / "prompts" / "channels").exists():
            return parent
    raise RuntimeError("Repository root not found from openai_policy_drift_service.")


def _article_prompt_files(root: Path) -> list[Path]:
    targets = [
        root / "prompts" / "channels" / "blogger",
        root / "prompts" / "channels" / "cloudflare",
        root / "apps" / "api" / "prompts" / "channels" / "blogger",
        root / "apps" / "api" / "prompts" / "channels" / "cloudflare",
    ]
    files: list[Path] = []
    for target in targets:
        files.extend(sorted(target.rglob("*article_generation*.md")))
    return files


def _channel_json_files(root: Path) -> list[Path]:
    targets = [
        root / "prompts" / "channels" / "blogger",
        root / "prompts" / "channels" / "cloudflare",
        root / "apps" / "api" / "prompts" / "channels" / "blogger",
        root / "apps" / "api" / "prompts" / "channels" / "cloudflare",
    ]
    files: list[Path] = []
    for target in targets:
        files.extend(sorted(target.rglob("channel.json")))
    return files


def _prompt_sync_key(path: Path) -> str:
    return "/".join(path.parts[-2:])


def _expected_stage_model(path: Path, stage: str, step: dict[str, Any] | None = None) -> str | None:
    folder_name = path.parent.name
    if folder_name in _TRAVEL_CHANNEL_FOLDERS:
        step_payload = step or {}
        policy_config = step_payload.get("policy_config") if isinstance(step_payload.get("policy_config"), dict) else {}
        route = str(
            step_payload.get("text_generation_route")
            or policy_config.get("text_generation_route")
            or TRAVEL_DEFAULT_TEXT_ROUTE
        )
        route_models = resolve_travel_text_route_models(route)
        if stage == "topic_discovery":
            return None
        if stage == "article_generation":
            return route_models["pass_provider_model"]
        if stage == "image_prompt_generation":
            return route_models["image_prompt_provider_model"]
        if stage == "image_generation":
            return TRAVEL_LOCKED_IMAGE_MODEL
    if folder_name in _MYSTERY_CHANNEL_FOLDERS and stage == "topic_discovery":
        provider_hint = str((step or {}).get("provider_hint") or "").strip()
        if provider_hint == "codex_cli":
            return "gpt-5.4"
    if folder_name == "miseuteria-seutori" and stage == "topic_discovery":
        provider_hint = str((step or {}).get("provider_hint") or "").strip()
        if provider_hint == "codex_cli":
            return "gpt-5.4"
    return _EXPECTED_STAGE_MODELS.get(stage)


def _extract_stage_models(path: Path) -> list[tuple[str, str, dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    pairs: list[tuple[str, str, dict[str, Any]]] = []
    for raw_step in payload.get("steps", []):
        if not isinstance(raw_step, dict):
            continue
        stage = str(raw_step.get("stage_type") or "").strip()
        model = str(raw_step.get("provider_model") or "").strip()
        if stage and model:
            pairs.append((stage, model, raw_step))
    return pairs


def build_openai_policy_drift_payload() -> dict[str, object]:
    root = _repo_root()
    article_prompt_files = _article_prompt_files(root)
    prompt_block_violations = [
        str(path)
        for path in article_prompt_files
        if _THREE_STEP_BLOCK in path.read_text(encoding="utf-8")
    ]

    repo_prompt_files = [
        *sorted((root / "prompts" / "channels" / "blogger").rglob("*article_generation*.md")),
        *sorted((root / "prompts" / "channels" / "cloudflare").rglob("*article_generation*.md")),
    ]
    api_prompt_files = [
        *sorted((root / "apps" / "api" / "prompts" / "channels" / "blogger").rglob("*article_generation*.md")),
        *sorted((root / "apps" / "api" / "prompts" / "channels" / "cloudflare").rglob("*article_generation*.md")),
    ]
    left = {_prompt_sync_key(path): path.read_text(encoding="utf-8").strip() for path in repo_prompt_files}
    right = {_prompt_sync_key(path): path.read_text(encoding="utf-8").strip() for path in api_prompt_files}
    shared_keys = sorted(set(left).intersection(right))
    prompt_sync_mismatches = [
        key
        for key in shared_keys
        if key not in _PROMPT_SYNC_IGNORED_KEYS and left.get(key) != right.get(key)
    ]

    channel_violations: list[str] = []
    for path in _channel_json_files(root):
        for stage, model, step in _extract_stage_models(path):
            expected = _expected_stage_model(path, stage, step)
            if expected and model != expected:
                channel_violations.append(f"{path}:{stage}={model}")

    return {
        "official_docs": list(OFFICIAL_OPENAI_POLICY_URLS),
        "repo_policy": {
            "topic_model": settings.topic_discovery_model,
            "article_model": settings.article_generation_model,
            "default_image_prompt_model": settings.image_prompt_generation_model,
            "travel_image_prompt_model": TRAVEL_IMAGE_PROMPT_MODEL,
            "image_model": TRAVEL_LOCKED_IMAGE_MODEL,
        },
        "drift": {
            "channel_model_violations": channel_violations,
            "three_step_file_block_violations": prompt_block_violations,
            "prompt_sync_mismatches": prompt_sync_mismatches,
        },
    }
