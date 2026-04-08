from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.api import (
    PlannerCalendarRead,
    PlannerCategoryRead,
    PlannerDayBriefAnalysisRequest,
    PlannerDayBriefAnalysisResponse,
    PlannerDayBriefApplyRequest,
    PlannerDayBriefApplyResponse,
    PlannerBriefRunRead,
    PlannerMonthPlanRequest,
    PlannerSlotCreate,
    PlannerSlotRead,
    PlannerSlotUpdate,
)
from app.services.planner_service import (
    analyze_day_briefs,
    apply_day_briefs,
    cancel_slot,
    create_month_plan,
    create_slot,
    get_calendar,
    list_day_brief_runs,
    list_categories,
    run_slot_generation,
    update_slot,
)

router = APIRouter(prefix="/planner", tags=["planner"])


@router.get("/calendar", response_model=PlannerCalendarRead)
def read_calendar(
    channel_id: str | None = Query(default=None),
    blog_id: int | None = Query(default=None, ge=1),
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
) -> PlannerCalendarRead:
    try:
        return get_calendar(db, channel_id=channel_id, blog_id=blog_id, month=month)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/categories", response_model=list[PlannerCategoryRead])
def read_categories(
    channel_id: str | None = Query(default=None),
    blog_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
) -> list[PlannerCategoryRead]:
    try:
        return list_categories(db, channel_id=channel_id, blog_id=blog_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/month-plan", response_model=PlannerCalendarRead, status_code=status.HTTP_201_CREATED)
def build_month_plan(payload: PlannerMonthPlanRequest, db: Session = Depends(get_db)) -> PlannerCalendarRead:
    try:
        return create_month_plan(
            db,
            channel_id=payload.channel_id,
            blog_id=payload.blog_id,
            month=payload.month,
            target_post_count=payload.target_post_count,
            overwrite=payload.overwrite,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/slots", response_model=PlannerSlotRead, status_code=status.HTTP_201_CREATED)
def create_planner_slot(payload: PlannerSlotCreate, db: Session = Depends(get_db)) -> PlannerSlotRead:
    try:
        return create_slot(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/slots/{slot_id}", response_model=PlannerSlotRead)
def update_planner_slot(slot_id: int, payload: PlannerSlotUpdate, db: Session = Depends(get_db)) -> PlannerSlotRead:
    try:
        return update_slot(db, slot_id=slot_id, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/slots/{slot_id}/generate", response_model=PlannerSlotRead)
def generate_slot(slot_id: int, db: Session = Depends(get_db)) -> PlannerSlotRead:
    try:
        return run_slot_generation(db, slot_id=slot_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/slots/{slot_id}/cancel", response_model=PlannerSlotRead)
def cancel_planner_slot(slot_id: int, db: Session = Depends(get_db)) -> PlannerSlotRead:
    return cancel_slot(db, slot_id=slot_id)


@router.post("/days/{plan_day_id}/brief-analysis", response_model=PlannerDayBriefAnalysisResponse)
def analyze_planner_day_brief(
    plan_day_id: int,
    payload: PlannerDayBriefAnalysisRequest,
    db: Session = Depends(get_db),
) -> PlannerDayBriefAnalysisResponse:
    try:
        return analyze_day_briefs(db, plan_day_id=plan_day_id, prompt_override=payload.prompt_override)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/days/{plan_day_id}/brief-apply", response_model=PlannerDayBriefApplyResponse)
def apply_planner_day_brief(
    plan_day_id: int,
    payload: PlannerDayBriefApplyRequest,
    db: Session = Depends(get_db),
) -> PlannerDayBriefApplyResponse:
    try:
        return apply_day_briefs(
            db,
            plan_day_id=plan_day_id,
            run_id=payload.run_id,
            slot_suggestions=payload.slot_suggestions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/days/{plan_day_id}/brief-runs", response_model=list[PlannerBriefRunRead])
def read_planner_day_brief_runs(
    plan_day_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[PlannerBriefRunRead]:
    try:
        return list_day_brief_runs(db, plan_day_id=plan_day_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
