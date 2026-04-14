from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.api import ManagedChannelRead, PromptFlowRead, PromptFlowReorderRequest, PromptFlowStepUpdate, WorkflowStepCreate
from app.services.platform.blog_service import create_workflow_step, delete_workflow_step, get_blog, get_blog_summary_map, list_blogs, reorder_workflow_steps, update_blog_agent
from app.services.content.channel_prompt_service import build_prompt_flow, save_platform_prompt_step
from app.services.cloudflare.cloudflare_channel_service import save_cloudflare_prompt
from app.services.platform.workspace_service import list_managed_channels, serialize_managed_channel

router = APIRouter(prefix="/channels", tags=["channels"])


def _parse_channel_id(channel_id: str) -> tuple[str, str]:
    if ":" not in channel_id:
        raise HTTPException(status_code=404, detail="Channel not found")
    provider, raw_id = channel_id.split(":", 1)
    if provider not in {"blogger", "cloudflare", "youtube", "instagram"} or not raw_id:
        raise HTTPException(status_code=404, detail="Channel not found")
    return provider, raw_id


def _raise_prompt_flow_error(exc: ValueError) -> None:
    detail = str(exc) or "Prompt flow request failed"
    status_code = 404 if "not found" in detail.lower() else 400
    raise HTTPException(status_code=status_code, detail=detail) from exc


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
    try:
        return build_prompt_flow(db, channel_id, sync_backup=True)
    except ValueError as exc:
        _raise_prompt_flow_error(exc)


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
    return build_prompt_flow(db, channel_id, sync_backup=True)


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
    return build_prompt_flow(db, channel_id, sync_backup=True)


@router.patch("/{channel_id}/prompt-flow/steps/{step_id}", response_model=PromptFlowRead)
def update_channel_prompt_flow_step(
    channel_id: str,
    step_id: str,
    payload: PromptFlowStepUpdate,
    db: Session = Depends(get_db),
) -> PromptFlowRead:
    provider, raw_id = _parse_channel_id(channel_id)
    try:
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
        elif provider in {"youtube", "instagram"}:
            save_platform_prompt_step(db, channel_id=channel_id, step_id=step_id, payload=payload)
        else:
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
        return build_prompt_flow(db, channel_id, sync_backup=True)
    except ValueError as exc:
        _raise_prompt_flow_error(exc)


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
    return build_prompt_flow(db, channel_id, sync_backup=True)
