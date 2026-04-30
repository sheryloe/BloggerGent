from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from html import escape, unescape
from html.parser import HTMLParser
from typing import Any

from slugify import slugify
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Article, ContentPlanSlot, Job, Topic
from app.schemas.ai import ArticleGenerationOutput
from app.services.content.content_guard_service import assert_article_not_duplicate
from app.services.content.faq_hygiene import strip_generic_faq_leak_html
from app.services.content.travel_blog_policy import (
    TRAVEL_PATTERN_KEY_TO_LEGACY_ID,
    TRAVEL_PATTERN_VERSION,
    TRAVEL_BLOG_IDS,
    build_travel_asset_object_key,
    build_travel_collage_context,
    build_travel_image_contract,
    get_travel_blog_policy,
    normalize_travel_pattern_key,
    normalize_travel_pattern_version_key,
    normalize_travel_category_key,
    travel_pattern_missing_requirements,
)
from app.services.content.travel_translation_state_service import seed_article_travel_sync_fields
from app.services.cloudflare.cloudflare_asset_policy import (
    build_cloudflare_r2_object_key,
    build_default_cloudflare_asset_policy,
)


TAG_RE = re.compile(r"<[^>]+>")
H1_RE = re.compile(r"(?is)<h1\b")
ALLOWED_HTML_TAGS = {
    "section",
    "article",
    "div",
    "aside",
    "figure",
    "figcaption",
    "blockquote",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "ol",
    "ul",
    "li",
    "hr",
    "details",
    "summary",
    "a",
    "img",
    "strong",
    "em",
    "span",
    "p",
    "h2",
    "h3",
    "br",
    "iframe",
}
VOID_HTML_TAGS = {"br", "hr", "img"}
BLOCKED_CONTENT_TAGS = {"script", "style", "form"}
CLASS_TOKEN_PREFIXES = (
    "callout-",
    "timeline-",
    "card-",
    "fact-",
    "caution-",
    "quote-",
    "chat-",
    "comparison-",
    "route-",
    "event-",
    "policy-",
    "summary-",
    "timing-",
    "local-",
    "scene-",
    "note-",
    "workflow-",
    "eligibility-",
    "process-",
    "document-",
    "market-",
    "company-",
    "checkpoint-",
    "viewing-",
    "highlight-",
    "curator-",
    "case-",
    "evidence-",
    "interpretation-",
    "friction-",
    "risk-",
    "reflection-",
    "thought-",
    "dialogue-",
)
ALLOWED_CLASS_TOKENS = {
    "callout",
    "timeline",
    "card-grid",
    "fact-box",
    "caution-box",
    "quote-box",
    "chat-thread",
    "comparison-table",
    "route-steps",
    "event-checklist",
    "policy-summary",
    "route-hero-card",
    "step-flow",
    "timing-box",
    "timing-table",
    "local-tip-box",
    "summary-box",
    "comparison-matrix",
    "workflow-strip",
    "scene-intro",
    "scene-divider",
    "note-block",
    "note-aside",
    "event-hero",
    "crowd-timing-box",
    "food-lodging-table",
    "field-caution-box",
    "viewing-order-box",
    "highlight-table",
    "curator-note",
    "case-summary",
    "timeline-board",
    "evidence-table",
    "interpretation-compare",
    "checklist-box",
    "step-box",
    "friction-table",
    "eligibility-table",
    "process-strip",
    "document-checklist",
    "market-summary",
    "factor-table",
    "viewpoint-compare",
    "company-brief",
    "dialogue-thread",
    "checkpoint-box",
    "checkpoint-strip",
    "risk-factor-table",
    "reflection-scene",
    "thought-block",
    "table-wrap",
    "cover",
    "inline",
}
RELATED_POSTS_TOKEN = "__RELATED_POSTS_PLACEHOLDER__"
HANGUL_CHAR_RE = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]+")
MULTISPACE_RE = re.compile(r"\s{2,}")
EMPTY_PAREN_RE = re.compile(r"\(\s*\)")


def _build_render_metadata_from_output(output: ArticleGenerationOutput) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in (
        "series_variant",
        "company_name",
        "ticker",
        "exchange",
        "chart_provider",
        "chart_symbol",
        "chart_interval",
    ):
        value = getattr(output, key, None)
        text = str(value or "").strip()
        if text:
            metadata[key] = text
    slide_sections = []
    for item in getattr(output, "slide_sections", []) or []:
        if hasattr(item, "model_dump"):
            payload = item.model_dump()
        elif isinstance(item, dict):
            payload = dict(item)
        else:
            continue
        title = str(payload.get("title") or "").strip()
        summary = str(payload.get("summary") or "").strip()
        if not title or not summary:
            continue
        slide_sections.append(
            {
                "title": title,
                "summary": summary,
                "speaker": str(payload.get("speaker") or "").strip() or None,
                "key_points": [
                    str(point).strip()
                    for point in (payload.get("key_points") or [])
                    if str(point).strip()
                ][:6],
            }
        )
    if slide_sections:
        metadata["slide_sections"] = slide_sections
    return metadata
