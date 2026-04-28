from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.api.deps.admin_auth import AdminMutationRoute
from app.models.entities import Article, Job, PublishMode, Topic
from app.schemas.api import (
    GeneratedDataResetRequest,
    GeneratedDataResetResponse,
    JobCreate,
    JobDetailRead,
    JobListItemRead,
    JobRetryResponse,
)
from app.services.platform.blog_service import get_blog, list_visible_blog_ids
from app.services.content.content_guard_service import DuplicateContentError
from app.services.ops.job_service import create_job, load_job
from app.services.integrations.settings_service import get_settings_map
from app.services.ops.generated_data_reset_service import (
    GeneratedDataResetConfirmationError,
    reset_generated_data,
)
from app.services.content.topic_guard_service import TopicGuardConflictError
from app.tasks.pipeline import PIPELINE_CONTROL_KEY, _resolve_stop_after, _serialize_pipeline_control, run_job

router = APIRouter(route_class=AdminMutationRoute)


@router.get("", response_model=list[JobListItemRead])
def list_jobs(
    limit: int = Query(default=30, le=100),
    blog_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[Job]:
    visible_blog_ids = set(list_visible_blog_ids(db))
    if not visible_blog_ids:
        return []
    if blog_id and blog_id not in visible_blog_ids:
        return []

    query = (
        select(Job)
        .where(Job.blog_id.in_(visible_blog_ids))
        .options(
            selectinload(Job.blog),
            selectinload(Job.topic),
            selectinload(Job.article).selectinload(Article.image),
            selectinload(Job.article).selectinload(Article.blogger_post),
            selectinload(Job.article).selectinload(Article.blog),
            selectinload(Job.article).selectinload(Article.publish_queue_items),
            selectinload(Job.image),
            selectinload(Job.blogger_post),
        )
        .order_by(Job.created_at.desc())
        .limit(limit)
    )
    if blog_id:
        query = query.where(Job.blog_id == blog_id)
    return db.execute(query).scalars().unique().all()


@router.get("/{job_id}", response_model=JobDetailRead)
def get_job(job_id: int, db: Session = Depends(get_db)) -> Job:
    job = load_job(db, job_id)
    if not job or job.blog_id not in set(list_visible_blog_ids(db)):
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("", response_model=JobDetailRead)
def create_job_endpoint(payload: JobCreate, db: Session = Depends(get_db)) -> Job:
    topic = db.get(Topic, payload.topic_id) if payload.topic_id else None
    if payload.topic_id and not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    target_blog_id = payload.blog_id or (topic.blog_id if topic else None)
    blog = get_blog(db, target_blog_id) if target_blog_id else None
    if not blog:
        raise HTTPException(status_code=400, detail="Provide a valid blog_id or topic_id")

    keyword = payload.keyword or (topic.keyword if topic else None)
    if not keyword:
        raise HTTPException(status_code=400, detail="Provide either keyword or topic_id")

    settings_map = get_settings_map(db)
    stop_after_status = _resolve_stop_after(settings_map, override=payload.stop_after_status)
    publish_mode = payload.publish_mode or PublishMode.DRAFT

    try:
        job = create_job(
            db,
            blog_id=blog.id,
            keyword=keyword,
            topic_id=topic.id if topic else None,
            publish_mode=publish_mode,
            raw_prompts={
                PIPELINE_CONTROL_KEY: _serialize_pipeline_control(
                    stop_after_status,
                    defer_images=payload.defer_images,
                )
            },
        )
    except TopicGuardConflictError as exc:
        raise HTTPException(status_code=409, detail=exc.to_detail()) from exc
    except DuplicateContentError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    run_job.delay(job.id)
    return load_job(db, job.id) or job


@router.post("/{job_id}/retry", response_model=JobRetryResponse)
def retry_job(job_id: int, db: Session = Depends(get_db)) -> JobRetryResponse:
    job = load_job(db, job_id)
    if not job or job.blog_id not in set(list_visible_blog_ids(db)):
        raise HTTPException(status_code=404, detail="Job not found")

    job.publish_mode = PublishMode.DRAFT
    db.add(job)
    db.commit()

    run_job.delay(job_id, force_retry=True)
    return JobRetryResponse(job_id=job_id, status="queued", message="재시도 요청을 접수했습니다.")


@router.delete("/generated-data", response_model=GeneratedDataResetResponse)
def reset_generated_data_deprecated(
    payload: GeneratedDataResetRequest = Body(default_factory=GeneratedDataResetRequest),
    db: Session = Depends(get_db),
) -> GeneratedDataResetResponse:
    try:
        result = reset_generated_data(db, dry_run=payload.dry_run, confirm_text=payload.confirm_text)
    except GeneratedDataResetConfirmationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GeneratedDataResetResponse(**result)
