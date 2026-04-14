from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx
from PIL import Image
from slugify import slugify
from sqlalchemy import select
from sqlalchemy.orm import selectinload

REPO_ROOT = Path(__file__).resolve().parents[1]
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get(
        "BLOGGENT_DATABASE_URL",
        "postgresql://bloggent:bloggent@postgres:5432/bloggent",
    )
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Blog, ManagedChannel, R2AssetRelayoutMapping, SyncedBloggerPost  # noqa: E402
from app.services.content.article_service import build_r2_asset_object_key, resolve_r2_category_key  # noqa: E402
from app.services.blogger.blogger_sync_service import sync_blogger_posts_for_blog  # noqa: E402
from app.services.cloudflare.cloudflare_channel_service import (  # noqa: E402
    _integration_data_or_raise,
    _integration_request,
    _list_integration_posts,
)
from app.services.cloudflare.cloudflare_sync_service import sync_cloudflare_posts  # noqa: E402
from app.services.providers.factory import get_blogger_provider  # noqa: E402
from app.services.integrations.settings_service import get_settings_map  # noqa: E402
from app.services.integrations.storage_service import (  # noqa: E402
    _resolve_cloudflare_r2_configuration,
    cloudflare_r2_download_binary,
    normalize_r2_url_to_key,
    upload_binary_to_cloudflare_r2,
)

HTML_IMG_RE = re.compile(r"<img\b[^>]*\bsrc=['\"]([^'\"]+)['\"]", re.IGNORECASE)
SRCSET_RE = re.compile(r"\bsrcset=['\"]([^'\"]+)['\"]", re.IGNORECASE)
MD_IMG_RE = re.compile(r"!\[[^\]]*]\(([^)\s]+)\)")
LIVE_STATUSES = {"live", "published"}
TARGET_BLOGGER_BLOG_IDS = {34, 35, 36, 37}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Relayout LIVE post assets into canonical R2 WebP paths.")
    parser.add_argument(
        "--source",
        choices=("blogger-only", "all"),
        default="blogger-only",
        help="Process source scope.",
    )
    parser.add_argument(
        "--blog-id",
        action="append",
        type=int,
        default=[],
        help="Target Blogger blog id (repeatable).",
    )
    parser.add_argument(
        "--blog-slug",
        action="append",
        default=[],
        help="Target Blogger blog slug (repeatable).",
    )
    parser.add_argument(
        "--mode",
        choices=("dry-run", "canary", "full"),
        default="dry-run",
        help="Execution mode.",
    )
    parser.add_argument(
        "--canary-count",
        type=int,
        default=4,
        help="Posts per source in canary mode.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=45.0,
        help="HTTP timeout seconds.",
    )
    parser.add_argument(
        "--report-path",
        default="",
        help="Optional JSON report output path.",
    )
    return parser.parse_args(argv)


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _slug_token(value: Any, fallback: str = "") -> str:
    normalized = slugify(_safe_str(value), separator="-")
    return normalized or fallback


def _resolve_cloudflare_channel_slug(
    db,
    *,
    channel_id: Any,
    channel_name: Any,
    cache: dict[str, str] | None = None,
) -> str:
    raw_channel_id = _safe_str(channel_id)
    if cache is not None and raw_channel_id and raw_channel_id in cache:
        return cache[raw_channel_id]
    managed_channel = None
    if raw_channel_id:
        managed_channel = db.execute(
            select(ManagedChannel).where(
                ManagedChannel.provider == "cloudflare",
                ManagedChannel.channel_id == raw_channel_id,
            )
        ).scalar_one_or_none()
    metadata = managed_channel.channel_metadata if managed_channel and isinstance(managed_channel.channel_metadata, dict) else {}
    metadata_slug = _slug_token(metadata.get("slug"), fallback="")
    resolved = metadata_slug
    if not resolved:
        resolved = _slug_token(managed_channel.display_name if managed_channel else channel_name, fallback="")
    if not resolved and raw_channel_id:
        if ":" in raw_channel_id:
            tail_slug = _slug_token(raw_channel_id.split(":", 1)[1], fallback="")
            if tail_slug:
                resolved = tail_slug
        if not resolved:
            resolved = _slug_token(raw_channel_id, fallback="")
    if not resolved:
        resolved = "dongri-archive"
    if cache is not None and raw_channel_id:
        cache[raw_channel_id] = resolved
    return resolved


