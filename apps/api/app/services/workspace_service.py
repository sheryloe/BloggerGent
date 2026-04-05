from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from threading import Lock

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import AIUsageEvent, AgentRun, AgentWorker, ContentItem, PlatformCredential, PublicationRecord
from app.services.metric_ingestion_service import run_workspace_metric_sync_schedule, sync_channel_metrics
from app.services.platform_oauth_service import build_platform_authorization_url, refresh_platform_access_token
from app.services.platform_publish_service import (
    content_item_missing_asset_reason,
    mark_content_item_publish_queued,
    process_platform_publish_queue,
    publish_content_item_now as publish_platform_content_item_now,
)
from app.services.platform_service import (
    PLATFORM_PROMPT_STEPS,
    create_agent_run as create_platform_agent_run,
    create_agent_worker as create_platform_agent_worker,
    create_content_item as create_platform_content_item,
    get_agent_runtime_health,
    get_managed_channel_by_channel_id,
    list_agent_runs as list_platform_agent_runs,
    list_agent_workers as list_platform_agent_workers,
    list_content_items as list_platform_content_items,
    list_managed_channels as list_platform_channels,
    list_platform_integrations as list_platform_integration_state,
    serialize_agent_run,
    serialize_agent_worker,
    serialize_channel,
    serialize_content_item,
    serialize_platform_credential,
    update_agent_worker as update_platform_agent_worker,
    update_agent_run as update_platform_agent_run,
    update_content_item as update_platform_content_item,
    upsert_platform_credential as upsert_platform_credential_record,
)

RUNTIME_LABELS: dict[str, str] = {
    "claude_cli": "Claude CLI",
    "codex_cli": "Codex CLI",
    "gemini_cli": "Gemini CLI",
    "openai": "OpenAI",
    "other": "기타",
}

_MISSION_CONTROL_CACHE_TTL_SECONDS = 5
_MISSION_CONTROL_CACHE_LOCK = Lock()
_MISSION_CONTROL_CACHE_PAYLOAD: dict | None = None
_MISSION_CONTROL_CACHE_EXPIRES_AT: datetime | None = None


def _read_mission_control_cache(now: datetime) -> dict | None:
    global _MISSION_CONTROL_CACHE_PAYLOAD, _MISSION_CONTROL_CACHE_EXPIRES_AT
    with _MISSION_CONTROL_CACHE_LOCK:
        if _MISSION_CONTROL_CACHE_PAYLOAD is None or _MISSION_CONTROL_CACHE_EXPIRES_AT is None:
            return None
        if now >= _MISSION_CONTROL_CACHE_EXPIRES_AT:
            _MISSION_CONTROL_CACHE_PAYLOAD = None
            _MISSION_CONTROL_CACHE_EXPIRES_AT = None
            return None
        return _MISSION_CONTROL_CACHE_PAYLOAD


def _write_mission_control_cache(payload: dict, now: datetime) -> None:
    global _MISSION_CONTROL_CACHE_PAYLOAD, _MISSION_CONTROL_CACHE_EXPIRES_AT
    with _MISSION_CONTROL_CACHE_LOCK:
        _MISSION_CONTROL_CACHE_PAYLOAD = payload
        _MISSION_CONTROL_CACHE_EXPIRES_AT = now + timedelta(seconds=_MISSION_CONTROL_CACHE_TTL_SECONDS)


def list_managed_channels(db: Session, *, include_disconnected: bool = False):
    return list_platform_channels(db, include_disconnected=include_disconnected)


def ensure_workspace_foundation(db: Session):
    return list_platform_channels(db)


def _runtime_usage_bucket(event: AIUsageEvent) -> str:
    combined = " ".join(
        [
            str(event.provider_mode or ""),
            str(event.provider_name or ""),
            str(event.provider_model or ""),
            str(event.endpoint or ""),
        ]
    ).lower()
    if "codex" in combined:
        return "codex_cli"
    if "gemini" in combined:
        return "gemini_cli"
    if "claude" in combined:
        return "claude_cli"
    if "openai" in combined or "gpt-" in combined:
        return "openai"
    return str(event.provider_name or event.provider_mode or "unknown").strip().lower() or "unknown"


