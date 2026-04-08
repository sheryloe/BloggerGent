from __future__ import annotations

import calendar
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Iterable

import httpx
from sqlalchemy import and_
from sqlalchemy.orm import Session, joinedload

from app.models.entities import (
    AnalyticsArticleFact,
    AnalyticsBlogMonthlyReport,
    AnalyticsThemeMonthlyStat,
    Article,
    Blog,
    BlogTheme,
    ContentPlanDay,
    ContentPlanSlot,
    PlannerBriefRun,
    PublishMode,
    Topic,
    WorkflowStageType,
)
from app.schemas.api import (
    PlannerBriefRunRead,
    PlannerBriefSuggestionInput,
    PlannerBriefSuggestionRead,
    PlannerCalendarRead,
    PlannerCategoryRead,
    PlannerDayRead,
    PlannerDayBriefApplyResponse,
    PlannerDayBriefAnalysisResponse,
    PlannerMonthPlanRequest,
    PlannerSlotCreate,
    PlannerSlotRead,
    PlannerSlotUpdate,
)
from app.services.cloudflare_channel_service import (
    README_V3_LEAF_WEIGHTS,
    generate_cloudflare_posts,
    get_cloudflare_overview,
    list_cloudflare_categories,
)
from app.services.blog_service import get_blog, get_workflow_step, sync_stage_prompts_from_profile_files
from app.services.google_indexing_service import load_fact_enrichment_maps
from app.services.job_service import create_job
from app.services.multilingual_bundle_service import (
    bundle_publish_offset_minutes,
    default_target_audience_for_language,
    parse_planner_bundle_context,
    resolve_blog_bundle_language,
)
from app.services.platform_publish_service import content_item_missing_asset_reason
from app.services.platform_service import (
    create_content_item as create_platform_content_item,
    resolve_blogger_channel_display_name,
)
from app.services.prompt_service import get_prompt_template, render_prompt_template
from app.services.providers.base import ProviderRuntimeError
from app.services.providers.factory import get_runtime_config
from app.services.openai_usage_service import route_openai_free_tier_text_model
from app.services.settings_service import get_settings_map
from app.services.workspace_service import get_managed_channel, list_channel_categories
from app.tasks.pipeline import run_job

BLOGGER_CATEGORY_PRESETS: dict[str, list[tuple[str, str, int, str]]] = {
    "korea_travel": [
        ("travel", "Travel", 45, "#0f766e"),
        ("culture", "Culture", 30, "#7c3aed"),
        ("food", "Food", 25, "#d97706"),
    ],
    "world_mystery": [
        ("case-files", "Case Files", 45, "#7f1d1d"),
        ("mystery-archives", "Mystery Archives", 30, "#1d4ed8"),
        ("legends-lore", "Legends & Lore", 25, "#581c87"),
    ],
}

BLOGGER_WEIGHT_KEYS = {
    "korea_travel": "travel_editorial_weights",
    "world_mystery": "mystery_editorial_weights",
}

CLOUDFLARE_CATEGORY_COLORS = (
    "#2563eb",
    "#7c3aed",
    "#0f766e",
    "#d97706",
    "#dc2626",
    "#0891b2",
    "#4f46e5",
    "#9333ea",
    "#059669",
    "#ea580c",
    "#be123c",
)

READY_BRIEF_FIELDS = ("brief_topic", "brief_audience")
ACTIVE_SLOT_STATUSES = {"queued", "generating", "generated", "published", "failed", "canceled"}
MULTILINGUAL_FIXED_WORKFLOW_STAGES: tuple[WorkflowStageType, ...] = (
    WorkflowStageType.ARTICLE_GENERATION,
    WorkflowStageType.IMAGE_PROMPT_GENERATION,
    WorkflowStageType.IMAGE_GENERATION,
    WorkflowStageType.HTML_ASSEMBLY,
    WorkflowStageType.PUBLISHING,
)
PLANNER_DAILY_BRIEF_PROMPT_KEY = "planner_daily_brief_analysis"
BRIEF_APPLY_FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("brief_topic", "topic"),
    ("brief_audience", "audience"),
    ("brief_information_level", "information_level"),
    ("brief_extra_context", "extra_context"),
)


@dataclass(frozen=True, slots=True)
class PlannerCategoryDefinition:
    key: str
    name: str
    weight: int
    color: str | None
    sort_order: int
    is_active: bool = True


@dataclass(slots=True)
class PlannerChannelContext:
    channel_id: str
    provider: str
    channel_name: str
    categories: list[PlannerCategoryDefinition]
    blog: Blog | None = None

    @property
    def blog_id(self) -> int | None:
        return self.blog.id if self.blog else None


def _month_bounds(month: str) -> tuple[date, date]:
    start = datetime.strptime(f"{month}-01", "%Y-%m-%d").date()
    _, last_day = calendar.monthrange(start.year, start.month)
    return start, date(start.year, start.month, last_day)


def _plan_day_options():
    return (
        joinedload(ContentPlanDay.blog),
        joinedload(ContentPlanDay.slots).joinedload(ContentPlanSlot.theme),
        joinedload(ContentPlanDay.slots).joinedload(ContentPlanSlot.article).joinedload(Article.blogger_post),
    )


def _parse_clock(value: str | None, fallback: time) -> time:
    if not value:
        return fallback
    try:
        parsed = datetime.strptime(value, "%H:%M").time()
    except ValueError:
        return fallback
    return parsed.replace(second=0, microsecond=0)


def _normalize_weight_key(value: str) -> str:
    return "-".join(part for part in "".join(ch.lower() if ch.isalnum() else "-" for ch in (value or "")).split("-") if part)


def _parse_weight_overrides(raw_value: str | None, defaults: list[tuple[str, str, int, str]]) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for chunk in str(raw_value or "").split(","):
        part = chunk.strip()
        if not part or ":" not in part:
            continue
        label, weight_text = part.split(":", maxsplit=1)
        key = _normalize_weight_key(label)
        try:
            weight = int(weight_text.strip())
        except ValueError:
            continue
        if key and weight > 0:
            parsed[key] = weight
    if parsed:
        return parsed
    return {key: weight for key, _label, weight, _color in defaults}


def _load_legacy_blog_themes(db: Session, blog_id: int) -> list[BlogTheme]:
    return (
        db.query(BlogTheme)
        .filter(BlogTheme.blog_id == blog_id)
        .order_by(BlogTheme.sort_order.asc(), BlogTheme.id.asc())
        .all()
    )


def _build_blogger_categories(db: Session, blog: Blog, settings_map: dict[str, str]) -> list[PlannerCategoryDefinition]:
    preset = BLOGGER_CATEGORY_PRESETS.get(blog.profile_key or "")
    if preset:
        weight_map = _parse_weight_overrides(settings_map.get(BLOGGER_WEIGHT_KEYS.get(blog.profile_key or "", "")), preset)
        return [
            PlannerCategoryDefinition(
                key=key,
                name=name,
                weight=max(weight_map.get(key, default_weight), 1),
                color=color,
                sort_order=index,
                is_active=True,
            )
            for index, (key, name, default_weight, color) in enumerate(preset, start=1)
        ]

    legacy_themes = [item for item in _load_legacy_blog_themes(db, blog.id) if item.is_active]
    if legacy_themes:
        return [
            PlannerCategoryDefinition(
                key=item.key,
                name=item.name,
                weight=max(int(item.weight or 1), 1),
                color=item.color,
                sort_order=int(item.sort_order or 0),
                is_active=bool(item.is_active),
            )
            for item in legacy_themes
        ]

    fallback_key = _normalize_weight_key(blog.content_category or "general") or "general"
    fallback_name = (blog.content_category or "General").replace("-", " ").title()
    return [PlannerCategoryDefinition(key=fallback_key, name=fallback_name, weight=1, color="#475569", sort_order=1)]


