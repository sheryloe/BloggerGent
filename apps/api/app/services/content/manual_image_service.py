from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from PIL import Image as PILImage
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import (
    Article,
    Blog,
    BloggerPost,
    Image,
    Job,
    ManagedChannel,
    ManualImageSlot,
    ManualImageSlotStatus,
    SyncedCloudflarePost,
)
from app.services.cloudflare.cloudflare_asset_policy import (
    build_cloudflare_r2_object_key,
    get_cloudflare_asset_policy,
    resolve_cloudflare_category_leaf,
    resolve_cloudflare_post_slug,
)
from app.services.content.article_service import build_article_r2_asset_object_key
from app.services.integrations.settings_service import get_settings_map
from app.services.integrations.storage_service import (
    _normalize_binary_for_filename,
    save_public_binary,
    upload_binary_to_cloudflare_r2,
)
from app.services.platform.publishing_service import rebuild_article_html, upsert_article_blogger_post
from app.services.providers.factory import get_blogger_provider

TRUTHY_VALUES = {"1", "true", "yes", "on", "enabled"}
MANUAL_IMAGE_PROVIDER_BLOGGER = "blogger"
MANUAL_IMAGE_PROVIDER_CLOUDFLARE = "cloudflare"
MANUAL_IMAGE_DEFAULT_CHANNEL_ID = "cloudflare:dongriarchive"
MANUAL_IMAGE_SUPPORTED_EXTENSIONS = {".webp", ".png", ".jpg", ".jpeg"}
TRAVEL_MANUAL_IMAGE_BLOG_IDS = {34, 36, 37}
MANUAL_IMAGE_LOCKED_BLOG_IDS = {34, 35, 36, 37}
MANUAL_IMAGE_LOCKED_CLOUDFLARE_CHANNEL_IDS = {"cloudflare:dongriarchive"}


