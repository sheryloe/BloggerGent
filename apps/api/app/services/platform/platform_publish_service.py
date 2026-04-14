from __future__ import annotations

import mimetypes
import random
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.entities import ContentItem, ManagedChannel, PublicationRecord
from app.services.platform.platform_oauth_service import PlatformOAuthError, authorized_platform_request
from app.services.integrations.settings_service import get_settings_map

YOUTUBE_UPLOAD_INIT_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
YOUTUBE_THUMBNAIL_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
INSTAGRAM_GRAPH_BASE_URL = "https://graph.facebook.com/{version}"
INSTAGRAM_REQUIRED_PUBLISH_SCOPES = {"instagram_content_publish", "pages_show_list", "pages_read_engagement"}
PUBLISH_SUCCESS_STATUSES = {"published", "uploaded_private"}
PUBLISH_INFLIGHT_STATUSES = {"queued", "publishing"}
PUBLISH_TARGET_STATE = "publish"
ERROR_CODE_MISSING_ASSET = "MISSING_ASSET"
ERROR_CODE_AUTH_EXPIRED = "AUTH_EXPIRED"
ERROR_CODE_CAPABILITY_BLOCKED = "CAPABILITY_BLOCKED"
ERROR_CODE_RATE_LIMITED = "RATE_LIMITED"
ERROR_CODE_PROVIDER_ERROR = "PROVIDER_ERROR"


class PlatformPublishError(Exception):
    def __init__(self, message: str, *, detail: str | None = None, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or message
        self.status_code = status_code


def _parse_response_payload(response) -> dict:
    try:
        payload = response.json() if response.content else {}
    except ValueError:
        payload = {"raw": response.text}
    return payload if isinstance(payload, dict) else {"raw": str(payload)}


def _response_detail(payload: dict, fallback: str) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("status") or fallback)
    if isinstance(error, str):
        return error
    return str(payload.get("message") or fallback)


def _resolve_local_path(raw_path: str) -> Path:
    candidate = Path(raw_path)
    candidates = [candidate]
    if not candidate.is_absolute():
        candidates.extend(
            [
                Path(settings.storage_root) / candidate,
                Path("/app") / candidate,
                Path("/workspace") / candidate,
            ]
        )
    for item in candidates:
        if item.exists() and item.is_file():
            return item
    raise PlatformPublishError(f"File not found: {raw_path}", status_code=404)


