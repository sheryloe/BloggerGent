from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.services.cloudflare.cloudflare_sync_service import list_synced_cloudflare_posts

SEO_GEO_CTR_LIGHTHOUSE_LOW_THRESHOLD = 70.0
LIGHTHOUSE_ALERT_THRESHOLD = 70.0
REFACTOR_CANDIDATE_THRESHOLD = 80.0
SEOUL_TZ = ZoneInfo("Asia/Seoul")


def _default_month() -> str:
    return datetime.now(SEOUL_TZ).strftime("%Y-%m")


def _normalize_month(value: str | None) -> str:
    text = str(value or "").strip()
    if len(text) == 7 and text[4] == "-":
        return text
    return _default_month()


def _normalize_status(value: str | None) -> str | None:
    text = str(value or "").strip().lower()
    return text or None


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _score_value(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_low_score(row: dict[str, Any]) -> bool:
    for key in ("seo_score", "geo_score", "ctr", "lighthouse_score"):
        score = _score_value(row.get(key))
        if score is not None and score < SEO_GEO_CTR_LIGHTHOUSE_LOW_THRESHOLD:
            return True
    return False


def _is_lighthouse_below_70(row: dict[str, Any]) -> bool:
    score = _score_value(row.get("lighthouse_score"))
    return score is not None and score < LIGHTHOUSE_ALERT_THRESHOLD


def _is_refactor_candidate(row: dict[str, Any]) -> bool:
    for key in ("seo_score", "geo_score", "ctr", "lighthouse_score"):
        score = _score_value(row.get(key))
        if score is not None and score < REFACTOR_CANDIDATE_THRESHOLD:
            return True
    return False


def _month_matches(row: dict[str, Any], month: str) -> bool:
    published_at = _normalize_text(row.get("published_at"))
    return published_at.startswith(month)


def _resolve_category_slug(row: dict[str, Any]) -> str | None:
    value = _normalize_text(row.get("canonical_category_slug") or row.get("category_slug"))
    return value or None


def _resolve_category_name(row: dict[str, Any]) -> str | None:
    value = _normalize_text(
        row.get("canonical_category_name")
        or row.get("category_name")
        or row.get("canonical_category_slug")
        or row.get("category_slug")
    )
    return value or None


def _row_matches(
    row: dict[str, Any],
    *,
    status: str | None,
    query: str | None,
    category: str | None,
    low_score_only: bool,
) -> bool:
    if status and _normalize_status(row.get("status")) != status:
        return False
    if category:
        category_candidates = {
            _normalize_text(row.get("canonical_category_slug")).lower(),
            _normalize_text(row.get("category_slug")).lower(),
        }
        if category.lower() not in category_candidates:
            return False
    if query:
        lowered = query.lower()
        haystacks = (
            _normalize_text(row.get("title")).lower(),
            _normalize_text(row.get("canonical_category_name")).lower(),
            _normalize_text(row.get("category_name")).lower(),
            _normalize_text(row.get("published_url")).lower(),
        )
        if not any(lowered in item for item in haystacks):
            return False
    if low_score_only and not _is_low_score(row):
        return False
    return True


def _sort_key(row: dict[str, Any], sort: str):
    if sort == "title":
        return _normalize_text(row.get("title")).casefold()
    if sort == "seo":
        return _score_value(row.get("seo_score")) if _score_value(row.get("seo_score")) is not None else -1.0
    if sort == "geo":
        return _score_value(row.get("geo_score")) if _score_value(row.get("geo_score")) is not None else -1.0
    if sort == "ctr":
        return _score_value(row.get("ctr")) if _score_value(row.get("ctr")) is not None else -1.0
    if sort == "lighthouse":
        return _score_value(row.get("lighthouse_score")) if _score_value(row.get("lighthouse_score")) is not None else -1.0
    return _normalize_text(row.get("published_at"))


def _serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "channel_id": _normalize_text(row.get("channel_id")) or "dongriarchive",
        "channel_name": _normalize_text(row.get("channel_name")) or "Dongri Archive",
        "category_slug": _resolve_category_slug(row),
        "category_name": _resolve_category_name(row),
        "canonical_category_slug": _normalize_text(row.get("canonical_category_slug")) or None,
        "canonical_category_name": _normalize_text(row.get("canonical_category_name")) or None,
        "title": _normalize_text(row.get("title")) or "Untitled",
        "url": _normalize_text(row.get("published_url")) or None,
        "published_at": _normalize_text(row.get("published_at")) or None,
        "seo_score": _score_value(row.get("seo_score")),
        "geo_score": _score_value(row.get("geo_score")),
        "ctr": _score_value(row.get("ctr")),
        "lighthouse_score": _score_value(row.get("lighthouse_score")),
        "index_status": _normalize_text(row.get("index_status")) or "unknown",
        "live_image_count": row.get("live_image_count"),
        "live_unique_image_count": row.get("live_unique_image_count"),
        "live_duplicate_image_count": row.get("live_duplicate_image_count"),
        "live_webp_count": row.get("live_webp_count"),
        "live_png_count": row.get("live_png_count"),
        "live_other_image_count": row.get("live_other_image_count"),
        "live_image_issue": _normalize_text(row.get("live_image_issue")) or None,
        "live_image_audited_at": _normalize_text(row.get("live_image_audited_at")) or None,
        "lighthouse_accessibility_score": _score_value(row.get("lighthouse_accessibility_score")),
        "lighthouse_best_practices_score": _score_value(row.get("lighthouse_best_practices_score")),
        "lighthouse_seo_score": _score_value(row.get("lighthouse_seo_score")),
        "article_pattern_id": _normalize_text(row.get("article_pattern_id")) or None,
        "article_pattern_version": row.get("article_pattern_version"),
        "refactor_candidate": _is_refactor_candidate(row),
        "status": _normalize_text(row.get("status")) or "unknown",
        "quality_status": _normalize_text(row.get("quality_status")) or None,
    }