def workspace_runtime_usage(db: Session, *, days: int = 7) -> dict:
    normalized_days = max(1, min(int(days or 7), 90))
    now = datetime.now(UTC)
    since = now - timedelta(days=normalized_days)
    events = db.execute(select(AIUsageEvent).where(AIUsageEvent.created_at >= since).order_by(AIUsageEvent.created_at.desc())).scalars().all()

    grouped: dict[str, dict] = {}
    total_models: set[str] = set()
    total_request_count = 0
    total_input_tokens = 0
    total_output_tokens = 0
    total_tokens = 0
    total_estimated_cost_usd = 0.0
    total_error_count = 0
    last_event_at: datetime | None = None

    for event in events:
        bucket = _runtime_usage_bucket(event)
        payload = grouped.setdefault(
            bucket,
            {
                "provider_key": bucket,
                "label": RUNTIME_LABELS.get(bucket, bucket.replace("_", " ").title()),
                "request_count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "estimated_cost_usd": 0.0,
                "error_count": 0,
                "last_event_at": None,
                "models": set(),
            },
        )
        request_count = int(event.request_count or 0)
        input_tokens = int(event.input_tokens or 0)
        output_tokens = int(event.output_tokens or 0)
        total_token_count = int(event.total_tokens or 0)
        estimated_cost = float(event.estimated_cost_usd or 0.0)
        error_count = 0 if event.success else max(1, request_count or 1)

        payload["request_count"] += request_count
        payload["input_tokens"] += input_tokens
        payload["output_tokens"] += output_tokens
        payload["total_tokens"] += total_token_count
        payload["estimated_cost_usd"] += estimated_cost
        payload["error_count"] += error_count
        payload["last_event_at"] = max(filter(None, [payload["last_event_at"], event.created_at]), default=event.created_at)
        if event.provider_model:
            payload["models"].add(str(event.provider_model))

        total_request_count += request_count
        total_input_tokens += input_tokens
        total_output_tokens += output_tokens
        total_tokens += total_token_count
        total_estimated_cost_usd += estimated_cost
        total_error_count += error_count
        if event.provider_model:
            total_models.add(str(event.provider_model))
        last_event_at = max(filter(None, [last_event_at, event.created_at]), default=event.created_at)

    providers = [
        {
            **payload,
            "estimated_cost_usd": round(float(payload["estimated_cost_usd"]), 6),
            "models": sorted(payload["models"]),
        }
        for payload in grouped.values()
    ]
    providers.sort(key=lambda item: (-int(item["request_count"]), str(item["provider_key"])))

    return {
        "generated_at": now,
        "days": normalized_days,
        "providers": providers,
        "totals": {
            "request_count": total_request_count,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "total_tokens": total_tokens,
            "estimated_cost_usd": round(total_estimated_cost_usd, 6),
            "error_count": total_error_count,
            "last_event_at": last_event_at,
            "models": sorted(total_models),
        },
    }


def get_managed_channel(db: Session, channel_id: str):
    return get_managed_channel_by_channel_id(db, channel_id)


def serialize_managed_channel(channel) -> dict:
    return serialize_channel(channel)


def list_platform_prompt_steps(provider: str) -> list[dict[str, str | None]]:
    return [
        {
            "id": f"{provider}:{index}",
            "stage_type": definition.stage_type,
            "stage_label": definition.stage_label,
            "name": definition.name,
            "role_name": definition.role_name,
            "objective": definition.objective,
            "prompt_template": "",
            "provider_hint": definition.provider_hint,
            "provider_model": definition.provider_model,
        }
        for index, definition in enumerate(PLATFORM_PROMPT_STEPS.get(provider, ()), start=1)
    ]


def list_channel_categories(channel) -> list[dict[str, str | int | bool | None]]:
    if channel.provider == "youtube":
        return [
            {"key": "long-form", "name": "Long-form", "weight": 70, "color": "#dc2626", "sort_order": 1, "is_active": True},
            {"key": "shorts", "name": "Shorts", "weight": 30, "color": "#f97316", "sort_order": 2, "is_active": True},
        ]
    if channel.provider == "instagram":
        return [
            {"key": "image", "name": "Image Posts", "weight": 55, "color": "#db2777", "sort_order": 1, "is_active": True},
            {"key": "reel", "name": "Reels", "weight": 45, "color": "#2563eb", "sort_order": 2, "is_active": True},
        ]
    return []


