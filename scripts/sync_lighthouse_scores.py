from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
LOCAL_STORAGE_ROOT = REPO_ROOT / "storage"
REPORT_ROOT = LOCAL_STORAGE_ROOT / "reports" / "lighthouse"

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
from app.models.entities import Article, Blog, PostStatus  # noqa: E402
from app.services.analytics_service import rebuild_blog_month_rollup, upsert_article_fact  # noqa: E402
from app.services.lighthouse_service import LighthouseAuditError, run_lighthouse_audit  # noqa: E402


PROFILE_CHOICES = ("korea_travel", "world_mystery")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit published posts with Lighthouse and persist per-article scores.")
    parser.add_argument("--profile", choices=PROFILE_CHOICES, default=None, help="Filter by blog profile key")
    parser.add_argument("--published-only", action="store_true", help="Only include published Blogger posts")
    parser.add_argument("--limit", type=int, default=0, help="Maximum number of articles to process")
    parser.add_argument("--form-factor", choices=("mobile", "desktop"), default="mobile", help="Lighthouse emulation preset")
    parser.add_argument("--timeout-seconds", type=int, default=180, help="Per-URL Lighthouse timeout")
    parser.add_argument("--only-missing", action="store_true", help="Skip rows that already have Lighthouse score")
    parser.add_argument("--skip-hours", type=int, default=0, help="Skip rows audited within this many hours")
    return parser.parse_args()


def _safe_str(value: object | None) -> str:
    return str(value or "").strip()


def _slugify(value: str, *, fallback: str = "post") -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-")
    return normalized[:80] if normalized else fallback


def _pick_article_url(article: Article) -> str:
    post = getattr(article, "blogger_post", None)
    return _safe_str(getattr(post, "published_url", None))


def _load_articles(*, profile: str | None, published_only: bool, limit: int) -> list[Article]:
    with SessionLocal() as db:
        stmt = (
            select(Article)
            .join(Blog, Blog.id == Article.blog_id)
            .options(selectinload(Article.blog), selectinload(Article.blogger_post))
            .where(Blog.is_active.is_(True))
            .order_by(Article.created_at.desc(), Article.id.desc())
        )
        if profile:
            stmt = stmt.where(Blog.profile_key == profile)
        if published_only:
            stmt = stmt.where(Article.blogger_post.has(post_status=PostStatus.PUBLISHED))
        if limit > 0:
            stmt = stmt.limit(limit)
        return list(db.execute(stmt).scalars().unique().all())


def main() -> int:
    args = parse_args()
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)

    articles = _load_articles(profile=args.profile, published_only=args.published_only, limit=args.limit)
    if not articles:
        print(json.dumps({"status": "ok", "processed": 0, "message": "No matching articles."}, ensure_ascii=False, indent=2))
        return 0

    now_utc = datetime.now(timezone.utc)
    skip_cutoff = now_utc - timedelta(hours=max(args.skip_hours, 0)) if args.skip_hours > 0 else None

    summary: dict[str, Any] = {
        "status": "ok",
        "processed": 0,
        "updated": 0,
        "skipped": 0,
        "failed": 0,
        "profile": args.profile,
        "form_factor": args.form_factor,
        "started_at": now_utc.isoformat(),
        "items": [],
    }

    touched_pairs: set[tuple[int, str]] = set()

    with SessionLocal() as db:
        for item in articles:
            article = db.get(Article, item.id)
            if article is None:
                continue

            url = _pick_article_url(article)
            if not url:
                summary["skipped"] += 1
                summary["items"].append({
                    "article_id": item.id,
                    "title": _safe_str(item.title),
                    "status": "skipped",
                    "reason": "missing_published_url",
                })
                continue

            if args.only_missing and article.quality_lighthouse_score is not None:
                summary["skipped"] += 1
                summary["items"].append({
                    "article_id": article.id,
                    "title": _safe_str(article.title),
                    "url": url,
                    "status": "skipped",
                    "reason": "already_scored",
                })
                continue

            if skip_cutoff is not None and article.quality_lighthouse_last_audited_at is not None:
                last_audited = article.quality_lighthouse_last_audited_at
                if last_audited.tzinfo is None:
                    last_audited = last_audited.replace(tzinfo=timezone.utc)
                if last_audited >= skip_cutoff:
                    summary["skipped"] += 1
                    summary["items"].append({
                        "article_id": article.id,
                        "title": _safe_str(article.title),
                        "url": url,
                        "status": "skipped",
                        "reason": "skip_hours_window",
                    })
                    continue

            summary["processed"] += 1

            try:
                audit = run_lighthouse_audit(
                    url,
                    form_factor=args.form_factor,
                    timeout_seconds=args.timeout_seconds,
                )
                audited_at = datetime.now(timezone.utc)
                timestamp = audited_at.strftime("%Y%m%d-%H%M%S")
                report_file = REPORT_ROOT / f"article-{article.id}-{timestamp}-{_slugify(article.slug or article.title)}.json"
                report_file.write_text(json.dumps(audit.get("raw_report") or {}, ensure_ascii=False), encoding="utf-8")

                scores = dict(audit.get("scores") or {})
                lighthouse_score = scores.get("lighthouse_score")
                if lighthouse_score is None:
                    raise LighthouseAuditError("Missing lighthouse_score in parsed report.")

                article.quality_lighthouse_score = float(lighthouse_score)
                article.quality_lighthouse_last_audited_at = audited_at
                article.quality_lighthouse_payload = {
                    "version": "lighthouse-v1",
                    "url": url,
                    "form_factor": args.form_factor,
                    "weights": dict(audit.get("weights") or {}),
                    "scores": scores,
                    "report_path": str(report_file),
                    "audited_at": audited_at.isoformat(),
                }
                db.add(article)

                touched_months = upsert_article_fact(db, article.id, commit=False)
                for month in touched_months:
                    touched_pairs.add((article.blog_id, month))

                db.commit()

                summary["updated"] += 1
                summary["items"].append({
                    "article_id": article.id,
                    "title": _safe_str(article.title),
                    "url": url,
                    "status": "updated",
                    "lighthouse_score": article.quality_lighthouse_score,
                    "report_path": str(report_file),
                })
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                summary["failed"] += 1
                summary["items"].append({
                    "article_id": article.id,
                    "title": _safe_str(article.title),
                    "url": url,
                    "status": "failed",
                    "error": str(exc),
                })

        if touched_pairs:
            for blog_id, month in sorted(touched_pairs, key=lambda item: (item[0], item[1])):
                rebuild_blog_month_rollup(db, blog_id, month, commit=False)
            db.commit()

    summary["ended_at"] = datetime.now(timezone.utc).isoformat()
    if summary["failed"] > 0:
        summary["status"] = "partial"

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
