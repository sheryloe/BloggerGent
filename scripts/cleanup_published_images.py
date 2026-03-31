#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import selectinload


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
LOCAL_STORAGE_ROOT = REPO_ROOT / "storage"
DEFAULT_REPORT_DIR = LOCAL_STORAGE_ROOT / "reports"

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get(
        "BLOGGENT_DATABASE_URL",
        "postgresql://bloggent:bloggent@localhost:15432/bloggent",
    )
if "STORAGE_ROOT" not in os.environ:
    os.environ["STORAGE_ROOT"] = str(LOCAL_STORAGE_ROOT)

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import BloggerPost, PostStatus, SyncedBloggerPost  # noqa: E402
from app.services.cloudflare_channel_service import (  # noqa: E402
    _integration_data_or_raise,
    _integration_request,
    _list_integration_posts,
)
from app.services.providers.factory import get_blogger_provider  # noqa: E402
from app.services.settings_service import get_settings_map  # noqa: E402
from app.services.storage_service import (  # noqa: E402
    _resolve_cloudflare_r2_configuration,
    cloudflare_r2_download_binary,
    cloudflare_r2_object_exists,
    cloudflare_r2_object_size,
    delete_cloudflare_r2_asset,
    normalize_r2_url_to_key,
    upload_binary_to_cloudflare_r2,
)


IMG_SRC_RE = re.compile(r"<img\b[^>]*\bsrc=['\"]([^'\"]+)['\"]", re.IGNORECASE)
SRCSET_RE = re.compile(r"\bsrcset=['\"]([^'\"]+)['\"]", re.IGNORECASE)
MD_IMG_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
URL_RE = re.compile(r"https?://[^\s'\"<>)\]]+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cleanup R2 images for published Google/Cloudflare posts.")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default is dry-run).")
    parser.add_argument("--quality", type=int, default=82, help="WebP quality setting (default: 82).")
    parser.add_argument("--scope", choices=("google", "cloudflare", "all"), default="all", help="Target scope.")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR), help="Report directory.")
    parser.add_argument("--batch-size", type=int, default=0, help="Optional batch size for post processing.")
    parser.add_argument("--limit", type=int, default=0, help="Optional limit for posts per scope.")
    parser.add_argument("--delete-png", action="store_true", help="Delete PNG files only when no published references remain.")
    parser.add_argument("--delete-orphan", action="store_true", help="Delete orphan PNG/WebP files not referenced by any published post.")
    return parser.parse_args()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_str(value: object | None) -> str:
    return str(value or "").strip()


def _chunked(items: list[Any], size: int) -> list[list[Any]]:
    if size <= 0:
        return [items]
    return [items[index : index + size] for index in range(0, len(items), size)]


def _extract_srcset_urls(srcset_value: str) -> list[str]:
    urls: list[str] = []
    for part in (srcset_value or "").split(","):
        candidate = part.strip().split(" ")[0].strip()
        if candidate:
            urls.append(candidate)
    return urls


def _extract_urls(content: str) -> list[str]:
    urls: set[str] = set()
    for match in IMG_SRC_RE.finditer(content or ""):
        urls.add(match.group(1).strip())
    for match in SRCSET_RE.finditer(content or ""):
        for candidate in _extract_srcset_urls(match.group(1)):
            urls.add(candidate)
    for match in MD_IMG_RE.finditer(content or ""):
        urls.add(match.group(1).strip())
    for match in URL_RE.finditer(content or ""):
        urls.add(match.group(0).strip())
    return [url for url in urls if url]


def _is_r2_url(url: str, public_base_url: str) -> bool:
    if not public_base_url:
        return False
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return False
    base = urlparse(public_base_url)
    if base.netloc and parsed.netloc.lower() != base.netloc.lower():
        return False
    return True


def _key_extension(key: str) -> str:
    lower = key.lower()
    if lower.endswith(".png"):
        return "png"
    if lower.endswith(".webp"):
        return "webp"
    return ""


