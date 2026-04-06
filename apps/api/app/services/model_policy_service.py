from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

FREE_MODEL_POLICY = {
    "large": [
        "gpt-5-codex",
        "gpt-5-2025-08-07",
        "gpt-5-chat-latest",
        "gpt-4.5-preview-2025-02-27",
        "gpt-4.1-2025-04-14",
        "gpt-4o-2024-05-13",
        "gpt-4o-2024-08-06",
        "gpt-4o-2024-11-20",
        "o3-2025-04-16",
        "o1-preview-2024-09-12",
        "o1-2024-12-17",
    ],
    "small": [
        "gpt-5-mini-2025-08-07",
        "gpt-5-nano-2025-08-07",
        "gpt-4.1-mini-2025-04-14",
        "gpt-4.1-nano-2025-04-14",
        "gpt-4o-mini-2024-07-18",
        "o4-mini-2025-04-16",
        "o1-mini-2024-09-12",
        "codex-mini-latest",
    ],
}

DEPRECATED_MODELS = ["gpt-4.5-preview-2025-02-27"]
DEFAULT_TEXT_MODEL = "gpt-4.1-2025-04-14"
DEFAULT_LIGHTWEIGHT_MODEL = "gpt-4.1-mini-2025-04-14"
SETTINGS_MODEL_KEYS = (
    "openai_text_model",
    "topic_discovery_model",
    "article_generation_model",
)


@dataclass(frozen=True)
class ModelPolicy:
    large: list[str]
    small: list[str]
    deprecated: list[str]
    defaults: dict[str, str]

    @property
    def allowed(self) -> list[str]:
        ordered = []
        for item in [*self.large, *self.small]:
            if item not in ordered:
                ordered.append(item)
        return ordered


def build_model_policy() -> ModelPolicy:
    return ModelPolicy(
        large=list(FREE_MODEL_POLICY["large"]),
        small=list(FREE_MODEL_POLICY["small"]),
        deprecated=list(DEPRECATED_MODELS),
        defaults={
            "text": DEFAULT_TEXT_MODEL,
            "lightweight": DEFAULT_LIGHTWEIGHT_MODEL,
        },
    )


def is_allowed_model(model_name: str | None) -> bool:
    if not model_name:
        return False
    return model_name in build_model_policy().allowed


def validate_model_name(model_name: str | None) -> str:
    if not model_name:
        raise ValueError("model name is required")
    if not is_allowed_model(model_name):
        raise ValueError(f"model '{model_name}' is not in the free-tier allowlist")
    return model_name


def validate_text_settings_payload(payload: dict[str, str]) -> None:
    for key in SETTINGS_MODEL_KEYS:
        value = payload.get(key)
        if value is None:
            continue
        validate_model_name(value)


def normalize_models(models: Iterable[str | None]) -> list[str]:
    normalized: list[str] = []
    for model in models:
        if not model:
            continue
        validate_model_name(model)
        if model not in normalized:
            normalized.append(model)
    return normalized
