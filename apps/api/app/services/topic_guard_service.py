from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from slugify import slugify
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import Article, Blog, BloggerPost, PostStatus, SyncedBloggerPost, TopicMemory
from app.schemas.ai import TopicClassificationOutput, TopicDiscoveryItem
from app.services.openai_usage_service import resolve_free_tier_text_model
from app.services.providers.base import ProviderRuntimeError
from app.services.providers.factory import get_runtime_config
from app.services.settings_service import get_settings_map

ANGLE_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("schedule_info", "일정 안내", ("schedule", "date", "dates", "calendar", "opening hours", "tide time", "tide times", "when", "라인업", "일정", "시간", "날짜")),
    ("crowd_tips", "혼잡 회피 팁", ("crowd", "busy", "avoid", "tip", "tips", "queue", "survival", "must know", "혼잡", "붐비", "피하", "팁")),
    ("transport_parking", "교통/주차", ("parking", "traffic", "transport", "subway", "bus", "drive", "driving", "how to get", "주차", "교통", "가는 법", "지하철")),
    ("tickets_booking", "예매/티켓", ("ticket", "tickets", "booking", "book", "reservation", "presale", "티켓", "예매", "예약")),
    ("food_course", "맛집/코스", ("restaurant", "restaurants", "cafe", "cafes", "food", "eat", "course", "itinerary", "맛집", "카페", "코스")),
    ("review_highlights", "후기/리뷰", ("review", "reviews", "recap", "highlight", "highlights", "photo spot", "best moments", "후기", "리뷰", "볼거리")),
)

ANGLE_STRIP_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(schedule|dates?|calendar|opening hours|tide times?|when)\b",
        r"\b(crowd|busy|avoid|tips?|queue|survival|must know)\b",
        r"\b(parking|traffic|transport|subway|bus|driv(?:e|ing)|how to get)\b",
        r"\b(ticket|tickets|booking|book|reservation|presale)\b",
        r"\b(restaurants?|cafes?|food|eat|course|itinerary)\b",
        r"\b(review|reviews|recap|highlights?|photo spots?|best moments)\b",
        r"\b(guide|travel guide|ultimate|local guide|what to know|explained|tips and tricks)\b",
        r"\b(일정|시간|날짜|혼잡|팁|주차|교통|가는 법|예매|예약|맛집|카페|코스|후기|리뷰)\b",
    )
)

YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")
DELIMITER_SPLIT_PATTERN = re.compile(r"\s*(?:[:|\-]|[|])\s*")
WHITESPACE_PATTERN = re.compile(r"\s+")
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")

DEFAULT_CLASSIFICATION_PROMPT = """You classify blog topic intent for publishing deduplication.
Return strict JSON with keys:
- topic_cluster_label
- topic_cluster_key
- topic_angle_label
- topic_angle_key
- entity_names
- distinct_reason

Rules:
- topic_cluster_label is the shared main subject, such as an event name, concert tour, festival, attraction, or place.
- topic_angle_label is the content angle, such as schedule info, crowd tips, transport, food course, tickets, review, or general guide.
- topic_cluster_key and topic_angle_key must be lowercase kebab-safe identifiers.
- distinct_reason is one short sentence explaining the chosen angle.
- entity_names should list 1-5 concrete named entities when present.
"""

