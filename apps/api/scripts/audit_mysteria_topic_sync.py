from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent")
os.environ.setdefault("SETTINGS_ENCRYPTION_SECRET", "bloggent-dockerdesktop-2026-03-17")

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import SyncedBloggerPost  # noqa: E402
from package_common import CloudflareIntegrationClient, fetch_synced_blogger_posts, resolve_blog_by_profile_key  # noqa: E402

REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\cloudflare\reports")
TARGET_CATEGORY_ID = "cat-world-mysteria-story"
TARGET_CATEGORY_SLUG = "미스테리아-스토리"
NUMBERED_SLUG_RE = re.compile(r"^mystery-archive-(\d+)(?:-|$)", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def safe_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_space(value: str) -> str:
    return SPACE_RE.sub(" ", safe_text(value).replace("\xa0", " ")).strip()


def strip_tags(value: str) -> str:
    return normalize_space(TAG_RE.sub(" ", value or ""))


def normalize_url(value: str) -> str:
    raw = safe_text(value)
    if not raw:
        return ""
    return raw.split("#")[0].split("?")[0].strip().lower()


def parse_number_from_slug(slug: str) -> int | None:
    match = NUMBERED_SLUG_RE.match(safe_text(slug))
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def title_tokens(value: str) -> set[str]:
    tokens = re.split(r"[^a-z0-9가-힣]+", safe_text(value).lower())
    return {token for token in tokens if len(token) >= 2}


def token_overlap(left: str, right: str) -> int:
    return len(title_tokens(left) & title_tokens(right))


def source_slug_from_url(url: str) -> str:
    path = unquote((urlparse(url).path or "").strip("/"))
    slug = path.split("/")[-1] if path else ""
    return re.sub(r"\.html$", "", slug, flags=re.IGNORECASE)


def fetch_hash(client: httpx.Client, cache: dict[str, str], url: str) -> str:
    key = normalize_url(url)
    if not key:
        return ""
    if key in cache:
        return cache[key]
    try:
        response = client.get(url, timeout=45)
        response.raise_for_status()
        digest = hashlib.sha256(response.content).hexdigest()
        cache[key] = digest
    except Exception:
        cache[key] = ""
    return cache[key]


def resolve_image_match_state(
    client: httpx.Client,
    cache: dict[str, str],
    source_image: str,
    cover_image: str,
) -> str:
    source_key = normalize_url(source_image)
    cover_key = normalize_url(cover_image)
    if source_key and cover_key and source_key == cover_key:
        return "url_match"
    if source_key and cover_key:
        left_hash = fetch_hash(client, cache, source_image)
        right_hash = fetch_hash(client, cache, cover_image)
        if left_hash and right_hash and left_hash == right_hash:
            return "hash_match"
    return "mismatch"


def select_source_candidate(
    source_rows: list[SyncedBloggerPost],
    source_by_number: dict[int, SyncedBloggerPost],
    *,
    cf_slug: str,
    cf_title: str,
) -> tuple[SyncedBloggerPost | None, int]:
    number = parse_number_from_slug(cf_slug)
    if number is not None and number in source_by_number:
        return source_by_number[number], 999
    best: SyncedBloggerPost | None = None
    best_score = -1
    for src in source_rows:
        overlap = token_overlap(cf_title, src.title)
        overlap += token_overlap(cf_slug, source_slug_from_url(src.url or ""))
        if overlap > best_score:
            best = src
            best_score = overlap
    return best, best_score


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
        lh = (seo + geo + ctr) / 3.0
    return seo, geo, ctr, lh


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Mysteria topic/image synchronization with metadata-only matching.")
    parser.add_argument("--category", default=TARGET_CATEGORY_SLUG, help="Target Cloudflare category slug.")
    parser.add_argument("--topic-only", action="store_true", help="Topic metadata mode only (default behavior).")
    parser.add_argument("--dry-run", action="store_true", help="No mutation. Audit only.")
    parser.add_argument("--token", default=safe_text(os.environ.get("DONGRI_M2M_TOKEN", "")), help="Integration token override.")
    parser.add_argument(
        "--api-base-url",
        default=safe_text(os.environ.get("CLOUDFLARE_BLOG_API_BASE_URL", "https://api.dongriarchive.com")),
        help="Integration API base URL override.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as db:
        source_blog = resolve_blog_by_profile_key(db, "world_mystery")
        source_rows = fetch_synced_blogger_posts(db, source_blog.id)
        source_rows = sorted(
            source_rows,
            key=lambda row: (
                row.published_at or datetime.min.replace(tzinfo=timezone.utc),
                row.id,
            ),
        )
        source_by_number: dict[int, SyncedBloggerPost] = {}
        for index, row in enumerate(source_rows, start=1):
            source_by_number[index] = row

        if args.token:
            client = CloudflareIntegrationClient(base_url=args.api_base_url, token=args.token)
        else:
            client = CloudflareIntegrationClient.from_db(db)
        all_posts = client.list_posts()
        target_posts = []
        for post in all_posts:
            category = post.get("category") if isinstance(post.get("category"), dict) else {}
            category_id = safe_text(category.get("id") or post.get("categoryId"))
            category_slug = safe_text(category.get("slug") or post.get("categorySlug"))
            if category_id != TARGET_CATEGORY_ID and category_slug != args.category:
                continue
            target_posts.append(post)

    rows: list[dict[str, Any]] = []
    image_hash_cache: dict[str, str] = {}
    with httpx.Client(follow_redirects=True) as web_client, SessionLocal() as db:
        if args.token:
            api_client = CloudflareIntegrationClient(base_url=args.api_base_url, token=args.token)
        else:
            api_client = CloudflareIntegrationClient.from_db(db)
        for post in target_posts:
            remote_id = safe_text(post.get("id"))
            if not remote_id:
                continue
            detail = api_client.get_post(remote_id)
            slug = safe_text(detail.get("slug") or post.get("slug"))
            title = safe_text(detail.get("title") or post.get("title"))
            public_url = safe_text(detail.get("publicUrl") or detail.get("url") or post.get("url"))
            cover_image = safe_text(detail.get("coverImage") or post.get("coverImage"))
            content = safe_text(detail.get("content") or detail.get("contentMarkdown"))
            content_len = len(strip_tags(content))
            body_img_count = len(re.findall(r"(?is)<img\b", content))

            src, overlap_score = select_source_candidate(
                source_rows,
                source_by_number,
                cf_slug=slug,
                cf_title=title,
            )
            source_url = safe_text(src.url if src else "")
            source_title = safe_text(src.title if src else "")
            source_image = safe_text(src.thumbnail_url if src else "")
            image_match_state = resolve_image_match_state(web_client, image_hash_cache, source_image, cover_image)

            title_overlap = token_overlap(source_title, title) if src else 0
            category_slug = safe_text((detail.get("category") or {}).get("slug") or post.get("categorySlug"))
            category_match = category_slug == args.category
            number_match = False
            src_number = None
            if src is not None:
                src_number = next((num for num, row in source_by_number.items() if row.id == src.id), None)
            cf_number = parse_number_from_slug(slug)
            if src_number is not None and cf_number is not None:
                number_match = src_number == cf_number

            topic_match_state = "mismatch"
            if category_match and (number_match or title_overlap >= 2) and image_match_state in {"url_match", "hash_match"}:
                topic_match_state = "synced_ok"
            elif category_match and (number_match or title_overlap >= 1 or overlap_score >= 1):
                topic_match_state = "review_required"

            seo, geo, ctr, lh = parse_scores(detail)
            avg_score = round((seo + geo + ctr + lh) / 4.0, 1)
            min_score = round(min(seo, geo, ctr, lh), 1)
            pass_rule = avg_score >= 80.0 and min_score >= 70.0 and content_len >= 3000 and body_img_count <= 1

            rows.append(
                {
                    "number": cf_number,
                    "google_url": source_url,
                    "google_title": source_title,
                    "cloudflare_remote_id": remote_id,
                    "cloudflare_slug": slug,
                    "cloudflare_url": public_url,
                    "cloudflare_title": title,
                    "category_match": category_match,
                    "topic_overlap_score": overlap_score,
                    "title_token_overlap": title_overlap,
                    "number_match": number_match,
                    "image_match_state": image_match_state,
                    "image_match": image_match_state in {"url_match", "hash_match"},
                    "content_len": content_len,
                    "body_image_count": body_img_count,
                    "seo_score": round(seo, 1),
                    "geo_score": round(geo, 1),
                    "ctr_score": round(ctr, 1),
                    "lighthouse_score": round(lh, 1),
                    "avg_score": avg_score,
                    "min_score": min_score,
                    "pass_rule": pass_rule,
                    "topic_match_state": topic_match_state,
                }
            )

    rows.sort(key=lambda row: (row.get("number") is None, row.get("number") or 999999, row.get("cloudflare_slug") or ""))
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": bool(args.dry_run),
        "category": args.category,
        "target_count": len(rows),
        "synced_ok": sum(1 for row in rows if row.get("topic_match_state") == "synced_ok"),
        "review_required": sum(1 for row in rows if row.get("topic_match_state") == "review_required"),
        "mismatch": sum(1 for row in rows if row.get("topic_match_state") == "mismatch"),
        "pass_rule_count": sum(1 for row in rows if row.get("pass_rule") is True),
        "below_3000_count": sum(1 for row in rows if int(row.get("content_len") or 0) < 3000),
        "image_mismatch_count": sum(1 for row in rows if row.get("image_match") is False),
    }

    report_path = REPORT_ROOT / f"mysteria-topic-sync-audit-{stamp}.json"
    report_payload = {"summary": summary, "rows": rows}
    report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary": summary, "report_path": str(report_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
