from __future__ import annotations

import calendar
import html
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from statistics import mean
from sqlalchemy import and_, delete, func, select, tuple_
from sqlalchemy.orm import Session, selectinload

from app.services.ops.dedupe_utils import (
    canonicalize_url as canonicalize_dedupe_url,
    normalize_title as normalize_dedupe_title,
    pick_best_status as pick_best_dedupe_status,
    pick_preferred_url as pick_preferred_dedupe_url,
    status_priority as dedupe_status_priority,
    url_identity_key as dedupe_url_identity_key,
)
from app.models.entities import (
    AIUsageEvent,
    AuditLog,
    AnalyticsArticleFact,
    AnalyticsBlogMonthlyReport,
    AnalyticsThemeMonthlyStat,
    Article,
    Blog,
    BlogTheme,
    BloggerPost,
    ContentPlanDay,
    ContentPlanSlot,
    GoogleIndexUrlState,
    Image,
    Job,
    PublishQueueItem,
    SearchConsolePageMetric,
    SyncedBloggerPost,
)
from app.schemas.api import (
    AnalyticsArticleFactListResponse,
    AnalyticsArticleFactRead,
    AnalyticsBackfillRead,
    AnalyticsDailySummaryListResponse,
    AnalyticsDailySummaryRead,
    AnalyticsBlogMonthlyListResponse,
    AnalyticsBlogMonthlyReportRead,
    AnalyticsBlogMonthlySummaryRead,
    AnalyticsIntegratedKpiRead,
    AnalyticsIntegratedRead,
    AnalyticsThemeFilterOptionRead,
    AnalyticsThemeMonthlyStatRead,
    AnalyticsThemeWeightApplyResponse,
)


def _month_bounds(month: str) -> tuple[date, date]:
    start = datetime.strptime(f"{month}-01", "%Y-%m-%d").date()
    _, last_day = calendar.monthrange(start.year, start.month)
    return start, date(start.year, start.month, last_day)


def _month_range(month: str) -> tuple[datetime, datetime]:
    start_date, end_date = _month_bounds(month)
    return (
        datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc),
        datetime.combine(end_date, datetime.max.time()).replace(tzinfo=timezone.utc),
    )


def _month_key(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).strftime("%Y-%m") if value.tzinfo else value.strftime("%Y-%m")


def _safe_mean(values: list[float | int | None]) -> float | None:
    numeric = [float(value) for value in values if value is not None]
    if not numeric:
        return None
    return round(mean(numeric), 2)


def _coerce_score(value) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _score_below(value: float | None, threshold: float = 80.0) -> bool:
    return value is not None and value < threshold


def _theme_name_from_synced(post: SyncedBloggerPost) -> str:
    labels = [str(label).strip() for label in (post.labels or []) if str(label).strip()]
    return labels[0] if labels else "Uncategorized"


@dataclass(slots=True)
class MergedAnalyticsFactRow:
    fact: AnalyticsArticleFact
    source_facts: list[AnalyticsArticleFact]
    canonical_url: str | None


@dataclass(slots=True)
class MergedAnalyticsFactContext:
    article_map: dict[int, Article]
    synced_post_map: dict[int, SyncedBloggerPost]
    synced_post_by_url: dict[tuple[int, str], SyncedBloggerPost]
    live_urls_by_blog: dict[int, set[str]]
    index_state_map: dict[tuple[int, str], object]
    ctr_map: dict[tuple[int, str], object]


def _find_single_fact(db: Session, *, article_id: int | None = None, synced_post_id: int | None = None) -> AnalyticsArticleFact | None:
    query = select(AnalyticsArticleFact)
    if article_id is not None:
        query = query.where(AnalyticsArticleFact.article_id == article_id)
    if synced_post_id is not None:
        query = query.where(AnalyticsArticleFact.synced_post_id == synced_post_id)
    items = db.execute(query.order_by(AnalyticsArticleFact.id.asc())).scalars().all()
    if not items:
        return None
    if len(items) == 1:
        return items[0]
    merged = _merge_fact_group(items).fact
    primary = next((item for item in items if item.id == merged.id), items[0])
    _apply_merged_fact_values(primary, merged)
    for extra in items:
        if extra.id == primary.id:
            continue
        db.delete(extra)
    return primary


def _normalize_fact_status(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    if normalized in {"live", "published"}:
        return "published"
    return normalized


def _status_filter_values(status: str | None) -> list[str]:
    normalized = _normalize_fact_status(status)
    if not normalized:
        return []
    if normalized == "published":
        return ["published", "live"]
    return [normalized]


_STATUS_PRIORITY: dict[str, int] = {
    "published": 500,
    "live": 400,
    "scheduled": 300,
    "draft": 200,
    "failed": 100,
    "error": 100,
    "error_deleted": 100,
}


def _status_priority(value: str | None) -> int:
    return dedupe_status_priority(value, priorities=_STATUS_PRIORITY)


def _pick_preferred_status(facts: list[AnalyticsArticleFact]) -> str | None:
    winner_status: str | None = None
    winner_rank = -1
    winner_source_rank = -1
    winner_id = -1

    for fact in facts:
        raw_status = str(getattr(fact, "status", "") or "").strip().lower()
        if not raw_status:
            continue
        status_rank = _status_priority(raw_status)
        source_rank = 2 if str(fact.source_type or "").strip().lower() == "generated" else 1
        fact_id = int(getattr(fact, "id", 0) or 0)
        if (status_rank, source_rank, fact_id) > (winner_rank, winner_source_rank, winner_id):
            winner_status = raw_status
            winner_rank = status_rank
            winner_source_rank = source_rank
            winner_id = fact_id
    return winner_status


_WHITESPACE_RE = re.compile(r"\s+")


def _plain_text_for_ctr(html_body: str | None) -> str:
    if not html_body:
        return ""
    without_tags = re.sub(r"<[^>]+>", " ", html.unescape(html_body))
    return _WHITESPACE_RE.sub(" ", without_tags).strip()


def _tokenize_ctr_words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9가-힣]+", str(text or "").lower())


def _fallback_ctr_score(*, title: str, excerpt: str | None = None, html_body: str | None = None) -> dict[str, float]:
    title_text = str(title or "").strip()
    excerpt_text = str(excerpt or "").strip()
    body_text = _plain_text_for_ctr(html_body)
    title_words = _tokenize_ctr_words(title_text)
    combined_text = f"{title_text} {excerpt_text} {body_text[:600]}".lower()

    title_length = len(title_text)
    if 28 <= title_length <= 88 and 4 <= len(title_words) <= 14:
        headline_fit = 30
    elif 20 <= title_length <= 110 and len(title_words) >= 3:
        headline_fit = 24
    else:
        headline_fit = 16

    specificity_tokens = ("2026", "2025", "guide", "checklist", "timeline", "route", "map", "cost", "budget", "schedule", "best", "near", "seoul", "busan", "korea", "travel")
    specificity_hits = sum(1 for token in specificity_tokens if token in combined_text)
    specificity_score = 25 if specificity_hits >= 5 else 20 if specificity_hits >= 3 else 15 if specificity_hits >= 1 else 10

    intent_tokens = ("how", "why", "what", "where", "when", "best", "top", "guide", "tips", "checklist", "timeline", "review")
    intent_hits = sum(1 for token in intent_tokens if token in combined_text)
    click_intent_score = 20 if intent_hits >= 4 else 16 if intent_hits >= 2 else 12 if intent_hits >= 1 else 8

    if 70 <= len(excerpt_text) <= 180:
        excerpt_support_score = 15
    elif len(excerpt_text) >= 35:
        excerpt_support_score = 11
    else:
        excerpt_support_score = 7

    freshness_hits = len(re.findall(r"\b(?:18|19|20)\d{2}\b", combined_text))
    freshness_score = 10 if freshness_hits >= 2 else 7 if freshness_hits == 1 else 4
    ctr_score = max(0, min(100, headline_fit + specificity_score + click_intent_score + excerpt_support_score + freshness_score))
    return {"ctr_score": float(ctr_score)}


def _compute_ctr_score_payload(*, title: str, excerpt: str | None = None, html_body: str | None = None) -> dict[str, float]:
    try:
        from app.services.content.content_ops_service import compute_ctr_score as compute_ctr_score_impl
    except Exception:
        return _fallback_ctr_score(title=title, excerpt=excerpt, html_body=html_body)
    return compute_ctr_score_impl(title=title, excerpt=excerpt, html_body=html_body)


