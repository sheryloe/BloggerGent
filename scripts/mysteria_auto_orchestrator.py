
import os
import sys
import logging
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import select, func
from sqlalchemy.orm import Session

# Setup path for imports
BASE_DIR = r"d:\Donggri_Platform\BloggerGent\apps\api"
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

os.environ["SETTINGS_ENCRYPTION_SECRET"] = "cloudflare-bootstrap-20260418"
os.environ["DATABASE_URL"] = "postgresql+psycopg2://bloggent:bloggent@localhost:15432/bloggent"

from app.db.session import SessionLocal
from app.models.entities import Blog, ManagedChannel, PostStatus, PublishMode, WorkflowStageType, Article, Image
from app.services.cloudflare.cloudflare_channel_service import (
    list_cloudflare_categories,
    _prepare_markdown_body,
    _integration_request,
    _integration_data_or_raise,
    _fix_cloudflare_meta_description
)
from app.services.platform.publishing_service import perform_publish_now, rebuild_article_html
from app.services.content.article_three_pass_service import (
    generate_mystery_four_part_article, 
    generate_mystery_topic_suggestion
)
from app.services.providers.factory import get_article_provider, get_image_provider
from app.services.integrations.telegram_service import send_telegram_post_notification
from app.services.ops.job_service import create_job, set_status, JobStatus
from app.services.integrations.storage_service import upload_binary_to_cloudflare_r2
from app.services.content.article_service import build_article_r2_asset_object_key

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mysteria_orchestrator")

def simple_html_to_markdown(html: str) -> str:
    """Very basic HTML to Markdown converter for Cloudflare compatibility."""
    import re
    # Headings (Downgrade H1 to H2, and others accordingly or keep at H2)
    text = re.sub(r'<(h[1-6])\b[^>]*>(.*?)</\1>', lambda m: f"\n\n{'#' * (int(m.group(1)[1]) + 1 if int(m.group(1)[1]) == 1 else int(m.group(1)[1]))} {m.group(2).strip()}\n\n", html, flags=re.I)
    # Paragraphs
    text = re.sub(r'<p\b[^>]*>(.*?)</p>', r'\n\n\1\n\n', text, flags=re.I)
    # List items
    text = re.sub(r'<li\b[^>]*>(.*?)</li>', r'\n* \1', text, flags=re.I)
    # Bold/Italic
    text = re.sub(r'<(strong|b)\b[^>]*>(.*?)</\1>', r'**\2**', text, flags=re.I)
    text = re.sub(r'<(em|i)\b[^>]*>(.*?)</\1>', r'*\2*', text, flags=re.I)
    # Strip remaining tags
    text = re.sub(r'<[^>]+>', '', text)
    # Normalize spacing
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def generate_unique_topic(db: Session, blog_id: int):
    """Generates a topic and checks for duplicates in the DB. Loops until unique."""
    while True:
        logger.info("Generating a new mystery topic...")
        topic_suggestion = generate_mystery_topic_suggestion(db, blog_id)
        
        # Check if topic already exists (case-insensitive title check)
        existing = db.execute(
            select(Article).where(
                Article.blog_id == blog_id,
                func.lower(Article.title) == topic_suggestion["title"].lower()
            )
        ).scalar_one_or_none()
        
        if not existing:
            logger.info(f"Topic accepted: {topic_suggestion['title']}")
            return topic_suggestion
        
        logger.info(f"Topic '{topic_suggestion['title']}' is a duplicate. Regenerating...")


