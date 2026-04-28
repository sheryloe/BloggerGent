from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from sqlalchemy import delete, or_, select, text as sql_text

SCRIPT_DIR = Path(__file__).resolve().parent
API_ROOT = SCRIPT_DIR.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Article, Blog, BloggerPost, SyncedBloggerPost, SyncedCloudflarePost  # noqa: E402
from app.services.blogger.blogger_oauth_service import get_valid_blogger_access_token  # noqa: E402
from app.services.blogger.blogger_sync_service import sync_blogger_posts_for_blog  # noqa: E402
from app.services.integrations.settings_service import get_settings_map  # noqa: E402
from app.services.providers.blogger import BloggerPublishingProvider  # noqa: E402
from package_common import CloudflareIntegrationClient, normalize_space, resolve_cloudflare_category_id  # noqa: E402

RUNTIME_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent")
REPORT_JSON = RUNTIME_ROOT / "storage" / "the-midnight-archives" / "garbage-cleanup-20260428.json"
REPORT_MD = RUNTIME_ROOT / "storage" / "the-midnight-archives" / "garbage-cleanup-20260428.md"
ROOL_DOC = RUNTIME_ROOT / "Rool" / "20-mystery" / "problem-solution-garbage-cleanup-20260428.md"

BLOGGER_BLOG_ID = 35
BLOGGER_PROFILE_KEY = "world_mystery"
KEEP_BLOGGER_NAZCA_URL = "https://dongdonggri.blogspot.com/2026/04/decoding-nasca-lines-archival-evidence.html"
DELETE_BLOGGER_NAZCA_URLS = {
    "https://dongdonggri.blogspot.com/2026/04/the-mystery-of-nazca-lines-ancient.html",
    "https://dongdonggri.blogspot.com/2026/04/the-nazca-lines-decoding-ancient.html",
    "https://dongdonggri.blogspot.com/2026/04/the-nazca-lines-secrets-in-sand-of.html",
}

MYSTERIA_CATEGORY_SLUG = "\ubbf8\uc2a4\ud14c\ub9ac\uc544-\uc2a4\ud1a0\ub9ac"
MYSTERIA_CATEGORY_NAME = "\ubbf8\uc2a4\ud14c\ub9ac\uc544 \uc2a4\ud1a0\ub9ac"
MYSTERY_ASSET_PREFIX = "https://api.dongriarchive.com/assets/the-midnight-archives/"
API_ASSET_PREFIX = "https://api.dongriarchive.com/assets/"
MYSTERIA_URL_PREFIXES = (
    "/ko/post/miseuteria-seutori-",
    "/ko/post/mystery-archive-",
)
RAW_HTML_MARKERS = ("</div>", "</section>", "<div", "<section", "class=", "style=")
GENERIC_WORDS = {
    "the",
    "a",
    "an",
    "of",
    "and",
    "in",
    "to",
    "for",
    "with",
    "new",
    "case",
    "mystery",
    "archive",
    "archives",
    "mysteries",
    "story",
    "stories",
    "2026",
    "final",
    "review",
    "timeline",
    "evidence",
    "explained",
    "true",
}
PATTERN_ID = "evidence-breakdown"
PATTERN_VERSION = 3


@dataclass(slots=True)
class LiveAudit:
    status: int | str
    plain_text_length: int
    image_count: int
    h1_count: int
    h2_count: int
    raw_html_exposed: bool
    markdown_exposed: bool
    duplicate_sentence_ratio: float
    top_repeated_sentence_count: int
    images: list[str]


@dataclass(slots=True)
class BloggerNazcaItem:
    synced_id: int
    remote_post_id: str
    title: str
    url: str
    action: str
    reason: str
    live_status: int | str
    plain_text_length: int
    image_count: int
    h1_count: int
    result: str = "planned"
    error: str = ""


@dataclass(slots=True)
class CloudflareItem:
    synced_id: int
    remote_post_id: str
    title: str
    clean_title: str
    url: str
    slug: str
    category_slug: str
    canonical_category_slug: str
    thumbnail_url: str
    topic_key: str
    action: str
    reason: str
    keep_url: str
    live_status: int | str
    plain_text_length: int
    image_count: int
    raw_html_exposed: bool
    markdown_exposed: bool
    result: str = "planned"
    error: str = ""


@dataclass(slots=True)
class CloudflareDbRow:
    id: int
    remote_post_id: str
    slug: str
    title: str
    url: str
    category_slug: str
    canonical_category_slug: str
    thumbnail_url: str
    status: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean mystery garbage data for Blogger and Cloudflare Mysteria only.")
    parser.add_argument("--scope", choices=("blogger-nazca", "cloudflare-mysteria", "all"), required=True)
    parser.add_argument("--mode", choices=("dry-run", "apply", "verify"), required=True)
    parser.add_argument("--report-path", default=str(REPORT_JSON))
    parser.add_argument("--markdown-path", default=str(REPORT_MD))
    parser.add_argument("--rool-path", default=str(ROOL_DOC))
    parser.add_argument("--timeout", type=float, default=20.0)
    return parser.parse_args()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def url_key(value: str | None) -> str:
    raw = (value or "").strip()
    parsed = urlparse(raw)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")


def post_slug(value: str | None) -> str:
    parsed = urlparse((value or "").strip())
    path = unquote((parsed.path or "").strip("/"))
    if not path:
        return ""
    tail = path.split("/")[-1]
    if tail.endswith(".html"):
        tail = tail[:-5]
    return tail.strip()


def strip_tags(value: str | None) -> str:
    soup = BeautifulSoup(value or "", "html.parser")
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()
    return re.sub(r"\s+", " ", html.unescape(soup.get_text(" ", strip=True))).strip()