def _truthy(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return default
    return text in TRUTHY_VALUES


def _csv_tokens(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        values = [str(item).strip() for item in raw if str(item).strip()]
        return values
    text = str(raw).strip()
    if not text:
        return []
    return [token.strip() for token in text.split(",") if token.strip()]


def _locked_blog_ids(settings_map: dict[str, str] | None = None) -> set[int]:
    locked_ids = set(MANUAL_IMAGE_LOCKED_BLOG_IDS)
    for token in _csv_tokens((settings_map or {}).get("manual_image_locked_blog_ids")):
        try:
            locked_ids.add(int(token))
        except (TypeError, ValueError):
            continue
    return locked_ids


def _locked_cloudflare_channels(settings_map: dict[str, str] | None = None) -> set[str]:
    locked_channels = {str(value).strip().lower() for value in MANUAL_IMAGE_LOCKED_CLOUDFLARE_CHANNEL_IDS}
    for token in _csv_tokens((settings_map or {}).get("manual_image_locked_cloudflare_channels")):
        normalized = str(token).strip().lower()
        if normalized:
            locked_channels.add(normalized)
    return locked_channels


def is_manual_image_blog_locked(blog_id: int | None, settings_map: dict[str, str] | None = None) -> bool:
    if blog_id is None:
        return False
    return int(blog_id) in _locked_blog_ids(settings_map)


def is_manual_image_channel_locked(channel_id: str | None, settings_map: dict[str, str] | None = None) -> bool:
    normalized_channel_id = str(channel_id or "").strip().lower()
    if not normalized_channel_id:
        return False
    return normalized_channel_id in _locked_cloudflare_channels(settings_map)


def resolve_manual_image_defer_for_blog(
    *,
    blog_id: int | None,
    requested_defer_images: bool | None,
    settings_map: dict[str, str] | None = None,
) -> bool:
    if is_manual_image_blog_locked(blog_id, settings_map):
        return True
    if requested_defer_images is None:
        return _truthy((settings_map or {}).get("manual_image_defer_enabled"), default=True)
    return bool(requested_defer_images)


def manual_image_defer_enabled(job: Job | None, settings_map: dict[str, str] | None = None) -> bool:
    if job is not None and is_manual_image_blog_locked(getattr(job, "blog_id", None), settings_map):
        return True
    control = dict(getattr(job, "raw_prompts", None) or {}).get("pipeline_control", {}) if job is not None else {}
    if isinstance(control, dict) and "defer_images" in control:
        return _truthy(control.get("defer_images"), default=True)
    return _truthy((settings_map or {}).get("manual_image_defer_enabled"), default=True)


def _schedule_timezone(db: Session) -> ZoneInfo:
    values = get_settings_map(db)
    timezone_name = str(values.get("schedule_timezone") or "Asia/Seoul").strip() or "Asia/Seoul"
    try:
        return ZoneInfo(timezone_name)
    except Exception:  # noqa: BLE001
        return ZoneInfo("Asia/Seoul")


def _ensure_serial_code(db: Session, slot: ManualImageSlot) -> ManualImageSlot:
    current = str(slot.serial_code or "").strip()
    if current.startswith("BGIMG-"):
        return slot
    created_at = slot.created_at or datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    date_label = created_at.astimezone(_schedule_timezone(db)).strftime("%Y%m%d")
    slot.serial_code = f"BGIMG-{date_label}-{int(slot.id):06d}"
    db.add(slot)
    db.commit()
    db.refresh(slot)
    return slot


def _slot_metadata(**values: Any) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value not in (None, "")}


def _merge_metadata(existing: dict | None, updates: dict | None) -> dict:
    merged = dict(existing or {})
    merged.update(dict(updates or {}))
    return merged


def create_manual_image_slot(
    db: Session,
    *,
    provider: str,
    slot_role: str,
    prompt: str,
    blog: Blog | None = None,
    job: Job | None = None,
    article: Article | None = None,
    blogger_post: BloggerPost | None = None,
    managed_channel: ManagedChannel | None = None,
    synced_cloudflare_post: SyncedCloudflarePost | None = None,
    remote_post_id: str | None = None,
    batch_key: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ManualImageSlot:
    normalized_provider = str(provider or "").strip().lower()
    normalized_role = str(slot_role or "hero").strip().lower() or "hero"
    normalized_remote_id = str(remote_post_id or "").strip() or None
    prompt_text = str(prompt or "").strip()

    existing = None
    if normalized_remote_id:
        existing = db.execute(
            select(ManualImageSlot).where(
                ManualImageSlot.provider == normalized_provider,
                ManualImageSlot.remote_post_id == normalized_remote_id,
                ManualImageSlot.slot_role == normalized_role,
            )
        ).scalar_one_or_none()

    if existing:
        if existing.status == ManualImageSlotStatus.PENDING:
            existing.prompt = prompt_text
            existing.blog_id = getattr(blog, "id", None) or existing.blog_id
            existing.job_id = getattr(job, "id", None) or existing.job_id
            existing.article_id = getattr(article, "id", None) or existing.article_id
            existing.blogger_post_id = getattr(blogger_post, "id", None) or existing.blogger_post_id
            existing.managed_channel_id = getattr(managed_channel, "id", None) or existing.managed_channel_id
            existing.synced_cloudflare_post_id = (
                getattr(synced_cloudflare_post, "id", None) or existing.synced_cloudflare_post_id
            )
            existing.batch_key = batch_key or existing.batch_key
            existing.slot_metadata = _merge_metadata(existing.slot_metadata, metadata)
            db.add(existing)
            db.commit()
            db.refresh(existing)
        return _ensure_serial_code(db, existing)

    slot = ManualImageSlot(
        serial_code=f"PENDING-{uuid4().hex[:20]}",
        provider=normalized_provider,
        blog_id=getattr(blog, "id", None),
        job_id=getattr(job, "id", None),
        article_id=getattr(article, "id", None),
        blogger_post_id=getattr(blogger_post, "id", None),
        managed_channel_id=getattr(managed_channel, "id", None),
        synced_cloudflare_post_id=getattr(synced_cloudflare_post, "id", None),
        remote_post_id=normalized_remote_id,
        slot_role=normalized_role,
        prompt=prompt_text,
        status=ManualImageSlotStatus.PENDING,
        batch_key=batch_key,
        slot_metadata=dict(metadata or {}),
    )
    db.add(slot)
    db.commit()
    db.refresh(slot)
    return _ensure_serial_code(db, slot)


def list_manual_image_slots(
    db: Session,
    *,
    provider: str | None = None,
    status: ManualImageSlotStatus | str | None = ManualImageSlotStatus.PENDING,
    blog_id: int | None = None,
    batch_key: str | None = None,
    limit: int = 100,
) -> list[ManualImageSlot]:
    query = select(ManualImageSlot).order_by(ManualImageSlot.id.asc()).limit(max(1, min(int(limit or 100), 500)))
    if provider:
        query = query.where(ManualImageSlot.provider == str(provider).strip().lower())
    if status:
        query = query.where(ManualImageSlot.status == _normalize_status(status))
    if blog_id:
        query = query.where(ManualImageSlot.blog_id == int(blog_id))
    if batch_key:
        query = query.where(ManualImageSlot.batch_key == str(batch_key).strip())
    return list(db.execute(query).scalars().all())


def format_manual_image_slot_for_chat(slot: ManualImageSlot) -> str:
    metadata = dict(slot.slot_metadata or {})
    lines = [
        str(slot.serial_code or "").strip(),
        f"provider: {slot.provider}",
    ]
    if slot.blog_id:
        lines.append(f"blog_id: {slot.blog_id}")
    if slot.article_id:
        lines.append(f"article_id: {slot.article_id}")
    if slot.remote_post_id:
        lines.append(f"remote_post_id: {slot.remote_post_id}")
    lines.extend(
        [
            f"slot: {slot.slot_role}",
            f"title: {metadata.get('title', '')}",
            f"published_url: {metadata.get('published_url') or metadata.get('public_url') or ''}",
            "prompt:",
            str(slot.prompt or "").strip(),
        ]
    )
    return "\n".join(lines).rstrip()


def format_manual_image_slots_for_chat(slots: list[ManualImageSlot]) -> str:
    if not slots:
        return "pending manual image slots: 0"
    return "\n\n".join(format_manual_image_slot_for_chat(slot) for slot in slots)


def apply_manual_image_slots(db: Session, items: list[dict[str, str]]) -> dict[str, Any]:
    slots: list[ManualImageSlot] = []
    applied_count = 0
    failed_count = 0
    for item in items:
        serial_code = str(item.get("serial_code") or "").strip()
        file_path = str(item.get("file_path") or "").strip()
        slot = apply_manual_image_slot(db, serial_code=serial_code, file_path=file_path)
        slots.append(slot)
        if slot.status == ManualImageSlotStatus.APPLIED:
            applied_count += 1
        elif slot.status == ManualImageSlotStatus.FAILED:
            failed_count += 1
    return {
        "status": "ok" if failed_count == 0 else "partial_failed",
        "applied_count": applied_count,
        "failed_count": failed_count,
        "items": slots,
    }


def apply_manual_image_slot(db: Session, *, serial_code: str, file_path: str) -> ManualImageSlot:
    normalized_serial = str(serial_code or "").strip()
    if not normalized_serial:
        raise ValueError("serial_code is required.")
    slot = db.execute(
        select(ManualImageSlot).where(ManualImageSlot.serial_code == normalized_serial)
    ).scalar_one_or_none()
    if not slot:
        raise ValueError(f"Manual image slot not found: {normalized_serial}")
    if slot.status == ManualImageSlotStatus.APPLIED:
        return slot

    try:
        source_path, image_bytes, width, height = _load_manual_image(file_path)
        if slot.provider == MANUAL_IMAGE_PROVIDER_BLOGGER:
            apply_result = _apply_blogger_image_slot(
                db,
                slot=slot,
                source_path=source_path,
                image_bytes=image_bytes,
                width=width,
                height=height,
            )
        elif slot.provider == MANUAL_IMAGE_PROVIDER_CLOUDFLARE:
            apply_result = _apply_cloudflare_image_slot(
                db,
                slot=slot,
                source_path=source_path,
                image_bytes=image_bytes,
                width=width,
                height=height,
            )
        else:
            raise ValueError(f"Unsupported manual image provider: {slot.provider}")

        slot.status = ManualImageSlotStatus.APPLIED
        slot.file_path = str(apply_result.get("file_path") or source_path)
        slot.public_url = str(apply_result.get("public_url") or "")
        slot.object_key = str(apply_result.get("object_key") or "")
        slot.applied_at = datetime.now(timezone.utc)
        slot.slot_metadata = _merge_metadata(
            slot.slot_metadata,
            {
                "last_error": "",
                "width": width,
                "height": height,
                **dict(apply_result.get("metadata") or {}),
            },
        )
    except Exception as exc:  # noqa: BLE001
        slot.status = ManualImageSlotStatus.FAILED
        slot.file_path = str(file_path or "").strip()
        slot.slot_metadata = _merge_metadata(
            slot.slot_metadata,
            {"last_error": str(exc), "failed_at": datetime.now(timezone.utc).isoformat()},
        )
    db.add(slot)
    db.commit()
    db.refresh(slot)
    return slot


def _normalize_status(value: ManualImageSlotStatus | str) -> ManualImageSlotStatus:
    if isinstance(value, ManualImageSlotStatus):
        return value
    return ManualImageSlotStatus(str(value).strip().lower())


def _load_manual_image(file_path: str) -> tuple[Path, bytes, int, int]:
    source_path = Path(str(file_path or "").strip().strip('"')).expanduser()
    if not source_path.exists() or not source_path.is_file():
        raise ValueError(f"Image file not found: {source_path}")
    if source_path.suffix.lower() not in MANUAL_IMAGE_SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported image extension: {source_path.suffix}")
    source_bytes = source_path.read_bytes()
    webp_bytes = _normalize_binary_for_filename(
        content=source_bytes,
        filename=f"{source_path.stem}.webp",
        force_webp=True,
    )
    with PILImage.open(source_path) as loaded:
        width, height = loaded.size
    return source_path, webp_bytes, int(width or 0), int(height or 0)


def _upsert_manual_article_image(
    db: Session,
    *,
    article: Article,
    slot: ManualImageSlot,
    file_path: str,
    public_url: str,
    width: int,
    height: int,
    delivery_meta: dict,
) -> Image:
    image = db.execute(select(Image).where(Image.job_id == article.job_id)).scalar_one_or_none()
    metadata = {
        "manual_image_slot_id": slot.id,
        "manual_image_serial_code": slot.serial_code,
        "delivery": delivery_meta,
    }
    if image:
        image.article_id = article.id
        image.prompt = slot.prompt
        image.file_path = file_path
        image.public_url = public_url
        image.width = width or image.width
        image.height = height or image.height
        image.provider = "manual"
        image.image_metadata = _merge_metadata(image.image_metadata, metadata)
    else:
        image = Image(
            job_id=article.job_id,
            article_id=article.id,
            prompt=slot.prompt,
            file_path=file_path,
            public_url=public_url,
            width=width or 1536,
            height=height or 1024,
            provider="manual",
            image_metadata=metadata,
        )
    db.add(image)
    db.commit()
    db.refresh(image)
    return image


def _apply_blogger_image_slot(
    db: Session,
    *,
    slot: ManualImageSlot,
    source_path: Path,
    image_bytes: bytes,
    width: int,
    height: int,
) -> dict[str, Any]:
    article = db.execute(
        select(Article)
        .where(Article.id == slot.article_id)
        .options(
            selectinload(Article.blog),
            selectinload(Article.image),
            selectinload(Article.blogger_post),
        )
    ).scalar_one_or_none()
    if not article:
        raise ValueError(f"Article not found for manual image slot: {slot.serial_code}")
    if article.blog_id not in TRAVEL_MANUAL_IMAGE_BLOG_IDS and not _is_mystery_blog(article.blog):
        raise ValueError(f"Manual Blogger image apply is not allowed for blog_id={article.blog_id}")
    blogger_post = article.blogger_post or (db.get(BloggerPost, slot.blogger_post_id) if slot.blogger_post_id else None)
    if not blogger_post or not str(blogger_post.blogger_post_id or "").strip():
        raise ValueError(f"Blogger post not found for manual image slot: {slot.serial_code}")

    slot_role = str(slot.slot_role or "hero").strip().lower()
    asset_role = "hero" if slot_role in {"hero", "cover"} else slot_role
    object_key = build_article_r2_asset_object_key(article, asset_role=asset_role, content=image_bytes)
    image_subdir = "images/mystery" if _is_mystery_blog(article.blog) else "images"
    file_path, public_url, delivery_meta = save_public_binary(
        db,
        subdir=image_subdir,
        filename=f"{article.slug}-{asset_role}.webp" if asset_role != "hero" else f"{article.slug}.webp",
        content=image_bytes,
        object_key=object_key,
    )

    if slot_role in {"hero", "cover"}:
        _upsert_manual_article_image(
            db,
            article=article,
            slot=slot,
            file_path=file_path,
            public_url=public_url,
            width=width,
            height=height,
            delivery_meta=delivery_meta,
        )
        hero_image_url = public_url
    else:
        inline_media = list(article.inline_media or [])
        inline_media = [item for item in inline_media if dict(item).get("manual_image_slot_id") != slot.id]
        inline_media.append(
            {
                "slot": slot_role,
                "kind": "collage",
                "image_url": public_url,
                "file_path": file_path,
                "prompt": slot.prompt,
                "width": width,
                "height": height,
                "delivery": delivery_meta,
                "manual_image_slot_id": slot.id,
                "manual_image_serial_code": slot.serial_code,
            }
        )
        article.inline_media = inline_media
        db.add(article)
        db.commit()
        db.refresh(article)
        hero_image_url = article.image.public_url if article.image else ""

    assembled_html = rebuild_article_html(db, article, hero_image_url)
    provider = get_blogger_provider(db, article.blog)
    labels = [str(label).strip() for label in (article.labels or []) if str(label).strip()]
    summary, raw_payload = provider.update_post(
        post_id=blogger_post.blogger_post_id,
        title=article.title,
        content=assembled_html,
        labels=labels,
        meta_description=article.meta_description,
    )
    upsert_article_blogger_post(db, article=article, summary=summary, raw_payload=raw_payload)
    return {
        "file_path": file_path,
        "public_url": public_url,
        "object_key": object_key,
        "metadata": {
            "delivery": delivery_meta,
            "source_file_path": str(source_path),
            "blogger_update_post_id": blogger_post.blogger_post_id,
        },
    }


def _apply_cloudflare_image_slot(
    db: Session,
    *,
    slot: ManualImageSlot,
    source_path: Path,
    image_bytes: bytes,
    width: int,
    height: int,
) -> dict[str, Any]:
    metadata = dict(slot.slot_metadata or {})
    channel = slot.managed_channel or (
        db.get(ManagedChannel, slot.managed_channel_id) if slot.managed_channel_id else None
    )
    if channel is None:
        channel = db.execute(
            select(ManagedChannel).where(
                ManagedChannel.provider == "cloudflare",
                ManagedChannel.channel_id == MANUAL_IMAGE_DEFAULT_CHANNEL_ID,
            )
        ).scalar_one_or_none()
    if channel is None:
        raise ValueError("Cloudflare managed channel is not configured.")

    remote_post_id = str(slot.remote_post_id or metadata.get("remote_post_id") or "").strip()
    if not remote_post_id:
        raise ValueError(f"Cloudflare remote_post_id is missing for slot: {slot.serial_code}")

    policy = get_cloudflare_asset_policy(channel)
    category_slug = str(metadata.get("category_slug") or metadata.get("canonical_category_slug") or "").strip()
    post_slug = resolve_cloudflare_post_slug(str(metadata.get("slug") or remote_post_id).strip())
    slot_role = str(slot.slot_role or "cover").strip().lower()
    if slot_role in {"cover", "hero"}:
        object_key = build_cloudflare_r2_object_key(
            policy=policy,
            category_slug=category_slug,
            post_slug=post_slug,
            published_at=datetime.now(timezone.utc),
        )
    else:
        category_leaf = resolve_cloudflare_category_leaf(category_slug, policy=policy)
        object_key = (
            f"{policy.r2_prefix}/{category_leaf}/{datetime.now(timezone.utc):%Y/%m}/"
            f"{post_slug}/{post_slug}-{slot_role}-{slot.serial_code.lower()}.webp"
        )
    public_url, upload_payload, delivery_meta = upload_binary_to_cloudflare_r2(
        db,
        object_key=object_key,
        filename=f"{post_slug}-{slot_role}.webp",
        content=image_bytes,
    )

    from app.services.cloudflare.cloudflare_channel_service import (
        _fetch_integration_post_detail,
        _insert_markdown_inline_image,
        _integration_data_or_raise,
        _integration_request,
        _prepare_markdown_body,
        _strip_generated_body_images,
    )

    update_payload: dict[str, Any]
    if slot_role in {"cover", "hero"}:
        update_payload = {
            "coverImage": public_url,
            "coverAlt": str(metadata.get("cover_alt") or metadata.get("title") or "cover image").strip()[:180],
        }
    else:
        detail = _fetch_integration_post_detail(db, remote_post_id)
        title = str(detail.get("title") or metadata.get("title") or "Post").strip()
        body = _cloudflare_detail_body(detail)
        body = _strip_generated_body_images(body)
        body = _insert_markdown_inline_image(body, f"![{title} inline collage]({public_url})")
        update_payload = {"content": _prepare_markdown_body(title, body)}

    response = _integration_request(
        db,
        method="PUT",
        path=f"/api/integrations/posts/{remote_post_id}",
        json_payload=update_payload,
        timeout=120.0,
    )
    updated_post = _integration_data_or_raise(response)

    synced_post = slot.synced_cloudflare_post or db.execute(
        select(SyncedCloudflarePost).where(SyncedCloudflarePost.remote_id == remote_post_id)
    ).scalar_one_or_none()
    if synced_post and slot_role in {"cover", "hero"}:
        synced_post.thumbnail_url = public_url
        synced_post.render_metadata = _merge_metadata(
            synced_post.render_metadata,
            {"manual_image_slot_id": slot.id, "manual_image_serial_code": slot.serial_code},
        )
        db.add(synced_post)
        db.commit()

    try:
        from app.services.cloudflare.cloudflare_sync_service import sync_cloudflare_posts

        sync_result = sync_cloudflare_posts(db, include_non_published=True)
    except Exception as exc:  # noqa: BLE001
        sync_result = {"status": "failed", "error": str(exc)}

    return {
        "file_path": str(source_path),
        "public_url": public_url,
        "object_key": str(upload_payload.get("object_key") or object_key),
        "metadata": {
            "delivery": delivery_meta,
            "source_file_path": str(source_path),
            "cloudflare_update_post_id": remote_post_id,
            "cloudflare_update_payload": update_payload,
            "cloudflare_sync": sync_result,
            "cloudflare_updated_post": updated_post if isinstance(updated_post, dict) else {},
            "width": width,
            "height": height,
        },
    }


def _cloudflare_detail_body(detail: dict[str, Any]) -> str:
    for key in ("contentMarkdown", "markdown", "bodyMarkdown", "content", "body"):
        value = detail.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _is_mystery_blog(blog: Blog | None) -> bool:
    return bool(
        blog
        and (
            str(blog.profile_key or "").strip() == "world_mystery"
            or str(blog.content_category or "").strip().lower() == "mystery"
        )
    )


def build_slot_metadata(
    *,
    title: str | None = None,
    published_url: str | None = None,
    public_url: str | None = None,
    category_slug: str | None = None,
    category_name: str | None = None,
    slug: str | None = None,
    cover_alt: str | None = None,
    remote_post_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _merge_metadata(
        _slot_metadata(
            title=title,
            published_url=published_url,
            public_url=public_url,
            category_slug=category_slug,
            category_name=category_name,
            slug=slug,
            cover_alt=cover_alt,
            remote_post_id=remote_post_id,
        ),
        extra,
    )
