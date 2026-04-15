from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, selectinload

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO_ROOT / "storage" / "reports"
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@postgres:5432/bloggent"
DEFAULT_BLOGGER_BLOG_IDS = [34, 35, 36, 37]
LIVE_STATUSES = {"live", "published", "LIVE", "PUBLISHED"}

RELATED_SECTION_RE = re.compile(
    r"<section\b[^>]*class=['\"][^'\"]*related-posts[^'\"]*['\"][^>]*>.*?</section>",
    re.IGNORECASE | re.DOTALL,
)
IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
ONERROR_ATTR_RE = re.compile(
    r"\s+onerror\s*=\s*(?:\".*?\"|'.*?')",
    re.IGNORECASE | re.DOTALL,
)

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get("BLOGGENT_DATABASE_URL", DEFAULT_DATABASE_URL)
if "STORAGE_ROOT" not in os.environ:
    os.environ["STORAGE_ROOT"] = str((REPO_ROOT / "storage").resolve())
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Article, Blog, BloggerPost, SyncedBloggerPost  # noqa: E402
from app.services.providers.factory import get_blogger_provider  # noqa: E402


@dataclass(slots=True)
class CleanupTarget:
    synced_post_id: int
    blog_id: int
    blog_name: str
    blog_slug: str
    remote_post_id: str
    url: str
    title: str
    content_onerror_count: int
    article_id: int | None
    article_onerror_count: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Remove related-posts img onerror attributes from live Blogger posts and republish safely.",
    )
    parser.add_argument("--mode", choices=("dry-run", "apply"), default="dry-run")
    parser.add_argument("--blog-id", action="append", type=int, default=[], help="Target blog id. Repeat for multiple.")
    parser.add_argument("--url", action="append", default=[], help="Target post URL. Repeat for multiple.")
    parser.add_argument("--report-path", default="", help="Optional JSON report path.")
    parser.add_argument("--max-retries", type=int, default=3, help="Deadlock retry count for blog batch commits.")
    parser.add_argument("--backoff-seconds", type=float, default=0.4, help="Initial deadlock retry backoff.")
    return parser.parse_args()


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_blogger_url_key(value: str) -> str:
    raw = _safe_str(value).rstrip("/")
    if not raw:
        return ""
    parsed = urlparse(raw)
    host = _safe_str(parsed.netloc).lower()
    if host.startswith("www."):
        host = host[4:]
    path = unquote(_safe_str(parsed.path)).rstrip("/")
    return f"{host}{path}".lower()


def _is_deadlock_error(exc: Exception) -> bool:
    text = " ".join(
        [
            _safe_str(exc),
            _safe_str(getattr(exc, "orig", "")),
        ]
    ).lower()
    deadlock_tokens = (
        "deadlock detected",
        "deadlock",
        "database is locked",
        "could not serialize access due to concurrent update",
    )
    return any(token in text for token in deadlock_tokens)


def sanitize_related_posts_onerror(html_value: str | None) -> tuple[str, int, int]:
    source = str(html_value or "")
    if not source:
        return source, 0, 0

    removed_count = 0
    section_count = 0

    def replace_img_tag(match: re.Match[str]) -> str:
        nonlocal removed_count
        tag = match.group(0)
        sanitized = ONERROR_ATTR_RE.sub("", tag)
        if sanitized != tag:
            removed_count += 1
        return sanitized

    def replace_related_section(match: re.Match[str]) -> str:
        nonlocal section_count
        section_count += 1
        section_html = match.group(0)
        return IMG_TAG_RE.sub(replace_img_tag, section_html)

    sanitized_html = RELATED_SECTION_RE.sub(replace_related_section, source)
    return sanitized_html, removed_count, section_count


def _init_report(mode: str, *, blog_ids: list[int], urls: list[str], max_retries: int, backoff_seconds: float) -> dict[str, Any]:
    return {
        "generated_at": _utc_now_iso(),
        "mode": mode,
        "filters": {
            "blog_ids": blog_ids,
            "urls": urls,
        },
        "runtime": {
            "max_retries": max_retries,
            "backoff_seconds": backoff_seconds,
        },
        "summary": {
            "scanned": 0,
            "targets": 0,
            "dry_run_only": 0,
            "updated": 0,
            "failed": 0,
            "deadlock_retries": 0,
            "related_onerror_removed": 0,
            "article_onerror_removed": 0,
        },
        "by_blog": {},
        "items": [],
    }


