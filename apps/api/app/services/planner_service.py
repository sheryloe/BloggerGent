from __future__ import annotations

import calendar
from collections import Counter
from datetime import date, datetime, time, timedelta
from typing import Iterable

from sqlalchemy import and_
from sqlalchemy.orm import Session, joinedload

from app.models.entities import Article, Blog, BlogTheme, ContentPlanDay, ContentPlanSlot, PublishMode, Topic
from app.schemas.api import (
    PlannerCalendarRead,
    PlannerCategoryRead,
    PlannerDayRead,
    PlannerMonthPlanRequest,
    PlannerSlotCreate,
    PlannerSlotRead,
    PlannerSlotUpdate,
    PlannerThemeRead,
)
from app.services.job_service import create_job
from app.services.settings_service import get_settings_map
from app.tasks.pipeline import run_job

DEFAULT_THEME_PRESETS = {
    "travel": [
        ("itinerary", "Itinerary", 30, "#0f766e"),
        ("budget", "Budget", 20, "#2563eb"),
        ("food", "Food", 15, "#d97706"),
        ("stay", "Stay", 15, "#7c3aed"),
        ("transport", "Transport", 10, "#475569"),
        ("culture", "Culture", 10, "#dc2626"),
    ],
    "mystery": [
        ("case-files", "Case Files", 25, "#7f1d1d"),
        ("urban-legends", "Urban Legends", 20, "#581c87"),
        ("history", "History", 20, "#1d4ed8"),
        ("locations", "Locations", 15, "#0f766e"),
        ("theories", "Theories", 10, "#d97706"),
        ("timeline", "Timeline", 10, "#334155"),
    ],
    "default": [
        ("insight", "Insight", 30, "#2563eb"),
        ("guide", "Guide", 20, "#0f766e"),
        ("analysis", "Analysis", 20, "#7c3aed"),
        ("trend", "Trend", 15, "#d97706"),
        ("ops", "Ops", 15, "#475569"),
    ],
}

BRIEF_FIELDS = (
    "brief_topic",
    "brief_audience",
    "brief_information_level",
    "brief_extra_context",
)


def _month_bounds(month: str) -> tuple[date, date]:
    start = datetime.strptime(f"{month}-01", "%Y-%m-%d").date()
    _, last_day = calendar.monthrange(start.year, start.month)
    return start, date(start.year, start.month, last_day)


def _parse_clock(value: str | None, fallback: time) -> time:
    if not value:
        return fallback
    try:
        parsed = datetime.strptime(value, "%H:%M").time()
    except ValueError:
        return fallback
    return parsed.replace(second=0, microsecond=0)


def _slot_status(slot: ContentPlanSlot) -> str:
    if slot.status:
        return slot.status
    if all(getattr(slot, field) for field in BRIEF_FIELDS) and slot.scheduled_for:
        return "brief_ready"
    return "planned"


def _serialize_theme(theme: BlogTheme) -> PlannerThemeRead:
    return PlannerThemeRead(
        id=theme.id,
        key=theme.key,
        name=theme.name,
        weight=theme.weight,
        color=theme.color,
        sort_order=theme.sort_order,
        is_active=theme.is_active,
    )


def _serialize_category(theme: BlogTheme) -> PlannerCategoryRead:
    return PlannerCategoryRead(
        id=theme.id,
        key=theme.key,
        name=theme.name,
        weight=theme.weight,
        color=theme.color,
        sort_order=theme.sort_order,
        is_active=theme.is_active,
    )


def _serialize_slot(slot: ContentPlanSlot) -> PlannerSlotRead:
    return PlannerSlotRead(
        id=slot.id,
        plan_day_id=slot.plan_day_id,
        theme_id=slot.theme_id,
        theme_key=slot.theme.key if slot.theme else None,
        theme_name=slot.theme.name if slot.theme else None,
        category_id=slot.theme_id,
        category_key=slot.theme.key if slot.theme else None,
        category_name=slot.theme.name if slot.theme else None,
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
        article_seo_score=slot.article.quality_seo_score if slot.article else None,
        article_geo_score=slot.article.quality_geo_score if slot.article else None,
        article_similarity_score=slot.article.quality_similarity_score if slot.article else None,
        article_most_similar_url=slot.article.quality_most_similar_url if slot.article else None,
        article_quality_status=slot.article.quality_status if slot.article else None,
        article_publish_status=slot.article.blogger_post.post_status.value if slot.article and slot.article.blogger_post and slot.article.blogger_post.post_status else None,
        article_published_url=slot.article.blogger_post.published_url if slot.article and slot.article.blogger_post else None,
    )


