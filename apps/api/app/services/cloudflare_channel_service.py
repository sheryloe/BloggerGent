from __future__ import annotations

from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
import hashlib
import io
import json
import math
from pathlib import Path
import re
from typing import Any, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import httpx
from PIL import Image
from slugify import slugify
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Blog, GoogleIndexUrlState, SyncedBloggerPost
from app.services.audit_service import add_log
from app.services.dedupe_utils import (
    dedupe_key as build_dedupe_key,
    pick_best_status as pick_best_dedupe_status,
    pick_preferred_url as pick_preferred_dedupe_url,
    status_priority as dedupe_status_priority,
)
from app.services.openai_usage_service import (
    FREE_TIER_DEFAULT_LARGE_TEXT_MODEL,
    route_openai_free_tier_text_model,
)
from app.services.providers.factory import get_article_provider, get_image_provider, get_runtime_config, get_topic_provider
from app.services.prompt_service import render_prompt_template
from app.services.publish_trust_gate_service import assess_publish_trust_requirements
from app.services.settings_service import get_settings_map, upsert_settings

DEFAULT_CATEGORY_SCHEDULE_TIME = "00:00"
DEFAULT_CATEGORY_TIMEZONE = "Asia/Seoul"
DEFAULT_PROMPT_STAGES = (
    "topic_discovery",
    "article_generation",
    "image_prompt_generation",
)
TOPIC_PROVIDER_CATEGORY_MISMATCH_FALLBACK_STREAK = 2
TOPIC_TEMPLATE_CATEGORY_MISMATCH_FALLBACK_STREAK = 2
CLOUDFLARE_RELAXED_GEO_MIN_SCORE = 40.0
RELAXED_GEO_CATEGORY_SLUGS = {
    "개발과-프로그래밍",
    "개발과도구",
}
CLOUDFLARE_DAILY_MAX_CATEGORY_ATTEMPTS = 3
MAX_TOPIC_REGEN_ATTEMPTS_PER_CATEGORY = 4
DEFAULT_TOPIC_HISTORY_LOOKBACK_DAYS = 180
DEFAULT_TOPIC_NOVELTY_CLUSTER_THRESHOLD = 0.85
DEFAULT_TOPIC_NOVELTY_ANGLE_THRESHOLD = 0.75
DEFAULT_TOPIC_SOFT_PENALTY_THRESHOLD = 2
TOPIC_CLUSTER_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "into",
    "about",
    "guide",
    "tips",
    "update",
    "news",
    "2026",
}

CLOUDFLARE_PROMPT_FILE_MAP: dict[str, tuple[str, ...]] = {
    "01_travel_festival_v3.md": ("여행과-기록", "축제와-현장"),
    "02_culture_exhibition_popup_v3.md": ("문화와-공간",),
    "03_mystery_history_v3.md": ("미스테리아-스토리",),
    "04_company_analysis_v3.md": ("동그리의-생각",),
    "05_stock_weekly_v3.md": ("주식의-흐름",),
    "06_crypto_v3.md": ("크립토의-흐름",),
    "07_welfare_life_v3.md": ("삶을-유용하게", "삶의-기름칠", "일상과-메모"),
    "08_it_ai_tools_v3.md": ("개발과-프로그래밍",),
}

README_V3_LEAF_WEIGHTS: dict[str, int] = {
    "여행과기록": 10,
    "여행과-기록": 10,
    "축제와현장": 10,
    "축제와-현장": 10,
    "문화와공간": 12,
    "문화와-공간": 12,
    "미스터리-스토리": 10,
    "미스테리아-스토리": 10,
    "주식-흐름": 8,
    "주식의-흐름": 8,
    "크립토-흐름": 10,
    "크립토의-흐름": 10,
    "생활-실용": 6,
    "삶을-유용하게": 6,
    "생활-기록": 6,
    "삶의-기름칠": 6,
    "일상과메모": 6,
    "일상과-메모": 6,
    "개발과도구": 6,
    "개발과-프로그래밍": 6,
    "동그리의-생각": 5,
    "기술의기록": 6,
}

BLOSSOM_KEYWORDS = (
    "cherry blossom",
    "cherry-blossom",
    "blossom",
    "sakura",
    "벚꽃",
    "봄꽃",
    "벚꽃축제",
    "꽃놀이",
)

FALLBACK_CATEGORIES: tuple[dict[str, str | None], ...] = (
    {
        "id": "cat-donggri-dev",
        "slug": "개발과-프로그래밍",
        "name": "개발과 프로그래밍",
        "description": "개발, AI, 자동화, 실무 도구를 다루는 카테고리",
        "parentId": "cat-donggri",
    },
    {
        "id": "cat-donggri-travel",
        "slug": "여행과-기록",
        "name": "여행과 기록",
        "description": "여행 동선, 장소 기록, 현장 팁을 다루는 카테고리",
        "parentId": "cat-donggri",
    },
    {
        "id": "cat-donggri-daily",
        "slug": "일상과-메모",
        "name": "일상과 메모",
        "description": "생활 메모와 실용 정보를 정리하는 카테고리",
        "parentId": "cat-donggri",
    },
    {
        "id": "cat-donggri-life",
        "slug": "삶의-기름칠",
        "name": "삶의 기름칠",
        "description": "루틴, 정리, 생활 감각을 다루는 카테고리",
        "parentId": "cat-donggri",
    },
    {
        "id": "cat-donggri-utility",
        "slug": "삶을-유용하게",
        "name": "삶을 유용하게",
        "description": "실용 팁과 체크리스트를 다루는 카테고리",
        "parentId": "cat-donggri",
    },
    {
        "id": "cat-donggri-finance-stock",
        "slug": "주식의-흐름",
        "name": "주식의 흐름",
        "description": "시장 흐름과 종목 관찰 포인트를 다루는 카테고리",
        "parentId": "cat-donggri",
    },
    {
        "id": "cat-donggri-finance-crypto",
        "slug": "크립토의-흐름",
        "name": "크립토의 흐름",
        "description": "코인과 블록체인 흐름을 다루는 카테고리",
        "parentId": "cat-donggri",
    },
    {
        "id": "cat-donggri-culture",
        "slug": "문화와-공간",
        "name": "문화와 공간",
        "description": "전시, 공간, 문화 경험을 다루는 카테고리",
        "parentId": "cat-donggri",
    },
    {
        "id": "cat-donggri-festival",
        "slug": "축제와-현장",
        "name": "축제와 현장",
        "description": "축제 현장 정보와 시즌 이슈를 다루는 카테고리",
        "parentId": "cat-donggri",
    },
    {
        "id": "cat-world-mysteria-story",
        "slug": "미스테리아-스토리",
        "name": "미스테리아 스토리",
        "description": "사건, 전설, 역사 미스터리를 다루는 카테고리",
        "parentId": "cat-donggri",
    },
    {
        "id": "cat-world-donggri-thought",
        "slug": "동그리의-생각",
        "name": "동그리의 생각",
        "description": "현상, 서비스, 브랜드, 문화 흐름에 대한 해석과 생각을 다루는 카테고리",
        "parentId": "cat-donggri",
    },
)

CLOUDFLARE_CANONICAL_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "개발과-프로그래밍": (
        "ai",
        "llm",
        "gpt",
        "claude",
        "cursor",
        "codex",
        "agent",
        "workflow",
        "automation",
        "api",
        "python",
        "개발",
        "프로그래밍",
        "자동화",
        "에이전트",
        "코딩",
    ),
    "삶을-유용하게": (
        "복지",
        "지원금",
        "신청",
        "대상",
        "서류",
        "혜택",
        "환급",
        "할인",
        "이벤트",
        "행사",
        "정책",
        "지원",
        "생활정보",
    ),
    "삶의-기름칠": (
        "명언",
        "마음가짐",
        "태도",
        "루틴",
        "습관",
        "멘탈",
        "집중",
        "회복",
        "동기",
        "마음",
        "생각정리",
    ),
    "여행과-기록": ("여행", "코스", "동선", "방문", "route", "trip", "travel", "visit", "itinerary"),
    "축제와-현장": ("축제", "현장", "행사", "festival", "event", "fair", "expo", "팝업현장"),
    "문화와-공간": ("문화", "공간", "전시", "미술관", "박물관", "popup", "museum", "gallery", "architecture"),
    "미스테리아-스토리": ("미스터리", "미스테리아", "전설", "괴담", "unsolved", "mystery", "legend", "haunted"),
    "동그리의-생각": ("생각", "브랜드", "해석", "인사이트", "opinion", "analysis", "company", "service"),
    "주식의-흐름": ("주식", "증시", "실적", "etf", "stock", "earnings", "market"),
    "크립토의-흐름": ("비트코인", "이더리움", "코인", "토큰", "crypto", "bitcoin", "ethereum", "token"),
    "일상과-메모": ("일상", "메모", "정리", "노트", "daily", "memo", "note", "diary"),
}

