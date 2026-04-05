from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.api import (
    AnalyticsArticleFactListResponse,
    AnalyticsBackfillRead,
    AnalyticsDailySummaryListResponse,
    AnalyticsBlogMonthlyListResponse,
    AnalyticsBlogMonthlyReportRead,
    AnalyticsIndexingRefreshRequest,
    AnalyticsIndexingRequest,
    AnalyticsIntegratedRead,
    AnalyticsThemeWeightApplyRequest,
    AnalyticsThemeWeightApplyResponse,
)
from app.services.analytics_service import (
    apply_next_month_weights,
    backfill_analytics,
    get_blog_daily_summary,
    get_blog_monthly_articles,
    get_blog_monthly_report,
    get_integrated_dashboard,
    get_monthly_blog_summaries,
)
from app.services.google_indexing_service import refresh_indexing_for_blog, request_indexing_for_url

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/blogs/monthly", response_model=AnalyticsBlogMonthlyListResponse)
def read_monthly_blogs(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
) -> AnalyticsBlogMonthlyListResponse:
    return get_monthly_blog_summaries(db, month=month)


@router.get("/blogs/{blog_id}/monthly-report", response_model=AnalyticsBlogMonthlyReportRead)
def read_blog_monthly_report(
    blog_id: int,
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
) -> AnalyticsBlogMonthlyReportRead:
    return get_blog_monthly_report(db, blog_id=blog_id, month=month)


@router.get("/blogs/{blog_id}/articles", response_model=AnalyticsArticleFactListResponse)
def read_blog_monthly_articles(
    blog_id: int,
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    source_type: str | None = Query(default="all"),
    theme_key: str | None = Query(default=None),
    category: str | None = Query(default=None),
    status: str | None = Query(default=None),
    sort: str = Query(default="published_at", pattern=r"^(published_at|seo|geo|similarity|title)$"),
    dir: str = Query(default="desc", pattern=r"^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> AnalyticsArticleFactListResponse:
    return get_blog_monthly_articles(
        db,
        blog_id=blog_id,
        month=month,
        date=date,
        source_type=source_type,
        theme_key=theme_key,
        category=category,
        status=status,
        sort=sort,
        dir=dir,
        page=page,
        page_size=page_size,
    )


@router.get("/blogs/{blog_id}/daily-summary", response_model=AnalyticsDailySummaryListResponse)
def read_blog_daily_summary(
    blog_id: int,
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    source_type: str | None = Query(default="all"),
    theme_key: str | None = Query(default=None),
    category: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> AnalyticsDailySummaryListResponse:
    return get_blog_daily_summary(
        db,
        blog_id=blog_id,
        month=month,
        source_type=source_type,
        theme_key=theme_key,
        category=category,
        status=status,
    )


@router.get("/integrated", response_model=AnalyticsIntegratedRead)
def read_integrated_dashboard(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    range: str = Query(default="month", pattern=r"^(month|week|day)$"),
    include_report: bool = Query(default=False),
    blog_id: int | None = Query(default=None, ge=1),
    source_type: str | None = Query(default="all"),
    theme_key: str | None = Query(default=None),
    category: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> AnalyticsIntegratedRead:
    return get_integrated_dashboard(
        db,
        range_name=range,
        month=month,
        blog_id=blog_id,
        source_type=source_type,
        theme_key=theme_key,
        category=category,
        status=status,
        include_report=include_report,
    )


@router.post("/backfill", response_model=AnalyticsBackfillRead)
def run_analytics_backfill(db: Session = Depends(get_db)) -> AnalyticsBackfillRead:
    return backfill_analytics(db)


@router.post("/blogs/{blog_id}/apply-next-month-weights", response_model=AnalyticsThemeWeightApplyResponse)
def apply_month_weights(
    blog_id: int,
    payload: AnalyticsThemeWeightApplyRequest,
    db: Session = Depends(get_db),
) -> AnalyticsThemeWeightApplyResponse:
    return apply_next_month_weights(db, blog_id=blog_id, month=payload.month)


@router.post("/indexing/request")
def request_indexing(
    payload: AnalyticsIndexingRequest,
    db: Session = Depends(get_db),
) -> dict:
    return request_indexing_for_url(
        db,
        blog_id=payload.blog_id,
        url=payload.url,
        force=payload.force,
    )


@router.post("/indexing/refresh")
def refresh_indexing(
    payload: AnalyticsIndexingRefreshRequest,
    db: Session = Depends(get_db),
) -> dict:
    return refresh_indexing_for_blog(
        db,
        blog_id=payload.blog_id,
        urls=payload.urls,
        limit=payload.limit,
    )
