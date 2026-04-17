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
    CloudflareAssetRebuildRead,
    CloudflareAssetRebuildReportRead,
    CloudflareAssetRebuildRequest,
    CloudflareR2MigrationRead,
    CloudflareR2MigrationRequest,
)
from app.services.platform.blog_service import list_visible_blog_ids
from app.services.blogger.blogger_label_backfill_service import dry_run_blogger_editorial_label_backfill
from app.services.cloudflare.cloudflare_asset_rebuild_service import (
    get_latest_cloudflare_asset_rebuild_report,
    rebuild_cloudflare_assets,
)
from app.services.ops.ops_health_service import generate_ops_health_report
from app.services.cloudflare.cloudflare_r2_migration_service import run_cloudflare_r2_image_migration
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
            "report_path": "",
            "generated_at_kst": None,
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

    generated_at_kst = report.get("generated_at_kst") if isinstance(report, dict) else None
    return {
        "status": "ok",
        "file_path": str(latest),
        "report_path": str(latest),
        "generated_at_kst": generated_at_kst,
        "report": report,
        "recent_files": [path.name for path in files],
    }


@router.post("/ops-health/sync")
def sync_ops_health_report(db: Session = Depends(get_db)) -> dict:
    try:
        result = generate_ops_health_report(db)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={
                "message": "ops_health_sync_failed",
                "detail": str(exc),
            },
        ) from exc

    recent_files = [path.name for path in _list_ops_health_reports(limit=20)]
    file_path = str(result["report_paths"].get("json", ""))
    report = result.get("report") if isinstance(result, dict) else None
    generated_at_kst = report.get("generated_at_kst") if isinstance(report, dict) else None
    return {
        "status": "ok",
        "message": "ops_health_sync_completed",
        "file_path": file_path,
        "report_path": file_path,
        "generated_at_kst": generated_at_kst,
        "report": report,
        "recent_files": recent_files,
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


@router.post("/cloudflare-assets/rebuild", response_model=CloudflareAssetRebuildRead)
def rebuild_cloudflare_channel_assets(
    payload: CloudflareAssetRebuildRequest | None = Body(default=None),
    db: Session = Depends(get_db),
) -> dict:
    request_payload = payload or CloudflareAssetRebuildRequest()
    try:
        return rebuild_cloudflare_assets(
            db,
            mode=request_payload.mode,
            channel_id=request_payload.channel_id,
            category_slugs=list(request_payload.category_slugs or []),
            limit=request_payload.limit,
            purge_target=request_payload.purge_target,
            use_fallback_heuristic=request_payload.use_fallback_heuristic,
        )
    except ProviderRuntimeError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code or 502, detail=exc.detail or exc.message) from exc
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/cloudflare-assets/reports/latest", response_model=CloudflareAssetRebuildReportRead)
def get_latest_cloudflare_asset_rebuild_report_route(db: Session = Depends(get_db)) -> dict:
    try:
        return get_latest_cloudflare_asset_rebuild_report(db)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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
