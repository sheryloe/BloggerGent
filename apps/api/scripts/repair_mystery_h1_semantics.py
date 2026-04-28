from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@postgres:5432/bloggent"
DEFAULT_REPORT_PATH = Path(r"D:\Donggri_Runtime\BloggerGent\Rool\mystery\h1-repair-20260421.json")
MYSTERY_BLOG_ID = 35
MYSTERY_PROFILE_KEY = "world_mystery"
LIVE_STATUSES = {"LIVE", "PUBLISHED", "live", "published"}

H1_RE = re.compile(r"<h1\b[^>]*>.*?</h1>", re.IGNORECASE | re.DOTALL)
HTML_TAG_RE = re.compile(r"<.*?>", re.DOTALL)
LEADING_TITLE_H1_RE = re.compile(
    r"^\s*<h1\b[^>]*>.*?</h1>\s*"
    r"(?=<div\b[^>]*class=(?P<quote>['\"])[^'\"]*\bfont-body\b[^'\"]*(?P=quote)[^>]*>)",
    re.IGNORECASE | re.DOTALL,
)
LEADING_NESTED_TITLE_H1_RE = re.compile(
    r"^((?:\s*<div\b[^>]*class=(?P<quote>['\"])[^'\"]*\bfont-body\b[^'\"]*(?P=quote)[^>]*>\s*)+)"
    r"<h1\b[^>]*>.*?</h1>\s*",
    re.IGNORECASE | re.DOTALL,
)
OPEN_H1_RE = re.compile(r"<h1(\s[^>]*)?>", re.IGNORECASE)
CLOSE_H1_RE = re.compile(r"</h1\s*>", re.IGNORECASE)

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get("BLOGGENT_DATABASE_URL", DEFAULT_DATABASE_URL)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Article, Blog, BloggerPost, SyncedBloggerPost  # noqa: E402
from app.services.providers.factory import get_blogger_provider  # noqa: E402


@dataclass(slots=True)
class H1RepairResult:
    html: str
    h1_before: int
    h1_after: int
    leading_wrappers_removed: int
    trailing_divs_removed: int
    h1_demoted: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair mystery Blogger post H1 semantics.")
    parser.add_argument("--blog-id", type=int, required=True)
    parser.add_argument("--mode", choices=("dry-run", "apply", "verify-live"), required=True)
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--sleep-seconds", type=float, default=0.15)
    return parser.parse_args()


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _h1_texts(html_value: str | None) -> list[str]:
    texts: list[str] = []
    for match in H1_RE.finditer(str(html_value or "")):
        text = unescape(HTML_TAG_RE.sub("", match.group(0))).strip()
        texts.append(re.sub(r"\s+", " ", text))
    return texts


def _count_h1(html_value: str | None) -> int:
    return len(H1_RE.findall(str(html_value or "")))


def _remove_leading_title_h1s(html_value: str) -> tuple[str, int]:
    html = html_value
    removed = 0
    match = LEADING_TITLE_H1_RE.match(html)
    if match:
        html = html[match.end() :]
        removed += 1
    while True:
        match = LEADING_NESTED_TITLE_H1_RE.match(html)
        if not match:
            return html, removed
        html = f"{match.group(1)}{html[match.end():]}"
        removed += 1


def repair_content_h1(html_value: str | None) -> H1RepairResult:
    original = str(html_value or "")
    h1_before = _count_h1(original)
    without_leading_titles, leading_titles_removed = _remove_leading_title_h1s(original)
    h1_demoted = _count_h1(without_leading_titles)
    repaired = OPEN_H1_RE.sub(lambda match: f"<h2{match.group(1) or ''}>", without_leading_titles)
    repaired = CLOSE_H1_RE.sub("</h2>", repaired)
    return H1RepairResult(
        html=repaired,
        h1_before=h1_before,
        h1_after=_count_h1(repaired),
        leading_wrappers_removed=leading_titles_removed,
        trailing_divs_removed=0,
        h1_demoted=h1_demoted,
    )


