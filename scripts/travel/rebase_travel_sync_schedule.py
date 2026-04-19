from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
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
TRAVEL_BLOG_IDS = (34, 36, 37)
TRAVEL_LANGUAGES = ("en", "es", "ja")
TARGET_BLOG_BY_LANGUAGE = {"en": 34, "es": 36, "ja": 37}
TRAVEL_TIMEZONE = ZoneInfo("Asia/Seoul")
AUTOMATION_SETTING_KEYS = (
    "automation_scheduler_enabled",
    "automation_publish_queue_enabled",
)


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
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get("BLOGGENT_DATABASE_URL", DEFAULT_DATABASE_URL)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import ContentPlanDay, ContentPlanSlot, Job, JobStatus, Setting  # noqa: E402
from app.services.integrations.settings_service import upsert_settings  # noqa: E402


@dataclass(slots=True)
class PendingTravelJob:
    job: Job
    slot: ContentPlanSlot | None
    source_article_id: int
    target_language: str
    target_blog_id: int
    group_key: str
    current_scheduled_for: datetime | None


@dataclass(slots=True)
class Assignment:
    job_id: int
    slot_id: int | None
    source_article_id: int
    target_language: str
    target_blog_id: int
    group_key: str
    old_scheduled_for: datetime | None
    new_scheduled_for: datetime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebase Travel sync pending jobs into a 7-day staggered schedule.")
    parser.add_argument("--start-date", default="2026-04-20", help="Schedule start date in YYYY-MM-DD (Asia/Seoul).")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--interval-minutes", type=int, default=10)
    parser.add_argument("--blog-ids", default="34,36,37")
    parser.add_argument("--en-start", default="11:00")
    parser.add_argument("--es-start", default="13:00")
    parser.add_argument("--ja-start-fallback", default="15:00")
    parser.add_argument("--report-root", default=str(DEFAULT_REPORT_ROOT))
    parser.add_argument("--report-prefix", default="travel-weekly-rebase")
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def _parse_blog_ids(raw: str | None) -> tuple[int, ...]:
    values: list[int] = []
    for token in [segment.strip() for segment in str(raw or "").split(",") if segment.strip()]:
        blog_id = int(token)
        if blog_id not in TRAVEL_BLOG_IDS:
            raise ValueError(f"Travel rebase allows only {TRAVEL_BLOG_IDS}; got {blog_id}")
        if blog_id not in values:
            values.append(blog_id)
    if not values:
        raise ValueError("--blog-ids resolved to empty set")
    return tuple(sorted(values))


def _parse_date(raw: str) -> date:
    return datetime.strptime(str(raw).strip(), "%Y-%m-%d").date()


def _parse_clock(raw: str, *, fallback: str) -> time:
    value = str(raw or "").strip() or fallback
    try:
        parsed = datetime.strptime(value, "%H:%M").time()
    except ValueError:
        parsed = datetime.strptime(fallback, "%H:%M").time()
    return parsed.replace(second=0, microsecond=0)