GENERAL_ANGLE_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "schedule_info",
        "Schedule / timing",
        (
            "schedule",
            "date",
            "dates",
            "calendar",
            "opening hours",
            "hours",
            "when",
            "timeline",
            "tide time",
            "tide times",
            "lineup",
            "setlist",
            "일정",
            "날짜",
            "시간",
            "기간",
            "라인업",
            "타임테이블",
        ),
    ),
    (
        "crowd_tips",
        "Crowd / survival tips",
        (
            "crowd",
            "busy",
            "avoid",
            "queue",
            "survival",
            "must know",
            "tips",
            "tip",
            "packed",
            "혼잡",
            "사람 많",
            "대기",
            "웨이팅",
            "꿀팁",
            "준비물",
        ),
    ),
    (
        "transport_parking",
        "Transport / parking",
        (
            "parking",
            "traffic",
            "transport",
            "subway",
            "bus",
            "drive",
            "driving",
            "how to get",
            "route",
            "station",
            "주차",
            "교통",
            "가는 법",
            "지하철",
            "버스",
            "동선",
        ),
    ),
    (
        "tickets_booking",
        "Tickets / booking",
        (
            "ticket",
            "tickets",
            "booking",
            "book",
            "reservation",
            "reserve",
            "presale",
            "seat",
            "예매",
            "예약",
            "티켓",
            "좌석",
            "입장료",
        ),
    ),
    (
        "food_course",
        "Food / course",
        (
            "restaurant",
            "restaurants",
            "cafe",
            "cafes",
            "food",
            "eat",
            "course",
            "itinerary",
            "맛집",
            "카페",
            "먹거리",
            "코스",
            "동선 추천",
        ),
    ),
    (
        "review_highlights",
        "Review / highlights",
        (
            "review",
            "reviews",
            "recap",
            "highlight",
            "highlights",
            "photo spot",
            "best moments",
            "후기",
            "리뷰",
            "현장",
            "포토",
            "하이라이트",
        ),
    ),
    (
        "explainer_context",
        "Explainer / context",
        (
            "what is",
            "meaning",
            "explained",
            "overview",
            "guide",
            "beginner",
            "basics",
            "정리",
            "설명",
            "의미",
            "개요",
            "입문",
            "가이드",
        ),
    ),
    (
        "update_tracker",
        "Update / latest developments",
        (
            "latest",
            "update",
            "updates",
            "news",
            "rumor",
            "rumours",
            "development",
            "breaking",
            "근황",
            "최신",
            "업데이트",
            "속보",
            "소식",
        ),
    ),
    (
        "theory_analysis",
        "Theory / analysis",
        (
            "theory",
            "analysis",
            "analyze",
            "explained",
            "evidence",
            "clue",
            "clues",
            "proof",
            "debunk",
            "해석",
            "분석",
            "가설",
            "단서",
            "증거",
            "정체",
        ),
    ),
    (
        "case_profile",
        "Case / profile",
        (
            "case",
            "story",
            "history",
            "background",
            "profile",
            "location",
            "legend",
            "myth",
            "사건",
            "배경",
            "인물",
            "장소",
            "전설",
            "괴담",
            "유래",
        ),
    ),
    (
        "comparison_roundup",
        "Comparison / roundup",
        (
            "compare",
            "comparison",
            "vs",
            "versus",
            "best",
            "top",
            "roundup",
            "추천",
            "비교",
            "순위",
            "베스트",
            "top 10",
        ),
    ),
)

GENERAL_ANGLE_PRIORITY: dict[str, int] = {
    "theory_analysis": 90,
    "comparison_roundup": 80,
    "update_tracker": 70,
    "case_profile": 60,
    "schedule_info": 50,
    "crowd_tips": 50,
    "transport_parking": 50,
    "tickets_booking": 50,
    "food_course": 40,
    "review_highlights": 40,
    "explainer_context": 30,
}

GENERAL_ANGLE_STRIP_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(schedule|dates?|calendar|opening hours|hours|when|timeline|lineup|setlist|tide times?)\b",
        r"\b(crowd|busy|avoid|tips?|queue|survival|must know|packed)\b",
        r"\b(parking|traffic|transport|subway|bus|driv(?:e|ing)|how to get|route|station)\b",
        r"\b(ticket|tickets|booking|book|reservation|reserve|presale|seat)\b",
        r"\b(restaurants?|cafes?|food|eat|course|itinerary)\b",
        r"\b(review|reviews|recap|highlights?|photo spots?|best moments)\b",
        r"\b(what is|meaning|explained|overview|guide|beginner|basics)\b",
        r"\b(latest|update|updates|news|rumou?rs?|development|breaking)\b",
        r"\b(theory|analysis|analyze|evidence|clues?|proof|debunk)\b",
        r"\b(case|story|history|background|profile|location|legend|myth)\b",
        r"\b(compare|comparison|vs|versus|best|top|roundup)\b",
        r"\b(ultimate|complete|strongest|avoidance|survival|must-know|must know|essentials?)\b",
        r"(일정|날짜|시간|기간|라인업|타임테이블|혼잡|사람\s*많|대기|웨이팅|꿀팁|준비물|주차|교통|가는\s*법|지하철|버스|동선|예매|예약|티켓|좌석|입장료|맛집|카페|먹거리|코스|후기|리뷰|현장|포토|하이라이트|정리|설명|의미|개요|입문|가이드|근황|최신|업데이트|속보|소식|해석|분석|가설|단서|증거|정체|사건|배경|인물|장소|전설|괴담|유래|추천|비교|순위|베스트)",
    )
)

