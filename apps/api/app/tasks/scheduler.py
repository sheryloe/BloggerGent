from __future__ import annotations

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import or_

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.entities import ContentPlanDay, ContentPlanSlot, PublishMode, WorkflowStageType
from app.services.blog_service import enforce_free_tier_model_policy, get_workflow_step, list_active_blogs
from app.services.cloudflare_channel_service import run_cloudflare_daily_schedule
from app.services.content_ops_service import sync_live_content_reviews
from app.services.metric_ingestion_service import run_workspace_metric_sync_schedule
from app.services.planner_service import run_slot_generation
from app.services.google_sheet_service import sync_google_sheet_snapshot
from app.services.publishing_service import process_publish_queue_batch
from app.services.platform_publish_service import process_platform_publish_queue
from app.services.settings_service import get_settings_map, upsert_settings
from app.services.telegram_service import poll_telegram_ops_commands, send_telegram_error_notification
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
        "default_time": "00:00",
        "interval_hours_key": "travel_schedule_interval_hours",
        "default_interval_hours": 2,
        "topic_count_key": "travel_topics_per_run",
        "default_topic_count": 1,
        "last_run_key": "last_schedule_run_on_travel",
    },
    {
        "profile_key": "world_mystery",
        "label": "mystery",
        "time_key": "mystery_schedule_time",
        "default_time": "01:00",
        "interval_hours_key": "mystery_schedule_interval_hours",
        "default_interval_hours": 2,
        "topic_count_key": "mystery_topics_per_run",
        "default_topic_count": 1,
        "last_run_key": "last_schedule_run_on_mystery",
    },
)

EDITORIAL_CATEGORY_RULES = {
    "korea_travel": {
        "weights_key": "travel_editorial_weights",
        "last_key": "travel_editorial_last_category",
        "streak_key": "travel_editorial_last_streak",
        "counts_key": "travel_editorial_daily_counts",
        "categories": (
            {
                "key": "travel",
                "label": "Travel",
                "guidance": "Focus on routes, movement logic, transit choices, and local travel planning.",
                "weight": 45,
            },
            {
                "key": "culture",
                "label": "Culture",
                "guidance": "Focus on festivals, exhibitions, events, heritage, and cultural spaces.",
                "weight": 30,
            },
            {
                "key": "food",
                "label": "Food",
                "guidance": "Focus on trending Korean food, local restaurants, market food, and practical dining decisions.",
                "weight": 25,
            },
        ),
    },
    "world_mystery": {
        "weights_key": "mystery_editorial_weights",
        "last_key": "mystery_editorial_last_category",
        "streak_key": "mystery_editorial_last_streak",
        "counts_key": "mystery_editorial_daily_counts",
        "categories": (
            {
                "key": "case-files",
                "label": "Case Files",
                "guidance": "Focus on documented cases, timelines, evidence, investigations, and unresolved factual questions.",
                "weight": 45,
            },
            {
                "key": "mystery-archives",
                "label": "Mystery Archives",
                "guidance": "Focus on archival records, historical enigmas, and document-based reconstructions.",
                "weight": 30,
            },
            {
                "key": "legends-lore",
                "label": "Legends & Lore",
                "guidance": "Focus on folklore, legends, urban lore, and SCP-style fictional world interpretation.",
                "weight": 25,
            },
        ),
    },
}


def _normalize_editorial_key(value: str) -> str:
    return "-".join(part for part in "".join(ch.lower() if ch.isalnum() else "-" for ch in (value or "")).split("-") if part)


def _parse_editorial_weights(raw_value: str | None, categories: tuple[dict, ...]) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for chunk in str(raw_value or "").split(","):
        part = chunk.strip()
        if not part or ":" not in part:
            continue
        label, weight_text = part.split(":", maxsplit=1)
        key = _normalize_editorial_key(label)
        try:
            weight = int(weight_text.strip())
        except ValueError:
            continue
        if key and weight > 0:
            parsed[key] = weight
    if parsed:
        return parsed
    return {_normalize_editorial_key(item["key"]): int(item["weight"]) for item in categories}


def _load_daily_counts(raw_value: str | None, *, today: str, keys: list[str]) -> dict[str, int]:
    try:
        payload = json.loads(raw_value or "{}")
    except json.JSONDecodeError:
        payload = {}
    if str(payload.get("date") or "") != today:
        return {key: 0 for key in keys}
    counts = payload.get("counts")
    if not isinstance(counts, dict):
        return {key: 0 for key in keys}
    normalized: dict[str, int] = {}
    for key in keys:
        try:
            normalized[key] = max(int(str(counts.get(key) or "0")), 0)
        except (TypeError, ValueError):
            normalized[key] = 0
    return normalized


