from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
from textwrap import dedent

from slugify import slugify
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import BlogAgentConfig, WorkflowStageType
from app.schemas.api import PromptFlowRead, PromptFlowStepRead, PromptFlowStepUpdate
from app.services.platform.blog_service import (
    get_stage_definition,
    get_blog,
    get_profile_definition,
    get_missing_optional_stage_types,
    list_workflow_steps,
    stage_is_removable,
    stage_label,
    stage_supports_prompt,
)
from app.services.cloudflare.cloudflare_channel_service import get_cloudflare_overview, get_cloudflare_prompt_bundle
from app.services.platform.platform_service import PLATFORM_PROMPT_STEPS
from app.services.integrations.settings_service import get_settings_map, upsert_settings
from app.services.platform.workspace_service import get_managed_channel, list_managed_channels

_SAFE_SEGMENT_RE = re.compile(r"[^a-zA-Z0-9._-]+")
_PLATFORM_REQUIRED_STAGE_TYPES = {"platform_publish"}
_BLOGGER_AUXILIARY_PROMPT_FILES: dict[str, tuple[str, ...]] = {
    "korea_travel": ("travel_inline_collage_prompt.md",),
    "world_mystery": ("mystery_inline_collage_prompt.md",),
    "custom": (),
}
_CLOUDFLARE_CANONICAL_STAGE_TYPES: tuple[WorkflowStageType, ...] = (
    WorkflowStageType.TOPIC_DISCOVERY,
    WorkflowStageType.ARTICLE_GENERATION,
    WorkflowStageType.IMAGE_PROMPT_GENERATION,
    WorkflowStageType.RELATED_POSTS,
    WorkflowStageType.IMAGE_GENERATION,
    WorkflowStageType.HTML_ASSEMBLY,
    WorkflowStageType.PUBLISHING,
)


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


def _resolve_blogger_profile_key(blog) -> str:
    profile_key = str(getattr(blog, "profile_key", "") or "").strip()
    if profile_key:
        return profile_key
    if str(getattr(blog, "content_category", "") or "").strip() == "travel":
        return "korea_travel"
    if str(getattr(blog, "content_category", "") or "").strip() == "mystery":
        return "world_mystery"
    return "custom"


def _read_root_prompt_file(file_name: str | None) -> str | None:
    normalized = str(file_name or "").strip()
    if not normalized:
        return None
    path = _prompt_root() / normalized
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _blogger_prompt_file_map(blog) -> dict[str, str]:
    profile = get_profile_definition(_resolve_blogger_profile_key(blog))
    return {
        blueprint.stage_type.value if hasattr(blueprint.stage_type, "value") else str(blueprint.stage_type): blueprint.prompt_file
        for blueprint in profile.workflow_steps
        if blueprint.prompt_file
    }


def _blogger_auxiliary_prompt_files(blog) -> list[str]:
    profile_key = _resolve_blogger_profile_key(blog)
    return list(_BLOGGER_AUXILIARY_PROMPT_FILES.get(profile_key, ()))


def _stage_file_slug(stage_type: str) -> str:
    normalized = slugify(str(stage_type or "").strip(), separator="-") or _safe_segment(stage_type, "prompt")
    return normalized or "prompt"


def _stage_prompt_file_name(stage_type: str) -> str:
    normalized = str(stage_type or "").strip()
    safe_name = normalized or _stage_file_slug(stage_type)
    return f"{safe_name}.md"


def _normalize_prompt_text(content: str | None) -> str:
    normalized = str(content or "").strip()
    return normalized + ("\n" if normalized else "")


