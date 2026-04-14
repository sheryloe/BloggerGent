from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import Article, SyncedCloudflarePost

ARTICLE_PATTERN_VERSION = 1


@dataclass(frozen=True, slots=True)
class ArticlePatternDefinition:
    pattern_id: str
    label: str
    summary: str
    html_hint: str


@dataclass(frozen=True, slots=True)
class ArticlePatternSelection:
    pattern_id: str
    pattern_version: int
    label: str
    summary: str
    html_hint: str
    allowed_pattern_ids: tuple[str, ...]
    recent_pattern_ids: tuple[str, ...]


ARTICLE_PATTERNS: dict[str, ArticlePatternDefinition] = {
    "experience-diary": ArticlePatternDefinition(
        pattern_id="experience-diary",
        label="Experience Diary",
        summary="A blog-style narrative that follows lived experience, movement, and reflection.",
        html_hint="section.callout, div.card-grid, aside.caution-box",
    ),
    "problem-solution": ArticlePatternDefinition(
        pattern_id="problem-solution",
        label="Problem Solution",
        summary="A practical structure that moves from problem definition to setup, solution, and applied tips.",
        html_hint="section.callout, div.comparison-table, section.route-steps",
    ),
    "route-timeline": ArticlePatternDefinition(
        pattern_id="route-timeline",
        label="Route Timeline",
        summary="A visit-oriented structure driven by time order, route flow, and checkpoints.",
        html_hint="section.timeline, section.route-steps, div.callout",
    ),
    "spot-card-grid": ArticlePatternDefinition(
        pattern_id="spot-card-grid",
        label="Spot Card Grid",
        summary="A comparison-led structure that breaks places or tools into clear cards.",
        html_hint="div.card-grid, div.fact-box, table.comparison-table",
    ),
    "mystery-dossier": ArticlePatternDefinition(
        pattern_id="mystery-dossier",
        label="Mystery Dossier",
        summary="A dossier-style mystery structure that alternates story movement with documented records.",
        html_hint="section.timeline, aside.fact-box, blockquote.quote-box",
    ),
    "claim-evidence-board": ArticlePatternDefinition(
        pattern_id="claim-evidence-board",
        label="Claim Evidence Board",
        summary="An evidence board structure that separates claims, records, counterpoints, and uncertainty.",
        html_hint="table.comparison-table, div.fact-box, aside.caution-box",
    ),
    "three-expert-chat": ArticlePatternDefinition(
        pattern_id="three-expert-chat",
        label="Three Expert Chat",
        summary="A three-voice chat structure that lets contrasting viewpoints surface naturally.",
        html_hint="div.chat-thread, aside.fact-box, table.comparison-table",
    ),
    "two-voice-market-chat": ArticlePatternDefinition(
        pattern_id="two-voice-market-chat",
        label="Two Voice Market Chat",
        summary="A two-voice market dialogue that frames one stock through aggressive and conservative viewpoints.",
        html_hint="div.chat-thread, table.comparison-table, aside.fact-box",
    ),
    "reflective-monologue": ArticlePatternDefinition(
        pattern_id="reflective-monologue",
        label="Reflective Monologue",
        summary="A reflective monologue that follows thought, feeling, and quiet insight.",
        html_hint="blockquote.quote-box, section.callout, aside.caution-box",
    ),
    "exhibition-field-guide": ArticlePatternDefinition(
        pattern_id="exhibition-field-guide",
        label="Exhibition Field Guide",
        summary="A field-guide structure that walks the reader through an exhibition, festival, or space.",
        html_hint="section.route-steps, div.card-grid, section.event-checklist",
    ),
    "policy-benefit-explainer": ArticlePatternDefinition(
        pattern_id="policy-benefit-explainer",
        label="Policy Benefit Explainer",
        summary="A policy explainer that breaks down eligibility, timing, amount, and application flow.",
        html_hint="section.policy-summary, div.fact-box, section.event-checklist",
    ),
}