CATEGORY_TOPIC_GUIDANCE: dict[str, str] = {}
CATEGORY_MODULE_GUIDANCE: dict[str, tuple[str, ...]] = {}
CATEGORY_IMAGE_GUIDANCE: dict[str, str] = {}
def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _prompt_root() -> Path:
    resolved = Path(__file__).resolve()
    candidates = [
        resolved.parents[2] / "prompts" / "cloudflare",  # /app/prompts/cloudflare inside containers
        Path.cwd() / "prompts" / "cloudflare",  # local repo execution
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _extract_code_blocks(markdown: str) -> list[str]:
    blocks: list[str] = []
    for match in re.finditer(r"```(?:[a-zA-Z0-9_-]+)?\n(.*?)```", markdown, flags=re.DOTALL):
        block = (match.group(1) or "").strip()
        if block:
            blocks.append(block)
    return blocks


def _category_slug_key(category: dict[str, Any]) -> str:
    return str(category.get("slug") or "").strip()


def _leaf_category_ids(categories: list[dict[str, Any]]) -> set[str]:
    parents = {str(item.get("parentId") or "").strip() for item in categories if str(item.get("parentId") or "").strip()}
    return {
        str(item.get("id") or "").strip()
        for item in categories
        if str(item.get("id") or "").strip() and str(item.get("id") or "").strip() not in parents
    }


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return fallback


def _safe_float(value: Any, fallback: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return fallback


def _resolve_topic_history_settings(values: dict[str, str]) -> tuple[int, float, float, int]:
    lookback_days = max(_safe_int(values.get("topic_history_lookback_days"), DEFAULT_TOPIC_HISTORY_LOOKBACK_DAYS), 1)
    cluster_threshold = _safe_float(values.get("topic_novelty_cluster_threshold"), DEFAULT_TOPIC_NOVELTY_CLUSTER_THRESHOLD)
    angle_threshold = _safe_float(values.get("topic_novelty_angle_threshold"), DEFAULT_TOPIC_NOVELTY_ANGLE_THRESHOLD)
    penalty_threshold = max(_safe_int(values.get("topic_soft_penalty_threshold"), DEFAULT_TOPIC_SOFT_PENALTY_THRESHOLD), 1)
    return lookback_days, cluster_threshold, angle_threshold, penalty_threshold


def _parse_cloudflare_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _infer_topic_cluster_angle(keyword: str) -> tuple[str, str]:
    text = str(keyword or "").strip()
    for delimiter in ("|", ":", " - ", " ??"):
        if delimiter in text:
            left, right = text.split(delimiter, 1)
            return left.strip(), right.strip()
    return "", ""


def _build_cloudflare_history_entries_from_posts(
    posts: Sequence[dict[str, Any]],
    *,
    lookback_days: int,
    limit: int,
    entry_cls: type[Any],
) -> list[Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(int(lookback_days or 1), 1))
    entries: list[Any] = []
    seen: set[str] = set()
    for post in posts:
        dt = _parse_cloudflare_datetime(post.get("publishedAt") or post.get("updatedAt") or post.get("createdAt"))
        if dt is None or dt < cutoff:
            continue
        title = str(post.get("title") or "").strip()
        if not title:
            continue
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        category = post.get("category") if isinstance(post.get("category"), dict) else {}
        entries.append(
            entry_cls(
                keyword=title,
                topic_cluster=str(category.get("slug") or category.get("name") or "").strip(),
                topic_angle=str(post.get("excerpt") or "").strip()[:120],
                category=str(category.get("name") or "").strip(),
                profile="",
                blog="cloudflare",
                published_at=dt.isoformat(),
                source="db_fallback",
            )
        )
        if len(entries) >= max(limit, 1):
            break
    return entries


def _quality_gate_thresholds(values: dict[str, str]) -> dict[str, float]:
    enabled = _is_enabled(values.get("quality_gate_enabled"), default=True)
    return {
        "enabled": 1.0 if enabled else 0.0,
        "similarity_threshold": _safe_float(values.get("quality_gate_similarity_threshold"), 65.0),
        "min_seo_score": _safe_float(values.get("quality_gate_min_seo_score"), 70.0),
        "min_geo_score": _safe_float(values.get("quality_gate_min_geo_score"), 60.0),
        "min_ctr_score": _safe_float(values.get("quality_gate_min_ctr_score"), 60.0),
    }


def _quality_gate_fail_reasons(
    *,
    similarity_score: float,
    seo_score: float,
    geo_score: float,
    ctr_score: float,
    similarity_threshold: float,
    min_seo_score: float,
    min_geo_score: float,
    min_ctr_score: float,
) -> list[str]:
    reasons: list[str] = []
    if similarity_score >= similarity_threshold:
        reasons.append("similarity_threshold")
    if seo_score < min_seo_score:
        reasons.append("seo_below_min")
    if geo_score < min_geo_score:
        reasons.append("geo_below_min")
    if ctr_score < min_ctr_score:
        reasons.append("ctr_below_min")
    return reasons


def _is_blossom_topic_keyword(keyword: str | None) -> bool:
    lowered = str(keyword or "").strip().lower()
    if not lowered:
        return False
    return any(token in lowered for token in BLOSSOM_KEYWORDS)


def _load_daily_topic_mix_counter(raw_value: str | None, *, today: str) -> dict[str, int]:
    try:
        payload = json.loads(raw_value or "{}")
    except json.JSONDecodeError:
        payload = {}
    if str(payload.get("date") or "") != today:
        return {"total_topics": 0, "blossom_topics": 0}
    return {
        "total_topics": max(_safe_int(payload.get("total_topics"), 0), 0),
        "blossom_topics": max(_safe_int(payload.get("blossom_topics"), 0), 0),
    }


def _dump_daily_topic_mix_counter(*, today: str, counter: dict[str, int]) -> str:
    return json.dumps(
        {
            "date": today,
            "total_topics": max(_safe_int(counter.get("total_topics"), 0), 0),
            "blossom_topics": max(_safe_int(counter.get("blossom_topics"), 0), 0),
        },
        ensure_ascii=False,
    )


def _would_exceed_blossom_cap(*, counter: dict[str, int], is_blossom: bool, cap_ratio: float) -> bool:
    if not is_blossom:
        return False
    normalized_cap = max(min(cap_ratio, 1.0), 0.0)
    if normalized_cap <= 0.0:
        return True
    if normalized_cap >= 1.0:
        return False
    total_next = max(_safe_int(counter.get("total_topics"), 0), 0) + 1
    blossom_next = max(_safe_int(counter.get("blossom_topics"), 0), 0) + 1
    max_allowed_blossom = max(1, math.floor(float(total_next) * normalized_cap))
    return blossom_next > max_allowed_blossom


def _increment_topic_mix_counter(counter: dict[str, int], *, is_blossom: bool) -> None:
    counter["total_topics"] = max(_safe_int(counter.get("total_topics"), 0), 0) + 1
    if is_blossom:
        counter["blossom_topics"] = max(_safe_int(counter.get("blossom_topics"), 0), 0) + 1


def _build_blossom_block_prompt(*, blocked_keywords: list[str], cap_ratio: float, limit: int = 16) -> str:
    if not blocked_keywords:
        return ""
    unique_keywords: list[str] = []
    seen: set[str] = set()
    for raw in blocked_keywords:
        keyword = str(raw or "").strip()
        lowered = keyword.lower()
        if not keyword or lowered in seen:
            continue
        seen.add(lowered)
        unique_keywords.append(keyword)
        if len(unique_keywords) >= max(limit, 1):
            break
    if not unique_keywords:
        return ""
    bullet_list = "\n".join(f"- {item}" for item in unique_keywords)
    return (
        "\n\n[Daily blossom cap guard]\n"
        f"- Cherry blossom topics are capped at {cap_ratio * 100:.0f}% for this channel today.\n"
        "- Generate non-blossom alternatives with different cluster and angle.\n"
        "- Blocked blossom candidates:\n"
        f"{bullet_list}"
    )


def _load_daily_counter(raw: str | None, *, today: str, keys: list[str]) -> dict[str, int]:
    payload: dict[str, Any] = {}
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        payload = {}
    if str(payload.get("date") or "") != today:
        return {key: 0 for key in keys}
    counts = payload.get("counts")
    if not isinstance(counts, dict):
        return {key: 0 for key in keys}
    return {key: max(_safe_int(counts.get(key), 0), 0) for key in keys}


def _serialize_daily_counter(*, today: str, counts: dict[str, int]) -> str:
    return json.dumps({"date": today, "counts": counts}, ensure_ascii=False)


def _parse_schedule_minutes(raw_value: str | None, fallback: str) -> int:
    candidate = str(raw_value or fallback).strip() or fallback
    parts = candidate.split(":")
    if len(parts) != 2:
        candidate = fallback
        parts = candidate.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except (TypeError, ValueError):
        hour, minute = 0, 0
    hour = max(0, min(hour, 23))
    minute = max(0, min(minute, 59))
    return (hour * 60) + minute


def _slot_marker_for_now(
    now: datetime,
    *,
    start_time_raw: str | None,
    fallback_time: str,
    interval_hours: int,
) -> str | None:
    interval_minutes = max(interval_hours, 1) * 60
    current_minutes = (now.hour * 60) + now.minute
    start_minutes = _parse_schedule_minutes(start_time_raw, fallback_time)
    delta_minutes = current_minutes - start_minutes
    if delta_minutes < 0 or delta_minutes % interval_minutes != 0:
        return None
    return now.replace(second=0, microsecond=0).isoformat(timespec="minutes")


def _parse_slot_marker(raw_value: str | None, *, timezone_name: str) -> datetime | None:
    candidate = str(raw_value or "").strip()
    if not candidate:
        return None
    normalized = candidate[:-1] + "+00:00" if candidate.endswith("Z") else candidate
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    tz = ZoneInfo(timezone_name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def _build_due_slot_markers(
    now: datetime,
    *,
    start_time_raw: str | None,
    fallback_time: str,
    interval_hours: int,
    last_run_slot: str | None,
    last_attempted_slot: str | None,
    timezone_name: str,
) -> list[str]:
    interval_minutes = max(interval_hours, 1) * 60
    current_minutes = (now.hour * 60) + now.minute
    start_minutes = _parse_schedule_minutes(start_time_raw, fallback_time)
    if current_minutes < start_minutes:
        return []

    latest_slot_index = (current_minutes - start_minutes) // interval_minutes
    due_slots: list[datetime] = []
    for slot_index in range(latest_slot_index + 1):
        slot_minutes = start_minutes + (slot_index * interval_minutes)
        slot_hour = slot_minutes // 60
        slot_minute = slot_minutes % 60
        due_slots.append(now.replace(hour=slot_hour, minute=slot_minute, second=0, microsecond=0))

    last_run_at = _parse_slot_marker(last_run_slot, timezone_name=timezone_name)
    last_attempted_at = _parse_slot_marker(last_attempted_slot, timezone_name=timezone_name)
    cutoff_candidates = [
        marker
        for marker in (last_run_at, last_attempted_at)
        if marker is not None and marker.date() == now.date()
    ]
    if cutoff_candidates:
        cutoff = max(cutoff_candidates)
        due_slots = [slot for slot in due_slots if slot > cutoff]

    if not due_slots:
        return []

    # Process only the latest eligible slot to prevent catch-up bursts.
    latest_slot = due_slots[-1]
    return [latest_slot.isoformat(timespec="minutes")]


def _normalize_base_url(raw_value: str | None) -> str:
    return str(raw_value or "").strip().rstrip("/")


def _public_api_url(values: dict[str, str], path: str) -> str:
    base_url = _normalize_base_url(values.get("cloudflare_blog_api_base_url"))
    if not base_url:
        return ""
    return f"{base_url}{path}"


def _public_site_base_url(values: dict[str, str]) -> str:
    api_base = _normalize_base_url(values.get("cloudflare_blog_api_base_url"))
    if not api_base:
        return ""
    parsed = urlparse(api_base)
    host = parsed.netloc
    if host.startswith("api."):
        host = host[4:]
    if not host:
        return ""
    return f"{parsed.scheme}://{host}"


def _fetch_json(url: str) -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "BloggerGent/1.0 (+https://dongriarchive.com)",
        },
    )
    with urlopen(request, timeout=10) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8-sig"))
    if isinstance(payload, dict) and "data" in payload:
        return payload.get("data")
    return payload


_REMOTE_CATEGORY_CHILD_KEYS: tuple[str, ...] = (
    "children",
    "childCategories",
    "subcategories",
    "subCategories",
)


def _remote_category_text(*values: Any) -> str:
    return " ".join(str(value or "").strip() for value in values if str(value or "").strip()).casefold()


def _iter_remote_category_children(item: dict[str, Any]) -> list[dict[str, Any]]:
    children: list[dict[str, Any]] = []
    for key in _REMOTE_CATEGORY_CHILD_KEYS:
        raw = item.get(key)
        if not isinstance(raw, list):
            continue
        children.extend(child for child in raw if isinstance(child, dict))
    return children


def _build_generated_category_id(*, parent_id: str, slug: str, name: str) -> str:
    source = slug.strip() or name.strip()
    if not source:
        return ""
    normalized = slugify(source, separator="-")
    if not normalized:
        return ""
    parent_key = slugify(parent_id, separator="-") if parent_id else "root"
    return f"cat-generated-{parent_key}-{normalized}"


def _flatten_remote_categories(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    raw_items = [item for item in payload if isinstance(item, dict)]
    flattened: list[dict[str, Any]] = []
    index_by_id: dict[str, int] = {}

    def walk(node: dict[str, Any], parent_id: str | None) -> None:
        raw_id = str(node.get("id") or "").strip()
        raw_slug = str(node.get("slug") or "").strip()
        raw_name = str(node.get("name") or "").strip()
        raw_parent = str(node.get("parentId") or "").strip()
        resolved_parent = raw_parent or (parent_id or "")
        category_id = raw_id or _build_generated_category_id(parent_id=resolved_parent, slug=raw_slug, name=raw_name)

        if category_id and raw_slug:
            normalized = dict(node)
            normalized["id"] = category_id
            if resolved_parent:
                normalized["parentId"] = resolved_parent
            elif "parentId" in normalized:
                normalized["parentId"] = None
            if category_id in index_by_id:
                existing = flattened[index_by_id[category_id]]
                if not str(existing.get("parentId") or "").strip() and str(normalized.get("parentId") or "").strip():
                    existing["parentId"] = normalized.get("parentId")
                for key in ("name", "description", "createdAt", "updatedAt"):
                    if not existing.get(key) and normalized.get(key):
                        existing[key] = normalized.get(key)
            else:
                index_by_id[category_id] = len(flattened)
                flattened.append(normalized)

        next_parent = category_id or resolved_parent or None
        for child in _iter_remote_category_children(node):
            walk(child, next_parent)

    for item in raw_items:
        walk(item, None)
    return flattened


def _ensure_midnight_scp_leaf(categories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not categories:
        return categories
    midnight = next(
        (
            item
            for item in categories
            if "midnight" in _remote_category_text(item.get("slug"), item.get("name"), item.get("id"))
        ),
        None,
    )
    if midnight is None:
        return categories

    midnight_id = str(midnight.get("id") or "").strip()
    for item in categories:
        text = _remote_category_text(item.get("slug"), item.get("name"), item.get("id"))
        if "scp" not in text:
            continue
        parent_id = str(item.get("parentId") or "").strip()
        if parent_id == midnight_id:
            return categories

    scp_id = f"{midnight_id}-scp" if midnight_id else "cat-midnight-scp"
    if any(str(item.get("id") or "").strip() == scp_id for item in categories):
        return categories

    appended = list(categories)
    appended.append(
        {
            "id": scp_id,
            "slug": "scp",
            "name": "SCP",
            "description": "Midnight category SCP archive",
            "parentId": midnight_id or None,
            "createdAt": _utc_now_iso(),
            "updatedAt": _utc_now_iso(),
        }
    )
    return appended


def _list_remote_categories(values: dict[str, str]) -> list[dict]:
    url = _public_api_url(values, "/api/public/categories")
    if not url:
        return []
    try:
        payload = _fetch_json(url)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return []
    flattened = _flatten_remote_categories(payload)
    return _ensure_midnight_scp_leaf(flattened)


def _list_remote_posts(values: dict[str, str]) -> list[dict]:
    url = _public_api_url(values, "/api/public/posts")
    if not url:
        return []
    try:
        payload = _fetch_json(url)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return []
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _fetch_remote_site_settings(values: dict[str, str]) -> dict[str, Any]:
    url = _public_api_url(values, "/api/public/settings")
    if not url:
        return {}
    try:
        payload = _fetch_json(url)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _cloudflare_category_search_text(*values: str | None) -> str:
    return " ".join(str(value or "").strip() for value in values if str(value or "").strip()).casefold()


def _cloudflare_prompt_profile(category_slug: str, category_name: str, category_description: str, category_id: str = "") -> str:
    text = _cloudflare_category_search_text(category_id, category_slug, category_name, category_description)
    if any(token in text for token in ("mystery", "mysteria", "case", "archive", "legend", "lore", "미스터리", "미스테리", "전설", "괴담", "기록")):
        return "mystery"
    if any(token in text for token in ("travel", "festival", "culture", "food", "trip", "tour", "popup", "museum", "여행", "축제", "문화", "맛집", "전시", "카페")):
        return "travel"
    if any(token in text for token in ("stock", "crypto", "coin", "blockchain", "주식", "코인", "가상자산")):
        return "finance"
    if any(token in text for token in ("dev", "tool", "ai", "tech", "program", "개발", "도구", "기술")):
        return "tech"
    if any(token in text for token in ("daily", "life", "memo", "welfare", "생활", "메모", "복지")):
        return "daily"
    return "general"


def _category_topic_guidance(category_slug: str, category_name: str, category_description: str) -> str:
    if category_slug == "삶을-유용하게":
        return "복지, 지원금, 신청 절차, 생활 실용 정보, 행사·이벤트처럼 바로 확인하고 실행할 수 있는 주제만 다룹니다."
    if category_slug == "삶의-기름칠":
        return "명언, 마음가짐, 태도, 루틴, 삶의 정리처럼 내면 정돈과 생활 감각을 다루되 복지·지원금형 정보 글은 배제합니다."
    if category_slug == "개발과-프로그래밍":
        return "AI 코딩, LLM 에이전트, 자동화 워크플로우, 무료 vs 유료 비교, 실사용 셋업처럼 바로 적용 가능한 개발 주제만 다룹니다."
    profile = _cloudflare_prompt_profile(category_slug, category_name, category_description)
    if profile == "mystery":
        return "문서화된 사실, 기록, 해석 차이를 분리해서 읽을 수 있는 다큐형 미스터리 주제를 다룹니다."
    if profile == "travel":
        return "실제 방문 결정에 도움이 되는 동선, 장소 선택, 체류 포인트, 시즌성을 중심으로 다룹니다."
    if profile == "finance":
        return "가격 방향을 단정하기보다 흐름, 변수, 리스크, 체크 포인트를 빠르게 이해하게 돕습니다."
    if profile == "tech":
        return "실무 적용성, 비교 포인트, 선택 기준이 바로 잡히는 도구·기술형 글을 우선합니다."
    if profile == "daily":
        return "바로 써먹을 수 있는 생활 판단 기준과 준비 포인트를 짧고 명확하게 정리합니다."
    return category_description or f"{category_name} 카테고리에 맞는 실전형 블로그 주제를 다룹니다."


def _category_modules(category_slug: str) -> tuple[str, ...]:
    normalized = _cloudflare_category_search_text(category_slug)
    if category_slug == "삶을-유용하게":
        return ("대상 확인", "핵심 혜택", "신청 방법", "실수 방지", "바로 할 일")
    if category_slug == "삶의-기름칠":
        return ("문제 장면", "생각 전환", "실천 루틴", "지속 팁", "마무리 문장")
    if category_slug == "개발과-프로그래밍":
        return ("문제 정의", "도구 비교", "설정 방법", "실사용 예시", "선택 기준")
    if any(token in normalized for token in ("travel", "festival", "culture", "food", "여행", "축제", "문화", "맛집")):
        return ("검색 의도", "방문 결정 포인트", "현장 감각", "주의사항", "실행 팁")
    if any(token in normalized for token in ("mystery", "mysteria", "case", "archive", "legend", "미스터리", "전설", "괴담")):
        return ("핵심 사건", "기록과 증거", "주요 해석", "논쟁 지점", "지금도 읽히는 이유")
    if any(token in normalized for token in ("stock", "crypto", "coin", "주식", "코인")):
        return ("현재 흐름", "리스크 포인트", "체크 지표", "시나리오", "실행 판단")
    if any(token in normalized for token in ("dev", "tool", "ai", "tech", "개발", "도구", "기술")):
        return ("문제 정의", "도구 비교", "실무 적용", "주의점", "추천 상황")
    if any(token in normalized for token in ("daily", "life", "memo", "welfare", "생활", "메모", "복지")):
        return ("핵심 요약", "준비물", "실수 방지", "체크리스트", "실행 순서")
    return ("핵심 요약", "실전 정보", "결정 포인트", "주의사항", "바로 할 일")


def _category_image_guidance(category_slug: str) -> str:
    normalized = _cloudflare_category_search_text(category_slug)
    if category_slug == "삶을-유용하게":
        return "한국 생활 맥락이 읽히는 실제 신청·확인·준비 장면과 생활 도구가 보이는 현실 사진이 맞습니다."
    if category_slug == "삶의-기름칠":
        return "과한 감성 연출보다 한국 일상 공간에서 생각을 정리하거나 루틴을 실천하는 현실적인 장면이 맞습니다."
    if category_slug == "개발과-프로그래밍":
        return "한국형 업무 환경에서 노트북, IDE, 터미널, 협업 문서, 자동화 흐름이 보이는 실사 장면이 맞습니다."
    if any(token in normalized for token in ("mystery", "mysteria", "case", "archive", "legend", "미스터리", "괴담", "전설")):
        return "문서, 장소, 흔적, 조사 분위기가 바로 읽히는 다큐멘터리형 장면이 맞습니다."
    if any(token in normalized for token in ("travel", "festival", "culture", "food", "여행", "축제", "문화", "맛집")):
        return "독자가 가고 싶어지는 실제 장소성과 현장 밀도를 먼저 보여주는 장면이 맞습니다."
    if any(token in normalized for token in ("stock", "crypto", "coin", "주식", "코인")):
        return "추상 아이콘보다 화면, 차트 맥락, 의사결정 분위기가 느껴지는 현실적인 장면이 맞습니다."
    if any(token in normalized for token in ("dev", "tool", "ai", "tech", "개발", "도구", "기술")):
        return "실무 도구를 다루는 손, 화면, 작업 환경처럼 사용 맥락이 보이는 장면이 맞습니다."
    return "글의 핵심 약속이 한눈에 읽히는 현실적인 대표 장면이 맞습니다."


def _cloudflare_editorial_category_key(category_slug: str) -> str:
    normalized = _cloudflare_category_search_text(category_slug)
    if any(token in normalized for token in ("food", "restaurant", "cafe", "market", "맛집", "카페", "먹거리")):
        return "food"
    if any(token in normalized for token in ("festival", "culture", "popup", "museum", "exhibition", "heritage", "축제", "문화", "전시", "뮤지엄")):
        return "culture"
    if any(token in normalized for token in ("legend", "lore", "folklore", "scp", "괴담", "전설", "민속")):
        return "legends-lore"
    if any(token in normalized for token in ("archive", "history", "historical", "기록", "역사", "아카이브")):
        return "mystery-archives"
    if any(token in normalized for token in ("mystery", "mysteria", "case", "unsolved", "미스터리", "사건")):
        return "case-files"
    if any(token in normalized for token in ("travel", "trip", "tour", "visit", "여행", "동선", "코스")):
        return "travel"
    return "general"


def _cloudflare_target_audience(category_slug: str, category_name: str) -> str:
    if category_slug == "삶을-유용하게":
        return "지원 제도, 생활 혜택, 행사 정보, 신청 순서를 빠르게 파악하고 바로 행동하려는 독자"
    if category_slug == "삶의-기름칠":
        return "삶의 태도와 루틴을 가볍지 않게 정리하고, 실제로 지속 가능한 변화를 만들고 싶은 독자"
    if category_slug == "개발과-프로그래밍":
        return "AI 도구와 자동화 흐름을 실무에 바로 붙이고 싶고, 무료와 유료 선택 기준까지 알고 싶은 개발 실무 독자"
    profile = _cloudflare_prompt_profile(category_slug, category_name, "")
    if profile == "mystery":
        return "사실과 해석을 구분해서 읽고 싶고, 기록과 출처를 따라가며 보는 독자"
    if profile == "travel":
        return "실제 방문 전 결정을 하려는 독자. 동선, 시간, 비용, 대기, 체류 포인트를 빠르게 파악하고 싶어 한다."
    if profile == "finance":
        return "가격 예측보다 흐름과 리스크를 빠르게 정리해 의사결정에 참고하려는 독자"
    if profile == "tech":
        return "업무에 바로 적용할 도구와 방법을 비교하고 선택 기준을 알고 싶은 실무 독자"
    if profile == "daily":
        return "복잡한 설명보다 바로 실행 가능한 생활 정보와 체크 포인트를 원하는 독자"
    return f"{category_name} 주제에서 핵심 판단 포인트를 빠르게 알고 싶은 블로그 독자"


def _cloudflare_content_brief(category_slug: str, category_name: str, category_description: str) -> str:
    if category_slug == "삶을-유용하게":
        return "복지, 지원금, 생활 정보, 행사 안내를 블로그답게 풀되 대상·준비물·실행 순서를 바로 이해하게 만드는 실용형 글을 만듭니다."
    if category_slug == "삶의-기름칠":
        return "명언 모음처럼 흩어지지 않게 문제 장면, 생각 전환, 실천 루틴까지 자연스럽게 이어지는 태도형 블로그 글을 만듭니다."
    if category_slug == "개발과-프로그래밍":
        return "AI 코딩, LLM 에이전트, 자동화 워크플로우, 무료 vs 유료 비교를 실사용 셋업과 선택 기준 중심으로 정리하는 개발형 글을 만듭니다."
    profile = _cloudflare_prompt_profile(category_slug, category_name, category_description)
    if profile == "mystery":
        return "다큐멘터리형 미스터리 블로그처럼 기록, 정황, 해석 차이를 분리하고 과장 없이 긴장감을 유지하는 글을 만듭니다."
    if profile == "travel":
        return "클릭을 부르되 과장하지 않고, 실제 방문에 도움이 되는 장소 선택·동선·현장 정보 중심의 여행형 글을 만듭니다."
    if profile == "finance":
        return "점수 리포트처럼 쓰지 말고, 흐름·변수·리스크를 실전 판단 기준으로 정리하는 금융형 글을 만듭니다."
    if profile == "tech":
        return "툴 나열보다 왜 써야 하는지, 언제 맞는지, 무엇이 달라지는지를 바로 이해시키는 실무형 글을 만듭니다."
    if profile == "daily":
        return "체크리스트와 실행 순서가 바로 보이는 생활형 블로그 글을 짧고 명확하게 만듭니다."
    return category_description or f"{category_name} 주제를 블로그 독자가 바로 읽고 활용할 수 있는 실전형 글로 만듭니다."


def _read_master_prompt_template(file_name: str) -> str:
    resolved = Path(__file__).resolve()
    app_root = resolved.parents[2] if len(resolved.parents) >= 3 else Path.cwd()
    candidates = (
        app_root / "prompts" / file_name,
        Path.cwd() / "prompts" / file_name,
        Path("/app/prompts") / file_name,
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    raise FileNotFoundError(f"Prompt template not found: {file_name}")


def _cloudflare_master_prompt_file(category: dict[str, Any], stage: str) -> str:
    category_id = str(category.get("id") or "").strip()
    category_slug = str(category.get("slug") or "").strip()
    category_name = str(category.get("name") or "").strip()
    category_description = str(category.get("description") or "").strip()
    profile = _cloudflare_prompt_profile(category_slug, category_name, category_description, category_id)
    if stage == "topic_discovery":
        return {
            "travel": "travel_topic_discovery.md",
            "mystery": "mystery_topic_discovery.md",
        }.get(profile, "topic_discovery.md")
    if stage == "article_generation":
        return {
            "travel": "travel_article_generation.md",
            "mystery": "mystery_article_generation.md",
        }.get(profile, "article_generation.md")
    return "collage_prompt.md"


def _cloudflare_stage_display_label(stage: str) -> str:
    normalized = str(stage or "").strip().lower()
    if normalized == "topic_discovery":
        return "주제 발굴"
    if normalized == "article_generation":
        return "본문 작성"
    if normalized == "image_prompt_generation":
        return "대표 이미지 프롬프트"
    return normalized or "프롬프트"


def _cloudflare_stage_default_objective(stage: str, *, category_name: str) -> str:
    normalized = str(stage or "").strip().lower()
    if normalized == "topic_discovery":
        return f"{category_name} 카테고리에 맞는 클릭 유도형 주제를 블로그 톤으로 발굴합니다."
    if normalized == "article_generation":
        return f"{category_name} 카테고리 글을 자연스러운 블로그 문체로 작성합니다."
    if normalized == "image_prompt_generation":
        return f"{category_name} 글의 첫 인상을 살리는 대표 이미지 프롬프트를 만듭니다."
    return f"{category_name} 카테고리 전용 프롬프트"


def _build_cloudflare_master_article_prompt(
    category: dict[str, Any],
    *,
    keyword: str,
    current_date: str,
    planner_brief: str,
    prompt_template: str | None = None,
) -> str:
    category_name = str(category.get("name") or category.get("slug") or "").strip()
    category_slug = str(category.get("slug") or "").strip()
    category_description = str(category.get("description") or "").strip()
    base_prompt_template = str(prompt_template or "").strip() or _build_default_article_prompt(category)
    rendered = render_prompt_template(
        base_prompt_template,
        blog_name=f"Dongri Archive | {category_name or 'Cloudflare'}",
        keyword=keyword,
        primary_language="ko",
        target_audience=_cloudflare_target_audience(category_slug, category_name),
        content_brief=_cloudflare_content_brief(category_slug, category_name, category_description),
        planner_brief=planner_brief or "플래너 브리프 없음",
        current_date=current_date,
        editorial_category_key=_cloudflare_editorial_category_key(category_slug),
        editorial_category_label=category_name or "Cloudflare",
        editorial_category_guidance=_category_topic_guidance(category_slug, category_name, category_description),
        article_title="{article_title}",
        article_excerpt="{article_excerpt}",
        article_context="{article_context}",
    )
    policy_block = (
        "[Cloudflare article policy]\n"
        "- Write like a publish-ready Korean blog article for real readers, not an audit note or compliance memo.\n"
        "- Use natural topic-first headings. Do not use headings like '점수 높이기 위하여 해야 할 것', '점수 개선 체크리스트', or '품질 진단 결과' unless the topic itself is a diagnosis.\n"
        "- Keep the body substantial enough for a real 6 to 10 minute read without filler.\n"
        "- If schedules, prices, eligibility, or operating details can change, use recheck wording naturally inside the relevant section.\n"
    )
    if "[Cloudflare article policy]" in rendered:
        return rendered
    return f"{rendered.rstrip()}\n\n{policy_block}"


def _render_bullets(items: tuple[str, ...]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _is_mysteria_story_category(*, category_id: str, category_slug: str) -> bool:
    lowered = f"{category_id} {category_slug}".casefold()
    return (
        "cat-world-mysteria-story" in lowered
        or "mysteria" in lowered
        or "mystery" in lowered
    )


def _build_mysteria_blogger_source_block(
    db: Session,
    *,
    category_id: str,
    category_slug: str,
    pair_size: int = 2,
    preview_limit: int = 6,
) -> str:
    if not _is_mysteria_story_category(category_id=category_id, category_slug=category_slug):
        return ""

    intro_lines = [
        "[誘몄뒪?뚮━???ㅽ넗由??뚯뒪 ?댁쁺 而⑥뀎]",
        "- ??移댄뀒怨좊━??Blogger ?먮낯 ?뚯뒪瑜??쒓뎅??臾명솕沅?留λ씫??留욊쾶 ?ш?怨듯븯??諛⑹떇?쇰줈 ?묒꽦?⑸땲??",
        "- DB ?뚯뒪 ?먮뒗 ?ㅻ옒??湲遺??ascending) ?쒖꽌?濡??쎄퀬, ???뚯감??2媛쒖뵫(source pair) 臾띠뼱 ?ъ슜?⑸땲??",
        "- ?⑥닚 吏곸뿭 湲덉?: ?ъ떎 愿怨?異쒖쿂???좎??섍퀬 ?쒓뎅 ?낆옄 湲곗???留λ씫, ?⑹뼱, ?ㅻ챸 ?쒖꽌濡??ш뎄?깊빀?덈떎.",
        "- source pair?먯꽌 寃뱀튂???ъ떎? 援먯감 寃利??ъ씤?몃줈 ?뺣━?섍퀬, ?곸땐 ?댁슜? 遺꾨━ ?쒓린?⑸땲??",
        "- 蹂몃Ц?먯꽌 ?먮Ц ?쒗쁽??湲멸쾶 蹂듭궗?섏? 留먭퀬, 寃利?媛?ν븳 ?ъ떎 以묒떖???쒓뎅???ㅽ걧硫섑꽣由??ㅼ쑝濡??곷땲??",
    ]

    try:
        blog_ids = (
            db.execute(
                select(Blog.id)
                .where(Blog.profile_key == "world_mystery")
                .order_by(Blog.is_active.desc(), Blog.id.desc())
            )
            .scalars()
            .all()
        )
        if not blog_ids:
            return "\n".join(intro_lines) + "\n"

        source_rows = db.execute(
            select(SyncedBloggerPost.title, SyncedBloggerPost.url)
            .where(SyncedBloggerPost.blog_id.in_(blog_ids))
            .order_by(SyncedBloggerPost.published_at.asc().nullslast(), SyncedBloggerPost.id.asc())
            .limit(max(preview_limit, pair_size * 2))
        ).all()
        if not source_rows:
            return "\n".join(intro_lines) + "\n"

        intro_lines.append("- 현재 source queue 미리보기(오래된 순):")
        for index, row in enumerate(source_rows, start=1):
            title = str(row[0] or "").strip()
            url = str(row[1] or "").strip() or "URL 없음"
            if not title:
                continue
            intro_lines.append(f"  - source_{index}: {title} ({url})")
        intro_lines.append("- 글 생성은 source_1 + source_2를 우선 pair로 사용하고, 다음 회차는 source_3 + source_4로 진행합니다.")
    except Exception:  # noqa: BLE001
        return "\n".join(intro_lines) + "\n"

    return "\n".join(intro_lines) + "\n"


def _shared_structure_rules() -> str:
    return """[공통 원칙]
- 모든 글을 같은 템플릿처럼 찍어내지 않습니다.
- SEO와 GEO를 고려하되, 문단 길이·리듬·리스트 배치·도입 방식은 주제마다 달라져야 합니다.
- 같은 카테고리 안에서도 제목 패턴, 소제목 순서, 결론 문장을 반복하지 않습니다.
- 이모지는 0~3개 범위에서 필요한 경우에만 쓰고, 고정 위치에 박아 넣지 않습니다.
- '한눈에 보기', '정리하면', '마무리' 같은 상투적 소제목을 기계적으로 반복하지 않습니다.
"""


def _shared_fit_rules(category_name: str) -> str:
    return f"""[카테고리 적합성]
- 제목, 리드, 본문, 카테고리, 이미지가 모두 같은 중심 주제를 가리켜야 합니다.
- 카테고리가 {category_name}라면 본문의 핵심 판단 포인트도 반드시 그 카테고리 독자에게 맞아야 합니다.
- 다른 카테고리 사례를 참고할 수는 있지만, 그 예시가 제목과 대표 이미지를 먹어버리면 실패입니다.
- 메모형 글이면 메모와 루틴이 먼저 보여야 하고, 사건/장소는 보조 재료여야 합니다.
- 사건·공간·축제 글인데 generic 책상 사진이나 추상 이미지가 주인공이면 실패입니다.
"""


def _seasonal_cherry_blossom_rules() -> str:
    return """[봄 시즌 운영 원칙]
- 날짜가 3월~4월이라고 해서 벚꽃 주제를 무조건 밀어 넣지 않습니다.
- 벚꽃 주제는 채널 상한을 넘지 않는 범위에서만 선택합니다.
- 벚꽃을 다루더라도 장소·시간대·동선·현장 운영처럼 실전 정보 중심으로 제한합니다.
- 벚꽃 외에도 축제 운영, 전시/공간, 로컬 골목, 시장/먹거리 문화 일정 같은 비벚꽃 시즌 주제를 함께 섞습니다.
"""


def _build_default_topic_prompt(category: dict) -> str:
    category_id = str(category.get("id") or "").strip()
    category_name = str(category.get("name") or category.get("slug") or "Cloudflare").strip()
    category_slug = str(category.get("slug") or "").strip()
    category_description = str(category.get("description") or "").strip()
    prompt_template = _read_master_prompt_template(_cloudflare_master_prompt_file(category, "topic_discovery"))
    rendered = render_prompt_template(
        prompt_template,
        blog_name=f"Dongri Archive | {category_name}",
        keyword="{keyword}",
        primary_language="ko",
        target_audience=_cloudflare_target_audience(category_slug, category_name),
        content_brief=_cloudflare_content_brief(category_slug, category_name, category_description),
        planner_brief="{planner_brief}",
        current_date="{current_date}",
        topic_count="{topic_count}",
        editorial_category_key=_cloudflare_editorial_category_key(category_slug),
        editorial_category_label=category_name,
        editorial_category_guidance=_category_topic_guidance(category_slug, category_name, category_description),
        article_title="{article_title}",
        article_excerpt="{article_excerpt}",
        article_context="{article_context}",
    )
    return (
        f"{rendered.rstrip()}\n\n"
        "[Cloudflare topic language override]\n"
        f"- Category id: {category_id or 'unknown'}\n"
        "- Return Korean keyword candidates for this category.\n"
        "- Make the topic line feel like a natural Korean blog post subject, not a score report or audit memo.\n"
        "- Avoid headings or ideas framed as '점수 높이기 위하여 해야 할 것', '품질 진단 결과', or similar ops/report wording.\n"
    )


def _build_default_article_prompt(category: dict) -> str:
    category_name = str(category.get("name") or category.get("slug") or "Cloudflare").strip()
    category_slug = str(category.get("slug") or "").strip()
    category_description = str(category.get("description") or "").strip()
    prompt_template = _read_master_prompt_template(_cloudflare_master_prompt_file(category, "article_generation"))
    rendered = render_prompt_template(
        prompt_template,
        blog_name=f"Dongri Archive | {category_name}",
        keyword="{keyword}",
        primary_language="ko",
        target_audience=_cloudflare_target_audience(category_slug, category_name),
        content_brief=_cloudflare_content_brief(category_slug, category_name, category_description),
        planner_brief="{planner_brief}",
        current_date="{current_date}",
        editorial_category_key=_cloudflare_editorial_category_key(category_slug),
        editorial_category_label=category_name,
        editorial_category_guidance=_category_topic_guidance(category_slug, category_name, category_description),
        article_title="{article_title}",
        article_excerpt="{article_excerpt}",
        article_context="{article_context}",
    )
    return (
        f"{rendered.rstrip()}\n\n"
        "[Cloudflare article policy]\n"
        "- Write like a publish-ready Korean blog article for real readers.\n"
        "- Use natural topic-first section titles.\n"
        "- Do not turn the article into an audit note, compliance memo, score report, or checklist dump.\n"
        "- Do not use headings such as '점수 높이기 위하여 해야 할 것', '점수 개선 체크리스트', or '품질 진단 결과' unless the topic itself is a diagnosis.\n"
    )


def _build_default_image_prompt(category: dict) -> str:
    category_name = str(category.get("name") or category.get("slug") or "Cloudflare").strip()
    category_slug = str(category.get("slug") or "").strip()
    category_description = str(category.get("description") or "").strip()
    return f"""You are preparing one final English hero-image prompt for the Cloudflare blog category \"{category_name}\".

Current date: {{current_date}}
Topic: {{keyword}}
Category guidance: {_category_topic_guidance(category_slug, category_name, category_description)}
Image guidance: {_category_image_guidance(category_slug)}

Rules:
- Return plain text only.
- Write one final prompt for a single 3x3 hero collage with exactly 9 distinct panels.
- Use visible white gutters and one dominant center panel.
- Keep the visual grounded in realistic Korean context when the topic is Korea-facing.
- Use realistic editorial photography language, not illustration language.
- No text overlays, no logos, no infographic styling, and no generic checklist visuals.
- Avoid generic stock-photo mood. Show the real problem and the real usage scene.
- Match the category tone of \"{category_name}\" rather than a generic stock-photo mood.
"""


def _prompt_storage_keys(category_id: str, stage: str) -> dict[str, str]:
    prefix = f"cloudflare_prompt__{category_id}__{stage}"
    return {
        "content": f"{prefix}__content",
        "name": f"{prefix}__name",
        "objective": f"{prefix}__objective",
        "is_enabled": f"{prefix}__is_enabled",
        "provider_model": f"{prefix}__provider_model",
        "version": f"{prefix}__version",
        "created_at": f"{prefix}__created_at",
        "updated_at": f"{prefix}__updated_at",
    }


def _default_prompt_for_stage(category: dict, stage: str) -> str:
    normalized_stage = stage.strip().lower()
    if normalized_stage == "topic_discovery":
        return _build_default_topic_prompt(category)
    if normalized_stage == "image_prompt_generation":
        return _build_default_image_prompt(category)
    return _build_default_article_prompt(category)


def list_cloudflare_categories(db: Session) -> list[dict]:
    values = get_settings_map(db)
    schedule_timezone = values.get("schedule_timezone", DEFAULT_CATEGORY_TIMEZONE)
    categories = _list_remote_categories(values) or list(FALLBACK_CATEGORIES)
    leaf_ids = _leaf_category_ids(categories)
    items: list[dict] = []
    for category in categories:
        category_id = str(category.get("id") or "").strip()
        category_slug = str(category.get("slug") or "").strip()
        if not category_id or not category_slug:
            continue
        schedule_time = values.get(f"cloudflare_category_schedule__{category_id}") or DEFAULT_CATEGORY_SCHEDULE_TIME
        items.append(
            {
                "id": category_id,
                "slug": category_slug,
                "name": str(category.get("name") or category_slug),
                "description": category.get("description"),
                "parentId": str(category.get("parentId") or "").strip() or None,
                "isLeaf": category_id in leaf_ids,
                "status": "active",
                "scheduleTime": str(schedule_time).strip() or DEFAULT_CATEGORY_SCHEDULE_TIME,
                "scheduleTimezone": schedule_timezone,
                "createdAt": str(category.get("createdAt") or _utc_now_iso()),
                "updatedAt": str(category.get("updatedAt") or _utc_now_iso()),
            }
        )
    return sorted(items, key=lambda item: item["slug"])


def _canonical_cloudflare_leaf_map(categories: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    return {
        str(item.get("slug") or "").strip(): {
            "slug": str(item.get("slug") or "").strip(),
            "name": str(item.get("name") or item.get("slug") or "").strip(),
        }
        for item in categories
        if bool(item.get("isLeaf")) and str(item.get("slug") or "").strip()
    }


def _resolve_cloudflare_canonical_category(
    *,
    title: str,
    excerpt: str,
    raw_category_slug: str,
    raw_category_name: str,
    leaf_categories: dict[str, dict[str, str]],
) -> dict[str, str | None]:
    if raw_category_slug in leaf_categories:
        return leaf_categories[raw_category_slug]

    title_text = _cloudflare_category_search_text(title)
    category_text = _cloudflare_category_search_text(raw_category_slug, raw_category_name)
    excerpt_text = _cloudflare_category_search_text(excerpt)
    best_slug = ""
    best_score = -1

    for slug, keywords in CLOUDFLARE_CANONICAL_CATEGORY_KEYWORDS.items():
        if slug not in leaf_categories:
            continue
        score = 0
        for keyword in keywords:
            if keyword in title_text:
                score += 6
            if keyword in category_text:
                score += 3
            if keyword in excerpt_text:
                score += 1
        if score > best_score:
            best_slug = slug
            best_score = score

    if best_slug:
        return leaf_categories[best_slug]
    if "일상과-메모" in leaf_categories:
        return leaf_categories["일상과-메모"]
    return {"slug": raw_category_slug or None, "name": raw_category_name or None}


def _fetch_integration_post_detail(db: Session, remote_post_id: str) -> dict[str, Any]:
    post_id = str(remote_post_id or "").strip()
    if not post_id:
        return {}
    response = _integration_request(
        db,
        method="GET",
        path=f"/api/integrations/posts/{post_id}",
        timeout=45.0,
    )
    data = _integration_data_or_raise(response)
    return data if isinstance(data, dict) else {}


def _cloudflare_item_timestamp(row: dict[str, Any]) -> datetime:
    for field in ("updated_at", "published_at", "created_at"):
        parsed = _parse_cloudflare_datetime(row.get(field))
        if parsed is not None:
            return parsed
    return datetime.min.replace(tzinfo=timezone.utc)


def _cloudflare_item_priority(row: dict[str, Any]) -> tuple[int, datetime, int, str]:
    status_rank = dedupe_status_priority(str(row.get("status") or "").strip().lower())
    timestamp = _cloudflare_item_timestamp(row)
    has_remote_id = 1 if str(row.get("remote_id") or "").strip() else 0
    remote_id = str(row.get("remote_id") or "").strip()
    return (status_rank, timestamp, has_remote_id, remote_id)


def _pick_first_non_empty(rows: list[dict[str, Any]], field: str):
    for row in rows:
        value = row.get(field)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _merge_cloudflare_item_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=_cloudflare_item_priority, reverse=True)
    keeper = dict(ordered[0])

    keeper["status"] = pick_best_dedupe_status(*[str(row.get("status") or "").strip().lower() for row in ordered]) or keeper.get("status")
    keeper["published_url"] = pick_preferred_dedupe_url(*[row.get("published_url") for row in ordered]) or keeper.get("published_url")

    for score_field in ("seo_score", "geo_score", "ctr", "lighthouse_score"):
        keeper[score_field] = _pick_first_non_empty(ordered, score_field)

    keeper["index_status"] = _pick_first_non_empty(
        [row for row in ordered if str(row.get("index_status") or "").strip().lower() not in {"", "unknown"}]
        or ordered,
        "index_status",
    ) or "unknown"
    keeper["quality_status"] = _pick_first_non_empty(ordered, "quality_status")
    keeper["thumbnail_url"] = pick_preferred_dedupe_url(*[row.get("thumbnail_url") for row in ordered]) or keeper.get("thumbnail_url")
    keeper["excerpt"] = _pick_first_non_empty(ordered, "excerpt")
    keeper["canonical_category_slug"] = _pick_first_non_empty(ordered, "canonical_category_slug")
    keeper["canonical_category_name"] = _pick_first_non_empty(ordered, "canonical_category_name")
    keeper["category_slug"] = _pick_first_non_empty(ordered, "category_slug")
    keeper["category_name"] = _pick_first_non_empty(ordered, "category_name")
    keeper["published_at"] = _pick_first_non_empty(ordered, "published_at")
    keeper["updated_at"] = _pick_first_non_empty(ordered, "updated_at")
    keeper["created_at"] = _pick_first_non_empty(ordered, "created_at")

    labels: list[str] = []
    seen_labels: set[str] = set()
    for row in ordered:
        for raw in row.get("labels") or []:
            label = str(raw or "").strip()
            if not label:
                continue
            key = label.casefold()
            if key in seen_labels:
                continue
            seen_labels.add(key)
            labels.append(label)
    keeper["labels"] = labels
    return keeper


def _dedupe_cloudflare_items(rows: list[dict[str, Any]]) -> list[dict]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        channel_id = str(row.get("channel_id") or "dongriarchive").strip() or "dongriarchive"
        dedupe_id = build_dedupe_key(
            scope=f"cloudflare:{channel_id}",
            url=str(row.get("published_url") or "").strip() or None,
            title=str(row.get("title") or "").strip() or None,
            published_at=_parse_cloudflare_datetime(row.get("published_at")),
        )
        grouped.setdefault(dedupe_id, []).append(row)

    ordered_unique: list[dict] = []
    emitted_keys: set[str] = set()
    for row in rows:
        channel_id = str(row.get("channel_id") or "dongriarchive").strip() or "dongriarchive"
        dedupe_id = build_dedupe_key(
            scope=f"cloudflare:{channel_id}",
            url=str(row.get("published_url") or "").strip() or None,
            title=str(row.get("title") or "").strip() or None,
            published_at=_parse_cloudflare_datetime(row.get("published_at")),
        )
        if dedupe_id in emitted_keys:
            continue
        emitted_keys.add(dedupe_id)
        ordered_unique.append(_merge_cloudflare_item_group(grouped[dedupe_id]))
    return ordered_unique


def list_cloudflare_posts(db: Session) -> list[dict]:
    def _optional_float(value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _resolve_index_status(post_payload: dict[str, Any]) -> str:
        direct = str(post_payload.get("index_status") or post_payload.get("indexStatus") or "").strip()
        if direct:
            return direct
        index_payload = post_payload.get("index")
        if isinstance(index_payload, dict):
            nested = str(index_payload.get("status") or index_payload.get("indexStatus") or "").strip()
            if nested:
                return nested
        return "unknown"

    values = get_settings_map(db)
    leaf_categories = _canonical_cloudflare_leaf_map(list_cloudflare_categories(db))
    posts = _list_remote_posts(values)
    detail_cache: dict[str, dict[str, Any]] = {}
    remote_urls: set[str] = set()
    for post in posts:
        for raw_url in (
            post.get("publicUrl"),
            post.get("public_url"),
            post.get("url"),
        ):
            url = str(raw_url or "").strip()
            if url:
                remote_urls.add(url)

    state_by_url: dict[str, GoogleIndexUrlState] = {}
    if remote_urls:
        rows = db.execute(
            select(GoogleIndexUrlState).where(GoogleIndexUrlState.url.in_(list(remote_urls)))
        ).scalars().all()
        for row in rows:
            existing = state_by_url.get(row.url)
            row_ts = row.last_checked_at or row.updated_at or row.created_at
            existing_ts = (
                (existing.last_checked_at or existing.updated_at or existing.created_at)
                if existing is not None
                else None
            )
            if existing is None or (
                row_ts is not None and (existing_ts is None or row_ts > existing_ts)
            ):
                state_by_url[row.url] = row

    public_site_base = _public_site_base_url(values)
    provider_status = "connected" if _normalize_base_url(values.get("cloudflare_blog_api_base_url")) else "disconnected"
    site_settings = _fetch_remote_site_settings(values)
    channel_name = str(site_settings.get("siteTitle") or "Dongri Archive")
    items: list[dict] = []
    for post in posts:
        slug = str(post.get("slug") or "").strip()
        remote_id = str(post.get("id") or slug).strip()
        category = post.get("category") if isinstance(post.get("category"), dict) else {}
        quality_payload = post.get("quality") if isinstance(post.get("quality"), dict) else {}
        analytics_payload = post.get("analytics") if isinstance(post.get("analytics"), dict) else {}
        index_payload = post.get("index") if isinstance(post.get("index"), dict) else {}
        remote_public_url = str(post.get("publicUrl") or post.get("public_url") or post.get("url") or "").strip()
        published_url = remote_public_url or (f"{public_site_base}/ko/post/{quote(slug)}" if public_site_base and slug else None)
        state = state_by_url.get(str(published_url or "").strip()) or state_by_url.get(remote_public_url)
        tags = post.get("tags") if isinstance(post.get("tags"), list) else []
        status_value = str(post.get("status") or "published").strip() or "published"
        created_at = str(post.get("createdAt") or post.get("created_at") or "").strip()
        updated_at = str(post.get("updatedAt") or post.get("updated_at") or "").strip()
        published_at = str(post.get("publishedAt") or post.get("published_at") or "").strip()
        if not published_at and status_value.lower() in {"published", "live"}:
            published_at = updated_at or created_at
        seo_score = _optional_float(
            post.get("seo_score")
            or post.get("seoScore")
            or quality_payload.get("seo_score")
            or quality_payload.get("seoScore")
        )
        geo_score = _optional_float(
            post.get("geo_score")
            or post.get("geoScore")
            or quality_payload.get("geo_score")
            or quality_payload.get("geoScore")
        )
        ctr = _optional_float(
            post.get("ctr")
            or post.get("clickThroughRate")
            or analytics_payload.get("ctr")
            or analytics_payload.get("clickThroughRate")
        )
        lighthouse_score = _optional_float(
            post.get("lighthouse_score")
            or post.get("lighthouseScore")
            or analytics_payload.get("lighthouse_score")
            or analytics_payload.get("lighthouseScore")
            or quality_payload.get("lighthouse_score")
            or quality_payload.get("lighthouseScore")
        )
        if (seo_score is None or geo_score is None or ctr is None or lighthouse_score is None) and remote_id:
            detail_post = detail_cache.get(remote_id)
            if detail_post is None:
                try:
                    detail_post = _fetch_integration_post_detail(db, remote_id)
                except Exception:  # noqa: BLE001
                    detail_post = {}
                detail_cache[remote_id] = detail_post
            if detail_post:
                detail_quality = detail_post.get("quality") if isinstance(detail_post.get("quality"), dict) else {}
                detail_analytics = detail_post.get("analytics") if isinstance(detail_post.get("analytics"), dict) else {}
                seo_score = seo_score or _optional_float(
                    detail_post.get("seo_score")
                    or detail_post.get("seoScore")
                    or detail_quality.get("seo_score")
                    or detail_quality.get("seoScore")
                )
                geo_score = geo_score or _optional_float(
                    detail_post.get("geo_score")
                    or detail_post.get("geoScore")
                    or detail_quality.get("geo_score")
                    or detail_quality.get("geoScore")
                )
                ctr = ctr or _optional_float(
                    detail_post.get("ctr")
                    or detail_post.get("clickThroughRate")
                    or detail_analytics.get("ctr")
                    or detail_analytics.get("clickThroughRate")
                )
                lighthouse_score = lighthouse_score or _optional_float(
                    detail_post.get("lighthouse_score")
                    or detail_post.get("lighthouseScore")
                    or detail_analytics.get("lighthouse_score")
                    or detail_analytics.get("lighthouseScore")
                    or detail_quality.get("lighthouse_score")
                    or detail_quality.get("lighthouseScore")
                )
                if seo_score is None or geo_score is None or ctr is None:
                    detail_title = str(detail_post.get("title") or post.get("title") or slug).strip()
                    detail_excerpt = str(detail_post.get("excerpt") or post.get("excerpt") or "").strip()
                    detail_content = str(detail_post.get("content") or detail_post.get("contentMarkdown") or "").strip()
                    if detail_title and detail_content:
                        try:
                            from app.services.content_ops_service import compute_seo_geo_scores

                            fallback_scores = compute_seo_geo_scores(
                                title=detail_title,
                                html_body=detail_content,
                                excerpt=detail_excerpt,
                                faq_section=[],
                            )
                            seo_score = seo_score or _optional_float(fallback_scores.get("seo_score"))
                            geo_score = geo_score or _optional_float(fallback_scores.get("geo_score"))
                            ctr = ctr or _optional_float(fallback_scores.get("ctr_score"))
                        except Exception:  # noqa: BLE001
                            pass
        quality_status = str(
            post.get("quality_status")
            or post.get("qualityStatus")
            or quality_payload.get("status")
            or "",
        ).strip() or None
        canonical_category = _resolve_cloudflare_canonical_category(
            title=str(post.get("title") or slug),
            excerpt=str(post.get("excerpt") or ""),
            raw_category_slug=str(category.get("slug") or "").strip(),
            raw_category_name=str(category.get("name") or "").strip(),
            leaf_categories=leaf_categories,
        )
        index_status = str(
            post.get("index_status")
            or post.get("indexStatus")
            or index_payload.get("status")
            or _resolve_index_status(post)
        ).strip() or "unknown"
        if state and str(state.index_status or "").strip():
            index_status = str(state.index_status).strip()
        items.append(
            {
                "provider": "cloudflare",
                "channel_id": str(category.get("id") or "dongriarchive"),
                "channel_name": channel_name,
                "category_name": str(category.get("name") or "").strip(),
                "category_slug": str(category.get("slug") or "").strip(),
                "canonical_category_name": str(canonical_category.get("name") or "").strip() or None,
                "canonical_category_slug": str(canonical_category.get("slug") or "").strip() or None,
                "remote_id": remote_id,
                "provider_status": provider_status,
                "title": str(post.get("title") or slug),
                "excerpt": post.get("excerpt"),
                "published_url": published_url,
                "thumbnail_url": post.get("coverImage"),
                "labels": [
                    str(tag.get("name") or "").strip()
                    for tag in tags
                    if isinstance(tag, dict) and str(tag.get("name") or "").strip()
                ],
                "seo_score": seo_score,
                "geo_score": geo_score,
                "ctr": ctr,
                "lighthouse_score": lighthouse_score,
                "index_status": index_status,
                "index_coverage_state": state.index_coverage_state if state else None,
                "index_last_checked_at": state.last_checked_at.isoformat() if state and state.last_checked_at else None,
                "next_eligible_at": state.next_eligible_at.isoformat() if state and state.next_eligible_at else None,
                "last_error": state.last_error if state else None,
                "quality_status": quality_status,
                "published_at": published_at,
                "created_at": created_at,
                "updated_at": updated_at,
                "status": status_value,
            }
        )
    return _dedupe_cloudflare_items(items)


def get_cloudflare_overview(db: Session) -> dict:
    values = get_settings_map(db)
    categories = [item for item in list_cloudflare_categories(db) if bool(item.get("isLeaf"))]
    posts = list_cloudflare_posts(db)
    site_settings = _fetch_remote_site_settings(values)
    base_url = _public_site_base_url(values) or None
    provider_status = "connected" if _normalize_base_url(values.get("cloudflare_blog_api_base_url")) else "disconnected"
    prompt_bundle = get_cloudflare_prompt_bundle(db)
    return {
        "provider": "cloudflare",
        "channel_id": "dongriarchive",
        "channel_name": str(site_settings.get("siteTitle") or "Dongri Archive"),
        "provider_status": provider_status,
        "posts_count": len(posts),
        "categories_count": len(categories),
        "prompts_count": len(prompt_bundle["templates"]),
        "runs_count": 0,
        "site_title": str(site_settings.get("siteTitle") or "Dongri Archive"),
        "base_url": base_url,
        "error": None if provider_status == "connected" else "Cloudflare integration base URL is not configured.",
    }


def get_cloudflare_prompt_bundle(db: Session) -> dict:
    values = get_settings_map(db)
    categories = [item for item in list_cloudflare_categories(db) if bool(item.get("isLeaf"))]
    templates: list[dict] = []
    for category in categories:
        for stage in DEFAULT_PROMPT_STAGES:
            keys = _prompt_storage_keys(str(category["id"]), stage)
            content = values.get(keys["content"]) or _default_prompt_for_stage(category, stage)
            display_name = (values.get(keys["name"]) or "").strip() or f"{category['name']} | {_cloudflare_stage_display_label(stage)}"
            objective = (values.get(keys["objective"]) or "").strip() or _cloudflare_stage_default_objective(
                stage,
                category_name=str(category["name"]),
            )
            is_enabled = str(values.get(keys["is_enabled"]) or "true").strip().lower() not in {"false", "0", "off", "no"}
            provider_model = (values.get(keys["provider_model"]) or "").strip() or None
            version = int(str(values.get(keys["version"]) or "1").strip() or "1")
            created_at = values.get(keys["created_at"]) or _utc_now_iso()
            updated_at = values.get(keys["updated_at"]) or created_at
            templates.append(
                {
                    "id": f"{category['slug']}:{stage}",
                    "categoryId": category["id"],
                    "categorySlug": category["slug"],
                    "categoryName": category["name"],
                    "stage": stage,
                    "name": display_name,
                    "objective": objective,
                    "isEnabled": is_enabled,
                    "currentVersion": version,
                    "content": content,
                    "providerModel": provider_model,
                    "createdAt": created_at,
                    "updatedAt": updated_at,
                }
            )
    return {
        "categories": categories,
        "templates": sorted(templates, key=lambda item: (item["categorySlug"], item["stage"])),
        "stages": list(DEFAULT_PROMPT_STAGES),
    }


def save_cloudflare_prompt(
    db: Session,
    *,
    category_key: str,
    stage: str,
    content: str,
    name: str | None = None,
    objective: str | None = None,
    is_enabled: bool | None = None,
    provider_model: str | None = None,
) -> dict:
    normalized_category_key = category_key.strip()
    normalized_stage = stage.strip().lower()
    if normalized_stage not in DEFAULT_PROMPT_STAGES:
        raise ValueError(f"Unknown Cloudflare prompt stage: {stage}")

    bundle = get_cloudflare_prompt_bundle(db)
    category = next(
        (
            item
            for item in bundle["categories"]
            if item["slug"] == normalized_category_key or item["id"] == normalized_category_key
        ),
        None,
    )
    if category is None:
        raise ValueError(f"Unknown Cloudflare category: {category_key}")

    keys = _prompt_storage_keys(str(category["id"]), normalized_stage)
    values = get_settings_map(db)
    current_version = int(str(values.get(keys["version"]) or "0").strip() or "0")
    created_at = values.get(keys["created_at"]) or _utc_now_iso()
    updated_at = _utc_now_iso()
    upsert_settings(
        db,
        {
            keys["content"]: content,
            keys["name"]: (name or "").strip(),
            keys["objective"]: (objective or "").strip(),
            keys["is_enabled"]: "true" if is_enabled is not False else "false",
            keys["provider_model"]: (provider_model or "").strip(),
            keys["version"]: str(current_version + 1),
            keys["created_at"]: created_at,
            keys["updated_at"]: updated_at,
        },
    )
    return {
        "id": f"{category['slug']}:{normalized_stage}",
        "categoryId": category["id"],
        "categorySlug": category["slug"],
        "categoryName": category["name"],
        "stage": normalized_stage,
        "name": (name or "").strip() or f"{category['name']} | {_cloudflare_stage_display_label(normalized_stage)}",
        "objective": (objective or "").strip() or _cloudflare_stage_default_objective(
            normalized_stage,
            category_name=str(category["name"]),
        ),
        "isEnabled": is_enabled is not False,
        "currentVersion": current_version + 1,
        "content": content,
        "providerModel": (provider_model or "").strip() or None,
        "createdAt": created_at,
        "updatedAt": updated_at,
    }


def sync_cloudflare_prompts_from_files(db: Session, *, execute: bool = True) -> dict:
    categories = list_cloudflare_categories(db)
    categories_by_slug = {str(item.get("slug") or "").strip(): item for item in categories if str(item.get("slug") or "").strip()}
    leaf_slugs = {slug for slug, item in categories_by_slug.items() if bool(item.get("isLeaf"))}
    bundle = get_cloudflare_prompt_bundle(db)
    current_templates = {
        (str(item.get("categorySlug") or "").strip(), str(item.get("stage") or "").strip()): str(item.get("content") or "")
        for item in (bundle.get("templates") or [])
        if isinstance(item, dict)
    }

    updated = 0
    skipped = 0
    failures: list[dict[str, str]] = []
    file_results: list[dict[str, Any]] = []
    root = _prompt_root()

    for file_name, target_slugs in CLOUDFLARE_PROMPT_FILE_MAP.items():
        file_path = root / file_name
        if not file_path.exists():
            failures.append({"file": file_name, "reason": "file_not_found"})
            continue
        content = file_path.read_text(encoding="utf-8")
        blocks = _extract_code_blocks(content)
        if len(blocks) < 3:
            failures.append({"file": file_name, "reason": "invalid_prompt_format"})
            continue

        stage_map = {
            "topic_discovery": blocks[0].strip(),
            "article_generation": blocks[1].strip(),
            "image_prompt_generation": blocks[2].strip(),
        }
        file_updated = 0
        file_skipped = 0
        file_mode = "mapped"

        if not target_slugs:
            file_mode = "loaded_unmapped"
            file_results.append(
                {
                    "file": file_name,
                    "updated": 0,
                    "skipped": 0,
                    "targets": [],
                    "mode": file_mode,
                }
            )
            continue

        for slug in target_slugs:
            if slug not in categories_by_slug:
                failures.append({"file": file_name, "reason": f"missing_category:{slug}"})
                continue
            if slug not in leaf_slugs:
                file_skipped += len(stage_map)
                skipped += len(stage_map)
                continue
            for stage, stage_content in stage_map.items():
                current = current_templates.get((slug, stage), "")
                if current.strip() == stage_content.strip():
                    file_skipped += 1
                    skipped += 1
                    continue
                if execute:
                    save_cloudflare_prompt(db, category_key=slug, stage=stage, content=stage_content)
                    current_templates[(slug, stage)] = stage_content
                file_updated += 1
                updated += 1

        file_results.append(
            {
                "file": file_name,
                "updated": file_updated,
                "skipped": file_skipped,
                "targets": [slug for slug in target_slugs],
                "mode": file_mode,
            }
        )

    status = "ok" if not failures else "partial"
    return {
        "status": status,
        "execute": execute,
        "updated": updated,
        "skipped": skipped,
        "files": file_results,
        "failures": failures,
    }


def _is_enabled(value: str | bool | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _cloudflare_inline_images_enabled(values: dict[str, str]) -> bool:
    return _is_enabled(values.get("cloudflare_inline_images_enabled"), default=False)


def _cloudflare_require_cover_image(values: dict[str, str]) -> bool:
    return _is_enabled(values.get("cloudflare_require_cover_image"), default=True)


def _select_weighted_daily_categories(
    *,
    values: dict[str, str],
    category_slugs: list[str],
    today: str,
    quota: int,
) -> tuple[dict[str, int], dict[str, int]]:
    keys = [slug for slug in category_slugs if slug]
    counts = _load_daily_counter(values.get("cloudflare_daily_category_counts"), today=today, keys=keys)
    return _select_weighted_daily_categories_from_counts(
        category_slugs=keys,
        counts=counts,
        quota=quota,
    )


def _select_weighted_daily_categories_from_counts(
    *,
    category_slugs: list[str],
    counts: dict[str, int],
    quota: int,
) -> tuple[dict[str, int], dict[str, int]]:
    keys = [slug for slug in category_slugs if slug]
    if quota <= 0 or not keys:
        return {}, counts

    weight_map = {slug: max(README_V3_LEAF_WEIGHTS.get(slug, 1), 1) for slug in keys}
    plan: dict[str, int] = {slug: 0 for slug in keys}
    total_weight = sum(weight_map.values()) or len(keys)
    next_counts = {slug: max(_safe_int(counts.get(slug), 0), 0) for slug in keys}

    for _ in range(quota):
        total_so_far = sum(next_counts.values())
        ranked = sorted(
            keys,
            key=lambda slug: (
                ((weight_map[slug] / total_weight) * (total_so_far + 1)) - next_counts.get(slug, 0),
                weight_map[slug],
                -next_counts.get(slug, 0),
            ),
            reverse=True,
        )
        selected = ranked[0]
        plan[selected] = plan.get(selected, 0) + 1
        next_counts[selected] = next_counts.get(selected, 0) + 1
    return {slug: count for slug, count in plan.items() if count > 0}, next_counts


def _apply_generation_counts_to_daily_counter(
    *,
    counts: dict[str, int],
    generation: dict[str, Any],
) -> dict[str, int]:
    next_counts = {key: max(_safe_int(value, 0), 0) for key, value in counts.items()}
    for category_result in generation.get("categories") or []:
        if not isinstance(category_result, dict):
            continue
        slug = str(category_result.get("category_slug") or "").strip()
        created = max(_safe_int(category_result.get("created"), 0), 0)
        if not slug or created <= 0:
            continue
        next_counts[slug] = next_counts.get(slug, 0) + created
    return next_counts


def run_cloudflare_daily_schedule(db: Session, *, now: datetime | None = None) -> dict:
    values = get_settings_map(db)
    if not _is_enabled(values.get("cloudflare_daily_publish_enabled"), default=True):
        return {"status": "disabled", "reason": "cloudflare_daily_publish_disabled"}

    timezone_name = (values.get("cloudflare_daily_publish_timezone") or DEFAULT_CATEGORY_TIMEZONE).strip() or DEFAULT_CATEGORY_TIMEZONE
    local_now = (now or datetime.now(ZoneInfo(timezone_name))).astimezone(ZoneInfo(timezone_name))
    expected_time = (values.get("cloudflare_daily_publish_time") or DEFAULT_CATEGORY_SCHEDULE_TIME).strip() or DEFAULT_CATEGORY_SCHEDULE_TIME
    interval_hours = max(_safe_int(values.get("cloudflare_daily_publish_interval_hours"), 2), 1)
    today = local_now.date().isoformat()
    last_run_slot = (values.get("cloudflare_daily_last_run_slot") or "").strip()
    last_attempted_slot = (values.get("cloudflare_daily_last_attempted_slot") or "").strip()
    due_slot_markers = _build_due_slot_markers(
        local_now,
        start_time_raw=expected_time,
        fallback_time=DEFAULT_CATEGORY_SCHEDULE_TIME,
        interval_hours=interval_hours,
        last_run_slot=last_run_slot,
        last_attempted_slot=last_attempted_slot,
        timezone_name=timezone_name,
    )
    if not due_slot_markers:
        return {
            "status": "idle",
            "reason": "no_due_slots",
            "start_time": expected_time,
            "interval_hours": interval_hours,
            "now": local_now.strftime("%H:%M"),
            "timezone": timezone_name,
        }

    prompt_sync = sync_cloudflare_prompts_from_files(db, execute=True)

    categories = [item for item in list_cloudflare_categories(db) if bool(item.get("isLeaf"))]
    available_slugs = [str(item.get("slug") or "").strip() for item in categories if str(item.get("slug") or "").strip()]
    weekday_quota = max(_safe_int(values.get("cloudflare_daily_publish_weekday_quota"), 3), 0)
    sunday_quota = max(_safe_int(values.get("cloudflare_daily_publish_sunday_quota"), 2), 0)
    quota = sunday_quota if local_now.weekday() == 6 else weekday_quota
    current_counts = _load_daily_counter(values.get("cloudflare_daily_category_counts"), today=today, keys=available_slugs)
    total_today = sum(max(_safe_int(count, 0), 0) for count in current_counts.values())
    if quota > 0 and total_today >= quota:
        return {
            "status": "idle",
            "reason": "daily_quota_reached",
            "slot_marker": due_slot_markers[-1],
            "date": today,
            "daily_quota": quota,
            "daily_created": total_today,
        }

    processed_slots: list[str] = []
    slot_results: list[dict[str, Any]] = []
    last_successful_slot = last_run_slot or None

    for slot_marker in due_slot_markers:
        total_today = sum(max(_safe_int(count, 0), 0) for count in current_counts.values())
        if quota > 0 and total_today >= quota:
            return {
                "status": "partial" if processed_slots else "idle",
                "reason": "daily_quota_reached",
                "date": today,
                "slot_marker": slot_marker,
                "timezone": timezone_name,
                "start_time": expected_time,
                "interval_hours": interval_hours,
                "daily_quota": quota,
                "daily_created": total_today,
                "processed_slots": processed_slots,
                "pending_slots": [item for item in due_slot_markers if item not in processed_slots],
                "last_successful_slot": last_successful_slot,
                "last_attempted_slot": last_attempted_slot or None,
                "prompt_sync": prompt_sync,
                "slot_results": slot_results,
            }

        upsert_settings(db, {"cloudflare_daily_last_attempted_slot": slot_marker})
        last_attempted_slot = slot_marker

        slot_attempted_categories: list[str] = []
        slot_failure_breakdown: dict[str, int] = {}
        slot_attempts: list[dict[str, Any]] = []
        slot_completed = False
        max_category_attempts = max(1, min(CLOUDFLARE_DAILY_MAX_CATEGORY_ATTEMPTS, len(available_slugs)))

        for _attempt in range(max_category_attempts):
            remaining_category_slugs = [slug for slug in available_slugs if slug not in slot_attempted_categories]
            category_plan, _ = _select_weighted_daily_categories_from_counts(
                category_slugs=remaining_category_slugs,
                counts=current_counts,
                quota=1,
            )
            if not category_plan:
                slot_failure_breakdown["empty_category_plan"] = slot_failure_breakdown.get("empty_category_plan", 0) + 1
                break

            planned_slug = next(iter(category_plan.keys()))
            if planned_slug:
                slot_attempted_categories.append(planned_slug)

            generation = generate_cloudflare_posts(
                db,
                per_category=1,
                category_plan=category_plan,
                status="published",
            )
            created_count = max(_safe_int(generation.get("created_count"), 0), 0)
            failure_reason = str(generation.get("reason") or generation.get("status") or "").strip()
            if not failure_reason:
                failure_reason = "generation_created_zero" if created_count <= 0 else "ok"

            attempt_entry = {
                "slot_marker": slot_marker,
                "category_plan": category_plan,
                "generation": generation,
                "created_count": created_count,
                "failure_reason": failure_reason,
            }
            slot_attempts.append(attempt_entry)

            if created_count <= 0:
                slot_failure_breakdown[failure_reason] = slot_failure_breakdown.get(failure_reason, 0) + 1
                continue

            current_counts = _apply_generation_counts_to_daily_counter(
                counts=current_counts,
                generation=generation,
            )
            upsert_settings(
                db,
                {
                    "cloudflare_daily_last_run_on": today,
                    "cloudflare_daily_last_run_slot": slot_marker,
                    "cloudflare_daily_last_attempted_slot": slot_marker,
                    "cloudflare_daily_category_counts": _serialize_daily_counter(today=today, counts=current_counts),
                },
            )
            last_successful_slot = slot_marker
            processed_slots.append(slot_marker)
            slot_results.append(
                {
                    "status": "ok",
                    "slot_marker": slot_marker,
                    "attempted_categories": list(slot_attempted_categories),
                    "failure_breakdown": dict(slot_failure_breakdown),
                    "attempts": slot_attempts,
                    "created_count": created_count,
                }
            )
            slot_completed = True
            break

        if slot_completed:
            continue

        failure_reason = "generation_created_zero"
        if not slot_attempted_categories and "empty_category_plan" in slot_failure_breakdown:
            failure_reason = "empty_category_plan"

        slot_results.append(
            {
                "status": "failed",
                "slot_marker": slot_marker,
                "attempted_categories": list(slot_attempted_categories),
                "failure_breakdown": dict(slot_failure_breakdown),
                "attempts": slot_attempts,
                "created_count": 0,
            }
        )
        return {
            "status": "partial" if processed_slots else "failed",
            "reason": failure_reason,
            "date": today,
            "slot_marker": slot_marker,
            "timezone": timezone_name,
            "start_time": expected_time,
            "interval_hours": interval_hours,
            "daily_quota": quota,
            "daily_created": total_today,
            "processed_slots": processed_slots,
            "pending_slots": [item for item in due_slot_markers if item not in processed_slots],
            "last_successful_slot": last_successful_slot,
            "last_attempted_slot": last_attempted_slot or None,
            "attempted_categories": list(slot_attempted_categories),
            "failure_breakdown": dict(slot_failure_breakdown),
            "prompt_sync": prompt_sync,
            "slot_results": slot_results,
        }

    return {
        "status": "ok",
        "date": today,
        "slot_marker": processed_slots[-1] if processed_slots else due_slot_markers[-1],
        "timezone": timezone_name,
        "start_time": expected_time,
        "interval_hours": interval_hours,
        "daily_quota": quota,
        "daily_created": sum(max(_safe_int(count, 0), 0) for count in current_counts.values()),
        "processed_slots": processed_slots,
        "pending_slots": [item for item in due_slot_markers if item not in processed_slots],
        "last_successful_slot": last_successful_slot,
        "last_attempted_slot": last_attempted_slot or None,
        "prompt_sync": prompt_sync,
        "slot_results": slot_results,
    }


def _normalize_text(value: str | None) -> str:
    normalized = slugify(value or "", separator=" ", lowercase=True, allow_unicode=True)
    return " ".join(normalized.split()).strip()


def _is_similar(left: str, right: str) -> bool:
    left_norm = _normalize_text(left)
    right_norm = _normalize_text(right)
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return True
    left_compact = left_norm.replace(" ", "")
    right_compact = right_norm.replace(" ", "")
    if len(left_compact) >= 14 and (left_compact in right_compact or right_compact in left_compact):
        return True
    return SequenceMatcher(None, left_norm, right_norm).ratio() >= 0.9


def _topic_cluster_tokens(value: str | None) -> set[str]:
    normalized = _normalize_text(value)
    if not normalized:
        return set()
    tokens: set[str] = set()
    for token in normalized.split():
        candidate = token.strip().lower()
        if len(candidate) <= 1 or candidate in TOPIC_CLUSTER_STOPWORDS:
            continue
        tokens.add(candidate)
    return tokens


def _is_topic_duplicate_like(left: str, right: str) -> bool:
    if _is_similar(left, right):
        return True
    left_tokens = _topic_cluster_tokens(left)
    right_tokens = _topic_cluster_tokens(right)
    if len(left_tokens) < 2 or len(right_tokens) < 2:
        return False
    overlap = len(left_tokens.intersection(right_tokens))
    if overlap < 2:
        return False
    min_size = min(len(left_tokens), len(right_tokens))
    return (overlap / max(min_size, 1)) >= 0.75


def _topic_matches_any(keyword: str, candidates: list[str]) -> bool:
    return any(_is_topic_duplicate_like(keyword, candidate) for candidate in candidates)


def _render_prompt_template(
    template: str,
    *,
    current_date: str,
    keyword: str = "",
    topic_count: int = 2,
) -> str:
    rendered = str(template or "")
    replacements = {
        "{current_date}": current_date,
        "{keyword}": keyword,
        "{topic_count}": str(topic_count),
    }
    for needle, value in replacements.items():
        rendered = rendered.replace(needle, value)
    return rendered.strip()


def _topic_output_contract(topic_count: int) -> str:
    return (
        "\n\n[Output contract]\n"
        "Return only one JSON object (no markdown fence) using this schema:\n"
        '{"topics":[{"keyword":"string","reason":"string","trend_score":0}]}\n'
        f"- Return {topic_count} topics if possible.\n"
        "- All topics must be unique and materially different.\n"
        "- Avoid recurring intent patterns from prior posts; change entity, place, and time context.\n"
        "- Reject light rephrases of existing topics; novelty is required.\n"
        "- trend_score must be 0~100.\n"
    )


def _build_runtime_topic_exclusion_prompt(*, attempted_keywords: list[str], limit: int = 24) -> str:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in attempted_keywords:
        keyword = str(raw or "").strip()
        lowered = keyword.lower()
        if not keyword or lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(keyword)
        if len(normalized) >= max(limit, 1):
            break
    if not normalized:
        return ""
    bullet_list = "\n".join(f"- {value}" for value in normalized)
    return (
        "\n\n[Runtime duplicate exclusions]\n"
        "Do not return topics that duplicate or lightly rephrase these already-attempted topics:\n"
        f"{bullet_list}\n"
        "- Change core nouns and scenario, not only wording."
    )


def _build_runtime_blocked_topic_prompt(*, blocked_keywords: list[str], limit: int = 24) -> str:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in blocked_keywords:
        keyword = str(raw or "").strip()
        lowered = keyword.lower()
        if not keyword or lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(keyword)
        if len(normalized) >= max(limit, 1):
            break
    if not normalized:
        return ""
    bullet_list = "\n".join(f"- {value}" for value in normalized)
    return (
        "\n\n[Blocked by duplicate guard]\n"
        "These are blocked by prior duplicate/category filtering in this run.\n"
        "Return different topic clusters and different angles:\n"
        f"{bullet_list}\n"
        "- New cluster means different core entities, location, and user task."
    )


def _build_history_exclusion_prompt_from_entries(entries: Sequence[Any], *, limit: int = 36) -> str:
    values: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        keyword = str(getattr(entry, "keyword", "") or "").strip()
        if not keyword:
            continue
        lowered = keyword.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        values.append(keyword)
        if len(values) >= max(limit, 1):
            break
    if not values:
        return ""
    bullet_list = "\n".join(f"- {value}" for value in values)
    return (
        "\n\nHard exclusion list from persisted topic history.\n"
        "Do not rephrase these topics. If cluster overlaps, enforce a clearly different angle and user task.\n"
        f"{bullet_list}"
    )


def _article_output_contract() -> str:
    return (
        "\n\n[Output contract]\n"
        "Return only one JSON object (no markdown fence) using exact keys:\n"
        "{\n"
        '  "title": "string",\n'
        '  "meta_description": "string",\n'
        '  "labels": ["string", "string"],\n'
        '  "slug": "string",\n'
        '  "excerpt": "string",\n'
        '  "html_article": "string",\n'
        '  "faq_section": [{"question":"string","answer":"string"}],\n'
        '  "image_collage_prompt": "string",\n'
        '  "inline_collage_prompt": "string"\n'
        "}\n"
        "- html_article must be valid Markdown content for a published article.\n"
        "- Keep structure SEO-friendly, readable, and blog-like rather than report-like.\n"
        "- Keep html_article body roughly in the 3000 to 4000 Korean character range when writing Korean Cloudflare posts.\n"
        "- Do not include inline markdown/HTML images in html_article body.\n"
        "- The system inserts one inline collage image separately in the middle of the article body.\n"
        "- meta_description and excerpt must not appear as visible duplicated summary lines inside html_article.\n"
        "- faq_section is an appendix block and should appear only once at the very end conceptually.\n"
        "- image_collage_prompt must be one final English prompt for one hero 3x3 collage with exactly 9 distinct panels.\n"
        "- The center panel must be visually dominant and the panel borders must remain visible.\n"
        "- inline_collage_prompt must be one final English prompt for one supporting 3x2 collage with exactly 6 distinct panels.\n"
    )


def _append_no_inline_image_rule(prompt: str) -> str:
    return (
        f"{prompt}\n\n"
        "[Inline image policy]\n"
        "- Do not insert markdown images or HTML image tags in body content.\n"
        "- Never include ![...](...), <img>, <figure>, or collage marker text in article body.\n"
        "- If the schema includes inline_collage_prompt, use that field for one mid-article supporting collage prompt.\n"
        "- Keep raw image markup out of html_article because the system injects the inline visual later.\n"
    )


def _append_cloudflare_seo_trust_guard(prompt: str, *, category_slug: str, current_date: str) -> str:
    guard_lines = [
        "[SEO trust + source integrity guard]",
        f"- Include one explicit timestamp line near the top: 기준 시각: {current_date} (Asia/Seoul).",
        "- Include one short section that clearly separates 확인된 사실 and 미확인 또는 변동 가능 정보.",
        "- Include one source/verification section with 2-5 concrete references or official channels.",
        "- If no verifiable URL exists, explicitly say that no confirmed official URL was available at writing time.",
        "- Do not present rumors or repost claims as confirmed facts.",
        "- Avoid exaggerated or absolute claims unless verifiable evidence is provided.",
        "- Follow a fixed SEO/GEO/CTR-friendly article flow: hook, why now, concept, how-to, use cases, comparison, pros and cons, conclusion, FAQ appendix.",
        "- In the first 220 characters, state target reader and what they can decide after reading.",
        "- Avoid vague prose. Prefer concrete entities, dates, and actionable checkpoints.",
    ]

    if category_slug in {"주식-흐름", "크립토-흐름", "동그리의-생각"}:
        guard_lines.append("- For forward-looking analysis, label scenarios as possibilities, not certainties.")
    if category_slug in {"문화와공간", "축제와현장", "여행과기록"}:
        guard_lines.append("- For schedule/price/entry details, use recheck wording when uncertain.")
    if category_slug == "미스터리-스토리":
        guard_lines.append("- Separate documented records, claims, and retellings in different blocks.")

    if _is_mysteria_story_category(category_id="", category_slug=category_slug):
        guard_lines.extend(
            [
                "- For mysteria-story, enforce source-pair workflow from Blogger origin posts (2 items per run).",
                "- Keep Korean localization natural and culturally adapted, not literal translation tone.",
            ]
        )

    return f"{prompt}\n\n" + "\n".join(guard_lines) + "\n"


def _append_hero_only_visual_rule(prompt: str) -> str:
    return (
        f"{prompt}\n\n"
        "[Hero image policy]\n"
        "- Generate one cover-image prompt only.\n"
        "- Use one composite 3x3 collage with exactly 9 distinct panels.\n"
        "- Keep visible white gutters and make the center panel visually dominant.\n"
        "- Do not request inline, supplementary, infographic, or chart body images.\n"
    )


def _category_hard_gate(category_slug: str, category_name: str) -> str:
    lines = [
        "\n\n[Hard category gate]",
        f"- Every output must fit category '{category_name}' ({category_slug}).",
        "- If the output does not clearly fit this category, regenerate internally before returning.",
    ]
    if category_slug == "삶을-유용하게":
        lines.append("- This category is for welfare, benefits, event, and practical living information. Do not drift into mindset essays or quote collections.")
    if category_slug == "삶의-기름칠":
        lines.append("- This category is for mindset, routine, reflection, and attitude. Do not drift into welfare, subsidy, application, or event bulletin writing.")
    if category_slug == "개발과-프로그래밍":
        lines.append("- This category must stay in AI coding, LLM agents, automation workflows, tool comparison, or practical setup. Do not drift into generic IT news.")
    if category_slug != "미스터리-스토리":
        lines.append("- Do not use mystery, murder, unsolved-case, haunting, or conspiracy angles.")
    if category_slug != "축제와현장":
        lines.append("- Do not force festival operation logistics unless the category is festival-focused.")
    return "\n".join(lines) + "\n"


def _extract_integration_asset(payload: object) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    if any(key in payload for key in ("url", "publicUrl", "public_url", "objectKey", "object_key", "path")):
        return payload
    if isinstance(payload.get("asset"), dict):
        return payload.get("asset")
    data = payload.get("data")
    if isinstance(data, dict):
        if isinstance(data.get("asset"), dict):
            return data.get("asset")
        return data
    return None


def _integration_request(
    db: Session,
    *,
    method: str,
    path: str,
    params: dict[str, str] | None = None,
    json_payload: dict | None = None,
    form_data: dict[str, str] | None = None,
    files: dict[str, tuple[str, bytes, str]] | None = None,
    timeout: float = 60.0,
) -> httpx.Response:
    values = get_settings_map(db)
    base_url = _normalize_base_url(values.get("cloudflare_blog_api_base_url"))
    token = str(values.get("cloudflare_blog_m2m_token") or "").strip()
    if not base_url:
        raise ValueError("Cloudflare API base URL is not configured.")
    if not token:
        raise ValueError("Cloudflare integration token is not configured.")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if files is None:
        headers["Content-Type"] = "application/json"

    return httpx.request(
        method=method,
        url=f"{base_url}{path}",
        headers=headers,
        params=params,
        json=json_payload,
        data=form_data,
        files=files,
        timeout=timeout,
    )


def _integration_data_or_raise(response: httpx.Response) -> Any:
    payload: Any = {}
    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if not response.is_success:
        detail = response.text
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                detail = str(error.get("message") or error.get("code") or detail)
            else:
                detail = str(payload.get("message") or payload.get("detail") or detail)
        raise ValueError(f"Cloudflare API request failed ({response.status_code}): {detail}")

    if isinstance(payload, dict) and payload.get("success") is False:
        error = payload.get("error")
        if isinstance(error, dict):
            detail = str(error.get("message") or error.get("code") or payload)
        else:
            detail = str(payload)
        raise ValueError(f"Cloudflare API responded with failure: {detail}")

    if isinstance(payload, dict) and "data" in payload:
        return payload.get("data")
    return payload


def _list_integration_posts(db: Session) -> list[dict[str, Any]]:
    response = _integration_request(db, method="GET", path="/api/integrations/posts", timeout=45.0)
    data = _integration_data_or_raise(response)
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _upload_integration_asset(
    db: Session,
    *,
    post_slug: str,
    alt_text: str,
    filename: str,
    image_bytes: bytes,
) -> str:
    normalized_filename = str(Path(filename).with_suffix(".webp"))
    normalized_image_bytes = _normalize_integration_asset_image(image_bytes)
    response = _integration_request(
        db,
        method="POST",
        path="/api/integrations/assets",
        form_data={
            "postSlug": post_slug,
            "altText": alt_text,
        },
        files={"file": (normalized_filename, normalized_image_bytes, "image/webp")},
        timeout=120.0,
    )
    data = _integration_data_or_raise(response)
    asset = _extract_integration_asset(data)
    if not isinstance(asset, dict):
        raise ValueError("Cloudflare asset upload returned no asset payload.")
    public_url = str(
        asset.get("publicUrl")
        or asset.get("public_url")
        or asset.get("url")
        or ""
    ).strip()
    if not public_url:
        base_url = str(asset.get("publicBaseUrl") or asset.get("public_base_url") or "").strip().rstrip("/")
        path = str(asset.get("path") or "").strip().lstrip("/")
        if base_url and path:
            public_url = f"{base_url}/{path}"
    if not public_url:
        raise ValueError("Cloudflare asset upload returned no public URL.")
    return public_url


def _normalize_integration_asset_image(image_bytes: bytes) -> bytes:
    if not image_bytes:
        raise ValueError("Integration asset image is empty.")
    try:
        with Image.open(io.BytesIO(image_bytes)) as loaded:
            output = io.BytesIO()
            converted = loaded if loaded.mode in {"RGB", "RGBA"} else loaded.convert("RGB")
            converted.save(output, format="WEBP", quality=88, optimize=True, method=6)
            return output.getvalue()
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Failed to convert integration asset image to WebP.") from exc


def _ensure_unique_title(title: str, existing_titles: list[str]) -> str:
    base = title.strip()
    if not any(_is_similar(base, existing) for existing in existing_titles):
        return base

    suffix = 2
    while True:
        candidate = f"{base} {suffix}"
        if not any(_is_similar(candidate, existing) for existing in existing_titles):
            return candidate
        suffix += 1


def _prepare_markdown_body(title: str, body: str) -> str:
    cleaned = (body or "").strip()
    if not cleaned:
        return f"# {title}\n\n蹂몃Ц???앹꽦?섏? 紐삵뻽?듬땲??"
    if cleaned.startswith("# "):
        return cleaned
    return f"# {title}\n\n{cleaned}"


def _hash_image_bytes(image_bytes: bytes | None) -> str:
    if not image_bytes:
        return ""
    return hashlib.sha256(image_bytes).hexdigest()


def _is_inline_duplicate(cover_hash: str, inline_bytes: bytes | None) -> bool:
    if not cover_hash or not inline_bytes:
        return False
    return _hash_image_bytes(inline_bytes) == cover_hash


def _strip_generated_body_images(body_markdown: str) -> str:
    body = (body_markdown or "").strip()
    if not body:
        return ""
    cleaned = re.sub(r"(?is)<figure\b[^>]*>.*?</figure>", "", body)
    cleaned = re.sub(r"(?is)<img\b[^>]*>", "", cleaned)
    cleaned = re.sub(r"(?m)^\s*!\[[^\]]*\]\([^)]+\)\s*$", "", cleaned)
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _insert_markdown_inline_image(body_markdown: str, image_markdown: str) -> str:
    body = (body_markdown or "").strip()
    image_block = (image_markdown or "").strip()
    if not body or not image_block:
        return body

    h2_matches = list(re.finditer(r"(?m)^##\s+", body))
    if h2_matches:
        insert_at = h2_matches[len(h2_matches) // 2].start()
        return f"{body[:insert_at].rstrip()}\n\n{image_block}\n\n{body[insert_at:].lstrip()}"

    paragraph_breaks = list(re.finditer(r"\n\s*\n", body))
    if paragraph_breaks:
        insert_at = paragraph_breaks[len(paragraph_breaks) // 2].end()
        return f"{body[:insert_at].rstrip()}\n\n{image_block}\n\n{body[insert_at:].lstrip()}"

    return f"{body}\n\n{image_block}"


MYSTERY_BLOCK_TERMS = (
    "mystery",
    "unsolved",
    "haunting",
    "conspiracy",
    "murder",
    "괴담",
    "미스터리",
    "음모론",
)

CATEGORY_REQUIRED_TERMS: dict[str, tuple[str, ...]] = {
    "여행과기록": ("여행", "코스", "동선", "trip", "walk"),
    "축제와현장": ("축제", "행사", "festival", "event"),
    "문화와공간": ("전시", "공간", "museum", "popup", "culture"),
    "생활-실용": ("체크리스트", "실용", "정리", "guide", "check"),
    "생활-기록": ("루틴", "기록", "생활", "wellbeing", "memo"),
    "일상과메모": ("메모", "일상", "tip", "daily", "note"),
    "주식-흐름": ("stock", "market", "주식", "실적", "지표"),
    "크립토-흐름": ("crypto", "bitcoin", "ethereum", "코인", "토큰"),
    "개발과도구": ("tool", "ai", "workflow", "개발", "도구"),
    "기술의기록": ("tech", "workflow", "automation", "기술", "자동화"),
    "미스터리-스토리": ("mystery", "unsolved", "legend", "archive", "미스터리", "사건"),
}
def _topic_matches_category(*, category_slug: str, keyword: str) -> bool:
    lowered = keyword.lower()
    if not _is_mysteria_story_category(category_id="", category_slug=category_slug) and any(
        term in lowered for term in MYSTERY_BLOCK_TERMS
    ):
        return False

    required = CATEGORY_REQUIRED_TERMS.get(category_slug)
    if not required:
        return True
    return any(term.lower() in lowered for term in required)


def _safe_fallback_image_prompt(category_name: str, keyword: str) -> str:
    return (
        "Create one hero-cover editorial 3x3 collage with exactly 9 distinct panels. "
        f"Category context: {category_name}. Topic: {keyword}. "
        "Keep visible white gutters, make the center panel visually dominant, use realistic photography, "
        "show a real-world scene, and avoid violence, graphic details, text overlays, and logos."
    )


def _build_cloudflare_topic_provider_order(runtime: Any) -> list[str]:
    primary = str(getattr(runtime, "topic_discovery_provider", "") or "openai").strip().lower() or "openai"
    order = [primary]
    if primary != "openai" and str(getattr(runtime, "openai_api_key", "") or "").strip():
        order.append("openai")
    return order


def _resolve_cloudflare_topic_provider_order_for_generation(runtime: Any) -> list[str]:
    # Cloudflare channel should align with Blogger OpenAI model policy when OpenAI key is available.
    if str(getattr(runtime, "provider_mode", "") or "").strip().lower() == "live" and str(
        getattr(runtime, "openai_api_key", "") or ""
    ).strip():
        return ["openai"]
    return _build_cloudflare_topic_provider_order(runtime)


def _route_cloudflare_text_model(
    db: Session,
    *,
    requested_model: str | None,
    allow_large: bool,
    stage_name: str,
) -> str:
    decision = route_openai_free_tier_text_model(
        db,
        requested_model=requested_model,
        allow_large=allow_large,
        minimum_remaining_tokens=1,
    )
    if decision.reasons:
        add_log(
            db,
            job=None,
            stage=f"model_router:cloudflare:{stage_name}",
            message=f"Model routing applied for Cloudflare stage '{stage_name}'.",
            payload=decision.to_payload(),
        )
    return decision.resolved_model


def _resolve_cloudflare_requested_models(*, settings_map: dict[str, str], runtime: Any) -> tuple[str, str, str]:
    large_stage_model = (
        (settings_map.get("article_generation_model") or "").strip()
        or (settings_map.get("topic_discovery_model") or runtime.topic_discovery_model or "").strip()
        or (settings_map.get("openai_text_model") or runtime.openai_text_model or "").strip()
        or FREE_TIER_DEFAULT_LARGE_TEXT_MODEL
    )
    return (
        large_stage_model,  # topic discovery
        large_stage_model,  # article generation
        large_stage_model,  # image prompt generation
    )


def _should_switch_cloudflare_topic_provider(
    *,
    current_provider_hint: str,
    fallback_provider_hint: str | None,
    selected_on_attempt: int,
    discovered_topics: list[dict[str, Any]],
    attempt_reject_breakdown: dict[str, int],
    consecutive_category_mismatch_attempts: int,
) -> bool:
    if not fallback_provider_hint or current_provider_hint == fallback_provider_hint:
        return False
    if selected_on_attempt > 0 or not discovered_topics:
        return False
    if set(attempt_reject_breakdown.keys()) != {"category_mismatch"}:
        return False
    return consecutive_category_mismatch_attempts >= TOPIC_PROVIDER_CATEGORY_MISMATCH_FALLBACK_STREAK


def _should_switch_cloudflare_topic_template(
    *,
    current_topic_prompt_template: str,
    default_topic_prompt_template: str,
    selected_on_attempt: int,
    discovered_topics: list[dict[str, Any]],
    attempt_reject_breakdown: dict[str, int],
    consecutive_category_mismatch_attempts: int,
) -> bool:
    if current_topic_prompt_template.strip() == default_topic_prompt_template.strip():
        return False
    if selected_on_attempt > 0 or not discovered_topics:
        return False
    if set(attempt_reject_breakdown.keys()) != {"category_mismatch"}:
        return False
    return consecutive_category_mismatch_attempts >= TOPIC_TEMPLATE_CATEGORY_MISMATCH_FALLBACK_STREAK


def _build_prompt_map(bundle: dict, category_id: str) -> dict[str, str]:
    templates = bundle.get("templates") if isinstance(bundle, dict) else []
    mapping: dict[str, str] = {}
    for item in templates if isinstance(templates, list) else []:
        if not isinstance(item, dict):
            continue
        if str(item.get("categoryId") or "").strip() != category_id:
            continue
        stage = str(item.get("stage") or "").strip().lower()
        if not stage:
            continue
        mapping[stage] = str(item.get("content") or "")
    return mapping


SEO_GEO_CTR_STRUCTURE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("missing_summary_section", ("요약", "한눈에 보기", "tl;dr")),
    ("missing_confirmed_section", ("확인된 사실", "검증된 사실", "confirmed")),
    ("missing_unconfirmed_section", ("미확인", "검증 필요", "불확실", "가정", "주장/증언", "unconfirmed")),
    ("missing_scenario_section", ("시나리오", "전개 가능성", "향후 전개", "impact scenario")),
    ("missing_checklist_section", ("체크리스트", "실행 포인트", "행동 포인트", "action checklist")),
    ("missing_sources_section", ("출처/확인 경로", "출처", "참고 링크", "source/verification")),
)


def _assess_seo_geo_ctr_structure(body_markdown: str) -> dict[str, Any]:
    body = str(body_markdown or "")
    lowered = body.casefold()
    reasons: list[str] = []
    checks: dict[str, bool] = {}

    for reason, markers in SEO_GEO_CTR_STRUCTURE_RULES:
        passed = any(marker.casefold() in lowered for marker in markers)
        checks[reason] = passed
        if not passed:
            reasons.append(reason)

    h2_html_count = len(re.findall(r"(?is)<h2\b", body))
    h3_html_count = len(re.findall(r"(?is)<h3\b", body))
    h2_md_count = len(re.findall(r"(?m)^##\s+", body))
    h3_md_count = len(re.findall(r"(?m)^###\s+", body))
    h2_count = h2_html_count + h2_md_count
    h3_count = h3_html_count + h3_md_count
    has_depth = h2_count >= 4 and h3_count >= 2
    checks["section_depth"] = has_depth
    if not has_depth:
        reasons.append("missing_seo_geo_ctr_section_depth")

    return {
        "passed": len(reasons) == 0,
        "reasons": reasons,
        "checks": checks,
        "h2_count": h2_count,
        "h3_count": h3_count,
    }


def _assess_cloudflare_quality_gate(
    *,
    title: str,
    body_markdown: str,
    excerpt: str,
    faq_section: list[dict[str, Any]],
    similarity_corpus: list[dict[str, str]],
    thresholds: dict[str, float],
) -> dict[str, Any]:
    from app.services.content_ops_service import compute_seo_geo_scores, compute_similarity_analysis

    similarity_score = 0.0
    most_similar_url = ""
    if similarity_corpus:
        similarity_items = [
            {
                "key": "current",
                "title": title,
                "body_html": body_markdown,
                "url": "",
            }
        ]
        similarity_items.extend(
            {
                "key": item.get("key", ""),
                "title": item.get("title", ""),
                "body_html": item.get("body_html", ""),
                "url": item.get("url", ""),
            }
            for item in similarity_corpus
            if isinstance(item, dict)
        )
        similarity_map = compute_similarity_analysis(similarity_items)
        current_similarity = similarity_map.get("current", {})
        similarity_score = float(current_similarity.get("similarity_score", 0.0) or 0.0)
        most_similar_url = str(current_similarity.get("most_similar_url") or "").strip()

    seo_geo = compute_seo_geo_scores(
        title=title,
        html_body=body_markdown,
        excerpt=excerpt,
        faq_section=faq_section,
    )
    seo_score = float(seo_geo.get("seo_score", 0) or 0)
    geo_score = float(seo_geo.get("geo_score", 0) or 0)
    ctr_score = float(seo_geo.get("ctr_score", 0) or 0)
    reasons = _quality_gate_fail_reasons(
        similarity_score=similarity_score,
        seo_score=seo_score,
        geo_score=geo_score,
        ctr_score=ctr_score,
        similarity_threshold=float(thresholds["similarity_threshold"]),
        min_seo_score=float(thresholds["min_seo_score"]),
        min_geo_score=float(thresholds["min_geo_score"]),
        min_ctr_score=float(thresholds["min_ctr_score"]),
    )
    trust_assessment = assess_publish_trust_requirements(body_markdown)
    for trust_reason in trust_assessment.get("reasons", []):
        if trust_reason not in reasons:
            reasons.append(str(trust_reason))
    structure_assessment = _assess_seo_geo_ctr_structure(body_markdown)
    for structure_reason in structure_assessment.get("reasons", []):
        if structure_reason not in reasons:
            reasons.append(str(structure_reason))
    return {
        "passed": len(reasons) == 0,
        "reasons": reasons,
        "similarity_score": round(similarity_score, 1),
        "most_similar_url": most_similar_url,
        "seo_score": int(round(seo_score)),
        "geo_score": int(round(geo_score)),
        "ctr_score": int(round(ctr_score)),
        "trust_gate": trust_assessment,
        "structure_gate": structure_assessment,
    }


def _effective_quality_thresholds_for_category(category_slug: str, thresholds: dict[str, float]) -> dict[str, float]:
    effective = dict(thresholds)
    if category_slug in RELAXED_GEO_CATEGORY_SLUGS:
        effective["min_geo_score"] = min(
            _safe_float(effective.get("min_geo_score"), CLOUDFLARE_RELAXED_GEO_MIN_SCORE),
            CLOUDFLARE_RELAXED_GEO_MIN_SCORE,
        )
    return effective


def _sync_cloudflare_quality_rows(
    db: Session,
    *,
    rows: list[dict[str, str]],
    strict_live_only: bool = False,
    backup_tab_name: str | None = None,
) -> dict[str, Any]:
    from app.services.google_sheet_service import (
        CLOUDFLARE_SNAPSHOT_COLUMNS,
        QUALITY_COLUMNS,
        get_google_sheet_sync_config,
        sync_google_sheet_quality_tab,
    )

    def _safe_tab_name(raw: str, *, fallback: str) -> str:
        cleaned = re.sub(r'[:\\/?*\\[\\]]+', " ", str(raw or "").strip())
        cleaned = re.sub(r"\\s+", " ", cleaned).strip()
        if not cleaned:
            cleaned = fallback
        return cleaned[:100]

    config = get_google_sheet_sync_config(db)
    sheet_id = str(config.get("sheet_id") or "").strip()
    tab_name = _safe_tab_name(str(config.get("cloudflare_tab") or "").strip(), fallback="Cloudflare Blog")
    category_tabs_enabled = _is_enabled(config.get("cloudflare_category_tabs_enabled"), default=False)
    auto_format_enabled = _is_enabled(config.get("auto_format_enabled"), default=True)
    live_rows = [row for row in rows if str(row.get("status") or "").strip().lower() in {"published", "live"}]

    if not sheet_id:
        return {"status": "skipped", "reason": "google_sheet_not_configured", "rows": 0, "tab": tab_name}
    if not live_rows:
        return {"status": "skipped", "reason": "empty_rows", "rows": 0, "tab": tab_name}

    main_result = sync_google_sheet_quality_tab(
        db,
        sheet_id=sheet_id,
        tab_name=tab_name,
        incoming_rows=live_rows,
        base_columns=CLOUDFLARE_SNAPSHOT_COLUMNS,
        quality_columns=QUALITY_COLUMNS,
        key_columns=("remote_id", "url", "title"),
        auto_format_enabled=auto_format_enabled,
        strict_live_only=strict_live_only,
        backup_tab_name=backup_tab_name,
    )

    if not category_tabs_enabled:
        payload = dict(main_result if isinstance(main_result, dict) else {})
        payload.update(
            {
                "status": str(payload.get("status") or "ok"),
                "tab": str(payload.get("tab") or tab_name),
                "rows": int(payload.get("rows", 0) or 0),
                "category_tabs_enabled": False,
                "category_tabs": [],
            }
        )
        return payload

    grouped_rows: dict[str, list[dict[str, str]]] = {}
    for row in live_rows:
        category_slug = str(row.get("category_slug") or "").strip()
        category_name = str(row.get("category") or "").strip()
        group_key = category_slug or category_name
        if not group_key:
            continue
        grouped_rows.setdefault(group_key, []).append(row)

    used_tab_names: set[str] = {tab_name}
    category_results: list[dict[str, Any]] = []
    for group_key, group_rows in grouped_rows.items():
        candidate = _safe_tab_name(f"{tab_name}-{group_key}", fallback=tab_name)
        if candidate in used_tab_names:
            suffix = 2
            unique_candidate = candidate
            while unique_candidate in used_tab_names:
                unique_candidate = _safe_tab_name(f"{candidate}-{suffix}", fallback=tab_name)
                suffix += 1
            candidate = unique_candidate
        used_tab_names.add(candidate)

        category_result = sync_google_sheet_quality_tab(
            db,
            sheet_id=sheet_id,
            tab_name=candidate,
            incoming_rows=group_rows,
            base_columns=CLOUDFLARE_SNAPSHOT_COLUMNS,
            quality_columns=QUALITY_COLUMNS,
            key_columns=("remote_id", "url", "title"),
            auto_format_enabled=auto_format_enabled,
            strict_live_only=strict_live_only,
            backup_tab_name=f"{candidate}_BACKUP" if strict_live_only else None,
        )
        category_results.append(
            {
                "category": group_key,
                "tab": category_result.get("tab"),
                "rows": category_result.get("rows"),
                "status": category_result.get("status"),
            }
        )

    return {
        "status": "ok",
        "tab": tab_name,
        "rows": int(main_result.get("rows", 0) or 0),
        "category_tabs_enabled": True,
        "category_tabs": category_results,
    }


def generate_cloudflare_posts(
    db: Session,
    *,
    per_category: int = 1,
    category_slugs: list[str] | None = None,
    category_plan: dict[str, int] | None = None,
    manual_topic_plan: dict[str, list[dict[str, Any]]] | None = None,
    status: str = "published",
) -> dict:
    normalized_per_category = max(1, min(int(per_category), 5))
    normalized_status = "published" if status.strip().lower() != "draft" else "draft"
    settings_map = get_settings_map(db)
    schedule_timezone = (settings_map.get("schedule_timezone") or DEFAULT_CATEGORY_TIMEZONE).strip() or DEFAULT_CATEGORY_TIMEZONE
    try:
        schedule_tz = ZoneInfo(schedule_timezone)
    except Exception:  # noqa: BLE001
        schedule_tz = ZoneInfo(DEFAULT_CATEGORY_TIMEZONE)
    current_date = datetime.now(schedule_tz).date().isoformat()

    categories = [item for item in list_cloudflare_categories(db) if bool(item.get("isLeaf"))]
    if category_slugs:
        requested = {slug.strip() for slug in category_slugs if slug.strip()}
        categories = [item for item in categories if item["slug"] in requested or item["id"] in requested]
    normalized_plan: dict[str, int] = {}
    if category_plan:
        normalized_plan = {
            str(key).strip(): max(_safe_int(value, 0), 0)
            for key, value in category_plan.items()
            if str(key).strip()
        }
        categories = [
            item
            for item in categories
            if normalized_plan.get(str(item.get("slug") or "").strip(), normalized_plan.get(str(item.get("id") or "").strip(), 0)) > 0
        ]
    normalized_manual_topic_plan: dict[str, list[dict[str, Any]]] = {}
    if manual_topic_plan:
        for raw_key, raw_items in manual_topic_plan.items():
            key = str(raw_key or "").strip()
            if not key or not isinstance(raw_items, list):
                continue
            normalized_items: list[dict[str, Any]] = []
            for raw_item in raw_items:
                if not isinstance(raw_item, dict):
                    continue
                keyword = str(raw_item.get("keyword") or raw_item.get("title") or "").strip()
                if not keyword:
                    continue
                normalized_items.append({
                    "keyword": keyword,
                    "audience": str(raw_item.get("audience") or "").strip(),
                    "information_level": str(raw_item.get("information_level") or "").strip(),
                    "extra_context": str(raw_item.get("extra_context") or "").strip(),
                    "category_name": str(raw_item.get("category_name") or "").strip(),
                    "scheduled_for": str(raw_item.get("scheduled_for") or "").strip(),
                })
            if normalized_items:
                normalized_manual_topic_plan[key] = normalized_items
    if not categories:
        return {
            "status": "skipped",
            "reason": "no_categories_selected",
            "created_count": 0,
            "failed_count": 0,
            "categories": [],
        }

    runtime = get_runtime_config(db)
    inline_images_enabled = _cloudflare_inline_images_enabled(settings_map)
    require_cover_image = _cloudflare_require_cover_image(settings_map)
    topic_requested_model, article_requested_model, prompt_requested_model = _resolve_cloudflare_requested_models(
        settings_map=settings_map,
        runtime=runtime,
    )
    quality_thresholds = _quality_gate_thresholds(settings_map)
    (
        topic_history_lookback_days,
        topic_novelty_cluster_threshold,
        topic_novelty_angle_threshold,
        topic_soft_penalty_threshold,
    ) = _resolve_topic_history_settings(settings_map)
    blossom_cap_ratio = _safe_float(settings_map.get("cloudflare_blossom_cap_ratio"), 0.2)
    daily_mix_counter = _load_daily_topic_mix_counter(
        settings_map.get("cloudflare_daily_topic_mix_counts"),
        today=current_date,
    )
    blocked_blossom_keywords: list[str] = []

    topic_provider_order = _resolve_cloudflare_topic_provider_order_for_generation(runtime)
    topic_providers = {
        hint: get_topic_provider(
            db,
            provider_hint=hint,
            model_override=topic_requested_model if hint == "openai" else None,
        )
        for hint in topic_provider_order
    }
    image_provider = get_image_provider(db)
    prompt_bundle = get_cloudflare_prompt_bundle(db)
    integration_posts = _list_integration_posts(db)
    sheet_history_entries: list[Any] = []
    topic_history_source = "none"
    assess_novelty = None
    try:
        from app.services.google_sheet_service import (
            TopicHistoryEntry,
            assess_topic_novelty_against_history,
            build_sheet_topic_exclusion_prompt_cloudflare,
            list_sheet_topic_history_entries_cloudflare,
        )

        assess_novelty = assess_topic_novelty_against_history
        cloudflare_sheet_exclusion_prompt = build_sheet_topic_exclusion_prompt_cloudflare(
            db,
            lookback_days=topic_history_lookback_days,
            limit=36,
        )
        sheet_history_entries = list_sheet_topic_history_entries_cloudflare(
            db,
            lookback_days=topic_history_lookback_days,
            limit=180,
        )
        topic_history_source = "sheet" if sheet_history_entries else "sheet_empty"
        sheet_exclusion_entries = []
        for value in sheet_history_entries:
            entry = str(getattr(value, "keyword", "") or "").strip()
            if not entry:
                continue
            sheet_exclusion_entries.append(entry)
            cluster = str(getattr(value, "topic_cluster", "") or "").strip()
            angle = str(getattr(value, "topic_angle", "") or "").strip()
            if cluster:
                sheet_exclusion_entries.append(cluster)
            if angle:
                sheet_exclusion_entries.append(angle)
        if not sheet_history_entries:
            sheet_history_entries = _build_cloudflare_history_entries_from_posts(
                integration_posts,
                lookback_days=topic_history_lookback_days,
                limit=180,
                entry_cls=TopicHistoryEntry,
            )
            if sheet_history_entries:
                topic_history_source = "db_fallback"
                if not cloudflare_sheet_exclusion_prompt:
                    cloudflare_sheet_exclusion_prompt = _build_history_exclusion_prompt_from_entries(
                        sheet_history_entries,
                        limit=36,
                    )
    except Exception:  # noqa: BLE001
        cloudflare_sheet_exclusion_prompt = ""
        sheet_exclusion_entries = []
        sheet_history_entries = []
        topic_history_source = "sheet_error"

    all_titles = [str(item.get("title") or "").strip() for item in integration_posts if str(item.get("title") or "").strip()]
    all_slugs = [str(item.get("slug") or "").strip() for item in integration_posts if str(item.get("slug") or "").strip()]
    generated_similarity_corpus: list[dict[str, str]] = []
    for index, post in enumerate(integration_posts):
        generated_similarity_corpus.append(
            {
                "key": f"existing-{index + 1}",
                "title": str(post.get("title") or "").strip(),
                "body_html": str(post.get("contentMarkdown") or post.get("content") or post.get("excerpt") or "").strip(),
                "url": str(post.get("publicUrl") or post.get("url") or "").strip(),
            }
        )

    category_results: list[dict[str, Any]] = []
    created_count = 0
    failed_count = 0
    cloudflare_quality_rows: list[dict[str, str]] = []

    for category in categories:
        category_id = str(category.get("id") or "").strip()
        category_slug = str(category.get("slug") or "").strip()
        category_name = str(category.get("name") or category_slug)
        requested_for_category = normalized_per_category
        if normalized_plan:
            requested_for_category = normalized_plan.get(category_slug, normalized_plan.get(category_id, 0))
        if requested_for_category <= 0:
            continue
        category_gate = _category_hard_gate(category_slug, category_name)
        prompt_map = _build_prompt_map(prompt_bundle, category_id)
        default_topic_prompt_template = _default_prompt_for_stage(category, "topic_discovery")
        topic_prompt_template = prompt_map.get("topic_discovery") or default_topic_prompt_template
        article_prompt_template = prompt_map.get("article_generation") or _default_prompt_for_stage(category, "article_generation")
        image_prompt_template = prompt_map.get("image_prompt_generation") or _default_prompt_for_stage(category, "image_prompt_generation")
        mysteria_source_block = _build_mysteria_blogger_source_block(
            db,
            category_id=category_id,
            category_slug=category_slug,
            pair_size=2,
            preview_limit=6,
        )
        if mysteria_source_block:
            topic_prompt_template = f"{topic_prompt_template}\n\n{mysteria_source_block}"
            article_prompt_template = f"{article_prompt_template}\n\n{mysteria_source_block}"
            image_prompt_template = f"{image_prompt_template}\n\n{mysteria_source_block}"
        effective_quality_thresholds = _effective_quality_thresholds_for_category(category_slug, quality_thresholds)

        discovered_topics: list[dict[str, Any]] = []
        selected_topics: list[str] = []
        attempted_keywords: list[str] = []
        blocked_keywords: list[str] = []
        reject_breakdown: dict[str, int] = {}
        topic_attempt_logs: list[dict[str, Any]] = []
        selected_topic_novelty: dict[str, dict[str, Any]] = {}
        selected_topic_briefs: dict[str, dict[str, Any]] = {}
        max_topic_attempts = max(MAX_TOPIC_REGEN_ATTEMPTS_PER_CATEGORY, requested_for_category * 4)
        topic_discovery_error = ""
        active_topic_provider_hint = topic_provider_order[0]
        fallback_topic_provider_hint = topic_provider_order[1] if len(topic_provider_order) > 1 else None
        consecutive_category_mismatch_attempts = 0
        active_topic_prompt_template = topic_prompt_template
        manual_topic_entries = normalized_manual_topic_plan.get(category_slug) or normalized_manual_topic_plan.get(category_id) or []
        if manual_topic_entries:
            selected_on_manual = 0
            rejected_on_manual = 0
            for item in manual_topic_entries:
                keyword = str(item.get("keyword") or "").strip()
                if not keyword:
                    continue
                attempted_keywords.append(keyword)
                if _topic_matches_any(keyword, selected_topics) or _topic_matches_any(keyword, all_titles) or _topic_matches_any(keyword, all_slugs):
                    rejected_on_manual += 1
                    reject_breakdown["manual_duplicate"] = reject_breakdown.get("manual_duplicate", 0) + 1
                    continue
                selected_topics.append(keyword)
                selected_topic_briefs[keyword] = item
                _increment_topic_mix_counter(
                    daily_mix_counter,
                    is_blossom=_is_blossom_topic_keyword(keyword),
                )
                selected_on_manual += 1
                if len(selected_topics) >= requested_for_category:
                    break
            topic_attempt_logs.append(
                {
                    "attempt": 1,
                    "provider": "planner_manual",
                    "requested_topics": requested_for_category,
                    "discovered_topics": len(manual_topic_entries),
                    "selected_on_attempt": selected_on_manual,
                    "selected_total": len(selected_topics),
                    "rejected_on_attempt": rejected_on_manual,
                    "reject_breakdown": dict(reject_breakdown),
                    "attempt_reject_breakdown": {"manual_duplicate": rejected_on_manual} if rejected_on_manual else {},
                    "topic_history_source": "planner_manual",
                }
            )

        for attempt_index in range(max_topic_attempts):
            remaining_topics = requested_for_category - len(selected_topics)
            if remaining_topics <= 0:
                break

            requested_topic_count = max(remaining_topics * 3, remaining_topics + 1)
            runtime_exclusion_prompt = _build_runtime_topic_exclusion_prompt(
                attempted_keywords=attempted_keywords,
                limit=24,
            )
            runtime_blocked_prompt = _build_runtime_blocked_topic_prompt(
                blocked_keywords=blocked_keywords,
                limit=24,
            )
            blossom_block_prompt = _build_blossom_block_prompt(
                blocked_keywords=blocked_blossom_keywords,
                cap_ratio=blossom_cap_ratio,
                limit=16,
            )
            topic_prompt = (
                _render_prompt_template(
                    active_topic_prompt_template,
                    current_date=current_date,
                    topic_count=requested_topic_count,
                )
                + category_gate
                + cloudflare_sheet_exclusion_prompt
                + runtime_exclusion_prompt
                + runtime_blocked_prompt
                + blossom_block_prompt
                + _topic_output_contract(requested_topic_count)
            )
            try:
                topic_provider = topic_providers[active_topic_provider_hint]
                if runtime.provider_mode == "live" and active_topic_provider_hint == "openai":
                    topic_model = _route_cloudflare_text_model(
                        db,
                        requested_model=topic_requested_model,
                        allow_large=True,
                        stage_name="topic_discovery",
                    )
                    topic_provider = get_topic_provider(
                        db,
                        provider_hint=active_topic_provider_hint,
                        model_override=topic_model,
                    )
                topic_payload, _topic_raw = topic_provider.discover_topics(topic_prompt)
                discovered_topics = [
                    {"keyword": item.keyword, "reason": item.reason, "trend_score": item.trend_score}
                    for item in (topic_payload.topics or [])
                ]
            except Exception as exc:  # noqa: BLE001
                topic_discovery_error = str(exc)
                topic_attempt_logs.append(
                    {
                        "attempt": attempt_index + 1,
                        "provider": active_topic_provider_hint,
                        "requested_topics": requested_topic_count,
                        "status": "error",
                        "error": str(exc),
                    }
                )
                continue

            selected_on_attempt = 0
            rejected_on_attempt = 0
            attempt_reject_breakdown: dict[str, int] = {}
            attempt_novelty_blocks: list[dict[str, Any]] = []
            for item in discovered_topics:
                keyword = str(item.get("keyword") or "").strip()
                if not keyword:
                    continue
                attempted_keywords.append(keyword)

                reject_reason = ""
                novelty_assessment: dict[str, Any] = {}
                if not _topic_matches_category(category_slug=category_slug, keyword=keyword):
                    reject_reason = "category_mismatch"
                elif _topic_matches_any(keyword, selected_topics):
                    reject_reason = "batch_duplicate"
                elif _topic_matches_any(keyword, all_titles):
                    reject_reason = "existing_title_duplicate"
                elif _topic_matches_any(keyword, all_slugs):
                    reject_reason = "existing_slug_duplicate"
                elif _topic_matches_any(keyword, blocked_keywords):
                    reject_reason = "runtime_blocked"
                elif _would_exceed_blossom_cap(
                    counter=daily_mix_counter,
                    is_blossom=_is_blossom_topic_keyword(keyword),
                    cap_ratio=blossom_cap_ratio,
                ):
                    reject_reason = "blossom_cap_blocked"
                else:
                    if assess_novelty and sheet_history_entries:
                        inferred_cluster, inferred_angle = _infer_topic_cluster_angle(keyword)
                        novelty_raw = assess_novelty(
                            keyword=keyword,
                            topic_cluster=inferred_cluster,
                            topic_angle=inferred_angle,
                            history_entries=sheet_history_entries,
                            cluster_threshold=topic_novelty_cluster_threshold,
                            angle_threshold=topic_novelty_angle_threshold,
                        )
                        novelty_assessment = {
                            "novelty_score": novelty_raw.get("novelty_score"),
                            "penalty_points": novelty_raw.get("penalty_points"),
                            "penalty_reason": novelty_raw.get("penalty_reason"),
                            "matched_history_item": novelty_raw.get("matched_history_item"),
                            "similarity": novelty_raw.get("similarity"),
                            "topic_history_source": topic_history_source,
                        }
                        if int(novelty_raw.get("penalty_points") or 0) >= topic_soft_penalty_threshold:
                            reject_reason = "history_soft_penalty_threshold_exceeded"
                            attempt_novelty_blocks.append(
                                {
                                    "keyword": keyword,
                                    **novelty_assessment,
                                }
                            )
                    elif _topic_matches_any(keyword, sheet_exclusion_entries):
                        reject_reason = "sheet_blocked"

                if reject_reason:
                    blocked_keywords.append(keyword)
                    if reject_reason == "blossom_cap_blocked":
                        blocked_blossom_keywords.append(keyword)
                    reject_breakdown[reject_reason] = reject_breakdown.get(reject_reason, 0) + 1
                    attempt_reject_breakdown[reject_reason] = attempt_reject_breakdown.get(reject_reason, 0) + 1
                    rejected_on_attempt += 1
                    continue

                selected_topics.append(keyword)
                if novelty_assessment:
                    selected_topic_novelty[keyword] = novelty_assessment
                _increment_topic_mix_counter(
                    daily_mix_counter,
                    is_blossom=_is_blossom_topic_keyword(keyword),
                )
                selected_on_attempt += 1
                if len(selected_topics) >= requested_for_category:
                    break

            topic_attempt_logs.append(
                {
                    "attempt": attempt_index + 1,
                    "provider": active_topic_provider_hint,
                    "requested_topics": requested_topic_count,
                    "discovered_topics": len(discovered_topics),
                    "selected_on_attempt": selected_on_attempt,
                    "selected_total": len(selected_topics),
                    "rejected_on_attempt": rejected_on_attempt,
                    "reject_breakdown": dict(reject_breakdown),
                    "attempt_reject_breakdown": dict(attempt_reject_breakdown),
                    "novelty_blocks": attempt_novelty_blocks,
                    "topic_history_source": topic_history_source,
                }
            )
            if len(selected_topics) >= requested_for_category:
                break
            if set(attempt_reject_breakdown.keys()) == {"category_mismatch"} and rejected_on_attempt > 0 and selected_on_attempt == 0:
                consecutive_category_mismatch_attempts += 1
            else:
                consecutive_category_mismatch_attempts = 0
            if _should_switch_cloudflare_topic_provider(
                current_provider_hint=active_topic_provider_hint,
                fallback_provider_hint=fallback_topic_provider_hint,
                selected_on_attempt=selected_on_attempt,
                discovered_topics=discovered_topics,
                attempt_reject_breakdown=attempt_reject_breakdown,
                consecutive_category_mismatch_attempts=consecutive_category_mismatch_attempts,
            ):
                active_topic_provider_hint = fallback_topic_provider_hint or active_topic_provider_hint
                topic_attempt_logs[-1]["provider_switch"] = active_topic_provider_hint
                consecutive_category_mismatch_attempts = 0
                continue
            if _should_switch_cloudflare_topic_template(
                current_topic_prompt_template=active_topic_prompt_template,
                default_topic_prompt_template=default_topic_prompt_template,
                selected_on_attempt=selected_on_attempt,
                discovered_topics=discovered_topics,
                attempt_reject_breakdown=attempt_reject_breakdown,
                consecutive_category_mismatch_attempts=consecutive_category_mismatch_attempts,
            ):
                active_topic_prompt_template = default_topic_prompt_template
                topic_attempt_logs[-1]["template_switch"] = "default_prompt"
                consecutive_category_mismatch_attempts = 0

        if len(selected_topics) < requested_for_category:
            shortage = requested_for_category - len(selected_topics)
            failed_count += requested_for_category
            category_results.append(
                {
                    "category_id": category_id,
                    "category_slug": category_slug,
                    "category_name": category_name,
                    "requested": requested_for_category,
                    "created": 0,
                    "failed": requested_for_category,
                    "skipped": 0,
                    "topic_discovery_attempts": topic_attempt_logs,
                    "topic_discovery_error": (
                        topic_discovery_error
                        or f"topic_selection_incomplete: selected {len(selected_topics)} of "
                        f"{requested_for_category} after {max_topic_attempts} regeneration attempts"
                    ),
                    "topic_reject_breakdown": reject_breakdown,
                    "items": [
                        {
                            "status": "failed",
                            "error": "topic_selection_incomplete",
                            "selected_topics": list(selected_topics),
                            "selected_topic_novelty": selected_topic_novelty,
                            "missing_count": shortage,
                        }
                    ],
                }
            )
            continue

        items: list[dict[str, Any]] = []
        for keyword in selected_topics:
            topic_novelty = selected_topic_novelty.get(keyword, {})
            planner_brief = selected_topic_briefs.get(keyword, {})
            planner_brief_block = ""
            if planner_brief:
                planner_lines = [
                    "\n\n[Planner brief]",
                    f"- Topic: {keyword}",
                    f"- Audience: {planner_brief.get('audience') or ''}",
                ]
                if planner_brief.get("information_level"):
                    planner_lines.append(f"- Information level: {planner_brief.get('information_level')}")
                if planner_brief.get("extra_context"):
                    planner_lines.append(f"- Extra context: {planner_brief.get('extra_context')}")
                planner_brief_block = "\n".join(planner_lines)
            try:
                article_prompt = _build_cloudflare_master_article_prompt(
                    category=category,
                    keyword=keyword,
                    current_date=current_date,
                    planner_brief=planner_brief_block,
                    prompt_template=article_prompt_template,
                )
                article_prompt = f"{article_prompt}{category_gate}"
                article_prompt = _append_no_inline_image_rule(article_prompt)
                article_model = article_requested_model
                if runtime.provider_mode == "live":
                    article_model = _route_cloudflare_text_model(
                        db,
                        requested_model=article_requested_model,
                        allow_large=True,
                        stage_name="article_generation",
                    )
                article_provider = get_article_provider(db, model_override=article_model, allow_large=True)
                article_output, _article_raw = article_provider.generate_article(keyword, article_prompt)
                quality_attempts: list[dict[str, Any]] = []
                for quality_attempt in range(1, 3):
                    quality_assessment = _assess_cloudflare_quality_gate(
                        title=article_output.title,
                        body_markdown=article_output.html_article,
                        excerpt=article_output.excerpt,
                        faq_section=[
                            item.model_dump() if hasattr(item, "model_dump") else dict(item)
                            for item in (article_output.faq_section or [])
                            if isinstance(item, dict) or hasattr(item, "model_dump")
                        ],
                        similarity_corpus=generated_similarity_corpus,
                        thresholds=effective_quality_thresholds,
                    )
                    quality_assessment["attempt"] = quality_attempt
                    quality_attempts.append(quality_assessment)
                    if quality_assessment["passed"] or not bool(quality_thresholds.get("enabled", 1.0)):
                        break
                    if quality_attempt >= 2:
                        break
                    retry_prompt = (
                        article_prompt
                        + "\n\n[Quality gate retry instruction]\n"
                        + f"- Previous draft failed: {', '.join(quality_assessment.get('reasons', [])) or 'quality thresholds'}.\n"
                        + "- Rewrite with a materially different structure and sentence flow.\n"
                        + "- Keep SEO/GEO clarity and practical utility.\n"
                    )
                    retry_model = article_requested_model
                    if runtime.provider_mode == "live":
                        retry_model = _route_cloudflare_text_model(
                            db,
                            requested_model=article_requested_model,
                            allow_large=True,
                            stage_name="article_generation_retry",
                        )
                    retry_provider = get_article_provider(db, model_override=retry_model, allow_large=True)
                    article_output, _article_raw = retry_provider.generate_article(keyword, retry_prompt)

                final_quality = quality_attempts[-1] if quality_attempts else {
                    "passed": True,
                    "reasons": [],
                    "similarity_score": 0.0,
                    "most_similar_url": "",
                    "seo_score": 0,
                    "geo_score": 0,
                    "ctr_score": 0,
                    "attempt": 1,
                }
                quality_gate_payload = {
                    "enabled": bool(quality_thresholds.get("enabled", 1.0)),
                    "passed": bool(final_quality.get("passed")),
                    "attempts": quality_attempts,
                    "reason": ",".join(final_quality.get("reasons", [])),
                    "scores": {
                        "similarity_score": final_quality.get("similarity_score"),
                        "most_similar_url": final_quality.get("most_similar_url"),
                        "seo_score": final_quality.get("seo_score"),
                        "geo_score": final_quality.get("geo_score"),
                        "ctr_score": final_quality.get("ctr_score"),
                    },
                    "thresholds": {
                        "similarity_threshold": quality_thresholds.get("similarity_threshold"),
                        "min_seo_score": quality_thresholds.get("min_seo_score"),
                        "min_geo_score": effective_quality_thresholds.get("min_geo_score"),
                        "min_ctr_score": quality_thresholds.get("min_ctr_score"),
                    },
                }
                if not quality_gate_payload["enabled"]:
                    quality_gate_payload["passed"] = True
                    quality_gate_payload["reason"] = "disabled"
                if not quality_gate_payload["passed"]:
                    failed_count += 1
                    items.append(
                        {
                            "status": "failed",
                            "keyword": keyword,
                            "title": article_output.title,
                            "category_id": category_id,
                            "topic_novelty": topic_novelty,
                            "quality_gate": quality_gate_payload,
                            "error": "quality_gate_failed",
                        }
                    )
                    cloudflare_quality_rows.append(
                        {
                            "remote_id": "",
                            "published_at": "",
                            "created_at": "",
                            "category": category_name,
                            "category_slug": category_slug,
                            "title": article_output.title,
                            "url": "",
                            "excerpt": article_output.excerpt,
                            "labels": ", ".join(article_output.labels or []),
                            "status": "failed",
                            "updated_at": _utc_now_iso(),
                            "topic_cluster": "",
                            "topic_angle": "",
                            "similarity_score": str(final_quality.get("similarity_score") or ""),
                            "most_similar_url": str(final_quality.get("most_similar_url") or ""),
                            "seo_score": str(final_quality.get("seo_score") or ""),
                            "geo_score": str(final_quality.get("geo_score") or ""),
                            "ctr_score": str(final_quality.get("ctr_score") or ""),
                            "quality_status": "quality_gate_failed",
                            "rewrite_attempts": str(len(quality_attempts)),
                            "last_audited_at": _utc_now_iso(),
                        }
                    )
                    continue

                image_prompt_base = _render_prompt_template(
                    image_prompt_template,
                    current_date=current_date,
                    keyword=keyword,
                    topic_count=requested_for_category,
                ) + category_gate + planner_brief_block
                image_prompt_base = _append_hero_only_visual_rule(image_prompt_base)
                prompt_model = prompt_requested_model
                if runtime.provider_mode == "live":
                    prompt_model = _route_cloudflare_text_model(
                        db,
                        requested_model=prompt_requested_model,
                        allow_large=True,
                        stage_name="image_prompt_generation",
                    )
                prompt_provider = get_article_provider(db, model_override=prompt_model, allow_large=True)
                visual_prompt, _visual_raw = prompt_provider.generate_visual_prompt(image_prompt_base)
                visual_prompt = _append_hero_only_visual_rule(visual_prompt)

                title = _ensure_unique_title(article_output.title, all_titles)
                slug_seed = str(article_output.slug or title).strip()
                slug_candidate = slugify(slug_seed, separator="-", lowercase=True, allow_unicode=True)
                if not slug_candidate:
                    slug_candidate = slugify(title, separator="-", lowercase=True, allow_unicode=True)
                if not slug_candidate:
                    slug_candidate = f"post-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
                original_slug = slug_candidate
                serial = 2
                while slug_candidate in all_slugs:
                    slug_candidate = f"{original_slug}-{serial}"
                    serial += 1

                cover_alt = (article_output.meta_description or title).strip()[:180]
                cover_image_url = ""
                image_warning = ""
                image_bytes: bytes | None = None
                cover_hash = ""
                try:
                    image_bytes, _image_raw = image_provider.generate_image(visual_prompt, slug_candidate)
                except Exception as primary_image_exc:
                    fallback_visual_prompt = _safe_fallback_image_prompt(category_name, keyword)
                    try:
                        image_bytes, _image_raw = image_provider.generate_image(fallback_visual_prompt, slug_candidate)
                    except Exception as fallback_image_exc:
                        image_warning = f"image_generation_failed: {primary_image_exc}; fallback_failed: {fallback_image_exc}"
                cover_hash = _hash_image_bytes(image_bytes)
                if image_bytes:
                    try:
                        cover_image_url = _upload_integration_asset(
                            db,
                            post_slug=slug_candidate,
                            alt_text=cover_alt,
                            filename=f"{slug_candidate}.webp",
                            image_bytes=image_bytes,
                        )
                    except Exception as asset_exc:  # noqa: BLE001
                        image_warning = f"cover_upload_failed: {asset_exc}"

                if require_cover_image and not cover_image_url:
                    failed_count += 1
                    items.append(
                        {
                            "status": "failed",
                            "keyword": keyword,
                            "title": article_output.title,
                            "category_id": category_id,
                            "topic_novelty": topic_novelty,
                            "quality_gate": quality_gate_payload,
                            "error": "cover_image_missing",
                            "image_warning": image_warning or "cover_image_missing",
                        }
                    )
                    cloudflare_quality_rows.append(
                        {
                            "remote_id": "",
                            "published_at": "",
                            "created_at": "",
                            "category": category_name,
                            "category_slug": category_slug,
                            "title": article_output.title,
                            "url": "",
                            "excerpt": article_output.excerpt,
                            "labels": ", ".join(article_output.labels or []),
                            "status": "failed",
                            "updated_at": _utc_now_iso(),
                            "topic_cluster": "",
                            "topic_angle": "",
                            "similarity_score": str(final_quality.get("similarity_score") or ""),
                            "most_similar_url": str(final_quality.get("most_similar_url") or ""),
                            "seo_score": str(final_quality.get("seo_score") or ""),
                            "geo_score": str(final_quality.get("geo_score") or ""),
                            "ctr_score": str(final_quality.get("ctr_score") or ""),
                            "quality_status": "cover_image_missing",
                            "rewrite_attempts": str(len(quality_attempts)),
                            "last_audited_at": _utc_now_iso(),
                        }
                    )
                    continue

                body_markdown = _strip_generated_body_images(article_output.html_article)
                inline_prompt = str(getattr(article_output, "inline_collage_prompt", "") or "").strip()
                if inline_images_enabled and inline_prompt:
                    try:
                        inline_bytes, _inline_raw = image_provider.generate_image(inline_prompt, f"{slug_candidate}-inline-3x2")
                        if cover_image_url and _is_inline_duplicate(cover_hash, inline_bytes):
                            image_warning = "; ".join(
                                value for value in (image_warning, "inline_duplicate_skipped") if value
                            )
                        else:
                            inline_url = _upload_integration_asset(
                                db,
                                post_slug=slug_candidate,
                                alt_text=f"{title} inline collage",
                                filename=f"{slug_candidate}-inline-3x2.webp",
                                image_bytes=inline_bytes,
                            )
                            body_markdown = _insert_markdown_inline_image(
                                body_markdown,
                                f"![{title} inline collage]({inline_url})",
                            )
                    except Exception as inline_exc:  # noqa: BLE001
                        image_warning = "; ".join(
                            value
                            for value in (image_warning, f"inline_collage_failed:{inline_exc}")
                            if value
                        )

                tag_names: list[str] = []
                seen_tag_keys: set[str] = set()
                for raw_tag in [category_name, *(article_output.labels or [])]:
                    normalized_tag = str(raw_tag or "").replace("#", " ").strip()
                    normalized_tag = " ".join(normalized_tag.split())
                    if not normalized_tag:
                        continue
                    tag_key = normalized_tag.casefold()
                    if tag_key in seen_tag_keys:
                        continue
                    seen_tag_keys.add(tag_key)
                    tag_names.append(normalized_tag)
                    if len(tag_names) >= 20:
                        break

                create_payload = {
                    "title": title,
                    "content": _prepare_markdown_body(title, body_markdown),
                    "excerpt": article_output.excerpt,
                    "seoTitle": title,
                    "seoDescription": article_output.meta_description,
                    "tagNames": tag_names,
                    "categorySlug": category_slug or category_id,
                    "status": normalized_status,
                }
                if cover_image_url:
                    create_payload["coverImage"] = cover_image_url
                    create_payload["coverAlt"] = cover_alt
                create_response = _integration_request(
                    db,
                    method="POST",
                    path="/api/integrations/posts",
                    json_payload=create_payload,
                    timeout=120.0,
                )
                created_post = _integration_data_or_raise(create_response)
                if not isinstance(created_post, dict):
                    raise ValueError("Cloudflare create post returned an invalid payload.")
                category_fix_warning = ""
                created_post_id = str(created_post.get("id") or "").strip()
                category_payload = created_post.get("category")
                category_assigned = isinstance(category_payload, dict) and str(category_payload.get("id") or "").strip() == category_id
                if created_post_id and not category_assigned:
                    try:
                        category_fix_response = _integration_request(
                            db,
                            method="PUT",
                            path=f"/api/integrations/posts/{created_post_id}",
                            json_payload={"categoryId": category_id},
                            timeout=45.0,
                        )
                        updated_post = _integration_data_or_raise(category_fix_response)
                        if isinstance(updated_post, dict):
                            created_post = updated_post
                    except Exception as category_fix_exc:  # noqa: BLE001
                        category_fix_warning = f"category_fix_failed: {category_fix_exc}"

                created_count += 1
                all_titles.append(title)
                created_slug = str(created_post.get("slug") or slug_candidate).strip()
                if created_slug:
                    all_slugs.append(created_slug)
                created_post_published_at = str(created_post.get("publishedAt") or "").strip()
                created_post_created_at = str(created_post.get("createdAt") or "").strip()
                created_post_updated_at = str(created_post.get("updatedAt") or _utc_now_iso()).strip() or _utc_now_iso()
                if not created_post_created_at:
                    created_post_created_at = created_post_updated_at
                if not created_post_published_at and normalized_status == "published":
                    created_post_published_at = created_post_updated_at or created_post_created_at
                items.append(
                    {
                        "status": "created",
                        "keyword": keyword,
                        "title": str(created_post.get("title") or title),
                        "post_id": str(created_post.get("id") or ""),
                        "slug": created_slug,
                        "public_url": str(created_post.get("publicUrl") or "").strip(),
                        "category_id": category_id,
                        "topic_novelty": topic_novelty,
                        "quality_gate": quality_gate_payload,
                        "error": "; ".join(value for value in (image_warning, category_fix_warning) if value) or None,
                    }
                )
                generated_similarity_corpus.append(
                    {
                        "key": f"generated-{len(generated_similarity_corpus) + 1}",
                        "title": str(created_post.get("title") or title),
                        "body_html": article_output.html_article,
                        "url": str(created_post.get("publicUrl") or "").strip(),
                    }
                )
                cloudflare_quality_rows.append(
                    {
                        "remote_id": created_post_id,
                        "published_at": created_post_published_at,
                        "created_at": created_post_created_at,
                        "due_at": created_post_published_at or created_post_updated_at or created_post_created_at,
                        "category": category_name,
                        "category_slug": category_slug,
                        "title": str(created_post.get("title") or title),
                        "url": str(created_post.get("publicUrl") or "").strip(),
                        "excerpt": article_output.excerpt,
                        "labels": ", ".join(article_output.labels or []),
                        "status": normalized_status,
                        "updated_at": created_post_updated_at,
                        "topic_cluster": "",
                        "topic_angle": "",
                        "similarity_score": str(quality_gate_payload["scores"].get("similarity_score") or ""),
                        "most_similar_url": str(quality_gate_payload["scores"].get("most_similar_url") or ""),
                        "seo_score": str(quality_gate_payload["scores"].get("seo_score") or ""),
                        "geo_score": str(quality_gate_payload["scores"].get("geo_score") or ""),
                        "ctr_score": str(quality_gate_payload["scores"].get("ctr_score") or ""),
                        "quality_status": "ok",
                        "rewrite_attempts": str(len(quality_attempts)),
                        "last_audited_at": _utc_now_iso(),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                failed_count += 1
                items.append(
                    {
                        "status": "failed",
                        "keyword": keyword,
                        "topic_novelty": topic_novelty,
                        "error": str(exc),
                    }
                )
                cloudflare_quality_rows.append(
                    {
                        "remote_id": "",
                        "published_at": "",
                        "created_at": "",
                        "due_at": _utc_now_iso(),
                        "category": category_name,
                        "category_slug": category_slug,
                        "title": keyword,
                        "url": "",
                        "excerpt": "",
                        "labels": "",
                        "status": "failed",
                        "updated_at": _utc_now_iso(),
                        "topic_cluster": "",
                        "topic_angle": "",
                        "similarity_score": "",
                        "most_similar_url": "",
                        "seo_score": "",
                        "geo_score": "",
                        "ctr_score": "",
                        "quality_status": "failed",
                        "rewrite_attempts": "0",
                        "last_audited_at": _utc_now_iso(),
                    }
                )

        missing = max(requested_for_category - len(items), 0)
        if missing:
            failed_count += missing
            items.extend(
                {
                    "status": "skipped",
                    "error": "not_enough_unique_topics",
                }
                for _ in range(missing)
            )

        category_results.append(
            {
                "category_id": category_id,
                "category_slug": category_slug,
                "category_name": category_name,
                "requested": requested_for_category,
                "created": len([item for item in items if item.get("status") == "created"]),
                "failed": len([item for item in items if item.get("status") == "failed"]),
                "skipped": len([item for item in items if item.get("status") == "skipped"]),
                "topic_discovery_attempts": topic_attempt_logs,
                "topic_discovery_error": topic_discovery_error or None,
                "topic_reject_breakdown": reject_breakdown,
                "topic_history_source": topic_history_source,
                "topic_history_lookback_days": topic_history_lookback_days,
                "topic_soft_penalty_threshold": topic_soft_penalty_threshold,
                "items": items,
            }
        )

    upsert_settings(
        db,
        {
            "cloudflare_daily_topic_mix_counts": _dump_daily_topic_mix_counter(
                today=current_date,
                counter=daily_mix_counter,
            )
        },
    )
    try:
        quality_sheet_sync = _sync_cloudflare_quality_rows(db, rows=cloudflare_quality_rows)
    except Exception as exc:  # noqa: BLE001
        quality_sheet_sync = {"status": "failed", "reason": str(exc), "rows": len(cloudflare_quality_rows)}
    status_value = "ok" if failed_count == 0 else ("partial" if created_count > 0 else "failed")
    return {
        "status": status_value,
        "created_count": created_count,
        "failed_count": failed_count,
        "requested_categories": len(categories),
        "per_category": normalized_per_category,
        "category_plan": normalized_plan if normalized_plan else None,
        "quality_sheet_sync": quality_sheet_sync,
        "categories": category_results,
    }