def _cloudflare_blog_group(channel_slug: str) -> str:
    return f"cloudflare/{_slug_token(channel_slug, fallback='dongri-archive')}"


def _looks_like_image_url(url: str) -> bool:
    lowered = (url or "").lower()
    if any(lowered.endswith(ext) for ext in (".webp", ".png", ".jpg", ".jpeg", ".gif", ".avif")):
        return True
    return "/assets/media/" in lowered or "/cdn-cgi/image/" in lowered


def _normalize_candidate_url(raw: str) -> str:
    candidate = unescape(_safe_str(raw))
    if not candidate:
        return ""
    candidate = candidate.strip().strip("()[]<>")
    for splitter in ("'", '"', "<", ">", "\r", "\n", "\t", " "):
        index = candidate.find(splitter)
        if index > 0:
            candidate = candidate[:index]
    candidate = candidate.strip().rstrip(".,);")
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    if "javascript:" in candidate.lower() or "data:" in candidate.lower():
        return ""
    return candidate


def _extract_srcset_urls(srcset_value: str) -> list[str]:
    urls: list[str] = []
    for part in (srcset_value or "").split(","):
        candidate = _normalize_candidate_url(part.strip().split(" ")[0].strip())
        if candidate:
            urls.append(candidate)
    return urls


def _extract_image_urls(content: str) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    for match in HTML_IMG_RE.finditer(content or ""):
        value = _normalize_candidate_url(match.group(1))
        if value and value not in seen and _looks_like_image_url(value):
            seen.add(value)
            results.append(value)
    for match in SRCSET_RE.finditer(content or ""):
        for value in _extract_srcset_urls(match.group(1)):
            if value and value not in seen and _looks_like_image_url(value):
                seen.add(value)
                results.append(value)
    for match in MD_IMG_RE.finditer(content or ""):
        value = _normalize_candidate_url(match.group(1))
        if value and value not in seen and _looks_like_image_url(value):
            seen.add(value)
            results.append(value)
    return results


def _url_ext(url: str) -> str:
    path = (urlparse(url).path or "").lower()
    if path.endswith(".webp"):
        return ".webp"
    if path.endswith(".png"):
        return ".png"
    if path.endswith(".jpg"):
        return ".jpg"
    if path.endswith(".jpeg"):
        return ".jpeg"
    return ""


def _slug_from_url(value: str, fallback: str) -> str:
    parsed = urlparse(_safe_str(value))
    path = unquote((parsed.path or "").strip("/"))
    if not path:
        return slugify(fallback, separator="-") or "post"
    token = path.split("/")[-1].strip()
    if token:
        return slugify(token, separator="-") or (slugify(fallback, separator="-") or "post")
    return slugify(fallback, separator="-") or "post"


def _normalize_target_key_for_layout(key: str) -> str:
    normalized = _safe_str(key).strip().lstrip("/")
    while normalized.startswith("assets/assets/"):
        normalized = normalized[len("assets/") :]
    return normalized


def _expected_prefix(*, blog_group: str, category_key: str, post_slug: str) -> str:
    return f"assets/media/{blog_group}/{category_key}/"


def _is_target_path(
    *,
    key: str,
    blog_group: str,
    category_key: str,
    post_slug: str,
) -> bool:
    normalized_key = _normalize_target_key_for_layout(key)
    if not normalized_key.lower().endswith(".webp"):
        return False
    prefix = _expected_prefix(blog_group=blog_group, category_key=category_key, post_slug=post_slug)
    if not normalized_key.startswith(prefix):
        return False
    return f"/{post_slug}/" in normalized_key


def _to_webp_bytes(raw_bytes: bytes) -> bytes:
    with Image.open(io.BytesIO(raw_bytes)) as loaded:
        output = io.BytesIO()
        converted = loaded if loaded.mode in {"RGB", "RGBA"} else loaded.convert("RGB")
        converted.save(output, format="WEBP", quality=86, method=6, optimize=True)
        return output.getvalue()