def run_mysteria_pipeline_core(db: Session, manual_topic: str = None):
    # 1. Target Blogs
    blogger_blog = db.get(Blog, 35) # The Midnight Archives (en)
    cloudflare_channel = db.execute(
        select(ManagedChannel).where(ManagedChannel.channel_id == "cloudflare:dongriarchive")
    ).scalar_one_or_none()
    
    if not blogger_blog or not cloudflare_channel:
        logger.error("Required blogs/channels not found")
        return

    # 2. Topic Selection
    if manual_topic:
        logger.info(f"Using manual topic: {manual_topic}")
        keyword = manual_topic
    else:
        topic_data = generate_unique_topic(db, blogger_blog.id)
        keyword = topic_data["title"]
    
    # 3. Content & Image Generation with Internal Retries
    mystery_patterns = [
        "Declassified File: Focus on redacted documents, timestamped logs, and official bureaucratic tone.",
        "Urban Legend Investigation: Focus on eyewitness accounts, blurry photos, and local folklore.",
        "Scientific Journal: Focus on data analysis, anomalous properties, and laboratory observations.",
        "Survivor's Testimony: Focus on the emotional trauma, inconsistent memories, and the 'human' side of the mystery.",
        "Historical Archive: Focus on ancient manuscripts, dusty records, and connections to historical events."
    ]
    selected_pattern = random.choice(mystery_patterns)
    logger.info(f"Selected Pattern: {selected_pattern}")

    article_provider = get_article_provider(db)
    image_provider = get_image_provider(db)
    
    en_job = create_job(db, blog_id=blogger_blog.id, keyword=keyword, publish_mode=PublishMode.PUBLISH)
    
    # -- Generation Block (Retries only here) --
    en_output = None
    ko_output = None
    image_bytes = None
    
    max_gen_retries = 3
    for attempt in range(max_gen_retries):
        try:
            logger.info(f"Generation Attempt {attempt+1}/{max_gen_retries}")
            
            # English Generation
            if not en_output:
                logger.info(f"Generating English content: {keyword}")
                en_output, _ = generate_mystery_four_part_article(
                    base_prompt=f"Subject: {keyword}\nPattern: {selected_pattern}\nStyle: Documentary, Investigative Archive",
                    language="en",
                    generate_planner=lambda p: article_provider.generate_structured_json(p),
                    generate_pass=lambda p: article_provider.generate_article(keyword, p)
                )

            # Korean Generation
            if not ko_output:
                logger.info(f"Generating Korean content: {keyword}")
                ko_output, _ = generate_mystery_four_part_article(
                    base_prompt=(
                        f"주제: {keyword}\n"
                        f"패턴: {selected_pattern}\n"
                        f"스타일: 전문 다큐멘터리, 수사 기록물 아카이브\n"
                        "반드시 모든 출력(제목, 본문, 메타 설명 등)은 한국어로만 작성하세요.\n"
                        "핵심 요구사항:\n"
                        "1. 분량: 본문은 최소 3,500자 이상의 매우 상세하고 깊이 있는 내용을 담아야 합니다.\n"
                        "2. 구조: 제공된 4개 섹션(Setup, Records & Timeline, Evidence & Interpretation, Current Status & Open Questions)에 맞춰 전문적인 어조로 작성하세요.\n"
                        "3. 상호작용 요소: 본문 중간에 반드시 해당 사건의 핵심 장소와 관련된 Google Maps iframe 임베드 코드를 포함하세요.\n"
                        "4. 가이드 형태: 단순한 사실 나열이 아니라, 독자를 미스터리 속으로 안내하는 상세한 가이드 형태여야 합니다."
                    ),
                    language="ko",
                    generate_planner=lambda p: article_provider.generate_structured_json(p),
                    generate_pass=lambda p: article_provider.generate_article(keyword, p)
                )

            # Image Generation
            if not image_bytes:
                logger.info("Generating hero image")
                img_prompt = en_output.image_collage_prompt or f"Documentary style archive photo of {keyword}, mystery, evidence"
                image_bytes, _ = image_provider.generate_image(img_prompt, en_output.slug)
            
            break # Success
        except Exception as e:
            logger.warning(f"Generation error on attempt {attempt+1}: {e}")
            if attempt == max_gen_retries - 1:
                set_status(db, en_job, JobStatus.FAILED, f"Generation failed after {max_gen_retries} attempts: {e}")
                raise
            time.sleep(5)

    # 4. Prepare Database Entities
    image_prompt = en_output.image_collage_prompt or f"Documentary style archive photo of {keyword}, mystery, evidence"
    en_article = Article(
        job_id=en_job.id,
        blog_id=blogger_blog.id,
        title=en_output.title,
        slug=en_output.slug,
        excerpt=en_output.meta_description,
        meta_description=en_output.meta_description,
        html_article=en_output.html_article,
        assembled_html=en_output.html_article,
        labels=en_output.labels,
        image_collage_prompt=image_prompt
    )
    db.add(en_article)
    db.commit()
    db.refresh(en_article)

    # Save image locally
    local_storage_dir = Path(r"D:\Donggri_Runtime\BloggerGent\storage\images\mystery")
    local_storage_dir.mkdir(parents=True, exist_ok=True)
    local_file_path = local_storage_dir / f"{en_article.slug}.webp"
    with open(local_file_path, "wb") as f:
        f.write(image_bytes)
    
    # Save image to R2
    object_key = build_article_r2_asset_object_key(en_article, asset_role="hero")
    public_url, upload_payload, delivery_meta = upload_binary_to_cloudflare_r2(
        db, object_key=object_key, filename=f"{en_article.slug}.webp", content=image_bytes
    )
    
    hero_image = Image(
        article_id=en_article.id,
        job_id=en_job.id,
        public_url=public_url,
        file_path=str(local_file_path),
        prompt=image_prompt,
        image_metadata={"delivery": delivery_meta, "upload": upload_payload}
    )
    db.add(hero_image)
    db.commit()
    
    rebuild_article_html(db, en_article, public_url)
    db.refresh(en_article)

    # 5. FINAL STEP: PUBLISHING (No retries for the whole block)
    logger.info("Starting Final Publishing Steps")
    
    # Blogger
    if not en_article.blogger_post:
        logger.info("Publishing to Blogger...")
        perform_publish_now(db, article=en_article)
        db.refresh(en_article)
        send_telegram_post_notification(
            db, blog_name=blogger_blog.name, article_title=en_article.title,
            post_url=en_article.blogger_post.published_url, post_status="published"
        )
    
    # Cloudflare
    categories = list_cloudflare_categories(db)
    mysteria_cat = next((c for c in categories if c['id'] == 'cat-world-mysteria-story'), None)
    if mysteria_cat:
        logger.info("Publishing to Cloudflare...")
        ko_md = simple_html_to_markdown(ko_output.html_article)
        ko_body = _prepare_markdown_body(ko_output.title, ko_md)
        fixed_meta = _fix_cloudflare_meta_description(ko_output.meta_description)
        
        create_payload = {
            "title": ko_output.title, "content": ko_body, "excerpt": fixed_meta,
            "seoTitle": ko_output.title, "seoDescription": fixed_meta, "tagNames": ko_output.labels,
            "status": "published", "coverImage": public_url, "coverAlt": ko_output.title
        }
        
        # 2-step Cloudflare publishing
        temp_payload = create_payload.copy()
        temp_payload["status"] = "draft"
        temp_payload["categorySlug"] = mysteria_cat['slug']
        
        post_response = _integration_request(db, method="POST", path="/api/integrations/posts", json_payload=temp_payload, timeout=120.0)
        post_data = _integration_data_or_raise(post_response)
        new_post_id = post_data.get("id")
        
        final_payload = create_payload.copy()
        final_payload["categoryId"] = mysteria_cat['id']
        cf_put_response = _integration_request(db, method="PUT", path=f"/api/integrations/posts/{new_post_id}", json_payload=final_payload, timeout=120.0)
        cf_res = _integration_data_or_raise(cf_put_response)
        
        send_telegram_post_notification(
            db, blog_name="Mysteria Story", article_title=ko_output.title,
            post_url=cf_res.get("publicUrl") or cf_res.get("url", ""), post_status="published"
        )

    set_status(db, en_job, JobStatus.COMPLETED, "Full Mysteria pipeline completed successfully")
    logger.info("Pipeline completed successfully")

def run_mysteria_pipeline(manual_topic=None):
    db = SessionLocal()
    try:
        run_mysteria_pipeline_core(db, manual_topic=manual_topic)
    except Exception as e:
        logger.exception(f"Pipeline failed: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword", default=None, help="Specific topic to write about")
    args = parser.parse_args()
    
    run_mysteria_pipeline(manual_topic=args.keyword)
