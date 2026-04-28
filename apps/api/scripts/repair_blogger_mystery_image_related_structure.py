from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import selectinload

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@postgres:5432/bloggent"
RUNTIME_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent")
REPORT_PATH = RUNTIME_ROOT / "storage" / "the-midnight-archives" / "repair-blogger-4image-20260427.json"
MYSTERY_BASE = "https://api.dongriarchive.com/assets/the-midnight-archives/"
LIVE_STATUSES = {"LIVE", "PUBLISHED", "live", "published"}

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get("BLOGGENT_DATABASE_URL", DEFAULT_DATABASE_URL)
if "STORAGE_ROOT" not in os.environ:
    os.environ["STORAGE_ROOT"] = str((REPO_ROOT / "storage").resolve())
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Article, Blog, BloggerPost, SyncedBloggerPost, SyncedCloudflarePost  # noqa: E402
from app.services.blogger.blogger_sync_service import sync_blogger_posts_for_blog  # noqa: E402
from app.services.providers.factory import get_blogger_provider  # noqa: E402


RELATED_RE = re.compile(
    r"<section\b[^>]*class=['\"][^'\"]*related-posts[^'\"]*['\"][^>]*>.*?</section>",
    re.IGNORECASE | re.DOTALL,
)
ASSET_RE = re.compile(
    r"https://api\.dongriarchive\.com/(?:cdn-cgi/image/[^\s\"'<>]+/https://api\.dongriarchive\.com/)?"
    r"assets/the-midnight-archives/[^\s\"'<> )]+?\.webp",
    re.IGNORECASE,
)
IMG_SRC_RE = re.compile(r"<img\b[^>]*\bsrc=['\"]([^'\"]+)['\"]", re.IGNORECASE)
FAQ_HEADING_RE = re.compile(r"(?:frequently\s+asked\s+questions|faq|자주\s*묻는\s*질문)", re.IGNORECASE)


@dataclass(slots=True)
class PostAudit:
    plain_text_length: int
    canonical_images: list[str]
    all_images: list[str]
    duplicate_sentence_ratio: float
    top_repeated_sentence_count: int
    body_h1_count: int
    faq_block_count: int
    midnight_count: int


@dataclass(slots=True)
class PlanItem:
    synced_id: int
    remote_post_id: str
    title: str
    url: str
    action: str
    reason: str
    before: dict[str, Any]
    after_expected_images: int | None = None
    hero_url: str = ""
    related_count: int = 0
    cloudflare_match_url: str = ""
    article_id: int | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair Blogger mystery posts to 1 hero + 3 related images.")
    parser.add_argument("--blog-id", type=int, required=True)
    parser.add_argument("--mode", choices=("dry-run", "apply", "verify"), default="dry-run")
    parser.add_argument("--report-path", default=str(REPORT_PATH))
    parser.add_argument("--timeout", type=float, default=20.0)
    return parser.parse_args()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def safe_str(value: Any) -> str:
    return str(value or "").strip()


def normalize_asset_url(url: str) -> str:
    marker = "https://api.dongriarchive.com/assets/"
    value = html.unescape(safe_str(url)).strip()
    if marker in value:
        return marker + value.split(marker, 1)[1]
    return value


def slugify_text(value: str) -> str:
    text = safe_str(value).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return re.sub(r"-+", "-", text).strip("-")


def slug_from_url(url: str) -> str:
    path = unquote(urlparse(url).path or "").rstrip("/")
    tail = path.rsplit("/", 1)[-1]
    if tail.endswith(".html"):
        tail = tail[:-5]
    return slugify_text(tail)


def title_tokens(value: str) -> set[str]:
    stop = {
        "the",
        "and",
        "of",
        "in",
        "a",
        "an",
        "to",
        "with",
        "what",
        "why",
        "how",
        "case",
        "mystery",
        "guide",
        "timeline",
        "review",
        "2026",
    }
    return {token for token in re.findall(r"[a-z0-9]+", safe_str(value).lower()) if len(token) > 2 and token not in stop}


def plain_text_from_html(value: str) -> str:
    soup = BeautifulSoup(value or "", "html.parser")
    return re.sub(r"\s+", " ", html.unescape(soup.get_text(" ", strip=True))).strip()


