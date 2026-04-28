import os
import sys
import json
import re
import argparse
from datetime import datetime, timezone
from typing import Any

# Set environment variables BEFORE importing local modules
os.environ["SETTINGS_ENCRYPTION_SECRET"] = "cloudflare-bootstrap-20260418"
os.environ["DATABASE_URL"] = "postgresql+psycopg2://bloggent:bloggent@localhost:15432/bloggent"

# Add project root to path
BASE_DIR = r"d:\Donggri_Platform\BloggerGent\apps\api"
sys.path.append(BASE_DIR)

# Import local modules
from scripts.package_common import CloudflareIntegrationClient, SessionLocal
from app.services.content import article_pattern_service
from app.services.platform.codex_cli_queue_service import submit_codex_text_job
from app.services.providers.factory import get_runtime_config

def safe_text(value: Any) -> str:
    return str(value or "").strip()

def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", safe_text(value)).strip()

def strip_tags(value: str) -> str:
    return normalize_space(re.sub(r"<[^>]+>", " ", value or ""))

def korean_char_count(value: str) -> int:
    return len(re.findall(r"[가-힣]", strip_tags(value)))

def generate_repair_prompt(title: str, pattern_id: str) -> str:
    pattern = article_pattern_service.ARTICLE_PATTERNS.get(pattern_id)
    pattern_block = article_pattern_service.build_article_pattern_prompt_block(
        article_pattern_service.ArticlePatternSelection(
            pattern_id=pattern.pattern_id,
            pattern_version=article_pattern_service.ARTICLE_PATTERN_VERSION,
            label=pattern.label,
            summary=pattern.summary,
            html_hint=pattern.html_hint,
            allowed_pattern_ids=(pattern_id,),
            recent_pattern_ids=(),
            selection_note="manual_repair",
        )
    )
    
    return (
        f"주제: {title}\n"
        "아래 주제를 바탕으로 최고 품질의 한국어 미스테리아 분석 글을 작성한다.\n"
        "이 글은 전문 탐정이나 조사관의 보고서 같은 느낌을 주어야 하며, 독자를 몰입시켜야 한다.\n\n"
        "JSON 객체 하나만 반환한다:\n"
        "{\"title\":\"...\",\"body_html\":\"...\",\"meta_description\":\"...\"}\n\n"
        "규칙:\n"
        "- 100% 한국어만 사용 (제목, 본문 모두).\n"
        "- Markdown 형식으로 작성.\n"
        "- H2(##), H3(###) 소제목을 6~8개 사용하여 구조적으로 작성.\n"
        "- 한글 글자수 3,500자 이상 (매우 상세하게 작성).\n"
        "- 자유 HTML 사용 금지 (이미지, 표 등).\n"
        "- FAQ, 관련 링크 섹션 금지.\n"
        "- 마지막은 '마무리 기록' 섹션으로 끝낼 것.\n\n"
        f"{pattern_block}\n"
    )

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--post-id", required=True)
    parser.add_argument("--map-url", help="Google Maps embed URL")
    parser.add_argument("--no-map", action="store_true", help="Skip map injection")
    parser.add_argument("--apply", action="store_true", help="Actually apply the changes")
    args = parser.parse_args()

    with SessionLocal() as db:
        cloudflare = CloudflareIntegrationClient.from_db(db)

    # 1. Fetch current post
    print(f"[*] Fetching post {args.post_id}...")
    post = cloudflare.get_post(args.post_id)
    if not post:
        print("[!] Post not found")
        return 1

    current_title = strip_tags(post.get("title")).split("|")[0].split("(")[0].strip()
    print(f"[*] Target title: {current_title}")

    # 2. Generate new content
    print("[*] Generating new content via Codex...")
    prompt = generate_repair_prompt(current_title, "mystery-theory-analysis")
    
    with SessionLocal() as db:
        runtime = get_runtime_config(db)
        
    try:
        response = submit_codex_text_job(
            runtime=runtime,
            stage_name="repair_generation",
            model="gpt-5.4",
            prompt=prompt,
            response_kind="text",
            inline=True,
            codex_config_overrides={"model_reasoning_effort": "high"},
        )
    except Exception as e:
        print(f"[!] Codex CLI failed: {e}")
        if hasattr(e, "detail"):
            print(f"[!] Detail: {e.detail}")
        return 1
    
    result = safe_text(response.get("content"))
    
    # Try to parse JSON from result
    try:
        json_match = re.search(r"\{.*\}", result, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
        else:
            print("[!] Could not find JSON in Codex response")
            print(result)
            return 1
    except Exception as e:
        print(f"[!] JSON parse error: {e}")
        print(result)
        return 1

    new_title = data.get("title", current_title)
    new_body = data.get("body_html", "")
    new_meta = data.get("meta_description", "")

    # Clean title
    new_title = re.sub(r"\|.*$", "", new_title).strip()
    new_title = re.sub(r"\(.*\)$", "", new_title).strip()
    
    # Strip forbidden style attributes
    new_body = re.sub(r"(?i)\s+style\s*=\s*(['\"]).*?\1", "", new_body)

    # 3. Inject Map
    if args.map_url:
        print("[*] Injecting Google Map...")
        map_html = f'<figure class="article-figure" data-media-block data-align="center"><iframe src="{args.map_url}" width="100%" height="450" allowfullscreen="" loading="lazy" referrerpolicy="no-referrer-when-downgrade"></iframe></figure>'
        new_body = f"{map_html}\n\n{new_body}"

    print(f"[*] New Title: {new_title}")
    print(f"[*] New Length (Chars): {len(new_body)}")
    print(f"[*] Korean Char Count: {korean_char_count(new_body)}")

    # 4. Update
    if args.apply:
        print("[*] Applying update...")
        payload = {
            "title": new_title,
            "content": new_body,
            "contentFormat": "html",
            "excerpt": new_meta,
            "status": "published",
        }
        cloudflare.update_post(args.post_id, payload)
        print("[+] Update successful!")
    else:
        print("[*] Dry run - not applying. Use --apply to save.")

    return 0

if __name__ == "__main__":
    sys.exit(main())
