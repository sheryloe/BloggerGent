from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get(
        "BLOGGENT_DATABASE_URL",
        "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent",
    )
if "STORAGE_ROOT" not in os.environ:
    os.environ["STORAGE_ROOT"] = os.environ.get("BLOGGENT_RUNTIME_STORAGE_ROOT", r"D:\Donggri_Runtime\BloggerGent\storage")

REPORT_ROOT = Path(
    os.environ.get("TRAVEL_REPORT_ROOT")
    or os.environ.get("BLOGGENT_TRAVEL_REPORT_ROOT")
    or str(Path(os.environ["STORAGE_ROOT"]) / "travel" / "reports")
)

sys.path.insert(0, str(API_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import delete, select, update  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import (  # noqa: E402
    AIUsageEvent,
    AnalyticsArticleFact,
    Article,
    AuditLog,
    Blog,
    BloggerPost,
    ContentItem,
    ContentPlanSlot,
    Image,
    Job,
    ManualImageSlot,
    PublishQueueItem,
    SearchConsolePageMetric,
    SyncedBloggerPost,
    SyncedCloudflarePost,
)
from app.services.blogger.blogger_sync_service import sync_blogger_posts_for_blog  # noqa: E402
from app.services.cloudflare.cloudflare_sync_service import sync_cloudflare_posts  # noqa: E402
from app.services.content.content_ops_service import compute_seo_geo_scores  # noqa: E402
from app.services.integrations.google_indexing_service import refresh_search_console_ctr_cache  # noqa: E402
from app.services.ops.analytics_service import rebuild_blog_month_rollup, sync_synced_post_facts_for_blog  # noqa: E402
from app.services.ops.dedupe_utils import url_identity_key  # noqa: E402
from app.services.ops.lighthouse_service import (  # noqa: E402
    LighthouseAuditError,
    parse_lighthouse_report,
    run_lighthouse_audit,
    write_lighthouse_raw_report,
)

LIVE_STATUSES = {"live", "published"}
TRAVEL_BLOG_IDS = {34, 36, 37}


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _write_report(payload: dict[str, Any]) -> Path:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = REPORT_ROOT / f"live-db-score-reconcile-{stamp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    return path


def _month_key(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).strftime("%Y-%m") if value.tzinfo else value.strftime("%Y-%m")


def _score_complete_article(article: Article) -> bool:
    return (
        article.quality_seo_score is not None
        and article.quality_geo_score is not None
        and article.quality_lighthouse_score is not None
    )


def _generated_score_incomplete_rows(db: Session) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            select(Article, BloggerPost)
            .join(BloggerPost, BloggerPost.article_id == Article.id)
            .order_by(Article.id.asc())
        )
        .all()
    )
    output: list[dict[str, Any]] = []
    for article, post in rows:
        if _score_complete_article(article):
            continue
        output.append(
            {
                "article_id": article.id,
                "job_id": article.job_id,
                "blog_id": article.blog_id,
                "title": article.title,
                "published_url": post.published_url,
                "missing": {
                    "seo": article.quality_seo_score is None,
                    "geo": article.quality_geo_score is None,
                    "lighthouse": article.quality_lighthouse_score is None,
                },
            }
        )
    return output


def _generated_missing_live_post_rows(db: Session) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            select(Article)
            .outerjoin(BloggerPost, BloggerPost.article_id == Article.id)
            .where(BloggerPost.id.is_(None))
            .order_by(Article.id.asc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "article_id": row.id,
            "job_id": row.job_id,
            "blog_id": row.blog_id,
            "title": row.title,
            "published_url": None,
            "reason": "missing_live_blogger_post_row",
        }
        for row in rows
    ]


