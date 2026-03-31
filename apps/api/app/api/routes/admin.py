from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.schemas.api import (
    BloggerEditorialLabelBackfillRead,
    BloggerEditorialLabelBackfillRequest,
    CloudflareR2MigrationRead,
    CloudflareR2MigrationRequest,
)
from app.services.blog_service import list_visible_blog_ids
from app.services.blogger_label_backfill_service import dry_run_blogger_editorial_label_backfill
from app.services.cloudflare_r2_migration_service import run_cloudflare_r2_image_migration
from app.services.providers.base import ProviderRuntimeError
from app.tasks.admin import run_blogger_editorial_label_backfill

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


def _ops_health_report_dir() -> Path:
    return Path(settings.storage_root) / "reports"


def _list_ops_health_reports(limit: int = 20) -> list[Path]:
    report_dir = _ops_health_report_dir()
    if not report_dir.exists():
        return []
    files = [path for path in report_dir.glob("ops-health-*.json") if path.is_file()]
    files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return files[: max(limit, 1)]


@router.get("/ops-health/latest")
def get_latest_ops_health_report() -> dict:
    files = _list_ops_health_reports(limit=20)
    if not files:
        return {
            "status": "missing",
            "file_path": "",
            "report": None,
            "recent_files": [],
        }

    latest = files[0]
    try:
        report = json.loads(latest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Invalid ops-health report JSON: {latest.name}",
        ) from exc

    return {
        "status": "ok",
        "file_path": str(latest),
        "report": report,
        "recent_files": [path.name for path in files],
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


@router.post("/blogger-editorial-label-backfill", response_model=BloggerEditorialLabelBackfillRead)
def backfill_blogger_editorial_labels(
    payload: BloggerEditorialLabelBackfillRequest | None = Body(default=None),
    db: Session = Depends(get_db),
) -> dict:
    request_payload = payload or BloggerEditorialLabelBackfillRequest()
    if request_payload.mode == "dry_run":
        return dry_run_blogger_editorial_label_backfill(
            db,
            profile_keys=list(request_payload.profile_keys or []),
        )

    task = run_blogger_editorial_label_backfill.apply_async(
        kwargs={"profile_keys": list(request_payload.profile_keys or [])},
        queue="default",
    )
    return {
        "status": "queued",
        "mode": "execute",
        "profile_keys": list(request_payload.profile_keys or []),
        "candidate_count": 0,
        "processable_count": 0,
        "skipped_count": 0,
        "updated_count": 0,
        "failed_count": 0,
        "task_id": task.id,
        "report_path": f"storage/reports/blogger-editorial-label-backfill-{task.id}.json",
        "sync_results": [],
        "sheet_sync": None,
        "items": [],
    }