def _dump_daily_counts(*, today: str, counts: dict[str, int]) -> str:
    return json.dumps({"date": today, "counts": counts}, ensure_ascii=False)


def _pick_editorial_category(
    *,
    profile_key: str,
    settings_map: dict[str, str],
    today: str,
) -> tuple[dict | None, dict[str, str]]:
    rule = EDITORIAL_CATEGORY_RULES.get(profile_key)
    if not rule:
        return None, {}

    categories: tuple[dict, ...] = rule["categories"]
    weights = _parse_editorial_weights(settings_map.get(rule["weights_key"]), categories)
    keys = [_normalize_editorial_key(item["key"]) for item in categories]
    counts = _load_daily_counts(settings_map.get(rule["counts_key"]), today=today, keys=keys)
    total_so_far = sum(counts.values())
    total_weight = sum(weights.get(key, 1) for key in keys) or len(keys)

    last_key = _normalize_editorial_key(settings_map.get(rule["last_key"]) or "")
    try:
        last_streak = max(int(str(settings_map.get(rule["streak_key"]) or "0")), 0)
    except ValueError:
        last_streak = 0

    ranked = sorted(
        keys,
        key=lambda key: (
            ((weights.get(key, 1) / total_weight) * (total_so_far + 1)) - counts.get(key, 0),
            weights.get(key, 1),
            -counts.get(key, 0),
        ),
        reverse=True,
    )
    if last_key and last_streak >= 2 and len(ranked) > 1:
        ranked = [key for key in ranked if key != last_key] + [last_key]
    selected_key = ranked[0] if ranked else keys[0]

    selected = next((item for item in categories if _normalize_editorial_key(item["key"]) == selected_key), categories[0])
    counts[selected_key] = counts.get(selected_key, 0) + 1
    next_streak = (last_streak + 1) if selected_key == last_key else 1
    updates = {
        rule["last_key"]: selected_key,
        rule["streak_key"]: str(next_streak),
        rule["counts_key"]: _dump_daily_counts(today=today, counts=counts),
    }
    return selected, updates


def _iter_fallback_editorial_categories(*, profile_key: str, preferred_key: str | None) -> list[dict]:
    rule = EDITORIAL_CATEGORY_RULES.get(profile_key)
    if not rule:
        return []
    preferred = _normalize_editorial_key(preferred_key or "")
    categories: tuple[dict, ...] = rule["categories"]
    if not preferred:
        return list(categories)
    return [item for item in categories if _normalize_editorial_key(item.get("key", "")) != preferred]


def _build_forced_editorial_updates(
    *,
    profile_key: str,
    settings_map: dict[str, str],
    today: str,
    selected_key: str,
) -> dict[str, str]:
    rule = EDITORIAL_CATEGORY_RULES.get(profile_key)
    if not rule:
        return {}

    categories: tuple[dict, ...] = rule["categories"]
    keys = [_normalize_editorial_key(item["key"]) for item in categories]
    normalized_key = _normalize_editorial_key(selected_key)
    if normalized_key not in keys:
        return {}

    counts = _load_daily_counts(settings_map.get(rule["counts_key"]), today=today, keys=keys)
    counts[normalized_key] = counts.get(normalized_key, 0) + 1

    last_key = _normalize_editorial_key(settings_map.get(rule["last_key"]) or "")
    try:
        last_streak = max(int(str(settings_map.get(rule["streak_key"]) or "0")), 0)
    except ValueError:
        last_streak = 0
    next_streak = (last_streak + 1) if normalized_key == last_key else 1

    return {
        rule["last_key"]: normalized_key,
        rule["streak_key"]: str(next_streak),
        rule["counts_key"]: _dump_daily_counts(today=today, counts=counts),
    }


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


def _parse_schedule_minutes(raw_value: str | None, fallback: str) -> int:
    candidate = str(raw_value or fallback).strip() or fallback
    parts = candidate.split(":")
    if len(parts) != 2:
        candidate = fallback
        parts = candidate.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except (TypeError, ValueError):
        hour, minute = 0, 0
    hour = max(0, min(hour, 23))
    minute = max(0, min(minute, 59))
    return (hour * 60) + minute


def _slot_marker_for_now(
    now: datetime,
    *,
    start_time_raw: str | None,
    fallback_time: str,
    interval_hours: int,
) -> str | None:
    interval_minutes = max(interval_hours, 1) * 60
    current_minutes = (now.hour * 60) + now.minute
    start_minutes = _parse_schedule_minutes(start_time_raw, fallback_time)
    delta_minutes = current_minutes - start_minutes
    if delta_minutes < 0 or delta_minutes % interval_minutes != 0:
        return None
    return now.replace(second=0, microsecond=0).isoformat(timespec="minutes")


