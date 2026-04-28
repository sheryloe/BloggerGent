from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.api.deps.admin_auth import AdminMutationRoute
from app.models.entities import ManualImageSlotStatus
from app.schemas.api import ManualImageApplyRequest, ManualImageApplyResponse, ManualImageSlotRead
from app.services.content.manual_image_service import apply_manual_image_slots, list_manual_image_slots

router = APIRouter(route_class=AdminMutationRoute)


@router.get("/pending", response_model=list[ManualImageSlotRead])
def get_pending_manual_images(
    provider: str | None = Query(default=None),
    blog_id: int | None = Query(default=None),
    batch_key: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list:
    return list_manual_image_slots(
        db,
        provider=provider,
        status=ManualImageSlotStatus.PENDING,
        blog_id=blog_id,
        batch_key=batch_key,
        limit=limit,
    )


@router.post("/apply", response_model=ManualImageApplyResponse)
def apply_manual_images(payload: ManualImageApplyRequest, db: Session = Depends(get_db)) -> dict:
    if not payload.items:
        raise HTTPException(status_code=422, detail="items is required.")
    try:
        return apply_manual_image_slots(
            db,
            [item.model_dump() for item in payload.items],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
