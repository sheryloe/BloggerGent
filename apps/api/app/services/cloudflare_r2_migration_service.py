from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import Article, LogLevel, PostStatus
from app.services.article_service import ensure_article_editorial_labels
from app.services.audit_service import add_log
from app.services.html_assembler import assemble_article_html
from app.services.providers.base import ProviderRuntimeError
from app.services.providers.factory import get_blogger_provider
from app.services.related_posts import find_related_articles
from app.services.settings_service import get_settings_map
from app.services.storage_service import (
    _resolve_cloudflare_integration_upload_configuration,
    _resolve_cloudflare_r2_configuration,
    build_cloudflare_r2_preview_url,
    delete_cloudflare_r2_asset,
    save_html,
    upload_binary_to_cloudflare_r2,
)

MIGRATION_STAGE = "cloudflare_r2_image_migration"


def _resolve_cloudflare_migration_configuration(values: dict[str, str]) -> tuple[str, str, bool]:
    account_id, bucket, access_key_id, secret_access_key, public_base_url, prefix = _resolve_cloudflare_r2_configuration(values)
    integration_base_url, integration_token = _resolve_cloudflare_integration_upload_configuration(values)

    direct_ready = bool(account_id and bucket and access_key_id and secret_access_key and public_base_url)
    integration_ready = bool(bucket and public_base_url and integration_base_url and integration_token)

    return public_base_url, prefix, (direct_ready or integration_ready)


def _parse_remote_datetime(value: str | None):
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    from datetime import datetime

    return datetime.fromisoformat(normalized)


def _article_uses_cloudflare_r2(article: Article) -> bool:
    image = article.image
    if not image:
        return False
    rendered_html = f"{article.assembled_html or ''}\n{article.html_article or ''}"
    image_filename = Path((image.file_path or "")).name.strip()
    if not image_filename and (image.public_url or "").strip():
        image_filename = Path((image.public_url or "").split("?")[0]).name.strip()

    has_cloudflare_transform = "/cdn-cgi/image/" in (image.public_url or "")
    if not has_cloudflare_transform and image_filename:
        has_cloudflare_transform = "/cdn-cgi/image/" in rendered_html and image_filename in rendered_html
    metadata = image.image_metadata or {}
    delivery = metadata.get("delivery") if isinstance(metadata, dict) else {}
    if isinstance(delivery, dict) and str(delivery.get("provider") or "").strip().lower() == "cloudflare_r2":
        return has_cloudflare_transform
    return has_cloudflare_transform


def _current_image_provider(article: Article) -> str:
    image = article.image
    if not image:
        return "unknown"
    metadata = image.image_metadata or {}
    delivery = metadata.get("delivery") if isinstance(metadata, dict) else {}
    if isinstance(delivery, dict):
        provider = str(delivery.get("provider") or "").strip().lower()
        if provider:
            return provider
    storage_provider = str(metadata.get("storage_provider") or "").strip().lower() if isinstance(metadata, dict) else ""
    if storage_provider:
        return storage_provider
    public_url = (image.public_url or "").lower()
    if "/cdn-cgi/image/" in public_url:
        return "cloudflare_r2"
    if "res.cloudinary.com" in public_url:
        return "cloudinary"
    if "github.io" in public_url:
        return "github_pages"
    return "local"


def _load_candidates(db: Session, *, blog_ids: set[int], limit: int) -> list[Article]:
    articles = (
        db.execute(
            select(Article)
            .where(Article.blog_id.in_(blog_ids))
            .options(
                selectinload(Article.blog),
                selectinload(Article.image),
                selectinload(Article.blogger_post),
                selectinload(Article.job),
            )
            .order_by(Article.created_at.desc())
        )
        .scalars()
        .unique()
        .all()
    )

    candidates: list[Article] = []
    for article in articles:
        if not article.image:
            continue
        if not (article.image.file_path or "").strip():
            continue
        if not (article.image.public_url or "").strip():
            continue
        if not ((article.assembled_html or "").strip() or (article.html_article or "").strip()):
            continue
        if not article.blogger_post or not (article.blogger_post.blogger_post_id or "").strip():
            continue
        candidates.append(article)
        if len(candidates) >= limit:
            break
    return candidates