GENERAL_DEFAULT_CLASSIFICATION_PROMPT = """You classify blog topics for deduplication, scheduling, and topic-memory guards.
Return strict JSON with keys:
- topic_cluster_label
- topic_cluster_key
- topic_angle_label
- topic_angle_key
- entity_names
- distinct_reason

Rules:
- topic_cluster_label is the shared main subject that would make two posts feel like they are about the same thing.
- topic_cluster_label can be an event, festival, concert tour, place, attraction, case name, legend, person, creature, documentary subject, franchise, product, destination, or named issue.
- topic_angle_label is the editorial angle that makes one post meaningfully different from another.
- topic_angle_label can be schedule info, crowd tips, transport, tickets, review, explainer, update, theory analysis, case profile, comparison, beginner guide, or another concise angle when those fit better.
- topic_cluster_key and topic_angle_key must be lowercase kebab-case identifiers.
- distinct_reason must be one short sentence explaining why this angle is different.
- entity_names should list 1-5 concrete named entities when present.
- Prefer the most reusable subject phrase for topic_cluster_label. Remove years or generic filler unless they are essential to identity.
- For mystery, documentary, folklore, and investigative topics, separate the subject from the angle. Example: "Dyatlov Pass" can have angles like timeline, theories, evidence review, or travel location guide.
"""


@dataclass(slots=True)
class TopicDescriptor:
    topic_cluster_key: str
    topic_cluster_label: str
    topic_angle_key: str
    topic_angle_label: str
    entity_names: list[str]
    evidence_excerpt: str
    distinct_reason: str


@dataclass(slots=True)
class TopicGuardConflict:
    title: str
    published_at: str | None
    topic_cluster_label: str
    topic_angle_label: str


@dataclass(slots=True)
class TopicGuardViolation:
    reason_code: str
    message: str
    conflicts: list[TopicGuardConflict]


class TopicGuardConflictError(ValueError):
    def __init__(self, violation: TopicGuardViolation) -> None:
        super().__init__(violation.message)
        self.violation = violation

    def to_detail(self) -> dict:
        return {
            "message": self.violation.message,
            "reason_code": self.violation.reason_code,
            "conflicts": [
                {
                    "title": item.title,
                    "published_at": item.published_at,
                    "topic_cluster_label": item.topic_cluster_label,
                    "topic_angle_label": item.topic_angle_label,
                }
                for item in self.violation.conflicts
            ],
        }


def _normalize_key(value: str | None, fallback: str = "general") -> str:
    normalized = slugify(value or "", separator="-")
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    return normalized or fallback


def _plain_text(value: str | None) -> str:
    cleaned = HTML_TAG_PATTERN.sub(" ", value or "")
    cleaned = WHITESPACE_PATTERN.sub(" ", cleaned).strip()
    return cleaned


def _trim_excerpt(value: str, limit: int = 220) -> str:
    if len(value) <= limit:
        return value
    shortened = value[: limit + 1]
    return (shortened.rsplit(" ", 1)[0].strip() or shortened[:limit].strip()).rstrip(" ,.;:-") + "..."


def _detect_angle(text: str) -> tuple[str, str]:
    normalized = _normalize_key(text, fallback="")
    compact = normalized.replace("-", " ")
    lowered = (text or "").lower()
    best_match: tuple[str, str] | None = None
    best_priority = -1
    best_score = 0
    for key, label, keywords in GENERAL_ANGLE_RULES:
        score = sum(1 for keyword in keywords if keyword.lower() in lowered or keyword.lower() in compact)
        priority = GENERAL_ANGLE_PRIORITY.get(key, 0)
        if score > best_score or (score == best_score and score > 0 and priority > best_priority):
            best_match = (key, label)
            best_score = score
            best_priority = priority
    if best_match is not None:
        return best_match
    return "general_guide", "General guide"


def _remove_angle_terms(value: str) -> str:
    stripped = value
    for pattern in GENERAL_ANGLE_STRIP_PATTERNS:
        stripped = pattern.sub(" ", stripped)
    stripped = YEAR_PATTERN.sub(" ", stripped)
    stripped = re.sub(r"[()\\[\\],/&]+", " ", stripped)
    stripped = WHITESPACE_PATTERN.sub(" ", stripped).strip(" -:|")
    return stripped.strip()


