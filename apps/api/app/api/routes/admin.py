from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.api import CloudflareR2MigrationRead, CloudflareR2MigrationRequest
from app.services.blog_service import list_visible_blog_ids
from app.services.cloudflare_r2_migration_service import run_cloudflare_r2_image_migration
from app.services.providers.base import ProviderRuntimeError

router = APIRouter()


def _empty_image_migration_response(mode: str) -> dict:
    return {
        "mode": mode,
        "candidate_count": 0,
        "processable_count": 0,
        "skipped_count": 0,
        "updated_count": 0,
        "failed_count": 0,
        "items": [],
    }


@router.post("/image-migrations/cloudflare-r2", response_model=CloudflareR2MigrationRead)
def migrate_generated_article_images_to_cloudflare_r2(
    payload: CloudflareR2MigrationRequest | None = Body(default=None),
    db: Session = Depends(get_db),
) -> dict:
    request_payload = payload or CloudflareR2MigrationRequest()
    visible_blog_ids = set(list_visible_blog_ids(db))
    if not visible_blog_ids:
        return _empty_image_migration_response(request_payload.mode)

    if request_payload.blog_id is not None:
        if request_payload.blog_id not in visible_blog_ids:
            raise HTTPException(status_code=404, detail="Blog not found")
        blog_ids = {request_payload.blog_id}
    else:
        blog_ids = visible_blog_ids

    try:
        return run_cloudflare_r2_image_migration(
            db,
            blog_ids=blog_ids,
            mode=request_payload.mode,
            limit=request_payload.limit,
        )
    except ProviderRuntimeError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code or 502, detail=exc.detail or exc.message) from exc