def _write_text(path: Path, content: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_normalize_prompt_text(content), encoding="utf-8")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _make_path_writable(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        return


def _handle_remove_readonly(func, path: str, exc_info) -> None:
    target = Path(path)
    original_error = exc_info[1]
    _make_path_writable(target)
    try:
        func(path)
    except OSError as retry_error:
        raise retry_error from original_error


def _safe_remove_tree(path: Path, *, root: Path) -> None:
    if not path.exists():
        return
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    if resolved_root not in resolved_path.parents:
        raise ValueError("Refusing to remove a path outside the prompt backup root")
    for candidate in sorted(resolved_path.rglob("*"), reverse=True):
        _make_path_writable(candidate)
    _make_path_writable(resolved_path)
    shutil.rmtree(resolved_path, onerror=_handle_remove_readonly)


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


def _cloudflare_step_objective(category_name: str, stage_type: WorkflowStageType) -> str:
    definition = get_stage_definition(stage_type)
    return f"{category_name} 카테고리에서 {definition.default_objective}"


def _default_cloudflare_prompt(channel_name: str, category_name: str, stage_type: WorkflowStageType) -> str:
    definition = get_stage_definition(stage_type)
    return _normalize_prompt_text(
        dedent(
            f"""
            You are the {definition.default_role_name} for the "{category_name}" category in the "{channel_name}" Cloudflare channel.

            Objective
            - {_cloudflare_step_objective(category_name, stage_type)}

            Execution rules
            - Stay inside the `{stage_type.value}` stage only.
            - Keep the output aligned with the "{category_name}" category positioning.
            - Return concrete, production-ready deliverables without filler analysis.
            """
        ).strip()
    )


def _cloudflare_system_step_backup(channel_name: str, category_name: str, stage_type: WorkflowStageType) -> str:
    definition = get_stage_definition(stage_type)
    return _normalize_prompt_text(
        dedent(
            f"""
            [Cloudflare System Step Backup]
            Channel: {channel_name}
            Category: {category_name}
            Stage: {stage_type.value}

            Objective
            - {_cloudflare_step_objective(category_name, stage_type)}

            Notes
            - This stage is part of the fixed 7-step Cloudflare blog pipeline.
            - The runtime executes this stage automatically.
            - This file is written to keep the backup folder structure consistent with the settings UI.
            - Prompt editing is not supported for this stage.
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
    channel_name = overview.get("channel_name") or overview.get("site_title") or "Cloudflare"
    stage_order = {
        stage_type.value: index for index, stage_type in enumerate(_CLOUDFLARE_CANONICAL_STAGE_TYPES, start=1)
    }
    category_order = {item.get("slug"): index for index, item in enumerate(bundle.get("categories", []), start=1)}
    templates_by_key = {
        (str(item.get("categorySlug") or "").strip(), str(item.get("stage") or "").strip()): item
        for item in bundle.get("templates", [])
        if str(item.get("categorySlug") or "").strip() and str(item.get("stage") or "").strip()
    }
    steps: list[PromptFlowStepRead] = []
    for category in bundle.get("categories", []):
        category_slug = str(category.get("slug") or "").strip()
        category_name = str(category.get("name") or category_slug or "Cloudflare").strip() or "Cloudflare"
        if not category_slug:
            continue
        category_rank = category_order.get(category_slug, 999)
        for stage_type in _CLOUDFLARE_CANONICAL_STAGE_TYPES:
            template = templates_by_key.get((category_slug, stage_type.value))
            definition = get_stage_definition(stage_type)
            prompt_enabled = stage_supports_prompt(stage_type)
            steps.append(
                PromptFlowStepRead(
                    id=f"{category_slug}::{stage_type.value}",
                    channel_id=channel_id,
                    provider="cloudflare",
                    stage_type=stage_type.value,
                    stage_label=stage_label(stage_type),
                    name=(
                        str(template.get("name") or "").strip()
                        if template
                        else f"{category_name} · {definition.default_name}"
                    ),
                    role_name=definition.default_role_name,
                    objective=(
                        str(template.get("objective") or "").strip()
                        if template
                        else _cloudflare_step_objective(category_name, stage_type)
                    ),
                    prompt_template=(
                        _normalize_prompt_text(str(template.get("content") or ""))
                        if template
                        else (
                            _default_cloudflare_prompt(channel_name, category_name, stage_type)
                            if prompt_enabled
                            else _cloudflare_system_step_backup(channel_name, category_name, stage_type)
                        )
                    ),
                    provider_hint=(
                        "cloudflare"
                        if prompt_enabled
                        else (definition.provider_hint or "cloudflare")
                    ),
                    provider_model=(
                        str(template.get("providerModel") or "").strip() or definition.provider_model
                        if template
                        else definition.provider_model
                    ),
                    is_enabled=bool(template.get("isEnabled", True)) if template else True,
                    is_required=definition.is_required,
                    removable=False,
                    prompt_enabled=prompt_enabled,
                    editable=prompt_enabled,
                    structure_editable=False,
                    content_editable=prompt_enabled,
                    sort_order=(category_rank * 100) + stage_order[stage_type.value],
                )
            )
    return PromptFlowRead(
        channel_id=channel_id,
        channel_name=channel_name,
        provider="cloudflare",
        structure_editable=False,
        content_editable=True,
        available_stage_types=[],
        steps=steps,
        backup_directory=_named_channel_backup_relative_dir(
            "cloudflare",
            channel_name,
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


def _step_backup_file_name(db: Session, flow: PromptFlowRead, step: PromptFlowStepRead) -> str | None:
    if flow.provider == "cloudflare":
        return _stage_prompt_file_name(step.stage_type)

    if not step.prompt_enabled:
        return None

    if flow.provider == "blogger":
        _provider, raw_id = _parse_channel_id(flow.channel_id)
        blog = get_blog(db, int(raw_id))
        if blog:
            prompt_file_name = _blogger_prompt_file_map(blog).get(step.stage_type)
            if prompt_file_name:
                return prompt_file_name

    return _stage_prompt_file_name(step.stage_type)


def _step_backup_relative_path(db: Session, flow: PromptFlowRead, step: PromptFlowStepRead, index: int) -> str | None:
    file_name = _step_backup_file_name(db, flow, step)
    if not file_name:
        return None

    channel_dir = Path(flow.backup_directory or _default_channel_backup_relative_dir(flow.channel_id))
    if flow.provider == "cloudflare":
        category_slug, _separator, _stage = str(step.id).partition("::")
        return (channel_dir / _safe_segment(category_slug, "default") / file_name).as_posix()

    return (channel_dir / file_name).as_posix()


def _auxiliary_backup_files(db: Session, flow: PromptFlowRead) -> dict[str, str]:
    if flow.provider != "blogger":
        return {}

    _provider, raw_id = _parse_channel_id(flow.channel_id)
    blog = get_blog(db, int(raw_id))
    if not blog:
        return {}

    channel_dir = Path(flow.backup_directory or _default_channel_backup_relative_dir(flow.channel_id))
    files: dict[str, str] = {}
    for file_name in _blogger_auxiliary_prompt_files(blog):
        content = _read_root_prompt_file(file_name)
        if content is None:
            continue
        files[(channel_dir / file_name).as_posix()] = content
    return files


def attach_backup_metadata(db: Session, flow: PromptFlowRead) -> PromptFlowRead:
    flow.backup_directory = flow.backup_directory or _default_channel_backup_relative_dir(flow.channel_id)
    for index, step in enumerate(sorted(flow.steps, key=lambda item: (item.sort_order, item.id)), start=1):
        step.backup_relative_path = _step_backup_relative_path(db, flow, step, index)
        step.backup_exists = bool(step.backup_relative_path and (_prompt_root() / step.backup_relative_path).exists())
    return flow


def sync_prompt_flow_backup(db: Session, flow: PromptFlowRead) -> PromptFlowRead:
    attach_backup_metadata(db, flow)

    root = _prompt_root()
    channel_dir = root / str(flow.backup_directory or _default_channel_backup_relative_dir(flow.channel_id))
    legacy_channel_dir = root / _default_channel_backup_relative_dir(flow.channel_id)

    if channel_dir.exists():
        _safe_remove_tree(channel_dir, root=root)
    channel_dir.mkdir(parents=True, exist_ok=True)

    for step in flow.steps:
        if not step.backup_relative_path:
            continue
        _write_text(root / step.backup_relative_path, step.prompt_template)

    auxiliary_files = _auxiliary_backup_files(db, flow)
    for relative_path, content in auxiliary_files.items():
        _write_text(root / relative_path, content)

    metadata = {
        "channel_id": flow.channel_id,
        "channel_name": flow.channel_name,
        "provider": flow.provider,
        "backup_directory": flow.backup_directory,
        "backup_files": sorted(
            [step.backup_relative_path for step in flow.steps if step.backup_relative_path] + list(auxiliary_files.keys())
        ),
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
    return attach_backup_metadata(db, flow)


def build_prompt_flow(db: Session, channel_id: str, *, sync_backup: bool = False) -> PromptFlowRead:
    provider, raw_id = _parse_channel_id(channel_id)
    if provider == "blogger":
        flow = _build_blogger_flow(db, channel_id, int(raw_id))
    elif provider in {"youtube", "instagram"}:
        flow = _build_platform_flow(db, channel_id)
    else:
        flow = _build_cloudflare_flow(db, channel_id)

    if sync_backup:
        return sync_prompt_flow_backup(db, flow)
    return attach_backup_metadata(db, flow)


def sync_all_channel_prompt_backups(db: Session, *, include_disconnected: bool = True) -> list[PromptFlowRead]:
    flows: list[PromptFlowRead] = []
    channels = list_managed_channels(db, include_disconnected=include_disconnected)
    for channel in channels:
        try:
            flows.append(build_prompt_flow(db, channel.channel_id, sync_backup=True))
        except ValueError:
            continue
    return flows
