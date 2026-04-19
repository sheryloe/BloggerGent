from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from slugify import slugify
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import (
    Article,
    Blog,
    BloggerPost,
    ContentPlanDay,
    ContentPlanSlot,
    Job,
    PostStatus,
    PublishMode,
    Topic,
)
from app.services.content.multilingual_bundle_service import default_target_audience_for_language
from app.services.content.travel_blog_policy import (
    TRAVEL_BLOG_IDS,
    normalize_travel_category_key,
    normalize_travel_text_generation_route,
)
from app.services.ops.job_service import create_job

TRAVEL_LANGUAGE_BY_BLOG_ID: dict[int, str] = {
    34: "en",
    36: "es",
    37: "ja",
}
TRAVEL_BLOG_ID_BY_LANGUAGE: dict[str, int] = {value: key for key, value in TRAVEL_LANGUAGE_BY_BLOG_ID.items()}
TRAVEL_CHANNEL_BY_BLOG_ID: dict[int, str] = {
    34: "blogger:34",
    36: "blogger:36",
    37: "blogger:37",
}
TRAVEL_SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "es", "ja")
TRAVEL_PLANNER_TIMEZONE = ZoneInfo("Asia/Seoul")
TRAVEL_PLANNER_DEFAULT_START_TIMES: dict[str, str] = {
    "en": "11:00",
    "es": "13:00",
    "ja": "15:00",
}
PIPELINE_SCHEDULE_KEY = "pipeline_schedule"
PLANNER_BRIEF_KEY = "planner_brief"
TRAVEL_SYNC_KEY = "travel_sync"
STATUS_WEIGHT: dict[str, int] = {"published": 4, "scheduled": 3, "draft": 2, "sync_error": 1, "missing": 0}
TOKEN_STOPWORDS: set[str] = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "your",
    "guide",
    "tips",
    "2026",
    "2025",
    "travel",
    "korea",
    "blog",
    "how",
    "use",
    "best",
    "first",
    "time",
    "last",
    "year",
}


@dataclass(slots=True)
class TravelSyncCandidate:
    article_id: int
    blog_id: int
    language: str
    slug: str
    title: str
    labels: tuple[str, ...]
    category_key: str
    hero_url: str
    status: str
    created_at: datetime
    source_article_id: int | None
    existing_group_key: str | None
    title_tokens: frozenset[str]
    label_tokens: frozenset[str]
    year_tokens: frozenset[str]


@dataclass(slots=True)
class TravelSyncGroup:
    group_key: str
    source_article_id: int
    source_blog_id: int
    source_language: str
    member_article_ids: tuple[int, ...]
    members_by_language: dict[str, int]
    missing_languages: tuple[str, ...]
    category_key: str
    hero_url: str


@dataclass(slots=True)
class TravelSyncBacklogItem:
    group_key: str
    source_article_id: int
    source_blog_id: int
    source_language: str
    source_slug: str
    source_title: str
    source_hero_url: str
    category_key: str
    target_language: str
    target_blog_id: int
    scheduled_for: datetime | None = None


def _normalize_post_status(article: Article) -> str:
    blogger_post = getattr(article, "blogger_post", None)
    if blogger_post is None:
        return "draft"
    raw = getattr(blogger_post, "post_status", None)
    if isinstance(raw, PostStatus):
        return raw.value
    normalized = str(raw or "").strip().lower()
    if normalized in {"draft", "scheduled", "published"}:
        return normalized
    return "draft"


