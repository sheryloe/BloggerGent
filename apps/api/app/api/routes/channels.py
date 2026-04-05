from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.entities import BlogAgentConfig, WorkflowStageType
from app.schemas.api import (
    BlogAgentConfigUpdate,
    ManagedChannelRead,
    PromptFlowRead,
    PromptFlowReorderRequest,
    PromptFlowStepRead,
    PromptFlowStepUpdate,
    WorkflowStepCreate,
)
from app.services.blog_service import (
    create_workflow_step,
    delete_workflow_step,
    get_blog,
    get_blog_summary_map,
    get_missing_optional_stage_types,
    list_blogs,
    list_workflow_steps,
    reorder_workflow_steps,
    stage_is_removable,
    stage_label,
    stage_supports_prompt,
    update_blog_agent,
)
from app.services.cloudflare_channel_service import get_cloudflare_overview, get_cloudflare_prompt_bundle, save_cloudflare_prompt
from app.services.workspace_service import get_managed_channel, list_managed_channels, list_platform_prompt_steps, serialize_managed_channel

router = APIRouter(prefix="/channels", tags=["channels"])


def _parse_channel_id(channel_id: str) -> tuple[str, str]:
    if ":" not in channel_id:
        raise HTTPException(status_code=404, detail="Channel not found")
    provider, raw_id = channel_id.split(":", 1)
    if provider not in {"blogger", "cloudflare", "youtube", "instagram"} or not raw_id:
        raise HTTPException(status_code=404, detail="Channel not found")
    return provider, raw_id


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
        raise HTTPException(status_code=404, detail="Blog not found")
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
            name=template.get("name") or f"{template.get('categoryName')} · {template.get('stage')}",
            role_name=None,
            objective=template.get("objective") or f"{template.get('categoryName')} 단계 프롬프트",
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
    )