def _extract_cluster_label(title: str, text: str) -> str:
    title = (title or "").strip()
    if not title:
        return "General Topic"

    split_parts = [part.strip() for part in DELIMITER_SPLIT_PATTERN.split(title) if part.strip()]
    if split_parts:
        primary = split_parts[0]
        cleaned_primary = _remove_angle_terms(primary)
        if cleaned_primary:
            return cleaned_primary

    cleaned_title = _remove_angle_terms(title)
    if cleaned_title:
        return cleaned_title

    cleaned_text = _remove_angle_terms(text)
    if cleaned_text:
        return cleaned_text[:255]
    return title[:255]


def _extract_entities(cluster_label: str, labels: list[str]) -> list[str]:
    entities: list[str] = []
    if cluster_label:
        entities.append(cluster_label)
    for label in labels:
        clean = label.strip()
        if clean and clean not in entities:
            entities.append(clean)
        if len(entities) >= 5:
            break
    return entities


def _load_blog(db: Session, blog_id: int | None) -> Blog | None:
    if blog_id is None:
        return None
    return db.get(Blog, blog_id)


def _blog_context_lines(blog: Blog | None) -> str:
    if blog is None:
        return ""

    lines = [
        f"Blog profile key: {(blog.profile_key or 'custom').strip()}",
        f"Content category: {(blog.content_category or 'custom').strip()}",
        f"Primary language: {(blog.primary_language or 'unknown').strip()}",
    ]
    if (blog.name or "").strip():
        lines.append(f"Blog name: {blog.name.strip()}")
    if (blog.description or "").strip():
        lines.append(f"Blog description: {_trim_excerpt(_plain_text(blog.description), limit=220)}")
    if (blog.target_audience or "").strip():
        lines.append(f"Target audience: {blog.target_audience.strip()}")
    if (blog.content_brief or "").strip():
        lines.append(f"Content brief: {_trim_excerpt(_plain_text(blog.content_brief), limit=320)}")
    return "\n".join(lines)


def _prompt_path() -> Path:
    return Path(settings.prompt_root) / "topic_memory_classification.md"


def _classification_prompt() -> str:
    path = _prompt_path()
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return GENERAL_DEFAULT_CLASSIFICATION_PROMPT


def _build_llm_payload(title: str, excerpt: str, labels: list[str], content_html: str, blog: Blog | None = None) -> str:
    excerpt_text = _trim_excerpt(_plain_text(excerpt or content_html))
    content_snippet = _trim_excerpt(_plain_text(content_html), limit=500)
    labels_text = ", ".join(labels or [])
    blog_context = _blog_context_lines(blog)
    return (
        f"{_classification_prompt()}\n\n"
        f"{blog_context}\n"
        f"Title: {title.strip()}\n"
        f"Excerpt: {excerpt_text}\n"
        f"Labels: {labels_text}\n"
        f"Content snippet: {content_snippet}\n"
    )


def _classify_with_openai(api_key: str, model: str, prompt: str) -> TopicClassificationOutput:
    response = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "Return strict JSON only."},
                {"role": "user", "content": prompt},
            ],
        },
        timeout=60.0,
    )
    if not response.is_success:
        raise ProviderRuntimeError(
            provider="openai_text",
            message="OpenAI topic classification failed.",
            status_code=response.status_code,
            detail=response.text,
        )
    payload = response.json()["choices"][0]["message"]["content"]
    return TopicClassificationOutput.model_validate_json(payload)


def _classify_with_gemini(api_key: str, model: str, prompt: str) -> TopicClassificationOutput:
    response = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
        json={
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
        },
        timeout=60.0,
    )
    if not response.is_success:
        raise ProviderRuntimeError(
            provider="gemini",
            message="Gemini topic classification failed.",
            status_code=response.status_code,
            detail=response.text,
        )
    payload = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    return TopicClassificationOutput.model_validate_json(payload)


