from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import Article, BloggerPost, PostStatus, PublishMode, PublishQueueItem, WorkflowStageType
from app.services.blogger.blogger_editor_service import (
    BloggerEditorAutomationError,
    is_blogger_playwright_auto_sync_enabled,
    is_blogger_playwright_enabled,
    sync_article_search_description,
)
from app.services.content.article_service import build_article_r2_asset_object_key, ensure_article_editorial_labels
from app.services.content.html_assembler import assemble_article_html
from app.services.providers.factory import get_blogger_provider
from app.services.content.publish_trust_gate_service import enforce_publish_trust_requirements, ensure_trust_gate_appendix
from app.services.content.related_posts import find_related_articles
from app.services.integrations.settings_service import get_settings_map
from app.services.integrations.storage_service import ensure_existing_public_image_url, is_private_asset_url, save_html
from app.services.content.topic_guard_service import TopicGuardConflictError, rebuild_topic_memories_for_blog, validate_candidate_topic
from app.services.ops.usage_service import record_mock_usage

RETRY_REQUIRED_STATUS = "retry-required"
MANUAL_ACTION_STATUS = "needs-manual-action"
ACTIVE_PUBLISH_QUEUE_STATUSES = {"queued", "scheduled", "processing", RETRY_REQUIRED_STATUS}
RETRYABLE_PUBLISH_ERROR_CODES = {
    "Cloudflare R2 upload failed.": "cloudflare_r2_upload_failed",
    "Cloudflare integration asset upload failed.": "cloudflare_asset_upload_failed",
}
MAX_PUBLISH_RETRY_ATTEMPTS = 3
JA_ENGLISH_SLUG_PERMALINK_BLOG_ID = 37
JA_ENGLISH_SLUG_PERMALINK_MAX_LENGTH = 72
CTR_PERMALINK_MAX_LENGTH = 72
CTR_PERMALINK_SUFFIX = "Korea Travel Guide"
PERMALINK_TITLE_STOPWORDS = {"how", "to", "the", "and", "for", "with", "in", "on", "at", "of", "a", "an"}
JA_LABEL_TRAVEL = "旅行・お祭り"
JA_LABEL_LIFESTYLE = "ライフスタイル"


def _tokenize_ascii_terms(value: str | None) -> list[str]:
    tokens: list[str] = []
    for token in re.findall(r"[a-z0-9]+", str(value or "").lower()):
        if token in PERMALINK_TITLE_STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def _title_case_keywords(tokens: list[str]) -> str:
    words = [token.capitalize() for token in tokens if token]
    return " ".join(words).strip()


def _trim_title_at_word_boundary(value: str, max_length: int = JA_ENGLISH_SLUG_PERMALINK_MAX_LENGTH) -> str:
    text = str(value or "").strip()
    if len(text) <= max_length:
        return text
    trimmed = text[:max_length].rstrip()
    space_index = trimmed.rfind(" ")
    if space_index > 0:
        trimmed = trimmed[:space_index].rstrip()
    return trimmed


def build_english_slug_permalink_seed_title(
    article: Article,
    *,
    max_length: int = JA_ENGLISH_SLUG_PERMALINK_MAX_LENGTH,
) -> str:
    tokens = _tokenize_ascii_terms(article.slug)
    if not tokens:
        label_tokens: list[str] = []
        for label in list(article.labels or []):
            label_tokens.extend(_tokenize_ascii_terms(str(label)))
        tokens = label_tokens

    if tokens:
        keyword_part = _title_case_keywords(tokens)
        keyword_trimmed = _trim_title_at_word_boundary(keyword_part, max_length=max_length)
        if keyword_trimmed:
            return keyword_trimmed

    fallback = f"korea-travel-guide-{article.id}".strip()
    return _trim_title_at_word_boundary(fallback, max_length=max_length)