WEEKDAY_NAMES = {
    0: "MONDAY",
    1: "TUESDAY",
    2: "WEDNESDAY",
    3: "THURSDAY",
    4: "FRIDAY",
    5: "SATURDAY",
    6: "SUNDAY",
}


def _scheduler_slot_ready(slot: ContentPlanSlot) -> bool:
    if slot.scheduled_for is None:
        return False
    if not str(slot.category_key or "").strip():
        return False
    if not str(slot.brief_topic or "").strip():
        return False
    if not str(slot.brief_audience or "").strip():
        return False
    return True


def _run_planner_due_slots(db, *, now: datetime) -> dict:
    now_utc = now.astimezone(timezone.utc)
    due_slots = (
        db.query(ContentPlanSlot)
        .join(ContentPlanDay, ContentPlanSlot.plan_day_id == ContentPlanDay.id)
        .filter(ContentPlanSlot.status.in_(["planned", "brief_ready"]))
        .filter(ContentPlanSlot.scheduled_for.is_not(None))
        .filter(ContentPlanSlot.scheduled_for <= now_utc)
        .filter(
            or_(
                ContentPlanDay.channel_id.like("blogger:%"),
                ContentPlanDay.channel_id.like("cloudflare:%"),
            )
        )
        .order_by(ContentPlanDay.channel_id.asc(), ContentPlanSlot.scheduled_for.asc(), ContentPlanSlot.slot_order.asc(), ContentPlanSlot.id.asc())
        .all()
    )
    if not due_slots:
        return {"status": "idle", "processed": 0, "triggered": 0, "items": []}

    first_due_by_channel: dict[str, ContentPlanSlot] = {}
    for slot in due_slots:
        channel_id = str(slot.plan_day.channel_id or "").strip()
        if not channel_id or channel_id in first_due_by_channel:
            continue
        first_due_by_channel[channel_id] = slot

    if not first_due_by_channel:
        return {"status": "idle", "processed": 0, "triggered": 0, "items": []}

    items: list[dict] = []
    triggered = 0
    for channel_id in sorted(first_due_by_channel):
        slot = first_due_by_channel[channel_id]
        provider = channel_id.split(":", maxsplit=1)[0]
        if not _scheduler_slot_ready(slot):
            items.append(
                {
                    "slot_id": slot.id,
                    "channel_id": channel_id,
                    "provider": provider,
                    "status": "blocked",
                    "reason": "slot_not_ready",
                }
            )
            continue
        try:
            run_slot_generation(db, slot.id, publish_mode_override=PublishMode.PUBLISH)
        except ValueError as exc:
            db.rollback()
            items.append(
                {
                    "slot_id": slot.id,
                    "channel_id": channel_id,
                    "provider": provider,
                    "status": "blocked",
                    "reason": str(exc),
                }
            )
            continue
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            send_telegram_error_notification(
                db,
                title="Planner scheduled slot execution failed",
                detail=str(exc),
                context={
                    "slot_id": slot.id,
                    "channel_id": channel_id,
                    "provider": provider,
                },
            )
            items.append(
                {
                    "slot_id": slot.id,
                    "channel_id": channel_id,
                    "provider": provider,
                    "status": "failed",
                    "reason": str(exc),
                }
            )
            continue

        triggered += 1
        items.append(
            {
                "slot_id": slot.id,
                "channel_id": channel_id,
                "provider": provider,
                "status": "triggered",
            }
        )

    return {
        "status": "triggered" if triggered else "idle",
        "processed": len(items),
        "triggered": triggered,
        "items": items,
    }