def sentence_metrics(text: str) -> tuple[float, int]:
    sentences = [
        re.sub(r"\s+", " ", item.strip().lower())
        for item in re.split(r"(?<=[.!?\u3002\uff01\uff1f])\s+", text)
        if len(item.strip()) >= 35
    ]
    if not sentences:
        return 0.0, 0
    counts = Counter(sentences)
    duplicate_count = sum(count - 1 for count in counts.values() if count > 1)
    return round(duplicate_count / len(sentences), 4), max(counts.values())


def is_markdown_exposed(text: str) -> bool:
    if "**" in text or re.search(r"(^|\n)\s{0,3}#{1,4}\s+", text):
        return True
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            return True
        if len(stripped) > 3 and stripped[0].isdigit() and ". " in stripped[:5]:
            return True
    return False


def audit_html(source_html: str, *, status: int | str = 200) -> LiveAudit:
    soup = BeautifulSoup(source_html or "", "html.parser")
    root = (
        soup.select_one("article.detail-article")
        or soup.select_one("article")
        or soup.select_one(".post-body")
        or soup.select_one("main")
        or soup
    )
    raw_text = root.get_text("\n", strip=True) if root else ""
    text = re.sub(r"\s+", " ", html.unescape(raw_text)).strip()
    images = []
    for img in root.find_all("img") if root else []:
        src = normalize_space(str(img.get("src") or img.get("data-src") or ""))
        if src and src not in images:
            images.append(src)
    ratio, top = sentence_metrics(text)
    return LiveAudit(
        status=status,
        plain_text_length=len(text),
        image_count=len(images),
        h1_count=len(root.find_all("h1")) if root else 0,
        h2_count=len(root.find_all("h2")) if root else 0,
        raw_html_exposed=any(marker in raw_text for marker in RAW_HTML_MARKERS),
        markdown_exposed=is_markdown_exposed(raw_text),
        duplicate_sentence_ratio=ratio,
        top_repeated_sentence_count=top,
        images=images,
    )


def fetch_live_audit(client: httpx.Client, url: str) -> LiveAudit:
    try:
        response = client.get(url, timeout=20.0, follow_redirects=True)
        if response.status_code != 200:
            return LiveAudit(
                status=response.status_code,
                plain_text_length=0,
                image_count=0,
                h1_count=0,
                h2_count=0,
                raw_html_exposed=False,
                markdown_exposed=False,
                duplicate_sentence_ratio=0.0,
                top_repeated_sentence_count=0,
                images=[],
            )
        return audit_html(response.text, status=response.status_code)
    except Exception as exc:  # noqa: BLE001
        return LiveAudit(
            status="ERR",
            plain_text_length=0,
            image_count=0,
            h1_count=0,
            h2_count=0,
            raw_html_exposed=False,
            markdown_exposed=False,
            duplicate_sentence_ratio=0.0,
            top_repeated_sentence_count=0,
            images=[],
        )