def _serialize_day(plan_day: ContentPlanDay) -> PlannerDayRead:
    theme_counter = Counter(slot.theme.key for slot in plan_day.slots if slot.theme)
    return PlannerDayRead(
        id=plan_day.id,
        blog_id=plan_day.blog_id,
        plan_date=plan_day.plan_date.isoformat(),
        target_post_count=plan_day.target_post_count,
        status=plan_day.status,
        slot_count=len(plan_day.slots),
        theme_mix=dict(theme_counter),
        category_mix=dict(theme_counter),
        slots=[_serialize_slot(slot) for slot in sorted(plan_day.slots, key=lambda item: (item.slot_order, item.id))],
    )


def _ensure_theme_set(db: Session, blog: Blog) -> list[BlogTheme]:
    themes = (
        db.query(BlogTheme)
        .filter(BlogTheme.blog_id == blog.id)
        .order_by(BlogTheme.sort_order.asc(), BlogTheme.id.asc())
        .all()
    )
    if themes:
        return themes
    preset = DEFAULT_THEME_PRESETS.get(getattr(blog, "profile_key", None) or "default", DEFAULT_THEME_PRESETS["default"])
    for index, (key, name, weight, color) in enumerate(preset, start=1):
        db.add(
            BlogTheme(
                blog_id=blog.id,
                key=key,
                name=name,
                weight=weight,
                color=color,
                sort_order=index,
                is_active=True,
            )
        )
    db.commit()
    return (
        db.query(BlogTheme)
        .filter(BlogTheme.blog_id == blog.id)
        .order_by(BlogTheme.sort_order.asc(), BlogTheme.id.asc())
        .all()
    )


def _weighted_theme_cycle(themes: Iterable[BlogTheme]) -> list[BlogTheme]:
    expanded: list[BlogTheme] = []
    active_themes = [theme for theme in themes if theme.is_active and theme.weight > 0]
    if not active_themes:
        active_themes = list(themes)
    if not active_themes:
        return []
    max_weight = max(theme.weight or 1 for theme in active_themes)
    for round_index in range(max_weight):
        for theme in active_themes:
            if (theme.weight or 1) > round_index:
                expanded.append(theme)
    return expanded or active_themes


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


def _ensure_day(db: Session, blog_id: int, plan_date: date, target_post_count: int) -> ContentPlanDay:
    plan_day = (
        db.query(ContentPlanDay)
        .options(
            joinedload(ContentPlanDay.slots).joinedload(ContentPlanSlot.theme),
            joinedload(ContentPlanDay.slots).joinedload(ContentPlanSlot.article).joinedload(Article.blogger_post),
        )
        .filter(ContentPlanDay.blog_id == blog_id, ContentPlanDay.plan_date == plan_date)
        .one_or_none()
    )
    if plan_day:
        plan_day.target_post_count = target_post_count
        return plan_day
    plan_day = ContentPlanDay(
        blog_id=blog_id,
        plan_date=plan_date,
        target_post_count=target_post_count,
        status="planned",
    )
    db.add(plan_day)
    db.flush()
    return plan_day


def _topic_prompt(slot: ContentPlanSlot, blog: Blog) -> tuple[str, str]:
    theme_name = slot.theme.name if slot.theme else "General"
    title_seed = slot.brief_topic or f"{blog.name} {theme_name}"
    prompt = "\n".join(
        [
            f"Theme: {theme_name}",
            f"Topic: {slot.brief_topic or ''}",
            f"Audience: {slot.brief_audience or ''}",
            f"Information level: {slot.brief_information_level or ''}",
            f"Extra context: {slot.brief_extra_context or ''}",
            "Planner mode: Use the brief exactly as the writing contract.",
        ]
    )
    return title_seed, prompt


