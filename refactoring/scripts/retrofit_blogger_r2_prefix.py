from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse


def _repo_root() -> Path:
    configured = os.environ.get("BLOGGENT_REPO_ROOT", "").strip()
    if configured:
        return Path(configured).resolve()
    cursor = Path(__file__).resolve().parent
    for candidate in [cursor, *cursor.parents]:
        if (candidate / "apps" / "api").exists():
            return candidate
    return Path(__file__).resolve().parents[2]


REPO_ROOT = _repo_root()
API_ROOT = REPO_ROOT / "apps" / "api"
LOCAL_STORAGE_ROOT = REPO_ROOT / "storage"
REPORT_DIR = REPO_ROOT / "refactoring" / "reports"

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get(
        "BLOGGENT_DATABASE_URL",
        "postgresql://bloggent:bloggent@localhost:15432/bloggent",
    )
if "STORAGE_ROOT" not in os.environ:
    os.environ["STORAGE_ROOT"] = str(LOCAL_STORAGE_ROOT)

sys.path.insert(0, str(API_ROOT))
sys.path.insert(0, str(REPO_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session, selectinload  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Article, Blog, BloggerPost, PostStatus  # noqa: E402
from app.services.blogger.blogger_sync_service import sync_blogger_posts_for_blog  # noqa: E402
from app.services.integrations.storage_service import (  # noqa: E402
    cloudflare_r2_download_binary,
    cloudflare_r2_object_exists,
    normalize_r2_url_to_key,
    upload_binary_to_cloudflare_r2,
)
from app.services.platform.publishing_service import upsert_article_blogger_post  # noqa: E402
from app.services.providers.factory import get_blogger_provider  # noqa: E402


LEGACY_URL_RE = re.compile(r"/assets(?:/assets){0,2}/media/blogger/", re.IGNORECASE)
LEGACY_KEY_RE = re.compile(r"^(?:assets/)+(media/blogger/.+)$", re.IGNORECASE)


@dataclass(slots=True)
class UrlPatch:
    old_url: str
    new_url: str
    legacy_key_candidates: list[str]
    canonical_key: str


def _replace_ext(value: str, *, to_ext: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return raw
    return re.sub(r"\.(?:png|jpg|jpeg)$", f".{to_ext}", raw, flags=re.IGNORECASE)


def _is_non_webp_image_url(url: str) -> bool:
    return bool(re.search(r"\.(?:png|jpg|jpeg)$", str(url or ""), flags=re.IGNORECASE))


def _webp_fallback_patch(patch: UrlPatch) -> UrlPatch:
    webp_new = _replace_ext(patch.new_url, to_ext="webp")
    webp_key = _replace_ext(patch.canonical_key, to_ext="webp")
    webp_legacy = [_replace_ext(key, to_ext="webp") for key in patch.legacy_key_candidates]
    return UrlPatch(
        old_url=patch.old_url,
        new_url=webp_new,
        canonical_key=webp_key,
        legacy_key_candidates=webp_legacy,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Retrofit Blogger R2 prefix from blogger/ to google-blogger/.")
    parser.add_argument("--scope", default="all-blogger", choices=("all-blogger",), help="Execution scope.")
    parser.add_argument("--execute", action="store_true", help="Apply DB patch + republish. Default dry-run.")
    parser.add_argument("--sync-blogger", action="store_true", help="Call provider.update_post for changed articles.")
    parser.add_argument(
        "--include-status",
        action="append",
        choices=("published", "scheduled", "draft"),
        help="Post statuses to include. Default: published,scheduled.",
    )
    parser.add_argument("--report-prefix", default="retrofit-blogger-r2-prefix", help="Report file name prefix.")
    return parser.parse_args()


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return json.dumps(str(value), ensure_ascii=False)


def _normalize_host(netloc: str) -> str:
    host = (netloc or "").strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def normalize_legacy_url_to_canonical(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    path = parsed.path or ""
    lower_path = path.lower()
    marker = "/media/blogger/"
    idx = lower_path.find(marker)
    if idx < 0:
        return raw
    tail = path[idx + len(marker) :].lstrip("/")
    canonical_path = f"/assets/media/google-blogger/{tail}"
    return urlunparse((parsed.scheme, parsed.netloc, canonical_path, "", "", ""))


def _collapse_legacy_key(key: str) -> str:
    normalized = str(key or "").strip().strip("/")
    if not normalized:
        return ""
    match = LEGACY_KEY_RE.match(normalized)
    if match:
        return f"assets/{match.group(1)}"
    if normalized.lower().startswith("media/blogger/"):
        return f"assets/{normalized}"
    return normalized


def canonical_key_from_legacy_key(key: str) -> str:
    collapsed = _collapse_legacy_key(key)
    if not collapsed:
        return ""
    return re.sub(r"^assets/media/blogger/", "assets/media/google-blogger/", collapsed, flags=re.IGNORECASE)


def legacy_key_candidates_from_url(url: str) -> list[str]:
    raw_key = normalize_r2_url_to_key(url)
    candidates = [raw_key, _collapse_legacy_key(raw_key)]
    result: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        token = str(item or "").strip().strip("/")
        if not token or token in seen:
            continue
        seen.add(token)
        result.append(token)
    return result


def extract_legacy_urls(text: str | None) -> list[str]:
    raw = str(text or "")
    if not raw:
        return []
    found = re.findall(r"https?://[^\s'\"<>)\]]+", raw)
    result: list[str] = []
    seen: set[str] = set()
    for url in found:
        candidate = str(url).strip().rstrip(".,);")
        for marker in ("&#", "\\", ";if(", ";return", "&quot;"):
            cut = candidate.find(marker)
            if cut > 0:
                candidate = candidate[:cut]
        lowered = candidate.lower()
        for ext in (".webp", ".png", ".jpg", ".jpeg", ".gif", ".avif"):
            idx = lowered.find(ext)
            if idx > 0:
                candidate = candidate[: idx + len(ext)]
                lowered = candidate.lower()
                break
        if not candidate:
            continue
        if not LEGACY_URL_RE.search(candidate):
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        result.append(candidate)
    return result


def apply_url_map_to_text(value: str | None, url_map: dict[str, str]) -> str:
    text = str(value or "")
    if not text or not url_map:
        return text
    updated = text
    for old, new in url_map.items():
        updated = updated.replace(old, new)
    return updated


def deep_replace_urls(value: Any, url_map: dict[str, str]) -> Any:
    if isinstance(value, str):
        return apply_url_map_to_text(value, url_map)
    if isinstance(value, list):
        return [deep_replace_urls(item, url_map) for item in value]
    if isinstance(value, dict):
        return {key: deep_replace_urls(item, url_map) for key, item in value.items()}
    return value


def _build_report_path(prefix: str) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return REPORT_DIR / f"{prefix}-{stamp}.json"


def _status_list(values: list[str] | None) -> list[PostStatus]:
    raw = [item.strip().lower() for item in (values or []) if item]
    if not raw:
        raw = ["published", "scheduled"]
    mapping = {
        "published": PostStatus.PUBLISHED,
        "scheduled": PostStatus.SCHEDULED,
        "draft": PostStatus.DRAFT,
    }
    return [mapping[item] for item in raw if item in mapping]


def _copy_and_verify_canonical(db: Session, patch: UrlPatch) -> tuple[bool, str]:
    try:
        exists = cloudflare_r2_object_exists(db, public_key="", key=patch.canonical_key)
        if exists:
            return True, "exists"
    except Exception as exc:  # noqa: BLE001
        return False, f"head_canonical_failed:{exc}"

    selected_source = ""
    for key in patch.legacy_key_candidates:
        try:
            if cloudflare_r2_object_exists(db, public_key="", key=key):
                selected_source = key
                break
        except Exception:
            continue

    if not selected_source:
        return False, "legacy_source_not_found"

    try:
        payload = cloudflare_r2_download_binary(db, public_key="", key=selected_source)
        upload_binary_to_cloudflare_r2(
            db,
            object_key=patch.canonical_key,
            filename=Path(patch.canonical_key).name,
            content=payload,
        )
        verified = cloudflare_r2_object_exists(db, public_key="", key=patch.canonical_key)
        if not verified:
            return False, "head_canonical_false_after_copy"
        return True, f"copied_from:{selected_source}"
    except Exception as exc:  # noqa: BLE001
        return False, f"copy_failed:{exc}"


def _collect_active_blogger_blogs(db: Session) -> list[Blog]:
    stmt = (
        select(Blog)
        .where(
            Blog.is_active.is_(True),
            Blog.blogger_blog_id.is_not(None),
            Blog.blogger_blog_id != "",
        )
        .order_by(Blog.id.asc())
    )
    return list(db.execute(stmt).scalars().all())


def _collect_candidate_articles(db: Session, blog_ids: list[int], statuses: list[PostStatus]) -> list[Article]:
    stmt = (
        select(Article)
        .join(BloggerPost, BloggerPost.article_id == Article.id)
        .where(BloggerPost.blog_id.in_(blog_ids), BloggerPost.post_status.in_(tuple(statuses)))
        .options(
            selectinload(Article.blog),
            selectinload(Article.image),
            selectinload(Article.blogger_post),
        )
        .order_by(Article.id.asc())
    )
    return db.execute(stmt).scalars().all()


def _article_legacy_urls(article: Article) -> list[str]:
    source_chunks = [
        article.html_article or "",
        article.assembled_html or "",
        article.excerpt or "",
        article.meta_description or "",
    ]
    if article.image:
        source_chunks.append(article.image.public_url or "")
        source_chunks.append(_json_dumps(article.image.image_metadata or {}))
    if article.blogger_post:
        source_chunks.append(_json_dumps(article.blogger_post.response_payload or {}))
    joined = "\n".join(source_chunks)
    return extract_legacy_urls(joined)


def _sync_article_to_blogger(db: Session, article: Article) -> tuple[bool, str]:
    if not article.blog or not article.blogger_post:
        return False, "missing_linked_post"
    provider = get_blogger_provider(db, article.blog)
    if not hasattr(provider, "update_post") or type(provider).__name__.startswith("Mock"):
        return False, "update_post_unavailable"
    summary, raw_payload = provider.update_post(
        post_id=article.blogger_post.blogger_post_id,
        title=article.title,
        content=article.assembled_html or article.html_article or "",
        labels=list(article.labels or []),
        meta_description=article.meta_description or "",
    )
    upsert_article_blogger_post(
        db,
        article=article,
        summary=summary,
        raw_payload=raw_payload if isinstance(raw_payload, dict) else {},
    )
    return True, "updated"


def main() -> int:
    args = parse_args()
    statuses = _status_list(args.include_status)
    report: dict[str, Any] = {
        "scope": args.scope,
        "execute": bool(args.execute),
        "sync_blogger": bool(args.sync_blogger),
        "include_status": [item.value for item in statuses],
        "legacy_ref_count_before": 0,
        "legacy_ref_count_after": 0,
        "copied_object_count": 0,
        "reposted_count": 0,
        "failed_count": 0,
        "items": [],
        "failed_items": [],
        "blogs": [],
    }

    with SessionLocal() as db:
        blogs = _collect_active_blogger_blogs(db)
        blog_ids = [int(blog.id) for blog in blogs]
        report["blogs"] = [{"blog_id": blog.id, "slug": blog.slug, "name": blog.name} for blog in blogs]
        articles = _collect_candidate_articles(db, blog_ids=blog_ids, statuses=statuses)

    for article in articles:
        urls = _article_legacy_urls(article)
        if not urls:
            continue
        report["legacy_ref_count_before"] += len(urls)
        item: dict[str, Any] = {
            "article_id": article.id,
            "blog_id": article.blog_id,
            "url_count": len(urls),
            "status": "planned" if not args.execute else "pending",
            "copied_keys": [],
            "replaced_urls": [],
            "errors": [],
        }

        patch_list: list[UrlPatch] = []
        for old_url in urls:
            old_key_candidates = legacy_key_candidates_from_url(old_url)
            base_key = old_key_candidates[0] if old_key_candidates else normalize_r2_url_to_key(old_url)
            canonical_key = canonical_key_from_legacy_key(base_key)
            new_url = normalize_legacy_url_to_canonical(old_url)
            if not canonical_key or not new_url:
                item["errors"].append(f"cannot_build_mapping:{old_url}")
                continue
            patch_list.append(
                UrlPatch(
                    old_url=old_url,
                    new_url=new_url,
                    legacy_key_candidates=old_key_candidates,
                    canonical_key=canonical_key,
                )
            )

        if not args.execute:
            item["status"] = "planned"
            item["replaced_urls"] = [{"old": p.old_url, "new": p.new_url, "canonical_key": p.canonical_key} for p in patch_list]
            report["items"].append(item)
            continue

        with SessionLocal() as db:
            fresh = db.execute(
                select(Article)
                .where(Article.id == article.id)
                .options(
                    selectinload(Article.blog),
                    selectinload(Article.image),
                    selectinload(Article.blogger_post),
                )
            ).scalar_one_or_none()
            if not fresh:
                item["status"] = "failed"
                item["errors"].append("article_not_found")
                report["failed_items"].append(item)
                report["failed_count"] += 1
                continue

            url_map: dict[str, str] = {}
            blocked = False
            for patch in patch_list:
                ok, reason = _copy_and_verify_canonical(db, patch)
                selected_patch = patch
                if (not ok) and reason == "legacy_source_not_found" and _is_non_webp_image_url(patch.old_url):
                    selected_patch = _webp_fallback_patch(patch)
                    ok, reason = _copy_and_verify_canonical(db, selected_patch)
                if not ok:
                    blocked = True
                    item["errors"].append(f"{patch.old_url}::{reason}")
                    continue
                if reason.startswith("copied_from:"):
                    report["copied_object_count"] += 1
                    item["copied_keys"].append({"canonical": selected_patch.canonical_key, "source": reason.split(":", 1)[1]})
                url_map[patch.old_url] = selected_patch.new_url

            if blocked or not url_map:
                db.rollback()
                item["status"] = "failed"
                report["failed_items"].append(item)
                report["failed_count"] += 1
                report["items"].append(item)
                continue

            fresh.html_article = apply_url_map_to_text(fresh.html_article, url_map)
            fresh.assembled_html = apply_url_map_to_text(fresh.assembled_html, url_map)
            fresh.excerpt = apply_url_map_to_text(fresh.excerpt, url_map)
            fresh.meta_description = apply_url_map_to_text(fresh.meta_description, url_map)

            if fresh.image:
                fresh.image.public_url = apply_url_map_to_text(fresh.image.public_url, url_map)
                fresh.image.image_metadata = deep_replace_urls(fresh.image.image_metadata or {}, url_map)
                cloudflare_meta = (
                    fresh.image.image_metadata.get("cloudflare")
                    if isinstance(fresh.image.image_metadata, dict)
                    else None
                )
                if isinstance(cloudflare_meta, dict):
                    current_key = str(cloudflare_meta.get("object_key") or "").strip()
                    if current_key:
                        cloudflare_meta["object_key"] = canonical_key_from_legacy_key(current_key) or current_key
                    current_public = str(cloudflare_meta.get("public_url") or "").strip()
                    if current_public:
                        cloudflare_meta["public_url"] = normalize_legacy_url_to_canonical(current_public)
                    fresh.image.image_metadata["cloudflare"] = cloudflare_meta
                db.add(fresh.image)

            if fresh.blogger_post:
                fresh.blogger_post.response_payload = deep_replace_urls(fresh.blogger_post.response_payload or {}, url_map)
                db.add(fresh.blogger_post)

            db.add(fresh)
            db.commit()
            db.refresh(fresh)

            reposted = False
            repost_reason = "skipped"
            if args.sync_blogger:
                reposted, repost_reason = _sync_article_to_blogger(db, fresh)
                if reposted:
                    report["reposted_count"] += 1

            item["status"] = "updated"
            item["reposted"] = reposted
            item["repost_reason"] = repost_reason
            item["replaced_urls"] = [{"old": old, "new": new} for old, new in url_map.items()]
            report["items"].append(item)

    if args.execute:
        with SessionLocal() as db:
            blogs = _collect_active_blogger_blogs(db)
            sync_rows: list[dict[str, Any]] = []
            for blog in blogs:
                try:
                    sync_result = sync_blogger_posts_for_blog(db, blog)
                    sync_rows.append(
                        {
                            "blog_id": blog.id,
                            "count": int(sync_result.get("count") or 0) if isinstance(sync_result, dict) else 0,
                            "source": str(sync_result.get("source") or "") if isinstance(sync_result, dict) else "",
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    sync_rows.append({"blog_id": blog.id, "error": str(exc)})
            report["sync_rows"] = sync_rows

    with SessionLocal() as db:
        blogs = _collect_active_blogger_blogs(db)
        blog_ids = [int(blog.id) for blog in blogs]
        articles = _collect_candidate_articles(db, blog_ids=blog_ids, statuses=statuses)
        after_count = 0
        for article in articles:
            after_count += len(_article_legacy_urls(article))
        report["legacy_ref_count_after"] = after_count

    report_path = _build_report_path(args.report_prefix)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "report_path": str(report_path),
                "legacy_ref_count_before": report["legacy_ref_count_before"],
                "legacy_ref_count_after": report["legacy_ref_count_after"],
                "copied_object_count": report["copied_object_count"],
                "reposted_count": report["reposted_count"],
                "failed_count": report["failed_count"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