def _sync_legacy_blogger_themes(
    db: Session,
    *,
    blog: Blog,
    categories: list[PlannerCategoryDefinition],
) -> dict[str, BlogTheme]:
    existing = _load_legacy_blog_themes(db, blog.id)
    by_key = {item.key: item for item in existing}
    desired_keys = {item.key for item in categories}
    changed = False

    for index, category in enumerate(categories, start=1):
        theme = by_key.get(category.key)
        if theme is None:
            theme = BlogTheme(
                blog_id=blog.id,
                key=category.key,
                name=category.name,
                weight=category.weight,
                color=category.color,
                sort_order=index,
                is_active=category.is_active,
            )
            db.add(theme)
            existing.append(theme)
            changed = True
            continue
        if theme.name != category.name:
            theme.name = category.name
            changed = True
        if int(theme.weight or 0) != int(category.weight):
            theme.weight = category.weight
            changed = True
        if theme.color != category.color:
            theme.color = category.color
            changed = True
        if int(theme.sort_order or 0) != index:
            theme.sort_order = index
            changed = True
        if bool(theme.is_active) != bool(category.is_active):
            theme.is_active = category.is_active
            changed = True

    for theme in existing:
        if theme.key not in desired_keys and theme.is_active:
            theme.is_active = False
            changed = True

    if changed:
        db.flush()

    return {item.key: item for item in existing if item.key in desired_keys}


def _build_cloudflare_categories(db: Session) -> list[PlannerCategoryDefinition]:
    leaf_categories = [item for item in list_cloudflare_categories(db) if bool(item.get("isLeaf"))]
    return [
        PlannerCategoryDefinition(
            key=str(item.get("slug") or "").strip(),
            name=str(item.get("name") or item.get("slug") or "").strip(),
            weight=max(int(README_V3_LEAF_WEIGHTS.get(str(item.get("slug") or "").strip(), 1)), 1),
            color=CLOUDFLARE_CATEGORY_COLORS[(index - 1) % len(CLOUDFLARE_CATEGORY_COLORS)],
            sort_order=index,
            is_active=True,
        )
        for index, item in enumerate(leaf_categories, start=1)
        if str(item.get("slug") or "").strip()
    ]


def _parse_channel_id(channel_id: str) -> tuple[str, str]:
    normalized = str(channel_id or "").strip()
    if ":" not in normalized:
        raise ValueError("channel_id must include provider prefix")
    provider, raw_id = normalized.split(":", 1)
    if provider not in {"blogger", "cloudflare", "youtube", "instagram"} or not raw_id.strip():
        raise ValueError("unsupported channel_id")
    return provider, raw_id.strip()


def _normalize_channel_id(*, channel_id: str | None = None, blog_id: int | None = None) -> str:
    if channel_id:
        return str(channel_id).strip()
    if blog_id is not None:
        return f"blogger:{int(blog_id)}"
    raise ValueError("channel_id or blog_id is required")


def _resolve_channel_context(
    db: Session,
    *,
    channel_id: str | None = None,
    blog_id: int | None = None,
    settings_map: dict[str, str] | None = None,
) -> PlannerChannelContext:
    normalized_channel_id = _normalize_channel_id(channel_id=channel_id, blog_id=blog_id)
    provider, raw_id = _parse_channel_id(normalized_channel_id)
    current_settings = settings_map or get_settings_map(db)

    if provider == "blogger":
        blog = db.query(Blog).filter(Blog.id == int(raw_id)).one()
        categories = _build_blogger_categories(db, blog, current_settings)
        _sync_legacy_blogger_themes(db, blog=blog, categories=categories)
        return PlannerChannelContext(
            channel_id=normalized_channel_id,
            provider="blogger",
            channel_name=resolve_blogger_channel_display_name(blog),
            categories=categories,
            blog=blog,
        )

    if provider in {"youtube", "instagram"}:
        channel = get_managed_channel(db, normalized_channel_id)
        if channel is None:
            raise ValueError("managed channel not found")
        categories = [
            PlannerCategoryDefinition(
                key=item["key"],
                name=item["name"],
                weight=max(int(item.get("weight") or 1), 1),
                color=item.get("color"),
                sort_order=int(item.get("sort_order") or 0),
                is_active=bool(item.get("is_active", True)),
            )
            for item in list_channel_categories(channel)
        ]
        return PlannerChannelContext(
            channel_id=normalized_channel_id,
            provider=provider,
            channel_name=channel.display_name,
            categories=categories,
            blog=channel.linked_blog,
        )

    overview = get_cloudflare_overview(db)
    resolved_id = str(overview.get("channel_id") or "").strip()
    if raw_id != resolved_id:
        raise ValueError("cloudflare channel not found")
    categories = _build_cloudflare_categories(db)
    return PlannerChannelContext(
        channel_id=normalized_channel_id,
        provider="cloudflare",
        channel_name=overview.get("channel_name") or overview.get("site_title") or "Dongri Archive",
        categories=categories,
        blog=None,
    )

def _category_lookup(categories: Iterable[PlannerCategoryDefinition]) -> dict[str, PlannerCategoryDefinition]:
    return {item.key: item for item in categories}


def _select_category(context: PlannerChannelContext, category_key: str) -> PlannerCategoryDefinition:
    candidate = _category_lookup(context.categories).get(category_key)
    if candidate is None:
        raise ValueError("planner category not found")
    return candidate


def _slot_category_key(slot: ContentPlanSlot) -> str | None:
    return slot.category_key or (slot.theme.key if slot.theme else None)


def _slot_category_name(slot: ContentPlanSlot) -> str | None:
    return slot.category_name or (slot.theme.name if slot.theme else None)


def _slot_category_color(slot: ContentPlanSlot) -> str | None:
    return slot.category_color or (slot.theme.color if slot.theme else None)


def _slot_publish_mode(slot: ContentPlanSlot) -> str | None:
    if isinstance(slot.result_payload, dict):
        requested_status = slot.result_payload.get("requested_status")
        if requested_status:
            return str(requested_status)
    if slot.plan_day.blog and slot.plan_day.blog.publish_mode:
        return slot.plan_day.blog.publish_mode.value if hasattr(slot.plan_day.blog.publish_mode, "value") else str(slot.plan_day.blog.publish_mode)
    return "draft"


def _slot_status(slot: ContentPlanSlot) -> str:
    if slot.status in ACTIVE_SLOT_STATUSES:
        return slot.status
    ready = slot.scheduled_for and _slot_category_key(slot) and all(getattr(slot, field) for field in READY_BRIEF_FIELDS)
    return "brief_ready" if ready else "planned"


def _serialize_category(category: PlannerCategoryDefinition) -> PlannerCategoryRead:
    return PlannerCategoryRead(
        key=category.key,
        name=category.name,
        weight=category.weight,
        color=category.color,
        sort_order=category.sort_order,
        is_active=category.is_active,
    )


def _serialize_slot(slot: ContentPlanSlot) -> PlannerSlotRead:
    result_payload = slot.result_payload if isinstance(slot.result_payload, dict) else {}
    result_quality = result_payload.get("quality_gate") if isinstance(result_payload.get("quality_gate"), dict) else {}
    result_scores = result_quality.get("scores") if isinstance(result_quality.get("scores"), dict) else {}

    article_publish_status = None
    article_published_url = None
    if slot.article and slot.article.blogger_post:
        article_publish_status = (
            slot.article.blogger_post.post_status.value
            if hasattr(slot.article.blogger_post.post_status, "value")
            else str(slot.article.blogger_post.post_status)
        )
        article_published_url = slot.article.blogger_post.published_url

    quality_gate_status = None
    if slot.article and slot.article.quality_status:
        quality_gate_status = slot.article.quality_status
    elif result_quality:
        quality_gate_status = "passed" if bool(result_quality.get("passed")) else "failed"

    return PlannerSlotRead(
        id=slot.id,
        plan_day_id=slot.plan_day_id,
        channel_id=slot.plan_day.channel_id,
        publish_mode=_slot_publish_mode(slot),
        theme_id=slot.theme_id,
        theme_key=slot.theme.key if slot.theme else None,
        theme_name=slot.theme.name if slot.theme else None,
        category_key=_slot_category_key(slot),
        category_name=_slot_category_name(slot),
        category_color=_slot_category_color(slot),
        scheduled_for=slot.scheduled_for.isoformat() if slot.scheduled_for else None,
        slot_order=slot.slot_order,
        status=_slot_status(slot),
        brief_topic=slot.brief_topic,
        brief_audience=slot.brief_audience,
        brief_information_level=slot.brief_information_level,
        brief_extra_context=slot.brief_extra_context,
        article_id=slot.article_id,
        job_id=slot.job_id,
        error_message=slot.error_message,
        last_run_at=slot.last_run_at.isoformat() if slot.last_run_at else None,
        article_title=slot.article.title if slot.article else None,
        article_seo_score=slot.article.quality_seo_score if slot.article else result_scores.get("seo_score"),
        article_geo_score=slot.article.quality_geo_score if slot.article else result_scores.get("geo_score"),
        article_similarity_score=slot.article.quality_similarity_score if slot.article else result_scores.get("similarity_score"),
        article_most_similar_url=slot.article.quality_most_similar_url if slot.article else result_scores.get("most_similar_url"),
        article_quality_status=slot.article.quality_status if slot.article else quality_gate_status,
        article_publish_status=article_publish_status or (str(result_payload.get("status")) if result_payload.get("status") else None),
        article_published_url=article_published_url or (str(result_payload.get("public_url")) if result_payload.get("public_url") else None),
        result_title=(slot.article.title if slot.article else str(result_payload.get("title") or "").strip()) or None,
        result_url=article_published_url or (str(result_payload.get("public_url") or "").strip() or None),
        result_status=str(result_payload.get("status") or "").strip() or article_publish_status or None,
        quality_gate_status=quality_gate_status,
    )


