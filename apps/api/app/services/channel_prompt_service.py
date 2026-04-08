from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
from textwrap import dedent

from slugify import slugify
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import BlogAgentConfig
from app.schemas.api import PromptFlowRead, PromptFlowStepRead, PromptFlowStepUpdate
from app.services.blog_service import (
    get_blog,
    get_missing_optional_stage_types,
    list_workflow_steps,
    stage_is_removable,
    stage_label,
    stage_supports_prompt,
)
from app.services.cloudflare_channel_service import DEFAULT_PROMPT_STAGES, get_cloudflare_overview, get_cloudflare_prompt_bundle
from app.services.platform_service import PLATFORM_PROMPT_STEPS
from app.services.settings_service import get_settings_map, upsert_settings
from app.services.workspace_service import get_managed_channel, list_managed_channels

_SAFE_SEGMENT_RE = re.compile(r"[^a-zA-Z0-9._-]+")
_PLATFORM_REQUIRED_STAGE_TYPES = {"platform_publish"}


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_channel_id(channel_id: str) -> tuple[str, str]:
    normalized = str(channel_id or "").strip()
    if ":" not in normalized:
        raise ValueError("Channel not found")
    provider, raw_id = normalized.split(":", 1)
    if provider not in {"blogger", "cloudflare", "youtube", "instagram"} or not raw_id:
        raise ValueError("Channel not found")
    return provider, raw_id


def _safe_segment(value: str | None, fallback: str) -> str:
    raw = str(value or "").strip()
    normalized = slugify(raw, separator="-")
    if not normalized:
        normalized = _SAFE_SEGMENT_RE.sub("-", raw).strip("-._")
    if normalized:
        return normalized[:80]
    if raw:
        fallback_slug = slugify(fallback, separator="-") or _SAFE_SEGMENT_RE.sub("-", fallback).strip("-._") or "item"
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
        return f"{fallback_slug}-{digest}"[:80]
    return fallback


def _prompt_root() -> Path:
    resolved = Path(__file__).resolve()
    candidates: list[Path] = [Path(settings.prompt_root), Path.cwd() / "prompts"]
    if len(resolved.parents) >= 5:
        candidates.append(resolved.parents[4] / "prompts")
    candidates.append(resolved.parents[2] / "prompts")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[1]


def _backup_root() -> Path:
    return _prompt_root() / "channels"


def _default_channel_backup_dir(channel_id: str) -> Path:
    provider, raw_id = _parse_channel_id(channel_id)
    return _backup_root() / _safe_segment(provider, "channel") / _safe_segment(raw_id, "default")


def _default_channel_backup_relative_dir(channel_id: str) -> str:
    return _default_channel_backup_dir(channel_id).relative_to(_prompt_root()).as_posix()


def _named_channel_backup_relative_dir(provider: str, channel_name: str | None, *, channel_id: str | None = None) -> str:
    fallback = provider
    if channel_id:
        _channel_provider, raw_id = _parse_channel_id(channel_id)
        fallback = raw_id or provider
    folder_name = _safe_segment(channel_name, fallback)
    return (_backup_root() / _safe_segment(provider, "channel") / folder_name).relative_to(_prompt_root()).as_posix()


def _blogger_backup_relative_dir(blog) -> str:
    return _named_channel_backup_relative_dir(
        "blogger",
        getattr(blog, "name", "") or getattr(blog, "slug", ""),
        channel_id=f"blogger:{getattr(blog, 'id', '')}",
    )


def _stage_file_slug(stage_type: str) -> str:
    normalized = slugify(str(stage_type or "").strip(), separator="-") or _safe_segment(stage_type, "prompt")
    return normalized or "prompt"


def _normalize_prompt_text(content: str | None) -> str:
    normalized = str(content or "").strip()
    return normalized + ("\n" if normalized else "")


