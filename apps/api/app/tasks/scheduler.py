from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.entities import JobStatus, WorkflowStageType
from app.services.blog_service import get_workflow_step, list_active_blogs
from app.services.google_sheet_service import sync_google_sheet_snapshot
from app.services.publishing_service import process_publish_queue_batch
from app.services.settings_service import get_settings_map, upsert_settings
from app.services.telegram_service import send_telegram_error_notification
from app.services.training_service import (
    DEFAULT_SAVE_EVERY_MINUTES,
    DEFAULT_SESSION_HOURS,
    SCHEDULE_LAST_RUN_ON_KEY,
    TrainingServiceError,
    get_training_schedule,
    start_training_run,
)
from app.tasks.pipeline import discover_topics_and_enqueue
from app.tasks.training import run_training_session


PROFILE_SCHEDULES = (
    {
        "profile_key": "korea_travel",
        "label": "travel",
        "time_key": "travel_schedule_time",
        "default_time": "12:00",
        "last_run_key": "last_schedule_run_on_travel",
    },
    {
        "profile_key": "world_mystery",
        "label": "mystery",
        "time_key": "mystery_schedule_time",
        "default_time": "12:30",
        "last_run_key": "last_schedule_run_on_mystery",
    },
)


def _parse_non_negative_int(raw_value: str | None, fallback: int) -> int:
    try:
        parsed = int(str(raw_value or fallback).strip())
    except (TypeError, ValueError):
        return fallback
    return max(parsed, 0)


def _representative_blog(active_blogs, profile_key: str):
    candidates = [
        blog
        for blog in active_blogs
        if blog.profile_key == profile_key
        and (step := get_workflow_step(blog, WorkflowStageType.TOPIC_DISCOVERY))
        and step.is_enabled
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (item.created_at, item.id))[0]


