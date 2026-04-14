from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session, selectinload


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
STORAGE_ROOT = REPO_ROOT / "storage"
REPORT_ROOT = STORAGE_ROOT / "reports"
RUNTIME_ENV_PATH = REPO_ROOT / "env" / "runtime.settings.env"
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"
KST = ZoneInfo("Asia/Seoul")
HREF_RE = re.compile(r"<a\b[^>]*\bhref=['\"]([^'\"]+)['\"]", re.IGNORECASE)
RELATED_POSTS_BLOCK_RE = re.compile(
    r"<(?P<tag>section|div|aside)\b[^>]*class=['\"][^'\"]*related-posts[^'\"]*['\"][^>]*>.*?</(?P=tag)>",
    re.IGNORECASE | re.DOTALL,
)
ONERROR_ATTR_RE = re.compile(
    r"\bonerror\s*=\s*(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
    re.IGNORECASE | re.DOTALL,
)


def _load_runtime_env(path: Path) -> None:
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:  # noqa: BLE001
        return
    for raw_line in lines:
        line = str(raw_line or "").strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and ((value.startswith("'") and value.endswith("'")) or (value.startswith('"') and value.endswith('"'))):
            value = value[1:-1]
        os.environ[key] = value


_load_runtime_env(RUNTIME_ENV_PATH)

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get("BLOGGENT_DATABASE_URL", DEFAULT_DATABASE_URL)
if "STORAGE_ROOT" not in os.environ:
    os.environ["STORAGE_ROOT"] = str(STORAGE_ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import (  # noqa: E402
    AIUsageEvent,
    AnalyticsArticleFact,
    Article,
    AuditLog,
    Blog,
    BloggerPost,
    Job,
    PostStatus,
    PublishQueueItem,
    SyncedBloggerPost,
)
from app.services.blogger.blogger_sync_service import sync_blogger_posts_for_blog  # noqa: E402
from app.services.platform.publishing_service import rebuild_article_html, upsert_article_blogger_post  # noqa: E402
from app.services.providers.factory import get_blogger_provider  # noqa: E402


@dataclass(slots=True)
class StalePostCandidate:
    blog_id: int
    blog_name: str
    article_id: int | None
    job_id: int | None
    blogger_post_row_id: int
    blogger_post_id: str
    status: str
    title: str
    slug: str
    published_url: str
    normalized_url_key: str


@dataclass(slots=True)
class RelatedIssue:
    article_id: int
    title: str
    slug: str
    published_url: str
    related_link_count: int
    missing_keys: list[str]


@dataclass(slots=True)
class PngRelatedCandidate:
    article_id: int
    title: str
    slug: str
    published_url: str
    fallback_png_token_count: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sync travel Blogger blogs with live posts, hard-delete stale generated rows, "
            "and rebuild related posts in article HTML."
        )
    )
    parser.add_argument("--profile-key", default="korea_travel", help="Target blog profile key.")
    parser.add_argument(
        "--date",
        default=datetime.now(KST).date().isoformat(),
        help="Execution date (YYYY-MM-DD) used in report metadata.",
    )
    parser.add_argument("--execute", action="store_true", help="Apply DB/live mutations.")
    parser.add_argument("--sync-blogger", action="store_true", help="Push rebuilt related HTML to Blogger.")
    parser.add_argument("--report-prefix", default="travel-live-prune", help="Report filename prefix.")
    parser.add_argument(
        "--max-issue-examples",
        type=int,
        default=50,
        help="Max number of issue examples to include per blog.",
    )
    return parser.parse_args()


def now_kst_iso() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def report_stamp() -> str:
    return datetime.now(KST).strftime("%Y%m%d-%H%M%S")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=lambda value: value.isoformat() if hasattr(value, "isoformat") else str(value),
        ),
        encoding="utf-8",
    )


