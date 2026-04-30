from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select


REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
RUNTIME_STORAGE_ROOT = Path(os.getenv("BLOGGENT_RUNTIME_STORAGE_ROOT", r"D:\Donggri_Runtime\BloggerGent\storage"))
REPORT_ROOT = RUNTIME_STORAGE_ROOT / "_common" / "analysis" / "lighthouse" / "cloudflare"

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get(
        "BLOGGENT_DATABASE_URL",
        "postgresql://bloggent:bloggent@localhost:15432/bloggent",
    )
if "STORAGE_ROOT" not in os.environ:
    os.environ["STORAGE_ROOT"] = str(RUNTIME_STORAGE_ROOT)

sys.path.insert(0, str(API_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import ManagedChannel, SyncedCloudflarePost  # noqa: E402
from app.services.ops.lighthouse_service import LighthouseAuditError, run_lighthouse_audit  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit published Cloudflare posts with Lighthouse and persist scores into synced_cloudflare_posts."
    )
    parser.add_argument("--month", default=None, help="Optional YYYY-MM month filter")
    parser.add_argument("--category", action="append", default=[], help="Canonical or raw category slug filter. Repeatable.")
    parser.add_argument("--status", action="append", default=["published"], help="Post status filter. Repeatable.")
    parser.add_argument("--form-factor", choices=("mobile", "desktop"), default="mobile", help="Lighthouse emulation preset")
    parser.add_argument("--timeout-seconds", type=int, default=180, help="Per-URL Lighthouse timeout")
    parser.add_argument("--workers", type=int, default=2, help="Concurrent Lighthouse workers")
    parser.add_argument("--limit", type=int, default=0, help="Maximum number of posts to audit")
    parser.add_argument("--slug-file", default=None, help="Optional CSV/TXT file containing slugs to audit")
    parser.add_argument("--only-missing", action="store_true", help="Only audit rows whose lighthouse_score is null")
    parser.add_argument("--skip-hours", type=int, default=0, help="Skip rows audited within this many hours")
    return parser.parse_args()


def _safe_str(value: object | None) -> str:
    return str(value or "").strip()


def _load_slug_filter(path_value: str | None) -> set[str]:
    path = Path(path_value or "")
    if not path.exists():
        return set()
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames and "slug" in reader.fieldnames:
                return {_safe_str(row.get("slug")) for row in reader if _safe_str(row.get("slug"))}
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def _slugify(value: str, *, fallback: str = "post") -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-")
    return normalized[:80] if normalized else fallback


def _published_month_matches(post: SyncedCloudflarePost, month: str | None) -> bool:
    if not month:
        return True
    if post.published_at is None:
        return False
    value = post.published_at
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m") == month


def _resolve_channel_id(db) -> int:
    channel = db.execute(
        select(ManagedChannel).where(ManagedChannel.provider == "cloudflare").order_by(ManagedChannel.id.desc())
    ).scalar_one_or_none()
    if channel is None:
        raise RuntimeError("Cloudflare channel is not configured.")
    return int(channel.id)


def _load_posts(args: argparse.Namespace) -> list[SyncedCloudflarePost]:
    normalized_statuses = {value.strip().lower() for value in args.status if value and value.strip()}
    normalized_categories = {value.strip() for value in args.category if value and value.strip()}
    normalized_slugs = _load_slug_filter(args.slug_file)
    skip_cutoff = None
    if int(args.skip_hours or 0) > 0:
        skip_cutoff = datetime.now(timezone.utc) - timedelta(hours=max(int(args.skip_hours), 1))

    with SessionLocal() as db:
        channel_id = _resolve_channel_id(db)
        stmt = select(SyncedCloudflarePost).where(SyncedCloudflarePost.managed_channel_id == channel_id)
        if normalized_statuses:
            stmt = stmt.where(SyncedCloudflarePost.status.in_(sorted(normalized_statuses)))
        if normalized_categories:
            stmt = stmt.where(
                or_(
                    SyncedCloudflarePost.canonical_category_slug.in_(sorted(normalized_categories)),
                    SyncedCloudflarePost.category_slug.in_(sorted(normalized_categories)),
                )
            )
        if normalized_slugs:
            stmt = stmt.where(SyncedCloudflarePost.slug.in_(sorted(normalized_slugs)))
        if args.only_missing:
            stmt = stmt.where(SyncedCloudflarePost.lighthouse_score.is_(None))
        if skip_cutoff is not None:
            stmt = stmt.where(
                or_(
                    SyncedCloudflarePost.lighthouse_last_audited_at.is_(None),
                    SyncedCloudflarePost.lighthouse_last_audited_at < skip_cutoff,
                )
            )
        stmt = stmt.order_by(
            SyncedCloudflarePost.published_at.desc().nullslast(),
            SyncedCloudflarePost.updated_at_remote.desc().nullslast(),
            SyncedCloudflarePost.id.desc(),
        )
        posts = list(db.execute(stmt).scalars().all())

    filtered = [post for post in posts if _published_month_matches(post, args.month) and _safe_str(post.url)]
    if int(args.limit or 0) > 0:
        filtered = filtered[: int(args.limit)]
    return filtered


def _audit_post(url: str, *, form_factor: str, timeout_seconds: int) -> dict[str, Any]:
    return run_lighthouse_audit(
        url,
        form_factor=form_factor,
        timeout_seconds=timeout_seconds,
    )


def _persist_audit_result(
    *,
    post_id: int,
    audit: dict[str, Any],
    report_path: str,
    form_factor: str,
) -> None:
    with SessionLocal() as db:
        post = db.get(SyncedCloudflarePost, post_id)
        if post is None:
            return
        scores = dict(audit.get("scores") or {})
        audited_at = datetime.now(timezone.utc)
        post.lighthouse_score = float(scores.get("lighthouse_score")) if scores.get("lighthouse_score") is not None else None
        post.lighthouse_accessibility_score = (
            float(scores.get("accessibility_score")) if scores.get("accessibility_score") is not None else None
        )
        post.lighthouse_best_practices_score = (
            float(scores.get("best_practices_score")) if scores.get("best_practices_score") is not None else None
        )
        post.lighthouse_seo_score = float(scores.get("seo_score")) if scores.get("seo_score") is not None else None
        post.lighthouse_last_audited_at = audited_at
        post.lighthouse_payload = {
            "version": "cloudflare-lighthouse-v1",
            "url": _safe_str(post.url),
            "form_factor": form_factor,
            "weights": dict(audit.get("weights") or {}),
            "scores": scores,
            "report_path": report_path,
            "audited_at": audited_at.isoformat(),
        }
        db.add(post)
        db.commit()


def main() -> int:
    args = parse_args()
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)

    posts = _load_posts(args)
    if not posts:
        print(
            json.dumps(
                {
                    "status": "ok",
                    "processed": 0,
                    "message": "No matching Cloudflare posts.",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    workers = max(min(int(args.workers or 1), 8), 1)
    summary: dict[str, Any] = {
        "status": "ok",
        "processed": 0,
        "updated": 0,
        "failed": 0,
        "skipped": 0,
        "workers": workers,
        "form_factor": args.form_factor,
        "month": args.month,
        "only_missing": bool(args.only_missing),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "items": [],
    }

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(
                _audit_post,
                _safe_str(post.url),
                form_factor=args.form_factor,
                timeout_seconds=max(int(args.timeout_seconds or 180), 30),
            ): {
                "post_id": int(post.id),
                "title": _safe_str(post.title),
                "url": _safe_str(post.url),
                "slug": _safe_str(post.slug) or _slugify(_safe_str(post.title)),
            }
            for post in posts
        }

        for future in as_completed(future_map):
            item = future_map[future]
            summary["processed"] += 1
            try:
                audit = future.result()
                audited_at = datetime.now(timezone.utc)
                timestamp = audited_at.strftime("%Y%m%d-%H%M%S")
                report_file = REPORT_ROOT / f"cloudflare-{item['post_id']}-{timestamp}-{_slugify(item['slug'])}.json"
                report_file.write_text(json.dumps(audit.get("raw_report") or {}, ensure_ascii=False), encoding="utf-8")
                _persist_audit_result(
                    post_id=item["post_id"],
                    audit=audit,
                    report_path=str(report_file),
                    form_factor=args.form_factor,
                )
                summary["updated"] += 1
                summary["items"].append(
                    {
                        "post_id": item["post_id"],
                        "title": item["title"],
                        "url": item["url"],
                        "status": "updated",
                        "lighthouse_score": audit.get("scores", {}).get("lighthouse_score"),
                        "report_path": str(report_file),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                summary["failed"] += 1
                summary["items"].append(
                    {
                        "post_id": item["post_id"],
                        "title": item["title"],
                        "url": item["url"],
                        "status": "failed",
                        "error": str(exc),
                    }
                )

    summary["ended_at"] = datetime.now(timezone.utc).isoformat()
    if summary["failed"] > 0:
        summary["status"] = "partial"

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