TRAVEL_EDITORIAL_CATEGORY_MAP: dict[str, tuple[str, tuple[str, ...]]] = {
    "travel": (
        "Travel",
        ("travel", "trip", "route", "itinerary", "walk", "neighborhood", "local", "course"),
    ),
    "culture": (
        "Culture",
        ("culture", "festival", "event", "exhibition", "museum", "heritage", "idol", "filming"),
    ),
    "food": (
        "Food",
        ("food", "restaurant", "market", "cafe", "eatery", "korean food", "dining", "bakery"),
    ),
}
MYSTERY_EDITORIAL_CATEGORY_MAP: dict[str, tuple[str, tuple[str, ...]]] = {
    "case-files": (
        "Case Files",
        ("case", "incident", "investigation", "evidence", "timeline", "disappearance", "murder"),
    ),
    "legends-lore": (
        "Legends & Lore",
        ("legend", "folklore", "myth", "urban legend", "scp", "lore", "haunted"),
    ),
    "mystery-archives": (
        "Mystery Archives",
        ("archive", "historical", "record", "document", "expedition", "manuscript", "chronology"),
    ),
}
TRAVEL_EDITORIAL_LOCALIZED_CATEGORY_LABELS: dict[str, dict[str, str]] = {
    "es": {
        "travel": "Viajes",
        "culture": "Cultura",
        "food": "Gastronom\u00eda",
    },
    "ja": {
        "travel": "\u65c5\u884c\u30fb\u304a\u796d\u308a",
        "culture": "\u30e9\u30a4\u30d5\u30b9\u30bf\u30a4\u30eb",
        "food": "\u30b0\u30eb\u30e1\u30fb\u30ab\u30d5\u30a7",
    },
}
TRAVEL_EDITORIAL_CANONICAL_KEYS = {"travel", "culture", "food"}
MYSTERY_EDITORIAL_CANONICAL_KEYS = {"mystery", "history", "casefile"}


def _normalize_slug_token(value: str | None, *, fallback: str) -> str:
    raw = str(value or "").strip()
    normalized = slugify(raw, separator="-") if raw else ""
    return normalized or fallback


def resolve_r2_blog_group(
    *,
    profile_key: str | None,
    blog_id: int | None = None,
    primary_language: str | None = None,
    channel_provider: str | None = None,
) -> str:
    normalized_profile = (profile_key or "").strip().lower()
    normalized_provider = (channel_provider or "").strip().lower()
    travel_policy = get_travel_blog_policy(blog_id=blog_id)

    if normalized_provider == "cloudflare":
        return "cloudflare/dongri-archive"

    if travel_policy is not None:
        return "travel-blogger"
    if normalized_profile == "korea_travel":
        return "google-blogger/korea-travel"
    if normalized_profile == "world_mystery":
        return "google-blogger/world-mystery"
    if normalized_profile in {"archive", "cloudflare_archive"}:
        return "cloudflare/dongri-archive"
    return "cloudflare/dongri-archive"


def _travel_category_alias_map(primary_language: str | None) -> dict[str, str]:
    localized = _travel_localized_category_map(primary_language)
    aliases: dict[str, str] = {
        "travel": "travel",
        "viaje": "travel",
        "viajes": "travel",
        "trip": "travel",
        "trips": "travel",
        "旅行": "travel",
        "旅行・お祭り": "travel",
        "culture": "culture",
        "cultura": "culture",
        "lifestyle": "culture",
        "ライフスタイル": "culture",
        "food": "food",
        "gastronomia": "food",
        "gastronomía": "food",
        "gourmet": "food",
        "グルメ": "food",
        "グルメ・カフェ": "food",
        "cafe": "food",
    }
    for key, value in localized.items():
        aliases[value] = key
    for key, (label, _keywords) in TRAVEL_EDITORIAL_CATEGORY_MAP.items():
        aliases[key] = key
        aliases[label] = key
    return {_normalize_label_key(raw): canonical for raw, canonical in aliases.items() if _normalize_label_key(raw)}


def resolve_r2_category_key(
    *,
    profile_key: str | None,
    primary_language: str | None = None,
    editorial_category_key: str | None = None,
    editorial_category_label: str | None = None,
    labels: list[str] | None = None,
    title: str = "",
    summary: str = "",
    category_slug: str | None = None,
) -> str:
    normalized_profile = (profile_key or "").strip().lower()
    normalized_key = (editorial_category_key or "").strip().lower()

    if normalized_profile == "korea_travel":
        if normalized_key in TRAVEL_EDITORIAL_CANONICAL_KEYS:
            return normalized_key

        alias_map = _travel_category_alias_map(primary_language)
        candidate_labels = [editorial_category_label or "", *(labels or [])]
        for candidate in candidate_labels:
            resolved = alias_map.get(_normalize_label_key(candidate))
            if resolved:
                return resolved

        inferred_key, _ = infer_editorial_category(
            profile_key="korea_travel",
            primary_language=primary_language,
            labels=list(labels or []),
            title=title,
            summary=summary,
        )
        if inferred_key in TRAVEL_EDITORIAL_CANONICAL_KEYS and any(
            token.strip()
            for token in [title, summary, *(labels or []), editorial_category_label or "", category_slug or ""]
        ):
            return inferred_key
        return "uncategorized"

    if normalized_profile == "world_mystery":
        if normalized_key in MYSTERY_EDITORIAL_CANONICAL_KEYS:
            if normalized_key in {"history", "casefile"}:
                return normalized_key
            return "mystery"

        normalized_label = _normalize_label_key(editorial_category_label)
        if normalized_label in {"history", "historical"}:
            return "history"
        if normalized_label in {"case files", "casefile", "case-file"}:
            return "casefile"
        return "mystery"

    if normalized_profile in {"archive", "cloudflare_archive"}:
        raw_category_slug = str(category_slug or "").strip()
        if raw_category_slug:
            return raw_category_slug

    slug_candidate = _normalize_slug_token(category_slug, fallback="")
    return slug_candidate or "uncategorized"


