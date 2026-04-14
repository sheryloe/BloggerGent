from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse, urlunparse

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
from app.models.entities import Blog, SyncedBloggerPost  # noqa: E402
from app.services.blogger.blogger_sync_service import sync_blogger_posts_for_blog  # noqa: E402
from app.services.cloudflare.cloudflare_channel_service import (  # noqa: E402
    _integration_data_or_raise,
    _integration_request,
    _list_integration_posts,
    _safe_fallback_image_prompt,
    _upload_integration_asset,
)
from app.services.cloudflare.cloudflare_sync_service import sync_cloudflare_posts  # noqa: E402
from app.services.providers.factory import get_blogger_provider, get_image_provider  # noqa: E402

LIVE_STATUSES = {"live", "published"}
HTML_IMG_RE = re.compile(r"<img\b[^>]*\bsrc=['\"]([^'\"]+)['\"]", re.IGNORECASE)
SRCSET_RE = re.compile(r"\bsrcset=['\"]([^'\"]+)['\"]", re.IGNORECASE)
MD_IMG_RE = re.compile(r"!\[[^\]]*]\(([^)\s]+)\)")
URL_RE = re.compile(r"https?://[^\s'\"<>)\]]+")
P_END_RE = re.compile(r"</p>", re.IGNORECASE)
SEO_META_DIV_RE = re.compile(
    r"<div\b[^>]*id=['\"]bloggent-seo-meta['\"][^>]*>.*?</div>",
    re.IGNORECASE | re.DOTALL,
)
HEADER_END_RE = re.compile(r"</header>", re.IGNORECASE)
RELATED_SECTION_RE = re.compile(
    r"<section\b[^>]*class=['\"][^'\"]*related-posts[^'\"]*['\"][^>]*>.*?</section>",
    re.IGNORECASE | re.DOTALL,
)
RESTORE_FIGURE_RE = re.compile(
    r"<figure\b[^>]*data-bloggent-restore-slot=['\"][^'\"]+['\"][^>]*>.*?</figure>",
    re.IGNORECASE | re.DOTALL,
)
NORMALIZE_FIGURE_RE = re.compile(
    r"<figure\b[^>]*data-bloggent-normalize-slot=['\"][^'\"]+['\"][^>]*>.*?</figure>",
    re.IGNORECASE | re.DOTALL,
)
INLINE_FIGURE_RE = re.compile(
    r"<figure\b[^>]*>.*?<img\b[^>]*>.*?</figure>",
    re.IGNORECASE | re.DOTALL,
)
ONERROR_RE = re.compile(r"\s+onerror=(['\"]).*?\1", re.IGNORECASE | re.DOTALL)
WHITESPACE_RE = re.compile(r"\s+")

MARK_COVER = "<!--BLOGGENT_NORMALIZE_COVER-->"
MARK_INLINE = "<!--BLOGGENT_NORMALIZE_INLINE-->"

OLD_MARKERS = [
    "<!--BLOGGENT_RESTORE_COVER-->",
    "<!--BLOGGENT_RESTORE_INLINE_1-->",
    "<!--BLOGGENT_RESTORE_INLINE_2-->",
    "<!--TRAVEL_INLINE_3X2-->",
    "<!--MYSTERY_INLINE_3X2-->",
    MARK_COVER,
    MARK_INLINE,
]


@dataclass
class TargetPost:
    source: str
    post_id: str
    title: str
    post_url: str
    content: str
    cover_alt: str
    category_hint: str
    group_name: str
    slug_seed: str
    blog_id: int | None = None
    labels: list[str] | None = None
    excerpt: str = ""
    cloudflare_slug: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize LIVE posts to exactly 2 unique body images (cover + inline).",
    )
    parser.add_argument("--mode", choices=("audit", "canary", "full"), default="audit")
    parser.add_argument("--source", choices=("all", "blogger", "cloudflare"), default="all")
    parser.add_argument("--generation-policy", choices=("existing-only", "generate"), default="existing-only")
    parser.add_argument("--model", default="gpt-image-1")
    parser.add_argument("--canary-count", type=int, default=15)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--report-path", default="")
    return parser.parse_args()


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_live_status(value: Any) -> bool:
    return _safe_str(value).lower() in LIVE_STATUSES


def _quote_path(path: str) -> str:
    return quote(unquote(path), safe="/-_.~")


