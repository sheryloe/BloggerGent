from __future__ import annotations

import html
import httpx
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.entities import Blog, SyncedBloggerPost
from app.services.blogger_live_audit_service import fetch_and_audit_blogger_post
from app.services.blogger_oauth_service import BloggerOAuthError, authorized_google_request
from app.services.topic_guard_service import rebuild_topic_memories_for_blog

BLOGGER_POSTS_URL = "https://www.googleapis.com/blogger/v3/blogs/{blog_id}/posts"
BLOGGER_PUBLIC_FEED_PATH = "/feeds/posts/default"
BLOGGER_PUBLIC_FEED_MAX_RESULTS = 500

logger = logging.getLogger(__name__)
IMAGE_SRC_PATTERN = re.compile(r"<img\b[^>]*\bsrc=['\"]([^'\"]+)['\"]", re.IGNORECASE)
META_DESCRIPTION_PATTERN = re.compile(r"data-bloggent-meta-description=['\"]([^'\"]+)['\"]", re.IGNORECASE)
PARAGRAPH_PATTERN = re.compile(r"<p\b[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
WHITESPACE_PATTERN = re.compile(r"\s+")
PUBLIC_FEED_POST_ID_PATTERN = re.compile(r"post-(\d+)")
MAX_EXCERPT_LENGTH = 480


def _parse_google_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _error_detail(response) -> str:
    detail = response.text
    try:
        payload = response.json()
    except ValueError:
        return detail

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return error.get("message", detail)
        if isinstance(error, str):
            return error
    return detail


def _raise_sync_error(response, message: str) -> None:
    raise BloggerOAuthError(message, detail=_error_detail(response), status_code=response.status_code)


def _extract_thumbnail_url(content_html: str) -> str | None:
    match = IMAGE_SRC_PATTERN.search(content_html or "")
    if not match:
        return None
    candidate = html.unescape(match.group(1).strip())
    return candidate or None


def _plain_text(value: str) -> str:
    collapsed = HTML_TAG_PATTERN.sub(" ", value or "")
    unescaped = html.unescape(collapsed)
    cleaned = WHITESPACE_PATTERN.sub(" ", unescaped).strip()
    if len(cleaned) <= MAX_EXCERPT_LENGTH:
        return cleaned
    shortened = cleaned[: MAX_EXCERPT_LENGTH + 1]
    trimmed = shortened.rsplit(" ", 1)[0].strip() or shortened[:MAX_EXCERPT_LENGTH].strip()
    return trimmed.rstrip(" ,.;:-") + "..."


def _extract_excerpt_text(content_html: str) -> str:
    meta_match = META_DESCRIPTION_PATTERN.search(content_html or "")
    if meta_match:
        excerpt = _plain_text(meta_match.group(1))
        if excerpt:
            return excerpt

    paragraphs: list[str] = []
    for match in PARAGRAPH_PATTERN.finditer(content_html or ""):
        paragraph_text = _plain_text(match.group(1))
        if not paragraph_text:
            continue
        if paragraph_text in paragraphs:
            continue
        paragraphs.append(paragraph_text)
        if len(" ".join(paragraphs)) >= MAX_EXCERPT_LENGTH:
            break
    if paragraphs:
        return _plain_text(paragraphs[0])

    return _plain_text(content_html)


def _normalize_remote_post(item: dict) -> dict:
    labels = item.get("labels", []) or []
    if not isinstance(labels, list):
        labels = []
    replies = item.get("replies", {}) if isinstance(item.get("replies"), dict) else {}
    author = item.get("author", {}) if isinstance(item.get("author"), dict) else {}
    content_html = str(item.get("content", "") or "")
    return {
        "remote_post_id": str(item.get("id", "")).strip(),
        "title": str(item.get("title", "")).strip() or "Untitled",
        "url": str(item.get("url", "")).strip() or None,
        "status": str(item.get("status", "")).strip() or "live",
        "published_at": _parse_google_datetime(item.get("published")),
        "updated_at_remote": _parse_google_datetime(item.get("updated")),
        "labels": [str(label).strip() for label in labels if str(label).strip()],
        "author_display_name": str(author.get("displayName", "")).strip() or None,
        "replies_total_items": int(replies.get("totalItems", 0) or 0) if replies else 0,
        "content_html": content_html,
        "thumbnail_url": _extract_thumbnail_url(content_html),
        "excerpt_text": _extract_excerpt_text(content_html),
    }


def _build_public_feed_url(blog_url: str) -> str:
    parsed = urlsplit(str(blog_url or "").strip())
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc or parsed.path
    if not netloc:
        raise ValueError("Blogger public URL is missing.")
    return urlunsplit((scheme, netloc, BLOGGER_PUBLIC_FEED_PATH, "", ""))


def _feed_text(value) -> str:
    if isinstance(value, dict):
        return str(value.get("$t") or "").strip()
    return str(value or "").strip()


def _extract_public_feed_post_id(entry: dict) -> str:
    raw_id = _feed_text(entry.get("id"))
    if raw_id:
        match = PUBLIC_FEED_POST_ID_PATTERN.search(raw_id)
        if match:
            return match.group(1)
    alternate = _extract_public_feed_url(entry)
    return alternate or raw_id


def _extract_public_feed_url(entry: dict) -> str | None:
    for link in entry.get("link", []) or []:
        if not isinstance(link, dict):
            continue
        if str(link.get("rel") or "").strip().lower() == "alternate":
            href = str(link.get("href") or "").strip()
            if href:
                return href
    return None


def _normalize_public_feed_post(entry: dict) -> dict:
    author = {}
    if isinstance(entry.get("author"), list) and entry["author"]:
        author = entry["author"][0] if isinstance(entry["author"][0], dict) else {}
    content_html = _feed_text(entry.get("content")) or _feed_text(entry.get("summary"))
    labels = [
        str(item.get("term") or "").strip()
        for item in (entry.get("category") or [])
        if isinstance(item, dict) and str(item.get("term") or "").strip()
    ]
    return {
        "remote_post_id": _extract_public_feed_post_id(entry),
        "title": _feed_text(entry.get("title")) or "Untitled",
        "url": _extract_public_feed_url(entry),
        "status": "live",
        "published_at": _parse_google_datetime(_feed_text(entry.get("published"))),
        "updated_at_remote": _parse_google_datetime(_feed_text(entry.get("updated"))),
        "labels": labels,
        "author_display_name": _feed_text(author.get("name")) or None,
        "replies_total_items": 0,
        "content_html": content_html,
        "thumbnail_url": _extract_thumbnail_url(content_html),
        "excerpt_text": _extract_excerpt_text(content_html),
    }


def fetch_public_blogger_posts(blog_url: str) -> list[dict]:
    feed_url = _build_public_feed_url(blog_url)
    posts: list[dict] = []
    start_index = 1
    total_results: int | None = None

    with httpx.Client(follow_redirects=True, timeout=20.0) as client:
        while True:
            response = client.get(
                feed_url,
                params={
                    "alt": "json",
                    "start-index": start_index,
                    "max-results": BLOGGER_PUBLIC_FEED_MAX_RESULTS,
                },
            )
            response.raise_for_status()
            payload = response.json()
            feed = payload.get("feed") if isinstance(payload, dict) else {}
            if not isinstance(feed, dict):
                break
            if total_results is None:
                total_results = int(_feed_text(feed.get("openSearch$totalResults")) or 0)
            entries = feed.get("entry") or []
            if not isinstance(entries, list) or not entries:
                break
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                normalized = _normalize_public_feed_post(entry)
                if normalized["remote_post_id"]:
                    posts.append(normalized)
            start_index += len(entries)
            if len(entries) < BLOGGER_PUBLIC_FEED_MAX_RESULTS:
                break
            if total_results is not None and start_index > total_results:
                break

    return posts


def _should_fallback_to_public_feed(exc: BloggerOAuthError) -> bool:
    detail = str(exc.detail or "").strip().lower()
    if int(exc.status_code or 0) in {401, 403, 404}:
        return True
    return "project" in detail or "deleted" in detail or "access not configured" in detail


def fetch_all_live_blogger_posts(db: Session, remote_blog_id: str) -> list[dict]:
    posts: list[dict] = []
    page_token: str | None = None

    while True:
        params: list[tuple[str, str]] = [
            ("fetchBodies", "true"),
            ("view", "ADMIN"),
            ("sortBy", "UPDATED"),
            ("maxResults", "50"),
            ("status", "live"),
        ]
        if page_token:
            params.append(("pageToken", page_token))

        response = authorized_google_request(
            db,
            "GET",
            BLOGGER_POSTS_URL.format(blog_id=remote_blog_id),
            params=params,
        )
        if not response.is_success:
            _raise_sync_error(response, "Failed to sync live Blogger posts.")

        payload = response.json()
        items = payload.get("items", []) or []
        for item in items:
            normalized = _normalize_remote_post(item)
            if normalized["remote_post_id"]:
                posts.append(normalized)

        page_token = payload.get("nextPageToken")
        if not page_token:
            break

    return posts


def sync_blogger_posts_for_blog(db: Session, blog: Blog) -> dict:
    if not (blog.blogger_blog_id or "").strip() and not (blog.blogger_url or "").strip():
        raise ValueError("Blogger sync requires either a remote blog id or a public blog URL.")

    try:
        used_public_feed = False
        if (blog.blogger_blog_id or "").strip():
            try:
                remote_posts = fetch_all_live_blogger_posts(db, blog.blogger_blog_id or "")
            except BloggerOAuthError as exc:
                if not (blog.blogger_url or "").strip() or not _should_fallback_to_public_feed(exc):
                    raise
                logger.warning(
                    "Falling back to public Blogger feed for '%s' because API sync failed: %s",
                    blog.name,
                    exc.detail or exc,
                )
                remote_posts = fetch_public_blogger_posts(blog.blogger_url or "")
                used_public_feed = True
        else:
            remote_posts = fetch_public_blogger_posts(blog.blogger_url or "")
            used_public_feed = True

        existing_posts = db.execute(select(SyncedBloggerPost).where(SyncedBloggerPost.blog_id == blog.id)).scalars().all()
        existing_by_remote_id = {post.remote_post_id: post for post in existing_posts}
        remote_ids: list[str] = []
        now = datetime.now(timezone.utc)
        with httpx.Client(follow_redirects=True, timeout=15.0) as http_client:
            for payload in remote_posts:
                remote_post_id = payload["remote_post_id"]
                remote_ids.append(remote_post_id)
                post = existing_by_remote_id.get(remote_post_id)
                if post is None:
                    post = SyncedBloggerPost(blog_id=blog.id, remote_post_id=remote_post_id)
                    db.add(post)

                post.title = payload["title"]
                post.url = payload["url"]
                post.status = payload["status"]
                post.published_at = payload["published_at"]
                post.updated_at_remote = payload["updated_at_remote"]
                post.labels = payload["labels"]
                post.author_display_name = payload["author_display_name"]
                post.replies_total_items = payload["replies_total_items"]
                post.content_html = payload["content_html"]
                post.thumbnail_url = payload["thumbnail_url"]
                post.excerpt_text = payload["excerpt_text"]
                post.synced_at = now

                audit = fetch_and_audit_blogger_post(post.url, client=http_client)
                post.live_image_count = audit.live_image_count
                post.live_cover_present = audit.live_cover_present
                post.live_inline_present = audit.live_inline_present
                post.live_image_issue = audit.live_image_issue
                post.live_image_audited_at = now if audit.live_image_count is not None else None

        if remote_ids:
            db.execute(
                delete(SyncedBloggerPost).where(
                    SyncedBloggerPost.blog_id == blog.id,
                    SyncedBloggerPost.remote_post_id.not_in(remote_ids),
                )
            )
        else:
            db.execute(delete(SyncedBloggerPost).where(SyncedBloggerPost.blog_id == blog.id))

        db.commit()
        rebuild_topic_memories_for_blog(db, blog)
        from app.services.analytics_service import sync_synced_post_facts_for_blog

        sync_synced_post_facts_for_blog(db, blog.id)
        return {
            "blog_id": blog.id,
            "count": len(remote_posts),
            "last_synced_at": now,
            "source": "public_feed" if used_public_feed else "blogger_api",
        }
    except Exception:
        db.rollback()
        raise


def sync_connected_blogger_posts(db: Session) -> list[str]:
    warnings: list[str] = []
    blogs = db.execute(
        select(Blog).where(Blog.blogger_blog_id.is_not(None)).order_by(Blog.id.asc())
    ).scalars().all()

    for blog in blogs:
        if not (blog.blogger_blog_id or "").strip():
            continue
        try:
            sync_blogger_posts_for_blog(db, blog)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            message = f"{blog.name}: {exc}"
            warnings.append(message)
            logger.warning("Failed to sync Blogger posts for connected blog '%s': %s", blog.name, exc)

    return warnings


def list_synced_blogger_posts_page(db: Session, blog: Blog, *, page: int = 1, page_size: int = 50) -> dict:
    resolved_page = max(page, 1)
    resolved_page_size = max(1, min(page_size, 100))
    offset = (resolved_page - 1) * resolved_page_size

    base_query = select(SyncedBloggerPost).where(SyncedBloggerPost.blog_id == blog.id)
    ordered_query = base_query.order_by(
        SyncedBloggerPost.published_at.desc().nullslast(),
        SyncedBloggerPost.updated_at_remote.desc().nullslast(),
        SyncedBloggerPost.id.desc(),
    )

    items = db.execute(ordered_query.offset(offset).limit(resolved_page_size)).scalars().all()
    total = db.execute(
        select(func.count(SyncedBloggerPost.id)).where(SyncedBloggerPost.blog_id == blog.id)
    ).scalar_one()
    last_synced_at = db.execute(
        select(func.max(SyncedBloggerPost.synced_at)).where(SyncedBloggerPost.blog_id == blog.id)
    ).scalar_one()

    return {
        "items": items,
        "total": int(total or 0),
        "page": resolved_page,
        "page_size": resolved_page_size,
        "last_synced_at": last_synced_at,
    }


def list_recent_synced_blogger_posts(db: Session, blog: Blog, *, limit: int = 10) -> list[SyncedBloggerPost]:
    resolved_limit = max(1, min(limit, 25))
    return (
        db.execute(
            select(SyncedBloggerPost)
            .where(SyncedBloggerPost.blog_id == blog.id)
            .order_by(
                SyncedBloggerPost.published_at.desc().nullslast(),
                SyncedBloggerPost.updated_at_remote.desc().nullslast(),
                SyncedBloggerPost.id.desc(),
            )
            .limit(resolved_limit)
        )
        .scalars()
        .all()
    )
