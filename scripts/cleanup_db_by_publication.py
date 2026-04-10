from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
REPORT_ROOT = REPO_ROOT / "storage" / "reports"
KST = ZoneInfo("Asia/Seoul")

DATABASE_URL_WAS_EXPLICIT = bool(os.environ.get("DATABASE_URL") or os.environ.get("BLOGGENT_DATABASE_URL"))
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get(
        "BLOGGENT_DATABASE_URL",
        "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent",
    )
if "STORAGE_ROOT" not in os.environ:
    os.environ["STORAGE_ROOT"] = str(REPO_ROOT / "storage")

sys.path.insert(0, str(API_ROOT))

from sqlalchemy import or_, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import AnalyticsArticleFact, SyncedCloudflarePost  # noqa: E402
from app.services.analytics_service import rebuild_blog_month_rollup  # noqa: E402
from app.services.blogger_sync_service import sync_connected_blogger_posts  # noqa: E402
from app.services.cloudflare_sync_service import sync_cloudflare_posts  # noqa: E402
from app.services.dedupe_utils import (  # noqa: E402
    dedupe_key as build_dedupe_key,
    pick_best_status as pick_best_dedupe_status,
    pick_preferred_url as pick_preferred_dedupe_url,
    status_priority as dedupe_status_priority,
)

SOURCE_PRIORITY = {"generated": 2, "synced": 1}
KEEPER_SELECTION_RULE = "status_priority > source_priority(generated) > latest_updated_at > id"


@dataclass(slots=True)
class DedupeStats:
    merged_group_count: int
    merged_row_deleted_count: int
    sample_merged_keys: list[str]


@dataclass(slots=True)
class CleanupResult:
    report_path: str
    cutoff_kst: str
    cutoff_utc: str
    scope: str
    mode: str
    live_sync: dict[str, Any]
    merged_group_count: int
    merged_row_deleted_count: int
    keeper_selection_rule: str
    sample_merged_keys: list[str]
    blogger: dict[str, Any]
    cloudflare: dict[str, Any]
    touched_months: list[str]


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


def _to_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_cutoff(cutoff_date: str, tz_name: str) -> tuple[datetime, datetime]:
    local_tz = ZoneInfo(tz_name)
    parsed_date = date.fromisoformat(str(cutoff_date).strip())
    cutoff_local = datetime.combine(parsed_date, time(23, 59, 59, 999999), tzinfo=local_tz)
    return cutoff_local, cutoff_local.astimezone(timezone.utc)


def _write_report(payload: dict[str, Any]) -> Path:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(KST).strftime("%Y%m%d-%H%M%S")
    report_path = REPORT_ROOT / f"dedupe-cleanup-{stamp}.json"
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    return report_path


def _pick_first_non_empty(rows: list[Any], field: str):
    for row in rows:
        value = getattr(row, field, None)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _pick_first_value(rows: list[Any], field: str, *, allow_empty_string: bool = False):
    for row in rows:
        value = getattr(row, field, None)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip() and not allow_empty_string:
            continue
        return value
    return None


def _analytics_group_key(row: AnalyticsArticleFact) -> str:
    return build_dedupe_key(
        scope=f"blogger:{row.blog_id}",
        url=row.actual_url,
        title=row.title,
        published_at=_to_utc(row.published_at),
    )


def _analytics_row_priority(row: AnalyticsArticleFact) -> tuple[int, int, datetime, int]:
    status_rank = dedupe_status_priority(str(row.status or "").strip().lower())
    source_rank = SOURCE_PRIORITY.get(str(row.source_type or "").strip().lower(), 0)
    updated_at = _to_utc(row.updated_at) or _to_utc(row.created_at) or _to_utc(row.published_at) or datetime.min.replace(tzinfo=timezone.utc)
    row_id = int(row.id or 0)
    return (status_rank, source_rank, updated_at, row_id)