def _purge_generated_bundles(db: Session, rows: list[dict[str, Any]], *, execute: bool) -> dict[str, Any]:
    article_ids = sorted({int(row["article_id"]) for row in rows if row.get("article_id") is not None})
    job_ids = sorted({int(row["job_id"]) for row in rows if row.get("job_id") is not None})
    counts: dict[str, int] = {}
    if not execute:
        return {"article_ids": article_ids, "job_ids": job_ids, "deleted": counts}

    if article_ids:
        result = db.execute(
            update(ContentPlanSlot)
            .where(ContentPlanSlot.article_id.in_(article_ids))
            .values(article_id=None, status="score_pending", error_message="generated_final_row_removed_score_incomplete")
        )
        counts["content_plan_slots_article_unlinked"] = int(result.rowcount or 0)
        result = db.execute(
            update(ContentItem)
            .where(ContentItem.source_article_id.in_(article_ids))
            .values(source_article_id=None, lifecycle_status="score_pending", blocked_reason="score_pending")
        )
        counts["content_items_article_unlinked"] = int(result.rowcount or 0)
        for model, label in (
            (PublishQueueItem, "publish_queue_items"),
            (AIUsageEvent, "ai_usage_events_by_article"),
            (AnalyticsArticleFact, "analytics_article_facts_by_article"),
            (ManualImageSlot, "manual_image_slots_by_article"),
            (BloggerPost, "blogger_posts_by_article"),
            (Image, "images_by_article"),
        ):
            result = db.execute(delete(model).where(model.article_id.in_(article_ids)))
            counts[label] = int(result.rowcount or 0)

    if job_ids:
        result = db.execute(
            update(ContentPlanSlot)
            .where(ContentPlanSlot.job_id.in_(job_ids))
            .values(job_id=None, status="score_pending", error_message="generated_final_row_removed_score_incomplete")
        )
        counts["content_plan_slots_job_unlinked"] = int(result.rowcount or 0)
        result = db.execute(
            update(ContentItem)
            .where(ContentItem.job_id.in_(job_ids))
            .values(job_id=None, lifecycle_status="score_pending", blocked_reason="score_pending")
        )
        counts["content_items_job_unlinked"] = int(result.rowcount or 0)
        for model, label in (
            (AIUsageEvent, "ai_usage_events_by_job"),
            (AuditLog, "audit_logs"),
            (ManualImageSlot, "manual_image_slots_by_job"),
            (BloggerPost, "blogger_posts_by_job"),
            (Image, "images_by_job"),
        ):
            result = db.execute(delete(model).where(model.job_id.in_(job_ids)))
            counts[label] = counts.get(label, 0) + int(result.rowcount or 0)

    if article_ids:
        result = db.execute(delete(Article).where(Article.id.in_(article_ids)))
        counts["articles"] = int(result.rowcount or 0)
    if job_ids:
        result = db.execute(delete(Job).where(Job.id.in_(job_ids)))
        counts["jobs"] = int(result.rowcount or 0)
    return {"article_ids": article_ids, "job_ids": job_ids, "deleted": counts}


def _purge_orphan_generated_facts(db: Session, *, execute: bool) -> dict[str, Any]:
    rows = (
        db.execute(
            select(AnalyticsArticleFact)
            .where(AnalyticsArticleFact.source_type == "generated")
            .where(AnalyticsArticleFact.article_id.is_(None))
            .order_by(AnalyticsArticleFact.id.asc())
        )
        .scalars()
        .all()
    )
    fact_ids = [int(row.id) for row in rows]
    output = {
        "fact_ids": fact_ids,
        "sample": [
            {
                "fact_id": row.id,
                "blog_id": row.blog_id,
                "actual_url": row.actual_url,
                "status": row.status,
            }
            for row in rows[:20]
        ],
        "deleted": 0,
    }
    if execute and fact_ids:
        result = db.execute(delete(AnalyticsArticleFact).where(AnalyticsArticleFact.id.in_(fact_ids)))
        output["deleted"] = int(result.rowcount or 0)
    return output


def _refresh_ctr(db: Session, *, blog_ids: set[int]) -> list[dict[str, Any]]:
    results = []
    blogs = db.execute(select(Blog).where(Blog.id.in_(sorted(blog_ids))).order_by(Blog.id.asc())).scalars().all()
    for blog in blogs:
        try:
            results.append(refresh_search_console_ctr_cache(db, blog=blog, trigger_mode="manual_live_reconcile"))
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            results.append({"status": "failed", "blog_id": blog.id, "error": str(exc)})
    return results


def _sync_live_sources(db: Session, *, scope: str) -> dict[str, Any]:
    result: dict[str, Any] = {"scope": scope, "blogger": [], "cloudflare": None}
    if scope in {"all", "blogger", "travel", "mystery"}:
        query = select(Blog).where((Blog.blogger_blog_id.is_not(None)) | (Blog.blogger_url.is_not(None)))
        if scope == "travel":
            query = query.where(Blog.id.in_(sorted(TRAVEL_BLOG_IDS)))
        elif scope == "mystery":
            query = query.where((Blog.profile_key == "world_mystery") | (Blog.content_category == "mystery"))
        blogs = db.execute(query.order_by(Blog.id.asc())).scalars().all()
        for blog in blogs:
            try:
                result["blogger"].append(sync_blogger_posts_for_blog(db, blog))
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                result["blogger"].append({"status": "failed", "blog_id": blog.id, "error": str(exc)})
    if scope in {"all", "cloudflare"}:
        try:
            result["cloudflare"] = sync_cloudflare_posts(db, include_non_published=False)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            result["cloudflare"] = {"status": "failed", "error": str(exc)}
    return result