def build_r2_asset_object_key(
    *,
    profile_key: str | None,
    blog_id: int | None = None,
    primary_language: str | None = None,
    blog_slug: str | None = None,
    channel_slug: str | None = None,
    editorial_category_key: str | None = None,
    editorial_category_label: str | None = None,
    labels: list[str] | None = None,
    title: str = "",
    summary: str = "",
    category_slug: str | None = None,
    channel_provider: str | None = None,
    post_slug: str,
    asset_role: str,
    content: bytes | None = None,
    timestamp: datetime | None = None,
) -> str:
    resolved_time = timestamp.astimezone(timezone.utc) if timestamp else datetime.now(timezone.utc)
    normalized_blog_slug = _normalize_slug_token(blog_slug, fallback="")
    normalized_channel_slug = _normalize_slug_token(channel_slug, fallback="")
    normalized_profile = (profile_key or "").strip().lower()
    normalized_provider = (channel_provider or "").strip().lower()
    travel_policy = get_travel_blog_policy(blog_id=blog_id)
    if travel_policy is not None:
        category_key = normalize_travel_category_key(
            resolve_r2_category_key(
                profile_key=profile_key,
                primary_language=primary_language,
                editorial_category_key=editorial_category_key,
                editorial_category_label=editorial_category_label,
                labels=labels,
                title=title,
                summary=summary,
                category_slug=category_slug,
            )
        )
        return build_travel_asset_object_key(
            policy=travel_policy,
            category_key=category_key,
            post_slug=post_slug,
            asset_role=asset_role,
        )
    if normalized_provider == "cloudflare" or normalized_profile in {"archive", "cloudflare_archive"}:
        category_key = resolve_r2_category_key(
            profile_key=profile_key,
            primary_language=primary_language,
            editorial_category_key=editorial_category_key,
            editorial_category_label=editorial_category_label,
            labels=labels,
            title=title,
            summary=summary,
            category_slug=category_slug,
        )
        return build_cloudflare_r2_object_key(
            policy=build_default_cloudflare_asset_policy(),
            category_slug=category_key,
            post_slug=post_slug,
            published_at=resolved_time,
        )
    else:
        blog_group = (
            normalized_blog_slug
            if normalized_blog_slug
            else (
                normalized_channel_slug
                if normalized_channel_slug
                else "default-blog"
            )
        )
    category_key = resolve_r2_category_key(
        profile_key=profile_key,
        primary_language=primary_language,
        editorial_category_key=editorial_category_key,
        editorial_category_label=editorial_category_label,
        labels=labels,
        title=title,
        summary=summary,
        category_slug=category_slug,
    )
    slug_token = _normalize_slug_token(post_slug, fallback="post")
    if normalized_profile == "world_mystery":
        role_token = _normalize_slug_token(asset_role, fallback="hero")
        file_stem = f"{slug_token}-closing" if role_token in {"closing", "visual-summary", "summary"} else slug_token
        return (
            f"assets/the-midnight-archives/{category_key}/"
            f"{resolved_time:%Y}/{resolved_time:%m}/{slug_token}/{file_stem}.webp"
        )

    role_token = _normalize_slug_token(asset_role, fallback="asset")
    hash_source = (
        content
        if content
        else f"{blog_group}:{category_key}:{slug_token}:{role_token}:{resolved_time:%Y%m%d%H%M}".encode("utf-8")
    )
    digest = hashlib.sha256(hash_source).hexdigest()[:12]
    return (
        f"assets/media/{blog_group}/{category_key}/"
        f"{resolved_time:%Y}/{resolved_time:%m}/{slug_token}/{role_token}-{digest}.webp"
    )


def build_article_r2_asset_object_key(
    article: Article,
    *,
    asset_role: str,
    content: bytes | None = None,
    timestamp: datetime | None = None,
) -> str:
    blog = article.blog
    return build_r2_asset_object_key(
        profile_key=str(getattr(blog, "profile_key", "") or ""),
        blog_id=int(getattr(blog, "id", 0) or 0),
        primary_language=str(getattr(blog, "primary_language", "") or ""),
        blog_slug=str(getattr(blog, "slug", "") or ""),
        editorial_category_key=article.editorial_category_key,
        editorial_category_label=article.editorial_category_label,
        labels=list(article.labels or []),
        title=article.title,
        summary=article.excerpt,
        post_slug=article.slug,
        asset_role=asset_role,
        content=content,
        timestamp=timestamp,
    )

def estimate_reading_time(html_fragment: str) -> int:
    text = TAG_RE.sub(" ", html_fragment)
    words = [word for word in text.split() if word.strip()]
    return max(4, round(len(words) / 180))


