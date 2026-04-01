from __future__ import annotations

import calendar
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import mean

from sqlalchemy import and_, delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import (
    AnalyticsArticleFact,
    AnalyticsBlogMonthlyReport,
    AnalyticsThemeMonthlyStat,
    Article,
    Blog,
    BlogTheme,
    ContentPlanDay,
    ContentPlanSlot,
    SyncedBloggerPost,
)
from app.schemas.api import (
    AnalyticsArticleFactListResponse,
    AnalyticsArticleFactRead,
    AnalyticsBackfillRead,
    AnalyticsBlogMonthlyListResponse,
    AnalyticsBlogMonthlyReportRead,
    AnalyticsBlogMonthlySummaryRead,
    AnalyticsIntegratedKpiRead,
    AnalyticsIntegratedRead,
    AnalyticsThemeFilterOptionRead,
    AnalyticsThemeMonthlyStatRead,
    AnalyticsThemeWeightApplyResponse,
)
from app.services.planner_service import create_month_plan
from app.services.settings_service import get_settings_map


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


def _theme_name_from_synced(post: SyncedBloggerPost) -> str:
    labels = [str(label).strip() for label in (post.labels or []) if str(label).strip()]
    return labels[0] if labels else "Uncategorized"


def _find_single_fact(db: Session, *, article_id: int | None = None, synced_post_id: int | None = None) -> AnalyticsArticleFact | None:
    query = select(AnalyticsArticleFact)
    if article_id is not None:
        query = query.where(AnalyticsArticleFact.article_id == article_id)
    if synced_post_id is not None:
        query = query.where(AnalyticsArticleFact.synced_post_id == synced_post_id)
    items = db.execute(query.order_by(AnalyticsArticleFact.id.asc())).scalars().all()
    if not items:
        return None
    primary = items[0]
    for extra in items[1:]:
        db.delete(extra)
    return primary


def _serialize_fact(fact: AnalyticsArticleFact) -> AnalyticsArticleFactRead:
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
        similarity_score=fact.similarity_score,
        most_similar_url=fact.most_similar_url,
        status=fact.status,
        actual_url=fact.actual_url,
        source_type=fact.source_type,
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
        article_facts=[_serialize_fact(fact) for fact in facts],
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


def _apply_article_fact_payload(fact: AnalyticsArticleFact, article: Article, month: str) -> None:
    published_at = getattr(getattr(article, "blogger_post", None), "published_at", None) or article.created_at
    fact.blog_id = article.blog_id
    fact.month = month
    fact.article_id = article.id
    fact.synced_post_id = None
    fact.published_at = published_at
    fact.title = article.title
    fact.theme_key = article.editorial_category_key or "unassigned"
    fact.theme_name = article.editorial_category_label or "Unassigned"
    fact.category = article.editorial_category_label or "Unassigned"
    fact.seo_score = _coerce_score(article.quality_seo_score)
    fact.geo_score = _coerce_score(article.quality_geo_score)
    fact.similarity_score = _coerce_score(article.quality_similarity_score)
    fact.most_similar_url = article.quality_most_similar_url
    fact.status = getattr(getattr(article, "blogger_post", None), "post_status", None).value if getattr(article, "blogger_post", None) and getattr(article.blogger_post, "post_status", None) else "draft"
    fact.actual_url = getattr(getattr(article, "blogger_post", None), "published_url", None)
    fact.source_type = "generated"


def _apply_synced_fact_payload(fact: AnalyticsArticleFact, post: SyncedBloggerPost, month: str) -> None:
    theme_name = _theme_name_from_synced(post)
    fact.blog_id = post.blog_id
    fact.month = month
    fact.article_id = None
    fact.synced_post_id = post.id
    fact.published_at = post.published_at
    fact.title = post.title
    fact.theme_key = theme_name.lower().replace(" ", "-")
    fact.theme_name = theme_name
    fact.category = theme_name
    fact.seo_score = None
    fact.geo_score = None
    fact.similarity_score = None
    fact.most_similar_url = None
    fact.status = post.status
    fact.actual_url = post.url
    fact.source_type = "synced"


def rebuild_blog_month_rollup(db: Session, blog_id: int, month: str, *, commit: bool = True) -> None:
    start_date, end_date = _month_bounds(month)
    facts = db.execute(
        select(AnalyticsArticleFact)
        .where(AnalyticsArticleFact.blog_id == blog_id, AnalyticsArticleFact.month == month)
        .order_by(AnalyticsArticleFact.published_at.desc(), AnalyticsArticleFact.id.desc())
    ).scalars().all()
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

    actual_by_theme = Counter((fact.theme_key or "unassigned") for fact in facts)
    facts_by_theme: dict[str, list[AnalyticsArticleFact]] = defaultdict(list)
    for fact in facts:
        facts_by_theme[fact.theme_key or "unassigned"].append(fact)
        theme_names.setdefault(fact.theme_key or "unassigned", fact.theme_name or "Unassigned")

    planned_total = sum(planned_by_theme.values())
    actual_total = len(facts)
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
    existing_report.avg_seo_score = _safe_mean([fact.seo_score for fact in facts])
    existing_report.avg_geo_score = _safe_mean([fact.geo_score for fact in facts])
    existing_report.avg_similarity_score = _safe_mean([fact.similarity_score for fact in facts])
    existing_report.most_underused_theme_key = most_underused.theme_key if most_underused else None
    existing_report.most_underused_theme_name = most_underused.theme_name if most_underused else None
    existing_report.most_overused_theme_key = most_overused.theme_key if most_overused else None
    existing_report.most_overused_theme_name = most_overused.theme_name if most_overused else None
    existing_report.next_month_focus = (
        f"Increase {most_underused.theme_name} coverage and reduce {most_overused.theme_name} overload."
        if most_underused and most_overused and most_underused.theme_key != most_overused.theme_key
        else "Keep balance and improve low-performing themes."
    )
    existing_report.report_summary = _report_summary(existing_report, stats, facts)
    db.add(existing_report)
    if commit:
        db.commit()


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
    report = db.execute(
        select(AnalyticsBlogMonthlyReport).where(AnalyticsBlogMonthlyReport.blog_id == blog_id, AnalyticsBlogMonthlyReport.month == month)
    ).scalar_one_or_none()
    return _serialize_report(db, blog, month, report)


