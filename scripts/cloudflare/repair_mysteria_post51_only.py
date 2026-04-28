from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.package_common import (  # noqa: E402
    CloudflareIntegrationClient,
    SessionLocal,
    now_iso,
    read_text_utf8,
    safe_filename,
    write_json,
)


POST_ID = "90d08755-cb7e-4e99-95a7-9b9360e7bdc7"
TARGET_SLUG = "mystery-archive-51-the-hinterkaifeck-farm-murders"
TARGET_TITLE = "힌터카이펙 참극: 1922년 독일 농가 미제 살인 사건"
TARGET_CATEGORY_ID = "cat-world-mysteria-story"
TARGET_CATEGORY_SLUG = "미스테리아-스토리"
SOURCE_PATH = REPO_ROOT / "scratch" / "art51_v4.txt"
REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\cloudflare\reports")

PUBLIC_POST_URL = f"https://dongriarchive.com/ko/post/{TARGET_SLUG}"
PUBLIC_POST_API_URL = f"https://api.dongriarchive.com/api/public/posts/{TARGET_SLUG}"
PUBLIC_CATEGORY_API_URL = "https://api.dongriarchive.com/api/public/categories/%EB%AF%B8%EC%8A%A4%ED%85%8C%EB%A6%AC%EC%95%84-%EC%8A%A4%ED%86%A0%EB%A6%AC/posts"

