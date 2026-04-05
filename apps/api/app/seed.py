from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.entities import Article, BloggerPost, Image, Job, JobStatus, PostStatus, PublishMode, Topic
from app.services.article_service import save_article
from app.services.blog_service import ensure_all_blog_workflows, ensure_default_blogs, get_blog_by_slug, purge_legacy_demo_blogs
from app.services.html_assembler import assemble_article_html
from app.services.job_service import create_job, set_status
from app.services.providers.mock import MockArticleProvider, MockBloggerProvider, MockImageProvider
from app.services.related_posts import find_related_articles
from app.services.settings_service import ensure_default_settings, get_settings_map
from app.services.storage_service import save_html, save_public_binary


def _seed_completed_post(db, *, blog_slug: str, keyword: str, publish_mode: PublishMode, offset_days: int) -> None:
    blog = get_blog_by_slug(db, blog_slug)
    if not blog:
        return

    topic = db.execute(select(Topic).where(Topic.blog_id == blog.id, Topic.keyword == keyword)).scalar_one_or_none()
    if not topic:
        topic = Topic(
            blog_id=blog.id,
            keyword=keyword,
            reason="??쒕낫???쒖뿰???꾪븳 ?섑뵆 二쇱젣",
            trend_score=80.0,
            source="seed",
            locale=blog.primary_language,
        )
        db.add(topic)
        db.commit()
        db.refresh(topic)

    job = create_job(db, blog_id=blog.id, keyword=keyword, topic_id=topic.id, publish_mode=publish_mode)
    article_provider = MockArticleProvider()
    image_provider = MockImageProvider()
    blogger_provider = MockBloggerProvider()

    set_status(db, job, JobStatus.GENERATING_ARTICLE, "?쒕뱶 ?곗씠?곕? ?꾪븳 蹂몃Ц???앹꽦?섍퀬 ?덉뒿?덈떎.")
    article_output, _ = article_provider.generate_article(keyword, blog.content_brief or "")
    article = save_article(db, job=job, topic=topic, output=article_output)

    set_status(db, job, JobStatus.GENERATING_IMAGE_PROMPT, "?쒕뱶 ?곗씠?곕? ?꾪븳 ????대?吏 ?꾨＼?꾪듃瑜?留뚮뱾怨??덉뒿?덈떎.")
    article.image_collage_prompt = article_output.image_collage_prompt
    db.add(article)
    db.commit()
    db.refresh(article)

    set_status(db, job, JobStatus.GENERATING_IMAGE, "?쒕뱶 ?곗씠?곕? ?꾪븳 ????대?吏瑜??앹꽦?섍퀬 ?덉뒿?덈떎.")
    image_bytes, image_meta = image_provider.generate_image(article.image_collage_prompt, article.slug)
    file_path, public_url, delivery_meta = save_public_binary(
        db,
        subdir="images",
        filename=f"{article.slug}.png",
        content=image_bytes,
    )
    image = Image(
        job_id=job.id,
        article_id=article.id,
        prompt=article.image_collage_prompt,
        file_path=file_path,
        public_url=public_url,
        width=image_meta["width"],
        height=image_meta["height"],
        provider="mock",
        image_metadata={**image_meta, "delivery": delivery_meta},
    )
    db.add(image)
    db.commit()

    set_status(db, job, JobStatus.FINDING_RELATED_POSTS, "?쒕뱶 ?곗씠?곕? ?꾪븳 愿??湲??李얘퀬 ?덉뒿?덈떎.")
    db.refresh(article, attribute_names=["blog"])
    related = find_related_articles(db, article)
    set_status(db, job, JobStatus.ASSEMBLING_HTML, "?쒕뱶 ?곗씠?곕? ?꾪븳 HTML??議곕┰?섍퀬 ?덉뒿?덈떎.")
    article.assembled_html = assemble_article_html(article, public_url, related)
    db.add(article)
    db.commit()
    save_html(slug=article.slug, html=article.assembled_html)

    set_status(db, job, JobStatus.PUBLISHING, "?쒕뱶 ?곗씠?곕? ?꾪븳 Blogger 寃뚯떆瑜??쒕??덉씠?섑븯怨??덉뒿?덈떎.")
    summary, raw = blogger_provider.publish(
        title=article.title,
        content=article.assembled_html,
        labels=article.labels,
        meta_description=article.meta_description,
        slug=article.slug,
        publish_mode=publish_mode,
    )
    post = BloggerPost(
        job_id=job.id,
        blog_id=blog.id,
        article_id=article.id,
        blogger_post_id=summary["id"],
        published_url=summary["url"],
        published_at=datetime.now(timezone.utc) - timedelta(days=offset_days),
        is_draft=summary["isDraft"],
        post_status=PostStatus.DRAFT if summary["isDraft"] else PostStatus.PUBLISHED,
        scheduled_for=None,
        response_payload=raw,
    )
    db.add(post)
    set_status(db, job, JobStatus.COMPLETED, "?쒕뱶 ?곗씠???묒뾽???꾨즺?섏뿀?듬땲??")
    job.start_time = datetime.now(timezone.utc) - timedelta(days=offset_days, minutes=7)
    job.end_time = datetime.now(timezone.utc) - timedelta(days=offset_days, minutes=1)
    db.add(job)
    db.commit()


def _seed_failed_job(db, *, blog_slug: str, keyword: str) -> None:
    blog = get_blog_by_slug(db, blog_slug)
    if not blog:
        return

    topic = db.execute(select(Topic).where(Topic.blog_id == blog.id, Topic.keyword == keyword)).scalar_one_or_none()
    if not topic:
        topic = Topic(
            blog_id=blog.id,
            keyword=keyword,
            reason="?ㅽ뙣 ?쒕굹由ъ삤 ?뺤씤???쒕뱶 二쇱젣",
            trend_score=52.0,
            source="seed",
            locale=blog.primary_language,
        )
        db.add(topic)
        db.commit()
        db.refresh(topic)

    job = create_job(db, blog_id=blog.id, keyword=keyword, topic_id=topic.id, publish_mode=PublishMode.DRAFT)
    job.status = JobStatus.FAILED
    job.start_time = datetime.now(timezone.utc) - timedelta(hours=2)
    job.end_time = job.start_time + timedelta(minutes=4)
    job.error_logs = [{"message": "????대?吏 ?앹꽦 ?④퀎?먯꽌 mock 怨듦툒???ㅻ쪟媛 諛쒖깮?덉뒿?덈떎.", "attempt": 1}]
    db.add(job)
    db.commit()


def seed_demo_data() -> None:
    db = SessionLocal()
    try:
        ensure_default_settings(db)
        ensure_default_blogs(db, enable_demo=False)
        purge_legacy_demo_blogs(db)
        ensure_all_blog_workflows(db)
        return
    finally:
        db.close()


if __name__ == "__main__":
    seed_demo_data()

