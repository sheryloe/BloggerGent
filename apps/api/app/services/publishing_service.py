from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import Article, BloggerPost, PostStatus, PublishMode, PublishQueueItem, WorkflowStageType
from app.services.blogger_editor_service import (
    BloggerEditorAutomationError,
    is_blogger_playwright_auto_sync_enabled,
    is_blogger_playwright_enabled,
    sync_article_search_description,
)
from app.services.article_service import build_article_r2_asset_object_key, ensure_article_editorial_labels
from app.services.html_assembler import assemble_article_html
from app.services.providers.factory import get_blogger_provider
from app.services.publish_trust_gate_service import enforce_publish_trust_requirements, ensure_trust_gate_appendix
from app.services.related_posts import find_related_articles
from app.services.settings_service import get_settings_map
from app.services.storage_service import ensure_existing_public_image_url, is_private_asset_url, save_html
from app.services.topic_guard_service import TopicGuardConflictError, rebuild_topic_memories_for_blog, validate_candidate_topic
from app.services.usage_service import record_mock_usage

RETRY_REQUIRED_STATUS = "retry-required"
MANUAL_ACTION_STATUS = "needs-manual-action"
ACTIVE_PUBLISH_QUEUE_STATUSES = {"queued", "scheduled", "processing", RETRY_REQUIRED_STATUS}
RETRYABLE_PUBLISH_ERROR_CODES = {
    "Cloudflare R2 upload failed.": "cloudflare_r2_upload_failed",
    "Cloudflare integration asset upload failed.": "cloudflare_asset_upload_failed",
}
MAX_PUBLISH_RETRY_ATTEMPTS = 3


def load_article_for_publish(db: Session, article_id: int) -> Article | None:
    return db.execute(
        select(Article)
        .where(Article.id == article_id)
        .options(
            selectinload(Article.blog),
            selectinload(Article.image),
            selectinload(Article.blogger_post),
            selectinload(Article.ai_usage_events),
            selectinload(Article.publish_queue_items),
        )
    ).scalar_one_or_none()


def _parse_remote_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    return datetime.fromisoformat(normalized)


def resolve_request_datetime(db: Session, value: datetime | None) -> datetime | None:
    if value is None:
        return None
    timezone_name = get_settings_map(db).get("schedule_timezone", "Asia/Seoul")
    tz = ZoneInfo(timezone_name)
    if value.tzinfo is None:
        return value.replace(tzinfo=tz).astimezone(timezone.utc)
    return value.astimezone(timezone.utc)


