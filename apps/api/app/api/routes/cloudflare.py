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
    IntegratedArchiveItemRead,
    IntegratedChannelSummaryRead,
    IntegratedRunItemRead,
)
from app.services.cloudflare_channel_service import (
    generate_cloudflare_posts,
    get_cloudflare_overview,
    get_cloudflare_prompt_bundle,
    list_cloudflare_posts,
    sync_cloudflare_prompts_from_files,
    save_cloudflare_prompt,
)
from app.services.google_sheet_service import sync_google_sheet_snapshot

router = APIRouter()


@router.get("/overview", response_model=IntegratedChannelSummaryRead)
def get_cloudflare_overview_route(db: Session = Depends(get_db)) -> dict:
    return get_cloudflare_overview(db)


@router.get("/posts", response_model=list[IntegratedArchiveItemRead])
def get_cloudflare_posts_route(db: Session = Depends(get_db)) -> list[dict]:
    return list_cloudflare_posts(db)


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
