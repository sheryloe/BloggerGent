from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@postgres:5432/bloggent"
DEFAULT_BLOG_IDS = [34, 35, 36, 37]
LIVE_STATUSES = {"live", "published", "LIVE", "PUBLISHED"}

IMG_SRC_RE = re.compile(r"""<img\b[^>]*\bsrc=['"]([^'"]+)['"]""", re.IGNORECASE)
SRCSET_RE = re.compile(r"""\bsrcset=['"]([^'"]+)['"]""", re.IGNORECASE)
RELATED_SECTION_RE = re.compile(
    r"""<section\b[^>]*class=['"][^'"]*related-posts[^'"]*['"][^>]*>.*?</section>""",
    re.IGNORECASE | re.DOTALL,
)

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get("BLOGGENT_DATABASE_URL", DEFAULT_DATABASE_URL)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import SyncedBloggerPost  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan live Blogger pages for PNG URLs, including related-posts sections.")
    parser.add_argument("--blog-id", action="append", type=int, default=[], help="Target blog id. Repeat for multiple.")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout seconds.")
    parser.add_argument("--report-path", default="", help="Optional JSON report path.")
    return parser.parse_args()


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _extract_srcset_urls(srcset_value: str) -> list[str]:
    urls: list[str] = []
    for part in (srcset_value or "").split(","):
        candidate = _safe_str(part.split(" ")[0])
        if candidate:
            urls.append(candidate)
    return urls


def _extract_image_urls(content: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for match in IMG_SRC_RE.finditer(content or ""):
        value = _safe_str(match.group(1))
        if value and value not in seen:
            seen.add(value)
            urls.append(value)
    for match in SRCSET_RE.finditer(content or ""):
        for value in _extract_srcset_urls(match.group(1)):
            if value and value not in seen:
                seen.add(value)
                urls.append(value)
    return urls


def _is_image_like(url: str) -> bool:
    path = (urlparse(_safe_str(url)).path or "").lower()
    return any(token in path for token in (".webp", ".png", ".jpg", ".jpeg", ".gif", ".avif", ".svg"))


def _is_png_url(url: str) -> bool:
    path = (urlparse(_safe_str(url)).path or "").lower()
    return ".png" in path


def _new_summary() -> dict[str, int]:
    return {
        "posts_scanned": 0,
        "pages_fetch_failed": 0,
        "image_urls_total": 0,
        "png_urls_total": 0,
        "posts_with_png": 0,
        "related_image_urls_total": 0,
        "related_png_urls_total": 0,
        "posts_with_related_png": 0,
    }


def run_scan(*, blog_ids: list[int], timeout: float) -> dict[str, Any]:
    target_blog_ids = sorted({int(value) for value in blog_ids if int(value) > 0}) or DEFAULT_BLOG_IDS.copy()
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": {"blog_ids": target_blog_ids, "statuses": sorted(LIVE_STATUSES)},
        "summary": _new_summary(),
        "by_blog": {str(blog_id): _new_summary() for blog_id in target_blog_ids},
        "items_with_png": [],
        "related_items_with_png": [],
        "fetch_failures": [],
    }

    with SessionLocal() as db:
        posts = (
            db.execute(
                select(SyncedBloggerPost)
                .where(
                    SyncedBloggerPost.blog_id.in_(target_blog_ids),
                    SyncedBloggerPost.status.in_(sorted(LIVE_STATUSES)),
                    SyncedBloggerPost.url.is_not(None),
                )
                .order_by(SyncedBloggerPost.blog_id.asc(), SyncedBloggerPost.id.desc())
            )
            .scalars()
            .all()
        )

    with httpx.Client(timeout=max(float(timeout), 5.0), follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
        for post in posts:
            blog_id = int(post.blog_id)
            summary = report["summary"]
            blog_summary = report["by_blog"].setdefault(str(blog_id), _new_summary())
            summary["posts_scanned"] += 1
            blog_summary["posts_scanned"] += 1
            page_url = _safe_str(post.url)

            try:
                response = client.get(page_url)
                response.raise_for_status()
                html = response.text
            except Exception as exc:  # noqa: BLE001
                summary["pages_fetch_failed"] += 1
                blog_summary["pages_fetch_failed"] += 1
                report["fetch_failures"].append(
                    {
                        "blog_id": blog_id,
                        "remote_post_id": _safe_str(post.remote_post_id),
                        "url": page_url,
                        "error": str(exc),
                    }
                )
                continue

            image_urls = [url for url in _extract_image_urls(html) if _is_image_like(url)]
            png_urls = [url for url in image_urls if _is_png_url(url)]
            summary["image_urls_total"] += len(image_urls)
            blog_summary["image_urls_total"] += len(image_urls)
            summary["png_urls_total"] += len(png_urls)
            blog_summary["png_urls_total"] += len(png_urls)
            if png_urls:
                summary["posts_with_png"] += 1
                blog_summary["posts_with_png"] += 1
                report["items_with_png"].append(
                    {
                        "blog_id": blog_id,
                        "remote_post_id": _safe_str(post.remote_post_id),
                        "title": _safe_str(post.title),
                        "url": page_url,
                        "png_urls": png_urls,
                    }
                )

            related_sections = RELATED_SECTION_RE.findall(html)
            related_html = "\n".join(related_sections)
            related_urls = [url for url in _extract_image_urls(related_html) if _is_image_like(url)]
            related_png_urls = [url for url in related_urls if _is_png_url(url)]
            summary["related_image_urls_total"] += len(related_urls)
            blog_summary["related_image_urls_total"] += len(related_urls)
            summary["related_png_urls_total"] += len(related_png_urls)
            blog_summary["related_png_urls_total"] += len(related_png_urls)
            if related_png_urls:
                summary["posts_with_related_png"] += 1
                blog_summary["posts_with_related_png"] += 1
                report["related_items_with_png"].append(
                    {
                        "blog_id": blog_id,
                        "remote_post_id": _safe_str(post.remote_post_id),
                        "title": _safe_str(post.title),
                        "url": page_url,
                        "related_png_urls": related_png_urls,
                    }
                )

    return report


def main() -> int:
    args = parse_args()
    report = run_scan(
        blog_ids=list(args.blog_id or []),
        timeout=float(args.timeout or 30.0),
    )
    report_path = (
        Path(args.report_path)
        if _safe_str(args.report_path)
        else REPO_ROOT / "storage" / "reports" / f"scan-blogger-live-png-{_timestamp()}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(report_path))
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
