from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import Article, Blog, Job, JobStatus, LogLevel, PublishMode, Topic
from app.services.audit_service import add_log
from app.services.content_guard_service import DuplicateContentError, find_duplicate_match


def create_job(
    db: Session,
    *,
    blog_id: int,
    keyword: str,
    topic_id: int | None = None,
    publish_mode: PublishMode = PublishMode.DRAFT,
    initial_status: JobStatus = JobStatus.PENDING,
    raw_prompts: dict | None = None,
    raw_responses: dict | None = None,
) -> Job:
    resolved_topic_id = topic_id
    if resolved_topic_id is None:
        existing_topic = db.execute(
            select(Topic).where(Topic.blog_id == blog_id, Topic.keyword == keyword)
        ).scalar_one_or_none()
        if existing_topic:
            resolved_topic_id = existing_topic.id

    duplicate = find_duplicate_match(
        db,
        blog_id=blog_id,
        candidate=keyword,
        include_topics=False,
    )
    if duplicate:
        raise DuplicateContentError(f"중복 주제로 작업을 만들 수 없습니다. 기준값: {duplicate.value}")

    job = Job(
        blog_id=blog_id,
        topic_id=resolved_topic_id,
        keyword_snapshot=keyword,
        publish_mode=publish_mode,
        status=initial_status,
        raw_prompts=raw_prompts or {},
        raw_responses=raw_responses or {},
        start_time=datetime.now(timezone.utc) if initial_status != JobStatus.PENDING else None,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    add_log(db, job=job, stage=initial_status.value, message=f"'{keyword}' 작업이 생성되었습니다.")
    return job


def load_job(db: Session, job_id: int) -> Job | None:
    query = (
        select(Job)
        .where(Job.id == job_id)
        .options(
            selectinload(Job.blog).selectinload(Blog.agent_configs),
            selectinload(Job.topic).selectinload(Topic.blog),
            selectinload(Job.article).selectinload(Article.image),
            selectinload(Job.article).selectinload(Article.blogger_post),
            selectinload(Job.article).selectinload(Article.blog),
            selectinload(Job.image),
            selectinload(Job.blogger_post),
            selectinload(Job.audit_logs),
        )
    )
    return db.execute(query).scalar_one_or_none()


def set_status(db: Session, job: Job, status: JobStatus, message: str, payload: dict | None = None) -> Job:
    if job.start_time is None and status not in {JobStatus.PENDING, JobStatus.DISCOVERING_TOPICS}:
        job.start_time = datetime.now(timezone.utc)
    job.status = status
    if status in {JobStatus.STOPPED, JobStatus.COMPLETED, JobStatus.FAILED}:
        job.end_time = datetime.now(timezone.utc)
    db.add(job)
    db.commit()
    db.refresh(job)
    add_log(db, job=job, stage=status.value, message=message, payload=payload)
    return job


def merge_prompt(db: Session, job: Job, key: str, value: object) -> None:
    prompts = dict(job.raw_prompts or {})
    prompts[key] = value
    job.raw_prompts = prompts
    db.add(job)
    db.commit()


def merge_response(db: Session, job: Job, key: str, value: object) -> None:
    responses = dict(job.raw_responses or {})
    responses[key] = value
    job.raw_responses = responses
    db.add(job)
    db.commit()


def record_failure(db: Session, job: Job, exc: Exception) -> Job:
    errors = list(job.error_logs or [])
    errors.append(
        {
            "message": str(exc),
            "attempt": job.attempt_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    job.error_logs = errors
    job.status = JobStatus.FAILED
    job.end_time = datetime.now(timezone.utc)
    db.add(job)
    db.commit()
    db.refresh(job)
    add_log(db, job=job, stage=JobStatus.FAILED.value, message=str(exc), level=LogLevel.ERROR)
    return job


def increment_attempt(db: Session, job: Job) -> Job:
    job.attempt_count += 1
    db.add(job)
    db.commit()
    db.refresh(job)
    return job
