from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape, unescape
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx
from slugify import slugify
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

REPO_ROOT = Path(__file__).resolve().parents[3]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get(
        "BLOGGENT_DATABASE_URL",
        "postgresql://bloggent:bloggent@localhost:15432/bloggent",
    )
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from package_common import CloudflareIntegrationClient, SessionLocal  # noqa: E402
from app.models.entities import (  # noqa: E402
    Article,
    Blog,
    BloggerPost,
    Image,
    Job,
    JobStatus,
    PostStatus,
    PublishMode,
    SyncedBloggerPost,
    SyncedCloudflarePost,
    Topic,
)
from app.services.blogger.blogger_sync_service import sync_blogger_posts_for_blog  # noqa: E402
from app.services.cloudflare.cloudflare_sync_service import sync_cloudflare_posts  # noqa: E402
from app.services.content.article_service import build_r2_asset_object_key  # noqa: E402
from app.services.integrations.settings_service import get_settings_map  # noqa: E402
from app.services.integrations.storage_service import save_public_binary, upload_binary_to_cloudflare_r2  # noqa: E402
from app.services.platform.publishing_service import upsert_article_blogger_post  # noqa: E402
from app.services.providers.factory import get_article_provider, get_blogger_provider, get_image_provider  # noqa: E402


BLOGGER_BLOG_ID = 35
BLOGGER_PROFILE_KEY = "world_mystery"
CLOUDFLARE_CATEGORY_LEAF = "miseuteria-seutori"
CLOUDFLARE_CATEGORY_LABEL = "\ubbf8\uc2a4\ud14c\ub9ac\uc544 \uc2a4\ud1a0\ub9ac"
CLOUDFLARE_CATEGORY_ID_FALLBACK = "cat-world-mysteria-story"
PATTERN_VERSION = 4
ALLOWED_PATTERNS = {
    "case-timeline",
    "evidence-breakdown",
    "legend-context",
    "scene-investigation",
    "scp-dossier",
}
RUNTIME_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\the-midnight-archives")
BLOGGER_PROMPT_ROOT = REPO_ROOT / "prompts" / "channels" / "blogger" / "the-midnight-archives"
CLOUDFLARE_PROMPT_ROOT = (
    REPO_ROOT
    / "prompts"
    / "channels"
    / "cloudflare"
    / "dongri-archive"
    / "\uc138\uc0c1\uc758 \uae30\ub85d"
    / CLOUDFLARE_CATEGORY_LEAF
)

TAG_RE = re.compile(r"<[^>]+>")
H1_RE = re.compile(r"<h1\b", re.IGNORECASE)
H2_RE = re.compile(r"<h2\b[^>]*>(.*?)</h2>", re.IGNORECASE | re.DOTALL)
IMG_RE = re.compile(r"""<img\b[^>]*\bsrc=["']([^"']+)["']""", re.IGNORECASE)
MYSTERY_WEBP_URL_RE = re.compile(r"https://api\.dongriarchive\.com/[^\s\"'<>)]*?\.webp", re.IGNORECASE)
MD_EXPOSED_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s+|\*\*[^*\n]+?\*\*")
RAW_HTML_TEXT_RE = re.compile(r"&lt;/?(?:div|section|article|h[1-6]|p|img|figure)\b", re.IGNORECASE)
SPACE_RE = re.compile(r"\s+")

SAMPLE_TOPICS = [
    {
        "keyword": "The Green Children of Woolpit medieval record contradictions",
        "reason": "Strong mystery search intent with folklore, records, and historical uncertainty.",
        "trend_score": 72,
    },
    {
        "keyword": "Ourang Medan ghost ship distress call evidence review",
        "reason": "High-CTR maritime mystery with evidence gaps and disputed source trails.",
        "trend_score": 70,
    },
]


@dataclass(frozen=True)
class GeneratedAsset:
    slot: str
    prompt: str
    bytes_value: bytes
    blogger_url: str
    blogger_object_key: str
    cloudflare_url: str
    cloudflare_object_key: str
    local_path: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ImagePromptSpec:
    key: str
    keyword: str
    blogger_slug: str
    cloudflare_slug: str
    hero_prompt: str
    closing_prompt: str
    semantic_keywords: tuple[str, ...]


IMAGE_PROMPT_SPECS: tuple[ImagePromptSpec, ...] = (
    ImagePromptSpec(
        key="taos-hum",
        keyword="Taos Hum low-frequency sound mystery",
        blogger_slug="why-taos-hum-still-divides-witnesses",
        cloudflare_slug="taos-hum-acoustic-studies-local-testimony-record",
        hero_prompt=(
            "Realistic documentary-style 3x4 panel grid collage about the Taos Hum mystery in New Mexico. "
            "Show adobe houses at night, quiet desert streets, a sleepless resident listening indoors, acoustic "
            "engineers with low-frequency meters, waveform charts, power lines, mountain horizon, and investigation "
            "notes. Visible white gutters, clean grid layout, muted archival colors, cinematic realism, no text, "
            "no logo, no watermark, 1024x1024."
        ),
        closing_prompt=(
            "Realistic visual evidence-board summary of the Taos Hum investigation. Include a New Mexico desert map, "
            "low-frequency waveform diagram, witness testimony cards, acoustic measurement devices, night street "
            "ambience, and unresolved source markers. Balanced documentary archive composition, realistic materials, "
            "muted gray-blue desert palette, no readable text, no logo, no watermark, 1024x1024."
        ),
        semantic_keywords=(
            "taos hum",
            "new mexico",
            "adobe",
            "desert",
            "low-frequency",
            "waveform",
            "acoustic",
            "power lines",
            "mountain horizon",
            "witness",
        ),
    ),
    ImagePromptSpec(
        key="amber-room",
        keyword="Amber Room disappearance looting records",
        blogger_slug="the-amber-room-trail-what-looting",
        cloudflare_slug="amber-room-nazi-loot-records-unclosed-search",
        hero_prompt=(
            "Realistic documentary-style 3x4 panel grid collage about the Amber Room disappearance. Show an "
            "amber-gold palace chamber, wartime evacuation crates, Nazi-era looting records, railway transport "
            "route, Königsberg ruins, restoration sketches, archive folders, and missing artifact fragments. Visible "
            "white gutters, clean grid layout, muted gold-brown historical colors, cinematic realism, no text, "
            "no logo, no watermark, 1024x1024."
        ),
        closing_prompt=(
            "Realistic visual evidence-board summary of the Amber Room trail. Include a Königsberg route map, sealed "
            "wooden crates, amber wall fragments, wartime archive files, restoration blueprint sheets, palace interior "
            "clues, and unresolved search markers. Balanced historical investigation composition, warm amber lighting, "
            "realistic paper and wood textures, no readable text, no logo, no watermark, 1024x1024."
        ),
        semantic_keywords=(
            "amber room",
            "amber-gold",
            "palace",
            "wartime",
            "crates",
            "nazi",
            "looting",
            "railway",
            "königsberg",
            "restoration",
            "fragments",
        ),
    ),
)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _strip_tags(value: str) -> str:
    return SPACE_RE.sub(" ", unescape(TAG_RE.sub(" ", value or ""))).strip()


def _plain_len(value: str) -> int:
    return len(SPACE_RE.sub("", _strip_tags(value)))


def _body_h1_count(value: str) -> int:
    return len(H1_RE.findall(value or ""))


def _image_count(value: str) -> int:
    return len(IMG_RE.findall(value or ""))


