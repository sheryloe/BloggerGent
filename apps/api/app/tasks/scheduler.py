from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.entities import WorkflowStageType
from app.services.blog_service import get_workflow_step, list_active_blogs
from app.services.publishing_service import process_publish_queue_batch
from app.services.settings_service import get_settings_map, upsert_settings
from app.tasks.pipeline import discover_topics_and_enqueue


@celery_app.task(name="app.tasks.scheduler.run_scheduler_tick")
def run_scheduler_tick() -> dict:
    db = SessionLocal()
    try:
        settings_map = get_settings_map(db)
        if settings_map.get("schedule_enabled", "true").lower() != "true":
            return {"status": "disabled"}

        tz = ZoneInfo(settings_map.get("schedule_timezone", "Asia/Seoul"))
        now = datetime.now(tz)
        current_time = now.strftime("%H:%M")
        today = now.date().isoformat()
        scheduled_time = settings_map.get("schedule_time", "09:00")
        last_run = settings_map.get("last_schedule_run_on", "")

        if current_time != scheduled_time or last_run == today:
            return {"status": "idle", "current_time": current_time, "scheduled_time": scheduled_time, "last_run": last_run}

        active_blogs = list_active_blogs(db)
        discovery_enabled_blogs = [
            blog
            for blog in active_blogs
            if (step := get_workflow_step(blog, WorkflowStageType.TOPIC_DISCOVERY)) and step.is_enabled
        ]
        results = [discover_topics_and_enqueue(db, blog_id=blog.id) for blog in discovery_enabled_blogs]
        upsert_settings(db, {"last_schedule_run_on": today})
        return {
            "status": "triggered",
            "blog_runs": results,
            "skipped_blogs": [
                {"blog_id": blog.id, "blog_name": blog.name}
                for blog in active_blogs
                if blog.id not in {item.id for item in discovery_enabled_blogs}
            ],
        }
    finally:
        db.close()


@celery_app.task(name="app.tasks.scheduler.process_publish_queue")
def process_publish_queue() -> dict:
    db = SessionLocal()
    try:
        return process_publish_queue_batch(db)
    finally:
        db.close()