def _download_source_bytes(
    db,
    *,
    url: str,
    r2_public_prefix: str,
    timeout: float,
) -> bytes:
    key = normalize_r2_url_to_key(url)
    if key:
        try:
            return cloudflare_r2_download_binary(db, public_key=r2_public_prefix, key=key)
        except Exception:
            pass
    response = httpx.get(url, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    return response.content


def _fetch_live_html(url: str, *, timeout: float) -> str:
    candidate = _safe_str(url)
    if not candidate:
        return ""
    response = httpx.get(
        candidate,
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (BloggerGent relayout)"},
    )
    response.raise_for_status()
    return response.text


def _upsert_mapping(
    db,
    *,
    source_type: str,
    source_blog_id: int | None,
    source_post_id: str,
    source_post_url: str | None,
    legacy_url: str,
    legacy_key: str,
    migrated_url: str,
    migrated_key: str,
    blog_group: str,
    category_key: str,
    asset_role: str,
    notes: str = "",
) -> None:
    existing = db.execute(
        select(R2AssetRelayoutMapping).where(
            R2AssetRelayoutMapping.source_type == source_type,
            R2AssetRelayoutMapping.source_post_id == source_post_id,
            R2AssetRelayoutMapping.legacy_url == legacy_url,
            R2AssetRelayoutMapping.migrated_url == migrated_url,
        )
    ).scalar_one_or_none()
    if existing:
        existing.legacy_key = legacy_key or existing.legacy_key
        existing.migrated_key = migrated_key or existing.migrated_key
        existing.status = "mapped"
        existing.cleaned_at = None
        existing.notes = notes
        existing.blog_group = blog_group
        existing.category_key = category_key
        existing.asset_role = asset_role
        existing.source_blog_id = source_blog_id
        existing.source_post_url = source_post_url
        db.add(existing)
        db.flush()
        return

    mapping = R2AssetRelayoutMapping(
        source_type=source_type,
        source_blog_id=source_blog_id,
        source_post_id=source_post_id,
        source_post_url=source_post_url,
        legacy_url=legacy_url,
        legacy_key=legacy_key or None,
        migrated_url=migrated_url,
        migrated_key=migrated_key or None,
        blog_group=blog_group,
        category_key=category_key,
        asset_role=asset_role,
        status="mapped",
        notes=notes or None,
        cleaned_at=None,
    )
    db.add(mapping)
    db.flush()


def _process_single_image(
    db,
    *,
    source_type: str,
    source_blog_id: int | None,
    source_post_id: str,
    source_post_url: str | None,
    url: str,
    blog_group: str,
    mapping_blog_group: str,
    category_key: str,
    post_slug: str,
    asset_role: str,
    profile_key: str,
    primary_language: str,
    blog_slug: str,
    channel_slug: str,
    mode: str,
    r2_public_prefix: str,
    timeout: float,
    title: str,
    summary: str,
) -> dict[str, Any]:
    legacy_key = _normalize_target_key_for_layout(normalize_r2_url_to_key(url))
    if _is_target_path(key=legacy_key, blog_group=blog_group, category_key=category_key, post_slug=post_slug):
        return {
            "status": "skip",
            "reason": "already_target_path",
            "legacy_url": url,
            "legacy_key": legacy_key,
            "migrated_url": url,
            "migrated_key": legacy_key,
            "asset_role": asset_role,
        }

    if mode == "dry-run":
        placeholder_key = build_r2_asset_object_key(
            profile_key=profile_key,
            primary_language=primary_language,
            blog_slug=blog_slug,
            channel_slug=channel_slug,
            editorial_category_key=category_key,
            editorial_category_label=category_key,
            labels=[category_key],
            title=title,
            summary=summary,
            category_slug=category_key,
            post_slug=post_slug,
            asset_role=asset_role,
            content=b"",
        )
        return {
            "status": "plan",
            "reason": "candidate",
            "legacy_url": url,
            "legacy_key": legacy_key,
            "migrated_url": "",
            "migrated_key": placeholder_key,
            "asset_role": asset_role,
        }

    source_bytes = _download_source_bytes(
        db,
        url=url,
        r2_public_prefix=r2_public_prefix,
        timeout=timeout,
    )
    webp_bytes = _to_webp_bytes(source_bytes)
    object_key = build_r2_asset_object_key(
        profile_key=profile_key,
        primary_language=primary_language,
        blog_slug=blog_slug,
        channel_slug=channel_slug,
        editorial_category_key=category_key,
        editorial_category_label=category_key,
        labels=[category_key],
        title=title,
        summary=summary,
        category_slug=category_key,
        post_slug=post_slug,
        asset_role=asset_role,
        content=webp_bytes,
    )
    filename = f"{post_slug}-{asset_role}.webp"
    migrated_url, upload_payload, _delivery = upload_binary_to_cloudflare_r2(
        db,
        object_key=object_key,
        filename=filename,
        content=webp_bytes,
    )
    migrated_key = _safe_str(upload_payload.get("object_key") or object_key)
    _upsert_mapping(
        db,
        source_type=source_type,
        source_blog_id=source_blog_id,
        source_post_id=source_post_id,
        source_post_url=source_post_url,
        legacy_url=url,
        legacy_key=legacy_key,
        migrated_url=migrated_url,
        migrated_key=migrated_key,
        blog_group=mapping_blog_group,
        category_key=category_key,
        asset_role=asset_role,
    )
    return {
        "status": "updated",
        "reason": "uploaded",
        "legacy_url": url,
        "legacy_key": legacy_key,
        "migrated_url": migrated_url,
        "migrated_key": migrated_key,
        "asset_role": asset_role,
    }


def _replace_urls(content: str, replacements: dict[str, str]) -> str:
    updated = content
    for old_url, new_url in replacements.items():
        if old_url and new_url and old_url != new_url:
            updated = updated.replace(old_url, new_url)
    return updated


def _load_target_blogger_blogs(
    db,
    *,
    blog_ids: list[int],
    blog_slugs: list[str],
) -> list[Blog]:
    requested_ids = {int(item) for item in blog_ids if int(item) > 0}
    allowed_ids = set(TARGET_BLOGGER_BLOG_IDS)
    target_ids = allowed_ids & requested_ids if requested_ids else allowed_ids
    if not target_ids:
        return []
    query = (
        select(Blog)
        .where(
            Blog.is_active.is_(True),
            Blog.blogger_blog_id.is_not(None),
            Blog.id.in_(sorted(target_ids)),
        )
        .order_by(Blog.id.asc())
    )
    if blog_slugs:
        normalized = sorted({_safe_str(item) for item in blog_slugs if _safe_str(item)})
        if not normalized:
            return []
        query = query.where(Blog.slug.in_(normalized))
    return db.execute(query).scalars().all()


def _load_live_blogger_posts(
    db,
    *,
    blogs: list[Blog],
    mode: str,
    canary_count: int,
) -> list[SyncedBloggerPost]:
    posts: list[SyncedBloggerPost] = []
    for blog in blogs:
        rows = (
            db.execute(
                select(SyncedBloggerPost)
                .where(
                    SyncedBloggerPost.blog_id == blog.id,
                    SyncedBloggerPost.status.in_(["live", "LIVE", "published", "PUBLISHED"]),
                )
                .options(selectinload(SyncedBloggerPost.blog))
                .order_by(SyncedBloggerPost.published_at.desc().nullslast(), SyncedBloggerPost.id.desc())
            )
            .scalars()
            .all()
        )
        if mode == "canary":
            rows = rows[: max(canary_count, 1)]
        posts.extend(rows)
    return posts


def _fetch_cloudflare_post_detail(db, post_id: str) -> dict[str, Any]:
    response = _integration_request(
        db,
        method="GET",
        path=f"/api/integrations/posts/{post_id}",
        timeout=60.0,
    )
    data = _integration_data_or_raise(response)
    return data if isinstance(data, dict) else {}


def _build_report_base(mode: str, *, source: str, blog_ids: list[int], blog_slugs: list[str]) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "source": source,
        "target_blog_ids": sorted({int(item) for item in blog_ids if int(item) > 0}),
        "target_blog_slugs": sorted({_safe_str(item) for item in blog_slugs if _safe_str(item)}),
        "summary": {
            "posts_scanned": 0,
            "images_planned": 0,
            "images_migrated": 0,
            "already_target": 0,
            "legacy_cleanup_candidates": 0,
            "failed": 0,
            "posts_updated": 0,
            "posts_scanned_blogger": 0,
            "posts_scanned_cloudflare": 0,
            "posts_updated_blogger": 0,
            "posts_updated_cloudflare": 0,
        },
        "blogger": [],
        "cloudflare": [],
    }


