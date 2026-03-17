from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.entities import Article, BloggerPost, Image, Job, JobStatus, SyncedBloggerPost
from app.utils.embeddings import cosine_similarity, text_to_embedding


def _label_similarity(left: list[str], right: list[str]) -> float:
    if not left or not right:
        return 0.0
    left_set = {item.lower() for item in left}
    right_set = {item.lower() for item in right}
    union = left_set | right_set
    if not union:
        return 0.0
    return len(left_set & right_set) / len(union)


def _normalize_text(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _urls_match(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return left.rstrip("/") == right.rstrip("/")


def _titles_match(left: str | None, right: str | None) -> bool:
    normalized_left = _normalize_text(left)
    normalized_right = _normalize_text(right)
    if not normalized_left or not normalized_right:
        return False
    if normalized_left == normalized_right:
        return True
    return SequenceMatcher(a=normalized_left, b=normalized_right).ratio() >= 0.94


def _related_payload(
    *,
    score: float,
    title: str,
    excerpt: str,
    thumbnail: str,
    link: str,
    source: str,
    published_at,
    slug: str | None = None,
) -> dict[str, Any]:
    return {
        "score": round(score, 4),
        "title": title,
        "slug": slug or "",
        "excerpt": excerpt,
        "thumbnail": thumbnail,
        "link": link,
        "source": source,
        "published_at": published_at.isoformat() if published_at else None,
    }


def find_related_articles(db: Session, article: Article, limit: int | None = None) -> list[dict]:
    limit = limit or settings.related_post_count
    generated_query = (
        select(Article)
        .join(Job, Job.id == Article.job_id)
        .outerjoin(Image, Image.article_id == Article.id)
        .outerjoin(BloggerPost, BloggerPost.article_id == Article.id)
        .where(Job.status == JobStatus.COMPLETED, Article.blog_id == article.blog_id, Article.id != article.id)
        .options(selectinload(Article.image), selectinload(Article.blogger_post))
        .order_by(Article.created_at.desc())
    )
    synced_query = (
        select(SyncedBloggerPost)
        .where(SyncedBloggerPost.blog_id == article.blog_id)
        .order_by(
            SyncedBloggerPost.published_at.desc().nullslast(),
            SyncedBloggerPost.updated_at_remote.desc().nullslast(),
            SyncedBloggerPost.id.desc(),
        )
    )

    generated_candidates = db.execute(generated_query).scalars().unique().all()
    synced_candidates = db.execute(synced_query).scalars().all()
    base_embedding = text_to_embedding(f"{article.title} {article.excerpt}")
    current_url = article.blogger_post.published_url if article.blogger_post else None

    ranked: list[tuple[float, dict[str, Any]]] = []

    for candidate in generated_candidates:
        candidate_embedding = text_to_embedding(f"{candidate.title} {candidate.excerpt}")
        embedding_score = cosine_similarity(base_embedding, candidate_embedding)
        label_score = _label_similarity(article.labels or [], candidate.labels or [])
        score = (label_score * 0.6) + (embedding_score * 0.4)
        ranked.append(
            (
                score,
                _related_payload(
                    score=score,
                    title=candidate.title,
                    slug=candidate.slug,
                    excerpt=candidate.excerpt,
                    thumbnail=candidate.image.public_url if candidate.image else "",
                    link=candidate.blogger_post.published_url if candidate.blogger_post else "#",
                    source="generated",
                    published_at=candidate.blogger_post.published_at if candidate.blogger_post else None,
                ),
            )
        )

    for candidate in synced_candidates:
        if _urls_match(candidate.url, current_url) or _titles_match(candidate.title, article.title):
            continue
        candidate_text = " ".join(
            [
                candidate.title,
                candidate.excerpt_text or "",
                " ".join(candidate.labels or []),
            ]
        ).strip()
        candidate_embedding = text_to_embedding(candidate_text)
        embedding_score = cosine_similarity(base_embedding, candidate_embedding)
        label_score = _label_similarity(article.labels or [], candidate.labels or [])
        score = (label_score * 0.6) + (embedding_score * 0.4)
        ranked.append(
            (
                score,
                _related_payload(
                    score=score,
                    title=candidate.title,
                    excerpt=candidate.excerpt_text,
                    thumbnail=candidate.thumbnail_url or "",
                    link=candidate.url or "#",
                    source="synced",
                    published_at=candidate.published_at,
                ),
            )
        )

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [payload for _, payload in ranked[:limit]]


def render_related_cards_html(
    related_posts: list[dict],
    section_title: str = "Related Posts",
    *,
    category: str = "",
) -> str:
    category = (category or "").lower()
    card_background = "rgba(255,255,255,0.05)" if category == "mystery" else "#f8fafc"
    card_border = "rgba(255,255,255,0.16)" if category == "mystery" else "#e2e8f0"
    heading_color = "#f8fafc" if category == "mystery" else "#0f172a"
    body_color = "#e5e7eb" if category == "mystery" else "#475569"

    if not related_posts:
        return (
            f"<section class='related-posts'><h2>{section_title}</h2>"
            "<p>Relevant posts will appear here once this blog has more published content.</p></section>"
        )

    cards = []
    for post in related_posts:
        thumbnail = (
            f"<img src='{post['thumbnail']}' alt='{post['title']}' "
            "style='width:100%;height:120px;object-fit:cover;border-radius:14px;' />"
            if post["thumbnail"]
            else ""
        )
        cards.append(
            "<a href='{link}' style='display:block;text-decoration:none;color:#1f2937;'>"
            f"<div style='border:1px solid {card_border};border-radius:18px;padding:14px;background:{card_background};backdrop-filter:blur(8px);'>"
            f"{thumbnail}"
            f"<h3 style='font-size:18px;margin:12px 0 8px;color:{heading_color};'>{post['title']}</h3>"
            f"<p style='font-size:14px;line-height:1.7;color:{body_color};'>{post['excerpt']}</p>"
            "</div></a>".format(link=post["link"])
        )

    return (
        "<section class='related-posts' style='margin-top:36px;'>"
        f"<h2 style='font-size:28px;margin-bottom:16px;color:{heading_color};'>{section_title}</h2>"
        "<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;'>"
        + "".join(cards)
        + "</div></section>"
    )