def _load_fact_enrichment_maps(
    db: Session,
    *,
    pairs: set[tuple[int, str]],
) -> tuple[dict[tuple[int, str], GoogleIndexUrlState], dict[tuple[int, str], SearchConsolePageMetric]]:
    if not pairs:
        return {}, {}

    normalized_pairs = {
        (blog_id, str(url or "").strip())
        for blog_id, url in pairs
        if str(url or "").strip() and not str(url or "").strip().startswith("noscheme:")
    }
    if not normalized_pairs:
        return {}, {}

    states = db.execute(
        select(GoogleIndexUrlState).where(tuple_(GoogleIndexUrlState.blog_id, GoogleIndexUrlState.url).in_(list(normalized_pairs)))
    ).scalars().all()
    ctr_rows = db.execute(
        select(SearchConsolePageMetric).where(tuple_(SearchConsolePageMetric.blog_id, SearchConsolePageMetric.url).in_(list(normalized_pairs)))
    ).scalars().all()

    state_map: dict[tuple[int, str], GoogleIndexUrlState] = {}
    ctr_map: dict[tuple[int, str], SearchConsolePageMetric] = {}
    for item in states:
        direct_key = (item.blog_id, item.url)
        state_map[direct_key] = item
        no_scheme_key = _fact_url_identity_key(item.url)
        if no_scheme_key:
            state_map[(item.blog_id, f"noscheme:{no_scheme_key}")] = item

    for item in ctr_rows:
        direct_key = (item.blog_id, item.url)
        ctr_map[direct_key] = item
        no_scheme_key = _fact_url_identity_key(item.url)
        if no_scheme_key:
            ctr_map[(item.blog_id, f"noscheme:{no_scheme_key}")] = item

    return state_map, ctr_map


def _canonicalize_fact_url(url: str | None) -> str | None:
    return canonicalize_dedupe_url(url)


def _fact_url_identity_key(url: str | None) -> str | None:
    return dedupe_url_identity_key(url)


def _pick_preferred_actual_url(facts: list[AnalyticsArticleFact]) -> str | None:
    return pick_preferred_dedupe_url(*[str(getattr(fact, "actual_url", "") or "").strip() for fact in facts])


def _normalize_title_for_merge(title: str | None) -> str | None:
    normalized = normalize_dedupe_title(title)
    return normalized or None


def _fact_match_signature(fact: AnalyticsArticleFact) -> tuple[int, str, str] | None:
    normalized_title = _normalize_title_for_merge(fact.title)
    published_at = _ensure_utc(fact.published_at)
    if not normalized_title or published_at is None:
        return None
    return (fact.blog_id, normalized_title, published_at.date().isoformat())


