from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@localhost:15432/bloggent"
MYSTERY_BLOG_ID = 35
MYSTERY_PROFILE_KEY = "world_mystery"
MYSTERY_CATEGORY_KEY = "case-files"
MYSTERY_CATEGORY_LABEL = "Case Files"
LIVE_STATUSES = {"LIVE", "PUBLISHED", "live", "published"}

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get("BLOGGENT_DATABASE_URL", DEFAULT_DATABASE_URL)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Article, Blog, BloggerPost, Image, Job, JobStatus, PostStatus, PublishMode, SyncedBloggerPost, Topic, WorkflowStageType  # noqa: E402
from app.schemas.ai import ArticleGenerationOutput, FAQItem  # noqa: E402
from app.services.blogger.blogger_sync_service import sync_blogger_posts_for_blog  # noqa: E402
from app.services.content.article_service import build_article_r2_asset_object_key, ensure_article_editorial_labels, save_article  # noqa: E402
from app.services.content.html_assembler import assemble_article_html  # noqa: E402
from app.services.content.manual_image_service import build_slot_metadata, create_manual_image_slot, format_manual_image_slot_for_chat  # noqa: E402
from app.services.content.manual_image_service import resolve_manual_image_defer_for_blog  # noqa: E402
from app.services.content.publish_trust_gate_service import enforce_publish_trust_requirements, ensure_trust_gate_appendix  # noqa: E402
from app.services.content.related_posts import find_related_articles  # noqa: E402
from app.services.content.topic_guard_service import rebuild_topic_memories_for_blog, validate_candidate_topic  # noqa: E402
from app.services.integrations.settings_service import get_settings_map  # noqa: E402
from app.services.integrations.storage_service import save_html, save_public_binary  # noqa: E402
from app.services.ops.usage_service import record_image_generation_usage, record_mock_usage  # noqa: E402
from app.services.platform.publishing_service import upsert_article_blogger_post  # noqa: E402
from app.services.providers.base import ProviderRuntimeError  # noqa: E402
from app.services.providers.factory import get_blogger_provider, get_image_provider, get_runtime_config  # noqa: E402
from app.services.providers.openai import OpenAIImageProvider  # noqa: E402


