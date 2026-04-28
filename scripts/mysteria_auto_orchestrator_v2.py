
import os
import sys
import logging
import random
import time
from datetime import datetime
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
    _integration_request,
    _integration_data_or_raise,
    _fix_cloudflare_meta_description,
    _list_integration_posts
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
logger = logging.getLogger("mysteria_orchestrator_v2")

def get_already_covered_topics(db: Session, blog_id: int):
    """Fetches titles of recently covered topics from local DB and Cloudflare."""
    # 1. From local DB
    articles = db.execute(
        select(Article.title).where(Article.blog_id == blog_id).order_by(Article.created_at.desc()).limit(50)
    ).scalars().all()
    
    # 2. From Cloudflare
    cf_posts = _list_integration_posts(db)
    cf_titles = [p["title"] for p in cf_posts if isinstance(p, dict) and "title" in p]
    
    # Combine and deduplicate
    combined = list(set(articles + cf_titles))
    return combined

def generate_unique_topic_v2(db: Session, blog_id: int):
    """Generates a topic and checks for duplicates using semantic awareness."""
    covered = get_already_covered_topics(db, blog_id)
    covered_str = "\n".join([f"- {t}" for t in covered[-20:]]) # last 20 for prompt context
    
    article_provider = get_article_provider(db)
    
    while True:
        logger.info("Generating a new unique mystery topic...")
        prompt = f"""
        Generate a unique and compelling mystery topic for a professional documentary-style blog.
        
        CRITICAL: DO NOT cover any of the following topics or their synonyms:
        {covered_str}
        
        The topic must be entirely different from the ones above.
        Return a JSON object with:
        - title: A catchy, investigative title.
        - audience: Target audience description.
        - information_level: Description of depth.
        - editorial_category_key: one of [case-files, mystery-archives, legends-lore]
        - editorial_category_label: the display name for the category.
        """
        
        try:
            suggestion, _ = article_provider.generate_structured_json(prompt)
            title = suggestion["title"]
            
            # Case-insensitive duplicate check
            is_dup = any(title.lower() in t.lower() or t.lower() in title.lower() for t in covered)
            if not is_dup:
                logger.info(f"Topic accepted: {title}")
                return suggestion
            
            logger.info(f"Topic '{title}' is semantically similar to existing topics. Regenerating...")
        except Exception as e:
            logger.error(f"Error generating topic: {e}")
            time.sleep(2)