def _resolve_provider_support(
    db: Session,
    article: Article,
    *,
    cache: dict[int, tuple[bool, Any | None, str]],
) -> tuple[bool, Any | None, str]:
    if article.blog_id in cache:
        return cache[article.blog_id]

    if not article.blog:
        result = (False, None, "Blog relation is missing")
        cache[article.blog_id] = result
        return result

    try:
        provider = get_blogger_provider(db, article.blog)
    except ProviderRuntimeError as exc:
        result = (False, None, exc.detail or exc.message)
        cache[article.blog_id] = result
        return result

    if not hasattr(provider, "update_post"):
        result = (False, None, "Resolved provider does not support update_post")
        cache[article.blog_id] = result
        return result

    result = (True, provider, "")
    cache[article.blog_id] = result
    return result


def _migration_item(article: Article, *, planned_public_url: str | None, status: str, message: str) -> dict:
    image = article.image
    return {
        "article_id": article.id,
        "title": article.title,
        "current_provider": _current_image_provider(article),
        "current_public_url": image.public_url if image else None,
        "planned_public_url": planned_public_url,
        "status": status,
        "message": message,
    }


def _apply_blogger_post_summary(article: Article, *, summary: dict, raw_payload: dict) -> None:
    if not article.blogger_post:
        return

    blogger_post = article.blogger_post
    published_at = _parse_remote_datetime(summary.get("published"))
    scheduled_for = _parse_remote_datetime(summary.get("scheduledFor"))
    post_status_value = summary.get("postStatus")
    if post_status_value:
        post_status = PostStatus(post_status_value)
    else:
        post_status = PostStatus.DRAFT if bool(summary.get("isDraft", True)) else PostStatus.PUBLISHED

    existing_payload = dict(blogger_post.response_payload or {})
    existing_payload["migration"] = raw_payload

    blogger_post.blog_id = article.blog_id
    blogger_post.article_id = article.id
    blogger_post.blogger_post_id = summary.get("id", blogger_post.blogger_post_id)
    blogger_post.published_url = summary.get("url", blogger_post.published_url or "")
    blogger_post.published_at = published_at
    blogger_post.is_draft = post_status == PostStatus.DRAFT
    blogger_post.post_status = post_status
    blogger_post.scheduled_for = scheduled_for
    blogger_post.response_payload = existing_payload


def _record_audit_log(
    db: Session,
    *,
    article: Article,
    level: LogLevel,
    message: str,
    payload: dict | None = None,
) -> None:
    add_log(
        db,
        job=article.job,
        stage=MIGRATION_STAGE,
        message=message,
        level=level,
        payload=payload or {},
    )


