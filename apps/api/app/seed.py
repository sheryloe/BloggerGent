from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.entities import Article, BloggerPost, Image, Job, JobStatus, PublishMode, Topic
from app.services.article_service import save_article
from app.services.blog_service import disable_legacy_demo_blogs_for_live, ensure_all_blog_workflows, ensure_default_blogs, get_blog_by_slug
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
            reason="대시보드 시연을 위한 샘플 주제",
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

    set_status(db, job, JobStatus.GENERATING_ARTICLE, "시드 데이터를 위한 본문을 생성하고 있습니다.")
    article_output, _ = article_provider.generate_article(keyword, blog.content_brief or "")
    article = save_article(db, job=job, topic=topic, output=article_output)

    set_status(db, job, JobStatus.GENERATING_IMAGE_PROMPT, "시드 데이터를 위한 대표 이미지 프롬프트를 만들고 있습니다.")
    article.image_collage_prompt = article_output.image_collage_prompt
    db.add(article)
    db.commit()
    db.refresh(article)

    set_status(db, job, JobStatus.GENERATING_IMAGE, "시드 데이터를 위한 대표 이미지를 생성하고 있습니다.")
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

    set_status(db, job, JobStatus.FINDING_RELATED_POSTS, "시드 데이터를 위한 관련 글을 찾고 있습니다.")
    db.refresh(article, attribute_names=["blog"])
    related = find_related_articles(db, article)
    set_status(db, job, JobStatus.ASSEMBLING_HTML, "시드 데이터를 위한 HTML을 조립하고 있습니다.")
    article.assembled_html = assemble_article_html(article, public_url, related)
    db.add(article)
    db.commit()
    save_html(slug=article.slug, html=article.assembled_html)

    set_status(db, job, JobStatus.PUBLISHING, "시드 데이터를 위한 Blogger 게시를 시뮬레이션하고 있습니다.")
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
        response_payload=raw,
    )
    db.add(post)
    set_status(db, job, JobStatus.COMPLETED, "시드 데이터 작업이 완료되었습니다.")
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
            reason="실패 시나리오 확인용 시드 주제",
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
    job.error_logs = [{"message": "대표 이미지 생성 단계에서 mock 공급자 오류가 발생했습니다.", "attempt": 1}]
    db.add(job)
    db.commit()


def seed_demo_data() -> None:
    db = SessionLocal()
    try:
        ensure_default_settings(db)
        settings_map = get_settings_map(db)
        enable_demo = settings_map.get("provider_mode", settings.provider_mode).lower() != "live"
        ensure_default_blogs(db, enable_demo=enable_demo)
        if not enable_demo:
            disable_legacy_demo_blogs_for_live(db)
        ensure_all_blog_workflows(db)
        if not settings.seed_demo_data:
            return
        if not enable_demo:
            return

        travel_blog = get_blog_by_slug(db, "korea-travel-and-events")
        mystery_blog = get_blog_by_slug(db, "world-mystery-documentary")
        if travel_blog and not db.execute(select(Job.id).where(Job.blog_id == travel_blog.id)).first():
            _seed_completed_post(
                db,
                blog_slug=travel_blog.slug,
                keyword="Best hanok cafes in Seoul",
                publish_mode=PublishMode.DRAFT,
                offset_days=1,
            )
            _seed_completed_post(
                db,
                blog_slug=travel_blog.slug,
                keyword="Korean night markets for foreigners",
                publish_mode=PublishMode.PUBLISH,
                offset_days=0,
            )
            _seed_failed_job(db, blog_slug=travel_blog.slug, keyword="Jeju spring itinerary for foreigners")

        if mystery_blog and not db.execute(select(Job.id).where(Job.blog_id == mystery_blog.id)).first():
            _seed_completed_post(
                db,
                blog_slug=mystery_blog.slug,
                keyword="The Mary Celeste unsolved mystery",
                publish_mode=PublishMode.DRAFT,
                offset_days=0,
            )
    finally:
        db.close()


if __name__ == "__main__":
    seed_demo_data()