def _normalize_hero_url(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    base = raw.split("#", maxsplit=1)[0].split("?", maxsplit=1)[0].strip()
    return base.rstrip("/")


def _tokenize(*parts: str) -> tuple[frozenset[str], frozenset[str]]:
    tokens: set[str] = set()
    years: set[str] = set()
    for part in parts:
        normalized = slugify(str(part or ""), separator=" ").strip().lower()
        if not normalized:
            continue
        for token in normalized.split():
            token = token.strip().lower()
            if not token:
                continue
            if token.isdigit() and len(token) == 4 and token.startswith("20"):
                years.add(token)
                continue
            if len(token) < 3:
                continue
            if token in TOKEN_STOPWORDS:
                continue
            tokens.add(token)
    return frozenset(tokens), frozenset(years)


def _is_strong_similarity(left: TravelSyncCandidate, right: TravelSyncCandidate) -> bool:
    if left.language == right.language:
        return False
    if left.year_tokens and right.year_tokens and not (left.year_tokens & right.year_tokens):
        return False
    intersection = left.title_tokens & right.title_tokens
    if len(intersection) < 2:
        return False
    union = left.title_tokens | right.title_tokens
    if not union:
        return False
    jaccard = len(intersection) / len(union)
    label_overlap = len(left.label_tokens & right.label_tokens)
    if label_overlap >= 1 and jaccard >= 0.42:
        return True
    return jaccard >= 0.62


def _status_rank(candidate: TravelSyncCandidate) -> tuple[int, int, int]:
    return (
        STATUS_WEIGHT.get(candidate.status, 0),
        int(candidate.created_at.timestamp()) if isinstance(candidate.created_at, datetime) else 0,
        int(candidate.article_id),
    )


def _pick_best_member(candidates: list[TravelSyncCandidate]) -> TravelSyncCandidate:
    return sorted(candidates, key=_status_rank, reverse=True)[0]


def _derive_group_key(candidates: list[TravelSyncCandidate]) -> str:
    existing_keys = sorted(
        {
            str(candidate.existing_group_key or "").strip()
            for candidate in candidates
            if str(candidate.existing_group_key or "").strip()
        }
    )
    if existing_keys:
        return existing_keys[0]

    hero_urls = sorted({candidate.hero_url for candidate in candidates if candidate.hero_url})
    if hero_urls:
        digest = hashlib.sha1(hero_urls[0].encode("utf-8")).hexdigest()[:16]
        return f"travel-sync-hero-{digest}"

    joined = ",".join(str(candidate.article_id) for candidate in sorted(candidates, key=lambda item: item.article_id))
    digest = hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]
    return f"travel-sync-{digest}"


def _union_find(ids: list[int]) -> tuple[dict[int, int], dict[int, int]]:
    parent = {item: item for item in ids}
    rank = {item: 0 for item in ids}
    return parent, rank


def _find(parent: dict[int, int], node: int) -> int:
    while parent[node] != node:
        parent[node] = parent[parent[node]]
        node = parent[node]
    return node


def _union(parent: dict[int, int], rank: dict[int, int], left: int, right: int) -> None:
    root_left = _find(parent, left)
    root_right = _find(parent, right)
    if root_left == root_right:
        return
    left_rank = rank[root_left]
    right_rank = rank[root_right]
    if left_rank < right_rank:
        parent[root_left] = root_right
        return
    if left_rank > right_rank:
        parent[root_right] = root_left
        return
    parent[root_right] = root_left
    rank[root_left] += 1


def _load_candidates(db: Session, *, blog_ids: tuple[int, ...]) -> list[TravelSyncCandidate]:
    rows = (
        db.execute(
            select(Article)
            .join(Blog, Blog.id == Article.blog_id)
            .where(
                Article.blog_id.in_(blog_ids),
                Blog.profile_key == "korea_travel",
            )
            .options(
                selectinload(Article.blog),
                selectinload(Article.image),
                selectinload(Article.blogger_post),
            )
            .order_by(Article.id.asc())
        )
        .scalars()
        .all()
    )
    candidates: list[TravelSyncCandidate] = []
    for article in rows:
        blog_id = int(article.blog_id or 0)
        language = TRAVEL_LANGUAGE_BY_BLOG_ID.get(blog_id)
        if language is None:
            continue
        title_tokens, year_tokens = _tokenize(article.title, article.slug)
        label_tokens, _ = _tokenize(*[str(label) for label in (article.labels or [])])
        candidates.append(
            TravelSyncCandidate(
                article_id=int(article.id),
                blog_id=blog_id,
                language=language,
                slug=str(article.slug or "").strip(),
                title=str(article.title or "").strip(),
                labels=tuple(str(label).strip() for label in (article.labels or []) if str(label).strip()),
                category_key=normalize_travel_category_key(article.editorial_category_key),
                hero_url=_normalize_hero_url(article.image.public_url if article.image else ""),
                status=_normalize_post_status(article),
                created_at=article.created_at if isinstance(article.created_at, datetime) else datetime.now(UTC),
                source_article_id=int(article.travel_sync_source_article_id or 0) or None,
                existing_group_key=str(article.travel_sync_group_key or "").strip() or None,
                title_tokens=title_tokens,
                label_tokens=label_tokens,
                year_tokens=year_tokens,
            )
        )
    return candidates