def _normalize_url(url: str) -> str:
    parsed = urlparse(_safe_str(url))
    if not parsed.scheme or not parsed.netloc:
        return _safe_str(url)
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            _quote_path(parsed.path),
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def _replace_path_token(url: str, source: str, target: str) -> str:
    parsed = urlparse(url)
    path = unquote(parsed.path or "")
    if source not in path:
        return ""
    replaced = path.replace(source, target, 1)
    if replaced == path:
        return ""
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            _quote_path(replaced),
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def _replace_path_extension(url: str, extension: str) -> str:
    parsed = urlparse(url)
    path = unquote(parsed.path or "")
    dot = path.rfind(".")
    slash = path.rfind("/")
    if dot <= slash:
        return ""
    replaced = f"{path[:dot]}{extension}"
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            _quote_path(replaced),
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def _candidate_urls(url: str) -> list[str]:
    normalized = _normalize_url(url)
    if not normalized:
        return []
    out: list[str] = []
    for source, target in (
        ("/assets/media/", "/assets/assets/media/"),
        ("/assets/assets/media/", "/assets/media/"),
    ):
        swapped = _replace_path_token(normalized, source, target)
        if swapped:
            out.append(swapped)

    lowered_path = urlparse(normalized).path.lower()
    if lowered_path.endswith(".webp"):
        for ext in (".png", ".jpg", ".jpeg"):
            switched = _replace_path_extension(normalized, ext)
            if switched:
                out.append(switched)
    unique: list[str] = []
    seen: set[str] = set()
    for item in out:
        candidate = _normalize_url(item)
        if not candidate or candidate == normalized or candidate in seen:
            continue
        seen.add(candidate)
        unique.append(candidate)
    return unique


def _probe_url(
    client: httpx.Client,
    url: str,
    timeout: float,
    cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    normalized = _normalize_url(url)
    if normalized in cache:
        return cache[normalized]
    try:
        response = client.get(normalized, timeout=timeout, follow_redirects=True)
        result = {
            "url": normalized,
            "status_code": int(response.status_code),
            "ok": bool(response.status_code < 400),
            "content_type": _safe_str(response.headers.get("content-type")),
        }
    except Exception as exc:  # noqa: BLE001
        result = {"url": normalized, "status_code": 0, "ok": False, "error": str(exc)}
    cache[normalized] = result
    return result


def _resolve_healthy_url(
    client: httpx.Client,
    url: str,
    timeout: float,
    cache: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any], bool]:
    probe = _probe_url(client, url, timeout, cache)
    if probe.get("ok"):
        return _normalize_url(url), probe, False
    for candidate in _candidate_urls(url):
        c_probe = _probe_url(client, candidate, timeout, cache)
        if c_probe.get("ok"):
            return candidate, c_probe, True
    return _normalize_url(url), probe, False


def _extract_srcset_urls(srcset_value: str) -> list[str]:
    urls: list[str] = []
    for part in (srcset_value or "").split(","):
        token = part.strip().split(" ")[0].strip()
        if token:
            urls.append(token)
    return urls


def _looks_like_image_url(url: str) -> bool:
    lowered = _safe_str(url).lower()
    if any(lowered.endswith(ext) for ext in (".webp", ".png", ".jpg", ".jpeg", ".gif", ".avif", ".svg")):
        return True
    return "/assets/media/" in lowered or "/assets/assets/media/" in lowered or "/cdn-cgi/image/" in lowered


