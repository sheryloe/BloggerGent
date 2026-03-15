from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Blog, Topic
from app.schemas.ai import TopicDiscoveryItem


def upsert_topics(db: Session, blog: Blog, items: list[TopicDiscoveryItem]) -> list[Topic]:
    if not items:
        return []

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
        if topic:
            topic.reason = item.reason
            topic.trend_score = item.trend_score
        else:
            topic = Topic(
                blog_id=blog.id,
                keyword=item.keyword,
                reason=item.reason,
                trend_score=item.trend_score,
                source="gemini",
                locale=blog.primary_language or "global",
            )
            db.add(topic)
        topics.append(topic)
    db.commit()
    for topic in topics:
        db.refresh(topic)
    return topics
