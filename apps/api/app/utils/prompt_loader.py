from __future__ import annotations

from pathlib import Path

from app.core.config import settings


def load_prompt(name: str) -> str:
    prompt_path = Path(settings.prompt_root) / name
    return prompt_path.read_text(encoding="utf-8")
