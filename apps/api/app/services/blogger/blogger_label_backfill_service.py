from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.entities import Article, Blog, BloggerPost, PostStatus
from app.services.content.article_service import resolve_article_editorial_labels
from app.services.blogger.blogger_sync_service import sync_blogger_posts_for_blog
from app.services.integrations.google_sheet_service import sync_google_sheet_snapshot
from app.services.providers.factory import get_blogger_provider

DEFAULT_PROFILE_KEYS = ("korea_travel", "world_mystery")
ELIGIBLE_STATUSES = (PostStatus.PUBLISHED, PostStatus.SCHEDULED)


def _normalize_profile_keys(profile_keys: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in profile_keys or list(DEFAULT_PROFILE_KEYS):
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized or list(DEFAULT_PROFILE_KEYS)


def _reports_dir() -> Path:
    path = Path(settings.storage_root) / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _relative_report_path(file_name: str) -> str:
    return f"storage/reports/{file_name}"


def _write_report(*, execution_id: str, payload: dict[str, Any]) -> str:
    file_name = f"blogger-editorial-label-backfill-{execution_id}.json"
    report_path = _reports_dir() / file_name
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return _relative_report_path(file_name)


def _load_candidate_articles(db: Session, *, profile_keys: list[str]) -> list[Article]:
    return (
        db.execute(
            select(Article)
            .join(Blog, Blog.id == Article.blog_id)
            .join(BloggerPost, BloggerPost.article_id == Article.id)
            .where(
                Blog.profile_key.in_(profile_keys),
                Blog.blogger_blog_id.is_not(None),
                BloggerPost.post_status.in_(ELIGIBLE_STATUSES),
            )
            .options(
                selectinload(Article.blog),
                selectinload(Article.blogger_post),
            )
            .order_by(Article.blog_id.asc(), Article.created_at.asc(), Article.id.asc())
        )
        .scalars()
        .unique()
        .all()
    )


def _build_item(
    article: Article,
    *,
    current_labels: list[str] | None = None,
    target_labels: list[str],
    status: str,
    message: str,
) -> dict[str, Any]:
    return {
        "article_id": article.id,
        "blog_id": article.blog_id,
        "blog_name": article.blog.name if article.blog else "",
        "profile_key": article.blog.profile_key if article.blog else "",
        "title": article.title,
        "published_url": article.blogger_post.published_url if article.blogger_post else "",
        "blogger_post_id": article.blogger_post.blogger_post_id if article.blogger_post else "",
        "current_labels": list(current_labels if current_labels is not None else (article.labels or [])),
        "target_labels": target_labels,
        "editorial_category_key": article.editorial_category_key,
        "editorial_category_label": article.editorial_category_label,
        "status": status,
        "message": message,
    }


def dry_run_blogger_editorial_label_backfill(
    db: Session,
    *,
    profile_keys: list[str] | None = None,
) -> dict[str, Any]:
    resolved_profiles = _normalize_profile_keys(profile_keys)
    articles = _load_candidate_articles(db, profile_keys=resolved_profiles)
    items: list[dict[str, Any]] = []
    processable_count = 0

    for article in articles:
        current_labels = list(article.labels or [])
        resolved_key, resolved_label, target_labels = resolve_article_editorial_labels(article)
        needs_update = (
            current_labels != target_labels
            or (article.editorial_category_key or "") != (resolved_key or "")
            or (article.editorial_category_label or "") != (resolved_label or "")
        )
        item = _build_item(
            article,
            current_labels=current_labels,
            target_labels=target_labels,
            status="processable" if needs_update else "skipped",
            message="Editorial label update required." if needs_update else "Editorial labels are already normalized.",
        )
        item["resolved_editorial_category_key"] = resolved_key
        item["resolved_editorial_category_label"] = resolved_label
        items.append(item)
        if needs_update:
            processable_count += 1

    return {
        "status": "ok",
        "mode": "dry_run",
        "profile_keys": resolved_profiles,
        "candidate_count": len(articles),
        "processable_count": processable_count,
        "skipped_count": len(articles) - processable_count,
        "updated_count": 0,
        "failed_count": 0,
        "task_id": None,
        "report_path": None,
        "sync_results": [],
        "sheet_sync": None,
        "items": items,
    }


def execute_blogger_editorial_label_backfill(
    db: Session,
    *,
    profile_keys: list[str] | None = None,
    execution_id: str,
) -> dict[str, Any]:
    resolved_profiles = _normalize_profile_keys(profile_keys)
    articles = _load_candidate_articles(db, profile_keys=resolved_profiles)
    provider_cache: dict[int, Any] = {}
    touched_blog_ids: set[int] = set()
    items: list[dict[str, Any]] = []
    updated_count = 0
    failed_count = 0
    skipped_count = 0

    for article in articles:
        current_labels = list(article.labels or [])
        resolved_key, resolved_label, target_labels = resolve_article_editorial_labels(article)
        needs_update = (
            current_labels != target_labels
            or (article.editorial_category_key or "") != (resolved_key or "")
            or (article.editorial_category_label or "") != (resolved_label or "")
        )
        if not needs_update:
            skipped_count += 1
            items.append(
                _build_item(
                    article,
                    current_labels=current_labels,
                    target_labels=target_labels,
                    status="skipped",
                    message="Editorial labels are already normalized.",
                )
            )
            continue

        blog = article.blog
        blogger_post = article.blogger_post
        if not blog or not blogger_post:
            skipped_count += 1
            items.append(
                _build_item(
                    article,
                    current_labels=current_labels,
                    target_labels=target_labels,
                    status="skipped",
                    message="Article is missing blog or Blogger post linkage.",
                )
            )
            continue

        provider = provider_cache.get(blog.id)
        if provider is None:
            provider = get_blogger_provider(db, blog)
            provider_cache[blog.id] = provider

        try:
            summary, raw_payload = provider.update_post(
                post_id=blogger_post.blogger_post_id,
                title=article.title,
                content=article.assembled_html or article.html_article or "",
                labels=target_labels,
                meta_description=article.meta_description,
            )
            article.editorial_category_key = resolved_key
            article.editorial_category_label = resolved_label
            article.labels = target_labels
            blogger_post.response_payload = {
                **dict(blogger_post.response_payload or {}),
                "editorial_label_backfill": {
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "summary": summary,
                    "raw_payload": raw_payload if isinstance(raw_payload, dict) else {},
                },
            }
            db.add(article)
            db.add(blogger_post)
            db.commit()
            db.refresh(article)
            db.refresh(blogger_post)
            touched_blog_ids.add(blog.id)
            updated_count += 1
            items.append(
                _build_item(
                    article,
                    current_labels=current_labels,
                    target_labels=target_labels,
                    status="updated",
                    message="Updated Blogger labels and local article labels.",
                )
            )
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            failed_count += 1
            items.append(
                _build_item(
                    article,
                    current_labels=current_labels,
                    target_labels=target_labels,
                    status="failed",
                    message=str(exc),
                )
            )

    sync_results: list[dict[str, Any]] = []
    for blog_id in sorted(touched_blog_ids):
        blog = db.get(Blog, blog_id)
        if not blog:
            continue
        try:
            result = sync_blogger_posts_for_blog(db, blog)
            sync_results.append(
                {
                    "blog_id": blog.id,
                    "blog_name": blog.name,
                    "status": "ok",
                    "result": result,
                }
            )
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            sync_results.append(
                {
                    "blog_id": blog.id,
                    "blog_name": blog.name,
                    "status": "failed",
                    "error": str(exc),
                }
            )

    try:
        sheet_sync = sync_google_sheet_snapshot(db, initial=False)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        sheet_sync = {
            "status": "failed",
            "reason": "google_sheet_sync_failed",
            "detail": str(exc),
        }

    result = {
        "status": "ok" if failed_count == 0 else ("partial" if updated_count > 0 else "failed"),
        "mode": "execute",
        "profile_keys": resolved_profiles,
        "candidate_count": len(articles),
        "processable_count": updated_count + failed_count,
        "skipped_count": skipped_count,
        "updated_count": updated_count,
        "failed_count": failed_count,
        "task_id": execution_id,
        "sync_results": sync_results,
        "sheet_sync": sheet_sync,
        "items": items,
    }
    result["report_path"] = _write_report(execution_id=execution_id, payload=result)
    return result