_BLOGGER_PATTERN_MAP: dict[tuple[str, str], tuple[str, ...]] = {
    ("korea_travel", "travel"): ("experience-diary", "route-timeline", "spot-card-grid"),
    ("korea_travel", "culture"): ("experience-diary", "route-timeline", "exhibition-field-guide"),
    ("korea_travel", "food"): ("experience-diary", "spot-card-grid", "route-timeline"),
    ("world_mystery", "case-files"): ("mystery-dossier", "claim-evidence-board"),
    ("world_mystery", "legends-lore"): ("mystery-dossier", "claim-evidence-board"),
    ("world_mystery", "mystery-archives"): ("claim-evidence-board", "mystery-dossier"),
}

_CLOUDFLARE_PATTERN_MAP: dict[str, tuple[str, ...]] = {
    "개발과-프로그래밍": ("problem-solution", "spot-card-grid"),
    "여행과-기록": ("experience-diary", "route-timeline", "spot-card-grid", "exhibition-field-guide"),
    "축제와-현장": ("experience-diary", "route-timeline", "spot-card-grid", "exhibition-field-guide"),
    "문화와-공간": ("exhibition-field-guide", "experience-diary", "spot-card-grid"),
    "미스테리아-스토리": ("mystery-dossier", "claim-evidence-board"),
    "주식의-흐름": ("three-expert-chat",),
    "나스닥의-흐름": ("two-voice-market-chat",),
    "크립토의-흐름": ("problem-solution", "three-expert-chat"),
    "동그리의-생각": ("reflective-monologue",),
    "삶을-유용하게": ("experience-diary", "spot-card-grid", "problem-solution"),
    "삶의-기름칠": ("policy-benefit-explainer",),
    "일상과-메모": ("reflective-monologue", "experience-diary"),
}


def _normalize_key(value: str | None) -> str:
    return str(value or "").strip().casefold()


def _resolve_pattern_definition(pattern_id: str) -> ArticlePatternDefinition:
    return ARTICLE_PATTERNS.get(pattern_id, ARTICLE_PATTERNS["problem-solution"])


def _pick_pattern(*, allowed_ids: Sequence[str], recent_ids: Sequence[str], rotation_seed: int = 0) -> str:
    normalized_recent = [_normalize_key(item) for item in recent_ids if str(item or "").strip()]
    for candidate in allowed_ids:
        if _normalize_key(candidate) not in normalized_recent:
            return candidate
    if not allowed_ids:
        return "problem-solution"
    index = rotation_seed % len(allowed_ids)
    return allowed_ids[index]


def _recent_blogger_pattern_ids(
    db: Session,
    *,
    blog_id: int,
    editorial_category_key: str | None,
    limit: int = 3,
) -> tuple[str, ...]:
    statement = select(Article.article_pattern_id).where(Article.blog_id == blog_id, Article.article_pattern_id.is_not(None))
    normalized_editorial_key = str(editorial_category_key or "").strip()
    if normalized_editorial_key:
        statement = statement.where(Article.editorial_category_key == normalized_editorial_key)
    rows = db.execute(statement.order_by(Article.created_at.desc(), Article.id.desc()).limit(limit)).scalars().all()
    return tuple(str(item).strip() for item in rows if str(item or "").strip())


def _recent_cloudflare_pattern_ids(
    db: Session,
    *,
    category_slug: str | None,
    limit: int = 3,
) -> tuple[str, ...]:
    normalized_slug = str(category_slug or "").strip()
    statement = select(SyncedCloudflarePost.article_pattern_id).where(
        SyncedCloudflarePost.article_pattern_id.is_not(None)
    )
    if normalized_slug:
        statement = statement.where(
            (SyncedCloudflarePost.canonical_category_slug == normalized_slug)
            | (SyncedCloudflarePost.category_slug == normalized_slug)
        )
    rows = (
        db.execute(
            statement.order_by(
                SyncedCloudflarePost.published_at.desc().nullslast(),
                SyncedCloudflarePost.updated_at_remote.desc().nullslast(),
                SyncedCloudflarePost.id.desc(),
            ).limit(limit)
        )
        .scalars()
        .all()
    )
    return tuple(str(item).strip() for item in rows if str(item or "").strip())


