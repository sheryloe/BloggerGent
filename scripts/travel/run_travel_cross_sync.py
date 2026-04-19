from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
RUNTIME_ENV_PATH = REPO_ROOT / "env" / "runtime.settings.env"
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"
DEFAULT_REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\travel")


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
from app.services.content.travel_blog_policy import (  # noqa: E402
    normalize_travel_text_generation_route,
    travel_text_generation_route_setting_key,
)
from app.services.content.travel_cross_sync_service import (  # noqa: E402
    TRAVEL_SUPPORTED_LANGUAGES,
    apply_travel_sync_group_links,
    assign_backlog_schedule_slots,
    build_travel_sync_groups,
    seed_travel_weekly_planner_slots,
    enqueue_travel_cross_sync_jobs,
)
from app.services.content.travel_translation_state_service import refresh_travel_translation_state  # noqa: E402
from app.services.integrations.settings_service import upsert_settings  # noqa: E402


def _parse_blog_ids(raw: str | None) -> tuple[int, ...]:
    allowed = {34, 36, 37}
    values: list[int] = []
    for token in [segment.strip() for segment in str(raw or "").split(",") if segment.strip()]:
        blog_id = int(token)
        if blog_id not in allowed:
            raise ValueError(f"--blog-ids allows only {sorted(allowed)}; got {blog_id}")
        if blog_id not in values:
            values.append(blog_id)
    if not values:
        raise ValueError("--blog-ids resolved to empty set")
    return tuple(sorted(values))


def _parse_languages(raw: str | None) -> tuple[str, ...]:
    normalized: list[str] = []
    allowed = set(TRAVEL_SUPPORTED_LANGUAGES)
    for token in [segment.strip().lower() for segment in str(raw or "").split(",") if segment.strip()]:
        if token not in allowed:
            raise ValueError(f"unsupported language '{token}', allowed={sorted(allowed)}")
        if token not in normalized:
            normalized.append(token)
    if not normalized:
        raise ValueError("language list resolved to empty set")
    return tuple(normalized)


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Travel EN/ES/JA cross-sync planner and execution runner.")
    parser.add_argument("--blog-ids", default="34,36,37")
    parser.add_argument("--source-languages", default="en,es,ja")
    parser.add_argument("--target-languages", default="en,es,ja")
    parser.add_argument("--publish-mode", choices=("scheduled", "draft", "publish"), default="scheduled")
    parser.add_argument("--min-schedule-gap-minutes", type=int, default=10)
    parser.add_argument("--max-items-per-run", type=int, default=500)
    parser.add_argument("--retry-failed-only", action="store_true")
    parser.add_argument("--text-generation-route", default="codex_cli")
    parser.add_argument("--schedule-days", type=int, default=7)
    parser.add_argument("--seed-planner-slots", action="store_true")
    parser.add_argument("--slot-seed-mode", choices=("append", "replace"), default="append")
    parser.add_argument("--slot-start-time-en", default="11:00")
    parser.add_argument("--slot-start-time-es", default="13:00")
    parser.add_argument("--slot-start-time-ja", default="15:00")
    parser.add_argument("--slot-gap-minutes", type=int, default=10)
    parser.add_argument("--report-root", default=str(DEFAULT_REPORT_ROOT))
    parser.add_argument("--report-prefix", default="travel-cross-sync")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--dispatch-jobs", action="store_true")
    parser.add_argument("--no-refresh-state", action="store_true")
    return parser.parse_args()


def _report_paths(report_root: Path, report_prefix: str) -> tuple[Path, Path, Path]:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    reports_dir = report_root / "reports"
    manifest_path = reports_dir / f"{report_prefix}-travel-sync-group-manifest-{stamp}.json"
    backlog_path = reports_dir / f"{report_prefix}-travel-sync-backlog-plan-{stamp}.json"
    execute_path = reports_dir / f"{report_prefix}-travel-sync-execute-{stamp}.json"
    return manifest_path, backlog_path, execute_path


