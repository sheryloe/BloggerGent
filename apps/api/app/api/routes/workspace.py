from __future__ import annotations

import threading
import time
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.blogger_oauth_service import BloggerOAuthError
from app.schemas.api import (
    AgentRunCreate,
    AgentRunRead,
    AgentRunUpdate,
    AgentRuntimeHealthRead,
    AgentWorkerCreate,
    AgentWorkerRead,
    AgentWorkerUpdate,
    ContentItemCreate,
    ContentItemRead,
    ContentItemReviewRequest,
    ContentItemUpdate,
    MissionControlRead,
    PlatformCredentialRead,
    PlatformCredentialUpsert,
    WorkspaceIntegrationOverviewRead,
    WorkspaceOverviewRead,
    WorkspaceRuntimeOverviewRead,
    WorkspaceRuntimeUsageRead,
)
from app.services.blogger_sync_service import sync_connected_blogger_posts
from app.services.platform_oauth_service import (
    PlatformOAuthError,
    complete_google_platform_oauth,
    complete_instagram_oauth,
    get_platform_web_return_url,
    try_decode_platform_oauth_state,
)
from app.services.platform_publish_service import PlatformPublishError
from app.services.workspace_service import (
    build_mission_control_payload,
    build_channel_oauth_authorization_url,
    build_runtime_health,
    create_workspace_agent_worker,
    create_agent_run,
    create_content_item,
    get_agent_run,
    get_agent_worker,
    get_content_item,
    list_agent_runs,
    list_agent_workers,
    list_content_items,
    list_managed_channels,
    list_platform_credentials,
    list_platform_integrations,
    mark_content_item_for_review,
    publish_content_item_now,
    queue_content_item_publish,
    refresh_workspace_channel_credential,
    run_workspace_metric_sync_now,
    process_workspace_publish_queue_now,
    serialize_managed_channel,
    sync_workspace_channel_metrics,
    update_agent_run,
    update_workspace_agent_worker,
    update_content_item,
    upsert_platform_credential,
    workspace_runtime_overview,
    workspace_runtime_usage,
)

router = APIRouter(prefix="/workspace", tags=["workspace"])

_MISSION_CONTROL_CACHE_TTL_SECONDS = 3.0
_mission_control_cache_lock = threading.Lock()
_mission_control_cache: dict[str, Any] = {
    "expires_at": 0.0,
    "payload": None,
}


def _redirect_with_query(base_url: str, **params: str) -> RedirectResponse:
    query = urlencode({key: value for key, value in params.items() if value is not None})
    separator = "&" if "?" in base_url else "?"
    return RedirectResponse(url=f"{base_url}{separator}{query}", status_code=307)


def _get_mission_control_payload(db: Session, *, refresh: bool = False) -> dict[str, Any]:
    now = time.monotonic()
    if not refresh:
        with _mission_control_cache_lock:
            cached_payload = _mission_control_cache.get("payload")
            cached_expires_at = float(_mission_control_cache.get("expires_at", 0.0))
            if cached_payload is not None and cached_expires_at > now:
                return cached_payload

    payload = build_mission_control_payload(db, use_cache=not refresh)
    with _mission_control_cache_lock:
        _mission_control_cache["payload"] = payload
        _mission_control_cache["expires_at"] = now + _MISSION_CONTROL_CACHE_TTL_SECONDS
    return payload