def extract_canonical_assets(value: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for match in ASSET_RE.finditer(value or ""):
        url = normalize_asset_url(match.group(0))
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def extract_img_srcs(value: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for match in IMG_SRC_RE.finditer(value or ""):
        url = html.unescape(match.group(1).strip())
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def sentence_metrics(text: str) -> tuple[float, int]:
    sentences = [
        re.sub(r"\s+", " ", item.strip().lower())
        for item in re.split(r"(?<=[.!?])\s+", text)
        if len(item.strip()) >= 45
    ]
    if not sentences:
        return 0.0, 0
    counts = Counter(sentences)
    duplicate_count = sum(count - 1 for count in counts.values() if count > 1)
    return round(duplicate_count / len(sentences), 4), max(counts.values())


def count_faq_blocks(soup: BeautifulSoup) -> int:
    count = 0
    for tag in soup.find_all(["h2", "h3", "summary"]):
        if FAQ_HEADING_RE.search(tag.get_text(" ", strip=True)):
            count += 1
    return count


def audit_html(value: str) -> PostAudit:
    soup = BeautifulSoup(value or "", "html.parser")
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", html.unescape(soup.get_text(" ", strip=True))).strip()
    midnight_boilerplate_count = 0
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "p", "div"]):
        tag_text = re.sub(r"\s+", " ", tag.get_text(" ", strip=True))
        if tag_text == "The Midnight Archives":
            midnight_boilerplate_count += 1
    ratio, top = sentence_metrics(text)
    return PostAudit(
        plain_text_length=len(text),
        canonical_images=extract_canonical_assets(value),
        all_images=extract_img_srcs(value),
        duplicate_sentence_ratio=ratio,
        top_repeated_sentence_count=top,
        body_h1_count=len(soup.find_all("h1")),
        faq_block_count=count_faq_blocks(soup),
        midnight_count=midnight_boilerplate_count,
    )


def fetch_live_html(client: httpx.Client, url: str) -> str:
    response = client.get(url)
    response.raise_for_status()
    return response.text


def choose_hero(content_html: str, cloudflare_hero: str = "") -> str:
    assets = extract_canonical_assets(content_html)
    return assets[0] if assets else cloudflare_hero


def sanitize_body_html(content_html: str, *, hero_url: str, related_posts: list[dict[str, str]]) -> str:
    source = safe_str(content_html)
    source = RELATED_RE.sub("", source)
    soup = BeautifulSoup(source, "html.parser")

    for h1 in soup.find_all("h1"):
        h1.name = "h2"

    # Keep only one visible "The Midnight Archives" boilerplate node.
    seen_midnight = False
    for tag in list(soup.find_all(["h2", "h3", "p", "div"])):
        text = re.sub(r"\s+", " ", tag.get_text(" ", strip=True))
        if text == "The Midnight Archives":
            if seen_midnight:
                tag.decompose()
            else:
                seen_midnight = True

    # Keep only the last FAQ block when multiple FAQ headings are present.
    faq_heads = [tag for tag in soup.find_all(["h2", "h3"]) if FAQ_HEADING_RE.search(tag.get_text(" ", strip=True))]
    if len(faq_heads) > 1:
        for head in faq_heads[:-1]:
            cursor = head
            while cursor is not None:
                nxt = cursor.find_next_sibling()
                cursor.decompose()
                if nxt is None or (getattr(nxt, "name", "") in {"h2", "section"}):
                    break
                cursor = nxt

    # If no main image exists, prepend one using the recovered hero.
    if hero_url and not extract_canonical_assets(str(soup)):
        figure = soup.new_tag("figure")
        figure["class"] = "mystery-hero"
        img = soup.new_tag("img", src=hero_url)
        img["alt"] = "Mystery case file collage"
        img["loading"] = "eager"
        img["decoding"] = "async"
        img["style"] = "width:100%;height:auto;border-radius:18px;"
        figure.append(img)
        if soup.body:
            soup.body.insert(0, figure)
        else:
            soup.insert(0, figure)

    related_html = build_related_html(related_posts)
    cleaned = str(soup).strip()
    return cleaned + "\n\n" + related_html