def _ensure_blog_summary(report: dict[str, Any], blog: Blog) -> dict[str, Any]:
    key = str(blog.id)
    bucket = report["by_blog"].get(key)
    if bucket is None:
        bucket = {
            "blog_id": blog.id,
            "blog_name": _safe_str(blog.name),
            "blog_slug": _safe_str(blog.slug),
            "scanned": 0,
            "targets": 0,
            "dry_run_only": 0,
            "updated": 0,
            "failed": 0,
            "deadlock_retries": 0,
            "related_onerror_removed": 0,
            "article_onerror_removed": 0,
        }
        report["by_blog"][key] = bucket
    return bucket


def _collect_targets(
    db: Session,
    *,
    blog_ids: list[int],
    urls: list[str],
    report: dict[str, Any],
) -> list[CleanupTarget]:
    query = (
        select(SyncedBloggerPost)
        .where(
            SyncedBloggerPost.blog_id.in_(blog_ids),
            SyncedBloggerPost.status.in_(sorted(LIVE_STATUSES)),
            SyncedBloggerPost.url.is_not(None),
        )
        .options(selectinload(SyncedBloggerPost.blog))
        .order_by(SyncedBloggerPost.blog_id.asc(), SyncedBloggerPost.id.desc())
    )
    synced_posts = db.execute(query).scalars().all()

    url_filters = {_normalize_blogger_url_key(value) for value in urls if _normalize_blogger_url_key(value)}
    if url_filters:
        synced_posts = [
            row
            for row in synced_posts
            if _normalize_blogger_url_key(_safe_str(row.url)) in url_filters
        ]

    pairs = {
        (row.blog_id, _safe_str(row.remote_post_id))
        for row in synced_posts
        if _safe_str(row.remote_post_id)
    }
    remote_ids = sorted({pair[1] for pair in pairs})
    blogger_posts = (
        db.execute(
            select(BloggerPost)
            .where(
                BloggerPost.blog_id.in_(blog_ids),
                BloggerPost.blogger_post_id.in_(remote_ids) if remote_ids else False,
            )
            .options(selectinload(BloggerPost.article))
        )
        .scalars()
        .all()
        if remote_ids
        else []
    )
    article_by_pair = {
        (row.blog_id, _safe_str(row.blogger_post_id)): row.article
        for row in blogger_posts
    }

    targets: list[CleanupTarget] = []
    for synced in synced_posts:
        blog = synced.blog
        if blog is None:
            continue
        bucket = _ensure_blog_summary(report, blog)
        report["summary"]["scanned"] += 1
        bucket["scanned"] += 1

        sanitized_content, content_onerror_count, _section_count = sanitize_related_posts_onerror(synced.content_html)
        if content_onerror_count <= 0:
            continue

        article = article_by_pair.get((synced.blog_id, _safe_str(synced.remote_post_id)))
        article_onerror_count = 0
        if article is not None and _safe_str(article.assembled_html):
            _sanitized_assembled, article_onerror_count, _ = sanitize_related_posts_onerror(article.assembled_html)

        report["summary"]["targets"] += 1
        bucket["targets"] += 1
        targets.append(
            CleanupTarget(
                synced_post_id=synced.id,
                blog_id=synced.blog_id,
                blog_name=_safe_str(blog.name),
                blog_slug=_safe_str(blog.slug),
                remote_post_id=_safe_str(synced.remote_post_id),
                url=_safe_str(synced.url),
                title=_safe_str(synced.title),
                content_onerror_count=content_onerror_count,
                article_id=article.id if article is not None else None,
                article_onerror_count=article_onerror_count,
            )
        )
    return targets


def _append_report_item(report: dict[str, Any], item: dict[str, Any]) -> None:
    report["items"].append(item)


