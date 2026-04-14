from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT_PATH = SCRIPT_DIR.parent
if str(REPO_ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT_PATH))

from scripts.package_common import REPO_ROOT, STORAGE_ROOT, SessionLocal, now_iso, write_json

from app.models.entities import JobStatus
from app.services.cloudflare.cloudflare_channel_service import (
    _load_daily_counter,
    _select_weighted_daily_categories_from_counts,
    _serialize_daily_counter,
    generate_cloudflare_posts,
)
from app.services.ops.job_service import increment_attempt, load_job, record_failure
from app.services.integrations.settings_service import get_settings_map, upsert_settings
from app.tasks.pipeline import (
    DuplicateContentError,
    _upsert_blogger_post,
    execute_job_pipeline,
    discover_topics_and_enqueue,
    run_job,
)
from app.tasks.scheduler import EDITORIAL_CATEGORY_RULES, _pick_editorial_category


SEOUL = ZoneInfo("Asia/Seoul")
SCHEDULE_ROOT = STORAGE_ROOT / "scheduled-post-batches"
DEFAULT_BUFFER_MINUTES = 20


@dataclass(slots=True)
class BloggerSlot:
    channel: str
    blog_id: int
    blog_name: str
    category_key: str
    category_name: str
    category_guidance: str
    scheduled_for_local: str
    scheduled_for_utc: str
    status: str = "planned"
    job_id: int | None = None
    article_id: int | None = None
    article_title: str | None = None
    publish_status: str | None = None
    published_url: str | None = None
    error: str | None = None
    error_code: str | None = None
    error_cause: str | None = None
    retry_state: str | None = None
    manual_action_required: bool = False


@dataclass(slots=True)
class CloudflareSlot:
    channel: str
    category_key: str
    category_name: str
    category_weight: int
    scheduled_for_local: str
    scheduled_for_utc: str
    task_name: str | None = None
    slot_file: str | None = None
    result_file: str | None = None
    status: str = "planned"
    created_count: int | None = None
    public_url: str | None = None
    title: str | None = None
    error: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Queue 3 Travel + 3 Mystery + 4 Cloudflare posts with 2-hour spacing."
    )
    parser.add_argument("--execute", action="store_true", help="Execute Blogger generation and register Cloudflare one-off tasks.")
    parser.add_argument("--dry-run", action="store_true", help="Write plan only without queueing or task registration.")
    parser.add_argument("--travel-count", type=int, default=3)
    parser.add_argument("--mystery-count", type=int, default=3)
    parser.add_argument("--cloudflare-count", type=int, default=4)
    parser.add_argument("--interval-hours", type=int, default=2)
    parser.add_argument("--buffer-minutes", type=int, default=DEFAULT_BUFFER_MINUTES)
    parser.add_argument("--travel-start", type=str, default="")
    parser.add_argument("--mystery-start", type=str, default="")
    parser.add_argument("--cloudflare-start", type=str, default="")
    parser.add_argument("--run-cloudflare-slot", type=str, default="", help="Internal mode for a single scheduled Cloudflare slot.")
    return parser.parse_args()


def safe_slug(value: str) -> str:
    ascii_only = re.sub(r"[^0-9a-z]+", "-", str(value or "").casefold()).strip("-")
    if ascii_only:
        return ascii_only
    digest = hashlib.sha1(str(value or "item").encode("utf-8")).hexdigest()[:10]
    return f"item-{digest}"


def parse_local_dt(raw: str) -> datetime:
    text = str(raw or "").strip()
    if not text:
        raise ValueError("datetime text is empty")
    normalized = text.replace("Z", "+00:00")
    candidate = datetime.fromisoformat(normalized)
    if candidate.tzinfo is None:
        return candidate.replace(tzinfo=SEOUL)
    return candidate.astimezone(SEOUL)


def next_parity_hour(
    now_local: datetime,
    *,
    parity: int,
    minute: int,
    buffer_minutes: int,
) -> datetime:
    threshold = now_local + timedelta(minutes=buffer_minutes)
    candidate = threshold.replace(minute=minute, second=0, microsecond=0)
    if candidate < threshold:
        candidate += timedelta(hours=1)
    while candidate.hour % 2 != parity:
        candidate += timedelta(hours=1)
    return candidate


