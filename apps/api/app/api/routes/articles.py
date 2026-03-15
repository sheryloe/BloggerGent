from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models.entities import Article, BloggerPost, PublishMode
from app.schemas.api import ArticleRead, ArticleSeoMetaRead
from app.services.blog_seo_meta_service import get_article_seo_meta_overview, verify_article_seo_meta
from app.services.blog_service import list_visible_blog_ids
from app.services.html_assembler import assemble_article_html
from app.services.providers.base import ProviderRuntimeError
from app.services.providers.factory import get_blogger_provider
from app.services.related_posts import find_related_articles
from app.services.storage_service import ensure_existing_public_image_url, is_private_asset_url, save_html

router = APIRouter()


def _upsert_article_blogger_post(
    db: Session,
    *,
    article: Article,
    summary: dict,
    raw_payload: dict,
) -> BloggerPost:
    blogger_post = article.blogger_post or db.execute(
        select(BloggerPost).where(BloggerPost.job_id == article.job_id)
    ).scalar_one_or_none()
    published_at = summary.get("published")
    if isinstance(published_at, str):
        published_at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))

    payload = {
        "blog_id": article.blog_id,
        "article_id": article.id,
        "blogger_post_id": summary.get("id", f"article-{article.id}"),
        "published_url": summary.get("url", ""),
        "published_at": published_at,
        "is_draft": bool(summary.get("isDraft", True)),
        "response_payload": raw_payload,
    }

    if blogger_post:
        for key, value in payload.items():
            setattr(blogger_post, key, value)
    else:
        blogger_post = BloggerPost(job_id=article.job_id, **payload)
        db.add(blogger_post)

    db.commit()
    db.refresh(blogger_post)
    return blogger_post


def _refresh_article_public_image(db: Session, article: Article) -> str | None:
    image = article.image
    if not image:
        return None
    if not (image.file_path or "").strip():
        return image.public_url

    public_url, delivery_meta = ensure_existing_public_image_url(db, file_path=image.file_path)
    metadata = dict(image.image_metadata or {})
    delivery = dict(metadata.get("delivery") or {})
    delivery.update(delivery_meta)
    metadata["delivery"] = delivery

    image.public_url = public_url
    image.image_metadata = metadata
    db.add(image)
    return public_url


def _rebuild_article_html(db: Session, article: Article, hero_image_url: str) -> str:
    db.refresh(article, attribute_names=["blog"])
    related_posts = find_related_articles(db, article)
    assembled_html = assemble_article_html(article, hero_image_url, related_posts)
    article.assembled_html = assembled_html
    db.add(article)
    db.commit()
    db.refresh(article)
    save_html(slug=article.slug, html=assembled_html)
    return assembled_html


@router.get("", response_model=list[ArticleRead])
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

    query = (
        select(Article)
        .where(Article.blog_id.in_(visible_blog_ids))
        .options(selectinload(Article.blog), selectinload(Article.image), selectinload(Article.blogger_post))
        .order_by(Article.created_at.desc())
        .limit(limit)
    )
    if blog_id:
        query = query.where(Article.blog_id == blog_id)
    return db.execute(query).scalars().unique().all()


@router.get("/{article_id}", response_model=ArticleRead)
def get_article(article_id: int, db: Session = Depends(get_db)) -> Article:
    article = db.execute(
        select(Article)
        .where(Article.id == article_id)
        .options(selectinload(Article.blog), selectinload(Article.image), selectinload(Article.blogger_post))
    ).scalar_one_or_none()
    if not article or article.blog_id not in set(list_visible_blog_ids(db)):
        raise HTTPException(status_code=404, detail="Article not found")
    return article


@router.post("/{article_id}/publish", response_model=ArticleRead)
def publish_article(article_id: int, db: Session = Depends(get_db)) -> Article:
    try:
        article = db.execute(
            select(Article)
            .where(Article.id == article_id)
            .options(selectinload(Article.blog), selectinload(Article.image), selectinload(Article.blogger_post))
        ).scalar_one_or_none()
        if not article or article.blog_id not in set(list_visible_blog_ids(db)):
            raise HTTPException(status_code=404, detail="Article not found")
        if not article.blog or not (article.blog.blogger_blog_id or "").strip():
            raise HTTPException(status_code=400, detail="Blogger blog is not connected for this article")
        hero_image_url = _refresh_article_public_image(db, article) or (article.image.public_url if article.image else "")
        assembled_html = _rebuild_article_html(db, article, hero_image_url)
        if not (assembled_html or "").strip():
            raise HTTPException(status_code=400, detail="Assembled HTML is missing for this article")

        provider = get_blogger_provider(db, article.blog)
        if getattr(provider, "access_token", "") and is_private_asset_url(hero_image_url):
            raise HTTPException(
                status_code=400,
                detail="대표 이미지가 아직 공개 URL이 아닙니다. public_asset_base_url 또는 Cloudinary 설정을 먼저 저장해주세요.",
            )
        existing_post = article.blogger_post
        if existing_post and not existing_post.is_draft:
            raise HTTPException(
                status_code=409,
                detail="이미 공개된 글은 덮어쓸 수 없습니다. 새 글로 다시 생성하거나 초안 상태에서만 게시하세요.",
            )

        if existing_post and hasattr(provider, "update_post"):
            update_summary, update_payload = provider.update_post(
                post_id=existing_post.blogger_post_id,
                title=article.title,
                content=assembled_html,
                labels=article.labels,
                meta_description=article.meta_description,
            )
            if existing_post.is_draft and hasattr(provider, "publish_draft"):
                publish_summary, publish_payload = provider.publish_draft(existing_post.blogger_post_id)
                summary = publish_summary
                raw_payload = {"update": update_payload, "publish": publish_payload}
            else:
                summary = update_summary
                raw_payload = update_payload
        else:
            summary, raw_payload = provider.publish(
                title=article.title,
                content=assembled_html or article.html_article,
                labels=article.labels,
                meta_description=article.meta_description,
                slug=article.slug,
                publish_mode=PublishMode.PUBLISH,
            )

        _upsert_article_blogger_post(db, article=article, summary=summary, raw_payload=raw_payload)
        refreshed = db.execute(
            select(Article)
            .where(Article.id == article_id)
            .options(selectinload(Article.blog), selectinload(Article.image), selectinload(Article.blogger_post))
        ).scalar_one_or_none()
        if not refreshed:
            raise HTTPException(status_code=404, detail="Article not found after publishing")
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
