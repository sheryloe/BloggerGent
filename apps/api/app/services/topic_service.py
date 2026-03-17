from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Blog, Topic
from app.schemas.ai import TopicDiscoveryItem


def upsert_topics(
    db: Session,
    blog: Blog,
    items: list[TopicDiscoveryItem],
    *,
    metadata_by_keyword: dict[str, dict[str, str]] | None = None,
) -> list[Topic]:
    if not items:
        return []

    metadata_by_keyword = metadata_by_keyword or {}
    existing = {
        topic.keyword: topic
        for topic in db.execute(
            select(Topic).where(Topic.blog_id == blog.id, Topic.keyword.in_([item.keyword for item in items]))
        )
        .scalars()
        .all()
    }
    topics: list[Topic] = []
    for item in items:
        topic = existing.get(item.keyword)
        metadata = metadata_by_keyword.get(item.keyword, {})
        if topic:
            topic.reason = item.reason
            topic.trend_score = item.trend_score
            topic.topic_cluster_label = metadata.get("topic_cluster_label")
            topic.topic_angle_label = metadata.get("topic_angle_label")
            topic.distinct_reason = metadata.get("distinct_reason")
        else:
            topic = Topic(
                blog_id=blog.id,
                keyword=item.keyword,
                reason=item.reason,
                trend_score=item.trend_score,
                source="gemini",
                locale=blog.primary_language or "global",
                topic_cluster_label=metadata.get("topic_cluster_label"),
                topic_angle_label=metadata.get("topic_angle_label"),
                distinct_reason=metadata.get("distinct_reason"),
            )
            db.add(topic)
        topics.append(topic)
    db.commit()
    for topic in topics:
        db.refresh(topic)
    return topics