def next_minute_slot(now_local: datetime, *, minute: int, buffer_minutes: int) -> datetime:
    threshold = now_local + timedelta(minutes=buffer_minutes)
    candidate = threshold.replace(minute=minute, second=0, microsecond=0)
    if candidate < threshold:
        candidate += timedelta(hours=1)
    return candidate


def resolve_start_times(args: argparse.Namespace) -> dict[str, datetime]:
    now_local = datetime.now(SEOUL)
    travel_start = parse_local_dt(args.travel_start) if args.travel_start else next_parity_hour(
        now_local,
        parity=0,
        minute=0,
        buffer_minutes=args.buffer_minutes,
    )
    mystery_start = parse_local_dt(args.mystery_start) if args.mystery_start else next_parity_hour(
        now_local,
        parity=1,
        minute=0,
        buffer_minutes=args.buffer_minutes,
    )
    cloudflare_start = parse_local_dt(args.cloudflare_start) if args.cloudflare_start else next_minute_slot(
        now_local,
        minute=30,
        buffer_minutes=args.buffer_minutes,
    )
    return {
        "travel": travel_start,
        "mystery": mystery_start,
        "cloudflare": cloudflare_start,
    }


def build_blogger_slots(
    *,
    channel_key: str,
    blog_id: int,
    blog_name: str,
    count: int,
    start_local: datetime,
    interval_hours: int,
    settings_map: dict[str, str],
) -> list[BloggerSlot]:
    if count <= 0:
        return []
    rule_key = "korea_travel" if channel_key == "travel" else "world_mystery"
    local_settings = dict(settings_map)
    slots: list[BloggerSlot] = []
    for index in range(count):
        scheduled_local = start_local + timedelta(hours=interval_hours * index)
        selected, updates = _pick_editorial_category(
            profile_key=rule_key,
            settings_map=local_settings,
            today=scheduled_local.date().isoformat(),
        )
        if not selected:
            raise ValueError(f"editorial category not found for {rule_key}")
        local_settings.update(updates)
        slots.append(
            BloggerSlot(
                channel=channel_key,
                blog_id=blog_id,
                blog_name=blog_name,
                category_key=str(selected["key"]),
                category_name=str(selected["label"]),
                category_guidance=str(selected["guidance"]),
                scheduled_for_local=scheduled_local.isoformat(),
                scheduled_for_utc=scheduled_local.astimezone(timezone.utc).isoformat(),
            )
        )
    return slots


def build_cloudflare_slots(
    *,
    count: int,
    start_local: datetime,
    interval_hours: int,
    settings_map: dict[str, str],
    category_defs: list[dict[str, Any]],
) -> list[CloudflareSlot]:
    if count <= 0:
        return []
    keys = [str(item["key"]) for item in category_defs]
    weight_map = {str(item["key"]): int(item["weight"]) for item in category_defs}
    name_map = {str(item["key"]): str(item["name"]) for item in category_defs}
    today = start_local.date().isoformat()
    counts = _load_daily_counter(settings_map.get("cloudflare_daily_category_counts"), today=today, keys=keys)
    slots: list[CloudflareSlot] = []
    for index in range(count):
        plan, counts = _select_weighted_daily_categories_from_counts(category_slugs=keys, counts=counts, quota=1)
        if not plan:
            raise ValueError("cloudflare weighted category selection failed")
        category_key = next(iter(plan.keys()))
        scheduled_local = start_local + timedelta(hours=interval_hours * index)
        slots.append(
            CloudflareSlot(
                channel="cloudflare",
                category_key=category_key,
                category_name=name_map.get(category_key, category_key),
                category_weight=weight_map.get(category_key, 1),
                scheduled_for_local=scheduled_local.isoformat(),
                scheduled_for_utc=scheduled_local.astimezone(timezone.utc).isoformat(),
            )
        )
    return slots