def _content_item_query():
    return (
        select(ContentItem)
        .options(
            selectinload(ContentItem.managed_channel),
            selectinload(ContentItem.publication_records),
            selectinload(ContentItem.metric_facts),
            selectinload(ContentItem.agent_runs),
        )
    )


def _agent_run_query():
    return (
        select(AgentRun)
        .options(
            selectinload(AgentRun.managed_channel),
            selectinload(AgentRun.worker),
            selectinload(AgentRun.content_item),
        )
    )


def get_content_item(db: Session, item_id: int) -> ContentItem | None:
    query = _content_item_query().where(ContentItem.id == item_id)
    return db.execute(query).scalar_one_or_none()


def get_agent_run(db: Session, run_id: int) -> AgentRun | None:
    query = _agent_run_query().where(AgentRun.id == run_id)
    return db.execute(query).scalar_one_or_none()


def get_agent_worker(db: Session, worker_id: int) -> AgentWorker | None:
    query = (
        select(AgentWorker)
        .options(selectinload(AgentWorker.managed_channel), selectinload(AgentWorker.runs))
        .where(AgentWorker.id == worker_id)
    )
    return db.execute(query).scalar_one_or_none()


def _reload_content_item(db: Session, item_id: int) -> ContentItem:
    item = get_content_item(db, item_id)
    if item is None:
        raise ValueError("Content item not found")
    return item


def _reload_agent_run(db: Session, run_id: int) -> AgentRun:
    run = get_agent_run(db, run_id)
    if run is None:
        raise ValueError("Agent run not found")
    return run


def _runtime_profiles(workers: list[dict], runs: list[dict]) -> list[dict]:
    worker_counter = Counter(item["runtime_kind"] for item in workers)
    live_worker_counter = Counter(item["runtime_kind"] for item in workers if item["status"] in {"running", "busy"})
    queued_run_counter = Counter(item["runtime_kind"] for item in runs if item["status"] == "queued")
    failed_run_counter = Counter(item["runtime_kind"] for item in runs if item["status"] == "failed")

    runtime_kinds = sorted(set(RUNTIME_LABELS) | set(worker_counter) | set(queued_run_counter) | set(failed_run_counter))
    profiles: list[dict] = []
    for runtime_kind in runtime_kinds:
        profiles.append(
            {
                "runtime_kind": runtime_kind,
                "label": RUNTIME_LABELS.get(runtime_kind, runtime_kind),
                "worker_count": worker_counter.get(runtime_kind, 0),
                "live_worker_count": live_worker_counter.get(runtime_kind, 0),
                "queued_runs": queued_run_counter.get(runtime_kind, 0),
                "failed_runs": failed_run_counter.get(runtime_kind, 0),
                "healthy": failed_run_counter.get(runtime_kind, 0) == 0,
            }
        )
    return profiles


def _runtime_health_from_serialized(workers: list[dict], runs: list[dict]) -> dict:
    worker_status = Counter(item.get("status") for item in workers if item.get("status"))
    run_status = Counter(item.get("status") for item in runs if item.get("status"))
    runtime_kinds = sorted({str(item.get("runtime_kind")) for item in workers if item.get("runtime_kind")})
    last_run_at = runs[0].get("created_at") if runs else None
    failed_runs = int(run_status.get("failed", 0))
    worker_errors = int(worker_status.get("error", 0))
    return {
        "worker_count": len(workers),
        "run_count": len(runs),
        "worker_status": dict(worker_status),
        "run_status": dict(run_status),
        "last_run_at": last_run_at,
        "runtime_kinds": runtime_kinds,
        "healthy": failed_runs == 0 and worker_errors == 0,
        "generated_at": datetime.now(UTC),
    }


def _to_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _channel_has_activity(channel: dict) -> bool:
    return any(
        _to_int(channel.get(key), 0) > 0
        for key in ("posts_count", "pending_items", "failed_items", "live_worker_count")
    )


def _should_include_mission_channel(channel: dict) -> bool:
    provider = str(channel.get("provider") or "").strip().lower()
    oauth_state = str(channel.get("oauth_state") or "").strip().lower()
    is_enabled = bool(channel.get("is_enabled", True))

    if not is_enabled:
        return False
    if provider in {"youtube", "instagram"}:
        return oauth_state == "connected" or _channel_has_activity(channel)
    return True


