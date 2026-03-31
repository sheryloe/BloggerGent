from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.api import (
    PlannerCalendarRead,
    PlannerCategoryRead,
    PlannerMonthPlanRequest,
    PlannerSlotCreate,
    PlannerSlotRead,
    PlannerSlotUpdate,
)
from app.services.planner_service import (
    cancel_slot,
    create_month_plan,
    create_slot,
    get_calendar,
    list_categories,
    run_slot_generation,
    update_slot,
)

router = APIRouter(prefix="/planner", tags=["planner"])


@router.get("/calendar", response_model=PlannerCalendarRead)
def read_calendar(
    blog_id: int = Query(..., ge=1),
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
) -> PlannerCalendarRead:
    return get_calendar(db, blog_id=blog_id, month=month)


@router.get("/categories", response_model=list[PlannerCategoryRead])
def read_categories(blog_id: int = Query(..., ge=1), db: Session = Depends(get_db)) -> list[PlannerCategoryRead]:
    return list_categories(db, blog_id=blog_id)


@router.post("/month-plan", response_model=PlannerCalendarRead, status_code=status.HTTP_201_CREATED)
def build_month_plan(payload: PlannerMonthPlanRequest, db: Session = Depends(get_db)) -> PlannerCalendarRead:
    return create_month_plan(
        db,
        blog_id=payload.blog_id,
        month=payload.month,
        target_post_count=payload.target_post_count,
        overwrite=payload.overwrite,
    )


@router.post("/slots", response_model=PlannerSlotRead, status_code=status.HTTP_201_CREATED)
def create_planner_slot(payload: PlannerSlotCreate, db: Session = Depends(get_db)) -> PlannerSlotRead:
    return create_slot(db, payload)


@router.patch("/slots/{slot_id}", response_model=PlannerSlotRead)
def update_planner_slot(slot_id: int, payload: PlannerSlotUpdate, db: Session = Depends(get_db)) -> PlannerSlotRead:
    return update_slot(db, slot_id=slot_id, payload=payload)


@router.post("/slots/{slot_id}/generate", response_model=PlannerSlotRead)
def generate_slot(slot_id: int, db: Session = Depends(get_db)) -> PlannerSlotRead:
    try:
        return run_slot_generation(db, slot_id=slot_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/slots/{slot_id}/cancel", response_model=PlannerSlotRead)
def cancel_planner_slot(slot_id: int, db: Session = Depends(get_db)) -> PlannerSlotRead:
    return cancel_slot(db, slot_id=slot_id)
