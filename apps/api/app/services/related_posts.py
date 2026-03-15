from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.entities import Article, BloggerPost, Image, Job, JobStatus
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


def find_related_articles(db: Session, article: Article, limit: int | None = None) -> list[dict]:
    limit = limit or settings.related_post_count
    query = (
        select(Article)
        .join(Job, Job.id == Article.job_id)
        .outerjoin(Image, Image.article_id == Article.id)
        .outerjoin(BloggerPost, BloggerPost.article_id == Article.id)
        .where(Job.status == JobStatus.COMPLETED, Article.blog_id == article.blog_id, Article.id != article.id)
        .options(selectinload(Article.image), selectinload(Article.blogger_post))
        .order_by(Article.created_at.desc())
    )
    candidates = db.execute(query).scalars().unique().all()
    base_embedding = text_to_embedding(f"{article.title} {article.excerpt}")
    ranked: list[tuple[float, Article]] = []
    for candidate in candidates:
        embedding_score = cosine_similarity(base_embedding, text_to_embedding(f"{candidate.title} {candidate.excerpt}"))
        label_score = _label_similarity(article.labels or [], candidate.labels or [])
        score = (label_score * 0.6) + (embedding_score * 0.4)
        ranked.append((score, candidate))
    ranked.sort(key=lambda item: item[0], reverse=True)

    related = []
    for score, candidate in ranked[:limit]:
        related.append(
            {
                "score": round(score, 4),
                "title": candidate.title,
                "slug": candidate.slug,
                "excerpt": candidate.excerpt,
                "thumbnail": candidate.image.public_url if candidate.image else "",
                "link": candidate.blogger_post.published_url if candidate.blogger_post else "#",
            }
        )
    return related


def render_related_cards_html(related_posts: list[dict], section_title: str = "Related Posts") -> str:
    if not related_posts:
        return (
            f"<section class='related-posts'><h2>{section_title}</h2>"
            "<p>추천 글은 라이브러리가 더 쌓이면 이 영역에 자동으로 채워집니다.</p></section>"
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
            "<div style='border:1px solid #e5e7eb;border-radius:18px;padding:14px;background:#fff;'>"
            f"{thumbnail}"
            f"<h3 style='font-size:18px;margin:12px 0 8px;'>{post['title']}</h3>"
            f"<p style='font-size:14px;line-height:1.6;color:#4b5563;'>{post['excerpt']}</p>"
            "</div></a>".format(link=post["link"])
        )

    return (
        "<section class='related-posts' style='margin-top:36px;'>"
        f"<h2 style='font-size:28px;margin-bottom:16px;'>{section_title}</h2>"
        "<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;'>"
        + "".join(cards)
        + "</div></section>"
    )