def list_platform_credentials(db: Session, *, channel_id: str | None = None) -> list[dict]:
    records: list[dict] = []
    for channel in list_platform_channels(db):
        if channel_id and channel.channel_id != channel_id:
            continue
        for credential in channel.credentials:
            payload = serialize_platform_credential(credential)
            payload["managed_channel_id"] = credential.managed_channel_id
            payload["channel_id"] = channel.channel_id
            records.append(payload)
    return records


def list_platform_integrations(db: Session) -> list[dict]:
    return list_platform_integration_state(db)


def list_content_items(
    db: Session,
    *,
    provider: str | None = None,
    channel_id: str | None = None,
    content_type: str | None = None,
    status: str | None = None,
    lifecycle_status: str | None = None,
    limit: int = 50,
    ensure_channels: bool = True,
) -> list[dict]:
    items = list_platform_content_items(
        db,
        provider=provider,
        channel_id=channel_id,
        content_type=content_type,
        lifecycle_status=lifecycle_status or status,
        limit=limit,
        ensure_channels=ensure_channels,
    )
    return [serialize_content_item(item) for item in items]


def create_content_item(
    db: Session,
    *,
    channel_id: str,
    content_type: str,
    title: str,
    description: str = "",
    body_text: str = "",
    asset_manifest: dict | None = None,
    brief_payload: dict | None = None,
    scheduled_for: datetime | None = None,
    created_by_agent: str | None = None,
    idempotency_key: str | None = None,
    job_id: int | None = None,
    source_article_id: int | None = None,
) -> dict:
    channel = get_managed_channel_by_channel_id(db, channel_id)
    if channel is None:
        raise ValueError("Channel not found")

    item = create_platform_content_item(
        db,
        channel=channel,
        content_type=content_type,
        title=title,
        description=description,
        body_text=body_text,
        asset_manifest=asset_manifest or {},
        brief_payload=brief_payload or {},
        scheduled_for=scheduled_for,
        created_by_agent=created_by_agent,
        idempotency_key=idempotency_key,
    )
    if job_id is not None:
        item.job_id = job_id
    if source_article_id is not None:
        item.source_article_id = source_article_id
    if job_id is not None or source_article_id is not None:
        db.add(item)
        db.commit()
        db.refresh(item)
    return serialize_content_item(_reload_content_item(db, item.id))


def update_content_item(
    db: Session,
    item: ContentItem,
    *,
    lifecycle_status: str | None = None,
    title: str | None = None,
    description: str | None = None,
    body_text: str | None = None,
    approval_status: str | None = None,
    asset_manifest: dict | None = None,
    brief_payload: dict | None = None,
    review_notes: list | None = None,
    scheduled_for: datetime | None = None,
    last_feedback: str | None = None,
    blocked_reason: str | None = None,
    last_score: dict | None = None,
) -> dict:
    resolved_lifecycle_status = lifecycle_status
    resolved_blocked_reason = blocked_reason
    if asset_manifest is not None and lifecycle_status is None and item.managed_channel.provider in {"youtube", "instagram"}:
        missing_reason = content_item_missing_asset_reason(item, asset_manifest=asset_manifest)
        if missing_reason:
            resolved_lifecycle_status = "blocked_asset"
            resolved_blocked_reason = missing_reason
        elif item.lifecycle_status in {"blocked_asset", "draft", "review"}:
            resolved_lifecycle_status = "ready_to_publish"
            resolved_blocked_reason = ""

    updated = update_platform_content_item(
        db,
        item,
        lifecycle_status=resolved_lifecycle_status,
        title=title,
        description=description,
        body_text=body_text,
        approval_status=approval_status,
        asset_manifest=asset_manifest,
        brief_payload=brief_payload,
        review_notes=review_notes,
        scheduled_for=scheduled_for,
        last_feedback=last_feedback,
        blocked_reason=resolved_blocked_reason,
        last_score=last_score,
    )
    return serialize_content_item(_reload_content_item(db, updated.id))


