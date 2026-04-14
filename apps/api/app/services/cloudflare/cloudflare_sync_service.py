from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.entities import ManagedChannel, SyncedCloudflarePost
from app.services.ops.dedupe_utils import (
    dedupe_key as build_dedupe_key,
    pick_best_status as pick_best_dedupe_status,
    pick_preferred_url as pick_preferred_dedupe_url,
    status_priority as dedupe_status_priority,
)
from app.services.cloudflare.cloudflare_channel_service import CloudflareRemoteFetchError, list_cloudflare_posts
from app.services.platform.platform_service import ensure_managed_channels


def _parse_cloudflare_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _truncate(value: Any, limit: int) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if limit <= 0:
        return ""
    return text[:limit]


def _is_published(status_value: str) -> bool:
    return status_value in {"published", "live"}


def _extract_slug_from_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    path = parsed.path.strip("/")
    if not path:
        return None
    return path.split("/")[-1] or None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _cloudflare_row_priority(row: SyncedCloudflarePost) -> tuple[int, datetime, int]:
    status_rank = dedupe_status_priority(str(row.status or "").strip().lower())
    timestamp = (
        _as_utc(row.updated_at_remote)
        or _as_utc(row.published_at)
        or _as_utc(row.created_at_remote)
        or _as_utc(row.synced_at)
        or _as_utc(row.updated_at)
        or _as_utc(row.created_at)
        or datetime.min.replace(tzinfo=timezone.utc)
    )
    row_id = int(row.id or 0)
    return (status_rank, timestamp, row_id)


def _pick_first_row_value(rows: list[SyncedCloudflarePost], field: str, *, allow_empty_string: bool = False):
    for row in rows:
        value = getattr(row, field)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip() and not allow_empty_string:
            continue
        return value
    return None


def _merge_synced_cloudflare_group(rows: list[SyncedCloudflarePost]) -> SyncedCloudflarePost:
    ordered = sorted(rows, key=_cloudflare_row_priority, reverse=True)
    keeper = ordered[0]
    keeper.status = pick_best_dedupe_status(*[row.status for row in ordered]) or keeper.status or "published"
    keeper.url = pick_preferred_dedupe_url(*[row.url for row in ordered]) or keeper.url
    keeper.thumbnail_url = pick_preferred_dedupe_url(*[row.thumbnail_url for row in ordered]) or keeper.thumbnail_url

    field_specs = (
        "slug",
        "title",
        "published_at",
        "created_at_remote",
        "updated_at_remote",
        "category_name",
        "category_slug",
        "canonical_category_name",
        "canonical_category_slug",
        "excerpt_text",
        "seo_score",
        "geo_score",
        "ctr",
        "lighthouse_score",
        "lighthouse_accessibility_score",
        "lighthouse_best_practices_score",
        "lighthouse_seo_score",
        "lighthouse_payload",
        "lighthouse_last_audited_at",
        "index_status",
        "quality_status",
        "article_pattern_id",
        "article_pattern_version",
        "render_metadata",
    )
    for field in field_specs:
        merged_value = _pick_first_row_value(
            ordered,
            field,
            allow_empty_string=field in {"excerpt_text"},
        )
        if merged_value is not None:
            setattr(keeper, field, merged_value)

    live_source = next((row for row in ordered if row.live_image_count is not None), None)
    if live_source is None:
        live_source = next(
            (
                row
                for row in ordered
                if row.live_image_issue is not None or row.live_image_audited_at is not None
            ),
            None,
        )
    if live_source is not None:
        keeper.live_image_count = live_source.live_image_count
        keeper.live_unique_image_count = live_source.live_unique_image_count
        keeper.live_duplicate_image_count = live_source.live_duplicate_image_count
        keeper.live_webp_count = live_source.live_webp_count
        keeper.live_png_count = live_source.live_png_count
        keeper.live_other_image_count = live_source.live_other_image_count
        keeper.live_image_audited_at = live_source.live_image_audited_at
        if live_source.live_image_count is None:
            keeper.live_image_issue = live_source.live_image_issue
        elif live_source.live_image_count <= 0:
            keeper.live_image_issue = "missing_images"
        elif live_source.live_image_count == 1:
            keeper.live_image_issue = "single_image"
        else:
            keeper.live_image_issue = None

    labels: list[str] = []
    seen_labels: set[str] = set()
    for row in ordered:
        for raw_label in row.labels or []:
            label = str(raw_label or "").strip()
            if not label:
                continue
            key = label.casefold()
            if key in seen_labels:
                continue
            seen_labels.add(key)
            labels.append(label)
    keeper.labels = labels
    normalized_synced_at = []
    for row in ordered:
        normalized = _as_utc(row.synced_at)
        if normalized is not None:
            normalized_synced_at.append(normalized)
    keeper.synced_at = max(normalized_synced_at or [datetime.now(timezone.utc)])
    return keeper


