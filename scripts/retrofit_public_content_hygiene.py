from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
DEFAULT_DATABASE_URL = "postgresql+psycopg2://bloggent:bloggent@localhost:15432/bloggent"
TRACE_TOKENS = (
    "quick brief",
    "core focus",
    "key entities",
    "기준 시각",
    "internal archive",
    "같은 주제로 다시 정리했다",
    "summary section",
    "intro keyword",
    "heading structure",
)
FAQ_TITLE_BY_LOCALE = {
    "en": "Frequently Asked Questions",
    "es": "Preguntas frecuentes",
    "ja": "よくある質問（FAQ）",
}
RELATED_TITLE_BY_LOCALE = {
    "en": "Related Korea Travel Reads",
    "es": "Más lecturas sobre Corea",
    "ja": "あわせて読みたい韓国ローカル案内",
}


def _bootstrap_local_runtime_env() -> None:
    env_path = REPO_ROOT / "env" / "runtime.settings.env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        existing = os.environ.get(key)
        if not key or (existing is not None and existing.strip()):
            continue
        os.environ[key] = value.strip()


_bootstrap_local_runtime_env()
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.models.entities import Blog, SyncedBloggerPost, SyncedCloudflarePost  # noqa: E402
from app.services.ops.analytics_service import rebuild_blog_month_rollup  # noqa: E402
from app.services.blogger.blogger_sync_service import sync_blogger_posts_for_blog  # noqa: E402
from app.services.cloudflare.cloudflare_channel_service import (  # noqa: E402
    _prepare_markdown_body,
    _sanitize_cloudflare_public_body,
)
from app.services.content.faq_hygiene import (  # noqa: E402
    strip_generic_faq_leak_html_with_stats,
)
from app.services.cloudflare.cloudflare_sync_service import sync_cloudflare_posts  # noqa: E402
from app.services.providers.factory import get_blogger_provider  # noqa: E402
from app.services.integrations.settings_service import get_settings_map  # noqa: E402


def _database_url() -> str:
    return str(os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL).strip()


def _collapse_html_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _remove_trace_preface(html_text: str) -> str:
    text = str(html_text or "")
    article_index = text.lower().find("<article")
    if article_index > 0:
        prefix = text[:article_index]
        lowered_prefix = prefix.casefold()
        if any(token in lowered_prefix for token in TRACE_TOKENS):
            text = text[article_index:]
    return text