def build_related_html(related_posts: list[dict[str, str]]) -> str:
    cards: list[str] = []
    for post in related_posts[:3]:
        title = html.escape(post["title"], quote=True)
        link = html.escape(post["url"], quote=True)
        thumb = html.escape(post["thumbnail"], quote=True)
        excerpt = html.escape(post.get("excerpt") or "", quote=True)
        cards.append(
            "<a class='related-card' "
            f"href='{link}' style='display:block;text-decoration:none;color:#e2e8f0;'>"
            "<div style='border:1px solid #2a3a52;border-radius:18px;padding:14px;background:#111c2f;'>"
            f"<img src='{thumb}' alt='{title}' loading='lazy' decoding='async' "
            "style='width:100%;height:120px;object-fit:cover;border-radius:14px;' />"
            f"<h3 style='font-size:18px;margin:12px 0 8px;color:#f3f7ff;'>{title}</h3>"
            f"<p style='font-size:14px;line-height:1.7;color:#c7d3e6;'>{excerpt}</p>"
            "</div></a>"
        )
    return (
        "<section class='related-posts' style='margin-top:36px;'>"
        "<h2 style='font-size:28px;margin-bottom:16px;color:#f3f7ff;'>Related Mystery Stories</h2>"
        "<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;'>"
        + "".join(cards)
        + "</div></section>"
    )


def load_blog(db, blog_id: int) -> Blog:
    blog = db.get(Blog, blog_id)
    if blog is None:
        raise SystemExit(f"blog_not_found:{blog_id}")
    if int(blog.id) != 35:
        raise SystemExit("scope_violation: only blog_id=35 is allowed")
    return blog


def load_synced_posts(db, blog_id: int) -> list[SyncedBloggerPost]:
    return (
        db.execute(
            select(SyncedBloggerPost)
            .where(
                SyncedBloggerPost.blog_id == blog_id,
                SyncedBloggerPost.status.in_(sorted(LIVE_STATUSES)),
                SyncedBloggerPost.url.is_not(None),
            )
            .order_by(SyncedBloggerPost.published_at.asc().nullslast(), SyncedBloggerPost.id.asc())
        )
        .scalars()
        .all()
    )


def load_blogger_posts(db, blog_id: int, remote_ids: list[str]) -> dict[str, BloggerPost]:
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
    return {safe_str(row.blogger_post_id): row for row in rows}


def cloudflare_image_candidates(db) -> list[dict[str, str]]:
    cat = "미스테리아-스토리"
    rows = (
        db.execute(
            select(SyncedCloudflarePost)
            .where(
                or_(SyncedCloudflarePost.category_slug == cat, SyncedCloudflarePost.canonical_category_slug == cat),
                SyncedCloudflarePost.status.in_(sorted(LIVE_STATUSES)),
            )
            .order_by(SyncedCloudflarePost.published_at.desc().nullslast(), SyncedCloudflarePost.id.desc())
        )
        .scalars()
        .all()
    )
    candidates: list[dict[str, str]] = []
    for row in rows:
        urls = extract_canonical_assets(" ".join([safe_str(row.thumbnail_url), json.dumps(row.render_metadata or {})]))
        if not urls:
            continue
        candidates.append(
            {
                "title": safe_str(row.title),
                "url": safe_str(row.url),
                "thumbnail": urls[0],
                "slug": slug_from_url(safe_str(row.url)),
                "tokens": " ".join(sorted(title_tokens(row.title) | title_tokens(row.slug))),
            }
        )
    return candidates


def match_cloudflare_hero(post: SyncedBloggerPost, candidates: list[dict[str, str]]) -> dict[str, str] | None:
    tokens = title_tokens(post.title) | title_tokens(slug_from_url(safe_str(post.url)))
    best: tuple[int, dict[str, str]] | None = None
    for candidate in candidates:
        candidate_tokens = set(candidate.get("tokens", "").split())
        score = len(tokens & candidate_tokens)
        if score <= 1:
            continue
        if best is None or score > best[0]:
            best = (score, candidate)
    return best[1] if best else None


