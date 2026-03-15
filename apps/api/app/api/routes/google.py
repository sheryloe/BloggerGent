from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.api import BloggerRemotePostRead, GoogleBlogOverviewRead, GoogleIntegrationConfigRead
from app.services.blog_service import get_blog
from app.services.blogger_oauth_service import BloggerOAuthError, get_google_oauth_scopes, get_granted_google_scopes
from app.services.google_reporting_service import (
    build_google_blog_overview,
    list_analytics_properties,
    list_blogger_posts,
    list_search_console_sites,
)
from app.services.settings_service import get_settings_map

router = APIRouter()


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
        payload["warnings"].append(f"Search Console 사이트 목록을 가져오지 못했습니다: {exc.detail}")
    try:
        payload["analytics_properties"] = list_analytics_properties(db)
    except BloggerOAuthError as exc:
        payload["warnings"].append(f"GA4 속성 목록을 가져오지 못했습니다: {exc.detail}")
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
        raise HTTPException(status_code=400, detail="Blogger 블로그 ID가 설정되지 않았습니다.")

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
        return build_google_blog_overview(db, blog, days=days, posts_limit=posts_limit)
    except BloggerOAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