def build_ctr_permalink_title(
    article: Article,
    *,
    max_length: int = CTR_PERMALINK_MAX_LENGTH,
) -> str:
    """Build the temporary Blogger title used to force a CTR-safe permalink."""

    tokens = _tokenize_ascii_terms(getattr(article, "slug", ""))
    if not tokens:
        label_tokens: list[str] = []
        for label in list(getattr(article, "labels", []) or []):
            label_tokens.extend(_tokenize_ascii_terms(str(label)))
        tokens = label_tokens

    if not tokens:
        fallback = f"{CTR_PERMALINK_SUFFIX} {getattr(article, 'id', '')}".strip()
        return _trim_title_at_word_boundary(fallback, max_length=max_length)

    keywords = _title_case_keywords(tokens)
    suffix = CTR_PERMALINK_SUFFIX
    keyword_max_length = max(1, max_length - len(suffix) - 1)
    keyword_part = _trim_title_at_word_boundary(keywords, max_length=keyword_max_length)
    candidate = f"{keyword_part} {suffix}".strip()
    return _trim_title_at_word_boundary(candidate, max_length=max_length)


def _should_use_english_slug_permalink_seed(article: Article, existing_post: BloggerPost | None) -> bool:
    if int(article.blog_id or 0) != JA_ENGLISH_SLUG_PERMALINK_BLOG_ID:
        return False
    return existing_post is None


def _is_mojibake_label(value: str | None) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    if "�" in text:
        return True
    return bool(re.fullmatch(r"\?+", text))


def sanitize_blogger_labels_for_article(article: Article, labels: list[str] | None) -> list[str]:
    raw_labels = [str(item).strip() for item in list(labels or []) if str(item).strip()]
    clean_labels: list[str] = []
    seen: set[str] = set()
    removed_mojibake = False

    for label in raw_labels:
        if _is_mojibake_label(label):
            removed_mojibake = True
            continue
        lowered = label.casefold()
        if lowered in seen:
            continue
        seen.add(lowered)
        clean_labels.append(label)

    if int(article.blog_id or 0) == JA_ENGLISH_SLUG_PERMALINK_BLOG_ID:
        has_ja_anchor = any(label in {JA_LABEL_TRAVEL, JA_LABEL_LIFESTYLE} for label in clean_labels)
        if (removed_mojibake or not clean_labels) and not has_ja_anchor:
            if any(label.casefold() == "travel" for label in clean_labels):
                clean_labels.insert(0, JA_LABEL_TRAVEL)
            else:
                clean_labels.insert(0, JA_LABEL_LIFESTYLE)

    return clean_labels


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
    from app.services.ops.analytics_service import upsert_article_fact

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

    existing_post = article.blogger_post
    existing_status = existing_post.post_status if existing_post else None
    if existing_post and existing_status in {PostStatus.PUBLISHED, PostStatus.SCHEDULED}:
        raise ValueError("This article is already published or scheduled in Blogger.")

    labels = sanitize_blogger_labels_for_article(article, ensure_article_editorial_labels(db, article))
    if labels != list(article.labels or []):
        article.labels = list(labels)
        db.add(article)
        db.commit()
        db.refresh(article)
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
        if _should_use_english_slug_permalink_seed(article, existing_post) and hasattr(provider, "publish_draft"):
            permalink_seed_title = build_english_slug_permalink_seed_title(article)
            draft_summary, draft_payload = provider.publish(
                title=permalink_seed_title,
                content=assembled_html or article.html_article,
                labels=labels,
                meta_description=article.meta_description,
                slug=article.slug,
                publish_mode=PublishMode.DRAFT,
            )
            draft_post_id = str(draft_summary.get("id") or "").strip()
            if not draft_post_id:
                raise ValueError("Blogger draft post id is missing after permalink seed publish")
            publish_summary, publish_payload = provider.publish_draft(draft_post_id)
            update_summary, update_payload = provider.update_post(
                post_id=draft_post_id,
                title=article.title,
                content=assembled_html,
                labels=labels,
                meta_description=article.meta_description,
            )
            summary = update_summary or publish_summary
            raw_payload = {
                "draft_permalink_seed": draft_payload,
                "publish": publish_payload,
                "draft_title_restore": update_payload,
                "permalink_seed_title": permalink_seed_title,
                "permalink_source_slug": article.slug,
                "visible_title_preserved": article.title,
                "permalink_sequence": "seed_draft_then_publish_then_restore_title",
            }
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
    from app.services.content.content_ops_service import review_article_publish_state

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