def _require_mystery_blog(db: Session, blog_id: int) -> Blog:
    if int(blog_id) != MYSTERY_BLOG_ID:
        raise RuntimeError(f"refusing_non_mystery_blog:{blog_id}")
    blog = db.get(Blog, blog_id)
    if blog is None:
        raise RuntimeError(f"blog_not_found:{blog_id}")
    if _safe_str(blog.profile_key) != MYSTERY_PROFILE_KEY:
        raise RuntimeError(f"profile_key_mismatch:{blog.profile_key}")
    return blog


def _load_live_posts(db: Session, blog_id: int) -> list[SyncedBloggerPost]:
    return (
        db.execute(
            select(SyncedBloggerPost)
            .where(
                SyncedBloggerPost.blog_id == blog_id,
                SyncedBloggerPost.status.in_(sorted(LIVE_STATUSES)),
                SyncedBloggerPost.url.is_not(None),
            )
            .order_by(SyncedBloggerPost.id.asc())
        )
        .scalars()
        .all()
    )


def _load_blogger_posts_by_remote(db: Session, blog_id: int, posts: list[SyncedBloggerPost]) -> dict[str, BloggerPost]:
    remote_ids = sorted({_safe_str(row.remote_post_id) for row in posts if _safe_str(row.remote_post_id)})
    if not remote_ids:
        return {}
    rows = (
        db.execute(
            select(BloggerPost)
            .where(BloggerPost.blog_id == blog_id, BloggerPost.blogger_post_id.in_(remote_ids))
            .options(selectinload(BloggerPost.article))
        )
        .scalars()
        .all()
    )
    return {_safe_str(row.blogger_post_id): row for row in rows}


def _apply_article_repair(article: Article | None) -> dict[str, Any] | None:
    if article is None or not _safe_str(article.assembled_html):
        return None
    result = repair_content_h1(article.assembled_html)
    if result.html == article.assembled_html:
        return {
            "article_id": article.id,
            "changed": False,
            "h1_before": result.h1_before,
            "h1_after": result.h1_after,
        }
    article.assembled_html = result.html
    return {
        "article_id": article.id,
        "changed": True,
        "h1_before": result.h1_before,
        "h1_after": result.h1_after,
        "leading_wrappers_removed": result.leading_wrappers_removed,
        "trailing_divs_removed": result.trailing_divs_removed,
        "h1_demoted": result.h1_demoted,
    }


def _base_report(mode: str, blog_id: int) -> dict[str, Any]:
    return {
        "generated_at": _utc_now_iso(),
        "mode": mode,
        "scope": {
            "blog_id": blog_id,
            "profile_key": MYSTERY_PROFILE_KEY,
        },
        "summary": {
            "posts_scanned": 0,
            "posts_planned": 0,
            "posts_updated": 0,
            "posts_failed": 0,
            "content_h1_before_total": 0,
            "content_h1_after_total": 0,
            "leading_wrappers_removed": 0,
            "trailing_divs_removed": 0,
            "h1_demoted": 0,
            "articles_changed": 0,
        },
        "items": [],
    }


