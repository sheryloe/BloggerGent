from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
LOCAL_STORAGE_ROOT = REPO_ROOT / "storage"
REPORT_ROOT = LOCAL_STORAGE_ROOT / "reports"
TARGET_MONTH_DEFAULT = "2026-04"
TARGET_DATE_DEFAULT = "2026-04-10"
BELL_ISLAND_URL = "https://dongdonggri.blogspot.com/2026/03/the-legend-and-reality-of-bell-island.html"

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get(
        "BLOGGENT_DATABASE_URL",
        "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent",
    )
if "STORAGE_ROOT" not in os.environ:
    os.environ["STORAGE_ROOT"] = str(LOCAL_STORAGE_ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(API_ROOT))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import ManagedChannel, WorkflowStageType  # noqa: E402
from app.services.blogger.blogger_live_audit_service import fetch_and_audit_blogger_post  # noqa: E402
from app.services.blogger.blogger_sync_service import sync_connected_blogger_posts  # noqa: E402
from app.services.platform.blog_service import (  # noqa: E402
    ensure_all_blog_workflows,
    enforce_free_tier_model_policy,
    get_blog,
    sync_stage_prompts_from_profile_files,
)
from app.services.content.channel_prompt_service import sync_all_channel_prompt_backups  # noqa: E402
from app.services.cloudflare.cloudflare_channel_service import sync_cloudflare_prompts_from_files  # noqa: E402
from app.services.cloudflare.cloudflare_channel_service import generate_cloudflare_posts, list_cloudflare_categories, list_cloudflare_posts  # noqa: E402
from app.services.cloudflare.cloudflare_sync_service import sync_cloudflare_posts  # noqa: E402
from app.services.integrations.google_sheet_service import sync_google_sheet_snapshot  # noqa: E402
from app.services.ops.planner_service import create_month_plan, get_calendar  # noqa: E402
from app.services.platform.platform_service import ensure_managed_channels  # noqa: E402


@dataclass(slots=True)
class StepResult:
    step: str
    status: str
    detail: object


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply the 2026-04-10 Blogger/Cloudflare overhaul plan.")
    parser.add_argument("--month", default=TARGET_MONTH_DEFAULT, help="Target month in YYYY-MM format.")
    parser.add_argument("--target-date", default=TARGET_DATE_DEFAULT, help="Target day in YYYY-MM-DD format.")
    parser.add_argument("--overwrite-month-plan", action="store_true", help="Rebuild target month plans with overwrite.")
    parser.add_argument("--sync-sheet", action="store_true", help="Run Google Sheet sync after post sync.")
    parser.add_argument("--skip-prompt-sync", action="store_true", help="Skip Cloudflare/Blogger prompt sync.")
    parser.add_argument("--skip-post-sync", action="store_true", help="Skip Blogger/Cloudflare live sync.")
    parser.add_argument(
        "--cloudflare-canary-status",
        default="draft",
        choices=("draft", "published"),
        help="Status for the Cloudflare generation canary.",
    )
    parser.add_argument(
        "--cloudflare-canary-category",
        default="개발과-프로그래밍",
        help="Preferred category slug for the Cloudflare generation canary.",
    )
    parser.add_argument(
        "--skip-cloudflare-canary",
        action="store_true",
        help="Skip creating one Cloudflare canary post.",
    )
    parser.add_argument(
        "--skip-cloudflare-rewrite-canary",
        action="store_true",
        help="Skip the Cloudflare low-score rewrite canary.",
    )
    parser.add_argument(
        "--cloudflare-rewrite-apply",
        action="store_true",
        help="Apply the rewrite canary instead of dry-run.",
    )
    return parser.parse_args()


def _now_kst() -> datetime:
    return datetime.now(ZoneInfo("Asia/Seoul"))