def get_calendar(db: Session, blog_id: int, month: str) -> PlannerCalendarRead:
    start_date, end_date = _month_bounds(month)
    blog = db.query(Blog).filter(Blog.id == blog_id).one()
    themes = _ensure_theme_set(db, blog)
    days = (
        db.query(ContentPlanDay)
        .options(
            joinedload(ContentPlanDay.slots).joinedload(ContentPlanSlot.theme),
            joinedload(ContentPlanDay.slots).joinedload(ContentPlanSlot.article).joinedload(Article.blogger_post),
        )
        .filter(ContentPlanDay.blog_id == blog_id)
        .filter(and_(ContentPlanDay.plan_date >= start_date, ContentPlanDay.plan_date <= end_date))
        .order_by(ContentPlanDay.plan_date.asc())
        .all()
    )
    return PlannerCalendarRead(
        blog_id=blog.id,
        blog_name=blog.name,
        month=month,
        categories=[_serialize_category(theme) for theme in themes],
        themes=[_serialize_theme(theme) for theme in themes],
        days=[_serialize_day(day) for day in days],
    )


def list_categories(db: Session, blog_id: int) -> list[PlannerCategoryRead]:
    blog = db.query(Blog).filter(Blog.id == blog_id).one()
    themes = _ensure_theme_set(db, blog)
    return [_serialize_category(theme) for theme in themes]


def create_month_plan(db: Session, blog_id: int, month: str, target_post_count: int | None = None, overwrite: bool = False) -> PlannerCalendarRead:
    start_date, end_date = _month_bounds(month)
    blog = db.query(Blog).filter(Blog.id == blog_id).one()
    themes = _ensure_theme_set(db, blog)
    settings_map = get_settings_map(db)
    daily_target = target_post_count or int(settings_map.get("planner_default_daily_posts", "3"))
    if overwrite:
        existing_days = (
            db.query(ContentPlanDay)
            .filter(ContentPlanDay.blog_id == blog_id)
            .filter(and_(ContentPlanDay.plan_date >= start_date, ContentPlanDay.plan_date <= end_date))
            .all()
        )
        for day in existing_days:
            db.delete(day)
        db.flush()

    theme_cycle = _weighted_theme_cycle(themes)
    if not theme_cycle:
        raise ValueError("at least one active theme is required")

    cycle_index = 0
    day_cursor = start_date
    while day_cursor <= end_date:
        plan_day = _ensure_day(db, blog_id=blog_id, plan_date=day_cursor, target_post_count=daily_target)
        if overwrite or not plan_day.slots:
            if overwrite:
                for slot in list(plan_day.slots):
                    db.delete(slot)
                db.flush()
            times = _build_slot_times(day_cursor, daily_target, settings_map)
            for slot_time in times:
                theme = theme_cycle[cycle_index % len(theme_cycle)]
                cycle_index += 1
                db.add(
                    ContentPlanSlot(
                        plan_day_id=plan_day.id,
                        theme_id=theme.id,
                        scheduled_for=slot_time,
                        slot_order=cycle_index,
                        status="planned",
                    )
                )
        day_cursor += timedelta(days=1)

    db.commit()
    return get_calendar(db, blog_id=blog_id, month=month)


