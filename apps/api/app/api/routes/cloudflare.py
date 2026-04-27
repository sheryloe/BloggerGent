from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.api.deps.admin_auth import AdminMutationRoute, require_admin_auth
from app.schemas.api import (
    CloudflareGenerateRead,
    CloudflareGenerateRequest,
    CloudflarePersonaFitPreviewRead,
    CloudflarePersonaFitPreviewRequest,
    CloudflarePersonaPackRead,
    CloudflarePersonaPackUpdate,
    CloudflarePerformancePageRead,
    CloudflarePrnPreviewRead,
    CloudflarePrnPreviewRequest,
    CloudflarePrnRunRead,
    CloudflareRefactorRead,
    CloudflareRefactorRequest,
    CloudflarePerformanceSummaryRead,
    CloudflarePromptBundleRead,
    CloudflarePromptRead,
    CloudflarePromptSyncRead,
    CloudflarePromptSyncRequest,
    CloudflarePromptUpdate,
    IntegratedArchiveCategoryGroupRead,
    IntegratedArchiveItemRead,
    IntegratedChannelSummaryRead,
    IntegratedRunItemRead,
)
from app.services.cloudflare.cloudflare_channel_service import (
    generate_cloudflare_posts,
    get_cloudflare_overview,
    get_cloudflare_prompt_bundle,
    list_cloudflare_categories,
    save_cloudflare_prompt,
    sync_cloudflare_prompts_from_files,
)
from app.services.cloudflare.cloudflare_persona_service import (
    ensure_default_cloudflare_persona_packs,
    get_cloudflare_persona_pack,
    list_cloudflare_persona_packs,
    score_persona_fit,
    set_default_cloudflare_persona_pack,
    upsert_cloudflare_persona_pack,
)
from app.services.cloudflare.cloudflare_prn_service import (
    get_prn_run,
    list_prn_runs,
    normalize_prn_options,
    preview_cloudflare_prn_titles,
)
from app.services.cloudflare.cloudflare_performance_service import (
    get_cloudflare_performance_page,
    get_cloudflare_performance_summary,
)
from app.services.cloudflare.cloudflare_refactor_service import refactor_cloudflare_low_score_posts
from app.services.cloudflare.cloudflare_sync_service import list_synced_cloudflare_posts, sync_cloudflare_posts
from app.services.integrations.google_sheet_service import sync_google_sheet_snapshot
from app.tasks.admin import run_cloudflare_low_score_refactor
from app.models.entities import ManagedChannel

router = APIRouter(route_class=AdminMutationRoute)


def _get_cloudflare_channel(db: Session) -> ManagedChannel:
    channel = (
        db.query(ManagedChannel)
        .filter(ManagedChannel.provider == "cloudflare")
        .order_by(ManagedChannel.id.desc())
        .first()
    )
    if channel is None:
        raise HTTPException(status_code=404, detail="cloudflare_channel_not_configured")
    return channel


@router.get("/overview", response_model=IntegratedChannelSummaryRead)
def get_cloudflare_overview_route(db: Session = Depends(get_db)) -> dict:
    return get_cloudflare_overview(db)


@router.get("/posts", response_model=list[IntegratedArchiveItemRead])
def get_cloudflare_posts_route(db: Session = Depends(get_db)) -> list[dict]:
    return list_synced_cloudflare_posts(db, include_non_published=False)


@router.post("/posts/refresh")
def refresh_cloudflare_posts_route(db: Session = Depends(get_db)) -> dict:
    result = sync_cloudflare_posts(db, include_non_published=False)
    return {
        "status": result.get("status", "ok"),
        "channel_id": result.get("channel_id"),
        "count": result.get("count", 0),
        "last_synced_at": result.get("last_synced_at").isoformat() if result.get("last_synced_at") else None,
        "dedupe": result.get("dedupe", {}),
        "error": result.get("error"),
    }


@router.get("/posts/grouped-by-category", response_model=list[IntegratedArchiveCategoryGroupRead])
def get_cloudflare_posts_grouped_by_category_route(db: Session = Depends(get_db)) -> list[dict]:
    rows = list_synced_cloudflare_posts(db, include_non_published=False)
    grouped: dict[str, dict] = {}
    for row in rows:
        category_slug = str(
            row.get("canonical_category_slug")
            or row.get("category_slug")
            or "uncategorized"
        ).strip() or "uncategorized"
        category_name = str(
            row.get("canonical_category_name")
            or row.get("category_name")
            or category_slug
        ).strip() or category_slug
        group = grouped.setdefault(
            category_slug,
            {
                "category_slug": category_slug,
                "category_name": category_name,
                "total": 0,
                "last_synced_at": None,
                "items": [],
            },
        )
        group["items"].append(row)
        group["total"] += 1
        audited_at = row.get("live_image_audited_at")
        if isinstance(audited_at, str) and audited_at.strip():
            current = group.get("last_synced_at")
            if current is None or audited_at > current:
                group["last_synced_at"] = audited_at

    return sorted(grouped.values(), key=lambda item: item["category_slug"])