def _dedupe_synced_cloudflare_rows(db: Session, *, managed_channel_id: int) -> dict[str, Any]:
    rows = (
        db.execute(
            select(SyncedCloudflarePost)
            .where(SyncedCloudflarePost.managed_channel_id == managed_channel_id)
            .order_by(SyncedCloudflarePost.id.asc())
        )
        .scalars()
        .all()
    )
    grouped: dict[str, list[SyncedCloudflarePost]] = {}
    for row in rows:
        key = build_dedupe_key(
            scope=f"cloudflare:{managed_channel_id}",
            url=row.url,
            title=row.title,
            published_at=row.published_at,
        )
        grouped.setdefault(key, []).append(row)

    merged_group_count = 0
    merged_row_deleted_count = 0
    sample_merged_keys: list[str] = []
    for key, items in grouped.items():
        if len(items) <= 1:
            continue
        merged_group_count += 1
        keeper = _merge_synced_cloudflare_group(items)
        for row in items:
            if row.id == keeper.id:
                continue
            db.delete(row)
            merged_row_deleted_count += 1
        if len(sample_merged_keys) < 20:
            sample_merged_keys.append(f"{key} -> keep:{keeper.id}")

    return {
        "merged_group_count": merged_group_count,
        "merged_row_deleted_count": merged_row_deleted_count,
        "sample_merged_keys": sample_merged_keys,
    }


