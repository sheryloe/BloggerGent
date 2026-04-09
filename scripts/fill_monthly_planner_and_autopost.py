from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import and_

from app.db.session import SessionLocal
from app.models.entities import Blog, ContentPlanDay, ContentPlanSlot, ManagedChannel, WorkflowStageType
from app.services.blog_service import ensure_all_blog_workflows, enforce_free_tier_model_policy, get_blog, sync_stage_prompts_from_profile_files
from app.services.cloudflare_channel_service import sync_cloudflare_prompts_from_files
from app.services.openai_usage_service import FREE_TIER_DEFAULT_SMALL_TEXT_MODEL
from app.services.planner_service import analyze_day_briefs, apply_day_briefs, create_month_plan, get_calendar
from app.services.settings_service import upsert_settings


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO_ROOT / "storage" / "reports"
STALE_CANCEL_REASON = "auto_skipped_past_due_by_planner_sync"


@dataclass(slots=True)
class ChannelRunResult:
    channel_id: str
    provider: str
    linked_blog_id: int | None
    synced_topic_prompt: bool = False
    canceled_stale_slots: int = 0
    analyzed_days: int = 0
    applied_slots: int = 0
    skipped_slots: int = 0
    failed_days: int = 0
    failed_day_details: list[dict[str, str]] | None = None


def parse_args() -> argparse.Namespace:
    timezone = ZoneInfo("Asia/Seoul")
    now_local = datetime.now(timezone)
    parser = argparse.ArgumentParser(description="Fill the monthly planner with Korean briefs and enable 11:00 / 5-minute autopost defaults.")
    parser.add_argument("--month", default=now_local.strftime("%Y-%m"), help="Target month in YYYY-MM format.")
    parser.add_argument("--timezone", default="Asia/Seoul", help="Planner timezone.")
    parser.add_argument("--start-time", default="11:00", help="First publish time in HH:MM.")
    parser.add_argument("--slot-interval-minutes", type=int, default=5, help="Minutes between planner slots.")
    parser.add_argument("--publish-min-interval-seconds", type=int, default=300, help="Minimum publish queue spacing in seconds.")
    parser.add_argument(
        "--channels",
        nargs="*",
        default=[],
        help="Optional explicit channel IDs. Defaults to all enabled Blogger/Cloudflare channels.",
    )
    parser.add_argument(
        "--skip-cancel-stale",
        action="store_true",
        help="Do not cancel past-due planned/brief_ready slots before the effective start date.",
    )
    return parser.parse_args()


