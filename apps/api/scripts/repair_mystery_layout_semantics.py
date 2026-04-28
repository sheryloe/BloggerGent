from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@postgres:5432/bloggent"
DEFAULT_REPORT_PATH = Path(r"D:\Donggri_Runtime\BloggerGent\Rool\mystery\layout-repair-20260421.json")
MYSTERY_BLOG_ID = 35
MYSTERY_PROFILE_KEY = "world_mystery"
LIVE_STATUSES = {"LIVE", "PUBLISHED", "live", "published"}

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get("BLOGGENT_DATABASE_URL", DEFAULT_DATABASE_URL)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Article, Blog, BloggerPost, SyncedBloggerPost  # noqa: E402
from app.services.providers.factory import get_blogger_provider  # noqa: E402


ARTICLE_OPEN_RE = re.compile(r"<article\b", re.IGNORECASE)
ARTICLE_CLOSE_RE = re.compile(r"</article\s*>", re.IGNORECASE)
DIV_OPEN_RE = re.compile(r"<div\b", re.IGNORECASE)
DIV_CLOSE_RE = re.compile(r"</div\s*>", re.IGNORECASE)
H1_OPEN_RE = re.compile(r"<h1\b", re.IGNORECASE)
THEME_ASIDE_RE = re.compile(
    r"<aside\b[^>]*class=(?P<quote>['\"])[^'\"]*\bw-full\b[^'\"]*\blg:w-72\b[^'\"]*\bshrink-0\b[^'\"]*(?P=quote)[^>]*>",
    re.IGNORECASE | re.DOTALL,
)
TRAILING_CLOSE_BLOCK_RE = re.compile(r"((?:\s*</(?:article|div)\s*>)+)\s*$", re.IGNORECASE)
TRAILING_CLOSE_TAG_RE = re.compile(r"</(article|div)\s*>", re.IGNORECASE)


@dataclass(slots=True)
class StructureCounts:
    article_open: int
    article_close: int
    div_open: int
    div_close: int
    h1_open: int
    theme_sidebar: bool

    @property
    def article_extra_close(self) -> int:
        return max(0, self.article_close - self.article_open)

    @property
    def div_extra_close(self) -> int:
        return max(0, self.div_close - self.div_open)

    @property
    def structurally_bad(self) -> bool:
        return self.theme_sidebar or self.article_extra_close > 0 or self.div_extra_close > 0


@dataclass(slots=True)
class LayoutRepairResult:
    html: str
    before: StructureCounts
    after: StructureCounts
    theme_tail_removed: bool
    removed_article_closes: int
    removed_div_closes: int
    changed: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair mystery Blogger post layout wrappers.")
    parser.add_argument("--blog-id", type=int, required=True)
    parser.add_argument("--mode", choices=("dry-run", "apply", "audit"), required=True)
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--sleep-seconds", type=float, default=0.15)
    return parser.parse_args()


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def count_structure(html_value: str | None) -> StructureCounts:
    html = str(html_value or "")
    return StructureCounts(
        article_open=len(ARTICLE_OPEN_RE.findall(html)),
        article_close=len(ARTICLE_CLOSE_RE.findall(html)),
        div_open=len(DIV_OPEN_RE.findall(html)),
        div_close=len(DIV_CLOSE_RE.findall(html)),
        h1_open=len(H1_OPEN_RE.findall(html)),
        theme_sidebar=bool(THEME_ASIDE_RE.search(html)),
    )


def _strip_theme_tail(html: str) -> tuple[str, bool]:
    match = THEME_ASIDE_RE.search(html)
    if not match:
        return html, False
    return html[: match.start()].rstrip(), True