def get_blog_monthly_articles(db: Session, blog_id: int, month: str) -> AnalyticsArticleFactListResponse:
    items = db.execute(
        select(AnalyticsArticleFact)
        .where(AnalyticsArticleFact.blog_id == blog_id, AnalyticsArticleFact.month == month)
        .order_by(AnalyticsArticleFact.published_at.desc(), AnalyticsArticleFact.id.desc())
    ).scalars().all()
    return AnalyticsArticleFactListResponse(blog_id=blog_id, month=month, items=[_serialize_fact(item) for item in items])


def apply_next_month_weights(db: Session, blog_id: int, month: str) -> AnalyticsThemeWeightApplyResponse:
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
        query = query.where(AnalyticsArticleFact.status == status)
    return query


def get_integrated_dashboard(
    db: Session,
    *,
    range_name: str,
    month: str,
    blog_id: int | None = None,
    source_type: str | None = None,
    theme_key: str | None = None,
    category: str | None = None,
    status: str | None = None,
) -> AnalyticsIntegratedRead:
    start_dt, end_dt = _range_window(range_name, month)
    base_query = select(AnalyticsArticleFact).where(and_(AnalyticsArticleFact.published_at >= start_dt, AnalyticsArticleFact.published_at <= end_dt))
    facts = db.execute(
        _apply_fact_filters(
            base_query,
            blog_id=blog_id,
            source_type=source_type,
            theme_key=theme_key,
            category=category,
            status=status,
        ).order_by(AnalyticsArticleFact.published_at.desc(), AnalyticsArticleFact.id.desc())
    ).scalars().all()
    theme_option_facts = db.execute(
        _apply_fact_filters(
            base_query,
            blog_id=blog_id,
            source_type=source_type,
            category=category,
            status=status,
        )
    ).scalars().all()
    category_option_facts = db.execute(
        _apply_fact_filters(
            base_query,
            blog_id=blog_id,
            source_type=source_type,
            theme_key=theme_key,
            status=status,
        )
    ).scalars().all()

    summaries = get_monthly_blog_summaries(db, month).items
    selected_blog_id = blog_id or (summaries[0].blog_id if summaries else None)
    selected_report = get_blog_monthly_report(db, selected_blog_id, month) if selected_blog_id is not None else None
    if selected_report is not None:
        selected_report.article_facts = [
            item for item in selected_report.article_facts if not blog_id or item.blog_id == selected_blog_id
        ]
        if source_type and source_type != "all":
            selected_report.article_facts = [item for item in selected_report.article_facts if item.source_type == source_type]
        if theme_key:
            selected_report.article_facts = [item for item in selected_report.article_facts if item.theme_key == theme_key]
        if category:
            selected_report.article_facts = [item for item in selected_report.article_facts if item.category == category]
        if status:
            selected_report.article_facts = [item for item in selected_report.article_facts if item.status == status]

    stats_query = select(AnalyticsThemeMonthlyStat).where(AnalyticsThemeMonthlyStat.month == month)
    if blog_id is not None:
        stats_query = stats_query.where(AnalyticsThemeMonthlyStat.blog_id == blog_id)
    stats = db.execute(stats_query).scalars().all()
    underused = max(stats, key=lambda item: item.coverage_gap_score, default=None)
    overused = min(stats, key=lambda item: item.coverage_gap_score, default=None)
    recent_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    kpis = AnalyticsIntegratedKpiRead(
        total_posts=len(facts),
        avg_seo_score=_safe_mean([fact.seo_score for fact in facts]),
        avg_geo_score=_safe_mean([fact.geo_score for fact in facts]),
        avg_similarity_score=_safe_mean([fact.similarity_score for fact in facts]),
        most_underused_theme_name=underused.theme_name if underused else None,
        most_overused_theme_name=overused.theme_name if overused else None,
        recent_upload_count=sum(1 for fact in facts if fact.published_at and fact.published_at >= recent_cutoff),
    )
    available_theme_map: dict[str, str] = {}
    for fact in theme_option_facts:
        if fact.theme_key:
            available_theme_map[fact.theme_key] = fact.theme_name or fact.theme_key
    if theme_key and theme_key not in available_theme_map:
        available_theme_map[theme_key] = theme_key
    available_categories = sorted({fact.category for fact in category_option_facts if fact.category})
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