def _is_safe_href(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith(("http://", "https://", "//", "/", "#", "mailto:"))


def _is_safe_src(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith(("http://", "https://", "//", "/"))


def _sanitize_class_value(raw_value: str) -> str | None:
    tokens: list[str] = []
    seen: set[str] = set()
    for raw_token in str(raw_value or "").split():
        token = raw_token.strip()
        if not token:
            continue
        if token in ALLOWED_CLASS_TOKENS or any(token.startswith(prefix) for prefix in CLASS_TOKEN_PREFIXES):
            if token not in seen:
                seen.add(token)
                tokens.append(token)
    if not tokens:
        return None
    return " ".join(tokens)


class _SafeHtmlSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self.blocked_depth = 0

    def _push_tag(self, tag: str, attrs: list[tuple[str, str | None]], *, self_closing: bool = False) -> None:
        if tag not in ALLOWED_HTML_TAGS:
            return
        rendered_attrs: list[str] = []
        attr_map = {str(key or "").lower(): value for key, value in attrs if str(key or "").strip()}
        class_value = _sanitize_class_value(str(attr_map.get("class") or ""))
        if class_value:
            rendered_attrs.append(f'class="{escape(class_value, quote=True)}"')
        # Allow all data-* attributes for whitelisted tags to support client-side interactive blocks
        if tag in {"figure", "img", "div", "section", "article", "span"}:
            for attr_name, attr_value in attr_map.items():
                if attr_name.startswith("data-"):
                    rendered_attrs.append(f'{attr_name}="{escape(str(attr_value or ""), quote=True)}"')
        if tag == "a":
            href = str(attr_map.get("href") or "").strip()
            if href and _is_safe_href(href):
                rendered_attrs.append(f'href="{escape(href, quote=True)}"')
            title = str(attr_map.get("title") or "").strip()
            if title:
                rendered_attrs.append(f'title="{escape(title, quote=True)}"')
            target = str(attr_map.get("target") or "").strip()
            if target == "_blank":
                rendered_attrs.append('target="_blank"')
                rendered_attrs.append('rel="noopener noreferrer"')
        elif tag == "img":
            src = str(attr_map.get("src") or "").strip()
            if src and _is_safe_src(src):
                rendered_attrs.append(f'src="{escape(src, quote=True)}"')
            alt = str(attr_map.get("alt") or "").strip()
            rendered_attrs.append(f'alt="{escape(alt, quote=True)}"')
            title = str(attr_map.get("title") or "").strip()
            if title:
                rendered_attrs.append(f'title="{escape(title, quote=True)}"')
            loading = str(attr_map.get("loading") or "").strip().lower()
            rendered_attrs.append(f'loading="{loading if loading in {"lazy", "eager"} else "lazy"}"')
            for dimension in ("width", "height"):
                value = str(attr_map.get(dimension) or "").strip()
                if value.isdigit():
                    rendered_attrs.append(f'{dimension}="{value}"')
        elif tag in {"h2", "h3"}:
            id_val = str(attr_map.get("id") or "").strip()
            if id_val:
                rendered_attrs.append(f'id="{escape(id_val, quote=True)}"')
        elif tag == "details":
            if "open" in attr_map:
                rendered_attrs.append("open")
        elif tag == "iframe":
            src = str(attr_map.get("src") or "").strip()
            if src and (src.startswith("https://s.tradingview.com/") or src.startswith("https://www.google.com/maps/")):
                rendered_attrs.append(f'src="{escape(src, quote=True)}"')
            for attr in ("width", "height", "frameborder", "allowfullscreen"):
                if attr in attr_map:
                    val = str(attr_map.get(attr) or "").strip()
                    if val:
                        rendered_attrs.append(f'{attr}="{escape(val, quote=True)}"')
                    else:
                        rendered_attrs.append(attr)

        attr_suffix = f" {' '.join(rendered_attrs)}" if rendered_attrs else ""
        if self_closing or tag in VOID_HTML_TAGS:
            self.parts.append(f"<{tag}{attr_suffix}>")
            return
        self.parts.append(f"<{tag}{attr_suffix}>")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        if normalized_tag in BLOCKED_CONTENT_TAGS:
            self.blocked_depth += 1
            return
        if self.blocked_depth:
            return
        self._push_tag(normalized_tag, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        if normalized_tag in BLOCKED_CONTENT_TAGS or self.blocked_depth:
            return
        self._push_tag(normalized_tag, attrs, self_closing=True)

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag in BLOCKED_CONTENT_TAGS:
            self.blocked_depth = max(0, self.blocked_depth - 1)
            return
        if self.blocked_depth or normalized_tag not in ALLOWED_HTML_TAGS or normalized_tag in VOID_HTML_TAGS:
            return
        self.parts.append(f"</{normalized_tag}>")

    def handle_data(self, data: str) -> None:
        if self.blocked_depth or not data:
            return
        self.parts.append(escape(data))

    def handle_entityref(self, name: str) -> None:
        if self.blocked_depth:
            return
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self.blocked_depth:
            return
        self.parts.append(f"&#{name};")


def sanitize_blog_html(html_fragment: str) -> str:
    stripped = strip_generic_faq_leak_html(html_fragment)
    preserved = stripped.replace("<!--RELATED_POSTS-->", RELATED_POSTS_TOKEN)
    parser = _SafeHtmlSanitizer()
    parser.feed(preserved)
    parser.close()
    sanitized = "".join(parser.parts)
    sanitized = sanitized.replace(RELATED_POSTS_TOKEN, "<!--RELATED_POSTS-->")
    return sanitized.strip()


def _is_english_mystery(*, profile_key: str, primary_language: str) -> bool:
    return (profile_key or "").strip().lower() == "world_mystery" and (primary_language or "").strip().lower().startswith("en")


def _strip_hangul_text(value: str) -> str:
    cleaned = HANGUL_CHAR_RE.sub("", str(value or ""))
    cleaned = EMPTY_PAREN_RE.sub("", cleaned)
    cleaned = MULTISPACE_RE.sub(" ", cleaned)
    return cleaned.strip()


def _plain_text_length(value: str) -> int:
    raw = TAG_RE.sub(" ", str(value or ""))
    normalized = MULTISPACE_RE.sub("", unescape(raw))
    return len(normalized.strip())


def _plain_text_for_quality(value: str) -> str:
    raw = TAG_RE.sub(" ", str(value or ""))
    normalized = unicodedata.normalize("NFKC", unescape(raw))
    return MULTISPACE_RE.sub(" ", normalized).strip()


def _quality_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = re.sub(r"https?://\S+", "", normalized)
    normalized = re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)
    return normalized.strip()


def _extract_quality_paragraphs(html_fragment: str) -> list[str]:
    matches = re.findall(r"(?is)<p\b[^>]*>(.*?)</p>", str(html_fragment or ""))
    paragraphs = [_plain_text_for_quality(item) for item in matches]
    return [item for item in paragraphs if item]


def _split_quality_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。！？])\s+|(?<=[.!?。！？])", str(text or ""))
    sentences = [MULTISPACE_RE.sub(" ", part).strip() for part in parts]
    return [item for item in sentences if len(_quality_key(item)) >= 10]


