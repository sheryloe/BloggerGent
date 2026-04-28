from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session


REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
RUNTIME_ENV_PATH = REPO_ROOT / "env" / "runtime.settings.env"
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"
DEFAULT_REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\travel")
TRAVEL_TIMEZONE = ZoneInfo("Asia/Seoul")
TRAVEL_BLOG_IDS = (34, 36, 37)
TRAVEL_LANGUAGES = ("en", "es", "ja")
TRAVEL_BLOG_ID_BY_LANGUAGE = {"en": 34, "es": 36, "ja": 37}
TRAVEL_LANGUAGE_BY_BLOG_ID = {34: "en", 36: "es", 37: "ja"}
AUTOMATION_SETTING_KEYS = (
    "automation_scheduler_enabled",
    "automation_publish_queue_enabled",
)
PIPELINE_SCHEDULE_KEY = "pipeline_schedule"
PLANNER_BRIEF_KEY = "planner_brief"
TRAVEL_SYNC_KEY = "travel_sync"


def _load_runtime_env(path: Path) -> None:
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:  # noqa: BLE001
        return
    for raw_line in lines:
        line = str(raw_line or "").strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and ((value.startswith("'") and value.endswith("'")) or (value.startswith('"') and value.endswith('"'))):
            value = value[1:-1]
        os.environ[key] = value


_load_runtime_env(RUNTIME_ENV_PATH)
os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL") or os.environ.get("BLOGGENT_DATABASE_URL") or DEFAULT_DATABASE_URL
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import ContentPlanDay, ContentPlanSlot, Job, JobStatus, Setting  # noqa: E402
from app.services.content.multilingual_bundle_service import default_target_audience_for_language  # noqa: E402
from app.services.content.travel_blog_policy import (  # noqa: E402
    normalize_travel_category_key,
    normalize_travel_text_generation_route,
    travel_text_generation_route_setting_key,
)
from app.services.content.travel_cross_sync_service import (  # noqa: E402
    TravelSyncBacklogItem,
    apply_travel_sync_group_links,
    build_travel_sync_groups,
    enqueue_travel_cross_sync_jobs,
)
from app.services.integrations.settings_service import upsert_settings  # noqa: E402


ACTIVE_JOB_STATUSES = {
    JobStatus.DISCOVERING_TOPICS,
    JobStatus.GENERATING_ARTICLE,
    JobStatus.GENERATING_IMAGE_PROMPT,
    JobStatus.GENERATING_IMAGE,
    JobStatus.ASSEMBLING_HTML,
    JobStatus.FINDING_RELATED_POSTS,
    JobStatus.PUBLISHING,
}


def _parse_blog_ids(raw: str | None) -> tuple[int, ...]:
    values: list[int] = []
    for token in [segment.strip() for segment in str(raw or "").split(",") if segment.strip()]:
        blog_id = int(token)
        if blog_id not in TRAVEL_BLOG_IDS:
            raise ValueError(f"Travel sync allows only {TRAVEL_BLOG_IDS}; got {blog_id}")
        if blog_id not in values:
            values.append(blog_id)
    if not values:
        raise ValueError("--blog-ids resolved to empty set")
    return tuple(sorted(values))


def _parse_languages(raw: str | None) -> tuple[str, ...]:
    values: list[str] = []
    for token in [segment.strip().lower() for segment in str(raw or "").split(",") if segment.strip()]:
        if token not in TRAVEL_LANGUAGES:
            raise ValueError(f"unsupported language '{token}', allowed={TRAVEL_LANGUAGES}")
        if token not in values:
            values.append(token)
    if not values:
        raise ValueError("language list resolved to empty set")
    return tuple(values)


def _largest_remainder(total: int, days: int) -> list[int]:
    safe_total = max(int(total or 0), 0)
    safe_days = max(int(days or 0), 1)
    base = safe_total // safe_days
    remainder = safe_total % safe_days
    return [base + (1 if index < remainder else 0) for index in range(safe_days)]


