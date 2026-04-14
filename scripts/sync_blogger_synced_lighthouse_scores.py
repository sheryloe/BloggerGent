from __future__ import annotations

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
LOCAL_STORAGE_ROOT = REPO_ROOT / "storage"
REPORT_ROOT = LOCAL_STORAGE_ROOT / "reports" / "lighthouse" / "blogger-synced"

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get(
        "BLOGGENT_DATABASE_URL",
        "postgresql://bloggent:bloggent@localhost:15432/bloggent",
    )
if "STORAGE_ROOT" not in os.environ:
    os.environ["STORAGE_ROOT"] = str(LOCAL_STORAGE_ROOT)

sys.path.insert(0, str(API_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import AnalyticsArticleFact, Blog, SyncedBloggerPost  # noqa: E402
from app.services.ops.analytics_service import rebuild_blog_month_rollup, upsert_synced_post_fact  # noqa: E402
from app.services.ops.lighthouse_service import run_lighthouse_audit  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit synced-only Blogger live posts with Lighthouse and persist scores into synced_blogger_posts."
    )
    parser.add_argument("--blog-id", action="append", type=int, default=[], help="Specific blog id filter. Repeatable.")
    parser.add_argument("--month", default=None, help="Optional YYYY-MM month filter.")
    parser.add_argument("--status", action="append", default=["published", "live"], help="Post status filter. Repeatable.")
    parser.add_argument("--form-factor", choices=("mobile", "desktop"), default="mobile", help="Lighthouse emulation preset.")
    parser.add_argument("--timeout-seconds", type=int, default=180, help="Per-URL Lighthouse timeout.")
    parser.add_argument("--workers", type=int, default=2, help="Concurrent Lighthouse workers.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum number of posts to audit.")
    parser.add_argument("--only-missing", action="store_true", help="Only audit rows whose lighthouse_score is null.")
    parser.add_argument("--skip-hours", type=int, default=0, help="Skip rows audited within this many hours.")
    return parser.parse_args()


def _safe_str(value: object | None) -> str:
    return str(value or "").strip()


def _slugify(value: str, *, fallback: str = "post") -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-")
    return normalized[:80] if normalized else fallback


def _published_month_matches(post: SyncedBloggerPost, month: str | None) -> bool:
    if not month:
        return True
    if post.published_at is None:
        return False
    value = post.published_at
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m") == month


def _load_posts(args: argparse.Namespace) -> list[SyncedBloggerPost]:
    normalized_statuses = {value.strip().lower() for value in args.status if value and value.strip()}
    skip_cutoff = None
    if int(args.skip_hours or 0) > 0:
        skip_cutoff = datetime.now(timezone.utc) - timedelta(hours=max(int(args.skip_hours), 1))

    with SessionLocal() as db:
        stmt = (
            select(SyncedBloggerPost)
            .join(Blog, Blog.id == SyncedBloggerPost.blog_id)
            .where(Blog.is_active.is_(True))
            .where(SyncedBloggerPost.url.is_not(None))
            .where(SyncedBloggerPost.url != "")
        )
        if normalized_statuses:
            stmt = stmt.where(func.lower(SyncedBloggerPost.status).in_(sorted(normalized_statuses)))
        if args.blog_id:
            stmt = stmt.where(SyncedBloggerPost.blog_id.in_(sorted(set(int(value) for value in args.blog_id))))
        stmt = stmt.order_by(
            SyncedBloggerPost.published_at.desc().nullslast(),
            SyncedBloggerPost.updated_at_remote.desc().nullslast(),
            SyncedBloggerPost.id.desc(),
        )
        posts = list(db.execute(stmt).scalars().all())
        fact_rows = db.execute(
            select(AnalyticsArticleFact)
            .where(AnalyticsArticleFact.synced_post_id.in_([post.id for post in posts]))
            .order_by(AnalyticsArticleFact.id.desc())
        ).scalars().all() if posts else []

    fact_map: dict[int, AnalyticsArticleFact] = {}
    for fact in fact_rows:
        if fact.synced_post_id is None:
            continue
        fact_map.setdefault(int(fact.synced_post_id), fact)

    filtered: list[SyncedBloggerPost] = []
    for post in posts:
        if not _published_month_matches(post, args.month):
            continue
        fact = fact_map.get(int(post.id))
        if args.only_missing and fact is not None and fact.lighthouse_score is not None:
            continue
        if skip_cutoff is not None and fact is not None and fact.updated_at is not None:
            last_updated = fact.updated_at
            if last_updated.tzinfo is None:
                last_updated = last_updated.replace(tzinfo=timezone.utc)
            if last_updated >= skip_cutoff:
                continue
        filtered.append(post)
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
) -> tuple[int, str] | None:
    with SessionLocal() as db:
        post = db.get(SyncedBloggerPost, post_id)
        if post is None:
            return None
        scores = dict(audit.get("scores") or {})
        upsert_synced_post_fact(db, post_id, commit=False)
        fact = db.execute(
            select(AnalyticsArticleFact)
            .where(AnalyticsArticleFact.synced_post_id == post_id)
            .order_by(AnalyticsArticleFact.id.desc())
        ).scalar_one_or_none()
        if fact is None:
            db.rollback()
            return None
        fact.lighthouse_score = float(scores.get("lighthouse_score")) if scores.get("lighthouse_score") is not None else None
        fact.lighthouse_accessibility_score = (
            float(scores.get("accessibility_score")) if scores.get("accessibility_score") is not None else None
        )
        fact.lighthouse_best_practices_score = (
            float(scores.get("best_practices_score")) if scores.get("best_practices_score") is not None else None
        )
        fact.lighthouse_seo_score = float(scores.get("seo_score")) if scores.get("seo_score") is not None else None
        db.add(fact)
        month = str(fact.month or "").strip()
        blog_id = int(fact.blog_id)
        db.commit()
        return (blog_id, month)


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
                    "message": "No matching synced Blogger posts.",
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
        "blogs_rebuilt": [],
        "workers": workers,
        "form_factor": args.form_factor,
        "month": args.month,
        "only_missing": bool(args.only_missing),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "items": [],
    }
    touched_pairs: set[tuple[int, str]] = set()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(
                _audit_post,
                _safe_str(post.url),
                form_factor=args.form_factor,
                timeout_seconds=max(int(args.timeout_seconds or 180), 30),
            ): {
                "post_id": int(post.id),
                "blog_id": int(post.blog_id),
                "remote_post_id": _safe_str(post.remote_post_id),
                "title": _safe_str(post.title),
                "url": _safe_str(post.url),
                "slug": _slugify(_safe_str(post.title)),
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
                report_file = REPORT_ROOT / (
                    f"blogger-synced-{item['post_id']}-{timestamp}-{_slugify(item['slug'])}.json"
                )
                report_file.write_text(json.dumps(audit.get("raw_report") or {}, ensure_ascii=False), encoding="utf-8")
                touched_pair = _persist_audit_result(
                    post_id=item["post_id"],
                    audit=audit,
                    report_path=str(report_file),
                    form_factor=args.form_factor,
                )
                if touched_pair is not None and touched_pair[1]:
                    touched_pairs.add(touched_pair)
                summary["updated"] += 1
                summary["items"].append(
                    {
                        "post_id": item["post_id"],
                        "blog_id": item["blog_id"],
                        "remote_post_id": item["remote_post_id"],
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
                        "blog_id": item["blog_id"],
                        "remote_post_id": item["remote_post_id"],
                        "title": item["title"],
                        "url": item["url"],
                        "status": "failed",
                        "error": str(exc),
                    }
                )

    if touched_pairs:
        with SessionLocal() as db:
            for blog_id, month in sorted(touched_pairs, key=lambda item: (item[0], item[1])):
                rebuild_blog_month_rollup(db, blog_id, month, commit=False)
            db.commit()
        summary["blogs_rebuilt"] = sorted({blog_id for blog_id, _month in touched_pairs})

    summary["ended_at"] = datetime.now(timezone.utc).isoformat()
    if summary["failed"] > 0:
        summary["status"] = "partial"

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
