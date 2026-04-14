from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO_ROOT / "storage" / "reports"
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@postgres:5432/bloggent"
IMG_SRC_RE = re.compile(r"""<img\b[^>]*src=["']([^"']+)["']""", re.IGNORECASE)

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get("BLOGGENT_DATABASE_URL", DEFAULT_DATABASE_URL)
if "STORAGE_ROOT" not in os.environ:
    os.environ["STORAGE_ROOT"] = str((REPO_ROOT / "storage").resolve())
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Article, Blog, BloggerPost, Image, SyncedBloggerPost  # noqa: E402
from app.services.blogger.blogger_live_audit_service import (  # noqa: E402
    ISSUE_AUDIT_FAILED,
    ISSUE_BROKEN_IMAGE,
    ISSUE_EMPTY_FIGURE,
    ISSUE_MISSING_COVER,
    fetch_and_audit_blogger_post,
)
from app.services.providers.factory import get_blogger_provider  # noqa: E402
from app.services.platform.publishing_service import rebuild_article_html, refresh_article_public_image, upsert_article_blogger_post  # noqa: E402
from app.services.integrations.settings_service import get_settings_map  # noqa: E402
from app.services.integrations.storage_service import _resolve_cloudflare_r2_configuration  # noqa: E402
from scripts.restore_missing_live_images import (  # noqa: E402
    MatchDecision,
    TargetPost as RestoreTargetPost,
    _index_r2_objects,
    _list_r2_objects,
    _public_origin_from_base,
    _rank_folder_keys,
    _slug_seed_from_blogger,
    _strip_assets_prefix,
    _strict_match_existing_urls,
    _year_month_from_url,
)


@dataclass(slots=True)
class RepairTarget:
    blogger_post: BloggerPost
    blog: Blog
    article: Article | None
    synced_post: SyncedBloggerPost | None
    issue_codes: set[str]


@dataclass(slots=True)
class AssetResolution:
    public_url: str
    canonical_key: str
    source: str


@dataclass(slots=True)
class ExactAssetPatch:
    hero: AssetResolution | None
    inline_updates: list[tuple[int, str, AssetResolution]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Repair Blogger posts whose main cover figure is missing and report strict R2 candidates.",
    )
    parser.add_argument("--mode", choices=("dry-run", "apply"), default="dry-run")
    parser.add_argument("--blog-id", action="append", type=int, default=[], help="Target blog id. Repeat for multiple.")
    parser.add_argument("--url", action="append", default=[], help="Target post URL. Repeat for multiple.")
    parser.add_argument("--report-path", default="", help="Optional JSON report path.")
    parser.add_argument("--timeout", type=float, default=15.0, help="Live audit timeout in seconds.")
    return parser.parse_args()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _normalize_blogger_url_key(value: str) -> str:
    raw = _safe_str(value).rstrip("/")
    if not raw:
        return ""
    parsed = urlparse(raw)
    host = _safe_str(parsed.netloc).lower()
    path = unquote(_safe_str(parsed.path)).rstrip("/")
    return f"{host}{path}".lower()


def _extract_image_urls(html_value: str | None) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in IMG_SRC_RE.findall(html_value or ""):
        candidate = _safe_str(match)
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        urls.append(candidate)
    return urls


def _extract_inline_media_urls(article: Article | None) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    if article is None or not isinstance(article.inline_media, list):
        return urls
    for item in article.inline_media:
        if not isinstance(item, dict):
            continue
        delivery = item.get("delivery") if isinstance(item.get("delivery"), dict) else {}
        cloudflare = delivery.get("cloudflare") if isinstance(delivery, dict) else {}
        cloudinary = delivery.get("cloudinary") if isinstance(delivery, dict) else {}
        candidates = [
            _safe_str(cloudflare.get("original_url")) if isinstance(cloudflare, dict) else "",
            _safe_str(cloudinary.get("secure_url_original")) if isinstance(cloudinary, dict) else "",
            _safe_str(item.get("image_url")),
        ]
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            urls.append(candidate)
    return urls