def select_blogger_article_pattern(
    db: Session,
    *,
    blog_id: int,
    profile_key: str | None,
    editorial_category_key: str | None,
) -> ArticlePatternSelection:
    normalized_profile = str(profile_key or "").strip()
    normalized_editorial_key = str(editorial_category_key or "").strip()
    allowed_ids = _BLOGGER_PATTERN_MAP.get(
        (normalized_profile, normalized_editorial_key),
        ("problem-solution", "spot-card-grid") if normalized_profile == "custom" else ("problem-solution",),
    )
    recent_ids = _recent_blogger_pattern_ids(
        db,
        blog_id=blog_id,
        editorial_category_key=normalized_editorial_key,
    )
    chosen_id = _pick_pattern(allowed_ids=allowed_ids, recent_ids=recent_ids, rotation_seed=len(recent_ids))
    definition = _resolve_pattern_definition(chosen_id)
    return ArticlePatternSelection(
        pattern_id=definition.pattern_id,
        pattern_version=ARTICLE_PATTERN_VERSION,
        label=definition.label,
        summary=definition.summary,
        html_hint=definition.html_hint,
        allowed_pattern_ids=tuple(allowed_ids),
        recent_pattern_ids=recent_ids,
    )


def select_cloudflare_article_pattern(
    db: Session,
    *,
    category_slug: str | None,
) -> ArticlePatternSelection:
    normalized_slug = str(category_slug or "").strip()
    allowed_ids = _CLOUDFLARE_PATTERN_MAP.get(normalized_slug, ("problem-solution", "spot-card-grid"))
    recent_ids = _recent_cloudflare_pattern_ids(
        db,
        category_slug=normalized_slug,
    )
    total_posts = db.execute(
        select(func.count(SyncedCloudflarePost.id)).where(
            (SyncedCloudflarePost.canonical_category_slug == normalized_slug)
            | (SyncedCloudflarePost.category_slug == normalized_slug)
        )
    ).scalar_one()
    chosen_id = _pick_pattern(allowed_ids=allowed_ids, recent_ids=recent_ids, rotation_seed=int(total_posts or 0))
    definition = _resolve_pattern_definition(chosen_id)
    return ArticlePatternSelection(
        pattern_id=definition.pattern_id,
        pattern_version=ARTICLE_PATTERN_VERSION,
        label=definition.label,
        summary=definition.summary,
        html_hint=definition.html_hint,
        allowed_pattern_ids=tuple(allowed_ids),
        recent_pattern_ids=recent_ids,
    )


def build_article_pattern_prompt_block(selection: ArticlePatternSelection) -> str:
    allowed = ", ".join(selection.allowed_pattern_ids)
    recent = ", ".join(selection.recent_pattern_ids) if selection.recent_pattern_ids else "none"
    return (
        "[Article pattern registry]\n"
        f"- Use this pattern for this draft: {selection.pattern_id} (v{selection.pattern_version}).\n"
        f"- Pattern summary: {selection.summary}.\n"
        f"- Preferred HTML structures: {selection.html_hint}.\n"
        f"- Allowed patterns for this category: {allowed}.\n"
        f"- Recent pattern history to avoid repeating when possible: {recent}.\n"
        "- Return article_pattern_id and article_pattern_version in the JSON output.\n"
    )


def apply_pattern_defaults(output, selection: ArticlePatternSelection):
    if getattr(output, "article_pattern_id", None) in {None, ""}:
        output.article_pattern_id = selection.pattern_id
    if getattr(output, "article_pattern_version", None) in {None, 0}:
        output.article_pattern_version = selection.pattern_version
    return output