def review_content_item(
    db: Session,
    item: ContentItem,
    *,
    approval_status: str,
    lifecycle_status: str | None = None,
    review_note: str | None = None,
) -> dict:
    review_notes = list(item.review_notes or [])
    if review_note:
        review_notes.append({"created_at": datetime.now(UTC).isoformat(), "note": review_note})
    updated = update_platform_content_item(
        db,
        item,
        lifecycle_status=lifecycle_status or item.lifecycle_status,
        approval_status=approval_status,
        review_notes=review_notes,
    )
    return serialize_content_item(_reload_content_item(db, updated.id))


def mark_content_item_for_review(
    db: Session,
    item: ContentItem,
    *,
    review_notes: list | None = None,
    last_feedback: str | None = None,
) -> dict:
    merged_notes = list(item.review_notes or [])
    if review_notes:
        merged_notes.extend(review_notes)
    updated = update_platform_content_item(
        db,
        item,
        lifecycle_status="review",
        approval_status="pending",
        review_notes=merged_notes,
        last_feedback=last_feedback,
    )
    return serialize_content_item(_reload_content_item(db, updated.id))


def queue_content_item_publish(db: Session, item: ContentItem) -> dict:
    missing_reason = content_item_missing_asset_reason(item)
    if missing_reason:
        updated = update_platform_content_item(
            db,
            item,
            lifecycle_status="blocked_asset",
            blocked_reason=missing_reason,
        )
        return serialize_content_item(_reload_content_item(db, updated.id))

    if item.managed_channel.provider in {"youtube", "instagram"} and item.lifecycle_status in {"blocked_asset", "draft", "review"}:
        item = update_platform_content_item(
            db,
            item,
            lifecycle_status="ready_to_publish",
            blocked_reason="",
        )

    queued = mark_content_item_publish_queued(db, item)
    return serialize_content_item(_reload_content_item(db, queued.id))


def publish_content_item_now(db: Session, item: ContentItem) -> dict:
    published = publish_platform_content_item_now(db, item)
    return serialize_content_item(_reload_content_item(db, published.id))


def process_workspace_publish_queue_now(db: Session, *, limit: int = 10) -> dict:
    return process_platform_publish_queue(db, limit=limit)


def build_channel_oauth_authorization_url(db: Session, *, channel_id: str) -> str:
    return build_platform_authorization_url(db, channel_id=channel_id)


def refresh_workspace_channel_credential(db: Session, *, channel_id: str) -> dict:
    refreshed = refresh_platform_access_token(db, channel_id=channel_id)
    return serialize_platform_credential(refreshed)


def sync_workspace_channel_metrics(
    db: Session,
    *,
    channel_id: str,
    days: int = 28,
    refresh_indexing: bool = True,
) -> dict:
    return sync_channel_metrics(
        db,
        channel_id=channel_id,
        days=days,
        refresh_indexing=refresh_indexing,
    )


def run_workspace_metric_sync_now(db: Session, *, force: bool = False) -> dict:
    return run_workspace_metric_sync_schedule(db, force=force)


def workspace_runtime_overview(
    db: Session,
    *,
    channel_id: str | None = None,
    limit: int = 50,
) -> dict:
    _ = list_platform_channels(db)
    workers = list_agent_workers(db, channel_id=channel_id, ensure_channels=False)
    runs_for_health = list_agent_runs(db, channel_id=channel_id, limit=200, ensure_channels=False)
    runs = runs_for_health[: max(1, min(limit, 200))]
    runtime_health = _runtime_health_from_serialized(workers, runs_for_health)
    return {
        "profiles": _runtime_profiles(workers, runs),
        "workers": workers,
        "runs": runs,
        "runtime_health": runtime_health,
    }


def list_agent_workers(
    db: Session,
    *,
    channel_id: str | None = None,
    runtime_kind: str | None = None,
    ensure_channels: bool = True,
) -> list[dict]:
    workers = list_platform_agent_workers(
        db,
        channel_id=channel_id,
        runtime_kind=runtime_kind,
        ensure_channels=ensure_channels,
    )
    return [serialize_agent_worker(item) for item in workers]


