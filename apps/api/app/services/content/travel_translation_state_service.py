from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from slugify import slugify
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import Article, Blog, ContentItem, PostStatus, SyncedBloggerPost
from app.services.content.travel_blog_policy import TRAVEL_BLOG_IDS, get_travel_blog_policy


DEFAULT_TRAVEL_REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\travel")
TRAVEL_SYNC_SOURCE_BLOG_ID = 34
TRAVEL_SYNC_TARGET_BLOG_IDS = (34, 36, 37)
TRAVEL_SYNC_ROLE_BY_BLOG_ID = {
    34: "source_en",
    36: "localized_es",
    37: "localized_ja",
}
TRAVEL_SYNC_STATUS_PRIORITY = {
    "published": 5,
    "scheduled": 4,
    "draft": 3,
    "sync_error": 2,
    "missing": 1,
}
TRAVEL_SYNC_EXPLICIT_ARTICLE_ID_KEYS = (
    "travel_sync_source_article_id",
    "translation_source_article_id",
    "source_article_id",
    "source_en_article_id",
)
TRAVEL_SYNC_EXPLICIT_SLUG_KEYS = (
    "travel_sync_source_slug",
    "translation_source_slug",
    "source_slug",
    "source_en_slug",
)


def build_travel_sync_group_key(article: Article) -> str:
    return f"travel-en-{int(article.id or 0)}"


def _report_path(report_root: Path, prefix: str) -> Path:
    output_root = report_root / "reports"
    output_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return output_root / f"{prefix}-{stamp}.json"


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _normalize_role_for_blog_id(blog_id: int) -> str | None:
    return TRAVEL_SYNC_ROLE_BY_BLOG_ID.get(int(blog_id or 0))


def _normalize_status(value: str | PostStatus | None) -> str:
    if isinstance(value, PostStatus):
        return value.value
    normalized = str(value or "").strip().lower()
    if normalized in {"draft", "scheduled", "published"}:
        return normalized
    return "draft"


def _choose_best_localized_article(
    articles: list[Article],
    *,
    synced_by_remote_id: dict[tuple[int, str], SyncedBloggerPost],
    synced_by_url: dict[tuple[int, str], SyncedBloggerPost],
) -> Article | None:
    if not articles:
        return None

    def _sort_key(article: Article) -> tuple[int, int, int]:
        status = _resolve_localized_status(
            article,
            synced_by_remote_id=synced_by_remote_id,
            synced_by_url=synced_by_url,
        )
        has_sync = int(status in {"published", "scheduled"})
        published_weight = TRAVEL_SYNC_STATUS_PRIORITY.get(status, 0)
        return (published_weight, has_sync, int(article.id or 0))

    return sorted(articles, key=_sort_key, reverse=True)[0]


def _resolve_synced_match(
    article: Article,
    *,
    synced_by_remote_id: dict[tuple[int, str], SyncedBloggerPost],
    synced_by_url: dict[tuple[int, str], SyncedBloggerPost],
) -> SyncedBloggerPost | None:
    blogger_post = getattr(article, "blogger_post", None)
    if blogger_post is None:
        return None
    remote_id = str(getattr(blogger_post, "blogger_post_id", "") or "").strip()
    if remote_id:
        matched = synced_by_remote_id.get((int(article.blog_id or 0), remote_id))
        if matched is not None:
            return matched
    published_url = str(getattr(blogger_post, "published_url", "") or "").strip()
    if published_url:
        return synced_by_url.get((int(article.blog_id or 0), published_url))
    return None


def _resolve_localized_status(
    article: Article | None,
    *,
    synced_by_remote_id: dict[tuple[int, str], SyncedBloggerPost],
    synced_by_url: dict[tuple[int, str], SyncedBloggerPost],
) -> str:
    if article is None:
        return "missing"
    blogger_post = getattr(article, "blogger_post", None)
    if blogger_post is None:
        return "draft"

    normalized_status = _normalize_status(getattr(blogger_post, "post_status", None))
    if normalized_status == "draft":
        return "draft"

    synced_match = _resolve_synced_match(
        article,
        synced_by_remote_id=synced_by_remote_id,
        synced_by_url=synced_by_url,
    )
    if synced_match is None:
        return "sync_error"
    return normalized_status


