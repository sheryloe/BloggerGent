from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
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


NUMBER_MIN = 1
NUMBER_MAX = 51
TARGET_CATEGORY_ID = "cat-world-mysteria-story"
TARGET_CATEGORY_SLUG = "미스테리아-스토리"
REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\cloudflare\reports")

NUMBERED_SLUG_RE = re.compile(r"^mystery-archive-(\d+)(?:-|$)", re.IGNORECASE)
IMG_SRC_RE = re.compile(r"<img\b[^>]*\bsrc=['\"]([^'\"]+)['\"]", re.IGNORECASE)
H1_RE = re.compile(r"<h1\b", re.IGNORECASE)
MD_HEADING_RE = re.compile(r"^\s*#{1,6}\s+", re.MULTILINE)
MD_BOLD_RE = re.compile(r"\*\*[^*\n]+?\*\*")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _category_slug_from_item(item: dict[str, Any]) -> str:
    category = item.get("category")
    if isinstance(category, dict):
        return _safe_text(category.get("slug"))
    return _safe_text(item.get("categorySlug") or item.get("category_slug"))


def _category_id_from_item(item: dict[str, Any]) -> str:
    category = item.get("category")
    if isinstance(category, dict):
        cat_id = _safe_text(category.get("id"))
        if cat_id:
            return cat_id
    return _safe_text(item.get("categoryId") or item.get("category_id"))


def _is_target_category(item: dict[str, Any]) -> bool:
    cat_id = _category_id_from_item(item)
    cat_slug = _category_slug_from_item(item)
    return cat_id == TARGET_CATEGORY_ID or cat_slug == TARGET_CATEGORY_SLUG


def _extract_number(slug: str) -> int | None:
    match = NUMBERED_SLUG_RE.match(_safe_text(slug))
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _analyze_public_content(*, content: str, cover_image: str) -> dict[str, Any]:
    img_urls = [src.strip() for src in IMG_SRC_RE.findall(content or "") if src.strip()]
    h1_count = len(H1_RE.findall(content or ""))
    has_md_heading = bool(MD_HEADING_RE.search(content or ""))
    has_md_bold = bool(MD_BOLD_RE.search(content or ""))
    has_markdown = has_md_heading or has_md_bold
    has_banner = "THE MYSTERIA ARCHIVE" in (content or "")
    cover_match = len(img_urls) == 1 and cover_image and img_urls[0] == cover_image
    return {
        "content_len": len(content or ""),
        "img_count": len(img_urls),
        "img_urls": img_urls,
        "h1_count": h1_count,
        "has_markdown_syntax": has_markdown,
        "has_markdown_heading": has_md_heading,
        "has_markdown_bold": has_md_bold,
        "has_archive_banner": has_banner,
        "one_image_matches_cover": bool(cover_match),
    }


def fetch_public_post(slug: str, *, timeout: float = 30.0) -> dict[str, Any]:
    url = f"https://api.dongriarchive.com/api/public/posts/{slug}"
    response = httpx.get(url, timeout=timeout, follow_redirects=True)
    payload: Any = {}
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return {
            "found": False,
            "status_code": response.status_code,
            "url": url,
            "message": payload.get("message") if isinstance(payload, dict) else "",
        }

    content = _safe_text(data.get("content"))
    cover_image = _safe_text(data.get("coverImage"))
    analysis = _analyze_public_content(content=content, cover_image=cover_image)
    return {
        "found": True,
        "status_code": response.status_code,
        "url": url,
        "id": _safe_text(data.get("id")),
        "slug": _safe_text(data.get("slug")),
        "title": _safe_text(data.get("title")),
        "status": _safe_text(data.get("status")),
        "category_slug": _category_slug_from_item(data),
        "category_id": _category_id_from_item(data),
        "coverImage": cover_image,
        "analysis": analysis,
    }


def _build_integration_map(posts: list[dict[str, Any]]) -> tuple[dict[int, list[dict[str, Any]]], list[dict[str, Any]]]:
    numbered: dict[int, list[dict[str, Any]]] = defaultdict(list)
    rows: list[dict[str, Any]] = []
    for post in posts:
        slug = _safe_text(post.get("slug"))
        num = _extract_number(slug)
        if num is None or num < NUMBER_MIN or num > NUMBER_MAX:
            continue
        row = {
            "number": num,
            "id": _safe_text(post.get("id")),
            "slug": slug,
            "title": _safe_text(post.get("title")),
            "status": _safe_text(post.get("status")),
            "category_id": _category_id_from_item(post),
            "category_slug": _category_slug_from_item(post),
            "is_target_category": _is_target_category(post),
            "updatedAt": _safe_text(post.get("updatedAt")),
            "publishedAt": _safe_text(post.get("publishedAt")),
        }
        numbered[num].append(row)
        rows.append(row)
    return numbered, rows


