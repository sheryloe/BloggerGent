from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.entities import AnalyticsArticleFact, Blog, SyncedBloggerPost
from app.schemas.api import (
    BloggerRefactorRead,
    BloggerRefactorRequest,
    BloggerRemotePostRead,
    GoogleBlogIndexingRequest,
    GoogleBlogIndexingQuotaRead,
    GoogleBlogIndexingTestRequest,
    GoogleIndexingStatusRefreshRequest,
    GooglePlaywrightIndexingRequest,
    GoogleBlogOverviewRead,
    GoogleIntegrationConfigRead,
    SyncedBloggerPostGroupPageRead,
    SyncedBloggerPostPageRead,
)
from app.services.platform.blog_service import get_blog
from app.services.blogger.blogger_refactor_service import refactor_blogger_low_score_posts
from app.services.blogger.blogger_oauth_service import BloggerOAuthError, get_google_oauth_scopes, get_granted_google_scopes
from app.services.blogger.blogger_sync_service import (
    list_recent_synced_blogger_posts,
    list_synced_blogger_posts_page,
    sync_connected_blogger_posts,
    sync_blogger_posts_for_blog,
)
from app.services.integrations.google_reporting_service import (
    build_google_blog_overview,
    list_analytics_properties,
    list_blogger_posts,
    list_search_console_sites,
)
from app.services.integrations.google_indexing_service import (
    get_google_blog_indexing_quota,
    load_fact_enrichment_maps,
    refresh_indexing_for_blog,
    refresh_indexing_status_for_scope,
    request_playwright_indexing,
    request_indexing_for_blog,
)
from app.services.ops.dedupe_utils import status_priority as dedupe_status_priority, url_identity_key
from app.services.integrations.settings_service import get_settings_map
from app.tasks.admin import run_blogger_low_score_refactor

router = APIRouter()


def _to_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _score_priority(fact: AnalyticsArticleFact) -> tuple[int, int, datetime]:
    status_rank = dedupe_status_priority(str(fact.status or "").strip().lower())
    source_rank = 1 if str(fact.source_type or "").strip().lower() == "generated" else 0
    updated_at = _to_utc(fact.updated_at) or _to_utc(fact.created_at) or _to_utc(fact.published_at) or datetime.min.replace(tzinfo=timezone.utc)
    return (status_rank, source_rank, updated_at)


def _load_score_map_for_blog(db: Session, *, blog_id: int, urls: set[str]) -> dict[str, dict]:
    identities = {
        url_identity_key(url)
        for url in urls
        if isinstance(url, str) and str(url).strip()
    }
    identities = {key for key in identities if key}
    if not identities:
        return {}

    rows = (
        db.execute(
            select(AnalyticsArticleFact)
            .where(
                AnalyticsArticleFact.blog_id == blog_id,
                AnalyticsArticleFact.actual_url.is_not(None),
                AnalyticsArticleFact.actual_url != "",
            )
            .order_by(AnalyticsArticleFact.id.desc())
        )
        .scalars()
        .all()
    )

    selected: dict[str, dict] = {}
    for row in sorted(rows, key=_score_priority, reverse=True):
        key = url_identity_key(row.actual_url)
        if not key or key not in identities:
            continue
        entry = selected.setdefault(
            key,
            {
                "seo_score": None,
                "geo_score": None,
                "lighthouse_score": None,
            },
        )
        if entry["seo_score"] is None and row.seo_score is not None:
            entry["seo_score"] = row.seo_score
        if entry["geo_score"] is None and row.geo_score is not None:
            entry["geo_score"] = row.geo_score
        if entry["lighthouse_score"] is None and row.lighthouse_score is not None:
            entry["lighthouse_score"] = row.lighthouse_score

    return selected


def _serialize_synced_post(post, state=None, score: dict | None = None, ctr_value: float | None = None) -> dict:
    score_payload = score or {}
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
        "live_image_count": post.live_image_count,
        "live_unique_image_count": getattr(post, "live_unique_image_count", None),
        "live_duplicate_image_count": getattr(post, "live_duplicate_image_count", None),
        "live_webp_count": post.live_webp_count,
        "live_png_count": post.live_png_count,
        "live_other_image_count": post.live_other_image_count,
        "live_cover_present": post.live_cover_present,
        "live_inline_present": post.live_inline_present,
        "live_image_issue": post.live_image_issue,
        "live_image_audited_at": post.live_image_audited_at.isoformat() if post.live_image_audited_at else None,
        "synced_at": post.synced_at.isoformat() if post.synced_at else None,
        "seo_score": score_payload.get("seo_score"),
        "geo_score": score_payload.get("geo_score"),
        "lighthouse_score": score_payload.get("lighthouse_score"),
        "ctr": ctr_value,
        "index_status": state.index_status if state else "unknown",
        "index_coverage_state": state.index_coverage_state if state else None,
        "index_last_checked_at": state.last_checked_at.isoformat() if state and state.last_checked_at else None,
        "next_eligible_at": state.next_eligible_at.isoformat() if state and state.next_eligible_at else None,
        "last_error": state.last_error if state else None,
    }