def related_candidates(posts: list[SyncedBloggerPost]) -> list[dict[str, str]]:
    values: list[dict[str, str]] = []
    seen: set[str] = set()
    for post in reversed(posts):
        assets = extract_canonical_assets(post.content_html or "")
        if not assets:
            continue
        url = safe_str(post.url)
        if not url or url in seen:
            continue
        seen.add(url)
        values.append(
            {
                "title": safe_str(post.title),
                "url": url,
                "thumbnail": assets[0],
                "excerpt": plain_text_from_html(post.excerpt_text or post.content_html or "")[:180],
            }
        )
    return values


def pick_related(current_url: str, candidates: list[dict[str, str]], tokens: set[str]) -> list[dict[str, str]]:
    ranked: list[tuple[int, dict[str, str]]] = []
    for candidate in candidates:
        if candidate["url"] == current_url:
            continue
        score = len(tokens & title_tokens(candidate["title"]))
        ranked.append((score, candidate))
    ranked.sort(key=lambda item: item[0], reverse=True)
    selected: list[dict[str, str]] = []
    seen: set[str] = set()
    for _score, candidate in ranked:
        if candidate["url"] in seen:
            continue
        selected.append(candidate)
        seen.add(candidate["url"])
        if len(selected) == 3:
            break
    return selected


def build_plan(db, blog_id: int, client: httpx.Client) -> tuple[list[PlanItem], dict[str, Any], list[SyncedBloggerPost]]:
    posts = load_synced_posts(db, blog_id)
    remote_ids = [safe_str(row.remote_post_id) for row in posts if safe_str(row.remote_post_id)]
    blogger_by_remote = load_blogger_posts(db, blog_id, remote_ids)
    cf_candidates = cloudflare_image_candidates(db)
    related_pool = related_candidates(posts)
    items: list[PlanItem] = []
    summary = {
        "scanned": len(posts),
        "delete_candidates": 0,
        "recover_candidates": 0,
        "related_update_candidates": 0,
        "faq_h1_cleanup_candidates": 0,
        "repeat_ge_050_candidates": 0,
        "already_ok": 0,
    }
    for post in posts:
        source_html = post.content_html or ""
        live_html = ""
        try:
            live_html = fetch_live_html(client, safe_str(post.url))
        except Exception:
            live_html = source_html
        audit = audit_html(live_html or source_html)
        content_audit = audit_html(source_html)
        remote_id = safe_str(post.remote_post_id)
        blogger_row = blogger_by_remote.get(remote_id)
        article = blogger_row.article if blogger_row is not None else None
        before = {
            "live_images": len(audit.canonical_images),
            "content_images": len(content_audit.canonical_images),
            "plain_text_length": audit.plain_text_length,
            "duplicate_sentence_ratio": audit.duplicate_sentence_ratio,
            "top_repeated_sentence_count": audit.top_repeated_sentence_count,
            "body_h1_count": content_audit.body_h1_count,
            "faq_block_count": content_audit.faq_block_count,
            "midnight_count": content_audit.midnight_count,
        }
        needs_cleanup = (
            content_audit.body_h1_count > 0
            or content_audit.faq_block_count > 1
            or content_audit.midnight_count > 1
            or audit.duplicate_sentence_ratio >= 0.50
        )
        if audit.duplicate_sentence_ratio >= 0.50:
            summary["repeat_ge_050_candidates"] += 1

        image_count = len(audit.canonical_images)
        if image_count == 0:
            if audit.duplicate_sentence_ratio >= 0.50:
                summary["delete_candidates"] += 1
                items.append(
                    PlanItem(
                        synced_id=post.id,
                        remote_post_id=remote_id,
                        title=safe_str(post.title),
                        url=safe_str(post.url),
                        action="delete",
                        reason="image_count_0_and_duplicate_sentence_ratio_ge_050",
                        before=before,
                        article_id=article.id if article else None,
                    )
                )
                continue
            match = match_cloudflare_hero(post, cf_candidates)
            if match is None:
                summary["delete_candidates"] += 1
                items.append(
                    PlanItem(
                        synced_id=post.id,
                        remote_post_id=remote_id,
                        title=safe_str(post.title),
                        url=safe_str(post.url),
                        action="delete",
                        reason="image_count_0_no_cloudflare_candidate",
                        before=before,
                        article_id=article.id if article else None,
                    )
                )
                continue
            related = pick_related(safe_str(post.url), related_pool, title_tokens(post.title))
            summary["recover_candidates"] += 1
            items.append(
                PlanItem(
                    synced_id=post.id,
                    remote_post_id=remote_id,
                    title=safe_str(post.title),
                    url=safe_str(post.url),
                    action="recover",
                    reason="image_count_0_cloudflare_candidate",
                    before=before,
                    after_expected_images=4,
                    hero_url=match["thumbnail"],
                    cloudflare_match_url=match["url"],
                    related_count=len(related),
                    article_id=article.id if article else None,
                )
            )
            continue

        if image_count != 4 or needs_cleanup:
            hero = choose_hero(source_html) or (audit.canonical_images[0] if audit.canonical_images else "")
            related = pick_related(safe_str(post.url), related_pool, title_tokens(post.title))
            if image_count != 4:
                summary["related_update_candidates"] += 1
            if needs_cleanup:
                summary["faq_h1_cleanup_candidates"] += 1
            items.append(
                PlanItem(
                    synced_id=post.id,
                    remote_post_id=remote_id,
                    title=safe_str(post.title),
                    url=safe_str(post.url),
                    action="update",
                    reason="image_count_or_html_cleanup",
                    before=before,
                    after_expected_images=4,
                    hero_url=hero,
                    related_count=len(related),
                    article_id=article.id if article else None,
                )
            )
        else:
            summary["already_ok"] += 1
    return items, summary, posts