def run_job_sync(job_id: int) -> dict[str, Any]:
    db = SessionLocal()
    try:
        job = load_job(db, job_id)
        if not job:
            raise ValueError(f"job not found: {job_id}")
        increment_attempt(db, job)
        execute_job_pipeline(db, job_id=job_id)
        final_job = load_job(db, job_id)
        if not final_job:
            raise ValueError(f"job not found after execution: {job_id}")
        article = final_job.article
        blogger_post = article.blogger_post if article else None
        return {
            "job_id": job_id,
            "job_status": final_job.status.value if hasattr(final_job.status, "value") else str(final_job.status),
            "article_id": article.id if article else None,
            "article_title": article.title if article else None,
            "publish_status": (
                blogger_post.post_status.value
                if blogger_post and hasattr(blogger_post.post_status, "value")
                else (str(blogger_post.post_status) if blogger_post else None)
            ),
            "published_url": blogger_post.published_url if blogger_post else None,
            "scheduled_for": blogger_post.scheduled_for.isoformat() if blogger_post and blogger_post.scheduled_for else None,
        }
    except DuplicateContentError as exc:
        db.rollback()
        job = load_job(db, job_id)
        if job:
            record_failure(db, job, exc)
        return {"job_id": job_id, "job_status": "failed", "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        job = load_job(db, job_id)
        if job:
            record_failure(db, job, exc)
        return {"job_id": job_id, "job_status": "failed", "error": str(exc)}
    finally:
        db.close()


def should_retry_topic_generation(error: str | None) -> bool:
    message = str(error or "")
    return "400 Bad Request" in message and "chat/completions" in message


def should_mark_retry_required(error: str | None) -> bool:
    message = str(error or "")
    return "Cloudflare R2 upload failed." in message or "Cloudflare integration asset upload failed." in message


def build_retry_required_result(*, job_id: int, error: str | None) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "job_status": "retry-required",
        "error": str(error or "").strip() or "Cloudflare R2 upload failed.",
        "error_code": "cloudflare_r2_upload_failed",
        "error_cause": "hero_image_upload",
        "retry_state": "retry-required",
        "manual_action_required": False,
    }


def queue_blogger_slot(slot: BloggerSlot) -> BloggerSlot:
    db = SessionLocal()
    try:
        with patch.object(run_job, "delay", return_value=None):
            discovery = discover_topics_and_enqueue(
                db,
                blog_id=slot.blog_id,
                topic_count=1,
                scheduled_start=slot.scheduled_for_utc,
                publish_interval_minutes=120,
                editorial_category_key=slot.category_key,
                editorial_category_label=slot.category_name,
                editorial_category_guidance=slot.category_guidance,
            )
        job_ids = list(discovery.get("job_ids") or [])
        if not job_ids:
            slot.status = "failed"
            slot.error = "no_job_created"
            return slot
        slot.job_id = int(job_ids[0])
    finally:
        db.close()

    result = run_job_sync(slot.job_id)
    if should_mark_retry_required(result.get("error")):
        result = build_retry_required_result(job_id=slot.job_id, error=result.get("error"))
    elif should_retry_topic_generation(result.get("error")):
        retry_db = SessionLocal()
        try:
            with patch.object(run_job, "delay", return_value=None):
                retry_discovery = discover_topics_and_enqueue(
                    retry_db,
                    blog_id=slot.blog_id,
                    topic_count=1,
                    scheduled_start=slot.scheduled_for_utc,
                    publish_interval_minutes=120,
                    editorial_category_key=slot.category_key,
                    editorial_category_label=slot.category_name,
                    editorial_category_guidance=slot.category_guidance,
                )
            retry_job_ids = list(retry_discovery.get("job_ids") or [])
            if retry_job_ids:
                slot.job_id = int(retry_job_ids[0])
                result = run_job_sync(slot.job_id)
                if should_mark_retry_required(result.get("error")):
                    result = build_retry_required_result(job_id=slot.job_id, error=result.get("error"))
        finally:
            retry_db.close()

    slot.status = str(result.get("job_status") or "failed")
    slot.article_id = result.get("article_id")
    slot.article_title = result.get("article_title")
    slot.publish_status = result.get("publish_status")
    slot.published_url = result.get("published_url")
    slot.error = result.get("error")
    slot.error_code = result.get("error_code")
    slot.error_cause = result.get("error_cause")
    slot.retry_state = result.get("retry_state")
    slot.manual_action_required = bool(result.get("manual_action_required"))
    return slot