def run_cloudflare_r2_image_migration(
    db: Session,
    *,
    blog_ids: set[int],
    mode: str,
    limit: int,
) -> dict:
    candidates = _load_candidates(db, blog_ids=blog_ids, limit=limit)
    values = get_settings_map(db)
    public_base_url, prefix, cloudflare_ready = _resolve_cloudflare_migration_configuration(values)
    execute_mode = mode == "execute"

    provider_cache: dict[int, tuple[bool, Any | None, str]] = {}
    items: list[dict] = []
    processable_articles: list[tuple[Article, Any, str | None]] = []

    for article in candidates:
        image = article.image
        file_path = (image.file_path if image else "") or ""
        planned_public_url = (
            build_cloudflare_r2_preview_url(public_base_url=public_base_url, prefix=prefix, file_path=file_path)
            if public_base_url and file_path
            else None
        )
        local_file_exists = bool(file_path and Path(file_path).exists())
        supports_update, provider, provider_message = _resolve_provider_support(db, article, cache=provider_cache)

        if _article_uses_cloudflare_r2(article):
            items.append(_migration_item(article, planned_public_url=planned_public_url, status="skipped", message="Article already uses Cloudflare R2 delivery"))
            continue
        if not cloudflare_ready:
            items.append(_migration_item(article, planned_public_url=planned_public_url, status="skipped", message="Cloudflare R2 settings are incomplete"))
            continue
        if not local_file_exists:
            items.append(_migration_item(article, planned_public_url=planned_public_url, status="skipped", message="Local image file is missing"))
            continue
        if not supports_update:
            items.append(_migration_item(article, planned_public_url=planned_public_url, status="skipped", message=provider_message or "Resolved provider does not support update_post"))
            continue

        if not execute_mode:
            items.append(_migration_item(article, planned_public_url=planned_public_url, status="processable", message="Ready for Cloudflare R2 migration"))
            continue

        processable_articles.append((article, provider, planned_public_url))

    updated_count = 0
    failed_count = 0

    if execute_mode:
        for article, provider, planned_public_url in processable_articles:
            image = article.image
            blogger_post = article.blogger_post
            if not image or not blogger_post:
                failed_count += 1
                items.append(_migration_item(article, planned_public_url=planned_public_url, status="failed", message="Image or Blogger post relation is missing"))
                continue

            file_path = Path(image.file_path)
            old_public_url = image.public_url
            old_image_metadata = dict(image.image_metadata or {})
            old_assembled_html = article.assembled_html
            old_remote_html = old_assembled_html or article.html_article
            uploaded_object_key = ""
            updated_remote = False
            cleanup_message = ""
            revert_message = ""
            commit_warning = ""

            try:
                labels = ensure_article_editorial_labels(db, article)
                new_public_url, upload_payload, delivery_meta = upload_binary_to_cloudflare_r2(
                    db,
                    filename=file_path.name,
                    content=file_path.read_bytes(),
                )
                uploaded_object_key = str(upload_payload.get("object_key") or "").strip()

                image_metadata = dict(old_image_metadata)
                image_metadata["delivery"] = delivery_meta

                image.public_url = new_public_url
                image.image_metadata = image_metadata

                related_posts = find_related_articles(db, article)
                assembled_html = assemble_article_html(article, new_public_url, related_posts)

                summary, raw_payload = provider.update_post(
                    post_id=blogger_post.blogger_post_id,
                    title=article.title,
                    content=assembled_html,
                    labels=labels,
                    meta_description=article.meta_description,
                )
                updated_remote = True

                article.assembled_html = assembled_html
                _apply_blogger_post_summary(article, summary=summary, raw_payload=raw_payload if isinstance(raw_payload, dict) else {})
                db.add(image)
                db.add(article)
                db.add(blogger_post)
                db.commit()

                try:
                    save_html(slug=article.slug, html=assembled_html)
                except Exception as html_exc:  # noqa: BLE001
                    commit_warning = f"HTML snapshot save failed: {html_exc}"
                    _record_audit_log(
                        db,
                        article=article,
                        level=LogLevel.WARNING,
                        message="Cloudflare R2 migration completed but HTML snapshot save failed",
                        payload={"article_id": article.id, "public_url": new_public_url, "error": str(html_exc)},
                    )

                _record_audit_log(
                    db,
                    article=article,
                    level=LogLevel.INFO,
                    message="Migrated article image delivery to Cloudflare R2",
                    payload={"article_id": article.id, "old_public_url": old_public_url, "new_public_url": new_public_url, "blogger_post_id": blogger_post.blogger_post_id},
                )
                updated_count += 1
                items.append(_migration_item(article, planned_public_url=new_public_url, status="updated", message=commit_warning or "Cloudflare R2 migration completed"))
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                if updated_remote:
                    try:
                        provider.update_post(
                            post_id=blogger_post.blogger_post_id,
                            title=article.title,
                            content=old_remote_html,
                            labels=labels,
                            meta_description=article.meta_description,
                        )
                    except Exception as revert_exc:  # noqa: BLE001
                        revert_message = f"Remote revert failed: {revert_exc}"
                if uploaded_object_key:
                    try:
                        delete_cloudflare_r2_asset(db, object_key=uploaded_object_key)
                    except Exception as cleanup_exc:  # noqa: BLE001
                        cleanup_message = f"Cloudflare R2 cleanup failed: {cleanup_exc}"

                image.public_url = old_public_url
                image.image_metadata = old_image_metadata
                article.assembled_html = old_assembled_html

                _record_audit_log(
                    db,
                    article=article,
                    level=LogLevel.ERROR,
                    message="Cloudflare R2 migration failed",
                    payload={
                        "article_id": article.id,
                        "old_public_url": old_public_url,
                        "planned_public_url": planned_public_url,
                        "error": str(exc),
                        "remote_revert": revert_message,
                        "cleanup": cleanup_message,
                    },
                )
                failed_count += 1
                items.append(_migration_item(article, planned_public_url=planned_public_url, status="failed", message=str(exc)))

    processable_count = sum(1 for item in items if item["status"] == "processable") + (len(processable_articles) if execute_mode else 0)
    skipped_count = sum(1 for item in items if item["status"] == "skipped")

    return {
        "mode": mode,
        "candidate_count": len(candidates),
        "processable_count": processable_count,
        "skipped_count": skipped_count,
        "updated_count": updated_count,
        "failed_count": failed_count,
        "items": items,
    }