def main() -> int:
    args = parse_args()
    blog_ids = _parse_blog_ids(args.blog_ids)
    source_languages = _parse_languages(args.source_languages)
    target_languages = _parse_languages(args.target_languages)
    route = normalize_travel_text_generation_route(args.text_generation_route)
    report_root = Path(str(args.report_root)).resolve()
    manifest_path, backlog_path, execute_path = _report_paths(report_root, str(args.report_prefix).strip() or "travel-cross-sync")

    with SessionLocal() as db:
        groups, backlog, summary = build_travel_sync_groups(
            db,
            blog_ids=blog_ids,
            source_languages=source_languages,
            target_languages=target_languages,
        )
        manifest_payload = {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "mode": "execute" if args.execute else "dry-run",
            "blog_ids": list(blog_ids),
            "source_languages": list(source_languages),
            "target_languages": list(target_languages),
            "summary": summary,
            "groups": [
                {
                    "group_key": group.group_key,
                    "source_article_id": group.source_article_id,
                    "source_blog_id": group.source_blog_id,
                    "source_language": group.source_language,
                    "member_article_ids": list(group.member_article_ids),
                    "members_by_language": dict(group.members_by_language),
                    "missing_languages": list(group.missing_languages),
                    "category_key": group.category_key,
                    "hero_url": group.hero_url,
                }
                for group in groups
            ],
        }
        _write_report(manifest_path, manifest_payload)

        planner_slot_seed_summary: dict[str, Any] = {"enabled": False}
        if bool(args.seed_planner_slots):
            scheduled_backlog, planner_slot_seed_summary = seed_travel_weekly_planner_slots(
                db,
                backlog=backlog,
                days=max(int(args.schedule_days), 1),
                slot_seed_mode=str(args.slot_seed_mode or "append"),
                slot_gap_minutes=max(int(args.slot_gap_minutes), 1),
                slot_start_times_by_language={
                    "en": str(args.slot_start_time_en or "").strip(),
                    "es": str(args.slot_start_time_es or "").strip(),
                    "ja": str(args.slot_start_time_ja or "").strip(),
                },
                commit=bool(args.execute),
            )
        else:
            scheduled_backlog = assign_backlog_schedule_slots(
                db,
                backlog=backlog,
                min_schedule_gap_minutes=max(int(args.min_schedule_gap_minutes), 1),
            )

        backlog_payload = {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "mode": "execute" if args.execute else "dry-run",
            "summary": {
                **summary,
                "scheduled_backlog_count": len(scheduled_backlog),
            },
            "planner_slot_seed": planner_slot_seed_summary,
            "items": [
                {
                    "group_key": item.group_key,
                    "source_article_id": item.source_article_id,
                    "source_blog_id": item.source_blog_id,
                    "source_language": item.source_language,
                    "source_slug": item.source_slug,
                    "source_title": item.source_title,
                    "source_hero_url": item.source_hero_url,
                    "category_key": item.category_key,
                    "target_language": item.target_language,
                    "target_blog_id": item.target_blog_id,
                    "scheduled_for": item.scheduled_for.isoformat() if item.scheduled_for else None,
                }
                for item in scheduled_backlog
            ],
        }
        _write_report(backlog_path, backlog_payload)

        execute_payload: dict[str, Any] = {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "mode": "dry-run",
            "text_generation_route": route,
            "apply_group_links": {"updated_article_count": 0},
            "planner_slot_seed": planner_slot_seed_summary,
            "enqueue_result": {
                "requested_count": 0,
                "created_count": 0,
                "skipped_count": 0,
                "created": [],
                "skipped": [],
                "text_generation_route": route,
                "publish_mode": str(args.publish_mode),
            },
            "state_refresh": None,
        }

        if args.execute:
            route_updates = {
                travel_text_generation_route_setting_key(blog_id): route
                for blog_id in blog_ids
            }
            upsert_settings(db, route_updates)

            execute_payload["mode"] = "execute"
            execute_payload["route_updates"] = route_updates
            execute_payload["apply_group_links"] = apply_travel_sync_group_links(
                db,
                groups=groups,
                commit=True,
            )
            enqueue_result = enqueue_travel_cross_sync_jobs(
                db,
                backlog=scheduled_backlog,
                text_generation_route=route,
                publish_mode=str(args.publish_mode),
                max_items_per_run=max(int(args.max_items_per_run), 0),
                retry_failed_only=bool(args.retry_failed_only),
            )
            execute_payload["enqueue_result"] = enqueue_result

            if args.dispatch_jobs and enqueue_result.get("created"):
                from app.tasks.pipeline import run_job  # noqa: WPS433

                dispatched_job_ids: list[int] = []
                for row in enqueue_result.get("created", []):
                    job_id = int(row.get("job_id") or 0)
                    if job_id <= 0:
                        continue
                    run_job.delay(job_id)
                    dispatched_job_ids.append(job_id)
                execute_payload["dispatched_job_ids"] = dispatched_job_ids

            if not args.no_refresh_state:
                execute_payload["state_refresh"] = refresh_travel_translation_state(
                    db,
                    blog_ids=blog_ids,
                    report_root=report_root,
                    write_report=True,
                )

        _write_report(execute_path, execute_payload)

    output = {
        "manifest_report_path": str(manifest_path),
        "backlog_report_path": str(backlog_path),
        "execute_report_path": str(execute_path),
        "mode": "execute" if args.execute else "dry-run",
        "text_generation_route": route,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
