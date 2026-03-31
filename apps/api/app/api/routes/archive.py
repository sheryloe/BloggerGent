from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query

from app.schemas.api import ArchiveChannelListRead, ArchiveChannelPageRead

router = APIRouter()


@router.get("/channels", response_model=ArchiveChannelListRead)
def list_archive_channels() -> dict:
    return {"items": []}


@router.get("/channel/{channel_key}", response_model=ArchiveChannelPageRead)
def get_archive_channel_page(
    channel_key: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
    category: str | None = Query(default=None),
) -> dict:
    return {
        "channel_key": channel_key,
        "channel_label": channel_key,
        "provider": "blogger",
        "channel_id": channel_key,
        "channel_name": channel_key,
        "provider_status": "disconnected",
        "items": [],
        "total": 0,
        "page": page,
        "page_size": page_size,
        "last_synced_at": datetime.now(timezone.utc).isoformat(),
        "available_categories": [],
        "selected_category": category,
    }