def build_travel_sync_groups(
    db: Session,
    *,
    blog_ids: tuple[int, ...] = (34, 36, 37),
    source_languages: tuple[str, ...] = TRAVEL_SUPPORTED_LANGUAGES,
    target_languages: tuple[str, ...] = TRAVEL_SUPPORTED_LANGUAGES,
) -> tuple[list[TravelSyncGroup], list[TravelSyncBacklogItem], dict[str, Any]]:
    scoped_blog_ids = tuple(sorted({int(blog_id) for blog_id in blog_ids if int(blog_id) in TRAVEL_BLOG_IDS}))
    if not scoped_blog_ids:
        raise ValueError("Travel sync grouping requires blog_id in {34, 36, 37}.")
    normalized_source_languages = tuple(
        language for language in TRAVEL_SUPPORTED_LANGUAGES if language in {item.strip().lower() for item in source_languages}
    )
    normalized_target_languages = tuple(
        language for language in TRAVEL_SUPPORTED_LANGUAGES if language in {item.strip().lower() for item in target_languages}
    )
    if not normalized_source_languages or not normalized_target_languages:
        raise ValueError("Travel sync source/target languages cannot be empty.")

    candidates = _load_candidates(db, blog_ids=scoped_blog_ids)
    by_id = {candidate.article_id: candidate for candidate in candidates}
    parent, rank = _union_find(list(by_id.keys()))

    for candidate in candidates:
        source_article_id = int(candidate.source_article_id or 0)
        if source_article_id > 0 and source_article_id in by_id:
            _union(parent, rank, candidate.article_id, source_article_id)

    hero_url_map: dict[str, list[int]] = {}
    for candidate in candidates:
        if not candidate.hero_url:
            continue
        hero_url_map.setdefault(candidate.hero_url, []).append(candidate.article_id)
    for article_ids in hero_url_map.values():
        if len(article_ids) < 2:
            continue
        first = article_ids[0]
        for item in article_ids[1:]:
            _union(parent, rank, first, item)

    for left_index in range(len(candidates)):
        left = candidates[left_index]
        for right_index in range(left_index + 1, len(candidates)):
            right = candidates[right_index]
            if left.language == right.language:
                continue
            if _is_strong_similarity(left, right):
                _union(parent, rank, left.article_id, right.article_id)

    grouped: dict[int, list[TravelSyncCandidate]] = {}
    for candidate in candidates:
        root = _find(parent, candidate.article_id)
        grouped.setdefault(root, []).append(candidate)

    groups: list[TravelSyncGroup] = []
    backlog: list[TravelSyncBacklogItem] = []
    for members in grouped.values():
        ordered_members = sorted(members, key=lambda item: item.article_id)
        best_by_language: dict[str, TravelSyncCandidate] = {}
        for language in TRAVEL_SUPPORTED_LANGUAGES:
            bucket = [item for item in ordered_members if item.language == language]
            if bucket:
                best_by_language[language] = _pick_best_member(bucket)
        representative = _pick_best_member(list(best_by_language.values()) or ordered_members)
        group_key = _derive_group_key(ordered_members)
        missing_languages = tuple(language for language in normalized_target_languages if language not in best_by_language)
        group = TravelSyncGroup(
            group_key=group_key,
            source_article_id=representative.article_id,
            source_blog_id=representative.blog_id,
            source_language=representative.language,
            member_article_ids=tuple(item.article_id for item in ordered_members),
            members_by_language={language: member.article_id for language, member in best_by_language.items()},
            missing_languages=missing_languages,
            category_key=normalize_travel_category_key(representative.category_key),
            hero_url=representative.hero_url,
        )
        groups.append(group)
        source_candidates = [best_by_language[lang] for lang in normalized_source_languages if lang in best_by_language]
        if not source_candidates:
            continue
        source = _pick_best_member(source_candidates)
        for target_language in missing_languages:
            target_blog_id = TRAVEL_BLOG_ID_BY_LANGUAGE.get(target_language)
            if not target_blog_id:
                continue
            backlog.append(
                TravelSyncBacklogItem(
                    group_key=group_key,
                    source_article_id=source.article_id,
                    source_blog_id=source.blog_id,
                    source_language=source.language,
                    source_slug=source.slug,
                    source_title=source.title,
                    source_hero_url=source.hero_url,
                    category_key=normalize_travel_category_key(source.category_key),
                    target_language=target_language,
                    target_blog_id=target_blog_id,
                )
            )

    groups.sort(key=lambda item: item.group_key)
    backlog.sort(key=lambda item: (STATUS_WEIGHT.get(by_id[item.source_article_id].status, 0), item.group_key, item.target_language), reverse=True)

    summary = {
        "article_count": len(candidates),
        "group_count": len(groups),
        "backlog_count": len(backlog),
        "source_languages": list(normalized_source_languages),
        "target_languages": list(normalized_target_languages),
        "per_language_article_count": {
            language: sum(1 for item in candidates if item.language == language) for language in TRAVEL_SUPPORTED_LANGUAGES
        },
        "missing_targets": {
            language: sum(1 for item in backlog if item.target_language == language) for language in TRAVEL_SUPPORTED_LANGUAGES
        },
    }
    return groups, backlog, summary