def _build_platform_flow(db: Session, channel_id: str) -> PromptFlowRead:
    channel = get_managed_channel(db, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    return PromptFlowRead(
        channel_id=channel.channel_id,
        channel_name=channel.display_name,
        provider=channel.provider,
        structure_editable=False,
        content_editable=True,
        available_stage_types=[],
        steps=[
            PromptFlowStepRead(
                id=item["id"],
                channel_id=channel.channel_id,
                provider=channel.provider,
                stage_type=item["stage_type"],
                stage_label=item["stage_label"],
                name=item["name"],
                role_name=item["role_name"],
                objective=item["objective"],
                prompt_template=item["prompt_template"],
                provider_hint=item["provider_hint"],
                provider_model=item["provider_model"],
                is_enabled=True,
                is_required=item["stage_type"] == "platform_publish",
                removable=item["stage_type"] != "platform_publish",
                prompt_enabled=bool(item["prompt_template"]),
                editable=False,
                structure_editable=False,
                content_editable=True,
                sort_order=index * 10,
            )
            for index, item in enumerate(list_platform_prompt_steps(channel.provider), start=1)
        ],
    )


@router.get("", response_model=list[ManagedChannelRead])
def get_channels(
    include_disconnected: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> list[ManagedChannelRead]:
    blogs = list_blogs(db)
    summary_map = get_blog_summary_map(db, [blog.id for blog in blogs]) if blogs else {}
    channels = [
        ManagedChannelRead(**serialize_managed_channel(channel))
        for channel in list_managed_channels(db, include_disconnected=include_disconnected)
    ]

    for channel in channels:
        if channel.provider != "blogger":
            continue
        raw_id = channel.channel_id.split(":", 1)[1]
        blog_id = int(raw_id)
        summary = asdict(summary_map[blog_id]) if blog_id in summary_map else {}
        channel.posts_count = summary.get("published_posts", channel.posts_count)
        channel.pending_items = max(channel.pending_items, summary.get("job_count", 0) - summary.get("completed_jobs", 0))

    return channels


@router.get("/{channel_id}/prompt-flow", response_model=PromptFlowRead)
def get_channel_prompt_flow(channel_id: str, db: Session = Depends(get_db)) -> PromptFlowRead:
    provider, raw_id = _parse_channel_id(channel_id)
    if provider == "blogger":
        return _build_blogger_flow(db, channel_id, int(raw_id))
    if provider in {"youtube", "instagram"}:
        return _build_platform_flow(db, channel_id)
    return _build_cloudflare_flow(db, channel_id)


@router.post("/{channel_id}/prompt-flow/steps", response_model=PromptFlowRead, status_code=status.HTTP_201_CREATED)
def create_channel_prompt_flow_step(
    channel_id: str,
    payload: WorkflowStepCreate,
    db: Session = Depends(get_db),
) -> PromptFlowRead:
    provider, raw_id = _parse_channel_id(channel_id)
    if provider != "blogger":
        raise HTTPException(status_code=400, detail="Structure editing is not supported for this channel")
    blog = get_blog(db, int(raw_id))
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")
    create_workflow_step(db, blog, payload.stage_type)
    return _build_blogger_flow(db, channel_id, blog.id)


@router.post("/{channel_id}/prompt-flow/reorder", response_model=PromptFlowRead)
def reorder_channel_prompt_flow(
    channel_id: str,
    payload: PromptFlowReorderRequest,
    db: Session = Depends(get_db),
) -> PromptFlowRead:
    provider, raw_id = _parse_channel_id(channel_id)
    if provider != "blogger":
        raise HTTPException(status_code=400, detail="Structure editing is not supported for this channel")
    blog = get_blog(db, int(raw_id))
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")
    ordered_ids = [int(item) for item in payload.ordered_ids]
    reorder_workflow_steps(db, blog, ordered_ids)
    return _build_blogger_flow(db, channel_id, blog.id)


@router.patch("/{channel_id}/prompt-flow/steps/{step_id}", response_model=PromptFlowRead)
def update_channel_prompt_flow_step(
    channel_id: str,
    step_id: str,
    payload: PromptFlowStepUpdate,
    db: Session = Depends(get_db),
) -> PromptFlowRead:
    provider, raw_id = _parse_channel_id(channel_id)
    if provider == "blogger":
        blog = get_blog(db, int(raw_id))
        if not blog:
            raise HTTPException(status_code=404, detail="Blog not found")
        step = next((item for item in blog.agent_configs if item.id == int(step_id)), None)
        if not step:
            raise HTTPException(status_code=404, detail="Workflow step not found")
        update_blog_agent(
            db,
            step,
            name=payload.name or step.name,
            role_name=payload.role_name or step.role_name,
            objective=payload.objective if payload.objective is not None else step.objective,
            prompt_template=payload.prompt_template if payload.prompt_template is not None else step.prompt_template,
            provider_hint=payload.provider_hint if payload.provider_hint is not None else step.provider_hint,
            provider_model=payload.provider_model if payload.provider_model is not None else step.provider_model,
            is_enabled=payload.is_enabled if payload.is_enabled is not None else step.is_enabled,
        )
        return _build_blogger_flow(db, channel_id, blog.id)

    category_slug, stage = step_id.split("::", 1)
    if payload.prompt_template is None:
        raise HTTPException(status_code=400, detail="Prompt content is required")
    save_cloudflare_prompt(
        db,
        category_key=category_slug,
        stage=stage,
        content=payload.prompt_template,
        name=payload.name,
        objective=payload.objective,
        is_enabled=payload.is_enabled,
        provider_model=payload.provider_model,
    )
    return _build_cloudflare_flow(db, channel_id)


@router.delete("/{channel_id}/prompt-flow/steps/{step_id}", response_model=PromptFlowRead)
def delete_channel_prompt_flow_step(channel_id: str, step_id: str, db: Session = Depends(get_db)) -> PromptFlowRead:
    provider, raw_id = _parse_channel_id(channel_id)
    if provider != "blogger":
        raise HTTPException(status_code=400, detail="Structure editing is not supported for this channel")
    blog = get_blog(db, int(raw_id))
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")
    step = next((item for item in blog.agent_configs if item.id == int(step_id)), None)
    if not step:
        raise HTTPException(status_code=404, detail="Workflow step not found")
    delete_workflow_step(db, blog, step)
    return _build_blogger_flow(db, channel_id, blog.id)