def _write_text(path: Path, content: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_normalize_prompt_text(content), encoding="utf-8")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _safe_remove_tree(path: Path, *, root: Path) -> None:
    if not path.exists():
        return
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    if resolved_root not in resolved_path.parents:
        raise ValueError("Refusing to remove a path outside the prompt backup root")
    shutil.rmtree(resolved_path)


def _cleanup_stale_channel_dirs(flow: PromptFlowRead, *, root: Path, current_channel_dir: Path) -> None:
    provider_root = root / "channels" / _safe_segment(flow.provider, "channel")
    if not provider_root.exists():
        return
    for metadata_path in provider_root.glob("*/channel.json"):
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(payload.get("channel_id") or "").strip() != flow.channel_id:
            continue
        candidate_dir = metadata_path.parent
        if candidate_dir == current_channel_dir:
            continue
        _safe_remove_tree(candidate_dir, root=root)


def _platform_prompt_storage_keys(channel_id: str, stage_type: str) -> dict[str, str]:
    channel_key = slugify(str(channel_id or "").replace(":", "-"), separator="_") or _safe_segment(channel_id, "channel")
    stage_key = slugify(str(stage_type or ""), separator="_") or _safe_segment(stage_type, "stage")
    prefix = f"channel_prompt__{channel_key}__{stage_key}"
    return {
        "prompt_template": f"{prefix}__txt",
        "name": f"{prefix}__name",
        "objective": f"{prefix}__obj",
        "provider_model": f"{prefix}__model",
        "is_enabled": f"{prefix}__enabled",
        "updated_at": f"{prefix}__updated",
    }


def _default_platform_prompt(channel_name: str, definition) -> str:
    return _normalize_prompt_text(
        dedent(
            f"""
            You are the {definition.role_name} for the "{channel_name}" channel.

            Objective
            - {definition.objective}

            Execution rules
            - Stay inside the `{definition.stage_type}` stage only.
            - Produce concrete, ready-to-use output.
            - Keep the voice consistent with the channel positioning.
            - Do not add unrelated analysis outside the requested stage deliverable.
            """
        ).strip()
    )


def _resolve_platform_definition(provider: str, step_id: str):
    definitions = PLATFORM_PROMPT_STEPS.get(provider, ())
    if not definitions:
        raise ValueError("Prompt flow is not supported for this provider")

    if ":" in step_id:
        step_provider, raw_index = step_id.split(":", 1)
        if step_provider == provider and raw_index.isdigit():
            index = int(raw_index)
            if 1 <= index <= len(definitions):
                return index, definitions[index - 1]

    for index, definition in enumerate(definitions, start=1):
        if definition.stage_type == step_id:
            return index, definition

    raise ValueError("Prompt flow step not found")


def _platform_step_payload(db: Session, channel, step_id: str) -> dict[str, str | bool | None]:
    index, definition = _resolve_platform_definition(channel.provider, step_id)
    values = get_settings_map(db)
    keys = _platform_prompt_storage_keys(channel.channel_id, definition.stage_type)
    prompt_template = values.get(keys["prompt_template"]) or _default_platform_prompt(channel.display_name, definition)
    is_required = definition.stage_type in _PLATFORM_REQUIRED_STAGE_TYPES
    is_enabled = str(values.get(keys["is_enabled"]) or "true").strip().lower() not in {"false", "0", "off", "no"}
    return {
        "id": f"{channel.provider}:{index}",
        "stage_type": definition.stage_type,
        "stage_label": definition.stage_label,
        "name": (values.get(keys["name"]) or "").strip() or definition.name,
        "role_name": definition.role_name,
        "objective": (values.get(keys["objective"]) or "").strip() or definition.objective,
        "prompt_template": _normalize_prompt_text(prompt_template),
        "provider_hint": definition.provider_hint,
        "provider_model": (values.get(keys["provider_model"]) or "").strip() or definition.provider_model,
        "is_enabled": True if is_required else is_enabled,
        "is_required": is_required,
        "removable": not is_required,
        "prompt_enabled": True,
        "editable": True,
        "structure_editable": False,
        "content_editable": True,
        "sort_order": index * 10,
    }