def create_slot(db: Session, payload: PlannerSlotCreate) -> PlannerSlotRead:
    plan_day = (
        db.query(ContentPlanDay)
        .options(
            joinedload(ContentPlanDay.slots).joinedload(ContentPlanSlot.theme),
            joinedload(ContentPlanDay.slots).joinedload(ContentPlanSlot.article).joinedload(Article.blogger_post),
        )
        .filter(ContentPlanDay.id == payload.plan_day_id)
        .one()
    )
    slot = ContentPlanSlot(
        plan_day_id=payload.plan_day_id,
        theme_id=payload.theme_id,
        scheduled_for=datetime.fromisoformat(payload.scheduled_for),
        slot_order=len(plan_day.slots) + 1,
        status="planned",
        brief_topic=payload.brief_topic,
        brief_audience=payload.brief_audience,
        brief_information_level=payload.brief_information_level,
        brief_extra_context=payload.brief_extra_context,
    )
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
            joinedload(ContentPlanSlot.article).joinedload(Article.blogger_post),
            joinedload(ContentPlanSlot.plan_day).joinedload(ContentPlanDay.slots).joinedload(ContentPlanSlot.article).joinedload(Article.blogger_post),
        )
        .filter(ContentPlanSlot.id == slot_id)
        .one()
    )
    updates = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else payload.dict(exclude_unset=True)
    sort_by_time = False
    if "scheduled_for" in updates and updates["scheduled_for"] is not None:
        slot.scheduled_for = datetime.fromisoformat(updates.pop("scheduled_for"))
        sort_by_time = True
    for key, value in updates.items():
        setattr(slot, key, value)
    slot.status = _slot_status(slot)
    _resequence_slots(slot.plan_day, sort_by_time=sort_by_time)
    db.commit()
    db.refresh(slot)
    return _serialize_slot(slot)


def cancel_slot(db: Session, slot_id: int) -> PlannerSlotRead:
    slot = (
        db.query(ContentPlanSlot)
        .options(
            joinedload(ContentPlanSlot.theme),
            joinedload(ContentPlanSlot.article).joinedload(Article.blogger_post),
            joinedload(ContentPlanSlot.plan_day).joinedload(ContentPlanDay.slots).joinedload(ContentPlanSlot.article).joinedload(Article.blogger_post),
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
    missing = [field for field in BRIEF_FIELDS if not getattr(slot, field)]
    if missing:
        raise ValueError("planner brief is incomplete")


def _ensure_sequential_order(db: Session, slot: ContentPlanSlot) -> None:
    prior = (
        db.query(ContentPlanSlot)
        .join(ContentPlanDay, ContentPlanSlot.plan_day_id == ContentPlanDay.id)
        .filter(ContentPlanDay.blog_id == slot.plan_day.blog_id)
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
        .first()
    )
    if prior is not None:
        raise ValueError("earlier planner slots must run first")


def run_slot_generation(db: Session, slot_id: int) -> PlannerSlotRead:
    slot = (
        db.query(ContentPlanSlot)
        .options(
            joinedload(ContentPlanSlot.theme),
            joinedload(ContentPlanSlot.plan_day).joinedload(ContentPlanDay.blog),
        )
        .filter(ContentPlanSlot.id == slot_id)
        .one()
    )
    _ensure_slot_ready(slot)
    _ensure_sequential_order(db, slot)
    blog = slot.plan_day.blog
    title_seed, planner_prompt = _topic_prompt(slot, blog)
    topic = db.query(Topic).filter(Topic.blog_id == blog.id, Topic.keyword == title_seed).one_or_none()
    if topic is None:
        topic = Topic(
            blog_id=blog.id,
            keyword=title_seed,
            reason=planner_prompt,
            editorial_category_key=slot.theme.key if slot.theme else None,
            editorial_category_label=slot.theme.name if slot.theme else None,
        )
        db.add(topic)
        db.flush()
    else:
        topic.reason = planner_prompt
        topic.editorial_category_key = slot.theme.key if slot.theme else None
        topic.editorial_category_label = slot.theme.name if slot.theme else None
        db.add(topic)
        db.flush()
    job = create_job(
        db,
        blog_id=blog.id,
        keyword=title_seed,
        topic_id=topic.id,
        publish_mode=PublishMode.DRAFT,
        raw_prompts={
            "planner_brief": {
                "topic": slot.brief_topic,
                "audience": slot.brief_audience,
                "information_level": slot.brief_information_level,
                "extra_context": slot.brief_extra_context,
                "theme": slot.theme.name if slot.theme else None,
                "scheduled_for": slot.scheduled_for.isoformat(),
            }
        },
    )
    slot.job_id = job.id
    slot.status = "queued"
    slot.last_run_at = datetime.utcnow()
    slot.error_message = None
    db.commit()
    run_job.delay(job.id)
    db.refresh(slot)
    return _serialize_slot(slot)