def _serialize_day(plan_day: ContentPlanDay) -> PlannerDayRead:
    category_counter: dict[str, int] = {}
    for slot in plan_day.slots:
        key = _slot_category_key(slot)
        if not key:
            continue
        category_counter[key] = category_counter.get(key, 0) + 1
    ordered_slots = sorted(plan_day.slots, key=lambda item: (item.slot_order, item.id))
    return PlannerDayRead(
        id=plan_day.id,
        channel_id=plan_day.channel_id,
        blog_id=plan_day.blog_id,
        plan_date=plan_day.plan_date.isoformat(),
        target_post_count=plan_day.target_post_count,
        status=plan_day.status,
        slot_count=len(plan_day.slots),
        category_mix=category_counter,
        slots=[_serialize_slot(slot) for slot in ordered_slots],
    )


def _normalize_existing_slots(
    db: Session,
    *,
    context: PlannerChannelContext,
    days: list[ContentPlanDay],
) -> bool:
    valid_categories = _category_lookup(context.categories)
    category_cycle = _weighted_category_cycle(context.categories)
    if not valid_categories or not category_cycle:
        return False

    legacy_themes = _sync_legacy_blogger_themes(db, blog=context.blog, categories=context.categories) if context.blog else {}
    changed = False
    cycle_index = 0

    ordered_days = sorted(days, key=lambda item: item.plan_date)
    for plan_day in ordered_days:
        ordered_slots = sorted(
            plan_day.slots,
            key=lambda item: (item.scheduled_for or datetime.max, item.slot_order, item.id),
        )
        for slot in ordered_slots:
            fallback_category = category_cycle[cycle_index % len(category_cycle)]
            cycle_index += 1

            current_key = _slot_category_key(slot)
            category = valid_categories.get(current_key or "") or fallback_category
            legacy_theme = legacy_themes.get(category.key)
            expected_theme_id = legacy_theme.id if legacy_theme is not None else None

            if (
                current_key != category.key
                or slot.category_name != category.name
                or slot.category_color != category.color
                or slot.theme_id != expected_theme_id
            ):
                _apply_slot_category(slot, category, legacy_theme)
                if slot.status not in ACTIVE_SLOT_STATUSES:
                    slot.status = _slot_status(slot)
                changed = True

    if changed:
        db.commit()
    return changed


def _weighted_category_cycle(categories: Iterable[PlannerCategoryDefinition]) -> list[PlannerCategoryDefinition]:
    expanded: list[PlannerCategoryDefinition] = []
    active_categories = [category for category in categories if category.is_active and category.weight > 0]
    if not active_categories:
        active_categories = list(categories)
    if not active_categories:
        return []
    max_weight = max(category.weight or 1 for category in active_categories)
    for round_index in range(max_weight):
        for category in active_categories:
            if (category.weight or 1) > round_index:
                expanded.append(category)
    return expanded or active_categories


def _build_slot_times(day: date, count: int, settings_map: dict[str, str]) -> list[datetime]:
    start_clock = _parse_clock(settings_map.get("planner_day_start_time"), time(9, 0))
    end_clock = _parse_clock(settings_map.get("planner_day_end_time"), time(21, 0))
    start_dt = datetime.combine(day, start_clock)
    end_dt = datetime.combine(day, end_clock)
    if count <= 1 or end_dt <= start_dt:
        return [start_dt]
    total_seconds = int((end_dt - start_dt).total_seconds())
    interval = max(total_seconds // max(count - 1, 1), 1)
    return [start_dt + timedelta(seconds=interval * index) for index in range(count)]


def _resequence_slots(plan_day: ContentPlanDay, *, sort_by_time: bool = False) -> None:
    if sort_by_time:
        ordered = sorted(plan_day.slots, key=lambda item: (item.scheduled_for or datetime.max, item.slot_order, item.id))
    else:
        ordered = sorted(plan_day.slots, key=lambda item: (item.slot_order, item.id))
    for index, slot in enumerate(ordered, start=1):
        slot.slot_order = index


def _apply_slot_category(slot: ContentPlanSlot, category: PlannerCategoryDefinition, legacy_theme: BlogTheme | None = None) -> None:
    slot.category_key = category.key
    slot.category_name = category.name
    slot.category_color = category.color
    slot.theme_id = legacy_theme.id if legacy_theme is not None else None


def _ensure_day(
    db: Session,
    *,
    context: PlannerChannelContext,
    plan_date: date,
    target_post_count: int,
) -> ContentPlanDay:
    plan_day = (
        db.query(ContentPlanDay)
        .options(*_plan_day_options())
        .filter(ContentPlanDay.channel_id == context.channel_id, ContentPlanDay.plan_date == plan_date)
        .one_or_none()
    )
    if plan_day:
        plan_day.target_post_count = target_post_count
        if context.blog_id is not None and plan_day.blog_id != context.blog_id:
            plan_day.blog_id = context.blog_id
        return plan_day

    plan_day = ContentPlanDay(
        channel_id=context.channel_id,
        blog_id=context.blog_id,
        plan_date=plan_date,
        target_post_count=target_post_count,
        status="planned",
    )
    db.add(plan_day)
    db.flush()
    return plan_day


def _datetime_to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).isoformat()
    return value.astimezone(UTC).isoformat()


def _enforce_multilingual_blogger_setup(db: Session, blog: Blog) -> tuple[Blog, str | None]:
    hydrated_blog = get_blog(db, blog.id) or blog
    language = resolve_blog_bundle_language(hydrated_blog)
    if not language:
        return hydrated_blog, None

    changed = False
    if (hydrated_blog.primary_language or "").strip().lower() != language:
        hydrated_blog.primary_language = language
        changed = True

    default_audience = default_target_audience_for_language(language)
    if default_audience and (hydrated_blog.target_audience or "").strip() != default_audience:
        hydrated_blog.target_audience = default_audience
        changed = True

    topic_step = get_workflow_step(hydrated_blog, WorkflowStageType.TOPIC_DISCOVERY)
    if topic_step and topic_step.is_enabled:
        topic_step.is_enabled = False
        db.add(topic_step)
        changed = True

    for stage_type in MULTILINGUAL_FIXED_WORKFLOW_STAGES:
        step = get_workflow_step(hydrated_blog, stage_type)
        if not step or step.is_enabled:
            continue
        step.is_enabled = True
        db.add(step)
        changed = True

    if changed:
        db.add(hydrated_blog)
        db.commit()

    sync_stage_prompts_from_profile_files(
        db,
        blog=hydrated_blog,
        stage_types=(
            WorkflowStageType.ARTICLE_GENERATION,
            WorkflowStageType.IMAGE_PROMPT_GENERATION,
        ),
    )
    refreshed = get_blog(db, hydrated_blog.id) or hydrated_blog
    return refreshed, language