def _score_blogger_synced_rows(db: Session, *, execute: bool, limit: int | None) -> dict[str, Any]:
    rows = (
        db.execute(
            select(AnalyticsArticleFact, SyncedBloggerPost)
            .join(SyncedBloggerPost, SyncedBloggerPost.id == AnalyticsArticleFact.synced_post_id)
            .where(AnalyticsArticleFact.source_type == "synced")
            .where(AnalyticsArticleFact.status.in_(("published", "live")))
            .order_by(AnalyticsArticleFact.published_at.desc().nullslast(), AnalyticsArticleFact.id.desc())
        )
        .all()
    )
    candidates = [
        (fact, post)
        for fact, post in rows
        if fact.seo_score is None or fact.geo_score is None or fact.lighthouse_score is None
    ]
    if limit is not None:
        candidates = candidates[: max(limit, 0)]
    scored: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    touched: set[tuple[int, str]] = set()
    for fact, post in candidates:
        url = str(fact.actual_url or post.url or "").strip()
        if not url:
            pending.append({"fact_id": fact.id, "synced_post_id": post.id, "reason": "missing_url"})
            continue
        if execute and (fact.seo_score is None or fact.geo_score is None):
            payload = compute_seo_geo_scores(
                title=post.title,
                html_body=post.content_html,
                excerpt=post.excerpt_text,
                faq_section=[],
            )
            fact.seo_score = payload.get("seo_score")
            fact.geo_score = payload.get("geo_score")
        if execute and fact.lighthouse_score is None:
            try:
                audit = run_lighthouse_audit(url, form_factor="mobile")
                report_path = write_lighthouse_raw_report(
                    audit,
                    provider="blogger-synced",
                    identity=post.remote_post_id or post.id,
                    slug=post.title,
                )
                parsed = parse_lighthouse_report(audit.get("raw_report") or {})
                fact.lighthouse_score = parsed.get("lighthouse_score")
                fact.lighthouse_accessibility_score = parsed.get("accessibility_score")
                fact.lighthouse_best_practices_score = parsed.get("best_practices_score")
                fact.lighthouse_seo_score = parsed.get("seo_score")
                scored.append({"fact_id": fact.id, "url": url, "lighthouse": fact.lighthouse_score, "report_path": str(report_path)})
            except Exception as exc:  # noqa: BLE001
                pending.append({"fact_id": fact.id, "url": url, "reason": str(exc)})
                continue
        month = _month_key(fact.published_at)
        if month:
            touched.add((fact.blog_id, month))
    if execute:
        for blog_id, month in sorted(touched):
            rebuild_blog_month_rollup(db, blog_id, month, commit=False)
    return {"candidates": len(candidates), "scored": scored, "score_pending": pending}


def _score_cloudflare_rows(db: Session, *, execute: bool, limit: int | None) -> dict[str, Any]:
    rows = (
        db.execute(
            select(SyncedCloudflarePost)
            .where(SyncedCloudflarePost.status.in_(("published", "live")))
            .where(
                (SyncedCloudflarePost.lighthouse_score.is_(None))
                | (SyncedCloudflarePost.seo_score.is_(None))
                | (SyncedCloudflarePost.geo_score.is_(None))
            )
            .order_by(SyncedCloudflarePost.published_at.desc().nullslast(), SyncedCloudflarePost.id.desc())
        )
        .scalars()
        .all()
    )
    if limit is not None:
        rows = rows[: max(limit, 0)]
    scored: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for row in rows:
        url = str(row.url or "").strip()
        if not url:
            pending.append({"id": row.id, "remote_post_id": row.remote_post_id, "reason": "missing_url"})
            continue
        if execute and row.lighthouse_score is None:
            try:
                audit = run_lighthouse_audit(url, form_factor="mobile")
                report_path = write_lighthouse_raw_report(
                    audit,
                    provider="cloudflare",
                    identity=row.remote_post_id or row.id,
                    slug=row.slug or row.title,
                )
                parsed = parse_lighthouse_report(audit.get("raw_report") or {})
                row.lighthouse_score = parsed.get("lighthouse_score")
                row.lighthouse_accessibility_score = parsed.get("accessibility_score")
                row.lighthouse_best_practices_score = parsed.get("best_practices_score")
                row.lighthouse_seo_score = parsed.get("seo_score")
                row.lighthouse_payload = {
                    "status": "ok",
                    "measurement_source": "google_pagespeed_insights_lighthouse",
                    "scores": parsed,
                    "report_path": str(report_path),
                    "audited_at": datetime.now(timezone.utc).isoformat(),
                }
                row.lighthouse_last_audited_at = datetime.now(timezone.utc)
                scored.append({"id": row.id, "url": url, "lighthouse": row.lighthouse_score, "report_path": str(report_path)})
            except Exception as exc:  # noqa: BLE001
                pending.append({"id": row.id, "url": url, "reason": str(exc)})
                continue
    return {"candidates": len(rows), "scored": scored, "score_pending": pending}