def item_to_dict(item: PlanItem) -> dict[str, Any]:
    return {
        "synced_id": item.synced_id,
        "remote_post_id": item.remote_post_id,
        "title": item.title,
        "url": item.url,
        "action": item.action,
        "reason": item.reason,
        "before": item.before,
        "after_expected_images": item.after_expected_images,
        "hero_url": item.hero_url,
        "related_count": item.related_count,
        "cloudflare_match_url": item.cloudflare_match_url,
        "article_id": item.article_id,
    }


def apply_plan(db, blog: Blog, items: list[PlanItem], posts: list[SyncedBloggerPost]) -> dict[str, Any]:
    provider = get_blogger_provider(db, blog)
    post_by_id = {post.id: post for post in posts}
    remote_ids = [safe_str(post.remote_post_id) for post in posts if safe_str(post.remote_post_id)]
    blogger_by_remote = load_blogger_posts(db, blog.id, remote_ids)
    related_pool = related_candidates(posts)
    result = {
        "updated": 0,
        "deleted": 0,
        "failed": 0,
        "skipped_rewrite_required": 0,
        "items": [],
    }
    for item in items:
        post = post_by_id.get(item.synced_id)
        if post is None:
            result["failed"] += 1
            result["items"].append({**item_to_dict(item), "status": "failed", "error": "synced_missing"})
            continue
        remote_id = safe_str(post.remote_post_id)
        blogger_row = blogger_by_remote.get(remote_id)
        article = blogger_row.article if blogger_row is not None else None

        if item.action == "delete":
            try:
                provider.delete_post(remote_id)
                db.delete(post)
                if blogger_row is not None:
                    linked_article = blogger_row.article
                    db.delete(blogger_row)
                    if linked_article is not None:
                        db.delete(linked_article)
                db.commit()
                result["deleted"] += 1
                result["items"].append({**item_to_dict(item), "status": "deleted"})
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                result["failed"] += 1
                result["items"].append({**item_to_dict(item), "status": "failed", "error": str(exc)})
            continue

        if item.before.get("duplicate_sentence_ratio", 0.0) >= 0.50 and item.action != "delete":
            result["skipped_rewrite_required"] += 1
            result["items"].append({**item_to_dict(item), "status": "skipped_rewrite_required"})
            continue

        related = pick_related(safe_str(post.url), related_pool, title_tokens(post.title))
        if len(related) < 3:
            result["failed"] += 1
            result["items"].append({**item_to_dict(item), "status": "failed", "error": "related_candidates_lt_3"})
            continue
        hero = item.hero_url or choose_hero(post.content_html or "")
        if not hero:
            result["failed"] += 1
            result["items"].append({**item_to_dict(item), "status": "failed", "error": "hero_missing"})
            continue
        content = sanitize_body_html(post.content_html or "", hero_url=hero, related_posts=related)
        labels = list(article.labels or []) if article is not None else list(post.labels or [])
        meta = safe_str(article.meta_description if article is not None else post.excerpt_text)
        title = safe_str(article.title if article is not None else post.title) or post.title
        try:
            provider.update_post(
                post_id=remote_id,
                title=title,
                content=content,
                labels=labels,
                meta_description=meta[:300],
            )
            post.content_html = content
            post.thumbnail_url = hero
            post.synced_at = datetime.now(timezone.utc)
            db.add(post)
            if article is not None:
                article.assembled_html = content
                db.add(article)
            db.commit()
            result["updated"] += 1
            result["items"].append({**item_to_dict(item), "status": "updated"})
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            result["failed"] += 1
            result["items"].append({**item_to_dict(item), "status": "failed", "error": str(exc)})
    return result