def _build_planner_brief_payload(
    *,
    slot: ContentPlanSlot,
    category_key: str | None,
    category_name: str,
    language: str | None,
) -> dict[str, Any]:
    parsed_context = parse_planner_bundle_context(slot.brief_extra_context)
    offset_minutes = bundle_publish_offset_minutes(language)
    recommended_publish_at = None
    if slot.scheduled_for is not None:
        recommended_publish_at = _datetime_to_iso(slot.scheduled_for + timedelta(minutes=offset_minutes))

    return {
        "topic": slot.brief_topic or "",
        "audience": slot.brief_audience or "",
        "information_level": slot.brief_information_level or "",
        "extra_context": slot.brief_extra_context or "",
        "category_key": category_key,
        "category_name": category_name,
        "scheduled_for": _datetime_to_iso(slot.scheduled_for),
        "bundle_key": parsed_context.bundle_key,
        "facts": parsed_context.facts,
        "prohibited_claims": parsed_context.prohibited_claims,
        "context_notes": parsed_context.notes,
        "language": language or "",
        "publish_offset_minutes": offset_minutes,
        "recommended_publish_at": recommended_publish_at,
    }


def _planner_prompt_lines(slot: ContentPlanSlot, *, blog_name: str, category_name: str) -> tuple[str, str]:
    parsed_context = parse_planner_bundle_context(slot.brief_extra_context)
    title_seed = (slot.brief_topic or "").strip() or f"{blog_name} {category_name}"
    prompt_lines = [
        f"Category: {category_name}",
        f"Topic: {slot.brief_topic or ''}",
        f"Audience: {slot.brief_audience or ''}",
    ]
    if parsed_context.bundle_key:
        prompt_lines.append(f"Bundle key: {parsed_context.bundle_key}")
    if parsed_context.facts:
        prompt_lines.append("Confirmed facts:")
        prompt_lines.extend(f"- {item}" for item in parsed_context.facts)
    if parsed_context.prohibited_claims:
        prompt_lines.append("Prohibited claims:")
        prompt_lines.extend(f"- {item}" for item in parsed_context.prohibited_claims)
    if slot.brief_information_level:
        prompt_lines.append(f"Information level: {slot.brief_information_level}")
    if parsed_context.notes:
        prompt_lines.append(f"Context notes: {parsed_context.notes}")
    prompt_lines.append("Planner mode: Use the brief exactly as the writing contract.")
    return title_seed, "\n".join(prompt_lines)


def _planner_manual_topic_payload(slot: ContentPlanSlot) -> dict[str, list[dict[str, Any]]]:
    category_key = _slot_category_key(slot)
    if not category_key:
        return {}
    parsed_context = parse_planner_bundle_context(slot.brief_extra_context)
    return {
        category_key: [
            {
                "keyword": slot.brief_topic or "",
                "audience": slot.brief_audience or "",
                "information_level": slot.brief_information_level or "",
                "extra_context": slot.brief_extra_context or "",
                "category_name": _slot_category_name(slot) or category_key,
                "scheduled_for": slot.scheduled_for.isoformat() if slot.scheduled_for else "",
                "bundle_key": parsed_context.bundle_key,
                "facts": parsed_context.facts,
                "prohibited_claims": parsed_context.prohibited_claims,
            }
        ]
    }


def _is_blank_text(value: Any) -> bool:
    return not str(value or "").strip()


def _clean_text(value: Any, *, max_length: int = 1000) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:max_length]


def _parse_confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return round(max(0.0, min(parsed, 1.0)), 3)