def _record_search_description_sync(
    db: Session,
    *,
    article: Article,
    status: str,
    message: str,
    editor_url: str | None = None,
    cdp_url: str | None = None,
) -> None:
    if not article.blogger_post:
        return

    payload = dict(article.blogger_post.response_payload or {})
    payload["search_description_sync"] = {
        "status": status,
        "message": message,
        "editor_url": editor_url or "",
        "cdp_url": cdp_url or "",
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    article.blogger_post.response_payload = payload
    db.add(article.blogger_post)
    db.commit()
    db.refresh(article.blogger_post)


def upsert_article_blogger_post(
    db: Session,
    *,
    article: Article,
    summary: dict,
    raw_payload: dict,
) -> BloggerPost:
    blogger_post = article.blogger_post or db.execute(
        select(BloggerPost).where(BloggerPost.job_id == article.job_id)
    ).scalar_one_or_none()
    published_at = _parse_remote_datetime(summary.get("published"))
    scheduled_for = _parse_remote_datetime(summary.get("scheduledFor"))

    post_status_value = summary.get("postStatus")
    if post_status_value:
        post_status = PostStatus(post_status_value)
    else:
        post_status = PostStatus.DRAFT if bool(summary.get("isDraft", True)) else PostStatus.PUBLISHED

    payload = {
        "blog_id": article.blog_id,
        "article_id": article.id,
        "blogger_post_id": summary.get("id", f"article-{article.id}"),
        "published_url": summary.get("url", ""),
        "published_at": published_at,
        "is_draft": post_status == PostStatus.DRAFT,
        "post_status": post_status,
        "scheduled_for": scheduled_for,
        "response_payload": raw_payload,
    }

    if blogger_post:
        for key, value in payload.items():
            setattr(blogger_post, key, value)
    else:
        blogger_post = BloggerPost(job_id=article.job_id, **payload)
        db.add(blogger_post)

    db.commit()
    db.refresh(blogger_post)
    from app.services.analytics_service import upsert_article_fact

    upsert_article_fact(db, article.id)
    return blogger_post


def refresh_article_public_image(db: Session, article: Article) -> str | None:
    image = article.image
    if not image:
        return None
    if not (image.file_path or "").strip():
        return image.public_url

    object_key = build_article_r2_asset_object_key(
        article,
        asset_role="hero-refresh",
    )
    public_url, delivery_meta = ensure_existing_public_image_url(
        db,
        file_path=image.file_path,
        object_key=object_key,
    )
    metadata = dict(image.image_metadata or {})
    metadata["delivery"] = delivery_meta

    image.public_url = public_url
    image.image_metadata = metadata
    db.add(image)
    db.commit()
    db.refresh(image)
    return public_url


def rebuild_article_html(db: Session, article: Article, hero_image_url: str) -> str:
    db.refresh(article, attribute_names=["blog", "image"])
    related_posts = find_related_articles(db, article)
    assembled_html = assemble_article_html(article, hero_image_url, related_posts)
    article.assembled_html = assembled_html
    db.add(article)
    db.commit()
    db.refresh(article)
    save_html(slug=article.slug, html=assembled_html)
    return assembled_html


def get_active_publish_queue_item(article: Article) -> PublishQueueItem | None:
    return next((item for item in article.publish_queue_items or [] if item.status in ACTIVE_PUBLISH_QUEUE_STATUSES), None)


def _publish_interval_seconds(db: Session) -> int:
    settings_map = get_settings_map(db)
    try:
        value = int((settings_map.get("publish_min_interval_seconds") or "60").strip())
    except (TypeError, ValueError, AttributeError):
        return 60
    return max(0, value)


def _next_available_publish_time(db: Session, *, blog_id: int, requested_time: datetime) -> datetime:
    interval_seconds = _publish_interval_seconds(db)
    latest_queue_item = db.execute(
        select(PublishQueueItem)
        .where(
            PublishQueueItem.blog_id == blog_id,
            PublishQueueItem.status.in_(["queued", "scheduled", "processing", RETRY_REQUIRED_STATUS, "completed"]),
        )
        .order_by(PublishQueueItem.not_before.desc(), PublishQueueItem.completed_at.desc(), PublishQueueItem.id.desc())
    ).scalars().first()
    anchor = requested_time
    if latest_queue_item:
        if latest_queue_item.status == "completed" and latest_queue_item.completed_at:
            anchor = max(anchor, latest_queue_item.completed_at + timedelta(seconds=interval_seconds))
        else:
            anchor = max(anchor, latest_queue_item.not_before + timedelta(seconds=interval_seconds))
    return anchor


def enqueue_publish_request(
    db: Session,
    *,
    article: Article,
    mode: str,
    scheduled_for: datetime | None,
) -> PublishQueueItem:
    if not article.blog or not (article.blog.blogger_blog_id or "").strip():
        raise ValueError("Blogger blog is not connected for this article")
    if article.blogger_post and article.blogger_post.post_status in {PostStatus.PUBLISHED, PostStatus.SCHEDULED}:
        raise ValueError("This article is already published or scheduled in Blogger.")
    if get_active_publish_queue_item(article):
        raise ValueError("A publish request is already queued for this article.")

    labels = ensure_article_editorial_labels(db, article)
    requested_time = scheduled_for or datetime.now(timezone.utc)
    not_before = _next_available_publish_time(db, blog_id=article.blog_id, requested_time=requested_time)
    validate_candidate_topic(
        db,
        blog_id=article.blog_id,
        title=article.title,
        excerpt=article.excerpt,
        labels=labels,
        content_html=article.assembled_html or article.html_article,
        target_datetime=not_before,
    )

    queue_item = PublishQueueItem(
        article_id=article.id,
        blog_id=article.blog_id,
        requested_mode=mode,
        scheduled_for=scheduled_for,
        not_before=not_before,
        status="scheduled" if scheduled_for else "queued",
        response_payload={
            "mode": mode,
            "scheduled_for": scheduled_for.isoformat() if scheduled_for else None,
            "not_before": not_before.isoformat(),
        },
    )
    db.add(queue_item)
    db.commit()
    db.refresh(queue_item)
    return queue_item


def _finalize_search_description_sync(db: Session, article: Article) -> None:
    if (
        article.blogger_post
        and article.blogger_post.post_status == PostStatus.PUBLISHED
        and is_blogger_playwright_enabled(db)
        and is_blogger_playwright_auto_sync_enabled(db)
    ):
        try:
            sync_result = sync_article_search_description(db, article)
            _record_search_description_sync(
                db,
                article=article,
                status=sync_result.status,
                message=sync_result.message,
                editor_url=sync_result.editor_url,
                cdp_url=sync_result.cdp_url,
            )
        except BloggerEditorAutomationError as exc:
            _record_search_description_sync(
                db,
                article=article,
                status="error",
                message=exc.message,
            )


def perform_publish_now(db: Session, *, article: Article, queue_item: PublishQueueItem | None = None) -> Article:
    if not article.blog or not (article.blog.blogger_blog_id or "").strip():
        raise ValueError("Blogger blog is not connected for this article")

    labels = ensure_article_editorial_labels(db, article)
    target_publish_datetime = datetime.now(timezone.utc)
    validate_candidate_topic(
        db,
        blog_id=article.blog_id,
        title=article.title,
        excerpt=article.excerpt,
        labels=labels,
        content_html=article.assembled_html or article.html_article,
        target_datetime=target_publish_datetime,
    )

    hero_image_url = refresh_article_public_image(db, article) or (article.image.public_url if article.image else "")
    assembled_html = rebuild_article_html(db, article, hero_image_url)
    if not (assembled_html or "").strip():
        raise ValueError("Assembled HTML is missing for this article")
    assembled_html, trust_assessment = ensure_trust_gate_appendix(assembled_html)
    if assembled_html != (article.assembled_html or "").strip():
        article.assembled_html = assembled_html
        db.add(article)
        db.commit()
        db.refresh(article)
    enforce_publish_trust_requirements(
        assembled_html,
        context=f"publish_queue_article_{article.id}",
    )

    provider = get_blogger_provider(db, article.blog)
    if getattr(provider, "access_token", "") and is_private_asset_url(hero_image_url):
        raise ValueError(
            "The hero image is still private. Configure a public asset base URL, Cloudflare R2, or Cloudinary first."
        )

    existing_post = article.blogger_post
    existing_status = existing_post.post_status if existing_post else None
    if existing_post and existing_status in {PostStatus.PUBLISHED, PostStatus.SCHEDULED}:
        raise ValueError("This article is already published or scheduled in Blogger.")

    if existing_post and hasattr(provider, "update_post"):
        update_summary, update_payload = provider.update_post(
            post_id=existing_post.blogger_post_id,
            title=article.title,
            content=assembled_html,
            labels=labels,
            meta_description=article.meta_description,
        )
        if existing_post.is_draft and hasattr(provider, "publish_draft"):
            publish_summary, publish_payload = provider.publish_draft(existing_post.blogger_post_id)
            summary = publish_summary
            raw_payload = {"update": update_payload, "publish": publish_payload}
        else:
            summary = update_summary
            raw_payload = update_payload
    else:
        summary, raw_payload = provider.publish(
            title=article.title,
            content=assembled_html or article.html_article,
            labels=labels,
            meta_description=article.meta_description,
            slug=article.slug,
            publish_mode=PublishMode.PUBLISH,
        )

    upsert_article_blogger_post(db, article=article, summary=summary, raw_payload=raw_payload)
    rebuild_topic_memories_for_blog(db, article.blog)

    provider_name = "mock_blogger" if type(provider).__name__.startswith("Mock") else "blogger"
    endpoint = "mock:publish" if provider_name == "mock_blogger" else "blogger:publish"
    record_mock_usage(
        db,
        blog_id=article.blog_id,
        job_id=article.job_id,
        article_id=article.id,
        stage_type=WorkflowStageType.PUBLISHING.value,
        provider_name=provider_name,
        provider_model="blogger-v3" if provider_name == "blogger" else "mock-blogger",
        endpoint=endpoint,
        raw_usage=raw_payload if isinstance(raw_payload, dict) else {},
    )

    refreshed = load_article_for_publish(db, article.id)
    if not refreshed:
        raise ValueError("Article not found after publishing")

    _finalize_search_description_sync(db, refreshed)
    from app.services.content_ops_service import review_article_publish_state

    review_article_publish_state(db, refreshed.id, trigger="publish_queue")

    if queue_item:
        queue_item.status = "completed"
        queue_item.last_error = None
        queue_item.completed_at = datetime.now(timezone.utc)
        queue_item.response_payload = {
            **dict(queue_item.response_payload or {}),
            "published_url": refreshed.blogger_post.published_url if refreshed.blogger_post else None,
            "completed_at": queue_item.completed_at.isoformat(),
        }
        db.add(queue_item)
        db.commit()

    return load_article_for_publish(db, article.id) or refreshed


def _classify_publish_error(exc: Exception) -> tuple[str, bool]:
    message = str(exc).strip()
    for marker, error_code in RETRYABLE_PUBLISH_ERROR_CODES.items():
        if marker in message:
            return error_code, True
    return "publish_failed", False


def _publish_retry_delay(attempt_count: int) -> timedelta:
    minutes = min(15 * max(attempt_count, 1), 180)
    return timedelta(minutes=minutes)


def process_publish_queue_item(db: Session, queue_item_id: int) -> PublishQueueItem | None:
    queue_item = db.execute(
        select(PublishQueueItem)
        .where(PublishQueueItem.id == queue_item_id)
        .options(
            selectinload(PublishQueueItem.article).selectinload(Article.blog),
            selectinload(PublishQueueItem.article).selectinload(Article.image),
            selectinload(PublishQueueItem.article).selectinload(Article.blogger_post),
            selectinload(PublishQueueItem.article).selectinload(Article.publish_queue_items),
            selectinload(PublishQueueItem.article).selectinload(Article.ai_usage_events),
        )
    ).scalar_one_or_none()
    if not queue_item:
        return None
    if queue_item.status in {"completed", "cancelled", MANUAL_ACTION_STATUS}:
        return queue_item
    if queue_item.not_before > datetime.now(timezone.utc):
        return queue_item

    queue_item.status = "processing"
    queue_item.attempt_count += 1
    db.add(queue_item)
    db.commit()
    db.refresh(queue_item)

    try:
        article = queue_item.article or load_article_for_publish(db, queue_item.article_id)
        if not article:
            raise ValueError("Article not found for publish queue item")
        perform_publish_now(db, article=article, queue_item=queue_item)
        return db.get(PublishQueueItem, queue_item.id)
    except (TopicGuardConflictError, ValueError) as exc:
        queue_item.status = "failed"
        queue_item.last_error = str(exc)
        queue_item.response_payload = {
            **dict(queue_item.response_payload or {}),
            "last_error_code": "publish_validation_failed",
            "last_error_cause": str(exc),
            "last_error_at": datetime.now(timezone.utc).isoformat(),
        }
        db.add(queue_item)
        db.commit()
        return queue_item
    except Exception as exc:  # noqa: BLE001
        error_code, retryable = _classify_publish_error(exc)
        queue_item.last_error = str(exc)
        payload = {
            **dict(queue_item.response_payload or {}),
            "last_error_code": error_code,
            "last_error_cause": str(exc),
            "last_error_at": datetime.now(timezone.utc).isoformat(),
        }
        if retryable:
            if queue_item.attempt_count < MAX_PUBLISH_RETRY_ATTEMPTS:
                retry_at = datetime.now(timezone.utc) + _publish_retry_delay(queue_item.attempt_count)
                queue_item.status = RETRY_REQUIRED_STATUS
                queue_item.not_before = retry_at
                payload.update(
                    {
                        "retry_state": RETRY_REQUIRED_STATUS,
                        "retry_attempt_count": queue_item.attempt_count,
                        "retry_scheduled_for": retry_at.isoformat(),
                        "manual_action_required": False,
                    }
                )
            else:
                queue_item.status = MANUAL_ACTION_STATUS
                payload.update(
                    {
                        "retry_state": MANUAL_ACTION_STATUS,
                        "retry_attempt_count": queue_item.attempt_count,
                        "manual_action_required": True,
                    }
                )
        else:
            queue_item.status = "failed"
            payload.update(
                {
                    "retry_state": "failed",
                    "retry_attempt_count": queue_item.attempt_count,
                    "manual_action_required": False,
                }
            )
        queue_item.response_payload = payload
        db.add(queue_item)
        db.commit()
        return queue_item


def process_publish_queue_batch(db: Session) -> dict:
    now = datetime.now(timezone.utc)
    due_items = db.execute(
        select(PublishQueueItem)
        .where(
            PublishQueueItem.status.in_(["queued", "scheduled", RETRY_REQUIRED_STATUS]),
            PublishQueueItem.not_before <= now,
        )
        .order_by(PublishQueueItem.not_before.asc(), PublishQueueItem.created_at.asc())
    ).scalars().all()

    processed_ids: list[int] = []
    seen_blogs: set[int] = set()
    for item in due_items:
        if item.blog_id in seen_blogs:
            continue
        seen_blogs.add(item.blog_id)
        processed_ids.append(item.id)
        process_publish_queue_item(db, item.id)

    return {
        "processed_count": len(processed_ids),
        "queue_item_ids": processed_ids,
    }