def _next_local_start(delay_minutes: int) -> datetime:
    now = datetime.now(TRAVEL_TIMEZONE)
    return now.replace(second=0, microsecond=0) + timedelta(minutes=max(int(delay_minutes), 1))


def _clock(raw: str, fallback: str) -> time:
    value = str(raw or "").strip() or fallback
    try:
        return datetime.strptime(value, "%H:%M").time().replace(second=0, microsecond=0)
    except ValueError:
        return datetime.strptime(fallback, "%H:%M").time().replace(second=0, microsecond=0)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(UTC).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _job_status(job: Job) -> str:
    raw = job.status
    return str(raw.value if hasattr(raw, "value") else raw)


def _is_stale_active_job(job: Job, *, threshold_minutes: int) -> bool:
    if job.status not in ACTIVE_JOB_STATUSES:
        return False
    threshold = datetime.now(UTC) - timedelta(minutes=max(int(threshold_minutes), 1))
    updated_at = getattr(job, "updated_at", None)
    if not isinstance(updated_at, datetime):
        return True
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return updated_at.astimezone(UTC) < threshold


def _job_key(job: Job) -> tuple[int, str] | None:
    prompts = job.raw_prompts if isinstance(job.raw_prompts, dict) else {}
    sync = prompts.get(TRAVEL_SYNC_KEY) if isinstance(prompts.get(TRAVEL_SYNC_KEY), dict) else None
    if not isinstance(sync, dict):
        return None
    target_language = str(sync.get("target_language") or "").strip().lower()
    target_blog_id = int(sync.get("target_blog_id") or TRAVEL_BLOG_ID_BY_LANGUAGE.get(target_language, int(job.blog_id or 0)) or 0)
    group_key = str(sync.get("group_key") or "").strip()
    if target_blog_id not in TRAVEL_BLOG_IDS or not group_key:
        return None
    return (target_blog_id, group_key)


def _item_key(item: TravelSyncBacklogItem) -> tuple[int, str]:
    return (int(item.target_blog_id), str(item.group_key).strip())


def _slot_marker(slot: ContentPlanSlot) -> dict[str, Any] | None:
    payload = slot.result_payload if isinstance(slot.result_payload, dict) else {}
    marker = payload.get("travel_cross_sync") if isinstance(payload.get("travel_cross_sync"), dict) else None
    return marker if isinstance(marker, dict) else None


def _slot_key(slot: ContentPlanSlot) -> tuple[int, str] | None:
    marker = _slot_marker(slot)
    if not marker:
        return None
    target_blog_id = int(marker.get("target_blog_id") or TRAVEL_BLOG_ID_BY_LANGUAGE.get(str(marker.get("target_language") or "").lower(), 0) or 0)
    group_key = str(marker.get("group_key") or "").strip()
    if target_blog_id not in TRAVEL_BLOG_IDS or not group_key:
        return None
    return (target_blog_id, group_key)


def _load_travel_jobs(db: Session, blog_ids: tuple[int, ...]) -> list[Job]:
    rows = db.execute(select(Job).where(Job.blog_id.in_(list(blog_ids))).order_by(Job.id.asc())).scalars().all()
    return [job for job in rows if _job_key(job) is not None]


def _load_travel_slots(db: Session, blog_ids: tuple[int, ...]) -> list[ContentPlanSlot]:
    channel_ids = [f"blogger:{blog_id}" for blog_id in blog_ids]
    rows = (
        db.execute(
            select(ContentPlanSlot)
            .join(ContentPlanDay, ContentPlanSlot.plan_day_id == ContentPlanDay.id)
            .where(ContentPlanDay.channel_id.in_(channel_ids))
            .order_by(ContentPlanSlot.scheduled_for.asc().nullslast(), ContentPlanSlot.id.asc())
        )
        .scalars()
        .all()
    )
    return [slot for slot in rows if _slot_marker(slot) is not None]