def apply_travel_sync_group_links(
    db: Session,
    *,
    groups: list[TravelSyncGroup],
    commit: bool = True,
) -> dict[str, int]:
    all_article_ids = {article_id for group in groups for article_id in group.member_article_ids}
    rows = (
        db.execute(select(Article).where(Article.id.in_(list(all_article_ids))))
        .scalars()
        .all()
    )
    by_id = {int(article.id): article for article in rows}
    updated = 0
    for group in groups:
        for article_id in group.member_article_ids:
            article = by_id.get(int(article_id))
            if article is None:
                continue
            expected_group_key = str(group.group_key).strip()
            expected_source_id = None if int(article_id) == int(group.source_article_id) else int(group.source_article_id)
            changed = False
            if str(article.travel_sync_group_key or "").strip() != expected_group_key:
                article.travel_sync_group_key = expected_group_key
                changed = True
            current_source_id = int(article.travel_sync_source_article_id or 0) or None
            if current_source_id != expected_source_id:
                article.travel_sync_source_article_id = expected_source_id
                changed = True
            if changed:
                db.add(article)
                updated += 1
    if commit:
        db.commit()
    else:
        db.flush()
    return {"updated_article_count": updated}


def _parse_clock_text(value: str | None, *, fallback: str) -> time:
    raw = str(value or "").strip()
    if not raw:
        raw = fallback
    try:
        parsed = datetime.strptime(raw, "%H:%M").time()
    except ValueError:
        parsed = datetime.strptime(fallback, "%H:%M").time()
    return parsed.replace(second=0, microsecond=0)


def _largest_remainder_daily_distribution(total: int, days: int) -> list[int]:
    safe_total = max(int(total or 0), 0)
    safe_days = max(int(days or 0), 1)
    base = safe_total // safe_days
    remainder = safe_total % safe_days
    return [base + (1 if index < remainder else 0) for index in range(safe_days)]


def build_missing_target_daily_quota_map(
    *,
    missing_targets: dict[str, int],
    days: int = 7,
) -> dict[str, list[int]]:
    safe_days = max(int(days or 0), 1)
    quotas: dict[str, list[int]] = {}
    for language in TRAVEL_SUPPORTED_LANGUAGES:
        quotas[language] = _largest_remainder_daily_distribution(
            int(missing_targets.get(language, 0) or 0),
            safe_days,
        )
    return quotas


def _extract_daily_backlog_quota(
    *,
    backlog: list[TravelSyncBacklogItem],
    days: int,
) -> tuple[dict[str, int], dict[str, list[int]]]:
    missing_targets = {language: 0 for language in TRAVEL_SUPPORTED_LANGUAGES}
    for item in backlog:
        language = str(item.target_language or "").strip().lower()
        if language in missing_targets:
            missing_targets[language] += 1
    return missing_targets, build_missing_target_daily_quota_map(missing_targets=missing_targets, days=days)


def _travel_sync_slot_signature(item: TravelSyncBacklogItem) -> tuple[int, str, str]:
    return (
        int(item.source_article_id),
        str(item.group_key).strip(),
        str(item.target_language).strip().lower(),
    )


def _is_managed_travel_sync_slot(slot: ContentPlanSlot) -> bool:
    payload = slot.result_payload if isinstance(slot.result_payload, dict) else {}
    marker = payload.get("travel_cross_sync")
    return isinstance(marker, dict)