def _merge_analytics_group(rows: list[AnalyticsArticleFact]) -> AnalyticsArticleFact:
    ordered = sorted(rows, key=_analytics_row_priority, reverse=True)
    keeper = ordered[0]
    keeper.status = pick_best_dedupe_status(*[row.status for row in ordered]) or keeper.status
    keeper.actual_url = pick_preferred_dedupe_url(*[row.actual_url for row in ordered]) or keeper.actual_url

    for field in (
        "article_id",
        "synced_post_id",
        "published_at",
        "title",
        "theme_key",
        "theme_name",
        "category",
        "seo_score",
        "geo_score",
        "lighthouse_score",
        "similarity_score",
        "most_similar_url",
    ):
        setattr(keeper, field, _pick_first_non_empty(ordered, field))

    keeper.source_type = "generated" if keeper.article_id is not None or any(str(row.source_type or "").strip().lower() == "generated" for row in ordered) else "synced"
    return keeper


def _dedupe_blogger_analytics(db: Session, *, cutoff_utc: datetime) -> tuple[DedupeStats, set[tuple[int, str]]]:
    rows = (
        db.execute(
            select(AnalyticsArticleFact)
            .where(
                or_(
                    AnalyticsArticleFact.published_at <= cutoff_utc,
                    AnalyticsArticleFact.created_at <= cutoff_utc,
                )
            )
            .order_by(AnalyticsArticleFact.blog_id.asc(), AnalyticsArticleFact.id.asc())
        )
        .scalars()
        .all()
    )

    grouped: dict[str, list[AnalyticsArticleFact]] = {}
    for row in rows:
        grouped.setdefault(_analytics_group_key(row), []).append(row)

    merged_group_count = 0
    merged_row_deleted_count = 0
    sample_merged_keys: list[str] = []
    touched_months: set[tuple[int, str]] = set()
    for key, items in grouped.items():
        if len(items) <= 1:
            continue
        merged_group_count += 1
        keeper = _merge_analytics_group(items)
        for row in items:
            if row.month:
                touched_months.add((row.blog_id, row.month))
            if row.id == keeper.id:
                continue
            db.delete(row)
            merged_row_deleted_count += 1
        if len(sample_merged_keys) < 20:
            sample_merged_keys.append(f"{key} -> keep:{keeper.id}")

    return (
        DedupeStats(
            merged_group_count=merged_group_count,
            merged_row_deleted_count=merged_row_deleted_count,
            sample_merged_keys=sample_merged_keys,
        ),
        touched_months,
    )


def _cloudflare_group_key(row: SyncedCloudflarePost) -> str:
    return build_dedupe_key(
        scope=f"cloudflare:{row.managed_channel_id}",
        url=row.url,
        title=row.title,
        published_at=_to_utc(row.published_at),
    )


def _cloudflare_row_priority(row: SyncedCloudflarePost) -> tuple[int, datetime, int]:
    status_rank = dedupe_status_priority(str(row.status or "").strip().lower())
    updated_at = (
        _to_utc(row.updated_at_remote)
        or _to_utc(row.published_at)
        or _to_utc(row.created_at_remote)
        or _to_utc(row.synced_at)
        or _to_utc(row.updated_at)
        or _to_utc(row.created_at)
        or datetime.min.replace(tzinfo=timezone.utc)
    )
    row_id = int(row.id or 0)
    return (status_rank, updated_at, row_id)