def _extract_image_urls(content: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for match in HTML_IMG_RE.finditer(content or ""):
        value = _safe_str(match.group(1))
        if value and _looks_like_image_url(value) and value not in seen:
            seen.add(value)
            out.append(value)
    for match in SRCSET_RE.finditer(content or ""):
        for value in _extract_srcset_urls(match.group(1)):
            if value and _looks_like_image_url(value) and value not in seen:
                seen.add(value)
                out.append(value)
    for match in MD_IMG_RE.finditer(content or ""):
        value = _safe_str(match.group(1))
        if value and _looks_like_image_url(value) and value not in seen:
            seen.add(value)
            out.append(value)
    for match in URL_RE.finditer(content or ""):
        value = _safe_str(match.group(0))
        if value and _looks_like_image_url(value) and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _dedupe_normalized(urls: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in urls:
        normalized = _normalize_url(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def _protect_related_sections(content: str) -> tuple[str, dict[str, str]]:
    placeholders: dict[str, str] = {}
    index = 0

    def replacer(match: re.Match[str]) -> str:
        nonlocal index
        token = f"__BLOGGENT_RELATED_SECTION_{index}__"
        placeholders[token] = match.group(0)
        index += 1
        return token

    return RELATED_SECTION_RE.sub(replacer, content or ""), placeholders


def _restore_related_sections(content: str, placeholders: dict[str, str]) -> str:
    restored = content
    for token, section in placeholders.items():
        restored = restored.replace(token, section)
    return restored


def _extract_body_image_inventory(content: str) -> tuple[list[str], list[str]]:
    protected, _ = _protect_related_sections(content or "")
    tag_urls: list[str] = []

    for match in HTML_IMG_RE.finditer(protected):
        value = _safe_str(match.group(1))
        if value and _looks_like_image_url(value):
            tag_urls.append(value)

    for match in MD_IMG_RE.finditer(protected):
        value = _safe_str(match.group(1))
        if value and _looks_like_image_url(value):
            tag_urls.append(value)

    candidate_urls = _extract_image_urls(protected)
    if not candidate_urls and tag_urls:
        candidate_urls = tag_urls.copy()
    return tag_urls, candidate_urls


def _collapse_blank_lines(content: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", content or "").strip()


def _strip_existing_body_images(content: str) -> str:
    working = content or ""
    for marker in OLD_MARKERS:
        working = working.replace(marker, "")
    working = RESTORE_FIGURE_RE.sub("", working)
    working = NORMALIZE_FIGURE_RE.sub("", working)
    working = INLINE_FIGURE_RE.sub("", working)
    working = re.sub(r"<img\b[^>]*>", "", working, flags=re.IGNORECASE)
    working = re.sub(r"!\[[^\]]*]\([^)]+\)", "", working)
    return _collapse_blank_lines(working)


def _escape_attr(value: str) -> str:
    return html.escape(_safe_str(value), quote=True)


def _make_cover_block(url: str, title: str, alt: str) -> str:
    return (
        f"{MARK_COVER}\n"
        '<figure data-bloggent-normalize-slot="cover" style="margin:0 0 32px;">'
        f'<img src="{_escape_attr(url)}" alt="{_escape_attr(alt or title)}" loading="eager" decoding="async" '
        'style="width:100%;border-radius:28px;display:block;object-fit:cover;" />'
        "</figure>"
    )


def _make_inline_block(url: str, title: str) -> str:
    return (
        f"{MARK_INLINE}\n"
        '<figure data-bloggent-normalize-slot="inline" style="margin:30px 0 30px;">'
        f'<img src="{_escape_attr(url)}" alt="{_escape_attr(title + " supporting image")}" '
        'loading="lazy" decoding="async" style="width:100%;border-radius:20px;display:block;object-fit:cover;" />'
        "</figure>"
    )


def _insert_cover(content: str, cover_block: str) -> str:
    seo_match = SEO_META_DIV_RE.search(content)
    if seo_match:
        index = seo_match.end()
        return f"{content[:index]}\n{cover_block}\n{content[index:]}"
    header_match = HEADER_END_RE.search(content)
    if header_match:
        index = header_match.end()
        return f"{content[:index]}\n{cover_block}\n{content[index:]}"
    return f"{cover_block}\n{content}"


def _insert_inline_middle(content: str, inline_block: str) -> str:
    matches = list(P_END_RE.finditer(content))
    if not matches:
        return f"{content}\n{inline_block}"
    index = matches[len(matches) // 2].end()
    return f"{content[:index]}\n{inline_block}\n{content[index:]}"


def _escape_js_single(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _build_related_onerror_chain(primary_url: str) -> str:
    candidates = _candidate_urls(primary_url)
    if not candidates:
        return "this.onerror=null;this.style.display='none';"
    parts: list[str] = []
    for index, candidate in enumerate(candidates):
        key = f"fb{index}"
        parts.append(
            f"if(this.dataset.{key}!=='1'){{this.dataset.{key}='1';this.src='{_escape_js_single(candidate)}';return;}}"
        )
    parts.append("this.onerror=null;this.style.display='none';")
    return "".join(parts)


def _patch_related_section_images(
    related_html: str,
    *,
    client: httpx.Client,
    timeout: float,
    cache: dict[str, dict[str, Any]],
) -> tuple[str, int]:
    patched_count = 0

    def replace_img(match: re.Match[str]) -> str:
        nonlocal patched_count
        tag = match.group(0)
        src_match = re.search(r"\bsrc=['\"]([^'\"]+)['\"]", tag, re.IGNORECASE)
        if not src_match:
            return tag
        raw_src = _safe_str(src_match.group(1))
        if not raw_src:
            return tag
        resolved_src, _probe, _changed = _resolve_healthy_url(client, raw_src, timeout, cache)
        onerror_value = _build_related_onerror_chain(resolved_src)

        patched = ONERROR_RE.sub("", tag)
        patched = re.sub(
            r"\bsrc=['\"][^'\"]+['\"]",
            f"src='{html.escape(resolved_src, quote=True)}'",
            patched,
            count=1,
            flags=re.IGNORECASE,
        )
        if "onerror=" not in patched.lower():
            patched = patched[:-1] + f" onerror=\"{html.escape(onerror_value, quote=True)}\">"
        patched_count += 1
        return patched

    return re.sub(r"<img\b[^>]*>", replace_img, related_html, flags=re.IGNORECASE), patched_count


def _build_generation_prompt(*, category_name: str, title: str, slot: str, summary: str) -> str:
    base = _safe_fallback_image_prompt(category_name, title)
    clean_summary = WHITESPACE_RE.sub(" ", _safe_str(summary))
    if slot == "cover":
        extra = " Create one clear hero image with strong subject focus and no overlaid text."
    else:
        extra = " Create one distinct inline supporting image for mid-article context and no overlaid text."
    if clean_summary:
        extra += f" Context summary: {clean_summary[:320]}."
    return f"{base} {extra}"


def _slug_seed_from_blogger(post_url: str, title: str) -> str:
    parsed = urlparse(_safe_str(post_url))
    token = _safe_str(unquote(parsed.path or "")).strip("/").split("/")[-1]
    token = token.replace(".html", "").strip()
    token = re.sub(r"_[0-9]+$", "", token).strip("-_")
    slug = slugify(token, separator="-") if token else ""
    return slug or slugify(title, separator="-") or "post"


def _slug_seed_from_cloudflare(slug: str, title: str) -> str:
    seeded = slugify(_safe_str(slug), separator="-")
    return seeded or slugify(title, separator="-") or "post"


def _first_paragraph(content: str) -> str:
    plain = WHITESPACE_RE.sub(" ", re.sub(r"<[^>]+>", " ", content or "")).strip()
    return plain[:320]


def _upload_generated_slot(
    db,
    *,
    image_provider,
    target: TargetPost,
    post_slug: str,
    slot: str,
) -> tuple[bool, str, str]:
    prompt = _build_generation_prompt(
        category_name=target.category_hint or target.group_name,
        title=target.title,
        slot=slot,
        summary=target.excerpt or _first_paragraph(target.content),
    )
    suffix = "cover" if slot == "cover" else "inline"
    try:
        image_bytes, _raw = image_provider.generate_image(prompt, f"{post_slug}-normalize-{suffix}")
        public_url = _upload_integration_asset(
            db,
            post_slug=post_slug,
            alt_text=(target.cover_alt or target.title) if slot == "cover" else f"{target.title} supporting image",
            filename=f"{post_slug}-normalize-{suffix}.webp",
            image_bytes=image_bytes,
        )
        return True, public_url, prompt
    except Exception as exc:  # noqa: BLE001
        return False, f"generation_failed:{exc}", prompt


def _fetch_cloudflare_detail(db, post_id: str) -> dict[str, Any]:
    response = _integration_request(
        db,
        method="GET",
        path=f"/api/integrations/posts/{post_id}",
        timeout=90.0,
    )
    payload = _integration_data_or_raise(response)
    return payload if isinstance(payload, dict) else {}


def _collect_targets(db) -> list[TargetPost]:
    targets: list[TargetPost] = []
    active_blogs = (
        db.execute(
            select(Blog)
            .where(Blog.is_active.is_(True), Blog.blogger_blog_id.is_not(None))
            .order_by(Blog.id.asc())
        )
        .scalars()
        .all()
    )

    for blog in active_blogs:
        try:
            sync_blogger_posts_for_blog(db, blog)
        except Exception:
            db.rollback()

    blogger_posts = (
        db.execute(
            select(SyncedBloggerPost)
            .where(SyncedBloggerPost.blog_id.in_([blog.id for blog in active_blogs]))
            .options(selectinload(SyncedBloggerPost.blog))
            .order_by(SyncedBloggerPost.blog_id.asc(), SyncedBloggerPost.id.asc())
        )
        .scalars()
        .all()
    )
    for post in blogger_posts:
        if not _is_live_status(post.status):
            continue
        blog = post.blog
        if blog is None:
            continue
        targets.append(
            TargetPost(
                source="blogger",
                post_id=_safe_str(post.remote_post_id),
                title=_safe_str(post.title) or "Untitled",
                post_url=_safe_str(post.url),
                content=_safe_str(post.content_html),
                cover_alt=_safe_str(post.title) or "cover image",
                category_hint=f"{_safe_str(blog.primary_language)}:{_safe_str(blog.profile_key)}",
                group_name=_safe_str(blog.name),
                slug_seed=_slug_seed_from_blogger(_safe_str(post.url), _safe_str(post.title)),
                blog_id=blog.id,
                labels=list(post.labels or []),
                excerpt=_safe_str(post.excerpt_text),
            )
        )

    cloudflare_rows = _list_integration_posts(db)
    for row in cloudflare_rows:
        if not _is_live_status(row.get("status")):
            continue
        post_id = _safe_str(row.get("id"))
        if not post_id:
            continue
        detail = _fetch_cloudflare_detail(db, post_id)
        if not detail:
            continue
        category = detail.get("category") if isinstance(detail.get("category"), dict) else {}
        category_name = _safe_str(category.get("name")) or _safe_str(category.get("slug")) or "Cloudflare"
        cloudflare_slug = _safe_str(detail.get("slug"))
        targets.append(
            TargetPost(
                source="cloudflare",
                post_id=post_id,
                title=_safe_str(detail.get("title")) or "Untitled",
                post_url=_safe_str(detail.get("publicUrl") or detail.get("url")),
                content=_safe_str(detail.get("content") or detail.get("contentMarkdown") or detail.get("content_markdown")),
                cover_alt=_safe_str(detail.get("coverAlt") or detail.get("coverImageAlt") or detail.get("title")),
                category_hint=category_name,
                group_name="Dongri Archive",
                slug_seed=_slug_seed_from_cloudflare(cloudflare_slug, _safe_str(detail.get("title"))),
                cloudflare_slug=cloudflare_slug,
                excerpt=_safe_str(detail.get("excerpt")),
            )
        )

    targets.sort(key=lambda item: (item.source, item.post_url, item.post_id))
    return targets


def _update_blogger_post(
    db,
    *,
    target: TargetPost,
    updated_content: str,
) -> tuple[bool, str]:
    if target.blog_id is None:
        return False, "blog_id_missing"
    blog = db.get(Blog, target.blog_id)
    if blog is None:
        return False, "blog_not_found"
    provider = get_blogger_provider(db, blog)
    try:
        provider.update_post(
            post_id=target.post_id,
            title=target.title,
            content=updated_content,
            labels=list(target.labels or []),
            meta_description=target.excerpt[:300],
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"blogger_update_failed:{exc}"

    post = db.execute(
        select(SyncedBloggerPost).where(
            SyncedBloggerPost.blog_id == blog.id,
            SyncedBloggerPost.remote_post_id == target.post_id,
        )
    ).scalar_one_or_none()
    if post is not None:
        post.content_html = updated_content
        post.synced_at = datetime.now(timezone.utc)
        db.add(post)
    db.commit()
    return True, "ok"


def _update_cloudflare_post(
    db,
    *,
    target: TargetPost,
    updated_content: str,
    cover_url: str,
) -> tuple[bool, str]:
    payload = {
        "content": updated_content,
        "coverImage": cover_url,
        "coverAlt": target.cover_alt or target.title,
    }
    try:
        response = _integration_request(
            db,
            method="PUT",
            path=f"/api/integrations/posts/{target.post_id}",
            json_payload=payload,
            timeout=120.0,
        )
        _integration_data_or_raise(response)
    except Exception as exc:  # noqa: BLE001
        return False, f"cloudflare_update_failed:{exc}"
    return True, "ok"


def _new_report(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "generated_at": _utc_now_iso(),
        "mode": args.mode,
        "source": args.source,
        "generation_policy": _safe_str(getattr(args, "generation_policy", "existing-only")) or "existing-only",
        "model": args.model,
        "canary_count": int(args.canary_count),
        "summary": {
            "targets": 0,
            "needs_update": 0,
            "processed": 0,
            "updated": 0,
            "failed": 0,
            "generated_images": 0,
            "kept_existing": 0,
            "related_patched_posts": 0,
            "class_0": 0,
            "class_1": 0,
            "class_2": 0,
            "class_3_plus": 0,
            "duplicate_slots": 0,
            "broken_related_urls": 0,
            "manual_review_required": 0,
        },
        "by_host": {},
        "items": [],
    }


def _ensure_host_bucket(report: dict[str, Any], host_key: str) -> dict[str, Any]:
    by_host = report.setdefault("by_host", {})
    if host_key not in by_host:
        by_host[host_key] = {
            "targets": 0,
            "needs_update": 0,
            "updated": 0,
            "failed": 0,
            "class_0": 0,
            "class_1": 0,
            "class_2": 0,
            "class_3_plus": 0,
            "duplicate_slots": 0,
            "related_patched_posts": 0,
        }
    return by_host[host_key]


def _host_key(target: TargetPost) -> str:
    host = urlparse(_safe_str(target.post_url)).hostname or "(unknown)"
    return f"{target.source}::{host}"


def _normalize_post_content(
    *,
    content: str,
    cover_url: str,
    inline_url: str,
    title: str,
    cover_alt: str,
    client: httpx.Client,
    timeout: float,
    cache: dict[str, dict[str, Any]],
) -> tuple[str, int, int]:
    protected, related_sections = _protect_related_sections(content or "")
    stripped = _strip_existing_body_images(protected)
    with_cover = _insert_cover(stripped, _make_cover_block(cover_url, title, cover_alt))
    with_inline = _insert_inline_middle(with_cover, _make_inline_block(inline_url, title))

    patched_sections: dict[str, str] = {}
    related_patched_count = 0
    related_broken_count = 0
    for token, section in related_sections.items():
        raw_related_urls = _extract_image_urls(section)
        for raw_url in raw_related_urls:
            _resolved_url, probe, _changed = _resolve_healthy_url(client, raw_url, timeout, cache)
            if not probe.get("ok"):
                related_broken_count += 1
        patched_section, patched_count = _patch_related_section_images(
            section,
            client=client,
            timeout=timeout,
            cache=cache,
        )
        if patched_count > 0:
            related_patched_count += 1
        patched_sections[token] = patched_section

    restored = _restore_related_sections(with_inline, patched_sections)
    return _collapse_blank_lines(restored), related_patched_count, related_broken_count


def main() -> int:
    args = parse_args()
    apply_mode = args.mode in {"canary", "full"}
    generation_policy = _safe_str(getattr(args, "generation_policy", "existing-only")) or "existing-only"
    report = _new_report(args)

    with SessionLocal() as db:
        targets = _collect_targets(db)
        if args.source != "all":
            targets = [target for target in targets if target.source == args.source]
        report["summary"]["targets"] = len(targets)
        image_provider = get_image_provider(db, model_override=args.model) if apply_mode and generation_policy == "generate" else None
        touched_blog_ids: set[int] = set()
        touched_cloudflare = False

        url_probe_cache: dict[str, dict[str, Any]] = {}
        with httpx.Client(timeout=max(float(args.timeout), 5.0), follow_redirects=True) as client:
            analyzed: list[tuple[TargetPost, dict[str, Any], bool]] = []

            for target in targets:
                host_bucket = _ensure_host_bucket(report, _host_key(target))
                host_bucket["targets"] += 1

                body_tag_urls, body_candidate_urls = _extract_body_image_inventory(target.content)
                raw_count = len(body_tag_urls)
                raw_unique = _dedupe_normalized(body_tag_urls)
                candidate_unique = _dedupe_normalized(body_candidate_urls)
                ordered_candidates = _dedupe_normalized([*raw_unique, *candidate_unique])

                resolved_unique: list[str] = []
                seen_resolved: set[str] = set()
                for raw_url in ordered_candidates:
                    resolved_url, probe, _changed = _resolve_healthy_url(client, raw_url, float(args.timeout), url_probe_cache)
                    if probe.get("ok") and resolved_url not in seen_resolved:
                        seen_resolved.add(resolved_url)
                        resolved_unique.append(resolved_url)

                cls = raw_count
                if cls == 0:
                    report["summary"]["class_0"] += 1
                    host_bucket["class_0"] += 1
                elif cls == 1:
                    report["summary"]["class_1"] += 1
                    host_bucket["class_1"] += 1
                elif cls == 2:
                    report["summary"]["class_2"] += 1
                    host_bucket["class_2"] += 1
                else:
                    report["summary"]["class_3_plus"] += 1
                    host_bucket["class_3_plus"] += 1

                duplicate_slots = raw_count > len(raw_unique)
                if duplicate_slots:
                    report["summary"]["duplicate_slots"] += 1
                    host_bucket["duplicate_slots"] += 1

                reasons: list[str] = []
                needs_update = False
                healthy_count = len(resolved_unique)
                if cls == 0 or healthy_count == 0:
                    reasons.append("missing_main")
                    needs_update = True
                if cls <= 1 or healthy_count <= 1:
                    reasons.append("missing_inline")
                    needs_update = True
                elif cls >= 3:
                    reasons.append("extra_slots")
                    needs_update = True
                if duplicate_slots:
                    reasons.append("duplicate_slots")
                    needs_update = True
                if raw_count > 2:
                    reasons.append("raw_image_tags_over_2")
                    needs_update = True
                if cls >= 1 and healthy_count < min(2, cls):
                    reasons.append("broken_slots")
                    needs_update = True

                row = {
                    "source": target.source,
                    "host": _host_key(target),
                    "post_id": target.post_id,
                    "post_url": target.post_url,
                    "title": target.title,
                    "raw_image_count": raw_count,
                    "raw_unique_count": len(raw_unique),
                    "candidate_unique_count": len(ordered_candidates),
                    "resolved_unique_count": len(resolved_unique),
                    "resolved_unique_urls": resolved_unique[:4],
                    "duplicate_slots": duplicate_slots,
                    "reasons": sorted(set(reasons)),
                    "status": "audit_update" if needs_update else "audit_keep",
                }
                if needs_update:
                    report["summary"]["needs_update"] += 1
                    host_bucket["needs_update"] += 1
                analyzed.append((target, row, needs_update))

            selected_keys: set[tuple[str, str]] = set()
            if apply_mode:
                update_candidates = [item for item in analyzed if item[2]]
                if args.mode == "canary":
                    update_candidates = update_candidates[: max(int(args.canary_count or 1), 1)]
                selected_keys = {(item[0].source, item[0].post_id) for item in update_candidates}

            for target, row, needs_update in analyzed:
                report["summary"]["processed"] += 1
                if not apply_mode:
                    report["items"].append(row)
                    continue
                if not needs_update:
                    row["status"] = "kept"
                    report["summary"]["kept_existing"] += 1
                    report["items"].append(row)
                    continue
                if (target.source, target.post_id) not in selected_keys:
                    row["status"] = "skipped_canary"
                    report["items"].append(row)
                    continue

                body_tag_urls, body_candidate_urls = _extract_body_image_inventory(target.content)
                unique_urls = _dedupe_normalized([*body_tag_urls, *body_candidate_urls])

                healthy_urls: list[str] = []
                seen_healthy: set[str] = set()
                for candidate in unique_urls:
                    resolved, probe, _changed = _resolve_healthy_url(client, candidate, float(args.timeout), url_probe_cache)
                    if probe.get("ok") and resolved not in seen_healthy:
                        seen_healthy.add(resolved)
                        healthy_urls.append(resolved)

                cover_url = healthy_urls[0] if healthy_urls else ""
                inline_url = healthy_urls[1] if len(healthy_urls) >= 2 else ""
                upload_slug = _safe_str(target.cloudflare_slug) or target.slug_seed or slugify(target.title, separator="-")
                generated_prompts: dict[str, str] = {}

                if generation_policy == "existing-only" and (not cover_url or not inline_url or inline_url == cover_url):
                    row["status"] = "manual_review_required"
                    row["reason"] = "insufficient_existing_images"
                    row["normalized_cover"] = cover_url
                    row["normalized_inline"] = inline_url
                    report["summary"]["manual_review_required"] += 1
                    report["items"].append(row)
                    continue

                if not cover_url:
                    ok, value, prompt = _upload_generated_slot(
                        db,
                        image_provider=image_provider,
                        target=target,
                        post_slug=upload_slug,
                        slot="cover",
                    )
                    generated_prompts["cover"] = prompt
                    if not ok:
                        row["status"] = "failed"
                        row["reason"] = value
                        report["summary"]["failed"] += 1
                        _ensure_host_bucket(report, _host_key(target))["failed"] += 1
                        report["items"].append(row)
                        continue
                    cover_url = value
                    report["summary"]["generated_images"] += 1

                if not inline_url or inline_url == cover_url:
                    ok, value, prompt = _upload_generated_slot(
                        db,
                        image_provider=image_provider,
                        target=target,
                        post_slug=upload_slug,
                        slot="inline",
                    )
                    generated_prompts["inline"] = prompt
                    if not ok:
                        row["status"] = "failed"
                        row["reason"] = value
                        report["summary"]["failed"] += 1
                        _ensure_host_bucket(report, _host_key(target))["failed"] += 1
                        report["items"].append(row)
                        continue
                    inline_url = value
                    report["summary"]["generated_images"] += 1

                cover_url, _cover_probe, _ = _resolve_healthy_url(client, cover_url, float(args.timeout), url_probe_cache)
                inline_url, _inline_probe, _ = _resolve_healthy_url(client, inline_url, float(args.timeout), url_probe_cache)

                updated_content, related_patched_count, related_broken_count = _normalize_post_content(
                    content=target.content,
                    cover_url=cover_url,
                    inline_url=inline_url,
                    title=target.title,
                    cover_alt=target.cover_alt or target.title,
                    client=client,
                    timeout=float(args.timeout),
                    cache=url_probe_cache,
                )
                if related_patched_count > 0:
                    report["summary"]["related_patched_posts"] += 1
                    _ensure_host_bucket(report, _host_key(target))["related_patched_posts"] += 1
                if related_broken_count > 0:
                    report["summary"]["broken_related_urls"] += related_broken_count
                    row["reasons"] = sorted(set([*(row.get("reasons") or []), "related_thumb_fail"]))

                if target.source == "blogger":
                    ok, reason = _update_blogger_post(db, target=target, updated_content=updated_content)
                    if ok and target.blog_id is not None:
                        touched_blog_ids.add(target.blog_id)
                else:
                    ok, reason = _update_cloudflare_post(
                        db,
                        target=target,
                        updated_content=updated_content,
                        cover_url=cover_url,
                    )
                    if ok:
                        touched_cloudflare = True

                if ok:
                    row["status"] = "updated"
                    row["normalized_cover"] = cover_url
                    row["normalized_inline"] = inline_url
                    row["generated_prompts"] = generated_prompts
                    report["summary"]["updated"] += 1
                    _ensure_host_bucket(report, _host_key(target))["updated"] += 1
                else:
                    row["status"] = "failed"
                    row["reason"] = reason
                    report["summary"]["failed"] += 1
                    _ensure_host_bucket(report, _host_key(target))["failed"] += 1
                report["items"].append(row)

        if apply_mode:
            for blog_id in sorted(touched_blog_ids):
                blog = db.get(Blog, blog_id)
                if blog is None:
                    continue
                try:
                    sync_blogger_posts_for_blog(db, blog)
                except Exception as exc:  # noqa: BLE001
                    report["summary"]["failed"] += 1
                    report["items"].append(
                        {
                            "source": "blogger",
                            "post_id": "",
                            "status": "failed",
                            "reason": f"sync_blogger_failed:{blog_id}:{exc}",
                        }
                    )

            if touched_cloudflare:
                try:
                    sync_cloudflare_posts(db, include_non_published=False)
                except Exception as exc:  # noqa: BLE001
                    report["summary"]["failed"] += 1
                    report["items"].append(
                        {
                            "source": "cloudflare",
                            "post_id": "",
                            "status": "failed",
                            "reason": f"sync_cloudflare_failed:{exc}",
                        }
                    )

    report_path = Path(args.report_path) if _safe_str(args.report_path) else (
        REPO_ROOT / "storage" / "reports" / f"normalize-live-images-two-slots-{_timestamp()}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "report_path": str(report_path),
                "summary": report["summary"],
                "mode": args.mode,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