def _extract_mystery_webp_urls(value: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for url in [*IMG_RE.findall(value or ""), *MYSTERY_WEBP_URL_RE.findall(value or "")]:
        normalized = str(url or "").strip()
        if not normalized:
            continue
        if not normalized.lower().startswith("https://api.dongriarchive.com/"):
            continue
        if not normalized.lower().endswith(".webp"):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        urls.append(normalized)
    return urls


def _prompt_spec_by_key(key: str) -> ImagePromptSpec:
    normalized = str(key or "").strip().lower()
    for spec in IMAGE_PROMPT_SPECS:
        if spec.key == normalized:
            return spec
    raise ValueError(f"unknown_image_prompt_spec:{key}")


def _prompt_spec_for_text(value: str) -> ImagePromptSpec | None:
    lowered = str(value or "").lower()
    for spec in IMAGE_PROMPT_SPECS:
        if spec.key in lowered or spec.blogger_slug in lowered or spec.cloudflare_slug in lowered:
            return spec
    if "taos" in lowered or "타오스" in lowered:
        return _prompt_spec_by_key("taos-hum")
    if "amber" in lowered or "호박방" in lowered:
        return _prompt_spec_by_key("amber-room")
    return None


def _audit_image_prompt(prompt: str, *, spec: ImagePromptSpec, slot: str) -> dict[str, Any]:
    lowered = str(prompt or "").lower()
    hits = [term for term in spec.semantic_keywords if term.lower() in lowered]
    missing = [term for term in spec.semantic_keywords if term.lower() not in lowered]
    layout_ok = (
        ("3x4" in lowered and "grid" in lowered and "collage" in lowered)
        if slot == "hero"
        else ("evidence-board" in lowered or "visual evidence-board" in lowered or "visual summary" in lowered)
    )
    scene_ok = any(term in lowered for term in ("show ", "include ", "map", "diagram", "houses", "chamber", "crates"))
    material_ok = any(term in lowered for term in ("realistic", "documentary", "cinematic", "archive", "materials"))
    negative_ok = all(term in lowered for term in ("no logo", "no watermark")) and (
        "no text" in lowered or "no readable text" in lowered
    )
    size_ok = "1024x1024" in lowered
    score = 0
    score += min(45, len(hits) * 6)
    score += 20 if layout_ok else 0
    score += 10 if scene_ok else 0
    score += 10 if material_ok else 0
    score += 10 if negative_ok else 0
    score += 5 if size_ok else 0
    passed = score >= 80 and len(hits) >= 5 and layout_ok and scene_ok and negative_ok and size_ok
    return {
        "slot": slot,
        "score": min(score, 100),
        "pass": passed,
        "semantic_keywords": list(spec.semantic_keywords),
        "semantic_hits": hits,
        "semantic_missing": missing,
        "layout_ok": layout_ok,
        "scene_ok": scene_ok,
        "material_ok": material_ok,
        "negative_ok": negative_ok,
        "size_ok": size_ok,
    }


def _object_key_from_public_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    path = unquote(parsed.path or "").lstrip("/")
    if not path.startswith("assets/") or not path.lower().endswith(".webp"):
        raise ValueError(f"unsupported_public_image_url:{url}")
    return path


def _ordered_hero_closing_urls(urls: list[str]) -> list[str]:
    unique: list[str] = []
    for url in urls:
        normalized = str(url or "").strip()
        if normalized and normalized not in unique:
            unique.append(normalized)
    hero = next((url for url in unique if "-closing.webp" not in url.lower()), "")
    closing = next((url for url in unique if "-closing.webp" in url.lower()), "")
    return [url for url in (hero, closing) if url]


def _expected_article_image_count(html: str, image_urls: list[str]) -> int:
    page_urls = set(_extract_mystery_webp_urls(html))
    return sum(1 for image_url in image_urls if image_url in page_urls)


def _safe_slug(value: str, fallback: str = "mystery-topic") -> str:
    return slugify(str(value or "").strip(), separator="-") or fallback


def _render_template(template: str, values: dict[str, Any]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", str(value if value is not None else ""))
    return rendered


def _clean_json_payload(payload: dict[str, Any], *, fallback_keyword: str) -> dict[str, Any]:
    cleaned = dict(payload)
    cleaned["title"] = str(cleaned.get("title") or fallback_keyword).strip()
    cleaned["slug"] = _safe_slug(str(cleaned.get("slug") or cleaned["title"]))
    cleaned["meta_description"] = str(cleaned.get("meta_description") or cleaned.get("excerpt") or cleaned["title"]).strip()
    cleaned["excerpt"] = str(cleaned.get("excerpt") or cleaned["meta_description"]).strip()
    cleaned["html_article"] = str(cleaned.get("html_article") or "").strip()
    cleaned["article_pattern_id"] = str(cleaned.get("article_pattern_id") or "evidence-breakdown").strip()
    cleaned["article_pattern_version"] = int(cleaned.get("article_pattern_version") or PATTERN_VERSION)
    cleaned["hero_image_prompt"] = str(
        cleaned.get("hero_image_prompt") or cleaned.get("image_collage_prompt") or f"3x4 panel grid collage about {fallback_keyword}"
    ).strip()
    cleaned["closing_image_prompt"] = str(
        cleaned.get("closing_image_prompt") or f"final archive board visual summary about {fallback_keyword}"
    ).strip()
    cleaned["image_collage_prompt"] = cleaned["hero_image_prompt"]
    cleaned["inline_collage_prompt"] = None
    if not isinstance(cleaned.get("labels"), list):
        cleaned["labels"] = []
    if not isinstance(cleaned.get("faq_section"), list):
        cleaned["faq_section"] = []
    if not isinstance(cleaned.get("image_asset_plan"), dict):
        cleaned["image_asset_plan"] = {
            "slots": [
                {"slot": "hero", "prompt_key": "hero_image_prompt"},
                {"slot": "closing", "prompt_key": "closing_image_prompt"},
            ]
        }
    if not isinstance(cleaned.get("seo_keyword_map"), dict):
        cleaned["seo_keyword_map"] = {
            "primary_keyword": fallback_keyword,
            "secondary_keywords": [],
            "search_intent": "mystery evidence review",
        }
    return cleaned


def _validate_article_contract(payload: dict[str, Any], *, locale: str) -> list[str]:
    errors: list[str] = []
    html = str(payload.get("html_article") or "")
    if _plain_len(html) < 3000:
        errors.append("plain_text_under_3000")
    if _body_h1_count(html) > 0:
        errors.append("body_h1_detected")
    h2_count = len(H2_RE.findall(html))
    if h2_count not in {4, 5}:
        errors.append(f"h2_count_invalid:{h2_count}")
    if len(payload.get("faq_section") or []) != 3:
        errors.append("faq_count_not_3")
    if "summary-box" not in html:
        errors.append("summary_box_missing")
    if "evidence-table" not in html and "<table" not in html.lower():
        errors.append("comparison_table_missing")
    if str(payload.get("article_pattern_id") or "") not in ALLOWED_PATTERNS:
        errors.append("invalid_article_pattern_id")
    if int(payload.get("article_pattern_version") or 0) != PATTERN_VERSION:
        errors.append("invalid_article_pattern_version")
    if not str(payload.get("hero_image_prompt") or "").strip():
        errors.append("hero_image_prompt_missing")
    if not str(payload.get("closing_image_prompt") or "").strip():
        errors.append("closing_image_prompt_missing")
    if not isinstance(payload.get("seo_keyword_map"), dict):
        errors.append("seo_keyword_map_missing")
    if any(token in html for token in ("\uac80\uc99d \uba54\ubaa8", "\uc791\uc131 \uba54\ubaa8", "verification memo", "validation note")):
        errors.append("forbidden_validation_memo")
    if locale == "ko" and re.search(r"\?{2,}|\uFFFD", json.dumps(payload, ensure_ascii=False)):
        errors.append("mojibake_or_replacement_char_detected")
    return errors


def _score_article(payload: dict[str, Any]) -> dict[str, int]:
    html = str(payload.get("html_article") or "")
    text_len = _plain_len(html)
    has_summary = "summary-box" in html
    has_table = "evidence-table" in html or "<table" in html.lower()
    keyword_map = payload.get("seo_keyword_map") if isinstance(payload.get("seo_keyword_map"), dict) else {}
    seo = 55
    seo += 10 if text_len >= 3000 else 0
    seo += 8 if keyword_map.get("primary_keyword") else 0
    seo += 7 if len(keyword_map.get("secondary_keywords") or []) >= 4 else 0
    seo += 6 if has_table else 0
    seo += 6 if has_summary else 0
    geo = 60 + (10 if has_table else 0) + (8 if has_summary else 0) + (7 if text_len >= 3200 else 0)
    title = str(payload.get("title") or "")
    ctr = 55 + (10 if len(title) >= 35 else 0) + (10 if any(t in title.lower() for t in ("why", "missing", "record", "evidence", "\uacf5\ubc31", "\uae30\ub85d", "\ub2e8\uc11c")) else 0)
    return {
        "seo_score": min(seo, 100),
        "geo_score": min(geo, 100),
        "ctr_score": min(ctr, 100),
        "lighthouse_score": 0,
    }


def _load_topics(path: str | None, topic_count: int, *, mode: str, db) -> list[dict[str, Any]]:
    if path:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        topics = payload.get("topics") if isinstance(payload, dict) else payload
        if not isinstance(topics, list):
            raise ValueError("topics_file_must_contain_list_or_topics_key")
        return [dict(item) if isinstance(item, dict) else {"keyword": str(item)} for item in topics][:topic_count]
    if mode == "repair-existing-images":
        return [
            {
                "keyword": spec.keyword,
                "image_prompt_spec": spec.key,
                "blogger_slug": spec.blogger_slug,
                "cloudflare_slug": spec.cloudflare_slug,
                "reason": "regenerate existing Taos/Amber hero and closing images in place; do not create posts",
                "trend_score": 0,
            }
            for spec in IMAGE_PROMPT_SPECS[:topic_count]
        ]
    if mode == "repair-existing-today":
        rows = (
            db.execute(
                select(SyncedBloggerPost)
                .where(
                    SyncedBloggerPost.blog_id == BLOGGER_BLOG_ID,
                    SyncedBloggerPost.status.in_(["live", "published", "LIVE", "PUBLISHED"]),
                )
                .order_by(SyncedBloggerPost.published_at.desc().nullslast(), SyncedBloggerPost.id.desc())
                .limit(topic_count)
            )
            .scalars()
            .all()
        )
        return [
            {
                "keyword": row.title,
                "blogger_url": row.url or "",
                "blogger_remote_post_id": row.remote_post_id,
                "reason": "existing Blogger mystery post repair; do not create new post",
                "trend_score": 0,
            }
            for row in rows
        ]
    if mode == "complete-existing-cloudflare":
        rows = (
            db.execute(
                select(SyncedCloudflarePost)
                .where(
                    SyncedCloudflarePost.status.in_(["published", "live", "PUBLISHED", "LIVE"]),
                    or_(
                        SyncedCloudflarePost.canonical_category_slug == CLOUDFLARE_CATEGORY_LABEL,
                        SyncedCloudflarePost.category_slug == CLOUDFLARE_CATEGORY_LABEL,
                        SyncedCloudflarePost.canonical_category_name == CLOUDFLARE_CATEGORY_LABEL,
                        SyncedCloudflarePost.category_name == CLOUDFLARE_CATEGORY_LABEL,
                        SyncedCloudflarePost.slug.like(f"%{CLOUDFLARE_CATEGORY_LEAF}%"),
                    ),
                )
                .order_by(SyncedCloudflarePost.published_at.desc().nullslast(), SyncedCloudflarePost.id.desc())
                .limit(topic_count)
            )
            .scalars()
            .all()
        )
        return [
            {
                "keyword": row.title,
                "cloudflare_url": row.url or "",
                "cloudflare_remote_post_id": row.remote_post_id,
                "cloudflare_slug": row.slug or "",
                "reason": "complete existing Cloudflare Mysteria post with Blogger counterpart",
                "trend_score": 0,
            }
            for row in rows
        ]
    if mode == "dry-run":
        return SAMPLE_TOPICS[:topic_count]
    provider = get_article_provider(db, provider_hint="codex_cli", allow_large=True)
    prompt = (
        "Return JSON only with key topics. Generate high-CTR global mystery topics for paired publishing. "
        "Each item must include keyword, reason, trend_score. Avoid already famous topics recently overused. "
        f"Need {topic_count} topics."
    )
    payload, _raw = provider.generate_structured_json(prompt)
    topics = payload.get("topics")
    if not isinstance(topics, list):
        raise ValueError("topic_generation_payload_missing_topics")
    return [dict(item) for item in topics if isinstance(item, dict)][:topic_count]


def _require_blogger_blog(db) -> Blog:
    blog = (
        db.execute(
            select(Blog)
            .where(Blog.id == BLOGGER_BLOG_ID)
            .options(selectinload(Blog.articles), selectinload(Blog.blogger_posts))
        )
        .scalars()
        .one_or_none()
    )
    if blog is None:
        raise RuntimeError("blogger_mystery_blog_not_found")
    if str(blog.profile_key or "").strip() != BLOGGER_PROFILE_KEY:
        raise RuntimeError(f"blogger_profile_key_mismatch:{blog.profile_key}")
    return blog


def _resolve_cloudflare_category(client: CloudflareIntegrationClient) -> dict[str, Any]:
    categories = client.list_categories()
    for item in categories:
        slug = str(item.get("slug") or item.get("leaf") or "").strip()
        name = str(item.get("name") or item.get("label") or "").strip()
        item_id = str(item.get("id") or "").strip()
        if slug == CLOUDFLARE_CATEGORY_LEAF or name == CLOUDFLARE_CATEGORY_LABEL or item_id == CLOUDFLARE_CATEGORY_ID_FALLBACK:
            return item
    return {"id": CLOUDFLARE_CATEGORY_ID_FALLBACK, "slug": CLOUDFLARE_CATEGORY_LEAF, "name": CLOUDFLARE_CATEGORY_LABEL}


def _duplicate_gate(db, *, keyword: str, proposed_slug: str, cloudflare_posts: list[dict[str, Any]]) -> dict[str, Any]:
    terms = [term for term in re.split(r"[^a-z0-9]+", f"{keyword} {proposed_slug}".lower()) if len(term) >= 4]
    terms = [term for term in terms if term not in {"mystery", "case", "archive", "evidence", "review"}][:4]
    slug = _safe_slug(proposed_slug or keyword)

    article_hits = (
        db.execute(
            select(Article.id, Article.title, Article.slug)
            .where(
                Article.blog_id == BLOGGER_BLOG_ID,
                or_(
                    func.lower(Article.slug).like(f"%{slug}%"),
                    *[func.lower(Article.title).like(f"%{term}%") for term in terms[:2]],
                ),
            )
            .limit(10)
        )
        .all()
    )
    blogger_hits = (
        db.execute(
            select(SyncedBloggerPost.id, SyncedBloggerPost.title, SyncedBloggerPost.url)
            .where(
                SyncedBloggerPost.blog_id == BLOGGER_BLOG_ID,
                or_(
                    func.lower(SyncedBloggerPost.url).like(f"%{slug}%"),
                    *[func.lower(SyncedBloggerPost.title).like(f"%{term}%") for term in terms[:2]],
                ),
            )
            .limit(10)
        )
        .all()
    )
    cf_hits: list[dict[str, str]] = []
    for post in cloudflare_posts:
        haystack = " ".join(str(post.get(k) or "") for k in ("title", "slug", "publicUrl", "url")).lower()
        if slug in haystack or (terms and all(term in haystack for term in terms[:2])):
            cf_hits.append(
                {
                    "id": str(post.get("id") or ""),
                    "title": str(post.get("title") or ""),
                    "slug": str(post.get("slug") or ""),
                    "url": str(post.get("publicUrl") or post.get("url") or ""),
                }
            )
    blocked = bool(article_hits or blogger_hits or cf_hits)
    return {
        "status": "blocked" if blocked else "pass",
        "terms": terms,
        "blogger_article_hits": [dict(row._mapping) for row in article_hits],
        "blogger_live_hits": [dict(row._mapping) for row in blogger_hits],
        "cloudflare_hits": cf_hits[:10],
    }


def _generate_structured_json_with_fallback(
    db,
    prompt: str,
    *,
    values: dict[str, Any],
    allow_large: bool,
    model_override: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    provider_specs = [
        ("codex_cli", model_override),
        ("gemini", str(values.get("gemini_model") or "")),
        ("openai", model_override or str(values.get("openai_large_text_model" if allow_large else "openai_small_text_model") or "")),
        (None, model_override),
    ]
    seen: set[tuple[str, str]] = set()
    for provider_hint, model in provider_specs:
        key = (str(provider_hint or ""), str(model or ""))
        if key in seen:
            continue
        seen.add(key)
        try:
            provider = get_article_provider(
                db,
                provider_hint=provider_hint,
                model_override=model or None,
                allow_large=allow_large,
            )
            payload, raw = provider.generate_structured_json(prompt)
            if attempts:
                raw = {**dict(raw or {}), "fallback_attempts": attempts}
            return payload, raw
        except Exception as exc:  # noqa: BLE001
            attempts.append({"provider_hint": provider_hint or "runtime_default", "model": model or "", "error": str(exc)})
            continue
    raise RuntimeError(f"all_text_generation_providers_failed:{attempts}")


def _resolve_existing_blogger_target(db, topic: dict[str, Any], duplicate_gate: dict[str, Any]) -> SyncedBloggerPost | None:
    remote_id = str(topic.get("blogger_remote_post_id") or "").strip()
    url = str(topic.get("blogger_url") or "").strip()
    if remote_id or url:
        row = (
            db.execute(
                select(SyncedBloggerPost).where(
                    SyncedBloggerPost.blog_id == BLOGGER_BLOG_ID,
                    or_(
                        SyncedBloggerPost.remote_post_id == remote_id,
                        SyncedBloggerPost.url == url,
                    ),
                )
            )
            .scalars()
            .first()
        )
        if row:
            return row
    hits = duplicate_gate.get("blogger_live_hits") or []
    if hits:
        hit_id = hits[0].get("id")
        if hit_id:
            return db.get(SyncedBloggerPost, int(hit_id))
    return None


def _resolve_existing_cloudflare_target(client: CloudflareIntegrationClient, topic: dict[str, Any], duplicate_gate: dict[str, Any]) -> dict[str, Any] | None:
    explicit_id = str(topic.get("cloudflare_remote_post_id") or topic.get("cloudflare_id") or "").strip()
    explicit_url = str(topic.get("cloudflare_url") or "").strip()
    if explicit_id:
        detail = client.get_post(explicit_id)
        if detail:
            return detail
    hits = duplicate_gate.get("cloudflare_hits") or []
    candidates = []
    if explicit_url:
        candidates.append({"url": explicit_url})
    candidates.extend(hits)
    posts = client.list_posts()
    for candidate in candidates:
        candidate_url = str(candidate.get("url") or "").rstrip("/")
        candidate_id = str(candidate.get("id") or "").strip()
        for post in posts:
            post_url = str(post.get("publicUrl") or post.get("url") or "").rstrip("/")
            post_id = str(post.get("id") or post.get("remote_id") or "").strip()
            if (candidate_id and candidate_id == post_id) or (candidate_url and candidate_url == post_url):
                detail = client.get_post(post_id)
                if detail:
                    return detail
    return None


def _resolve_blogger_counterpart(db, *, cloudflare_slug: str, keyword: str) -> SyncedBloggerPost | None:
    slug_terms = [term for term in re.split(r"[^a-z0-9]+", cloudflare_slug.lower()) if len(term) >= 3]
    keyword_terms = [term for term in re.split(r"[^a-z0-9]+", keyword.lower()) if len(term) >= 3]
    strong_pairs: list[tuple[str, str]] = []
    if len(slug_terms) >= 2:
        strong_pairs.append((slug_terms[0], slug_terms[1]))
    if len(keyword_terms) >= 2:
        strong_pairs.append((keyword_terms[0], keyword_terms[1]))
    for first, second in strong_pairs:
        row = (
            db.execute(
                select(SyncedBloggerPost)
                .where(
                    SyncedBloggerPost.blog_id == BLOGGER_BLOG_ID,
                    or_(
                        SyncedBloggerPost.url.ilike(f"%{first}%{second}%"),
                        SyncedBloggerPost.url.ilike(f"%{second}%{first}%"),
                        SyncedBloggerPost.title.ilike(f"%{first}%{second}%"),
                        SyncedBloggerPost.title.ilike(f"%{second}%{first}%"),
                    ),
                )
                .order_by(SyncedBloggerPost.published_at.desc().nullslast(), SyncedBloggerPost.id.desc())
            )
            .scalars()
            .first()
        )
        if row:
            return row
    return None


def _collect_existing_image_urls(*, live_url: str, stored_content: str, timeout: float) -> list[str]:
    html = stored_content or ""
    if live_url:
        live = _probe(live_url, timeout=timeout)
        html = f"{html}\n{live.get('text') or ''}"
    return _extract_mystery_webp_urls(html)[:2]


def _generate_planner(db, *, keyword: str, values: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    prompt = f"""
Return JSON only.
Design one paired mystery article plan for this topic: {keyword}
Keys:
- topic
- recommended_pattern_id: one of {sorted(ALLOWED_PATTERNS)}
- ctr_angle
- korean_angle
- english_angle
- primary_keyword
- secondary_keywords
- hero_visual_direction
- closing_visual_direction
Rules:
- article_pattern_version must be {PATTERN_VERSION}
- no raw topic echo title
- topic must work for Korean Cloudflare and English Blogger.
"""
    payload, raw = _generate_structured_json_with_fallback(
        db,
        prompt,
        values=values,
        allow_large=True,
        model_override=str(values.get("openai_large_text_model") or values.get("text_runtime_model") or ""),
    )
    pattern = str(payload.get("recommended_pattern_id") or "evidence-breakdown").strip()
    if pattern not in ALLOWED_PATTERNS:
        payload["recommended_pattern_id"] = "evidence-breakdown"
    payload["article_pattern_version"] = PATTERN_VERSION
    return payload, raw


def _generate_article(db, *, keyword: str, planner: dict[str, Any], prompt_path: Path, locale: str, values: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str]:
    template = _read_text(prompt_path)
    prompt = _render_template(
        template,
        {
            "keyword": keyword,
            "current_date": datetime.now().strftime("%Y-%m-%d"),
            "target_audience": values.get("target_audience") or "mystery readers",
            "content_brief": values.get("content_brief") or "documentary mystery feature",
            "planner_brief": json.dumps(planner, ensure_ascii=False, indent=2),
            "editorial_category_key": "mysteria-story" if locale == "ko" else "case-files",
            "editorial_category_label": CLOUDFLARE_CATEGORY_LABEL if locale == "ko" else "Case Files",
            "editorial_category_guidance": "Mystery evidence and archive storytelling",
            "article_pattern_id": planner.get("recommended_pattern_id") or "evidence-breakdown",
            "blog_name": "The Midnight Archives" if locale == "en" else "Dongri Archive",
        },
    )
    try:
        payload, raw = _generate_structured_json_with_fallback(
            db,
            prompt,
            values=values,
            allow_large=False,
            model_override=str(values.get("openai_small_text_model") or values.get("text_runtime_model") or ""),
        )
    except Exception as exc:  # noqa: BLE001
        payload = _local_article_payload(keyword=keyword, planner=planner, locale=locale)
        raw = {"provider": "local_fallback", "reason": str(exc)}
    return _clean_json_payload(payload, fallback_keyword=keyword), raw, prompt




def _topic_profile(keyword: str) -> dict[str, str]:
    lowered = keyword.lower()
    if "taos" in lowered or "타오스" in keyword:
        return {
            "key": "taos-hum",
            "en_title": "Why the Taos Hum Still Divides Witnesses, Engineers, and Acoustic Records",
            "ko_title": "타오스 험: 들리는 사람에게만 남는 저주파 소리의 기록",
            "slug": "taos-hum-acoustic-studies-local-testimony-record",
            "primary_en": "Taos Hum evidence",
            "primary_ko": "타오스 험 원인",
            "subject_en": "the Taos Hum",
            "subject_ko": "타오스 험",
            "hook_en": "A low hum is reported at night, yet the person standing beside the witness may hear nothing.",
            "hook_ko": "밤마다 낮은 윙윙거림이 들린다는 증언이 있지만, 같은 공간의 다른 사람은 아무 소리도 듣지 못한다.",
            "scene_en": "New Mexico rooms, quiet desert streets, night testimony, low-frequency measurement sheets",
            "scene_ko": "뉴멕시코의 조용한 주택가, 밤의 증언, 저주파 측정 기록, 들리지 않는 소리의 불균형",
        }
    return {
        "key": "amber-room",
        "en_title": "The Amber Room Trail: What the Looting Records Reveal and What Still Vanishes",
        "ko_title": "사라진 호박방의 금빛 벽: 나치 약탈 기록과 아직 닫히지 않은 추적",
        "slug": "amber-room-nazi-loot-records-unclosed-search",
        "primary_en": "Amber Room disappearance",
        "primary_ko": "호박방 실종 기록",
        "subject_en": "the Amber Room",
        "subject_ko": "호박방",
        "hook_en": "금빛 호박 패널로 채워진 방은 전쟁 중 해체되어 옮겨졌고, 이후 기록과 소문 사이에서 흔적을 잃었다.",
        "hook_ko": "금빛 호박 패널로 채워진 방은 전쟁 중 해체되어 옮겨졌고, 이후 기록과 소문 사이에서 흔적을 잃었다.",
        "scene_en": "palace rooms, wartime rail records, missing crates, restoration sketches, looting archives",
        "scene_ko": "궁전 내부, 전시 철도 기록, 사라진 상자, 복원 도면, 약탈 문서와 추적 파일",
    }


def _local_article_payload(*, keyword: str, planner: dict[str, Any], locale: str) -> dict[str, Any]:
    profile = _topic_profile(keyword)
    pattern = str(planner.get("recommended_pattern_id") or "evidence-breakdown")
    if pattern not in ALLOWED_PATTERNS:
        pattern = "evidence-breakdown"
    if locale == "ko":
        return _local_korean_article(profile=profile, pattern=pattern)
    return _local_english_article(profile=profile, pattern=pattern)


def _local_english_article(*, profile: dict[str, str], pattern: str) -> dict[str, Any]:
    title = profile["en_title"]
    subject = profile["subject_en"]
    h2s = {
        "case-timeline": ["Case Snapshot", "Timeline of the Record", "What Still Does Not Fit", "Closing File"],
        "evidence-breakdown": ["Case Snapshot", "Evidence on the Table", "Counterpoints and Limits", "Closing File"],
        "legend-context": ["Where the Legend Starts", "How the Story Spread", "Modern Readings", "Closing File"],
        "scene-investigation": ["Scene Reconstruction", "Movement and Timing", "The Strange Point", "Closing File"],
        "scp-dossier": ["File Overview", "Observation Log", "Risk Signal", "Closing File"],
    }[pattern]
    paragraphs = [
        f"<p>{profile['hook_en']} That contradiction is why {subject} still works as a mystery rather than a simple anecdote. If the event was only rumor, the reports should fade; if it was only one measurable source, the records should close neatly. Neither happened.</p>",
        f"<p>The useful question is not whether every dramatic version is true. The better question is which parts of the record survive contact with testimony, geography, measurement, and motive. This article follows that narrower path so the mystery stays readable without becoming inflated.</p>",
        f"<h2>{h2s[0]}</h2>",
        f"<p>{subject.title()} sits at the point where public memory and documented uncertainty overlap. The case is often repeated as a finished legend, but the stronger reading starts with restraint: what was reported, who had reason to notice it, and which details were added later because they made the story easier to sell.</p>",
        f"<p>That restraint matters because the case has several layers. There is the immediate event, the later retelling, the technical explanation, and the emotional reason people keep returning to it. When those layers are mixed together, every theory looks stronger than it really is.</p>",
        "<aside class=\"summary-box\"><h3>Key Takeaways</h3><ul><li>The record is real enough to deserve analysis.</li><li>The most dramatic versions are not always the most useful.</li><li>Evidence and testimony point in different directions.</li><li>The unresolved part is the gap between explanation and experience.</li></ul></aside>",
        f"<h2>{h2s[1]}</h2>",
        f"<p>The strongest evidence is not a single clue but a pattern of partial clues. Witness accounts, location details, timing, and later technical interpretations all contribute something. None of them, alone, has enough force to end the case.</p>",
        f"<p>For {subject}, the central tension is that the ordinary explanations are plausible but incomplete. Environmental conditions, human perception, wartime confusion, paperwork loss, or institutional silence can explain much of the story. They do not explain why specific details continued to resist closure.</p>",
        "<table class=\"evidence-table\"><thead><tr><th>Claim</th><th>What Supports It</th><th>What Limits It</th></tr></thead><tbody><tr><td>Documented record</td><td>Reports and later references remain traceable</td><td>Some details depend on retelling</td></tr><tr><td>Technical explanation</td><td>Fits part of the known pattern</td><td>Does not cover every witness or gap</td></tr><tr><td>Legend growth</td><td>Explains dramatic additions</td><td>Cannot erase the original uncertainty</td></tr></tbody></table>",
        f"<h2>{h2s[2]}</h2>",
        f"<p>The main counterpoint is that mystery culture rewards ambiguity. Once a case becomes famous, every missing document or conflicting statement can be treated as proof of something larger. A careful reading has to resist that temptation.</p>",
        f"<p>At the same time, dismissing the case as exaggeration is too easy. The durable part of {subject} is not the most spectacular theory. It is the fact that reasonable explanations still leave a remainder: a witness mismatch, a lost chain of custody, an untested assumption, or a timeline that does not land cleanly.</p>",
        f"<p>This is where search interest remains high. Readers are not only asking what happened; they are asking why the available explanation feels almost complete but not final. That small distance between almost and final is the engine of the case.</p>",
        f"<p>A stronger article about {subject} has to slow down at the points where short summaries rush ahead. The first point is source quality: a late retelling cannot carry the same weight as a nearer record. The second is motive: people preserve stories for emotional, political, commercial, or defensive reasons. The third is physical plausibility: even a strange case must pass through location, weather, sound, transport, paperwork, or human behavior.</p>",
        f"<p>Those filters do not make the mystery smaller. They make it sharper. Instead of asking readers to accept every dramatic claim, the record asks them to notice which claims survive comparison. A theory that explains one clue while ignoring two others is not a solution; it is only a sketch.</p>",
        f"<p>The most interesting feature of {subject} is that its uncertainty is not empty. It has shape. It gathers around witness reliability, missing or damaged records, limits of reconstruction, and the way later audiences want the story to mean more than the documents can prove.</p>",
        f"<p>That is why the case should not be treated as a contest between believers and skeptics. A skeptical reading can still admit that something unusual was reported. A believer's reading can still admit that some famous details were probably amplified. The archive becomes useful only when both admissions are allowed at the same time.</p>",
        f"<h2>{h2s[3]}</h2>",
        f"<p>The most responsible conclusion is that {subject} should be treated as a layered record, not a solved puzzle and not a blank canvas for fantasy. The evidence narrows the field, but it does not erase the central uncertainty.</p>",
        f"<p>That is why the case still deserves a place in the archive.</p>",
    ]
    html = "\n".join(paragraphs)
    return {
        "title": title,
        "meta_description": f"A structured evidence review of {subject}, separating record, theory, witness conflict, and the unresolved gap that keeps the case active.",
        "labels": ["Case Files", "Mystery Archives", "Evidence Review", "Unsolved Cases", "Historical Mystery"],
        "slug": profile["slug"],
        "excerpt": f"{title} This article separates the surviving record from the claims that grew around it.",
        "html_article": html,
        "faq_section": [
            {"question": f"Is {subject} considered solved?", "answer": "No. Several explanations are plausible, but the record still leaves unresolved gaps."},
            {"question": "What is the strongest explanation?", "answer": "The strongest explanation is usually a mixed one that combines documented conditions with later retelling."},
            {"question": "Why does the case still matter?", "answer": "It shows how evidence, memory, and missing context can keep a mystery alive long after the first report."},
        ],
        "hero_image_prompt": f"One realistic 3x4 panel grid collage about {profile['scene_en']}, visible white gutters, clean grid layout, muted archival colors, no text, no logo, 1024x1024.",
        "closing_image_prompt": f"One realistic final archive board visual summary about {profile['scene_en']}, balanced composition, evidence map mood, no text, no logo, 1024x1024.",
        "image_collage_prompt": f"One realistic 3x4 panel grid collage about {profile['scene_en']}, visible white gutters, clean grid layout, muted archival colors, no text, no logo, 1024x1024.",
        "image_asset_plan": {"slots": [{"slot": "hero", "prompt_key": "hero_image_prompt"}, {"slot": "closing", "prompt_key": "closing_image_prompt"}]},
        "seo_keyword_map": {"primary_keyword": profile["primary_en"], "secondary_keywords": [subject, "mystery timeline", "evidence review", "unresolved theories", "historical records"], "search_intent": "evidence-led mystery feature"},
        "article_pattern_id": pattern,
        "article_pattern_version": PATTERN_VERSION,
    }



def _html_to_markdownish(html_value: str) -> str:
    text = str(html_value or "")
    text = re.sub(
        r"<aside[^>]*class=[\"'][^\"']*summary-box[^\"']*[\"'][^>]*>\s*<h3>(.*?)</h3>",
        lambda m: "\n" + _strip_tags(m.group(1)) + "\n",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"</aside>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<h2[^>]*>(.*?)</h2>", lambda m: "\n" + _strip_tags(m.group(1)) + "\n", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<h3[^>]*>(.*?)</h3>", lambda m: "\n" + _strip_tags(m.group(1)) + "\n", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<li[^>]*>(.*?)</li>", lambda m: "ㆍ" + _strip_tags(m.group(1)) + "\n", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(
        r"<tr[^>]*>(.*?)</tr>",
        lambda m: "\n" + " / ".join(_strip_tags(cell) for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", m.group(1), flags=re.IGNORECASE | re.DOTALL)) + "\n",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"<p[^>]*>(.*?)</p>", lambda m: _strip_tags(m.group(1)) + "\n\n", text, flags=re.IGNORECASE | re.DOTALL)
    text = _strip_tags(text)
    text = re.sub(r"(?m)^\s*#{1,6}\s+", "", text)
    text = text.replace("**", "")
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()

def _local_korean_article(*, profile: dict[str, str], pattern: str) -> dict[str, Any]:
    title = profile["ko_title"]
    subject = profile["subject_ko"]
    h2s = {
        "case-timeline": ["사건 개요", "연대기", "남은 공백", "마무리 기록"],
        "evidence-breakdown": ["사건 개요", "증거 목록", "반론과 한계", "마무리 기록"],
        "legend-context": ["전설의 시작", "전파 경로", "현대적 해석", "마무리 기록"],
        "scene-investigation": ["현장 묘사", "동선과 시간", "이상한 지점", "마무리 기록"],
        "scp-dossier": ["파일 개요", "관찰 기록", "위험 신호", "마무리 기록"],
    }[pattern]
    paragraphs = [
        f"<p>{profile['hook_ko']} 이 모순 때문에 {subject}은 단순한 괴담이 아니라 기록과 체험이 충돌하는 사건으로 남는다. 모두가 같은 것을 보거나 들었다면 설명은 쉬웠을 것이다. 그러나 이 사건은 처음부터 경험한 사람과 경험하지 못한 사람 사이의 간격에서 시작된다.</p>",
        f"<p>중요한 질문은 자극적인 전설이 사실인지가 아니다. 남은 기록이 어디까지 확인되고, 어느 지점부터 해석이 붙었으며, 그 해석이 아직도 독자를 붙잡는 이유가 무엇인지 따져보는 것이다.</p>",
        f"<h2>{h2s[0]}</h2>",
        f"<p>{subject}은 확인 가능한 기록과 대중적 상상이 겹치는 지점에 있다. 유명한 미스터리일수록 이야기는 단순해 보이지만, 실제로는 증언, 장소, 시간, 조사 과정, 보도 방식이 서로 다른 방향으로 움직인다.</p>",
        f"<p>그래서 이 사건을 볼 때는 결론보다 구조가 먼저다. 누가 무엇을 경험했는지, 그 경험을 뒷받침하는 자료가 있는지, 그리고 나중에 붙은 설명이 원래 기록을 얼마나 바꾸었는지 분리해야 한다.</p>",
        "<aside class=\"summary-box\"><h3>핵심 정리</h3><ul><li>출발점은 확인 가능한 증언과 기록이다.</li><li>가장 유명한 설명이 항상 가장 강한 증거는 아니다.</li><li>기록의 빈칸은 해석을 부르지만 확정 근거는 아니다.</li><li>남은 의문은 체험과 설명 사이의 간격에 있다.</li></ul></aside>",
        f"<h2>{h2s[1]}</h2>",
        f"<p>증거를 보면 하나의 결정적 단서보다 여러 약한 단서의 배열이 중요하다. 증언은 사건의 감각을 보여주고, 장소 정보는 가능성을 좁히며, 조사 기록은 과장된 주장을 걸러낸다. 문제는 이 요소들이 항상 같은 결론을 향하지 않는다는 점이다.</p>",
        f"<p>{subject}의 핵심도 바로 그 불균형에 있다. 일반적인 설명은 상당 부분을 해명한다. 환경 조건, 인간의 지각 차이, 전쟁과 행정의 혼란, 기록 손실, 보도 과정의 반복이 각각 일부를 설명할 수 있다. 그러나 일부를 설명한다는 사실이 전체를 닫는 것은 아니다.</p>",
        "<table class=\"evidence-table\"><thead><tr><th>가설</th><th>설명</th><th>한계</th></tr></thead><tbody><tr><td>기록 중심 해석</td><td>확인 가능한 자료를 기준으로 범위를 좁힌다</td><td>사라진 자료와 누락된 맥락은 남는다</td></tr><tr><td>환경 또는 기술 설명</td><td>현상의 일부를 현실적으로 설명한다</td><td>모든 증언 차이를 완전히 덮지는 못한다</td></tr><tr><td>전설화 과정</td><td>과장과 반복을 설명한다</td><td>초기 의문 자체를 제거하지는 못한다</td></tr></tbody></table>",
        f"<h2>{h2s[2]}</h2>",
        f"<p>반론은 분명하다. 미스터리 콘텐츠는 빈칸을 좋아한다. 문서가 사라지거나 증언이 엇갈리면 그것만으로 거대한 음모나 초자연적 설명이 붙기 쉽다. 하지만 그런 방식은 사건을 더 흥미롭게 만들 수는 있어도 더 정확하게 만들지는 않는다.</p>",
        f"<p>그렇다고 {subject}을 단순한 착각이나 과장으로만 닫는 것도 부족하다. 오래 살아남은 사건에는 대체로 이유가 있다. 설명은 가능하지만 완전히 매끈하지 않고, 기록은 남아 있지만 결정적인 연결 고리가 비어 있다. 그 작은 불일치가 사건을 계속 되돌아보게 만든다.</p>",
        f"<p>검색자가 이 주제를 다시 찾는 이유도 여기에 있다. 사람들은 단지 무엇이 일어났는지를 묻는 것이 아니라, 왜 제시된 설명이 끝까지 만족스럽지 않은지를 묻는다. 그 질문이 남아 있는 한 사건은 닫히지 않는다.</p>",
        f"<p>{subject}을 제대로 읽으려면 짧은 요약이 건너뛰는 부분에서 속도를 늦춰야 한다. 첫째는 자료의 거리다. 사건 가까이에서 남은 기록과 훨씬 뒤에 반복된 이야기는 같은 무게로 놓을 수 없다. 둘째는 보존의 이유다. 사람들은 사실만이 아니라 두려움, 체면, 손실, 기억 때문에도 이야기를 남긴다.</p>",
        f"<p>셋째는 물리적 가능성이다. 이상한 사건이라도 장소, 시간, 이동 경로, 소리의 전달, 운송 기록, 행정 문서 같은 현실 조건을 통과해야 한다. 이 조건을 통과하지 못한 가설은 흥미로울 수는 있어도 설명으로는 약하다.</p>",
        f"<p>이 기준은 미스터리를 작게 만드는 장치가 아니다. 오히려 사건을 더 선명하게 만든다. 모든 주장을 한꺼번에 믿으라고 요구하는 대신, 어떤 주장이 비교를 견디는지 보게 한다. 하나의 단서만 잘 설명하고 다른 단서를 버리는 주장은 결론이 아니라 임시 스케치에 가깝다.</p>",
        f"<p>{subject}의 흥미로운 점은 불확실성이 비어 있지 않다는 데 있다. 그 불확실성은 늘 비슷한 지점에 모인다. 증언의 신뢰도, 사라진 자료, 기술적 재구성의 한계, 그리고 후대 독자가 사건에 더 큰 의미를 부여하려는 욕망이 그 지점이다.</p>",
        f"<p>그래서 이 사건은 믿는 사람과 의심하는 사람의 논쟁으로만 보면 흐려진다. 회의적인 독해도 무언가 특이한 보고가 있었다는 사실을 인정할 수 있다. 반대로 믿는 쪽도 유명한 세부사항 일부가 과장되었을 가능성을 받아들일 수 있다.</p>",
        f"<p>중요한 것은 결론을 서두르지 않는 것이다. 미스터리 글의 목적은 독자를 겁주거나 모든 의문을 한 번에 봉합하는 데 있지 않다. 오히려 어느 부분이 설명되었고, 어느 부분이 아직 남았는지 선명하게 보여주는 데 있다.</p>",
        f"<p>또 하나 봐야 할 지점은 제목이 만든 선입견이다. {subject}처럼 이름이 강한 사건은 제목만으로 이미 결론이 난 것처럼 보일 때가 많다. 하지만 강한 이름은 때로 실제 기록의 약한 연결부를 가린다. 독자는 이름이 주는 인상과 문서가 실제로 말하는 내용을 따로 보아야 한다.</p>",
        f"<p>장소성도 중요하다. 사건이 벌어진 공간은 단순한 배경이 아니다. 그 공간의 구조, 접근 가능성, 당시의 기술 수준, 주변 사람들의 위치가 해석을 제한한다. 같은 증언이라도 어느 장소에서 나왔는지에 따라 무게가 달라진다.</p>",
        f"<p>시간표는 더 엄격한 기준을 요구한다. 어떤 설명은 전체 분위기에는 맞지만 특정 시점의 이동이나 보고 순서와 충돌한다. 미스터리 분석에서 시간표를 세우는 이유는 글을 길게 만들기 위해서가 아니라 가능한 설명과 불가능한 설명을 가르기 위해서다.</p>",
        f"<p>침묵도 하나의 자료가 될 수 있다. 기록이 없다는 사실은 곧바로 음모를 뜻하지 않는다. 그러나 중요한 지점에서 반복적으로 자료가 비어 있다면, 그 빈칸이 생긴 이유를 따져볼 필요가 있다. 자연스러운 누락인지, 보존 실패인지, 애초에 기록되지 않은 사건인지에 따라 결론은 달라진다.</p>",
        f"<p>따라서 {subject}을 읽는 가장 좋은 방식은 단일한 해답을 고르는 것이 아니다. 먼저 확인 가능한 자료를 놓고, 다음으로 증언의 방향을 보고, 마지막으로 가설이 그 자료를 얼마나 자연스럽게 연결하는지 따져야 한다. 이 순서가 바뀌면 결론이 먼저 나오고 자료가 뒤따라가는 글이 된다.</p>",
        f"<p>이 글의 기준은 사건을 신비롭게 포장하는 것이 아니라 검토 가능한 형태로 정리하는 데 있다. 독자가 마지막에 남겨야 할 것은 공포가 아니라 판단의 순서다. 무엇이 확인되었고, 무엇이 추정이며, 무엇이 아직 빈칸인지 분리될 때 비로소 미스터리는 제대로 읽힌다.</p>",
        f"<p>독자가 실제로 얻어야 할 정보도 여기에 있다. {subject}을 둘러싼 많은 글은 결론을 먼저 던지고 근거를 뒤에 붙인다. 그러나 그렇게 쓰면 사건은 빨리 이해되는 대신 쉽게 왜곡된다. 이 글은 반대로 근거를 먼저 놓고, 그 근거가 허락하는 만큼만 결론을 좁힌다.</p>",
        f"<p>특히 증언과 기록이 충돌할 때는 어느 한쪽을 즉시 버리면 안 된다. 증언은 현장의 긴장과 체험의 방향을 알려주지만, 기억의 흔들림을 피할 수 없다. 기록은 더 차갑고 안정적이지만, 누락과 편집의 문제를 가진다. 두 자료가 어긋나는 지점이 바로 사건의 핵심이다.</p>",
        f"<p>{subject}이 오래 살아남은 이유는 설명이 전혀 없어서가 아니다. 오히려 설명 후보가 많기 때문에 더 오래 남았다. 각각의 설명은 일부를 잘 해명하지만 전체를 닫는 순간 약점을 드러낸다. 그래서 독자는 가장 화려한 가설보다 가장 적게 무너지는 가설을 찾아야 한다.</p>",
        f"<p>이런 방식으로 보면 미스터리는 단순한 소비용 이야기가 아니라 기록을 읽는 훈련이 된다. 무엇이 사실인지, 무엇이 추정인지, 무엇이 후대의 장식인지 구분하는 순간 사건은 더 차분해진다. 동시에 남은 빈칸은 더 분명해진다.</p>",
        f"<p>그래서 최종 판단은 극적인 한 문장이 아니라 검토 가능한 기준으로 남아야 한다. {subject}의 핵심은 무섭다는 감정이 아니라, 설명이 닿는 곳과 닿지 못하는 곳을 나누어 보는 데 있다. 그 구분이 있을 때 독자는 사건을 믿거나 비웃는 대신 스스로 판단할 수 있다.</p>",
        f"<h2>{h2s[3]}</h2>",
        f"<p>{subject}은 하나의 답으로 닫기보다 층을 나누어 읽어야 하는 기록이다. 확인된 사실은 과장을 줄이고, 남은 빈칸은 억지를 막는다. 그래서 이 사건은 해결된 이야기도 아니고 마음대로 꾸며도 되는 전설도 아니다.</p>",
        f"<p>가장 신중한 결론은 간단하다. 기록은 설명의 범위를 좁히지만, 모든 의문을 지우지는 못한다.</p>",
        f"<p>그 간격 때문에 {subject}은 아직도 다시 읽을 가치가 있다.</p>",
    ]
    html = "\n".join(paragraphs)
    return {
        "title": title,
        "meta_description": f"{subject}의 기록, 증언, 가설, 반론을 분리해 사건의 핵심 쟁점과 아직 남은 의문을 정리한 미스테리아 스토리 분석.",
        "excerpt": f"{title} 이 글은 확인된 기록과 후대의 해석을 분리해 사건의 빈칸을 다시 읽는다.",
        "labels": ["미스테리아 스토리", "미스터리", "기록 분석", "미해결 사건", "증거 검토"],
        "slug": profile["slug"],
        "html_article": html,
        "cloudflare_article_markdown": _html_to_markdownish(html),
        "faq_section": [
            {"question": f"{subject}은 해결된 사건인가?", "answer": "아니다. 여러 설명이 가능하지만 모든 기록과 증언을 동시에 닫는 결론은 아직 부족하다."},
            {"question": "가장 조심스럽게 볼 설명은 무엇인가?", "answer": "확인 가능한 기록을 중심에 두고 환경, 지각, 행정 기록, 전설화 과정을 함께 보는 복합 해석이다."},
            {"question": "왜 지금도 이 사건을 다시 보나?", "answer": "설명은 많지만 결정적 연결 고리가 부족하기 때문에 사건의 빈칸이 계속 남아 있기 때문이다."},
        ],
        "hero_image_prompt": f"One realistic 3x4 panel grid collage about {profile['scene_ko']}, visible white gutters, clean grid layout, muted archive colors, no text, no logo, 1024x1024.",
        "closing_image_prompt": f"One realistic final archive board visual summary about {profile['scene_ko']}, evidence map mood, balanced composition, no text, no logo, 1024x1024.",
        "image_collage_prompt": f"One realistic 3x4 panel grid collage about {profile['scene_ko']}, visible white gutters, clean grid layout, muted archive colors, no text, no logo, 1024x1024.",
        "image_asset_plan": {"slots": [{"slot": "hero", "prompt_key": "hero_image_prompt"}, {"slot": "closing", "prompt_key": "closing_image_prompt"}]},
        "seo_keyword_map": {"primary_keyword": profile["primary_ko"], "secondary_keywords": [subject, "미스터리 기록", "증거 분석", "사건 연대기", "미해결 가설"], "search_intent": "기록 기반 미스터리 분석"},
        "article_pattern_id": pattern,
        "article_pattern_version": PATTERN_VERSION,
    }

def _generate_image_bytes(
    db,
    *,
    slot: str,
    prompt: str,
    slug: str,
    prompt_audit: dict[str, Any] | None = None,
    allow_fallback: bool = False,
) -> tuple[bytes, dict[str, Any]]:
    if prompt_audit is not None and not bool(prompt_audit.get("pass")):
        raise RuntimeError(f"image_prompt_audit_failed:{slot}:{prompt_audit}")
    try:
        image_provider = get_image_provider(db)
        image_bytes, raw = image_provider.generate_image(prompt, f"{slug}-{slot}", size_override="1024x1024")
        metadata = dict(raw or {})
        metadata.setdefault("provider", metadata.get("provider") or "runtime_image_provider")
        metadata["fallback_used"] = False
        metadata["prompt"] = prompt
        if prompt_audit is not None:
            metadata["prompt_audit"] = prompt_audit
            metadata["prompt_audit_score"] = prompt_audit.get("score")
            metadata["semantic_keywords"] = prompt_audit.get("semantic_keywords") or []
        return image_bytes, metadata
    except Exception as exc:  # noqa: BLE001
        if not allow_fallback:
            raise RuntimeError(f"image_provider_failed_no_fallback:{slot}:{exc}") from exc
        return _generate_local_fallback_webp(slot=slot, prompt=prompt, slug=slug), {
            "provider": "local_fallback",
            "reason": str(exc),
            "prompt": prompt,
            "fallback_used": True,
            "prompt_audit": prompt_audit or {},
            "prompt_audit_score": (prompt_audit or {}).get("score"),
        }


def _generate_local_fallback_webp(*, slot: str, prompt: str, slug: str) -> bytes:
    from io import BytesIO

    from PIL import Image, ImageDraw, ImageFilter

    size = 1024
    image = Image.new("RGB", (size, size), (20, 20, 20))
    draw = ImageDraw.Draw(image)
    palette = [
        (33, 42, 49),
        (56, 65, 62),
        (84, 75, 58),
        (105, 91, 62),
        (42, 51, 67),
        (74, 60, 66),
    ]
    seed = sum(ord(ch) for ch in f"{slug}:{slot}:{prompt}")
    if slot == "hero":
        gutter = 8
        cols, rows = 5, 4
        cell_w = (size - gutter * (cols + 1)) // cols
        cell_h = (size - gutter * (rows + 1)) // rows
        draw.rectangle([0, 0, size, size], fill=(242, 242, 238))
        for row in range(rows):
            for col in range(cols):
                idx = (seed + row * cols + col) % len(palette)
                base = palette[idx]
                x0 = gutter + col * (cell_w + gutter)
                y0 = gutter + row * (cell_h + gutter)
                x1 = x0 + cell_w
                y1 = y0 + cell_h
                draw.rectangle([x0, y0, x1, y1], fill=base)
                for step in range(0, cell_h, 12):
                    shade = tuple(max(0, min(255, channel + ((step + seed) % 30) - 15)) for channel in base)
                    draw.line([x0, y0 + step, x1, y0 + step // 2], fill=shade, width=2)
                draw.ellipse(
                    [x0 + cell_w * 0.18, y0 + cell_h * 0.18, x0 + cell_w * 0.82, y0 + cell_h * 0.82],
                    outline=tuple(min(255, c + 38) for c in base),
                    width=3,
                )
    else:
        for y in range(size):
            tone = int(24 + (y / size) * 45)
            draw.line([0, y, size, y], fill=(tone, tone + 3, tone + 8))
        for i in range(9):
            offset = (seed + i * 97) % 760
            x0 = 90 + (offset % 360)
            y0 = 90 + ((offset * 3) % 700)
            color = palette[(seed + i) % len(palette)]
            draw.rounded_rectangle([x0, y0, x0 + 360, y0 + 92], radius=18, outline=(230, 230, 220), width=3, fill=color)
            draw.line([x0 + 24, y0 + 46, x0 + 330, y0 + 46], fill=tuple(min(255, c + 50) for c in color), width=4)
        draw.rounded_rectangle([68, 68, 956, 956], radius=32, outline=(235, 235, 225), width=6)
    image = image.filter(ImageFilter.UnsharpMask(radius=1.1, percent=115, threshold=3))
    output = BytesIO()
    image.save(output, format="WEBP", quality=88, method=6)
    return output.getvalue()


def _cloudflare_object_key(*, slug: str, slot: str) -> str:
    file_stem = slug if slot == "hero" else f"{slug}-closing"
    now = datetime.now(timezone.utc)
    return f"assets/media/cloudflare/dongri-archive/{CLOUDFLARE_CATEGORY_LEAF}/{now:%Y}/{now:%m}/{slug}/{file_stem}.webp"


def _upload_pair_asset(db, *, blog: Blog, slug: str, category_key: str, slot: str, prompt: str, image_bytes: bytes, raw: dict[str, Any], artifact_dir: Path) -> GeneratedAsset:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    local_file = artifact_dir / f"{slot}.webp"
    local_file.write_bytes(image_bytes)

    blogger_key = build_r2_asset_object_key(
        profile_key=blog.profile_key,
        blog_id=blog.id,
        primary_language=blog.primary_language,
        blog_slug=blog.slug,
        editorial_category_key=category_key,
        editorial_category_label="Case Files",
        labels=["Case Files"],
        title=slug,
        summary=slug,
        post_slug=slug,
        asset_role=slot,
        content=image_bytes,
    )
    blogger_path, blogger_url, blogger_meta = save_public_binary(
        db,
        subdir="images/mystery",
        filename=f"{slug if slot == 'hero' else slug + '-closing'}.webp",
        content=image_bytes,
        object_key=blogger_key,
    )

    cloudflare_key = _cloudflare_object_key(slug=slug, slot=slot)
    cloudflare_url, cloudflare_payload, cloudflare_meta = upload_binary_to_cloudflare_r2(
        db,
        object_key=cloudflare_key,
        filename=f"{Path(cloudflare_key).name}",
        content=image_bytes,
    )
    return GeneratedAsset(
        slot=slot,
        prompt=prompt,
        bytes_value=image_bytes,
        blogger_url=blogger_url,
        blogger_object_key=blogger_key,
        cloudflare_url=cloudflare_url,
        cloudflare_object_key=cloudflare_key,
        local_path=blogger_path or str(local_file),
        metadata={
            "raw": raw,
            "blogger_delivery": blogger_meta,
            "cloudflare_upload": cloudflare_payload,
            "cloudflare_delivery": cloudflare_meta,
        },
    )


def _overwrite_existing_image_object(
    db,
    *,
    public_url: str,
    image_bytes: bytes,
    filename: str,
) -> dict[str, Any]:
    object_key = _object_key_from_public_url(public_url)
    if object_key.startswith("assets/the-midnight-archives/"):
        file_path, resolved_url, delivery_meta = save_public_binary(
            db,
            subdir="images/mystery",
            filename=Path(object_key).name,
            content=image_bytes,
            object_key=object_key,
        )
        return {
            "public_url": resolved_url,
            "object_key": object_key,
            "local_path": file_path,
            "delivery": delivery_meta,
            "upload_route": "mystery_save_public_binary",
        }
    if object_key.startswith("assets/media/cloudflare/"):
        resolved_url, upload_payload, delivery_meta = upload_binary_to_cloudflare_r2(
            db,
            object_key=object_key,
            filename=filename or Path(object_key).name,
            content=image_bytes,
        )
        return {
            "public_url": resolved_url,
            "object_key": object_key,
            "local_path": "",
            "delivery": delivery_meta,
            "upload_payload": upload_payload,
            "upload_route": "cloudflare_media_r2",
        }
    raise ValueError(f"unsupported_existing_image_object_key:{object_key}")


def _resolve_image_repair_targets(db, spec: ImagePromptSpec, *, timeout: float) -> dict[str, Any]:
    blogger_row = (
        db.execute(
            select(SyncedBloggerPost)
            .where(
                SyncedBloggerPost.blog_id == BLOGGER_BLOG_ID,
                or_(
                    SyncedBloggerPost.url.ilike(f"%{spec.blogger_slug}%"),
                    SyncedBloggerPost.title.ilike(f"%{spec.keyword.split()[0]}%"),
                ),
            )
            .order_by(SyncedBloggerPost.published_at.desc().nullslast(), SyncedBloggerPost.id.desc())
        )
        .scalars()
        .first()
    )
    article = (
        db.execute(
            select(Article)
            .where(
                Article.blog_id == BLOGGER_BLOG_ID,
                or_(Article.slug == spec.blogger_slug, Article.assembled_html.ilike(f"%{spec.blogger_slug}%")),
            )
            .order_by(Article.id.desc())
        )
        .scalars()
        .first()
    )
    cloudflare_row = (
        db.execute(
            select(SyncedCloudflarePost)
            .where(
                or_(
                    SyncedCloudflarePost.slug == spec.cloudflare_slug,
                    SyncedCloudflarePost.url.ilike(f"%{spec.cloudflare_slug}%"),
                    SyncedCloudflarePost.title.ilike(f"%{spec.keyword.split()[0]}%"),
                )
            )
            .order_by(SyncedCloudflarePost.published_at.desc().nullslast(), SyncedCloudflarePost.id.desc())
        )
        .scalars()
        .first()
    )
    if not blogger_row or not article or not cloudflare_row:
        return {
            "ok": False,
            "blogger_found": bool(blogger_row),
            "article_found": bool(article),
            "cloudflare_found": bool(cloudflare_row),
        }

    blogger_urls = _ordered_hero_closing_urls(
        _collect_existing_image_urls(
            live_url=str(blogger_row.url or ""),
            stored_content="\n".join(
                [
                    str(blogger_row.content_html or ""),
                    str(article.assembled_html or ""),
                    json.dumps(article.inline_media or [], ensure_ascii=False, default=str),
                    json.dumps(article.render_metadata or {}, ensure_ascii=False, default=str),
                ]
            ),
            timeout=timeout,
        )
    )

    cloudflare_meta = dict(cloudflare_row.render_metadata or {})
    cloudflare_seed = "\n".join(
        [
            str(cloudflare_row.thumbnail_url or ""),
            json.dumps(cloudflare_meta, ensure_ascii=False, default=str),
        ]
    )
    cloudflare_urls = _ordered_hero_closing_urls(
        _collect_existing_image_urls(live_url=str(cloudflare_row.url or ""), stored_content=cloudflare_seed, timeout=timeout)
    )
    return {
        "ok": len(blogger_urls) == 2 and len(cloudflare_urls) == 2,
        "blogger": blogger_row,
        "article": article,
        "cloudflare": cloudflare_row,
        "blogger_urls": blogger_urls,
        "cloudflare_urls": cloudflare_urls,
    }


def _repair_existing_images_for_topic(
    db,
    *,
    topic: dict[str, Any],
    artifact_dir: Path,
    timeout: float,
) -> dict[str, Any]:
    spec = _prompt_spec_by_key(str(topic.get("image_prompt_spec") or ""))
    targets = _resolve_image_repair_targets(db, spec, timeout=timeout)
    item: dict[str, Any] = {
        "topic": spec.keyword,
        "mode": "repair-existing-images",
        "artifact_dir": str(artifact_dir),
        "image_prompt_spec": spec.key,
    }
    if not targets.get("ok"):
        item.update({"status": "image_repair_target_not_resolved", "target_resolution": targets})
        return item

    image_dir = artifact_dir / "04-image"
    image_dir.mkdir(parents=True, exist_ok=True)
    prompts = {"hero": spec.hero_prompt, "closing": spec.closing_prompt}
    blogger_urls: list[str] = targets["blogger_urls"]
    cloudflare_urls: list[str] = targets["cloudflare_urls"]
    deliveries: list[dict[str, Any]] = []
    image_urls_by_slot = {"hero": (blogger_urls[0], cloudflare_urls[0]), "closing": (blogger_urls[1], cloudflare_urls[1])}

    for slot in ("hero", "closing"):
        prompt = prompts[slot]
        audit = _audit_image_prompt(prompt, spec=spec, slot=slot)
        _write_text(image_dir / f"{slot}-prompt.txt", prompt)
        _write_json(image_dir / f"{slot}-prompt-audit.json", audit)
        image_bytes, raw = _generate_image_bytes(
            db,
            slot=slot,
            prompt=prompt,
            slug=spec.blogger_slug,
            prompt_audit=audit,
            allow_fallback=False,
        )
        if bool(raw.get("fallback_used")):
            raise RuntimeError(f"fallback_used_blocked:{spec.key}:{slot}")
        local_file = image_dir / f"{slot}.webp"
        local_file.write_bytes(image_bytes)
        blogger_url, cloudflare_url = image_urls_by_slot[slot]
        blogger_delivery = _overwrite_existing_image_object(
            db,
            public_url=blogger_url,
            image_bytes=image_bytes,
            filename=f"{spec.blogger_slug if slot == 'hero' else spec.blogger_slug + '-closing'}.webp",
        )
        cloudflare_delivery = _overwrite_existing_image_object(
            db,
            public_url=cloudflare_url,
            image_bytes=image_bytes,
            filename=f"{spec.blogger_slug if slot == 'hero' else spec.blogger_slug + '-closing'}.webp",
        )
        blogger_probe = _probe(blogger_url, timeout=timeout)
        cloudflare_probe = _probe(cloudflare_url, timeout=timeout)
        delivery = {
            "slot": slot,
            "prompt": prompt,
            "prompt_audit_score": audit["score"],
            "prompt_audit": audit,
            "fallback_used": bool(raw.get("fallback_used")),
            "provider": raw.get("provider") or "runtime_image_provider",
            "semantic_keywords": list(spec.semantic_keywords),
            "local_path": str(local_file),
            "blogger_url": blogger_url,
            "blogger_object_key": blogger_delivery["object_key"],
            "blogger_probe": {
                "status_code": blogger_probe.get("status_code"),
                "content_type": blogger_probe.get("content_type"),
                "ok": bool(blogger_probe.get("ok")) and "image/webp" in str(blogger_probe.get("content_type", "")).lower(),
            },
            "cloudflare_url": cloudflare_url,
            "cloudflare_object_key": cloudflare_delivery["object_key"],
            "cloudflare_probe": {
                "status_code": cloudflare_probe.get("status_code"),
                "content_type": cloudflare_probe.get("content_type"),
                "ok": bool(cloudflare_probe.get("ok")) and "image/webp" in str(cloudflare_probe.get("content_type", "")).lower(),
            },
            "raw": raw,
        }
        deliveries.append(delivery)

    _write_json(image_dir / "image-delivery.json", deliveries)

    article: Article = targets["article"]
    cloudflare_row: SyncedCloudflarePost = targets["cloudflare"]
    article.image_collage_prompt = spec.hero_prompt
    article.inline_media = [
        {
            "slot": delivery["slot"],
            "image_url": delivery["blogger_url"],
            "object_key": delivery["blogger_object_key"],
            "prompt": delivery["prompt"],
            "prompt_audit_score": delivery["prompt_audit_score"],
            "fallback_used": delivery["fallback_used"],
            "provider": delivery["provider"],
            "semantic_keywords": delivery["semantic_keywords"],
        }
        for delivery in deliveries
    ]
    article.render_metadata = {
        **dict(article.render_metadata or {}),
        "image_prompt_repair": True,
        "image_prompt_audit": [
            {"slot": delivery["slot"], "score": delivery["prompt_audit_score"], "pass": delivery["prompt_audit"]["pass"]}
            for delivery in deliveries
        ],
        "image_slots": [
            {"slot": delivery["slot"], "url": delivery["blogger_url"], "object_key": delivery["blogger_object_key"]}
            for delivery in deliveries
        ],
    }
    cloudflare_row.thumbnail_url = deliveries[0]["cloudflare_url"]
    cloudflare_row.render_metadata = {
        **dict(cloudflare_row.render_metadata or {}),
        "image_prompt_repair": True,
        "image_prompt_audit": [
            {"slot": delivery["slot"], "score": delivery["prompt_audit_score"], "pass": delivery["prompt_audit"]["pass"]}
            for delivery in deliveries
        ],
        "image_slots": [
            {"slot": delivery["slot"], "url": delivery["cloudflare_url"], "object_key": delivery["cloudflare_object_key"]}
            for delivery in deliveries
        ],
    }
    db.add(article)
    db.add(cloudflare_row)
    db.commit()

    success = all(
        delivery["prompt_audit_score"] >= 80
        and not delivery["fallback_used"]
        and delivery["blogger_probe"]["ok"]
        and delivery["cloudflare_probe"]["ok"]
        for delivery in deliveries
    )
    item.update(
        {
            "status": "existing_images_repaired" if success else "existing_images_repair_failed",
            "blogger_url": targets["blogger"].url,
            "cloudflare_url": cloudflare_row.url,
            "hero_image_url": blogger_urls[0],
            "closing_image_url": blogger_urls[1],
            "deliveries": deliveries,
            "db_finalized": success,
        }
    )
    return item


def _insert_closing_before_last_h2(html: str, closing_url: str, title: str) -> str:
    figure = (
        '<figure data-bloggent-role="closing-figure" style="margin:30px 0;">'
        f'<img src="{escape(closing_url, quote=True)}" alt="{escape(title, quote=True)} visual summary" '
        'loading="lazy" decoding="async" style="width:100%;border-radius:20px;display:block;object-fit:cover;" />'
        "</figure>"
    )
    matches = list(re.finditer(r"<h2\b", html or "", flags=re.IGNORECASE))
    if len(matches) >= 2:
        idx = matches[-1].start()
        return f"{html[:idx]}{figure}\n{html[idx:]}"
    return f"{html}\n{figure}"


def _assemble_blogger_html(article: dict[str, Any], *, hero_url: str, closing_url: str) -> str:
    title = str(article.get("title") or "")
    body = str(article.get("html_article") or "")
    hero = (
        '<figure data-bloggent-role="hero-figure" style="margin:0 0 32px;">'
        f'<img src="{escape(hero_url, quote=True)}" alt="{escape(title, quote=True)}" '
        'fetchpriority="high" loading="eager" decoding="async" style="width:100%;border-radius:28px;display:block;object-fit:cover;" />'
        "</figure>"
    )
    return f"{hero}\n{_insert_closing_before_last_h2(body, closing_url, title)}"


def _assemble_cloudflare_markdown(article: dict[str, Any], *, hero_url: str, closing_url: str) -> str:
    title = str(article.get("title") or "")
    body = str(article.get("cloudflare_article_markdown") or "").strip()
    if not body:
        body = _strip_tags(str(article.get("html_article") or ""))
    hero = f"![{title}]({hero_url})"
    closing = f"![{title} visual summary]({closing_url})"
    parts = body.split("\n## ")
    if len(parts) >= 2:
        body = "\n## ".join(parts[:-1]) + "\n\n" + closing + "\n\n## " + parts[-1]
    else:
        body = body + "\n\n" + closing
    return f"{hero}\n\n{body.strip()}\n"


def _assemble_cloudflare_html(article: dict[str, Any], *, hero_url: str, closing_url: str) -> str:
    title = str(article.get("title") or "")
    body = str(article.get("html_article") or "")
    hero = (
        '<figure data-bloggent-role="hero-figure">'
        f'<img src="{escape(hero_url, quote=True)}" alt="{escape(title, quote=True)}" loading="eager" decoding="async" />'
        "</figure>"
    )
    return f"{hero}\n{_insert_closing_before_last_h2(body, closing_url, title)}"


def _publish_cloudflare(client: CloudflareIntegrationClient, *, category_id: str, article: dict[str, Any], markdown: str, hero_url: str, assets: list[GeneratedAsset]) -> dict[str, Any]:
    payload = _build_cloudflare_payload(
        category_id=category_id,
        article=article,
        markdown=markdown,
        hero_url=hero_url,
        image_slots=[
            {"slot": asset.slot, "url": asset.cloudflare_url, "object_key": asset.cloudflare_object_key}
            for asset in assets
        ],
    )
    created = client._request("POST", "/api/integrations/posts", json_payload={**payload, "status": "draft"}, timeout=120.0)
    post_id = str(created.get("id") or "").strip()
    if not post_id:
        raise RuntimeError(f"cloudflare_create_missing_id:{created}")
    return client._request("PUT", f"/api/integrations/posts/{post_id}", json_payload=payload, timeout=120.0)


def _build_cloudflare_payload(*, category_id: str, article: dict[str, Any], markdown: str, hero_url: str, image_slots: list[dict[str, Any]]) -> dict[str, Any]:
    seo_description = _normalize_seo_description(str(article.get("meta_description") or article.get("excerpt") or article["title"]))
    closing_url = ""
    for slot in image_slots:
        if str(slot.get("slot") or "") == "closing":
            closing_url = str(slot.get("url") or "").strip()
            break
    html_article = _assemble_cloudflare_html(article, hero_url=hero_url, closing_url=closing_url or hero_url)
    payload = {
        "title": article["title"],
        "slug": article["slug"],
        "content": markdown,
        "contentMarkdown": markdown,
        "markdown": markdown,
        "contentHtml": html_article,
        "bodyHtml": html_article,
        "html": html_article,
        "contentFormat": "markdown",
        "excerpt": article["excerpt"],
        "seoTitle": article["title"],
        "seoDescription": seo_description,
        "tagNames": article.get("labels") or [CLOUDFLARE_CATEGORY_LABEL],
        "coverImage": hero_url,
        "thumbnailUrl": hero_url,
        "thumbnail_url": hero_url,
        "heroImage": hero_url,
        "coverAlt": article["title"],
        "status": "published",
        "categoryId": category_id,
        "categorySlug": CLOUDFLARE_CATEGORY_LEAF,
        "metadata": {
            "article_pattern_id": article["article_pattern_id"],
            "article_pattern_version": PATTERN_VERSION,
            "image_slots": image_slots,
            "paired_publish_group": "mystery-cloudflare-blogger",
        },
    }
    return payload


def _normalize_seo_description(value: str) -> str:
    text = SPACE_RE.sub(" ", str(value or "").strip())
    if len(text) < 90:
        text = (
            f"{text} 기록, 증언, 가설, 반론을 분리해 사건의 핵심 쟁점과 아직 남은 의문을 정리한 분석입니다."
        ).strip()
    if len(text) < 90:
        text = f"{text} 미스테리아 스토리 아카이브 분석."
    return text[:170]


def _publish_blogger(db, *, blog: Blog, article: dict[str, Any], html: str) -> tuple[dict[str, Any], dict[str, Any]]:
    provider = get_blogger_provider(db, blog)
    labels = [str(item) for item in (article.get("labels") or ["Case Files"]) if str(item).strip()]
    return provider.publish(
        title=article["title"],
        content=html,
        labels=labels[:8],
        meta_description=article["meta_description"],
        slug=article["slug"],
        publish_mode=PublishMode.PUBLISH,
    )


def _probe(url: str, *, timeout: float) -> dict[str, Any]:
    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True)
        return {
            "url": url,
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "ok": response.status_code < 400,
            "text": response.text if "text/html" in response.headers.get("content-type", "") else "",
        }
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "status_code": 0, "content_type": "", "ok": False, "error": str(exc), "text": ""}


def _verify_live(url: str, image_urls: list[str], *, timeout: float) -> dict[str, Any]:
    if "dongriarchive.com/ko/post/" in str(url):
        browser_result = _verify_live_with_browser(url, image_urls, timeout=timeout)
        if browser_result:
            return browser_result
    page = _probe(url, timeout=timeout)
    html = str(page.get("text") or "")
    image_results = [_probe(image_url, timeout=timeout) for image_url in image_urls]
    page_image_count = _image_count(html)
    expected_image_count = _expected_article_image_count(html, image_urls)
    return {
        "published_url": url,
        "live_status": page["status_code"],
        "plain_text_length": _plain_len(html),
        "body_h1_count": max(0, _body_h1_count(html) - 1),
        "page_image_count": page_image_count,
        "expected_article_image_count": expected_image_count,
        "markdown_exposed": bool(MD_EXPOSED_RE.search(_strip_tags(html))),
        "raw_html_exposed": bool(RAW_HTML_TEXT_RE.search(_strip_tags(html))),
        "images": [
            {
                "url": result["url"],
                "status_code": result["status_code"],
                "content_type": result["content_type"],
                "ok": bool(result["ok"]) and "image/webp" in str(result["content_type"]).lower(),
            }
            for result in image_results
        ],
        "pass": (
            bool(page["ok"])
            and _plain_len(html) >= 3000
            and max(0, _body_h1_count(html) - 1) == 0
            and expected_image_count == len(image_urls) == 2
            and not bool(MD_EXPOSED_RE.search(_strip_tags(html)))
            and not bool(RAW_HTML_TEXT_RE.search(_strip_tags(html)))
            and all(bool(result["ok"]) and "image/webp" in str(result["content_type"]).lower() for result in image_results)
        ),
    }


def _verify_live_with_browser(url: str, image_urls: list[str], *, timeout: float) -> dict[str, Any] | None:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001
        return None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1365, "height": 900})
            response = page.goto(url, wait_until="networkidle", timeout=int(timeout * 1000))
            page.wait_for_timeout(1500)
            payload = page.evaluate(
                """() => {
                  const root = document.querySelector('article.detail-article') || document.querySelector('article') || document.querySelector('main') || document.body;
                  const text = root ? (root.innerText || '') : '';
                  const html = root ? (root.innerHTML || '') : '';
                  const imgs = Array.from(document.querySelectorAll('img')).map(img => img.currentSrc || img.src || '').filter(Boolean);
                  const h1 = root ? root.querySelectorAll('h1').length : 0;
                  return {text, html, imgs, h1};
                }"""
            )
            browser.close()
    except Exception:  # noqa: BLE001
        return None

    text = str(payload.get("text") or "")
    html = str(payload.get("html") or "")
    imgs = [str(item) for item in (payload.get("imgs") or []) if str(item).strip()]
    expected_image_count = sum(
        1 for image_url in image_urls if any(image_url == img or image_url in img for img in imgs)
    )
    image_results = [_probe(image_url, timeout=timeout) for image_url in image_urls]
    markdown_exposed = bool(MD_EXPOSED_RE.search(text))
    raw_html_exposed = bool(RAW_HTML_TEXT_RE.search(text))
    plain_text_length = len(SPACE_RE.sub("", _strip_tags(text)))
    return {
        "published_url": url,
        "live_status": response.status if response else 0,
        "plain_text_length": plain_text_length,
        "body_h1_count": max(0, int(payload.get("h1") or 0) - 1),
        "page_image_count": len(imgs),
        "expected_article_image_count": expected_image_count,
        "markdown_exposed": markdown_exposed,
        "raw_html_exposed": raw_html_exposed,
        "images": [
            {
                "url": result["url"],
                "status_code": result["status_code"],
                "content_type": result["content_type"],
                "ok": bool(result["ok"]) and "image/webp" in str(result["content_type"]).lower(),
            }
            for result in image_results
        ],
        "pass": (
            bool(response and response.status < 400)
            and plain_text_length >= 3000
            and max(0, int(payload.get("h1") or 0) - 1) == 0
            and expected_image_count == len(image_urls) == 2
            and not markdown_exposed
            and not raw_html_exposed
            and all(bool(result["ok"]) and "image/webp" in str(result["content_type"]).lower() for result in image_results)
        ),
    }


def _finalize_blogger_db(db, *, blog: Blog, topic_keyword: str, article_payload: dict[str, Any], html: str, summary: dict[str, Any], raw_payload: dict[str, Any], assets: list[GeneratedAsset], scores: dict[str, int]) -> dict[str, Any]:
    topic = Topic(
        blog_id=blog.id,
        keyword=topic_keyword,
        reason="paired mystery publish live-verified",
        trend_score=0.0,
        source="paired_mystery_pipeline",
        locale="en-US",
        editorial_category_key="case-files",
        editorial_category_label="Case Files",
    )
    db.add(topic)
    db.flush()
    job = Job(
        blog_id=blog.id,
        topic_id=topic.id,
        keyword_snapshot=topic_keyword,
        status=JobStatus.COMPLETED,
        publish_mode=PublishMode.PUBLISH,
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
        raw_prompts={"source": "publish_paired_mystery_topics", "paired_publish": True},
        raw_responses={"article": article_payload, "assets": [asset.metadata for asset in assets]},
    )
    db.add(job)
    db.flush()
    article = Article(
        job_id=job.id,
        blog_id=blog.id,
        topic_id=topic.id,
        title=article_payload["title"],
        meta_description=article_payload["meta_description"],
        labels=article_payload.get("labels") or ["Case Files"],
        slug=article_payload["slug"],
        excerpt=article_payload["excerpt"],
        html_article=article_payload["html_article"],
        faq_section=article_payload.get("faq_section") or [],
        image_collage_prompt=article_payload["hero_image_prompt"],
        inline_media=[
            {
                "slot": asset.slot,
                "image_url": asset.blogger_url,
                "object_key": asset.blogger_object_key,
                "prompt": asset.prompt,
            }
            for asset in assets
        ],
        assembled_html=html,
        article_pattern_id=article_payload["article_pattern_id"],
        article_pattern_version=PATTERN_VERSION,
        render_metadata={
            "paired_publish_group": "mystery-cloudflare-blogger",
            "seo_keyword_map": article_payload.get("seo_keyword_map") or {},
            "image_slots": [
                {"slot": asset.slot, "url": asset.blogger_url, "object_key": asset.blogger_object_key}
                for asset in assets
            ],
            "finalized_after_live_verify": True,
        },
        editorial_category_key="case-files",
        editorial_category_label="Case Files",
        quality_seo_score=scores["seo_score"],
        quality_geo_score=scores["geo_score"],
        quality_ctr_score=scores["ctr_score"],
        quality_lighthouse_score=scores["lighthouse_score"],
        quality_status="pass",
        quality_last_audited_at=datetime.now(timezone.utc),
    )
    db.add(article)
    db.flush()
    hero = next(asset for asset in assets if asset.slot == "hero")
    image = Image(
        job_id=job.id,
        article_id=article.id,
        prompt=hero.prompt,
        file_path=hero.local_path,
        public_url=hero.blogger_url,
        width=1024,
        height=1024,
        provider="openai",
        image_metadata={
            "slot": "hero",
            "object_key": hero.blogger_object_key,
            "closing": [
                {"url": asset.blogger_url, "object_key": asset.blogger_object_key}
                for asset in assets
                if asset.slot == "closing"
            ],
            "delivery": hero.metadata.get("blogger_delivery") or {},
        },
    )
    db.add(image)
    db.flush()
    article.image = image
    db.add(article)
    db.flush()
    blogger_post = upsert_article_blogger_post(db, article=article, summary=summary, raw_payload=raw_payload)
    db.commit()
    return {"topic_id": topic.id, "job_id": job.id, "article_id": article.id, "blogger_post_id": blogger_post.id}


def _finalize_blogger_db_if_missing(
    db,
    *,
    blog: Blog,
    topic_keyword: str,
    article_payload: dict[str, Any],
    html: str,
    summary: dict[str, Any],
    raw_payload: dict[str, Any],
    assets: list[GeneratedAsset],
    scores: dict[str, int],
) -> dict[str, Any]:
    existing = (
        db.execute(
            select(Article)
            .where(Article.blog_id == blog.id, Article.slug == article_payload["slug"])
            .order_by(Article.id.desc())
        )
        .scalars()
        .first()
    )
    if existing is None:
        return _finalize_blogger_db(
            db,
            blog=blog,
            topic_keyword=topic_keyword,
            article_payload=article_payload,
            html=html,
            summary=summary,
            raw_payload=raw_payload,
            assets=assets,
            scores=scores,
        )

    existing.title = article_payload["title"]
    existing.meta_description = article_payload["meta_description"]
    existing.labels = article_payload.get("labels") or ["Case Files"]
    existing.excerpt = article_payload["excerpt"]
    existing.html_article = article_payload["html_article"]
    existing.faq_section = article_payload.get("faq_section") or []
    existing.image_collage_prompt = article_payload["hero_image_prompt"]
    existing.inline_media = [
        {
            "slot": asset.slot,
            "image_url": asset.blogger_url,
            "object_key": asset.blogger_object_key,
            "prompt": asset.prompt,
        }
        for asset in assets
    ]
    existing.assembled_html = html
    existing.article_pattern_id = article_payload["article_pattern_id"]
    existing.article_pattern_version = PATTERN_VERSION
    existing.render_metadata = {
        **dict(existing.render_metadata or {}),
        "paired_publish_group": "mystery-cloudflare-blogger",
        "seo_keyword_map": article_payload.get("seo_keyword_map") or {},
        "image_slots": [
            {"slot": asset.slot, "url": asset.blogger_url, "object_key": asset.blogger_object_key}
            for asset in assets
        ],
        "finalized_after_live_verify": True,
    }
    existing.quality_seo_score = scores["seo_score"]
    existing.quality_geo_score = scores["geo_score"]
    existing.quality_ctr_score = scores["ctr_score"]
    existing.quality_lighthouse_score = scores["lighthouse_score"]
    existing.quality_status = "pass"
    existing.quality_last_audited_at = datetime.now(timezone.utc)
    db.add(existing)
    blogger_post = upsert_article_blogger_post(db, article=existing, summary=summary, raw_payload=raw_payload)
    db.commit()
    return {"article_id": existing.id, "blogger_post_id": blogger_post.id, "updated_existing_article": True}


def _finalize_cloudflare_db(db, *, remote_id: str, article_payload: dict[str, Any], live: dict[str, Any], assets: list[GeneratedAsset], scores: dict[str, int]) -> dict[str, Any]:
    sync_result = sync_cloudflare_posts(db, include_non_published=True)
    row = (
        db.execute(select(SyncedCloudflarePost).where(SyncedCloudflarePost.remote_post_id == remote_id))
        .scalars()
        .one_or_none()
    )
    if row:
        row.article_pattern_id = article_payload["article_pattern_id"]
        row.article_pattern_version = PATTERN_VERSION
        row.seo_score = scores["seo_score"]
        row.geo_score = scores["geo_score"]
        row.lighthouse_score = scores["lighthouse_score"]
        row.quality_status = "pass"
        row.render_metadata = {
            **dict(row.render_metadata or {}),
            "paired_publish_group": "mystery-cloudflare-blogger",
            "live_verify": live,
            "image_slots": [
                {"slot": asset.slot, "url": asset.cloudflare_url, "object_key": asset.cloudflare_object_key}
                for asset in assets
            ],
            "finalized_after_live_verify": True,
        }
        db.add(row)
        db.commit()
    return {
        "sync_count": sync_result.get("count") if isinstance(sync_result, dict) else None,
        "synced_cloudflare_post_id": row.id if row else None,
    }


def _sync_existing_verified_pair(
    db,
    *,
    blog: Blog,
    cloudflare_remote_id: str,
    cloudflare_article: dict[str, Any],
    cloudflare_live: dict[str, Any],
    cloudflare_scores: dict[str, int],
) -> dict[str, Any]:
    blogger_sync = sync_blogger_posts_for_blog(db, blog)
    cloudflare_sync = sync_cloudflare_posts(db, include_non_published=True)
    row = (
        db.execute(select(SyncedCloudflarePost).where(SyncedCloudflarePost.remote_post_id == cloudflare_remote_id))
        .scalars()
        .one_or_none()
    )
    if row:
        row.article_pattern_id = cloudflare_article["article_pattern_id"]
        row.article_pattern_version = PATTERN_VERSION
        row.seo_score = cloudflare_scores["seo_score"]
        row.geo_score = cloudflare_scores["geo_score"]
        row.lighthouse_score = cloudflare_scores["lighthouse_score"]
        row.quality_status = "pass"
        row.render_metadata = {
            **dict(row.render_metadata or {}),
            "paired_publish_group": "mystery-cloudflare-blogger",
            "existing_post_repair": True,
            "live_verify": cloudflare_live,
            "finalized_after_live_verify": True,
        }
        db.add(row)
    db.commit()
    return {
        "blogger_sync_count": blogger_sync.get("count") if isinstance(blogger_sync, dict) else None,
        "cloudflare_sync_count": cloudflare_sync.get("count") if isinstance(cloudflare_sync, dict) else None,
        "synced_cloudflare_post_id": row.id if row else None,
    }


def _repair_existing_topic(
    db,
    *,
    blog: Blog,
    client: CloudflareIntegrationClient,
    cloudflare_category: dict[str, Any],
    cloudflare_posts: list[dict[str, Any]],
    topic: dict[str, Any],
    artifact_dir: Path,
    values: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    keyword = str(topic.get("keyword") or topic.get("topic") or "").strip()
    proposed_slug = _safe_slug(keyword)
    duplicate_gate = _duplicate_gate(db, keyword=keyword, proposed_slug=proposed_slug, cloudflare_posts=cloudflare_posts)
    item: dict[str, Any] = {
        "topic": keyword,
        "duplicate_gate": duplicate_gate,
        "artifact_dir": str(artifact_dir),
        "mode": "repair-existing-today",
    }
    if duplicate_gate["status"] != "blocked":
        item["status"] = "existing_post_not_found_no_create"
        return item

    blogger_target = _resolve_existing_blogger_target(db, topic, duplicate_gate)
    cloudflare_target = _resolve_existing_cloudflare_target(client, topic, duplicate_gate)
    if not blogger_target or not cloudflare_target:
        item.update(
            {
                "status": "existing_pair_not_resolved_no_create",
                "blogger_found": bool(blogger_target),
                "cloudflare_found": bool(cloudflare_target),
            }
        )
        return item

    cloudflare_url = str(cloudflare_target.get("publicUrl") or cloudflare_target.get("url") or "").strip()
    cloudflare_remote_id = str(cloudflare_target.get("id") or cloudflare_target.get("remote_id") or "").strip()
    blogger_url = str(blogger_target.url or "").strip()
    blogger_remote_id = str(blogger_target.remote_post_id or "").strip()

    blogger_images = _collect_existing_image_urls(live_url=blogger_url, stored_content=blogger_target.content_html, timeout=timeout)
    cloudflare_images = _collect_existing_image_urls(
        live_url=cloudflare_url,
        stored_content=str(cloudflare_target.get("content") or ""),
        timeout=timeout,
    )
    if len(blogger_images) != 2 or len(cloudflare_images) != 2:
        item.update(
            {
                "status": "missing_existing_two_images_no_update",
                "blogger_url": blogger_url,
                "cloudflare_url": cloudflare_url,
                "blogger_existing_images": blogger_images,
                "cloudflare_existing_images": cloudflare_images,
            }
        )
        return item

    planner, planner_raw = _generate_planner(db, keyword=keyword, values=values)
    _write_json(artifact_dir / "01-planner" / "planner-output.json", planner)
    _write_json(artifact_dir / "01-planner" / "planner-raw.json", planner_raw)

    cloudflare_article, cloudflare_raw, cloudflare_prompt = _generate_article(
        db,
        keyword=keyword,
        planner=planner,
        prompt_path=CLOUDFLARE_PROMPT_ROOT / "article_generation.md",
        locale="ko",
        values=values,
    )
    blogger_article, blogger_raw, blogger_prompt = _generate_article(
        db,
        keyword=keyword,
        planner=planner,
        prompt_path=BLOGGER_PROMPT_ROOT / "mystery_article_generation.md",
        locale="en",
        values=values,
    )
    cloudflare_article["slug"] = str(cloudflare_target.get("slug") or cloudflare_article["slug"]).strip()
    blogger_article["slug"] = _safe_slug(blogger_url.rstrip("/").split("/")[-1].removesuffix(".html") or blogger_article["slug"])
    _write_text(artifact_dir / "02-cloudflare" / "article-prompt.md", cloudflare_prompt)
    _write_json(artifact_dir / "02-cloudflare" / "article-output.json", cloudflare_article)
    _write_json(artifact_dir / "02-cloudflare" / "article-raw.json", cloudflare_raw)
    _write_text(artifact_dir / "02-blogger" / "article-prompt.md", blogger_prompt)
    _write_json(artifact_dir / "02-blogger" / "article-output.json", blogger_article)
    _write_json(artifact_dir / "02-blogger" / "article-raw.json", blogger_raw)

    contract_errors = {
        "cloudflare": _validate_article_contract(cloudflare_article, locale="ko"),
        "blogger": _validate_article_contract(blogger_article, locale="en"),
    }
    if contract_errors["cloudflare"] or contract_errors["blogger"]:
        item.update({"status": "article_contract_failed_no_update", "contract_errors": contract_errors})
        return item

    cloudflare_markdown = _assemble_cloudflare_markdown(
        cloudflare_article,
        hero_url=cloudflare_images[0],
        closing_url=cloudflare_images[1],
    )
    blogger_html = _assemble_blogger_html(
        blogger_article,
        hero_url=blogger_images[0],
        closing_url=blogger_images[1],
    )
    _write_text(artifact_dir / "05-html" / "cloudflare-payload.md", cloudflare_markdown)
    _write_text(artifact_dir / "05-html" / "blogger-assembled.html", blogger_html)

    cloudflare_payload = _build_cloudflare_payload(
        category_id=str(cloudflare_category.get("id") or CLOUDFLARE_CATEGORY_ID_FALLBACK),
        article=cloudflare_article,
        markdown=cloudflare_markdown,
        hero_url=cloudflare_images[0],
        image_slots=[
            {"slot": "hero", "url": cloudflare_images[0]},
            {"slot": "closing", "url": cloudflare_images[1]},
        ],
    )
    cloudflare_updated = client.update_post(cloudflare_remote_id, cloudflare_payload)
    blogger_provider = get_blogger_provider(db, blog)
    blogger_summary, blogger_raw_payload = blogger_provider.update_post(
        post_id=blogger_remote_id,
        title=blogger_article["title"],
        content=blogger_html,
        labels=[str(item) for item in (blogger_article.get("labels") or ["Case Files"]) if str(item).strip()][:8],
        meta_description=blogger_article["meta_description"],
    )
    _write_json(artifact_dir / "06-publish" / "cloudflare-update-summary.json", cloudflare_updated)
    _write_json(artifact_dir / "06-publish" / "blogger-update-summary.json", blogger_summary)
    _write_json(artifact_dir / "06-publish" / "blogger-update-raw.json", blogger_raw_payload)

    cloudflare_live = _verify_live(cloudflare_url, cloudflare_images, timeout=timeout)
    blogger_live = _verify_live(blogger_url, blogger_images, timeout=timeout)
    _write_json(artifact_dir / "07-live" / "live-validation.json", {"cloudflare": cloudflare_live, "blogger": blogger_live})
    cloudflare_scores = _score_article(cloudflare_article)
    blogger_scores = _score_article(blogger_article)
    _write_json(artifact_dir / "08-audit" / "scores.json", {"cloudflare": cloudflare_scores, "blogger": blogger_scores})

    if not cloudflare_live["pass"] or not blogger_live["pass"]:
        item.update(
            {
                "status": "partial_failed_existing_updated_not_finalized",
                "cloudflare_url": cloudflare_url,
                "blogger_url": blogger_url,
                "cloudflare_live": cloudflare_live,
                "blogger_live": blogger_live,
                "cloudflare_scores": cloudflare_scores,
                "blogger_scores": blogger_scores,
                "db_finalized": False,
            }
        )
        return item

    db_result = _sync_existing_verified_pair(
        db,
        blog=blog,
        cloudflare_remote_id=cloudflare_remote_id,
        cloudflare_article=cloudflare_article,
        cloudflare_live=cloudflare_live,
        cloudflare_scores=cloudflare_scores,
    )
    _write_json(artifact_dir / "09-db" / "existing-repair-db-sync.json", db_result)
    item.update(
        {
            "status": "existing_repaired_live_verified",
            "cloudflare_url": cloudflare_url,
            "blogger_url": blogger_url,
            "hero_image_url": blogger_images[0],
            "closing_image_url": blogger_images[1],
            "cloudflare_scores": cloudflare_scores,
            "blogger_scores": blogger_scores,
            "db": db_result,
            "db_finalized": True,
        }
    )
    return item


def _complete_existing_cloudflare_topic(
    db,
    *,
    blog: Blog,
    client: CloudflareIntegrationClient,
    cloudflare_category: dict[str, Any],
    cloudflare_posts: list[dict[str, Any]],
    topic: dict[str, Any],
    artifact_dir: Path,
    values: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    keyword = str(topic.get("keyword") or topic.get("topic") or "").strip()
    cloudflare_slug = str(topic.get("cloudflare_slug") or "").strip()
    duplicate_gate = _duplicate_gate(db, keyword=keyword, proposed_slug=cloudflare_slug or _safe_slug(keyword), cloudflare_posts=cloudflare_posts)
    item: dict[str, Any] = {
        "topic": keyword,
        "mode": "complete-existing-cloudflare",
        "duplicate_gate": duplicate_gate,
        "artifact_dir": str(artifact_dir),
    }

    cloudflare_target = _resolve_existing_cloudflare_target(client, topic, duplicate_gate)
    if not cloudflare_target:
        item["status"] = "cloudflare_existing_post_not_found_no_create"
        return item

    cloudflare_remote_id = str(cloudflare_target.get("id") or cloudflare_target.get("remote_id") or topic.get("cloudflare_remote_post_id") or "").strip()
    cloudflare_url = str(cloudflare_target.get("publicUrl") or cloudflare_target.get("url") or topic.get("cloudflare_url") or "").strip()
    if not cloudflare_remote_id or not cloudflare_url:
        item.update({"status": "cloudflare_existing_identity_incomplete", "cloudflare_target": cloudflare_target})
        return item

    blogger_target = _resolve_blogger_counterpart(db, cloudflare_slug=cloudflare_slug or str(cloudflare_target.get("slug") or ""), keyword=keyword)
    planner, planner_raw = _generate_planner(db, keyword=keyword, values=values)
    _write_json(artifact_dir / "01-planner" / "planner-output.json", planner)
    _write_json(artifact_dir / "01-planner" / "planner-raw.json", planner_raw)

    cloudflare_article, cloudflare_raw, cloudflare_prompt = _generate_article(
        db,
        keyword=keyword,
        planner=planner,
        prompt_path=CLOUDFLARE_PROMPT_ROOT / "article_generation.md",
        locale="ko",
        values=values,
    )
    blogger_article, blogger_raw, blogger_prompt = _generate_article(
        db,
        keyword=keyword,
        planner=planner,
        prompt_path=BLOGGER_PROMPT_ROOT / "mystery_article_generation.md",
        locale="en",
        values=values,
    )
    cloudflare_article["slug"] = str(cloudflare_target.get("slug") or cloudflare_slug or cloudflare_article["slug"]).strip()
    if blogger_target:
        blogger_article["slug"] = _safe_slug(str(blogger_target.url or "").rstrip("/").split("/")[-1].removesuffix(".html") or blogger_article["slug"])
    _write_text(artifact_dir / "02-cloudflare" / "article-prompt.md", cloudflare_prompt)
    _write_json(artifact_dir / "02-cloudflare" / "article-output.json", cloudflare_article)
    _write_json(artifact_dir / "02-cloudflare" / "article-raw.json", cloudflare_raw)
    _write_text(artifact_dir / "02-blogger" / "article-prompt.md", blogger_prompt)
    _write_json(artifact_dir / "02-blogger" / "article-output.json", blogger_article)
    _write_json(artifact_dir / "02-blogger" / "article-raw.json", blogger_raw)

    contract_errors = {
        "cloudflare": _validate_article_contract(cloudflare_article, locale="ko"),
        "blogger": _validate_article_contract(blogger_article, locale="en"),
    }
    if contract_errors["cloudflare"] or contract_errors["blogger"]:
        item.update({"status": "article_contract_failed_no_publish", "contract_errors": contract_errors})
        return item

    shared_slug = _safe_slug(blogger_article.get("slug") or cloudflare_article.get("slug") or keyword)
    assets: list[GeneratedAsset] = []
    for slot, prompt_key in (("hero", "hero_image_prompt"), ("closing", "closing_image_prompt")):
        prompt = str(blogger_article.get(prompt_key) or cloudflare_article.get(prompt_key) or "").strip()
        _write_text(artifact_dir / "03-image" / f"{slot}-prompt.txt", prompt)
        image_bytes, image_raw = _generate_image_bytes(db, slot=slot, prompt=prompt, slug=shared_slug)
        assets.append(
            _upload_pair_asset(
                db,
                blog=blog,
                slug=shared_slug,
                category_key="casefile",
                slot=slot,
                prompt=prompt,
                image_bytes=image_bytes,
                raw=image_raw,
                artifact_dir=artifact_dir / "04-image",
            )
        )
    _write_json(
        artifact_dir / "04-image" / "image-delivery.json",
        [
            {
                "slot": asset.slot,
                "blogger_url": asset.blogger_url,
                "blogger_object_key": asset.blogger_object_key,
                "cloudflare_url": asset.cloudflare_url,
                "cloudflare_object_key": asset.cloudflare_object_key,
            }
            for asset in assets
        ],
    )

    hero = next(asset for asset in assets if asset.slot == "hero")
    closing = next(asset for asset in assets if asset.slot == "closing")
    cloudflare_markdown = _assemble_cloudflare_markdown(
        cloudflare_article,
        hero_url=hero.cloudflare_url,
        closing_url=closing.cloudflare_url,
    )
    blogger_html = _assemble_blogger_html(
        blogger_article,
        hero_url=hero.blogger_url,
        closing_url=closing.blogger_url,
    )
    _write_text(artifact_dir / "05-html" / "cloudflare-payload.md", cloudflare_markdown)
    _write_text(artifact_dir / "05-html" / "blogger-assembled.html", blogger_html)

    cloudflare_payload = _build_cloudflare_payload(
        category_id=str(cloudflare_category.get("id") or CLOUDFLARE_CATEGORY_ID_FALLBACK),
        article=cloudflare_article,
        markdown=cloudflare_markdown,
        hero_url=hero.cloudflare_url,
        image_slots=[
            {"slot": asset.slot, "url": asset.cloudflare_url, "object_key": asset.cloudflare_object_key}
            for asset in assets
        ],
    )
    cloudflare_updated = client.update_post(cloudflare_remote_id, cloudflare_payload)
    if blogger_target:
        blogger_provider = get_blogger_provider(db, blog)
        blogger_summary, blogger_raw_payload = blogger_provider.update_post(
            post_id=str(blogger_target.remote_post_id),
            title=blogger_article["title"],
            content=blogger_html,
            labels=[str(label) for label in (blogger_article.get("labels") or ["Case Files"]) if str(label).strip()][:8],
            meta_description=blogger_article["meta_description"],
        )
        blogger_action = "updated_existing"
    else:
        blogger_summary, blogger_raw_payload = _publish_blogger(db, blog=blog, article=blogger_article, html=blogger_html)
        blogger_action = "created_counterpart"
    _write_json(artifact_dir / "06-publish" / "cloudflare-update-summary.json", cloudflare_updated)
    _write_json(artifact_dir / "06-publish" / "blogger-summary.json", blogger_summary)
    _write_json(artifact_dir / "06-publish" / "blogger-raw.json", blogger_raw_payload)

    blogger_url = str(blogger_summary.get("url") or (blogger_target.url if blogger_target else "") or "").strip()
    cloudflare_live = _verify_live(cloudflare_url, [asset.cloudflare_url for asset in assets], timeout=timeout)
    blogger_live = _verify_live(blogger_url, [asset.blogger_url for asset in assets], timeout=timeout)
    _write_json(artifact_dir / "07-live" / "live-validation.json", {"cloudflare": cloudflare_live, "blogger": blogger_live})
    cloudflare_scores = _score_article(cloudflare_article)
    blogger_scores = _score_article(blogger_article)
    _write_json(artifact_dir / "08-audit" / "scores.json", {"cloudflare": cloudflare_scores, "blogger": blogger_scores})

    if not cloudflare_live["pass"] or not blogger_live["pass"]:
        item.update(
            {
                "status": "partial_failed",
                "cloudflare_url": cloudflare_url,
                "blogger_url": blogger_url,
                "blogger_action": blogger_action,
                "cloudflare_live": cloudflare_live,
                "blogger_live": blogger_live,
                "cloudflare_scores": cloudflare_scores,
                "blogger_scores": blogger_scores,
                "db_finalized": False,
            }
        )
        return item

    blogger_db = _finalize_blogger_db_if_missing(
        db,
        blog=blog,
        topic_keyword=keyword,
        article_payload=blogger_article,
        html=blogger_html,
        summary=blogger_summary,
        raw_payload=blogger_raw_payload,
        assets=assets,
        scores=blogger_scores,
    )
    db_result = _sync_existing_verified_pair(
        db,
        blog=blog,
        cloudflare_remote_id=cloudflare_remote_id,
        cloudflare_article=cloudflare_article,
        cloudflare_live=cloudflare_live,
        cloudflare_scores=cloudflare_scores,
    )
    final_db = {"blogger": blogger_db, "sync": db_result}
    _write_json(artifact_dir / "09-db" / "complete-existing-cloudflare-db-sync.json", final_db)
    item.update(
        {
            "status": "completed_existing_cloudflare_live_verified",
            "cloudflare_url": cloudflare_url,
            "blogger_url": blogger_url,
            "blogger_action": blogger_action,
            "hero_image_url": hero.blogger_url,
            "closing_image_url": closing.blogger_url,
            "cloudflare_hero_image_url": hero.cloudflare_url,
            "cloudflare_closing_image_url": closing.cloudflare_url,
            "cloudflare_scores": cloudflare_scores,
            "blogger_scores": blogger_scores,
            "cloudflare_live": cloudflare_live,
            "blogger_live": blogger_live,
            "db": final_db,
            "db_finalized": True,
        }
    )
    return item


def run(args: argparse.Namespace) -> dict[str, Any]:
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    artifact_root = RUNTIME_ROOT / "paired-runs" / run_id
    artifact_root.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as db:
        values = get_settings_map(db)
        blog = _require_blogger_blog(db)
        cloudflare_auth_error = ""
        client: CloudflareIntegrationClient | None = None
        cloudflare_category: dict[str, Any] = {
            "id": CLOUDFLARE_CATEGORY_ID_FALLBACK,
            "slug": CLOUDFLARE_CATEGORY_LEAF,
            "name": CLOUDFLARE_CATEGORY_LABEL,
        }
        cloudflare_posts: list[dict[str, Any]] = []
        try:
            client = CloudflareIntegrationClient.from_db(db)
            cloudflare_category = _resolve_cloudflare_category(client)
            cloudflare_posts = client.list_posts()
        except Exception as exc:  # noqa: BLE001
            cloudflare_auth_error = str(exc)
            if args.mode in {"apply", "repair-existing-today", "complete-existing-cloudflare"}:
                raise RuntimeError(f"cloudflare_integration_required_for_{args.mode}:{cloudflare_auth_error}") from exc
        topics = _load_topics(args.topics_file, int(args.topic_count), mode=args.mode, db=db)
        if args.mode in {"repair-existing-today", "complete-existing-cloudflare"}:
            sync_blogger_posts_for_blog(db, blog)

        results: list[dict[str, Any]] = []
        for index, topic in enumerate(topics, start=1):
            keyword = str(topic.get("keyword") or topic.get("topic") or "").strip()
            if not keyword:
                continue
            topic_dir = artifact_root / f"{index:02d}-{_safe_slug(keyword)}"
            topic_dir.mkdir(parents=True, exist_ok=True)
            if args.mode == "repair-existing-images":
                item = _repair_existing_images_for_topic(
                    db,
                    topic=topic,
                    artifact_dir=topic_dir,
                    timeout=float(args.timeout),
                )
                _write_json(topic_dir / "result.json", item)
                results.append(item)
                continue
            if args.mode == "repair-existing-today":
                if client is None:
                    raise RuntimeError("cloudflare_client_missing_for_existing_repair")
                item = _repair_existing_topic(
                    db,
                    blog=blog,
                    client=client,
                    cloudflare_category=cloudflare_category,
                    cloudflare_posts=cloudflare_posts,
                    topic=topic,
                    artifact_dir=topic_dir,
                    values=values,
                    timeout=float(args.timeout),
                )
                _write_json(topic_dir / "result.json", item)
                results.append(item)
                continue
            if args.mode == "complete-existing-cloudflare":
                if client is None:
                    raise RuntimeError("cloudflare_client_missing_for_existing_cloudflare_completion")
                item = _complete_existing_cloudflare_topic(
                    db,
                    blog=blog,
                    client=client,
                    cloudflare_category=cloudflare_category,
                    cloudflare_posts=cloudflare_posts,
                    topic=topic,
                    artifact_dir=topic_dir,
                    values=values,
                    timeout=float(args.timeout),
                )
                _write_json(topic_dir / "result.json", item)
                results.append(item)
                continue

            proposed_slug = _safe_slug(keyword)
            duplicate_gate = _duplicate_gate(db, keyword=keyword, proposed_slug=proposed_slug, cloudflare_posts=cloudflare_posts)
            item: dict[str, Any] = {
                "topic": keyword,
                "reason": topic.get("reason") or "",
                "trend_score": topic.get("trend_score") or 0,
                "duplicate_gate": duplicate_gate,
                "status": "planned",
                "artifact_dir": str(topic_dir),
            }
            _write_json(topic_dir / "00-manifest" / "manifest.json", item)
            if duplicate_gate["status"] != "pass":
                item["status"] = "blocked_duplicate"
                results.append(item)
                continue

            if args.mode == "dry-run":
                item["status"] = "dry_run_ready"
                item["planned_contract"] = {
                    "paired_publish": True,
                    "article_pattern_version": PATTERN_VERSION,
                    "image_slots": ["hero", "closing"],
                    "remote_publish": False,
                    "db_finalize": False,
                }
                results.append(item)
                continue

            planner, planner_raw = _generate_planner(db, keyword=keyword, values=values)
            _write_json(topic_dir / "01-planner" / "planner-output.json", planner)
            _write_json(topic_dir / "01-planner" / "planner-raw.json", planner_raw)

            cloudflare_article, cloudflare_raw, cloudflare_prompt = _generate_article(
                db,
                keyword=keyword,
                planner=planner,
                prompt_path=CLOUDFLARE_PROMPT_ROOT / "article_generation.md",
                locale="ko",
                values=values,
            )
            blogger_article, blogger_raw, blogger_prompt = _generate_article(
                db,
                keyword=keyword,
                planner=planner,
                prompt_path=BLOGGER_PROMPT_ROOT / "mystery_article_generation.md",
                locale="en",
                values=values,
            )
            _write_text(topic_dir / "02-cloudflare" / "article-prompt.md", cloudflare_prompt)
            _write_json(topic_dir / "02-cloudflare" / "article-output.json", cloudflare_article)
            _write_json(topic_dir / "02-cloudflare" / "article-raw.json", cloudflare_raw)
            _write_text(topic_dir / "02-blogger" / "article-prompt.md", blogger_prompt)
            _write_json(topic_dir / "02-blogger" / "article-output.json", blogger_article)
            _write_json(topic_dir / "02-blogger" / "article-raw.json", blogger_raw)

            contract_errors = {
                "cloudflare": _validate_article_contract(cloudflare_article, locale="ko"),
                "blogger": _validate_article_contract(blogger_article, locale="en"),
            }
            if contract_errors["cloudflare"] or contract_errors["blogger"]:
                item.update({"status": "article_contract_failed", "contract_errors": contract_errors})
                results.append(item)
                continue

            shared_slug = _safe_slug(blogger_article.get("slug") or cloudflare_article.get("slug") or keyword)
            assets: list[GeneratedAsset] = []
            for slot, prompt_key in (("hero", "hero_image_prompt"), ("closing", "closing_image_prompt")):
                prompt = str(blogger_article.get(prompt_key) or cloudflare_article.get(prompt_key) or "").strip()
                _write_text(topic_dir / "03-image" / f"{slot}-prompt.txt", prompt)
                image_bytes, image_raw = _generate_image_bytes(db, slot=slot, prompt=prompt, slug=shared_slug)
                asset = _upload_pair_asset(
                    db,
                    blog=blog,
                    slug=shared_slug,
                    category_key="casefile",
                    slot=slot,
                    prompt=prompt,
                    image_bytes=image_bytes,
                    raw=image_raw,
                    artifact_dir=topic_dir / "04-image",
                )
                assets.append(asset)
            _write_json(
                topic_dir / "04-image" / "image-delivery.json",
                [
                    {
                        "slot": asset.slot,
                        "blogger_url": asset.blogger_url,
                        "blogger_object_key": asset.blogger_object_key,
                        "cloudflare_url": asset.cloudflare_url,
                        "cloudflare_object_key": asset.cloudflare_object_key,
                    }
                    for asset in assets
                ],
            )

            hero = next(asset for asset in assets if asset.slot == "hero")
            closing = next(asset for asset in assets if asset.slot == "closing")
            cloudflare_markdown = _assemble_cloudflare_markdown(
                cloudflare_article,
                hero_url=hero.cloudflare_url,
                closing_url=closing.cloudflare_url,
            )
            blogger_html = _assemble_blogger_html(
                blogger_article,
                hero_url=hero.blogger_url,
                closing_url=closing.blogger_url,
            )
            _write_text(topic_dir / "05-html" / "cloudflare-payload.md", cloudflare_markdown)
            _write_text(topic_dir / "05-html" / "blogger-assembled.html", blogger_html)

            cloudflare_published = _publish_cloudflare(
                client,
                category_id=str(cloudflare_category.get("id") or CLOUDFLARE_CATEGORY_ID_FALLBACK),
                article=cloudflare_article,
                markdown=cloudflare_markdown,
                hero_url=hero.cloudflare_url,
                assets=assets,
            )
            blogger_summary, blogger_raw_payload = _publish_blogger(db, blog=blog, article=blogger_article, html=blogger_html)
            _write_json(topic_dir / "06-publish" / "cloudflare-summary.json", cloudflare_published)
            _write_json(topic_dir / "06-publish" / "blogger-summary.json", blogger_summary)

            cloudflare_url = str(cloudflare_published.get("publicUrl") or cloudflare_published.get("url") or "").strip()
            blogger_url = str(blogger_summary.get("url") or "").strip()
            cloudflare_live = _verify_live(cloudflare_url, [asset.cloudflare_url for asset in assets], timeout=float(args.timeout))
            blogger_live = _verify_live(blogger_url, [asset.blogger_url for asset in assets], timeout=float(args.timeout))
            _write_json(topic_dir / "07-live" / "live-validation.json", {"cloudflare": cloudflare_live, "blogger": blogger_live})

            cloudflare_scores = _score_article(cloudflare_article)
            blogger_scores = _score_article(blogger_article)
            _write_json(topic_dir / "08-audit" / "scores.json", {"cloudflare": cloudflare_scores, "blogger": blogger_scores})

            if not cloudflare_live["pass"] or not blogger_live["pass"]:
                item.update(
                    {
                        "status": "partial_failed",
                        "cloudflare_url": cloudflare_url,
                        "blogger_url": blogger_url,
                        "cloudflare_live": cloudflare_live,
                        "blogger_live": blogger_live,
                    }
                )
                results.append(item)
                continue

            blogger_db = _finalize_blogger_db(
                db,
                blog=blog,
                topic_keyword=keyword,
                article_payload=blogger_article,
                html=blogger_html,
                summary=blogger_summary,
                raw_payload=blogger_raw_payload,
                assets=assets,
                scores=blogger_scores,
            )
            cloudflare_db = _finalize_cloudflare_db(
                db,
                remote_id=str(cloudflare_published.get("id") or ""),
                article_payload=cloudflare_article,
                live=cloudflare_live,
                assets=assets,
                scores=cloudflare_scores,
            )
            sync_blogger = sync_blogger_posts_for_blog(db, blog)
            final_db = {"blogger": blogger_db, "cloudflare": cloudflare_db, "blogger_sync": sync_blogger}
            _write_json(topic_dir / "09-db" / "final-db-commit.json", final_db)
            item.update(
                {
                    "status": "published_live_verified",
                    "cloudflare_url": cloudflare_url,
                    "blogger_url": blogger_url,
                    "hero_image_url": hero.blogger_url,
                    "closing_image_url": closing.blogger_url,
                    "cloudflare_scores": cloudflare_scores,
                    "blogger_scores": blogger_scores,
                    "db": final_db,
                }
            )
            results.append(item)

    summary = {
        "mode": args.mode,
        "topic_count": len(topics),
        "artifact_root": str(artifact_root),
        "cloudflare_auth_error": cloudflare_auth_error,
        "published_live_verified": len([item for item in results if item.get("status") == "published_live_verified"]),
        "existing_repaired_live_verified": len([item for item in results if item.get("status") == "existing_repaired_live_verified"]),
        "existing_images_repaired": len([item for item in results if item.get("status") == "existing_images_repaired"]),
        "completed_existing_cloudflare_live_verified": len(
            [item for item in results if item.get("status") == "completed_existing_cloudflare_live_verified"]
        ),
        "blocked_duplicate": len([item for item in results if item.get("status") == "blocked_duplicate"]),
        "partial_failed": len([item for item in results if item.get("status") == "partial_failed"]),
        "items": results,
    }
    _write_json(artifact_root / "result.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish paired Cloudflare Mysteria + Blogger English mystery topics.")
    parser.add_argument("--topic-count", type=int, default=2)
    parser.add_argument(
        "--mode",
        choices=("dry-run", "apply", "repair-existing-today", "repair-existing-images", "complete-existing-cloudflare"),
        default="dry-run",
    )
    parser.add_argument("--topics-file", default="")
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run(args)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if args.mode == "apply":
        return 0 if result.get("published_live_verified") == result.get("topic_count") else 2
    if args.mode == "repair-existing-today":
        return 0 if result.get("existing_repaired_live_verified") == result.get("topic_count") else 2
    if args.mode == "repair-existing-images":
        return 0 if result.get("existing_images_repaired") == result.get("topic_count") else 2
    if args.mode == "complete-existing-cloudflare":
        return 0 if result.get("completed_existing_cloudflare_live_verified") == result.get("topic_count") else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