def register_cloudflare_task(*, task_name: str, run_at_local: datetime, slot_file: Path) -> None:
    python_exe = Path(sys.executable).resolve()
    script_path = (REPO_ROOT / "scripts" / "schedule_channel_posts.py").resolve()
    repo_root = REPO_ROOT.resolve()
    cmd_arguments = (
        f'/c cd /d "{repo_root}" && '
        f'"{python_exe}" "{script_path}" --run-cloudflare-slot "{slot_file.resolve()}"'
    )
    ps_command = "\n".join(
        [
            f"$taskName = {ps_literal(task_name)}",
            f"$arguments = {ps_literal(cmd_arguments)}",
            "$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument $arguments",
            f"$trigger = New-ScheduledTaskTrigger -Once -At ([datetime]{ps_literal(run_at_local.strftime('%Y-%m-%dT%H:%M:%S'))})",
            "$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries",
            "Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue | Out-Null",
            "Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null",
        ]
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_command],
        check=True,
        cwd=str(REPO_ROOT),
    )


def ps_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def run_cloudflare_slot(slot_file: Path) -> dict[str, Any]:
    payload = json.loads(slot_file.read_text(encoding="utf-8"))
    slot_result_path = Path(payload["result_file"])
    db = SessionLocal()
    try:
        result = generate_cloudflare_posts(
            db,
            per_category=1,
            category_plan={str(payload["category_key"]): 1},
            status="published",
        )
        category_result = next(
            (
                item
                for item in result.get("categories", [])
                if str(item.get("category_slug") or item.get("category_id") or "") == str(payload["category_key"])
            ),
            None,
        )
        created_item = next(
            (
                item
                for item in (category_result or {}).get("items", [])
                if isinstance(item, dict) and str(item.get("status") or "") == "created"
            ),
            None,
        )
        created_count = int(result.get("created_count") or 0)
        status = "created" if created_count > 0 and created_item else "failed"
        error = None
        if status != "created":
            error = str((created_item or {}).get("error") or result.get("reason") or result.get("status") or "cloudflare_generation_failed")

        payload["status"] = status
        payload["created_count"] = created_count
        payload["executed_at"] = now_iso()
        payload["title"] = str((created_item or {}).get("title") or "")
        payload["public_url"] = str((created_item or {}).get("public_url") or "")
        payload["error"] = error
        write_json(slot_result_path, payload)

        if status == "created":
            settings_map = get_settings_map(db)
            today = datetime.now(SEOUL).date().isoformat()
            available_keys = [str(item.get("slug") or "").strip() for item in result.get("categories", []) if str(item.get("category_slug") or "").strip()]
            if not available_keys:
                available_keys = [str(payload["category_key"])]
            counts = _load_daily_counter(
                settings_map.get("cloudflare_daily_category_counts"),
                today=today,
                keys=available_keys,
            )
            counts[str(payload["category_key"])] = counts.get(str(payload["category_key"]), 0) + created_count
            upsert_settings(
                db,
                {"cloudflare_daily_category_counts": _serialize_daily_counter(today=today, counts=counts)},
            )
        return payload
    finally:
        db.close()