def _travel_content_quality_check(
    *,
    title: str,
    meta_description: str,
    excerpt: str,
    html_article: str,
) -> dict[str, Any]:
    plain_text = _plain_text_for_quality(html_article)
    paragraphs = _extract_quality_paragraphs(html_article)
    sentences = _split_quality_sentences(plain_text)
    sentence_counter = Counter(_quality_key(sentence) for sentence in sentences)
    paragraph_counter = Counter(_quality_key(paragraph) for paragraph in paragraphs if len(_quality_key(paragraph)) >= 60)
    issues: list[str] = []

    repeated_sentences = [
        key for key, count in sentence_counter.items()
        if key and count >= 2
    ]
    if repeated_sentences:
        issues.append("duplicate_sentence")

    repeated_paragraphs = [
        key for key, count in paragraph_counter.items()
        if key and count >= 2
    ]
    if repeated_paragraphs:
        issues.append("duplicate_paragraph")

    first_paragraph_key = _quality_key(paragraphs[0]) if paragraphs else ""
    for source_name, source_value in (
        ("meta_description", meta_description),
        ("excerpt", excerpt),
        ("title", title),
    ):
        source_key = _quality_key(source_value)
        if len(source_key) < 30 or not first_paragraph_key:
            continue
        shorter = min(len(source_key), len(first_paragraph_key))
        if source_key == first_paragraph_key or first_paragraph_key.startswith(source_key[:shorter]) or source_key.startswith(first_paragraph_key[:shorter]):
            issues.append(f"intro_duplicates_{source_name}")

    lower_plain = plain_text.casefold()
    water_terms = (
        "river",
        "riverside",
        "stream",
        "川沿い",
        "川辺",
        "河川",
        "río",
        "ribera",
        "arroyo",
    )
    water_context_terms = (
        "hangang",
        "han river",
        "nodeul",
        "ichon",
        "anyangcheon",
        "cheonggyecheon",
        "seokchon",
        "lake",
        "한강",
        "노들",
        "이촌",
        "안양천",
        "청계천",
        "石村湖",
        "漢江",
        "ノドゥル",
        "二村",
        "río han",
        "cheonggyecheon",
    )
    if any(term in lower_plain for term in water_terms) and not any(term in lower_plain for term in water_context_terms):
        issues.append("route_irrelevant_water_template")

    return {
        "passed": not issues,
        "issues": issues,
        "sentence_count": len(sentences),
        "paragraph_count": len(paragraphs),
        "duplicate_sentence_count": len(repeated_sentences),
        "duplicate_paragraph_count": len(repeated_paragraphs),
        "body_chars": _plain_text_length(html_article),
    }


def _legacy_travel_pattern_version(value: int | str | None) -> int | None:
    if value == TRAVEL_PATTERN_VERSION:
        return TRAVEL_PATTERN_VERSION
    if isinstance(value, str):
        stripped = value.strip().lower()
        if stripped.isdigit() and int(stripped) == TRAVEL_PATTERN_VERSION:
            return TRAVEL_PATTERN_VERSION
    return None


def _body_h1_count(value: str) -> int:
    return len(H1_RE.findall(str(value or "")))


def _normalize_english_mystery_faq(faq_items: list[dict]) -> list[dict]:
    defaults = [
        {
            "question": "What are the key verified facts in this case?",
            "answer": "Start from records that can be dated, sourced, and cross-checked before considering later retellings.",
        },
        {
            "question": "How should readers evaluate competing theories?",
            "answer": "Compare each theory against documented evidence, timeline consistency, and source credibility.",
        },
        {
            "question": "What still makes this case unresolved today?",
            "answer": "The remaining gap is usually a missing record, a weak chain of custody, or conflicting testimony that has never been fully reconciled.",
        },
    ]
    normalized: list[dict] = []
    for item in faq_items:
        question = _strip_hangul_text(str(item.get("question") or item.get("q") or item.get("title") or ""))
        answer = _strip_hangul_text(str(item.get("answer") or item.get("a") or item.get("text") or ""))
        if question and answer:
            normalized.append({"question": question, "answer": answer})

    if len(normalized) >= 3:
        return normalized[:3]
    return normalized + defaults[: max(0, 3 - len(normalized))]


def ensure_unique_slug(db: Session, blog_id: int, slug_base: str, article_id: int | None = None) -> str:
    slug = slugify(slug_base) or "post"
    candidate = slug
    counter = 2
    while True:
        existing = db.execute(
            select(Article).where(Article.blog_id == blog_id, Article.slug == candidate)
        ).scalar_one_or_none()
        if not existing or existing.id == article_id:
            return candidate
        candidate = f"{slug}-{counter}"
        counter += 1


def _editorial_category_map(profile_key: str) -> dict[str, tuple[str, tuple[str, ...]]]:
    normalized = (profile_key or "").strip().lower()
    if normalized == "korea_travel":
        return TRAVEL_EDITORIAL_CATEGORY_MAP
    if normalized == "world_mystery":
        return MYSTERY_EDITORIAL_CATEGORY_MAP
    return {}


def _travel_localized_category_map(primary_language: str | None) -> dict[str, str]:
    language = (primary_language or "").strip().lower()
    return TRAVEL_EDITORIAL_LOCALIZED_CATEGORY_LABELS.get(language, {})


def _canonical_editorial_label(*, profile_key: str, category_key: str | None) -> str | None:
    if not category_key:
        return None
    category_map = _editorial_category_map(profile_key)
    bucket = category_map.get(category_key)
    if not bucket:
        return None
    return bucket[0]


def _resolved_editorial_label(
    *,
    profile_key: str,
    primary_language: str | None,
    category_key: str | None,
) -> str | None:
    if not category_key:
        return None
    normalized_profile = (profile_key or "").strip().lower()
    if normalized_profile == "korea_travel":
        localized_map = _travel_localized_category_map(primary_language)
        localized = localized_map.get(category_key)
        if localized:
            return localized
    return _canonical_editorial_label(profile_key=profile_key, category_key=category_key)