def _append_publication_record(
    db: Session,
    *,
    item: ContentItem,
    publish_status: str,
    target_state: str = PUBLISH_TARGET_STATE,
    error_code: str | None = None,
    remote_id: str | None = None,
    remote_url: str | None = None,
    response_payload: dict | None = None,
) -> ContentItem:
    if publish_status in {"queued", "publishing"}:
        existing = (
            db.execute(
                select(PublicationRecord)
                .where(PublicationRecord.content_item_id == item.id)
                .where(PublicationRecord.provider == item.managed_channel.provider)
                .where(PublicationRecord.target_state == target_state)
                .where(PublicationRecord.publish_status.in_(tuple(sorted(PUBLISH_INFLIGHT_STATUSES))))
                .order_by(PublicationRecord.created_at.desc(), PublicationRecord.id.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        if existing is not None:
            item.lifecycle_status = "queued"
            db.add(item)
            db.commit()
            db.refresh(item)
            return item

    published_at = datetime.now(UTC) if publish_status in {"published", "uploaded_private"} else None
    record = PublicationRecord(
        content_item_id=item.id,
        managed_channel_id=item.managed_channel_id,
        provider=item.managed_channel.provider,
        remote_id=remote_id,
        remote_url=remote_url,
        target_state=target_state,
        publish_status=publish_status,
        error_code=error_code,
        scheduled_for=item.scheduled_for,
        published_at=published_at,
        response_payload=response_payload or {},
    )
    item.lifecycle_status = "published" if publish_status == "published" else ("review" if publish_status == "uploaded_private" else publish_status)
    db.add(record)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _latest_publication_record(db: Session, item: ContentItem) -> PublicationRecord | None:
    if item.publication_records:
        for record in item.publication_records:
            if record.target_state == PUBLISH_TARGET_STATE:
                return record
    return (
        db.execute(
            select(PublicationRecord)
            .where(PublicationRecord.content_item_id == item.id)
            .where(PublicationRecord.target_state == PUBLISH_TARGET_STATE)
            .order_by(PublicationRecord.created_at.desc(), PublicationRecord.id.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )


def _youtube_privacy_status(db: Session) -> str:
    values = get_settings_map(db)
    privacy_status = str(values.get("youtube_default_privacy_status") or settings.youtube_default_privacy_status or "private").strip().lower()
    if privacy_status not in {"private", "public", "unlisted"}:
        return "private"
    return privacy_status


def _channel_capabilities(channel: ManagedChannel) -> set[str]:
    return {str(item).strip() for item in (channel.capabilities or []) if str(item).strip()}


def _append_failure_record(
    db: Session,
    *,
    item: ContentItem,
    publish_status: str,
    message: str,
    detail: str | None = None,
    error_code: str | None = None,
    failure_status_code: int | None = None,
    response_payload: dict | None = None,
) -> ContentItem:
    payload = dict(response_payload or {})
    payload["message"] = message
    if detail:
        payload["detail"] = detail
    if error_code:
        payload["error_code"] = error_code
    if failure_status_code is not None:
        payload["failure_status_code"] = int(failure_status_code)
    return _append_publication_record(
        db,
        item=item,
        target_state=PUBLISH_TARGET_STATE,
        publish_status=publish_status,
        error_code=error_code,
        response_payload=payload,
    )


def _classify_publish_failure(exc: Exception) -> tuple[str, str]:
    detail = str(getattr(exc, "detail", "") or str(exc) or "").strip()
    detail_lower = detail.lower()
    status_code = int(getattr(exc, "status_code", 0) or 0)

    if isinstance(exc, PlatformOAuthError) or status_code in {401, 403}:
        return ERROR_CODE_AUTH_EXPIRED, detail or "oauth_error"
    if (
        "publish_capability" in detail_lower
        or "permissions_unverified" in detail_lower
        or "publish_api_disabled" in detail_lower
        or "capability" in detail_lower
    ):
        return ERROR_CODE_CAPABILITY_BLOCKED, detail or "capability_blocked"
    if status_code == 429 or "quota" in detail_lower or "rate limit" in detail_lower:
        return ERROR_CODE_RATE_LIMITED, detail or "rate_limited"
    if detail_lower.startswith("missing_") or "missing_" in detail_lower or "file not found" in detail_lower:
        return ERROR_CODE_MISSING_ASSET, detail or "missing_required_asset"
    return ERROR_CODE_PROVIDER_ERROR, detail or "platform_publish_failed"


def content_item_missing_asset_reason(item: ContentItem, *, asset_manifest: dict | None = None) -> str | None:
    provider = item.managed_channel.provider
    manifest = dict(asset_manifest if asset_manifest is not None else (item.asset_manifest or {}))
    if provider == "youtube":
        if not str(manifest.get("video_file_path") or "").strip():
            return "missing_video_file_path"
        return None
    if provider == "instagram":
        if item.content_type == "instagram_reel":
            if not str(manifest.get("video_url") or "").strip():
                return "missing_instagram_video_url"
            return None
        if not str(manifest.get("image_url") or "").strip():
            return "missing_instagram_image_url"
    return None


def _youtube_tags(item: ContentItem) -> list[str]:
    raw_tags = item.brief_payload.get("tags") if isinstance(item.brief_payload, dict) else None
    if isinstance(raw_tags, list):
        return [str(tag).strip() for tag in raw_tags if str(tag).strip()]
    return []


def _resolve_youtube_privacy_status(db: Session, item: ContentItem, *, asset_manifest: dict) -> str:
    raw_privacy = str((item.brief_payload or {}).get("privacy_status") or asset_manifest.get("privacy_status") or "").strip().lower()
    if raw_privacy:
        if raw_privacy not in {"private", "public", "unlisted"}:
            raise PlatformPublishError(
                "YouTube privacy_status must be one of private|public|unlisted.",
                detail="invalid_privacy_status",
                status_code=400,
            )
        return raw_privacy
    return _youtube_privacy_status(db)


def _validate_youtube_tags(item: ContentItem) -> None:
    if not isinstance(item.brief_payload, dict):
        return
    raw_tags = item.brief_payload.get("tags")
    if raw_tags is None:
        return
    if not isinstance(raw_tags, list):
        raise PlatformPublishError(
            "YouTube tags must be provided as an array.",
            detail="invalid_tags_payload",
            status_code=400,
        )


def _validate_youtube_publish_input(item: ContentItem, *, video_file: Path) -> None:
    if not str(item.title or "").strip():
        raise PlatformPublishError("YouTube content requires a non-empty title.", detail="missing_title", status_code=400)
    if video_file.stat().st_size <= 0:
        raise PlatformPublishError(
            "YouTube content requires a non-empty video file.",
            detail="video_file_empty",
            status_code=400,
        )


def _preflight_content_item_for_queue(db: Session, item: ContentItem) -> None:
    provider = item.managed_channel.provider
    missing_reason = content_item_missing_asset_reason(item)
    if missing_reason:
        raise PlatformPublishError(
            "Content item is missing required publish assets.",
            detail=missing_reason,
            status_code=400,
        )
    if provider == "youtube":
        asset_manifest = dict(item.asset_manifest or {})
        video_file_path = str(asset_manifest.get("video_file_path") or "").strip()
        video_file = _resolve_local_path(video_file_path)
        _validate_youtube_publish_input(item, video_file=video_file)
        _validate_youtube_tags(item)
        _resolve_youtube_privacy_status(db, item, asset_manifest=asset_manifest)
        return

    if provider == "instagram":
        return


def _credential_scope_set(channel: ManagedChannel) -> set[str]:
    credential = next((record for record in (channel.credentials or []) if record.provider == channel.provider and record.is_valid), None)
    if credential is None:
        return set()
    return {str(scope).strip() for scope in (credential.scopes or []) if str(scope).strip()}


def _instagram_publish_gate_result(db: Session, channel: ManagedChannel) -> tuple[bool, str]:
    values = get_settings_map(db)
    publish_enabled = str(values.get("instagram_publish_api_enabled") or str(settings.instagram_publish_api_enabled).lower()).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not publish_enabled:
        return False, "instagram_publish_api_disabled"

    capabilities = _channel_capabilities(channel)
    if not any(capability in capabilities for capability in {"instagram_live_publish", "live_publish"}):
        return False, "instagram_publish_capability_missing"

    scopes = _credential_scope_set(channel)
    if not INSTAGRAM_REQUIRED_PUBLISH_SCOPES.issubset(scopes):
        return False, "instagram_publish_permissions_unverified"

    return True, "ok"


def _instagram_poll_window_seconds(db: Session) -> tuple[int, float, float]:
    values = get_settings_map(db)
    try:
        max_seconds = max(int(str(values.get("instagram_reel_publish_poll_seconds") or "120").strip()), 15)
    except (TypeError, ValueError):
        max_seconds = 120
    try:
        interval_seconds = max(float(str(values.get("instagram_reel_publish_poll_interval_seconds") or "3").strip()), 1.0)
    except (TypeError, ValueError):
        interval_seconds = 3.0
    try:
        max_interval_seconds = max(
            float(str(values.get("instagram_reel_publish_poll_max_interval_seconds") or "20").strip()),
            interval_seconds,
        )
    except (TypeError, ValueError):
        max_interval_seconds = max(20.0, interval_seconds)
    return max_seconds, interval_seconds, max_interval_seconds


def _poll_instagram_reel_container_ready(
    db: Session,
    *,
    channel_id: str,
    creation_id: str,
) -> dict:
    max_seconds, interval_seconds, max_interval_seconds = _instagram_poll_window_seconds(db)
    started = time.monotonic()
    attempts = 0
    next_sleep_seconds = interval_seconds
    while (time.monotonic() - started) < max_seconds:
        attempts += 1
        status_response = authorized_platform_request(
            db,
            channel_id=channel_id,
            method="GET",
            url=_instagram_graph_url(f"/{creation_id}"),
            params={"fields": "id,status_code,status"},
            timeout=60.0,
        )
        status_payload = _parse_response_payload(status_response)
        if not status_response.is_success:
            raise PlatformPublishError(
                "Instagram reel container status check failed.",
                detail=_response_detail(status_payload, status_response.text),
                status_code=status_response.status_code,
            )
        status_code = str(status_payload.get("status_code") or status_payload.get("status") or "").strip().upper()
        if status_code in {"FINISHED", "PUBLISHED", "READY"}:
            return {"status": "ready", "attempts": attempts, "payload": status_payload}
        if status_code in {"ERROR", "EXPIRED", "FAILED"}:
            raise PlatformPublishError(
                "Instagram reel container is not publishable.",
                detail=f"media_not_ready:container_status={status_code}",
                status_code=400,
            )
        jitter = random.uniform(0.0, min(0.75, next_sleep_seconds * 0.2))
        sleep_seconds = min(next_sleep_seconds, max_interval_seconds) + jitter
        time.sleep(sleep_seconds)
        next_sleep_seconds = min(next_sleep_seconds * 1.8, max_interval_seconds)

    raise PlatformPublishError(
        "Instagram reel container polling timed out.",
        detail=f"media_not_ready:container_not_ready_after_{max_seconds}s",
        status_code=504,
    )


def _upload_youtube_video(db: Session, item: ContentItem) -> ContentItem:
    asset_manifest = dict(item.asset_manifest or {})
    video_file_path = str(asset_manifest.get("video_file_path") or "").strip()
    if not video_file_path:
        raise PlatformPublishError(
            "YouTube content requires asset_manifest.video_file_path.",
            detail="missing_video_file_path",
            status_code=400,
        )

    video_file = _resolve_local_path(video_file_path)
    _validate_youtube_publish_input(item, video_file=video_file)
    _validate_youtube_tags(item)
    mime_type = mimetypes.guess_type(video_file.name)[0] or "video/mp4"
    privacy_status = _resolve_youtube_privacy_status(db, item, asset_manifest=asset_manifest)

    init_response = authorized_platform_request(
        db,
        channel_id=item.managed_channel.channel_id,
        method="POST",
        url=YOUTUBE_UPLOAD_INIT_URL,
        params={"part": "snippet,status", "uploadType": "resumable"},
        json_payload={
            "snippet": {
                "title": item.title,
                "description": item.body_text or item.description,
                "tags": _youtube_tags(item),
                "categoryId": str(asset_manifest.get("category_id") or "22"),
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": bool(asset_manifest.get("made_for_kids", False)),
            },
        },
        headers={
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(video_file.stat().st_size),
            "X-Upload-Content-Type": mime_type,
        },
        timeout=120.0,
    )
    init_payload = _parse_response_payload(init_response)
    if not init_response.is_success:
        raise PlatformPublishError(
            "YouTube upload session creation failed.",
            detail=_response_detail(init_payload, init_response.text),
            status_code=init_response.status_code,
        )

    upload_url = init_response.headers.get("Location", "")
    if not upload_url:
        raise PlatformPublishError("YouTube resumable upload URL was not returned.", status_code=502)

    with video_file.open("rb") as video_stream:
        upload_response = authorized_platform_request(
            db,
            channel_id=item.managed_channel.channel_id,
            method="PUT",
            url=upload_url,
            headers={"Content-Type": mime_type},
            content=video_stream,
            timeout=3600.0,
        )
    upload_payload = _parse_response_payload(upload_response)
    if not upload_response.is_success:
        raise PlatformPublishError(
            "YouTube video upload failed.",
            detail=_response_detail(upload_payload, upload_response.text),
            status_code=upload_response.status_code,
        )

    video_id = str(upload_payload.get("id") or "").strip()
    if not video_id:
        raise PlatformPublishError("YouTube upload response did not include a video id.", status_code=502)

    thumbnail_path = str(asset_manifest.get("thumbnail_file_path") or "").strip()
    thumbnail_payload: dict = {}
    if thumbnail_path:
        thumbnail_file = _resolve_local_path(thumbnail_path)
        thumbnail_mime = mimetypes.guess_type(thumbnail_file.name)[0] or "image/png"
        with thumbnail_file.open("rb") as thumbnail_stream:
            thumbnail_response = authorized_platform_request(
                db,
                channel_id=item.managed_channel.channel_id,
                method="POST",
                url=YOUTUBE_THUMBNAIL_UPLOAD_URL,
                params={"videoId": video_id, "uploadType": "media"},
                headers={"Content-Type": thumbnail_mime},
                content=thumbnail_stream,
                timeout=300.0,
            )
        thumbnail_payload = _parse_response_payload(thumbnail_response)
        if not thumbnail_response.is_success:
            raise PlatformPublishError(
                "YouTube thumbnail upload failed.",
                detail=_response_detail(thumbnail_payload, thumbnail_response.text),
                status_code=thumbnail_response.status_code,
            )

    remote_url = f"https://www.youtube.com/watch?v={video_id}"
    return _append_publication_record(
        db,
        item=item,
        publish_status="uploaded_private" if privacy_status == "private" else "published",
        remote_id=video_id,
        remote_url=remote_url,
        response_payload={"video": upload_payload, "thumbnail": thumbnail_payload},
    )


def _instagram_graph_url(path: str) -> str:
    version = (settings.meta_graph_api_version or "v23.0").strip()
    return f"{INSTAGRAM_GRAPH_BASE_URL.format(version=version)}{path}"


def _publish_instagram_content(db: Session, item: ContentItem) -> ContentItem:
    publish_allowed, block_reason = _instagram_publish_gate_result(db, item.managed_channel)
    if not publish_allowed:
        return _append_publication_record(
            db,
            item=item,
            publish_status="blocked",
            target_state=PUBLISH_TARGET_STATE,
            error_code=ERROR_CODE_CAPABILITY_BLOCKED,
            response_payload={"reason": block_reason, "error_code": ERROR_CODE_CAPABILITY_BLOCKED},
        )

    remote_account_id = str(item.managed_channel.remote_resource_id or "").strip()
    if not remote_account_id:
        raise PlatformPublishError("Instagram channel is missing a remote business account id.", status_code=400)

    asset_manifest = dict(item.asset_manifest or {})
    caption = str((item.brief_payload or {}).get("caption") or item.description or item.title).strip()
    if item.content_type == "instagram_reel":
        video_url = str(asset_manifest.get("video_url") or "").strip()
        if not video_url:
            raise PlatformPublishError("Instagram reel requires asset_manifest.video_url")
        container_payload = {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "share_to_feed": "true",
        }
        cover_url = str(asset_manifest.get("cover_url") or "").strip()
        if cover_url:
            container_payload["cover_url"] = cover_url
    else:
        image_url = str(asset_manifest.get("image_url") or "").strip()
        if not image_url:
            raise PlatformPublishError("Instagram image requires asset_manifest.image_url")
        container_payload = {"image_url": image_url, "caption": caption}

    container_response = authorized_platform_request(
        db,
        channel_id=item.managed_channel.channel_id,
        method="POST",
        url=_instagram_graph_url(f"/{remote_account_id}/media"),
        data=container_payload,
        timeout=120.0,
    )
    container_result = _parse_response_payload(container_response)
    if not container_response.is_success:
        raise PlatformPublishError(
            "Instagram media container creation failed.",
            detail=_response_detail(container_result, container_response.text),
            status_code=container_response.status_code,
        )

    creation_id = str(container_result.get("id") or "").strip()
    if not creation_id:
        raise PlatformPublishError("Instagram publish container id is missing.", status_code=502)

    reel_poll_payload: dict = {}
    if item.content_type == "instagram_reel":
        reel_poll_payload = _poll_instagram_reel_container_ready(
            db,
            channel_id=item.managed_channel.channel_id,
            creation_id=creation_id,
        )

    publish_response = authorized_platform_request(
        db,
        channel_id=item.managed_channel.channel_id,
        method="POST",
        url=_instagram_graph_url(f"/{remote_account_id}/media_publish"),
        data={"creation_id": creation_id},
        timeout=120.0,
    )
    publish_result = _parse_response_payload(publish_response)
    if not publish_response.is_success:
        raise PlatformPublishError(
            "Instagram publish failed.",
            detail=_response_detail(publish_result, publish_response.text),
            status_code=publish_response.status_code,
        )

    media_id = str(publish_result.get("id") or "").strip()
    permalink = None
    if media_id:
        media_response = authorized_platform_request(
            db,
            channel_id=item.managed_channel.channel_id,
            method="GET",
            url=_instagram_graph_url(f"/{media_id}"),
            params={"fields": "id,permalink,media_product_type"},
            timeout=60.0,
        )
        media_result = _parse_response_payload(media_response)
        if media_response.is_success:
            permalink = str(media_result.get("permalink") or "").strip() or None
            publish_result["media"] = media_result

    return _append_publication_record(
        db,
        item=item,
        target_state=PUBLISH_TARGET_STATE,
        publish_status="published",
        remote_id=media_id or creation_id,
        remote_url=permalink,
        response_payload={"container": container_result, "container_poll": reel_poll_payload, "publish": publish_result},
    )


def publish_content_item_now(db: Session, item: ContentItem) -> ContentItem:
    latest = _latest_publication_record(db, item)
    if latest is not None and latest.publish_status in PUBLISH_SUCCESS_STATUSES:
        target_status = "review" if latest.publish_status == "uploaded_private" else "published"
        if item.lifecycle_status != target_status:
            item.lifecycle_status = target_status
            db.add(item)
            db.commit()
            db.refresh(item)
        return item

    if item.managed_channel.provider == "youtube":
        return _upload_youtube_video(db, item)
    if item.managed_channel.provider == "instagram":
        return _publish_instagram_content(db, item)
    raise PlatformPublishError("Immediate publish is supported only for YouTube and Instagram.", status_code=400)


def mark_content_item_publish_queued(db: Session, item: ContentItem) -> ContentItem:
    latest = _latest_publication_record(db, item)
    if latest is not None:
        if latest.publish_status in PUBLISH_INFLIGHT_STATUSES:
            if item.lifecycle_status != "queued":
                item.lifecycle_status = "queued"
                db.add(item)
                db.commit()
                db.refresh(item)
            return item
        if latest.publish_status in PUBLISH_SUCCESS_STATUSES:
            target_status = "review" if latest.publish_status == "uploaded_private" else "published"
            if item.lifecycle_status != target_status:
                item.lifecycle_status = target_status
                db.add(item)
                db.commit()
                db.refresh(item)
            return item

    missing_reason = content_item_missing_asset_reason(item)
    if missing_reason:
        item.lifecycle_status = "blocked_asset"
        item.blocked_reason = missing_reason
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    _preflight_content_item_for_queue(db, item)
    return _append_publication_record(
        db,
        item=item,
        target_state=PUBLISH_TARGET_STATE,
        publish_status="queued",
        response_payload={"queued_from": "workspace", "idempotency_key": item.idempotency_key},
    )


def process_platform_publish_queue(db: Session, *, limit: int = 10) -> dict:
    now = datetime.now(UTC)
    queued_items = (
        db.execute(
            select(ContentItem)
            .join(ContentItem.managed_channel)
            .options(
                selectinload(ContentItem.managed_channel),
                selectinload(ContentItem.publication_records),
            )
            .where(ManagedChannel.provider.in_(("youtube", "instagram")))
            .where(ContentItem.lifecycle_status.in_(("queued", "scheduled")))
            .order_by(ContentItem.scheduled_for.asc().nullsfirst(), ContentItem.created_at.asc(), ContentItem.id.asc())
            .limit(max(1, min(limit, 100)))
        )
        .scalars()
        .unique()
        .all()
    )

    processed: list[dict] = []
    for item in queued_items:
        latest_publication = item.publication_records[0] if item.publication_records else None
        if latest_publication is None or latest_publication.publish_status != "queued":
            continue
        if item.scheduled_for is not None:
            scheduled_for = item.scheduled_for if item.scheduled_for.tzinfo is not None else item.scheduled_for.replace(tzinfo=UTC)
            if scheduled_for > now:
                continue
        try:
            updated = publish_content_item_now(db, item)
        except (PlatformPublishError, PlatformOAuthError) as exc:
            error_code, normalized_detail = _classify_publish_failure(exc)
            updated = _append_failure_record(
                db,
                item=item,
                publish_status="failed",
                message=exc.message if hasattr(exc, "message") else "platform_publish_failed",
                detail=normalized_detail,
                error_code=error_code,
                failure_status_code=getattr(exc, "status_code", None),
                response_payload={"queued_record_id": latest_publication.id},
            )
            processed.append(
                {
                    "item_id": updated.id,
                    "channel_id": updated.managed_channel.channel_id,
                    "provider": updated.managed_channel.provider,
                    "status": "failed",
                    "error_code": error_code,
                    "failure_code": error_code,
                    "detail": normalized_detail,
                }
            )
            continue

        latest_result = updated.publication_records[0] if updated.publication_records else None
        processed.append(
            {
                "item_id": updated.id,
                "channel_id": updated.managed_channel.channel_id,
                "provider": updated.managed_channel.provider,
                "status": latest_result.publish_status if latest_result else updated.lifecycle_status,
                "remote_url": latest_result.remote_url if latest_result else None,
            }
        )

    return {
        "status": "ok",
        "processed": processed,
        "processed_count": len(processed),
    }
