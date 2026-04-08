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

from app.models.entities import Blog, SyncedBloggerPost
from app.services.audit_service import add_log
from app.services.openai_usage_service import (
    FREE_TIER_DEFAULT_LARGE_TEXT_MODEL,
    FREE_TIER_DEFAULT_SMALL_TEXT_MODEL,
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
    "04_company_analysis_v3.md": (),
    "05_stock_weekly_v3.md": ("주식의-흐름",),
    "06_crypto_v3.md": ("크립토의-흐름",),
    "07_welfare_life_v3.md": ("삶을-유용하게", "삶의-기름칠", "일상과-메모"),
    "08_it_ai_tools_v3.md": ("개발과-프로그래밍", "기술의-기록"),
}

README_V3_LEAF_WEIGHTS: dict[str, int] = {
    "여행과-기록": 10,
    "축제와-현장": 10,
    "문화와-공간": 12,
    "미스테리아-스토리": 10,
    "주식의-흐름": 8,
    "크립토의-흐름": 10,
    "삶을-유용하게": 6,
    "삶의-기름칠": 6,
    "일상과-메모": 6,
    "개발과-프로그래밍": 6,
    "기술의-기록": 6,
}

BLOSSOM_KEYWORDS = (
    "cherry blossom",
    "cherry-blossom",
    "blossom",
    "sakura",
    "벚꽃",
    "왕벚꽃",
    "겹벚꽃",
    "봄꽃",
)

FALLBACK_CATEGORIES: tuple[dict[str, str | None], ...] = (
    {
        "id": "cat-donggri-dev",
        "slug": "개발과-프로그래밍",
        "name": "개발과 프로그래밍",
        "description": "개발 워크플로와 프로그래밍 실무를 다루는 글",
        "parentId": "cat-donggri",
    },
    {
        "id": "cat-donggri-travel",
        "slug": "여행과-기록",
        "name": "여행과 기록",
        "description": "한국 여행의 장면과 기록을 다루는 글",
        "parentId": "cat-donggri",
    },
    {
        "id": "cat-donggri-daily",
        "slug": "일상과-메모",
        "name": "일상과 메모",
        "description": "메모와 루틴, 생활 기록을 다루는 글",
        "parentId": "cat-donggri",
    },
    {
        "id": "cat-tech-useful-life",
        "slug": "삶을-유용하게",
        "name": "삶을 유용하게",
        "description": "유용한 기술과 정보를 합쳐 바로 쓰는 실용 기록",
        "parentId": "cat-market-tech",
    },
    {
        "id": "cat-tech-life-oil",
        "slug": "삶의-기름칠",
        "name": "삶의 기름칠",
        "description": "일상과 여행을 가볍게 정리",
        "parentId": "cat-market-tech",
    },
    {
        "id": "cat-market-stock",
        "slug": "주식의-흐름",
        "name": "주식의 흐름",
        "description": "현재 주목 종목을 분석하는 글",
        "parentId": "cat-market",
    },
    {
        "id": "cat-market-crypto",
        "slug": "크립토의-흐름",
        "name": "크립토의 흐름",
        "description": "암호화폐와 체인 트렌드를 분석하는 글",
        "parentId": "cat-market",
    },
    {
        "id": "cat-world-donggri-thought",
        "slug": "동그리의-생각",
        "name": "동그리의 생각",
        "description": "이슈를 동그리 관점으로 정리하는 해설 기록",
        "parentId": "cat-world",
    },
    {
        "id": "cat-world-mysteria-story",
        "slug": "미스테리아-스토리",
        "name": "미스테리아 스토리",
        "description": "미스터리와 역사 문화를 엮어 맥락을 정리하는 기록",
        "parentId": "cat-world",
    },
    {
        "id": "cat-info-culture",
        "slug": "문화와-공간",
        "name": "문화와 공간",
        "description": "전시와 문화 공간을 다루는 글",
        "parentId": "cat-info",
    },
    {
        "id": "cat-info-festival-field",
        "slug": "축제와-현장",
        "name": "축제와 현장",
        "description": "축제 정보와 현장 운영 가이드를 합쳐 정리하는 기록",
        "parentId": "cat-info",
    },
)

