from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.api.deps.admin_auth import AdminMutationRoute
from app.schemas.api import (
    ContentOverviewRecalculateRead,
    ContentOverviewResponse,
    ContentOverviewSyncRead,
    ContentOverviewSyncRequest,
    ContentOpsStatusRead,
    ContentReviewItemRead,
)
from app.services.content.content_ops_service import (
    ContentOpsError,
    get_content_overview,
    apply_content_review,
    approve_content_review,
    get_content_ops_status,
    list_content_reviews,
    refresh_content_overview_cache,
    reject_content_review,
    rerun_content_review,
    serialize_review_item,
    sync_content_overview_to_sheet,
    sync_live_content_reviews,
)

router = APIRouter(route_class=AdminMutationRoute)


def _raise_http(exc: ContentOpsError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/status", response_model=ContentOpsStatusRead)
def get_status(db: Session = Depends(get_db)) -> dict:
    return get_content_ops_status(db)


@router.get("/reviews", response_model=list[ContentReviewItemRead])
def get_reviews(
    blog_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    approval_status: str | None = Query(default=None),
    risk_level: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = list_content_reviews(
        db,
        blog_id=blog_id,
        limit=limit,
        approval_status=approval_status,
        risk_level=risk_level,
    )
    return [serialize_review_item(item) for item in rows]


@router.post("/reviews/{item_id}/approve", response_model=ContentReviewItemRead)
def approve_review(item_id: int, db: Session = Depends(get_db)) -> dict:
    try:
        item = approve_content_review(db, item_id, actor="api", channel="api")
    except ContentOpsError as exc:
        _raise_http(exc)
    return serialize_review_item(item)


@router.post("/reviews/{item_id}/apply", response_model=ContentReviewItemRead)
def apply_review(item_id: int, db: Session = Depends(get_db)) -> dict:
    try:
        item = apply_content_review(db, item_id, actor="api", channel="api")
    except ContentOpsError as exc:
        _raise_http(exc)
    return serialize_review_item(item)


@router.post("/reviews/{item_id}/reject", response_model=ContentReviewItemRead)
def reject_review(item_id: int, db: Session = Depends(get_db)) -> dict:
    try:
        item = reject_content_review(db, item_id, actor="api", channel="api")
    except ContentOpsError as exc:
        _raise_http(exc)
    return serialize_review_item(item)


@router.post("/reviews/{item_id}/rerun", response_model=ContentReviewItemRead)
def rerun_review(item_id: int, db: Session = Depends(get_db)) -> dict:
    try:
        item = rerun_content_review(db, item_id, actor="api", channel="api")
    except ContentOpsError as exc:
        _raise_http(exc)
    return serialize_review_item(item)


@router.get("/overview", response_model=ContentOverviewResponse)
def get_content_overview_route(
    profile: str | None = Query(default=None),
    published_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    return get_content_overview(
        db,
        profile=profile,
        published_only=published_only,
        page=page,
        page_size=page_size,
    )


@router.post("/overview/sync", response_model=ContentOverviewSyncRead)
def sync_content_overview(
    payload: ContentOverviewSyncRequest,
    db: Session = Depends(get_db),
) -> dict:
    if not payload.sync_sheet:
        return {
            "sheet_id": "",
            "profile": payload.profile,
            "tab": "전체 글 현황",
            "status": "skipped",
            "rows": 0,
            "columns": 0,
        }
    return sync_content_overview_to_sheet(
        db,
        profile=payload.profile,
        published_only=payload.published_only,
    )


@router.post("/overview/recalculate", response_model=ContentOverviewRecalculateRead)
def recalculate_content_overview(
    payload: ContentOverviewSyncRequest,
    db: Session = Depends(get_db),
) -> dict:
    return refresh_content_overview_cache(
        db,
        profile=payload.profile,
        published_only=payload.published_only,
    )


@router.post("/sync-now")
def sync_now(db: Session = Depends(get_db)) -> dict:
    return sync_live_content_reviews(db)