def _remove_trailing_surplus_closes(html: str) -> tuple[str, int, int]:
    counts = count_structure(html)
    article_surplus = counts.article_extra_close
    div_surplus = counts.div_extra_close
    if article_surplus <= 0 and div_surplus <= 0:
        return html, 0, 0

    block_match = TRAILING_CLOSE_BLOCK_RE.search(html)
    if not block_match:
        return html, 0, 0

    block = block_match.group(1)
    remove_spans: list[tuple[int, int]] = []
    removed_article = 0
    removed_div = 0

    for tag_match in reversed(list(TRAILING_CLOSE_TAG_RE.finditer(block))):
        tag_name = tag_match.group(1).lower()
        if tag_name == "article" and article_surplus > 0:
            remove_spans.append((tag_match.start(), tag_match.end()))
            article_surplus -= 1
            removed_article += 1
        elif tag_name == "div" and div_surplus > 0:
            remove_spans.append((tag_match.start(), tag_match.end()))
            div_surplus -= 1
            removed_div += 1

    if not remove_spans:
        return html, 0, 0

    chars = list(block)
    for start, end in remove_spans:
        for index in range(start, end):
            chars[index] = ""
    new_block = "".join(chars).rstrip()
    repaired = f"{html[: block_match.start(1)]}{new_block}{html[block_match.end(1):]}"
    return repaired.rstrip(), removed_article, removed_div


def repair_layout(html_value: str | None) -> LayoutRepairResult:
    original = str(html_value or "")
    before = count_structure(original)
    html, theme_removed = _strip_theme_tail(original)
    html, removed_article, removed_div = _remove_trailing_surplus_closes(html)
    after = count_structure(html)
    return LayoutRepairResult(
        html=html,
        before=before,
        after=after,
        theme_tail_removed=theme_removed,
        removed_article_closes=removed_article,
        removed_div_closes=removed_div,
        changed=html != original,
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


def _repair_article(article: Article | None) -> dict[str, Any] | None:
    if article is None or not _safe_str(article.assembled_html):
        return None
    result = repair_layout(article.assembled_html)
    if not result.changed:
        return {
            "article_id": article.id,
            "changed": False,
            "before": asdict(result.before),
            "after": asdict(result.after),
        }
    article.assembled_html = result.html
    return {
        "article_id": article.id,
        "changed": True,
        "before": asdict(result.before),
        "after": asdict(result.after),
        "theme_tail_removed": result.theme_tail_removed,
        "removed_article_closes": result.removed_article_closes,
        "removed_div_closes": result.removed_div_closes,
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
            "posts_structural_problem_before": 0,
            "posts_planned": 0,
            "posts_updated": 0,
            "posts_failed": 0,
            "posts_structural_problem_after": 0,
            "theme_tails_removed": 0,
            "article_closes_removed": 0,
            "div_closes_removed": 0,
            "articles_changed": 0,
        },
        "items": [],
    }


def run(db: Session, *, blog_id: int, mode: str, sleep_seconds: float) -> dict[str, Any]:
    blog = _require_mystery_blog(db, blog_id)
    posts = _load_live_posts(db, blog_id)
    blogger_by_remote = _load_blogger_posts_by_remote(db, blog_id, posts)
    provider = get_blogger_provider(db, blog) if mode == "apply" else None
    report = _base_report(mode, blog_id)
    report["summary"]["posts_scanned"] = len(posts)

    for index, post in enumerate(posts, 1):
        old_html = str(post.content_html or "")
        result = repair_layout(old_html)
        if result.before.structurally_bad:
            report["summary"]["posts_structural_problem_before"] += 1
        if result.after.structurally_bad:
            report["summary"]["posts_structural_problem_after"] += 1

        changed = result.changed
        if changed:
            report["summary"]["posts_planned"] += 1
        if result.theme_tail_removed:
            report["summary"]["theme_tails_removed"] += 1
        report["summary"]["article_closes_removed"] += result.removed_article_closes
        report["summary"]["div_closes_removed"] += result.removed_div_closes

        item = {
            "synced_post_id": post.id,
            "remote_post_id": _safe_str(post.remote_post_id),
            "url": _safe_str(post.url),
            "title": _safe_str(post.title),
            "status": "planned" if changed else "already_clean",
            "before": asdict(result.before),
            "after": asdict(result.after),
            "theme_tail_removed": result.theme_tail_removed,
            "removed_article_closes": result.removed_article_closes,
            "removed_div_closes": result.removed_div_closes,
        }

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
                article_result = _repair_article(article)
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

        if item["status"] != "already_clean" or mode == "audit":
            report["items"].append(item)

    return report


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    report_path = Path(args.report_path)
    with SessionLocal() as db:
        report = run(
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
