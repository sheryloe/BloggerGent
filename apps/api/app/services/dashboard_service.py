from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Blog, BloggerPost, Job, JobStatus, Topic
from app.services.blog_service import get_blog, get_blog_summary_map, list_blogs


def build_dashboard_metrics(db: Session, blog_id: int | None = None) -> dict:
    blogs = [get_blog(db, blog_id)] if blog_id else list_blogs(db)
    blogs = [blog for blog in blogs if blog]
    blog_ids = [blog.id for blog in blogs]
    if not blog_ids:
        return {
            "today_generated_posts": 0,
            "success_jobs": 0,
            "failed_jobs": 0,
            "avg_processing_seconds": 0.0,
            "latest_published_links": [],
            "jobs_by_status": {},
            "processing_series": [],
            "blog_summaries": [],
        }

    job_query = select(Job).where(Job.blog_id.in_(blog_ids)).order_by(Job.created_at.desc())
    jobs = db.execute(job_query).scalars().all()
    now = datetime.now(timezone.utc)
    today = now.date()

    completed_jobs = [job for job in jobs if job.status == JobStatus.COMPLETED]
    failed_jobs = [job for job in jobs if job.status == JobStatus.FAILED]
    today_generated = [job for job in completed_jobs if (job.end_time or job.updated_at).date() == today]

    processing_seconds = []
    for job in completed_jobs:
        if job.start_time and job.end_time:
            processing_seconds.append((job.end_time - job.start_time).total_seconds())

    status_counter = Counter(job.status.value for job in jobs)

    latest_post_query = (
        select(BloggerPost)
        .where(BloggerPost.blog_id.in_(blog_ids))
        .order_by(BloggerPost.published_at.desc().nullslast(), BloggerPost.created_at.desc())
        .limit(5)
    )
    latest_published = db.execute(latest_post_query).scalars().all()

    series = []
    for offset in range(6, -1, -1):
        current_day = (now - timedelta(days=offset)).date()
        day_completed = sum(1 for job in completed_jobs if job.end_time and job.end_time.date() == current_day)
        day_failed = sum(1 for job in failed_jobs if job.end_time and job.end_time.date() == current_day)
        series.append({"date": current_day.isoformat(), "completed": day_completed, "failed": day_failed})

    summary_map = get_blog_summary_map(db, blog_ids)
    blog_summaries = []
    for blog in blogs:
        blog_jobs = [job for job in jobs if job.blog_id == blog.id]
        summary = summary_map.get(blog.id)
        blog_summaries.append(
            {
                "blog_id": blog.id,
                "blog_name": blog.name,
                "blog_slug": blog.slug,
                "content_category": blog.content_category,
                "completed_jobs": summary.completed_jobs if summary else sum(1 for job in blog_jobs if job.status == JobStatus.COMPLETED),
                "failed_jobs": summary.failed_jobs if summary else sum(1 for job in blog_jobs if job.status == JobStatus.FAILED),
                "queued_jobs": sum(1 for job in blog_jobs if job.status not in {JobStatus.COMPLETED, JobStatus.FAILED}),
                "published_posts": summary.published_posts if summary else 0,
                "latest_topic_keywords": summary.latest_topic_keywords if summary else [],
                "latest_published_url": summary.latest_published_url if summary else None,
            }
        )

    return {
        "today_generated_posts": len(today_generated),
        "success_jobs": len(completed_jobs),
        "failed_jobs": len(failed_jobs),
        "avg_processing_seconds": round(sum(processing_seconds) / len(processing_seconds), 2) if processing_seconds else 0.0,
        "latest_published_links": latest_published,
        "jobs_by_status": dict(status_counter),
        "processing_series": series,
        "blog_summaries": blog_summaries,
    }