CATEGORY_TOPIC_GUIDANCE: dict[str, str] = {
    "개발과-프로그래밍": "개발 워크플로, SDK, 자동화, 프로그래밍 실무 개선과 같은 실행형 주제를 다룹니다.",
    "여행과-기록": "한국 여행 동선, 계절 장면, 지역 산책, 로컬 장소 경험을 다룹니다.",
    "일상과-메모": "메모 습관, 루틴, 기록법, 생활 정리와 같은 개인 실행형 주제를 다룹니다.",
    "삶을-유용하게": "바로 써먹는 기술, 도구, 서비스, 생활 생산성 정보를 다룹니다.",
    "삶의-기름칠": "일상 회복, 가벼운 정리, 생활 감각, 루틴 개선을 다룹니다.",
    "주식의-흐름": "종목, 실적, 시장 반응, 투자 포인트를 다룹니다.",
    "크립토의-흐름": "체인, 토큰, 프로젝트, 일정, 리스크를 다룹니다.",
    "동그리의-생각": "이슈 해설, 구조 분석, 관점 정리를 다룹니다.",
    "미스테리아-스토리": "미스터리 사건, 전설, 역사 논쟁, 기록 재해석을 다룹니다.",
    "문화와-공간": "전시, 박물관, 미술관, 영화·드라마·아이돌 관련 장소, 유적과 공간 경험을 다룹니다.",
    "축제와-현장": "축제 일정, 현장 운영, 교통, 숙박, 체크리스트 같은 실전 정보를 다룹니다.",
}

CATEGORY_MODULE_GUIDANCE: dict[str, tuple[str, ...]] = {
    "개발과-프로그래밍": (
        "문제가 발생하는 실제 장면",
        "핵심 개념 요약",
        "적용 순서",
        "실무에서 흔한 실패 포인트",
        "바로 써먹는 체크리스트",
    ),
    "여행과-기록": (
        "처음 가는 사람이 바로 이해할 포인트",
        "걷는 흐름과 동선",
        "현장 분위기",
        "근처에서 함께 묶기 좋은 요소",
        "시간대별 판단 기준",
    ),
    "일상과-메모": (
        "문제를 느끼는 생활 장면",
        "바로 적용 가능한 기록법",
        "오래 가는 이유",
        "실패를 줄이는 최소 규칙",
        "기록을 유지하는 트리거",
    ),
    "삶을-유용하게": (
        "실제 사용 장면",
        "무엇이 해결되는지",
        "설정 순서",
        "주의할 점",
        "추천 대상",
    ),
    "삶의-기름칠": (
        "지친 순간을 바꾸는 포인트",
        "가볍게 시작하는 방법",
        "지속 가능한 루틴",
        "생활에 붙이는 요령",
        "무리하지 않는 마무리",
    ),
    "주식의-흐름": (
        "지금 시장에서 보는 포인트",
        "숫자로 보는 변화",
        "기업 또는 업종 맥락",
        "다음 확인 포인트",
        "리스크 요약",
    ),
    "크립토의-흐름": (
        "가격보다 먼저 볼 구조",
        "체인/프로젝트 맥락",
        "일정과 촉매",
        "리스크 관리",
        "지금 체크할 데이터",
    ),
    "동그리의-생각": (
        "왜 이 이슈가 중요한지",
        "표면 현상과 구조 구분",
        "오해를 줄이는 정리",
        "현실적 영향",
        "관점의 결론",
    ),
    "미스테리아-스토리": (
        "사건 개요",
        "확인된 사실과 가설 구분",
        "기록 또는 장소 맥락",
        "주요 해석 비교",
        "왜 지금도 읽히는지",
    ),
    "문화와-공간": (
        "공간의 첫인상",
        "왜 지금 가볼 만한지",
        "체류 동선",
        "주변과 함께 보는 방법",
        "공간이 남기는 감각",
    ),
    "축제와-현장": (
        "일정과 운영 핵심",
        "도착 시간과 이동법",
        "구역별 동선",
        "먹거리·숙박·체크포인트",
        "출발 전 체크리스트",
    ),
}

CATEGORY_IMAGE_GUIDANCE: dict[str, str] = {
    "개발과-프로그래밍": "코드, 화면, 워크플로 장면처럼 주제가 바로 읽히는 실무 이미지가 맞습니다.",
    "여행과-기록": "장소의 공기, 걷는 흐름, 계절감, 동네 맥락이 한 장면 안에서 읽혀야 합니다.",
    "일상과-메모": "메모 습관과 기록 장면이 주인공이어야 하며, 사건 이미지가 주인공이면 안 됩니다.",
    "삶을-유용하게": "도구를 실제로 쓰는 장면이나 문제 해결 전후가 보이는 이미지가 맞습니다.",
    "삶의-기름칠": "정리, 회복, 일상 감각이 자연스럽게 보이는 생활 장면이 맞습니다.",
    "주식의-흐름": "기업, 거래 화면, 업종 현장처럼 분석 대상을 시각적으로 붙잡아야 합니다.",
    "크립토의-흐름": "체인, 프로젝트, 네트워크 맥락이 읽히는 이미지가 맞고 추상 배경 남발은 피합니다.",
    "동그리의-생각": "이슈의 구조나 사회적 맥락이 드러나는 이미지가 맞습니다.",
    "미스테리아-스토리": "사건 장소, 문서, 기록물, 조사 분위기처럼 다큐멘터리 톤이 맞습니다.",
    "문화와-공간": "전시 공간, 유적, 박물관, 촬영지, 아이돌 관련 장소처럼 실제 공간성이 읽혀야 합니다.",
    "축제와-현장": "행사 입구, 군중 흐름, 운영 동선, 현장 분위기처럼 실전 정보가 느껴지는 장면이 맞습니다.",
}


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
    for delimiter in ("|", ":", " - ", " — "):
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