def run_dry_run_or_apply(
    db: Session,
    *,
    blog_id: int,
    mode: str,
    sleep_seconds: float,
) -> dict[str, Any]:
    blog = _require_mystery_blog(db, blog_id)
    posts = _load_live_posts(db, blog_id)
    blogger_by_remote = _load_blogger_posts_by_remote(db, blog_id, posts)
    provider = get_blogger_provider(db, blog) if mode == "apply" else None
    report = _base_report(mode, blog_id)
    report["summary"]["posts_scanned"] = len(posts)

    for index, post in enumerate(posts, 1):
        old_html = str(post.content_html or "")
        result = repair_content_h1(old_html)
        changed = result.html != old_html
        item = {
            "synced_post_id": post.id,
            "remote_post_id": _safe_str(post.remote_post_id),
            "url": _safe_str(post.url),
            "title": _safe_str(post.title),
            "status": "planned" if changed else "already_clean",
            "h1_before": result.h1_before,
            "h1_after": result.h1_after,
            "h1_texts_before": _h1_texts(old_html),
            "h1_texts_after": _h1_texts(result.html),
            "leading_wrappers_removed": result.leading_wrappers_removed,
            "trailing_divs_removed": result.trailing_divs_removed,
            "h1_demoted": result.h1_demoted,
        }
        report["summary"]["content_h1_before_total"] += result.h1_before
        report["summary"]["content_h1_after_total"] += result.h1_after
        report["summary"]["leading_wrappers_removed"] += result.leading_wrappers_removed
        report["summary"]["trailing_divs_removed"] += result.trailing_divs_removed
        report["summary"]["h1_demoted"] += result.h1_demoted
        if changed:
            report["summary"]["posts_planned"] += 1

        if mode == "apply" and changed:
            remote_id = _safe_str(post.remote_post_id)
            blogger_post = blogger_by_remote.get(remote_id)
            article = blogger_post.article if blogger_post is not None else None
            title = _safe_str(article.title if article is not None else post.title) or _safe_str(post.title) or "Untitled"
            labels = list(article.labels or []) if article is not None else list(post.labels or [])
            meta_description = _safe_str(article.meta_description if article is not None else "") or _safe_str(post.excerpt_text)
            try:
                if not remote_id:
                    raise RuntimeError("remote_post_id_missing")
                if provider is None or not hasattr(provider, "update_post"):
                    raise RuntimeError("provider_update_post_unavailable")
                provider.update_post(
                    post_id=remote_id,
                    title=title,
                    content=result.html,
                    labels=labels,
                    meta_description=meta_description[:300],
                )
                post.content_html = result.html
                post.synced_at = datetime.now(timezone.utc)
                db.add(post)
                article_result = _apply_article_repair(article)
                if article_result is not None:
                    item["article_repair"] = article_result
                    if article_result.get("changed"):
                        report["summary"]["articles_changed"] += 1
                        db.add(article)
                db.commit()
                report["summary"]["posts_updated"] += 1
                item["status"] = "updated"
                if index % 10 == 0:
                    print(
                        json.dumps(
                            {
                                "progress": index,
                                "updated": report["summary"]["posts_updated"],
                                "failed": report["summary"]["posts_failed"],
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                report["summary"]["posts_failed"] += 1
                item["status"] = "failed"
                item["reason"] = str(exc)
                print(json.dumps({"failed_url": item["url"], "reason": str(exc)}, ensure_ascii=False), flush=True)

        report["items"].append(item)

    return report


def run_verify_live(db: Session, *, blog_id: int, timeout: float) -> dict[str, Any]:
    _require_mystery_blog(db, blog_id)
    posts = _load_live_posts(db, blog_id)
    report = {
        "generated_at": _utc_now_iso(),
        "mode": "verify-live",
        "scope": {
            "blog_id": blog_id,
            "profile_key": MYSTERY_PROFILE_KEY,
        },
        "summary": {
            "posts_scanned": len(posts),
            "live_h1_expected": 1,
            "posts_with_live_h1_not_1": 0,
            "fetch_failed": 0,
        },
        "items": [],
    }
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for post in posts:
            url = _safe_str(post.url).replace("http://", "https://", 1)
            item = {
                "synced_post_id": post.id,
                "url": url,
                "title": _safe_str(post.title),
                "status": "ok",
                "live_h1_count": 0,
                "live_h1_texts": [],
            }
            try:
                response = client.get(url)
                item["status_code"] = response.status_code
                item["content_type"] = response.headers.get("content-type", "")
                response.raise_for_status()
                item["live_h1_count"] = _count_h1(response.text)
                item["live_h1_texts"] = _h1_texts(response.text)
                if item["live_h1_count"] != 1:
                    report["summary"]["posts_with_live_h1_not_1"] += 1
                    item["status"] = "h1_count_mismatch"
            except Exception as exc:  # noqa: BLE001
                report["summary"]["fetch_failed"] += 1
                item["status"] = "fetch_failed"
                item["reason"] = str(exc)
            if item["status"] != "ok":
                report["items"].append(item)
    return report


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    report_path = Path(args.report_path)
    with SessionLocal() as db:
        if args.mode == "verify-live":
            report = run_verify_live(db, blog_id=int(args.blog_id), timeout=float(args.timeout))
        else:
            report = run_dry_run_or_apply(
                db,
                blog_id=int(args.blog_id),
                mode=str(args.mode),
                sleep_seconds=float(args.sleep_seconds),
            )
    _write_report(report_path, report)
    print(json.dumps({"report_path": str(report_path), "summary": report["summary"]}, ensure_ascii=False, indent=2))
    return 0 if int(report["summary"].get("posts_failed", 0) or 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