def list_platform_prompt_steps(db: Session, channel) -> list[dict[str, str | bool | None]]:
    return [
        _platform_step_payload(db, channel, f"{channel.provider}:{index}")
        for index, _definition in enumerate(PLATFORM_PROMPT_STEPS.get(channel.provider, ()), start=1)
    ]


def save_platform_prompt_step(
    db: Session,
    *,
    channel_id: str,
    step_id: str,
    payload: PromptFlowStepUpdate,
) -> None:
    channel = get_managed_channel(db, channel_id)
    if channel is None:
        raise ValueError("Channel not found")
    if channel.provider not in {"youtube", "instagram"}:
        raise ValueError("Platform prompt editing is not supported for this channel")

    _index, definition = _resolve_platform_definition(channel.provider, step_id)
    current = _platform_step_payload(db, channel, step_id)
    keys = _platform_prompt_storage_keys(channel.channel_id, definition.stage_type)
    updated_prompt = (
        _normalize_prompt_text(payload.prompt_template)
        if payload.prompt_template is not None
        else str(current["prompt_template"] or "")
    )
    is_required = definition.stage_type in _PLATFORM_REQUIRED_STAGE_TYPES
    is_enabled = True if is_required else (
        payload.is_enabled if payload.is_enabled is not None else bool(current["is_enabled"])
    )

    upsert_settings(
        db,
        {
            keys["prompt_template"]: updated_prompt,
            keys["name"]: payload.name if payload.name is not None else str(current["name"] or ""),
            keys["objective"]: payload.objective if payload.objective is not None else str(current["objective"] or ""),
            keys["provider_model"]: (
                payload.provider_model if payload.provider_model is not None else str(current["provider_model"] or "")
            ),
            keys["is_enabled"]: "true" if is_enabled else "false",
            keys["updated_at"]: _utc_now_iso(),
        },
    )


def _serialize_blogger_step(channel_id: str, step: BlogAgentConfig) -> PromptFlowStepRead:
    return PromptFlowStepRead(
        id=str(step.id),
        channel_id=channel_id,
        provider="blogger",
        stage_type=step.stage_type.value if hasattr(step.stage_type, "value") else str(step.stage_type),
        stage_label=stage_label(step.stage_type),
        name=step.name,
        role_name=step.role_name,
        objective=step.objective,
        prompt_template=step.prompt_template,
        provider_hint=step.provider_hint,
        provider_model=step.provider_model,
        is_enabled=step.is_enabled,
        is_required=step.is_required,
        removable=stage_is_removable(step.stage_type),
        prompt_enabled=stage_supports_prompt(step.stage_type),
        editable=True,
        structure_editable=True,
        content_editable=stage_supports_prompt(step.stage_type),
        sort_order=step.sort_order,
    )


def _build_blogger_flow(db: Session, channel_id: str, blog_id: int) -> PromptFlowRead:
    blog = get_blog(db, blog_id)
    if not blog:
        raise ValueError("Blog not found")
    steps = [_serialize_blogger_step(channel_id, step) for step in list_workflow_steps(blog)]
    available_stage_types = [
        stage.value if hasattr(stage, "value") else str(stage) for stage in get_missing_optional_stage_types(blog)
    ]
    return PromptFlowRead(
        channel_id=channel_id,
        channel_name=blog.name,
        provider="blogger",
        structure_editable=True,
        content_editable=True,
        available_stage_types=available_stage_types,
        steps=steps,
        backup_directory=_blogger_backup_relative_dir(blog),
    )