def _list_remote_categories(values: dict[str, str]) -> list[dict]:
    url = _public_api_url(values, "/api/public/categories")
    if not url:
        return []
    try:
        payload = _fetch_json(url)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return []
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


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


def _category_topic_guidance(category_slug: str, category_name: str, category_description: str) -> str:
    return CATEGORY_TOPIC_GUIDANCE.get(category_slug, category_description or f"{category_name}에 맞는 주제를 다룹니다.")


def _category_modules(category_slug: str) -> tuple[str, ...]:
    return CATEGORY_MODULE_GUIDANCE.get(
        category_slug,
        (
            "핵심 맥락",
            "실전 정보",
            "현장 또는 공간 감각",
            "주의할 점",
            "독자가 바로 쓸 포인트",
        ),
    )


def _category_image_guidance(category_slug: str) -> str:
    return CATEGORY_IMAGE_GUIDANCE.get(category_slug, "글의 첫 약속을 즉시 보여주는 단일 장면 이미지가 맞습니다.")


def _cloudflare_editorial_category_key(category_slug: str) -> str:
    normalized = (category_slug or "").strip()
    if any(token in normalized for token in ("여행", "축제")):
        return "travel"
    if "문화" in normalized:
        return "culture"
    if any(token in normalized for token in ("맛", "푸드", "식")):
        return "food"
    return "general"


def _cloudflare_target_audience(category_slug: str, category_name: str) -> str:
    normalized = (category_slug or "").strip()
    if any(token in normalized for token in ("여행", "축제", "문화")):
        return (
            "한국에서 실제 방문 결정을 하려는 한국어 독자. 동선, 시간대, 비용, 대기, 혼잡 회피, "
            "가볼지 말지 판단 포인트를 빠르게 알고 싶어 한다."
        )
    if any(token in normalized for token in ("주식", "코인", "블록체인")):
        return "핵심 변수와 리스크를 빠르게 파악해 다음 판단 포인트를 잡으려는 한국어 투자자."
    if any(token in normalized for token in ("일", "개발", "기술")):
        return "실무에 바로 적용할 도구, 워크플로, 비교 기준을 찾는 한국어 개발자와 지식노동자."
    if any(token in normalized for token in ("생활", "복지", "메모")):
        return "자격, 절차, 준비물, 자주 하는 실수를 빠르게 확인하려는 한국어 생활정보 독자."
    if "미스터리" in normalized:
        return "사실과 해석을 구분해 읽고 싶고 핵심 기록과 주요 가설을 짧게 정리받고 싶은 한국어 독자."
    return f"{category_name} 주제에서 실제 판단 포인트를 빠르게 확인하려는 한국어 독자."


def _cloudflare_content_brief(category_slug: str, category_name: str, category_description: str) -> str:
    normalized = (category_slug or "").strip()
    if any(token in normalized for token in ("여행", "축제", "문화")):
        return (
            "CTR과 SEO를 함께 잡는 한국어 실전 가이드 글로 작성한다. "
            "도입부에서 방문 여부 판단 포인트를 빠르게 주고, 본문은 동선, 시간, 예산, 대기, 체류 포인트 중심으로 전개한다."
        )
    if any(token in normalized for token in ("주식", "코인", "블록체인")):
        return (
            "CTR과 SEO를 함께 잡는 한국어 분석형 글로 작성한다. "
            "헤드라인은 클릭 훅을 유지하되 본문은 변수, 흐름, 리스크, 다음 체크포인트 중심으로 전개한다."
        )
    if any(token in normalized for token in ("일", "개발", "기술")):
        return (
            "CTR과 SEO를 함께 잡는 한국어 실무형 글로 작성한다. "
            "툴 소개에 그치지 말고 누가 언제 왜 써야 하는지, 실무에서 무엇이 달라지는지 중심으로 전개한다."
        )
    if any(token in normalized for token in ("생활", "복지", "메모")):
        return (
            "CTR과 SEO를 함께 잡는 한국어 생활정보 글로 작성한다. "
            "자격, 절차, 준비물, 실수 방지, 다시 확인해야 할 포인트를 먼저 정리하고 본문을 전개한다."
        )
    if "미스터리" in normalized:
        return (
            "CTR과 SEO를 함께 잡는 한국어 다큐멘터리형 글로 작성한다. "
            "흥미를 끌되 과장하지 말고 기록, 쟁점, 대표 해석, 지금 읽어야 하는 이유를 중심으로 전개한다."
        )
    return category_description or f"{category_name} 주제를 CTR과 SEO에 맞는 한국어 실전 글로 재구성한다."


