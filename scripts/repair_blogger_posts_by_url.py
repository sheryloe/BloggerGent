from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select

from scripts.package_common import (
    REPORT_ROOT,
    SessionLocal,
    blogger_url_key,
    now_iso,
    write_json,
)

from app.models.entities import Article, Blog, BloggerPost, Image, Job, JobStatus, PublishMode, WorkflowStageType
from app.services.platform.blog_service import ensure_blog_workflow_steps, get_workflow_step, render_agent_prompt
from app.services.blogger.blogger_sync_service import fetch_all_live_blogger_posts
from app.services.providers.factory import get_article_provider, get_blogger_provider, get_image_provider
from app.services.platform.publishing_service import rebuild_article_html, refresh_article_public_image, upsert_article_blogger_post
from app.services.integrations.settings_service import get_settings_map
from app.services.integrations.storage_service import save_public_binary
from app.services.content.wikimedia_service import fetch_wikimedia_media


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Repair Blogger posts by URL: rebuild HTML for managed posts and regenerate missing posts."
    )
    parser.add_argument("--url", action="append", required=True, help="Target Blogger post URL. Repeat for multiple.")
    parser.add_argument("--apply", action="store_true", help="Apply updates to Blogger and DB.")
    return parser.parse_args()


def _url_host(value: str) -> str:
    parsed = urlparse(value)
    return (parsed.netloc or "").strip().lower()


def _find_blog_for_url(db, url: str) -> Blog | None:
    host = _url_host(url)
    if not host:
        return None
    blogs = db.query(Blog).filter(Blog.blogger_url.isnot(None)).all()
    for blog in blogs:
        if _url_host(blog.blogger_url or "") == host:
            return blog
    return None


def _find_blogger_post_by_url(db, blog_id: int, url: str) -> BloggerPost | None:
    target_key = blogger_url_key(url)
    posts = db.query(BloggerPost).filter(BloggerPost.blog_id == blog_id).all()
    for post in posts:
        if blogger_url_key(post.published_url or "") == target_key:
            return post
    return None


def _find_remote_post_by_url(db, blog: Blog, url: str) -> dict | None:
    if not (blog.blogger_blog_id or "").strip():
        return None
    target_key = blogger_url_key(url)
    for item in fetch_all_live_blogger_posts(db, blog.blogger_blog_id or ""):
        if blogger_url_key(item.get("url") or "") == target_key:
            return item
    return None


def _append_blogger_seo_trust_guard(prompt: str, *, blog, current_date: str) -> str:
    profile_key = str(getattr(blog, "profile_key", "") or "").strip().lower()
    if profile_key not in {"korea_travel", "world_mystery"}:
        return prompt

    common_rules = [
        "[SEO trust + source integrity guard]",
        f'- Include one explicit absolute-date timestamp line: "As of {current_date}".',
        "- Add one dedicated section that separates confirmed facts from unverified details.",
        "- Add one dedicated section for source/verification path with 2-5 concrete source channels.",
        '- If no verifiable source URL exists, explicitly say "No verified source URL yet".',
        "- Never present assumptions, rumors, or secondary reposts as confirmed facts.",
        "- Avoid clickbait superlatives unless directly supported by verifiable evidence.",
    ]
    if profile_key == "world_mystery":
        common_rules.append("- For SCP or fiction-universe topics, clearly label fiction context near the top.")
    if profile_key == "korea_travel":
        common_rules.append("- For schedule, price, entry, and transport details, use recheck wording when uncertain.")

    return f"{prompt}\n\n" + "\n".join(common_rules) + "\n"


def _append_no_inline_image_rule(prompt: str) -> str:
    return (
        f"{prompt}\n\n"
        "[Inline image policy]\n"
        "- Do not output inline image tags or markdown image syntax in article body.\n"
        "- Never include <img>, <figure>, ![...](...) or collage marker text in body content.\n"
        "- If the output schema includes inline_collage_prompt, use that separate field for one mid-article supporting collage.\n"
        "- Keep raw image markup out of body content because the system inserts visuals after generation.\n"
    )