def _parse_dt(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(UTC).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _build_report_paths(report_root: Path, report_prefix: str) -> dict[str, Path]:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    reports_dir = report_root / "reports"
    return {
        "before": reports_dir / f"{report_prefix}-before-{stamp}.json",
        "plan": reports_dir / f"{report_prefix}-plan-{stamp}.json",
        "exec": reports_dir / f"{report_prefix}-exec-{stamp}.json",
        "after": reports_dir / f"{report_prefix}-after-{stamp}.json",
    }


def _largest_remainder(total: int, days: int) -> list[int]:
    safe_total = max(int(total or 0), 0)
    safe_days = max(int(days or 0), 1)
    base = safe_total // safe_days
    remainder = safe_total % safe_days
    return [base + (1 if index < remainder else 0) for index in range(safe_days)]


def _load_slot_by_job_id(db: Session, *, job_ids: list[int]) -> dict[int, ContentPlanSlot]:
    if not job_ids:
        return {}
    rows = (
        db.execute(select(ContentPlanSlot).where(ContentPlanSlot.job_id.in_(job_ids)).order_by(ContentPlanSlot.id.asc()))
        .scalars()
        .all()
    )
    slot_map: dict[int, ContentPlanSlot] = {}
    for slot in rows:
        key = int(slot.job_id or 0)
        if key <= 0 or key in slot_map:
            continue
        slot_map[key] = slot
    return slot_map


def _load_pending_travel_jobs(db: Session, *, blog_ids: tuple[int, ...]) -> list[PendingTravelJob]:
    jobs = (
        db.execute(
            select(Job)
            .where(
                Job.blog_id.in_(list(blog_ids)),
                Job.status == JobStatus.PENDING,
            )
            .order_by(Job.id.asc())
        )
        .scalars()
        .all()
    )
    slot_map = _load_slot_by_job_id(db, job_ids=[int(job.id) for job in jobs])
    items: list[PendingTravelJob] = []
    for job in jobs:
        prompts = job.raw_prompts if isinstance(job.raw_prompts, dict) else {}
        sync = prompts.get("travel_sync") if isinstance(prompts.get("travel_sync"), dict) else None
        if not isinstance(sync, dict):
            continue
        source_article_id = int(sync.get("source_article_id") or 0)
        target_language = str(sync.get("target_language") or "").strip().lower()
        target_blog_id = int(sync.get("target_blog_id") or TARGET_BLOG_BY_LANGUAGE.get(target_language, int(job.blog_id or 0)) or 0)
        group_key = str(sync.get("group_key") or "").strip()
        if source_article_id <= 0 or target_language not in TRAVEL_LANGUAGES or target_blog_id not in blog_ids or not group_key:
            continue
        schedule = prompts.get("pipeline_schedule") if isinstance(prompts.get("pipeline_schedule"), dict) else {}
        current_scheduled_for = _parse_dt(schedule.get("scheduled_for"))
        items.append(
            PendingTravelJob(
                job=job,
                slot=slot_map.get(int(job.id)),
                source_article_id=source_article_id,
                target_language=target_language,
                target_blog_id=target_blog_id,
                group_key=group_key,
                current_scheduled_for=current_scheduled_for,
            )
        )
    return items


def _count_due_travel_slots(db: Session, *, blog_ids: tuple[int, ...]) -> dict[str, int]:
    now_utc = datetime.now(UTC)
    channel_ids = {f"blogger:{blog_id}" for blog_id in blog_ids}
    rows = (
        db.execute(
            select(ContentPlanSlot, ContentPlanDay.channel_id)
            .join(ContentPlanDay, ContentPlanSlot.plan_day_id == ContentPlanDay.id)
            .where(ContentPlanDay.channel_id.in_(channel_ids))
            .where(ContentPlanSlot.status.in_(("planned", "brief_ready")))
            .where(ContentPlanSlot.scheduled_for.is_not(None))
            .where(ContentPlanSlot.scheduled_for <= now_utc)
            .order_by(ContentPlanSlot.id.asc())
        )
        .all()
    )
    result = {"total_due": 0}
    for slot, channel_id in rows:
        payload = slot.result_payload if isinstance(slot.result_payload, dict) else {}
        marker = payload.get("travel_cross_sync")
        if not isinstance(marker, dict):
            continue
        result["total_due"] += 1
        result[str(channel_id)] = int(result.get(str(channel_id), 0)) + 1
    return result


def _same_minute_overlap(jobs: list[PendingTravelJob]) -> dict[str, Any]:
    bucket: dict[str, set[int]] = {}
    es_ja_overlap = 0
    for item in jobs:
        if item.current_scheduled_for is None:
            continue
        minute_key = item.current_scheduled_for.astimezone(TRAVEL_TIMEZONE).strftime("%Y-%m-%d %H:%M")
        blogs = bucket.setdefault(minute_key, set())
        blogs.add(int(item.target_blog_id))
    multi_minute_keys = [key for key, blogs in bucket.items() if len(blogs) > 1]
    for key, blogs in bucket.items():
        if 36 in blogs and 37 in blogs:
            es_ja_overlap += 1
    return {
        "same_minute_overlap_count": len(multi_minute_keys),
        "es_ja_same_minute_overlap_count": es_ja_overlap,
        "same_minute_overlap_samples": multi_minute_keys[:20],
    }


def _build_daily_quotas(items: list[PendingTravelJob], *, days: int) -> dict[str, list[int]]:
    counts = {language: 0 for language in TRAVEL_LANGUAGES}
    for item in items:
        counts[item.target_language] += 1
    return {language: _largest_remainder(counts[language], days) for language in TRAVEL_LANGUAGES}


def _sorted_by_priority(items: list[PendingTravelJob]) -> list[PendingTravelJob]:
    return sorted(
        items,
        key=lambda row: (
            row.current_scheduled_for or datetime(1970, 1, 1, tzinfo=UTC),
            int(row.job.id),
        ),
    )


def _build_assignments(
    *,
    items: list[PendingTravelJob],
    start_date: date,
    days: int,
    interval_minutes: int,
    en_start_clock: time,
    es_start_clock: time,
    ja_start_fallback_clock: time,
) -> tuple[list[Assignment], dict[str, Any]]:
    by_lang = {language: [] for language in TRAVEL_LANGUAGES}
    for row in items:
        by_lang[row.target_language].append(row)
    for language in TRAVEL_LANGUAGES:
        by_lang[language] = _sorted_by_priority(by_lang[language])

    quotas = _build_daily_quotas(items, days=days)
    assignments: list[Assignment] = []
    daily_counts: dict[str, dict[str, int]] = {}

    for day_index in range(days):
        day = start_date + timedelta(days=day_index)
        day_key = day.isoformat()
        daily_counts[day_key] = {}
        en_quota = int(quotas["en"][day_index] if day_index < len(quotas["en"]) else 0)
        es_quota = int(quotas["es"][day_index] if day_index < len(quotas["es"]) else 0)
        ja_quota = int(quotas["ja"][day_index] if day_index < len(quotas["ja"]) else 0)
        daily_counts[day_key]["en"] = en_quota
        daily_counts[day_key]["es"] = es_quota
        daily_counts[day_key]["ja"] = ja_quota

        en_base = datetime.combine(day, en_start_clock, tzinfo=TRAVEL_TIMEZONE)
        es_base = datetime.combine(day, es_start_clock, tzinfo=TRAVEL_TIMEZONE)
        if es_quota > 0:
            ja_base = es_base + timedelta(minutes=interval_minutes * es_quota)
        else:
            ja_base = datetime.combine(day, ja_start_fallback_clock, tzinfo=TRAVEL_TIMEZONE)

        for idx in range(en_quota):
            if not by_lang["en"]:
                break
            row = by_lang["en"].pop(0)
            new_dt = (en_base + timedelta(minutes=interval_minutes * idx)).astimezone(UTC)
            assignments.append(
                Assignment(
                    job_id=int(row.job.id),
                    slot_id=int(row.slot.id) if row.slot is not None else None,
                    source_article_id=int(row.source_article_id),
                    target_language="en",
                    target_blog_id=int(row.target_blog_id),
                    group_key=row.group_key,
                    old_scheduled_for=row.current_scheduled_for,
                    new_scheduled_for=new_dt,
                )
            )

        for idx in range(es_quota):
            if not by_lang["es"]:
                break
            row = by_lang["es"].pop(0)
            new_dt = (es_base + timedelta(minutes=interval_minutes * idx)).astimezone(UTC)
            assignments.append(
                Assignment(
                    job_id=int(row.job.id),
                    slot_id=int(row.slot.id) if row.slot is not None else None,
                    source_article_id=int(row.source_article_id),
                    target_language="es",
                    target_blog_id=int(row.target_blog_id),
                    group_key=row.group_key,
                    old_scheduled_for=row.current_scheduled_for,
                    new_scheduled_for=new_dt,
                )
            )

        for idx in range(ja_quota):
            if not by_lang["ja"]:
                break
            row = by_lang["ja"].pop(0)
            new_dt = (ja_base + timedelta(minutes=interval_minutes * idx)).astimezone(UTC)
            assignments.append(
                Assignment(
                    job_id=int(row.job.id),
                    slot_id=int(row.slot.id) if row.slot is not None else None,
                    source_article_id=int(row.source_article_id),
                    target_language="ja",
                    target_blog_id=int(row.target_blog_id),
                    group_key=row.group_key,
                    old_scheduled_for=row.current_scheduled_for,
                    new_scheduled_for=new_dt,
                )
            )

    leftovers = {language: len(by_lang[language]) for language in TRAVEL_LANGUAGES}
    assignment_bucket: dict[str, set[int]] = {}
    for row in assignments:
        minute_key = row.new_scheduled_for.astimezone(TRAVEL_TIMEZONE).strftime("%Y-%m-%d %H:%M")
        assignment_bucket.setdefault(minute_key, set()).add(int(row.target_blog_id))
    overlap_count = sum(1 for blogs in assignment_bucket.values() if len(blogs) > 1)
    es_ja_overlap_count = sum(1 for blogs in assignment_bucket.values() if 36 in blogs and 37 in blogs)

    summary = {
        "quotas": quotas,
        "daily_counts": daily_counts,
        "total_assignments": len(assignments),
        "leftover_by_language": leftovers,
        "same_minute_overlap_count": overlap_count,
        "es_ja_same_minute_overlap_count": es_ja_overlap_count,
    }
    return assignments, summary


def _setting_snapshot(db: Session) -> dict[str, str | None]:
    rows = db.execute(select(Setting).where(Setting.key.in_(AUTOMATION_SETTING_KEYS))).scalars().all()
    values = {key: None for key in AUTOMATION_SETTING_KEYS}
    for row in rows:
        values[str(row.key)] = str(row.value)
    return values


def _set_automation_state(db: Session, *, enabled: bool) -> dict[str, str]:
    value = "true" if enabled else "false"
    updates = {
        "automation_scheduler_enabled": value,
        "automation_publish_queue_enabled": value,
    }
    upsert_settings(db, updates)
    return updates


def _apply_assignment(db: Session, *, assignments: list[Assignment], interval_minutes: int) -> dict[str, Any]:
    by_job_id = {
        int(row.id): row
        for row in db.execute(select(Job).where(Job.id.in_([entry.job_id for entry in assignments]))).scalars().all()
    }
    by_slot_id = {
        int(row.id): row
        for row in db.execute(
            select(ContentPlanSlot).where(ContentPlanSlot.id.in_([entry.slot_id for entry in assignments if entry.slot_id is not None]))
        )
        .scalars()
        .all()
    }

    travel_slot_rows = (
        db.execute(
            select(ContentPlanSlot, ContentPlanDay.channel_id)
            .join(ContentPlanDay, ContentPlanSlot.plan_day_id == ContentPlanDay.id)
            .where(ContentPlanDay.channel_id.in_((f"blogger:{TRAVEL_BLOG_IDS[0]}", f"blogger:{TRAVEL_BLOG_IDS[1]}", f"blogger:{TRAVEL_BLOG_IDS[2]}")))
            .where(ContentPlanSlot.status.in_(("planned", "brief_ready")))
            .order_by(ContentPlanSlot.scheduled_for.asc(), ContentPlanSlot.id.asc())
        )
        .all()
    )
    slots_by_signature: dict[tuple[int, str, str], list[ContentPlanSlot]] = {}
    for slot, _channel_id in travel_slot_rows:
        payload = slot.result_payload if isinstance(slot.result_payload, dict) else {}
        marker = payload.get("travel_cross_sync") if isinstance(payload.get("travel_cross_sync"), dict) else None
        if not isinstance(marker, dict):
            continue
        source_article_id = int(marker.get("source_article_id") or 0)
        group_key = str(marker.get("group_key") or "").strip()
        target_language = str(marker.get("target_language") or "").strip().lower()
        if source_article_id <= 0 or not group_key or target_language not in TRAVEL_LANGUAGES:
            continue
        signature = (source_article_id, group_key, target_language)
        slots_by_signature.setdefault(signature, []).append(slot)

    updated_jobs = 0
    updated_slots = 0
    for entry in assignments:
        job = by_job_id.get(int(entry.job_id))
        if job is None:
            continue
        prompts = dict(job.raw_prompts or {})
        schedule_payload = prompts.get("pipeline_schedule") if isinstance(prompts.get("pipeline_schedule"), dict) else {}
        schedule_payload = dict(schedule_payload)
        schedule_payload["mode"] = "publish"
        schedule_payload["scheduled_for"] = entry.new_scheduled_for.isoformat()
        schedule_payload["interval_minutes"] = int(interval_minutes)
        schedule_payload.setdefault("topic_count", 1)
        schedule_payload.setdefault("slot_index", 0)
        prompts["pipeline_schedule"] = schedule_payload

        planner_payload = prompts.get("planner_brief") if isinstance(prompts.get("planner_brief"), dict) else {}
        planner_payload = dict(planner_payload)
        planner_payload["scheduled_for"] = entry.new_scheduled_for.isoformat()
        prompts["planner_brief"] = planner_payload

        job.raw_prompts = prompts
        db.add(job)
        updated_jobs += 1

        slot: ContentPlanSlot | None = None
        if entry.slot_id is not None:
            slot = by_slot_id.get(int(entry.slot_id))
        if slot is None:
            signature = (int(entry.source_article_id), str(entry.group_key), str(entry.target_language))
            queue = slots_by_signature.get(signature, [])
            if queue:
                slot = queue.pop(0)
        if slot is not None:
            slot.scheduled_for = entry.new_scheduled_for
            if int(slot.job_id or 0) <= 0:
                slot.job_id = int(entry.job_id)
            db.add(slot)
            updated_slots += 1
    db.commit()
    return {
        "updated_jobs": updated_jobs,
        "updated_slots": updated_slots,
    }


def _serialize_assignments(assignments: list[Assignment]) -> list[dict[str, Any]]:
    return [
        {
            "job_id": row.job_id,
            "slot_id": row.slot_id,
            "source_article_id": row.source_article_id,
            "target_language": row.target_language,
            "target_blog_id": row.target_blog_id,
            "group_key": row.group_key,
            "old_scheduled_for": _iso(row.old_scheduled_for),
            "new_scheduled_for": _iso(row.new_scheduled_for),
            "new_scheduled_for_kst": row.new_scheduled_for.astimezone(TRAVEL_TIMEZONE).isoformat(timespec="minutes"),
        }
        for row in assignments
    ]


def main() -> int:
    args = parse_args()
    blog_ids = _parse_blog_ids(args.blog_ids)
    start_date = _parse_date(args.start_date)
    days = max(int(args.days), 1)
    interval_minutes = max(int(args.interval_minutes), 10)
    en_start_clock = _parse_clock(args.en_start, fallback="11:00")
    es_start_clock = _parse_clock(args.es_start, fallback="13:00")
    ja_fallback_clock = _parse_clock(args.ja_start_fallback, fallback="15:00")
    report_root = Path(str(args.report_root)).resolve()
    report_prefix = str(args.report_prefix or "travel-weekly-rebase").strip() or "travel-weekly-rebase"
    paths = _build_report_paths(report_root, report_prefix)

    with SessionLocal() as db:
        pending_items = _load_pending_travel_jobs(db, blog_ids=blog_ids)
        before_payload = {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "mode": "execute" if args.execute else "dry-run",
            "blog_ids": list(blog_ids),
            "start_date": start_date.isoformat(),
            "days": days,
            "interval_minutes": interval_minutes,
            "settings_snapshot": _setting_snapshot(db),
            "pending_travel_sync_jobs": len(pending_items),
            "pending_by_language": {
                language: sum(1 for row in pending_items if row.target_language == language)
                for language in TRAVEL_LANGUAGES
            },
            "due_travel_slots": _count_due_travel_slots(db, blog_ids=blog_ids),
            "schedule_overlap_before": _same_minute_overlap(pending_items),
        }
        _write_json(paths["before"], before_payload)

        assignments, plan_summary = _build_assignments(
            items=pending_items,
            start_date=start_date,
            days=days,
            interval_minutes=interval_minutes,
            en_start_clock=en_start_clock,
            es_start_clock=es_start_clock,
            ja_start_fallback_clock=ja_fallback_clock,
        )

        documented_today = {
            "date": datetime.now(TRAVEL_TIMEZONE).date().isoformat(),
            "allocation": {
                "en": int(plan_summary["quotas"]["en"][0]) if plan_summary["quotas"]["en"] else 0,
                "es": int(plan_summary["quotas"]["es"][0]) if plan_summary["quotas"]["es"] else 0,
                "ja": int(plan_summary["quotas"]["ja"][0]) if plan_summary["quotas"]["ja"] else 0,
            },
            "execution_policy": f"defer_execution_to_start_date={start_date.isoformat()}",
        }
        documented_today["allocation"]["total"] = (
            documented_today["allocation"]["en"]
            + documented_today["allocation"]["es"]
            + documented_today["allocation"]["ja"]
        )

        plan_payload = {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "mode": "execute" if args.execute else "dry-run",
            "summary": plan_summary,
            "documented_today": documented_today,
            "assignments": _serialize_assignments(assignments),
        }
        _write_json(paths["plan"], plan_payload)

        exec_payload: dict[str, Any] = {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "mode": "dry-run",
            "freeze_applied": False,
            "resume_applied": False,
            "apply_result": {"updated_jobs": 0, "updated_slots": 0},
        }

        if args.execute:
            frozen = False
            resumed = False
            try:
                _set_automation_state(db, enabled=False)
                db.commit()
                frozen = True

                apply_result = _apply_assignment(db, assignments=assignments, interval_minutes=interval_minutes)
                _set_automation_state(db, enabled=True)
                db.commit()
                resumed = True

                exec_payload = {
                    "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "mode": "execute",
                    "freeze_applied": frozen,
                    "resume_applied": resumed,
                    "apply_result": apply_result,
                    "assignments_applied": len(assignments),
                }
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                if frozen and not resumed:
                    try:
                        _set_automation_state(db, enabled=True)
                        db.commit()
                        resumed = True
                    except Exception:  # noqa: BLE001
                        db.rollback()
                exec_payload = {
                    "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "mode": "execute",
                    "freeze_applied": frozen,
                    "resume_applied": resumed,
                    "error": str(exc),
                }
                _write_json(paths["exec"], exec_payload)
                raise

        _write_json(paths["exec"], exec_payload)

        after_items = _load_pending_travel_jobs(db, blog_ids=blog_ids)
        after_payload = {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "mode": "execute" if args.execute else "dry-run",
            "settings_snapshot": _setting_snapshot(db),
            "pending_travel_sync_jobs": len(after_items),
            "pending_by_language": {
                language: sum(1 for row in after_items if row.target_language == language)
                for language in TRAVEL_LANGUAGES
            },
            "due_travel_slots": _count_due_travel_slots(db, blog_ids=blog_ids),
            "schedule_overlap_after": _same_minute_overlap(after_items),
        }
        _write_json(paths["after"], after_payload)

    output = {
        "before_report_path": str(paths["before"]),
        "plan_report_path": str(paths["plan"]),
        "exec_report_path": str(paths["exec"]),
        "after_report_path": str(paths["after"]),
        "mode": "execute" if args.execute else "dry-run",
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