ARTICLE_OPEN_RE = re.compile(r"^\s*<article\b[^>]*>\s*", re.IGNORECASE | re.DOTALL)
ARTICLE_CLOSE_RE = re.compile(r"\s*</article>\s*$", re.IGNORECASE | re.DOTALL)
SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
STYLE_RE = re.compile(r"<style\b[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL)
H1_RE = re.compile(r"<h1\b[^>]*>.*?</h1>", re.IGNORECASE | re.DOTALL)
BANNER_RE = re.compile(r"<p\b[^>]*>\s*THE\s+MYSTERIA\s+ARCHIVE\s*</p>", re.IGNORECASE)
IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")
MULTISPACE_RE = re.compile(r"\s+")
MD_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
MD_LIST_RE = re.compile(r"^\s*[-*+]\s+(.+)$", re.MULTILINE)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def unwrap_article(html_text: str) -> str:
    text = _safe_text(html_text)
    text = ARTICLE_OPEN_RE.sub("", text, count=1)
    text = ARTICLE_CLOSE_RE.sub("", text, count=1)
    return text.strip()


def _extract_documentary_body(html_text: str) -> str:
    for tag in ("div", "section"):
        match = re.search(
            rf"<{tag}\b[^>]*class=['\"][^'\"]*documentary-body[^'\"]*['\"][^>]*>(.*?)</{tag}>",
            html_text,
            re.IGNORECASE | re.DOTALL,
        )
        if match:
            return _safe_text(match.group(1))
    return html_text


def _markdown_to_html(html_text: str) -> str:
    text = _safe_text(html_text)
    text = re.sub(r"(?m)^\s*---+\s*$", "", text)
    text = re.sub(r"(?m)^\s*___+\s*$", "", text)
    text = re.sub(r"(?m)^\s*\*\*\*+\s*$", "", text)
    text = re.sub(r"(?m)^\s*```+\s*$", "", text)

    def _heading_repl(match: re.Match[str]) -> str:
        level = min(max(len(match.group(1)) + 1, 2), 6)
        heading = _safe_text(match.group(2))
        return f"<h{level}>{heading}</h{level}>"

    text = MD_HEADING_RE.sub(_heading_repl, text)
    text = MD_BOLD_RE.sub(r"<strong>\1</strong>", text)

    # 간단한 markdown 리스트를 ul/li로 변환
    lines = text.splitlines()
    out: list[str] = []
    in_list = False
    for line in lines:
        item_match = MD_LIST_RE.match(line)
        if item_match:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{item_match.group(1).strip()}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        out.append(line)
    if in_list:
        out.append("</ul>")
    return "\n".join(out).strip()


def sanitize_body(html_text: str) -> str:
    text = _safe_text(html_text)
    text = unwrap_article(text)
    text = _extract_documentary_body(text)
    text = SCRIPT_RE.sub("", text)
    text = STYLE_RE.sub("", text)
    text = re.sub(r"<figure\b[^>]*>.*?</figure>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = BANNER_RE.sub("", text)
    text = H1_RE.sub("", text)
    text = IMG_RE.sub("", text)  # 본문 인라인 이미지는 전부 제거(메인 1장 규칙)
    text = _markdown_to_html(text)
    text = text.replace("***", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def plain_text(html_text: str) -> str:
    text = TAG_RE.sub(" ", _safe_text(html_text))
    text = MULTISPACE_RE.sub(" ", text)
    return text.strip()


def build_excerpt(body_text: str) -> str:
    text = _safe_text(body_text)
    if len(text) <= 150:
        return text
    return f"{text[:150].rstrip()}..."


def build_seo_description(body_text: str) -> str:
    text = _safe_text(body_text)
    if len(text) <= 280:
        return text
    return f"{text[:280].rstrip()}..."


def build_content(*, title: str, cover_image: str, body_html: str) -> str:
    escaped_title = html.escape(title, quote=True)
    escaped_cover = html.escape(cover_image, quote=True)
    body = _safe_text(body_html)
    return (
        "<article class='mysteria-record-v1' style='max-width:840px;margin:0 auto;"
        "font-family:\"Pretendard\",sans-serif;color:#111827;line-height:1.85;'>"
        "<figure style='margin:0 0 28px;'>"
        f"<img src=\"{escaped_cover}\" alt=\"{escaped_title}\" loading='eager' decoding='async' "
        "style='width:100%;display:block;border-radius:18px;object-fit:cover;'/>"
        "</figure>"
        "<section class='documentary-body' style='font-size:17px;line-height:1.95;color:#111827;'>"
        f"{body}"
        "</section>"
        "</article>"
    )


def fetch_public_post() -> dict[str, Any]:
    response = httpx.get(PUBLIC_POST_API_URL, timeout=30.0, follow_redirects=True)
    payload: Any = {}
    try:
        payload = response.json()
    except ValueError:
        payload = {}

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return {
            "url": PUBLIC_POST_API_URL,
            "status_code": response.status_code,
            "found": False,
            "message": payload.get("message") if isinstance(payload, dict) else "",
        }

    content = _safe_text(data.get("content"))
    cover_image = _safe_text(data.get("coverImage"))
    img_urls = re.findall(r"<img\b[^>]*\bsrc=['\"]([^'\"]+)['\"]", content, re.IGNORECASE)
    return {
        "url": PUBLIC_POST_API_URL,
        "status_code": response.status_code,
        "found": True,
        "id": _safe_text(data.get("id")),
        "slug": _safe_text(data.get("slug")),
        "title": _safe_text(data.get("title")),
        "category_slug": _safe_text((data.get("category") or {}).get("slug") if isinstance(data.get("category"), dict) else ""),
        "content_len": len(content),
        "contains_archive_banner": "THE MYSTERIA ARCHIVE" in content,
        "h1_count": len(re.findall(r"<h1\b", content, re.IGNORECASE)),
        "img_count": len(img_urls),
        "img_urls": img_urls,
        "coverImage": cover_image,
        "one_image_matches_cover": len(img_urls) == 1 and cover_image and img_urls[0] == cover_image,
        "has_markdown_bold": bool(re.search(r"\*\*.+?\*\*", content)),
        "has_markdown_heading": bool(re.search(r"^\s*#{1,6}\s+", content, re.MULTILINE)),
    }


def fetch_public_page() -> dict[str, Any]:
    cache_bust = int(time.time())
    url = f"{PUBLIC_POST_URL}?cb={cache_bust}"
    response = httpx.get(url, timeout=30.0, follow_redirects=True)
    text = response.text
    return {
        "url": url,
        "status_code": response.status_code,
        "content_len": len(text),
        "contains_archive_banner": "THE MYSTERIA ARCHIVE" in text,
        "contains_slug": TARGET_SLUG in text,
    }


def fetch_public_category_api() -> dict[str, Any]:
    response = httpx.get(PUBLIC_CATEGORY_API_URL, timeout=30.0, follow_redirects=True)
    payload: Any = {}
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    data = payload.get("data") if isinstance(payload, dict) else {}
    posts = data.get("posts") if isinstance(data, dict) else []
    contains = False
    if isinstance(posts, list):
        contains = any(_safe_text(item.get("slug")) == TARGET_SLUG for item in posts if isinstance(item, dict))
    return {
        "url": PUBLIC_CATEGORY_API_URL,
        "status_code": response.status_code,
        "posts_count": len(posts) if isinstance(posts, list) else None,
        "contains_post51": contains,
    }


def trigger_build(client: CloudflareIntegrationClient) -> dict[str, Any]:
    response = httpx.post(
        f"{client.base_url}/api/integrations/builds",
        headers={
            "Authorization": f"Bearer {client.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=120.0,
    )
    payload: Any
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text}
    if not response.is_success:
        raise ValueError(f"Build trigger failed ({response.status_code}): {payload}")
    return {"status_code": response.status_code, "payload": payload}


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair Mysteria post 51 to pure HTML + one hero image.")
    parser.add_argument("--execute", action="store_true", help="Apply PUT update.")
    parser.add_argument("--trigger-build", action="store_true", help="Trigger integration build after execute.")
    parser.add_argument("--token", default=os.environ.get("DONGRI_M2M_TOKEN", "").strip(), help="Fallback API token.")
    parser.add_argument(
        "--api-base-url",
        default=os.environ.get("CLOUDFLARE_BLOG_API_BASE_URL", "https://api.dongriarchive.com").strip(),
        help="Fallback API base URL.",
    )
    args = parser.parse_args()

    started_at = now_iso()
    source_raw = read_text_utf8(SOURCE_PATH)
    body_html = sanitize_body(source_raw)
    body_text = plain_text(body_html)
    excerpt = build_excerpt(body_text)
    seo_description = build_seo_description(body_text)

    with SessionLocal() as db:
        try:
            client = CloudflareIntegrationClient.from_db(db)
        except Exception:
            client = CloudflareIntegrationClient(base_url=args.api_base_url, token=args.token)

        before = client.get_post(POST_ID)
        if not before:
            raise ValueError(f"Target post not found: {POST_ID}")

        cover_image = _safe_text(before.get("coverImage"))
        if not cover_image:
            raise ValueError("coverImage is empty on target post 51.")

        final_content = build_content(title=TARGET_TITLE, cover_image=cover_image, body_html=body_html)
        payload = {
            "title": TARGET_TITLE,
            "slug": TARGET_SLUG,
            "content": final_content,
            "coverImage": cover_image,
            "categoryId": TARGET_CATEGORY_ID,
            "status": "published",
            "excerpt": excerpt,
            "seoDescription": seo_description,
            "metaDescription": seo_description,
        }

        report: dict[str, Any] = {
            "started_at": started_at,
            "mode": "execute" if args.execute else "dry-run",
            "post_id": POST_ID,
            "source_path": str(SOURCE_PATH),
            "target": {
                "slug": TARGET_SLUG,
                "title": TARGET_TITLE,
                "categoryId": TARGET_CATEGORY_ID,
                "categorySlug": TARGET_CATEGORY_SLUG,
            },
            "payload_preview": {
                "title": payload["title"],
                "slug": payload["slug"],
                "status": payload["status"],
                "content_len": len(payload["content"]),
                "excerpt_len": len(payload["excerpt"]),
                "seoDescription_len": len(payload["seoDescription"]),
                "coverImage": payload["coverImage"],
            },
            "before": {
                "title": _safe_text(before.get("title")),
                "slug": _safe_text(before.get("slug")),
                "status": _safe_text(before.get("status")),
                "categoryId": _safe_text(before.get("categoryId") or before.get("category_id")),
                "categorySlug": _safe_text(before.get("categorySlug") or before.get("category_slug")),
                "coverImage": _safe_text(before.get("coverImage")),
                "content_len": len(_safe_text(before.get("content"))),
            },
            "source_analysis": {
                "raw_len": len(source_raw),
                "clean_body_len": len(body_html),
                "body_text_len": len(body_text),
                "contains_markdown_heading": bool(re.search(r"^\s*#{1,6}\s+", body_html, re.MULTILINE)),
                "contains_markdown_bold": bool(re.search(r"\*\*.+?\*\*", body_html)),
                "contains_h1": "<h1" in body_html.lower(),
            },
            "public_before": {
                "post_api": fetch_public_post(),
                "post_page": fetch_public_page(),
                "category_api": fetch_public_category_api(),
            },
            "updated": None,
            "build": None,
            "public_after": None,
        }

        if args.execute:
            updated = client.update_post(POST_ID, payload)
            report["updated"] = {
                "title": _safe_text(updated.get("title")),
                "slug": _safe_text(updated.get("slug")),
                "status": _safe_text(updated.get("status")),
                "categoryId": _safe_text(updated.get("categoryId") or updated.get("category_id")),
                "categorySlug": _safe_text(updated.get("categorySlug") or updated.get("category_slug")),
                "coverImage": _safe_text(updated.get("coverImage")),
                "content_len": len(_safe_text(updated.get("content"))),
            }
            if args.trigger_build:
                try:
                    report["build"] = trigger_build(client)
                    time.sleep(8)
                except Exception as exc:  # noqa: BLE001
                    report["build"] = {"error": str(exc)}

            report["public_after"] = {
                "post_api": fetch_public_post(),
                "post_page": fetch_public_page(),
                "category_api": fetch_public_category_api(),
            }

    report_name = f"{utc_stamp()}-{safe_filename(TARGET_SLUG)}-repair-post51.json"
    report_path = REPORT_ROOT / report_name
    write_json(report_path, report)
    print(json.dumps({"report_path": str(report_path), "mode": report["mode"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