def _build_cloudflare_flow(db: Session, channel_id: str) -> PromptFlowRead:
    overview = get_cloudflare_overview(db)
    bundle = get_cloudflare_prompt_bundle(db)
    stage_order = {stage: index for index, stage in enumerate(bundle.get("stages", []), start=1)}
    category_order = {item.get("slug"): index for index, item in enumerate(bundle.get("categories", []), start=1)}
    templates = sorted(
        bundle.get("templates", []),
        key=lambda item: (
            category_order.get(item.get("categorySlug"), 999),
            stage_order.get(item.get("stage"), 999),
            item.get("id", ""),
        ),
    )
    steps = [
        PromptFlowStepRead(
            id=f"{template.get('categorySlug')}::{template.get('stage')}",
            channel_id=channel_id,
            provider="cloudflare",
            stage_type=template.get("stage", "prompt"),
            stage_label=template.get("stage", "prompt"),
            name=template.get("name") or f"{template.get('categoryName')} {template.get('stage')}",
            role_name=None,
            objective=template.get("objective") or f"{template.get('categoryName')} prompt",
            prompt_template=template.get("content", ""),
            provider_hint="cloudflare",
            provider_model=template.get("providerModel"),
            is_enabled=bool(template.get("isEnabled", True)),
            is_required=False,
            removable=False,
            prompt_enabled=True,
            editable=True,
            structure_editable=False,
            content_editable=True,
            sort_order=(category_order.get(template.get("categorySlug"), 999) * 100)
            + stage_order.get(template.get("stage"), 0),
        )
        for template in templates
    ]
    return PromptFlowRead(
        channel_id=channel_id,
        channel_name=overview.get("channel_name") or overview.get("site_title") or "Cloudflare",
        provider="cloudflare",
        structure_editable=False,
        content_editable=True,
        available_stage_types=[],
        steps=steps,
        backup_directory=_named_channel_backup_relative_dir(
            "cloudflare",
            overview.get("channel_name") or overview.get("site_title") or "Cloudflare",
            channel_id=channel_id,
        ),
    )


def _build_platform_flow(db: Session, channel_id: str) -> PromptFlowRead:
    channel = get_managed_channel(db, channel_id)
    if channel is None:
        raise ValueError("Channel not found")
    steps = [
        PromptFlowStepRead(
            id=str(item["id"]),
            channel_id=channel.channel_id,
            provider=channel.provider,
            stage_type=str(item["stage_type"]),
            stage_label=str(item["stage_label"]),
            name=str(item["name"]),
            role_name=str(item["role_name"]) if item["role_name"] is not None else None,
            objective=str(item["objective"]) if item["objective"] is not None else None,
            prompt_template=str(item["prompt_template"] or ""),
            provider_hint=str(item["provider_hint"]) if item["provider_hint"] is not None else None,
            provider_model=str(item["provider_model"]) if item["provider_model"] is not None else None,
            is_enabled=bool(item["is_enabled"]),
            is_required=bool(item["is_required"]),
            removable=bool(item["removable"]),
            prompt_enabled=bool(item["prompt_enabled"]),
            editable=bool(item["editable"]),
            structure_editable=bool(item["structure_editable"]),
            content_editable=bool(item["content_editable"]),
            sort_order=int(item["sort_order"]),
        )
        for item in list_platform_prompt_steps(db, channel)
    ]
    return PromptFlowRead(
        channel_id=channel.channel_id,
        channel_name=channel.display_name,
        provider=channel.provider,
        structure_editable=False,
        content_editable=True,
        available_stage_types=[],
        steps=steps,
        backup_directory=_named_channel_backup_relative_dir(
            channel.provider,
            channel.display_name,
            channel_id=channel.channel_id,
        ),
    )