@router.get("/performance", response_model=CloudflarePerformancePageRead)
def get_cloudflare_performance_route(
    month: str | None = None,
    status: str | None = None,
    query: str | None = None,
    sort: str | None = None,
    dir: str | None = None,
    low_score_only: bool = False,
    category: str | None = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
) -> dict:
    return get_cloudflare_performance_page(
        db,
        month=month,
        status=status,
        query=query,
        sort=sort,
        dir=dir,
        low_score_only=low_score_only,
        category=category,
        page=page,
        page_size=page_size,
    )


@router.get("/performance/summary", response_model=CloudflarePerformanceSummaryRead)
def get_cloudflare_performance_summary_route(month: str | None = None, db: Session = Depends(get_db)) -> dict:
    return get_cloudflare_performance_summary(db, month=month)


@router.get("/runs", response_model=list[IntegratedRunItemRead])
def get_cloudflare_runs() -> list[dict]:
    return []


@router.get("/prompts", response_model=CloudflarePromptBundleRead)
def get_cloudflare_prompts(db: Session = Depends(get_db)) -> dict:
    return get_cloudflare_prompt_bundle(db)


@router.get(
    "/persona-packs",
    response_model=list[CloudflarePersonaPackRead],
    dependencies=[Depends(require_admin_auth)],
)
def list_cloudflare_persona_packs_route(
    category_slug: str | None = None,
    include_profiles: bool = False,
    seed_defaults: bool = True,
    db: Session = Depends(get_db),
) -> list[dict]:
    channel = _get_cloudflare_channel(db)
    if seed_defaults:
        categories = [item for item in list_cloudflare_categories(db) if bool(item.get("isLeaf"))]
        ensure_default_cloudflare_persona_packs(db, managed_channel=channel, categories=categories)
        db.commit()
    return list_cloudflare_persona_packs(
        db,
        managed_channel_id=channel.id,
        category_slug=category_slug,
        include_profiles=include_profiles,
    )


@router.get(
    "/persona-packs/{category_slug}",
    response_model=list[CloudflarePersonaPackRead],
    dependencies=[Depends(require_admin_auth)],
)
def list_cloudflare_persona_packs_for_category_route(
    category_slug: str,
    include_profiles: bool = True,
    db: Session = Depends(get_db),
) -> list[dict]:
    channel = _get_cloudflare_channel(db)
    return list_cloudflare_persona_packs(
        db,
        managed_channel_id=channel.id,
        category_slug=category_slug,
        include_profiles=include_profiles,
    )


@router.post("/persona-packs/{category_slug}", response_model=CloudflarePersonaPackRead)
def upsert_cloudflare_persona_pack_route(
    category_slug: str,
    payload: CloudflarePersonaPackUpdate,
    db: Session = Depends(get_db),
) -> dict:
    channel = _get_cloudflare_channel(db)
    result = upsert_cloudflare_persona_pack(
        db,
        managed_channel_id=channel.id,
        category_slug=category_slug,
        payload=payload.model_dump(),
    )
    db.commit()
    return result


@router.patch("/persona-packs/{category_slug}/{pack_key}", response_model=CloudflarePersonaPackRead)
def patch_cloudflare_persona_pack_route(
    category_slug: str,
    pack_key: str,
    payload: CloudflarePersonaPackUpdate,
    db: Session = Depends(get_db),
) -> dict:
    channel = _get_cloudflare_channel(db)
    values = payload.model_dump()
    values["pack_key"] = pack_key
    result = upsert_cloudflare_persona_pack(
        db,
        managed_channel_id=channel.id,
        category_slug=category_slug,
        payload=values,
    )
    db.commit()
    return result


