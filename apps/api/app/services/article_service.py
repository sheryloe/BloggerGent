from __future__ import annotations

import re

from slugify import slugify
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Article, Job, Topic
from app.schemas.ai import ArticleGenerationOutput
from app.services.content_guard_service import assert_article_not_duplicate


TAG_RE = re.compile(r"<[^>]+>")
HTML_TAG_RE = re.compile(r"</?([a-zA-Z0-9]+)(?:\s[^>]*)?>")
ALLOWED_HTML_TAGS = {"h2", "h3", "p", "ul", "li", "strong", "br"}
RELATED_POSTS_TOKEN = "__RELATED_POSTS_PLACEHOLDER__"


def estimate_reading_time(html_fragment: str) -> int:
    text = TAG_RE.sub(" ", html_fragment)
    words = [word for word in text.split() if word.strip()]
    return max(4, round(len(words) / 180))


def sanitize_blog_html(html_fragment: str) -> str:
    preserved = html_fragment.replace("<!--RELATED_POSTS-->", RELATED_POSTS_TOKEN)

    def replace_tag(match: re.Match[str]) -> str:
        raw = match.group(0)
        tag_name = match.group(1).lower()
        if tag_name not in ALLOWED_HTML_TAGS:
            return ""
        if raw.startswith("</"):
            return f"</{tag_name}>"
        if tag_name == "br":
            return "<br>"
        return f"<{tag_name}>"

    sanitized = HTML_TAG_RE.sub(replace_tag, preserved)
    sanitized = sanitized.replace(RELATED_POSTS_TOKEN, "<!--RELATED_POSTS-->")
    return sanitized.strip()


def ensure_unique_slug(db: Session, blog_id: int, slug_base: str, article_id: int | None = None) -> str:
    slug = slugify(slug_base) or "post"
    candidate = slug
    counter = 2
    while True:
        existing = db.execute(
            select(Article).where(Article.blog_id == blog_id, Article.slug == candidate)
        ).scalar_one_or_none()
        if not existing or existing.id == article_id:
            return candidate
        candidate = f"{slug}-{counter}"
        counter += 1


def save_article(db: Session, *, job: Job, topic: Topic | None, output: ArticleGenerationOutput) -> Article:
    article = db.execute(select(Article).where(Article.job_id == job.id)).scalar_one_or_none()
    slug_candidate = slugify(output.slug or output.title) or "post"
    assert_article_not_duplicate(
        db,
        blog_id=job.blog_id,
        title=output.title,
        slug=slug_candidate,
        exclude_article_id=article.id if article else None,
    )
    sanitized_html = sanitize_blog_html(output.html_article)
    payload = {
        "blog_id": job.blog_id,
        "topic_id": topic.id if topic else None,
        "title": output.title,
        "meta_description": output.meta_description,
        "labels": output.labels,
        "slug": slug_candidate,
        "excerpt": output.excerpt,
        "html_article": sanitized_html,
        "faq_section": [item.model_dump() for item in output.faq_section],
        "image_collage_prompt": output.image_collage_prompt,
        "reading_time_minutes": estimate_reading_time(sanitized_html),
    }
    if article:
        for key, value in payload.items():
            setattr(article, key, value)
    else:
        article = Article(job_id=job.id, **payload)
        db.add(article)
    db.commit()
    db.refresh(article)
    return article


def build_collage_article_context(article: Article) -> str:
    labels = ", ".join(article.labels or [])
    return "\n".join(
        [
            f"Blog: {article.blog.name if article.blog else ''}",
            f"Title: {article.title}",
            f"Excerpt: {article.excerpt}",
            f"Labels: {labels}",
            f"Article HTML: {article.html_article}",
            f"Initial image direction: {article.image_collage_prompt}",
        ]
    )


def build_collage_prompt(article: Article, prompt_template: str | None = None) -> str:
    if prompt_template:
        article_context = build_collage_article_context(article)
        return prompt_template.replace("{article_context}", article_context).strip()

    return (
        f"{article.image_collage_prompt.strip()}. "
        "Create a single editorial cover image with realistic photography, no text overlay, and cohesive lighting."
    )
