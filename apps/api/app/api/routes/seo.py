from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.api import SeoTargetRead
from app.services.platform.blog_service import list_connected_blogs
from app.services.cloudflare.cloudflare_channel_service import get_cloudflare_overview
from app.services.platform.workspace_service import list_managed_channels

router = APIRouter(prefix="/seo", tags=["seo"])

_MOJIBAKE_HINTS: tuple[str, ...] = ("�",)


def _safe_blog_label(value: str | None, *, blog_id: int) -> str:
    raw = str(value or "").strip()
    if not raw:
        return f"Blogger Blog {blog_id}"
    if raw.count("?") >= 3 or any(token in raw for token in _MOJIBAKE_HINTS):
        return f"Blogger Blog {blog_id}"
    return raw


@router.get("/targets", response_model=list[SeoTargetRead])
def get_seo_targets(db: Session = Depends(get_db)) -> list[SeoTargetRead]:
    channels = {channel.channel_id: channel for channel in list_managed_channels(db, include_disconnected=False)}
    targets: list[SeoTargetRead] = []

    for blog in list_connected_blogs(db):
        channel_id = f"blogger:{blog.id}"
        channel = channels.get(channel_id)
        preferred_label = channel.display_name if channel else blog.name
        targets.append(
            SeoTargetRead(
                target_id=channel_id,
                provider="blogger",
                channel_id=channel_id,
                label=_safe_blog_label(preferred_label, blog_id=blog.id),
                base_url=blog.blogger_url,
                linked_blog_id=blog.id,
                search_console_site_url=blog.search_console_site_url,
                ga4_property_id=blog.ga4_property_id,
                oauth_state=str(channel.oauth_state if channel else "unknown"),
                is_connected=bool(channel and channel.status == "connected"),
            )
        )

    cloudflare_channel = next((channel for channel in channels.values() if channel.provider == "cloudflare"), None)
    if cloudflare_channel is not None:
        overview = get_cloudflare_overview(db)
        targets.append(
            SeoTargetRead(
                target_id=cloudflare_channel.channel_id,
                provider="cloudflare",
                channel_id=cloudflare_channel.channel_id,
                label=overview.get("channel_name") or cloudflare_channel.display_name,
                base_url=overview.get("base_url") or cloudflare_channel.base_url,
                linked_blog_id=None,
                search_console_site_url=None,
                ga4_property_id=None,
                oauth_state=str(cloudflare_channel.oauth_state or "unknown"),
                is_connected=str(cloudflare_channel.status or "").lower() == "connected",
            )
        )

    return targets
