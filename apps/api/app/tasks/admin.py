from __future__ import annotations

from datetime import datetime, timezone

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.services.blogger_label_backfill_service import execute_blogger_editorial_label_backfill


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