def _extract_explicit_source_article_id(
    article: Article,
    *,
    english_by_id: dict[int, Article],
    english_by_slug: dict[str, Article],
    content_item_source_by_job_id: dict[int, int],
) -> int | None:
    current_value = int(article.travel_sync_source_article_id or 0)
    if current_value in english_by_id:
        return current_value

    metadata = article.render_metadata if isinstance(article.render_metadata, dict) else {}
    for key in TRAVEL_SYNC_EXPLICIT_ARTICLE_ID_KEYS:
        raw_value = metadata.get(key)
        try:
            candidate = int(raw_value or 0)
        except (TypeError, ValueError):
            candidate = 0
        if candidate in english_by_id:
            return candidate

    for key in TRAVEL_SYNC_EXPLICIT_SLUG_KEYS:
        candidate_slug = slugify(str(metadata.get(key) or "").strip(), separator="-")
        if candidate_slug and candidate_slug in english_by_slug:
            return int(english_by_slug[candidate_slug].id)

    job_id = int(article.job_id or 0)
    if job_id > 0:
        candidate = int(content_item_source_by_job_id.get(job_id) or 0)
        if candidate in english_by_id:
            return candidate
    return None


def seed_article_travel_sync_fields(db: Session, article: Article, *, commit: bool = True) -> Article:
    if get_travel_blog_policy(blog_id=int(article.blog_id or 0)) is None:
        return article

    changed = False
    role = _normalize_role_for_blog_id(int(article.blog_id or 0))
    if role and article.travel_sync_role != role:
        article.travel_sync_role = role
        changed = True

    if int(article.blog_id or 0) == TRAVEL_SYNC_SOURCE_BLOG_ID:
        existing_group_key = str(article.travel_sync_group_key or "").strip()
        group_key = existing_group_key or build_travel_sync_group_key(article)
        if article.travel_sync_group_key != group_key:
            article.travel_sync_group_key = group_key
            changed = True
        current_source_id = int(article.travel_sync_source_article_id or 0)
        if current_source_id > 0:
            source_article = db.execute(select(Article).where(Article.id == current_source_id)).scalar_one_or_none()
            if (
                source_article is None
                or int(source_article.id or 0) == int(article.id or 0)
                or int(source_article.blog_id or 0) not in TRAVEL_BLOG_IDS
            ):
                article.travel_sync_source_article_id = None
                changed = True
        elif article.travel_sync_source_article_id is not None:
            article.travel_sync_source_article_id = None
            changed = True
    elif int(article.blog_id or 0) in {36, 37} and int(article.job_id or 0) > 0:
        source_article_id = db.execute(
            select(ContentItem.source_article_id)
            .where(ContentItem.job_id == article.job_id, ContentItem.source_article_id.is_not(None))
            .order_by(ContentItem.id.asc())
            .limit(1)
        ).scalar_one_or_none()
        source_article_id = int(source_article_id or 0)
        if source_article_id > 0:
            source_article = db.execute(select(Article).where(Article.id == source_article_id)).scalar_one_or_none()
            if source_article is not None and int(source_article.blog_id or 0) == TRAVEL_SYNC_SOURCE_BLOG_ID:
                group_key = str(source_article.travel_sync_group_key or build_travel_sync_group_key(source_article)).strip()
                if article.travel_sync_source_article_id != source_article.id:
                    article.travel_sync_source_article_id = source_article.id
                    changed = True
                if article.travel_sync_group_key != group_key:
                    article.travel_sync_group_key = group_key
                    changed = True

    if changed:
        db.add(article)
        if commit:
            db.commit()
            db.refresh(article)
        else:
            db.flush()
    return article


def resolve_travel_source_image_reuse(db: Session, article: Article) -> dict[str, Any] | None:
    if int(article.blog_id or 0) not in TRAVEL_BLOG_IDS:
        return None
    source_article_id = int(article.travel_sync_source_article_id or 0)
    if source_article_id <= 0:
        return None
    if source_article_id == int(article.id or 0):
        return None

    source_article = (
        db.execute(
            select(Article)
            .where(Article.id == source_article_id)
            .options(
                selectinload(Article.blog),
                selectinload(Article.image),
            )
        )
        .scalar_one_or_none()
    )
    if source_article is None or int(source_article.blog_id or 0) not in TRAVEL_BLOG_IDS:
        return None
    if source_article.image is None:
        return None

    public_url = str(source_article.image.public_url or "").strip()
    if not public_url:
        return None

    image_metadata = source_article.image.image_metadata if isinstance(source_article.image.image_metadata, dict) else {}
    return {
        "source_article_id": int(source_article.id),
        "source_blog_id": int(source_article.blog_id),
        "source_slug": str(source_article.slug or "").strip(),
        "public_url": public_url,
        "file_path": str(source_article.image.file_path or "").strip(),
        "provider": str(source_article.image.provider or "travel_source_reuse").strip() or "travel_source_reuse",
        "prompt": str(source_article.image.prompt or article.image_collage_prompt or "").strip(),
        "width": int(source_article.image.width or 0),
        "height": int(source_article.image.height or 0),
        "metadata": {
            **dict(image_metadata),
            "travel_sync_reused": True,
            "travel_sync_source_article_id": int(source_article.id),
            "travel_sync_source_blog_id": int(source_article.blog_id),
        },
    }