def verify_posts(db, blog_id: int, client: httpx.Client) -> dict[str, Any]:
    posts = load_synced_posts(db, blog_id)
    distribution: dict[str, int] = {}
    failures: list[dict[str, Any]] = []
    for post in posts:
        try:
            live_html = fetch_live_html(client, safe_str(post.url))
        except Exception as exc:  # noqa: BLE001
            failures.append({"url": post.url, "title": post.title, "reason": f"fetch_failed:{exc}"})
            continue
        audit = audit_html(live_html)
        count = len(audit.canonical_images)
        distribution[str(count)] = distribution.get(str(count), 0) + 1
        problems: list[str] = []
        if count != 4:
            problems.append(f"image_count_{count}")
        if audit.body_h1_count > 1:
            problems.append(f"h1_count_{audit.body_h1_count}")
        if audit.faq_block_count > 1:
            problems.append(f"faq_count_{audit.faq_block_count}")
        if audit.duplicate_sentence_ratio >= 0.50:
            problems.append(f"duplicate_sentence_ratio_{audit.duplicate_sentence_ratio}")
        if problems:
            failures.append(
                {
                    "url": post.url,
                    "title": post.title,
                    "problems": problems,
                    "plain_text_length": audit.plain_text_length,
                    "image_count": count,
                }
            )
    return {
        "live_count": len(posts),
        "image_distribution": dict(sorted(distribution.items(), key=lambda item: int(item[0]))),
        "failure_count": len(failures),
        "failures": failures[:120],
    }


def write_report(path: str, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def main() -> int:
    args = parse_args()
    if args.blog_id != 35:
        raise SystemExit("scope_violation: only --blog-id 35 is allowed")
    report: dict[str, Any] = {"generated_at": now_iso(), "mode": args.mode, "blog_id": args.blog_id}
    with httpx.Client(follow_redirects=True, timeout=args.timeout, headers={"User-Agent": "Mozilla/5.0"}) as client:
        with SessionLocal() as db:
            blog = load_blog(db, args.blog_id)
            if args.mode in {"dry-run", "apply"}:
                items, summary, posts = build_plan(db, args.blog_id, client)
                report["plan_summary"] = summary
                report["plan_items"] = [item_to_dict(item) for item in items]
                if args.mode == "apply":
                    apply_result = apply_plan(db, blog, items, posts)
                    report["apply_result"] = apply_result
                    try:
                        sync_result = sync_blogger_posts_for_blog(db, blog)
                    except Exception as exc:  # noqa: BLE001
                        sync_result = {"status": "failed", "error": str(exc)}
                    report["sync_result"] = sync_result
                    report["verify_result"] = verify_posts(db, args.blog_id, client)
            else:
                report["verify_result"] = verify_posts(db, args.blog_id, client)
    write_report(args.report_path, report)
    print(json.dumps(report.get("verify_result") or report.get("apply_result") or report.get("plan_summary"), ensure_ascii=False, indent=2))
    print(f"report_path={args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
