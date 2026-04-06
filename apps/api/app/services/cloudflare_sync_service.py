from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.entities import ManagedChannel, SyncedCloudflarePost
from app.services.cloudflare_channel_service import list_cloudflare_posts
from app.services.platform_service import ensure_managed_channels


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


def sync_cloudflare_posts(db: Session, *, include_non_published: bool = False) -> dict:
    ensure_managed_channels(db)
    channel = db.execute(
        select(ManagedChannel).where(ManagedChannel.provider == "cloudflare").order_by(ManagedChannel.id.desc())
    ).scalar_one_or_none()
    if channel is None:
        raise ValueError("Cloudflare channel is not configured.")

    remote_posts = list_cloudflare_posts(db)
    existing_posts = (
        db.execute(
            select(SyncedCloudflarePost).where(SyncedCloudflarePost.managed_channel_id == channel.id)
        )
        .scalars()
        .all()
    )
    existing_by_remote_id = {post.remote_post_id: post for post in existing_posts}
    remote_ids: list[str] = []
    now = datetime.now(timezone.utc)

    for payload in remote_posts:
        remote_post_id = str(payload.get("remote_id") or "").strip()
        if not remote_post_id:
            continue
        status_value = str(payload.get("status") or "").strip().lower() or "published"
        if not include_non_published and not _is_published(status_value):
            continue

        remote_ids.append(remote_post_id)
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
        post.excerpt_text = str(payload.get("excerpt") or "").strip()
        post.thumbnail_url = _truncate(payload.get("thumbnail_url"), 1000)
        post.seo_score = _optional_float(payload.get("seo_score"))
        post.geo_score = _optional_float(payload.get("geo_score"))
        post.ctr = _optional_float(payload.get("ctr"))
        post.index_status = _truncate(payload.get("index_status"), 50)
        post.quality_status = _truncate(payload.get("quality_status"), 50)
        post.synced_at = now

    if remote_ids:
        db.execute(
            delete(SyncedCloudflarePost).where(
                SyncedCloudflarePost.managed_channel_id == channel.id,
                SyncedCloudflarePost.remote_post_id.not_in(remote_ids),
            )
        )
    else:
        db.execute(delete(SyncedCloudflarePost).where(SyncedCloudflarePost.managed_channel_id == channel.id))

    db.commit()
    return {
        "channel_id": channel.channel_id,
        "count": len(remote_ids),
        "last_synced_at": now,
    }
