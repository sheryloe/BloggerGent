from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from package_common import CloudflareIntegrationClient, SessionLocal  # noqa: E402

TARGET_CATEGORY_ID = "cat-world-mysteria-story"
TARGET_CATEGORY_SLUG = "미스테리아-스토리"
NUMBERED_SLUG_RE = re.compile(r"^mystery-archive-(\d+)(?:-|$)", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def safe_text(value: Any) -> str:
    return str(value or "").strip()


def strip_tags(value: str) -> str:
    return SPACE_RE.sub(" ", TAG_RE.sub(" ", safe_text(value))).strip()


def parse_number(slug: str) -> int | None:
    match = NUMBERED_SLUG_RE.match(safe_text(slug))
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def parse_scores(detail: dict[str, Any]) -> tuple[float, float, float, float]:
    quality = detail.get("quality") if isinstance(detail.get("quality"), dict) else {}
    analytics = detail.get("analytics") if isinstance(detail.get("analytics"), dict) else {}

    def pick(*values: Any) -> float:
        for value in values:
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return 0.0

    seo = pick(detail.get("seo_score"), detail.get("seoScore"), quality.get("seo_score"), quality.get("seoScore"))
    geo = pick(detail.get("geo_score"), detail.get("geoScore"), quality.get("geo_score"), quality.get("geoScore"))
    ctr = pick(detail.get("ctr"), detail.get("clickThroughRate"), analytics.get("ctr"), analytics.get("clickThroughRate"))
    lh = pick(
        detail.get("lighthouse_score"),
        detail.get("lighthouseScore"),
        quality.get("lighthouse_score"),
        quality.get("lighthouseScore"),
        analytics.get("lighthouse_score"),
        analytics.get("lighthouseScore"),
    )
    if lh <= 0.0:
        lh = (seo + geo + ctr) / 3.0 if (seo > 0 or geo > 0 or ctr > 0) else 0.0
    return seo, geo, ctr, lh


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify Mysteria post policy checks.")
    parser.add_argument("--post-number", type=int, required=True, help="mystery-archive-{n} number")
    parser.add_argument("--require-min-chars", type=int, default=3000, help="Minimum plain-text characters")
    parser.add_argument("--require-main-image-only", action="store_true", help="Require one body image == coverImage")
    parser.add_argument("--require-gate", choices=("avg80_min70",), default="avg80_min70", help="Quality gate rule")
    parser.add_argument("--token", default=safe_text(os.environ.get("DONGRI_M2M_TOKEN", "")), help="Integration token override.")
    parser.add_argument(
        "--api-base-url",
        default=safe_text(os.environ.get("CLOUDFLARE_BLOG_API_BASE_URL", "https://api.dongriarchive.com")),
        help="Integration API base URL override.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.token:
        client = CloudflareIntegrationClient(base_url=args.api_base_url, token=args.token)
    else:
        with SessionLocal() as db:
            client = CloudflareIntegrationClient.from_db(db)
    posts = client.list_posts()

    target: dict[str, Any] | None = None
    for post in posts:
        slug = safe_text(post.get("slug"))
        number = parse_number(slug)
        if number == args.post_number:
            target = post
            break

    if target is None:
        print(json.dumps({"error": f"post_number_not_found:{args.post_number}"}, ensure_ascii=False))
        return 1

    post_id = safe_text(target.get("id"))
    detail = client.get_post(post_id)

    slug = safe_text(detail.get("slug") or target.get("slug"))
    title = safe_text(detail.get("title") or target.get("title"))
    content = safe_text(detail.get("content") or detail.get("contentMarkdown"))
    cover_image = safe_text(detail.get("coverImage") or target.get("coverImage"))
    category = detail.get("category") if isinstance(detail.get("category"), dict) else {}
    category_id = safe_text(category.get("id") or detail.get("categoryId") or target.get("categoryId"))
    category_slug = safe_text(category.get("slug") or detail.get("categorySlug") or target.get("categorySlug"))

    body_text = strip_tags(content)
    char_count = len(body_text)
    body_imgs = re.findall(r"""<img\b[^>]*\bsrc=["']([^"']+)["']""", content, re.IGNORECASE)
    body_h1_count = len(re.findall(r"<h1\b", content, re.IGNORECASE))
    markdown_heading = bool(re.search(r"(?m)^\s*#{1,6}\s+", content))
    markdown_bold = bool(re.search(r"\*\*[^*\n]+?\*\*", content))
    archive_banner = "THE MYSTERIA ARCHIVE" in content

    seo, geo, ctr, lh = parse_scores(detail)
    avg_score = round((seo + geo + ctr + lh) / 4.0, 1)
    min_score = round(min(seo, geo, ctr, lh), 1)

    checks = {
        "category_ok": category_id == TARGET_CATEGORY_ID or category_slug == TARGET_CATEGORY_SLUG,
        "no_archive_banner": not archive_banner,
        "no_body_h1": body_h1_count == 0,
        "no_markdown": not markdown_heading and not markdown_bold,
        "min_chars_ok": char_count >= args.require_min_chars,
        "gate_ok": avg_score >= 80.0 and min_score >= 70.0,
    }

    if args.require_main_image_only:
        one_image_only = len(body_imgs) == 1
        image_matches_cover = one_image_only and safe_text(body_imgs[0]) == cover_image and bool(cover_image)
        checks["main_image_only"] = image_matches_cover

    result = {
        "post_id": post_id,
        "slug": slug,
        "title": title,
        "cloudflare_url": safe_text(detail.get("url") or target.get("url")),
        "category_id": category_id,
        "category_slug": category_slug,
        "char_count": char_count,
        "body_image_count": len(body_imgs),
        "cover_image": cover_image,
        "seo_score": round(seo, 1),
        "geo_score": round(geo, 1),
        "ctr_score": round(ctr, 1),
        "lighthouse_score": round(lh, 1),
        "avg_score": avg_score,
        "min_score": min_score,
        "checks": checks,
        "pass": all(bool(v) for v in checks.values()),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