def _extract_article_hero_metadata_url(image: Image | None) -> str:
    if image is None or not isinstance(image.image_metadata, dict):
        return ""
    delivery = image.image_metadata.get("delivery") if isinstance(image.image_metadata.get("delivery"), dict) else {}
    cloudflare = delivery.get("cloudflare") if isinstance(delivery, dict) else {}
    cloudinary = delivery.get("cloudinary") if isinstance(delivery, dict) else {}
    for candidate in (
        _safe_str(cloudflare.get("original_url")) if isinstance(cloudflare, dict) else "",
        _safe_str(cloudinary.get("secure_url_original")) if isinstance(cloudinary, dict) else "",
    ):
        if candidate:
            return candidate
    return ""


def _replace_suffix(value: str, suffix: str) -> str:
    text = _safe_str(value)
    if not text:
        return ""
    return re.sub(r"\.[A-Za-z0-9]+$", suffix, text)


def _extract_month_and_folder_from_canonical_key(canonical_key: str) -> tuple[str, str]:
    parts = _safe_str(canonical_key).split("/")
    if len(parts) < 6:
        return "", ""
    if parts[0] != "media" or parts[1] != "posts":
        return "", ""
    return f"{parts[2]}/{parts[3]}", parts[4]


def _canonical_key_exists(canonical_key: str, r2_index: dict[str, dict[str, list[str]]]) -> bool:
    month_key, folder = _extract_month_and_folder_from_canonical_key(canonical_key)
    if not month_key or not folder:
        return False
    return _safe_str(canonical_key) in set(r2_index.get(month_key, {}).get(folder, []))


def _canonical_key_from_asset_url(url: str) -> str:
    parsed = urlparse(_safe_str(url))
    path = _safe_str(unquote(parsed.path))
    if not path:
        return ""
    if "/assets/" in path:
        path = path.split("/assets/", 1)[1]
    path = path.lstrip("/")
    return _strip_assets_prefix(path)


def _infer_public_base_url(url: str) -> str:
    parsed = urlparse(_safe_str(url))
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}/assets"


def _build_public_url_from_public_base(*, public_base_url: str, canonical_key: str) -> str:
    base = _safe_str(public_base_url).rstrip("/")
    key = _safe_str(canonical_key).lstrip("/")
    if not base or not key:
        return ""
    return f"{base}/assets/{key}"


def _is_public_image_url_healthy(url: str, *, timeout: float = 15.0) -> bool:
    candidate = _safe_str(url)
    if not candidate:
        return False
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            response = client.head(candidate)
            content_type = _safe_str(response.headers.get("content-type")).lower()
            if response.status_code < 400 and content_type.startswith("image/"):
                return True
            if response.status_code not in {403, 405}:
                return False
            response = client.get(candidate)
            content_type = _safe_str(response.headers.get("content-type")).lower()
            return response.status_code < 400 and content_type.startswith("image/")
    except Exception:
        return False