def _extract_slot_signatures(slots: list[ContentPlanSlot]) -> set[tuple[int, str, str]]:
    signatures: set[tuple[int, str, str]] = set()
    for slot in slots:
        payload = slot.result_payload if isinstance(slot.result_payload, dict) else {}
        marker = payload.get("travel_cross_sync")
        if not isinstance(marker, dict):
            continue
        signatures.add(
            (
                int(marker.get("source_article_id") or 0),
                str(marker.get("group_key") or "").strip(),
                str(marker.get("target_language") or "").strip().lower(),
            )
        )
    return signatures


def _resequence_day_slots(slots: list[ContentPlanSlot]) -> None:
    ordered = sorted(
        slots,
        key=lambda row: (
            row.scheduled_for or datetime.max.replace(tzinfo=UTC),
            int(row.slot_order or 0),
            int(row.id or 0),
        ),
    )
    for index, slot in enumerate(ordered, start=1):
        slot.slot_order = index


def seed_travel_weekly_planner_slots(
    db: Session,
    *,
    backlog: list[TravelSyncBacklogItem],
    days: int = 7,
    slot_seed_mode: str = "append",
    slot_gap_minutes: int = 10,
    slot_start_times_by_language: dict[str, str] | None = None,
    start_date: date | None = None,
    commit: bool = False,
) -> tuple[list[TravelSyncBacklogItem], dict[str, Any]]:
    safe_days = max(int(days or 0), 1)
    safe_gap = max(int(slot_gap_minutes or 0), 1)
    normalized_mode = str(slot_seed_mode or "append").strip().lower()
    if normalized_mode not in {"append", "replace"}:
        normalized_mode = "append"

    merged_start_times = dict(TRAVEL_PLANNER_DEFAULT_START_TIMES)
    if isinstance(slot_start_times_by_language, dict):
        for language, raw_value in slot_start_times_by_language.items():
            normalized_language = str(language or "").strip().lower()
            if normalized_language in TRAVEL_SUPPORTED_LANGUAGES and str(raw_value or "").strip():
                merged_start_times[normalized_language] = str(raw_value).strip()

    clock_by_language = {
        language: _parse_clock_text(
            merged_start_times.get(language),
            fallback=TRAVEL_PLANNER_DEFAULT_START_TIMES[language],
        )
        for language in TRAVEL_SUPPORTED_LANGUAGES
    }

    reference_date = start_date or datetime.now(TRAVEL_PLANNER_TIMEZONE).date()
    by_language: dict[str, list[TravelSyncBacklogItem]] = {language: [] for language in TRAVEL_SUPPORTED_LANGUAGES}
    for item in backlog:
        language = str(item.target_language or "").strip().lower()
        if language not in by_language:
            continue
        by_language[language].append(item)

    missing_targets, daily_quota_map = _extract_daily_backlog_quota(backlog=backlog, days=safe_days)

    assigned: list[TravelSyncBacklogItem] = []
    assignments_by_day: dict[str, dict[str, list[TravelSyncBacklogItem]]] = {}
    for day_index in range(safe_days):
        plan_date = reference_date + timedelta(days=day_index)
        day_key = plan_date.isoformat()
        assignments_by_day[day_key] = {language: [] for language in TRAVEL_SUPPORTED_LANGUAGES}
        for language in TRAVEL_SUPPORTED_LANGUAGES:
            quota = int(daily_quota_map.get(language, [0] * safe_days)[day_index] or 0)
            if quota <= 0:
                continue
            base_local = datetime.combine(plan_date, clock_by_language[language], tzinfo=TRAVEL_PLANNER_TIMEZONE)
            for slot_index in range(quota):
                if not by_language[language]:
                    break
                item = by_language[language].pop(0)
                item.scheduled_for = (base_local + timedelta(minutes=safe_gap * slot_index)).astimezone(UTC)
                assignments_by_day[day_key][language].append(item)
                assigned.append(item)

    summary: dict[str, Any] = {
        "enabled": True,
        "mode": normalized_mode,
        "days": safe_days,
        "slot_gap_minutes": safe_gap,
        "start_date": reference_date.isoformat(),
        "start_times": dict(merged_start_times),
        "missing_targets": dict(missing_targets),
        "daily_quota": daily_quota_map,
        "assigned_count": len(assigned),
        "daily_assignments": {
            day_key: {
                language: len(items)
                for language, items in language_map.items()
            }
            for day_key, language_map in assignments_by_day.items()
        },
        "created_slot_count": 0,
        "skipped_duplicate_slot_count": 0,
        "removed_slot_count": 0,
    }

    if not commit:
        return assigned, summary

    created_slot_count = 0
    skipped_duplicate_count = 0
    removed_slot_count = 0
    for day_key, language_map in assignments_by_day.items():
        plan_date = date.fromisoformat(day_key)
        for language in TRAVEL_SUPPORTED_LANGUAGES:
            items = language_map.get(language) or []
            if not items:
                continue
            blog_id = int(TRAVEL_BLOG_ID_BY_LANGUAGE[language])
            channel_id = TRAVEL_CHANNEL_BY_BLOG_ID.get(blog_id, f"blogger:{blog_id}")
            plan_day = (
                db.execute(
                    select(ContentPlanDay)
                    .where(
                        ContentPlanDay.channel_id == channel_id,
                        ContentPlanDay.plan_date == plan_date,
                    )
                    .options(selectinload(ContentPlanDay.slots))
                )
                .scalar_one_or_none()
            )
            if plan_day is None:
                plan_day = ContentPlanDay(
                    channel_id=channel_id,
                    blog_id=blog_id,
                    plan_date=plan_date,
                    target_post_count=0,
                    status="planned",
                )
                db.add(plan_day)
                db.flush()
                plan_day = (
                    db.execute(
                        select(ContentPlanDay)
                        .where(ContentPlanDay.id == int(plan_day.id))
                        .options(selectinload(ContentPlanDay.slots))
                    )
                    .scalar_one()
                )

            existing_slots = list(plan_day.slots or [])
            if normalized_mode == "replace":
                removable_slots = [
                    slot
                    for slot in existing_slots
                    if _is_managed_travel_sync_slot(slot)
                    and str(slot.status or "").strip().lower() in {"planned", "brief_ready", "canceled", "failed"}
                    and int(slot.job_id or 0) <= 0
                    and int(slot.article_id or 0) <= 0
                ]
                for slot in removable_slots:
                    db.delete(slot)
                if removable_slots:
                    db.flush()
                    removed_slot_count += len(removable_slots)
                existing_slots = [slot for slot in existing_slots if slot not in removable_slots]

            existing_signatures = _extract_slot_signatures(existing_slots)
            next_slot_order = max((int(slot.slot_order or 0) for slot in existing_slots), default=0) + 1

            for item in items:
                signature = _travel_sync_slot_signature(item)
                if signature in existing_signatures:
                    skipped_duplicate_count += 1
                    continue
                context_note = (
                    f"travel_cross_sync group={item.group_key}; source_article_id={item.source_article_id}; "
                    f"source_language={item.source_language}; target_language={item.target_language}; "
                    f"reuse_hero_url={item.source_hero_url or 'none'}"
                )
                slot = ContentPlanSlot(
                    plan_day_id=int(plan_day.id),
                    theme_id=None,
                    category_key=normalize_travel_category_key(item.category_key),
                    category_name=normalize_travel_category_key(item.category_key).title(),
                    category_color=None,
                    scheduled_for=item.scheduled_for,
                    slot_order=next_slot_order,
                    status="brief_ready",
                    brief_topic=str(item.source_title or "").strip(),
                    brief_audience=default_target_audience_for_language(item.target_language),
                    brief_information_level="practical",
                    brief_extra_context=context_note,
                    article_id=None,
                    job_id=None,
                    error_message=None,
                    result_payload={
                        "travel_cross_sync": {
                            "group_key": str(item.group_key),
                            "source_article_id": int(item.source_article_id),
                            "source_blog_id": int(item.source_blog_id),
                            "source_language": str(item.source_language),
                            "source_slug": str(item.source_slug),
                            "target_blog_id": int(item.target_blog_id),
                            "target_language": str(item.target_language),
                            "source_hero_url": str(item.source_hero_url or "").strip(),
                            "category_key": normalize_travel_category_key(item.category_key),
                        }
                    },
                )
                db.add(slot)
                next_slot_order += 1
                created_slot_count += 1
                existing_signatures.add(signature)

            db.flush()
            refreshed_day = (
                db.execute(
                    select(ContentPlanDay)
                    .where(ContentPlanDay.id == int(plan_day.id))
                    .options(selectinload(ContentPlanDay.slots))
                )
                .scalar_one()
            )
            resequence_targets = list(refreshed_day.slots or [])
            _resequence_day_slots(resequence_targets)
            refreshed_day.target_post_count = len(resequence_targets)
            db.add(refreshed_day)

    db.commit()
    summary["created_slot_count"] = created_slot_count
    summary["skipped_duplicate_slot_count"] = skipped_duplicate_count
    summary["removed_slot_count"] = removed_slot_count
    return assigned, summary


