from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path, PurePosixPath


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
LOCAL_STORAGE_ROOT = REPO_ROOT / "storage"
CONTAINER_STORAGE_ROOT = PurePosixPath("/app/storage")

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get(
        "BLOGGENT_DATABASE_URL",
        "postgresql://bloggent:bloggent@localhost:15432/bloggent",
    )
if "STORAGE_ROOT" not in os.environ:
    os.environ["STORAGE_ROOT"] = str(LOCAL_STORAGE_ROOT)

sys.path.insert(0, str(API_ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Article, Blog  # noqa: E402
from app.services.providers.factory import get_blogger_provider  # noqa: E402
from app.services.publishing_service import (  # noqa: E402
    rebuild_article_html,
    refresh_article_public_image,
    upsert_article_blogger_post,
)
from app.services.storage_service import save_html  # noqa: E402


def to_local_storage_path(file_path: str | None) -> str:
    normalized = (file_path or "").strip()
    if not normalized:
        return ""
    if normalized.startswith("/app/storage/"):
        relative = PurePosixPath(normalized).relative_to(CONTAINER_STORAGE_ROOT)
        return str(LOCAL_STORAGE_ROOT / Path(relative.as_posix()))
    return normalized


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh local article HTML snapshots and optionally sync rebuilt HTML to existing Blogger posts."
    )
    parser.add_argument("--blog-id", type=int, help="Target blog ID")
    parser.add_argument("--article-id", type=int, action="append", help="Target article ID. Repeat for multiple IDs.")
    parser.add_argument("--profile-key", help="Target blog profile key such as korea_travel or world_mystery")
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of articles to process")
    parser.add_argument("--offset", type=int, default=0, help="Number of articles to skip before processing")
    parser.add_argument(
        "--mode",
        choices=("snapshot", "rebuild"),
        default="rebuild",
        help="snapshot saves the current DB HTML; rebuild regenerates HTML with current assembly rules.",
    )
    parser.add_argument(
        "--sync-blogger",
        action="store_true",
        help="After rebuild, update the existing Blogger post if the article is already published.",
    )
    return parser.parse_args()


def load_articles(args: argparse.Namespace) -> list[Article]:
    with SessionLocal() as db:
        stmt = (
            select(Article)
            .options(
                selectinload(Article.blog),
                selectinload(Article.image),
                selectinload(Article.blogger_post),
            )
            .order_by(Article.created_at.desc())
        )

        if args.blog_id is not None:
            stmt = stmt.where(Article.blog_id == args.blog_id)
        if args.article_id:
            stmt = stmt.where(Article.id.in_(args.article_id))
        if args.profile_key:
            stmt = stmt.join(Blog, Blog.id == Article.blog_id).where(Blog.profile_key == args.profile_key)

        stmt = stmt.offset(max(0, int(args.offset))).limit(max(1, int(args.limit)))
        return db.execute(stmt).scalars().unique().all()


def snapshot_article(article: Article) -> tuple[bool, str]:
    html = (article.assembled_html or article.html_article or "").strip()
    if not html:
        return False, "HTML is empty; nothing to snapshot"
    save_html(slug=article.slug, html=html)
    return True, "Saved current DB HTML to local snapshot"


def sync_existing_blogger_post(article: Article) -> tuple[bool, str]:
    with SessionLocal() as db:
        article = (
            db.execute(
                select(Article)
                .where(Article.id == article.id)
                .options(
                    selectinload(Article.blog),
                    selectinload(Article.image),
                    selectinload(Article.blogger_post),
                )
            )
            .scalar_one_or_none()
        )
        if article is None:
            return False, "Article not found during Blogger sync"
        if not article.blog or not article.blogger_post:
            return True, "Local rebuild completed; no Blogger post relation to sync"

        provider = get_blogger_provider(db, article.blog)
        if not hasattr(provider, "update_post") or type(provider).__name__.startswith("Mock"):
            return True, "Local rebuild completed; live Blogger provider is not available"

        summary, raw_payload = provider.update_post(
            post_id=article.blogger_post.blogger_post_id,
            title=article.title,
            content=article.assembled_html or article.html_article or "",
            labels=list(article.labels or []),
            meta_description=article.meta_description or "",
        )
        upsert_article_blogger_post(
            db,
            article=article,
            summary=summary,
            raw_payload=raw_payload if isinstance(raw_payload, dict) else {},
        )
        return True, "Rebuilt HTML and updated existing Blogger post"


def rebuild_article(article_id: int, *, sync_blogger: bool = False) -> tuple[bool, str]:
    with SessionLocal() as db:
        article = (
            db.execute(
                select(Article)
                .where(Article.id == article_id)
                .options(
                    selectinload(Article.blog),
                    selectinload(Article.image),
                    selectinload(Article.blogger_post),
                )
            )
            .scalar_one_or_none()
        )
        if article is None:
            return False, "Article lookup failed"
        if not article.image:
            return False, "Article has no image; rebuild skipped"

        article.image.file_path = to_local_storage_path(article.image.file_path)
        hero_image_url = refresh_article_public_image(db, article) or (article.image.public_url or "")
        if not hero_image_url:
            return False, "Public image URL is missing"

        rebuild_article_html(db, article, hero_image_url)

    if not sync_blogger:
        return True, "Rebuilt HTML and saved snapshot"
    return sync_existing_blogger_post(article)


def main() -> int:
    args = parse_args()
    articles = load_articles(args)
    if not articles:
        print("No matching articles found.")
        return 0

    print(f"mode={args.mode} count={len(articles)} sync_blogger={args.sync_blogger}")
    updated = 0
    skipped = 0

    for article in articles:
        try:
            if args.mode == "snapshot":
                ok, message = snapshot_article(article)
            else:
                ok, message = rebuild_article(article.id, sync_blogger=args.sync_blogger)
        except Exception as exc:  # noqa: BLE001
            ok = False
            message = str(exc)

        status = "updated" if ok else "skipped"
        print(f"{status}\t{article.id}\t{article.slug}\t{message}")
        if ok:
            updated += 1
        else:
            skipped += 1

    print(f"updated={updated} skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
