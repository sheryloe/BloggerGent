from __future__ import annotations

import re

_JSONISH_PREFIX_RE = re.compile(r"^\s*[\[{]")
_MARKDOWN_FENCE_RE = re.compile(r"```")
_MULTISPACE_RE = re.compile(r"\s+")


def normalize_visual_prompt(value: str | None) -> str:
    prompt = str(value or "").strip()
    if not prompt:
        return ""
    return _MULTISPACE_RE.sub(" ", prompt).strip()


def is_valid_visual_prompt(value: str | None, *, minimum_length: int = 40) -> bool:
    prompt = normalize_visual_prompt(value)
    if len(prompt) < minimum_length:
        return False
    if _MARKDOWN_FENCE_RE.search(prompt):
        return False
    if _JSONISH_PREFIX_RE.match(prompt):
        return False
    return True


def is_valid_collage_prompt(value: str | None, *, minimum_length: int = 40) -> bool:
    prompt = normalize_visual_prompt(value)
    if not is_valid_visual_prompt(prompt, minimum_length=minimum_length):
        return False
    lowered = prompt.casefold()
    return any(token in lowered for token in ("collage", "panel", "grid", "contact sheet"))


def should_reuse_article_collage_prompts(
    *,
    hero_prompt: str | None,
    inline_prompt: str | None,
    inline_required: bool,
) -> tuple[bool, bool, bool]:
    hero_valid = is_valid_collage_prompt(hero_prompt)
    inline_valid = (not inline_required) or is_valid_collage_prompt(inline_prompt, minimum_length=30)
    return hero_valid and inline_valid, hero_valid, inline_valid