def _step_backup_relative_path(flow: PromptFlowRead, step: PromptFlowStepRead, index: int) -> str | None:
    if not step.prompt_enabled:
        return None

    channel_dir = Path(flow.backup_directory or _default_channel_backup_relative_dir(flow.channel_id))
    if flow.provider == "cloudflare":
        category_slug, _separator, _stage = str(step.id).partition("::")
        stage_index = DEFAULT_PROMPT_STAGES.index(step.stage_type) + 1 if step.stage_type in DEFAULT_PROMPT_STAGES else index
        return (
            channel_dir
            / "steps"
            / _safe_segment(category_slug, "default")
            / f"{stage_index:02d}-{_stage_file_slug(step.stage_type)}.md"
        ).as_posix()

    return (channel_dir / "steps" / f"{index:02d}-{_stage_file_slug(step.stage_type)}.md").as_posix()


def attach_backup_metadata(flow: PromptFlowRead) -> PromptFlowRead:
    flow.backup_directory = flow.backup_directory or _default_channel_backup_relative_dir(flow.channel_id)
    for index, step in enumerate(sorted(flow.steps, key=lambda item: (item.sort_order, item.id)), start=1):
        step.backup_relative_path = _step_backup_relative_path(flow, step, index)
        step.backup_exists = bool(step.backup_relative_path and (_prompt_root() / step.backup_relative_path).exists())
    return flow


def sync_prompt_flow_backup(flow: PromptFlowRead) -> PromptFlowRead:
    attach_backup_metadata(flow)

    root = _prompt_root()
    channel_dir = root / str(flow.backup_directory or _default_channel_backup_relative_dir(flow.channel_id))
    steps_dir = channel_dir / "steps"
    legacy_channel_dir = root / _default_channel_backup_relative_dir(flow.channel_id)

    channel_dir.mkdir(parents=True, exist_ok=True)
    _safe_remove_tree(steps_dir, root=root)
    steps_dir.mkdir(parents=True, exist_ok=True)

    for step in flow.steps:
        if not step.backup_relative_path:
            continue
        _write_text(root / step.backup_relative_path, step.prompt_template)

    metadata = {
        "channel_id": flow.channel_id,
        "channel_name": flow.channel_name,
        "provider": flow.provider,
        "backup_directory": flow.backup_directory,
        "synced_at": _utc_now_iso(),
        "steps": [
            {
                "id": step.id,
                "stage_type": step.stage_type,
                "stage_label": step.stage_label,
                "name": step.name,
                "role_name": step.role_name,
                "objective": step.objective,
                "provider_hint": step.provider_hint,
                "provider_model": step.provider_model,
                "is_enabled": step.is_enabled,
                "is_required": step.is_required,
                "prompt_enabled": step.prompt_enabled,
                "sort_order": step.sort_order,
                "backup_relative_path": step.backup_relative_path,
            }
            for step in flow.steps
        ],
    }
    _write_json(channel_dir / "channel.json", metadata)
    _cleanup_stale_channel_dirs(flow, root=root, current_channel_dir=channel_dir)
    if legacy_channel_dir != channel_dir:
        _safe_remove_tree(legacy_channel_dir, root=root)
    return attach_backup_metadata(flow)


def build_prompt_flow(db: Session, channel_id: str, *, sync_backup: bool = False) -> PromptFlowRead:
    provider, raw_id = _parse_channel_id(channel_id)
    if provider == "blogger":
        flow = _build_blogger_flow(db, channel_id, int(raw_id))
    elif provider in {"youtube", "instagram"}:
        flow = _build_platform_flow(db, channel_id)
    else:
        flow = _build_cloudflare_flow(db, channel_id)

    if sync_backup:
        return sync_prompt_flow_backup(flow)
    return attach_backup_metadata(flow)


def sync_all_channel_prompt_backups(db: Session, *, include_disconnected: bool = True) -> list[PromptFlowRead]:
    flows: list[PromptFlowRead] = []
    channels = list_managed_channels(db, include_disconnected=include_disconnected)
    for channel in channels:
        try:
            flows.append(build_prompt_flow(db, channel.channel_id, sync_backup=True))
        except ValueError:
            continue
    return flows