def _fact_has_merge_value(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _prefer_generated_facts(facts: list[AnalyticsArticleFact]) -> list[AnalyticsArticleFact]:
    generated = [fact for fact in facts if str(fact.source_type or "").strip().lower() == "generated"]
    others = [fact for fact in facts if str(fact.source_type or "").strip().lower() != "generated"]
    return [*generated, *others]


def _pick_fact_value(
    facts: list[AnalyticsArticleFact],
    field_name: str,
    *,
    prefer_generated: bool = True,
):
    ordered = _prefer_generated_facts(facts) if prefer_generated else list(facts)
    for fact in ordered:
        value = getattr(fact, field_name)
        if _fact_has_merge_value(value):
            return value
    return None


def _group_fact_rows(facts: list[AnalyticsArticleFact]) -> list[list[AnalyticsArticleFact]]:
    url_groups: dict[tuple[int, str], list[AnalyticsArticleFact]] = {}
    fallback_to_url_groups: dict[tuple[int, str, str], set[tuple[int, str]]] = defaultdict(set)

    for fact in facts:
        url_identity = _fact_url_identity_key(fact.actual_url)
        if url_identity is None:
            continue
        group_key = (fact.blog_id, url_identity)
        url_groups.setdefault(group_key, []).append(fact)

    for group_key, grouped_facts in url_groups.items():
        signatures = {
            signature
            for signature in (_fact_match_signature(fact) for fact in grouped_facts)
            if signature is not None
        }
        for signature in signatures:
            fallback_to_url_groups[signature].add(group_key)

    fallback_groups: dict[tuple[int, str], list[AnalyticsArticleFact]] = {}
    for fact in facts:
        url_identity = _fact_url_identity_key(fact.actual_url)
        if url_identity is not None:
            continue
        signature = _fact_match_signature(fact)
        if signature is not None:
            candidate_groups = fallback_to_url_groups.get(signature) or set()
            if len(candidate_groups) == 1:
                only_group = next(iter(candidate_groups))
                url_groups.setdefault(only_group, []).append(fact)
                continue
            fallback_key = (fact.blog_id, f"fallback:{signature[1]}:{signature[2]}")
            fallback_groups.setdefault(fallback_key, []).append(fact)
            continue
        fallback_groups.setdefault((fact.blog_id, f"id:{fact.id}"), []).append(fact)

    ordered_groups: list[list[AnalyticsArticleFact]] = []
    seen_group_keys: set[tuple[int, str]] = set()
    seen_fallback_keys: set[tuple[int, str]] = set()

    for fact in facts:
        url_identity = _fact_url_identity_key(fact.actual_url)
        if url_identity is not None:
            group_key = (fact.blog_id, url_identity)
            if group_key in seen_group_keys:
                continue
            seen_group_keys.add(group_key)
            ordered_groups.append(url_groups[group_key])
            continue

        signature = _fact_match_signature(fact)
        if signature is not None:
            candidate_groups = fallback_to_url_groups.get(signature) or set()
            if len(candidate_groups) == 1:
                only_group = next(iter(candidate_groups))
                if only_group in seen_group_keys:
                    continue
                seen_group_keys.add(only_group)
                ordered_groups.append(url_groups[only_group])
                continue
            fallback_key = (fact.blog_id, f"fallback:{signature[1]}:{signature[2]}")
        else:
            fallback_key = (fact.blog_id, f"id:{fact.id}")
        if fallback_key in seen_fallback_keys:
            continue
        seen_fallback_keys.add(fallback_key)
        ordered_groups.append(fallback_groups[fallback_key])

    return ordered_groups


def _preferred_canonical_url(facts: list[AnalyticsArticleFact]) -> str | None:
    return _pick_preferred_actual_url(facts)


def _fact_keeper_priority(fact: AnalyticsArticleFact) -> tuple[int, int, datetime, int]:
    status_rank = _status_priority(getattr(fact, "status", None))
    source_rank = 2 if str(getattr(fact, "source_type", "") or "").strip().lower() == "generated" else 1
    updated_at = _ensure_utc(getattr(fact, "updated_at", None)) or _ensure_utc(getattr(fact, "created_at", None)) or datetime.min.replace(tzinfo=timezone.utc)
    fact_id = int(getattr(fact, "id", 0) or 0)
    return (status_rank, source_rank, updated_at, fact_id)


def _merge_fact_group(facts: list[AnalyticsArticleFact]) -> MergedAnalyticsFactRow:
    primary = sorted(facts, key=_fact_keeper_priority, reverse=True)[0]
    merged = AnalyticsArticleFact()
    merged.id = primary.id
    merged.blog_id = primary.blog_id
    merged.month = primary.month
    merged.article_id = _pick_fact_value(facts, "article_id", prefer_generated=True)
    merged.synced_post_id = _pick_fact_value(facts, "synced_post_id", prefer_generated=False)
    merged.published_at = _pick_fact_value(facts, "published_at", prefer_generated=True) or primary.published_at
    merged.title = _pick_fact_value(facts, "title", prefer_generated=True) or primary.title
    merged.theme_key = _pick_fact_value(facts, "theme_key", prefer_generated=True)
    merged.theme_name = _pick_fact_value(facts, "theme_name", prefer_generated=True)
    merged.category = _pick_fact_value(facts, "category", prefer_generated=True)
    merged.seo_score = _pick_fact_value(facts, "seo_score", prefer_generated=True)
    merged.geo_score = _pick_fact_value(facts, "geo_score", prefer_generated=True)
    merged.lighthouse_score = _pick_fact_value(facts, "lighthouse_score", prefer_generated=True)
    merged.lighthouse_accessibility_score = _pick_fact_value(facts, "lighthouse_accessibility_score", prefer_generated=True)
    merged.lighthouse_best_practices_score = _pick_fact_value(facts, "lighthouse_best_practices_score", prefer_generated=True)
    merged.lighthouse_seo_score = _pick_fact_value(facts, "lighthouse_seo_score", prefer_generated=True)
    merged.similarity_score = _pick_fact_value(facts, "similarity_score", prefer_generated=True)
    merged.most_similar_url = _pick_fact_value(facts, "most_similar_url", prefer_generated=True)
    merged.article_pattern_id = _pick_fact_value(facts, "article_pattern_id", prefer_generated=True)
    merged.article_pattern_version = _pick_fact_value(facts, "article_pattern_version", prefer_generated=True)
    merged.article_pattern_key = _pick_fact_value(facts, "article_pattern_key", prefer_generated=True)
    merged.article_pattern_version_key = _pick_fact_value(facts, "article_pattern_version_key", prefer_generated=True)
    merged.status = _pick_preferred_status(facts) or _pick_fact_value(facts, "status", prefer_generated=True)
    merged.actual_url = _pick_preferred_actual_url(facts) or _pick_fact_value(facts, "actual_url", prefer_generated=True) or primary.actual_url
    merged.source_type = "generated" if any((fact.article_id is not None) or (str(fact.source_type or "").strip().lower() == "generated") for fact in facts) else "synced"
    return MergedAnalyticsFactRow(
        fact=merged,
        source_facts=list(facts),
        canonical_url=_preferred_canonical_url(facts),
    )


def _merge_fact_rows(facts: list[AnalyticsArticleFact]) -> list[MergedAnalyticsFactRow]:
    return [_merge_fact_group(group) for group in _group_fact_rows(facts)]


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _fact_sort_value(fact: AnalyticsArticleFact, sort_field: str):
    if sort_field == "seo":
        return fact.seo_score
    if sort_field == "geo":
        return fact.geo_score
    if sort_field == "lighthouse":
        return fact.lighthouse_score
    if sort_field == "similarity":
        return fact.similarity_score
    if sort_field == "title":
        title = str(fact.title or "").strip()
        return title.casefold() if title else None
    return _ensure_utc(fact.published_at)


def _sort_fact_rows(
    rows: list[MergedAnalyticsFactRow],
    *,
    sort: str = "published_at",
    dir: str = "desc",
) -> list[MergedAnalyticsFactRow]:
    sort_field = (sort or "published_at").strip().lower()
    dir_name = "asc" if (dir or "").strip().lower() == "asc" else "desc"
    prepared = [(row, _fact_sort_value(row.fact, sort_field)) for row in rows]
    present = [item for item in prepared if item[1] is not None]
    missing = [item for item in prepared if item[1] is None]
    reverse = dir_name == "desc"
    present.sort(key=lambda item: (item[1], item[0].fact.id or 0), reverse=reverse)
    missing.sort(key=lambda item: item[0].fact.id or 0, reverse=reverse)
    return [row for row, _ in present] + [row for row, _ in missing]


def _fact_lookup_keys(*, blog_id: int, url: str | None, canonical_url: str | None = None) -> list[tuple[int, str]]:
    keys: list[tuple[int, str]] = []
    normalized = str(url or "").strip()
    if normalized:
        keys.append((blog_id, normalized))
    preferred_canonical = canonical_url or _canonicalize_fact_url(url)
    if preferred_canonical and (blog_id, preferred_canonical) not in keys:
        keys.append((blog_id, preferred_canonical))
    no_scheme_key = _fact_url_identity_key(preferred_canonical or normalized)
    if no_scheme_key and (blog_id, f"noscheme:{no_scheme_key}") not in keys:
        keys.append((blog_id, f"noscheme:{no_scheme_key}"))
    return keys


def _build_merged_fact_context(db: Session, rows: list[MergedAnalyticsFactRow]) -> MergedAnalyticsFactContext:
    article_ids = {
        fact.article_id
        for row in rows
        for fact in row.source_facts
        if fact.article_id is not None
    }
    blog_ids = {row.fact.blog_id for row in rows}
    article_map = {
        article.id: article
        for article in db.execute(select(Article).where(Article.id.in_(article_ids))).scalars().all()
    } if article_ids else {}

    synced_posts = db.execute(select(SyncedBloggerPost).where(SyncedBloggerPost.blog_id.in_(blog_ids))).scalars().all() if blog_ids else []
    synced_post_map = {post.id: post for post in synced_posts}
    synced_post_by_url: dict[tuple[int, str], SyncedBloggerPost] = {}
    live_urls_by_blog: dict[int, set[str]] = defaultdict(set)
    for post in synced_posts:
        url_identity = _fact_url_identity_key(post.url)
        if url_identity:
            live_urls_by_blog[post.blog_id].add(url_identity)
            synced_post_by_url.setdefault((post.blog_id, url_identity), post)

    pairs = {
        key
        for row in rows
        for key in _fact_lookup_keys(blog_id=row.fact.blog_id, url=row.fact.actual_url, canonical_url=row.canonical_url)
    }
    index_state_map, ctr_map = _load_fact_enrichment_maps(db, pairs=pairs)

    return MergedAnalyticsFactContext(
        article_map=article_map,
        synced_post_map=synced_post_map,
        synced_post_by_url=synced_post_by_url,
        live_urls_by_blog=dict(live_urls_by_blog),
        index_state_map=index_state_map,
        ctr_map=ctr_map,
    )


def _resolve_row_ctr_score(row: MergedAnalyticsFactRow, context: MergedAnalyticsFactContext) -> float | None:
    for fact in _prefer_generated_facts(row.source_facts):
        if fact.article_id is not None:
            article = context.article_map.get(fact.article_id)
            if article is not None:
                score_payload = _compute_ctr_score_payload(
                    title=article.title,
                    excerpt=article.excerpt,
                    html_body=article.assembled_html or article.html_article,
                )
                return _coerce_score(score_payload.get("ctr_score"))
        if fact.synced_post_id is not None:
            post = context.synced_post_map.get(fact.synced_post_id)
            if post is not None:
                score_payload = _compute_ctr_score_payload(
                    title=post.title,
                    excerpt=post.excerpt_text,
                    html_body=post.content_html,
                )
                return _coerce_score(score_payload.get("ctr_score"))
    return None


def _resolve_row_status_variant(row: MergedAnalyticsFactRow, context: MergedAnalyticsFactContext) -> str:
    if row.fact.synced_post_id is not None:
        return "live"
    if any(str(fact.source_type or "").strip().lower() == "synced" for fact in row.source_facts):
        return "live"
    live_urls = context.live_urls_by_blog.get(row.fact.blog_id, set())
    row_url_identity = _fact_url_identity_key(row.fact.actual_url)
    if row_url_identity and row_url_identity in live_urls:
        return "live"
    if not live_urls:
        return "unknown"

    has_generated_published = any(
        str(fact.source_type or "").strip().lower() == "generated" and _normalize_fact_status(fact.status) == "published"
        for fact in row.source_facts
    )
    if has_generated_published and row.canonical_url:
        return "error_deleted"
    return "unknown"


def _lookup_row_enrichment(
    row: MergedAnalyticsFactRow,
    context: MergedAnalyticsFactContext,
) -> tuple[object | None, object | None]:
    for key in _fact_lookup_keys(blog_id=row.fact.blog_id, url=row.fact.actual_url, canonical_url=row.canonical_url):
        index_state = context.index_state_map.get(key)
        ctr_row = context.ctr_map.get(key)
        if index_state is not None or ctr_row is not None:
            return index_state, ctr_row
    return None, None


def _resolve_row_synced_post(row: MergedAnalyticsFactRow, context: MergedAnalyticsFactContext) -> SyncedBloggerPost | None:
    if row.fact.synced_post_id is not None:
        post = context.synced_post_map.get(row.fact.synced_post_id)
        if post is not None:
            return post
    for key in _fact_lookup_keys(blog_id=row.fact.blog_id, url=row.fact.actual_url, canonical_url=row.canonical_url):
        post = context.synced_post_by_url.get(key)
        if post is not None:
            return post
    return None


def _serialize_fact(
    row: MergedAnalyticsFactRow,
    *,
    context: MergedAnalyticsFactContext,
) -> AnalyticsArticleFactRead:
    fact = row.fact
    index_state, ctr_row = _lookup_row_enrichment(row, context)
    synced_post = _resolve_row_synced_post(row, context)
    ctr_value = getattr(ctr_row, "ctr", None)
    ctr_score = _resolve_row_ctr_score(row, context)
    status_variant = _resolve_row_status_variant(row, context)
    refactor_candidate = any(
        (
            _score_below(_coerce_score(fact.seo_score)),
            _score_below(_coerce_score(fact.geo_score)),
            _score_below(_coerce_score(ctr_score)),
            _score_below(_coerce_score(fact.lighthouse_score)),
        )
    )
    return AnalyticsArticleFactRead(
        id=fact.id,
        blog_id=fact.blog_id,
        article_id=fact.article_id,
        synced_post_id=fact.synced_post_id,
        published_at=fact.published_at.isoformat() if fact.published_at else None,
        title=fact.title,
        theme_key=fact.theme_key,
        theme_name=fact.theme_name,
        category=fact.category,
        seo_score=fact.seo_score,
        geo_score=fact.geo_score,
        lighthouse_score=fact.lighthouse_score,
        lighthouse_accessibility_score=fact.lighthouse_accessibility_score,
        lighthouse_best_practices_score=fact.lighthouse_best_practices_score,
        lighthouse_seo_score=fact.lighthouse_seo_score,
        similarity_score=fact.similarity_score,
        most_similar_url=fact.most_similar_url,
        article_pattern_id=fact.article_pattern_id,
        article_pattern_version=fact.article_pattern_version,
        article_pattern_key=fact.article_pattern_key,
        article_pattern_version_key=fact.article_pattern_version_key,
        status=_normalize_fact_status(fact.status) or fact.status,
        actual_url=fact.actual_url,
        source_type=fact.source_type,
        ctr=ctr_value,
        ctr_score=ctr_score,
        live_image_count=synced_post.live_image_count if synced_post else None,
        live_unique_image_count=synced_post.live_unique_image_count if synced_post else None,
        live_duplicate_image_count=synced_post.live_duplicate_image_count if synced_post else None,
        live_webp_count=synced_post.live_webp_count if synced_post else None,
        live_png_count=synced_post.live_png_count if synced_post else None,
        live_other_image_count=synced_post.live_other_image_count if synced_post else None,
        live_image_issue=synced_post.live_image_issue if synced_post else None,
        refactor_candidate=refactor_candidate,
        index_status=index_state.index_status if index_state else "unknown",
        index_coverage_state=index_state.index_coverage_state if index_state else None,
        last_crawl_time=index_state.last_crawl_time.isoformat() if index_state and index_state.last_crawl_time else None,
        last_notify_time=index_state.last_notify_time.isoformat() if index_state and index_state.last_notify_time else None,
        next_eligible_at=index_state.next_eligible_at.isoformat() if index_state and index_state.next_eligible_at else None,
        index_last_checked_at=index_state.last_checked_at.isoformat() if index_state and index_state.last_checked_at else None,
        status_variant=status_variant,
        can_manual_delete=status_variant == "error_deleted",
    )


def _serialize_theme_stat(stat: AnalyticsThemeMonthlyStat) -> AnalyticsThemeMonthlyStatRead:
    return AnalyticsThemeMonthlyStatRead(
        id=stat.id,
        blog_id=stat.blog_id,
        month=stat.month,
        theme_key=stat.theme_key,
        theme_name=stat.theme_name,
        planned_posts=stat.planned_posts,
        actual_posts=stat.actual_posts,
        planned_share=stat.planned_share,
        actual_share=stat.actual_share,
        gap_share=stat.gap_share,
        avg_seo_score=stat.avg_seo_score,
        avg_geo_score=stat.avg_geo_score,
        avg_similarity_score=stat.avg_similarity_score,
        coverage_gap_score=stat.coverage_gap_score,
        next_month_weight_suggestion=stat.next_month_weight_suggestion,
    )


def _serialize_report(db: Session, blog: Blog, month: str, report: AnalyticsBlogMonthlyReport | None) -> AnalyticsBlogMonthlyReportRead:
    theme_stats = db.execute(
        select(AnalyticsThemeMonthlyStat)
        .where(AnalyticsThemeMonthlyStat.blog_id == blog.id, AnalyticsThemeMonthlyStat.month == month)
        .order_by(AnalyticsThemeMonthlyStat.theme_name.asc())
    ).scalars().all()
    facts = db.execute(
        select(AnalyticsArticleFact)
        .where(AnalyticsArticleFact.blog_id == blog.id, AnalyticsArticleFact.month == month)
        .order_by(AnalyticsArticleFact.published_at.desc(), AnalyticsArticleFact.id.desc())
    ).scalars().all()
    merged_rows = _sort_fact_rows(_merge_fact_rows(facts), sort="published_at", dir="desc")
    context = _build_merged_fact_context(db, merged_rows)
    serialized_facts = [_serialize_fact(row, context=context) for row in merged_rows]

    return AnalyticsBlogMonthlyReportRead(
        blog_id=blog.id,
        blog_name=blog.name,
        month=month,
        total_posts=report.total_posts if report else 0,
        avg_seo_score=report.avg_seo_score if report else None,
        avg_geo_score=report.avg_geo_score if report else None,
        avg_similarity_score=report.avg_similarity_score if report else None,
        most_underused_theme_name=report.most_underused_theme_name if report else None,
        most_overused_theme_name=report.most_overused_theme_name if report else None,
        next_month_focus=report.next_month_focus if report else None,
        report_summary=report.report_summary if report else None,
        theme_stats=[_serialize_theme_stat(stat) for stat in theme_stats],
        article_facts=serialized_facts,
    )


def _report_summary(report: AnalyticsBlogMonthlyReport, stats: list[AnalyticsThemeMonthlyStat], facts: list[AnalyticsArticleFact]) -> str:
    top_theme = max(stats, key=lambda item: ((item.avg_seo_score or 0) + (item.avg_geo_score or 0), item.actual_posts), default=None)
    weak_theme = min(stats, key=lambda item: ((item.avg_seo_score or 0) + (item.avg_geo_score or 0), -item.actual_posts), default=None)
    top_article = max(facts, key=lambda item: ((item.seo_score or 0) + (item.geo_score or 0)), default=None)
    weak_article = min(facts, key=lambda item: ((item.seo_score or 0) + (item.geo_score or 0)), default=None)
    return " ".join(
        [
            f"This period has {report.total_posts} tracked posts.",
            f"Average SEO is {report.avg_seo_score if report.avg_seo_score is not None else 'N/A'} and GEO is {report.avg_geo_score if report.avg_geo_score is not None else 'N/A'}.",
            f"Underused theme is {report.most_underused_theme_name or 'N/A'} while overused theme is {report.most_overused_theme_name or 'N/A'}.",
            f"Best theme is {top_theme.theme_name if top_theme else 'N/A'} and weakest theme is {weak_theme.theme_name if weak_theme else 'N/A'}.",
            f"Best article is {top_article.title if top_article else 'N/A'} and weakest article is {weak_article.title if weak_article else 'N/A'}.",
        ]
    )


def _pick_best_status(*statuses: str | None) -> str | None:
    return pick_best_dedupe_status(*statuses, priorities=_STATUS_PRIORITY)


def _pick_preferred_url_value(*urls: str | None) -> str | None:
    return pick_preferred_dedupe_url(*urls)


def _apply_merged_fact_values(target: AnalyticsArticleFact, merged: AnalyticsArticleFact) -> None:
    attrs = (
        "blog_id",
        "month",
        "article_id",
        "synced_post_id",
        "published_at",
        "title",
        "theme_key",
        "theme_name",
        "category",
        "seo_score",
        "geo_score",
        "lighthouse_score",
        "lighthouse_accessibility_score",
        "lighthouse_best_practices_score",
        "lighthouse_seo_score",
        "similarity_score",
        "most_similar_url",
        "article_pattern_id",
        "article_pattern_version",
        "status",
        "actual_url",
        "source_type",
    )
    for attr in attrs:
        setattr(target, attr, getattr(merged, attr))
    if target.article_id is not None:
        target.source_type = "generated"


def _dedupe_fact_rows_for_blog_month(db: Session, *, blog_id: int, month: str) -> int:
    facts = db.execute(
        select(AnalyticsArticleFact)
        .where(AnalyticsArticleFact.blog_id == blog_id, AnalyticsArticleFact.month == month)
        .order_by(AnalyticsArticleFact.published_at.desc(), AnalyticsArticleFact.id.desc())
    ).scalars().all()
    groups = _group_fact_rows(facts)
    merged_row_deleted_count = 0
    for group in groups:
        if len(group) <= 1:
            continue
        merged = _merge_fact_group(group).fact
        keeper = next((item for item in group if item.id == merged.id), group[0])
        _apply_merged_fact_values(keeper, merged)
        for row in group:
            if row.id == keeper.id:
                continue
            db.delete(row)
            merged_row_deleted_count += 1
    return merged_row_deleted_count


def _apply_article_fact_payload(fact: AnalyticsArticleFact, article: Article, month: str) -> None:
    published_at = getattr(getattr(article, "blogger_post", None), "published_at", None) or article.created_at
    post_url = getattr(getattr(article, "blogger_post", None), "published_url", None)
    fact.blog_id = article.blog_id
    fact.month = month
    fact.article_id = article.id
    if published_at is not None:
        if fact.published_at is None:
            fact.published_at = published_at
        else:
            current_published = _ensure_utc(fact.published_at)
            incoming_published = _ensure_utc(published_at)
            if incoming_published and (current_published is None or incoming_published >= current_published):
                fact.published_at = published_at
    fact.title = article.title or fact.title
    fact.theme_key = article.editorial_category_key or "unassigned"
    fact.theme_name = article.editorial_category_label or "Unassigned"
    fact.category = article.editorial_category_label or "Unassigned"
    fact.seo_score = _coerce_score(article.quality_seo_score) if article.quality_seo_score is not None else fact.seo_score
    fact.geo_score = _coerce_score(article.quality_geo_score) if article.quality_geo_score is not None else fact.geo_score
    fact.lighthouse_score = (
        _coerce_score(article.quality_lighthouse_score) if article.quality_lighthouse_score is not None else fact.lighthouse_score
    )
    fact.lighthouse_accessibility_score = (
        _coerce_score(article.quality_lighthouse_accessibility_score)
        if article.quality_lighthouse_accessibility_score is not None
        else fact.lighthouse_accessibility_score
    )
    fact.lighthouse_best_practices_score = (
        _coerce_score(article.quality_lighthouse_best_practices_score)
        if article.quality_lighthouse_best_practices_score is not None
        else fact.lighthouse_best_practices_score
    )
    fact.lighthouse_seo_score = (
        _coerce_score(article.quality_lighthouse_seo_score)
        if article.quality_lighthouse_seo_score is not None
        else fact.lighthouse_seo_score
    )
    fact.similarity_score = (
        _coerce_score(article.quality_similarity_score) if article.quality_similarity_score is not None else fact.similarity_score
    )
    fact.most_similar_url = article.quality_most_similar_url or fact.most_similar_url
    fact.article_pattern_id = article.article_pattern_id or fact.article_pattern_id
    fact.article_pattern_version = article.article_pattern_version if article.article_pattern_version is not None else fact.article_pattern_version
    fact.article_pattern_key = getattr(article, "article_pattern_key", None) or fact.article_pattern_key
    fact.article_pattern_version_key = getattr(article, "article_pattern_version_key", None) or fact.article_pattern_version_key
    raw_status = (
        getattr(getattr(article, "blogger_post", None), "post_status", None).value
        if getattr(article, "blogger_post", None) and getattr(article.blogger_post, "post_status", None)
        else "draft"
    )
    incoming_status = _normalize_fact_status(raw_status) or str(raw_status or "").strip().lower() or "draft"
    fact.status = _pick_best_status(fact.status, incoming_status) or incoming_status
    fact.actual_url = _pick_preferred_url_value(post_url, fact.actual_url) or fact.actual_url or post_url
    fact.source_type = "generated"


def _apply_synced_fact_payload(fact: AnalyticsArticleFact, post: SyncedBloggerPost, month: str) -> None:
    theme_name = _theme_name_from_synced(post)
    fact.blog_id = post.blog_id
    fact.month = month
    fact.synced_post_id = post.id
    if post.published_at is not None:
        if fact.published_at is None:
            fact.published_at = post.published_at
        else:
            current_published = _ensure_utc(fact.published_at)
            incoming_published = _ensure_utc(post.published_at)
            if incoming_published and (current_published is None or incoming_published >= current_published):
                fact.published_at = post.published_at
    if fact.article_id is None:
        fact.title = post.title
        fact.theme_key = theme_name.lower().replace(" ", "-")
        fact.theme_name = theme_name
        fact.category = theme_name
    incoming_status = _normalize_fact_status(post.status) or str(post.status or "").strip().lower() or None
    fact.status = _pick_best_status(fact.status, incoming_status) or incoming_status
    fact.actual_url = _pick_preferred_url_value(post.url, fact.actual_url) or fact.actual_url or post.url
    fact.source_type = "generated" if fact.article_id is not None else "synced"
    try:
        from app.services.content.content_ops_service import compute_seo_geo_scores

        score_payload = compute_seo_geo_scores(
            title=post.title,
            html_body=post.content_html,
            excerpt=post.excerpt_text,
            faq_section=[],
        )
        fact.seo_score = _coerce_score(score_payload.get("seo_score"))
        fact.geo_score = _coerce_score(score_payload.get("geo_score"))
    except Exception:
        pass


def rebuild_blog_month_rollup(db: Session, blog_id: int, month: str, *, commit: bool = True) -> None:
    start_date, end_date = _month_bounds(month)
    _dedupe_fact_rows_for_blog_month(db, blog_id=blog_id, month=month)
    facts = db.execute(
        select(AnalyticsArticleFact)
        .where(AnalyticsArticleFact.blog_id == blog_id, AnalyticsArticleFact.month == month)
        .order_by(AnalyticsArticleFact.published_at.desc(), AnalyticsArticleFact.id.desc())
    ).scalars().all()
    merged_rows = _sort_fact_rows(_merge_fact_rows(facts), sort="published_at", dir="desc")
    merged_facts = [row.fact for row in merged_rows]
    themes = db.execute(select(BlogTheme).where(BlogTheme.blog_id == blog_id).order_by(BlogTheme.sort_order.asc())).scalars().all()
    theme_names = {theme.key: theme.name for theme in themes}
    base_weights = {theme.key: theme.weight for theme in themes}

    db.execute(delete(AnalyticsThemeMonthlyStat).where(AnalyticsThemeMonthlyStat.blog_id == blog_id, AnalyticsThemeMonthlyStat.month == month))
    existing_report = db.execute(
        select(AnalyticsBlogMonthlyReport).where(AnalyticsBlogMonthlyReport.blog_id == blog_id, AnalyticsBlogMonthlyReport.month == month)
    ).scalar_one_or_none()
    if existing_report is None:
        existing_report = AnalyticsBlogMonthlyReport(blog_id=blog_id, month=month)
        db.add(existing_report)

    planned_slots = db.execute(
        select(ContentPlanSlot, BlogTheme)
        .join(ContentPlanDay, ContentPlanSlot.plan_day_id == ContentPlanDay.id)
        .outerjoin(BlogTheme, BlogTheme.id == ContentPlanSlot.theme_id)
        .where(ContentPlanDay.blog_id == blog_id)
        .where(and_(ContentPlanDay.plan_date >= start_date, ContentPlanDay.plan_date <= end_date))
    ).all()
    planned_by_theme = Counter()
    for slot, theme in planned_slots:
        key = theme.key if theme else "unassigned"
        planned_by_theme[key] += 1
        theme_names.setdefault(key, theme.name if theme else "Unassigned")

    actual_by_theme = Counter((fact.theme_key or "unassigned") for fact in merged_facts)
    facts_by_theme: dict[str, list[AnalyticsArticleFact]] = defaultdict(list)
    for fact in merged_facts:
        facts_by_theme[fact.theme_key or "unassigned"].append(fact)
        theme_names.setdefault(fact.theme_key or "unassigned", fact.theme_name or "Unassigned")

    planned_total = sum(planned_by_theme.values())
    actual_total = len(merged_facts)
    theme_keys = sorted(set(theme_names) | set(planned_by_theme) | set(actual_by_theme))

    stats: list[AnalyticsThemeMonthlyStat] = []
    for theme_key in theme_keys:
        theme_facts = facts_by_theme.get(theme_key, [])
        planned_posts = planned_by_theme.get(theme_key, 0)
        actual_posts = actual_by_theme.get(theme_key, 0)
        planned_share = round(planned_posts / planned_total, 4) if planned_total else 0.0
        actual_share = round(actual_posts / actual_total, 4) if actual_total else 0.0
        coverage_gap = round(planned_share - actual_share, 4)
        base_weight = base_weights.get(theme_key, 10)
        suggestion = max(1, int(round(base_weight * (1 + coverage_gap))))
        stat = AnalyticsThemeMonthlyStat(
            blog_id=blog_id,
            month=month,
            theme_key=theme_key,
            theme_name=theme_names.get(theme_key, theme_key.replace("-", " ").title()),
            planned_posts=planned_posts,
            actual_posts=actual_posts,
            planned_share=planned_share,
            actual_share=actual_share,
            gap_share=round(actual_share - planned_share, 4),
            avg_seo_score=_safe_mean([item.seo_score for item in theme_facts]),
            avg_geo_score=_safe_mean([item.geo_score for item in theme_facts]),
            avg_similarity_score=_safe_mean([item.similarity_score for item in theme_facts]),
            coverage_gap_score=coverage_gap,
            next_month_weight_suggestion=suggestion,
        )
        db.add(stat)
        stats.append(stat)

    most_underused = max(stats, key=lambda item: item.coverage_gap_score, default=None)
    most_overused = min(stats, key=lambda item: item.coverage_gap_score, default=None)
    existing_report.total_posts = actual_total
    existing_report.avg_seo_score = _safe_mean([fact.seo_score for fact in merged_facts])
    existing_report.avg_geo_score = _safe_mean([fact.geo_score for fact in merged_facts])
    existing_report.avg_similarity_score = _safe_mean([fact.similarity_score for fact in merged_facts])
    existing_report.most_underused_theme_key = most_underused.theme_key if most_underused else None
    existing_report.most_underused_theme_name = most_underused.theme_name if most_underused else None
    existing_report.most_overused_theme_key = most_overused.theme_key if most_overused else None
    existing_report.most_overused_theme_name = most_overused.theme_name if most_overused else None
    existing_report.next_month_focus = (
        f"Increase {most_underused.theme_name} coverage and reduce {most_overused.theme_name} overload."
        if most_underused and most_overused and most_underused.theme_key != most_overused.theme_key
        else "Keep balance and improve low-performing themes."
    )
    existing_report.report_summary = _report_summary(existing_report, stats, merged_facts)
    db.add(existing_report)
    if commit:
        db.commit()
    else:
        db.flush()


def upsert_article_fact(db: Session, article_id: int, *, commit: bool = True) -> list[str]:
    article = db.execute(
        select(Article)
        .where(Article.id == article_id)
        .options(selectinload(Article.blogger_post))
    ).scalar_one_or_none()
    if article is None:
        return []
    published_at = getattr(getattr(article, "blogger_post", None), "published_at", None) or article.created_at
    month = _month_key(published_at)
    if month is None:
        return []
    fact = _find_single_fact(db, article_id=article.id)
    previous_months: set[str] = set()
    if fact is None:
        fact = AnalyticsArticleFact(blog_id=article.blog_id, month=month, title=article.title, source_type="generated")
        db.add(fact)
    elif fact.month:
        previous_months.add(fact.month)
    _apply_article_fact_payload(fact, article, month)
    touched_months = {month, *previous_months}
    for month_key in sorted(item for item in touched_months if item):
        _dedupe_fact_rows_for_blog_month(db, blog_id=article.blog_id, month=month_key)
    if commit:
        db.commit()
        for month_key in sorted(item for item in touched_months if item):
            rebuild_blog_month_rollup(db, article.blog_id, month_key, commit=False)
        db.commit()
    return sorted(item for item in touched_months if item)


def upsert_synced_post_fact(db: Session, synced_post_id: int, *, commit: bool = True) -> list[str]:
    post = db.execute(select(SyncedBloggerPost).where(SyncedBloggerPost.id == synced_post_id)).scalar_one_or_none()
    if post is None or post.published_at is None:
        return []
    month = _month_key(post.published_at)
    if month is None:
        return []
    fact = _find_single_fact(db, synced_post_id=post.id)
    previous_months: set[str] = set()
    if fact is None:
        fact = AnalyticsArticleFact(blog_id=post.blog_id, month=month, title=post.title, source_type="synced")
        db.add(fact)
    elif fact.month:
        previous_months.add(fact.month)
    _apply_synced_fact_payload(fact, post, month)
    touched_months = {month, *previous_months}
    for month_key in sorted(item for item in touched_months if item):
        _dedupe_fact_rows_for_blog_month(db, blog_id=post.blog_id, month=month_key)
    if commit:
        db.commit()
        for month_key in sorted(item for item in touched_months if item):
            rebuild_blog_month_rollup(db, post.blog_id, month_key, commit=False)
        db.commit()
    return sorted(item for item in touched_months if item)


def sync_synced_post_facts_for_blog(db: Session, blog_id: int, *, commit: bool = True) -> list[str]:
    touched_months: set[str] = set()
    current_posts = db.execute(select(SyncedBloggerPost).where(SyncedBloggerPost.blog_id == blog_id)).scalars().all()
    current_ids = {post.id for post in current_posts}
    existing_facts = db.execute(
        select(AnalyticsArticleFact).where(AnalyticsArticleFact.blog_id == blog_id, AnalyticsArticleFact.source_type == "synced")
    ).scalars().all()

    for fact in existing_facts:
        if fact.month:
            touched_months.add(fact.month)
        if fact.synced_post_id not in current_ids:
            db.delete(fact)

    for post in current_posts:
        if post.published_at is None:
            continue
        fact = _find_single_fact(db, synced_post_id=post.id)
        if fact is None:
            fact = AnalyticsArticleFact(blog_id=blog_id, month=_month_key(post.published_at) or "", title=post.title, source_type="synced")
            db.add(fact)
        if fact.month:
            touched_months.add(fact.month)
        month = _month_key(post.published_at)
        if month:
            touched_months.add(month)
            _apply_synced_fact_payload(fact, post, month)

    for month_key in sorted(item for item in touched_months if item):
        _dedupe_fact_rows_for_blog_month(db, blog_id=blog_id, month=month_key)

    if commit:
        db.commit()
        for month_key in sorted(item for item in touched_months if item):
            rebuild_blog_month_rollup(db, blog_id, month_key, commit=False)
        db.commit()
    return sorted(item for item in touched_months if item)


def backfill_analytics(db: Session) -> AnalyticsBackfillRead:
    db.execute(delete(AnalyticsThemeMonthlyStat))
    db.execute(delete(AnalyticsBlogMonthlyReport))
    db.execute(delete(AnalyticsArticleFact))
    db.commit()

    touched: set[tuple[int, str]] = set()
    article_count = 0
    synced_count = 0

    articles = db.execute(select(Article).options(selectinload(Article.blogger_post)).order_by(Article.id.asc())).scalars().all()
    for article in articles:
        published_at = getattr(getattr(article, "blogger_post", None), "published_at", None) or article.created_at
        month = _month_key(published_at)
        if month is None:
            continue
        fact = AnalyticsArticleFact(blog_id=article.blog_id, month=month, title=article.title, source_type="generated")
        _apply_article_fact_payload(fact, article, month)
        db.add(fact)
        touched.add((article.blog_id, month))
        article_count += 1

    synced_posts = db.execute(select(SyncedBloggerPost).order_by(SyncedBloggerPost.id.asc())).scalars().all()
    for post in synced_posts:
        if post.published_at is None:
            continue
        month = _month_key(post.published_at)
        if month is None:
            continue
        fact = AnalyticsArticleFact(blog_id=post.blog_id, month=month, title=post.title, source_type="synced")
        _apply_synced_fact_payload(fact, post, month)
        db.add(fact)
        touched.add((post.blog_id, month))
        synced_count += 1

    db.commit()
    for blog_id, month in sorted(touched):
        rebuild_blog_month_rollup(db, blog_id, month, commit=False)
    db.commit()
    return AnalyticsBackfillRead(blog_months=len(touched), generated_facts=article_count, synced_facts=synced_count)


def get_monthly_blog_summaries(db: Session, month: str) -> AnalyticsBlogMonthlyListResponse:
    blogs = db.execute(select(Blog).order_by(Blog.name.asc())).scalars().all()
    for blog in blogs:
        rebuild_blog_month_rollup(db, blog.id, month, commit=False)
    reports = {
        report.blog_id: report
        for report in db.execute(select(AnalyticsBlogMonthlyReport).where(AnalyticsBlogMonthlyReport.month == month)).scalars().all()
    }
    items = [
        AnalyticsBlogMonthlySummaryRead(
            blog_id=blog.id,
            blog_name=blog.name,
            month=month,
            total_posts=reports[blog.id].total_posts if blog.id in reports else 0,
            avg_seo_score=reports[blog.id].avg_seo_score if blog.id in reports else None,
            avg_geo_score=reports[blog.id].avg_geo_score if blog.id in reports else None,
            avg_similarity_score=reports[blog.id].avg_similarity_score if blog.id in reports else None,
            most_underused_theme_name=reports[blog.id].most_underused_theme_name if blog.id in reports else None,
            most_overused_theme_name=reports[blog.id].most_overused_theme_name if blog.id in reports else None,
            next_month_focus=reports[blog.id].next_month_focus if blog.id in reports else None,
        )
        for blog in blogs
    ]
    return AnalyticsBlogMonthlyListResponse(month=month, items=items)


def get_blog_monthly_report(db: Session, blog_id: int, month: str) -> AnalyticsBlogMonthlyReportRead:
    blog = db.execute(select(Blog).where(Blog.id == blog_id)).scalar_one()
    rebuild_blog_month_rollup(db, blog_id, month, commit=False)
    report = db.execute(
        select(AnalyticsBlogMonthlyReport).where(AnalyticsBlogMonthlyReport.blog_id == blog_id, AnalyticsBlogMonthlyReport.month == month)
    ).scalar_one_or_none()
    return _serialize_report(db, blog, month, report)


def _parse_day_bounds(day_text: str) -> tuple[datetime, datetime]:
    day_value = datetime.strptime(day_text, "%Y-%m-%d").date()
    return (
        datetime.combine(day_value, datetime.min.time()).replace(tzinfo=timezone.utc),
        datetime.combine(day_value, datetime.max.time()).replace(tzinfo=timezone.utc),
    )


def _build_fact_order(sort: str, dir: str):
    sort_field = (sort or "published_at").strip().lower()
    dir_name = "asc" if (dir or "").strip().lower() == "asc" else "desc"
    field_map = {
        "published_at": AnalyticsArticleFact.published_at,
        "seo": AnalyticsArticleFact.seo_score,
        "geo": AnalyticsArticleFact.geo_score,
        "lighthouse": AnalyticsArticleFact.lighthouse_score,
        "similarity": AnalyticsArticleFact.similarity_score,
        "title": AnalyticsArticleFact.title,
    }
    column = field_map.get(sort_field, AnalyticsArticleFact.published_at)
    ordered = column.asc().nullslast() if dir_name == "asc" else column.desc().nullslast()
    return ordered, dir_name


def get_blog_monthly_articles(
    db: Session,
    *,
    blog_id: int,
    month: str,
    date: str | None = None,
    source_type: str | None = "all",
    theme_key: str | None = None,
    category: str | None = None,
    status: str | None = None,
    sort: str = "published_at",
    dir: str = "desc",
    page: int = 1,
    page_size: int = 50,
) -> AnalyticsArticleFactListResponse:
    conditions = [AnalyticsArticleFact.blog_id == blog_id]
    if month:
        conditions.append(AnalyticsArticleFact.month == month)
    if date:
        day_start, day_end = _parse_day_bounds(date)
        conditions.append(AnalyticsArticleFact.published_at >= day_start)
        conditions.append(AnalyticsArticleFact.published_at <= day_end)

    base_query = _apply_fact_filters(
        select(AnalyticsArticleFact).where(*conditions),
        source_type=source_type,
        theme_key=theme_key,
        category=category,
        status=status,
    )
    offset = max(page - 1, 0) * max(page_size, 1)
    facts = db.execute(base_query).scalars().all()
    merged_items = _sort_fact_rows(_merge_fact_rows(facts), sort=sort, dir=dir)
    total = len(merged_items)
    items = merged_items[offset : offset + page_size]
    context = _build_merged_fact_context(db, items)
    serialized = [_serialize_fact(item, context=context) for item in items]
    return AnalyticsArticleFactListResponse(
        blog_id=blog_id,
        month=month,
        total=total,
        page=page,
        page_size=page_size,
        items=serialized,
    )


def _find_merged_row_by_fact_id(rows: list[MergedAnalyticsFactRow], fact_id: int) -> MergedAnalyticsFactRow | None:
    for row in rows:
        if row.fact.id == fact_id:
            return row
        if any(source_fact.id == fact_id for source_fact in row.source_facts):
            return row
    return None


def _delete_generated_fact_sources(db: Session, row: MergedAnalyticsFactRow) -> None:
    article_ids = {
        fact.article_id
        for fact in row.source_facts
        if str(fact.source_type or "").strip().lower() == "generated" and fact.article_id is not None
    }
    source_fact_ids = [fact.id for fact in row.source_facts]
    job_ids: set[int] = set()

    if article_ids:
        article_rows = db.execute(select(Article.id, Article.job_id).where(Article.id.in_(article_ids))).all()
        job_ids = {int(job_id) for _article_id, job_id in article_rows if job_id is not None}
        db.execute(delete(PublishQueueItem).where(PublishQueueItem.article_id.in_(list(article_ids))))
        db.execute(delete(AIUsageEvent).where(AIUsageEvent.article_id.in_(list(article_ids))))
        db.execute(delete(AnalyticsArticleFact).where(AnalyticsArticleFact.article_id.in_(list(article_ids))))

    if source_fact_ids:
        db.execute(delete(AnalyticsArticleFact).where(AnalyticsArticleFact.id.in_(source_fact_ids)))

    if job_ids:
        db.execute(delete(AuditLog).where(AuditLog.job_id.in_(list(job_ids))))
        db.execute(delete(AIUsageEvent).where(AIUsageEvent.job_id.in_(list(job_ids))))
        db.execute(delete(BloggerPost).where(BloggerPost.job_id.in_(list(job_ids))))
        db.execute(delete(Image).where(Image.job_id.in_(list(job_ids))))

    if article_ids:
        db.execute(delete(Article).where(Article.id.in_(list(article_ids))))
    if job_ids:
        db.execute(delete(Job).where(Job.id.in_(list(job_ids))))


def _delete_synced_fact_sources(db: Session, row: MergedAnalyticsFactRow) -> None:
    synced_post_ids = {
        fact.synced_post_id
        for fact in row.source_facts
        if str(fact.source_type or "").strip().lower() == "synced" and fact.synced_post_id is not None
    }
    source_fact_ids = [fact.id for fact in row.source_facts]

    if synced_post_ids:
        db.execute(delete(AnalyticsArticleFact).where(AnalyticsArticleFact.synced_post_id.in_(list(synced_post_ids))))
        db.execute(delete(SyncedBloggerPost).where(SyncedBloggerPost.id.in_(list(synced_post_ids))))

    if source_fact_ids:
        db.execute(delete(AnalyticsArticleFact).where(AnalyticsArticleFact.id.in_(source_fact_ids)))


def delete_blog_article_fact(db: Session, *, blog_id: int, fact_id: int) -> None:
    target_fact = db.execute(
        select(AnalyticsArticleFact).where(AnalyticsArticleFact.id == fact_id, AnalyticsArticleFact.blog_id == blog_id)
    ).scalar_one_or_none()
    if target_fact is None:
        raise LookupError("Analytics article fact not found")

    facts = db.execute(
        select(AnalyticsArticleFact)
        .where(AnalyticsArticleFact.blog_id == blog_id, AnalyticsArticleFact.month == target_fact.month)
        .order_by(AnalyticsArticleFact.published_at.desc(), AnalyticsArticleFact.id.desc())
    ).scalars().all()
    merged_rows = _sort_fact_rows(_merge_fact_rows(facts), sort="published_at", dir="desc")
    target_row = _find_merged_row_by_fact_id(merged_rows, fact_id)
    if target_row is None:
        raise LookupError("Merged analytics article fact not found")

    context = _build_merged_fact_context(db, [target_row])
    status_variant = _resolve_row_status_variant(target_row, context)
    if status_variant != "error_deleted":
        raise PermissionError("Only deleted live posts can be removed manually")

    touched_months = sorted({fact.month for fact in target_row.source_facts if fact.month})
    if any(str(fact.source_type or "").strip().lower() == "generated" for fact in target_row.source_facts):
        _delete_generated_fact_sources(db, target_row)
    else:
        _delete_synced_fact_sources(db, target_row)

    for month_key in touched_months:
        rebuild_blog_month_rollup(db, blog_id, month_key, commit=False)
    db.commit()


def get_blog_daily_summary(
    db: Session,
    *,
    blog_id: int,
    month: str,
    source_type: str | None = "all",
    theme_key: str | None = None,
    category: str | None = None,
    status: str | None = None,
) -> AnalyticsDailySummaryListResponse:
    facts = db.execute(
        _apply_fact_filters(
            select(AnalyticsArticleFact).where(
                AnalyticsArticleFact.blog_id == blog_id,
                AnalyticsArticleFact.month == month,
            ),
            source_type=source_type,
            theme_key=theme_key,
            category=category,
            status=status,
        ).order_by(AnalyticsArticleFact.published_at.desc(), AnalyticsArticleFact.id.desc())
    ).scalars().all()
    merged_rows = _sort_fact_rows(_merge_fact_rows(facts), sort="published_at", dir="desc")

    daily_map: dict[str, dict[str, object]] = {}
    for row in merged_rows:
        fact = row.fact
        published_at = _ensure_utc(fact.published_at)
        if published_at is None:
            continue
        date_key = published_at.date().isoformat()
        bucket = daily_map.setdefault(
            date_key,
            {
                "total_posts": 0,
                "generated_posts": 0,
                "synced_posts": 0,
                "seo_scores": [],
                "geo_scores": [],
            },
        )
        bucket["total_posts"] = int(bucket["total_posts"] or 0) + 1
        if fact.source_type == "generated":
            bucket["generated_posts"] = int(bucket["generated_posts"] or 0) + 1
        elif fact.source_type == "synced":
            bucket["synced_posts"] = int(bucket["synced_posts"] or 0) + 1
        if fact.seo_score is not None:
            seo_scores = bucket.get("seo_scores")
            if isinstance(seo_scores, list):
                seo_scores.append(fact.seo_score)
        if fact.geo_score is not None:
            geo_scores = bucket.get("geo_scores")
            if isinstance(geo_scores, list):
                geo_scores.append(fact.geo_score)

    items: list[AnalyticsDailySummaryRead] = []
    for date_key in sorted(daily_map.keys()):
        row = daily_map[date_key]
        seo_scores = row.get("seo_scores") if isinstance(row, dict) else []
        geo_scores = row.get("geo_scores") if isinstance(row, dict) else []
        items.append(
            AnalyticsDailySummaryRead(
                date=date_key,
                total_posts=int(row.get("total_posts") or 0) if isinstance(row, dict) else 0,
                generated_posts=int(row.get("generated_posts") or 0) if isinstance(row, dict) else 0,
                synced_posts=int(row.get("synced_posts") or 0) if isinstance(row, dict) else 0,
                avg_seo=_safe_mean(seo_scores if isinstance(seo_scores, list) else []),
                avg_geo=_safe_mean(geo_scores if isinstance(geo_scores, list) else []),
            )
        )

    return AnalyticsDailySummaryListResponse(blog_id=blog_id, month=month, items=items)


def apply_next_month_weights(db: Session, blog_id: int, month: str) -> AnalyticsThemeWeightApplyResponse:
    from app.services.ops.planner_service import create_month_plan
    from app.services.integrations.settings_service import get_settings_map

    stats = db.execute(
        select(AnalyticsThemeMonthlyStat).where(AnalyticsThemeMonthlyStat.blog_id == blog_id, AnalyticsThemeMonthlyStat.month == month)
    ).scalars().all()
    applied: dict[str, int] = {}
    for stat in stats:
        theme = db.execute(select(BlogTheme).where(BlogTheme.blog_id == blog_id, BlogTheme.key == stat.theme_key)).scalar_one_or_none()
        if theme is None:
            continue
        theme.weight = stat.next_month_weight_suggestion
        db.add(theme)
        applied[theme.key] = theme.weight
    db.commit()

    month_date = datetime.strptime(f"{month}-01", "%Y-%m-%d").date()
    next_month_date = date(month_date.year + (1 if month_date.month == 12 else 0), 1 if month_date.month == 12 else month_date.month + 1, 1)
    settings_map = get_settings_map(db)
    create_month_plan(
        db,
        blog_id=blog_id,
        month=next_month_date.strftime("%Y-%m"),
        target_post_count=int(settings_map.get("planner_default_daily_posts", "3")),
        overwrite=True,
    )
    return AnalyticsThemeWeightApplyResponse(
        blog_id=blog_id,
        source_month=month,
        target_month=next_month_date.strftime("%Y-%m"),
        applied_weights=applied,
    )


def _range_window(range_name: str, month: str) -> tuple[datetime, datetime]:
    start, end = _month_range(month)
    if range_name == "day":
        day_start = datetime.combine(end.date(), datetime.min.time()).replace(tzinfo=timezone.utc)
        day_end = datetime.combine(end.date(), datetime.max.time()).replace(tzinfo=timezone.utc)
        return day_start, day_end
    if range_name == "week":
        week_start = datetime.combine(end.date() - timedelta(days=6), datetime.min.time()).replace(tzinfo=timezone.utc)
        return week_start, end
    return start, end


def _apply_fact_filters(
    query,
    *,
    blog_id: int | None = None,
    source_type: str | None = None,
    theme_key: str | None = None,
    category: str | None = None,
    status: str | None = None,
):
    if blog_id is not None:
        query = query.where(AnalyticsArticleFact.blog_id == blog_id)
    if source_type and source_type != "all":
        query = query.where(AnalyticsArticleFact.source_type == source_type)
    if theme_key:
        query = query.where(AnalyticsArticleFact.theme_key == theme_key)
    if category:
        query = query.where(AnalyticsArticleFact.category == category)
    if status:
        status_values = _status_filter_values(status)
        if status_values:
            query = query.where(func.lower(func.coalesce(AnalyticsArticleFact.status, "")).in_(status_values))
    return query


def get_integrated_dashboard(
    db: Session,
    *,
    range_name: str,
    month: str,
    include_report: bool = False,
    blog_id: int | None = None,
    source_type: str | None = None,
    theme_key: str | None = None,
    category: str | None = None,
    status: str | None = None,
) -> AnalyticsIntegratedRead:
    start_dt, end_dt = _range_window(range_name, month)
    base_window = and_(AnalyticsArticleFact.published_at >= start_dt, AnalyticsArticleFact.published_at <= end_dt)

    facts = db.execute(
        _apply_fact_filters(
            select(AnalyticsArticleFact).where(base_window),
            blog_id=blog_id,
            source_type=source_type,
            theme_key=theme_key,
            category=category,
            status=status,
        ).order_by(AnalyticsArticleFact.published_at.desc(), AnalyticsArticleFact.id.desc())
    ).scalars().all()
    merged_rows = _sort_fact_rows(_merge_fact_rows(facts), sort="published_at", dir="desc")
    merged_facts = [row.fact for row in merged_rows]
    recent_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    recent_upload_count = 0
    for fact in merged_facts:
        published_at = _ensure_utc(fact.published_at)
        if published_at is not None and published_at >= recent_cutoff:
            recent_upload_count += 1

    summaries = get_monthly_blog_summaries(db, month).items
    selected_blog_id = blog_id or (summaries[0].blog_id if summaries else None)
    selected_report = get_blog_monthly_report(db, selected_blog_id, month) if include_report and selected_blog_id is not None else None

    stats_query = select(AnalyticsThemeMonthlyStat).where(AnalyticsThemeMonthlyStat.month == month)
    if blog_id is not None:
        stats_query = stats_query.where(AnalyticsThemeMonthlyStat.blog_id == blog_id)
    stats = db.execute(stats_query).scalars().all()
    underused = max(stats, key=lambda item: item.coverage_gap_score, default=None)
    overused = min(stats, key=lambda item: item.coverage_gap_score, default=None)
    kpis = AnalyticsIntegratedKpiRead(
        total_posts=len(merged_facts),
        avg_seo_score=_safe_mean([fact.seo_score for fact in merged_facts]),
        avg_geo_score=_safe_mean([fact.geo_score for fact in merged_facts]),
        avg_similarity_score=_safe_mean([fact.similarity_score for fact in merged_facts]),
        most_underused_theme_name=underused.theme_name if underused else None,
        most_overused_theme_name=overused.theme_name if overused else None,
        recent_upload_count=recent_upload_count,
    )
    available_theme_map: dict[str, str] = {}
    for fact in merged_facts:
        if not fact.theme_key:
            continue
        key = str(fact.theme_key)
        available_theme_map.setdefault(key, str(fact.theme_name or fact.theme_key))
    if theme_key and theme_key not in available_theme_map:
        available_theme_map[theme_key] = theme_key
    available_categories = sorted({str(fact.category) for fact in merged_facts if fact.category})
    if category and category not in available_categories:
        available_categories.append(category)
        available_categories.sort()
    return AnalyticsIntegratedRead(
        month=month,
        range=range_name,
        selected_blog_id=selected_blog_id,
        kpis=kpis,
        blogs=summaries,
        report=selected_report,
        source_type=source_type or "all",
        theme_key=theme_key,
        category=category,
        status=status,
        available_themes=[
            AnalyticsThemeFilterOptionRead(key=key, name=name)
            for key, name in sorted(available_theme_map.items(), key=lambda item: item[1].lower())
        ],
        available_categories=available_categories,
    )