def normalize_blogger_url_key(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    host = (parsed.netloc or "").strip().lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return ""
    path = unquote(parsed.path or "/").strip() or "/"
    path = re.sub(r"/+", "/", path)
    if path != "/":
        path = path.rstrip("/")
    return f"{host}{path}"


def is_stale_published_url(published_url: str | None, live_url_keys: set[str]) -> bool:
    key = normalize_blogger_url_key(published_url)
    if not key:
        return False
    return key not in live_url_keys


def _extract_related_link_keys(html_text: str | None) -> list[str]:
    text = str(html_text or "")
    marker = text.lower().find("related-posts")
    if marker < 0:
        return []
    block = text[marker:]
    keys: list[str] = []
    seen: set[str] = set()
    for href in HREF_RE.findall(block):
        key = normalize_blogger_url_key(href)
        if not key or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return keys


def _extract_related_blocks(html_text: str | None) -> list[str]:
    text = str(html_text or "")
    if not text:
        return []
    return [match.group(0) for match in RELATED_POSTS_BLOCK_RE.finditer(text)]


def count_related_png_fallback_tokens(html_text: str | None) -> int:
    count = 0
    for block in _extract_related_blocks(html_text):
        for match in ONERROR_ATTR_RE.finditer(block):
            value = str(match.group("value") or "").lower()
            if ".png" not in value:
                continue
            count += value.count(".png")
    return count


def _load_target_blogs(db: Session, profile_key: str) -> list[Blog]:
    return (
        db.execute(
            select(Blog)
            .where(
                Blog.profile_key == profile_key,
                Blog.content_category == "travel",
                Blog.is_active.is_(True),
                or_(Blog.blogger_blog_id.is_not(None), Blog.blogger_url.is_not(None)),
            )
            .order_by(Blog.id.asc())
        )
        .scalars()
        .all()
    )


def _load_live_url_keys(db: Session, blog_id: int) -> set[str]:
    rows = db.execute(select(SyncedBloggerPost.url).where(SyncedBloggerPost.blog_id == blog_id)).all()
    keys: set[str] = set()
    for row in rows:
        key = normalize_blogger_url_key(row[0] if row else "")
        if key:
            keys.add(key)
    return keys


def _load_article_rows(db: Session, blog_id: int) -> list[Article]:
    return (
        db.execute(
            select(Article)
            .join(BloggerPost, BloggerPost.article_id == Article.id)
            .where(
                Article.blog_id == blog_id,
                BloggerPost.post_status.in_([PostStatus.PUBLISHED, PostStatus.SCHEDULED]),
            )
            .options(
                selectinload(Article.blog),
                selectinload(Article.image),
                selectinload(Article.blogger_post),
            )
            .order_by(Article.id.asc())
        )
        .scalars()
        .all()
    )


def _collect_stale_candidates(blog: Blog, articles: list[Article], live_url_keys: set[str]) -> list[StalePostCandidate]:
    candidates: list[StalePostCandidate] = []
    for article in articles:
        post = article.blogger_post
        if post is None:
            continue
        normalized_key = normalize_blogger_url_key(post.published_url)
        if not normalized_key:
            continue
        if normalized_key in live_url_keys:
            continue
        candidates.append(
            StalePostCandidate(
                blog_id=blog.id,
                blog_name=blog.name,
                article_id=article.id,
                job_id=post.job_id,
                blogger_post_row_id=post.id,
                blogger_post_id=post.blogger_post_id,
                status=post.post_status.value if hasattr(post.post_status, "value") else str(post.post_status),
                title=article.title,
                slug=article.slug,
                published_url=post.published_url,
                normalized_url_key=normalized_key,
            )
        )
    return candidates


def _scan_related_issues(articles: list[Article], live_url_keys: set[str]) -> dict[str, Any]:
    issues: list[RelatedIssue] = []
    article_with_related = 0
    total_related_links = 0

    for article in articles:
        post = article.blogger_post
        if post is None:
            continue
        html_value = article.assembled_html or article.html_article or ""
        related_keys = _extract_related_link_keys(html_value)
        if not related_keys:
            continue
        article_with_related += 1
        total_related_links += len(related_keys)
        missing = sorted([key for key in related_keys if key not in live_url_keys])
        if not missing:
            continue
        issues.append(
            RelatedIssue(
                article_id=article.id,
                title=article.title,
                slug=article.slug,
                published_url=post.published_url,
                related_link_count=len(related_keys),
                missing_keys=missing,
            )
        )

    return {
        "checked_article_count": len(articles),
        "article_with_related_count": article_with_related,
        "related_link_count": total_related_links,
        "missing_article_count": len(issues),
        "missing_link_count": sum(len(item.missing_keys) for item in issues),
        "issues": issues,
    }


def _scan_related_png_fallbacks(articles: list[Article]) -> dict[str, Any]:
    issues: list[PngRelatedCandidate] = []
    total_token_count = 0

    for article in articles:
        post = article.blogger_post
        if post is None:
            continue
        html_value = article.assembled_html or article.html_article or ""
        token_count = count_related_png_fallback_tokens(html_value)
        if token_count <= 0:
            continue
        total_token_count += token_count
        issues.append(
            PngRelatedCandidate(
                article_id=article.id,
                title=article.title,
                slug=article.slug,
                published_url=post.published_url,
                fallback_png_token_count=token_count,
            )
        )

    return {
        "checked_article_count": len(articles),
        "candidate_count": len(issues),
        "token_count": total_token_count,
        "issues": issues,
    }


def _hard_delete_stale_candidates(db: Session, candidates: list[StalePostCandidate]) -> dict[str, int]:
    if not candidates:
        return {
            "candidate_count": 0,
            "job_delete_count": 0,
            "orphan_article_delete_count": 0,
            "orphan_blogger_post_delete_count": 0,
            "analytics_fact_delete_count": 0,
        }

    article_ids = {item.article_id for item in candidates if item.article_id is not None}
    job_ids = {item.job_id for item in candidates if item.job_id is not None}
    article_ids_linked_to_job = {
        item.article_id for item in candidates if item.article_id is not None and item.job_id is not None
    }
    orphan_article_ids = sorted(article_ids - article_ids_linked_to_job)
    orphan_blogger_post_ids = sorted({item.blogger_post_row_id for item in candidates if item.job_id is None})

    analytics_fact_delete_count = 0
    if article_ids:
        analytics_fact_delete_count = int(
            db.execute(delete(AnalyticsArticleFact).where(AnalyticsArticleFact.article_id.in_(list(article_ids)))).rowcount
            or 0
        )
        db.execute(delete(PublishQueueItem).where(PublishQueueItem.article_id.in_(list(article_ids))))
        db.execute(delete(AIUsageEvent).where(AIUsageEvent.article_id.in_(list(article_ids))))

    if job_ids:
        db.execute(delete(AuditLog).where(AuditLog.job_id.in_(list(job_ids))))
        db.execute(delete(AIUsageEvent).where(AIUsageEvent.job_id.in_(list(job_ids))))
        db.execute(delete(Job).where(Job.id.in_(list(job_ids))))

    if orphan_article_ids:
        db.execute(delete(Article).where(Article.id.in_(orphan_article_ids)))

    if orphan_blogger_post_ids:
        db.execute(delete(BloggerPost).where(BloggerPost.id.in_(orphan_blogger_post_ids)))

    return {
        "candidate_count": len(candidates),
        "job_delete_count": len(job_ids),
        "orphan_article_delete_count": len(orphan_article_ids),
        "orphan_blogger_post_delete_count": len(orphan_blogger_post_ids),
        "analytics_fact_delete_count": analytics_fact_delete_count,
    }


def _rebuild_related_for_article(db: Session, article: Article, *, sync_blogger: bool) -> tuple[str, str]:
    hero_image_url = article.image.public_url if article.image else ""
    rebuilt_html = rebuild_article_html(db, article, hero_image_url)

    if not sync_blogger:
        return rebuilt_html, "skip:no-sync-flag"

    post = article.blogger_post
    if post is None or article.blog is None:
        return rebuilt_html, "skip:no-linked-post"

    provider = get_blogger_provider(db, article.blog)
    if not hasattr(provider, "update_post") or type(provider).__name__.startswith("Mock"):
        return rebuilt_html, "skip:update-unavailable"

    summary, raw_payload = provider.update_post(
        post_id=post.blogger_post_id,
        title=article.title,
        content=rebuilt_html,
        labels=list(article.labels or []),
        meta_description=article.meta_description or "",
    )
    upsert_article_blogger_post(
        db,
        article=article,
        summary=summary,
        raw_payload=raw_payload if isinstance(raw_payload, dict) else {},
    )
    return rebuilt_html, "updated"


def _to_report_issue_payload(
    issues: list[RelatedIssue], *, max_issue_examples: int
) -> list[dict[str, Any]]:
    return [asdict(item) for item in issues[: max(1, max_issue_examples)]]


def _to_report_png_payload(
    issues: list[PngRelatedCandidate], *, max_issue_examples: int
) -> list[dict[str, Any]]:
    return [asdict(item) for item in issues[: max(1, max_issue_examples)]]


def run(args: argparse.Namespace) -> dict[str, Any]:
    stamp = report_stamp()
    before_report_path = REPORT_ROOT / f"{args.report_prefix}-{stamp}-before.json"
    after_report_path = REPORT_ROOT / f"{args.report_prefix}-{stamp}-after.json"

    contexts: list[dict[str, Any]] = []
    run_started_at = now_kst_iso()

    with SessionLocal() as db:
        blogs = _load_target_blogs(db, args.profile_key)
        for blog in blogs:
            context: dict[str, Any] = {
                "blog_id": blog.id,
                "blog_name": blog.name,
                "primary_language": blog.primary_language,
                "sync_result": {},
                "sync_error": "",
                "resync_result": {},
                "resync_error": "",
                "live_url_count": 0,
                "article_count": 0,
                "stale_candidates": [],
                "delete_result": {},
                "delete_error": "",
                "related_before": {},
                "related_after": {},
                "related_rebuilt_count": 0,
                "related_sync_updated_count": 0,
                "related_rebuild_errors": [],
                "png_related_before": {},
                "png_related_after": {},
                "png_related_cleaned_count": 0,
                "png_related_sync_updated_count": 0,
                "png_related_cleanup_errors": [],
            }
            try:
                context["sync_result"] = sync_blogger_posts_for_blog(db, blog)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                context["sync_error"] = str(exc)
                contexts.append(context)
                continue

            live_keys = _load_live_url_keys(db, blog.id)
            articles = _load_article_rows(db, blog.id)
            stale_candidates = _collect_stale_candidates(blog, articles, live_keys)
            related_before = _scan_related_issues(articles, live_keys)
            png_related_before = _scan_related_png_fallbacks(articles)

            context["live_url_count"] = len(live_keys)
            context["article_count"] = len(articles)
            context["stale_candidates"] = stale_candidates
            context["related_before"] = related_before
            context["png_related_before"] = png_related_before
            contexts.append(context)

        before_payload = {
            "run_started_at_kst": run_started_at,
            "run_mode": "execute" if args.execute else "dry-run",
            "profile_key": args.profile_key,
            "execution_date": args.date,
            "sync_blogger": bool(args.sync_blogger),
            "blog_count": len(contexts),
            "blogs": [],
        }
        for context in contexts:
            issues_before = context.get("related_before", {}).get("issues", [])
            png_issues_before = context.get("png_related_before", {}).get("issues", [])
            before_payload["blogs"].append(
                {
                    "blog_id": context["blog_id"],
                    "blog_name": context["blog_name"],
                    "primary_language": context["primary_language"],
                    "sync_result": context["sync_result"],
                    "sync_error": context["sync_error"],
                    "live_url_count": context["live_url_count"],
                    "article_count": context["article_count"],
                    "stale_candidate_count": len(context["stale_candidates"]),
                    "stale_candidates": [asdict(item) for item in context["stale_candidates"]],
                    "related_before": {
                        **{
                            key: value
                            for key, value in (context.get("related_before") or {}).items()
                            if key != "issues"
                        },
                        "issues": _to_report_issue_payload(issues_before, max_issue_examples=args.max_issue_examples),
                    },
                    "png_related_candidate_count": int(context.get("png_related_before", {}).get("candidate_count") or 0),
                    "png_related_token_count": int(context.get("png_related_before", {}).get("token_count") or 0),
                    "png_related_examples": _to_report_png_payload(
                        png_issues_before,
                        max_issue_examples=args.max_issue_examples,
                    ),
                }
            )
        before_payload["total_stale_candidate_count"] = sum(
            len(context["stale_candidates"]) for context in contexts
        )
        before_payload["total_related_missing_link_count"] = sum(
            int(context.get("related_before", {}).get("missing_link_count") or 0) for context in contexts
        )
        before_payload["total_png_related_candidate_count"] = sum(
            int(context.get("png_related_before", {}).get("candidate_count") or 0) for context in contexts
        )
        before_payload["total_png_related_token_count"] = sum(
            int(context.get("png_related_before", {}).get("token_count") or 0) for context in contexts
        )
        write_json(before_report_path, before_payload)

        if args.execute:
            for context in contexts:
                if context["sync_error"]:
                    continue
                blog_id = int(context["blog_id"])
                blog = db.get(Blog, blog_id)
                if blog is None:
                    context["delete_error"] = "blog_not_found_after_sync"
                    continue

                png_cleaned_count = 0
                png_sync_updated_count = 0
                png_cleanup_errors: list[dict[str, Any]] = []

                png_issue_items = context.get("png_related_before", {}).get("issues", [])
                png_candidate_ids = sorted({item.article_id for item in png_issue_items})
                if png_candidate_ids:
                    article_map = {item.id: item for item in _load_article_rows(db, blog_id)}
                    for article_id in png_candidate_ids:
                        article = article_map.get(article_id)
                        if article is None or article.blogger_post is None:
                            continue
                        html_before = article.assembled_html or article.html_article or ""
                        if count_related_png_fallback_tokens(html_before) <= 0:
                            continue
                        try:
                            _rebuilt_html, sync_status = _rebuild_related_for_article(
                                db,
                                article,
                                sync_blogger=args.sync_blogger,
                            )
                            html_after = article.assembled_html or article.html_article or ""
                            if count_related_png_fallback_tokens(html_after) == 0:
                                png_cleaned_count += 1
                            if sync_status == "updated":
                                png_sync_updated_count += 1
                        except Exception as exc:  # noqa: BLE001
                            db.rollback()
                            png_cleanup_errors.append(
                                {
                                    "article_id": article.id,
                                    "title": article.title,
                                    "published_url": article.blogger_post.published_url,
                                    "error": str(exc),
                                }
                            )

                context["png_related_cleaned_count"] = png_cleaned_count
                context["png_related_sync_updated_count"] = png_sync_updated_count
                context["png_related_cleanup_errors"] = png_cleanup_errors

                try:
                    context["resync_result"] = sync_blogger_posts_for_blog(db, blog)
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    context["resync_error"] = str(exc)

                live_keys = _load_live_url_keys(db, blog_id)
                current_articles = _load_article_rows(db, blog_id)
                context["stale_candidates"] = _collect_stale_candidates(blog, current_articles, live_keys)

                try:
                    context["delete_result"] = _hard_delete_stale_candidates(
                        db,
                        context["stale_candidates"],
                    )
                    db.commit()
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    context["delete_error"] = str(exc)
                    continue

                live_keys_after_delete = _load_live_url_keys(db, blog_id)
                remaining_articles = _load_article_rows(db, blog_id)
                context["live_url_count"] = len(live_keys_after_delete)
                context["article_count"] = len(remaining_articles)

                rebuild_count = 0
                sync_updated_count = 0
                rebuild_errors: list[dict[str, Any]] = []

                for article in remaining_articles:
                    post = article.blogger_post
                    if post is None:
                        continue
                    html_before = article.assembled_html or article.html_article or ""
                    missing_before = sorted(
                        [key for key in _extract_related_link_keys(html_before) if key not in live_keys_after_delete]
                    )
                    if not missing_before:
                        continue
                    try:
                        rebuilt_html, sync_status = _rebuild_related_for_article(
                            db,
                            article,
                            sync_blogger=args.sync_blogger,
                        )
                        rebuild_count += 1
                        if sync_status == "updated":
                            sync_updated_count += 1
                        _ = rebuilt_html
                    except Exception as exc:  # noqa: BLE001
                        db.rollback()
                        rebuild_errors.append(
                            {
                                "article_id": article.id,
                                "title": article.title,
                                "published_url": post.published_url,
                                "error": str(exc),
                            }
                        )

                related_after_articles = _load_article_rows(db, blog_id)
                related_after = _scan_related_issues(related_after_articles, live_keys_after_delete)
                png_related_after = _scan_related_png_fallbacks(related_after_articles)
                context["related_after"] = related_after
                context["related_rebuilt_count"] = rebuild_count
                context["related_sync_updated_count"] = sync_updated_count
                context["related_rebuild_errors"] = rebuild_errors
                context["png_related_after"] = png_related_after
        else:
            for context in contexts:
                context["related_after"] = context.get("related_before", {})
                context["png_related_after"] = context.get("png_related_before", {})
                context["delete_result"] = {
                    "candidate_count": len(context["stale_candidates"]),
                    "job_delete_count": 0,
                    "orphan_article_delete_count": 0,
                    "orphan_blogger_post_delete_count": 0,
                    "analytics_fact_delete_count": 0,
                }
                context["related_rebuilt_count"] = 0
                context["related_sync_updated_count"] = 0
                context["related_rebuild_errors"] = []
                context["png_related_cleaned_count"] = 0
                context["png_related_sync_updated_count"] = 0
                context["png_related_cleanup_errors"] = []

    after_payload = {
        "run_started_at_kst": run_started_at,
        "run_finished_at_kst": now_kst_iso(),
        "run_mode": "execute" if args.execute else "dry-run",
        "profile_key": args.profile_key,
        "execution_date": args.date,
        "sync_blogger": bool(args.sync_blogger),
        "before_report_path": str(before_report_path),
        "blog_count": len(contexts),
        "blogs": [],
    }
    for context in contexts:
        issues_after = context.get("related_after", {}).get("issues", [])
        png_issues_after = context.get("png_related_after", {}).get("issues", [])
        after_payload["blogs"].append(
            {
                "blog_id": context["blog_id"],
                "blog_name": context["blog_name"],
                "primary_language": context["primary_language"],
                "sync_result": context["sync_result"],
                "sync_error": context["sync_error"],
                "resync_result": context["resync_result"],
                "resync_error": context["resync_error"],
                "stale_candidate_count": len(context["stale_candidates"]),
                "delete_result": context["delete_result"],
                "delete_error": context["delete_error"],
                "related_before": {
                    key: value
                    for key, value in (context.get("related_before") or {}).items()
                    if key != "issues"
                },
                "related_after": {
                    **{
                        key: value
                        for key, value in (context.get("related_after") or {}).items()
                        if key != "issues"
                    },
                    "issues": _to_report_issue_payload(issues_after, max_issue_examples=args.max_issue_examples),
                },
                "related_rebuilt_count": context["related_rebuilt_count"],
                "related_sync_updated_count": context["related_sync_updated_count"],
                "related_rebuild_error_count": len(context["related_rebuild_errors"]),
                "related_rebuild_errors": context["related_rebuild_errors"][: max(1, args.max_issue_examples)],
                "png_related_candidate_count": int(context.get("png_related_before", {}).get("candidate_count") or 0),
                "png_related_cleaned_count": int(context.get("png_related_cleaned_count") or 0),
                "png_related_remaining_count": int(context.get("png_related_after", {}).get("candidate_count") or 0),
                "png_related_examples": _to_report_png_payload(
                    png_issues_after,
                    max_issue_examples=args.max_issue_examples,
                ),
                "png_related_cleanup_error_count": len(context["png_related_cleanup_errors"]),
                "png_related_cleanup_errors": context["png_related_cleanup_errors"][: max(1, args.max_issue_examples)],
            }
        )

    after_payload["totals"] = {
        "stale_candidate_count": sum(len(context["stale_candidates"]) for context in contexts),
        "deleted_job_count": sum(int(context.get("delete_result", {}).get("job_delete_count") or 0) for context in contexts),
        "deleted_orphan_article_count": sum(
            int(context.get("delete_result", {}).get("orphan_article_delete_count") or 0) for context in contexts
        ),
        "deleted_orphan_blogger_post_count": sum(
            int(context.get("delete_result", {}).get("orphan_blogger_post_delete_count") or 0) for context in contexts
        ),
        "deleted_analytics_fact_count": sum(
            int(context.get("delete_result", {}).get("analytics_fact_delete_count") or 0) for context in contexts
        ),
        "related_missing_link_count_before": sum(
            int(context.get("related_before", {}).get("missing_link_count") or 0) for context in contexts
        ),
        "related_missing_link_count_after": sum(
            int(context.get("related_after", {}).get("missing_link_count") or 0) for context in contexts
        ),
        "related_rebuilt_count": sum(int(context.get("related_rebuilt_count") or 0) for context in contexts),
        "related_sync_updated_count": sum(int(context.get("related_sync_updated_count") or 0) for context in contexts),
        "png_related_candidate_count": sum(
            int(context.get("png_related_before", {}).get("candidate_count") or 0) for context in contexts
        ),
        "png_related_cleaned_count": sum(int(context.get("png_related_cleaned_count") or 0) for context in contexts),
        "png_related_remaining_count": sum(
            int(context.get("png_related_after", {}).get("candidate_count") or 0) for context in contexts
        ),
        "png_related_sync_updated_count": sum(
            int(context.get("png_related_sync_updated_count") or 0) for context in contexts
        ),
    }

    write_json(after_report_path, after_payload)
    return {
        "before_report_path": str(before_report_path),
        "after_report_path": str(after_report_path),
        "summary": after_payload["totals"],
        "run_mode": after_payload["run_mode"],
        "blog_count": after_payload["blog_count"],
    }


def main() -> int:
    args = parse_args()
    if args.sync_blogger and not args.execute:
        print(json.dumps({"warning": "--sync-blogger is ignored without --execute"}, ensure_ascii=False))

    result = run(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