@router.post("/persona-packs/{category_slug}/{pack_key}/set-default", response_model=CloudflarePersonaPackRead)
def set_default_cloudflare_persona_pack_route(
    category_slug: str,
    pack_key: str,
    db: Session = Depends(get_db),
) -> dict:
    channel = _get_cloudflare_channel(db)
    try:
        result = set_default_cloudflare_persona_pack(
            db,
            managed_channel_id=channel.id,
            category_slug=category_slug,
            pack_key=pack_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return result


@router.post("/persona-fit/preview", response_model=CloudflarePersonaFitPreviewRead)
def preview_cloudflare_persona_fit_route(
    payload: CloudflarePersonaFitPreviewRequest,
    db: Session = Depends(get_db),
) -> dict:
    channel = _get_cloudflare_channel(db)
    pack = get_cloudflare_persona_pack(
        db,
        managed_channel_id=channel.id,
        category_slug=payload.category_slug,
        pack_key=payload.pack_key,
    )
    result = score_persona_fit(
        pack,
        title=payload.title,
        body_html=payload.body_html,
        excerpt=payload.excerpt,
        labels=payload.labels,
        article_pattern_id=payload.article_pattern_id,
    )
    if result.get("status") == "skipped":
        result["reason"] = result.get("reason") or "persona_pack_not_found"
    return result


@router.post("/prn/preview", response_model=CloudflarePrnPreviewRead)
def preview_cloudflare_prn_route(payload: CloudflarePrnPreviewRequest, db: Session = Depends(get_db)) -> dict:
    channel = _get_cloudflare_channel(db)
    pack = None
    if payload.pack_key or payload.category_slug:
        pack = get_cloudflare_persona_pack(
            db,
            managed_channel_id=channel.id,
            category_slug=payload.category_slug,
            pack_key=payload.pack_key,
            active_only=not bool(payload.pack_key),
        )
    return preview_cloudflare_prn_titles(
        keyword=payload.keyword,
        category_slug=payload.category_slug,
        category_name=payload.category_name,
        persona_pack=pack,
        article_pattern_id=payload.article_pattern_id,
        article_pattern_version=payload.article_pattern_version,
        existing_titles=payload.existing_titles,
        planner_brief=payload.planner_brief,
        options=normalize_prn_options(payload.options),
    )


@router.get("/prn/runs", response_model=list[CloudflarePrnRunRead], dependencies=[Depends(require_admin_auth)])
def list_cloudflare_prn_runs_route(limit: int = 50, db: Session = Depends(get_db)) -> list[dict]:
    channel = _get_cloudflare_channel(db)
    return list_prn_runs(db, managed_channel_id=channel.id, limit=limit)


@router.get("/prn/runs/{run_id}", response_model=CloudflarePrnRunRead, dependencies=[Depends(require_admin_auth)])
def get_cloudflare_prn_run_route(run_id: int, db: Session = Depends(get_db)) -> dict:
    channel = _get_cloudflare_channel(db)
    result = get_prn_run(db, managed_channel_id=channel.id, run_id=run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="cloudflare_prn_run_not_found")
    return result


@router.put("/prompts/{category}/{stage}", response_model=CloudflarePromptRead)
def update_cloudflare_prompt(category: str, stage: str, payload: CloudflarePromptUpdate, db: Session = Depends(get_db)) -> dict:
    return save_cloudflare_prompt(
        db,
        category_key=category,
        stage=stage,
        content=payload.content,
    )


@router.post("/prompts/sync-from-files", response_model=CloudflarePromptSyncRead)
def sync_cloudflare_prompts_from_files_route(
    payload: CloudflarePromptSyncRequest,
    db: Session = Depends(get_db),
) -> dict:
    return sync_cloudflare_prompts_from_files(db, execute=payload.execute)


@router.post("/generate", response_model=CloudflareGenerateRead)
def generate_cloudflare_posts_route(payload: CloudflareGenerateRequest, db: Session = Depends(get_db)) -> dict:
    result = generate_cloudflare_posts(
        db,
        per_category=payload.per_category,
        category_slugs=payload.category_slugs or None,
        category_plan=payload.category_plan or None,
        persona_pack_key_by_category=payload.persona_pack_key_by_category or None,
        prn=payload.prn or None,
        status=payload.status,
    )
    if payload.sync_sheet:
        result["sheet_sync"] = sync_google_sheet_snapshot(db, initial=False)
    return result


@router.post("/refactor-low-score", response_model=CloudflareRefactorRead)
def refactor_cloudflare_low_score_route(
    payload: CloudflareRefactorRequest,
    db: Session = Depends(get_db),
    *,
    queue: bool | None = None,
    parallel_workers: int | None = None,
) -> dict:
    effective_queue = payload.queue if queue is None else bool(queue)
    effective_parallel_workers = payload.parallel_workers if parallel_workers is None else max(int(parallel_workers), 1)

    if effective_queue and payload.execute:
        task = run_cloudflare_low_score_refactor.apply_async(
            kwargs={
                "threshold": payload.threshold,
                "month": payload.month,
                "category_slugs": payload.category_slugs or None,
                "limit": payload.limit,
                "sync_before": payload.sync_before,
                "parallel_workers": effective_parallel_workers,
            },
            queue="default",
        )
        return {
            "status": "queued",
            "execute": True,
            "threshold": payload.threshold,
            "month": payload.month or "",
            "parallel_workers": effective_parallel_workers,
            "task_id": task.id,
            "total_candidates": 0,
            "processed_count": 0,
            "updated_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
            "sync_before_result": None,
            "sync_after_result": None,
            "summary_after": None,
            "items": [],
        }
    kwargs: dict[str, object] = {
        "execute": payload.execute,
        "threshold": payload.threshold,
        "month": payload.month,
        "category_slugs": payload.category_slugs or None,
        "limit": payload.limit,
        "sync_before": payload.sync_before,
        "parallel_workers": effective_parallel_workers,
    }
    if effective_queue:
        kwargs["queue"] = effective_queue

    return refactor_cloudflare_low_score_posts(db, **kwargs)
