from __future__ import annotations

import re

from slugify import slugify
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Article, ContentPlanSlot, Job, Topic
from app.schemas.ai import ArticleGenerationOutput
from app.services.content_guard_service import assert_article_not_duplicate


TAG_RE = re.compile(r"<[^>]+>")
HTML_TAG_RE = re.compile(r"</?([a-zA-Z0-9]+)(?:\s[^>]*)?>")
ALLOWED_HTML_TAGS = {"h2", "h3", "p", "ul", "li", "strong", "br"}
RELATED_POSTS_TOKEN = "__RELATED_POSTS_PLACEHOLDER__"
TRAVEL_EDITORIAL_CATEGORY_MAP: dict[str, tuple[str, tuple[str, ...]]] = {
    "travel": (
        "Travel",
        ("travel", "trip", "route", "itinerary", "walk", "neighborhood", "local", "course"),
    ),
    "culture": (
        "Culture",
        ("culture", "festival", "event", "exhibition", "museum", "heritage", "idol", "filming"),
    ),
    "food": (
        "Food",
        ("food", "restaurant", "market", "cafe", "eatery", "korean food", "dining", "bakery"),
    ),
}
MYSTERY_EDITORIAL_CATEGORY_MAP: dict[str, tuple[str, tuple[str, ...]]] = {
    "case-files": (
        "Case Files",
        ("case", "incident", "investigation", "evidence", "timeline", "disappearance", "murder"),
    ),
    "legends-lore": (
        "Legends & Lore",
        ("legend", "folklore", "myth", "urban legend", "scp", "lore", "haunted"),
    ),
    "mystery-archives": (
        "Mystery Archives",
        ("archive", "historical", "record", "document", "expedition", "manuscript", "chronology"),
    ),
}


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


def _editorial_category_map(profile_key: str) -> dict[str, tuple[str, tuple[str, ...]]]:
    normalized = (profile_key or "").strip().lower()
    if normalized == "korea_travel":
        return TRAVEL_EDITORIAL_CATEGORY_MAP
    if normalized == "world_mystery":
        return MYSTERY_EDITORIAL_CATEGORY_MAP
    return {}


def _normalize_label_key(value: str | None) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _dedupe_labels(labels: list[str] | None) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for raw in labels or []:
        value = str(raw or "").strip()
        if not value:
            continue
        key = _normalize_label_key(value)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def infer_editorial_category(
    *,
    profile_key: str,
    labels: list[str],
    title: str,
    summary: str,
) -> tuple[str, str]:
    category_map = _editorial_category_map(profile_key)
    if not category_map:
        return "", ""

    normalized_labels = {_normalize_label_key(label) for label in labels if str(label or "").strip()}
    for key, (label, _keywords) in category_map.items():
        if _normalize_label_key(label) in normalized_labels or _normalize_label_key(key) in normalized_labels:
            return key, label

    haystack = f"{title} {summary} {' '.join(labels)}".casefold()
    best_key = ""
    best_label = ""
    best_score = -1
    for key, (label, keywords) in category_map.items():
        score = sum(1 for keyword in keywords if keyword.casefold() in haystack)
        if score > best_score:
            best_key = key
            best_label = label
            best_score = score

    if best_key and best_label:
        return best_key, best_label

    first_key, (first_label, _keywords) = next(iter(category_map.items()))
    return first_key, first_label


def canonicalize_editorial_labels(
    *,
    profile_key: str,
    editorial_category_key: str | None,
    editorial_category_label: str | None,
    labels: list[str] | None,
    title: str,
    summary: str,
) -> tuple[str | None, str | None, list[str]]:
    category_map = _editorial_category_map(profile_key)
    cleaned_labels = _dedupe_labels(labels)
    key = (editorial_category_key or "").strip().lower() or None
    label = (editorial_category_label or "").strip() or None

    if category_map and (not key or not label):
        inferred_key, inferred_label = infer_editorial_category(
            profile_key=profile_key,
            labels=cleaned_labels,
            title=title,
            summary=summary,
        )
        key = key or inferred_key or None
        label = label or inferred_label or None

    if label:
        without_label = [item for item in cleaned_labels if _normalize_label_key(item) != _normalize_label_key(label)]
        cleaned_labels = [label, *without_label]

    return key, label, cleaned_labels[:8]


def resolve_article_editorial_labels(article: Article) -> tuple[str | None, str | None, list[str]]:
    profile_key = ""
    if getattr(article, "blog", None) is not None and getattr(article.blog, "profile_key", None):
        profile_key = str(article.blog.profile_key)
    return canonicalize_editorial_labels(
        profile_key=profile_key,
        editorial_category_key=article.editorial_category_key,
        editorial_category_label=article.editorial_category_label,
        labels=list(article.labels or []),
        title=article.title,
        summary=article.excerpt,
    )


def ensure_article_editorial_labels(db: Session, article: Article, *, commit: bool = True) -> list[str]:
    resolved_key, resolved_label, resolved_labels = resolve_article_editorial_labels(article)
    changed = (
        (article.editorial_category_key or "") != (resolved_key or "")
        or (article.editorial_category_label or "") != (resolved_label or "")
        or list(article.labels or []) != resolved_labels
    )
    article.editorial_category_key = resolved_key
    article.editorial_category_label = resolved_label
    article.labels = resolved_labels
    if changed:
        db.add(article)
        if commit:
            db.commit()
            db.refresh(article)
        else:
            db.flush()
    return list(article.labels or [])


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
    profile_key = ""
    if getattr(job, "blog", None) is not None and getattr(job.blog, "profile_key", None):
        profile_key = str(job.blog.profile_key)
    elif topic is not None and getattr(topic, "blog", None) is not None and getattr(topic.blog, "profile_key", None):
        profile_key = str(topic.blog.profile_key)
    resolved_editorial_key, resolved_editorial_label, resolved_labels = canonicalize_editorial_labels(
        profile_key=profile_key,
        editorial_category_key=(topic.editorial_category_key if topic else None),
        editorial_category_label=(topic.editorial_category_label if topic else None),
        labels=list(output.labels or []),
        title=output.title,
        summary=output.excerpt,
    )
    payload = {
        "blog_id": job.blog_id,
        "topic_id": topic.id if topic else None,
        "title": output.title,
        "meta_description": output.meta_description,
        "labels": resolved_labels,
        "slug": slug_candidate,
        "excerpt": output.excerpt,
        "html_article": sanitized_html,
        "faq_section": [item.model_dump() for item in output.faq_section],
        "image_collage_prompt": output.image_collage_prompt,
        "editorial_category_key": resolved_editorial_key,
        "editorial_category_label": resolved_editorial_label,
        "reading_time_minutes": estimate_reading_time(sanitized_html),
    }
    if article:
        for key, value in payload.items():
            setattr(article, key, value)
    else:
        article = Article(job_id=job.id, **payload)
        db.add(article)
    db.flush()
    planner_slot = db.execute(select(ContentPlanSlot).where(ContentPlanSlot.job_id == job.id)).scalar_one_or_none()
    if planner_slot is not None:
        planner_slot.article_id = article.id
        db.add(planner_slot)
    db.commit()
    db.refresh(article)
    from app.services.analytics_service import upsert_article_fact

    upsert_article_fact(db, article.id)
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
        "Create one hero-cover collage with exactly 9 distinct panels in a clear 3x3 grid, visible white gutters, "
        "a visually dominant center panel, realistic photography, no text overlay, and no logos."
    )