def refresh_travel_translation_state(
    db: Session,
    *,
    blog_ids: tuple[int, ...] = TRAVEL_SYNC_TARGET_BLOG_IDS,
    report_root: Path | None = DEFAULT_TRAVEL_REPORT_ROOT,
    write_report: bool = True,
) -> dict[str, Any]:
    scoped_blog_ids = tuple(sorted({int(blog_id) for blog_id in blog_ids if int(blog_id) in TRAVEL_BLOG_IDS}))
    if not scoped_blog_ids:
        raise ValueError("Travel translation refresh requires blog_id in {34, 36, 37}.")

    articles = (
        db.execute(
            select(Article)
            .join(Blog, Blog.id == Article.blog_id)
            .where(
                Article.blog_id.in_(scoped_blog_ids),
                Blog.profile_key == "korea_travel",
            )
            .options(
                selectinload(Article.blog),
                selectinload(Article.blogger_post),
                selectinload(Article.image),
            )
            .order_by(Article.id.asc())
        )
        .scalars()
        .all()
    )
    now = datetime.now(timezone.utc)

    synced_rows = (
        db.execute(select(SyncedBloggerPost).where(SyncedBloggerPost.blog_id.in_(scoped_blog_ids))).scalars().all()
    )
    synced_by_remote_id: dict[tuple[int, str], SyncedBloggerPost] = {}
    synced_by_url: dict[tuple[int, str], SyncedBloggerPost] = {}
    for row in synced_rows:
        remote_id = str(row.remote_post_id or "").strip()
        if remote_id:
            synced_by_remote_id[(int(row.blog_id or 0), remote_id)] = row
        url = str(row.url or "").strip()
        if url:
            synced_by_url[(int(row.blog_id or 0), url)] = row

    english_articles = [article for article in articles if int(article.blog_id or 0) == TRAVEL_SYNC_SOURCE_BLOG_ID]
    all_by_id = {int(article.id): article for article in articles}
    english_by_id = {int(article.id): article for article in english_articles}
    english_by_slug = {slugify(str(article.slug or "").strip(), separator="-"): article for article in english_articles}
    content_item_source_by_job_id = {
        int(job_id): int(source_article_id)
        for job_id, source_article_id in db.execute(
            select(ContentItem.job_id, ContentItem.source_article_id)
            .where(
                ContentItem.job_id.is_not(None),
                ContentItem.source_article_id.is_not(None),
            )
        ).all()
        if int(job_id or 0) > 0 and int(source_article_id or 0) in english_by_id
    }

    for article in english_articles:
        article.travel_sync_role = "source_en"
        article.travel_sync_group_key = str(article.travel_sync_group_key or "").strip() or build_travel_sync_group_key(article)
        current_source_id = int(article.travel_sync_source_article_id or 0)
        if (
            current_source_id <= 0
            or current_source_id == int(article.id or 0)
            or int(getattr(all_by_id.get(current_source_id), "blog_id", 0) or 0) not in TRAVEL_BLOG_IDS
        ):
            article.travel_sync_source_article_id = None
        article.travel_sync_last_checked_at = now
        db.add(article)

    localized_articles = [article for article in articles if int(article.blog_id or 0) in {36, 37}]
    for article in localized_articles:
        role = _normalize_role_for_blog_id(int(article.blog_id or 0))
        article.travel_sync_role = role
        source_article_id_from_en = _extract_explicit_source_article_id(
            article,
            english_by_id=english_by_id,
            english_by_slug=english_by_slug,
            content_item_source_by_job_id=content_item_source_by_job_id,
        )
        existing_source_id = int(article.travel_sync_source_article_id or 0)
        source_article_id = source_article_id_from_en
        if source_article_id is None and existing_source_id > 0 and existing_source_id in all_by_id:
            source_article_id = existing_source_id
        source_article = all_by_id.get(int(source_article_id or 0)) if source_article_id is not None else None
        existing_group_key = str(article.travel_sync_group_key or "").strip()
        resolved_group_key = existing_group_key
        if source_article is not None and not resolved_group_key:
            resolved_group_key = str(source_article.travel_sync_group_key or "").strip()
            if not resolved_group_key and int(source_article.blog_id or 0) == TRAVEL_SYNC_SOURCE_BLOG_ID:
                resolved_group_key = build_travel_sync_group_key(source_article)

        article.travel_sync_source_article_id = int(source_article_id) if source_article is not None else None
        article.travel_sync_group_key = resolved_group_key or None
        article.travel_sync_es_article_id = None
        article.travel_sync_ja_article_id = None
        article.travel_sync_es_status = None
        article.travel_sync_ja_status = None
        article.travel_all_languages_ready = False
        article.travel_sync_last_checked_at = now
        db.add(article)

    localized_by_group: dict[str, dict[int, list[Article]]] = defaultdict(lambda: defaultdict(list))
    for article in localized_articles:
        group_key = str(article.travel_sync_group_key or "").strip()
        if not group_key:
            continue
        localized_by_group[group_key][int(article.blog_id or 0)].append(article)

    master_rows: list[dict[str, Any]] = []
    ready_count = 0
    for article in english_articles:
        group_key = str(article.travel_sync_group_key or "").strip() or build_travel_sync_group_key(article)
        grouped_localized = localized_by_group.get(group_key, {})
        es_article = _choose_best_localized_article(
            grouped_localized.get(36, []),
            synced_by_remote_id=synced_by_remote_id,
            synced_by_url=synced_by_url,
        )
        ja_article = _choose_best_localized_article(
            grouped_localized.get(37, []),
            synced_by_remote_id=synced_by_remote_id,
            synced_by_url=synced_by_url,
        )
        es_status = _resolve_localized_status(
            es_article,
            synced_by_remote_id=synced_by_remote_id,
            synced_by_url=synced_by_url,
        )
        ja_status = _resolve_localized_status(
            ja_article,
            synced_by_remote_id=synced_by_remote_id,
            synced_by_url=synced_by_url,
        )
        article.travel_sync_es_article_id = int(es_article.id) if es_article is not None else None
        article.travel_sync_ja_article_id = int(ja_article.id) if ja_article is not None else None
        article.travel_sync_es_status = es_status
        article.travel_sync_ja_status = ja_status
        article.travel_all_languages_ready = es_status in {"scheduled", "published"} and ja_status in {"scheduled", "published"}
        article.travel_sync_last_checked_at = now
        db.add(article)
        if article.travel_all_languages_ready:
            ready_count += 1
        master_rows.append(
            {
                "article_id": int(article.id),
                "slug": str(article.slug or "").strip(),
                "group_key": group_key,
                "es_article_id": int(es_article.id) if es_article is not None else None,
                "ja_article_id": int(ja_article.id) if ja_article is not None else None,
                "es_status": es_status,
                "ja_status": ja_status,
                "all_languages_ready": bool(article.travel_all_languages_ready),
            }
        )

    db.commit()

    payload = {
        "generated_at": now.isoformat(timespec="seconds"),
        "blog_ids": list(scoped_blog_ids),
        "article_count": len(articles),
        "source_article_count": len(english_articles),
        "localized_article_count": len(localized_articles),
        "summary": {
            "ready_count": ready_count,
            "missing_es_count": sum(1 for row in master_rows if row["es_status"] == "missing"),
            "missing_ja_count": sum(1 for row in master_rows if row["ja_status"] == "missing"),
            "sync_error_es_count": sum(1 for row in master_rows if row["es_status"] == "sync_error"),
            "sync_error_ja_count": sum(1 for row in master_rows if row["ja_status"] == "sync_error"),
            "scheduled_or_published_es_count": sum(
                1 for row in master_rows if row["es_status"] in {"scheduled", "published"}
            ),
            "scheduled_or_published_ja_count": sum(
                1 for row in master_rows if row["ja_status"] in {"scheduled", "published"}
            ),
        },
        "masters": master_rows,
    }
    if write_report and report_root is not None:
        output_path = _report_path(Path(report_root).resolve(), "travel-translation-state")
        _write_report(output_path, payload)
        payload["report_path"] = str(output_path)
    return payload