def _summarize(report_rows: list[dict[str, Any]], integration_map: dict[int, list[dict[str, Any]]]) -> dict[str, Any]:
    expected_numbers = list(range(NUMBER_MIN, NUMBER_MAX + 1))
    missing_numbers = [n for n in expected_numbers if n not in integration_map]
    multi_number_slots = [n for n, values in integration_map.items() if len(values) > 1]

    integration_total = len(report_rows)
    integration_wrong_category = sum(1 for row in report_rows if not row.get("integration", {}).get("is_target_category", False))

    public_rows = [row for row in report_rows if row.get("public", {}).get("found")]
    public_missing = [row for row in report_rows if not row.get("public", {}).get("found")]

    def _count_public(key: str, *, nested: bool = True) -> int:
        total = 0
        for row in public_rows:
            if nested:
                if row.get("public", {}).get("analysis", {}).get(key):
                    total += 1
            else:
                if row.get("public", {}).get(key):
                    total += 1
        return total

    return {
        "target_range": {"from": NUMBER_MIN, "to": NUMBER_MAX},
        "expected_slots": len(expected_numbers),
        "integration_found_slots": len(integration_map),
        "integration_total_rows": integration_total,
        "integration_missing_numbers": missing_numbers,
        "integration_duplicate_number_slots": multi_number_slots,
        "integration_wrong_category_count": integration_wrong_category,
        "public_found_count": len(public_rows),
        "public_missing_count": len(public_missing),
        "forbidden_archive_banner_count": _count_public("has_archive_banner"),
        "forbidden_body_h1_count": sum(
            1 for row in public_rows if int(row.get("public", {}).get("analysis", {}).get("h1_count", 0)) > 0
        ),
        "forbidden_markdown_count": _count_public("has_markdown_syntax"),
        "image_rule_violation_count": sum(
            1 for row in public_rows if not row.get("public", {}).get("analysis", {}).get("one_image_matches_cover", False)
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Mysteria posts 1~51 with integration + public checks.")
    parser.add_argument("--include-nonpublic-check", action="store_true", help="Include integration API checks.")
    parser.add_argument(
        "--api-base-url",
        default=os.environ.get("CLOUDFLARE_BLOG_API_BASE_URL", "https://api.dongriarchive.com").strip(),
        help="Fallback integration API base URL.",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("DONGRI_M2M_TOKEN", "").strip(),
        help="Fallback integration bearer token.",
    )
    args = parser.parse_args()

    started_at = now_iso()
    report_rows: list[dict[str, Any]] = []
    integration_map: dict[int, list[dict[str, Any]]] = {}
    integration_rows: list[dict[str, Any]] = []

    if args.include_nonpublic_check:
        with SessionLocal() as db:
            try:
                client = CloudflareIntegrationClient.from_db(db)
            except Exception:
                client = CloudflareIntegrationClient(base_url=args.api_base_url, token=args.token)
            all_posts = client.list_posts()
        integration_map, integration_rows = _build_integration_map(all_posts)
    else:
        integration_map = {}
        integration_rows = []

    if args.include_nonpublic_check:
        for number in sorted(integration_map):
            candidates = sorted(
                integration_map[number],
                key=lambda item: (_safe_text(item.get("updatedAt")), _safe_text(item.get("publishedAt")), item.get("id", "")),
                reverse=True,
            )
            for idx, integration in enumerate(candidates):
                public = fetch_public_post(integration["slug"])
                report_rows.append(
                    {
                        "number": number,
                        "slot_rank": idx + 1,
                        "integration": integration,
                        "public": public,
                    }
                )
    else:
        # 공개 기준 점검: public list를 스캔해 1~51 번호형 slug만 수집
        response = httpx.get("https://api.dongriarchive.com/api/public/posts?limit=1000", timeout=60.0, follow_redirects=True)
        payload: Any = {}
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        posts = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), list) else []
        candidates: list[tuple[int, str]] = []
        for item in posts:
            if not isinstance(item, dict):
                continue
            slug = _safe_text(item.get("slug"))
            number = _extract_number(slug)
            if number is None or number < NUMBER_MIN or number > NUMBER_MAX:
                continue
            candidates.append((number, slug))
        candidates.sort(key=lambda it: (it[0], it[1]))
        for number, slug in candidates:
            public = fetch_public_post(slug)
            report_rows.append(
                {
                    "number": number,
                    "slot_rank": 1,
                    "integration": {"slug": slug, "is_target_category": None},
                    "public": public,
                }
            )

    summary = _summarize(report_rows, integration_map)
    report = {
        "started_at": started_at,
        "mode": "integration+public" if args.include_nonpublic_check else "public_only",
        "category_rule": {"categoryId": TARGET_CATEGORY_ID, "categorySlug": TARGET_CATEGORY_SLUG},
        "summary": summary,
        "rows": report_rows,
        "integration_rows": integration_rows if args.include_nonpublic_check else [],
    }

    report_name = f"{utc_stamp()}-{safe_filename('mysteria-1-51-audit')}.json"
    report_path = REPORT_ROOT / report_name
    write_json(report_path, report)
    print(json.dumps({"report_path": str(report_path), "mode": report["mode"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