def _merge_cloudflare_group(rows: list[SyncedCloudflarePost]) -> SyncedCloudflarePost:
    ordered = sorted(rows, key=_cloudflare_row_priority, reverse=True)
    keeper = ordered[0]
    keeper.status = pick_best_dedupe_status(*[row.status for row in ordered]) or keeper.status
    keeper.url = pick_preferred_dedupe_url(*[row.url for row in ordered]) or keeper.url
    keeper.thumbnail_url = pick_preferred_dedupe_url(*[row.thumbnail_url for row in ordered]) or keeper.thumbnail_url

    for field in (
        "slug",
        "title",
        "published_at",
        "created_at_remote",
        "updated_at_remote",
        "category_name",
        "category_slug",
        "canonical_category_name",
        "canonical_category_slug",
        "excerpt_text",
        "seo_score",
        "geo_score",
        "ctr",
        "lighthouse_score",
        "live_image_count",
        "live_image_issue",
        "live_image_audited_at",
        "index_status",
        "quality_status",
    ):
        merged_value = _pick_first_value(ordered, field, allow_empty_string=field in {"excerpt_text"})
        if merged_value is not None:
            setattr(keeper, field, merged_value)

    labels: list[str] = []
    seen_labels: set[str] = set()
    for row in ordered:
        for raw in row.labels or []:
            label = str(raw or "").strip()
            if not label:
                continue
            key = label.casefold()
            if key in seen_labels:
                continue
            seen_labels.add(key)
            labels.append(label)
    keeper.labels = labels
    keeper.synced_at = max(
        [value for value in [row.synced_at for row in ordered] if value is not None] or [datetime.now(timezone.utc)]
    )
    return keeper


def _dedupe_cloudflare_rows(db: Session, *, cutoff_utc: datetime) -> DedupeStats:
    rows = (
        db.execute(
            select(SyncedCloudflarePost)
            .where(
                or_(
                    SyncedCloudflarePost.published_at <= cutoff_utc,
                    SyncedCloudflarePost.created_at <= cutoff_utc,
                )
            )
            .order_by(SyncedCloudflarePost.managed_channel_id.asc(), SyncedCloudflarePost.id.asc())
        )
        .scalars()
        .all()
    )
    grouped: dict[str, list[SyncedCloudflarePost]] = {}
    for row in rows:
        grouped.setdefault(_cloudflare_group_key(row), []).append(row)

    merged_group_count = 0
    merged_row_deleted_count = 0
    sample_merged_keys: list[str] = []
    for key, items in grouped.items():
        if len(items) <= 1:
            continue
        merged_group_count += 1
        keeper = _merge_cloudflare_group(items)
        for row in items:
            if row.id == keeper.id:
                continue
            db.delete(row)
            merged_row_deleted_count += 1
        if len(sample_merged_keys) < 20:
            sample_merged_keys.append(f"{key} -> keep:{keeper.id}")

    return DedupeStats(
        merged_group_count=merged_group_count,
        merged_row_deleted_count=merged_row_deleted_count,
        sample_merged_keys=sample_merged_keys,
    )


def _sync_live_sources(db: Session, *, run_live_sync: bool, scope: str) -> dict[str, Any]:
    if not run_live_sync:
        return {"status": "skipped", "reason": "skip_live_sync"}
    result: dict[str, Any] = {"status": "ok", "scope": scope}
    if scope in {"all", "blogger"}:
        try:
            result["blogger"] = sync_connected_blogger_posts(db)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            result["blogger_error"] = str(exc)
    if scope in {"all", "cloudflare"}:
        try:
            result["cloudflare"] = sync_cloudflare_posts(db, include_non_published=True)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            result["cloudflare_error"] = str(exc)
    return result


