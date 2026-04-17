from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload
from slugify import slugify

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@postgres:5432/bloggent"
DEFAULT_BLOG_IDS = [34, 35, 36, 37]
LIVE_STATUSES = {"live", "published", "LIVE", "PUBLISHED"}
LEGACY_TOKEN = "/assets/media/posts/2026/"
LEGACY_SCAN_TOKEN = "media/posts/2026/"
LEGACY_URL_TOKENS = (
    "/assets/media/posts/2026/",
    "/assets/assets/media/posts/2026/",
    "/assets/assets/images/media/posts/2026/",
)
ALLOWED_GOOGLE_BLOGGER_PATH_TOKEN = "/assets/media/google-blogger/"
URL_RE = re.compile(r"https?://[^\s'\"<>)\]]+", re.IGNORECASE)

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get("BLOGGENT_DATABASE_URL", DEFAULT_DATABASE_URL)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Article, Blog, BloggerPost, R2AssetRelayoutMapping, SyncedBloggerPost  # noqa: E402
from app.services.integrations.storage_service import (  # noqa: E402
    cloudflare_r2_download_binary,
    normalize_r2_url_to_key,
    upload_binary_to_cloudflare_r2,
)
from app.services.providers.factory import get_blogger_provider  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replace legacy media/posts/2026 URLs in live Blogger content and article fields.",
    )
    parser.add_argument("--mode", choices=("dry-run", "apply"), default="dry-run")
    parser.add_argument("--blog-id", action="append", type=int, default=[], help="Target blog id. Repeat for multiple.")
    parser.add_argument("--report-path", default="", help="Optional JSON report path.")
    return parser.parse_args()


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _normalize_legacy_key(raw_key: str) -> str:
    key = _safe_str(raw_key).lstrip("/")
    while key.startswith("assets/assets/"):
        key = key[len("assets/") :]
    return key