def _remove_trace_blocks(html_text: str) -> str:
    cleaned = str(html_text or "")
    block_patterns = (
        r"(?is)<p\b[^>]*>\s*<strong>\s*quick brief\..*?</p>",
        r"(?is)<p\b[^>]*>\s*<strong>\s*core focus\..*?</p>",
        r"(?is)<p\b[^>]*>\s*<strong>\s*key entities:.*?</p>",
        r"(?is)<p\b[^>]*>.*?(intro keyword|heading structure|internal archive|summary section|같은 주제로 다시 정리했다).*?</p>",
        r"(?is)<h[23]\b[^>]*>[^<]*related links\s*\|\s*internal archive[^<]*</h[23]>\s*(?:<div\b[^>]*>.*?</div>|<ul\b[^>]*>.*?</ul>)?",
    )
    for pattern in block_patterns:
        cleaned = re.sub(pattern, "", cleaned)
    cleaned = re.sub(r"(?is)<!--BLOGGENT_LANGUAGE_SWITCH_START-->.*?<!--BLOGGENT_LANGUAGE_SWITCH_END-->", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _localize_heading(html_text: str, english_title: str, localized_title: str) -> str:
    pattern = re.compile(re.escape(english_title), re.IGNORECASE)
    return pattern.sub(localized_title, str(html_text or ""))


def _localize_generic_faq_copy(html_text: str, *, locale: str, title: str) -> str:
    text = str(html_text or "")
    safe_title = str(title or "").strip() or "이 글"
    replacements: list[tuple[str, str]] = []
    if locale == "es":
        replacements = [
            (rf"What should readers know about {re.escape(safe_title)}\?", f"¿Qué conviene saber antes de leer {safe_title}?"),
            (
                rf"This section summarizes the essential context, expectations, and constraints around {re.escape(safe_title)} so readers can act with confidence\.",
                f"Este bloque resume el contexto esencial de {safe_title} para que puedas planificar la visita o la lectura con más seguridad.",
            ),
            (rf"How can readers apply {re.escape(safe_title)} effectively\?", f"¿Cómo aprovechar mejor {safe_title}?"),
            (
                rf"Use a short checklist and the key steps in this article to plan, evaluate, and execute {re.escape(safe_title)} without missing critical details\.",
                f"Usa la ruta, los pasos clave y la lista breve de este artículo para aplicar {safe_title} sin pasar por alto los detalles importantes.",
            ),
        ]
    if locale == "ja":
        replacements = [
            (rf"What should readers know about {re.escape(safe_title)}\?", f"{safe_title}を読む前に知っておきたいことは？"),
            (
                rf"This section summarizes the essential context, expectations, and constraints around {re.escape(safe_title)} so readers can act with confidence\.",
                f"このブロックでは、{safe_title}を無理なく読み進めたり現地で役立てたりするための前提を短く整理します。",
            ),
            (rf"How can readers apply {re.escape(safe_title)} effectively\?", f"{safe_title}をうまく活用するコツは？"),
            (
                rf"Use a short checklist and the key steps in this article to plan, evaluate, and execute {re.escape(safe_title)} without missing critical details\.",
                f"この記事の要点と短いチェック項目を使って、{safe_title}を実際の行動につなげやすくしてください。",
            ),
        ]
    if locale == "en":
        return text
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def _empty_faq_cleanup_stats() -> dict[str, int]:
    return {
        "faq_static_block_removed_count": 0,
        "question_line_removed_count": 0,
        "details_preserved_count": 0,
    }


def _retrofit_blogger_html(html_text: str, *, locale: str, title: str) -> tuple[str, dict[str, int]]:
    cleaned = _remove_trace_preface(html_text)
    cleaned = _remove_trace_blocks(cleaned)
    cleaned, faq_cleanup_stats = strip_generic_faq_leak_html_with_stats(cleaned)
    localized_faq_title = FAQ_TITLE_BY_LOCALE.get(locale, FAQ_TITLE_BY_LOCALE["en"])
    localized_related_title = RELATED_TITLE_BY_LOCALE.get(locale, RELATED_TITLE_BY_LOCALE["en"])
    cleaned = _localize_heading(cleaned, "Frequently Asked Questions", localized_faq_title)
    cleaned = _localize_heading(cleaned, "Related Korea Travel Reads", localized_related_title)
    cleaned = re.sub(r">\s+<", "><", cleaned)
    return cleaned.strip(), faq_cleanup_stats


def _cloudflare_update_payload(row: SyncedCloudflarePost, detail: dict[str, Any], cleaned_body: str) -> dict[str, Any]:
    title = str(detail.get("title") or row.title or "Untitled").strip() or "Untitled"
    excerpt = str(detail.get("excerpt") or row.excerpt_text or "").strip()
    seo_description = str(detail.get("seoDescription") or excerpt or "").strip()
    status = str(detail.get("status") or row.status or "published").strip() or "published"
    category = detail.get("category") if isinstance(detail.get("category"), dict) else {}
    tag_names: list[str] = []
    for item in detail.get("tags") or []:
        if isinstance(item, dict):
            value = str(item.get("name") or "").strip()
        else:
            value = str(item or "").strip()
        if value and value not in tag_names:
            tag_names.append(value)

    payload: dict[str, Any] = {
        "title": title,
        "content": _prepare_markdown_body(title, cleaned_body),
        "excerpt": excerpt,
        "seoTitle": str(detail.get("seoTitle") or title).strip() or title,
        "seoDescription": seo_description,
        "tagNames": tag_names[:20],
        "status": status,
    }
    category_id = str(category.get("id") or "").strip()
    category_slug = str(category.get("slug") or row.canonical_category_slug or row.category_slug or "").strip()
    if category_id:
        payload["categoryId"] = category_id
    elif category_slug:
        payload["categorySlug"] = category_slug
    cover_image = str(detail.get("coverImage") or "").strip()
    cover_alt = str(detail.get("coverAlt") or "").strip()
    if cover_image:
        payload["coverImage"] = cover_image
    if cover_alt:
        payload["coverAlt"] = cover_alt
    if isinstance(row.render_metadata, dict) and row.render_metadata:
        payload["metadata"] = row.render_metadata
    return payload


def _retrofit_cloudflare(db: Session, *, execute: bool, limit: int | None) -> dict[str, Any]:
    values = get_settings_map(db)
    base_url = str(values.get("cloudflare_blog_api_base_url") or "").strip().rstrip("/")
    token = str(values.get("cloudflare_blog_m2m_token") or "").strip()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    rows = [
        row
        for row in db.execute(select(SyncedCloudflarePost).order_by(SyncedCloudflarePost.id.asc())).scalars().all()
        if str(row.status or "").strip().lower() in {"published", "live"} and str(row.remote_post_id or "").strip()
    ]
    if isinstance(limit, int) and limit > 0:
        rows = rows[:limit]

    items: list[dict[str, Any]] = []
    updated = 0
    for row in rows:
        remote_id = str(row.remote_post_id or "").strip()
        response = httpx.get(f"{base_url}/api/integrations/posts/{remote_id}", headers=headers, timeout=20.0)
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else payload
        detail = data if isinstance(data, dict) else {}
        original_body = str(detail.get("content") or "").strip()
        cleaned_body = _sanitize_cloudflare_public_body(
            original_body,
            category_slug=str(row.canonical_category_slug or row.category_slug or "").strip(),
            title=str(detail.get("title") or row.title or "").strip(),
        )
        changed = _collapse_html_whitespace(cleaned_body) != _collapse_html_whitespace(original_body)
        item = {
            "remote_id": remote_id,
            "title": row.title,
            "url": row.url,
            "category": str(row.canonical_category_slug or row.category_slug or "").strip(),
            "changed": changed,
            "action": "skip",
        }
        if changed and execute:
            update_payload = _cloudflare_update_payload(row, detail, cleaned_body)
            update_response = httpx.put(
                f"{base_url}/api/integrations/posts/{remote_id}",
                headers=headers,
                json=update_payload,
                timeout=60.0,
            )
            update_response.raise_for_status()
            updated += 1
            item["action"] = "updated"
        elif changed:
            item["action"] = "dry_run"
        items.append(item)

    sync_after = None
    if execute and updated > 0:
        sync_after = sync_cloudflare_posts(db, include_non_published=False)

    return {
        "total_considered": len(rows),
        "updated_count": updated,
        "items": items[:50],
        "sync_after": sync_after,
    }


def _retrofit_blogger(
    db: Session,
    *,
    execute: bool,
    limit: int | None,
    month: str | None,
    blog_language: str | None,
) -> dict[str, Any]:
    blogs = db.execute(select(Blog).order_by(Blog.id.asc())).scalars().all()
    blog_map = {blog.id: blog for blog in blogs}
    rows = db.execute(select(SyncedBloggerPost).order_by(SyncedBloggerPost.id.asc())).scalars().all()
    candidates: list[SyncedBloggerPost] = []
    for row in rows:
        blog = blog_map.get(row.blog_id)
        if blog is None or not str(blog.blogger_blog_id or "").strip():
            continue
        if blog_language:
            language = str(blog.primary_language or "").strip().lower()
            if not language.startswith(blog_language):
                continue
        if str(row.status or "").strip().lower() not in {"published", "live"}:
            continue
        candidates.append(row)
    if isinstance(limit, int) and limit > 0:
        candidates = candidates[:limit]

    touched_blog_ids: set[int] = set()
    touched_months: defaultdict[int, set[str]] = defaultdict(set)
    items: list[dict[str, Any]] = []
    updated = 0
    provider_cache: dict[int, Any] = {}
    faq_cleanup_totals = _empty_faq_cleanup_stats()

    for row in candidates:
        blog = blog_map[row.blog_id]
        locale = str(blog.primary_language or "en").strip().lower()
        original_html = str(row.content_html or "").strip()
        cleaned_html, faq_cleanup_stats = _retrofit_blogger_html(
            original_html,
            locale=locale,
            title=str(row.title or "").strip(),
        )
        for key in faq_cleanup_totals:
            faq_cleanup_totals[key] += int(faq_cleanup_stats.get(key, 0))
        changed = _collapse_html_whitespace(cleaned_html) != _collapse_html_whitespace(original_html)
        item = {
            "blog_id": blog.id,
            "blog_name": blog.name,
            "remote_post_id": row.remote_post_id,
            "title": row.title,
            "url": row.url,
            "changed": changed,
            "action": "skip",
            "faq_cleanup_stats": faq_cleanup_stats,
        }
        if changed and execute:
            provider = provider_cache.get(blog.id)
            if provider is None:
                provider = get_blogger_provider(db, blog)
                provider_cache[blog.id] = provider
            provider.update_post(
                post_id=str(row.remote_post_id or "").strip(),
                title=str(row.title or "").strip() or "Untitled",
                content=cleaned_html,
                labels=list(row.labels or []),
                meta_description=str(row.excerpt_text or "").strip(),
            )
            updated += 1
            touched_blog_ids.add(blog.id)
            if row.published_at is not None:
                touched_months[blog.id].add(row.published_at.strftime("%Y-%m"))
            elif month:
                touched_months[blog.id].add(month)
            item["action"] = "updated"
        elif changed:
            item["action"] = "dry_run"
        items.append(item)

    sync_after: list[dict[str, Any]] = []
    if execute and updated > 0:
        for blog_id in sorted(touched_blog_ids):
            blog = blog_map[blog_id]
            sync_result = sync_blogger_posts_for_blog(db, blog)
            sync_after.append({"blog_id": blog_id, "blog_name": blog.name, "sync": sync_result})
            for touched_month in sorted(touched_months.get(blog_id) or []):
                rebuild_blog_month_rollup(db, blog_id=blog_id, month=touched_month, commit=False)
        db.commit()

    return {
        "total_considered": len(candidates),
        "updated_count": updated,
        "faq_static_block_removed_count": faq_cleanup_totals["faq_static_block_removed_count"],
        "question_line_removed_count": faq_cleanup_totals["question_line_removed_count"],
        "details_preserved_count": faq_cleanup_totals["details_preserved_count"],
        "items": items[:50],
        "sync_after": sync_after,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Retrofit public content hygiene for existing Blogger and Cloudflare posts.")
    parser.add_argument("--channel", choices=("all", "blogger", "cloudflare"), default="all")
    parser.add_argument("--database-url", default="", help="Optional SQLAlchemy database URL override.")
    parser.add_argument("--execute", action="store_true", help="Apply updates instead of dry-run only.")
    parser.add_argument("--limit", type=int, default=0, help="Optional limit per channel.")
    parser.add_argument("--month", default=datetime.now().strftime("%Y-%m"), help="Month used for Blogger rollup rebuild.")
    parser.add_argument(
        "--blog-language",
        default="",
        help="Optional Blogger language prefix filter (example: en, es, ja).",
    )
    args = parser.parse_args()

    engine = create_engine(str(args.database_url or _database_url()).strip(), future=True)
    limit = int(args.limit) if int(args.limit) > 0 else None
    blog_language = str(args.blog_language or "").strip().lower() or None
    payload: dict[str, Any] = {
        "channel": args.channel,
        "execute": bool(args.execute),
        "month": args.month,
        "blog_language": blog_language or "",
    }

    with Session(engine) as db:
        if args.channel in {"all", "cloudflare"}:
            payload["cloudflare"] = _retrofit_cloudflare(db, execute=bool(args.execute), limit=limit)
        if args.channel in {"all", "blogger"}:
            payload["blogger"] = _retrofit_blogger(
                db,
                execute=bool(args.execute),
                limit=limit,
                month=str(args.month or "").strip() or None,
                blog_language=blog_language,
            )

    rendered = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    try:
        print(rendered)
    except UnicodeEncodeError:
        encoding = str(getattr(sys.stdout, "encoding", "") or "utf-8")
        safe_text = rendered.encode(encoding, errors="backslashreplace").decode(encoding, errors="ignore")
        print(safe_text)


if __name__ == "__main__":
    main()