def assign_backlog_schedule_slots(
    db: Session,
    *,
    backlog: list[TravelSyncBacklogItem],
    min_schedule_gap_minutes: int = 10,
) -> list[TravelSyncBacklogItem]:
    gap = max(int(min_schedule_gap_minutes), 1)
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    initial_cursor: dict[int, datetime] = {}
    for blog_id in TRAVEL_BLOG_IDS:
        latest = db.execute(
            select(BloggerPost.scheduled_for)
            .where(
                BloggerPost.blog_id == blog_id,
                BloggerPost.post_status == PostStatus.SCHEDULED,
                BloggerPost.scheduled_for.is_not(None),
            )
            .order_by(BloggerPost.scheduled_for.desc())
            .limit(1)
        ).scalar_one_or_none()
        latest_dt = latest if isinstance(latest, datetime) else None
        baseline = now + timedelta(minutes=20)
        initial_cursor[blog_id] = max(baseline, (latest_dt + timedelta(minutes=gap)) if latest_dt else baseline)

    assigned: list[TravelSyncBacklogItem] = []
    for item in backlog:
        cursor = initial_cursor.get(item.target_blog_id, now + timedelta(minutes=20))
        item.scheduled_for = cursor
        initial_cursor[item.target_blog_id] = cursor + timedelta(minutes=gap)
        assigned.append(item)
    return assigned


