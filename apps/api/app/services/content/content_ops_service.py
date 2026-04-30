from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.entities import (
    Article,
    Blog,
    ContentReviewAction,
    ContentReviewItem,
    PostStatus,
    SyncedBloggerPost,
)
from app.services.content.article_service import ensure_article_editorial_labels, estimate_reading_time
from app.services.content.blog_seo_meta_service import verify_article_seo_meta
from app.services.blogger.blogger_editor_service import BloggerEditorAutomationError, sync_article_search_description
from app.services.blogger.blogger_sync_service import sync_blogger_posts_for_blog
from app.services.integrations.google_sheet_service import (
    BLOGGER_SNAPSHOT_COLUMNS,
    QUALITY_COLUMNS,
    get_google_sheet_sync_config,
    sync_google_sheet_quality_tab,
)
from app.services.providers.factory import get_blogger_provider
from app.services.platform.publishing_service import rebuild_article_html, refresh_article_public_image, upsert_article_blogger_post
from app.services.integrations.settings_service import get_settings_map, upsert_settings

SOURCE_ARTICLE = "article"
SOURCE_SYNCED_POST = "synced_blogger_post"

REVIEW_KIND_DRAFT = "draft_quality"
REVIEW_KIND_PUBLISH = "publish_validation"
REVIEW_KIND_LIVE = "live_sync"

RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"

APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_AUTO_APPROVED = "auto_approved"
APPROVAL_REJECTED = "rejected"
APPROVAL_NOT_REQUIRED = "not_required"

APPLY_PENDING = "pending"
APPLY_AWAITING_APPROVAL = "awaiting_approval"
APPLY_APPLIED = "applied"
APPLY_FAILED = "failed"
APPLY_SKIPPED = "skipped"

LEARNING_PENDING = "pending"
LEARNING_REFERENCE = "reference_quality"
LEARNING_APPROVED = "approved"
LEARNING_REJECTED = "rejected"
LEARNING_EXCLUDED = "excluded"

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
URL_RE = re.compile(r"https?://[^\s<>\"]+")
HEADING_RE = re.compile(r"<h([23])[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
LINK_RE = re.compile(r"""href=["']([^"']+)["']""", re.IGNORECASE)
MARKDOWN_HEADING_RE = re.compile(r"(?m)^\s*(#{2,3})\s+(.+?)\s*$")
MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]+]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9가-힣]+|[ぁ-ん]+|[ァ-ヶー]+|[一-龯々]+")
SENTENCE_SPLIT_RE = re.compile(r"[.!?。！？]+\s+")

SAFE_DRAFT_PATCH_KEYS = {"meta_description", "excerpt", "faq_section", "named_entity_drift", "html_diff_ratio"}
SAFE_PUBLISH_PATCH_KEYS = {"meta_description", "search_description", "named_entity_drift", "html_diff_ratio"}
OVERVIEW_TAB_NAME = "전체 글 현황"
CONTENT_OVERVIEW_PROFILE_OPTIONS = {
    "korea_travel",
    "world_mystery",
}
DBS_VERSION = "dbs-v1"

TRAVEL_CATEGORY_HINTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "travel": ("Travel", ("travel", "trip", "route", "itinerary", "walk", "neighborhood", "local")),
    "culture": ("Culture", ("culture", "festival", "event", "exhibition", "museum", "heritage", "idol", "filming")),
    "food": ("Food", ("food", "restaurant", "market", "cafe", "eatery", "korean food", "dining")),
}

MYSTERY_CATEGORY_HINTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "case-files": ("Case Files", ("case", "incident", "investigation", "evidence", "timeline", "disappearance", "murder")),
    "legends-lore": ("Legends & Lore", ("legend", "folklore", "myth", "urban legend", "scp", "lore", "haunted")),
    "mystery-archives": ("Mystery Archives", ("archive", "historical", "record", "document", "expedition", "manuscript", "chronology")),
}


class ContentOpsError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_str(value: object | None) -> str:
    return str(value or "").strip()


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.replace(microsecond=0).isoformat()


def _plain_text(value: str | None) -> str:
    without_tags = TAG_RE.sub(" ", value or "")
    return WS_RE.sub(" ", without_tags).strip()


def _normalized_hash_input(value: str | None) -> str:
    return _plain_text(value).lower()


