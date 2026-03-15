from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.entities import BlogAgentConfig, JobStatus, PublishMode, WorkflowStageType
from app.schemas.api import (
    BlogAgentConfigRead,
    BlogAgentConfigUpdate,
    BlogConnectionOptionsRead,
    BlogConnectionUpdate,
    BlogImportOptionsRead,
    BlogImportRequest,
    BlogRead,
    BlogUpdate,
    DiscoveryRunResponse,
    WorkflowStepCreate,
    WorkflowStepReorder,
)
from app.services.blog_service import (
    create_workflow_step,
    delete_workflow_step,
    get_agent_config,
    get_blog,
    get_blog_by_remote_id,
    get_blog_summary_map,
    get_missing_optional_stage_types,
    import_blog_from_remote,
    list_blog_profiles,
    list_blogs,
    list_workflow_steps,
    reorder_workflow_steps,
    stage_is_removable,
    stage_is_required,
    stage_label,
    stage_supports_prompt,
    update_blog,
    update_blog_agent,
    update_blog_connections,
)
from app.services.blogger_oauth_service import BloggerOAuthError, list_blogger_blogs
from app.services.google_reporting_service import list_analytics_properties, list_search_console_sites
from app.services.providers.base import ProviderRuntimeError
from app.tasks.pipeline import discover_topics_and_enqueue

router = APIRouter()


def _load_google_reference_data(db: Session) -> dict:
    payload = {
        "available_blogs": [],
        "search_console_sites": [],
        "analytics_properties": [],
        "warnings": [],
    }
    try:
        payload["available_blogs"] = list_blogger_blogs(db)
    except BloggerOAuthError as exc:
        payload["warnings"].append(exc.detail)

    try:
        payload["search_console_sites"] = list_search_console_sites(db)
    except BloggerOAuthError as exc:
        payload["warnings"].append(f"Search Console 목록을 가져오지 못했습니다: {exc.detail}")

    try:
        payload["analytics_properties"] = list_analytics_properties(db)
    except BloggerOAuthError as exc:
        payload["warnings"].append(f"GA4 속성 목록을 가져오지 못했습니다: {exc.detail}")

    return payload


def _serialize_workflow_step(step: BlogAgentConfig) -> dict:
    return {
        "id": step.id,
        "agent_key": step.agent_key,
        "stage_type": step.stage_type,
        "name": step.name,
        "role_name": step.role_name,
        "objective": step.objective,
        "prompt_template": step.prompt_template,
        "provider_hint": step.provider_hint,
        "is_enabled": step.is_enabled,
        "is_required": step.is_required,
        "sort_order": step.sort_order,
        "created_at": step.created_at,
        "updated_at": step.updated_at,
        "stage_label": stage_label(step.stage_type),
        "prompt_enabled": stage_supports_prompt(step.stage_type),
        "removable": stage_is_removable(step.stage_type),
    }


def _find_selected_summary(blog, google_refs: dict) -> dict:
    blogger = next((item for item in google_refs["available_blogs"] if item.get("id") == (blog.blogger_blog_id or "")), None)
    search_console = next(
        (item for item in google_refs["search_console_sites"] if item.get("site_url") == (blog.search_console_site_url or "")),
        None,
    )
    analytics = next(
        (item for item in google_refs["analytics_properties"] if item.get("property_id") == (blog.ga4_property_id or "")),
        None,
    )
    return {
        "blogger": blogger,
        "search_console": search_console,
        "analytics": analytics,
    }


def _local_selected_summary(blog) -> dict:
    blogger = None
    if blog.blogger_blog_id:
        blogger = {
            "id": blog.blogger_blog_id,
            "name": blog.name,
            "description": blog.description,
            "url": blog.blogger_url,
            "published": None,
            "updated": None,
            "locale": None,
            "posts_total_items": None,
            "pages_total_items": None,
        }
    search_console = {"site_url": blog.search_console_site_url, "permission_level": None} if blog.search_console_site_url else None
    analytics = (
        {
            "property_id": blog.ga4_property_id,
            "display_name": blog.ga4_property_id,
            "property_type": None,
            "parent_display_name": None,
        }
        if blog.ga4_property_id
        else None
    )
    return {
        "blogger": blogger,
        "search_console": search_console,
        "analytics": analytics,
    }


def _find_selected_summary_with_fallback(blog, google_refs: dict | None = None) -> dict:
    local_summary = _local_selected_summary(blog)
    if not google_refs:
        return local_summary
    remote_summary = _find_selected_summary(blog, google_refs)
    return {
        "blogger": remote_summary["blogger"] or local_summary["blogger"],
        "search_console": remote_summary["search_console"] or local_summary["search_console"],
        "analytics": remote_summary["analytics"] or local_summary["analytics"],
    }