def _setting_snapshot(db: Session) -> dict[str, str | None]:
    rows = db.execute(select(Setting).where(Setting.key.in_(AUTOMATION_SETTING_KEYS))).scalars().all()
    values = {key: None for key in AUTOMATION_SETTING_KEYS}
    for row in rows:
        values[str(row.key)] = str(row.value)
    return values


def _set_automation_state(db: Session, enabled: bool) -> dict[str, str]:
    value = "true" if enabled else "false"
    updates = {
        "automation_scheduler_enabled": value,
        "automation_publish_queue_enabled": value,
    }
    upsert_settings(db, updates)
    return updates


def _build_schedule(
    backlog: list[TravelSyncBacklogItem],
    *,
    days: int,
    interval_minutes: int,
    first_start_local: datetime,
    en_start: str,
    es_start: str,
    ja_start_fallback: str,
) -> tuple[list[TravelSyncBacklogItem], dict[str, Any]]:
    safe_days = max(int(days or 0), 1)
    gap = timedelta(minutes=max(int(interval_minutes or 0), 10))
    by_language = {language: [] for language in TRAVEL_LANGUAGES}
    for item in backlog:
        by_language[str(item.target_language)].append(item)

    quotas = {
        language: _largest_remainder(len(by_language[language]), safe_days)
        for language in TRAVEL_LANGUAGES
    }
    en_clock = _clock(en_start, "11:00")
    es_clock = _clock(es_start, "13:00")
    ja_clock = _clock(ja_start_fallback, "15:00")
    assigned: list[TravelSyncBacklogItem] = []
    daily_counts: dict[str, dict[str, int]] = {}
    first_date = first_start_local.date()

    for day_index in range(safe_days):
        day = first_date + timedelta(days=day_index)
        day_key = day.isoformat()
        daily_counts[day_key] = {}
        day_quota = {language: int(quotas[language][day_index] if day_index < len(quotas[language]) else 0) for language in TRAVEL_LANGUAGES}
        daily_counts[day_key] = dict(day_quota)

        if day_index == 0:
            cursor = first_start_local
            for language in TRAVEL_LANGUAGES:
                if day_quota[language] <= 0 or not by_language[language]:
                    continue
                item = by_language[language].pop(0)
                item.scheduled_for = cursor.astimezone(UTC)
                assigned.append(item)
                day_quota[language] -= 1
                cursor += gap
            for language in TRAVEL_LANGUAGES:
                for _idx in range(day_quota[language]):
                    if not by_language[language]:
                        break
                    item = by_language[language].pop(0)
                    item.scheduled_for = cursor.astimezone(UTC)
                    assigned.append(item)
                    cursor += gap
            continue

        en_base = datetime.combine(day, en_clock, tzinfo=TRAVEL_TIMEZONE)
        es_base = datetime.combine(day, es_clock, tzinfo=TRAVEL_TIMEZONE)
        ja_base = (es_base + gap * day_quota["es"]) if day_quota["es"] > 0 else datetime.combine(day, ja_clock, tzinfo=TRAVEL_TIMEZONE)
        for language, base in (("en", en_base), ("es", es_base), ("ja", ja_base)):
            for idx in range(day_quota[language]):
                if not by_language[language]:
                    break
                item = by_language[language].pop(0)
                item.scheduled_for = (base + gap * idx).astimezone(UTC)
                assigned.append(item)

    minute_bucket: dict[str, set[int]] = {}
    for item in assigned:
        if item.scheduled_for is None:
            continue
        minute_key = item.scheduled_for.astimezone(TRAVEL_TIMEZONE).strftime("%Y-%m-%d %H:%M")
        minute_bucket.setdefault(minute_key, set()).add(int(item.target_blog_id))

    summary = {
        "days": safe_days,
        "interval_minutes": int(gap.total_seconds() // 60),
        "first_start_kst": first_start_local.isoformat(timespec="minutes"),
        "daily_quota": quotas,
        "daily_counts": daily_counts,
        "assigned_count": len(assigned),
        "same_minute_overlap_count": sum(1 for blogs in minute_bucket.values() if len(blogs) > 1),
        "today": {
            "date": first_date.isoformat(),
            "allocation": {
                "en": daily_counts.get(first_date.isoformat(), {}).get("en", 0),
                "es": daily_counts.get(first_date.isoformat(), {}).get("es", 0),
                "ja": daily_counts.get(first_date.isoformat(), {}).get("ja", 0),
            },
        },
    }
    summary["today"]["allocation"]["total"] = sum(int(v) for v in summary["today"]["allocation"].values())
    return assigned, summary


def _update_job_schedule(job: Job, item: TravelSyncBacklogItem, *, interval_minutes: int, route: str) -> None:
    prompts = dict(job.raw_prompts or {})
    sync_payload = prompts.get(TRAVEL_SYNC_KEY) if isinstance(prompts.get(TRAVEL_SYNC_KEY), dict) else {}
    sync_payload = dict(sync_payload)
    sync_payload.update(
        {
            "group_key": str(item.group_key),
            "source_article_id": int(item.source_article_id),
            "source_blog_id": int(item.source_blog_id),
            "source_language": str(item.source_language),
            "target_blog_id": int(item.target_blog_id),
            "target_language": str(item.target_language),
            "source_hero_url": str(item.source_hero_url or "").strip(),
            "text_generation_route": route,
        }
    )
    prompts[TRAVEL_SYNC_KEY] = sync_payload

    schedule_payload = prompts.get(PIPELINE_SCHEDULE_KEY) if isinstance(prompts.get(PIPELINE_SCHEDULE_KEY), dict) else {}
    schedule_payload = dict(schedule_payload)
    schedule_payload["mode"] = "publish"
    schedule_payload["scheduled_for"] = item.scheduled_for.isoformat() if item.scheduled_for else None
    schedule_payload["interval_minutes"] = int(interval_minutes)
    schedule_payload.setdefault("slot_index", 0)
    schedule_payload.setdefault("topic_count", 1)
    prompts[PIPELINE_SCHEDULE_KEY] = schedule_payload

    planner_payload = prompts.get(PLANNER_BRIEF_KEY) if isinstance(prompts.get(PLANNER_BRIEF_KEY), dict) else {}
    planner_payload = dict(planner_payload)
    planner_payload["topic"] = str(item.source_title or "").strip()
    planner_payload["audience"] = default_target_audience_for_language(item.target_language)
    planner_payload["information_level"] = "practical"
    planner_payload["category_key"] = normalize_travel_category_key(item.category_key)
    planner_payload["category_name"] = normalize_travel_category_key(item.category_key).title()
    planner_payload["bundle_key"] = str(item.group_key)
    planner_payload["scheduled_for"] = item.scheduled_for.isoformat() if item.scheduled_for else None
    planner_payload["context_notes"] = (
        f"travel_cross_sync group={item.group_key}; source_article_id={item.source_article_id}; "
        f"source_language={item.source_language}; target_language={item.target_language}; "
        f"reuse_hero_url={item.source_hero_url or 'none'}"
    )
    prompts[PLANNER_BRIEF_KEY] = planner_payload
    job.raw_prompts = prompts


def _plan_day(db: Session, *, blog_id: int, scheduled_for: datetime) -> ContentPlanDay:
    local_date = scheduled_for.astimezone(TRAVEL_TIMEZONE).date()
    channel_id = f"blogger:{int(blog_id)}"
    plan_day = (
        db.execute(
            select(ContentPlanDay).where(
                ContentPlanDay.channel_id == channel_id,
                ContentPlanDay.plan_date == local_date,
            )
        )
        .scalars()
        .one_or_none()
    )
    if plan_day is not None:
        return plan_day
    plan_day = ContentPlanDay(
        channel_id=channel_id,
        blog_id=int(blog_id),
        plan_date=local_date,
        target_post_count=0,
        status="planned",
    )
    db.add(plan_day)
    db.flush()
    return plan_day


def _upsert_slot(
    db: Session,
    *,
    item: TravelSyncBacklogItem,
    job: Job,
    existing_slots_by_job: dict[int, ContentPlanSlot],
    existing_slots_by_key: dict[tuple[int, str], list[ContentPlanSlot]],
) -> tuple[ContentPlanSlot, str]:
    slot = existing_slots_by_job.get(int(job.id))
    action = "updated"
    if slot is None:
        queue = existing_slots_by_key.get(_item_key(item), [])
        while queue:
            candidate = queue.pop(0)
            if int(candidate.job_id or 0) in {0, int(job.id)}:
                slot = candidate
                break
    if slot is None:
        plan_day = _plan_day(db, blog_id=int(item.target_blog_id), scheduled_for=item.scheduled_for or datetime.now(UTC))
        slot = ContentPlanSlot(
            plan_day_id=int(plan_day.id),
            slot_order=1,
            status="brief_ready",
            result_payload={},
        )
        db.add(slot)
        db.flush()
        action = "created"
    else:
        plan_day = _plan_day(db, blog_id=int(item.target_blog_id), scheduled_for=item.scheduled_for or datetime.now(UTC))
        if int(slot.plan_day_id) != int(plan_day.id):
            slot.plan_day_id = int(plan_day.id)

    slot.category_key = normalize_travel_category_key(item.category_key)
    slot.category_name = normalize_travel_category_key(item.category_key).title()
    slot.scheduled_for = item.scheduled_for
    slot.job_id = int(job.id)
    slot.article_id = int(job.article.id) if job.article is not None and job.status == JobStatus.COMPLETED else None
    slot.brief_topic = str(item.source_title or "").strip()
    slot.brief_audience = default_target_audience_for_language(item.target_language)
    slot.brief_information_level = "practical"
    slot.brief_extra_context = (
        f"travel_cross_sync group={item.group_key}; source_article_id={item.source_article_id}; "
        f"source_language={item.source_language}; target_language={item.target_language}; "
        f"reuse_hero_url={item.source_hero_url or 'none'}"
    )
    slot.error_message = None
    slot.result_payload = {
        "travel_cross_sync": {
            "group_key": str(item.group_key),
            "source_article_id": int(item.source_article_id),
            "source_blog_id": int(item.source_blog_id),
            "source_language": str(item.source_language),
            "source_slug": str(item.source_slug),
            "target_blog_id": int(item.target_blog_id),
            "target_language": str(item.target_language),
            "source_hero_url": str(item.source_hero_url or "").strip(),
            "category_key": normalize_travel_category_key(item.category_key),
        }
    }
    if job.status == JobStatus.COMPLETED:
        slot.status = "generated"
    elif job.status in {JobStatus.PENDING, JobStatus.FAILED, JobStatus.STOPPED}:
        slot.status = "brief_ready"
    else:
        slot.status = "queued"
    db.add(slot)
    return slot, action


def _resequence_plan_days(db: Session, blog_ids: tuple[int, ...]) -> None:
    rows = (
        db.execute(
            select(ContentPlanDay).where(ContentPlanDay.blog_id.in_(list(blog_ids))).order_by(ContentPlanDay.plan_date.asc())
        )
        .scalars()
        .all()
    )
    for day in rows:
        slots = (
            db.execute(
                select(ContentPlanSlot)
                .where(ContentPlanSlot.plan_day_id == int(day.id))
                .order_by(ContentPlanSlot.scheduled_for.asc().nullslast(), ContentPlanSlot.id.asc())
            )
            .scalars()
            .all()
        )
        active_count = 0
        for index, slot in enumerate(slots, start=1):
            slot.slot_order = index
            if str(slot.status or "").lower() not in {"canceled"}:
                active_count += 1
            db.add(slot)
        day.target_post_count = active_count
        db.add(day)


def _serialize_job(job: Job) -> dict[str, Any]:
    key = _job_key(job)
    prompts = job.raw_prompts if isinstance(job.raw_prompts, dict) else {}
    sync = prompts.get(TRAVEL_SYNC_KEY) if isinstance(prompts.get(TRAVEL_SYNC_KEY), dict) else {}
    schedule = prompts.get(PIPELINE_SCHEDULE_KEY) if isinstance(prompts.get(PIPELINE_SCHEDULE_KEY), dict) else {}
    return {
        "job_id": int(job.id),
        "blog_id": int(job.blog_id),
        "key": list(key) if key else None,
        "status": _job_status(job),
        "group_key": str(sync.get("group_key") or ""),
        "source_article_id": int(sync.get("source_article_id") or 0),
        "target_language": str(sync.get("target_language") or ""),
        "scheduled_for": schedule.get("scheduled_for") if isinstance(schedule, dict) else None,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the Travel 3-blog sync safely from the latest backlog.")
    parser.add_argument("--blog-ids", default="34,36,37")
    parser.add_argument("--source-languages", default="en,es,ja")
    parser.add_argument("--target-languages", default="en,es,ja")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--interval-minutes", type=int, default=10)
    parser.add_argument("--start-delay-minutes", type=int, default=10)
    parser.add_argument("--slot-start-time-en", default="11:00")
    parser.add_argument("--slot-start-time-es", default="13:00")
    parser.add_argument("--slot-start-time-ja", default="15:00")
    parser.add_argument("--text-generation-route", default="codex_cli")
    parser.add_argument("--publish-mode", choices=("scheduled", "publish"), default="publish")
    parser.add_argument("--reset-stale-active-minutes", type=int, default=120)
    parser.add_argument("--report-root", default=str(DEFAULT_REPORT_ROOT))
    parser.add_argument("--report-prefix", default="travel-today-sync")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if str(args.publish_mode or "").strip().lower() == "scheduled":
        raise SystemExit("travel scheduled mode is disabled: travel success policy requires live-validated publish")
    blog_ids = _parse_blog_ids(args.blog_ids)
    source_languages = _parse_languages(args.source_languages)
    target_languages = _parse_languages(args.target_languages)
    route = normalize_travel_text_generation_route(args.text_generation_route)
    interval_minutes = max(int(args.interval_minutes), 10)
    report_root = Path(str(args.report_root)).resolve()
    report_prefix = str(args.report_prefix or "travel-today-sync").strip() or "travel-today-sync"
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    report_path = report_root / "reports" / f"{report_prefix}-{stamp}.json" if args.write_report else None

    with SessionLocal() as db:
        groups, backlog, summary = build_travel_sync_groups(
            db,
            blog_ids=blog_ids,
            source_languages=source_languages,
            target_languages=target_languages,
        )
        first_start_local = _next_local_start(int(args.start_delay_minutes))
        scheduled_backlog, schedule_summary = _build_schedule(
            backlog,
            days=max(int(args.days), 1),
            interval_minutes=interval_minutes,
            first_start_local=first_start_local,
            en_start=str(args.slot_start_time_en),
            es_start=str(args.slot_start_time_es),
            ja_start_fallback=str(args.slot_start_time_ja),
        )
        latest_keys = {_item_key(item) for item in scheduled_backlog}

        before_jobs = _load_travel_jobs(db, blog_ids)
        before_slots = _load_travel_slots(db, blog_ids)
        before_status_counts = Counter(_job_status(job) for job in before_jobs)
        before_pending_by_language = Counter(
            str((job.raw_prompts or {}).get(TRAVEL_SYNC_KEY, {}).get("target_language") or "")
            for job in before_jobs
            if job.status == JobStatus.PENDING
        )

        execute_payload: dict[str, Any] = {
            "route_updates": {},
            "apply_group_links": {"updated_article_count": 0},
            "enqueue_result": None,
            "stale_jobs_stopped": [],
            "stale_active_jobs_reset": [],
            "stale_slots_canceled": [],
            "duplicate_jobs_stopped": [],
            "slot_actions": Counter(),
            "updated_job_count": 0,
            "automation_freeze": False,
            "automation_resume": False,
        }

        if args.execute:
            frozen = False
            resumed = False
            try:
                _set_automation_state(db, False)
                db.commit()
                frozen = True
                execute_payload["automation_freeze"] = True

                route_updates = {travel_text_generation_route_setting_key(blog_id): route for blog_id in blog_ids}
                upsert_settings(db, route_updates)
                execute_payload["route_updates"] = route_updates
                execute_payload["apply_group_links"] = apply_travel_sync_group_links(db, groups=groups, commit=True)
                execute_payload["enqueue_result"] = enqueue_travel_cross_sync_jobs(
                    db,
                    backlog=scheduled_backlog,
                    text_generation_route=route,
                    publish_mode=str(args.publish_mode),
                    max_items_per_run=len(scheduled_backlog),
                    retry_failed_only=False,
                )
                db.commit()

                jobs = _load_travel_jobs(db, blog_ids)
                slots = _load_travel_slots(db, blog_ids)
                jobs_by_key: dict[tuple[int, str], list[Job]] = {}
                for job in jobs:
                    key = _job_key(job)
                    if key is None:
                        continue
                    jobs_by_key.setdefault(key, []).append(job)

                current_jobs_by_key: dict[tuple[int, str], Job] = {}
                for key, bucket in jobs_by_key.items():
                    bucket = sorted(bucket, key=lambda row: int(row.id))
                    if key not in latest_keys:
                        for job in bucket:
                            if job.status == JobStatus.PENDING:
                                job.status = JobStatus.STOPPED
                                job.end_time = datetime.now(UTC)
                                db.add(job)
                                execute_payload["stale_jobs_stopped"].append(_serialize_job(job))
                        continue

                    for job in bucket:
                        if _is_stale_active_job(job, threshold_minutes=int(args.reset_stale_active_minutes)):
                            errors = list(job.error_logs or [])
                            errors.append(
                                {
                                    "message": "reset stale active travel sync job before weekly schedule",
                                    "previous_status": _job_status(job),
                                    "reset_at": datetime.now(UTC).isoformat(),
                                }
                            )
                            job.error_logs = errors
                            job.status = JobStatus.PENDING
                            job.end_time = None
                            db.add(job)
                            execute_payload["stale_active_jobs_reset"].append(_serialize_job(job))

                    preferred = next((job for job in bucket if job.status == JobStatus.PENDING), None) or bucket[0]
                    current_jobs_by_key[key] = preferred
                    for duplicate in bucket:
                        if int(duplicate.id) == int(preferred.id):
                            continue
                        if duplicate.status == JobStatus.PENDING:
                            duplicate.status = JobStatus.STOPPED
                            duplicate.end_time = datetime.now(UTC)
                            db.add(duplicate)
                            execute_payload["duplicate_jobs_stopped"].append(_serialize_job(duplicate))

                slots_by_job = {int(slot.job_id): slot for slot in slots if int(slot.job_id or 0) > 0}
                slots_by_key: dict[tuple[int, str], list[ContentPlanSlot]] = {}
                for slot in slots:
                    key = _slot_key(slot)
                    if key is not None:
                        slots_by_key.setdefault(key, []).append(slot)
                        if key not in latest_keys and str(slot.status or "").lower() in {"planned", "brief_ready"}:
                            slot.status = "canceled"
                            slot.error_message = "stale travel sync slot excluded by latest backlog"
                            db.add(slot)
                            execute_payload["stale_slots_canceled"].append({"slot_id": int(slot.id), "key": list(key)})

                item_by_key = {_item_key(item): item for item in scheduled_backlog}
                for key, item in item_by_key.items():
                    job = current_jobs_by_key.get(key)
                    if job is None:
                        continue
                    if job.status in {JobStatus.PENDING, JobStatus.FAILED, JobStatus.STOPPED}:
                        _update_job_schedule(job, item, interval_minutes=interval_minutes, route=route)
                        if job.status in {JobStatus.FAILED, JobStatus.STOPPED}:
                            job.status = JobStatus.PENDING
                            job.end_time = None
                        db.add(job)
                        execute_payload["updated_job_count"] += 1
                    slot, action = _upsert_slot(
                        db,
                        item=item,
                        job=job,
                        existing_slots_by_job=slots_by_job,
                        existing_slots_by_key=slots_by_key,
                    )
                    slots_by_job[int(job.id)] = slot
                    execute_payload["slot_actions"][action] += 1

                _resequence_plan_days(db, blog_ids)
                _set_automation_state(db, True)
                db.commit()
                resumed = True
                execute_payload["automation_resume"] = True
            except Exception:
                db.rollback()
                if frozen and not resumed:
                    try:
                        _set_automation_state(db, True)
                        db.commit()
                        execute_payload["automation_resume"] = True
                    except Exception:  # noqa: BLE001
                        db.rollback()
                raise

        after_jobs = _load_travel_jobs(db, blog_ids)
        after_slots = _load_travel_slots(db, blog_ids)
        after_status_counts = Counter(_job_status(job) for job in after_jobs)
        after_pending_by_language = Counter(
            str((job.raw_prompts or {}).get(TRAVEL_SYNC_KEY, {}).get("target_language") or "")
            for job in after_jobs
            if job.status == JobStatus.PENDING
        )

        scheduled_items = [
            {
                "group_key": item.group_key,
                "source_article_id": item.source_article_id,
                "source_language": item.source_language,
                "source_title": item.source_title,
                "source_slug": item.source_slug,
                "source_hero_url": item.source_hero_url,
                "category_key": item.category_key,
                "target_language": item.target_language,
                "target_blog_id": item.target_blog_id,
                "scheduled_for": _iso(item.scheduled_for),
                "scheduled_for_kst": item.scheduled_for.astimezone(TRAVEL_TIMEZONE).isoformat(timespec="minutes") if item.scheduled_for else None,
            }
            for item in scheduled_backlog
        ]
        today_batch_count = int(schedule_summary.get("today", {}).get("allocation", {}).get("total") or 0)
        today_items = scheduled_items[:today_batch_count]
        canary = []
        seen_blogs: set[int] = set()
        for item in scheduled_items:
            blog_id = int(item["target_blog_id"])
            if blog_id in seen_blogs:
                continue
            canary.append(item)
            seen_blogs.add(blog_id)
            if len(seen_blogs) == len(blog_ids):
                break

        report = {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "mode": "execute" if args.execute else "dry-run",
            "blog_ids": list(blog_ids),
            "source_languages": list(source_languages),
            "target_languages": list(target_languages),
            "text_generation_route": route,
            "settings_before": _setting_snapshot(db),
            "summary": {
                **summary,
                "latest_backlog_count": len(scheduled_backlog),
                "before_travel_jobs": len(before_jobs),
                "before_travel_slots": len(before_slots),
                "after_travel_jobs": len(after_jobs),
                "after_travel_slots": len(after_slots),
                "before_status_counts": dict(before_status_counts),
                "after_status_counts": dict(after_status_counts),
                "before_pending_by_language": dict(before_pending_by_language),
                "after_pending_by_language": dict(after_pending_by_language),
            },
            "schedule": schedule_summary,
            "today_items": today_items,
            "canary_items": canary,
            "execute": {
                **execute_payload,
                "slot_actions": dict(execute_payload["slot_actions"]),
            },
            "reports_root": str(report_root),
        }
        if report_path is not None:
            _write_json(report_path, report)

    print(
        json.dumps(
            {
                "report_path": str(report_path) if report_path is not None else None,
                "mode": "execute" if args.execute else "dry-run",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