def _heuristic_descriptor(
    title: str,
    excerpt: str = "",
    labels: list[str] | None = None,
    content_html: str = "",
    blog: Blog | None = None,
) -> TopicDescriptor:
    labels = labels or []
    combined = " ".join(
        part
        for part in [
            title,
            excerpt,
            " ".join(labels),
            _plain_text(content_html),
        ]
        if part
    ).strip()
    angle_key, angle_label = _detect_angle(combined)
    cluster_label = _extract_cluster_label(title, combined)
    cluster_key = _normalize_key(cluster_label, fallback=_normalize_key(title, fallback="general-topic"))
    angle_key = _normalize_key(angle_key, fallback="general-guide")
    evidence_excerpt = _trim_excerpt(_plain_text(excerpt) or _plain_text(content_html) or title)
    return TopicDescriptor(
        topic_cluster_key=cluster_key,
        topic_cluster_label=cluster_label[:255],
        topic_angle_key=angle_key,
        topic_angle_label=angle_label[:255],
        entity_names=_extract_entities(cluster_label, labels),
        evidence_excerpt=evidence_excerpt,
        distinct_reason=f"Classified '{cluster_label}' under the '{angle_label}' angle.",
    )


def infer_topic_descriptor(
    db: Session,
    *,
    title: str,
    excerpt: str = "",
    labels: list[str] | None = None,
    content_html: str = "",
    blog: Blog | None = None,
    blog_id: int | None = None,
    prefer_llm: bool = True,
) -> TopicDescriptor:
    labels = labels or []
    resolved_blog = blog or _load_blog(db, blog_id)
    runtime = get_runtime_config(db)
    prompt = _build_llm_payload(title, excerpt, labels, content_html, resolved_blog)

    try:
        if prefer_llm and runtime.provider_mode == "live" and runtime.openai_api_key:
            output = _classify_with_openai(
                runtime.openai_api_key,
                resolve_free_tier_text_model(runtime.openai_text_model, allow_large=False),
                prompt,
            )
            return TopicDescriptor(
                topic_cluster_key=_normalize_key(output.topic_cluster_key or output.topic_cluster_label, fallback="general-topic"),
                topic_cluster_label=(output.topic_cluster_label or title).strip()[:255],
                topic_angle_key=_normalize_key(output.topic_angle_key or output.topic_angle_label, fallback="general-guide"),
                topic_angle_label=(output.topic_angle_label or "General guide").strip()[:255],
                entity_names=[item.strip() for item in output.entity_names if item.strip()][:5],
                evidence_excerpt=_trim_excerpt(_plain_text(excerpt) or _plain_text(content_html) or title),
                distinct_reason=(output.distinct_reason or "").strip(),
            )
        if prefer_llm and runtime.provider_mode == "live" and runtime.gemini_api_key:
            output = _classify_with_gemini(runtime.gemini_api_key, runtime.gemini_model, prompt)
            return TopicDescriptor(
                topic_cluster_key=_normalize_key(output.topic_cluster_key or output.topic_cluster_label, fallback="general-topic"),
                topic_cluster_label=(output.topic_cluster_label or title).strip()[:255],
                topic_angle_key=_normalize_key(output.topic_angle_key or output.topic_angle_label, fallback="general-guide"),
                topic_angle_label=(output.topic_angle_label or "General guide").strip()[:255],
                entity_names=[item.strip() for item in output.entity_names if item.strip()][:5],
                evidence_excerpt=_trim_excerpt(_plain_text(excerpt) or _plain_text(content_html) or title),
                distinct_reason=(output.distinct_reason or "").strip(),
            )
    except Exception:
        pass

    return _heuristic_descriptor(title, excerpt, labels, content_html, resolved_blog)


def _settings_bundle(db: Session) -> tuple[dict[str, str], ZoneInfo]:
    settings_map = get_settings_map(db)
    timezone_name = settings_map.get("schedule_timezone", settings.schedule_timezone)
    return settings_map, ZoneInfo(timezone_name)


def _bool_setting(raw: str | None, default: bool = True) -> bool:
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _int_setting(raw: str | None, default: int) -> int:
    try:
        parsed = int(str(raw if raw is not None else default).strip())
    except (TypeError, ValueError):
        return default
    return max(parsed, 0)