def _serialize_blog(blog, google_refs: dict | None = None, summary_metrics=None) -> dict:
    summary = summary_metrics or {}
    return {
        "id": blog.id,
        "name": blog.name,
        "slug": blog.slug,
        "description": blog.description,
        "content_category": blog.content_category,
        "primary_language": blog.primary_language,
        "profile_key": blog.profile_key,
        "target_audience": blog.target_audience,
        "content_brief": blog.content_brief,
        "blogger_blog_id": blog.blogger_blog_id,
        "blogger_url": blog.blogger_url,
        "search_console_site_url": blog.search_console_site_url,
        "ga4_property_id": blog.ga4_property_id,
        "publish_mode": blog.publish_mode,
        "is_active": blog.is_active,
        "created_at": blog.created_at,
        "updated_at": blog.updated_at,
        "workflow_steps": [_serialize_workflow_step(step) for step in list_workflow_steps(blog)],
        "selected_connections": _find_selected_summary_with_fallback(blog, google_refs),
        "job_count": summary.get("job_count", 0),
        "completed_jobs": summary.get("completed_jobs", 0),
        "failed_jobs": summary.get("failed_jobs", 0),
        "published_posts": summary.get("published_posts", 0),
        "latest_topic_keywords": summary.get("latest_topic_keywords", []),
        "latest_published_url": summary.get("latest_published_url"),
    }


def _workflow_list_response(blog) -> list[dict]:
    return [_serialize_workflow_step(step) for step in list_workflow_steps(blog)]


def _validate_connection_value(items: list[dict], key: str, value: str | None, label: str) -> None:
    if not value:
        return
    if any(item.get(key) == value for item in items):
        return
    raise HTTPException(status_code=422, detail=f"선택한 {label} 값이 현재 Google 연결 목록에 없습니다.")


@router.get("", response_model=list[BlogRead])
def get_blogs(db: Session = Depends(get_db)) -> list[dict]:
    blogs = list_blogs(db)
    summary_map = get_blog_summary_map(db, [blog.id for blog in blogs])
    return [
        _serialize_blog(
            blog,
            summary_metrics=asdict(summary_map[blog.id]) if blog.id in summary_map else None,
        )
        for blog in blogs
    ]


@router.get("/import-options", response_model=BlogImportOptionsRead)
def get_blog_import_options(db: Session = Depends(get_db)) -> dict:
    google_refs = _load_google_reference_data(db)
    imported_ids = [blog.blogger_blog_id for blog in list_blogs(db) if (blog.blogger_blog_id or "").strip()]
    return {
        "available_blogs": [
            blog for blog in google_refs["available_blogs"] if blog.get("id") not in set(imported_ids)
        ],
        "profiles": list_blog_profiles(),
        "imported_blogger_blog_ids": imported_ids,
        "warnings": google_refs["warnings"],
    }


