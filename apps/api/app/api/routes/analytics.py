from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.api import (
    AnalyticsArticleFactListResponse,
    AnalyticsBackfillRead,
    AnalyticsBlogMonthlyListResponse,
    AnalyticsBlogMonthlyReportRead,
    AnalyticsIntegratedRead,
    AnalyticsThemeWeightApplyRequest,
    AnalyticsThemeWeightApplyResponse,
)
from app.services.analytics_service import (
    apply_next_month_weights,
    backfill_analytics,
    get_blog_monthly_articles,
    get_blog_monthly_report,
    get_integrated_dashboard,
    get_monthly_blog_summaries,
)

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
    db: Session = Depends(get_db),
) -> AnalyticsArticleFactListResponse:
    return get_blog_monthly_articles(db, blog_id=blog_id, month=month)


@router.get("/integrated", response_model=AnalyticsIntegratedRead)
def read_integrated_dashboard(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    range: str = Query(default="month", pattern=r"^(month|week|day)$"),
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
