from __future__ import annotations

from celery import Celery

from app.core.config import settings

celery_app = Celery("bloggent", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_track_started=True,
    timezone=settings.schedule_timezone,
    enable_utc=True,
    task_default_queue="default",
    result_extended=True,
    imports=("app.tasks.pipeline", "app.tasks.scheduler"),
    beat_schedule={
        "run-scheduler-tick": {
            "task": "app.tasks.scheduler.run_scheduler_tick",
            "schedule": 60.0,
        }
    },
)