def run_mysteria_pipeline_v2(db: Session, manual_topic: str = None):
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
        topic_data = generate_unique_topic_v2(db, blogger_blog.id)
        keyword = topic_data["title"]
    
    # 3. Content Generation
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
    
    # English Generation
    logger.info(f"Generating English content: {keyword}")
    en_output, _ = generate_mystery_four_part_article(
        base_prompt=f"Subject: {keyword}\nPattern: {selected_pattern}\nStyle: Documentary, Investigative Archive",
        language="en",
        generate_planner=lambda p: article_provider.generate_structured_json(p),
        generate_pass=lambda p: article_provider.generate_article(keyword, p)
    )

    # Korean Generation (ENHANCED PROMPT)
    logger.info(f"Generating high-quality Korean content: {keyword}")
    ko_output, _ = generate_mystery_four_part_article(
        base_prompt=(
            f"주제: {keyword}\n"
            f"패턴: {selected_pattern}\n"
            f"스타일: 전문 다큐멘터리, 수사 기록물 아카이브\n"
            "핵심 요구사항:\n"
            "1. 구조적 완성도: 최소 6개 이상의 상세 소제목(H2, H3)을 사용하여 글의 깊이를 확보하세요.\n"
            "2. 전문성: 단순한 사실 나열이 아니라, 증거 분석, 타임라인 구성, 가설 검증 등 전문가의 시각을 담으세요.\n"
            "3. 시각적 요소: 본문 중간에 반드시 해당 사건의 핵심 장소와 관련된 Google Maps iframe 임베드 코드를 포함하세요. (style='border:0;' 등 모든 속성 유지)\n"
            "4. 분량: 공백 제외 최소 3,500자 이상의 압도적인 정보를 제공하세요.\n"
            "5. 가이드: 독자가 사건의 현장에 있는 것처럼 느끼게 하는 몰입감 있는 가이드 형태여야 합니다.\n"
            "6. 모든 항목(제목, 본문, 메타 설명)은 한국어로만 작성하세요."
        ),
        language="ko",
        generate_planner=lambda p: article_provider.generate_structured_json(p),
        generate_pass=lambda p: article_provider.generate_article(keyword, p)
    )

    # Image Generation
    logger.info("Generating hero image")
    img_prompt = en_output.image_collage_prompt or f"Documentary style archive photo of {keyword}, mystery, evidence"
    image_bytes, _ = image_provider.generate_image(img_prompt, en_output.slug)
    
    # 4. Save to DB
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
        image_collage_prompt=img_prompt
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
        prompt=img_prompt,
        image_metadata={"delivery": "cloudflare_r2", "url": public_url}
    )
    db.add(hero_image)
    db.commit()
    
    rebuild_article_html(db, en_article, public_url)
    db.refresh(en_article)

    # 5. Publishing
    # Blogger (English)
    logger.info("Publishing to Blogger...")
    perform_publish_now(db, article=en_article)
    
    # Cloudflare (Korean - PURE HTML)
    categories = list_cloudflare_categories(db)
    mysteria_cat = next((c for c in categories if c['id'] == 'cat-world-mysteria-story'), None)
    if mysteria_cat:
        logger.info("Publishing high-quality HTML to Cloudflare...")
        fixed_meta = _fix_cloudflare_meta_description(ko_output.meta_description)
        
        # WE USE contentHtml AND PRESERVE EVERYTHING
        create_payload = {
            "title": ko_output.title,
            "contentHtml": ko_output.html_article, 
            "excerpt": fixed_meta,
            "seoTitle": ko_output.title,
            "seoDescription": fixed_meta,
            "tagNames": ko_output.labels,
            "status": "published",
            "coverImage": public_url,
            "coverAlt": ko_output.title,
            "categoryId": mysteria_cat['id']
        }
        
        # Create as draft first to ensure category binding (as per existing 2-step pattern in core service)
        temp_payload = create_payload.copy()
        temp_payload["status"] = "draft"
        temp_payload["categorySlug"] = mysteria_cat['slug']
        if "categoryId" in temp_payload: del temp_payload["categoryId"]
        
        post_response = _integration_request(db, method="POST", path="/api/integrations/posts", json_payload=temp_payload, timeout=120.0)
        post_data = _integration_data_or_raise(post_response)
        new_post_id = post_data.get("id")
        
        # Final update with full HTML and published status
        final_payload = create_payload.copy()
        final_payload["categoryId"] = mysteria_cat['id']
        if "categorySlug" in final_payload: del final_payload["categorySlug"]
        
        cf_put_response = _integration_request(db, method="PUT", path=f"/api/integrations/posts/{new_post_id}", json_payload=final_payload, timeout=120.0)
        cf_res = _integration_data_or_raise(cf_put_response)
        
        logger.info(f"Cloudflare post successful: {cf_res.get('url')}")
        
        send_telegram_post_notification(
            db, blog_name="Mysteria Story", article_title=ko_output.title,
            post_url=cf_res.get("publicUrl") or cf_res.get("url", ""), post_status="published"
        )

    set_status(db, en_job, JobStatus.COMPLETED, "V2 Pipeline completed with high-quality HTML")
    logger.info("V2 Pipeline completed successfully")

if __name__ == "__main__":
    db = SessionLocal()
    try:
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--keyword", default=None)
        args = parser.parse_args()
        run_mysteria_pipeline_v2(db, manual_topic=args.keyword)
    finally:
        db.close()