WEEKDAY_NAMES = {
    0: "MONDAY",
    1: "TUESDAY",
    2: "WEDNESDAY",
    3: "THURSDAY",
    4: "FRIDAY",
    5: "SATURDAY",
    6: "SUNDAY",
}


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
        active_blogs = list_active_blogs(db)
        topics_per_run = _parse_non_negative_int(settings_map.get("topics_per_run"), 9) or 9
        publish_interval_minutes = _parse_non_negative_int(settings_map.get("publish_interval_minutes"), 60) or 60
        first_publish_delay_minutes = _parse_non_negative_int(settings_map.get("first_publish_delay_minutes"), 60)

        profile_runs: list[dict] = []
        run_marker_updates: dict[str, str] = {}
        sheet_sync_result: dict | None = None
        training_schedule_result: dict | None = None

        for profile in PROFILE_SCHEDULES:
            scheduled_time = settings_map.get(profile["time_key"], profile["default_time"])
            last_run = settings_map.get(profile["last_run_key"], "")
            if current_time != scheduled_time or last_run == today:
                profile_runs.append(
                    {
                        "profile": profile["label"],
                        "status": "idle",
                        "scheduled_time": scheduled_time,
                        "last_run": last_run,
                    }
                )
                continue

            blog = _representative_blog(active_blogs, profile["profile_key"])
            if blog is None:
                profile_runs.append(
                    {
                        "profile": profile["label"],
                        "status": "skipped",
                        "reason": "No active representative blog with topic discovery enabled.",
                    }
                )
                continue

            first_slot_local = (now + timedelta(minutes=first_publish_delay_minutes)).replace(second=0, microsecond=0)
            try:
                result = discover_topics_and_enqueue(
                    db,
                    blog_id=blog.id,
                    stop_after=JobStatus.ASSEMBLING_HTML,
                    topic_count=topics_per_run,
                    scheduled_start=first_slot_local.astimezone(timezone.utc).isoformat(),
                    publish_interval_minutes=publish_interval_minutes,
                )
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                send_telegram_error_notification(
                    db,
                    title="Scheduled generation failed",
                    detail=str(exc),
                    context={
                        "profile": profile["label"],
                        "blog": blog.name,
                        "blog_id": blog.id,
                        "scheduled_time": scheduled_time,
                    },
                )
                profile_runs.append(
                    {
                        "profile": profile["label"],
                        "status": "failed",
                        "blog_id": blog.id,
                        "blog_name": blog.name,
                        "scheduled_time": scheduled_time,
                        "reason": str(exc),
                    }
                )
                continue

            run_marker_updates[profile["last_run_key"]] = today
            if int(result.get("queued_topics", 0) or 0) == 0:
                send_telegram_error_notification(
                    db,
                    title="Scheduled generation produced no articles",
                    detail=result.get("message") or "No jobs were queued for this scheduled run.",
                    context={
                        "profile": profile["label"],
                        "blog": blog.name,
                        "blog_id": blog.id,
                        "scheduled_time": scheduled_time,
                        "topic_count": result.get("topic_count"),
                    },
                )
            profile_runs.append(
                {
                    "profile": profile["label"],
                    "status": "triggered",
                    "blog_id": blog.id,
                    "blog_name": blog.name,
                    "scheduled_time": scheduled_time,
                    "topic_count": topics_per_run,
                    "publish_interval_minutes": publish_interval_minutes,
                    "first_publish_at": first_slot_local.isoformat(),
                    "result": result,
                }
            )

        if run_marker_updates:
            upsert_settings(db, run_marker_updates)

        sheet_sync_enabled = settings_map.get("sheet_sync_enabled", "false").lower() == "true"
        expected_day = (settings_map.get("sheet_sync_day") or "SUNDAY").strip().upper() or "SUNDAY"
        expected_time = (settings_map.get("sheet_sync_time") or "13:00").strip() or "13:00"
        last_sheet_sync_on = (settings_map.get("last_sheet_sync_on") or "").strip()
        if sheet_sync_enabled and WEEKDAY_NAMES.get(now.weekday()) == expected_day and current_time == expected_time:
            if last_sheet_sync_on != today:
                try:
                    sheet_sync_result = sync_google_sheet_snapshot(db, initial=False)
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    sheet_sync_result = {"status": "failed", "detail": str(exc)}
                    send_telegram_error_notification(
                        db,
                        title="Google Sheet sync failed",
                        detail=str(exc),
                        context={
                            "scheduled_time": expected_time,
                            "scheduled_day": expected_day,
                        },
                    )
                else:
                    run_marker_updates["last_sheet_sync_on"] = today
                    upsert_settings(db, {"last_sheet_sync_on": today})
            else:
                sheet_sync_result = {"status": "idle", "reason": "already_synced_today"}

        training_schedule = get_training_schedule(settings_map)
        training_now = datetime.now(ZoneInfo(training_schedule.timezone))
        training_today = training_now.date().isoformat()
        training_last_run = (settings_map.get(SCHEDULE_LAST_RUN_ON_KEY) or "").strip()
        if training_schedule.enabled and training_now.strftime("%H:%M") == training_schedule.time and training_last_run != training_today:
            try:
                run = start_training_run(
                    db,
                    session_hours=DEFAULT_SESSION_HOURS,
                    save_every_minutes=DEFAULT_SAVE_EVERY_MINUTES,
                    trigger_source="schedule",
                )
                run_training_session.apply_async(args=[run.id], queue="training")
                training_schedule_result = {
                    "status": "triggered",
                    "run_id": run.id,
                    "time": training_schedule.time,
                    "timezone": training_schedule.timezone,
                }
            except TrainingServiceError as exc:
                training_schedule_result = {
                    "status": "skipped",
                    "reason": exc.message,
                    "time": training_schedule.time,
                    "timezone": training_schedule.timezone,
                }
            upsert_settings(db, {SCHEDULE_LAST_RUN_ON_KEY: training_today})
        elif training_schedule.enabled:
            training_schedule_result = {
                "status": "idle",
                "time": training_schedule.time,
                "timezone": training_schedule.timezone,
                "last_run_on": training_last_run or None,
            }

        triggered = [item for item in profile_runs if item.get("status") == "triggered"]
        return {
            "status": "triggered" if triggered else "idle",
            "current_time": current_time,
            "timezone": str(tz),
            "profile_runs": profile_runs,
            "sheet_sync": sheet_sync_result,
            "training_schedule": training_schedule_result,
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