def _apply_blog_targets(
    db: Session,
    *,
    blog: Blog,
    targets: list[CleanupTarget],
    max_retries: int,
    backoff_seconds: float,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    attempt = 0
    while attempt < max_retries:
        attempt += 1
        try:
            provider = get_blogger_provider(db, blog)
            if not hasattr(provider, "update_post"):
                raise RuntimeError("provider_update_post_unavailable")

            target_ids = [target.synced_post_id for target in targets]
            synced_rows = {
                row.id: row
                for row in db.execute(
                    select(SyncedBloggerPost)
                    .where(SyncedBloggerPost.id.in_(target_ids))
                    .options(selectinload(SyncedBloggerPost.blog))
                )
                .scalars()
                .all()
            }
            remote_post_ids = sorted(
                {
                    _safe_str(row.remote_post_id)
                    for row in synced_rows.values()
                    if _safe_str(row.remote_post_id)
                }
            )
            blogger_rows = (
                db.execute(
                    select(BloggerPost)
                    .where(
                        BloggerPost.blog_id == blog.id,
                        BloggerPost.blogger_post_id.in_(remote_post_ids) if remote_post_ids else False,
                    )
                    .options(selectinload(BloggerPost.article))
                )
                .scalars()
                .all()
                if remote_post_ids
                else []
            )
            blogger_by_remote = {
                _safe_str(row.blogger_post_id): row
                for row in blogger_rows
            }

            updated = 0
            failed = 0
            related_removed = 0
            article_removed = 0
            items: list[dict[str, Any]] = []

            for target in targets:
                synced = synced_rows.get(target.synced_post_id)
                if synced is None:
                    failed += 1
                    items.append(
                        {
                            "blog_id": target.blog_id,
                            "blog_slug": target.blog_slug,
                            "url": target.url,
                            "remote_post_id": target.remote_post_id,
                            "title": target.title,
                            "status": "failed",
                            "reason": "synced_post_missing",
                        }
                    )
                    continue

                sanitized_content, content_removed_count, section_count = sanitize_related_posts_onerror(synced.content_html)
                if content_removed_count <= 0:
                    items.append(
                        {
                            "blog_id": target.blog_id,
                            "blog_slug": target.blog_slug,
                            "url": target.url,
                            "remote_post_id": target.remote_post_id,
                            "title": target.title,
                            "status": "already_clean",
                            "related_sections": section_count,
                            "content_onerror_removed": 0,
                            "article_onerror_removed": 0,
                        }
                    )
                    continue

                blogger_post = blogger_by_remote.get(_safe_str(synced.remote_post_id))
                article = blogger_post.article if blogger_post is not None else None
                article_sanitized = ""
                article_removed_count = 0
                if article is not None and _safe_str(article.assembled_html):
                    article_sanitized, article_removed_count, _ = sanitize_related_posts_onerror(article.assembled_html)

                title = _safe_str(article.title if article is not None else synced.title) or "Untitled"
                labels = list(article.labels or []) if article is not None else list(synced.labels or [])
                meta_description = _safe_str(article.meta_description if article is not None else "") or _safe_str(synced.excerpt_text)
                try:
                    provider.update_post(
                        post_id=_safe_str(synced.remote_post_id),
                        title=title,
                        content=sanitized_content,
                        labels=labels,
                        meta_description=meta_description[:300],
                    )
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    items.append(
                        {
                            "blog_id": target.blog_id,
                            "blog_slug": target.blog_slug,
                            "url": target.url,
                            "remote_post_id": target.remote_post_id,
                            "title": title,
                            "status": "failed",
                            "reason": f"provider_update_failed:{exc}",
                        }
                    )
                    continue

                synced.content_html = sanitized_content
                synced.synced_at = datetime.now(timezone.utc)
                db.add(synced)

                if article is not None and article_removed_count > 0 and article_sanitized != article.assembled_html:
                    article.assembled_html = article_sanitized
                    db.add(article)

                updated += 1
                related_removed += content_removed_count
                article_removed += article_removed_count
                items.append(
                    {
                        "blog_id": target.blog_id,
                        "blog_slug": target.blog_slug,
                        "url": target.url,
                        "remote_post_id": target.remote_post_id,
                        "title": title,
                        "status": "updated",
                        "related_sections": section_count,
                        "content_onerror_removed": content_removed_count,
                        "article_onerror_removed": article_removed_count,
                        "article_id": article.id if article is not None else None,
                    }
                )

            db.commit()
            return items, {
                "updated": updated,
                "failed": failed,
                "related_onerror_removed": related_removed,
                "article_onerror_removed": article_removed,
                "deadlock_retries": attempt - 1,
            }
        except OperationalError as exc:
            db.rollback()
            if _is_deadlock_error(exc) and attempt < max_retries:
                time.sleep(max(backoff_seconds * (2 ** (attempt - 1)), 0.0))
                continue
            raise
        except Exception:
            db.rollback()
            raise

    raise RuntimeError("deadlock_retry_exhausted")


def run_cleanup(
    db: Session,
    *,
    mode: str,
    blog_ids: list[int] | None = None,
    urls: list[str] | None = None,
    max_retries: int = 3,
    backoff_seconds: float = 0.4,
) -> dict[str, Any]:
    normalized_blog_ids = sorted({int(value) for value in (blog_ids or []) if int(value) > 0})
    if not normalized_blog_ids:
        normalized_blog_ids = DEFAULT_BLOGGER_BLOG_IDS.copy()
    normalized_urls = [_safe_str(value) for value in (urls or []) if _safe_str(value)]
    normalized_max_retries = max(int(max_retries), 1)
    normalized_backoff = max(float(backoff_seconds), 0.0)

    report = _init_report(
        mode,
        blog_ids=normalized_blog_ids,
        urls=normalized_urls,
        max_retries=normalized_max_retries,
        backoff_seconds=normalized_backoff,
    )
    targets = _collect_targets(
        db,
        blog_ids=normalized_blog_ids,
        urls=normalized_urls,
        report=report,
    )
    grouped: dict[int, list[CleanupTarget]] = defaultdict(list)
    for target in targets:
        grouped[target.blog_id].append(target)

    for blog_id in sorted(grouped.keys()):
        blog = db.get(Blog, blog_id)
        if blog is None:
            for target in grouped[blog_id]:
                report["summary"]["failed"] += 1
                _append_report_item(
                    report,
                    {
                        "blog_id": target.blog_id,
                        "blog_slug": target.blog_slug,
                        "url": target.url,
                        "remote_post_id": target.remote_post_id,
                        "title": target.title,
                        "status": "failed",
                        "reason": "blog_missing",
                    },
                )
            continue

        blog_bucket = _ensure_blog_summary(report, blog)
        blog_targets = sorted(grouped[blog_id], key=lambda item: (item.url, item.remote_post_id))

        if mode == "dry-run":
            for target in blog_targets:
                report["summary"]["dry_run_only"] += 1
                report["summary"]["related_onerror_removed"] += target.content_onerror_count
                report["summary"]["article_onerror_removed"] += target.article_onerror_count
                blog_bucket["dry_run_only"] += 1
                blog_bucket["related_onerror_removed"] += target.content_onerror_count
                blog_bucket["article_onerror_removed"] += target.article_onerror_count
                _append_report_item(
                    report,
                    {
                        "blog_id": target.blog_id,
                        "blog_slug": target.blog_slug,
                        "url": target.url,
                        "remote_post_id": target.remote_post_id,
                        "title": target.title,
                        "status": "needs_cleanup",
                        "content_onerror_removed": target.content_onerror_count,
                        "article_onerror_removed": target.article_onerror_count,
                        "article_id": target.article_id,
                    },
                )
            continue

        try:
            items, stats = _apply_blog_targets(
                db,
                blog=blog,
                targets=blog_targets,
                max_retries=normalized_max_retries,
                backoff_seconds=normalized_backoff,
            )
            for item in items:
                _append_report_item(report, item)
            report["summary"]["updated"] += int(stats.get("updated", 0))
            report["summary"]["failed"] += int(stats.get("failed", 0))
            report["summary"]["deadlock_retries"] += int(stats.get("deadlock_retries", 0))
            report["summary"]["related_onerror_removed"] += int(stats.get("related_onerror_removed", 0))
            report["summary"]["article_onerror_removed"] += int(stats.get("article_onerror_removed", 0))

            blog_bucket["updated"] += int(stats.get("updated", 0))
            blog_bucket["failed"] += int(stats.get("failed", 0))
            blog_bucket["deadlock_retries"] += int(stats.get("deadlock_retries", 0))
            blog_bucket["related_onerror_removed"] += int(stats.get("related_onerror_removed", 0))
            blog_bucket["article_onerror_removed"] += int(stats.get("article_onerror_removed", 0))
        except Exception as exc:  # noqa: BLE001
            report["summary"]["failed"] += len(blog_targets)
            blog_bucket["failed"] += len(blog_targets)
            for target in blog_targets:
                _append_report_item(
                    report,
                    {
                        "blog_id": target.blog_id,
                        "blog_slug": target.blog_slug,
                        "url": target.url,
                        "remote_post_id": target.remote_post_id,
                        "title": target.title,
                        "status": "failed",
                        "reason": f"blog_batch_failed:{exc}",
                    },
                )

    report["items"].sort(key=lambda row: (_safe_str(row.get("blog_slug")), _safe_str(row.get("url"))))
    report["by_blog"] = [
        report["by_blog"][key]
        for key in sorted(report["by_blog"].keys(), key=lambda value: int(value))
    ]
    return report


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    report_path = Path(args.report_path) if _safe_str(args.report_path) else REPORT_DIR / f"cleanup-blogger-related-onerror-{_timestamp()}.json"
    with SessionLocal() as db:
        report = run_cleanup(
            db,
            mode=args.mode,
            blog_ids=list(args.blog_id or []),
            urls=list(args.url or []),
            max_retries=int(args.max_retries),
            backoff_seconds=float(args.backoff_seconds),
        )
    _write_json(report_path, report)
    print(json.dumps({"report_path": str(report_path), "summary": report["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