def rebuild_topic_memories_for_blog(db: Session, blog: Blog) -> None:
    db.execute(delete(TopicMemory).where(TopicMemory.blog_id == blog.id))

    synced_posts = db.execute(
        select(SyncedBloggerPost).where(SyncedBloggerPost.blog_id == blog.id)
    ).scalars().all()
    generated_rows = db.execute(
        select(BloggerPost, Article)
        .join(Article, Article.id == BloggerPost.article_id)
        .where(
            BloggerPost.blog_id == blog.id,
            BloggerPost.post_status.in_((PostStatus.SCHEDULED, PostStatus.PUBLISHED)),
        )
    ).all()

    for post in synced_posts:
        descriptor = infer_topic_descriptor(
            db,
            title=post.title,
            excerpt=post.excerpt_text,
            labels=list(post.labels or []),
            content_html=post.content_html,
            blog=blog,
            prefer_llm=False,
        )
        db.add(
            TopicMemory(
                blog_id=blog.id,
                source_type="synced",
                source_id=post.remote_post_id,
                title=post.title,
                canonical_url=(post.url or "").strip() or None,
                published_at=post.published_at,
                topic_cluster_key=descriptor.topic_cluster_key,
                topic_cluster_label=descriptor.topic_cluster_label,
                topic_angle_key=descriptor.topic_angle_key,
                topic_angle_label=descriptor.topic_angle_label,
                entity_names=descriptor.entity_names,
                evidence_excerpt=descriptor.evidence_excerpt,
            )
        )

    for blogger_post, article in generated_rows:
        descriptor = infer_topic_descriptor(
            db,
            title=article.title,
            excerpt=article.excerpt,
            labels=list(article.labels or []),
            content_html=article.assembled_html or article.html_article,
            blog=blog,
            prefer_llm=False,
        )
        db.add(
            TopicMemory(
                blog_id=blog.id,
                source_type="generated",
                source_id=blogger_post.blogger_post_id,
                title=article.title,
                canonical_url=(blogger_post.published_url or "").strip() or None,
                published_at=blogger_post.scheduled_for or blogger_post.published_at,
                topic_cluster_key=descriptor.topic_cluster_key,
                topic_cluster_label=descriptor.topic_cluster_label,
                topic_angle_key=descriptor.topic_angle_key,
                topic_angle_label=descriptor.topic_angle_label,
                entity_names=descriptor.entity_names,
                evidence_excerpt=descriptor.evidence_excerpt,
            )
        )

    db.commit()


def backfill_missing_topic_memories(db: Session) -> None:
    blogs = db.execute(select(Blog).order_by(Blog.id.asc())).scalars().all()
    for blog in blogs:
        existing_count = db.execute(
            select(func.count(TopicMemory.id)).where(TopicMemory.blog_id == blog.id)
        ).scalar_one()
        if existing_count:
            continue
        synced_count = db.execute(
            select(func.count(SyncedBloggerPost.id)).where(SyncedBloggerPost.blog_id == blog.id)
        ).scalar_one()
        generated_count = db.execute(
            select(func.count(BloggerPost.id)).where(
                BloggerPost.blog_id == blog.id,
                BloggerPost.post_status.in_((PostStatus.SCHEDULED, PostStatus.PUBLISHED)),
            )
        ).scalar_one()
        if int(synced_count or 0) or int(generated_count or 0):
            rebuild_topic_memories_for_blog(db, blog)


def list_effective_topic_memories(db: Session, blog_id: int) -> list[TopicMemory]:
    items = db.execute(
        select(TopicMemory)
        .where(TopicMemory.blog_id == blog_id)
        .order_by(TopicMemory.published_at.desc().nullslast(), TopicMemory.id.desc())
    ).scalars().all()

    deduped: list[TopicMemory] = []
    seen: set[str] = set()
    for item in items:
        key = (item.canonical_url or "").strip().lower() or f"{item.source_type}:{item.source_id}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def build_topic_memory_exclusion_prompt(db: Session, *, blog_id: int, limit: int = 12) -> str:
    items = list_effective_topic_memories(db, blog_id)[:limit]
    if not items:
        return ""
    bullet_list = "\n".join(
        f"- {item.topic_cluster_label} | {item.topic_angle_label} | {(item.published_at or datetime.now(timezone.utc)).date().isoformat()}"
        for item in items
    )
    return (
        "\n\nAvoid main subjects and angles that this blog already published or scheduled recently.\n"
        "Existing public coverage memory:\n"
        f"{bullet_list}"
    )