@celery_app.task(name="app.tasks.scheduler.run_scheduler_tick")
def run_scheduler_tick() -> dict:
    db = SessionLocal()
    try:
        enforce_free_tier_model_policy(db)
        settings_map = get_settings_map(db)
        if settings_map.get("automation_master_enabled", "false").lower() != "true":
            return {"status": "disabled", "reason": "automation_master_disabled"}
        if settings_map.get("automation_scheduler_enabled", "false").lower() != "true":
            return {"status": "disabled", "reason": "automation_scheduler_disabled"}
        if settings_map.get("schedule_enabled", "true").lower() != "true":
            return {"status": "disabled", "reason": "legacy_schedule_disabled"}

        tz = ZoneInfo(settings_map.get("schedule_timezone", "Asia/Seoul"))
        now = datetime.now(tz)
        current_time = now.strftime("%H:%M")
        today = now.date().isoformat()
        active_blogs = list_active_blogs(db)

        profile_runs: list[dict] = []
        run_marker_updates: dict[str, str] = {}
        planner_slot_result: dict | None = None
        cloudflare_daily_result: dict | None = None
        google_indexing_result: dict | None = None
        workspace_metric_sync_result: dict | None = None
        sheet_sync_result: dict | None = None
        training_schedule_result: dict | None = None

        for profile in PROFILE_SCHEDULES:
            scheduled_time = settings_map.get(profile["time_key"], profile["default_time"])
            interval_hours = _parse_non_negative_int(
                settings_map.get(profile["interval_hours_key"]),
                profile["default_interval_hours"],
            ) or profile["default_interval_hours"]
            topic_count = _parse_non_negative_int(
                settings_map.get(profile["topic_count_key"]),
                profile["default_topic_count"],
            ) or profile["default_topic_count"]
            publish_interval_minutes = max(interval_hours * 60, 1)
            last_run = settings_map.get(profile["last_run_key"], "")
            slot_marker = _slot_marker_for_now(
                now,
                start_time_raw=scheduled_time,
                fallback_time=profile["default_time"],
                interval_hours=interval_hours,
            )
            if slot_marker is None or last_run == slot_marker:
                profile_runs.append(
                    {
                        "profile": profile["label"],
                        "status": "idle",
                        "scheduled_time": scheduled_time,
                        "interval_hours": interval_hours,
                        "slot_marker": slot_marker,
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

            publish_at_local = now.replace(second=0, microsecond=0)
            editorial_selection, editorial_updates = _pick_editorial_category(
                profile_key=profile["profile_key"],
                settings_map=settings_map,
                today=today,
            )
            selected_editorial = editorial_selection
            selected_editorial_updates = editorial_updates
            try:
                result = discover_topics_and_enqueue(
                    db,
                    blog_id=blog.id,
                    topic_count=topic_count,
                    scheduled_start=publish_at_local.astimezone(timezone.utc).isoformat(),
                    publish_interval_minutes=publish_interval_minutes,
                    editorial_category_key=(editorial_selection or {}).get("key"),
                    editorial_category_label=(editorial_selection or {}).get("label"),
                    editorial_category_guidance=(editorial_selection or {}).get("guidance"),
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

            queued_topics = int(result.get("queued_topics", 0) or 0)
            fallback_attempts: list[dict] = []
            if queued_topics == 0 and editorial_selection:
                fallback_categories = _iter_fallback_editorial_categories(
                    profile_key=profile["profile_key"],
                    preferred_key=(editorial_selection or {}).get("key"),
                )
                for fallback in fallback_categories:
                    fallback_attempt = {
                        "editorial_category_key": fallback.get("key"),
                        "editorial_category_label": fallback.get("label"),
                        "status": "failed",
                    }
                    try:
                        fallback_result = discover_topics_and_enqueue(
                            db,
                            blog_id=blog.id,
                            topic_count=max(topic_count, 3),
                            scheduled_start=publish_at_local.astimezone(timezone.utc).isoformat(),
                            publish_interval_minutes=publish_interval_minutes,
                            editorial_category_key=(fallback or {}).get("key"),
                            editorial_category_label=(fallback or {}).get("label"),
                            editorial_category_guidance=(fallback or {}).get("guidance"),
                        )
                    except Exception as fallback_exc:  # noqa: BLE001
                        db.rollback()
                        fallback_attempt["status"] = "error"
                        fallback_attempt["reason"] = str(fallback_exc)
                        fallback_attempts.append(fallback_attempt)
                        continue

                    fallback_attempt["result"] = fallback_result
                    fallback_attempt["status"] = "queued" if int(fallback_result.get("queued_topics", 0) or 0) > 0 else "empty"
                    fallback_attempts.append(fallback_attempt)

                    if int(fallback_result.get("queued_topics", 0) or 0) > 0:
                        result = fallback_result
                        selected_editorial = fallback
                        selected_editorial_updates = _build_forced_editorial_updates(
                            profile_key=profile["profile_key"],
                            settings_map=settings_map,
                            today=today,
                            selected_key=str((fallback or {}).get("key") or ""),
                        )
                        queued_topics = int(result.get("queued_topics", 0) or 0)
                        break

            run_marker_updates[profile["last_run_key"]] = slot_marker
            run_marker_updates.update(selected_editorial_updates)
            if queued_topics == 0:
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
                        "slot_marker": slot_marker,
                        "editorial_category_key": (selected_editorial or {}).get("key"),
                        "fallback_attempts": fallback_attempts,
                    },
                )
            profile_runs.append(
                {
                    "profile": profile["label"],
                    "status": "triggered",
                    "blog_id": blog.id,
                    "blog_name": blog.name,
                    "scheduled_time": scheduled_time,
                    "interval_hours": interval_hours,
                    "topic_count": topic_count,
                    "publish_interval_minutes": publish_interval_minutes,
                    "slot_marker": slot_marker,
                    "editorial_category_key": (selected_editorial or {}).get("key"),
                    "editorial_category_label": (selected_editorial or {}).get("label"),
                    "first_publish_at": publish_at_local.isoformat(),
                    "fallback_attempts": fallback_attempts,
                    "result": result,
                }
            )

        if run_marker_updates:
            upsert_settings(db, run_marker_updates)

        try:
            planner_slot_result = _run_planner_due_slots(db, now=now)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            planner_slot_result = {"status": "failed", "detail": str(exc)}
            send_telegram_error_notification(
                db,
                title="Planner schedule tick failed",
                detail=str(exc),
                context={"current_time": current_time, "timezone": str(tz)},
            )

        try:
            cloudflare_daily_result = run_cloudflare_daily_schedule(db, now=now)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            cloudflare_daily_result = {"status": "failed", "detail": str(exc)}
            send_telegram_error_notification(
                db,
                title="Cloudflare daily generation failed",
                detail=str(exc),
                context={"current_time": current_time, "timezone": str(tz)},
            )

        google_indexing_result = {"status": "disabled", "reason": "manual_only_mode"}

        try:
            workspace_metric_sync_result = run_workspace_metric_sync_schedule(
                db,
                now=now.astimezone(timezone.utc),
                refresh_indexing=False,
            )
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            workspace_metric_sync_result = {"status": "failed", "detail": str(exc)}
            send_telegram_error_notification(
                db,
                title="Workspace metric sync failed",
                detail=str(exc),
                context={"current_time": current_time, "timezone": str(tz)},
            )

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
        learning_paused = (settings_map.get("content_ops_learning_paused") or "").strip().lower() == "true"
        if learning_paused:
            training_schedule_result = {
                "status": "paused",
                "time": training_schedule.time,
                "timezone": training_schedule.timezone,
            }
        elif training_schedule.enabled and training_now.strftime("%H:%M") == training_schedule.time and training_last_run != training_today:
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
            "planner_slots": planner_slot_result,
            "cloudflare_daily": cloudflare_daily_result,
            "google_indexing": google_indexing_result,
            "workspace_metrics": workspace_metric_sync_result,
            "sheet_sync": sheet_sync_result,
            "training_schedule": training_schedule_result,
        }
    finally:
        db.close()


