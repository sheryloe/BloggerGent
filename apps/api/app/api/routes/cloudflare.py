from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.api import (
    CloudflareGenerateRead,
    CloudflareGenerateRequest,
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
from app.services.cloudflare_channel_service import (
    generate_cloudflare_posts,
    get_cloudflare_overview,
    get_cloudflare_prompt_bundle,
    save_cloudflare_prompt,
    sync_cloudflare_prompts_from_files,
)
from app.services.cloudflare_sync_service import list_synced_cloudflare_posts, sync_cloudflare_posts
from app.services.google_sheet_service import sync_google_sheet_snapshot

router = APIRouter()


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


@router.get("/runs", response_model=list[IntegratedRunItemRead])
def get_cloudflare_runs() -> list[dict]:
    return []


@router.get("/prompts", response_model=CloudflarePromptBundleRead)
def get_cloudflare_prompts(db: Session = Depends(get_db)) -> dict:
    return get_cloudflare_prompt_bundle(db)


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
        status=payload.status,
    )
    if payload.sync_sheet:
        result["sheet_sync"] = sync_google_sheet_snapshot(db, initial=False)
    return result