def create_workspace_agent_worker(
    db: Session,
    *,
    channel_id: str | None,
    worker_key: str,
    display_name: str,
    role_name: str,
    runtime_kind: str,
    queue_name: str,
    concurrency_limit: int,
    status: str,
    config_payload: dict | None,
) -> dict:
    channel = get_managed_channel_by_channel_id(db, channel_id) if channel_id else None
    worker = create_platform_agent_worker(
        db,
        channel=channel,
        worker_key=worker_key,
        display_name=display_name,
        role_name=role_name,
        runtime_kind=runtime_kind,
        queue_name=queue_name,
        concurrency_limit=concurrency_limit,
        status=status,
        config_payload=config_payload,
    )
    return serialize_agent_worker(get_agent_worker(db, worker.id) or worker)


def update_workspace_agent_worker(
    db: Session,
    worker: AgentWorker,
    *,
    status: str | None = None,
    concurrency_limit: int | None = None,
    config_payload: dict | None = None,
    last_heartbeat_at: datetime | None = None,
    last_error: str | None = None,
) -> dict:
    updated = update_platform_agent_worker(
        db,
        worker,
        status=status,
        concurrency_limit=concurrency_limit,
        config_payload=config_payload,
        last_heartbeat_at=last_heartbeat_at,
        last_error=last_error,
    )
    return serialize_agent_worker(get_agent_worker(db, updated.id) or updated)


def list_agent_runs(
    db: Session,
    *,
    channel_id: str | None = None,
    limit: int = 50,
    ensure_channels: bool = True,
) -> list[dict]:
    runs = list_platform_agent_runs(
        db,
        channel_id=channel_id,
        limit=limit,
        ensure_channels=ensure_channels,
    )
    return [serialize_agent_run(item) for item in runs]


def create_agent_run(
    db: Session,
    *,
    channel_id: str | None,
    content_item_id: int | None,
    worker_id: int | None,
    run_key: str,
    runtime_kind: str,
    assigned_role: str,
    provider_model: str | None,
    priority: int,
    timeout_seconds: int,
    prompt_snapshot: str,
    status: str,
) -> dict:
    worker = get_agent_worker(db, worker_id) if worker_id else None
    content_item = get_content_item(db, content_item_id) if content_item_id else None
    resolved_channel_id = channel_id
    if resolved_channel_id is None and worker and worker.managed_channel:
        resolved_channel_id = worker.managed_channel.channel_id
    if resolved_channel_id is None and content_item and content_item.managed_channel:
        resolved_channel_id = content_item.managed_channel.channel_id
    channel = get_managed_channel_by_channel_id(db, resolved_channel_id) if resolved_channel_id else None

    run = create_platform_agent_run(
        db,
        run_key=run_key,
        runtime_kind=runtime_kind,
        assigned_role=assigned_role,
        managed_channel=channel,
        content_item=content_item,
        worker=worker,
        provider_model=provider_model,
        priority=priority,
        timeout_seconds=timeout_seconds,
        prompt_snapshot=prompt_snapshot,
        status=status,
    )
    return serialize_agent_run(_reload_agent_run(db, run.id))


def create_workspace_agent_run(
    db: Session,
    *,
    channel_id: str | None,
    content_item_id: int | None,
    worker_id: int | None,
    run_key: str,
    runtime_kind: str,
    assigned_role: str,
    provider_model: str | None,
    priority: int,
    timeout_seconds: int,
    prompt_snapshot: str,
    status: str,
) -> dict:
    return create_agent_run(
        db,
        channel_id=channel_id,
        content_item_id=content_item_id,
        worker_id=worker_id,
        run_key=run_key,
        runtime_kind=runtime_kind,
        assigned_role=assigned_role,
        provider_model=provider_model,
        priority=priority,
        timeout_seconds=timeout_seconds,
        prompt_snapshot=prompt_snapshot,
        status=status,
    )


def update_agent_run(
    db: Session,
    run: AgentRun,
    *,
    status: str | None = None,
    retry_count: int | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    response_snapshot: str | None = None,
    log_lines: list | None = None,
    error_message: str | None = None,
) -> dict:
    updated = update_platform_agent_run(
        db,
        run,
        status=status,
        retry_count=retry_count,
        started_at=started_at,
        ended_at=ended_at,
        response_snapshot=response_snapshot,
        log_lines=log_lines,
        error_message=error_message,
    )
    return serialize_agent_run(_reload_agent_run(db, updated.id))


