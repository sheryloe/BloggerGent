from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.entities import TopicDiscoveryRun


def create_topic_discovery_run(
    db: Session,
    *,
    blog_id: int,
    provider: str,
    model: str | None,
    prompt: str,
    raw_response: dict,
    items: list[dict],
    job_ids: list[int],
) -> TopicDiscoveryRun:
    total_topics = len(items)
    queued_topics = sum(1 for item in items if str(item.get("status", "")).lower() == "queued")
    skipped_topics = max(total_topics - queued_topics, 0)

    run = TopicDiscoveryRun(
        blog_id=blog_id,
        provider=provider or "",
        model=model,
        prompt=prompt or "",
        raw_response=raw_response or {},
        items=items or [],
        queued_topics=queued_topics,
        skipped_topics=skipped_topics,
        total_topics=total_topics,
        job_ids=job_ids or [],
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run
