from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas.api import HelpTopicRead
from app.services.integrations.help_service import get_help_topic, list_help_topics


router = APIRouter()


@router.get("/topics", response_model=list[HelpTopicRead])
def get_help_topics(
    keyword: str | None = Query(default=None, min_length=1, max_length=200),
    tag: str | None = Query(default=None, min_length=1, max_length=50),
) -> list[dict]:
    return list_help_topics(keyword=keyword, tag=tag)


@router.get("/topics/{topic_id}", response_model=HelpTopicRead)
def get_help_topic_by_id(topic_id: str) -> dict:
    payload = get_help_topic(topic_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="help_topic_not_found")
    return payload