@celery_app.task(name="app.tasks.scheduler.process_publish_queue")
def process_publish_queue() -> dict:
    db = SessionLocal()
    try:
        settings_map = get_settings_map(db)
        if settings_map.get("automation_master_enabled", "false").lower() != "true":
            return {"status": "disabled", "reason": "automation_master_disabled"}
        if settings_map.get("automation_publish_queue_enabled", "false").lower() != "true":
            return {"status": "disabled", "reason": "automation_publish_queue_disabled"}
        blogger_result = process_publish_queue_batch(db)
        workspace_result = process_platform_publish_queue(db)
        return {
            "status": "ok",
            "blogger": blogger_result,
            "workspace": workspace_result,
        }
    finally:
        db.close()


@celery_app.task(name="app.tasks.scheduler.run_content_ops_scan")
def run_content_ops_scan() -> dict:
    db = SessionLocal()
    try:
        settings_map = get_settings_map(db)
        if settings_map.get("automation_master_enabled", "false").lower() != "true":
            return {"status": "disabled", "reason": "automation_master_disabled"}
        if settings_map.get("automation_content_review_enabled", "false").lower() != "true":
            return {"status": "disabled", "reason": "automation_content_review_disabled"}
        return sync_live_content_reviews(db)
    finally:
        db.close()


@celery_app.task(name="app.tasks.scheduler.poll_telegram_ops")
def poll_telegram_ops() -> dict:
    db = SessionLocal()
    try:
        settings_map = get_settings_map(db)
        if settings_map.get("automation_master_enabled", "false").lower() != "true":
            return {"status": "disabled", "reason": "automation_master_disabled"}
        if settings_map.get("automation_telegram_enabled", "false").lower() != "true":
            return {"status": "disabled", "reason": "automation_telegram_disabled"}
        return poll_telegram_ops_commands(db)
    finally:
        db.close()
