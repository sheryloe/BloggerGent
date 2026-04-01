from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models.entities import AIUsageEvent, Article, AuditLog, Blog, BloggerPost, Image, Job, PostStatus, PublishMode, PublishQueueItem, Topic
from app.schemas.api import GeneratedDataResetResponse, JobCreate, JobDetailRead, JobListItemRead, JobRetryResponse
from app.services.blog_service import get_blog, list_visible_blog_ids
from app.services.content_guard_service import DuplicateContentError
from app.services.job_service import create_job, load_job
from app.services.providers.factory import get_blogger_provider
from app.services.settings_service import get_settings_map
from app.services.storage_service import clear_generated_storage
from app.services.topic_guard_service import TopicGuardConflictError
from app.tasks.pipeline import PIPELINE_CONTROL_KEY, _resolve_stop_after, _serialize_pipeline_control, run_job

router = APIRouter()


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
            raw_prompts={PIPELINE_CONTROL_KEY: _serialize_pipeline_control(stop_after_status)},
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
def reset_generated_data(db: Session = Depends(get_db)) -> GeneratedDataResetResponse:
    draft_posts = db.execute(
        select(BloggerPost, Blog)
        .join(Blog, BloggerPost.blog_id == Blog.id)
        .where(BloggerPost.post_status != PostStatus.PUBLISHED)
    ).all()

    for blogger_post, blog in draft_posts:
        post_id = (blogger_post.blogger_post_id or "").strip()
        blog_id = (blog.blogger_blog_id or "").strip()
        if not post_id or not blog_id:
            continue
        try:
            provider = get_blogger_provider(db, blog)
            delete_post = getattr(provider, "delete_post", None)
            if callable(delete_post):
                delete_post(post_id)
        except Exception:
            pass

    counts = {
        "deleted_jobs": int(db.execute(select(func.count()).select_from(Job)).scalar_one()),
        "deleted_topics": int(db.execute(select(func.count()).select_from(Topic)).scalar_one()),
        "deleted_articles": int(db.execute(select(func.count()).select_from(Article)).scalar_one()),
        "deleted_images": int(db.execute(select(func.count()).select_from(Image)).scalar_one()),
        "deleted_blogger_posts": int(db.execute(select(func.count()).select_from(BloggerPost)).scalar_one()),
        "deleted_ai_usage_events": int(db.execute(select(func.count()).select_from(AIUsageEvent)).scalar_one()),
        "deleted_publish_queue_items": int(db.execute(select(func.count()).select_from(PublishQueueItem)).scalar_one()),
        "deleted_audit_logs": int(db.execute(select(func.count()).select_from(AuditLog)).scalar_one()),
    }

    db.execute(delete(AuditLog))
    db.execute(delete(AIUsageEvent))
    db.execute(delete(PublishQueueItem))
    db.execute(delete(BloggerPost))
    db.execute(delete(Image))
    db.execute(delete(Article))
    db.execute(delete(Job))
    db.execute(delete(Topic))
    db.commit()

    deleted_storage_files = clear_generated_storage()
    return GeneratedDataResetResponse(
        **counts,
        deleted_storage_files=deleted_storage_files,
        message="생성 작업, 글, 이미지, 토픽, 감사 로그를 모두 정리했습니다.",
    )