def _extract_urls(content: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for match in URL_RE.finditer(content or ""):
        value = _safe_str(match.group(0))
        if value and value not in seen:
            seen.add(value)
            urls.append(value)
    return urls


def _is_legacy_url(url: str) -> bool:
    raw = _safe_str(url)
    if not raw:
        return False
    lowered = raw.lower()
    if any(token in lowered for token in LEGACY_URL_TOKENS):
        return True
    normalized_key = _normalize_legacy_key(_safe_str(normalize_r2_url_to_key(raw))).lower()
    return normalized_key.startswith("assets/media/posts/2026/")


def _ensure_google_blogger_single_assets_url(*, db, url: str) -> str:
    normalized = _safe_str(url)
    if not normalized:
        return ""
    if "/assets/media/google-blogger/" in normalized and "/assets/assets/media/google-blogger/" not in normalized:
        return normalized
    if "/assets/assets/media/google-blogger/" not in normalized:
        return normalized

    source_key = _safe_str(normalize_r2_url_to_key(normalized)).lstrip("/")
    if not source_key:
        return normalized
    if not source_key.startswith("assets/media/google-blogger/"):
        return normalized

    target_key = source_key[len("assets/") :]
    try:
        binary = cloudflare_r2_download_binary(db, public_key="", key=source_key)
        public_url, _upload_payload, _delivery_meta = upload_binary_to_cloudflare_r2(
            db,
            object_key=target_key,
            filename=Path(target_key).name,
            content=binary,
        )
        final_url = _safe_str(public_url)
        if final_url and ALLOWED_GOOGLE_BLOGGER_PATH_TOKEN in final_url:
            return final_url
    except Exception:
        return normalized
    return normalized


def _build_legacy_url_map(db) -> dict[str, str]:
    rows = (
        db.execute(
            select(R2AssetRelayoutMapping)
            .where(
                R2AssetRelayoutMapping.legacy_key.is_not(None),
                R2AssetRelayoutMapping.migrated_url.is_not(None),
                R2AssetRelayoutMapping.status == "mapped",
                R2AssetRelayoutMapping.legacy_key.like("assets/media/posts/2026/%"),
            )
            .order_by(R2AssetRelayoutMapping.created_at.desc(), R2AssetRelayoutMapping.id.desc())
        )
        .scalars()
        .all()
    )
    out: dict[str, str] = {}
    for row in rows:
        legacy_key = _normalize_legacy_key(_safe_str(row.legacy_key))
        migrated_url = _safe_str(row.migrated_url)
        if not legacy_key or not migrated_url:
            continue
        if legacy_key not in out:
            out[legacy_key] = migrated_url
    return out


def _resolve_migrated_url(*, legacy_key: str, legacy_map: dict[str, str]) -> str:
    def _is_legacy_target(url: str) -> bool:
        normalized = _safe_str(url)
        if not normalized:
            return True
        if LEGACY_TOKEN in normalized:
            return True
        normalized_key = _normalize_legacy_key(_safe_str(normalize_r2_url_to_key(normalized)))
        return normalized_key.startswith("assets/media/posts/2026/")

    normalized = _normalize_legacy_key(legacy_key)
    direct = _safe_str(legacy_map.get(normalized))
    if direct and not _is_legacy_target(direct):
        return direct

    lower = normalized.lower()
    for ext in (".png", ".jpg", ".jpeg", ".gif"):
        if lower.endswith(ext):
            webp_key = normalized[: -len(ext)] + ".webp"
            candidate = _safe_str(legacy_map.get(webp_key))
            if candidate and not _is_legacy_target(candidate):
                return candidate
    return ""


def _replace_legacy_urls(
    content: str,
    *,
    db,
    legacy_map: dict[str, str],
) -> tuple[str, list[dict[str, str]], list[dict[str, str]]]:
    updated = content or ""
    replacements: list[dict[str, str]] = []
    unresolved: list[dict[str, str]] = []
    for url in _extract_urls(updated):
        if not _is_legacy_url(url):
            continue
        legacy_key = _normalize_legacy_key(_safe_str(normalize_r2_url_to_key(url)))
        target_url = _resolve_migrated_url(legacy_key=legacy_key, legacy_map=legacy_map)
        if not target_url:
            unresolved.append({"url": url, "legacy_key": legacy_key})
            continue
        target_url = _ensure_google_blogger_single_assets_url(db=db, url=target_url)
        if target_url == url:
            continue
        updated = updated.replace(url, target_url)
        replacements.append({"from": url, "to": target_url, "legacy_key": legacy_key})
    return updated, replacements, unresolved


def _remove_unresolved_img_tags(content: str, unresolved_urls: list[str]) -> tuple[str, int]:
    updated = content or ""
    removed_total = 0
    for url in [_safe_str(value) for value in unresolved_urls if _safe_str(value)]:
        pattern = re.compile(rf"<img\b[^>]*\bsrc=(['\"]){re.escape(url)}\1[^>]*>\s*", re.IGNORECASE)
        updated, removed_count = pattern.subn("", updated)
        removed_total += int(removed_count or 0)
    return updated, removed_total


def _build_fallback_object_key(*, blog_slug: str, legacy_key: str) -> str:
    normalized_key = _normalize_legacy_key(legacy_key)
    parts = normalized_key.split("/")
    if len(parts) >= 7 and parts[0] == "assets" and parts[1] == "media" and parts[2] == "posts":
        yyyy = parts[3]
        mm = parts[4]
        folder = slugify(parts[5], separator="-") or "legacy-post"
        filename = parts[-1]
    else:
        yyyy = "2026"
        mm = "04"
        folder = slugify(Path(normalized_key).stem, separator="-") or "legacy-post"
        filename = Path(normalized_key).name or "asset.webp"

    stem = Path(filename).stem
    hash_token = slugify(stem.split(".")[-1], separator="-") or hashlib.sha1(normalized_key.encode("utf-8")).hexdigest()[:12]
    role = "inline-legacy" if "inline" in stem.lower() else "cover-legacy"
    safe_blog_slug = slugify(blog_slug, separator="-") or "unknown-blog"
    return f"assets/media/google-blogger/{safe_blog_slug}/legacy/{yyyy}/{mm}/{folder}/{role}-{hash_token}.webp"


def _migrate_unresolved_url(*, db, blog_slug: str, legacy_key: str) -> str:
    object_key = _build_fallback_object_key(blog_slug=blog_slug, legacy_key=legacy_key)
    normalized_legacy_key = _normalize_legacy_key(legacy_key)
    candidate_keys = [normalized_legacy_key]
    if normalized_legacy_key.startswith("assets/"):
        candidate_keys.append(normalized_legacy_key[len("assets/") :])
    binary: bytes | None = None
    last_error: Exception | None = None
    for candidate in candidate_keys:
        try:
            binary = cloudflare_r2_download_binary(db, public_key="", key=candidate)
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue
    if binary is None:
        raise RuntimeError(f"legacy_download_failed:{normalized_legacy_key}") from last_error
    public_url, _upload_payload, _delivery_meta = upload_binary_to_cloudflare_r2(
        db,
        object_key=object_key,
        filename=Path(object_key).name,
        content=binary,
    )
    return _ensure_google_blogger_single_assets_url(db=db, url=_safe_str(public_url))


def _resolve_unresolved_items(
    *,
    db,
    blog_slug: str,
    updated_content: str,
    unresolved: list[dict[str, str]],
    replacements: list[dict[str, str]],
    legacy_map: dict[str, str],
) -> tuple[str, list[dict[str, str]], list[dict[str, str]]]:
    remaining: list[dict[str, str]] = []
    for unresolved_item in unresolved:
        source_url = _safe_str(unresolved_item.get("url"))
        legacy_key = _safe_str(unresolved_item.get("legacy_key"))
        if not source_url or not legacy_key:
            remaining.append(unresolved_item)
            continue
        try:
            migrated_url = _migrate_unresolved_url(
                db=db,
                blog_slug=blog_slug,
                legacy_key=legacy_key,
            )
        except Exception:  # noqa: BLE001
            remaining.append(unresolved_item)
            continue
        if not migrated_url:
            remaining.append(unresolved_item)
            continue
        legacy_map[legacy_key] = migrated_url
        updated_content = updated_content.replace(source_url, migrated_url)
        replacements.append({"from": source_url, "to": migrated_url, "legacy_key": legacy_key})
    return updated_content, replacements, remaining


def run(*, mode: str, blog_ids: list[int] | None = None) -> dict[str, Any]:
    target_blog_ids = sorted({int(value) for value in (blog_ids or []) if int(value) > 0}) or DEFAULT_BLOG_IDS.copy()
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "blog_ids": target_blog_ids,
        "summary": {
            "posts_scanned": 0,
            "target_posts": 0,
            "updated_posts": 0,
            "failed_posts": 0,
            "replaced_url_total": 0,
            "unresolved_url_total": 0,
            "articles_scanned": 0,
            "target_articles": 0,
            "updated_articles": 0,
            "failed_articles": 0,
            "article_replaced_url_total": 0,
            "article_unresolved_url_total": 0,
            "html_article_scanned": 0,
            "html_article_targets": 0,
            "html_article_updated": 0,
            "html_article_unresolved_removed": 0,
        },
        "items": [],
        "article_items": [],
    }

    with SessionLocal() as db:
        legacy_map = _build_legacy_url_map(db)
        posts = (
            db.execute(
                select(SyncedBloggerPost)
                .where(
                    SyncedBloggerPost.blog_id.in_(target_blog_ids),
                    SyncedBloggerPost.status.in_(sorted(LIVE_STATUSES)),
                    SyncedBloggerPost.url.is_not(None),
                    SyncedBloggerPost.content_html.ilike(f"%{LEGACY_SCAN_TOKEN}%"),
                )
                .options(selectinload(SyncedBloggerPost.blog))
                .order_by(SyncedBloggerPost.blog_id.asc(), SyncedBloggerPost.id.desc())
            )
            .scalars()
            .all()
        )
        report["summary"]["posts_scanned"] = len(posts)

        remote_ids = sorted({_safe_str(post.remote_post_id) for post in posts if _safe_str(post.remote_post_id)})
        blogger_posts = (
            db.execute(
                select(BloggerPost)
                .where(
                    BloggerPost.blog_id.in_(target_blog_ids),
                    BloggerPost.blogger_post_id.in_(remote_ids) if remote_ids else False,
                )
                .options(selectinload(BloggerPost.article))
            )
            .scalars()
            .all()
            if remote_ids
            else []
        )
        blogger_post_map = {
            (row.blog_id, _safe_str(row.blogger_post_id)): row
            for row in blogger_posts
        }

        for post in posts:
            updated_content, replacements, unresolved = _replace_legacy_urls(
                post.content_html,
                db=db,
                legacy_map=legacy_map,
            )
            blog_for_fallback = post.blog if post.blog is not None else db.get(Blog, post.blog_id)
            if mode == "apply" and unresolved and blog_for_fallback is not None:
                updated_content, replacements, unresolved = _resolve_unresolved_items(
                    db=db,
                    blog_slug=_safe_str(blog_for_fallback.slug),
                    updated_content=updated_content,
                    unresolved=unresolved,
                    replacements=replacements,
                    legacy_map=legacy_map,
                )
            if not replacements and not unresolved:
                continue

            report["summary"]["target_posts"] += 1
            report["summary"]["replaced_url_total"] += len(replacements)
            report["summary"]["unresolved_url_total"] += len(unresolved)
            item = {
                "blog_id": post.blog_id,
                "remote_post_id": _safe_str(post.remote_post_id),
                "url": _safe_str(post.url),
                "title": _safe_str(post.title),
                "replacements": replacements,
                "unresolved_urls": [_safe_str(value.get("url")) for value in unresolved],
                "status": "planned" if mode == "dry-run" else "pending",
            }
            if mode == "dry-run":
                report["items"].append(item)
                continue

            blog = blog_for_fallback
            if blog is None:
                item["status"] = "failed"
                item["reason"] = "blog_missing"
                report["summary"]["failed_posts"] += 1
                report["items"].append(item)
                continue

            provider = get_blogger_provider(db, blog)
            if not hasattr(provider, "update_post"):
                item["status"] = "failed"
                item["reason"] = "provider_update_post_unavailable"
                report["summary"]["failed_posts"] += 1
                report["items"].append(item)
                continue

            blogger_post = blogger_post_map.get((post.blog_id, _safe_str(post.remote_post_id)))
            article = blogger_post.article if blogger_post is not None else None
            if article is not None and _safe_str(article.assembled_html):
                article_updated, _article_replacements, _article_unresolved = _replace_legacy_urls(
                    article.assembled_html,
                    db=db,
                    legacy_map=legacy_map,
                )
                if article_updated != article.assembled_html:
                    article.assembled_html = article_updated
                    db.add(article)

            try:
                provider.update_post(
                    post_id=_safe_str(post.remote_post_id),
                    title=_safe_str(post.title) or (_safe_str(article.title) if article is not None else "Untitled"),
                    content=updated_content,
                    labels=list(post.labels or []),
                    meta_description=_safe_str(post.excerpt_text)[:300],
                )
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                item["status"] = "failed"
                item["reason"] = f"provider_update_failed:{exc}"
                report["summary"]["failed_posts"] += 1
                report["items"].append(item)
                continue

            post.content_html = updated_content
            post.synced_at = datetime.now(timezone.utc)
            db.add(post)
            db.commit()
            item["status"] = "updated"
            report["summary"]["updated_posts"] += 1
            report["items"].append(item)

        article_rows = (
            db.execute(
                select(
                    Article.id,
                    BloggerPost.blog_id,
                    Article.assembled_html.ilike(f"%{LEGACY_TOKEN}%").label("has_assembled"),
                    Article.html_article.ilike(f"%{LEGACY_TOKEN}%").label("has_html"),
                )
                .join(BloggerPost, BloggerPost.article_id == Article.id)
                .where(
                    BloggerPost.blog_id.in_(target_blog_ids),
                    or_(
                        Article.assembled_html.ilike(f"%{LEGACY_SCAN_TOKEN}%"),
                        Article.html_article.ilike(f"%{LEGACY_SCAN_TOKEN}%"),
                    ),
                )
                .order_by(Article.id.asc(), BloggerPost.blog_id.asc())
            )
            .all()
        )
        article_blog_id_map: dict[int, int] = {}
        article_has_assembled_map: dict[int, bool] = {}
        article_has_html_map: dict[int, bool] = {}
        for article_id, blog_id, has_assembled, has_html in article_rows:
            normalized_article_id = int(article_id)
            article_blog_id_map.setdefault(normalized_article_id, int(blog_id))
            article_has_assembled_map[normalized_article_id] = bool(article_has_assembled_map.get(normalized_article_id) or has_assembled)
            article_has_html_map[normalized_article_id] = bool(article_has_html_map.get(normalized_article_id) or has_html)

        article_ids = sorted(article_blog_id_map.keys())
        articles = (
            db.execute(select(Article).where(Article.id.in_(article_ids)))
            .scalars()
            .all()
            if article_ids
            else []
        )
        article_map = {int(article.id): article for article in articles}

        report["summary"]["articles_scanned"] = len(article_ids)
        report["summary"]["html_article_scanned"] = sum(1 for article_id in article_ids if article_has_html_map.get(article_id))
        for article_id in article_ids:
            article = article_map.get(article_id)
            if article is None:
                continue

            blog_id = int(article_blog_id_map.get(article_id, 0) or 0)
            blog_row = db.get(Blog, blog_id) if blog_id > 0 else None
            assembled_updated = _safe_str(article.assembled_html)
            html_article_updated = _safe_str(article.html_article)

            assembled_replacements: list[dict[str, str]] = []
            assembled_unresolved: list[dict[str, str]] = []
            if article_has_assembled_map.get(article_id):
                assembled_updated, assembled_replacements, assembled_unresolved = _replace_legacy_urls(
                    assembled_updated,
                    db=db,
                    legacy_map=legacy_map,
                )
                if mode == "apply" and assembled_unresolved and blog_row is not None:
                    assembled_updated, assembled_replacements, assembled_unresolved = _resolve_unresolved_items(
                        db=db,
                        blog_slug=_safe_str(blog_row.slug),
                        updated_content=assembled_updated,
                        unresolved=assembled_unresolved,
                        replacements=assembled_replacements,
                        legacy_map=legacy_map,
                    )

            html_replacements: list[dict[str, str]] = []
            html_unresolved: list[dict[str, str]] = []
            unresolved_removed = 0
            if article_has_html_map.get(article_id):
                html_article_updated, html_replacements, html_unresolved = _replace_legacy_urls(
                    html_article_updated,
                    db=db,
                    legacy_map=legacy_map,
                )
                if mode == "apply" and html_unresolved and blog_row is not None:
                    html_article_updated, html_replacements, html_unresolved = _resolve_unresolved_items(
                        db=db,
                        blog_slug=_safe_str(blog_row.slug),
                        updated_content=html_article_updated,
                        unresolved=html_unresolved,
                        replacements=html_replacements,
                        legacy_map=legacy_map,
                    )
                if mode == "apply" and html_unresolved:
                    unresolved_urls = [_safe_str(value.get("url")) for value in html_unresolved]
                    html_article_updated, unresolved_removed = _remove_unresolved_img_tags(html_article_updated, unresolved_urls)
                    if unresolved_removed:
                        _tmp_html, _tmp_replacements, html_unresolved = _replace_legacy_urls(
                            html_article_updated,
                            db=db,
                            legacy_map=legacy_map,
                        )

            has_article_target = bool(
                assembled_replacements
                or assembled_unresolved
                or html_replacements
                or html_unresolved
                or unresolved_removed
            )
            if not has_article_target:
                continue

            report["summary"]["target_articles"] += 1
            report["summary"]["article_replaced_url_total"] += len(assembled_replacements) + len(html_replacements)
            report["summary"]["article_unresolved_url_total"] += len(assembled_unresolved) + len(html_unresolved)
            if article_has_html_map.get(article_id):
                report["summary"]["html_article_targets"] += 1
                report["summary"]["html_article_unresolved_removed"] += int(unresolved_removed or 0)

            article_item = {
                "article_id": article_id,
                "blog_id": blog_id,
                "assembled_replacements": assembled_replacements,
                "assembled_unresolved_urls": [_safe_str(value.get("url")) for value in assembled_unresolved],
                "html_article_replacements": html_replacements,
                "html_article_unresolved_urls": [_safe_str(value.get("url")) for value in html_unresolved],
                "html_article_unresolved_removed": int(unresolved_removed or 0),
                "status": "planned" if mode == "dry-run" else "pending",
            }
            if mode == "dry-run":
                report["article_items"].append(article_item)
                continue

            if assembled_unresolved or html_unresolved:
                article_item["status"] = "failed"
                article_item["reason"] = "unresolved_urls_remain"
                report["summary"]["failed_articles"] += 1
                report["article_items"].append(article_item)
                continue

            changed = False
            if assembled_updated != _safe_str(article.assembled_html):
                article.assembled_html = assembled_updated
                changed = True
            if html_article_updated != _safe_str(article.html_article):
                article.html_article = html_article_updated
                changed = True

            try:
                if changed:
                    db.add(article)
                    db.commit()
                else:
                    db.rollback()
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                article_item["status"] = "failed"
                article_item["reason"] = f"article_update_failed:{exc}"
                report["summary"]["failed_articles"] += 1
                report["article_items"].append(article_item)
                continue

            article_item["status"] = "updated"
            report["summary"]["updated_articles"] += 1
            if article_has_html_map.get(article_id) and html_article_updated != _safe_str(article.html_article):
                report["summary"]["html_article_updated"] += 1
            elif article_has_html_map.get(article_id) and (html_replacements or unresolved_removed):
                report["summary"]["html_article_updated"] += 1
            report["article_items"].append(article_item)

    return report


def main() -> int:
    args = parse_args()
    report = run(mode=args.mode, blog_ids=list(args.blog_id or []))
    report_path = (
        Path(args.report_path)
        if _safe_str(args.report_path)
        else REPO_ROOT / "storage" / "reports" / f"repair-blogger-media-posts-2026-legacy-{_timestamp()}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(report_path))
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
