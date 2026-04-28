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
    safe_filename,
    write_json,
)


TARGET_CATEGORY_ID = "cat-world-mysteria-story"
TARGET_CATEGORY_SLUG = "미스테리아-스토리"
REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\cloudflare\reports")
NUMBER_RE = re.compile(r"^mystery-archive-(\d+)(?:-|$)", re.IGNORECASE)
ARTICLE_OPEN_RE = re.compile(r"^\s*<article\b[^>]*>\s*", re.IGNORECASE | re.DOTALL)
ARTICLE_CLOSE_RE = re.compile(r"\s*</article>\s*$", re.IGNORECASE | re.DOTALL)
SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
STYLE_RE = re.compile(r"<style\b[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL)
H1_RE = re.compile(r"<h1\b[^>]*>.*?</h1>", re.IGNORECASE | re.DOTALL)
BANNER_RE = re.compile(r"<p\b[^>]*>\s*THE\s+MYSTERIA\s+ARCHIVE\s*</p>", re.IGNORECASE)
IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
MD_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
MD_LIST_RE = re.compile(r"^\s*[-*+]\s+(.+)$", re.MULTILINE)
TAG_RE = re.compile(r"<[^>]+>")
MULTISPACE_RE = re.compile(r"\s+")
TITLE_PREFIXES = (
    "미스테리아 스토리 | ",
    "미스테리아 사건 파일 | ",
    "미스테리아 사건 파일: ",
)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _extract_number(slug: str) -> int | None:
    match = NUMBER_RE.match(_safe_text(slug))
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _clean_title(title: str) -> str:
    cleaned = _safe_text(title)
    for prefix in TITLE_PREFIXES:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
    cleaned = re.sub(r"\*\*", "", cleaned).strip()
    return cleaned


def _unwrap_article(text: str) -> str:
    content = _safe_text(text)
    content = ARTICLE_OPEN_RE.sub("", content, count=1)
    content = ARTICLE_CLOSE_RE.sub("", content, count=1)
    return content.strip()


def _extract_documentary_body(text: str) -> str:
    for tag in ("div", "section"):
        match = re.search(
            rf"<{tag}\b[^>]*class=['\"][^'\"]*documentary-body[^'\"]*['\"][^>]*>(.*?)</{tag}>",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if match:
            return _safe_text(match.group(1))
    return text


def _markdown_to_html(text: str) -> str:
    html_text = _safe_text(text)
    html_text = re.sub(r"(?m)^\s*---+\s*$", "", html_text)
    html_text = re.sub(r"(?m)^\s*___+\s*$", "", html_text)
    html_text = re.sub(r"(?m)^\s*\*\*\*+\s*$", "", html_text)
    html_text = re.sub(r"(?m)^\s*```+\s*$", "", html_text)

    def _heading_repl(match: re.Match[str]) -> str:
        # 본문 H1 금지: markdown # ~ ###### 를 h2~h6 범위로 승격 변환
        level = min(max(len(match.group(1)) + 1, 2), 6)
        text_part = _safe_text(match.group(2))
        return f"<h{level}>{text_part}</h{level}>"

    html_text = MD_HEADING_RE.sub(_heading_repl, html_text)
    html_text = MD_BOLD_RE.sub(r"<strong>\1</strong>", html_text)

    lines = html_text.splitlines()
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


def _sanitize_body(content: str) -> str:
    text = _unwrap_article(content)
    text = _extract_documentary_body(text)
    text = SCRIPT_RE.sub("", text)
    text = STYLE_RE.sub("", text)
    text = re.sub(r"<figure\b[^>]*>.*?</figure>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = BANNER_RE.sub("", text)
    text = H1_RE.sub("", text)
    text = IMG_RE.sub("", text)
    text = _markdown_to_html(text)
    text = text.replace("***", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _plain_text(content: str) -> str:
    text = TAG_RE.sub(" ", _safe_text(content))
    text = MULTISPACE_RE.sub(" ", text)
    return text.strip()


def _build_excerpt(text: str) -> str:
    value = _safe_text(text)
    if len(value) <= 150:
        return value
    return f"{value[:150].rstrip()}..."


def _build_seo_description(text: str) -> str:
    value = _safe_text(text)
    if len(value) <= 280:
        return value
    return f"{value[:280].rstrip()}..."


def _build_content(*, title: str, cover_image: str, body_html: str) -> str:
    escaped_title = html.escape(title, quote=True)
    escaped_cover = html.escape(cover_image, quote=True)
    return (
        "<article class='mysteria-record-v1' style='max-width:840px;margin:0 auto;"
        "font-family:\"Pretendard\",sans-serif;color:#111827;line-height:1.85;'>"
        "<figure style='margin:0 0 28px;'>"
        f"<img src=\"{escaped_cover}\" alt=\"{escaped_title}\" loading='eager' decoding='async' "
        "style='width:100%;display:block;border-radius:18px;object-fit:cover;'/>"
        "</figure>"
        "<section class='documentary-body' style='font-size:17px;line-height:1.95;color:#111827;'>"
        f"{_safe_text(body_html)}"
        "</section>"
        "</article>"
    )


def _trigger_build(client: CloudflareIntegrationClient) -> dict[str, Any]:
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
    parser = argparse.ArgumentParser(description="Repair Mysteria posts by number range with one-image policy.")
    parser.add_argument("--from", dest="range_from", type=int, default=52, help="Start number (inclusive).")
    parser.add_argument("--to", dest="range_to", type=int, default=150, help="End number (inclusive).")
    parser.add_argument("--execute", action="store_true", help="Apply PUT update. Default is dry-run.")
    parser.add_argument("--trigger-build", action="store_true", help="Trigger build after execute.")
    parser.add_argument("--limit", type=int, default=0, help="Optional max number of rows to process.")
    parser.add_argument(
        "--only-uncategorized",
        action="store_true",
        help="Process only rows where both categoryId/categorySlug are empty.",
    )
    parser.add_argument("--token", default=os.environ.get("DONGRI_M2M_TOKEN", "").strip(), help="Fallback API token.")
    parser.add_argument(
        "--api-base-url",
        default=os.environ.get("CLOUDFLARE_BLOG_API_BASE_URL", "https://api.dongriarchive.com").strip(),
        help="Fallback API base URL.",
    )
    args = parser.parse_args()

    if args.range_from > args.range_to:
        raise ValueError("--from must be <= --to")

    started_at = now_iso()
    with SessionLocal() as db:
        try:
            client = CloudflareIntegrationClient.from_db(db)
        except Exception:
            client = CloudflareIntegrationClient(base_url=args.api_base_url, token=args.token)
        all_posts = client.list_posts()

        candidates: list[dict[str, Any]] = []
        for post in all_posts:
            slug = _safe_text(post.get("slug"))
            number = _extract_number(slug)
            if number is None:
                continue
            if number < args.range_from or number > args.range_to:
                continue
            if args.only_uncategorized:
                post_cat_id = _safe_text(post.get("categoryId") or post.get("category_id"))
                post_cat_slug = _safe_text(post.get("categorySlug") or post.get("category_slug"))
                cat_obj = post.get("category") if isinstance(post.get("category"), dict) else {}
                if not post_cat_id:
                    post_cat_id = _safe_text(cat_obj.get("id"))
                if not post_cat_slug:
                    post_cat_slug = _safe_text(cat_obj.get("slug"))
                if post_cat_id or post_cat_slug:
                    continue
            candidates.append(post)

        candidates.sort(key=lambda item: (_extract_number(_safe_text(item.get("slug"))) or 0, _safe_text(item.get("slug"))))
        if args.limit and args.limit > 0:
            candidates = candidates[: args.limit]

        rows: list[dict[str, Any]] = []
        updated_count = 0
        skipped_count = 0

        for post in candidates:
            post_id = _safe_text(post.get("id"))
            slug = _safe_text(post.get("slug"))
            number = _extract_number(slug)
            title_before = _safe_text(post.get("title"))

            detail = client.get_post(post_id)
            cover_image = _safe_text(detail.get("coverImage"))
            content_before = _safe_text(detail.get("content"))
            cleaned_title = _clean_title(title_before)
            if (
                not cleaned_title
                or "안녕하십니까" in cleaned_title
                or "Midnight Archives" in cleaned_title
                or "다큐멘터리" in cleaned_title
                or "매거진" in cleaned_title
            ):
                fallback = re.sub(r"^mystery-archive-\d+-", "", slug, flags=re.IGNORECASE)
                fallback = fallback.replace("-", " ").strip()
                cleaned_title = fallback.title()[:120] if fallback else title_before

            row: dict[str, Any] = {
                "number": number,
                "id": post_id,
                "slug": slug,
                "title_before": title_before,
                "title_after": cleaned_title,
                "status_before": _safe_text(detail.get("status")),
                "categoryId_before": _safe_text(detail.get("categoryId") or detail.get("category_id")),
                "categorySlug_before": _safe_text(detail.get("categorySlug") or detail.get("category_slug")),
                "coverImage": cover_image,
                "content_len_before": len(content_before),
                "mode": "execute" if args.execute else "dry-run",
            }

            if not cover_image:
                row["action"] = "skipped_no_cover_image"
                skipped_count += 1
                rows.append(row)
                continue

            body_html = _sanitize_body(content_before)
            body_text = _plain_text(body_html)
            excerpt = _build_excerpt(body_text)
            seo_description = _build_seo_description(body_text)
            content_after = _build_content(title=cleaned_title, cover_image=cover_image, body_html=body_html)

            payload = {
                "title": cleaned_title,
                "slug": slug,
                "content": content_after,
                "coverImage": cover_image,
                "categoryId": TARGET_CATEGORY_ID,
                "status": "published",
                "excerpt": excerpt,
                "seoDescription": seo_description,
                "metaDescription": seo_description,
            }
            row["payload_preview"] = {
                "title": payload["title"],
                "content_len_after": len(payload["content"]),
                "excerpt_len": len(payload["excerpt"]),
                "seoDescription_len": len(payload["seoDescription"]),
            }

            if args.execute:
                try:
                    updated = client.update_post(post_id, payload)
                    row["action"] = "updated"
                    row["status_after"] = _safe_text(updated.get("status"))
                    row["categoryId_after"] = _safe_text(updated.get("categoryId") or updated.get("category_id"))
                    row["categorySlug_after"] = _safe_text(updated.get("categorySlug") or updated.get("category_slug"))
                    updated_count += 1
                except Exception as exc:  # noqa: BLE001
                    row["action"] = "failed"
                    row["error"] = str(exc)
                    skipped_count += 1
            else:
                row["action"] = "planned_update"
                updated_count += 1

            rows.append(row)

        report: dict[str, Any] = {
            "started_at": started_at,
            "mode": "execute" if args.execute else "dry-run",
            "range": {"from": args.range_from, "to": args.range_to},
            "category_rule": {"categoryId": TARGET_CATEGORY_ID, "categorySlug": TARGET_CATEGORY_SLUG},
            "summary": {
                "candidates": len(candidates),
                "updated_or_planned": updated_count,
                "skipped_or_failed": skipped_count,
            },
            "rows": rows,
            "build": None,
        }

        if args.execute and args.trigger_build:
            try:
                report["build"] = _trigger_build(client)
                time.sleep(6)
            except Exception as exc:  # noqa: BLE001
                report["build"] = {"error": str(exc)}

    report_name = f"{utc_stamp()}-{safe_filename(f'mysteria-repair-{args.range_from}-{args.range_to}')}.json"
    report_path = REPORT_ROOT / report_name
    write_json(report_path, report)
    print(json.dumps({"report_path": str(report_path), "mode": report["mode"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