def _read_master_prompt_template(file_name: str) -> str:
    resolved = Path(__file__).resolve()
    candidates = (
        resolved.parents[4] / "prompts" / file_name,
        Path.cwd() / "prompts" / file_name,
        Path("/app/prompts") / file_name,
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    raise FileNotFoundError(f"Prompt template not found: {file_name}")


def _build_cloudflare_master_article_prompt(
    category: dict[str, Any],
    *,
    keyword: str,
    current_date: str,
    planner_brief: str,
) -> str:
    category_name = str(category.get("name") or category.get("slug") or "").strip()
    category_slug = str(category.get("slug") or "").strip()
    category_description = str(category.get("description") or "").strip()
    prompt_template = _read_master_prompt_template("travel_article_generation.md")
    rendered = render_prompt_template(
        prompt_template,
        keyword=keyword,
        primary_language="ko",
        target_audience=_cloudflare_target_audience(category_slug, category_name),
        content_brief=_cloudflare_content_brief(category_slug, category_name, category_description),
        planner_brief=planner_brief or "No planner brief provided.",
        current_date=current_date,
        editorial_category_key=_cloudflare_editorial_category_key(category_slug),
        editorial_category_label=category_name or "Cloudflare",
        editorial_category_guidance=_category_topic_guidance(category_slug, category_name, category_description),
    )
    return (
        f"{rendered.rstrip()}\n\n"
        "[Cloudflare article policy]\n"
        "- Write like a publish-ready Korean CTR/SEO article, not an audit note or compliance memo.\n"
        "- Do not use fixed report headings such as timestamp blocks, 핵심 요약, 확인된 사실, 미확인 정보/가정, 출처/확인 경로.\n"
        "- Keep the body substantial enough for a real 6 to 10 minute read without filler.\n"
        "- If schedules, prices, eligibility, or 운영 정보 can change, use recheck wording naturally inside the relevant section.\n"
    )


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
        "[미스테리아 스토리 소스 운영 컨셉]",
        "- 이 카테고리는 Blogger 원본 소스를 한국어 문화권 맥락에 맞게 재가공하는 방식으로 작성합니다.",
        "- DB 소스 큐는 오래된 글부터(ascending) 순서대로 읽고, 한 회차에 2개씩(source pair) 묶어 사용합니다.",
        "- 단순 직역 금지: 사실 관계/출처는 유지하고 한국 독자 기준의 맥락, 용어, 설명 순서로 재구성합니다.",
        "- source pair에서 겹치는 사실은 교차 검증 포인트로 정리하고, 상충 내용은 분리 표기합니다.",
        "- 본문에서 원문 표현을 길게 복사하지 말고, 검증 가능한 사실 중심의 한국어 다큐멘터리 톤으로 씁니다.",
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
        intro_lines.append("- 글 생성 시 source_1 + source_2를 우선 pair로 사용하고, 다음 회차는 source_3 + source_4로 진행합니다.")
    except Exception:  # noqa: BLE001
        return "\n".join(intro_lines) + "\n"

    return "\n".join(intro_lines) + "\n"


def _shared_structure_rules() -> str:
    return """[공통 원칙]
- 한국 문화/여행 블로그의 실전형 구조를 따르되, 모든 글을 같은 패턴으로 찍어내지 않습니다.
- SEO + GEO를 지키더라도 도입 방식, 문단 길이, 리스트 위치, 정리 방식은 매번 달라야 합니다.
- 같은 카테고리 안에서도 같은 제목 리듬, 같은 문단 순서, 같은 결론 문장을 반복하지 않습니다.
- 이모지는 0~3개 범위에서 필요할 때만 쓰고, 고정 위치에 박아 넣지 않습니다.
- '한눈에 보기', '정리하면', '마무리' 같은 상투적 소제목을 기계적으로 반복하지 않습니다.
"""


def _shared_fit_rules(category_name: str) -> str:
    return f"""[카테고리 적합성]
- 제목, 리드, 본문, 카테고리, 이미지가 모두 같은 중심 약속을 가리켜야 합니다.
- 카테고리가 {category_name}이면 본문 중심도 반드시 그 카테고리 관점이어야 합니다.
- 다른 카테고리의 예시를 들 수는 있지만, 그 예시가 제목과 대표 이미지를 먹어버리면 실패입니다.
- 메모 글이면 메모와 루틴이 먼저 보여야 하고, 사건/장소는 보조 재료여야 합니다.
- 사건·공간·축제 글이면 메모 도구, 노트북, 책상 같은 generic 이미지가 주인공이면 안 됩니다.
"""


def _seasonal_cherry_blossom_rules() -> str:
    return """[봄 시즌 우선순위]
- 현재 날짜가 3월 말~4월이어도 벚꽃은 강제 주제가 아닙니다.
- 벚꽃 주제는 일간 채널 상한을 넘지 않는 범위에서만 선택합니다.
- 벚꽃을 쓰더라도 전국 총정리 대신 장소·시간대·동선·현장 운영처럼 실전 각도로 제한합니다.
- 벚꽃 대안으로 축제 운영, 전시/공간, 로컬 산책, 시장/먹거리, 문화 일정 같은 비벚꽃 주제를 적극 섞습니다.
"""


def _build_default_topic_prompt(category: dict) -> str:
    category_name = str(category["name"])
    category_slug = str(category["slug"])
    category_description = str(category.get("description") or "")
    modules = _render_bullets(_category_modules(category_slug))
    return f"""당신은 Dongri Archive의 카테고리 기획 에디터입니다.

Current date: {{current_date}}

[카테고리]
- 이름: {category_name}
- 슬러그: {category_slug}
- 설명: {category_description}
- 주제 기준: {_category_topic_guidance(category_slug, category_name, category_description)}

[목표]
- 이 카테고리에 정확히 맞는 주제만 제안합니다.
- 검색 수요가 있어도 카테고리와 맞지 않으면 제외합니다.
- 제목만 바꾼 복제 제안을 하지 않습니다.

{_shared_structure_rules()}
{_shared_fit_rules(category_name)}
{_seasonal_cherry_blossom_rules()}

[선호 모듈]
{modules}

[추가 규칙]
- 문화와-공간은 전시, 박물관, 유적, 촬영지, 아이돌 관련 장소처럼 실제 공간 경험이 있어야 합니다.
- 축제와-현장은 일정, 운영, 교통, 숙박, 대기 흐름 같은 현장 판단 정보가 살아 있어야 합니다.
- 여행과-기록은 장소를 나열하지 말고, 걷는 흐름과 지역 감각이 살아 있어야 합니다.
- 미스테리아-스토리는 사건 개요, 기록, 해석 차이처럼 미스터리 자체가 중심이어야 합니다.

[금지]
- 카테고리와 맞지 않는 주제
- 제목만 바꾼 중복 제안
- 한 글 안에 여러 카테고리 관점을 동시에 주인공으로 세우는 제안
"""


def _build_default_article_prompt(category: dict) -> str:
    category_name = str(category["name"])
    category_slug = str(category["slug"])
    category_description = str(category.get("description") or "")
    modules = _render_bullets(_category_modules(category_slug))
    return f"""당신은 Dongri Archive 글을 쓰는 에디터입니다.

Current date: {{current_date}}
Topic: {{keyword}}

[카테고리]
- 이름: {category_name}
- 설명: {category_description}
- 주제 기준: {_category_topic_guidance(category_slug, category_name, category_description)}

{_shared_structure_rules()}
{_shared_fit_rules(category_name)}
{_seasonal_cherry_blossom_rules()}

[글쓰기 규칙]
- 첫 문단 안에서 독자의 검색 의도를 바로 잡아줍니다.
- 도입 방식은 매번 다르게 시작합니다: 장면, 질문, 경고, 요약, 현장감 중 하나를 골라 자연스럽게 엽니다.
- 본문은 4~6개 단락 블록으로 운영하되, 늘 같은 순서로 쓰지 않습니다.
- 리스트는 필요할 때만 쓰고, 같은 위치에 반복 배치하지 않습니다.
- 제목, 리드, 본문, 이미지가 모두 같은 약속을 향해야 합니다.
- 본문 안에는 이미지 마크다운, HTML 이미지 태그, 콜라주 안내 문구를 넣지 않습니다.

[우선 고려 모듈]
{modules}

[카테고리별 보정]
- 문화와-공간: 공간 경험, 체류 동선, 왜 지금 가볼 만한지, 주변과 함께 묶는 방식을 우선합니다.
- 축제와-현장: 일정, 도착 시간, 이동법, 현장 운영, 체크리스트를 우선합니다.
- 여행과-기록: 장소 열거보다 동선과 감각, 시간대 판단을 우선합니다.
- 일상과-메모: 루틴과 기록법이 주인공이어야 합니다.
- 미스테리아-스토리: 사실, 기록, 해석 차이를 분명히 나눕니다.

[금지]
- 모든 글을 같은 5단 구조로 고정하기
- 다른 카테고리 예시가 제목과 이미지를 먹어버리게 쓰기
- generic 결론 문장을 복붙하기
"""


def _build_default_image_prompt(category: dict) -> str:
    category_name = str(category["name"])
    category_slug = str(category["slug"])
    category_description = str(category.get("description") or "")
    return f"""당신은 Dongri Archive 대표 이미지 디렉터입니다.

Current date: {{current_date}}
Topic: {{keyword}}

[카테고리]
- 이름: {category_name}
- 설명: {category_description}
- 주제 기준: {_category_topic_guidance(category_slug, category_name, category_description)}

[공통 규칙]
- 대표 이미지는 글의 첫 약속을 즉시 보여주는 hero 이미지여야 합니다.
- 대표 이미지는 정확히 9개의 패널로 분리된 3x3 콜라주여야 합니다.
- 패널 사이에는 흰 여백이 보여야 하고, 가운데 패널이 가장 크게 강조되어야 합니다.
- 제목과 리드가 약속한 장소·사건·공간·현장감을 바로 읽을 수 있어야 합니다.
- 노트북, 메모장, 책상 같은 generic 도구 이미지는 메모 글이 아닐 때 금지합니다.
- 본문용 보조 이미지, 인포그래픽, 차트 이미지는 자동 발행 기본값에서 금지합니다.

[카테고리 우선 규칙]
- {_category_image_guidance(category_slug)}
- 문화와-공간은 실제 공간성이 먼저 보여야 합니다.
- 축제와-현장은 입구, 군중 흐름, 운영 동선, 현장 분위기가 드러나야 합니다.
- 여행과-기록은 지역의 결, 걷는 흐름, 계절감이 같이 읽혀야 합니다.
- 미스테리아-스토리는 다큐멘터리 톤의 사건 장소, 문서, 기록물, 조사 분위기가 맞습니다.

[봄 시즌 보정]
- 3월 말~4월이면 벚꽃 주제에서 장소성이 없는 generic 분홍 배경을 금지합니다.
- 동네 벚꽃길, 하천 산책, 구 단위 축제, 저녁 조명처럼 제목 속 장소와 현장성이 읽혀야 합니다.
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
    posts = _list_remote_posts(values)
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
        quality_status = str(
            post.get("quality_status")
            or post.get("qualityStatus")
            or quality_payload.get("status")
            or "",
        ).strip() or None
        index_status = str(
            post.get("index_status")
            or post.get("indexStatus")
            or index_payload.get("status")
            or _resolve_index_status(post)
        ).strip() or "unknown"
        items.append(
            {
                "provider": "cloudflare",
                "channel_id": str(category.get("id") or "dongriarchive"),
                "channel_name": channel_name,
                "category_name": str(category.get("name") or "").strip(),
                "category_slug": str(category.get("slug") or "").strip(),
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
                "index_status": index_status,
                "quality_status": quality_status,
                "published_at": published_at,
                "created_at": created_at,
                "updated_at": updated_at,
                "status": status_value,
            }
        )
    return items


def get_cloudflare_overview(db: Session) -> dict:
    values = get_settings_map(db)
    categories = list_cloudflare_categories(db)
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
    categories = list_cloudflare_categories(db)
    templates: list[dict] = []
    for category in categories:
        for stage in DEFAULT_PROMPT_STAGES:
            keys = _prompt_storage_keys(str(category["id"]), stage)
            content = values.get(keys["content"]) or _default_prompt_for_stage(category, stage)
            display_name = (values.get(keys["name"]) or "").strip() or f"{category['name']} · {stage}"
            objective = (values.get(keys["objective"]) or "").strip() or f"{category['name']} 카테고리용 프롬프트"
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
        "name": (name or "").strip() or f"{category['name']} · {normalized_stage}",
        "objective": (objective or "").strip() or f"{category['name']} 카테고리용 프롬프트",
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
        "- Keep structure SEO-friendly and readable.\n"
        "- Do not include inline markdown/HTML images in html_article body.\n"
        "- The system inserts one inline collage image separately in the middle of the article body.\n"
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
        "- Include one section that clearly separates 확인된 사실 and 미확인 정보.",
        "- Include one source/verification section with 2-5 concrete references or official channels.",
        "- If no verifiable URL exists, explicitly write: 확인 가능한 공식 URL 없음(작성 시점 기준).",
        "- Do not present rumors or repost claims as confirmed facts.",
        "- Avoid exaggerated or absolute claims unless verifiable evidence is provided.",
        "- Follow a fixed SEO/GEO/CTR-friendly section order.",
        "- Required section order: 핵심 요약 -> 확인된 사실 -> 미확인 정보/가정 -> 전개 시나리오 -> 행동 체크리스트 -> 출처/확인 경로 -> FAQ.",
        "- Keep at least 4 top-level sections and at least 2 sub-sections.",
        "- In the first 220 characters, state target reader and what they can decide after reading.",
        "- Avoid vague prose. Prefer concrete entities, dates, and actionable checkpoints.",
    ]

    if category_slug in {"주식의-흐름", "크립토의-흐름", "동그리의-생각"}:
        guard_lines.append("- For forward-looking analysis, label scenarios as possibilities, not certainties.")
    if category_slug in {"문화와-공간", "축제와-현장", "여행과-기록"}:
        guard_lines.append("- For schedule/price/entry details, use recheck wording when uncertain.")
    if category_slug == "미스테리아-스토리":
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
    if category_slug != "미스테리아-스토리":
        lines.append("- Do not use mystery, murder, unsolved-case, haunting, or conspiracy angles.")
    if category_slug != "축제와-현장":
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
        return f"# {title}\n\n본문을 생성하지 못했습니다."
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
    "murder",
    "haunting",
    "dyatlov",
    "roanoke",
    "hinterkaifeck",
    "black dahlia",
    "hope diamond",
    "미스터리",
    "살인",
    "실종",
    "사건",
)

CATEGORY_REQUIRED_TERMS: dict[str, tuple[str, ...]] = {
    "축제와-현장": ("축제", "행사", "일정", "운영", "동선", "벚꽃", "festival"),
    "문화와-공간": ("전시", "박물관", "미술관", "촬영지", "문화", "유적", "공간", "exhibition", "museum"),
    "여행과-기록": ("여행", "산책", "코스", "동선", "지역", "벚꽃", "trip", "walk"),
    "일상과-메모": ("메모", "루틴", "기록", "노트", "습관", "memo", "routine"),
    "개발과-프로그래밍": ("개발", "코드", "프로그래밍", "sdk", "api", "automation"),
    "삶을-유용하게": ("도구", "생산성", "실전", "정리", "유용", "tool", "productivity"),
    "삶의-기름칠": ("일상", "회복", "루틴", "정리", "생활", "wellbeing"),
    "주식의-흐름": ("주식", "종목", "실적", "시장", "stock", "earnings"),
    "크립토의-흐름": ("크립토", "코인", "체인", "토큰", "crypto", "bitcoin", "ethereum"),
    "동그리의-생각": ("관점", "해설", "분석", "이슈", "opinion", "analysis"),
    "미스테리아-스토리": ("mystery", "unsolved", "사건", "미스터리", "전설", "legend"),
    "기술의-기록": ("기술", "테크", "툴", "도구", "tech", "workflow"),
    "동그리의-기록": ("기록", "동네", "생활", "산책", "로컬", "log"),
    "세상의-기록": ("세계", "이슈", "국제", "트렌드", "global", "world"),
    "시장의-기록": ("시장", "산업", "경제", "소비", "market", "business"),
    "정보의-기록": ("가이드", "정보", "체크리스트", "안내", "guide", "info"),
}

RELAXED_GEO_CATEGORY_SLUGS = {
    "개발과-프로그래밍",
    "삶을-유용하게",
    "삶의-기름칠",
    "일상과-메모",
    "주식의-흐름",
    "크립토의-흐름",
    "동그리의-생각",
    "미스테리아-스토리",
    "기술의-기록",
    "세상의-기록",
    "시장의-기록",
    "정보의-기록",
}

CATEGORY_FALLBACK_TOPICS: dict[str, tuple[str, ...]] = {
    "축제와-현장": (
        "서울 동네 축제 현장 운영 체크리스트",
        "부산 구단위 봄축제 이동 동선과 대기 시간 줄이는 방법",
        "주말 야간행사 입장 동선과 교통 전략",
    ),
    "문화와-공간": (
        "봄 시즌 서울 전시 공간 하루 코스 구성법",
        "드라마 촬영지 기반 문화공간 산책 루트",
        "아이돌 관련 전시·공간 방문 동선 가이드",
    ),
    "여행과-기록": (
        "동네 아침 산책 코스 기록법",
        "하천 산책 루트와 시간대별 풍경 비교",
        "도심 로컬 스팟 1일 도보 동선 구성",
    ),
    "일상과-메모": (
        "봄 시즌 한 달 기록 루틴 설계",
        "출퇴근 산책 메모를 남기는 10분 습관",
        "사진·메모·지출을 한 번에 정리하는 생활 로그",
    ),
    "개발과-프로그래밍": (
        "콘텐츠 자동화 파이프라인 실패 복구 체크리스트",
        "OpenAI 이미지·텍스트 호출 비용 모니터링 구조",
        "스케줄러 중복 주제 차단 로직 설계 패턴",
    ),
    "삶을-유용하게": (
        "봄철 외출 준비를 줄이는 체크리스트 자동화",
        "동네 행사 일정과 이동 메모를 한 번에 관리하는 법",
        "일상 반복 업무를 줄이는 실전 도구 조합",
    ),
    "삶의-기름칠": (
        "봄철 생활 리듬 회복 루틴 구성",
        "하루 15분 정리 습관으로 피로 줄이기",
        "주간 리셋 루틴: 산책·기록·정리 결합법",
    ),
    "주식의-흐름": (
        "이번 주 실적 발표 종목 점검 프레임",
        "변동성 장세에서 손실 제한 체크리스트",
        "섹터 순환 국면에서 확인할 핵심 지표",
    ),
    "크립토의-흐름": (
        "이번 주 크립토 일정 캘린더 핵심 요약",
        "알트코인 변동성 구간 리스크 관리법",
        "체인 지표로 보는 시장 모멘텀 점검",
    ),
    "동그리의-생각": (
        "로컬 행사 소비 패턴 변화와 도시 운영 관점",
        "콘텐츠 자동화 시대의 품질 기준 재정의",
        "지역 문화 기록이 도시 브랜드에 미치는 영향",
    ),
    "기술의-기록": (
        "생성형 AI 글쓰기 파이프라인 운영 안정화 체크포인트",
        "이미지 프롬프트 품질 관리 자동화 설계",
        "콘텐츠 스케줄러 장애 대응 운영 로그 템플릿",
    ),
    "동그리의-기록": (
        "오늘 동네 산책 기록을 오래 남기는 방법",
        "로컬 카페와 하천 산책을 묶는 주말 기록 루트",
        "계절 변화 관찰 노트를 꾸준히 쓰는 루틴",
    ),
    "세상의-기록": (
        "이번 주 글로벌 이슈 핵심 맥락 정리",
        "국제 뉴스 소비를 줄이면서 핵심만 보는 프레임",
        "세계 경제 이슈가 생활 비용에 미치는 영향",
    ),
    "시장의-기록": (
        "이번 주 소비·유통 시장 변화 포인트",
        "중소상권 매출 흐름을 읽는 핵심 지표",
        "가격 변동 구간에서 시장 체감도 점검",
    ),
    "정보의-기록": (
        "봄철 지역 행사 참여 전 필수 체크리스트",
        "주말 외출 동선 계획을 빠르게 만드는 방법",
        "대중교통·주차·혼잡도 정보를 한 번에 확인하는 법",
    ),
    "미스테리아-스토리": (
        "Dyatlov Pass 자료 재검토: 사실과 가설 분리",
        "Flannan Isles 실종 사건 기록 비교",
        "Hinterkaifeck 수사 타임라인 재구성",
    ),
}


def _topic_matches_category(*, category_slug: str, keyword: str) -> bool:
    lowered = keyword.lower()
    if category_slug != "미스테리아-스토리" and any(term in lowered for term in MYSTERY_BLOCK_TERMS):
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
    small_stage_model = (
        (settings_map.get("openai_text_model") or runtime.openai_text_model or "").strip()
        or FREE_TIER_DEFAULT_SMALL_TEXT_MODEL
    )
    return (
        large_stage_model,  # topic discovery
        large_stage_model,  # article generation
        small_stage_model,  # image prompt generation
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
    ("missing_summary_section", ("핵심 요약", "요약", "tl;dr")),
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
    per_category: int = 2,
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
                        allow_large=False,
                        stage_name="image_prompt_generation",
                    )
                prompt_provider = get_article_provider(db, model_override=prompt_model, allow_large=False)
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