def _jsonable(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "__dict__"):
        return {
            key: _jsonable(item)
            for key, item in value.__dict__.items()
            if not key.startswith("_")
        }
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _write_report(payload: dict[str, object]) -> Path:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = _now_kst().strftime("%Y%m%d-%H%M%S")
    path = REPORT_ROOT / f"apply-20260410-overhaul-{stamp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _sync_blogger_topic_prompts(db, channels: list[ManagedChannel]) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for channel in channels:
        if channel.provider != "blogger" or not channel.linked_blog_id:
            continue
        blog = get_blog(db, channel.linked_blog_id)
        if blog is None:
            results.append(
                {
                    "channel_id": channel.channel_id,
                    "blog_id": channel.linked_blog_id,
                    "status": "missing_blog",
                }
            )
            continue
        updates = sync_stage_prompts_from_profile_files(
            db,
            blog=blog,
            stage_types=(WorkflowStageType.TOPIC_DISCOVERY, WorkflowStageType.ARTICLE_GENERATION, WorkflowStageType.IMAGE_PROMPT_GENERATION),
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


def _load_enabled_channels(db) -> list[ManagedChannel]:
    ensure_managed_channels(db)
    return (
        db.execute(
            select(ManagedChannel)
            .where(ManagedChannel.is_enabled.is_(True))
            .where(ManagedChannel.provider.in_(("blogger", "cloudflare")))
            .order_by(ManagedChannel.provider.asc(), ManagedChannel.channel_id.asc())
        )
        .scalars()
        .all()
    )


def _extract_day_summary(calendar, target_date: str) -> dict[str, object]:
    for day in calendar.days:
        if day.plan_date != target_date:
            continue
        slots = sorted(day.slots, key=lambda item: (item.scheduled_for or "", item.id))
        return {
            "plan_date": day.plan_date,
            "slot_count": len(slots),
            "scheduled_times": [slot.scheduled_for for slot in slots],
            "statuses": [slot.status for slot in slots],
            "categories": [slot.category_name for slot in slots],
        }
    return {
        "plan_date": target_date,
        "slot_count": 0,
        "scheduled_times": [],
        "statuses": [],
        "categories": [],
    }


def _rebuild_and_summarize_month_plan(db, *, channel_id: str, month: str, overwrite: bool, target_date: str) -> dict[str, object]:
    create_month_plan(
        db,
        channel_id=channel_id,
        month=month,
        overwrite=overwrite,
    )
    calendar = get_calendar(db, channel_id=channel_id, month=month)
    return _extract_day_summary(calendar, target_date)


def _run_step(results: list[StepResult], step_name: str, fn) -> object:
    try:
        detail = fn()
    except Exception as exc:  # noqa: BLE001
        results.append(StepResult(step=step_name, status="failed", detail={"error": str(exc)}))
        return None
    results.append(StepResult(step=step_name, status="ok", detail=_jsonable(detail)))
    return detail


def _append_skipped_step(results: list[StepResult], step_name: str, reason: str) -> None:
    results.append(StepResult(step=step_name, status="ok", detail={"status": "skipped", "reason": reason}))


def _sync_workflows_and_policy(db) -> dict[str, object]:
    ensure_all_blog_workflows(db)
    return {
        "workflow_sync": "ok",
        "model_policy": enforce_free_tier_model_policy(db),
    }


def _select_cloudflare_canary_category(db, preferred_slug: str) -> str | None:
    preferred = str(preferred_slug or "").strip()
    categories = [item for item in list_cloudflare_categories(db) if bool(item.get("isLeaf"))]
    if preferred:
        for category in categories:
            slug = str(category.get("slug") or "").strip()
            if slug == preferred:
                return slug
    for category in categories:
        slug = str(category.get("slug") or "").strip()
        if slug:
            return slug
    return None


def _run_cloudflare_generation_canary(db, *, preferred_slug: str, status: str) -> dict[str, object]:
    category_slug = _select_cloudflare_canary_category(db, preferred_slug)
    if not category_slug:
        return {
            "status": "skipped",
            "reason": "no_leaf_categories",
        }
    result = generate_cloudflare_posts(
        db,
        per_category=1,
        category_slugs=[category_slug],
        status=status,
    )
    return {
        "status": "ok",
        "category_slug": category_slug,
        "publish_status": status,
        "result": result,
    }


def _pick_low_score_cloudflare_slug(db, threshold: int = 80) -> str | None:
    rows = list_cloudflare_posts(db)
    candidates: list[tuple[float, str]] = []
    for row in rows:
        slug = str(row.get("slug") or "").strip()
        if not slug:
            published_url = str(row.get("published_url") or "").strip()
            parsed = urlparse(published_url)
            path_parts = [segment for segment in (parsed.path or "").split("/") if segment]
            if len(path_parts) >= 3 and path_parts[0].lower() == "ko" and path_parts[1].lower() == "post":
                slug = unquote(path_parts[2]).strip()
            elif path_parts:
                slug = unquote(path_parts[-1]).strip()
        if not slug:
            continue
        scores = []
        missing_score = False
        for key in ("seo_score", "geo_score", "ctr", "lighthouse_score"):
            value = row.get(key)
            if value is None:
                missing_score = True
                continue
            try:
                scores.append(float(value))
            except (TypeError, ValueError):
                missing_score = True
                continue
        if missing_score:
            candidates.append((-1.0, slug))
            continue
        if not scores or min(scores) >= float(threshold):
            continue
        candidates.append((min(scores), slug))
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][1] if candidates else None


