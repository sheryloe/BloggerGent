from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.api.deps.admin_auth import AdminMutationRoute
from app.models.entities import Topic
from app.schemas.api import DiscoveryRunRequest, DiscoveryRunResponse, TopicRead
from app.services.platform.blog_service import get_blog, list_visible_blog_ids
from app.services.providers.base import ProviderRuntimeError
from app.services.content.topic_guard_service import TopicGuardConflictError
from app.tasks.pipeline import discover_topics_and_enqueue

router = APIRouter(route_class=AdminMutationRoute)


@router.get("", response_model=list[TopicRead])
def list_topics(
    limit: int = Query(default=20, le=100),
    blog_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[Topic]:
    visible_blog_ids = set(list_visible_blog_ids(db))
    if not visible_blog_ids:
        return []
    if blog_id and blog_id not in visible_blog_ids:
        return []

    query = (
        select(Topic)
        .where(Topic.blog_id.in_(visible_blog_ids))
        .options(selectinload(Topic.blog))
        .order_by(Topic.created_at.desc())
        .limit(limit)
    )
    if blog_id:
        query = query.where(Topic.blog_id == blog_id)
    return db.execute(query).scalars().all()


@router.post("/discover", response_model=DiscoveryRunResponse)
def trigger_topic_discovery(payload: DiscoveryRunRequest, db: Session = Depends(get_db)) -> dict:
    blog = get_blog(db, payload.blog_id)
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")
    try:
        return discover_topics_and_enqueue(
            db,
            blog_id=payload.blog_id,
            publish_mode=payload.publish_mode.value if payload.publish_mode else None,
            stop_after=payload.stop_after_status,
        )
    except ProviderRuntimeError as exc:
        status_code = exc.status_code if exc.status_code in {400, 401, 403, 404, 409, 422, 429} else 502
        raise HTTPException(
            status_code=status_code,
            detail={
                "provider": exc.provider,
                "message": exc.message,
                "detail": exc.detail,
            },
        ) from exc
    except TopicGuardConflictError as exc:
        raise HTTPException(status_code=409, detail=exc.to_detail()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