def _normalize_label_key(value: str | None) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _dedupe_labels(labels: list[str] | None) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for raw in labels or []:
        value = str(raw or "").strip()
        if not value:
            continue
        key = _normalize_label_key(value)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def infer_editorial_category(
    *,
    profile_key: str,
    primary_language: str | None = None,
    labels: list[str],
    title: str,
    summary: str,
) -> tuple[str, str]:
    category_map = _editorial_category_map(profile_key)
    if not category_map:
        return "", ""

    normalized_labels = {_normalize_label_key(label) for label in labels if str(label or "").strip()}
    localized_travel_map = (
        _travel_localized_category_map(primary_language)
        if (profile_key or "").strip().lower() == "korea_travel"
        else {}
    )
    for key, (label, _keywords) in category_map.items():
        if _normalize_label_key(label) in normalized_labels or _normalize_label_key(key) in normalized_labels:
            return key, localized_travel_map.get(key, label)

    for key, localized_label in localized_travel_map.items():
        if _normalize_label_key(localized_label) in normalized_labels:
            canonical_label = _canonical_editorial_label(profile_key=profile_key, category_key=key)
            return key, localized_label or canonical_label or ""

    haystack = f"{title} {summary} {' '.join(labels)}".casefold()
    best_key = ""
    best_label = ""
    best_score = -1
    for key, (label, keywords) in category_map.items():
        score = sum(1 for keyword in keywords if keyword.casefold() in haystack)
        if score > best_score:
            best_key = key
            best_label = label
            best_score = score

    if best_key and best_label:
        return best_key, localized_travel_map.get(best_key, best_label)

    first_key, (first_label, _keywords) = next(iter(category_map.items()))
    return first_key, localized_travel_map.get(first_key, first_label)


def canonicalize_editorial_labels(
    *,
    profile_key: str,
    primary_language: str | None = None,
    editorial_category_key: str | None,
    editorial_category_label: str | None,
    labels: list[str] | None,
    title: str,
    summary: str,
) -> tuple[str | None, str | None, list[str]]:
    category_map = _editorial_category_map(profile_key)
    cleaned_labels = _dedupe_labels(labels)
    key = (editorial_category_key or "").strip().lower() or None
    label = (editorial_category_label or "").strip() or None
    if key and category_map and key not in category_map:
        key = None

    if category_map and (not key or not label):
        inferred_key, inferred_label = infer_editorial_category(
            profile_key=profile_key,
            primary_language=primary_language,
            labels=cleaned_labels,
            title=title,
            summary=summary,
        )
        key = key or inferred_key or None
        label = label or inferred_label or None

    resolved_label = label
    canonical_label = None
    if category_map and key:
        resolved_label = _resolved_editorial_label(
            profile_key=profile_key,
            primary_language=primary_language,
            category_key=key,
        ) or resolved_label
        canonical_label = _canonical_editorial_label(profile_key=profile_key, category_key=key)

    ordered_labels: list[str] = []
    seen: set[str] = set()
    for candidate in (resolved_label, canonical_label):
        normalized_candidate = _normalize_label_key(candidate)
        if not normalized_candidate or normalized_candidate in seen:
            continue
        seen.add(normalized_candidate)
        ordered_labels.append(candidate or "")

    for raw in cleaned_labels:
        normalized_raw = _normalize_label_key(raw)
        if not normalized_raw or normalized_raw in seen:
            continue
        seen.add(normalized_raw)
        ordered_labels.append(raw)

    return key, resolved_label, ordered_labels[:8]


def resolve_article_editorial_labels(article: Article) -> tuple[str | None, str | None, list[str]]:
    profile_key = ""
    primary_language = ""
    if getattr(article, "blog", None) is not None and getattr(article.blog, "profile_key", None):
        profile_key = str(article.blog.profile_key)
        primary_language = str(getattr(article.blog, "primary_language", "") or "")
    return canonicalize_editorial_labels(
        profile_key=profile_key,
        primary_language=primary_language,
        editorial_category_key=article.editorial_category_key,
        editorial_category_label=article.editorial_category_label,
        labels=list(article.labels or []),
        title=article.title,
        summary=article.excerpt,
    )


def ensure_article_editorial_labels(db: Session, article: Article, *, commit: bool = True) -> list[str]:
    resolved_key, resolved_label, resolved_labels = resolve_article_editorial_labels(article)
    changed = (
        (article.editorial_category_key or "") != (resolved_key or "")
        or (article.editorial_category_label or "") != (resolved_label or "")
        or list(article.labels or []) != resolved_labels
    )
    article.editorial_category_key = resolved_key
    article.editorial_category_label = resolved_label
    article.labels = resolved_labels
    if changed:
        db.add(article)
        if commit:
            db.commit()
            db.refresh(article)
        else:
            db.flush()
    return list(article.labels or [])