def enqueue_travel_cross_sync_jobs(
    db: Session,
    *,
    backlog: list[TravelSyncBacklogItem],
    text_generation_route: str,
    publish_mode: str = "scheduled",
    max_items_per_run: int | None = None,
    retry_failed_only: bool = False,
) -> dict[str, Any]:
    normalized_route = normalize_travel_text_generation_route(text_generation_route)
    normalized_publish_mode = str(publish_mode or "scheduled").strip().lower()
    target_mode = PublishMode.PUBLISH if normalized_publish_mode in {"scheduled", "publish", "published"} else PublishMode.DRAFT
    requested_items = backlog[: max(int(max_items_per_run or len(backlog)), 0)]

    recent_jobs = (
        db.execute(
            select(Job)
            .where(Job.blog_id.in_(list(TRAVEL_BLOG_IDS)))
            .order_by(Job.id.desc())
            .limit(5000)
        )
        .scalars()
        .all()
    )
    existing_job_keys: set[tuple[int, str]] = set()
    failed_job_keys: set[tuple[int, str]] = set()
    for job in recent_jobs:
        prompts = job.raw_prompts if isinstance(job.raw_prompts, dict) else {}
        sync_payload = prompts.get(TRAVEL_SYNC_KEY) if isinstance(prompts, dict) else None
        if not isinstance(sync_payload, dict):
            continue
        group_key = str(sync_payload.get("group_key") or "").strip()
        target_language = str(sync_payload.get("target_language") or "").strip().lower()
        target_blog_id = TRAVEL_BLOG_ID_BY_LANGUAGE.get(target_language, int(job.blog_id or 0))
        if not group_key or int(target_blog_id or 0) <= 0:
            continue
        key = (int(target_blog_id), group_key)
        existing_job_keys.add(key)
        if str(job.status or "").strip().upper() == "FAILED":
            failed_job_keys.add(key)

    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for item in requested_items:
        key = (int(item.target_blog_id), str(item.group_key))
        if retry_failed_only and key not in failed_job_keys:
            skipped.append(
                {
                    "group_key": item.group_key,
                    "target_blog_id": item.target_blog_id,
                    "target_language": item.target_language,
                    "reason": "retry_failed_only_skip",
                }
            )
            continue
        if not retry_failed_only and key in existing_job_keys:
            skipped.append(
                {
                    "group_key": item.group_key,
                    "target_blog_id": item.target_blog_id,
                    "target_language": item.target_language,
                    "reason": "existing_job",
                }
            )
            continue

        source = (
            db.execute(
                select(Article)
                .where(Article.id == int(item.source_article_id))
                .options(selectinload(Article.blog), selectinload(Article.image))
            )
            .scalar_one_or_none()
        )
        if source is None:
            skipped.append(
                {
                    "group_key": item.group_key,
                    "target_blog_id": item.target_blog_id,
                    "target_language": item.target_language,
                    "reason": "missing_source_article",
                }
            )
            continue

        keyword = str(source.title or item.source_title or "").strip() or str(source.slug or item.source_slug or "travel-topic")
        topic = db.execute(
            select(Topic)
            .where(
                Topic.blog_id == int(item.target_blog_id),
                Topic.keyword == keyword,
            )
        ).scalar_one_or_none()
        if topic is None:
            topic = Topic(
                blog_id=int(item.target_blog_id),
                keyword=keyword,
                reason=f"travel_cross_sync source_article_id={item.source_article_id}",
                editorial_category_key=normalize_travel_category_key(item.category_key),
                editorial_category_label=normalize_travel_category_key(item.category_key).title(),
            )
            db.add(topic)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                topic = db.execute(
                    select(Topic).where(
                        Topic.blog_id == int(item.target_blog_id),
                        Topic.keyword == keyword,
                    )
                ).scalar_one_or_none()
                if topic is None:
                    raise

        planner_brief = {
            "topic": keyword,
            "audience": default_target_audience_for_language(item.target_language),
            "information_level": "practical",
            "category_key": normalize_travel_category_key(item.category_key),
            "category_name": normalize_travel_category_key(item.category_key).title(),
            "bundle_key": item.group_key,
            "facts": [],
            "prohibited_claims": [],
            "context_notes": (
                f"travel_cross_sync group={item.group_key}; source_article_id={item.source_article_id}; "
                f"source_language={item.source_language}; target_language={item.target_language}; "
                f"reuse_hero_url={item.source_hero_url or 'none'}"
            ),
            "scheduled_for": item.scheduled_for.isoformat() if item.scheduled_for and target_mode == PublishMode.PUBLISH else None,
        }
        raw_prompts: dict[str, Any] = {
            PLANNER_BRIEF_KEY: planner_brief,
            TRAVEL_SYNC_KEY: {
                "group_key": item.group_key,
                "source_article_id": int(item.source_article_id),
                "source_blog_id": int(item.source_blog_id),
                "source_language": item.source_language,
                "target_language": item.target_language,
                "source_hero_url": item.source_hero_url,
                "text_generation_route": normalized_route,
            },
        }
        if target_mode == PublishMode.PUBLISH and item.scheduled_for is not None:
            raw_prompts[PIPELINE_SCHEDULE_KEY] = {
                "mode": "publish",
                "scheduled_for": item.scheduled_for.isoformat(),
                "slot_index": 0,
                "interval_minutes": 10,
                "topic_count": 1,
            }

        try:
            job = create_job(
                db,
                blog_id=int(item.target_blog_id),
                keyword=keyword,
                topic_id=int(topic.id),
                publish_mode=target_mode,
                raw_prompts=raw_prompts,
            )
            created.append(
                {
                    "job_id": int(job.id),
                    "topic_id": int(topic.id),
                    "group_key": item.group_key,
                    "target_blog_id": int(item.target_blog_id),
                    "target_language": item.target_language,
                    "source_article_id": int(item.source_article_id),
                    "scheduled_for": item.scheduled_for.isoformat() if item.scheduled_for else None,
                    "text_generation_route": normalized_route,
                }
            )
            existing_job_keys.add(key)
        except Exception as exc:  # noqa: BLE001
            skipped.append(
                {
                    "group_key": item.group_key,
                    "target_blog_id": item.target_blog_id,
                    "target_language": item.target_language,
                    "reason": "job_create_failed",
                    "detail": str(exc),
                }
            )

    return {
        "requested_count": len(requested_items),
        "created_count": len(created),
        "skipped_count": len(skipped),
        "created": created,
        "skipped": skipped,
        "text_generation_route": normalized_route,
        "publish_mode": target_mode.value,
    }