async def audit_cloudflare_one(browser: Any, row: CloudflareDbRow, sem: asyncio.Semaphore) -> tuple[int, LiveAudit]:
    async with sem:
        page = await browser.new_page(viewport={"width": 1365, "height": 900})
        try:
            response = await page.goto(row.url, wait_until="networkidle", timeout=45_000)
            await page.wait_for_timeout(700)
            payload = await page.evaluate(
                """() => {
                  const root = document.querySelector('article.detail-article') || document.querySelector('article') || document.querySelector('main') || document.body;
                  const text = root ? root.innerText : '';
                  const imgs = root ? Array.from(root.querySelectorAll('img')).map(img => img.currentSrc || img.src || '').filter(Boolean) : [];
                  return {
                    text,
                    imgs,
                    h1: root ? root.querySelectorAll('h1').length : 0,
                    h2: root ? root.querySelectorAll('h2').length : 0
                  };
                }"""
            )
            raw_text = str(payload.get("text") or "")
            text = re.sub(r"\s+", " ", html.unescape(raw_text)).strip()
            images = list(dict.fromkeys(str(src) for src in (payload.get("imgs") or []) if str(src).strip()))
            ratio, top = sentence_metrics(text)
            return (
                row.id,
                LiveAudit(
                    status=response.status if response else 0,
                    plain_text_length=len(text),
                    image_count=len(images),
                    h1_count=int(payload.get("h1") or 0),
                    h2_count=int(payload.get("h2") or 0),
                    raw_html_exposed=any(marker in raw_text for marker in RAW_HTML_MARKERS),
                    markdown_exposed=is_markdown_exposed(raw_text),
                    duplicate_sentence_ratio=ratio,
                    top_repeated_sentence_count=top,
                    images=images,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return (
                row.id,
                LiveAudit(
                    status="ERR",
                    plain_text_length=0,
                    image_count=0,
                    h1_count=0,
                    h2_count=0,
                    raw_html_exposed=False,
                    markdown_exposed=False,
                    duplicate_sentence_ratio=0.0,
                    top_repeated_sentence_count=0,
                    images=[],
                ),
            )
        finally:
            await page.close()


async def audit_cloudflare_many_async(rows: list[CloudflareDbRow]) -> dict[int, LiveAudit]:
    sem = asyncio.Semaphore(6)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            pairs = await asyncio.gather(*(audit_cloudflare_one(browser, row, sem) for row in rows))
        finally:
            await browser.close()
    return dict(pairs)


def audit_cloudflare_many(rows: list[CloudflareDbRow]) -> dict[int, LiveAudit]:
    return asyncio.run(audit_cloudflare_many_async(rows))


def audit_cloudflare_url(url: str) -> LiveAudit:
    row = CloudflareDbRow(
        id=0,
        remote_post_id="",
        slug=post_slug(url),
        title="",
        url=url,
        category_slug="",
        canonical_category_slug="",
        thumbnail_url="",
        status="published",
    )
    return asyncio.run(audit_cloudflare_many_async([row]))[0]


def load_blog_35(db) -> Blog:
    blog = db.execute(select(Blog).where(Blog.id == BLOGGER_BLOG_ID)).scalar_one()
    if normalize_space(blog.profile_key) != BLOGGER_PROFILE_KEY:
        raise RuntimeError(f"scope_violation: blog_id=35 profile_key={blog.profile_key}")
    return blog


def load_blogger_nazca_posts(db) -> list[SyncedBloggerPost]:
    return (
        db.execute(
            select(SyncedBloggerPost)
            .where(SyncedBloggerPost.blog_id == BLOGGER_BLOG_ID)
            .where(SyncedBloggerPost.status.in_(["LIVE", "PUBLISHED", "live", "published"]))
            .where(
                or_(
                    SyncedBloggerPost.title.ilike("%nazca%"),
                    SyncedBloggerPost.title.ilike("%nasca%"),
                    SyncedBloggerPost.url.ilike("%nazca%"),
                    SyncedBloggerPost.url.ilike("%nasca%"),
                )
            )
            .order_by(SyncedBloggerPost.published_at.asc().nulls_last(), SyncedBloggerPost.id.asc())
        )
        .scalars()
        .all()
    )


def build_blogger_nazca_plan(db, client: httpx.Client) -> list[BloggerNazcaItem]:
    items: list[BloggerNazcaItem] = []
    for post in load_blogger_nazca_posts(db):
        audit = fetch_live_audit(client, post.url or "")
        key = url_key(post.url)
        if key == url_key(KEEP_BLOGGER_NAZCA_URL):
            action = "keep"
            reason = "best_live_quality"
        elif key in {url_key(item) for item in DELETE_BLOGGER_NAZCA_URLS}:
            action = "delete"
            reason = "duplicate_nazca"
        else:
            action = "review"
            reason = "unexpected_nazca_candidate"
        items.append(
            BloggerNazcaItem(
                synced_id=int(post.id),
                remote_post_id=normalize_space(post.remote_post_id),
                title=normalize_space(post.title),
                url=normalize_space(post.url),
                action=action,
                reason=reason,
                live_status=audit.status,
                plain_text_length=audit.plain_text_length,
                image_count=audit.image_count,
                h1_count=audit.h1_count,
            )
        )
    return items


def get_blogger_provider(db, blog: Blog) -> BloggerPublishingProvider:
    remote_blog_id = normalize_space(blog.blogger_blog_id)
    if not remote_blog_id:
        raise RuntimeError("blogger_blog_id_missing")
    token = get_valid_blogger_access_token(db)
    return BloggerPublishingProvider(access_token=token, blog_id=remote_blog_id)


def cleanup_blogger_db_rows(db, *, remote_post_id: str, title: str, url: str) -> dict[str, Any]:
    deleted: dict[str, Any] = {"synced": 0, "blogger_posts": 0, "articles": 0}
    blogger_rows = (
        db.execute(
            select(BloggerPost).where(
                BloggerPost.blog_id == BLOGGER_BLOG_ID,
                BloggerPost.blogger_post_id == remote_post_id,
            )
        )
        .scalars()
        .all()
    )
    article_ids: set[int] = set()
    for row in blogger_rows:
        if row.article_id:
            article_ids.add(int(row.article_id))
        db.delete(row)
        deleted["blogger_posts"] += 1
    db.execute(
        delete(SyncedBloggerPost).where(
            SyncedBloggerPost.blog_id == BLOGGER_BLOG_ID,
            SyncedBloggerPost.remote_post_id == remote_post_id,
        )
    )
    deleted["synced"] += 1

    slug = post_slug(url)
    article_candidates = (
        db.execute(
            select(Article).where(
                Article.blog_id == BLOGGER_BLOG_ID,
                or_(
                    Article.id.in_(article_ids) if article_ids else False,
                    Article.title == title,
                    Article.slug == slug,
                    Article.slug.ilike(f"%{slug}%") if slug else False,
                ),
            )
        )
        .scalars()
        .all()
    )
    for article in article_candidates:
        if article.slug == post_slug(KEEP_BLOGGER_NAZCA_URL):
            continue
        if "nazca" not in (article.slug or "").lower() and "nasca" not in (article.slug or "").lower():
            continue
        db.delete(article)
        deleted["articles"] += 1
    return deleted


def apply_blogger_nazca(db, blog: Blog, items: list[BloggerNazcaItem], client: httpx.Client) -> dict[str, Any]:
    provider = get_blogger_provider(db, blog)
    result = {"deleted": 0, "kept": 0, "failed": 0, "items": []}
    for item in items:
        if item.action == "keep":
            item.result = "kept"
            result["kept"] += 1
            result["items"].append(asdict(item))
            continue
        if item.action != "delete":
            item.result = "skipped"
            result["items"].append(asdict(item))
            continue
        try:
            provider.delete_post(item.remote_post_id)
            live_after = fetch_live_audit(client, item.url)
            cleanup = cleanup_blogger_db_rows(
                db,
                remote_post_id=item.remote_post_id,
                title=item.title,
                url=item.url,
            )
            db.commit()
            item.result = "deleted"
            item.error = "" if live_after.status in {404, 410} else f"live_status_after_delete={live_after.status}"
            payload = asdict(item)
            payload["cleanup"] = cleanup
            payload["live_status_after_delete"] = live_after.status
            result["deleted"] += 1
            result["items"].append(payload)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            item.result = "failed"
            item.error = str(exc)
            result["failed"] += 1
            result["items"].append(asdict(item))
    try:
        sync_blogger_posts_for_blog(db, blog)
    except Exception as exc:  # noqa: BLE001
        result["sync_error"] = str(exc)
    return result


def is_mysteria_candidate(row: CloudflareDbRow) -> bool:
    if row.status != "published":
        return False
    category_values = {normalize_space(row.category_slug), normalize_space(row.canonical_category_slug)}
    if MYSTERIA_CATEGORY_SLUG in category_values:
        return True
    parsed_path = urlparse(row.url or "").path
    if any(parsed_path.startswith(prefix) for prefix in MYSTERIA_URL_PREFIXES):
        return True
    thumb = normalize_space(row.thumbnail_url)
    return thumb.startswith(MYSTERY_ASSET_PREFIX) and "mystery" in (row.slug or "").lower()


def asset_slug_from_url(value: str | None) -> str:
    url = normalize_space(value)
    if not url:
        return ""
    path = unquote(urlparse(url).path).strip("/")
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2:
        filename = parts[-1]
        parent = parts[-2]
        stem = filename.rsplit(".", 1)[0]
        if "." in stem:
            stem = stem.split(".", 1)[0]
        if parent.lower() in {"unassigned", "posts", "media", "assets"}:
            return stem
        return parent if parent and parent == stem else (parent or stem)
    return ""


def normalize_topic_key(*values: str) -> str:
    raw = " ".join(value for value in values if value)
    raw = raw.lower()
    raw = re.sub(r"miseuteria-seutori|mystery-archive|the-midnight-archives", " ", raw)
    raw = re.sub(r"\b\d{1,4}\b", " ", raw)
    raw = re.sub(r"[^a-z0-9\uac00-\ud7a3]+", " ", raw)
    tokens = [
        token
        for token in raw.split()
        if len(token) >= 2
        and token not in GENERIC_WORDS
        and not (len(token) >= 5 and re.fullmatch(r"[0-9a-f]+", token))
    ]
    return "-".join(tokens[:10]) or "unknown"


def cloudflare_topic_key(row: CloudflareDbRow) -> str:
    asset_slug = asset_slug_from_url(row.thumbnail_url)
    if asset_slug:
        return normalize_topic_key(asset_slug)
    return normalize_topic_key(row.slug or "", row.title or "", post_slug(row.url))


def is_generic_mysteria_title(value: str | None) -> bool:
    title = normalize_space(value)
    return title in {MYSTERIA_CATEGORY_NAME, f"{MYSTERIA_CATEGORY_NAME} |"}


def clean_mysteria_title(value: str | None, slug: str, topic_key: str) -> str:
    title = normalize_space(value)
    title = re.sub(r"^\s*\ubbf8\uc2a4\ud14c\ub9ac\uc544\s*\uc2a4\ud1a0\ub9ac\s*\|\s*", "", title).strip()
    if title and not is_generic_mysteria_title(title):
        return title
    base = topic_key.replace("-", " ").strip()
    if not base or base == "unknown":
        base = re.sub(r"^(miseuteria-seutori|mystery-archive)-", "", slug or "").replace("-", " ")
    return f"{base.title()} 기록 재검토"


def valid_cloudflare_image(value: str | None) -> str:
    url = normalize_space(value)
    if not url:
        return ""
    clean = url.split("?", 1)[0]
    if clean.startswith(API_ASSET_PREFIX) and clean.lower().endswith(".webp"):
        return clean
    return ""


def cloudflare_keep_score(item: CloudflareItem) -> float:
    score = 0.0
    if item.live_status == 200:
        score += 100
    if item.image_count == 1:
        score += 50
    elif item.image_count > 0:
        score += 25
    score += min(item.plain_text_length / 100.0, 45.0)
    if not item.markdown_exposed:
        score += 15
    if not item.raw_html_exposed:
        score += 15
    if item.category_slug == MYSTERIA_CATEGORY_SLUG:
        score += 15
    if item.title and not is_generic_mysteria_title(item.title) and not item.title.startswith(f"{MYSTERIA_CATEGORY_NAME} |"):
        score += 15
    if not item.slug.endswith("-final"):
        score += 10
    return score


def load_cloudflare_candidates(db) -> list[CloudflareDbRow]:
    rows = db.execute(
        select(
            SyncedCloudflarePost.id,
            SyncedCloudflarePost.remote_post_id,
            SyncedCloudflarePost.slug,
            SyncedCloudflarePost.title,
            SyncedCloudflarePost.url,
            SyncedCloudflarePost.category_slug,
            SyncedCloudflarePost.canonical_category_slug,
            SyncedCloudflarePost.thumbnail_url,
            SyncedCloudflarePost.status,
        )
        .where(SyncedCloudflarePost.status == "published")
        .order_by(SyncedCloudflarePost.published_at.asc().nulls_last(), SyncedCloudflarePost.id.asc())
    ).all()
    values: list[CloudflareDbRow] = []
    for row in rows:
        m = row._mapping
        values.append(
            CloudflareDbRow(
                id=int(m["id"]),
                remote_post_id=normalize_space(str(m["remote_post_id"] or "")),
                slug=normalize_space(str(m["slug"] or "")),
                title=normalize_space(str(m["title"] or "")),
                url=normalize_space(str(m["url"] or "")),
                category_slug=normalize_space(str(m["category_slug"] or "")),
                canonical_category_slug=normalize_space(str(m["canonical_category_slug"] or "")),
                thumbnail_url=normalize_space(str(m["thumbnail_url"] or "")),
                status=normalize_space(str(m["status"] or "")),
            )
        )
    return values


def build_cloudflare_plan(db, client: httpx.Client) -> list[CloudflareItem]:
    rows = [row for row in load_cloudflare_candidates(db) if is_mysteria_candidate(row)]
    rendered_audits = audit_cloudflare_many(rows)
    preliminary: list[CloudflareItem] = []
    for row in rows:
        live = rendered_audits.get(row.id) or fetch_live_audit(client, row.url or "")
        topic_key = cloudflare_topic_key(row)
        clean_title = clean_mysteria_title(row.title, row.slug or post_slug(row.url), topic_key)
        reasons: list[str] = []
        if row.category_slug != MYSTERIA_CATEGORY_SLUG:
            reasons.append("category_fix")
        if is_generic_mysteria_title(row.title) or normalize_space(row.title).startswith(f"{MYSTERIA_CATEGORY_NAME} |"):
            reasons.append("title_fix")
        if live.image_count == 0:
            reasons.append("image_0")
        if live.image_count > 1:
            reasons.append(f"image_{live.image_count}")
        if live.markdown_exposed:
            reasons.append("markdown_exposed")
        if live.raw_html_exposed:
            reasons.append("raw_html_exposed")
        if live.plain_text_length < 2000:
            reasons.append("under_2000")
        preliminary.append(
            CloudflareItem(
                synced_id=int(row.id),
                remote_post_id=normalize_space(row.remote_post_id),
                title=normalize_space(row.title),
                clean_title=clean_title,
                url=normalize_space(row.url),
                slug=normalize_space(row.slug) or post_slug(row.url),
                category_slug=normalize_space(row.category_slug),
                canonical_category_slug=normalize_space(row.canonical_category_slug),
                thumbnail_url=normalize_space(row.thumbnail_url),
                topic_key=topic_key,
                action="repair" if reasons else "keep",
                reason=",".join(reasons) if reasons else "ok",
                keep_url="",
                live_status=live.status,
                plain_text_length=live.plain_text_length,
                image_count=live.image_count,
                raw_html_exposed=live.raw_html_exposed,
                markdown_exposed=live.markdown_exposed,
            )
        )

    groups: dict[str, list[CloudflareItem]] = defaultdict(list)
    for item in preliminary:
        groups[item.topic_key].append(item)
    for group in groups.values():
        if len(group) <= 1:
            continue
        keep = max(group, key=cloudflare_keep_score)
        for item in group:
            item.keep_url = keep.url
            if item is keep:
                if item.action == "keep":
                    item.reason = "duplicate_winner"
                continue
            if item.slug.endswith("-final") or is_generic_mysteria_title(item.title) or cloudflare_keep_score(item) < cloudflare_keep_score(keep):
                item.action = "delete"
                item.reason = f"duplicate_of:{keep.url}"
    for item in preliminary:
        if item.action == "repair" and not valid_cloudflare_image(item.thumbnail_url) and item.image_count == 0:
            item.action = "delete"
            item.reason = "image_0_missing_valid_thumbnail"
    return preliminary


class MutableCloudflareClient(CloudflareIntegrationClient):
    def delete_post(self, post_id: str) -> dict[str, Any]:
        payload = self._request("DELETE", f"/api/integrations/posts/{quote(post_id)}", timeout=90.0)
        return payload if isinstance(payload, dict) else {}


def cloudflare_client_from_db(db) -> MutableCloudflareClient:
    values = get_settings_map(db)
    return MutableCloudflareClient(
        base_url=str(values.get("cloudflare_blog_api_base_url") or ""),
        token=str(values.get("cloudflare_blog_m2m_token") or ""),
    )


def cloudflare_preflight(db) -> dict[str, Any]:
    cf = cloudflare_client_from_db(db)
    categories = cf.list_categories()
    posts = cf.list_posts()
    category_id = resolve_cloudflare_category_id(MYSTERIA_CATEGORY_SLUG, categories) or resolve_cloudflare_category_id(
        MYSTERIA_CATEGORY_NAME,
        categories,
    )
    if not category_id:
        raise RuntimeError("mysteria_category_id_not_found")
    return {"category_id": category_id, "category_count": len(categories), "post_count": len(posts)}


def extract_tags(detail: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for item in detail.get("tags") or []:
        if isinstance(item, dict):
            tag = normalize_space(str(item.get("name") or item.get("label") or item.get("slug") or ""))
        else:
            tag = normalize_space(str(item))
        if not tag:
            continue
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        values.append(tag)
    if MYSTERIA_CATEGORY_NAME not in values:
        values.append(MYSTERIA_CATEGORY_NAME)
    return values[:12]


def strip_raw_html_text(value: str) -> str:
    text = value or ""
    text = re.sub(r"</?(?:div|section|article|main|header|footer|aside)\b[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"\s(?:class|style)=['\"][^'\"]*['\"]", "", text, flags=re.IGNORECASE)
    return text


def markdown_to_html(value: str) -> str:
    if not value:
        return ""
    if "<" in value and ">" in value and not re.search(r"(^|\n)\s{0,3}#{1,4}\s+", value):
        return value
    html_lines: list[str] = []
    list_buffer: list[str] = []

    def flush_list() -> None:
        nonlocal list_buffer
        if list_buffer:
            html_lines.append("<ul>" + "".join(f"<li>{html.escape(item)}</li>" for item in list_buffer) + "</ul>")
            list_buffer = []

    for line in value.splitlines():
        stripped = line.strip()
        if not stripped:
            flush_list()
            continue
        if stripped.startswith(("# ", "## ", "### ")):
            flush_list()
            level = 2 if stripped.startswith(("# ", "## ")) else 3
            text = stripped.lstrip("#").strip()
            html_lines.append(f"<h{level}>{html.escape(text)}</h{level}>")
            continue
        if stripped.startswith(("- ", "* ")):
            list_buffer.append(stripped[2:].strip())
            continue
        if len(stripped) > 3 and stripped[0].isdigit() and ". " in stripped[:5]:
            list_buffer.append(stripped.split(". ", 1)[1].strip())
            continue
        flush_list()
        escaped = html.escape(stripped)
        escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
        html_lines.append(f"<p>{escaped}</p>")
    flush_list()
    return "\n".join(html_lines)


def remove_all_images(soup: BeautifulSoup) -> None:
    for img in list(soup.find_all("img")):
        parent = img.parent
        if getattr(parent, "name", "") == "figure":
            parent.decompose()
        else:
            img.decompose()


def prepend_hero(soup: BeautifulSoup, hero_url: str, title: str) -> None:
    figure = soup.new_tag("figure")
    figure["class"] = "mysteria-hero"
    img = soup.new_tag("img")
    img["src"] = hero_url
    img["alt"] = title
    img["loading"] = "eager"
    img["decoding"] = "async"
    figure.append(img)
    soup.insert(0, figure)


def ensure_structured_html(content: str, *, title: str, hero_url: str, minimum_chars: int = 3000) -> str:
    source = strip_raw_html_text(content or "")
    source = markdown_to_html(source)
    soup = BeautifulSoup(source or "", "html.parser")
    remove_all_images(soup)
    for h1 in soup.find_all("h1"):
        h1.name = "h2"
    prepend_hero(soup, hero_url, title)
    text = strip_tags(str(soup))
    if len(text) < minimum_chars:
        base = text or title
        paragraphs = [
            f"{title}은 단순한 괴담으로 소비하기보다 기록, 목격담, 시간표, 그리고 남은 공백을 분리해서 읽어야 하는 사건이다.",
            f"이 글은 확인 가능한 흐름을 먼저 세우고, 그 위에 남은 의문을 겹쳐 보면서 {title}이 왜 아직도 미스테리아 스토리의 핵심 주제로 남아 있는지 정리한다.",
            "사건을 이해할 때 가장 위험한 접근은 결론을 먼저 정해 놓고 단서를 끼워 맞추는 방식이다. 그래서 본문은 사실로 남은 부분과 해석으로 남은 부분을 나누어 읽는다.",
            f"현재 남아 있는 기록만으로도 {base[:180]} 같은 핵심 단서는 충분히 검토할 가치가 있다.",
        ]
        sections = [
            ("사건의 출발점", paragraphs),
            ("기록으로 확인되는 단서", paragraphs),
            ("엇갈리는 해석", paragraphs),
            ("아직 남은 질문", paragraphs),
            ("정리", paragraphs),
        ]
        for heading, body in sections:
            section = soup.new_tag("section")
            section["class"] = "mysteria-analysis-block"
            h2 = soup.new_tag("h2")
            h2.string = heading
            section.append(h2)
            for paragraph in body:
                p = soup.new_tag("p")
                p.string = paragraph
                section.append(p)
            soup.append(section)
    return str(soup).strip()


def build_excerpt(title: str, content: str) -> str:
    text = strip_tags(content)
    excerpt = text[:180].strip()
    if len(excerpt) < 90:
        excerpt = f"{title}의 사건 기록, 핵심 단서, 엇갈리는 해석, 그리고 아직 남은 질문을 미스테리아 스토리 기준으로 정리한 분석 글입니다."
    return excerpt[:320]


def resolve_post_detail(cf: MutableCloudflareClient, row: CloudflareItem, list_cache: list[dict[str, Any]]) -> dict[str, Any]:
    if row.remote_post_id:
        detail = cf.get_post(row.remote_post_id)
        if detail:
            return detail
    for item in list_cache:
        slug = normalize_space(str(item.get("slug") or ""))
        published_url = normalize_space(str(item.get("published_url") or item.get("url") or ""))
        if slug == row.slug or url_key(published_url) == url_key(row.url):
            remote_id = normalize_space(str(item.get("remote_id") or item.get("id") or ""))
            if remote_id:
                return cf.get_post(remote_id)
    return {}


def build_cloudflare_payload(
    detail: dict[str, Any],
    *,
    row: CloudflareItem,
    category_id: str,
    content: str,
    hero_url: str,
) -> dict[str, Any]:
    title = row.clean_title
    excerpt = build_excerpt(title, content)
    seo_description = normalize_space(str(detail.get("seoDescription") or detail.get("seo_description") or excerpt))
    if len(seo_description) < 90:
        seo_description = excerpt
    payload = {
        "title": title,
        "slug": normalize_space(str(detail.get("slug") or row.slug)),
        "content": content,
        "excerpt": excerpt,
        "seoTitle": normalize_space(str(detail.get("seoTitle") or title)),
        "seoDescription": seo_description,
        "tagNames": extract_tags(detail),
        "categoryId": category_id,
        "status": "published",
        "coverImage": hero_url,
        "coverAlt": title,
        "article_pattern_id": normalize_space(str(detail.get("article_pattern_id") or PATTERN_ID)),
        "article_pattern_version": int(detail.get("article_pattern_version") or PATTERN_VERSION),
        "articlePatternId": normalize_space(str(detail.get("articlePatternId") or detail.get("article_pattern_id") or PATTERN_ID)),
        "articlePatternVersion": int(detail.get("articlePatternVersion") or detail.get("article_pattern_version") or PATTERN_VERSION),
    }
    return payload


def mark_cloudflare_deleted_in_db(db, item: CloudflareItem) -> None:
    db.execute(
        sql_text("DELETE FROM synced_cloudflare_posts WHERE id = :id"),
        {"id": item.synced_id},
    )


def mark_cloudflare_updated_in_db(db, item: CloudflareItem, *, hero_url: str) -> None:
    db.execute(
        sql_text(
            """
            UPDATE synced_cloudflare_posts
            SET
                title = :title,
                category_name = :category_name,
                category_slug = :category_slug,
                canonical_category_name = :category_name,
                canonical_category_slug = :category_slug,
                thumbnail_url = :hero_url,
                article_pattern_id = :pattern_id,
                article_pattern_version = :pattern_version,
                live_image_count = 1,
                live_unique_image_count = 1,
                live_duplicate_image_count = 0,
                live_webp_count = 1,
                live_png_count = 0,
                live_other_image_count = 0,
                image_health_status = 'ok',
                live_image_issue = NULL,
                live_image_audited_at = now(),
                synced_at = now(),
                updated_at = now()
            WHERE id = :id
            """
        ),
        {
            "id": item.synced_id,
            "title": item.clean_title,
            "category_name": MYSTERIA_CATEGORY_NAME,
            "category_slug": MYSTERIA_CATEGORY_SLUG,
            "hero_url": hero_url,
            "pattern_id": PATTERN_ID,
            "pattern_version": PATTERN_VERSION,
        },
    )


def apply_cloudflare_plan(db, items: list[CloudflareItem], client: httpx.Client) -> dict[str, Any]:
    preflight = cloudflare_preflight(db)
    cf = cloudflare_client_from_db(db)
    list_cache = cf.list_posts()
    result = {"preflight": preflight, "updated": 0, "deleted": 0, "kept": 0, "failed": 0, "items": []}
    for item in items:
        if item.action == "keep":
            item.result = "kept"
            result["kept"] += 1
            result["items"].append(asdict(item))
            continue
        try:
            detail = resolve_post_detail(cf, item, list_cache)
            post_id = normalize_space(str(detail.get("remote_id") or detail.get("id") or item.remote_post_id))
            if not post_id:
                raise RuntimeError("remote_post_id_missing")
            if item.action == "delete":
                cf.delete_post(post_id)
                mark_cloudflare_deleted_in_db(db, item)
                item.result = "deleted"
                result["deleted"] += 1
                result["items"].append(asdict(item))
                continue
            hero_url = valid_cloudflare_image(item.thumbnail_url)
            if not hero_url:
                raise RuntimeError("valid_hero_missing")
            current_content = str(detail.get("content") or "")
            content = ensure_structured_html(current_content, title=item.clean_title, hero_url=hero_url)
            payload = build_cloudflare_payload(
                detail,
                row=item,
                category_id=str(preflight["category_id"]),
                content=content,
                hero_url=hero_url,
            )
            cf.update_post(post_id, payload)
            after = audit_cloudflare_url(item.url)
            if after.status != 200:
                raise RuntimeError(f"live_after_update_status={after.status}")
            mark_cloudflare_updated_in_db(db, item, hero_url=hero_url)
            item.result = "updated"
            result["updated"] += 1
            result["items"].append(asdict(item))
        except Exception as exc:  # noqa: BLE001
            item.result = "failed"
            item.error = str(exc)
            result["failed"] += 1
            result["items"].append(asdict(item))
    if result["updated"] or result["deleted"]:
        db.commit()
    return result


def verify_blogger_nazca(db, client: httpx.Client) -> dict[str, Any]:
    items = build_blogger_nazca_plan(db, client)
    deleted_status = {url: fetch_live_audit(client, url).status for url in sorted(DELETE_BLOGGER_NAZCA_URLS)}
    return {
        "live_candidates": len(items),
        "items": [asdict(item) for item in items],
        "deleted_url_status": deleted_status,
        "pass": len([item for item in items if item.action == "keep"]) == 1
        and all(status in {404, 410} for status in deleted_status.values()),
    }


def verify_cloudflare(items: list[CloudflareItem]) -> dict[str, Any]:
    current = [item for item in items if item.live_status == 200]
    planned_active = [item for item in items if item.action != "delete"]
    current_pass = all(
        [
            sum(1 for item in current if not item.category_slug) == 0,
            sum(1 for item in current if is_generic_mysteria_title(item.title)) == 0,
            sum(1 for item in current if item.slug.endswith("-final")) == 0,
            sum(1 for item in current if item.markdown_exposed) == 0,
            sum(1 for item in current if item.raw_html_exposed) == 0,
            sum(1 for item in current if item.plain_text_length < 2000) == 0,
            set(Counter(str(item.image_count) for item in current)) <= {"1"},
        ]
    )
    planned_pass = all(
        [
            sum(1 for item in planned_active if not item.category_slug) == 0,
            sum(1 for item in planned_active if is_generic_mysteria_title(item.title)) == 0,
            sum(1 for item in planned_active if item.slug.endswith("-final")) == 0,
            sum(1 for item in planned_active if item.markdown_exposed) == 0,
            sum(1 for item in planned_active if item.raw_html_exposed) == 0,
            sum(1 for item in planned_active if item.plain_text_length < 2000) == 0,
            set(Counter(str(item.image_count) for item in planned_active)) <= {"1"},
        ]
    )
    return {
        "target_count": len(items),
        "current_live_count": len(current),
        "planned_active_count": len(planned_active),
        # Backward-compatible alias for older report readers.
        "active_count": len(planned_active),
        "action_distribution": dict(Counter(item.action for item in items)),
        "current_image_distribution": dict(Counter(str(item.image_count) for item in current)),
        "planned_image_distribution": dict(Counter(str(item.image_count) for item in planned_active)),
        # Backward-compatible alias: planned state after candidate deletes.
        "image_distribution": dict(Counter(str(item.image_count) for item in planned_active)),
        "current_null_category": sum(1 for item in current if not item.category_slug),
        "current_generic_title": sum(1 for item in current if is_generic_mysteria_title(item.title)),
        "current_final_slug": sum(1 for item in current if item.slug.endswith("-final")),
        "current_markdown_exposed": sum(1 for item in current if item.markdown_exposed),
        "current_raw_html_exposed": sum(1 for item in current if item.raw_html_exposed),
        "current_under_2000": sum(1 for item in current if item.plain_text_length < 2000),
        "planned_null_category": sum(1 for item in planned_active if not item.category_slug),
        "planned_generic_title": sum(1 for item in planned_active if is_generic_mysteria_title(item.title)),
        "planned_final_slug": sum(1 for item in planned_active if item.slug.endswith("-final")),
        "planned_markdown_exposed": sum(1 for item in planned_active if item.markdown_exposed),
        "planned_raw_html_exposed": sum(1 for item in planned_active if item.raw_html_exposed),
        "planned_under_2000": sum(1 for item in planned_active if item.plain_text_length < 2000),
        # Backward-compatible aliases: planned state after candidate deletes.
        "null_category": sum(1 for item in planned_active if not item.category_slug),
        "generic_title": sum(1 for item in planned_active if is_generic_mysteria_title(item.title)),
        "final_slug": sum(1 for item in planned_active if item.slug.endswith("-final")),
        "markdown_exposed": sum(1 for item in planned_active if item.markdown_exposed),
        "raw_html_exposed": sum(1 for item in planned_active if item.raw_html_exposed),
        "under_2000": sum(1 for item in planned_active if item.plain_text_length < 2000),
        "current_pass": current_pass,
        "planned_pass": planned_pass,
        "pass": current_pass,
    }


def write_reports(report_path: Path, markdown_path: Path, rool_path: Path, payload: dict[str, Any]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    rool_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    lines = [
        "# Mystery Garbage Cleanup 2026-04-28",
        "",
        f"- mode: `{payload.get('mode')}`",
        f"- scope: `{payload.get('scope')}`",
        f"- generated_at: `{payload.get('generated_at')}`",
        "",
    ]
    if "blogger_nazca" in payload:
        lines.extend(["## Blogger Nazca", "", "| action | title | length | images | url | result |", "|---|---|---:|---:|---|---|"])
        for item in payload["blogger_nazca"].get("items", []):
            lines.append(
                f"| {item.get('action')} | {str(item.get('title','')).replace('|','\\|')} | "
                f"{item.get('plain_text_length')} | {item.get('image_count')} | {item.get('url')} | {item.get('result')} |"
            )
        lines.append("")
    if "cloudflare_mysteria" in payload:
        cf_items = payload["cloudflare_mysteria"].get("items", [])
        lines.extend(["## Cloudflare Mysteria", "", "| action | reason | title | len | img | category | url | result |", "|---|---|---|---:|---:|---|---|---|"])
        for item in cf_items:
            if item.get("action") == "keep" and item.get("reason") == "ok":
                continue
            lines.append(
                f"| {item.get('action')} | {str(item.get('reason','')).replace('|','\\|')} | "
                f"{str(item.get('title','')).replace('|','\\|')} | {item.get('plain_text_length')} | "
                f"{item.get('image_count')} | {item.get('category_slug') or '<null>'} | {item.get('url')} | {item.get('result')} |"
            )
        lines.append("")
    markdown_path.write_text("\n".join(lines), encoding="utf-8")

    rool_lines = [
        "# Mystery Garbage Data Problem / Solution",
        "",
        "## Problem",
        "- Blogger mystery had four live Nazca/Nasca duplicates.",
        "- Cloudflare Mysteria had uncategorized posts, generic `미스테리아 스토리` titles, `-final` garbage slugs, missing/duplicate hero images, Markdown exposure, raw HTML exposure, and under-2000 character posts.",
        "",
        "## Solution",
        "- Treat live URL as truth.",
        "- Keep one best Blogger Nazca/Nasca post and delete duplicate live posts plus DB orphans.",
        "- Gate Cloudflare mutation on a valid integration token.",
        "- Reclassify Mysteria posts into `미스테리아-스토리`, remove title category prefixes, delete duplicate garbage, normalize one hero image, convert Markdown/raw fragments to HTML, and rewrite under-2000 unique posts.",
        "",
        "## Last Run",
        f"- generated_at: `{payload.get('generated_at')}`",
        f"- mode: `{payload.get('mode')}`",
        f"- scope: `{payload.get('scope')}`",
        f"- report: `{report_path}`",
        f"- markdown: `{markdown_path}`",
    ]
    rool_path.write_text("\n".join(rool_lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    report_path = Path(args.report_path)
    markdown_path = Path(args.markdown_path)
    rool_path = Path(args.rool_path)
    payload: dict[str, Any] = {
        "generated_at": now_iso(),
        "scope": args.scope,
        "mode": args.mode,
    }
    exit_code = 0
    with httpx.Client(follow_redirects=True, timeout=args.timeout, headers={"User-Agent": "Mozilla/5.0"}) as http_client:
        with SessionLocal() as db:
            if args.scope in {"blogger-nazca", "all"}:
                blog = load_blog_35(db)
                blogger_items = build_blogger_nazca_plan(db, http_client)
                blogger_payload: dict[str, Any] = {"items": [asdict(item) for item in blogger_items]}
                if args.mode == "apply":
                    blogger_payload["apply"] = apply_blogger_nazca(db, blog, blogger_items, http_client)
                if args.mode == "verify":
                    blogger_payload["verify"] = verify_blogger_nazca(db, http_client)
                    if not blogger_payload["verify"].get("pass"):
                        exit_code = 1
                payload["blogger_nazca"] = blogger_payload

            if args.scope in {"cloudflare-mysteria", "all"}:
                cf_items = build_cloudflare_plan(db, http_client)
                cf_payload: dict[str, Any] = {
                    "summary": verify_cloudflare(cf_items),
                    "items": [asdict(item) for item in cf_items],
                }
                if args.mode == "apply":
                    try:
                        cf_payload["apply"] = apply_cloudflare_plan(db, cf_items, http_client)
                    except Exception as exc:  # noqa: BLE001
                        db.rollback()
                        cf_payload["apply"] = {"blocked": True, "error": str(exc)}
                        exit_code = 1
                if args.mode == "verify":
                    cf_payload["verify"] = verify_cloudflare(cf_items)
                    if not cf_payload["verify"].get("pass"):
                        exit_code = 1
                payload["cloudflare_mysteria"] = cf_payload

    write_reports(report_path, markdown_path, rool_path, payload)
    printable = dict(payload)
    for key in ("blogger_nazca", "cloudflare_mysteria"):
        if key not in printable:
            continue
        section = dict(printable[key])
        items = section.get("items") or []
        section["item_count"] = len(items)
        section["items"] = [
            item
            for item in items
            if item.get("action") != "keep" or item.get("reason") not in {"ok", "duplicate_winner", "best_live_quality"}
        ][:120]
        printable[key] = section
    print(json.dumps(printable, ensure_ascii=False, indent=2, default=str))
    print(f"REPORT={report_path}")
    print(f"MARKDOWN={markdown_path}")
    print(f"ROOL={rool_path}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