def _build_summary(rows: list[dict[str, Any]], *, month: str) -> dict[str, Any]:
    channel_id = _normalize_text(rows[0].get("channel_id")) if rows else "dongriarchive"
    channel_name = _normalize_text(rows[0].get("channel_name")) if rows else "Dongri Archive"
    category_counter: Counter[tuple[str, str]] = Counter()
    status_values: set[str] = set()
    for row in rows:
        category_slug = _resolve_category_slug(row)
        category_name = _resolve_category_name(row)
        if category_slug:
            category_counter[(category_slug, category_name or category_slug)] += 1
        status_value = _normalize_status(row.get("status"))
        if status_value:
            status_values.add(status_value)
    available_categories = [
        {"slug": slug, "name": name, "count": count}
        for (slug, name), count in sorted(category_counter.items(), key=lambda item: (item[0][0], item[0][1]))
    ]
    return {
        "month": month,
        "channel_id": channel_id,
        "channel_name": channel_name,
        "total": len(rows),
        "low_score_count": sum(1 for row in rows if _is_low_score(row)),
        "refactor_candidate_count": sum(1 for row in rows if _is_refactor_candidate(row)),
        "lighthouse_below_70_count": sum(1 for row in rows if _is_lighthouse_below_70(row)),
        "available_categories": available_categories,
        "available_statuses": sorted(status_values),
    }


def get_cloudflare_performance_summary(db: Session, *, month: str | None = None) -> dict[str, Any]:
    normalized_month = _normalize_month(month)
    rows = [row for row in list_synced_cloudflare_posts(db, include_non_published=True) if _month_matches(row, normalized_month)]
    return _build_summary(rows, month=normalized_month)


def get_cloudflare_performance_page(
    db: Session,
    *,
    month: str | None = None,
    status: str | None = None,
    query: str | None = None,
    sort: str | None = None,
    dir: str | None = None,
    low_score_only: bool = False,
    category: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    normalized_month = _normalize_month(month)
    normalized_status = _normalize_status(status)
    normalized_query = _normalize_text(query) or None
    normalized_category = _normalize_text(category) or None
    normalized_sort = (_normalize_text(sort) or "published_at").lower()
    normalized_dir = "asc" if (_normalize_text(dir).lower() == "asc") else "desc"
    safe_page = max(int(page or 1), 1)
    safe_page_size = max(min(int(page_size or 50), 500), 1)

    month_rows = [row for row in list_synced_cloudflare_posts(db, include_non_published=True) if _month_matches(row, normalized_month)]
    filtered_rows = [
        row
        for row in month_rows
        if _row_matches(
            row,
            status=normalized_status,
            query=normalized_query,
            category=normalized_category,
            low_score_only=low_score_only,
        )
    ]
    filtered_rows.sort(
        key=lambda item: (_sort_key(item, normalized_sort), _normalize_text(item.get("title")).casefold()),
        reverse=(normalized_dir == "desc"),
    )

    start = (safe_page - 1) * safe_page_size
    end = start + safe_page_size
    paged_rows = filtered_rows[start:end]
    return {
        "month": normalized_month,
        "total": len(filtered_rows),
        "page": safe_page,
        "page_size": safe_page_size,
        "summary": _build_summary(month_rows, month=normalized_month),
        "items": [_serialize_row(row) for row in paged_rows],
    }
