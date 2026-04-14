from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models.entities import Article
from app.schemas.api import (
    ArticleDetailRead,
    ArticleListItemRead,
    ArticlePublishRequest,
    ArticleSearchDescriptionSyncRead,
    ArticleSeoMetaRead,
)
from app.services.content.blog_seo_meta_service import get_article_seo_meta_overview, verify_article_seo_meta
from app.services.platform.blog_service import list_visible_blog_ids
from app.services.blogger.blogger_editor_service import BloggerEditorAutomationError, sync_article_search_description
from app.services.platform.publishing_service import (
    enqueue_publish_request,
    load_article_for_publish,
    resolve_request_datetime,
)
from app.services.providers.base import ProviderRuntimeError
from app.services.content.topic_guard_service import TopicGuardConflictError

router = APIRouter()


def _record_search_description_sync(
    db: Session,
    *,
    article: Article,
    status: str,
    message: str,
    editor_url: str | None = None,
    cdp_url: str | None = None,
) -> None:
    if not article.blogger_post:
        return

    payload = dict(article.blogger_post.response_payload or {})
    payload["search_description_sync"] = {
        "status": status,
        "message": message,
        "editor_url": editor_url or "",
        "cdp_url": cdp_url or "",
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    article.blogger_post.response_payload = payload
    db.add(article.blogger_post)
    db.commit()
    db.refresh(article.blogger_post)


def _article_query(limit: int | None = None):
    query = (
        select(Article)
        .options(
            selectinload(Article.blog),
            selectinload(Article.image),
            selectinload(Article.blogger_post),
            selectinload(Article.publish_queue_items),
        )
        .order_by(Article.created_at.desc())
    )
    if limit is not None:
        query = query.limit(limit)
    return query


@router.get("", response_model=list[ArticleListItemRead])
def list_articles(
    limit: int = Query(default=20, le=100),
    blog_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[Article]:
    visible_blog_ids = set(list_visible_blog_ids(db))
    if not visible_blog_ids:
        return []
    if blog_id and blog_id not in visible_blog_ids:
        return []

    query = _article_query(limit).where(Article.blog_id.in_(visible_blog_ids))
    if blog_id:
        query = query.where(Article.blog_id == blog_id)
    return db.execute(query).scalars().unique().all()


@router.get("/{article_id}", response_model=ArticleDetailRead)
def get_article(article_id: int, db: Session = Depends(get_db)) -> Article:
    article = load_article_for_publish(db, article_id)
    if not article or article.blog_id not in set(list_visible_blog_ids(db)):
        raise HTTPException(status_code=404, detail="Article not found")
    return article


@router.post("/{article_id}/publish", response_model=ArticleDetailRead)
def publish_article(
    article_id: int,
    payload: ArticlePublishRequest | None = Body(default=None),
    db: Session = Depends(get_db),
) -> Article:
    try:
        request_payload = payload or ArticlePublishRequest()
        article = load_article_for_publish(db, article_id)
        if not article or article.blog_id not in set(list_visible_blog_ids(db)):
            raise HTTPException(status_code=404, detail="Article not found")

        scheduled_for = resolve_request_datetime(db, request_payload.scheduled_for)
        if request_payload.mode == "schedule":
            if scheduled_for is None:
                raise HTTPException(status_code=422, detail="scheduled_for is required when mode is schedule")
            if scheduled_for <= datetime.now(timezone.utc):
                raise HTTPException(status_code=422, detail="scheduled_for must be in the future")

        try:
            enqueue_publish_request(db, article=article, mode=request_payload.mode, scheduled_for=scheduled_for)
        except TopicGuardConflictError as exc:
            raise HTTPException(status_code=409, detail=exc.to_detail()) from exc
        except ValueError as exc:
            message = str(exc)
            status_code = 409
            raise HTTPException(status_code=status_code, detail=message) from exc

        refreshed = load_article_for_publish(db, article_id)
        if not refreshed:
            raise HTTPException(status_code=404, detail="Article not found after queueing publish")
        return refreshed
    except ProviderRuntimeError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code or 502, detail=exc.detail or exc.message) from exc


@router.get("/{article_id}/seo-meta", response_model=ArticleSeoMetaRead)
def get_article_seo_meta(article_id: int, db: Session = Depends(get_db)) -> dict:
    article = db.execute(
        select(Article)
        .where(Article.id == article_id)
        .options(selectinload(Article.blog), selectinload(Article.blogger_post))
    ).scalar_one_or_none()
    if not article or article.blog_id not in set(list_visible_blog_ids(db)):
        raise HTTPException(status_code=404, detail="Article not found")
    return get_article_seo_meta_overview(article)


@router.post("/{article_id}/seo-meta/verify", response_model=ArticleSeoMetaRead)
def verify_article_seo_meta_status(article_id: int, db: Session = Depends(get_db)) -> dict:
    article = db.execute(
        select(Article)
        .where(Article.id == article_id)
        .options(selectinload(Article.blog), selectinload(Article.blogger_post))
    ).scalar_one_or_none()
    if not article or article.blog_id not in set(list_visible_blog_ids(db)):
        raise HTTPException(status_code=404, detail="Article not found")
    return verify_article_seo_meta(article)


@router.post("/{article_id}/search-description/sync", response_model=ArticleSearchDescriptionSyncRead)
def sync_article_search_description_status(article_id: int, db: Session = Depends(get_db)) -> dict:
    article = db.execute(
        select(Article)
        .where(Article.id == article_id)
        .options(selectinload(Article.blog), selectinload(Article.blogger_post))
    ).scalar_one_or_none()
    if not article or article.blog_id not in set(list_visible_blog_ids(db)):
        raise HTTPException(status_code=404, detail="Article not found")

    try:
        result = sync_article_search_description(db, article)
    except BloggerEditorAutomationError as exc:
        _record_search_description_sync(
            db,
            article=article,
            status="error",
            message=exc.message,
        )
        raise HTTPException(status_code=502, detail=exc.message) from exc

    _record_search_description_sync(
        db,
        article=article,
        status=result.status,
        message=result.message,
        editor_url=result.editor_url,
        cdp_url=result.cdp_url,
    )
    return {
        "article_id": article.id,
        "blogger_post_id": article.blogger_post.blogger_post_id if article.blogger_post else "",
        "editor_url": result.editor_url,
        "cdp_url": result.cdp_url,
        "description": result.description,
        "status": result.status,
        "message": result.message,
    }