def build_batch_manifest(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    batch_id = datetime.now(SEOUL).strftime("%Y%m%d-%H%M%S")
    batch_root = SCHEDULE_ROOT / batch_id
    batch_root.mkdir(parents=True, exist_ok=True)

    start_times = resolve_start_times(args)
    db = SessionLocal()
    try:
        settings_map = get_settings_map(db)
        from app.services.ops.planner_service import _resolve_channel_context  # local import to avoid wider side effects
        from scripts.package_common import resolve_blog_by_profile_key

        travel_blog = resolve_blog_by_profile_key(db, "korea_travel")
        mystery_blog = resolve_blog_by_profile_key(db, "world_mystery")
        cloudflare_context = _resolve_channel_context(db, channel_id="cloudflare:dongriarchive")
        cloudflare_categories = [
            {"key": item.key, "name": item.name, "weight": item.weight}
            for item in cloudflare_context.categories
        ]
    finally:
        db.close()

    travel_slots = build_blogger_slots(
        channel_key="travel",
        blog_id=travel_blog.id,
        blog_name=travel_blog.name,
        count=args.travel_count,
        start_local=start_times["travel"],
        interval_hours=args.interval_hours,
        settings_map=settings_map,
    )
    mystery_slots = build_blogger_slots(
        channel_key="mystery",
        blog_id=mystery_blog.id,
        blog_name=mystery_blog.name,
        count=args.mystery_count,
        start_local=start_times["mystery"],
        interval_hours=args.interval_hours,
        settings_map=settings_map,
    )
    cloudflare_slots = build_cloudflare_slots(
        count=args.cloudflare_count,
        start_local=start_times["cloudflare"],
        interval_hours=args.interval_hours,
        settings_map=settings_map,
        category_defs=cloudflare_categories,
    )

    manifest = {
        "batch_id": batch_id,
        "created_at": now_iso(),
        "execute": bool(args.execute),
        "interval_hours": int(args.interval_hours),
        "travel": [asdict(item) for item in travel_slots],
        "mystery": [asdict(item) for item in mystery_slots],
        "cloudflare": [asdict(item) for item in cloudflare_slots],
    }
    manifest_path = batch_root / "schedule-manifest.json"
    write_json(manifest_path, manifest)
    return batch_root, manifest


def execute_batch(batch_root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    report = dict(manifest)
    report["executed_at"] = now_iso()

    travel_results: list[dict[str, Any]] = []
    for item in report["travel"]:
        slot = queue_blogger_slot(BloggerSlot(**item))
        travel_results.append(asdict(slot))
    report["travel"] = travel_results

    mystery_results: list[dict[str, Any]] = []
    for item in report["mystery"]:
        slot = queue_blogger_slot(BloggerSlot(**item))
        mystery_results.append(asdict(slot))
    report["mystery"] = mystery_results

    cloudflare_results: list[dict[str, Any]] = []
    for index, item in enumerate(report["cloudflare"], start=1):
        slot = CloudflareSlot(**item)
        run_at_local = parse_local_dt(slot.scheduled_for_local)
        slot_dir = batch_root / "cloudflare-slots"
        slot_dir.mkdir(parents=True, exist_ok=True)
        slot_file = slot_dir / f"{index:02d}-{safe_slug(slot.category_key)}.json"
        result_file = slot_dir / f"{index:02d}-{safe_slug(slot.category_key)}.result.json"
        task_name = f"Bloggent-Cloudflare-{run_at_local.strftime('%Y%m%d-%H%M')}-{index:02d}-{safe_slug(slot.category_key)}"
        slot.slot_file = str(slot_file.resolve())
        slot.result_file = str(result_file.resolve())
        slot.task_name = task_name
        write_json(slot_file, asdict(slot))
        try:
            register_cloudflare_task(task_name=task_name, run_at_local=run_at_local, slot_file=slot_file)
            slot.status = "scheduled"
        except subprocess.CalledProcessError as exc:
            slot.status = "failed"
            slot.error = str(exc)
        cloudflare_results.append(asdict(slot))
    report["cloudflare"] = cloudflare_results

    report_path = batch_root / "schedule-report.json"
    write_json(report_path, report)
    return report


def main() -> int:
    args = parse_args()
    if args.run_cloudflare_slot:
        result = run_cloudflare_slot(Path(args.run_cloudflare_slot))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if not args.execute and not args.dry_run:
        args.dry_run = True

    batch_root, manifest = build_batch_manifest(args)
    manifest_path = batch_root / "schedule-manifest.json"

    if args.dry_run:
        print(json.dumps({"status": "planned", "manifest": str(manifest_path.resolve()), "summary": manifest}, ensure_ascii=False, indent=2))
        return 0

    report = execute_batch(batch_root, manifest)
    print(json.dumps({"status": "executed", "report": str((batch_root / 'schedule-report.json').resolve()), "summary": report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
