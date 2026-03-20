from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import Article, Blog, SyncedBloggerPost
from app.services.storage_service import build_public_image_variants


def _coerce_sort_datetime(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _generated_archive_item(article: Article) -> dict:
    blogger_post = article.blogger_post
    status = "generated"
    if blogger_post and blogger_post.published_url:
        status = getattr(blogger_post.post_status, "value", blogger_post.post_status) or (
            "draft" if blogger_post.is_draft else "published"
        )

    return {
        "source": "generated",
        "id": str(article.id),
        "blog_id": article.blog_id,
        "title": article.title,
        "excerpt": article.excerpt,
        "thumbnail_url": (
            build_public_image_variants(
                public_url=article.image.public_url,
                image_metadata=article.image.image_metadata,
                width=article.image.width,
                height=article.image.height,
            )["thumb_src"]
            if article.image
            else None
        ),
        "labels": article.labels or [],
        "published_url": blogger_post.published_url if blogger_post else None,
        "published_at": blogger_post.published_at if blogger_post else None,
        "updated_at": article.updated_at,
        "status": status,
        "content_html": article.assembled_html or article.html_article,
        "scheduled_for": blogger_post.scheduled_for if blogger_post else None,
    }


def _synced_archive_item(post: SyncedBloggerPost) -> dict:
    return {
        "source": "synced",
        "id": post.remote_post_id,
        "blog_id": post.blog_id,
        "title": post.title,
        "excerpt": post.excerpt_text,
        "thumbnail_url": post.thumbnail_url,
        "labels": post.labels or [],
        "published_url": post.url,
        "published_at": post.published_at,
        "updated_at": post.updated_at_remote or post.updated_at,
        "status": post.status or "live",
        "content_html": post.content_html,
        "scheduled_for": None,
    }


def _archive_sort_key(item: dict) -> tuple[datetime, datetime, str, str]:
    primary = _coerce_sort_datetime(item.get("published_at") or item.get("updated_at"))
    secondary = _coerce_sort_datetime(item.get("updated_at"))
    return (primary, secondary, item["source"], item["id"])


def list_blog_archive_page(db: Session, blog: Blog, *, page: int = 1, page_size: int = 20) -> dict:
    resolved_page = max(page, 1)
    resolved_page_size = max(1, min(page_size, 100))

    generated_articles = (
        db.execute(
            select(Article)
            .where(Article.blog_id == blog.id)
            .options(selectinload(Article.image), selectinload(Article.blogger_post))
        )
        .scalars()
        .unique()
        .all()
    )
    synced_posts = (
        db.execute(
            select(SyncedBloggerPost)
            .where(SyncedBloggerPost.blog_id == blog.id)
            .order_by(
                SyncedBloggerPost.published_at.desc().nullslast(),
                SyncedBloggerPost.updated_at_remote.desc().nullslast(),
                SyncedBloggerPost.id.desc(),
            )
        )
        .scalars()
        .all()
    )

    items = [_generated_archive_item(article) for article in generated_articles]
    items.extend(_synced_archive_item(post) for post in synced_posts)
    items.sort(key=_archive_sort_key, reverse=True)

    offset = (resolved_page - 1) * resolved_page_size
    paged_items = items[offset : offset + resolved_page_size]
    last_synced_at = db.execute(
        select(func.max(SyncedBloggerPost.synced_at)).where(SyncedBloggerPost.blog_id == blog.id)
    ).scalar_one()

    return {
        "items": paged_items,
        "total": len(items),
        "page": resolved_page,
        "page_size": resolved_page_size,
        "last_synced_at": last_synced_at,
    }