def _lookup_enrichment_row(enrichment_map: dict, *, blog_id: int, url: str):
    normalized_url = str(url or "").strip()
    if not normalized_url:
        return None
    direct = enrichment_map.get((blog_id, normalized_url))
    if direct is not None:
        return direct
    identity = url_identity_key(normalized_url)
    if identity:
        return enrichment_map.get((blog_id, f"noscheme:{identity}"))
    return None


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
    pairs = {
        (blog.id, post.url.strip())
        for post in payload["items"]
        if isinstance(post.url, str) and post.url.strip()
    }
    state_map, ctr_map = load_fact_enrichment_maps(db, pairs=pairs)
    urls = {post.url.strip() for post in payload["items"] if isinstance(post.url, str) and post.url.strip()}
    score_map = _load_score_map_for_blog(db, blog_id=blog.id, urls=urls)
    items: list[dict] = []
    for post in payload["items"]:
        if isinstance(post.url, str) and post.url.strip():
            url_value = post.url.strip()
            state = _lookup_enrichment_row(state_map, blog_id=blog.id, url=url_value)
            score = score_map.get(url_identity_key(url_value) or "")
            ctr_row = _lookup_enrichment_row(ctr_map, blog_id=blog.id, url=url_value)
            ctr_value = ctr_row.ctr if ctr_row is not None else None
        else:
            state = None
            score = None
            ctr_value = None
        items.append(_serialize_synced_post(post, state, score, ctr_value))

    return {
        "items": items,
        "total": payload["total"],
        "page": payload["page"],
        "page_size": payload["page_size"],
        "last_synced_at": payload["last_synced_at"].isoformat() if payload["last_synced_at"] else None,
    }


