from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import selectinload


REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
RUNTIME_ENV_PATH = REPO_ROOT / "env" / "runtime.settings.env"
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"
DEFAULT_REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\travel")
TARGET_ARTICLE_IDS = (77, 382, 387, 383, 336, 384)


def _load_runtime_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = str(raw_line or "").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip("'").strip('"')


_load_runtime_env(RUNTIME_ENV_PATH)
os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL") or os.environ.get("BLOGGENT_DATABASE_URL") or DEFAULT_DATABASE_URL
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import AIUsageEvent, Article, AuditLog, BloggerPost, ContentItem, ContentPlanSlot, Image, Job, ManualImageSlot, PublishQueueItem  # noqa: E402


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _scalar_count(db, statement) -> int:
    value = db.execute(statement).scalar_one()
    return int(value or 0)


def _build_item(db, article: Article) -> dict[str, Any]:
    job_id = int(article.job_id)
    article_id = int(article.id)
    blogger_post = article.blogger_post
    counts = {
        "images": _scalar_count(db, select(func.count()).select_from(Image).where((Image.job_id == job_id) | (Image.article_id == article_id))),
        "blogger_posts": _scalar_count(
            db,
            select(func.count()).select_from(BloggerPost).where((BloggerPost.job_id == job_id) | (BloggerPost.article_id == article_id)),
        ),
        "audit_logs": _scalar_count(db, select(func.count()).select_from(AuditLog).where(AuditLog.job_id == job_id)),
        "ai_usage_events": _scalar_count(
            db,
            select(func.count()).select_from(AIUsageEvent).where((AIUsageEvent.job_id == job_id) | (AIUsageEvent.article_id == article_id)),
        ),
        "publish_queue_items": _scalar_count(db, select(func.count()).select_from(PublishQueueItem).where(PublishQueueItem.article_id == article_id)),
        "manual_image_slots": _scalar_count(
            db,
            select(func.count()).select_from(ManualImageSlot).where((ManualImageSlot.job_id == job_id) | (ManualImageSlot.article_id == article_id)),
        ),
        "content_plan_slots": _scalar_count(
            db,
            select(func.count()).select_from(ContentPlanSlot).where((ContentPlanSlot.article_id == article_id) | (ContentPlanSlot.job_id == job_id)),
        ),
        "content_items": _scalar_count(
            db,
            select(func.count()).select_from(ContentItem).where((ContentItem.source_article_id == article_id) | (ContentItem.job_id == job_id)),
        ),
    }
    linked_slots = (
        db.execute(
            select(ContentPlanSlot)
            .where((ContentPlanSlot.article_id == article_id) | (ContentPlanSlot.job_id == job_id))
            .order_by(ContentPlanSlot.id.asc())
        )
        .scalars()
        .all()
    )
    return {
        "article_id": article_id,
        "job_id": job_id,
        "blog_id": int(article.blog_id),
        "title": article.title,
        "published_url": blogger_post.published_url if blogger_post else None,
        "post_status": blogger_post.post_status.value if blogger_post and blogger_post.post_status else None,
        "job_status": article.job.status.value if article.job and article.job.status else None,
        "reason": "hard_delete_unpublished_travel_row",
        "deleted_relations_count": counts,
        "linked_content_plan_slots": [
            {
                "slot_id": int(slot.id),
                "article_id": slot.article_id,
                "job_id": slot.job_id,
                "status": slot.status,
                "category_key": slot.category_key,
            }
            for slot in linked_slots
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hard delete unpublished travel rows that never reached a live URL.")
    parser.add_argument("--report-root", default=str(DEFAULT_REPORT_ROOT))
    parser.add_argument("--report-prefix", default="travel-hard-delete-report")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    report_root = Path(str(args.report_root)).resolve()
    report_path = report_root / "reports" / f"{args.report_prefix}-{stamp}.json"

    with SessionLocal() as db:
        articles = (
            db.execute(
                select(Article)
                .where(Article.id.in_(list(TARGET_ARTICLE_IDS)))
                .options(
                    selectinload(Article.job),
                    selectinload(Article.blogger_post),
                    selectinload(Article.image),
                )
                .order_by(Article.blog_id.asc(), Article.id.asc())
            )
            .scalars()
            .all()
        )
        items = [_build_item(db, article) for article in articles]

        if args.execute:
            target_job_ids = [int(article.job_id) for article in articles]
            target_article_ids = [int(article.id) for article in articles]
            if target_article_ids or target_job_ids:
                db.execute(
                    update(ContentPlanSlot)
                    .where((ContentPlanSlot.article_id.in_(target_article_ids)) | (ContentPlanSlot.job_id.in_(target_job_ids)))
                    .values(article_id=None, job_id=None)
                )
                db.flush()
            if target_job_ids:
                db.execute(delete(Job).where(Job.id.in_(target_job_ids)))
            db.commit()

            remaining = {
                "jobs": _scalar_count(db, select(func.count()).select_from(Job).where(Job.id.in_(target_job_ids))),
                "articles": _scalar_count(db, select(func.count()).select_from(Article).where(Article.id.in_(target_article_ids))),
                "images": _scalar_count(db, select(func.count()).select_from(Image).where((Image.job_id.in_(target_job_ids)) | (Image.article_id.in_(target_article_ids)))),
                "blogger_posts": _scalar_count(
                    db,
                    select(func.count()).select_from(BloggerPost).where((BloggerPost.job_id.in_(target_job_ids)) | (BloggerPost.article_id.in_(target_article_ids))),
                ),
                "audit_logs": _scalar_count(db, select(func.count()).select_from(AuditLog).where(AuditLog.job_id.in_(target_job_ids))),
                "ai_usage_events": _scalar_count(
                    db,
                    select(func.count()).select_from(AIUsageEvent).where((AIUsageEvent.job_id.in_(target_job_ids)) | (AIUsageEvent.article_id.in_(target_article_ids))),
                ),
                "publish_queue_items": _scalar_count(db, select(func.count()).select_from(PublishQueueItem).where(PublishQueueItem.article_id.in_(target_article_ids))),
                "manual_image_slots": _scalar_count(
                    db,
                    select(func.count()).select_from(ManualImageSlot).where((ManualImageSlot.job_id.in_(target_job_ids)) | (ManualImageSlot.article_id.in_(target_article_ids))),
                ),
                "content_plan_slots_linked": _scalar_count(
                    db,
                    select(func.count()).select_from(ContentPlanSlot).where((ContentPlanSlot.article_id.in_(target_article_ids)) | (ContentPlanSlot.job_id.in_(target_job_ids))),
                ),
                "content_items": _scalar_count(
                    db,
                    select(func.count()).select_from(ContentItem).where((ContentItem.source_article_id.in_(target_article_ids)) | (ContentItem.job_id.in_(target_job_ids))),
                ),
            }
        else:
            remaining = None

    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "mode": "execute" if args.execute else "dry_run",
        "target_article_ids": list(TARGET_ARTICLE_IDS),
        "items": items,
        "remaining_after_execute": remaining,
    }

    if args.write_report:
        _write_json(report_path, report)

    print(
        json.dumps(
            {
                "report_path": str(report_path) if args.write_report else None,
                "mode": report["mode"],
                "target_count": len(items),
                "remaining_after_execute": remaining,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