DETAILS_RE = re.compile(
    r"<details\b[^>]*>\s*<summary\b[^>]*>(?P<q>.*?)</summary>\s*<p\b[^>]*>(?P<a>.*?)</p>\s*</details>",
    re.IGNORECASE | re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")
OPEN_H1_RE = re.compile(r"<h1(\s[^>]*)?>", re.IGNORECASE)
CLOSE_H1_RE = re.compile(r"</h1\s*>", re.IGNORECASE)
MOJIBAKE_REPLACEMENTS = {
    "?셲": "'s",
    "\ufffd": "",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish one generated mystery draft to Blogger.")
    parser.add_argument("--blog-id", type=int, required=True)
    parser.add_argument("--draft-path", required=True)
    parser.add_argument("--publish-live", action="store_true")
    parser.add_argument("--defer-images", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args()


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _clean_text(value: Any) -> str:
    text = _safe_str(value)
    for source, replacement in MOJIBAKE_REPLACEMENTS.items():
        text = text.replace(source, replacement)
    return text


def _clean_nested(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean_nested(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean_nested(item) for item in value]
    if isinstance(value, str):
        return _clean_text(value)
    return value


def _plain_text(html_value: str) -> str:
    return re.sub(r"\s+", " ", unescape(TAG_RE.sub(" ", html_value))).strip()


def _extract_faq_and_strip_details(html_article: str) -> tuple[str, list[FAQItem]]:
    faq_items: list[FAQItem] = []

    def replacer(match: re.Match[str]) -> str:
        question = _plain_text(match.group("q"))
        answer = _plain_text(match.group("a"))
        if question and answer:
            faq_items.append(FAQItem(question=question, answer=answer))
        return ""

    cleaned = DETAILS_RE.sub(replacer, html_article)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, faq_items[:6]


def _demote_body_h1(html_value: str) -> str:
    return CLOSE_H1_RE.sub("</h2>", OPEN_H1_RE.sub(lambda match: f"<h2{match.group(1) or ''}>", html_value))


def _require_mystery_blog(db, blog_id: int) -> Blog:
    if int(blog_id) != MYSTERY_BLOG_ID:
        raise RuntimeError(f"refusing_non_mystery_blog:{blog_id}")
    blog = (
        db.execute(
            select(Blog)
            .where(Blog.id == blog_id)
            .options(selectinload(Blog.articles), selectinload(Blog.blogger_posts))
        )
        .scalars()
        .one_or_none()
    )
    if blog is None:
        raise RuntimeError(f"blog_not_found:{blog_id}")
    if _safe_str(blog.profile_key) != MYSTERY_PROFILE_KEY:
        raise RuntimeError(f"profile_key_mismatch:{blog.profile_key}")
    if not _safe_str(blog.blogger_blog_id):
        raise RuntimeError("blogger_blog_id_missing")
    return blog


def _duplicate_gate(db, *, blog_id: int, title: str, slug: str) -> dict[str, Any]:
    normalized_title = _clean_text(title).lower()
    normalized_slug = _clean_text(slug).lower()
    slug_terms = [
        term
        for term in re.split(r"[^a-z0-9]+", normalized_slug)
        if len(term) >= 4 and term not in {"case", "file", "files", "mystery", "incident", "archive", "archives"}
    ][:4]
    title_terms = [
        term
        for term in re.split(r"[^a-z0-9]+", normalized_title)
        if len(term) >= 4 and term not in {"case", "file", "files", "mystery", "incident", "archive", "archives"}
    ][:4]
    candidate_terms = list(dict.fromkeys(slug_terms + title_terms))[:6]
    fuzzy_conditions = []
    if normalized_title:
        fuzzy_conditions.append(func.lower(Article.title) == normalized_title)
    if normalized_slug:
        fuzzy_conditions.append(func.lower(Article.slug) == normalized_slug)
    if not fuzzy_conditions:
        fuzzy_conditions = [Article.slug == slug]

    articles = (
        db.execute(
            select(Article.id, Article.title, Article.slug)
            .where(
                Article.blog_id == blog_id,
                or_(*fuzzy_conditions),
            )
            .order_by(Article.id.asc())
        )
        .all()
    )
    live_conditions = []
    if normalized_title:
        live_conditions.append(func.lower(SyncedBloggerPost.title) == normalized_title)
    if normalized_slug:
        live_conditions.append(func.lower(SyncedBloggerPost.url).like(f"%{normalized_slug}%"))
    if not live_conditions:
        live_conditions = [func.lower(SyncedBloggerPost.url).like(f"%{normalized_slug}%")]
    synced = (
        db.execute(
            select(SyncedBloggerPost.id, SyncedBloggerPost.title, SyncedBloggerPost.url)
            .where(
                SyncedBloggerPost.blog_id == blog_id,
                SyncedBloggerPost.status.in_(sorted(LIVE_STATUSES)),
                or_(*live_conditions),
            )
            .order_by(SyncedBloggerPost.id.asc())
        )
        .all()
    )
    matching_articles = [dict(row._mapping) for row in articles]
    matching_synced = [dict(row._mapping) for row in synced]
    return {
        "status": "pass" if not matching_articles and not matching_synced else "blocked",
        "matching_articles": matching_articles,
        "matching_live_posts": matching_synced,
        "candidate": {
            "title": title,
            "slug": slug,
            "dedupe_terms": candidate_terms,
        },
    }


def _load_draft(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _clean_nested(payload)


def _draft_to_output(draft: dict[str, Any]) -> ArticleGenerationOutput:
    article = dict(draft.get("article") or {})
    html_article = _clean_text(article.get("html_article"))
    html_article, faq_items = _extract_faq_and_strip_details(html_article)
    labels = list(article.get("labels") or [])
    if MYSTERY_CATEGORY_LABEL not in labels:
        labels.insert(0, MYSTERY_CATEGORY_LABEL)
    return ArticleGenerationOutput(
        title=_clean_text(article.get("title")),
        meta_description=_clean_text(article.get("meta_description")),
        labels=[_clean_text(item) for item in labels if _clean_text(item)][:8],
        slug=_clean_text(article.get("slug")),
        excerpt=_clean_text(article.get("excerpt")),
        html_article=html_article,
        faq_section=faq_items,
        image_collage_prompt=_clean_text(article.get("image_collage_prompt")),
    )


def _upsert_topic(db, *, blog_id: int, draft: dict[str, Any], descriptor) -> Topic:
    keyword = _clean_text((draft.get("article") or {}).get("keyword")) or _clean_text((draft.get("planner") or {}).get("keyword"))
    keyword = keyword or _clean_text((draft.get("article") or {}).get("title"))
    topic = db.execute(select(Topic).where(Topic.blog_id == blog_id, Topic.keyword == keyword)).scalar_one_or_none()
    payload = {
        "reason": _clean_text((draft.get("planner") or {}).get("distinct_reason")) or _safe_str(getattr(descriptor, "distinct_reason", "")),
        "trend_score": 0.0,
        "source": "codex_generated_draft",
        "locale": "en-US",
        "topic_cluster_label": _safe_str(getattr(descriptor, "topic_cluster_label", "")),
        "topic_angle_label": _safe_str(getattr(descriptor, "topic_angle_label", "")),
        "editorial_category_key": MYSTERY_CATEGORY_KEY,
        "editorial_category_label": MYSTERY_CATEGORY_LABEL,
        "distinct_reason": _safe_str(getattr(descriptor, "distinct_reason", "")),
    }
    if topic:
        for key, value in payload.items():
            setattr(topic, key, value)
    else:
        topic = Topic(blog_id=blog_id, keyword=keyword, **payload)
        db.add(topic)
    db.commit()
    db.refresh(topic)
    return topic


def _create_job(db, *, blog_id: int, topic: Topic, draft: dict[str, Any], publish_live: bool, defer_images: bool) -> Job:
    keyword = _clean_text((draft.get("article") or {}).get("keyword")) or topic.keyword
    job = Job(
        blog_id=blog_id,
        topic_id=topic.id,
        keyword_snapshot=keyword,
        status=JobStatus.GENERATING_IMAGE,
        publish_mode=PublishMode.PUBLISH if publish_live else PublishMode.DRAFT,
        start_time=datetime.now(timezone.utc),
        raw_prompts={
            "source": "publish_mystery_generated_draft",
            "draft_path": _safe_str(draft.get("_draft_path")),
            "pipeline_control": {
                "stop_after": None,
                "defer_images": bool(defer_images),
            },
        },
        raw_responses={
            "generated_draft": draft,
        },
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _upsert_image(
    db,
    *,
    job_id: int,
    article_id: int,
    prompt: str,
    file_path: str,
    public_url: str,
    provider: str,
    meta: dict[str, Any],
) -> Image:
    image = db.execute(select(Image).where(Image.job_id == job_id)).scalar_one_or_none()
    payload = {
        "article_id": article_id,
        "prompt": prompt,
        "file_path": file_path,
        "public_url": public_url,
        "width": int(meta.get("width") or 1024),
        "height": int(meta.get("height") or 1024),
        "provider": provider,
        "image_metadata": meta,
    }
    if image:
        for key, value in payload.items():
            setattr(image, key, value)
    else:
        image = Image(job_id=job_id, **payload)
        db.add(image)
    db.commit()
    db.refresh(image)
    return image


def _create_manual_slot_for_article(
    db,
    *,
    blog: Blog,
    job: Job,
    article: Article,
    post: BloggerPost | None,
) -> dict[str, Any] | None:
    if article.image:
        return None
    if post is None:
        post = (
            db.execute(
                select(BloggerPost)
                .where(BloggerPost.article_id == article.id)
                .order_by(BloggerPost.id.desc())
            )
            .scalars()
            .first()
        )
    if post is None:
        raise RuntimeError(f"blogger_post_missing_for_manual_image_slot:{article.id}")
    prompt = _safe_str(article.image_collage_prompt)
    if not prompt:
        raise RuntimeError(f"image_collage_prompt_missing:{article.id}")

    remote_post_id = _safe_str(post.blogger_post_id)
    slot = create_manual_image_slot(
        db,
        provider="blogger",
        slot_role="hero",
        prompt=prompt,
        blog=blog,
        job=job,
        article=article,
        blogger_post=post,
        remote_post_id=remote_post_id,
        batch_key=f"blogger:{blog.id}:{job.id}",
        metadata=build_slot_metadata(
            title=article.title,
            published_url=post.published_url,
            slug=article.slug,
            remote_post_id=remote_post_id,
            extra={
                "source": "publish_mystery_generated_draft",
                "language": blog.primary_language or "en",
                "blog_slug": blog.slug,
            },
        ),
    )
    return {
        "serial_code": slot.serial_code,
        "slot": slot.slot_role,
        "prompt": slot.prompt,
        "chat": format_manual_image_slot_for_chat(slot),
    }


def _publish_article(db, *, article: Article, publish_live: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    labels = ensure_article_editorial_labels(db, article)
    related_posts = find_related_articles(db, article)
    hero_image_url = article.image.public_url if article.image else ""
    assembled_html = assemble_article_html(article, hero_image_url, related_posts)
    assembled_html = _demote_body_h1(assembled_html)
    assembled_html, _ = ensure_trust_gate_appendix(assembled_html)
    enforce_publish_trust_requirements(assembled_html, context=f"publish_mystery_generated_draft_{article.id}")
    article.assembled_html = assembled_html
    db.add(article)
    db.commit()
    db.refresh(article)
    save_html(slug=article.slug, html=assembled_html)

    provider = get_blogger_provider(db, article.blog)
    publish_mode = PublishMode.PUBLISH if publish_live else PublishMode.DRAFT
    summary, raw_payload = provider.publish(
        title=article.title,
        content=assembled_html,
        labels=labels,
        meta_description=article.meta_description,
        slug=article.slug,
        publish_mode=publish_mode,
    )
    post = upsert_article_blogger_post(db, article=article, summary=summary, raw_payload=raw_payload)
    if article.job:
        article.job.status = JobStatus.COMPLETED
        article.job.end_time = datetime.now(timezone.utc)
        db.add(article.job)
        db.commit()
    rebuild_topic_memories_for_blog(db, article.blog)
    record_mock_usage(
        db,
        blog_id=article.blog_id,
        job_id=article.job_id,
        article_id=article.id,
        stage_type=WorkflowStageType.PUBLISHING.value,
        provider_name="blogger" if _safe_str(summary.get("url")).startswith(("http://", "https://")) else "mock_blogger",
        provider_model="blogger-v3",
        endpoint="blogger:publish",
        raw_usage=raw_payload if isinstance(raw_payload, dict) else {},
    )
    return {
        **summary,
        "local_blogger_post_id": post.id,
        "post_status": post.post_status.value,
    }, raw_payload


def _probe_url(url: str, *, timeout: float) -> dict[str, Any]:
    if not url:
        return {"ok": False, "status_code": 0, "content_type": "", "url": url}
    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True)
        return {
            "ok": response.status_code < 400,
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "url": url,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status_code": 0, "content_type": "", "url": url, "error": str(exc)}


def run(args: argparse.Namespace) -> dict[str, Any]:
    draft_path = Path(args.draft_path)
    draft = _load_draft(draft_path)
    draft["_draft_path"] = str(draft_path)
    output = _draft_to_output(draft)

    with SessionLocal() as db:
        blog = _require_mystery_blog(db, int(args.blog_id))
        settings_map = get_settings_map(db)
        if _safe_str(settings_map.get("provider_mode")) != "live":
            raise RuntimeError(f"provider_mode_not_live:{settings_map.get('provider_mode')}")
        defer_images = resolve_manual_image_defer_for_blog(
            blog_id=blog.id,
            requested_defer_images=bool(args.defer_images),
            settings_map=settings_map,
        )

        existing_article = db.execute(
            select(Article)
            .where(Article.blog_id == blog.id, Article.slug == output.slug)
            .options(
                selectinload(Article.image),
                selectinload(Article.blogger_post),
                selectinload(Article.blog),
                selectinload(Article.job),
                selectinload(Article.topic),
            )
        ).scalar_one_or_none()
        if existing_article and existing_article.blogger_post and existing_article.blogger_post.post_status in {
            PostStatus.PUBLISHED,
            PostStatus.SCHEDULED,
        }:
            manual_slot = None
            if defer_images:
                manual_slot = _create_manual_slot_for_article(
                    db,
                    blog=blog,
                    job=existing_article.job,
                    article=existing_article,
                    post=existing_article.blogger_post,
                )
            return {
                "status": "already_published",
                "article_id": existing_article.id,
                "published_url": existing_article.blogger_post.published_url,
                "image_url": existing_article.image.public_url if existing_article.image else "",
                "manual_image_deferred": bool(defer_images and not existing_article.image),
                "manual_image_slots": [manual_slot] if manual_slot else [],
                "manual_image_prompt_chat": manual_slot["chat"] if manual_slot else "",
            }
        if existing_article:
            article = existing_article
            job = article.job
            topic = article.topic
            if job is None:
                raise RuntimeError(f"existing_article_missing_job:{article.id}")
            if topic is None:
                raise RuntimeError(f"existing_article_missing_topic:{article.id}")
            duplicate_gate = {
                "status": "pass",
                "resumed_existing_unpublished_article_id": article.id,
                "matching_articles": [],
                "matching_live_posts": [],
            }
            descriptor = validate_candidate_topic(
                db,
                blog_id=blog.id,
                title=article.title,
                excerpt=article.excerpt,
                labels=list(article.labels or []),
                content_html=article.html_article,
            )
        else:
            duplicate_gate = _duplicate_gate(db, blog_id=blog.id, title=output.title, slug=output.slug)
            if duplicate_gate["status"] != "pass":
                raise RuntimeError(json.dumps({"duplicate_gate": duplicate_gate}, ensure_ascii=False))

            descriptor = validate_candidate_topic(
                db,
                blog_id=blog.id,
                title=output.title,
                excerpt=output.excerpt,
                labels=output.labels,
                content_html=output.html_article,
            )
            topic = _upsert_topic(db, blog_id=blog.id, draft=draft, descriptor=descriptor)
            job = _create_job(
                db,
                blog_id=blog.id,
                topic=topic,
                draft=draft,
                publish_live=bool(args.publish_live),
                defer_images=defer_images,
            )
            article = save_article(db, job=job, topic=topic, output=output)
            db.refresh(article, attribute_names=["blog", "job", "topic", "image"])

        image = article.image
        delivery_meta: dict[str, Any] = {}
        if image:
            image = article.image
            public_url = image.public_url
            object_key = _safe_str((image.image_metadata or {}).get("object_key"))
            file_path = image.file_path
            delivery_meta = dict((image.image_metadata or {}).get("delivery") or {})
        elif defer_images:
            public_url = ""
            object_key = ""
            file_path = ""
        else:
            try:
                image_provider = get_image_provider(db)
            except ProviderRuntimeError as exc:
                runtime = get_runtime_config(db)
                if runtime.provider_mode != "live" or not runtime.openai_api_key:
                    raise
                image_provider = OpenAIImageProvider(api_key=runtime.openai_api_key, model=runtime.openai_image_model)
                print(
                    json.dumps(
                        {
                            "warning": "openai_usage_guard_unavailable_single_image_direct_provider_used",
                            "detail": exc.detail or exc.message,
                        },
                        ensure_ascii=False,
                    )
                )
            image_bytes, image_raw = image_provider.generate_image(
                article.image_collage_prompt,
                article.slug,
                size_override="1024x1024",
            )
            object_key = build_article_r2_asset_object_key(article, asset_role="hero", content=image_bytes)
            if "/hero-" in object_key or "/hero-refresh-" in object_key or "/cover-" in object_key or "/inline-" in object_key:
                raise RuntimeError(f"forbidden_object_key:{object_key}")
            file_path, public_url, delivery_meta = save_public_binary(
                db,
                subdir="images/mystery",
                filename=f"{article.slug}.webp",
                content=image_bytes,
                object_key=object_key,
            )
            image_meta = {**dict(image_raw or {}), "delivery": delivery_meta, "object_key": object_key}
            image = _upsert_image(
                db,
                job_id=job.id,
                article_id=article.id,
                prompt=article.image_collage_prompt,
                file_path=file_path,
                public_url=public_url,
                provider=image_provider.__class__.__name__.replace("Provider", "").lower(),
                meta=image_meta,
            )
            record_image_generation_usage(
                db,
                blog_id=blog.id,
                job_id=job.id,
                article_id=article.id,
                stage_type=WorkflowStageType.IMAGE_GENERATION.value,
                provider_name=image.provider,
                provider_model=_safe_str(image_meta.get("actual_model") or image_meta.get("requested_model")),
                endpoint="openai:images.generate",
                raw_response=image_meta,
            )

        db.refresh(article, attribute_names=["image", "blog", "job", "topic"])
        if public_url:
            image_probe = _probe_url(public_url, timeout=float(args.timeout))
            if not image_probe["ok"] or "image/webp" not in _safe_str(image_probe.get("content_type")).lower():
                raise RuntimeError(json.dumps({"image_probe_failed": image_probe}, ensure_ascii=False))
        else:
            image_probe = {
                "ok": True,
                "skipped": True,
                "reason": "manual_image_deferred",
                "url": "",
            }

        publish_summary, _ = _publish_article(db, article=article, publish_live=bool(args.publish_live))
        synced_result = sync_blogger_posts_for_blog(db, blog) if args.publish_live else {}
        post_url = _safe_str(publish_summary.get("url"))
        post_probe = _probe_url(post_url, timeout=float(args.timeout)) if post_url else {}

        db.refresh(article, attribute_names=["image", "blogger_post", "job"])
        manual_slot = None
        if defer_images and not article.image:
            manual_slot = _create_manual_slot_for_article(
                db,
                blog=blog,
                job=job,
                article=article,
                post=article.blogger_post,
            )
        return {
            "status": "published" if args.publish_live else "draft_created",
            "blog_id": blog.id,
            "article_id": article.id,
            "job_id": job.id,
            "topic_id": topic.id,
            "image_id": image.id if image else None,
            "title": article.title,
            "slug": article.slug,
            "published_url": post_url,
            "post_status": _safe_str(publish_summary.get("postStatus") or publish_summary.get("post_status")),
            "image_url": public_url,
            "object_key": object_key,
            "local_webp_path": file_path,
            "local_png_path": _safe_str(delivery_meta.get("local_png_path")),
            "manual_image_deferred": bool(defer_images and not article.image),
            "manual_image_slots": [manual_slot] if manual_slot else [],
            "manual_image_prompt_chat": manual_slot["chat"] if manual_slot else "",
            "duplicate_gate": duplicate_gate,
            "topic_descriptor": {
                "topic_cluster_label": _safe_str(getattr(descriptor, "topic_cluster_label", "")),
                "topic_angle_label": _safe_str(getattr(descriptor, "topic_angle_label", "")),
            },
            "image_probe": image_probe,
            "post_probe": post_probe,
            "sync_result": synced_result,
            "usage_from_draft": draft.get("usage") or {},
        }


def main() -> None:
    args = parse_args()
    result = run(args)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
