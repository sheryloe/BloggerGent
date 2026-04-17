from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.services.content.travel_blog_policy import (
    TRAVEL_IMAGE_PROMPT_MODEL,
    TRAVEL_LOCKED_IMAGE_MODEL,
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


def _expected_stage_model(path: Path, stage: str) -> str | None:
    folder_name = path.parent.name
    if folder_name in _TRAVEL_CHANNEL_FOLDERS and stage == "image_prompt_generation":
        return TRAVEL_IMAGE_PROMPT_MODEL
    if folder_name in _TRAVEL_CHANNEL_FOLDERS and stage == "image_generation":
        return TRAVEL_LOCKED_IMAGE_MODEL
    return _EXPECTED_STAGE_MODELS.get(stage)


def _extract_stage_models(path: Path) -> list[tuple[str, str]]:
    current_stage = ""
    pairs: list[tuple[str, str]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if '"stage_type"' in line:
            current_stage = line.split('"')[-2]
        elif current_stage and '"provider_model"' in line:
            if "null" in line:
                current_stage = ""
                continue
            model = line.split('"')[-2]
            pairs.append((current_stage, model))
            current_stage = ""
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
        for stage, model in _extract_stage_models(path):
            expected = _expected_stage_model(path, stage)
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