def main() -> int:
    args = parse_args()
    source = args.source
    mode = args.mode
    canary_count = max(int(args.canary_count or 1), 1)
    timeout = float(args.timeout or 45.0)
    apply_changes = mode in {"canary", "full"}
    report = _build_report_base(
        mode,
        source=source,
        blog_ids=list(args.blog_id or []),
        blog_slugs=list(args.blog_slug or []),
    )
    legacy_cleanup_candidates: set[str] = set()

    with SessionLocal() as db:
        settings_map = get_settings_map(db)
        _account_id, _bucket, _access_key, _secret_key, public_base_url, r2_public_prefix = _resolve_cloudflare_r2_configuration(
            settings_map
        )
        if not public_base_url:
            raise SystemExit("cloudflare_r2_public_base_url is required.")

        target_blogs = _load_target_blogger_blogs(
            db,
            blog_ids=list(args.blog_id or []),
            blog_slugs=list(args.blog_slug or []),
        )

        try:
            for blog in target_blogs:
                sync_blogger_posts_for_blog(db, blog)
        except Exception:
            db.rollback()

        touched_blogger_blog_ids: set[int] = set()

        blogger_posts = _load_live_blogger_posts(
            db,
            blogs=target_blogs,
            mode=mode,
            canary_count=canary_count,
        )
        for post in blogger_posts:
            report["summary"]["posts_scanned"] += 1
            report["summary"]["posts_scanned_blogger"] += 1
            blog = post.blog
            if blog is None:
                continue
            post_slug = _slug_from_url(post.url or "", fallback=f"post-{post.remote_post_id}")
            labels = list(post.labels or [])
            category_key = resolve_r2_category_key(
                profile_key=blog.profile_key,
                primary_language=blog.primary_language,
                labels=labels,
                title=post.title,
                summary=post.excerpt_text,
            )
            normalized_blog_slug = _safe_str(blog.slug) or f"blog-{blog.id}"
            blog_group = f"google-blogger/{normalized_blog_slug}"
            extraction_source = "stored_content_html"
            extraction_html = _safe_str(post.content_html)
            live_url = _safe_str(post.url)
            if live_url:
                try:
                    extraction_html = _fetch_live_html(live_url, timeout=timeout)
                    extraction_source = "live_page"
                except Exception:
                    extraction_source = "stored_content_html_fallback"
            image_urls = _extract_image_urls(extraction_html or "")
            replacements: dict[str, str] = {}
            item_logs: list[dict[str, Any]] = []
            for index, image_url in enumerate(image_urls):
                asset_role = "cover" if index == 0 else f"inline-{index}"
                try:
                    item = _process_single_image(
                        db,
                        source_type="blogger",
                        source_blog_id=blog.id,
                        source_post_id=post.remote_post_id,
                        source_post_url=post.url,
                        url=image_url,
                        blog_group=blog_group,
                        mapping_blog_group=blog_group,
                        category_key=category_key,
                        post_slug=post_slug,
                        asset_role=asset_role,
                        profile_key=blog.profile_key,
                        primary_language=blog.primary_language,
                        blog_slug=normalized_blog_slug,
                        channel_slug="",
                        mode=mode,
                        r2_public_prefix=r2_public_prefix,
                        timeout=timeout,
                        title=post.title,
                        summary=post.excerpt_text,
                    )
                    item_logs.append(item)
                    legacy_key = _safe_str(item.get("legacy_key"))
                    migrated_key = _safe_str(item.get("migrated_key"))
                    if legacy_key and migrated_key and legacy_key != migrated_key:
                        legacy_cleanup_candidates.add(legacy_key)
                    if item["status"] == "plan":
                        report["summary"]["images_planned"] += 1
                    elif item["status"] == "updated":
                        report["summary"]["images_migrated"] += 1
                        replacements[image_url] = item["migrated_url"]
                    elif item["reason"] == "already_target_path":
                        report["summary"]["already_target"] += 1
                    else:
                        report["summary"]["already_target"] += 1
                except Exception as exc:  # noqa: BLE001
                    item_logs.append(
                        {
                            "status": "failed",
                            "reason": str(exc),
                            "legacy_url": image_url,
                            "asset_role": asset_role,
                        }
                    )
                    report["summary"]["failed"] += 1

            post_updated = False
            if apply_changes and replacements:
                updated_html = _replace_urls(post.content_html or "", replacements)
                try:
                    provider = get_blogger_provider(db, blog)
                    provider.update_post(
                        post_id=post.remote_post_id,
                        title=post.title,
                        content=updated_html,
                        labels=labels,
                        meta_description=(post.excerpt_text or "")[:300],
                    )
                    post.content_html = updated_html
                    post.thumbnail_url = replacements.get(image_urls[0], post.thumbnail_url) if image_urls else post.thumbnail_url
                    post.synced_at = datetime.now(timezone.utc)
                    db.add(post)
                    db.flush()
                    touched_blogger_blog_ids.add(blog.id)
                    post_updated = True
                    report["summary"]["posts_updated"] += 1
                    report["summary"]["posts_updated_blogger"] += 1
                except Exception as exc:  # noqa: BLE001
                    report["summary"]["failed"] += 1
                    item_logs.append(
                        {
                            "status": "failed",
                            "reason": f"blogger_update_failed:{exc}",
                            "legacy_url": "",
                            "asset_role": "post-update",
                        }
                    )

            report["blogger"].append(
                {
                    "blog_id": blog.id,
                    "blog_name": blog.name,
                    "post_id": post.remote_post_id,
                    "post_url": post.url,
                    "post_slug": post_slug,
                    "blog_group": blog_group,
                    "category_key": category_key,
                    "image_source": extraction_source,
                    "items": item_logs,
                    "post_updated": post_updated,
                }
            )

        if apply_changes:
            for blog_id in sorted(touched_blogger_blog_ids):
                blog = db.get(Blog, blog_id)
                if blog is None:
                    continue
                sync_blogger_posts_for_blog(db, blog)

        if source == "all":
            cloudflare_posts = _list_integration_posts(db)
            cloudflare_live = [
                item
                for item in cloudflare_posts
                if _safe_str(item.get("status")).lower() in LIVE_STATUSES and _safe_str(item.get("id"))
            ]
            if mode == "canary":
                cloudflare_live = cloudflare_live[:canary_count]

            channel_slug_cache: dict[str, str] = {}
            for row in cloudflare_live:
                report["summary"]["posts_scanned"] += 1
                report["summary"]["posts_scanned_cloudflare"] += 1
                post_id = _safe_str(row.get("id"))
                detail = _fetch_cloudflare_post_detail(db, post_id)
                if not detail:
                    continue
                post_slug = _safe_str(detail.get("slug")) or _slug_from_url(_safe_str(detail.get("publicUrl")), fallback=f"post-{post_id}")
                post_url = _safe_str(detail.get("publicUrl") or detail.get("url"))
                content = _safe_str(detail.get("content") or detail.get("contentMarkdown") or detail.get("content_markdown"))
                cover_image = _safe_str(detail.get("coverImage"))
                category = detail.get("category") if isinstance(detail.get("category"), dict) else {}
                category_slug = _safe_str(category.get("slug"))
                category_key = resolve_r2_category_key(
                    profile_key="archive",
                    category_slug=category_slug or "uncategorized",
                )
                channel_slug = _resolve_cloudflare_channel_slug(
                    db,
                    channel_id=detail.get("channelId") or row.get("channelId"),
                    channel_name=detail.get("channelName") or row.get("channelName"),
                    cache=channel_slug_cache,
                )
                blog_group = _cloudflare_blog_group(channel_slug)

                ordered_urls: list[str] = []
                if cover_image:
                    ordered_urls.append(cover_image)
                for image_url in _extract_image_urls(content):
                    if image_url not in ordered_urls:
                        ordered_urls.append(image_url)

                replacements: dict[str, str] = {}
                item_logs: list[dict[str, Any]] = []
                for index, image_url in enumerate(ordered_urls):
                    asset_role = "cover" if index == 0 and image_url == cover_image else f"inline-{index}"
                    try:
                        item = _process_single_image(
                            db,
                            source_type="cloudflare",
                            source_blog_id=None,
                            source_post_id=post_id,
                            source_post_url=post_url,
                            url=image_url,
                            blog_group=blog_group,
                            mapping_blog_group=blog_group,
                            category_key=category_key,
                            post_slug=post_slug,
                            asset_role=asset_role,
                            profile_key="archive",
                            primary_language="ko",
                            blog_slug="",
                            channel_slug=channel_slug,
                            mode=mode,
                            r2_public_prefix=r2_public_prefix,
                            timeout=timeout,
                            title=_safe_str(detail.get("title") or post_slug),
                            summary=_safe_str(detail.get("excerpt")),
                        )
                        item_logs.append(item)
                        legacy_key = _safe_str(item.get("legacy_key"))
                        migrated_key = _safe_str(item.get("migrated_key"))
                        if legacy_key and migrated_key and legacy_key != migrated_key:
                            legacy_cleanup_candidates.add(legacy_key)
                        if item["status"] == "plan":
                            report["summary"]["images_planned"] += 1
                        elif item["status"] == "updated":
                            report["summary"]["images_migrated"] += 1
                            replacements[image_url] = item["migrated_url"]
                        elif item["reason"] == "already_target_path":
                            report["summary"]["already_target"] += 1
                        else:
                            report["summary"]["already_target"] += 1
                    except Exception as exc:  # noqa: BLE001
                        item_logs.append(
                            {
                                "status": "failed",
                                "reason": str(exc),
                                "legacy_url": image_url,
                                "asset_role": asset_role,
                            }
                        )
                        report["summary"]["failed"] += 1

                post_updated = False
                if apply_changes and replacements:
                    updated_content = _replace_urls(content, replacements)
                    update_payload: dict[str, Any] = {}
                    if updated_content != content:
                        update_payload["content"] = updated_content
                    if cover_image and cover_image in replacements:
                        update_payload["coverImage"] = replacements[cover_image]
                    if update_payload:
                        try:
                            response = _integration_request(
                                db,
                                method="PUT",
                                path=f"/api/integrations/posts/{post_id}",
                                json_payload=update_payload,
                                timeout=120.0,
                            )
                            _integration_data_or_raise(response)
                            post_updated = True
                            report["summary"]["posts_updated"] += 1
                            report["summary"]["posts_updated_cloudflare"] += 1
                        except Exception as exc:  # noqa: BLE001
                            report["summary"]["failed"] += 1
                            item_logs.append(
                                {
                                    "status": "failed",
                                    "reason": f"cloudflare_update_failed:{exc}",
                                    "legacy_url": "",
                                    "asset_role": "post-update",
                                }
                            )

                report["cloudflare"].append(
                    {
                        "post_id": post_id,
                        "post_url": post_url,
                        "post_slug": post_slug,
                        "blog_group": blog_group,
                        "channel_slug": channel_slug,
                        "category_key": category_key,
                        "items": item_logs,
                        "post_updated": post_updated,
                    }
                )

            if apply_changes:
                sync_cloudflare_posts(db, include_non_published=False)

        report["summary"]["legacy_cleanup_candidates"] = len(legacy_cleanup_candidates)

        db.commit()

    report_text = json.dumps(report, ensure_ascii=False, indent=2)
    print(report_text)
    if args.report_path:
        report_path = Path(args.report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