def _swap_extension(url: str, old_ext: str, new_ext: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or ""
    if not path.lower().endswith(old_ext.lower()):
        return url
    new_path = path[: -len(old_ext)] + new_ext
    return urlunparse(parsed._replace(path=new_path))


def _swap_png_to_webp(url: str) -> str:
    return _swap_extension(url, ".png", ".webp")


def _apply_replacements(content: str, replacements: dict[str, str]) -> str:
    updated = content
    for old, new in replacements.items():
        if old in updated:
            updated = updated.replace(old, new)
    return updated

def _load_google_published_items(db, limit: int) -> list[dict[str, Any]]:
    posts = (
        db.execute(
            select(BloggerPost)
            .options(selectinload(BloggerPost.blog), selectinload(BloggerPost.article))
            .where(BloggerPost.post_status == PostStatus.PUBLISHED)
            .order_by(BloggerPost.published_at.desc().nullslast(), BloggerPost.id.desc())
        )
        .scalars()
        .all()
    )
    if limit > 0:
        posts = posts[:limit]

    remote_ids = [post.blogger_post_id for post in posts if _safe_str(post.blogger_post_id)]
    synced_posts = []
    if remote_ids:
        synced_posts = (
            db.execute(
                select(SyncedBloggerPost).where(SyncedBloggerPost.remote_post_id.in_(remote_ids))
            )
            .scalars()
            .all()
        )
    synced_map = {(post.blog_id, post.remote_post_id): post for post in synced_posts}

    items: list[dict[str, Any]] = []
    for post in posts:
        blog = post.blog
        if not blog:
            continue
        synced_post = synced_map.get((post.blog_id, post.blogger_post_id))
        content = ""
        if synced_post and _safe_str(synced_post.content_html):
            content = synced_post.content_html
        elif post.article:
            content = _safe_str(post.article.assembled_html) or _safe_str(post.article.html_article)
        if not content:
            continue

        labels = []
        if synced_post and isinstance(synced_post.labels, list):
            labels = synced_post.labels
        elif post.article and isinstance(post.article.labels, list):
            labels = post.article.labels

        items.append(
            {
                "source": "google",
                "post_id": _safe_str(post.blogger_post_id),
                "blog_id": post.blog_id,
                "blog": blog,
                "title": _safe_str(synced_post.title if synced_post else (post.article.title if post.article else "")),
                "labels": [label for label in labels if _safe_str(label)],
                "meta_description": _safe_str(post.article.meta_description if post.article else ""),
                "content": content,
                "synced_post": synced_post,
                "article": post.article,
            }
        )

    return items


def _load_google_orphan_contents(db, published_ids: set[str]) -> list[str]:
    posts = (
        db.execute(
            select(BloggerPost)
            .options(selectinload(BloggerPost.blog), selectinload(BloggerPost.article))
            .order_by(BloggerPost.id.desc())
        )
        .scalars()
        .all()
    )
    candidates = [post for post in posts if _safe_str(post.blogger_post_id) not in published_ids]
    if not candidates:
        return []
    remote_ids = [post.blogger_post_id for post in candidates if _safe_str(post.blogger_post_id)]
    if not remote_ids:
        return []
    synced_posts = (
        db.execute(select(SyncedBloggerPost).where(SyncedBloggerPost.remote_post_id.in_(remote_ids)))
        .scalars()
        .all()
    )
    contents = []
    for post in synced_posts:
        if _safe_str(post.content_html):
            contents.append(post.content_html)
    return contents


def _cloudflare_content(post: dict[str, Any]) -> str:
    return _safe_str(
        post.get("contentMarkdown")
        or post.get("content_markdown")
        or post.get("content")
        or post.get("excerpt")
    )


def _load_cloudflare_items(db, limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    posts = _list_integration_posts(db)
    if limit > 0:
        posts = posts[:limit]
    for post in posts:
        status = _safe_str(post.get("status")).lower()
        if status not in {"published", "live"}:
            continue
        content = _cloudflare_content(post)
        if not content:
            continue
        items.append(
            {
                "source": "cloudflare",
                "post_id": _safe_str(post.get("id") or post.get("slug")),
                "status": status or "published",
                "title": _safe_str(post.get("title")),
                "content": content,
                "raw": post,
            }
        )
    return items


def _load_cloudflare_orphan_contents(db) -> list[str]:
    contents: list[str] = []
    posts = _list_integration_posts(db)
    for post in posts:
        status = _safe_str(post.get("status")).lower()
        if status in {"published", "live"}:
            continue
        content = _cloudflare_content(post)
        if content:
            contents.append(content)
    return contents


def _collect_references(
    items: list[dict[str, Any]],
    public_base_url: str,
) -> tuple[list[dict[str, str]], list[set[str]]]:
    refs: list[dict[str, str]] = []
    per_item_urls: list[set[str]] = []
    for item in items:
        content = _safe_str(item.get("content"))
        urls = set()
        for url in _extract_urls(content):
            if not _is_r2_url(url, public_base_url):
                continue
            key = normalize_r2_url_to_key(url)
            if not key:
                continue
            ext = _key_extension(key)
            if not ext:
                continue
            urls.add(url)
            refs.append({"url": url, "key": key, "ext": ext})
        per_item_urls.append(urls)
    return refs, per_item_urls


def _item_identity(item: dict[str, Any]) -> tuple[str, str, str]:
    source = _safe_str(item.get("source")).lower()
    post_id = _safe_str(item.get("post_id"))
    if source == "google":
        return source, _safe_str(item.get("blog_id")), post_id
    return source, "", post_id


def _collect_png_keys_from_items(
    items: list[dict[str, Any]],
    public_base_url: str,
    *,
    content_overrides: dict[tuple[str, str, str], str] | None = None,
) -> set[str]:
    overrides = content_overrides or {}
    keys: set[str] = set()
    for item in items:
        identity = _item_identity(item)
        content = _safe_str(overrides.get(identity, item.get("content")))
        if not content:
            continue
        for url in _extract_urls(content):
            if not _is_r2_url(url, public_base_url):
                continue
            key = normalize_r2_url_to_key(url)
            if not key:
                continue
            if _key_extension(key) != "png":
                continue
            keys.add(key)
    return keys


def _ensure_r2_config(db) -> tuple[str, str, str, str, str, str]:
    values = dict(get_settings_map(db))
    env_overrides = {
        "cloudflare_account_id": os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip(),
        "cloudflare_r2_bucket": os.environ.get("CLOUDFLARE_R2_BUCKET", "").strip(),
        "cloudflare_r2_access_key_id": os.environ.get("CLOUDFLARE_R2_ACCESS_KEY_ID", "").strip(),
        "cloudflare_r2_secret_access_key": os.environ.get("CLOUDFLARE_R2_SECRET_ACCESS_KEY", "").strip(),
        "cloudflare_r2_public_base_url": os.environ.get("CLOUDFLARE_R2_PUBLIC_BASE_URL", "").strip(),
        "cloudflare_r2_prefix": os.environ.get("CLOUDFLARE_R2_PREFIX", "").strip(),
    }
    for key, env_value in env_overrides.items():
        if env_value and not str(values.get(key) or "").strip():
            values[key] = env_value
    account_id, bucket, access_key, secret_key, public_base_url, public_key = _resolve_cloudflare_r2_configuration(values)
    if not account_id or not bucket or not access_key or not secret_key:
        raise ValueError("Cloudflare R2 credentials are missing.")
    if not public_base_url:
        raise ValueError("Cloudflare R2 public base URL is missing.")
    return account_id, bucket, access_key, secret_key, public_base_url, public_key


def _webp_bytes_from_png(png_bytes: bytes, quality: int) -> bytes:
    with Image.open(io.BytesIO(png_bytes)) as image:
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        output = io.BytesIO()
        image.save(output, format="WEBP", quality=quality, optimize=True, method=6)
        return output.getvalue()


def _write_report(report_dir: Path, payload: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, str]:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = report_dir / f"cleanup-published-images-{stamp}.json"
    csv_path = report_dir / f"cleanup-published-images-{stamp}.csv"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "action",
                "source",
                "post_id",
                "key",
                "url",
                "status",
                "detail",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return {"json": str(json_path), "csv": str(csv_path)}

def main() -> int:
    args = parse_args()
    dry_run = not bool(args.apply)

    action_rows: list[dict[str, Any]] = []
    errors: list[str] = []
    summary: dict[str, Any] = {
        "generated_at": _utc_now_iso(),
        "dry_run": dry_run,
        "scope": args.scope,
        "quality": int(args.quality),
        "published_items": 0,
        "png_refs": 0,
        "webp_refs": 0,
        "png_convert_planned": 0,
        "png_delete_planned": 0,
        "webp_only_png_delete_planned": 0,
        "orphan_delete_planned": 0,
        "content_updates_planned": 0,
        "content_updates_applied": 0,
        "converted": 0,
        "content_updated": 0,
        "png_deleted": 0,
        "png_skipped_ref_exists": 0,
        "bytes_uploaded": 0,
        "bytes_deleted": 0,
        "net_bytes_delta": 0,
        "failures": 0,
    }

    with SessionLocal() as db:
        _, _, _, _, public_base_url, public_key = _ensure_r2_config(db)

        google_items: list[dict[str, Any]] = []
        cloudflare_items: list[dict[str, Any]] = []
        reference_google_items = _load_google_published_items(db, limit=0)
        reference_cloudflare_items = _load_cloudflare_items(db, limit=0)
        reference_items = reference_google_items + reference_cloudflare_items
        google_orphan_contents: list[str] = []
        cloudflare_orphan_contents: list[str] = []

        if args.scope in {"google", "all"}:
            google_items = _load_google_published_items(db, limit=int(args.limit))

        if args.scope in {"cloudflare", "all"}:
            cloudflare_items = _load_cloudflare_items(db, limit=int(args.limit))

        if args.delete_orphan:
            published_ids = {item["post_id"] for item in reference_google_items if _safe_str(item.get("post_id"))}
            google_orphan_contents = _load_google_orphan_contents(db, published_ids=published_ids)
            cloudflare_orphan_contents = _load_cloudflare_orphan_contents(db)

        items = google_items + cloudflare_items
        summary["published_items"] = len(items)

        refs, per_item_urls = _collect_references(items, public_base_url=public_base_url)
        all_public_refs, _ = _collect_references(reference_items, public_base_url=public_base_url)
        url_to_key = {ref["url"]: ref["key"] for ref in refs}
        public_png_keys = {ref["key"] for ref in refs if ref["ext"] == "png"}
        public_webp_keys = {ref["key"] for ref in refs if ref["ext"] == "webp"}
        all_public_keys = {ref["key"] for ref in all_public_refs}
        summary["png_refs"] = len(public_png_keys)
        summary["webp_refs"] = len(public_webp_keys)

        png_key_to_items: dict[str, set[int]] = {}
        for idx, urls in enumerate(per_item_urls):
            for url in urls:
                key = url_to_key.get(url)
                if not key or _key_extension(key) != "png":
                    continue
                png_key_to_items.setdefault(key, set()).add(idx)

        exists_cache: dict[str, bool] = {}
        size_cache: dict[str, int | None] = {}

        def _exists(key: str) -> bool:
            if key in exists_cache:
                return exists_cache[key]
            try:
                exists_cache[key] = cloudflare_r2_object_exists(db, public_key=public_key, key=key)
            except Exception as exc:
                exists_cache[key] = False
                errors.append(f"exists_failed:{key}:{exc}")
            return exists_cache[key]

        def _size(key: str) -> int | None:
            if key in size_cache:
                return size_cache[key]
            try:
                size_cache[key] = cloudflare_r2_object_size(db, public_key=public_key, key=key)
            except Exception as exc:
                size_cache[key] = None
                errors.append(f"size_failed:{key}:{exc}")
            return size_cache[key]

        png_plan: dict[str, dict[str, Any]] = {}
        png_size_cache: dict[str, int] = {}
        for png_key in sorted(public_png_keys):
            webp_key = png_key[:-4] + ".webp"
            png_exists = _exists(png_key)
            webp_exists = _exists(webp_key) if png_exists else _exists(webp_key)
            if not png_exists:
                action = "missing_png"
            elif webp_exists:
                action = "replace_after_update"
            else:
                action = "convert_to_webp"
                summary["png_convert_planned"] += 1
            png_plan[png_key] = {
                "png_key": png_key,
                "webp_key": webp_key,
                "png_exists": png_exists,
                "webp_exists": webp_exists,
                "action": action,
            }

        webp_only_png_deletes: list[str] = []
        if args.delete_png:
            for webp_key in sorted(public_webp_keys):
                png_key = webp_key[:-5] + ".png"
                if png_key in public_png_keys:
                    continue
                if _exists(png_key):
                    webp_only_png_deletes.append(png_key)
        summary["webp_only_png_delete_planned"] = len(webp_only_png_deletes)

        orphan_deletes: list[str] = []
        if args.delete_orphan:
            orphan_contents = google_orphan_contents + cloudflare_orphan_contents
            orphan_keys: set[str] = set()
            for content in orphan_contents:
                for url in _extract_urls(content):
                    if not _is_r2_url(url, public_base_url):
                        continue
                    key = normalize_r2_url_to_key(url)
                    if not key:
                        continue
                    if _key_extension(key) not in {"png", "webp"}:
                        continue
                    orphan_keys.add(key)
            orphan_deletes = sorted(key for key in orphan_keys if key not in all_public_keys)
        summary["orphan_delete_planned"] = len(orphan_deletes)

        webp_available: set[str] = set()

        for png_key, plan in png_plan.items():
            action = plan["action"]
            webp_key = plan["webp_key"]
            if action == "missing_png":
                if plan["webp_exists"]:
                    webp_available.add(webp_key)
                action_rows.append(
                    {
                        "action": "png_missing",
                        "source": "r2",
                        "post_id": "",
                        "key": png_key,
                        "url": "",
                        "status": "skipped",
                        "detail": "webp_exists" if plan["webp_exists"] else "webp_missing",
                    }
                )
                continue

            if plan["webp_exists"]:
                webp_available.add(webp_key)
                continue

            if dry_run:
                webp_available.add(webp_key)
                summary["converted"] += 1
                action_rows.append(
                    {
                        "action": "png_to_webp",
                        "source": "r2",
                        "post_id": "",
                        "key": png_key,
                        "url": "",
                        "status": "planned",
                        "detail": "convert",
                    }
                )
                continue

            try:
                png_bytes = cloudflare_r2_download_binary(db, public_key=public_key, key=png_key)
                png_size_cache[png_key] = len(png_bytes)
                webp_bytes = _webp_bytes_from_png(png_bytes, quality=int(args.quality))
                upload_binary_to_cloudflare_r2(
                    db,
                    object_key=webp_key,
                    filename=Path(webp_key).name,
                    content=webp_bytes,
                )
                webp_available.add(webp_key)
                summary["converted"] += 1
                summary["bytes_uploaded"] += len(webp_bytes)
                action_rows.append(
                    {
                        "action": "png_to_webp",
                        "source": "r2",
                        "post_id": "",
                        "key": png_key,
                        "url": "",
                        "status": "ok",
                        "detail": "converted",
                    }
                )
            except Exception as exc:
                summary["failures"] += 1
                errors.append(f"png_convert_failed:{png_key}:{exc}")
                action_rows.append(
                    {
                        "action": "png_to_webp",
                        "source": "r2",
                        "post_id": "",
                        "key": png_key,
                        "url": "",
                        "status": "failed",
                        "detail": str(exc),
                    }
                )
                continue

        replacements: dict[str, str] = {}
        for url, key in url_to_key.items():
            if _key_extension(key) != "png":
                continue
            webp_key = key[:-4] + ".webp"
            if webp_key not in webp_available:
                continue
            replacements[url] = _swap_png_to_webp(url)

        updated_items: list[dict[str, Any]] = []
        for index, item in enumerate(items):
            urls = per_item_urls[index] if index < len(per_item_urls) else set()
            if not urls:
                continue
            applicable = {url: replacements[url] for url in urls if url in replacements}
            if not applicable:
                continue
            updated_content = _apply_replacements(item["content"], applicable)
            if updated_content == item["content"]:
                continue
            item["updated_content"] = updated_content
            item["_index"] = index
            updated_items.append(item)

        summary["content_updates_planned"] = len(updated_items)

        item_update_ok: dict[int, bool] = {}

        for batch in _chunked(updated_items, int(args.batch_size)):
            for item in batch:
                source = item["source"]
                post_id = _safe_str(item.get("post_id"))
                item_index = int(item.get("_index", -1))
                if dry_run:
                    if source == "google":
                        blog = item.get("blog")
                        if not blog:
                            item_update_ok[item_index] = False
                            action_rows.append(
                                {
                                    "action": "content_update",
                                    "source": source,
                                    "post_id": post_id,
                                    "key": "",
                                    "url": "",
                                    "status": "skipped",
                                    "detail": "missing_blog",
                                }
                            )
                            continue
                        try:
                            provider = get_blogger_provider(db, blog)
                            if type(provider).__name__.startswith("Mock") or not hasattr(provider, "update_post"):
                                item_update_ok[item_index] = False
                                action_rows.append(
                                    {
                                        "action": "content_update",
                                        "source": source,
                                        "post_id": post_id,
                                        "key": "",
                                        "url": "",
                                        "status": "skipped",
                                        "detail": "mock_provider",
                                    }
                                )
                                continue
                        except Exception as exc:
                            item_update_ok[item_index] = False
                            action_rows.append(
                                {
                                    "action": "content_update",
                                    "source": source,
                                    "post_id": post_id,
                                    "key": "",
                                    "url": "",
                                    "status": "skipped",
                                    "detail": f"provider_error:{exc}",
                                }
                            )
                            continue
                        item_update_ok[item_index] = True
                        summary["content_updated"] += 1
                        action_rows.append(
                            {
                                "action": "content_update",
                                "source": source,
                                "post_id": post_id,
                                "key": "",
                                "url": "",
                                "status": "planned",
                                "detail": "",
                            }
                        )
                        continue

                    if source == "cloudflare":
                        if not post_id:
                            item_update_ok[item_index] = False
                            action_rows.append(
                                {
                                    "action": "content_update",
                                    "source": source,
                                    "post_id": "",
                                    "key": "",
                                    "url": "",
                                    "status": "skipped",
                                    "detail": "missing_post_id",
                                }
                            )
                            continue
                        item_update_ok[item_index] = True
                        summary["content_updated"] += 1
                        action_rows.append(
                            {
                                "action": "content_update",
                                "source": source,
                                "post_id": post_id,
                                "key": "",
                                "url": "",
                                "status": "planned",
                                "detail": "",
                            }
                        )
                        continue
                    continue

                if source == "google":
                    blog = item.get("blog")
                    if not blog:
                        summary["failures"] += 1
                        item_update_ok[item_index] = False
                        action_rows.append(
                            {
                                "action": "content_update",
                                "source": source,
                                "post_id": post_id,
                                "key": "",
                                "url": "",
                                "status": "failed",
                                "detail": "missing_blog",
                            }
                        )
                        continue

                    provider = get_blogger_provider(db, blog)
                    if type(provider).__name__.startswith("Mock") or not hasattr(provider, "update_post"):
                        item_update_ok[item_index] = False
                        action_rows.append(
                            {
                                "action": "content_update",
                                "source": source,
                                "post_id": post_id,
                                "key": "",
                                "url": "",
                                "status": "skipped",
                                "detail": "mock_provider",
                            }
                        )
                        continue

                    try:
                        summary_payload, _raw_payload = provider.update_post(
                            post_id=post_id,
                            title=_safe_str(item.get("title")),
                            content=item["updated_content"],
                            labels=list(item.get("labels") or []),
                            meta_description=_safe_str(item.get("meta_description")),
                        )
                        if item.get("synced_post"):
                            item["synced_post"].content_html = item["updated_content"]
                            db.add(item["synced_post"])
                        article = item.get("article")
                        if article:
                            updated_article_html = _apply_replacements(
                                _safe_str(article.html_article), replacements
                            )
                            updated_assembled_html = _apply_replacements(
                                _safe_str(article.assembled_html), replacements
                            )
                            if updated_article_html:
                                article.html_article = updated_article_html
                            if updated_assembled_html:
                                article.assembled_html = updated_assembled_html
                            db.add(article)
                        db.commit()
                        db.flush()
                        summary["content_updates_applied"] += 1
                        item_update_ok[item_index] = True
                        summary["content_updated"] += 1
                        action_rows.append(
                            {
                                "action": "content_update",
                                "source": source,
                                "post_id": post_id,
                                "key": "",
                                "url": "",
                                "status": "ok",
                                "detail": _safe_str(summary_payload.get("postStatus") if isinstance(summary_payload, dict) else ""),
                            }
                        )
                    except Exception as exc:
                        db.rollback()
                        summary["failures"] += 1
                        item_update_ok[item_index] = False
                        errors.append(f"google_update_failed:{post_id}:{exc}")
                        action_rows.append(
                            {
                                "action": "content_update",
                                "source": source,
                                "post_id": post_id,
                                "key": "",
                                "url": "",
                                "status": "failed",
                                "detail": str(exc),
                            }
                        )
                    continue

                if source == "cloudflare":
                    if not post_id:
                        summary["failures"] += 1
                        item_update_ok[item_index] = False
                        action_rows.append(
                            {
                                "action": "content_update",
                                "source": source,
                                "post_id": "",
                                "key": "",
                                "url": "",
                                "status": "failed",
                                "detail": "missing_post_id",
                            }
                        )
                        continue
                    try:
                        response = _integration_request(
                            db,
                            method="PUT",
                            path=f"/api/integrations/posts/{post_id}",
                            json_payload={"content": item["updated_content"]},
                            timeout=120.0,
                        )
                        _integration_data_or_raise(response)
                        summary["content_updates_applied"] += 1
                        item_update_ok[item_index] = True
                        summary["content_updated"] += 1
                        action_rows.append(
                            {
                                "action": "content_update",
                                "source": source,
                                "post_id": post_id,
                                "key": "",
                                "url": "",
                                "status": "ok",
                                "detail": "",
                            }
                        )
                    except Exception as exc:
                        summary["failures"] += 1
                        item_update_ok[item_index] = False
                        errors.append(f"cloudflare_update_failed:{post_id}:{exc}")
                        action_rows.append(
                            {
                                "action": "content_update",
                                "source": source,
                                "post_id": post_id,
                                "key": "",
                                "url": "",
                                "status": "failed",
                                "detail": str(exc),
                            }
                        )
                    continue

        applied_content_overrides: dict[tuple[str, str, str], str] = {}
        for item in updated_items:
            item_index = int(item.get("_index", -1))
            if not item_update_ok.get(item_index, False):
                continue
            applied_content_overrides[_item_identity(item)] = _safe_str(item.get("updated_content"))

        remaining_png_keys = _collect_png_keys_from_items(
            reference_items,
            public_base_url=public_base_url,
            content_overrides=applied_content_overrides,
        )

        deletable_png_candidates: dict[str, str] = {}
        if args.delete_png:
            for png_key, plan in png_plan.items():
                if not plan["png_exists"]:
                    continue
                webp_key = plan["webp_key"]
                if webp_key not in webp_available:
                    continue
                item_indices = png_key_to_items.get(png_key, set())
                if item_indices and not all(item_update_ok.get(idx, False) for idx in item_indices):
                    continue
                deletable_png_candidates[png_key] = "after_update"
            for png_key in webp_only_png_deletes:
                deletable_png_candidates.setdefault(png_key, "webp_only")

        skipped_ref_png_keys = sorted(key for key in deletable_png_candidates if key in remaining_png_keys)
        summary["png_skipped_ref_exists"] = len(skipped_ref_png_keys)
        for png_key in skipped_ref_png_keys:
            action_rows.append(
                {
                    "action": "png_delete",
                    "source": "r2",
                    "post_id": "",
                    "key": png_key,
                    "url": "",
                    "status": "skipped",
                    "detail": f"ref_exists:{deletable_png_candidates.get(png_key, '')}",
                }
            )

        deletable_png_keys = sorted(key for key in deletable_png_candidates if key not in remaining_png_keys)
        summary["png_delete_planned"] = len(deletable_png_keys)

        for png_key in deletable_png_keys:
            reason = deletable_png_candidates.get(png_key, "after_update")
            if dry_run:
                summary["png_deleted"] += 1
                action_rows.append(
                    {
                        "action": "png_delete",
                        "source": "r2",
                        "post_id": "",
                        "key": png_key,
                        "url": "",
                        "status": "planned",
                        "detail": reason,
                    }
                )
                continue
            try:
                size_value = png_size_cache.get(png_key)
                if size_value is None:
                    size_value = _size(png_key)
                delete_cloudflare_r2_asset(db, object_key=png_key)
                if size_value:
                    summary["bytes_deleted"] += int(size_value)
                summary["png_deleted"] += 1
                action_rows.append(
                    {
                        "action": "png_delete",
                        "source": "r2",
                        "post_id": "",
                        "key": png_key,
                        "url": "",
                        "status": "ok",
                        "detail": reason,
                    }
                )
            except Exception as exc:
                summary["failures"] += 1
                errors.append(f"png_delete_failed:{png_key}:{exc}")
                action_rows.append(
                    {
                        "action": "png_delete",
                        "source": "r2",
                        "post_id": "",
                        "key": png_key,
                        "url": "",
                        "status": "failed",
                        "detail": str(exc),
                    }
                )

        for key in orphan_deletes:
            if not _exists(key):
                action_rows.append(
                    {
                        "action": "orphan_delete",
                        "source": "r2",
                        "post_id": "",
                        "key": key,
                        "url": "",
                        "status": "skipped",
                        "detail": "missing",
                    }
                )
                continue
            if dry_run:
                action_rows.append(
                    {
                        "action": "orphan_delete",
                        "source": "r2",
                        "post_id": "",
                        "key": key,
                        "url": "",
                        "status": "planned",
                        "detail": "",
                    }
                )
            else:
                try:
                    size_value = _size(key)
                    delete_cloudflare_r2_asset(db, object_key=key)
                    if size_value:
                        summary["bytes_deleted"] += int(size_value)
                    action_rows.append(
                        {
                            "action": "orphan_delete",
                            "source": "r2",
                            "post_id": "",
                            "key": key,
                            "url": "",
                            "status": "ok",
                            "detail": "",
                        }
                    )
                except Exception as exc:
                    summary["failures"] += 1
                    errors.append(f"orphan_delete_failed:{key}:{exc}")
                    action_rows.append(
                        {
                            "action": "orphan_delete",
                            "source": "r2",
                            "post_id": "",
                            "key": key,
                            "url": "",
                            "status": "failed",
                            "detail": str(exc),
                        }
                    )

        summary["net_bytes_delta"] = summary["bytes_deleted"] - summary["bytes_uploaded"]

        report_payload = {
            "generated_at": summary["generated_at"],
            "args": vars(args),
            "summary": summary,
            "errors": errors,
            "actions": action_rows,
        }
        report_paths = _write_report(Path(args.report_dir), report_payload, action_rows)
        output = {
            "status": "ok" if summary["failures"] == 0 else "partial",
            "summary": summary,
            "report_paths": report_paths,
        }
        print(json.dumps(output, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
