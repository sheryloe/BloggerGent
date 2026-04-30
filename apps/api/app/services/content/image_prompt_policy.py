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
    forbidden_terms = (
        "contact sheet",
        "sprite sheet",
        "separate images",
        "separate image files",
        "separate assets",
    )
    if any(term in lowered for term in forbidden_terms):
        return False
    if "single hero shot" in lowered and "without panel" not in lowered:
        return False
    return any(token in lowered for token in ("collage", "panel", "grid"))


def should_reuse_article_collage_prompts(
    *,
    hero_prompt: str | None,
    inline_prompt: str | None,
    inline_required: bool,
    hero_requires_collage: bool = True,
) -> tuple[bool, bool, bool]:
    hero_valid = (
        is_valid_collage_prompt(hero_prompt)
        if hero_requires_collage
        else is_valid_visual_prompt(hero_prompt)
    )
    inline_valid = (not inline_required) or is_valid_collage_prompt(inline_prompt, minimum_length=30)
    return hero_valid and inline_valid, hero_valid, inline_valid