def annotate_topic_items(
    db: Session,
    *,
    blog: Blog | None = None,
    items: list[TopicDiscoveryItem],
) -> dict[str, TopicDescriptor]:
    annotated: dict[str, TopicDescriptor] = {}
    for item in items:
        annotated[item.keyword] = infer_topic_descriptor(db, title=item.keyword, blog=blog)
    return annotated


def _local_date(value: datetime | None, tz: ZoneInfo) -> str | None:
    if value is None:
        return None
    current = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return current.astimezone(tz).date().isoformat()


def evaluate_topic_guard(
    db: Session,
    *,
    blog_id: int,
    descriptor: TopicDescriptor,
    target_datetime: datetime,
) -> TopicGuardViolation | None:
    settings_map, tz = _settings_bundle(db)
    if not _bool_setting(settings_map.get("topic_guard_enabled"), default=True):
        return None

    daily_limit = _int_setting(settings_map.get("publish_daily_limit_per_blog"), default=3)
    cluster_hours = _int_setting(settings_map.get("same_cluster_cooldown_hours"), default=24)
    angle_days = _int_setting(settings_map.get("same_angle_cooldown_days"), default=7)
    target = target_datetime if target_datetime.tzinfo else target_datetime.replace(tzinfo=timezone.utc)

    items = list_effective_topic_memories(db, blog_id)
    cluster_conflicts: list[TopicGuardConflict] = []
    angle_conflicts: list[TopicGuardConflict] = []
    same_day_count = 0
    target_local_date = _local_date(target, tz)

    for item in items:
        if _local_date(item.published_at, tz) == target_local_date:
            same_day_count += 1
        if not item.published_at:
            continue
        delta = abs(target - (item.published_at if item.published_at.tzinfo else item.published_at.replace(tzinfo=timezone.utc)))
        conflict = TopicGuardConflict(
            title=item.title or item.topic_cluster_label,
            published_at=item.published_at.isoformat() if item.published_at else None,
            topic_cluster_label=item.topic_cluster_label,
            topic_angle_label=item.topic_angle_label,
        )
        if item.topic_cluster_key == descriptor.topic_cluster_key and delta < timedelta(hours=cluster_hours):
            cluster_conflicts.append(conflict)
        elif (
            item.topic_cluster_key == descriptor.topic_cluster_key
            and item.topic_angle_key == descriptor.topic_angle_key
            and delta < timedelta(days=angle_days)
        ):
            angle_conflicts.append(conflict)

    if cluster_conflicts:
        return TopicGuardViolation(
            reason_code="cluster_recently_published",
            message="같은 메인 주제의 글이 최근 24시간 안에 이미 공개 또는 예약되어 있습니다.",
            conflicts=cluster_conflicts[:3],
        )
    if angle_conflicts:
        return TopicGuardViolation(
            reason_code="same_angle_cooldown",
            message="같은 메인 주제와 같은 각도의 글이 아직 쿨다운 기간 안에 있습니다.",
            conflicts=angle_conflicts[:3],
        )
    if daily_limit and same_day_count >= daily_limit:
        return TopicGuardViolation(
            reason_code="daily_publish_limit_reached",
            message="이 블로그는 해당 날짜에 이미 허용된 발행 수를 모두 사용했습니다.",
            conflicts=[],
        )
    return None


def assert_topic_guard(
    db: Session,
    *,
    blog_id: int,
    descriptor: TopicDescriptor,
    target_datetime: datetime,
) -> None:
    violation = evaluate_topic_guard(db, blog_id=blog_id, descriptor=descriptor, target_datetime=target_datetime)
    if violation:
        raise TopicGuardConflictError(violation)


def current_publish_target_datetime(db: Session) -> datetime:
    _, tz = _settings_bundle(db)
    return datetime.now(tz).astimezone(timezone.utc)


def validate_candidate_topic(
    db: Session,
    *,
    blog_id: int,
    title: str,
    excerpt: str = "",
    labels: list[str] | None = None,
    content_html: str = "",
    target_datetime: datetime | None = None,
) -> TopicDescriptor:
    descriptor = infer_topic_descriptor(
        db,
        title=title,
        excerpt=excerpt,
        labels=labels,
        content_html=content_html,
        blog_id=blog_id,
    )
    assert_topic_guard(
        db,
        blog_id=blog_id,
        descriptor=descriptor,
        target_datetime=target_datetime or current_publish_target_datetime(db),
    )
    return descriptor
