from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.api import DashboardMetrics
from app.services.ops.dashboard_service import build_dashboard_metrics

router = APIRouter()


@router.get("", response_model=DashboardMetrics)
def get_dashboard(
    blog_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    return build_dashboard_metrics(db, blog_id=blog_id)