def sync_cloudflare_posts(db: Session, *, include_non_published: bool = False) -> dict:
    ensure_managed_channels(db)
    channel = db.execute(
        select(ManagedChannel).where(ManagedChannel.provider == "cloudflare").order_by(ManagedChannel.id.desc())
    ).scalar_one_or_none()
    if channel is None:
        raise ValueError("Cloudflare channel is not configured.")

    existing_posts = (
        db.execute(
            select(SyncedCloudflarePost).where(SyncedCloudflarePost.managed_channel_id == channel.id)
        )
        .scalars()
        .all()
    )
    try:
        remote_posts = list_cloudflare_posts(db)
    except CloudflareRemoteFetchError as exc:
        db.rollback()
        return {
            "channel_id": channel.channel_id,
            "count": len(existing_posts),
            "last_synced_at": None,
            "dedupe": {},
            "status": "fetch_failed",
            "error": str(exc),
        }
    existing_by_remote_id = {post.remote_post_id: post for post in existing_posts}
    remote_ids: set[str] = set()
    now = datetime.now(timezone.utc)

    for payload in remote_posts:
        remote_post_id = str(payload.get("remote_id") or "").strip()
        if not remote_post_id:
            continue
        status_value = str(payload.get("status") or "").strip().lower() or "published"
        if not include_non_published and not _is_published(status_value):
            continue

        remote_ids.add(remote_post_id)
        post = existing_by_remote_id.get(remote_post_id)
        if post is None:
            post = SyncedCloudflarePost(managed_channel_id=channel.id, remote_post_id=remote_post_id)
            db.add(post)

        published_url = _truncate(payload.get("published_url"), 1000)
        post.slug = _truncate(payload.get("slug"), 255) or _truncate(_extract_slug_from_url(published_url), 255)
        post.title = _truncate(payload.get("title"), 500) or "Untitled"
        post.url = published_url
        post.status = _truncate(status_value, 50) or "published"
        post.published_at = _parse_cloudflare_datetime(payload.get("published_at"))
        post.created_at_remote = _parse_cloudflare_datetime(payload.get("created_at"))
        post.updated_at_remote = _parse_cloudflare_datetime(payload.get("updated_at"))
        post.labels = list(payload.get("labels") or [])
        post.category_name = _truncate(payload.get("category_name"), 255)
        post.category_slug = _truncate(payload.get("category_slug"), 255)
        post.canonical_category_name = _truncate(payload.get("canonical_category_name"), 255)
        post.canonical_category_slug = _truncate(payload.get("canonical_category_slug"), 255)
        post.excerpt_text = str(payload.get("excerpt") or "").strip()
        post.thumbnail_url = _truncate(payload.get("thumbnail_url"), 1000)
        post.seo_score = _optional_float(payload.get("seo_score"))
        post.geo_score = _optional_float(payload.get("geo_score"))
        post.ctr = _optional_float(payload.get("ctr"))
        incoming_lighthouse_score = _optional_float(payload.get("lighthouse_score"))
        if incoming_lighthouse_score is not None:
            post.lighthouse_score = incoming_lighthouse_score
        incoming_lighthouse_accessibility_score = _optional_float(payload.get("lighthouse_accessibility_score"))
        if incoming_lighthouse_accessibility_score is not None:
            post.lighthouse_accessibility_score = incoming_lighthouse_accessibility_score
        incoming_lighthouse_best_practices_score = _optional_float(payload.get("lighthouse_best_practices_score"))
        if incoming_lighthouse_best_practices_score is not None:
            post.lighthouse_best_practices_score = incoming_lighthouse_best_practices_score
        incoming_lighthouse_seo_score = _optional_float(payload.get("lighthouse_seo_score"))
        if incoming_lighthouse_seo_score is not None:
            post.lighthouse_seo_score = incoming_lighthouse_seo_score
        incoming_lighthouse_payload = payload.get("lighthouse_payload")
        if isinstance(incoming_lighthouse_payload, dict) and incoming_lighthouse_payload:
            post.lighthouse_payload = dict(incoming_lighthouse_payload)
        incoming_lighthouse_last_audited_at = _parse_cloudflare_datetime(payload.get("lighthouse_last_audited_at"))
        if incoming_lighthouse_last_audited_at is not None:
            post.lighthouse_last_audited_at = incoming_lighthouse_last_audited_at
        post.live_image_count = _optional_int(payload.get("live_image_count"))
        post.live_unique_image_count = _optional_int(payload.get("live_unique_image_count"))
        post.live_duplicate_image_count = _optional_int(payload.get("live_duplicate_image_count"))
        post.live_webp_count = _optional_int(payload.get("live_webp_count"))
        post.live_png_count = _optional_int(payload.get("live_png_count"))
        post.live_other_image_count = _optional_int(payload.get("live_other_image_count"))
        post.live_image_issue = _truncate(payload.get("live_image_issue"), 255)
        post.live_image_audited_at = _parse_cloudflare_datetime(payload.get("live_image_audited_at"))
        post.index_status = _truncate(payload.get("index_status"), 50)
        post.quality_status = _truncate(payload.get("quality_status"), 50)
        incoming_pattern_id = _truncate(payload.get("article_pattern_id"), 100)
        incoming_pattern_version = _optional_int(payload.get("article_pattern_version"))
        incoming_render_metadata = payload.get("render_metadata") if isinstance(payload.get("render_metadata"), dict) else {}
        if incoming_pattern_id is not None:
            post.article_pattern_id = incoming_pattern_id
        if incoming_pattern_version is not None:
            post.article_pattern_version = incoming_pattern_version
        if incoming_render_metadata:
            post.render_metadata = dict(incoming_render_metadata)
        post.synced_at = now

    if remote_ids:
        db.execute(
            delete(SyncedCloudflarePost).where(
                SyncedCloudflarePost.managed_channel_id == channel.id,
                SyncedCloudflarePost.remote_post_id.not_in(list(remote_ids)),
            )
        )
    else:
        db.execute(delete(SyncedCloudflarePost).where(SyncedCloudflarePost.managed_channel_id == channel.id))

    db.flush()
    dedupe_report = _dedupe_synced_cloudflare_rows(db, managed_channel_id=channel.id)
    db.commit()
    return {
        "channel_id": channel.channel_id,
        "count": len(remote_ids),
        "last_synced_at": now,
        "dedupe": dedupe_report,
    }