def _upsert_image(
    db,
    *,
    job_id: int,
    article_id: int,
    prompt: str,
    file_path: str,
    public_url: str,
    provider: str,
    meta: dict,
) -> Image:
    image = db.execute(select(Image).where(Image.job_id == job_id)).scalar_one_or_none()
    payload = {
        "article_id": article_id,
        "prompt": prompt,
        "file_path": file_path,
        "public_url": public_url,
        "width": int(meta.get("width", 1536)),
        "height": int(meta.get("height", 1024)),
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


def _create_job(db, *, blog: Blog, keyword: str) -> Job:
    job = Job(
        blog_id=blog.id,
        keyword_snapshot=keyword,
        status=JobStatus.GENERATING_ARTICLE,
        publish_mode=PublishMode.PUBLISH,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _generate_article_output(db, *, blog: Blog, keyword: str):
    ensure_blog_workflow_steps(db, blog)
    step = get_workflow_step(blog, WorkflowStageType.ARTICLE_GENERATION)
    if step is None:
        raise RuntimeError("Article generation step is missing.")

    rendered = render_agent_prompt(
        blog,
        step,
        keyword=keyword,
        editorial_category_key="",
        editorial_category_label="",
        editorial_category_guidance="",
    )
    rendered = _append_blogger_seo_trust_guard(
        rendered,
        blog=blog,
        current_date=datetime.now(timezone.utc).date().isoformat(),
    )
    rendered = _append_no_inline_image_rule(rendered)
    provider = get_article_provider(db, model_override=step.provider_model, allow_large=True)
    output, _raw = provider.generate_article(keyword, rendered)
    return output, rendered


def _store_generated_image(
    db,
    *,
    job_id: int,
    article_id: int,
    prompt: str,
    slug: str,
    provider_name: str,
):
    image_provider = get_image_provider(db)
    image_bytes, image_raw = image_provider.generate_image(prompt, slug)
    file_path, public_url, delivery_meta = save_public_binary(
        db,
        subdir="images",
        filename=f"{slug}.png",
        content=image_bytes,
    )
    image = _upsert_image(
        db,
        job_id=job_id,
        article_id=article_id,
        prompt=prompt,
        file_path=file_path,
        public_url=public_url,
        provider=provider_name,
        meta={**image_raw, "delivery": delivery_meta},
    )
    return image, public_url


def _resolve_hero_url_for_article(db, article: Article, *, keyword: str, is_mystery: bool) -> str:
    hero_url = ""
    try:
        hero_url = refresh_article_public_image(db, article) or (article.image.public_url if article.image else "")
    except FileNotFoundError:
        hero_url = article.image.public_url if article.image else ""
    if hero_url:
        return hero_url

    if is_mystery:
        settings_map = get_settings_map(db)
        count = int(settings_map.get("wikimedia_image_count", 3) or 3)
        media_items = fetch_wikimedia_media(keyword, count=count)
        if media_items:
            hero_url = str(media_items[0].get("image_url") or media_items[0].get("thumb_url") or "")
            if hero_url:
                return hero_url

    _image, public_url = _store_generated_image(
        db,
        job_id=article.job_id,
        article_id=article.id,
        prompt=article.image_collage_prompt or f"Documentary hero image for {keyword}.",
        slug=article.slug,
        provider_name="openai_image",
    )
    return public_url


def _rebuild_and_update_existing(db, *, article: Article, blog: Blog, apply: bool) -> dict[str, Any]:
    print(f"rebuild_existing article_id={article.id} apply={apply}", flush=True)
    is_mystery = (blog.profile_key or "").strip().lower() == "world_mystery"
    hero_url = _resolve_hero_url_for_article(db, article, keyword=article.title, is_mystery=is_mystery)
    assembled_html = rebuild_article_html(db, article, hero_url)
    if not apply:
        return {"status": "dry_run_rebuilt", "hero_url": hero_url, "assembled_len": len(assembled_html)}

    provider = get_blogger_provider(db, blog)
    if not hasattr(provider, "update_post") or type(provider).__name__.startswith("Mock"):
        return {"status": "skip:update_unavailable", "hero_url": hero_url, "assembled_len": len(assembled_html)}

    summary, raw_payload = provider.update_post(
        post_id=article.blogger_post.blogger_post_id,
        title=article.title,
        content=assembled_html,
        labels=list(article.labels or []),
        meta_description=article.meta_description or "",
    )
    upsert_article_blogger_post(
        db,
        article=article,
        summary=summary,
        raw_payload=raw_payload if isinstance(raw_payload, dict) else {},
    )
    return {"status": "updated", "hero_url": hero_url, "assembled_len": len(assembled_html)}


def _regenerate_and_update_remote(
    db,
    *,
    blog: Blog,
    remote_post: dict,
    apply: bool,
) -> dict[str, Any]:
    keyword = remote_post.get("title") or remote_post.get("url") or "untitled"
    print(f"regenerate_missing keyword={keyword} apply={apply}", flush=True)
    job = _create_job(db, blog=blog, keyword=keyword)
    output, _prompt = _generate_article_output(db, blog=blog, keyword=keyword)

    from app.services.content.article_service import save_article

    article = save_article(db, job=job, topic=None, output=output)
    is_mystery = (blog.profile_key or "").strip().lower() == "world_mystery"
    hero_url = _resolve_hero_url_for_article(db, article, keyword=keyword, is_mystery=is_mystery)
    assembled_html = rebuild_article_html(db, article, hero_url)

    if not apply:
        return {
            "status": "dry_run_regenerated",
            "keyword": keyword,
            "hero_url": hero_url,
            "assembled_len": len(assembled_html),
        }

    provider = get_blogger_provider(db, blog)
    if not hasattr(provider, "update_post") or type(provider).__name__.startswith("Mock"):
        return {
            "status": "skip:update_unavailable",
            "keyword": keyword,
            "hero_url": hero_url,
            "assembled_len": len(assembled_html),
        }

    summary, raw_payload = provider.update_post(
        post_id=remote_post.get("remote_post_id"),
        title=article.title,
        content=assembled_html,
        labels=list(article.labels or []),
        meta_description=article.meta_description or "",
    )
    upsert_article_blogger_post(
        db,
        article=article,
        summary=summary,
        raw_payload=raw_payload if isinstance(raw_payload, dict) else {},
    )
    return {
        "status": "updated",
        "keyword": keyword,
        "hero_url": hero_url,
        "assembled_len": len(assembled_html),
    }


def main() -> int:
    args = parse_args()
    results: list[dict[str, Any]] = []
    with SessionLocal() as db:
        for url in args.url:
            print(f"processing_url={url}", flush=True)
            row: dict[str, Any] = {"url": url, "applied": bool(args.apply)}
            blog = _find_blog_for_url(db, url)
            if not blog:
                row["status"] = "skip:no_blog_match"
                results.append(row)
                continue

            row["blog_id"] = blog.id
            row["blog_slug"] = blog.slug
            row["profile_key"] = blog.profile_key

            post = _find_blogger_post_by_url(db, blog.id, url)
            if post and post.article:
                row["article_id"] = post.article.id
                row["mode"] = "rebuild_existing"
                row.update(_rebuild_and_update_existing(db, article=post.article, blog=blog, apply=args.apply))
                results.append(row)
                continue

            remote_post = _find_remote_post_by_url(db, blog, url)
            if not remote_post:
                row["status"] = "skip:no_remote_post"
                results.append(row)
                continue

            row["mode"] = "regenerate_missing"
            row["remote_post_id"] = remote_post.get("remote_post_id")
            row.update(_regenerate_and_update_remote(db, blog=blog, remote_post=remote_post, apply=args.apply))
            results.append(row)

    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    report_path = REPORT_ROOT / f"blogger-repair-by-url-{stamp}.json"
    write_json(report_path, {"generated_at": now_iso(), "results": results})
    print(f"report={report_path}", flush=True)
    for row in results:
        print(row, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