@router.post("/import", response_model=BlogRead)
def import_blog(payload: BlogImportRequest, db: Session = Depends(get_db)) -> dict:
    google_refs = _load_google_reference_data(db)
    remote_blog = next((item for item in google_refs["available_blogs"] if item.get("id") == payload.blogger_blog_id), None)
    if not remote_blog:
        raise HTTPException(status_code=404, detail="가져올 Blogger 블로그를 찾을 수 없습니다.")
    if get_blog_by_remote_id(db, payload.blogger_blog_id):
        raise HTTPException(status_code=409, detail="이미 가져온 Blogger 블로그입니다.")

    try:
        blog = import_blog_from_remote(db, remote_blog, payload.profile_key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    refreshed = get_blog(db, blog.id)
    summary_map = get_blog_summary_map(db, [blog.id])
    return _serialize_blog(
        refreshed or blog,
        google_refs,
        summary_metrics=asdict(summary_map[blog.id]) if blog.id in summary_map else None,
    )


@router.get("/{blog_id}", response_model=BlogRead)
def get_blog_detail(blog_id: int, db: Session = Depends(get_db)) -> dict:
    blog = get_blog(db, blog_id)
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")
    summary_map = get_blog_summary_map(db, [blog.id])
    return _serialize_blog(blog, summary_metrics=asdict(summary_map[blog.id]) if blog.id in summary_map else None)


@router.put("/{blog_id}", response_model=BlogRead)
def update_blog_detail(blog_id: int, payload: BlogUpdate, db: Session = Depends(get_db)) -> dict:
    blog = get_blog(db, blog_id)
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")
    updated = update_blog(db, blog, **payload.model_dump())
    refreshed = get_blog(db, updated.id)
    summary_map = get_blog_summary_map(db, [updated.id])
    return _serialize_blog(
        refreshed or updated,
        summary_metrics=asdict(summary_map[updated.id]) if updated.id in summary_map else None,
    )


@router.get("/{blog_id}/connection-options", response_model=BlogConnectionOptionsRead)
def get_blog_connection_options(blog_id: int, db: Session = Depends(get_db)) -> dict:
    blog = get_blog(db, blog_id)
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")

    google_refs = _load_google_reference_data(db)
    return {
        "blog_id": blog.id,
        "blogger_blog": next(
            (item for item in google_refs["available_blogs"] if item.get("id") == (blog.blogger_blog_id or "")),
            None,
        ),
        "search_console_sites": google_refs["search_console_sites"],
        "analytics_properties": google_refs["analytics_properties"],
        "selected_search_console": next(
            (item for item in google_refs["search_console_sites"] if item.get("site_url") == (blog.search_console_site_url or "")),
            None,
        ),
        "selected_analytics": next(
            (item for item in google_refs["analytics_properties"] if item.get("property_id") == (blog.ga4_property_id or "")),
            None,
        ),
        "warnings": google_refs["warnings"],
    }


@router.put("/{blog_id}/connections", response_model=BlogRead)
def update_blog_connection_values(blog_id: int, payload: BlogConnectionUpdate, db: Session = Depends(get_db)) -> dict:
    blog = get_blog(db, blog_id)
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")

    google_refs = _load_google_reference_data(db)
    _validate_connection_value(google_refs["search_console_sites"], "site_url", payload.search_console_site_url, "Search Console 속성")
    _validate_connection_value(google_refs["analytics_properties"], "property_id", payload.ga4_property_id, "GA4 속성")

    updated = update_blog_connections(
        db,
        blog,
        search_console_site_url=payload.search_console_site_url,
        ga4_property_id=payload.ga4_property_id,
    )
    refreshed = get_blog(db, updated.id)
    summary_map = get_blog_summary_map(db, [updated.id])
    return _serialize_blog(
        refreshed or updated,
        google_refs,
        summary_metrics=asdict(summary_map[updated.id]) if updated.id in summary_map else None,
    )


@router.get("/{blog_id}/workflow", response_model=list[BlogAgentConfigRead])
def get_blog_workflow(blog_id: int, db: Session = Depends(get_db)) -> list[dict]:
    blog = get_blog(db, blog_id)
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")
    return _workflow_list_response(blog)


@router.post("/{blog_id}/workflow", response_model=list[BlogAgentConfigRead])
def add_blog_workflow_step(blog_id: int, payload: WorkflowStepCreate, db: Session = Depends(get_db)) -> list[dict]:
    blog = get_blog(db, blog_id)
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")
    try:
        create_workflow_step(db, blog, payload.stage_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    refreshed = get_blog(db, blog.id) or blog
    return _workflow_list_response(refreshed)


@router.put("/{blog_id}/workflow/{step_id}", response_model=list[BlogAgentConfigRead])
def update_blog_workflow_step(
    blog_id: int,
    step_id: int,
    payload: BlogAgentConfigUpdate,
    db: Session = Depends(get_db),
) -> list[dict]:
    blog = get_blog(db, blog_id)
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")
    step = next((item for item in blog.agent_configs if item.id == step_id), None)
    if not step:
        raise HTTPException(status_code=404, detail="Workflow step not found")
    try:
        update_blog_agent(db, step, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    refreshed = get_blog(db, blog.id) or blog
    return _workflow_list_response(refreshed)


@router.delete("/{blog_id}/workflow/{step_id}", response_model=list[BlogAgentConfigRead])
def remove_blog_workflow_step(blog_id: int, step_id: int, db: Session = Depends(get_db)) -> list[dict]:
    blog = get_blog(db, blog_id)
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")
    step = next((item for item in blog.agent_configs if item.id == step_id), None)
    if not step:
        raise HTTPException(status_code=404, detail="Workflow step not found")
    try:
        delete_workflow_step(db, blog, step)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    refreshed = get_blog(db, blog.id) or blog
    return _workflow_list_response(refreshed)


@router.post("/{blog_id}/workflow/reorder", response_model=list[BlogAgentConfigRead])
def reorder_blog_workflow(blog_id: int, payload: WorkflowStepReorder, db: Session = Depends(get_db)) -> list[dict]:
    blog = get_blog(db, blog_id)
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")
    try:
        steps = reorder_workflow_steps(db, blog, payload.ordered_ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return [_serialize_workflow_step(step) for step in steps]


@router.get("/{blog_id}/agents", response_model=list[BlogAgentConfigRead])
def get_blog_agents(blog_id: int, db: Session = Depends(get_db)) -> list[dict]:
    blog = get_blog(db, blog_id)
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")
    return _workflow_list_response(blog)


@router.put("/{blog_id}/agents/{agent_key}", response_model=BlogAgentConfigRead)
def update_blog_agent_detail(blog_id: int, agent_key: str, payload: BlogAgentConfigUpdate, db: Session = Depends(get_db)) -> dict:
    blog = get_blog(db, blog_id)
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")
    agent = get_agent_config(blog, agent_key)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent config not found")
    try:
        updated = update_blog_agent(db, agent, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _serialize_workflow_step(updated)


@router.post("/{blog_id}/discover", response_model=DiscoveryRunResponse)
def trigger_blog_discovery(
    blog_id: int,
    publish_mode: PublishMode | None = Query(default=None),
    stop_after: JobStatus | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    blog = get_blog(db, blog_id)
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")
    try:
        return discover_topics_and_enqueue(
            db,
            blog_id=blog_id,
            publish_mode=publish_mode.value if publish_mode else None,
            stop_after=stop_after,
        )
    except ProviderRuntimeError as exc:
        status_code = exc.status_code if exc.status_code in {400, 401, 403, 404, 409, 422, 429} else 502
        raise HTTPException(
            status_code=status_code,
            detail={
                "provider": exc.provider,
                "message": exc.message,
                "detail": exc.detail,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