def list_synced_cloudflare_posts(db: Session, *, include_non_published: bool = False) -> list[dict]:
    channel = db.execute(
        select(ManagedChannel).where(ManagedChannel.provider == "cloudflare").order_by(ManagedChannel.id.desc())
    ).scalar_one_or_none()
    if channel is None:
        return []

    query = select(SyncedCloudflarePost).where(SyncedCloudflarePost.managed_channel_id == channel.id)
    if not include_non_published:
        query = query.where(SyncedCloudflarePost.status.in_(("published", "live")))

    rows = db.execute(
        query.order_by(
            SyncedCloudflarePost.published_at.desc().nullslast(),
            SyncedCloudflarePost.updated_at_remote.desc().nullslast(),
            SyncedCloudflarePost.id.desc(),
        )
    ).scalars().all()

    items: list[dict] = []
    for row in rows:
        items.append(
            {
                "provider": "cloudflare",
                "channel_id": channel.channel_id,
                "channel_name": channel.display_name or channel.channel_id,
                "category_name": row.category_name,
                "category_slug": row.category_slug,
                "canonical_category_name": row.canonical_category_name,
                "canonical_category_slug": row.canonical_category_slug,
                "remote_id": row.remote_post_id,
                "provider_status": "connected",
                "title": row.title,
                "excerpt": row.excerpt_text,
                "published_url": row.url,
                "thumbnail_url": row.thumbnail_url,
                "labels": list(row.labels or []),
                "seo_score": row.seo_score,
                "geo_score": row.geo_score,
                "ctr": row.ctr,
                "lighthouse_score": row.lighthouse_score,
                "lighthouse_accessibility_score": row.lighthouse_accessibility_score,
                "lighthouse_best_practices_score": row.lighthouse_best_practices_score,
                "lighthouse_seo_score": row.lighthouse_seo_score,
                "lighthouse_last_audited_at": row.lighthouse_last_audited_at.isoformat() if row.lighthouse_last_audited_at else None,
                "live_image_count": row.live_image_count,
                "live_unique_image_count": row.live_unique_image_count,
                "live_duplicate_image_count": row.live_duplicate_image_count,
                "live_webp_count": row.live_webp_count,
                "live_png_count": row.live_png_count,
                "live_other_image_count": row.live_other_image_count,
                "live_image_issue": row.live_image_issue,
                "live_image_audited_at": row.live_image_audited_at.isoformat() if row.live_image_audited_at else None,
                "index_status": row.index_status or "unknown",
                "index_coverage_state": None,
                "index_last_checked_at": None,
                "next_eligible_at": None,
                "last_error": None,
                "quality_status": row.quality_status,
                "article_pattern_id": row.article_pattern_id,
                "article_pattern_version": row.article_pattern_version,
                "published_at": row.published_at.isoformat() if row.published_at else None,
                "updated_at": row.updated_at_remote.isoformat() if row.updated_at_remote else None,
                "status": row.status,
            }
        )
    return items