def save_article(
    db: Session,
    *,
    job: Job,
    topic: Topic | None,
    output: ArticleGenerationOutput,
    persist: bool = True,
    commit: bool = True,
    upsert_fact: bool = True,
) -> Article:
    article = db.execute(select(Article).where(Article.job_id == job.id)).scalar_one_or_none() if persist else None
    sanitized_title = output.title
    sanitized_meta_description = output.meta_description
    sanitized_excerpt = output.excerpt
    sanitized_html = sanitize_blog_html(output.html_article)
    sanitized_faq_section = [item.model_dump() for item in output.faq_section]
    slug_candidate = slugify(output.slug or sanitized_title) or "post"
    if int(job.blog_id or 0) == 37 and get_travel_blog_policy(blog_id=job.blog_id) is not None:
        travel_sync_payload = {}
        if isinstance(job.raw_prompts, dict):
            candidate = job.raw_prompts.get("travel_sync")
            if isinstance(candidate, dict):
                travel_sync_payload = dict(candidate)
        try:
            explicit_source_id = int(travel_sync_payload.get("source_article_id") or 0)
        except (TypeError, ValueError):
            explicit_source_id = 0
        if explicit_source_id > 0:
            source_slug = db.execute(
                select(Article.slug).where(Article.id == explicit_source_id)
            ).scalar_one_or_none()
            source_slug_candidate = slugify(source_slug or "", separator="-")
            if source_slug_candidate:
                slug_candidate = source_slug_candidate
    assert_article_not_duplicate(
        db,
        blog_id=job.blog_id,
        title=sanitized_title,
        slug=slug_candidate,
        exclude_article_id=article.id if article else None,
    )
    profile_key = ""
    primary_language = ""
    if getattr(job, "blog", None) is not None and getattr(job.blog, "profile_key", None):
        profile_key = str(job.blog.profile_key)
        primary_language = str(getattr(job.blog, "primary_language", "") or "")
    elif topic is not None and getattr(topic, "blog", None) is not None and getattr(topic.blog, "profile_key", None):
        profile_key = str(topic.blog.profile_key)
        primary_language = str(getattr(topic.blog, "primary_language", "") or "")
    if _is_english_mystery(profile_key=profile_key, primary_language=primary_language):
        sanitized_title = _strip_hangul_text(sanitized_title) or "Mystery feature"
        sanitized_meta_description = _strip_hangul_text(sanitized_meta_description)
        sanitized_excerpt = _strip_hangul_text(sanitized_excerpt)
        sanitized_html = _strip_hangul_text(sanitized_html) or sanitized_html
        sanitized_faq_section = _normalize_english_mystery_faq(sanitized_faq_section)
        slug_candidate = slugify(output.slug or sanitized_title) or "post"
        if _plain_text_length(sanitized_html) < 3000:
            raise ValueError("mystery_article_plain_text_too_short")
        if _body_h1_count(sanitized_html) > 0:
            raise ValueError("mystery_article_body_h1_forbidden")
        if len(sanitized_faq_section) != 3:
            raise ValueError("mystery_article_faq_count_invalid")
        if not str(output.image_collage_prompt or "").strip():
            raise ValueError("mystery_article_image_prompt_missing")
    travel_policy = get_travel_blog_policy(blog_id=job.blog_id)
    resolved_article_pattern_key = normalize_travel_pattern_key(
        getattr(output, "article_pattern_key", None),
        pattern_id=output.article_pattern_id,
    )
    resolved_article_pattern_version_key = normalize_travel_pattern_version_key(
        getattr(output, "article_pattern_version_key", None),
        pattern_version=output.article_pattern_version,
    )
    resolved_article_pattern_id = (
        output.article_pattern_id
        or TRAVEL_PATTERN_KEY_TO_LEGACY_ID.get(resolved_article_pattern_key)
    )
    resolved_article_pattern_version = _legacy_travel_pattern_version(output.article_pattern_version)
    if resolved_article_pattern_version is None and resolved_article_pattern_version_key:
        resolved_article_pattern_version = TRAVEL_PATTERN_VERSION
    travel_quality_check_payload: dict[str, Any] | None = None
    if travel_policy is not None:
        if _plain_text_length(sanitized_html) < 3000:
            raise ValueError("travel_article_plain_text_too_short")
        if _body_h1_count(sanitized_html) > 0:
            raise ValueError("travel_article_body_h1_forbidden")
        missing_pattern_requirements = travel_pattern_missing_requirements(
            resolved_article_pattern_id,
            output.article_pattern_version,
            pattern_key=resolved_article_pattern_key,
            pattern_version_key=resolved_article_pattern_version_key,
        )
        if missing_pattern_requirements:
            raise ValueError(
                "travel_article_pattern_invalid:" + ",".join(missing_pattern_requirements)
            )
        if "<img" in str(output.html_article or "").lower():
            raise ValueError("travel_article_inline_image_forbidden")
        travel_quality_check_payload = _travel_content_quality_check(
            title=sanitized_title,
            meta_description=sanitized_meta_description,
            excerpt=sanitized_excerpt,
            html_article=sanitized_html,
        )
        if not bool(travel_quality_check_payload.get("passed")):
            issues = [str(item) for item in travel_quality_check_payload.get("issues") or []]
            raise ValueError("travel_article_quality_invalid:" + ",".join(issues))
    resolved_editorial_key, resolved_editorial_label, resolved_labels = canonicalize_editorial_labels(
        profile_key=profile_key,
        primary_language=primary_language,
        editorial_category_key=(topic.editorial_category_key if topic else None),
        editorial_category_label=(topic.editorial_category_label if topic else None),
        labels=list(output.labels or []),
        title=sanitized_title,
        summary=sanitized_excerpt,
    )
    render_metadata = _build_render_metadata_from_output(output)
    if travel_quality_check_payload is not None:
        render_metadata = {
            **render_metadata,
            "travel_quality_checks": travel_quality_check_payload,
        }
    travel_score_payload: dict[str, Any] | None = None
    if travel_policy is not None:
        try:
            from app.services.content.content_ops_service import compute_seo_geo_scores

            travel_score_payload = compute_seo_geo_scores(
                title=sanitized_title,
                html_body=sanitized_html,
                excerpt=sanitized_excerpt,
                faq_section=sanitized_faq_section,
            )
            quality_scores = dict(render_metadata.get("travel_quality_scores") or {})
            quality_scores.update(
                {
                    "seo_score": int(travel_score_payload.get("seo_score") or 0),
                    "geo_score": int(travel_score_payload.get("geo_score") or 0),
                    "ctr_title_score": int(travel_score_payload.get("ctr_score") or 0),
                    "ctr_breakdown": dict(travel_score_payload.get("ctr_breakdown") or {}),
                }
            )
            render_metadata = {
                **render_metadata,
                "travel_quality_scores": quality_scores,
            }
        except Exception:
            travel_score_payload = None

    payload = {
        "blog_id": job.blog_id,
        "topic_id": topic.id if topic else None,
        "title": sanitized_title,
        "meta_description": sanitized_meta_description,
        "labels": resolved_labels,
        "slug": slug_candidate,
        "excerpt": sanitized_excerpt,
        "html_article": sanitized_html,
        "faq_section": sanitized_faq_section,
        "image_collage_prompt": output.image_collage_prompt,
        "article_pattern_id": resolved_article_pattern_id,
        "article_pattern_version": resolved_article_pattern_version,
        "article_pattern_key": resolved_article_pattern_key,
        "article_pattern_version_key": resolved_article_pattern_version_key,
        "render_metadata": render_metadata,
        "editorial_category_key": resolved_editorial_key,
        "editorial_category_label": resolved_editorial_label,
        "reading_time_minutes": estimate_reading_time(sanitized_html),
    }
    if travel_score_payload is not None:
        payload["quality_seo_score"] = int(travel_score_payload.get("seo_score") or 0)
        payload["quality_geo_score"] = int(travel_score_payload.get("geo_score") or 0)
        payload["quality_ctr_score"] = float(travel_score_payload.get("ctr_score") or 0)
    if article:
        for key, value in payload.items():
            setattr(article, key, value)
    elif persist:
        article = Article(job_id=job.id, **payload)
        db.add(article)
    else:
        article = Article(job_id=job.id, **payload)
        article.blog = getattr(job, "blog", None)
        article.job = job
        if topic is not None:
            article.topic = topic
        return article

    db.flush()
    seed_article_travel_sync_fields(db, article, commit=False)
    travel_sync_payload = {}
    if isinstance(job.raw_prompts, dict):
        candidate = job.raw_prompts.get("travel_sync")
        if isinstance(candidate, dict):
            travel_sync_payload = dict(candidate)
    explicit_source_id = int(travel_sync_payload.get("source_article_id") or 0)
    if explicit_source_id > 0 and explicit_source_id != int(article.id or 0):
        source_article = db.execute(select(Article).where(Article.id == explicit_source_id)).scalar_one_or_none()
        if source_article is not None and int(source_article.blog_id or 0) in TRAVEL_BLOG_IDS:
            article.travel_sync_source_article_id = int(source_article.id)
            explicit_group_key = str(travel_sync_payload.get("group_key") or "").strip()
            if explicit_group_key:
                article.travel_sync_group_key = explicit_group_key
            render_metadata = dict(article.render_metadata or {})
            render_metadata["travel_sync_source_article_id"] = int(source_article.id)
            render_metadata["travel_sync_source_blog_id"] = int(source_article.blog_id or 0)
            if explicit_group_key:
                render_metadata["travel_sync_group_key"] = explicit_group_key
            source_language = str(travel_sync_payload.get("source_language") or "").strip().lower()
            target_language = str(travel_sync_payload.get("target_language") or "").strip().lower()
            if source_language:
                render_metadata["travel_sync_source_language"] = source_language
            if target_language:
                render_metadata["travel_sync_target_language"] = target_language
            article.render_metadata = render_metadata
            db.add(article)
    planner_slot = db.execute(select(ContentPlanSlot).where(ContentPlanSlot.job_id == job.id)).scalar_one_or_none()
    if planner_slot is not None:
        planner_slot.article_id = article.id
        db.add(planner_slot)
    if commit:
        db.commit()
        db.refresh(article)
    else:
        db.flush()
    if upsert_fact:
        from app.services.ops.analytics_service import upsert_article_fact

        upsert_article_fact(db, article.id, commit=commit)
    return article


