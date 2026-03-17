from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.api import (
    BloggerRemotePostRead,
    GoogleBlogOverviewRead,
    GoogleIntegrationConfigRead,
    SyncedBloggerPostPageRead,
)
from app.services.blog_service import get_blog
from app.services.blogger_oauth_service import BloggerOAuthError, get_google_oauth_scopes, get_granted_google_scopes
from app.services.blogger_sync_service import (
    list_recent_synced_blogger_posts,
    list_synced_blogger_posts_page,
    sync_blogger_posts_for_blog,
)
from app.services.google_reporting_service import (
    build_google_blog_overview,
    list_analytics_properties,
    list_blogger_posts,
    list_search_console_sites,
)
from app.services.settings_service import get_settings_map

router = APIRouter()


def _serialize_synced_post(post) -> dict:
    return {
        "id": post.remote_post_id,
        "title": post.title,
        "url": post.url,
        "status": post.status,
        "published": post.published_at.isoformat() if post.published_at else None,
        "updated": post.updated_at_remote.isoformat() if post.updated_at_remote else None,
        "labels": post.labels or [],
        "author_display_name": post.author_display_name,
        "replies_total_items": post.replies_total_items,
        "content_html": post.content_html,
        "thumbnail_url": post.thumbnail_url,
        "excerpt_text": post.excerpt_text,
        "synced_at": post.synced_at.isoformat() if post.synced_at else None,
    }


@router.get("/integrations", response_model=GoogleIntegrationConfigRead)
def get_google_integrations(db: Session = Depends(get_db)) -> dict:
    values = get_settings_map(db)
    payload = {
        "oauth_scopes": get_google_oauth_scopes(),
        "granted_scopes": get_granted_google_scopes(values),
        "search_console_sites": [],
        "analytics_properties": [],
        "warnings": [],
    }
    try:
        payload["search_console_sites"] = list_search_console_sites(db)
    except BloggerOAuthError as exc:
        payload["warnings"].append(f"Failed to load Search Console sites: {exc.detail}")
    try:
        payload["analytics_properties"] = list_analytics_properties(db)
    except BloggerOAuthError as exc:
        payload["warnings"].append(f"Failed to load GA4 properties: {exc.detail}")
    return payload


@router.get("/blogs/{blog_id}/posts", response_model=list[BloggerRemotePostRead])
def get_google_blog_posts(
    blog_id: int,
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> list[dict]:
    blog = get_blog(db, blog_id)
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")
    if not blog.blogger_blog_id:
        raise HTTPException(status_code=400, detail="Blogger blog id is not configured.")

    try:
        return list_blogger_posts(db, blog.blogger_blog_id, max_results=limit)
    except BloggerOAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/blogs/{blog_id}/overview", response_model=GoogleBlogOverviewRead)
def get_google_blog_overview(
    blog_id: int,
    days: int = Query(default=28, ge=7, le=90),
    posts_limit: int = Query(default=10, ge=1, le=25),
    db: Session = Depends(get_db),
) -> dict:
    blog = get_blog(db, blog_id)
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")

    try:
        overview = build_google_blog_overview(db, blog, days=days, posts_limit=posts_limit)
    except BloggerOAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    overview["recent_posts"] = [_serialize_synced_post(post) for post in list_recent_synced_blogger_posts(db, blog, limit=posts_limit)]
    return overview


@router.get("/blogs/{blog_id}/synced-posts", response_model=SyncedBloggerPostPageRead)
def get_google_blog_synced_posts(
    blog_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    blog = get_blog(db, blog_id)
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")

    payload = list_synced_blogger_posts_page(db, blog, page=page, page_size=page_size)
    return {
        "items": [_serialize_synced_post(post) for post in payload["items"]],
        "total": payload["total"],
        "page": payload["page"],
        "page_size": payload["page_size"],
        "last_synced_at": payload["last_synced_at"].isoformat() if payload["last_synced_at"] else None,
    }


@router.post("/blogs/{blog_id}/synced-posts/refresh")
def refresh_google_blog_synced_posts(
    blog_id: int,
    db: Session = Depends(get_db),
) -> dict:
    blog = get_blog(db, blog_id)
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")
    if not blog.blogger_blog_id:
        raise HTTPException(status_code=400, detail="Blogger blog id is not configured.")

    try:
        result = sync_blogger_posts_for_blog(db, blog)
    except BloggerOAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return {
        "blog_id": result["blog_id"],
        "count": result["count"],
        "last_synced_at": result["last_synced_at"].isoformat() if result["last_synced_at"] else None,
    }