def parse_month_bounds(month: str) -> tuple[date, date]:
    start = datetime.strptime(f"{month}-01", "%Y-%m-%d").date()
    if start.month == 12:
        end = date(start.year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(start.year, start.month + 1, 1) - timedelta(days=1)
    return start, end


def parse_clock(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time().replace(second=0, microsecond=0)


def effective_start_date(*, now_local: datetime, month_start: date, month_end: date, first_slot_time: time) -> date:
    if month_start > now_local.date():
        return month_start
    if month_end < now_local.date():
        return month_start
    first_slot_today = datetime.combine(now_local.date(), first_slot_time, tzinfo=now_local.tzinfo)
    start = now_local.date() if now_local < first_slot_today else now_local.date() + timedelta(days=1)
    if start < month_start:
        return month_start
    if start > month_end:
        return month_end
    return start


def load_target_channels(db, requested_channel_ids: list[str]) -> list[ManagedChannel]:
    query = (
        db.query(ManagedChannel)
        .filter(ManagedChannel.is_enabled.is_(True))
        .filter(ManagedChannel.provider.in_(("blogger", "cloudflare")))
        .order_by(ManagedChannel.provider.asc(), ManagedChannel.channel_id.asc())
    )
    channels = query.all()
    if requested_channel_ids:
        requested = {item.strip() for item in requested_channel_ids if item.strip()}
        channels = [channel for channel in channels if channel.channel_id in requested]
    return channels


def ensure_runtime_defaults(db, *, timezone_name: str, start_time: str, slot_interval_minutes: int, publish_min_interval_seconds: int) -> dict[str, str]:
    updates = {
        "schedule_enabled": "true",
        "schedule_timezone": timezone_name,
        "planner_publish_start_time": start_time,
        "planner_slot_interval_minutes": str(max(1, slot_interval_minutes)),
        "planner_brief_model": FREE_TIER_DEFAULT_SMALL_TEXT_MODEL,
        "publish_min_interval_seconds": str(max(300, publish_min_interval_seconds)),
        "automation_master_enabled": "true",
        "automation_scheduler_enabled": "true",
        "automation_publish_queue_enabled": "true",
    }
    upsert_settings(db, updates)
    return updates


def sync_blogger_topic_prompts(db, channels: list[ManagedChannel]) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for channel in channels:
        if channel.provider != "blogger" or not channel.linked_blog_id:
            continue
        blog = get_blog(db, channel.linked_blog_id)
        if blog is None:
            results.append({"channel_id": channel.channel_id, "blog_id": channel.linked_blog_id, "status": "missing_blog"})
            continue
        updates = sync_stage_prompts_from_profile_files(
            db,
            blog=blog,
            stage_types=(WorkflowStageType.TOPIC_DISCOVERY,),
        )
        results.append(
            {
                "channel_id": channel.channel_id,
                "blog_id": blog.id,
                "status": "synced" if updates else "unchanged",
                "updated": len(updates),
            }
        )
    return results


def cancel_stale_slots(
    db,
    *,
    channel_id: str,
    month_start: date,
    start_date: date,
) -> int:
    stale_slots = (
        db.query(ContentPlanSlot)
        .join(ContentPlanDay, ContentPlanSlot.plan_day_id == ContentPlanDay.id)
        .filter(ContentPlanDay.channel_id == channel_id)
        .filter(ContentPlanDay.plan_date >= month_start)
        .filter(ContentPlanDay.plan_date < start_date)
        .filter(ContentPlanSlot.status.in_(("planned", "brief_ready")))
        .order_by(ContentPlanDay.plan_date.asc(), ContentPlanSlot.scheduled_for.asc(), ContentPlanSlot.id.asc())
        .all()
    )
    for slot in stale_slots:
        slot.status = "canceled"
        slot.error_message = STALE_CANCEL_REASON
        db.add(slot)
    if stale_slots:
        db.commit()
    return len(stale_slots)


def day_needs_brief_fill(day) -> bool:
    if not getattr(day, "slots", None):
        return False
    for slot in day.slots:
        if not str(slot.brief_topic or "").strip():
            return True
        if not str(slot.brief_audience or "").strip():
            return True
        if not str(slot.brief_information_level or "").strip():
            return True
        if not str(slot.brief_extra_context or "").strip():
            return True
    return False


def fill_channel_days(
    db,
    *,
    channel_id: str,
    month: str,
    fill_start_date: date,
) -> ChannelRunResult:
    managed_channel = db.query(ManagedChannel).filter(ManagedChannel.channel_id == channel_id).one()
    result = ChannelRunResult(
        channel_id=managed_channel.channel_id,
        provider=str(managed_channel.provider),
        linked_blog_id=managed_channel.linked_blog_id,
        failed_day_details=[],
    )

    create_month_plan(db, channel_id=channel_id, month=month, overwrite=False)
    calendar = get_calendar(db, channel_id=channel_id, month=month)
    fill_start_key = fill_start_date.isoformat()

    for day in calendar.days:
        if day.plan_date < fill_start_key:
            continue
        if not day_needs_brief_fill(day):
            continue
        try:
            analysis = analyze_day_briefs(db, plan_day_id=day.id)
            applied = apply_day_briefs(db, plan_day_id=day.id, run_id=analysis.run.id)
            result.analyzed_days += 1
            result.applied_slots += len(applied.applied_slot_ids)
            result.skipped_slots += len(applied.skipped_slot_ids)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            result.failed_days += 1
            result.failed_day_details.append({"plan_date": day.plan_date, "error": str(exc)})

    return result


def build_report_path(now_local: datetime) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    return REPORT_DIR / f"planner-autopost-sync-{now_local.strftime('%Y%m%d-%H%M%S')}.json"


def main() -> int:
    args = parse_args()
    timezone = ZoneInfo(args.timezone)
    now_local = datetime.now(timezone)
    month_start, month_end = parse_month_bounds(args.month)
    first_slot_time = parse_clock(args.start_time)
    start_date = effective_start_date(
        now_local=now_local,
        month_start=month_start,
        month_end=month_end,
        first_slot_time=first_slot_time,
    )

    db = SessionLocal()
    try:
        ensure_all_blog_workflows(db)
        enforce_free_tier_model_policy(db)

        settings_updates = ensure_runtime_defaults(
            db,
            timezone_name=args.timezone,
            start_time=args.start_time,
            slot_interval_minutes=args.slot_interval_minutes,
            publish_min_interval_seconds=args.publish_min_interval_seconds,
        )
        channels = load_target_channels(db, args.channels)
        cloudflare_prompt_sync = sync_cloudflare_prompts_from_files(db, execute=True)
        blogger_prompt_sync = sync_blogger_topic_prompts(db, channels)

        channel_results: list[ChannelRunResult] = []
        for channel in channels:
            channel_result = fill_channel_days(
                db,
                channel_id=channel.channel_id,
                month=args.month,
                fill_start_date=start_date,
            )
            channel_result.synced_topic_prompt = any(
                item.get("channel_id") == channel.channel_id and item.get("status") in {"synced", "unchanged"}
                for item in blogger_prompt_sync
            )
            if not args.skip_cancel_stale:
                channel_result.canceled_stale_slots = cancel_stale_slots(
                    db,
                    channel_id=channel.channel_id,
                    month_start=month_start,
                    start_date=start_date,
                )
            channel_results.append(channel_result)

        report = {
            "status": "ok",
            "executed_at": now_local.isoformat(),
            "month": args.month,
            "timezone": args.timezone,
            "planner_start_time": args.start_time,
            "planner_slot_interval_minutes": args.slot_interval_minutes,
            "publish_min_interval_seconds": max(300, args.publish_min_interval_seconds),
            "brief_model": FREE_TIER_DEFAULT_SMALL_TEXT_MODEL,
            "effective_fill_start_date": start_date.isoformat(),
            "settings_updates": settings_updates,
            "cloudflare_prompt_sync": cloudflare_prompt_sync,
            "blogger_topic_prompt_sync": blogger_prompt_sync,
            "channels": [asdict(item) for item in channel_results],
        }

        report_path = build_report_path(now_local)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "ok", "report_path": str(report_path), "effective_fill_start_date": start_date.isoformat()}, ensure_ascii=False))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