def _run_cloudflare_rewrite_canary(*, repo_root: Path, slug: str | None, apply: bool) -> dict[str, object]:
    if not slug:
        return {
            "status": "skipped",
            "reason": "no_low_score_slug",
        }
    command = [
        sys.executable,
        str(repo_root / "apps" / "api" / "scripts" / "rewrite_cloudflare_low_score_posts.py"),
        "--apply" if apply else "--dry-run",
        "--slug",
        slug,
        "--limit",
        "1",
        "--score-threshold",
        "80",
        "--min-body-chars",
        "3500",
        "--max-body-chars",
        "4000",
        "--require-threshold-pass",
    ]
    completed = subprocess.run(
        command,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    stdout_text = (completed.stdout or "").strip()
    payload: dict[str, object] = {
        "status": "ok" if completed.returncode == 0 else "failed",
        "mode": "apply" if apply else "dry-run",
        "slug": slug,
        "returncode": completed.returncode,
        "stdout": stdout_text,
        "stderr": (completed.stderr or "").strip(),
    }
    if stdout_text:
        last_line = stdout_text.splitlines()[-1].strip()
        try:
            payload["summary"] = json.loads(last_line)
        except json.JSONDecodeError:
            payload["summary"] = {"raw": last_line}
    return payload


def main() -> int:
    args = parse_args()
    target_date = date.fromisoformat(args.target_date)
    target_date_text = target_date.isoformat()
    step_results: list[StepResult] = []

    db = SessionLocal()
    try:
        channels = _load_enabled_channels(db)
        blogger_channels = [channel for channel in channels if channel.provider == "blogger"]
        cloudflare_channels = [channel for channel in channels if channel.provider == "cloudflare"]

        _run_step(
            step_results,
            "01_runtime_policy",
            lambda: _sync_workflows_and_policy(db),
        )

        if not args.skip_prompt_sync:
            _run_step(
                step_results,
                "02_prompt_sync",
                lambda: {
                    "cloudflare_prompt_sync": sync_cloudflare_prompts_from_files(db, execute=True),
                    "blogger_prompt_sync": _sync_blogger_topic_prompts(db, blogger_channels),
                    "channel_backup_sync": [
                        {
                            "channel_id": flow.channel_id,
                            "provider": flow.provider,
                            "backup_directory": flow.backup_directory,
                        }
                        for flow in sync_all_channel_prompt_backups(db, include_disconnected=True)
                    ],
                },
            )

        _run_step(
            step_results,
            "03_channel_baseline",
            lambda: {
                "blogger_channel_count": len(blogger_channels),
                "blogger_channel_ids": [channel.channel_id for channel in blogger_channels],
                "cloudflare_channel_count": len(cloudflare_channels),
                "cloudflare_channel_ids": [channel.channel_id for channel in cloudflare_channels],
            },
        )

        _run_step(
            step_results,
            "04_month_plan",
            lambda: {
                channel.channel_id: _rebuild_and_summarize_month_plan(
                    db,
                    channel_id=channel.channel_id,
                    month=args.month,
                    overwrite=bool(args.overwrite_month_plan),
                    target_date=target_date_text,
                )
                for channel in channels
            },
        )

        if not args.skip_post_sync:
            _run_step(
                step_results,
                "05_live_sync",
                lambda: {
                    "blogger": {"warnings": sync_connected_blogger_posts(db)},
                    "cloudflare": sync_cloudflare_posts(db),
                },
            )

        _run_step(
            step_results,
            "06_bell_island_canary",
            lambda: asdict(fetch_and_audit_blogger_post(BELL_ISLAND_URL, probe_images=False)),
        )

        if args.sync_sheet:
            _run_step(
                step_results,
                "07_google_sheet_sync",
                lambda: sync_google_sheet_snapshot(db, initial=False),
            )
        else:
            _append_skipped_step(step_results, "07_google_sheet_sync", "sync_sheet_disabled")

        if args.skip_cloudflare_canary:
            _append_skipped_step(step_results, "08_cloudflare_generation_canary", "skip_cloudflare_canary")
        else:
            _run_step(
                step_results,
                "08_cloudflare_generation_canary",
                lambda: _run_cloudflare_generation_canary(
                    db,
                    preferred_slug=args.cloudflare_canary_category,
                    status=args.cloudflare_canary_status,
                ),
            )

        if args.skip_cloudflare_rewrite_canary:
            _append_skipped_step(step_results, "09_cloudflare_rewrite_canary", "skip_cloudflare_rewrite_canary")
        else:
            low_score_slug = _pick_low_score_cloudflare_slug(db, threshold=80)
            _run_step(
                step_results,
                "09_cloudflare_rewrite_canary",
                lambda: _run_cloudflare_rewrite_canary(
                    repo_root=REPO_ROOT,
                    slug=low_score_slug,
                    apply=bool(args.cloudflare_rewrite_apply),
                ),
            )

        _run_step(
            step_results,
            "10_final_resync",
            lambda: {
                "cloudflare": sync_cloudflare_posts(db),
                "sheet_sync": sync_google_sheet_snapshot(db, initial=False) if args.sync_sheet else {"status": "skipped"},
            },
        )

        overall_status = "ok" if all(item.status == "ok" for item in step_results) else "warning"
        payload = {
            "status": overall_status,
            "executed_at": _now_kst().isoformat(),
            "month": args.month,
            "target_date": target_date_text,
            "overwrite_month_plan": bool(args.overwrite_month_plan),
            "sync_sheet": bool(args.sync_sheet),
            "steps": [_jsonable(asdict(item)) for item in step_results],
        }
        report_path = _write_report(payload)
        print(
            json.dumps(
                {
                    "status": overall_status,
                    "report_path": str(report_path),
                    "target_date": target_date_text,
                },
                ensure_ascii=False,
            )
        )
        return 0 if overall_status == "ok" else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
