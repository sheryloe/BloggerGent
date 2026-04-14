from __future__ import annotations

from datetime import datetime, timezone

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.services.blogger.blogger_label_backfill_service import execute_blogger_editorial_label_backfill
from app.services.blogger.blogger_refactor_service import refactor_blogger_low_score_posts
from app.services.cloudflare.cloudflare_refactor_service import refactor_cloudflare_low_score_posts


@celery_app.task(bind=True, name="app.tasks.admin.run_blogger_editorial_label_backfill")
def run_blogger_editorial_label_backfill(self, profile_keys: list[str] | None = None) -> dict:
    db = SessionLocal()
    try:
        execution_id = getattr(self.request, "id", None) or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return execute_blogger_editorial_label_backfill(
            db,
            profile_keys=profile_keys,
            execution_id=execution_id,
        )
    finally:
        db.close()


@celery_app.task(bind=True, name="app.tasks.admin.run_blogger_low_score_refactor")
def run_blogger_low_score_refactor(
    self,
    blog_id: int,
    threshold: float = 80.0,
    month: str | None = None,
    limit: int | None = None,
    sync_before: bool = True,
    run_lighthouse: bool = True,
    parallel_workers: int = 1,
) -> dict:
    db = SessionLocal()
    try:
        result = refactor_blogger_low_score_posts(
            db,
            blog_id=blog_id,
            execute=True,
            threshold=threshold,
            month=month,
            limit=limit,
            sync_before=sync_before,
            run_lighthouse=run_lighthouse,
            parallel_workers=parallel_workers,
        )
        result["task_id"] = getattr(self.request, "id", None)
        return result
    finally:
        db.close()


@celery_app.task(bind=True, name="app.tasks.admin.run_cloudflare_low_score_refactor")
def run_cloudflare_low_score_refactor(
    self,
    threshold: float = 80.0,
    month: str | None = None,
    category_slugs: list[str] | None = None,
    limit: int | None = None,
    sync_before: bool = True,
    parallel_workers: int = 1,
) -> dict:
    db = SessionLocal()
    try:
        result = refactor_cloudflare_low_score_posts(
            db,
            execute=True,
            threshold=threshold,
            month=month,
            category_slugs=category_slugs,
            limit=limit,
            sync_before=sync_before,
            parallel_workers=parallel_workers,
        )
        result["task_id"] = getattr(self.request, "id", None)
        return result
    finally:
        db.close()