@router.get("/synced-posts/grouped-by-blog", response_model=SyncedBloggerPostGroupPageRead)
def get_google_synced_posts_grouped_by_blog(
    db: Session = Depends(get_db),
) -> dict:
    blogs = (
        db.execute(
            select(Blog)
            .where(
                or_(
                    Blog.blogger_blog_id.is_not(None),
                    Blog.blogger_url.is_not(None),
                )
            )
            .order_by(Blog.id.asc())
        )
        .scalars()
        .all()
    )

    groups: list[dict] = []
    for blog in blogs:
        rows = (
            db.execute(
                select(SyncedBloggerPost)
                .where(SyncedBloggerPost.blog_id == blog.id)
                .order_by(
                    SyncedBloggerPost.published_at.desc().nullslast(),
                    SyncedBloggerPost.updated_at_remote.desc().nullslast(),
                    SyncedBloggerPost.id.desc(),
                )
            )
            .scalars()
            .all()
        )
        pairs = {
            (blog.id, row.url.strip())
            for row in rows
            if isinstance(row.url, str) and row.url.strip()
        }
        state_map, ctr_map = load_fact_enrichment_maps(db, pairs=pairs)
        score_map = _load_score_map_for_blog(
            db,
            blog_id=blog.id,
            urls={row.url.strip() for row in rows if isinstance(row.url, str) and row.url.strip()},
        )
        items = []
        for row in rows:
            if isinstance(row.url, str) and row.url.strip():
                url_value = row.url.strip()
                state = _lookup_enrichment_row(state_map, blog_id=blog.id, url=url_value)
                score = score_map.get(url_identity_key(url_value) or "")
                ctr_row = _lookup_enrichment_row(ctr_map, blog_id=blog.id, url=url_value)
                ctr_value = ctr_row.ctr if ctr_row is not None else None
            else:
                state = None
                score = None
                ctr_value = None
            items.append(_serialize_synced_post(row, state, score, ctr_value))

        last_synced_at = max([item.synced_at for item in rows if item.synced_at is not None], default=None)
        groups.append(
            {
                "blog_id": blog.id,
                "blog_name": blog.name,
                "blog_url": blog.blogger_url,
                "total": len(items),
                "last_synced_at": last_synced_at.isoformat() if last_synced_at else None,
                "items": items,
            }
        )

    return {
        "groups": groups,
        "total_groups": len(groups),
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


@router.post("/blogs/{blog_id}/refactor-low-score", response_model=BloggerRefactorRead)
def refactor_google_blog_low_score_posts(
    blog_id: int,
    payload: BloggerRefactorRequest,
    db: Session = Depends(get_db),
) -> dict:
    blog = get_blog(db, blog_id)
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")

    if payload.queue and payload.execute:
        task = run_blogger_low_score_refactor.apply_async(
            kwargs={
                "blog_id": blog_id,
                "threshold": payload.threshold,
                "month": payload.month,
                "limit": payload.limit,
                "sync_before": payload.sync_before,
                "run_lighthouse": payload.run_lighthouse,
                "parallel_workers": payload.parallel_workers,
            },
            queue="default",
        )
        return {
            "status": "queued",
            "execute": True,
            "blog_id": blog.id,
            "blog_name": blog.name,
            "threshold": payload.threshold,
            "month": payload.month or "",
            "parallel_workers": payload.parallel_workers,
            "task_id": task.id,
            "total_candidates": 0,
            "processed_count": 0,
            "updated_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
            "sync_before_result": None,
            "sync_after_result": None,
            "summary_after": None,
            "items": [],
        }

    try:
        return refactor_blogger_low_score_posts(
            db,
            blog_id=blog_id,
            execute=payload.execute,
            threshold=payload.threshold,
            month=payload.month,
            limit=payload.limit,
            sync_before=payload.sync_before,
            run_lighthouse=payload.run_lighthouse,
            parallel_workers=payload.parallel_workers,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/synced-posts/refresh-all")
def refresh_all_google_blog_synced_posts(
    db: Session = Depends(get_db),
) -> dict:
    sync_result = sync_connected_blogger_posts(db)
    warnings = list(sync_result.get("warnings") or [])
    refreshed_blog_ids = [int(item) for item in (sync_result.get("refreshed_blog_ids") or [])]
    skipped_blog_ids = [int(item) for item in (sync_result.get("skipped_blog_ids") or [])]
    return {
        "status": "ok" if not warnings else "partial",
        "refreshed_blog_count": len(refreshed_blog_ids),
        "refreshed_blog_ids": refreshed_blog_ids,
        "skipped_blog_ids": skipped_blog_ids,
        "warnings": warnings,
    }


@router.post("/blogs/{blog_id}/indexing/test")
def test_google_blog_indexing(
    blog_id: int,
    payload: GoogleBlogIndexingTestRequest,
    db: Session = Depends(get_db),
) -> dict:
    blog = get_blog(db, blog_id)
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")

    return refresh_indexing_for_blog(
        db,
        blog_id=blog_id,
        urls=payload.urls,
        limit=payload.limit,
    )


@router.post("/blogs/{blog_id}/indexing/request")
def request_google_blog_indexing(
    blog_id: int,
    payload: GoogleBlogIndexingRequest,
    db: Session = Depends(get_db),
) -> dict:
    blog = get_blog(db, blog_id)
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")

    return request_indexing_for_blog(
        db,
        blog_id=blog_id,
        count=payload.count,
        urls=payload.urls,
        force=payload.force,
        run_test=payload.run_test,
        test_limit=payload.test_limit,
    )


@router.post("/indexing/request-playwright")
def request_google_indexing_playwright(
    payload: GooglePlaywrightIndexingRequest,
    db: Session = Depends(get_db),
) -> dict:
    return request_playwright_indexing(
        db,
        count=payload.count,
        force=payload.force,
        run_test=payload.run_test,
        test_limit=payload.test_limit,
        urls=payload.urls,
        target_scope=payload.target_scope,
        trigger_mode="manual",
    )


@router.post("/indexing/status-refresh")
def refresh_google_indexing_status(
    payload: GoogleIndexingStatusRefreshRequest,
    db: Session = Depends(get_db),
) -> dict:
    _ = payload.run_test
    return refresh_indexing_status_for_scope(
        db,
        urls=payload.urls,
        target_scope=payload.target_scope,
        force=payload.force,
        trigger_mode="manual",
    )


@router.get("/blogs/{blog_id}/indexing/quota", response_model=GoogleBlogIndexingQuotaRead)
def get_google_blog_indexing_quota_view(
    blog_id: int,
    db: Session = Depends(get_db),
) -> dict:
    blog = get_blog(db, blog_id)
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")
    return get_google_blog_indexing_quota(db, blog_id=blog_id)