def _content_hash(*parts: str | None) -> str:
    payload = "||".join(_normalized_hash_input(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _excerpt_from_text(text: str, *, limit: int = 180) -> str:
    cleaned = WS_RE.sub(" ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    shortened = cleaned[: limit + 1]
    return (shortened.rsplit(" ", 1)[0].strip() or shortened[:limit].strip()).rstrip(" ,.;:-") + "..."


def _derive_excerpt(article: Article) -> str:
    return _excerpt_from_text(_plain_text(article.html_article), limit=180)


def _derive_meta_description(article: Article, excerpt: str | None = None) -> str:
    text = (excerpt or article.excerpt or _derive_excerpt(article)).strip()
    if not text:
        text = article.title.strip()
    meta = text[:160].strip()
    if len(meta) < 60:
        meta = f"{article.title.strip()}: {_excerpt_from_text(_plain_text(article.html_article), limit=140)}".strip()
    return meta[:160].strip()


def _derive_faq(article: Article) -> list[dict[str, str]]:
    topic = article.title.strip() or "this topic"
    context = _excerpt_from_text(_plain_text(article.html_article), limit=180)
    return [
        {
            "question": f"What should readers know first about {topic}?",
            "answer": context or f"This article explains the main context behind {topic}.",
        },
        {
            "question": f"Why does {topic} matter for readers?",
            "answer": article.excerpt.strip() or context or f"The article summarizes the key practical context around {topic}.",
        },
    ]


def _build_issue(code: str, message: str, *, severity: str = "warning", patchable: bool = False) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "severity": severity,
        "patchable": patchable,
    }


def _clamp_score(value: int) -> int:
    return max(0, min(100, int(value)))


def _setting_enabled(settings_map: dict[str, str], key: str, *, default: bool = False) -> bool:
    raw = settings_map.get(key)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _parse_int(value: str | None, default: int = 0) -> int:
    try:
        return int(str(value or default).strip())
    except (TypeError, ValueError):
        return default


def _clamp_component(value: int | float, *, minimum: int = 0, maximum: int = 100) -> int:
    return max(minimum, min(maximum, int(round(value))))


def normalize_similarity_text(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", _plain_text(value))

    def _replace_url(match: re.Match[str]) -> str:
        raw_url = match.group(0)
        try:
            parsed = urlsplit(raw_url)
            if not parsed.netloc:
                return ""
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        except ValueError:
            return ""

    without_tracking = URL_RE.sub(_replace_url, normalized)
    lowered = without_tracking.lower()
    return WS_RE.sub(" ", lowered).strip()


def extract_outline_sequence(html_value: str | None) -> list[str]:
    if not (html_value or "").strip():
        return []
    outlines: list[str] = []
    for match in HEADING_RE.finditer(html_value or ""):
        level = match.group(1)
        text = normalize_similarity_text(match.group(2))
        if text:
            outlines.append(f"h{level}:{text}")
    return outlines


def _tokenize_words(value: str | None) -> list[str]:
    tokens = WORD_RE.findall(normalize_similarity_text(value))
    return [token for token in tokens if len(token) >= 2]


def _token_set_ratio(left: str | None, right: str | None) -> float:
    left_set = set(_tokenize_words(left))
    right_set = set(_tokenize_words(right))
    if not left_set or not right_set:
        return 0.0
    return (2.0 * len(left_set.intersection(right_set))) / float(len(left_set) + len(right_set))


def _char_ngram_counts(value: str, *, min_n: int = 3, max_n: int = 5) -> Counter[str]:
    compacted = WS_RE.sub("", value or "")
    counts: Counter[str] = Counter()
    for n in range(min_n, max_n + 1):
        if len(compacted) < n:
            continue
        for index in range(len(compacted) - n + 1):
            counts[compacted[index : index + n]] += 1
    return counts


def _build_tfidf_vectors(texts: list[str]) -> tuple[list[dict[str, float]], list[float]]:
    if not texts:
        return [], []
    counts = [_char_ngram_counts(text) for text in texts]
    document_frequency: Counter[str] = Counter()
    for counter in counts:
        document_frequency.update(counter.keys())

    total_docs = float(len(counts))
    vectors: list[dict[str, float]] = []
    norms: list[float] = []
    for counter in counts:
        weighted: dict[str, float] = {}
        norm_sq = 0.0
        for ngram, tf in counter.items():
            idf = math.log((total_docs + 1.0) / (float(document_frequency.get(ngram, 0)) + 1.0)) + 1.0
            weight = (1.0 + math.log(float(tf))) * idf
            weighted[ngram] = weight
            norm_sq += weight * weight
        vectors.append(weighted)
        norms.append(math.sqrt(norm_sq))
    return vectors, norms


def _cosine_similarity(left: dict[str, float], left_norm: float, right: dict[str, float], right_norm: float) -> float:
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    dot = 0.0
    for key, weight in left.items():
        right_weight = right.get(key)
        if right_weight is None:
            continue
        dot += weight * right_weight
    if dot <= 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def compute_similarity_analysis(
    items: list[dict[str, Any]],
    *,
    key_field: str = "key",
    title_field: str = "title",
    body_field: str = "body_html",
    url_field: str = "url",
) -> dict[str, dict[str, Any]]:
    if not items:
        return {}

    normalized_items: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        key = str(item.get(key_field) or f"item-{index + 1}")
        body_html = str(item.get(body_field) or "")
        normalized_items.append(
            {
                "key": key,
                "title": str(item.get(title_field) or ""),
                "url": str(item.get(url_field) or ""),
                "body": normalize_similarity_text(body_html),
                "outline": "|".join(extract_outline_sequence(body_html)),
            }
        )

    vectors, norms = _build_tfidf_vectors([row["body"] for row in normalized_items])
    results: dict[str, dict[str, Any]] = {}
    for row in normalized_items:
        results[row["key"]] = {
            "similarity_score": 0.0,
            "most_similar_key": "",
            "most_similar_url": "",
            "body_score": 0.0,
            "title_score": 0.0,
            "outline_score": 0.0,
        }

    if len(normalized_items) <= 1:
        return results

    for left_index in range(len(normalized_items)):
        for right_index in range(left_index + 1, len(normalized_items)):
            left = normalized_items[left_index]
            right = normalized_items[right_index]
            body_score = _cosine_similarity(vectors[left_index], norms[left_index], vectors[right_index], norms[right_index])
            title_score = _token_set_ratio(left["title"], right["title"])
            outline_score = 0.0
            if left["outline"] and right["outline"]:
                outline_score = SequenceMatcher(None, left["outline"], right["outline"]).ratio()
            similarity_score = round((0.70 * body_score + 0.20 * title_score + 0.10 * outline_score) * 100.0, 1)

            left_result = results[left["key"]]
            if similarity_score > float(left_result["similarity_score"]):
                left_result.update(
                    {
                        "similarity_score": similarity_score,
                        "most_similar_key": right["key"],
                        "most_similar_url": right["url"],
                        "body_score": round(body_score, 4),
                        "title_score": round(title_score, 4),
                        "outline_score": round(outline_score, 4),
                    }
                )

            right_result = results[right["key"]]
            if similarity_score > float(right_result["similarity_score"]):
                right_result.update(
                    {
                        "similarity_score": similarity_score,
                        "most_similar_key": left["key"],
                        "most_similar_url": left["url"],
                        "body_score": round(body_score, 4),
                        "title_score": round(title_score, 4),
                        "outline_score": round(outline_score, 4),
                    }
                )
    return results


def _split_sentences(value: str) -> list[str]:
    if not value.strip():
        return []
    return [segment.strip() for segment in SENTENCE_SPLIT_RE.split(value) if segment.strip()]


def extract_faq_section_from_html(html_body: str | None) -> list[dict[str, str]]:
    """Extract visible FAQ pairs embedded in Cloudflare/body HTML for scoring only."""
    html_value = html_body or ""
    if not html_value.strip():
        return []

    start_match = re.search(r"(?is)<h2[^>]*>\s*(?:FAQ|\uc790\uc8fc \ubb3b\ub294 \uc9c8\ubb38)\s*</h2>", html_value)
    if start_match:
        faq_html = html_value[start_match.end() :]
        next_h2 = re.search(r"(?is)<h2\b", faq_html)
        if next_h2:
            faq_html = faq_html[: next_h2.start()]
        pairs: list[dict[str, str]] = []
        for match in re.finditer(r"(?is)<h3[^>]*>(.*?)</h3>\s*<p[^>]*>(.*?)</p>", faq_html):
            question = _plain_text(match.group(1))
            answer = _plain_text(match.group(2))
            if len(question) >= 5 and len(answer) >= 10:
                pairs.append({"question": question, "answer": answer})
        if pairs:
            return pairs[:6]

    markdown_match = re.search(r"(?is)(?:^|\n)##\s*(?:FAQ|\uc790\uc8fc \ubb3b\ub294 \uc9c8\ubb38)\s*(.*)$", html_value)
    if not markdown_match:
        return []
    faq_text = markdown_match.group(1)
    pairs = []
    for match in re.finditer(r"(?is)(?:^|\n)###\s*(.*?)\n+(.+?)(?=(?:\n###\s*)|\Z)", faq_text):
        question = _plain_text(match.group(1))
        answer = _plain_text(match.group(2))
        if len(question) >= 5 and len(answer) >= 10:
            pairs.append({"question": question, "answer": answer})
    return pairs[:6]


def _heading_counts(html_value: str) -> tuple[int, int]:
    h2_count = 0
    h3_count = 0
    for level, _text in HEADING_RE.findall(html_value):
        if level == "2":
            h2_count += 1
        elif level == "3":
            h3_count += 1
    for hashes, _text in MARKDOWN_HEADING_RE.findall(html_value or ""):
        if len(hashes) == 2:
            h2_count += 1
        elif len(hashes) == 3:
            h3_count += 1
    return h2_count, h3_count


def _extract_links(html_value: str) -> list[str]:
    html_links = [match.strip() for match in LINK_RE.findall(html_value or "") if match.strip()]
    markdown_links = [match.strip() for match in MARKDOWN_LINK_RE.findall(html_value or "") if match.strip()]
    return [*html_links, *markdown_links]


def compute_ctr_score(*, title: str, excerpt: str | None = None, html_body: str | None = None) -> dict[str, Any]:
    title_text = (title or "").strip()
    excerpt_text = (excerpt or "").strip()
    plain_body = _plain_text(html_body)
    combined_text = f"{title_text} {excerpt_text} {plain_body[:600]}".strip().lower()
    title_words = _tokenize_words(title_text)
    title_length = len(title_text)

    if 28 <= title_length <= 88 and 4 <= len(title_words) <= 14:
        headline_fit = 30
    elif 20 <= title_length <= 110 and len(title_words) >= 3:
        headline_fit = 24
    else:
        headline_fit = 16

    specificity_tokens = [
        "2026",
        "2025",
        "guide",
        "checklist",
        "timeline",
        "route",
        "map",
        "cost",
        "budget",
        "schedule",
        "best",
        "near",
        "seoul",
        "busan",
        "korea",
        "mystery",
        "case",
        "festival",
        "museum",
        "travel",
        "ruta",
        "gu?a",
        "viaje",
        "consejos",
        "horario",
        "se?l",
        "corea",
        "gu\u00eda",
        "se\u00fal",
        "\u30eb\u30fc\u30c8",
        "\u6563\u6b69",
        "\u65c5\u884c",
        "\u97d3\u56fd",
        "\u30bd\u30a6\u30eb",
        "\u6df7\u96d1",
        "\u907f\u3051\u308b",
        "\u6642\u9593",
        "\u5224\u65ad",
        "\u99c5",
        "\u5915\u65b9",
        "???",
        "??",
        "??",
        "??",
        "???",
        "??",
        "???",
        "??",
        "??",
        "?",
        "??",
        "가이드",
        "체크리스트",
        "타임라인",
        "동선",
        "코스",
        "비용",
        "예산",
        "일정",
        "서울",
        "부산",
        "한국",
        "미스터리",
        "사건",
        "축제",
        "박물관",
        "여행",
    ]
    specificity_hits = len([token for token in specificity_tokens if token in combined_text])
    if specificity_hits >= 5:
        specificity_score = 25
    elif specificity_hits >= 3:
        specificity_score = 20
    elif specificity_hits >= 1:
        specificity_score = 15
    else:
        specificity_score = 10

    intent_tokens = [
        "how",
        "why",
        "what",
        "where",
        "when",
        "best",
        "top",
        "guide",
        "tips",
        "checklist",
        "timeline",
        "review",
        "how to",
        "ruta",
        "gu?a",
        "consejos",
        "evitar",
        "elegir",
        "cu?ndo",
        "d?nde",
        "gu\u00eda",
        "cu\u00e1ndo",
        "d\u00f3nde",
        "\u304a\u3059\u3059\u3081",
        "\u884c\u304d\u65b9",
        "\u907f\u3051\u308b",
        "\u9078\u3076",
        "\u5224\u65ad",
        "\u6df7\u96d1",
        "\u30c1\u30a7\u30c3\u30af",
        "\u6642\u9593",
        "????",
        "???",
        "???",
        "??",
        "??",
        "??",
        "????",
        "??",
        "왜",
        "무엇",
        "어디",
        "언제",
        "가이드",
        "팁",
        "정리",
        "비교",
        "추천",
        "후기",
        "방법",
    ]
    intent_hits = len([token for token in intent_tokens if token in combined_text])
    if intent_hits >= 4:
        click_intent_score = 20
    elif intent_hits >= 2:
        click_intent_score = 16
    elif intent_hits >= 1:
        click_intent_score = 12
    else:
        click_intent_score = 8

    if 70 <= len(excerpt_text) <= 180:
        excerpt_support_score = 15
    elif len(excerpt_text) >= 35:
        excerpt_support_score = 11
    else:
        excerpt_support_score = 7

    freshness_hits = len(re.findall(r"\b(?:18|19|20)\d{2}\b", combined_text)) + len(
        re.findall(r"(?:\d{4}년|\d{1,2}월|봄|여름|가을|겨울)", combined_text)
    )
    if freshness_hits >= 2:
        freshness_score = 10
    elif freshness_hits == 1:
        freshness_score = 7
    else:
        freshness_score = 4

    ctr_score = _clamp_component(
        headline_fit + specificity_score + click_intent_score + excerpt_support_score + freshness_score,
        maximum=100,
    )
    return {
        "ctr_score": ctr_score,
        "ctr_breakdown": {
            "headline_fit": headline_fit,
            "specificity": specificity_score,
            "click_intent": click_intent_score,
            "excerpt_support": excerpt_support_score,
            "freshness": freshness_score,
        },
    }


def compute_seo_geo_scores(
    *,
    title: str,
    html_body: str,
    excerpt: str | None = None,
    faq_section: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not faq_section:
        faq_section = extract_faq_section_from_html(html_body)
    plain_text = _plain_text(html_body)
    plain_text_lower = plain_text.lower()
    intro_text = plain_text[:600].lower()
    sentence_list = _split_sentences(plain_text)
    sentence_word_lengths = [len(WORD_RE.findall(sentence)) for sentence in sentence_list if sentence.strip()]
    links = _extract_links(html_body)
    unique_links = {link for link in links if link}
    internal_link_count = len(
        [
            link
            for link in unique_links
            if link.startswith("/")
            or "dongriarchive.com" in link
            or "dongdonggri.blogspot.com" in link
            or "blogspot.com" in link
        ]
    )
    h2_count, h3_count = _heading_counts(html_body)

    title_words = _tokenize_words(title)
    title_length = len(title.strip())
    if 36 <= title_length <= 96 and 5 <= len(title_words) <= 16:
        title_score = 15
    elif 24 <= title_length <= 120 and len(title_words) >= 3:
        title_score = 11
    else:
        title_score = 7

    intro_keywords = [token for token in title_words if len(token) >= 4][:10]
    intro_hits = len([token for token in intro_keywords if token in intro_text])
    intro_coverage = (intro_hits / len(intro_keywords)) if intro_keywords else 0.0
    if intro_coverage >= 0.5:
        intro_score = 10
    elif intro_coverage >= 0.3:
        intro_score = 7
    else:
        intro_score = 4

    if h2_count >= 4 and h3_count >= 2:
        structure_score = 20
    elif h2_count >= 3 and h3_count >= 1:
        structure_score = 16
    elif h2_count >= 2:
        structure_score = 12
    elif h2_count >= 1:
        structure_score = 8
    else:
        structure_score = 4

    unique_sentence_ratio = 0.0
    if sentence_list:
        lowered_sentences = [sentence.lower() for sentence in sentence_list]
        unique_sentence_ratio = len(set(lowered_sentences)) / float(len(lowered_sentences))
    plain_length = len(plain_text)
    if plain_length >= 7000 and unique_sentence_ratio >= 0.86:
        density_score = 20
    elif plain_length >= 5000 and unique_sentence_ratio >= 0.80:
        density_score = 17
    elif plain_length >= 3500 and unique_sentence_ratio >= 0.72:
        density_score = 14
    elif plain_length >= 2500:
        density_score = 11
    else:
        density_score = 7
    if unique_sentence_ratio < 0.60:
        density_score -= 3
    density_score = _clamp_component(density_score, minimum=0, maximum=20)

    duplicate_links = len(links) - len(unique_links)
    if internal_link_count >= 3:
        links_score = 15
    elif internal_link_count == 2:
        links_score = 11
    elif internal_link_count == 1:
        links_score = 8
    else:
        links_score = 4
    if duplicate_links >= 2:
        links_score -= 2
    links_score = _clamp_component(links_score, minimum=0, maximum=15)

    if sentence_word_lengths:
        avg_words = sum(sentence_word_lengths) / float(len(sentence_word_lengths))
        variance = sum((length - avg_words) ** 2 for length in sentence_word_lengths) / float(len(sentence_word_lengths))
        std_words = math.sqrt(variance)
        long_ratio = len([length for length in sentence_word_lengths if length >= 40]) / float(len(sentence_word_lengths))
    else:
        avg_words = 0.0
        std_words = 0.0
        long_ratio = 1.0
    if 12.0 <= avg_words <= 28.0:
        readability_score = 13
    elif 8.0 <= avg_words <= 35.0:
        readability_score = 10
    else:
        readability_score = 7
    readability_score += 5 if 4.0 <= std_words <= 18.0 else 3
    if long_ratio > 0.25:
        readability_score -= 3
    readability_score = _clamp_component(readability_score, minimum=0, maximum=20)

    seo_score = _clamp_component(
        title_score + intro_score + structure_score + density_score + links_score + readability_score,
        maximum=100,
    )

    intent_cues = [
        "this article",
        "this guide",
        "what happened",
        "how to",
        "why",
        "timeline",
        "we cover",
        "in this guide",
        "esta guía",
        "esta ruta",
        "en esta guía",
        "\u3053\u306e\u8a18\u4e8b",
        "\u3053\u306e\u30eb\u30fc\u30c8",
        "\u5224\u65ad",
        "\u907f\u3051\u308b",
        "\u9078\u3076",
        "이 글",
        "이 가이드",
        "무엇",
        "어떻게",
        "왜",
        "타임라인",
        "정리",
        "안내",
        "소개",
        "핵심",
        "방법",
    ]
    intent_hits = len([cue for cue in intent_cues if cue in intro_text])
    if intent_hits >= 3:
        intent_score = 20
    elif intent_hits == 2:
        intent_score = 15
    elif intent_hits == 1:
        intent_score = 10
    else:
        intent_score = 6

    year_matches = set(re.findall(r"\b(?:18|19|20)\d{2}\b", plain_text)) | set(re.findall(r"(?:18|19|20)\d{2}?", plain_text))
    named_entities = {
        match.strip()
        for match in re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\b", plain_text)
        if len(match.strip()) >= 4
    }
    korean_named_entities = {
        match.strip()
        for match in re.findall(
            r"[가-힣]{2,}(?:시|군|구|동|읍|면|리|역|공원|박물관|미술관|궁|거리|시장|광장|한옥마을|해변|항구)",
            plain_text,
        )
        if len(match.strip()) >= 3
    }
    english_location_hits = len(
        [
            token
            for token in [
                "seoul", "busan", "korea", "england", "france", "europe", "asia", "island", "tower", "lighthouse",
                "se?l", "corea", "isla", "ruta", "???", "??", "??", "????", "??", "??", "???", "??", "??",
                "se\u00fal", "corea", "\u30bd\u30a6\u30eb", "\u97d3\u56fd", "\u6f22\u6c5f", "\u30ce\u30c9\u30a5\u30eb",
                "\u4e8c\u6751", "\u65b0\u6797", "\u30dd\u30e9\u30e1", "\u5f18\u5927", "\u6c5f\u5357",
            ]
            if token in plain_text_lower
        ]
    )
    korean_location_hits = len(
        [
            token
            for token in [
                "서울",
                "부산",
                "인천",
                "대구",
                "광주",
                "대전",
                "울산",
                "제주",
                "종로",
                "강남",
                "강북",
                "여의도",
                "인사동",
                "북촌",
                "명동",
                "홍대",
                "성수",
                "한강",
                "박물관",
                "미술관",
            ]
            if token in plain_text
        ]
    )
    location_hits = english_location_hits + korean_location_hits
    if (
        len(named_entities) >= 6
        or len(korean_named_entities) >= 5
        or (len(year_matches) >= 2 and location_hits >= 1)
    ):
        entity_score = 20
    elif len(named_entities) >= 4 or len(korean_named_entities) >= 3 or len(year_matches) >= 1:
        entity_score = 15
    elif len(named_entities) >= 2 or len(korean_named_entities) >= 1:
        entity_score = 11
    else:
        entity_score = 7

    evidence_keywords = [
        "source",
        "archive",
        "record",
        "document",
        "according",
        "reported",
        "witness",
        "official",
        "investigation",
        "evidence",
        "actualizado",
        "confirmar",
        "oficial",
        "aprox",
        "\u73fe\u5730",
        "\u78ba\u8a8d",
        "\u76ee\u5b89",
        "\u7d04",
        "\u66f4\u65b0",
        "\u5224\u65ad",
        "\u516c\u5f0f",
        "??",
        "??",
        "??",
        "?",
        "??",
        "??",
        "??",
        "출처",
        "아카이브",
        "기록",
        "문서",
        "자료",
        "근거",
        "공식",
        "보도",
        "증언",
        "조사",
        "통계",
        "연구",
    ]
    evidence_hits = len([keyword for keyword in evidence_keywords if keyword in plain_text_lower])
    if evidence_hits >= 4 and len(unique_links) >= 1:
        evidence_score = 20
    elif evidence_hits >= 2:
        evidence_score = 15
    elif evidence_hits >= 1:
        evidence_score = 11
    else:
        evidence_score = 6

    actionable_keywords = [
        "checklist",
        "tips",
        "route",
        "schedule",
        "timeline",
        "step",
        "visit",
        "prepare",
        "transport",
        "budget",
        "plan",
        "safety",
        "ruta",
        "horario",
        "consejos",
        "transporte",
        "presupuesto",
        "reserva",
        "evitar",
        "\u30c1\u30a7\u30c3\u30af",
        "\u30eb\u30fc\u30c8",
        "\u6642\u9593",
        "\u99c5",
        "\u6df7\u96d1",
        "\u4e88\u7d04",
        "\u4ea4\u901a",
        "\u4e88\u7b97",
        "\u98df\u4e8b",
        "\u4f11\u61a9",
        "\u5224\u65ad",
        "????",
        "???",
        "??",
        "?",
        "??",
        "??",
        "??",
        "??",
        "??",
        "??",
        "??",
        "체크리스트",
        "팁",
        "코스",
        "동선",
        "일정",
        "단계",
        "방문",
        "준비",
        "교통",
        "예산",
        "계획",
        "주의",
        "예약",
        "운영시간",
        "입장",
        "위치",
        "운영",
        "기준",
        "검증",
        "배포",
        "롤백",
        "로그",
        "재시도",
        "실패",
        "검수",
        "점검",
        "적용",
        "절차",
        "흐름",
        "우선순위",
        "판단",
    ]
    actionable_hits = len([keyword for keyword in actionable_keywords if keyword in plain_text_lower])
    if actionable_hits >= 6:
        actionable_score = 20
    elif actionable_hits >= 4:
        actionable_score = 16
    elif actionable_hits >= 2:
        actionable_score = 12
    else:
        actionable_score = 7

    month_hits = len(
        re.findall(
            r"\b(january|february|march|april|may|june|july|august|september|october|november|december|enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\b",
            plain_text_lower,
        )
    ) + len(
        re.findall(
            "(?:\\d{1,2}\\u6708|\\u6625|\\u590f|\\u79cb|\\u51ac|\\u5915\\u65b9|\\u65e5\\u6ca1|\\u9031\\u672b|\\u5e73\\u65e5|\\u591c)",
            plain_text,
        )
    )
    korean_time_hits = len(re.findall(r"(?:\d{4}년|\d{1,2}월|봄|여름|가을|겨울)", plain_text))
    time_mentions = len(year_matches) + month_hits + korean_time_hits
    if time_mentions >= 3:
        recency_score = 10
    elif time_mentions >= 1:
        recency_score = 7
    else:
        recency_score = 4

    faq_items = [item for item in (faq_section or []) if isinstance(item, dict)]
    valid_faq_count = len(
        [
            item
            for item in faq_items
            if len(str(item.get("question") or "").strip()) >= 5 and len(str(item.get("answer") or "").strip()) >= 10
        ]
    )
    has_summary_heading = any(
        token in "|".join(extract_outline_sequence(html_body)).lower() for token in ["faq", "summary", "요약"]
    )
    if valid_faq_count >= 2:
        faq_score = 10
    elif valid_faq_count == 1:
        faq_score = 7
    elif has_summary_heading:
        faq_score = 5
    else:
        faq_score = 3

    geo_score = _clamp_component(
        intent_score + entity_score + evidence_score + actionable_score + recency_score + faq_score,
        maximum=100,
    )

    ctr_payload = compute_ctr_score(title=title, excerpt=excerpt, html_body=html_body)

    return {
        "seo_score": seo_score,
        "geo_score": geo_score,
        "ctr_score": int(ctr_payload.get("ctr_score") or 0),
        "seo_breakdown": {
            "title_intent": title_score,
            "intro_topic_match": intro_score,
            "heading_structure": structure_score,
            "information_density": density_score,
            "internal_links": links_score,
            "readability": readability_score,
        },
        "geo_breakdown": {
            "intent_response": intent_score,
            "entity_specificity": entity_score,
            "evidence_context": evidence_score,
            "actionable_depth": actionable_score,
            "time_context": recency_score,
            "faq_summary": faq_score,
        },
        "ctr_breakdown": dict(ctr_payload.get("ctr_breakdown") or {}),
        "plain_text_length": plain_length,
        "sentence_count": len(sentence_list),
        "excerpt_length": len((excerpt or "").strip()),
    }


def _dbs_grade(score: float) -> str:
    value = float(score)
    if value >= 85.0:
        return "A"
    if value >= 75.0:
        return "B"
    if value >= 65.0:
        return "C"
    if value >= 55.0:
        return "D"
    return "F"


def compute_dbs_score(
    *,
    seo_score: float,
    geo_score: float,
    ctr_score: float,
    plain_text_length: int,
    sentence_count: int,
    excerpt_length: int,
) -> dict[str, Any]:
    seo = _clamp_component(float(seo_score), minimum=0, maximum=100)
    geo = _clamp_component(float(geo_score), minimum=0, maximum=100)
    ctr = _clamp_component(float(ctr_score), minimum=0, maximum=100)

    base = (0.40 * seo) + (0.35 * geo) + (0.25 * ctr)

    thin_penalty = 10 if plain_text_length < 1200 else (5 if plain_text_length < 2000 else 0)
    weak_excerpt_penalty = 3 if excerpt_length < 60 else (1 if excerpt_length < 90 else 0)
    minimum_component = min(seo, geo, ctr)
    imbalance_penalty = 8 if minimum_component < 50 else (4 if minimum_component < 60 else 0)
    all_green_bonus = 4 if (seo >= 80 and geo >= 75 and ctr >= 70) else (2 if (seo >= 70 and geo >= 60 and ctr >= 60) else 0)

    score = _clamp_component(
        base - thin_penalty - weak_excerpt_penalty - imbalance_penalty + all_green_bonus,
        minimum=0,
        maximum=100,
    )

    content_factor = min(max(float(plain_text_length), 0.0) / 2500.0, 1.0)
    sentence_factor = min(max(float(sentence_count), 0.0) / 18.0, 1.0)
    excerpt_factor = 1.0 if excerpt_length >= 90 else (0.7 if excerpt_length >= 60 else 0.4)
    confidence = round(
        _clamp_component(
            100.0 * ((0.50 * content_factor) + (0.30 * sentence_factor) + (0.20 * excerpt_factor)),
            minimum=0.0,
            maximum=100.0,
        ),
        1,
    )
    confidence_label = "high" if confidence >= 80 else ("medium" if confidence >= 60 else "low")

    return {
        "dbs_score": round(float(score), 1),
        "dbs_grade": _dbs_grade(float(score)),
        "dbs_confidence": confidence,
        "dbs_confidence_label": confidence_label,
        "dbs_version": DBS_VERSION,
        "dbs_components": {
            "seo_score": int(seo),
            "geo_score": int(geo),
            "ctr_score": int(ctr),
        },
        "dbs_adjustments": {
            "thin_penalty": thin_penalty,
            "weak_excerpt_penalty": weak_excerpt_penalty,
            "imbalance_penalty": imbalance_penalty,
            "all_green_bonus": all_green_bonus,
        },
    }


def compute_blog_dbs_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    live_rows = [row for row in rows if _safe_str(row.get("status")).lower() in {"published", "live"}]
    if not live_rows:
        return {
            "blog_dbs_score": 0.0,
            "blog_dbs_grade": "F",
            "blog_dbs_confidence": 0.0,
            "post_count": 0,
            "recent_90d_post_count": 0,
            "weighted_post_avg": 0.0,
            "gate_pass_rate": 0.0,
            "consistency_score": 0.0,
            "dbs_version": DBS_VERSION,
        }

    now_utc = _utc_now()

    def _age_days(value: str) -> int:
        raw = _safe_str(value)
        if not raw:
            return 9999
        normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return 9999
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        delta = now_utc - parsed.astimezone(timezone.utc)
        return max(int(delta.days), 0)

    weighted_sum = 0.0
    total_weight = 0.0
    scores: list[float] = []
    confidence_values: list[float] = []
    recent_90d = 0
    gate_pass_count = 0

    for row in live_rows:
        score = float(row.get("dbs_score") or 0.0)
        confidence = float(row.get("dbs_confidence") or 0.0)
        age_days = _age_days(_safe_str(row.get("published_at")) or _safe_str(row.get("updated_at")) or _safe_str(row.get("created_at")))
        recency_weight = 1.0 if age_days <= 30 else (0.8 if age_days <= 90 else (0.6 if age_days <= 180 else 0.4))
        confidence_weight = max(min(confidence / 100.0, 1.0), 0.5)
        weight = recency_weight * confidence_weight
        weighted_sum += score * weight
        total_weight += weight
        scores.append(score)
        confidence_values.append(confidence)
        if age_days <= 90:
            recent_90d += 1
        seo = float(row.get("seo_score") or 0.0)
        geo = float(row.get("geo_score") or 0.0)
        ctr = float(row.get("ctr_score") or 0.0)
        if seo >= 70.0 and geo >= 60.0 and ctr >= 60.0:
            gate_pass_count += 1

    weighted_post_avg = (weighted_sum / total_weight) if total_weight > 0 else 0.0
    gate_pass_rate = (float(gate_pass_count) / float(len(live_rows))) * 100.0
    if len(scores) >= 2:
        mean_score = sum(scores) / float(len(scores))
        variance = sum((score - mean_score) ** 2 for score in scores) / float(len(scores))
        stddev = math.sqrt(variance)
    else:
        stddev = 0.0
    consistency_score = _clamp_component(100.0 - (2.0 * stddev), minimum=0.0, maximum=100.0)
    blog_dbs_score = _clamp_component(
        (0.75 * weighted_post_avg) + (0.15 * gate_pass_rate) + (0.10 * consistency_score),
        minimum=0.0,
        maximum=100.0,
    )

    avg_post_confidence = (sum(confidence_values) / float(len(confidence_values))) if confidence_values else 0.0
    sample_factor = min(float(len(live_rows)) / 30.0, 1.0)
    freshness_factor = min(float(recent_90d) / 12.0, 1.0)
    blog_confidence = _clamp_component(
        100.0
        * (
            (0.60 * (avg_post_confidence / 100.0))
            + (0.25 * sample_factor)
            + (0.15 * freshness_factor)
        ),
        minimum=0.0,
        maximum=100.0,
    )

    return {
        "blog_dbs_score": round(float(blog_dbs_score), 1),
        "blog_dbs_grade": _dbs_grade(float(blog_dbs_score)),
        "blog_dbs_confidence": round(float(blog_confidence), 1),
        "post_count": len(live_rows),
        "recent_90d_post_count": int(recent_90d),
        "weighted_post_avg": round(float(weighted_post_avg), 1),
        "gate_pass_rate": round(float(gate_pass_rate), 1),
        "consistency_score": round(float(consistency_score), 1),
        "dbs_version": DBS_VERSION,
    }


def _content_ops_dir() -> Path:
    return Path(settings.storage_root) / "training" / "content-ops"


def _learning_snapshot_paths() -> tuple[Path, Path, Path]:
    base_dir = _content_ops_dir()
    base_dir.mkdir(parents=True, exist_ok=True)
    return (
        base_dir / "curated-learning.jsonl",
        base_dir / "curated-learning.manifest.json",
        base_dir / "prompt-memory.json",
    )


def _load_article(db: Session, article_id: int) -> Article | None:
    return db.execute(
        select(Article)
        .where(Article.id == article_id)
        .options(
            selectinload(Article.blog),
            selectinload(Article.image),
            selectinload(Article.blogger_post),
            selectinload(Article.publish_queue_items),
        )
    ).scalar_one_or_none()


def _load_synced_post(db: Session, synced_post_id: int) -> SyncedBloggerPost | None:
    return db.execute(
        select(SyncedBloggerPost)
        .where(SyncedBloggerPost.id == synced_post_id)
        .options(selectinload(SyncedBloggerPost.blog))
    ).scalar_one_or_none()


def _find_review_item(db: Session, *, source_type: str, source_id: str, review_kind: str) -> ContentReviewItem | None:
    return db.execute(
        select(ContentReviewItem)
        .where(
            ContentReviewItem.source_type == source_type,
            ContentReviewItem.source_id == source_id,
            ContentReviewItem.review_kind == review_kind,
        )
        .options(selectinload(ContentReviewItem.actions))
    ).scalar_one_or_none()


def _log_review_action(
    db: Session,
    *,
    item: ContentReviewItem,
    action: str,
    actor: str,
    channel: str,
    result_payload: dict[str, Any] | None = None,
) -> ContentReviewAction:
    row = ContentReviewAction(
        item_id=item.id,
        action=action,
        actor=actor,
        channel=channel,
        result_payload=result_payload or {},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    db.refresh(item)
    return row


def _record_search_sync_state(
    db: Session,
    *,
    article: Article,
    status: str,
    message: str,
    editor_url: str | None = None,
    cdp_url: str | None = None,
) -> None:
    if not article.blogger_post:
        return
    payload = dict(article.blogger_post.response_payload or {})
    payload["search_description_sync"] = {
        "status": status,
        "message": message,
        "editor_url": editor_url or "",
        "cdp_url": cdp_url or "",
        "updated_at": _utc_now().isoformat(),
    }
    article.blogger_post.response_payload = payload
    db.add(article.blogger_post)
    db.commit()
    db.refresh(article.blogger_post)


def _has_successful_search_sync(article: Article) -> bool:
    if not article.blogger_post:
        return False
    payload = dict(article.blogger_post.response_payload or {})
    sync_payload = payload.get("search_description_sync")
    if not isinstance(sync_payload, dict):
        return False
    return str(sync_payload.get("status") or "").strip().lower() in {"ok", "updated", "synced"}


def _initial_learning_state(*, score: int, issues: list[dict[str, Any]]) -> str:
    if any(str(issue.get("severity")) == "error" for issue in issues):
        return LEARNING_EXCLUDED
    if not issues and score >= 85:
        return LEARNING_REFERENCE
    return LEARNING_PENDING


def _draft_review_payload(article: Article) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    patch: dict[str, Any] = {"named_entity_drift": False, "html_diff_ratio": 0.0}
    score = 100

    excerpt = (article.excerpt or "").strip()
    meta_description = (article.meta_description or "").strip()
    faq_items = [item for item in (article.faq_section or []) if isinstance(item, dict)]

    if len(meta_description) < 60 or len(meta_description) > 170:
        issues.append(
            _build_issue(
                "meta_description_length",
                "Meta description length is outside the safe operating range.",
                patchable=True,
            )
        )
        patch["meta_description"] = _derive_meta_description(article, excerpt or None)
        score -= 15

    if len(excerpt) < 70 or len(excerpt) > 220:
        issues.append(
            _build_issue(
                "excerpt_length",
                "Excerpt is too short or too long for the review target.",
                patchable=True,
            )
        )
        patch["excerpt"] = _derive_excerpt(article)
        score -= 12

    if len(faq_items) < 2:
        issues.append(
            _build_issue(
                "faq_coverage",
                "FAQ coverage is missing or too shallow.",
                patchable=True,
            )
        )
        patch["faq_section"] = _derive_faq(article)
        score -= 10

    if article.blog and (
        article.reading_time_minutes < article.blog.target_reading_time_min_minutes
        or article.reading_time_minutes > article.blog.target_reading_time_max_minutes
    ):
        issues.append(
            _build_issue(
                "reading_time_range",
                "Reading time sits outside the configured target range for this blog.",
            )
        )
        score -= 8

    risk_level = RISK_LOW if set(patch.keys()).issubset(SAFE_DRAFT_PATCH_KEYS) else RISK_MEDIUM
    if not issues:
        risk_level = RISK_LOW
    return {
        "quality_score": _clamp_score(score),
        "risk_level": risk_level,
        "issues": issues,
        "proposed_patch": patch if issues else {},
        "approval_status": APPROVAL_PENDING if issues else APPROVAL_NOT_REQUIRED,
        "apply_status": APPLY_PENDING if issues else APPLY_SKIPPED,
        "learning_state": _initial_learning_state(score=_clamp_score(score), issues=issues),
    }


def _publish_review_payload(article: Article) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    patch: dict[str, Any] = {"named_entity_drift": False, "html_diff_ratio": 0.0}
    score = 100

    verification = verify_article_seo_meta(article)
    statuses = [
        verification["head_meta_description_status"],
        verification["og_description_status"],
        verification["twitter_description_status"],
    ]
    for status in statuses:
        if status.status == "warning":
            issues.append(
                _build_issue(
                    f"meta_status_{status.key}",
                    status.message,
                )
            )
            score -= 10

    if len((article.meta_description or "").strip()) < 60 or len((article.meta_description or "").strip()) > 170:
        issues.append(
            _build_issue(
                "published_meta_description_length",
                "Published article meta description is outside the safe operating range.",
                patchable=True,
            )
        )
        patch["meta_description"] = _derive_meta_description(article)
        score -= 12

    if article.blogger_post and article.blogger_post.post_status == PostStatus.PUBLISHED and not _has_successful_search_sync(article):
        issues.append(
            _build_issue(
                "search_description_sync",
                "Blogger search description has not been synced after publish.",
                patchable=True,
            )
        )
        patch["search_description"] = article.meta_description or _derive_meta_description(article)
        score -= 10

    risk_level = RISK_LOW if set(patch.keys()).issubset(SAFE_PUBLISH_PATCH_KEYS) else RISK_MEDIUM
    if not issues:
        risk_level = RISK_LOW
    return {
        "quality_score": _clamp_score(score),
        "risk_level": risk_level,
        "issues": issues,
        "proposed_patch": patch if issues else {},
        "approval_status": APPROVAL_PENDING if issues else APPROVAL_NOT_REQUIRED,
        "apply_status": APPLY_PENDING if issues else APPLY_SKIPPED,
        "learning_state": _initial_learning_state(score=_clamp_score(score), issues=issues),
    }


def _live_review_payload(post: SyncedBloggerPost) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    score = 100

    plain_text = _plain_text(post.content_html)
    if len(plain_text) < 900:
        issues.append(
            _build_issue(
                "live_content_depth",
                "Live post body is shallow enough that manual review is recommended.",
                severity="error",
            )
        )
        score -= 25

    if len((post.excerpt_text or "").strip()) < 80:
        issues.append(
            _build_issue(
                "live_excerpt_length",
                "Live post excerpt is shorter than the review target.",
            )
        )
        score -= 10

    if not list(post.labels or []):
        issues.append(
            _build_issue(
                "live_labels_missing",
                "Live post is missing labels.",
            )
        )
        score -= 8

    risk_level = RISK_HIGH if any(str(issue.get("severity")) == "error" for issue in issues) else RISK_MEDIUM
    if not issues:
        risk_level = RISK_LOW
    return {
        "quality_score": _clamp_score(score),
        "risk_level": risk_level,
        "issues": issues,
        "proposed_patch": {},
        "approval_status": APPROVAL_PENDING if issues else APPROVAL_NOT_REQUIRED,
        "apply_status": APPLY_AWAITING_APPROVAL if issues else APPLY_SKIPPED,
        "learning_state": _initial_learning_state(score=_clamp_score(score), issues=issues),
    }


def _serialize_action(action: ContentReviewAction) -> dict[str, Any]:
    return {
        "id": action.id,
        "action": action.action,
        "actor": action.actor,
        "channel": action.channel,
        "result_payload": dict(action.result_payload or {}),
        "created_at": action.created_at,
    }


def serialize_review_item(item: ContentReviewItem) -> dict[str, Any]:
    actions = list(item.actions or [])
    return {
        "id": item.id,
        "blog_id": item.blog_id,
        "source_type": item.source_type,
        "source_id": item.source_id,
        "source_title": item.source_title,
        "source_url": item.source_url,
        "review_kind": item.review_kind,
        "content_hash": item.content_hash,
        "quality_score": int(item.quality_score or 0),
        "risk_level": item.risk_level,
        "issues": list(item.issues or []),
        "proposed_patch": dict(item.proposed_patch or {}),
        "approval_status": item.approval_status,
        "apply_status": item.apply_status,
        "learning_state": item.learning_state,
        "source_updated_at": item.source_updated_at,
        "last_reviewed_at": item.last_reviewed_at,
        "last_applied_at": item.last_applied_at,
        "last_error": item.last_error,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "actions": [_serialize_action(action) for action in actions[:10]],
    }


def _send_ops_notification(db: Session, *, title: str, detail: str) -> None:
    from app.services.integrations.telegram_service import send_telegram_ops_notification

    send_telegram_ops_notification(db, title=title, detail=detail)


def _build_overview_topic_cluster(title: str, slug: str, topic_cluster_label: str | None) -> str:
    normalized = _safe_str(topic_cluster_label)
    if normalized:
        return normalized

    tokens = [token for token in _safe_str(slug).replace("-", " ").split(" ") if token]
    stop_words = {
        "the",
        "and",
        "guide",
        "tips",
        "travel",
        "mystery",
        "historical",
        "history",
        "review",
        "analysis",
        "for",
        "with",
        "from",
        "2026",
        "2025",
    }
    selected: list[str] = []
    for token in tokens:
        lowered = token.lower()
        if lowered in stop_words:
            continue
        selected.append(token)
        if len(selected) >= 4:
            break
    if selected:
        return " ".join(selected)

    words = [word for word in normalize_similarity_text(title).split(" ") if word]
    return " ".join(words[:4]) if words else "General topic"


def _build_overview_topic_angle(title: str, excerpt: str, angle_label: str | None) -> str:
    normalized = _safe_str(angle_label)
    if normalized:
        return normalized

    haystack = f"{title} {excerpt}".lower()
    rules = [
        ("schedule", ("schedule", "timing", "date", "calendar")),
        ("transport", ("transport", "subway", "bus", "route", "transfer")),
        ("food", ("food", "eat", "restaurant", "snack", "menu")),
        ("crowd", ("crowd", "queue", "line", "peak", "busy")),
        ("timeline", ("timeline", "chronology", "sequence")),
        ("theory", ("theory", "hypothesis", "interpretation")),
        ("cultural_impact", ("culture", "impact", "legacy", "influence")),
    ]
    for label, keywords in rules:
        if any(keyword in haystack for keyword in keywords):
            return label
    return "overview"


def _build_overview_media_state(*, blog_post_exists: bool, article_image_exists: bool, assembled_html: str | None) -> str:
    if not blog_post_exists:
        return "not_published"
    if not article_image_exists:
        return "missing_hero_image"
    if not (assembled_html or "").strip():
        return "missing_html"
    return "ok"


def _infer_overview_editorial_category(
    *,
    profile: str,
    labels: list[str],
    title: str,
    summary: str,
) -> tuple[str, str]:
    hint_map = TRAVEL_CATEGORY_HINTS if profile == "korea_travel" else MYSTERY_CATEGORY_HINTS
    normalized_labels = {label.strip().lower() for label in labels if label and label.strip()}

    for key, (label, _hints) in hint_map.items():
        if label.lower() in normalized_labels:
            return key, label

    haystack = f"{title} {summary} {' '.join(labels)}".lower()
    best_key = ""
    best_label = ""
    best_score = -1
    for key, (label, hints) in hint_map.items():
        score = sum(1 for hint in hints if hint in haystack)
        if score > best_score:
            best_key = key
            best_label = label
            best_score = score

    if best_key and best_label:
        return best_key, best_label
    fallback_key, (fallback_label, _hints) = next(iter(hint_map.items()))
    return fallback_key, fallback_label


def _resolve_overview_quality_state(
    *,
    profile: str,
    status: str,
    media_state: str,
    cached_status: str | None,
    similarity_score: float | None,
) -> tuple[str, str, bool, bool]:
    normalized_status = _safe_str(status).lower()
    normalized_cached = _safe_str(cached_status)

    if normalized_status != "published":
        return "DISLIVE", "publish_status_check", True, False

    if media_state != "ok":
        return normalized_cached or "media_fix_needed", "media_fix", False, False

    if profile == "world_mystery" and similarity_score is not None and similarity_score >= 70.0:
        return "rewrite_required", "rewrite_required", False, True

    if normalized_cached:
        return normalized_cached, "none", True, False

    return "not_audited", "recalculate_required", True, False


def persist_article_quality_cache(
    db: Session,
    *,
    article: Article,
    similarity_score: float | None,
    most_similar_url: str | None,
    seo_score: int | None,
    geo_score: int | None,
    quality_status: str,
    ctr_score: float | None = None,
    rewrite_attempts: int | None = None,
    audited_at: datetime | None = None,
) -> None:
    article.quality_similarity_score = round(float(similarity_score), 1) if similarity_score is not None else None
    article.quality_most_similar_url = _safe_str(most_similar_url) or None
    article.quality_seo_score = int(seo_score) if seo_score is not None else None
    article.quality_geo_score = int(geo_score) if geo_score is not None else None
    article.quality_ctr_score = float(ctr_score) if ctr_score is not None else None
    article.quality_status = _safe_str(quality_status) or None
    if rewrite_attempts is not None:
        article.quality_rewrite_attempts = max(0, int(rewrite_attempts))
    article.quality_last_audited_at = audited_at or _utc_now()
    db.add(article)


def refresh_content_overview_cache(
    db: Session,
    *,
    profile: str | None = None,
    published_only: bool = False,
) -> dict[str, int | str | None]:
    selected_profile = _safe_str(profile)
    if selected_profile and selected_profile not in CONTENT_OVERVIEW_PROFILE_OPTIONS:
        raise ContentOpsError(f"Unsupported profile: {selected_profile}", status_code=400)

    stmt = (
        select(Article)
        .join(Blog, Blog.id == Article.blog_id)
        .where(Blog.is_active.is_(True))
        .options(
            selectinload(Article.blog),
            selectinload(Article.topic),
            selectinload(Article.image),
            selectinload(Article.blogger_post),
        )
        .order_by(Article.created_at.desc(), Article.id.desc())
    )
    if selected_profile:
        stmt = stmt.where(Blog.profile_key == selected_profile)
    if published_only:
        stmt = stmt.where(Article.blogger_post.has(post_status=PostStatus.PUBLISHED))

    articles = db.execute(stmt).scalars().unique().all()
    if not articles:
        return {
            "profile": selected_profile or None,
            "published_only": int(bool(published_only)),
            "updated_articles": 0,
            "total_articles": 0,
            "status": "ok",
        }

    grouped_inputs: dict[str, list[dict[str, str]]] = {}
    article_lookup: dict[int, Article] = {}
    for article in articles:
        if article.blog is None:
            continue
        article_lookup[int(article.id)] = article
        grouped_inputs.setdefault(_safe_str(article.blog.profile_key), []).append(
            {
                "key": str(article.id),
                "title": _safe_str(article.title),
                "body_html": _safe_str(article.assembled_html or article.html_article),
                "url": _safe_str(article.blogger_post.published_url if article.blogger_post else ""),
            }
        )

    similarity_by_article: dict[int, dict[str, Any]] = {}
    for similarity_items in grouped_inputs.values():
        similarity_map = compute_similarity_analysis(
            similarity_items,
            key_field="key",
            title_field="title",
            body_field="body_html",
            url_field="url",
        )
        for key, payload in similarity_map.items():
            if str(key).isdigit():
                similarity_by_article[int(key)] = payload

    audited_at = _utc_now().replace(microsecond=0)
    updated_articles = 0
    for article_id, article in article_lookup.items():
        blog = article.blog
        if blog is None:
            continue
        blogger_post = article.blogger_post
        status = blogger_post.post_status.value if blogger_post else "draft"
        media_state = _build_overview_media_state(
            blog_post_exists=blogger_post is not None,
            article_image_exists=article.image is not None,
            assembled_html=_safe_str(article.assembled_html),
        )
        similarity_payload = similarity_by_article.get(article_id, {})
        similarity_score = (
            float(similarity_payload.get("similarity_score", 0.0))
            if similarity_payload.get("similarity_score") is not None
            else None
        )
        seo_geo = compute_seo_geo_scores(
            title=_safe_str(article.title),
            html_body=_safe_str(article.assembled_html or article.html_article),
            excerpt=_safe_str(article.excerpt),
            faq_section=list(article.faq_section or []),
        )
        quality_status, _suggested_action, _auto_fixable, _manual_review = _resolve_overview_quality_state(
            profile=_safe_str(blog.profile_key),
            status=status,
            media_state=media_state,
            cached_status="ok",
            similarity_score=similarity_score,
        )
        persist_article_quality_cache(
            db,
            article=article,
            similarity_score=similarity_score,
            most_similar_url=_safe_str(similarity_payload.get("most_similar_url")),
            seo_score=int(seo_geo["seo_score"]),
            geo_score=int(seo_geo["geo_score"]),
            quality_status=quality_status,
            ctr_score=float(seo_geo.get("ctr_score") or 0),
            rewrite_attempts=article.quality_rewrite_attempts,
            audited_at=audited_at,
        )
        updated_articles += 1

    db.commit()
    return {
        "profile": selected_profile or None,
        "published_only": int(bool(published_only)),
        "updated_articles": updated_articles,
        "total_articles": len(article_lookup),
        "status": "ok",
    }


def _article_to_content_overview_row(article: Article) -> dict[str, Any] | None:
    blog = article.blog
    if blog is None:
        return None

    topic = article.topic
    blogger_post = article.blogger_post
    labels = article.labels if isinstance(article.labels, list) else []
    url = _safe_str(blogger_post.published_url if blogger_post else "")
    status = blogger_post.post_status.value if blogger_post else "draft"
    published_at = blogger_post.published_at if blogger_post else None
    updated_at = article.updated_at
    content_category = _safe_str(
        getattr(article, "editorial_category_label", None) or (topic.editorial_category_label if topic else "")
    )
    category_key = _safe_str(
        getattr(article, "editorial_category_key", None) or (topic.editorial_category_key if topic else "")
    )
    if not content_category or not category_key:
        inferred_key, inferred_label = _infer_overview_editorial_category(
            profile=_safe_str(blog.profile_key),
            labels=[_safe_str(label) for label in labels],
            title=_safe_str(article.title),
            summary=_safe_str(article.excerpt),
        )
        category_key = category_key or inferred_key
        content_category = content_category or inferred_label

    media_state = _build_overview_media_state(
        blog_post_exists=blogger_post is not None,
        article_image_exists=article.image is not None,
        assembled_html=_safe_str(article.assembled_html),
    )
    similarity_score = float(article.quality_similarity_score) if article.quality_similarity_score is not None else None
    quality_status, suggested_action, auto_fixable, manual_review = _resolve_overview_quality_state(
        profile=_safe_str(blog.profile_key),
        status=status,
        media_state=media_state,
        cached_status=article.quality_status,
        similarity_score=similarity_score,
    )
    return {
        "article_id": int(article.id),
        "blog_id": int(blog.id),
        "profile": _safe_str(blog.profile_key),
        "blog": _safe_str(blog.name),
        "title": _safe_str(article.title),
        "url": url,
        "summary": _safe_str(article.excerpt),
        "labels": ", ".join(_safe_str(label) for label in labels if _safe_str(label)),
        "status": status,
        "published_at": _format_datetime(published_at) if published_at else "",
        "updated_at": _format_datetime(updated_at),
        "date_kst": _format_datetime(article.created_at),
        "slug": _safe_str(article.slug),
        "content_category": content_category,
        "category_key": category_key,
        "topic_cluster": _build_overview_topic_cluster(article.title, article.slug, topic.topic_cluster_label if topic else None),
        "topic_angle": _build_overview_topic_angle(article.title, article.excerpt, topic.topic_angle_label if topic else None),
        "media_state": media_state,
        "similarity_score": similarity_score,
        "most_similar_url": _safe_str(article.quality_most_similar_url),
        "seo_score": float(article.quality_seo_score) if article.quality_seo_score is not None else None,
        "geo_score": float(article.quality_geo_score) if article.quality_geo_score is not None else None,
        "ctr_score": float(article.quality_ctr_score) if article.quality_ctr_score is not None else None,
        "lighthouse_score": float(article.quality_lighthouse_score) if article.quality_lighthouse_score is not None else None,
        "quality_status": quality_status,
        "suggested_action": suggested_action,
        "auto_fixable": auto_fixable,
        "manual_review": manual_review,
        "rewrite_attempts": int(article.quality_rewrite_attempts or 0),
        "last_audited_at": _format_datetime(article.quality_last_audited_at),
        "lighthouse_last_audited_at": _format_datetime(article.quality_lighthouse_last_audited_at),
    }


def _content_overview_payload(*, rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    payload: list[dict[str, str]] = []
    for row in rows:
        payload.append(
            {
                "date_kst": _safe_str(row.get("date_kst")),
                "profile": _safe_str(row.get("profile")),
                "blog": _safe_str(row.get("blog")),
                "title": _safe_str(row.get("title")),
                "url": _safe_str(row.get("url")),
                "slug": _safe_str(row.get("slug")),
                "summary": _safe_str(row.get("summary")),
                "labels": _safe_str(row.get("labels")),
                "status": _safe_str(row.get("status")),
                "published_at": _safe_str(row.get("published_at")),
                "updated_at": _safe_str(row.get("updated_at")),
                "content_category": _safe_str(row.get("content_category")),
                "category_key": _safe_str(row.get("category_key")),
                "topic_cluster": _safe_str(row.get("topic_cluster")),
                "topic_angle": _safe_str(row.get("topic_angle")),
                "similarity_score": _safe_str(row.get("similarity_score")),
                "most_similar_url": _safe_str(row.get("most_similar_url")),
                "seo_score": _safe_str(row.get("seo_score")),
                "geo_score": _safe_str(row.get("geo_score")),
                "lighthouse_score": _safe_str(row.get("lighthouse_score")),
                "quality_status": _safe_str(row.get("quality_status")),
                "rewrite_attempts": _safe_str(row.get("rewrite_attempts")),
                "last_audited_at": _safe_str(row.get("last_audited_at")),
                "lighthouse_last_audited_at": _safe_str(row.get("lighthouse_last_audited_at")),
            }
        )
    return payload


def get_content_overview(
    db: Session,
    *,
    profile: str | None = None,
    published_only: bool = False,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    selected_profile = _safe_str(profile)
    if selected_profile and selected_profile not in CONTENT_OVERVIEW_PROFILE_OPTIONS:
        raise ContentOpsError(f"Unsupported profile: {selected_profile}", status_code=400)
    safe_page = max(1, int(page))
    safe_page_size = max(1, min(int(page_size), 200))

    base_stmt = (
        select(Article.id)
        .join(Blog, Blog.id == Article.blog_id)
        .where(Blog.is_active.is_(True))
    )
    if selected_profile:
        base_stmt = base_stmt.where(Blog.profile_key == selected_profile)
    if published_only:
        base_stmt = base_stmt.where(Article.blogger_post.has(post_status=PostStatus.PUBLISHED))

    total = int(
        db.execute(select(func.count()).select_from(base_stmt.subquery())).scalar_one() or 0
    )
    stmt = (
        select(Article)
        .join(Blog, Blog.id == Article.blog_id)
        .where(Blog.is_active.is_(True))
        .options(
            selectinload(Article.blog),
            selectinload(Article.topic),
            selectinload(Article.image),
            selectinload(Article.blogger_post),
        )
        .order_by(Article.created_at.desc(), Article.id.desc())
        .offset((safe_page - 1) * safe_page_size)
        .limit(safe_page_size)
    )
    if selected_profile:
        stmt = stmt.where(Blog.profile_key == selected_profile)
    if published_only:
        stmt = stmt.where(Article.blogger_post.has(post_status=PostStatus.PUBLISHED))

    articles = db.execute(stmt).scalars().unique().all()
    rows = [row for article in articles if (row := _article_to_content_overview_row(article)) is not None]
    return {
        "rows": rows,
        "total": total,
        "page": safe_page,
        "page_size": safe_page_size,
        "profile": selected_profile or None,
        "published_only": bool(published_only),
    }


def sync_content_overview_to_sheet(
    db: Session,
    *,
    profile: str | None = None,
    published_only: bool = False,
) -> dict[str, str | int]:
    config = get_google_sheet_sync_config(db)
    sheet_id = _safe_str(config.get("sheet_id"))
    tab_name = _safe_str(config.get("content_overview_tab", OVERVIEW_TAB_NAME)) or OVERVIEW_TAB_NAME

    if not sheet_id:
        return {
            "sheet_id": "",
            "tab": tab_name,
            "status": "skipped",
            "rows": 0,
            "columns": 0,
            "reason": "google_sheet_not_configured",
        }

    refresh_content_overview_cache(db, profile=profile, published_only=published_only)
    overview = get_content_overview(db, profile=profile, published_only=published_only, page=1, page_size=5000)
    rows = list(overview["rows"])
    if not rows:
        result = sync_google_sheet_quality_tab(
            db,
            sheet_id=sheet_id,
            tab_name=tab_name,
            incoming_rows=[],
            base_columns=BLOGGER_SNAPSHOT_COLUMNS,
            quality_columns=QUALITY_COLUMNS,
            key_columns=("url", "slug"),
        )
        return {
            "sheet_id": sheet_id,
            "profile": profile,
            "tab": _safe_str(result.get("tab")) or tab_name,
            "status": _safe_str(result.get("status")) or "ok",
            "rows": int(result.get("rows", 0) or 0),
            "columns": int(result.get("columns", 0) or 0),
        }

    payload = _content_overview_payload(rows=rows)
    result = sync_google_sheet_quality_tab(
        db,
        sheet_id=sheet_id,
        tab_name=tab_name,
        incoming_rows=payload,
        base_columns=BLOGGER_SNAPSHOT_COLUMNS,
        quality_columns=QUALITY_COLUMNS,
        key_columns=("url", "slug"),
    )
    return {
        "sheet_id": sheet_id,
        "profile": profile,
        "tab": _safe_str(result.get("tab")) or tab_name,
        "status": _safe_str(result.get("status")) or "ok",
        "rows": int(result.get("rows", 0) or 0),
        "columns": int(result.get("columns", 0) or 0),
    }

def _upsert_review_item(
    db: Session,
    *,
    blog_id: int,
    source_type: str,
    source_id: str,
    source_title: str,
    source_url: str | None,
    source_updated_at: datetime | None,
    review_kind: str,
    content_hash: str,
    payload: dict[str, Any],
) -> tuple[ContentReviewItem, bool]:
    item = _find_review_item(db, source_type=source_type, source_id=source_id, review_kind=review_kind)
    is_new = item is None
    if item is None:
        item = ContentReviewItem(
            blog_id=blog_id,
            source_type=source_type,
            source_id=source_id,
            review_kind=review_kind,
        )
        db.add(item)

    changed = any(
        [
            is_new,
            item.content_hash != content_hash,
            item.source_title != source_title,
            item.source_url != source_url,
            item.quality_score != int(payload["quality_score"]),
            item.risk_level != str(payload["risk_level"]),
            list(item.issues or []) != list(payload["issues"] or []),
            dict(item.proposed_patch or {}) != dict(payload["proposed_patch"] or {}),
        ]
    )

    item.blog_id = blog_id
    item.source_title = source_title
    item.source_url = source_url
    item.source_updated_at = source_updated_at
    item.content_hash = content_hash
    item.quality_score = int(payload["quality_score"])
    item.risk_level = str(payload["risk_level"])
    item.issues = list(payload["issues"] or [])
    item.proposed_patch = dict(payload["proposed_patch"] or {})
    item.last_reviewed_at = _utc_now()
    item.last_error = None

    if not item.issues:
        item.approval_status = APPROVAL_NOT_REQUIRED
        item.apply_status = APPLY_SKIPPED
        if item.learning_state != LEARNING_APPROVED:
            item.learning_state = payload["learning_state"]
    elif changed or item.approval_status in {APPROVAL_REJECTED, APPROVAL_NOT_REQUIRED}:
        item.approval_status = str(payload["approval_status"])
        item.apply_status = str(payload["apply_status"])
        if item.learning_state != LEARNING_APPROVED:
            item.learning_state = str(payload["learning_state"])

    db.add(item)
    db.commit()
    db.refresh(item)

    if changed and item.risk_level == RISK_HIGH and item.issues:
        _send_ops_notification(
            db,
            title="High-risk content review queued",
            detail=f"[{item.review_kind}] {item.source_title} (review #{item.id})",
        )
    return item, changed


def _rebuild_article_if_needed(db: Session, article: Article) -> None:
    hero_image_url = refresh_article_public_image(db, article) or (article.image.public_url if article.image else "")
    rebuild_article_html(db, article, hero_image_url)
    db.refresh(article)


def _apply_draft_patch(db: Session, item: ContentReviewItem, article: Article) -> dict[str, Any]:
    patch = dict(item.proposed_patch or {})
    if not patch:
        raise ContentOpsError("No safe draft patch is available for this review item.")

    if patch.get("meta_description"):
        article.meta_description = str(patch["meta_description"]).strip()
    if patch.get("excerpt"):
        article.excerpt = str(patch["excerpt"]).strip()
    if patch.get("faq_section"):
        article.faq_section = list(patch["faq_section"])
    article.reading_time_minutes = estimate_reading_time(article.html_article or "")
    db.add(article)
    db.commit()
    db.refresh(article)

    if article.assembled_html is not None:
        _rebuild_article_if_needed(db, article)

    return {
        "article_id": article.id,
        "meta_description": article.meta_description,
        "excerpt": article.excerpt,
        "faq_count": len(article.faq_section or []),
    }


def _apply_publish_patch(db: Session, item: ContentReviewItem, article: Article) -> dict[str, Any]:
    patch = dict(item.proposed_patch or {})
    if not patch:
        raise ContentOpsError("No safe publish patch is available for this review item.")
    if not article.blog:
        raise ContentOpsError("Article blog is missing.")

    result: dict[str, Any] = {"article_id": article.id}

    if patch.get("meta_description"):
        article.meta_description = str(patch["meta_description"]).strip()
        db.add(article)
        db.commit()
        db.refresh(article)
        result["meta_description"] = article.meta_description

    if article.assembled_html is not None:
        _rebuild_article_if_needed(db, article)

    if article.blogger_post and article.blogger_post.post_status in {PostStatus.PUBLISHED, PostStatus.SCHEDULED}:
        labels = ensure_article_editorial_labels(db, article)
        provider = get_blogger_provider(db, article.blog)
        summary, raw_payload = provider.update_post(
            post_id=article.blogger_post.blogger_post_id,
            title=article.title,
            content=article.assembled_html or article.html_article or "",
            labels=labels,
            meta_description=article.meta_description or "",
        )
        upsert_article_blogger_post(
            db,
            article=article,
            summary=summary,
            raw_payload=raw_payload if isinstance(raw_payload, dict) else {},
        )
        result["blogger_update"] = summary

    if patch.get("search_description") and article.blogger_post and article.blogger_post.post_status == PostStatus.PUBLISHED:
        try:
            sync_result = sync_article_search_description(db, article)
        except BloggerEditorAutomationError as exc:
            _record_search_sync_state(db, article=article, status="error", message=exc.message)
            raise ContentOpsError(exc.message, status_code=502) from exc
        _record_search_sync_state(
            db,
            article=article,
            status=sync_result.status,
            message=sync_result.message,
            editor_url=sync_result.editor_url,
            cdp_url=sync_result.cdp_url,
        )
        result["search_description"] = {
            "status": sync_result.status,
            "message": sync_result.message,
        }

    return result


def apply_content_review(
    db: Session,
    item_id: int,
    *,
    actor: str = "system",
    channel: str = "api",
    auto: bool = False,
) -> ContentReviewItem:
    item = db.execute(
        select(ContentReviewItem)
        .where(ContentReviewItem.id == item_id)
        .options(selectinload(ContentReviewItem.actions))
    ).scalar_one_or_none()
    if not item:
        raise ContentOpsError("Content review item not found.", status_code=404)
    if not item.issues:
        item.apply_status = APPLY_SKIPPED
        db.add(item)
        db.commit()
        db.refresh(item)
        return item
    if not auto and item.approval_status not in {APPROVAL_APPROVED, APPROVAL_AUTO_APPROVED, APPROVAL_NOT_REQUIRED}:
        item.apply_status = APPLY_AWAITING_APPROVAL
        db.add(item)
        db.commit()
        db.refresh(item)
        raise ContentOpsError("Review item is awaiting approval.", status_code=409)

    try:
        if item.source_type != SOURCE_ARTICLE:
            raise ContentOpsError("Only article-backed review items support apply in v1.", status_code=409)

        article = _load_article(db, int(item.source_id))
        if not article:
            raise ContentOpsError("Article source is missing.", status_code=404)

        if item.review_kind == REVIEW_KIND_DRAFT:
            result_payload = _apply_draft_patch(db, item, article)
        elif item.review_kind == REVIEW_KIND_PUBLISH:
            result_payload = _apply_publish_patch(db, item, article)
        else:
            raise ContentOpsError("This review kind does not support apply in v1.", status_code=409)

        if item.approval_status == APPROVAL_PENDING:
            item.approval_status = APPROVAL_AUTO_APPROVED if auto else APPROVAL_APPROVED
        item.apply_status = APPLY_APPLIED
        item.learning_state = LEARNING_APPROVED
        item.last_applied_at = _utc_now()
        item.last_error = None
        db.add(item)
        db.commit()
        db.refresh(item)
        _log_review_action(
            db,
            item=item,
            action="auto_apply" if auto else "apply",
            actor=actor,
            channel=channel,
            result_payload=result_payload,
        )
        build_learning_snapshot(db)
        return item
    except ContentOpsError as exc:
        item.apply_status = APPLY_FAILED
        item.last_error = exc.message
        db.add(item)
        db.commit()
        db.refresh(item)
        _log_review_action(
            db,
            item=item,
            action="apply_failed",
            actor=actor,
            channel=channel,
            result_payload={"error": exc.message},
        )
        _send_ops_notification(
            db,
            title="Content review apply failed",
            detail=f"{item.source_title} ({item.review_kind}): {exc.message}",
        )
        raise
    except Exception as exc:  # noqa: BLE001
        item.apply_status = APPLY_FAILED
        item.last_error = str(exc)
        db.add(item)
        db.commit()
        db.refresh(item)
        _log_review_action(
            db,
            item=item,
            action="apply_failed",
            actor=actor,
            channel=channel,
            result_payload={"error": str(exc)},
        )
        _send_ops_notification(
            db,
            title="Content review apply failed",
            detail=f"{item.source_title} ({item.review_kind}): {exc}",
        )
        raise


def approve_content_review(db: Session, item_id: int, *, actor: str = "operator", channel: str = "api") -> ContentReviewItem:
    item = db.get(ContentReviewItem, item_id)
    if not item:
        raise ContentOpsError("Content review item not found.", status_code=404)
    item.approval_status = APPROVAL_APPROVED
    if item.learning_state != LEARNING_APPROVED:
        item.learning_state = LEARNING_APPROVED
    db.add(item)
    db.commit()
    db.refresh(item)
    _log_review_action(db, item=item, action="approve", actor=actor, channel=channel)
    build_learning_snapshot(db)
    return item


def reject_content_review(db: Session, item_id: int, *, actor: str = "operator", channel: str = "api") -> ContentReviewItem:
    item = db.get(ContentReviewItem, item_id)
    if not item:
        raise ContentOpsError("Content review item not found.", status_code=404)
    item.approval_status = APPROVAL_REJECTED
    item.apply_status = APPLY_SKIPPED if item.apply_status != APPLY_APPLIED else item.apply_status
    item.learning_state = LEARNING_REJECTED
    db.add(item)
    db.commit()
    db.refresh(item)
    _log_review_action(db, item=item, action="reject", actor=actor, channel=channel)
    build_learning_snapshot(db)
    return item


def review_article_draft(db: Session, article_id: int, *, trigger: str = "system") -> ContentReviewItem:
    article = _load_article(db, article_id)
    if not article or not article.blog:
        raise ContentOpsError("Article not found.", status_code=404)
    content_hash = _content_hash(
        article.title,
        article.html_article,
        article.meta_description,
        article.excerpt,
        json.dumps(article.faq_section or []),
    )
    item, _ = _upsert_review_item(
        db,
        blog_id=article.blog_id,
        source_type=SOURCE_ARTICLE,
        source_id=str(article.id),
        source_title=article.title,
        source_url=article.blogger_post.published_url if article.blogger_post else None,
        source_updated_at=article.updated_at,
        review_kind=REVIEW_KIND_DRAFT,
        content_hash=content_hash,
        payload=_draft_review_payload(article),
    )
    _log_review_action(db, item=item, action="review", actor=trigger, channel="system", result_payload={"review_kind": REVIEW_KIND_DRAFT})

    settings_map = get_settings_map(db)
    safe_patch = set(dict(item.proposed_patch or {}).keys()).issubset(SAFE_DRAFT_PATCH_KEYS)
    if item.issues and item.risk_level == RISK_LOW and safe_patch and _setting_enabled(settings_map, "content_ops_auto_fix_drafts", default=True):
        apply_content_review(db, item.id, actor="system", channel="auto", auto=True)
        item = db.get(ContentReviewItem, item.id) or item

    build_learning_snapshot(db)
    return item


def review_article_publish_state(db: Session, article_id: int, *, trigger: str = "system") -> ContentReviewItem:
    article = _load_article(db, article_id)
    if not article or not article.blog:
        raise ContentOpsError("Article not found.", status_code=404)
    sync_payload = {}
    if article.blogger_post and isinstance(article.blogger_post.response_payload, dict):
        sync_payload = dict(article.blogger_post.response_payload.get("search_description_sync") or {})
    content_hash = _content_hash(
        article.title,
        article.meta_description,
        article.assembled_html or article.html_article,
        json.dumps(sync_payload, ensure_ascii=False),
    )
    item, _ = _upsert_review_item(
        db,
        blog_id=article.blog_id,
        source_type=SOURCE_ARTICLE,
        source_id=str(article.id),
        source_title=article.title,
        source_url=article.blogger_post.published_url if article.blogger_post else None,
        source_updated_at=article.updated_at,
        review_kind=REVIEW_KIND_PUBLISH,
        content_hash=content_hash,
        payload=_publish_review_payload(article),
    )
    _log_review_action(db, item=item, action="review", actor=trigger, channel="system", result_payload={"review_kind": REVIEW_KIND_PUBLISH})

    settings_map = get_settings_map(db)
    safe_patch = set(dict(item.proposed_patch or {}).keys()).issubset(SAFE_PUBLISH_PATCH_KEYS)
    if item.issues and item.risk_level == RISK_LOW and safe_patch and _setting_enabled(settings_map, "content_ops_auto_fix_published_meta", default=True):
        try:
            apply_content_review(db, item.id, actor="system", channel="auto", auto=True)
            item = db.get(ContentReviewItem, item.id) or item
        except ContentOpsError as exc:
            # Post-publish auto-fix must not fail the publishing pipeline.
            _log_review_action(
                db,
                item=item,
                action="auto_apply_failed",
                actor="system",
                channel="auto",
                result_payload={
                    "message": exc.message,
                    "status_code": exc.status_code,
                },
            )

    build_learning_snapshot(db)
    return item


def review_synced_post(db: Session, synced_post_id: int, *, trigger: str = "system") -> ContentReviewItem:
    post = _load_synced_post(db, synced_post_id)
    if not post:
        raise ContentOpsError("Synced Blogger post not found.", status_code=404)
    content_hash = _content_hash(post.title, post.content_html, post.excerpt_text, json.dumps(post.labels or [], ensure_ascii=False))
    item, _ = _upsert_review_item(
        db,
        blog_id=post.blog_id,
        source_type=SOURCE_SYNCED_POST,
        source_id=str(post.id),
        source_title=post.title,
        source_url=post.url,
        source_updated_at=post.updated_at_remote or post.synced_at,
        review_kind=REVIEW_KIND_LIVE,
        content_hash=content_hash,
        payload=_live_review_payload(post),
    )
    _log_review_action(db, item=item, action="review", actor=trigger, channel="system", result_payload={"review_kind": REVIEW_KIND_LIVE})
    build_learning_snapshot(db)
    return item


def rerun_content_review(db: Session, item_id: int, *, actor: str = "operator", channel: str = "api") -> ContentReviewItem:
    item = db.get(ContentReviewItem, item_id)
    if not item:
        raise ContentOpsError("Content review item not found.", status_code=404)
    if item.source_type == SOURCE_ARTICLE and item.review_kind == REVIEW_KIND_DRAFT:
        refreshed = review_article_draft(db, int(item.source_id), trigger=actor)
    elif item.source_type == SOURCE_ARTICLE and item.review_kind == REVIEW_KIND_PUBLISH:
        refreshed = review_article_publish_state(db, int(item.source_id), trigger=actor)
    elif item.source_type == SOURCE_SYNCED_POST and item.review_kind == REVIEW_KIND_LIVE:
        refreshed = review_synced_post(db, int(item.source_id), trigger=actor)
    else:
        raise ContentOpsError("Unsupported review item rerun target.", status_code=409)
    refreshed = db.get(ContentReviewItem, refreshed.id) or refreshed
    _log_review_action(db, item=refreshed, action="rerun", actor=actor, channel=channel)
    return refreshed


def list_content_reviews(
    db: Session,
    *,
    blog_id: int | None = None,
    limit: int = 50,
    approval_status: str | None = None,
    risk_level: str | None = None,
) -> list[ContentReviewItem]:
    query = (
        select(ContentReviewItem)
        .options(selectinload(ContentReviewItem.actions))
        .order_by(ContentReviewItem.updated_at.desc(), ContentReviewItem.id.desc())
        .limit(max(1, min(limit, 200)))
    )
    if blog_id is not None:
        query = query.where(ContentReviewItem.blog_id == blog_id)
    if approval_status:
        query = query.where(ContentReviewItem.approval_status == approval_status)
    if risk_level:
        query = query.where(ContentReviewItem.risk_level == risk_level)
    return db.execute(query).scalars().unique().all()


def get_content_ops_status(db: Session) -> dict[str, Any]:
    items = db.execute(
        select(ContentReviewItem)
        .options(selectinload(ContentReviewItem.actions))
        .order_by(ContentReviewItem.updated_at.desc(), ContentReviewItem.id.desc())
    ).scalars().unique().all()
    settings_map = get_settings_map(db)
    learning_snapshot_updated_at = (settings_map.get("content_ops_learning_snapshot_updated_at") or "").strip()
    learning_age_minutes: int | None = None
    if learning_snapshot_updated_at:
        try:
            learning_timestamp = datetime.fromisoformat(learning_snapshot_updated_at.replace("Z", "+00:00"))
            learning_age_minutes = max(0, int((_utc_now() - learning_timestamp.astimezone(timezone.utc)).total_seconds() // 60))
        except ValueError:
            learning_age_minutes = None

    pending_items = [
        item
        for item in items
        if item.approval_status == APPROVAL_PENDING or item.apply_status in {APPLY_PENDING, APPLY_AWAITING_APPROVAL, APPLY_FAILED}
    ]
    high_risk_items = [item for item in items if item.risk_level == RISK_HIGH]
    today = _utc_now().date()
    auto_fix_applied_today = 0
    for item in items:
        for action in list(item.actions or []):
            if action.action == "auto_apply" and action.created_at.astimezone(timezone.utc).date() == today:
                auto_fix_applied_today += 1

    return {
        "review_queue_count": len(pending_items),
        "high_risk_count": len(high_risk_items),
        "auto_fix_applied_today": auto_fix_applied_today,
        "learning_snapshot_age": learning_age_minutes,
        "learning_paused": _setting_enabled(settings_map, "content_ops_learning_paused", default=False),
        "learning_snapshot_path": settings_map.get("content_ops_learning_snapshot_path", ""),
        "prompt_memory_path": settings_map.get("content_ops_prompt_memory_path", ""),
        "recent_reviews": [serialize_review_item(item) for item in items[:10]],
    }


def _eligible_learning_items(db: Session) -> list[ContentReviewItem]:
    rows = db.execute(
        select(ContentReviewItem)
        .where(ContentReviewItem.learning_state.in_([LEARNING_REFERENCE, LEARNING_APPROVED]))
        .order_by(ContentReviewItem.last_reviewed_at.desc().nullslast(), ContentReviewItem.id.desc())
    ).scalars().all()
    deduped: dict[tuple[str, str], ContentReviewItem] = {}
    for item in rows:
        key = (item.source_type, item.source_id)
        deduped.setdefault(key, item)
    return list(deduped.values())


def build_learning_snapshot(db: Session) -> dict[str, Any]:
    items = _eligible_learning_items(db)
    dataset_path, manifest_path, prompt_memory_path = _learning_snapshot_paths()

    article_ids = [int(item.source_id) for item in items if item.source_type == SOURCE_ARTICLE and item.source_id.isdigit()]
    synced_ids = [int(item.source_id) for item in items if item.source_type == SOURCE_SYNCED_POST and item.source_id.isdigit()]

    article_rows = {}
    if article_ids:
        rows = db.execute(
            select(Article.id, Article.blog_id, Article.title, Article.meta_description, Article.excerpt, Article.html_article)
            .where(Article.id.in_(article_ids))
        ).all()
        article_rows = {row[0]: row for row in rows}

    synced_rows = {}
    if synced_ids:
        rows = db.execute(
            select(SyncedBloggerPost.id, SyncedBloggerPost.blog_id, SyncedBloggerPost.title, SyncedBloggerPost.excerpt_text, SyncedBloggerPost.content_html)
            .where(SyncedBloggerPost.id.in_(synced_ids))
        ).all()
        synced_rows = {row[0]: row for row in rows}

    prompt_memory: list[dict[str, Any]] = []
    count = 0
    with dataset_path.open("w", encoding="utf-8") as dataset_fp:
        for item in items:
            if item.source_type == SOURCE_ARTICLE and item.source_id.isdigit():
                row = article_rows.get(int(item.source_id))
                if not row:
                    continue
                dataset_fp.write(
                    json.dumps(
                        {
                            "source": SOURCE_ARTICLE,
                            "source_id": item.source_id,
                            "blog_id": row[1],
                            "title": row[2],
                            "meta_description": row[3],
                            "excerpt": row[4],
                            "text": _plain_text(row[5]),
                            "quality_score": item.quality_score,
                            "learning_state": item.learning_state,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            elif item.source_type == SOURCE_SYNCED_POST and item.source_id.isdigit():
                row = synced_rows.get(int(item.source_id))
                if not row:
                    continue
                dataset_fp.write(
                    json.dumps(
                        {
                            "source": SOURCE_SYNCED_POST,
                            "source_id": item.source_id,
                            "blog_id": row[1],
                            "title": row[2],
                            "excerpt": row[3],
                            "text": _plain_text(row[4]),
                            "quality_score": item.quality_score,
                            "learning_state": item.learning_state,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            else:
                continue

            prompt_memory.append(
                {
                    "review_id": item.id,
                    "source_type": item.source_type,
                    "source_id": item.source_id,
                    "title": item.source_title,
                    "quality_score": item.quality_score,
                    "risk_level": item.risk_level,
                    "issues": list(item.issues or []),
                    "proposed_patch": dict(item.proposed_patch or {}),
                    "learning_state": item.learning_state,
                    "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                }
            )
            count += 1

    manifest = {
        "built_at": _utc_now().isoformat(),
        "item_count": count,
        "eligible_review_ids": [item.id for item in items],
        "dataset_path": str(dataset_path),
        "prompt_memory_path": str(prompt_memory_path),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    prompt_memory_path.write_text(json.dumps(prompt_memory, ensure_ascii=False, indent=2), encoding="utf-8")
    upsert_settings(
        db,
        {
            "content_ops_learning_snapshot_path": str(dataset_path),
            "content_ops_prompt_memory_path": str(prompt_memory_path),
            "content_ops_learning_snapshot_updated_at": manifest["built_at"],
        },
    )
    return manifest


def _sync_failure_streak(db: Session, *, failed: bool) -> int:
    settings_map = get_settings_map(db)
    current = _parse_int(settings_map.get("content_ops_sync_failure_streak"), 0)
    next_value = current + 1 if failed else 0
    upsert_settings(db, {"content_ops_sync_failure_streak": str(next_value)})
    return next_value


def sync_live_content_reviews(db: Session) -> dict[str, Any]:
    settings_map = get_settings_map(db)
    if not _setting_enabled(settings_map, "content_ops_scan_enabled", default=True):
        return {"status": "disabled", "reviewed_count": 0, "changed_count": 0, "failed_blogs": []}

    active_blogs = db.execute(
        select(Blog)
        .where(Blog.is_active.is_(True), Blog.blogger_blog_id.is_not(None))
        .order_by(Blog.id.asc())
    ).scalars().all()

    reviewed_count = 0
    changed_count = 0
    failed_blogs: list[str] = []

    for blog in active_blogs:
        existing_rows = db.execute(
            select(SyncedBloggerPost.id, SyncedBloggerPost.updated_at_remote, SyncedBloggerPost.content_html)
            .where(SyncedBloggerPost.blog_id == blog.id)
        ).all()
        before_map = {
            int(row[0]): {
                "updated_at_remote": row[1].isoformat() if row[1] else None,
                "content_hash": _content_hash(row[2]),
            }
            for row in existing_rows
        }

        try:
            sync_blogger_posts_for_blog(db, blog)
        except Exception as exc:  # noqa: BLE001
            failed_blogs.append(f"{blog.name}: {exc}")
            streak = _sync_failure_streak(db, failed=True)
            if streak >= 3:
                _send_ops_notification(
                    db,
                    title="Repeated live sync failure",
                    detail=f"{blog.name}: {exc}",
                )
            continue

        _sync_failure_streak(db, failed=False)
        after_rows = db.execute(
            select(SyncedBloggerPost.id, SyncedBloggerPost.updated_at_remote, SyncedBloggerPost.content_html)
            .where(SyncedBloggerPost.blog_id == blog.id)
        ).all()
        for row in after_rows:
            current_id = int(row[0])
            new_updated_at = row[1].isoformat() if row[1] else None
            new_hash = _content_hash(row[2])
            before = before_map.get(current_id)
            if before and before["updated_at_remote"] == new_updated_at and before["content_hash"] == new_hash:
                continue
            review_synced_post(db, current_id, trigger="live_sync")
            reviewed_count += 1
            changed_count += 1

    build_learning_snapshot(db)
    return {
        "status": "ok" if not failed_blogs else "partial",
        "reviewed_count": reviewed_count,
        "changed_count": changed_count,
        "failed_blogs": failed_blogs,
    }