def _candidate_canonical_keys(*, url_candidates: list[str], object_key: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for raw_candidate in [object_key, *url_candidates]:
        candidate = _safe_str(raw_candidate)
        if not candidate:
            continue
        canonical = _strip_assets_prefix(candidate) if "/" in candidate and not candidate.startswith("http") else _canonical_key_from_asset_url(candidate)
        canonical = _safe_str(canonical)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        candidates.append(canonical)
        if Path(canonical).suffix.lower() != ".webp":
            webp_variant = _replace_suffix(canonical, ".webp")
            if webp_variant not in seen:
                seen.add(webp_variant)
                candidates.append(webp_variant)
    return candidates


def _resolve_exact_r2_public_url(
    *,
    url_candidates: list[str],
    object_key: str,
    public_base_url: str,
    r2_index: dict[str, dict[str, list[str]]],
) -> AssetResolution | None:
    for canonical_key in _candidate_canonical_keys(url_candidates=url_candidates, object_key=object_key):
        if not _canonical_key_exists(canonical_key, r2_index):
            continue
        return AssetResolution(
            public_url=_build_public_url_from_public_base(public_base_url=public_base_url, canonical_key=canonical_key),
            canonical_key=canonical_key,
            source="exact_r2",
        )
    return None


def _update_cloudflare_delivery(
    *,
    delivery: dict[str, Any],
    resolved: AssetResolution,
) -> dict[str, Any]:
    updated_delivery = dict(delivery or {})
    cloudflare = updated_delivery.get("cloudflare") if isinstance(updated_delivery.get("cloudflare"), dict) else {}
    updated_cloudflare = dict(cloudflare or {})
    updated_cloudflare["original_url"] = resolved.public_url
    updated_cloudflare["object_key"] = resolved.canonical_key
    updated_cloudflare["public_base_url"] = _infer_public_base_url(resolved.public_url)
    updated_cloudflare["transform_enabled"] = False
    updated_delivery["cloudflare"] = updated_cloudflare
    updated_delivery["public_url"] = resolved.public_url
    return updated_delivery


def _build_exact_asset_patch(
    target: RepairTarget,
    *,
    public_base_url: str,
    r2_index: dict[str, dict[str, list[str]]],
) -> ExactAssetPatch:
    article = target.article
    if article is None:
        return ExactAssetPatch(hero=None, inline_updates=[])

    hero_resolution: AssetResolution | None = None
    if article.image is not None:
        metadata = article.image.image_metadata if isinstance(article.image.image_metadata, dict) else {}
        delivery = metadata.get("delivery") if isinstance(metadata.get("delivery"), dict) else {}
        cloudflare = delivery.get("cloudflare") if isinstance(delivery.get("cloudflare"), dict) else {}
        hero_resolution = _resolve_exact_r2_public_url(
            url_candidates=[
                _safe_str(article.image.public_url),
                _extract_article_hero_metadata_url(article.image),
                _safe_str(delivery.get("public_url")) if isinstance(delivery, dict) else "",
            ],
            object_key=_safe_str(cloudflare.get("object_key")) if isinstance(cloudflare, dict) else "",
            public_base_url=public_base_url,
            r2_index=r2_index,
        )

    inline_updates: list[tuple[int, str, AssetResolution]] = []
    media_items = article.inline_media if isinstance(article.inline_media, list) else []
    for index, item in enumerate(media_items):
        if not isinstance(item, dict):
            continue
        delivery = item.get("delivery") if isinstance(item.get("delivery"), dict) else {}
        cloudflare = delivery.get("cloudflare") if isinstance(delivery.get("cloudflare"), dict) else {}
        resolution = _resolve_exact_r2_public_url(
            url_candidates=[
                _safe_str(item.get("image_url")),
                _safe_str(cloudflare.get("original_url")) if isinstance(cloudflare, dict) else "",
                _safe_str(delivery.get("public_url")) if isinstance(delivery, dict) else "",
            ],
            object_key=_safe_str(cloudflare.get("object_key")) if isinstance(cloudflare, dict) else "",
            public_base_url=public_base_url,
            r2_index=r2_index,
        )
        if resolution is None:
            continue
        inline_updates.append((index, _safe_str(item.get("slot")), resolution))

    return ExactAssetPatch(hero=hero_resolution, inline_updates=inline_updates)


def _apply_exact_asset_patch(target: RepairTarget, patch: ExactAssetPatch) -> bool:
    article = target.article
    if article is None:
        return False

    changed = False
    if patch.hero is not None and article.image is not None:
        metadata = dict(article.image.image_metadata or {})
        delivery = metadata.get("delivery") if isinstance(metadata.get("delivery"), dict) else {}
        metadata["delivery"] = _update_cloudflare_delivery(delivery=delivery, resolved=patch.hero)
        if article.image.public_url != patch.hero.public_url or article.image.image_metadata != metadata:
            article.image.public_url = patch.hero.public_url
            article.image.image_metadata = metadata
            changed = True

    if patch.inline_updates:
        updated_media = [dict(item) if isinstance(item, dict) else item for item in (article.inline_media or [])]
        for index, _slot, resolution in patch.inline_updates:
            current_item = updated_media[index]
            if not isinstance(current_item, dict):
                continue
            delivery = current_item.get("delivery") if isinstance(current_item.get("delivery"), dict) else {}
            current_item["delivery"] = _update_cloudflare_delivery(delivery=delivery, resolved=resolution)
            current_item["image_url"] = resolution.public_url
            updated_media[index] = current_item
            changed = True
        article.inline_media = updated_media

    if patch.hero is not None and target.synced_post is not None and target.synced_post.thumbnail_url != patch.hero.public_url:
        target.synced_post.thumbnail_url = patch.hero.public_url
        changed = True

    return changed


def _has_repairable_db_hero(article: Article | None) -> bool:
    if article is None or article.image is None:
        return False
    image = article.image
    if _safe_str(image.public_url):
        return True
    if _safe_str(_extract_article_hero_metadata_url(image)):
        return True
    file_path = _safe_str(image.file_path)
    return bool(file_path and Path(file_path).exists())


def _has_local_hero_file(article: Article | None) -> bool:
    if article is None or article.image is None:
        return False
    file_path = _safe_str(article.image.file_path)
    return bool(file_path and Path(file_path).exists())


def _resolve_existing_hero_url(article: Article | None) -> str:
    if article is None or article.image is None:
        return ""
    image = article.image
    for candidate in (_safe_str(image.public_url), _safe_str(_extract_article_hero_metadata_url(image))):
        if candidate:
            return candidate
    return ""


def _resolve_hero_url_for_apply(db: Session, article: Article | None, *, allow_existing: bool = True) -> str:
    if article is None or article.image is None:
        return ""
    image = article.image
    file_path = _safe_str(image.file_path)
    if file_path and Path(file_path).exists():
        try:
            resolved = _safe_str(refresh_article_public_image(db, article))
            if resolved:
                return resolved
        except FileNotFoundError:
            pass
    if allow_existing:
        return _resolve_existing_hero_url(article)
    return ""


def _build_restore_target(target: RepairTarget) -> RestoreTargetPost:
    article = target.article
    synced_post = target.synced_post
    title = _safe_str(article.title if article is not None else target.blogger_post.published_url) or "Untitled"
    slug_seed = _safe_str(article.slug if article is not None else "")
    if not slug_seed:
        slug_seed = _slug_seed_from_blogger(_safe_str(target.blogger_post.published_url), title)
    content = ""
    if article is not None:
        content = _safe_str(article.assembled_html or article.html_article)
    if not content and synced_post is not None:
        content = _safe_str(synced_post.content_html)
    excerpt = _safe_str(article.excerpt if article is not None else "")
    if not excerpt and synced_post is not None:
        excerpt = _safe_str(synced_post.excerpt_text)
    labels = list(article.labels or []) if article is not None else list((synced_post.labels or []) if synced_post else [])
    return RestoreTargetPost(
        source="blogger",
        post_id=_safe_str(target.blogger_post.blogger_post_id),
        title=title,
        post_url=_safe_str(target.blogger_post.published_url),
        content=content,
        month_key=_year_month_from_url(_safe_str(target.blogger_post.published_url)),
        slug_seed=slug_seed,
        group_name=_safe_str(target.blog.name),
        category_hint=f"{_safe_str(target.blog.primary_language)}:{_safe_str(target.blog.profile_key)}",
        cover_alt=title,
        blog_id=target.blog.id,
        labels=labels,
        excerpt=excerpt,
        blogger_thumbnail_url=_safe_str(synced_post.thumbnail_url) if synced_post is not None else "",
    )


def _init_report(mode: str, *, blog_ids: list[int], urls: list[str]) -> dict[str, Any]:
    return {
        "generated_at": _utc_now_iso(),
        "mode": mode,
        "filters": {
            "blog_ids": blog_ids,
            "urls": urls,
        },
        "summary": {
            "audited": 0,
            "targets": 0,
            "reassemblable": 0,
            "repaired": 0,
            "report_only": 0,
            "ambiguous": 0,
            "no_candidate": 0,
            "repair_failed": 0,
            "audit_failed": 0,
        },
        "by_blog": {},
        "items": [],
        "warnings": [],
    }


def _ensure_blog_summary(report: dict[str, Any], blog: Blog) -> dict[str, Any]:
    key = str(blog.id)
    bucket = report["by_blog"].get(key)
    if bucket is None:
        bucket = {
            "blog_id": blog.id,
            "blog_name": blog.name,
            "host": _safe_str(urlparse(_safe_str(blog.blogger_url)).netloc),
            "audited": 0,
            "targets": 0,
            "reassemblable": 0,
            "repaired": 0,
            "report_only": 0,
            "ambiguous": 0,
            "no_candidate": 0,
            "repair_failed": 0,
            "audit_failed": 0,
        }
        report["by_blog"][key] = bucket
    return bucket


def _collect_targets(
    db: Session,
    *,
    blog_ids: list[int],
    urls: list[str],
    timeout: float,
    report: dict[str, Any],
) -> list[RepairTarget]:
    query = (
        select(BloggerPost)
        .where(BloggerPost.published_url.is_not(None))
        .options(
            selectinload(BloggerPost.blog),
            selectinload(BloggerPost.article).selectinload(Article.image),
        )
        .order_by(BloggerPost.blog_id.asc(), BloggerPost.id.desc())
    )
    if blog_ids:
        query = query.where(BloggerPost.blog_id.in_(blog_ids))
    posts = db.execute(query).scalars().all()

    url_filters = {_normalize_blogger_url_key(value) for value in urls if _normalize_blogger_url_key(value)}
    if url_filters:
        posts = [post for post in posts if _normalize_blogger_url_key(post.published_url) in url_filters]

    target_keys = {
        _normalize_blogger_url_key(post.published_url)
        for post in posts
        if _normalize_blogger_url_key(post.published_url)
    }
    synced_posts = db.execute(select(SyncedBloggerPost).where(SyncedBloggerPost.url.is_not(None))).scalars().all()
    synced_by_key = {
        _normalize_blogger_url_key(row.url): row
        for row in synced_posts
        if _normalize_blogger_url_key(row.url) in target_keys
    }

    targets: list[RepairTarget] = []
    for post in posts:
        if post.blog is None:
            continue

        blog_summary = _ensure_blog_summary(report, post.blog)
        report["summary"]["audited"] += 1
        blog_summary["audited"] += 1

        audit = fetch_and_audit_blogger_post(
            post.published_url,
            timeout=timeout,
            probe_images=True,
        )
        if audit.live_image_issue == ISSUE_AUDIT_FAILED:
            report["summary"]["audit_failed"] += 1
            blog_summary["audit_failed"] += 1
            report["warnings"].append(
                {
                    "blog_id": post.blog_id,
                    "url": _safe_str(post.published_url),
                    "reason": ISSUE_AUDIT_FAILED,
                }
            )
            continue

        issue_codes = {
            code
            for code in _safe_str(audit.live_image_issue).split(",")
            if code
        }
        should_target = (
            audit.live_cover_present is False
            or ISSUE_MISSING_COVER in issue_codes
            or ISSUE_BROKEN_IMAGE in issue_codes
        )
        if not should_target:
            continue

        report["summary"]["targets"] += 1
        blog_summary["targets"] += 1
        targets.append(
            RepairTarget(
                blogger_post=post,
                blog=post.blog,
                article=post.article,
                synced_post=synced_by_key.get(_normalize_blogger_url_key(post.published_url)),
                issue_codes=issue_codes,
            )
        )
    return targets


def _build_item_base(target: RepairTarget) -> dict[str, Any]:
    article = target.article
    synced_post = target.synced_post
    return {
        "blog_id": target.blog.id,
        "blog_name": target.blog.name,
        "url": _safe_str(target.blogger_post.published_url),
        "title": _safe_str(article.title if article is not None else target.blogger_post.published_url),
        "article_id": article.id if article is not None else None,
        "blogger_post_id": _safe_str(target.blogger_post.blogger_post_id),
        "issue_codes": sorted(target.issue_codes),
        "db_hero_available": _has_repairable_db_hero(article),
        "db_hero_public_url": _safe_str(article.image.public_url) if article is not None and article.image is not None else "",
        "db_hero_metadata_url": _extract_article_hero_metadata_url(article.image if article is not None else None),
        "db_hero_file_path": _safe_str(article.image.file_path) if article is not None and article.image is not None else "",
        "synced_thumbnail_url": _safe_str(synced_post.thumbnail_url) if synced_post is not None else "",
        "inline_media_urls": _extract_inline_media_urls(article),
        "assembled_html_image_urls": _extract_image_urls(article.assembled_html if article is not None else ""),
    }


def _load_r2_index(db: Session) -> tuple[str, dict[str, dict[str, list[str]]]]:
    settings_map = get_settings_map(db)
    account_id, bucket, access_key_id, secret_access_key, public_base_url, _prefix = _resolve_cloudflare_r2_configuration(
        settings_map
    )
    if not account_id or not bucket or not access_key_id or not secret_access_key:
        raise RuntimeError("Cloudflare R2 credentials are required.")
    if not public_base_url:
        raise RuntimeError("cloudflare_r2_public_base_url is required.")
    r2_objects = _list_r2_objects(
        account_id=account_id,
        bucket=bucket,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
    )
    return public_base_url, _index_r2_objects(r2_objects)


def _strict_match_existing_urls_with_public_base(
    *,
    target: RestoreTargetPost,
    r2_index: dict[str, dict[str, list[str]]],
    public_base_url: str,
) -> MatchDecision:
    decision = _strict_match_existing_urls(
        target=target,
        r2_index=r2_index,
        public_origin=_public_origin_from_base(public_base_url),
    )
    if not decision.matched:
        return decision
    month_bucket = r2_index.get(_safe_str(target.month_key)) or {}
    folder_keys = month_bucket.get(_safe_str(decision.folder)) or []
    cover_key, inline1_key = _rank_folder_keys(folder_keys)
    if not cover_key:
        return MatchDecision(matched=False, reason="strict_folder_empty")
    return MatchDecision(
        matched=True,
        reason=decision.reason,
        cover_url=_build_public_url_from_public_base(public_base_url=public_base_url, canonical_key=cover_key),
        inline1_url=_build_public_url_from_public_base(
            public_base_url=public_base_url,
            canonical_key=inline1_key or cover_key,
        ),
        inline2_url=_build_public_url_from_public_base(
            public_base_url=public_base_url,
            canonical_key=inline1_key or cover_key,
        ),
        folder=decision.folder,
        score=decision.score,
        candidates=decision.candidates,
    )


def _append_summary(report: dict[str, Any], *, blog_id: int, field: str) -> None:
    report["summary"][field] += 1
    blog_summary = report["by_blog"].get(str(blog_id))
    if blog_summary is not None:
        blog_summary[field] += 1


def _reassemble_and_publish(db: Session, target: RepairTarget, *, hero_url: str) -> tuple[bool, str]:
    if target.article is None:
        return False, "article_missing"

    provider = get_blogger_provider(db, target.blog)
    if not hasattr(provider, "update_post") or type(provider).__name__.startswith("Mock"):
        return False, "update_post_unavailable"

    assembled_html = rebuild_article_html(db, target.article, hero_url)
    summary, raw_payload = provider.update_post(
        post_id=target.blogger_post.blogger_post_id,
        title=target.article.title,
        content=assembled_html,
        labels=list(target.article.labels or []),
        meta_description=target.article.meta_description or "",
    )
    upsert_article_blogger_post(
        db,
        article=target.article,
        summary=summary,
        raw_payload=raw_payload if isinstance(raw_payload, dict) else {},
    )
    return True, "ok"


def _exact_patch_payload(patch: ExactAssetPatch) -> dict[str, Any]:
    return {
        "hero_url": patch.hero.public_url if patch.hero is not None else "",
        "hero_canonical_key": patch.hero.canonical_key if patch.hero is not None else "",
        "inline_updates": [
            {
                "index": index,
                "slot": slot,
                "url": resolution.public_url,
                "canonical_key": resolution.canonical_key,
            }
            for index, slot, resolution in patch.inline_updates
        ],
    }


def run_repair(
    db: Session,
    *,
    mode: str,
    blog_ids: list[int] | None = None,
    urls: list[str] | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    normalized_blog_ids = sorted({int(value) for value in (blog_ids or [])})
    normalized_urls = [_safe_str(value) for value in (urls or []) if _safe_str(value)]
    report = _init_report(mode, blog_ids=normalized_blog_ids, urls=normalized_urls)
    targets = _collect_targets(
        db,
        blog_ids=normalized_blog_ids,
        urls=normalized_urls,
        timeout=timeout,
        report=report,
    )

    unresolved: list[tuple[RepairTarget, dict[str, Any]]] = []
    publish_queue: list[tuple[RepairTarget, dict[str, Any], str]] = []
    apply_mode = mode == "apply"
    r2_state: tuple[str, dict[str, dict[str, list[str]]]] | None = None
    patched_assets = False

    def _ensure_r2_state() -> tuple[str, dict[str, dict[str, list[str]]]]:
        nonlocal r2_state
        if r2_state is None:
            r2_state = _load_r2_index(db)
        return r2_state

    for target in targets:
        item = _build_item_base(target)
        exact_patch = ExactAssetPatch(hero=None, inline_updates=[])
        if ISSUE_BROKEN_IMAGE in target.issue_codes or not item["db_hero_available"]:
            public_base_url, r2_index = _ensure_r2_state()
            exact_patch = _build_exact_asset_patch(
                target,
                public_base_url=public_base_url,
                r2_index=r2_index,
            )
            item["exact_r2_patch"] = _exact_patch_payload(exact_patch)

        current_existing_hero = _resolve_existing_hero_url(target.article)
        existing_hero_healthy = True
        if ISSUE_BROKEN_IMAGE in target.issue_codes and exact_patch.hero is None:
            existing_hero_healthy = _is_public_image_url_healthy(current_existing_hero)
        can_use_existing_hero = ISSUE_BROKEN_IMAGE not in target.issue_codes or existing_hero_healthy
        if item["db_hero_available"]:
            hero_url = exact_patch.hero.public_url if exact_patch.hero is not None else ""
            if not hero_url and apply_mode:
                hero_url = _resolve_hero_url_for_apply(
                    db,
                    target.article,
                    allow_existing=can_use_existing_hero,
                )
            elif not hero_url and can_use_existing_hero:
                hero_url = _resolve_existing_hero_url(target.article)
            elif not hero_url and _has_local_hero_file(target.article):
                hero_url = "local-file-refresh"

            if hero_url:
                _append_summary(report, blog_id=target.blog.id, field="reassemblable")
                if not apply_mode:
                    item["status"] = "reassemblable"
                    item["resolved_hero_url"] = hero_url
                    report["items"].append(item)
                    continue

                if exact_patch.hero is not None or exact_patch.inline_updates:
                    if _apply_exact_asset_patch(target, exact_patch):
                        patched_assets = True
                        item["asset_patch_applied"] = True
                publish_queue.append((target, item, hero_url))
                continue

        unresolved.append((target, item))

    if apply_mode and patched_assets:
        db.commit()

    for target, item, hero_url in publish_queue:
        ok, reason = _reassemble_and_publish(db, target, hero_url=hero_url)
        item["resolved_hero_url"] = hero_url
        item["status"] = "reassembled" if ok else "repair_failed"
        if ok:
            _append_summary(report, blog_id=target.blog.id, field="repaired")
        else:
            item["reason"] = reason
            _append_summary(report, blog_id=target.blog.id, field="repair_failed")
        report["items"].append(item)

    if unresolved:
        public_base_url, r2_index = _ensure_r2_state()
        for target, item in unresolved:
            decision = _strict_match_existing_urls_with_public_base(
                target=_build_restore_target(target),
                r2_index=r2_index,
                public_base_url=public_base_url,
            )
            item["r2_match"] = {
                "matched": bool(decision.matched),
                "reason": decision.reason,
                "folder": decision.folder,
                "score": decision.score,
                "cover_url": decision.cover_url,
                "inline1_url": decision.inline1_url,
                "inline2_url": decision.inline2_url,
                "candidates": decision.candidates or [],
            }
            if decision.matched:
                item["status"] = "report_only"
                _append_summary(report, blog_id=target.blog.id, field="report_only")
            elif decision.reason == "strict_ambiguous":
                item["status"] = "strict_ambiguous"
                _append_summary(report, blog_id=target.blog.id, field="ambiguous")
            else:
                item["status"] = "no_candidate"
                _append_summary(report, blog_id=target.blog.id, field="no_candidate")
            report["items"].append(item)

    report["items"].sort(key=lambda row: (_safe_str(row.get("blog_name")), _safe_str(row.get("url"))))
    report["by_blog"] = [
        report["by_blog"][key]
        for key in sorted(report["by_blog"].keys(), key=lambda value: int(value))
    ]
    return report


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    report_path = Path(args.report_path) if _safe_str(args.report_path) else REPORT_DIR / f"repair-blogger-missing-cover-{_timestamp()}.json"
    with SessionLocal() as db:
        report = run_repair(
            db,
            mode=args.mode,
            blog_ids=list(args.blog_id or []),
            urls=list(args.url or []),
            timeout=float(args.timeout),
        )
    _write_json(report_path, report)
    print(json.dumps({"report_path": str(report_path), "summary": report["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