def _final_audit(db: Session) -> dict[str, Any]:
    generated_incomplete = _generated_score_incomplete_rows(db)
    blogger_missing = db.execute(
        select(AnalyticsArticleFact)
        .where(AnalyticsArticleFact.status.in_(("published", "live")))
        .where(
            (AnalyticsArticleFact.seo_score.is_(None))
            | (AnalyticsArticleFact.geo_score.is_(None))
            | (AnalyticsArticleFact.lighthouse_score.is_(None))
        )
        .order_by(AnalyticsArticleFact.id.asc())
    ).scalars().all()
    cloudflare_missing = db.execute(
        select(SyncedCloudflarePost)
        .where(SyncedCloudflarePost.status.in_(("published", "live")))
        .where(
            (SyncedCloudflarePost.seo_score.is_(None))
            | (SyncedCloudflarePost.geo_score.is_(None))
            | (SyncedCloudflarePost.lighthouse_score.is_(None))
        )
        .order_by(SyncedCloudflarePost.id.asc())
    ).scalars().all()
    return {
        "generated_score_incomplete_count": len(generated_incomplete),
        "generated_score_incomplete_sample": generated_incomplete[:20],
        "blogger_fact_score_incomplete_count": len(blogger_missing),
        "blogger_fact_score_incomplete_sample": [
            {
                "fact_id": row.id,
                "blog_id": row.blog_id,
                "source_type": row.source_type,
                "url": row.actual_url,
                "missing": {
                    "seo": row.seo_score is None,
                    "geo": row.geo_score is None,
                    "lighthouse": row.lighthouse_score is None,
                },
            }
            for row in blogger_missing[:20]
        ],
        "cloudflare_score_incomplete_count": len(cloudflare_missing),
        "cloudflare_score_incomplete_sample": [
            {
                "id": row.id,
                "remote_post_id": row.remote_post_id,
                "url": row.url,
                "missing": {
                    "seo": row.seo_score is None,
                    "geo": row.geo_score is None,
                    "lighthouse": row.lighthouse_score is None,
                },
            }
            for row in cloudflare_missing[:20]
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reconcile final DB rows from live posts and completed scores.")
    parser.add_argument("--execute", action="store_true", help="Apply cleanup/sync/scoring changes.")
    parser.add_argument("--scope", choices=["all", "blogger", "travel", "mystery", "cloudflare"], default="all")
    parser.add_argument("--skip-sync", action="store_true")
    parser.add_argument("--skip-score", action="store_true")
    parser.add_argument("--score-limit", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload: dict[str, Any] = {
        "status": "ok",
        "mode": "execute" if args.execute else "dry_run",
        "scope": args.scope,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    with SessionLocal() as db:
        before = _generated_score_incomplete_rows(db)
        payload["generated_score_incomplete_before"] = before
        payload["purge_generated"] = _purge_generated_bundles(db, before, execute=args.execute)
        missing_live_post = _generated_missing_live_post_rows(db)
        payload["generated_missing_live_post_before"] = missing_live_post
        payload["purge_missing_live_post"] = _purge_generated_bundles(db, missing_live_post, execute=args.execute)
        payload["purge_orphan_generated_facts"] = _purge_orphan_generated_facts(db, execute=args.execute)
        if args.execute:
            db.commit()
        else:
            db.rollback()

        payload["sync"] = {"status": "skipped", "reason": "skip_sync"}
        if not args.skip_sync:
            payload["sync"] = _sync_live_sources(db, scope=args.scope)

        blog_ids = {
            int(row[0])
            for row in db.execute(
                select(Blog.id).where((Blog.blogger_blog_id.is_not(None)) | (Blog.blogger_url.is_not(None)))
            ).all()
        }
        payload["ctr_refresh"] = _refresh_ctr(db, blog_ids=blog_ids) if args.execute else []

        payload["score"] = {"status": "skipped", "reason": "skip_score"}
        if not args.skip_score:
            blogger_score = _score_blogger_synced_rows(db, execute=args.execute, limit=args.score_limit)
            cloudflare_score = _score_cloudflare_rows(db, execute=args.execute, limit=args.score_limit)
            payload["score"] = {"blogger": blogger_score, "cloudflare": cloudflare_score}
            if args.execute:
                db.commit()
            else:
                db.rollback()

        if args.execute:
            for blog_id, month in db.execute(
                select(AnalyticsArticleFact.blog_id, AnalyticsArticleFact.month)
                .where(AnalyticsArticleFact.month.is_not(None))
                .distinct()
            ).all():
                rebuild_blog_month_rollup(db, int(blog_id), str(month), commit=False)
            db.commit()

        payload["final_audit"] = _final_audit(db)

    payload["finished_at"] = datetime.now(timezone.utc).isoformat()
    report_path = _write_report(payload)
    payload["report_path"] = str(report_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0 if payload["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
