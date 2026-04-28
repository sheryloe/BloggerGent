from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.entities import (
    AIUsageEvent,
    Article,
    AuditLog,
    Blog,
    BloggerPost,
    Image,
    Job,
    PostStatus,
    PublishQueueItem,
    Topic,
)
from app.services.integrations.storage_service import clear_generated_storage
from app.services.providers.factory import get_blogger_provider


GENERATED_DATA_RESET_CONFIRM_TEXT = "RESET GENERATED DATA"


class GeneratedDataResetConfirmationError(ValueError):
    pass


def reset_generated_data(
    db: Session,
    *,
    dry_run: bool = True,
    confirm_text: str | None = None,
) -> dict:
    counts = _count_generated_data(db)
    if dry_run:
        return {
            **counts,
            "deleted_storage_files": 0,
            "dry_run": True,
            "executed": False,
            "confirm_required": GENERATED_DATA_RESET_CONFIRM_TEXT,
            "message": "dry_run=true 상태입니다. 삭제 대상 수만 계산했고 실제 데이터는 삭제하지 않았습니다.",
        }

    if (confirm_text or "").strip() != GENERATED_DATA_RESET_CONFIRM_TEXT:
        raise GeneratedDataResetConfirmationError(
            f"confirm_text must be exactly {GENERATED_DATA_RESET_CONFIRM_TEXT!r} when dry_run=false"
        )

    _delete_remote_draft_blogger_posts(db)
    db.execute(delete(AuditLog))
    db.execute(delete(AIUsageEvent))
    db.execute(delete(PublishQueueItem))
    db.execute(delete(BloggerPost))
    db.execute(delete(Image))
    db.execute(delete(Article))
    db.execute(delete(Job))
    db.execute(delete(Topic))
    db.commit()

    deleted_storage_files = clear_generated_storage()
    return {
        **counts,
        "deleted_storage_files": deleted_storage_files,
        "dry_run": False,
        "executed": True,
        "confirm_required": GENERATED_DATA_RESET_CONFIRM_TEXT,
        "message": "생성 작업, 글, 이미지, 토픽, 감사 로그를 모두 정리했습니다.",
    }


def _count_generated_data(db: Session) -> dict:
    return {
        "deleted_jobs": int(db.execute(select(func.count()).select_from(Job)).scalar_one()),
        "deleted_topics": int(db.execute(select(func.count()).select_from(Topic)).scalar_one()),
        "deleted_articles": int(db.execute(select(func.count()).select_from(Article)).scalar_one()),
        "deleted_images": int(db.execute(select(func.count()).select_from(Image)).scalar_one()),
        "deleted_blogger_posts": int(db.execute(select(func.count()).select_from(BloggerPost)).scalar_one()),
        "deleted_ai_usage_events": int(db.execute(select(func.count()).select_from(AIUsageEvent)).scalar_one()),
        "deleted_publish_queue_items": int(db.execute(select(func.count()).select_from(PublishQueueItem)).scalar_one()),
        "deleted_audit_logs": int(db.execute(select(func.count()).select_from(AuditLog)).scalar_one()),
    }


def _delete_remote_draft_blogger_posts(db: Session) -> None:
    draft_posts = db.execute(
        select(BloggerPost, Blog)
        .join(Blog, BloggerPost.blog_id == Blog.id)
        .where(BloggerPost.post_status != PostStatus.PUBLISHED)
    ).all()

    for blogger_post, blog in draft_posts:
        post_id = (blogger_post.blogger_post_id or "").strip()
        blog_id = (blog.blogger_blog_id or "").strip()
        if not post_id or not blog_id:
            continue
        try:
            provider = get_blogger_provider(db, blog)
            delete_post = getattr(provider, "delete_post", None)
            if callable(delete_post):
                delete_post(post_id)
        except Exception:
            pass
