from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
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
from app.models.entities import Blog, ManagedChannel, SyncedBloggerPost, SyncedCloudflarePost  # noqa: E402
from app.services.integrations.storage_service import normalize_r2_url_to_key  # noqa: E402

TARGET_BLOGGER_BLOG_IDS = {34, 35, 36, 37}
IMG_SRC_RE = re.compile(r"<img\b[^>]*\bsrc=['\"]([^'\"]+)['\"]", re.IGNORECASE)
SRCSET_RE = re.compile(r"\bsrcset=['\"]([^'\"]+)['\"]", re.IGNORECASE)
RAW_IMAGE_URL_RE = re.compile(r"https?://[^\s'\"<>()]+\.(?:webp|png|jpg|jpeg|gif|avif)", re.IGNORECASE)
LIVE_STATUSES = {"live", "LIVE", "published", "PUBLISHED"}
MYSTERY_BLOG_ID = 35
MYSTERY_SLUG_LAYOUT_RE = re.compile(
    r"^the-midnight-archives/[a-z0-9-]+/\d{4}/\d{2}/([a-z0-9-]+)/([a-z0-9-]+)\.webp$",
    re.IGNORECASE,
)
FORBIDDEN_KEY_TOKENS = (
    "assets/assets/",
    "media/posts",
    "media/blogger",
    "assets/media/google-blogger/",
    "cover-",
    "hero-refresh-",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify live image URLs follow R2 layout policy v2.")
    parser.add_argument("--source", choices=("blogger", "cloudflare", "all"), default="all")
    parser.add_argument(
        "--content-source",
        choices=("db", "live"),
        default="db",
        help="For Blogger source: inspect synced DB HTML (db) or fetch live post URL (live).",
    )
    parser.add_argument("--blog-id", action="append", type=int, default=[], help="Target Blogger blog id (repeatable).")
    parser.add_argument("--blog-slug", action="append", default=[], help="Target Blogger blog slug (repeatable).")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds.")
    parser.add_argument("--report-path", default="", help="Optional JSON report output path.")
    return parser.parse_args(argv)


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _slug_token(value: Any, fallback: str = "") -> str:
    normalized = slugify(_safe_str(value), separator="-")
    return normalized or fallback


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
        candidate = _normalize_candidate_url(part.split(" ")[0])
        if candidate:
            urls.append(candidate)
    return urls


def _extract_image_urls(content: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for match in IMG_SRC_RE.finditer(content or ""):
        candidate = _normalize_candidate_url(match.group(1))
        if candidate and candidate not in seen:
            seen.add(candidate)
            urls.append(candidate)
    for match in SRCSET_RE.finditer(content or ""):
        for candidate in _extract_srcset_urls(match.group(1)):
            if candidate and candidate not in seen:
                seen.add(candidate)
                urls.append(candidate)
    return urls


def _extract_raw_image_urls(content: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for match in RAW_IMAGE_URL_RE.finditer(content or ""):
        candidate = _normalize_candidate_url(match.group(0))
        if candidate and candidate not in seen:
            seen.add(candidate)
            urls.append(candidate)
    return urls


def _is_api_image_url(url: str) -> bool:
    candidate = _safe_str(url)
    if not candidate:
        return False
    parsed = urlparse(candidate)
    host = (parsed.netloc or "").lower()
    if host != "api.dongriarchive.com":
        return False
    path = (parsed.path or "").lower()
    if "/assets/" not in path:
        return False
    return any(path.endswith(ext) for ext in (".webp", ".png", ".jpg", ".jpeg", ".gif", ".avif"))


def _canonical_media_key(url: str) -> str:
    key = _safe_str(normalize_r2_url_to_key(url)).strip().lstrip("/")
    while key.startswith("assets/assets/"):
        key = key[len("assets/") :]
    if key.startswith("assets/"):
        key = key[len("assets/") :]
    return key


def _is_valid_mystery_slug_key(canonical_key: str) -> bool:
    key = _safe_str(canonical_key).lstrip("/")
    match = MYSTERY_SLUG_LAYOUT_RE.fullmatch(key)
    if match is None:
        return False
    return _safe_str(match.group(1)).lower() == _safe_str(match.group(2)).lower()


def _forbidden_tokens_for_key(canonical_key: str) -> list[str]:
    lowered = _safe_str(canonical_key).lower()
    return [token for token in FORBIDDEN_KEY_TOKENS if token in lowered]


def _resolve_cloudflare_channel_slug(managed_channel: ManagedChannel | None) -> str:
    metadata = managed_channel.channel_metadata if managed_channel and isinstance(managed_channel.channel_metadata, dict) else {}
    metadata_slug = _slug_token(metadata.get("slug"), fallback="")
    if metadata_slug:
        return metadata_slug
    display_name_slug = _slug_token(managed_channel.display_name if managed_channel else "", fallback="")
    if display_name_slug:
        return display_name_slug
    channel_id = _safe_str(managed_channel.channel_id if managed_channel else "")
    if channel_id:
        if ":" in channel_id:
            tail_slug = _slug_token(channel_id.split(":", 1)[1], fallback="")
            if tail_slug:
                return tail_slug
        channel_slug = _slug_token(channel_id, fallback="")
        if channel_slug:
            return channel_slug
    return "dongri-archive"


def _load_target_blogs(db, *, blog_ids: list[int], blog_slugs: list[str]) -> list[Blog]:
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


def _probe_image(
    client: httpx.Client,
    cache: dict[str, dict[str, Any]],
    image_url: str,
) -> dict[str, Any]:
    if image_url not in cache:
        try:
            response = client.get(image_url)
            content_type = _safe_str(response.headers.get("content-type")).lower()
            cache[image_url] = {
                "ok": response.status_code < 400 and content_type.startswith("image/"),
                "status_code": response.status_code,
                "content_type": content_type,
            }
        except Exception as exc:  # noqa: BLE001
            cache[image_url] = {
                "ok": False,
                "error": str(exc),
            }
    return cache[image_url]


def main() -> int:
    args = parse_args()
    timeout = float(args.timeout or 30.0)
    source = args.source
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "content_source": args.content_source,
        "target_blog_ids": sorted({int(item) for item in args.blog_id if int(item) > 0}),
        "target_blog_slugs": sorted({_safe_str(item) for item in args.blog_slug if _safe_str(item)}),
        "summary": {
            "blogs_scanned": 0,
            "posts_scanned": 0,
            "images_checked": 0,
            "pages_with_broken_images": 0,
            "broken_image_total": 0,
            "pages_with_non_slug_prefix": 0,
            "non_slug_prefix_total": 0,
            "pages_with_forbidden_token": 0,
            "forbidden_token_total": 0,
            "posts_scanned_blogger": 0,
            "posts_scanned_cloudflare": 0,
        },
        "blogger": [],
        "cloudflare_channels": [],
    }

    with SessionLocal() as db:
        blogger_blogs = _load_target_blogs(
            db,
            blog_ids=list(args.blog_id or []),
            blog_slugs=list(args.blog_slug or []),
        ) if source in {"blogger", "all"} else []
        blogger_blog_map = {blog.id: blog for blog in blogger_blogs}

        blogger_posts = (
            db.execute(
                select(SyncedBloggerPost)
                .where(
                    SyncedBloggerPost.blog_id.in_(sorted(blogger_blog_map.keys())) if blogger_blog_map else False,
                    SyncedBloggerPost.status.in_(sorted(LIVE_STATUSES)),
                    SyncedBloggerPost.url.is_not(None),
                )
                .options(selectinload(SyncedBloggerPost.blog))
                .order_by(SyncedBloggerPost.blog_id.asc(), SyncedBloggerPost.published_at.desc().nullslast(), SyncedBloggerPost.id.desc())
            )
            .scalars()
            .all()
        ) if source in {"blogger", "all"} and blogger_blog_map else []

        cloudflare_posts = (
            db.execute(
                select(SyncedCloudflarePost)
                .where(
                    SyncedCloudflarePost.status.in_(sorted(LIVE_STATUSES)),
                    SyncedCloudflarePost.url.is_not(None),
                )
                .options(selectinload(SyncedCloudflarePost.managed_channel))
                .order_by(SyncedCloudflarePost.managed_channel_id.asc(), SyncedCloudflarePost.published_at.desc().nullslast(), SyncedCloudflarePost.id.desc())
            )
            .scalars()
            .all()
        ) if source in {"cloudflare", "all"} else []

    report["summary"]["blogs_scanned"] = len(blogger_blogs)
    blogger_buckets: dict[int, dict[str, Any]] = {}
    cloudflare_buckets: dict[str, dict[str, Any]] = {}

    with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
        image_probe_cache: dict[str, dict[str, Any]] = {}

        for post in blogger_posts:
            blog = post.blog
            if blog is None:
                continue
            report["summary"]["posts_scanned"] += 1
            report["summary"]["posts_scanned_blogger"] += 1
            expected_prefix = f"media/google-blogger/{_safe_str(blog.slug)}/"
            page_url = _safe_str(post.url)
            broken_items: list[dict[str, Any]] = []
            non_prefix_items: list[dict[str, Any]] = []
            forbidden_token_items: list[dict[str, Any]] = []

            image_urls: list[str] = []
            if args.content_source == "live":
                try:
                    response = client.get(page_url)
                    response.raise_for_status()
                    image_urls = [url for url in _extract_image_urls(response.text) if _is_api_image_url(url)]
                except Exception as exc:  # noqa: BLE001
                    image_urls = []
                    broken_items.append({"src": page_url, "reason": f"page_fetch_failed:{exc}"})
            else:
                db_urls = []
                thumbnail = _safe_str(post.thumbnail_url)
                if thumbnail:
                    db_urls.append(thumbnail)
                db_urls.extend(_extract_image_urls(post.content_html or ""))
                db_urls.extend(_extract_raw_image_urls(post.content_html or ""))
                dedup: list[str] = []
                seen_urls: set[str] = set()
                for candidate in db_urls:
                    normalized = _normalize_candidate_url(candidate)
                    if not normalized or not _is_api_image_url(normalized) or normalized in seen_urls:
                        continue
                    seen_urls.add(normalized)
                    dedup.append(normalized)
                image_urls = dedup

            report["summary"]["images_checked"] += len(image_urls)
            for image_url in image_urls:
                canonical_key = _canonical_media_key(image_url)
                forbidden_tokens = _forbidden_tokens_for_key(canonical_key)
                if forbidden_tokens:
                    forbidden_token_items.append(
                        {
                            "src": image_url,
                            "canonical_key": canonical_key,
                            "tokens": forbidden_tokens,
                        }
                    )
                if blog.id == MYSTERY_BLOG_ID:
                    key_ok = _is_valid_mystery_slug_key(canonical_key)
                    if canonical_key and not key_ok:
                        non_prefix_items.append(
                            {
                                "src": image_url,
                                "canonical_key": canonical_key,
                                "expected_layout": "the-midnight-archives/<category>/YYYY/MM/<slug>/<slug>.webp",
                            }
                        )
                elif canonical_key and not canonical_key.startswith(expected_prefix):
                    non_prefix_items.append(
                        {
                            "src": image_url,
                            "canonical_key": canonical_key,
                            "expected_prefix": expected_prefix,
                        }
                    )
                probe = _probe_image(client, image_probe_cache, image_url)
                if not bool(probe.get("ok")):
                    broken_items.append(
                        {
                            "src": image_url,
                            "status_code": probe.get("status_code"),
                            "content_type": probe.get("content_type"),
                            "error": probe.get("error"),
                        }
                    )

            bucket = blogger_buckets.setdefault(
                blog.id,
                {
                    "blog_id": blog.id,
                    "blog_slug": blog.slug,
                    "posts_scanned": 0,
                    "images_checked": 0,
                    "broken_image_total": 0,
                    "non_slug_prefix_total": 0,
                    "forbidden_token_total": 0,
                    "items": [],
                },
            )
            bucket["posts_scanned"] += 1
            bucket["images_checked"] += len(image_urls)
            bucket["broken_image_total"] += len(broken_items)
            bucket["non_slug_prefix_total"] += len(non_prefix_items)
            bucket["forbidden_token_total"] += len(forbidden_token_items)
            if broken_items or non_prefix_items or forbidden_token_items:
                bucket["items"].append(
                    {
                        "post_id": post.remote_post_id,
                        "post_url": page_url,
                        "broken_images": broken_items,
                        "non_slug_prefix_images": non_prefix_items,
                        "forbidden_token_images": forbidden_token_items,
                    }
                )

            if broken_items:
                report["summary"]["pages_with_broken_images"] += 1
                report["summary"]["broken_image_total"] += len(broken_items)
            if non_prefix_items:
                report["summary"]["pages_with_non_slug_prefix"] += 1
                report["summary"]["non_slug_prefix_total"] += len(non_prefix_items)
            if forbidden_token_items:
                report["summary"]["pages_with_forbidden_token"] += 1
                report["summary"]["forbidden_token_total"] += len(forbidden_token_items)

        for post in cloudflare_posts:
            report["summary"]["posts_scanned"] += 1
            report["summary"]["posts_scanned_cloudflare"] += 1
            managed_channel = post.managed_channel
            channel_slug = _resolve_cloudflare_channel_slug(managed_channel)
            expected_prefix = f"media/cloudflare/{channel_slug}/"
            page_url = _safe_str(post.url)
            broken_items: list[dict[str, Any]] = []
            non_prefix_items: list[dict[str, Any]] = []
            forbidden_token_items: list[dict[str, Any]] = []
            try:
                response = client.get(page_url)
                response.raise_for_status()
                image_urls = [url for url in _extract_image_urls(response.text) if _is_api_image_url(url)]
            except Exception as exc:  # noqa: BLE001
                image_urls = []
                broken_items.append({"src": page_url, "reason": f"page_fetch_failed:{exc}"})

            report["summary"]["images_checked"] += len(image_urls)
            for image_url in image_urls:
                canonical_key = _canonical_media_key(image_url)
                forbidden_tokens = _forbidden_tokens_for_key(canonical_key)
                if forbidden_tokens:
                    forbidden_token_items.append(
                        {
                            "src": image_url,
                            "canonical_key": canonical_key,
                            "tokens": forbidden_tokens,
                        }
                    )
                if canonical_key and not canonical_key.startswith(expected_prefix):
                    non_prefix_items.append(
                        {
                            "src": image_url,
                            "canonical_key": canonical_key,
                            "expected_prefix": expected_prefix,
                        }
                    )
                probe = _probe_image(client, image_probe_cache, image_url)
                if not bool(probe.get("ok")):
                    broken_items.append(
                        {
                            "src": image_url,
                            "status_code": probe.get("status_code"),
                            "content_type": probe.get("content_type"),
                            "error": probe.get("error"),
                        }
                    )

            channel_key = f"{_safe_str(post.managed_channel_id)}:{channel_slug}"
            bucket = cloudflare_buckets.setdefault(
                channel_key,
                {
                    "managed_channel_id": post.managed_channel_id,
                    "channel_id": _safe_str(managed_channel.channel_id if managed_channel else ""),
                    "channel_name": _safe_str(managed_channel.display_name if managed_channel else ""),
                    "channel_slug": channel_slug,
                    "posts_scanned": 0,
                    "images_checked": 0,
                    "broken_image_total": 0,
                    "non_slug_prefix_total": 0,
                    "forbidden_token_total": 0,
                    "items": [],
                },
            )
            bucket["posts_scanned"] += 1
            bucket["images_checked"] += len(image_urls)
            bucket["broken_image_total"] += len(broken_items)
            bucket["non_slug_prefix_total"] += len(non_prefix_items)
            bucket["forbidden_token_total"] += len(forbidden_token_items)
            if broken_items or non_prefix_items or forbidden_token_items:
                bucket["items"].append(
                    {
                        "post_id": post.remote_post_id,
                        "post_url": page_url,
                        "broken_images": broken_items,
                        "non_slug_prefix_images": non_prefix_items,
                        "forbidden_token_images": forbidden_token_items,
                    }
                )

            if broken_items:
                report["summary"]["pages_with_broken_images"] += 1
                report["summary"]["broken_image_total"] += len(broken_items)
            if non_prefix_items:
                report["summary"]["pages_with_non_slug_prefix"] += 1
                report["summary"]["non_slug_prefix_total"] += len(non_prefix_items)
            if forbidden_token_items:
                report["summary"]["pages_with_forbidden_token"] += 1
                report["summary"]["forbidden_token_total"] += len(forbidden_token_items)

    report["blogger"] = [blogger_buckets[key] for key in sorted(blogger_buckets)]
    report["cloudflare_channels"] = [cloudflare_buckets[key] for key in sorted(cloudflare_buckets)]
    report_text = json.dumps(report, ensure_ascii=False, indent=2)
    print(report_text)
    if args.report_path:
        report_path = Path(args.report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