def update_workspace_agent_run(
    db: Session,
    run: AgentRun,
    *,
    status: str | None = None,
    retry_count: int | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    response_snapshot: str | None = None,
    log_lines: list | None = None,
    error_message: str | None = None,
) -> dict:
    return update_agent_run(
        db,
        run,
        status=status,
        retry_count=retry_count,
        started_at=started_at,
        ended_at=ended_at,
        response_snapshot=response_snapshot,
        log_lines=log_lines,
        error_message=error_message,
    )


def upsert_platform_credential(
    db: Session,
    *,
    channel_id: str,
    provider: str,
    subject: str | None,
    display_name: str | None = None,
    access_token: str = "",
    refresh_token: str = "",
    scopes: list[str] | None = None,
    expires_at: datetime | None = None,
    credential_key: str | None = None,
    token_type: str = "Bearer",
    refresh_metadata: dict | None = None,
    is_valid: bool | None = None,
    last_error: str | None = None,
) -> dict:
    channel = get_managed_channel_by_channel_id(db, channel_id)
    if channel is None:
        raise ValueError("Channel not found")

    credential = upsert_platform_credential_record(
        db,
        channel=channel,
        provider=provider,
        credential_key=credential_key or channel.channel_id,
        subject=subject or display_name,
        scopes=scopes or [],
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        token_type=token_type,
        refresh_metadata={"display_name": display_name, **(refresh_metadata or {})},
        last_error=last_error,
        is_valid=bool(access_token) if is_valid is None else is_valid,
    )
    payload = serialize_platform_credential(credential)
    payload["managed_channel_id"] = credential.managed_channel_id
    payload["channel_id"] = channel.channel_id
    return payload


def build_runtime_health(db: Session) -> dict:
    return get_agent_runtime_health(db)


def build_mission_control_payload(db: Session, *, use_cache: bool = True) -> dict:
    now = datetime.now(UTC)
    if use_cache:
        cached_payload = _read_mission_control_cache(now)
        if cached_payload is not None:
            return cached_payload

    channels = [serialize_channel(item) for item in list_platform_channels(db)]
    channels = [item for item in channels if _should_include_mission_channel(item)]
    visible_channel_ids = {str(item.get("channel_id")) for item in channels if item.get("channel_id")}

    workers = [
        item
        for item in list_agent_workers(db, ensure_channels=False)
        if not item.get("channel_id") or item.get("channel_id") in visible_channel_ids
    ]
    runs_for_health = [
        item
        for item in list_agent_runs(db, limit=200, ensure_channels=False)
        if not item.get("channel_id") or item.get("channel_id") in visible_channel_ids
    ]
    runs = runs_for_health[:30]
    recent_content = [
        item
        for item in list_content_items(db, limit=12, ensure_channels=False)
        if item.get("channel_id") in visible_channel_ids
    ]
    runtime_health = _runtime_health_from_serialized(workers, runs_for_health)

    alerts: list[dict[str, str]] = []
    disconnected = [item for item in channels if item.get("oauth_state") in {"not_configured", "disconnected", "attention"}]
    failed_channels = [item for item in channels if int(item.get("failed_items", 0)) > 0]
    failed_runs = [item for item in runs if item.get("status") == "failed"]

    if disconnected:
        alerts.append(
            {
                "key": "oauth-state",
                "level": "info",
                "title": "연동 점검 필요",
                "message": f"{len(disconnected)}개 채널에서 인증 또는 권한 확인이 필요합니다.",
            }
        )
    if failed_channels:
        alerts.append(
            {
                "key": "failed-content",
                "level": "warning",
                "title": "실패 콘텐츠 존재",
                "message": f"{len(failed_channels)}개 채널에 실패 상태의 콘텐츠가 남아 있습니다.",
            }
        )
    if failed_runs:
        alerts.append(
            {
                "key": "failed-runs",
                "level": "warning",
                "title": "실패 실행 감지",
                "message": f"최근 실행에서 {len(failed_runs)}건의 실패가 감지되었습니다.",
            }
        )

    payload = {
        "workspace_label": "동그리 자동 블로그전트",
        "channels": channels,
        "workers": workers,
        "runs": runs,
        "recent_content": recent_content,
        "runtime_health": runtime_health,
        "alerts": alerts,
    }
    if use_cache:
        _write_mission_control_cache(payload, now)
    return payload