def _extract_json_payload(content: str) -> dict[str, Any]:
    normalized = str(content or "").strip()
    if not normalized:
        raise ValueError("analysis response is empty")
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError:
        start = normalized.find("{")
        end = normalized.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("analysis response is not valid JSON") from None
        parsed = json.loads(normalized[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("analysis response root must be a JSON object")
    return parsed


def _fact_url_key_for_planner(*, blog_id: int, url: str | None) -> tuple[int, str] | None:
    normalized = str(url or "").strip()
    if not normalized:
        return None
    return (blog_id, normalized)


def _load_monthly_signal_payload(db: Session, *, blog: Blog, month: str) -> dict[str, Any]:
    report = (
        db.query(AnalyticsBlogMonthlyReport)
        .filter(AnalyticsBlogMonthlyReport.blog_id == blog.id, AnalyticsBlogMonthlyReport.month == month)
        .one_or_none()
    )
    theme_stats = (
        db.query(AnalyticsThemeMonthlyStat)
        .filter(AnalyticsThemeMonthlyStat.blog_id == blog.id, AnalyticsThemeMonthlyStat.month == month)
        .order_by(AnalyticsThemeMonthlyStat.theme_name.asc())
        .all()
    )
    facts = (
        db.query(AnalyticsArticleFact)
        .filter(AnalyticsArticleFact.blog_id == blog.id, AnalyticsArticleFact.month == month)
        .order_by(AnalyticsArticleFact.published_at.desc(), AnalyticsArticleFact.id.desc())
        .limit(40)
        .all()
    )
    pairs = {
        key
        for key in (_fact_url_key_for_planner(blog_id=item.blog_id, url=item.actual_url) for item in facts)
        if key is not None
    }
    _index_state_map, ctr_map = load_fact_enrichment_maps(db, pairs=pairs)

    fact_items: list[dict[str, Any]] = []
    for fact in facts:
        key = _fact_url_key_for_planner(blog_id=fact.blog_id, url=fact.actual_url)
        ctr_row = ctr_map.get(key) if key else None
        ctr_value = float(ctr_row.ctr) if ctr_row and ctr_row.ctr is not None else None
        fact_items.append(
            {
                "id": fact.id,
                "title": fact.title,
                "theme_key": fact.theme_key,
                "theme_name": fact.theme_name,
                "category": fact.category,
                "published_at": fact.published_at.isoformat() if fact.published_at else None,
                "ctr": ctr_value,
                "seo_score": fact.seo_score,
                "geo_score": fact.geo_score,
                "status": fact.status,
                "actual_url": fact.actual_url,
            }
        )

    ctr_facts = [item for item in fact_items if item.get("ctr") is not None]
    ctr_facts.sort(key=lambda item: float(item.get("ctr") or 0), reverse=True)
    top_ctr_facts = ctr_facts[:8]

    return {
        "month": month,
        "total_posts": int(report.total_posts) if report else len(fact_items),
        "avg_seo_score": float(report.avg_seo_score) if report and report.avg_seo_score is not None else None,
        "avg_geo_score": float(report.avg_geo_score) if report and report.avg_geo_score is not None else None,
        "avg_similarity_score": (
            float(report.avg_similarity_score) if report and report.avg_similarity_score is not None else None
        ),
        "report_summary": report.report_summary if report else None,
        "next_month_focus": report.next_month_focus if report else None,
        "theme_stats": [
            {
                "theme_key": item.theme_key,
                "theme_name": item.theme_name,
                "planned_posts": item.planned_posts,
                "actual_posts": item.actual_posts,
                "planned_share": item.planned_share,
                "actual_share": item.actual_share,
                "gap_share": item.gap_share,
                "next_month_weight_suggestion": item.next_month_weight_suggestion,
            }
            for item in theme_stats
        ],
        "article_facts": fact_items,
        "top_ctr_facts": top_ctr_facts,
        "ctr_data_points": len(ctr_facts),
    }


def _build_day_analysis_context(
    db: Session,
    *,
    plan_day: ContentPlanDay,
    context: PlannerChannelContext,
) -> dict[str, Any]:
    slots = sorted(plan_day.slots, key=lambda item: (item.slot_order, item.id))
    month = plan_day.plan_date.strftime("%Y-%m")
    category_weights = [
        {
            "key": category.key,
            "name": category.name,
            "weight": category.weight,
            "color": category.color,
        }
        for category in context.categories
    ]
    slot_payload = [
        {
            "slot_id": slot.id,
            "slot_order": slot.slot_order,
            "scheduled_for": slot.scheduled_for.isoformat() if slot.scheduled_for else None,
            "category_key": _slot_category_key(slot),
            "category_name": _slot_category_name(slot),
            "brief_topic": slot.brief_topic,
            "brief_audience": slot.brief_audience,
            "brief_information_level": slot.brief_information_level,
            "brief_extra_context": slot.brief_extra_context,
        }
        for slot in slots
    ]

    monthly_signals: dict[str, Any] = {
        "month": month,
        "total_posts": 0,
        "theme_stats": [],
        "article_facts": [],
        "top_ctr_facts": [],
        "ctr_data_points": 0,
    }
    if context.blog is not None:
        monthly_signals = _load_monthly_signal_payload(db, blog=context.blog, month=month)

    return {
        "channel": {
            "channel_id": context.channel_id,
            "provider": context.provider,
            "channel_name": context.channel_name,
            "blog_id": context.blog_id,
            "blog_slug": context.blog.slug if context.blog else None,
            "primary_language": context.blog.primary_language if context.blog else None,
        },
        "plan_day": {
            "id": plan_day.id,
            "date": plan_day.plan_date.isoformat(),
            "target_post_count": plan_day.target_post_count,
            "status": plan_day.status,
        },
        "slots": slot_payload,
        "category_weights": category_weights,
        "monthly_signals": monthly_signals,
        "signal_policy": {
            "priority": [
                "ctr_data",
                "monthly_report",
                "article_facts",
                "category_weights",
                "fallback",
            ]
        },
    }


def _build_day_analysis_prompt(*, analysis_context: dict[str, Any], prompt_override: str | None) -> str:
    template = get_prompt_template(PLANNER_DAILY_BRIEF_PROMPT_KEY).get("content") or ""
    if not str(template).strip():
        raise ValueError("planner daily brief analysis prompt template is empty")
    return render_prompt_template(
        template,
        analysis_context_json=json.dumps(analysis_context, ensure_ascii=False, indent=2),
        user_prompt_override=(prompt_override or "").strip() or "(none)",
    )


def _run_daily_analysis_with_openai(
    db: Session,
    *,
    prompt: str,
    requested_model: str | None,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    runtime = get_runtime_config(db)
    if str(runtime.provider_mode or "").strip().lower() != "live":
        raise ValueError("planner daily analysis requires provider_mode=live")
    if not str(runtime.openai_api_key or "").strip():
        raise ValueError("planner daily analysis requires openai_api_key")

    decision = route_openai_free_tier_text_model(
        db,
        requested_model=requested_model or runtime.openai_text_model,
        allow_large=False,
        minimum_remaining_tokens=1,
    )
    response = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {runtime.openai_api_key}"},
        json={
            "model": decision.resolved_model,
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": "Return strict JSON only. Never include markdown fences.",
                },
                {"role": "user", "content": prompt},
            ],
        },
        timeout=120.0,
    )
    if not response.is_success:
        detail = response.text
        try:
            detail = response.json().get("error", {}).get("message", detail)
        except ValueError:
            pass
        raise ProviderRuntimeError(
            provider="openai_text",
            status_code=response.status_code,
            message="Planner daily brief analysis failed.",
            detail=detail,
        )

    response_payload = response.json()
    try:
        content = str(response_payload["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("analysis response shape is invalid") from exc
    parsed = _extract_json_payload(content)
    raw_response = {
        "routing": decision.to_payload(),
        "response": response_payload,
    }
    return parsed, raw_response, decision.resolved_model


def _normalize_analysis_suggestions(
    raw_payload: dict[str, Any],
    *,
    slots: list[ContentPlanSlot],
) -> list[dict[str, Any]]:
    items = raw_payload.get("slot_suggestions")
    if not isinstance(items, list):
        raise ValueError("analysis response missing slot_suggestions list")

    slot_map = {slot.id: slot for slot in slots}
    normalized: list[dict[str, Any]] = []
    seen_slot_ids: set[int] = set()

    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            slot_id = int(item.get("slot_id"))
        except (TypeError, ValueError):
            continue
        slot = slot_map.get(slot_id)
        if slot is None or slot_id in seen_slot_ids:
            continue
        seen_slot_ids.add(slot_id)
        normalized.append(
            {
                "slot_id": slot_id,
                "slot_order": slot.slot_order,
                "category_key": _slot_category_key(slot),
                "topic": _clean_text(item.get("topic"), max_length=500),
                "audience": _clean_text(item.get("audience"), max_length=500),
                "information_level": _clean_text(item.get("information_level"), max_length=250),
                "extra_context": _clean_text(item.get("extra_context"), max_length=2000),
                "expected_ctr_lift": _clean_text(item.get("expected_ctr_lift"), max_length=120),
                "confidence": _parse_confidence(item.get("confidence")),
                "signal_source": _clean_text(item.get("signal_source"), max_length=120),
                "reason": _clean_text(item.get("reason"), max_length=240),
            }
        )

    if not normalized:
        raise ValueError("analysis response did not include valid slot suggestions")

    normalized.sort(key=lambda item: (int(item.get("slot_order") or 0), int(item.get("slot_id") or 0)))
    return normalized


def _serialize_brief_run(
    run: PlannerBriefRun,
    *,
    slot_lookup: dict[int, ContentPlanSlot] | None = None,
) -> PlannerBriefRunRead:
    slot_lookup = slot_lookup or {}
    suggestions: list[PlannerBriefSuggestionRead] = []
    raw_suggestions = run.slot_suggestions if isinstance(run.slot_suggestions, list) else []
    for item in raw_suggestions:
        if not isinstance(item, dict):
            continue
        try:
            slot_id = int(item.get("slot_id"))
        except (TypeError, ValueError):
            continue
        slot = slot_lookup.get(slot_id)
        suggestions.append(
            PlannerBriefSuggestionRead(
                slot_id=slot_id,
                slot_order=int(item.get("slot_order") or (slot.slot_order if slot else 0) or 0),
                category_key=_clean_text(item.get("category_key"), max_length=100)
                or (_slot_category_key(slot) if slot else None),
                topic=_clean_text(item.get("topic"), max_length=500),
                audience=_clean_text(item.get("audience"), max_length=500),
                information_level=_clean_text(item.get("information_level"), max_length=250),
                extra_context=_clean_text(item.get("extra_context"), max_length=2000),
                expected_ctr_lift=_clean_text(item.get("expected_ctr_lift"), max_length=120),
                confidence=_parse_confidence(item.get("confidence")),
                signal_source=_clean_text(item.get("signal_source"), max_length=120),
                reason=_clean_text(item.get("reason"), max_length=240),
            )
        )

    applied_ids: list[int] = []
    for item in run.applied_slot_ids if isinstance(run.applied_slot_ids, list) else []:
        try:
            applied_ids.append(int(item))
        except (TypeError, ValueError):
            continue

    return PlannerBriefRunRead(
        id=run.id,
        plan_day_id=run.plan_day_id,
        channel_id=run.channel_id,
        blog_id=run.blog_id,
        provider=run.provider,
        model=run.model,
        prompt=run.prompt,
        raw_response=run.raw_response if isinstance(run.raw_response, dict) else {},
        slot_suggestions=suggestions,
        status=run.status,
        error_message=run.error_message,
        applied_slot_ids=applied_ids,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def analyze_day_briefs(
    db: Session,
    *,
    plan_day_id: int,
    prompt_override: str | None = None,
) -> PlannerDayBriefAnalysisResponse:
    plan_day = (
        db.query(ContentPlanDay)
        .options(*_plan_day_options())
        .filter(ContentPlanDay.id == plan_day_id)
        .one_or_none()
    )
    if plan_day is None:
        raise ValueError("planner day not found")

    ordered_slots = sorted(plan_day.slots, key=lambda item: (item.slot_order, item.id))
    if not ordered_slots:
        raise ValueError("planner day has no slots")

    settings_map = get_settings_map(db)
    context = _resolve_channel_context(
        db,
        channel_id=plan_day.channel_id,
        blog_id=plan_day.blog_id,
        settings_map=settings_map,
    )
    analysis_context = _build_day_analysis_context(db, plan_day=plan_day, context=context)
    prompt = _build_day_analysis_prompt(analysis_context=analysis_context, prompt_override=prompt_override)

    run = PlannerBriefRun(
        plan_day_id=plan_day.id,
        channel_id=plan_day.channel_id,
        blog_id=plan_day.blog_id,
        provider=context.provider,
        model=None,
        prompt=prompt,
        raw_response={},
        slot_suggestions=[],
        status="running",
        error_message=None,
        applied_slot_ids=[],
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        parsed_payload, raw_response, resolved_model = _run_daily_analysis_with_openai(
            db,
            prompt=prompt,
            requested_model=settings_map.get("openai_text_model"),
        )
        slot_suggestions = _normalize_analysis_suggestions(parsed_payload, slots=ordered_slots)
        run.model = resolved_model
        run.raw_response = raw_response
        run.slot_suggestions = slot_suggestions
        run.status = "completed"
        run.error_message = None
    except Exception as exc:  # noqa: BLE001
        run.status = "failed"
        run.error_message = str(exc)
    db.add(run)
    db.commit()
    db.refresh(run)

    slot_lookup = {slot.id: slot for slot in ordered_slots}
    return PlannerDayBriefAnalysisResponse(run=_serialize_brief_run(run, slot_lookup=slot_lookup))


def _normalize_apply_suggestions(
    *,
    raw_items: list[PlannerBriefSuggestionInput] | list[dict[str, Any]],
    slot_map: dict[int, ContentPlanSlot],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen_slot_ids: set[int] = set()

    for entry in raw_items:
        payload = entry.model_dump() if hasattr(entry, "model_dump") else dict(entry)
        try:
            slot_id = int(payload.get("slot_id"))
        except (TypeError, ValueError):
            raise ValueError("slot_suggestions must include valid slot_id") from None
        if slot_id in seen_slot_ids:
            continue
        slot = slot_map.get(slot_id)
        if slot is None:
            raise ValueError(f"slot_id {slot_id} is not in this planner day")
        seen_slot_ids.add(slot_id)
        normalized.append(
            {
                "slot_id": slot_id,
                "topic": _clean_text(payload.get("topic"), max_length=500),
                "audience": _clean_text(payload.get("audience"), max_length=500),
                "information_level": _clean_text(payload.get("information_level"), max_length=250),
                "extra_context": _clean_text(payload.get("extra_context"), max_length=2000),
                "expected_ctr_lift": _clean_text(payload.get("expected_ctr_lift"), max_length=120),
                "confidence": _parse_confidence(payload.get("confidence")),
                "signal_source": _clean_text(payload.get("signal_source"), max_length=120),
                "reason": _clean_text(payload.get("reason"), max_length=240),
            }
        )

    if not normalized:
        raise ValueError("slot_suggestions is empty")
    return normalized


def apply_day_briefs(
    db: Session,
    *,
    plan_day_id: int,
    run_id: int | None = None,
    slot_suggestions: list[PlannerBriefSuggestionInput] | None = None,
) -> PlannerDayBriefApplyResponse:
    plan_day = (
        db.query(ContentPlanDay)
        .options(*_plan_day_options())
        .filter(ContentPlanDay.id == plan_day_id)
        .one_or_none()
    )
    if plan_day is None:
        raise ValueError("planner day not found")

    ordered_slots = sorted(plan_day.slots, key=lambda item: (item.slot_order, item.id))
    if not ordered_slots:
        raise ValueError("planner day has no slots")
    slot_map = {slot.id: slot for slot in ordered_slots}

    selected_run: PlannerBriefRun | None = None
    raw_items: list[PlannerBriefSuggestionInput] | list[dict[str, Any]]
    if run_id is not None:
        selected_run = (
            db.query(PlannerBriefRun)
            .filter(PlannerBriefRun.id == run_id, PlannerBriefRun.plan_day_id == plan_day_id)
            .one_or_none()
        )
        if selected_run is None:
            raise ValueError("planner brief run not found")
        if selected_run.status == "failed" and not slot_suggestions:
            raise ValueError("cannot apply a failed planner brief run")
    if slot_suggestions:
        raw_items = slot_suggestions
    elif selected_run is not None:
        raw_items = selected_run.slot_suggestions if isinstance(selected_run.slot_suggestions, list) else []
    else:
        raise ValueError("run_id or slot_suggestions is required")

    normalized = _normalize_apply_suggestions(raw_items=raw_items, slot_map=slot_map)
    applied_slot_ids: list[int] = []
    skipped_slot_ids: list[int] = []

    for suggestion in normalized:
        slot = slot_map[suggestion["slot_id"]]
        changed = False
        for slot_field, suggestion_field in BRIEF_APPLY_FIELD_MAP:
            incoming_value = suggestion.get(suggestion_field)
            if _is_blank_text(incoming_value):
                continue
            current_value = getattr(slot, slot_field)
            if _is_blank_text(current_value):
                setattr(slot, slot_field, str(incoming_value).strip())
                changed = True
        if changed:
            slot.status = _slot_status(slot)
            db.add(slot)
            applied_slot_ids.append(slot.id)
        else:
            next_status = _slot_status(slot)
            if slot.status != next_status:
                slot.status = next_status
                db.add(slot)
            skipped_slot_ids.append(slot.id)

    if selected_run is not None:
        existing_applied = {
            int(item)
            for item in (selected_run.applied_slot_ids if isinstance(selected_run.applied_slot_ids, list) else [])
            if str(item).strip().isdigit()
        }
        existing_applied.update(applied_slot_ids)
        selected_run.applied_slot_ids = sorted(existing_applied)
        if selected_run.status != "failed":
            selected_run.status = "applied"
        selected_run.error_message = None
        db.add(selected_run)

    db.commit()
    return PlannerDayBriefApplyResponse(
        plan_day_id=plan_day_id,
        applied_slot_ids=applied_slot_ids,
        skipped_slot_ids=skipped_slot_ids,
        run_id=selected_run.id if selected_run else None,
        status="applied",
    )


def list_day_brief_runs(db: Session, *, plan_day_id: int, limit: int = 20) -> list[PlannerBriefRunRead]:
    plan_day = (
        db.query(ContentPlanDay)
        .options(*_plan_day_options())
        .filter(ContentPlanDay.id == plan_day_id)
        .one_or_none()
    )
    if plan_day is None:
        raise ValueError("planner day not found")
    slot_lookup = {slot.id: slot for slot in plan_day.slots}
    runs = (
        db.query(PlannerBriefRun)
        .filter(PlannerBriefRun.plan_day_id == plan_day_id)
        .order_by(PlannerBriefRun.created_at.desc(), PlannerBriefRun.id.desc())
        .limit(max(1, min(limit, 100)))
        .all()
    )
    return [_serialize_brief_run(run, slot_lookup=slot_lookup) for run in runs]


def get_calendar(db: Session, channel_id: str | None, month: str, blog_id: int | None = None) -> PlannerCalendarRead:
    settings_map = get_settings_map(db)
    context = _resolve_channel_context(db, channel_id=channel_id, blog_id=blog_id, settings_map=settings_map)
    start_date, end_date = _month_bounds(month)
    def load_days() -> list[ContentPlanDay]:
        return (
            db.query(ContentPlanDay)
            .options(*_plan_day_options())
            .filter(ContentPlanDay.channel_id == context.channel_id)
            .filter(and_(ContentPlanDay.plan_date >= start_date, ContentPlanDay.plan_date <= end_date))
            .order_by(ContentPlanDay.plan_date.asc())
            .all()
        )

    days = load_days()
    if _normalize_existing_slots(db, context=context, days=days):
        days = load_days()
    return PlannerCalendarRead(
        channel_id=context.channel_id,
        channel_name=context.channel_name,
        channel_provider=context.provider,
        blog_id=context.blog_id,
        month=month,
        categories=[_serialize_category(category) for category in context.categories],
        days=[_serialize_day(day) for day in days],
    )


def list_categories(db: Session, channel_id: str | None, blog_id: int | None = None) -> list[PlannerCategoryRead]:
    context = _resolve_channel_context(db, channel_id=channel_id, blog_id=blog_id)
    return [_serialize_category(category) for category in context.categories]

def create_month_plan(
    db: Session,
    *,
    channel_id: str | None,
    month: str,
    target_post_count: int | None = None,
    overwrite: bool = False,
    blog_id: int | None = None,
) -> PlannerCalendarRead:
    settings_map = get_settings_map(db)
    context = _resolve_channel_context(db, channel_id=channel_id, blog_id=blog_id, settings_map=settings_map)
    start_date, end_date = _month_bounds(month)
    daily_target = target_post_count or int(settings_map.get("planner_default_daily_posts", "3"))
    legacy_themes = _sync_legacy_blogger_themes(db, blog=context.blog, categories=context.categories) if context.blog else {}

    if overwrite:
        existing_days = (
            db.query(ContentPlanDay)
            .filter(ContentPlanDay.channel_id == context.channel_id)
            .filter(and_(ContentPlanDay.plan_date >= start_date, ContentPlanDay.plan_date <= end_date))
            .all()
        )
        for day in existing_days:
            db.delete(day)
        db.flush()

    category_cycle = _weighted_category_cycle(context.categories)
    if not category_cycle:
        raise ValueError("at least one active category is required")

    cycle_index = 0
    day_cursor = start_date
    while day_cursor <= end_date:
        plan_day = _ensure_day(db, context=context, plan_date=day_cursor, target_post_count=daily_target)
        if overwrite or not plan_day.slots:
            if overwrite:
                for slot in list(plan_day.slots):
                    db.delete(slot)
                db.flush()
            times = _build_slot_times(day_cursor, daily_target, settings_map)
            for day_slot_order, slot_time in enumerate(times, start=1):
                category = category_cycle[cycle_index % len(category_cycle)]
                cycle_index += 1
                slot = ContentPlanSlot(
                    plan_day_id=plan_day.id,
                    scheduled_for=slot_time,
                    slot_order=day_slot_order,
                    status="planned",
                    result_payload={},
                )
                _apply_slot_category(slot, category, legacy_themes.get(category.key))
                db.add(slot)
        day_cursor += timedelta(days=1)

    db.commit()
    return get_calendar(db, channel_id=context.channel_id, month=month)


def _apply_multilingual_schedule_default(slot: ContentPlanSlot, blog: Blog | None) -> None:
    if blog is None or slot.scheduled_for is None:
        return
    parsed_context = parse_planner_bundle_context(slot.brief_extra_context)
    if not parsed_context.bundle_key:
        return
    language = resolve_blog_bundle_language(blog)
    if not language:
        return
    base_time = slot.scheduled_for.replace(minute=0, second=0, microsecond=0)
    slot.scheduled_for = base_time + timedelta(minutes=bundle_publish_offset_minutes(language))


def create_slot(db: Session, payload: PlannerSlotCreate) -> PlannerSlotRead:
    plan_day = (
        db.query(ContentPlanDay)
        .options(*_plan_day_options())
        .filter(ContentPlanDay.id == payload.plan_day_id)
        .one()
    )
    context = _resolve_channel_context(db, channel_id=plan_day.channel_id, blog_id=plan_day.blog_id)
    category = _select_category(context, payload.category_key)
    legacy_themes = _sync_legacy_blogger_themes(db, blog=context.blog, categories=context.categories) if context.blog else {}
    slot = ContentPlanSlot(
        plan_day_id=payload.plan_day_id,
        scheduled_for=datetime.fromisoformat(payload.scheduled_for),
        slot_order=len(plan_day.slots) + 1,
        brief_topic=payload.brief_topic,
        brief_audience=payload.brief_audience,
        brief_information_level=payload.brief_information_level,
        brief_extra_context=payload.brief_extra_context,
        status="planned",
        result_payload={},
    )
    _apply_slot_category(slot, category, legacy_themes.get(category.key))
    _apply_multilingual_schedule_default(slot, context.blog)
    slot.status = _slot_status(slot)
    db.add(slot)
    db.flush()
    _resequence_slots(plan_day, sort_by_time=True)
    db.commit()
    db.refresh(slot)
    return _serialize_slot(slot)


def update_slot(db: Session, slot_id: int, payload: PlannerSlotUpdate) -> PlannerSlotRead:
    slot = (
        db.query(ContentPlanSlot)
        .options(
            joinedload(ContentPlanSlot.theme),
            joinedload(ContentPlanSlot.plan_day).joinedload(ContentPlanDay.blog),
            joinedload(ContentPlanSlot.plan_day).joinedload(ContentPlanDay.slots).joinedload(ContentPlanSlot.article).joinedload(Article.blogger_post),
            joinedload(ContentPlanSlot.article).joinedload(Article.blogger_post),
        )
        .filter(ContentPlanSlot.id == slot_id)
        .one()
    )
    updates = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else payload.dict(exclude_unset=True)
    explicit_status = updates.pop("status", None)
    sort_by_time = False

    context = _resolve_channel_context(db, channel_id=slot.plan_day.channel_id, blog_id=slot.plan_day.blog_id)
    legacy_themes = _sync_legacy_blogger_themes(db, blog=context.blog, categories=context.categories) if context.blog else {}

    if "category_key" in updates and updates["category_key"] is not None:
        category = _select_category(context, str(updates.pop("category_key")))
        _apply_slot_category(slot, category, legacy_themes.get(category.key))

    if "scheduled_for" in updates and updates["scheduled_for"] is not None:
        slot.scheduled_for = datetime.fromisoformat(str(updates.pop("scheduled_for")))
        sort_by_time = True

    for key, value in updates.items():
        setattr(slot, key, value)

    _apply_multilingual_schedule_default(slot, context.blog)
    slot.status = str(explicit_status) if explicit_status is not None else _slot_status(slot)
    _resequence_slots(slot.plan_day, sort_by_time=sort_by_time)
    db.commit()
    db.refresh(slot)
    return _serialize_slot(slot)


def cancel_slot(db: Session, slot_id: int) -> PlannerSlotRead:
    slot = (
        db.query(ContentPlanSlot)
        .options(
            joinedload(ContentPlanSlot.theme),
            joinedload(ContentPlanSlot.plan_day).joinedload(ContentPlanDay.blog),
            joinedload(ContentPlanSlot.article).joinedload(Article.blogger_post),
        )
        .filter(ContentPlanSlot.id == slot_id)
        .one()
    )
    slot.status = "canceled"
    slot.error_message = None
    db.commit()
    db.refresh(slot)
    return _serialize_slot(slot)


def _ensure_slot_ready(slot: ContentPlanSlot) -> None:
    if not slot.scheduled_for:
        raise ValueError("scheduled_for is required")
    if not _slot_category_key(slot):
        raise ValueError("category_key is required")
    missing = [field for field in READY_BRIEF_FIELDS if not getattr(slot, field)]
    if "brief_audience" in missing and slot.plan_day.blog is not None:
        language = resolve_blog_bundle_language(slot.plan_day.blog)
        default_audience = default_target_audience_for_language(language)
        if default_audience:
            slot.brief_audience = default_audience
            missing = [field for field in missing if field != "brief_audience"]
    if missing:
        raise ValueError("planner brief is incomplete")


def _has_ready_brief(slot: ContentPlanSlot) -> bool:
    return all(bool(getattr(slot, field)) for field in READY_BRIEF_FIELDS)


def _ensure_sequential_order(db: Session, slot: ContentPlanSlot) -> None:
    prior_slots = (
        db.query(ContentPlanSlot)
        .join(ContentPlanDay, ContentPlanSlot.plan_day_id == ContentPlanDay.id)
        .filter(ContentPlanDay.channel_id == slot.plan_day.channel_id)
        .filter(ContentPlanSlot.id != slot.id)
        .filter(ContentPlanSlot.status.in_(["planned", "brief_ready", "queued", "generating"]))
        .filter(
            (ContentPlanSlot.scheduled_for < slot.scheduled_for)
            | (
                and_(
                    ContentPlanSlot.scheduled_for == slot.scheduled_for,
                    ContentPlanSlot.slot_order < slot.slot_order,
                )
            )
        )
        .order_by(ContentPlanSlot.scheduled_for.asc(), ContentPlanSlot.slot_order.asc())
        .all()
    )
    prior = next((candidate for candidate in prior_slots if _has_ready_brief(candidate)), None)
    if prior is not None:
        raise ValueError("earlier planner slots must run first")

def _run_blogger_slot_generation(
    db: Session,
    slot: ContentPlanSlot,
    *,
    publish_mode_override: PublishMode | None = None,
) -> None:
    if slot.plan_day.blog is None:
        raise ValueError("blog channel context is missing")

    blog, multilingual_language = _enforce_multilingual_blogger_setup(db, slot.plan_day.blog)
    _apply_multilingual_schedule_default(slot, blog)
    db.add(slot)
    db.commit()
    db.refresh(slot)

    if not (slot.brief_audience or "").strip() and multilingual_language:
        slot.brief_audience = default_target_audience_for_language(multilingual_language)
        db.add(slot)
        db.commit()
        db.refresh(slot)

    category_key = _slot_category_key(slot)
    category_name = _slot_category_name(slot) or "General"
    title_seed, planner_prompt = _planner_prompt_lines(slot, blog_name=blog.name, category_name=category_name)
    planner_brief_payload = _build_planner_brief_payload(
        slot=slot,
        category_key=category_key,
        category_name=category_name,
        language=multilingual_language,
    )

    topic = db.query(Topic).filter(Topic.blog_id == blog.id, Topic.keyword == title_seed).one_or_none()
    if topic is None:
        topic = Topic(
            blog_id=blog.id,
            keyword=title_seed,
            reason=planner_prompt,
            editorial_category_key=category_key,
            editorial_category_label=category_name,
        )
        db.add(topic)
        db.flush()
    else:
        topic.reason = planner_prompt
        topic.editorial_category_key = category_key
        topic.editorial_category_label = category_name
        db.add(topic)
        db.flush()

    requested_publish_mode = publish_mode_override or PublishMode.DRAFT
    job = create_job(
        db,
        blog_id=blog.id,
        keyword=title_seed,
        topic_id=topic.id,
        publish_mode=requested_publish_mode,
        raw_prompts={
            "planner_brief": planner_brief_payload
        },
    )
    slot.job_id = job.id
    slot.result_payload = {
        "bundle_key": planner_brief_payload.get("bundle_key"),
        "language": planner_brief_payload.get("language"),
        "recommended_publish_at": planner_brief_payload.get("recommended_publish_at"),
        "requested_status": requested_publish_mode.value,
    }
    slot.status = "queued"
    slot.last_run_at = datetime.now(UTC).replace(tzinfo=None)
    slot.error_message = None
    db.commit()
    run_job.delay(job.id)


def _run_cloudflare_slot_generation(
    db: Session,
    slot: ContentPlanSlot,
    *,
    publish_mode_override: PublishMode | None = None,
) -> None:
    category_key = _slot_category_key(slot)
    if not category_key:
        raise ValueError("category_key is required")
    requested_status = "published" if publish_mode_override == PublishMode.PUBLISH else "draft"

    result = generate_cloudflare_posts(
        db,
        per_category=1,
        category_plan={category_key: 1},
        status=requested_status,
        manual_topic_plan=_planner_manual_topic_payload(slot),
    )
    category_result = next(
        (
            item
            for item in result.get("categories", [])
            if str(item.get("category_slug") or item.get("category_id") or "").strip() == category_key
        ),
        None,
    )
    item = None
    if isinstance(category_result, dict):
        item = next((entry for entry in category_result.get("items", []) if isinstance(entry, dict)), None)

    result_payload = {
        "provider": "cloudflare",
        "requested_status": requested_status,
        "status": str((item or {}).get("status") or result.get("status") or "").strip(),
        "title": str((item or {}).get("title") or slot.brief_topic or "").strip(),
        "public_url": str((item or {}).get("public_url") or "").strip(),
        "post_id": str((item or {}).get("post_id") or "").strip(),
        "slug": str((item or {}).get("slug") or "").strip(),
        "quality_gate": (item or {}).get("quality_gate") if isinstance((item or {}).get("quality_gate"), dict) else {},
        "error": str((item or {}).get("error") or result.get("reason") or "").strip() or None,
    }

    slot.result_payload = result_payload
    slot.last_run_at = datetime.now(UTC).replace(tzinfo=None)
    slot.error_message = str(result_payload.get("error") or "") or None
    slot.status = "generated" if result_payload.get("status") == "created" else "failed"
    db.add(slot)
    db.commit()


def _resolve_platform_content_type(slot: ContentPlanSlot, provider: str) -> str:
    if provider == "youtube":
        return "youtube_video"
    category_key = (_slot_category_key(slot) or "").strip().lower()
    return "instagram_reel" if category_key == "reel" else "instagram_image"


def _run_platform_slot_generation(db: Session, slot: ContentPlanSlot, *, provider: str) -> None:
    managed_channel = get_managed_channel(db, slot.plan_day.channel_id)
    if managed_channel is None:
        raise ValueError("managed channel context is missing")

    category_key = _slot_category_key(slot) or "general"
    category_name = _slot_category_name(slot) or category_key
    title_seed = (slot.brief_topic or "").strip() or f"{managed_channel.display_name} {category_name}"
    description = (slot.brief_audience or "").strip()
    if slot.brief_extra_context:
        description = (f"{description}\n{slot.brief_extra_context}").strip()

    brief_payload = {
        "planner_mode": True,
        "planner_slot_id": slot.id,
        "category_key": category_key,
        "category_name": category_name,
        "topic": slot.brief_topic,
        "audience": slot.brief_audience,
        "information_level": slot.brief_information_level,
        "extra_context": slot.brief_extra_context,
        "scheduled_for": slot.scheduled_for.isoformat() if slot.scheduled_for else None,
    }
    content_item = create_platform_content_item(
        db,
        channel=managed_channel,
        content_type=_resolve_platform_content_type(slot, provider),
        title=title_seed,
        description=description,
        body_text="",
        asset_manifest={},
        brief_payload=brief_payload,
        scheduled_for=slot.scheduled_for,
        created_by_agent="planner",
        idempotency_key=f"planner-slot:{provider}:{slot.id}",
        lifecycle_status="blocked_asset",
        blocked_reason="",
    )
    blocked_reason = content_item_missing_asset_reason(content_item) or "missing_required_asset"
    content_item.blocked_reason = blocked_reason
    db.add(content_item)
    db.commit()
    db.refresh(content_item)

    slot.result_payload = {
        "provider": provider,
        "status": "blocked_asset",
        "content_item_id": content_item.id,
        "requested_status": "blocked_asset",
        "blocked_reason": blocked_reason,
        "title": content_item.title,
        "scheduled_for": slot.scheduled_for.isoformat() if slot.scheduled_for else None,
    }
    slot.last_run_at = datetime.now(UTC).replace(tzinfo=None)
    slot.error_message = blocked_reason
    slot.status = "generated"
    db.add(slot)
    db.commit()


def run_slot_generation(
    db: Session,
    slot_id: int,
    *,
    publish_mode_override: PublishMode | None = None,
) -> PlannerSlotRead:
    slot = (
        db.query(ContentPlanSlot)
        .options(
            joinedload(ContentPlanSlot.theme),
            joinedload(ContentPlanSlot.plan_day).joinedload(ContentPlanDay.blog),
            joinedload(ContentPlanSlot.article).joinedload(Article.blogger_post),
        )
        .filter(ContentPlanSlot.id == slot_id)
        .one()
    )
    _ensure_slot_ready(slot)
    _ensure_sequential_order(db, slot)

    provider, _raw_id = _parse_channel_id(slot.plan_day.channel_id)
    if provider == "blogger":
        _run_blogger_slot_generation(db, slot, publish_mode_override=publish_mode_override)
    elif provider == "cloudflare":
        _run_cloudflare_slot_generation(db, slot, publish_mode_override=publish_mode_override)
    elif provider in {"youtube", "instagram"}:
        _run_platform_slot_generation(db, slot, provider=provider)
    else:
        raise ValueError("unsupported planner channel provider")

    db.refresh(slot)
    return _serialize_slot(slot)


def normalize_month_plan_payload(payload: PlannerMonthPlanRequest) -> dict[str, Any]:
    return {
        "channel_id": payload.channel_id,
        "blog_id": payload.blog_id,
        "month": payload.month,
        "target_post_count": payload.target_post_count,
        "overwrite": payload.overwrite,
    }