def run_cleanup(
    *,
    cutoff_date: str,
    timezone_name: str,
    scope: str,
    run_live_sync: bool,
    execute: bool,
) -> CleanupResult:
    cutoff_kst, cutoff_utc = _parse_cutoff(cutoff_date, timezone_name)
    with SessionLocal() as db:
        live_sync = _sync_live_sources(db, run_live_sync=run_live_sync, scope=scope)

        blogger_stats = DedupeStats(0, 0, [])
        cloudflare_stats = DedupeStats(0, 0, [])
        touched_months: set[tuple[int, str]] = set()

        if scope in {"all", "blogger"}:
            blogger_stats, touched_months = _dedupe_blogger_analytics(db, cutoff_utc=cutoff_utc)
            for blog_id, month in sorted(touched_months):
                if month:
                    rebuild_blog_month_rollup(db, blog_id, month, commit=False)

        if scope in {"all", "cloudflare"}:
            cloudflare_stats = _dedupe_cloudflare_rows(db, cutoff_utc=cutoff_utc)

        if execute:
            db.commit()
        else:
            db.rollback()

    merged_group_count = blogger_stats.merged_group_count + cloudflare_stats.merged_group_count
    merged_row_deleted_count = blogger_stats.merged_row_deleted_count + cloudflare_stats.merged_row_deleted_count
    sample_merged_keys = [*blogger_stats.sample_merged_keys, *cloudflare_stats.sample_merged_keys][:20]

    payload = {
        "cutoff_kst": cutoff_kst.isoformat(),
        "cutoff_utc": cutoff_utc.isoformat(),
        "scope": scope,
        "mode": "execute" if execute else "dry-run",
        "live_sync": live_sync,
        "merged_group_count": merged_group_count,
        "merged_row_deleted_count": merged_row_deleted_count,
        "keeper_selection_rule": KEEPER_SELECTION_RULE,
        "sample_merged_keys": sample_merged_keys,
        "blogger": {
            "merged_group_count": blogger_stats.merged_group_count,
            "merged_row_deleted_count": blogger_stats.merged_row_deleted_count,
            "sample_merged_keys": blogger_stats.sample_merged_keys,
        },
        "cloudflare": {
            "merged_group_count": cloudflare_stats.merged_group_count,
            "merged_row_deleted_count": cloudflare_stats.merged_row_deleted_count,
            "sample_merged_keys": cloudflare_stats.sample_merged_keys,
        },
        "touched_months": [f"{blog_id}:{month}" for blog_id, month in sorted(touched_months)],
    }
    report_path = _write_report(payload)
    return CleanupResult(
        report_path=str(report_path),
        cutoff_kst=payload["cutoff_kst"],
        cutoff_utc=payload["cutoff_utc"],
        scope=scope,
        mode=payload["mode"],
        live_sync=payload["live_sync"],
        merged_group_count=payload["merged_group_count"],
        merged_row_deleted_count=payload["merged_row_deleted_count"],
        keeper_selection_rule=payload["keeper_selection_rule"],
        sample_merged_keys=payload["sample_merged_keys"],
        blogger=payload["blogger"],
        cloudflare=payload["cloudflare"],
        touched_months=payload["touched_months"],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deduplicate blogger/cloudflare analytics records by canonical key.")
    parser.add_argument("--cutoff-date", default="2026-04-10", help="Cutoff date (YYYY-MM-DD) in local timezone.")
    parser.add_argument("--timezone", default="Asia/Seoul", help="Timezone for cutoff date.")
    parser.add_argument("--scope", choices=["all", "blogger", "cloudflare"], default="all", help="Cleanup scope.")
    parser.add_argument("--skip-live-sync", action="store_true", help="Skip Blogger/Cloudflare live sync before dedupe.")
    parser.add_argument("--dry-run", action="store_true", help="Run cleanup logic without committing.")
    parser.add_argument("--execute", action="store_true", help="Execute dedupe and commit changes.")
    args = parser.parse_args()
    if args.dry_run and args.execute:
        parser.error("--dry-run and --execute cannot be used together.")
    if args.execute and not DATABASE_URL_WAS_EXPLICIT:
        parser.error("--execute requires DATABASE_URL or BLOGGENT_DATABASE_URL to be explicitly set.")
    return args


def main() -> int:
    args = parse_args()
    execute = bool(args.execute) and not bool(args.dry_run)
    result = run_cleanup(
        cutoff_date=args.cutoff_date,
        timezone_name=args.timezone,
        scope=args.scope,
        run_live_sync=not args.skip_live_sync,
        execute=execute,
    )
    print(
        json.dumps(
            {
                "report_path": result.report_path,
                "cutoff_kst": result.cutoff_kst,
                "cutoff_utc": result.cutoff_utc,
                "scope": result.scope,
                "mode": result.mode,
                "merged_group_count": result.merged_group_count,
                "merged_row_deleted_count": result.merged_row_deleted_count,
                "keeper_selection_rule": result.keeper_selection_rule,
                "sample_merged_keys": result.sample_merged_keys,
                "blogger": result.blogger,
                "cloudflare": result.cloudflare,
                "touched_months": result.touched_months,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
