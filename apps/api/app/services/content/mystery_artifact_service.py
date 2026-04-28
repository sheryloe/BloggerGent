from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from app.core.config import settings


def _safe_slug(value: object | None, *, fallback: str = "unknown") -> str:
    text = str(value or "").strip().lower()
    normalized = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in text).strip("-_")
    return normalized[:120] if normalized else fallback


@dataclass(frozen=True, slots=True)
class MysteryArtifactContext:
    channel_kind: str
    channel_slug: str
    category_key: str
    slug: str
    year: str
    month: str

    @property
    def root(self) -> Path:
        return (
            Path(settings.storage_root)
            / "the-midnight-archives"
            / self.channel_kind
            / self.channel_slug
            / self.category_key
            / self.year
            / self.month
            / self.slug
        )


def build_mystery_artifact_context(
    *,
    channel_kind: str,
    channel_slug: str,
    category_key: str,
    slug: str,
    created_at: datetime | None = None,
) -> MysteryArtifactContext:
    resolved_dt = created_at or datetime.now(timezone.utc)
    return MysteryArtifactContext(
        channel_kind=_safe_slug(channel_kind, fallback="unknown-channel"),
        channel_slug=_safe_slug(channel_slug, fallback="mystery"),
        category_key=_safe_slug(category_key, fallback="uncategorized"),
        slug=_safe_slug(slug, fallback="post"),
        year=resolved_dt.strftime("%Y"),
        month=resolved_dt.strftime("%m"),
    )


def ensure_mystery_artifact_dir(context: MysteryArtifactContext, stage_dir: str) -> Path:
    destination = context.root / stage_dir
    destination.mkdir(parents=True, exist_ok=True)
    return destination


def write_mystery_artifact_text(
    context: MysteryArtifactContext,
    *,
    stage_dir: str,
    filename: str,
    content: str,
) -> Path:
    destination = ensure_mystery_artifact_dir(context, stage_dir) / filename
    destination.write_text(str(content or ""), encoding="utf-8")
    return destination


def write_mystery_artifact_json(
    context: MysteryArtifactContext,
    *,
    stage_dir: str,
    filename: str,
    payload: Mapping[str, Any] | list[Any] | str | int | float | bool | None,
) -> Path:
    destination = ensure_mystery_artifact_dir(context, stage_dir) / filename
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return destination


def copy_mystery_artifact_file(
    context: MysteryArtifactContext,
    *,
    stage_dir: str,
    source_path: str | Path | None,
    target_name: str | None = None,
) -> Path | None:
    if not source_path:
        return None
    source = Path(source_path)
    if not source.exists() or not source.is_file():
        return None
    destination = ensure_mystery_artifact_dir(context, stage_dir) / (target_name or source.name)
    shutil.copy2(source, destination)
    return destination


def write_mystery_artifact_manifest(
    context: MysteryArtifactContext,
    *,
    payload: Mapping[str, Any],
) -> Path:
    return write_mystery_artifact_json(
        context,
        stage_dir="00-manifest",
        filename="manifest.json",
        payload=payload,
    )