@router.get("/mission-control", response_model=MissionControlRead)
def read_mission_control(
    refresh: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> MissionControlRead:
    payload = _get_mission_control_payload(db, refresh=refresh)
    return MissionControlRead(**payload)


@router.get("/overview", response_model=WorkspaceOverviewRead)
def read_workspace_overview(
    content_limit: int = Query(default=12, ge=1, le=100),
    db: Session = Depends(get_db),
) -> WorkspaceOverviewRead:
    runtime = workspace_runtime_overview(db, limit=content_limit)
    return WorkspaceOverviewRead(
        channels=[serialize_managed_channel(channel) for channel in list_managed_channels(db)],
        content_items=list_content_items(db, limit=content_limit),
        runtime=WorkspaceRuntimeOverviewRead(**runtime),
    )


@router.get("/content-items", response_model=list[ContentItemRead])
def read_content_items(
    channel_id: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    content_type: str | None = Query(default=None),
    lifecycle_status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[ContentItemRead]:
    return list_content_items(
        db,
        channel_id=channel_id,
        provider=provider,
        content_type=content_type,
        lifecycle_status=lifecycle_status,
        limit=limit,
    )


@router.post("/content-items", response_model=ContentItemRead, status_code=status.HTTP_201_CREATED)
def create_workspace_content_item(payload: ContentItemCreate, db: Session = Depends(get_db)) -> ContentItemRead:
    try:
        return create_content_item(
            db,
            channel_id=payload.channel_id,
            idempotency_key=payload.idempotency_key,
            content_type=str(payload.content_type),
            title=payload.title,
            description=payload.description,
            body_text=payload.body_text,
            asset_manifest=payload.asset_manifest,
            brief_payload=payload.brief_payload,
            scheduled_for=payload.scheduled_for,
            created_by_agent=payload.created_by_agent,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/content-items/{item_id}", response_model=ContentItemRead)
def update_workspace_content_item(item_id: int, payload: ContentItemUpdate, db: Session = Depends(get_db)) -> ContentItemRead:
    item = get_content_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Content item not found")
    return update_content_item(
        db,
        item,
        lifecycle_status=str(payload.lifecycle_status) if payload.lifecycle_status is not None else None,
        title=payload.title,
        description=payload.description,
        body_text=payload.body_text,
        approval_status=payload.approval_status,
        asset_manifest=payload.asset_manifest,
        brief_payload=payload.brief_payload,
        review_notes=payload.review_notes,
        scheduled_for=payload.scheduled_for,
        last_feedback=payload.last_feedback,
        blocked_reason=payload.blocked_reason,
        last_score=payload.last_score,
    )


@router.post("/content-items/{item_id}/review", response_model=ContentItemRead)
def review_workspace_content_item(
    item_id: int,
    payload: ContentItemReviewRequest,
    db: Session = Depends(get_db),
) -> ContentItemRead:
    item = get_content_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Content item not found")
    return mark_content_item_for_review(
        db,
        item,
        review_notes=payload.review_notes,
        last_feedback=payload.last_feedback,
    )


@router.post("/content-items/{item_id}/publish", response_model=ContentItemRead)
def publish_workspace_content_item(item_id: int, db: Session = Depends(get_db)) -> ContentItemRead:
    item = get_content_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Content item not found")
    try:
        return queue_content_item_publish(db, item)
    except PlatformPublishError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/content-items/{item_id}/publish-now", response_model=ContentItemRead)
def publish_workspace_content_item_now(item_id: int, db: Session = Depends(get_db)) -> ContentItemRead:
    item = get_content_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Content item not found")
    try:
        return publish_content_item_now(db, item)
    except (ValueError, PlatformOAuthError, PlatformPublishError) as exc:
        detail = exc.detail if isinstance(exc, (PlatformOAuthError, PlatformPublishError)) else str(exc)
        status_code = exc.status_code if isinstance(exc, (PlatformOAuthError, PlatformPublishError)) else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.post("/publish-queue/process")
def process_workspace_publish_queue(limit: int = Query(default=10, ge=1, le=100), db: Session = Depends(get_db)) -> dict:
    return process_workspace_publish_queue_now(db, limit=limit)


@router.get("/integrations", response_model=WorkspaceIntegrationOverviewRead)
def read_workspace_integrations(
    channel_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> WorkspaceIntegrationOverviewRead:
    return WorkspaceIntegrationOverviewRead(
        channels=[
            item
            for item in [serialize_managed_channel(channel) for channel in list_managed_channels(db, include_disconnected=True)]
            if channel_id is None or item["channel_id"] == channel_id
        ],
        integrations=[
            item for item in list_platform_integrations(db) if channel_id is None or item["channel_id"] == channel_id
        ],
        credentials=list_platform_credentials(db, channel_id=channel_id),
    )


@router.get("/oauth/{channel_id}/start")
def start_workspace_oauth(channel_id: str, db: Session = Depends(get_db)):
    try:
        authorization_url = build_channel_oauth_authorization_url(db, channel_id=channel_id)
    except (ValueError, PlatformOAuthError) as exc:
        detail = exc.detail if isinstance(exc, PlatformOAuthError) else str(exc)
        status_code = exc.status_code if isinstance(exc, PlatformOAuthError) else 404
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return RedirectResponse(url=authorization_url, status_code=307)


@router.get("/oauth/google/callback")
def complete_workspace_google_oauth(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    platform_state = try_decode_platform_oauth_state(state)
    channel_id = str((platform_state or {}).get("channel_id") or "").strip() or None
    base_url = get_platform_web_return_url(channel_id)
    if error:
        return _redirect_with_query(base_url, platform_oauth="error", message=error)
    if not code:
        return _redirect_with_query(base_url, platform_oauth="error", message="missing_code")
    try:
        result = complete_google_platform_oauth(db, code=code, state=state)
    except PlatformOAuthError as exc:
        return _redirect_with_query(base_url, platform_oauth="error", message=exc.detail)

    if str(result.get("channel_id") or "").startswith("blogger:"):
        sync_connected_blogger_posts(db)
    return _redirect_with_query(base_url, platform_oauth="success", channel_id=str(result.get("channel_id") or ""))


@router.get("/oauth/instagram/callback")
def complete_workspace_instagram_oauth(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    platform_state = try_decode_platform_oauth_state(state)
    channel_id = str((platform_state or {}).get("channel_id") or "").strip() or None
    base_url = get_platform_web_return_url(channel_id)
    if error:
        return _redirect_with_query(base_url, platform_oauth="error", message=error)
    if not code:
        return _redirect_with_query(base_url, platform_oauth="error", message="missing_code")
    try:
        result = complete_instagram_oauth(db, code=code, state=state)
    except PlatformOAuthError as exc:
        return _redirect_with_query(base_url, platform_oauth="error", message=exc.detail)
    return _redirect_with_query(base_url, platform_oauth="success", channel_id=str(result.get("channel_id") or ""))


@router.post("/oauth/{channel_id}/refresh", response_model=PlatformCredentialRead)
def refresh_workspace_oauth(channel_id: str, db: Session = Depends(get_db)) -> PlatformCredentialRead:
    try:
        return refresh_workspace_channel_credential(db, channel_id=channel_id)
    except (ValueError, PlatformOAuthError) as exc:
        detail = exc.detail if isinstance(exc, PlatformOAuthError) else str(exc)
        status_code = exc.status_code if isinstance(exc, PlatformOAuthError) else 404
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.post("/platform-credentials", response_model=PlatformCredentialRead, status_code=status.HTTP_201_CREATED)
def save_platform_credential(payload: PlatformCredentialUpsert, db: Session = Depends(get_db)) -> PlatformCredentialRead:
    try:
        return upsert_platform_credential(
            db,
            channel_id=payload.channel_id,
            provider=str(payload.provider),
            subject=payload.subject,
            display_name=payload.display_name,
            access_token=payload.access_token,
            refresh_token=payload.refresh_token,
            scopes=payload.scopes,
            expires_at=payload.expires_at,
            credential_key=payload.credential_key,
            token_type=payload.token_type,
            refresh_metadata=payload.refresh_metadata,
            is_valid=payload.is_valid,
            last_error=payload.last_error,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runtime/health", response_model=AgentRuntimeHealthRead)
def read_workspace_runtime_health(db: Session = Depends(get_db)) -> AgentRuntimeHealthRead:
    return build_runtime_health(db)


@router.get("/runtime", response_model=WorkspaceRuntimeOverviewRead)
def read_workspace_runtime(
    channel_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> WorkspaceRuntimeOverviewRead:
    return WorkspaceRuntimeOverviewRead(**workspace_runtime_overview(db, channel_id=channel_id, limit=limit))


@router.get("/runtime/usage", response_model=WorkspaceRuntimeUsageRead)
def read_workspace_runtime_usage(
    days: int = Query(default=7, ge=1, le=365),
    db: Session = Depends(get_db),
) -> WorkspaceRuntimeUsageRead:
    return WorkspaceRuntimeUsageRead(**workspace_runtime_usage(db, days=days))


@router.post("/metrics/sync")
def run_workspace_metric_sync(force: bool = Query(default=False), db: Session = Depends(get_db)) -> dict:
    return run_workspace_metric_sync_now(db, force=force)


@router.post("/channels/{channel_id}/metrics/sync")
def sync_workspace_channel_metrics_route(
    channel_id: str,
    days: int = Query(default=28, ge=1, le=365),
    refresh_indexing: bool = Query(default=True),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return sync_workspace_channel_metrics(
            db,
            channel_id=channel_id,
            days=days,
            refresh_indexing=refresh_indexing,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (BloggerOAuthError, PlatformOAuthError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/agent-workers", response_model=list[AgentWorkerRead])
def read_workspace_agent_workers(
    channel_id: str | None = Query(default=None),
    runtime_kind: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[AgentWorkerRead]:
    return list_agent_workers(db, channel_id=channel_id, runtime_kind=runtime_kind)


@router.post("/agent-workers", response_model=AgentWorkerRead, status_code=status.HTTP_201_CREATED)
def create_workspace_agent_worker_route(payload: AgentWorkerCreate, db: Session = Depends(get_db)) -> AgentWorkerRead:
    try:
        return create_workspace_agent_worker(
            db,
            channel_id=payload.channel_id,
            worker_key=payload.worker_key,
            display_name=payload.display_name,
            role_name=payload.role_name,
            runtime_kind=str(payload.runtime_kind),
            queue_name=payload.queue_name,
            concurrency_limit=payload.concurrency_limit,
            status=str(payload.status),
            config_payload=payload.config_payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/agent-workers/{worker_id}", response_model=AgentWorkerRead)
def update_workspace_agent_worker_route(
    worker_id: int,
    payload: AgentWorkerUpdate,
    db: Session = Depends(get_db),
) -> AgentWorkerRead:
    worker = get_agent_worker(db, worker_id)
    if worker is None:
        raise HTTPException(status_code=404, detail="Agent worker not found")
    return update_workspace_agent_worker(
        db,
        worker,
        status=str(payload.status) if payload.status is not None else None,
        concurrency_limit=payload.concurrency_limit,
        config_payload=payload.config_payload,
        last_heartbeat_at=payload.last_heartbeat_at,
        last_error=payload.last_error,
    )


@router.get("/agent-runs", response_model=list[AgentRunRead])
def read_workspace_agent_runs(
    channel_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[AgentRunRead]:
    return list_agent_runs(db, channel_id=channel_id, limit=limit)


@router.post("/agent-runs", response_model=AgentRunRead, status_code=status.HTTP_201_CREATED)
def create_workspace_agent_run(payload: AgentRunCreate, db: Session = Depends(get_db)) -> AgentRunRead:
    try:
        return create_agent_run(
            db,
            channel_id=payload.channel_id,
            content_item_id=payload.content_item_id,
            worker_id=payload.worker_id,
            run_key=payload.run_key,
            runtime_kind=str(payload.runtime_kind),
            assigned_role=payload.assigned_role,
            provider_model=payload.provider_model,
            priority=payload.priority,
            timeout_seconds=payload.timeout_seconds,
            prompt_snapshot=payload.prompt_snapshot,
            status=str(payload.status),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/agent-runs/{run_id}", response_model=AgentRunRead)
def update_workspace_agent_run(run_id: int, payload: AgentRunUpdate, db: Session = Depends(get_db)) -> AgentRunRead:
    run = get_agent_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return update_agent_run(
        db,
        run,
        status=str(payload.status) if payload.status is not None else None,
        retry_count=payload.retry_count,
        started_at=payload.started_at,
        ended_at=payload.ended_at,
        response_snapshot=payload.response_snapshot,
        log_lines=payload.log_lines,
        error_message=payload.error_message,
    )