def build_collage_article_context(article: Article) -> str:
    travel_policy = get_travel_blog_policy(blog=article.blog)
    if travel_policy is not None:
        planner_summary = ""
        render_metadata = article.render_metadata if isinstance(article.render_metadata, dict) else {}
        planner = render_metadata.get("travel_planner") if isinstance(render_metadata, dict) else None
        if isinstance(planner, dict):
            beat_lines: list[str] = []
            for beat in planner.get("beats") or []:
                if not isinstance(beat, dict):
                    continue
                label = str(beat.get("label") or beat.get("key") or "").strip()
                goal = str(beat.get("goal") or "").strip()
                if label and goal:
                    beat_lines.append(f"{label}: {goal}")
            planner_summary = " | ".join(beat_lines[:4])
        return build_travel_collage_context(
            title=article.title,
            excerpt=article.excerpt,
            labels=list(article.labels or []),
            image_seed=article.image_collage_prompt,
            planner_summary=planner_summary,
            category_key=article.editorial_category_key,
            pattern_key=getattr(article, "article_pattern_key", None),
            pattern_id=getattr(article, "article_pattern_id", None),
            policy=travel_policy,
        )

    labels = ", ".join(article.labels or [])
    return "\n".join(
        [
            f"Blog: {article.blog.name if article.blog else ''}",
            f"Title: {article.title}",
            f"Excerpt: {article.excerpt}",
            f"Labels: {labels}",
            f"Article HTML: {article.html_article}",
            f"Initial image direction: {article.image_collage_prompt}",
        ]
    )


def build_collage_prompt(article: Article, prompt_template: str | None = None) -> str:
    if prompt_template:
        article_context = build_collage_article_context(article)
        return prompt_template.replace("{article_context}", article_context).strip()

    base_prompt = str(article.image_collage_prompt or "").strip()
    prefix = f"{base_prompt}. " if base_prompt else ""
    travel_policy = get_travel_blog_policy(blog=article.blog)
    if travel_policy is not None:
        contract = build_travel_image_contract(
            category_key=article.editorial_category_key,
            pattern_key=getattr(article, "article_pattern_key", None),
            pattern_id=getattr(article, "article_pattern_id", None),
            policy=travel_policy,
        )
        return f"{prefix}{contract}".strip()
    is_mystery = (
        getattr(article.blog, "profile_key", "") == "world_mystery"
        or str(getattr(article.blog, "content_category", "") or "").strip().lower() == "mystery"
    )
    if is_mystery:
        return (
            f"{prefix}"
            'Rewrite into one clear editorial panel-grid collage hero prompt with visible white gutters, '
            "clean grid layout, one balanced single-image composition, 2-4 grouped visual categories, realistic "
            "documentary mood, no text/logo/watermark, no gore, do not request separate image files, under 60 words."
        )
    return (
        f"{prefix}"
        "Create one hero-cover collage with exactly 9 distinct panels in a clear 3x3 grid, visible white gutters, "
        "a visually dominant center panel, realistic photography, no text overlay, and no logos."
    )
